"""Cluster observability: HDFS, YARN and the JobHistoryServer."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import PlainTextResponse

from app.core.config import settings
from app.services import hdfs, yarn

router = APIRouter(prefix="/cluster", tags=["cluster"])


@router.get("")
def cluster_overview() -> dict[str, Any]:
    """One view of the whole cluster, with each service reported separately.

    A service that cannot be reached is marked unreachable with the reason. The
    view never fills a gap with a plausible-looking number.
    """
    report = yarn.cluster_health()
    report["profile"] = {
        "replication": settings.hdfs_replication,
        "block_size": settings.hdfs_block_size,
        "nodemanager_memory_mb": settings.nm_memory_mb,
        "nodemanager_vcores": settings.nm_vcores,
        "map_container_mb": settings.map_memory_mb,
        "reduce_container_mb": settings.reduce_memory_mb,
        "application_master_mb": settings.am_memory_mb,
        "default_reducers": settings.default_reducers,
        "expected_datanodes": 3,
        "expected_nodemanagers": 3,
    }
    report["links"] = {
        "namenode_ui": settings.namenode_ui,
        "resourcemanager_ui": settings.rm_ui,
        "jobhistory_ui": settings.history_ui,
    }
    return report


@router.get("/applications")
def list_applications(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
    """Applications the ResourceManager knows about, newest first."""
    try:
        return {"applications": yarn.applications(limit=limit)}
    except yarn.HadoopServiceError as unavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(unavailable)) from unavailable


@router.get("/applications/{application_id}")
def get_application(application_id: str) -> dict[str, Any]:
    try:
        return yarn.application(application_id)
    except yarn.HadoopServiceError as unavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(unavailable)) from unavailable


@router.get("/applications/{application_id}/logs", response_class=PlainTextResponse)
def get_application_logs(application_id: str) -> PlainTextResponse:
    return PlainTextResponse(yarn.application_logs(application_id))


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    """Finished job detail from the JobHistoryServer."""
    try:
        return yarn.history_job(job_id)
    except yarn.HadoopServiceError as unavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(unavailable)) from unavailable


@router.get("/jobs/{job_id}/counters")
def get_job_counters(job_id: str) -> dict[str, Any]:
    """Counters straight from the JobHistoryServer, for cross-checking.

    The same counters are already stored with the run. This endpoint reads them
    from Hadoop again, which is how the UI can show that the stored numbers are
    the cluster's numbers.
    """
    try:
        return {"job_id": job_id, "counter_groups": yarn.history_counters(job_id)}
    except yarn.HadoopServiceError as unavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(unavailable)) from unavailable


@router.get("/jobs/{job_id}/tasks")
def get_job_tasks(job_id: str) -> dict[str, Any]:
    """Task attempts of a job and the worker container each one ran on."""
    try:
        placements = yarn.task_placement(job_id)
    except yarn.HadoopServiceError as unavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(unavailable)) from unavailable
    return {
        "job_id": job_id,
        "attempts": placements,
        "summary": yarn.placement_summary(placements),
    }


@router.get("/hdfs")
def browse_hdfs(
    path: str = Query(default=None, description="HDFS path to list. Defaults to the "
                                                "CartScope root."),
    blocks: bool = Query(default=False, description="Include block locations for files."),
) -> dict[str, Any]:
    """Lists an HDFS directory.

    Browsing is confined to the CartScope tree: this endpoint exists to explain
    the product's own storage, not to expose the filesystem.
    """
    target = (path or settings.hdfs_root).rstrip("/") or "/"
    root = settings.hdfs_root.rstrip("/")
    if target != root and not target.startswith(root + "/"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"path must be inside {root}",
        )

    try:
        entries = hdfs.list_status(target)
    except FileNotFoundError as missing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no such path: {target}") from missing
    except hdfs.HdfsError as unreadable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(unreadable)) from unreadable

    listing = []
    for entry in entries:
        item = entry.to_dict()
        if blocks and not entry.is_directory and entry.length:
            try:
                item["blocks"] = hdfs.block_locations(entry.path)
            except hdfs.HdfsError:
                item["blocks"] = []
        listing.append(item)

    summary = None
    try:
        summary = hdfs.content_summary(target)
    except (hdfs.HdfsError, FileNotFoundError):
        summary = None

    parent = target.rsplit("/", 1)[0] or "/"
    return {
        "path": target,
        "parent": parent if target != root else None,
        "root": root,
        "summary": summary,
        "entries": listing,
    }
