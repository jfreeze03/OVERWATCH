"""Shared section navigation helpers.

Keep direct section-to-section jumps aligned with sidebar navigation, saved
views, and retired route compatibility.
"""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from config import compatibility_state_for_section, normalize_section_name
from runtime_state import (
    ALERT_CENTER_ACTIVE_VIEW,
    COST_CONTRACT_WORKFLOW,
    DBA_CONTROL_ROOM_ACTIVE_VIEW,
    EXECUTIVE_LANDING_BRIEF_MODE,
    EXECUTIVE_LANDING_REFRESH_STARTED_AT,
    EXECUTIVE_LANDING_WORKSPACE_REQUESTED,
    NAV_SECTION,
    PENDING_AUTOLOAD_SECTION,
    PENDING_AUTOLOAD_STARTED_AT,
    PENDING_SECTION,
    SECTION_TRANSITION_STARTED_AT,
    SECURITY_POSTURE_VIEW,
    SECURITY_POSTURE_WORKFLOW,
    WORKLOAD_OPERATIONS_WORKFLOW,
    get_state,
    pop_state,
    set_state,
)


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
        pop_state(key, None)
    set_state(EXECUTIVE_LANDING_REFRESH_STARTED_AT, datetime.now().isoformat(timespec="seconds"))


def request_section_workspace(section: str) -> None:
    """Make a section jump render the useful working surface."""
    target = normalize_section_name(section)
    if target == "Executive Landing":
        set_state(EXECUTIVE_LANDING_WORKSPACE_REQUESTED, True)
        set_state(EXECUTIVE_LANDING_BRIEF_MODE, False)
        request_executive_landing_hydration()
    elif target == "DBA Control Room":
        set_state(DBA_CONTROL_ROOM_ACTIVE_VIEW, "Fast Watch")
    elif target == "Alert Center":
        set_state(ALERT_CENTER_ACTIVE_VIEW, "Active Alerts")
    elif target == "Cost & Contract":
        set_state(COST_CONTRACT_WORKFLOW, "Cost by Warehouse")
    elif target == "Workload Operations":
        set_state(WORKLOAD_OPERATIONS_WORKFLOW, "Workload Overview")
    elif target == "Security Monitoring":
        set_state(SECURITY_POSTURE_VIEW, "Failed Logins")
        set_state(SECURITY_POSTURE_WORKFLOW, "Failed Logins")
    set_state(PENDING_AUTOLOAD_SECTION, target)
    set_state(PENDING_AUTOLOAD_STARTED_AT, datetime.now().isoformat(timespec="seconds"))


def apply_navigation_state(section: str, *, mark_pending: bool = True) -> str:
    """Set the active section and apply compatibility state for retired routes."""
    raw_section = str(section or "").strip()
    target = normalize_section_name(raw_section)
    current = normalize_section_name(get_state(NAV_SECTION, ""))
    if mark_pending and (target != current or target == "Executive Landing"):
        set_state(PENDING_SECTION, target)
        set_state(SECTION_TRANSITION_STARTED_AT, datetime.now().isoformat(timespec="seconds"))
    for key, value in compatibility_state_for_section(raw_section).items():
        set_state(key, value)
    request_section_workspace(target)
    set_state(NAV_SECTION, target)
    return target


def apply_section_workflow_navigation(
    section: str,
    *,
    workflow: str = "",
    alert_center_view: str = "",
    mark_pending: bool = True,
) -> str:
    """Navigate to a section and optionally select its most useful workflow."""
    target = apply_navigation_state(section, mark_pending=mark_pending)
    workflow_value = str(workflow or "").strip()
    if target == "Alert Center":
        set_state(ALERT_CENTER_ACTIVE_VIEW, str(alert_center_view or workflow_value or "Active Alerts"))
    elif target == "Cost & Contract" and workflow_value:
        set_state(COST_CONTRACT_WORKFLOW, workflow_value)
    elif target == "Workload Operations" and workflow_value:
        set_state(WORKLOAD_OPERATIONS_WORKFLOW, workflow_value)
        if workflow_value in {"Task graphs", "Task & procedure health", "Task Management"}:
            set_state("workload_operations_pipeline_focus", "Failed Tasks")
        elif workflow_value in {"Stored procedures", "Stored procedure lineage", "Stored Proc Tracker"}:
            set_state("workload_operations_pipeline_focus", "Failed Procedures")
        elif workflow_value in {"Pipeline health", "Pipeline / SLA risk"}:
            set_state("workload_operations_pipeline_focus", "Load Issues & SLA")
    elif target == "Security Monitoring" and workflow_value:
        set_state(SECURITY_POSTURE_VIEW, workflow_value)
        set_state(SECURITY_POSTURE_WORKFLOW, workflow_value)
    return target
