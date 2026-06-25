"""Renderer for mart-backed section command briefs."""

from __future__ import annotations

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


def _metric_html(brief: SectionCommandBrief) -> str:
    cards: list[str] = []
    for metric in tuple(brief.metrics or ())[:8]:
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


def _apply_action(action: SectionCommandAction) -> None:
    if action.target_section:
        queue_section_navigation(action.target_section)
    for key, value in tuple(action.session_state_updates or ()):
        st.session_state[str(key)] = value
    if action.target_workflow:
        target = str(action.target_section or "")
        workflow = str(action.target_workflow)
        if target == "Cost & Contract":
            st.session_state["cost_contract_workflow"] = workflow
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


def _render_action_strip(brief: SectionCommandBrief, *, key_prefix: str) -> None:
    actions = tuple(brief.next_actions or ())[:4]
    if not actions:
        return
    st.html('<div class="ow-command-action-strip" aria-label="Command brief actions"></div>')
    cols = st.columns(min(4, len(actions)))
    for idx, action in enumerate(actions):
        with cols[idx % len(cols)]:
            st.html(
                '<article class="ow-command-brief-action">'
                f'<strong>{_html(action.label)}</strong>'
                f'<span>{_html(action.detail)}</span>'
                '</article>'
            )
            if st.button(action.cta or action.label, key=f"{key_prefix}_{idx}_{_key_token(action.label)}", width="stretch"):
                _apply_action(action)
                st.rerun()


def render_section_command_brief(brief: SectionCommandBrief, *, key_prefix: str) -> None:
    """Render status, metrics, top signal, actions, and source freshness for a command brief."""
    metric_body = _metric_html(brief)
    fallback = (
        f'<div class="ow-command-fallback">{_html(brief.fallback_reason)}</div>'
        if brief.fallback_reason
        else ""
    )
    st.html(
        '<section class="ow-command-brief" role="region" aria-label="Section command brief">'
        '<div class="ow-command-status-band">'
        f'<span>{_html(brief.state)}</span>'
        f'<strong>{_html(brief.headline)}</strong>'
        f'<p>{_html(brief.summary)}</p>'
        '</div>'
        f'<div class="ow-command-metric-strip">{metric_body}</div>'
        f'{_signal_html(brief)}'
        '<div class="ow-command-detail-boundary">'
        f'<strong>Detail boundary</strong><span>{_html(brief.detail_cta)} loads deeper evidence when needed.</span>'
        '</div>'
        f'<footer class="ow-command-footer"><span>Source: {_html(brief.source)}</span>'
        f'<span>{_html(brief.freshness_label)}</span><span>Scope: {_html(brief.company)} / {_html(brief.environment)} / {_html(brief.window_label)}</span></footer>'
        f'{fallback}'
        '</section>'
    )
    _render_action_strip(brief, key_prefix=key_prefix)


__all__ = ["render_section_command_brief"]
