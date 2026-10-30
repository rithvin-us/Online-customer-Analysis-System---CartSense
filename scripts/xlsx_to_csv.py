#!/usr/bin/env python3
"""Convert a single-sheet .xlsx workbook to CSV using only the standard library.

The UCI Online Retail dataset is published as an Excel workbook. Rather than
add a spreadsheet dependency to the project for one conversion, this script
reads the parts of the OOXML package that matter: the shared string table, the
cell format table (to recognise which columns hold dates), and the worksheet
itself.

Usage:
    python3 -I scripts/xlsx_to_csv.py <input.xlsx> <output.csv>
"""

from __future__ import annotations

import csv
import datetime as dt
import sys
import zipfile
from xml.etree import ElementTree

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

# Built-in number format ids that denote a date or a time.
BUILTIN_DATE_FORMATS = set(range(14, 23)) | set(range(45, 48))

# Excel's 1900 date system counts day 1 as 1900-01-01 but also contains a
# deliberate bug: it treats 1900 as a leap year. Anchoring at 1899-12-30
# reproduces Excel's own arithmetic for every date after 1900-03-01, which
# covers every real transaction date.
EXCEL_EPOCH = dt.datetime(1899, 12, 30)


def _column_index(reference: str) -> int:
    """'C7' -> 2. Column letters are base-26 with no zero digit."""
    index = 0
    for character in reference:
        if not character.isalpha():
            break
        index = index * 26 + (ord(character.upper()) - ord("A") + 1)
    return index - 1


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        payload = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ElementTree.fromstring(payload)
    strings = []
    for item in root.findall("m:si", NS):
        # A shared string can be split into several runs; concatenate them.
        strings.append("".join(node.text or "" for node in item.iter(f"{{{NS['m']}}}t")))
    return strings


def _read_date_styles(archive: zipfile.ZipFile) -> set[int]:
    """Indexes into cellXfs whose number format renders a date."""
    try:
        payload = archive.read("xl/styles.xml")
    except KeyError:
        return set()
    root = ElementTree.fromstring(payload)

    custom_date_formats = set()
    for number_format in root.iter(f"{{{NS['m']}}}numFmt"):
        code = (number_format.get("formatCode") or "").lower()
        # Strip the colour and literal sections before looking for date tokens.
        if any(token in code for token in ("yy", "dd", "mmm", "hh", "ss")):
            custom_date_formats.add(int(number_format.get("numFmtId")))

    date_styles = set()
    cell_xfs = root.find("m:cellXfs", NS)
    if cell_xfs is None:
        return date_styles
    for position, xf in enumerate(cell_xfs.findall("m:xf", NS)):
        number_format_id = int(xf.get("numFmtId") or 0)
        if number_format_id in BUILTIN_DATE_FORMATS or number_format_id in custom_date_formats:
            date_styles.add(position)
    return date_styles


def _worksheet_name(archive: zipfile.ZipFile) -> str:
    for name in archive.namelist():
        if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
            return name
    raise SystemExit("no worksheet found in workbook")


def _serial_to_timestamp(serial: float) -> str:
    moment = EXCEL_EPOCH + dt.timedelta(days=serial)
    # The time of day is stored as a fraction of a day, so 08:26 comes back as
    # 08:25:59.999994. Round to the nearest second.
    moment += dt.timedelta(microseconds=500_000)
    return moment.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def convert(source: str, target: str) -> tuple[int, int]:
    with zipfile.ZipFile(source) as archive:
        shared_strings = _read_shared_strings(archive)
        date_styles = _read_date_styles(archive)
        sheet = _worksheet_name(archive)

        rows_written = 0
        columns = 0
        with archive.open(sheet) as stream, open(target, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            current: list[str] = []
            for event, element in ElementTree.iterparse(stream, events=("end",)):
                tag = element.tag.split("}", 1)[-1]
                if tag == "c":
                    position = _column_index(element.get("r") or "")
                    while len(current) <= position:
                        current.append("")
                    current[position] = _cell_value(element, shared_strings, date_styles)
                elif tag == "row":
                    writer.writerow(current)
                    rows_written += 1
                    columns = max(columns, len(current))
                    current = []
                    element.clear()
    return rows_written, columns


def _cell_value(element, shared_strings: list[str], date_styles: set[int]) -> str:
    cell_type = element.get("t")
    value_node = element.find("m:v", NS)

    if cell_type == "s":
        if value_node is None or value_node.text is None:
            return ""
        return shared_strings[int(value_node.text)]
    if cell_type == "inlineStr":
        inline = element.find("m:is", NS)
        if inline is None:
            return ""
        return "".join(node.text or "" for node in inline.iter(f"{{{NS['m']}}}t"))
    if cell_type == "str":
        return value_node.text if value_node is not None and value_node.text else ""
    if value_node is None or value_node.text is None:
        return ""

    raw = value_node.text
    style = int(element.get("s") or -1)
    if style in date_styles:
        try:
            return _serial_to_timestamp(float(raw))
        except ValueError:
            return raw
    # Render whole numbers without a trailing ".0" so that CustomerID stays an
    # identifier rather than becoming "17850.0".
    try:
        number = float(raw)
    except ValueError:
        return raw
    if number.is_integer():
        return str(int(number))
    return repr(number)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 64
    rows, columns = convert(argv[1], argv[2])
    print(f"wrote {rows} rows x {columns} columns to {argv[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
