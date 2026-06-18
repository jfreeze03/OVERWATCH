"""Top-level Streamlit render flow for OVERWATCH.

The shell coordinates startup state, access checks, global filters, sidebar
chrome, idle pause behavior, connection empty states, and lazy section dispatch.
Business logic remains in sections and Snowflake mart utilities.
"""
from __future__ import annotations

import time

import streamlit as st
from streamlit.runtime.scriptrunner import StopException

from access_control import (
    admin_access_is_allowed,
    cached_snowflake_available,
    get_current_role,
    probe_snowflake_available,
    refresh_current_role_for_access,
    seed_current_role_from_secrets,
)
from config import DEFAULT_COMPANY
from filters import maybe_clear_scope_cache_on_filter_change, render_topbar_filter_strip
from layout import (
    fresh_section_container,
    render_admin_access_required,
    render_app_header,
    render_connection_empty_state,
    render_query_pause_state,
    render_section_transition_state,
    render_sidebar,
)
from navigation import (
    current_active_section,
    current_visible_sections,
    mark_section_rendered,
    section_requires_connection,
    set_active_section,
    should_show_section_transition,
)
from refresh import current_credit_price, section_render_signature
from runtime_state import (
    ACTIVE_COMPANY,
    CONNECTION_UNAVAILABLE,
    LAST_SECTION_RENDER_MS,
    SECONDARY_CHROME_READY,
    apply_admin_defaults,
    ensure_startup_state,
    get_state,
    set_state,
)
from section_dispatch import dispatch_section
from theme import inject_theme
from utils.idle import ensure_idle_state, mark_operator_activity, queries_paused
from utils.logging import log_section_load


def _format_section_error(exc: Exception) -> str:
    """Format Snowflake or metadata errors without importing query helpers early."""
    from utils.query import format_snowflake_error

    return format_snowflake_error(exc)


def render_app() -> None:
    """Render the OVERWATCH app shell and selected section."""
    inject_theme()
    ensure_startup_state()
    seed_current_role_from_secrets()
    apply_admin_defaults()
    ensure_idle_state()

    idle_query_paused = queries_paused()
    if not idle_query_paused:
        mark_operator_activity("app render")

    connection_available = (
        cached_snowflake_available(default=False)
        if idle_query_paused
        else probe_snowflake_available()
    )
    current_role = (
        get_current_role()
        if idle_query_paused
        else refresh_current_role_for_access(connection_available)
    )
    admin_allowed = admin_access_is_allowed(current_role, connection_available)
    visible_sections = current_visible_sections()
    active_section = current_active_section(visible_sections)
    active_company = str(get_state(ACTIVE_COMPANY, DEFAULT_COMPANY) or DEFAULT_COMPANY)
    credit_price = current_credit_price()
    set_active_section(active_section)

    # Paint the main app shell before the sidebar and selected section hydrate.
    render_app_header(active_section, active_company, credit_price, current_role)
    active_company = render_topbar_filter_strip(active_company)

    sidebar_state = render_sidebar(
        active_company=active_company,
        active_section=active_section,
        visible_sections=visible_sections,
        current_role=current_role,
        connection_available=connection_available,
        admin_access_allowed=admin_allowed,
        idle_query_paused=idle_query_paused,
        credit_price=credit_price,
    )
    active_company = sidebar_state.active_company
    active_section = sidebar_state.active_section
    current_role = sidebar_state.current_role
    admin_allowed = sidebar_state.admin_access_allowed
    connection_available = sidebar_state.connection_available
    idle_query_paused = sidebar_state.idle_query_paused
    credit_price = sidebar_state.credit_price
    visible_sections = sidebar_state.visible_sections

    maybe_clear_scope_cache_on_filter_change()
    active_section = current_active_section(visible_sections)
    set_active_section(active_section)

    section_signature = section_render_signature(active_section, active_company, current_role)
    section_slot = st.empty()
    show_transition = should_show_section_transition(section_signature)

    section_render_started = time.perf_counter()
    if show_transition:
        with fresh_section_container(section_slot):
            render_section_transition_state(active_section)

    try:
        needs_connection = section_requires_connection(active_section)
        if idle_query_paused:
            with fresh_section_container(section_slot):
                render_query_pause_state()
            mark_section_rendered(active_section, section_signature)
        elif not admin_allowed:
            with fresh_section_container(section_slot):
                render_admin_access_required(current_role)
            mark_section_rendered(active_section, section_signature)
        elif needs_connection and (
            not connection_available or get_state(CONNECTION_UNAVAILABLE)
        ):
            with fresh_section_container(section_slot):
                render_connection_empty_state(active_section)
            mark_section_rendered(active_section, section_signature)
        else:
            try:
                with fresh_section_container(section_slot):
                    dispatch_section(active_section)
                mark_section_rendered(active_section, section_signature)
            except StopException:
                set_state(CONNECTION_UNAVAILABLE, True)
                with fresh_section_container(section_slot):
                    render_connection_empty_state(active_section)
                mark_section_rendered(active_section, section_signature)
            except Exception as exc:
                with fresh_section_container(section_slot):
                    st.error(f"{active_section} could not finish rendering.")
                    st.caption(_format_section_error(exc))
                    st.info(
                        "The Snowflake connection may still be healthy. This usually means one panel hit a metadata, "
                        "permission, or empty-data edge case. Try another section or refresh after the source view is available."
                    )
                mark_section_rendered(active_section, section_signature)
    finally:
        duration_ms = int((time.perf_counter() - section_render_started) * 1000)
        set_state(LAST_SECTION_RENDER_MS, duration_ms)
        set_state(SECONDARY_CHROME_READY, True)
        log_section_load(active_section, duration_ms)
