"""Mission Control risk queue built only from already-loaded session evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape as _escape_markup
from typing import Any

import streamlit as st

from sections.shell_helpers import _clean_display_text
from utils.primitives import safe_float, safe_int


_SEVERITY_RANK = {
    "CRITICAL": 0,
    "HIGH": 1,
    "ELEVATED": 2,
    "WATCH": 3,
    "READY": 4,
    "ON DEMAND": 5,
}


def _pd():
    import pandas as pd

    return pd


def _frame(value: object):
    pd = _pd()
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _first_row(frame):
    return frame.iloc[0] if getattr(frame, "empty", True) is False else {}


def _severity_text(value: object) -> str:
    text = str(value or "Watch").strip().upper()
    if text in {"CRITICAL", "HIGH", "ELEVATED", "WATCH", "READY"}:
        return text.title()
    return "Watch"


def _queue_item(
    *,
    section: str,
    severity: str,
    signal: str,
    evidence: str,
    next_action: str,
    freshness: str,
) -> dict[str, str]:
    return {
        "section": _clean_display_text(section),
        "severity": _severity_text(severity),
        "signal": _clean_display_text(signal),
        "evidence": _clean_display_text(evidence),
        "next_action": _clean_display_text(next_action),
        "freshness": _clean_display_text(freshness),
    }


def build_mission_control_items(
    state: Mapping[str, Any],
    *,
    company: str,
    environment: str,
) -> tuple[dict[str, str], ...]:
    """Return cross-section risk rows without starting Snowflake work."""
    items: list[dict[str, str]] = []

    alert_data = state.get("alert_center_data")
    if isinstance(alert_data, dict):
        alerts = _frame(alert_data.get("alerts"))
        queue = _frame(alert_data.get("action_queue"))
        open_alerts = alerts
        if not alerts.empty and "STATUS" in alerts.columns:
            status = alerts["STATUS"].fillna("").astype(str).str.title()
            open_alerts = alerts[~status.isin(["Fixed", "Ignored", "Closed", "Resolved"])]
        severity = (
            open_alerts.get("SEVERITY", _pd().Series(dtype=str)).fillna("").astype(str).str.upper()
            if not open_alerts.empty
            else _pd().Series(dtype=str)
        )
        critical_high = safe_int(severity.isin(["CRITICAL", "HIGH"]).sum())
        overdue = 0
        if not open_alerts.empty and "SLA_STATE" in open_alerts.columns:
            overdue = safe_int(open_alerts["SLA_STATE"].fillna("").astype(str).str.upper().eq("OVERDUE").sum())
        if critical_high or overdue or not open_alerts.empty:
            items.append(_queue_item(
                section="Alert Center",
                severity="Critical" if critical_high else "High" if overdue else "Watch",
                signal=f"{critical_high:,} critical/high alerts; {overdue:,} overdue",
                evidence=f"{len(open_alerts):,} open alert row(s), {len(queue):,} action queue row(s)",
                next_action="Open Active Alerts and route the highest severity lane.",
                freshness=str((alert_data.get("_freshness_meta") or {}).get("loaded_at") or "Loaded alert session"),
            ))

    cost = _frame(state.get("cost_contract_cockpit"))
    cost_meta = state.get("cost_contract_cockpit_meta") if isinstance(state.get("cost_contract_cockpit_meta"), dict) else {}
    if not cost.empty:
        row = _first_row(cost)
        current = safe_float(row.get("CURRENT_CREDITS", 0))
        prior = safe_float(row.get("PRIOR_CREDITS", 0))
        delta_pct = ((current - prior) / prior * 100.0) if prior > 0 else 0.0
        top_wh = str(row.get("TOP_INCREASE_WAREHOUSE") or "No warehouse spike")
        items.append(_queue_item(
            section="Cost & Contract",
            severity="High" if delta_pct >= 25 else "Elevated" if delta_pct >= 10 else "Watch",
            signal=f"Spend movement {delta_pct:+.1f}%",
            evidence=f"Top driver: {top_wh}",
            next_action="Refresh Cost or open Cost by Warehouse for attribution.",
            freshness=str(cost_meta.get("loaded_at") or "Loaded cost session"),
        ))

    security = _frame(state.get("security_posture_summary"))
    security_meta = state.get("security_posture_meta") if isinstance(state.get("security_posture_meta"), dict) else {}
    if not security.empty:
        row = _first_row(security)
        failed_logins = safe_int(row.get("FAILED_LOGINS", row.get("FAILED_LOGIN_COUNT", 0)))
        mfa_gaps = safe_int(row.get("USERS_WITHOUT_MFA", row.get("MFA_GAP_USERS", 0)))
        grants = safe_int(row.get("RECENT_GRANTS", row.get("RECENT_GRANT_COUNT", 0)))
        risk_count = failed_logins + mfa_gaps + grants
        items.append(_queue_item(
            section="Security Monitoring",
            severity="High" if risk_count >= 20 else "Elevated" if risk_count else "Ready",
            signal=f"{failed_logins:,} failed logins; {mfa_gaps:,} MFA gaps; {grants:,} recent grants",
            evidence="Loaded security summary is available in session.",
            next_action="Refresh Security Summary or open Failed Logins / Risky Grants.",
            freshness=str(security_meta.get("loaded_at") or "Loaded security session"),
        ))

    if not items:
        items.append(_queue_item(
            section="Mission Control",
            severity="On demand",
            signal=f"No loaded cross-section evidence for {company} / {environment}",
            evidence="The shell is intentionally query-free on first paint.",
            next_action="Start with Load Active Alerts, Refresh Cost, or Refresh Security Summary.",
            freshness="Not loaded",
        ))

    return tuple(sorted(
        items,
        key=lambda item: (
            _SEVERITY_RANK.get(str(item.get("severity", "")).upper(), 9),
            str(item.get("section", "")),
        ),
    ))


def render_mission_control_queue(
    state: Mapping[str, Any],
    *,
    company: str,
    environment: str,
    max_items: int = 5,
) -> None:
    """Render the cross-section Mission Control queue from session evidence."""
    items = build_mission_control_items(state, company=company, environment=environment)
    rows = list(items[: max(1, int(max_items or 5))])
    cards = []
    for item in rows:
        severity = _escape_markup(str(item["severity"]))
        section = _escape_markup(str(item["section"]))
        signal = _escape_markup(str(item["signal"]))
        evidence = _escape_markup(str(item["evidence"]))
        next_action = _escape_markup(str(item["next_action"]))
        freshness = _escape_markup(str(item["freshness"]))
        cards.append(
            '<article class="ow-mission-row">'
            f'<div class="ow-mission-severity">{severity}</div>'
            '<div class="ow-mission-main">'
            f'<div class="ow-mission-section">{section}</div>'
            f'<div class="ow-mission-signal">{signal}</div>'
            f'<div class="ow-mission-evidence">{evidence}</div>'
            '</div>'
            '<div class="ow-mission-next">'
            f'<span>Next</span><strong>{next_action}</strong>'
            f'<em>{freshness}</em>'
            '</div>'
            '</article>'
        )
    st.html(
        '<section class="ow-mission-control" role="region" aria-label="Mission Control risk queue">'
        '<div class="ow-mission-kicker">Mission Control</div>'
        '<div class="ow-mission-title">What needs attention now</div>'
        '<div class="ow-mission-copy">Session evidence only. No Snowflake read is started by this queue.</div>'
        f'<div class="ow-mission-list">{"".join(cards)}</div>'
        '</section>'
    )


__all__ = ["build_mission_control_items", "render_mission_control_queue"]
