"""Shared alert status and severity normalization contracts.

The triage/action-queue normalizer preserves operational status labels found
in OVERWATCH_ALERTS. The command-center normalizer intentionally collapses
unknown values to ``New`` because those rows feed lifecycle event inserts.
Keep both behaviors explicit until the downstream SQL contracts are unified.
"""
from __future__ import annotations

from typing import Any


ALERT_OPEN_STATUSES = {
    "NEW",
    "OPEN",
    "ACTIVE",
    "ACKNOWLEDGED",
    "IN PROGRESS",
    "IN_PROGRESS",
    "EMAIL_READY",
    "EMAIL_QUEUED",
    "PENDING",
}
ALERT_CLOSED_STATUSES = {"FIXED", "IGNORED", "RESOLVED"}
ALERT_STATUS_CHOICES = ("Acknowledged", "In Progress", "Fixed", "Ignored")
ALERT_SLA_HOURS = {
    "Critical": 4,
    "High": 8,
    "Medium": 24,
    "Low": 72,
}
ALERT_SEVERITY_RANKS = {
    "Critical": 0,
    "High": 1,
    "Medium": 2,
    "Low": 3,
}


def normalize_alert_severity(value: Any) -> str:
    severity = str(value or "Medium").strip().title()
    if severity.upper() == "CRITICAL":
        return "Critical"
    if severity.upper() == "HIGH":
        return "High"
    if severity.upper() == "LOW":
        return "Low"
    return "Medium"


def normalize_alert_status(value: Any) -> str:
    status = str(value or "New").strip().replace("_", " ").title()
    if status.upper() in {"CONFIG REQUIRED", "CONFIG_REQUIRED"}:
        return "Config Required"
    if status.upper() in {"EMAIL READY", "EMAIL_READY"}:
        return "Email Ready"
    if status.upper() in {"EMAIL QUEUED", "EMAIL_QUEUED"}:
        return "Email Queued"
    if status.upper() in {"IN PROGRESS", "IN_PROGRESS"}:
        return "In Progress"
    if status.upper() in {"RESOLVED", "FIXED"}:
        return "Fixed"
    if status.upper() == "IGNORED":
        return "Ignored"
    if not status:
        return "New"
    return status


def normalize_command_center_alert_status(value: Any) -> str:
    status = str(value or "New").strip().replace("_", " ").title()
    if status.upper() in {"IN PROGRESS", "IN-PROGRESS"}:
        return "In Progress"
    if status.upper() == "EMAIL READY":
        return "Email Ready"
    if status.upper() == "EMAIL QUEUED":
        return "Email Queued"
    if status.upper() in {"FIXED", "RESOLVED"}:
        return "Fixed"
    if status.upper() in {"IGNORED", "SUPPRESSED"}:
        return "Ignored"
    if status.upper() == "ACKNOWLEDGED":
        return "Acknowledged"
    return "New"


def alert_severity_rank(value: Any) -> int:
    return ALERT_SEVERITY_RANKS.get(normalize_alert_severity(value), 4)
