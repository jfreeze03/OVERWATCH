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
| 4 | Predictive FinOps and Automated Value Log | Cost & Contract, Snowflake Value | Forecast contract burn and auto-capture verified DBA value from evidence. |
| 5 | Alert Lifecycle 2.0 | Alert Center | Acknowledge, assign, suppress, resolve, comment, route, and audit alert work. |
| 6 | Fact-Grounded AI Query Diagnosis | Workload Operations | Use Cortex only with exact query/profile/object evidence and required verification SQL. |
| 7 | OVERWATCH Self-Monitoring | Cost & Contract, Setup | Track app query cost, failures, slow sections, and tagged runtime behavior. |
| 8 | Precomputed Mart / Dynamic Table Layer With Fallback | Setup | Keep first paint fast; make live ACCOUNT_USAGE scans explicit. |
| 9 | Compliance Readiness Scorecard | Governance & Security, Executive Landing | Show admin grants, access spikes, dormant activity, and risky posture with owner actions. |
| 10 | Multi-Account / Org View | Executive Landing, Cost & Contract | Optional org-level rollup when the Snowflake role has organization usage privileges. |
| 11 | Data-First Navigation Contract | App shell, every primary section | Show scoped KPIs and summaries on first section click without saved-state persistence or global mode toggles. |
| 12 | Architecture Docs and Runbooks | Repo docs, Setup & Runbook | Keep setup, privileges, failure modes, rollback, and operating rules with the code. |

## Automated Snowflake Value Log

The Snowflake Value Log should not depend on DBAs remembering to update it.
Manual logging remains available, but it is a fallback.

Default value sources:

- `OVERWATCH_ACTION_QUEUE`: fixed cost actions with estimated savings and
  post-period verification.
- `ALERT_EVENTS`: resolved critical/high/medium incidents with impact evidence.
- `OVERWATCH_WORKLOAD_RECOVERY_AUDIT`: recovery actions that improve runtime,
  queue pressure, task success, or SLA state.
- `QUERY_HISTORY`: query hash improvements after a targeted optimization.

Value states:

- `ESTIMATED`: candidate value exists, but post-period proof is incomplete.
- `VERIFIED`: owner-approved action has measured before/after evidence.
- `REJECTED`: no measurable value was proven after the verification window.

Guardrail:

Do not present estimated value as verified savings. Verified value requires an
evidence source, owner/action context, measured result, and timestamp.

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

## Precompute Decision

Use `snowflake/PRECOMPUTE.sql` only after review. Dynamic Tables are optional.
Fallback views keep the base setup lower-risk.

Use Dynamic Tables when:

- `OVERWATCH_WH` has an approved monitoring budget.
- Target lag is acceptable for DBA morning triage.
- The setup role can own and operate refresh objects.

Use fallback views/tasks when:

- Dynamic Tables are not approved.
- You need caller-mode transparency over refresh behavior.
- You want to reduce deployment risk while production hardening continues.

## Required Privilege Families

- Read access to selected `SNOWFLAKE.ACCOUNT_USAGE` views.
- Optional read access to `SNOWFLAKE.ORGANIZATION_USAGE` for org rollups.
- Create/alter privileges in the OVERWATCH database/schema for setup objects.
- Task/warehouse ownership or delegated privileges for scheduled refresh.
- Notification integration privileges only if external notifications are used.
- Optional Snowflake ALERT objects can be deployed from
  `snowflake/OVERWATCH_NATIVE_ALERT_TEMPLATES.sql` after the monitoring
  warehouse, integration, owner route, and audit tables are approved.

## Daily DBA Flow

1. Open Executive Landing for platform score and top maturity blockers.
2. Open DBA Control Room for root-cause, critical path, and morning queue.
3. Open Alert Center for alert lifecycle and detection catalog.
4. Open Workload Operations for task, contention, query, and reconciliation work.
5. Open Cost & Contract for burn forecast, action queue, and value automation.
6. Use Snowflake Value to verify that automated value capture is working.
