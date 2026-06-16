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
    "OWNER_EMAIL",
    "ONCALL_PRIMARY",
    "ONCALL_SECONDARY",
    "ESCALATION_TARGET",
    "DEFAULT_ROUTE",
    "SERVICE_TIER",
    "OWNER_SOURCE",
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


def _oncall_default(owner_value: str) -> str:
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
        or _row_value(row, "OWNER", "ROUTED_OWNER", "ESCALATION_TARGET", default="DBA On-Call")
    )
    escalation = _row_value(row, "ESCALATION_TARGET", "ALERT_ROUTE", default=owner_value)
    route = _text(default_route) or _row_value(row, "DEFAULT_ROUTE", "NEXT_WORKFLOW", default="Monitoring")
    return {
        "OWNER": owner_value,
        "OWNER_EMAIL": _row_value(row, "OWNER_EMAIL", "EMAIL_TARGET"),
        "ONCALL_PRIMARY": _row_value(row, "ONCALL_PRIMARY", default=_oncall_default(owner_value)),
        "ONCALL_SECONDARY": _row_value(row, "ONCALL_SECONDARY"),
        "APPROVAL_GROUP": "",
        "ESCALATION_TARGET": escalation or owner_value,
        "DEFAULT_ROUTE": route,
        "SERVICE_TIER": _text(service_tier) or _row_value(row, "SERVICE_TIER", default="Monitor"),
        "OWNER_SOURCE": "MONITORING_CONTEXT",
        "OWNER_EVIDENCE": "Derived from the loaded telemetry row.",
        "MATCH_PRIORITY": 0,
    }
