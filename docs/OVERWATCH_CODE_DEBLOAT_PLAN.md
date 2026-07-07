# OVERWATCH Code De-Bloat Plan

Date: 2026-06-23

## Goal

Reduce bloat without breaking the six-section operator model or removing useful Snowflake DBA functionality.

## Highest-Bloat Files

| File | Approx lines | Primary issue | Action |
|---|---:|---|---|
| `.overwatch_final/sections/contention_center.py` | 2356 | Contention investigation, render helpers, and route orchestration remain combined. | Revisit after delegated route metrics show active use. |
| `.overwatch_final/sections/stored_proc_tracker.py` | 1849 | Stored procedure tracker still mixes workflow UI, metadata, and evidence helpers. | Revisit only after route metrics prove active use. |
| `.overwatch_final/sections/dba_control_room/render.py` | 1787 | DBA Control Room render orchestration remains broad inside the already-split package. | Revisit after legacy route cleanup and route metrics. |
| `.overwatch_final/theme.py` | 1694 | Shared style and app chrome helpers remain broad but stable. | Revisit only after route metrics and production-readiness gates are green. |

## Completed Thin Facades

| File | Approx lines | Status |
|---|---:|---|
| `.overwatch_final/sections/change_drift.py` | 97 | Change Drift public selector/renderer-dispatch and compatibility reexport facade after contracts, common helpers, SQL/evidence helpers, models, action queue writers, and both Change Brief / Change Workflows renderers moved into focused modules. |
| `.overwatch_final/sections/task_management.py` | 74 | Task Management public workflow selector/renderer-dispatch and compatibility reexport facade after contracts, models, SQL/action helpers, read-only workflow renderers, and guarded task control renderers moved into focused modules. |
| `.overwatch_final/sections/executive_landing.py` | 133 | Executive Landing public workflow selector/load-gate/renderer-dispatch and compatibility reexport facade after contracts, models, observability loading, workflow panes, charts, data-health, and admin rollups moved into focused modules. |
| `.overwatch_final/sections/cost_center.py` | 92 | Cost Center public selector/renderer-dispatch and compatibility reexport facade after contracts, models, SQL, action-queue, and all eight view branches moved into focused modules. |
| `.overwatch_final/sections/account_health.py` | 83 | Account Health public route/renderer-dispatch and compatibility reexport facade after Overview, Morning Report, checklist, access hygiene, history, and action-queue split; both pane renderers are map-owned. |
| `.overwatch_final/sections/alert_center.py` | 845 | Alert Center public route/load-gate/renderer-dispatch shell after pane, admin, diagnostics, and data split; legacy Issue Inbox/Triage Digest aliases normalize to Active Alerts. |
| `.overwatch_final/sections/security_posture.py` | 180 | Security Monitoring public route/dispatch and compatibility reexport facade after overview, access-review, action-queue, and privilege-sprawl split, now with explicit `__all__` and a <250-line guard. |
| `.overwatch_final/sections/dba_tools.py` | 304 | Thin public DBA Tools selector/dispatch and compatibility reexport facade, locked by no-implementation tests. |
| `.overwatch_final/utils/shared_metrics.py` | 164 | Import-only shared metrics compatibility facade with explicit `__all__`, identity reexport tests, and no SQL/query/dataframe implementation guardrails. |
| `.overwatch_final/sections/warehouse_health.py` | 229 | Thin Warehouse Health selector/support-panel/dispatch shell after focused split. |
| `.overwatch_final/sections/cost_contract.py` | 257 | Public Cost & Contract entrypoint after focused split. |
| `.overwatch_final/utils/mart.py` | 136 | Mart compatibility facade with explicit `__all__`; contracts, names, filters, loaders, and all SQL builder families now live in focused modules. |
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

## Route Registry / Legacy Alias Cleanup

| File | Approx lines | Contents |
|---|---:|---|
| `.overwatch_final/route_registry.py` | 364 | Central six-section route registry, retired route aliases, workflow aliases, default workflows, compatibility route state, and pure normalization helpers. |
| `.overwatch_final/workflow_contracts.py` | 16 | Compatibility exports for route/workflow contracts used by tests and regression runners. |

Low-risk pure helpers now consume the registry while preserving their public names:
`normalize_executive_landing_workflow()`, `_normalize_alert_center_view()`,
`SECURITY_VIEW_ALIASES`, and `_canonical_account_route()`. `config.py` now
keeps the historical `SECTION_REDIRECTS`, `RETIRED_SECTION_REDIRECTS`,
`SECTION_ROUTE_STATE`, `SECTION_ALIASES`, and `normalize_section_name()` public
surface while sourcing those contracts from `route_registry.py`. Route-registry
tests also assert the registry remains dependency-light and does not import
`config`, Streamlit, Snowflake, section modules, or broader utilities.

## Mart-Load Rationalization Planning

`docs/OVERWATCH_MART_LOAD_RATIONALIZATION.md` inventories current mart families,
daily operator dependency groups, consolidation candidates, advanced/admin
evidence stores, and no-change guardrails. This pass did not drop, disable,
rename, or rewrite mart objects. `tests/test_mart_contracts.py` now locks the
planning document, setup/drop artifact presence, reset-only drop posture,
stable `utils.mart` public helper groups, complete SQL-builder group coverage,
representative object references for every builder, source-caption behavior,
offline `load_mart_table()` success/empty/error behavior, loader reexport
identity, and static setup/drop inventory before future mart load-plan work.
`utils/mart.py` remains the compatibility surface and now reexports focused
contract, name, filter, loader, and SQL-builder modules. `docs/OVERWATCH_PRODUCTION_READINESS.md`
adds release gates for validation, deployment contracts, mart setup, browser
smoke, performance smoke, action queue/admin guard checks, secrets, rollback,
and release notes. `docs/OVERWATCH_RELEASE_EVIDENCE_TEMPLATE.md` captures the
release evidence bundle and explicitly prevents claiming live Snowflake
regression success unless the credentialed run actually happened. The current
release candidate is declared in `docs/OVERWATCH_RELEASE_MANIFEST.md`, its
filled release record is
`docs/releases/OVERWATCH_RELEASE_EVIDENCE_24cd05e_2026-06-24.md`, and
`docs/OVERWATCH_RELEASE_PROCESS.md` documents the manifest/evidence/tagging
flow so historical evidence cannot be mistaken for current release evidence.
`perf_tests/profiles/12_power_users.json`, `perf_tests/run_12_power_users.py`,
and `perf_tests/power_user_review.py` add a repeatable 12-heavy-power-user
browser benchmark and deterministic expert review report for high-traffic
release gates without clicking mutation controls.

## New Focused Mart Modules

| File | Approx lines | Contents |
|---|---:|---|
| `.overwatch_final/utils/mart_contracts.py` | 25 | `MartResult` and `mart_source_caption()` for fallback-friendly mart result contracts. |
| `.overwatch_final/utils/mart_names.py` | 17 | Safe fully-qualified mart object-name helper using existing config and identifier validation. |
| `.overwatch_final/utils/mart_filters.py` | 95 | Pure mart text/company/environment/database/window filter helpers used by existing SQL builders. |
| `.overwatch_final/utils/mart_control_room.py` | 244 | Pure DBA Control Room mart SQL builders. |
| `.overwatch_final/utils/mart_account_health.py` | 275 | Account Health mart SQL builders for storage, cost drivers, change, failure, credit, queue, and YTD summaries. |
| `.overwatch_final/utils/mart_service_health.py` | 91 | Service-health mart SQL builders for query, warehouse, login, and task health summaries. |
| `.overwatch_final/utils/mart_task_procedure.py` | 272 | Task, query-detail lookup, and stored-procedure mart SQL builders. |
| `.overwatch_final/utils/mart_cost.py` | 358 | Bill summary, warehouse delta, chargeback, Cost Explorer, Cost & Contract cockpit, service lens, and run-rate mart SQL builders. |
| `.overwatch_final/utils/mart_warehouse.py` | 189 | Warehouse overview, heatmap, and scaling mart SQL builders. |
| `.overwatch_final/utils/mart_usage.py` | 301 | Usage overview, metering, storage, pressure, cost-driver, query-mix, and database-adoption mart SQL builders. |
| `.overwatch_final/utils/mart_adoption.py` | 140 | Adoption summary, warehouse-size, trend, user/warehouse, user/database, and role/query-type mart SQL builders. |
| `.overwatch_final/utils/mart_storage_pipeline.py` | 180 | Storage trend/detail and pipeline freshness/load failure/volume mart SQL builders. |
| `.overwatch_final/utils/mart_recommendations.py` | 218 | Recommendation, query bottleneck, and query degradation mart SQL builders. |
| `.overwatch_final/utils/mart_loader.py` | 74 | Offline-safe mart loaders for generic mart table reads and the latest Control Room summary, reexported through `utils.mart`. |

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
| `.overwatch_final/sections/security_posture_admin_view.py` | 307 | Advanced security evidence panels, score drivers, workflow route coverage, action approvals, command findings, and data-health renderer. |
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
| `.overwatch_final/sections/cost_center_sql.py` | 335 | Annual service projection, optional query-history expression probe, admin reconciliation, Cost Explorer live, chargeback verification, and warehouse cost verification SQL builders. |
| `.overwatch_final/sections/cost_center_action_queue.py` | 359 | Review-only cost outlier and bill exception action-queue payload/writer helpers preserving workflow route and verification contracts. |
| `.overwatch_final/sections/cost_center_explorer_view.py` | 259 | Cost Explorer renderer preserving lens, min-cost, department filter, load, source, and queue keys. |
| `.overwatch_final/sections/cost_center_explain_view.py` | 635 | Explain This Bill renderer preserving all `cc_explain_*` loads, source metadata, finance movement, service-credit caveats, markdown download, and exception queue behavior. |
| `.overwatch_final/sections/cost_center_user_leaderboard_view.py` | 181 | User Leaderboard renderer preserving user profile and leaderboard queue keys plus `cost_leaderboard.csv`. |
| `.overwatch_final/sections/cost_center_burn_view.py` | 125 | Burn Rate renderer preserving `br_days`, `br_load`, `df_br`, `cc_burn_source`, and `burn_rate.csv`. |
| `.overwatch_final/sections/cost_center_reconciliation_view.py` | 254 | Reconciliation renderer preserving `cc_recon_*`, admin bridge state, and `cost_reconciliation.csv`. |
| `.overwatch_final/sections/cost_center_forecast_view.py` | 182 | Forecast renderer preserving run-rate and annual service projection keys. |
| `.overwatch_final/sections/cost_center_attribution_view.py` | 152 | Attribution renderer preserving `cc_attr_*` keys and attribution drilldown/download behavior. |
| `.overwatch_final/sections/cost_center_chargeback_view.py` | 282 | Chargeback renderer preserving chargeback load/queue keys, ALFA/Trexis scope behavior, allocation readiness fields, and mart-first fallback. |

## New Focused Executive Landing Modules

| File | Approx lines | Contents |
|---|---:|---|
| `.overwatch_final/sections/executive_landing_contracts.py` | 38 | Executive Landing version, workflow names, workflow order, and legacy workflow alias map. |
| `.overwatch_final/sections/executive_landing_common.py` | 164 | Active scope helpers, formatting helpers, workflow normalization, workflow-state sync, token filtering, and `executive_nav_*` navigation button behavior. |
| `.overwatch_final/sections/executive_landing_models.py` | 1368 | Platform operating score, source-health/snapshot summary models, observability KPI/advisor rows, pressure lanes, decision rows, command summary rows, and action brief logic. |
| `.overwatch_final/sections/executive_landing_data.py` | 758 | Snapshot loading, offline-safe Snowflake session handling, observability mart SQL/build parts, first-paint payload storage, autoload gates, and source/error handling. |
| `.overwatch_final/sections/executive_landing_charts.py` | 557 | Observability source status, executive command/priority/pressure boards, advisor overlay, line/bar chart renderers, and observability wall chart panels. |
| `.overwatch_final/sections/executive_landing_data_health_view.py` | 122 | Executive Data Health panel and loaded alert-context drillthrough with existing `executive_alert_*` keys. |
| `.overwatch_final/sections/executive_landing_overview_view.py` | 221 | Executive Overview renderer, Load Snapshot prompt, next-click navigation, front-door KPI rows, and executive decision table. |
| `.overwatch_final/sections/executive_landing_cost_view.py` | 104 | Cost Movement renderer preserving cost drillthrough navigation, forecast summary, and cost-movement rows. |
| `.overwatch_final/sections/executive_landing_operational_view.py` | 104 | Operational Risk renderer preserving workload/DBA navigation and snapshot-gated operational alerts. |
| `.overwatch_final/sections/executive_landing_security_view.py` | 105 | Security Risk renderer preserving Security Monitoring navigation and snapshot-gated security alerts. |
| `.overwatch_final/sections/executive_landing_change_view.py` | 100 | Change Summary renderer preserving change-intelligence summary, migration rows, data-health expander, and change navigation. |
| `.overwatch_final/sections/executive_landing_actions_view.py` | 99 | Executive Actions renderer preserving decision/action queue display and snapshot gate. |
| `.overwatch_final/sections/executive_landing_admin_view.py` | 497 | Executive Admin / Advanced renderer, scorecard/value ledger/data trust/production readiness rollups, forecasts, change intelligence, closed-loop, and correlated-investigation summaries. |

## New Focused Task Management Modules

| File | Approx lines | Contents |
|---|---:|---|
| `.overwatch_final/sections/task_management_contracts.py` | 26 | Task Management workflow names, details, task state sets, and recovery SLA target. |
| `.overwatch_final/sections/task_management_common.py` | 124 | Quoted task names, typed confirmation helpers, task inventory load wrapper, execution-context cache, admin SQL runner, and admin audit wrapper. |
| `.overwatch_final/sections/task_management_models.py` | 1569 | Task/procedure dependency parsing, predecessor/root detection, graph impact, failure classification, recovery SLA, critical-path, job-status, reliability, and runbook dataframe models. |
| `.overwatch_final/sections/task_management_sql.py` | 185 | ETL/admin audit FQNs, query-detail SQL, guarded task/graph SQL builders, preflight SQL, and reliability proof/generated SQL helpers. |
| `.overwatch_final/sections/task_management_action_queue.py` | 183 | Review-only task history, ETL audit, failure-console, and operations-brief action queue payloads/writers. |
| `.overwatch_final/sections/task_management_job_status_view.py` | 543 | Job Status Brief renderer, mart-first/live-gated task operations scope load, task status boards, critical-path view, and task graph operations download. |
| `.overwatch_final/sections/task_management_failure_console_view.py` | 206 | Failure Console renderer preserving failure load, category/detail filters, action-queue handoff, query telemetry, and runbook download keys. |
| `.overwatch_final/sections/task_management_sla_cost_view.py` | 252 | SLA & Cost Drift renderer preserving release-risk, query detail, and drift workflow keys. |
| `.overwatch_final/sections/task_management_history_view.py` | 108 | Task History renderer preserving task/history load state, failed-task queue handoff, and `task_history.csv`. |
| `.overwatch_final/sections/task_management_etl_audit_view.py` | 79 | ETL Audit renderer preserving `etl_load`, `tm_df_etl`, `tm_etl_queue`, recent-window query, and `etl_audit.csv`. |
| `.overwatch_final/sections/task_management_control_view.py` | 296 | Guarded Control Center renderer preserving typed confirmations, `admin_button_disabled()`, graph/task/cancel keys, admin action audit, and rerun behavior. |
| `.overwatch_final/sections/task_management_execute_view.py` | 109 | Guarded Execute Task renderer preserving typed confirmation, on-demand execute key behavior, and admin audit logging. |

## New Focused Change Drift Modules

| File | Approx lines | Contents |
|---|---:|---|
| `.overwatch_final/sections/change_drift_contracts.py` | 78 | Change Drift view/workflow contracts, brief workflow launchpad metadata, delegated workflow routing, stable evidence table names, and scope filter keys. |
| `.overwatch_final/sections/change_drift_common.py` | 55 | Active scope helpers, freshness/confidence labels, operator notes, and delegated workflow module rendering. |
| `.overwatch_final/sections/change_drift_sql.py` | 592 | Change-control evidence and operability fact FQN/DDL/migration SQL, scoped drift queries, evidence history, closure analytics, and ticket extraction SQL fragments. |
| `.overwatch_final/sections/change_drift_models.py` | 1266 | Change ticket parsing, qualified-name splitting, source-health rows, owner/readiness models, control boards, priority views, score/rating helpers, verification SQL, and markdown export builders. |
| `.overwatch_final/sections/change_drift_action_queue.py` | 214 | Review-only change exception action payloads, action queue writer, and evidence snapshot persistence helper. |
| `.overwatch_final/sections/change_drift_brief_view.py` | 598 | Change Brief renderer preserving brief-first behavior, explicit evidence/snapshot loads, queue handoff, trend/closure gates, and download keys. |
| `.overwatch_final/sections/change_drift_workflows_view.py` | 100 | Change Workflows renderer preserving delegated workflow module routing and DBA Tools focus handoff behavior. |

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
| Large app modules above 3000 lines | 0 | 3 or fewer |
| Daily operator mart tables | 90+ expected in current setup | 28-34 after migration |
| Primary route aliases exposed to users | Several before this pass | Zero known in primary UI |
| Live Snowflake regression coverage | Credentialed PASS recorded in `docs/OVERWATCH_SNOWFLAKE_REGRESSION_RESULTS.md` | Passing in test account |

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
- `tests/test_executive_landing_split.py` locks Executive Landing workflow contracts, legacy aliases, compatibility reexports, scoring/filter helpers, offline snapshot behavior, renderer map coverage, dispatch helper behavior, key/navigation preservation, and the Executive Landing facade no-creep guard.
- `tests/test_task_management_split.py` locks Task Management workflow contracts, compatibility reexports, graph/model helpers, guarded SQL builders, review-only action queue payloads, renderer map coverage, view key preservation, and the Task Management facade no-creep guard.
- `tests/test_change_drift_split.py` locks Change Drift view/workflow contracts, delegated module routing, compatibility reexports, evidence and operability SQL builders, ticket/qualified-name parsing, review-only action queue payloads, renderer map coverage, key preservation, and the Change Drift facade no-creep guard.
- `tests/test_facade_no_creep.py` applies a global line-count, `__all__`, renderer-map, and no-implementation-creep guard across completed facade files.
- `tests/test_validation_workflow.py` locks the GitHub Validate workflow contract, including push/pull-request triggers on `main`, read-only permissions, dependency installation from both requirement files, Ruff, mypy, compileall, deployment contract, targeted shell guards, Cortex guardrails, unittest discovery, mojibake scan roots and `__pycache__` exclusion, timeout budget, and Ruff-before-typecheck ordering.
- `tests/test_route_registry.py` locks the central route registry, old 4-section absence from primary UI, legacy section aliases, workflow/default validity, config.py compatibility reexports, route-state parity, dependency-light source guard, import-only runtime smoke behavior, Executive Landing aliases, Security Monitoring aliases, Alert Center aliases, and Account Health retired-route normalization.
- `tests/test_mart_contracts.py` locks the static mart-load rationalization inventory, setup/drop artifact presence, reset-only drop posture, `mart_object_name()` behavior, public `utils.mart` helper groups, complete `build_mart_*_sql` grouping, explicit `utils.mart.__all__` coverage, focused-module identity reexports including the loader split, mart filter behavior, every grouped SQL builder's mart object references/no-ACCOUNT_USAGE posture, `utils.mart` facade no-SQL/no-loader-definition guard, `load_mart_table()` success/empty/error behavior, source-caption behavior, unique setup table names, required core facts, and static task/procedure families.
- `tests/test_production_readiness_contract.py` locks the production-readiness checklist document, six-section route sanity model, compatibility/deep-link framing, static release gate references, and release evidence template.
- `tests/test_release_manifest_contract.py` locks the manifest-backed current release candidate, required artifact references, release-ready gate results, and manifest-to-evidence SHA matching.
- `tests/test_release_evidence_contract.py` locks the release evidence template, requires at least one filled release record, blocks empty placeholder bullets, requires the manifest-referenced evidence to match the manifest commit SHA, requires validation PASS bullets to include command/result summaries, requires live Snowflake PASS claims to cite the recorded result document and environment fields, and requires "not run" claims to include a reason.
- `tests/test_snowflake_regression_results_contract.py` locks the recorded live Snowflake regression result fields and ensures recommended follow-ups such as section smoke and full unit regression are either recorded in release evidence or explicitly deferred.
- `tests/test_release_process_contract.py` locks the release process document so release candidates, evidence files, validation, deployment, live-regression caveats, tagging, and rollback/reset references stay documented.
- `tests/test_perf_live_concurrent_runner.py` locks profile loading, CLI override behavior, section-to-button load mappings, and forbidden mutation-control labels for the live concurrent browser runner.
- `tests/test_perf_power_user_contract.py` locks the 12-heavy-power-user profile, safe load-button posture, wrapper/report script presence, and deterministic expert-panel report generation.
- `tests/test_command_center.py` now validates correlated investigation UI placement and explicit load gates.
- `tests/test_contention_center.py`, `tests/test_formula_regressions.py`, and `tests/test_operational_intelligence.py` validate renamed workflow/action contracts.
- `perf_tests/full_app_snowflake_regression.py` is the live Snowflake gate when credentials/auth are available.

## Next Rewrite Order

1. If release candidate is release-ready, deploy/stage using `STREAMLIT_CLOUD_DEPLOY.md`.
2. If not release-ready, resolve failed or deferred gates first.
3. Run the 12-heavy-power-user benchmark and attach the expert review before high-traffic rollout.
4. Add/rerun live Snowflake regression only when credentials/auth are available.
5. Revisit `contention_center.py` / `stored_proc_tracker.py` / DBA Control Room render only with route metrics.
6. Mart load-plan rationalization only after release evidence is green.

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
| Cost Center split completed for current pass | Reduced `.overwatch_final/sections/cost_center.py` from about 3106 lines to about 92 lines by moving contracts, allocation/dataframe models, SQL builders, review-only action queue helpers, optional query-history expression probing, and all eight Cost Center render branches into focused modules. `COST_CENTER_RENDERERS` covers Cost Explorer, Explain This Bill, User Leaderboard, Burn Rate, Reconciliation, Forecast, Attribution, and Chargeback while preserving existing Streamlit keys, session-state names, CSV filenames, mart-first/live fallback behavior, and review-gated action queue boundaries. |
| Executive Landing split completed for current pass | Reduced `.overwatch_final/sections/executive_landing.py` from about 3746 lines to about 133 lines by moving workflow contracts, common navigation/scope helpers, platform/observability models, offline-safe data loading, charts, data-health panels, all seven workflow renderers, and Executive Admin / Advanced rollups into focused modules. `EXECUTIVE_LANDING_RENDERERS` covers Executive Overview, Cost Movement, Operational Risk, Security Risk, Change Summary, Executive Actions, and Executive Admin / Advanced while preserving legacy aliases, progressive/on-demand loading, offline Snowflake behavior, `executive_landing_*` session-state keys, and `executive_nav_*` navigation behavior. |
| Task Management split completed for current pass | Reduced `.overwatch_final/sections/task_management.py` from about 3530 lines to about 74 lines by moving contracts, typed-confirmation/common helpers, task graph/failure/recovery models, SQL builders, review-only action queue helpers, read-only workflow renderers, and guarded Control Center / Execute Task branches into focused modules. `TASK_MANAGEMENT_RENDERERS` covers Job Status Brief, Failure Console, SLA & Cost Drift, Task History, ETL Audit, Control Center, and Execute Task while preserving task/session keys, typed confirmations, `admin_button_disabled()`, `log_admin_action()` audit behavior, task mutation SQL, and review-only action queue boundaries. |
| Task Management guarded SQL hardening | Added focused cancel/execute SQL builders in `task_management_sql.py` for `SYSTEM$CANCEL_TASK_GRAPH`, `SYSTEM$CANCEL_QUERY`, and `EXECUTE TASK`, then routed Control Center / Execute Task renderers through those helpers while preserving typed confirmations, admin-disabled guards, audit logging, and existing keys. |
| Change Drift split completed for current pass | Reduced `.overwatch_final/sections/change_drift.py` from about 2924 lines to about 97 lines by moving contracts, active-scope/common helpers, evidence and operability SQL, ticket/readiness/control models, review-only action queue writers, evidence snapshot persistence, Change Brief rendering, and Change Workflows delegated routing into focused modules. `CHANGE_DRIFT_RENDERERS` covers Change Brief and Change Workflows while preserving delegated modules, evidence table names, workflow keys, DBA Tools handoff behavior, and review-only action queue boundaries. |
| Global facade no-creep guard | Added `tests/test_facade_no_creep.py` to keep completed facades under explicit line thresholds, verify `__all__` exports, validate renderer-map coverage, and block SQL/query/dataframe implementation creep from returning to route shells. |
| Route registry consolidation | Added `.overwatch_final/route_registry.py` and converted `workflow_contracts.py` into a compatibility export. Executive Landing workflow aliases, Alert Center pane aliases, Security Monitoring view aliases, and Account Health retired-route normalization now read from the registry through their existing public helper names. |
| Change Drift / Task Management helper hardening | Made Change Drift action payload `Verification Status` explicitly use the approval-route status instead of relying on a duplicate dict key overwrite. Added source and helper tests that Task Management cancellation/execute renderers continue to use focused SQL builders. |
| Mart-load rationalization planning | Added `docs/OVERWATCH_MART_LOAD_RATIONALIZATION.md` as a static inventory of current mart families, daily operator dependency groups, consolidation candidates, advanced/admin evidence stores, and no-drop guardrails. |
| Validation, route, and mart contract hardening | Expanded workflow contract tests for triggers, permissions, dependency install order, timeout, targeted shell guards, and mojibake exclusions. Added route-registry parity/no-import-cycle checks and deeper mart contracts for public helper groups, representative builder object references, source captions, unique setup tables, required core facts, and setup/drop inventory. No mart object was dropped, renamed, disabled, or rewritten. |
| Mart contracts/names/filters micro-split | Moved `MartResult`, `mart_source_caption()`, `mart_object_name()`, and pure mart filter/window helpers into `mart_contracts.py`, `mart_names.py`, and `mart_filters.py` while keeping all public and private compatibility imports available from `utils.mart`. Large SQL builder families were subsequently split once contract coverage was in place. |
| Mart SQL-family split started | Moved pure DBA Control Room, Account Health, Service Health, Task, Query Detail, and Procedure SQL builders into focused `mart_control_room.py`, `mart_account_health.py`, `mart_service_health.py`, and `mart_task_procedure.py` modules. `utils.mart` remains the compatibility surface and keeps `load_mart_table()`, `load_latest_control_room_mart()`, and the larger cost/warehouse/usage/adoption/storage/pipeline/recommendation builder families. Complete builder grouping, object-reference, no-ACCOUNT_USAGE, and identity tests cover the moved families. |
| Mart SQL-family split completed | Moved the remaining cost, warehouse, usage, adoption, storage/pipeline, recommendation, bottleneck, and degradation mart SQL builders into focused modules. `utils.mart` became a 136-line compatibility reexport facade with explicit `__all__`; tests cover every public builder's focused-module identity, grouping, mart object references, no direct ACCOUNT_USAGE references, and loader success/empty/error behavior. |
| Mart loader split and release evidence hardening | Moved `load_mart_table()` and `load_latest_control_room_mart()` into `mart_loader.py`, keeping their public `utils.mart` reexports and offline success/empty/error behavior intact. Added route-aware production-readiness checklist coverage, a release evidence template, manifest-backed release evidence for `24cd05e`, and contract tests for validation, deployment, mart setup, browser/performance smoke, action queue/admin guard smoke, live-regression caveats, deferred items, and rollback references. |
