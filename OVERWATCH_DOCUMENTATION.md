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
4. Which security, access, and change-control risks need owner action?
5. What can be summarized for executives without manually rebuilding a slide
   deck?

The product goal is not just dashboard visibility. The goal is closed-loop DBA
operations: detect, route, act, verify, and retain evidence.

## Production Navigation

| Group | Section | What it is for |
|---|---|---|
| Command Center | Executive Landing | Executive-ready summary, KPI packet, cost movement, risk movement, and presentation notes. |
| Command Center | DBA Control Room | Morning triage, top priority brief, open work, live status, and action queue routing. |
| Command Center | Alert Center | Alert rules, alert history, delivery preparation, digest evidence, and alert health. |
| Command Center | Account Health | Account-level exception checklist, service health, source freshness, and DBA next actions. |
| Financial Control | Cost & Contract | Cost overview, warehouse/user/role attribution, Cortex spend, contract pacing, savings verification, and RCA narrative. |
| Operations | Workload Operations | Live query/task/procedure status, Control-M style job evidence, performance indicators, and errors. |
| Operations | Warehouse Health | Warehouse pressure, queue/spill/latency evidence, setting review, resize/suspend/resume guardrails, and verification proof. |
| Governance | Security Posture | MFA, login posture, role/grant posture, dormant/high-risk access, sharing exposure, and security evidence. |
| Governance | Change & Drift | Object changes, schema compare, Terraform evidence, Jira evidence, Flyway/Git evidence, and drift context. |
| Architecture | Architecture Readiness | Ownership, objectives, platform futures, source health, control register, and readiness evidence. |

Legacy bookmarks and saved views may still redirect to the current sections, but
production documentation and navigation should use only the names above.

## User Roles And Experience Views

The app uses experience views to reduce risk and noise:

| Experience view | Intended audience | Access intent |
|---|---|---|
| DBA | Full DBA/admin operator | Full enabled admin control, action routing, evidence, and guarded execution paths. |
| Manager | DSA-style manager | Broad health, cost, security, governance, and action status without needing every admin control first. |
| Analyst | DTI-style analyst | Workload Operations and analysis surfaces needed to investigate query, task, and warehouse behavior. |
| Executive | Leadership | Executive Landing, high-level health, cost, open risk, and report-ready evidence. |

The DBA role must retain the strongest confirmation, audit, rollback, and
verification requirements because it can trigger production-impacting actions.

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
| Exceptions-only | Keeps first-load views focused on failing or high-risk evidence. |

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

Environment classification is evidence-sensitive. Rows with no reliable
database context should remain `No Database Context`; they should not be forced
into production or development.

## Mart-First Architecture

The Snowflake setup file creates the OVERWATCH database, schema, tables,
procedures, tasks, and dedicated app warehouse. The Streamlit app runs on
`OVERWATCH_WH`. The current mart task graph runs on `COMPUTE_WH`.

Core mart facts include:

- `FACT_WAREHOUSE_HOURLY`
- `FACT_QUERY_HOURLY`
- `FACT_QUERY_DETAIL_RECENT`
- `FACT_TASK_DAILY`
- `FACT_OBJECT_CHANGE`
- `FACT_COST_DAILY`
- `FACT_CORTEX_DAILY`
- `FACT_CHARGEBACK_DAILY`
- `FACT_ACCOUNT_HEALTH_OPERABILITY_DAILY`
- `FACT_WAREHOUSE_OPERABILITY_DAILY`
- `FACT_SECURITY_OPERABILITY_DAILY`

Core durable evidence tables include:

- `OVERWATCH_ACTION_QUEUE`
- `OVERWATCH_ALERTS`
- `OVERWATCH_OWNER_DIRECTORY`
- `OVERWATCH_ADMIN_ACTION_AUDIT`
- `OVERWATCH_WORKLOAD_RECOVERY_AUDIT`
- `OVERWATCH_WAREHOUSE_SETTING_REVIEW`
- `OVERWATCH_AUTOMATION_RUN`
- `OVERWATCH_EXECUTIVE_PACKET`
- `OVERWATCH_EXTERNAL_CONTROL_FEED`

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
| User/role/schema/database attribution | Allocate exact metered warehouse-hour credits by query evidence when direct billing is unavailable. |

All sections should distinguish exact Snowflake metering from allocated
attribution. Cost tables should include dollars when the metric represents
credits, spend, savings, or forecast.

## Admin Safety

Any production-impacting admin control must follow this pattern:

1. Show the current value.
2. Generate changed-only SQL.
3. Require typed confirmation or explicit approval.
4. Capture owner, ticket, reason, rollback SQL, and proof query.
5. Write an audit row even when the action fails.
6. Keep the action open until verification evidence exists.

Warehouse setting changes, query cancellation, task execution, account
parameter changes, and security/role changes should never be treated as simple
button clicks.

## Integrations

OVERWATCH supports evidence surfaces for:

- Control-M style task/job status, performance indicators, and errors.
- Jira approval and issue evidence.
- Terraform plan/apply/drift evidence.
- Flyway migration evidence.
- Git/source-control evidence.
- Snowflake email notification integration for digest and critical alerts.

These integrations should land in durable evidence tables or external feed
tables before they become trusted production signals.

## Alerting And Executive Reporting

Alert Center prepares alert content with severity, owner, route, proof query,
and delivery state. When the Snowflake email notification integration is
approved, alert digest procedures can call Snowflake email delivery instead of
remaining dry-run packaging.

Executive Landing and the automation objects support weekly or on-demand
executive packets. A production packet should include cost movement, top risk,
open actions, verified savings, incidents, governance blockers, and next steps.

## UI Standards

Production sections should follow these rules:

- Exception-first: show urgent failures or risk before tables.
- One navigation level: avoid tabs inside tabs.
- Explicit load gates: heavy evidence should load only when requested.
- Useful metrics only: no build/test/internal performance metrics in app UI.
- Cost where it matters: credit tables should include dollar estimates.
- Toggle chart/table state: when a chart exposes data, users need a path back
  to the chart.
- Compact action briefs: use short operator language and proof links.
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
