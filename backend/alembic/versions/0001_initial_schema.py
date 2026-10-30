"""Initial CartScope metadata schema.

Creates the tables that record datasets, their immutable versions, analysis
runs, the MapReduce stages those runs executed with the counters Hadoop
reported, the result sets in HDFS, saved benchmarks and cluster snapshots.

Revision ID: 0001
Revises:
Create Date: 2026-10-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# create_type=False: the types are created once, explicitly, below. Without it
# each CREATE TABLE that references a type would try to create it again, and
# run_status is referenced by two tables.
DATASET_SOURCE = postgresql.ENUM(
    "UPLOAD", "BUILTIN", "SYNTHETIC", name="dataset_source", create_type=False
)
VERSION_STATUS = postgresql.ENUM(
    "RECEIVED",
    "PROFILING",
    "UPLOADING_TO_HDFS",
    "VALIDATING",
    "READY",
    "FAILED",
    name="version_status",
    create_type=False,
)
RUN_STATUS = postgresql.ENUM(
    "PENDING",
    "RUNNING",
    "SUCCEEDED",
    "PARTIAL",
    "FAILED",
    "CANCELLED",
    name="run_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    DATASET_SOURCE.create(bind, checkfirst=True)
    VERSION_STATUS.create(bind, checkfirst=True)
    RUN_STATUS.create(bind, checkfirst=True)

    op.create_table(
        "datasets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("source", DATASET_SOURCE, nullable=False, server_default="UPLOAD"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "dataset_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", VERSION_STATUS, nullable=False, server_default="RECEIVED"),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64)),
        sa.Column("encoding", sa.String(40)),
        sa.Column("delimiter", sa.String(8)),
        sa.Column("raw_line_count", sa.BigInteger()),
        sa.Column("validated_record_count", sa.BigInteger()),
        sa.Column("rejected_record_count", sa.BigInteger()),
        sa.Column("duplicate_record_count", sa.BigInteger()),
        sa.Column("hdfs_raw_path", sa.String(600)),
        sa.Column("hdfs_validated_path", sa.String(600)),
        sa.Column("hdfs_rejected_path", sa.String(600)),
        sa.Column("schema_report", postgresql.JSONB()),
        sa.Column("quality_report", postgresql.JSONB()),
        sa.Column("validation_counters", postgresql.JSONB()),
        sa.Column("generation_spec", postgresql.JSONB()),
        sa.Column("error", sa.Text()),
        sa.Column("celery_task_id", sa.String(100)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("ready_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("dataset_id", "version_number", name="uq_dataset_version_number"),
    )
    op.create_index("ix_dataset_versions_dataset", "dataset_versions", ["dataset_id"])

    op.create_table(
        "analysis_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_key", sa.String(80), nullable=False, unique=True),
        sa.Column(
            "dataset_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dataset_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", RUN_STATUS, nullable=False, server_default="PENDING"),
        sa.Column("requested_analyses", postgresql.JSONB(), nullable=False),
        sa.Column("configuration", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("notes", sa.Text()),
        sa.Column("label", sa.String(200)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.BigInteger()),
        sa.Column("error", sa.Text()),
        sa.Column("celery_task_id", sa.String(100)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_analysis_runs_created", "analysis_runs", ["created_at"])

    op.create_table(
        "analysis_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("analysis", sa.String(60), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", RUN_STATUS, nullable=False, server_default="PENDING"),
        sa.Column("hdfs_work_dir", sa.String(600)),
        sa.Column("hdfs_result_dir", sa.String(600)),
        sa.Column("hdfs_manifest_path", sa.String(600)),
        sa.Column("log_path", sa.String(600)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.BigInteger()),
        sa.Column("exit_code", sa.Integer()),
        sa.Column("error", sa.Text()),
        sa.UniqueConstraint("run_id", "analysis", name="uq_run_analysis"),
    )
    op.create_index("ix_analysis_executions_run", "analysis_executions", ["run_id"])

    op.create_table(
        "job_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "analysis_execution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analysis_executions.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "dataset_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dataset_versions.id", ondelete="CASCADE"),
        ),
        sa.Column("analysis", sa.String(60), nullable=False),
        sa.Column("stage", sa.String(60), nullable=False),
        sa.Column("stage_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("job_name", sa.String(300)),
        sa.Column("job_id", sa.String(100)),
        sa.Column("application_id", sa.String(100)),
        sa.Column("tracking_url", sa.String(600)),
        sa.Column("state", sa.String(40)),
        sa.Column("start_time", sa.DateTime(timezone=True)),
        sa.Column("finish_time", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.BigInteger()),
        sa.Column("configured_reducers", sa.Integer()),
        sa.Column("launched_map_tasks", sa.Integer()),
        sa.Column("launched_reduce_tasks", sa.Integer()),
        sa.Column("failed_map_tasks", sa.Integer()),
        sa.Column("failed_reduce_tasks", sa.Integer()),
        sa.Column("map_input_records", sa.BigInteger()),
        sa.Column("map_output_records", sa.BigInteger()),
        sa.Column("reduce_input_groups", sa.BigInteger()),
        sa.Column("reduce_output_records", sa.BigInteger()),
        sa.Column("hdfs_bytes_read", sa.BigInteger()),
        sa.Column("hdfs_bytes_written", sa.BigInteger()),
        sa.Column("input_paths", postgresql.JSONB()),
        sa.Column("output_path", sa.String(600)),
        sa.Column("counters", postgresql.JSONB()),
        sa.Column("task_attempts", postgresql.JSONB()),
    )
    op.create_index("ix_job_executions_analysis", "job_executions", ["analysis_execution_id"])
    op.create_index("ix_job_executions_application", "job_executions", ["application_id"])

    op.create_table(
        "result_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "analysis_execution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analysis_executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("hdfs_path", sa.String(600), nullable=False),
        sa.Column("row_count", sa.BigInteger()),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("columns", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("analysis_execution_id", "name", name="uq_result_name"),
    )

    op.create_table(
        "benchmarks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("run_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "cluster_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("live_datanodes", sa.Integer()),
        sa.Column("dead_datanodes", sa.Integer()),
        sa.Column("active_nodemanagers", sa.Integer()),
        sa.Column("total_memory_mb", sa.Integer()),
        sa.Column("total_vcores", sa.Integer()),
        sa.Column("hdfs_capacity_bytes", sa.BigInteger()),
        sa.Column("hdfs_used_bytes", sa.BigInteger()),
        sa.Column("replication", sa.Integer()),
        sa.Column("block_size", sa.BigInteger()),
        sa.Column("healthy", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("detail", postgresql.JSONB()),
    )


def downgrade() -> None:
    op.drop_table("cluster_snapshots")
    op.drop_table("benchmarks")
    op.drop_table("result_sets")
    op.drop_index("ix_job_executions_application", table_name="job_executions")
    op.drop_index("ix_job_executions_analysis", table_name="job_executions")
    op.drop_table("job_executions")
    op.drop_index("ix_analysis_executions_run", table_name="analysis_executions")
    op.drop_table("analysis_executions")
    op.drop_index("ix_analysis_runs_created", table_name="analysis_runs")
    op.drop_table("analysis_runs")
    op.drop_index("ix_dataset_versions_dataset", table_name="dataset_versions")
    op.drop_table("dataset_versions")
    op.drop_table("datasets")

    bind = op.get_bind()
    RUN_STATUS.drop(bind, checkfirst=True)
    VERSION_STATUS.drop(bind, checkfirst=True)
    DATASET_SOURCE.drop(bind, checkfirst=True)
