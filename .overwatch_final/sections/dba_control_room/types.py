"""Shared constants, lazy utility proxies, and primitive helpers for the DBA Control Room package."""
from __future__ import annotations

from config import DEFAULTS
from config import DEFAULT_ENVIRONMENT
from sections.base import lazy_pandas
from sections.base import lazy_util as _lazy_util
from sections.base import lazy_util_attr
from utils.primitives import safe_float
from utils.primitives import safe_int
from utils.section_guidance import defer_section_note
import streamlit as st




pd = lazy_pandas()


def get_active_environment() -> str:
    return str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)


def get_credit_price() -> float:
    return safe_float(st.session_state.get("credit_price", DEFAULTS.get("credit_price", 3.68)), 3.68)


def metric_confidence_label(kind: str) -> str:
    labels = {
        "exact": "Measurement: Exact",
        "allocated": "Measurement: Allocated from warehouse metering",
        "estimated": "Measurement: Estimated",
        "forecast": "Measurement: Forecast from recent observed burn",
        "projection": "Measurement: Projection from recent observed burn",
        "composite": "Measurement: Composite rollup from operational signals",
        "account": "Measurement: Account-wide",
        "account-wide": "Measurement: Account-wide",
    }
    return labels.get(str(kind or "").lower(), "Measurement depends on available account metadata")


def freshness_note(source: str) -> str:
    source_key = str(source or "").lower()
    if "information_schema" in source_key or source_key in {"live", "is"}:
        return "Freshness: live INFORMATION_SCHEMA view"
    if "account_usage" in source_key or source_key in {"account", "query_history", "warehouse_metering_history"}:
        return "Freshness: ACCOUNT_USAGE can lag up to about 45-90 minutes"
    if "organization_usage" in source_key:
        return "Freshness: ORGANIZATION_USAGE can lag several hours"
    if "session" in source_key:
        return "Freshness: current Streamlit session only"
    return "Freshness: depends on source view availability"


def _gate_state_from_counts(blocked: int, review: int) -> str:
    if safe_int(blocked):
        return "Blocked"
    if safe_int(review):
        return "Review"
    return "Ready"


def render_operator_briefing(items: list[tuple[str, str]], *, columns: int = 4) -> None:
    for label, detail in items:
        defer_section_note(f"{label}: {detail}")


build_metered_credit_cte = _lazy_util("build_metered_credit_cte")
build_task_failure_summary_sql = _lazy_util("build_task_failure_summary_sql")
build_task_history_sql = _lazy_util("build_task_history_sql")
credits_to_dollars = _lazy_util("credits_to_dollars")
dba_control_plane_section_scorecards = _lazy_util("dba_control_plane_section_scorecards")
dba_effective_readiness_score = _lazy_util("dba_effective_readiness_score")
download_csv = _lazy_util("download_csv")
enrich_action_queue_view = _lazy_util("enrich_action_queue_view")
format_credits = _lazy_util("format_credits")
format_snowflake_error = _lazy_util("format_snowflake_error")
filter_existing_columns = _lazy_util("filter_existing_columns")
get_db_filter_clause = _lazy_util("get_db_filter_clause")
get_active_company = _lazy_util("get_active_company")
get_global_filter_clause = _lazy_util("get_global_filter_clause")
get_session = _lazy_util("get_session")
get_user_company_filter_clause = _lazy_util("get_user_company_filter_clause")
get_wh_filter_clause = _lazy_util("get_wh_filter_clause")
get_owner_context_columns = lazy_util_attr("OWNER_CONTEXT_COLUMNS")
build_mart_control_room_summary_sql = _lazy_util("build_mart_control_room_summary_sql")
build_mart_control_room_credits_sql = _lazy_util("build_mart_control_room_credits_sql")
build_mart_control_room_cost_drivers_sql = _lazy_util("build_mart_control_room_cost_drivers_sql")
build_mart_control_room_warehouse_pressure_sql = _lazy_util("build_mart_control_room_warehouse_pressure_sql")
build_mart_control_room_failed_queries_sql = _lazy_util("build_mart_control_room_failed_queries_sql")
build_mart_control_room_object_changes_sql = _lazy_util("build_mart_control_room_object_changes_sql")
build_mart_control_room_failed_logins_sql = _lazy_util("build_mart_control_room_failed_logins_sql")
build_mart_control_room_task_failures_sql = _lazy_util("build_mart_control_room_task_failures_sql")
build_mart_query_detail_recent_sql = _lazy_util("build_mart_query_detail_recent_sql")
build_mart_task_history_sql = _lazy_util("build_mart_task_history_sql")
build_mart_procedure_sla_sql = _lazy_util("build_mart_procedure_sla_sql")
build_schema_migration_status_sql = _lazy_util("build_schema_migration_status_sql")
load_latest_control_room_mart = _lazy_util("load_latest_control_room_mart")
load_task_inventory = _lazy_util("load_task_inventory")
load_action_queue = _lazy_util("load_action_queue")
load_app_observability_detail = _lazy_util("load_app_observability_detail")
load_change_correlation_detail = _lazy_util("load_change_correlation_detail")
load_change_event_detail = _lazy_util("load_change_event_detail")
load_closed_loop_execution_plan_detail = _lazy_util("load_closed_loop_execution_plan_detail")
load_closed_loop_verification_detail = _lazy_util("load_closed_loop_verification_detail")
load_closed_loop_workflow_detail = _lazy_util("load_closed_loop_workflow_detail")
load_command_center_evidence_detail = _lazy_util("load_command_center_evidence_detail")
load_command_center_finding_detail = _lazy_util("load_command_center_finding_detail")
load_command_center_recommendation_detail = _lazy_util("load_command_center_recommendation_detail")
load_data_trust_detail = _lazy_util("load_data_trust_detail")
load_executive_scorecard_detail = _lazy_util("load_executive_scorecard_detail")
load_forecast_detail = _lazy_util("load_forecast_detail")
load_production_validation_detail = _lazy_util("load_production_validation_detail")
run_query = _lazy_util("run_query")
sql_literal = _lazy_util("sql_literal")
resolve_owner_context = _lazy_util("resolve_owner_context")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
render_load_status = _lazy_util("render_load_status")
render_workflow_selector = _lazy_util("render_workflow_selector")

DBA_CONTROL_SCOPE_FILTER_KEYS = (
    "global_warehouse",
    "global_user",
    "global_role",
    "global_database",
    "global_start_date",
    "global_end_date",
)
DBA_CONTROL_ROOM_PANES = (
    "Fast Watch",
    "Morning Brief",
    "Operations Detail",
    "Triage",
    "Drill Routes",
    "Service Posture",
    "Admin Tools",
)
DBA_CONTROL_ROOM_PANE_LABELS = {
    "Fast Watch": "Watch",
    "Morning Brief": "Morning",
    "Operations Detail": "Ops",
    "Triage": "Triage",
    "Drill Routes": "Routes",
    "Service Posture": "Service",
    "Admin Tools": "Admin",
}
DBA_CONTROL_ROOM_DETAIL_PANES = (
    "Failed Queries",
    "Task Failures",
    "Task SLA/Cost",
    "Procedure SLA/Cost",
    "Cortex Cost",
    "Failed Logins",
    "Object Changes",
    "Action Queue",
)

DBA_CONTROL_ROOM_DERIVED_STATE_KEYS = (
    "dba_control_room_incident_board",
    "dba_control_room_handoff",
    "dba_control_room_morning_brief",
    "dba_control_room_morning_brief_markdown",
    "dba_control_room_escalation_packet",
    "dba_control_room_escalation_packet_markdown",
    "dba_operations_priority_index",
    "dba_operator_runbook",
    "dba_operator_runbook_markdown",
    "dba_control_room_ops_scope_key",
    "dba_control_room_ops_ready",
)
DBA_CONTROL_ROOM_LIVE_FALLBACK_CAP_HOURS = 24
DBA_CONTROL_ROOM_LIVE_FALLBACK_KEYS = {
    "credits",
    "failed_queries",
    "failed_logins",
}


def _live_fallback_deferred_message(source: str, mart_exc: Exception | None = None) -> str:
    detail = format_snowflake_error(mart_exc) if mart_exc is not None else ""
    suffix = f" Summary error: {detail}" if detail else ""
    return (
        f"{source} telemetry is unavailable for the loaded scope. "
        f"Use the guarded drilldown workflow or refresh the fast summary for this surface.{suffix}"
    )


def _clear_dba_control_room_derived_state() -> None:
    """Clear derived boards when the loaded telemetry scope changes."""
    for key in DBA_CONTROL_ROOM_DERIVED_STATE_KEYS:
        st.session_state.pop(key, None)


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame()


def _dba_control_scope_value(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value).strip()


def _frame_or_empty(data: dict, key: str) -> pd.DataFrame:
    value = data.get(key, _empty_df()) if isinstance(data, dict) else _empty_df()
    return value if isinstance(value, pd.DataFrame) else _empty_df()


def _row_value(row, *names: str, default: object = "") -> object:
    for name in names:
        try:
            value = row.get(name)
        except AttributeError:
            value = None
        if value is None:
            continue
        if isinstance(value, float) and value != value:
            continue
        text = str(value).strip()
        if text and text.upper() not in {"NAN", "NONE", "NULL"}:
            return value
    return default
