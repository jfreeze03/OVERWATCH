# OVERWATCH

OVERWATCH is a production Streamlit command center for Snowflake DBA operations.
It brings account health, cost control, workload triage, warehouse governance,
security posture, change evidence, architecture readiness, and executive
briefing into one DBA-owned workflow.

The app is intentionally mart-first. Snowflake account telemetry is collected
into compact OVERWATCH facts by scheduled tasks, and the Streamlit app reads
those facts before it falls back to live account views. This keeps the app fast,
keeps Snowflake cost predictable, and gives every recommendation an evidence
path.

## Current Production Sections

| Group | Sections | Primary job |
|---|---|---|
| Command Center | Executive Landing, DBA Control Room, Alert Center, Account Health | Morning triage, action queue, alert routing, leadership evidence. |
| Financial Control | Cost & Contract | Spend explanation, warehouse/user/role attribution, Cortex spend, contract pacing, savings verification. |
| Operations | Workload Operations, Warehouse Health | Query/task/procedure status, Control-M style pipeline evidence, warehouse pressure, settings review. |
| Governance | Security Posture, Change & Drift | MFA/login/grant posture, object changes, Terraform/Jira/Flyway/Git evidence, schema compare. |
| Architecture | Architecture Readiness | Owner-backed readiness, source health, future Snowflake controls, control register evidence. |

## Daily Operating Model

1. Open DBA Control Room for the top priority brief and exception queue.
2. Use the topbar filters for company, environment, date window, warehouse, and
   user scope.
3. Start with exceptions. Load secondary evidence only when the exception,
   owner, or audit proof requires it.
4. Route actions through the action queue with owner, severity, proof query,
   rollback evidence, and verification status.
5. Use Executive Landing when leadership needs a paste-ready summary.

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

`ALERT_DATA_QUALITY_CHECKS` is the metadata-driven table for freshness, row
count, null-rate, duplicate, volume, and schema checks. DBAs and data owners can
tune database/schema/table/column/check type/threshold/severity/owner/channel
without changing Streamlit code.

Remediation is approval-gated by default. The app may recommend SQL or actions,
but state-changing fixes must log trigger, approval, before/after state,
rollback guidance, affected object/user/warehouse/task, and verification result
in `ALERT_REMEDIATION_LOG`.

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
- [UX_PRODUCTION_GUIDELINES.md](UX_PRODUCTION_GUIDELINES.md) documents current
  production UI standards.
- [OVERWATCH_PROCESS_FOR_16_YEAR_OLD.md](OVERWATCH_PROCESS_FOR_16_YEAR_OLD.md)
  explains the process in plain language.
- [OVERWATCH_PROCESS_FOR_GAME_OF_THRONES_FANS.md](OVERWATCH_PROCESS_FOR_GAME_OF_THRONES_FANS.md)
  explains the process with Game of Thrones-style analogies.
