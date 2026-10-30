"""File profiling and the data quality report.

This module inspects an uploaded CSV before any of it reaches HDFS. It answers
the questions a data engineer asks first: what encoding is this, what delimiter,
does the schema match, how many rows, which columns have gaps, which values do
not parse, and how many records are exact duplicates.

Scope boundary, which matters for how the product's numbers are explained:
profiling describes the *file*. It does not classify transactions and it does
not compute revenue. Record classification and every analytical figure are
produced by the Hadoop jobs; the counters they report are stored separately. The
duplicate count found here and the ``DUPLICATE_RECORDS`` counter reported by
the Hadoop validation job are computed independently and should agree, which
makes them a useful cross-check on each other.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)

EXPECTED_COLUMNS: tuple[str, ...] = (
    "InvoiceNo",
    "StockCode",
    "Description",
    "Quantity",
    "InvoiceDate",
    "UnitPrice",
    "CustomerID",
    "Country",
)

#: Declared type of each expected column, used to count values that do not fit.
EXPECTED_TYPES: dict[str, str] = {
    "InvoiceNo": "string",
    "StockCode": "string",
    "Description": "string",
    "Quantity": "integer",
    "InvoiceDate": "timestamp",
    "UnitPrice": "float",
    "CustomerID": "integer",
    "Country": "string",
}

#: Encodings tried in order. The UCI Online Retail CSV exports are usually
#: cp1252, not UTF-8, so a UTF-8-only reader would fail on real data.
CANDIDATE_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "utf-8", "cp1252", "latin-1")

#: Timestamp patterns, in the same order the Java InvoiceDateParser tries them,
#: so that a value accepted here is also accepted by the cluster.
MONTH_FIRST_PATTERNS: tuple[str, ...] = ("%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%y %H:%M", "%m/%d/%Y")
DAY_FIRST_PATTERNS: tuple[str, ...] = ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%y %H:%M", "%d/%m/%Y")
ISO_PATTERNS: tuple[str, ...] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d",
)

_SAMPLE_BYTES = 262_144
_DISTINCT_SAMPLE_LIMIT = 25


class ProfilingError(ValueError):
    """The upload cannot be profiled, so it must not be ingested."""


@dataclass(slots=True)
class ColumnProfile:
    name: str
    declared_type: str
    non_empty: int = 0
    empty: int = 0
    type_mismatches: int = 0
    distinct_sample: list[str] = field(default_factory=list)
    min_value: float | None = None
    max_value: float | None = None
    min_text: str | None = None
    max_text: str | None = None
    _seen: set[str] = field(default_factory=set, repr=False)

    def observe(self, value: str) -> None:
        if value == "":
            self.empty += 1
            return
        self.non_empty += 1

        if len(self._seen) < _DISTINCT_SAMPLE_LIMIT and value not in self._seen:
            self._seen.add(value)
            self.distinct_sample.append(value)

        if self.declared_type in ("integer", "float"):
            number = _as_number(value, self.declared_type)
            if number is None:
                self.type_mismatches += 1
                return
            self.min_value = number if self.min_value is None else min(self.min_value, number)
            self.max_value = number if self.max_value is None else max(self.max_value, number)
        elif self.declared_type == "timestamp":
            parsed = parse_timestamp(value)
            if parsed is None:
                self.type_mismatches += 1
                return
            text = parsed.isoformat(sep=" ")
            self.min_text = text if self.min_text is None else min(self.min_text, text)
            self.max_text = text if self.max_text is None else max(self.max_text, text)

    def to_dict(self) -> dict[str, Any]:
        total = self.non_empty + self.empty
        return {
            "name": self.name,
            "declared_type": self.declared_type,
            "values": total,
            "non_empty": self.non_empty,
            "empty": self.empty,
            "empty_percent": round(100.0 * self.empty / total, 4) if total else 0.0,
            "type_mismatches": self.type_mismatches,
            "min": self.min_value if self.min_value is not None else self.min_text,
            "max": self.max_value if self.max_value is not None else self.max_text,
            "distinct_sample": self.distinct_sample,
        }


@dataclass(slots=True)
class FileProfile:
    path: str
    size_bytes: int
    sha256: str
    encoding: str
    delimiter: str
    header: list[str]
    schema_matches: bool
    missing_columns: list[str]
    unexpected_columns: list[str]
    data_rows: int
    wrong_field_count_rows: int
    multiline_records: int
    duplicate_rows: int
    distinct_rows: int
    columns: list[ColumnProfile]
    sample_rows: list[list[str]]

    def schema_report(self) -> dict[str, Any]:
        return {
            "encoding": self.encoding,
            "delimiter": self.delimiter,
            "header": self.header,
            "expected_columns": list(EXPECTED_COLUMNS),
            "schema_matches": self.schema_matches,
            "missing_columns": self.missing_columns,
            "unexpected_columns": self.unexpected_columns,
            "columns": [column.to_dict() for column in self.columns],
            "sample_rows": self.sample_rows,
        }

    def quality_report(self) -> dict[str, Any]:
        rows = self.data_rows or 1
        issues = []
        if not self.schema_matches:
            issues.append(
                {
                    "severity": "error",
                    "code": "SCHEMA_MISMATCH",
                    "message": "The header does not match the expected retail schema.",
                    "detail": {
                        "missing": self.missing_columns,
                        "unexpected": self.unexpected_columns,
                    },
                }
            )
        if self.wrong_field_count_rows:
            issues.append(
                {
                    "severity": "warning",
                    "code": "WRONG_FIELD_COUNT",
                    "message": f"{self.wrong_field_count_rows} rows do not have "
                               f"{len(EXPECTED_COLUMNS)} fields and will be rejected.",
                    "detail": {"rows": self.wrong_field_count_rows},
                }
            )
        if self.duplicate_rows:
            issues.append(
                {
                    "severity": "warning",
                    "code": "DUPLICATE_ROWS",
                    "message": f"{self.duplicate_rows} rows are exact duplicates of an "
                               "earlier row and will be collapsed by the validation job.",
                    "detail": {
                        "rows": self.duplicate_rows,
                        "percent": round(100.0 * self.duplicate_rows / rows, 4),
                    },
                }
            )
        if self.multiline_records:
            issues.append(
                {
                    "severity": "warning",
                    "code": "MULTILINE_RECORDS",
                    "message": f"{self.multiline_records} records contain a newline inside a "
                               "quoted field. Hadoop's TextInputFormat splits on newlines, so "
                               "these will be rejected as malformed rather than mis-parsed.",
                    "detail": {"records": self.multiline_records},
                }
            )
        for column in self.columns:
            if column.empty and column.declared_type != "string":
                issues.append(
                    {
                        "severity": "info",
                        "code": "MISSING_VALUES",
                        "message": f"{column.name} is empty in {column.empty} rows.",
                        "detail": {
                            "column": column.name,
                            "rows": column.empty,
                            "percent": round(100.0 * column.empty / rows, 4),
                        },
                    }
                )
            if column.type_mismatches:
                issues.append(
                    {
                        "severity": "warning",
                        "code": "TYPE_MISMATCH",
                        "message": f"{column.type_mismatches} values in {column.name} do not "
                                   f"parse as {column.declared_type}.",
                        "detail": {
                            "column": column.name,
                            "rows": column.type_mismatches,
                            "percent": round(100.0 * column.type_mismatches / rows, 4),
                        },
                    }
                )

        return {
            "data_rows": self.data_rows,
            "distinct_rows": self.distinct_rows,
            "duplicate_rows": self.duplicate_rows,
            "wrong_field_count_rows": self.wrong_field_count_rows,
            "multiline_records": self.multiline_records,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "issues": issues,
            "blocking_issues": [issue for issue in issues if issue["severity"] == "error"],
            "scope_note": (
                "This report describes the uploaded file. Transaction classification and "
                "every analytical figure are produced by the Hadoop MapReduce jobs."
            ),
        }


def _as_number(value: str, kind: str) -> float | None:
    try:
        number = float(value)
    except ValueError:
        return None
    if kind == "integer" and not number.is_integer():
        # A float in an integer column is a mismatch worth reporting, except for
        # the spreadsheet artefact "17850.0", which the cluster normalises.
        return number if value.endswith(".0") else None
    return number


def parse_timestamp(value: str, *, day_first: bool = False) -> datetime | None:
    """Parses a timestamp with the same pattern set as the cluster."""
    text = value.strip()
    if not text:
        return None
    families = (
        (DAY_FIRST_PATTERNS, ISO_PATTERNS, MONTH_FIRST_PATTERNS)
        if day_first
        else (MONTH_FIRST_PATTERNS, ISO_PATTERNS, DAY_FIRST_PATTERNS)
    )
    for family in families:
        for pattern in family:
            try:
                return datetime.strptime(text, pattern)
            except ValueError:
                continue
    return None


def detect_encoding(path: Path) -> str:
    """First candidate encoding that decodes a sample of the file."""
    with path.open("rb") as handle:
        sample = handle.read(_SAMPLE_BYTES)
    if sample.startswith(b"PK\x03\x04"):
        raise ProfilingError(
            "the uploaded file is a ZIP or Excel (.xlsx) workbook, not a CSV file; "
            "convert it to CSV before uploading (e.g. using 'scripts/xlsx_to_csv.py')"
        )
    if b"\x00" in sample:
        raise ProfilingError(
            "the uploaded file contains binary null bytes and is not a valid text CSV"
        )
    for encoding in CANDIDATE_ENCODINGS:
        try:
            sample.decode(encoding)
        except UnicodeDecodeError:
            continue
        return encoding
    raise ProfilingError(
        "the file could not be decoded as any of: " + ", ".join(CANDIDATE_ENCODINGS)
    )


def detect_delimiter(path: Path, encoding: str) -> str:
    with path.open("r", encoding=encoding, errors="replace") as handle:
        sample = handle.read(_SAMPLE_BYTES)
    if not sample.strip():
        raise ProfilingError("the file is empty")
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        # A single-column file or an unusual quoting style defeats the sniffer.
        # Comma is the documented format, so fall back to it rather than fail.
        log.info("delimiter sniffing failed for %s; assuming comma", path)
        return ","


def checksum(path: Path, *, chunk_size: int = 1_048_576) -> str:
    """SHA-256 of the file as uploaded, computed without loading it into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def profile_csv(path: str | Path, *, sample_rows: int = 10) -> FileProfile:
    """Reads the whole file once and returns its profile.

    The parse uses Python's ``csv`` module, which implements RFC 4180: quoted
    fields containing commas are handled correctly, so a product description
    such as ``"CUPS, LARGE"`` is one field and not two.
    """
    source = Path(path)
    if not source.is_file():
        raise ProfilingError(f"{source} is not a file")

    size_bytes = source.stat().st_size
    if size_bytes == 0:
        raise ProfilingError("the file is empty")

    encoding = detect_encoding(source)
    delimiter = detect_delimiter(source, encoding)
    digest = checksum(source)

    columns: list[ColumnProfile] = []
    samples: list[list[str]] = []
    row_hashes: set[bytes] = set()
    data_rows = 0
    duplicate_rows = 0
    wrong_field_count = 0
    multiline_records = 0
    header: list[str] = []

    with source.open("r", encoding=encoding, errors="replace", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        try:
            header = [field_name.strip() for field_name in next(reader)]
        except StopIteration as empty:
            raise ProfilingError("the file has no header row") from empty

        normalised = [name.lower().replace(" ", "").replace("_", "") for name in header]
        expected = [name.lower() for name in EXPECTED_COLUMNS]
        missing = [
            EXPECTED_COLUMNS[index]
            for index, name in enumerate(expected)
            if name not in normalised
        ]
        unexpected = [
            header[index]
            for index, name in enumerate(normalised)
            if name not in expected
        ]
        schema_matches = not missing and not unexpected

        columns = [
            ColumnProfile(name=name, declared_type=EXPECTED_TYPES.get(name, "string"))
            for name in (EXPECTED_COLUMNS if schema_matches else header)
        ]
        field_count = len(columns)

        previous_line = reader.line_num
        for row in reader:
            # reader.line_num counts physical lines, so a jump of more than one
            # means the record spanned a newline inside a quoted field.
            if reader.line_num - previous_line > 1:
                multiline_records += 1
            previous_line = reader.line_num

            if not row or (len(row) == 1 and not row[0].strip()):
                continue
            data_rows += 1

            if len(row) != field_count:
                wrong_field_count += 1

            fingerprint = hashlib.blake2b(
                delimiter.join(value.strip() for value in row).encode("utf-8", "replace"),
                digest_size=16,
            ).digest()
            if fingerprint in row_hashes:
                duplicate_rows += 1
            else:
                row_hashes.add(fingerprint)

            for index, column in enumerate(columns):
                column.observe(row[index].strip() if index < len(row) else "")

            if len(samples) < sample_rows:
                samples.append([value.strip() for value in row])

    log.info(
        "profiled %s: %d data rows, %d duplicates, %d wrong field count, encoding=%s",
        source.name, data_rows, duplicate_rows, wrong_field_count, encoding,
    )

    return FileProfile(
        path=str(source),
        size_bytes=size_bytes,
        sha256=digest,
        encoding=encoding,
        delimiter=delimiter,
        header=header,
        schema_matches=schema_matches,
        missing_columns=missing,
        unexpected_columns=unexpected,
        data_rows=data_rows,
        wrong_field_count_rows=wrong_field_count,
        multiline_records=multiline_records,
        duplicate_rows=duplicate_rows,
        distinct_rows=len(row_hashes),
        columns=columns,
        sample_rows=samples,
    )


def preview(path: str | Path, *, rows: int = 20) -> dict[str, Any]:
    """A quick look at the head of a file, without a full profiling pass."""
    source = Path(path)
    encoding = detect_encoding(source)
    delimiter = detect_delimiter(source, encoding)
    with source.open("r", encoding=encoding, errors="replace", newline="") as handle:
        head = io.StringIO(handle.read(_SAMPLE_BYTES))
    reader = csv.reader(head, delimiter=delimiter)
    collected = []
    header: list[str] = []
    for index, row in enumerate(reader):
        if index == 0:
            header = [value.strip() for value in row]
            continue
        if len(collected) >= rows:
            break
        collected.append([value.strip() for value in row])
    return {"encoding": encoding, "delimiter": delimiter, "header": header, "rows": collected}
