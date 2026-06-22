"""Operator-first OVERWATCH Command Center.

The first screen answers the five operator questions without exposing score
formulas, proof ledgers, validation internals, or mart implementation details.
"""

from __future__ import annotations

import html

import streamlit as st

from sections.navigation import apply_navigation_state
from utils.operator_model import (
    load_operator_snapshot,
    money,
    severity_counts,
    short_number,
)


def _status_color(status: str) -> str:
    status = str(status or "").lower()
    if status == "critical":
        return "#ef4444"
    if status == "warning":
        return "#f59e0b"
    return "#22c55e"


def _card(title: str, value: str, detail: str, status: str = "Healthy") -> None:
    color = _status_color(status)
    st.markdown(
        f"""
        <div style="border:1px solid rgba(148,163,184,.22); border-left:4px solid {color};
                    border-radius:8px; padding:.7rem .8rem; min-height:96px;
                    background:rgba(15,23,42,.42);">
            <div style="font-size:.72rem; text-transform:uppercase; color:#94a3b8; font-weight:800;">
                {html.escape(title)}
            </div>
            <div style="font-size:1.42rem; line-height:1.2; font-weight:850; color:#f8fafc; margin-top:.15rem;">
                {html.escape(value)}
            </div>
            <div style="font-size:.78rem; color:#cbd5e1; margin-top:.25rem; line-height:1.25;">
                {html.escape(detail)}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _nav_button(label: str, target: str, key: str) -> None:
    if st.button(label, key=key, width="stretch"):
        apply_navigation_state(target)
        st.rerun()


def render() -> None:
    """Render the no-scroll command center summary."""
    snapshot = load_operator_snapshot()
    summary = snapshot.board.summary
    counts = severity_counts(snapshot.incidents)
    incident_total = counts["Critical"] + counts["Warning"] + counts["Info"]
    cost_status = "Warning" if float(summary.get("spend_delta_cost_usd") or 0) > 0 else "Healthy"
    perf_status = "Warning" if int(summary.get("failed_queries") or 0) or int(summary.get("queued_queries") or 0) else "Healthy"
    security_status = "Warning" if int(summary.get("failed_logins") or 0) or int(summary.get("privileged_grants") or 0) else "Healthy"
    pipeline_status = "Critical" if int(summary.get("failed_tasks") or 0) else "Healthy"

    st.markdown("### OVERWATCH COMMAND CENTER")
    st.caption("What is broken, expensive, changed, ownerless, and next.")

    row1 = st.columns(4)
    with row1[0]:
        _card("Overall Health", snapshot.health, snapshot.health_reason, snapshot.health)
    with row1[1]:
        _card(
            "Active Incidents",
            str(incident_total),
            f"{counts['Critical']} critical / {counts['Warning']} warning / {counts['Info']} info",
            "Critical" if counts["Critical"] else "Warning" if counts["Warning"] else "Healthy",
        )
    with row1[2]:
        _card(
            "Cost Risk",
            money(summary.get("current_cost_usd")),
            f"Delta {money(summary.get('spend_delta_cost_usd'))}; Cortex {money(summary.get('cortex_cost_usd'))}",
            cost_status,
        )
    with row1[3]:
        _card(
            "Performance Risk",
            f"{int(summary.get('failed_queries') or 0)} failures",
            f"{int(summary.get('queued_queries') or 0)} queued; {short_number(summary.get('remote_spill_gb'), 'GB')} spill",
            perf_status,
        )

    row2 = st.columns(4)
    with row2[0]:
        _card(
            "Security Risk",
            f"{int(summary.get('failed_logins') or 0)} failed logins",
            f"{int(summary.get('privileged_grants') or 0)} privileged grants",
            security_status,
        )
    with row2[1]:
        _card(
            "Failed Pipelines",
            str(int(summary.get("failed_tasks") or 0)),
            f"{int(summary.get('task_runs') or 0)} task/procedure runs observed",
            pipeline_status,
        )
    with row2[2]:
        _card(
            "Top Recommendations",
            str(min(5, len(snapshot.recommendations))),
            "Sorted by urgency and savings/risk avoided.",
            "Warning" if len(snapshot.recommendations) else "Healthy",
        )
    with row2[3]:
        _card(
            "Last Refresh / Freshness",
            snapshot.loaded_at,
            "Uses compact summary facts; details load only on demand.",
            "Warning" if snapshot.loaded_at == "Awaiting refresh" else "Healthy",
        )

    action_cols = st.columns([1, 1, 1, 2])
    with action_cols[0]:
        _nav_button("Open Incidents", "INCIDENTS", "command_center_open_incidents")
    with action_cols[1]:
        _nav_button("Open Optimization", "OPTIMIZATION", "command_center_open_optimization")
    with action_cols[2]:
        _nav_button("Open Settings", "SETTINGS", "command_center_open_settings")

    if not snapshot.recommendations.empty:
        st.dataframe(
            snapshot.recommendations,
            hide_index=True,
            width="stretch",
            height=210,
        )

