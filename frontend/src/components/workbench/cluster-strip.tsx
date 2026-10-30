"use client";

import Link from "next/link";
import { Database, HardDrive, Layers, Server } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { getCluster } from "@/lib/api";
import { formatBytes, formatInteger } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * A compact, always-visible read of the cluster.
 *
 * It answers the two questions that decide whether anything else on screen can
 * be trusted: are the three DataNodes up, and are the three NodeManagers
 * registered. A missing worker is shown as missing.
 */
export function ClusterStrip({ className }: { className?: string }) {
  const { data, error, loading } = useResource(getCluster, { intervalMs: 10_000 });

  if (loading) {
    return (
      <div className={cn("flex items-center gap-4", className)}>
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-4 w-28" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <Link
        href="/cluster"
        className={cn("flex items-center gap-2 text-2xs text-destructive", className)}
      >
        <Server className="size-3.5" aria-hidden />
        Cluster unreachable
      </Link>
    );
  }

  const liveDataNodes = data.hdfs?.live_datanodes ?? 0;
  const expectedDataNodes = data.profile.expected_datanodes;
  const activeNodeManagers = data.metrics?.active_nodes ?? 0;
  const expectedNodeManagers = data.profile.expected_nodemanagers;

  const dataNodesHealthy = liveDataNodes >= expectedDataNodes;
  const nodeManagersHealthy = activeNodeManagers >= expectedNodeManagers;

  return (
    <Link
      href="/cluster"
      className={cn(
        "flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-muted-foreground transition-colors hover:text-foreground",
        className,
      )}
    >
      <span className="flex items-center gap-1.5">
        <HardDrive className="size-3.5" aria-hidden />
        <Badge variant={dataNodesHealthy ? "success" : "danger"}>
          {liveDataNodes}/{expectedDataNodes} DataNodes
        </Badge>
      </span>
      <span className="flex items-center gap-1.5">
        <Server className="size-3.5" aria-hidden />
        <Badge variant={nodeManagersHealthy ? "success" : "danger"}>
          {activeNodeManagers}/{expectedNodeManagers} NodeManagers
        </Badge>
      </span>
      {data.metrics && (
        <span className="flex items-center gap-1.5 tabular">
          <Layers className="size-3.5" aria-hidden />
          {formatInteger(data.metrics.memory_available_mb)} MiB free of{" "}
          {formatInteger(data.metrics.memory_total_mb)} MiB
        </span>
      )}
      {data.hdfs && (
        <span className="flex items-center gap-1.5 tabular">
          <Database className="size-3.5" aria-hidden />
          {formatBytes(data.hdfs.capacity_used)} used · {formatInteger(data.hdfs.blocks_total)}{" "}
          blocks · replication {data.hdfs.configured_replication}
        </span>
      )}
      {data.metrics && data.metrics.apps_running > 0 && (
        <Badge variant="info">{data.metrics.apps_running} running</Badge>
      )}
    </Link>
  );
}
