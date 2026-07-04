"""Session-state contracts and startup defaults for the OVERWATCH shell.

This module owns the app-level Streamlit session keys that must exist before
navigation, filters, access checks, or section rendering run. Section-specific
state remains inside each section.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import streamlit as st

from config import DEFAULT_COMPANY
from utils.evidence_mode import (
    TRIAGE_MODE_TRIAGE,
    evidence_mode_from_exceptions,
    exceptions_enabled_from_evidence_mode,
    normalize_evidence_mode,
)


ACTIVE_COMPANY = "active_company"
NAV_SECTION = "nav_section"
GLOBAL_START_DATE = "global_start_date"
GLOBAL_END_DATE = "global_end_date"
GLOBAL_DATE_RANGE_INPUT = "_global_date_range_input"
GLOBAL_ENVIRONMENT = "global_environment"
GLOBAL_WAREHOUSE = "global_warehouse"
GLOBAL_USER = "global_user"
GLOBAL_ROLE = "global_role"
GLOBAL_DATABASE = "global_database"
GLOBAL_SCHEMA = "global_schema"
GLOBAL_WAREHOUSE_SELECT = "global_warehouse_select"
GLOBAL_DATABASE_SELECT = "global_database_select"
GLOBAL_SCHEMA_SELECT = "global_schema_select"
GLOBAL_WAREHOUSE_OPTIONS = "global_warehouse_options"
GLOBAL_DATABASE_OPTIONS = "global_database_options"
GLOBAL_SCHEMA_OPTIONS = "global_schema_options"
GLOBAL_WAREHOUSE_CHOICE_SCOPE = "_global_warehouse_choice_scope"
GLOBAL_DATABASE_CHOICE_SCOPE = "_global_database_choice_scope"
GLOBAL_SCHEMA_CHOICE_SCOPE = "_global_schema_choice_scope"
GLOBAL_FILTER_CHOICE_SCOPE = "_global_filter_choice_scope"
GLOBAL_DATE_CLAMP_NOTICE_KEY = "_global_date_clamp_notice_key"
GLOBAL_DATE_CLAMP_PENDING_WARNING = "_global_date_clamp_pending_warning"
WIDGET_KEYS_RENDERED_THIS_RUN = "_overwatch_widget_keys_rendered_this_run"
PENDING_WIDGET_STATE_UPDATES = "_overwatch_pending_widget_state_updates"
PREV_ACTIVE_COMPANY = "_prev_active_company"
CURRENT_ROLE = "_overwatch_current_role"
CURRENT_ROLE_SOURCE = "_overwatch_current_role_source"
LAST_ALLOWED_ROLE = "_overwatch_last_allowed_role"
OVERWATCH_ACTOR = "_overwatch_actor"
SESSION_ID = "_session_id"
CONNECTION_AVAILABLE = "_overwatch_connection_available"
CONNECTION_UNAVAILABLE = "_overwatch_connection_unavailable"
CONNECTION_SURFACE = "_overwatch_connection_surface"
PRE_FIRST_PAINT_SESSION_OPEN_COUNT = "_overwatch_pre_first_paint_session_open_count"
SHELL_SESSION_OPEN_COUNT = "_overwatch_shell_session_open_count"
ADMIN_CONNECTION_TEST_COUNT = "_overwatch_admin_connection_test_count"
ACTIVE_SESSION_PROBE_COUNT = "_overwatch_active_session_probe_count"
RUNTIME_EVENT_LEDGER = "_overwatch_runtime_event_ledger"
ACCESS_GATE_STATE = "_overwatch_access_gate_state"
ACTIVE_SECTION = "_overwatch_active_section"
PENDING_SECTION = "_overwatch_pending_section"
PENDING_AUTOLOAD_SECTION = "_overwatch_pending_autoload_section"
PENDING_AUTOLOAD_STARTED_AT = "_overwatch_pending_autoload_started_at"
SECTION_TRANSITION_STARTED_AT = "_overwatch_section_transition_started_at"
LAST_RENDERED_SECTION = "_overwatch_last_rendered_section"
LAST_SECTION_RENDER_SIGNATURE = "_overwatch_last_section_render_signature"
SECTION_BODY_RESET_SIGNATURE = "_overwatch_section_body_reset_signature"
LAST_SECTION_RENDER_MS = "_overwatch_last_section_render_ms"
SECONDARY_CHROME_READY = "_overwatch_secondary_chrome_ready"
PREV_GLOBAL_FILTER_SIGNATURE = "_prev_global_filter_signature"
PREV_METRIC_SETTINGS_SIGNATURE = "_prev_metric_settings_signature"
SIDEBAR_PANEL = "_overwatch_sidebar_panel"
LOGGING_ENABLED = "_logging_enabled"
QUERY_LOGGING_ENABLED = "_query_logging_enabled"
DETAILED_QUERY_TAGS_ENABLED = "_detailed_query_tags_enabled"
ACTIVE_QUERY_TAG = "_overwatch_active_query_tag"
ACTIVE_QUERY_TAG_SECTION = "_overwatch_active_query_tag_section"
BROAD_ROLE_WARNING_SHOWN = "_overwatch_broad_role_warning_shown"
PERF_RUN_ID = "_overwatch_perf_run_id"
QUERY_TELEMETRY = "_overwatch_query_telemetry"
QUERY_BUDGET_HITS = "_overwatch_query_budget_hits"
QUERY_BUDGET_WARNING_HASHES = "_overwatch_query_budget_warning_hashes"
QUERY_WARNING_HASHES = "_overwatch_query_warning_hashes"
RESULT_GUARD_WARNING_HASHES = "_overwatch_result_guard_warning_hashes"
STATEMENT_TIMEOUT_SECONDS = "_overwatch_statement_timeout_seconds"
AVAILABLE_COLUMNS_CACHE = "_overwatch_available_columns"
UNAVAILABLE_COLUMN_VIEWS = "_overwatch_unavailable_column_views"
COLUMN_PROBE_CACHE = "_overwatch_column_probe"
SHOW_STATEMENT_CACHE = "_overwatch_show_statement_cache"
QUERY_BUDGET_WINDOW_STARTED_AT = "_overwatch_query_budget_window_started_at"
QUERY_BUDGET_WINDOW_COUNT = "_overwatch_query_budget_window_count"
QUERY_BUDGET_WINDOW_WARNED = "_overwatch_query_budget_window_warned"
REFRESH_SALT_GLOBAL = "_refresh_salt_global"
REFRESH_SALT_PREFIX = "_refresh_salt_"
TRIAGE_VIEW_MODE = "triage_view_mode"
EXCEPTIONS_ONLY_MODE = "exceptions_only_mode"
CREDIT_PRICE = "credit_price"
CREDIT_PRICE_INPUT = "_credit_price_input"
AI_CREDIT_PRICE = "ai_credit_price"
AI_CREDIT_PRICE_INPUT = "_ai_credit_price_input"
STORAGE_COST_PER_TB = "storage_cost_per_tb"
STORAGE_COST_INPUT = "_storage_cost_input"
ALERT_EMAIL_TARGETS = "alert_email_targets"
ALERT_EMAIL_TARGETS_INPUT = "_alert_email_targets_input"
LIVE_REFRESH_INTERVAL = "rt_interval"
IDLE_TIMEOUT_SECONDS = "overwatch_idle_timeout_seconds"
LAST_OPERATOR_ACTIVITY_TS = "_overwatch_last_operator_activity_ts"
QUERIES_PAUSED = "_overwatch_queries_paused"
QUERY_PAUSED_AT_TS = "_overwatch_query_paused_at_ts"
QUERY_PAUSE_REASON = "_overwatch_query_pause_reason"
QUERY_PAUSE_WARNING_PREFIX = "_overwatch_query_pause_warning_shown"
LIVE_MONITOR_AUTO_REFRESH = "lm_auto"
ADMIN_ACTIONS_ENABLED = "admin_actions_enabled"
SF_SESSION = "sf_session"
SF_SESSION_CREATED_AT = "_sf_session_created_at"

GLOBAL_FILTER_KEYS = (
    GLOBAL_START_DATE,
    GLOBAL_END_DATE,
    GLOBAL_WAREHOUSE,
    GLOBAL_USER,
    GLOBAL_ROLE,
    GLOBAL_DATABASE,
    GLOBAL_SCHEMA,
    GLOBAL_ENVIRONMENT,
    GLOBAL_WAREHOUSE_SELECT,
    GLOBAL_DATABASE_SELECT,
    GLOBAL_SCHEMA_SELECT,
    GLOBAL_WAREHOUSE_OPTIONS,
    GLOBAL_DATABASE_OPTIONS,
    GLOBAL_SCHEMA_OPTIONS,
    GLOBAL_FILTER_CHOICE_SCOPE,
    GLOBAL_WAREHOUSE_CHOICE_SCOPE,
    GLOBAL_DATABASE_CHOICE_SCOPE,
    GLOBAL_SCHEMA_CHOICE_SCOPE,
    GLOBAL_DATE_RANGE_INPUT,
    GLOBAL_DATE_CLAMP_NOTICE_KEY,
    GLOBAL_DATE_CLAMP_PENDING_WARNING,
)

EXECUTIVE_LANDING_WORKSPACE_REQUESTED = "_executive_landing_full_workspace_requested"
EXECUTIVE_LANDING_BRIEF_MODE = "_executive_landing_brief_mode"
EXECUTIVE_LANDING_REFRESH_STARTED_AT = "_overwatch_executive_landing_refresh_started_at"
EXECUTIVE_LANDING_WORKFLOW = "executive_landing_workflow"
DBA_CONTROL_ROOM_ACTIVE_VIEW = "dba_control_room_active_view"
ALERT_CENTER_ACTIVE_VIEW = "alert_center_active_view"
COST_CONTRACT_WORKFLOW = "cost_contract_workflow"
WORKLOAD_OPERATIONS_WORKFLOW = "workload_operations_workflow"
WORKLOAD_OPERATIONS_QUERY_FOCUS = "workload_operations_query_focus"
SECURITY_POSTURE_VIEW = "security_posture_view"
SECURITY_POSTURE_WORKFLOW = "security_posture_workflow"

WIDGET_GLOBAL_REFRESH = "global_refresh"
WIDGET_RETRY_SNOWFLAKE_CONNECTION = "retry_snowflake_connection"
WIDGET_RESUME_QUERIES = "overwatch_resume_queries"
WIDGET_GLOBAL_FILTERS_CLEAR_TOPBAR = "global_filters_clear_topbar"
WIDGET_GLOBAL_FILTERS_CLEAR = "global_filters_clear"
WIDGET_ADVANCED_SCOPE_STATUS = "global_advanced_scope_status"
WIDGET_SIDEBAR_PANEL_PREFIX = "sidebar_panel"
WIDGET_NAV_BUTTON_PREFIX = "nav_btn"


def get_state(key: str, default: Any = None) -> Any:
    """Read an app-level state key without scattering raw access."""
    return st.session_state.get(key, default)


def _test_session_state_mirror_allowed() -> bool:
    return isinstance(st.session_state, dict)


def set_state(key: str, value: Any) -> None:
    """Set an app-level state key."""
    if widget_key_rendered_this_run(key):
        if st.session_state.get(key) == value:
            return
        queue_pending_widget_state_update(key, value)
        if _test_session_state_mirror_allowed():
            try:
                st.session_state[key] = value
            except Exception:
                pass
        return
    try:
        st.session_state[key] = value
    except Exception as exc:
        message = str(exc or "")
        if "cannot be modified after the widget with key" not in message:
            raise
        if st.session_state.get(key) == value:
            return
        queue_pending_widget_state_update(key, value)
        if _test_session_state_mirror_allowed():
            try:
                st.session_state[key] = value
            except Exception:
                pass


def queue_pending_widget_state_update(key: str, value: Any) -> None:
    """Queue a widget-key update for the next script run."""
    pending = st.session_state.setdefault(PENDING_WIDGET_STATE_UPDATES, {})
    if not isinstance(pending, dict):
        pending = {}
        st.session_state[PENDING_WIDGET_STATE_UPDATES] = pending
    pending[str(key)] = value


def pop_state(key: str, default: Any = None) -> Any:
    """Remove and return an app-level state key."""
    return st.session_state.pop(key, default)


def reset_widget_render_tracking() -> None:
    """Start a fresh widget-render tracking window for the current script run."""
    st.session_state[WIDGET_KEYS_RENDERED_THIS_RUN] = []


def apply_pending_widget_state_updates() -> None:
    """Apply widget-key state updates queued during the previous script run."""
    pending = st.session_state.pop(PENDING_WIDGET_STATE_UPDATES, {})
    if not isinstance(pending, dict):
        return
    for key, value in pending.items():
        st.session_state[str(key)] = value


def widget_key_rendered_this_run(key: str) -> bool:
    """Return whether a Streamlit widget key has already been instantiated this run."""
    rendered = st.session_state.get(WIDGET_KEYS_RENDERED_THIS_RUN, [])
    return str(key) in {str(item) for item in rendered if item is not None}


def mark_widget_key_rendered(key: str) -> None:
    """Record that a widget key has been instantiated in this script run."""
    rendered = st.session_state.setdefault(WIDGET_KEYS_RENDERED_THIS_RUN, [])
    if not isinstance(rendered, list):
        rendered = []
        st.session_state[WIDGET_KEYS_RENDERED_THIS_RUN] = rendered
    key_text = str(key)
    if key_text not in {str(item) for item in rendered if item is not None}:
        rendered.append(key_text)


def _runtime_event_list() -> list[Any]:
    try:
        value = st.session_state.setdefault(RUNTIME_EVENT_LEDGER, [])
    except Exception:
        return []
    if not isinstance(value, list):
        try:
            st.session_state[RUNTIME_EVENT_LEDGER] = []
            return st.session_state[RUNTIME_EVENT_LEDGER]
        except Exception:
            return []
    return value


def record_runtime_event(
    *,
    event_type: str,
    route: str = "",
    section: str = "",
    workflow: str = "",
    boundary: str = "",
    query_tier: str = "",
    ttl_key: str = "",
    cache_hit: bool | None = None,
    elapsed_ms: float | int = 0,
    row_count: int = 0,
    max_rows: int | None = None,
    error: str = "",
    source_module: str = "",
    product_boundary: str = "",
    execution_boundary: str = "",
    action_id: str = "",
    before_first_paint: bool = False,
    after_first_paint: bool = False,
    user_initiated: bool = False,
    query_count_delta: int = 0,
    session_open_count_delta: int = 0,
    active_session_probe_count_delta: int = 0,
    direct_sql_count_delta: int = 0,
    account_usage_count_delta: int = 0,
    metadata_probe_count_delta: int = 0,
    account_usage_marker_present: bool = False,
    evidence_loader_marker_present: bool = False,
    cost_evidence_marker_present: bool = False,
    query_search_broad_marker_present: bool = False,
    setup_live_validation_marker_present: bool = False,
    route_action_marker_present: bool = False,
    raw_sql_included: bool = False,
    started_at: str = "",
    finished_at: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record an app-source runtime event without storing SQL or secrets."""
    now = datetime.now().isoformat(timespec="milliseconds")
    event = {
        "event_id": uuid4().hex[:16],
        "event_type": str(event_type or "runtime"),
        "route": str(route or section or ""),
        "section": str(section or ""),
        "workflow": str(workflow or ""),
        "boundary": str(boundary or execution_boundary or product_boundary or ""),
        "product_boundary": str(product_boundary or boundary or ""),
        "execution_boundary": str(execution_boundary or boundary or ""),
        "query_tier": str(query_tier or ""),
        "ttl_key": str(ttl_key or "")[:160],
        "cache_hit": cache_hit,
        "elapsed_ms": round(float(elapsed_ms or 0), 2),
        "row_count": int(row_count or 0),
        "max_rows": None if max_rows is None else int(max_rows),
        "error": str(error or "")[:300],
        "source_module": str(source_module or ""),
        "action_id": str(action_id or ""),
        "before_first_paint": bool(before_first_paint),
        "after_first_paint": bool(after_first_paint),
        "user_initiated": bool(user_initiated),
        "query_count_delta": int(query_count_delta or 0),
        "session_open_count_delta": int(session_open_count_delta or 0),
        "active_session_probe_count_delta": int(active_session_probe_count_delta or 0),
        "direct_sql_count_delta": int(direct_sql_count_delta or 0),
        "account_usage_count_delta": int(account_usage_count_delta or 0),
        "metadata_probe_count_delta": int(metadata_probe_count_delta or 0),
        "account_usage_marker_present": bool(account_usage_marker_present),
        "evidence_loader_marker_present": bool(evidence_loader_marker_present),
        "cost_evidence_marker_present": bool(cost_evidence_marker_present),
        "query_search_broad_marker_present": bool(query_search_broad_marker_present),
        "setup_live_validation_marker_present": bool(setup_live_validation_marker_present),
        "route_action_marker_present": bool(route_action_marker_present),
        "started_at": started_at or now,
        "finished_at": finished_at or now,
        "producer": "runtime_state",
        "provenance_origin": "producer",
        "raw_sql_included": bool(raw_sql_included),
    }
    if extra:
        for key, value in extra.items():
            if key not in event and key not in {"query_text", "sql", "raw_sql", "token_file_path"}:
                event[str(key)] = value
    events = _runtime_event_list()
    try:
        events.append(event)
        if len(events) > 500:
            del events[:-500]
    except Exception:
        pass
    return event


def get_runtime_event_ledger() -> list[dict[str, Any]]:
    """Return the source runtime event ledger for release harness capture."""
    return [dict(event) for event in _runtime_event_list() if isinstance(event, dict)]


def clear_runtime_event_ledger() -> None:
    """Clear source runtime event ledger rows for a fresh validation capture."""
    try:
        st.session_state[RUNTIME_EVENT_LEDGER] = []
    except Exception:
        pass


def summarize_runtime_event_ledger() -> dict[str, Any]:
    """Summarize source runtime events without needing raw SQL."""
    rows = get_runtime_event_ledger()
    return {
        "event_count": len(rows),
        "query_count": sum(int(row.get("query_count_delta") or 0) for row in rows),
        "session_open_count": sum(int(row.get("session_open_count_delta") or 0) for row in rows),
        "active_session_probe_count": sum(int(row.get("active_session_probe_count_delta") or 0) for row in rows),
        "direct_sql_count": sum(int(row.get("direct_sql_count_delta") or 0) for row in rows),
        "account_usage_count": sum(int(row.get("account_usage_count_delta") or 0) for row in rows),
        "metadata_probe_count": sum(int(row.get("metadata_probe_count_delta") or 0) for row in rows),
        "account_usage_marker_count": sum(1 for row in rows if bool(row.get("account_usage_marker_present"))),
        "evidence_loader_marker_count": sum(1 for row in rows if bool(row.get("evidence_loader_marker_present"))),
        "cost_evidence_marker_count": sum(1 for row in rows if bool(row.get("cost_evidence_marker_present"))),
        "query_search_broad_marker_count": sum(1 for row in rows if bool(row.get("query_search_broad_marker_present"))),
        "setup_live_validation_marker_count": sum(1 for row in rows if bool(row.get("setup_live_validation_marker_present"))),
        "route_action_marker_count": sum(1 for row in rows if bool(row.get("route_action_marker_present"))),
        "raw_sql_included": any(bool(row.get("raw_sql_included")) for row in rows),
    }


def ensure_default_state(key: str, value: Any) -> Any:
    """Ensure a default state value and return the effective value."""
    return st.session_state.setdefault(key, value)


def clear_scoped_state(keys: list[str] | tuple[str, ...]) -> None:
    """Clear a bounded set of related app-level state keys."""
    for key in keys:
        st.session_state.pop(key, None)


def ensure_startup_state() -> None:
    """Seed shell defaults before any widgets render."""
    apply_pending_widget_state_updates()
    reset_widget_render_tracking()
    ensure_default_state(ACTIVE_COMPANY, DEFAULT_COMPANY)
    ensure_default_state(LOGGING_ENABLED, False)
    ensure_default_state(QUERY_LOGGING_ENABLED, False)
    ensure_default_state(DETAILED_QUERY_TAGS_ENABLED, True)
    if GLOBAL_START_DATE not in st.session_state or GLOBAL_END_DATE not in st.session_state:
        default_end = datetime.now().date()
        default_start = default_end - timedelta(days=7)
        ensure_default_state(GLOBAL_START_DATE, default_start)
        ensure_default_state(GLOBAL_END_DATE, default_end)
        ensure_default_state(GLOBAL_DATE_RANGE_INPUT, (default_start, default_end))


def triage_mode_from_exceptions(enabled: bool) -> str:
    """Return the canonical triage mode for the legacy exceptions boolean."""
    return evidence_mode_from_exceptions(enabled)


def normalize_triage_mode(mode: object) -> str:
    """Normalize triage mode aliases from older sessions."""
    return normalize_evidence_mode(mode)


def exceptions_enabled_from_triage_mode(mode: object) -> bool:
    """Return whether the current triage mode means exception-only behavior."""
    return exceptions_enabled_from_evidence_mode(mode)


def sync_exceptions_only_mode() -> None:
    """Keep the legacy exceptions-only key aligned with triage mode."""
    set_state(
        EXCEPTIONS_ONLY_MODE,
        exceptions_enabled_from_triage_mode(get_state(TRIAGE_VIEW_MODE, TRIAGE_MODE_TRIAGE)),
    )


def ensure_triage_mode_state(default_exceptions: bool) -> None:
    """Seed and normalize triage mode without exposing a global UI knob."""
    raw_mode = get_state(TRIAGE_VIEW_MODE)
    if raw_mode is None:
        set_state(
            TRIAGE_VIEW_MODE,
            triage_mode_from_exceptions(bool(get_state(EXCEPTIONS_ONLY_MODE, default_exceptions))),
        )
    else:
        set_state(TRIAGE_VIEW_MODE, normalize_triage_mode(raw_mode))
    sync_exceptions_only_mode()


def apply_admin_defaults() -> None:
    """Seed admin-only defaults for the current session."""
    ensure_triage_mode_state(True)
