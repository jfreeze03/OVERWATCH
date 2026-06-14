"""Fast first-paint shell for the Account Health route."""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, ENVIRONMENT_CONFIG
from sections.shell_helpers import action_state_label, evidence_caption, evidence_label, evidence_loaded, full_workspace_requested, render_shell_kpi_row, render_shell_status_strip, render_shell_workflows, scope_label


_FULL_WORKSPACE_KEY = "_account_health_full_workspace_requested"
_BRIEF_MODE_KEY = "_account_health_brief_mode"
_FULL_WORKSPACE_STATE_KEYS = (
    "health_data",
    "account_health_morning_exceptions",
    "account_health_operator_gates",
    "account_health_operability_fact",
    "account_health_access_hygiene",
    "account_health_checklist_trend",
    "account_health_closure_analytics",
    "morning_data",
)

_WORKFLOWS = (
    {
        "PANE": "Morning Report",
        "TITLE": "DBA Morning Brief",
        "BUTTON_LABEL": "Open Morning Brief",
        "MOVE": "Build the on-call DBA morning packet from Control Room evidence, Account Health exceptions, and owner proof.",
    },
    {
        "PANE": "Overview",
        "TITLE": "Health Detail",
        "BUTTON_LABEL": "Open Health Detail",
        "MOVE": "Load the daily health checklist, morning exceptions, gates, controls, and operator next moves.",
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


def _open_workspace(pane: str = "Overview") -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    st.session_state["account_health_active_view"] = pane
    st.rerun()


def _delegate_full_workspace() -> None:
    from sections import account_health

    account_health.render()


def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


def _render_back_to_brief_control() -> None:
    control_col, _spacer = st.columns([1.0, 4.0])
    with control_col:
        if st.button("Back to Brief", key="account_health_shell_back_to_brief", width="stretch"):
            _return_to_brief()


def _render_status_strip() -> None:
    detail = evidence_caption(
        st.session_state,
        _FULL_WORKSPACE_STATE_KEYS,
        "Morning brief, health gates, access hygiene, checklist, and closure evidence open from the workflow grid.",
    )
    render_shell_status_strip(
        state=action_state_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS),
        headline="Account health command view: morning checklist, gates, controls, and owner proof.",
        detail=detail,
    )


def _render_kpi_row() -> None:
    render_shell_kpi_row((
        ("Scope", scope_label(_active_company(), _active_environment())),
        ("Window", _window_label()),
        ("Evidence", evidence_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS)),
        ("Primary route", "Morning Brief"),
    ))


def _render_workflow_launchpad() -> None:
    def _open(row):
        _open_workspace(str(row["PANE"]))

    render_shell_workflows(
        "Account Health Workflows",
        _WORKFLOWS,
        label_key="PANE",
        title_key="TITLE",
        key_prefix="account_health_shell",
        on_open=_open,
    )


def render() -> None:
    if _full_workspace_requested():
        _render_back_to_brief_control()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("account_health_shell_seen_at", datetime.now().isoformat(timespec="seconds"))
    _render_status_strip()
    _render_kpi_row()
    _render_workflow_launchpad()
