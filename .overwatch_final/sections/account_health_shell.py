"""Fast first-paint shell for the Account Health route."""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, ENVIRONMENT_CONFIG
from sections.shell_helpers import action_state_label, evidence_caption, evidence_label, evidence_loaded, render_shell_snapshot, render_shell_workflows, scope_label


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
    "ah_briefing_data",
    "resmon_data",
)

_WORKFLOWS = (
    {
        "PANE": "Overview",
        "BUTTON_LABEL": "Open Health",
        "MOVE": "Load the daily health checklist, morning exceptions, gates, controls, and operator next moves.",
    },
    {
        "PANE": "Morning Report",
        "BUTTON_LABEL": "Open Morning Report",
        "MOVE": "Generate a DBA morning report for failures, pressure, changes, and workload risk.",
    },
    {
        "PANE": "Executive Briefing",
        "BUTTON_LABEL": "Open Executive Briefing",
        "MOVE": "Prepare leadership-ready cost, reliability, and risk summary evidence.",
    },
    {
        "PANE": "Resource Monitors",
        "BUTTON_LABEL": "Open Resource Monitors",
        "MOVE": "Review monitor coverage, quota pressure, and credit-governance blockers.",
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


def _render_action_brief() -> None:
    workspace_help = evidence_caption(
        st.session_state,
        _FULL_WORKSPACE_STATE_KEYS,
        "The shell stays zero-query; the health snapshot loads only after the full workspace is opened.",
    )
    with st.container(border=True):
        label_col, detail_col, action_col = st.columns([1.0, 3.0, 1.8])
        with label_col:
            st.markdown("**Action Brief**")
            st.caption(action_state_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS))
        with detail_col:
            st.markdown("**Open Account Health when the daily DBA checklist needs evidence.**")
        with action_col:
            if st.button(
                "Open Account Health",
                key="account_health_shell_open",
                help=workspace_help,
                type="primary",
                width="stretch",
            ):
                _open_workspace()


def _render_workflow_launchpad() -> None:
    def _open(row):
        _open_workspace(str(row["PANE"]))

    render_shell_workflows(
        "Account Health Workflows",
        _WORKFLOWS,
        label_key="PANE",
        key_prefix="account_health_shell",
        on_open=_open,
    )


def render() -> None:
    if _full_workspace_requested():
        _render_back_to_brief_control()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("account_health_shell_seen_at", datetime.now().isoformat(timespec="seconds"))
    _render_action_brief()
    _render_workflow_launchpad()
