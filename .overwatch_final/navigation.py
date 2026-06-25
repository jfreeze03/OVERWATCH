"""Top-level navigation resolution for the OVERWATCH app shell.

This module owns sidebar section selection, visible section calculation, and
section transition state. In-section workflow routing remains in
`sections.navigation` for compatibility with existing section modules.
"""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from config import (
    ALL_SECTIONS,
    PRIMARY_NAV_HIDDEN_SECTIONS,
    compatibility_state_for_section,
    normalize_section_name,
)
from runtime_state import (
    ACTIVE_SECTION,
    LAST_RENDERED_SECTION,
    LAST_SECTION_RENDER_SIGNATURE,
    NAV_SECTION,
    PENDING_AUTOLOAD_SECTION,
    PENDING_AUTOLOAD_STARTED_AT,
    PENDING_SECTION,
    SECTION_BODY_RESET_SIGNATURE,
    SECTION_TRANSITION_STARTED_AT,
    get_state,
    pop_state,
    set_state,
)
from sections.navigation import request_section_workspace


CONNECTION_OPTIONAL_SECTIONS = set(ALL_SECTIONS)


def normalize_nav_section(section: str) -> str:
    """Normalize labels, aliases, and retired route names to canonical sections."""
    return normalize_section_name(section)


def resolve_visible_sections() -> list[str]:
    """Return the full admin monitoring navigation."""
    return [section for section in ALL_SECTIONS if section not in PRIMARY_NAV_HIDDEN_SECTIONS]


def current_visible_sections() -> list[str]:
    """Return visible sections for the current role without importing section modules."""
    return resolve_visible_sections()


def current_active_section(visible_sections: list[str]) -> str:
    """Normalize the active section and keep the nav state valid."""
    fallback = visible_sections[0] if visible_sections else normalize_nav_section("Executive Landing")
    active = normalize_nav_section(get_state(NAV_SECTION, fallback))
    if active not in visible_sections:
        active = fallback
        set_state(NAV_SECTION, active)
    return active


def apply_section_compatibility_state(section: str) -> None:
    """Apply workflow state for retired routes that now open canonical sections."""
    for key, value in compatibility_state_for_section(section).items():
        set_state(key, value)


def queue_section_navigation(section: str) -> None:
    """Mark a section switch before the next rerun starts rendering."""
    raw_section = str(section or "").strip()
    target = normalize_nav_section(raw_section)
    current = normalize_nav_section(get_state(NAV_SECTION, ""))
    pop_state(PENDING_AUTOLOAD_SECTION, None)
    pop_state(PENDING_AUTOLOAD_STARTED_AT, None)
    section_changed = target != current
    if target == "Executive Landing" and section_changed:
        set_state(PENDING_SECTION, target)
        set_state(SECTION_TRANSITION_STARTED_AT, datetime.now().isoformat(timespec="seconds"))
    elif section_changed:
        set_state(PENDING_SECTION, target)
        set_state(SECTION_TRANSITION_STARTED_AT, datetime.now().isoformat(timespec="seconds"))
    request_section_workspace(
        target,
        reset_workflow=section_changed,
        request_autoload=section_changed,
    )
    if section_changed or raw_section != target:
        apply_section_compatibility_state(raw_section)
    set_state(NAV_SECTION, target)


def section_requires_connection(section: str) -> bool:
    """Return whether the selected section needs Snowflake before it renders."""
    return normalize_nav_section(section) not in CONNECTION_OPTIONAL_SECTIONS


def mark_section_rendered(section: str, signature: tuple) -> None:
    """Record a successful shell render for transition and stale-body control."""
    set_state(LAST_RENDERED_SECTION, normalize_nav_section(section))
    set_state(LAST_SECTION_RENDER_SIGNATURE, signature)
    pop_state(PENDING_SECTION, None)
    pop_state(SECTION_TRANSITION_STARTED_AT, None)
    pop_state(SECTION_BODY_RESET_SIGNATURE, None)


def section_transition_needed(signature: tuple) -> bool:
    """Return whether the previous section body no longer matches active state."""
    return get_state(LAST_SECTION_RENDER_SIGNATURE) != signature


def should_show_section_transition(signature: tuple) -> bool:
    """Show the stale-body cover only after a section has actually rendered."""
    has_pending_navigation = PENDING_SECTION in st.session_state
    last_signature = get_state(LAST_SECTION_RENDER_SIGNATURE)
    last_section = last_signature[0] if isinstance(last_signature, tuple) and last_signature else ""
    current_section = signature[0] if isinstance(signature, tuple) and signature else ""
    section_changed = bool(last_section and current_section and last_section != current_section)
    return (has_pending_navigation or section_changed) and section_transition_needed(signature)


def section_body_reset_needed(signature: tuple) -> bool:
    """Return whether the previous section body needs a clean clearing pass."""
    return (
        should_show_section_transition(signature)
        and get_state(SECTION_BODY_RESET_SIGNATURE) != signature
    )


def set_active_section(section: str) -> None:
    """Expose the active section to shared helpers and downstream sections."""
    set_state(ACTIVE_SECTION, normalize_nav_section(section))
