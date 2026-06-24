"""Executive Landing overview renderer."""
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
from sections.executive_landing_common import _format_delta_credits, _format_gb, _format_seconds, _money, _nav_button
from sections.executive_landing_data_health_view import _render_loaded_executive_alert_context
from sections.executive_landing_models import _decision_rows, _executive_action_brief, _platform_score_state


def _render_executive_action_brief(summary: dict | None, days: int, *, show_strip: bool = True) -> bool:
    brief = _executive_action_brief(summary)
    button_help = " ".join(
        part for part in (str(brief.get("headline") or ""), str(brief.get("detail") or "")) if part
    )
    if show_strip:
        render_shell_status_strip(
            state=brief["state"],
            headline=brief["headline"],
            detail=brief.get("detail") or f"{int(days)}-day window",
        )
    load_col, _ = st.columns([1.1, 4.0])
    with load_col:
        return bool(
            st.button(
                "Load Snapshot",
                key="executive_landing_load",
                help=button_help or None,
                type="primary",
                width="stretch",
            )
        )

def _render_snapshot_prompt(workflow: str, summary: dict, days: int) -> bool:
    st.info(
        f"{workflow} is showing fast summary facts. Load Snapshot only when you need "
        "alert, action, source-health, or export detail for the selected scope."
    )
    return _render_executive_action_brief(summary, int(days), show_strip=False)

def _render_executive_next_clicks() -> None:
    cols = st.columns(5)
    with cols[0]:
        _nav_button(
            "Active Alerts",
            "Alert Center",
            state_updates={"alert_center_active_view": "Active Alerts"},
        )
    with cols[1]:
        _nav_button("Open Cost", "Cost & Contract", workflow_key="cost_contract_workflow", workflow="Cost Overview")
    with cols[2]:
        _nav_button(
            "Open DBA Cockpit",
            "DBA Control Room",
            state_updates={"dba_control_room_active_view": "Morning Cockpit"},
        )
    with cols[3]:
        _nav_button(
            "Open Workload",
            "Workload Operations",
            workflow_key="workload_operations_workflow",
            workflow="Workload Overview",
        )
    with cols[4]:
        _nav_button(
            "Open Security",
            "Security Monitoring",
            workflow_key="security_posture_workflow",
            workflow="Security Overview",
            state_updates={"security_posture_view": "Security Overview"},
        )

def _render_executive_overview(
    summary: dict,
    *,
    company: str,
    environment: str,
    days: int,
    credit_price: float,
    board: pd.DataFrame,
    board_payload: dict,
    snapshot: dict | None,
) -> bool:
    st.markdown("**Executive Overview**")
    render_shell_status_strip(
        state=str(summary.get("state") or "Review"),
        headline="Environment status, movement, and next actions.",
        detail=(
            "Fast summary facts only; open a workflow or load the snapshot when leadership needs more context."
        ),
    )
    render_refresh_contract(
        board_payload,
        source="Executive summary facts",
        target_minutes=60,
        refresh_method="Scheduled data refresh",
        live_fallback="On demand",
    )
    st.markdown("**Snowflake Observability Wall**")
    current_spend = safe_float(
        summary.get("current_spend_usd"),
        credits_to_dollars(safe_float(summary.get("current_credits")), credit_price),
    )
    failed_queries = safe_int(summary.get("failed_queries"))
    failed_tasks = safe_int(summary.get("failed_tasks"))
    p95_runtime = safe_float(summary.get("p95_runtime_sec"))
    spill_gb = safe_float(summary.get("spill_gb"))
    biggest_workload = (
        f"{failed_queries:,} failed query(s), {failed_tasks:,} failed task(s)"
        if failed_queries or failed_tasks
        else f"P95 {_format_seconds(p95_runtime)} / spill {_format_gb(spill_gb)}"
    )
    security_signal = (
        f"{safe_int(summary.get('critical_high_alerts')):,} Critical/High alert(s)"
        if safe_int(summary.get("critical_high_alerts"))
        else "No major signal in summary"
    )
    render_shell_kpi_row((
        ("Health", str(summary.get("state") or _platform_score_state(summary.get("score", 0)))),
        ("Major Issues", f"{safe_int(summary.get('critical_high_alerts')):,}"),
        ("Cost Movement", _format_delta_credits(summary, credit_price=credit_price)),
        ("Security Risk", security_signal),
    ))
    detail_open = bool(st.session_state.get("executive_landing_summary_detail_open"))
    if not isinstance(snapshot, dict):
        detail_col, _ = st.columns([1.15, 4.0])
        with detail_col:
            if st.button(
                "Show Summary Detail",
                key="executive_landing_show_summary_detail",
                width="stretch",
            ):
                st.session_state["executive_landing_summary_detail_open"] = True
                detail_open = True

    if detail_open or isinstance(snapshot, dict):
        render_shell_kpi_row((
            ("Spend", _money(current_spend)),
            ("Workload Risk", biggest_workload),
            ("Open Actions", f"{safe_int(summary.get('open_actions')):,}"),
            ("Freshness", "Loaded" if isinstance(board, pd.DataFrame) and not board.empty else "On demand"),
        ))

        render_priority_dataframe(
            _decision_rows(summary).head(5),
            title="Executive decisions to make first",
            priority_columns=["PRIORITY", "DECISION_AREA", "SIGNAL", "NEXT_ACTION", "WORKFLOW"],
            sort_by=["PRIORITY"],
            ascending=True,
            raw_label="All executive decision rows",
            height=230,
            max_rows=5,
        )
    shortcuts_open = bool(st.session_state.get("executive_landing_workflow_shortcuts_open"))
    if not shortcuts_open:
        shortcut_col, _ = st.columns([1.25, 3.9])
        with shortcut_col:
            if st.button(
                "Show Workflow Shortcuts",
                key="executive_landing_show_workflow_shortcuts",
                width="stretch",
            ):
                st.session_state["executive_landing_workflow_shortcuts_open"] = True
                shortcuts_open = True
        if not shortcuts_open:
            st.caption("Workflow shortcuts stay collapsed during first paint.")
    if shortcuts_open:
        _render_executive_next_clicks()

    if isinstance(snapshot, dict):
        _render_loaded_executive_alert_context()
        alerts = snapshot.get("alerts", pd.DataFrame())
        if isinstance(alerts, pd.DataFrame) and not alerts.empty:
            render_priority_dataframe(
                alerts,
                title="Major alerts in the loaded executive snapshot",
                priority_columns=[
                    "SEVERITY", "STATUS", "CATEGORY", "ALERT_TYPE",
                    "ENTITY_NAME", "OWNER", "SLA_STATE", "SUGGESTED_ACTION",
                ],
                sort_by=["SEVERITY", "ALERT_TS"],
                ascending=[True, False],
                raw_label="All loaded executive alerts",
                max_rows=5,
                height=240,
            )
        return False
    return _render_snapshot_prompt(EXECUTIVE_OVERVIEW_WORKFLOW, summary, days)

def render_executive_overview(*, summary: dict, company: str, environment: str, days: int, credit_price: float, board: pd.DataFrame, board_payload: dict, snapshot: dict | None, source_health: pd.DataFrame | None = None) -> bool:
    return _render_executive_overview(summary, company=company, environment=environment, days=int(days), credit_price=credit_price, board=board, board_payload=board_payload, snapshot=snapshot)


__all__ = ['_render_executive_action_brief', '_render_snapshot_prompt', '_render_executive_next_clicks', '_render_executive_overview', 'render_executive_overview']
