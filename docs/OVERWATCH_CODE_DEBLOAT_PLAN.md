# OVERWATCH Code De-Bloat Plan

Date: 2026-06-22

## Goal

Reduce bloat without breaking the six-section operator model or removing useful Snowflake DBA functionality.

## Highest-Bloat Files

| File | Approx lines | Primary issue | Action |
|---|---:|---|---|
| `.overwatch_final/sections/cost_contract.py` | 5003 | Workflow shell, cost overview, value ledger, forecast, changes, savings evidence, and old delegation in one module. | Split cost workflows and advanced evidence gates after live regression is available. |
| `.overwatch_final/utils/alerts.py` | 4671 | Alert SQL catalog, rule generation, alert actions, delivery, active queue helpers, and DBA briefing helpers mixed together. | Split catalog/admin SQL from active alert queue logic. |
| `.overwatch_final/sections/warehouse_health.py` | 4108 | Old optimization advisor and warehouse controls overlap Cost & Contract. | Move operator output behind Cost & Contract > Waste Detection; keep raw controls advanced. |
| `.overwatch_final/sections/dba_tools.py` | 3861 | Admin tools, generated SQL, settings controls, compare tools, validation utilities. | Keep under Workload Operations > Advanced DBA Tools / Control Room Admin. |
| `.overwatch_final/utils/shared_metrics.py` | 3804 | Many shared SQL builders and cache wrappers. | Consolidate shared mart-first query helpers by workflow. |
| `.overwatch_final/sections/account_health.py` | 3604 | Legacy account-health cockpit overlaps DBA Control Room. | Retain as compatibility route, move useful pieces into DBA workflows. |
| `.overwatch_final/sections/executive_landing.py` | 3470 | Advanced rollups remain in same module as front door. | Split advanced/admin rollups later if tests prove import or render pain. |
| `.overwatch_final/sections/alert_center.py` | 3432 | Active alerts, history, admin config, suppression, closed loop, and investigation evidence. | Split active workflow from admin/evidence helpers. |
| `.overwatch_final/sections/task_management.py` | 3281 | Task management and pipeline health overlap Pipeline & Task Health. | Keep as delegated implementation, remove duplicate entry points only after regression. |
| `.overwatch_final/sections/security_posture.py` | 3267 | Security overview, failed logins, grants, sprawl, sharing, admin evidence in one file. | Split advanced evidence after route behavior is stable. |

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
| Large app modules above 3000 lines | 10 | 3 or fewer |
| Daily operator mart tables | 90+ expected in current setup | 28-34 after migration |
| Primary route aliases exposed to users | Several before this pass | Zero known in primary UI |
| Live Snowflake regression coverage | New runner, blocked by auth | Passing in test account |

## Tests Proving No Functionality Was Lost

- `.overwatch_final/workflow_contracts.py` now centralizes the six-section workflow contract and legacy route matrix used by both tests and the live Snowflake regression runner.
- `tests/test_navigation_integrity.py` checks the six primary sections, legacy route redirects, workflow names, old 4-section absence, company scoping, and stale chart text.
- `tests/test_command_center.py` now validates correlated investigation UI placement and explicit load gates.
- `tests/test_contention_center.py`, `tests/test_formula_regressions.py`, and `tests/test_operational_intelligence.py` validate renamed workflow/action contracts.
- `perf_tests/full_app_snowflake_regression.py` is the live Snowflake gate once authentication is corrected.

## Next Rewrite Order

1. Split `utils/alerts.py` into active queue, catalog/admin SQL, delivery/suppression, and DBA brief helpers.
2. Split `cost_contract.py` into cost overview/workflow shell and advanced evidence modules.
3. Consolidate shared explicit-load gates and priority dataframe patterns.
4. Retire duplicated legacy route rendering after route metrics prove no active usage.
5. Rewrite mart loads to feed daily workflows directly before dropping any old objects.

## De-Bloat Completed After Initial Audit

| Item | Result |
|---|---|
| Duplicated six-section workflow list in Snowflake regression runner | Replaced with `.overwatch_final/workflow_contracts.py`. |
| Duplicated legacy route matrix in navigation tests | Replaced with `.overwatch_final/workflow_contracts.py`. |
| Contract drift guard | Added a test that the workflow contract matches the configured six primary sections. |
