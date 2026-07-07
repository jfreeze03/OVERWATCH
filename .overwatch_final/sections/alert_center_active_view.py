"""Active Alerts pane renderer."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from sections.alert_center_boards import (
    _alert_next_incident_packet,
    _alert_operator_workflow_rows,
)
from sections.shell_helpers import render_shell_snapshot, render_shell_status_strip
from utils.explicit_load import render_export_controls
from utils.primitives import safe_int
from utils.workflows import render_priority_dataframe


def _download_csv(df: pd.DataFrame, file_name: str) -> None:
    render_export_controls(df, file_name, label="Export CSV")


def _metric_snapshot_value(metric_lookup: dict[str, object], metric_name: str) -> str:
    row = metric_lookup.get(metric_name, {})
    value = row.get("VALUE", 0) if hasattr(row, "get") else 0
    return f"{safe_int(value):,}"


def render_active_alerts_pane(
    alerts: pd.DataFrame,
    queue: pd.DataFrame,
    delivery_log: pd.DataFrame,
    rules: pd.DataFrame,
) -> None:
    from utils.alert_boards import (
        build_alert_command_center_summary,
        build_alert_incident_action_board,
        build_alert_owner_workload_board,
    )

    st.subheader("Active Alerts")
    summary = build_alert_command_center_summary(alerts)
    metrics = summary.get("metrics", pd.DataFrame())
    if isinstance(metrics, pd.DataFrame) and not metrics.empty:
        metric_lookup = {str(row["METRIC"]): row for _, row in metrics.iterrows()}
        render_shell_snapshot((
            ("Open Critical", _metric_snapshot_value(metric_lookup, "Open critical")),
            ("Warnings", _metric_snapshot_value(metric_lookup, "Warning alerts")),
            ("Info", _metric_snapshot_value(metric_lookup, "Info alerts")),
            ("Resolved", _metric_snapshot_value(metric_lookup, "Resolved alerts")),
        ))

    incident_board = build_alert_incident_action_board(alerts, queue, limit=25)
    workflow_rows = _alert_operator_workflow_rows(
        alerts=alerts,
        queue=queue,
        delivery_log=delivery_log,
        incident_board=incident_board,
    )
    if isinstance(incident_board, pd.DataFrame) and not incident_board.empty:
        top_incident = incident_board.iloc[0]
        render_shell_status_strip(
            state=f"{top_incident.get('SEVERITY', 'Review')} / {top_incident.get('SLA_STATE', 'On Track')}",
            headline=f"Work priority 1: {top_incident.get('SIGNAL', 'Alert')} on {top_incident.get('ENTITY', 'Snowflake account')}",
            detail=str(top_incident.get("FIRST_RESPONSE") or top_incident.get("RECOMMENDED_ACTION") or "Acknowledge, route, and capture evidence."),
        )
        packet = _alert_next_incident_packet(incident_board)
        if not packet.empty:
            render_priority_dataframe(
                packet,
                title="Next incident packet",
                priority_columns=["CHECKPOINT", "STATE", "DETAIL", "NEXT_ACTION"],
                raw_label="All next incident packet fields",
                height=240,
                max_rows=5,
            )
        active_queue = incident_board.copy()
        active_queue["WHAT_HAPPENED"] = active_queue.get("SIGNAL", pd.Series(index=active_queue.index, dtype=str)).fillna("Alert").astype(str)
        active_queue["WHY_CARE"] = active_queue.get("BUSINESS_IMPACT", pd.Series(index=active_queue.index, dtype=str)).fillna("Impact needs review.").astype(str)
        active_queue["ACKNOWLEDGE"] = "Use Alert History > Update alert lifecycle"
        active_queue["INVESTIGATE"] = (
            active_queue.get("DESTINATION_SECTION", pd.Series("Alert Center", index=active_queue.index)).fillna("Alert Center").astype(str)
            + " > "
            + active_queue.get("DESTINATION_WORKFLOW", pd.Series("Active Alerts", index=active_queue.index)).fillna("Active Alerts").astype(str)
        )
        render_priority_dataframe(
            active_queue,
            title="Active alert triage queue",
            priority_columns=[
                "PRIORITY", "SEVERITY", "SLA_STATE", "CATEGORY",
                "WHAT_HAPPENED", "ENTITY", "OWNER", "WHY_CARE",
                "RECOMMENDED_ACTION", "ACKNOWLEDGE", "INVESTIGATE",
            ],
            sort_by=["PRIORITY"],
            ascending=True,
            raw_label="All active incident rows",
            height=420,
        )
        _download_csv(incident_board, "overwatch_alert_incident_action_board.csv")
    else:
        st.success("No active alert rows found in the loaded scope.")

    with st.expander("View Details", expanded=False):
        if isinstance(metrics, pd.DataFrame) and not metrics.empty:
            render_priority_dataframe(
                metrics,
                title="Operating metrics",
                priority_columns=["METRIC", "VALUE", "STATE", "DETAIL"],
                raw_label="All alert operating metrics",
                height=220,
            )
        render_priority_dataframe(
            workflow_rows,
            title="Operator workflow",
            priority_columns=["STEP", "STATE", "COUNT", "WHAT_TO_CHECK", "NEXT_ACTION", "OPERATOR_VIEW"],
            raw_label="All alert operator workflow steps",
            height=260,
            max_rows=6,
        )

        category_board = summary.get("category_board", pd.DataFrame())
        if isinstance(category_board, pd.DataFrame) and not category_board.empty:
            render_priority_dataframe(
                category_board,
                title="Business-impact categories",
                priority_columns=[
                    "CATEGORY", "OPEN", "CRITICAL_HIGH", "RESOLVED",
                    "SEVERITY_SCORE", "BUSINESS_IMPACT",
                    "RECOMMENDED_ACTION",
                ],
                sort_by=["SEVERITY_SCORE", "OPEN"],
                ascending=[False, False],
                raw_label="All alert categories",
                height=300,
            )
        else:
            st.success("No open category risk rows found in the loaded alert scope.")

        recurring = summary.get("recurring", pd.DataFrame())
        if isinstance(recurring, pd.DataFrame) and not recurring.empty:
            render_priority_dataframe(
                recurring,
                title="Top recurring issues",
                priority_columns=["CATEGORY", "SIGNAL", "ENTITY", "ALERTS", "SEVERITY", "OWNER", "RECOMMENDED_ACTION"],
                sort_by=["ALERTS", "SEVERITY"],
                ascending=[False, True],
                raw_label="All recurring alert groups",
                height=260,
            )

        owner_board = build_alert_owner_workload_board(alerts, queue)
        if isinstance(owner_board, pd.DataFrame) and not owner_board.empty:
            render_priority_dataframe(
                owner_board,
                title="Route workload and telemetry gaps",
                priority_columns=[
                    "OWNER", "OPEN_ALERTS", "CRITICAL_HIGH", "SLA_BREACHED",
                    "TICKETS_ATTACHED", "TOP_CATEGORY", "NEXT_ACTION", "REVIEW_STATUS",
                ],
                sort_by=["SLA_BREACHED", "CRITICAL_HIGH", "OPEN_ALERTS"],
                ascending=[False, False, False],
                raw_label="All route workload rows",
                height=260,
            )

        queue_open = 0
        if not queue.empty and "STATUS" in queue.columns:
            queue_open = int((~queue["STATUS"].fillna("New").astype(str).str.title().isin(["Fixed", "Ignored"])).sum())
        digest_rows = [
            {
                "CONTROL": "Action queue handoff",
                "STATE": "Ready" if queue_open else "No Open Queue",
                "EVIDENCE": f"{queue_open:,} open action queue row(s).",
                "NEXT_ACTION": "Route confirmed alerts into action rows with ticket/reference and telemetry state.",
                "OWNER": "DBA Review",
            },
            {
                "CONTROL": "Rule coverage",
                "STATE": "Ready" if not rules.empty else "Fallback",
                "EVIDENCE": f"{len(rules):,} alert rule row(s) available.",
                "NEXT_ACTION": "Use loaded rule telemetry before treating severity, SLA, route, or runbook changes as authoritative.",
                "OWNER": "Platform DBA",
            },
            {
                "CONTROL": "Notification telemetry",
                "STATE": "Ready" if not delivery_log.empty else "Review",
                "EVIDENCE": f"{len(delivery_log):,} delivery log row(s) loaded.",
                "NEXT_ACTION": "Log alert digests until Snowflake notification integration is live.",
                "OWNER": "DBA Review",
            },
        ]
        render_priority_dataframe(
            pd.DataFrame(digest_rows),
            title="Operating controls",
            priority_columns=["STATE", "CONTROL", "EVIDENCE", "NEXT_ACTION", "OWNER"],
            raw_label="All alert monitoring controls",
            height=220,
        )
        _render_loaded_advisor_alert_candidates()


def _render_loaded_advisor_alert_candidates() -> None:
    from utils import build_loaded_advisor_signal_board

    advisor_rows = build_loaded_advisor_signal_board(st.session_state)
    if advisor_rows.empty:
        return
    view = advisor_rows.copy()
    if "SEVERITY" in view.columns:
        severity = view["SEVERITY"].fillna("").astype(str).str.title()
        view = view[severity.isin(["Critical", "High", "Medium"])]
    if view.empty:
        return
    high = int(view["SEVERITY"].astype(str).str.title().isin(["Critical", "High"]).sum())
    savings = 0.0
    risk = 0.0
    if "EST_MONTHLY_SAVINGS_USD" in view.columns:
        savings = float(pd.to_numeric(view["EST_MONTHLY_SAVINGS_USD"], errors="coerce").fillna(0).sum())
    if "VALUE_AT_RISK_USD" in view.columns:
        risk = float(pd.to_numeric(view["VALUE_AT_RISK_USD"], errors="coerce").fillna(0).sum())
    st.markdown("**Loaded Advisor Alert Candidates**")
    render_shell_snapshot((
        ("Candidates", f"{len(view):,}"),
        ("Critical / High", f"{high:,}"),
        ("Est. Savings / Mo", f"${savings:,.0f}"),
        ("Value At Risk", f"${risk:,.0f}"),
    ))
    render_priority_dataframe(
        view,
        title="Advisor signals that may need alert routing",
        priority_columns=[
            "SOURCE_SURFACE", "SEVERITY", "SIGNAL", "ENTITY",
            "ROUTE", "NEXT_ACTION", "TELEMETRY_BASIS",
            "EST_MONTHLY_SAVINGS_USD", "VALUE_AT_RISK_USD",
        ],
        sort_by=["PRIORITY_RANK", "VALUE_AT_RISK_USD", "EST_MONTHLY_SAVINGS_USD"],
        ascending=[True, False, False],
        raw_label="All advisor alert candidate rows",
        height=300,
        max_rows=12,
    )
