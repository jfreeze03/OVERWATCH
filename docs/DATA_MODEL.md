# OVERWATCH Data Model

This file summarizes the Snowflake objects that support the command-intelligence
layer. The full source of truth remains `snowflake/OVERWATCH_MART_SETUP.sql`.

## Command Intelligence

| Object | Type | Purpose |
|---|---|---|
| `OVERWATCH_USAGE_LOG` | Table | Runtime/query event log used for app self-observability summaries. |
| `MART_EXECUTIVE_OBSERVABILITY` | Transient mart | Executive monitoring wall: spend, Cortex, runtime, queue, spill, alerts, actions, storage, cost drivers, query database mix, execution status, and warehouse pressure. |
| `MART_SECTION_COMMAND_BRIEF` | Transient mart | Primary-section command brief parent packet keyed by `BRIEF_ID`: state, headline, summary, resolved scope, source objects, source snapshot, freshness, stale flag, source coverage, confidence, and top signal. |
| `MART_SECTION_COMMAND_METRIC` | Transient mart | Typed metric rows keyed by `BRIEF_ID`, including numeric/text value fields, format, unit, trend points, delta fields, tone, and display order for the compact metric strip. |
| `MART_SECTION_COMMAND_EXCEPTION` | Transient mart | Top signal/exception rows keyed by `BRIEF_ID` with deterministic severity, priority score, impact, owner route, SLA, and route context. |
| `MART_SECTION_COMMAND_ACTION` | Transient mart | Allowlisted route action references keyed by `BRIEF_ID`; action rows provide `ACTION_KEY`, `ROUTE_KEY`, and `CTA_LABEL` instead of arbitrary app state mutation. |
| `OVERWATCH_SECTION_COMMAND_SOURCE_CONFIG` | Table | Authoritative source-trust catalog for each primary section: source key/object, required flag, target freshness, default confidence, and enabled state. |
| `MART_SECTION_COMMAND_SOURCE` | Transient mart | Source-level availability, freshness, stale/data-gap, confidence, and gap-reason rows keyed by `BRIEF_ID`. Missing sources stay missing and cannot be converted into healthy zeros. |
| `MART_SECTION_DECISION_CURRENT` | Transient mart | One-row current decision packet per section/scope/window. App entry queries this table once and parses `DECISION_PACKET` instead of aggregating child tables at first paint. |
| `MART_EXECUTIVE_DECISION_INBOX` | Transient mart | Latest cross-section priority rows derived from current decision findings for executive handoff and routing. |
| `SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS` | Procedure | Populates command brief parent, metric, exception, and action rows for all six primary sections and canonical 1/7/14/30/60/90 day windows. |
| `OVERWATCH_SECTION_COMMAND_BRIEF_REFRESH` | Task | Runs the compact command brief refresh every 15 minutes from scheduled summary marts. |

Decision Brief 3.1 keeps normalized history for audit while serving the app from
`MART_SECTION_DECISION_CURRENT`. Route behavior is allowlisted in code; mart
actions choose an `ACTION_KEY`/`ROUTE_KEY` and cannot inject arbitrary Streamlit
session-state updates. The refresh procedure uses six explicit decision-builder
groups (`executive_decision`, `dba_decision`, `alert_decision`,
`cost_decision`, `workload_decision`, and `security_decision`) so cost movement,
workload failures, Cortex alerts, and security exposure do not leak into
unrelated section state. Source configuration is seeded during setup and remains
operator-owned after deployment; scheduled command-brief refreshes read the
configuration, emit source-health rows into the packet, and publish current
packets append-first instead of clearing `MART_SECTION_DECISION_CURRENT`.

## Enterprise Operating Model

Phase 1 enterprise capabilities connect monitoring work through:

Finding -> Owner -> Trust Level -> Business Impact -> Action -> Value Verified.

| Object | Type | Purpose |
|---|---|---|
| `OVERWATCH_DATA_TRUST_SOURCE` | Table | Source freshness policy, owner route, business impact, and confidence label catalog. |
| `OVERWATCH_DATA_TRUST_STATUS` | Transient table | Source-level trust diagnostics for DBA Control Room explicit loads. |
| `MART_DATA_TRUST_SUMMARY` | Transient mart | Compact trust rollup for Executive Landing first paint. |
| `OVERWATCH_OPERATIONAL_OWNER_MAP` | Table | Operational route fallback by entity type; it is not a generic owner directory. |
| `MART_OPERATIONAL_OWNER_COVERAGE` | Transient mart | Ownership coverage and route gaps for Alert Center and Security Monitoring. |
| `OVERWATCH_VALUE_LEDGER` | Table | Expected savings, actual verified savings, confidence, evidence, owner route, status, and rollback notes. |
| `MART_EXECUTIVE_VALUE_LEDGER` | Transient mart | Executive value rollup. Verified savings and unverified estimates are separate. |
| `OVERWATCH_APP_OBSERVABILITY` | Transient table | App runtime detail from OVERWATCH usage logs. |
| `MART_APP_OBSERVABILITY_SUMMARY` | Transient mart | Compact app health rollup for Executive Landing/DBA Control Room. |
| `SP_OVERWATCH_REFRESH_ENTERPRISE_OPERATING_MODEL` | Procedure | Refreshes the enterprise operating-model summaries from existing OVERWATCH facts and app tables. |

Details and validation steps live in `docs/ENTERPRISE_OPERATING_MODEL.md`.

## Production Readiness

Phase 2A validates whether the deployed OVERWATCH platform is fit for real
production use before larger command-center capabilities are added.

| Object | Type | Purpose |
|---|---|---|
| `OVERWATCH_PRODUCTION_CHECKLIST` | Table | Production validation checklist and runbook catalog. |
| `OVERWATCH_ROLE_READINESS_REQUIREMENT` | Table | Target OVERWATCH roles and legacy compatibility role expectations. |
| `OVERWATCH_PRIVILEGE_READINESS_REQUIREMENT` | Table | Required Snowflake privilege families and manual proof SQL. |
| `OVERWATCH_PRODUCTION_VALIDATION_STATUS` | Transient table | Detail readiness rows for deployment, validation, role, privilege, refresh, data freshness, config, and environment checks. |
| `MART_PRODUCTION_READINESS_SUMMARY` | Transient mart | Compact Production Readiness Dashboard source for first paint. |
| `SP_OVERWATCH_REFRESH_PRODUCTION_READINESS` | Procedure | Refreshes the production readiness summary and detail status rows from OVERWATCH audit/config/mart data. |

Details and manual validation steps live in `docs/PRODUCTION_READINESS.md`.

## Executive Scorecard

Phase 2B adds a leadership scorecard that answers whether the Snowflake platform
is healthy, what is worsening, what needs action, who owns the risk, and what
value/risk is tied to the signal.

| Object | Type | Purpose |
|---|---|---|
| `OVERWATCH_EXECUTIVE_SCORECARD_CONFIG` | Table | Score catalog, thresholds, owner routes, driver sources, and default recommended actions. |
| `OVERWATCH_EXECUTIVE_SCORECARD_HISTORY` | Transient table | Score snapshots and driver history for explicit Load panels. |
| `MART_EXECUTIVE_SCORECARD_SUMMARY` | Transient mart | Compact first-paint Executive Landing scorecard source. |
| `SP_OVERWATCH_REFRESH_EXECUTIVE_SCORECARD` | Procedure | Refreshes all six leadership scores from existing OVERWATCH marts and app tables. |

Details and manual validation steps live in `docs/EXECUTIVE_SCORECARD.md`.

## Executive Forecasting

| Object | Type | Purpose |
| --- | --- | --- |
| `OVERWATCH_FORECAST_CONFIG` | Table | Forecast catalog, owner route, methodology, confidence rule, source object list, and recommended action defaults. |
| `OVERWATCH_FORECAST_HISTORY` | Transient table | Forecast snapshots and historical driver rows for explicit Load panels. |
| `MART_EXECUTIVE_FORECAST_SUMMARY` | Transient mart | Compact first-paint Executive Landing forecast summary. |
| `SP_OVERWATCH_REFRESH_FORECASTING` | Procedure | Refreshes leadership forecasts from existing OVERWATCH cost, storage, query, task, and procedure facts. |

Details and manual validation steps live in `docs/FORECASTING.md`.

## Change Intelligence

Phase 2D normalizes Snowflake changes and possible downstream correlations so
operators can review what changed before a cost, performance, security, or alert
issue without claiming unsupported root cause.

| Object | Type | Purpose |
| --- | --- | --- |
| `OVERWATCH_CHANGE_RULE` | Table | Change category catalog, risk label, owner route, confidence label, and default business impact. |
| `OVERWATCH_CHANGE_EVENT` | Transient table | Normalized warehouse, role, grant, task, procedure, network policy, integration, object, and security-sensitive changes. |
| `OVERWATCH_CHANGE_CORRELATION` | Transient table | Explicit-load possible correlation rows between changes and later alert, cost, security, or workload signals. |
| `MART_CHANGE_INTELLIGENCE_SUMMARY` | Transient mart | Compact first-paint recent-change and risk summary for Executive Landing. |
| `SP_OVERWATCH_REFRESH_CHANGE_INTELLIGENCE` | Procedure | Refreshes change events, possible correlations, and summary rows from existing OVERWATCH marts. |

Details and manual validation steps live in `docs/CHANGE_INTELLIGENCE.md`.

## Closed Loop Operations

Phase 2E makes actions auditable from finding through approval, review plan,
verification, measured value, and closure. It does not execute remediation.

| Object | Type | Purpose |
| --- | --- | --- |
| `OVERWATCH_ACTION_WORKFLOW` | Transient table | Action lifecycle rows with finding, source telemetry, owner route, business impact, risk, approval status, review text, rollback guidance, verification, savings, evidence, and closure state. |
| `OVERWATCH_ACTION_APPROVAL` | Transient table | Approval proof rows with status, approver, approval timestamp, risk, owner route, and recommended action. |
| `OVERWATCH_ACTION_EXECUTION_PLAN` | Transient table | Review-gated SQL/action text, rollback guidance, dangerous-action flag, and explicit in-app execution block. |
| `OVERWATCH_ACTION_VERIFICATION` | Transient table | Verification status, verification window, evidence, expected savings, and actual verified savings. |
| `OVERWATCH_ACTION_EVIDENCE` | Transient table | Evidence trail for workflow, source telemetry, business impact, rollback, verification, and closure context. |
| `MART_CLOSED_LOOP_OPERATIONS_SUMMARY` | Transient mart | Compact first-paint action, approval, verification, closure, owner-gap, and value summary. |
| `SP_OVERWATCH_REFRESH_CLOSED_LOOP_OPERATIONS` | Procedure | Refreshes closed-loop operations rows from existing OVERWATCH alert, action, value, and dry-run sources without executing remediation. |

Details and manual validation steps live in `docs/CLOSED_LOOP_OPERATIONS.md`.

## Command Center

Phase 2F correlates cost, performance, alerts, ownership, trust, security,
change intelligence, forecasts, scorecards, value, and closed-loop action state
into deterministic root-cause candidate findings. It does not execute
remediation.

| Object | Type | Purpose |
| --- | --- | --- |
| `OVERWATCH_COMMAND_CENTER_QUESTION` | Table | Investigation catalog for cost spike, warehouse slow, recent change, failure/SLA, security risk, and executive risk questions. |
| `OVERWATCH_COMMAND_CENTER_FINDING` | Transient table | Root-cause candidate findings with evidence, owner, business/technical impact, related signals, recommendation, risk, execution-plan reference, expected value/risk, and verification path. |
| `OVERWATCH_COMMAND_CENTER_EVIDENCE` | Transient table | Evidence rows tied to each finding and source object. |
| `OVERWATCH_COMMAND_CENTER_RECOMMENDATION` | Transient table | Review-gated recommendations tied to closed-loop execution plan references when available. |
| `MART_COMMAND_CENTER_SUMMARY` | Transient mart | Compact first-paint summary by investigation type. |
| `SP_OVERWATCH_REFRESH_COMMAND_CENTER` | Procedure | Refreshes Command Center findings, evidence, recommendations, and summaries from existing OVERWATCH marts without executing remediation. |

Details and manual validation steps live in `docs/COMMAND_CENTER.md`.

## Reconciliation

| Object | Type | Purpose |
|---|---|---|
| `OVERWATCH_RECON_CONFIG` | Table | Metadata-driven schema/database/table comparison rules. |
| `OVERWATCH_RECON_RUN` | Table | Count/hash/diff run results for configured reconciliation checks. |
| `OVERWATCH_SCHEMA_DIFF_RESULT` | Table | Object-level differences and generated DDL for missing objects. |

The app's interactive Schema Compare uses live metadata on demand rather than a
first-paint mart: `SHOW OBJECTS` supplies all visible schema objects, while
`INFORMATION_SCHEMA.COLUMNS` supplies column drift. Interactive Data Compare is
also on demand and moves from row count to `HASH_AGG`, bucket isolation, and
forensic diff SQL. Both tools generate persistence SQL for their run evidence;
DBAs review and execute that SQL when the compare should become release or
incident proof.

## Cost Monitoring

| Object | Type | Purpose |
|---|---|---|
| `FACT_COST_DAILY` | Transient fact | Daily Snowflake service-cost facts for the cost wall and trend charts. |
| `FACT_CORTEX_DAILY` | Transient fact | Cortex AI request, credit, and estimated-dollar facts. |
| `FACT_COST_MONITORING_SIGNAL` | Transient fact | Ranked cost movement and Cortex signals consumed by Cost & Contract and Alert Center. |
| `FACT_COST_INCIDENT_TIMELINE` | Transient fact | Ordered cost incident timeline for root cause, alerting, and action status. |

## Alert Operations

| Object | Type | Purpose |
|---|---|---|
| `ALERT_EVENTS` | Table | Durable alert lifecycle event table used by Alert Center command lanes. Includes `COMPANY` and `ENVIRONMENT` for ALFA/Trexis-scoped alert routing where the source can provide it. |
| `ALERT_NATIVE_OBJECT_REGISTRY` | Table | Reviewed native Snowflake alert candidates with generated create/drop SQL. Candidates are disabled by default. |
| `ALERT_NATIVE_DEPLOYMENT_REVIEW_V` | View | Review-only native alert deployment state, generated SQL presence, validation SQL, and next operator step. |
| `ALERT_REMEDIATION_POLICY` | Table | Recommend/status-review policy catalog for future guarded remediation. |
| `ALERT_REMEDIATION_DRY_RUN` | Table | Audit table for proposed remediation dry-runs before any execution path exists. |
| `SP_OVERWATCH_STAGE_ALERT_REMEDIATION_DRY_RUN` | Procedure | Stages remediation dry-run rows from alert events and policy rows; it does not execute corrective SQL. |
| `ALERT_ACKNOWLEDGEMENTS`, `ALERT_NOTIFICATION_LOG`, `ALERT_REMEDIATION_LOG` | Tables | Alert acknowledgement, delivery, and remediation audit history. |

## Native Snowflake Proof Contracts

| Source | Purpose |
|---|---|
| `SNOWFLAKE.ACCOUNT_USAGE.DATA_METRIC_FUNCTION_REFERENCES` | Registers Snowflake DMF data-quality checks, schedules, states, and stale/failed runs where DMFs are enabled. |
| `SHOW ALERTS IN ACCOUNT` / `INFORMATION_SCHEMA.ALERT_HISTORY` | Proves native Snowflake ALERT objects exist, are scheduled, and have recent run history. |
| `OVERWATCH_USAGE_LOG` and optional legacy query-tag telemetry | Measures OVERWATCH's own query count, failures, latency, and section attribution without first-paint `ACCOUNT_USAGE` scans. |
| `SNOWFLAKE.ORGANIZATION_USAGE.METERING_DAILY_HISTORY` | Optional ORGADMIN rollup for multi-account cost when organization privileges exist. |
