"""Lightweight routing context for monitoring rows.

This module intentionally does not maintain a static routing directory or
approval register. It only keeps existing operational boards from breaking
when they need a compact escalation label for an alert, task, procedure, or
warehouse.
"""
from __future__ import annotations

from typing import Any


OWNER_CONTEXT_COLUMNS = (
    "OWNER",
    "ROUTE_EMAIL",
    "ROUTE_EMAIL",
    "REVIEW_PRIMARY",
    "REVIEW_SECONDARY",
    "REVIEW_TARGET",
    "DEFAULT_ROUTE",
    "SERVICE_TIER",
    "ROUTE_SOURCE",
)


def _text(value: Any, default: str = "") -> str:
    text = str(value if value is not None else "").strip()
    return text or default


def _row_value(row: Any, *names: str, default: str = "") -> str:
    for name in names:
        try:
            value = row.get(name)
        except Exception:
            value = None
        text = _text(value)
        if text:
            return text
    return default


def _review_default(owner_value: str) -> str:
    upper = _text(owner_value).upper()
    if not upper or "OWNER" in upper or upper.endswith(" ROUTE") or " ROUTE /" in upper or "/ " in upper:
        return ""
    return owner_value


def resolve_owner_context(
    row: Any = None,
    *,
    directory: Any = None,
    entity: str = "",
    entity_type: str = "",
    owner: str = "",
    category: str = "",
    alert_type: str = "",
    default_route: str = "",
    service_tier: str = "",
    **_: Any,
) -> dict[str, str]:
    """Return generic monitoring escalation context without directory lookup."""
    _ = directory, entity, entity_type, category, alert_type
    row = row if row is not None else {}
    owner_value = (
        _text(owner)
        or _row_value(row, "OWNER", "ROUTED_OWNER", "REVIEW_TARGET", default="DBA Review")
    )
    escalation = _row_value(row, "REVIEW_TARGET", "ALERT_ROUTE", default=owner_value)
    route = _text(default_route) or _row_value(row, "DEFAULT_ROUTE", "NEXT_WORKFLOW", default="Monitoring")
    return {
        "OWNER": owner_value,
        "ROUTE_EMAIL": _row_value(row, "ROUTE_EMAIL", "ROUTE_EMAIL", "EMAIL_TARGET"),
        "ROUTE_EMAIL": _row_value(row, "ROUTE_EMAIL", "ROUTE_EMAIL", "EMAIL_TARGET"),
        "REVIEW_PRIMARY": _row_value(row, "REVIEW_PRIMARY", default=_review_default(owner_value)),
        "REVIEW_SECONDARY": _row_value(row, "REVIEW_SECONDARY"),
        "REVIEW_GROUP": "",
        "REVIEW_TARGET": escalation or owner_value,
        "DEFAULT_ROUTE": route,
        "SERVICE_TIER": _text(service_tier) or _row_value(row, "SERVICE_TIER", default="Monitor"),
        "ROUTE_SOURCE": "MONITORING_CONTEXT",
        "ROUTE_EVIDENCE": "Derived from the loaded telemetry row.",
        "MATCH_PRIORITY": 0,
    }
