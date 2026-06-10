"""Fast first-paint shell for the DBA Control Room route."""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, DEFAULTS, ENVIRONMENT_CONFIG
from sections.shell_helpers import action_state_label, evidence_caption, evidence_label, evidence_loaded, render_shell_snapshot, scope_label


_FULL_WORKSPACE_KEY = "_dba_control_room_full_workspace_requested"
_BRIEF_MODE_KEY = "_dba_control_room_brief_mode"
_FULL_WORKSPACE_STATE_KEYS = (
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
        "VIEW": "Operations Board",
        "BUTTON_LABEL": "Open Ops Board",
        "MOVE": "Build route priority, runbook, escalation, handoff, incident, and action queue detail.",
    },
    {
        "VIEW": "Release Gate",
        "BUTTON_LABEL": "Open Release Gate",
        "MOVE": "Check deployment blockers, task recovery, schema migration, and approval evidence.",
    },
    {
        "VIEW": "Source Health",
        "BUTTON_LABEL": "Open Source Health",
        "MOVE": "Review which evidence sources are fresh, stale, skipped, or missing for this scope.",
    },
    {
        "VIEW": "Executive Evidence",
        "BUTTON_LABEL": "Open Brief Export",
        "MOVE": "Prepare report-ready operator notes for leaders without giving them the dashboard.",
    },
    {
        "VIEW": "Release Compare",
        "BUTTON_LABEL": "Open Compare",
        "MOVE": "Compare release windows for task, procedure, runtime, and cost regressions.",
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


def _full_workspace_requested() -> bool:
    if st.session_state.get(_BRIEF_MODE_KEY):
        return False
    if st.session_state.get(_FULL_WORKSPACE_KEY):
        return True
    return False


def _loaded_evidence_available() -> bool:
    return evidence_loaded(st.session_state, _FULL_WORKSPACE_STATE_KEYS)


def _open_workspace(view: str | None = None) -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    if view:
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


def _render_action_brief() -> None:
    with st.container(border=True):
        label_col, detail_col, action_col = st.columns([1.0, 3.0, 1.8])
        with label_col:
            st.markdown("**Action Brief**")
            st.caption(action_state_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS))
        with detail_col:
            st.markdown("**Open the DBA workspace when a signal needs triage, release proof, or a handoff.**")
            st.caption(
                (
                    evidence_caption(st.session_state, _FULL_WORKSPACE_STATE_KEYS, "")
                    if _loaded_evidence_available()
                    else "Fast snapshot, source health, routed actions, and exports stay on demand."
                )
            )
        with action_col:
            if st.button("Open DBA workspace", key="dba_control_room_open_full_workspace", type="primary", width="stretch"):
                _open_workspace()


def _render_operating_snapshot() -> None:
    metrics = (
        ("Scope", scope_label(_active_company(), _active_environment())),
        ("Window", _window_label()),
        ("Evidence", evidence_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS)),
        ("Rate", f"${_credit_price():.2f}"),
    )
    st.markdown("**Operating Snapshot**")
    render_shell_snapshot(metrics)


def _render_workflow_launchpad() -> None:
    st.markdown("**DBA Control Workflows**")
    visible = _WORKFLOWS[:3]
    cols = st.columns(3)
    for col, row in zip(cols, visible):
        with col:
            st.markdown(f"**{row['VIEW']}**")
            st.caption(row["MOVE"])
            if st.button(row["BUTTON_LABEL"], key=f"dba_control_room_shell_{row['VIEW']}", width="stretch"):
                _open_workspace(str(row["VIEW"]))

    show_all = bool(st.session_state.get("dba_control_room_shell_show_all"))
    if not show_all and st.button("More DBA Workflows", key="dba_control_room_shell_more"):
        st.session_state["dba_control_room_shell_show_all"] = True
        st.rerun()

    if show_all:
        extra_cols = st.columns(3)
        for col, row in zip(extra_cols, _WORKFLOWS[3:]):
            with col:
                st.markdown(f"**{row['VIEW']}**")
                st.caption(row["MOVE"])
                if st.button(row["BUTTON_LABEL"], key=f"dba_control_room_shell_extra_{row['VIEW']}", width="stretch"):
                    _open_workspace(str(row["VIEW"]))
        if st.button("Hide DBA Workflows", key="dba_control_room_shell_hide"):
            st.session_state["dba_control_room_shell_show_all"] = False
            st.rerun()


def render() -> None:
    if _full_workspace_requested():
        _render_back_to_brief_control()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("dba_control_room_shell_seen_at", datetime.now().isoformat(timespec="seconds"))

    _render_action_brief()
    _render_operating_snapshot()
    _render_workflow_launchpad()
