"""Fast first-paint shell for the Account Health route."""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, ENVIRONMENT_CONFIG
from sections.shell_helpers import action_state_label, evidence_caption, evidence_label, evidence_loaded, scope_label


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
    return evidence_loaded(st.session_state, _FULL_WORKSPACE_STATE_KEYS)


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
    with st.container(border=True):
        label_col, detail_col, action_col = st.columns([1.0, 3.0, 1.8])
        with label_col:
            st.markdown("**Action Brief**")
            st.caption(action_state_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS))
        with detail_col:
            st.markdown("**Open Account Health when the daily DBA checklist needs evidence.**")
            st.caption(
                evidence_caption(
                    st.session_state,
                    _FULL_WORKSPACE_STATE_KEYS,
                    "The shell stays zero-query; the health snapshot loads only after the full workspace is opened.",
                )
            )
        with action_col:
            if st.button("Open Account Health", key="account_health_shell_open", type="primary", width="stretch"):
                _open_workspace()


def _render_operating_snapshot() -> None:
    metrics = (
        ("Scope", scope_label(_active_company(), _active_environment())),
        ("Window", _window_label()),
        ("Evidence", evidence_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS)),
        ("Focus", "Checklist"),
    )
    st.markdown("**Operating Snapshot**")
    cols = st.columns(4)
    for col, (label, value) in zip(cols, metrics):
        with col:
            st.metric(label, value)


def _render_workflow_launchpad() -> None:
    st.markdown("**Account Health Workflows**")
    visible = _WORKFLOWS[:3]
    cols = st.columns(3)
    for col, row in zip(cols, visible):
        with col:
            st.markdown(f"**{row['PANE']}**")
            st.caption(row["MOVE"])
            if st.button(row["BUTTON_LABEL"], key=f"account_health_shell_{row['PANE']}", width="stretch"):
                _open_workspace(str(row["PANE"]))

    show_all = bool(st.session_state.get("account_health_shell_show_all"))
    if not show_all and st.button("More Account Health Workflows", key="account_health_shell_more"):
        st.session_state["account_health_shell_show_all"] = True
        st.rerun()

    if show_all:
        extra_cols = st.columns(1)
        for col, row in zip(extra_cols, _WORKFLOWS[3:]):
            with col:
                st.markdown(f"**{row['PANE']}**")
                st.caption(row["MOVE"])
                if st.button(row["BUTTON_LABEL"], key=f"account_health_shell_extra_{row['PANE']}", width="stretch"):
                    _open_workspace(str(row["PANE"]))
        if st.button("Hide Account Health Workflows", key="account_health_shell_hide"):
            st.session_state["account_health_shell_show_all"] = False
            st.rerun()


def render() -> None:
    if _full_workspace_requested():
        _render_back_to_brief_control()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("account_health_shell_seen_at", datetime.now().isoformat(timespec="seconds"))
    _render_action_brief()
    _render_operating_snapshot()
    _render_workflow_launchpad()
