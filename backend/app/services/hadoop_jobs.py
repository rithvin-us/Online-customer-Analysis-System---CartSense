"""MapReduce job submission.

The Celery worker runs inside a container that holds a real Hadoop client and
the compiled job jar, so submitting work means exactly what it would mean on a
production cluster:

    hadoop jar cartscope-mapreduce.jar <analysis> -D ... --input ... --output ...

The backend's job is to build that command, stream its output to a log file,
and read back the report the Java driver wrote. It does not compute any
analytical figure, and it does not invent any execution metric: the counters
stored in PostgreSQL are the ones the driver read out of the finished job.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

# Counter group names, as Hadoop publishes them.
GROUP_TASK = "org.apache.hadoop.mapreduce.TaskCounter"
GROUP_JOB = "org.apache.hadoop.mapreduce.JobCounter"
GROUP_FILESYSTEM = "org.apache.hadoop.mapreduce.FileSystemCounter"
#: MultipleOutputs reports one counter per named output when counters are
#: enabled, which the validation job does.
GROUP_MULTIPLE_OUTPUTS = "org.apache.hadoop.mapreduce.lib.output.MultipleOutputs"
#: Counter groups are named after the declaring enum class, so a nested enum
#: appears with a dollar sign.
GROUP_VALIDATION_STAT = "com.cartscope.jobs.ValidationJob$Stat"


class JobSubmissionError(RuntimeError):
    def __init__(self, message: str, *, log_path: str | None = None, output: str = ""):
        super().__init__(message)
        self.log_path = log_path
        self.output = output


@dataclass(slots=True)
class JobRunResult:
    """Outcome of one `hadoop jar` invocation."""

    analysis: str
    command: list[str]
    exit_code: int
    duration_ms: int
    log_path: str
    report: dict[str, Any] | None
    output_tail: str
    succeeded: bool = field(init=False)

    def __post_init__(self) -> None:
        self.succeeded = self.exit_code == 0 and bool(self.report) and bool(
            self.report.get("succeeded")
        )

    @property
    def stages(self) -> list[dict[str, Any]]:
        return list((self.report or {}).get("stages") or [])

    @property
    def outputs(self) -> dict[str, str]:
        return dict((self.report or {}).get("outputs") or {})


def build_command(
    analysis: str,
    *,
    inputs: list[str],
    work_dir: str,
    result_dir: str,
    run_key: str,
    report_path: str,
    manifest_path: str,
    overrides: dict[str, Any] | None = None,
) -> list[str]:
    """Assembles the Hadoop command line.

    Configuration overrides are passed as ``-D`` options, which is how the
    standard Hadoop tooling expects them, so the same command can be copied
    out of the UI and pasted into a terminal to reproduce a run by hand.
    """
    command = ["hadoop", "jar", settings.mr_jar, analysis]
    for key, value in (overrides or {}).items():
        if value is None:
            continue
        command += ["-D", f"{key}={value}"]
    for path in inputs:
        command += ["--input", path]
    command += [
        "--work", work_dir,
        "--output", result_dir,
        "--run-id", run_key,
        "--report", report_path,
        "--manifest", manifest_path,
    ]
    return command


def submit(
    analysis: str,
    *,
    inputs: list[str],
    work_dir: str,
    result_dir: str,
    run_key: str,
    log_path: str | Path,
    manifest_path: str,
    overrides: dict[str, Any] | None = None,
    timeout: int | None = None,
) -> JobRunResult:
    """Runs one analysis to completion and returns what Hadoop reported."""
    log_file = Path(log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    report_path = str(log_file.with_suffix(".report.json"))

    command = build_command(
        analysis,
        inputs=inputs,
        work_dir=work_dir,
        result_dir=result_dir,
        run_key=run_key,
        report_path=report_path,
        manifest_path=manifest_path,
        overrides=overrides,
    )

    log.info("submitting %s: %s", analysis, " ".join(command))
    started = time.monotonic()
    tail: deque[str] = deque(maxlen=200)

    environment = os.environ.copy()
    environment.setdefault("HADOOP_USER_NAME", settings.hadoop_user_name)
    # Keep the client's own heap small: it only orchestrates, the work happens
    # in YARN containers.
    environment.setdefault("HADOOP_CLIENT_OPTS", "-Xmx512m")

    with log_file.open("w", encoding="utf-8") as handle:
        handle.write(f"$ {' '.join(command)}\n\n")
        handle.flush()
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=environment,
        )
        assert process.stdout is not None
        try:
            for line in process.stdout:
                handle.write(line)
                tail.append(line.rstrip("\n"))
                # Flushing per line is what makes the UI's log view follow a
                # running job instead of showing nothing until it ends.
                handle.flush()
            exit_code = process.wait(timeout=timeout or settings.job_timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            handle.write("\n[cartscope] job killed: exceeded the configured timeout\n")
            exit_code = 124

    duration_ms = int((time.monotonic() - started) * 1000)
    report = _read_report(report_path)

    result = JobRunResult(
        analysis=analysis,
        command=command,
        exit_code=exit_code,
        duration_ms=duration_ms,
        log_path=str(log_file),
        report=report,
        output_tail="\n".join(tail),
    )
    log.info(
        "%s finished: exit=%s succeeded=%s stages=%d duration=%dms",
        analysis, exit_code, result.succeeded, len(result.stages), duration_ms,
    )
    return result


def _read_report(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        log.warning("job report missing at %s", path)
        return None
    except json.JSONDecodeError as malformed:
        log.warning("job report at %s is not valid JSON: %s", path, malformed)
        return None


# ---------------------------------------------------------------------------
# Counter helpers
# ---------------------------------------------------------------------------

def flatten_counters(stage: dict[str, Any]) -> dict[str, dict[str, int]]:
    """``{group name: {counter name: value}}`` for one reported stage."""
    flattened: dict[str, dict[str, int]] = {}
    for group in stage.get("counterGroups") or []:
        name = group.get("name") or group.get("displayName") or "unknown"
        flattened[name] = {
            counter.get("name") or "": int(counter.get("value") or 0)
            for counter in group.get("counters") or []
        }
    return flattened


def counter(counters: dict[str, dict[str, int]], group: str, name: str) -> int | None:
    """One counter value, or None when Hadoop did not report it."""
    return counters.get(group, {}).get(name)


def headline_counters(counters: dict[str, dict[str, int]]) -> dict[str, int | None]:
    """The counters the product reports for every stage.

    Returning ``None`` for an absent counter is deliberate: a map-only job has
    no reduce counters, and showing a blank is honest where showing 0 would
    not be.
    """
    return {
        "map_input_records": counter(counters, GROUP_TASK, "MAP_INPUT_RECORDS"),
        "map_output_records": counter(counters, GROUP_TASK, "MAP_OUTPUT_RECORDS"),
        "map_output_bytes": counter(counters, GROUP_TASK, "MAP_OUTPUT_BYTES"),
        "combine_input_records": counter(counters, GROUP_TASK, "COMBINE_INPUT_RECORDS"),
        "combine_output_records": counter(counters, GROUP_TASK, "COMBINE_OUTPUT_RECORDS"),
        "reduce_input_groups": counter(counters, GROUP_TASK, "REDUCE_INPUT_GROUPS"),
        "reduce_input_records": counter(counters, GROUP_TASK, "REDUCE_INPUT_RECORDS"),
        "reduce_output_records": counter(counters, GROUP_TASK, "REDUCE_OUTPUT_RECORDS"),
        "reduce_shuffle_bytes": counter(counters, GROUP_TASK, "REDUCE_SHUFFLE_BYTES"),
        "spilled_records": counter(counters, GROUP_TASK, "SPILLED_RECORDS"),
        "launched_map_tasks": counter(counters, GROUP_JOB, "TOTAL_LAUNCHED_MAPS"),
        "launched_reduce_tasks": counter(counters, GROUP_JOB, "TOTAL_LAUNCHED_REDUCES"),
        "failed_map_tasks": counter(counters, GROUP_JOB, "NUM_FAILED_MAPS"),
        "failed_reduce_tasks": counter(counters, GROUP_JOB, "NUM_FAILED_REDUCES"),
        "data_local_map_tasks": counter(counters, GROUP_JOB, "DATA_LOCAL_MAPS"),
        "rack_local_map_tasks": counter(counters, GROUP_JOB, "RACK_LOCAL_MAPS"),
        "millis_maps": counter(counters, GROUP_JOB, "MILLIS_MAPS"),
        "millis_reduces": counter(counters, GROUP_JOB, "MILLIS_REDUCES"),
        "hdfs_bytes_read": counter(counters, GROUP_FILESYSTEM, "HDFS_BYTES_READ"),
        "hdfs_bytes_written": counter(counters, GROUP_FILESYSTEM, "HDFS_BYTES_WRITTEN"),
    }


def custom_counters(counters: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    """The job's own counters: the business rule tallies, not Hadoop's."""
    return {
        group: values
        for group, values in counters.items()
        if group.startswith("com.cartscope")
    }
