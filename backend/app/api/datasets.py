"""Dataset ingestion and inspection."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.db import get_session
from app.core.logging import get_logger
from app.models import Dataset, DatasetSource, DatasetVersion, VersionStatus
from app.schemas import (
    DatasetDetail,
    DatasetSummary,
    DatasetVersionDetail,
    DatasetVersionSummary,
    ResultPage,
    SyntheticRequest,
)
from app.services import hdfs, registry, results
from app.tasks.ingest_tasks import generate_synthetic_version, ingest_version, upload_path

log = get_logger(__name__)

router = APIRouter(prefix="/datasets", tags=["datasets"])

_ALLOWED_SUFFIXES = (".csv", ".txt", ".tsv")
_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
_CHUNK = 1_048_576


def _slugify(value: str) -> str:
    slug = _SLUG_PATTERN.sub("-", value.strip().lower()).strip("-")
    return slug or "dataset"


def _unique_slug(session: Session, base: str) -> str:
    slug = base
    suffix = 2
    while session.scalar(select(func.count()).select_from(Dataset).where(Dataset.slug == slug)):
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def _version_summary(version: DatasetVersion) -> DatasetVersionSummary:
    return DatasetVersionSummary(
        id=version.id,
        version_number=version.version_number,
        status=version.status.value,
        original_filename=version.original_filename,
        size_bytes=version.size_bytes,
        sha256=version.sha256,
        raw_line_count=version.raw_line_count,
        validated_record_count=version.validated_record_count,
        rejected_record_count=version.rejected_record_count,
        duplicate_record_count=version.duplicate_record_count,
        created_at=version.created_at,
        ready_at=version.ready_at,
        error=version.error,
    )


def _dataset_summary(dataset: Dataset) -> DatasetSummary:
    versions = sorted(dataset.versions, key=lambda item: item.version_number)
    return DatasetSummary(
        id=dataset.id,
        name=dataset.name,
        slug=dataset.slug,
        description=dataset.description,
        source=dataset.source.value,
        created_at=dataset.created_at,
        version_count=len(versions),
        latest_version=_version_summary(versions[-1]) if versions else None,
    )


async def _store_upload(file: UploadFile, destination_id: uuid.UUID) -> int:
    """Streams an upload to the uploads volume, enforcing the size limit.

    The file is written in chunks and the limit is checked as it is written, so
    an oversized upload is rejected without ever being held in memory or
    finished on disk.
    """
    target = upload_path(str(destination_id))
    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with target.open("wb") as handle:
            while chunk := await file.read(_CHUNK):
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    raise HTTPException(
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        f"the upload exceeds the {settings.max_upload_mb} MB limit",
                    )
                handle.write(chunk)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    if written == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "the uploaded file is empty")
    return written


def _check_filename(filename: str | None) -> str:
    name = (filename or "").strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "the upload has no filename")
    if not name.lower().endswith(_ALLOWED_SUFFIXES):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"only {', '.join(_ALLOWED_SUFFIXES)} files are accepted",
        )
    return name


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------

@router.get("", response_model=list[DatasetSummary])
def list_datasets(session: Session = Depends(get_session)) -> list[DatasetSummary]:
    datasets = (
        session.execute(
            select(Dataset)
            .options(selectinload(Dataset.versions))
            .order_by(Dataset.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [_dataset_summary(dataset) for dataset in datasets]


@router.post("", response_model=DatasetDetail, status_code=status.HTTP_201_CREATED)
async def create_dataset(
    file: UploadFile = File(..., description="A retail transaction CSV."),
    name: str = Form(..., max_length=200),
    description: str | None = Form(default=None),
    day_first: bool = Form(
        default=False,
        description="Interpret ambiguous dates as day/month rather than month/day.",
    ),
    session: Session = Depends(get_session),
) -> DatasetDetail:
    """Creates a dataset from an uploaded CSV and queues its ingestion.

    The response returns immediately with the version in ``RECEIVED``. Profiling,
    the HDFS upload and the Hadoop validation job all happen in the worker, and
    the version's status reports where it has got to.
    """
    filename = _check_filename(file.filename)

    dataset = Dataset(
        name=name.strip(),
        slug=_unique_slug(session, _slugify(name)),
        description=(description or "").strip() or None,
        source=DatasetSource.UPLOAD,
    )
    session.add(dataset)
    session.flush()

    version = DatasetVersion(
        dataset_id=dataset.id,
        version_number=1,
        original_filename=filename,
        status=VersionStatus.RECEIVED,
        generation_spec={"day_first": day_first} if day_first else None,
    )
    session.add(version)
    session.flush()

    version.size_bytes = await _store_upload(file, version.id)
    session.commit()

    task = ingest_version.delay(str(version.id))
    version.celery_task_id = task.id
    session.commit()
    session.refresh(dataset)

    log.info("queued ingestion of dataset %s version %s", dataset.slug, version.id)
    return _dataset_detail(dataset)


def _dataset_detail(dataset: Dataset) -> DatasetDetail:
    summary = _dataset_summary(dataset)
    return DatasetDetail(
        **summary.model_dump(),
        hdfs_path=settings.dataset_dir(str(dataset.id)),
        versions=[
            _version_summary(version)
            for version in sorted(dataset.versions, key=lambda item: item.version_number)
        ],
    )


@router.get("/{dataset_id}", response_model=DatasetDetail)
def get_dataset(dataset_id: uuid.UUID, session: Session = Depends(get_session)) -> DatasetDetail:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no dataset {dataset_id}")
    return _dataset_detail(dataset)


@router.post(
    "/{dataset_id}/versions",
    response_model=DatasetVersionSummary,
    status_code=status.HTTP_201_CREATED,
)
async def add_version(
    dataset_id: uuid.UUID,
    file: UploadFile = File(...),
    day_first: bool = Form(default=False),
    session: Session = Depends(get_session),
) -> DatasetVersionSummary:
    """Adds a new version to an existing dataset.

    Versions are never replaced. Analyses record the version they read, so an
    earlier result stays explainable after new data arrives.
    """
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no dataset {dataset_id}")
    filename = _check_filename(file.filename)

    next_number = 1 + (
        session.scalar(
            select(func.coalesce(func.max(DatasetVersion.version_number), 0)).where(
                DatasetVersion.dataset_id == dataset_id
            )
        )
        or 0
    )

    version = DatasetVersion(
        dataset_id=dataset.id,
        version_number=next_number,
        original_filename=filename,
        status=VersionStatus.RECEIVED,
        generation_spec={"day_first": day_first} if day_first else None,
    )
    session.add(version)
    session.flush()

    version.size_bytes = await _store_upload(file, version.id)
    session.commit()

    task = ingest_version.delay(str(version.id))
    version.celery_task_id = task.id
    session.commit()
    return _version_summary(version)


@router.post(
    "/{dataset_id}/synthetic",
    response_model=DatasetVersionSummary,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_synthetic_version(
    dataset_id: uuid.UUID,
    request: SyntheticRequest,
    session: Session = Depends(get_session),
) -> DatasetVersionSummary:
    """Generates a larger dataset from an existing version.

    The generated data lands in a new version of the *target* dataset, so the
    original and the amplified data sit side by side and a benchmark can compare
    them directly.
    """
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no dataset {dataset_id}")

    source = session.get(DatasetVersion, request.source_version_id)
    if source is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"no dataset version {request.source_version_id}"
        )
    if source.status is not VersionStatus.READY:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"the source version is {source.status.value}; it must be READY to generate from",
        )

    next_number = 1 + (
        session.scalar(
            select(func.coalesce(func.max(DatasetVersion.version_number), 0)).where(
                DatasetVersion.dataset_id == dataset_id
            )
        )
        or 0
    )

    version = DatasetVersion(
        dataset_id=dataset.id,
        version_number=next_number,
        original_filename=(
            request.name or f"synthetic-{request.target_rows}-rows.csv"
        ),
        status=VersionStatus.RECEIVED,
        generation_spec={
            "kind": "synthetic",
            "source_version_id": str(request.source_version_id),
            "target_rows": request.target_rows,
            "seed": request.seed,
            "day_first": False,
        },
    )
    session.add(version)
    session.commit()

    task = generate_synthetic_version.delay(
        str(version.id), str(request.source_version_id), request.target_rows, request.seed
    )
    version.celery_task_id = task.id
    session.commit()

    log.info(
        "queued synthetic generation of %d rows into dataset %s version %s",
        request.target_rows, dataset.slug, version.id,
    )
    return _version_summary(version)


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

@router.get("/{dataset_id}/versions/{version_id}", response_model=DatasetVersionDetail)
def get_version(
    dataset_id: uuid.UUID,
    version_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> DatasetVersionDetail:
    version = _require_version(session, dataset_id, version_id)
    return DatasetVersionDetail(
        **_version_summary(version).model_dump(),
        encoding=version.encoding,
        delimiter=version.delimiter,
        hdfs_raw_path=version.hdfs_raw_path,
        hdfs_validated_path=version.hdfs_validated_path,
        hdfs_rejected_path=version.hdfs_rejected_path,
        schema_report=version.schema_report,
        quality_report=version.quality_report,
        validation_counters=version.validation_counters,
        generation_spec=version.generation_spec,
    )


def _require_version(
    session: Session, dataset_id: uuid.UUID, version_id: uuid.UUID
) -> DatasetVersion:
    version = session.get(DatasetVersion, version_id)
    if version is None or version.dataset_id != dataset_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"dataset {dataset_id} has no version {version_id}",
        )
    return version


@router.get("/{dataset_id}/versions/{version_id}/records", response_model=ResultPage)
def read_records(
    dataset_id: uuid.UUID,
    version_id: uuid.UUID,
    kind: str = "validated",
    limit: int = 100,
    offset: int = 0,
    session: Session = Depends(get_session),
) -> ResultPage:
    """Pages through the canonical or the rejected records in HDFS."""
    version = _require_version(session, dataset_id, version_id)
    if kind not in registry.VALIDATION_OUTPUTS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"kind must be one of: {', '.join(registry.VALIDATION_OUTPUTS)}",
        )

    path = version.hdfs_validated_path if kind == "validated" else version.hdfs_rejected_path
    if not path:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"this version has no {kind} data yet; its status is {version.status.value}",
        )

    limit = max(1, min(limit, settings.max_result_limit))
    try:
        page = results.read_output(
            path, registry.VALIDATION_OUTPUTS[kind], limit=limit, offset=max(0, offset)
        )
    except results.ResultSchemaMismatch as mismatch:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(mismatch)) from mismatch
    except (hdfs.HdfsError, FileNotFoundError) as unreadable:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"HDFS could not be read: {unreadable}"
        ) from unreadable

    expected_count = (
        version.validated_record_count if kind == "validated" else version.rejected_record_count
    )
    return ResultPage(**page, row_count=expected_count)


@router.get("/{dataset_id}/versions/{version_id}/storage")
def describe_storage(
    dataset_id: uuid.UUID,
    version_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """How this version is actually stored in HDFS.

    Returns, for each subtree, the files it holds and, for the raw upload, the
    DataNodes holding each block. That is the direct answer to "is the data
    really in HDFS, split into blocks and replicated?".
    """
    version = _require_version(session, dataset_id, version_id)
    report: dict[str, Any] = {
        "version_id": str(version.id),
        "status": version.status.value,
        "replication": settings.hdfs_replication,
        "block_size": settings.hdfs_block_size,
        "subtrees": {},
    }

    for label, path in (
        ("raw", settings.raw_dir(str(dataset_id), str(version_id))),
        ("validated", version.hdfs_validated_path),
        ("rejected", version.hdfs_rejected_path),
    ):
        if not path:
            report["subtrees"][label] = {"path": None, "exists": False}
            continue
        entry: dict[str, Any] = {"path": path}
        try:
            entry["files"] = [item.to_dict() for item in hdfs.list_status(path)]
            entry["summary"] = hdfs.content_summary(path)
            entry["exists"] = True
        except FileNotFoundError:
            entry.update({"exists": False, "files": [], "summary": None})
        except hdfs.HdfsError as unreadable:
            entry.update({"exists": False, "error": str(unreadable)})
        report["subtrees"][label] = entry

    if version.hdfs_raw_path:
        try:
            report["raw_block_locations"] = hdfs.block_locations(version.hdfs_raw_path)
        except hdfs.HdfsError as unreadable:
            report["raw_block_locations_error"] = str(unreadable)

    return report


@router.post("/{dataset_id}/versions/{version_id}/retry", response_model=DatasetVersionSummary)
def retry_ingestion(
    dataset_id: uuid.UUID,
    version_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> DatasetVersionSummary:
    """Re-runs ingestion for a version that failed.

    Only a failed version may be retried, and only when its uploaded file is
    still on the volume. A version that reached READY is never re-ingested,
    because its validated data may already have analyses pointing at it.
    """
    version = _require_version(session, dataset_id, version_id)
    if version.status is not VersionStatus.FAILED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"only a FAILED version can be retried; this one is {version.status.value}",
        )
    if not upload_path(str(version.id)).is_file():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "the uploaded file is no longer on the volume; upload it again as a new version",
        )

    # Clear the partial HDFS state so the validation job's refusal to overwrite
    # an existing output does not block the retry.
    for path in (version.hdfs_validated_path, version.hdfs_rejected_path):
        if path and hdfs.exists(path):
            hdfs.remove(path)

    version.status = VersionStatus.RECEIVED
    version.error = None
    version.ready_at = None
    session.commit()

    task = ingest_version.delay(str(version.id))
    version.celery_task_id = task.id
    version.created_at = version.created_at or datetime.now(timezone.utc)
    session.commit()
    return _version_summary(version)
