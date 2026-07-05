"""Top-level navigation resolution for the OVERWATCH app shell.

This module owns sidebar section selection, visible section calculation, and
section transition state. In-section workflow routing remains isolated behind
the local queueing helper for compatibility with existing section modules.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import streamlit as st

from config import (
    ALL_SECTIONS,
    PRIMARY_NAV_HIDDEN_SECTIONS,
    compatibility_state_for_section,
    normalize_section_name,
)
from utils.performance import SECTION_ROUTE_QUERY_BUDGET, query_budget_context
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
    record_runtime_event,
    set_state,
)


@dataclass(frozen=True)
class SectionConnectionPolicy:
    section: str
    offline_capable: bool
    requires_connection: bool
    fallback_surface: str


OFFLINE_CAPABLE_SECTIONS = frozenset(ALL_SECTIONS)
CONNECTION_REQUIRED_SECTIONS = frozenset()


def normalize_nav_section(section: str) -> str:
    """Normalize labels, aliases, and retired route names to canonical sections."""
    return normalize_section_name(section)


def resolve_visible_sections() -> list[str]:
    """Return the full admin monitoring navigation."""
    return [section for section in ALL_SECTIONS if section not in PRIMARY_NAV_HIDDEN_SECTIONS]


def current_visible_sections() -> list[str]:
    """Return visible sections for the current role without importing section modules."""
    return resolve_visible_sections()


def section_connection_policy(section: str) -> SectionConnectionPolicy:
    """Return the explicit connection policy for a shell section.

    OVERWATCH primary sections are packet/fallback capable by design: section
    entry should not probe Snowflake, and unavailable/missing-packet states are
    rendered by the section or shell fallback instead of blocking navigation.
    Unknown routes fail closed until they are classified.
    """
    target = normalize_nav_section(section)
    if target not in set(ALL_SECTIONS):
        return SectionConnectionPolicy(
            section=target,
            offline_capable=False,
            requires_connection=True,
            fallback_surface="connection_required",
        )
    offline_capable = target in OFFLINE_CAPABLE_SECTIONS
    requires_connection = target in CONNECTION_REQUIRED_SECTIONS
    return SectionConnectionPolicy(
        section=target,
        offline_capable=offline_capable,
        requires_connection=requires_connection,
        fallback_surface="packet_or_connection_fallback",
    )


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
    from sections.navigation import request_executive_landing_hydration, request_section_workspace

    raw_section = str(section or "").strip()
    with query_budget_context("route_action", section=normalize_nav_section(raw_section), workflow="", budget=SECTION_ROUTE_QUERY_BUDGET):
        target = normalize_nav_section(raw_section)
        current = normalize_nav_section(get_state(NAV_SECTION, ""))
        pop_state(PENDING_AUTOLOAD_SECTION, None)
        pop_state(PENDING_AUTOLOAD_STARTED_AT, None)
        if target == "Executive Landing":
            request_executive_landing_hydration()
            set_state(PENDING_SECTION, target)
            set_state(SECTION_TRANSITION_STARTED_AT, datetime.now().isoformat(timespec="seconds"))
        elif target != current:
            set_state(PENDING_SECTION, target)
            set_state(SECTION_TRANSITION_STARTED_AT, datetime.now().isoformat(timespec="seconds"))
        request_section_workspace(target)
        apply_section_compatibility_state(raw_section)
        set_state(NAV_SECTION, target)
        record_runtime_event(
            event_type="route_action",
            route=target,
            section=target,
            workflow="",
            boundary="metadata_bounded",
            product_boundary="metadata_bounded",
            execution_boundary="metadata_bounded",
            action_id=f"nav::{target.lower().replace(' ', '_')}",
            user_initiated=True,
            route_action_marker_present=True,
            source_module="navigation.queue_section_navigation",
        )


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
