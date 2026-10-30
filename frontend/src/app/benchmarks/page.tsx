"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Save } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState, ErrorState, LoadingRow } from "@/components/workbench/states";
import { StatusPill } from "@/components/workbench/status-pill";
import { compareRuns, getBenchmarks, getRuns, saveBenchmark } from "@/lib/api";
import {
  formatBytes,
  formatDecimal,
  formatDuration,
  formatInteger,
  formatTimestamp,
} from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * Benchmarking.
 *
 * Every figure in the comparison is derived from the counters and timings
 * Hadoop reported for those runs. Throughput is the one computed value, and it
 * is a plain division of a Hadoop record count by a Hadoop-reported duration.
 */
export default function BenchmarksPage() {
  const [selected, setSelected] = useState<string[]>([]);
  const [name, setName] = useState("");

  const runs = useResource(() => getRuns(50));
  const comparison = useResource(() => compareRuns(selected, 8), {
    deps: [selected.join(",")],
  });
  const saved = useResource(getBenchmarks);

  const save = useAction(async () =>
    saveBenchmark({ name: name.trim(), run_ids: selected }),
  );

  const finished = useMemo(
    () =>
      (runs.data ?? []).filter(
        (run) => run.status === "SUCCEEDED" || run.status === "PARTIAL",
      ),
    [runs.data],
  );

  function toggle(runId: string) {
    setSelected((current) =>
      current.includes(runId)
        ? current.filter((item) => item !== runId)
        : [...current, runId],
    );
  }

  const rows = comparison.data ?? [];
  const fastest = rows.reduce<number | null>(
    (best, row) =>
      row.records_per_second !== null && (best === null || row.records_per_second > best)
        ? row.records_per_second
        : best,
    null,
  );

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Benchmarks</h1>
        <p className="mt-0.5 max-w-3xl text-xs text-muted-foreground">
          Compare what runs cost. Running the same analyses against a larger dataset
          version, or against the same data with a different split size or reducer count,
          is how to measure how this cluster behaves as the work grows.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Choose runs</CardTitle>
          <CardDescription>
            Select two or more. With nothing selected, the most recent finished runs are
            compared.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {runs.loading ? (
            <LoadingRow label="Reading runs" />
          ) : runs.error ? (
            <ErrorState message={runs.error} className="m-4" />
          ) : finished.length === 0 ? (
            <EmptyState
              title="No finished runs yet"
              description="A run must complete before it can be benchmarked."
              action={
                <Button size="sm" variant="secondary" asChild>
                  <Link href="/runs">Go to runs</Link>
                </Button>
              }
            />
          ) : (
            <ul className="max-h-64 divide-y divide-border overflow-auto scrollbar-slim">
              {finished.map((run) => {
                const checked = selected.includes(run.id);
                return (
                  <li key={run.id}>
                    <label
                      className={cn(
                        "flex cursor-pointer items-center gap-3 px-4 py-2 transition-colors",
                        checked ? "bg-accent/30" : "hover:bg-muted/50",
                      )}
                    >
                      <Checkbox checked={checked} onCheckedChange={() => toggle(run.id)} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-mono text-2xs">
                          {run.run_key}
                        </span>
                        <span className="block truncate text-2xs text-muted-foreground">
                          {run.label ? `${run.label} · ` : ""}
                          {run.requested_analyses.length} analyses ·{" "}
                          {formatDuration(run.duration_ms)} ·{" "}
                          {formatTimestamp(run.submitted_at ?? run.created_at)}
                        </span>
                      </span>
                      <StatusPill status={run.status} />
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>Comparison</CardTitle>
              <CardDescription>
                {selected.length > 0
                  ? `${selected.length} selected runs.`
                  : "The most recent finished runs."}{" "}
                Records read is the map input of each analysis&apos;s first stage, which
                avoids double counting the stages that read the previous stage&apos;s
                output.
              </CardDescription>
            </div>
            {selected.length >= 2 && (
              <div className="flex items-end gap-2">
                <div className="space-y-1">
                  <Label htmlFor="benchmark-name">Save as</Label>
                  <Input
                    id="benchmark-name"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="540k vs 1M rows"
                    className="h-8 w-48 text-xs"
                  />
                </div>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={save.pending || name.trim().length === 0}
                  onClick={async () => {
                    const created = await save.run();
                    if (created) {
                      setName("");
                      saved.reload();
                    }
                  }}
                >
                  <Save aria-hidden />
                  Save
                </Button>
              </div>
            )}
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {save.error && <ErrorState message={save.error} className="m-4" />}
          {comparison.loading && !comparison.data ? (
            <LoadingRow label="Reading execution metrics" />
          ) : comparison.error ? (
            <ErrorState message={comparison.error} className="m-4" />
          ) : rows.length === 0 ? (
            <EmptyState title="Nothing to compare yet" />
          ) : (
            <div className="overflow-x-auto scrollbar-slim">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Run</TableHead>
                    <TableHead>Dataset</TableHead>
                    <TableHead className="text-right">Validated records</TableHead>
                    <TableHead className="text-right">Records read</TableHead>
                    <TableHead className="text-right">Wall clock</TableHead>
                    <TableHead className="text-right">Records/s</TableHead>
                    <TableHead className="text-right">Map tasks</TableHead>
                    <TableHead className="text-right">Reduce tasks</TableHead>
                    <TableHead className="text-right">Jobs</TableHead>
                    <TableHead className="text-right">HDFS read</TableHead>
                    <TableHead className="text-right">HDFS written</TableHead>
                    <TableHead>Settings</TableHead>
                    <TableHead>Cluster</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => (
                    <TableRow key={row.run_id}>
                      <TableCell className="max-w-[16rem]">
                        <Link
                          href={`/runs/${row.run_id}`}
                          className="truncate font-mono text-2xs hover:underline"
                        >
                          {row.run_key}
                        </Link>
                        {row.label && (
                          <p className="truncate pt-0.5 text-2xs text-muted-foreground">
                            {row.label}
                          </p>
                        )}
                      </TableCell>
                      <TableCell className="max-w-[12rem] truncate">
                        {row.dataset_name ?? "—"}
                        {row.dataset_version_number !== null && (
                          <span className="pl-1 text-muted-foreground">
                            v{row.dataset_version_number}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular">
                        {formatInteger(row.validated_records)}
                      </TableCell>
                      <TableCell className="text-right tabular">
                        {formatInteger(row.map_input_records)}
                      </TableCell>
                      <TableCell className="text-right tabular">
                        {formatDuration(row.total_duration_ms)}
                      </TableCell>
                      <TableCell className="text-right tabular">
                        <span
                          className={cn(
                            row.records_per_second !== null &&
                              row.records_per_second === fastest &&
                              "font-medium text-success",
                          )}
                        >
                          {formatDecimal(row.records_per_second)}
                        </span>
                      </TableCell>
                      <TableCell className="text-right tabular">
                        {formatInteger(row.launched_map_tasks)}
                      </TableCell>
                      <TableCell className="text-right tabular">
                        {formatInteger(row.launched_reduce_tasks)}
                      </TableCell>
                      <TableCell className="text-right tabular">{row.stage_count}</TableCell>
                      <TableCell className="text-right tabular">
                        {formatBytes(row.hdfs_bytes_read)}
                      </TableCell>
                      <TableCell className="text-right tabular">
                        {formatBytes(row.hdfs_bytes_written)}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-2xs text-muted-foreground">
                        {row.reducers ?? "default"} reducers
                        {row.split_maxsize ? ` · ${formatBytes(row.split_maxsize)} splits` : ""}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-2xs text-muted-foreground">
                        {row.live_datanodes ?? "—"} DN · {row.active_nodemanagers ?? "—"} NM
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {rows.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Per-analysis timings</CardTitle>
            <CardDescription>
              Where the wall clock went, analysis by analysis.
            </CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto scrollbar-slim">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Run</TableHead>
                    <TableHead>Analysis</TableHead>
                    <TableHead className="text-right">Duration</TableHead>
                    <TableHead className="text-right">Jobs</TableHead>
                    <TableHead className="text-right">Map tasks</TableHead>
                    <TableHead className="text-right">Reduce tasks</TableHead>
                    <TableHead>Stage durations</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.flatMap((row) =>
                    row.per_analysis.map((entry) => (
                      <TableRow key={`${row.run_id}-${entry.analysis}`}>
                        <TableCell className="font-mono text-2xs text-muted-foreground">
                          {row.label ?? row.run_key}
                        </TableCell>
                        <TableCell className="capitalize">
                          {entry.analysis.replace(/_/g, " ")}
                        </TableCell>
                        <TableCell className="text-right tabular">
                          {formatDuration(entry.duration_ms)}
                        </TableCell>
                        <TableCell className="text-right tabular">{entry.stages}</TableCell>
                        <TableCell className="text-right tabular">
                          {formatInteger(entry.launched_map_tasks)}
                        </TableCell>
                        <TableCell className="text-right tabular">
                          {formatInteger(entry.launched_reduce_tasks)}
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-wrap gap-1">
                            {entry.stage_durations.map((stage) => (
                              <Badge key={stage.stage} variant="outline">
                                {stage.stage} {formatDuration(stage.duration_ms)}
                              </Badge>
                            ))}
                          </div>
                        </TableCell>
                      </TableRow>
                    )),
                  )}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}

      {saved.data && saved.data.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Saved comparisons</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <ul className="divide-y divide-border">
              {saved.data.map((benchmark) => (
                <li key={benchmark.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(benchmark.run_ids)}
                    className="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left transition-colors hover:bg-muted/50"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-xs font-medium">
                        {benchmark.name}
                      </span>
                      <span className="block truncate text-2xs text-muted-foreground">
                        {benchmark.run_ids.length} runs ·{" "}
                        {formatTimestamp(benchmark.created_at)}
                      </span>
                    </span>
                    <Badge variant="outline">load</Badge>
                  </button>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
