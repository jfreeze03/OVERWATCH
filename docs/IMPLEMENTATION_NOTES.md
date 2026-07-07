# OVERWATCH Implementation Notes

This file records user-facing implementation changes that should be documented
outside the Streamlit app UI.

## 2026-06-17 - App Shell Phase 1 Refactor

- `.overwatch_final/app.py` is now a thin Streamlit entrypoint that only sets
  page config and calls `shell.render_app()`.
- App-shell responsibilities were split into explicit modules:
  `shell.py`, `navigation.py`, `access_control.py`, `filters.py`,
  `layout.py`, `runtime_state.py`, `refresh.py`, and `section_dispatch.py`.
- Follow-up hardening centralized shell-owned session keys in
  `runtime_state.py`, replaced the sidebar positional return tuple with a
  `SidebarState` contract, and prevents the shell from probing Snowflake while
  idle query pause is active.
- The hardening pass expanded `SidebarState` to include active company,
  connection availability, and idle state; moved shared section-navigation keys
  to constants; and added tests blocking raw shell-layer `st.session_state`
  access outside `runtime_state.py`.
- Streamlit-in-Snowflake packaging was updated so `.overwatch_final/snowflake.yml`
  includes the new top-level shell modules.
- `sections.__init__` now re-exports the top-level section dispatcher for
  backward compatibility with existing internal imports.
- `docs/APP_ARCHITECTURE.md` records the Phase 1 refactor map, module
  responsibilities, migration summary, manual validation points, and
  production-readiness checklist.
- `docs/SESSION_STATE_CONTRACT.md` records persistent, transient, filter, cache,
  and known-exception state ownership.

## 2026-06-17 - Alert Operations Review Workflow

- Added `snowflake/OVERWATCH_ALERT_OPERATIONS_REVIEW.sql` as a read-only
  worksheet script for object readiness, native alert promotion state,
  threshold/baseline tuning candidates, ALFA/Trexis company-scope quality, and
  dynamic-table compatibility reminders.
- `Alert Center > Detection Catalog` now shows the threshold tuning review plan
  and a native alert operations checklist next to the native registry and
  deployment review rows.
- `Alert Center > Delivery & Automation` now shows operations readiness,
  loaded-alert threshold tuning, and company-scope readiness before the
  remediation policy, dry-run, delivery, and action-queue tables.
- Native alert promotion is still manual. The app does not execute promotion
  SQL, enable native alerts, or run corrective automation.
- Threshold changes should be made from Snowflake evidence after comparing
  current value, baseline, company split, workflow route, and Snowflake Admin/Cost
  Management context where appropriate.

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
  `get_user_company_filter_clause()`. Trexis-only users with active `%TRXS%`
  role grants stay in the Trexis view even when the username itself is not
  enough; mixed ALFA/Trexis administrators remain in ALFA user metrics so admin
  grants do not remove them from ALFA operator views.
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
- Alert Center `Detection Catalog` can now load the live native alert registry,
  and `Delivery & Automation` can load registry, remediation policy, and
  dry-run audit rows in the same bounded refresh as alert history.
- Native alert candidates now include warehouse credit spike and user/query
  behavior anomaly checks in addition to Cortex spend, privileged grants, and
  task failures. These candidates remain disabled by default and review-only.

## 2026-06-17 - Dynamic Table Audit Artifact

- Added `snowflake/OVERWATCH_DYNAMIC_TABLE_SECURE_VIEW_AUDIT.sql` as a
  read-only pre-reset/pre-import scan for side-built DDLs and old deployed
  objects.
- The audit now emits generated drop SQL plus table/procedure/task rewrite
  stubs for any Dynamic Table collision or Dynamic Table -> secure view
  dependency it finds. These are review stubs, not executable finished mart
  logic; the source query must still be rewritten into the approved
  `SP_OVERWATCH_*` pattern.
- The deployable setup still contains no Dynamic Tables or Secure Views. If a
  future mart is proposed as a Dynamic Table, rewrite it as a physical table
  loaded by `SP_OVERWATCH_*` and scheduled by an `OVERWATCH_*` task before it
  enters `OVERWATCH_MART_SETUP.sql`.

## 2026-06-17 - Native Alert Deployment Review

- `ALERT_EVENTS` now has explicit `COMPANY` and `ENVIRONMENT` columns so
  materialized alerts and native alert events can preserve ALFA/Trexis scope
  instead of relying only on fallback inference.
- Native alert generated SQL now uses company-labeled OVERWATCH marts where
  possible: `FACT_CORTEX_DAILY`, `FACT_WAREHOUSE_HOURLY`,
  `FACT_GRANT_DAILY`, `FACT_TASK_RUN`, and `FACT_QUERY_DETAIL_RECENT`.
- `snowflake/OVERWATCH_NATIVE_ALERT_DEPLOYMENT.sql` creates
  `ALERT_NATIVE_DEPLOYMENT_REVIEW_V` and
  `SP_OVERWATCH_STAGE_ALERT_REMEDIATION_DRY_RUN`. The script does not execute
  generated alert SQL and does not perform remediation; it stages dry-run rows
  for review.
- The native warehouse credit alert template now uses the deployed mart column
  `CREDITS_USED`; do not use `METERED_CREDITS` against
  `FACT_WAREHOUSE_HOURLY`.

## 2026-06-17 - Alert Center Operator Workflow Polish

- `Alert Center > Command Center` now renders an operator workflow spine before
  the broad incident/category tables. The workflow shows detect, triage, route,
  notify, dry-run, and close steps with the loaded count, current state, and
  next DBA move.
- The highest-priority incident now renders as a compact decision packet with
  what fired, why it matters, owner/route readiness, evidence, and automation
  boundary. This keeps the first DBA action visible without opening additional
  panes.
- Cost/Cortex, Reliability, and Security alert lanes now show a first-response
  path before their detailed workbench: confirm signal, open the owning
  monitoring workflow, capture evidence, and respect the remediation boundary.
- The workflow remains review/status focused. It does not execute remediation
  SQL, change native alert status, or add new Snowflake objects.

## 2026-06-17 - Advisor And Company-Scope Polish

- `Warehouse Health > Optimization Advisor` now labels idle and right-sizing
  rows by value type and shows estimated monthly savings where a downsize/idle
  candidate has a defensible calculation. Pressure/upsize rows remain
  reliability/performance items, not savings claims.
- Stored procedure advisor rows now include Alert Center Reliability handoff
  columns so procedure runtime/cost/orchestration issues route consistently.
- `Cost & Contract` coverage/trust boards now call out the Trexis role/user
  boundary so ALFA/Trexis cost review can separate exact warehouse/database
  scope from user/role allocation and account-wide Snowflake service totals.

## 2026-06-17 - Production Startup Cleanup

- App startup should not use development hot-reload guards for config, utils,
  theme, section guidance, display helpers, or workflow helpers.
- Theme version state remains only to preserve the selected Snowflake Dark/White
  theme across sessions and Streamlit reruns.

## 2026-06-17 - Enterprise Operating Model Phase 1

- Added mart-first Phase 1 enterprise capabilities around:
  `Finding -> Owner -> Trust Level -> Business Impact -> Action -> Value Verified`.
- New Snowflake objects live in `snowflake/OVERWATCH_MART_SETUP.sql` and are
  documented in `docs/ENTERPRISE_OPERATING_MODEL.md`.
- Executive Landing reads compact trust, ownership, value, and app health
  summaries only. DBA Control Room and Cost & Contract detail evidence require
  explicit Load buttons.
- `MART_EXECUTIVE_VALUE_LEDGER` separates verified savings from unverified
  estimates. Unverified expected savings must not be counted as realized value.
- `OVERWATCH_OPERATIONAL_ROUTE_MAP` is an operational route fallback by entity
  type. It is not a generic owner directory or governance approval workflow.
- `SP_OVERWATCH_REFRESH_ENTERPRISE_OPERATING_MODEL` does not execute
  remediation. It only summarizes existing OVERWATCH facts, app logs, action
  queue rows, and ledger rows.

## 2026-06-18 - Change Intelligence Phase 2D

- Added a mart-first Change Intelligence layer that normalizes warehouse, role,
  grant, task, procedure, network policy, integration, object, and
  security-sensitive changes.
- Executive Landing reads only `MART_CHANGE_INTELLIGENCE_SUMMARY` for first
  paint. DBA Control Room, Cost & Contract, Workload Operations, Security
  Monitoring, and Alert Center load event/correlation evidence only after an
  explicit Load button.
- Correlation rows are labeled `possible correlation`; OVERWATCH does not claim
  root cause unless separate proof exists.
- `SP_OVERWATCH_REFRESH_CHANGE_INTELLIGENCE` writes OVERWATCH mart rows only and
  does not execute remediation.

## 2026-06-18 - Closed Loop Operations Phase 2E

- Added a mart-first Closed Loop Operations layer for:
  detect -> analyze -> recommend -> approve -> review plan -> verify ->
  measure -> close.
- Executive Landing reads only `MART_CLOSED_LOOP_OPERATIONS_SUMMARY` for first
  paint. DBA Control Room, Alert Center, Cost & Contract, Workload Operations,
  and Security Monitoring load action workflow, review SQL/action text,
  evidence, and verification detail only after explicit Load buttons.
- `OVERWATCH_ACTION_EXECUTION_PLAN` stores review-gated SQL/action text and
  marks in-app execution as blocked. OVERWATCH does not execute generated
  `ALTER`, `CREATE`, `DROP`, `GRANT`, `REVOKE`, `SUSPEND`, or `RESUME`
  statements.
- Expected savings and forecasted savings remain separate from actual verified
  savings. Actual verified savings require post-action telemetry and evidence.

## 2026-06-18 - Command Center Phase 2F

- Added a mart-first Command Center that correlates cost, performance, alerts,
  ownership, trust, security, change intelligence, forecasting, scorecards,
  value ledger, and closed-loop operations into deterministic findings.
- Executive Landing reads only `MART_COMMAND_CENTER_SUMMARY` for first paint.
  DBA Control Room, Alert Center, Cost & Contract, Workload Operations, and
  Security Monitoring load finding/evidence/recommendation detail only after
  explicit Load buttons.
- Findings use conservative wording: `root-cause candidate`, `likely driver`,
  and `possible correlation`. The app does not claim causality from timing or
  entity proximity alone.
- Command Center recommendations remain review-gated through Closed Loop
  Operations references when available. The refresh procedure does not execute
  remediation SQL or dangerous Snowflake actions.
- Non-AI explanations are required. Optional AI/Cortex summarization can be
  added later only as a clearly labeled assistive layer, not a first-paint
  dependency.
