"""Executive Landing actions renderer."""
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
from sections.executive_landing_models import _decision_rows
from sections.executive_landing_overview_view import _render_snapshot_prompt


def _render_executive_actions(summary: dict, *, snapshot: dict | None, days: int) -> bool:
    st.markdown("**Executive Actions**")
    render_priority_dataframe(
        _decision_rows(summary).head(5),
        title="Top action items",
        priority_columns=["PRIORITY", "DECISION_AREA", "SIGNAL", "NEXT_ACTION", "WORKFLOW"],
        sort_by=["PRIORITY"],
        ascending=True,
        raw_label="All executive action rows",
        height=230,
        max_rows=5,
    )
    if isinstance(snapshot, dict):
        queue = snapshot.get("queue", pd.DataFrame())
        if isinstance(queue, pd.DataFrame) and not queue.empty:
            render_priority_dataframe(
                queue,
                title="Loaded owner action queue",
                priority_columns=[
                    "SEVERITY", "STATUS", "CATEGORY", "ENTITY_NAME",
                    "OWNER", "DUE_DATE", "NEXT_ACTION", "OWNER_ROUTE",
                ],
                sort_by=["SEVERITY", "DUE_DATE"],
                ascending=[True, True],
                raw_label="All loaded executive action queue rows",
                max_rows=8,
                height=280,
            )
        return False
    return _render_snapshot_prompt(EXECUTIVE_ACTIONS_WORKFLOW, summary, days)

def render_executive_actions(*, summary: dict, company: str, environment: str, days: int, credit_price: float, board: pd.DataFrame, board_payload: dict | None = None, snapshot: dict | None = None, source_health: pd.DataFrame | None = None) -> bool:
    return _render_executive_actions(summary, snapshot=snapshot, days=int(days))


__all__ = ['_render_executive_actions', 'render_executive_actions']
