"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  formatCompact,
  formatCurrency,
  formatInteger,
  formatPercent,
} from "@/lib/format";
import { summariseMetrics } from "@/lib/summary";
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

export const PALETTE = [
  "hsl(var(--series-1))",
  "hsl(var(--series-3))",
  "hsl(var(--series-2))",
  "hsl(270 65% 58%)",
  "hsl(330 75% 55%)",
  "hsl(45 90% 48%)",
  "hsl(190 85% 42%)",
  "hsl(140 60% 45%)",
  "hsl(215 25% 60%)",
] as const;

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
  metric:
    | "net_revenue"
    | "gross_revenue"
    | "quantity_sold"
    | "quantity_returned"
    | "distinct_invoices";
  limit?: number;
}) {
  const titles = {
    net_revenue: "Top products by net revenue",
    gross_revenue: "Top products by gross revenue",
    quantity_sold: "Top products by units sold",
    quantity_returned: "Products with the most returned units",
    distinct_invoices: "Top products by orders appeared on",
  } as const;
  const format =
    metric === "net_revenue" || metric === "gross_revenue" ? formatCurrency : formatInteger;
  const valueLabels = {
    net_revenue: "Net revenue",
    gross_revenue: "Gross revenue",
    quantity_sold: "Units",
    quantity_returned: "Units",
    distinct_invoices: "Orders",
  } as const;

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
      valueLabel={valueLabels[metric]}
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

// ---------------------------------------------------------------------------
// Extended Visualizations (Donuts, Volume Areas, Orders Breakdown)
// ---------------------------------------------------------------------------

export function DonutChart({
  title,
  note,
  data,
  format,
  centerLabel,
  centerValue,
  height = 240,
}: {
  title: string;
  note?: string;
  data: { label: string; value: number; color?: string; percent?: number }[];
  format: (value: number) => string;
  centerLabel?: string;
  centerValue?: string;
  height?: number;
}) {
  if (data.length === 0) return null;
  const items = data.map((d, i) => ({
    ...d,
    color: d.color || PALETTE[i % PALETTE.length]!,
  }));

  return (
    <ChartFrame title={title} note={note} height={height}>
      <Legend
        items={items.map((item) => ({
          label: `${item.label} (${item.percent !== undefined ? `${item.percent.toFixed(1)}%` : format(item.value)})`,
          color: item.color,
        }))}
      />
      <div className="relative h-[calc(100%-28px)]">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
            <Pie
              data={items}
              dataKey="value"
              nameKey="label"
              cx="50%"
              cy="50%"
              innerRadius={50}
              outerRadius={80}
              paddingAngle={3}
              isAnimationActive={false}
            >
              {items.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.color} stroke={SURFACE} strokeWidth={2} />
              ))}
            </Pie>
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload || payload.length === 0) return null;
                const d = payload[0]?.payload as { label: string; value: number; percent?: number };
                return (
                  <div className="rounded-md border border-border bg-surface-raised px-2.5 py-1.5 shadow-md text-2xs">
                    <p className="font-medium text-foreground">{d.label}</p>
                    <p className="text-muted-foreground">
                      {format(d.value)} {d.percent !== undefined && `(${d.percent.toFixed(1)}%)`}
                    </p>
                  </div>
                );
              }}
            />
          </PieChart>
        </ResponsiveContainer>
        {centerValue && (
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-lg font-bold tracking-tight text-foreground">{centerValue}</span>
            {centerLabel && (
              // Constrained to the hole: a long band name wraps inside the
              // donut instead of running out over the ring.
              <span className="max-w-[88px] text-balance text-center text-3xs font-medium leading-tight text-muted-foreground">
                {centerLabel}
              </span>
            )}
          </div>
        )}
      </div>
    </ChartFrame>
  );
}

/** Customer retention & loyalty breakdown for repeat_customers summary. */
export function LoyaltyBreakdownChart({ rows }: { rows: Row[] }) {
  const metrics = summariseMetrics(rows);
  const repeat = metrics.repeat_customers || 0;
  const single = metrics.customers_with_single_completed_invoice || 0;
  const zero = metrics.customers_without_completed_invoice || 0;
  const total = repeat + single + zero;

  if (total === 0) return null;

  const data = [
    {
      label: "Repeat (2+ orders)",
      value: repeat,
      color: "hsl(var(--series-3))",
      percent: (repeat / total) * 100,
    },
    {
      label: "Single Order",
      value: single,
      color: "hsl(var(--series-1))",
      percent: (single / total) * 100,
    },
    {
      label: "Never Purchased",
      value: zero,
      color: "hsl(var(--series-2))",
      percent: (zero / total) * 100,
    },
  ].filter((d) => d.value > 0);

  const rate = metrics.repeat_customer_percentage;

  return (
    <DonutChart
      title="Customer Retention Breakdown"
      note="Distribution of identified customers by completed purchase count."
      data={data}
      format={formatInteger}
      centerValue={rate !== null ? `${Number(rate).toFixed(1)}%` : undefined}
      centerLabel="Repeat Rate"
      height={220}
    />
  );
}

/** Geographic market share breakdown (% net revenue). */
export function CountryMarketShareChart({ rows, limit = 5 }: { rows: Row[]; limit?: number }) {
  const topRows = rows.slice(0, limit);
  const remainingRows = rows.slice(limit);

  const totalRevenue = rows.reduce((acc, r) => acc + numeric(r, "net_revenue"), 0);
  if (totalRevenue <= 0) return null;

  const topItems = topRows.map((row, i) => {
    const val = numeric(row, "net_revenue");
    return {
      label: text(row, "country"),
      value: val,
      color: PALETTE[i % PALETTE.length]!,
      percent: (val / totalRevenue) * 100,
    };
  });

  const otherRevenue = remainingRows.reduce((acc, r) => acc + numeric(r, "net_revenue"), 0);
  if (otherRevenue > 0) {
    topItems.push({
      label: "Other Countries",
      value: otherRevenue,
      color: "hsl(215 25% 60%)",
      percent: (otherRevenue / totalRevenue) * 100,
    });
  }

  return (
    <DonutChart
      title="Geographic Market Share"
      note={`Top ${limit} countries vs remainder of world by net revenue.`}
      data={topItems}
      format={formatCurrency}
      centerValue={topItems[0] ? `${topItems[0].percent?.toFixed(0)}%` : undefined}
      centerLabel={topItems[0]?.label}
      height={240}
    />
  );
}

/** Monetary value share across RFM segments. */
export function SegmentShareChart({ rows }: { rows: Row[] }) {
  const totalRev = rows.reduce((acc, r) => acc + numeric(r, "total_monetary"), 0);
  if (totalRev <= 0) return null;

  const data = rows
    .map((row, i) => {
      const val = numeric(row, "total_monetary");
      return {
        label: text(row, "segment"),
        value: val,
        color: PALETTE[i % PALETTE.length]!,
        percent: (val / totalRev) * 100,
      };
    })
    .sort((a, b) => b.value - a.value);

  return (
    <DonutChart
      title="Segment Revenue Contribution"
      note="Distribution of total monetary value across customer segments."
      data={data}
      format={formatCurrency}
      centerValue={formatCompact(totalRev)}
      centerLabel="Total Value"
      height={240}
    />
  );
}

/** Monthly completed order count and physical units sold. */
export function MonthlyOrderVolumeChart({ rows }: { rows: Row[] }) {
  const data = rows.map((row) => ({
    month: text(row, "month"),
    orders: numeric(row, "completed_invoices"),
    items: numeric(row, "quantity_sold"),
  }));

  if (data.length === 0) return null;

  return (
    <ChartFrame
      title="Monthly Order & Item Volume"
      note="Distinct completed invoices and total physical units sold per month."
      height={200}
    >
      <Legend
        items={[
          { label: "Completed orders", color: SERIES.one },
          { label: "Units sold", color: SERIES.two },
        ]}
      />
      <ResponsiveContainer width="100%" height="84%">
        <AreaChart data={data} margin={{ top: 4, right: 46, bottom: 4, left: 4 }}>
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
                format={formatInteger}
              />
            )}
          />
          <Area
            type="monotone"
            dataKey="orders"
            name="Completed orders"
            stroke={SERIES.one}
            fill={SERIES.one}
            fillOpacity={0.2}
            strokeWidth={2}
          />
          <Area
            type="monotone"
            dataKey="items"
            name="Units sold"
            stroke={SERIES.two}
            fill={SERIES.two}
            fillOpacity={0.12}
            strokeWidth={2}
          />
        </AreaChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

/** Orders placed by the highest-spending customers. */
export function TopCustomerOrdersChart({ rows, limit = 10 }: { rows: Row[]; limit?: number }) {
  const data = rows.slice(0, limit).map((row) => {
    const id = text(row, "customer_id");
    return {
      label: id,
      full: `Customer ${id}`,
      value: numeric(row, "total_orders"),
    };
  });

  return (
    <RankedBars
      title={`Orders by Top ${data.length} Customers`}
      note="Completed order count for each of the top spending customers."
      data={data}
      valueLabel="Orders"
      format={formatInteger}
      color={SERIES.three}
      labelWidth={90}
    />
  );
}

// ---------------------------------------------------------------------------
// Product classification
// ---------------------------------------------------------------------------

/**
 * The Pareto curve: cumulative share of the sold catalogue's gross revenue
 * against the revenue ranking.
 *
 * Both the share and the rank are columns of the `classify` stage's output, so
 * the curve is drawn, not computed. The two dashed rules are the published ABC
 * boundaries — they are where the class on each row changes, which makes the
 * shape of the curve and the letter in the table the same statement.
 *
 * One series, so no legend: the title names it.
 */
export function ProductParetoChart({
  rows,
  totalProducts,
}: {
  rows: Row[];
  totalProducts?: number | null;
}) {
  const data = rows
    .map((row) => ({
      rank: numeric(row, "rank"),
      cumulative: numeric(row, "cumulative_revenue_share_pct"),
      product: text(row, "description") || text(row, "stock_code"),
      abc: text(row, "abc_class"),
    }))
    .sort((left, right) => left.rank - right.rank);

  if (data.length < 2) return null;

  const last = data[data.length - 1]!;
  const shown = data.length;
  // Never claim to have drawn the whole catalogue without knowing its size:
  // the chart reads a fixed number of rows, which may be all of them or not.
  const coverage = !totalProducts
    ? `${formatInteger(shown)} classified products`
    : totalProducts > shown
      ? `the first ${formatInteger(shown)} of ${formatInteger(totalProducts)} classified products`
      : `all ${formatInteger(shown)} classified products`;

  return (
    <ChartFrame
      title="Cumulative revenue share by rank"
      note={`Plotted over ${coverage}. The dashed rules at 80% and 95% are the ABC class boundaries.`}
      height={250}
    >
      <ResponsiveContainer width="100%" height="88%">
        <AreaChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
          <CartesianGrid stroke={GRID} strokeWidth={1} vertical={false} />
          <XAxis
            dataKey="rank"
            tick={AXIS_TICK}
            stroke={GRID}
            tickLine={false}
            interval="preserveStartEnd"
            minTickGap={28}
            tickFormatter={(value: number) => formatCompact(value)}
          />
          <YAxis
            tick={AXIS_TICK}
            stroke={GRID}
            tickLine={false}
            width={40}
            domain={[0, 100]}
            ticks={[0, 20, 40, 60, 80, 100]}
            tickFormatter={(value: number) => `${value}%`}
          />
          <ReferenceLine y={80} stroke={AXIS_INK} strokeDasharray="3 3" strokeWidth={1} />
          <ReferenceLine y={95} stroke={AXIS_INK} strokeDasharray="3 3" strokeWidth={1} />
          <Tooltip
            cursor={{ stroke: AXIS_INK, strokeWidth: 1 }}
            content={({ active, payload }) => {
              if (!active || !payload || payload.length === 0) return null;
              const datum = payload[0]?.payload as {
                rank: number;
                cumulative: number;
                product: string;
                abc: string;
              };
              return (
                <div className="rounded-md border border-border bg-surface-raised px-2.5 py-1.5 text-2xs shadow-md">
                  <p className="font-medium text-foreground">
                    #{formatInteger(datum.rank)} {datum.product}
                  </p>
                  <p className="text-muted-foreground">
                    {formatPercent(datum.cumulative, 2)} cumulative · class {datum.abc}
                  </p>
                </div>
              );
            }}
          />
          <Area
            type="monotone"
            dataKey="cumulative"
            name="Cumulative revenue share"
            stroke={SERIES.one}
            fill={SERIES.one}
            fillOpacity={0.18}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: SURFACE }}
          />
        </AreaChart>
      </ResponsiveContainer>
      <p className="pt-1 text-2xs text-muted-foreground">
        The top {formatInteger(shown)} products account for{" "}
        {formatPercent(last.cumulative, 2)} of the sold catalogue&apos;s gross revenue.
      </p>
    </ChartFrame>
  );
}

/**
 * The four classification dimensions of the band summary.
 *
 * The display order of the dimensions, and the title and gloss of each, are the
 * only things decided here. Which bands exist, how many products are in each,
 * and every share came out of the `band-summary` reducer; the bands are drawn
 * in the reporting order that stage assigned them rather than re-sorted by
 * size, because a band order that moved with the data would make two runs hard
 * to compare.
 */
const CLASSIFICATION_DIMENSIONS = [
  {
    key: "abc_class",
    title: "ABC revenue class",
    note:
      "A while the products above have not reached 80% of gross revenue, B up to 95%, then C.",
  },
  {
    key: "price_band",
    title: "Price band",
    note: "By average unit price: a product's gross revenue divided by the units it sold.",
  },
  {
    key: "volume_band",
    title: "Volume band",
    note: "By units sold.",
  },
  {
    key: "return_class",
    title: "Return class",
    note: "By returned units as a share of the units handled.",
  },
] as const;

export function ClassificationBandCharts({ rows }: { rows: Row[] }) {
  const groups = CLASSIFICATION_DIMENSIONS.map((dimension) => ({
    ...dimension,
    bands: rows
      .filter((row) => text(row, "dimension") === dimension.key)
      .sort((left, right) => numeric(left, "ordinal") - numeric(right, "ordinal")),
  })).filter((group) => group.bands.length > 0);

  if (groups.length === 0) return null;

  return (
    <div className="space-y-6">
      {groups.map((group) => {
        const slices = group.bands.map((row, index) => ({
          label: text(row, "band"),
          value: numeric(row, "gross_revenue"),
          percent: numeric(row, "revenue_share_pct"),
          color: PALETTE[index % PALETTE.length]!,
        }));
        const products = group.bands.map((row) => {
          const band = text(row, "band");
          return {
            label: band.length > 22 ? `${band.slice(0, 21)}…` : band,
            full: band,
            value: numeric(row, "products"),
          };
        });
        const headline = slices.reduce(
          (best, slice) => (slice.percent > best.percent ? slice : best),
          slices[0]!,
        );

        return (
          <section key={group.key}>
            <div className="pb-2">
              <p className="text-xs font-medium">{group.title}</p>
              <p className="pt-0.5 text-2xs text-muted-foreground">{group.note}</p>
            </div>
            <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
              <DonutChart
                title="Share of gross revenue"
                note="Shares as the band-summary reducer reported them."
                data={slices}
                format={formatCurrency}
                centerValue={formatPercent(headline.percent)}
                centerLabel={headline.label}
                height={248}
              />
              <RankedBars
                title="Products in each band"
                note="In reporting order, not sorted by size."
                data={products}
                valueLabel="Products"
                format={formatInteger}
                color={SERIES.three}
                labelWidth={140}
              />
            </div>
          </section>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Counters
// ---------------------------------------------------------------------------

/**
 * A bar chart over Hadoop counters.
 *
 * A counter is a count of records, so the only thing a chart adds is the
 * comparison between them — which is why the bars are ordered by size and the
 * zero counters are left out instead of drawn as empty rows.
 */
export function CounterBars({
  title,
  note,
  items,
  valueLabel,
  color = SERIES.one,
  labelWidth = 170,
}: {
  title: string;
  note?: string;
  items: { label: string; value: number | null }[];
  valueLabel: string;
  color?: string;
  labelWidth?: number;
}) {
  const data = items
    .filter((item): item is { label: string; value: number } =>
      typeof item.value === "number" && item.value > 0)
    .map((item) => ({
      label: item.label.length > 24 ? `${item.label.slice(0, 23)}…` : item.label,
      full: item.label,
      value: item.value,
    }))
    .sort((left, right) => right.value - left.value);

  if (data.length === 0) return null;

  return (
    <RankedBars
      title={title}
      note={note}
      data={data}
      valueLabel={valueLabel}
      format={formatInteger}
      color={color}
      labelWidth={labelWidth}
    />
  );
}
