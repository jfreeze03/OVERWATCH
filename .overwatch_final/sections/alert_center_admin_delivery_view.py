"""Alert Center Delivery & Automation admin renderer."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import streamlit as st

from sections.alert_center_boards import (
    _alert_company_scope_readiness_rows,
    _alert_operations_review_rows,
    _alert_threshold_tuning_rows,
    _open_alert_mask,
)
from sections.alert_center_contracts import ALERT_CENTER_DEFAULT_VIEW, defer_source_note
from utils.explicit_load import render_export_controls
from utils.workflows import render_priority_dataframe


def _default_action_session(action: str):
    from utils import get_session_for_action

    return get_session_for_action(
        action,
        surface="Alert Center",
        offline_note=(
            "Alert Center source summaries remain available without a connection. "
            "Status changes are handled by the DBA team outside this dashboard."
        ),
    )


def _default_alert_actor() -> str:
    return str(st.session_state.get("_overwatch_actor") or "OVERWATCH").strip() or "OVERWATCH"


def _default_format_error(exc: Exception) -> str:
    from utils import format_snowflake_error

    return format_snowflake_error(exc)


def _default_email_target() -> str:
    from config import DEFAULT_ALERT_EMAIL
    from utils.alert_delivery import current_alert_recipient

    return current_alert_recipient(DEFAULT_ALERT_EMAIL)


def _delivery_failed_count(delivery_log: pd.DataFrame) -> int:
    if delivery_log is None or delivery_log.empty or "DELIVERY_STATUS" not in delivery_log.columns:
        return 0
    status = delivery_log["DELIVERY_STATUS"].fillna("").astype(str).str.upper()
    return int(status.str.contains("FAILED|ERROR|BOUNCED", regex=True).sum())


def _delivery_remediation_control_rows(
    *,
    alerts: pd.DataFrame,
    queue: pd.DataFrame,
    delivery_log: pd.DataFrame,
    rules: pd.DataFrame,
    native_registry: pd.DataFrame | None = None,
    remediation_policy: pd.DataFrame | None = None,
    remediation_dry_run: pd.DataFrame | None = None,
) -> pd.DataFrame:
    native_registry = native_registry if isinstance(native_registry, pd.DataFrame) else pd.DataFrame()
    remediation_policy = remediation_policy if isinstance(remediation_policy, pd.DataFrame) else pd.DataFrame()
    remediation_dry_run = remediation_dry_run if isinstance(remediation_dry_run, pd.DataFrame) else pd.DataFrame()
    enabled_native = 0
    candidate_native = 0
    if not native_registry.empty:
        enabled_native = int(native_registry.get("ENABLED_BY_DEFAULT", pd.Series(dtype=bool)).fillna(False).astype(bool).sum())
        candidate_native = int(native_registry.get("STATUS", pd.Series(dtype=str)).fillna("").astype(str).str.upper().eq("CANDIDATE").sum())
    auto_policy = 0
    if not remediation_policy.empty:
        auto_policy = int(remediation_policy.get("AUTO_ELIGIBLE", pd.Series(dtype=bool)).fillna(False).astype(bool).sum())
    failed_delivery = _delivery_failed_count(delivery_log)
    controls = [
        {
            "CONTROL": "Alert inbox",
            "STATE": "Ready",
            "EVIDENCE": f"{len(alerts):,} alert row(s) loaded.",
            "NEXT_ACTION": "Use alert status, acknowledgement, suppression, and action-queue routing from Alert Center.",
            "ROUTE": ALERT_CENTER_DEFAULT_VIEW,
        },
        {
            "CONTROL": "Delivery status",
            "STATE": "Review" if delivery_log.empty or failed_delivery else "Ready",
            "EVIDENCE": f"{len(delivery_log):,} delivery audit row(s) loaded; {failed_delivery:,} failed/bounced/error row(s).",
            "NEXT_ACTION": "Review failed delivery attempts before treating notification status as complete." if failed_delivery else "Log delivery status for open critical/high alerts.",
            "ROUTE": "Delivery & Automation",
        },
        {
            "CONTROL": "Action queue handoff",
            "STATE": "Ready" if not queue.empty else "Review",
            "EVIDENCE": f"{len(queue):,} action queue row(s) loaded.",
            "NEXT_ACTION": "Route open alerts to queue rows and confirm ticket, due date, and closure state.",
            "ROUTE": "Delivery & Automation",
        },
        {
            "CONTROL": "Rule catalog",
            "STATE": "Ready" if not rules.empty else "Fallback",
            "EVIDENCE": f"{len(rules):,} rules loaded.",
            "NEXT_ACTION": "Use rules as monitoring context; do not change thresholds from the alert view.",
            "ROUTE": "Detection Catalog",
        },
        {
            "CONTROL": "Native alert registry",
            "STATE": "Review" if enabled_native else ("Ready" if not native_registry.empty else "Review"),
            "EVIDENCE": (
                f"{len(native_registry):,} native candidate row(s); {enabled_native:,} enabled by default; {candidate_native:,} candidate(s)."
                if not native_registry.empty else "Registry table not loaded or not deployed yet."
            ),
            "NEXT_ACTION": "Review generated CREATE ALERT SQL and enable only after owner, threshold, and warehouse are approved.",
            "ROUTE": "Detection Catalog",
        },
        {
            "CONTROL": "Remediation policy",
            "STATE": "Ready" if not remediation_policy.empty and auto_policy == 0 else "Review",
            "EVIDENCE": (
                f"{len(remediation_policy):,} policy row(s); {auto_policy:,} auto-eligible."
                if not remediation_policy.empty else "Policy table not loaded or not deployed yet."
            ),
            "NEXT_ACTION": "Keep AUTO_ELIGIBLE false until dry-run evidence and rollback checks are proven.",
            "ROUTE": "Delivery & Automation",
        },
        {
            "CONTROL": "Remediation dry-runs",
            "STATE": "Ready" if not remediation_dry_run.empty else "No Rows",
            "EVIDENCE": f"{len(remediation_dry_run):,} recent dry-run row(s) loaded.",
            "NEXT_ACTION": "Use dry-runs to prove before-state, proposed action, blocker, and verification SQL before any future automation.",
            "ROUTE": "Delivery & Automation",
        },
    ]
    return pd.DataFrame(controls)


def _email_delivery_status_frame(
    alerts: pd.DataFrame,
    *,
    email_target: Callable[[], str] | None = None,
) -> pd.DataFrame:
    if alerts is None or alerts.empty:
        return pd.DataFrame()
    target = email_target or _default_email_target
    email_view = alerts.copy()
    if "EMAIL_TARGET" not in email_view.columns:
        email_view["EMAIL_TARGET"] = target()
    email_view["EMAIL_TARGET"] = email_view["EMAIL_TARGET"].replace("", target()).fillna(target())
    return email_view


def _action_queue_routing_preview(alerts: pd.DataFrame, *, company: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    from utils.alert_action_queue import alert_history_to_actions

    routable = alerts[_open_alert_mask(alerts)] if alerts is not None and not alerts.empty else pd.DataFrame()
    actions_preview = pd.DataFrame(alert_history_to_actions(routable, company=company))
    return routable, actions_preview


def _remediation_policy_display_rows(remediation_policy: pd.DataFrame | None) -> pd.DataFrame:
    from utils.alert_native_catalog import build_alert_remediation_policy_seed_rows

    policy_rows = remediation_policy.copy() if isinstance(remediation_policy, pd.DataFrame) and not remediation_policy.empty else pd.DataFrame(build_alert_remediation_policy_seed_rows())
    if not policy_rows.empty and "POLICY_SOURCE" not in policy_rows.columns:
        policy_rows["POLICY_SOURCE"] = "Live policy table" if isinstance(remediation_policy, pd.DataFrame) and not remediation_policy.empty else "Built-in seed policy"
    return policy_rows


def _native_registry_status_rows(native_registry: pd.DataFrame | None) -> pd.DataFrame:
    native_registry = native_registry if isinstance(native_registry, pd.DataFrame) else pd.DataFrame()
    if native_registry.empty:
        return pd.DataFrame()
    return native_registry.copy()


def render_alert_email_delivery_status(
    alerts: pd.DataFrame,
    delivery_log: pd.DataFrame,
    *,
    email_target: Callable[[], str] | None = None,
) -> None:
    st.markdown("**Notification Queue**")
    defer_source_note(
        "Rows are email-ready by default once the Snowflake email integration is enabled."
    )
    email_view = _email_delivery_status_frame(alerts, email_target=email_target)
    if email_view.empty:
        st.info("No email-ready alert rows found.")
    else:
        render_priority_dataframe(
            email_view,
            title="Email-ready alert messages",
            priority_columns=[
                "ALERT_TS", "SEVERITY", "DELIVERY_STATUS", "EMAIL_TARGET",
                "EMAIL_SUBJECT", "ENTITY_NAME", "MESSAGE",
            ],
            sort_by=["ALERT_TS"],
            ascending=False,
            raw_label="All email delivery rows",
            height=320,
        )
        for _, row in email_view.head(5).iterrows():
            with st.expander(str(row.get("EMAIL_SUBJECT") or "OVERWATCH alert email"), expanded=False):
                st.text(str(row.get("EMAIL_BODY") or row.get("MESSAGE") or "No email body captured."))

    st.markdown("**Delivery Audit**")
    if delivery_log.empty:
        st.info("No delivery audit rows loaded for this window.")
    else:
        render_priority_dataframe(
            delivery_log,
            title="Email delivery audit",
            priority_columns=[
                "DELIVERY_TS", "DELIVERY_STATUS", "DELIVERY_TARGET", "ALERT_COUNT",
                "EMAIL_SUBJECT", "DELIVERY_BY", "DELIVERY_NOTES",
            ],
            sort_by=["DELIVERY_TS"],
            ascending=False,
            raw_label="All delivery audit rows",
            height=260,
        )


def render_alert_action_queue_routing(
    alerts: pd.DataFrame,
    queue: pd.DataFrame,
    company: str,
    *,
    action_session_factory: Callable[[str], object | None] | None = None,
    alert_actor: Callable[[], str] | None = None,
    format_error: Callable[[Exception], str] | None = None,
) -> None:
    from utils.alert_action_queue import mark_alerts_routed
    from utils.action_queue import upsert_actions

    action_session_factory = action_session_factory or _default_action_session
    alert_actor = alert_actor or _default_alert_actor
    format_error = format_error or _default_format_error
    st.markdown("**Route Alerts To Action Queue**")
    if alerts.empty:
        st.info("Load alert history before routing alerts to the action queue.")
    else:
        routable, actions_preview = _action_queue_routing_preview(alerts, company=company)
        defer_source_note(f"{len(routable):,} open alert row(s) are eligible for action queue routing.")
        if not actions_preview.empty:
            recovery_count = int((actions_preview.get("Category", pd.Series(dtype=str)) == "Task & Procedure Reliability").sum())
            if recovery_count:
                defer_source_note(f"{recovery_count:,} task/procedure recovery action(s) include recovery SLA and telemetry status fields.")
            render_priority_dataframe(
                actions_preview,
                title="Action queue routing preview",
                priority_columns=[
                    "Severity", "Category", "Entity Type", "Entity", "Owner",
                    "Oncall Primary", "Review Group",
                    "Recovery SLA State", "Recovery SLA Target Hours",
                    "Action",
                ],
                sort_by=["Severity", "Category", "Entity"],
                ascending=[True, True, True],
                raw_label="All routed action fields",
                height=300,
            )
        if st.button("Send Open Alerts To Action Queue", key="alert_center_to_action_queue"):
            try:
                # SESSION_OPEN_ADMIN_OK boundary=admin reason=post_click_session budget=advanced_diagnostics owner=platform
                session = action_session_factory("route alerts to the action queue")
                if session is None:
                    return
                saved = upsert_actions(session, actions_preview.to_dict("records"))
                alert_ids = routable.get("ALERT_ID", pd.Series(dtype=str)).dropna().astype(str).tolist()
                mark_alerts_routed(session, alert_ids, action_count=saved, actor=alert_actor())
                st.success(f"Saved {saved} alert action(s) to the action queue.")
                st.session_state.pop("alert_center_data", None)
            except Exception as exc:
                st.error(f"Could not save alerts to action queue: {format_error(exc)}")
    if not queue.empty:
        render_priority_dataframe(
            queue,
            title="Current action queue",
            priority_columns=[
                "SEVERITY", "STATUS", "CATEGORY", "ENTITY_NAME", "OWNER",
                "ONCALL_PRIMARY", "FINDING", "RECOMMENDED_ACTION",
                "TICKET_ID", "DUE_STATE",
            ],
            sort_by=["SEVERITY", "STATUS", "UPDATED_AT"],
            ascending=[True, True, False],
            raw_label="All action queue rows",
            height=320,
        )


def render_alert_delivery_automation_pane(
    alerts: pd.DataFrame,
    queue: pd.DataFrame,
    delivery_log: pd.DataFrame,
    rules: pd.DataFrame,
    company: str,
    *,
    native_registry: pd.DataFrame | None = None,
    remediation_policy: pd.DataFrame | None = None,
    remediation_dry_run: pd.DataFrame | None = None,
    action_session_factory: Callable[[str], object | None] | None = None,
    alert_actor: Callable[[], str] | None = None,
    format_error: Callable[[Exception], str] | None = None,
    email_target: Callable[[], str] | None = None,
    email_target_label: Callable[[], str] | None = None,
) -> None:
    from utils.alert_boards import build_alert_remediation_contract

    native_registry = native_registry if isinstance(native_registry, pd.DataFrame) else pd.DataFrame()
    remediation_policy = remediation_policy if isinstance(remediation_policy, pd.DataFrame) else pd.DataFrame()
    remediation_dry_run = remediation_dry_run if isinstance(remediation_dry_run, pd.DataFrame) else pd.DataFrame()
    st.subheader("Delivery & Automation")
    if email_target_label:
        defer_source_note(f"Email target defaults to {email_target_label()}.")
    controls = _delivery_remediation_control_rows(
        alerts=alerts,
        queue=queue,
        delivery_log=delivery_log,
        rules=rules,
        native_registry=native_registry,
        remediation_policy=remediation_policy,
        remediation_dry_run=remediation_dry_run,
    )
    render_priority_dataframe(
        controls,
        title="Delivery and remediation status",
        priority_columns=["STATE", "CONTROL", "EVIDENCE", "NEXT_ACTION", "ROUTE"],
        raw_label="All delivery and remediation rows",
        height=260,
    )
    operations_rows = _alert_operations_review_rows(
        alerts=alerts,
        queue=queue,
        native_registry=native_registry,
        remediation_policy=remediation_policy,
        remediation_dry_run=remediation_dry_run,
    )
    render_priority_dataframe(
        operations_rows,
        title="Alert operations readiness",
        priority_columns=["STATE", "REVIEW_AREA", "COUNT", "EVIDENCE", "NEXT_ACTION"],
        raw_label="All alert operations readiness rows",
        height=240,
        max_rows=5,
    )
    threshold_rows = _alert_threshold_tuning_rows(alerts, rules)
    render_priority_dataframe(
        threshold_rows,
        title="Threshold tuning from loaded alerts",
        priority_columns=[
            "REVIEW_STATE", "THRESHOLD_KEY", "CATEGORY", "SIGNAL_NAME",
            "CONFIGURED_THRESHOLD", "WINDOW", "RECENT_ALERTS", "OPEN_ALERTS",
            "OWNER", "SOURCE_OBJECT", "NEXT_ACTION",
        ],
        raw_label="All loaded threshold tuning rows",
        height=300,
        max_rows=9,
    )
    scope_rows = _alert_company_scope_readiness_rows(alerts, queue)
    render_priority_dataframe(
        scope_rows,
        title="Company scope readiness",
        priority_columns=[
            "STATE", "SOURCE", "ROWS", "COMPANY_VALUES", "MISSING_COMPANY",
            "ENVIRONMENT_VALUES", "MISSING_ENVIRONMENT", "NEXT_ACTION",
        ],
        raw_label="All company scope readiness rows",
        height=260,
        max_rows=6,
    )
    if alerts.empty:
        st.info("Load alert history to review remediation status for real alert rows.")
    else:
        alert_options = alerts.get("ALERT_ID", pd.Series(range(1, len(alerts) + 1), index=alerts.index)).dropna().astype(str).tolist()
        selected_id = st.selectbox("Remediation status alert", alert_options[:100], key="alert_remediation_contract_id")
        if "ALERT_ID" in alerts.columns:
            selected_rows = alerts[alerts["ALERT_ID"].astype(str) == str(selected_id)]
        else:
            selected_rows = alerts.iloc[[max(0, alert_options.index(selected_id))]]
        contract = build_alert_remediation_contract(selected_rows.iloc[0].to_dict() if not selected_rows.empty else {})
        render_priority_dataframe(
            pd.DataFrame([contract]),
            title="Safe remediation status",
            priority_columns=[
                "REMEDIATION_MODE", "EXECUTION_BOUNDARY", "ROLLBACK_GUIDANCE",
                "VERIFY_NEXT",
            ],
            raw_label="All remediation status fields",
            height=260,
        )
    policy_rows = _remediation_policy_display_rows(remediation_policy)
    if not policy_rows.empty:
        render_priority_dataframe(
            policy_rows,
            title="Remediation policy matrix",
            priority_columns=[
                "POLICY_SOURCE", "REMEDIATION_MODE", "AUTO_ELIGIBLE", "CATEGORY", "ALERT_KEY",
                "ACTION_TYPE", "REQUIRED_REVIEW", "ROLLBACK_GUIDANCE",
                "VERIFICATION_SQL",
            ],
            raw_label="All remediation policy rows",
            height=300,
            max_rows=8,
        )
    native_rows = _native_registry_status_rows(native_registry)
    if not native_rows.empty:
        render_priority_dataframe(
            native_rows,
            title="Native alert deployment status",
            priority_columns=[
                "STATUS", "ENABLED_BY_DEFAULT", "CATEGORY", "ALERT_KEY",
                "ALERT_OBJECT_NAME", "TARGET_ROUTE", "WAREHOUSE_NAME",
                "SCHEDULE_TEXT", "SAFETY_NOTE",
            ],
            raw_label="All native alert registry rows",
            height=260,
            max_rows=8,
        )
    if not remediation_dry_run.empty:
        render_priority_dataframe(
            remediation_dry_run,
            title="Recent remediation dry-runs",
            priority_columns=[
                "CREATED_AT", "DRY_RUN_STATUS", "POLICY_ID", "ALERT_KEY",
                "EXPECTED_EFFECT", "BLOCKING_REASON", "VERIFICATION_SQL",
            ],
            sort_by=["CREATED_AT"],
            ascending=False,
            raw_label="All remediation dry-run rows",
            height=260,
            max_rows=10,
        )
    render_alert_email_delivery_status(alerts, delivery_log, email_target=email_target)
    render_alert_action_queue_routing(
        alerts,
        queue,
        company,
        action_session_factory=action_session_factory,
        alert_actor=alert_actor,
        format_error=format_error,
    )


_render_alert_email_delivery_status = render_alert_email_delivery_status
_render_alert_action_queue_routing = render_alert_action_queue_routing
_render_alert_notification_remediation = render_alert_delivery_automation_pane
