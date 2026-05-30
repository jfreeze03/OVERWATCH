# utils/__init__.py — re-exports all shared utilities
from .session import get_session
from .query import (
    run_query, run_query_cached, run_query_or_raise, force_refresh,
    safe_sql, safe_identifier, safe_schedule, sql_literal,
    get_query_telemetry, get_query_budget_summary, clear_query_telemetry, format_snowflake_error,
)
from .data import normalize_df, safe_strip_tz
from .cost import (
    format_credits, credits_to_dollars, estimate_live_credits,
    build_metered_credit_cte, build_idle_warehouse_sql,
    build_monitoring_cost_sql, build_app_runtime_cost_sql, build_cost_reconciliation_sql,
    metric_confidence_label,
    freshness_note, CREDIT_RATES, COMPUTE_CREDIT_CASE
)
from .scorecards import (
    clamp_score, score_label, bad_ratio_score, trend_score, weighted_score,
    burn_trend_label, executive_health_score, service_health_scorecard,
)
from .display import (
    download_csv, show_loaded_time, mark_loaded, clear_all_cache,
    render_query_drilldown, render_warehouse_drilldown,
    render_drillable_bar_chart, render_entity_query_drilldown,
)
from .company_filter import (
    get_active_company, get_db_filter_clause, get_wh_filter_clause,
    get_user_filter_clause, get_role_filter_clause, get_combined_filter_clause,
    get_global_date_clause, get_global_wh_filter_clause,
    get_global_user_filter_clause, get_global_role_filter_clause,
    get_global_db_filter_clause, get_global_filter_clause,
    get_company_case_expr, get_company_scope_key, company_scoped_query, company_value_allowed,
    invalidate_company_cache,
)
from .helpers import paginate_df, safe_float, safe_int
from .alerts import send_teams_alert
from .logging import (
    log_section_load, set_logging_enabled,
    is_logging_enabled, log_query_event, is_query_logging_enabled,
    set_query_logging_enabled, SectionTimer,
)
from .admin import (
    admin_actions_enabled, admin_button_disabled, admin_disabled_reason,
    render_admin_mode_control, require_admin_enabled,
)
from .metadata import (
    show_to_df, first_existing_column, ensure_column_alias,
    scope_warehouse_names, scope_metadata_df, load_task_inventory,
    load_warehouse_inventory, build_unclassified_assets_sql,
)
from .mart import (
    MartResult, mart_object_name, load_mart_table,
    load_latest_control_room_mart, mart_source_caption,
    build_mart_control_room_summary_sql, build_mart_control_room_credits_sql,
    build_mart_control_room_cost_drivers_sql, build_mart_control_room_warehouse_pressure_sql,
    build_mart_control_room_failed_queries_sql, build_mart_control_room_object_changes_sql,
    build_mart_control_room_failed_logins_sql, build_mart_control_room_task_failures_sql,
    build_mart_account_health_storage_sql, build_mart_account_health_cost_drivers_sql,
    build_mart_account_health_change_sql,
    build_mart_account_health_failure_types_sql, build_mart_account_health_long_queries_sql,
    build_mart_account_health_credits_sql, build_mart_account_health_failure_count_sql,
    build_mart_account_health_top_driver_sql, build_mart_account_health_queued_sql,
    build_mart_account_health_ytd_credits_sql,
    build_mart_bill_summary_sql, build_mart_bill_warehouse_delta_sql,
    build_mart_cost_cockpit_sql,
    build_mart_warehouse_overview_sql, build_mart_warehouse_scaling_sql,
    build_mart_usage_overview_sql, build_mart_usage_metering_sql, build_mart_usage_pressure_sql,
    build_mart_usage_cost_drivers_sql, build_mart_usage_query_mix_sql,
    build_mart_usage_database_adoption_sql,
    build_mart_adoption_summary_sql, build_mart_adoption_warehouse_size_sql,
    build_mart_adoption_trend_sql, build_mart_adoption_users_wh_sql,
    build_mart_adoption_users_db_sql, build_mart_adoption_role_type_sql,
    build_mart_storage_trend_sql, build_mart_storage_db_detail_sql,
    build_mart_pipeline_freshness_sql, build_mart_pipeline_load_failures_sql,
    build_mart_pipeline_volume_sql,
    build_mart_recommendation_idle_sql, build_mart_recommendation_spill_sql,
    build_mart_recommendation_failed_tasks_sql, build_mart_recommendation_query_errors_sql,
    build_mart_query_bottleneck_sql, build_mart_query_degradation_sql,
    build_mart_task_inventory_sql, build_mart_task_history_sql,
    build_mart_query_detail_recent_sql,
    build_mart_procedure_inventory_sql, build_mart_procedure_calls_sql,
    build_mart_procedure_sla_sql,
    build_mart_service_query_health_sql, build_mart_service_warehouse_health_sql,
    build_mart_service_login_health_sql, build_mart_service_task_health_sql,
)
from .bookmarks import (
    save_bookmark, load_bookmarks,
    apply_bookmark, delete_bookmark,
)
from .action_queue import (
    make_action_id, upsert_actions,
    load_action_queue, update_action_status,
)
from .workflows import (
    coerce_workflow_state, render_workflow_selector, render_workflow_guide,
    render_signal_confidence, add_signal_routes, render_priority_dataframe,
)
from .compatibility import (
    run_compatibility_checks, get_available_columns, view_supports_columns,
    filter_existing_columns, build_smoke_test_checklist, build_cost_formula_audit,
    build_task_history_sql, build_task_failure_summary_sql, build_task_health_sql,
)
from .optimization_advisor import render_optimization_advisor

__all__ = [
    "get_session",
    "run_query", "run_query_cached", "run_query_or_raise", "force_refresh",
    "safe_sql", "safe_identifier", "safe_schedule", "sql_literal",
    "get_query_telemetry", "get_query_budget_summary", "clear_query_telemetry", "format_snowflake_error",
    "normalize_df", "safe_strip_tz",
    "format_credits", "credits_to_dollars", "estimate_live_credits",
    "build_metered_credit_cte", "build_idle_warehouse_sql",
    "build_monitoring_cost_sql", "build_app_runtime_cost_sql", "build_cost_reconciliation_sql",
    "metric_confidence_label",
    "freshness_note", "CREDIT_RATES", "COMPUTE_CREDIT_CASE",
    "clamp_score", "score_label", "bad_ratio_score", "trend_score", "weighted_score",
    "burn_trend_label", "executive_health_score", "service_health_scorecard",
    "download_csv", "show_loaded_time", "mark_loaded", "clear_all_cache",
    "render_query_drilldown", "render_warehouse_drilldown",
    "render_drillable_bar_chart", "render_entity_query_drilldown",
    "render_optimization_advisor",
    "get_active_company", "get_db_filter_clause", "get_wh_filter_clause",
    "get_user_filter_clause", "get_role_filter_clause", "get_combined_filter_clause",
    "get_global_date_clause", "get_global_wh_filter_clause",
    "get_global_user_filter_clause", "get_global_role_filter_clause",
    "get_global_db_filter_clause", "get_global_filter_clause",
    "get_company_case_expr", "get_company_scope_key", "company_scoped_query",
    "company_value_allowed", "invalidate_company_cache",
    "paginate_df", "safe_float", "safe_int",
    "send_teams_alert",
    "log_section_load", "set_logging_enabled",
    "is_logging_enabled", "log_query_event", "is_query_logging_enabled",
    "set_query_logging_enabled", "SectionTimer",
    "admin_actions_enabled", "admin_button_disabled", "admin_disabled_reason",
    "render_admin_mode_control", "require_admin_enabled",
    "show_to_df", "first_existing_column", "ensure_column_alias",
    "scope_warehouse_names", "scope_metadata_df", "load_task_inventory",
    "load_warehouse_inventory", "build_unclassified_assets_sql",
    "MartResult", "mart_object_name", "load_mart_table",
    "load_latest_control_room_mart", "mart_source_caption",
    "build_mart_control_room_summary_sql", "build_mart_control_room_credits_sql",
    "build_mart_control_room_cost_drivers_sql", "build_mart_control_room_warehouse_pressure_sql",
    "build_mart_control_room_failed_queries_sql", "build_mart_control_room_object_changes_sql",
    "build_mart_control_room_failed_logins_sql", "build_mart_control_room_task_failures_sql",
    "build_mart_account_health_storage_sql", "build_mart_account_health_cost_drivers_sql",
    "build_mart_account_health_change_sql",
    "build_mart_account_health_failure_types_sql", "build_mart_account_health_long_queries_sql",
    "build_mart_account_health_credits_sql", "build_mart_account_health_failure_count_sql",
    "build_mart_account_health_top_driver_sql", "build_mart_account_health_queued_sql",
    "build_mart_account_health_ytd_credits_sql",
    "build_mart_bill_summary_sql", "build_mart_bill_warehouse_delta_sql",
    "build_mart_cost_cockpit_sql",
    "build_mart_warehouse_overview_sql", "build_mart_warehouse_scaling_sql",
    "build_mart_usage_overview_sql", "build_mart_usage_metering_sql", "build_mart_usage_pressure_sql",
    "build_mart_usage_cost_drivers_sql", "build_mart_usage_query_mix_sql",
    "build_mart_usage_database_adoption_sql",
    "build_mart_adoption_summary_sql", "build_mart_adoption_warehouse_size_sql",
    "build_mart_adoption_trend_sql", "build_mart_adoption_users_wh_sql",
    "build_mart_adoption_users_db_sql", "build_mart_adoption_role_type_sql",
    "build_mart_storage_trend_sql", "build_mart_storage_db_detail_sql",
    "build_mart_pipeline_freshness_sql", "build_mart_pipeline_load_failures_sql",
    "build_mart_pipeline_volume_sql",
    "build_mart_recommendation_idle_sql", "build_mart_recommendation_spill_sql",
    "build_mart_recommendation_failed_tasks_sql", "build_mart_recommendation_query_errors_sql",
    "build_mart_query_bottleneck_sql", "build_mart_query_degradation_sql",
    "build_mart_task_inventory_sql", "build_mart_task_history_sql",
    "build_mart_query_detail_recent_sql",
    "build_mart_procedure_inventory_sql", "build_mart_procedure_calls_sql",
    "build_mart_procedure_sla_sql",
    "build_mart_service_query_health_sql", "build_mart_service_warehouse_health_sql",
    "build_mart_service_login_health_sql", "build_mart_service_task_health_sql",
    "save_bookmark", "load_bookmarks",
    "apply_bookmark", "delete_bookmark",
    "make_action_id", "upsert_actions",
    "load_action_queue", "update_action_status",
    "coerce_workflow_state", "render_workflow_selector", "render_workflow_guide",
    "render_signal_confidence", "add_signal_routes", "render_priority_dataframe",
    "run_compatibility_checks", "get_available_columns", "view_supports_columns",
    "filter_existing_columns", "build_smoke_test_checklist", "build_cost_formula_audit",
    "build_task_history_sql", "build_task_failure_summary_sql", "build_task_health_sql",
]
