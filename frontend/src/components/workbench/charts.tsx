"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatCompact, formatCurrency, formatInteger } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Charts over reducer output.
 *
 * These are supporting views, not the product: each one sits directly above the
 * table of the same rows, so every value is readable without hovering anything.
 *
 * Conventions held across all of them:
 *  - categorical hues are assigned in a fixed order and never cycled, so a
 *    series keeps its colour when the data behind it changes;
 *  - a single-series chart gets one colour and no legend — colouring bars by
 *    their own value would encode length twice and say nothing new;
 *  - never two y-scales on one plot;
 *  - 2px lines, bars capped at 24px with a 4px rounded data-end, solid hairline
 *    gridlines, and axis text in muted ink rather than in a series colour.
 */

const SERIES = {
  one: "hsl(var(--series-1))",
  two: "hsl(var(--series-2))",
  three: "hsl(var(--series-3))",
} as const;

const GRID = "hsl(var(--chart-grid))";
const AXIS_INK = "hsl(var(--chart-axis))";
const SURFACE = "hsl(var(--surface))";

const AXIS_TICK = { fill: AXIS_INK, fontSize: 10 } as const;
const BAR_CAP = 22;

function ChartFrame({
  title,
  note,
  height,
  children,
  className,
}: {
  title: string;
  note?: string;
  height: number;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <figure className={cn("m-0", className)}>
      <figcaption className="pb-2">
        <p className="text-xs font-medium">{title}</p>
        {note && <p className="pt-0.5 text-2xs text-muted-foreground">{note}</p>}
      </figcaption>
      {/* The height includes the axis band, so the card never grows a nested
          scrollbar just to show the x-axis labels. */}
      <div style={{ height }}>{children}</div>
    </figure>
  );
}

interface TooltipDatum {
  name?: string | number;
  value?: number | string;
  color?: string;
  dataKey?: string | number;
}

function TooltipCard({
  active,
  label,
  payload,
  format,
}: {
  active?: boolean;
  label?: string | number;
  payload?: TooltipDatum[];
  format: (value: number) => string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="rounded-md border border-border bg-surface-raised px-2.5 py-2 shadow-md">
      {label !== undefined && (
        <p className="pb-1 text-2xs font-medium text-foreground">{String(label)}</p>
      )}
      <ul className="space-y-0.5">
        {payload.map((entry, index) => (
          <li
            key={`${entry.dataKey ?? index}`}
            className="flex items-center gap-2 text-2xs"
          >
            <span
              className="size-2 shrink-0 rounded-sm"
              style={{ background: entry.color }}
              aria-hidden
            />
            <span className="text-muted-foreground">{entry.name}</span>
            <span className="ml-auto tabular text-foreground">
              {typeof entry.value === "number" ? format(entry.value) : String(entry.value)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** A legend built from swatches and text ink, never coloured text. */
function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 pb-1.5">
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5 text-2xs">
          <span
            className="h-0.5 w-3.5 rounded-full"
            style={{ background: item.color }}
            aria-hidden
          />
          <span className="text-muted-foreground">{item.label}</span>
        </li>
      ))}
    </ul>
  );
}

type Row = Record<string, string | number | null>;

function numeric(row: Row, key: string): number {
  const value = row[key];
  return typeof value === "number" ? value : 0;
}

function text(row: Row, key: string): string {
  const value = row[key];
  return value === null || value === undefined ? "" : String(value);
}

// ---------------------------------------------------------------------------
// Monthly revenue
// ---------------------------------------------------------------------------

/**
 * Gross revenue, returns and net revenue by month.
 *
 * All three are money in the same currency, so they share one axis. Returns sit
 * close to zero against the other two, which is itself the thing worth seeing.
 */
export function MonthlyRevenueChart({ rows }: { rows: Row[] }) {
  const data = rows.map((row) => ({
    month: text(row, "month"),
    gross: numeric(row, "gross_revenue"),
    returns: numeric(row, "returns"),
    net: numeric(row, "net_revenue"),
  }));

  if (data.length === 0) return null;

  const last = data[data.length - 1]!;

  return (
    <ChartFrame
      title="Revenue by month"
      note="Computed by the monthly sales job. Returns are the absolute value of reversal lines, so net is gross less returns."
      height={240}
    >
      <Legend
        items={[
          { label: "Gross revenue", color: SERIES.one },
          { label: "Net revenue", color: SERIES.three },
          { label: "Returns", color: SERIES.two },
        ]}
      />
      <ResponsiveContainer width="100%" height="88%">
        <LineChart data={data} margin={{ top: 6, right: 46, bottom: 4, left: 4 }}>
          <CartesianGrid stroke={GRID} strokeWidth={1} vertical={false} />
          <XAxis
            dataKey="month"
            tick={AXIS_TICK}
            stroke={GRID}
            tickLine={false}
            interval="preserveStartEnd"
            minTickGap={16}
          />
          <YAxis
            tick={AXIS_TICK}
            stroke={GRID}
            tickLine={false}
            width={48}
            tickFormatter={(value: number) => formatCompact(value)}
          />
          <Tooltip
            cursor={{ stroke: AXIS_INK, strokeWidth: 1 }}
            content={({ active, label, payload }) => (
              <TooltipCard
                active={active}
                label={label}
                payload={payload as TooltipDatum[]}
                format={formatCurrency}
              />
            )}
          />
          <Line
            type="monotone"
            dataKey="gross"
            name="Gross revenue"
            stroke={SERIES.one}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: SURFACE }}
          />
          <Line
            type="monotone"
            dataKey="net"
            name="Net revenue"
            stroke={SERIES.three}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: SURFACE }}
          />
          <Line
            type="monotone"
            dataKey="returns"
            name="Returns"
            stroke={SERIES.two}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: SURFACE }}
          />
        </LineChart>
      </ResponsiveContainer>
      <p className="pt-1 text-2xs text-muted-foreground">
        Final month {last.month}: net {formatCurrency(last.net)}.
      </p>
    </ChartFrame>
  );
}

// ---------------------------------------------------------------------------
// Horizontal ranking bars
// ---------------------------------------------------------------------------

function RankedBars({
  title,
  note,
  data,
  valueLabel,
  format,
  color = SERIES.one,
  labelWidth = 150,
}: {
  title: string;
  note?: string;
  data: { label: string; value: number; full: string }[];
  valueLabel: string;
  format: (value: number) => string;
  color?: string;
  labelWidth?: number;
}) {
  if (data.length === 0) return null;
  // 26px per row plus the axis band, so the container always fits its content.
  const height = data.length * 26 + 34;

  return (
    <ChartFrame title={title} note={note} height={height}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 2, right: 72, bottom: 2, left: 0 }}
          barCategoryGap={6}
        >
          <CartesianGrid stroke={GRID} strokeWidth={1} horizontal={false} />
          <XAxis
            type="number"
            tick={AXIS_TICK}
            stroke={GRID}
            tickLine={false}
            tickFormatter={(value: number) => formatCompact(value)}
          />
          <YAxis
            type="category"
            dataKey="label"
            tick={AXIS_TICK}
            stroke={GRID}
            tickLine={false}
            width={labelWidth}
            interval={0}
          />
          <Tooltip
            cursor={{ fill: "hsl(var(--muted))", fillOpacity: 0.4 }}
            content={({ active, label, payload }) => (
              <TooltipCard
                active={active}
                label={
                  (payload?.[0]?.payload as { full?: string } | undefined)?.full ??
                  (label as string)
                }
                payload={payload as TooltipDatum[]}
                format={format}
              />
            )}
          />
          <Bar
            dataKey="value"
            name={valueLabel}
            fill={color}
            barSize={BAR_CAP}
            radius={[0, 4, 4, 0]}
            label={{
              position: "right",
              fill: "hsl(var(--muted-foreground))",
              fontSize: 10,
              formatter: (value: number) => format(value),
            }}
          />
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

/** Top countries by net revenue, from the country analysis ranking stage. */
export function TopCountriesChart({ rows, limit = 10 }: { rows: Row[]; limit?: number }) {
  const data = rows.slice(0, limit).map((row) => {
    const country = text(row, "country");
    return {
      label: country.length > 22 ? `${country.slice(0, 21)}…` : country,
      full: country,
      value: numeric(row, "net_revenue"),
    };
  });

  return (
    <RankedBars
      title={`Top ${data.length} countries by net revenue`}
      note="Ordered by the ranking stage in Hadoop, not re-sorted here."
      data={data}
      valueLabel="Net revenue"
      format={formatCurrency}
    />
  );
}

/** Top products, by whichever metric the chosen ranking used. */
export function TopProductsChart({
  rows,
  metric,
  limit = 10,
}: {
  rows: Row[];
  metric: "net_revenue" | "quantity_sold" | "quantity_returned";
  limit?: number;
}) {
  const titles = {
    net_revenue: "Top products by net revenue",
    quantity_sold: "Top products by units sold",
    quantity_returned: "Products with the most returned units",
  } as const;
  const format = metric === "net_revenue" ? formatCurrency : formatInteger;

  const data = rows.slice(0, limit).map((row) => {
    const description = text(row, "description");
    const code = text(row, "stock_code");
    const full = description ? `${code} · ${description}` : code;
    return {
      label: description
        ? description.length > 26
          ? `${description.slice(0, 25)}…`
          : description
        : code,
      full,
      value: numeric(row, metric),
    };
  });

  return (
    <RankedBars
      title={`${titles[metric].replace("Top products", `Top ${data.length} products`)}`}
      note="Keyed on StockCode; the description is a label only."
      data={data}
      valueLabel={metric === "net_revenue" ? "Net revenue" : "Units"}
      format={format}
      labelWidth={170}
    />
  );
}

/** Customers per RFM segment. */
export function SegmentChart({ rows }: { rows: Row[] }) {
  const data = rows
    .map((row) => ({
      label: text(row, "segment"),
      full: text(row, "segment"),
      value: numeric(row, "customers"),
    }))
    .sort((left, right) => right.value - left.value);

  return (
    <RankedBars
      title="Customers per segment"
      note="Segments follow the documented scoring rules; no model is involved."
      data={data}
      valueLabel="Customers"
      format={formatInteger}
      labelWidth={160}
    />
  );
}

/** Highest spending customers, from the customer ranking stage. */
export function TopCustomersChart({ rows, limit = 10 }: { rows: Row[]; limit?: number }) {
  const data = rows.slice(0, limit).map((row) => {
    const id = text(row, "customer_id");
    return { label: id, full: `Customer ${id}`, value: numeric(row, "net_spending") };
  });

  return (
    <RankedBars
      title={`Top ${data.length} customers by net spending`}
      note="Ordered by the ranking stage, which runs with a single reducer to produce a total order."
      data={data}
      valueLabel="Net spending"
      format={formatCurrency}
      labelWidth={90}
    />
  );
}
