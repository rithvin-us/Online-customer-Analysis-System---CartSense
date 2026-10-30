#!/usr/bin/env bash
#
# CartScope backend entrypoint.
#
# Usage: cartscope-backend <api|worker|shell> [args...]
#
# Both roles first render the Hadoop configuration, because this image carries
# a real Hadoop client and the client must agree with the cluster about the
# NameNode address, the replication factor and the block size.
set -euo pipefail

ROLE="${1:-api}"
shift || true

# Reuse the cluster image's config rendering, then return here.
/usr/local/bin/cartscope-hadoop render-config-only true

log() { printf '[cartscope-backend][%s] %s\n' "$ROLE" "$*" >&2; }

wait_for_postgres() {
  local tries=0
  until python3 -c "
import sys
import psycopg
from app.core.config import settings
try:
    psycopg.connect(settings.psycopg_dsn, connect_timeout=3).close()
except Exception as error:
    print(error, file=sys.stderr)
    sys.exit(1)
" >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [ "$tries" -gt 60 ]; then
      log 'PostgreSQL did not become available'
      return 1
    fi
    sleep 2
  done
  log 'PostgreSQL is available'
}

case "$ROLE" in
  api)
    wait_for_postgres
    log 'applying database migrations'
    alembic upgrade head
    log 'starting uvicorn on 0.0.0.0:8000'
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers "$@"
    ;;

  worker)
    wait_for_postgres
    # Migrations are owned by the API container so that two containers never
    # race to apply the same revision.
    log 'starting celery worker'
    exec celery -A app.tasks.celery_app:celery_app worker \
      --loglevel="${CARTSCOPE_LOG_LEVEL:-INFO}" \
      --concurrency="${CARTSCOPE_WORKER_CONCURRENCY:-2}" \
      -Q "${CARTSCOPE_WORKER_QUEUES:-ingest,analysis}" "$@"
    ;;

  migrate)
    wait_for_postgres
    exec alembic upgrade head
    ;;

  shell)
    exec "${@:-bash}"
    ;;

  *)
    log "unknown role '$ROLE'"
    exit 64
    ;;
esac
