# OVERWATCH Query And Mart Inventory

This is a static map for query consolidation and mart slimming work. The source
of truth for deployed Snowflake objects remains `snowflake/OVERWATCH_MART_SETUP.sql`;
the mass-drop reset script remains `snowflake/OVERWATCH_MART_DROP.sql`.

## App Query Surface

Current static scan of `.overwatch_final/sections` and `.overwatch_final/utils`:

| Signal | Count |
| --- | ---: |
| `run_query(` call sites | 244 |
| `ttl_key=` call sites | 274 |

These counts are not all live Snowflake scans. Many call sites are mart-first,
cached through `utils.query`, or wrapped by shared loaders in
`utils.shared_metrics`. The useful refactor target is repeated SQL shape under
different cache keys, not raw call-site count alone.

## High-Volume Source Mentions

Static token mentions in app Python code:

| Source family | Mentions | Current strategy |
| --- | ---: | --- |
| `QUERY_HISTORY` | 262 | Keep consolidating rollups, advisor pressure, and attribution paths behind shared loaders. |
| `WAREHOUSE_METERING_HISTORY` | 89 | Cost cockpit, run-rate, splash movement, anomaly, forecast, and burn-rate paths now share common metering shapes where practical. |
| `TASK_HISTORY` | 102 | Task summary and recommendation candidates use shared loaders; deeper samples remain section-specific. |
| `USERS` | 149 | Security/access snapshots are partially shared; posture exceptions remain a future consolidation target. |
| `METERING_HISTORY` | 111 | Service-cost lens remains the main official cost source; keep explicit refresh only. |
| `LOGIN_HISTORY` | 56 | Access hygiene and security surfaces are the consolidation target. |
| `GRANTS_TO_USERS` | 26 | MFA/grant/account-health paths use shared snapshots where column shape matches. |
| `DATABASE_STORAGE_USAGE_HISTORY` | 10 | Storage trend/detail already has shared loader coverage. |
| `TABLE_STORAGE_METRICS` | 6 | Kept as targeted drilldown source. |

## Current Cost Metering Consolidation

| Query shape | Shared owner | Current consumers |
| --- | --- | --- |
| Usage metering KPI current/prior | `load_shared_usage_metering_kpis` | Usage Overview, Account Health |
| Daily warehouse credits | `load_shared_warehouse_daily_credits` | Cost Forecast |
| Daily warehouse credits by warehouse | `load_shared_warehouse_daily_credits_by_warehouse` | Cost Center Burn Rate |
| Bill summary current/prior | `load_shared_bill_metering_summary` | Cost Center Explain This Bill |
| Warehouse delta current/prior | `load_shared_bill_warehouse_delta`, `build_shared_bill_warehouse_delta_live_sql` | Cost Center Explain This Bill, Cost & Contract splash |
| Credit anomalies | `load_shared_warehouse_credit_anomalies` | Cost & Contract Anomaly Log |
| Cost cockpit movement | `build_cost_cockpit_metering_sql` | Cost & Contract mart and live fallback paths |
| Cost run-rate / YOY | `build_cost_run_rate_metering_sql` | Cost & Contract mart and live fallback paths |

The Cost & Contract detail refresh now refreshes run-rate, action queue,
attribution, service lens, and advisor detail paths regardless of whether the
fast cockpit mart succeeds.

## Mart Object Disposition

Static setup scan:

| Disposition | Count | Notes |
| --- | ---: | --- |
| Direct app read or app-managed state | 59 | Used by `.overwatch_final` sections or utilities. |
| Test/setup contract only | 9 | Mostly tasks, setup function, and owner-tag support contracts. |
| Refresh/setup plumbing | 6 | Procedures and load audit used by scheduled refresh chains. |
| Total deployable objects | 74 | Matches the mart object review count. |

No additional safe table drop was identified in this pass. The objects without
direct app reads are refresh procedures, refresh tasks, setup support, or test
contracts that represent desired production setup behavior.

## Slimming Rule

Only merge or drop mart objects when all of these are true:

1. The app has no direct read path for the object.
2. Refresh procedures no longer write it.
3. Validation/tests no longer represent a desired production contract for it.
4. The object does not preserve audit, setup, or operational history that the app
   still needs.
5. A replacement exists, or the product workflow has been intentionally retired.

The next useful slimming work is compatibility-driven: merge objects only where
grain, retention, refresh cadence, and downstream displays are genuinely the
same.
