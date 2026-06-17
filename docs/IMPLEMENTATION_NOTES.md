# OVERWATCH Implementation Notes

This file records user-facing implementation changes that should be documented
outside the Streamlit app UI.

## 2026-06-17 - COST_MONITOR Formula Audit

- Added `docs/COST_MONITOR_FORMULA_AUDIT.md` to compare OVERWATCH cost
  metrics against the original `COST_MONITOR_DB.txt` dashboard formulas.
- `DBA Control Room > Cost Formula Audit` now shows source-dashboard formula,
  OVERWATCH formula, parity status, measurement basis, notes, and next-review
  guidance.
- Service spend categorization now keeps Openflow, Snowpark Container Services,
  automatic clustering, replication, and serverless/task service rows out of
  vague `Other` or warehouse-compute buckets.
- Known follow-ups are storage-class coverage for hybrid/archive storage,
  optional Cortex sub-service detail panes, and an annual all-service projection
  if the original dashboard view is needed again.

## 2026-06-17 - Advisor UX Polish

- `Workload Operations > Stored procedures` now has a top-level Stored
  Procedure Advisor load path that hydrates operations and SLA/cost telemetry
  through explicit user action before showing ranked decisions.
- Stored procedure advisor rows include decision, review stage, impact summary,
  verification expectation, and execution guardrail fields so reviewers can
  decide what to inspect before reruns, redeploys, or warehouse changes.
- `Cost & Contract > Warehouse Advisor` now exposes action posture, savings
  type, expected verification impact, and do-not-execute guardrails while
  preserving the no-generated-DDL boundary.
- Warehouse setting changes remain routed to `DBA Control Room > Admin >
  Warehouse Settings`, where preview, typed confirmation, rollback context, and
  audit logging stay guarded.

## 2026-06-17 - Warehouse Advisor Boundary

- `Cost & Contract > Recommendations and action queue > Warehouse Advisor` is
  the recommendation surface for warehouse tuning. It ranks auto-suspend,
  downsize, pressure, timeout, and guardrail findings with estimated monthly and
  annual savings where the savings can be quantified.
- Warehouse Advisor calibration lives in `config.WAREHOUSE_ADVISOR_CONFIG`.
  The default assumptions are directional: auto-suspend recovery bands, one-step
  downsize recovery rate, queue/spill/p95 pressure thresholds, minimum monthly
  run-rate, and verification window.
- The Warehouse Advisor must not present generated `ALTER WAREHOUSE` scripts,
  setup DDL, or execution-ready SQL. It should show the recommendation, current
  signal, estimated savings, verified savings when available, safe next step,
  validation telemetry, and the Admin workflow route.
- State-changing warehouse changes belong in `DBA Control Room > Admin >
  Warehouse Settings`, where preview, typed confirmation, rollback context, and
  audit logging remain guarded.
- Savings shown by the advisor are estimates until a post-change complete
  telemetry window confirms lower credits without worse queue, spill, p95, or
  failure behavior.

## 2026-06-17 - Secure-View Mart Boundary

- OVERWATCH mart facts remain task/procedure-loaded physical tables. Do not
  replace those facts with Dynamic Tables when any source path can include a
  secure view.
- `snowflake/OVERWATCH_MART_SETUP.sql` is the single deployable mart setup file,
  and `snowflake/OVERWATCH_MART_DROP.sql` is the reset/drop script for fresh
  rebuilds.
- Any future mart rename, merge, or retirement must update setup SQL, drop SQL,
  refresh procedures, validation docs, and mart object review together.

## 2026-06-17 - Stored Procedure Advisor Boundary

- `Workload Operations > Stored procedures` is the Stored Procedure Advisor
  surface. It ranks runtime regressions, cost regressions, orchestration gaps,
  and child-query optimization signals.
- The advisor may queue findings with safe next action and proof telemetry. It
  must not rerun procedures, redeploy procedure code, or change warehouse
  settings directly.
- Procedure cost is estimated unless procedure facts or `ROOT_QUERY_ID`
  child-query attribution are available; the UI should label that confidence.

## 2026-06-17 - Production Startup Cleanup

- App startup should not use development hot-reload guards for config, utils,
  theme, section guidance, display helpers, or workflow helpers.
- Theme version state remains only to preserve the selected Snowflake Dark/White
  theme across sessions and Streamlit reruns.
