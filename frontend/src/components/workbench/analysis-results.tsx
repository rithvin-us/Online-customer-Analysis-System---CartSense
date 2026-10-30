"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { ResultTable } from "./result-table";
import { ErrorState, LoadingRow } from "./states";
import {
  CountryMarketShareChart,
  LoyaltyBreakdownChart,
  MonthlyOrderVolumeChart,
  MonthlyRevenueChart,
  SegmentChart,
  SegmentShareChart,
  TopCountriesChart,
  TopCustomerOrdersChart,
  TopCustomersChart,
  TopProductsChart,
} from "./charts";
import { getResult, resultExportUrl } from "@/lib/api";
import { formatInteger } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import { summariseMetrics } from "@/lib/summary";
import { Field, FieldGrid } from "./field";
import type { ResultSetSummary } from "@/lib/types";

const PAGE_SIZE = 100;
/** Rows to read for a chart. Charts show a ranking's head, not the whole file. */
const CHART_ROWS = 60;

/**
 * One analysis's results: an output selector, a chart where one helps, and the
 * table of the same rows underneath it.
 *
 * The chart never replaces the table. Every value a chart draws is also
 * readable as text directly below it, which is what keeps the visualisation a
 * supporting view rather than the only way to read the output.
 */
export function AnalysisResults({
  runId,
  analysis,
  outputs,
}: {
  runId: string;
  analysis: string;
  outputs: ResultSetSummary[];
}) {
  const [outputName, setOutputName] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    if (outputs.length > 0 && !outputs.some((output) => output.name === outputName)) {
      setOutputName(preferredOutput(analysis, outputs));
      setOffset(0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outputs, analysis]);

  const page = useResource(
    () => getResult(runId, analysis, outputName!, PAGE_SIZE, offset),
    { enabled: Boolean(outputName), deps: [runId, analysis, outputName, offset] },
  );

  // A chart reads the head of the result independently of the table's paging,
  // so paging through rows does not change what the chart shows.
  const chartSource = useResource(
    () => getResult(runId, analysis, outputName!, CHART_ROWS, 0),
    {
      enabled: Boolean(outputName) && chartKind(analysis, outputName ?? "") !== null,
      deps: [runId, analysis, outputName],
    },
  );

  if (outputs.length === 0) {
    return (
      <p className="px-4 py-6 text-xs text-muted-foreground">
        This analysis has not written any output yet.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-1.5">
        {outputs.map((output) => (
          <Button
            key={output.name}
            variant={output.name === outputName ? "default" : "secondary"}
            size="xs"
            onClick={() => {
              setOutputName(output.name);
              setOffset(0);
            }}
          >
            {output.name.replace(/_/g, " ")}
            {output.row_count !== null && (
              <span className="tabular opacity-70">{formatInteger(output.row_count)}</span>
            )}
          </Button>
        ))}
      </div>

      {page.loading && !page.data ? (
        <LoadingRow label="Reading the result from HDFS" />
      ) : page.error ? (
        <ErrorState message={page.error} />
      ) : page.data ? (
        <div className={page.refreshing ? "opacity-60 transition-opacity" : undefined}>
          {renderChart(
            analysis,
            outputName ?? "",
            chartSource.data?.rows?.length ? chartSource.data.rows : page.data.rows,
          )}
          <div className="mt-4 overflow-hidden rounded-md border border-border">
            <ResultTable
              page={page.data}
              offset={offset}
              pageSize={PAGE_SIZE}
              onOffsetChange={setOffset}
              busy={page.refreshing}
              exportUrls={{
                csv: resultExportUrl(runId, analysis, outputName!, "csv"),
                tsv: resultExportUrl(runId, analysis, outputName!, "tsv"),
                json: resultExportUrl(runId, analysis, outputName!, "json"),
              }}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** Which output to open first: the ranked view where there is one. */
function preferredOutput(analysis: string, outputs: ResultSetSummary[]): string {
  const order: Record<string, string[]> = {
    customer_analysis: ["ranked_by_net_spending", "by_customer"],
    monthly_sales: ["by_month"],
    product_analysis: ["ranked_by_net_revenue", "by_product"],
    country_analysis: ["ranked_by_net_revenue", "by_country"],
    repeat_customers: ["summary", "by_customer"],
    rfm_analysis: ["by_segment", "by_customer"],
  };
  for (const name of order[analysis] ?? []) {
    if (outputs.some((output) => output.name === name)) return name;
  }
  return outputs[0]!.name;
}

type ChartKind =
  | "monthly"
  | "countries"
  | "customers"
  | "products_revenue"
  | "products_quantity"
  | "products_returns"
  | "segments"
  | "loyalty";

function chartKind(analysis: string, output: string): ChartKind | null {
  if (analysis === "monthly_sales" && output === "by_month") return "monthly";
  if (analysis === "country_analysis" && output === "ranked_by_net_revenue") return "countries";
  if (analysis === "customer_analysis" && output === "ranked_by_net_spending") {
    return "customers";
  }
  if (analysis === "product_analysis") {
    if (output === "ranked_by_net_revenue") return "products_revenue";
    if (output === "ranked_by_quantity_sold") return "products_quantity";
    if (output === "ranked_by_quantity_returned") return "products_returns";
  }
  if (analysis === "rfm_analysis" && output === "by_segment") return "segments";
  if (analysis === "repeat_customers" && output === "summary") return "loyalty";
  return null;
}

function renderChart(
  analysis: string,
  output: string,
  rows: Record<string, string | number | null>[],
) {
  const kind = chartKind(analysis, output);
  if (!kind || rows.length === 0) return null;

  const chart = (() => {
    switch (kind) {
      case "monthly":
        return (
          <div className="space-y-4">
            <MonthlyRevenueChart rows={rows} />
            <MonthlyOrderVolumeChart rows={rows} />
          </div>
        );
      case "countries":
        return (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <TopCountriesChart rows={rows} />
            <CountryMarketShareChart rows={rows} />
          </div>
        );
      case "customers":
        return (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <TopCustomersChart rows={rows} />
            <TopCustomerOrdersChart rows={rows} />
          </div>
        );
      case "segments":
        return (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <SegmentChart rows={rows} />
            <SegmentShareChart rows={rows} />
          </div>
        );
      case "loyalty":
        return (
          <div className="grid grid-cols-1 items-center gap-4 lg:grid-cols-2">
            <LoyaltyBreakdownChart rows={rows} />
            <LoyaltySummary rows={rows} />
          </div>
        );
      case "products_revenue":
        return <TopProductsChart rows={rows} metric="net_revenue" />;
      case "products_quantity":
        return <TopProductsChart rows={rows} metric="quantity_sold" />;
      case "products_returns":
        return <TopProductsChart rows={rows} metric="quantity_returned" />;
      default:
        return null;
    }
  })();

  if (!chart) return null;
  return <div className="rounded-md border border-border bg-surface px-4 py-3">{chart}</div>;
}

/** The loyalty summary reads better as labelled figures than as a two-column table. */
function LoyaltySummary({ rows }: { rows: Record<string, string | number | null>[] }) {
  const metrics = summariseMetrics(rows);

  const entries: { label: string; value: string; hint?: string }[] = [
    {
      label: "Identified customers",
      value: formatInteger(metrics.identified_customers),
      hint: "Distinct CustomerID values in the validated data.",
    },
    {
      label: "Repeat customers",
      value: formatInteger(metrics.repeat_customers),
      hint: "Two or more distinct completed invoices.",
    },
    {
      label: "Single-invoice customers",
      value: formatInteger(metrics.customers_with_single_completed_invoice),
    },
    {
      label: "Never completed a purchase",
      value: formatInteger(metrics.customers_without_completed_invoice),
      hint: "Present in the data but with no net positive invoice.",
    },
    {
      label: "Repeat rate",
      value:
        metrics.repeat_customer_percentage === null
          ? "—"
          : `${Number(metrics.repeat_customer_percentage).toFixed(2)}%`,
      hint: "Of customers who completed at least one purchase.",
    },
    {
      label: "Average purchase frequency",
      value:
        metrics.average_purchase_frequency === null
          ? "—"
          : Number(metrics.average_purchase_frequency).toFixed(2),
      hint: "Completed invoices per purchasing customer.",
    },
  ];

  return (
    <div className="mb-4 rounded-md border border-border bg-surface px-4 py-3">
      <FieldGrid>
        {entries.map((entry) => (
          <Field key={entry.label} label={entry.label} hint={entry.hint}>
            {entry.value}
          </Field>
        ))}
      </FieldGrid>
    </div>
  );
}
