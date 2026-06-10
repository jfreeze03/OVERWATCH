"""Fast first-paint shell for the Change & Drift route."""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, ENVIRONMENT_CONFIG
from sections.shell_helpers import action_state_label, evidence_caption, evidence_label, evidence_loaded, render_shell_snapshot, render_shell_workflows, scope_label


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
    "terraform_status",
    "jira_status",
    "source_control_status",
    "itsm_ticket_status",
)

_WORKFLOWS = (
    {
        "WORKFLOW": "Object and access changes",
        "BUTTON_LABEL": "Open Object Changes",
        "MOVE": "Start with recent DDL, grants, ownership, policy, and actor evidence.",
    },
    {
        "WORKFLOW": "Terraform evidence",
        "BUTTON_LABEL": "Open Terraform",
        "MOVE": "Match Terraform, Flyway, or Git deploy proof to Snowflake drift.",
    },
    {
        "WORKFLOW": "Jira evidence",
        "BUTTON_LABEL": "Open Jira",
        "MOVE": "Match approved Jira or ITSM tickets to deployment and object-change evidence.",
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
    if st.session_state.get(_BRIEF_MODE_KEY):
        return False
    if st.session_state.get(_FULL_WORKSPACE_KEY):
        return True
    return False


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


def _render_action_brief() -> None:
    with st.container(border=True):
        label_col, detail_col, action_col = st.columns([1.0, 3.0, 1.8])
        with label_col:
            st.markdown("**Action Brief**")
            st.caption(action_state_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS))
        with detail_col:
            st.markdown("**Open Change & Drift when approval proof, drift, or DBA action evidence is needed.**")
            st.caption(
                evidence_caption(
                    st.session_state,
                    _FULL_WORKSPACE_STATE_KEYS,
                    "The shell stays zero-query; change evidence loads only after a workflow is selected.",
                )
            )
        with action_col:
            if st.button("Open Change Workspace", key="change_drift_shell_open", type="primary", width="stretch"):
                _open_workspace()


def _render_operating_snapshot() -> None:
    metrics = (
        ("Scope", scope_label(_active_company(), _active_environment())),
        ("Window", _window_label()),
        ("Evidence", evidence_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS)),
    )
    st.markdown("**Operating Snapshot**")
    render_shell_snapshot(metrics)


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
    _render_action_brief()
    _render_operating_snapshot()
    _render_workflow_launchpad()
