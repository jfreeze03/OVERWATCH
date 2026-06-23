"""Executive Landing operational risk renderer."""
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
from sections.executive_landing_common import _filter_frame_by_tokens, _format_gb, _format_seconds, _nav_button
from sections.executive_landing_overview_view import _render_snapshot_prompt


def _render_operational_risk(summary: dict, *, snapshot: dict | None, days: int) -> bool:
    st.markdown("**Operational Risk**")
    render_shell_snapshot((
        ("Failed Queries", f"{safe_int(summary.get('failed_queries')):,}"),
        ("Failed Tasks", f"{safe_int(summary.get('failed_tasks')):,}"),
        ("P95 Runtime", _format_seconds(safe_float(summary.get("p95_runtime_sec")))),
        ("Spill", _format_gb(safe_float(summary.get("spill_gb")))),
    ))
    if isinstance(snapshot, dict):
        alerts = _filter_frame_by_tokens(
            snapshot.get("alerts", pd.DataFrame()),
            ("QUERY", "TASK", "PIPELINE", "PROCEDURE", "LOAD", "SLA", "QUEUE", "WAREHOUSE"),
            ("CATEGORY", "ALERT_TYPE", "ENTITY_NAME", "SUGGESTED_ACTION"),
        )
        if not alerts.empty:
            render_priority_dataframe(
                alerts,
                title="Operational alerts and workload risks",
                priority_columns=["SEVERITY", "STATUS", "CATEGORY", "ALERT_TYPE", "ENTITY_NAME", "OWNER", "SUGGESTED_ACTION"],
                sort_by=["SEVERITY", "ALERT_TS"],
                ascending=[True, False],
                raw_label="All operational executive alerts",
                max_rows=8,
                height=260,
            )
    cols = st.columns(3)
    with cols[0]:
        _nav_button("Failure Triage", "DBA Control Room", state_updates={"dba_control_room_active_view": "Failure Triage"})
    with cols[1]:
        _nav_button("Pipeline Health", "Workload Operations", workflow_key="workload_operations_workflow", workflow="Pipeline & Task Health")
    with cols[2]:
        _nav_button("Performance", "Workload Operations", workflow_key="workload_operations_workflow", workflow="Performance & Contention")
    if not isinstance(snapshot, dict):
        return _render_snapshot_prompt(EXECUTIVE_OPERATIONAL_RISK_WORKFLOW, summary, days)
    return False

def render_executive_operational_risk(*, summary: dict, company: str, environment: str, days: int, credit_price: float, board: pd.DataFrame, board_payload: dict | None = None, snapshot: dict | None = None, source_health: pd.DataFrame | None = None) -> bool:
    return _render_operational_risk(summary, snapshot=snapshot, days=int(days))


__all__ = ['_render_operational_risk', 'render_executive_operational_risk']
