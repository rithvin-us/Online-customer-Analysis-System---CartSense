"""Celery application.

Ingestion and analysis are long running — a MapReduce chain takes minutes — so
neither can happen inside an HTTP request. The API validates a request,
persists the intent, and hands it to this worker; the UI then follows progress
by polling the metadata the worker writes.

Two queues keep the two kinds of work from blocking each other: a large upload
being profiled must not delay a submitted analysis.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import settings
from app.core.logging import configure_logging

configure_logging()

celery_app = Celery(
    "cartscope",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.ingest_tasks", "app.tasks.analysis_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    #: A Hadoop job chain can run for a long time; the result backend should
    #: keep its record long enough for the UI to notice.
    result_expires=86_400,
    #: One job at a time per worker process. These tasks are not CPU bound in
    #: the worker — they wait on YARN — but prefetching would hide queued work
    #: from a second worker.
    worker_prefetch_multiplier=1,
    #: Acknowledge only once finished, so a worker crash re-queues the work
    #: rather than losing it.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_routes={
        "cartscope.ingest.*": {"queue": "ingest"},
        "cartscope.analysis.*": {"queue": "analysis"},
    },
    broker_connection_retry_on_startup=True,
)
