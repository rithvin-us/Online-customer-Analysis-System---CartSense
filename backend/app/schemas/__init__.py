"""Request and response models.

Response models are explicit rather than inferred from the ORM, so that an
internal column rename cannot silently change the API, and so the UI has a
single place to look for the shape of everything it renders.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services import registry


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

class ColumnOut(ApiModel):
    name: str
    label: str
    type: str
    unit: str
    description: str


class OutputOut(ApiModel):
    name: str
    title: str
    description: str
    ranked: bool
    default_sort: str | None
    columns: list[ColumnOut]


class StageOut(ApiModel):
    name: str
    title: str
    purpose: str


class AnalysisOut(ApiModel):
    key: str
    title: str
    objective: str
    scope_note: str
    optional: bool
    stage_count: int
    stages: list[StageOut]
    outputs: list[OutputOut]


def analysis_to_schema(analysis: registry.Analysis) -> AnalysisOut:
    return AnalysisOut(
        key=analysis.key,
        title=analysis.title,
        objective=analysis.objective,
        scope_note=analysis.scope_note,
        optional=analysis.optional,
        stage_count=analysis.stage_count,
        stages=[StageOut(name=s.name, title=s.title, purpose=s.purpose) for s in analysis.stages],
        outputs=[
            OutputOut(
                name=o.name,
                title=o.title,
                description=o.description,
                ranked=o.ranked,
                default_sort=o.default_sort,
                columns=[
                    ColumnOut(
                        name=c.name, label=c.label, type=c.type,
                        unit=c.unit, description=c.description,
                    )
                    for c in o.columns
                ],
            )
            for o in analysis.outputs
        ],
    )


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------

class DatasetVersionSummary(ApiModel):
    id: uuid.UUID
    version_number: int
    status: str
    original_filename: str
    size_bytes: int
    sha256: str | None
    raw_line_count: int | None
    validated_record_count: int | None
    rejected_record_count: int | None
    duplicate_record_count: int | None
    created_at: datetime
    ready_at: datetime | None
    error: str | None


class DatasetVersionDetail(DatasetVersionSummary):
    encoding: str | None
    delimiter: str | None
    hdfs_raw_path: str | None
    hdfs_validated_path: str | None
    hdfs_rejected_path: str | None
    schema_report: dict[str, Any] | None
    quality_report: dict[str, Any] | None
    validation_counters: dict[str, Any] | None
    generation_spec: dict[str, Any] | None


class DatasetSummary(ApiModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    source: str
    created_at: datetime
    version_count: int
    latest_version: DatasetVersionSummary | None


class DatasetDetail(DatasetSummary):
    hdfs_path: str
    versions: list[DatasetVersionSummary]


class SyntheticRequest(BaseModel):
    """Ask for a larger dataset derived from an existing version."""

    source_version_id: uuid.UUID
    target_rows: int = Field(
        ...,
        ge=1_000,
        le=20_000_000,
        description="Approximate number of rows to generate. Generation stops on an "
                    "invoice boundary at or past this count.",
    )
    name: str | None = Field(default=None, max_length=200)
    seed: int = Field(default=20251030, description="Generation seed; the same seed "
                                                    "reproduces the same dataset.")

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip() if value else None


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

class RunConfiguration(BaseModel):
    """Hadoop settings a user may vary for one run."""

    reducers: int | None = Field(
        default=None, ge=1, le=32,
        description="Reducers per stage, unless the stage overrides it.",
    )
    stage_reducers: dict[str, int] = Field(
        default_factory=dict,
        description="Per-stage reducer counts, keyed by stage name.",
    )
    split_maxsize: int | None = Field(
        default=None, ge=65_536,
        description="Maximum bytes per input split. Lower it to create more map "
                    "tasks over the same data.",
    )
    day_first: bool = Field(
        default=False,
        description="Interpret ambiguous dates as day/month rather than month/day.",
    )
    rank_limit: int | None = Field(
        default=None, ge=1,
        description="Truncate ranked outputs to this many rows. Unset keeps every row.",
    )

    @field_validator("stage_reducers")
    @classmethod
    def _check_counts(cls, value: dict[str, int]) -> dict[str, int]:
        for stage, count in value.items():
            if not 1 <= count <= 32:
                raise ValueError(f"reducer count for stage {stage!r} must be between 1 and 32")
        return value


class RunCreate(BaseModel):
    dataset_version_id: uuid.UUID
    analyses: list[str] = Field(..., min_length=1)
    label: str | None = Field(default=None, max_length=200)
    notes: str | None = None
    configuration: RunConfiguration = Field(default_factory=RunConfiguration)

    @field_validator("analyses")
    @classmethod
    def _known(cls, value: list[str]) -> list[str]:
        return registry.validate_selection(value)


class JobExecutionOut(ApiModel):
    id: uuid.UUID
    analysis: str
    stage: str
    stage_index: int
    job_name: str | None
    job_id: str | None
    application_id: str | None
    tracking_url: str | None
    state: str | None
    start_time: datetime | None
    finish_time: datetime | None
    duration_ms: int | None
    configured_reducers: int | None
    launched_map_tasks: int | None
    launched_reduce_tasks: int | None
    failed_map_tasks: int | None
    failed_reduce_tasks: int | None
    map_input_records: int | None
    map_output_records: int | None
    reduce_input_groups: int | None
    reduce_output_records: int | None
    hdfs_bytes_read: int | None
    hdfs_bytes_written: int | None
    input_paths: list[str] | None
    output_path: str | None


class JobExecutionDetail(JobExecutionOut):
    counters: dict[str, Any] | None
    task_attempts: list[dict[str, Any]] | None
    placement_summary: dict[str, Any] | None = None
    #: The ResourceManager's current view of the application, when asked for.
    #: Absent rather than stale when the ResourceManager cannot be reached.
    live_application: dict[str, Any] | None = None


class ResultSetOut(ApiModel):
    id: uuid.UUID
    name: str
    hdfs_path: str
    row_count: int | None
    size_bytes: int | None
    columns: list[dict[str, Any]]


class AnalysisExecutionOut(ApiModel):
    id: uuid.UUID
    analysis: str
    position: int
    status: str
    hdfs_work_dir: str | None
    hdfs_result_dir: str | None
    hdfs_manifest_path: str | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    exit_code: int | None
    error: str | None
    jobs: list[JobExecutionOut]
    outputs: list[ResultSetOut]


class RunSummary(ApiModel):
    id: uuid.UUID
    run_key: str
    status: str
    label: str | None
    requested_analyses: list[str]
    dataset_version_id: uuid.UUID
    submitted_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    created_at: datetime
    error: str | None


class RunDetail(RunSummary):
    notes: str | None
    configuration: dict[str, Any]
    analyses: list[AnalysisExecutionOut]
    dataset_name: str | None = None
    dataset_id: uuid.UUID | None = None
    dataset_version_number: int | None = None
    validated_record_count: int | None = None


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

class ResultPage(BaseModel):
    name: str
    title: str
    description: str
    hdfs_path: str
    ranked: bool
    columns: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    offset: int
    returned: int
    has_more: bool
    row_count: int | None = None


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------

class BenchmarkCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    run_ids: list[uuid.UUID] = Field(..., min_length=2)


class BenchmarkOut(ApiModel):
    id: uuid.UUID
    name: str
    description: str | None
    run_ids: list[str]
    created_at: datetime


class BenchmarkRunMetrics(BaseModel):
    """What a run cost, for comparison against another run."""

    run_id: uuid.UUID
    run_key: str
    label: str | None
    status: str
    dataset_name: str | None
    dataset_version_number: int | None
    validated_records: int | None
    analyses: list[str]
    total_duration_ms: int | None
    stage_count: int
    launched_map_tasks: int | None
    launched_reduce_tasks: int | None
    map_input_records: int | None
    hdfs_bytes_read: int | None
    hdfs_bytes_written: int | None
    records_per_second: float | None
    reducers: int | None
    split_maxsize: int | None
    live_datanodes: int | None
    active_nodemanagers: int | None
    per_analysis: list[dict[str, Any]]


class SortDirection(BaseModel):
    column: str
    direction: Literal["asc", "desc"] = "desc"
