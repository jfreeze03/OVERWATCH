"""Shared section navigation helpers.

Keep direct section-to-section jumps aligned with sidebar navigation, saved
views, and retired route compatibility.
"""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from config import compatibility_state_for_section, normalize_section_name


EXECUTIVE_LANDING_BOARD_STATE_KEYS = (
    "executive_landing_snapshot",
    "executive_landing_platform_summary",
    "executive_landing_command_board",
    "executive_landing_command_board_meta",
    "executive_landing_command_board_refresh_marker",
)


def request_executive_landing_hydration() -> None:
    """Force the landing wall to hydrate from the command mart on navigation."""
    for key in EXECUTIVE_LANDING_BOARD_STATE_KEYS:
        st.session_state.pop(key, None)
    st.session_state["_overwatch_executive_landing_refresh_started_at"] = datetime.now().isoformat(timespec="seconds")


def request_section_workspace(section: str) -> None:
    """Make a section jump render the useful working surface."""
    target = normalize_section_name(section)
    if target == "Executive Landing":
        st.session_state["_executive_landing_full_workspace_requested"] = True
        st.session_state["_executive_landing_brief_mode"] = False
        request_executive_landing_hydration()
    elif target == "DBA Control Room":
        st.session_state["dba_control_room_active_view"] = "Fast Watch"
    elif target == "Alert Center":
        st.session_state["alert_center_active_view"] = "Command Center"
    elif target == "Cost & Contract":
        st.session_state["cost_contract_workflow"] = "Usage attribution and run-rate"
    elif target == "Workload Operations":
        st.session_state["workload_operations_workflow"] = "Query investigation"
        st.session_state["workload_operations_query_focus"] = "Contention Telemetry"
    elif target == "Security Monitoring":
        st.session_state["security_posture_view"] = "Access posture"
        st.session_state["security_posture_workflow"] = "Access posture"
    st.session_state["_overwatch_pending_autoload_section"] = target
    st.session_state["_overwatch_pending_autoload_started_at"] = datetime.now().isoformat(timespec="seconds")


def apply_navigation_state(section: str, *, mark_pending: bool = True) -> str:
    """Set the active section and apply compatibility state for retired routes."""
    raw_section = str(section or "").strip()
    target = normalize_section_name(raw_section)
    current = normalize_section_name(st.session_state.get("nav_section", ""))
    if mark_pending and (target != current or target == "Executive Landing"):
        st.session_state["_overwatch_pending_section"] = target
        st.session_state["_overwatch_section_transition_started_at"] = datetime.now().isoformat(timespec="seconds")
    for key, value in compatibility_state_for_section(raw_section).items():
        st.session_state[key] = value
    request_section_workspace(target)
    st.session_state["nav_section"] = target
    return target
