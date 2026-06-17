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
- Storage-class coverage, Cortex service detail probing, and annual all-service
  projection were added after this audit. Keep `docs/COST_MONITOR_FORMULA_AUDIT.md`
  current whenever a formula or source changes.

## 2026-06-17 - Cost Allocation And Service Coverage

- `Storage Monitor` and `FACT_STORAGE_DAILY` include standard database/stage/
  failsafe storage, hybrid table storage, archive cool storage, and archive cold
  storage. Hybrid/archive telemetry is account-level and should be shown in ALL
  scope unless a documented allocation basis exists.
- `Cost & Contract > Forecast` keeps the near-term warehouse forecast and adds
  an account-wide annual service projection from completed-window
  `METERING_HISTORY` so OVERWATCH can be reconciled to Snowflake Admin/Cost
  Management totals.
- `AI & Cortex Monitor > Service Details` probes Cortex service usage history
  views on explicit load. It renders detail only when the current role can see
  the view and required columns.
- ALFA/Trexis cost allocation uses warehouse and database naming first, then
  user naming and active role membership where telemetry exposes them. Roles
  containing `TRXS` classify as Trexis in live cost queries, user-scoped Cortex
  paths, and mart loaders.
- User/auth/grant surfaces now use role-aware company filtering through
  `get_user_company_filter_clause()` so Trexis users with active `%TRXS%` role
  grants stay in the Trexis view even when the username itself is not enough.
- `Cost Center > Reconciliation` now includes a Snowflake Admin/Cost Management
  bridge from account-level `METERING_HISTORY` and official
  `WAREHOUSE_METERING_HISTORY`. The bridge intentionally separates account-wide
  totals from company-scoped OVERWATCH warehouse and allocated query totals.
- `docs/COMPANY_SCOPE_AUDIT.md` records which sections are exact,
  directional/allocated, or account-wide only for ALFA/Trexis views.
- Account-wide service rows from `METERING_HISTORY` remain reconciliation totals.
  Do not force company splits for Snowflake services or storage classes unless
  there is a defensible allocation rule documented outside the app.

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

## 2026-06-17 - CLAUDE-UI Alert/SP Review

- `docs/CLAUDE_UI_ALERT_PROCEDURE_REVIEW.md` inventories the latest CLAUDE-UI
  stored procedure and alert changes and maps them to OVERWATCH coverage.
- `docs/ALERTING_AUTOMATION_ROADMAP.md` defines the broader alert taxonomy,
  cost/system/user-behavior anomaly plan, Snowflake-native alerting boundaries,
  and future guarded remediation model.
- Port detection ideas, not the smaller CLAUDE-UI alert framework. OVERWATCH
  should keep its alert lifecycle, action queue, remediation log, rule catalog,
  and mart-first DBA monitoring model.
- Before adding more scheduled detections, decide whether new alert events write
  directly to `ALERT_EVENTS` or continue through `OVERWATCH_ALERTS` plus
  materialization for compatibility.

## 2026-06-17 - Alert Center Domain Lanes

- Alert Center is now organized around `Command Center`, `Cost & Behavior`,
  `Reliability`, `Security`, `Detection Catalog`, `Delivery & Automation`, and
  `Suppression Windows`. Older saved view names normalize into the new command
  or automation views.
- Cost/Cortex, workload reliability, security, and executive sections can show
  loaded Alert Center signals from `st.session_state["alert_center_data"]`.
  These cross-section alert strips are read-only and do not trigger additional
  Snowflake queries.
- Cortex spend is now first-class in alert setup: Python fallback rules,
  command-center threshold seeds, the Snowflake setup seed, and the detection
  catalog include Cortex spend spike/quota drift coverage.
- Keep future alert UI additions domain-focused. Prefer a single filtered
  evidence workbench over adding more inbox/digest/history-style panes.

## 2026-06-17 - Alert Drilldowns And Native Registry

- Loaded alert strips now carry operator route metadata: destination section,
  destination workflow, Alert Center lane, drilldown hint, and automation
  readiness. Executive Landing, Cost & Contract, Workload Operations, Security
  Monitoring, and Alert Center domain lanes use that metadata for quick-open
  buttons.
- `Cost & Contract` has a dedicated loaded Cortex/spend alert drilldown that
  explains why a signal fired, where to open the evidence, the safe first
  action, and the automation boundary.
- Fresh setup now creates `ALERT_NATIVE_OBJECT_REGISTRY`,
  `ALERT_REMEDIATION_POLICY`, and `ALERT_REMEDIATION_DRY_RUN`. These objects
  are registry/policy/audit contracts only; native Snowflake alerts remain
  disabled candidates until a DBA reviews and deploys generated SQL outside the
  app.
- All seeded remediation policies default to recommend/status-review behavior.
  Cortex access changes, privileged grants, task reruns, and warehouse timeout
  changes must keep before-state, rollback, verification, and owner review
  evidence before any execution path is considered.

## 2026-06-17 - Production Startup Cleanup

- App startup should not use development hot-reload guards for config, utils,
  theme, section guidance, display helpers, or workflow helpers.
- Theme version state remains only to preserve the selected Snowflake Dark/White
  theme across sessions and Streamlit reruns.
