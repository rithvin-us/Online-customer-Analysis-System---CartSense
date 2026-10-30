"""The analysis registry: what CartScope can run, and what it produces.

This module is the single description of the MapReduce catalogue. The API, the
result readers, the exporters and the UI all derive their behaviour from it, so
a column layout is written down exactly once.

The column lists here must match the reducers in ``mapreduce/src``. They are
checked at runtime: a result row with a different number of fields is reported
as a schema mismatch rather than silently mis-labelled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ColumnType = Literal["string", "integer", "float"]


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    type: ColumnType
    label: str
    description: str = ""
    #: Rendering hint for the UI: currency, quantity, percent, count or plain.
    unit: str = "plain"


@dataclass(frozen=True, slots=True)
class Output:
    """One result directory written by an analysis."""

    name: str
    title: str
    description: str
    columns: tuple[Column, ...]
    #: Rows are already in rank order and the first column is the rank.
    ranked: bool = False
    #: Column the UI should sort by when showing an unranked output.
    default_sort: str | None = None

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)


@dataclass(frozen=True, slots=True)
class Stage:
    """One MapReduce job inside an analysis chain."""

    name: str
    title: str
    purpose: str


@dataclass(frozen=True, slots=True)
class Analysis:
    key: str
    title: str
    objective: str
    scope_note: str
    stages: tuple[Stage, ...]
    outputs: tuple[Output, ...]
    optional: bool = False

    def output(self, name: str) -> Output:
        for candidate in self.outputs:
            if candidate.name == name:
                return candidate
        raise KeyError(f"analysis {self.key} has no output named {name!r}")

    @property
    def stage_count(self) -> int:
        return len(self.stages)


# ---------------------------------------------------------------------------
# Reusable column groups
# ---------------------------------------------------------------------------

RANK_COLUMN = Column("rank", "integer", "Rank", "Position in the ordering", unit="count")


def _ranked(output: Output, name: str, title: str, description: str) -> Output:
    """A ranked view of an aggregated output: the same columns behind a rank."""
    return Output(
        name=name,
        title=title,
        description=description,
        columns=(RANK_COLUMN, *output.columns),
        ranked=True,
    )


VALIDATED_COLUMNS: tuple[Column, ...] = (
    Column("invoice_no", "string", "Invoice"),
    Column("stock_code", "string", "Stock code"),
    Column("description", "string", "Description"),
    Column("quantity", "integer", "Quantity", unit="quantity"),
    Column("invoice_ts", "integer", "Timestamp (epoch ms)"),
    Column("invoice_date", "string", "Invoice date"),
    Column("month", "string", "Month"),
    Column("unit_price", "float", "Unit price", unit="currency"),
    Column("customer_id", "string", "Customer"),
    Column("country", "string", "Country"),
    Column("line_value", "float", "Line value", "Signed quantity x unit price", unit="currency"),
    Column("abs_value", "float", "Absolute value", "|quantity| x unit price", unit="currency"),
    Column("txn_class", "string", "Class", "SALE or RETURN"),
)

REJECTED_COLUMNS: tuple[Column, ...] = (
    Column("reason", "string", "Reason", "Which rule rejected the record"),
    Column("copies", "integer", "Copies", "How many identical records had this fault", unit="count"),
    Column("record", "string", "Record", "The original line, or the canonical form for a duplicate"),
)


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------

_CUSTOMER_BY_CUSTOMER = Output(
    name="by_customer",
    title="Customers",
    description="One row per identified customer.",
    columns=(
        Column("customer_id", "string", "Customer"),
        Column("total_orders", "integer", "Completed orders",
               "Distinct invoices with net positive value", unit="count"),
        Column("gross_spending", "float", "Gross spending",
               "Sum of fulfilled sale line values", unit="currency"),
        Column("returns", "float", "Returns",
               "Sum of the absolute value of reversal lines", unit="currency"),
        Column("net_spending", "float", "Net spending", "Gross spending less returns", unit="currency"),
        Column("average_order_value", "float", "Average order value",
               "Gross spending divided by completed orders", unit="currency"),
        Column("returned_lines", "integer", "Return lines", unit="count"),
        Column("invoices_touched", "integer", "Invoices touched",
               "Distinct invoices including pure cancellations", unit="count"),
    ),
    default_sort="net_spending",
)

_PRODUCT_BY_PRODUCT = Output(
    name="by_product",
    title="Products",
    description="One row per stock code.",
    columns=(
        Column("stock_code", "string", "Stock code"),
        Column("gross_revenue", "float", "Gross revenue", unit="currency"),
        Column("returns", "float", "Returns", unit="currency"),
        Column("net_revenue", "float", "Net revenue", unit="currency"),
        Column("quantity_sold", "integer", "Quantity sold", unit="quantity"),
        Column("quantity_returned", "integer", "Quantity returned", unit="quantity"),
        Column("distinct_invoices", "integer", "Distinct invoices", unit="count"),
        Column("sale_lines", "integer", "Sale lines", unit="count"),
        Column("return_lines", "integer", "Return lines", unit="count"),
        Column("description", "string", "Description",
               "Lexicographically smallest description seen for this stock code"),
    ),
    default_sort="net_revenue",
)

_COUNTRY_BY_COUNTRY = Output(
    name="by_country",
    title="Countries",
    description="One row per country.",
    columns=(
        Column("country", "string", "Country"),
        Column("gross_revenue", "float", "Gross revenue", unit="currency"),
        Column("returns", "float", "Returns", unit="currency"),
        Column("net_revenue", "float", "Net revenue", unit="currency"),
        Column("distinct_invoices", "integer", "Distinct invoices", unit="count"),
        Column("completed_invoices", "integer", "Completed invoices", unit="count"),
        Column("identifiable_customers", "integer", "Identifiable customers",
               "Distinct CustomerID values; records without one are excluded here only",
               unit="count"),
        Column("quantity_sold", "integer", "Quantity sold", unit="quantity"),
        Column("quantity_returned", "integer", "Quantity returned", unit="quantity"),
        Column("transaction_records", "integer", "Transaction records", unit="count"),
    ),
    default_sort="net_revenue",
)

ANALYSES: dict[str, Analysis] = {
    "customer_analysis": Analysis(
        key="customer_analysis",
        title="Customer spending",
        objective="Measure what each customer bought, returned and ultimately spent.",
        scope_note=(
            "Transactions without a CustomerID are excluded: a customer level figure "
            "cannot be attributed to an unknown customer. The excluded line count is "
            "reported as the SKIPPED_MISSING_CUSTOMER_ID counter."
        ),
        stages=(
            Stage("invoice-rollup", "Invoice roll-up",
                  "Groups by (customer, invoice) so that an invoice with many lines is "
                  "counted as one order."),
            Stage("customer-rollup", "Customer roll-up",
                  "Groups the invoice rows by customer and computes the reported figures."),
            Stage("rank", "Rank",
                  "Orders customers by net spending using the shuffle, with a single "
                  "reducer to produce a total order."),
        ),
        outputs=(
            _CUSTOMER_BY_CUSTOMER,
            _ranked(_CUSTOMER_BY_CUSTOMER, "ranked_by_net_spending",
                    "Highest spending customers",
                    "Customers in descending order of net spending."),
        ),
    ),
    "monthly_sales": Analysis(
        key="monthly_sales",
        title="Monthly sales",
        objective="Show how revenue, returns and customer activity moved month by month.",
        scope_note=(
            "Money figures include transactions without a CustomerID, because they are "
            "real sales. Only the customer count excludes them, which is why it is "
            "labelled identifiable customers."
        ),
        stages=(
            Stage("distinct-rollup", "Distinct roll-up",
                  "Emits one key per (month, invoice) and one per (month, customer) so "
                  "that both distinct counts come out of the shuffle."),
            Stage("month-rollup", "Month roll-up",
                  "Sums the rows into one row per month, with a single reducer so the "
                  "series comes out in chronological order."),
        ),
        outputs=(
            Output(
                name="by_month",
                title="Months",
                description="One row per calendar month, in order.",
                columns=(
                    Column("month", "string", "Month"),
                    Column("gross_revenue", "float", "Gross revenue", unit="currency"),
                    Column("returns", "float", "Returns", unit="currency"),
                    Column("net_revenue", "float", "Net revenue", unit="currency"),
                    Column("distinct_invoices", "integer", "Distinct invoices", unit="count"),
                    Column("completed_invoices", "integer", "Completed invoices", unit="count"),
                    Column("identifiable_customers", "integer", "Identifiable customers", unit="count"),
                    Column("quantity_sold", "integer", "Quantity sold", unit="quantity"),
                    Column("quantity_returned", "integer", "Quantity returned", unit="quantity"),
                    Column("sale_lines", "integer", "Sale lines", unit="count"),
                    Column("return_lines", "integer", "Return lines", unit="count"),
                ),
                default_sort="month",
            ),
        ),
    ),
    "product_analysis": Analysis(
        key="product_analysis",
        title="Product popularity",
        objective="Find which products sell, which earn and which come back.",
        scope_note=(
            "Keyed on StockCode. Description is a label only and is collapsed with a "
            "deterministic rule, because one stock code carries several spellings in "
            "the source data."
        ),
        stages=(
            Stage("invoice-rollup", "Invoice roll-up",
                  "Groups by (stock code, invoice) to count distinct invoices per product."),
            Stage("product-rollup", "Product roll-up", "One row per stock code."),
            Stage("rank-revenue", "Rank by revenue", "Descending net revenue."),
            Stage("rank-quantity", "Rank by quantity", "Descending quantity sold."),
            Stage("rank-returns", "Rank by returns", "Descending returned quantity."),
        ),
        outputs=(
            _PRODUCT_BY_PRODUCT,
            _ranked(_PRODUCT_BY_PRODUCT, "ranked_by_net_revenue",
                    "Top products by revenue",
                    "Products in descending order of net revenue; the top ten are the "
                    "first ten rows."),
            _ranked(_PRODUCT_BY_PRODUCT, "ranked_by_quantity_sold",
                    "Top products by quantity",
                    "Products in descending order of units sold."),
            _ranked(_PRODUCT_BY_PRODUCT, "ranked_by_quantity_returned",
                    "Products with the most returns",
                    "Products in descending order of returned units."),
        ),
    ),
    "country_analysis": Analysis(
        key="country_analysis",
        title="Country sales",
        objective="Show where the revenue comes from geographically.",
        scope_note=(
            "Transactions without a CustomerID are kept: the country of a sale is known "
            "even when the buyer is not. Only the customer count excludes them."
        ),
        stages=(
            Stage("distinct-rollup", "Distinct roll-up",
                  "Two key kinds per record, for distinct invoices and distinct customers."),
            Stage("country-rollup", "Country roll-up", "One row per country."),
            Stage("rank", "Rank", "Descending net revenue."),
        ),
        outputs=(
            _COUNTRY_BY_COUNTRY,
            _ranked(_COUNTRY_BY_COUNTRY, "ranked_by_net_revenue",
                    "Top countries",
                    "Countries in descending order of net revenue."),
        ),
    ),
    "repeat_customers": Analysis(
        key="repeat_customers",
        title="Repeat customers",
        objective="Measure loyalty: who came back, how often, and what they were worth.",
        scope_note=(
            "A repeat customer has at least two distinct completed invoices. A completed "
            "invoice is one with net positive value, so a cancellation is not a purchase. "
            "Transactions without a CustomerID are excluded."
        ),
        stages=(
            Stage("invoice-rollup", "Invoice roll-up", "Lines become invoices."),
            Stage("customer-rollup", "Customer roll-up", "Invoices become customers."),
            Stage("cohort-summary", "Cohort summary",
                  "A single group over all customers produces the population figures; "
                  "the combiner does the per-split arithmetic first."),
        ),
        outputs=(
            Output(
                name="by_customer",
                title="Customers",
                description="Per-customer loyalty detail.",
                columns=(
                    Column("customer_id", "string", "Customer"),
                    Column("completed_invoices", "integer", "Completed invoices", unit="count"),
                    Column("net_spend", "float", "Net spend", unit="currency"),
                    Column("invoices_touched", "integer", "Invoices touched", unit="count"),
                    Column("is_repeat_customer", "integer", "Repeat", "1 when two or more "
                           "completed invoices", unit="count"),
                ),
                default_sort="completed_invoices",
            ),
            Output(
                name="summary",
                title="Loyalty summary",
                description="Population level figures, one metric per row.",
                columns=(
                    Column("metric", "string", "Metric"),
                    Column("value", "float", "Value"),
                ),
            ),
        ),
    ),
    "rfm_analysis": Analysis(
        key="rfm_analysis",
        title="RFM segmentation",
        objective="Score customers on recency, frequency and monetary value, and segment them.",
        scope_note=(
            "Scores are population quintiles, not fixed thresholds. The reference date "
            "is the latest completed purchase in the dataset, not the time of the run, "
            "so repeating a run over the same data reproduces the same scores. No model "
            "is trained: every segment can be re-derived by hand from the three scores."
        ),
        stages=(
            Stage("invoice-rollup", "Invoice roll-up",
                  "Lines become invoices; the latest timestamp travels in a "
                  "maximum-merged slot so no combiner can sum two dates."),
            Stage("customer-rollup", "Customer roll-up",
                  "Frequency, monetary value and last purchase per customer."),
            Stage("score", "Score",
                  "A single reducer computes the quintile boundaries over the customer "
                  "population and assigns the segments."),
            Stage("segment-summary", "Segment summary", "Size and value of each segment."),
        ),
        outputs=(
            Output(
                name="by_customer",
                title="Scored customers",
                description="One row per scored customer.",
                columns=(
                    Column("customer_id", "string", "Customer"),
                    Column("recency_days", "integer", "Recency (days)",
                           "Days from the customer's last purchase to the reference date"),
                    Column("frequency", "integer", "Frequency",
                           "Distinct completed invoices", unit="count"),
                    Column("monetary", "float", "Monetary", "Net spend", unit="currency"),
                    Column("r_score", "integer", "R", "1 to 5, 5 is most recent"),
                    Column("f_score", "integer", "F", "1 to 5, 5 is most frequent"),
                    Column("m_score", "integer", "M", "1 to 5, 5 is highest spending"),
                    Column("rfm_score", "string", "RFM", "The three scores concatenated"),
                    Column("segment", "string", "Segment"),
                    Column("last_purchase_date", "string", "Last purchase"),
                    Column("reference_date", "string", "Reference date"),
                ),
                default_sort="monetary",
            ),
            Output(
                name="by_segment",
                title="Segments",
                description="One row per segment.",
                columns=(
                    Column("segment", "string", "Segment"),
                    Column("customers", "integer", "Customers", unit="count"),
                    Column("total_monetary", "float", "Total value", unit="currency"),
                    Column("average_monetary", "float", "Average value", unit="currency"),
                    Column("average_frequency", "float", "Average frequency"),
                    Column("average_recency_days", "float", "Average recency (days)"),
                ),
                default_sort="customers",
            ),
        ),
        optional=True,
    ),
}

#: The validation job is not a user-selectable analysis: it runs once per
#: dataset version during ingestion. Its outputs are described here so the UI
#: can browse them with the same machinery.
VALIDATION_OUTPUTS: dict[str, Output] = {
    "validated": Output(
        name="validated",
        title="Validated records",
        description="The canonical, de-duplicated, classified dataset.",
        columns=VALIDATED_COLUMNS,
    ),
    "rejected": Output(
        name="rejected",
        title="Rejected records",
        description="Records that failed a cleaning rule, with the reason.",
        columns=REJECTED_COLUMNS,
    ),
}

#: Order in which analyses are offered and executed.
ANALYSIS_ORDER: tuple[str, ...] = (
    "customer_analysis",
    "monthly_sales",
    "product_analysis",
    "country_analysis",
    "repeat_customers",
    "rfm_analysis",
)


def get_analysis(key: str) -> Analysis:
    try:
        return ANALYSES[key]
    except KeyError as missing:
        raise KeyError(f"unknown analysis {key!r}") from missing


def all_analyses() -> list[Analysis]:
    return [ANALYSES[key] for key in ANALYSIS_ORDER]


def validate_selection(keys: list[str]) -> list[str]:
    """Normalises a requested analysis list into registry order."""
    unknown = [key for key in keys if key not in ANALYSES]
    if unknown:
        raise ValueError(f"unknown analyses: {', '.join(sorted(unknown))}")
    if not keys:
        raise ValueError("at least one analysis must be selected")
    requested = set(keys)
    return [key for key in ANALYSIS_ORDER if key in requested]
