"""Renderer for mart-backed OVERWATCH Decision Briefs."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from html import escape as _escape_markup
import math
import re

import streamlit as st

from utils.performance import (
    ADMIN_CLICK_QUERY_BUDGET,
    SECTION_ROUTE_QUERY_BUDGET,
    current_first_paint_render_id,
    end_first_paint,
    query_budget_context,
)
from runtime_state import set_state
from sections.command_brief_routes import COMMAND_BRIEF_ROUTES, apply_command_brief_route
from sections.decision_workspace_controls import (
    CommandBriefDetailAction,
    DecisionWorkspaceControls,
    apply_finding_evidence_target,
    render_evidence_settings,
)
from sections.decision_workspace_components import (
    render_command_brief as _kit_command_brief,
    render_data_trust_footer as _kit_data_trust_footer,
    render_metric_row as _kit_metric_row,
    render_signal_panel as _kit_signal_panel,
)
from sections.decision_workspace_setup_health import can_open_decision_setup_health, open_decision_setup_health
from sections.decision_workspace_bootstrap import BOOTSTRAP_REQUEST_KEY
from sections.decision_workspace_view_model import (
    DecisionActionView,
    DecisionMetricCell,
    DecisionWorkspaceViewModel,
    build_decision_workspace_view_model,
    format_metric_value,
)
from sections.section_command_brief import SectionCommandBrief
from utils.display_safety import safe_source_label, scrub_daily_text

_COMMAND_BRIEF_HTML = _kit_command_brief


def _section_display_label(value: object) -> str:
    text = str(value or "").strip()
    return "Cost Intelligence" if text == "Cost & Contract" else text


def _key_token(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "action"


def _html(value: object) -> str:
    return _escape_markup(str(value or "").strip())


def _public_text(value: object) -> str:
    """Remove Snowflake implementation names from first-viewport user copy."""
    text = scrub_daily_text(value)
    text = re.sub(r"\bsnowflake/[A-Za-z0-9_./-]+\.sql\b", "setup script", text, flags=re.IGNORECASE)
    return text


def _bootstrap_attempt_note() -> str:
    """Return a daily-safe setup-attempt note for uninitialized packet states."""
    raw = st.session_state.get("_overwatch_decision_setup_health")
    if not isinstance(raw, dict):
        return ""
    status = str(raw.get("status", "") or "").strip().upper()
    if not status or status in {"SUCCESS", "PASSED"}:
        return ""
    packet_count = 0
    try:
        packet_count = int(raw.get("current_packet_count") or 0)
    except Exception:
        packet_count = 0
    selected_scope_status = str(raw.get("selected_scope_status", "") or "").strip().upper()
    if packet_count > 0 and selected_scope_status == "SUCCESS" and status == "DEGRADED":
        return (
            "Initialization created Decision summaries with setup warnings. "
            "Review Setup Health in Settings before relying on this scope."
        )
    return (
        "Last initialization attempt did not create a current Decision packet. "
        "The table definitions may exist, but the complete setup and refresh step still has to run."
    )


def _close_first_paint_for_user_action() -> None:
    """Keep explicit button work out of first-paint performance accounting."""
    render_id = current_first_paint_render_id()
    if render_id:
        end_first_paint(render_id)


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
        return ""
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
    display_clean = [_section_display_label(part) for part in clean]
    return '<nav class="ow-page-breadcrumb" aria-label="Breadcrumb">' + "<span>&rsaquo;</span>".join(
        f"<strong>{_html(part)}</strong>" if index == len(display_clean) - 1 else f"<em>{_html(part)}</em>"
        for index, part in enumerate(display_clean)
    ) + "</nav>"


def _trust_detail_html(model: DecisionWorkspaceViewModel) -> str:
    fixture_badge = (
        '<div class="ow-fixture-badge">FIXTURE DATA</div>'
        if model.fixture_badge_label
        else ""
    )
    rows = (
        ("Mode", model.trust.mode_label),
        ("Freshness", model.trust.freshness_label),
        ("Target", model.trust.target_label),
        ("Coverage", model.trust.coverage_label),
        ("Confidence", model.trust.quality_label),
    )
    detail = fixture_badge + "".join(
        f'<div class="ow-decision-trust-detail"><strong>{_html(label)}</strong><span>{_html(value)}</span></div>'
        for label, value in rows
    )
    source_rows = []
    for source in model.source_rows:
        required = "required" if source.required else "optional"
        meta = " / ".join(
            part
            for part in (
                source.status,
                required,
                source.environment_scope_label,
                source.age_label,
                source.target_label,
            )
            if part
        )
        source_rows.append(
            '<div class="ow-decision-source-row">'
            f'<strong>{_html(safe_source_label(source.source_label or source.source_object, source_key=source.source_key))}</strong>'
            f'<span>{_html(source.environment_scope_label or source.status)}</span>'
            f'<span>{_html(meta)}</span>'
            f'<small>{_html(_public_text(source.gap_reason or source.confidence or "No source gap reported"))}</small>'
            '</div>'
        )
    if source_rows:
        detail += '<div class="ow-decision-source-table" aria-label="Command brief source health">' + "".join(source_rows) + "</div>"
    if model.fallback is not None and model.fallback.technical_summary:
        detail += (
            '<div class="ow-decision-trust-detail"><strong>Summary</strong>'
            f'<span>{_html(model.fallback.technical_summary)}</span></div>'
        )
    return detail


def _render_detail_action(
    *,
    key_prefix: str,
    detail_action: CommandBriefDetailAction,
    evidence_target: object | None = None,
    section: str = "",
    workflow: str = "",
) -> None:
    if st.button(
        detail_action.label,
        key=detail_action.key or f"{key_prefix}_detail_{_key_token(detail_action.label)}",
        type="secondary",
        width="stretch",
        help=detail_action.help_text or None,
    ):
        _close_first_paint_for_user_action()
        apply_finding_evidence_target(evidence_target, section, workflow)
        detail_action.callback()
        st.rerun()


def _render_fallback(
    model: DecisionWorkspaceViewModel,
    *,
    key_prefix: str,
    refresh_action: Callable[[], None] | None,
    detail_action: CommandBriefDetailAction | None,
) -> None:
    fallback = model.fallback
    if fallback is None:
        return
    fallback_metrics = tuple(model.metric_cells)
    if len(fallback_metrics) < 3:
        fallback_metrics = (
            DecisionMetricCell(
                key="summary_packet_state",
                label="Summary",
                value=fallback.title,
                detail="Packet",
                tone="warning",
            ),
            DecisionMetricCell(
                key="source_status",
                label="Source status",
                value=model.trust.quality_label or "Unavailable",
                detail=model.trust.freshness_label or "Freshness unavailable",
                tone="warning",
            ),
            DecisionMetricCell(
                key="evidence_state",
                label="Evidence",
                value="On request",
                detail="Use the action buttons below",
                tone="neutral",
            ),
        )
    fallback_actions: list[DecisionActionView] = []
    if refresh_action is not None:
        fallback_actions.append(DecisionActionView(label="Refresh", cta="Refresh"))
    if fallback.can_initialize:
        fallback_actions.append(DecisionActionView(label=fallback.recovery_label, cta=fallback.recovery_label))
    if detail_action is not None and fallback.can_show_evidence:
        fallback_actions.append(DecisionActionView(label=detail_action.label, cta=detail_action.label))
    fallback_model = replace(
        model,
        state=fallback.title,
        state_token=fallback.mode,
        headline=fallback.title,
        summary=_public_text(fallback.message),
        metric_cells=fallback_metrics,
        actions=tuple(fallback_actions[:3]),
    )
    with st.container(key=f"{key_prefix}_decision_workspace_shell", border=False):
        st.html(
            f'<div class="ow-decision-workspace-marker" data-section="{_html(model.section)}" '
            f'data-workflow="{_html(model.workflow)}" aria-hidden="true"></div>'
            + _COMMAND_BRIEF_HTML(fallback_model)
        )
        actions = []
        if refresh_action is not None:
            actions.append("refresh")
        if fallback.can_initialize:
            actions.append("initialize")
            if can_open_decision_setup_health():
                actions.append("setup_health")
            else:
                st.html(
                    '<p class="ow-decision-admin-note">'
                    "Ask an administrator to review Decision summary setup health."
                    "</p>"
                )
        attempt_note = _bootstrap_attempt_note()
        if attempt_note:
            st.html(
                '<p class="ow-decision-admin-note">'
                f"{_html(attempt_note)}"
                "</p>"
            )
        if detail_action is not None and fallback.can_show_evidence:
            actions.append("evidence")
        if not actions:
            return
        cols = st.columns(len(actions))
        for idx, action in enumerate(actions):
            with cols[idx]:
                if action == "refresh" and st.button(
                    "Refresh",
                    key=f"{key_prefix}_fallback_refresh_packet",
                    type="secondary",
                    width="stretch",
                    help="Refresh the Decision packet for this scope",
                ):
                    _close_first_paint_for_user_action()
                    refresh_action()
                    st.rerun()
                elif action == "initialize" and st.button(
                    fallback.recovery_label,
                    key=f"{key_prefix}_initialize_summaries",
                    width="stretch",
                ):
                    _close_first_paint_for_user_action()
                    with query_budget_context(
                        "admin_setup",
                        section=model.section,
                        workflow=model.workflow or "Decision Summary Initialization",
                        budget=ADMIN_CLICK_QUERY_BUDGET,
                    ):
                        st.session_state[BOOTSTRAP_REQUEST_KEY] = True
                    st.rerun()
                elif action == "setup_health" and st.button(
                    "Open Setup Health",
                    key=f"{key_prefix}_open_setup_health",
                    type="secondary",
                    width="stretch",
                    help="Open Settings to review Decision summary setup health.",
                ):
                    _close_first_paint_for_user_action()
                    with query_budget_context(
                        "route_action",
                        section=model.section,
                        workflow=model.workflow,
                        budget=SECTION_ROUTE_QUERY_BUDGET,
                    ):
                        open_decision_setup_health()
                    st.rerun()
                elif action == "evidence":
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


def _finding_for_action(model: DecisionWorkspaceViewModel, action: object) -> object | None:
    route_key = _action_route_key(action)
    if route_key:
        for finding in model.findings:
            if str(getattr(finding, "route_key", "") or "").strip() == route_key:
                return finding
    return model.findings[0] if model.findings else None


def _priority_route_action(model: DecisionWorkspaceViewModel) -> DecisionActionView | None:
    fallback_routes = {
        "Executive Landing": "executive_overview",
        "DBA Control Room": "dba_failures",
        "Alert Center": "alert_center_active",
        "Cost & Contract": "cost_contract_overview",
        "Workload Operations": "workload_query_investigation",
        "Security Monitoring": "security_overview",
    }
    route_key = fallback_routes.get(model.section, "")
    if route_key in COMMAND_BRIEF_ROUTES:
        return DecisionActionView(
            label="View all priorities",
            cta="View all priorities",
            action_key="view_all_priorities",
            route_key=route_key,
        )
    return None


def _apply_route_action(action: object, *, finding: object | None, section: str, workflow: str) -> bool:
    with query_budget_context("route_action", section=section, workflow=workflow, budget=SECTION_ROUTE_QUERY_BUDGET):
        route_key = _action_route_key(action)
        route = COMMAND_BRIEF_ROUTES.get(route_key)
        target_section = route.section if route is not None else section
        target_workflow = route.workflow if route is not None else workflow
        apply_finding_evidence_target(finding, target_section, target_workflow)
        if route is not None:
            for state_key, state_value in route.state_updates:
                set_state(state_key, state_value)
        return bool(route_key and apply_command_brief_route(route_key))


def _metric_ribbon(model: DecisionWorkspaceViewModel, *, compact: bool) -> str:
    if compact:
        return ""
    return _kit_metric_row(model.metric_cells[:5], min_count=3, max_count=5)


def _render_model_attention_panel(model: DecisionWorkspaceViewModel) -> str:
    return _kit_signal_panel(model.findings, title="What needs attention")


def _render_model_trend_band(model: DecisionWorkspaceViewModel) -> str:
    tiles: list[str] = []
    candidates = tuple(model.trends or model.metric_cells)
    partial_count = sum(1 for metric in candidates if str(metric.trend_quality or "").lower() == "partial")
    has_partial = partial_count > 0
    partial_badge = '<span class="ow-decision-trend-quality">partial source history</span>' if has_partial else ""
    for metric in candidates[:5]:
        trend_svg = _trend_bar_svg(metric.trend_points, tone=metric.tone or "neutral")
        if not trend_svg:
            continue
        tone = _html(metric.tone or "neutral").lower()
        tiles.append(
            f'<article class="ow-decision-trend-tile" data-tone="{tone}">'
            f'<span>{_html(metric.label)}</span>'
            f'<strong>{_html(metric.value)}</strong>'
            f'<small>{_html(metric.detail)}</small>'
            f'{trend_svg}'
            '<div><em>Start</em><em>Now</em></div>'
            '</article>'
        )
        if len(tiles) == 5:
            break
    if not tiles:
        return (
            '<section class="ow-decision-trend-band ow-decision-trend-empty">'
            '<h4>What changed</h4>'
            '<p>Trend unavailable. No governed trend metadata in this packet.</p>'
            '</section>'
        )
    return (
        '<section class="ow-decision-trend-band">'
        f'<h4>What changed {partial_badge}</h4>'
        '<div class="ow-decision-trend-grid">'
        + "".join(tiles)
        + "</div>"
        + (f'<p class="ow-decision-trend-meta">Trend history: {partial_count} partial</p>' if partial_count else "")
        + "</section>"
    )


def _render_model_trust_footer(model: DecisionWorkspaceViewModel) -> str:
    source_labels = tuple(source.source_label or source.source_object or source.source_key for source in model.source_rows)
    return _kit_data_trust_footer(
        mode=model.trust.mode_label,
        freshness=model.trust.freshness_label,
        target=model.trust.target_label,
        coverage=model.trust.coverage_label,
        quality=model.trust.quality_label,
        source_labels=source_labels,
    )


def _render_workspace_actions(
    model: DecisionWorkspaceViewModel,
    controls: DecisionWorkspaceControls,
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
            f"{label} ->",
            key=f"{key_prefix}_primary_{_key_token(key_source)}",
            type="primary",
            width="stretch",
        ):
            _close_first_paint_for_user_action()
            if _apply_route_action(
                primary,
                finding=_finding_for_action(model, primary),
                section=model.section,
                workflow=model.workflow,
            ):
                st.rerun()
        for index, action in enumerate(actions[1:3], start=1):
            label = str(getattr(action, "cta", "") or getattr(action, "label", "") or "Open")
            key_source = str(getattr(action, "action_key", "") or getattr(action, "label", "") or f"secondary_{index}")
            if st.button(
                f"{label} ->",
                key=f"{key_prefix}_secondary_{index}_{_key_token(key_source)}",
                type="secondary",
                width="stretch",
            ):
                _close_first_paint_for_user_action()
                if _apply_route_action(
                    action,
                    finding=_finding_for_action(model, action),
                    section=model.section,
                    workflow=model.workflow,
                ):
                    st.rerun()
    if controls.evidence_action is not None:
        st.markdown('<div class="ow-decision-evidence-action-shell">', unsafe_allow_html=True)
        top_finding = model.findings[0] if model.findings else None
        _render_detail_action(
            key_prefix=key_prefix,
            detail_action=controls.evidence_action,
            evidence_target=top_finding,
            section=model.section,
            workflow=model.workflow,
        )
        settings_renderer = controls.evidence_action.settings_renderer or controls.evidence_settings
        if settings_renderer is not None:
            render_evidence_settings(controls.evidence_action.settings_label, settings_renderer)
        st.markdown("</div>", unsafe_allow_html=True)


def _command_brief_render_model(
    model: DecisionWorkspaceViewModel,
    controls: DecisionWorkspaceControls,
) -> DecisionWorkspaceViewModel:
    """Return the view model shape used by the shared UI-kit CommandBrief."""

    route_actions = dedupe_command_actions(controls.route_actions or model.actions, model.section, model.workflow)
    actions = list(route_actions or model.actions)
    if controls.evidence_action is not None:
        actions.append(
            DecisionActionView(
                label=controls.evidence_action.label,
                cta=controls.evidence_action.label,
                action_key="load_evidence",
            )
        )
    if not actions:
        priority_action = _priority_route_action(model)
        if priority_action is not None:
            actions.append(priority_action)
    return replace(model, actions=tuple(actions[:3]))


def _extra_metrics_panel(metrics: tuple[DecisionMetricCell, ...]) -> str:
    extra = "".join(
        f'<div class="ow-decision-extra-metric"><strong>{_html(metric.label)}</strong>'
        f'<span>{_html(metric.value if metric.available else metric.availability_state)}</span>'
        f'<small>{_html(" / ".join(part for part in (metric.detail, metric.trend_quality, metric.zero_fill_policy) if part))}</small></div>'
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
    controls: DecisionWorkspaceControls | None = None,
    compact: bool = False,
) -> None:
    """Render the target OVERWATCH Decision Workspace layout."""
    workflow = current_workflow or "Overview"
    model = build_decision_workspace_view_model(
        brief,
        current_workflow=workflow,
        evidence_action=evidence_action,
    )
    controls = controls or DecisionWorkspaceControls(
        section=model.section,
        current_workflow=model.workflow,
        refresh_packet=refresh_action or primary_action,
        route_actions=model.actions,
        evidence_action=evidence_action,
        can_refresh=bool(refresh_action or primary_action),
        can_load_evidence=evidence_action is not None,
    )
    if model.fallback is not None and not model.metric_cells:
        _render_fallback(
            model,
            key_prefix=key_prefix,
            refresh_action=controls.refresh_packet if controls.can_refresh else None,
            detail_action=controls.evidence_action,
        )
        return
    if compact:
        st.html(
            '<section class="ow-decision-context-strip ow-decision-workspace-marker">'
            f'<strong>{_html(model.state)}</strong>'
            f'<span>{_html(model.headline)}</span>'
            f'<small>{_html(model.trust.summary)}</small>'
            '</section>'
        )
        if controls.evidence_action is not None:
            top_finding = model.findings[0] if model.findings else None
            _render_detail_action(
                key_prefix=key_prefix,
                detail_action=controls.evidence_action,
                evidence_target=top_finding,
                section=model.section,
                workflow=model.workflow,
            )
        return

    parts = tuple(breadcrumb or (model.section, model.workflow))
    with st.container(key=f"{key_prefix}_decision_workspace_shell", border=False):
        st.html(
            f'<div class="ow-decision-workspace-marker" data-section="{_html(model.section)}" '
            f'data-workflow="{_html(model.workflow)}" role="region" '
            'aria-label="OVERWATCH Decision Workspace"></div>'
        )
        st.html(_breadcrumb_html(parts))
        st.html(_kit_command_brief(_command_brief_render_model(model, controls)))
        action_left, action_right = st.columns([0.42, 0.58])
        with action_left:
            if controls.can_refresh and controls.refresh_packet is not None and st.button(
                "Refresh",
                key=f"{key_prefix}_refresh_packet",
                type="secondary",
                width="stretch",
                help="Refresh the Decision packet for this scope",
            ):
                _close_first_paint_for_user_action()
                controls.refresh_packet()
                st.rerun()
            priority_action = _priority_route_action(model)
            if priority_action is not None and st.button(
                "View all priorities",
                key=f"{key_prefix}_view_all_priorities",
                type="secondary",
                width="stretch",
                help="Open the current section priority list without loading row evidence.",
            ):
                _close_first_paint_for_user_action()
                if _apply_route_action(
                    priority_action,
                    finding=_finding_for_action(model, priority_action),
                    section=model.section,
                    workflow=model.workflow,
                ):
                    st.rerun()
        with action_right:
            _render_workspace_actions(model, controls, key_prefix=key_prefix)
        if model.has_sources:
            with st.expander("Data Trust details", expanded=False):
                st.html(f'<div class="ow-decision-source-drawer">{_trust_detail_html(model)}</div>')
        if getattr(model, "additional_metrics", ()):
            with st.expander("Additional brief metrics", expanded=False):
                st.html(_extra_metrics_panel(tuple(model.additional_metrics)))


def render_section_command_brief(
    brief: SectionCommandBrief,
    *,
    key_prefix: str,
    current_workflow: str = "",
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
    current_workflow = current_workflow or ("Overview" if not compact else "")
    render_decision_workspace(
        brief,
        breadcrumb=(brief.section, current_workflow or "Overview"),
        current_workflow=current_workflow,
        key_prefix=key_prefix,
        refresh_action=primary_action,
        evidence_action=detail_action,
        controls=DecisionWorkspaceControls(
            section=brief.section,
            current_workflow=current_workflow,
            refresh_packet=primary_action,
            route_actions=(),
            evidence_action=detail_action,
            can_refresh=primary_action is not None,
            can_load_evidence=detail_action is not None,
        ),
        compact=compact,
    )


__all__ = [
    "CommandBriefDetailAction",
    "dedupe_command_actions",
    "format_command_metric",
    "render_decision_workspace",
    "render_section_command_brief",
]
