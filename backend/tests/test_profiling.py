"""Tests for the ingestion profiler.

The cases here are the ones that actually bite on real retail exports: a
description containing a comma, a cp1252 file, a CustomerID rendered as a
float, and an exact duplicate row.
"""

from __future__ import annotations

import textwrap
from datetime import datetime
from pathlib import Path

import pytest

from app.services import profiling

HEADER = "InvoiceNo,StockCode,Description,Quantity,InvoiceDate,UnitPrice,CustomerID,Country"


def write(tmp_path: Path, body: str, *, encoding: str = "utf-8", name: str = "retail.csv") -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body).lstrip("\n"), encoding=encoding)
    return path


def test_profiles_a_clean_file(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        f"""
        {HEADER}
        536365,85123A,WHITE HANGING HEART T-LIGHT HOLDER,6,12/1/2010 8:26,2.55,17850,United Kingdom
        536365,71053,WHITE METAL LANTERN,6,12/1/2010 8:26,3.39,17850,United Kingdom
        """,
    )
    profile = profiling.profile_csv(path)

    assert profile.schema_matches
    assert profile.data_rows == 2
    assert profile.duplicate_rows == 0
    assert profile.wrong_field_count_rows == 0
    assert profile.delimiter == ","
    assert len(profile.sha256) == 64
    assert profile.quality_report()["blocking_issues"] == []


def test_keeps_a_quoted_comma_as_one_field(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        f"""
        {HEADER}
        536370,22728,"SET/6 RED SPOTTY PAPER CUPS, LARGE",24,12/1/2010 8:45,0.85,12583,France
        """,
    )
    profile = profiling.profile_csv(path)

    assert profile.wrong_field_count_rows == 0
    description = next(column for column in profile.columns if column.name == "Description")
    assert description.distinct_sample == ["SET/6 RED SPOTTY PAPER CUPS, LARGE"]
    country = next(column for column in profile.columns if column.name == "Country")
    assert country.distinct_sample == ["France"]


def test_detects_duplicate_rows(tmp_path: Path) -> None:
    row = "536365,85123A,WHITE HANGING HEART,6,12/1/2010 8:26,2.55,17850,United Kingdom"
    path = write(tmp_path, f"""
        {HEADER}
        {row}
        {row}
        {row}
        """)
    profile = profiling.profile_csv(path)

    assert profile.data_rows == 3
    assert profile.distinct_rows == 1
    assert profile.duplicate_rows == 2
    codes = {issue["code"] for issue in profile.quality_report()["issues"]}
    assert "DUPLICATE_ROWS" in codes


def test_reads_a_cp1252_file(tmp_path: Path) -> None:
    # The real UCI exports are not UTF-8; a UTF-8-only reader fails on them.
    path = write(
        tmp_path,
        f"""
        {HEADER}
        536367,21755,CAFÉ OLE MUG,3,12/1/2010 8:34,1.25,13047,United Kingdom
        """,
        encoding="cp1252",
    )
    profile = profiling.profile_csv(path)

    assert profile.encoding == "cp1252"
    assert profile.data_rows == 1
    assert profile.wrong_field_count_rows == 0


def test_reports_a_schema_mismatch_as_blocking(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        """
        Order,Item,Amount
        1,widget,3
        """,
    )
    profile = profiling.profile_csv(path)
    report = profile.quality_report()

    assert not profile.schema_matches
    assert [issue["code"] for issue in report["blocking_issues"]] == ["SCHEMA_MISMATCH"]


def test_counts_unparseable_values_per_column(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        f"""
        {HEADER}
        536365,85123A,GOOD,6,12/1/2010 8:26,2.55,17850,United Kingdom
        536366,85123B,BAD QUANTITY,many,12/1/2010 8:26,2.55,17850,United Kingdom
        536367,85123C,BAD DATE,6,not-a-date,2.55,17850,United Kingdom
        """,
    )
    profile = profiling.profile_csv(path)
    by_name = {column.name: column for column in profile.columns}

    assert by_name["Quantity"].type_mismatches == 1
    assert by_name["InvoiceDate"].type_mismatches == 1
    assert by_name["CustomerID"].type_mismatches == 0


def test_treats_a_float_customer_id_as_an_integer(tmp_path: Path) -> None:
    # Spreadsheet exports render the numeric CustomerID column as 17850.0.
    path = write(
        tmp_path,
        f"""
        {HEADER}
        536365,85123A,GOOD,6,12/1/2010 8:26,2.55,17850.0,United Kingdom
        """,
    )
    profile = profiling.profile_csv(path)
    customer = next(column for column in profile.columns if column.name == "CustomerID")

    assert customer.type_mismatches == 0


def test_counts_empty_customer_ids(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        f"""
        {HEADER}
        536414,22139,NO CUSTOMER,56,12/1/2010 11:52,1.25,,United Kingdom
        536365,85123A,HAS CUSTOMER,6,12/1/2010 8:26,2.55,17850,United Kingdom
        """,
    )
    profile = profiling.profile_csv(path)
    customer = next(column for column in profile.columns if column.name == "CustomerID")

    assert customer.empty == 1
    assert customer.non_empty == 1


def test_rejects_an_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(profiling.ProfilingError):
        profiling.profile_csv(path)


@pytest.mark.parametrize(
    ("value", "day_first", "expected"),
    [
        ("12/1/2010 8:26", False, datetime(2010, 12, 1, 8, 26)),
        ("12/1/2010 8:26", True, datetime(2010, 1, 12, 8, 26)),
        ("2011-03-04 13:45:09", False, datetime(2011, 3, 4, 13, 45, 9)),
        ("2011-03-04", False, datetime(2011, 3, 4, 0, 0)),
    ],
)
def test_timestamp_patterns(value: str, day_first: bool, expected: datetime) -> None:
    assert profiling.parse_timestamp(value, day_first=day_first) == expected


def test_unparseable_timestamp_returns_none() -> None:
    assert profiling.parse_timestamp("13/45/2010 99:99") is None
    assert profiling.parse_timestamp("") is None


def test_checksum_is_stable(tmp_path: Path) -> None:
    first = write(tmp_path, f"{HEADER}\n", name="a.csv")
    second = write(tmp_path, f"{HEADER}\n", name="b.csv")
    assert profiling.checksum(first) == profiling.checksum(second)
