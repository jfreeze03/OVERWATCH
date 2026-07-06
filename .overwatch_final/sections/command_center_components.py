"""Safe HTML components for the Executive command-center dashboard."""

from __future__ import annotations

from html import escape as _escape
import math

import streamlit as st

from sections.command_center_models import (
    CommandCenterContextRow,
    CommandCenterKpi,
    CommandCenterStatusRow,
    ExecutiveCommandCenterModel,
    WarehouseCreditSlice,
)
from utils.display_safety import clean_display_text
from utils.primitives import safe_float


def _html(value: object) -> str:
    return _escape(clean_display_text(value))


def _tone(value: object) -> str:
    text = str(value or "neutral").strip().lower()
    if text in {"critical", "high", "risk", "failed", "error"}:
        return "critical"
    if text in {"warning", "watch", "medium", "pending", "stale"}:
        return "warning"
    if text in {"healthy", "clear", "ready", "excellent", "loaded"}:
        return "healthy"
    if text in {"info", "on_request"}:
        return "info"
    return "neutral"


def _icon(name: str) -> str:
    paths = {
        "clipboard": '<rect x="9" y="8" width="22" height="25" rx="3"/><path d="M15 8V5h10v3"/><path d="m15 21 4 4 7-9"/>',
        "database": '<ellipse cx="20" cy="9" rx="11" ry="5"/><path d="M9 9v15c0 3 5 5 11 5s11-2 11-5V9"/><path d="M9 17c0 3 5 5 11 5s11-2 11-5"/>',
        "shield": '<path d="M20 4 33 10v10c0 8-5 14-13 17C12 34 7 28 7 20V10Z"/><path d="m15 20 4 4 7-9"/>',
        "heart": '<path d="M20 33s-12-7-12-17a7 7 0 0 1 12-5 7 7 0 0 1 12 5c0 10-12 17-12 17Z"/>',
        "warning": '<path d="M20 5 36 34H4Z"/><path d="M20 15v8"/><path d="M20 29h.01"/>',
        "clock": '<circle cx="20" cy="20" r="15"/><path d="M20 11v10l7 4"/>',
        "refresh": '<path d="M32 14a13 13 0 0 0-22-4l-4 4"/><path d="M6 7v7h7"/><path d="M8 26a13 13 0 0 0 22 4l4-4"/><path d="M34 33v-7h-7"/>',
        "download": '<path d="M20 6v19"/><path d="m12 17 8 8 8-8"/><path d="M8 32h24"/>',
        "folder": '<path d="M5 12h11l3 4h16v16H5Z"/>',
        "search": '<circle cx="18" cy="18" r="10"/><path d="m26 26 8 8"/>',
        "route": '<path d="M8 30c6 0 6-20 12-20s6 20 12 20"/><circle cx="8" cy="30" r="3"/><circle cx="20" cy="10" r="3"/><circle cx="32" cy="30" r="3"/>',
        "status": '<circle cx="20" cy="20" r="14"/><path d="m14 20 4 4 8-9"/>',
    }
    path = paths.get(str(name or ""), paths["status"])
    return (
        '<svg class="ow-cc-icon-svg" viewBox="0 0 40 40" aria-hidden="true">'
        f'<g fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">{path}</g>'
        "</svg>"
    )


def _sparkline(points: tuple[float, ...], *, tone: str = "neutral") -> str:
    values: list[float] = []
    for value in points:
        number = safe_float(value, default=float("nan"))
        if math.isfinite(number):
            values.append(number)
    if len(values) < 2:
        return '<svg class="ow-cc-sparkline ow-cc-sparkline-empty" viewBox="0 0 120 28" aria-hidden="true"><path d="M4 19h112"/></svg>'
    low = min(values)
    high = max(values)
    span = high - low or 1.0
    step = 116 / max(len(values) - 1, 1)
    coords = []
    for index, value in enumerate(values):
        x = 2 + index * step
        y = 24 - ((value - low) / span * 19)
        coords.append(f"{x:.2f},{y:.2f}")
    return (
        f'<svg class="ow-cc-sparkline" data-tone="{_html(tone)}" viewBox="0 0 120 28" role="img" aria-label="Trend">'
        '<path class="ow-cc-sparkline-fill" d="M2 27 '
        + " ".join(f"L{point}" for point in coords)
        + ' L118 27 Z"></path>'
        f'<polyline points="{" ".join(coords)}"></polyline>'
        "</svg>"
    )


def _kpi_card(card: CommandCenterKpi) -> str:
    tone = _tone(card.tone)
    return (
        f'<article class="ow-cc-kpi-card" data-tone="{_html(tone)}">'
        f'<div class="ow-cc-kpi-icon">{_icon(card.icon)}</div>'
        f'<div class="ow-cc-kpi-label">{_html(card.label)}</div>'
        f'<div class="ow-cc-kpi-value">{_html(card.value)}</div>'
        f'<div class="ow-cc-kpi-detail ow-cc-kpi-subtitle">{_html(card.subtitle)}</div>'
        f'{_sparkline(card.trend, tone=tone)}'
        "</article>"
    )


def render_command_center_kpi_strip(model: ExecutiveCommandCenterModel) -> None:
    st.html(
        '<section class="ow-cc-kpi-strip" aria-label="Executive command-center KPIs">'
        + "".join(_kpi_card(card) for card in model.kpis)
        + "</section>"
    )


def _score_value(model: ExecutiveCommandCenterModel) -> float:
    if model.health_value in {"Refresh required", "Unavailable"}:
        return 0.0
    return max(0.0, min(100.0, safe_float(str(model.health_value).split("/")[0], default=0.0)))


def render_coco_ai_summary(model: ExecutiveCommandCenterModel) -> None:
    headline = clean_display_text(model.summary_headline)
    detail = clean_display_text(model.summary_detail)
    if not detail or "connection unavailable" in detail.lower():
        detail = "Loading the current packet for the selected scope."
    if headline and headline.lower() not in {"refresh required", "operating summary loaded"}:
        body = f"{headline}. {detail}"
    else:
        body = detail
    st.html(
        '<section class="ow-coco-ai-summary" aria-label="Cortex AI Platform Summary">'
        '<div class="ow-coco-ai-icon">AI</div>'
        '<div><span>Cortex AI Platform Summary</span>'
        f'<p>{_html(body)}</p></div>'
        "</section>"
    )


def render_coco_score_section(model: ExecutiveCommandCenterModel) -> None:
    score = _score_value(model)
    dash = 314.16 * score / 100.0
    breakdown = (
        ("Cost Health", "Ready" if model.total_credits_text not in {"Refresh required", "Unavailable"} else "Refresh required", "blue"),
        ("Pipeline Success", "Open details", "amber"),
        ("Security Posture", "Ready" if model.health_value not in {"Refresh required", "Unavailable"} else "Refresh required", "green"),
        ("Alert Health", model.open_actions_detail, "amber" if model.open_actions_value != "0" else "green"),
        ("Warehouse Efficiency", "Scoped" if model.warehouse_slices else "Refresh required", "purple"),
        ("Data Freshness", model.freshness_value, "blue"),
    )
    items = "".join(
        '<div class="ow-coco-score-item">'
        f'<i data-tone="{_html(tone)}"></i><span>{_html(label)}</span><strong>{_html(value)}</strong>'
        "</div>"
        for label, value, tone in breakdown
    )
    st.html(
        '<section class="ow-coco-score-section" aria-label="Platform Operating Score">'
        '<div class="ow-coco-score-ring">'
        '<svg viewBox="0 0 120 120" aria-hidden="true">'
        '<circle class="ow-coco-score-bg" cx="60" cy="60" r="50"></circle>'
        f'<circle class="ow-coco-score-fill" cx="60" cy="60" r="50" stroke-dasharray="{dash:.1f} 314.2"></circle>'
        '</svg>'
        f'<div><strong>{_html(f"{score:.0f}" if score else "N/A")}</strong><span>Platform Score</span></div>'
        '</div>'
        f'<div class="ow-coco-score-breakdown">{items}</div>'
        '</section>'
    )


def _coco_kpi(label: str, value: str, delta: str, tone: str = "blue") -> str:
    return (
        f'<article class="ow-coco-kpi-card" data-tone="{_html(tone)}">'
        f'<span>{_html(label)}</span><strong>{_html(value)}</strong><small>{_html(delta)}</small>'
        "</article>"
    )


def render_coco_kpi_row(model: ExecutiveCommandCenterModel) -> None:
    warehouse_count = len(model.warehouse_slices)
    warehouse_value = f"{warehouse_count:,}" if warehouse_count else "Scoped"
    cards = (
        _coco_kpi("Credits Used", model.total_credits_text, "Selected window", "blue"),
        _coco_kpi("Active Warehouses", warehouse_value, "All scoped warehouses", "purple"),
        _coco_kpi("Open Actions", model.open_actions_value, model.open_actions_detail, "amber" if model.open_actions_value != "0" else "green"),
        _coco_kpi("Account Health", model.health_value, model.health_detail, "green" if model.health_value not in {"Refresh required", "Unavailable"} else "amber"),
    )
    st.html('<section class="ow-coco-kpi-row" aria-label="Executive KPIs">' + "".join(cards) + "</section>")


def render_coco_credit_consumption_panel(model: ExecutiveCommandCenterModel) -> None:
    points = model.credit_points or model.health_points
    st.html(
        '<section class="ow-coco-chart-card" aria-label="Daily Credit Consumption">'
        '<header><div><h3>Daily Credit Consumption</h3><p>Selected-window trend from the command packet.</p></div>'
        '<span>Packet</span></header>'
        f'{_sparkline(points, tone="info")}'
        '<div class="ow-coco-chart-footer"><span>Actual</span><span>Forecast on drill-through</span></div>'
        '</section>'
    )


def render_coco_warehouse_panel(model: ExecutiveCommandCenterModel) -> None:
    rows = (
        "".join(
            f'<div class="ow-coco-table-row"><strong>{_html(item.warehouse)}</strong><span>{_html(item.credits_text)}</span><em>{_html(item.pct_text)}</em></div>'
            for item in model.warehouse_slices
        )
        or '<div class="ow-coco-table-row"><strong>Warehouse split</strong><span>Loading current summary</span><em>Packet</em></div>'
    )
    st.html(
        '<section class="ow-coco-chart-card" aria-label="Top Warehouses by Credits">'
        '<header><div><h3>Top Warehouses by Credits</h3><p>Compact ranking paired to credit share.</p></div>'
        '<span>Scoped</span></header>'
        '<div class="ow-coco-warehouse-grid">'
        f'<div class="ow-coco-donut" style="background:{_html(_donut_style(model.warehouse_slices))}"><div><strong>{_html(model.total_credits_text)}</strong><span>Total Credits</span></div></div>'
        f'<div class="ow-coco-table">{rows}</div>'
        '</div></section>'
    )


def render_coco_leadership_watchlist(model: ExecutiveCommandCenterModel) -> None:
    entries = (
        ("Credit burn", model.total_credits_text, "Cost Intelligence", "blue"),
        ("Failed logins", "Open details", "Security Monitoring", "amber"),
        ("Query errors", "Open details", "Workload Operations", "amber"),
        ("Storage growth", "Open details", "Cost Intelligence", "blue"),
        ("Cortex Code", "Open details", "Cost Intelligence", "purple"),
        ("Role / grant audit", "Open details", "Security Monitoring", "green"),
    )
    rows = "".join(
        f'<div class="ow-coco-watch-row"><i data-tone="{_html(tone)}"></i><strong>{_html(label)}</strong><span>{_html(value)}</span><em>{_html(route)}</em></div>'
        for label, value, route, tone in entries
    )
    st.html(
        '<section class="ow-coco-watchlist" aria-label="Leadership Watchlist">'
        '<header><h3>Leadership Watchlist</h3><span>Recurring manual checks</span></header>'
        f'<div>{rows}</div>'
        '</section>'
    )


def _hero_circuit() -> str:
    return (
        '<div class="ow-cc-hero-visual" aria-hidden="true">'
        '<svg viewBox="0 0 360 220" preserveAspectRatio="xMidYMid meet">'
        '<defs><linearGradient id="ow_cc_cube" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#79dcff"/><stop offset="1" stop-color="#0a67d8"/></linearGradient></defs>'
        '<path class="grid" d="M22 166h316M40 142h280M66 118h228M96 94h168M180 26v166M130 52v128M230 52v128"/>'
        '<path class="plate" d="m180 66 94 45-94 45-94-45Z"/>'
        '<path class="base" d="m180 92 54 26-54 26-54-26Z"/>'
        '<path class="cube" d="m180 70 34 17v52l-34 17-34-17V87Z"/>'
        '<path class="cube-face" d="m180 70v86M146 87l34 18 34-18M146 139l34-18 34 18"/>'
        '<circle class="node" cx="72" cy="141" r="4"/><circle class="node" cx="286" cy="111" r="4"/><circle class="node" cx="180" cy="194" r="4"/>'
        '<path class="pulse" d="M72 141h72l36 53M286 111h-72l-34-41"/>'
        "</svg></div>"
    )


def render_executive_hero_card(model: ExecutiveCommandCenterModel) -> None:
    tiles = (
        ("Summary", model.summary_headline, "Packet", "warning"),
        ("Source Status", model.source_status, model.source_detail, _tone(model.source_status)),
        ("Evidence", model.evidence_status, model.evidence_detail, _tone(model.evidence_status)),
    )
    tile_html = "".join(
        f'<div class="ow-cc-hero-tile" data-tone="{_html(tone)}"><span>{_html(label)}</span><strong>{_html(value)}</strong><small>{_html(detail)}</small><i></i></div>'
        for label, value, detail, tone in tiles
    )
    st.html(
        '<section class="ow-cc-card ow-cc-hero-card" aria-label="Executive Landing command center">'
        '<div class="ow-cc-hero-copy">'
        '<h1>Executive Landing</h1>'
        '<div class="ow-cc-hero-kicker">Command Center</div>'
        f'<div class="ow-cc-status-pill" data-tone="{_html(_tone(model.summary_state))}">{_html(model.summary_state)}</div>'
        f'<h2>{_html(model.summary_headline)}</h2>'
        f'<p>{_html(model.summary_detail)}</p>'
        "</div>"
        + _hero_circuit()
        + f'<div class="ow-cc-hero-tiles">{tile_html}</div>'
        "</section>"
    )


def _attention_row(row: CommandCenterStatusRow) -> str:
    tone = _tone(row.severity)
    return (
        f'<div class="ow-cc-attention-row" data-tone="{_html(tone)}">'
        f'<div><i></i><strong>{_html(row.severity)}</strong></div>'
        f'<div><b>{_html(row.status)}</b><small>{_html(row.details)}</small></div>'
        f'<div><span>Workflow</span><small>{_html(row.owner)}</small></div>'
        f'<div><span>SLA</span><small>{_html(row.sla)}</small></div>'
        "</div>"
    )


def render_attention_panel(model: ExecutiveCommandCenterModel) -> None:
    rows = "".join(_attention_row(row) for row in model.attention_rows[:3])
    st.html(
        '<section class="ow-cc-card ow-cc-attention-panel" aria-label="What needs attention">'
        '<header><h3>What Needs Attention</h3><span aria-hidden="true">i</span></header>'
        f'<div class="ow-cc-attention-list">{rows}</div>'
        "</section>"
    )


def _gauge(model: ExecutiveCommandCenterModel) -> str:
    score_text = model.health_value
    score = 0.0
    if score_text not in {"Refresh required", "Unavailable"}:
        score = max(0.0, min(100.0, safe_float(score_text.split("/")[0].strip(), default=0.0)))
    dash = 188.0 * score / 100.0
    return (
        '<svg class="ow-cc-gauge" viewBox="0 0 150 102" role="img" aria-label="Account Health">'
        '<path class="track" d="M24 78a51 51 0 0 1 102 0"/>'
        f'<path class="value" stroke-dasharray="{dash:.1f} 188" d="M24 78a51 51 0 0 1 102 0"/>'
        f'<text x="75" y="66" text-anchor="middle">{_html(score_text.split()[0] if score_text not in {"Refresh required", "Unavailable"} else "N/A")}</text>'
        f'<text x="75" y="86" text-anchor="middle">{"/100" if score_text not in {"Refresh required", "Unavailable"} else ""}</text>'
        "</svg>"
    )


def render_account_health_trend_panel(model: ExecutiveCommandCenterModel) -> None:
    st.html(
        '<section class="ow-cc-card ow-cc-health-panel" aria-label="Account Health Trend">'
        '<header><h3>Account Health Trend</h3><span>7 Days</span></header>'
        '<div class="ow-cc-health-body">'
        f'<div class="ow-cc-health-score">{_gauge(model)}<strong>{_html(model.health_detail)}</strong><small>Selected window</small></div>'
        f'<div class="ow-cc-health-line">{_sparkline(model.health_points, tone=model.health_tone)}</div>'
        "</div></section>"
    )


def _donut_style(slices: tuple[WarehouseCreditSlice, ...]) -> str:
    if not slices:
        return "conic-gradient(rgba(126,220,255,0.22) 0 100%)"
    colors = {
        "blue": "#2f88ff",
        "cyan": "#28c7f7",
        "purple": "#a56bff",
        "orange": "#ffad48",
        "slate": "#8aa7bb",
    }
    start = 0.0
    segments = []
    for item in slices:
        end = start + max(item.pct_value, 0.0)
        color = colors.get(item.tone, "#29b5e8")
        segments.append(f"{color} {start:.2f}% {min(end, 100.0):.2f}%")
        start = end
    if start < 100.0:
        segments.append(f"rgba(126,220,255,0.16) {start:.2f}% 100%")
    return "conic-gradient(" + ", ".join(segments) + ")"


def render_credits_by_warehouse_panel(model: ExecutiveCommandCenterModel) -> None:
    legend = (
        "".join(
            f'<div class="ow-cc-legend-row" data-tone="{_html(item.tone)}"><span></span><strong>{_html(item.warehouse)}</strong><em>{_html(item.pct_text)}</em></div>'
            for item in model.warehouse_slices
        )
        or '<div class="ow-cc-empty-note">Warehouse split loading</div>'
    )
    st.html(
        '<section class="ow-cc-card ow-cc-warehouse-panel" aria-label="Credits by Warehouse">'
        '<header><h3>Credits by Warehouse</h3><span aria-hidden="true">i</span></header>'
        '<div class="ow-cc-donut-row">'
        f'<div class="ow-cc-donut" style="background:{_html(_donut_style(model.warehouse_slices))}"><div><strong>{_html(model.total_credits_text)}</strong><span>Total Credits</span></div></div>'
        f'<div class="ow-cc-donut-legend">{legend}</div>'
        "</div>"
        "</section>"
    )


def render_recent_status_alerts_panel(model: ExecutiveCommandCenterModel) -> None:
    rows = "".join(
        f'<div class="ow-cc-status-row" data-tone="{_html(_tone(row.severity))}"><span>{_html(row.severity)}</span><strong>{_html(row.status)}</strong><em>{_html(row.details)}</em><small>{_html(row.owner)}</small><small>{_html(row.sla)}</small><small>{_html(row.time_label)}</small></div>'
        for row in model.alert_rows
    )
    st.html(
        '<section class="ow-cc-card ow-cc-status-panel" aria-label="Recent Status and Alerts">'
        '<header><h3>Recent Status &amp; Alerts</h3><span aria-hidden="true">i</span></header>'
        '<div class="ow-cc-status-head"><span>Severity</span><span>Status</span><span>Details</span><span>Workflow</span><span>SLA</span><span>Time</span></div>'
        f'<div class="ow-cc-status-table">{rows}</div>'
        "</section>"
    )


def _context_row(row: CommandCenterContextRow) -> str:
    return (
        '<div class="ow-cc-context-row">'
        f'<span>{_icon(row.icon)}</span><strong>{_html(row.label)}</strong><em>{_html(row.value)}</em>'
        "</div>"
    )


def render_operational_context_panel(model: ExecutiveCommandCenterModel) -> None:
    st.html(
        '<section class="ow-cc-card ow-cc-context-panel" aria-label="Operational Context">'
        '<header><h3>Operational Context</h3><span aria-hidden="true">i</span></header>'
        + "".join(_context_row(row) for row in model.context_rows)
        + "</section>"
    )


__all__ = [
    "render_coco_ai_summary",
    "render_coco_credit_consumption_panel",
    "render_coco_kpi_row",
    "render_coco_leadership_watchlist",
    "render_coco_score_section",
    "render_coco_warehouse_panel",
    "render_account_health_trend_panel",
    "render_attention_panel",
    "render_command_center_kpi_strip",
    "render_credits_by_warehouse_panel",
    "render_executive_hero_card",
    "render_operational_context_panel",
    "render_recent_status_alerts_panel",
]
