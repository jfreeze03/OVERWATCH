# OVERWATCH Snowflake Regression Results

- Run ID: `SNOWFLAKE_REGRESSION_LIVE_PASS`
- Timestamp: `2026-06-23T23:24:48.769959+00:00`
- Status: `PASS`
- Environment: `LOKAXGM-WU94316`
- Role: `SNOW_ACCOUNTADMINS`
- Warehouse: `COMPUTE_WH`
- Database/schema: `DBA_MAINT_DB.OVERWATCH`
- JSON evidence: `C:\Users\jfree\Desktop\overwatchv3\_deploy_OVERWATCH\perf_tests\results\SNOWFLAKE_REGRESSION_LIVE_PASS_full_app_snowflake_regression.json`

## Sections Tested
- Executive Landing
- DBA Control Room
- Alert Center
- Cost & Contract
- Workload Operations
- Security Monitoring

## Workflows Tested
- Executive Landing: Executive Overview, Cost Movement, Operational Risk, Security Risk, Change Summary, Executive Actions, Executive Admin / Advanced
- DBA Control Room: Morning Cockpit, Failure Triage, Cost Watch, Performance Watch, Change Watch, Action Queue, Control Room Admin / Advanced
- Alert Center: Active Alerts, Cost Alerts, Reliability Alerts, Security Alerts, Alert History, Alert Settings / Admin
- Cost & Contract: Cost Overview, Cost by Warehouse, Cost by User / Role, Burn Rate & Forecast, Budget vs Actual, Waste Detection, Chargeback / Company Split, Cost Recommendations
- Workload Operations: Workload Overview, Query Investigation, Pipeline & Task Health, Performance & Contention, Change Analysis, Advanced DBA Tools
- Security Monitoring: Security Overview, Failed Logins, Risky Grants, Privilege Sprawl, Access Changes, Data Sharing Exposure, Security Alerts, Security Admin / Advanced

## Static Route / Label Checks
- Status: `PASS`
- Missing workflows: `{}`
- Primary nav violations: `[]`
- Stale chart references: `[]`

## Snowflake Checks
- snowflake_checks: 2 checks
  - `current_session`: `PASS` (102.09 ms)
  - `overwatch_schema_access`: `PASS` (1414.97 ms)
- mart_probes: 24 checks
  - `MART_DBA_CONTROL_ROOM_preview`: `PASS` (126.74 ms)
  - `MART_DBA_CONTROL_ROOM_freshness`: `PASS` (159.43 ms)
  - `MART_EXECUTIVE_OBSERVABILITY_preview`: `PASS` (143.77 ms)
  - `MART_EXECUTIVE_OBSERVABILITY_freshness`: `PASS` (152.91 ms)
  - `MART_DATA_TRUST_SUMMARY_preview`: `PASS` (93.77 ms)
  - `MART_DATA_TRUST_SUMMARY_freshness`: `PASS` (104.46 ms)
  - `MART_OPERATIONAL_OWNER_COVERAGE_preview`: `PASS` (162.59 ms)
  - `MART_OPERATIONAL_OWNER_COVERAGE_freshness`: `PASS` (107.8 ms)
  - `MART_EXECUTIVE_VALUE_LEDGER_preview`: `PASS` (120.86 ms)
  - `MART_EXECUTIVE_VALUE_LEDGER_freshness`: `PASS` (101.59 ms)
  - `MART_APP_OBSERVABILITY_SUMMARY_preview`: `PASS` (160.31 ms)
  - `MART_APP_OBSERVABILITY_SUMMARY_freshness`: `PASS` (156.02 ms)
  - `MART_PRODUCTION_READINESS_SUMMARY_preview`: `PASS` (84.3 ms)
  - `MART_PRODUCTION_READINESS_SUMMARY_freshness`: `PASS` (131.8 ms)
  - `MART_EXECUTIVE_SCORECARD_SUMMARY_preview`: `PASS` (93.55 ms)
  - `MART_EXECUTIVE_SCORECARD_SUMMARY_freshness`: `PASS` (106.11 ms)
  - `MART_EXECUTIVE_FORECAST_SUMMARY_preview`: `PASS` (121.75 ms)
  - `MART_EXECUTIVE_FORECAST_SUMMARY_freshness`: `PASS` (124.19 ms)
  - `MART_CHANGE_INTELLIGENCE_SUMMARY_preview`: `PASS` (115.01 ms)
  - `MART_CHANGE_INTELLIGENCE_SUMMARY_freshness`: `PASS` (110.59 ms)
- account_usage_probes: 2 checks
  - `account_usage_warehouse_access`: `PASS` (327.08 ms)
  - `account_usage_recent_metering_access`: `PASS` (2107.57 ms)

## Object Inventory
- `summary_marts`: `PASS`, rows `12`
- `refresh_procedures`: `PASS`, rows `10`

## Failures
- None recorded.

## Recommended Fixes
- Review warnings, then run section smoke and full unit regression.
