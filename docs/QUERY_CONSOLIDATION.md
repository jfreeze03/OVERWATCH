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
| `load_shared_bill_metering_summary` | Cost Center Explain This Bill current/prior warehouse totals | Fast warehouse hourly mart first, live WAREHOUSE_METERING_HISTORY fallback |
| `load_shared_bill_warehouse_delta` / `build_shared_bill_warehouse_delta_live_sql` | Cost Center Explain This Bill and Cost & Contract splash warehouse movement | Fast warehouse hourly mart first, shared live WAREHOUSE_METERING_HISTORY fallback shape |
| `load_shared_warehouse_daily_credits` | Cost Forecast daily credit trend | Live warehouse metering, cached once per company/filter scope |
| `load_shared_warehouse_daily_credits_by_warehouse` | Cost Center Burn Rate daily warehouse trend | Live warehouse metering with latest observed warehouse size, cached once per company/filter scope |
| `load_shared_warehouse_credit_anomalies` | Cost & Contract Anomaly Log | Fast warehouse hourly mart first, live WAREHOUSE_METERING_HISTORY fallback only from the explicit anomaly action |
| `load_shared_warehouse_overview` | Warehouse Health overview and current/prior movement | Fast warehouse overview mart first, live query-history plus metering fallback only on explicit load |
| `load_shared_query_history_rollup` | Usage Overview and Account Health query/error/queue KPIs | Fast query mart first, live QUERY_HISTORY fallback only on explicit load |
| `load_shared_warehouse_pressure_summary` | Usage Overview and Account Health active/pressured warehouse counts | Fast query mart first, live QUERY_HISTORY fallback only on explicit load |
| `load_shared_warehouse_scaling_events` | Warehouse Health scaling/metering event review | Fast warehouse mart first, live WAREHOUSE_METERING_HISTORY fallback |
| `load_shared_task_health_summary` | Usage Overview task run/failure counters | Live TASK_HISTORY with optional-column compatibility and zero-row fallback |
| `load_shared_mfa_coverage` | Security Access MFA coverage | Live USERS snapshot, cached once per company/user filter scope |
| `load_shared_grants_to_users` | Security Access role-grant review | Fast grant mart first, live GRANTS_TO_USERS fallback |
| `load_shared_access_hygiene_snapshot` | Account Health access hygiene | Live USERS + LOGIN_HISTORY + GRANTS_TO_USERS account-level snapshot |
| `load_shared_recommendation_idle_warehouses` | Recommendations and Warehouse Health idle-credit advisor | Fast recommendation mart first for default 7-day view, live warehouse/query fallback for custom lookbacks |
| `load_shared_recommendation_spill_warehouses` | Recommendations remote-spill advisor | Fast recommendation mart first, live QUERY_HISTORY fallback with optional-column checks |
| `load_shared_recommendation_failed_tasks` | Recommendations task-failure advisor | Fast task-run mart first, live TASK_HISTORY fallback through compatibility SQL |
| `load_shared_recommendation_query_failures` | Recommendations query-failure advisor | Fast query-hourly mart first, live QUERY_HISTORY fallback |
| `load_shared_recommendation_storage_retention` | Recommendations storage-retention advisor | Live TABLE_STORAGE_METRICS, cached once per company/scope because this remains a targeted drilldown source |
| `load_shared_recommendation_clustering_cost` | Recommendations clustering-cost advisor | Live AUTOMATIC_CLUSTERING_HISTORY, cached once per company/window/rate |
| `load_shared_recommendation_repeated_queries` | Recommendations repeated expensive query patterns | Fast query-detail mart first, live QUERY_HISTORY hash fallback for empty/custom paths |
| `load_shared_duplicate_query_patterns` | Warehouse Health duplicate-query advisor | Fast query-detail mart first, live QUERY_HISTORY fallback with optional cloud-services credits |
| `load_shared_warehouse_right_sizing` | Warehouse Health right-sizing advisor | Live QUERY_HISTORY + WAREHOUSE_METERING_HISTORY with optional-column checks |
| `load_shared_procedure_inventory` | Stored Procedure operations brief | Fast procedure snapshot mart first, live PROCEDURES fallback supplied by the section |
| `load_shared_procedure_calls` | Stored Procedure recent CALL summary | Fast procedure-run mart first, live QUERY_HISTORY fallback supplied by the section |
| `load_shared_procedure_sla` | Stored Procedure SLA/cost watch | Fast procedure-run mart first, lazy live QUERY_HISTORY fallback supplied by the section |

Shared results are stored under `_shared_metric_...` session keys and are cleared
by the global refresh path.

`utils.metering_sql` now owns shared SQL shapes for Cost & Contract cockpit
movement and run-rate/YOY metering. The mart and live fallback builders both use
those shapes, so future cost logic changes land in one place.

## Static Query Inventory

Current scan of `.overwatch_final/sections` and `.overwatch_final/utils` found
about 240 `run_query(` call sites and about 270 explicit `ttl_key=` call sites.
Most are already cached by `utils.query`; the remaining opportunity is to reduce
different sections building near-identical SQL under different cache keys.

Latest pass note: the raw call-site count will not drop one-for-one because
shared loaders deliberately keep the SQL source in `utils.shared_metrics`.
The important change is that idle warehouse, remote spill, task failure, query
failure, repeated-query, duplicate-query, right-sizing, clustering, storage
retention, and procedure summary candidates now share one source-caption and
cache contract. The visible Recommendations default now runs in fast
mart-backed mode; live ACCOUNT_USAGE fallback plus storage/clustering deep scans
require the explicit deep-scan action. The Anomaly Log now also shares the
warehouse credit anomaly loader instead of building a one-off metering query in
the section. Cost Center Explain This Bill now uses shared bill summary and
warehouse-delta loaders for current/prior metering rather than embedding another
copy of the WAREHOUSE_METERING_HISTORY summary SQL in the section. Cost &
Contract splash keeps its stricter mart/live error reporting while reusing the
shared live warehouse-delta SQL builder. Cost & Contract cockpit and run-rate
SQL now reuse `utils.metering_sql` for both mart and live paths, and the detail
refresh block now refreshes run-rate, action queue, attribution, service lens,
and advisor detail data even when the fast cockpit mart succeeds.

`docs/QUERY_INVENTORY.md` is the static map for current query families, cache
call sites, and mart object disposition.

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
   First pass done for Usage Overview, Cost Forecast, Burn Rate, Cost Center
   Explain This Bill, Cost & Contract splash warehouse ranking, and Cost &
   Contract Anomaly Log. Cost & Contract run-rate/cockpit helpers now share
   common metering SQL shapes. Remaining consumers: deeper warehouse advisor
   panels that still need specialized event-level metering.

2. Query history operational rollup:
   First pass done for Usage Overview and Account Health. Remaining consumers:
   Warehouse Health deeper advisor panels, DBA Control Room detail, and Service
   Health where the same counters are shown.

3. Warehouse pressure rollup:
   First pass done for Usage Overview pressure and Account Health warehouse
   pressure. Remaining consumers: DBA detail and any advisor panels that still
   rebuild queue/failure pressure by warehouse.

4. Task/procedure health:
   Task summary counters, recommendation-level failed task candidates, procedure
   inventory, procedure call summaries, and procedure SLA/cost watch loads now
   have shared loaders. Remaining work is deeper task failure sample reuse where
   the UI needs more than advisor candidates.

5. Security/access hygiene:
   MFA, grants, and Account Health access hygiene now use shared snapshots.
   Remaining work is folding Security Posture summary/exceptions into the same
   access snapshot where the column shape matches.

6. Advisor signal inventory:
   First pass done for recommendation idle, spill, failed-task, failed-query,
   repeated-query, storage-retention, clustering, Warehouse Health duplicate
   queries, and right-sizing candidates. Remaining work is deeper DBA detail
   panels that still rebuild query-history pressure for one-off investigations.

## Refactor Rules

- Keep marts first and live ACCOUNT_USAGE fallback second.
- Keep live broad scans behind explicit user refresh/drilldown actions.
- Cache by company, environment, global filters, lookback, and metric family.
- Return a source caption with every shared frame so the UI can remain honest
  about fast summary vs live fallback.
- Do not change chargeback semantics while consolidating. Exact metering and
  allocated query cost must remain labeled separately.
