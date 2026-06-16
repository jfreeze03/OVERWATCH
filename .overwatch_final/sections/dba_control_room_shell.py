"""Fast first-paint shell for the DBA Control Room route."""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_DAY_WINDOW, DEFAULT_ENVIRONMENT, DEFAULTS, ENVIRONMENT_CONFIG
from sections.shell_helpers import (
    full_workspace_requested,
    render_shell_snapshot,
    render_shell_workflows,
    render_signal_lane_board,
)
from utils.command_board import load_or_reuse_command_board


_FULL_WORKSPACE_KEY = "_dba_control_room_full_workspace_requested"
_BRIEF_MODE_KEY = "_dba_control_room_brief_mode"
_FAST_ENTRY_VERSION_KEY = "_dba_control_room_shell_fast_entry_version"
_FAST_ENTRY_VERSION = 2
_COMMAND_BOARD_DATA_KEY = "dba_control_room_command_board_data"
_COMMAND_BOARD_SUMMARY_KEY = "dba_control_room_command_board_summary"
_COMMAND_BOARD_META_KEY = "dba_control_room_command_board_meta"
_COMMAND_BOARD_REFRESH_MARKER_KEY = "dba_control_room_command_board_refresh_marker"
_FULL_WORKSPACE_STATE_KEYS = (
    _COMMAND_BOARD_SUMMARY_KEY,
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
        "MOVE": "Refresh the DBA morning packet from route priority, handoff blockers, escalations, and route status.",
    },
    {
        "VIEW": "Operations Board",
        "BUTTON_LABEL": "Open Ops Board",
        "MOVE": "Build route priority, runbook, escalation, handoff, incident, and action queue detail.",
    },
    {
        "VIEW": "Triage",
        "BUTTON_LABEL": "Open Triage",
        "MOVE": "Work failed queries, failed tasks, security signals, cost pressure, and action queue blockers.",
    },
    {
        "VIEW": "Drill Routes",
        "BUTTON_LABEL": "Open Drill Routes",
        "MOVE": "Jump from each signal lane to the right monitoring detail without adding sidebar sprawl.",
    },
    {
        "VIEW": "Service Posture",
        "BUTTON_LABEL": "Open Service Posture",
        "MOVE": "Review service risk across query execution, warehouses, login/auth, tasks, and data loading.",
    },
    {
        "VIEW": "Report Brief",
        "BUTTON_LABEL": "Open Brief Export",
        "MOVE": "Prepare report-ready operator notes for leaders without giving them the dashboard.",
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


def _window_days() -> int:
    start = st.session_state.get("global_start_date")
    end = st.session_state.get("global_end_date")
    if isinstance(start, date) and isinstance(end, date):
        return max(1, (end - start).days + 1)
    return int(DEFAULT_DAY_WINDOW)


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


def _command_summary() -> dict:
    summary = st.session_state.get(_COMMAND_BOARD_SUMMARY_KEY)
    if isinstance(summary, dict) and summary.get("loaded"):
        return dict(summary)
    return {}


def _command_meta() -> dict:
    meta = st.session_state.get(_COMMAND_BOARD_META_KEY)
    return dict(meta) if isinstance(meta, dict) else {}


def _load_command_board() -> None:
    payload = load_or_reuse_command_board(
        data_key=_COMMAND_BOARD_DATA_KEY,
        summary_key=_COMMAND_BOARD_SUMMARY_KEY,
        meta_key=_COMMAND_BOARD_META_KEY,
        refresh_marker_key=_COMMAND_BOARD_REFRESH_MARKER_KEY,
        company=_active_company(),
        environment=_active_environment(),
        days=_window_days(),
    )
    if payload.summary.get("loaded"):
        st.session_state.setdefault("dba_control_room_source_mode", "Fast summary")


def _loaded_data_snapshot() -> tuple[tuple[str, object], ...]:
    data = st.session_state.get("dba_control_room_data")
    if isinstance(data, dict) and data:
        failed_queries = _frame_len(data.get("failed_queries"))
        failed_tasks = _frame_len(data.get("task_failures"))
        action_rows = _frame_len(data.get("action_queue"))
        return (
            ("Failed Queries", f"{failed_queries:,}"),
            ("Failed Tasks", f"{failed_tasks:,}"),
            ("Action Rows", f"{action_rows:,}"),
            ("Service Posture", "Loaded"),
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

    summary = _command_summary()
    if summary:
        return (
            ("Failed Queries", f"{int(_safe_float(summary.get('failed_queries'))):,}"),
            ("Failed Tasks", f"{int(_safe_float(summary.get('failed_tasks'))):,}"),
            ("Cost", f"${_safe_float(summary.get('current_cost_usd')):,.0f}"),
            ("Open Actions", f"{int(_safe_float(summary.get('open_actions'))):,}"),
        )

    return (
        ("Fast Watch", "On demand"),
        ("Morning", "On demand"),
        ("Ops Board", "On demand"),
        ("Triage", "On demand"),
    )


def _dba_shell_lanes() -> tuple[dict[str, str], ...]:
    data = st.session_state.get("dba_control_room_data")
    if isinstance(data, dict) and data:
        failed_queries = _frame_len(data.get("failed_queries"))
        failed_tasks = _frame_len(data.get("task_failures"))
        action_rows = _frame_len(data.get("action_queue"))
        incident_rows = _frame_len(data.get("incident_board")) or failed_queries + failed_tasks
        return (
            {
                "label": "Incidents",
                "value": f"{incident_rows:,}",
                "state": "Now",
                "detail": f"{failed_queries:,} query failures and {failed_tasks:,} task failures in the loaded board.",
            },
            {
                "label": "Action queue",
                "value": f"{action_rows:,}",
                "state": "Routes",
                "detail": "Open work should have route, action, and current status.",
            },
            {
                "label": "Service posture",
                "value": "Loaded",
                "state": "Ops",
                "detail": "Query, warehouse, login, task, and load posture roll up here.",
            },
            {
                "label": "Triage status",
                "value": "Loaded",
                "state": "Route",
                "detail": "Incident, action, and service posture signals stay visible before drilldown.",
            },
            {
                "label": "Morning route",
                "value": "Loaded",
                "state": "Brief",
                "detail": "Prioritize incidents, action blockers, then cost/control work.",
            },
            {
                "label": "Service posture",
                "value": "Loaded",
                "state": "Ops",
                "detail": "Query, warehouse, login, task, and load posture roll up here.",
            },
            {
                "label": "Handoff status",
                "value": "Available",
                "state": "Audit",
                "detail": "Operator notes should survive shift changes and leadership review.",
            },
            {
                "label": "Live fallback",
                "value": "Guarded",
                "state": "Safe",
                "detail": "Live Snowflake scans stay behind an explicit DBA route.",
            },
        )

    snapshot_result = st.session_state.get("dba_control_room_snapshot_result")
    snapshot = getattr(snapshot_result, "data", None)
    available = bool(getattr(snapshot_result, "available", False))
    if available and _frame_len(snapshot):
        failed_queries = int(_sum_column(snapshot, "FAILED_QUERIES_24H"))
        failed_tasks = int(_sum_column(snapshot, "FAILED_TASKS_24H"))
        credits = _sum_column(snapshot, "CREDITS_24H")
        cortex = _sum_column(snapshot, "CORTEX_COST_7D_USD")
        return (
            {
                "label": "Failed queries",
                "value": f"{failed_queries:,}",
                "state": "24h",
                "detail": "Start with repeated failures and high-impact users/warehouses.",
            },
            {
                "label": "Failed tasks",
                "value": f"{failed_tasks:,}",
                "state": "24h",
                "detail": "Task failures route into morning brief and incident handoff.",
            },
            {
                "label": "Credits 24h",
                "value": f"{credits:,.1f}",
                "state": f"${credits * _credit_price():,.0f}",
                "detail": "Compute burn is visible without opening Cost & Contract.",
            },
            {
                "label": "Cortex 7d",
                "value": f"${cortex:,.0f}",
                "state": "AI",
                "detail": "AI exceptions and cost patterns route to DBA action.",
            },
            {
                "label": "Incident pressure",
                "value": f"{failed_queries + failed_tasks:,}",
                "state": "Route",
                "detail": "Failures become prioritized DBA work, not passive charts.",
            },
            {
                "label": "Action route",
                "value": "Ready",
                "state": "Queue",
                "detail": "Failures become prioritized DBA work with status and next action.",
            },
            {
                "label": "Triage",
                "value": "Ready",
                "state": "Route",
                "detail": "Open triage for active failures, queue pressure, and blockers.",
            },
            {
                "label": "Live fallback",
                "value": "Guarded",
                "state": "Safe",
                "detail": "Use live routes only for current incidents.",
            },
        )

    summary = _command_summary()
    if summary:
        failed_queries = int(_safe_float(summary.get("failed_queries")))
        failed_tasks = int(_safe_float(summary.get("failed_tasks")))
        queue_seconds = _safe_float(summary.get("queue_seconds"))
        spill_gb = _safe_float(summary.get("remote_spill_gb"))
        p95 = _safe_float(summary.get("p95_runtime_sec"))
        open_actions = int(_safe_float(summary.get("open_actions")))
        critical_high = int(_safe_float(summary.get("critical_high_alerts")))
        current_cost = _safe_float(summary.get("current_cost_usd"))
        cortex = _safe_float(summary.get("cortex_cost_usd"))
        return (
            {
                "label": "Incident pressure",
                "value": f"{failed_queries + failed_tasks + critical_high:,}",
                "state": "Now",
                "detail": f"{failed_queries:,} failed querie(s), {failed_tasks:,} failed task(s), and {critical_high:,} critical/high alert(s).",
            },
            {
                "label": "Queue pressure",
                "value": f"{queue_seconds / 60.0:,.1f}m" if queue_seconds else "0m",
                "state": "Capacity",
                "detail": f"Top queue warehouse: {summary.get('top_queue_warehouse') or 'On demand'}.",
            },
            {
                "label": "P95 runtime",
                "value": f"{p95:,.1f}s" if p95 else "0s",
                "state": "Performance",
                "detail": "Use Query Diagnosis when p95 runtime and failure signals move together.",
            },
            {
                "label": "Remote spillage",
                "value": f"{spill_gb:,.1f} GB",
                "state": "Memory",
                "detail": f"Top spill warehouse: {summary.get('top_spill_warehouse') or 'On demand'}.",
            },
            {
                "label": "Spend",
                "value": f"${current_cost:,.0f}",
                "state": f"Cortex ${cortex:,.0f}",
                "detail": f"Top cost driver: {summary.get('top_cost_driver') or 'On demand'}.",
            },
            {
                "label": "Action queue",
                "value": f"{open_actions:,}",
                "state": "Routes",
                "detail": "Open actions should have route, recommendation, business impact, and telemetry status.",
            },
            {
                "label": "Failed queries",
                "value": f"{failed_queries:,}",
                "state": "Failures",
                "detail": "Repeated query failures drive the first DBA triage lane.",
            },
            {
                "label": "Failed tasks",
                "value": f"{failed_tasks:,}",
                "state": "Pipeline",
                "detail": "Task failures route into Workload Operations and DBA handoff.",
            },
        )

    return (
        {
            "label": "Fast watch",
            "value": "On demand",
            "state": "Refresh",
            "detail": "Failed queries, tasks, credits, and data health load from the fast summary.",
        },
        {
            "label": "Morning brief",
            "value": "On demand",
            "state": "Route",
            "detail": "Refresh the operator packet from failures, blockers, and routed actions.",
        },
        {
            "label": "Incident board",
            "value": "On demand",
            "state": "Ops",
            "detail": "Incidents need impact, route, next action, and telemetry status.",
        },
        {
            "label": "Triage",
            "value": "On demand",
            "state": "Route",
            "detail": "Route failed queries, tasks, cost pressure, security signals, and action blockers.",
        },
        {
            "label": "Failed queries",
            "value": "On demand",
            "state": "Failures",
            "detail": "Failed query counts load into the first DBA triage lane.",
        },
        {
            "label": "Service posture",
            "value": "On demand",
            "state": "Health",
            "detail": "Query execution, warehouses, login/auth, tasks, and data loading.",
        },
        {
            "label": "Handoff status",
            "value": "On demand",
            "state": "Audit",
            "detail": "Shift handoff should explain what happened and what to do next.",
        },
        {
            "label": "Failed tasks",
            "value": "On demand",
            "state": "Pipeline",
            "detail": "Failed task counts load into Workload Operations and handoff.",
        },
    )


def _open_workspace(view: str | None = None) -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    if view:
        if view == "Telemetry Inputs":
            view = "Operations Board"
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


def _render_command_snapshot() -> None:
    st.markdown("**DBA Command Snapshot**")
    render_signal_lane_board("DBA Command Board", _dba_shell_lanes(), max_lanes=8)
    render_shell_snapshot(_loaded_data_snapshot())


def _render_morning_route_board() -> None:
    data = st.session_state.get("dba_control_room_data")
    failed_queries = failed_tasks = action_rows = queue_minutes = 0
    if isinstance(data, dict) and data:
        failed_queries = _frame_len(data.get("failed_queries"))
        failed_tasks = _frame_len(data.get("task_failures"))
        action_rows = _frame_len(data.get("action_queue"))
    elif _command_summary():
        summary = _command_summary()
        failed_queries = int(_safe_float(summary.get("failed_queries")))
        failed_tasks = int(_safe_float(summary.get("failed_tasks")))
        action_rows = int(_safe_float(summary.get("open_actions")))
        queue_minutes = _safe_float(summary.get("queue_seconds")) / 60.0
    st.markdown("**Morning Route Board**")
    render_shell_snapshot((
        ("Incidents", f"{failed_queries + failed_tasks:,}" if failed_queries or failed_tasks else "On demand"),
        ("Action Queue", f"{action_rows:,}" if action_rows else "On demand"),
        ("Queue Pressure", f"{queue_minutes:,.1f}m" if queue_minutes else "On demand"),
        ("Triage", "Ready"),
    ))


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

    _load_command_board()
    _render_command_snapshot()
    _render_morning_route_board()
    _render_workflow_launchpad()
