"""The analysis registry is the contract between the jobs and the UI.

These tests guard the parts of it that break silently: a column list that no
longer matches the reducers, a duplicated name, or a ranking output whose first
column is not the rank.
"""

from __future__ import annotations

import pytest

from app.services import registry


def test_every_analysis_is_reachable_in_order() -> None:
    assert set(registry.ANALYSIS_ORDER) == set(registry.ANALYSES)
    assert [analysis.key for analysis in registry.all_analyses()] == list(
        registry.ANALYSIS_ORDER
    )


def test_each_analysis_has_stages_and_outputs() -> None:
    for analysis in registry.all_analyses():
        assert analysis.stages, f"{analysis.key} declares no stages"
        assert analysis.outputs, f"{analysis.key} declares no outputs"
        assert analysis.objective and analysis.scope_note


def test_output_and_column_names_are_unique() -> None:
    for analysis in registry.all_analyses():
        names = [output.name for output in analysis.outputs]
        assert len(names) == len(set(names)), f"{analysis.key} repeats an output name"
        for output in analysis.outputs:
            columns = [column.name for column in output.columns]
            assert len(columns) == len(set(columns)), (
                f"{analysis.key}/{output.name} repeats a column name"
            )


def test_ranked_outputs_lead_with_the_rank() -> None:
    for analysis in registry.all_analyses():
        for output in analysis.outputs:
            if output.ranked:
                assert output.columns[0].name == "rank"
                assert output.columns[0].type == "integer"
            else:
                assert output.columns[0].name != "rank"


def test_a_ranked_output_mirrors_its_aggregate() -> None:
    # A ranking stage sorts the aggregate rows, so the two layouts must agree
    # apart from the leading rank column.
    products = registry.get_analysis("product_analysis")
    aggregate = products.output("by_product")
    ranked = products.output("ranked_by_net_revenue")
    assert ranked.column_names == ("rank", *aggregate.column_names)


def test_default_sort_names_a_real_column() -> None:
    for analysis in registry.all_analyses():
        for output in analysis.outputs:
            if output.default_sort:
                assert output.default_sort in output.column_names


def test_validate_selection_normalises_to_registry_order() -> None:
    chosen = registry.validate_selection(["monthly_sales", "customer_analysis"])
    assert chosen == ["customer_analysis", "monthly_sales"]


def test_validate_selection_removes_duplicates() -> None:
    assert registry.validate_selection(["monthly_sales", "monthly_sales"]) == ["monthly_sales"]


def test_validate_selection_rejects_an_unknown_analysis() -> None:
    with pytest.raises(ValueError, match="unknown analyses: nope"):
        registry.validate_selection(["nope"])


def test_validate_selection_rejects_an_empty_choice() -> None:
    with pytest.raises(ValueError, match="at least one analysis"):
        registry.validate_selection([])


def test_validation_outputs_match_the_canonical_record() -> None:
    validated = registry.VALIDATION_OUTPUTS["validated"]
    assert validated.column_names == (
        "invoice_no",
        "stock_code",
        "description",
        "quantity",
        "invoice_ts",
        "invoice_date",
        "month",
        "unit_price",
        "customer_id",
        "country",
        "line_value",
        "abs_value",
        "txn_class",
    )
    assert registry.VALIDATION_OUTPUTS["rejected"].column_names == (
        "reason",
        "copies",
        "record",
    )


def test_only_rfm_is_optional() -> None:
    optional = {analysis.key for analysis in registry.all_analyses() if analysis.optional}
    assert optional == {"rfm_analysis"}


def test_unknown_output_raises() -> None:
    with pytest.raises(KeyError):
        registry.get_analysis("monthly_sales").output("nope")


def test_product_classification_layouts_match_the_reducers() -> None:
    # These two layouts are written by ProductPopularityJob's classify and
    # band-summary reducers. The order is the contract between them and the
    # reader, so it is pinned here rather than only described in a docstring.
    products = registry.get_analysis("product_analysis")
    assert products.output("classified_products").column_names == (
        "rank",
        "stock_code",
        "gross_revenue",
        "net_revenue",
        "quantity_sold",
        "quantity_returned",
        "distinct_invoices",
        "average_unit_price",
        "return_rate_pct",
        "revenue_share_pct",
        "cumulative_revenue_share_pct",
        "abc_class",
        "price_band",
        "volume_band",
        "return_class",
        "description",
    )
    assert products.output("by_classification").column_names == (
        "dimension",
        "band",
        "ordinal",
        "products",
        "product_share_pct",
        "quantity_sold",
        "quantity_returned",
        "gross_revenue",
        "net_revenue",
        "revenue_share_pct",
        "average_unit_price",
    )


def test_every_product_ranking_has_a_stage_behind_it() -> None:
    # A ranked output with no ranking stage would be an output nothing writes.
    products = registry.get_analysis("product_analysis")
    stages = {stage.name for stage in products.stages}
    assert {"rank-revenue", "rank-quantity", "rank-returns", "rank-reach",
            "classify", "band-summary"} <= stages
    ranked = {output.name for output in products.outputs if output.ranked}
    assert ranked == {
        "ranked_by_net_revenue",
        "ranked_by_quantity_sold",
        "ranked_by_quantity_returned",
        "ranked_by_distinct_invoices",
        "classified_products",
    }
