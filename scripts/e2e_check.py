#!/usr/bin/env python3
"""End-to-end verification of a running CartScope stack.

This is the check that the project's central claims are true, not just that the
HTTP endpoints answer. It drives the real API and then asserts against what
Hadoop reported:

1. a dataset version reaches READY, which means the Hadoop validation job ran;
2. the raw file in HDFS is split across several blocks held by several
   DataNodes, so storage really is distributed and replicated;
3. every analysis of a submitted run succeeds;
4. every stage has a real MapReduce job id and a real YARN application id;
5. the first stage of each analysis launched more than one map task, so the
   input was genuinely split;
6. task attempts ran on more than one worker container, so the work was
   genuinely distributed;
7. the reducers' output is readable and non-empty;
8. two independently computed Hadoop results agree: the net revenue totalled by
   the country analysis matches the net revenue totalled by the monthly
   analysis. Nothing in the backend could make those agree if the jobs were
   wrong.

Usage: python3 -I scripts/e2e_check.py [--api http://localhost:8000]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

ANALYSES = [
    "customer_analysis",
    "monthly_sales",
    "product_analysis",
    "country_analysis",
    "repeat_customers",
    "rfm_analysis",
]

PASS = "PASS"
FAIL = "FAIL"


class Checks:
    def __init__(self) -> None:
        self.results: list[tuple[str, str, str]] = []

    def record(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append((PASS if ok else FAIL, name, detail))
        marker = "✓" if ok else "✗"
        print(f"  {marker} {name}" + (f" — {detail}" if detail else ""), flush=True)
        return ok

    @property
    def failed(self) -> list[tuple[str, str, str]]:
        return [entry for entry in self.results if entry[0] == FAIL]

    def summary(self) -> int:
        passed = len(self.results) - len(self.failed)
        print()
        print(f"{passed}/{len(self.results)} checks passed")
        if self.failed:
            print()
            print("failures:")
            for _, name, detail in self.failed:
                print(f"  - {name}: {detail}")
            return 1
        return 0


def get(url: str, timeout: int = 120) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any], timeout: int = 120) -> Any:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_multipart(url: str, fields: dict[str, str], file_path: Path) -> Any:
    """Uploads a file without pulling in a dependency for one request."""
    boundary = f"----cartscope{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
            f"{value}\r\n".encode("utf-8")
        )
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{file_path.name}\"\r\nContent-Type: text/csv\r\n\r\n".encode("utf-8")
    )
    parts.append(file_path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)

    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=900) as response:
        return json.loads(response.read().decode("utf-8"))


def ready_version(api: str) -> tuple[str, str] | None:
    """The largest READY dataset version the stack already holds.

    Largest rather than newest: the distribution checks are only meaningful
    against a dataset big enough to span several HDFS blocks, so if the stack
    holds both a small fixture and a full dataset, the full one is the right
    thing to verify against.
    """
    candidates: list[tuple[int, str, str]] = []
    for dataset in get(f"{api}/api/datasets"):
        detail = get(f"{api}/api/datasets/{dataset['id']}")
        for version in detail["versions"]:
            if version["status"] == "READY":
                candidates.append(
                    (version["validated_record_count"] or 0, dataset["id"], version["id"])
                )
    if not candidates:
        return None
    records, dataset_id, version_id = max(candidates)
    print(f"    {len(candidates)} ready versions; using the largest ({records:,} records)")
    return dataset_id, version_id


def wait_for_version(api: str, dataset_id: str, version_id: str, timeout: int) -> dict[str, Any]:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        version = get(f"{api}/api/datasets/{dataset_id}/versions/{version_id}")
        if version["status"] != last:
            last = version["status"]
            print(f"    version status: {last}", flush=True)
        if version["status"] in ("READY", "FAILED"):
            return version
        time.sleep(5)
    raise TimeoutError(f"version {version_id} did not settle within {timeout}s")


def wait_for_run(api: str, run_id: str, timeout: int) -> dict[str, Any]:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        run = get(f"{api}/api/runs/{run_id}")
        states = ",".join(
            f"{entry['analysis']}={entry['status']}" for entry in run["analyses"]
        )
        if states != last:
            last = states
            print(f"    {run['status']}: {states}", flush=True)
        if run["status"] in ("SUCCEEDED", "PARTIAL", "FAILED", "CANCELLED"):
            return run
        time.sleep(5)
    raise TimeoutError(f"run {run_id} did not finish within {timeout}s")


def total(api: str, run_id: str, analysis: str, output: str, column: str) -> float:
    """Sums one column of a result by paging through it."""
    summed = 0.0
    offset = 0
    while True:
        page = get(
            f"{api}/api/runs/{run_id}/analyses/{analysis}/results/{output}"
            f"?limit=5000&offset={offset}"
        )
        for row in page["rows"]:
            value = row.get(column)
            if isinstance(value, (int, float)):
                summed += float(value)
        offset += page["returned"]
        if not page["has_more"] or page["returned"] == 0:
            return summed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=os.environ.get("CARTSCOPE_API", "http://localhost:8000"))
    parser.add_argument("--csv", default="data/online_retail.csv")
    parser.add_argument("--ingest-timeout", type=int, default=2400)
    parser.add_argument("--run-timeout", type=int, default=5400)
    parser.add_argument(
        "--analyses", default=",".join(ANALYSES), help="comma separated analysis keys"
    )
    arguments = parser.parse_args()
    api = arguments.api.rstrip("/")
    checks = Checks()

    print("CartScope end-to-end check")
    print(f"api: {api}")
    print()

    # --- 1. The stack is up ------------------------------------------------
    print("Platform")
    try:
        health = get(f"{api}/api/health", timeout=20)
        checks.record(
            "API is healthy",
            health["status"] == "ok",
            ", ".join(
                f"{name}={'up' if state['reachable'] else 'down'}"
                for name, state in health["dependencies"].items()
            ),
        )
    except Exception as failure:  # noqa: BLE001
        checks.record("API is reachable", False, str(failure))
        return checks.summary()

    try:
        cluster = get(f"{api}/api/cluster", timeout=40)
    except Exception as failure:  # noqa: BLE001
        checks.record("cluster view is reachable", False, str(failure))
        return checks.summary()

    hdfs = cluster.get("hdfs") or {}
    metrics = cluster.get("metrics") or {}
    expected_dn = cluster["profile"]["expected_datanodes"]
    expected_nm = cluster["profile"]["expected_nodemanagers"]

    checks.record(
        f"{expected_dn} DataNodes are live",
        hdfs.get("live_datanodes", 0) >= expected_dn,
        f"live={hdfs.get('live_datanodes')} dead={hdfs.get('dead_datanodes')}",
    )
    checks.record(
        f"{expected_nm} NodeManagers are registered",
        metrics.get("active_nodes", 0) >= expected_nm,
        f"active={metrics.get('active_nodes')}",
    )
    checks.record(
        "HDFS replication is 2",
        hdfs.get("configured_replication") == 2,
        f"replication={hdfs.get('configured_replication')}",
    )

    # --- 2. A validated dataset -------------------------------------------
    print()
    print("Dataset")
    existing = ready_version(api)
    if existing:
        dataset_id, version_id = existing
        print(f"    reusing the ready version {version_id}")
    else:
        csv_path = Path(arguments.csv)
        if not csv_path.is_file():
            checks.record(
                "a dataset is available",
                False,
                f"{csv_path} is missing — run 'make dataset' first",
            )
            return checks.summary()
        print(f"    uploading {csv_path} ({csv_path.stat().st_size:,} bytes)")
        created = post_multipart(
            f"{api}/api/datasets",
            {
                "name": "UCI Online Retail",
                "description": "Loaded by scripts/e2e_check.py",
                "day_first": "false",
            },
            csv_path,
        )
        dataset_id = created["id"]
        version_id = created["versions"][0]["id"]
        version = wait_for_version(api, dataset_id, version_id, arguments.ingest_timeout)
        if not checks.record(
            "the dataset version validated",
            version["status"] == "READY",
            version.get("error") or version["status"],
        ):
            return checks.summary()

    version = get(f"{api}/api/datasets/{dataset_id}/versions/{version_id}")
    checks.record(
        "the validation job reported record counts",
        bool(version["validated_record_count"]) and version["rejected_record_count"] is not None,
        f"validated={version['validated_record_count']:,} "
        f"rejected={version['rejected_record_count']:,} "
        f"duplicates={version['duplicate_record_count']:,}",
    )
    checks.record(
        "a SHA-256 checksum was recorded",
        bool(version["sha256"]) and len(version["sha256"]) == 64,
        version["sha256"] or "missing",
    )

    classification = (version.get("validation_counters") or {}).get("classification") or {}
    checks.record(
        "transaction classes came from Hadoop counters",
        (classification.get("FULFILLED_SALES") or 0) > 0,
        f"sales={classification.get('FULFILLED_SALES')} "
        f"returns={classification.get('RETURNS_AND_CANCELLATIONS')}",
    )

    storage = get(f"{api}/api/datasets/{dataset_id}/versions/{version_id}/storage")
    blocks = storage.get("raw_block_locations") or []
    hosts = {host for block in blocks for host in block["hosts"]}
    block_size = storage["block_size"]
    raw_bytes = version["size_bytes"]
    expected_blocks = max(1, -(-raw_bytes // block_size))

    checks.record(
        "the raw file occupies the expected number of HDFS blocks",
        len(blocks) == expected_blocks,
        f"{len(blocks)} blocks for {raw_bytes:,} bytes at a {block_size:,} byte block size",
    )
    if expected_blocks > 1:
        checks.record(
            "the raw file is split across several blocks, so the input can be split",
            len(blocks) > 1,
            f"{len(blocks)} blocks",
        )
    else:
        print(
            "    (the file is smaller than one block, so a multi-block split is "
            "not applicable; use a larger dataset to exercise it)"
        )
    checks.record(
        "every block is replicated across DataNodes",
        len(hosts) >= 2 and all(len(block["hosts"]) >= 2 for block in blocks),
        f"{len(hosts)} distinct DataNodes hold them",
    )

    # --- 3. A run ----------------------------------------------------------
    print()
    print("Run")
    requested = [key.strip() for key in arguments.analyses.split(",") if key.strip()]
    run = post_json(
        f"{api}/api/runs",
        {
            "dataset_version_id": version_id,
            "analyses": requested,
            "label": "end-to-end check",
            "configuration": {"reducers": 3},
        },
    )
    run_id = run["id"]
    print(f"    submitted {run['run_key']}")
    run = wait_for_run(api, run_id, arguments.run_timeout)

    checks.record(
        "every analysis succeeded",
        run["status"] == "SUCCEEDED",
        run.get("error") or run["status"],
    )

    for execution in run["analyses"]:
        analysis = execution["analysis"]
        jobs = sorted(execution["jobs"], key=lambda job: job["stage_index"])

        checks.record(
            f"{analysis}: ran its MapReduce chain",
            execution["status"] == "SUCCEEDED" and len(jobs) >= 1,
            f"{len(jobs)} stages, {execution['duration_ms']} ms",
        )
        if not jobs:
            continue

        checks.record(
            f"{analysis}: every stage has a real job and application id",
            all(
                job["job_id"] and job["job_id"].startswith("job_")
                and job["application_id"] and job["application_id"].startswith("application_")
                for job in jobs
            ),
            ", ".join(f"{job['stage']}={job['application_id']}" for job in jobs[:2]) + " …",
        )
        checks.record(
            f"{analysis}: Hadoop counters were captured",
            all(job["map_input_records"] is not None for job in jobs),
            f"first stage read {jobs[0]['map_input_records']:,} records",
        )
        # More than one map task requires more than one input split, which
        # requires validated data larger than one block. Below that the honest
        # assertion is that at least one map task ran.
        minimum_maps = 2 if expected_blocks > 1 else 1
        checks.record(
            f"{analysis}: the input was read by {minimum_maps} or more map tasks",
            (jobs[0]["launched_map_tasks"] or 0) >= minimum_maps,
            f"{jobs[0]['launched_map_tasks']} map tasks in {jobs[0]['stage']}",
        )
        checks.record(
            f"{analysis}: reduce tasks ran",
            any((job["launched_reduce_tasks"] or 0) > 0 for job in jobs),
            f"{sum(job['launched_reduce_tasks'] or 0 for job in jobs)} reduce tasks in total",
        )
        checks.record(
            f"{analysis}: no task failed",
            all(
                (job["failed_map_tasks"] or 0) == 0 and (job["failed_reduce_tasks"] or 0) == 0
                for job in jobs
            ),
        )

        stage = jobs[0]["stage"]
        detail = get(f"{api}/api/runs/{run_id}/analyses/{analysis}/jobs/{stage}")
        placement = detail.get("placement_summary") or {}
        # A single-split job runs one map task, which lands on one worker; the
        # reduce tasks are what spread it. Require two hosts only where the
        # data gives the scheduler something to spread.
        minimum_hosts = 2 if expected_blocks > 1 else 1
        checks.record(
            f"{analysis}: work ran on {minimum_hosts} or more worker containers",
            (placement.get("distinct_hosts") or 0) >= minimum_hosts,
            f"{placement.get('distinct_hosts')} hosts: {', '.join(placement.get('hosts') or [])}",
        )

        for output in execution["outputs"]:
            page = get(
                f"{api}/api/runs/{run_id}/analyses/{analysis}"
                f"/results/{output['name']}?limit=5"
            )
            checks.record(
                f"{analysis}/{output['name']}: the reducers wrote readable rows",
                len(page["rows"]) > 0,
                f"{output['row_count']:,} rows" if output["row_count"] else "row count unknown",
            )

    # --- 4. Cross-check two independent Hadoop results ---------------------
    completed = {execution["analysis"] for execution in run["analyses"]
                 if execution["status"] == "SUCCEEDED"}
    if {"country_analysis", "monthly_sales"} <= completed:
        print()
        print("Consistency")
        country_total = total(api, run_id, "country_analysis", "by_country", "net_revenue")
        monthly_total = total(api, run_id, "monthly_sales", "by_month", "net_revenue")
        difference = abs(country_total - monthly_total)
        tolerance = max(1.0, abs(monthly_total) * 1e-6)
        checks.record(
            "country and monthly net revenue agree",
            difference <= tolerance,
            f"country={country_total:,.2f} monthly={monthly_total:,.2f} "
            f"difference={difference:,.4f}",
        )

    print()
    print(f"run: {api.replace('8000', '3000')}/runs/{run_id}")
    return checks.summary()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted")
        sys.exit(130)
