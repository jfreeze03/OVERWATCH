"""Fast first-paint shell for the DBA Control Room route."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, DEFAULTS, ENVIRONMENT_CONFIG


_FULL_WORKSPACE_KEY = "_dba_control_room_full_workspace_requested"
_FULL_WORKSPACE_STATE_KEYS = (
    "dba_control_room_data",
    "dba_control_room_snapshot_result",
    "dba_control_room_incident_board",
    "dba_control_room_handoff",
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


def _full_workspace_requested() -> bool:
    if st.session_state.get(_FULL_WORKSPACE_KEY):
        return True
    return any(st.session_state.get(key) is not None for key in _FULL_WORKSPACE_STATE_KEYS)


def _delegate_full_workspace() -> None:
    from sections import dba_control_room

    dba_control_room.render()


def _render_action_brief() -> None:
    with st.container(border=True):
        label_col, detail_col, action_col = st.columns([1.1, 3.2, 1.4])
        with label_col:
            st.markdown("**Action Brief**")
            st.caption("Ready")
        with detail_col:
            st.markdown("**Open the DBA workspace when a signal needs triage or proof.**")
            st.caption("Snapshot checks, source health, routed actions, and exports stay on demand.")
        with action_col:
            if st.button("Open DBA workspace", key="dba_control_room_open_full_workspace", type="primary", width="stretch"):
                st.session_state[_FULL_WORKSPACE_KEY] = True
                st.rerun()


def _render_operating_snapshot() -> None:
    metrics = (
        ("Scope", f"{_active_company()} / {_active_environment()}"),
        ("Window", "24h"),
        ("Evidence", "On demand"),
        ("Rate", f"${_credit_price():.2f}"),
    )
    st.markdown("**Operating Snapshot**")
    cols = st.columns(4)
    for col, (label, value) in zip(cols, metrics):
        with col:
            st.metric(label, value)


def render() -> None:
    if _full_workspace_requested():
        _delegate_full_workspace()
        return

    st.session_state.setdefault("dba_control_room_shell_seen_at", datetime.now().isoformat(timespec="seconds"))

    _render_action_brief()
    _render_operating_snapshot()
