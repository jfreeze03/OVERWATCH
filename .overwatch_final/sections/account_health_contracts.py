"""Account Health workflow contracts and stable source identifiers."""
from __future__ import annotations


CHECKLIST_HISTORY_TABLE = "OVERWATCH_DBA_CHECKLIST_HISTORY"
ACCOUNT_HEALTH_OPERABILITY_FACT_TABLE = "FACT_ACCOUNT_HEALTH_OPERABILITY_DAILY"
ACCOUNT_HEALTH_ACTION_SOURCE = "Account Health - Daily DBA Checklist"
ACCOUNT_HEALTH_ACCESS_HYGIENE_SOURCE = "Account Health - Account Access Hygiene"
ACCOUNT_HEALTH_PANES = (
    "Overview",
    "Morning Report",
)
ACCOUNT_HEALTH_PANE_LABELS = {
    "Overview": "Health Workspace",
    "Morning Report": "DBA Daily Brief",
}
ACCOUNT_HEALTH_PANE_DETAILS = {
    "Overview": "Daily account cockpit: checklist state, source readiness, exception signals, and escalation routes.",
    "Morning Report": "Copy-ready DBA morning packet built from Control Room blockers, handoff rows, and route status.",
}
ACCOUNT_HEALTH_SCOPE_FILTER_KEYS = (
    "global_start_date",
    "global_end_date",
    "global_warehouse",
    "global_user",
    "global_role",
    "global_database",
)


__all__ = [
    "ACCOUNT_HEALTH_ACCESS_HYGIENE_SOURCE",
    "ACCOUNT_HEALTH_ACTION_SOURCE",
    "ACCOUNT_HEALTH_OPERABILITY_FACT_TABLE",
    "ACCOUNT_HEALTH_PANES",
    "ACCOUNT_HEALTH_PANE_DETAILS",
    "ACCOUNT_HEALTH_PANE_LABELS",
    "ACCOUNT_HEALTH_SCOPE_FILTER_KEYS",
    "CHECKLIST_HISTORY_TABLE",
]
