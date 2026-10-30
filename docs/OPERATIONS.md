# Operations

## Starting and stopping

```bash
make build        # build every image, in dependency order
make up           # start all 13 containers
make wait         # block until the cluster can actually accept work
make status       # container state and health
make down         # stop, keeping every volume
make destroy      # stop AND delete all data — asks for confirmation first
```

`make wait` is not optional in a script. "The containers started" is not the same
as "the cluster is ready": it blocks until HDFS has left safe mode with all three
DataNodes registered, the ResourceManager has all three NodeManagers registered,
and the API answers. Submitting a job before that produces confusing
"no NodeManagers available" failures.

`make down` preserves NameNode metadata, every DataNode's block storage and the
database, because they are on named volumes. Only `make destroy` removes them.

## Verifying the cluster by hand

```bash
# HDFS: the DataNode report, straight from the NameNode
make report

# The CartScope tree
make hdfs

# YARN: registered NodeManagers
docker compose exec hadoop-client yarn node -list

# A configured Hadoop client shell
make shell-client
```

Useful things to run inside that shell:

```bash
hdfs dfsadmin -report                       # per-DataNode capacity and block counts
hdfs fsck /cartscope -files -blocks -locations | head -40
hdfs dfs -du -h /cartscope                  # size per subtree
yarn application -list -appStates ALL
mapred job -list all
yarn logs -applicationId application_…      # aggregated container logs
```

## Loading data

```bash
make dataset                      # fetch the UCI archive and convert it to CSV
make seed                         # upload through the API and wait for validation
scripts/seed_dataset.sh path.csv "My dataset"   # any CSV with the same eight columns
```

The UCI host serves slowly, advertises no `Content-Length` and does not support
byte ranges, so a truncated transfer looks like a successful one to `curl` and
cannot be resumed. `scripts/fetch_uci_dataset.sh` therefore retries from the
start and verifies each attempt by opening the file as a ZIP container before
accepting it. On a slow connection this can take a long time; it is the network,
not the script.

Uploading from the workbench does exactly the same thing as `make seed`.

## Running analyses

From the workbench, or directly:

```bash
curl -s -X POST http://localhost:8000/api/runs \
  -H 'Content-Type: application/json' \
  -d '{
        "dataset_version_id": "<version uuid>",
        "analyses": ["customer_analysis","monthly_sales","product_analysis",
                     "country_analysis","repeat_customers","rfm_analysis"],
        "label": "baseline",
        "configuration": {"reducers": 3}
      }'
```

Watch it:

```bash
curl -s http://localhost:8000/api/runs/<run id> | python3 -m json.tool | head -40
make logs                                  # API and worker
docker compose logs -f nodemanager1        # a worker's view
```

Or run a job entirely by hand, bypassing the application:

```bash
docker compose exec worker hadoop jar /opt/cartscope/cartscope-mapreduce.jar \
  monthly_sales \
  -D cartscope.reducers=3 \
  --input  /cartscope/datasets/<dataset>/versions/<version>/validated \
  --work   /cartscope/jobs/manual-1/monthly_sales \
  --output /cartscope/results/manual-1/monthly_sales \
  --run-id manual-1 \
  --report /tmp/manual-1.json \
  --manifest /cartscope/manifests/manual-1/monthly_sales.json
```

The command the application used for any analysis is the first line of that
analysis's driver log, so it can be copied out of the UI and pasted into a
terminal unchanged.

## Scaling the data

The UCI dataset is about 45 MB, which is small. To see how the platform behaves
as data grows, generate a larger dataset from it:

1. Open the dataset, select a `READY` version, choose **Generate a larger
   version**.
2. Pick a target: 100,000 / 500,000 / 1,000,000 / 2,000,000 rows, or type one.
3. The generated file goes through the same profiling, HDFS upload and Hadoop
   validation as an upload, so a benchmark against it is comparable to one
   against the real data.

The generator is a structure-preserving resampler, not a random row factory. It
learns the source's product catalogue and per-product price range, how often each
product is bought, the customer population and how often each returns, basket
sizes, line quantities, the monthly weighting of activity, and the rates of
missing `CustomerID`, cancellation and duplication. It then synthesises **whole
invoices**, so the generated data has the structure the analyses depend on: an
invoice has several lines, a customer has several invoices, and some invoices
reverse earlier ones. Generation is seeded, so the same request reproduces the
same dataset.

### Rough expectations on the default profile

| Rows | File size | Blocks at 4 MiB | Map tasks, first stage |
|---|---|---|---|
| 540,000 | ~45 MB | ~11 | ~11 |
| 1,000,000 | ~85 MB | ~21 | ~21 |
| 2,000,000 | ~170 MB | ~42 | ~42 |

With 6 GiB of schedulable memory and 512 MiB containers, up to twelve map tasks
run concurrently, so a job's map phase runs in waves.

## Benchmarking

Two comparisons are worth making.

**Same analyses, more data.** Run the full set against the 540k version and then
against a 1M-row version. Records per second should stay roughly flat while wall
clock grows — which is the useful observation: the pipeline is throughput-bound
rather than overhead-bound once the data is large enough to fill the map phase.

**Same data, more parallelism.** Run the same analyses against the same version
twice, once with the default splits and once with
**Maximum split size = 1 MiB**. The second run launches roughly four times the
map tasks over identical data. On one machine the speed-up is sub-linear, because
the three NodeManagers share the host's CPUs — and the benchmark view records the
cluster's shape with each run so the comparison stays honest about that.

The comparison table derives every figure from the counters and timings Hadoop
reported. Throughput is the one computed value: records read divided by wall
clock. "Records read" is the map input of each analysis's *first* stage, which
avoids double counting the later stages that read the previous stage's output.

## Changing the cluster profile

Everything is in `.env`, and nothing there requires an image rebuild.

| Variable | Default | Effect |
|---|---|---|
| `CARTSCOPE_HDFS_REPLICATION` | 2 | Blocks per DataNode set |
| `CARTSCOPE_HDFS_BLOCK_SIZE` | 4194304 | Block size, and therefore the split count. `134217728` for a production-like profile |
| `CARTSCOPE_NM_MEMORY_MB` | 2048 | Schedulable memory per NodeManager |
| `CARTSCOPE_MAP_MEMORY_MB` | 512 | Map container size |
| `CARTSCOPE_REDUCE_MEMORY_MB` | 512 | Reduce container size |
| `CARTSCOPE_AM_MEMORY_MB` | 768 | ApplicationMaster size |
| `CARTSCOPE_DEFAULT_REDUCERS` | 3 | Default reducers per stage |

After editing, `make down && make up`. Note that changing the block size affects
only *newly written* files: existing blocks keep the size they were written with,
which the HDFS browser shows per file.

### Adding a fourth worker

Copy the `datanode3` and `nodemanager3` service blocks in
`docker-compose.yml` to `datanode4` / `nodemanager4`, add a `datanode4-data`
volume, and raise `expected_datanodes` / `expected_nodemanagers` in
`backend/app/api/cluster.py`. Check the host has the memory first: each
NodeManager advertises 2 GiB.

---

## Troubleshooting

### A job stays ACCEPTED and never runs

YARN has no room for the ApplicationMaster. Check:

```bash
docker compose exec hadoop-client yarn node -list
curl -s http://localhost:8088/ws/v1/cluster/metrics | python3 -m json.tool
```

If `availableMB` is less than `CARTSCOPE_AM_MEMORY_MB`, something else is holding
containers — usually a previous run that has not finished. If no NodeManagers are
listed, they have not registered yet; `make wait`.

The default `yarn.scheduler.capacity.maximum-am-resource-percent` of 0.1 would
reserve only ~600 MiB of this 6 GiB cluster for ApplicationMasters, which is less
than one 768 MiB MapReduce AM, so no job could ever start. CartScope raises it to
0.5 in `hadoop/conf/capacity-scheduler.xml`. If you shrink the cluster, keep that
relationship in mind.

### Containers are killed with exit code 143

The physical memory check. A 512 MiB container with a `-Xmx410m` heap has little
headroom. Raise `CARTSCOPE_MAP_MEMORY_MB` and `CARTSCOPE_MAP_HEAP_MB` together,
keeping the heap at about 80% of the container.

The *virtual* memory check is disabled on purpose: a 512 MiB JVM reserves far
more than 512 MiB of virtual address space on a 64-bit host, so the default 2.1×
ratio would kill healthy containers.

### A dataset version is stuck in `VALIDATING`

The validation job is still running, or it failed. Look at the driver log in the
UI, or:

```bash
docker compose exec api cat /var/lib/cartscope/joblogs/ingest-<version>/validation.log
docker compose logs --tail 100 worker
```

A failed version can be retried from the UI, which clears the partial HDFS state
first — the validation job refuses to overwrite an existing output, so without
that the retry would fail immediately.

### "result directory already exists and will not be overwritten"

Working as intended: a successful analytical output is never overwritten. Submit
a new run; it gets a new run id and a new directory.

### HDFS reports under-replicated blocks

Expected while a DataNode is restarting — HDFS re-replicates on its own. If it
persists, a DataNode is down:

```bash
make report
docker compose logs --tail 50 datanode2
```

### A frontend change does not show up

The production image is a compiled bundle. Either rebuild it:

```bash
docker compose build frontend && docker compose up -d frontend
```

or run the dev server for the duration:

```bash
FRONTEND_TARGET=dev docker compose up -d --build frontend
```

### The cluster will not start at all

Usually memory. The stack wants about 8 GB of RAM free; `docker stats` will show
containers being OOM-killed if it is not there. Lower `CARTSCOPE_NM_MEMORY_MB` to
1536 and the task containers to 384 MiB, or run fewer workers.

---

## Logs

| What | Where |
|---|---|
| API and worker | `make logs` |
| Hadoop daemons | `make logs-cluster`, or `docker compose logs <service>` |
| `hadoop jar` output per analysis | `joblogs` volume, and the driver log tab in the UI |
| Container logs per task attempt | Aggregated into HDFS by the NodeManagers; read with `yarn logs`, or the container logs tab in the UI |
| Job history | <http://localhost:19888> |

Log aggregation is enabled, which is why the UI can show real task logs. Nothing
in the product generates log text.

## Backups

The data worth keeping is in two places:

```bash
# PostgreSQL metadata
docker compose exec -T postgres pg_dump -U cartscope cartscope | gzip > cartscope-metadata.sql.gz

# HDFS content
docker compose exec hadoop-client hdfs dfs -get /cartscope /tmp/cartscope-backup
docker compose cp hadoop-client:/tmp/cartscope-backup ./cartscope-backup
```

Restoring metadata without the matching HDFS content leaves rows pointing at
paths that no longer exist. The UI reports that as an HDFS read failure rather
than as empty results, but the two should be restored together.
