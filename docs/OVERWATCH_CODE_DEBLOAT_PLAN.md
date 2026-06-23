# OVERWATCH Code De-Bloat Plan

Date: 2026-06-23

## Goal

Reduce bloat without breaking the six-section operator model or removing useful Snowflake DBA functionality.

## Highest-Bloat Files

| File | Approx lines | Primary issue | Action |
|---|---:|---|---|
| `.overwatch_final/sections/dba_tools.py` | 304 | Thin public DBA Tools compatibility facade after extracting contracts, common helpers, planning helpers, setup checks, read-only views, QAS Monitor, Query Kill List, Cortex AI Limits, and Task Graph Control. | Complete for current split and locked by no-implementation tests. Keep this file as selector/focus/dispatch plus compatibility reexports; do not add implementation logic here. |
| `.overwatch_final/utils/shared_metrics.py` | 164 | Public compatibility facade only. Shared metric implementations now live in focused `shared_metrics_*` modules with identity reexport tests and a shrinking/no-implementation guard. | Keep this file import-only; do not add SQL loaders or Snowflake query implementation logic here. |
| `.overwatch_final/sections/account_health.py` | 3604 | Legacy account-health cockpit overlaps DBA Control Room. | Retain as compatibility route, move useful pieces into DBA workflows. |
| `.overwatch_final/sections/executive_landing.py` | 3470 | Advanced rollups remain in same module as front door. | Split advanced/admin rollups later if tests prove import or render pain. |
| `.overwatch_final/sections/alert_center.py` | 3432 | Active alerts, history, admin config, suppression, closed loop, and investigation evidence. | Split active workflow from admin/evidence helpers. |
| `.overwatch_final/sections/task_management.py` | 3281 | Task management and pipeline health overlap Pipeline & Task Health. | Keep as delegated implementation, remove duplicate entry points only after regression. |
| `.overwatch_final/sections/security_posture.py` | 3267 | Security overview, failed logins, grants, sprawl, sharing, admin evidence in one file. | Split advanced evidence after route behavior is stable. |
| `.overwatch_final/sections/warehouse_health.py` | 229 | Thin public Warehouse Health shell after extracting contracts, SQL, dataframe helpers, overview launchpad, action-control builders, setting panels, capacity brief, source-health panels, queue writers, and per-workflow view renderers. | Complete for current split. Keep main `render()` as selector/support-panel/dispatch only. |
| `.overwatch_final/sections/cost_contract.py` | 243 | Public Cost & Contract entrypoint after split; compatibility reexports plus `render()`. | Complete. Keep thin; do not add new implementation logic here. |
| `.overwatch_final/utils/alerts.py` | 132 | Compatibility facade only after alert split. | Keep as stable import surface; do not add new implementation logic here. |

## New Focused Shared Metrics Modules

| File | Approx lines | Contents |
|---|---:|---|
| `.overwatch_final/utils/shared_metrics_contracts.py` | 21 | `SharedMetricResult` and shared storage fallback constants. |
| `.overwatch_final/utils/shared_metrics_cache.py` | 78 | Shared cache keys, session-state reuse, global filter reads, and company column filters. |
| `.overwatch_final/utils/shared_metrics_storage.py` | 319 | Storage trend, storage KPI, and per-database storage detail loaders. |
| `.overwatch_final/utils/shared_metrics_usage.py` | 376 | Usage metering KPI loaders, billing metering live SQL builders, and billing summary/delta loaders. |
| `.overwatch_final/utils/shared_metrics_service_cost.py` | 101 | Official service cost lens and trend loaders. |
| `.overwatch_final/utils/shared_metrics_service_health.py` | 373 | Query, warehouse, login, task, and pipe service-health loaders and optional query-history expression probes. |
| `.overwatch_final/utils/shared_metrics_query.py` | 252 | Query-history rollups and warehouse-pressure summary loaders. |
| `.overwatch_final/utils/shared_metrics_warehouse.py` | 891 | Warehouse credits, anomaly, overview, scaling, efficiency, spill, heatmap, and right-sizing loaders. |
| `.overwatch_final/utils/shared_metrics_security.py` | 835 | MFA/access hygiene SQL builders and security/access snapshot loaders. |
| `.overwatch_final/utils/shared_metrics_recommendations.py` | 672 | Recommendation and duplicate-query advisor loaders. |
| `.overwatch_final/utils/shared_metrics_tasks.py` | 141 | Shared task health and task-history detail loaders. |
| `.overwatch_final/utils/shared_metrics_procedures.py` | 165 | Procedure inventory, call summary, and SLA/cost loaders. |

## Duplicate Code Groups

| Group | Symptoms | Target utility |
|---|---|---|
| Workflow selectors | Multiple sections render similar workflow cards/tabs and alias maps. | Shared workflow selector contract plus per-section map. |
| Active filter badges | Cost, workload, security, and DBA show scope differently. | One `render_active_filter_badge()` utility. |
| Priority dataframes | Repeated sorting, visible columns, raw labels, max rows. | One opinionated priority-table helper per row type. |
| Advanced evidence gates | Many sections repeat Load button + session-state frame storage. | One explicit-load dataframe gate helper. |
| Legacy redirects | Aliases spread across config and section modules. | One route normalization registry, with tests. |
| Download controls | Repeated CSV download calls around similar tables. | Shared export control helper. |

## Dead or Overmodeled Candidates

These are candidates, not approved removals:

| Candidate | Reason | Safe path |
|---|---|---|
| Value-ledger proof widgets in primary flows | Daily operators need action and verified savings only when investigating. | Keep under advanced/admin evidence. |
| Production readiness score in normal flow | Useful for release governance, noisy for daily triage. | Keep under Control Room Admin / Advanced. |
| Full executive scorecard formulas | Leadership needs risk/action, not formula details. | Keep formulas in Executive Admin / Advanced. |
| Closed-loop evidence grids | Required for audit, too heavy for first paint. | Load only behind explicit details. |
| SPCS tracker | Useful only if SPCS is actively used. | Keep advanced until usage is confirmed. |

## Before / After Target

| Metric | Current | Target |
|---|---:|---:|
| Large app modules above 3000 lines | 9 | 3 or fewer |
| Daily operator mart tables | 90+ expected in current setup | 28-34 after migration |
| Primary route aliases exposed to users | Several before this pass | Zero known in primary UI |
| Live Snowflake regression coverage | New runner, blocked by auth | Passing in test account |

## Tests Proving No Functionality Was Lost

- `.overwatch_final/workflow_contracts.py` now centralizes the six-section workflow contract and legacy route matrix used by both tests and the live Snowflake regression runner.
- `tests/test_navigation_integrity.py` checks the six primary sections, legacy route redirects, workflow names, old 4-section absence, company scoping, and stale chart text.
- `tests/test_alert_status.py` locks down alert status/severity normalization, including the intentional difference between triage status preservation and command-center unknown-status collapse.
- `tests/test_alert_facade.py` proves representative `utils.alerts` imports still point to focused modules and that internal callers do not import private facade names.
- `tests/test_alert_lifecycle.py`, `tests/test_alert_triage.py`, `tests/test_alert_action_queue.py`, `tests/test_alert_command_center.py`, `tests/test_alert_catalog.py`, `tests/test_alert_delivery.py`, and `tests/test_alert_native_catalog.py` cover the completed alert helper split.
- `tests/test_command_center.py` now validates correlated investigation UI placement and explicit load gates.
- `tests/test_contention_center.py`, `tests/test_formula_regressions.py`, and `tests/test_operational_intelligence.py` validate renamed workflow/action contracts.
- `perf_tests/full_app_snowflake_regression.py` is the live Snowflake gate once authentication is corrected.

## Next Rewrite Order

1. Consolidate shared explicit-load gates and priority dataframe patterns.
2. Keep `utils.shared_metrics` locked as an import-only compatibility facade; split any newly discovered shared metric family into focused modules first.
3. Retire duplicated legacy route rendering after route metrics prove no active usage.
4. Rewrite mart loads to feed daily workflows directly before dropping any old objects.
5. Keep DBA Tools implementation logic in focused `dba_tools_*` modules and preserve the facade as dispatch/reexports only.

## De-Bloat Completed After Initial Audit

| Item | Result |
|---|---|
| Duplicated six-section workflow list in Snowflake regression runner | Replaced with `.overwatch_final/workflow_contracts.py`. |
| Duplicated legacy route matrix in navigation tests | Replaced with `.overwatch_final/workflow_contracts.py`. |
| Contract drift guard | Added a test that the workflow contract matches the configured six primary sections. |
| Alert facade split | Reduced `.overwatch_final/utils/alerts.py` to a 132-line compatibility facade. Implementation now lives in `alert_action_queue.py`, `alert_annotations.py`, `alert_boards.py`, `alert_catalog.py`, `alert_command_center.py`, `alert_delivery.py`, `alert_lifecycle.py`, `alert_native_catalog.py`, `alert_status.py`, and `alert_triage.py`. |
| Alert status/severity duplication | Centralized alert status and severity constants in `alert_status.py`; command-center unknown-status collapse remains explicit and tested. |
| Alert facade import hygiene | Replaced production `utils.alerts` imports in Alert Center with focused-module imports. No direct private imports from `utils.alerts` are expected outside compatibility tests. |
| Cost & Contract split | Reduced `.overwatch_final/sections/cost_contract.py` from about 5003 lines to a 243-line public shell. Implementation now lives in focused `cost_contract_*` modules for contracts, helpers, dataframes, SQL, charts, advisor, panels, splash/load, monitoring, evidence, rendering, workflow routing, and overview floor orchestration. |
| Warehouse Health split continued | Reduced `.overwatch_final/sections/warehouse_health.py` from about 4108 lines to about 229 lines by extracting stable contracts, SQL builders, pure dataframe helpers, capacity decision helpers, overview launchpad panels, setting/action-control builders, guarded setting panels, review snapshot SQL, capacity SQL/brief/watch-floor helpers, source-health panels, explicit queue writers, the action-session loader, and per-workflow view renderers into focused `warehouse_health_*` modules. The main `render()` flow now remains a thin public selector/support-panel/dispatch shell. |
| DBA Tools helper split started | Reduced `.overwatch_final/sections/dba_tools.py` from about 4128 lines to about 2668 lines by extracting stable contracts, common Streamlit-safe helpers, review-only warehouse setting planning, schema compare normalization/DDL helpers, data compare planning/SQL helpers, and setup status checks into focused `dba_tools_*` modules. |
| DBA Tools render-branch split continued | Reduced `.overwatch_final/sections/dba_tools.py` from about 2668 lines to about 1162 lines by moving Schema Compare, Data Compare, Warehouse Settings, read-only data movement monitors, object monitoring monitors, and read-only cost/health panels into focused `dba_tools_*_view.py` modules. |
| DBA Tools QAS Monitor split | Reduced `.overwatch_final/sections/dba_tools.py` from about 1162 lines to about 998 lines by moving QAS Monitor into `dba_tools_qas_monitor_view.py`, keeping the explicit load button, `dba_df_qas` session-state key, warehouse-size compatibility probe, and priority table contract tested. |
| DBA Tools guarded branch split completed | Reduced `.overwatch_final/sections/dba_tools.py` from about 998 lines to about 304 lines by moving Query Kill List, Cortex AI Limits, and Task Graph Control into focused view/helper modules. Typed confirmations, admin-disabled buttons, ACCOUNTADMIN account-parameter guards, scoped filters, cancellation SQL, task mutation SQL, rerun behavior, and session-state keys remain covered by focused tests. The unreachable legacy Operational Audit placeholder was removed rather than kept in the public shell. |
| DBA Tools facade hardening | Added no-implementation-creep tests that keep `dba_tools.py` free of live query execution, cancellation/task mutation SQL, account-parameter SQL, and dataframe construction. Task Graph Control task mutation SQL now runs through focused helper builders, and root/child matching treats regex-looking task names literally. |
| Shared metrics contracts/cache split | Moved `SharedMetricResult`, storage fallback constants, shared state-key/cache helpers, global filter reads, and company column filters into `shared_metrics_contracts.py` and `shared_metrics_cache.py`, while keeping all names re-exported from `utils.shared_metrics`. |
| Shared metrics storage/usage split | Moved storage trend/KPI/detail loaders into `shared_metrics_storage.py` and usage/billing metering loaders plus billing live SQL builders into `shared_metrics_usage.py`. Cache keys, effective-day caps, source labels, mart-first behavior, and public `utils.shared_metrics` imports remain covered by tests. |
| Shared metrics service cost split | Moved official service cost lens/trend loaders into `shared_metrics_service_cost.py` with the same `SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY` source labels and public facade reexports. |
| Shared metrics service health split | Moved service query, warehouse, login, task, and pipe health loaders into `shared_metrics_service_health.py`. Optional `QUERY_HISTORY` column probes, source labels, mart-first success, and live fallbacks are covered by focused tests. |
| Shared metrics query rollup split | Moved query-history rollups and warehouse-pressure summary loading into `shared_metrics_query.py`, preserving optional-column expressions, global filters, mart-first behavior, and live fallback labels. |
| Shared metrics warehouse split | Moved warehouse credit, anomaly, overview, scaling, efficiency, spill, heatmap, and right-sizing loaders into `shared_metrics_warehouse.py`, preserving mart-first/live fallback behavior and source labels. |
| Shared metrics security/access split | Moved MFA helpers, security summary builders, privileged grant review, access hygiene SQL, and access snapshot loaders into `shared_metrics_security.py` with ALFA/Trexis/company scoping intact. |
| Shared metrics recommendations split | Moved idle/spill/failed-task/query-failure/storage-retention/clustering/repeated-query and duplicate-query advisor loaders into `shared_metrics_recommendations.py`, keeping source labels and fallback behavior stable. |
| Shared metrics task/procedure split | Moved task health/detail loaders into `shared_metrics_tasks.py` and procedure inventory/call/SLA loaders into `shared_metrics_procedures.py`. `utils.shared_metrics` is now a 164-line import-only facade with explicit `__all__`, identity reexport tests, and no-implementation-creep coverage. |
