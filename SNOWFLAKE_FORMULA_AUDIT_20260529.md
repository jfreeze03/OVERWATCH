# OVERWATCH Formula Contract And Audit Status

Last updated: June 6, 2026

This file is retained as the formula-audit reference, but the content now
documents the current production formula contract instead of the historical
findings from May 2026. Historical issues from the original audit have been
folded into regression tests and the mart/app formula rules.

## Current Audit Status

| Area | Status | Production rule |
|---|---|---|
| Warehouse total credits | Aligned | Use `SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY.CREDITS_USED`. |
| Warehouse compute credits | Aligned | Use `CREDITS_USED_COMPUTE` when available; otherwise fall back to `CREDITS_USED`. |
| Cloud-services credits | Aligned | Use `COALESCE(CREDITS_USED_CLOUD_SERVICES, 0)` where the column is available. |
| Billed service credits | Aligned | Use `SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY`. |
| Warehouse dollars | Aligned | Multiply warehouse credits by `$3.68`. |
| Cortex AI dollars | Aligned | Multiply Cortex AI credits by `$2.20`. |
| Company scope | Aligned | Trexis is exact warehouse/database list; ALFA is all other listed account warehouse scope. |
| Null company handling | Aligned | Do not silently convert unknown/null ownership to ALFA. Use unclassified/no-context language. |
| Environment scope | Aligned | `_PRD` maps to production for Trexis; `_DEV` and `_SIT` map to development/test. ALFA uses configured ALFA database lists. |
| Live operational counts | Aligned by intent | Prefer Information Schema for current-state metrics; label Account Usage latency where used. |

## Official Snowflake Cost Inputs

| Input | Source | Grain | Use |
|---|---|---|---|
| Warehouse metering | `SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY` | Warehouse/hour | Primary warehouse credit and cost basis. |
| Service metering | `SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY` | Service/day | Official billed service-credit split. |
| Organization currency | `SNOWFLAKE.ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY` | Account/service/day | Optional official currency reconciliation when visible. |
| Rate sheet | `SNOWFLAKE.ORGANIZATION_USAGE.RATE_SHEET_DAILY` | Account/service/date | Optional contract-rate comparison when visible. |
| Query history | `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY` | Query | Allocation basis for user, role, database, schema, and workload cost. |
| Cortex usage | Cortex account usage views when available | User/model/day or event | AI spend and quota evidence. |

## Warehouse Credit Formulas

Total warehouse credits:

```sql
SUM(COALESCE(CREDITS_USED, 0))
```

Compute warehouse credits:

```sql
SUM(COALESCE(CREDITS_USED_COMPUTE, CREDITS_USED, 0))
```

Cloud-services credits:

```sql
SUM(COALESCE(CREDITS_USED_CLOUD_SERVICES, 0))
```

Estimated warehouse cost:

```sql
SUM(COALESCE(CREDITS_USED, 0)) * 3.68
```

When a table label says compute credits, it must not be populated from total
credits unless `CREDITS_USED_COMPUTE` is unavailable and the fallback is stated.

## Cortex AI Formula

Estimated Cortex AI cost:

```sql
SUM(COALESCE(AI_CREDITS, 0)) * 2.20
```

If Snowflake exposes exact billed Cortex/service currency for the account, show
that separately from the configured-rate estimate.

## Chargeback And Allocation Formula

Snowflake warehouse metering is exact at warehouse-hour grain. User, role,
database, schema, query type, and environment splits are allocations.

The production allocation rule is:

```text
allocated credits =
  warehouse-hour compute credits
  * query elapsed milliseconds for the group
  / total query elapsed milliseconds for that warehouse-hour
```

The allocation result must carry an evidence label such as:

- exact warehouse metering
- allocated from warehouse metering by query elapsed time
- owner tag attached
- owner validation required
- no database context

## Company Scope Formula

Trexis if any of the following is true:

- warehouse name is one of `WH_TRXS_LOAD`, `WH_TRXS_QUERY`,
  `WH_TRXS_TRANSFORM`, or `WH_TRXS_UNLOAD`
- database name is one of the configured Trexis databases
- user name matches approved Trexis user pattern

ALFA if the row is in the configured account scope and is not Trexis.

Unknown/no-context if there is not enough evidence to assign the row safely.

## Environment Formula

Trexis:

- `_PRD` database suffix: `PROD`
- `_DEV` or `_SIT` database suffix: `DEV_ALL`

ALFA:

- `ALFA_EDW_PRD` and `ALFA_EDW_MGM`: `PROD`
- configured development/test ALFA databases: `DEV_ALL`

No database context:

- account-level rows
- warehouse-only rows without query database
- login/security rows where Snowflake does not provide database context

## Regression Expectations

Regression tests should guard:

1. credit label/source alignment
2. compute vs total credit DDL
3. Cortex AI dollar rate
4. `$3.68` compute rate
5. null company behavior
6. Trexis exact warehouse/database scope
7. ALFA catch-all behavior
8. cost tables including dollars where credits are shown
9. current-state metrics using live sources where required

## Production Rule

If a formula changes in one section, it must change everywhere:

- app utility functions
- section SQL builders
- setup SQL facts/views
- documentation
- tests

Cost trust is a product feature. Do not ship a new cost metric without a source,
grain, allocation method, dollar rate, and regression test.
