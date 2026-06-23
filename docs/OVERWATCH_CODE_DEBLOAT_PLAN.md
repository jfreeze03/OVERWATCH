# OVERWATCH Code De-Bloat Plan

Date: 2026-06-22

## Goal

Reduce bloat without breaking the six-section operator model or removing useful Snowflake DBA functionality.

## Highest-Bloat Files

| File | Approx lines | Primary issue | Action |
|---|---:|---|---|
| `.overwatch_final/sections/dba_tools.py` | 3861 | Admin tools, generated SQL, settings controls, compare tools, validation utilities. | Keep under Workload Operations > Advanced DBA Tools / Control Room Admin. |
| `.overwatch_final/utils/shared_metrics.py` | 3804 | Many shared SQL builders and cache wrappers. | Consolidate shared mart-first query helpers by workflow. |
| `.overwatch_final/sections/account_health.py` | 3604 | Legacy account-health cockpit overlaps DBA Control Room. | Retain as compatibility route, move useful pieces into DBA workflows. |
| `.overwatch_final/sections/executive_landing.py` | 3470 | Advanced rollups remain in same module as front door. | Split advanced/admin rollups later if tests prove import or render pain. |
| `.overwatch_final/sections/alert_center.py` | 3432 | Active alerts, history, admin config, suppression, closed loop, and investigation evidence. | Split active workflow from admin/evidence helpers. |
| `.overwatch_final/sections/task_management.py` | 3281 | Task management and pipeline health overlap Pipeline & Task Health. | Keep as delegated implementation, remove duplicate entry points only after regression. |
| `.overwatch_final/sections/security_posture.py` | 3267 | Security overview, failed logins, grants, sprawl, sharing, admin evidence in one file. | Split advanced evidence after route behavior is stable. |
| `.overwatch_final/sections/warehouse_health.py` | 2909 | Old optimization advisor and warehouse controls overlap Cost & Contract; first split moved contracts, SQL builders, and dataframe helpers. | In progress: next split should extract render panels only after current contract tests stay green. |
| `.overwatch_final/sections/cost_contract.py` | 243 | Public Cost & Contract entrypoint after split; compatibility reexports plus `render()`. | Complete. Keep thin; do not add new implementation logic here. |
| `.overwatch_final/utils/alerts.py` | 132 | Compatibility facade only after alert split. | Keep as stable import surface; do not add new implementation logic here. |

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

1. Split `warehouse_health.py` so operator recommendations remain under Cost & Contract while low-level controls stay advanced.
2. Split `dba_tools.py` into compare tools, generated SQL, validation utilities, and settings controls.
3. Consolidate shared explicit-load gates and priority dataframe patterns.
4. Break up `shared_metrics.py` by workflow/query family only after the cost/workload callers have regression coverage.
5. Retire duplicated legacy route rendering after route metrics prove no active usage.
6. Rewrite mart loads to feed daily workflows directly before dropping any old objects.

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
| Warehouse Health split started | Reduced `.overwatch_final/sections/warehouse_health.py` from about 4108 lines to about 2909 lines by extracting stable contracts, SQL builders, pure dataframe helpers, and pure capacity decision helpers into `warehouse_health_contracts.py`, `warehouse_health_sql.py`, `warehouse_health_dataframes.py`, and `warehouse_health_helpers.py`. Rendering remains in the public shell for now. |
