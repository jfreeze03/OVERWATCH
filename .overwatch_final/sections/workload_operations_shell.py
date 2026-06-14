"""Fast first-paint shell for the Workload Operations route."""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, ENVIRONMENT_CONFIG
from sections.shell_helpers import action_state_label, evidence_caption, evidence_label, full_workspace_requested, render_refresh_contract, render_shell_kpi_row, render_shell_snapshot, render_shell_status_strip, render_shell_workflows, scope_label


_FULL_WORKSPACE_KEY = "_workload_operations_full_workspace_requested"
_BRIEF_MODE_KEY = "_workload_operations_brief_mode"
_EXPLICIT_WORKFLOW_KEY = "_workload_operations_explicit_workflow_request"
_FULL_WORKSPACE_STATE_KEYS = (
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
        "WORKFLOW": "Task graphs",
        "BUTTON_LABEL": "Open Task Graphs",
        "MOVE": "Check Snowflake task and Snowflake job status, SLA risk, retries, and downstream impact.",
    },
    {
        "WORKFLOW": "Contention Center",
        "BUTTON_LABEL": "Open Contention",
        "MOVE": "Prove lock waits, overlapping tasks, long DML, or warehouse queueing before changing compute.",
    },
    {
        "WORKFLOW": "Query diagnosis",
        "BUTTON_LABEL": "Open Query Diagnosis",
        "MOVE": "Review p95 runtime, queue pressure, spill, high-cost SQL, regressions, plan steps, and history search.",
    },
    {
        "WORKFLOW": "Live triage",
        "BUTTON_LABEL": "Open Live Triage",
        "MOVE": "Find running, queued, blocked, failed, or cancellable work right now.",
    },
    {
        "WORKFLOW": "Stored procedures",
        "BUTTON_LABEL": "Open Procedures",
        "MOVE": "Trace CALL history, procedure runtime drift, lineage, and attributed cost.",
    },
    {
        "WORKFLOW": "Pipeline health",
        "BUTTON_LABEL": "Open Pipelines",
        "MOVE": "Review load health, Snowpipe, task/pipeline signals, and backlog.",
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


def _full_workspace_requested() -> bool:
    """Keep Workload navigation data-first; open full proof only from a workflow."""
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


def _open_workspace(workflow: str | None = None) -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    st.session_state["workload_operations_view"] = "Workload Brief"
    if workflow:
        st.session_state[_EXPLICIT_WORKFLOW_KEY] = True
        st.session_state["workload_operations_view"] = "Specialist Workflows"
        st.session_state["workload_operations_workflow"] = workflow
    st.rerun()


def _delegate_full_workspace() -> None:
    from sections import workload_operations

    workload_operations.render()


def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


def _render_back_to_brief_control() -> None:
    control_col, _spacer = st.columns([1.0, 4.0])
    with control_col:
        if st.button("Back to Brief", key="workload_operations_shell_back_to_brief", width="stretch"):
            _return_to_brief()


def _render_status_strip() -> None:
    detail = evidence_caption(
        st.session_state,
        _FULL_WORKSPACE_STATE_KEYS,
        "Task status, contention, query diagnosis, live triage, procedure, and pipeline proof open from the workflow grid.",
    )
    render_shell_status_strip(
        state=action_state_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS),
        headline="Workload command view: job status, contention, query pressure, and pipeline failures.",
        detail=detail,
    )


def _render_kpi_row() -> None:
    render_shell_kpi_row((
        ("Scope", scope_label(_active_company(), _active_environment())),
        ("Window", _window_label()),
        ("Evidence", evidence_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS)),
        ("Primary route", "Task graphs"),
    ))


def _render_metric_board() -> None:
    snapshot = st.session_state.get("workload_operations_snapshot")
    task_snapshot = st.session_state.get("workload_operations_task_snapshot")
    snapshot_row = _first_row(snapshot)
    task_row = _first_row(task_snapshot)
    freshness_meta = st.session_state.get("workload_operations_snapshot_meta")
    if not isinstance(freshness_meta, dict) or not freshness_meta:
        freshness_meta = st.session_state.get("workload_operations_task_snapshot_meta", {})

    st.markdown("**Workload Metric Board**")
    render_refresh_contract(
        freshness_meta if isinstance(freshness_meta, dict) else {},
        source="MART_DBA_CONTROL_ROOM / TASK_HISTORY",
        target_minutes=30,
        refresh_method="Scheduled workload mart and task-history refresh",
        live_fallback="Explicit live triage",
    )
    render_shell_snapshot((
        ("Queries", f"{_int_value(_row_get(snapshot_row, 'TOTAL_QUERIES')):,}" if snapshot_row is not None else "Not loaded"),
        ("Failed Queries", f"{_int_value(_row_get(snapshot_row, 'FAILED_QUERIES')):,}" if snapshot_row is not None else "Not loaded"),
        ("Queued Queries", f"{_int_value(_row_get(snapshot_row, 'QUEUED_QUERIES')):,}" if snapshot_row is not None else "Not loaded"),
        ("Task Failures", f"{_int_value(_row_get(task_row, 'TASK_STATUS_FAILURE_ROWS')):,}" if task_row is not None else "Not loaded"),
    ))
    render_shell_snapshot((
        ("Late Tasks", f"{_int_value(_row_get(task_row, 'TASK_STATUS_LATE_ROWS')):,}" if task_row is not None else "Not loaded"),
        ("Contention", "Loaded" if _frame_len(st.session_state.get("contention_decision_rows")) else "On demand"),
        ("Query Diagnosis", "Loaded" if _frame_len(st.session_state.get("query_analysis_df")) else "On demand"),
        ("Pipeline Health", "Loaded" if _frame_len(st.session_state.get("pipeline_health_df")) else "On demand"),
    ))


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
        _render_back_to_brief_control()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("workload_operations_shell_seen_at", datetime.now().isoformat(timespec="seconds"))
    _render_status_strip()
    _render_kpi_row()
    _render_metric_board()
    _render_workflow_launchpad()
