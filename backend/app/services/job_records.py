"""Turning a Hadoop job report into metadata rows.

The Java driver writes a JSON report containing, for each stage, the job id,
the YARN application id, the state, the timings and every counter group Hadoop
published. This module stores that verbatim and, where the JobHistoryServer can
be reached, enriches it with the node each task attempt ran on.

Every numeric field written here comes from Hadoop. The only values this module
computes are the primary keys.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import AnalysisExecution, DatasetVersion, JobExecution
from app.services import hadoop_jobs, yarn

log = get_logger(__name__)


def _as_datetime(epoch_millis: Any) -> datetime | None:
    try:
        millis = int(epoch_millis)
    except (TypeError, ValueError):
        return None
    if millis <= 0:
        return None
    return datetime.fromtimestamp(millis / 1000.0, tz=timezone.utc)


def persist_stages(
    session: Session,
    result: hadoop_jobs.JobRunResult,
    *,
    analysis_execution: AnalysisExecution | None = None,
    dataset_version: DatasetVersion | None = None,
    collect_placement: bool = True,
) -> list[JobExecution]:
    """Creates one :class:`JobExecution` row per reported MapReduce stage."""
    if analysis_execution is None and dataset_version is None:
        raise ValueError("a stage must belong to an analysis execution or a dataset version")

    rows: list[JobExecution] = []

    for index, stage in enumerate(result.stages):
        counters = hadoop_jobs.flatten_counters(stage)
        headline = hadoop_jobs.headline_counters(counters)
        job_id = stage.get("jobId") or ""

        record = JobExecution(
            analysis_execution_id=analysis_execution.id if analysis_execution else None,
            dataset_version_id=dataset_version.id if dataset_version else None,
            analysis=result.analysis,
            stage=stage.get("stage") or f"stage-{index}",
            stage_index=index,
            job_name=stage.get("jobName"),
            job_id=job_id or None,
            application_id=stage.get("applicationId") or None,
            tracking_url=stage.get("trackingUrl") or None,
            state=stage.get("state"),
            start_time=_as_datetime(stage.get("startTime")),
            finish_time=_as_datetime(stage.get("finishTime")),
            duration_ms=int(stage.get("durationMs") or 0) or None,
            configured_reducers=stage.get("configuredReducers"),
            launched_map_tasks=headline["launched_map_tasks"],
            launched_reduce_tasks=headline["launched_reduce_tasks"],
            failed_map_tasks=headline["failed_map_tasks"],
            failed_reduce_tasks=headline["failed_reduce_tasks"],
            map_input_records=headline["map_input_records"],
            map_output_records=headline["map_output_records"],
            reduce_input_groups=headline["reduce_input_groups"],
            reduce_output_records=headline["reduce_output_records"],
            hdfs_bytes_read=headline["hdfs_bytes_read"],
            hdfs_bytes_written=headline["hdfs_bytes_written"],
            input_paths=stage.get("inputPaths") or [],
            output_path=stage.get("outputPath") or None,
            counters={
                "groups": counters,
                "headline": headline,
                "cartscope": hadoop_jobs.custom_counters(counters),
            },
        )

        if collect_placement and job_id:
            record.task_attempts = _placement(job_id)

        session.add(record)
        rows.append(record)

    return rows


def _placement(job_id: str) -> list[dict[str, Any]]:
    """Task attempt placement from the JobHistoryServer, or an empty list.

    A missing JobHistoryServer must not fail a run that otherwise succeeded, so
    the failure is logged and the field is left empty rather than populated
    with anything made up.
    """
    try:
        return yarn.task_placement(job_id)
    except yarn.HadoopServiceError as unavailable:
        log.warning("task placement unavailable for %s: %s", job_id, unavailable)
        return []


def counter_value(
    jobs: list[JobExecution],
    group: str,
    name: str,
    *,
    stage: str | None = None,
) -> int | None:
    """Sums one counter across stages, or reads it from a single named stage."""
    total: int | None = None
    for job in jobs:
        if stage is not None and job.stage != stage:
            continue
        groups = (job.counters or {}).get("groups") or {}
        value = groups.get(group, {}).get(name)
        if value is None:
            continue
        total = value if total is None else total + value
    return total


def cartscope_counter(jobs: list[JobExecution], enum_path: str, name: str) -> int | None:
    """Reads one of the jobs' own counters, for example a rejection reason."""
    return counter_value(jobs, enum_path, name)
