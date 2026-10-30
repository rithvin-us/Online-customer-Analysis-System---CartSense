"use client";

import { useState } from "react";
import { ChevronRight, CornerLeftUp, File, Folder } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
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
import { browseHdfs } from "@/lib/api";
import { formatBytes, formatInteger, formatTimestamp } from "@/lib/format";
import { useResource } from "@/lib/hooks";

/**
 * Browses the CartScope subtree of HDFS.
 *
 * This is the direct answer to "is the data really in HDFS": the layout, the
 * file sizes, the block size each file was written with, its replication, and
 * optionally which DataNodes hold each block.
 */
export default function StoragePage() {
  const [path, setPath] = useState<string | undefined>(undefined);
  const [withBlocks, setWithBlocks] = useState(false);

  const listing = useResource(() => browseHdfs(path, withBlocks), {
    deps: [path, withBlocks],
  });

  const segments = (listing.data?.path ?? "").split("/").filter(Boolean);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">HDFS browser</h1>
          <p className="mt-0.5 max-w-3xl text-xs text-muted-foreground">
            Datasets, intermediate stage output, final results, manifests and the
            aggregated YARN logs, as they are stored on the cluster. Browsing is confined
            to the CartScope tree.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Switch id="show-blocks" checked={withBlocks} onCheckedChange={setWithBlocks} />
          <Label htmlFor="show-blocks" className="cursor-pointer">
            Show block placement
          </Label>
        </div>
      </div>

      <Card>
        <CardHeader className="gap-2">
          <div className="flex flex-wrap items-center gap-1 text-xs">
            {listing.data?.parent && (
              <Button
                variant="ghost"
                size="xs"
                onClick={() => setPath(listing.data!.parent!)}
                className="mr-1"
              >
                <CornerLeftUp aria-hidden />
                Up
              </Button>
            )}
            {segments.map((segment, index) => {
              const target = `/${segments.slice(0, index + 1).join("/")}`;
              const last = index === segments.length - 1;
              return (
                <span key={target} className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => setPath(target)}
                    className={
                      last
                        ? "font-mono text-2xs text-foreground"
                        : "font-mono text-2xs text-muted-foreground hover:text-foreground"
                    }
                  >
                    {segment}
                  </button>
                  {!last && (
                    <ChevronRight className="size-3 text-muted-foreground/60" aria-hidden />
                  )}
                </span>
              );
            })}
          </div>
          {listing.data?.summary && (
            <CardDescription className="tabular">
              {formatInteger(listing.data.summary.file_count)} files ·{" "}
              {formatInteger(listing.data.summary.directory_count)} directories ·{" "}
              {formatBytes(listing.data.summary.length)} logical ·{" "}
              {formatBytes(listing.data.summary.space_consumed)} consumed after replication
            </CardDescription>
          )}
        </CardHeader>
        <CardContent className="p-0">
          {listing.loading && !listing.data ? (
            <LoadingRow label="Listing HDFS" />
          ) : listing.error ? (
            <ErrorState message={listing.error} className="m-4" />
          ) : listing.data && listing.data.entries.length > 0 ? (
            <div className="overflow-x-auto scrollbar-slim">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead className="text-right">Size</TableHead>
                    <TableHead className="text-right">Block size</TableHead>
                    <TableHead className="text-right">Replication</TableHead>
                    <TableHead>Permissions</TableHead>
                    <TableHead>Owner</TableHead>
                    <TableHead>Modified</TableHead>
                    {withBlocks && <TableHead>Blocks</TableHead>}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {listing.data.entries.map((entry) => (
                    <TableRow key={entry.path}>
                      <TableCell className="max-w-[24rem]">
                        {entry.is_directory ? (
                          <button
                            type="button"
                            onClick={() => setPath(entry.path)}
                            className="flex items-center gap-1.5 truncate hover:underline"
                          >
                            <Folder className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                            <span className="truncate font-mono text-2xs">{entry.name}</span>
                          </button>
                        ) : (
                          <span className="flex items-center gap-1.5 truncate">
                            <File className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                            <span className="truncate font-mono text-2xs">{entry.name}</span>
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular">
                        {entry.is_directory ? "—" : formatBytes(entry.length)}
                      </TableCell>
                      <TableCell className="text-right tabular">
                        {entry.is_directory ? "—" : formatBytes(entry.block_size)}
                      </TableCell>
                      <TableCell className="text-right tabular">
                        {entry.is_directory ? "—" : entry.replication}
                      </TableCell>
                      <TableCell className="font-mono text-2xs">{entry.permission}</TableCell>
                      <TableCell className="text-muted-foreground">
                        {entry.owner}:{entry.group}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {entry.modification_time
                          ? formatTimestamp(new Date(entry.modification_time).toISOString())
                          : "—"}
                      </TableCell>
                      {withBlocks && (
                        <TableCell>
                          {entry.blocks && entry.blocks.length > 0 ? (
                            <div className="flex flex-wrap gap-1">
                              {entry.blocks.map((block, index) => (
                                <Badge
                                  key={`${entry.path}-${index}`}
                                  variant={block.corrupt ? "danger" : "default"}
                                  title={`block ${index + 1} · ${formatBytes(block.length)} · ${block.hosts.join(", ")}`}
                                >
                                  {block.hosts.length}x
                                </Badge>
                              ))}
                            </div>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </TableCell>
                      )}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <EmptyState
              title="This directory is empty"
              description="Load a dataset to populate the CartScope tree."
            />
          )}
        </CardContent>
      </Card>

      {withBlocks && (
        <p className="text-2xs text-muted-foreground">
          A badge of <span className="font-mono">2x</span> means that block is held by two
          DataNodes, which is the configured replication factor. Hover a badge for the
          hostnames.
        </p>
      )}
    </div>
  );
}
