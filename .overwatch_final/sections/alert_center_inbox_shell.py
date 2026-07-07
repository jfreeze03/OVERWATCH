"""COCO-style Alert Center inbox shell components."""

from __future__ import annotations

from html import escape as _escape

import streamlit as st


def _html(value: object) -> str:
    return _escape(str(value or ""))


def render_alert_inbox_shell(
    *,
    source_view: str,
    summary: dict[str, str],
    source_summary: str,
    days: int,
    limit: int,
) -> None:
    chips = ("New", "Acknowledged", "In Progress", "Resolved", "Suppressed", "All")
    chip_html = "".join(
        f'<span class="ow-coco-filter-chip{" is-active" if chip == "New" else ""}">{_html(chip)}</span>'
        for chip in chips
    )
    kpis = (
        ("New", summary["open_queue"], "Action queue"),
        ("Critical / High", summary["critical_high"], "Priority alerts"),
        ("Overdue SLA", summary["overdue"], "Needs review"),
        ("Resolved 24h", "On load", "Detail rows"),
        ("Noise Ratio", "Pending", "Rule quality"),
        ("MTTR", "Pending", "After load"),
    )
    kpi_html = "".join(
        f'<article class="ow-coco-alert-kpi"><span>{_html(label)}</span><strong>{_html(value)}</strong><small>{_html(detail)}</small></article>'
        for label, value, detail in kpis
    )
    rows = (
        ("Info", f"{source_view} ready", source_summary, "Open", "Workflow on load", "Selected window"),
        ("Info", "Load details for row-level triage", f"{int(days)} days / {int(limit)} rows", "New", "Workflow on load", summary["freshness"]),
    )
    row_html = "".join(
        '<div class="ow-coco-alert-row">'
        f'<span>{_html(severity)}</span><strong>{_html(title)}</strong><em>{_html(obj)}</em><small>{_html(status)}</small><small>{_html(owner)}</small><small>{_html(sla)}</small>'
        "</div>"
        for severity, title, obj, status, owner, sla in rows
    )
    intelligence_rows = (
        ("Alert rule coverage", "On load", "Pending", "Review stale rules"),
        ("Noise ratio", "Pending", "Pending", "Tune noisy alerts"),
        ("Delivery reliability", "On load", "Pending", "Review delivery status"),
    )
    intelligence_html = "".join(
        '<div class="ow-coco-intel-row">'
        f'<strong>{_html(rule)}</strong><span>{_html(triggered)}</span><span>{_html(score)}</span><em>{_html(recommendation)}</em>'
        "</div>"
        for rule, triggered, score, recommendation in intelligence_rows
    )
    st.html(
        '<section class="ow-coco-alert-shell" aria-label="Alert Inbox">'
        '<header><div><h3>Alert Inbox</h3><p>Lifecycle filters and alert intelligence stay first.</p></div>'
        f'<span>{_html(source_summary)}</span></header>'
        f'<div class="ow-coco-alert-kpis">{kpi_html}</div>'
        f'<div class="ow-coco-filter-bar" aria-label="Alert lifecycle filters">{chip_html}</div>'
        '<div class="ow-coco-alert-table">'
        '<div class="ow-coco-alert-head"><span>Severity</span><span>Title</span><span>Object</span><span>Status</span><span>Workflow</span><span>SLA</span></div>'
        f"{row_html}</div>"
        '<div class="ow-coco-intel-table"><header><h4>Alert Intelligence</h4><span>Compact scorecard</span></header>'
        f"{intelligence_html}</div>"
        "</section>"
    )


__all__ = ["render_alert_inbox_shell"]
