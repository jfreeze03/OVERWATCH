# OVERWATCH Query And Mart Inventory

This is a static map for query consolidation and mart slimming work. The source
of truth for deployed Snowflake objects remains `snowflake/OVERWATCH_MART_SETUP.sql`;
the mass-drop reset script remains `snowflake/OVERWATCH_MART_DROP.sql`.

## App Query Surface

Current static scan of `.overwatch_final/sections` and `.overwatch_final/utils`:

| Signal | Count |
| --- | ---: |
| `run_query(` call sites | 244 |
| `ttl_key=` call sites | 275 |

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
| `TASK_HISTORY` | 99 | Task summary, Service Health counters, and recommendation candidates use shared loaders; deeper samples remain section-specific. |
| `USERS` | 143 | Security/access snapshots and Security Monitoring summary builders are partially shared; posture exception row reuse remains a future consolidation target. |
| `METERING_HISTORY` | 110 | Service-cost lens/trend now share one official loader; keep explicit refresh only. |
| `LOGIN_HISTORY` | 56 | Access hygiene, security, and Service Health day-level surfaces now share loaders where scopes match. |
| `GRANTS_TO_USERS` | 26 | MFA/grant/account-health paths use shared snapshots where column shape matches. |
| `DATABASE_STORAGE_USAGE_HISTORY` | 10 | Storage trend/detail already has shared loader coverage. |
| `TABLE_STORAGE_METRICS` | 6 | Kept as targeted drilldown source. |
| `COPY_HISTORY` | 14 | Service Health load counters use one shared cached live loader. |

## Current Cost Metering Consolidation

| Query shape | Shared owner | Current consumers |
| --- | --- | --- |
| Usage metering KPI current/prior | `load_shared_usage_metering_kpis` | Usage Overview, Account Health |
| Usage storage KPI current/prior | `load_shared_usage_storage_kpis` | Usage Overview, Account Health live detail |
| Daily warehouse credits | `load_shared_warehouse_daily_credits` | Cost Forecast |
| Daily warehouse credits by warehouse | `load_shared_warehouse_daily_credits_by_warehouse` | Cost Center Burn Rate |
| Bill summary current/prior | `load_shared_bill_metering_summary` | Cost Center Explain This Bill |
| Warehouse delta current/prior | `load_shared_bill_warehouse_delta`, `build_shared_bill_warehouse_delta_live_sql` | Cost Center Explain This Bill, Cost & Contract splash |
| Credit anomalies | `load_shared_warehouse_credit_anomalies` | Cost & Contract Anomaly Log |
| Cost cockpit movement | `build_cost_cockpit_metering_sql` | Cost & Contract mart and live fallback paths |
| Cost run-rate / YOY | `build_cost_run_rate_metering_sql` | Cost & Contract mart and live fallback paths |
| Official service-cost lens | `load_shared_service_cost_lens` | Cost & Contract splash and detail refresh |
| Official service-cost daily trend | `load_shared_service_cost_trend` | Cost & Contract splash |

## Current Security Monitoring Consolidation

| Query shape | Shared owner | Current consumers |
| --- | --- | --- |
| Security live summary and exceptions | `build_shared_security_summary_sql` | Security Monitoring live refresh |
| Security mart-backed summary and exceptions | `build_shared_security_mart_brief_sql` | Security Monitoring fast summary |
| Privileged grant review | `build_shared_security_privileged_grant_review_sql` | Security Monitoring privileged grant status |
| MFA compatibility expressions | `shared_mfa_count_expr`, `shared_mfa_gap_predicate`, `shared_mfa_proof_label` | Security Monitoring, shared MFA/access loaders |
| MFA coverage snapshot | `load_shared_mfa_coverage` | Security Access and reusable access posture surfaces |
| User role grants | `load_shared_grants_to_users` | Security Access and reusable access posture surfaces |
| Account access hygiene | `build_shared_access_hygiene_sql`, `load_shared_access_hygiene_snapshot` | Account Health access hygiene |

Security Monitoring now keeps its UI-specific wrappers in the section while the
large summary, exception, and privileged-grant SQL builders live in
`utils.shared_metrics`. Account Health access hygiene also delegates its legacy
SQL wrapper to the shared account-hygiene builder. This keeps the existing
fast-summary/live-refresh behavior and centralizes MFA column compatibility,
grant mart usage, login mart usage, privileged-grant review shape, account-level
access hygiene scope labels, and bounded live ACCOUNT_USAGE fallback in
one utility layer.

## Current Service Health Consolidation

| Query shape | Shared owner | Current consumers |
| --- | --- | --- |
| Query runtime/error/queue health | `load_shared_service_query_health` | Service Health |
| Warehouse pressure health | `load_shared_service_warehouse_health` | Service Health |
| Login success/failure health | `load_shared_service_login_health` | Service Health |
| Task run/failure health | `load_shared_service_task_health` | Service Health |
| Load success/failure health | `load_shared_service_pipe_health` | Service Health |

Service Health now gets its hourly cards from shared loaders. The query,
warehouse, login, and task paths prefer marts when the lookback and grain fit,
then fall back to bounded ACCOUNT_USAGE scans. The load path remains a bounded
`COPY_HISTORY` scan because there is not a broader shared consumer yet.

## Current Warehouse Health Consolidation

| Query shape | Shared owner | Current consumers |
| --- | --- | --- |
| Warehouse overview and movement | `load_shared_warehouse_overview` | Warehouse Health overview |
| Scaling and metering events | `load_shared_warehouse_scaling_events` | Warehouse Health scaling events |
| Efficiency risk scoring | `load_shared_warehouse_efficiency` | Warehouse Health efficiency panel |
| Spill and memory pressure | `load_shared_warehouse_spill` | Warehouse Health spill/memory panel |
| Workload heatmap | `load_shared_warehouse_heatmap` | Warehouse Health workload heatmap |
| Duplicate query patterns | `load_shared_duplicate_query_patterns` | Warehouse Health optimization advisor |
| Right-sizing candidates | `load_shared_warehouse_right_sizing` | Warehouse Health optimization advisor |

Warehouse Health now routes overview/scaling, efficiency, spill, heatmap, and
advisor panels through shared loaders. The support panels remain explicit user
actions, but their live ACCOUNT_USAGE paths now share cache keys, optional-column
compatibility, and source captions instead of rebuilding SQL in the section.

The Cost & Contract detail refresh now refreshes run-rate, action queue,
attribution, service lens, and advisor detail paths regardless of whether the
fast cockpit mart succeeds. The official service-cost frames use
`SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY` through shared loaders so future cost
surfaces can reuse the same bounded Snowflake scan.

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
contracts that represent desired production setup behavior. Query consolidation
can continue without changing the drop script; mass reset should still use
`snowflake/OVERWATCH_MART_DROP.sql` before a fresh setup run.

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
