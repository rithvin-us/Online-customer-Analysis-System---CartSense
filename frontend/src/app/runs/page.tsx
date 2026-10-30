"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState, ErrorState, LoadingRow } from "@/components/workbench/states";
import { StatusPill, isActive } from "@/components/workbench/status-pill";
import { SubmitRun } from "@/components/workbench/submit-run";
import { getDatasets, getRuns } from "@/lib/api";
import { formatDuration, formatInteger, formatTimestamp } from "@/lib/format";
import { useResource } from "@/lib/hooks";

export default function RunsPage() {
  const runs = useResource(() => getRuns(100), { intervalMs: 5_000 });
  const datasets = useResource(getDatasets);

  const readyVersions = (datasets.data ?? []).flatMap((dataset) =>
    dataset.latest_version && dataset.latest_version.status === "READY"
      ? [{ dataset, version: dataset.latest_version }]
      : [],
  );

  const anyActive = runs.data?.some((run) => isActive(run.status));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Runs</h1>
          <p className="mt-0.5 max-w-3xl text-xs text-muted-foreground">
            A run submits one or more analyses against a single validated dataset version.
            Each analysis is a chain of MapReduce jobs; the run records every job id, YARN
            application id and counter the cluster reported.
            {anyActive && " Work is in progress; this list refreshes itself."}
          </p>
        </div>
        {readyVersions.length > 0 && (
          <SubmitRun
            datasetVersionId={readyVersions[0]!.version.id}
            versionLabel={`${readyVersions[0]!.dataset.name} v${readyVersions[0]!.version.version_number}`}
            validatedRecords={readyVersions[0]!.version.validated_record_count}
          />
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>History</CardTitle>
          <CardDescription>Newest first.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {runs.loading ? (
            <LoadingRow label="Reading runs" />
          ) : runs.error ? (
            <ErrorState message={runs.error} className="m-4" />
          ) : runs.data && runs.data.length > 0 ? (
            <div className="overflow-x-auto scrollbar-slim">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Run</TableHead>
                    <TableHead>Analyses</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Duration</TableHead>
                    <TableHead>Submitted</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {runs.data.map((run) => (
                    <TableRow key={run.id}>
                      <TableCell className="max-w-[20rem]">
                        <Link
                          href={`/runs/${run.id}`}
                          className="truncate font-mono text-2xs hover:underline"
                        >
                          {run.run_key}
                        </Link>
                        {run.label && (
                          <p className="truncate pt-0.5 text-2xs text-muted-foreground">
                            {run.label}
                          </p>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {run.requested_analyses.map((analysis) => (
                            <Badge key={analysis} variant="outline">
                              {analysis.replace(/_/g, " ")}
                            </Badge>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell>
                        <StatusPill status={run.status} />
                      </TableCell>
                      <TableCell className="text-right tabular">
                        {formatDuration(run.duration_ms)}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {formatTimestamp(run.submitted_at ?? run.created_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <EmptyState
              title="No runs yet"
              description={
                readyVersions.length > 0
                  ? "Submit one or more analyses against a validated dataset version."
                  : "Load and validate a dataset first; an analysis can only read validated data."
              }
              action={
                readyVersions.length === 0 ? (
                  <Button size="sm" variant="secondary" asChild>
                    <Link href="/datasets">Go to datasets</Link>
                  </Button>
                ) : undefined
              }
            />
          )}
        </CardContent>
      </Card>

      {runs.data && runs.data.length > 1 && (
        <p className="text-2xs text-muted-foreground">
          {formatInteger(runs.data.length)} runs recorded. Compare their execution cost
          under{" "}
          <Link href="/benchmarks" className="underline hover:text-foreground">
            Benchmarks
          </Link>
          .
        </p>
      )}
    </div>
  );
}
