"""Central route and legacy-alias registry for OVERWATCH.

Keep this module dependency-light so config, tests, and pure normalization
helpers can share route contracts without importing Streamlit sections.
"""
from __future__ import annotations


PRIMARY_SECTION_TITLES = (
    "Executive Landing",
    "DBA Control Room",
    "Alert Center",
    "Cost & Contract",
    "Workload Operations",
    "Security Monitoring",
)

ABANDONED_PRIMARY_SECTION_TITLES = (
    "Command Center",
    "Incidents",
    "Optimization",
    "Settings",
)

SECTION_WORKFLOW_CONTRACT = {
    "Executive Landing": (
        "Executive Overview",
        "Cost Movement",
        "Operational Risk",
        "Security Risk",
        "Change Summary",
        "Executive Actions",
        "Executive Admin / Advanced",
    ),
    "DBA Control Room": (
        "Morning Cockpit",
        "Failure Triage",
        "Cost Watch",
        "Performance Watch",
        "Change Watch",
        "Action Queue",
        "Control Room Admin / Advanced",
    ),
    "Alert Center": (
        "Active Alerts",
        "Critical / High",
        "Cost Alerts",
        "Cortex Predictive Alerts",
        "Reliability Alerts",
        "Security Alerts",
        "Alert History",
        "Alert Settings / Admin",
    ),
    "Cost & Contract": (
        "Cost Overview",
        "Cost Explorer",
        "Burn Rate & Forecast",
        "Budget vs Actual",
        "Chargeback / Company Split",
        "Cost Recommendations",
        "Cortex AI",
        "Waste Detection",
    ),
    "Workload Operations": (
        "Workload Overview",
        "Query Investigation",
        "Pipeline & Task Health",
        "Performance & Contention",
        "Change Analysis",
        "Advanced DBA Tools",
    ),
    "Security Monitoring": (
        "Security Overview",
        "Failed Logins",
        "Risky Grants",
        "Privilege Sprawl",
        "Access Changes",
        "Data Sharing Exposure",
        "Security Alerts",
        "Security Admin / Advanced",
    ),
}

DEFAULT_WORKFLOW_BY_SECTION = {
    section: workflows[0]
    for section, workflows in SECTION_WORKFLOW_CONTRACT.items()
}

LEGACY_SECTION_ALIASES = {
    "Executive Briefing": "Executive Landing",
    "Query Workbench": "Workload Operations",
    "Live Monitor": "Workload Operations",
    "Detailed Diagnosis": "Workload Operations",
    "Query Analysis": "Workload Operations",
    "Query Search & History": "Workload Operations",
    "Task Management": "Workload Operations",
    "Pipeline Health": "Workload Operations",
    "Stored Proc Tracker": "Workload Operations",
    "Object Change Monitor": "Workload Operations",
    "Schema Compare": "Workload Operations",
    "Data Compare": "Workload Operations",
    "Cost Center": "Cost & Contract",
    "Credit Contract": "Cost & Contract",
    "Recommendations": "Cost & Contract",
    "Recommendations & Anomalies": "Cost & Contract",
    "Cortex Monitor": "Cost & Contract",
    "AI & Cortex Monitor": "Cost & Contract",
    "SPCS Tracker": "Cost & Contract",
    "Usage Overview": "DBA Control Room",
    "Service Health": "DBA Control Room",
    "Fast Watch": "DBA Control Room",
    "Morning Brief": "DBA Control Room",
    "Alerts": "Alert Center",
    "Alert History": "Alert Center",
    "Alert Configuration": "Alert Center",
    "Adoption Analytics": "Executive Landing",
    "Storage Monitor": "Cost & Contract",
    "Security Posture": "Security Monitoring",
    "Security & Access": "Security Monitoring",
    "Data Sharing": "Security Monitoring",
    "Failed Logins": "Security Monitoring",
    "Access posture": "Security Monitoring",
    "Access Posture": "Security Monitoring",
    "Command Center": "DBA Control Room",
    "Warehouse Health": "Cost & Contract",
    "Optimization": "Cost & Contract",
}

RETIRED_SECTION_ALIASES = {
    "Account Health": "DBA Control Room",
    "Warehouse Health": "Cost & Contract",
    "Security Posture": "Security Monitoring",
}

SECTION_ROUTE_STATE = {
    "Executive Landing": {"executive_landing_workflow": "Executive Overview"},
    "Executive Briefing": {"executive_landing_workflow": "Executive Overview"},
    "Adoption Analytics": {"executive_landing_workflow": "Executive Admin / Advanced"},
    "DBA Control Room": {"dba_control_room_active_view": "Morning Cockpit"},
    "Account Health": {
        "dba_control_room_active_view": "Morning Cockpit",
        "_dba_control_room_full_workspace_requested": True,
        "_dba_control_room_brief_mode": False,
    },
    "Command Center": {"dba_control_room_active_view": "Morning Cockpit"},
    "Usage Overview": {"dba_control_room_active_view": "Cost Watch"},
    "Service Health": {"dba_control_room_active_view": "Control Room Admin / Advanced"},
    "Fast Watch": {"dba_control_room_active_view": "Morning Cockpit"},
    "Morning Brief": {"dba_control_room_active_view": "Morning Cockpit"},
    "Alert Center": {"alert_center_active_view": "Active Alerts"},
    "Alerts": {"alert_center_active_view": "Active Alerts"},
    "Alert History": {"alert_center_active_view": "Alert History"},
    "Alert Configuration": {
        "alert_center_active_view": "Alert Settings / Admin",
        "alert_center_admin_view": "Delivery & Automation",
    },
    "Cost & Contract": {"cost_contract_workflow": "Cost Overview"},
    "Warehouse Health": {
        "cost_contract_workflow": "Waste Detection",
        "_cost_contract_full_workspace_requested": True,
        "_cost_contract_brief_mode": False,
    },
    "Optimization": {
        "cost_contract_workflow": "Cost Recommendations",
        "_cost_contract_full_workspace_requested": True,
        "_cost_contract_brief_mode": False,
    },
    "Cost Center": {
        "cost_contract_workflow": "Cost Explorer",
        "cost_center_view": "Cost Explorer",
        "cc_explorer_lens": "Warehouse",
    },
    "Credit Contract": {"cost_contract_workflow": "Budget vs Actual"},
    "Recommendations & Anomalies": {"cost_contract_workflow": "Cost Recommendations"},
    "Recommendations": {"cost_contract_workflow": "Cost Recommendations"},
    "Cortex Monitor": {
        "cost_contract_workflow": "Cortex AI",
    },
    "AI & Cortex Monitor": {
        "cost_contract_workflow": "Cortex AI",
    },
    "Storage Monitor": {
        "cost_contract_workflow": "Cost Overview",
        "cost_contract_advanced_tool": "Storage & Retention",
        "_cost_contract_show_advanced_tools": True,
    },
    "SPCS Tracker": {
        "cost_contract_workflow": "Cost Overview",
        "cost_contract_advanced_tool": "SPCS Spend",
        "_cost_contract_show_advanced_tools": True,
    },
    "Workload Operations": {"workload_operations_workflow": "Workload Overview"},
    "Query Workbench": {"workload_operations_workflow": "Query Investigation"},
    "Query Analysis": {"workload_operations_workflow": "Query Investigation"},
    "Query Search & History": {
        "workload_operations_workflow": "Query Investigation",
        "query_analysis_active_view": "History Search",
    },
    "Detailed Diagnosis": {
        "workload_operations_workflow": "Query Investigation",
        "query_analysis_active_view": "Detailed Diagnosis",
    },
    "Live Monitor": {"workload_operations_workflow": "Performance & Contention"},
    "Task Management": {
        "workload_operations_workflow": "Pipeline & Task Health",
        "workload_operations_pipeline_focus": "Failed Tasks",
    },
    "Pipeline Health": {
        "workload_operations_workflow": "Pipeline & Task Health",
        "workload_operations_pipeline_focus": "Load Issues & SLA",
    },
    "Stored Proc Tracker": {
        "workload_operations_workflow": "Pipeline & Task Health",
        "workload_operations_pipeline_focus": "Failed Procedures",
    },
    "Object Change Monitor": {"workload_operations_workflow": "Change Analysis"},
    "Schema Compare": {
        "workload_operations_workflow": "Advanced DBA Tools",
        "dba_tools_focus": "Object Monitoring",
        "dba_tools_focus_tool": "Schema Compare",
        "dba_tools_group_selector": "Object Monitoring",
    },
    "Data Compare": {
        "workload_operations_workflow": "Advanced DBA Tools",
        "dba_tools_focus": "Object Monitoring",
        "dba_tools_focus_tool": "Data Compare",
        "dba_tools_group_selector": "Object Monitoring",
    },
    "Security Monitoring": {
        "security_posture_view": "Security Overview",
        "security_posture_workflow": "Security Overview",
    },
    "Security Posture": {
        "security_posture_view": "Security Overview",
        "security_posture_workflow": "Security Overview",
    },
    "Security & Access": {
        "security_posture_view": "Risky Grants",
        "security_posture_workflow": "Risky Grants",
    },
    "Data Sharing": {
        "security_posture_view": "Data Sharing Exposure",
        "security_posture_workflow": "Data Sharing Exposure",
    },
    "Failed Logins": {
        "security_posture_view": "Failed Logins",
        "security_posture_workflow": "Failed Logins",
    },
    "Access posture": {
        "security_posture_view": "Security Overview",
        "security_posture_workflow": "Security Overview",
    },
    "Access Posture": {
        "security_posture_view": "Security Overview",
        "security_posture_workflow": "Security Overview",
    },
}

WORKFLOW_ALIASES_BY_SECTION = {
    "Executive Landing": {
        "Executive Briefing": "Executive Overview",
        "Executive Summary": "Executive Overview",
        "Adoption Analytics": "Executive Admin / Advanced",
        "Executive Scorecard": "Executive Admin / Advanced",
        "Scorecard Formulas": "Executive Admin / Advanced",
        "Value Ledger": "Executive Admin / Advanced",
        "Production Readiness": "Executive Admin / Advanced",
        "Data Trust": "Executive Admin / Advanced",
        "Command Center": "Executive Overview",
        "Forecasting": "Cost Movement",
    },
    "Alert Center": {
        "Command Center": "Active Alerts",
        "Issue Inbox": "Active Alerts",
        "Triage Digest": "Active Alerts",
        "Alert History": "Alert History",
        "Alert Brief": "Active Alerts",
        "Control Health": "Alert Settings / Admin",
        "Cost": "Cost Alerts",
        "Spend": "Cost Alerts",
        "Cost / Cortex": "Cost Alerts",
        "Cost & Behavior": "Cost Alerts",
        "Cortex": "Cortex Predictive Alerts",
        "Cortex Predictive": "Cortex Predictive Alerts",
        "Cortex Predictive Alerts": "Cortex Predictive Alerts",
        "Critical": "Critical / High",
        "Critical / High": "Critical / High",
        "Workload": "Reliability Alerts",
        "Pipeline": "Reliability Alerts",
        "Reliability": "Reliability Alerts",
        "Security": "Security Alerts",
        "Email Delivery": "Alert Settings / Admin",
        "Action Queue Routing": "Alert Settings / Admin",
        "Delivery & Remediation": "Alert Settings / Admin",
        "Detection Catalog": "Alert Settings / Admin",
        "Delivery & Automation": "Alert Settings / Admin",
        "Suppression Windows": "Alert Settings / Admin",
        "Alert Configuration": "Alert Settings / Admin",
        "Alert Settings": "Alert Settings / Admin",
        "Advanced Alert Admin": "Alert Settings / Admin",
    },
    "Security Monitoring": {
        "Security Posture": "Security Overview",
        "Security & Access": "Risky Grants",
        "Access posture": "Security Overview",
        "Access Posture": "Security Overview",
        "Login Audit": "Failed Logins",
        "Login Posture": "Failed Logins",
        "Roles & Grants": "Risky Grants",
        "Privilege sprawl": "Privilege Sprawl",
        "Data Sharing": "Data Sharing Exposure",
        "Data sharing exposure": "Data Sharing Exposure",
        "Data Health": "Security Admin / Advanced",
        "Security Summary": "Security Alerts",
        "Object and access changes": "Access Changes",
        "Advanced Security Diagnostics": "Security Admin / Advanced",
        "Security Admin": "Security Admin / Advanced",
        "Advanced Security": "Security Admin / Advanced",
        "Raw Grants": "Security Admin / Advanced",
        "Role Readiness": "Security Admin / Advanced",
    },
}

SECTION_ALIASES = {
    **{section: section for section in PRIMARY_SECTION_TITLES},
    **LEGACY_SECTION_ALIASES,
    **RETIRED_SECTION_ALIASES,
}

LEGACY_ROUTE_CONTRACT = tuple(
    (route, SECTION_ALIASES.get(route, route), dict(SECTION_ROUTE_STATE.get(route, {})))
    for route in SECTION_ROUTE_STATE
)


def normalize_section_route(route: object) -> str:
    text = str(route or "").strip()
    return SECTION_ALIASES.get(text, text)


def compatibility_state_for_route(route: object) -> dict[str, object]:
    return dict(SECTION_ROUTE_STATE.get(str(route or "").strip(), {}))


def normalize_workflow_alias(section: str, workflow: object, *, default: str | None = None) -> str:
    text = str(workflow or "").strip()
    workflows = SECTION_WORKFLOW_CONTRACT.get(section, ())
    if text in workflows:
        return text
    aliases = WORKFLOW_ALIASES_BY_SECTION.get(section, {})
    if text in aliases:
        return aliases[text]
    return default if default is not None else DEFAULT_WORKFLOW_BY_SECTION.get(section, text)


__all__ = [
    "ABANDONED_PRIMARY_SECTION_TITLES",
    "DEFAULT_WORKFLOW_BY_SECTION",
    "LEGACY_ROUTE_CONTRACT",
    "LEGACY_SECTION_ALIASES",
    "PRIMARY_SECTION_TITLES",
    "RETIRED_SECTION_ALIASES",
    "SECTION_ALIASES",
    "SECTION_ROUTE_STATE",
    "SECTION_WORKFLOW_CONTRACT",
    "WORKFLOW_ALIASES_BY_SECTION",
    "compatibility_state_for_route",
    "normalize_section_route",
    "normalize_workflow_alias",
]
