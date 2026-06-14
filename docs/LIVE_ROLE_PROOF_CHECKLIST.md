# OVERWATCH Live Role Proof Checklist

Use this checklist after deploying or refreshing OVERWATCH in Snowflake. The
goal is to prove each role sees useful data immediately, gets friendly
privilege messages when a source is unavailable, and cannot run actions outside
its operating lane.

## First Run Proof

1. Run `snowflake/OVERWATCH_MART_VALIDATION.sql` from the deployed OVERWATCH
   database and schema.
2. Confirm `MART_EXECUTIVE_OBSERVABILITY` has `KPI`, `DAILY_COST`,
   `MONTHLY_COST`, `DAILY_WORKLOAD`, `COST_DRIVER`, `QUERY_TYPE`,
   `QUERY_DATABASE`, `EXEC_STATUS`, `WAREHOUSE_PRESSURE`, `FRESHNESS`, and
   `SOURCE_STATUS` panels.
3. Confirm `OVERWATCH_REFRESH_POLICY` marks Executive Landing as
   `RUN_IN_FIRST_PAINT = TRUE` and live fallback as `FALSE`.
4. Confirm Alert Center audit tables exist:
   `ALERT_EVENTS`, `ALERT_ACKNOWLEDGEMENTS`, `ALERT_REMEDIATION_LOG`,
   `ALERT_NOTIFICATION_LOG`, `ALERT_THRESHOLDS`, and `ALERT_OWNER_ROUTING`.
5. Confirm compare tables exist:
   `OVERWATCH_RECON_CONFIG`, `OVERWATCH_RECON_RUN`, and
   `OVERWATCH_SCHEMA_DIFF_RESULT`.

## Role Expectations

| Role family | Expected access | Must verify |
|---|---|---|
| `ACCOUNTADMIN` / full DBA | All command surfaces, setup validation, alert lifecycle actions, schema compare, data compare, and controlled DBA action previews. | Executive Landing loads the metric wall; Alert History can record lifecycle audit; Schema/Data Compare config SQL is visible; Contention top fix path shows guarded SQL. |
| `SYSADMIN` / platform DBA | Workload, cost, mart, task, warehouse, and compare visibility. State-changing admin actions remain governed. | Cost & Contract first view is fast; Workload Operations shows task/query summaries; live contention degrades cleanly when a source is unavailable. |
| `_DSA` manager roles | Broad management visibility without unsafe execution. | Executive Landing, Cost & Contract, Alert Center, and Governance & Security show summary data, but dangerous remediation stays approval-gated. |
| `_DTI` analyst roles | Query, workload, data compare, and evidence review focus. | Workload Operations, Query Diagnosis, Schema/Data Compare, and read-only cost summaries are visible without setup/action controls. |
| Unknown, blank, or report roles | Restrictive report mode. | No DBA-only controls appear; unavailable Snowflake views show friendly messages; Executive Landing still renders a data-first frame when marts are granted. |

## Section Smoke By Role

- Executive Landing: first paint shows the platform score, executive summary
  grid, KPI rows, and `Executive Pressure Index`.
- Every primary navigation surface: first paint shows a scoped command board
  before workflow buttons. Buttons should be drill-through, not the only way to
  see useful data.
- DBA Control Room: morning queue loads without saved views or hidden workflow
  toggles.
- Alert Center: incident board loads; lifecycle audit requires a note and writes
  only `ALERT_ACKNOWLEDGEMENTS` and `ALERT_REMEDIATION_LOG`.
- Cost & Contract: first view shows the cost load contract; heavy proof stays
  behind explicit refresh.
- Workload Operations: subsection navigation opens detail immediately.
- Contention Center: top fix path displays route, blocker, waiter, precheck,
  manual SQL state, and verification guidance.
- Workload Operations: Schema Compare registers schema-object checks; Data Compare
  registers count/hash/bucket/forensic checks and exposes recon history SQL.

## Failure Rules

- If a role gets a raw Snowflake privilege traceback, treat it as a bug.
- If Executive Landing needs a live `ACCOUNT_USAGE` scan to paint, treat it as a
  performance regression.
- If a button silently changes Snowflake state without a preview, approval, and
  audit row, treat it as a security regression.
- If a summary screen opens to empty explanatory text instead of metrics,
  charts, or clear "not loaded" data frames, treat it as a product regression.
