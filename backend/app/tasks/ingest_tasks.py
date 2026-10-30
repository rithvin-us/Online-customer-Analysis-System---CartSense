"""Ingestion: from an uploaded file to a validated dataset version in HDFS.

The pipeline is deliberately ordered so that nothing enters HDFS before it has
been understood, and nothing is called ready before Hadoop has validated it:

1.  profile the file — encoding, delimiter, schema, column statistics,
    duplicates, checksum;
2.  refuse it if a blocking problem was found;
3.  write the original bytes into HDFS, unmodified;
4.  run the Hadoop validation job, which produces the canonical and rejected
    forms and reports what it classified;
5.  record the job's real counters and mark the version ready.

Step 3 stores the upload as received. The canonical form in step 4 is an
additional representation: the raw data is never rewritten in place.
"""

from __future__ import annotations

import shutil
import subprocess
import uuid as uuid_module
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.db import session_scope
from app.core.logging import get_logger
from app.models import DatasetVersion, VersionStatus
from app.services import hadoop_jobs, hdfs, job_records, profiling, synthetic
from app.services.hadoop_jobs import (
    GROUP_MULTIPLE_OUTPUTS,
    GROUP_VALIDATION_STAT,
)
from app.tasks.celery_app import celery_app

log = get_logger(__name__)

RAW_FILENAME = "source.csv"


class IngestionFailed(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _key(value: str | uuid_module.UUID) -> uuid_module.UUID:
    """Primary keys are UUIDs; task arguments arrive as strings over JSON."""
    return value if isinstance(value, uuid_module.UUID) else uuid_module.UUID(str(value))


def upload_path(version_id: str) -> Path:
    return settings.upload_dir / f"{version_id}.csv"


def _set(version_id: str, **fields: Any) -> None:
    """Writes progress to the metadata store so the UI can follow it."""
    with session_scope() as session:
        version = session.get(DatasetVersion, _key(version_id))
        if version is None:
            raise IngestionFailed(f"dataset version {version_id} disappeared")
        for key, value in fields.items():
            setattr(version, key, value)


def _fail(version_id: str, message: str) -> None:
    log.error("ingestion of %s failed: %s", version_id, message)
    _set(version_id, status=VersionStatus.FAILED, error=message[:4000])


@celery_app.task(name="cartscope.ingest.version", bind=True, max_retries=0)
def ingest_version(self, version_id: str) -> dict[str, Any]:
    """Profiles, stores and validates one dataset version."""
    log.info("ingesting dataset version %s", version_id)

    with session_scope() as session:
        version = session.get(DatasetVersion, _key(version_id))
        if version is None:
            raise IngestionFailed(f"unknown dataset version {version_id}")
        dataset_id = str(version.dataset_id)
        day_first = bool((version.generation_spec or {}).get("day_first", False))

    local_file = upload_path(version_id)
    if not local_file.is_file():
        _fail(version_id, f"the uploaded file is missing at {local_file}")
        return {"status": "FAILED", "reason": "missing upload"}

    # --- 1. Profile ------------------------------------------------------
    _set(version_id, status=VersionStatus.PROFILING, error=None)
    try:
        profile = profiling.profile_csv(local_file)
    except profiling.ProfilingError as unusable:
        _fail(version_id, f"the file could not be read: {unusable}")
        return {"status": "FAILED", "reason": str(unusable)}

    quality = profile.quality_report()
    _set(
        version_id,
        sha256=profile.sha256,
        size_bytes=profile.size_bytes,
        encoding=profile.encoding,
        delimiter=profile.delimiter,
        raw_line_count=profile.data_rows,
        schema_report=profile.schema_report(),
        quality_report=quality,
    )

    # --- 2. Refuse a file that cannot be analysed ------------------------
    if quality["blocking_issues"]:
        reasons = "; ".join(issue["message"] for issue in quality["blocking_issues"])
        _fail(version_id, reasons)
        return {"status": "FAILED", "reason": reasons}

    # --- 3. Store the original in HDFS -----------------------------------
    raw_dir = settings.raw_dir(dataset_id, version_id)
    raw_path = f"{raw_dir}/{RAW_FILENAME}"
    _set(version_id, status=VersionStatus.UPLOADING_TO_HDFS)
    try:
        hdfs.mkdirs(raw_dir)
        hdfs.upload(
            str(local_file),
            raw_path,
            block_size=settings.hdfs_block_size,
            replication=settings.hdfs_replication,
        )
    except hdfs.HdfsError as storage_failure:
        _fail(version_id, f"HDFS upload failed: {storage_failure}\n{storage_failure.output}")
        return {"status": "FAILED", "reason": "hdfs upload failed"}

    _set(version_id, hdfs_raw_path=raw_path)

    # --- 4. Validate with Hadoop -----------------------------------------
    _set(version_id, status=VersionStatus.VALIDATING)
    run_key = f"ingest-{version_id}"
    log_path = settings.joblog_dir / run_key / "validation.log"

    overrides: dict[str, Any] = {
        "cartscope.reducers": settings.default_reducers,
        "cartscope.invoice.date.dayfirst": str(day_first).lower(),
    }
    if settings.split_maxsize:
        overrides["cartscope.split.maxsize"] = settings.split_maxsize

    result = hadoop_jobs.submit(
        "validate",
        inputs=[raw_dir],
        work_dir=settings.job_work_dir(run_key, "validation"),
        result_dir=settings.version_dir(dataset_id, version_id),
        run_key=run_key,
        log_path=log_path,
        manifest_path=settings.manifest_path(run_key, "validation"),
        overrides=overrides,
    )

    with session_scope() as session:
        version = session.get(DatasetVersion, _key(version_id))
        if version is None:
            raise IngestionFailed(f"dataset version {version_id} disappeared")
        stages = job_records.persist_stages(session, result, dataset_version=version)
        session.flush()

        if not result.succeeded:
            version.status = VersionStatus.FAILED
            version.error = (
                f"the Hadoop validation job failed (exit code {result.exit_code}). "
                f"Last output:\n{result.output_tail[-2000:]}"
            )
            return {"status": "FAILED", "reason": "validation job failed",
                    "log": str(log_path)}

        validated = job_records.counter_value(stages, GROUP_MULTIPLE_OUTPUTS, "validated")
        rejected = job_records.counter_value(stages, GROUP_MULTIPLE_OUTPUTS, "rejected")
        duplicates = job_records.counter_value(
            stages, GROUP_VALIDATION_STAT, "DUPLICATE_RECORDS"
        )

        version.validated_record_count = validated
        version.rejected_record_count = rejected
        version.duplicate_record_count = duplicates
        version.hdfs_validated_path = settings.validated_dir(dataset_id, version_id)
        version.hdfs_rejected_path = settings.rejected_dir(dataset_id, version_id)
        version.validation_counters = {
            "stages": [
                {
                    "stage": stage.stage,
                    "job_id": stage.job_id,
                    "application_id": stage.application_id,
                    "counters": stage.counters,
                }
                for stage in stages
            ],
            "classification": _classification_summary(stages),
        }
        version.status = VersionStatus.READY
        version.ready_at = _now()
        version.error = None

    log.info(
        "dataset version %s is ready: %s validated, %s rejected, %s duplicates removed",
        version_id, validated, rejected, duplicates,
    )
    return {
        "status": "READY",
        "validated_records": validated,
        "rejected_records": rejected,
        "duplicate_records": duplicates,
        "log": str(log_path),
    }


def _classification_summary(stages: list[Any]) -> dict[str, int | None]:
    """The validation job's own counters, named as the product reports them."""
    names = (
        "ACCEPTED_RECORDS",
        "FULFILLED_SALES",
        "RETURNS_AND_CANCELLATIONS",
        "CANCELLATION_INVOICES",
        "NEGATIVE_QUANTITY_LINES",
        "MISSING_CUSTOMER_ID",
        "MISSING_COUNTRY",
        "DUPLICATE_RECORDS",
        "HEADER_RECORDS",
        "BLANK_LINES",
        "MALFORMED_QUOTING",
        "WRONG_FIELD_COUNT",
        "MISSING_INVOICE_NO",
        "MISSING_STOCK_CODE",
        "UNPARSEABLE_QUANTITY",
        "ZERO_QUANTITY",
        "UNPARSEABLE_UNIT_PRICE",
        "NON_POSITIVE_UNIT_PRICE",
        "UNPARSEABLE_INVOICE_DATE",
    )
    return {
        name: job_records.counter_value(stages, GROUP_VALIDATION_STAT, name)
        for name in names
    }


@celery_app.task(name="cartscope.ingest.synthetic", bind=True, max_retries=0)
def generate_synthetic_version(
    self,
    version_id: str,
    source_version_id: str,
    target_rows: int,
    seed: int = 20251030,
) -> dict[str, Any]:
    """Builds a larger dataset from an existing one, then ingests it normally.

    The generated file goes through the same profiling, HDFS upload and Hadoop
    validation as a human upload. A synthetic dataset is not a special case
    anywhere downstream, which is what makes a benchmark against it comparable
    to one against the real data.
    """
    log.info(
        "generating %d rows for version %s from version %s",
        target_rows, version_id, source_version_id,
    )
    _set(version_id, status=VersionStatus.PROFILING, error=None)

    source_file = upload_path(source_version_id)
    if not source_file.is_file():
        source_file = _materialise_source(source_version_id)
    if source_file is None or not source_file.is_file():
        _fail(version_id, f"the source dataset version {source_version_id} is not available")
        return {"status": "FAILED", "reason": "source unavailable"}

    target_file = upload_path(version_id)
    try:
        profile = synthetic.learn(source_file)
        summary = synthetic.generate(
            profile, target_file, target_rows=target_rows, seed=seed
        )
    except (ValueError, OSError) as generation_failure:
        _fail(version_id, f"synthetic generation failed: {generation_failure}")
        return {"status": "FAILED", "reason": str(generation_failure)}

    with session_scope() as session:
        version = session.get(DatasetVersion, _key(version_id))
        if version is not None:
            spec = dict(version.generation_spec or {})
            spec.update(
                {
                    "source_version_id": source_version_id,
                    "target_rows": target_rows,
                    "seed": seed,
                    "result": summary,
                }
            )
            version.generation_spec = spec

    # Hand over to the ordinary ingestion pipeline. Calling the task directly
    # runs it in this worker process, inside this task, so the whole generate
    # and ingest sequence is one unit of work.
    return ingest_version(version_id)


def _materialise_source(source_version_id: str) -> Path | None:
    """Brings a dataset version's raw file back to local disk from HDFS.

    Needed when generating from a version whose upload has been cleaned off the
    local volume: the authoritative copy is the one in HDFS.
    """
    with session_scope() as session:
        version = session.get(DatasetVersion, _key(source_version_id))
        if version is None or not version.hdfs_raw_path:
            return None
        raw_path = version.hdfs_raw_path

    destination = settings.upload_dir / f"{source_version_id}.from-hdfs.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if destination.exists():
            destination.unlink()
        subprocess.run(
            ["hdfs", "dfs", "-get", raw_path, str(destination)],
            check=True,
            capture_output=True,
            text=True,
            timeout=1800,
        )
    except (subprocess.CalledProcessError, subprocess.SubprocessError, OSError) as failure:
        log.error("could not fetch %s from HDFS: %s", raw_path, failure)
        return None
    return destination


def discard_upload(version_id: str) -> None:
    """Removes the local copy of an upload. HDFS keeps the authoritative one."""
    path = upload_path(version_id)
    if path.exists():
        try:
            path.unlink()
        except OSError as failure:
            log.warning("could not remove %s: %s", path, failure)
    from_hdfs = settings.upload_dir / f"{version_id}.from-hdfs.csv"
    if from_hdfs.exists():
        try:
            from_hdfs.unlink()
        except OSError:
            pass


def copy_into_uploads(source: str | Path, version_id: str) -> Path:
    """Places a file on the uploads volume under the version's name."""
    destination = upload_path(version_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return destination
