"""Allowlisted routing for mart-backed command brief actions."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Mapping

import streamlit as st

from navigation import queue_section_navigation
from route_registry import SECTION_WORKFLOW_CONTRACT


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandBriefRoute:
    section: str
    workflow_key: str = ""
    workflow: str = ""
    state_updates: tuple[tuple[str, object], ...] = ()


COMMAND_BRIEF_ROUTES: Mapping[str, CommandBriefRoute] = {
    "executive_overview": CommandBriefRoute("Executive Landing", "executive_landing_workflow", "Executive Overview"),
    "executive_cost": CommandBriefRoute("Executive Landing", "executive_landing_workflow", "Cost Movement"),
    "cost_contract_cortex_ai": CommandBriefRoute("Cost & Contract", "cost_contract_workflow", "Cortex AI"),
    "cost_contract_overview": CommandBriefRoute("Cost & Contract", "cost_contract_workflow", "Cost Overview"),
    "cost_contract_explorer_warehouse": CommandBriefRoute(
        "Cost & Contract",
        "cost_contract_workflow",
        "Cost Explorer",
        (("cc_explorer_lens", "Warehouse"), ("cost_center_view", "Cost Explorer")),
    ),
    "cost_contract_explorer_user_role": CommandBriefRoute(
        "Cost & Contract",
        "cost_contract_workflow",
        "Cost Explorer",
        (("cc_explorer_lens", "User / Role"), ("cost_center_view", "Cost Explorer")),
    ),
    "cost_contract_budget": CommandBriefRoute("Cost & Contract", "cost_contract_workflow", "Budget vs Actual"),
    "alert_center_active": CommandBriefRoute("Alert Center", "alert_center_active_view", "Active Alerts"),
    "alert_center_critical_high": CommandBriefRoute("Alert Center", "alert_center_active_view", "Critical / High"),
    "alert_cortex_predictive": CommandBriefRoute("Alert Center", "alert_center_active_view", "Cortex Predictive Alerts"),
    "alert_center_cost": CommandBriefRoute("Alert Center", "alert_center_active_view", "Cost Alerts"),
    "alert_center_reliability": CommandBriefRoute("Alert Center", "alert_center_active_view", "Reliability Alerts"),
    "alert_center_security": CommandBriefRoute("Alert Center", "alert_center_active_view", "Security Alerts"),
    "dba_overview": CommandBriefRoute("DBA Control Room", "dba_control_room_active_view", "Morning Cockpit"),
    "dba_failures": CommandBriefRoute("DBA Control Room", "dba_control_room_active_view", "Failure Triage"),
    "dba_performance": CommandBriefRoute("DBA Control Room", "dba_control_room_active_view", "Performance Watch"),
    "workload_query_investigation": CommandBriefRoute(
        "Workload Operations",
        "workload_operations_workflow",
        "Query Investigation",
    ),
    "workload_pipeline_tasks": CommandBriefRoute(
        "Workload Operations",
        "workload_operations_workflow",
        "Pipeline & Task Health",
    ),
    "workload_change_analysis": CommandBriefRoute(
        "Workload Operations",
        "workload_operations_workflow",
        "Change Analysis",
    ),
    "workload_performance": CommandBriefRoute(
        "Workload Operations",
        "workload_operations_workflow",
        "Performance & Contention",
    ),
    "security_overview": CommandBriefRoute(
        "Security Monitoring",
        "security_posture_workflow",
        "Security Overview",
        (("security_posture_view", "Security Overview"),),
    ),
    "security_risky_grants": CommandBriefRoute(
        "Security Monitoring",
        "security_posture_workflow",
        "Risky Grants",
        (("security_posture_view", "Risky Grants"),),
    ),
    "security_access_changes": CommandBriefRoute(
        "Security Monitoring",
        "security_posture_workflow",
        "Access Changes",
        (("security_posture_view", "Access Changes"),),
    ),
    "security_alerts": CommandBriefRoute(
        "Security Monitoring",
        "security_posture_workflow",
        "Security Alerts",
        (("security_posture_view", "Security Alerts"),),
    ),
    "security_failed_logins": CommandBriefRoute(
        "Security Monitoring",
        "security_posture_workflow",
        "Failed Logins",
        (("security_posture_view", "Failed Logins"),),
    ),
}


def _valid_workflow(section: str, workflow: str) -> bool:
    if not workflow:
        return True
    return workflow in SECTION_WORKFLOW_CONTRACT.get(section, ())


def apply_command_brief_route(route_key: str) -> bool:
    """Apply an allowlisted command-brief route after section defaults are queued."""
    key = str(route_key or "").strip()
    route = COMMAND_BRIEF_ROUTES.get(key)
    if route is None:
        LOGGER.warning("Rejected unknown command brief route key: %s", key)
        return False
    if not _valid_workflow(route.section, route.workflow):
        LOGGER.warning("Rejected invalid command brief route target: %s -> %s", key, route.workflow)
        return False
    queue_section_navigation(route.section)
    if route.workflow_key and route.workflow:
        st.session_state[route.workflow_key] = route.workflow
    if route.section == "Alert Center" and route.workflow:
        st.session_state["alert_center_requested_view"] = route.workflow
    for state_key, state_value in route.state_updates:
        st.session_state[state_key] = state_value
    return True


__all__ = ["COMMAND_BRIEF_ROUTES", "CommandBriefRoute", "apply_command_brief_route"]
