import { CounterBars, DonutChart } from "./charts";
import { Field, FieldGrid } from "./field";
import { formatCompact, formatInteger } from "@/lib/format";

/**
 * How the Hadoop validation job classified the records.
 *
 * Every number here is a counter the job reported. The rules behind them are
 * stated next to them, because at a demonstration the question is always "why
 * were those rows rejected?".
 */
const ACCEPTED: { key: string; label: string; hint: string }[] = [
  {
    key: "ACCEPTED_RECORDS",
    label: "Accepted",
    hint: "Records that passed every cleaning rule, before duplicate removal.",
  },
  {
    key: "FULFILLED_SALES",
    label: "Fulfilled sales",
    hint: "Positive quantity, positive price, not a cancellation invoice.",
  },
  {
    key: "RETURNS_AND_CANCELLATIONS",
    label: "Returns and cancellations",
    hint: "One exclusive class per record, so a cancelled negative line counts once.",
  },
  {
    key: "CANCELLATION_INVOICES",
    label: "Cancellation lines",
    hint: "Lines whose InvoiceNo begins with C.",
  },
  {
    key: "NEGATIVE_QUANTITY_LINES",
    label: "Negative quantity lines",
    hint: "Lines with a quantity below zero.",
  },
  {
    key: "MISSING_CUSTOMER_ID",
    label: "No CustomerID",
    hint: "Kept for country and monthly figures, excluded from customer-level analyses.",
  },
  {
    key: "DUPLICATE_RECORDS",
    label: "Duplicates removed",
    hint: "Collapsed in the reducer; identical records hash to the same key.",
  },
];

const REJECTED: { key: string; label: string; hint: string }[] = [
  {
    key: "NON_POSITIVE_UNIT_PRICE",
    label: "Price not positive",
    hint: "A zero or negative unit price cannot contribute revenue.",
  },
  {
    key: "ZERO_QUANTITY",
    label: "Zero quantity",
    hint: "A line with no units carries no value.",
  },
  {
    key: "UNPARSEABLE_INVOICE_DATE",
    label: "Unparseable date",
    hint: "No supported pattern matched; the record is rejected, never dated by guesswork.",
  },
  { key: "UNPARSEABLE_QUANTITY", label: "Unparseable quantity", hint: "Not an integer." },
  { key: "UNPARSEABLE_UNIT_PRICE", label: "Unparseable price", hint: "Not a number." },
  {
    key: "WRONG_FIELD_COUNT",
    label: "Wrong field count",
    hint: "The row did not have the eight expected fields.",
  },
  {
    key: "MALFORMED_QUOTING",
    label: "Malformed quoting",
    hint: "A quoted field was left open, usually an embedded newline.",
  },
  { key: "MISSING_INVOICE_NO", label: "No InvoiceNo", hint: "" },
  { key: "MISSING_STOCK_CODE", label: "No StockCode", hint: "" },
  { key: "HEADER_RECORDS", label: "Header rows skipped", hint: "" },
  { key: "BLANK_LINES", label: "Blank lines skipped", hint: "" },
];

export function ClassificationPanel({
  counters,
}: {
  counters: Record<string, number | null>;
}) {
  const present = (entries: typeof ACCEPTED) =>
    entries.filter((entry) => (counters[entry.key] ?? 0) > 0 || entry.key in counters);

  return (
    <div className="space-y-5">
      <ClassificationCharts counters={counters} />

      <section>
        <p className="pb-2.5 text-xs font-medium">Classified</p>
        <FieldGrid>
          {present(ACCEPTED).map((entry) => (
            <Field key={entry.key} label={entry.label} hint={entry.hint}>
              {formatInteger(counters[entry.key])}
            </Field>
          ))}
        </FieldGrid>
      </section>

      <section>
        <p className="pb-2.5 text-xs font-medium">Rejected, by rule</p>
        <FieldGrid>
          {present(REJECTED).map((entry) => (
            <Field key={entry.key} label={entry.label} hint={entry.hint}>
              {formatInteger(counters[entry.key])}
            </Field>
          ))}
        </FieldGrid>
      </section>

      <p className="border-t border-border pt-3 text-2xs leading-relaxed text-muted-foreground">
        Revenue is computed from these classes as: gross revenue is the sum of fulfilled
        sale line values; returns are the sum of the absolute value of reversal lines; net
        revenue is gross less returns. Because each record carries exactly one class, a
        cancelled negative-quantity line is counted as a reversal once and never twice.
      </p>
    </div>
  );
}

/**
 * The same counters as the fields below, drawn.
 *
 * Two charts, because the counters answer two different questions and mixing
 * them would invite a false comparison:
 *
 *  - how the *accepted* records divide. A record is classified either a
 *    fulfilled sale or a reversal and never both, so these two counters add up
 *    to ACCEPTED_RECORDS exactly and a share of the whole is a true statement
 *    about them;
 *  - which rule rejected the records that did not get that far. Each rejected
 *    record is counted under exactly one rule, so the bars are a partition of
 *    the rejections, not overlapping tallies.
 *
 * Counters that overlap those classes — lines without a CustomerID, which are
 * accepted and kept, and the duplicate copies the reducer collapsed — are left
 * to the fields below rather than drawn as if they were another slice.
 */
function ClassificationCharts({
  counters,
}: {
  counters: Record<string, number | null>;
}) {
  const sales = counters.FULFILLED_SALES ?? 0;
  const reversals = counters.RETURNS_AND_CANCELLATIONS ?? 0;
  const accepted = counters.ACCEPTED_RECORDS ?? sales + reversals;

  const classes =
    accepted > 0
      ? [
          {
            label: "Fulfilled sales",
            value: sales,
            color: "hsl(var(--series-1))",
            percent: (sales / accepted) * 100,
          },
          {
            label: "Returns and cancellations",
            value: reversals,
            color: "hsl(var(--series-2))",
            percent: (reversals / accepted) * 100,
          },
        ].filter((slice) => slice.value > 0)
      : [];

  const rejections = REJECTED.map((entry) => ({
    label: entry.label,
    value: counters[entry.key] ?? null,
  }));

  const hasRejections = rejections.some(
    (entry) => typeof entry.value === "number" && entry.value > 0,
  );

  if (classes.length === 0 && !hasRejections) return null;

  return (
    <div className="grid grid-cols-1 items-start gap-4 rounded-md border border-border bg-surface px-4 py-3 lg:grid-cols-2">
      {classes.length > 0 && (
        <DonutChart
          title="Accepted records by class"
          note="Each accepted record carries exactly one class, so these add up to the accepted total."
          data={classes}
          format={formatInteger}
          centerValue={formatCompact(accepted)}
          centerLabel="Accepted"
          height={238}
        />
      )}
      <CounterBars
        title="Rejections by rule"
        note="One rule per rejected record. Rules that rejected nothing are not drawn."
        items={rejections}
        valueLabel="Records"
        color="hsl(var(--series-2))"
        labelWidth={150}
      />
    </div>
  );
}
