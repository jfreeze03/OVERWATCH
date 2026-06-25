"""Shared Command Deck renderer for query-on-demand section shells."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
import re

import streamlit as st

from navigation import queue_section_navigation
from sections.command_deck_contracts import CommandDeckAction, SectionCommandDeckContract
from sections.command_deck_contracts import get_command_deck_contract
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


def render_command_deck(
    contract: SectionCommandDeckContract,
    *,
    key_prefix: str | None = None,
    on_action: Callable[[CommandDeckAction], None] | None = None,
) -> None:
    """Render first-paint route actions without starting telemetry work."""
    prefix = key_prefix or f"command_deck_{_key_token(contract.section)}"
    with st.container(border=True):
        render_escaped_bold_text(f"{contract.section} Command Deck")
        render_shell_snapshot(
            (
                ("Primary CTA", contract.primary_cta),
                ("Evidence boundary", contract.evidence_boundary),
            )
        )
        safe_caption(contract.no_query_note)

        actions = tuple(contract.route_actions or ())
        if not actions:
            return

        cols = st.columns(min(3, len(actions)))
        for idx, action in enumerate(actions):
            with cols[idx % len(cols)]:
                render_escaped_bold_text(action.label)
                safe_caption(action.description)
                button_key = f"{prefix}_{idx}_{_key_token(action.label)}"
                if safe_button(action.label, key=button_key, width="stretch"):
                    apply_command_deck_action(action, st.session_state)
                    if on_action is not None:
                        on_action(action)
                    st.rerun()


def render_command_deck_for_section(section: str, *, key_prefix: str | None = None) -> None:
    """Render the Command Deck contract for a canonical section."""
    render_command_deck(get_command_deck_contract(section), key_prefix=key_prefix)


__all__ = [
    "apply_command_deck_action",
    "render_command_deck",
    "render_command_deck_for_section",
]
