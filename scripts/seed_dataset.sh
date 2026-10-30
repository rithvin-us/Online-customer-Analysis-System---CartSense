#!/usr/bin/env bash
#
# Load a retail CSV into a running CartScope stack and wait for it to validate.
#
# Usage: scripts/seed_dataset.sh [csv_path] [dataset_name]
#
# Defaults to data/online_retail.csv, which `make dataset` produces from the UCI
# archive. This drives the real API, so the dataset goes through exactly the
# ingestion path a human upload would: profiling, checksum, HDFS write, then the
# Hadoop validation job.
set -euo pipefail

cd "$(dirname "$0")/.."

CSV="${1:-data/online_retail.csv}"
NAME="${2:-UCI Online Retail}"
API_PORT="$(grep -E '^API_HOST_PORT=' .env | cut -d= -f2)"
API="http://localhost:${API_PORT}/api"
TIMEOUT="${TIMEOUT:-1800}"

if [ ! -f "$CSV" ]; then
  echo "no such file: $CSV" >&2
  echo "run 'make dataset' first, or pass a CSV path" >&2
  exit 1
fi

json_field() {
  python3 -I -c "
import json, sys
payload = json.load(sys.stdin)
for key in sys.argv[1].split('.'):
    if payload is None:
        break
    payload = payload[int(key)] if key.isdigit() else payload.get(key)
print('' if payload is None else payload)
" "$1"
}

echo "uploading $CSV ($(du -h "$CSV" | cut -f1)) as '$NAME'"
response="$(curl -fsS -X POST "$API/datasets" \
  -F "file=@${CSV};type=text/csv" \
  -F "name=${NAME}" \
  -F "description=UCI Online Retail transactions, loaded by scripts/seed_dataset.sh" \
  -F "day_first=false")"

dataset_id="$(printf '%s' "$response" | json_field id)"
version_id="$(printf '%s' "$response" | json_field versions.0.id)"

if [ -z "$dataset_id" ] || [ -z "$version_id" ]; then
  echo "unexpected response from the API:" >&2
  printf '%s\n' "$response" >&2
  exit 1
fi

echo "dataset  $dataset_id"
echo "version  $version_id"
echo "waiting for profiling, the HDFS write and the Hadoop validation job"

deadline=$(( $(date +%s) + TIMEOUT ))
last=""
while :; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "timed out waiting for the version to become READY" >&2
    exit 1
  fi

  detail="$(curl -fsS "$API/datasets/${dataset_id}/versions/${version_id}")"
  status="$(printf '%s' "$detail" | json_field status)"

  if [ "$status" != "$last" ]; then
    echo "  status: $status"
    last="$status"
  fi

  case "$status" in
    READY)
      echo
      printf '%s' "$detail" | python3 -I -c "
import json, sys
version = json.load(sys.stdin)
print(f\"raw rows        {version['raw_line_count']:,}\")
print(f\"validated       {version['validated_record_count']:,}\")
print(f\"rejected        {version['rejected_record_count']:,}\")
print(f\"duplicates      {version['duplicate_record_count']:,}\")
print(f\"sha256          {version['sha256']}\")
print(f\"validated path  {version['hdfs_validated_path']}\")
"
      echo
      echo "dataset version is ready"
      echo "DATASET_ID=${dataset_id}"
      echo "VERSION_ID=${version_id}"
      exit 0
      ;;
    FAILED)
      echo "ingestion failed:" >&2
      printf '%s' "$detail" | json_field error >&2
      exit 1
      ;;
  esac
  sleep 5
done
