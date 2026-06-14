"""Fast first-paint shell for the Change & Drift route."""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, ENVIRONMENT_CONFIG
from sections.shell_helpers import action_state_label, evidence_caption, evidence_label, evidence_loaded, full_workspace_requested, render_shell_kpi_row, render_shell_status_strip, render_shell_workflows, scope_label


_FULL_WORKSPACE_KEY = "_change_drift_full_workspace_requested"
_BRIEF_MODE_KEY = "_change_drift_brief_mode"
_FULL_WORKSPACE_STATE_KEYS = (
    "change_drift_summary",
    "change_drift_exceptions",
    "change_control_operability_fact",
    "change_control_readiness",
    "change_action_closure",
    "change_drift_evidence_trend",
    "change_drift_proof_sql",
    "change_lineage_status",
    "change_data_movement_status",
)

_WORKFLOWS = (
    {
        "WORKFLOW": "Object and access changes",
        "BUTTON_LABEL": "Open Object Changes",
        "MOVE": "Start with recent DDL, grants, ownership, policy, and actor evidence.",
    },
    {
        "WORKFLOW": "Schema and object drift",
        "BUTTON_LABEL": "Open Schema Drift",
        "MOVE": "Compare schemas and review orphaned, unmanaged, or unexpected objects.",
    },
    {
        "WORKFLOW": "Data movement and replication",
        "BUTTON_LABEL": "Open Data Movement",
        "MOVE": "Review Snowpipe, dynamic tables, replication, and load freshness signals.",
    },
    {
        "WORKFLOW": "Stored procedure lineage",
        "BUTTON_LABEL": "Open Procedure Lineage",
        "MOVE": "Trace stored procedure ownership, child SQL, runtime drift, and downstream impact.",
    },
    {
        "WORKFLOW": "Controlled DBA actions",
        "BUTTON_LABEL": "Open DBA Actions",
        "MOVE": "Use guarded admin workflows with audit proof and verification requirements.",
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
    return full_workspace_requested(st.session_state, _FULL_WORKSPACE_KEY, _BRIEF_MODE_KEY)


def _open_workspace(workflow: str | None = None) -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    st.session_state["change_drift_view"] = "Change Brief"
    if workflow:
        st.session_state["change_drift_requested_view"] = "Change Workflows"
        st.session_state["change_drift_requested_workflow"] = workflow
    st.rerun()


def _delegate_full_workspace() -> None:
    from sections import change_drift

    change_drift.render()


def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


def _render_back_to_brief_control() -> None:
    control_col, _spacer = st.columns([1.0, 4.0])
    with control_col:
        if st.button("Back to Brief", key="change_drift_shell_back_to_brief", width="stretch"):
            _return_to_brief()


def _render_status_strip() -> None:
    detail = evidence_caption(
        st.session_state,
        _FULL_WORKSPACE_STATE_KEYS,
        "DDL, grants, schema drift, procedure lineage, replication, and controlled DBA action evidence open from the workflow grid.",
    )
    render_shell_status_strip(
        state=action_state_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS),
        headline="Change command view: Snowflake change proof, drift, lineage, and DBA action audit.",
        detail=detail,
    )


def _render_kpi_row() -> None:
    render_shell_kpi_row((
        ("Scope", scope_label(_active_company(), _active_environment())),
        ("Window", _window_label()),
        ("Evidence", evidence_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS)),
        ("Primary route", "Object changes"),
    ))


def _render_workflow_launchpad() -> None:
    def _open(row):
        _open_workspace(str(row["WORKFLOW"]))

    render_shell_workflows(
        "Change Investigation Workflows",
        _WORKFLOWS,
        label_key="WORKFLOW",
        key_prefix="change_drift_shell",
        on_open=_open,
    )


def render() -> None:
    if _full_workspace_requested():
        _render_back_to_brief_control()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("change_drift_shell_seen_at", datetime.now().isoformat(timespec="seconds"))
    _render_status_strip()
    _render_kpi_row()
    _render_workflow_launchpad()
