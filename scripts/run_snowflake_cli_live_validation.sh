#!/usr/bin/env bash
set -euo pipefail

connection="${1:-${OVERWATCH_SNOWFLAKE_CLI_CONNECTION:-}}"
profile="${OVERWATCH_LAUNCH_PROFILE:-internal_live}"
company="${OVERWATCH_COMPANY:-ALL}"
environment="${OVERWATCH_ENVIRONMENT:-ALL}"
window_days="${OVERWATCH_WINDOW_DAYS:-8}"
credit_price="${OVERWATCH_CREDIT_PRICE:-3.68}"

if ! command -v snow >/dev/null 2>&1; then
  echo "Snowflake CLI executable 'snow' is not available on PATH." >&2
  exit 1
fi

mkdir -p artifacts/snowflake_validation artifacts/launch_readiness

args=(
  -m tools.contracts.snowflake_cli_live_validation
  --profile "$profile"
  --company "$company"
  --environment "$environment"
  --window-days "$window_days"
  --credit-price "$credit_price"
)

if [[ -n "$connection" ]]; then args+=(--connection "$connection"); fi
if [[ -n "${OVERWATCH_SNOWFLAKE_VALIDATION_DATABASE:-}" ]]; then args+=(--database "$OVERWATCH_SNOWFLAKE_VALIDATION_DATABASE"); fi
if [[ -n "${OVERWATCH_SNOWFLAKE_VALIDATION_SCHEMA:-}" ]]; then args+=(--schema "$OVERWATCH_SNOWFLAKE_VALIDATION_SCHEMA"); fi
if [[ -n "${OVERWATCH_SNOWFLAKE_VALIDATION_WAREHOUSE:-}" ]]; then args+=(--warehouse "$OVERWATCH_SNOWFLAKE_VALIDATION_WAREHOUSE"); fi
if [[ -n "${OVERWATCH_SNOWFLAKE_VALIDATION_ROLE:-}" ]]; then args+=(--role "$OVERWATCH_SNOWFLAKE_VALIDATION_ROLE"); fi
if [[ "${OVERWATCH_RUN_FAST_REFRESH_VALIDATION:-0}" == "1" ]]; then args+=(--run-fast-refresh); fi
if [[ "${OVERWATCH_RUN_FULL_REFRESH_DRY_RUN:-0}" == "1" ]]; then args+=(--run-full-refresh-dry-run); fi
if [[ "${OVERWATCH_SKIP_REFRESH_VALIDATION:-1}" == "1" ]]; then args+=(--skip-refresh); fi

python "${args[@]}"

echo "Snowflake CLI validation artifacts:"
echo "  artifacts/snowflake_validation/snowflake_cli_*.json"
echo "  artifacts/launch_readiness/snowflake_cli_live_gate_results.json"
