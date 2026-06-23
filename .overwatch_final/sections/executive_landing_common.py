"""Executive Landing scope, formatting, and navigation helpers."""
from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from config import (
    ACTION_QUEUE_TABLE,
    ALERT_DB,
    ALERT_SCHEMA,
    DEFAULT_COMPANY,
    DEFAULT_DAY_WINDOW,
    DEFAULT_ENVIRONMENT,
    DEFAULTS,
    DAY_WINDOW_OPTIONS,
)
from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.navigation import apply_navigation_state, apply_section_workflow_navigation
from sections.shell_helpers import (
    render_escaped_bold_text,
    render_refresh_contract,
    render_shell_kpi_row,
    render_shell_snapshot,
    render_shell_status_strip,
)
from runtime_state import EXECUTIVE_LANDING_WORKFLOW
from route_registry import normalize_workflow_alias
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_source_note


pd = lazy_pandas()

build_mart_cost_cockpit_sql = _lazy_util("build_mart_cost_cockpit_sql")
build_schema_migration_status_sql = _lazy_util("build_schema_migration_status_sql")
credits_to_dollars = _lazy_util("credits_to_dollars")
format_snowflake_error = _lazy_util("format_snowflake_error")
get_environment_label = _lazy_util("get_environment_label")
get_session_for_action = _lazy_util("get_session_for_action")
load_action_queue = _lazy_util("load_action_queue")
load_alert_history = _lazy_util("load_alert_history")
mart_object_name = _lazy_util("mart_object_name")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
build_loaded_section_alert_signal_board = _lazy_util("build_loaded_section_alert_signal_board")
load_enterprise_operating_rollups = _lazy_util("load_enterprise_operating_rollups")
load_change_intelligence_summary = _lazy_util("load_change_intelligence_summary")
load_closed_loop_summary = _lazy_util("load_closed_loop_summary")
load_command_center_summary = _lazy_util("load_command_center_summary")
load_executive_scorecard_summary = _lazy_util("load_executive_scorecard_summary")
load_executive_forecast_summary = _lazy_util("load_executive_forecast_summary")
load_production_readiness_summary = _lazy_util("load_production_readiness_summary")
render_workflow_selector = _lazy_util("render_workflow_selector")
run_query = _lazy_util("run_query")
safe_identifier = _lazy_util("safe_identifier")
snowflake_connection_known_unavailable = _lazy_util("snowflake_connection_known_unavailable")
sql_literal = _lazy_util("sql_literal")


from sections.executive_landing_contracts import *


def _altair():
    """Load Altair only when charts are shown."""
    import altair as alt

    return alt

def _active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)

def _active_environment() -> str:
    return str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)

def _credit_price() -> float:
    return safe_float(st.session_state.get("credit_price", DEFAULTS.get("credit_price", 3.68)), 3.68)

def _money(value: float, *, signed: bool = False) -> str:
    number = safe_float(value)
    prefix = "+" if signed and number > 0 else ""
    if abs(number) >= 1000:
        return f"{prefix}${number:,.0f}"
    return f"{prefix}${number:,.2f}"

def _format_seconds(value: float) -> str:
    seconds = safe_float(value)
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h"
    if seconds >= 60:
        return f"{seconds / 60:.1f}m"
    return f"{seconds:.1f}s"

def _format_gb(value: float) -> str:
    gb = safe_float(value)
    if gb >= 1024:
        return f"{gb / 1024:.1f} TB"
    return f"{gb:.1f} GB"

def _format_metric_value(value: float, unit: str) -> str:
    unit_key = str(unit or "").lower()
    if "usd" in unit_key:
        return _money(safe_float(value))
    if unit_key == "seconds":
        return _format_seconds(value)
    if unit_key == "gb":
        return _format_gb(value)
    if unit_key == "score":
        from sections.executive_landing_models import _platform_score_state

        return _platform_score_state(value)
    if unit_key in {"queries", "tasks", "alerts", "actions"}:
        return f"{safe_int(value):,}"
    if unit_key == "tb_usd":
        return f"{safe_float(value):,.2f} TB"
    return f"{safe_float(value):,.2f}"

def _nav_button(
    label: str,
    section: str,
    *,
    workflow_key: str = "",
    workflow: str = "",
    state_updates: dict[str, str] | None = None,
) -> None:
    if st.button(label, key=f"executive_nav_{section}_{workflow or label}", width="stretch"):
        apply_navigation_state(section)
        if workflow_key and workflow:
            st.session_state[workflow_key] = workflow
        for key, value in (state_updates or {}).items():
            st.session_state[key] = value
        st.rerun()

def normalize_executive_landing_workflow(value: object) -> str:
    """Map legacy executive routes into the current front-door workflows."""
    return normalize_workflow_alias(
        "Executive Landing",
        value,
        default=EXECUTIVE_OVERVIEW_WORKFLOW,
    )

def _ensure_executive_landing_workflow_state() -> str:
    workflow = normalize_executive_landing_workflow(st.session_state.get(EXECUTIVE_LANDING_WORKFLOW))
    st.session_state[EXECUTIVE_LANDING_WORKFLOW] = workflow
    return workflow

def _format_delta_credits(summary: dict, *, credit_price: float) -> str:
    credits = safe_float(summary.get("cost_delta"))
    usd = credits_to_dollars(credits, credit_price)
    return f"{credits:+,.2f} credits / {_money(usd, signed=True)}"

def _filter_frame_by_tokens(
    frame: pd.DataFrame,
    tokens: tuple[str, ...],
    columns: tuple[str, ...],
) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame()
    available = [column for column in columns if column in frame.columns]
    if not available:
        return pd.DataFrame()
    search = frame[available].fillna("").astype(str).agg(" ".join, axis=1).str.upper()
    mask = search.apply(lambda value: any(token in value for token in tokens))
    return frame.loc[mask].copy()


__all__ = ['_altair', '_active_company', '_active_environment', '_credit_price', '_money', '_format_seconds', '_format_gb', '_format_metric_value', '_nav_button', 'normalize_executive_landing_workflow', '_ensure_executive_landing_workflow_state', '_format_delta_credits', '_filter_frame_by_tokens']
