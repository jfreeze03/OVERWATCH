"""Lazy re-exports for shared OVERWATCH utilities.

Keep the historical ``from utils import ...`` API without importing every
utility module during startup. This matters for Streamlit reruns because the
top-level package is imported before a section knows which helpers it needs.
"""
from __future__ import annotations

from importlib import import_module


UTILS_EXPORT_VERSION = "2026-06-02-guardrails-v1"


_EXPORT_GROUPS: dict[str, tuple[str, ...]] = {
    "session": (
        "get_session", "get_session_for_action", "snowflake_connection_known_unavailable",
    ),
    "query": (
        "run_query", "run_query_cached", "run_query_or_raise", "force_refresh",
        "safe_sql", "safe_identifier", "safe_schedule", "sql_literal",
        "get_query_telemetry", "get_query_budget_summary", "clear_query_telemetry",
        "format_snowflake_error",
    ),
    "data": (
        "normalize_df", "safe_strip_tz",
    ),
    "cost": (
        "get_credit_price", "get_storage_cost_per_tb", "format_credits",
        "credits_to_dollars", "estimate_live_credits", "query_attribution_supported",
        "build_metered_credit_cte", "build_idle_warehouse_sql",
        "build_monitoring_cost_sql", "build_app_runtime_cost_sql",
        "build_cost_reconciliation_sql", "build_snowflake_cost_management_account_sql",
        "build_snowflake_billed_credit_reconciliation_sql",
        "build_snowflake_org_currency_cost_sql", "metric_confidence_label",
        "freshness_note", "CREDIT_RATES", "COMPUTE_CREDIT_CASE",
    ),
    "scorecards": (
        "clamp_score", "score_label", "bad_ratio_score", "trend_score",
        "weighted_score", "burn_trend_label", "executive_health_score",
        "service_health_scorecard", "dba_control_plane_readiness_score",
        "dba_effective_readiness_score", "dba_deployment_label",
        "dba_control_plane_section_scorecards", "dba_control_plane_component_rows",
    ),
    "owner_directory": (
        "OWNER_CONTEXT_COLUMNS", "OWNER_DIRECTORY_TABLE", "OWNER_DIRECTORY_VIEW",
        "build_owner_directory_ddl", "default_owner_directory",
        "enrich_owner_dataframe", "load_owner_directory", "owner_directory_fqn",
        "owner_directory_readiness_board", "owner_directory_view_fqn", "resolve_owner_context",
    ),
    "workload_audit": (
        "WORKLOAD_RECOVERY_AUDIT_TABLE", "build_workload_recovery_audit_ddl",
        "workload_recovery_audit_fqn",
    ),
    "cache": (
        "bump_global_cache_salt", "clear_all_cache",
    ),
    "downloads": (
        "download_csv", "show_loaded_time", "mark_loaded",
    ),
    "display": (
        "render_query_drilldown", "render_warehouse_drilldown",
        "render_drillable_bar_chart", "render_entity_query_drilldown",
        "rank_chart_frame", "render_ranked_bar_chart",
    ),
    "company_filter": (
        "get_active_company", "get_db_filter_clause", "get_wh_filter_clause",
        "get_user_filter_clause", "get_role_filter_clause",
        "get_combined_filter_clause", "get_global_date_clause",
        "get_global_wh_filter_clause", "get_global_user_filter_clause",
        "get_global_role_filter_clause", "get_global_db_filter_clause",
        "get_global_filter_clause", "get_active_environment",
        "get_environment_filter_clause", "get_environment_filter_or_no_database_clause",
        "get_environment_case_expr", "environment_label_for_database",
        "get_company_case_expr", "get_company_scope_key", "company_scoped_query",
        "company_value_allowed", "environment_value_allowed", "invalidate_company_cache",
    ),
    "helpers": (
        "paginate_df", "safe_float", "safe_int",
    ),
    "alerts": (
        "ALERT_OPEN_STATUSES", "ALERT_STATUS_CHOICES", "DEFAULT_ALERT_RECIPIENT",
        "acknowledge_alert_escalation", "alert_rule_catalog",
        "alert_delivery_log_fqn", "alert_escalation_candidates",
        "alert_history_to_actions", "alert_severity_rank", "alert_table_fqn",
        "alert_triage_view_fqn", "annotate_alert_triage_frame",
        "build_alert_digest_body", "build_alert_digest_subject",
        "build_alert_digest_summary", "build_alert_email_delivery_procedure_sql",
        "build_alert_email_body", "build_alert_email_subject",
        "build_alert_rule_audit_ddl", "build_alert_rule_audit_insert_sql",
        "build_alert_delivery_log_ddl", "build_alert_delivery_log_insert_sql",
        "build_alert_delivery_mark_sql", "build_alert_escalation_ack_sql",
        "build_alert_insert_sql", "build_alert_status_update_sql",
        "build_alert_triage_view_sql",
        "build_dashboard_issue_rows", "build_alert_rule_update_sql",
        "load_alert_delivery_log", "load_alert_history", "load_alert_rule_audit",
        "load_alert_rule_catalog", "log_alert_digest_delivery",
        "mark_alerts_routed", "normalize_alert_frame", "normalize_alert_rule_frame",
        "send_teams_alert", "update_alert_rule", "update_alert_status",
    ),
    "logging": (
        "log_section_load", "set_logging_enabled", "is_logging_enabled",
        "log_query_event", "is_query_logging_enabled", "set_query_logging_enabled",
        "SectionTimer",
    ),
    "admin": (
        "admin_actions_default_enabled", "admin_actions_enabled",
        "admin_button_disabled", "admin_disabled_reason",
        "initialize_admin_actions_default", "render_admin_mode_control", "require_admin_enabled",
        "clamp_global_date_range",
        "build_admin_audit_insert_sql", "log_admin_action",
    ),
    "metadata": (
        "show_to_df", "clear_show_statement_cache", "first_existing_column",
        "ensure_column_alias", "scope_warehouse_names", "scope_metadata_df",
        "load_task_inventory", "load_warehouse_inventory", "build_unclassified_assets_sql",
    ),
    "futures_governance": (
        "PLATFORM_FUTURES_CONTROL_TABLE", "PLATFORM_FUTURES_EVIDENCE_TABLE",
        "PLATFORM_FUTURES_LATEST_VIEW", "PLATFORM_FUTURES_COVERAGE_VIEW",
        "AGENTIC_AI_CONTROL_AREAS",
        "build_platform_futures_evidence_ddl",
        "build_forward_platform_control_register", "build_platform_futures_adoption_gate",
        "build_agentic_ai_surface_scorecard",
        "build_platform_futures_board",
        "classify_adaptive_compute_readiness", "load_adaptive_compute_readiness",
        "load_agent_mcp_inventory", "load_ai_usage_guardrails",
        "classify_ai_security_guardrails", "load_ai_security_guardrails",
        "load_horizon_semantic_readiness", "load_openflow_operations",
    ),
    "mart": (
        "MartResult", "mart_object_name", "load_mart_table",
        "load_latest_control_room_mart", "mart_source_caption",
        "build_mart_control_room_summary_sql", "build_mart_control_room_credits_sql",
        "build_mart_control_room_cost_drivers_sql",
        "build_mart_control_room_warehouse_pressure_sql",
        "build_mart_control_room_failed_queries_sql",
        "build_mart_control_room_object_changes_sql",
        "build_mart_control_room_failed_logins_sql",
        "build_mart_control_room_task_failures_sql",
        "build_mart_account_health_storage_sql",
        "build_mart_account_health_cost_drivers_sql",
        "build_mart_account_health_change_sql",
        "build_mart_account_health_failure_types_sql",
        "build_mart_account_health_long_queries_sql",
        "build_mart_account_health_credits_sql",
        "build_mart_account_health_failure_count_sql",
        "build_mart_account_health_top_driver_sql",
        "build_mart_account_health_queued_sql",
        "build_mart_account_health_ytd_credits_sql",
        "build_mart_bill_summary_sql", "build_mart_bill_warehouse_delta_sql",
        "build_mart_chargeback_sql", "build_mart_cost_explorer_sql",
        "build_mart_cost_cockpit_sql",
        "build_mart_cost_run_rate_sql",
        "build_mart_warehouse_overview_sql", "build_mart_warehouse_scaling_sql",
        "build_mart_usage_overview_sql", "build_mart_usage_metering_sql",
        "build_mart_usage_pressure_sql", "build_mart_usage_cost_drivers_sql",
        "build_mart_usage_storage_sql",
        "build_mart_usage_query_mix_sql", "build_mart_usage_database_adoption_sql",
        "build_mart_adoption_summary_sql", "build_mart_adoption_warehouse_size_sql",
        "build_mart_adoption_trend_sql", "build_mart_adoption_users_wh_sql",
        "build_mart_adoption_users_db_sql", "build_mart_adoption_role_type_sql",
        "build_mart_storage_trend_sql", "build_mart_storage_db_detail_sql",
        "build_mart_warehouse_heatmap_sql",
        "build_mart_pipeline_freshness_sql", "build_mart_pipeline_load_failures_sql",
        "build_mart_pipeline_volume_sql", "build_mart_recommendation_idle_sql",
        "build_mart_recommendation_spill_sql", "build_mart_recommendation_failed_tasks_sql",
        "build_mart_recommendation_query_errors_sql", "build_mart_query_bottleneck_sql",
        "build_mart_query_degradation_sql", "build_mart_task_inventory_sql",
        "build_mart_task_history_sql", "build_mart_task_critical_path_sql",
        "build_mart_query_detail_recent_sql", "build_mart_procedure_inventory_sql",
        "build_mart_procedure_calls_sql", "build_mart_procedure_sla_sql",
        "build_mart_service_query_health_sql", "build_mart_service_warehouse_health_sql",
        "build_mart_service_login_health_sql", "build_mart_service_task_health_sql",
    ),
    "bookmarks": (
        "save_bookmark", "load_bookmarks", "apply_bookmark", "delete_bookmark",
    ),
    "action_queue": (
        "make_action_id", "upsert_actions", "load_action_queue", "update_action_status",
        "action_queue_environment_clause", "action_queue_environment_values",
        "action_queue_fixed_missing_fields", "update_action_status_with_evidence",
        "action_queue_default_due_days", "enrich_action_queue_view",
        "build_safe_verification_query", "summarize_verification_frame",
        "verification_query_safety_issues", "build_cost_savings_verification_sql",
        "build_cost_savings_verification_health_sql",
    ),
    "workflows": (
        "coerce_workflow_state", "render_workflow_selector", "render_workflow_guide",
        "render_signal_confidence", "add_signal_routes", "render_priority_dataframe",
        "migrate_legacy_workflow_state", "render_workflow_module",
    ),
    "section_guidance": (
        "defer_section_note", "defer_source_note",
    ),
    "compatibility": (
        "run_compatibility_checks", "get_available_columns", "view_supports_columns",
        "filter_existing_columns", "build_smoke_test_checklist",
        "build_cost_formula_audit", "build_task_history_sql",
        "build_task_failure_summary_sql", "build_task_health_sql",
    ),
    "optimization_advisor": (
        "render_optimization_advisor",
    ),
    "recommendation_intelligence": (
        "duplicate_query_decision", "harden_recommendation",
        "harden_recommendation_rows", "warehouse_sizing_decision",
    ),
    "ask_overwatch": (
        "answer_ask_overwatch", "build_ask_overwatch_context",
        "build_grounded_cortex_prompt", "snapshot_ask_overwatch_state",
    ),
}

_EXPORT_MODULES = {
    name: module
    for module, names in _EXPORT_GROUPS.items()
    for name in names
}

__all__ = tuple(_EXPORT_MODULES)


def __getattr__(name: str):
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
