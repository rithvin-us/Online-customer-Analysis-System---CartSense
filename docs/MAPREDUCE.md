# The MapReduce design

Every analytical figure CartScope reports is produced by the Java jobs in
`mapreduce/`. This document explains how, and — more usefully — *why each job
needs the number of stages it has*. "Why is customer spending three MapReduce
jobs and not one?" is the question worth being able to answer.

Run a job by hand to see it work:

```bash
docker compose exec worker hadoop jar /opt/cartscope/cartscope-mapreduce.jar
# usage: hadoop jar cartscope-mapreduce.jar <analysis> [options]
# analyses: validate, customer_analysis, monthly_sales, product_analysis,
#           country_analysis, repeat_customers, rfm_analysis
```

---

## The shared pieces

### `Aggregate` — one value type for every job

`com.cartscope.io.Aggregate` carries three things:

* a vector of **additive** metrics, merged by addition;
* a vector of **maximum-merged** metrics, merged by `Math.max`;
* one optional **text label**, collapsed to the lexicographically smallest
  non-empty value.

All three merge rules are associative, commutative and deterministic, which is
precisely the condition a combiner requires. That is what makes one reducer —
`AggregateSumReducer` — reusable as the combiner of every stage in the project.

The maximum-merged vector exists for a specific bug it prevents. RFM's recency
component is the *latest* purchase timestamp, and a timestamp must never be
summed. Keeping it in a separate vector means no combiner can add two dates
together even by accident.

### Combiners

A combiner is set on every stage whose reduce is a pure merge of `Aggregate`
values. It is deliberately **not** set on the RFM scoring stage, because quintile
boundaries are a property of the whole customer population and a partial
aggregation on the map side cannot help.

### Intermediate output is text

Stages write tab-separated text to `/cartscope/jobs/<run_id>/<analysis>/<stage>`
rather than sequence files. Text costs a little more I/O; what it buys is that
any stage of any pipeline can be inspected from the command line during a
demonstration:

```bash
docker compose exec hadoop-client \
  hdfs dfs -cat /cartscope/jobs/<run_id>/customer_analysis/invoice-rollup/part-r-00000 | head
```

### Reducer counts

Three reducers by default, one per worker, so the reduce phase is distributed
too. Two kinds of stage override that to **one** reducer, each for a reason:

| Stage kind | Reducers | Reason |
|---|---|---|
| Ranking | 1 | A rank is a *total* order. With several reducers each would produce its own independently sorted partition. For a result of tens of thousands of rows one reducer is the right trade-off; at a scale where it is not, the same stage would run with `TotalOrderPartitioner` and an `InputSampler`. |
| Population summary | 1 | A summary over all customers is one group. The combiner does the per-split arithmetic first, so the single reducer receives a handful of partial sums rather than one row per customer. |
| Monthly and country roll-up | 1 | A few dozen keys, and one reducer yields a single ordered file — which is what a time series needs. |

### Result layout

Final output goes to `/cartscope/results/<run_id>/<analysis>/<output>`. The driver
**refuses to start** if its result directory already exists, so a successful
analytical output can never be overwritten; a repeat of the same analysis gets a
new run id.

### Counters

After each stage the driver reads the completed `Job` object's counters and writes
them, verbatim, to a JSON report. The backend stores that report and never
computes a counter of its own. A counter Hadoop did not report is stored and
displayed as absent, not as zero.

The job id to YARN application id mapping is exact rather than a guess: in MRv2
`job_1730000000000_0003` is run by `application_1730000000000_0003` — the same
cluster timestamp and sequence number.

---

## `validate` — one job

**Input** the raw CSV in HDFS · **Output** `/validated` and `/rejected`

| | |
|---|---|
| Mapper | `ValidationJob.CanonicaliseMapper` |
| Combiner | `AggregateSumReducer` |
| Reducer | `ValidationJob.DedupeReducer` |
| Output format | `LazyOutputFormat` + `MultipleOutputs` |

The mapper parses one CSV line with a quote-aware parser, applies the cleaning
rules, and emits a **tagged key**: `V\t<canonical record>` for an accepted record,
`R\t<reason>\t<original line>` for a rejected one. The value is a count of one.

Both kinds of record travel through the shuffle. That costs a little extra
network for the rejects, and buys two things: all of the job's output is produced
by one output committer, and identical rejected lines are counted rather than
repeated.

The reducer sums the counts for a key. For an accepted record it writes the
record once to the `validated` named output and reports any surplus copies as
duplicates; for a rejected record it writes one line carrying the reason and the
number of copies that shared the fault.

`MultipleOutputs.setCountersEnabled(job, true)` makes Hadoop report how many
records each named output received, and those counters are what the product uses
for the validated and rejected record counts — the backend does not count rows
itself.

On success the `validated` and `rejected` subtrees are **renamed** into the
dataset version directory. A rename on HDFS is a NameNode metadata operation, so
no data is copied.

---

## `customer_analysis` — three jobs

### Stage 1, `invoice-rollup`

Key `customerId \t invoiceNo` · metrics `[gross, returns, saleLines, returnLines]`

**This stage exists entirely to make the invoice count correct.** An invoice has
many lines. Counting invoices by counting records would multiply every customer's
order count by their basket size — on the UCI dataset, by about four. Grouping on
the pair first collapses each invoice to exactly one row, after which counting is
trivial.

The reducer re-keys each row by customer and attaches two invoice-level flags
that the next stage sums: whether the invoice is a completed order
(`gross − returns > 0`), and that it is one invoice.

Records with no `CustomerID` are skipped here and counted in
`SKIPPED_MISSING_CUSTOMER_ID`.

### Stage 2, `customer-rollup`

Key `customerId`. Sums the invoice rows and emits the reported row:

`customer_id, total_orders, gross_spending, returns, net_spending,
average_order_value, returned_lines, invoices_touched`

### Stage 3, `rank`

Sorting is the shuffle's job. The mapper emits `−net_spending` as a
`DoubleWritable` key — negated because Hadoop sorts keys ascending — and the
single reducer walks them in order, numbering the rows as it goes. The rank is
prepended so the ordering survives export.

---

## `monthly_sales` — two jobs

A month's figures include two **distinct** counts: how many invoices, and how
many identifiable customers. A distinct count cannot be produced by summing; it
needs the duplicates removed first, which means a shuffle.

### Stage 1, `distinct-rollup`

The mapper emits **two kinds of key** per record:

```
<month> \t I \t <invoice_no>     carrying the money and quantity metrics
<month> \t C \t <customer_id>    carrying no metrics
```

Hadoop groups each key, so one invoice produces exactly one group no matter how
many lines it had, and one customer produces exactly one group per month no
matter how often they bought. The reducer turns each group into a single row
keyed by month with a 1 in the right counting slot.

### Stage 2, `month-rollup`

Sums the rows into one row per month. One reducer, so the series comes out in
chronological order in a single file:

`month, gross_revenue, returns, net_revenue, distinct_invoices,
completed_invoices, identifiable_customers, quantity_sold, quantity_returned,
sale_lines, return_lines`

---

## `product_analysis` — eight jobs

1. **`invoice-rollup`** — group by `(stock_code, invoice_no)`, so "number of
   distinct invoices this product appeared on" is a count of groups rather than a
   count of lines. The description travels as the `Aggregate` label.
2. **`product-rollup`** — one row per stock code.
3. **`rank-revenue`**, **`rank-quantity`**, **`rank-returns`**, **`rank-reach`**
   — four orderings of the same rows. The top ten by revenue, by units, by
   returned units and by the number of distinct orders a product appeared on are
   the first ten rows of those four files. Reach is a different question from
   volume: one customer ordering five hundred of something is not the same event
   as a hundred customers ordering five.
4. **`classify`** — the products that *actually sold*, in descending gross
   revenue order, each given an ABC revenue class, a price band, a volume band
   and a return class, with the cumulative revenue share the ABC class is read
   from printed on the same row.
5. **`band-summary`** — how many products, units and pounds sit in each band of
   each of those four classifications, and each band's share of the catalogue.

### Why the classification needs its own stage

A band on a product's own figures — its price, its volume — could in principle
be assigned in the roll-up reducer. The ABC class could not: it is a property of
where the product sits in the *whole* catalogue's revenue distribution, which no
reducer handling one product can see. So `classify` runs with a single reducer
that walks the catalogue in revenue order, exactly as the RFM scoring stage walks
the customer population, and with the same cost: one short row per product held
in memory, bounded by the size of the catalogue rather than by the number of
transactions — about 4,000 rows for the UCI dataset.

`band-summary` holds data too, but trivially: a share is a fraction of a total
no single band's reduce group can see, so the bands are held until the groups are
exhausted and written in `cleanup`. That is at most a few dozen rows for any
dataset.

### Products that never sold

A stock code seen only on reversal lines has no selling price, no sold volume and
no revenue to contribute. Classifying it would mean inventing figures for it, so
it is excluded from `classify` and counted as `PRODUCTS_NEVER_SOLD_EXCLUDED`
instead. It stays in `by_product` and in the return ranking, which is where it
belongs.

### Gross, not net, under the shares

The revenue shares and the Pareto curve are taken over **gross** revenue. A
cumulative share has to be monotonic to mean anything, and net revenue is
negative for a product whose returns in the loaded period outweigh its sales, so
a cumulative *net* share could fall as it went down the ranking. Net revenue is
reported on every row beside the gross figure, so neither is hidden.

---

## `country_analysis` — three jobs

The same two-key technique as the monthly analysis, keyed on country, then a
ranking by net revenue.

Unlike the customer analyses this one deliberately **keeps** records with no
`CustomerID`: the country of a sale is known even when the buyer is not, so
excluding them would understate every country's revenue. Only the distinct
customer count ignores them, and it is labelled "identifiable customers" to say
so.

---

## `repeat_customers` — three jobs

"At least two distinct completed invoices" cannot be evaluated in a single pass:
a line does not know how many invoices its customer has, and an invoice has many
lines. The pipeline narrows the data twice before drawing a conclusion.

1. **`invoice-rollup`** — many lines become one invoice, and the invoice's net
   value decides whether it is completed.
2. **`customer-rollup`** — many invoices become one customer, with a completed
   invoice count and a net spend.
3. **`cohort-summary`** — a single group over all customers produces the
   population figures. The combiner does the per-split arithmetic, so the one
   reducer receives partial sums rather than one row per customer.

The summary is emitted as `metric \t value` rows, which keeps the file self
describing.

---

## `rfm_analysis` — four jobs

1. **`invoice-rollup`** — lines become invoices. The latest timestamp travels in
   the maximum-merged slot. Recency counts the last *completed* purchase, so a
   cancellation does not refresh a customer's recency.
2. **`customer-rollup`** — frequency, monetary value and last purchase per
   customer.
3. **`score`** — a single reducer computes the quintile boundaries over the
   customer population and assigns the segments. **This is the one stage that
   holds data in memory**: one short row per customer, bounded by the number of
   customers rather than by the number of transactions — about 4,400 for the UCI
   dataset, tens of thousands for a one-million-row synthetic one, so a few
   megabytes. For a customer population large enough to matter, the same result
   would come from computing approximate quantiles in a separate pass and
   broadcasting the boundaries to many reducers.
4. **`segment-summary`** — size and value of each segment.

---

## Handling bad records

No mapper throws on bad input. A record that cannot be parsed is counted and
skipped:

| Counter | Where |
|---|---|
| `MALFORMED_VALIDATED_RECORDS` | Every analytical mapper, if a canonical line does not parse |
| `MALFORMED_STAGE_ROWS` | `KeyedAggregateMapper`, if a previous stage's row does not parse |
| `UNPARSEABLE_SORT_KEY`, `SHORT_ROWS` | `RankStage`, if a row cannot be ranked |

One corrupt line never fails a task, and the count is always visible in the UI,
so a silent data problem cannot hide.

---

## Job and stage inventory

| Analysis | Stages |
|---|---|
| `validate` | `canonicalise` |
| `customer_analysis` | `invoice-rollup`, `customer-rollup`, `rank` |
| `monthly_sales` | `distinct-rollup`, `month-rollup` |
| `product_analysis` | `invoice-rollup`, `product-rollup`, `rank-revenue`, `rank-quantity`, `rank-returns`, `rank-reach`, `classify`, `band-summary` |
| `country_analysis` | `distinct-rollup`, `country-rollup`, `rank` |
| `repeat_customers` | `invoice-rollup`, `customer-rollup`, `cohort-summary` |
| `rfm_analysis` | `invoice-rollup`, `customer-rollup`, `score`, `segment-summary` |

**24 MapReduce jobs**, each with its own mapper, reducer and driver
configuration. A run of all six analyses submits 23 YARN applications.
