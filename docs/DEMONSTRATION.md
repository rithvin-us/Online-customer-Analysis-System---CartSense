# Demonstration walkthrough

A sequence that proves each of the project's claims, with the command or the
screen that proves it. Roughly 20 minutes at a normal pace.

Have the stack up and the dataset loaded first:

```bash
make build && make up && make wait
make dataset && make seed
```

---

## 1. The cluster is real, and it has three workers

**Screen** — *HDFS and YARN*.

Point at the DataNode table: three independent containers, each with its own
capacity and its own block count. Then the NodeManager table: three workers, each
advertising 2048 MiB.

**Prove it from the command line:**

```bash
make report        # the NameNode's own DataNode report
docker compose exec hadoop-client yarn node -list
```

**Say the quiet part out loud.** These are thirteen containers on one physical
machine, not three computers. The processes, the storage and the scheduling are
genuinely separate; the network cost and the CPU parallelism are not. `docs/ARCHITECTURE.md`
sets out exactly which claims that supports.

---

## 2. The data is in HDFS, split into blocks, replicated across DataNodes

**Screen** — *Datasets → UCI Online Retail → the ready version → HDFS storage*.

The block table lists each block of the raw upload and the DataNodes holding it.
Two hostnames per block, because replication is 2. The block count is the number
of map input splits the next job will get.

**Prove it:**

```bash
docker compose exec hadoop-client \
  hdfs fsck /cartscope/datasets/*/versions/*/raw/source.csv -files -blocks -locations
```

**Then stop a DataNode and show HDFS survive it:**

```bash
docker compose stop datanode3
# within about a minute
make report                       # datanode3 is dead; the other two carry the data
docker compose start datanode3    # HDFS re-replicates on its own
```

---

## 3. Cleaning is a Hadoop job, and every rule is accountable

**Screen** — the same version, *Data quality*, then *Classification*.

*Data quality* describes the file: encoding, schema match, duplicate rows,
per-column unparseable values, SHA-256. *Classification* shows what the Hadoop
validation job did: accepted records, fulfilled sales, returns and cancellations,
duplicates removed, and a count against every rejection rule.

Two things worth pointing out:

* The duplicate count is computed **twice, independently** — once by the Python
  profiler reading the file, once by the reducer collapsing identical records —
  and the two agree. That is a real cross-check, not a restatement.
* Roughly 135,000 rows have no `CustomerID`. They are *kept*, because the sale
  happened, and each analysis then decides whether it can attribute them. The
  exclusions are visible as counters.

**Screen** — *Records → Rejected records*. Every rejected row, with the rule that
rejected it. Nothing was silently dropped.

---

## 4. An analysis is a chain of real MapReduce jobs

**Screen** — the version, **Run analyses**. Open **Hadoop settings** so the
reducer count and split size are visible, then submit all six.

Switch to the YARN ResourceManager at <http://localhost:8088> while it runs. The
applications appear one after another, named
`cartscope:<analysis>:<stage>:<run_id>`. A run of all six submits **23 YARN
applications**.

**Screen** — the run page. The stage chain for each analysis, each stage carrying
its own duration and task counts.

Ask the question the stage chain answers: *why is customer spending three jobs?*
Because an invoice has many lines, so counting records would multiply every
customer's order count by their basket size. Stage one groups by
`(customer, invoice)` to collapse each invoice to one row; stage two counts; stage
three ranks.

---

## 5. The numbers come from Hadoop, and here are the counters

**Screen** — run page → an analysis → a stage → *Counters*.

Map input records, map output records, reduce input groups, reduce output records,
launched map and reduce tasks, failed tasks, HDFS bytes read and written. Expand
*Every counter group Hadoop reported* for the raw list.

**Cross-check it against the cluster**, so the stored values are visibly the
cluster's values:

```bash
curl -s http://localhost:8000/api/cluster/jobs/<job id>/counters | python3 -m json.tool | head -40
```

That endpoint re-reads the counters from the JobHistoryServer. The same numbers.

Point out the em dashes: a counter Hadoop did not report shows as absent, not as
zero. A map-only stage has no reduce counters, and the UI says so rather than
claiming zero.

---

## 6. The work really was distributed across the workers

**Screen** — the same stage → *Worker placement*.

One bar per worker host, split into map and reduce attempts, and under *Every
attempt* the node each individual attempt ran on. Those hostnames come from the
JobHistoryServer's task attempt records.

**Prove it:**

```bash
curl -s http://localhost:8000/api/cluster/jobs/<job id>/tasks \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["summary"])'
```

---

## 7. The reducers' output, and the logs that produced it

**Screen** — run page → an analysis → *Results*.

The output selector lists each directory the analysis wrote. Each result is
readable as a table, with a chart above it where one helps. Export any of them as
CSV, TSV or JSON.

**Screen** — *Driver log*. The real stdout of `hadoop jar`: the submission, the
split count, the progress percentages, the counter dump. The first line is the
exact command, so it can be copied and run by hand.

**Screen** — *Container logs*. The logs the NodeManagers aggregated into HDFS —
the ApplicationMaster's log and one section per task attempt. If aggregation has
not finished, Hadoop's own message is passed through unchanged rather than
replaced with filler.

**Browse the raw output:**

```bash
docker compose exec hadoop-client hdfs dfs -ls -R /cartscope/results | head -30
docker compose exec hadoop-client \
  hdfs dfs -cat '/cartscope/results/<run_id>/monthly_sales/by_month/part-r-00000'
```

Those are the exact bytes the UI is displaying.

**Inspect an intermediate stage**, to show the chain is real:

```bash
docker compose exec hadoop-client \
  hdfs dfs -cat '/cartscope/jobs/<run_id>/customer_analysis/invoice-rollup/part-r-00000' | head
```

One row per `(customer, invoice)` — the stage that makes the order count correct.

---

## 8. Two Hadoop results agree with each other

The country analysis and the monthly analysis total net revenue by completely
different keys, in separate job chains. They should land on the same number, and
nothing in the backend could make them agree if the jobs were wrong.

```bash
make test-e2e
```

The last check in that run is exactly this comparison. The whole script asserts
the claims above: blocks split across DataNodes, every analysis succeeded, real
job and application ids, more than one map task, more than one worker host,
readable reducer output, and the two totals agreeing.

---

## 9. Scaling and benchmarking

**Screen** — the dataset → **Generate a larger version** → 1,000,000 rows.

Say what the generator preserves and why it matters: whole invoices resampled from
the source's own product catalogue, customer population and monthly weighting,
with its rates of missing `CustomerID`, cancellation and duplication reproduced.
A benchmark over data with the wrong shape measures the wrong thing.

When it is ready, run the same six analyses against it. Then:

**Screen** — *Benchmarks*. Select both runs.

Wall clock grows with the data; records per second stays roughly flat; the map
task count roughly doubles because the file spans twice the blocks.

**Then show parallelism on identical data.** Run the original version again with
**Maximum split size = 1 MiB**. Roughly four times the map tasks over the same
bytes. The speed-up is sub-linear, and that is the honest finding on one machine:
the three NodeManagers share the host's CPUs. The benchmark table records the
cluster's shape with each run so the comparison says so.

---

## 10. Reproducibility

Point at one run's *Run configuration* panel: the reducer count, the split size,
the date interpretation, the dataset version and its SHA-256.

**Screen** — **Analytical report**. A single JSON document carrying the dataset
provenance, the exact Hadoop configuration, every stage with its real counters
and task placement, and the head of each result. That is the artefact to attach to
a write-up: it explains where each number came from.

Also kept with the data, on the cluster itself:

```bash
docker compose exec hadoop-client hdfs dfs -ls /cartscope/manifests/<run_id>/
docker compose exec hadoop-client hdfs dfs -cat /cartscope/manifests/<run_id>/monthly_sales.json | head -40
```

---

## Likely questions

**"Is Hadoop actually doing the work, or is Python computing this?"**
Every analytical value is written by a reducer to HDFS and read back as text. The
backend labels columns and casts strings to numbers; it never re-adds a column or
re-derives a total. `hdfs dfs -cat` on a result file shows the same values the UI
shows. The two-way agreement check in §8 could not pass if that were not true.

**"Why is the block size 4 MiB? That is not realistic."**
Correct, and it is deliberate. A 45 MB file under a 128 MiB block is one split and
one map task, which demonstrates nothing. `.env` switches to 128 MiB for a
production-like profile.

**"Three containers on one laptop is not a real cluster."**
Agreed, and the project says so in writing. What is real: separate processes,
separate storage volumes, separate YARN budgets, real block placement, real
scheduling across workers, real failure recovery. What is not: network cost, rack
awareness, and genuine hardware parallelism.

**"Why does an analysis need three jobs?"**
Because distinct counts and per-invoice aggregation need a shuffle to be correct.
`docs/MAPREDUCE.md` works through each chain.

**"What happens to a bad record?"**
It is rejected with the rule that rejected it, written to `/rejected`, and counted.
No record is repaired by guesswork and none is silently dropped.

**"Could you run this on more machines?"**
Yes, without changing any code: the configuration templates take the NameNode and
ResourceManager hostnames from the environment. What changes is `docker-compose.yml`,
which would become a deployment across hosts.
