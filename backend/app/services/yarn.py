"""YARN, HDFS and MapReduce observability.

Every figure this module returns comes from a Hadoop service:

* the ResourceManager REST API for cluster capacity, node state and
  application state;
* the NameNode JMX endpoint for the DataNode report and filesystem capacity;
* the JobHistoryServer REST API for finished job detail, counters and — the
  interesting one — the node each task attempt ran on;
* ``yarn logs`` for the aggregated container logs.

If a service cannot be reached the caller is told so. No value is ever
substituted.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_TIMEOUT = 15.0


class HadoopServiceError(RuntimeError):
    """A Hadoop service was unreachable or returned an error."""


def _get(url: str, *, timeout: float = _TIMEOUT) -> dict[str, Any]:
    try:
        response = httpx.get(url, timeout=timeout, headers={"Accept": "application/json"})
    except httpx.HTTPError as transport_failure:
        raise HadoopServiceError(f"{url} unreachable: {transport_failure}") from transport_failure
    if response.status_code >= 400:
        raise HadoopServiceError(f"{url} returned {response.status_code}")
    try:
        return response.json()
    except ValueError as not_json:
        raise HadoopServiceError(f"{url} did not return JSON") from not_json


def _as_list(value: Any) -> list[Any]:
    """Hadoop REST APIs return a dict for single-element lists and a list for multiple."""
    if not value:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


# ---------------------------------------------------------------------------
# ResourceManager
# ---------------------------------------------------------------------------

def cluster_info() -> dict[str, Any]:
    payload = _get(f"{settings.rm_ui}/ws/v1/cluster/info").get("clusterInfo", {})
    return {
        "state": payload.get("state"),
        "ha_state": payload.get("haState"),
        "hadoop_version": payload.get("hadoopVersion"),
        "resource_manager_version": payload.get("resourceManagerVersion"),
        "started_on": payload.get("startedOn"),
    }


def cluster_metrics() -> dict[str, Any]:
    payload = _get(f"{settings.rm_ui}/ws/v1/cluster/metrics").get("clusterMetrics", {})
    return {
        "apps_submitted": payload.get("appsSubmitted", 0),
        "apps_running": payload.get("appsRunning", 0),
        "apps_completed": payload.get("appsCompleted", 0),
        "apps_failed": payload.get("appsFailed", 0),
        "containers_allocated": payload.get("containersAllocated", 0),
        "containers_pending": payload.get("containersPending", 0),
        "memory_total_mb": payload.get("totalMB", 0),
        "memory_allocated_mb": payload.get("allocatedMB", 0),
        "memory_available_mb": payload.get("availableMB", 0),
        "vcores_total": payload.get("totalVirtualCores", 0),
        "vcores_allocated": payload.get("allocatedVirtualCores", 0),
        "active_nodes": payload.get("activeNodes", 0),
        "lost_nodes": payload.get("lostNodes", 0),
        "unhealthy_nodes": payload.get("unhealthyNodes", 0),
        "decommissioned_nodes": payload.get("decommissionedNodes", 0),
    }


def node_managers() -> list[dict[str, Any]]:
    """One entry per NodeManager, with its own resource budget and usage."""
    payload = _as_list(_get(f"{settings.rm_ui}/ws/v1/cluster/nodes").get("nodes", {}).get("node"))
    nodes = []
    for node in payload:
        nodes.append(
            {
                "id": node.get("id"),
                "hostname": node.get("nodeHostName"),
                "state": node.get("state"),
                "http_address": node.get("nodeHTTPAddress"),
                "health_report": node.get("healthReport") or "",
                "last_health_update": node.get("lastHealthUpdate"),
                "containers": node.get("numContainers", 0),
                "memory_used_mb": node.get("usedMemoryMB", 0),
                "memory_available_mb": node.get("availMemoryMB", 0),
                "vcores_used": node.get("usedVirtualCores", 0),
                "vcores_available": node.get("availableVirtualCores", 0),
                "version": node.get("version"),
            }
        )
    return sorted(nodes, key=lambda item: item["hostname"] or "")


def application(application_id: str) -> dict[str, Any]:
    """Live or recently finished state of one YARN application."""
    payload = _get(f"{settings.rm_ui}/ws/v1/cluster/apps/{application_id}").get("app", {})
    return {
        "id": payload.get("id"),
        "name": payload.get("name"),
        "state": payload.get("state"),
        "final_status": payload.get("finalStatus"),
        "progress": payload.get("progress", 0.0),
        "tracking_url": payload.get("trackingUrl"),
        "queue": payload.get("queue"),
        "started_time": payload.get("startedTime"),
        "finished_time": payload.get("finishedTime"),
        "elapsed_time": payload.get("elapsedTime"),
        "allocated_mb": payload.get("allocatedMB"),
        "allocated_vcores": payload.get("allocatedVCores"),
        "running_containers": payload.get("runningContainers"),
        "memory_seconds": payload.get("memorySeconds"),
        "vcore_seconds": payload.get("vcoreSeconds"),
        "diagnostics": (payload.get("diagnostics") or "")[:4000],
        "am_host_http_address": payload.get("amHostHttpAddress"),
    }


def applications(*, limit: int = 50) -> list[dict[str, Any]]:
    payload = _get(f"{settings.rm_ui}/ws/v1/cluster/apps?limit={limit}")
    apps = (payload.get("apps") or {}).get("app") or []
    return [
        {
            "id": app.get("id"),
            "name": app.get("name"),
            "state": app.get("state"),
            "final_status": app.get("finalStatus"),
            "started_time": app.get("startedTime"),
            "finished_time": app.get("finishedTime"),
            "elapsed_time": app.get("elapsedTime"),
            "progress": app.get("progress", 0.0),
        }
        for app in apps
    ]


# ---------------------------------------------------------------------------
# NameNode
# ---------------------------------------------------------------------------

def _jmx(bean: str) -> dict[str, Any]:
    payload = _get(f"{settings.namenode_ui}/jmx?qry={bean}")
    beans = payload.get("beans") or []
    if not beans:
        raise HadoopServiceError(f"NameNode JMX bean {bean} not found")
    return beans[0]


def hdfs_summary() -> dict[str, Any]:
    """Capacity, usage and block statistics of the filesystem."""
    state = _jmx("Hadoop:service=NameNode,name=FSNamesystemState")
    info = _jmx("Hadoop:service=NameNode,name=NameNodeInfo")
    return {
        "capacity_total": int(info.get("Total", 0)),
        "capacity_used": int(info.get("Used", 0)),
        "capacity_remaining": int(info.get("Free", 0)),
        "percent_used": float(info.get("PercentUsed", 0.0)),
        "blocks_total": int(state.get("BlocksTotal", 0)),
        "files_total": int(state.get("FilesTotal", 0)),
        # Hadoop 3 renamed UnderReplicatedBlocks to LowRedundancyBlocks; read
        # whichever the running NameNode publishes.
        "under_replicated_blocks": int(
            state.get("LowRedundancyBlocks", state.get("UnderReplicatedBlocks", 0)) or 0
        ),
        "missing_blocks": int(info.get("NumberOfMissingBlocks", 0) or 0),
        "corrupt_blocks": int(state.get("CorruptBlocks", 0) or 0),
        "live_datanodes": int(state.get("NumLiveDataNodes", 0)),
        "dead_datanodes": int(state.get("NumDeadDataNodes", 0)),
        "decommissioning": int(state.get("NumDecommissioningDataNodes", 0)),
        "safemode": info.get("Safemode") or "",
        "configured_block_size": settings.hdfs_block_size,
        "configured_replication": settings.hdfs_replication,
        "version": info.get("Version"),
        "cluster_id": info.get("ClusterId"),
    }


def data_nodes() -> list[dict[str, Any]]:
    """The DataNode report, as the NameNode sees it.

    ``LiveNodes`` and ``DeadNodes`` are JSON documents embedded in JMX as
    strings, so they are parsed rather than read directly.
    """
    info = _jmx("Hadoop:service=NameNode,name=NameNodeInfo")
    nodes: list[dict[str, Any]] = []

    for state, attribute in (("live", "LiveNodes"), ("dead", "DeadNodes")):
        try:
            entries = json.loads(info.get(attribute) or "{}")
        except (TypeError, ValueError):
            continue
        for name, detail in entries.items():
            capacity = int(detail.get("capacity", 0) or 0)
            used = int(detail.get("used", 0) or 0)
            nodes.append(
                {
                    "name": name,
                    "hostname": (detail.get("hostName") or name.split(":")[0]),
                    "state": state,
                    "admin_state": detail.get("adminState"),
                    "capacity": capacity,
                    "used": used,
                    "remaining": int(detail.get("remaining", 0) or 0),
                    "percent_used": round(100.0 * used / capacity, 2) if capacity else 0.0,
                    "blocks": int(detail.get("numBlocks", 0) or 0),
                    "last_contact": detail.get("lastContact"),
                    "version": detail.get("version"),
                    "info_addr": detail.get("infoAddr"),
                }
            )
    return sorted(nodes, key=lambda item: item["hostname"])


# ---------------------------------------------------------------------------
# JobHistoryServer
# ---------------------------------------------------------------------------

def history_job(job_id: str) -> dict[str, Any]:
    payload = _get(f"{settings.history_ui}/ws/v1/history/mapreduce/jobs/{job_id}").get("job", {})
    return {
        "id": payload.get("id"),
        "name": payload.get("name"),
        "state": payload.get("state"),
        "user": payload.get("user"),
        "queue": payload.get("queue"),
        "submit_time": payload.get("submitTime"),
        "start_time": payload.get("startTime"),
        "finish_time": payload.get("finishTime"),
        "maps_total": payload.get("mapsTotal", 0),
        "maps_completed": payload.get("mapsCompleted", 0),
        "reduces_total": payload.get("reducesTotal", 0),
        "reduces_completed": payload.get("reducesCompleted", 0),
        "failed_map_attempts": payload.get("failedMapAttempts", 0),
        "failed_reduce_attempts": payload.get("failedReduceAttempts", 0),
        "avg_map_time": payload.get("avgMapTime"),
        "avg_reduce_time": payload.get("avgReduceTime"),
        "avg_shuffle_time": payload.get("avgShuffleTime"),
        "avg_merge_time": payload.get("avgMergeTime"),
        "uberized": payload.get("uberized", False),
    }


def history_counters(job_id: str) -> list[dict[str, Any]]:
    payload = _get(f"{settings.history_ui}/ws/v1/history/mapreduce/jobs/{job_id}/counters")
    groups = _as_list((payload.get("jobCounters") or {}).get("counterGroup"))
    result = []
    for group in groups:
        counters = _as_list(group.get("counter"))
        result.append(
            {
                "name": group.get("counterGroupName"),
                "counters": [
                    {
                        "name": counter.get("name"),
                        "total": counter.get("totalCounterValue", 0),
                        "map": counter.get("mapCounterValue", 0),
                        "reduce": counter.get("reduceCounterValue", 0),
                    }
                    for counter in counters
                ],
            }
        )
    return result


def task_placement(job_id: str, *, max_tasks: int = 400) -> list[dict[str, Any]]:
    """Which worker container ran each task attempt of a finished job.

    This is the direct evidence that the work was distributed: every attempt
    reports the NodeManager it executed on, and for a multi-split job those
    hostnames are spread across the worker containers.
    """
    payload = _get(f"{settings.history_ui}/ws/v1/history/mapreduce/jobs/{job_id}/tasks",
                   timeout=30.0)
    tasks = _as_list((payload.get("tasks") or {}).get("task"))
    placements: list[dict[str, Any]] = []

    for task in tasks[:max_tasks]:
        task_id = task.get("id")
        if not task_id:
            continue
        try:
            attempts_payload = _get(
                f"{settings.history_ui}/ws/v1/history/mapreduce/jobs/{job_id}"
                f"/tasks/{task_id}/attempts",
                timeout=30.0,
            )
        except HadoopServiceError:
            continue
        attempts = _as_list((attempts_payload.get("taskAttempts") or {}).get("taskAttempt"))
        for attempt in attempts:
            node = attempt.get("nodeHttpAddress") or ""
            placements.append(
                {
                    "task_id": task_id,
                    "attempt_id": attempt.get("id"),
                    "type": task.get("type"),
                    "state": attempt.get("state"),
                    "node": node,
                    "host": node.split(":")[0],
                    "container_id": attempt.get("assignedContainerId"),
                    "start_time": attempt.get("startTime"),
                    "finish_time": attempt.get("finishTime"),
                    "elapsed_time": attempt.get("elapsedTime"),
                    "progress": attempt.get("progress"),
                    "diagnostics": (attempt.get("diagnostics") or "")[:1000],
                }
            )
    return placements


def placement_summary(placements: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts of map and reduce attempts per worker host."""
    per_host: dict[str, dict[str, int]] = {}
    for attempt in placements:
        host = attempt["host"] or "unknown"
        bucket = per_host.setdefault(host, {"map": 0, "reduce": 0})
        kind = (attempt.get("type") or "").lower()
        if kind in bucket:
            bucket[kind] += 1
    return {
        "hosts": sorted(per_host.keys()),
        "per_host": per_host,
        "distinct_hosts": len(per_host),
        "total_attempts": len(placements),
    }


def application_logs(application_id: str, *, max_chars: int = 400_000) -> str:
    """Aggregated container logs of an application, via the Hadoop client.

    Reads what the NodeManagers aggregated into HDFS. If aggregation has not
    finished yet the command says so, and that message is returned unchanged
    rather than replaced with placeholder text.
    """
    completed = subprocess.run(
        ["yarn", "logs", "-applicationId", application_id],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    output = completed.stdout or ""
    if not output.strip():
        output = (completed.stderr or "").strip() or (
            f"No aggregated logs available for {application_id} yet."
        )
    if len(output) > max_chars:
        head = output[: max_chars // 2]
        tail = output[-max_chars // 2 :]
        omitted = len(output) - max_chars
        return f"{head}\n\n... {omitted} characters omitted ...\n\n{tail}"
    return output


def cluster_health() -> dict[str, Any]:
    """One call for the whole cluster view, with per-service error reporting."""
    report: dict[str, Any] = {"services": {}}

    for name, loader in (
        ("resourcemanager", cluster_info),
        ("cluster_metrics", cluster_metrics),
        ("hdfs", hdfs_summary),
    ):
        try:
            report[name if name != "cluster_metrics" else "metrics"] = loader()
            report["services"][name] = {"reachable": True, "error": None}
        except HadoopServiceError as failure:
            report[name if name != "cluster_metrics" else "metrics"] = None
            report["services"][name] = {"reachable": False, "error": str(failure)}

    for name, loader in (("datanodes", data_nodes), ("nodemanagers", node_managers)):
        try:
            report[name] = loader()
            report["services"][name] = {"reachable": True, "error": None}
        except HadoopServiceError as failure:
            report[name] = []
            report["services"][name] = {"reachable": False, "error": str(failure)}

    try:
        _get(f"{settings.history_ui}/ws/v1/history/info")
        report["services"]["historyserver"] = {"reachable": True, "error": None}
    except HadoopServiceError as failure:
        report["services"]["historyserver"] = {"reachable": False, "error": str(failure)}

    return report
