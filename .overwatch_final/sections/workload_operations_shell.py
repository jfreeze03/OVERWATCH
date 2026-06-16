"""Fast first-paint shell for the Workload Operations route."""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_DAY_WINDOW, DEFAULT_ENVIRONMENT, ENVIRONMENT_CONFIG
from sections.shell_helpers import (
    full_workspace_requested,
    render_shell_kpi_row,
    render_shell_snapshot,
    render_shell_workflows,
    render_signal_lane_board,
)
from utils.command_board import load_or_reuse_command_board


_FULL_WORKSPACE_KEY = "_workload_operations_full_workspace_requested"
_BRIEF_MODE_KEY = "_workload_operations_brief_mode"
_EXPLICIT_WORKFLOW_KEY = "_workload_operations_explicit_workflow_request"
_COMMAND_BOARD_DATA_KEY = "workload_operations_command_board_data"
_COMMAND_BOARD_SUMMARY_KEY = "workload_operations_command_board_summary"
_COMMAND_BOARD_META_KEY = "workload_operations_command_board_meta"
_COMMAND_BOARD_REFRESH_MARKER_KEY = "workload_operations_command_board_refresh_marker"
_FULL_WORKSPACE_STATE_KEYS = (
    _COMMAND_BOARD_SUMMARY_KEY,
    "workload_operations_snapshot",
    "workload_operations_task_snapshot",
    "workload_operations_snapshot_error",
    "workload_operations_task_snapshot_error",
    "live_monitor_state",
    "query_analysis_df",
    "task_management_df",
    "contention_decision_rows",
    "contention_historical_waits",
    "contention_table_hotspots",
    "contention_task_overlap",
    "contention_long_dml",
    "contention_task_mapping",
    "stored_proc_tracker_df",
    "pipeline_health_df",
    "query_search_results",
)

_WORKFLOWS = (
    {
        "WORKFLOW": "Query & contention triage",
        "BUTTON_LABEL": "Open Query Triage",
        "MOVE": "Find running, queued, failed, slow, spilling, blocked, or high-cost SQL before changing compute.",
    },
    {
        "WORKFLOW": "Task, procedure & pipeline health",
        "BUTTON_LABEL": "Open Pipeline Health",
        "MOVE": "Review task graph failures, late jobs, procedure drift, load health, and downstream backlog together.",
    },
)


def _active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def _active_environment() -> str:
    env = str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)
    return env if env in ENVIRONMENT_CONFIG else DEFAULT_ENVIRONMENT


def _window_label() -> str:
    start = st.session_state.get("global_start_date")
    end = st.session_state.get("global_end_date")
    if isinstance(start, date) and isinstance(end, date):
        days = max(1, (end - start).days + 1)
        return f"{days}d"
    return "Selected"


def _window_days() -> int:
    start = st.session_state.get("global_start_date")
    end = st.session_state.get("global_end_date")
    if isinstance(start, date) and isinstance(end, date):
        return max(1, (end - start).days + 1)
    return int(DEFAULT_DAY_WINDOW)


def _command_summary() -> dict:
    summary = st.session_state.get(_COMMAND_BOARD_SUMMARY_KEY)
    if isinstance(summary, dict) and summary.get("loaded"):
        return dict(summary)
    return {}


def _command_meta() -> dict:
    meta = st.session_state.get(_COMMAND_BOARD_META_KEY)
    return dict(meta) if isinstance(meta, dict) else {}


def _load_command_board() -> None:
    load_or_reuse_command_board(
        data_key=_COMMAND_BOARD_DATA_KEY,
        summary_key=_COMMAND_BOARD_SUMMARY_KEY,
        meta_key=_COMMAND_BOARD_META_KEY,
        refresh_marker_key=_COMMAND_BOARD_REFRESH_MARKER_KEY,
        company=_active_company(),
        environment=_active_environment(),
        days=_window_days(),
    )


def _full_workspace_requested() -> bool:
    """Keep Workload navigation data-first; open full detail only from a workflow."""
    _ = full_workspace_requested
    if st.session_state.get(_FULL_WORKSPACE_KEY):
        return True
    st.session_state.setdefault(_BRIEF_MODE_KEY, True)
    return False


def _frame_len(value: object) -> int:
    try:
        if value is None or bool(getattr(value, "empty", False)):
            return 0
    except Exception:
        if value is None:
            return 0
    try:
        return max(0, int(len(value)))
    except Exception:
        return 0


def _first_row(value: object) -> object | None:
    if not _frame_len(value):
        return None
    try:
        return value.iloc[0]
    except Exception:
        return None


def _row_get(row: object | None, key: str, default: object = None) -> object:
    if row is None:
        return default
    getter = getattr(row, "get", None)
    if callable(getter):
        return getter(key, default)
    try:
        return row[key]
    except Exception:
        return default


def _int_value(value: object, default: int = 0) -> int:
    try:
        return int(float(value if value is not None else default))
    except (TypeError, ValueError):
        return default


def _float_value(value: object, default: float = 0.0) -> float:
    try:
        number = float(value if value is not None else default)
        return default if number != number else number
    except (TypeError, ValueError):
        return default


def _seconds_label(value: object) -> str:
    if value is None or str(value).strip() == "":
        return "On demand"
    seconds = _float_value(value)
    if not seconds:
        return "0s"
    if seconds < 90:
        return f"{seconds:,.1f}s"
    return f"{seconds / 60.0:,.1f}m"


def _gb_label(value: object) -> str:
    gb = _float_value(value)
    if not gb:
        return "0 GB"
    return f"{gb:,.1f} GB"


def _summary_seconds_label(summary: dict, key: str) -> str:
    return _seconds_label(summary.get(key))


def _summary_gb_label(summary: dict, key: str) -> str:
    return _gb_label(summary.get(key))


def _open_workspace(workflow: str | None = None) -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    if workflow:
        st.session_state[_EXPLICIT_WORKFLOW_KEY] = True
        st.session_state["workload_operations_workflow"] = workflow
    st.rerun()


def _delegate_full_workspace() -> None:
    from sections import workload_operations

    workload_operations.render()


def _return_to_workload_board() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


def _render_back_to_workload_board_control() -> None:
    control_col, _spacer = st.columns([1.0, 4.0])
    with control_col:
        if st.button("Back to Workload Board", key="workload_operations_shell_back_to_board", width="stretch"):
            _return_to_workload_board()


def _render_metric_board() -> None:
    snapshot = st.session_state.get("workload_operations_snapshot")
    task_snapshot = st.session_state.get("workload_operations_task_snapshot")
    snapshot_row = _first_row(snapshot)
    task_row = _first_row(task_snapshot)
    freshness_meta = st.session_state.get("workload_operations_snapshot_meta")
    if not isinstance(freshness_meta, dict) or not freshness_meta:
        freshness_meta = st.session_state.get("workload_operations_task_snapshot_meta", {})
    if not isinstance(freshness_meta, dict) or not freshness_meta:
        freshness_meta = _command_meta()

    st.markdown("**Workload Command Board**")
    render_signal_lane_board(
        "Workload Command Board",
        _workload_shell_lanes(snapshot_row, task_row),
        max_lanes=8,
    )
    summary = _command_summary()
    render_shell_snapshot((
        ("Queries", f"{_int_value(_row_get(snapshot_row, 'TOTAL_QUERIES', summary.get('total_queries'))):,}" if snapshot_row is not None or summary else "On demand"),
        ("Failed Queries", f"{_int_value(_row_get(snapshot_row, 'FAILED_QUERIES', summary.get('failed_queries'))):,}" if snapshot_row is not None or summary else "On demand"),
        ("Queue Time", _seconds_label(_row_get(snapshot_row, "QUEUE_SECONDS", summary.get("queue_seconds"))) if snapshot_row is not None or summary else "On demand"),
        ("Task Failures", f"{_int_value(_row_get(task_row, 'TASK_STATUS_FAILURE_ROWS', summary.get('failed_tasks'))):,}" if task_row is not None or summary else "On demand"),
    ))


def _workload_shell_lanes(snapshot_row: object | None, task_row: object | None) -> tuple[dict[str, str], ...]:
    if snapshot_row is None and task_row is None:
        summary = _command_summary()
        if summary:
            failed_queries = _int_value(summary.get("failed_queries"))
            failed_tasks = _int_value(summary.get("failed_tasks"))
            total_queries = _int_value(summary.get("total_queries"))
            open_actions = _int_value(summary.get("open_actions"))
            critical_high = _int_value(summary.get("critical_high_alerts"))
            return (
                {
                    "label": "Query volume",
                    "value": f"{total_queries:,}",
                    "state": f"{failed_queries:,} failed",
                    "detail": "Fast summary facts supply first-paint query volume and failure pressure.",
                },
                {
                    "label": "Runtime p95",
                    "value": _summary_seconds_label(summary, "p95_runtime_sec"),
                    "state": "Performance",
                    "detail": "P95 runtime is the first signal for regressions before opening Query Diagnosis.",
                },
                {
                    "label": "Queue pressure",
                    "value": _summary_seconds_label(summary, "queue_seconds"),
                    "state": "Capacity",
                    "detail": f"Top queue warehouse: {summary.get('top_queue_warehouse') or 'On demand'}.",
                },
                {
                    "label": "Remote spillage",
                    "value": _summary_gb_label(summary, "remote_spill_gb"),
                    "state": "Memory",
                    "detail": f"Top spill warehouse: {summary.get('top_spill_warehouse') or 'On demand'}.",
                },
                {
                    "label": "Task failures",
                    "value": f"{failed_tasks:,}",
                    "state": "Pipeline",
                    "detail": "Failed task count routes into Task Graphs and the DBA morning queue.",
                },
                {
                    "label": "Alert pressure",
                    "value": f"{critical_high:,}",
                    "state": "Risk",
                    "detail": "Critical/high alert pressure should outrank routine optimization work.",
                },
                {
                    "label": "Routed actions",
                    "value": f"{open_actions:,}",
                    "state": "Queue",
                    "detail": "Open workload actions need a route, fix plan, and current status.",
                },
            )
        return (
            {
                "label": "Query volume",
                "value": "On demand",
                "state": "Refresh",
                "detail": "Fast summary facts supply bounded workload facts.",
            },
            {
                "label": "Runtime p95",
                "value": "On demand",
                "state": "Performance",
                "detail": "P95 runtime points to degraded query shapes and warehouse pressure.",
            },
            {
                "label": "Queue pressure",
                "value": "On demand",
                "state": "Capacity",
                "detail": "Queue seconds separate compute saturation from bad SQL.",
            },
            {
                "label": "Remote spillage",
                "value": "On demand",
                "state": "Memory",
                "detail": "Remote spill usually means inefficient joins, scans, or undersized compute.",
            },
            {
                "label": "Task failures",
                "value": "On demand",
                "state": "Pipeline",
                "detail": "Task graph failures and late runs become DBA work immediately.",
            },
            {
                "label": "Late task risk",
                "value": "On demand",
                "state": "SLA",
                "detail": "Late tasks are more important than generic task counts.",
            },
            {
                "label": "Contention",
                "value": "On demand",
                "state": "Root cause",
                "detail": "Blocked/waiting, table hotspots, task overlap, and fix plans load together.",
            },
        )

    total_queries = _int_value(_row_get(snapshot_row, "TOTAL_QUERIES"))
    failed_queries = _int_value(_row_get(snapshot_row, "FAILED_QUERIES"))
    queued_queries = _int_value(_row_get(snapshot_row, "QUEUED_QUERIES"))
    spill_queries = _int_value(_row_get(snapshot_row, "REMOTE_SPILL_QUERIES"))
    p95 = _row_get(snapshot_row, "P95_ELAPSED_SEC")
    failed_tasks = _int_value(_row_get(task_row, "TASK_STATUS_FAILURE_ROWS"))
    late_tasks = _int_value(_row_get(task_row, "TASK_STATUS_LATE_ROWS"))
    watch_tasks = _int_value(_row_get(task_row, "TASK_STATUS_WATCH_ROWS"))
    return (
        {
            "label": "Query volume",
            "value": f"{total_queries:,}",
            "state": f"{failed_queries:,} failed",
            "detail": "Failed query count should route into Query Diagnosis before escalation.",
        },
        {
            "label": "Runtime p95",
            "value": _seconds_label(p95),
            "state": "Performance",
            "detail": "Use query history and plan telemetry before changing warehouse size.",
        },
        {
            "label": "Queue pressure",
            "value": f"{queued_queries:,}",
            "state": "Capacity",
            "detail": "Queue pressure means inspect saturation, concurrency, and workload windows.",
        },
        {
            "label": "Remote spillage",
            "value": f"{spill_queries:,} query(s)",
            "state": "Memory",
            "detail": "Spill is a SQL-shape and warehouse-sizing signal, not just a cost metric.",
        },
        {
            "label": "Task failures",
            "value": f"{failed_tasks:,}",
            "state": "Pipeline",
            "detail": "Failed root/child task status routes into the morning command queue.",
        },
        {
            "label": "Late task risk",
            "value": f"{late_tasks:,}",
            "state": "SLA",
            "detail": f"{watch_tasks:,} additional task run(s) are on the watch list.",
        },
        {
            "label": "Contention",
            "value": f"{_frame_len(st.session_state.get('contention_decision_rows')):,}" if _frame_len(st.session_state.get("contention_decision_rows")) else "On demand",
            "state": "Root cause",
            "detail": "Lock waits, task overlap, long DML, and queue telemetry are handled together.",
        },
    )


def _render_workflow_launchpad() -> None:
    def _open(row):
        _open_workspace(str(row["WORKFLOW"]))

    render_shell_workflows(
        "Workload Investigation Workflows",
        _WORKFLOWS,
        label_key="WORKFLOW",
        key_prefix="workload_operations_shell",
        on_open=_open,
    )


def render() -> None:
    if _full_workspace_requested():
        _render_back_to_workload_board_control()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("workload_operations_shell_seen_at", datetime.now().isoformat(timespec="seconds"))
    _load_command_board()
    _render_metric_board()
    _render_workflow_launchpad()
