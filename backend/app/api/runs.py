"""Analysis runs: submission, observation, results and export."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.db import get_session
from app.core.logging import get_logger
from app.models import (
    AnalysisExecution,
    AnalysisRun,
    DatasetVersion,
    JobExecution,
    ResultSet,
    RunStatus,
    VersionStatus,
)
from app.schemas import (
    AnalysisExecutionOut,
    JobExecutionDetail,
    JobExecutionOut,
    ResultPage,
    ResultSetOut,
    RunCreate,
    RunDetail,
    RunSummary,
)
from app.services import hdfs, registry, results, yarn
from app.tasks.analysis_tasks import execute_run

log = get_logger(__name__)

router = APIRouter(prefix="/runs", tags=["runs"])


def _run_key() -> str:
    """A short, sortable, human readable run identifier.

    It doubles as the HDFS directory name for the run, which is why it avoids
    anything that would need escaping in a path.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"run-{stamp}-{uuid.uuid4().hex[:6]}"


def _summary(run: AnalysisRun) -> RunSummary:
    return RunSummary(
        id=run.id,
        run_key=run.run_key,
        status=run.status.value,
        label=run.label,
        requested_analyses=list(run.requested_analyses),
        dataset_version_id=run.dataset_version_id,
        submitted_at=run.submitted_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_ms=run.duration_ms,
        created_at=run.created_at,
        error=run.error,
    )


def _clean_tracking_url(url: str | None) -> str | None:
    if not url:
        return None
    return url.replace("resourcemanager:8088", "localhost:8088").replace("historyserver:19888", "localhost:19888")


def _job_out(job: JobExecution) -> JobExecutionOut:
    out = JobExecutionOut.model_validate(job)
    out.tracking_url = _clean_tracking_url(out.tracking_url)
    return out


def _execution_out(execution: AnalysisExecution) -> AnalysisExecutionOut:
    return AnalysisExecutionOut(
        id=execution.id,
        analysis=execution.analysis,
        position=execution.position,
        status=execution.status.value,
        hdfs_work_dir=execution.hdfs_work_dir,
        hdfs_result_dir=execution.hdfs_result_dir,
        hdfs_manifest_path=execution.hdfs_manifest_path,
        started_at=execution.started_at,
        finished_at=execution.finished_at,
        duration_ms=execution.duration_ms,
        exit_code=execution.exit_code,
        error=execution.error,
        jobs=[_job_out(job) for job in sorted(execution.jobs, key=lambda j: j.stage_index)],
        outputs=[ResultSetOut.model_validate(output) for output in execution.outputs],
    )


def _detail(run: AnalysisRun, version: DatasetVersion | None) -> RunDetail:
    return RunDetail(
        **_summary(run).model_dump(),
        notes=run.notes,
        configuration=dict(run.configuration or {}),
        analyses=[
            _execution_out(execution)
            for execution in sorted(run.analyses, key=lambda item: item.position)
        ],
        dataset_name=version.dataset.name if version else None,
        dataset_id=version.dataset_id if version else None,
        dataset_version_number=version.version_number if version else None,
        validated_record_count=version.validated_record_count if version else None,
    )


def _load_run(session: Session, run_id: uuid.UUID) -> AnalysisRun:
    run = (
        session.execute(
            select(AnalysisRun)
            .options(
                selectinload(AnalysisRun.analyses).selectinload(AnalysisExecution.jobs),
                selectinload(AnalysisRun.analyses).selectinload(AnalysisExecution.outputs),
            )
            .where(AnalysisRun.id == run_id)
        )
        .scalars()
        .one_or_none()
    )
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no analysis run {run_id}")
    return run


def _execution(run: AnalysisRun, analysis: str) -> AnalysisExecution:
    for execution in run.analyses:
        if execution.analysis == analysis:
            return execution
    raise HTTPException(
        status.HTTP_404_NOT_FOUND,
        f"run {run.run_key} did not include the analysis {analysis!r}",
    )


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------

@router.post("", response_model=RunDetail, status_code=status.HTTP_202_ACCEPTED)
def submit_run(request: RunCreate, session: Session = Depends(get_session)) -> RunDetail:
    """Submits one or more analyses against a validated dataset version.

    The run is persisted and handed to the worker; the response returns with
    every analysis ``PENDING``. Each analysis then reports its own status, its
    Hadoop job ids and its counters as the worker records them.
    """
    version = session.get(DatasetVersion, request.dataset_version_id)
    if version is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"no dataset version {request.dataset_version_id}"
        )
    if version.status is not VersionStatus.READY:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"the dataset version is {version.status.value}; it must be READY before an "
            "analysis can read it",
        )
    if not version.hdfs_validated_path:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "the dataset version has no validated data in HDFS"
        )

    run = AnalysisRun(
        run_key=_run_key(),
        dataset_version_id=version.id,
        status=RunStatus.PENDING,
        requested_analyses=request.analyses,
        configuration=request.configuration.model_dump(exclude_none=True),
        label=request.label,
        notes=request.notes,
        submitted_at=datetime.now(timezone.utc),
    )
    session.add(run)
    session.flush()

    for position, analysis_key in enumerate(request.analyses):
        session.add(
            AnalysisExecution(
                run_id=run.id,
                analysis=analysis_key,
                position=position,
                status=RunStatus.PENDING,
                hdfs_work_dir=settings.job_work_dir(run.run_key, analysis_key),
                hdfs_result_dir=settings.result_dir(run.run_key, analysis_key),
                hdfs_manifest_path=settings.manifest_path(run.run_key, analysis_key),
            )
        )
    session.commit()

    task = execute_run.delay(str(run.id))
    run.celery_task_id = task.id
    session.commit()

    run = _load_run(session, run.id)
    log.info("submitted run %s: %s", run.run_key, ", ".join(request.analyses))
    return _detail(run, version)


@router.get("", response_model=list[RunSummary])
def list_runs(
    limit: int = Query(default=50, ge=1, le=500),
    dataset_version_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
) -> list[RunSummary]:
    query = select(AnalysisRun).order_by(AnalysisRun.created_at.desc()).limit(limit)
    if dataset_version_id:
        query = query.where(AnalysisRun.dataset_version_id == dataset_version_id)
    runs = session.execute(query).scalars().all()
    return [_summary(run) for run in runs]


@router.get("/{run_id}", response_model=RunDetail)
def get_run(run_id: uuid.UUID, session: Session = Depends(get_session)) -> RunDetail:
    run = _load_run(session, run_id)
    version = session.get(DatasetVersion, run.dataset_version_id)
    return _detail(run, version)


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------

@router.get("/{run_id}/analyses/{analysis}/jobs/{stage}", response_model=JobExecutionDetail)
def get_stage(
    run_id: uuid.UUID,
    analysis: str,
    stage: str,
    live: bool = Query(
        default=False,
        description="Also ask the ResourceManager for the application's current state.",
    ),
    session: Session = Depends(get_session),
) -> JobExecutionDetail:
    """Everything recorded about one MapReduce stage, including its counters."""
    run = _load_run(session, run_id)
    execution = _execution(run, analysis)
    job = next((candidate for candidate in execution.jobs if candidate.stage == stage), None)
    if job is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"analysis {analysis} has no stage {stage!r}"
        )

    detail = JobExecutionDetail.model_validate(job)
    detail.tracking_url = _clean_tracking_url(detail.tracking_url)
    if job.task_attempts:
        detail.placement_summary = yarn.placement_summary(job.task_attempts)
    if live and job.application_id:
        try:
            detail_dict = detail.model_dump()
            detail_dict["live_application"] = yarn.application(job.application_id)
            return JobExecutionDetail(**detail_dict)
        except yarn.HadoopServiceError as unavailable:
            log.info("live application state unavailable: %s", unavailable)
    return detail


@router.get("/{run_id}/analyses/{analysis}/logs", response_class=PlainTextResponse)
def get_analysis_log(
    run_id: uuid.UUID,
    analysis: str,
    tail: int = Query(default=0, ge=0, le=100_000,
                      description="Return only the last N lines. 0 returns the whole log."),
    session: Session = Depends(get_session),
) -> PlainTextResponse:
    """The real stdout and stderr of the ``hadoop jar`` invocation.

    This is the client-side log: the submission, the split count, the progress
    percentages and the counter dump Hadoop printed. Container logs from the
    workers are a separate endpoint, served from the aggregated YARN logs.
    """
    run = _load_run(session, run_id)
    execution = _execution(run, analysis)
    if not execution.log_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "this analysis has no log yet")

    from pathlib import Path

    path = Path(execution.log_path)
    if not path.is_file():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"the log file {path} is not present on this container's volume",
        )
    text = path.read_text(encoding="utf-8", errors="replace")
    if tail:
        text = "\n".join(text.splitlines()[-tail:])
    return PlainTextResponse(text)


@router.get(
    "/{run_id}/analyses/{analysis}/jobs/{stage}/container-logs",
    response_class=PlainTextResponse,
)
def get_container_logs(
    run_id: uuid.UUID,
    analysis: str,
    stage: str,
    session: Session = Depends(get_session),
) -> PlainTextResponse:
    """Aggregated container logs for a stage's YARN application.

    These are the logs the NodeManagers wrote and aggregated into HDFS: the
    ApplicationMaster's log and one section per map and reduce attempt. If
    aggregation has not completed, the message Hadoop returns is passed through
    unchanged.
    """
    run = _load_run(session, run_id)
    execution = _execution(run, analysis)
    job = next((candidate for candidate in execution.jobs if candidate.stage == stage), None)
    if job is None or not job.application_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"no YARN application recorded for stage {stage!r}"
        )
    return PlainTextResponse(yarn.application_logs(job.application_id))


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

def _result_set(execution: AnalysisExecution, output: str) -> ResultSet:
    for candidate in execution.outputs:
        if candidate.name == output:
            return candidate
    available = ", ".join(sorted(item.name for item in execution.outputs)) or "none"
    raise HTTPException(
        status.HTTP_404_NOT_FOUND,
        f"analysis {execution.analysis} has no output {output!r}; available: {available}",
    )


@router.get("/{run_id}/analyses/{analysis}/results/{output}", response_model=ResultPage)
def read_result(
    run_id: uuid.UUID,
    analysis: str,
    output: str,
    limit: int = Query(default=0, ge=0, le=5000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> ResultPage:
    """Pages through one result directory produced by the reducers."""
    run = _load_run(session, run_id)
    execution = _execution(run, analysis)
    result_set = _result_set(execution, output)
    definition = registry.get_analysis(analysis).output(output)

    page_size = limit or settings.default_result_limit
    page_size = min(page_size, settings.max_result_limit)

    try:
        page = results.read_output(
            result_set.hdfs_path, definition, limit=page_size, offset=offset
        )
    except results.ResultSchemaMismatch as mismatch:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(mismatch)) from mismatch
    except (hdfs.HdfsError, FileNotFoundError) as unreadable:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"HDFS could not be read: {unreadable}"
        ) from unreadable

    return ResultPage(**page, row_count=result_set.row_count)


@router.get("/{run_id}/analyses/{analysis}/results/{output}/export")
def export_result(
    run_id: uuid.UUID,
    analysis: str,
    output: str,
    file_format: str = Query(default="csv", alias="format", pattern="^(csv|json|tsv)$"),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    """Streams a whole result out of HDFS as CSV, TSV or JSON.

    The response is streamed a page at a time, so exporting a large result does
    not require the backend to hold it in memory.
    """
    run = _load_run(session, run_id)
    execution = _execution(run, analysis)
    result_set = _result_set(execution, output)
    definition = registry.get_analysis(analysis).output(output)

    filename = f"{run.run_key}-{analysis}-{output}.{file_format}"

    if file_format == "json":
        def generate_json():
            yield "[\n"
            first = True
            for row in results.iter_all_rows(result_set.hdfs_path, definition):
                yield ("" if first else ",\n") + json.dumps(row)
                first = False
            yield "\n]\n"

        return StreamingResponse(
            generate_json(),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if file_format == "tsv":
        def generate_tsv():
            yield "\t".join(column.name for column in definition.columns) + "\n"
            for row in results.iter_all_rows(result_set.hdfs_path, definition):
                yield "\t".join(
                    "" if row[column.name] is None else str(row[column.name])
                    for column in definition.columns
                ) + "\n"

        return StreamingResponse(
            generate_tsv(),
            media_type="text/tab-separated-values",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return StreamingResponse(
        results.export_csv(result_set.hdfs_path, definition),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{run_id}/report")
def run_report(
    run_id: uuid.UUID,
    include_rows: int = Query(
        default=20, ge=0, le=500,
        description="Rows of each result to embed. 0 embeds metadata only.",
    ),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """A self-contained analytical report for one run.

    Bundles the dataset provenance, the exact Hadoop configuration used, every
    stage with its real counters and task placement, and the head of each
    result. This is the artefact to attach to a write-up: it explains where
    each number came from.
    """
    run = _load_run(session, run_id)
    version = session.get(DatasetVersion, run.dataset_version_id)

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run": _summary(run).model_dump(mode="json"),
        "configuration": dict(run.configuration or {}),
        "cluster_profile": {
            "hdfs_replication": settings.hdfs_replication,
            "hdfs_block_size": settings.hdfs_block_size,
            "nodemanager_memory_mb": settings.nm_memory_mb,
            "map_container_mb": settings.map_memory_mb,
            "reduce_container_mb": settings.reduce_memory_mb,
            "default_reducers": settings.default_reducers,
        },
        "dataset": None,
        "analyses": [],
    }

    if version is not None:
        report["dataset"] = {
            "dataset_id": str(version.dataset_id),
            "dataset_name": version.dataset.name,
            "version_id": str(version.id),
            "version_number": version.version_number,
            "original_filename": version.original_filename,
            "sha256": version.sha256,
            "size_bytes": version.size_bytes,
            "raw_line_count": version.raw_line_count,
            "validated_record_count": version.validated_record_count,
            "rejected_record_count": version.rejected_record_count,
            "duplicate_record_count": version.duplicate_record_count,
            "hdfs_raw_path": version.hdfs_raw_path,
            "hdfs_validated_path": version.hdfs_validated_path,
            "quality_report": version.quality_report,
            "validation_classification": (version.validation_counters or {}).get(
                "classification"
            ),
        }

    for execution in sorted(run.analyses, key=lambda item: item.position):
        definition = registry.get_analysis(execution.analysis)
        entry: dict[str, Any] = {
            "analysis": execution.analysis,
            "title": definition.title,
            "objective": definition.objective,
            "scope_note": definition.scope_note,
            "status": execution.status.value,
            "duration_ms": execution.duration_ms,
            "error": execution.error,
            "stages": [],
            "results": [],
        }

        for job in sorted(execution.jobs, key=lambda item: item.stage_index):
            entry["stages"].append(
                {
                    "stage": job.stage,
                    "job_id": job.job_id,
                    "application_id": job.application_id,
                    "state": job.state,
                    "duration_ms": job.duration_ms,
                    "configured_reducers": job.configured_reducers,
                    "counters": (job.counters or {}).get("headline"),
                    "cartscope_counters": (job.counters or {}).get("cartscope"),
                    "placement": (
                        yarn.placement_summary(job.task_attempts) if job.task_attempts else None
                    ),
                }
            )

        for result_set in execution.outputs:
            output_entry: dict[str, Any] = {
                "name": result_set.name,
                "hdfs_path": result_set.hdfs_path,
                "row_count": result_set.row_count,
                "columns": result_set.columns,
            }
            if include_rows:
                try:
                    page = results.read_output(
                        result_set.hdfs_path,
                        definition.output(result_set.name),
                        limit=include_rows,
                    )
                    output_entry["rows"] = page["rows"]
                except (hdfs.HdfsError, FileNotFoundError, results.ResultSchemaMismatch) as e:
                    output_entry["rows_error"] = str(e)
            entry["results"].append(output_entry)

        report["analyses"].append(entry)

    return report
