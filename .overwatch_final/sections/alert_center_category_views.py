"""Alert Center category pane renderers."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from sections.alert_center_boards import _alert_domain_next_move_rows
from sections.navigation import apply_section_workflow_navigation
from sections.shell_helpers import render_shell_snapshot, render_shell_status_strip
from utils.alert_boards import build_section_alert_signal_board
from utils.explicit_load import render_export_controls
from utils.workflows import render_priority_dataframe


ALERT_CATEGORY_TOKEN_PATTERNS = {
    "Cost Alerts": "COST|SPEND|CORTEX|WAREHOUSE|OPTIMIZATION|CONTRACT|CHARGEBACK",
    "Reliability Alerts": "QUERY|TASK|PIPELINE|PROCEDURE|COPY|LOAD|PERFORMANCE|WAREHOUSE",
    "Security Alerts": "SECURITY|LOGIN|GRANT|PRIVILEGE|SHARE|ACCESS|EXPORT",
}


def alert_category_token_pattern(active_view: str) -> str:
    return ALERT_CATEGORY_TOKEN_PATTERNS.get(active_view, "")


def _download_csv(df: pd.DataFrame, file_name: str) -> None:
    render_export_controls(df, file_name, label="Export CSV")


def render_alert_category_pane(
    active_view: str,
    alerts: pd.DataFrame,
    queue: pd.DataFrame,
    rules: pd.DataFrame,
) -> None:
    title_map = {
        "Cost Alerts": "Cost, Cortex, and Behavior Alerts",
        "Reliability Alerts": "Reliability Alerts",
        "Security Alerts": "Security Alerts",
    }
    st.subheader(title_map.get(active_view, f"{active_view} Alerts"))
    board = build_section_alert_signal_board(alerts, queue, section=active_view, limit=30)
    if board.empty:
        st.success(f"No loaded {active_view.lower()} alert rows are open in this scope.")
    else:
        severity = board.get("SEVERITY", pd.Series(dtype=str)).fillna("").astype(str)
        sla = board.get("SLA_STATE", pd.Series(dtype=str)).fillna("").astype(str)
        focus = board.get("SECTION_FOCUS", pd.Series(dtype=str)).fillna("").astype(str)
        render_shell_snapshot((
            ("Open Signals", f"{len(board):,}"),
            ("Critical / High", f"{int(severity.isin(['Critical', 'High']).sum()):,}"),
            ("Breached SLA", f"{int(sla.isin(['Breached', 'Overdue']).sum()):,}"),
            ("Spend / Cortex", f"{int(focus.isin(['Cortex spend', 'Spend spike', 'Cost movement']).sum()):,}"),
        ))
        top = board.iloc[0]
        render_shell_status_strip(
            state=str(top.get("SECTION_FOCUS") or "Review"),
            headline=f"First move: {top.get('SIGNAL', 'Alert')} on {top.get('ENTITY', 'Snowflake account')}",
            detail=str(top.get("DRILLDOWN_HINT") or top.get("FIRST_RESPONSE") or "Open the owning workflow and confirm evidence."),
        )
        next_moves = _alert_domain_next_move_rows(board, active_view)
        if not next_moves.empty:
            render_priority_dataframe(
                next_moves,
                title=f"{active_view} first response path",
                priority_columns=["MOVE", "STATE", "DETAIL", "NEXT_ACTION"],
                raw_label=f"All {active_view} first response steps",
                height=220,
                max_rows=4,
            )
        render_priority_dataframe(
            board,
            title=f"{active_view} alert workbench",
            priority_columns=[
                "SECTION_FOCUS", "PRIORITY", "SEVERITY", "SLA_STATE", "CATEGORY",
                "SIGNAL", "ENTITY", "OWNER", "ROUTE", "FIRST_RESPONSE",
                "RECOMMENDED_ACTION", "IMPACT_ESTIMATE", "SOURCE_FRESHNESS",
                "OPEN_PATH", "DRILLDOWN_HINT", "AUTOMATION_READINESS",
                "REMEDIATION_MODE", "QUEUE_STATE", "TICKET_ID",
            ],
            sort_by=["PRIORITY"],
            ascending=True,
            raw_label=f"All {active_view} alert rows",
            height=420,
            max_rows=15,
        )
        _download_csv(board, f"overwatch_{active_view.lower().replace(' ', '_')}_alerts.csv")
        cols = st.columns(2)
        with cols[0]:
            if st.button("Open Owning Section", key=f"alert_domain_open_owner_{active_view}", width="stretch"):
                apply_section_workflow_navigation(
                    str(top.get("DESTINATION_SECTION") or "Alert Center"),
                    workflow=str(top.get("DESTINATION_WORKFLOW") or ""),
                    alert_center_view=str(top.get("ALERT_CENTER_VIEW") or active_view),
                )
                st.rerun()
        with cols[1]:
            if st.button("Open Active Alerts", key=f"alert_domain_open_command_{active_view}", width="stretch"):
                apply_section_workflow_navigation("Alert Center", alert_center_view="Active Alerts")
                st.rerun()

    if rules is not None and not rules.empty:
        rule_text = pd.Series([""] * len(rules), index=rules.index, dtype=str)
        for column in ["CATEGORY", "ALERT_TYPE", "RULE_ID", "ROUTE", "RUNBOOK"]:
            if column in rules.columns:
                rule_text = rule_text + " " + rules[column].fillna("").astype(str).str.upper()
        token_pattern = alert_category_token_pattern(active_view)
        visible_rules = rules[rule_text.str.contains(token_pattern, regex=True)] if token_pattern else pd.DataFrame()
        if not visible_rules.empty:
            render_priority_dataframe(
                visible_rules,
                title=f"{active_view} rule coverage",
                priority_columns=[
                    "RULE_ID", "CATEGORY", "ALERT_TYPE", "DEFAULT_SEVERITY",
                    "SLA_HOURS", "OWNER", "ROUTE", "RUNBOOK", "IS_ACTIVE",
                ],
                raw_label=f"All {active_view} alert rules",
                height=260,
                max_rows=10,
            )


def render_cost_alerts_pane(alerts: pd.DataFrame, queue: pd.DataFrame, rules: pd.DataFrame) -> None:
    render_alert_category_pane("Cost Alerts", alerts, queue, rules)


def render_reliability_alerts_pane(alerts: pd.DataFrame, queue: pd.DataFrame, rules: pd.DataFrame) -> None:
    render_alert_category_pane("Reliability Alerts", alerts, queue, rules)


def render_security_alerts_pane(alerts: pd.DataFrame, queue: pd.DataFrame, rules: pd.DataFrame) -> None:
    render_alert_category_pane("Security Alerts", alerts, queue, rules)
