# app.py - OVERWATCH main entry point
# -----------------------------------------------------------------------------
# Includes:
#   - Role-based section visibility (ROLE_SECTIONS in config.py)
#   - ALFA default company seeded before radio renders
#   - Cache invalidation on company switch
#   - Saved Views / Bookmarks sidebar panel
# -----------------------------------------------------------------------------
import streamlit as st
import html
import importlib
import time
from datetime import datetime, timedelta
from streamlit.runtime.scriptrunner import StopException

st.set_page_config(
    page_title="OVERWATCH - Snowflake DBA Monitor",
    page_icon="O",
    layout="wide",
    initial_sidebar_state="expanded",
)

import theme as theme_module
from theme import inject_theme, render_theme_picker
import config as config_module

if getattr(config_module, "CONFIG_VERSION", "") != "2026-06-05-trexis-scope-v1":
    config_module = importlib.reload(config_module)

from config import (
    ALL_SECTIONS, NAV_GROUPS, DEFAULTS, COMPANY_CONFIG,
    DEFAULT_COMPANY, ROLE_SECTIONS,
    SECTION_BY_TITLE, ENVIRONMENT_CONFIG, DEFAULT_ENVIRONMENT,
    SECTION_ICONS, DEFAULT_ALERT_EMAIL, EXPERIENCE_VIEW_SECTIONS,
    normalize_section_name,
    resolve_allowed_experience_views,
    resolve_role_profile,
)
import utils as utils_package

if getattr(utils_package, "UTILS_EXPORT_VERSION", "") != "2026-06-02-guardrails-v1":
    utils_package = importlib.reload(utils_package)

from utils.cache import clear_all_cache
from utils.session import get_session
from utils.logging import log_section_load
from utils.company_filter import (
    get_environment_label,
    get_environment_options_for_company,
    invalidate_company_cache,
)
from utils.metadata import load_database_options, load_warehouse_options
from utils.admin import clamp_global_date_range, render_admin_mode_control
import utils.section_guidance as section_guidance


def _lazy_query_call(name: str):
    def _call(*args, **kwargs):
        query_module = importlib.import_module("utils.query")
        return getattr(query_module, name)(*args, **kwargs)

    _call.__name__ = name
    return _call


get_query_telemetry = _lazy_query_call("get_query_telemetry")
get_query_budget_summary = _lazy_query_call("get_query_budget_summary")
clear_query_telemetry = _lazy_query_call("clear_query_telemetry")
format_snowflake_error = _lazy_query_call("format_snowflake_error")


_ASK_OVERWATCH_STATE_KEYS = (
    "rec_recommendations",
    "rec_automation_board",
    "rec_action_queue",
    "cost_contract_queue",
    "cost_contract_budget_command_summary",
    "cost_contract_budget_command_center",
    "cost_contract_native_control_summary",
    "cost_contract_native_control_inventory",
    "cost_contract_spike_root_cause_summary",
    "cost_contract_spike_root_cause",
    "cost_contract_change_cost_summary",
    "cost_contract_change_cost_correlation",
    "cost_contract_governance_alert_summary",
    "cost_contract_governance_alerts",
    "cost_contract_incident_timeline_summary",
    "cost_contract_incident_timeline",
    "cost_contract_mart_operability_summary",
    "cost_contract_mart_operability",
    "alert_center_data",
    "dba_control_room_data",
    "dba_control_room_incident_board",
    "dba_control_room_handoff",
    "arch_adaptive_compute",
    "arch_ai_security_guardrails",
    "arch_futures_board",
    "arch_futures_adoption_gate",
    "arch_agentic_ai_summary",
    "arch_agentic_ai_scorecard",
)

CONNECTION_OPTIONAL_SECTIONS = {"Alert Center"}


def _seed_current_role_from_secrets() -> None:
    """Use configured Snowflake role as a zero-query startup hint when present."""
    if st.session_state.get("_overwatch_current_role"):
        return
    try:
        connections = st.secrets.get("connections", {})
        snowflake_cfg = connections.get("snowflake", {}) if connections else {}
        role = str(snowflake_cfg.get("role") or "").strip().upper()
    except Exception:
        role = ""
    if role:
        st.session_state["_overwatch_current_role"] = role


def _snapshot_ask_overwatch_state(state) -> dict:
    snapshot = {}
    for key in _ASK_OVERWATCH_STATE_KEYS:
        try:
            if key in state:
                snapshot[key] = state.get(key)
        except Exception:
            continue
    return snapshot


def _load_bookmark_helpers():
    """Lazy-load saved-view helpers only when a bookmark action is requested."""
    from utils.bookmarks import (
        save_bookmark,
        load_bookmarks,
        apply_bookmark,
        delete_bookmark,
    )

    return save_bookmark, load_bookmarks, apply_bookmark, delete_bookmark


def _dev_reload_helpers_enabled() -> bool:
    """Return whether shared helper hot-reload checks should run."""
    try:
        return bool(st.session_state.get("_overwatch_dev_reload_helpers", False))
    except Exception:
        return False


def _maybe_reload_dev_helpers() -> None:
    """Reload shared UI helpers only during explicit local development."""
    if not _dev_reload_helpers_enabled():
        return

    import utils.display as display_module
    import utils.workflows as workflows_module

    if getattr(display_module, "DISPLAY_VERSION", "") != "2026-06-01-explicit-drilldowns-v1":
        importlib.reload(display_module)

    if getattr(workflows_module, "WORKFLOWS_VERSION", "") != "2026-06-03-bottom-notes-v1":
        importlib.reload(workflows_module)
        if hasattr(sections, "reload_loaded_sections"):
            sections.reload_loaded_sections()


import sections

if getattr(theme_module, "THEME_VERSION", "") != "2026-06-05-roll-tide-war-eagle-v3":
    theme_module = importlib.reload(theme_module)
    inject_theme = theme_module.inject_theme
    render_theme_picker = theme_module.render_theme_picker

if getattr(section_guidance, "SECTION_GUIDANCE_VERSION", "") != "2026-06-03-bottom-notes-v1":
    section_guidance = importlib.reload(section_guidance)

_maybe_reload_dev_helpers()

inject_theme()

# Seed ALFA default before radio.
if "active_company" not in st.session_state:
    st.session_state["active_company"] = DEFAULT_COMPANY
if "_logging_enabled" not in st.session_state:
    st.session_state["_logging_enabled"] = False
if "_query_logging_enabled" not in st.session_state:
    st.session_state["_query_logging_enabled"] = False
if "_detailed_query_tags_enabled" not in st.session_state:
    st.session_state["_detailed_query_tags_enabled"] = False
_seed_current_role_from_secrets()
if "global_start_date" not in st.session_state or "global_end_date" not in st.session_state:
    _default_end = datetime.now().date()
    _default_start = _default_end - timedelta(days=7)
    st.session_state.setdefault("global_start_date", _default_start)
    st.session_state.setdefault("global_end_date", _default_end)
    st.session_state.setdefault("_global_date_range_input", (_default_start, _default_end))


# Role resolution, cached for five minutes.
def _get_current_role() -> str:
    return str(st.session_state.get("_overwatch_current_role", "") or "").upper()


def _allowed_experience_options() -> list[str]:
    return list(resolve_allowed_experience_views(_get_current_role()))


def _current_experience_view() -> str:
    allowed = _allowed_experience_options()
    current = str(st.session_state.get("overwatch_experience_view", "") or allowed[0])
    if current not in allowed:
        current = allowed[0]
        st.session_state["overwatch_experience_view"] = current
    return current


def _resolve_visible_sections() -> list[str]:
    return _resolve_visible_sections_for_experience(_current_experience_view())


def _resolve_visible_sections_for_experience(experience: str) -> list[str]:
    role_profile = resolve_role_profile(_get_current_role())
    base_sections = list(ROLE_SECTIONS.get(role_profile, ALL_SECTIONS))
    allowed = _allowed_experience_options()
    selected_experience = experience if experience in allowed else allowed[0]
    profile_sections = EXPERIENCE_VIEW_SECTIONS.get(selected_experience, EXPERIENCE_VIEW_SECTIONS["DBA"])
    visible = [section for section in profile_sections if section in base_sections]
    return visible or base_sections


def _normalize_nav_section(section: str) -> str:
    return normalize_section_name(section)


def _section_requires_connection(section: str) -> bool:
    return _normalize_nav_section(section) not in CONNECTION_OPTIONAL_SECTIONS


def _queue_section_navigation(section: str) -> None:
    """Mark a section switch before the next rerun starts rendering."""
    target = _normalize_nav_section(section)
    current = _normalize_nav_section(st.session_state.get("nav_section", ""))
    if target != current:
        st.session_state["_overwatch_pending_section"] = target
        st.session_state["_overwatch_section_transition_started_at"] = datetime.now().isoformat(timespec="seconds")
    st.session_state["nav_section"] = target


def _sync_experience_navigation() -> None:
    """Keep the active section valid when the persona filter changes."""
    selected = _current_experience_view()
    visible = _resolve_visible_sections_for_experience(selected)
    current = _normalize_nav_section(st.session_state.get("nav_section", visible[0]))
    if current not in visible:
        _queue_section_navigation(visible[0])


def _global_filter_signature() -> tuple:
    """Return the operator filter state that makes loaded evidence stale."""
    date_input = st.session_state.get("_global_date_range_input", ())
    if isinstance(date_input, list):
        date_input = tuple(date_input)
    return (
        str(st.session_state.get("global_start_date", "")),
        str(st.session_state.get("global_end_date", "")),
        str(st.session_state.get("global_warehouse", "")),
        str(st.session_state.get("global_user", "")),
        str(st.session_state.get("global_role", "")),
        str(st.session_state.get("global_database", "")),
        str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT)),
        str(date_input),
    )


def _metric_settings_signature() -> tuple:
    """Return settings that change dollarized metrics and derived evidence."""
    return (
        float(st.session_state.get("credit_price", DEFAULTS["credit_price"])),
        float(st.session_state.get("storage_cost_per_tb", DEFAULTS["storage_cost_per_tb"])),
    )


def _section_render_signature(section: str, company: str, role: str) -> tuple:
    """Return the state tuple that determines whether the main body is stale."""
    return (
        _normalize_nav_section(section),
        str(company),
        str(role or ""),
        bool(st.session_state.get("exceptions_only_mode")),
        _global_filter_signature(),
        _metric_settings_signature(),
    )


def _section_transition_needed(signature: tuple) -> bool:
    return st.session_state.get("_overwatch_last_section_render_signature") != signature


def _should_show_section_transition(signature: tuple) -> bool:
    """Show the stale-body cover only after a section has actually rendered."""
    has_prior_render = "_overwatch_last_section_render_signature" in st.session_state
    has_pending_navigation = "_overwatch_pending_section" in st.session_state
    return (has_prior_render or has_pending_navigation) and _section_transition_needed(signature)


def _current_visible_sections() -> list[str]:
    """Return visible sections for the current role without importing section modules."""
    return _resolve_visible_sections()


def _current_active_section(visible_sections: list[str]) -> str:
    """Normalize the active section and keep the nav state valid."""
    fallback = visible_sections[0]
    active = _normalize_nav_section(st.session_state.get("nav_section", fallback))
    if active not in visible_sections:
        active = fallback
        st.session_state["nav_section"] = active
    return active


def _current_credit_price() -> float:
    """Read the latest sidebar credit-rate state before the settings widget renders."""
    if "_credit_price_input" in st.session_state:
        st.session_state["credit_price"] = st.session_state["_credit_price_input"]
    return float(st.session_state.get("credit_price", DEFAULTS["credit_price"]))


def _sidebar_panel_toggle(label: str, panel_key: str) -> bool:
    """Render a sidebar panel launcher and return whether the panel is open."""
    active_panel = str(st.session_state.get("_overwatch_sidebar_panel", "") or "")
    is_active = active_panel == panel_key
    if st.button(
        label,
        key=f"sidebar_panel_{panel_key}",
        type="primary" if is_active else "secondary",
        width="stretch",
    ):
        is_active = not is_active
        st.session_state["_overwatch_sidebar_panel"] = panel_key if is_active else ""
    return is_active


def _mark_section_rendered(section: str, signature: tuple) -> None:
    st.session_state["_overwatch_last_rendered_section"] = _normalize_nav_section(section)
    st.session_state["_overwatch_last_section_render_signature"] = signature
    st.session_state.pop("_overwatch_pending_section", None)
    st.session_state.pop("_overwatch_section_transition_started_at", None)


def _probe_snowflake_available(force: bool = False) -> bool:
    """Return whether the app appears to have a Snowflake connection path."""
    if not force and "_overwatch_connection_available" in st.session_state:
        return bool(st.session_state.get("_overwatch_connection_available"))

    available = False
    try:
        connections = st.secrets.get("connections", {})
        snowflake_cfg = connections.get("snowflake", {}) if connections else {}
        available = bool(snowflake_cfg)
    except Exception:
        available = False

    if not available:
        try:
            from snowflake.snowpark.context import get_active_session

            get_active_session()
            available = True
        except Exception:
            available = False

    st.session_state["_overwatch_connection_available"] = available
    st.session_state["_overwatch_connection_unavailable"] = not available
    return available


SECTION_SUBTITLES = {
    "Executive Landing": "Board-ready risk, cost movement, action closure, and deployment trust.",
    "DBA Control Room": "Morning triage, route readiness, source health, and release risk.",
    "Alert Center": "Consolidated incidents, email digests, annotation history, and alert setup.",
    "Account Health": "Daily DBA checklist, source readiness, user hygiene, and account posture.",
    "Workload Operations": "Query history, task graphs, stored procedures, pipeline health, and runbooks.",
    "Warehouse Health": "Warehouse pressure, capacity controls, setting review, and efficiency evidence.",
    "Architecture Readiness": "Isolation, clustering, cache, DR, and forward Snowflake architecture checks.",
    "Cost & Contract": "Spend attribution, contract utilization, chargeback, savings, and action queue.",
    "Security Posture": "Access posture, privileged grants, data sharing, and governance evidence.",
    "Change & Drift": "Object changes, access changes, drift, approvals, and deployment evidence.",
}


def _section_subtitle(section: str) -> str:
    return SECTION_SUBTITLES.get(section, "Snowflake DBA operating surface.")


def _chip(label: str, value: object, *, muted: bool = False) -> str:
    safe_label = html.escape(str(label))
    safe_value = html.escape(str(value if value not in (None, "") else "All"))
    cls = "ow-scope-chip ow-muted-chip" if muted else "ow-scope-chip"
    return f'<span class="{cls}"><span>{safe_label}</span><strong>{safe_value}</strong></span>'


def _active_scope_chips(company: str) -> str:
    env_key = st.session_state.get("global_environment", DEFAULT_ENVIRONMENT)
    env_label = get_environment_label(env_key, company)
    chips = [
        _chip("Company", company),
        _chip("Environment", env_label),
    ]
    start = st.session_state.get("global_start_date")
    end = st.session_state.get("global_end_date")
    if start and end:
        chips.append(_chip("Window", f"{start} to {end}", muted=True))
    for label, key in [
        ("Warehouse", "global_warehouse"),
        ("User", "global_user"),
        ("Role", "global_role"),
        ("Database", "global_database"),
    ]:
        value = st.session_state.get(key)
        if value:
            chips.append(_chip(label, value, muted=True))
    if st.session_state.get("exceptions_only_mode"):
        chips.append(_chip("Mode", "Exceptions only"))
    return "".join(chips)


def _render_app_header(section: str, company: str, credit_price: float, role: str) -> None:
    section = _normalize_nav_section(section)
    icon = SECTION_ICONS.get(section, "target")
    now_label = datetime.now().strftime("%Y-%m-%d %H:%M")
    safe_section = html.escape(section)
    safe_subtitle = html.escape(_section_subtitle(section))
    safe_role = html.escape(role[:24] or "DBA")
    safe_icon = html.escape(str(icon).upper())
    scope_chips = _active_scope_chips(company)
    left, right = st.columns([5.4, 1.6])
    with left:
        st.markdown(
            f"""
            <div class="ow-topbar">
                <div class="ow-section-kicker">OVERWATCH DBA COMMAND CENTER</div>
                <div class="ow-section-row">
                    <span class="ow-section-icon">{safe_icon}</span>
                    <div>
                        <div class="ow-section-title">{safe_section}</div>
                        <div class="ow-section-subtitle">{safe_subtitle}</div>
                    </div>
                </div>
                <div class="ow-scope-row">{scope_chips}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with right:
        st.markdown(
            f"""
            <div class="ow-run-context">
                <div>{html.escape(now_label)}</div>
                <div>{safe_role}</div>
                <div>${float(credit_price):.2f}/credit</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Refresh", key="global_refresh", width="stretch"):
            clear_all_cache()
            st.rerun()


def _render_connection_empty_state(section: str) -> None:
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
    if st.button("Retry Snowflake connection", key="retry_snowflake_connection"):
        st.session_state.pop("_overwatch_connection_unavailable", None)
        st.session_state.pop("_overwatch_connection_available", None)
        st.session_state.pop("_overwatch_current_role", None)
        st.session_state.pop("sf_session", None)
        st.session_state.pop("_sf_session_created_at", None)
        st.rerun()


def _render_section_transition_state(section: str) -> None:
    """Hide the previous section while the selected section hydrates."""
    safe_section = html.escape(_normalize_nav_section(section))
    pending = st.session_state.get("_overwatch_pending_section")
    safe_pending = html.escape(_normalize_nav_section(str(pending or section)))
    st.markdown(
        f"""
        <div class="ow-section-transition" role="status" aria-live="polite">
            <div class="ow-section-transition-card">
                <div class="ow-section-transition-kicker">Switching section</div>
                <div class="ow-section-transition-title">Loading {safe_section}</div>
                <div class="ow-section-transition-copy">
                    Clearing the previous view while {safe_pending} renders fresh DBA evidence.
                </div>
                <div class="ow-section-transition-bar"><span></span></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


current_role = _get_current_role()
visible_sections = _current_visible_sections()
active_section = _current_active_section(visible_sections)
active_company = str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)
credit_price = _current_credit_price()
st.session_state["_overwatch_active_section"] = active_section

# Paint the main app shell before the sidebar and selected section hydrate. During
# high-concurrency startup this gives users an immediate, stable command-center frame.
_render_app_header(active_section, active_company, credit_price, current_role)

connection_available = _probe_snowflake_available()


# Sidebar.
with st.sidebar:
    st.markdown("""
    <div class="ow-sidebar-brand">
        <div class="ow-brand-row"><span class="ow-brand-dot"></span><span>OVERWATCH</span></div>
        <div class="ow-sidebar-subtitle">Snowflake DBA Command Center</div>
        <div class="ow-live-pill">LIVE</div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    if "_overwatch_current_role" not in st.session_state:
        st.session_state.setdefault("_overwatch_current_role", "")

    # Company filter.
    _prev_company = st.session_state.get("_prev_active_company", DEFAULT_COMPANY)
    active_company = st.radio(
        "Company view",
        list(COMPANY_CONFIG.keys()),
        horizontal=True,
        key="active_company",
    )
    if _prev_company != active_company:
        invalidate_company_cache()
    environment_options = list(get_environment_options_for_company(active_company))
    if st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) not in environment_options:
        st.session_state["global_environment"] = DEFAULT_ENVIRONMENT
    st.session_state["_prev_active_company"] = active_company

    if _sidebar_panel_toggle("Global Filters", "global_filters"):
        default_end = datetime.now().date()
        default_start = default_end - timedelta(days=7)
        date_input_key = "_global_date_range_input"
        existing_date_range = st.session_state.get(date_input_key)
        if isinstance(existing_date_range, tuple) and len(existing_date_range) == 2:
            clamped_start, clamped_end, was_clamped, max_days = clamp_global_date_range(
                existing_date_range[0],
                existing_date_range[1],
            )
            if was_clamped:
                st.session_state[date_input_key] = (clamped_start, clamped_end)
                st.session_state["global_start_date"] = clamped_start
                st.session_state["global_end_date"] = clamped_end
                clamp_key = f"{clamped_start}|{clamped_end}|{max_days}"
                st.session_state["_global_date_clamp_pending_warning"] = (clamp_key, max_days)
        date_range = st.date_input(
            "Date range",
            value=(
                st.session_state.get("global_start_date", default_start),
                st.session_state.get("global_end_date", default_end),
            ),
            key=date_input_key,
        )
        if isinstance(date_range, tuple) and len(date_range) == 2:
            clamped_start, clamped_end, was_clamped, max_days = clamp_global_date_range(date_range[0], date_range[1])
            st.session_state["global_start_date"] = clamped_start
            st.session_state["global_end_date"] = clamped_end
            pending_clamp_warning = st.session_state.pop("_global_date_clamp_pending_warning", None)
            if pending_clamp_warning:
                clamp_key, max_days = pending_clamp_warning
                if st.session_state.get("_global_date_clamp_notice_key") != clamp_key:
                    st.warning(
                        f"Global date range was clamped to the most recent {max_days} days to keep dashboard scans bounded."
                    )
                    st.session_state["_global_date_clamp_notice_key"] = clamp_key
            elif was_clamped:
                clamp_key = f"{clamped_start}|{clamped_end}|{max_days}"
                if st.session_state.get("_global_date_clamp_notice_key") != clamp_key:
                    st.warning(
                        f"Global date range was clamped to the most recent {max_days} days to keep dashboard scans bounded."
                    )
                    st.session_state["_global_date_clamp_notice_key"] = clamp_key
            else:
                st.session_state.pop("_global_date_clamp_notice_key", None)
        st.selectbox(
            "Environment",
            environment_options,
            index=environment_options.index(
                st.session_state.get("global_environment", DEFAULT_ENVIRONMENT)
                if st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) in environment_options
                else DEFAULT_ENVIRONMENT
            ),
            format_func=lambda key: get_environment_label(key, active_company),
            key="global_environment",
            help=(
                "Trexis PROD uses _PRD databases; All DEV/SIT uses _DEV and _SIT."
                if str(active_company).upper() == "TREXIS"
                else (
                    "Splits ALFA_EDW_PROD from DEV/SAN/PHX/SEA/SIT. "
                    "Cost split is allocated by query database when warehouses are shared."
                )
            ),
        )
        filter_choice_scope = (
            active_company,
            st.session_state.get("global_environment", DEFAULT_ENVIRONMENT),
        )
        if st.session_state.get("_global_filter_choice_scope") != filter_choice_scope:
            st.session_state["_global_filter_choice_scope"] = filter_choice_scope
            try:
                session_for_filters = get_session()
                st.session_state["global_warehouse_options"] = load_warehouse_options(
                    session_for_filters,
                    company=active_company,
                )
                st.session_state["global_database_options"] = load_database_options(
                    session_for_filters,
                    company=active_company,
                )
            except Exception:
                st.session_state["global_warehouse_options"] = []
                st.session_state["global_database_options"] = []

        global_warehouse_options = list(st.session_state.get("global_warehouse_options") or [])
        if global_warehouse_options:
            warehouse_choices = ["All scoped warehouses"] + global_warehouse_options
            if st.session_state.get("global_warehouse_select") not in warehouse_choices:
                st.session_state["global_warehouse_select"] = "All scoped warehouses"
            selected_global_warehouse = st.selectbox(
                "Warehouse",
                warehouse_choices,
                key="global_warehouse_select",
            )
            st.session_state["global_warehouse"] = (
                "" if selected_global_warehouse == "All scoped warehouses" else selected_global_warehouse
            )
        else:
            st.text_input("Warehouse contains", key="global_warehouse")

        st.text_input("User contains", key="global_user")
        st.text_input("Role contains", key="global_role")

        global_database_options = list(st.session_state.get("global_database_options") or [])
        if global_database_options:
            database_choices = ["All scoped databases"] + global_database_options
            if st.session_state.get("global_database_select") not in database_choices:
                st.session_state["global_database_select"] = "All scoped databases"
            selected_global_database = st.selectbox(
                "Database",
                database_choices,
                key="global_database_select",
            )
            st.session_state["global_database"] = (
                "" if selected_global_database == "All scoped databases" else selected_global_database
            )
        else:
            st.text_input("Database contains", key="global_database")

        current_filter_signature = _global_filter_signature()
        previous_filter_signature = st.session_state.get("_prev_global_filter_signature")
        if previous_filter_signature is None:
            st.session_state["_prev_global_filter_signature"] = current_filter_signature
        elif previous_filter_signature != current_filter_signature:
            clear_all_cache(clear_streamlit_cache=False, clear_metadata=False)
            st.session_state["_prev_global_filter_signature"] = current_filter_signature

        if st.button("Clear Global Filters", key="global_filters_clear"):
            for _k in [
                "global_start_date", "global_end_date", "global_warehouse",
                "global_user", "global_role", "global_database", "global_environment",
                "global_warehouse_select", "global_database_select",
                "global_warehouse_options", "global_database_options",
                "_global_filter_choice_scope",
                "_global_date_range_input",
                "_global_date_clamp_notice_key",
            ]:
                st.session_state.pop(_k, None)
            clear_all_cache(clear_streamlit_cache=False, clear_metadata=False)
            st.rerun()

    st.toggle(
        "Exceptions-only mode",
        key="exceptions_only_mode",
        help=(
            "Prioritize failures, cost spikes, queue pressure, suspicious access, "
            "and contract risk. Use this for DBA morning triage and leadership briefs."
        ),
    )

    st.divider()

    # Navigation.
    current_role     = _get_current_role()
    matched_profile  = resolve_role_profile(current_role)
    experience_options = _allowed_experience_options()
    current_experience = _current_experience_view()
    selected_experience = st.selectbox(
        "Experience View",
        experience_options,
        index=experience_options.index(current_experience),
        key="overwatch_experience_view",
        on_change=_sync_experience_navigation,
        help="Filters navigation for the current persona without granting additional Snowflake privileges.",
    )
    visible_sections = _current_visible_sections()
    profile_color    = {
        "ANALYST": "#fbbf24", "MANAGER": "#c084fc", "REPORT": "#fbbf24",
    }.get(matched_profile, "#38bdf8")
    role_label = current_role[:20] or "DBA"

    st.caption(f"{role_label} - {matched_profile} ROLE - {selected_experience} VIEW")
    st.caption("NAVIGATE")

    active_section = _current_active_section(visible_sections)

    def _set_section(section: str) -> None:
        _queue_section_navigation(section)

    for group_name, group_all in NAV_GROUPS.items():
        group_visible = [s for s in group_all if s in visible_sections]
        if not group_visible:
            continue
        st.caption(group_name)
        for section_name in group_visible:
            is_active = section_name == active_section
            st.button(
                section_name,
                key=f"nav_btn_{group_name}_{section_name}",
                type="primary" if is_active else "secondary",
                width="stretch",
                on_click=_set_section,
                args=(section_name,),
            )

    st.divider()

    # Saved views / bookmarks.
    if _sidebar_panel_toggle("Saved Views", "saved_views"):
        _session = st.session_state.get("sf_session")
        saved_views_loaded = bool(st.session_state.get("_overwatch_saved_views_loaded"))
        bookmarks = st.session_state.get("_overwatch_saved_views_cache", [])
        if st.button(
            "Refresh Saved Views" if saved_views_loaded else "Load Saved Views",
            key="bm_load_saved_views",
            width="stretch",
            disabled=not connection_available,
        ):
            try:
                _session = get_session()
                _, load_bookmarks, _, _ = _load_bookmark_helpers()
                bookmarks = load_bookmarks(_session)
                st.session_state["_overwatch_saved_views_cache"] = bookmarks
                st.session_state["_overwatch_saved_views_loaded"] = True
                st.session_state["_overwatch_saved_views_loaded_at"] = datetime.now().strftime("%H:%M:%S")
                saved_views_loaded = True
                st.session_state.pop("_overwatch_connection_unavailable", None)
            except StopException:
                _session = None
                st.session_state["_overwatch_connection_unavailable"] = True
            except Exception as e:
                _session = None
                st.session_state["_overwatch_connection_unavailable"] = True
                st.caption(f"Saved views unavailable until Snowflake is connected. {format_snowflake_error(e)}")

        if not saved_views_loaded:
            st.caption("Saved views are skipped during normal reruns. Load them only when you need to jump or manage views.")
        elif bookmarks:
            loaded_at = st.session_state.get("_overwatch_saved_views_loaded_at", "")
            if loaded_at:
                st.caption(f"Loaded at {loaded_at}. Click a bookmark to jump directly to that view.")
            else:
                st.caption("Click a bookmark to jump directly to that view.")
            for bm in bookmarks:
                shared_badge = " Shared" if bm["shared"] else ""
                uses_badge   = f" - {bm['uses']}x" if bm["uses"] else ""
                col_bm, col_del = st.columns([5, 1])
                with col_bm:
                    if st.button(
                        f"{bm['name']}{shared_badge}{uses_badge}",
                        key=f"bm_apply_{bm['id']}",
                        help=f"Section: {bm['section']}\nCreated: {bm['created']}",
                        width="stretch",
                    ):
                        if not _session:
                            _session = get_session()
                        _, _, apply_bookmark, _ = _load_bookmark_helpers()
                        apply_bookmark(_session, bm)  # calls st.rerun()
                with col_del:
                    if st.button("Delete", key=f"bm_del_{bm['id']}", help="Delete bookmark"):
                        if not _session:
                            _session = get_session()
                        _, _, _, delete_bookmark = _load_bookmark_helpers()
                        if delete_bookmark(_session, bm["id"]):
                            st.session_state.pop("_overwatch_saved_views_cache", None)
                            st.session_state["_overwatch_saved_views_loaded"] = False
                            st.rerun()
        elif saved_views_loaded:
            st.caption("No saved views yet.")

        st.divider()
        st.caption("Save current view")
        new_bm_name = st.text_input(
            "Bookmark name",
            placeholder="e.g. Monday Credit Check",
            label_visibility="collapsed",
            key="bm_name_input",
            max_chars=100,
        )
        bm_shared = st.checkbox("Share with all users", key="bm_shared_toggle")
        if st.button("Save View", key="bm_save_btn"):
            bookmark_name = str(st.session_state.get("bm_name_input") or new_bm_name or "").strip()
            if not bookmark_name:
                st.warning("Enter a bookmark name before saving.")
            else:
                if not _session:
                    try:
                        _session = get_session()
                    except Exception:
                        _session = None
                if not _session:
                    st.warning("Connect Snowflake before saving views.")
                else:
                    save_bookmark, _, _, _ = _load_bookmark_helpers()
                    if save_bookmark(_session, bookmark_name, bm_shared):
                        st.success(f"Saved '{bookmark_name}'")
                        st.session_state.pop("bm_name_input", None)
                        st.session_state.pop("_overwatch_saved_views_cache", None)
                        st.session_state["_overwatch_saved_views_loaded"] = False
                        st.rerun()

        if _session:
            st.caption("Saved View table setup is managed by `snowflake/OVERWATCH_MART_SETUP.sql`.")

    st.divider()

    if _sidebar_panel_toggle("Settings", "settings"):
        render_theme_picker()
        st.divider()
        credit_price = st.number_input(
            "$/credit (compute)",
            min_value=0.50, max_value=20.00,
            value=st.session_state.get("credit_price", DEFAULTS["credit_price"]),
            step=0.10, key="_credit_price_input",
        )
        st.session_state["credit_price"] = credit_price

        storage_cost = st.number_input(
            "$/TB/month (storage)",
            min_value=1.0, max_value=100.0,
            value=st.session_state.get("storage_cost_per_tb", DEFAULTS["storage_cost_per_tb"]),
            step=1.0, key="_storage_cost_input",
        )
        st.session_state["storage_cost_per_tb"] = storage_cost
        alert_email_targets = st.text_input(
            "Alert email recipients",
            value=st.session_state.get("alert_email_targets", DEFAULT_ALERT_EMAIL),
            key="_alert_email_targets_input",
            help="Comma-separated Snowflake notification recipients for generated alert SQL.",
        )
        st.session_state["alert_email_targets"] = str(alert_email_targets or "").strip() or DEFAULT_ALERT_EMAIL
        st.caption(
            "Dollar values use the configured rate. Database, user, role, and query cost views are "
            "allocated estimates unless a panel explicitly marks the metric as exact."
        )

        current_metric_signature = _metric_settings_signature()
        previous_metric_signature = st.session_state.get("_prev_metric_settings_signature")
        if previous_metric_signature is None:
            st.session_state["_prev_metric_settings_signature"] = current_metric_signature
        elif previous_metric_signature != current_metric_signature:
            clear_all_cache(clear_streamlit_cache=False, clear_metadata=False)
            st.session_state["_prev_metric_settings_signature"] = current_metric_signature

        st.selectbox(
            "Live refresh interval",
            [15, 30, 60, 120], index=1,
            format_func=lambda x: f"{x}s",
            key="rt_interval",
        )
        st.toggle(
            "Record section runtime",
            key="_logging_enabled",
            help=(
                "Writes one lightweight usage row per completed section render when the usage log is available."
            ),
        )
        st.toggle(
            "Record query activity",
            key="_query_logging_enabled",
            help="Writes query hash, section, elapsed time, row count, and result size to the OVERWATCH usage log when that table exists.",
        )
        st.toggle(
            "Detailed Snowflake query tags",
            key="_detailed_query_tags_enabled",
            help=(
                "Optional cost-forensics mode: updates QUERY_TAG with section-level context. "
                "Leave off during normal use to avoid extra ALTER SESSION statements."
            ),
        )
        render_admin_mode_control()

        telemetry_count = len(st.session_state.get("_overwatch_query_telemetry", []))
        if telemetry_count:
            st.divider()
            with st.expander(f"OVERWATCH query activity ({telemetry_count:,})", expanded=False):
                st.caption("Query activity summaries are rendered on demand to keep normal sidebar reruns light.")
                if st.button("Render query activity summary", key="render_query_telemetry"):
                    telemetry = get_query_telemetry()
                    total_calls = len(telemetry)
                    total_elapsed = float(telemetry["elapsed_ms"].fillna(0).sum()) / 1000
                    avg_elapsed = float(telemetry["elapsed_ms"].fillna(0).mean())
                    t1, t2 = st.columns(2)
                    t1.metric("App Queries This Session", f"{total_calls:,}")
                    t2.metric("Observed Wait", f"{total_elapsed:,.1f}s", f"{avg_elapsed:,.0f} ms avg")
                    budget_summary = get_query_budget_summary()
                    if not budget_summary.empty:
                        st.caption(
                            "Risk is session-based: High means repeated heavy calls, long total wait, "
                            "or very large result sets."
                        )
                        st.dataframe(
                            budget_summary,
                            width="stretch",
                            height=220,
                            column_config={
                                "section": "Section",
                                "budget_risk": "Budget Risk",
                                "calls": "Calls",
                                "unique_queries": "Unique Queries",
                                "expensive_calls": "Expensive Calls",
                                "elapsed_sec": st.column_config.NumberColumn("Elapsed Sec", format="%.2f"),
                                "max_rows": st.column_config.NumberColumn("Max Rows", format="%d"),
                                "max_result_mb": st.column_config.NumberColumn("Max MB", format="%.1f"),
                            },
                        )
                    st.dataframe(telemetry.tail(50), width="stretch", height=220)
                if st.button("Clear query activity", key="clear_query_telemetry"):
                    clear_query_telemetry()
                    st.rerun()

    st.divider()

    company_color = COMPANY_CONFIG.get(active_company, {}).get("color", "#38bdf8")
    st.markdown(f"""
    <div style="font-size:0.65rem; color:#475569; text-align:center;">
        <div style="color:{company_color}; font-weight:700; margin-bottom:4px;">{active_company} view</div>
        <div>${credit_price:.2f}/credit</div>
        <div style="margin-top:4px;">ACCOUNT_USAGE <=45min lag - IS: live</div>
    </div>
    """, unsafe_allow_html=True)

active_section = _current_active_section(visible_sections)
secondary_chrome_ready = bool(st.session_state.get("_overwatch_secondary_chrome_ready"))
if secondary_chrome_ready:
    if st.button("Ask OVERWATCH", key="ask_overwatch_panel_toggle", type="secondary"):
        st.session_state["_overwatch_show_ask_overwatch"] = not bool(
            st.session_state.get("_overwatch_show_ask_overwatch")
        )

    if st.session_state.get("_overwatch_show_ask_overwatch"):
        with st.expander("Ask OVERWATCH", expanded=True):
            with st.form("ask_overwatch_form", clear_on_submit=False):
                ask_q = st.text_input(
                    "Ask a specific DBA operating question...",
                    placeholder="e.g. What should I work first for cost or task reliability?",
                    key="ask_overwatch_input",
                    max_chars=500,
                )
                ask_submitted = st.form_submit_button("Ask")
            if ask_submitted:
                ask_text = str(st.session_state.get("ask_overwatch_input") or ask_q or "").strip()
                if not ask_text:
                    st.info("Type a specific DBA operating question first.")
                else:
                    from utils.ask_overwatch import answer_ask_overwatch

                    result = answer_ask_overwatch(
                        ask_text[:500],
                        _snapshot_ask_overwatch_state(st.session_state),
                        active_section=active_section,
                        company=active_company,
                        environment=st.session_state.get("global_environment", DEFAULT_ENVIRONMENT),
                        role=current_role or "",
                    )
                    st.markdown(result["answer"])
                    cards = result.get("cards") or []
                    if cards:
                        with st.expander("Evidence used", expanded=False):
                            st.dataframe(cards, width="stretch", hide_index=True, height=260)

# Section dispatch.
active_section = _current_active_section(visible_sections)
st.session_state["_overwatch_active_section"] = active_section

section_signature = _section_render_signature(active_section, active_company, current_role)
transition_slot = st.empty()
section_slot = st.empty()
show_transition = _should_show_section_transition(section_signature)
section_render_started = time.perf_counter()
if show_transition:
    with transition_slot.container():
        _render_section_transition_state(active_section)

try:
    needs_connection = _section_requires_connection(active_section)
    if needs_connection and (not connection_available or st.session_state.get("_overwatch_connection_unavailable")):
        with section_slot.container():
            _render_connection_empty_state(active_section)
        _mark_section_rendered(active_section, section_signature)
    else:
        try:
            with section_slot.container():
                section_guidance.clear_deferred_section_notes(active_section)
                sections.dispatch(active_section)
                section_guidance.render_deferred_section_notes(active_section)
            _mark_section_rendered(active_section, section_signature)
        except StopException:
            st.session_state["_overwatch_connection_unavailable"] = True
            with section_slot.container():
                _render_connection_empty_state(active_section)
            _mark_section_rendered(active_section, section_signature)
        except Exception as e:
            with section_slot.container():
                st.error(f"{active_section} could not finish rendering.")
                st.caption(format_snowflake_error(e))
                st.info(
                    "The Snowflake connection may still be healthy. This usually means one panel hit a metadata, "
                    "permission, or empty-data edge case. Try another section or refresh after the source view is available."
                )
            _mark_section_rendered(active_section, section_signature)
finally:
    duration_ms = int((time.perf_counter() - section_render_started) * 1000)
    st.session_state["_overwatch_last_section_render_ms"] = duration_ms
    st.session_state["_overwatch_secondary_chrome_ready"] = True
    log_section_load(active_section, duration_ms)
    if show_transition:
        transition_slot.empty()
