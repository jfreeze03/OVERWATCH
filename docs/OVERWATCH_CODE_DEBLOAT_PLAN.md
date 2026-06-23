# OVERWATCH Code De-Bloat Plan

Date: 2026-06-23

## Goal

Reduce bloat without breaking the six-section operator model or removing useful Snowflake DBA functionality.

## Highest-Bloat Files

| File | Approx lines | Primary issue | Action |
|---|---:|---|---|
| `.overwatch_final/sections/executive_landing.py` | 3746 | Advanced rollups remain in same module as front door. | Split advanced/admin rollups later if tests prove import or render pain. |
| `.overwatch_final/sections/task_management.py` | 3530 | Task management and pipeline health overlap Pipeline & Task Health. | Keep as delegated implementation, remove duplicate entry points only after regression. |
| `.overwatch_final/sections/change_drift.py` | 2924 | Change drift mixes overview, evidence, and investigation rendering. | Below 3000 now; revisit after larger modules are reduced. |

## Completed Thin Facades

| File | Approx lines | Status |
|---|---:|---|
| `.overwatch_final/sections/cost_center.py` | 99 | Cost Center public selector/renderer-dispatch and compatibility reexport facade after contracts, models, SQL, action-queue, and all eight view branches moved into focused modules. |
| `.overwatch_final/sections/account_health.py` | 83 | Account Health public route/renderer-dispatch and compatibility reexport facade after Overview, Morning Report, checklist, access hygiene, history, and action-queue split; both pane renderers are map-owned. |
| `.overwatch_final/sections/alert_center.py` | 845 | Alert Center public route/load-gate/renderer-dispatch shell after pane, admin, diagnostics, and data split; legacy Issue Inbox/Triage Digest aliases normalize to Active Alerts. |
| `.overwatch_final/sections/security_posture.py` | 180 | Security Monitoring public route/dispatch and compatibility reexport facade after overview, access-review, action-queue, and privilege-sprawl split, now with explicit `__all__` and a <250-line guard. |
| `.overwatch_final/sections/dba_tools.py` | 304 | Thin public DBA Tools selector/dispatch and compatibility reexport facade, locked by no-implementation tests. |
| `.overwatch_final/utils/shared_metrics.py` | 164 | Import-only shared metrics compatibility facade with explicit `__all__`, identity reexport tests, and no SQL/query/dataframe implementation guardrails. |
| `.overwatch_final/sections/warehouse_health.py` | 229 | Thin Warehouse Health selector/support-panel/dispatch shell after focused split. |
| `.overwatch_final/sections/cost_contract.py` | 243 | Public Cost & Contract entrypoint after focused split. |
| `.overwatch_final/utils/alerts.py` | 132 | Stable alert helper compatibility facade after focused utility split. |

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

## New Shared UI Helpers

| File | Approx lines | Contents |
|---|---:|---|
| `.overwatch_final/utils/explicit_load.py` | 72 | Opt-in explicit dataframe load helper and CSV export wrapper for repeated button/session-state/download patterns. |

## New Focused Alert Center Modules

| File | Approx lines | Contents |
|---|---:|---|
| `.overwatch_final/sections/alert_center_contracts.py` | 181 | Pane names, admin subview contracts, source-plan metadata, and deferred source notes. |
| `.overwatch_final/sections/alert_center_navigation.py` | 80 | Legacy alias normalization, admin subview routing, source-set selection, and operator source summaries. |
| `.overwatch_final/sections/alert_center_data.py` | 103 | Bounded source loading for alerts, action queue, delivery, rules, native registry, remediation policy, dry-run rows, and issue rows. |
| `.overwatch_final/sections/alert_center_boards.py` | 1205 | Pure Alert Center readiness, workflow, exception, lifecycle, route, and review board builders. |
| `.overwatch_final/sections/alert_center_active_view.py` | 233 | Active Alerts pane renderer, active incident packet, operator workflow detail, and advisor candidate display. |
| `.overwatch_final/sections/alert_center_category_views.py` | 133 | Cost, Reliability, and Security alert category workbenches plus tested category token mapping. |
| `.overwatch_final/sections/alert_center_history_view.py` | 245 | Alert History pane renderer, lifecycle summary, status update, escalation acknowledgement, and audit preview forms. |
| `.overwatch_final/sections/alert_center_admin_catalog_view.py` | 132 | Detection Catalog renderer and read-only native registry load using the shared explicit-load helper. |
| `.overwatch_final/sections/alert_center_admin_delivery_view.py` | 449 | Delivery & Automation renderer, action queue routing/mutation path, email delivery review, remediation status, and tested control-row helpers. |
| `.overwatch_final/sections/alert_center_admin_suppression_view.py` | 195 | Suppression Windows admin renderer plus tested insert/select/deactivate SQL builders. |
| `.overwatch_final/sections/alert_center_diagnostics_view.py` | 269 | Advanced diagnostics and enterprise evidence panels with existing explicit-load/session-state keys preserved. |

## New Focused Security Posture Modules

| File | Approx lines | Contents |
|---|---:|---|
| `.overwatch_final/sections/security_posture_contracts.py` | 143 | Security workflow names, details, legacy aliases, brief workflow cards, and delegated module routing. |
| `.overwatch_final/sections/security_posture_common.py` | 102 | Active scope helpers, MFA shared-helper passthroughs, freshness/confidence labels, operator notes, and delegated workflow module rendering. |
| `.overwatch_final/sections/security_posture_models.py` | 262 | Scope metadata matching, proof-table visibility flags, source-health rows, and security score/rating helpers. |
| `.overwatch_final/sections/security_posture_data.py` | 130 | Security summary SQL wrappers and mart-first/live-fallback summary loader preserving session-state keys and source labels. |
| `.overwatch_final/sections/security_posture_alerts_view.py` | 52 | Loaded Security Alerts context renderer with existing Alert Center and drilldown buttons. |
| `.overwatch_final/sections/security_posture_access_changes_view.py` | 58 | Explicit-load Security-Sensitive Changes detail renderer. |
| `.overwatch_final/sections/security_posture_admin_view.py` | 307 | Advanced security evidence panels, score drivers, ownership coverage, action approvals, command findings, and data-health renderer. |
| `.overwatch_final/sections/security_posture_overview_view.py` | 1104 | Security Overview controller, refresh/freshness behavior, exception loading, proof-table gates, summary download, and secondary control-detail panels. |
| `.overwatch_final/sections/security_posture_access_review.py` | 1013 | Access-review DDL/migration SQL, verification SQL, review readiness, control-board, closure/fact SQL, and snapshot save helpers. |
| `.overwatch_final/sections/security_posture_action_queue.py` | 247 | Security exception and privileged-grant action-queue writers with existing action payload contracts. |
| `.overwatch_final/sections/security_posture_privilege_sprawl_view.py` | 275 | Privileged grant readiness annotation, sprawl summary, and Privilege Sprawl renderer with existing explicit-load/action-queue keys. |

## New Focused Account Health Modules

| File | Approx lines | Contents |
|---|---:|---|
| `.overwatch_final/sections/account_health_contracts.py` | 40 | Account Health pane contracts, stable source identifiers, table names, and scope filter keys. |
| `.overwatch_final/sections/account_health_common.py` | 43 | Credit-price fallback, retired route normalization, operator notes, and action-session wrapper. |
| `.overwatch_final/sections/account_health_models.py` | 276 | Scope metadata matching, loaded/empty/source-state helpers, and Account Health source-readiness rows. |
| `.overwatch_final/sections/account_health_data.py` | 176 | Task SQL fallbacks, optional Query History capability probes, live query status SQL/load helper, and control-room mart gate. |
| `.overwatch_final/sections/account_health_sql.py` | 159 | Checklist/action queue/operability FQN builders plus checklist history and operability fact DDL/migration SQL. |
| `.overwatch_final/sections/account_health_source_health_view.py` | 51 | Account Health data-health/source-readiness renderer using the moved source-health model rows. |
| `.overwatch_final/sections/account_health_checklist.py` | 1119 | Checklist routing, owner context, verification SQL, readiness annotations, control-board helpers, morning exception rows, and action-brief helpers. |
| `.overwatch_final/sections/account_health_action_queue.py` | 204 | Review-only checklist and account-access hygiene action queue payloads/writers with existing source/category/recovery fields. |
| `.overwatch_final/sections/account_health_access_hygiene.py` | 150 | Account-level access hygiene SQL wrapper, annotation, and read-only user/auth verification SQL. |
| `.overwatch_final/sections/account_health_access_hygiene_view.py` | 147 | Account Access Hygiene renderer preserving load, source, meta, and queue keys plus No Database Context scope. |
| `.overwatch_final/sections/account_health_morning_view.py` | 221 | DBA Daily Brief packet builder and Morning Report renderer preserving lookback, fallback, source, meta, and morning packet keys. |
| `.overwatch_final/sections/account_health_overview_models.py` | 214 | Overview operating snapshot renderer and DBA intervention-matrix model extracted from the route. |
| `.overwatch_final/sections/account_health_history.py` | 353 | Checklist history insert/trend SQL, closure analytics SQL, operability fact SQL, and checklist snapshot persistence. |
| `.overwatch_final/sections/account_health_overview_view.py` | 986 | Account Health Overview controller/renderer preserving health refresh, auto-load scope, checklist, access hygiene, trend, closure, secondary evidence, quick nav, and warehouse-pressure keys. |

## New Focused Cost Center Modules

| File | Approx lines | Contents |
|---|---:|---|
| `.overwatch_final/sections/cost_center_contracts.py` | 77 | Cost Center view names, labels, details, no-database-context sentinels, and Cost Explorer lens metadata. |
| `.overwatch_final/sections/cost_center_models.py` | 848 | Allocation-quality, environment-rollup, forecast, Cost Explorer summary/gap, bill movement, finance bridge, service grouping, and Explain Bill markdown helpers. |
| `.overwatch_final/sections/cost_center_sql.py` | 321 | Annual service projection, admin reconciliation, Cost Explorer live, chargeback verification, and warehouse cost verification SQL builders. |
| `.overwatch_final/sections/cost_center_action_queue.py` | 359 | Review-only cost outlier and bill exception action-queue payload/writer helpers preserving owner route and verification contracts. |
| `.overwatch_final/sections/cost_center_explorer_view.py` | 259 | Cost Explorer renderer preserving lens, min-cost, department filter, load, source, and queue keys. |
| `.overwatch_final/sections/cost_center_explain_view.py` | 635 | Explain This Bill renderer preserving all `cc_explain_*` loads, source metadata, finance movement, service-credit caveats, markdown download, and exception queue behavior. |
| `.overwatch_final/sections/cost_center_user_leaderboard_view.py` | 181 | User Leaderboard renderer preserving user profile and leaderboard queue keys plus `cost_leaderboard.csv`. |
| `.overwatch_final/sections/cost_center_burn_view.py` | 125 | Burn Rate renderer preserving `br_days`, `br_load`, `df_br`, `cc_burn_source`, and `burn_rate.csv`. |
| `.overwatch_final/sections/cost_center_reconciliation_view.py` | 254 | Reconciliation renderer preserving `cc_recon_*`, admin bridge state, and `cost_reconciliation.csv`. |
| `.overwatch_final/sections/cost_center_forecast_view.py` | 182 | Forecast renderer preserving run-rate and annual service projection keys. |
| `.overwatch_final/sections/cost_center_attribution_view.py` | 152 | Attribution renderer preserving `cc_attr_*` keys and attribution drilldown/download behavior. |
| `.overwatch_final/sections/cost_center_chargeback_view.py` | 282 | Chargeback renderer preserving chargeback load/queue keys, ALFA/Trexis scope behavior, allocation readiness fields, and mart-first fallback. |

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
| Large app modules above 3000 lines | 2 | 3 or fewer |
| Daily operator mart tables | 90+ expected in current setup | 28-34 after migration |
| Primary route aliases exposed to users | Several before this pass | Zero known in primary UI |
| Live Snowflake regression coverage | New runner, blocked by auth | Passing in test account |

## Tests Proving No Functionality Was Lost

- `.overwatch_final/workflow_contracts.py` now centralizes the six-section workflow contract and legacy route matrix used by both tests and the live Snowflake regression runner.
- `tests/test_navigation_integrity.py` checks the six primary sections, legacy route redirects, workflow names, old 4-section absence, company scoping, and stale chart text.
- `tests/test_alert_status.py` locks down alert status/severity normalization, including the intentional difference between triage status preservation and command-center unknown-status collapse.
- `tests/test_alert_center_split.py` locks Alert Center pane names, renderer maps, legacy alias normalization, admin subview routing, source-set selection, operator source summaries, facade identity for focused modules, board-helper behavior, Delivery & Automation control rows, action-queue routing preview, suppression SQL builders, dispatch behavior, and the Alert Center facade line/no-creep guard.
- `tests/test_alert_facade.py` proves representative `utils.alerts` imports still point to focused modules and that internal callers do not import private facade names.
- `tests/test_alert_lifecycle.py`, `tests/test_alert_triage.py`, `tests/test_alert_action_queue.py`, `tests/test_alert_command_center.py`, `tests/test_alert_catalog.py`, `tests/test_alert_delivery.py`, and `tests/test_alert_native_catalog.py` cover the completed alert helper split.
- `tests/test_explicit_load.py` covers explicit dataframe loads, session-state reuse, error-to-empty-frame handling, and CSV export wrapper behavior.
- `tests/test_account_health_split.py` locks Account Health pane contracts, compatibility reexports, retired route normalization, source-scope metadata, source-health state classification, SQL/FQN builders, data helper contracts, checklist readiness, review-only action queue payloads, access hygiene No Database Context behavior, Morning Report and Overview keys, renderer dispatch coverage, history/closure SQL escaping, snapshot persistence behavior, and the Account Health shell no-creep guard.
- `tests/test_cost_center_split.py` locks Cost Center pane contracts, compatibility reexports, allocation/source helpers, SQL builders, review-only action queue behavior, renderer map coverage, view key preservation, and the Cost Center facade line/no-creep guard.
- `tests/test_command_center.py` now validates correlated investigation UI placement and explicit load gates.
- `tests/test_contention_center.py`, `tests/test_formula_regressions.py`, and `tests/test_operational_intelligence.py` validate renamed workflow/action contracts.
- `perf_tests/full_app_snowflake_regression.py` is the live Snowflake gate once authentication is corrected.

## Next Rewrite Order

1. Split Executive Landing advanced/admin panels if they remain above threshold.
2. Clean up Task Management delegated routes only after route metrics prove no active usage.
3. Consider Change Drift split if route metrics justify it.
4. Retire legacy route rendering.
5. Rationalize mart loads to feed daily workflows directly before dropping any old objects.

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
| Shared metrics and DBA facade lock | Added explicit `__all__` existence/coverage tests and kept `shared_metrics.py` free of ACCOUNT_USAGE strings, query calls, dataframe construction, and shared loader/builder function definitions. |
| Shared explicit-load/export helper | Added `utils.explicit_load` with tested button-gated dataframe loading, session-state reuse, error-to-empty-frame handling, and CSV export wrapping. |
| Alert Center contract/navigation split started | Moved pane contracts, admin subview metadata, source plans, legacy alias normalization, admin route mapping, and source summaries into `alert_center_contracts.py` and `alert_center_navigation.py`, with facade identity tests. |
| Alert Center data and Detection Catalog split started | Moved bounded alert source loading into `alert_center_data.py` and the Detection Catalog pane into `alert_center_admin_catalog_view.py`. Native registry and suppression-window loads now use the shared explicit-load helper while preserving Streamlit/session-state keys. |
| Alert Center board and pane split continued | Reduced `.overwatch_final/sections/alert_center.py` from about 3326 lines to about 1514 lines by moving pure board/model helpers, Active Alerts, Cost/Reliability/Security category panes, Alert History, and Suppression Windows into focused modules. Renderer maps, facade reexports, board behavior, category token patterns, suppression SQL builders, and no-creep guards are covered by tests. |
| Alert Center split completed for current pass | Reduced `.overwatch_final/sections/alert_center.py` from about 1514 lines to about 845 lines by moving Delivery & Automation, email delivery/action-queue routing, remediation admin rendering, and advanced diagnostics into focused modules. Legacy Issue Inbox and Triage Digest render branches were removed because aliases normalize to Active Alerts. The remaining shell owns load gates, freshness, source notes, shared pre-panels, renderer maps, and compatibility reexports. |
| Security Posture contracts/data/initial view split | Reduced `.overwatch_final/sections/security_posture.py` from about 3488 lines to about 2716 lines by moving workflow contracts, common helpers, model/source-health helpers, mart-first summary loading, loaded alert context, access-change detail, and advanced evidence panels into focused modules. The public route keeps compatibility reexports, delegated workflow module routing, Security Overview orchestration, Privilege Sprawl/action-queue behavior, and existing Streamlit/session-state keys. |
| Security Posture overview/controller split | Reduced `.overwatch_final/sections/security_posture.py` from about 2716 lines to about 146 lines by moving the previously unreachable Security Overview refresh/load/proof-table orchestration into `security_posture_overview_view.py`. Existing summary/session-state keys, `security_posture_brief_load`, exception load gates, proof-table gates, queue controls, and summary download behavior are preserved. |
| Security Posture access review and action queue split | Moved access-review DDL/migration SQL, verification SQL, review readiness, control-board builders, closure/fact SQL, snapshot save helpers, and action-queue writers into `security_posture_access_review.py` and `security_posture_action_queue.py`, preserving SQL literalization, action IDs, source/category fields, and `upsert_actions` behavior. |
| Security Posture Privilege Sprawl split | Moved privileged grant review loading, grant readiness annotation, sprawl summary, and Privilege Sprawl rendering into `security_posture_privilege_sprawl_view.py` while preserving `security_privilege_sprawl_load`, `security_priv_grants_queue`, `security_priv_grant_days`, and privileged grant session-state keys. |
| Security Posture facade hardening | Added explicit `__all__` to `security_posture.py` and tightened split tests so the route stays under 250 lines and remains free of ACCOUNT_USAGE strings, query calls, dataframe construction, DDL/DML, and moved private helper definitions. |
| Account Health initial split | Reduced `.overwatch_final/sections/account_health.py` from the local 3604-line baseline (older docs listed about 3812) to about 3190 lines by moving Account Health contracts, common helpers, source-health models, bounded data/query helpers, deterministic FQN/DDL/migration SQL builders, and the source-health renderer into focused modules. The public route keeps compatibility reexports and existing Account Health panes, keys, session-state names, and action behavior; Overview/Morning rendering and action queue/checklist mutation flows are deferred for a guarded pass. |
| Account Health checklist/action/Morning split | Reduced `.overwatch_final/sections/account_health.py` from about 3190 lines to about 1483 lines by moving checklist routing/readiness helpers, review-only action queue payloads/writers, access hygiene SQL/annotation/rendering, and the Morning Report packet builder/renderer into focused modules. Existing Account Health panes and keys are preserved, including access hygiene load/source/meta/queue keys and Morning Report lookback/fallback/source/meta packet keys. The remaining route owns the large Overview branch and a partial renderer map for the moved Morning Report pane. |
| Account Health Overview/history split completed | Reduced `.overwatch_final/sections/account_health.py` from about 1483 lines to about 83 lines by moving the Overview controller/renderer, operating snapshot/intervention helpers, checklist history SQL, closure analytics SQL, operability fact SQL, and checklist snapshot persistence into focused modules. `ACCOUNT_HEALTH_RENDERERS` now covers both Overview and Morning Report, and tests keep the route free of ACCOUNT_USAGE strings, query calls, dataframe construction, DDL/DML, and moved helper definitions. |
| Cost Center split completed for current pass | Reduced `.overwatch_final/sections/cost_center.py` from about 3106 lines to about 99 lines by moving contracts, allocation/dataframe models, SQL builders, review-only action queue helpers, and all eight Cost Center render branches into focused modules. `COST_CENTER_RENDERERS` covers Cost Explorer, Explain This Bill, User Leaderboard, Burn Rate, Reconciliation, Forecast, Attribution, and Chargeback while preserving existing Streamlit keys, session-state names, CSV filenames, mart-first/live fallback behavior, and review-gated action queue boundaries. |
