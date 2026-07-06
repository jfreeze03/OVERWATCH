# COCO V3 Hardening Audit

Date: 2026-07-06
Baseline: `aafa36805e0db33fe12a524db3804c188b5d2fdb`

## Forecast Buttons

Found button-gated forecast paths in:

- `.overwatch_final/sections/cost_center_forecast_view.py`: `Open Run-Rate Projection`, `Open Annual Service Projection`.
- `.overwatch_final/sections/cost_center_burn_view.py`: `Load Burn Rate & Forecast`.
- `.overwatch_final/sections/dba_control_room/render.py`: `Load Forecast Exceptions`, retained as DBA investigation detail, not a Cost first-paint forecast.

This pass removes the Cost first-paint forecast button gates and changes those views to scope-keyed summary autoload with deterministic forecast method, confidence, and upper/lower bounds.

## First-Paint Blockers

Found first-paint blocker language across shared CommandBrief, Executive COCO cards, Cost, Security, Alert, DBA, and legacy utility modules:

- `Refresh required`, `Current summary unavailable`, `Loading`, `Details available when needed`, `On request`.
- `Details available when needed`, `Open Cost Drivers`, `Open Security Details`.

Shared data-state helpers now map generic final placeholders to governed labels:

- `Refresh required`
- `No rows for selected scope`
- `Setup required`
- `Snowflake connection unavailable`
- `Query failed`

The summary mart fallback row now emits `Refresh required`, not `pending`. Executive Landing receives compact warehouse summary rows through the shared summary boundary before rendering the command-center model.

## Direct Account Usage Usage

Direct `SNOWFLAKE.ACCOUNT_USAGE` references still exist in refresh SQL, validation SQL, tests, docs, and bounded detail/drill-through helpers. They are not allowed in first-paint summary loaders or daily UI labels.

The active first-paint summary loader uses app-facing views, including:

- `V_WAREHOUSE_DAILY_CREDITS`
- `V_QUERY_DAILY_SUMMARY`
- `V_CORTEX_DAILY_USAGE`
- `V_LOGIN_SECURITY_DAILY`
- `V_TASK_STATUS_DAILY`
- `V_SECURITY_POSTURE_DAILY`
- `V_EXECUTIVE_PACKET_CURRENT`

## Cost Intelligence Structure

`cost_contract_intelligence.py` remains the core Cost Intelligence analysis module. It currently owns:

- source health and coverage boards
- cost decomposition
- spike/root-cause boards
- change/cost correlation
- drilldown command maps

Correlation output should be represented as scored findings with concise explanation first, confidence score/label, matched signals, caveats, and drill-through detail rows. Existing tests cover portions of the module but need more confidence-scoring coverage.

## Old / Retired Concepts

Active app searches still show retired wording in tests, docs, and some legacy utility modules:

- owner routing / owner approval / cost owner terminology
- theme picker / terminal theme
- evidence-first labels
- old route aliases

Production renderers must not surface these concepts in daily UI. Remaining hits are tracked for delete-first cleanup unless they are tests asserting removal or migration documentation.

## DDL Path

Active deployment path remains the seven-file mart setup path:

1. `snowflake/mart_setup/01_runtime_objects.sql`
2. `snowflake/mart_setup/02_roles_and_grants.sql`
3. `snowflake/mart_setup/03_config_and_audit_tables.sql`
4. `snowflake/mart_setup/04_mart_tables.sql`
5. `snowflake/mart_setup/05_load_procedures.sql`
6. `snowflake/mart_setup/06_alert_framework.sql`
7. `snowflake/mart_setup/07_tasks.sql`

Validation SQL remains outside active deployment under `snowflake/validation/`. The monolith remains generated from the active manifest and must stay equivalent to the seven active setup files.
