"""Alert Center history pane renderer."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import streamlit as st

from sections.alert_center_boards import _alert_lifecycle_board
from sections.shell_helpers import render_shell_snapshot
from utils.explicit_load import render_export_controls
from utils.workflows import render_priority_dataframe


def render_alert_history_pane(
    alerts: pd.DataFrame,
    queue: pd.DataFrame,
    *,
    action_session_factory: Callable[[str], object | None],
    alert_actor: Callable[[], str],
    format_error: Callable[[Exception], str],
) -> None:
    st.subheader("Alert History")
    if alerts.empty:
        st.info("No alert history rows found for this scope.")
        return

    lifecycle = _alert_lifecycle_board(alerts, queue)
    if not lifecycle.empty:
        render_shell_snapshot((
            ("Lifecycle Rows", f"{len(lifecycle):,}"),
            ("Escalate Now", f"{int(lifecycle['LIFECYCLE_STATE'].eq('Escalate now').sum()):,}"),
            ("Needs Route", f"{int(lifecycle['LIFECYCLE_STATE'].eq('Assign route').sum()):,}"),
            ("Not Queued", f"{int(lifecycle['ACTION_QUEUE_STATE'].eq('Not queued').sum()):,}"),
        ))
        closed_mask = lifecycle["STATUS"].fillna("").astype(str).str.upper().isin({"FIXED", "RESOLVED", "CLOSED", "IGNORED"})
        acknowledged_mask = lifecycle["DELIVERY_STATUS"].fillna("").astype(str).str.upper().str.contains("ACK|LOGGED|ESCALATED", regex=True)
        render_shell_snapshot((
            ("Acknowledged", f"{int(acknowledged_mask.sum()):,}"),
            ("Closed", f"{int(closed_mask.sum()):,}"),
            ("Recurring Groups", f"{int(lifecycle.groupby(['CATEGORY', 'ALERT_TYPE', 'ENTITY_NAME'], dropna=False).size().gt(1).sum()):,}"),
            ("Export", "Ready"),
        ))
        render_priority_dataframe(
            lifecycle,
            title="Alert lifecycle summary",
            priority_columns=[
                "LIFECYCLE_STATE", "SLA_STATE", "SEVERITY", "STATUS",
                "CATEGORY", "ALERT_TYPE", "ENTITY_NAME", "OWNER",
                "ESCALATION_TARGET", "DELIVERY_STATUS", "ACTION_QUEUE_STATE",
                "NEXT_ACTION",
            ],
            sort_by=["LIFECYCLE_STATE", "SEVERITY", "ALERT_TS"],
            ascending=[True, True, False],
            raw_label="All alert lifecycle rows",
            height=300,
        )
        recurring_history = (
            lifecycle
            .groupby(["CATEGORY", "ALERT_TYPE", "ENTITY_NAME", "OWNER"], dropna=False)
            .agg(ALERTS=("ALERT_ID", "count"), LATEST_ALERT=("ALERT_TS", "max"))
            .reset_index()
            .sort_values(["ALERTS", "LATEST_ALERT"], ascending=[False, False])
        )
        recurring_history = recurring_history[recurring_history["ALERTS"] > 1]
        if not recurring_history.empty:
            render_priority_dataframe(
                recurring_history,
                title="Recurring alert groups",
                priority_columns=["ALERTS", "CATEGORY", "ALERT_TYPE", "ENTITY_NAME", "OWNER", "LATEST_ALERT"],
                sort_by=["ALERTS", "LATEST_ALERT"],
                ascending=[False, False],
                raw_label="All recurring alert groups",
                height=240,
                max_rows=10,
            )
        if "ALERT_TS" in lifecycle.columns:
            history_trend = lifecycle.copy()
            history_trend["_ALERT_DATE"] = pd.to_datetime(history_trend["ALERT_TS"], errors="coerce").dt.date
            history_trend = (
                history_trend.dropna(subset=["_ALERT_DATE"])
                .groupby(["_ALERT_DATE", "STATUS"], dropna=False)
                .size()
                .reset_index(name="ALERTS")
                .sort_values(["_ALERT_DATE", "STATUS"], ascending=[False, True])
            )
            if not history_trend.empty:
                render_priority_dataframe(
                    history_trend,
                    title="Alert trend over time",
                    priority_columns=["_ALERT_DATE", "STATUS", "ALERTS"],
                    raw_label="All alert trend rows",
                    height=220,
                    max_rows=12,
                )
    render_priority_dataframe(
        alerts,
        title="Alert history",
        priority_columns=[
            "ALERT_TS", "ALERT_AGE_HOURS", "SLA_TARGET_HOURS", "SLA_STATE",
            "SEVERITY", "STATUS", "CATEGORY", "ALERT_TYPE",
            "ENTITY_NAME", "ENVIRONMENT", "MESSAGE", "SUGGESTED_ACTION",
            "OWNER", "ESCALATION_TARGET", "ESCALATED_AT", "ESCALATION_ACK_AT",
            "DELIVERY_STATUS", "LAST_DELIVERY_AT",
        ],
        sort_by=["TRIAGE_PRIORITY", "ALERT_TS"],
        ascending=[True, False],
        raw_label="All alert history rows",
        height=420,
    )
    render_export_controls(alerts, "overwatch_alert_history.csv", label="Export CSV")

    alert_ids = alerts["ALERT_ID"].dropna().astype(str).tolist() if "ALERT_ID" in alerts.columns else []
    if not alert_ids:
        return

    from utils.alert_command_center import (
        build_alert_acknowledgement_insert_sql,
        build_alert_remediation_log_insert_sql,
    )
    from utils.alert_lifecycle import (
        acknowledge_alert_escalation,
        update_alert_status,
    )
    from utils.alert_status import ALERT_STATUS_CHOICES

    with st.expander("Update alert lifecycle", expanded=False):
        with st.form("alert_center_status_update"):
            c_status_1, c_status_2 = st.columns([1, 1])
            with c_status_1:
                selected_alert = st.selectbox("Alert ID", alert_ids, key="alert_center_status_alert_id")
            with c_status_2:
                next_status = st.selectbox("New status", list(ALERT_STATUS_CHOICES), key="alert_center_next_status")
            reason = st.text_area(
                "Reason / status",
                key="alert_center_status_reason",
                placeholder="Ticket, route confirmation, remediation status, or reason for ignore.",
            )
            submitted = st.form_submit_button("Update Alert Status")
        if submitted:
            if not reason.strip():
                st.warning("A reason or status note is required before changing alert status.")
            else:
                try:
                    # SESSION_OPEN_ADMIN_OK boundary=admin reason=post_click_session budget=advanced_diagnostics owner=platform
                    session = action_session_factory("update alert status")
                    if session is None:
                        return
                    update_alert_status(
                        session,
                        selected_alert,
                        next_status,
                        reason=reason,
                        actor=alert_actor(),
                    )
                    st.success(f"Alert {selected_alert} moved to {next_status}. Reload the Alert Center to refresh the queue.")
                    st.session_state.pop("alert_center_data", None)
                except Exception as exc:
                    st.error(f"Could not update alert status: {format_error(exc)}")
    with st.expander("Acknowledge escalation", expanded=False):
        with st.form("alert_center_escalation_ack"):
            ack_alert = st.selectbox("Escalated alert ID", alert_ids, key="alert_center_ack_alert_id")
            ack_note = st.text_area(
                "Acknowledgment note",
                key="alert_center_ack_note",
                placeholder="Route accepted, ticket opened, escalation recipient confirmed, or next checkpoint.",
            )
            submitted_ack = st.form_submit_button("Acknowledge Escalation")
        if submitted_ack:
            if len(ack_note.strip()) < 10:
                st.warning("Acknowledgment note is required for escalation audit.")
            else:
                try:
                    # SESSION_OPEN_ADMIN_OK boundary=admin reason=post_click_session budget=advanced_diagnostics owner=platform
                    session = action_session_factory("acknowledge alert escalation")
                    if session is None:
                        return
                    acknowledge_alert_escalation(
                        session,
                        ack_alert,
                        actor=alert_actor(),
                        note=ack_note,
                    )
                    st.success(f"Escalation acknowledged for alert {ack_alert}. Reload the Alert Center to refresh.")
                    st.session_state.pop("alert_center_data", None)
                except Exception as exc:
                    st.error(f"Could not acknowledge escalation: {format_error(exc)}")
    with st.expander("Lifecycle audit preview", expanded=False):
        audit_alert = st.selectbox("Audit event ID", alert_ids, key="alert_center_audit_event_id")
        audit_status = st.selectbox(
            "Lifecycle status",
            list(ALERT_STATUS_CHOICES),
            key="alert_center_audit_status",
        )
        audit_owner = st.text_input(
            "Route",
            key="alert_center_audit_owner",
            placeholder="DBA / Cost owner / Security route",
        )
        audit_note = st.text_area(
            "Audit note",
            key="alert_center_audit_note",
            placeholder="Ticket, investigation result, route assignment, or remediation status.",
        )
        if len(str(audit_note or "").strip()) >= 5:
            audit_sql_parts = [
                build_alert_acknowledgement_insert_sql(
                    event_id=audit_alert,
                    alert_key=str(audit_alert),
                    note=audit_note,
                    actor=alert_actor(),
                    owner=audit_owner,
                    status_after_ack=audit_status,
                    next_checkpoint_hours=8,
                ),
                build_alert_remediation_log_insert_sql(
                    event_id=audit_alert,
                    alert_key=str(audit_alert),
                    remediation_mode="RECOMMEND",
                    action_type=f"Lifecycle status: {audit_status}",
                    before_state="Alert reviewed from Alert Center.",
                    after_state=str(audit_note),
                    execution_status="RECORDED",
                    rollback_guidance="Reopen the alert or add a follow-up acknowledgement if the condition returns.",
                    actor=alert_actor(),
                ),
            ]
            st.caption("Lifecycle audit will record the selected status, note, checkpoint, and remediation log.")
            if st.button(
                "Record Lifecycle Audit",
                key="alert_center_record_lifecycle_audit",
                help="Records the acknowledgement and remediation log. No remediation action is executed.",
                width="stretch",
            ):
                try:
                    # SESSION_OPEN_ADMIN_OK boundary=admin reason=post_click_session budget=advanced_diagnostics owner=platform
                    session = action_session_factory("record alert lifecycle audit")
                    if session is None:
                        return
                    for statement in audit_sql_parts:
                        # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics owner=platform
                        session.sql(statement).collect()
                    st.success(f"Lifecycle audit recorded for alert {audit_alert}. Reload the Alert Center to refresh.")
                    st.session_state.pop("alert_center_data", None)
                except Exception as exc:
                    st.error(f"Could not record lifecycle audit: {format_error(exc)}")
        else:
            st.caption("Enter an audit note to record acknowledgement and remediation-log status.")
