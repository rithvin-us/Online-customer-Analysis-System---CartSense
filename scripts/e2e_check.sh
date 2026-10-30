#!/usr/bin/env bash
#
# Thin wrapper so `make test-e2e` has one entry point. The check itself is
# Python, in scripts/e2e_check.py.
set -euo pipefail
cd "$(dirname "$0")/.."

API_PORT="$(grep -E '^API_HOST_PORT=' .env | cut -d= -f2)"
exec python3 -I scripts/e2e_check.py --api "http://localhost:${API_PORT}" "$@"
