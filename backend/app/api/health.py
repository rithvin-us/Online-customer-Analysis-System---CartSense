"""Liveness and readiness."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import __version__
from app.core.config import settings
from app.core.db import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
def health(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Reports each dependency separately, so a partial outage is visible."""
    report: dict[str, Any] = {
        "service": "cartscope-api",
        "version": __version__,
        "status": "ok",
        "dependencies": {},
    }

    try:
        session.execute(text("SELECT 1"))
        report["dependencies"]["postgres"] = {"reachable": True, "error": None}
    except Exception as failure:  # noqa: BLE001 - reported, not handled
        report["dependencies"]["postgres"] = {"reachable": False, "error": str(failure)}
        report["status"] = "degraded"

    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        client.ping()
        report["dependencies"]["redis"] = {"reachable": True, "error": None}
    except Exception as failure:  # noqa: BLE001
        report["dependencies"]["redis"] = {"reachable": False, "error": str(failure)}
        report["status"] = "degraded"

    return report


@router.get("/profile")
def cluster_profile() -> dict[str, Any]:
    """The configured cluster profile.

    The UI shows these values next to results so that a figure such as "11 map
    tasks" can be explained by the block size that produced it.
    """
    return {
        "hadoop": {
            "namenode": settings.namenode_ui,
            "resourcemanager": settings.rm_ui,
            "jobhistory": settings.history_ui,
        },
        "hdfs": {
            "replication": settings.hdfs_replication,
            "block_size": settings.hdfs_block_size,
            "root": settings.hdfs_root,
        },
        "yarn": {
            "nodemanager_memory_mb": settings.nm_memory_mb,
            "nodemanager_vcores": settings.nm_vcores,
            "map_container_mb": settings.map_memory_mb,
            "reduce_container_mb": settings.reduce_memory_mb,
            "application_master_mb": settings.am_memory_mb,
        },
        "mapreduce": {
            "default_reducers": settings.default_reducers,
            "split_maxsize": settings.split_maxsize or None,
            "jar": settings.mr_jar,
        },
        "limits": {
            "max_upload_mb": settings.max_upload_mb,
            "default_result_limit": settings.default_result_limit,
            "max_result_limit": settings.max_result_limit,
        },
        "topology_note": (
            "One NameNode, three DataNodes, one ResourceManager, three NodeManagers and "
            "one JobHistoryServer, each an independent container with its own storage "
            "and its own YARN resource budget, all running on a single physical machine."
        ),
    }
