#!/usr/bin/env bash
#
# Deploy the OVERWATCH mart in dependency-safe order.
#
# Runs the numbered active deployment files (01..07) in a single snowsql invocation so they
# share session context (USE DATABASE/SCHEMA established by 01). This is exactly
# equivalent to running ../OVERWATCH_MART_SETUP.sql.
#
# Usage:
#   ./run_mart_setup.sh <snowsql-connection-name>
#
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <snowsql-connection-name>" >&2
  exit 2
fi

CONNECTION="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v snowsql >/dev/null 2>&1; then
  echo "error: snowsql not found on PATH" >&2
  exit 1
fi

# Deterministic numeric order.
FILES=()
while IFS= read -r f; do
  FILES+=("$f")
done < <(find "$SCRIPT_DIR" -maxdepth 1 -name '[0-9][0-9]_*.sql' | sort)

if [[ ${#FILES[@]} -eq 0 ]]; then
  echo "error: no numbered .sql files found in $SCRIPT_DIR" >&2
  exit 1
fi

echo "Deploying ${#FILES[@]} files in order using connection '$CONNECTION':"
for f in "${FILES[@]}"; do
  echo "  - $(basename "$f")"
done

# Concatenate in order and pipe through a single session so USE context carries
# across files (matching the monolith's behavior).
cat "${FILES[@]}" | snowsql -c "$CONNECTION" -f /dev/stdin

echo "OVERWATCH mart setup complete."
