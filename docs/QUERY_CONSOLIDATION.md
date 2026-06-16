# OVERWATCH Query Consolidation Notes

This is the working inventory for reducing duplicate Snowflake reads in the
Streamlit app. The goal is to keep expensive ACCOUNT_USAGE scans behind explicit
refresh/drilldown actions and make repeated metric families load once per scope.

## Current Shared Loader

`utils.shared_metrics` now owns the first shared metric datasets:

| Loader | Primary use | Source strategy |
| --- | --- | --- |
| `load_shared_storage_trend` | Storage Monitor trend and reusable storage trend facts | Fast storage mart first, live storage views only on explicit fallback |
| `load_shared_usage_storage_kpis` | Usage Overview storage KPIs | Reuses shared storage trend, falls back to mart KPI SQL if needed |
| `load_shared_usage_metering_kpis` | Usage Overview credit KPIs and Account Health 24-hour burn | Fast warehouse metering mart first, live metering fallback only when needed |
| `load_shared_storage_db_detail` | Storage Monitor per-database detail | Fast storage mart first, live database storage fallback on demand |
| `load_shared_warehouse_daily_credits` | Cost Forecast daily credit trend | Live warehouse metering, cached once per company/filter scope |
| `load_shared_warehouse_daily_credits_by_warehouse` | Cost Center Burn Rate daily warehouse trend | Live warehouse metering with latest observed warehouse size, cached once per company/filter scope |
| `load_shared_warehouse_overview` | Warehouse Health overview and current/prior movement | Fast warehouse overview mart first, live query-history plus metering fallback only on explicit load |

Shared results are stored under `_shared_metric_...` session keys and are cleared
by the global refresh path.

## Static Query Inventory

Current scan of `.overwatch_final/sections` and `.overwatch_final/utils` found
about 240 `run_query(` call sites and about 270 explicit `ttl_key=` call sites.
Most are already cached by `utils.query`; the remaining opportunity is to reduce
different sections building near-identical SQL under different cache keys.

Top ACCOUNT_USAGE source families by static reference count:

| Source table/view | Count | Consolidation priority |
| --- | ---: | --- |
| `QUERY_HISTORY` | 125 | Highest. Split into shared recent status, query mix, warehouse pressure, spill, and attribution loaders. |
| `WAREHOUSE_METERING_HISTORY` | 41 | High. Consolidate daily credits, current/prior credits, and warehouse movement. |
| `LOGIN_HISTORY` | 26 | Medium. Security/account-health hygiene can share scoped loaders. |
| `USERS` | 19 | Medium. User posture and access hygiene should share account snapshots. |
| `TASK_HISTORY` | 14 | High for Workload Operations/Account Health. Prefer mart-first task health loaders. |
| `GRANTS_TO_USERS` | 12 | Medium. Share access hygiene snapshots. |
| `METERING_HISTORY` | 8 | Medium. Centralize service-cost lenses. |
| `DATABASE_STORAGE_USAGE_HISTORY` | 6 | First pass done through shared storage loaders. |
| `TABLE_STORAGE_METRICS` | 3 | Low. Kept on demand because it is a targeted table drilldown. |

## Next Safe Consolidation Targets

1. Warehouse metering summary:
   Extend the shared metering layer from Usage Overview/Cost Forecast into
   current/prior credits by company, warehouse, and day. Remaining consumers:
   Warehouse Health scaling events and deeper advisor panels.

2. Query history operational rollup:
   Create one mart-first/live-fallback loader for total queries, failures, queue,
   spill, p95/average elapsed, active users, and active warehouses. Consumers:
   Usage Overview, Account Health, Warehouse Health, DBA Control Room detail.

3. Warehouse pressure rollup:
   Extend the shared warehouse overview loader into a narrower pressure-only
   rollup with queued, spill, latency, failures, and metered credits. Consumers:
   Usage Overview pressure, Account Health warehouse pressure, and DBA detail.

4. Task/procedure health:
   Keep task/procedure detail on demand, but share the summary counters and recent
   failure samples used by Account Health, DBA Control Room, and Workload
   Operations.

5. Security/access hygiene:
   Share scoped `USERS`, `LOGIN_HISTORY`, and grants snapshots for Security
   Monitoring and Account Health instead of rebuilding similar login/grant views.

## Refactor Rules

- Keep marts first and live ACCOUNT_USAGE fallback second.
- Keep live broad scans behind explicit user refresh/drilldown actions.
- Cache by company, environment, global filters, lookback, and metric family.
- Return a source caption with every shared frame so the UI can remain honest
  about fast summary vs live fallback.
- Do not change chargeback semantics while consolidating. Exact metering and
  allocated query cost must remain labeled separately.
