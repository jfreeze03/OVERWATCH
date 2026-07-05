# OVERWATCH Production Documentation

Last updated: June 6, 2026

This is the production operating guide for OVERWATCH, a Snowflake DBA command
center built with Streamlit, Snowflake account telemetry, and a low-cost
OVERWATCH mart.

## Purpose

OVERWATCH gives DBAs one place to answer five production questions:

1. What needs attention right now?
2. What is driving Snowflake cost?
3. Which workloads, tasks, warehouses, or procedures are failing or slowing
   down?
4. Which security, access, and object-change risks need owner action?
5. What can be summarized for executives without manually rebuilding a slide
   deck?

The product goal is not just dashboard visibility. The goal is closed-loop DBA
operations: detect, route, act, refresh telemetry, and keep an audit trail.

## Production Navigation

| Group | Section | What it is for |
|---|---|---|
| Command Center | Executive Landing | Executive-ready summary, KPI packet, cost movement, risk movement, and presentation notes. |
| Command Center | DBA Control Room | Morning triage, top priority brief, open work, live status, and action queue routing. |
| Command Center | Alert Center | Alert rules, alert history, delivery preparation, digest telemetry, and alert health. |
| Command Center | Account Health | Account-level exception checklist, service health, source freshness, and DBA next actions. |
| Financial Control | Cost & Contract | Cost overview, warehouse/user/role attribution, Cortex spend, contract pacing, savings telemetry, and RCA narrative. |
| Operations | Workload Operations | Live query/task/procedure status, task graph health, stored procedure analysis, performance indicators, and errors. |
| Operations | Warehouse Health | Warehouse pressure, queue/spill/latency telemetry, setting review, resize/suspend/resume guardrails, and post-change checks. |
| Security | Security Posture | MFA, login posture, role/grant posture, dormant/high-risk access, sharing exposure, and security telemetry. |
| Operations | Change & Drift | Object changes, schema compare, stored procedure lineage, data movement, and drift context. |

Legacy bookmarks and saved views may still redirect to the current sections, but
production documentation and navigation should use only the names above.

## Admin Role Access

The app is an admin/DBA monitoring command center. Access is intended for
`SNOW_ACCOUNTADMINS` and `SNOW_SYSADMINS`, with local demo fallback only for
browser testing. Production-impacting actions retain confirmation, audit,
rollback, and verification requirements.

## Global Filters

Production filters are exposed as a persistent topbar so DBAs do not have to
dig through a long sidebar during morning triage.

| Filter | Purpose |
|---|---|
| Company | `ALFA`, `Trexis`, or account-wide view. |
| Environment | Production, all development/test, individual database environments, or all environments. |
| Cost/date window | Standard windows: `1`, `7`, `14`, `30`, `60`, and `90` days. |
| Warehouse | Metadata/static warehouse options scoped to the selected company/environment where possible. |
| User | Optional user-level workload or cost focus. |
| Exceptions-only | Keeps first-load views focused on failing or high-risk telemetry. |

For Trexis, production databases end in `_PRD`; development/test databases end
in `_DEV` or `_SIT`. For ALFA, configured production and development database
families are defined in `.overwatch_final/config.py` and mirrored in the mart
setup SQL.

## Company And Environment Scope

Trexis warehouses are explicitly hardcoded:

- `WH_TRXS_LOAD`
- `WH_TRXS_QUERY`
- `WH_TRXS_TRANSFORM`
- `WH_TRXS_UNLOAD`

All other listed account warehouses are treated as ALFA unless a future scope
entry explicitly assigns them elsewhere.

Trexis databases are explicitly hardcoded:

- `TRXS_ABC_METADATA_DEV`
- `TRXS_ABC_METADATA_PRD`
- `TRXS_ABC_METADATA_SIT`
- `TRXS_EDW_DEV`
- `TRXS_EDW_PRD`
- `TRXS_EDW_SIT`
- `TRXS_GW_DATA_DEV`
- `TRXS_GW_DATA_PRD`
- `TRXS_GW_DATA_SIT`

Environment classification is telemetry-sensitive. Rows with no reliable
database context should remain `No Database Context`; they should not be forced
into production or development.

## Mart-First Architecture

The Snowflake setup file creates the OVERWATCH database, schema, tables,
procedures, tasks, and dedicated app warehouse. The Streamlit app runs on
`COMPUTE_WH`. The current mart task graph runs on `COMPUTE_WH`.

Core mart facts include:

- `FACT_WAREHOUSE_HOURLY`
- `FACT_QUERY_HOURLY`
- `FACT_QUERY_DETAIL_RECENT`
- `FACT_TASK_RUN`
- `FACT_TASK_CRITICAL_PATH`
- `FACT_OBJECT_CHANGE`
- `FACT_COST_DAILY`
- `FACT_CORTEX_DAILY`
- `FACT_CHARGEBACK_DAILY`
- `FACT_ACCOUNT_HEALTH_OPERABILITY_DAILY`
- `FACT_WAREHOUSE_OPERABILITY_DAILY`
- `FACT_SECURITY_OPERABILITY_DAILY`

Core durable audit/status tables include:

- `OVERWATCH_ACTION_QUEUE`
- `OVERWATCH_ALERTS`
- `OVERWATCH_ADMIN_ACTION_AUDIT`
- `OVERWATCH_WORKLOAD_RECOVERY_AUDIT`
- `OVERWATCH_WAREHOUSE_SETTING_REVIEW`
- `OVERWATCH_ALERT_DELIVERY_LOG`
- `OVERWATCH_RECON_CONFIG`
- `OVERWATCH_RECON_RUN`
- `OVERWATCH_SCHEMA_DIFF_RESULT`

## Cost And Credit Rules

Cost metrics must stay aligned across sections.

| Metric | Rule |
|---|---|
| Warehouse total credits | Sum `CREDITS_USED` from `WAREHOUSE_METERING_HISTORY`. |
| Warehouse compute credits | Sum `CREDITS_USED_COMPUTE` when available; otherwise fall back to `CREDITS_USED`. |
| Warehouse dollar estimate | Warehouse credits multiplied by `$3.68`. |
| Cortex AI dollar estimate | Cortex AI credits multiplied by `$2.20`. |
| Official billed service credits | Use `METERING_DAILY_HISTORY`. |
| Official currency reconciliation | Use organization usage/rate-sheet views only when the active role can see them. |
| User/role/schema/database attribution | Allocate exact metered warehouse-hour credits by query telemetry when direct billing is unavailable. |

All sections should distinguish exact Snowflake metering from allocated
attribution. Cost tables should include dollars when the metric represents
credits, spend, savings, or forecast.

## Admin Safety

Any production-impacting admin control must follow this pattern:

1. Show the current value.
2. Generate changed-only SQL.
3. Require typed confirmation or reviewed route.
4. Capture owner, ticket, reason, rollback SQL, and telemetry query.
5. Write an audit row even when the action fails.
6. Keep the action open until verification telemetry exists.

Warehouse setting changes, query cancellation, task execution, account
parameter changes, and security/role changes should never be treated as simple
button clicks.

## Integrations

OVERWATCH supports Snowflake-native alert delivery telemetry through approved
Snowflake email notification integration when available. External workflow tools
are not part of the current product surface.

## Alerting And Executive Reporting

Alert Center prepares alert content with severity, owner, route, telemetry query,
and delivery state. When the Snowflake email notification integration is
approved, alert digest procedures can call Snowflake email delivery instead of
remaining dry-run packaging.

Executive Landing first paint renders a Snowflake-style command-center
dashboard from the current section command brief packet: six compact KPI cards,
an attention panel, account-health trend, warehouse-credit split when refreshed
facts exist, recommended actions, recent status rows, and operational context.
The heavier Executive snapshot still loads only after the explicit action.

## UI Standards

Production sections should follow these rules:

- Exception-first: show urgent failures or risk before tables.
- One navigation level: avoid tabs inside tabs.
- Explicit load gates: heavy telemetry should load only when requested.
- Useful metrics only: no build/test/internal performance metrics in app UI.
- Cost where it matters: credit tables should include dollar estimates.
- Toggle chart/table state: when a chart exposes data, users need a path back
  to the chart.
- Compact action briefs: use short operator language and telemetry links.
- Consistent labels: use current section names and remove stale terminology.

## Production Release Checklist

Before release:

1. Run focused navigation/runtime guards.
2. Run the full unit test suite.
3. Run section smoke against the local app.
4. Run the bad-character scan against app code, tests, and docs.
5. Compile changed Python files when app code changed.
6. Verify the browser renders primary sections without Streamlit or Python
   errors.
7. Confirm no production doc refers to retired navigation labels.
8. Commit and push only after explicit user instruction.
