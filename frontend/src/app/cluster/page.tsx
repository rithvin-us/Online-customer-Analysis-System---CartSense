"use client";

import { ExternalLink } from "lucide-react";

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
import { Field, FieldGrid } from "@/components/workbench/field";
import { ErrorState, LoadingRow } from "@/components/workbench/states";
import { getApplications, getCluster } from "@/lib/api";
import { formatBytes, formatDuration, formatInteger, formatPercent } from "@/lib/format";
import { useResource } from "@/lib/hooks";

export default function ClusterPage() {
  const cluster = useResource(getCluster, { intervalMs: 6_000 });
  const applications = useResource(() => getApplications(25), { intervalMs: 8_000 });

  if (cluster.loading && !cluster.data) return <LoadingRow label="Reading the cluster" />;
  if (cluster.error && !cluster.data) return <ErrorState message={cluster.error} />;
  if (!cluster.data) return null;

  const { hdfs, metrics, datanodes, nodemanagers, profile, links, services } = cluster.data;
  const unreachable = Object.entries(services).filter(([, state]) => !state.reachable);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">HDFS and YARN</h1>
        <p className="mt-0.5 max-w-3xl text-xs text-muted-foreground">
          Read live from the NameNode, the ResourceManager and the JobHistoryServer. A
          service that cannot be reached is reported as unreachable; no figure here is
          filled in from a default.
        </p>
      </div>

      {unreachable.length > 0 && (
        <div className="space-y-2">
          {unreachable.map(([name, state]) => (
            <ErrorState
              key={name}
              title={`${name} is unreachable`}
              message={state.error ?? "no reason reported"}
            />
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {(
          [
            ["NameNode UI", links.namenode_ui],
            ["ResourceManager UI", links.resourcemanager_ui],
            ["JobHistoryServer UI", links.jobhistory_ui],
          ] as const
        ).map(([label, href]) => (
          <Button key={label} variant="secondary" size="xs" asChild>
            <a href={href} target="_blank" rel="noreferrer">
              <ExternalLink aria-hidden />
              {label}
            </a>
          </Button>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>HDFS</CardTitle>
            <CardDescription>
              {hdfs
                ? `Cluster ${hdfs.cluster_id ?? "unknown"} · Hadoop ${hdfs.version ?? "unknown"}`
                : "The NameNode could not be reached."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {hdfs ? (
              <FieldGrid className="lg:grid-cols-3">
                <Field label="Live DataNodes">
                  <span
                    className={
                      hdfs.live_datanodes < profile.expected_datanodes
                        ? "text-destructive"
                        : undefined
                    }
                  >
                    {hdfs.live_datanodes} of {profile.expected_datanodes}
                  </span>
                </Field>
                <Field label="Dead DataNodes">{hdfs.dead_datanodes}</Field>
                <Field label="Safe mode">{hdfs.safemode || "off"}</Field>
                <Field label="Capacity used">{formatBytes(hdfs.capacity_used)}</Field>
                <Field label="Capacity total">{formatBytes(hdfs.capacity_total)}</Field>
                <Field label="Used">{formatPercent(hdfs.percent_used, 2)}</Field>
                <Field label="Blocks">{formatInteger(hdfs.blocks_total)}</Field>
                <Field label="Files">{formatInteger(hdfs.files_total)}</Field>
                <Field label="Under-replicated">
                  <span
                    className={hdfs.under_replicated_blocks > 0 ? "text-warning" : undefined}
                  >
                    {formatInteger(hdfs.under_replicated_blocks)}
                  </span>
                </Field>
                <Field label="Missing blocks">
                  <span className={hdfs.missing_blocks > 0 ? "text-destructive" : undefined}>
                    {formatInteger(hdfs.missing_blocks)}
                  </span>
                </Field>
                <Field label="Replication">{hdfs.configured_replication}</Field>
                <Field label="Block size">{formatBytes(hdfs.configured_block_size)}</Field>
              </FieldGrid>
            ) : (
              <p className="text-xs text-muted-foreground">No data.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>YARN</CardTitle>
            <CardDescription>
              {metrics
                ? `${metrics.active_nodes} of ${profile.expected_nodemanagers} NodeManagers registered`
                : "The ResourceManager could not be reached."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {metrics ? (
              <FieldGrid className="lg:grid-cols-3">
                <Field label="Memory total">
                  {formatInteger(metrics.memory_total_mb)} MiB
                </Field>
                <Field label="Memory allocated">
                  {formatInteger(metrics.memory_allocated_mb)} MiB
                </Field>
                <Field label="Memory available">
                  {formatInteger(metrics.memory_available_mb)} MiB
                </Field>
                <Field label="vCores total">{metrics.vcores_total}</Field>
                <Field label="vCores allocated">{metrics.vcores_allocated}</Field>
                <Field label="Containers">{metrics.containers_allocated}</Field>
                <Field label="Applications running">{metrics.apps_running}</Field>
                <Field label="Completed">{formatInteger(metrics.apps_completed)}</Field>
                <Field label="Failed">
                  <span className={metrics.apps_failed > 0 ? "text-warning" : undefined}>
                    {formatInteger(metrics.apps_failed)}
                  </span>
                </Field>
                <Field label="Unhealthy nodes">{metrics.unhealthy_nodes}</Field>
                <Field label="Lost nodes">{metrics.lost_nodes}</Field>
                <Field label="Containers pending">{metrics.containers_pending}</Field>
              </FieldGrid>
            ) : (
              <p className="text-xs text-muted-foreground">No data.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>DataNodes</CardTitle>
          <CardDescription>
            The NameNode&apos;s own report. Each DataNode is an independent container with
            its own storage volume, with every block held by {profile.replication} of them.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto scrollbar-slim">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Host</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead className="text-right">Blocks</TableHead>
                  <TableHead className="text-right">Used</TableHead>
                  <TableHead className="text-right">Capacity</TableHead>
                  <TableHead className="text-right">Used %</TableHead>
                  <TableHead className="text-right">Last contact</TableHead>
                  <TableHead>Version</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {datanodes.map((node) => (
                  <TableRow key={node.name}>
                    <TableCell className="font-mono text-2xs">{node.hostname}</TableCell>
                    <TableCell>
                      <Badge variant={node.state === "live" ? "success" : "danger"}>
                        {node.state}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right tabular">
                      {formatInteger(node.blocks)}
                    </TableCell>
                    <TableCell className="text-right tabular">
                      {formatBytes(node.used)}
                    </TableCell>
                    <TableCell className="text-right tabular">
                      {formatBytes(node.capacity)}
                    </TableCell>
                    <TableCell className="text-right tabular">
                      {formatPercent(node.percent_used, 1)}
                    </TableCell>
                    <TableCell className="text-right tabular">
                      {node.last_contact === null ? "—" : `${node.last_contact}s`}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {node.version ?? "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>NodeManagers</CardTitle>
          <CardDescription>
            Each worker has its own {formatInteger(profile.nodemanager_memory_mb)} MiB
            schedulable budget, which is what lets map tasks run on all three at once.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto scrollbar-slim">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Host</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead className="text-right">Containers</TableHead>
                  <TableHead className="text-right">Memory used</TableHead>
                  <TableHead className="text-right">Memory free</TableHead>
                  <TableHead className="text-right">vCores used</TableHead>
                  <TableHead>Health</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {nodemanagers.map((node) => (
                  <TableRow key={node.id}>
                    <TableCell className="font-mono text-2xs">{node.hostname}</TableCell>
                    <TableCell>
                      <Badge variant={node.state === "RUNNING" ? "success" : "warning"}>
                        {node.state}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right tabular">{node.containers}</TableCell>
                    <TableCell className="text-right tabular">
                      {formatInteger(node.memory_used_mb)} MiB
                    </TableCell>
                    <TableCell className="text-right tabular">
                      {formatInteger(node.memory_available_mb)} MiB
                    </TableCell>
                    <TableCell className="text-right tabular">{node.vcores_used}</TableCell>
                    <TableCell className="max-w-[18rem] truncate text-muted-foreground">
                      {node.health_report || "healthy"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>YARN applications</CardTitle>
          <CardDescription>
            Every MapReduce stage CartScope submits appears here as its own application.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {applications.loading && !applications.data ? (
            <LoadingRow label="Reading applications" />
          ) : applications.error ? (
            <ErrorState message={applications.error} className="m-4" />
          ) : (
            <div className="overflow-x-auto scrollbar-slim">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Application</TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead>State</TableHead>
                    <TableHead>Final status</TableHead>
                    <TableHead className="text-right">Elapsed</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(applications.data?.applications ?? []).map((application) => (
                    <TableRow key={application.id}>
                      <TableCell className="font-mono text-2xs">{application.id}</TableCell>
                      <TableCell className="max-w-[22rem] truncate font-mono text-2xs">
                        {application.name}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={
                            application.state === "RUNNING"
                              ? "info"
                              : application.state === "FINISHED"
                                ? "success"
                                : "default"
                          }
                        >
                          {application.state}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={
                            application.final_status === "SUCCEEDED"
                              ? "success"
                              : application.final_status === "FAILED"
                                ? "danger"
                                : "default"
                          }
                        >
                          {application.final_status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right tabular">
                        {formatDuration(application.elapsed_time)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
