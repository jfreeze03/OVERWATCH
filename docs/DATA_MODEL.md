# OVERWATCH Data Model

This file summarizes the Snowflake objects that support the command-intelligence
layer. The full source of truth remains `snowflake/OVERWATCH_MART_SETUP.sql`.

## Command Intelligence

| Object | Type | Purpose |
|---|---|---|
| `OVERWATCH_COMMAND_INTELLIGENCE_CAPABILITY` | Table | Ranked 12-item capability register used by setup/runbook review. |
| `OVERWATCH_REFRESH_POLICY` | Table | Surface-by-surface refresh contract for first paint, retention, live fallback, and owner accountability. |
| `OVERWATCH_SELF_MONITORING_V` | View | Summarizes app query tags, failures, latency, and bytes scanned by section. |
| `MART_EXECUTIVE_OBSERVABILITY` | Transient mart | Boss-page metric wall: spend, Cortex, runtime, queue, spill, alerts, actions, storage, platform score, cost drivers, query database mix, execution status, and warehouse pressure. |

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

## Security and Compliance

| Object | Type | Purpose |
|---|---|---|
| `OVERWATCH_COMPLIANCE_READINESS_V` | View | Flags admin grants and high-access user activity from Snowflake metadata. |

## Native Snowflake Proof Contracts

| Source | Purpose |
|---|---|
| `SNOWFLAKE.ACCOUNT_USAGE.DATA_METRIC_FUNCTION_REFERENCES` | Registers Snowflake DMF data-quality checks, schedules, states, and stale/failed runs where DMFs are enabled. |
| `SHOW ALERTS IN ACCOUNT` / `INFORMATION_SCHEMA.ALERT_HISTORY` | Proves native Snowflake ALERT objects exist, are scheduled, and have recent run history. |
| `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY` with `QUERY_TAG ILIKE 'OVERWATCH%'` | Measures OVERWATCH's own query count, failures, latency, bytes scanned, and section attribution. |
| `SNOWFLAKE.ORGANIZATION_USAGE.METERING_DAILY_HISTORY` | Optional ORGADMIN rollup for multi-account cost when organization privileges exist. |
