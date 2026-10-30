import { Field, FieldGrid } from "./field";
import { formatBytes, formatInteger } from "@/lib/format";
import type { JobExecution } from "@/lib/types";

/**
 * The headline Hadoop counters for one stage.
 *
 * Every figure is the value Hadoop reported. A counter the job did not produce
 * — reduce counters on a map-only stage, for example — shows an em dash rather
 * than a zero, because zero would be a claim and the dash is the truth.
 */
export function CounterGrid({ job }: { job: JobExecution }) {
  return (
    <FieldGrid>
      <Field label="Map input records">{formatInteger(job.map_input_records)}</Field>
      <Field label="Map output records">{formatInteger(job.map_output_records)}</Field>
      <Field label="Reduce input groups">{formatInteger(job.reduce_input_groups)}</Field>
      <Field label="Reduce output records">{formatInteger(job.reduce_output_records)}</Field>
      <Field label="Launched map tasks">{formatInteger(job.launched_map_tasks)}</Field>
      <Field label="Launched reduce tasks">{formatInteger(job.launched_reduce_tasks)}</Field>
      <Field label="Failed map tasks">{formatInteger(job.failed_map_tasks)}</Field>
      <Field label="Failed reduce tasks">{formatInteger(job.failed_reduce_tasks)}</Field>
      <Field label="HDFS bytes read">{formatBytes(job.hdfs_bytes_read)}</Field>
      <Field label="HDFS bytes written">{formatBytes(job.hdfs_bytes_written)}</Field>
      <Field label="Configured reducers">{formatInteger(job.configured_reducers)}</Field>
      <Field label="Reported state">{job.state ?? "—"}</Field>
    </FieldGrid>
  );
}
