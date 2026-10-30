#!/usr/bin/env python3
"""Verify the MapReduce jobs against hand-computed answers.

This runs the real jobs on the real cluster over a tiny fixture whose every
figure can be worked out by hand, and compares Hadoop's output with those
figures. Where `e2e_check.py` proves the platform works end to end, this proves
the *arithmetic* is right: that an invoice is counted once, that a cancelled
negative-quantity line contributes to returns exactly once, that a record with
no CustomerID is excluded from customer analyses but kept in country ones, and
that the four analyses which total revenue by different keys all land on the
same number.

The fixture is deliberately small and awkward: it contains a quoted description
with a comma, an exact duplicate row, a cancellation, a negative quantity, a
zero price, a zero quantity, an unparseable date and a row with no customer.

Usage: python3 -I scripts/verify_mapreduce.py [--container hadoop-client]
"""

from __future__ import annotations

import argparse
import csv
import io
import subprocess
import sys
import uuid

# InvoiceNo, StockCode, Description, Quantity, InvoiceDate, UnitPrice, CustomerID, Country
FIXTURE: list[tuple[str, ...]] = [
    ("I1", "P1", "Widget", "10", "12/1/2010 10:00", "2.00", "17001", "United Kingdom"),
    ("I1", "P2", "Gadget, large", "5", "12/1/2010 10:00", "4.00", "17001", "United Kingdom"),
    # An exact duplicate of the first row: the reducer must collapse it.
    ("I1", "P1", "Widget", "10", "12/1/2010 10:00", "2.00", "17001", "United Kingdom"),
    ("I2", "P1", "Widget", "3", "1/5/2011 11:00", "2.00", "17001", "United Kingdom"),
    ("I3", "P3", "Thing", "1", "1/6/2011 9:00", "100.00", "17002", "France"),
    # A cancellation AND a negative quantity: one reversal, counted once.
    ("C4", "P3", "Thing", "-1", "1/7/2011 9:00", "100.00", "17002", "France"),
    # A real sale with no CustomerID.
    ("I5", "P2", "Gadget, large", "2", "2/1/2011 12:00", "4.00", "", "Germany"),
    # A negative quantity on an ordinary invoice number.
    ("I6", "P1", "Widget", "-2", "2/2/2011 13:00", "2.00", "17003", "United Kingdom"),
    # Three rows that must be rejected, one per rule.
    ("I7", "P4", "Freebie", "5", "2/3/2011 14:00", "0.00", "17003", "United Kingdom"),
    ("I8", "P5", "Odd", "0", "2/4/2011 14:00", "1.00", "17003", "United Kingdom"),
    ("I9", "P1", "Widget", "4", "not-a-date", "2.00", "17003", "United Kingdom"),
    ("I10", "P1", "Widget", "7", "3/1/2011 10:00", "2.00", "17002", "France"),
]

HEADER = (
    "InvoiceNo", "StockCode", "Description", "Quantity",
    "InvoiceDate", "UnitPrice", "CustomerID", "Country",
)

ANALYSES = [
    "customer_analysis",
    "monthly_sales",
    "product_analysis",
    "country_analysis",
    "repeat_customers",
    "rfm_analysis",
]


class Verifier:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.checked = 0

    def expect(self, label: str, actual: object, expected: object) -> None:
        self.checked += 1
        if isinstance(expected, float) and isinstance(actual, (int, float)):
            ok = abs(float(actual) - expected) < 0.005
        else:
            ok = actual == expected
        if ok:
            print(f"  ✓ {label} = {actual}")
        else:
            print(f"  ✗ {label}: expected {expected!r}, got {actual!r}")
            self.failures.append(f"{label}: expected {expected!r}, got {actual!r}")

    def expect_true(self, label: str, condition: bool, detail: str = "") -> None:
        self.checked += 1
        if condition:
            print(f"  ✓ {label}" + (f" — {detail}" if detail else ""))
        else:
            print(f"  ✗ {label}" + (f" — {detail}" if detail else ""))
            self.failures.append(label)

    def summary(self) -> int:
        print()
        print(f"{self.checked - len(self.failures)}/{self.checked} assertions passed")
        if self.failures:
            print()
            print("failures:")
            for failure in self.failures:
                print(f"  - {failure}")
            return 1
        return 0


def run(container: str, *command: str, stdin: bytes | None = None) -> str:
    """Runs a command inside a compose service and returns its stdout."""
    completed = subprocess.run(
        ["docker", "compose", "exec", "-T", container, *command],
        input=stdin,
        capture_output=True,
        timeout=1800,
        check=False,
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stderr.decode("utf-8", "replace")[-4000:])
        raise RuntimeError(
            f"'{' '.join(command)}' in {container} exited {completed.returncode}"
        )
    return completed.stdout.decode("utf-8", "replace")


def read_tsv(container: str, path: str) -> list[list[str]]:
    """Reads every part file of an output directory as tab separated rows."""
    text = run(container, "bash", "-lc", f"hdfs dfs -cat '{path}/part-*' 2>/dev/null || true")
    return [line.split("\t") for line in text.splitlines() if line.strip()]


def counters(container: str, job_id: str) -> dict[str, dict[str, int]]:
    """Counter groups of a finished job, read from the JobHistoryServer."""
    import json
    import urllib.request

    url = (
        f"http://historyserver:19888/ws/v1/history/mapreduce/jobs/{job_id}/counters"
    )
    text = run(container, "curl", "-fsS", url)
    payload = json.loads(text)
    groups: dict[str, dict[str, int]] = {}
    for group in (payload.get("jobCounters") or {}).get("counterGroup") or []:
        groups[group["counterGroupName"]] = {
            counter["name"]: counter["totalCounterValue"]
            for counter in group.get("counter") or []
        }
    return groups


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="hadoop-client")
    parser.add_argument("--jar", default="/opt/cartscope/cartscope-mapreduce.jar")
    arguments = parser.parse_args()
    container = arguments.container
    jar = arguments.jar

    run_id = f"verify-{uuid.uuid4().hex[:8]}"
    base = f"/cartscope/datasets/_verify/{run_id}"
    verifier = Verifier()

    print(f"MapReduce verification — {run_id}")
    print(f"container: {container}")
    print()

    # --- Write the fixture into HDFS ---------------------------------------
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(HEADER)
    writer.writerows(FIXTURE)
    fixture_csv = buffer.getvalue()

    run(container, "bash", "-lc", f"mkdir -p /tmp/{run_id}")
    run(
        container,
        "bash",
        "-lc",
        f"cat > /tmp/{run_id}/fixture.csv",
        stdin=fixture_csv.encode("utf-8"),
    )
    run(container, "bash", "-lc", f"hdfs dfs -mkdir -p {base}/raw")
    run(
        container,
        "bash",
        "-lc",
        f"hdfs dfs -put -f /tmp/{run_id}/fixture.csv {base}/raw/source.csv",
    )
    print(f"fixture written to {base}/raw/source.csv ({len(FIXTURE)} data rows)")
    print()

    # --- validate ----------------------------------------------------------
    print("validate")
    run(
        container,
        "bash",
        "-lc",
        f"hadoop jar {jar} validate "
        f"-D cartscope.reducers=2 "
        f"--input {base}/raw "
        f"--work /cartscope/jobs/{run_id}/validation "
        f"--output {base} "
        f"--run-id {run_id} "
        f"--report /tmp/{run_id}/validation.json "
        f"--manifest /cartscope/manifests/{run_id}/validation.json "
        f">/tmp/{run_id}/validate.log 2>&1",
    )

    validated = read_tsv(container, f"{base}/validated")
    rejected = read_tsv(container, f"{base}/rejected")

    verifier.expect("validated records", len(validated), 8)
    verifier.expect("rejected output rows", len(rejected), 4)

    reasons = {row[0] for row in rejected}
    verifier.expect_true(
        "every rejection rule fired exactly once",
        reasons == {
            "NON_POSITIVE_UNIT_PRICE",
            "ZERO_QUANTITY",
            "UNPARSEABLE_INVOICE_DATE",
            "DUPLICATE_RECORDS",
        },
        ", ".join(sorted(reasons)),
    )

    duplicate = next(row for row in rejected if row[0] == "DUPLICATE_RECORDS")
    verifier.expect("duplicate copies removed", int(duplicate[1]), 1)

    classes = [row[12] for row in validated]
    verifier.expect("fulfilled sales", classes.count("SALE"), 6)
    verifier.expect("returns and cancellations", classes.count("RETURN"), 2)

    # The quoted description survived parsing as one field.
    verifier.expect_true(
        "a quoted description with a comma stayed one field",
        any(row[2] == "Gadget, large" for row in validated),
        "found 'Gadget, large' intact",
    )
    verifier.expect_true(
        "a record with no CustomerID was kept",
        any(row[8] == "" for row in validated),
    )

    gross = sum(float(row[10]) for row in validated if row[12] == "SALE")
    returns = sum(float(row[11]) for row in validated if row[12] == "RETURN")
    verifier.expect("gross revenue in the canonical data", gross, 168.0)
    verifier.expect("returns in the canonical data", returns, 104.0)

    # --- the analyses ------------------------------------------------------
    for analysis in ANALYSES:
        print()
        print(analysis)
        run(
            container,
            "bash",
            "-lc",
            f"hadoop jar {jar} {analysis} "
            f"-D cartscope.reducers=2 "
            f"--input {base}/validated "
            f"--work /cartscope/jobs/{run_id}/{analysis} "
            f"--output /cartscope/results/{run_id}/{analysis} "
            f"--run-id {run_id} "
            f"--report /tmp/{run_id}/{analysis}.json "
            f"--manifest /cartscope/manifests/{run_id}/{analysis}.json "
            f">/tmp/{run_id}/{analysis}.log 2>&1",
        )
        check = CHECKS[analysis]
        check(container, run_id, verifier)

    # --- the cross-check ---------------------------------------------------
    print()
    print("agreement between independently computed results")
    totals = {}
    for analysis, output, column in (
        ("monthly_sales", "by_month", 3),
        ("country_analysis", "by_country", 3),
        ("product_analysis", "by_product", 3),
    ):
        rows = read_tsv(container, f"/cartscope/results/{run_id}/{analysis}/{output}")
        totals[analysis] = round(sum(float(row[column]) for row in rows), 2)

    verifier.expect("net revenue by month", totals["monthly_sales"], 64.0)
    verifier.expect("net revenue by country", totals["country_analysis"], 64.0)
    verifier.expect("net revenue by product", totals["product_analysis"], 64.0)
    verifier.expect_true(
        "all three agree",
        len(set(totals.values())) == 1,
        " = ".join(f"{name} {value}" for name, value in totals.items()),
    )

    # --- distribution evidence --------------------------------------------
    print()
    print("execution")
    import json

    report = json.loads(run(container, "cat", f"/tmp/{run_id}/customer_analysis.json"))
    verifier.expect("customer_analysis stages", len(report["stages"]), 3)
    verifier.expect_true(
        "every stage reported a YARN application id",
        all(stage["applicationId"].startswith("application_") for stage in report["stages"]),
        ", ".join(stage["applicationId"] for stage in report["stages"]),
    )
    first = report["stages"][0]
    groups = {
        group["name"]: {c["name"]: c["value"] for c in group["counters"]}
        for group in first["counterGroups"]
    }
    verifier.expect(
        "stage 1 read every validated record",
        groups["org.apache.hadoop.mapreduce.TaskCounter"]["MAP_INPUT_RECORDS"],
        8,
    )
    verifier.expect(
        "stage 1 excluded the record with no CustomerID",
        groups["com.cartscope.jobs.CustomerSpendingJob$Stat"]["SKIPPED_MISSING_CUSTOMER_ID"],
        1,
    )
    verifier.expect_true(
        "a combiner ran",
        groups["org.apache.hadoop.mapreduce.TaskCounter"].get("COMBINE_INPUT_RECORDS", 0) > 0,
        f"combine input {groups['org.apache.hadoop.mapreduce.TaskCounter'].get('COMBINE_INPUT_RECORDS')}",
    )

    # --- tidy up -----------------------------------------------------------
    run(container, "bash", "-lc", f"hdfs dfs -rm -r -f -skipTrash {base} "
                                  f"/cartscope/jobs/{run_id} "
                                  f"/cartscope/results/{run_id} "
                                  f"/cartscope/manifests/{run_id} >/dev/null 2>&1 || true")
    run(container, "bash", "-lc", f"rm -rf /tmp/{run_id}")

    return verifier.summary()


# ---------------------------------------------------------------------------
# Per-analysis expectations, worked out by hand from the fixture.
# ---------------------------------------------------------------------------

def check_customer(container: str, run_id: str, v: Verifier) -> None:
    rows = {
        row[0]: row
        for row in read_tsv(container, f"/cartscope/results/{run_id}/customer_analysis/by_customer")
    }
    v.expect("customers reported", len(rows), 3)

    # 17001: invoices I1 (gross 40) and I2 (gross 6), both completed.
    # I1 has three source lines, one of which was a duplicate, so counting
    # records instead of invoices would report 2 or 3 orders rather than 2.
    one = rows["17001"]
    v.expect("17001 completed orders", int(float(one[1])), 2)
    v.expect("17001 gross spending", float(one[2]), 46.0)
    v.expect("17001 returns", float(one[3]), 0.0)
    v.expect("17001 net spending", float(one[4]), 46.0)
    v.expect("17001 average order value", float(one[5]), 23.0)

    # 17002: I3 (100) completed, C4 (returns 100) not a completed order,
    # I10 (14) completed.
    two = rows["17002"]
    v.expect("17002 completed orders", int(float(two[1])), 2)
    v.expect("17002 gross spending", float(two[2]), 114.0)
    v.expect("17002 returns", float(two[3]), 100.0)
    v.expect("17002 net spending", float(two[4]), 14.0)
    v.expect("17002 average order value", float(two[5]), 57.0)
    v.expect("17002 invoices touched", int(float(two[7])), 3)

    # 17003: only a return, so no completed order and negative net spending.
    three = rows["17003"]
    v.expect("17003 completed orders", int(float(three[1])), 0)
    v.expect("17003 net spending", float(three[4]), -4.0)
    v.expect("17003 average order value", float(three[5]), 0.0)

    ranked = read_tsv(container, f"/cartscope/results/{run_id}/customer_analysis/ranked_by_net_spending")
    v.expect("ranked rows", len(ranked), 3)
    v.expect("rank 1 is the highest net spender", ranked[0][1], "17001")
    v.expect_true(
        "the ranking is in descending order of net spending",
        [float(row[5]) for row in ranked] == sorted(
            (float(row[5]) for row in ranked), reverse=True
        ),
        ", ".join(f"{row[1]}={row[5]}" for row in ranked),
    )


def check_monthly(container: str, run_id: str, v: Verifier) -> None:
    rows = {
        row[0]: row
        for row in read_tsv(container, f"/cartscope/results/{run_id}/monthly_sales/by_month")
    }
    v.expect("months reported", len(rows), 4)

    december = rows["2010-12"]
    v.expect("2010-12 gross", float(december[1]), 40.0)
    v.expect("2010-12 net", float(december[3]), 40.0)
    v.expect("2010-12 distinct invoices", int(float(december[4])), 1)
    v.expect("2010-12 identifiable customers", int(float(december[6])), 1)
    v.expect("2010-12 quantity sold", int(float(december[7])), 15)

    january = rows["2011-01"]
    v.expect("2011-01 gross", float(january[1]), 106.0)
    v.expect("2011-01 returns", float(january[2]), 100.0)
    v.expect("2011-01 net", float(january[3]), 6.0)
    v.expect("2011-01 distinct invoices", int(float(january[4])), 3)
    v.expect("2011-01 completed invoices", int(float(january[5])), 2)
    v.expect("2011-01 identifiable customers", int(float(january[6])), 2)

    february = rows["2011-02"]
    # I5 has no CustomerID, so it counts in the money but not in the customers.
    v.expect("2011-02 gross", float(february[1]), 8.0)
    v.expect("2011-02 returns", float(february[2]), 4.0)
    v.expect("2011-02 identifiable customers", int(float(february[6])), 1)
    v.expect("2011-02 distinct invoices", int(float(february[4])), 2)

    v.expect_true(
        "months come out in chronological order",
        [row[0] for row in read_tsv(
            container, f"/cartscope/results/{run_id}/monthly_sales/by_month"
        )] == ["2010-12", "2011-01", "2011-02", "2011-03"],
    )


def check_product(container: str, run_id: str, v: Verifier) -> None:
    rows = {
        row[0]: row
        for row in read_tsv(container, f"/cartscope/results/{run_id}/product_analysis/by_product")
    }
    v.expect("products reported", len(rows), 3)

    p1 = rows["P1"]
    v.expect("P1 gross revenue", float(p1[1]), 40.0)
    v.expect("P1 returns", float(p1[2]), 4.0)
    v.expect("P1 net revenue", float(p1[3]), 36.0)
    v.expect("P1 quantity sold", int(float(p1[4])), 20)
    v.expect("P1 quantity returned", int(float(p1[5])), 2)
    v.expect("P1 distinct invoices", int(float(p1[6])), 4)
    v.expect("P1 description", p1[9], "Widget")

    p2 = rows["P2"]
    v.expect("P2 net revenue", float(p2[3]), 28.0)
    v.expect("P2 distinct invoices", int(float(p2[6])), 2)
    v.expect("P2 description kept its comma", p2[9], "Gadget, large")

    p3 = rows["P3"]
    v.expect("P3 net revenue", float(p3[3]), 0.0)
    v.expect("P3 quantity returned", int(float(p3[5])), 1)

    ranked = read_tsv(container, f"/cartscope/results/{run_id}/product_analysis/ranked_by_quantity_sold")
    v.expect("top product by quantity", ranked[0][1], "P1")


def check_country(container: str, run_id: str, v: Verifier) -> None:
    rows = {
        row[0]: row
        for row in read_tsv(container, f"/cartscope/results/{run_id}/country_analysis/by_country")
    }
    v.expect("countries reported", len(rows), 3)

    uk = rows["United Kingdom"]
    v.expect("United Kingdom gross", float(uk[1]), 46.0)
    v.expect("United Kingdom returns", float(uk[2]), 4.0)
    v.expect("United Kingdom net", float(uk[3]), 42.0)
    v.expect("United Kingdom distinct invoices", int(float(uk[4])), 3)
    v.expect("United Kingdom identifiable customers", int(float(uk[6])), 2)
    v.expect("United Kingdom transaction records", int(float(uk[9])), 4)

    france = rows["France"]
    v.expect("France net", float(france[3]), 14.0)
    v.expect("France identifiable customers", int(float(france[6])), 1)

    # Germany's only sale has no CustomerID: the revenue is kept, the customer
    # count is zero, and the column is labelled "identifiable customers" to say so.
    germany = rows["Germany"]
    v.expect("Germany net", float(germany[3]), 8.0)
    v.expect("Germany identifiable customers", int(float(germany[6])), 0)


def check_repeat(container: str, run_id: str, v: Verifier) -> None:
    summary = {
        row[0]: float(row[1])
        for row in read_tsv(container, f"/cartscope/results/{run_id}/repeat_customers/summary")
    }
    v.expect("identified customers", int(summary["identified_customers"]), 3)
    v.expect("repeat customers", int(summary["repeat_customers"]), 2)
    v.expect(
        "customers with a single completed invoice",
        int(summary["customers_with_single_completed_invoice"]),
        0,
    )
    v.expect(
        "customers without a completed invoice",
        int(summary["customers_without_completed_invoice"]),
        1,
    )
    v.expect("total completed invoices", int(summary["total_completed_invoices"]), 4)
    v.expect("purchasing customers", int(summary["purchasing_customers"]), 2)
    v.expect("average purchase frequency", summary["average_purchase_frequency"], 2.0)
    v.expect("repeat customer percentage", summary["repeat_customer_percentage"], 100.0)
    v.expect(
        "average net spend of repeat customers",
        summary["average_net_spend_repeat_customers"],
        30.0,
    )


def check_rfm(container: str, run_id: str, v: Verifier) -> None:
    rows = {
        row[0]: row
        for row in read_tsv(container, f"/cartscope/results/{run_id}/rfm_analysis/by_customer")
    }
    # 17003 never completed a purchase, so recency is undefined and the customer
    # is excluded rather than given a fabricated score.
    v.expect("customers scored", len(rows), 2)
    v.expect_true("the never-purchased customer was excluded", "17003" not in rows)

    v.expect("17002 recency in days", int(rows["17002"][1]), 0)
    v.expect("17002 frequency", int(rows["17002"][2]), 2)
    v.expect("17002 monetary", float(rows["17002"][3]), 14.0)
    v.expect("17001 recency in days", int(rows["17001"][1]), 54)
    v.expect("17001 monetary", float(rows["17001"][3]), 46.0)

    # The reference date is the dataset's latest completed purchase, not now.
    v.expect("reference date", rows["17001"][10], "2011-03-01 10:00:00")
    v.expect_true(
        "every score is between 1 and 5",
        all(1 <= int(row[index]) <= 5 for row in rows.values() for index in (4, 5, 6)),
    )

    segments = read_tsv(container, f"/cartscope/results/{run_id}/rfm_analysis/by_segment")
    v.expect(
        "segment customer counts add up to the scored customers",
        sum(int(float(row[1])) for row in segments),
        2,
    )


CHECKS = {
    "customer_analysis": check_customer,
    "monthly_sales": check_monthly,
    "product_analysis": check_product,
    "country_analysis": check_country,
    "repeat_customers": check_repeat,
    "rfm_analysis": check_rfm,
}


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted")
        sys.exit(130)
