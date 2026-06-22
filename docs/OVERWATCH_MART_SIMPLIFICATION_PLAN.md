# OVERWATCH Mart Simplification Plan

Date: 2026-06-22

This plan supports the simplified four-area product direction:

- `COMMAND CENTER`
- `INCIDENTS`
- `OPTIMIZATION`
- `SETTINGS`

No legacy Snowflake object should be dropped until the simplified UI has run in Snowflake and the retirement script is explicitly approved.

## Current UI Consumption

The simplified operator UI now reads the compact command summary first:

- `MART_EXECUTIVE_OBSERVABILITY`

Legacy diagnostics remain available from `SETTINGS` only and may still consume the older marts while the migration is underway.

## Slim Target Model

Target: approximately 28 to 34 tables.

### Keep For Operator Product

| Object | Purpose |
| --- | --- |
| `OVERWATCH_SETTINGS` | Configuration and fallback settings. |
| `OVERWATCH_SCHEMA_MIGRATION` | Deployment state. |
| `OVERWATCH_LOAD_AUDIT` | Refresh diagnostics. |
| `OVERWATCH_USAGE_LOG` | App usage audit. |
| `OVERWATCH_ADMIN_ACTION_AUDIT` | Admin safety audit. |
| `OVERWATCH_ACTION_QUEUE` | Simple recommended-action queue. |
| `OVERWATCH_ALERTS` | Simplified incident source. |
| `ALERT_CONFIG` | Alert configuration. |
| `ALERT_THRESHOLDS` | Alert thresholds. |
| `ALERT_ACKNOWLEDGEMENTS` | Operator acknowledgement state. |
| `ALERT_OWNER_ROUTING` | Owner/route lookup. |
| `ALERT_NOTIFICATION_LOG` | Delivery diagnostics, settings-only. |
| `FACT_WAREHOUSE_HOURLY` | Warehouse cost/performance facts. |
| `FACT_QUERY_HOURLY` | Workload summary facts. |
| `FACT_QUERY_DETAIL_RECENT` | Bounded incident detail facts. |
| `FACT_TASK_RUN` | Task and pipeline facts. |
| `FACT_PROCEDURE_RUN` | Stored procedure facts. |
| `FACT_COST_DAILY` | Daily cost facts. |
| `FACT_STORAGE_DAILY` | Storage cost facts. |
| `FACT_CORTEX_DAILY` | Cortex spend facts. |
| `FACT_LOGIN_DAILY` | Login security facts. |
| `FACT_GRANT_DAILY` | Grant/security facts. |
| `FACT_OBJECT_CHANGE` | Recent change facts. |
| `FACT_COPY_LOAD_DAILY` | Load failure facts. |
| `MART_EXECUTIVE_OBSERVABILITY` | Compact first-paint command summary. |

### Merge Or Replace

| Object group | New shape |
| --- | --- |
| `MART_DBA_CONTROL_ROOM` | Merge into the command summary or incident queue. |
| `ALERT_EVENTS` | Merge with `OVERWATCH_ALERTS` where possible. |
| `FACT_CHARGEBACK_DAILY` | Keep only if company allocation requires it. |
| `FACT_TASK_CRITICAL_PATH` | Merge into task/pipeline incident detail. |
| `FACT_COST_MONITORING_SIGNAL` / `FACT_COST_INCIDENT_TIMELINE` | Merge into incidents and optimization recommendations. |
| `FACT_*_OPERABILITY_DAILY` | Replace with direct Critical/Warning/Healthy status. |
| Snapshot dimensions | Retain only if schema/data compare still needs them. |

### Deprecated Candidates

These objects are overmodeled for the simplified operator product. They may still be referenced by legacy diagnostics until retirement is approved.

| Object group | Deprecation reason |
| --- | --- |
| Executive scorecard objects | Score formulas are removed from primary UI. |
| Forecasting objects | Forecasting is reduced to simple cost run-rate unless explicitly revived. |
| Data trust objects | Freshness remains, trust grids move out of primary workflow. |
| Production readiness objects | Release validation belongs in runbooks/settings, not operator triage. |
| Ownership coverage objects | Incident rows need an owner/owner gap, not a coverage dashboard. |
| Value ledger objects | Proof workflow is removed; verified savings may live on action rows. |
| Closed-loop approval/evidence objects | Replace with simple action queue plus audit until a real workflow is needed. |
| Command Center question/evidence/recommendation hierarchy | The product keeps Command Center output, not the heavy evidence model. |
| Alert native deployment/remediation registry objects | Settings-only or retired after alert setup is simplified. |
| SPCS-specific objects/views | Retire unless SPCS is actively used. |

## Migration Sequence

1. Run the simplified four-area UI in Snowflake.
2. Confirm `COMMAND CENTER` first paint uses compact summaries only.
3. Confirm `INCIDENTS`, `OPTIMIZATION`, and `SETTINGS` preserve required workflows.
4. Capture 7 to 14 days of query/use telemetry for legacy diagnostic objects.
5. Mark unconsumed proof/score/forecast/workflow tables as deprecated.
6. Review the draft retirement script with the DBA owner.
7. Retire only approved objects.

## Acceptance Gate

Do not drop any object until:

- The simplified UI has passed smoke testing.
- The object is not used by a visible workflow.
- The object is not required by a scheduled task/procedure.
- A rollback path exists.
- The DBA owner explicitly approves the drop list.

