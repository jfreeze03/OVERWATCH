"""Alert Center v2 inbox."""

from __future__ import annotations

from typing import Any

import pandas as pd

from overwatch_app.data.alert_actions import ALERT_STATUSES
from overwatch_app.sections._shared import section_header


ALERT_INBOX_COLUMNS = (
    "ALERT_ID",
    "SEVERITY",
    "STATUS",
    "ENTITY",
    "MESSAGE",
    "DELIVERY_STATUS",
    "ACK_AGE_MINUTES",
    "RESOLVE_AGE_MINUTES",
    "IS_OVERDUE",
    "SOURCE_FRESHNESS",
    "SOURCE_OBJECT",
    "SUGGESTED_ACTION",
    "TICKET_ID",
    "CLOSURE_STATUS",
)

ALERT_ACTIONS = tuple(ALERT_STATUSES)


def build_alert_detail(alert: dict[str, Any] | pd.Series) -> dict[str, Any]:
    return {
        "title": str(alert.get("TITLE") or alert.get("MESSAGE") or "Alert detail"),
        "severity": str(alert.get("SEVERITY") or ""),
        "status": str(alert.get("STATUS") or "OPEN"),
        "entity": str(alert.get("ENTITY") or alert.get("ENTITY_NAME") or ""),
        "message": str(alert.get("MESSAGE") or ""),
        "delivery_status": str(alert.get("DELIVERY_STATUS") or "Unknown"),
        "ack_age_minutes": alert.get("ACK_AGE_MINUTES", ""),
        "resolve_age_minutes": alert.get("RESOLVE_AGE_MINUTES", ""),
        "is_overdue": bool(alert.get("IS_OVERDUE", False)),
        "timeline": alert.get("TIMELINE", []),
        "source_freshness": str(alert.get("SOURCE_FRESHNESS") or "Precomputed alert mart"),
        "source_object": str(alert.get("SOURCE_OBJECT") or "MART_V2_ALERT_INTELLIGENCE"),
        "suggested_action": str(alert.get("SUGGESTED_ACTION") or ""),
        "ticket_id": str(alert.get("TICKET_ID") or ""),
        "notes": str(alert.get("NOTES") or ""),
        "related_work_item": str(alert.get("RELATED_WORK_ITEM") or ""),
        "verification_closure_status": str(alert.get("CLOSURE_STATUS") or ""),
    }


def build_alert_inbox(alerts: pd.DataFrame) -> pd.DataFrame:
    if alerts is None or alerts.empty:
        return pd.DataFrame(columns=ALERT_INBOX_COLUMNS)
    view = alerts.copy()
    for column in ALERT_INBOX_COLUMNS:
        if column not in view.columns:
            view[column] = ""
    return view[list(ALERT_INBOX_COLUMNS)]


def _severity_chip(severity: str) -> str:
    normalized = severity.strip().upper() or "UNKNOWN"
    colors = {
        "CRITICAL": "#ff5a5f",
        "HIGH": "#ffb020",
        "MEDIUM": "#4da3ff",
        "LOW": "#8bd17c",
    }
    color = colors.get(normalized, "#9aa4b2")
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:6px;'
        f'background:{color};color:#0b0f14;font-weight:700;font-size:12px;">'
        f'{normalized}</span>'
    )


def render_alert_detail_panel(st: Any, alert: dict[str, Any]) -> None:
    st.subheader(alert["title"])
    st.markdown(_severity_chip(alert["severity"]), unsafe_allow_html=True)
    left, right = st.columns(2)
    left.metric("Status", alert["status"])
    right.metric("Delivery", alert["delivery_status"])
    st.write(alert["message"])
    st.caption(f"Entity: {alert['entity']}")
    st.write(alert["suggested_action"])
    age_left, age_right, overdue_col = st.columns(3)
    age_left.metric("ACK age", alert["ack_age_minutes"] or "-")
    age_right.metric("Resolve age", alert["resolve_age_minutes"] or "-")
    overdue_col.metric("SLA", "Overdue" if alert["is_overdue"] else "Within SLA")
    st.caption(f"Source: {alert['source_object']} - {alert['source_freshness']}")
    if alert["ticket_id"]:
        st.caption(f"Ticket: {alert['ticket_id']}")
    if alert["verification_closure_status"]:
        st.caption(f"Closure: {alert['verification_closure_status']}")


def render_alert_inbox(alerts: pd.DataFrame | None = None) -> None:
    import streamlit as st

    section_header(st, "Alert Center", "active")
    inbox = build_alert_inbox(alerts if alerts is not None else pd.DataFrame())
    st.dataframe(inbox, hide_index=True)
    if not inbox.empty:
        label_column = "ALERT_ID" if "ALERT_ID" in inbox.columns else "MESSAGE"
        selected = st.selectbox("Alert", list(inbox[label_column].astype(str)), index=0)
        row = inbox[inbox[label_column].astype(str) == selected].iloc[0]
        render_alert_detail_panel(st, build_alert_detail(row))
