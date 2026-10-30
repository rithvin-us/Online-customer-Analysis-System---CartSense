"""Analysis orchestration.

A run is a list of analyses against one dataset version. For each analysis this
task submits the real Hadoop job chain, waits for it, and records what Hadoop
reported. The analyses of a run are executed one after another rather than in
parallel: the development cluster has 6 GiB of schedulable memory, and two
concurrent chains would spend most of their time queued behind each other in
YARN instead of running, which would make the benchmark timings meaningless.

The run's status reflects reality: SUCCEEDED when every analysis finished,
PARTIAL when some did, FAILED when none did.
"""

from __future__ import annotations

import uuid as uuid_module
from datetime import datetime, timezone
from typing import Any

from celery import shared_task

from app.core.config import settings
from app.core.db import session_scope
from app.core.logging import get_logger
from app.models import (
    AnalysisExecution,
    AnalysisRun,
    ClusterSnapshot,
    DatasetVersion,
    ResultSet,
    RunStatus,
)
from app.services import hadoop_jobs, hdfs, job_records, registry, yarn

log = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _key(value: str | uuid_module.UUID) -> uuid_module.UUID:
    return value if isinstance(value, uuid_module.UUID) else uuid_module.UUID(str(value))


@shared_task(name="cartscope.analysis.run", bind=True, max_retries=0)
def execute_run(self, run_id: str) -> dict[str, Any]:
    """Runs every analysis of one run."""
    run_pk = _key(run_id)

    with session_scope() as session:
        run = session.get(AnalysisRun, run_pk)
        if run is None:
            raise RuntimeError(f"unknown analysis run {run_id}")
        version = session.get(DatasetVersion, run.dataset_version_id)
        if version is None or not version.hdfs_validated_path:
            run.status = RunStatus.FAILED
            run.error = "the dataset version has no validated data to analyse"
            run.finished_at = _now()
            return {"status": "FAILED", "reason": "dataset not validated"}

        run.status = RunStatus.RUNNING
        run.started_at = _now()
        run.error = None
        run_key = run.run_key
        validated_path = version.hdfs_validated_path
        configuration = dict(run.configuration or {})
        analyses = list(run.requested_analyses)

    _capture_cluster_snapshot(run_pk)

    log.info("run %s: executing %s", run_key, ", ".join(analyses))
    succeeded: list[str] = []
    failed: list[str] = []

    for analysis_key in analyses:
        if _execute_analysis(run_pk, run_key, analysis_key, validated_path, configuration):
            succeeded.append(analysis_key)
        else:
            failed.append(analysis_key)

    with session_scope() as session:
        run = session.get(AnalysisRun, run_pk)
        if run is None:
            raise RuntimeError(f"analysis run {run_id} disappeared")
        run.finished_at = _now()
        if run.started_at:
            run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
        if failed and succeeded:
            run.status = RunStatus.PARTIAL
            run.error = "these analyses failed: " + ", ".join(failed)
        elif failed:
            run.status = RunStatus.FAILED
            run.error = "every analysis failed: " + ", ".join(failed)
        else:
            run.status = RunStatus.SUCCEEDED
            run.error = None

    log.info("run %s finished: %d succeeded, %d failed", run_key, len(succeeded), len(failed))
    return {
        "status": "SUCCEEDED" if not failed else ("PARTIAL" if succeeded else "FAILED"),
        "succeeded": succeeded,
        "failed": failed,
    }


def _execute_analysis(
    run_pk: uuid_module.UUID,
    run_key: str,
    analysis_key: str,
    validated_path: str,
    configuration: dict[str, Any],
) -> bool:
    """Submits one analysis chain and records the outcome. Returns success."""
    definition = registry.get_analysis(analysis_key)
    work_dir = settings.job_work_dir(run_key, analysis_key)
    result_dir = settings.result_dir(run_key, analysis_key)
    manifest_path = settings.manifest_path(run_key, analysis_key)
    log_path = settings.joblog_dir / run_key / f"{analysis_key}.log"

    with session_scope() as session:
        execution = _execution_for(session, run_pk, analysis_key)
        execution.status = RunStatus.RUNNING
        execution.started_at = _now()
        execution.hdfs_work_dir = work_dir
        execution.hdfs_result_dir = result_dir
        execution.hdfs_manifest_path = manifest_path
        execution.log_path = str(log_path)
        execution.error = None

    overrides = _overrides(configuration)
    result = hadoop_jobs.submit(
        analysis_key,
        inputs=[validated_path],
        work_dir=work_dir,
        result_dir=result_dir,
        run_key=run_key,
        log_path=log_path,
        manifest_path=manifest_path,
        overrides=overrides,
    )

    with session_scope() as session:
        execution = _execution_for(session, run_pk, analysis_key)
        execution.finished_at = _now()
        execution.exit_code = result.exit_code
        if execution.started_at:
            execution.duration_ms = int(
                (execution.finished_at - execution.started_at).total_seconds() * 1000
            )

        job_records.persist_stages(session, result, analysis_execution=execution)

        if not result.succeeded:
            execution.status = RunStatus.FAILED
            execution.error = (
                f"the Hadoop job chain for {analysis_key} failed "
                f"(exit code {result.exit_code}). Last output:\n"
                f"{result.output_tail[-3000:]}"
            )
            return False

        execution.status = RunStatus.SUCCEEDED
        _record_outputs(session, execution, definition, result.outputs)

    return True


def _execution_for(session, run_pk: uuid_module.UUID, analysis_key: str) -> AnalysisExecution:
    execution = (
        session.query(AnalysisExecution)
        .filter(AnalysisExecution.run_id == run_pk, AnalysisExecution.analysis == analysis_key)
        .one_or_none()
    )
    if execution is None:
        raise RuntimeError(f"run {run_pk} has no execution row for {analysis_key}")
    return execution


def _overrides(configuration: dict[str, Any]) -> dict[str, Any]:
    """Maps the run's configuration onto Hadoop ``-D`` options.

    Only options the user actually chose are passed, so a run's command line
    shows exactly what was non-default about it.
    """
    overrides: dict[str, Any] = {}

    reducers = configuration.get("reducers") or settings.default_reducers
    overrides["cartscope.reducers"] = reducers

    for stage, count in (configuration.get("stage_reducers") or {}).items():
        overrides[f"cartscope.reducers.{stage}"] = count

    split_maxsize = configuration.get("split_maxsize") or settings.split_maxsize
    if split_maxsize:
        overrides["cartscope.split.maxsize"] = split_maxsize

    if configuration.get("day_first"):
        overrides["cartscope.invoice.date.dayfirst"] = "true"

    rank_limit = configuration.get("rank_limit")
    if rank_limit:
        overrides["cartscope.rank.limit.customers"] = rank_limit
        overrides["cartscope.rank.limit.products"] = rank_limit

    return overrides


def _record_outputs(
    session,
    execution: AnalysisExecution,
    definition: registry.Analysis,
    reported_outputs: dict[str, str],
) -> None:
    """Registers each result directory the driver reported, with its columns.

    The row count comes from counting the data in HDFS, not from a counter,
    because a result directory is the thing the user will page through and its
    length must match what paging reports.
    """
    existing = {output.name: output for output in execution.outputs}

    for name, hdfs_path in reported_outputs.items():
        try:
            output_definition = definition.output(name)
        except KeyError:
            log.warning(
                "analysis %s reported an output %r that is not in the registry",
                definition.key, name,
            )
            continue

        try:
            row_count = hdfs.count_rows(hdfs_path)
        except hdfs.HdfsError as unreadable:
            log.warning("could not count rows in %s: %s", hdfs_path, unreadable)
            row_count = None

        try:
            size_bytes = hdfs.content_summary(hdfs_path)["length"]
        except (hdfs.HdfsError, FileNotFoundError):
            size_bytes = None

        record = existing.get(name) or ResultSet(
            analysis_execution_id=execution.id, name=name, hdfs_path=hdfs_path
        )
        record.hdfs_path = hdfs_path
        record.row_count = row_count
        record.size_bytes = size_bytes
        record.columns = [
            {
                "name": column.name,
                "label": column.label,
                "type": column.type,
                "unit": column.unit,
                "description": column.description,
            }
            for column in output_definition.columns
        ]
        session.add(record)


def _capture_cluster_snapshot(run_pk: uuid_module.UUID) -> None:
    """Records the cluster's shape at the moment the run began.

    A benchmark number without the cluster that produced it is not comparable,
    so the capacity is stored with the run rather than assumed to be constant.
    """
    snapshot = ClusterSnapshot(run_id=run_pk, replication=settings.hdfs_replication,
                               block_size=settings.hdfs_block_size)
    detail: dict[str, Any] = {}

    try:
        metrics = yarn.cluster_metrics()
        snapshot.active_nodemanagers = metrics["active_nodes"]
        snapshot.total_memory_mb = metrics["memory_total_mb"]
        snapshot.total_vcores = metrics["vcores_total"]
        detail["yarn"] = metrics
    except yarn.HadoopServiceError as unavailable:
        detail["yarn_error"] = str(unavailable)
        snapshot.healthy = False

    try:
        summary = yarn.hdfs_summary()
        snapshot.live_datanodes = summary["live_datanodes"]
        snapshot.dead_datanodes = summary["dead_datanodes"]
        snapshot.hdfs_capacity_bytes = summary["capacity_total"]
        snapshot.hdfs_used_bytes = summary["capacity_used"]
        detail["hdfs"] = summary
    except yarn.HadoopServiceError as unavailable:
        detail["hdfs_error"] = str(unavailable)
        snapshot.healthy = False

    snapshot.detail = detail
    with session_scope() as session:
        session.add(snapshot)
