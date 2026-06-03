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


def _render_briefing() -> None:
    rows = (
        ("Scope", f"{_active_company()} / {ENVIRONMENT_CONFIG[_active_environment()]['label']}"),
        ("Default window", "24-hour triage"),
        ("Evidence mode", "Snapshot first"),
        ("Credit rate", f"${_credit_price():.2f}/credit"),
    )
    cols = st.columns(len(rows))
    for col, (label, detail) in zip(cols, rows):
        with col:
            st.caption(label)
            st.write(detail)


def render() -> None:
    if _full_workspace_requested():
        _delegate_full_workspace()
        return

    st.session_state.setdefault("dba_control_room_shell_seen_at", datetime.now().isoformat(timespec="seconds"))

    _render_briefing()
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        st.metric("Scope", f"{_active_company()} / {_active_environment()}")
    with c2:
        st.number_input(
            "Cortex monthly budget ($)",
            min_value=1.0,
            value=float(st.session_state.get("dba_control_room_cortex_budget_usd", 5000.0)),
            step=250.0,
            key="dba_control_room_cortex_budget_usd",
        )
    with c3:
        st.info("DBA Control Room evidence is available on demand for live triage, snapshot checks, source health, and exports.")

    if st.button("Open DBA Control Room workspace", key="dba_control_room_open_full_workspace", type="primary"):
        st.session_state[_FULL_WORKSPACE_KEY] = True
        st.rerun()
