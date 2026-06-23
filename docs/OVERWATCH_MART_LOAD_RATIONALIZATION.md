# OVERWATCH Mart Load Rationalization Inventory

Date: 2026-06-23

This is a static planning inventory only. It does not drop, disable, rename, or
rewrite Snowflake mart objects. Use it to plan a later mart-load consolidation
after route metrics confirm which advanced surfaces are actively used.

## Current Mart Families

| Family | Representative objects | Primary consumers | Current posture |
|---|---|---|---|
| Executive first-paint summaries | `MART_EXECUTIVE_OBSERVABILITY`, `MART_DBA_CONTROL_ROOM`, `MART_EXECUTIVE_SCORECARD_SUMMARY`, `MART_EXECUTIVE_FORECAST_SUMMARY`, `MART_CHANGE_INTELLIGENCE_SUMMARY`, `MART_CLOSED_LOOP_OPERATIONS_SUMMARY`, `MART_COMMAND_CENTER_SUMMARY` | Executive Landing, DBA Control Room | Keep. These are fast first-paint inputs and should stay mart-first. |
| Core cost and spend facts | `FACT_COST_DAILY`, `FACT_CORTEX_DAILY`, `FACT_WAREHOUSE_HOURLY`, `FACT_CHARGEBACK_DAILY`, `FACT_COST_MONITORING_SIGNAL`, `FACT_COST_INCIDENT_TIMELINE` | Cost & Contract, Cost Center, Warehouse Health, Alert Center | Keep, then rationalize shared load plans around daily/hourly facts. |
| Query and workload facts | `FACT_QUERY_HOURLY`, `FACT_QUERY_DETAIL_RECENT`, `FACT_TASK_RUN`, `FACT_TASK_CRITICAL_PATH`, `FACT_PROCEDURE_RUN`, `DIM_TASK_SNAPSHOT`, `DIM_PROCEDURE_SNAPSHOT`, `DIM_TABLE_SNAPSHOT` | Workload Operations, Task Management, DBA Control Room, Stored Proc Tracker | Keep. Candidate area for shared loader contracts before any object decisions. |
| Security and access facts | `FACT_LOGIN_DAILY`, `FACT_GRANT_DAILY`, `FACT_SECURITY_OPERABILITY_DAILY` | Security Monitoring, Alert Center, Executive Landing | Keep. Access and MFA fallbacks remain bounded and explicit. |
| Storage and data movement facts | `FACT_STORAGE_DAILY`, `FACT_COPY_LOAD_DAILY`, `FACT_OBJECT_CHANGE` | Cost & Contract, Account Health, Change Drift, Workload Operations | Keep. Route metrics should decide whether advanced evidence stays separate. |
| Workflow operability facts | `FACT_ACCOUNT_HEALTH_OPERABILITY_DAILY`, `FACT_CHANGE_CONTROL_OPERABILITY_DAILY`, `FACT_WAREHOUSE_OPERABILITY_DAILY` | Account Health, Change Drift, Warehouse Health | Keep. These are workflow-specific review/readiness facts, not general rollup facts. |
| Governance and evidence tables | `OVERWATCH_CHANGE_CONTROL_EVIDENCE`, `OVERWATCH_DBA_CHECKLIST_HISTORY`, access-review and setting-review tables | Change Drift, Account Health, Security Monitoring, Warehouse Health | Keep. These are audit/evidence stores and should not be folded into first-paint facts. |

## Daily Operator Dependency Groups

| Daily workflow group | Preferred mart inputs | Fallback posture |
|---|---|---|
| Morning executive and DBA brief | `MART_EXECUTIVE_OBSERVABILITY`, `MART_DBA_CONTROL_ROOM`, `FACT_COST_DAILY`, `FACT_QUERY_HOURLY`, `FACT_TASK_RUN` | Cached/empty shell first; explicit live fallback only where already gated. |
| Cost watch and contract pacing | `FACT_COST_DAILY`, `FACT_WAREHOUSE_HOURLY`, `FACT_CORTEX_DAILY`, `FACT_CHARGEBACK_DAILY` | Live account metering remains explicit and bounded. |
| Reliability and task triage | `FACT_TASK_RUN`, `FACT_TASK_CRITICAL_PATH`, `FACT_QUERY_DETAIL_RECENT`, `DIM_TASK_SNAPSHOT` | `TASK_HISTORY` and `QUERY_HISTORY` loaders remain explicit or workflow-gated. |
| Security review | `FACT_LOGIN_DAILY`, `FACT_GRANT_DAILY`, security summary marts | Live `ACCOUNT_USAGE` access checks remain bounded and detail-gated. |
| Alert operations | Alert history/action/delivery tables plus selected fact signals | Detection catalog and delivery/admin evidence stay explicit-load. |
| Change review | `FACT_OBJECT_CHANGE`, `FACT_CHANGE_CONTROL_OPERABILITY_DAILY`, `OVERWATCH_CHANGE_CONTROL_EVIDENCE` | Object metadata and DBA Tools evidence stay delegated and guarded. |

## Consolidation Candidates

These are candidates for a later pass, not approved removals:

| Candidate consolidation | Why it may help | Required proof before action |
|---|---|---|
| Daily cost spine | Fold duplicated cost/service/warehouse movement loads into a single daily/hourly cost load plan. | Prove Cost & Contract, Cost Center, Warehouse Health, and Executive Landing all preserve exact source labels and scoped filters. |
| Workload health spine | Align query hourly/detail, task, procedure, and copy-load loaders behind a shared workload load plan. | Prove Task Management, Query Investigation, Contention, and Stored Proc Tracker keep explicit gates and bounded live fallbacks. |
| Security/access spine | Keep MFA, grants, failed logins, and access changes behind a shared access-health load plan. | Prove ALFA/Trexis/ALL scoping and admin-only access checks remain unchanged. |
| Workflow operability rollups | Standardize `*_OPERABILITY_DAILY` fact column contracts across Account Health, Change Drift, Security, and Warehouse Health. | Prove workflow-specific evidence/readiness fields do not lose audit detail. |
| Executive summary marts | Confirm whether scorecard, forecast, change, closed-loop, and command summaries can share load scheduling. | Route metrics must show usage patterns; do not collapse distinct executive workflows prematurely. |

## Advanced/Admin Evidence

Keep these out of first-paint daily marts unless route metrics prove otherwise:

- Change-control evidence snapshots and closure analytics.
- Checklist history snapshots.
- Warehouse setting review snapshots.
- Security access-review snapshots and proof tables.
- Alert native catalog, remediation policy, dry-run, and suppression evidence.
- Production readiness, scorecard formulas, value ledger, and data trust proof grids.

## Target Shape

The earlier target of roughly 28-34 daily operator mart tables remains a
directional goal. The safe path is:

1. Inventory current app dependencies and source labels.
2. Add contract tests around mart object names and loader public surfaces.
3. Consolidate loader plans, not objects, first.
4. Run live Snowflake regression in a credentialed account.
5. Only then propose object retirement or rebuild scripts.

## No-Change Guardrails

- No mart objects were dropped or disabled in this pass.
- No live Snowflake migration was run.
- `snowflake/OVERWATCH_MART_SETUP.sql` remains the source of deployable mart DDL.
- `snowflake/OVERWATCH_MART_DROP.sql` remains a reset-only runbook tool, not a rationalization plan.
