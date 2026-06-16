# OVERWATCH Command Intelligence Runbook

This runbook is the production hardening target for the next version of
OVERWATCH. The goal is not more pages. The goal is earlier detection, cleaner
root cause, fewer clicks, and evidence-backed DBA action.

## Operating Principle

Every section should show useful data immediately:

1. Status strip
2. KPI or priority row
3. Compact work grid or top evidence table
4. Drilldown/action controls only after the main signal is visible

Buttons should not hide the point of a page. They should load heavier evidence,
route work, export proof, or preview guarded SQL.

## Priority Capabilities

| Rank | Capability | Primary Surface | Production Target |
|---:|---|---|---|
| 1 | Detection and Root-Cause Engine | Alert Center, DBA Control Room | Correlate query, task, login, cost, and object-change symptoms into one incident route. |
| 2 | Task/Pipeline Critical Path Brain | Workload Operations | Rank root task, child failure, retry pattern, late risk, and downstream blast radius. |
| 3 | Data Quality and Reconciliation Center | Workload Operations | Compare schema/database pairs with counts, hash buckets, freshness, schema drift, and sampled diffs. |
| 4 | Cost Run-Rate and Attribution Monitor | Cost & Contract | Forecast contract burn and rank top cost drivers from metering facts. |
| 5 | Alert Lifecycle 2.0 | Alert Center | Acknowledge, assign, suppress, resolve, comment, route, and audit alert work. |
| 6 | Fact-Grounded AI Query Diagnosis | Workload Operations | Use Cortex only with exact query/profile/object evidence and required verification SQL. |
| 7 | OVERWATCH Query-Tag Cost Controls | Cost & Contract | Track app-attributed query cost when query tags are available, without exposing benchmark telemetry in the UI. |
| 8 | Scheduled Mart Layer | Snowflake setup | Keep first paint fast; make live ACCOUNT_USAGE scans explicit. |
| 9 | Security Activity Monitoring | Security Monitoring, Executive Landing | Show admin grants, access spikes, dormant activity, risky shares, and action evidence. |
| 10 | Multi-Account / Org View | Executive Landing, Cost & Contract | Optional org-level rollup when the Snowflake role has organization usage privileges. |
| 11 | Data-First Navigation Contract | App shell, every primary section | Show scoped KPIs and summaries on first section click without saved-state persistence or global mode toggles. |
| 12 | Monitoring Docs and Runbooks | Repo docs | Keep setup, privileges, failure modes, rollback, and operating rules with the code. |

## Cost Run-Rate Monitoring

Cost & Contract should explain spend movement before anyone changes a warehouse
or assumes a contract issue. The first read should use compact facts for current
credits, prior-window movement, Cortex spend, top drivers, and open action
queue items.

Guardrail:

Do not treat run-rate projections as remediation authority. They point to the
next investigation: top warehouse, service, query/user attribution, Cortex
usage, or a routed action queue item.

## Data Reconciliation

For schema/database sameness checks:

- Use `INFORMATION_SCHEMA` to enumerate all comparable tables and columns.
- Compare object inventory first.
- Compare row counts next.
- Use `HASH_AGG(*)` only when table size and warehouse budget allow it.
- For large tables, hash by configured key buckets.
- If hashes differ, generate sample-diff SQL before running full forensic
  comparisons.
- Store run results in `OVERWATCH_RECON_RUN` and schema differences in
  `OVERWATCH_SCHEMA_DIFF_RESULT`.

## AI Query Diagnosis

Cortex should not be asked for generic tuning advice. The prompt contract must
include:

- `query_id` and `query_hash`
- owner/user/role/warehouse/database/schema
- elapsed, compile, execution, and queue time
- bytes scanned and rows produced
- partitions scanned/total
- local and remote spill
- table context and object size
- exact verification query for the proposed fix

If evidence is missing, the AI answer must say what is missing instead of
inventing a recommendation.

## Setup Decision

Use `snowflake/OVERWATCH_MART_SETUP.sql` as the single deployable DDL document.
Scheduled tasks and transient facts are the default setup. Dynamic-table and
separate native-alert template scripts have been retired to keep deployment
honest and easier to support.

## Required Privilege Families

- Read access to selected `SNOWFLAKE.ACCOUNT_USAGE` views.
- Optional read access to `SNOWFLAKE.ORGANIZATION_USAGE` for org rollups.
- Create/alter privileges in the OVERWATCH database/schema for setup objects.
- Task/warehouse ownership or delegated privileges for scheduled refresh.
- Notification integration privileges only if external notifications are used.
- Optional Snowflake ALERT objects should be added to the consolidated setup
  only after the monitoring warehouse, integration, route, and audit tables are
  approved.

## Daily DBA Flow

1. Open Executive Landing for spend, workload, alert, and pressure signals.
2. Open DBA Control Room for root-cause, critical path, and morning queue.
3. Open Alert Center for alert lifecycle and detection catalog.
4. Open Workload Operations for task, contention, query, and reconciliation work.
5. Open Cost & Contract for burn forecast, attribution, Cortex spend, and the action queue.
6. Validate closure through post-period telemetry before marking savings complete.
