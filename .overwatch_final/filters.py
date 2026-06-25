"""Global operator filters for the OVERWATCH shell.

This module owns the topbar filters, advanced scope controls, and filter
signature used to invalidate loaded telemetry.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import streamlit as st

from config import (
    COMPANY_CONFIG,
    DEFAULT_COMPANY,
    DEFAULT_ENVIRONMENT,
    static_database_options,
    static_warehouse_options,
)
from runtime_state import (
    ACTIVE_COMPANY,
    GLOBAL_DATABASE,
    GLOBAL_DATABASE_CHOICE_SCOPE,
    GLOBAL_DATABASE_OPTIONS,
    GLOBAL_DATABASE_SELECT,
    GLOBAL_DATE_RANGE_INPUT,
    GLOBAL_DATE_CLAMP_NOTICE_KEY,
    GLOBAL_DATE_CLAMP_PENDING_WARNING,
    GLOBAL_END_DATE,
    GLOBAL_ENVIRONMENT,
    GLOBAL_FILTER_KEYS,
    GLOBAL_ROLE,
    GLOBAL_SCHEMA,
    GLOBAL_SCHEMA_CHOICE_SCOPE,
    GLOBAL_SCHEMA_OPTIONS,
    GLOBAL_SCHEMA_SELECT,
    GLOBAL_START_DATE,
    GLOBAL_USER,
    GLOBAL_WAREHOUSE,
    GLOBAL_WAREHOUSE_CHOICE_SCOPE,
    GLOBAL_WAREHOUSE_OPTIONS,
    GLOBAL_WAREHOUSE_SELECT,
    PREV_GLOBAL_FILTER_SIGNATURE,
    PREV_ACTIVE_COMPANY,
    WIDGET_GLOBAL_FILTERS_CLEAR,
    WIDGET_GLOBAL_FILTERS_CLEAR_TOPBAR,
    clear_scoped_state,
    get_state,
    pop_state,
    set_state,
)
from utils.cache import clear_all_cache
from utils.company_filter import (
    get_environment_label,
    get_environment_options_for_company,
    invalidate_company_cache,
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
        """Fallback for Snowflake stages that refresh filters before utils.admin."""
        if not start_date or not end_date:
            return start_date, end_date, False, int(standard_days)
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        max_days = int(admin_days)
        span_days = (end_date - start_date).days + 1
        if span_days <= max_days:
            return start_date, end_date, False, max_days
        return end_date - timedelta(days=max_days - 1), end_date, True, max_days


def global_filter_signature() -> tuple:
    """Return the operator filter state that makes loaded telemetry stale."""
    date_input = get_state(GLOBAL_DATE_RANGE_INPUT, ())
    if isinstance(date_input, list):
        date_input = tuple(date_input)
    return (
        str(get_state(GLOBAL_START_DATE, "")),
        str(get_state(GLOBAL_END_DATE, "")),
        str(get_state(GLOBAL_WAREHOUSE, "")),
        str(get_state(GLOBAL_USER, "")),
        str(get_state(GLOBAL_ROLE, "")),
        str(get_state(GLOBAL_DATABASE, "")),
        str(get_state(GLOBAL_SCHEMA, "")),
        str(get_state(GLOBAL_ENVIRONMENT, DEFAULT_ENVIRONMENT)),
        str(date_input),
    )


def sync_company_environment_state(company: str) -> list[str]:
    """Keep company/environment state valid before section queries hydrate."""
    previous_company = get_state(PREV_ACTIVE_COMPANY, DEFAULT_COMPANY)
    if previous_company != company:
        invalidate_company_cache()
    environment_options = list(get_environment_options_for_company(company))
    if get_state(GLOBAL_ENVIRONMENT, DEFAULT_ENVIRONMENT) not in environment_options:
        set_state(GLOBAL_ENVIRONMENT, DEFAULT_ENVIRONMENT)
    set_state(PREV_ACTIVE_COMPANY, company)
    return environment_options


def render_global_date_range_control(*, label: str = "Date range") -> None:
    """Render the bounded global date range control."""
    default_end = datetime.now().date()
    default_start = default_end - timedelta(days=7)
    existing_date_range = get_state(GLOBAL_DATE_RANGE_INPUT)
    if isinstance(existing_date_range, tuple) and len(existing_date_range) == 2:
        clamped_start, clamped_end, was_clamped, max_days = clamp_global_date_range(
            existing_date_range[0],
            existing_date_range[1],
        )
        if was_clamped:
            set_state(GLOBAL_DATE_RANGE_INPUT, (clamped_start, clamped_end))
            set_state(GLOBAL_START_DATE, clamped_start)
            set_state(GLOBAL_END_DATE, clamped_end)
            clamp_key = f"{clamped_start}|{clamped_end}|{max_days}"
            set_state(GLOBAL_DATE_CLAMP_PENDING_WARNING, (clamp_key, max_days))
    else:
        set_state(
            GLOBAL_DATE_RANGE_INPUT,
            (
                get_state(GLOBAL_START_DATE, default_start),
                get_state(GLOBAL_END_DATE, default_end),
            ),
        )
    date_range = st.date_input(
        label,
        key=GLOBAL_DATE_RANGE_INPUT,
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        clamped_start, clamped_end, was_clamped, max_days = clamp_global_date_range(date_range[0], date_range[1])
        set_state(GLOBAL_START_DATE, clamped_start)
        set_state(GLOBAL_END_DATE, clamped_end)
        pending_clamp_warning = pop_state(GLOBAL_DATE_CLAMP_PENDING_WARNING, None)
        if pending_clamp_warning:
            clamp_key, max_days = pending_clamp_warning
            if get_state(GLOBAL_DATE_CLAMP_NOTICE_KEY) != clamp_key:
                st.warning(
                    f"Global date range was clamped to the most recent {max_days} days to keep dashboard scans bounded."
                )
                set_state(GLOBAL_DATE_CLAMP_NOTICE_KEY, clamp_key)
        elif was_clamped:
            clamp_key = f"{clamped_start}|{clamped_end}|{max_days}"
            if get_state(GLOBAL_DATE_CLAMP_NOTICE_KEY) != clamp_key:
                st.warning(
                    f"Global date range was clamped to the most recent {max_days} days to keep dashboard scans bounded."
                )
                set_state(GLOBAL_DATE_CLAMP_NOTICE_KEY, clamp_key)
        else:
            pop_state(GLOBAL_DATE_CLAMP_NOTICE_KEY, None)


def ensure_global_warehouse_options(company: str) -> None:
    """Seed warehouse filter choices for the active scope."""
    filter_choice_scope = (
        company,
        get_state(GLOBAL_ENVIRONMENT, DEFAULT_ENVIRONMENT),
    )
    if get_state(GLOBAL_WAREHOUSE_CHOICE_SCOPE) == filter_choice_scope:
        return
    set_state(GLOBAL_WAREHOUSE_CHOICE_SCOPE, filter_choice_scope)
    set_state(GLOBAL_WAREHOUSE_OPTIONS, list(static_warehouse_options(company)))


def ensure_global_database_options(company: str) -> None:
    """Seed database filter choices for the active scope."""
    filter_choice_scope = (
        company,
        get_state(GLOBAL_ENVIRONMENT, DEFAULT_ENVIRONMENT),
    )
    if get_state(GLOBAL_DATABASE_CHOICE_SCOPE) == filter_choice_scope:
        return
    set_state(GLOBAL_DATABASE_CHOICE_SCOPE, filter_choice_scope)
    set_state(GLOBAL_DATABASE_OPTIONS, list(
        static_database_options(
            company,
            get_state(GLOBAL_ENVIRONMENT, DEFAULT_ENVIRONMENT),
        )
    ))


def render_global_environment_control(active_company: str) -> list[str]:
    """Render the company-scoped environment selector."""
    environment_options = sync_company_environment_state(active_company)
    st.selectbox(
        "Environment",
        environment_options,
        index=environment_options.index(
            get_state(GLOBAL_ENVIRONMENT, DEFAULT_ENVIRONMENT)
            if get_state(GLOBAL_ENVIRONMENT, DEFAULT_ENVIRONMENT) in environment_options
            else DEFAULT_ENVIRONMENT
        ),
        format_func=lambda key: get_environment_label(key, active_company),
        key=GLOBAL_ENVIRONMENT,
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


def render_global_warehouse_control(active_company: str) -> None:
    """Render the global warehouse selector or free-text fallback."""
    ensure_global_warehouse_options(active_company)
    global_warehouse_options = list(get_state(GLOBAL_WAREHOUSE_OPTIONS) or [])
    if global_warehouse_options:
        warehouse_choices = ["All scoped warehouses"] + global_warehouse_options
        current_wh = str(get_state(GLOBAL_WAREHOUSE, "") or "")
        desired_select = current_wh if current_wh in global_warehouse_options else "All scoped warehouses"
        if get_state(GLOBAL_WAREHOUSE_SELECT) not in warehouse_choices:
            set_state(GLOBAL_WAREHOUSE_SELECT, desired_select)
        elif current_wh and get_state(GLOBAL_WAREHOUSE_SELECT) != current_wh:
            set_state(GLOBAL_WAREHOUSE_SELECT, desired_select)
        selected_global_warehouse = st.selectbox(
            "Warehouse",
            warehouse_choices,
            key=GLOBAL_WAREHOUSE_SELECT,
        )
        set_state(GLOBAL_WAREHOUSE, (
            "" if selected_global_warehouse == "All scoped warehouses" else selected_global_warehouse
        ))
    else:
        st.text_input("Warehouse contains", key=GLOBAL_WAREHOUSE)


def clear_global_filters() -> None:
    """Clear all global filter state and invalidate loaded data."""
    clear_scoped_state(GLOBAL_FILTER_KEYS)
    clear_all_cache(clear_streamlit_cache=False, clear_metadata=False)
    st.rerun()


def maybe_clear_scope_cache_on_filter_change() -> None:
    """Invalidate loaded telemetry when global filters change."""
    current_filter_signature = global_filter_signature()
    previous_filter_signature = get_state(PREV_GLOBAL_FILTER_SIGNATURE)
    if previous_filter_signature is None:
        set_state(PREV_GLOBAL_FILTER_SIGNATURE, current_filter_signature)
    elif previous_filter_signature != current_filter_signature:
        clear_all_cache(clear_streamlit_cache=False, clear_metadata=False)
        set_state(PREV_GLOBAL_FILTER_SIGNATURE, current_filter_signature)


def render_topbar_filter_strip(active_company: str) -> str:
    """Render the high-use operator filters above every section."""
    st.markdown(
        """
        <div class="ow-filter-strip-shell">
            <div class="ow-filter-strip-kicker">Triage Filters</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    c_company, c_env, c_date, c_wh, c_clear = st.columns([1.0, 1.08, 2.2, 1.8, 0.68])
    with c_company:
        selected_company = st.selectbox(
            "Company view",
            list(COMPANY_CONFIG.keys()),
            index=list(COMPANY_CONFIG.keys()).index(active_company)
            if active_company in COMPANY_CONFIG else 0,
            key=ACTIVE_COMPANY,
        )
    with c_env:
        render_global_environment_control(selected_company)
    with c_date:
        render_global_date_range_control()
    with c_wh:
        render_global_warehouse_control(selected_company)
    with c_clear:
        st.write("")
        if st.button("Clear", key=WIDGET_GLOBAL_FILTERS_CLEAR_TOPBAR, width="stretch"):
            clear_global_filters()
    return str(selected_company or active_company)


def render_advanced_scope_controls(active_company: str) -> None:
    """Render optional user, role, database, and schema narrowing controls."""
    st.text_input("User contains", key=GLOBAL_USER)
    st.text_input("Role contains", key=GLOBAL_ROLE)
    ensure_global_database_options(active_company)

    global_database_options = list(get_state(GLOBAL_DATABASE_OPTIONS) or [])
    if global_database_options:
        database_choices = ["All scoped databases"] + global_database_options
        if get_state(GLOBAL_DATABASE_SELECT) not in database_choices:
            set_state(GLOBAL_DATABASE_SELECT, "All scoped databases")
        selected_global_database = st.selectbox(
            "Database",
            database_choices,
            key=GLOBAL_DATABASE_SELECT,
        )
        set_state(GLOBAL_DATABASE, (
            "" if selected_global_database == "All scoped databases" else selected_global_database
        ))
    else:
        st.text_input("Database contains", key=GLOBAL_DATABASE)

    selected_database = str(get_state(GLOBAL_DATABASE, "") or "").strip()
    schema_choice_scope = (
        active_company,
        get_state(GLOBAL_ENVIRONMENT, DEFAULT_ENVIRONMENT),
        selected_database,
    )
    if selected_database and get_state(GLOBAL_SCHEMA_CHOICE_SCOPE) != schema_choice_scope:
        set_state(GLOBAL_SCHEMA_CHOICE_SCOPE, schema_choice_scope)
        set_state(GLOBAL_SCHEMA_OPTIONS, [])
    elif not selected_database:
        pop_state(GLOBAL_SCHEMA_CHOICE_SCOPE, None)
        pop_state(GLOBAL_SCHEMA_OPTIONS, None)

    global_schema_options = list(get_state(GLOBAL_SCHEMA_OPTIONS) or [])
    if selected_database and global_schema_options:
        schema_choices = ["All schemas in database"] + global_schema_options
        if get_state(GLOBAL_SCHEMA_SELECT) not in schema_choices:
            set_state(GLOBAL_SCHEMA_SELECT, "All schemas in database")
        selected_global_schema = st.selectbox(
            "Schema",
            schema_choices,
            key=GLOBAL_SCHEMA_SELECT,
        )
        set_state(GLOBAL_SCHEMA, (
            "" if selected_global_schema == "All schemas in database" else selected_global_schema
        ))
    else:
        st.text_input("Schema contains", key=GLOBAL_SCHEMA)

    if st.button("Clear All Filters", key=WIDGET_GLOBAL_FILTERS_CLEAR):
        clear_global_filters()
