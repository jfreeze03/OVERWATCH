# app.py - OVERWATCH main entry point
# -----------------------------------------------------------------------------
# Includes:
#   - Role-based section visibility (ROLE_SECTIONS in config.py)
#   - ALFA default company seeded before radio renders
#   - Cache invalidation on company switch
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
    PRIMARY_NAV_HIDDEN_SECTIONS,
    compatibility_state_for_section,
    default_experience_view_for_role,
    normalize_section_name,
    resolve_allowed_experience_views,
    resolve_role_profile,
    static_database_options,
    static_warehouse_options,
)
import utils as utils_package

if getattr(utils_package, "UTILS_EXPORT_VERSION", "") != "2026-06-06-day-window-export-v1":
    utils_package = importlib.reload(utils_package)

from utils.cache import clear_all_cache
from utils.session import get_session
from utils.logging import log_section_load
from utils.company_filter import (
    get_environment_label,
    get_environment_options_for_company,
    invalidate_company_cache,
)
from utils.admin import render_admin_mode_control
from utils.evidence_mode import (
    TRIAGE_MODE_TRIAGE,
    evidence_mode_from_exceptions,
    exceptions_enabled_from_evidence_mode,
    normalize_evidence_mode,
)
try:
    from utils.admin import clamp_global_date_range
except ImportError:
    def clamp_global_date_range(
        start_date,
        end_date,
        standard_days: int = 35,
        admin_days: int = 90,
    ) -> tuple:
        """Fallback for Snowflake stages that refresh app.py before utils.admin."""
        if not start_date or not end_date:
            return start_date, end_date, False, int(standard_days)
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        try:
            from utils.admin import admin_actions_enabled
            max_days = int(admin_days if admin_actions_enabled() else standard_days)
        except Exception:
            max_days = int(standard_days)
        span_days = (end_date - start_date).days + 1
        if span_days <= max_days:
            return start_date, end_date, False, max_days
        return end_date - timedelta(days=max_days - 1), end_date, True, max_days
import utils.section_guidance as section_guidance

def _lazy_query_call(name: str):
    def _call(*args, **kwargs):
        query_module = importlib.import_module("utils.query")
        return getattr(query_module, name)(*args, **kwargs)

    _call.__name__ = name
    return _call


format_snowflake_error = _lazy_query_call("format_snowflake_error")


CONNECTION_OPTIONAL_SECTIONS = {"Alert Center"}

SECTION_WORKSPACE_STATE_KEYS = {
    "Executive Landing": ("_executive_landing_full_workspace_requested", "_executive_landing_brief_mode"),
    "DBA Control Room": ("_dba_control_room_full_workspace_requested", "_dba_control_room_brief_mode"),
    "Alert Center": ("_alert_center_full_workspace_requested", "_alert_center_brief_mode"),
    "Cost & Contract": ("_cost_contract_full_workspace_requested", "_cost_contract_brief_mode"),
    "Workload Operations": ("_workload_operations_full_workspace_requested", "_workload_operations_brief_mode"),
    "Security Monitoring": ("_security_monitoring_full_workspace_requested", "_security_monitoring_brief_mode"),
}


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

    if getattr(display_module, "DISPLAY_VERSION", "") != "2026-06-05-chart-drillback-cost-v1":
        importlib.reload(display_module)

    if getattr(workflows_module, "WORKFLOWS_VERSION", "") != "2026-06-09-load-status-guard-v1":
        importlib.reload(workflows_module)
        if hasattr(sections, "reload_loaded_sections"):
            sections.reload_loaded_sections()


import sections

if getattr(theme_module, "THEME_VERSION", "") != "2026-06-13-score-shell-white-theme-v1":
    theme_module = importlib.reload(theme_module)
    inject_theme = theme_module.inject_theme
    render_theme_picker = theme_module.render_theme_picker

if getattr(section_guidance, "SECTION_GUIDANCE_VERSION", "") != "2026-06-13-no-bottom-notes-v1":
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
    st.session_state["_detailed_query_tags_enabled"] = True
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
    visible = [
        section
        for section in profile_sections
        if section in base_sections and section not in PRIMARY_NAV_HIDDEN_SECTIONS
    ]
    base_visible = [section for section in base_sections if section not in PRIMARY_NAV_HIDDEN_SECTIONS]
    return visible or base_visible or base_sections


def _normalize_nav_section(section: str) -> str:
    return normalize_section_name(section)


def _apply_section_compatibility_state(section: str) -> None:
    """Apply workflow state for retired routes that now open canonical sections."""
    for key, value in compatibility_state_for_section(section).items():
        st.session_state[key] = value


def _request_section_board_state(section: str) -> None:
    """Make sidebar navigation land on the section board before detailed telemetry."""
    target = _normalize_nav_section(section)
    state_keys = SECTION_WORKSPACE_STATE_KEYS.get(target)
    if not state_keys:
        return
    workspace_key, brief_key = state_keys
    if target == "Executive Landing":
        st.session_state[workspace_key] = True
        st.session_state[brief_key] = False
        return
    st.session_state[workspace_key] = False
    st.session_state[brief_key] = True
    if target == "Security Monitoring":
        st.session_state["_security_posture_full_workspace_requested"] = False
        st.session_state["_security_posture_brief_mode"] = True


def _section_requires_connection(section: str) -> bool:
    return _normalize_nav_section(section) not in CONNECTION_OPTIONAL_SECTIONS


def _queue_section_navigation(section: str) -> None:
    """Mark a section switch before the next rerun starts rendering."""
    raw_section = str(section or "").strip()
    target = _normalize_nav_section(raw_section)
    current = _normalize_nav_section(st.session_state.get("nav_section", ""))
    st.session_state.pop("_overwatch_pending_autoload_section", None)
    st.session_state.pop("_overwatch_pending_autoload_started_at", None)
    if target != current:
        st.session_state["_overwatch_pending_section"] = target
        st.session_state["_overwatch_section_transition_started_at"] = datetime.now().isoformat(timespec="seconds")
    _request_section_board_state(target)
    _apply_section_compatibility_state(raw_section)
    st.session_state["nav_section"] = target


def _sync_experience_navigation() -> None:
    """Keep the active section valid when the persona filter changes."""
    selected = _current_experience_view()
    visible = _resolve_visible_sections_for_experience(selected)
    current = _normalize_nav_section(st.session_state.get("nav_section", visible[0]))
    if current not in visible:
        _queue_section_navigation(visible[0])


def _triage_mode_from_exceptions(enabled: bool) -> str:
    return evidence_mode_from_exceptions(enabled)


def _normalize_triage_mode(mode: object) -> str:
    return normalize_evidence_mode(mode)


def _exceptions_enabled_from_triage_mode(mode: object) -> bool:
    return exceptions_enabled_from_evidence_mode(mode)


def _sync_exceptions_only_mode() -> None:
    st.session_state["exceptions_only_mode"] = _exceptions_enabled_from_triage_mode(
        st.session_state.get("triage_view_mode", TRIAGE_MODE_TRIAGE)
    )


def _ensure_triage_mode_state(default_exceptions: bool) -> None:
    raw_mode = st.session_state.get("triage_view_mode")
    if raw_mode is None:
        st.session_state["triage_view_mode"] = _triage_mode_from_exceptions(
            bool(st.session_state.get("exceptions_only_mode", default_exceptions))
        )
    else:
        st.session_state["triage_view_mode"] = _normalize_triage_mode(raw_mode)
    _sync_exceptions_only_mode()


def _apply_role_based_defaults() -> None:
    """Seed no-click persona defaults for the current Snowflake role."""
    role = _get_current_role()
    profile = resolve_role_profile(role)
    scope = (role, profile)
    if st.session_state.get("_overwatch_role_defaults_scope") == scope:
        return

    default_experience = default_experience_view_for_role(role)
    st.session_state["overwatch_experience_view"] = default_experience
    _ensure_triage_mode_state(profile == "DBA")
    st.session_state["_overwatch_role_defaults_scope"] = scope
    _sync_experience_navigation()


def _global_filter_signature() -> tuple:
    """Return the operator filter state that makes loaded telemetry stale."""
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
        str(st.session_state.get("global_schema", "")),
        str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT)),
        str(date_input),
    )


def _metric_settings_signature() -> tuple:
    """Return settings that change dollarized metrics and derived telemetry."""
    return (
        float(st.session_state.get("credit_price", DEFAULTS["credit_price"])),
        float(st.session_state.get(
            "_ai_credit_price_input",
            st.session_state.get("ai_credit_price", DEFAULTS["ai_credit_price"]),
        )),
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


def _sync_company_environment_state(company: str) -> list[str]:
    """Keep company/environment state valid before section queries hydrate."""
    _prev_company = st.session_state.get("_prev_active_company", DEFAULT_COMPANY)
    if _prev_company != company:
        invalidate_company_cache()
    environment_options = list(get_environment_options_for_company(company))
    if st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) not in environment_options:
        st.session_state["global_environment"] = DEFAULT_ENVIRONMENT
    st.session_state["_prev_active_company"] = company
    return environment_options


def _render_global_date_range_control(*, label: str = "Date range") -> None:
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
        label,
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


def _ensure_global_warehouse_options(company: str) -> None:
    filter_choice_scope = (
        company,
        st.session_state.get("global_environment", DEFAULT_ENVIRONMENT),
    )
    if st.session_state.get("_global_warehouse_choice_scope") == filter_choice_scope:
        return
    st.session_state["_global_warehouse_choice_scope"] = filter_choice_scope
    st.session_state["global_warehouse_options"] = list(static_warehouse_options(company))


def _ensure_global_database_options(company: str) -> None:
    filter_choice_scope = (
        company,
        st.session_state.get("global_environment", DEFAULT_ENVIRONMENT),
    )
    if st.session_state.get("_global_database_choice_scope") == filter_choice_scope:
        return
    st.session_state["_global_database_choice_scope"] = filter_choice_scope
    st.session_state["global_database_options"] = list(
        static_database_options(
            company,
            st.session_state.get("global_environment", DEFAULT_ENVIRONMENT),
        )
    )


def _render_global_environment_control(active_company: str) -> list[str]:
    environment_options = _sync_company_environment_state(active_company)
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
    return environment_options


def _render_global_warehouse_control(active_company: str) -> None:
    _ensure_global_warehouse_options(active_company)
    global_warehouse_options = list(st.session_state.get("global_warehouse_options") or [])
    if global_warehouse_options:
        warehouse_choices = ["All scoped warehouses"] + global_warehouse_options
        current_wh = str(st.session_state.get("global_warehouse", "") or "")
        desired_select = current_wh if current_wh in global_warehouse_options else "All scoped warehouses"
        if st.session_state.get("global_warehouse_select") not in warehouse_choices:
            st.session_state["global_warehouse_select"] = desired_select
        elif current_wh and st.session_state.get("global_warehouse_select") != current_wh:
            st.session_state["global_warehouse_select"] = desired_select
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


def _clear_global_filters() -> None:
    for _k in [
        "global_start_date", "global_end_date", "global_warehouse",
        "global_user", "global_role", "global_database", "global_schema", "global_environment",
        "global_warehouse_select", "global_database_select", "global_schema_select",
        "global_warehouse_options", "global_database_options", "global_schema_options",
        "_global_filter_choice_scope", "_global_warehouse_choice_scope", "_global_database_choice_scope",
        "_global_schema_choice_scope", "_global_date_range_input", "_global_date_clamp_notice_key",
        "_global_date_clamp_pending_warning",
    ]:
        st.session_state.pop(_k, None)
    clear_all_cache(clear_streamlit_cache=False, clear_metadata=False)
    st.rerun()


def _maybe_clear_scope_cache_on_filter_change() -> None:
    current_filter_signature = _global_filter_signature()
    previous_filter_signature = st.session_state.get("_prev_global_filter_signature")
    if previous_filter_signature is None:
        st.session_state["_prev_global_filter_signature"] = current_filter_signature
    elif previous_filter_signature != current_filter_signature:
        clear_all_cache(clear_streamlit_cache=False, clear_metadata=False)
        st.session_state["_prev_global_filter_signature"] = current_filter_signature


def _render_topbar_filter_strip(active_company: str) -> str:
    """Render the high-use operator filters above every section."""
    st.markdown(
        """
        <div class="ow-filter-strip-shell">
            <div class="ow-filter-strip-kicker">Triage Filters</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    c_company, c_env, c_date = st.columns([1.2, 1.35, 2.45])
    with c_company:
        selected_company = st.selectbox(
            "Company view",
            list(COMPANY_CONFIG.keys()),
            index=list(COMPANY_CONFIG.keys()).index(active_company)
            if active_company in COMPANY_CONFIG else 0,
            key="active_company",
        )
    with c_env:
        _render_global_environment_control(selected_company)
    with c_date:
        _render_global_date_range_control()
    c_wh, c_user, c_clear = st.columns([2.5, 1.7, 0.75])
    with c_wh:
        _render_global_warehouse_control(selected_company)
    with c_user:
        st.text_input("User contains", key="global_user")
    with c_clear:
        st.write("")
        if st.button("Clear", key="global_filters_clear_topbar", width="stretch"):
            _clear_global_filters()
    return str(selected_company or active_company)


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
    "Executive Landing": "Board-ready risk, cost movement, action closure, and telemetry trust.",
    "DBA Control Room": "Morning triage, route status, data health, and release risk.",
    "Alert Center": "Consolidated incidents, email digests, annotation history, and control status.",
    "Workload Operations": "Query history, task graphs, stored procedures, pipeline health, and runbooks.",
    "Cost & Contract": "Spend attribution, contract utilization, chargeback, savings, and action queue.",
    "Security Monitoring": "Login risk, privileged grants, public access, data sharing, and security alerts.",
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
    return "".join(chips)


def _render_app_header(section: str, company: str, credit_price: float, role: str) -> None:
    section = _normalize_nav_section(section)
    icon = SECTION_ICONS.get(section, "target")
    now_label = datetime.now().strftime("%Y-%m-%d %H:%M")
    safe_section = html.escape(section)
    safe_subtitle = html.escape(_section_subtitle(section), quote=True)
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
                        <div class="ow-section-title" title="{safe_subtitle}">{safe_section}</div>
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
                    Clearing the previous view while {safe_pending} renders fresh DBA telemetry.
                </div>
                <div class="ow-section-transition-bar"><span></span></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


_apply_role_based_defaults()
current_role = _get_current_role()
visible_sections = _current_visible_sections()
active_section = _current_active_section(visible_sections)
active_company = str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)
credit_price = _current_credit_price()
st.session_state["_overwatch_active_section"] = active_section

# Paint the main app shell before the sidebar and selected section hydrate. During
# high-concurrency startup this gives users an immediate, stable command-center frame.
_render_app_header(active_section, active_company, credit_price, current_role)
active_company = _render_topbar_filter_strip(active_company)

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

    if _sidebar_panel_toggle("Advanced Scope", "advanced_scope"):
        st.caption("Optional role, database, and schema narrowing. Primary triage filters live above the page.")
        st.text_input("Role contains", key="global_role")
        _ensure_global_database_options(active_company)

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

        selected_database = str(st.session_state.get("global_database", "") or "").strip()
        schema_choice_scope = (
            active_company,
            st.session_state.get("global_environment", DEFAULT_ENVIRONMENT),
            selected_database,
        )
        if selected_database and st.session_state.get("_global_schema_choice_scope") != schema_choice_scope:
            st.session_state["_global_schema_choice_scope"] = schema_choice_scope
            st.session_state["global_schema_options"] = []
        elif not selected_database:
            st.session_state.pop("_global_schema_choice_scope", None)
            st.session_state.pop("global_schema_options", None)

        global_schema_options = list(st.session_state.get("global_schema_options") or [])
        if selected_database and global_schema_options:
            schema_choices = ["All schemas in database"] + global_schema_options
            if st.session_state.get("global_schema_select") not in schema_choices:
                st.session_state["global_schema_select"] = "All schemas in database"
            selected_global_schema = st.selectbox(
                "Schema",
                schema_choices,
                key="global_schema_select",
            )
            st.session_state["global_schema"] = (
                "" if selected_global_schema == "All schemas in database" else selected_global_schema
            )
        else:
            st.text_input("Schema contains", key="global_schema")

        if st.button("Clear All Filters", key="global_filters_clear"):
            _clear_global_filters()

    # Evidence depth is section-owned. Keep legacy session keys normalized for
    # deep links only; do not expose a global operator knob.
    _ensure_triage_mode_state(resolve_role_profile(_get_current_role()) == "DBA")
    _sync_exceptions_only_mode()

    st.divider()

    # Navigation.
    current_role     = _get_current_role()
    matched_profile  = resolve_role_profile(current_role)
    experience_options = _allowed_experience_options()
    current_experience = _current_experience_view()
    selected_experience = st.selectbox(
        "Navigation View",
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

    st.caption(f"{role_label} - {matched_profile} role - {selected_experience} view")

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

        ai_credit_price = st.number_input(
            "$/AI credit (Cortex)",
            min_value=0.50, max_value=20.00,
            value=st.session_state.get("ai_credit_price", DEFAULTS["ai_credit_price"]),
            step=0.10, key="_ai_credit_price_input",
        )
        st.session_state["ai_credit_price"] = ai_credit_price

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
        render_admin_mode_control()

    st.divider()

    company_color = COMPANY_CONFIG.get(active_company, {}).get("color", "#38bdf8")
    st.markdown(f"""
    <div style="font-size:0.65rem; color:#475569; text-align:center;">
        <div style="color:{company_color}; font-weight:700; margin-bottom:4px;">{active_company} view</div>
        <div>${credit_price:.2f}/credit</div>
        <div style="margin-top:4px;">Live metadata is current; account history may lag up to 45 minutes.</div>
    </div>
    """, unsafe_allow_html=True)

_maybe_clear_scope_cache_on_filter_change()
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
                sections.dispatch(active_section)
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
