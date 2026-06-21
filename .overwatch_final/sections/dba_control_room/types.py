

"""DBA Control Room - operational landing page for OVERWATCH.

This page is intentionally workflow-first. It summarizes exceptions that a DBA
must triage, routes each signal to the right specialist tool, and creates
report-ready notes for leadership without making executives use the app.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import streamlit as st

from config import DEFAULT_ENVIRONMENT, DEFAULTS, SECTION_BY_TITLE, normalize_section_name
from sections.base import lazy_pandas, lazy_util as _lazy_util, lazy_util_attr
from sections.navigation import apply_navigation_state
from sections.shell_helpers import (
    _clean_display_text,
    consume_section_autoload_request,
    render_data_freshness,
    render_escaped_bold_text,
    render_shell_snapshot,
    render_shell_status_strip,
    with_loaded_at,
)
from utils.evidence_mode import (
    TRIAGE_MODE_ALL_EVIDENCE,
    TRIAGE_MODE_INVESTIGATE,
    TRIAGE_MODE_TRIAGE,
    current_evidence_mode,
    evidence_mode_is_all_evidence,
    evidence_mode_is_investigation,
)
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_section_note


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


def _dba_control_ops_scope_key(
    company: str,
    environment: str,
    lookback_hours: int,
    cortex_budget_usd: float,
    include_deep_evidence: bool,
    allow_live_fallback: bool,
    loaded_meta: dict | None,
) -> tuple:
    meta_items = tuple(sorted((str(k), _dba_control_scope_value(v)) for k, v in (loaded_meta or {}).items()))
    return (
        str(company),
        str(environment),
        int(lookback_hours),
        round(safe_float(cortex_budget_usd), 2),
        bool(include_deep_evidence),
        bool(allow_live_fallback),
        meta_items,
    )


def _task_management_helpers():
    from sections.task_management import (
        _build_task_ops_frames,
        _extract_object_candidates,
        _normalize_query_details,
        _procedure_from_definition,
        _query_detail_sql,
    )

    return (
        _build_task_ops_frames,
        _extract_object_candidates,
        _normalize_query_details,
        _procedure_from_definition,
        _query_detail_sql,
    )


def _cortex_helpers():
    from sections.cortex_monitor import (
        _build_cortex_control_sql,
        _cortex_cost_rating,
        _cortex_cost_score,
    )

    return _build_cortex_control_sql, _cortex_cost_rating, _cortex_cost_score


def _procedure_helpers():
    from sections.stored_proc_tracker import (
        _build_procedure_sla_frames,
        _build_procedure_sla_sql,
        _procedure_run_estimated_credits,
        _query_history_has_root_query_id,
    )

    return (
        _build_procedure_sla_frames,
        _build_procedure_sla_sql,
        _procedure_run_estimated_credits,
        _query_history_has_root_query_id,
    )


def _jump(title: str, *, warehouse: str = "", user: str = "", workflow: str = "") -> None:
    """Navigate to a registered section and carry useful filter context."""
    raw_target = SECTION_BY_TITLE.get(title, title)
    target = normalize_section_name(raw_target)
    if target not in set(SECTION_BY_TITLE.values()):
        return
    apply_navigation_state(raw_target)
    if workflow:
        if title in {"Query Workbench", "Workload Operations"}:
            st.session_state["_workload_operations_explicit_workflow_request"] = True
            if workflow == "Diagnosis":
                st.session_state["workload_operations_workflow"] = "Query diagnosis"
            elif workflow == "History Search":
                st.session_state["workload_operations_workflow"] = "Query diagnosis"
                st.session_state["query_analysis_active_view"] = "History Search"
            else:
                st.session_state["workload_operations_workflow"] = workflow
        elif title == "DBA Control Room" and workflow in DBA_CONTROL_ROOM_PANES:
            st.session_state["dba_control_room_active_view"] = workflow
        elif title == "Cost & Contract":
            st.session_state["cost_contract_workflow"] = workflow
        elif title == "Security Monitoring":
            st.session_state["security_posture_view"] = workflow if workflow in {"Access posture", "Privilege sprawl", "Data sharing exposure"} else "Access posture"
            st.session_state["security_posture_workflow"] = workflow or "Access posture"
        elif title == "Security Posture":
            st.session_state["security_posture_workflow"] = workflow
    if warehouse:
        st.session_state["global_warehouse"] = warehouse
        st.session_state["wh_filter"] = warehouse
    if user:
        st.session_state["global_user"] = user
    st.rerun()


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame()


def _dba_control_scope_value(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value).strip()


def _dba_control_scope_meta(
    company: str,
    environment: str,
    lookback_hours: int | None = None,
    cortex_budget_usd: float | None = None,
    include_deep_evidence: bool | None = None,
    allow_live_fallback: bool | None = None,
    state: dict | None = None,
) -> dict:
    """Return the exact operator scope a loaded DBA Control Room surface must match."""
    state = state if state is not None else st.session_state
    meta = {
        "company": _dba_control_scope_value(company),
        "environment": _dba_control_scope_value(environment),
    }
    if lookback_hours is not None:
        meta["lookback_hours"] = int(lookback_hours)
    if cortex_budget_usd is not None:
        meta["cortex_budget_usd"] = round(safe_float(cortex_budget_usd), 2)
    if include_deep_evidence is not None:
        meta["include_deep_evidence"] = bool(include_deep_evidence)
    if allow_live_fallback is not None:
        meta["allow_live_fallback"] = bool(allow_live_fallback)
    for key in DBA_CONTROL_SCOPE_FILTER_KEYS:
        meta[key] = _dba_control_scope_value(state.get(key))
    return meta


def _dba_control_meta_matches(meta: dict | None, expected: dict | None) -> bool:
    if not isinstance(meta, dict) or not isinstance(expected, dict):
        return False
    for key, expected_value in expected.items():
        actual = meta.get(key)
        if key == "lookback_hours":
            try:
                if int(actual) != int(expected_value):
                    return False
            except Exception:
                return False
        elif key == "cortex_budget_usd":
            if round(safe_float(actual), 2) != round(safe_float(expected_value), 2):
                return False
        elif isinstance(expected_value, bool):
            if bool(actual) != expected_value:
                return False
        elif _dba_control_scope_value(actual) != _dba_control_scope_value(expected_value):
            return False
    return True


def _dba_snapshot_scope_compatible(environment: str, state: dict | None = None) -> bool:
    """Fast snapshot is company-level only; scoped DBA telemetry needs detail load."""
    state = state if state is not None else st.session_state
    if str(environment or "ALL").upper() != "ALL":
        return False
    return not any(_dba_control_scope_value(state.get(key)) for key in DBA_CONTROL_SCOPE_FILTER_KEYS)


def _frame_or_empty(data: dict, key: str) -> pd.DataFrame:
    value = data.get(key, _empty_df()) if isinstance(data, dict) else _empty_df()
    return value if isinstance(value, pd.DataFrame) else _empty_df()


def _dba_task_status_task_summary(data: dict | None) -> dict:
    """Normalize the bounded Snowflake TASK_HISTORY summary used by Workload Operations."""
    empty_summary = {
        "loaded": False,
        "task_status_rows": 0,
        "task_status_failures": 0,
        "task_status_late": 0,
        "task_status_alerts": 0,
        "task_status_watch": 0,
        "last_seen": "",
    }
    if not isinstance(data, dict):
        return empty_summary

    frame = _empty_df()
    for key in (
        "workload_task_status",
        "workload_operations_task_snapshot",
        "task_status_task_status",
        "task_status_history_summary",
    ):
        candidate = _frame_or_empty(data, key)
        if not candidate.empty:
            frame = candidate
            break
    if frame.empty:
        return empty_summary

    view = frame.copy()
    view.columns = [str(col).upper() for col in view.columns]
    row = view.iloc[0]
    return {
        "loaded": True,
        "task_status_rows": safe_int(_row_value(row, "TASK_STATUS_ROWS", default=0)),
        "task_status_failures": safe_int(_row_value(row, "TASK_STATUS_FAILURE_ROWS", default=0)),
        "task_status_late": safe_int(_row_value(row, "TASK_STATUS_LATE_ROWS", default=0)),
        "task_status_alerts": safe_int(_row_value(row, "TASK_STATUS_ALERT_ROWS", default=0)),
        "task_status_watch": safe_int(_row_value(row, "TASK_STATUS_WATCH_ROWS", default=0)),
        "last_seen": str(_row_value(row, "TASK_STATUS_LAST_SEEN_AT", "LAST_SEEN", default="") or ""),
    }


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


def _normalize_focus_frame(value: pd.DataFrame | None) -> pd.DataFrame:
    if value is None or not isinstance(value, pd.DataFrame) or value.empty:
        return _empty_df()
    view = value.copy()
    view.columns = [str(col).upper() for col in view.columns]
    return view


def _target_object_from_row(row: dict | pd.Series | None) -> str:
    row = row if row is not None else {}
    explicit = str(_row_value(row, "TARGET_OBJECT", "WAIT_OBJECTS", default="") or "").strip()
    if explicit:
        return explicit.split(",")[0].strip()
    parts = [
        str(_row_value(row, "DATABASE_NAME", default="") or "").strip(),
        str(_row_value(row, "SCHEMA_NAME", default="") or "").strip(),
        str(_row_value(row, "OBJECT_NAME", default="") or "").strip(),
    ]
    return ".".join(part for part in parts if part and part.upper() not in {"NAN", "NONE", "NULL"})


def _focus_context_from_row(row: dict | pd.Series | None, *, reason: str = "") -> dict[str, str]:
    row = row if row is not None else {}
    query_id = str(_row_value(
        row,
        "QUERY_ID",
        "WAITER_QUERY_ID",
        "BLOCKER_QUERY_ID",
        "TASK_QUERY_ID",
        "RUN_1_QUERY_ID",
        "RUN_2_QUERY_ID",
        default="",
    ) or "").strip()
    return {
        "FOCUS_QUERY_ID": query_id,
        "FOCUS_WAREHOUSE": str(_row_value(row, "WAREHOUSE_NAME", "WAREHOUSE", default="") or "").strip(),
        "FOCUS_USER": str(_row_value(row, "USER_NAME", "USER", default="") or "").strip(),
        "FOCUS_OBJECT": _target_object_from_row(row),
        "FOCUS_REASON": str(reason or _row_value(row, "ROOT_CAUSE", "SIGNAL", "STATE", default="") or "").strip(),
    }


def _first_focus_context(
    frame: pd.DataFrame | None,
    *,
    tokens: tuple[str, ...] = (),
    numeric_columns: tuple[str, ...] = (),
    reason: str = "",
) -> dict[str, str]:
    view = _normalize_focus_frame(frame)
    if view.empty:
        return {}
    mask = pd.Series(False, index=view.index)
    if tokens:
        text_columns = [
            column for column in (
                "ROOT_CAUSE", "SIGNAL", "STATE", "WHY_NOW", "EVIDENCE",
                "NEXT_ACTION", "IMPACT_UNIT", "ERROR_MESSAGE", "QUERY_TEXT",
            )
            if column in view.columns
        ]
        if text_columns:
            combined = view[text_columns].fillna("").astype(str).agg(" ".join, axis=1).str.upper()
            mask = mask | combined.apply(lambda text: any(token in text for token in tokens))
    for column in numeric_columns:
        if column in view.columns:
            mask = mask | pd.to_numeric(view[column], errors="coerce").fillna(0).gt(0)
    candidates = view[mask] if bool(mask.any()) else view.head(1)
    return _focus_context_from_row(candidates.iloc[0], reason=reason)


def _top_warehouse_focus_context(frame: pd.DataFrame | None, *, reason: str = "") -> dict[str, str]:
    view = _normalize_focus_frame(frame)
    if view.empty:
        return {}
    sort_cols = [
        column for column in (
            "BLOCKED_QUERIES", "QUEUED_QUERIES", "AVG_BLOCKED",
            "MAX_QUEUED_LOAD", "REMOTE_SPILL_GB", "QUERIES",
        )
        if column in view.columns
    ]
    if sort_cols:
        for column in sort_cols:
            view[column] = pd.to_numeric(view[column], errors="coerce").fillna(0)
        view = view.sort_values(sort_cols, ascending=[False] * len(sort_cols))
    return _focus_context_from_row(view.iloc[0], reason=reason)

__all__ = [name for name in globals() if not name.startswith("__") and name != "annotations"]
