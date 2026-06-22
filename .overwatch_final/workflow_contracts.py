"""Central workflow and legacy-route contracts for OVERWATCH regression tests.

The app still owns actual rendering and navigation behavior. This module is a
small test/regression contract so route tests, smoke runners, and live
Snowflake probes do not each maintain their own copy of the six-section model.
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
        "Cost Alerts",
        "Reliability Alerts",
        "Security Alerts",
        "Alert History",
        "Alert Settings / Admin",
    ),
    "Cost & Contract": (
        "Cost Overview",
        "Cost by Warehouse",
        "Cost by User / Role",
        "Burn Rate & Forecast",
        "Budget vs Actual",
        "Waste Detection",
        "Chargeback / Company Split",
        "Cost Recommendations",
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

LEGACY_ROUTE_CONTRACT = (
    ("Executive Landing", "Executive Landing", {"executive_landing_workflow": "Executive Overview"}),
    ("Executive Briefing", "Executive Landing", {"executive_landing_workflow": "Executive Overview"}),
    ("Adoption Analytics", "Executive Landing", {"executive_landing_workflow": "Executive Admin / Advanced"}),
    ("DBA Control Room", "DBA Control Room", {"dba_control_room_active_view": "Morning Cockpit"}),
    ("Command Center", "DBA Control Room", {"dba_control_room_active_view": "Morning Cockpit"}),
    ("Account Health", "DBA Control Room", {"dba_control_room_active_view": "Morning Cockpit"}),
    ("Usage Overview", "DBA Control Room", {"dba_control_room_active_view": "Cost Watch"}),
    ("Service Health", "DBA Control Room", {"dba_control_room_active_view": "Control Room Admin / Advanced"}),
    ("Fast Watch", "DBA Control Room", {"dba_control_room_active_view": "Morning Cockpit"}),
    ("Morning Brief", "DBA Control Room", {"dba_control_room_active_view": "Morning Cockpit"}),
    ("Alert Center", "Alert Center", {"alert_center_active_view": "Active Alerts"}),
    ("Alerts", "Alert Center", {"alert_center_active_view": "Active Alerts"}),
    ("Alert History", "Alert Center", {"alert_center_active_view": "Alert History"}),
    (
        "Alert Configuration",
        "Alert Center",
        {"alert_center_active_view": "Alert Settings / Admin", "alert_center_admin_view": "Delivery & Automation"},
    ),
    ("Cost & Contract", "Cost & Contract", {"cost_contract_workflow": "Cost Overview"}),
    ("Cost Center", "Cost & Contract", {"cost_contract_workflow": "Cost by Warehouse"}),
    ("Credit Contract", "Cost & Contract", {"cost_contract_workflow": "Budget vs Actual"}),
    ("Warehouse Health", "Cost & Contract", {"cost_contract_workflow": "Waste Detection"}),
    ("Recommendations", "Cost & Contract", {"cost_contract_workflow": "Cost Recommendations"}),
    ("Recommendations & Anomalies", "Cost & Contract", {"cost_contract_workflow": "Cost Recommendations"}),
    (
        "Cortex Monitor",
        "Cost & Contract",
        {
            "cost_contract_workflow": "Cost Overview",
            "cost_contract_advanced_tool": "Cortex Spend",
            "_cost_contract_show_advanced_tools": True,
        },
    ),
    (
        "Storage Monitor",
        "Cost & Contract",
        {
            "cost_contract_workflow": "Cost Overview",
            "cost_contract_advanced_tool": "Storage & Retention",
            "_cost_contract_show_advanced_tools": True,
        },
    ),
    (
        "SPCS Tracker",
        "Cost & Contract",
        {
            "cost_contract_workflow": "Cost Overview",
            "cost_contract_advanced_tool": "SPCS Spend",
            "_cost_contract_show_advanced_tools": True,
        },
    ),
    ("Workload Operations", "Workload Operations", {"workload_operations_workflow": "Workload Overview"}),
    ("Query Analysis", "Workload Operations", {"workload_operations_workflow": "Query Investigation"}),
    ("Query Workbench", "Workload Operations", {"workload_operations_workflow": "Query Investigation"}),
    (
        "Query Search & History",
        "Workload Operations",
        {"workload_operations_workflow": "Query Investigation", "query_analysis_active_view": "History Search"},
    ),
    (
        "Detailed Diagnosis",
        "Workload Operations",
        {"workload_operations_workflow": "Query Investigation", "query_analysis_active_view": "Detailed Diagnosis"},
    ),
    (
        "Task Management",
        "Workload Operations",
        {"workload_operations_workflow": "Pipeline & Task Health", "workload_operations_pipeline_focus": "Failed Tasks"},
    ),
    (
        "Pipeline Health",
        "Workload Operations",
        {
            "workload_operations_workflow": "Pipeline & Task Health",
            "workload_operations_pipeline_focus": "Load Issues & SLA",
        },
    ),
    (
        "Stored Proc Tracker",
        "Workload Operations",
        {
            "workload_operations_workflow": "Pipeline & Task Health",
            "workload_operations_pipeline_focus": "Failed Procedures",
        },
    ),
    ("Object Change Monitor", "Workload Operations", {"workload_operations_workflow": "Change Analysis"}),
    (
        "Schema Compare",
        "Workload Operations",
        {
            "workload_operations_workflow": "Advanced DBA Tools",
            "dba_tools_focus": "Object Monitoring",
            "dba_tools_focus_tool": "Schema Compare",
        },
    ),
    (
        "Data Compare",
        "Workload Operations",
        {
            "workload_operations_workflow": "Advanced DBA Tools",
            "dba_tools_focus": "Object Monitoring",
            "dba_tools_focus_tool": "Data Compare",
        },
    ),
    (
        "Security Monitoring",
        "Security Monitoring",
        {"security_posture_view": "Security Overview", "security_posture_workflow": "Security Overview"},
    ),
    (
        "Security Posture",
        "Security Monitoring",
        {"security_posture_view": "Security Overview", "security_posture_workflow": "Security Overview"},
    ),
    (
        "Security & Access",
        "Security Monitoring",
        {"security_posture_view": "Risky Grants", "security_posture_workflow": "Risky Grants"},
    ),
    (
        "Data Sharing",
        "Security Monitoring",
        {"security_posture_view": "Data Sharing Exposure", "security_posture_workflow": "Data Sharing Exposure"},
    ),
    (
        "Failed Logins",
        "Security Monitoring",
        {"security_posture_view": "Failed Logins", "security_posture_workflow": "Failed Logins"},
    ),
    (
        "Access posture",
        "Security Monitoring",
        {"security_posture_view": "Security Overview", "security_posture_workflow": "Security Overview"},
    ),
)

