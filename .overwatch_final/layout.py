"""Visual shell layout for OVERWATCH.

This module owns app chrome: the header, sidebar framing, utility panels, empty
states, and transition state. It intentionally does not own access decisions,
navigation resolution, or section rendering.
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime

import streamlit as st

from access_control import admin_access_is_allowed, get_stable_current_role
from brand import render_sidebar_brand
from config import (
    ADMIN_ACCESS_ROLES,
    COMPANY_CONFIG,
    DEFAULT_ALERT_EMAIL,
    DEFAULTS,
    DEFAULT_ENVIRONMENT,
    NAV_GROUPS,
    SECTION_ICONS,
    display_section_label,
)
from filters import render_advanced_scope_controls
from navigation import current_active_section, current_visible_sections, normalize_nav_section, queue_section_navigation
from refresh import metric_settings_signature
from runtime_state import (
    AI_CREDIT_PRICE,
    AI_CREDIT_PRICE_INPUT,
    ALERT_EMAIL_TARGETS,
    ALERT_EMAIL_TARGETS_INPUT,
    CONNECTION_AVAILABLE,
    CONNECTION_UNAVAILABLE,
    CREDIT_PRICE,
    CREDIT_PRICE_INPUT,
    CURRENT_ROLE,
    GLOBAL_DATABASE,
    GLOBAL_END_DATE,
    GLOBAL_ENVIRONMENT,
    GLOBAL_ROLE,
    GLOBAL_START_DATE,
    GLOBAL_USER,
    GLOBAL_WAREHOUSE,
    IDLE_TIMEOUT_SECONDS,
    LIVE_REFRESH_INTERVAL,
    PENDING_SECTION,
    SIDEBAR_PANEL,
    SF_SESSION,
    SF_SESSION_CREATED_AT,
    PREV_METRIC_SETTINGS_SIGNATURE,
    WIDGET_GLOBAL_REFRESH,
    WIDGET_NAV_BUTTON_PREFIX,
    WIDGET_RESUME_QUERIES,
    WIDGET_RETRY_SNOWFLAKE_CONNECTION,
    WIDGET_SIDEBAR_PANEL_PREFIX,
    STORAGE_COST_INPUT,
    STORAGE_COST_PER_TB,
    ensure_default_state,
    ensure_triage_mode_state,
    get_state,
    pop_state,
    set_state,
    sync_exceptions_only_mode,
)
from utils.cache import clear_all_cache
from utils.company_filter import get_environment_label
from utils.idle import (
    get_idle_timeout_seconds,
    idle_elapsed_seconds,
    query_pause_message,
    resume_queries,
)


SECTION_SUBTITLES = {
    "Executive Landing": "Risk, cost movement, action closure, and telemetry trust.",
    "DBA Control Room": "Morning triage, route status, data health, and release risk.",
    "Alert Center": "Active alerts, workflow routing, impact, recommended actions, and investigation paths.",
    "Workload Operations": "Query/contention triage plus task, procedure, and pipeline health.",
    "Cost & Contract": "Spend attribution, contract utilization, chargeback, savings, and action queue.",
    "Security Monitoring": "Login risk, privileged grants, public access, data sharing, and security alerts.",
}

SETUP_HEALTH_PANEL_OPEN_KEY = "_overwatch_show_decision_setup_health"


@dataclass(frozen=True)
class SidebarState:
    """Refreshed shell state after sidebar widgets have rendered."""

    active_company: str
    active_section: str
    current_role: str
    admin_access_allowed: bool
    connection_available: bool
    idle_query_paused: bool
    credit_price: float
    visible_sections: list[str]


def section_subtitle(section: str) -> str:
    """Return the short shell subtitle for a section."""
    return SECTION_SUBTITLES.get(section, "Snowflake DBA operating surface.")


def render_section_body_marker(section: str) -> None:
    """Render a hidden marker after the selected section body starts hydrating."""

    safe_section = html.escape(normalize_nav_section(section), quote=True)
    st.markdown(
        f'<div id="overwatch-active-section-body" data-overwatch-section="{safe_section}" '
        'style="display:none" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )


def _chip(label: str, value: object, *, muted: bool = False) -> str:
    safe_label = html.escape(str(label))
    safe_value = html.escape(str(value if value not in (None, "") else "All"))
    cls = "ow-scope-chip ow-muted-chip" if muted else "ow-scope-chip"
    return f'<span class="{cls}"><span>{safe_label}</span><strong>{safe_value}</strong></span>'


def active_scope_chips(company: str) -> str:
    """Render current scope chips for the header."""
    env_key = get_state(GLOBAL_ENVIRONMENT, DEFAULT_ENVIRONMENT)
    env_label = get_environment_label(env_key, company)
    chips = [
        _chip("Company", company),
        _chip("Environment", env_label),
    ]
    start = get_state(GLOBAL_START_DATE)
    end = get_state(GLOBAL_END_DATE)
    if start and end:
        chips.append(_chip("Window", f"{start} to {end}", muted=True))
    for label, key in [
        ("Warehouse", GLOBAL_WAREHOUSE),
        ("User", GLOBAL_USER),
        ("Role", GLOBAL_ROLE),
        ("Database", GLOBAL_DATABASE),
    ]:
        value = get_state(key)
        if value:
            chips.append(_chip(label, value, muted=True))
    return "".join(chips)


def render_app_header(section: str, company: str, credit_price: float, role: str) -> None:
    """Compatibility no-op; the global command bar owns top chrome now."""
    return None


def sidebar_panel_toggle(label: str, panel_key: str) -> bool:
    """Render a sidebar panel launcher and return whether the panel is open.

    Utility panels are not navigation destinations, so keep them visually
    secondary even when open. The primary sidebar bar should only identify the
    selected monitoring section.
    """
    active_panel = str(get_state(SIDEBAR_PANEL, "") or "")
    is_active = active_panel == panel_key
    if st.button(
        label,
        key=f"{WIDGET_SIDEBAR_PANEL_PREFIX}_{panel_key}",
        type="secondary",
        width="stretch",
    ):
        is_active = not is_active
        set_state(SIDEBAR_PANEL, panel_key if is_active else "")
    return is_active


def format_idle_duration(seconds: int) -> str:
    """Format idle duration for the pause shell."""
    minutes = max(1, int(round(seconds / 60)))
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    rem = minutes % 60
    return f"{hours}h {rem:02d}m" if rem else f"{hours}h"


def render_query_pause_state() -> None:
    """Render the idle pause shell without hydrating Snowflake telemetry."""
    elapsed = idle_elapsed_seconds()
    timeout = get_idle_timeout_seconds()
    st.markdown(
        f"""
        <div class="ow-empty-state">
            <div class="ow-empty-title">OVERWATCH is idle</div>
            <div class="ow-empty-list">
                <span>Snowflake queries are paused</span>
                <span>Idle: <code>{html.escape(format_idle_duration(elapsed))}</code></span>
                <span>Timeout: <code>{html.escape(format_idle_duration(timeout))}</code></span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.info(query_pause_message())
    if st.button("Resume OVERWATCH", key=WIDGET_RESUME_QUERIES, type="primary"):
        resume_queries()
        st.rerun()


def render_connection_empty_state(section: str) -> None:
    """Render the connection-required shell state."""
    st.markdown(
        f"""
        <div class="ow-empty-state">
            <div class="ow-empty-title">Snowflake connection required for {html.escape(section)}</div>
            <div class="ow-empty-list">
                <span>Snowflake Streamlit</span>
                <span><code>connections.snowflake</code></span>
                <span>Refresh</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Retry Snowflake connection", key=WIDGET_RETRY_SNOWFLAKE_CONNECTION):
        pop_state(CONNECTION_UNAVAILABLE, None)
        pop_state(CONNECTION_AVAILABLE, None)
        pop_state(CURRENT_ROLE, None)
        pop_state(SF_SESSION, None)
        pop_state(SF_SESSION_CREATED_AT, None)
        st.rerun()


def render_admin_access_required(role: str) -> None:
    """Render the admin-role gate."""
    safe_role = html.escape(str(role or "Unknown role"))
    safe_roles = html.escape(", ".join(ADMIN_ACCESS_ROLES))
    st.markdown(
        f"""
        <div class="ow-empty-state">
            <div class="ow-empty-title">Admin role required</div>
            <div class="ow-empty-list">
                <span>Current role: <code>{safe_role}</code></span>
                <span>Allowed roles: <code>{safe_roles}</code></span>
                <span>Switch roles in Snowflake and refresh</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _open_decision_setup_health() -> None:
    from sections.decision_workspace_setup_health import open_decision_setup_health

    open_decision_setup_health()


def _render_decision_setup_health_panel() -> None:
    from sections.decision_workspace_setup_health import render_decision_setup_health_panel

    render_decision_setup_health_panel(session=get_state(SF_SESSION))


def render_section_transition_state(section: str) -> None:
    """Hide the previous section while the selected section hydrates."""
    safe_section = html.escape(normalize_nav_section(section))
    pending = get_state(PENDING_SECTION)
    safe_pending = html.escape(normalize_nav_section(str(pending or section)))
    st.markdown(
        f"""
        <div class="ow-section-transition" role="status" aria-live="polite">
            <div class="ow-section-transition-card">
                <div class="ow-section-transition-kicker">Switching section</div>
                <div class="ow-section-transition-title">Loading {safe_section}</div>
                <div class="ow-section-transition-copy">
                    Clearing the previous view while {safe_pending} renders fresh DBA telemetry.
                </div>
                <div class="ow-section-transition-bar"><span></span></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def fresh_section_container(slot):
    """Clear stale section children before rendering a new body."""
    slot.empty()
    return slot.container()


def render_sidebar_utilities(
    *,
    active_company: str,
    admin_access_allowed: bool,
    credit_price: float,
) -> float:
    """Render app utility controls below primary navigation."""

    st.markdown('<div class="ow-sidebar-utility-break" aria-hidden="true"></div>', unsafe_allow_html=True)
    st.divider()
    st.markdown(
        '<div class="ow-sidebar-utility-heading">APP CONTROLS</div>',
        unsafe_allow_html=True,
    )

    if sidebar_panel_toggle("Advanced Scope", "advanced_scope"):
        render_advanced_scope_controls(active_company)

    if sidebar_panel_toggle("Settings", "settings"):
        credit_price = st.number_input(
            "$/credit (compute)",
            min_value=0.50, max_value=20.00,
            value=get_state(CREDIT_PRICE, DEFAULTS["credit_price"]),
            step=0.10, key=CREDIT_PRICE_INPUT,
        )
        set_state(CREDIT_PRICE, credit_price)

        ai_credit_price = st.number_input(
            "$/AI credit (Cortex)",
            min_value=0.50, max_value=20.00,
            value=get_state(AI_CREDIT_PRICE, DEFAULTS["ai_credit_price"]),
            step=0.10, key=AI_CREDIT_PRICE_INPUT,
        )
        set_state(AI_CREDIT_PRICE, ai_credit_price)

        storage_cost = st.number_input(
            "$/TB/month (storage)",
            min_value=1.0, max_value=100.0,
            value=get_state(STORAGE_COST_PER_TB, DEFAULTS["storage_cost_per_tb"]),
            step=1.0, key=STORAGE_COST_INPUT,
        )
        set_state(STORAGE_COST_PER_TB, storage_cost)
        alert_email_targets = st.text_input(
            "Alert email recipients",
            value=get_state(ALERT_EMAIL_TARGETS, DEFAULT_ALERT_EMAIL),
            key=ALERT_EMAIL_TARGETS_INPUT,
            help="Comma-separated Snowflake notification recipients for generated alert SQL.",
        )
        configured_alert_email = str(alert_email_targets or "").strip()
        set_state(ALERT_EMAIL_TARGETS, configured_alert_email)
        if not configured_alert_email:
            st.warning(
                "Alert email is not configured. Set OVERWATCH_SETTINGS.DEFAULT_ALERT_EMAIL "
                "in Snowflake, or enter recipients here before enabling scheduled email delivery."
            )
        st.caption("Cost estimates use configured credit rates.")

        current_metric_signature = metric_settings_signature()
        previous_metric_signature = get_state(PREV_METRIC_SETTINGS_SIGNATURE)
        if previous_metric_signature is None:
            set_state(PREV_METRIC_SETTINGS_SIGNATURE, current_metric_signature)
        elif previous_metric_signature != current_metric_signature:
            clear_all_cache(clear_streamlit_cache=False, clear_metadata=False)
            set_state(PREV_METRIC_SETTINGS_SIGNATURE, current_metric_signature)

        st.selectbox(
            "Live refresh interval",
            [15, 30, 60, 120], index=1,
            format_func=lambda x: f"{x}s",
            key=LIVE_REFRESH_INTERVAL,
        )
        idle_timeout_options = [300, 600, 900, 1800, 3600]
        current_idle_timeout = get_idle_timeout_seconds()
        if current_idle_timeout not in idle_timeout_options:
            idle_timeout_options.append(current_idle_timeout)
            idle_timeout_options = sorted(set(idle_timeout_options))
        st.selectbox(
            "Idle query pause",
            idle_timeout_options,
            index=idle_timeout_options.index(current_idle_timeout),
            format_func=lambda x: f"{int(x / 60)} min",
            key=IDLE_TIMEOUT_SECONDS,
            help="Pauses OVERWATCH Snowflake queries after inactivity. Resume keeps Live Monitor auto-refresh off.",
        )
        if admin_access_allowed:
            st.button(
                "Open Setup Health",
                key="settings_open_setup_health",
                type="secondary",
                width="stretch",
                on_click=_open_decision_setup_health,
            )
            if bool(get_state(SETUP_HEALTH_PANEL_OPEN_KEY, False)):
                _render_decision_setup_health_panel()
    return credit_price


def render_sidebar(
    *,
    active_company: str,
    active_section: str,
    visible_sections: list[str],
    current_role: str,
    connection_available: bool,
    admin_access_allowed: bool,
    idle_query_paused: bool,
    credit_price: float,
) -> SidebarState:
    """Render sidebar navigation/settings and return refreshed shell state."""
    with st.sidebar:
        st.markdown(render_sidebar_brand(), unsafe_allow_html=True)

        st.divider()

        ensure_default_state(CURRENT_ROLE, "")

        ensure_triage_mode_state(True)
        sync_exceptions_only_mode()

        st.divider()

        current_role = current_role or get_stable_current_role()
        admin_access_allowed = admin_access_allowed or admin_access_is_allowed(current_role, connection_available)
        visible_sections = current_visible_sections()

        if not admin_access_allowed and not idle_query_paused:
            st.warning("Switch to SNOW_ACCOUNTADMINS or SNOW_SYSADMINS to open monitoring sections.")

        active_section = current_active_section(visible_sections)

        def _set_section(section: str) -> None:
            queue_section_navigation(section)

        for group_name, group_all in NAV_GROUPS.items():
            group_visible = [s for s in group_all if s in visible_sections]
            if not group_visible:
                continue
            st.caption(group_name)
            for section_name in group_visible:
                is_active = section_name == active_section
                st.button(
                    display_section_label(section_name),
                    key=f"{WIDGET_NAV_BUTTON_PREFIX}_{group_name}_{section_name}",
                    type="primary" if is_active else "secondary",
                    width="stretch",
                    on_click=_set_section,
                    args=(section_name,),
                )

        credit_price = render_sidebar_utilities(
            active_company=active_company,
            admin_access_allowed=admin_access_allowed,
            credit_price=credit_price,
        )

    return SidebarState(
        active_company=active_company,
        active_section=active_section,
        current_role=current_role,
        admin_access_allowed=admin_access_allowed,
        connection_available=connection_available,
        idle_query_paused=idle_query_paused,
        credit_price=credit_price,
        visible_sections=visible_sections,
    )
