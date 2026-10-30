"""Benchmarking: comparing what runs cost.

Every number here is derived from the counters and timings Hadoop reported for
the runs being compared. Throughput is the one computed value, and it is a plain
division of a Hadoop record count by a Hadoop-reported duration.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.db import get_session
from app.models import (
    AnalysisExecution,
    AnalysisRun,
    Benchmark,
    ClusterSnapshot,
    DatasetVersion,
    RunStatus,
)
from app.schemas import BenchmarkCreate, BenchmarkOut, BenchmarkRunMetrics
from app.services import hadoop_jobs

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])


def _sum(values: list[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _metrics(session: Session, run: AnalysisRun) -> BenchmarkRunMetrics:
    version = session.get(DatasetVersion, run.dataset_version_id)
    snapshot = (
        session.execute(
            select(ClusterSnapshot)
            .where(ClusterSnapshot.run_id == run.id)
            .order_by(ClusterSnapshot.captured_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )

    jobs = [job for execution in run.analyses for job in execution.jobs]
    configuration = dict(run.configuration or {})

    # The map input records of the first stage of each analysis is the number of
    # validated records that analysis actually read. Summing every stage would
    # double count, because later stages read the previous stage's output.
    first_stage_inputs = [
        min(execution.jobs, key=lambda job: job.stage_index).map_input_records
        for execution in run.analyses
        if execution.jobs
    ]
    records_read = _sum(first_stage_inputs)

    duration_ms = run.duration_ms
    throughput = None
    if records_read and duration_ms:
        throughput = round(records_read / (duration_ms / 1000.0), 2)

    per_analysis: list[dict[str, Any]] = []
    for execution in sorted(run.analyses, key=lambda item: item.position):
        stage_jobs = sorted(execution.jobs, key=lambda job: job.stage_index)
        per_analysis.append(
            {
                "analysis": execution.analysis,
                "status": execution.status.value,
                "duration_ms": execution.duration_ms,
                "stages": len(stage_jobs),
                "launched_map_tasks": _sum([job.launched_map_tasks for job in stage_jobs]),
                "launched_reduce_tasks": _sum([job.launched_reduce_tasks for job in stage_jobs]),
                "map_input_records": stage_jobs[0].map_input_records if stage_jobs else None,
                "hdfs_bytes_read": _sum([job.hdfs_bytes_read for job in stage_jobs]),
                "hdfs_bytes_written": _sum([job.hdfs_bytes_written for job in stage_jobs]),
                "stage_durations": [
                    {"stage": job.stage, "duration_ms": job.duration_ms} for job in stage_jobs
                ],
            }
        )

    return BenchmarkRunMetrics(
        run_id=run.id,
        run_key=run.run_key,
        label=run.label,
        status=run.status.value,
        dataset_name=version.dataset.name if version else None,
        dataset_version_number=version.version_number if version else None,
        validated_records=version.validated_record_count if version else None,
        analyses=list(run.requested_analyses),
        total_duration_ms=duration_ms,
        stage_count=len(jobs),
        launched_map_tasks=_sum([job.launched_map_tasks for job in jobs]),
        launched_reduce_tasks=_sum([job.launched_reduce_tasks for job in jobs]),
        map_input_records=records_read,
        hdfs_bytes_read=_sum([job.hdfs_bytes_read for job in jobs]),
        hdfs_bytes_written=_sum([job.hdfs_bytes_written for job in jobs]),
        records_per_second=throughput,
        reducers=configuration.get("reducers"),
        split_maxsize=configuration.get("split_maxsize"),
        live_datanodes=snapshot.live_datanodes if snapshot else None,
        active_nodemanagers=snapshot.active_nodemanagers if snapshot else None,
        per_analysis=per_analysis,
    )


def _load_runs(session: Session, run_ids: list[uuid.UUID]) -> list[AnalysisRun]:
    runs = (
        session.execute(
            select(AnalysisRun)
            .options(selectinload(AnalysisRun.analyses).selectinload(AnalysisExecution.jobs))
            .where(AnalysisRun.id.in_(run_ids))
        )
        .scalars()
        .all()
    )
    found = {run.id for run in runs}
    missing = [str(run_id) for run_id in run_ids if run_id not in found]
    if missing:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"unknown runs: {', '.join(missing)}"
        )
    order = {run_id: index for index, run_id in enumerate(run_ids)}
    return sorted(runs, key=lambda run: order[run.id])


@router.get("/runs", response_model=list[BenchmarkRunMetrics])
def compare_runs(
    run_id: list[uuid.UUID] = Query(default=[], description="Runs to compare. Repeatable."),
    limit: int = Query(default=10, ge=1, le=50),
    session: Session = Depends(get_session),
) -> list[BenchmarkRunMetrics]:
    """Execution metrics for the given runs, or for the most recent finished ones."""
    if run_id:
        runs = _load_runs(session, run_id)
    else:
        runs = (
            session.execute(
                select(AnalysisRun)
                .options(selectinload(AnalysisRun.analyses).selectinload(AnalysisExecution.jobs))
                .where(AnalysisRun.status.in_([RunStatus.SUCCEEDED, RunStatus.PARTIAL]))
                .order_by(AnalysisRun.created_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
    return [_metrics(session, run) for run in runs]


@router.post("", response_model=BenchmarkOut, status_code=status.HTTP_201_CREATED)
def save_benchmark(
    request: BenchmarkCreate, session: Session = Depends(get_session)
) -> BenchmarkOut:
    """Saves a named comparison so it can be reopened later."""
    _load_runs(session, request.run_ids)
    benchmark = Benchmark(
        name=request.name.strip(),
        description=(request.description or "").strip() or None,
        run_ids=[str(run_id) for run_id in request.run_ids],
    )
    session.add(benchmark)
    session.commit()
    return BenchmarkOut.model_validate(benchmark)


@router.get("", response_model=list[BenchmarkOut])
def list_benchmarks(session: Session = Depends(get_session)) -> list[BenchmarkOut]:
    benchmarks = (
        session.execute(select(Benchmark).order_by(Benchmark.created_at.desc()))
        .scalars()
        .all()
    )
    return [BenchmarkOut.model_validate(benchmark) for benchmark in benchmarks]


@router.get("/{benchmark_id}")
def get_benchmark(
    benchmark_id: uuid.UUID, session: Session = Depends(get_session)
) -> dict[str, Any]:
    benchmark = session.get(Benchmark, benchmark_id)
    if benchmark is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no benchmark {benchmark_id}")
    runs = _load_runs(session, [uuid.UUID(value) for value in benchmark.run_ids])
    return {
        "benchmark": BenchmarkOut.model_validate(benchmark).model_dump(mode="json"),
        "runs": [_metrics(session, run).model_dump(mode="json") for run in runs],
    }


@router.get("/counters/reference")
def counter_reference() -> dict[str, Any]:
    """The counters the product reports, and where each one comes from.

    Useful during a demonstration: it names the Hadoop counter group behind
    every figure shown in the UI.
    """
    return {
        "groups": {
            "task": hadoop_jobs.GROUP_TASK,
            "job": hadoop_jobs.GROUP_JOB,
            "filesystem": hadoop_jobs.GROUP_FILESYSTEM,
            "multiple_outputs": hadoop_jobs.GROUP_MULTIPLE_OUTPUTS,
            "validation": hadoop_jobs.GROUP_VALIDATION_STAT,
        },
        "headline": {
            "map_input_records": f"{hadoop_jobs.GROUP_TASK}.MAP_INPUT_RECORDS",
            "map_output_records": f"{hadoop_jobs.GROUP_TASK}.MAP_OUTPUT_RECORDS",
            "reduce_input_groups": f"{hadoop_jobs.GROUP_TASK}.REDUCE_INPUT_GROUPS",
            "reduce_output_records": f"{hadoop_jobs.GROUP_TASK}.REDUCE_OUTPUT_RECORDS",
            "launched_map_tasks": f"{hadoop_jobs.GROUP_JOB}.TOTAL_LAUNCHED_MAPS",
            "launched_reduce_tasks": f"{hadoop_jobs.GROUP_JOB}.TOTAL_LAUNCHED_REDUCES",
            "failed_map_tasks": f"{hadoop_jobs.GROUP_JOB}.NUM_FAILED_MAPS",
            "failed_reduce_tasks": f"{hadoop_jobs.GROUP_JOB}.NUM_FAILED_REDUCES",
            "hdfs_bytes_read": f"{hadoop_jobs.GROUP_FILESYSTEM}.HDFS_BYTES_READ",
            "hdfs_bytes_written": f"{hadoop_jobs.GROUP_FILESYSTEM}.HDFS_BYTES_WRITTEN",
        },
    }
