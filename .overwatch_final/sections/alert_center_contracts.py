"""Alert Center pane contracts and source-plan metadata."""

from __future__ import annotations

import streamlit as st


_DEFERRED_NOTES_PREFIX = "_overwatch_deferred_section_notes"


def _deferred_notes_key(section: str) -> str:
    safe_section = str(section or "section").strip() or "section"
    return f"{_DEFERRED_NOTES_PREFIX}:{safe_section}"


def defer_source_note(*parts: object, section: str | None = None) -> None:
    """Collect Alert Center source notes without importing the full playbook module on first paint."""
    clean_parts = [
        " ".join(str(part or "").split())
        for part in parts
        if str(part or "").strip()
    ]
    if not clean_parts:
        return
    active_section = section or st.session_state.get("_overwatch_active_section", "")
    key = _deferred_notes_key(active_section)
    clean_note = " | ".join(clean_parts)
    notes = list(st.session_state.get(key, []))
    if clean_note not in notes:
        notes.append(clean_note)
    st.session_state[key] = notes


ALERT_CENTER_PANES = [
    "Active Alerts",
    "Critical / High",
    "Cost Alerts",
    "Cortex Predictive Alerts",
    "Reliability Alerts",
    "Security Alerts",
    "Alert History",
    "Alert Settings / Admin",
]

ALERT_CENTER_PANE_LABELS = {
    "Active Alerts": "Active",
    "Critical / High": "Critical / High",
    "Cost Alerts": "Cost",
    "Cortex Predictive Alerts": "Cortex Predictive",
    "Reliability Alerts": "Reliability",
    "Security Alerts": "Security",
    "Alert History": "History",
    "Alert Settings / Admin": "Admin",
}

ALERT_CENTER_BRIEF_FIRST_VERSION = 3
ALERT_CENTER_DEFAULT_VIEW = "Active Alerts"
ALERT_CENTER_ADMIN_VIEW_KEY = "alert_center_admin_view"
ALERT_CENTER_ADMIN_VIEWS = ("Detection Catalog", "Delivery & Automation", "Suppression Windows")
ALERT_CENTER_ADMIN_VIEW_DETAILS = {
    "Detection Catalog": "Alert rule coverage, thresholds, and Snowflake-native signal inputs.",
    "Delivery & Automation": "Email delivery, routing, action queue status, remediation logs, and dry-run evidence.",
    "Suppression Windows": "Maintenance annotations and temporary suppression windows.",
}

ALERT_CENTER_BRIEF_WORKFLOWS = (
    {
        "VIEW": "Active Alerts",
        "BUTTON_LABEL": "Open Active Alerts",
        "DBA_MOVE": "Start with severity, SLA, route, queue, and notification risk in one place.",
        "WHEN": "First look, shift start, incident review",
    },
    {
        "VIEW": "Cost Alerts",
        "BUTTON_LABEL": "Open Cost Alerts",
        "DBA_MOVE": "Focus on spend spikes, Cortex growth, warehouse cost behavior, and user-driven spend anomalies.",
        "WHEN": "Cost anomaly, AI spend review, contract burn concern",
    },
    {
        "VIEW": "Reliability Alerts",
        "BUTTON_LABEL": "Open Reliability Alerts",
        "DBA_MOVE": "Focus on query, task, pipeline, procedure, copy/load, and freshness risk.",
        "WHEN": "Production incident, workload health, SLA review",
    },
    {
        "VIEW": "Security Alerts",
        "BUTTON_LABEL": "Open Security Alerts",
        "DBA_MOVE": "Focus on login, privilege, role, export, sharing, and access-control risk.",
        "WHEN": "Security triage, audit review, access anomaly",
    },
    {
        "VIEW": "Alert History",
        "BUTTON_LABEL": "Open Alert History",
        "DBA_MOVE": "Review acknowledged, closed, recurring, and trend rows without mixing them into active triage.",
        "WHEN": "Recurring issue review, closure audit, export",
    },
    {
        "VIEW": "Alert Settings / Admin",
        "BUTTON_LABEL": "Open Alert Settings",
        "DBA_MOVE": "Review thresholds, delivery config, suppression windows, routing rules, native alerts, and dry-run evidence.",
        "WHEN": "Catalog tuning, notification audit, suppression cleanup",
    },
)

ALERT_CENTER_SOURCES_BY_PANE = {
    "Active Alerts": {"alerts", "action_queue", "delivery_log", "rules"},
    "Critical / High": {"alerts", "action_queue", "delivery_log", "rules"},
    "Cost Alerts": {"alerts", "action_queue", "rules"},
    "Cortex Predictive Alerts": {"alerts", "action_queue", "rules"},
    "Reliability Alerts": {"alerts", "action_queue", "rules"},
    "Security Alerts": {"alerts", "action_queue", "rules"},
    "Alert History": {"alerts", "action_queue", "delivery_log"},
    "Alert Settings / Admin": set(),
    "Advanced Alert Admin": set(),
    "Detection Catalog": set(),
    "Delivery & Automation": {
        "alerts",
        "action_queue",
        "delivery_log",
        "rules",
        "native_registry",
        "remediation_policy",
        "remediation_dry_run",
    },
    "Suppression Windows": set(),
}

ALERT_CENTER_SOURCE_PLAN = {
    "alerts": {
        "SOURCE": "Alert history",
        "OBJECT": "Alert triage view",
        "WHY": "Open issues, SLA state, email-ready rows",
        "COST_GUARDRAIL": "Bounded by selected window and row limit",
    },
    "action_queue": {
        "SOURCE": "Action queue",
        "OBJECT": "Persistent DBA action queue",
        "WHY": "Route, ticket, due date, and status tracking",
        "COST_GUARDRAIL": "Limited queue read",
    },
    "delivery_log": {
        "SOURCE": "Email delivery audit",
        "OBJECT": "Alert delivery log",
        "WHY": "Notification telemetry and escalation audit",
        "COST_GUARDRAIL": "Recent-window audit read",
    },
    "rules": {
        "SOURCE": "Rule catalog",
        "OBJECT": "Alert rules",
        "WHY": "Severity, SLA, route, and runbook control",
        "COST_GUARDRAIL": "Small configuration read",
    },
    "native_registry": {
        "SOURCE": "Native alert registry",
        "OBJECT": "Reviewed Snowflake ALERT candidates",
        "WHY": "Shows what native detections exist, are candidates, or are enabled",
        "COST_GUARDRAIL": "Small registry table read",
    },
    "remediation_policy": {
        "SOURCE": "Remediation policy",
        "OBJECT": "Review-only automation policy catalog",
        "WHY": "Shows whether any alert class is eligible for dry-run or auto mode",
        "COST_GUARDRAIL": "Small policy table read",
    },
    "remediation_dry_run": {
        "SOURCE": "Remediation dry-runs",
        "OBJECT": "Dry-run audit log",
        "WHY": "Shows proposed actions and blockers before any automation is allowed",
        "COST_GUARDRAIL": "Recent-window audit read",
    },
}


__all__ = [
    "ALERT_CENTER_ADMIN_VIEW_DETAILS",
    "ALERT_CENTER_ADMIN_VIEW_KEY",
    "ALERT_CENTER_ADMIN_VIEWS",
    "ALERT_CENTER_BRIEF_FIRST_VERSION",
    "ALERT_CENTER_BRIEF_WORKFLOWS",
    "ALERT_CENTER_DEFAULT_VIEW",
    "ALERT_CENTER_PANES",
    "ALERT_CENTER_PANE_LABELS",
    "ALERT_CENTER_SOURCES_BY_PANE",
    "ALERT_CENTER_SOURCE_PLAN",
    "_deferred_notes_key",
    "defer_source_note",
]
