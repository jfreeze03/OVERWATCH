# OVERWATCH Mart Object Review

Static scan date: 2026-06-16

This review inventories the deployable Snowflake objects in `snowflake/OVERWATCH_MART_SETUP.sql`
and cross-checks them against `.overwatch_final` app references. It is a static code scan,
not a live database dependency graph.

## Counts

| Object type | Count |
| --- | ---: |
| Tables | 59 |
| Procedures | 9 |
| Tasks | 8 |
| Views | 3 |
| Total | 79 |

Objects with direct app references: 62.

Objects without direct app references: 17. Most of these are refresh procedures, scheduled
tasks, or support tables used inside the setup SQL.

## Keep

These are directly used by app surfaces, validation, or core persisted DBA workflows.

| Object family | Why it stays |
| --- | --- |
| `MART_EXECUTIVE_OBSERVABILITY`, `MART_DBA_CONTROL_ROOM` | Fast first-paint telemetry for Executive Landing and DBA Control Room. |
| `FACT_COST_DAILY`, `FACT_CORTEX_DAILY`, `FACT_QUERY_HOURLY`, `FACT_QUERY_DETAIL_RECENT`, `FACT_WAREHOUSE_HOURLY` | Main cost, Cortex, workload, and warehouse health marts used by Cost & Contract, workload, query, and warehouse sections. |
| `FACT_TASK_RUN`, `FACT_TASK_CRITICAL_PATH`, `FACT_PROCEDURE_RUN`, `DIM_TASK_SNAPSHOT`, `DIM_PROCEDURE_SNAPSHOT`, `DIM_TABLE_SNAPSHOT` | Task/procedure health, task graph blast radius, stored procedure context, and workload reliability. |
| `OVERWATCH_ACTION_QUEUE`, `OVERWATCH_ALERTS`, `OVERWATCH_ADMIN_ACTION_AUDIT`, alert rule/log tables | Alert Center, recommendations, action queue, admin audit, and delivery/remediation history. |
| `OVERWATCH_RECON_CONFIG`, `OVERWATCH_RECON_RUN`, `OVERWATCH_SCHEMA_DIFF_RESULT` | Schema/data compare persistence and generated DDL review. |
| `OVERWATCH_WAREHOUSE_SETTING_REVIEW`, `FACT_WAREHOUSE_OPERABILITY_DAILY` | Warehouse change review, settings audit, and capacity/control telemetry. |
| `OVERWATCH_WORKLOAD_RECOVERY_AUDIT`, `OVERWATCH_WORKLOAD_RECOVERY_AUDIT_LATEST_V` | Task/procedure recovery evidence and latest recovery status. |

## Keep As Internal Plumbing

These do not have direct app reads, but they drive scheduled mart refresh or internal
refresh bookkeeping. They should not be removed unless their downstream facts are also
removed or replaced.

| Object | Current purpose |
| --- | --- |
| `SP_OVERWATCH_LOAD_HOURLY`, `SP_OVERWATCH_LOAD_DAILY`, `SP_OVERWATCH_LOAD_CORTEX` | Load the hourly, daily, and Cortex facts consumed by app marts. |
| `SP_OVERWATCH_REFRESH_CONTROL_ROOM`, `SP_OVERWATCH_REFRESH_EXECUTIVE_OBSERVABILITY`, `SP_OVERWATCH_REFRESH_AUTOMATION` | Refresh compact summary marts/views used by first-paint surfaces and automation health. |
| `SP_OVERWATCH_PRUNE` | Retention cleanup for transient facts. |
| `OVERWATCH_LOAD_HOURLY`, `OVERWATCH_LOAD_DAILY`, `OVERWATCH_LOAD_CORTEX`, `OVERWATCH_REFRESH_CONTROL_ROOM`, `OVERWATCH_EXECUTIVE_OBSERVABILITY_REFRESH`, `OVERWATCH_AUTOMATION_REFRESH` | Scheduled wrappers around the refresh procedures. |
| `OVERWATCH_LOAD_AUDIT` | Refresh bookkeeping written by setup procedures. It is not surfaced today, but it is useful for live refresh troubleshooting. |
| `OVERWATCH_OWNER_TAG_NAMES`, `DIM_COST_OWNER_TAG` | Owner tag configuration and snapshot used in chargeback fact construction. Keep only if chargeback by owner tag remains in scope. |

## Pruned Metadata Objects

These were removed from the deployable setup because the app does not read them
and the same information is already maintained in docs, Python config, or
read-only validation SQL.

| Object | Replacement |
| --- | --- |
| `OVERWATCH_COMMAND_INTELLIGENCE_CAPABILITY` | Capability direction remains in docs and app code, not a static mart table. |
| `OVERWATCH_REFRESH_POLICY` | Refresh contract remains in `docs/REFRESH_ARCHITECTURE.md` and inline validation SQL. |
| `OVERWATCH_COMPANY_SCOPE` | Company/scope filtering remains in app config and Python scope helpers. |
| `OVERWATCH_COMPLIANCE_READINESS_V` | Security Monitoring reads native Snowflake telemetry directly or through relevant future facts. |

## Retire Or Merge Candidates

These have no direct app reference and look more like metadata/control-plane scaffolding
than DBA monitoring surfaces. Remove only after updating tests and validation SQL.

| Object | Recommendation |
| --- | --- |
| `FACT_MONITORING_COST_DAILY` | Candidate to merge with `FACT_COST_DAILY` / `MART_EXECUTIVE_OBSERVABILITY` if no unique app-facing metric remains. It is loaded in setup but not read by the app. |

## Next Pruning Rule

Do not prune by table count alone. For each candidate, confirm:

1. No app read path.
2. No refresh procedure output dependency.
3. No validation/test contract that still represents desired production behavior.
4. No required audit/history retention purpose.
5. A replacement exists, or the feature is intentionally out of product scope.

The highest-confidence cleanup pass is to remove metadata-only objects first, then merge
overlapping cost facts after the new cost efficiency/RCA metrics settle.
