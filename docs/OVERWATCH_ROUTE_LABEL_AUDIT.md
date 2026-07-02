# OVERWATCH Route and Label Audit

Date: 2026-06-22

Scope: primary app code, route aliases, Snowflake setup text, and regression tests after restoring the six-section model.

## Result

- Primary navigation remains exactly six sections: Executive Landing, DBA Control Room, Alert Center, Cost & Contract, Workload Operations, Security Monitoring.
- The abandoned four-section model is not present as primary navigation.
- Stale first-paint and advanced-pane labels were corrected where they leaked into operator UI.
- Legacy names remain only as compatibility aliases, internal object/procedure names, or historical documentation.
- Route behavior is covered by `tests/test_navigation_integrity.py::test_legacy_route_matrix_lands_on_current_workflows`.

## Fixed Labels

| File | Old label | Corrected label | Fixed | Route behavior tested |
|---|---|---|---|---|
| `.overwatch_final/sections/dba_control_room/render.py` | Fast Watch detail | Live watch detail | Yes | Yes |
| `.overwatch_final/sections/dba_control_room/render.py` | Command Center Investigations | Correlated Investigations | Yes | Yes |
| `.overwatch_final/sections/dba_control_room/render.py` | Load Command Center Investigations | Load Correlated Investigations | Yes | Yes |
| `.overwatch_final/sections/dba_control_room/handoff.py` | DBA Morning Brief | DBA Daily Brief | Yes | Yes |
| `.overwatch_final/sections/dba_control_room/handoff.py` | Morning Brief routing text | Daily Brief routing text | Yes | Yes |
| `.overwatch_final/sections/account_health.py` | DBA Morning Brief | DBA Daily Brief | Yes | Yes |
| `.overwatch_final/sections/contention_center.py` | Task graphs | Pipeline & Task Health | Yes | Yes |
| `.overwatch_final/sections/contention_center.py` | Query diagnosis | Query Investigation | Yes | Yes |
| `.overwatch_final/sections/dba_control_room/data.py` | Task graphs | Pipeline & Task Health | Yes | Yes |
| `.overwatch_final/sections/dba_control_room/data.py` | Query diagnosis | Query Investigation | Yes | Yes |
| `.overwatch_final/sections/dba_control_room/handoff.py` | Task graphs | Pipeline & Task Health | Yes | Yes |
| `.overwatch_final/sections/dba_control_room/handoff.py` | Query diagnosis | Query Investigation | Yes | Yes |
| `.overwatch_final/sections/dba_control_room/incidents.py` | Active Incidents | Active Alert Board | Yes | Yes |
| `.overwatch_final/sections/cost_center.py` | Cost by User | Cost by User / Role | Yes | Yes |
| `.overwatch_final/sections/cost_center.py` | Burn Rate | Burn Rate & Forecast | Yes | Yes |
| `.overwatch_final/sections/cost_center.py` | Forecast | Run-Rate Projection | Yes | Yes |
| `.overwatch_final/sections/cost_center.py` | Chargeback | Chargeback / Company Split | Yes | Yes |
| `.overwatch_final/sections/cortex_monitor.py` | Cost by User | Cost by User / Role | Yes | Yes |
| `.overwatch_final/sections/cost_contract.py` | Cost Command Findings | Cost Investigation Findings | Yes | Yes |
| `.overwatch_final/sections/workload_operations.py` | Workload Command Findings | Workload Investigation Findings | Yes | Yes |
| `.overwatch_final/sections/security_posture.py` | Security Command Findings | Security Investigation Findings | Yes | Yes |
| `.overwatch_final/sections/alert_center.py` | Alert Command Findings | Alert Investigation Findings | Yes | Yes |
| `.overwatch_final/sections/executive_landing.py` | Command Center | Correlated Investigations | Yes | Yes |
| `.overwatch_final/sections/query_analysis.py` | AI Query Diagnosis | Query Investigation | Yes | Yes |
| `.overwatch_final/sections/query_investigation_root_cause.py` | AI Query Diagnosis | Query Investigation | Yes | Yes |
| `.overwatch_final/utils/alerts.py` | DBA Morning Brief | DBA Daily Brief | Yes | Yes |
| `.overwatch_final/utils/recommendation_intelligence.py` | Query diagnosis / Task graphs | Query Investigation / Pipeline & Task Health | Yes | Yes |
| `.overwatch_final/utils/scorecards.py` | Query Diagnosis / task graphs | Query Investigation / Pipeline & Task Health | Yes | Yes |
| `.overwatch_final/utils/operational_intelligence.py` | Fact-Grounded AI Query Diagnosis | Fact-Grounded Query Investigation | Yes | Yes |
| `README.md` | enterprise Snowflake Command Center | enterprise Snowflake DBA operations platform | Yes | N/A |
| `snowflake/OVERWATCH_MART_SETUP.sql` | Command Center descriptive text | correlated investigation descriptive text | Yes | SQL/static tests |
| `snowflake/mart_setup/03_config_and_audit_tables.sql` | Command Center descriptive text | correlated investigation descriptive text | Yes | SQL/static tests |
| `snowflake/mart_setup/05_load_procedures.sql` | Command Center descriptive text | correlated investigation descriptive text | Yes | SQL/static tests |
| `snowflake/OVERWATCH_MART_VALIDATION.sql` | Command Center safety proof wording | correlated investigation safety proof wording | Yes | SQL/static tests |

## Compatibility-Only References Retained

These labels intentionally remain in route maps or tests so old links do not break:

| Location | Retained label | Reason |
|---|---|---|
| `.overwatch_final/config.py` | Command Center | Legacy route maps to DBA Control Room > Morning Cockpit. |
| `.overwatch_final/config.py` | Optimization | Legacy route maps to Cost & Contract > Cost Recommendations. |
| `.overwatch_final/config.py` | Fast Watch | Legacy route maps to DBA Control Room > Morning Cockpit. |
| `.overwatch_final/config.py` | Morning Brief | Legacy route maps to DBA Control Room > Morning Cockpit. |
| `.overwatch_final/sections/dba_control_room/types.py` | Operations Detail | Legacy pane maps to Action Queue. |
| `.overwatch_final/sections/workload_operations.py` | Query diagnosis | Legacy workflow alias maps to Query Investigation. |
| `.overwatch_final/sections/workload_operations.py` | Task graphs | Legacy workflow alias maps to Pipeline & Task Health. |
| `.overwatch_final/sections/alert_center.py` | Advanced Alert Admin | Legacy view maps to Alert Settings / Admin. |
| `.overwatch_final/sections/security_posture.py` | Advanced Security Diagnostics | Legacy view maps to Security Admin / Advanced. |

## Internal Object Names Retained

The `MART_COMMAND_CENTER_*`, `OVERWATCH_COMMAND_CENTER_*`, and `SP_OVERWATCH_REFRESH_COMMAND_CENTER` names remain in DDL and tests as internal compatibility objects. The visible product language now uses correlated investigations.

## Stale Chart References

No `see chart A/B/C/D` or `chart A/B/C/D` references were found in primary app code by the regression runner.
