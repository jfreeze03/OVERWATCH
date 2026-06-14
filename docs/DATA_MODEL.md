# OVERWATCH Data Model

This file summarizes the Snowflake objects that support the command-intelligence
layer. The full source of truth remains `snowflake/OVERWATCH_MART_SETUP.sql`.

## Command Intelligence

| Object | Type | Purpose |
|---|---|---|
| `OVERWATCH_COMMAND_INTELLIGENCE_CAPABILITY` | Table | Ranked 12-item capability register used by setup/runbook review. |
| `OVERWATCH_REFRESH_POLICY` | Table | Surface-by-surface refresh contract for first paint, retention, live fallback, and owner accountability. |
| `OVERWATCH_SELF_MONITORING_V` | View | Summarizes app query tags, failures, latency, and bytes scanned by section. |

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
forensic diff SQL.

## FinOps and Value

| Object | Type | Purpose |
|---|---|---|
| `OVERWATCH_CONTRACT_BURN_FORECAST_V` | View | Projects month-end credits/USD and top cost driver from metering. |
| `OVERWATCH_ROI_LOG` | Table | Value ledger for Snowflake optimization and incident-prevention value. |
| `OVERWATCH_VALUE_CANDIDATE_V` | View | Derives value candidates from action queue and alert closure evidence. |
| `OVERWATCH_VALUE_AUTOMATION_HEALTH_V` | View | Shows candidate counts, ledger merge state, latest automation run, and next action. |
| `SP_OVERWATCH_AUTOMATE_VALUE_LOG` | Procedure | Merges evidence-backed candidates into `OVERWATCH_ROI_LOG`. |
| `OVERWATCH_VALUE_AUTOMATION_RUN` | Table | Logs each automated value-capture run. |

## Security and Compliance

| Object | Type | Purpose |
|---|---|---|
| `OVERWATCH_COMPLIANCE_READINESS_V` | View | Flags admin grants and high-access user activity from Snowflake metadata. |

## Optional Precompute

`snowflake/PRECOMPUTE.sql` contains optional Dynamic Tables plus fallback views:

- `DT_OVERWATCH_QUERY_HEALTH_HOURLY`
- `DT_OVERWATCH_COST_DAILY`
- `DT_OVERWATCH_TASK_CRITICAL_PATH`
- `OVERWATCH_QUERY_HEALTH_HOURLY_V`
- `OVERWATCH_COST_DAILY_V`
- `OVERWATCH_TASK_CRITICAL_PATH_V`

Dynamic Tables are not part of the base setup path. They require explicit DBA
review of refresh lag, warehouse, ownership, and monitoring budget.
