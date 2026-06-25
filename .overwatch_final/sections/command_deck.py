"""Shared Command Deck renderer for query-on-demand section shells."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from html import escape as _escape_markup
import re

import streamlit as st

from navigation import queue_section_navigation
from sections.command_deck_contracts import CommandDeckAction, SectionCommandDeckContract
from sections.command_deck_contracts import get_command_deck_contract
from sections.operator_case import render_case_drawer
from sections.shell_helpers import render_escaped_bold_text, render_shell_snapshot
from sections.ui_compat import safe_button, safe_caption


def _key_token(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "action"


def apply_command_deck_action(
    action: CommandDeckAction,
    state: MutableMapping[str, object],
) -> None:
    """Apply route-only state updates for a Command Deck action."""
    for key, value in action.session_state_updates:
        state[str(key)] = value
    if action.target_section:
        queue_section_navigation(action.target_section)


def _render_deck_header(contract: SectionCommandDeckContract) -> None:
    """Render escaped Command Deck framing copy."""
    section = _escape_markup(str(contract.section or "Command Deck"))
    primary = _escape_markup(str(contract.primary_cta or "Open evidence"))
    boundary = _escape_markup(str(contract.evidence_boundary or "Evidence remains explicit."))
    st.html(
        '<section class="ow-command-deck" role="region" '
        f'aria-label="{section} command deck">'
        '<div class="ow-command-deck-kicker">Command Deck</div>'
        f'<div class="ow-command-deck-title">{section}</div>'
        f'<div class="ow-command-deck-primary"><span>Primary CTA</span><strong>{primary}</strong></div>'
        f'<div class="ow-command-deck-boundary">{boundary}</div>'
        '</section>'
    )


def _render_action_context(action: CommandDeckAction) -> None:
    """Render escaped route-action copy before the native button."""
    label = _escape_markup(str(action.label or "Route action"))
    detail = _escape_markup(str(action.description or "Route without loading evidence."))
    st.html(
        '<div class="ow-command-action" role="group">'
        f'<div class="ow-command-action-label">{label}</div>'
        f'<div class="ow-command-action-detail">{detail}</div>'
        '</div>'
    )


def render_command_deck(
    contract: SectionCommandDeckContract,
    *,
    key_prefix: str | None = None,
    on_action: Callable[[CommandDeckAction], None] | None = None,
    on_primary_cta: Callable[[], None] | None = None,
) -> None:
    """Render first-paint route actions without starting telemetry work."""
    prefix = key_prefix or f"command_deck_{_key_token(contract.section)}"
    with st.container(border=True):
        _render_deck_header(contract)
        render_shell_snapshot(
            (
                ("Route status", "Ready"),
                ("Evidence boundary", "Explicit load only"),
            )
        )
        if contract.primary_cta_description:
            safe_caption(contract.primary_cta_description)
        if on_primary_cta is not None:
            if safe_button(
                contract.primary_cta,
                key=contract.primary_cta_key,
                width="stretch",
                type="primary",
                help=contract.evidence_boundary,
            ):
                on_primary_cta()
        elif contract.primary_cta_preserve_existing:
            safe_caption("Primary evidence loading remains on the existing section control.")
        safe_caption(contract.no_query_note)

        actions = tuple(contract.route_actions or ())
        if not actions:
            return

        cols = st.columns(min(3, len(actions)))
        for idx, action in enumerate(actions):
            with cols[idx % len(cols)]:
                _render_action_context(action)
                button_key = f"{prefix}_{idx}_{_key_token(action.label)}"
                if safe_button(action.label, key=button_key, width="stretch"):
                    apply_command_deck_action(action, st.session_state)
                    if on_action is not None:
                        on_action(action)
                    st.rerun()
        render_case_drawer()


def render_command_deck_for_section(section: str, *, key_prefix: str | None = None) -> None:
    """Render the Command Deck contract for a canonical section."""
    render_command_deck(get_command_deck_contract(section), key_prefix=key_prefix)


__all__ = [
    "apply_command_deck_action",
    "render_command_deck",
    "render_command_deck_for_section",
]
