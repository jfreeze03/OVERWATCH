"""Renderer for mart-backed section command briefs."""

from __future__ import annotations

from collections.abc import Callable
from html import escape as _escape_markup
import re

import streamlit as st

from navigation import queue_section_navigation
from sections.section_command_brief import SectionCommandAction, SectionCommandBrief


def _key_token(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "action"


def _html(value: object) -> str:
    return _escape_markup(str(value or "").strip())


def _metric_html(brief: SectionCommandBrief, *, limit: int = 4) -> str:
    cards: list[str] = []
    for metric in tuple(brief.metrics or ())[:limit]:
        tone = _html(metric.tone or "neutral").lower()
        detail = " | ".join(part for part in (metric.detail, metric.trend) if str(part or "").strip())
        cards.append(
            f'<article class="ow-command-metric" data-tone="{tone}">'
            f'<span>{_html(metric.label)}</span>'
            f'<strong>{_html(metric.value)}</strong>'
            f'<small>{_html(detail)}</small>'
            '</article>'
        )
    return "".join(cards)


def _additional_metric_html(brief: SectionCommandBrief) -> str:
    rows: list[str] = []
    for metric in tuple(brief.metrics or ())[4:]:
        detail = " | ".join(part for part in (metric.detail, metric.trend) if str(part or "").strip())
        rows.append(
            '<div class="ow-command-extra-metric">'
            f'<strong>{_html(metric.label)}</strong>'
            f'<span>{_html(metric.value)}</span>'
            f'<small>{_html(detail)}</small>'
            '</div>'
        )
    return "".join(rows)


def _signal_html(brief: SectionCommandBrief) -> str:
    signal = brief.top_signal
    if signal is None:
        return ""
    entity = f'<span class="ow-command-signal-entity">{_html(signal.entity)}</span>' if signal.entity else ""
    return (
        '<section class="ow-command-top-signal" aria-label="Top signal">'
        f'<div class="ow-command-signal-severity">{_html(signal.severity)}</div>'
        f'<strong>{_html(signal.signal)}</strong>'
        f'{entity}'
        f'<p>{_html(signal.detail)}</p>'
        '</section>'
    )


def _action_matches(action: SectionCommandAction, *, section: str, workflow: str = "") -> bool:
    if not action.target_section:
        return False
    if action.target_section != section:
        return False
    if workflow and action.target_workflow != workflow:
        return False
    return True


def _apply_action(action: SectionCommandAction) -> None:
    target = str(action.target_section or "")
    workflow = str(action.target_workflow or "")
    if workflow:
        if target == "Cost & Contract":
            st.session_state["cost_contract_workflow"] = workflow
            if workflow == "Cost Explorer" and str(action.route_key or "").endswith("_warehouse"):
                st.session_state["cc_explorer_lens"] = "Warehouse"
        elif target == "Alert Center":
            st.session_state["alert_center_requested_view"] = workflow
            st.session_state["alert_center_active_view"] = workflow
        elif target == "DBA Control Room":
            st.session_state["dba_control_room_active_view"] = workflow
        elif target == "Workload Operations":
            st.session_state["workload_operations_workflow"] = workflow
        elif target == "Security Monitoring":
            st.session_state["security_posture_view"] = workflow
            st.session_state["security_posture_workflow"] = workflow
        elif target == "Executive Landing":
            st.session_state["executive_landing_workflow"] = workflow
    if target:
        queue_section_navigation(target)


def _render_action_buttons(brief: SectionCommandBrief, *, key_prefix: str, on_primary_action: Callable[[], None] | None) -> None:
    actions = tuple(brief.next_actions or ())[:3]
    if not actions:
        return
    primary = actions[0]
    secondary = actions[1:3]
    st.html('<div class="ow-command-action-row" aria-label="Command brief actions"></div>')
    cols = st.columns(1 + len(secondary))
    with cols[0]:
        label = primary.cta or primary.label
        if st.button(label, key=f"{key_prefix}_primary_{_key_token(primary.label)}", type="primary", width="stretch"):
            if on_primary_action is not None:
                on_primary_action()
            else:
                _apply_action(primary)
            st.rerun()
    for idx, action in enumerate(secondary, start=1):
        with cols[idx]:
            label = action.cta or action.label
            if st.button(label, key=f"{key_prefix}_secondary_{idx}_{_key_token(action.label)}", width="stretch"):
                _apply_action(action)
                st.rerun()


def _render_detail_button(
    brief: SectionCommandBrief,
    *,
    key_prefix: str,
    on_detail: Callable[[], None] | None,
) -> None:
    if not brief.detail_cta:
        return
    disabled = on_detail is None and not brief.detail_available
    if st.button(
        brief.detail_cta,
        key=f"{key_prefix}_detail_{_key_token(brief.detail_cta)}",
        type="primary",
        width="stretch",
        disabled=disabled,
    ):
        if on_detail is not None:
            on_detail()
        st.rerun()


def _render_fallback(brief: SectionCommandBrief, *, key_prefix: str, on_detail: Callable[[], None] | None) -> None:
    last_known = "No last known good brief is available."
    if brief.stale and brief.source_snapshot_ts:
        last_known = f"Last known good source snapshot: {brief.source_snapshot_ts}."
    st.html(
        '<section class="ow-command-brief ow-command-brief-fallback" role="region" aria-label="Section command brief unavailable">'
        '<div class="ow-command-status-band" data-state="unavailable">'
        '<span>Summary unavailable</span>'
        f'<strong>{_html(brief.headline)}</strong>'
        f'<p>{_html(brief.fallback_reason or brief.summary)}</p>'
        '</div>'
        '<section class="ow-command-top-signal" aria-label="Command brief setup status">'
        '<div class="ow-command-signal-severity">Setup</div>'
        f'<strong>{_html(brief.top_signal.signal if brief.top_signal else "Command mart unavailable")}</strong>'
        f'<p>{_html(last_known)}</p>'
        '</section>'
        f'<footer class="ow-command-footer"><span>Requested: {_html(brief.company)} / {_html(brief.environment)} / {_html(brief.window_label)}</span>'
        f'<span>Source: {_html(brief.source)}</span></footer>'
        '</section>'
    )
    _render_detail_button(brief, key_prefix=key_prefix, on_detail=on_detail)


def render_section_command_brief(
    brief: SectionCommandBrief,
    *,
    key_prefix: str,
    on_primary_action: Callable[[], None] | None = None,
    on_detail: Callable[[], None] | None = None,
    compact: bool = False,
) -> None:
    """Render a concise command brief with a real detail-load boundary."""
    if brief.fallback_reason and not tuple(brief.metrics or ()):
        _render_fallback(brief, key_prefix=key_prefix, on_detail=on_detail)
        return

    metric_body = "" if compact else _metric_html(brief, limit=4)
    source_scope = (
        f"Requested: {_html(brief.requested_company or brief.company)} / "
        f"{_html(brief.requested_environment or brief.environment)} / "
        f"{_html(brief.requested_window_days or brief.window_label)}"
    )
    resolved = ""
    if brief.resolved_company or brief.resolved_environment:
        resolved = (
            f"<span>Resolved: {_html(brief.resolved_company)} / {_html(brief.resolved_environment)} / "
            f"{_html(brief.resolved_window_days or '')} days</span>"
        )
    stale = " stale" if brief.stale else ""
    st.html(
        f'<section class="ow-command-brief{stale}" role="region" aria-label="Section command brief">'
        '<div class="ow-command-status-band">'
        f'<span>{_html(brief.state)}</span>'
        f'<strong>{_html(brief.headline)}</strong>'
        f'<p>{_html(brief.summary)}</p>'
        f'<small>{_html(brief.freshness_label)}</small>'
        '</div>'
        f'<div class="ow-command-metric-strip">{metric_body}</div>'
        f'{_signal_html(brief)}'
        f'<footer class="ow-command-footer"><span>Packet: {_html(brief.source)}</span>'
        f'<span>Upstream: {_html(brief.source_objects)}</span><span>{source_scope}</span>{resolved}'
        f'<span>Confidence: {_html(brief.confidence)}</span></footer>'
        '</section>'
    )
    if not compact:
        extra = _additional_metric_html(brief)
        if extra:
            with st.expander("More command brief metrics", expanded=False):
                st.html(f'<div class="ow-command-extra-metrics">{extra}</div>')
        _render_action_buttons(brief, key_prefix=key_prefix, on_primary_action=on_primary_action)
    _render_detail_button(brief, key_prefix=key_prefix, on_detail=on_detail)


__all__ = ["render_section_command_brief"]
