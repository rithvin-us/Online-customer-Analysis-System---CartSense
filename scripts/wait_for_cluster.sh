#!/usr/bin/env bash
#
# Block until the CartScope cluster is ready to accept work.
#
# "Ready" is not "the containers started": it means the NameNode has left safe
# mode with all three DataNodes registered, the ResourceManager has all three
# NodeManagers registered, and the API answers. Submitting a job before that is
# what produces the confusing "no NodeManagers available" failures.
set -euo pipefail

cd "$(dirname "$0")/.."

TIMEOUT="${TIMEOUT:-420}"
EXPECTED_DATANODES="${EXPECTED_DATANODES:-3}"
EXPECTED_NODEMANAGERS="${EXPECTED_NODEMANAGERS:-3}"
API_PORT="$(grep -E '^API_HOST_PORT=' .env | cut -d= -f2)"

deadline=$(( $(date +%s) + TIMEOUT ))

say() { printf '[wait] %s\n' "$*"; }

live_datanodes() {
  docker compose exec -T hadoop-client \
    hdfs dfsadmin -report 2>/dev/null \
    | grep -c 'Name: ' || true
}

safemode_off() {
  docker compose exec -T hadoop-client \
    hdfs dfsadmin -safemode get 2>/dev/null | grep -q 'Safe mode is OFF'
}

registered_nodemanagers() {
  docker compose exec -T hadoop-client \
    yarn node -list -states RUNNING 2>/dev/null \
    | grep -cE '^nodemanager[0-9]+:' || true
}

api_ready() {
  curl -fsS --max-time 5 "http://localhost:${API_PORT}/api/health" >/dev/null 2>&1
}

while :; do
  now=$(date +%s)
  if [ "$now" -ge "$deadline" ]; then
    say "timed out after ${TIMEOUT}s"
    say "current state:"
    docker compose ps
    exit 1
  fi

  datanodes="$(live_datanodes)"
  nodemanagers="$(registered_nodemanagers)"

  if safemode_off \
     && [ "$datanodes" -ge "$EXPECTED_DATANODES" ] \
     && [ "$nodemanagers" -ge "$EXPECTED_NODEMANAGERS" ] \
     && api_ready; then
    say "ready: ${datanodes} DataNodes, ${nodemanagers} NodeManagers, HDFS out of safe mode, API responding"
    exit 0
  fi

  say "waiting — DataNodes ${datanodes}/${EXPECTED_DATANODES}, NodeManagers ${nodemanagers}/${EXPECTED_NODEMANAGERS}"
  sleep 6
done
