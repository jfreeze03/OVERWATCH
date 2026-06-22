# OVERWATCH Mart Strategy Rewrite

Date: 2026-06-22

## Current Strategy

The Snowflake setup still reflects several capability-building phases. It contains many useful objects, but the daily operator app now has a simpler strategy:

1. Executive Landing
2. DBA Control Room
3. Alert Center
4. Cost & Contract
5. Workload Operations
6. Security Monitoring

The mart layer should support those workflows directly, with proof/readiness/value/evidence objects loaded only for admin and advanced views.

## Operator Mart Target

Target daily mart count: 28-34 tables/views after migration, without dropping legacy objects immediately.

| Workflow family | Required slim marts |
|---|---|
| Executive Landing | `MART_EXECUTIVE_OBSERVABILITY`, `MART_EXECUTIVE_ACTION_SUMMARY`, `MART_EXECUTIVE_RISK_SUMMARY` |
| DBA Control Room | `MART_DBA_CONTROL_ROOM`, `MART_DBA_FAILURE_TRIAGE`, `MART_DBA_ACTION_QUEUE`, `MART_DBA_CHANGE_WATCH` |
| Alert Center | `MART_ALERT_ACTIVE`, `MART_ALERT_HISTORY`, `MART_ALERT_OWNER_ROUTE`, `MART_ALERT_ADMIN_STATUS` |
| Cost & Contract | `MART_COST_OVERVIEW`, `MART_COST_WAREHOUSE_DAILY`, `MART_COST_USER_ROLE_DAILY`, `MART_COST_BUDGET_ACTUAL`, `MART_COST_WASTE`, `MART_COST_COMPANY_SPLIT`, `MART_COST_RECOMMENDATION` |
| Workload Operations | `MART_WORKLOAD_OVERVIEW`, `MART_QUERY_INVESTIGATION`, `MART_PIPELINE_TASK_HEALTH`, `MART_WORKLOAD_CONTENTION`, `MART_WORKLOAD_CHANGE_ANALYSIS` |
| Security Monitoring | `MART_SECURITY_OVERVIEW`, `MART_FAILED_LOGIN`, `MART_RISKY_GRANT`, `MART_PRIVILEGE_SPRAWL`, `MART_ACCESS_CHANGE`, `MART_DATA_SHARING_EXPOSURE`, `MART_SECURITY_ALERT` |
| Shared governance/admin | `MART_DATA_TRUST_SUMMARY`, `MART_PRODUCTION_READINESS_SUMMARY`, `MART_APP_OBSERVABILITY_SUMMARY`, `OVERWATCH_SETTINGS` |

## Current Objects To Keep During Transition

| Object | Reason |
|---|---|
| `MART_EXECUTIVE_OBSERVABILITY` | Current first-paint executive summary. |
| `MART_DBA_CONTROL_ROOM` | Current fast DBA summary source. |
| `MART_DATA_TRUST_SUMMARY` | Required for trust/freshness labeling. |
| `MART_PRODUCTION_READINESS_SUMMARY` | Admin/release validation. |
| `MART_APP_OBSERVABILITY_SUMMARY` | App self-health. |
| `MART_EXECUTIVE_FORECAST_SUMMARY` | Supports simple burn/run-rate summary until slim cost forecast mart exists. |
| `MART_CHANGE_INTELLIGENCE_SUMMARY` | Supports change workflow until slim change marts exist. |
| `MART_CLOSED_LOOP_OPERATIONS_SUMMARY` | Admin evidence and action lifecycle. |
| `MART_COMMAND_CENTER_SUMMARY` | Internal compatibility source for correlated investigations. Visible UI no longer uses the old label. |

## Deprecated-By-Design Categories

Do not drop yet. Mark these as migration candidates and validate usage first:

| Category | Reason |
|---|---|
| Proof-only marts | They support governance evidence but do not drive daily operator decisions. |
| Score formula history | Useful for audit, noisy for normal UI. |
| Value ledger detail | Keep for Cost & Contract advanced verification, not first paint. |
| Closed-loop evidence detail | Keep review/audit detail behind explicit load. |
| Native alert deployment internals | Keep under Alert Settings / Admin. |
| Legacy command-center object hierarchy | Keep as internal correlated-investigation compatibility until data migration is approved. |

## Insert Rewrite Direction

The load procedures should prioritize rows in this order:

1. Active alerts and owner/action routing.
2. Workload failures: query, task, procedure, copy/load, SLA.
3. Cost drivers: warehouse, user/role, burn-rate, budget, waste, company split.
4. Change signals: object, task/procedure, access, deployment drift.
5. Security signals: failed logins, risky grants, sprawl, sharing exposure.
6. Freshness/status/trust.
7. Admin-only proof, readiness, value verification, and closed-loop evidence.

## Changes Completed In This Pass

- Updated Snowflake setup descriptive route text from old labels to current workflow labels.
- Updated cost recommendation seed routes to `Cost Recommendations`.
- Updated investigation wording from old Command Center language to correlated investigations.
- Added a live Snowflake regression runner that can validate mart existence and one-row reads after authentication is fixed.

## Migration Rules

- Do not drop legacy objects until the slim marts have at least one successful live refresh and UI regression pass.
- Keep old object names available for one release when replacing them.
- Use bounded windows for ACCOUNT_USAGE source reads.
- Use merge or delete/insert by snapshot scope for deterministic refreshes.
- Preserve ALFA / Trexis / ALL attribution in every cost, user, role, and warehouse mart.
- Keep admin/proof tables out of daily first-paint loads.

## Validation Required Before Drop Scripts

1. Run `snowflake/OVERWATCH_MART_SETUP.sql`.
2. Run every refresh procedure.
3. Run `snowflake/OVERWATCH_MART_VALIDATION.sql`.
4. Run `perf_tests/full_app_snowflake_regression.py`.
5. Run section smoke.
6. Confirm every six-section workflow can render with current marts.
7. Produce an approved object-retirement list before generating drops.

