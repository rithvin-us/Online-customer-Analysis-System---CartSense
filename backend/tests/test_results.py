"""Reading reducer output back into labelled rows.

The important property is that the reader never invents or recomputes a value:
it labels, it casts, and it refuses a row whose shape has drifted from the
registry rather than guessing which column is which.
"""

from __future__ import annotations

import pytest

from app.services import registry, results


def test_parses_a_monthly_row() -> None:
    output = registry.get_analysis("monthly_sales").output("by_month")
    line = "2011-01\t690000.5\t12000.25\t678000.25\t1200\t1150\t780\t45000\t900\t20000\t400"
    rows = results.parse_rows([line], output)

    assert rows == [
        {
            "month": "2011-01",
            "gross_revenue": 690000.5,
            "returns": 12000.25,
            "net_revenue": 678000.25,
            "distinct_invoices": 1200,
            "completed_invoices": 1150,
            "identifiable_customers": 780,
            "quantity_sold": 45000,
            "quantity_returned": 900,
            "sale_lines": 20000,
            "return_lines": 400,
        }
    ]


def test_reads_a_whole_number_written_as_a_double() -> None:
    # Java's Double.toString writes an integral count as "42.0".
    output = registry.get_analysis("repeat_customers").output("by_customer")
    rows = results.parse_rows(["17850\t7.0\t5391.21\t8.0\t1"], output)

    assert rows[0]["completed_invoices"] == 7
    assert rows[0]["invoices_touched"] == 8
    assert rows[0]["net_spend"] == 5391.21
    assert rows[0]["is_repeat_customer"] == 1


def test_an_empty_trailing_field_becomes_none() -> None:
    output = registry.VALIDATION_OUTPUTS["validated"]
    line = (
        "536414\t22139\tNO CUSTOMER\t56\t1291204320000\t2010-12-01 11:52:00\t"
        "2010-12\t1.25\t\tUnited Kingdom\t70.0\t70.0\tSALE"
    )
    rows = results.parse_rows([line], output)

    assert rows[0]["customer_id"] is None
    assert rows[0]["country"] == "United Kingdom"
    assert rows[0]["txn_class"] == "SALE"


def test_a_short_row_is_padded_not_misaligned() -> None:
    # A product with no description still has the right number of tabs, but a
    # defensive pad keeps the remaining columns aligned rather than shifted.
    output = registry.get_analysis("product_analysis").output("by_product")
    line = "85123A\t100.0\t0.0\t100.0\t40\t0\t12\t12\t0"
    rows = results.parse_rows([line], output)

    assert rows[0]["stock_code"] == "85123A"
    assert rows[0]["net_revenue"] == 100.0
    assert rows[0]["description"] is None


def test_a_long_row_is_a_schema_mismatch() -> None:
    output = registry.get_analysis("monthly_sales").output("by_month")
    with pytest.raises(results.ResultSchemaMismatch) as failure:
        results.parse_rows(["2011-01\t1\t2\t3\t4\t5\t6\t7\t8\t9\t10\t11\t12"], output)

    assert failure.value.expected == 11
    assert failure.value.found == 13


def test_a_ranked_row_keeps_its_rank() -> None:
    output = registry.get_analysis("country_analysis").output("ranked_by_net_revenue")
    line = "1\tUnited Kingdom\t8000000.0\t200000.0\t7800000.0\t19000\t18500\t3900\t4000000\t50000\t495000"
    rows = results.parse_rows([line], output)

    assert rows[0]["rank"] == 1
    assert rows[0]["country"] == "United Kingdom"
    assert rows[0]["net_revenue"] == 7800000.0


def test_non_numeric_text_in_a_numeric_column_is_preserved() -> None:
    # Better to surface the raw value than to silently turn it into 0.
    output = registry.get_analysis("repeat_customers").output("summary")
    rows = results.parse_rows(["average_purchase_frequency\tunavailable"], output)

    assert rows[0]["metric"] == "average_purchase_frequency"
    assert rows[0]["value"] == "unavailable"


def test_summarise_metric_rows() -> None:
    output = registry.get_analysis("repeat_customers").output("summary")
    rows = results.parse_rows(
        [
            "identified_customers\t4372",
            "repeat_customers\t2845",
            "repeat_customer_percentage\t65.1234",
        ],
        output,
    )
    summary = results.summarise_metric_rows(rows)

    assert summary["identified_customers"] == 4372
    assert summary["repeat_customer_percentage"] == 65.1234


def test_blank_lines_are_ignored() -> None:
    output = registry.get_analysis("repeat_customers").output("summary")
    assert results.parse_rows([], output) == []
