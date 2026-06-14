"""Fast first-paint shell for the Security Posture route."""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, ENVIRONMENT_CONFIG
from sections.shell_helpers import action_state_label, evidence_caption, evidence_label, evidence_loaded, full_workspace_requested, render_shell_kpi_row, render_shell_status_strip, render_shell_workflows, scope_label


_FULL_WORKSPACE_KEY = "_security_posture_full_workspace_requested"
_BRIEF_MODE_KEY = "_security_posture_brief_mode"
_FULL_WORKSPACE_STATE_KEYS = (
    "security_posture_summary",
    "security_posture_exceptions",
    "security_operability_fact",
    "security_privileged_grants",
    "security_access_review_trend",
    "security_action_closure",
    "security_posture_proof_sql",
)

_WORKFLOWS = (
    {
        "WORKFLOW": "Access posture",
        "TITLE": "MFA & Login Review",
        "BUTTON_LABEL": "Open MFA Review",
        "MOVE": "Start with MFA gaps, failed logins, and user-level access evidence.",
    },
    {
        "WORKFLOW": "Privilege sprawl",
        "TITLE": "Privilege Sprawl",
        "BUTTON_LABEL": "Open Privileges",
        "MOVE": "Review admin roles, ownership, grant option, and approval blockers.",
    },
    {
        "WORKFLOW": "Data sharing exposure",
        "TITLE": "Data Sharing Exposure",
        "BUTTON_LABEL": "Open Sharing",
        "MOVE": "Validate shared databases, imported data, consumers, and owners.",
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


def _loaded_evidence_available() -> bool:
    return evidence_loaded(st.session_state, _FULL_WORKSPACE_STATE_KEYS)


def _open_workspace(workflow: str | None = None) -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    st.session_state["security_posture_view"] = "Security Brief"
    if workflow:
        st.session_state["security_posture_requested_view"] = "Access Workflows"
        st.session_state["security_posture_requested_workflow"] = workflow
    st.rerun()


def _delegate_full_workspace() -> None:
    from sections import security_posture

    security_posture.render()


def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


def _render_back_to_brief_control() -> None:
    control_col, _spacer = st.columns([1.0, 4.0])
    with control_col:
        if st.button("Back to Brief", key="security_posture_shell_back_to_brief", width="stretch"):
            _return_to_brief()


def _render_status_strip() -> None:
    detail = (
        evidence_caption(st.session_state, _FULL_WORKSPACE_STATE_KEYS, "")
        if _loaded_evidence_available()
        else "MFA, login, privilege, ownership, grant, and sharing evidence open from the workflow grid."
    )
    render_shell_status_strip(
        state=action_state_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS),
        headline="Security command view: identity, privilege, access review, and sharing exposure.",
        detail=detail,
    )


def _render_kpi_row() -> None:
    render_shell_kpi_row((
        ("Scope", scope_label(_active_company(), _active_environment())),
        ("Window", _window_label()),
        ("Evidence", evidence_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS)),
        ("Primary route", "Access posture"),
    ))


def _render_workflow_launchpad() -> None:
    def _open(row):
        _open_workspace(str(row["WORKFLOW"]))

    render_shell_workflows(
        "Security Investigation Workflows",
        _WORKFLOWS,
        label_key="WORKFLOW",
        title_key="TITLE",
        key_prefix="security_posture_shell",
        on_open=_open,
    )


def render() -> None:
    if _full_workspace_requested():
        _render_back_to_brief_control()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("security_posture_shell_seen_at", datetime.now().isoformat(timespec="seconds"))
    _render_status_strip()
    _render_kpi_row()
    _render_workflow_launchpad()
