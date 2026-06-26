"""Renderer for mart-backed OVERWATCH Decision Briefs."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from html import escape as _escape_markup
import math
import re

import streamlit as st

from sections.command_brief_routes import COMMAND_BRIEF_ROUTES, apply_command_brief_route
from sections.decision_workspace_state import workspace_mode_for_brief
from sections.decision_workspace_view_model import (
    DecisionActionView,
    DecisionMetricCell,
    DecisionWorkspaceViewModel,
    build_decision_workspace_view_model,
    format_metric_value,
)
from sections.section_command_brief import SectionCommandBrief


@dataclass(frozen=True)
class CommandBriefDetailAction:
    label: str
    help_text: str
    callback: Callable[[], None]
    key: str | None = None


@dataclass(frozen=True)
class CommandBriefControlSet:
    refresh_action: Callable[[], None] | None = None
    route_actions: tuple[DecisionActionView, ...] = ()
    evidence_action: CommandBriefDetailAction | None = None


def _key_token(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "action"


def _html(value: object) -> str:
    return _escape_markup(str(value or "").strip())


def _public_text(value: object) -> str:
    """Remove Snowflake implementation names from first-viewport user copy."""
    text = str(value or "").strip()
    text = re.sub(r"\b(?:MART|FACT|OVERWATCH|ALERT)_[A-Z0-9_]+\b", "Decision source", text)
    text = re.sub(r"\bsnowflake/[A-Za-z0-9_./-]+\.sql\b", "setup script", text, flags=re.IGNORECASE)
    return text


def format_command_metric(metric: object) -> str:
    """Format typed command metric values without SQL-only display strings."""
    return format_metric_value(metric)


def _sparkline(points: tuple[object, ...]) -> str:
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
        return '<span class="ow-trend-unavailable">Trend unavailable</span>'
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


def _trend_bar_svg(points: tuple[object, ...], *, tone: str = "neutral") -> str:
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
        return '<span class="ow-trend-unavailable">Trend unavailable</span>'
    low = min(finite)
    high = max(finite)
    span = high - low or 1.0
    bars = []
    for index, value in enumerate(finite[-12:]):
        height = 8 + ((value - low) / span) * 34
        x = index * 9
        y = 44 - height
        bars.append(f'<rect x="{x}" y="{y:.2f}" width="6" height="{height:.2f}" rx="1.4"></rect>')
    return (
        f'<svg class="ow-decision-bars" data-tone="{_html(tone)}" viewBox="0 0 108 48" '
        'aria-label="Trend bars" role="img">'
        + "".join(bars)
        + "</svg>"
    )


def _state_icon_svg(token: str) -> str:
    if token == "healthy":
        path = '<path d="M20 3 34 10v10c0 9-6 15-14 17C12 35 6 29 6 20V10Z"/><path d="m14 20 4 4 8-9"/>'
    elif token == "critical":
        path = '<path d="M20 4 36 34H4Z"/><path d="M20 14v9"/><path d="M20 29h.01"/>'
    elif token in {"stale", "offline"}:
        path = '<circle cx="20" cy="20" r="15"/><path d="M20 11v10l7 4"/>'
    else:
        path = '<path d="M20 3 34 10v11c0 8-6 14-14 16C12 35 6 29 6 21V10Z"/><path d="M20 12v12"/><path d="M20 29h.01"/>'
    return (
        f'<svg viewBox="0 0 40 40" class="ow-decision-state-svg" aria-hidden="true">'
        f'<g fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">{path}</g>'
        '</svg>'
    )


def _breadcrumb_html(parts: tuple[object, ...]) -> str:
    clean = [str(part or "").strip() for part in parts if str(part or "").strip()]
    if not clean:
        return ""
    return '<nav class="ow-page-breadcrumb" aria-label="Breadcrumb">' + "<span>&rsaquo;</span>".join(
        f"<strong>{_html(part)}</strong>" if index == len(clean) - 1 else f"<em>{_html(part)}</em>"
        for index, part in enumerate(clean)
    ) + "</nav>"


def _data_trust_summary(brief: SectionCommandBrief) -> str:
    age = "freshness unavailable"
    if brief.freshness_minutes is not None:
        age = f"Updated {int(round(float(brief.freshness_minutes)))}m ago"
    method = brief.data_availability_state or ("Stale" if brief.stale else "Allocated")
    confidence = brief.confidence or "unknown"
    source_note = ""
    if brief.required_source_count:
        source_note = f"{brief.available_source_count}/{brief.required_source_count} required sources"
    parts = [age]
    if source_note:
        parts.append(source_note)
    parts.append(method)
    parts.append(confidence)
    return " · ".join(str(part) for part in parts if part)


def _trust_detail_html(brief: SectionCommandBrief) -> str:
    requested = (
        f"{brief.requested_company or brief.company} / "
        f"{brief.requested_environment or brief.environment} / "
        f"{brief.requested_window_days or brief.window_label}"
    )
    resolved = (
        f"{brief.resolved_company or brief.company} / "
        f"{brief.resolved_environment or brief.environment} / "
        f"{brief.resolved_window_days or brief.requested_window_days} days"
    )
    fixture_badge = ""
    if isinstance(brief.raw_payload, dict) and brief.raw_payload.get("fixture_mode") is True:
        fixture_badge = '<div class="ow-fixture-badge">FIXTURE DATA</div>'
    rows = (
        ("Packet source", brief.source),
        ("Upstream sources", brief.source_objects),
        ("Requested scope", requested),
        ("Resolved scope", resolved),
        ("Target freshness", f"{brief.target_freshness_minutes} minutes"),
        (
            "Source coverage",
            f"{brief.available_source_count}/{brief.required_source_count} sources ({brief.source_coverage_pct or 0:.1f}%)",
        ),
        ("Missing sources", brief.source_gap_detail or "None reported"),
        ("Confidence", brief.confidence),
    )
    detail = fixture_badge + "".join(
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


def _render_detail_action(*, key_prefix: str, detail_action: CommandBriefDetailAction) -> None:
    if st.button(
        detail_action.label,
        key=detail_action.key or f"{key_prefix}_detail_{_key_token(detail_action.label)}",
        type="secondary",
        width="stretch",
        help=detail_action.help_text or None,
    ):
        detail_action.callback()
        st.rerun()


def _render_fallback(brief: SectionCommandBrief, *, key_prefix: str, detail_action: CommandBriefDetailAction | None) -> None:
    mode = workspace_mode_for_brief(brief)
    state = "offline" if mode == "OFFLINE" else "uninitialized"
    title = "Offline summary is not available" if mode == "OFFLINE" else "Summary not initialized"
    scope = f"{brief.company} / {brief.environment} / {brief.window_label}"
    message = (
        "Snowflake is not reachable from this session. Configure the connection or ask an administrator to refresh the Decision summary marts."
        if mode == "OFFLINE"
        else f"No current Decision packet exists for {scope}."
    )
    st.html(
        f'<section class="ow-decision-brief ow-decision-recovery ow-decision-operating-loop" '
        f'role="region" aria-label="Decision workspace {state}">'
        f'<div class="ow-decision-loop-header" data-state="{_html(state)}">'
        f'<strong>{_html(title)}</strong>'
        f'<span>{_html(_data_trust_summary(brief))}</span>'
        '</div>'
        f'<p class="ow-decision-loop-summary">{_html(_public_text(message))}</p>'
        '</section>'
    )
    cols = st.columns(2)
    with cols[0]:
        if st.button("Initialize summaries", key=f"{key_prefix}_initialize_summaries", width="stretch"):
            st.session_state["_overwatch_decision_bootstrap_requested"] = True
            st.rerun()
    with cols[1]:
        if detail_action is not None:
            _render_detail_action(key_prefix=key_prefix, detail_action=detail_action)


def _action_route_key(action: object) -> str:
    return str(getattr(action, "route_key", "") or "").strip()


def dedupe_command_actions(
    actions: Iterable[object],
    current_section: str,
    current_workflow: str = "",
) -> tuple[object, ...]:
    """Return one primary and up to two secondary safe route actions."""
    selected: list[object] = []
    seen_routes: set[str] = set()
    for action in tuple(actions or ()):
        route_key = _action_route_key(action)
        if not route_key or route_key in seen_routes or route_key not in COMMAND_BRIEF_ROUTES:
            continue
        route = COMMAND_BRIEF_ROUTES[route_key]
        if (
            route.section == current_section
            and current_workflow
            and route.workflow
            and route.workflow == current_workflow
        ):
            continue
        selected.append(action)
        seen_routes.add(route_key)
        if len(selected) == 3:
            break
    return tuple(selected)


def _apply_route_action(action: object) -> bool:
    route_key = _action_route_key(action)
    return bool(route_key and apply_command_brief_route(route_key))


def _metric_ribbon(model: DecisionWorkspaceViewModel, *, compact: bool) -> str:
    if compact:
        return ""
    cells: list[str] = []
    for metric in model.metric_cells[:4]:
        tone = _html(metric.tone or "neutral").lower()
        cells.append(
            f'<article class="ow-decision-metric-cell" data-tone="{tone}">'
            f'<div><span>{_html(metric.label)}</span><strong>{_html(metric.value)}</strong>'
            f'<small>{_html(metric.detail)}</small></div>'
            f'{_sparkline(metric.trend_points)}'
            '</article>'
        )
    return '<section class="ow-decision-metric-ribbon" aria-label="Primary metrics">' + "".join(cells) + "</section>"


def _render_model_attention_panel(model: DecisionWorkspaceViewModel) -> str:
    rows: list[str] = []
    for item in model.findings[:3]:
        rows.append(
            '<div class="ow-decision-attention-row">'
            f'<span class="ow-attention-icon" data-severity="{_html(item.severity).lower()}"></span>'
            f'<strong>{_html(item.severity)}</strong>'
            f'<div class="ow-attention-copy"><b>{_html(item.signal)}</b><small>{_html(item.detail or item.entity)}</small></div>'
            f'<div class="ow-attention-meta"><span>Owner</span><b>{_html(item.owner or "Assigned")}</b></div>'
            f'<div class="ow-attention-meta"><span>SLA</span><b>{_html(item.sla or "On track")}</b></div>'
            '</div>'
        )
    if not rows:
        rows.append(
            '<div class="ow-decision-attention-row ow-decision-clear-row">'
            '<span class="ow-attention-icon" data-severity="clear"></span>'
            '<strong>CLEAR</strong>'
            '<div class="ow-attention-copy"><b>No threshold breach in the command brief</b>'
            '<small>Continue monitoring; load evidence only when proof is needed.</small></div>'
            '<div class="ow-attention-meta"><span>Owner</span><b>Monitoring</b></div>'
            '<div class="ow-attention-meta"><span>SLA</span><b>On track</b></div>'
            '</div>'
        )
    return (
        '<section class="ow-decision-attention-panel">'
        '<h4>What needs attention</h4>'
        + "".join(rows)
        + '<a class="ow-decision-view-all">View all priorities &rsaquo;</a>'
        + '</section>'
    )


def _render_model_trend_band(model: DecisionWorkspaceViewModel) -> str:
    tiles: list[str] = []
    candidates = tuple(model.trends or model.metric_cells)
    for metric in candidates[:5]:
        tone = _html(metric.tone or "neutral").lower()
        tiles.append(
            f'<article class="ow-decision-trend-tile" data-tone="{tone}">'
            f'<span>{_html(metric.label)}</span>'
            f'<strong>{_html(metric.value)}</strong>'
            f'<small>{_html(metric.detail)}</small>'
            f'{_trend_bar_svg(metric.trend_points, tone=tone)}'
            '<div><em>Start</em><em>Now</em></div>'
            '</article>'
        )
        if len(tiles) == 5:
            break
    return (
        '<section class="ow-decision-trend-band">'
        '<h4>What changed</h4>'
        '<div class="ow-decision-trend-grid">'
        + "".join(tiles)
        + "</div></section>"
    ) if tiles else ""


def _render_model_trust_footer(model: DecisionWorkspaceViewModel) -> str:
    badge = '<b class="ow-fixture-badge">FIXTURE DATA</b>' if model.fixture_mode else ""
    return (
        '<footer class="ow-decision-trust-footer">'
        '<strong>Data Trust</strong>'
        f'{badge}'
        f'<span>{_html(model.trust.mode_label)}</span>'
        f'<span>{_html(model.trust.freshness_label)}</span>'
        f'<span>{_html(model.trust.target_label)}</span>'
        f'<span>{_html(model.trust.coverage_label)}</span>'
        f'<span>Data quality <b>{_html(model.trust.quality_label)}</b></span>'
        '<span class="ow-decision-source-trigger">View sources &dtri;</span>'
        '</footer>'
    )


def _render_hero_refresh(*, key_prefix: str, refresh_action: Callable[[], None] | None) -> None:
    if refresh_action is None:
        return
    st.markdown('<div class="ow-decision-hero-refresh-control">', unsafe_allow_html=True)
    if st.button(
        "Refresh",
        key=f"{key_prefix}_refresh_packet",
        type="secondary",
        width="stretch",
        help="Refresh the Decision packet for this scope",
    ):
        refresh_action()
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def _render_workspace_actions(
    model: DecisionWorkspaceViewModel,
    controls: CommandBriefControlSet,
    *,
    key_prefix: str,
) -> None:
    st.markdown('<div class="ow-decision-actions-panel-label">Recommended actions</div>', unsafe_allow_html=True)
    actions = dedupe_command_actions(controls.route_actions or model.actions, model.section, model.workflow)
    if actions:
        primary = actions[0]
        label = str(getattr(primary, "cta", "") or getattr(primary, "label", "") or "Open")
        key_source = str(getattr(primary, "action_key", "") or getattr(primary, "label", "") or "primary")
        if st.button(
            f"{label}  →",
            key=f"{key_prefix}_primary_{_key_token(key_source)}",
            type="primary",
            width="stretch",
        ):
            if _apply_route_action(primary):
                st.rerun()
        for index, action in enumerate(actions[1:3], start=1):
            label = str(getattr(action, "cta", "") or getattr(action, "label", "") or "Open")
            key_source = str(getattr(action, "action_key", "") or getattr(action, "label", "") or f"secondary_{index}")
            if st.button(
                f"{label}  →",
                key=f"{key_prefix}_secondary_{index}_{_key_token(key_source)}",
                type="secondary",
                width="stretch",
            ):
                if _apply_route_action(action):
                    st.rerun()
    if controls.evidence_action is not None:
        st.markdown('<div class="ow-decision-evidence-action-shell">', unsafe_allow_html=True)
        _render_detail_action(key_prefix=key_prefix, detail_action=controls.evidence_action)
        st.markdown("</div>", unsafe_allow_html=True)


def _extra_metrics_panel(metrics: tuple[DecisionMetricCell, ...]) -> str:
    extra = "".join(
        f'<div class="ow-decision-extra-metric"><strong>{_html(metric.label)}</strong>'
        f'<span>{_html(metric.value if metric.available else metric.availability_state)}</span>'
        f'<small>{_html(metric.detail)}</small></div>'
        for metric in metrics
    )
    return f'<div class="ow-decision-extra-metrics">{extra}</div>'


def render_decision_workspace(
    brief: SectionCommandBrief,
    *,
    breadcrumb: tuple[object, ...] | list[object] | None = None,
    current_workflow: str = "",
    key_prefix: str,
    refresh_action: Callable[[], None] | None = None,
    evidence_action: CommandBriefDetailAction | None = None,
    primary_action: Callable[[], None] | None = None,
    compact: bool = False,
) -> None:
    """Render the target OVERWATCH Decision Workspace layout."""
    workflow = current_workflow or str(brief.raw_payload.get("view") if isinstance(brief.raw_payload, dict) else "") or "Overview"
    model = build_decision_workspace_view_model(
        brief,
        current_workflow=workflow,
        evidence_action=evidence_action,
    )
    if brief.fallback_reason and not model.metric_cells:
        _render_fallback(brief, key_prefix=key_prefix, detail_action=evidence_action)
        return
    controls = CommandBriefControlSet(
        refresh_action=refresh_action or primary_action,
        route_actions=model.actions,
        evidence_action=evidence_action,
    )
    if compact:
        st.html(
            '<section class="ow-decision-context-strip">'
            f'<strong>{_html(model.state)}</strong>'
            f'<span>{_html(model.headline)}</span>'
            f'<small>{_html(model.trust.summary)}</small>'
            '</section>'
        )
        if controls.evidence_action is not None:
            _render_detail_action(key_prefix=key_prefix, detail_action=controls.evidence_action)
        return

    state = model.state_token
    parts = tuple(breadcrumb or (model.section, model.workflow))
    fixture_badge = '<b class="ow-fixture-badge">FIXTURE DATA</b>' if model.fixture_mode else ""
    hero = (
        '<section class="ow-decision-workspace" role="region" aria-label="OVERWATCH Decision Workspace">'
        f'{_breadcrumb_html(parts)}'
        '<div class="ow-decision-hero">'
        f'<div class="ow-decision-state-icon" data-state="{_html(state)}">{_state_icon_svg(state)}</div>'
        '<div class="ow-decision-state-copy">'
        f'<strong>{_html(model.state)} {fixture_badge}</strong>'
        f'<h2>{_html(model.headline)}</h2>'
        f'<p>{_html(model.summary)}</p>'
        '</div>'
        '<div class="ow-decision-refresh">'
        f'<b>{_html(model.trust.freshness_label)}</b>'
        f'<span>{_html(model.trust.target_label)}</span>'
        '</div>'
        '</div>'
        f'{_metric_ribbon(model, compact=False)}'
        '</section>'
    )
    st.html(hero)
    _render_hero_refresh(key_prefix=key_prefix, refresh_action=controls.refresh_action)
    left, right = st.columns([2.05, 0.95])
    with left:
        st.html(_render_model_attention_panel(model))
    with right:
        _render_workspace_actions(
            model,
            controls,
            key_prefix=key_prefix,
        )
    st.html(_render_model_trend_band(model) + _render_model_trust_footer(model))
    if tuple(brief.sources or ()) or brief.source_objects or model.fixture_mode:
        with st.expander("View sources", expanded=False):
            st.html(f'<div class="ow-decision-source-drawer">{_trust_detail_html(brief)}</div>')
    if getattr(model, "additional_metrics", ()):
        with st.expander("Additional brief metrics", expanded=False):
            st.html(_extra_metrics_panel(tuple(model.additional_metrics)))


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
    """Render a concise Decision Workspace with safe actions and accurate data trust."""
    if detail_action is None and on_detail is not None and brief.detail_cta:
        detail_action = CommandBriefDetailAction(brief.detail_cta, "", on_detail)
    if primary_action is None and on_primary_action is not None:
        primary_action = on_primary_action
    current_workflow = str(
        (brief.raw_payload.get("view") if isinstance(brief.raw_payload, dict) else "")
        or ("Overview" if not compact else "")
    )
    render_decision_workspace(
        brief,
        breadcrumb=(brief.section, current_workflow or "Overview"),
        current_workflow=current_workflow,
        key_prefix=key_prefix,
        refresh_action=primary_action,
        evidence_action=detail_action,
        compact=compact,
    )


__all__ = [
    "CommandBriefControlSet",
    "CommandBriefDetailAction",
    "dedupe_command_actions",
    "format_command_metric",
    "render_decision_workspace",
    "render_section_command_brief",
]
