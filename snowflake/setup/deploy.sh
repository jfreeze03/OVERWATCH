#!/usr/bin/env bash
#
# Deploy the OVERWATCH mart in order, one file per snowsql invocation.
#
# Usage:
#   ./deploy.sh [snowsql_connection_name]
#
# With no argument the default snowsql connection is used. Running these files
# in numeric order is equivalent to deploying ../OVERWATCH_MART_SETUP.sql.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONN="${1:-}"

if ! command -v snowsql >/dev/null 2>&1; then
  echo "error: snowsql is not installed or not on PATH" >&2
  exit 1
fi

CONN_ARGS=()
if [[ -n "${CONN}" ]]; then
  CONN_ARGS=(-c "${CONN}")
fi

for f in "${DIR}"/0[1-9]_*.sql; do
  echo ">>> Running $(basename "${f}")"
  snowsql "${CONN_ARGS[@]}" -f "${f}"
done

echo "OVERWATCH mart setup complete."
