# sections/security_posture_alerts_view.py - Security alert context renderer
from __future__ import annotations

import streamlit as st

from sections.base import lazy_util as _lazy_util
from sections.navigation import apply_section_workflow_navigation


build_loaded_section_alert_signal_board = _lazy_util("build_loaded_section_alert_signal_board")
render_priority_dataframe = _lazy_util("render_priority_dataframe")


def _render_loaded_security_alert_context() -> None:
    board = build_loaded_section_alert_signal_board(st.session_state, section="Security Monitoring", limit=8)
    if board.empty:
        return
    st.markdown("**Loaded Security Alerts**")
    render_priority_dataframe(
        board,
        title="Loaded security alert context",
        priority_columns=[
            "SECTION_FOCUS", "SEVERITY", "SLA_STATE", "CATEGORY", "SIGNAL",
            "ENTITY", "OWNER", "FIRST_RESPONSE", "RECOMMENDED_ACTION",
            "IMPACT_ESTIMATE", "OPEN_PATH", "DRILLDOWN_HINT",
            "AUTOMATION_READINESS", "QUEUE_STATE", "TICKET_ID",
        ],
        sort_by=["PRIORITY"],
        ascending=True,
        raw_label="All loaded security alert rows",
        height=260,
        max_rows=6,
    )
    top = board.iloc[0]
    cols = st.columns(2)
    with cols[0]:
        if st.button("Open Alert Lane", key="security_alert_open_alert_lane", width="stretch"):
            apply_section_workflow_navigation(
                "Alert Center",
                alert_center_view=str(top.get("ALERT_CENTER_VIEW") or "Security"),
            )
            st.rerun()
    with cols[1]:
        if st.button("Open Security Drilldown", key="security_alert_open_drilldown", width="stretch"):
            apply_section_workflow_navigation(
                str(top.get("DESTINATION_SECTION") or "Security Monitoring"),
                workflow=str(top.get("DESTINATION_WORKFLOW") or "Failed Logins"),
            )
            st.rerun()


__all__ = ["_render_loaded_security_alert_context"]
