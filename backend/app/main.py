"""FastAPI application.

The backend's responsibility is orchestration and metadata: it receives data,
profiles it, puts it in HDFS, submits Hadoop jobs, records what Hadoop
reported, and serves the reducers' output back. It does not compute analytical
results.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.requests import Request

from app import __version__
from app.api import benchmarks, catalog, cluster, datasets, health, runs
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.services import hdfs
from app.tasks.celery_app import celery_app  # noqa: F401

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.joblog_dir.mkdir(parents=True, exist_ok=True)

    # The NameNode container creates the HDFS layout at startup. Doing it again
    # here is harmless and covers the case where the API starts against an
    # already-running cluster whose layout predates a new subdirectory.
    try:
        hdfs.mkdirs(f"{settings.hdfs_root}/datasets")
        hdfs.mkdirs(f"{settings.hdfs_root}/jobs")
        hdfs.mkdirs(f"{settings.hdfs_root}/results")
        hdfs.mkdirs(f"{settings.hdfs_root}/manifests")
        hdfs.mkdirs(f"{settings.hdfs_root}/benchmarks")
        log.info("HDFS layout verified under %s", settings.hdfs_root)
    except hdfs.HdfsError as unavailable:
        # The API still serves metadata and the cluster view when HDFS is down,
        # and the cluster view is exactly where that fact needs to be visible.
        log.warning("HDFS is not reachable at startup: %s", unavailable)

    yield


app = FastAPI(
    title="CartScope",
    description=(
        "Distributed retail intelligence platform. Datasets are stored in HDFS, "
        "analysed by native Hadoop MapReduce jobs on YARN, and the results, "
        "counters and job history are served from here."
    ),
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# The frontend is served from a different origin in development (port 3000 to
# port 8000), so the browser needs permission to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1|frontend)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(catalog.router, prefix="/api")
app.include_router(datasets.router, prefix="/api")
app.include_router(runs.router, prefix="/api")
app.include_router(cluster.router, prefix="/api")
app.include_router(benchmarks.router, prefix="/api")


@app.exception_handler(hdfs.HdfsError)
async def hdfs_error_handler(request: Request, error: hdfs.HdfsError) -> JSONResponse:
    """Surfaces an HDFS failure as a 503 with the command output.

    A storage outage is an operational condition, not a bug in the request, and
    the command's own stderr is the most useful thing to show.
    """
    log.error("HDFS error on %s: %s", request.url.path, error)
    return JSONResponse(
        status_code=503,
        content={
            "detail": str(error),
            "command": error.command,
            "output": error.output[:4000],
        },
    )


@app.get("/api", include_in_schema=False)
def api_root() -> dict[str, str]:
    return {
        "service": "cartscope-api",
        "version": __version__,
        "docs": "/api/docs",
    }
