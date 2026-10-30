"use client";

import { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AlertCircle, RefreshCw } from "lucide-react";

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
import { ClassificationPanel } from "@/components/workbench/classification-panel";
import { Field, FieldGrid } from "@/components/workbench/field";
import { Mono } from "@/components/workbench/mono";
import { QualityReportPanel } from "@/components/workbench/quality-report";
import { ResultTable } from "@/components/workbench/result-table";
import { SchemaProfile } from "@/components/workbench/schema-profile";
import { StatusPill, isActive } from "@/components/workbench/status-pill";
import { StoragePanel } from "@/components/workbench/storage-panel";
import { SubmitRun } from "@/components/workbench/submit-run";
import { SyntheticDialog } from "@/components/workbench/synthetic-dialog";
import { UploadDataset } from "@/components/workbench/upload-dataset";
import { EmptyState, ErrorState, LoadingRow } from "@/components/workbench/states";
import {
  getDataset,
  getVersion,
  getVersionRecords,
  getVersionStorage,
  retryVersion,
} from "@/lib/api";
import {
  formatBytes,
  formatInteger,
  formatPercent,
  formatTimestamp,
} from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";
import { cn } from "@/lib/utils";

const RECORD_PAGE_SIZE = 50;

export default function DatasetPage({
  params,
}: {
  params: Promise<{ datasetId: string }>;
}) {
  const { datasetId } = use(params);
  const [versionId, setVersionId] = useState<string | null>(null);
  const [recordKind, setRecordKind] = useState<"validated" | "rejected">("validated");
  const [recordOffset, setRecordOffset] = useState(0);

  const dataset = useResource(() => getDataset(datasetId), {
    intervalMs: 6_000,
    deps: [datasetId],
  });

  const versions = useMemo(
    () => [...(dataset.data?.versions ?? [])].sort((a, b) => b.version_number - a.version_number),
    [dataset.data],
  );

  useEffect(() => {
    if (!versionId && versions.length > 0) {
      setVersionId(versions[0]!.id);
    }
  }, [versions, versionId]);

  const selectedSummary = versions.find((version) => version.id === versionId) ?? null;
  const active = selectedSummary ? isActive(selectedSummary.status) : false;

  const version = useResource(
    () => getVersion(datasetId, versionId!),
    { enabled: Boolean(versionId), intervalMs: active ? 4_000 : 0, deps: [versionId, active] },
  );

  const storage = useResource(
    () => getVersionStorage(datasetId, versionId!),
    {
      enabled: Boolean(versionId) && selectedSummary?.status === "READY",
      deps: [versionId, selectedSummary?.status],
    },
  );

  const records = useResource(
    () => getVersionRecords(datasetId, versionId!, recordKind, RECORD_PAGE_SIZE, recordOffset),
    {
      enabled: Boolean(versionId) && selectedSummary?.status === "READY",
      deps: [versionId, recordKind, recordOffset, selectedSummary?.status],
    },
  );

  const retry = useAction(async () => retryVersion(datasetId, versionId!));

  if (dataset.loading) return <LoadingRow label="Reading the dataset" />;
  if (dataset.error) return <ErrorState message={dataset.error} />;
  if (!dataset.data) return <EmptyState title="That dataset does not exist" />;

  const detail = version.data;
  const readyVersions = versions.filter((item) => item.status === "READY");

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Link
              href="/datasets"
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              Datasets
            </Link>
            <span className="text-xs text-muted-foreground">/</span>
          </div>
          <h1 className="truncate pt-0.5 text-lg font-semibold tracking-tight">
            {dataset.data.name}
          </h1>
          <p className="max-w-3xl pt-0.5 text-xs text-muted-foreground">
            {dataset.data.description ?? "No description."}
          </p>
          <div className="flex flex-wrap items-center gap-2 pt-2">
            <Badge variant="outline">{dataset.data.source.toLowerCase()}</Badge>
            <Mono value={dataset.data.hdfs_path} />
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <UploadDataset datasetId={datasetId} onDone={dataset.reload} />
          {selectedSummary?.status === "READY" && (
            <SyntheticDialog
              datasetId={datasetId}
              sourceVersionId={selectedSummary.id}
              sourceRecords={selectedSummary.validated_record_count}
              onDone={dataset.reload}
            />
          )}
          {selectedSummary?.status === "READY" && (
            <SubmitRun
              datasetVersionId={selectedSummary.id}
              versionLabel={`${dataset.data.name} v${selectedSummary.version_number}`}
              validatedRecords={selectedSummary.validated_record_count}
            />
          )}
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Versions</CardTitle>
          <CardDescription>
            A version never changes once it is ready. Analyses record the version they
            read, so an earlier result stays explainable after new data arrives.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <ul className="divide-y divide-border">
            {versions.map((item) => {
              const selected = item.id === versionId;
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setVersionId(item.id);
                      setRecordOffset(0);
                    }}
                    className={cn(
                      "flex w-full flex-wrap items-center justify-between gap-3 px-4 py-2.5 text-left transition-colors",
                      selected ? "bg-accent/40" : "hover:bg-muted/50",
                    )}
                    aria-current={selected ? "true" : undefined}
                  >
                    <div className="min-w-0">
                      <p className="flex items-center gap-2 text-xs font-medium">
                        <span className="tabular">v{item.version_number}</span>
                        <span className="truncate text-muted-foreground">
                          {item.original_filename}
                        </span>
                      </p>
                      <p className="pt-0.5 text-2xs tabular text-muted-foreground">
                        {formatBytes(item.size_bytes)} ·{" "}
                        {formatInteger(item.raw_line_count)} raw rows ·{" "}
                        {formatInteger(item.validated_record_count)} validated ·{" "}
                        {formatInteger(item.rejected_record_count)} rejected ·{" "}
                        {formatTimestamp(item.created_at)}
                      </p>
                    </div>
                    <StatusPill status={item.status} kind="version" />
                  </button>
                </li>
              );
            })}
          </ul>
        </CardContent>
      </Card>

      {selectedSummary?.error && (
        <Card>
          <CardContent className="space-y-3 py-4">
            <div className="flex items-start gap-2.5">
              <AlertCircle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium">
                  Ingestion of v{selectedSummary.version_number} failed
                </p>
                <pre className="mt-1.5 max-h-48 overflow-auto scrollbar-slim whitespace-pre-wrap rounded border border-border bg-surface-sunken p-2.5 font-mono text-2xs text-muted-foreground">
                  {selectedSummary.error}
                </pre>
              </div>
            </div>
            {retry.error && <ErrorState message={retry.error} />}
            <Button
              variant="secondary"
              size="sm"
              disabled={retry.pending}
              onClick={async () => {
                await retry.run();
                dataset.reload();
              }}
            >
              <RefreshCw className={retry.pending ? "animate-spin" : undefined} aria-hidden />
              Retry ingestion
            </Button>
          </CardContent>
        </Card>
      )}

      {!versionId ? (
        <EmptyState title="This dataset has no versions" />
      ) : version.loading && !detail ? (
        <LoadingRow label="Reading the version" />
      ) : version.error ? (
        <ErrorState message={version.error} />
      ) : detail ? (
        <Card>
          <CardHeader>
            <CardTitle>
              v{detail.version_number} · {detail.original_filename}
            </CardTitle>
            <CardDescription>
              {active
                ? "This version is still being processed; the view refreshes itself."
                : "Everything recorded about this version."}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <FieldGrid>
              <Field label="Status">
                <StatusPill status={detail.status} kind="version" />
              </Field>
              <Field label="Raw rows">{formatInteger(detail.raw_line_count)}</Field>
              <Field label="Validated records">
                {formatInteger(detail.validated_record_count)}
              </Field>
              <Field label="Rejected records">
                {formatInteger(detail.rejected_record_count)}
                {detail.raw_line_count && detail.rejected_record_count !== null && (
                  <span className="pl-1.5 text-2xs text-muted-foreground">
                    {formatPercent(
                      (100 * detail.rejected_record_count) / detail.raw_line_count,
                      2,
                    )}
                  </span>
                )}
              </Field>
              <Field label="Duplicates removed">
                {formatInteger(detail.duplicate_record_count)}
              </Field>
              <Field label="Encoding">{detail.encoding ?? "—"}</Field>
              <Field label="Uploaded">{formatTimestamp(detail.created_at)}</Field>
              <Field label="Ready">{formatTimestamp(detail.ready_at)}</Field>
              <Field label="SHA-256" className="col-span-2">
                <Mono value={detail.sha256} truncate={28} />
              </Field>
              <Field label="Validated data" className="col-span-2">
                <Mono value={detail.hdfs_validated_path} truncate={46} />
              </Field>
            </FieldGrid>

            <Separator />

            <Tabs defaultValue="quality">
              <TabsList className="w-full justify-start overflow-x-auto scrollbar-slim">
                <TabsTrigger value="quality">Data quality</TabsTrigger>
                <TabsTrigger value="schema">Schema profile</TabsTrigger>
                <TabsTrigger value="classification">Classification</TabsTrigger>
                <TabsTrigger value="storage">HDFS storage</TabsTrigger>
                <TabsTrigger value="records">Records</TabsTrigger>
              </TabsList>

              <TabsContent value="quality" className="pt-4">
                {detail.quality_report ? (
                  <QualityReportPanel report={detail.quality_report} />
                ) : (
                  <p className="text-xs text-muted-foreground">
                    The quality report is produced during profiling, which has not
                    finished yet.
                  </p>
                )}
              </TabsContent>

              <TabsContent value="schema" className="pt-4">
                {detail.schema_report ? (
                  <SchemaProfile report={detail.schema_report} />
                ) : (
                  <p className="text-xs text-muted-foreground">
                    The schema profile is produced during profiling, which has not
                    finished yet.
                  </p>
                )}
              </TabsContent>

              <TabsContent value="classification" className="pt-4">
                {detail.validation_counters?.classification ? (
                  <ClassificationPanel
                    counters={detail.validation_counters.classification}
                  />
                ) : (
                  <p className="text-xs text-muted-foreground">
                    Classification counters come from the Hadoop validation job, which has
                    not reported yet.
                  </p>
                )}
              </TabsContent>

              <TabsContent value="storage" className="pt-4">
                {storage.loading ? (
                  <LoadingRow label="Reading HDFS" />
                ) : storage.error ? (
                  <ErrorState message={storage.error} />
                ) : storage.data ? (
                  <StoragePanel storage={storage.data} />
                ) : (
                  <p className="text-xs text-muted-foreground">
                    Storage detail becomes available once the version is ready.
                  </p>
                )}
              </TabsContent>

              <TabsContent value="records" className="pt-4">
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    {(["validated", "rejected"] as const).map((kind) => (
                      <Button
                        key={kind}
                        variant={recordKind === kind ? "default" : "secondary"}
                        size="xs"
                        onClick={() => {
                          setRecordKind(kind);
                          setRecordOffset(0);
                        }}
                      >
                        {kind === "validated" ? "Canonical records" : "Rejected records"}
                      </Button>
                    ))}
                  </div>
                  {records.loading && !records.data ? (
                    <LoadingRow label="Reading records from HDFS" />
                  ) : records.error ? (
                    <ErrorState message={records.error} />
                  ) : records.data ? (
                    <div className="overflow-hidden rounded-md border border-border">
                      <ResultTable
                        page={records.data}
                        offset={recordOffset}
                        pageSize={RECORD_PAGE_SIZE}
                        onOffsetChange={setRecordOffset}
                        busy={records.refreshing}
                      />
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      Records become readable once the validation job has written them.
                    </p>
                  )}
                </div>
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
      ) : null}

      {readyVersions.length > 1 && (
        <p className="text-2xs text-muted-foreground">
          {readyVersions.length} versions are ready. Running the same analyses against two
          of them, then comparing the runs under Benchmarks, is how to measure how this
          cluster scales.
        </p>
      )}
    </div>
  );
}
