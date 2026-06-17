# OVERWATCH Data Model

This file summarizes the Snowflake objects that support the command-intelligence
layer. The full source of truth remains `snowflake/OVERWATCH_MART_SETUP.sql`.

## Command Intelligence

| Object | Type | Purpose |
|---|---|---|
| `OVERWATCH_SELF_MONITORING_V` | View | Summarizes app query tags, failures, latency, and bytes scanned by section. |
| `MART_EXECUTIVE_OBSERVABILITY` | Transient mart | Executive monitoring wall: spend, Cortex, runtime, queue, spill, alerts, actions, storage, cost drivers, query database mix, execution status, and warehouse pressure. |

The refresh contract and capability notes now live in documentation and
validation SQL instead of static mart tables.

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
| `ALERT_EVENTS` | Table | Durable alert lifecycle event table used by Alert Center command lanes. |
| `ALERT_NATIVE_OBJECT_REGISTRY` | Table | Reviewed native Snowflake alert candidates with generated create/drop SQL. Candidates are disabled by default. |
| `ALERT_REMEDIATION_POLICY` | Table | Recommend/status-review policy catalog for future guarded remediation. |
| `ALERT_REMEDIATION_DRY_RUN` | Table | Audit table for proposed remediation dry-runs before any execution path exists. |
| `ALERT_ACKNOWLEDGEMENTS`, `ALERT_NOTIFICATION_LOG`, `ALERT_REMEDIATION_LOG` | Tables | Alert acknowledgement, delivery, and remediation audit history. |

## Native Snowflake Proof Contracts

| Source | Purpose |
|---|---|
| `SNOWFLAKE.ACCOUNT_USAGE.DATA_METRIC_FUNCTION_REFERENCES` | Registers Snowflake DMF data-quality checks, schedules, states, and stale/failed runs where DMFs are enabled. |
| `SHOW ALERTS IN ACCOUNT` / `INFORMATION_SCHEMA.ALERT_HISTORY` | Proves native Snowflake ALERT objects exist, are scheduled, and have recent run history. |
| `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY` with `QUERY_TAG ILIKE 'OVERWATCH%'` | Measures OVERWATCH's own query count, failures, latency, bytes scanned, and section attribution. |
| `SNOWFLAKE.ORGANIZATION_USAGE.METERING_DAILY_HISTORY` | Optional ORGADMIN rollup for multi-account cost when organization privileges exist. |
