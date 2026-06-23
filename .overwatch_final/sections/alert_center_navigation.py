"""Alert Center route normalization and source-summary helpers."""

from __future__ import annotations

from sections.alert_center_contracts import (
    ALERT_CENTER_ADMIN_VIEWS,
    ALERT_CENTER_DEFAULT_VIEW,
    ALERT_CENTER_PANES,
    ALERT_CENTER_SOURCES_BY_PANE,
    ALERT_CENTER_SOURCE_PLAN,
)
from route_registry import normalize_workflow_alias


def _normalize_alert_center_view(view: object) -> str:
    return normalize_workflow_alias(
        "Alert Center",
        view,
        default=ALERT_CENTER_DEFAULT_VIEW,
    )


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
