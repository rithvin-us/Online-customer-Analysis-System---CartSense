# Business rules

Every rule below is implemented in `mapreduce/src/main/java/com/cartscope/jobs/ValidationJob.java`
and is reported as a Hadoop counter, so each one can be shown to have fired, and
how often, for any dataset.

The rules exist so that a figure can be explained. The question at a
demonstration is never "what is the revenue" — it is "why is it *that*", and
these rules are the answer.

---

## Parsing

| Rule | Why |
|---|---|
| Fields are split with an RFC 4180 parser, not on commas | `"SET/6 RED SPOTTY PAPER CUPS, LARGE"` is one field. Splitting on commas corrupts roughly 2% of the UCI dataset's rows and silently shifts every column after the description. |
| A line with an unterminated quote is **rejected** as `MALFORMED_QUOTING` | Hadoop's `TextInputFormat` delivers records split on newlines, so a quoted field containing a literal newline arrives truncated. Rejecting it is honest; guessing is not. The ingestion profiler counts such records up front and reports them, so they are never a surprise. |
| The header is detected by content, not by line number | With multiple input splits only the split containing byte 0 can see the header, so an offset test would be unreliable. |
| A UTF-8 byte-order mark is stripped | Spreadsheet exports frequently carry one. |
| Encoding is detected from `utf-8-sig`, `utf-8`, `cp1252`, `latin-1` in that order | The real UCI exports are cp1252, not UTF-8. A UTF-8-only reader fails on them. |

## Dates

`InvoiceDate` is parsed against an ordered list of patterns, and the first that
matches a record is remembered so later records in the same task cost one
attempt.

| Family | Patterns |
|---|---|
| Month-first (default) | `M/d/uuuu H:mm`, `M/d/uuuu H:mm:ss`, `M/d/uu H:mm`, `M/d/uuuu` |
| ISO-8601 | `uuuu-MM-dd HH:mm:ss`, `uuuu-MM-dd'T'HH:mm:ss`, `uuuu-MM-dd HH:mm`, `uuuu-MM-dd` |
| Day-first | `d/M/uuuu H:mm`, and so on |

`3/4/2011` is genuinely ambiguous. Month-first is tried first because that is the
dominant form for this dataset, and the upload form asks rather than guessing
silently. The choice is recorded in the run manifest, because it changes every
monthly figure.

A date that matches no pattern **rejects the record** (`UNPARSEABLE_INVOICE_DATE`).
No record is ever given a substituted or defaulted date.

## Rejection rules

A rejected record is written to `/rejected` with the rule that rejected it and
the original line. Nothing is silently dropped.

| Counter | Rule | Reasoning |
|---|---|---|
| `WRONG_FIELD_COUNT` | The row does not have exactly eight fields | Either the schema is wrong or the row is corrupt; either way the columns cannot be trusted. |
| `MISSING_INVOICE_NO` | `InvoiceNo` is empty | The invoice is the unit of an order; without it the record cannot be grouped. |
| `MISSING_STOCK_CODE` | `StockCode` is empty | It is the product identifier. |
| `UNPARSEABLE_QUANTITY` | `Quantity` is not an integer | |
| `ZERO_QUANTITY` | `Quantity` is 0 | A line with no units carries no value. |
| `UNPARSEABLE_UNIT_PRICE` | `UnitPrice` is not a number | |
| `NON_POSITIVE_UNIT_PRICE` | `UnitPrice` is not strictly positive | A zero or negative price cannot contribute revenue. In the UCI dataset this removes roughly 2,500 rows, most of them promotional or adjustment lines. The test is written `!(price > 0)`, which also catches `NaN`. |
| `UNPARSEABLE_INVOICE_DATE` | No supported pattern matched | |
| `DUPLICATE_RECORDS` | An identical record appeared earlier | See below. |

`HEADER_RECORDS` and `BLANK_LINES` are counted and skipped rather than rejected:
they are not data.

## Duplicate detection

Duplicates are collapsed **in the shuffle**, not in the backend. The mapper emits
the whole canonical record as the key, so every identical copy hashes to the same
reducer; the reducer writes the record once and reports the surplus copies to
`/rejected` with their count.

A combiner sums the per-copy counts on the map side, so the copies themselves do
not cross the network — only the counts do.

This is the only part of cleaning that needs a global view of the data, which is
exactly what a shuffle provides.

## Classification

Each surviving record is given **exactly one** class.

```
cancellation = InvoiceNo starts with 'C' or 'c'
negative     = Quantity < 0

class = RETURN  when cancellation OR negative
        SALE    otherwise
```

The exclusivity is the important part. A cancelled line with a negative quantity
is a single reversal, and because the class is one label rather than two
independent flags, it contributes to returns **once**. That is what stops
cancellations and negative quantities being double counted.

`CANCELLATION_INVOICES` and `NEGATIVE_QUANTITY_LINES` are still counted
separately as diagnostics, so the overlap between them is visible.

## Missing CustomerID

A missing `CustomerID` **does not** reject a record. The sale happened; the buyer
is simply unknown. In the UCI dataset roughly 135,000 rows are affected — a
quarter of the file — so rejecting them would understate every revenue figure by
about a fifth.

Instead the field is preserved as empty and each analysis decides:

| Analysis | Records without a CustomerID | Why |
|---|---|---|
| Customer spending | **Excluded** | A customer-level figure cannot be attributed to an unknown customer. |
| Repeat customers | **Excluded** | Loyalty is a property of an identified customer. |
| RFM | **Excluded** | Same. |
| Monthly sales | **Included** in money; excluded from the customer count | The revenue is real. The count is labelled "identifiable customers" to say what it measures. |
| Country sales | **Included** in money; excluded from the customer count | The country of a sale is known even when the buyer is not. |
| Product popularity | **Included** | Product performance does not depend on who bought it. |

Every exclusion is reported as a counter (`SKIPPED_MISSING_CUSTOMER_ID`), so the
size of the effect is always on screen next to the figure.

A `CustomerID` rendered as `17850.0` is normalised to `17850`. That trailing
`.0` is a spreadsheet formatting artefact; without normalising it the same
customer would appear under two identities across differently exported versions
of the same data.

## Canonical record

The validation job writes one tab-separated record per accepted row:

| # | Field | Notes |
|---|---|---|
| 0 | `invoice_no` | |
| 1 | `stock_code` | |
| 2 | `description` | Tabs and newlines replaced with spaces |
| 3 | `quantity` | Signed |
| 4 | `invoice_ts` | Epoch milliseconds, UTC |
| 5 | `invoice_date` | `uuuu-MM-dd HH:mm:ss` |
| 6 | `month` | `uuuu-MM`, the key of the monthly analysis |
| 7 | `unit_price` | |
| 8 | `customer_id` | Empty when absent |
| 9 | `country` | `Unspecified` when absent |
| 10 | `line_value` | `quantity × unit_price`, signed |
| 11 | `abs_value` | `|quantity| × unit_price` |
| 12 | `txn_class` | `SALE` or `RETURN` |

Doing the parsing, the date interpretation and the line arithmetic **once**, here,
means the six analytical jobs read a tab-separated file with no quoting rules and
no ambiguity — and, more importantly, that all six compute revenue from exactly
the same numbers. Two analyses cannot disagree about what a line was worth.

The raw upload under `/raw` is never modified. The canonical form is an
additional representation.

---

## Revenue

```
Gross revenue = Σ line_value   over records classified SALE
Returns       = Σ abs_value    over records classified RETURN
Net revenue   = Gross revenue − Returns
```

Because classification is exclusive, no record contributes to both sums.

### Derived definitions

| Term | Definition | Why it is defined this way |
|---|---|---|
| **Completed invoice** | A distinct invoice whose net value is positive | An invoice that was wholly cancelled is not a purchase. Counting it would inflate order counts and deflate average order value. |
| **Total orders** (per customer) | Count of completed invoices | Counting *records* instead would multiply every customer's order count by their basket size. The invoice roll-up stage exists to make this correct. |
| **Average order value** | Gross spending ÷ completed invoices | Zero when the customer has no completed invoice, rather than undefined. |
| **Repeat customer** | Two or more distinct completed invoices | Stated as a threshold on completed invoices, not on records or on any invoice. |
| **Average purchase frequency** | Completed invoices ÷ customers with at least one completed invoice | Dividing by *all* identified customers would let customers who only ever cancelled drag the average down despite never having purchased. |
| **Identifiable customers** | Distinct non-empty `CustomerID` values | Named this way so the figure does not read as "all customers". |
| **Distinct invoices** | Count of shuffle groups on the invoice key | A count of groups, never a count of lines. |

### Product descriptions

`StockCode` is the identifier; `Description` is a label, and one stock code
carries several spellings of its description in the source data. The label is
collapsed to the **lexicographically smallest non-empty description**.

That rule is chosen for a specific reason: it is associative, commutative and
deterministic, which is what makes it safe to apply inside a combiner. A rule
like "first one seen" would make the displayed product name depend on which
combiner happened to run first, so two runs over identical data could disagree.

### RFM scoring

Scores are **population quintiles**, not fixed thresholds, so they adapt to
whichever dataset is loaded.

* **R** — days since the customer's last *completed* purchase, counted from a
  reference date. The reference date is the latest completed purchase anywhere in
  the dataset, **not** the time of the run: that is what makes repeating a run
  over the same data reproduce the same scores. The most recent fifth scores 5.
* **F** — distinct completed invoices. The most frequent fifth scores 5.
* **M** — net spend. The highest-spending fifth scores 5.

Segments, first match wins:

| Condition | Segment |
|---|---|
| R ≥ 4 and F ≥ 4 and M ≥ 4 | High-value customers |
| F ≥ 4 and M ≥ 3 | Loyal customers |
| R ≥ 4 and F ≤ 2 | New customers |
| R ≥ 3 and F ≥ 3 | Potential loyalists |
| R ≤ 2 and (F ≥ 3 or M ≥ 3) | At-risk customers |
| otherwise | Needs attention |

No model is trained and nothing is inferred. Any customer's segment can be
re-derived by hand from the three scores in their output row. A customer who
never completed a purchase has no defined recency and is **left unscored**,
reported through the `CUSTOMERS_WITHOUT_PURCHASE_EXCLUDED` counter, rather than
given a fabricated score.

---

## Expected figures for the UCI Online Retail dataset

Rounded, for the default month-first date interpretation. Your exact numbers
depend on which CSV export of the dataset you load — the counters in the UI are
the authority for the data you actually loaded.

| Figure | Order of magnitude |
|---|---|
| Raw rows | ~541,900 |
| Rejected: non-positive unit price | ~2,500 |
| Rejected: duplicates | ~5,200 |
| Accepted records | ~534,000 |
| Rows without a CustomerID | ~135,000 |
| Cancellation lines | ~9,300 |
| Identified customers | ~4,370 |
| Distinct products | ~4,000 |
| Countries | ~38 |
| Months covered | Dec 2010 – Dec 2011 |

If your run differs materially from these, the data quality report and the
classification counters will say which rule accounts for it.
