/**
 * Types mirroring the backend's response models.
 *
 * Kept by hand rather than generated, so that every field the UI relies on is
 * visible in one place; the backend's OpenAPI document at /api/docs is the
 * authority if the two ever disagree.
 */

export type RunStatus =
  | "PENDING"
  | "RUNNING"
  | "SUCCEEDED"
  | "PARTIAL"
  | "FAILED"
  | "CANCELLED";

export type VersionStatus =
  | "RECEIVED"
  | "PROFILING"
  | "UPLOADING_TO_HDFS"
  | "VALIDATING"
  | "READY"
  | "FAILED";

export interface ResultColumn {
  name: string;
  label: string;
  type: "string" | "integer" | "float";
  unit: string;
  description: string;
}

export interface AnalysisOutput {
  name: string;
  title: string;
  description: string;
  ranked: boolean;
  default_sort: string | null;
  columns: ResultColumn[];
}

export interface AnalysisStage {
  name: string;
  title: string;
  purpose: string;
}

export interface AnalysisDefinition {
  key: string;
  title: string;
  objective: string;
  scope_note: string;
  optional: boolean;
  stage_count: number;
  stages: AnalysisStage[];
  outputs: AnalysisOutput[];
}

export interface DatasetVersionSummary {
  id: string;
  version_number: number;
  status: VersionStatus;
  original_filename: string;
  size_bytes: number;
  sha256: string | null;
  raw_line_count: number | null;
  validated_record_count: number | null;
  rejected_record_count: number | null;
  duplicate_record_count: number | null;
  created_at: string;
  ready_at: string | null;
  error: string | null;
}

export interface QualityIssue {
  severity: "error" | "warning" | "info";
  code: string;
  message: string;
  detail?: Record<string, unknown>;
}

export interface ColumnProfile {
  name: string;
  declared_type: string;
  values: number;
  non_empty: number;
  empty: number;
  empty_percent: number;
  type_mismatches: number;
  min: number | string | null;
  max: number | string | null;
  distinct_sample: string[];
}

export interface SchemaReport {
  encoding: string;
  delimiter: string;
  header: string[];
  expected_columns: string[];
  schema_matches: boolean;
  missing_columns: string[];
  unexpected_columns: string[];
  columns: ColumnProfile[];
  sample_rows: string[][];
}

export interface QualityReport {
  data_rows: number;
  distinct_rows: number;
  duplicate_rows: number;
  wrong_field_count_rows: number;
  multiline_records: number;
  sha256: string;
  size_bytes: number;
  issues: QualityIssue[];
  blocking_issues: QualityIssue[];
  scope_note: string;
}

export interface DatasetVersionDetail extends DatasetVersionSummary {
  encoding: string | null;
  delimiter: string | null;
  hdfs_raw_path: string | null;
  hdfs_validated_path: string | null;
  hdfs_rejected_path: string | null;
  schema_report: SchemaReport | null;
  quality_report: QualityReport | null;
  validation_counters: {
    classification?: Record<string, number | null>;
    stages?: unknown[];
  } | null;
  generation_spec: Record<string, unknown> | null;
}

export interface DatasetSummary {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  source: "UPLOAD" | "BUILTIN" | "SYNTHETIC";
  created_at: string;
  version_count: number;
  latest_version: DatasetVersionSummary | null;
}

export interface DatasetDetail extends DatasetSummary {
  hdfs_path: string;
  versions: DatasetVersionSummary[];
}

export interface JobExecution {
  id: string;
  analysis: string;
  stage: string;
  stage_index: number;
  job_name: string | null;
  job_id: string | null;
  application_id: string | null;
  tracking_url: string | null;
  state: string | null;
  start_time: string | null;
  finish_time: string | null;
  duration_ms: number | null;
  configured_reducers: number | null;
  launched_map_tasks: number | null;
  launched_reduce_tasks: number | null;
  failed_map_tasks: number | null;
  failed_reduce_tasks: number | null;
  map_input_records: number | null;
  map_output_records: number | null;
  reduce_input_groups: number | null;
  reduce_output_records: number | null;
  hdfs_bytes_read: number | null;
  hdfs_bytes_written: number | null;
  input_paths: string[] | null;
  output_path: string | null;
}

export interface TaskAttempt {
  task_id: string;
  attempt_id: string;
  type: string;
  state: string;
  node: string;
  host: string;
  container_id: string | null;
  start_time: number | null;
  finish_time: number | null;
  elapsed_time: number | null;
  progress: number | null;
  diagnostics: string;
}

export interface PlacementSummary {
  hosts: string[];
  per_host: Record<string, { map: number; reduce: number }>;
  distinct_hosts: number;
  total_attempts: number;
}

export interface JobExecutionDetail extends JobExecution {
  counters: {
    groups?: Record<string, Record<string, number>>;
    headline?: Record<string, number | null>;
    cartscope?: Record<string, Record<string, number>>;
  } | null;
  task_attempts: TaskAttempt[] | null;
  placement_summary: PlacementSummary | null;
  live_application?: YarnApplication;
}

export interface ResultSetSummary {
  id: string;
  name: string;
  hdfs_path: string;
  row_count: number | null;
  size_bytes: number | null;
  columns: ResultColumn[];
}

export interface AnalysisExecution {
  id: string;
  analysis: string;
  position: number;
  status: RunStatus;
  hdfs_work_dir: string | null;
  hdfs_result_dir: string | null;
  hdfs_manifest_path: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  exit_code: number | null;
  error: string | null;
  jobs: JobExecution[];
  outputs: ResultSetSummary[];
}

export interface RunSummary {
  id: string;
  run_key: string;
  status: RunStatus;
  label: string | null;
  requested_analyses: string[];
  dataset_version_id: string;
  submitted_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  created_at: string;
  error: string | null;
}

export interface RunDetail extends RunSummary {
  notes: string | null;
  configuration: Record<string, unknown>;
  analyses: AnalysisExecution[];
  dataset_name: string | null;
  dataset_id: string | null;
  dataset_version_number: number | null;
  validated_record_count: number | null;
}

export interface ResultPage {
  name: string;
  title: string;
  description: string;
  hdfs_path: string;
  ranked: boolean;
  columns: ResultColumn[];
  rows: Record<string, string | number | null>[];
  offset: number;
  returned: number;
  has_more: boolean;
  row_count: number | null;
}

export interface DataNode {
  name: string;
  hostname: string;
  state: "live" | "dead";
  admin_state: string | null;
  capacity: number;
  used: number;
  remaining: number;
  percent_used: number;
  blocks: number;
  last_contact: number | null;
  version: string | null;
  info_addr: string | null;
}

export interface NodeManager {
  id: string;
  hostname: string;
  state: string;
  http_address: string;
  health_report: string;
  last_health_update: number;
  containers: number;
  memory_used_mb: number;
  memory_available_mb: number;
  vcores_used: number;
  vcores_available: number;
  version: string | null;
}

export interface ClusterMetrics {
  apps_submitted: number;
  apps_running: number;
  apps_completed: number;
  apps_failed: number;
  containers_allocated: number;
  containers_pending: number;
  memory_total_mb: number;
  memory_allocated_mb: number;
  memory_available_mb: number;
  vcores_total: number;
  vcores_allocated: number;
  active_nodes: number;
  lost_nodes: number;
  unhealthy_nodes: number;
  decommissioned_nodes: number;
}

export interface HdfsSummary {
  capacity_total: number;
  capacity_used: number;
  capacity_remaining: number;
  percent_used: number;
  blocks_total: number;
  files_total: number;
  under_replicated_blocks: number;
  missing_blocks: number;
  corrupt_blocks: number;
  live_datanodes: number;
  dead_datanodes: number;
  decommissioning: number;
  safemode: string;
  configured_block_size: number;
  configured_replication: number;
  version: string | null;
  cluster_id: string | null;
}

export interface ServiceState {
  reachable: boolean;
  error: string | null;
}

export interface ClusterOverview {
  services: Record<string, ServiceState>;
  resourcemanager: {
    state: string | null;
    ha_state: string | null;
    hadoop_version: string | null;
    resource_manager_version: string | null;
    started_on: number | null;
  } | null;
  metrics: ClusterMetrics | null;
  hdfs: HdfsSummary | null;
  datanodes: DataNode[];
  nodemanagers: NodeManager[];
  profile: {
    replication: number;
    block_size: number;
    nodemanager_memory_mb: number;
    nodemanager_vcores: number;
    map_container_mb: number;
    reduce_container_mb: number;
    application_master_mb: number;
    default_reducers: number;
    expected_datanodes: number;
    expected_nodemanagers: number;
  };
  links: {
    namenode_ui: string;
    resourcemanager_ui: string;
    jobhistory_ui: string;
  };
}

export interface YarnApplication {
  id: string;
  name: string;
  state: string;
  final_status: string;
  progress: number;
  tracking_url: string;
  queue: string;
  started_time: number;
  finished_time: number;
  elapsed_time: number;
  allocated_mb: number | null;
  allocated_vcores: number | null;
  running_containers: number | null;
  memory_seconds: number | null;
  vcore_seconds: number | null;
  diagnostics: string;
  am_host_http_address: string | null;
}

export interface BlockLocation {
  offset: number;
  length: number;
  hosts: string[];
  names: string[];
  cached_hosts: string[];
  corrupt: boolean;
}

export interface HdfsEntry {
  path: string;
  name: string;
  is_directory: boolean;
  length: number;
  block_size: number;
  replication: number;
  modification_time: number;
  owner: string;
  group: string;
  permission: string;
  blocks?: BlockLocation[];
}

export interface HdfsListing {
  path: string;
  parent: string | null;
  root: string;
  summary: {
    directory_count: number;
    file_count: number;
    length: number;
    space_consumed: number;
    quota: number;
  } | null;
  entries: HdfsEntry[];
}

export interface VersionStorage {
  version_id: string;
  status: VersionStatus;
  replication: number;
  block_size: number;
  subtrees: Record<
    string,
    {
      path: string | null;
      exists: boolean;
      files?: HdfsEntry[];
      summary?: {
        directory_count: number;
        file_count: number;
        length: number;
        space_consumed: number;
      } | null;
      error?: string;
    }
  >;
  raw_block_locations?: BlockLocation[];
  raw_block_locations_error?: string;
}

export interface BenchmarkRunMetrics {
  run_id: string;
  run_key: string;
  label: string | null;
  status: RunStatus;
  dataset_name: string | null;
  dataset_version_number: number | null;
  validated_records: number | null;
  analyses: string[];
  total_duration_ms: number | null;
  stage_count: number;
  launched_map_tasks: number | null;
  launched_reduce_tasks: number | null;
  map_input_records: number | null;
  hdfs_bytes_read: number | null;
  hdfs_bytes_written: number | null;
  records_per_second: number | null;
  reducers: number | null;
  split_maxsize: number | null;
  live_datanodes: number | null;
  active_nodemanagers: number | null;
  per_analysis: {
    analysis: string;
    status: RunStatus;
    duration_ms: number | null;
    stages: number;
    launched_map_tasks: number | null;
    launched_reduce_tasks: number | null;
    map_input_records: number | null;
    hdfs_bytes_read: number | null;
    hdfs_bytes_written: number | null;
    stage_durations: { stage: string; duration_ms: number | null }[];
  }[];
}

export interface Benchmark {
  id: string;
  name: string;
  description: string | null;
  run_ids: string[];
  created_at: string;
}

export interface ClusterProfile {
  hadoop: { namenode: string; resourcemanager: string; jobhistory: string };
  hdfs: { replication: number; block_size: number; root: string };
  yarn: {
    nodemanager_memory_mb: number;
    nodemanager_vcores: number;
    map_container_mb: number;
    reduce_container_mb: number;
    application_master_mb: number;
  };
  mapreduce: { default_reducers: number; split_maxsize: number | null; jar: string };
  limits: {
    max_upload_mb: number;
    default_result_limit: number;
    max_result_limit: number;
  };
  topology_note: string;
}
