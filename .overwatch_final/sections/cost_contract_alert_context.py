# sections/cost_contract_alert_context.py - Loaded Cost & Cortex alert context panel.
from __future__ import annotations

import streamlit as st

from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.navigation import apply_section_workflow_navigation
from sections.shell_helpers import render_shell_snapshot
from utils.section_guidance import defer_source_note


pd = lazy_pandas()

build_cost_cortex_alert_drilldown = _lazy_util("build_cost_cortex_alert_drilldown")
build_loaded_section_alert_signal_board = _lazy_util("build_loaded_section_alert_signal_board")
render_priority_dataframe = _lazy_util("render_priority_dataframe")


def _render_loaded_cost_alert_context() -> None:
    board = build_loaded_section_alert_signal_board(st.session_state, section="Cost & Contract", limit=8)
    if board.empty:
        return
    alert_data = st.session_state.get("alert_center_data", {}) if isinstance(st.session_state.get("alert_center_data"), dict) else {}
    drilldown = build_cost_cortex_alert_drilldown(
        alert_data.get("alerts", pd.DataFrame()),
        alert_data.get("action_queue", pd.DataFrame()),
        limit=8,
    )
    focus = board.get("SECTION_FOCUS", pd.Series(dtype=str)).fillna("").astype(str)
    severity = board.get("SEVERITY", pd.Series(dtype=str)).fillna("").astype(str)
    sla = board.get("SLA_STATE", pd.Series(dtype=str)).fillna("").astype(str)
    st.markdown("**Loaded Cost and Cortex Alerts**")
    render_shell_snapshot((
        ("Signals", f"{len(board):,}"),
        ("Cortex / Spend", f"{int(focus.isin(['Cortex spend', 'Spend spike', 'Cost movement']).sum()):,}"),
        ("Critical / High", f"{int(severity.isin(['Critical', 'High']).sum()):,}"),
        ("Breached", f"{int(sla.isin(['Breached', 'Overdue']).sum()):,}"),
    ))
    render_priority_dataframe(
        board,
        title="Loaded cost and Cortex alert context",
        priority_columns=[
            "SECTION_FOCUS", "SEVERITY", "SLA_STATE", "CATEGORY", "SIGNAL",
            "ENTITY", "OWNER", "FIRST_RESPONSE", "RECOMMENDED_ACTION",
            "IMPACT_ESTIMATE", "OPEN_PATH", "DRILLDOWN_HINT",
            "AUTOMATION_READINESS", "QUEUE_STATE", "TICKET_ID",
        ],
        sort_by=["PRIORITY"],
        ascending=True,
        raw_label="All loaded cost/Cortex alert rows",
        height=260,
        max_rows=6,
    )
    if not drilldown.empty:
        render_priority_dataframe(
            drilldown,
            title="Cost and Cortex alert drilldown",
            priority_columns=[
                "FOCUS", "SEVERITY", "ENTITY", "WHY_THIS_FIRED",
                "WHERE_TO_OPEN", "SAFE_ACTION", "AUTOMATION_BOUNDARY",
            ],
            raw_label="All cost and Cortex alert drilldown rows",
            height=260,
            max_rows=6,
        )
    top = board.iloc[0]
    button_cols = st.columns(2)
    with button_cols[0]:
        if st.button("Open Alert Lane", key="cost_alert_open_alert_lane", width="stretch"):
            apply_section_workflow_navigation(
                "Alert Center",
                alert_center_view=str(top.get("ALERT_CENTER_VIEW") or "Cost Alerts"),
            )
            st.rerun()
    with button_cols[1]:
        if st.button("Open Cost Drilldown", key="cost_alert_open_cost_drilldown", width="stretch"):
            apply_section_workflow_navigation(
                str(top.get("DESTINATION_SECTION") or "Cost & Contract"),
                workflow=str(top.get("DESTINATION_WORKFLOW") or "Cost Explorer"),
            )
            st.rerun()
    defer_source_note("Loaded Cost and Cortex Alerts reuse Alert Center data and do not run a separate Snowflake query.")
