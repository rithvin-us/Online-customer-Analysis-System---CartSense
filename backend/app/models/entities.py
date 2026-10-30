"""SQLAlchemy models: the platform's metadata store.

PostgreSQL holds metadata only. Every dataset, every intermediate stage and
every analytical result lives in HDFS; what is recorded here is where it lives,
how it was produced, and what Hadoop reported while producing it.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DatasetSource(str, enum.Enum):
    """Where a dataset came from."""

    UPLOAD = "UPLOAD"
    BUILTIN = "BUILTIN"
    SYNTHETIC = "SYNTHETIC"


class VersionStatus(str, enum.Enum):
    """Lifecycle of a dataset version."""

    RECEIVED = "RECEIVED"
    PROFILING = "PROFILING"
    UPLOADING_TO_HDFS = "UPLOADING_TO_HDFS"
    VALIDATING = "VALIDATING"
    READY = "READY"
    FAILED = "FAILED"


class RunStatus(str, enum.Enum):
    """Lifecycle of an analysis run or of one job within it."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Dataset(Base):
    """A named body of retail transaction data, holding one or more versions."""

    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[DatasetSource] = mapped_column(
        Enum(DatasetSource, name="dataset_source"), nullable=False, default=DatasetSource.UPLOAD
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    versions: Mapped[list["DatasetVersion"]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        order_by="DatasetVersion.version_number",
    )

    @property
    def hdfs_path(self) -> str:
        from app.core.config import settings

        return settings.dataset_dir(str(self.id))


class DatasetVersion(Base):
    """One immutable upload of a dataset, with its validated derivative.

    A version is never modified after it reaches ``READY``: a new upload or a
    new synthetic generation creates a new version. That is what makes an
    analysis run reproducible — the run records the version it read.
    """

    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "version_number", name="uq_dataset_version_number"),
        Index("ix_dataset_versions_dataset", "dataset_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[VersionStatus] = mapped_column(
        Enum(VersionStatus, name="version_status"), nullable=False, default=VersionStatus.RECEIVED
    )

    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: SHA-256 of the uploaded bytes. Two uploads of the same file are
    #: detectable, and the checksum is what a result is ultimately traceable to.
    sha256: Mapped[str | None] = mapped_column(String(64))
    encoding: Mapped[str | None] = mapped_column(String(40))
    delimiter: Mapped[str | None] = mapped_column(String(8))

    raw_line_count: Mapped[int | None] = mapped_column(BigInteger)
    validated_record_count: Mapped[int | None] = mapped_column(BigInteger)
    rejected_record_count: Mapped[int | None] = mapped_column(BigInteger)
    duplicate_record_count: Mapped[int | None] = mapped_column(BigInteger)

    hdfs_raw_path: Mapped[str | None] = mapped_column(String(600))
    hdfs_validated_path: Mapped[str | None] = mapped_column(String(600))
    hdfs_rejected_path: Mapped[str | None] = mapped_column(String(600))

    #: Column-by-column profile produced while reading the upload.
    schema_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    #: Counts and rates of every data quality problem found.
    quality_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    #: Counters reported by the Hadoop validation job.
    validation_counters: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    #: Generation parameters, for a synthetic version.
    generation_spec: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    error: Mapped[str | None] = mapped_column(Text)
    celery_task_id: Mapped[str | None] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    dataset: Mapped[Dataset] = relationship(back_populates="versions")
    validation_jobs: Mapped[list["JobExecution"]] = relationship(
        back_populates="dataset_version", cascade="all, delete-orphan"
    )
    runs: Mapped[list["AnalysisRun"]] = relationship(back_populates="dataset_version")


class AnalysisRun(Base):
    """One submission of one or more analyses against one dataset version."""

    __tablename__ = "analysis_runs"
    __table_args__ = (Index("ix_analysis_runs_created", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    #: Short human readable identifier, also used as the HDFS directory name.
    run_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="run_status"), nullable=False, default=RunStatus.PENDING
    )
    requested_analyses: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    #: Reducer count, split size and date interpretation actually used.
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(String(200))

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(Text)
    celery_task_id: Mapped[str | None] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    dataset_version: Mapped[DatasetVersion] = relationship(back_populates="runs")
    analyses: Mapped[list["AnalysisExecution"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AnalysisExecution.position"
    )


class AnalysisExecution(Base):
    """One analysis inside a run: the chain of MapReduce stages for it."""

    __tablename__ = "analysis_executions"
    __table_args__ = (
        UniqueConstraint("run_id", "analysis", name="uq_run_analysis"),
        Index("ix_analysis_executions_run", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    analysis: Mapped[str] = mapped_column(String(60), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="run_status"), nullable=False, default=RunStatus.PENDING
    )

    hdfs_work_dir: Mapped[str | None] = mapped_column(String(600))
    hdfs_result_dir: Mapped[str | None] = mapped_column(String(600))
    hdfs_manifest_path: Mapped[str | None] = mapped_column(String(600))
    #: Path on the worker's log volume holding the real stdout and stderr of
    #: the `hadoop jar` invocation.
    log_path: Mapped[str | None] = mapped_column(String(600))

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)

    run: Mapped[AnalysisRun] = relationship(back_populates="analyses")
    jobs: Mapped[list["JobExecution"]] = relationship(
        back_populates="analysis_execution",
        cascade="all, delete-orphan",
        order_by="JobExecution.stage_index",
    )
    outputs: Mapped[list["ResultSet"]] = relationship(
        back_populates="analysis_execution", cascade="all, delete-orphan"
    )


class JobExecution(Base):
    """One MapReduce job: a single stage of an analysis, or the validation job.

    Everything in this table other than the identifiers is read back from
    Hadoop: the job id, the YARN application id, the state, the timings and the
    counters. Nothing here is estimated by the backend.
    """

    __tablename__ = "job_executions"
    __table_args__ = (
        Index("ix_job_executions_analysis", "analysis_execution_id"),
        Index("ix_job_executions_application", "application_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    analysis_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analysis_executions.id", ondelete="CASCADE")
    )
    #: Set instead of ``analysis_execution_id`` for the ingestion validation job.
    dataset_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="CASCADE")
    )

    analysis: Mapped[str] = mapped_column(String(60), nullable=False)
    stage: Mapped[str] = mapped_column(String(60), nullable=False)
    stage_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    job_name: Mapped[str | None] = mapped_column(String(300))
    job_id: Mapped[str | None] = mapped_column(String(100))
    application_id: Mapped[str | None] = mapped_column(String(100))
    tracking_url: Mapped[str | None] = mapped_column(String(600))
    state: Mapped[str | None] = mapped_column(String(40))

    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finish_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)

    configured_reducers: Mapped[int | None] = mapped_column(Integer)
    launched_map_tasks: Mapped[int | None] = mapped_column(Integer)
    launched_reduce_tasks: Mapped[int | None] = mapped_column(Integer)
    failed_map_tasks: Mapped[int | None] = mapped_column(Integer)
    failed_reduce_tasks: Mapped[int | None] = mapped_column(Integer)
    map_input_records: Mapped[int | None] = mapped_column(BigInteger)
    map_output_records: Mapped[int | None] = mapped_column(BigInteger)
    reduce_input_groups: Mapped[int | None] = mapped_column(BigInteger)
    reduce_output_records: Mapped[int | None] = mapped_column(BigInteger)
    hdfs_bytes_read: Mapped[int | None] = mapped_column(BigInteger)
    hdfs_bytes_written: Mapped[int | None] = mapped_column(BigInteger)

    input_paths: Mapped[list[str] | None] = mapped_column(JSONB)
    output_path: Mapped[str | None] = mapped_column(String(600))
    #: Every counter group Hadoop reported, verbatim.
    counters: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    #: Per-attempt placement, read from the JobHistoryServer. This is what
    #: shows that map tasks really ran on different worker containers.
    task_attempts: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)

    analysis_execution: Mapped[AnalysisExecution | None] = relationship(back_populates="jobs")
    dataset_version: Mapped[DatasetVersion | None] = relationship(back_populates="validation_jobs")


class ResultSet(Base):
    """One output directory produced by an analysis, with its column layout."""

    __tablename__ = "result_sets"
    __table_args__ = (
        UniqueConstraint("analysis_execution_id", "name", name="uq_result_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    analysis_execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_executions.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    hdfs_path: Mapped[str] = mapped_column(String(600), nullable=False)
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    #: Column names and types, from the analysis registry.
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    analysis_execution: Mapped[AnalysisExecution] = relationship(back_populates="outputs")


class Benchmark(Base):
    """A saved comparison of analysis runs."""

    __tablename__ = "benchmarks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    run_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ClusterSnapshot(Base):
    """A point-in-time record of cluster capacity, taken when a run starts.

    Benchmarks are only meaningful next to the cluster that produced them, so
    the shape of the cluster is captured with the run rather than assumed.
    """

    __tablename__ = "cluster_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE")
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    live_datanodes: Mapped[int | None] = mapped_column(Integer)
    dead_datanodes: Mapped[int | None] = mapped_column(Integer)
    active_nodemanagers: Mapped[int | None] = mapped_column(Integer)
    total_memory_mb: Mapped[int | None] = mapped_column(Integer)
    total_vcores: Mapped[int | None] = mapped_column(Integer)
    hdfs_capacity_bytes: Mapped[int | None] = mapped_column(BigInteger)
    hdfs_used_bytes: Mapped[int | None] = mapped_column(BigInteger)
    replication: Mapped[int | None] = mapped_column(Integer)
    block_size: Mapped[int | None] = mapped_column(BigInteger)
    healthy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
