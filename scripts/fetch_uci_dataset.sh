#!/usr/bin/env bash
#
# Fetch the UCI Online Retail dataset and convert it to CSV.
#
# The UCI host serves these files slowly, advertises no Content-Length and does
# not support byte ranges, so a truncated transfer looks like a successful one
# to curl and cannot be resumed. The download is therefore retried from the
# start and every attempt is verified by opening the file as a ZIP container
# (both .xlsx and .zip are ZIP containers) before it is accepted.
#
# Usage: scripts/fetch_uci_dataset.sh [target_dir]
set -euo pipefail

TARGET_DIR="${1:-data/uci-download}"
WORKBOOK="$TARGET_DIR/Online Retail.xlsx"
ARCHIVE="$TARGET_DIR/online_retail.zip"
CSV_OUT="data/online_retail.csv"

XLSX_URL="https://archive.ics.uci.edu/ml/machine-learning-databases/00352/Online%20Retail.xlsx"
ZIP_URL="https://archive.ics.uci.edu/static/public/352/online+retail.zip"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-30}"

mkdir -p "$TARGET_DIR" data

# Both .xlsx and .zip are ZIP containers, so one check validates either.
container_is_valid() {
  python3 -I - "$1" <<'PY'
import sys
import zipfile

try:
    with zipfile.ZipFile(sys.argv[1]) as archive:
        if archive.testzip() is not None:
            sys.exit(1)
        if not archive.namelist():
            sys.exit(1)
except Exception as failure:
    print(f"invalid: {failure}", file=sys.stderr)
    sys.exit(1)
PY
}

download_attempt() {
  local url="$1" destination="$2" temporary="$2.part"
  rm -f "$temporary"
  # --speed-time/--speed-limit abandon a transfer that has stalled, rather than
  # holding the connection open for the full --max-time.
  curl -fL --http1.1 --no-progress-meter --max-time 2400 \
       --connect-timeout 30 --speed-time 120 --speed-limit 512 \
       -o "$temporary" "$url" || return 1
  if container_is_valid "$temporary" 2>/dev/null; then
    mv -f "$temporary" "$destination"
    return 0
  fi
  echo "  transfer was truncated ($(stat -c%s "$temporary" 2>/dev/null || echo 0) bytes)" >&2
  rm -f "$temporary"
  return 1
}

if [ -f "$WORKBOOK" ] && container_is_valid "$WORKBOOK" 2>/dev/null; then
  echo "workbook already present: $(stat -c%s "$WORKBOOK") bytes"
else
  rm -f "$ARCHIVE"
  obtained=0
  for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
    echo "attempt $attempt: downloading the workbook directly"
    if download_attempt "$XLSX_URL" "$WORKBOOK"; then
      obtained=1
      break
    fi
    echo "attempt $attempt: downloading the archive instead"
    if download_attempt "$ZIP_URL" "$ARCHIVE"; then
      python3 -I - "$ARCHIVE" "$TARGET_DIR" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    archive.extractall(sys.argv[2])
    print("extracted:", ", ".join(archive.namelist()))
PY
      obtained=1
      break
    fi
    sleep 5
  done

  if [ "$obtained" -ne 1 ]; then
    echo "could not obtain a complete copy of the dataset from archive.ics.uci.edu" >&2
    exit 1
  fi
fi

FOUND="$(find "$TARGET_DIR" -maxdepth 1 -iname '*.xlsx' | head -1)"
if [ -z "$FOUND" ]; then
  echo "no .xlsx found in $TARGET_DIR" >&2
  exit 1
fi

echo "converting $FOUND to $CSV_OUT"
python3 -I scripts/xlsx_to_csv.py "$FOUND" "$CSV_OUT"
ls -l "$CSV_OUT"
