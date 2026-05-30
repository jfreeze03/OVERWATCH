# OVERWATCH Snowflake Architecture

OVERWATCH should run as a thin Streamlit command center backed by a small
Snowflake mart. The app should not repeatedly scan broad `ACCOUNT_USAGE` views
for every user click. Expensive account-wide history is loaded on a schedule,
compressed into facts/dimensions, and read cheaply by the UI.

The deployable setup script is:

```text
snowflake/OVERWATCH_MART_SETUP.sql
```

## Runtime Shape

- `OVERWATCH_WH`: dedicated X-Small warehouse for mart refresh tasks
- `DBA_MAINT_DB.OVERWATCH`: app persistence schema and mart schema
- Streamlit app: reads compact marts first, direct Snowflake metadata only for
  live drilldowns and guarded admin actions
- Refresh tasks: hourly for operational telemetry, daily for slower governance
  snapshots

## Cost Controls

- X-Small refresh warehouse
- `AUTO_SUSPEND = 60`
- hourly refresh after likely `ACCOUNT_USAGE` latency
- transient mart tables for history that can be rebuilt
- short retention for query/task/procedure detail
- daily retention for governance and storage facts
- `FACT_MONITORING_COST_DAILY` to show what OVERWATCH itself costs

## Tables

| Table | Type | Purpose | Primary Sources | Cadence |
|---|---:|---|---|---|
| `OVERWATCH_SETTINGS` | Permanent | Credit price, retention, feature flags | Seed/config | Manual |
| `OVERWATCH_COMPANY_SCOPE` | Permanent | ALFA/Trexis scoping rules | Seed/config | Manual |
| `OVERWATCH_LOAD_AUDIT` | Permanent | Mart refresh audit trail | Procedures | Every load |
| `OVERWATCH_ADMIN_ACTION_AUDIT` | Permanent | DBA action audit trail | App/admin controls | Event-driven |
| `OVERWATCH_USAGE_LOG` | Permanent | App query telemetry and guardrails | App `run_query()` | Event-driven |
| `OVERWATCH_ACTION_QUEUE` | Permanent | Recommendations and operational work queue | App/mart findings | Event-driven |
| `OVERWATCH_ALERTS` | Permanent | Teams/email alert history | Alerts/recommendations | Event-driven |
| `OVERWATCH_ROI_LOG` | Permanent | Optimization wins and ROI evidence | App/manual entries | Event-driven |
| `FACT_WAREHOUSE_HOURLY` | Transient | Compute credits and warehouse cost | `WAREHOUSE_METERING_HISTORY` | Hourly |
| `FACT_QUERY_HOURLY` | Transient | Query volume, failures, latency, queue pressure | `QUERY_HISTORY` | Hourly |
| `FACT_QUERY_DETAIL_RECENT` | Transient | Recent drilldown query rows | `QUERY_HISTORY` | Hourly |
| `FACT_TASK_RUN` | Transient | Task graph run status and failures | `TASK_HISTORY` | Hourly |
| `DIM_TASK_SNAPSHOT` | Transient | Current task metadata | `TASKS` | Hourly |
| `DIM_PROCEDURE_SNAPSHOT` | Transient | Current procedure metadata | `PROCEDURES` | Hourly |
| `FACT_PROCEDURE_RUN` | Transient | Recent `CALL` history and procedure failures | `QUERY_HISTORY` | Hourly |
| `FACT_LOGIN_DAILY` | Transient | Login posture and client activity | `LOGIN_HISTORY` | Daily |
| `FACT_OBJECT_CHANGE` | Transient | DDL, object, and drift signals | `QUERY_HISTORY` | Daily |
| `FACT_GRANT_DAILY` | Transient | Role/user grant snapshot | `GRANTS_TO_USERS` | Daily |
| `FACT_STORAGE_DAILY` | Transient | Database storage and estimated storage cost | `DATABASE_STORAGE_USAGE_HISTORY` | Daily |
| `FACT_CORTEX_DAILY` | Transient | Cortex Code usage where views exist | Cortex usage history views | Hourly chained |
| `FACT_MONITORING_COST_DAILY` | Transient | Cost to operate OVERWATCH | Metering and query tags | Daily |
| `MART_DBA_CONTROL_ROOM` | Transient | DBA command-center summary | Mart facts | Hourly chained |

## Tasks and Load Flow

```text
OVERWATCH_LOAD_HOURLY
  -> SP_OVERWATCH_LOAD_HOURLY()
  -> OVERWATCH_LOAD_CORTEX
       -> SP_OVERWATCH_LOAD_CORTEX()
       -> OVERWATCH_REFRESH_CONTROL_ROOM
            -> SP_OVERWATCH_REFRESH_CONTROL_ROOM()

OVERWATCH_LOAD_DAILY
  -> SP_OVERWATCH_LOAD_DAILY()
```

`OVERWATCH_LOAD_HOURLY` runs hourly at minute 25 Central. It refreshes recent
warehouse, query, task, procedure, and metadata snapshots.

`OVERWATCH_LOAD_CORTEX` is chained after hourly refresh. It is best-effort and
logs `SKIPPED` if Cortex Code usage views are unavailable in the account.

`OVERWATCH_REFRESH_CONTROL_ROOM` builds compact ALFA/Trexis exception summaries
for Account Health and DBA Control Room views.

`OVERWATCH_LOAD_DAILY` runs at 6:15 AM Central and refreshes login posture,
grant snapshots, object changes, storage, and monitoring-cost facts.

## App Query Strategy

Use mart tables for:

- Account Health KPI tiles
- DBA Control Room exception summaries
- Cost Center warehouse/user trend panels
- Warehouse Health hourly summaries
- Security posture rollups
- stored procedure and task graph summary views
- leadership/export reports

Use direct Snowflake views only for:

- currently running queries
- query cancellation
- warehouse/task suspend or resume
- drilldowns that need exact recent SQL text
- setup/diagnostic screens that intentionally validate privileges

## Retention Defaults

- Recent query/task/procedure detail: 35 days
- Hourly facts: 400 days
- Daily facts: 400 days
- App state and audit logs: permanent until manually archived

These defaults are stored in `OVERWATCH_SETTINGS` and can be adjusted after
deployment.

## Deployment Steps

1. Run `snowflake/OVERWATCH_MART_SETUP.sql` in Snowsight as a platform-admin
   role.
2. Confirm `OVERWATCH_WH` exists and is suspended after setup.
3. Confirm `OVERWATCH_LOAD_HOURLY` and `OVERWATCH_LOAD_DAILY` are resumed.
4. Run the smoke queries at the end of the setup script.
5. Point the app role at `DBA_MAINT_DB.OVERWATCH`.
6. Gradually migrate heavy app sections from direct `ACCOUNT_USAGE` scans to
   mart reads.

## Production Principle

If a metric is needed on most pages or every morning, it belongs in the mart. If
it is needed only after a DBA clicks into a specific incident, it can remain a
live drilldown.

## Snowflake References

- Account Usage `TASKS` view:
  https://docs.snowflake.com/en/sql-reference/account-usage/tasks
- Account Usage `TASK_HISTORY` view:
  https://docs.snowflake.com/en/sql-reference/account-usage/task_history
- Account Usage `PROCEDURES` view:
  https://docs.snowflake.com/en/sql-reference/account-usage/procedures
