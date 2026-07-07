# Mart First-Paint State Audit

Generated for the first-paint placeholder cleanup. Scope: primary mart-backed OVERWATCH sections and shared renderers.

## Search Terms

`Refresh required`, `Loading`, `Details available when needed`, `Current summary unavailable`, `Source unavailable`, `Unavailable`, `Open Details`, `Load Full Evidence`, `Open Cost Drivers`, `Open Security Details`, `Refresh Summary`, `Details available when needed`, `Details load on request`, `command brief needs`, `unavailable_headline`, `unavailable_summary`, `detail_cta`.

## User-Facing Findings

| Area | Files | Fallback Appears Because | Decision |
| --- | --- | --- | --- |
| Shared CommandBrief fallback | `.overwatch_final/sections/section_command_brief.py`, `.overwatch_final/sections/decision_workspace_view_model.py`, `.overwatch_final/sections/section_command_rendering.py` | Missing current packet row, offline session, or fallback brief | Replace generic final `Loading`/`Refresh required` with shared data-state labels. |
| Executive COCO first viewport | `.overwatch_final/sections/command_center_models.py`, `.overwatch_final/sections/command_center_components.py`, `.overwatch_final/sections/executive_command_center_view.py` | Summary packet lacks trend/warehouse rows or source freshness | Replace with `Refresh required`, `No rows for selected scope`, or `Snowflake connection unavailable`; make link-looking controls real buttons. |
| Cost Intelligence evidence CTA | `.overwatch_final/sections/cost_contract.py`, `config/decision_brief_contracts.json`, `.overwatch_final/sections/first_paint_contracts.py` | Detail evidence is explicit-click only | Rename `Open Cost Drivers` to `Open Cost Drivers`. |
| Security Monitoring evidence CTA | `.overwatch_final/sections/security_posture.py`, `config/decision_brief_contracts.json`, `.overwatch_final/sections/first_paint_contracts.py` | Detail evidence is explicit-click only | Rename `Open Security Details` to `Open Security Details`. |
| Workload Operations CTA | `config/decision_brief_contracts.json`, `.overwatch_final/sections/first_paint_contracts.py` | Specialist views are explicit-click only | Rename `Open the right tool` to `Open specialist workflow`. |
| Deep detail loaders | `cortex_monitor.py`, `dba_control_room/render.py`, `pipeline_health.py`, `query_analysis.py`, other specialist modules | Transient spinner while explicit click query is actively running | Keep only as transient `st.status`/spinner text, not as final first-paint content. |
| Admin/setup health | `.overwatch_final/sections/decision_workspace_setup_health.py`, docs, validation SQL | Technical setup details intentionally admin-only | Allowed in Settings/Admin Setup Health only. |
| SQL procedure text | `snowflake/**` | Stored procedure generated values and validation states | Not daily UI; tracked by validation SQL and release gates. |
| Tests/docs asserting legacy labels | `tests/**`, `docs/**` | Historical guardrails or removal tests | Update when they assert production UI copy; allow only when documenting migration/removal. |

## State Model

Shared model: `.overwatch_final/utils/data_state.py`.

Primary states:

- `LOADED_CURRENT`: render metrics normally.
- `LOADED_STALE`: render latest available metrics with stale state.
- `NO_ROWS_FOR_SCOPE`: render empty/zero scope state without saying pending.
- `SOURCE_NOT_CONFIGURED`: setup required.
- `REFRESH_NOT_RUN`: mart exists but no current rows.
- `CONNECTION_UNAVAILABLE`: Snowflake session unavailable.
- `QUERY_FAILED`: compact safe error state.

## Remaining Allowed Terms

- `Loading ...` is allowed only in transient explicit-click loaders such as `with render_load_status(...)`, `st.status(...)`, or query spinners.
- `Unavailable` may remain in SQL/admin artifacts where it is a machine state, not daily first-paint copy.
- Legacy phrases may appear in tests that assert removal or in this audit document.
