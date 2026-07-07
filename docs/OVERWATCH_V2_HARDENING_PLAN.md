# OVERWATCH v2 Hardening Plan

This audit records the product-path contract for `overwatch_app/`. The legacy
`.overwatch_final/` tree remains fallback only.

## Current v2 Section List

| Section | Visible workflows |
| --- | --- |
| Executive Landing | Overview |
| Cost Intelligence | Overview; Chargeback / Showback |
| Alert Center | Active Alerts |
| DBA Control Room | Morning Cockpit; Live Mode |
| Workload Operations | Overview |
| Security Monitoring | Overview |

## Implemented Workflows

All visible workflows in `overwatch_app.registry.SECTIONS` have a unique render
function in `overwatch_app.sections.*`. There are no visible query-param-only
workflows.

## Registered But Unimplemented Workflows

None. Unimplemented workflows are not registered or visible in v2.

## Rendered Metrics

Rendered metrics live in `overwatch_app.metrics.RENDERED_METRICS` and are used
by section view models: executive score decomposition, contract burn-down,
forecast budget/bounds, top cost drivers, alert inbox/detail, live DBA mode,
workload reliability/anomalies, security heuristics, and OVERWATCH self-cost.

## Registered But Unrendered Metrics

None in v2. `REGISTERED_METRICS` aliases `RENDERED_METRICS`.

## First-Paint Data Sources

First paint uses stable app-facing views over task-loaded mart tables:

`V_EXECUTIVE_SUMMARY`, `V_DBA_MORNING_COCKPIT`, `V_SOURCE_FRESHNESS`,
`V_ALERT_INTELLIGENCE`, `V_TASK_STATUS_DAILY`,
`V_WAREHOUSE_DAILY_CREDITS`, `V_COST_FORECAST`, `V_CONTRACT_BURN_DOWN`,
`V_LOGIN_SECURITY_DAILY`, `V_QUERY_ERROR_SUMMARY`, `V_STORAGE_DAILY`,
`V_CORTEX_CODE_USAGE_DAILY`, `V_COST_ALLOCATION_DAILY`, and
`V_OVERWATCH_APP_SELF_COST_DAILY`.

## First-Paint Views That Aggregate At Query Time

None in v2. Each required view is a direct select from a `MART_V2_*` table.
`snowflake/validation/validate_v2_first_paint_marts.sql` checks view
definitions for raw first-paint source leaks and the alert-intelligence
correlated-subquery pattern.

## Repository Calls Missing `st.cache_data`

None in v2. Every repository first-paint function in
`overwatch_app/data/repositories/` is decorated with `st.cache_data(ttl=300)`
through `cached_first_paint`, with cache scope including company,
environment, window, warehouse, workflow, role, and source version.

## Admin/Live/Drill-Through Surfaces Lacking RBAC

Fixed in v2 through `overwatch_app/security/rbac.py`. RBAC derives from
Snowflake/session role context or secure configuration, not a Settings
checkbox. Restricted denials are audit logged.

## Alert Center Actions Missing Write Capability

Fixed in v2 through `overwatch_app/data/alert_actions.py`. The supported
actions are acknowledge, in progress, resolve, suppress, reopen, add note, and
link ticket/change ID through state/history tables and audit logging.

## Dead UI Components

The v2 package does not define `detail_action`, `DETAIL_ACTION_LABELS`,
`action_card_html`, `severity_badge_html`, or `donut_chart`.

## Legacy Surfaces Still Visible Or Imported

`streamlit_app.py` now starts `overwatch_app.app` when present. The
`.overwatch_final/` app is retained as fallback for legacy deployment paths.

## Tests That Grade Docs Instead Of Behavior

New v2 tests exercise code behavior: repository caching, RBAC, audit SQL,
first-paint mart/view contracts, workflow renderers, executive/cost/alert/DBA
models, security heuristics, timezone handling, and absence of dead components.
