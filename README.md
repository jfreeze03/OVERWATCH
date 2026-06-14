# OVERWATCH

OVERWATCH is a production Streamlit command center for Snowflake DBA operations.
It brings executive observability, DBA triage, alerts, FinOps, workload
operations, security, and change evidence into one DBA-owned workflow.

The app is intentionally mart-first. Snowflake account telemetry is collected
into compact OVERWATCH facts by scheduled tasks, and the Streamlit app reads
those facts before it falls back to live account views. This keeps the app fast,
keeps Snowflake cost predictable, and gives every recommendation an evidence
path.

## Telemetry Architecture Decision

OVERWATCH production setup uses scheduled Snowflake tasks plus transient fact
and mart tables as the default architecture. Permanent tables are reserved for
configuration, acknowledgements, remediation logs, action history, suppression
windows, and DBA-entered evidence that should not disappear if a reproducible
mart is rebuilt.

Dynamic Tables remain optional in `snowflake/PRECOMPUTE.sql`; they are not the
base architecture because ACCOUNT_USAGE is already delayed, target lag is a
freshness target rather than a fixed refresh interval, and each dynamic table
needs warehouse-backed refresh budget. Materialized views are avoided for the
main command center because the app needs multi-source, windowed, exception
ranking logic with explicit error handling and audit logging.

The Executive Landing page is the one deliberate first-paint aggregate:
`MART_EXECUTIVE_OBSERVABILITY`. It is refreshed after the hourly load, Cortex
load, Control Room, cost governance, and automation tasks so the first screen
can show spend, Cortex cost, runtime, queueing, spill, failures, alerts,
actions, storage, and platform score from one small query.

## Current Production Sections

| Group | Sections | Primary job |
|---|---|---|
| Command Center | Executive Landing, DBA Control Room, Alert Center | Leadership summary, morning triage, incident queue, alert routing, and action closure. |
| Financial Control | Cost & Contract | Spend explanation, warehouse/user/role attribution, Cortex spend, contract pacing, savings verification, storage, and optimization. |
| Operations | Workload Operations | Query/task/procedure status, contention, pipeline evidence, SLA risk, schema/data compare, and runbooks. |
| Governance | Governance & Security | MFA/login/grant posture, object changes, owner approval proof, rollback evidence, schema compare, and controlled DBA actions. |

## Daily Operating Model

1. Open Executive Landing for the board-ready health, cost, alert, and workload summary.
2. Use the topbar filters for company, environment, date window, warehouse, and
   user scope.
3. Open DBA Control Room for the morning priority queue and incident handoff.
4. Route actions through the action queue with owner, severity, proof query,
   rollback evidence, and verification status.
5. Use the specialist sections only when the summary shows a real exception or executive question.

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

## Alert Command Center

The Alert Center is being hardened into a proactive DBA command center rather
than a cosmetic inbox. It now has deployable configuration, event,
acknowledgement, notification, owner-routing, threshold, and remediation audit
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

The section covers security, Cost/FinOps, performance, task and pipeline,
data-quality, and optimization alert families. Snowflake `ACCOUNT_USAGE` views
are treated as authoritative historical evidence but are labeled as delayed
telemetry. Near-real-time operations should use `INFORMATION_SCHEMA` table
functions, Snowflake alert objects, task graph notifications, and event tables
where the account supports them.

The Command Center now promotes open alert rows into an incident action board.
That board sorts by severity, SLA age, owner, ticket state, business impact,
source freshness, proof query, and remediation mode so the DBA can work the
right item first instead of scanning a flat inbox.

The command-intelligence hardening pass adds the ranked 12-item operating
foundation from the COCO/Kiro review: root-cause correlation, task critical
path, reconciliation, predictive FinOps, alert lifecycle, fact-grounded Cortex
query diagnosis, OVERWATCH self-monitoring, optional precompute, compliance,
multi-account readiness, persistent preferences, and runbooks. These are exposed
as data-first panels and SQL contracts before deeper drilldown.

`ALERT_DATA_QUALITY_CHECKS` is the metadata-driven table for freshness, row
count, null-rate, duplicate, volume, and schema checks. DBAs and data owners can
tune database/schema/table/column/check type/threshold/severity/owner/channel
without changing Streamlit code.

Remediation is approval-gated by default. The app may recommend SQL or actions,
but state-changing fixes must log trigger, approval, before/after state,
rollback guidance, affected object/user/warehouse/task, and verification result
in `ALERT_REMEDIATION_LOG`.

Snowflake Value is automation-first. `OVERWATCH_VALUE_CANDIDATE_V` and
`SP_OVERWATCH_AUTOMATE_VALUE_LOG` derive value candidates from fixed action
queue items and resolved alert evidence so DBAs do not have to manually maintain
the value log. Estimated value remains separate from verified value until
post-period proof exists.

Optional precompute is separated into `snowflake/PRECOMPUTE.sql`. Dynamic Tables
must be approved for refresh lag, warehouse, ownership, and cost before use; the
same file also includes fallback views.

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

- [OVERWATCH_DOCUMENTATION.md](OVERWATCH_DOCUMENTATION.md) is the production
  operating guide.
- [OVERWATCH_MANUAL_INPUTS_AND_DDL_RUNBOOK.md](OVERWATCH_MANUAL_INPUTS_AND_DDL_RUNBOOK.md)
  is the manual input, hardcoded scope, and DDL maintenance map.
- [SNOWFLAKE_ARCHITECTURE.md](SNOWFLAKE_ARCHITECTURE.md) explains the mart,
  tasks, objects, and app query strategy.
- [SNOWFLAKE_FORMULA_AUDIT_20260529.md](SNOWFLAKE_FORMULA_AUDIT_20260529.md)
  documents the current cost formula contract and audit status.
- [DBA_CONTROL_ROOM_ROADMAP.md](DBA_CONTROL_ROOM_ROADMAP.md) tracks the path to
  closed-loop DBA operations.
- [ALERT_COMMAND_CENTER_RUNBOOK.md](ALERT_COMMAND_CENTER_RUNBOOK.md) explains
  Alert Center setup, privileges, integrations, and daily DBA alert triage.
- [docs/OVERWATCH_COMMAND_INTELLIGENCE_RUNBOOK.md](docs/OVERWATCH_COMMAND_INTELLIGENCE_RUNBOOK.md)
  explains the 12 command-intelligence capabilities, data-first UI model,
  automated value log, reconciliation approach, AI query diagnosis contract, and
  precompute decision.
- [docs/DATA_MODEL.md](docs/DATA_MODEL.md) summarizes the new command
  intelligence, reconciliation, FinOps/value, compliance, and optional
  precompute objects.
- [UX_PRODUCTION_GUIDELINES.md](UX_PRODUCTION_GUIDELINES.md) documents current
  production UI standards.
