"""Alert Center route normalization and source-summary helpers."""

from __future__ import annotations

from sections.alert_center_contracts import (
    ALERT_CENTER_ADMIN_VIEWS,
    ALERT_CENTER_DEFAULT_VIEW,
    ALERT_CENTER_PANES,
    ALERT_CENTER_SOURCES_BY_PANE,
    ALERT_CENTER_SOURCE_PLAN,
)


def _normalize_alert_center_view(view: object) -> str:
    normalized = str(view or "")
    aliases = {
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
        "Cortex": "Cost Alerts",
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
    }
    if normalized in aliases:
        return aliases[normalized]
    if normalized in {"Alert Brief", "Control Health"}:
        return ALERT_CENTER_DEFAULT_VIEW
    return normalized if normalized in ALERT_CENTER_PANES else ALERT_CENTER_DEFAULT_VIEW


def _alert_admin_view_for_route(view: object) -> str:
    raw = str(view or "").strip()
    if raw in ALERT_CENTER_ADMIN_VIEWS:
        return raw
    if raw in {"Alert Configuration", "Alert Settings", "Alert Settings / Admin", "Advanced Alert Admin", "Control Health"}:
        return "Delivery & Automation"
    if raw in {"Email Delivery", "Action Queue Routing", "Delivery & Remediation"}:
        return "Delivery & Automation"
    return ""


def _alert_center_sources_for_view(view: str) -> set[str]:
    if view in ALERT_CENTER_SOURCES_BY_PANE:
        return set(ALERT_CENTER_SOURCES_BY_PANE[view])
    return set(ALERT_CENTER_SOURCES_BY_PANE.get(_normalize_alert_center_view(view), {"alerts"}))


def _alert_center_source_summary(sources: set[str]) -> str:
    names = [
        str(ALERT_CENTER_SOURCE_PLAN[source]["SOURCE"]).replace("sources", "inputs").replace("Sources", "Inputs")
        for source in sorted(sources)
        if source in ALERT_CENTER_SOURCE_PLAN
    ]
    return ", ".join(names) if names else "No Snowflake inputs"


__all__ = [
    "_alert_admin_view_for_route",
    "_alert_center_source_summary",
    "_alert_center_sources_for_view",
    "_normalize_alert_center_view",
]
