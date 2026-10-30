"""The synthetic dataset generator.

A benchmark against generated data is only meaningful if the data has the shape
the analyses depend on, so these tests check the structure that matters: whole
invoices with several lines, repeat customers, cancellations that reverse a real
earlier basket, and the same schema the ingestion pipeline expects.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import pytest

from app.services import profiling, synthetic

SOURCE_ROWS = [
    # Two invoices for customer 17850, so the source has a repeat customer.
    ("536365", "85123A", "WHITE HANGING HEART", "6", "12/1/2010 8:26", "2.55", "17850", "United Kingdom"),
    ("536365", "71053", "WHITE METAL LANTERN", "6", "12/1/2010 8:26", "3.39", "17850", "United Kingdom"),
    ("536366", "22633", "HAND WARMER UNION JACK", "6", "12/1/2010 8:28", "1.85", "17850", "United Kingdom"),
    ("536367", "84879", "ASSORTED COLOUR BIRD ORNAMENT", "32", "12/2/2010 8:34", "1.69", "13047", "United Kingdom"),
    ("536368", "22960", "JAM MAKING SET WITH JARS", "6", "1/4/2011 8:34", "4.25", "13047", "France"),
    ("C536369", "22960", "JAM MAKING SET WITH JARS", "-6", "1/5/2011 9:00", "4.25", "13047", "France"),
    ("536370", "21730", "GLASS STAR FROSTED T-LIGHT", "24", "2/1/2011 10:03", "4.25", "", "Germany"),
]


@pytest.fixture()
def source(tmp_path: Path) -> Path:
    path = tmp_path / "source.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(profiling.EXPECTED_COLUMNS)
        writer.writerows(SOURCE_ROWS)
    return path


def test_learns_the_source_structure(source: Path) -> None:
    profile = synthetic.learn(source)

    assert profile.source_rows == len(SOURCE_ROWS)
    assert {product.stock_code for product in profile.products} == {
        "85123A", "71053", "22633", "84879", "22960", "21730",
    }
    assert set(profile.customers) == {"17850", "13047"}
    assert "Germany" in profile.countries
    # One of the seven rows has no CustomerID.
    assert profile.missing_customer_rate == pytest.approx(1 / 7)
    # One of the seven rows is a cancellation.
    assert profile.cancellation_rate == pytest.approx(1 / 7)


def test_learns_per_product_price_bounds(source: Path) -> None:
    profile = synthetic.learn(source)
    jam = next(product for product in profile.products if product.stock_code == "22960")

    assert jam.price_low == pytest.approx(4.25)
    assert jam.price_high == pytest.approx(4.25)
    assert jam.description == "JAM MAKING SET WITH JARS"


def test_generates_the_expected_schema(source: Path, tmp_path: Path) -> None:
    profile = synthetic.learn(source)
    target = tmp_path / "generated.csv"
    summary = synthetic.generate(profile, target, target_rows=2_000, seed=7)

    assert summary["rows_written"] >= 2_000
    assert target.stat().st_size > 0

    with target.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        rows = list(reader)

    assert header == list(profiling.EXPECTED_COLUMNS)
    assert all(len(row) == len(profiling.EXPECTED_COLUMNS) for row in rows)
    assert len(rows) == summary["rows_written"]


def test_generated_data_passes_the_ingestion_profiler(source: Path, tmp_path: Path) -> None:
    # The generated file goes through the same ingestion path as an upload, so
    # it has to profile cleanly.
    profile = synthetic.learn(source)
    target = tmp_path / "generated.csv"
    synthetic.generate(profile, target, target_rows=3_000, seed=11)

    report = profiling.profile_csv(target)

    assert report.schema_matches
    assert report.quality_report()["blocking_issues"] == []
    assert report.wrong_field_count_rows == 0
    assert report.multiline_records == 0


def test_generates_multi_line_invoices_and_repeat_customers(
    source: Path, tmp_path: Path
) -> None:
    profile = synthetic.learn(source)
    target = tmp_path / "generated.csv"
    synthetic.generate(profile, target, target_rows=5_000, seed=13)

    with target.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    lines_per_invoice = Counter(row["InvoiceNo"] for row in rows)
    assert max(lines_per_invoice.values()) > 1, "every invoice had a single line"

    invoices_per_customer: dict[str, set[str]] = {}
    for row in rows:
        customer = row["CustomerID"]
        if customer:
            invoices_per_customer.setdefault(customer, set()).add(row["InvoiceNo"])
    assert any(len(invoices) >= 2 for invoices in invoices_per_customer.values()), (
        "no customer bought twice"
    )


def test_reproduces_cancellations_that_reverse_a_basket(source: Path, tmp_path: Path) -> None:
    profile = synthetic.learn(source)
    target = tmp_path / "generated.csv"
    summary = synthetic.generate(profile, target, target_rows=5_000, seed=17)

    assert summary["cancellation_invoices"] > 0

    with target.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    cancellations = [row for row in rows if row["InvoiceNo"].startswith("C")]
    assert cancellations
    # A cancellation reverses units, so its quantity is negative and its price
    # stays positive — which is what the validation job classifies as a RETURN.
    assert all(int(row["Quantity"]) < 0 for row in cancellations)
    assert all(float(row["UnitPrice"]) > 0 for row in cancellations)


def test_the_same_seed_reproduces_the_same_file(source: Path, tmp_path: Path) -> None:
    profile = synthetic.learn(source)
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    synthetic.generate(profile, first, target_rows=2_000, seed=99)
    synthetic.generate(profile, second, target_rows=2_000, seed=99)

    assert first.read_bytes() == second.read_bytes()


def test_a_different_seed_produces_different_data(source: Path, tmp_path: Path) -> None:
    profile = synthetic.learn(source)
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    synthetic.generate(profile, first, target_rows=2_000, seed=1)
    synthetic.generate(profile, second, target_rows=2_000, seed=2)

    assert first.read_bytes() != second.read_bytes()


def test_rejects_a_non_positive_target(source: Path, tmp_path: Path) -> None:
    profile = synthetic.learn(source)
    with pytest.raises(ValueError):
        synthetic.generate(profile, tmp_path / "x.csv", target_rows=0)


def test_rejects_a_source_with_no_usable_rows(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(profiling.EXPECTED_COLUMNS)
    with pytest.raises(ValueError, match="no usable product rows"):
        synthetic.learn(path)
