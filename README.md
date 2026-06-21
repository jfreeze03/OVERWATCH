# OVERWATCH

OVERWATCH is an enterprise Snowflake Command Center and production Streamlit
monitor for Snowflake DBA operations. It brings executive observability, DBA
triage, alerts, cost monitoring, workload operations, security telemetry,
governance readiness, ownership routing, and value verification into one
DBA-owned workflow.

The app is intentionally mart-first. Snowflake account telemetry is collected
into compact OVERWATCH facts by scheduled tasks, and the Streamlit app reads
those facts before it falls back to live account views. This keeps the app fast,
keeps Snowflake cost predictable, and gives every recommendation a telemetry
path.

## Executive Rollout Status

OVERWATCH has passed validation for an admin pilot under the approved interim
`SNOW_ACCOUNTADMINS` and `SNOW_SYSADMINS` access model. The approved target
roles are `OVERWATCH_VIEWER`, `OVERWATCH_OPERATOR`, and `OVERWATCH_ADMIN`;
grant migration remains review-only and should move through controlled
Snowflake change management.

Current rollout posture:

- Admin pilot: Go.
- Broad production: Conditional Go / Review.
- Production readiness is gate-based, not self-scored in docs. Treat broad
  production as ready only when CI is green, all sections render, mart
  validation passes, no committed secrets are found, role-based viewer smoke
  testing passes, first paint avoids full `ACCOUNT_USAGE` scans, and deployment
  SQL runs in numbered order.
- Alert recipient: `jdees@alfains.com`.
- Remaining production review item: true telemetry freshness gaps, including
  Trexis coverage under ALFA-equivalent expectations.

The leadership-ready rollout package is documented in
`docs/EXECUTIVE_ROLLOUT_PACKAGE.md`. It explains the business case,
governance model, value framework, readiness posture, risk register, KPI
catalog, and rollout recommendation for CIO/CTO/VP/Director and governance
review audiences.

## Telemetry Architecture Decision

OVERWATCH production setup uses scheduled Snowflake tasks plus transient fact
and mart tables as the default architecture. Permanent tables are reserved for
configuration, acknowledgements, remediation logs, action history, suppression
windows, and DBA-entered audit notes that should not disappear if a reproducible
mart is rebuilt.

The production DDL is split under `snowflake/mart_setup/` in numbered
deployment order, with `snowflake/OVERWATCH_MART_SETUP.sql` retained as the
one-shot bundled setup source. Optional precompute experiments have been
retired so there is one deployable Snowflake setup path. Materialized views are
avoided for the main monitoring app because
the app needs multi-source, windowed, exception ranking logic with explicit
error handling and audit logging.

The Executive Landing page is the one deliberate first-paint aggregate:
`MART_EXECUTIVE_OBSERVABILITY`. It is refreshed after the hourly load, Cortex
load, Control Room, cost monitoring, and executive refresh tasks so the first screen
can show spend, Cortex cost, runtime, queueing, spill, failures, alerts,
actions, storage, ranked cost drivers, queries by database, execution status,
and warehouse pressure from one compact source. The app renders the monitoring
summary immediately and reuses cached/session values; an explicit Refresh
hydrates the mart when Snowflake access is available. Raw
`ACCOUNT_USAGE` scans are never part of Executive Landing first paint.

Every primary navigation click now follows the same production UX pattern:
direct entry into the useful monitoring surface with the most important facts
already visible. Workflow buttons are secondary drill-through actions, not a
required step before the DBA sees what is risky, expensive, late, or broken.

The fast monitoring surfaces share `MART_EXECUTIVE_OBSERVABILITY` as the tiny
summary backbone. Executive Landing uses it directly for the executive
summary; DBA Control Room, Alert Center, Workload Operations, and Cost &
Contract reuse the same cached/session board for spend, Cortex, queue, spill,
failure, alert, action, and freshness signals before their deeper
section-specific marts or detail workspaces are opened.

The same decision is documented in `docs/REFRESH_ARCHITECTURE.md` and checked by
`snowflake/OVERWATCH_MART_VALIDATION.sql`, which defines first-paint sources,
target freshness, live-fallback boundaries, and the owner for each surface
without adding a static policy table to the mart schema.

Use `snowflake/OVERWATCH_MART_VALIDATION.sql` after setup or release changes to
prove required marts, alert audit tables, reconciliation tables, executive board
panels, freshness rows, and caller context. Use
`docs/LIVE_ROLE_PROOF_CHECKLIST.md` to validate the app as
SNOW_ACCOUNTADMINS/SNOW_SYSADMINS before calling a build production-ready.

Production role setup now lives inside `snowflake/OVERWATCH_MART_SETUP.sql` so
there is one DDL document for databases, warehouses, roles, tables, procedures,
views, and tasks. Use `SNOW_ACCOUNTADMINS` and `SNOW_SYSADMINS` for app access
today; future dedicated OVERWATCH admin roles should inherit the same grants.
Avoid running daily operations as raw ACCOUNTADMIN/SYSADMIN except for
break-glass setup work. The deployment check remains
`snowflake/OVERWATCH_MART_VALIDATION.sql`.

Supporting operations documents:

- `docs/EXECUTIVE_ROLLOUT_PACKAGE.md` - leadership rollout package,
  value framework, risk register, KPIs, and go/no-go recommendation.
- `docs/OVERWATCH_RECOVERY_RUNBOOK.md` - operator recovery checklist.
- `docs/MART_RESET_RUNBOOK.md` - drop/setup/refresh sequence for mart rebuilds.
- `docs/MART_OBJECT_REVIEW.md` - current mart object inventory and pruning guardrails.
- `docs/IMPLEMENTATION_NOTES.md` - documented boundaries for new implementation changes.
- `CHANGELOG.md` - release-level change history.

The first-paint summaries expose monitoring lanes for Snowflake Data Metric
Functions, Snowflake ALERT objects, OVERWATCH query-tag self-cost, and optional
organization usage rollups. Those lanes are setup contracts, not hidden
live scans: unavailable privileges should produce friendly setup/fallback
messages while the page still renders instantly.

## Current Production Sections

| Group | Sections | Primary job |
|---|---|---|
| Monitoring Core | Executive Landing, DBA Control Room, Alert Center | Leadership summary, morning triage, incident queue, alert routing, and action closure. |
| Cost Monitoring | Cost & Contract | Spend explanation, warehouse/user/role attribution, Cortex spend, contract pacing, storage, optimization, and action telemetry. |
| Operations | Workload Operations | Query/task/procedure status, contention, pipeline telemetry, SLA risk, schema/data compare, and runbooks. |
| Security | Security Monitoring | MFA/login/grant posture, object changes, risky shares, access telemetry, rollback context, schema compare, and controlled DBA actions. |

## Daily Operating Model

1. Open Executive Landing for the observability health, cost, alert, and workload summary.
2. Use the topbar filters for company, environment, date window, warehouse, and
   user scope.
3. Open the section that matches the question; each primary section lands directly on useful telemetry or a specialist monitor.
4. Open DBA Control Room for the morning priority queue and incident handoff.
5. Route actions through the action queue with severity, telemetry basis,
   rollback context, and closure status.
6. Use specialist monitors when the first screen shows a real exception or executive question.

## Cost Formula Contract

OVERWATCH uses the same core warehouse metering source as Snowflake cost
reporting:

- Warehouse credits: `SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY`
- Compute credits: `CREDITS_USED_COMPUTE` when available, otherwise
  `CREDITS_USED`
- Total warehouse credits: `CREDITS_USED`
- Official billed service credits:
  `SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY`
- Configured compute credit rate: `$3.68`
- Configured Cortex AI credit rate: `$2.20`

Database, schema, user, role, and environment costs are allocated from exact
metered warehouse-hour credits when Snowflake does not provide direct billing at
that grain. Exact metering and allocated attribution are labeled separately.

## Alert Monitoring

The Alert Center is being hardened into a proactive DBA monitoring surface rather
than a cosmetic inbox. It now has deployable configuration, event,
acknowledgement, notification, routing, threshold, and remediation audit
tables:

- `ALERT_CONFIG`
- `ALERT_EVENTS`
- `ALERT_RUN_HISTORY`
- `ALERT_ACKNOWLEDGEMENTS`
- `ALERT_REMEDIATION_LOG`
- `ALERT_NOTIFICATION_LOG`
- `ALERT_THRESHOLDS`
- `ALERT_OWNER_ROUTING`
- `ALERT_DATA_QUALITY_CHECKS`

Lifecycle actions should be written to the alert audit tables. The app
generates reviewable insert SQL for `ALERT_ACKNOWLEDGEMENTS` and
`ALERT_REMEDIATION_LOG`; dangerous remediation remains review-gated and
logged rather than silently executed.

The section covers security, cost, performance, task and pipeline,
data-quality, and optimization alert families. Snowflake `ACCOUNT_USAGE` views
are treated as authoritative historical telemetry but are labeled as delayed
telemetry. Near-real-time operations should use `INFORMATION_SCHEMA` table
functions, Snowflake alert objects, task graph notifications, and event tables
where the account supports them.

The Alert Center now opens on active incidents and lifecycle telemetry. Rows are
sorted by severity, SLA age, route, business impact, source freshness, and
remediation mode so the DBA can work the right item first instead of scanning a
flat inbox.

The command-intelligence hardening pass keeps the monitoring foundation focused:
root-cause correlation, task critical path, reconciliation, cost run-rate
monitoring, alert lifecycle, fact-grounded Cortex query diagnosis, security
activity, optional org rollups, no-saved-state navigation, and runbooks. These
are exposed as data-first panels and SQL contracts before deeper drilldown.

`ALERT_DATA_QUALITY_CHECKS` is the metadata-driven table for freshness, row
count, null-rate, duplicate, volume, and schema checks. DBAs and data owners can
tune database/schema/table/column/check type/threshold/severity/owner/channel
without changing Streamlit code.

Remediation is review-gated by default. The app may recommend SQL or actions,
but state-changing fixes must log trigger, reviewer, before/after state,
rollback guidance, affected object/user/warehouse/task, and verification result
in `ALERT_REMEDIATION_LOG`.

All deployable Snowflake objects are consolidated into
`snowflake/OVERWATCH_MART_SETUP.sql`. Cost findings stay in the action queue and
are measured through post-period telemetry rather than a separate value ledger.

Run `snowflake/OVERWATCH_MART_VALIDATION.sql` after setup to verify required
objects, executive board panels, source freshness, refresh-policy targets,
alert lifecycle/audit tables, reconciliation status, and caller context.

## Quick Start

Local run:

```powershell
cd C:\Users\jfree\Desktop\overwatchv3\_deploy_OVERWATCH
.\run_overwatch_local.ps1
```

Manual Streamlit run:

```powershell
.\.venv\Scripts\python.exe -m streamlit run .overwatch_final\app.py --server.port 8501 --server.headless true
```

Production Snowflake setup:

```sql
-- Run in Snowflake with a role allowed to create the OVERWATCH database,
-- schema, tables, procedures, tasks, and app warehouse.
-- File:
-- snowflake/OVERWATCH_MART_SETUP.sql
```

Streamlit Community Cloud settings:

- Repository: `jfreeze03/OVERWATCH`
- Branch: `main`
- Main file path: `streamlit_app.py`
- Tracked app config: `.streamlit/config.toml`

Streamlit in Snowflake uses `.overwatch_final/snowflake.yml` with
`main_file: app.py` and `query_warehouse: OVERWATCH_WH`.

## Production Validation

Focused tests:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_navigation_integrity.NavigationIntegrityTests.test_app_performance_hot_paths_are_deferred_or_cached
```

Full suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Section smoke:

```powershell
.\.venv\Scripts\python.exe .\perf_tests\section_smoke_runner.py --url http://localhost:8501/ --timeout-ms 30000 --initial-wait-ms 1500 --run-id PERF_TEST_SECTION_SMOKE_RELEASE
```

Bad-character scan: run the repo-standard mojibake/unexpected-character search
against `.overwatch_final`, `tests`, and documentation before release.

## Documentation

- [docs/EXECUTIVE_ROLLOUT_PACKAGE.md](docs/EXECUTIVE_ROLLOUT_PACKAGE.md)
  is the leadership-facing rollout package for executive, architecture,
  governance, and risk review audiences.
- [docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md) documents
  production readiness, validation posture, and governance-alignment status.
- [OVERWATCH_DOCUMENTATION.md](OVERWATCH_DOCUMENTATION.md) is the production
  operating guide.
- [SNOWFLAKE_FORMULA_AUDIT_20260529.md](SNOWFLAKE_FORMULA_AUDIT_20260529.md)
  documents the current cost formula contract and audit status.
- [DBA_CONTROL_ROOM_ROADMAP.md](DBA_CONTROL_ROOM_ROADMAP.md) tracks the path to
  closed-loop DBA operations.
- [ALERT_COMMAND_CENTER_RUNBOOK.md](ALERT_COMMAND_CENTER_RUNBOOK.md) explains
  Alert Center setup, privileges, integrations, and daily DBA alert triage.
- [docs/OVERWATCH_COMMAND_INTELLIGENCE_RUNBOOK.md](docs/OVERWATCH_COMMAND_INTELLIGENCE_RUNBOOK.md)
  explains the 12 command-intelligence capabilities, data-first UI model,
  reconciliation approach, AI query diagnosis contract, and mart-first decision.
- [docs/DATA_MODEL.md](docs/DATA_MODEL.md) summarizes the new command
  intelligence, reconciliation, cost monitoring, and security objects.
- [docs/REFRESH_ARCHITECTURE.md](docs/REFRESH_ARCHITECTURE.md) documents the
  mart-first refresh policy, first-paint sources, and live-query boundaries.
- [docs/MART_OBJECT_REVIEW.md](docs/MART_OBJECT_REVIEW.md) records the current
  mart object inventory and safe-pruning decisions.
- [docs/MART_RESET_RUNBOOK.md](docs/MART_RESET_RUNBOOK.md) gives the mass-drop,
  setup, refresh, and validation sequence for a clean mart rebuild.
- [UX_PRODUCTION_GUIDELINES.md](UX_PRODUCTION_GUIDELINES.md) documents current
  production UI standards.
