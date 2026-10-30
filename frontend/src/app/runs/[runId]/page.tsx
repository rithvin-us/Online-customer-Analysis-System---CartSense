"use client";

import { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Download, ExternalLink, FileJson } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AnalysisResults } from "@/components/workbench/analysis-results";
import { CounterGrid } from "@/components/workbench/counter-grid";
import { Field, FieldGrid } from "@/components/workbench/field";
import { LogViewer } from "@/components/workbench/log-viewer";
import { Mono } from "@/components/workbench/mono";
import { PlacementPanel } from "@/components/workbench/placement";
import { StageChain } from "@/components/workbench/stage-chain";
import { StatusPill, isActive } from "@/components/workbench/status-pill";
import { EmptyState, ErrorState, LoadingRow } from "@/components/workbench/states";
import {
  getAnalysisLog,
  getContainerLogs,
  getRun,
  getStage,
  runReportUrl,
} from "@/lib/api";
import { formatBytes, formatDuration, formatInteger, formatTimestamp } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import type { AnalysisExecution } from "@/lib/types";

export default function RunPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = use(params);
  const [analysisKey, setAnalysisKey] = useState<string | null>(null);

  // Poll only while the run is still working; a finished page is static.
  const [polling, setPolling] = useState(true);
  const run = useResource(() => getRun(runId), {
    deps: [runId, polling],
    intervalMs: polling ? 4_000 : 0,
  });
  const active = run.data ? isActive(run.data.status) : true;

  useEffect(() => {
    if (run.data && !isActive(run.data.status)) setPolling(false);
  }, [run.data]);

  const analyses = useMemo(
    () => [...(run.data?.analyses ?? [])].sort((a, b) => a.position - b.position),
    [run.data],
  );

  useEffect(() => {
    if (!analysisKey && analyses.length > 0) setAnalysisKey(analyses[0]!.analysis);
  }, [analyses, analysisKey]);

  if (run.loading && !run.data) return <LoadingRow label="Reading the run" />;
  if (run.error && !run.data) return <ErrorState message={run.error} />;
  if (!run.data) return <EmptyState title="That run does not exist" />;

  const detail = run.data;
  const configuration = detail.configuration as {
    reducers?: number;
    split_maxsize?: number;
    day_first?: boolean;
    rank_limit?: number;
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Link href="/runs" className="hover:text-foreground">
              Runs
            </Link>
            <span>/</span>
          </div>
          <h1 className="pt-0.5 font-mono text-base font-semibold tracking-tight">
            {detail.run_key}
          </h1>
          <div className="flex flex-wrap items-center gap-2 pt-1.5">
            <StatusPill status={detail.status} />
            {detail.label && <Badge variant="outline">{detail.label}</Badge>}
            {detail.dataset_id && (
              <Link
                href={`/datasets/${detail.dataset_id}`}
                className="text-2xs text-muted-foreground hover:text-foreground hover:underline"
              >
                {detail.dataset_name} v{detail.dataset_version_number}
              </Link>
            )}
            <span className="text-2xs tabular text-muted-foreground">
              {formatInteger(detail.validated_record_count)} validated records
            </span>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" asChild>
            <a href={runReportUrl(runId, 20)} target="_blank" rel="noreferrer">
              <FileJson aria-hidden />
              Analytical report
            </a>
          </Button>
          <Button variant="ghost" size="sm" asChild>
            <a href={runReportUrl(runId, 0)} download={`${detail.run_key}-report.json`}>
              <Download aria-hidden />
              Metadata only
            </a>
          </Button>
        </div>
      </div>

      {detail.error && <ErrorState title="This run reported a problem" message={detail.error} />}

      <Card>
        <CardHeader>
          <CardTitle>Run configuration</CardTitle>
          <CardDescription>
            The settings the jobs actually ran under. These are recorded with the run, so
            a benchmark can say what differed between two runs.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FieldGrid>
            <Field label="Analyses">{detail.requested_analyses.length}</Field>
            <Field label="Reducers per stage">{configuration.reducers ?? "default"}</Field>
            <Field label="Maximum split size">
              {configuration.split_maxsize
                ? formatBytes(configuration.split_maxsize)
                : "HDFS block size"}
            </Field>
            <Field label="Date interpretation">
              {configuration.day_first ? "day/month" : "month/day"}
            </Field>
            <Field label="Submitted">{formatTimestamp(detail.submitted_at)}</Field>
            <Field label="Started">{formatTimestamp(detail.started_at)}</Field>
            <Field label="Finished">{formatTimestamp(detail.finished_at)}</Field>
            <Field label="Wall clock">{formatDuration(detail.duration_ms)}</Field>
          </FieldGrid>
        </CardContent>
      </Card>

      <Tabs
        value={analysisKey ?? analyses[0]?.analysis ?? ""}
        onValueChange={setAnalysisKey}
      >
        <TabsList className="w-full justify-start overflow-x-auto scrollbar-slim">
          {analyses.map((execution) => (
            <TabsTrigger key={execution.analysis} value={execution.analysis}>
              {execution.analysis.replace(/_/g, " ")}
              <StatusPill status={execution.status} className="ml-1" />
            </TabsTrigger>
          ))}
        </TabsList>

        {analyses.map((execution) => (
          <TabsContent key={execution.analysis} value={execution.analysis} className="pt-4">
            <AnalysisPanel runId={runId} execution={execution} live={active} />
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}

function AnalysisPanel({
  runId,
  execution,
  live,
}: {
  runId: string;
  execution: AnalysisExecution;
  live: boolean;
}) {
  const jobs = useMemo(
    () => [...execution.jobs].sort((a, b) => a.stage_index - b.stage_index),
    [execution.jobs],
  );
  const [stage, setStage] = useState<string | null>(null);

  useEffect(() => {
    if (jobs.length === 0) {
      setStage(null);
      return;
    }
    if (!stage || !jobs.some((job) => job.stage === stage)) {
      setStage(jobs[jobs.length - 1]!.stage);
    }
  }, [jobs, stage]);

  const stageDetail = useResource(() => getStage(runId, execution.analysis, stage!, true), {
    enabled: Boolean(stage),
    deps: [runId, execution.analysis, stage],
  });

  const running = execution.status === "RUNNING" || execution.status === "PENDING";

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <CardTitle className="capitalize">
                {execution.analysis.replace(/_/g, " ")}
              </CardTitle>
              <CardDescription>
                {jobs.length > 0
                  ? `${jobs.length} MapReduce job${jobs.length === 1 ? "" : "s"}, chained in order.`
                  : running
                    ? "Waiting for the first job to be submitted."
                    : "No job was recorded."}
              </CardDescription>
            </div>
            <div className="flex items-center gap-3 text-2xs tabular text-muted-foreground">
              <span>{formatDuration(execution.duration_ms)}</span>
              {execution.exit_code !== null && <span>exit {execution.exit_code}</span>}
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {execution.error && (
            <ErrorState title="This analysis failed" message={execution.error} />
          )}

          <StageChain jobs={jobs} selected={stage ?? undefined} onSelect={setStage} />

          <FieldGrid>
            <Field label="Work directory" className="col-span-2">
              <Mono value={execution.hdfs_work_dir} truncate={44} />
            </Field>
            <Field label="Results directory" className="col-span-2">
              <Mono value={execution.hdfs_result_dir} truncate={44} />
            </Field>
            <Field label="Manifest" className="col-span-2">
              <Mono value={execution.hdfs_manifest_path} truncate={44} />
            </Field>
          </FieldGrid>
        </CardContent>
      </Card>

      {stage && (
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <CardTitle>Stage: {stage}</CardTitle>
                <CardDescription>
                  Counters, placement and logs as the cluster reported them.
                </CardDescription>
              </div>
              {(stageDetail.data?.application_id || stageDetail.data?.tracking_url) && (
                <Button variant="ghost" size="xs" asChild>
                  <a
                    href={
                      stageDetail.data.application_id
                        ? `http://localhost:8088/cluster/app/${stageDetail.data.application_id}`
                        : stageDetail.data.tracking_url?.replace("resourcemanager:8088", "localhost:8088")
                    }
                    target="_blank"
                    rel="noreferrer"
                  >
                    <ExternalLink aria-hidden />
                    Open in YARN
                  </a>
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {stageDetail.loading && !stageDetail.data ? (
              <LoadingRow label="Reading the stage" />
            ) : stageDetail.error ? (
              <ErrorState message={stageDetail.error} />
            ) : stageDetail.data ? (
              <>
                <FieldGrid>
                  <Field label="Job id" className="col-span-2">
                    <Mono value={stageDetail.data.job_id} />
                  </Field>
                  <Field label="YARN application" className="col-span-2">
                    <Mono value={stageDetail.data.application_id} />
                  </Field>
                  <Field label="Reported state">{stageDetail.data.state ?? "—"}</Field>
                  <Field label="Duration">
                    {formatDuration(stageDetail.data.duration_ms)}
                  </Field>
                  <Field label="Started">
                    {formatTimestamp(stageDetail.data.start_time)}
                  </Field>
                  <Field label="Finished">
                    {formatTimestamp(stageDetail.data.finish_time)}
                  </Field>
                  {stageDetail.data.live_application && (
                    <>
                      <Field label="Live YARN state">
                        {stageDetail.data.live_application.state}
                      </Field>
                      <Field label="Final status">
                        {stageDetail.data.live_application.final_status}
                      </Field>
                    </>
                  )}
                </FieldGrid>

                <Separator />

                <Tabs defaultValue="counters">
                  <TabsList className="w-full justify-start overflow-x-auto scrollbar-slim">
                    <TabsTrigger value="counters">Counters</TabsTrigger>
                    <TabsTrigger value="placement">Worker placement</TabsTrigger>
                    <TabsTrigger value="rules">Rule counters</TabsTrigger>
                    <TabsTrigger value="driver-log">Driver log</TabsTrigger>
                    <TabsTrigger value="container-logs">Container logs</TabsTrigger>
                  </TabsList>

                  <TabsContent value="counters" className="pt-4">
                    <CounterGrid job={stageDetail.data} />
                    <details className="pt-4 text-xs">
                      <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                        Every counter group Hadoop reported
                      </summary>
                      <div className="mt-2 space-y-3">
                        {Object.entries(stageDetail.data.counters?.groups ?? {}).map(
                          ([group, counters]) => (
                            <div key={group}>
                              <p className="truncate font-mono text-2xs text-muted-foreground">
                                {group}
                              </p>
                              <table className="mt-1 w-full text-2xs">
                                <tbody>
                                  {Object.entries(counters).map(([name, value]) => (
                                    <tr key={name} className="border-t border-border/60">
                                      <td className="py-0.5 pr-3 font-mono">{name}</td>
                                      <td className="py-0.5 text-right tabular">
                                        {formatInteger(value)}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          ),
                        )}
                      </div>
                    </details>
                  </TabsContent>

                  <TabsContent value="placement" className="pt-2">
                    <PlacementPanel
                      summary={stageDetail.data.placement_summary}
                      attempts={stageDetail.data.task_attempts}
                    />
                  </TabsContent>

                  <TabsContent value="rules" className="pt-4">
                    {Object.keys(stageDetail.data.counters?.cartscope ?? {}).length === 0 ? (
                      <p className="text-xs text-muted-foreground">
                        This stage defined no counters of its own.
                      </p>
                    ) : (
                      <div className="space-y-3">
                        {Object.entries(stageDetail.data.counters?.cartscope ?? {}).map(
                          ([group, counters]) => (
                            <div key={group}>
                              <p className="truncate font-mono text-2xs text-muted-foreground">
                                {group}
                              </p>
                              <table className="mt-1 w-full text-xs">
                                <tbody>
                                  {Object.entries(counters).map(([name, value]) => (
                                    <tr key={name} className="border-t border-border/60">
                                      <td className="py-1 pr-3 font-mono text-2xs">{name}</td>
                                      <td className="py-1 text-right tabular">
                                        {formatInteger(value)}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          ),
                        )}
                      </div>
                    )}
                  </TabsContent>

                  <TabsContent value="driver-log" className="pt-2">
                    <div className="h-80 overflow-hidden rounded-md border border-border">
                      <LogViewer
                        load={() => getAnalysisLog(runId, execution.analysis)}
                        pollMs={live ? 4_000 : 0}
                        emptyMessage="No driver output has been written yet."
                      />
                    </div>
                  </TabsContent>

                  <TabsContent value="container-logs" className="pt-2">
                    <div className="h-80 overflow-hidden rounded-md border border-border">
                      <LogViewer
                        load={() => getContainerLogs(runId, execution.analysis, stage)}
                        emptyMessage="The NodeManagers have not aggregated this application's logs yet."
                      />
                    </div>
                  </TabsContent>
                </Tabs>
              </>
            ) : null}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Results</CardTitle>
          <CardDescription>
            Read straight from the reducers&apos; output in HDFS. The backend labels the
            columns and casts the numbers; it does not recompute them.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <AnalysisResults
            runId={runId}
            analysis={execution.analysis}
            outputs={execution.outputs}
          />
        </CardContent>
      </Card>
    </div>
  );
}
