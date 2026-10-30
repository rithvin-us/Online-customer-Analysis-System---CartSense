"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
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
import { UploadDataset } from "@/components/workbench/upload-dataset";
import { getClusterProfile, getDatasets } from "@/lib/api";
import { formatBytes, formatInteger, formatRelative } from "@/lib/format";
import { useResource } from "@/lib/hooks";

export default function DatasetsPage() {
  const datasets = useResource(getDatasets, { intervalMs: 8_000 });
  const profile = useResource(getClusterProfile);

  const working = datasets.data?.some((dataset) =>
    dataset.latest_version ? isActive(dataset.latest_version.status) : false,
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Datasets</h1>
          <p className="mt-0.5 max-w-3xl text-xs text-muted-foreground">
            A dataset holds one or more immutable versions. Uploading does four things in
            order: the file is profiled, a SHA-256 checksum is taken, the original bytes
            are written to HDFS, and a Hadoop job canonicalises and de-duplicates it.
            {working && " A version is being processed; this list refreshes itself."}
          </p>
        </div>
        <UploadDataset
          maxUploadMb={profile.data?.limits.max_upload_mb}
          onDone={datasets.reload}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Catalogue</CardTitle>
          <CardDescription>
            Record counts are the ones the Hadoop validation job reported.
          </CardDescription>
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
                    <TableHead>Source</TableHead>
                    <TableHead className="text-right">Versions</TableHead>
                    <TableHead className="text-right">Raw rows</TableHead>
                    <TableHead className="text-right">Validated</TableHead>
                    <TableHead className="text-right">Rejected</TableHead>
                    <TableHead className="text-right">Size</TableHead>
                    <TableHead>Latest status</TableHead>
                    <TableHead>Created</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {datasets.data.map((dataset) => {
                    const version = dataset.latest_version;
                    return (
                      <TableRow key={dataset.id}>
                        <TableCell className="max-w-[18rem]">
                          <Link
                            href={`/datasets/${dataset.id}`}
                            className="truncate font-medium hover:underline"
                          >
                            {dataset.name}
                          </Link>
                          {dataset.description && (
                            <p className="truncate pt-0.5 text-2xs text-muted-foreground">
                              {dataset.description}
                            </p>
                          )}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline">{dataset.source.toLowerCase()}</Badge>
                        </TableCell>
                        <TableCell className="text-right tabular">
                          {dataset.version_count}
                        </TableCell>
                        <TableCell className="text-right tabular">
                          {formatInteger(version?.raw_line_count)}
                        </TableCell>
                        <TableCell className="text-right tabular">
                          {formatInteger(version?.validated_record_count)}
                        </TableCell>
                        <TableCell className="text-right tabular">
                          {formatInteger(version?.rejected_record_count)}
                        </TableCell>
                        <TableCell className="text-right tabular">
                          {formatBytes(version?.size_bytes)}
                        </TableCell>
                        <TableCell>
                          {version && <StatusPill status={version.status} kind="version" />}
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-muted-foreground">
                          {formatRelative(dataset.created_at)}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          ) : (
            <EmptyState
              title="No datasets yet"
              description="Load a retail transaction CSV with the UCI Online Retail schema, or any CSV with the same eight columns."
              action={
                <UploadDataset
                  maxUploadMb={profile.data?.limits.max_upload_mb}
                  onDone={datasets.reload}
                />
              }
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
