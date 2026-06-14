"""Fast first-paint shell for the DBA Control Room route."""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, DEFAULTS, ENVIRONMENT_CONFIG
from sections.shell_helpers import (
    action_state_label,
    evidence_caption,
    evidence_label,
    evidence_loaded,
    full_workspace_requested,
    render_refresh_contract,
    render_shell_kpi_row,
    render_shell_snapshot,
    render_shell_status_strip,
    render_shell_workflows,
    scope_label,
)


_FULL_WORKSPACE_KEY = "_dba_control_room_full_workspace_requested"
_BRIEF_MODE_KEY = "_dba_control_room_brief_mode"
_FAST_ENTRY_VERSION_KEY = "_dba_control_room_shell_fast_entry_version"
_FAST_ENTRY_VERSION = 2
_FULL_WORKSPACE_STATE_KEYS = (
    "dba_control_room_data",
    "dba_control_room_snapshot_result",
    "dba_control_room_incident_board",
    "dba_control_room_handoff",
)

_WORKFLOWS = (
    {
        "VIEW": "Fast Watch",
        "BUTTON_LABEL": "Open Fast Watch",
        "MOVE": "Start with the cheapest snapshot, failures, queue pressure, and routed exceptions.",
    },
    {
        "VIEW": "Morning Brief",
        "BUTTON_LABEL": "Open Morning Brief",
        "MOVE": "Build the DBA morning packet from route priority, handoff blockers, escalations, and owner proof.",
    },
    {
        "VIEW": "Operations Board",
        "BUTTON_LABEL": "Open Ops Board",
        "MOVE": "Build route priority, runbook, escalation, handoff, incident, and action queue detail.",
    },
    {
        "VIEW": "Release Gate",
        "BUTTON_LABEL": "Open Release Gate",
        "MOVE": "Check deployment blockers, task recovery, schema migration, and approval evidence.",
    },
    {
        "VIEW": "Source Health",
        "BUTTON_LABEL": "Open Source Health",
        "MOVE": "Review which evidence sources are fresh, stale, skipped, or missing for this scope.",
    },
    {
        "VIEW": "Service Posture",
        "BUTTON_LABEL": "Open Service Posture",
        "MOVE": "Review service risk across query execution, warehouses, login/auth, tasks, and data loading.",
    },
    {
        "VIEW": "Executive Evidence",
        "BUTTON_LABEL": "Open Brief Export",
        "MOVE": "Prepare report-ready operator notes for leaders without giving them the dashboard.",
    },
    {
        "VIEW": "Release Compare",
        "BUTTON_LABEL": "Open Compare",
        "MOVE": "Compare release windows for task, procedure, runtime, and cost regressions.",
    },
)


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value != value:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def _active_environment() -> str:
    env = str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)
    return env if env in ENVIRONMENT_CONFIG else DEFAULT_ENVIRONMENT


def _credit_price() -> float:
    return _safe_float(st.session_state.get("credit_price", DEFAULTS["credit_price"]), DEFAULTS["credit_price"])


def _window_label() -> str:
    start = st.session_state.get("global_start_date")
    end = st.session_state.get("global_end_date")
    if isinstance(start, date) and isinstance(end, date):
        days = max(1, (end - start).days + 1)
        return f"{days}d"
    return "24h"


def _full_workspace_requested() -> bool:
    """Keep DBA navigation lightweight; open the heavy workspace only from a selected DBA route."""
    _ = full_workspace_requested
    if st.session_state.get(_FULL_WORKSPACE_KEY):
        return True
    st.session_state.setdefault(_BRIEF_MODE_KEY, True)
    return False


def _apply_fast_entry_default() -> None:
    if st.session_state.get(_FAST_ENTRY_VERSION_KEY) == _FAST_ENTRY_VERSION:
        return
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FAST_ENTRY_VERSION_KEY] = _FAST_ENTRY_VERSION


def _loaded_evidence_available() -> bool:
    return evidence_loaded(st.session_state, _FULL_WORKSPACE_STATE_KEYS)


def _frame_len(value: object) -> int:
    if value is None:
        return 0
    try:
        if bool(getattr(value, "empty", False)):
            return 0
    except Exception:
        pass
    try:
        return max(0, int(len(value)))
    except Exception:
        return 0


def _sum_column(frame: object, column: str) -> float:
    try:
        series = frame[column]
        if hasattr(series, "sum"):
            return _safe_float(series.sum())
    except Exception:
        return 0.0
    return 0.0


def _control_room_meta() -> dict:
    meta = st.session_state.get("dba_control_room_meta")
    if isinstance(meta, dict):
        return dict(meta)
    return {}


def _loaded_data_snapshot() -> tuple[tuple[str, object], ...]:
    data = st.session_state.get("dba_control_room_data")
    if isinstance(data, dict) and data:
        failed_queries = _frame_len(data.get("failed_queries"))
        failed_tasks = _frame_len(data.get("task_failures"))
        action_rows = _frame_len(data.get("action_queue"))
        source_rows = _frame_len(data.get("source_health"))
        return (
            ("Failed Queries", f"{failed_queries:,}"),
            ("Failed Tasks", f"{failed_tasks:,}"),
            ("Action Rows", f"{action_rows:,}"),
            ("Sources", f"{source_rows:,}" if source_rows else "Loaded"),
        )

    snapshot_result = st.session_state.get("dba_control_room_snapshot_result")
    snapshot = getattr(snapshot_result, "data", None)
    available = bool(getattr(snapshot_result, "available", False))
    if available and _frame_len(snapshot):
        return (
            ("Failed Queries", f"{int(_sum_column(snapshot, 'FAILED_QUERIES_24H')):,}"),
            ("Failed Tasks", f"{int(_sum_column(snapshot, 'FAILED_TASKS_24H')):,}"),
            ("Credits 24h", f"{_sum_column(snapshot, 'CREDITS_24H'):,.1f}"),
            ("Cortex 7d", f"${_sum_column(snapshot, 'CORTEX_COST_7D_USD'):,.0f}"),
        )

    return (
        ("Fast Watch", "On demand"),
        ("Morning", "On demand"),
        ("Ops Board", "On demand"),
        ("Release Gate", "On demand"),
    )


def _open_workspace(view: str | None = None) -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    if view:
        st.session_state["dba_control_room_active_view"] = view
    st.rerun()


def _delegate_full_workspace() -> None:
    from sections import dba_control_room

    dba_control_room.render()


def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


def _render_back_to_brief_control() -> None:
    control_col, _spacer = st.columns([1.0, 4.0])
    with control_col:
        if st.button("Back to Brief", key="dba_control_room_shell_back_to_brief", width="stretch"):
            _return_to_brief()


def _render_status_strip() -> None:
    detail = (
        evidence_caption(st.session_state, _FULL_WORKSPACE_STATE_KEYS, "")
        if _loaded_evidence_available()
        else "Fast watch, source health, incidents, release gate, and handoff proof open from the workflow grid."
    )
    render_shell_status_strip(
        state=action_state_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS),
        headline="DBA command view: incidents, source health, release gates, and handoff risk.",
        detail=detail,
    )


def _render_kpi_row() -> None:
    render_shell_kpi_row((
        ("Scope", scope_label(_active_company(), _active_environment())),
        ("Window", _window_label()),
        ("Evidence", evidence_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS)),
        ("Primary route", "Fast Watch"),
    ))


def _render_command_snapshot() -> None:
    st.markdown("**DBA Command Snapshot**")
    render_refresh_contract(
        _control_room_meta(),
        source=st.session_state.get("dba_control_room_source_mode", "MART_DBA_CONTROL_ROOM"),
        target_minutes=30,
        refresh_method="Scheduled DBA control mart refresh",
        live_fallback="Explicit DBA route",
    )
    render_shell_snapshot(_loaded_data_snapshot())


def _render_workflow_launchpad() -> None:
    def _open(row):
        _open_workspace(str(row["VIEW"]))

    render_shell_workflows(
        "DBA Control Workflows",
        _WORKFLOWS,
        label_key="VIEW",
        key_prefix="dba_control_room_shell",
        on_open=_open,
    )


def render() -> None:
    _apply_fast_entry_default()
    if _full_workspace_requested():
        _render_back_to_brief_control()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("dba_control_room_shell_seen_at", datetime.now().isoformat(timespec="seconds"))

    _render_status_strip()
    _render_kpi_row()
    _render_command_snapshot()
    _render_workflow_launchpad()
