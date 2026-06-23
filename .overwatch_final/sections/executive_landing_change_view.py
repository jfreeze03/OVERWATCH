"""Executive Landing change summary renderer."""
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
from sections.executive_landing_admin_view import _render_change_intelligence_summary
from sections.executive_landing_common import _nav_button
from sections.executive_landing_data_health_view import _render_executive_data_health


def _render_change_summary(company: str, environment: str, days: int, *, snapshot: dict | None, source_health: pd.DataFrame) -> bool:
    st.markdown("**Change Summary**")
    _render_change_intelligence_summary(load_change_intelligence_summary(company, environment, days=int(days)))
    if isinstance(snapshot, dict):
        migration = snapshot.get("migration", pd.DataFrame())
        if isinstance(migration, pd.DataFrame) and not migration.empty:
            render_priority_dataframe(
                migration,
                title="Deployment and monitoring coverage changes",
                priority_columns=[
                    "OBJECT_NAME", "OBJECT_TYPE", "MIGRATION_STATE",
                    "CURRENT_VERSION", "EXPECTED_VERSION", "NEXT_ACTION",
                ],
                sort_by=["MIGRATION_STATE", "OBJECT_NAME"],
                ascending=[True, True],
                raw_label="All executive migration rows",
                max_rows=8,
                height=250,
            )
    if isinstance(source_health, pd.DataFrame) and not source_health.empty:
        with st.expander("Change-summary data health", expanded=False):
            _render_executive_data_health(source_health)
    cols = st.columns(3)
    with cols[0]:
        _nav_button("Workload Changes", "Workload Operations", workflow_key="workload_operations_workflow", workflow="Change Analysis")
    with cols[1]:
        _nav_button("Access Changes", "Security Monitoring", workflow_key="security_posture_workflow", workflow="Access Changes", state_updates={"security_posture_view": "Access Changes"})
    with cols[2]:
        _nav_button("DBA Change Watch", "DBA Control Room", state_updates={"dba_control_room_active_view": "Change Watch"})
    return False

def render_executive_change_summary(*, summary: dict, company: str, environment: str, days: int, credit_price: float, board: pd.DataFrame, board_payload: dict | None = None, snapshot: dict | None = None, source_health: pd.DataFrame | None = None) -> bool:
    return _render_change_summary(company, environment, int(days), snapshot=snapshot, source_health=source_health if isinstance(source_health, pd.DataFrame) else pd.DataFrame())


__all__ = ['_render_change_summary', 'render_executive_change_summary']
