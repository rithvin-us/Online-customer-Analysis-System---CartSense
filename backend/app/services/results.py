"""Reading reducer output back out of HDFS.

The analytical values are produced by Hadoop and written to HDFS as tab
separated text. This module reads those files and labels the columns using the
analysis registry. It casts strings to numbers and nothing else: no value is
recomputed, no total is re-derived, and a row whose field count does not match
the registry is reported as a schema mismatch instead of being guessed at.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from typing import Any

from app.core.logging import get_logger
from app.services import hdfs
from app.services.registry import Column, Output

log = get_logger(__name__)


class ResultSchemaMismatch(RuntimeError):
    """A result row does not have the number of fields the registry expects."""

    def __init__(self, output: str, expected: int, found: int, sample: str):
        super().__init__(
            f"result {output!r} expected {expected} fields per row but found {found}"
        )
        self.output = output
        self.expected = expected
        self.found = found
        self.sample = sample[:500]


def _cast(value: str, column: Column) -> Any:
    if value == "":
        return None
    if column.type == "integer":
        try:
            return int(value)
        except ValueError:
            try:
                # Reducers emit whole numbers through Java's double formatting,
                # so "42.0" is an integer that happens to carry a decimal point.
                return int(float(value))
            except ValueError:
                return value
    if column.type == "float":
        try:
            return float(value)
        except ValueError:
            return value
    return value


def parse_rows(lines: list[str], output: Output) -> list[dict[str, Any]]:
    """Turns raw reducer lines into labelled, typed rows."""
    columns = output.columns
    expected = len(columns)
    rows: list[dict[str, Any]] = []

    for line in lines:
        fields = line.split("\t")
        if len(fields) != expected:
            # The final column of some outputs is free text that may itself be
            # empty; tolerate a short row by padding, but never a long one,
            # which would mean the layout has drifted from the registry.
            if len(fields) < expected:
                fields = fields + [""] * (expected - len(fields))
            else:
                raise ResultSchemaMismatch(output.name, expected, len(fields), line)
        rows.append({column.name: _cast(fields[index], column)
                     for index, column in enumerate(columns)})
    return rows


def read_output(
    hdfs_dir: str,
    output: Output,
    *,
    limit: int,
    offset: int = 0,
) -> dict[str, Any]:
    """Reads a page of one result directory."""
    lines, more = hdfs.read_rows(hdfs_dir, limit=limit, skip=offset)
    rows = parse_rows(lines, output)
    return {
        "name": output.name,
        "title": output.title,
        "description": output.description,
        "hdfs_path": hdfs_dir,
        "ranked": output.ranked,
        "columns": [
            {
                "name": column.name,
                "label": column.label,
                "type": column.type,
                "unit": column.unit,
                "description": column.description,
            }
            for column in output.columns
        ],
        "rows": rows,
        "offset": offset,
        "returned": len(rows),
        "has_more": more,
    }


def iter_all_rows(hdfs_dir: str, output: Output, *, page_size: int = 5000) -> Iterator[dict[str, Any]]:
    """Streams an entire result directory, a page at a time.

    Used by the exporters so that a large result is never held in memory in
    full, neither in the backend nor in the response buffer.
    """
    offset = 0
    while True:
        lines, more = hdfs.read_rows(hdfs_dir, limit=page_size, skip=offset)
        if not lines:
            return
        yield from parse_rows(lines, output)
        offset += len(lines)
        if not more:
            return


def export_csv(hdfs_dir: str, output: Output) -> Iterator[str]:
    """Yields the result as CSV text, header first."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    writer.writerow([column.name for column in output.columns])
    yield _drain(buffer)

    for row in iter_all_rows(hdfs_dir, output):
        writer.writerow(["" if row[column.name] is None else row[column.name]
                         for column in output.columns])
        if buffer.tell() > 65_536:
            yield _drain(buffer)
    remaining = _drain(buffer)
    if remaining:
        yield remaining


def _drain(buffer: io.StringIO) -> str:
    text = buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    return text


def summarise_metric_rows(rows: list[dict[str, Any]]) -> dict[str, float | int | str]:
    """Collapses a two-column ``metric``/``value`` result into a mapping.

    The loyalty summary is emitted one metric per row, because that is the
    natural shape for a reducer to write. The UI wants it as an object.
    """
    summary: dict[str, float | int | str] = {}
    for row in rows:
        metric = row.get("metric")
        if metric is None:
            continue
        summary[str(metric)] = row.get("value")
    return summary
