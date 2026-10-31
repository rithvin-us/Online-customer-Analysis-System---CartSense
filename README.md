# CartScope — Distributed Retail Intelligence Platform

CartScope is a data engineering workbench for retail transaction data. It stores
datasets in **HDFS**, analyses them with **native Java Hadoop MapReduce** jobs
running on **YARN**, and gives you the job ids, the counters, the task placement
and the logs behind every number it reports.

The point of the product is the distributed processing, not the charts. Hadoop is
the engine: no analytical figure in CartScope is computed in Python, SQL, pandas
or the browser. Each one is produced by a mapper and a reducer, written to HDFS,
and read back for display.

---

## What it does

1. **Ingest** — upload a retail CSV. It is profiled (encoding, delimiter, schema,
   per-column statistics, duplicates, SHA-256), then written to HDFS unmodified.
2. **Validate** — a MapReduce job canonicalises every record, classifies it as a
   fulfilled sale or a reversal, de-duplicates through the shuffle, and writes
   rejected records alongside the rule that rejected each one.
3. **Analyse** — submit any combination of six analyses. Each is a chain of real
   MapReduce jobs; between them a run launches 2 to 5 YARN applications per
   analysis.
4. **Observe** — watch the stages, their YARN application ids, their Hadoop
   counters, which worker container ran each task attempt, the driver's output
   and the aggregated container logs.
5. **Inspect** — page through the reducers' output, browse the HDFS tree, see
   which DataNodes hold which block.
6. **Scale and benchmark** — generate a larger dataset from a real one, run the
   same analyses against both, and compare the execution cost.
7. **Export** — any result as CSV, TSV or JSON, or a whole run as a
   self-contained JSON report.

## The analyses

| Analysis | MapReduce jobs | What it answers |
|---|---|---|
| Customer spending | 3 | What each customer bought, returned and ultimately spent |
| Monthly sales | 2 | How revenue, returns and customer activity moved month by month |
| Product popularity | 8 | Which products sell, which earn, which come back, and how the catalogue divides into classes and bands |
| Country sales | 3 | Where the revenue comes from geographically |
| Repeat customers | 3 | Who came back, how often, and what they were worth |
| RFM segmentation | 4 | Recency, frequency and monetary scores, and the segment each implies |

Plus the validation job that every dataset version passes through: **24
MapReduce jobs in total** across the catalogue.

---

## Quick start

Requirements: Docker with Compose v2, about 8 GB of free RAM, and about 10 GB of
disk.

```bash
# 1. Build the images, in dependency order (the backend image is built FROM the
#    Hadoop image, so the order matters).
make build

# 2. Start all 13 containers.
make up

# 3. Wait until HDFS is out of safe mode with 3 DataNodes and YARN has all 3
#    NodeManagers registered. Submitting work before this fails confusingly.
make wait
```

Then open:

| | |
|---|---|
| Workbench | <http://localhost:3000> |
| API documentation | <http://localhost:8000/api/docs> |
| NameNode UI | <http://localhost:9870> |
| YARN ResourceManager | <http://localhost:8088> |
| MapReduce JobHistoryServer | <http://localhost:19888> |

### Load the demonstration dataset

```bash
make dataset   # downloads the UCI Online Retail archive and converts it to CSV
make seed      # uploads it through the API and waits for validation to finish
```

The UCI host is slow and does not support resumable downloads, so `make dataset`
verifies each attempt and retries; expect it to take a while on a modest
connection. Any CSV with the same eight columns works just as well — upload it
from the workbench.

### Verify the whole thing end to end

```bash
make test-e2e
```

This drives the real API and then asserts against what Hadoop reported: that the
raw file is split across several HDFS blocks held by several DataNodes, that every
analysis succeeded, that each stage has a genuine job id and YARN application id,
that the input was split across more than one map task, that task attempts ran on
more than one worker container, that the reducers' output is readable, and that
two independently computed Hadoop results agree with each other.

---

## Architecture

```
                 ┌──────────────┐
  browser  ────▶ │   frontend   │  Next.js workbench
                 └──────┬───────┘
                        │ HTTP
                 ┌──────▼───────┐        ┌────────────┐
                 │     api      │◀──────▶│ PostgreSQL │  metadata only
                 │   FastAPI    │        └────────────┘
                 └──────┬───────┘
                        │ Celery over Redis
                 ┌──────▼───────┐
                 │    worker    │  holds a real Hadoop client
                 └──────┬───────┘  and the compiled job jar
                        │ hadoop jar … / hdfs dfs …
        ┌───────────────┼────────────────────────────┐
        │               │                            │
 ┌──────▼─────┐  ┌──────▼───────────┐      ┌─────────▼──────────┐
 │  NameNode  │  │ ResourceManager  │      │ JobHistoryServer   │
 └──────┬─────┘  └──────┬───────────┘      └────────────────────┘
        │               │
 ┌──────▼──────────┐  ┌─▼───────────────────┐
 │ datanode 1,2,3  │  │ nodemanager 1,2,3   │
 └─────────────────┘  └─────────────────────┘
```

**All thirteen containers run on one physical machine.** The three DataNodes and
three NodeManagers are genuinely independent processes, with their own storage
volumes and their own YARN resource budgets, and work is genuinely distributed
between them — but they are not three separate computers, and nothing in this
project claims otherwise. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for
what that does and does not demonstrate.

### Cluster profile

| Setting | Value | Why |
|---|---|---|
| HDFS replication | 2 | Across three DataNodes, so block placement is observable |
| HDFS block size | 4 MiB | Small on purpose: the 45 MB sample dataset then spans many blocks and produces many map input splits |
| NodeManager memory | 2048 MiB each | 6 GiB of schedulable memory on one machine |
| Map / reduce container | 512 MiB | Four concurrent tasks per worker |
| ApplicationMaster | 768 MiB | With `maximum-am-resource-percent` raised to 0.5, or no job could start |
| Uber mode | **disabled** | Otherwise a small job runs inside the AM and no task containers are ever launched |
| Default reducers | 3 | One per worker, so the reduce phase is distributed too |

Every value lives in `.env` and can be changed without rebuilding an image.

### HDFS layout

```
/cartscope
  /datasets/<dataset_id>/versions/<version_id>/raw         the upload, unmodified
                                              /validated   canonical records
                                              /rejected    records + the rule that rejected them
  /jobs/<run_id>/<analysis>/<stage>                        intermediate stage output
  /results/<run_id>/<analysis>/<output>                    final reducer output
  /manifests/<run_id>/<analysis>.json                      counters and job ids, kept with the data
  /yarn-logs                                               aggregated container logs
  /mr-history                                              JobHistoryServer archives
```

Dataset versions and analytical runs are isolated by construction, and a
successful result is never overwritten: a repeat of the same analysis gets a new
run id, and the job driver refuses to start if its result directory already
exists.

---

## Repository layout

```
mapreduce/     Java 17 MapReduce jobs — the analytical engine
hadoop/        The Apache Hadoop image, its configuration templates and entrypoint
backend/       FastAPI + Celery: orchestration and metadata, never analytics
frontend/      Next.js workbench
scripts/       Dataset fetch, seeding, cluster readiness, end-to-end check
docs/          Architecture, business rules, the MapReduce design, operations
```

## Documentation

| Document | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Topology, the single-machine distinction, data flow, design decisions |
| [docs/BUSINESS_RULES.md](docs/BUSINESS_RULES.md) | Every cleaning rule and revenue definition, and why each was chosen |
| [docs/MAPREDUCE.md](docs/MAPREDUCE.md) | Each job's mappers, reducers, combiners and stage chain |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Running, verifying, troubleshooting, scaling and benchmarking |
| [docs/DEMONSTRATION.md](docs/DEMONSTRATION.md) | A walkthrough that proves each claim, with the commands |

## Tests

```bash
make test-java      # 36 tests over the MapReduce logic, including a run of
                    # the whole product chain on Hadoop's LocalJobRunner
make test-api       # backend unit tests (profiling, registry, result parsing, generator)
make typecheck-web  # frontend type check
make test-e2e       # end-to-end against the running cluster
```

## Technology

Apache Hadoop 3.5.0 (HDFS, YARN, MapReduce) · Java 17 · Maven · Python 3.12 ·
FastAPI · SQLAlchemy · Alembic · PostgreSQL 16 · Redis 7 · Celery · Next.js 15 ·
React 19 · TypeScript · Tailwind CSS · Recharts · Docker Compose

Every container version and dependency is pinned.

## A note on credentials

`.env` is committed on purpose: it is the cluster profile a reader needs in order
to reproduce these results. The PostgreSQL password in it is a local development
credential for a stack that binds only to localhost. Change it before running
this anywhere other than a development machine.
