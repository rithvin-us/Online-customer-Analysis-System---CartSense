/**
 * Typed client for the CartScope API.
 *
 * Browser code calls the API on the host-published port; code running inside
 * the Next.js server talks to it over the Docker network. Both are configured,
 * so neither path depends on where the container happens to be running.
 */

import type {
  AnalysisDefinition,
  Benchmark,
  BenchmarkRunMetrics,
  ClusterOverview,
  ClusterProfile,
  DatasetDetail,
  DatasetSummary,
  DatasetVersionDetail,
  DatasetVersionSummary,
  HdfsListing,
  JobExecutionDetail,
  ResultPage,
  RunDetail,
  RunSummary,
  VersionStorage,
  YarnApplication,
} from "./types";

const BROWSER_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const SERVER_BASE = process.env.CARTSCOPE_INTERNAL_API_URL ?? BROWSER_BASE;

export function apiBase(): string {
  return typeof window === "undefined" ? SERVER_BASE : BROWSER_BASE;
}

/** An API error carrying the status and the backend's explanation. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase()}/api${path}`, {
    cache: "no-store",
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let detail: unknown = null;
    let message = `${response.status} ${response.statusText}`;
    try {
      detail = await response.json();
      const payload = detail as { detail?: unknown };
      if (typeof payload?.detail === "string") {
        message = payload.detail;
      } else if (Array.isArray(payload?.detail)) {
        // FastAPI validation errors arrive as a list of field problems.
        message = payload.detail
          .map((item) => {
            const entry = item as { loc?: unknown[]; msg?: string };
            const where = Array.isArray(entry.loc) ? entry.loc.join(".") : "";
            return where ? `${where}: ${entry.msg}` : entry.msg ?? "invalid";
          })
          .join("; ");
      }
    } catch {
      message = `${response.status} ${response.statusText}`;
    }
    throw new ApiError(response.status, message, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function requestText(path: string): Promise<string> {
  const response = await fetch(`${apiBase()}/api${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new ApiError(response.status, `${response.status} ${response.statusText}`, null);
  }
  return response.text();
}

// ---------------------------------------------------------------------------
// Catalogue and profile
// ---------------------------------------------------------------------------

export const getAnalyses = () => request<AnalysisDefinition[]>("/analyses");
export const getClusterProfile = () => request<ClusterProfile>("/profile");
export const getHealth = () =>
  request<{
    service: string;
    version: string;
    status: string;
    dependencies: Record<string, { reachable: boolean; error: string | null }>;
  }>("/health");

// ---------------------------------------------------------------------------
// Datasets
// ---------------------------------------------------------------------------

export const getDatasets = () => request<DatasetSummary[]>("/datasets");
export const getDataset = (datasetId: string) =>
  request<DatasetDetail>(`/datasets/${datasetId}`);

export function uploadDataset(form: FormData) {
  return request<DatasetDetail>("/datasets", { method: "POST", body: form });
}

export function uploadVersion(datasetId: string, form: FormData) {
  return request<DatasetVersionSummary>(`/datasets/${datasetId}/versions`, {
    method: "POST",
    body: form,
  });
}

export const getVersion = (datasetId: string, versionId: string) =>
  request<DatasetVersionDetail>(`/datasets/${datasetId}/versions/${versionId}`);

export const getVersionStorage = (datasetId: string, versionId: string) =>
  request<VersionStorage>(`/datasets/${datasetId}/versions/${versionId}/storage`);

export const getVersionRecords = (
  datasetId: string,
  versionId: string,
  kind: "validated" | "rejected",
  limit = 50,
  offset = 0,
) =>
  request<ResultPage>(
    `/datasets/${datasetId}/versions/${versionId}/records` +
      `?kind=${kind}&limit=${limit}&offset=${offset}`,
  );

export const retryVersion = (datasetId: string, versionId: string) =>
  request<DatasetVersionSummary>(`/datasets/${datasetId}/versions/${versionId}/retry`, {
    method: "POST",
  });

export const generateSynthetic = (
  datasetId: string,
  body: { source_version_id: string; target_rows: number; name?: string; seed?: number },
) =>
  request<DatasetVersionSummary>(`/datasets/${datasetId}/synthetic`, {
    method: "POST",
    body: JSON.stringify(body),
  });

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

export interface SubmitRunBody {
  dataset_version_id: string;
  analyses: string[];
  label?: string | null;
  notes?: string | null;
  configuration?: {
    reducers?: number | null;
    stage_reducers?: Record<string, number>;
    split_maxsize?: number | null;
    day_first?: boolean;
    rank_limit?: number | null;
  };
}

export const submitRun = (body: SubmitRunBody) =>
  request<RunDetail>("/runs", { method: "POST", body: JSON.stringify(body) });

export const getRuns = (limit = 50) => request<RunSummary[]>(`/runs?limit=${limit}`);
export const getRun = (runId: string) => request<RunDetail>(`/runs/${runId}`);

export const getStage = (runId: string, analysis: string, stage: string, live = false) =>
  request<JobExecutionDetail>(
    `/runs/${runId}/analyses/${analysis}/jobs/${stage}${live ? "?live=true" : ""}`,
  );

export const getAnalysisLog = (runId: string, analysis: string, tail = 0) =>
  requestText(`/runs/${runId}/analyses/${analysis}/logs${tail ? `?tail=${tail}` : ""}`);

export const getContainerLogs = (runId: string, analysis: string, stage: string) =>
  requestText(`/runs/${runId}/analyses/${analysis}/jobs/${stage}/container-logs`);

export const getResult = (
  runId: string,
  analysis: string,
  output: string,
  limit = 100,
  offset = 0,
) =>
  request<ResultPage>(
    `/runs/${runId}/analyses/${analysis}/results/${output}?limit=${limit}&offset=${offset}`,
  );

export function resultExportUrl(
  runId: string,
  analysis: string,
  output: string,
  format: "csv" | "json" | "tsv",
): string {
  return `${apiBase()}/api/runs/${runId}/analyses/${analysis}/results/${output}/export?format=${format}`;
}

export function runReportUrl(runId: string, includeRows = 20): string {
  return `${apiBase()}/api/runs/${runId}/report?include_rows=${includeRows}`;
}

export const getRunReport = (runId: string, includeRows = 20) =>
  request<Record<string, unknown>>(`/runs/${runId}/report?include_rows=${includeRows}`);

// ---------------------------------------------------------------------------
// Cluster
// ---------------------------------------------------------------------------

export const getCluster = () => request<ClusterOverview>("/cluster");
export const getApplications = (limit = 50) =>
  request<{ applications: YarnApplication[] }>(`/cluster/applications?limit=${limit}`);
export const getApplication = (applicationId: string) =>
  request<YarnApplication>(`/cluster/applications/${applicationId}`);
export const getJobCounters = (jobId: string) =>
  request<{
    job_id: string;
    counter_groups: { name: string; counters: { name: string; total: number }[] }[];
  }>(`/cluster/jobs/${jobId}/counters`);
export const getJobTasks = (jobId: string) =>
  request<{
    job_id: string;
    attempts: import("./types").TaskAttempt[];
    summary: import("./types").PlacementSummary;
  }>(`/cluster/jobs/${jobId}/tasks`);
export const browseHdfs = (path?: string, blocks = false) =>
  request<HdfsListing>(
    `/cluster/hdfs?${path ? `path=${encodeURIComponent(path)}&` : ""}blocks=${blocks}`,
  );

// ---------------------------------------------------------------------------
// Benchmarks
// ---------------------------------------------------------------------------

export const compareRuns = (runIds: string[], limit = 10) => {
  const query = runIds.length
    ? runIds.map((id) => `run_id=${id}`).join("&")
    : `limit=${limit}`;
  return request<BenchmarkRunMetrics[]>(`/benchmarks/runs?${query}`);
};

export const getBenchmarks = () => request<Benchmark[]>("/benchmarks");
export const saveBenchmark = (body: {
  name: string;
  description?: string | null;
  run_ids: string[];
}) => request<Benchmark>("/benchmarks", { method: "POST", body: JSON.stringify(body) });
export const getBenchmark = (benchmarkId: string) =>
  request<{ benchmark: Benchmark; runs: BenchmarkRunMetrics[] }>(
    `/benchmarks/${benchmarkId}`,
  );
