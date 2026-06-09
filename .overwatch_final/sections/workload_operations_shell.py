"""Fast first-paint shell for the Workload Operations route."""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, ENVIRONMENT_CONFIG
from sections.shell_helpers import action_state_label, evidence_caption, evidence_label, evidence_loaded, scope_label


_FULL_WORKSPACE_KEY = "_workload_operations_full_workspace_requested"
_BRIEF_MODE_KEY = "_workload_operations_brief_mode"
_FULL_WORKSPACE_STATE_KEYS = (
    "workload_operations_snapshot",
    "workload_operations_task_snapshot",
    "workload_operations_snapshot_error",
    "workload_operations_task_snapshot_error",
    "live_monitor_state",
    "query_analysis_df",
    "task_management_df",
    "stored_proc_tracker_df",
    "pipeline_health_df",
    "query_search_results",
)

_WORKFLOWS = (
    {
        "WORKFLOW": "Task graphs",
        "BUTTON_LABEL": "Open Task Graphs",
        "MOVE": "Check Control-M and Snowflake job status, SLA risk, retries, and downstream impact.",
    },
    {
        "WORKFLOW": "Query diagnosis",
        "BUTTON_LABEL": "Open Query Diagnosis",
        "MOVE": "Review p95 runtime, queue pressure, spill, high-cost SQL, and regressions.",
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
    {
        "WORKFLOW": "History search",
        "BUTTON_LABEL": "Open History",
        "MOVE": "Find one query, user, warehouse, task, or incident evidence trail.",
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
    if st.session_state.get(_BRIEF_MODE_KEY):
        return False
    if st.session_state.get(_FULL_WORKSPACE_KEY):
        return True
    return evidence_loaded(st.session_state, _FULL_WORKSPACE_STATE_KEYS)


def _open_workspace(workflow: str | None = None) -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    st.session_state["workload_operations_view"] = "Workload Brief"
    if workflow:
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


def _render_action_brief() -> None:
    with st.container(border=True):
        label_col, detail_col, action_col = st.columns([1.0, 3.0, 1.8])
        with label_col:
            st.markdown("**Action Brief**")
            st.caption(action_state_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS))
        with detail_col:
            st.markdown("**Open Workload Operations when job status, performance, or errors need live proof.**")
            st.caption(
                evidence_caption(
                    st.session_state,
                    _FULL_WORKSPACE_STATE_KEYS,
                    "The shell stays zero-query; workload snapshots and live views load only after a workflow is selected.",
                )
            )
        with action_col:
            if st.button("Open Workload Workspace", key="workload_operations_shell_open", type="primary", width="stretch"):
                _open_workspace()


def _render_operating_snapshot() -> None:
    metrics = (
        ("Scope", scope_label(_active_company(), _active_environment())),
        ("Window", _window_label()),
        ("Evidence", evidence_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS)),
        ("Focus", "Jobs"),
    )
    st.markdown("**Operating Snapshot**")
    cols = st.columns(4)
    for col, (label, value) in zip(cols, metrics):
        with col:
            st.metric(label, value)


def _render_workflow_launchpad() -> None:
    st.markdown("**Workload Investigation Workflows**")
    visible = _WORKFLOWS[:3]
    cols = st.columns(3)
    for col, row in zip(cols, visible):
        with col:
            st.markdown(f"**{row['WORKFLOW']}**")
            st.caption(row["MOVE"])
            if st.button(row["BUTTON_LABEL"], key=f"workload_operations_shell_{row['WORKFLOW']}", width="stretch"):
                _open_workspace(str(row["WORKFLOW"]))

    show_all = bool(st.session_state.get("workload_operations_shell_show_all"))
    if not show_all and st.button("More Workload Workflows", key="workload_operations_shell_more"):
        st.session_state["workload_operations_shell_show_all"] = True
        st.rerun()

    if show_all:
        extra_cols = st.columns(3)
        for col, row in zip(extra_cols, _WORKFLOWS[3:]):
            with col:
                st.markdown(f"**{row['WORKFLOW']}**")
                st.caption(row["MOVE"])
                if st.button(row["BUTTON_LABEL"], key=f"workload_operations_shell_extra_{row['WORKFLOW']}", width="stretch"):
                    _open_workspace(str(row["WORKFLOW"]))
        if st.button("Hide Workload Workflows", key="workload_operations_shell_hide"):
            st.session_state["workload_operations_shell_show_all"] = False
            st.rerun()


def render() -> None:
    if _full_workspace_requested():
        _render_back_to_brief_control()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("workload_operations_shell_seen_at", datetime.now().isoformat(timespec="seconds"))
    _render_action_brief()
    _render_operating_snapshot()
    _render_workflow_launchpad()
