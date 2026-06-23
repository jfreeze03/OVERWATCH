"""Executive Landing data-health and alert-context panels."""
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
from sections.executive_landing_models import _source_health_rows


def _render_executive_data_health(source_health: pd.DataFrame) -> None:
    if not isinstance(source_health, pd.DataFrame) or source_health.empty:
        return
    loaded_sources = int(source_health["STATE"].eq("Loaded").sum()) if "STATE" in source_health.columns else 0
    limited_sources = int(source_health["STATE"].eq("Limited").sum()) if "STATE" in source_health.columns else 0
    no_row_sources = int(source_health["STATE"].eq("No Rows").sum()) if "STATE" in source_health.columns else 0
    render_shell_snapshot((
        ("Inputs Ready", f"{loaded_sources}/4"),
        ("Limited Inputs", f"{limited_sources}"),
        ("No-Row Inputs", f"{no_row_sources}"),
    ))
    with st.expander("Executive Data Health", expanded=False):
        render_priority_dataframe(
            source_health,
            title="Executive data health",
            priority_columns=["SOURCE", "STATE", "EVIDENCE", "NEXT_ACTION"],
            sort_by=["STATE", "SOURCE"],
            ascending=[True, True],
            raw_label="All executive data-health rows",
            height=220,
        )

def _render_loaded_executive_alert_context() -> None:
    board = build_loaded_section_alert_signal_board(st.session_state, section="Executive Landing", limit=8)
    if board.empty:
        return
    render_priority_dataframe(
        board,
        title="Loaded alert signals affecting the executive summary",
        priority_columns=[
            "SECTION_FOCUS", "SEVERITY", "SLA_STATE", "CATEGORY", "SIGNAL",
            "ENTITY", "OWNER", "ROUTE", "FIRST_RESPONSE", "RECOMMENDED_ACTION",
            "OPEN_PATH", "AUTOMATION_READINESS",
        ],
        sort_by=["PRIORITY"],
        ascending=True,
        raw_label="All loaded executive alert context rows",
        height=260,
        max_rows=6,
    )
    top = board.iloc[0]
    cols = st.columns(2)
    with cols[0]:
        if st.button("Open Alert Command", key="executive_alert_open_command", width="stretch"):
            apply_section_workflow_navigation(
                "Alert Center",
                alert_center_view=str(top.get("ALERT_CENTER_VIEW") or "Active Alerts"),
            )
            st.rerun()
    with cols[1]:
        if st.button("Open Impacted Section", key="executive_alert_open_impacted_section", width="stretch"):
            apply_section_workflow_navigation(
                str(top.get("DESTINATION_SECTION") or "Alert Center"),
                workflow=str(top.get("DESTINATION_WORKFLOW") or "Active Alerts"),
                alert_center_view=str(top.get("ALERT_CENTER_VIEW") or "Active Alerts"),
            )
            st.rerun()


__all__ = ['_render_executive_data_health', '_render_loaded_executive_alert_context']
