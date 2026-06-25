"""Renderer for mart-backed OVERWATCH Decision Briefs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from html import escape as _escape_markup
import math
import re

import streamlit as st

from sections.command_brief_routes import apply_command_brief_route
from sections.section_command_brief import SectionCommandAction, SectionCommandBrief, SectionCommandMetric


@dataclass(frozen=True)
class CommandBriefDetailAction:
    label: str
    help_text: str
    callback: Callable[[], None]
    key: str | None = None


def _key_token(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "action"


def _html(value: object) -> str:
    return _escape_markup(str(value or "").strip())


def _compact_number(value: float, *, decimals: int = 1) -> str:
    sign = "-" if value < 0 else ""
    value = abs(float(value))
    if value >= 1_000_000_000:
        return f"{sign}{value / 1_000_000_000:.{decimals}f}B"
    if value >= 1_000_000:
        return f"{sign}{value / 1_000_000:.{decimals}f}M"
    if value >= 1_000:
        return f"{sign}{value / 1_000:.{decimals}f}K"
    if value == int(value):
        return f"{sign}{int(value)}"
    return f"{sign}{value:.{decimals}f}"


def format_command_metric(metric: SectionCommandMetric) -> str:
    """Format typed command metric values without relying on SQL-only display strings."""
    numeric = metric.numeric_value
    fmt = str(metric.metric_format or "").strip().lower()
    unit = str(metric.unit or "").strip()
    if numeric is None:
        return metric.text_value or metric.value or "Unavailable"
    if fmt in {"currency", "compact_currency"}:
        return f"${_compact_number(numeric)}"
    if fmt in {"percentage", "percent"}:
        return f"{numeric:.1f}%"
    if fmt in {"integer", "count"}:
        return _compact_number(numeric, decimals=0)
    if fmt == "duration":
        if numeric >= 3600:
            return f"{numeric / 3600:.1f}h"
        if numeric >= 60:
            return f"{numeric / 60:.1f}m"
        return f"{numeric:.0f}s"
    if fmt == "bytes":
        if numeric >= 1024**4:
            return f"{numeric / 1024**4:.1f} TB"
        if numeric >= 1024**3:
            return f"{numeric / 1024**3:.1f} GB"
        return f"{numeric / 1024**2:.1f} MB"
    if fmt == "credits":
        return f"{_compact_number(numeric)} credits"
    if unit:
        return f"{_compact_number(numeric)} {unit}"
    return _compact_number(numeric)


def _delta_label(metric: SectionCommandMetric) -> str:
    if metric.delta_percent is not None:
        sign = "+" if metric.delta_percent >= 0 else ""
        return f"{sign}{metric.delta_percent:.1f}%"
    if metric.delta_numeric_value is not None:
        sign = "+" if metric.delta_numeric_value >= 0 else ""
        return f"{sign}{_compact_number(metric.delta_numeric_value)}"
    return metric.trend or metric.detail


def _sparkline(points: tuple[object, ...]) -> str:
    if len(points) < 2:
        return ""
    finite: list[float] = []
    for point in points:
        value = point.get("value") if isinstance(point, dict) else point
        try:
            numeric = float(value)
        except Exception:
            continue
        if math.isfinite(numeric):
            finite.append(numeric)
    if len(finite) < 2:
        return ""
    low = min(finite)
    high = max(finite)
    span = high - low or 1.0
    width = 96
    height = 22
    step = width / max(len(finite) - 1, 1)
    coords = []
    for index, value in enumerate(finite):
        x = round(index * step, 2)
        y = round(height - ((value - low) / span * height), 2)
        coords.append(f"{x},{y}")
    return (
        '<svg class="ow-decision-sparkline" viewBox="0 0 96 22" role="img" aria-label="Metric trend">'
        f'<polyline points="{" ".join(coords)}" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round"></polyline></svg>'
    )


def _metric_ribbon_html(brief: SectionCommandBrief, *, compact: bool) -> str:
    if compact:
        return ""
    rows: list[str] = []
    for metric in tuple(brief.metrics or ())[:4]:
        tone = _html(metric.tone or "neutral").lower()
        delta = _delta_label(metric)
        rows.append(
            f'<article class="ow-decision-metric" data-tone="{tone}">'
            f'<span>{_html(metric.label)}</span>'
            f'<strong>{_html(format_command_metric(metric))}</strong>'
            f'<small class="ow-decision-delta">{_html(delta)}</small>'
            f'{_sparkline(metric.trend_points)}'
            '</article>'
        )
    return "".join(rows)


def _priority_list_html(brief: SectionCommandBrief, *, compact: bool) -> str:
    if compact:
        return ""
    rows: list[str] = []
    for item in tuple(brief.exceptions or ())[:3]:
        impact = ""
        if item.impact_value is not None:
            impact = f"{_compact_number(item.impact_value)} {item.impact_unit}".strip()
        owner = item.owner_route or ("Owner gap" if item.owner_gap else "Owner route")
        rows.append(
            '<div class="ow-decision-priority-row">'
            f'<span class="ow-decision-severity">{_html(item.severity)}</span>'
            f'<strong>{_html(item.signal)}</strong>'
            f'<span>{_html(item.entity)}</span>'
            f'<span class="ow-decision-impact">{_html(impact)}</span>'
            f'<span class="ow-decision-owner">{_html(owner)}</span>'
            f'<small>{_html(item.detail)}</small>'
            '</div>'
        )
    if not rows:
        return ""
    return '<section class="ow-decision-priority-list" aria-label="Priority findings">' + "".join(rows) + "</section>"


def _data_trust_summary(brief: SectionCommandBrief) -> str:
    age = "freshness unavailable"
    if brief.freshness_minutes is not None:
        age = f"Updated {int(round(float(brief.freshness_minutes)))}m ago"
    method = brief.data_availability_state or ("Stale" if brief.stale else "Scheduled mart")
    confidence = brief.confidence or "unknown"
    source_note = ""
    if brief.required_source_count:
        source_note = f" | {brief.available_source_count}/{brief.required_source_count} required sources"
    return f"{age} | {method}{source_note} | {confidence}"


def _trust_detail_html(brief: SectionCommandBrief) -> str:
    requested = f"{brief.requested_company or brief.company} / {brief.requested_environment or brief.environment} / {brief.requested_window_days or brief.window_label}"
    resolved = f"{brief.resolved_company or brief.company} / {brief.resolved_environment or brief.environment} / {brief.resolved_window_days or brief.requested_window_days} days"
    rows = (
        ("Packet source", brief.source),
        ("Upstream sources", brief.source_objects),
        ("Requested scope", requested),
        ("Resolved scope", resolved),
        ("Target freshness", f"{brief.target_freshness_minutes} minutes"),
        ("Source coverage", f"{brief.available_source_count}/{brief.required_source_count} sources ({brief.source_coverage_pct or 0:.1f}%)"),
        ("Missing sources", brief.source_gap_detail or "None reported"),
        ("Confidence", brief.confidence),
    )
    detail = "".join(
        f'<div class="ow-decision-trust-detail"><strong>{_html(label)}</strong><span>{_html(value)}</span></div>'
        for label, value in rows
    )
    source_rows = []
    for source in tuple(brief.sources or ()):
        status = "Unavailable"
        if source.available and source.stale:
            status = "Stale"
        elif source.available:
            status = "Available"
        age = "unknown age" if source.age_minutes is None else f"{int(round(float(source.age_minutes)))}m old"
        required = "required" if source.required else "optional"
        source_rows.append(
            '<div class="ow-decision-source-row">'
            f'<strong>{_html(source.source_key)}</strong>'
            f'<span>{_html(source.source_object)}</span>'
            f'<span>{_html(status)} / {_html(required)} / {_html(age)}</span>'
            f'<small>{_html(source.gap_reason or source.confidence or "No source gap reported")}</small>'
            '</div>'
        )
    if source_rows:
        detail += '<div class="ow-decision-source-table" aria-label="Command brief source health">' + "".join(source_rows) + "</div>"
    return detail


def _render_fallback(brief: SectionCommandBrief, *, key_prefix: str, detail_action: CommandBriefDetailAction | None) -> None:
    st.html(
        '<section class="ow-decision-brief ow-decision-fallback" role="region" aria-label="Decision brief unavailable">'
        '<div class="ow-decision-status" data-state="data-gap">'
        '<span>Data Gap</span>'
        f'<strong>{_html(brief.headline)}</strong>'
        f'<p>{_html(brief.fallback_reason or brief.summary)}</p>'
        '</div>'
        '<section class="ow-decision-priority-list" aria-label="Unavailable summary">'
        '<div class="ow-decision-priority-row">'
        '<span class="ow-decision-severity">Setup</span>'
        f'<strong>{_html(brief.top_signal.signal if brief.top_signal else "Command mart unavailable")}</strong>'
        f'<span>{_html(brief.company)} / {_html(brief.environment)} / {_html(brief.window_label)}</span>'
        f'<small>{_html(brief.source_gap_detail or "Refresh the command brief mart or review deployment status.")}</small>'
        '</div></section>'
        f'<div class="ow-decision-trust">{_html(_data_trust_summary(brief))}</div>'
        '</section>'
    )
    if detail_action is not None:
        _render_detail_action(key_prefix=key_prefix, detail_action=detail_action)


def _route_action(action: SectionCommandAction) -> bool:
    if action.route_key:
        return apply_command_brief_route(action.route_key)
    return False


def _render_action_row(
    brief: SectionCommandBrief,
    *,
    key_prefix: str,
    primary_action: Callable[[], None] | None,
    detail_action: CommandBriefDetailAction | None,
    compact: bool,
) -> None:
    if compact:
        if detail_action is not None:
            _render_detail_action(key_prefix=key_prefix, detail_action=detail_action)
        return
    actions = tuple(brief.next_actions or ())[:3]
    secondary_count = max(min(len(actions) - 1, 2), 0)
    cols = st.columns(1 + secondary_count + (1 if detail_action is not None else 0))
    if actions:
        primary = actions[0]
        with cols[0]:
            if st.button(primary.cta or primary.label, key=f"{key_prefix}_primary_{_key_token(primary.action_key or primary.label)}", type="primary", width="stretch"):
                if primary_action is not None:
                    primary_action()
                    st.rerun()
                else:
                    if _route_action(primary):
                        st.rerun()
        for index, action in enumerate(actions[1:3], start=1):
            with cols[index]:
                if st.button(action.cta or action.label, key=f"{key_prefix}_secondary_{index}_{_key_token(action.action_key or action.label)}", width="stretch"):
                    if _route_action(action):
                        st.rerun()
    if detail_action is not None:
        with cols[-1]:
            _render_detail_action(key_prefix=key_prefix, detail_action=detail_action)


def _render_detail_action(*, key_prefix: str, detail_action: CommandBriefDetailAction) -> None:
    if st.button(
        detail_action.label,
        key=detail_action.key or f"{key_prefix}_detail_{_key_token(detail_action.label)}",
        type="primary",
        width="stretch",
        help=detail_action.help_text or None,
    ):
        detail_action.callback()
        st.rerun()


def render_section_command_brief(
    brief: SectionCommandBrief,
    *,
    key_prefix: str,
    primary_action: Callable[[], None] | None = None,
    detail_action: CommandBriefDetailAction | None = None,
    compact: bool = False,
    on_primary_action: Callable[[], None] | None = None,
    on_detail: Callable[[], None] | None = None,
) -> None:
    """Render a concise Decision Brief with safe actions and accurate data trust."""
    if detail_action is None and on_detail is not None and brief.detail_cta:
        detail_action = CommandBriefDetailAction(brief.detail_cta, "", on_detail)
    if primary_action is None and on_primary_action is not None:
        primary_action = on_primary_action
    if brief.fallback_reason and not tuple(brief.metrics or ()):
        _render_fallback(brief, key_prefix=key_prefix, detail_action=detail_action)
        return

    state = "data-gap" if brief.missing_source_count else ("stale" if brief.stale else str(brief.state or "Watch").lower())
    metric_body = _metric_ribbon_html(brief, compact=compact)
    priority_body = _priority_list_html(brief, compact=compact)
    trend_metric = next((metric for metric in brief.metrics if metric.trend_points), None)
    trend_body = ""
    if trend_metric is not None and not compact:
        trend_body = (
            '<section class="ow-decision-what-changed" aria-label="What changed">'
            f'<strong>What changed</strong><span>{_html(trend_metric.label)}</span>'
            f'{_sparkline(trend_metric.trend_points)}'
            f'<p>{_html(_delta_label(trend_metric) or trend_metric.detail)}</p>'
            '</section>'
        )
    compact_class = " ow-decision-compact" if compact else ""
    st.html(
        f'<section class="ow-decision-brief{compact_class}" role="region" aria-label="OVERWATCH Decision Brief">'
        f'<div class="ow-decision-status" data-state="{_html(state)}">'
        f'<span>{_html("Data Gap" if brief.missing_source_count else ("Stale" if brief.stale else brief.state))}</span>'
        f'<strong>{_html(brief.headline)}</strong>'
        f'<p class="ow-decision-narrative">{_html(brief.summary)}</p>'
        f'<small class="ow-decision-freshness">{_html(_data_trust_summary(brief))}</small>'
        '</div>'
        f'<div class="ow-decision-metric-ribbon">{metric_body}</div>'
        f'{trend_body}'
        f'{priority_body}'
        '</section>'
    )
    _render_action_row(
        brief,
        key_prefix=key_prefix,
        primary_action=primary_action,
        detail_action=detail_action,
        compact=compact,
    )
    with st.expander("Data Trust", expanded=False):
        st.html(f'<div class="ow-decision-trust-panel">{_trust_detail_html(brief)}</div>')
    if not compact and len(tuple(brief.metrics or ())) > 4:
        extra = "".join(
            f'<div class="ow-decision-extra-metric"><strong>{_html(metric.label)}</strong>'
            f'<span>{_html(format_command_metric(metric))}</span><small>{_html(metric.detail)}</small></div>'
            for metric in tuple(brief.metrics or ())[4:]
        )
        with st.expander("Additional brief metrics", expanded=False):
            st.html(f'<div class="ow-decision-extra-metrics">{extra}</div>')


__all__ = ["CommandBriefDetailAction", "format_command_metric", "render_section_command_brief"]
