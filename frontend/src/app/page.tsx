"use client";

import Link from "next/link";
import { ArrowUpRight, Database, Play, Plus } from "lucide-react";

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
import { Field, FieldGrid } from "@/components/workbench/field";
import { StatusPill, isActive } from "@/components/workbench/status-pill";
import { getClusterProfile, getDatasets, getRuns } from "@/lib/api";
import { formatBytes, formatInteger, formatRelative, formatDuration } from "@/lib/format";
import { useResource } from "@/lib/hooks";

/**
 * The overview is an operator's starting point, not a KPI board: what data is
 * loaded, what has run recently, and how this cluster is configured.
 */
export default function OverviewPage() {
  const datasets = useResource(getDatasets, { intervalMs: 15_000 });
  const runs = useResource(() => getRuns(8), { intervalMs: 5_000 });
  const profile = useResource(getClusterProfile);

  const anythingActive =
    datasets.data?.some((dataset) =>
      dataset.latest_version ? isActive(dataset.latest_version.status) : false,
    ) || runs.data?.some((run) => isActive(run.status));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Workbench</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Retail transaction data in HDFS, analysed by Hadoop MapReduce jobs on YARN.
            {anythingActive && " Work is in progress; this view refreshes itself."}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" asChild>
            <Link href="/datasets">
              <Plus aria-hidden />
              Load a dataset
            </Link>
          </Button>
          <Button size="sm" asChild>
            <Link href="/runs">
              <Play aria-hidden />
              New run
            </Link>
          </Button>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.1fr_1fr]">
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <div>
              <CardTitle>Datasets</CardTitle>
              <CardDescription>
                Each version is immutable: an analysis records the version it read.
              </CardDescription>
            </div>
            <Button variant="ghost" size="xs" asChild>
              <Link href="/datasets">
                All datasets
                <ArrowUpRight aria-hidden />
              </Link>
            </Button>
          </CardHeader>
          <CardContent className="p-0">
            {datasets.loading ? (
              <LoadingRow label="Reading the dataset catalogue" />
            ) : datasets.error ? (
              <ErrorState message={datasets.error} className="m-4" />
            ) : datasets.data && datasets.data.length > 0 ? (
              <div className="overflow-x-auto scrollbar-slim">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Dataset</TableHead>
                      <TableHead>Latest version</TableHead>
                      <TableHead className="text-right">Validated records</TableHead>
                      <TableHead className="text-right">Size</TableHead>
                      <TableHead>Status</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {datasets.data.slice(0, 6).map((dataset) => (
                      <TableRow key={dataset.id}>
                        <TableCell className="max-w-[16rem]">
                          <Link
                            href={`/datasets/${dataset.id}`}
                            className="truncate font-medium hover:underline"
                          >
                            {dataset.name}
                          </Link>
                          <div className="flex items-center gap-1.5 pt-0.5">
                            <Badge variant="outline">{dataset.source.toLowerCase()}</Badge>
                            <span className="text-2xs text-muted-foreground">
                              {dataset.version_count} version
                              {dataset.version_count === 1 ? "" : "s"}
                            </span>
                          </div>
                        </TableCell>
                        <TableCell className="tabular text-muted-foreground">
                          {dataset.latest_version
                            ? `v${dataset.latest_version.version_number}`
                            : "—"}
                        </TableCell>
                        <TableCell className="text-right tabular">
                          {formatInteger(dataset.latest_version?.validated_record_count)}
                        </TableCell>
                        <TableCell className="text-right tabular">
                          {formatBytes(dataset.latest_version?.size_bytes)}
                        </TableCell>
                        <TableCell>
                          {dataset.latest_version && (
                            <StatusPill
                              status={dataset.latest_version.status}
                              kind="version"
                            />
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <EmptyState
                title="No dataset is loaded yet"
                description="Upload a retail transaction CSV. It will be profiled, written to HDFS and validated by a Hadoop job before any analysis can read it."
                action={
                  <Button size="sm" asChild>
                    <Link href="/datasets">
                      <Database aria-hidden />
                      Load a dataset
                    </Link>
                  </Button>
                }
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <div>
              <CardTitle>Recent runs</CardTitle>
              <CardDescription>
                Each run submits real MapReduce job chains through YARN.
              </CardDescription>
            </div>
            <Button variant="ghost" size="xs" asChild>
              <Link href="/runs">
                All runs
                <ArrowUpRight aria-hidden />
              </Link>
            </Button>
          </CardHeader>
          <CardContent className="p-0">
            {runs.loading ? (
              <LoadingRow label="Reading recent runs" />
            ) : runs.error ? (
              <ErrorState message={runs.error} className="m-4" />
            ) : runs.data && runs.data.length > 0 ? (
              <ul className="divide-y divide-border">
                {runs.data.map((run) => (
                  <li key={run.id}>
                    <Link
                      href={`/runs/${run.id}`}
                      className="flex items-center justify-between gap-3 px-4 py-2.5 transition-colors hover:bg-muted/50"
                    >
                      <div className="min-w-0">
                        <p className="truncate font-mono text-2xs">{run.run_key}</p>
                        <p className="truncate pt-0.5 text-2xs text-muted-foreground">
                          {run.label ? `${run.label} · ` : ""}
                          {run.requested_analyses.length} analys
                          {run.requested_analyses.length === 1 ? "is" : "es"} ·{" "}
                          {formatRelative(run.created_at)}
                        </p>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <span className="tabular text-2xs text-muted-foreground">
                          {formatDuration(run.duration_ms)}
                        </span>
                        <StatusPill status={run.status} />
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                title="Nothing has run yet"
                description="Once a dataset version is ready, submit one or more analyses against it."
              />
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>This cluster</CardTitle>
          <CardDescription>
            {profile.data?.topology_note ??
              "The configured profile every result on this instance was produced under."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {profile.loading ? (
            <LoadingRow label="Reading the cluster profile" />
          ) : profile.error ? (
            <ErrorState message={profile.error} />
          ) : profile.data ? (
            <FieldGrid>
              <Field label="HDFS replication">{profile.data.hdfs.replication}</Field>
              <Field label="HDFS block size">
                {formatBytes(profile.data.hdfs.block_size)}
              </Field>
              <Field label="NodeManager memory">
                {formatInteger(profile.data.yarn.nodemanager_memory_mb)} MiB each
              </Field>
              <Field label="Map container">
                {formatInteger(profile.data.yarn.map_container_mb)} MiB
              </Field>
              <Field label="Reduce container">
                {formatInteger(profile.data.yarn.reduce_container_mb)} MiB
              </Field>
              <Field label="ApplicationMaster">
                {formatInteger(profile.data.yarn.application_master_mb)} MiB
              </Field>
              <Field label="Default reducers">
                {profile.data.mapreduce.default_reducers}
              </Field>
              <Field label="HDFS root">
                <span className="font-mono text-xs">{profile.data.hdfs.root}</span>
              </Field>
            </FieldGrid>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
