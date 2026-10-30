"""Building the Hadoop command line, and reading counters back out of a report.

The report is the contract between the Java drivers and this backend, so these
tests pin its shape, and pin the rule that a counter Hadoop did not report is
reported as absent rather than as zero.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services import hadoop_jobs


def test_command_puts_overrides_before_the_tool_arguments() -> None:
    command = hadoop_jobs.build_command(
        "customer_analysis",
        inputs=["/cartscope/datasets/d/versions/v/validated"],
        work_dir="/cartscope/jobs/run-1/customer_analysis",
        result_dir="/cartscope/results/run-1/customer_analysis",
        run_key="run-1",
        report_path="/var/lib/cartscope/joblogs/run-1/customer_analysis.report.json",
        manifest_path="/cartscope/manifests/run-1/customer_analysis.json",
        overrides={"cartscope.reducers": 3, "cartscope.split.maxsize": 1048576},
    )

    assert command[:4] == ["hadoop", "jar", "/opt/cartscope/cartscope-mapreduce.jar",
                           "customer_analysis"]
    # GenericOptionsParser reads -D from the front, so they must precede --input.
    assert command.index("-D") < command.index("--input")
    assert "cartscope.reducers=3" in command
    assert "cartscope.split.maxsize=1048576" in command
    assert command[-2:] == ["--manifest", "/cartscope/manifests/run-1/customer_analysis.json"]


def test_command_accepts_several_inputs() -> None:
    command = hadoop_jobs.build_command(
        "monthly_sales",
        inputs=["/a", "/b"],
        work_dir="/w",
        result_dir="/r",
        run_key="run-2",
        report_path="/tmp/report.json",
        manifest_path="/m.json",
    )
    assert command.count("--input") == 2


def test_command_skips_an_unset_override() -> None:
    command = hadoop_jobs.build_command(
        "monthly_sales",
        inputs=["/a"],
        work_dir="/w",
        result_dir="/r",
        run_key="run-3",
        report_path="/tmp/report.json",
        manifest_path="/m.json",
        overrides={"cartscope.reducers": 3, "cartscope.split.maxsize": None},
    )
    assert "cartscope.split.maxsize=None" not in command
    assert "-D" in command


STAGE = {
    "stage": "invoice-rollup",
    "jobId": "job_1730000000000_0003",
    "applicationId": "application_1730000000000_0003",
    "counterGroups": [
        {
            "name": hadoop_jobs.GROUP_TASK,
            "counters": [
                {"name": "MAP_INPUT_RECORDS", "value": 524909},
                {"name": "MAP_OUTPUT_RECORDS", "value": 397884},
                {"name": "REDUCE_INPUT_GROUPS", "value": 22190},
                {"name": "REDUCE_OUTPUT_RECORDS", "value": 22190},
            ],
        },
        {
            "name": hadoop_jobs.GROUP_JOB,
            "counters": [
                {"name": "TOTAL_LAUNCHED_MAPS", "value": 11},
                {"name": "TOTAL_LAUNCHED_REDUCES", "value": 3},
                {"name": "NUM_FAILED_MAPS", "value": 0},
            ],
        },
        {
            "name": "com.cartscope.jobs.CustomerSpendingJob$Stat",
            "counters": [
                {"name": "SKIPPED_MISSING_CUSTOMER_ID", "value": 132220},
                {"name": "INVOICES_ROLLED_UP", "value": 22190},
            ],
        },
    ],
}


def test_flatten_counters_groups_by_name() -> None:
    flattened = hadoop_jobs.flatten_counters(STAGE)

    assert flattened[hadoop_jobs.GROUP_TASK]["MAP_INPUT_RECORDS"] == 524909
    assert flattened[hadoop_jobs.GROUP_JOB]["TOTAL_LAUNCHED_MAPS"] == 11


def test_headline_counters_read_the_real_values() -> None:
    headline = hadoop_jobs.headline_counters(hadoop_jobs.flatten_counters(STAGE))

    assert headline["map_input_records"] == 524909
    assert headline["launched_map_tasks"] == 11
    assert headline["launched_reduce_tasks"] == 3
    assert headline["failed_map_tasks"] == 0


def test_an_unreported_counter_is_absent_not_zero() -> None:
    headline = hadoop_jobs.headline_counters(hadoop_jobs.flatten_counters(STAGE))

    # This stage reported no filesystem group, so the bytes are unknown. Zero
    # would be a claim; None is the truth.
    assert headline["hdfs_bytes_read"] is None
    assert headline["hdfs_bytes_written"] is None
    assert headline["failed_reduce_tasks"] is None


def test_custom_counters_are_separated_from_hadoops() -> None:
    custom = hadoop_jobs.custom_counters(hadoop_jobs.flatten_counters(STAGE))

    assert list(custom) == ["com.cartscope.jobs.CustomerSpendingJob$Stat"]
    assert custom["com.cartscope.jobs.CustomerSpendingJob$Stat"][
        "SKIPPED_MISSING_CUSTOMER_ID"
    ] == 132220


def test_a_run_result_is_successful_only_when_the_report_says_so() -> None:
    succeeded = hadoop_jobs.JobRunResult(
        analysis="monthly_sales",
        command=["hadoop"],
        exit_code=0,
        duration_ms=1000,
        log_path="/tmp/log",
        report={"succeeded": True, "stages": [STAGE], "outputs": {"by_month": "/r"}},
        output_tail="",
    )
    assert succeeded.succeeded
    assert succeeded.outputs == {"by_month": "/r"}
    assert len(succeeded.stages) == 1

    # A zero exit code with no report is not success: the driver did not report.
    no_report = hadoop_jobs.JobRunResult(
        analysis="monthly_sales",
        command=["hadoop"],
        exit_code=0,
        duration_ms=1000,
        log_path="/tmp/log",
        report=None,
        output_tail="",
    )
    assert not no_report.succeeded

    reported_failure = hadoop_jobs.JobRunResult(
        analysis="monthly_sales",
        command=["hadoop"],
        exit_code=0,
        duration_ms=1000,
        log_path="/tmp/log",
        report={"succeeded": False, "stages": []},
        output_tail="",
    )
    assert not reported_failure.succeeded


def test_a_malformed_report_is_treated_as_missing(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text("{not json", encoding="utf-8")
    assert hadoop_jobs._read_report(str(path)) is None

    good = tmp_path / "good.json"
    good.write_text(json.dumps({"succeeded": True, "stages": []}), encoding="utf-8")
    assert hadoop_jobs._read_report(str(good)) == {"succeeded": True, "stages": []}
