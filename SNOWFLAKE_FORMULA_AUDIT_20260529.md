# Snowflake Formula Audit - 2026-05-29

## Executive Summary

The repository is generally strong on defensive patterns such as `NULLIF(..., 0)` for safe division, `ROW_NUMBER()` for latest-row selection, and progressive fallbacks when Snowflake columns vary by environment. The biggest correctness risks are concentrated in four areas:

1. Live-state metrics are sometimes derived from `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY`, which Snowflake documents as having up to 45 minutes of latency. That makes some "running", "queued", and "blocked" metrics risky for operational use.
2. Warehouse credit formulas sometimes label `CREDITS_USED` as compute-only even though Snowflake documents `CREDITS_USED` in `WAREHOUSE_METERING_HISTORY` as the sum of `CREDITS_USED_COMPUTE` and `CREDITS_USED_CLOUD_SERVICES`.
3. A few calculations silently substitute `ALFA` for missing `COMPANY`, which can misclassify cross-company or legacy rows.
4. Some business metrics are valid as estimates, but the repo does not always distinguish "estimated business math" from "Snowflake-exact metering math."

The most important fixes are to standardize live-query sourcing, tighten credit attribution labels and formulas, and remove default-company coercions where they can alter meaning.

## Files Reviewed

Files scanned for formulas and metrics:

- `_deploy_OVERWATCH/README.md`
- `_deploy_OVERWATCH/OVERWATCH_DOCUMENTATION.md`
- `_deploy_OVERWATCH/.overwatch_final/app.py`
- `_deploy_OVERWATCH/.overwatch_final/config.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/account_health.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/adoption_analytics.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/cortex_monitor.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/cost_center.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/data_sharing.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/dba_tools.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/detailed_diagnosis.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/live_monitor.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/object_change_monitor.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/pipeline_health.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/platform_topology.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/query_analysis.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/query_search.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/recommendations.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/security_access.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/service_health.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/snowflake_value.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/spcs_tracker.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/storage_monitor.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/stored_proc_tracker.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/task_management.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/usage_overview.py`
- `_deploy_OVERWATCH/.overwatch_final/sections/warehouse_health.py`
- `_deploy_OVERWATCH/.overwatch_final/utils/action_queue.py`
- `_deploy_OVERWATCH/.overwatch_final/utils/admin.py`
- `_deploy_OVERWATCH/.overwatch_final/utils/alerts.py`
- `_deploy_OVERWATCH/.overwatch_final/utils/company_filter.py`
- `_deploy_OVERWATCH/.overwatch_final/utils/compatibility.py`
- `_deploy_OVERWATCH/.overwatch_final/utils/cost.py`
- `_deploy_OVERWATCH/.overwatch_final/utils/data.py`
- `_deploy_OVERWATCH/.overwatch_final/utils/display.py`
- `_deploy_OVERWATCH/.overwatch_final/utils/logging.py`
- `_deploy_OVERWATCH/.overwatch_final/utils/metadata.py`
- `_deploy_OVERWATCH/.overwatch_final/utils/optimization_advisor.py`
- `_deploy_OVERWATCH/.overwatch_final/utils/query.py`
- `_deploy_OVERWATCH/.overwatch_final/utils/scorecards.py`
- `_deploy_OVERWATCH/.overwatch_final/utils/session.py`
- `_deploy_OVERWATCH/.overwatch_final/utils/setup_bundle.py`

Primary Snowflake references used:

- [Functions and operators](https://docs.snowflake.com/en/sql-reference/functions-all)
- [DATEADD](https://docs.snowflake.com/en/sql-reference/functions/dateadd)
- [DATEDIFF](https://docs.snowflake.com/en/sql-reference/functions/datediff)
- [DATE_TRUNC](https://docs.snowflake.com/en/sql-reference/functions/date_trunc)
- [COALESCE](https://docs.snowflake.com/en/sql-reference/functions/coalesce)
- [NULLIF](https://docs.snowflake.com/en/sql-reference/functions/nullif)
- [AVG](https://docs.snowflake.com/en/sql-reference/functions/avg.html)
- [COUNT](https://docs.snowflake.com/en/sql-reference/functions/count)
- [Aggregate functions and NULL behavior](https://docs.snowflake.com/en/sql-reference/functions-aggregation)
- [Data type conversion / coercion](https://docs.snowflake.com/en/sql-reference/data-type-conversion)
- [QUERY_HISTORY view](https://docs.snowflake.com/en/sql-reference/account-usage/query_history)
- [QUERY_HISTORY table functions](https://docs.snowflake.com/en/sql-reference/functions/query_history)
- [WAREHOUSE_METERING_HISTORY view](https://docs.snowflake.com/en/sql-reference/account-usage/warehouse_metering_history)

## Formula Inventory

| File | Object/function/page | Formula or calculation | Purpose | Snowflake doc reference | Status |
| --- | --- | --- | --- | --- | --- |
| `sections/usage_overview.py` | `_load_overview()` | `100 * success_expr / NULLIF(COUNT(*), 0)` | Query success rate | `NULLIF`, `COUNT`, `QUERY_HISTORY` | Valid |
| `sections/usage_overview.py` | `_load_overview()` | `AVG(total_elapsed_time) / 1000`, `AVG(execution_time) / 1000` | Query latency KPIs | `AVG`, `QUERY_HISTORY` | Valid |
| `sections/usage_overview.py` | `_load_overview()` | metering split between `credits_used`, `credits_used_compute`, `credits_used_cloud_services` | Credit totals and trend | `WAREHOUSE_METERING_HISTORY` | Valid |
| `sections/account_health.py` | live/query stats blocks | counts based on `ACCOUNT_USAGE.QUERY_HISTORY.execution_status` for running/queued/blocked | Executive live activity | `QUERY_HISTORY view`, `QUERY_HISTORY table functions` | Risky |
| `sections/live_monitor.py` | `_live_panel()` | uses `INFORMATION_SCHEMA.QUERY_HISTORY()` first, AU fallback second | Live/recent query monitor | `QUERY_HISTORY table functions`, `QUERY_HISTORY view` | Valid with caveat |
| `utils/cost.py` | `build_metered_credit_cte()` | `SUM(credits_used) AS hourly_compute_credits` | Per-query credit allocation | `WAREHOUSE_METERING_HISTORY` | Incorrect label / Risky formula |
| `utils/cost.py` | `build_idle_warehouse_sql()` | idle-hour warehouse cost based on metering minus query activity | Idle warehouse detector | `WAREHOUSE_METERING_HISTORY`, `QUERY_HISTORY` | Valid if labeled total warehouse credits |
| `sections/cost_center.py` | attribution views | `SUM(COALESCE(pqc.metered_credits,0))` by role/db/schema/app/proc | Chargeback / cost attribution | `SUM`, `COALESCE` | Valid |
| `sections/stored_proc_tracker.py` | procedure rollup | `SUM(COALESCE(ch.metered_credits,0))`, `SUM(ch.credits_used_cloud_services)` | Child-query procedure cost | `SUM`, `COALESCE` | Risky |
| `sections/dba_tools.py` | pre-aggregation DDL | `SUM(credits_used) AS compute_credits, SUM(credits_used) AS total_credits` | Materialized warehouse credit table | `WAREHOUSE_METERING_HISTORY` | Incorrect |
| `sections/dba_tools.py` | storage dollar input | `AVG(average_database_bytes + average_failsafe_bytes) / POWER(1024,4)` | Storage conversion input | `AVG`, aggregate NULL behavior | Needs clarification |
| `sections/service_health.py` | `_load_service_health()` | error/queue/blocked counts + p95 latency | Service posture scoring | `QUERY_HISTORY`, `PERCENTILE_CONT` | Mostly valid |
| `utils/scorecards.py` | `executive_health_score()` | weighted score across failure, queue, task, storage, burn | Executive rollup | Python business logic | Needs clarification |
| `utils/scorecards.py` | `service_health_scorecard()` | weighted service scoring | Service rollup | Python business logic | Needs clarification |
| `sections/snowflake_value.py` | value summary | `SUM(SAVINGS_CREDITS * 30)`, `SUM(SAVINGS_MONTHLY * 12)` | ROI rollup | Business estimate | Needs clarification |
| `utils/action_queue.py` | `load_action_queue()` | `COALESCE(COMPANY, 'ALFA')` | Company scoping | `COALESCE`, type conversion | Risky |

## Issues Found

### 1. `ACCOUNT_USAGE.QUERY_HISTORY` is used as a live-state feed

File and line numbers:

- `_deploy_OVERWATCH/.overwatch_final/sections/account_health.py:173`
- `_deploy_OVERWATCH/.overwatch_final/sections/account_health.py:177`
- `_deploy_OVERWATCH/.overwatch_final/sections/account_health.py:199`
- `_deploy_OVERWATCH/.overwatch_final/sections/live_monitor.py:139`

Current code:

```sql
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
WHERE q.start_time >= DATEADD('hours',-1,CURRENT_TIMESTAMP())
  AND q.execution_status IN ('RUNNING','QUEUED','BLOCKED','RESUMING_WAREHOUSE')
```

Problem:

These metrics are being presented as live or near-live operational state while being sourced from the `ACCOUNT_USAGE` view.

Why it is wrong or risky in Snowflake:

Snowflake documents that `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY` can have up to 45 minutes of latency. Snowflake also documents the `INFORMATION_SCHEMA.QUERY_HISTORY` table function as the live-query-family interface for recent query activity. Using the Account Usage view for active queue/running counts can undercount, lag, or miss transient states entirely.

Official references:

- [QUERY_HISTORY view](https://docs.snowflake.com/en/sql-reference/account-usage/query_history)
- [QUERY_HISTORY table functions](https://docs.snowflake.com/en/sql-reference/functions/query_history)

Corrected code:

```sql
SELECT ...
FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(
    END_TIME_RANGE_START => DATEADD('hour', -1, CURRENT_TIMESTAMP()),
    RESULT_LIMIT => 500
))
WHERE execution_status IN ('RUNNING','QUEUED','BLOCKED','RESUMING_WAREHOUSE')
```

Impact if not fixed:

Leadership and operators can see stale "live" queue pressure, stale active counts, and stale blocked/running metrics.

### 2. `credits_used` is labeled as compute-only

File and line number:

- `_deploy_OVERWATCH/.overwatch_final/utils/cost.py:110`

Current code:

```sql
SUM(credits_used) AS hourly_compute_credits
```

Problem:

The alias says compute-only, but the source column is total credits.

Why it is wrong or risky in Snowflake:

Snowflake documents `CREDITS_USED` in `WAREHOUSE_METERING_HISTORY` as the sum of `CREDITS_USED_COMPUTE` and `CREDITS_USED_CLOUD_SERVICES`. That means the allocation CTE is not compute-only unless it explicitly uses `CREDITS_USED_COMPUTE`.

Official reference:

- [WAREHOUSE_METERING_HISTORY view](https://docs.snowflake.com/en/sql-reference/account-usage/warehouse_metering_history)

Corrected code:

```sql
SUM(COALESCE(credits_used_compute, credits_used)) AS hourly_compute_credits
```

Or, if total warehouse credits are actually intended:

```sql
SUM(credits_used) AS hourly_total_credits
```

Impact if not fixed:

Any metric or caption that says "compute credits" can overstate compute-only cost by including warehouse cloud services credits.

### 3. Pre-aggregation DDL duplicates total credits into both compute and total

File and line number:

- `_deploy_OVERWATCH/.overwatch_final/sections/dba_tools.py:756`

Current code:

```sql
SUM(credits_used) AS compute_credits, SUM(credits_used) AS total_credits
```

Problem:

Both output columns are sourced from the same total column.

Why it is wrong or risky in Snowflake:

Snowflake separates `CREDITS_USED_COMPUTE`, `CREDITS_USED_CLOUD_SERVICES`, and `CREDITS_USED`. Storing `compute_credits` from `credits_used` collapses that distinction and makes downstream comparisons wrong.

Official reference:

- [WAREHOUSE_METERING_HISTORY view](https://docs.snowflake.com/en/sql-reference/account-usage/warehouse_metering_history)

Corrected code:

```sql
SUM(COALESCE(credits_used_compute, credits_used)) AS compute_credits,
SUM(credits_used) AS total_credits
```

Impact if not fixed:

Pre-aggregated warehouse cost tables will report inflated compute-only cost and mislead any downstream cost audit or reconciliation.

### 4. Stored procedure cloud credits can return `NULL`

File and line number:

- `_deploy_OVERWATCH/.overwatch_final/sections/stored_proc_tracker.py:115`

Current code:

```sql
ROUND(SUM(ch.credits_used_cloud_services), 4) AS cloud_credits
```

Problem:

This aggregate does not guard against all-`NULL` rows.

Why it is wrong or risky in Snowflake:

Snowflake aggregate functions ignore `NULL`, but if all input values are `NULL`, `SUM(...)` returns `NULL`. The repo elsewhere uses `COALESCE` for this exact reason.

Official references:

- [Aggregate functions and NULL values](https://docs.snowflake.com/en/sql-reference/functions-aggregation)
- [COALESCE](https://docs.snowflake.com/en/sql-reference/functions/coalesce)

Corrected code:

```sql
ROUND(SUM(COALESCE(ch.credits_used_cloud_services, 0)), 4) AS cloud_credits
```

Impact if not fixed:

Procedure cost summaries can show blank cloud-service cost instead of `0`, and downstream arithmetic can become inconsistent.

### 5. Missing `COMPANY` is silently coerced to `ALFA`

File and line numbers:

- `_deploy_OVERWATCH/.overwatch_final/utils/action_queue.py:127`
- `_deploy_OVERWATCH/.overwatch_final/sections/snowflake_value.py:86`
- `_deploy_OVERWATCH/.overwatch_final/sections/snowflake_value.py:88`

Current code:

```sql
WHERE COALESCE(COMPANY, 'ALFA') = ...
```

Problem:

Rows with missing company metadata are treated as `ALFA`.

Why it is wrong or risky in Snowflake:

`COALESCE` itself is valid, but Snowflake documents that it performs implicit conversion and returns the first non-`NULL` expression. Here the semantic problem is business meaning, not syntax: null company rows are not necessarily ALFA rows. This changes results rather than just formatting them.

Official references:

- [COALESCE](https://docs.snowflake.com/en/sql-reference/functions/coalesce)
- [Data type conversion / coercion](https://docs.snowflake.com/en/sql-reference/data-type-conversion)

Corrected code:

```sql
WHERE COMPANY = ...
```

If legacy null rows need explicit handling:

```sql
WHERE COMPANY = ...
   OR (COMPANY IS NULL AND :include_unclassified = TRUE)
```

Impact if not fixed:

ALFA views can include unclassified rows and appear more expensive or noisier than they really are.

### 6. Storage "average TB" likely does not match the label users will infer

File and line number:

- `_deploy_OVERWATCH/.overwatch_final/sections/dba_tools.py:1683`

Current code:

```sql
AVG(average_database_bytes + average_failsafe_bytes) / POWER(1024, 4) AS avg_tb
```

Problem:

This is averaging daily average-bytes rows, not calculating latest size or total average account storage.

Why it is wrong or risky in Snowflake:

Snowflake's aggregate behavior is fine here, but the business meaning is ambiguous. If this is used as a storage pricing input, averaging 30 days of daily values can diverge from the latest-billed state or from month-end average, depending on the intended pricing basis.

Official references:

- [AVG](https://docs.snowflake.com/en/sql-reference/functions/avg.html)
- [Aggregate functions and NULL values](https://docs.snowflake.com/en/sql-reference/functions-aggregation)

Corrected code:

For latest value per database:

```sql
WITH latest AS (
  SELECT database_name,
         average_database_bytes,
         average_failsafe_bytes,
         ROW_NUMBER() OVER (PARTITION BY database_name ORDER BY usage_date DESC) AS rn
  FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
  WHERE usage_date >= DATEADD('day', -30, CURRENT_DATE())
)
SELECT database_name,
       (average_database_bytes + average_failsafe_bytes) / POWER(1024, 4) AS current_tb
FROM latest
WHERE rn = 1
```

Impact if not fixed:

Storage conversion inputs can look lower or higher than the actual current footprint, depending on recent growth.

### 7. Monthly credit savings are hard-coded to 30-day months

File and line number:

- `_deploy_OVERWATCH/.overwatch_final/sections/snowflake_value.py:94`

Current code:

```sql
ROUND(SUM(SAVINGS_CREDITS * 30), 2) AS monthly_credit_savings
```

Problem:

The report assumes every monthly rollup should use `30` days.

Why it is wrong or risky in Snowflake:

This is not a Snowflake SQL error. It is a business estimate that should be labeled clearly because it is not tied to calendar-month boundaries or actual metering periods.

Official references:

- [DATE_TRUNC](https://docs.snowflake.com/en/sql-reference/functions/date_trunc)
- [DATEADD](https://docs.snowflake.com/en/sql-reference/functions/dateadd)

Corrected code:

If estimate is intended:

```sql
ROUND(SUM(SAVINGS_CREDITS * 30), 2) AS est_30_day_credit_savings
```

If calendar-month estimate is intended:

```sql
ROUND(SUM(SAVINGS_CREDITS * DAY(LAST_DAY(CURRENT_DATE()))), 2) AS est_current_month_credit_savings
```

Impact if not fixed:

Users may treat an estimate as an exact monthly Snowflake-measured value.

### 8. Success/failure fallback logic is inconsistent across sections

File and line numbers:

- `_deploy_OVERWATCH/.overwatch_final/sections/usage_overview.py:50`
- `_deploy_OVERWATCH/.overwatch_final/sections/service_health.py:44`
- `_deploy_OVERWATCH/.overwatch_final/sections/adoption_analytics.py:38`
- `_deploy_OVERWATCH/.overwatch_final/sections/platform_topology.py:34`

Current code:

```sql
SUM(IFF(q.error_code IS NULL, 1, 0))
```

and fallback:

```sql
SUM(IFF(q.execution_status = 'FAILED_WITH_ERROR', 1, 0))
```

Problem:

Some sections prefer `ERROR_CODE`, others rely on `EXECUTION_STATUS`, and some "success" formulas count all rows where `ERROR_CODE IS NULL`.

Why it is wrong or risky in Snowflake:

Snowflake documents that canceled queries are identified by `ERROR_MESSAGE` text rather than `EXECUTION_STATUS`, and the query history semantics are broader than a simple "error_code null means success" rule. The repo is directionally correct in preferring `ERROR_CODE` for failure detection, but the definitions are not standardized.

Official reference:

- [QUERY_HISTORY view](https://docs.snowflake.com/en/sql-reference/account-usage/query_history)

Corrected code:

Recommended repo standard:

```sql
SUM(IFF(error_code IS NOT NULL, 1, 0)) AS failed_queries
COUNT(*) - SUM(IFF(error_code IS NOT NULL, 1, 0)) AS non_failed_queries
```

Then explicitly decide whether canceled queries belong in failures, neutral, or a separate bucket.

Impact if not fixed:

Success rate, failure counts, and recommendation triggers can disagree between pages.

## Inconsistent Metrics

### Live query counts

- `account_health.py` uses `ACCOUNT_USAGE.QUERY_HISTORY` for running/queued/blocked.
- `live_monitor.py` correctly tries `INFORMATION_SCHEMA.QUERY_HISTORY()` first and only falls back to Account Usage.

Recommendation:

Adopt the `live_monitor.py` pattern everywhere live-state metrics are shown.

### Compute credits vs total credits

- `utils/cost.py` labels `SUM(credits_used)` as compute-only.
- `usage_overview.py` distinguishes total, compute, and warehouse cloud credits correctly when columns exist.
- `dba_tools.py` duplicates total credits into both `compute_credits` and `total_credits`.

Recommendation:

Standardize on:

- `total_credits = credits_used`
- `compute_credits = credits_used_compute`
- `warehouse_cloud_credits = credits_used_cloud_services`

with fallback only when a specific column is unavailable.

### Company scoping

- Most operational queries use `company_scoped_query()` / warehouse and database filters.
- `action_queue.py` and `snowflake_value.py` default null company rows to `ALFA`.

Recommendation:

Do not inject a default company value into analytical filters. Keep `NULL` as unclassified unless a separate migration rule is explicitly documented.

### Storage size semantics

- `usage_overview.py` uses latest-row-per-database logic for current and prior storage.
- `dba_tools.py` uses 30-day averages for storage conversion input.

Recommendation:

Pick one standard per use case:

- current storage snapshot
- prior-period snapshot
- time-averaged storage

and label each explicitly.

## Recommended Standards

### Safe division pattern

```sql
100 * numerator / NULLIF(denominator, 0)
```

Use this everywhere ratios or percentages are computed. If a `0` result is required instead of `NULL`, wrap the full expression with `COALESCE(..., 0)`.

Reference:

- [NULLIF](https://docs.snowflake.com/en/sql-reference/functions/nullif)

### Date bucket pattern

```sql
DATE_TRUNC('day', ts_col)
DATE_TRUNC('hour', ts_col)
DATEADD('day', -7, CURRENT_TIMESTAMP())
```

Prefer singular date parts in new code for consistency with Snowflake docs.

References:

- [DATE_TRUNC](https://docs.snowflake.com/en/sql-reference/functions/date_trunc)
- [DATEADD](https://docs.snowflake.com/en/sql-reference/functions/dateadd)

### Percent change pattern

```sql
ROUND(100 * (current_value - prior_value) / NULLIF(prior_value, 0), 1)
```

When `prior_value = 0`, decide explicitly whether the UI should show `NULL`, `New`, or `100+%`.

### NULL handling pattern

Use `COALESCE` only for real value substitution, not for hidden business recoding.

Good:

```sql
SUM(COALESCE(bytes_scanned, 0))
```

Risky:

```sql
COALESCE(company, 'ALFA')
```

Reference:

- [COALESCE](https://docs.snowflake.com/en/sql-reference/functions/coalesce)

### Timestamp handling pattern

- Use `CURRENT_TIMESTAMP()` for timestamp comparisons.
- Use `CURRENT_DATE()` for date-grain storage views.
- Use `DATEDIFF` only when unit-specific truncation semantics are intended.

Reference:

- [DATEDIFF](https://docs.snowflake.com/en/sql-reference/functions/datediff)

### Credit/cost calculation pattern

Use:

```sql
total_credits = credits_used
compute_credits = credits_used_compute
warehouse_cloud_credits = credits_used_cloud_services
```

Do not call `credits_used` compute-only.

Reference:

- [WAREHOUSE_METERING_HISTORY view](https://docs.snowflake.com/en/sql-reference/account-usage/warehouse_metering_history)

## Patch Suggestions

### 1. Fix compute-only allocation in `utils/cost.py`

```diff
- SUM(credits_used)               AS hourly_compute_credits
+ SUM(COALESCE(credits_used_compute, credits_used)) AS hourly_compute_credits
```

If total warehouse credits are intended instead:

```diff
- SUM(credits_used)               AS hourly_compute_credits
+ SUM(credits_used)               AS hourly_total_credits
```

### 2. Fix pre-aggregation DDL in `sections/dba_tools.py`

```diff
- SUM(credits_used) AS compute_credits, SUM(credits_used) AS total_credits
+ SUM(COALESCE(credits_used_compute, credits_used)) AS compute_credits,
+ SUM(credits_used) AS total_credits
```

### 3. Fix stored procedure cloud credits in `sections/stored_proc_tracker.py`

```diff
- ROUND(SUM(ch.credits_used_cloud_services), 4) AS cloud_credits,
+ ROUND(SUM(COALESCE(ch.credits_used_cloud_services, 0)), 4) AS cloud_credits,
```

### 4. Stop recoding null company rows to ALFA

`utils/action_queue.py`

```diff
- company_clause = "" if company == "ALL" else f"WHERE COALESCE(COMPANY, 'ALFA') = {sql_literal(company)}"
+ company_clause = "" if company == "ALL" else f"WHERE COMPANY = {sql_literal(company)}"
```

`sections/snowflake_value.py`

```diff
- company_select = "COALESCE(COMPANY, 'ALFA') AS COMPANY,"
+ company_select = "COMPANY,"

- company_filter = f"WHERE COALESCE(COMPANY, 'ALFA') = {sql_literal(company)}"
+ company_filter = f"WHERE COMPANY = {sql_literal(company)}"
```

### 5. Standardize live-state sourcing

For live queue/running/blocked counts, use:

```sql
FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(
    END_TIME_RANGE_START => DATEADD('hour', -1, CURRENT_TIMESTAMP()),
    RESULT_LIMIT => 500
))
```

Use `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY` only for historical or lag-tolerant views, and label it accordingly.

### 6. Label estimated 30-day savings explicitly

```diff
- ROUND(SUM(SAVINGS_CREDITS * 30), 2) AS monthly_credit_savings
+ ROUND(SUM(SAVINGS_CREDITS * 30), 2) AS est_30_day_credit_savings
```

### 7. Unify failure logic

Prefer one shared pattern for historical query failure counts:

```sql
SUM(IFF(error_code IS NOT NULL, 1, 0)) AS failed_queries
```

Then decide separately how canceled queries should be classified, instead of mixing status and error-code rules page by page.
