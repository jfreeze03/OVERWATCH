# First-Paint Account Usage Audit

Scope: every `.overwatch_final` file containing `SNOWFLAKE.ACCOUNT_USAGE`. Each row classifies every hit in that file.

Rule: first-paint renderers and summary loaders must not reference raw Account Usage. Explicit drill-through, admin proof, exact query search, live DBA tools, and compatibility probes may reference it when bounded or user initiated.

## Blocked Classes

| Class | Result | Evidence |
| --- | --- | --- |
| first-paint renderer | PASS: no raw references found in first-paint contract modules | `tests/test_first_paint_account_usage_audit.py` |
| summary loader | PASS: no raw references found in `.overwatch_final/sections/summary_mart_loaders.py` | `tests/test_first_paint_account_usage_audit.py` |
| unknown | PASS: no unclassified app files remain in this audit | `tests/test_first_paint_account_usage_audit.py` |

## Allowed File Classifications

| File | Classification | Result | Reason |
| --- | --- | --- | --- |
| `.overwatch_final/query_contracts.py` | setup/admin proof | ALLOWED | Query-boundary guard inspects tokens; it does not run the source. |
| `.overwatch_final/utils/alert_action_queue.py` | bounded drill-through | ALLOWED | Builds proof queries for queued alert actions. |
| `.overwatch_final/utils/alert_command_center.py` | setup/admin proof | ALLOWED | Alert catalog/setup SQL and reviewed detection definitions. |
| `.overwatch_final/utils/alert_native_catalog.py` | setup/admin proof | ALLOWED | Native alert policy templates and verification snippets. |
| `.overwatch_final/utils/billing_reconciliation.py` | bounded drill-through | ALLOWED | Explicit billing reconciliation evidence. |
| `.overwatch_final/sections/contention_center.py` | live current-state DBA/Panic Mode | ALLOWED | Contention and lock investigation tooling. |
| `.overwatch_final/sections/cortex_monitor.py` | bounded drill-through | ALLOWED | Explicit Cortex usage evidence and admin analysis. |
| `.overwatch_final/utils/company_filter.py` | setup/admin proof | ALLOWED | Role/scope capability probes. |
| `.overwatch_final/sections/cost_center_attribution_view.py` | bounded drill-through | ALLOWED | Explicit attribution drill-through. |
| `.overwatch_final/utils/compatibility.py` | setup/admin proof | ALLOWED | Source capability and compatibility metadata. |
| `.overwatch_final/sections/cost_center_chargeback_view.py` | bounded drill-through | ALLOWED | Explicit chargeback evidence. |
| `.overwatch_final/utils/cost.py` | bounded drill-through | ALLOWED | Cost detail helpers used behind cost evidence flows. |
| `.overwatch_final/sections/cost_center_explain_view.py` | bounded drill-through | ALLOWED | Explicit cost explanation drill-through. |
| `.overwatch_final/utils/cost_formula_authority.py` | setup/admin proof | ALLOWED | Formula provenance metadata and source labels. |
| `.overwatch_final/sections/cost_center_sql.py` | bounded drill-through | ALLOWED | SQL builders for explicit cost detail. |
| `.overwatch_final/utils/display.py` | bounded drill-through | ALLOWED | Query display helpers and sampled evidence. |
| `.overwatch_final/sections/cost_center_user_leaderboard_view.py` | bounded drill-through | ALLOWED | Explicit user leaderboard evidence. |
| `.overwatch_final/utils/incident_correlation.py` | bounded drill-through | ALLOWED | Incident correlation detail helpers. |
| `.overwatch_final/sections/cost_contract_intelligence.py` | bounded drill-through | ALLOWED | Source label and explicit cost-driver context. |
| `.overwatch_final/sections/cost_contract_loader.py` | bounded drill-through | ALLOWED | Cost cockpit fallback labels after explicit load paths. |
| `.overwatch_final/sections/cost_contract_overview_floor.py` | bounded drill-through | ALLOWED | Source note only; detailed data is loaded elsewhere. |
| `.overwatch_final/sections/cost_contract_sql.py` | bounded drill-through | ALLOWED | SQL builders for explicit cost/Cortex evidence. |
| `.overwatch_final/sections/data_sharing.py` | bounded drill-through | ALLOWED | Explicit data-sharing investigation. |
| `.overwatch_final/utils/metadata.py` | setup/admin proof | ALLOWED | Metadata and source availability helpers. |
| `.overwatch_final/sections/dba_tools_cortex_limits_view.py` | live current-state DBA/Panic Mode | ALLOWED | DBA tool for current Cortex usage. |
| `.overwatch_final/sections/dba_control_room/data.py` | live current-state DBA/Panic Mode | ALLOWED | DBA Control Room investigation loaders. |
| `.overwatch_final/utils/native_snowflake.py` | setup/admin proof | ALLOWED | Native Snowflake capability probes. |
| `.overwatch_final/sections/dba_tools_cost_health_view.py` | live current-state DBA/Panic Mode | ALLOWED | DBA cost-health tool. |
| `.overwatch_final/utils/operational_intelligence.py` | bounded drill-through | ALLOWED | Operational detail SQL helpers. |
| `.overwatch_final/sections/dba_tools_data_compare.py` | live current-state DBA/Panic Mode | ALLOWED | DBA data compare tool. |
| `.overwatch_final/sections/dba_control_room/incidents.py` | live current-state DBA/Panic Mode | ALLOWED | Incident playbook context. |
| `.overwatch_final/sections/dba_tools_data_movement_view.py` | live current-state DBA/Panic Mode | ALLOWED | DBA data movement tool. |
| `.overwatch_final/utils/predictive_sla.py` | bounded drill-through | ALLOWED | SLA prediction detail helpers. |
| `.overwatch_final/sections/dba_tools_object_monitoring_view.py` | live current-state DBA/Panic Mode | ALLOWED | DBA object monitoring tool. |
| `.overwatch_final/sections/dba_tools_qas_monitor_view.py` | live current-state DBA/Panic Mode | ALLOWED | DBA QAS monitor. |
| `.overwatch_final/sections/dba_tools_query_kill_view.py` | live current-state DBA/Panic Mode | ALLOWED | DBA query-kill workflow. |
| `.overwatch_final/sections/dba_tools_schema_compare.py` | live current-state DBA/Panic Mode | ALLOWED | DBA schema compare tool. |
| `.overwatch_final/utils/query.py` | setup/admin proof | ALLOWED | Central query facade and source guardrails. |
| `.overwatch_final/sections/dba_tools_task_graph_control.py` | live current-state DBA/Panic Mode | ALLOWED | DBA task graph control. |
| `.overwatch_final/sections/dba_tools_warehouse_settings.py` | live current-state DBA/Panic Mode | ALLOWED | DBA warehouse settings review. |
| `.overwatch_final/utils/shared_metrics_procedures.py` | bounded drill-through | ALLOWED | Procedure detail metrics. |
| `.overwatch_final/utils/shared_metrics_query.py` | bounded drill-through | ALLOWED | Query detail metrics. |
| `.overwatch_final/utils/shared_metrics_recommendations.py` | bounded drill-through | ALLOWED | Recommendation detail metrics. |
| `.overwatch_final/utils/shared_metrics_security.py` | bounded drill-through | ALLOWED | Security detail metrics. |
| `.overwatch_final/utils/shared_metrics_service_cost.py` | bounded drill-through | ALLOWED | Service-cost detail metrics. |
| `.overwatch_final/utils/shared_metrics_service_health.py` | bounded drill-through | ALLOWED | Service-health detail metrics. |
| `.overwatch_final/utils/shared_metrics_storage.py` | bounded drill-through | ALLOWED | Storage detail metrics. |
| `.overwatch_final/sections/detailed_diagnosis.py` | bounded drill-through | ALLOWED | Explicit detailed diagnosis. |
| `.overwatch_final/utils/shared_metrics_tasks.py` | bounded drill-through | ALLOWED | Task detail metrics. |
| `.overwatch_final/utils/shared_metrics_usage.py` | bounded drill-through | ALLOWED | Usage detail metrics. |
| `.overwatch_final/utils/shared_metrics_warehouse.py` | bounded drill-through | ALLOWED | Warehouse detail metrics. |
| `.overwatch_final/sections/pipeline_health.py` | bounded drill-through | ALLOWED | Pipeline detail views behind workflow interaction. |
| `.overwatch_final/sections/query_analysis.py` | exact query search | ALLOWED | Query analysis and history search workflow. |
| `.overwatch_final/sections/query_investigation_root_cause.py` | exact query search | ALLOWED | Query root-cause drill-through. |
| `.overwatch_final/sections/query_search.py` | exact query search | ALLOWED | Explicit query search. |
| `.overwatch_final/sections/recommendations.py` | bounded drill-through | ALLOWED | Recommendation generation/evidence workflow. |
| `.overwatch_final/sections/security_access.py` | bounded drill-through | ALLOWED | Security detail workflow. |
| `.overwatch_final/sections/security_posture_access_review.py` | bounded drill-through | ALLOWED | Access review proof queries. |
| `.overwatch_final/sections/security_posture_action_queue.py` | bounded drill-through | ALLOWED | Security action queue proof queries. |
| `.overwatch_final/sections/security_posture_data.py` | bounded drill-through | ALLOWED | Security data fallback labels. |
| `.overwatch_final/sections/security_posture_overview_view.py` | bounded drill-through | ALLOWED | Security overview source notes for loaded detail. |
| `.overwatch_final/sections/service_health.py` | live current-state DBA/Panic Mode | ALLOWED | Service-health diagnostic source labels. |
| `.overwatch_final/sections/spcs_tracker.py` | live current-state DBA/Panic Mode | ALLOWED | Snowpark container service tracker. |
| `.overwatch_final/sections/storage_monitor.py` | bounded drill-through | ALLOWED | Storage detail workflow. |
| `.overwatch_final/sections/stored_proc_tracker.py` | bounded drill-through | ALLOWED | Stored procedure detail workflow. |
| `.overwatch_final/sections/task_management_job_status_view.py` | bounded drill-through | ALLOWED | Task job status detail. |
| `.overwatch_final/sections/task_management_sql.py` | bounded drill-through | ALLOWED | Task detail SQL builders. |
| `.overwatch_final/sections/warehouse_health_capacity.py` | bounded drill-through | ALLOWED | Warehouse capacity detail. |
| `.overwatch_final/sections/warehouse_health_sql.py` | bounded drill-through | ALLOWED | Warehouse health SQL builders. |
| `.overwatch_final/sections/warehouse_health_view_overview.py` | bounded drill-through | ALLOWED | Warehouse overview source notes after workflow load. |
| `.overwatch_final/sections/warehouse_health_view_spill.py` | bounded drill-through | ALLOWED | Warehouse spill detail. |

## Contract

`tests/test_first_paint_account_usage_audit.py` enforces:

- every `.overwatch_final` raw Account Usage file appears above;
- first-paint modules do not contain `SNOWFLAKE.ACCOUNT_USAGE`;
- summary loaders do not contain `SNOWFLAKE.ACCOUNT_USAGE`;
- summary/Command Brief entry paths reference app-facing marts/views.
