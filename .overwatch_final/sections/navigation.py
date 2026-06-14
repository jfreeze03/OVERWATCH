"""Shared section navigation helpers.

Keep direct section-to-section jumps aligned with sidebar navigation, saved
views, and retired route compatibility.
"""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from config import compatibility_state_for_section, normalize_section_name


SECTION_WORKSPACE_STATE_KEYS = {
    "Executive Landing": ("_executive_landing_full_workspace_requested", "_executive_landing_brief_mode"),
    "DBA Control Room": ("_dba_control_room_full_workspace_requested", "_dba_control_room_brief_mode"),
    "Alert Center": ("_alert_center_full_workspace_requested", "_alert_center_brief_mode"),
    "Cost & Contract": ("_cost_contract_full_workspace_requested", "_cost_contract_brief_mode"),
    "Workload Operations": ("_workload_operations_full_workspace_requested", "_workload_operations_brief_mode"),
    "Governance & Security": ("_governance_security_full_workspace_requested", "_governance_security_brief_mode"),
}


def request_section_workspace(section: str) -> None:
    """Make a section jump render the data workspace instead of the compact brief."""
    target = normalize_section_name(section)
    state_keys = SECTION_WORKSPACE_STATE_KEYS.get(target)
    if not state_keys:
        return
    workspace_key, brief_key = state_keys
    st.session_state[workspace_key] = True
    st.session_state[brief_key] = False
    st.session_state["_overwatch_pending_autoload_section"] = target
    st.session_state["_overwatch_pending_autoload_started_at"] = datetime.now().isoformat(timespec="seconds")


def apply_navigation_state(section: str, *, mark_pending: bool = True) -> str:
    """Set the active section and apply compatibility state for retired routes."""
    raw_section = str(section or "").strip()
    target = normalize_section_name(raw_section)
    current = normalize_section_name(st.session_state.get("nav_section", ""))
    if mark_pending and target != current:
        st.session_state["_overwatch_pending_section"] = target
        st.session_state["_overwatch_section_transition_started_at"] = datetime.now().isoformat(timespec="seconds")
    for key, value in compatibility_state_for_section(raw_section).items():
        st.session_state[key] = value
    request_section_workspace(target)
    st.session_state["nav_section"] = target
    return target
