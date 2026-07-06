# OVERWATCH Snowflake Architecture

Last updated: June 16, 2026

OVERWATCH is built around a low-cost Snowflake mart that turns expensive,
high-latency account telemetry into compact DBA status. The Streamlit app
uses the mart first and requests live metadata only where immediacy matters.

## Runtime Layout

| Layer | Object or path | Purpose |
|---|---|---|
| Streamlit app | `.overwatch_final/app.py` | User interface, navigation, filters, section routing. |
| App runtime warehouse | `WH_ALFA_OVERWATCH` | Approved current Streamlit execution warehouse until a dedicated OVERWATCH warehouse is approved. |
| App resource monitor | `WH_ALFA_OVERWATCH_RM` | Runtime cost guardrail. |
| Mart task warehouse | `WH_ALFA_OVERWATCH` | Approved current scheduled mart refresh warehouse. |
| Snowflake setup | `snowflake/OVERWATCH_MART_SETUP.sql` | Creates database, schema, tables, procedures, tasks, and seed rows. |
| Local tests | `tests/` | Formula, navigation, admin, scope, and regression coverage. |
| Performance tests | `perf_tests/` | HTTP, live concurrency, and section smoke checks. |

## Data Flow

```text
Snowflake account views
  -> OVERWATCH stored procedures
  -> compact fact tables and durable monitoring tables
  -> Streamlit sections
  -> action queue, alerts, executive observability, and DBA telemetry
```

Live Snowflake views are still used for real-time needs, especially current
query, task, warehouse, and security posture checks. Any live view should be
labeled or designed with its freshness limits in mind.

## First-Paint Readiness States

App entry reads compact marts, not broad Account Usage scans. Each primary
section classifies its first-paint packet as loaded current, loaded stale, no
rows for selected scope, setup required, refresh required, connection
unavailable, or query failed. `snowflake/validation/validate_mart_first_paint_readiness.sql`
reports the source object, row count, latest snapshot, freshness, target
freshness, and mapped state for every primary section source.

Missing current rows should point operators to refresh/setup validation.
Missing objects should point to setup. Empty scoped results should show a
clean no-rows state without hiding the rest of navigation.

## Core Sources

| Source | Used for |
|---|---|
| `SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY` | Exact warehouse credits by hour. |
| `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY` | Query history, attribution, performance, errors, and change telemetry. |
| `SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY` | Task status, duration, failures, pipeline facts. |
| `SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY` | Official billed service credits. |
| `SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY` | Access and lineage telemetry where available. |
| `SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS` and grant views | Role and security posture. |
| `SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES` | Owner and chargeback telemetry. |
| Organization usage views | Optional currency/rate reconciliation when visible. |
| Information Schema table functions | Live current-state query and task checks where possible. |

## Mart Facts

| Fact | Purpose |
|---|---|
| `FACT_WAREHOUSE_HOURLY` | Warehouse credits, compute credits, cloud credits, and estimated cost. |
| `FACT_QUERY_HOURLY` | Query counts, failures, latency, queue time, spill, user/role/database/schema scope. |
| `FACT_QUERY_DETAIL_RECENT` | Recent query details for diagnosis and telemetry queries. |
| `FACT_TASK_RUN`, `FACT_TASK_CRITICAL_PATH` | Task/pipeline status, duration, failures, and critical-path context. |
| `FACT_OBJECT_CHANGE` | DDL, grants, warehouse changes, schema drift, and object-change telemetry. |
| `FACT_COST_DAILY` | Official daily service credits by service type. |
| `FACT_CORTEX_DAILY` | Cortex AI usage and estimated spend. |
| `FACT_CHARGEBACK_DAILY` | User/role/database/schema allocation from metered credits. |
| `FACT_COST_INCIDENT_TIMELINE` | Cost incidents, change correlations, and alert storyline. |
| `FACT_ACCOUNT_HEALTH_OPERABILITY_DAILY` | Account-health checklist state. |
| `FACT_WAREHOUSE_OPERABILITY_DAILY` | Warehouse pressure, setting-review, and action telemetry. |
| `FACT_SECURITY_OPERABILITY_DAILY` | Security posture telemetry and exception state. |

## Durable Audit And Status Objects

| Object | Purpose |
|---|---|
| `OVERWATCH_ACTION_QUEUE` | DBA work queue with severity, route, telemetry, savings, and status. |
| `OVERWATCH_ALERTS` | Alert event ledger and delivery state. |
| `OVERWATCH_ALERT_RULES` | Alert categories, severity defaults, SLA hours, routes, and runbooks. |
| `OVERWATCH_ADMIN_ACTION_AUDIT` | Immutable admin-action telemetry. |
| `OVERWATCH_WORKLOAD_RECOVERY_AUDIT` | Warehouse/workload recovery and status telemetry. |
| `OVERWATCH_WAREHOUSE_SETTING_REVIEW` | Warehouse setting review snapshots and recommendations. |
| `OVERWATCH_RECON_CONFIG`, `OVERWATCH_RECON_RUN`, `OVERWATCH_SCHEMA_DIFF_RESULT` | Schema/data compare configuration, run history, and generated missing-object DDL. |
| `OVERWATCH_ALERT_DELIVERY_LOG` | Optional alert digest delivery telemetry. |

## Key Views

| View | Purpose |
|---|---|
| `OVERWATCH_WORKLOAD_RECOVERY_AUDIT_LATEST_V` | Latest recovery state by workload. |
| `OVERWATCH_ALERT_TRIAGE_V` | Alert route, status, and delivery context. |
| `MART_DBA_CONTROL_ROOM` | Primary control-room rollup table. |
| `MART_EXECUTIVE_OBSERVABILITY` | Executive Landing metric rollup table. |

## Scheduled Tasks

| Task | Schedule or dependency | Purpose |
|---|---|---|
| `OVERWATCH_LOAD_HOURLY` | Hourly at :25 | Refresh hourly warehouse, query, task, object, cost, chargeback, and operability facts. |
| `OVERWATCH_LOAD_CORTEX` | After hourly load | Refresh Cortex AI spend facts. |
| `OVERWATCH_REFRESH_CONTROL_ROOM` | After Cortex load | Refresh control-room mart. |
| `OVERWATCH_COST_MONITORING_REFRESH` | After control-room refresh | Refresh cost monitoring signals, incident timeline, and cost alerts. |
| `OVERWATCH_EXECUTIVE_OBSERVABILITY_REFRESH` | After cost monitoring refresh | Refresh Executive Landing rollups. |
| `OVERWATCH_ANOMALY_CHECK` | Hourly at :05 | Seed anomaly alerts and action candidates. |
| `OVERWATCH_LOAD_DAILY` | Daily at 06:15 CT | Refresh daily history and longer-horizon facts. |

## Scope Rules

Trexis is explicitly scoped by warehouse and database names. ALFA covers all
other listed account warehouses and configured ALFA databases. Rows without
database context remain `No Database Context`.

The scope classifier should be kept in sync across:

1. `.overwatch_final/config.py`
2. Python company-scope helpers
3. environment classifier SQL
4. navigation/filter tests
5. cost and chargeback regression tests

## Cost Rules

Warehouse total credits use `CREDITS_USED`. Warehouse compute credits use
`CREDITS_USED_COMPUTE` when Snowflake exposes it. Dollar estimates use `$3.68`
for compute and `$2.20` for Cortex AI. Database, user, role, and schema costs
are allocated from exact warehouse-hour metering unless the official source
provides a direct billed value at that grain.

## App Query Strategy

Sections should load in this order:

1. Read compact mart facts.
2. Read durable audit/status tables.
3. Use static metadata options where the filter value is already known.
4. Use live Information Schema only for current-state operational needs.
5. Use Account Usage fallbacks only when the mart is unavailable or the user
   explicitly requests secondary telemetry.

Heavy tables, schema compare, source-health inventories, and deep diagnostic
panels should stay behind explicit load buttons.

## Metric Catalog

`.overwatch_final/metrics/metric_registry.py` is the app-side catalog for
product metric labels, plain-English calculations, thresholds, tooltips, and
owning workflows. It does not store raw SQL bodies or create Snowflake objects.
The Snowflake command-brief metric rows use the same product labels so packet
refresh does not reintroduce deleted owner-routing metrics or older queue
wording.

## Production Change Rules

Any setup or architecture change should update:

1. setup SQL
2. app config
3. documentation
4. formula/navigation/scope tests
5. section smoke expectations when UI behavior changes

Do not change runtime warehouse, mart task warehouse, company scope, or cost
rates without updating this document and the manual input runbook.
