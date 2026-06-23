"""Executive Landing cost movement renderer."""
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
from sections.executive_landing_admin_view import _render_executive_forecast_summary
from sections.executive_landing_common import _format_delta_credits, _money, _nav_button
from sections.executive_landing_models import _obs_rows


def _render_cost_movement(summary: dict, *, company: str, environment: str, days: int, credit_price: float, board: pd.DataFrame) -> bool:
    st.markdown("**Cost Movement**")
    current_spend = safe_float(
        summary.get("current_spend_usd"),
        credits_to_dollars(safe_float(summary.get("current_credits")), credit_price),
    )
    run_rate = current_spend / max(int(days), 1) * 30.0
    render_shell_snapshot((
        ("Spend", _money(current_spend)),
        ("Movement", _format_delta_credits(summary, credit_price=credit_price)),
        ("30d Run Rate", _money(run_rate)),
        ("Top Driver", str(summary.get("top_cost_driver") or "On demand")),
    ))
    cost_driver = _obs_rows(board, "COST_DRIVER").copy()
    if isinstance(cost_driver, pd.DataFrame) and not cost_driver.empty:
        render_priority_dataframe(
            cost_driver,
            title="Top cost movement drivers",
            priority_columns=["DIMENSION", "VALUE_USD", "VALUE", "UNIT", "PERIOD_START"],
            sort_by=["VALUE_USD"],
            ascending=False,
            raw_label="All executive cost movement rows",
            max_rows=8,
            height=240,
        )
    _render_executive_forecast_summary(load_executive_forecast_summary(company, environment, days=int(days)))
    cols = st.columns(3)
    with cols[0]:
        _nav_button("Cost Overview", "Cost & Contract", workflow_key="cost_contract_workflow", workflow="Cost Overview")
    with cols[1]:
        _nav_button("Warehouse Spend", "Cost & Contract", workflow_key="cost_contract_workflow", workflow="Cost by Warehouse")
    with cols[2]:
        _nav_button("Burn / Forecast", "Cost & Contract", workflow_key="cost_contract_workflow", workflow="Burn Rate & Forecast")
    return False

def render_executive_cost_movement(*, summary: dict, company: str, environment: str, days: int, credit_price: float, board: pd.DataFrame, board_payload: dict | None = None, snapshot: dict | None = None, source_health: pd.DataFrame | None = None) -> bool:
    return _render_cost_movement(summary, company=company, environment=environment, days=int(days), credit_price=credit_price, board=board)


__all__ = ['_render_cost_movement', 'render_executive_cost_movement']
