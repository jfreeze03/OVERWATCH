# OVERWATCH Snowflake Regression Results

- Run ID: `SNOWFLAKE_REGRESSION_HARDENING`
- Timestamp: `2026-06-22T21:39:28.494876+00:00`
- Status: `FAIL`
- Environment: `LOKAXGM-WU94316`
- Role: `ACCOUNTADMIN`
- Warehouse: `COMPUTE_WH`
- Database/schema: `DBA_MAINT_DB.OVERWATCH`
- JSON evidence: `C:\Users\jfree\Desktop\overwatchv3\_deploy_OVERWATCH\perf_tests\results\SNOWFLAKE_REGRESSION_HARDENING_full_app_snowflake_regression.json`

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
- Failure: `390190 (08001): Failed to connect to DB: LOKAXGM-WU94316.snowflakecomputing.com:443, There was an error related to the SAML Identity Provider account parameter. Contact Snowflake support.`
- snowflake_checks: 0 checks
- mart_probes: 0 checks
- account_usage_probes: 0 checks

## Object Inventory

## Failures
- 390190 (08001): Failed to connect to DB: LOKAXGM-WU94316.snowflakecomputing.com:443, There was an error related to the SAML Identity Provider account parameter. Contact Snowflake support.

## Recommended Fixes
- Fix connection/privilege issue, then rerun this regression.
