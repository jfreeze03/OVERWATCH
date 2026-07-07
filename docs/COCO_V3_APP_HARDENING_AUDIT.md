# COCO v3 App Hardening Audit

Generated for the COCO v3 hardening sprint. This audit records the first-pass
findings before and during the data-state/summary-loader cleanup.

## Scope

Reviewed active app code, tests, docs, and Snowflake setup files for:

- First-paint placeholder copy.
- Forecast buttons/gating.
- Owner-routing remnants.
- Alert Center Kanban/lane defaults.
- Summary-mart access and fallback behavior.
- Cost Intelligence progressive-disclosure/confidence gaps.
- Active DDL deployment path.

## Active DDL Deployment Path

Confirmed active setup remains the seven-file path:

- `snowflake/mart_setup/01_runtime_objects.sql`
- `snowflake/mart_setup/02_roles_and_grants.sql`
- `snowflake/mart_setup/03_config_and_audit_tables.sql`
- `snowflake/mart_setup/04_mart_tables.sql`
- `snowflake/mart_setup/05_load_procedures.sql`
- `snowflake/mart_setup/06_alert_framework.sql`
- `snowflake/mart_setup/07_tasks.sql`

Validation SQL remains outside active setup under `snowflake/validation/`.
Reset/drop remains `snowflake/OVERWATCH_MART_DROP.sql`.

## Findings

| Area | Status | Classification | Notes |
| --- | --- | --- | --- |
| Summary loader fallback row says pending | Fixed now | fix now | `.overwatch_final/sections/summary_mart_loaders.py` now returns explicit `SummaryResult` data states and no final `pending` fallback row. |
| Summary loader spinner says loading summary | Fixed now | rename | Spinner now says `Reading compact summary...`; final fallback states are explicit. |
| Forecast buttons gate core forecast output | Fixed now | fix now | Forecast/burn views were changed to autoload deterministic forecast/burn calculations without `Open Run-Rate Projection`, `Open Annual Service Projection`, or `Load Burn Rate & Forecast` buttons. |
| First-paint placeholders in active app source | Fixed now | fix now | `utils.data_state` now defines canonical states, packet parsing maps generic placeholders to explicit states, and the active `.overwatch_final` placeholder search is clean. Historical docs/tests still keep audit assertions. |
| Executive command-center summary data | Partially fixed | fix now | Executive Landing now reads compact warehouse summary through `get_cost_summary()` and consumes the `SummaryResult` frame. Other primary sections still need equivalent wiring. |
| Owner-routing terms in active app | Blocker | delete | Active modules still reference workflow route/source/evidence/approval/review fields. These should be replaced by section/workflow/status/verification terminology. |
| Owner-routing objects in active DDL | Blocker | delete | `03_config_and_audit_tables.sql` and `04_mart_tables.sql` still create or alter owner-routing tables/columns. Allowed only in migration/drop/validation files. |
| Owner-routing removal migration/drop | Allowed | migration/drop/validation only | `snowflake/migrations/2026_07_remove_owner_routing.sql` and drop/reset scripts may reference retired objects to remove them. |
| Alert Kanban/lane source markers | Follow-up | delete/rename | Search hits are in docs/tests; active Alert Center source still needs default inbox proof and cleanup scans. |
| Raw `SNOWFLAKE.ACCOUNT_USAGE` in app source | Follow-up | make admin-only | Many hits are live drill-through/setup/admin utilities. First-paint paths and default UI/export must continue to route through compact marts or explicit actions only. |
| Cost Intelligence confidence model | Follow-up | fix now | Current cost intelligence still needs a structured confidence-scored finding model and safer non-causal language. |
| Evidence-first wording | Follow-up | rename | Remaining first-paint/detail labels should use Details, Telemetry, Verification, Source Freshness, or Closure Status instead of evidence-first language. |
| Config/PII primary source | Follow-up | move to governed settings | Company/warehouse/config lists should be governed by settings with source-code placeholders only as fallback. |

## Required Search Results

The hardening searches were run during this pass.

- Placeholder/evidence/forecast search: first pass found 156 hits; second pass reduced this to 78 hits; current active-app pass now uses current/refresh-required data-state wording and explicit detail labels. Remaining repository hits are historical docs/tests and are not runtime render paths.
- Owner-routing search: remaining active app and active DDL hits are not allowed except migration/drop/validation references.
- Kanban/lane search: remaining docs/tests references are allowed as review context; active default route should remain Alert Inbox.
- `SNOWFLAKE.ACCOUNT_USAGE` search: many hits remain. Allowed only behind explicit detail/admin/live-validation boundaries; not allowed for primary first paint or default exports.

## Next Burn-Down Order

1. Remove owner-routing objects from active setup DDL, leaving only migration/drop/validation coverage.
2. Replace active app owner-routing labels/columns with workflow/status/verification terminology.
3. Wire all six primary sections through `SummaryResult` wrappers so first paint has explicit state and cached summary content.
4. Finish Cost Intelligence confidence scoring and non-causal copy.
5. Re-run full unit discovery and release sweeps after the active DDL cleanup.
