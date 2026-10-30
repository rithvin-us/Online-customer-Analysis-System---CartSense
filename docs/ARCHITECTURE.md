# Architecture

## What this cluster is, and what it is not

CartScope runs a **multi-container Apache Hadoop cluster on a single physical
machine**. There are thirteen containers:

| Role | Containers |
|---|---|
| HDFS | 1 NameNode, 3 DataNodes |
| YARN | 1 ResourceManager, 3 NodeManagers |
| MapReduce | 1 JobHistoryServer |
| Hadoop client | 1 (for manual inspection) |
| Application | API, Celery worker, frontend |
| Datastores | PostgreSQL, Redis |

**This is not a cluster of three independent computers, and the project does not
claim it is.** The distinction matters, so here is exactly what it does and does
not demonstrate.

### What is genuinely distributed

* **Processes.** Each DataNode and each NodeManager is a separate JVM in a
  separate container with its own hostname, its own filesystem namespace and its
  own network identity. They discover and heartbeat to the NameNode and the
  ResourceManager over the network exactly as they would on separate hosts.
* **Storage.** Each DataNode has its own Docker volume. HDFS splits a file into
  blocks and places each block on two of the three DataNodes, chosen by the
  NameNode's placement policy. `make report`, or the HDFS browser in the UI,
  shows which DataNodes hold which block — those are real placements, not a
  display of the configured value.
* **Scheduling.** The ResourceManager has 6 GiB of schedulable memory, 2 GiB per
  NodeManager, and allocates 512 MiB task containers from it. A job with eleven
  map tasks really is scheduled across all three NodeManagers, and the
  JobHistoryServer records which one ran each task attempt. The workbench reads
  those records and shows the distribution.
* **Failure handling.** Stop a DataNode and the NameNode marks it dead within
  about a minute; HDFS continues to serve from the surviving replica. Stop a
  NodeManager mid-job and YARN re-runs its tasks elsewhere. Both are worth
  demonstrating live.

### What is not demonstrated

* **Network cost.** All of the inter-node traffic crosses a Docker bridge on one
  host, so the shuffle is far cheaper than it would be between machines. Timing
  figures from this cluster are therefore optimistic about network overhead and
  should not be extrapolated to a physical cluster.
* **Rack awareness.** All containers are in one default rack, so the
  `DATA_LOCAL_MAPS` and `RACK_LOCAL_MAPS` counters are not meaningful as locality
  evidence here.
* **True hardware parallelism.** The three NodeManagers share the host's CPUs.
  Three tasks running concurrently are three processes time-sharing real cores,
  not three machines working in parallel. Throughput therefore does not scale
  linearly with the worker count on this profile, and the benchmark view records
  the cluster's shape with each run so a comparison is honest about that.

Everything about the *mechanics* — splits, mappers, combiners, the shuffle,
reducers, counters, speculative execution, log aggregation, job history — behaves
exactly as it does on a real cluster, because it is the same software doing it.
What a single machine cannot reproduce is the physics.

---

## Why the block size is small

The default `dfs.blocksize` here is **4 MiB**, where a production cluster would
use 128 MiB or more. That is deliberate.

Hadoop derives map input splits from HDFS blocks. The UCI Online Retail dataset
is about 45 MB. With a 128 MiB block it is one block, one split, one map task —
and a job with one map task cannot demonstrate distribution at all. At 4 MiB the
same file becomes roughly a dozen blocks and therefore roughly a dozen map
tasks, which the scheduler spreads across the three NodeManagers.

The run submission form also exposes `mapreduce.input.fileinputformat.split.maxsize`,
so the split count can be increased further over identical data. That is the
cleanest way to see the effect of parallelism on this cluster: same data, same
analyses, more map tasks.

Raising `CARTSCOPE_HDFS_BLOCK_SIZE` in `.env` to `134217728` gives a
production-like profile. Nothing else needs to change.

---

## Data flow

### Ingestion

```
upload ─▶ profile (Python)      encoding, delimiter, schema, column statistics,
          │                     duplicate rows, SHA-256
          ▼
      refuse if a blocking problem was found
          │
          ▼
      hdfs dfs -put ──▶ /cartscope/datasets/<id>/versions/<v>/raw
          │
          ▼
      hadoop jar … validate ──▶ /validated  canonical, de-duplicated, classified
                            └─▶ /rejected   with the rule that rejected each record
          │
          ▼
      counters, job id and YARN application id recorded in PostgreSQL
```

Two things are worth noting about the order. Nothing enters HDFS before it has
been understood, so a malformed upload never becomes cluster state. And nothing
is marked ready until Hadoop has validated it, so an analysis can only ever read
data the cluster itself has inspected.

**Scope boundary.** The Python profiler describes the *file*: how it is encoded,
whether the schema matches, how many values fail to parse, how many rows are
exact duplicates. It does not classify transactions and it does not compute
revenue. Classification and every analytical figure come from MapReduce. The
duplicate count the profiler finds and the `DUPLICATE_RECORDS` counter the
validation job reports are computed independently, which makes them a useful
cross-check on each other.

### Analysis

```
POST /api/runs ──▶ run + one execution row per analysis, all PENDING
     │
     ▼
Celery worker
     │  capture the cluster's shape (DataNodes, NodeManagers, memory) with the run
     │
     ├─▶ hadoop jar … customer_analysis   stage 1 ─▶ stage 2 ─▶ stage 3
     ├─▶ hadoop jar … monthly_sales       stage 1 ─▶ stage 2
     └─▶ …                                 (analyses run one after another)
            │
            ▼
     each stage's job id, YARN application id, state, timings and every counter
     group are read from the completed Job object and stored verbatim
            │
            ▼
     task attempt placement is read from the JobHistoryServer
            │
            ▼
     result row counts are counted in HDFS, and the result layout is recorded
```

Analyses within a run execute **sequentially**, not in parallel. On a cluster with
6 GiB of schedulable memory, two concurrent chains would spend most of their time
queued behind each other in YARN rather than running, which would make the
benchmark timings meaningless.

---

## Where each kind of state lives

| State | Where | Why |
|---|---|---|
| Uploaded files | `uploads` volume | So a failed ingestion can be retried without re-uploading |
| Raw, validated and rejected data | HDFS | The authoritative copy; replicated |
| Intermediate stage output | HDFS, under `/cartscope/jobs` | Scratch, cleared at the start of a run |
| Final results | HDFS, under `/cartscope/results` | Never overwritten |
| Counters, job ids, timings | PostgreSQL, and HDFS manifests | Queryable from the API, and kept beside the data |
| Driver logs | `joblogs` volume | The real stdout of `hadoop jar` |
| Container logs | HDFS, aggregated by the NodeManagers | Read back through `yarn logs` |
| Task queue | Redis | Celery broker and result backend |

NameNode metadata and every DataNode's block storage are on named Docker volumes,
never in a container's writable layer, so `make down` and `make up` preserve the
filesystem. Only `make destroy` deletes them, and it asks first.

---

## Why the backend is built on the Hadoop image

`backend/Dockerfile` starts `FROM cartscope/hadoop:3.5.0` and adds Python, rather
than starting from a Python image. The Celery worker submits jobs with the real
`hadoop jar` and `hdfs dfs` commands, so it needs the genuine Hadoop client, the
cluster's rendered configuration and a matching JVM. Reusing the cluster image
guarantees the client is exactly the version the daemons are.

The consequence is a build order: `cartscope/hadoop` must exist before the
backend image can build. `make build` does this in order; plain
`docker compose build` does not guarantee it.

---

## Reading HDFS: two mechanisms, each where it fits

The backend writes to HDFS with the **command line client** — it streams a local
file straight in and picks up the cluster's configuration without the backend
restating it — and reads with **WebHDFS over HTTP**, which returns structured
JSON for file status, content summaries and block locations.

Nothing in the backend parses human-readable CLI output into numbers.

---

## Separation of responsibilities

| Layer | Responsibility | Explicitly not its job |
|---|---|---|
| `mapreduce/` | Every analytical computation | Orchestration, metadata, presentation |
| `backend/` | Ingestion, job submission, metadata, serving results | Computing any analytical figure |
| `frontend/` | Presenting what the backend recorded | Deriving, totalling or recomputing any value |

This is the line the project is built around. The backend labels columns and
casts strings to numbers when it reads a result; it does not re-add a column or
re-derive a total. If a figure is wrong, it is wrong in a reducer, and the
reducer is the only place to fix it.
