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
    build_monitoring_cost_sql, build_app_runtime_cost_sql, metric_confidence_label,
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
from .helpers import paginate_df
from .alerts import build_alert_task_sql, send_teams_alert, build_annotation_ddl
from .logging import (
    build_usage_log_ddl, log_section_load, set_logging_enabled,
    is_logging_enabled, SectionTimer,
)
from .bookmarks import (
    build_bookmark_ddl, save_bookmark, load_bookmarks,
    apply_bookmark, delete_bookmark,
)
from .action_queue import (
    build_action_queue_ddl, make_action_id, upsert_actions,
    load_action_queue, update_action_status,
)
from .setup_bundle import build_overwatch_setup_bundle, build_snowflake_value_ddl
from .compatibility import (
    run_compatibility_checks, get_available_columns, view_supports_columns,
    filter_existing_columns, build_smoke_test_checklist, build_cost_formula_audit,
    build_task_history_sql, build_task_failure_summary_sql, build_task_health_sql,
)

__all__ = [
    "get_session",
    "run_query", "run_query_cached", "run_query_or_raise", "force_refresh",
    "safe_sql", "safe_identifier", "safe_schedule", "sql_literal",
    "get_query_telemetry", "get_query_budget_summary", "clear_query_telemetry", "format_snowflake_error",
    "normalize_df", "safe_strip_tz",
    "format_credits", "credits_to_dollars", "estimate_live_credits",
    "build_metered_credit_cte", "build_idle_warehouse_sql",
    "build_monitoring_cost_sql", "build_app_runtime_cost_sql", "metric_confidence_label",
    "freshness_note", "CREDIT_RATES", "COMPUTE_CREDIT_CASE",
    "clamp_score", "score_label", "bad_ratio_score", "trend_score", "weighted_score",
    "burn_trend_label", "executive_health_score", "service_health_scorecard",
    "download_csv", "show_loaded_time", "mark_loaded", "clear_all_cache",
    "render_query_drilldown", "render_warehouse_drilldown",
    "render_drillable_bar_chart", "render_entity_query_drilldown",
    "get_active_company", "get_db_filter_clause", "get_wh_filter_clause",
    "get_user_filter_clause", "get_role_filter_clause", "get_combined_filter_clause",
    "get_global_date_clause", "get_global_wh_filter_clause",
    "get_global_user_filter_clause", "get_global_role_filter_clause",
    "get_global_db_filter_clause", "get_global_filter_clause",
    "get_company_case_expr", "get_company_scope_key", "company_scoped_query",
    "company_value_allowed", "invalidate_company_cache",
    "paginate_df",
    "build_alert_task_sql", "send_teams_alert", "build_annotation_ddl",
    "build_usage_log_ddl", "log_section_load", "set_logging_enabled",
    "is_logging_enabled", "SectionTimer",
    "build_bookmark_ddl", "save_bookmark", "load_bookmarks",
    "apply_bookmark", "delete_bookmark",
    "build_action_queue_ddl", "make_action_id", "upsert_actions",
    "load_action_queue", "update_action_status",
    "build_overwatch_setup_bundle", "build_snowflake_value_ddl",
    "run_compatibility_checks", "get_available_columns", "view_supports_columns",
    "filter_existing_columns", "build_smoke_test_checklist", "build_cost_formula_audit",
    "build_task_history_sql", "build_task_failure_summary_sql", "build_task_health_sql",
]
