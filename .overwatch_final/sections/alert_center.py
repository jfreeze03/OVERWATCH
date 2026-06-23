# sections/alert_center.py - single alert inbox and email-first alert operations
from __future__ import annotations

import streamlit as st

from config import DAY_WINDOW_OPTIONS, DEFAULT_ALERT_EMAIL, DEFAULT_DAY_WINDOW
from sections.shell_helpers import (
    consume_section_autoload_request,
    render_data_freshness,
    render_escaped_bold_text,
    render_shell_kpi_row,
    render_shell_snapshot,
    render_shell_status_strip,
    with_loaded_at,
)
from sections.alert_center_contracts import (
    ALERT_CENTER_ADMIN_VIEW_DETAILS,
    ALERT_CENTER_ADMIN_VIEW_KEY,
    ALERT_CENTER_ADMIN_VIEWS,
    ALERT_CENTER_BRIEF_FIRST_VERSION,
    ALERT_CENTER_BRIEF_WORKFLOWS,
    ALERT_CENTER_DEFAULT_VIEW,
    ALERT_CENTER_PANES,
    ALERT_CENTER_PANE_LABELS,
    ALERT_CENTER_SOURCES_BY_PANE,
    ALERT_CENTER_SOURCE_PLAN,
    _deferred_notes_key,
    defer_source_note,
)
from sections.alert_center_navigation import (
    _alert_admin_view_for_route,
    _alert_center_source_summary,
    _alert_center_sources_for_view,
    _normalize_alert_center_view,
)
from sections.alert_center_data import _load_center_data
from sections.alert_center_admin_catalog_view import render_alert_detection_catalog_tool
from sections.alert_center_admin_suppression_view import (
    ANNOTATION_TABLE,
    _annotation_table_name,
    render_suppression_windows_pane,
)
from sections.alert_center_active_view import render_active_alerts_pane as _render_active_alerts
from sections.alert_center_category_views import (
    render_alert_category_pane as _render_alert_domain_workbench,
    render_cost_alerts_pane,
    render_reliability_alerts_pane,
    render_security_alerts_pane,
)
from sections.alert_center_history_view import render_alert_history_pane
from sections.alert_center_boards import (
    _alert_center_action_brief,
    _alert_center_exception_rows,
    _alert_center_health_score,
    _alert_center_loaded_meta,
    _alert_center_operability_rows,
    _alert_center_scope_key,
    _alert_company_scope_readiness_rows,
    _alert_domain_next_move_rows,
    _alert_integration_health_board,
    _alert_lifecycle_board,
    _alert_next_incident_packet,
    _alert_open_statuses,
    _alert_operations_review_rows,
    _alert_operator_workflow_rows,
    _alert_owner_route_board,
    _alert_threshold_tuning_rows,
    _open_alert_mask,
    _status_key,
)

def _alert_email_target() -> str:
    from utils.alert_delivery import current_alert_recipient

    return current_alert_recipient(DEFAULT_ALERT_EMAIL)


def _alert_email_target_label() -> str:
    from utils.alert_delivery import alert_recipient_label

    return alert_recipient_label(_alert_email_target())


def _format_snowflake_error(exc: Exception) -> str:
    from utils import format_snowflake_error

    return format_snowflake_error(exc)


def _alert_center_action_session(action: str):
    from utils import get_session_for_action

    return get_session_for_action(
        action,
        surface="Alert Center",
        offline_note=(
            "Alert Center source summaries remain available without a connection. "
            "Status changes are handled by the DBA team outside this dashboard."
        ),
    )


def _download_csv(df: pd.DataFrame, file_name: str) -> None:
    from utils.explicit_load import render_export_controls

    render_export_controls(df, file_name, label="Export CSV")


def _pd():
    import pandas as pd

    return pd


def get_active_company() -> str:
    from utils import get_active_company as _get_active_company

    return _get_active_company()


def get_active_environment() -> str:
    from utils import get_active_environment as _get_active_environment

    return _get_active_environment()


def _render_priority_dataframe(*args, **kwargs) -> None:
    from utils.workflows import render_priority_dataframe

    render_priority_dataframe(*args, **kwargs)


def _render_workflow_selector(*args, **kwargs) -> str:
    from utils.workflows import render_workflow_selector

    return render_workflow_selector(*args, **kwargs)


def _alert_actor() -> str:
    return str(st.session_state.get("_overwatch_actor") or "OVERWATCH").strip() or "OVERWATCH"


def _render_annotations() -> None:
    render_suppression_windows_pane(
        action_session_factory=_alert_center_action_session,
        format_error=_format_snowflake_error,
    )


def _filtered_issues(issues: pd.DataFrame) -> pd.DataFrame:
    pd = _pd()
    if issues is None or issues.empty:
        return pd.DataFrame()
    source_options = ["ALL"] + sorted(issues["ISSUE_SOURCE"].dropna().astype(str).unique().tolist())
    severity_options = ["ALL", "Critical", "High", "Medium", "Low"]
    status_options = ["ALL"] + sorted(issues["STATUS"].dropna().astype(str).unique().tolist())
    f1, f2, f3 = st.columns(3)
    with f1:
        source = st.selectbox("Issue source", source_options, key="alert_center_source_filter")
    with f2:
        severity = st.selectbox("Severity", severity_options, key="alert_center_severity_filter")
    with f3:
        status = st.selectbox("Status", status_options, key="alert_center_status_filter")

    visible = issues
    if source != "ALL":
        visible = visible[visible["ISSUE_SOURCE"] == source]
    if severity != "ALL":
        visible = visible[visible["SEVERITY"] == severity]
    if status != "ALL":
        visible = visible[visible["STATUS"] == status]
    return visible


def _alert_center_pending_brief(active_view: str, required_sources: set[str]) -> dict:
    active_view = _normalize_alert_center_view(active_view)
    return {
        "state": "Ready",
        "headline": f"Load {active_view} before routing alert work.",
        "detail": f"Inputs on load: {_alert_center_source_summary(required_sources)}.",
    }


def _alert_center_brief_workflow_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in ALERT_CENTER_BRIEF_WORKFLOWS:
        view = str(item["VIEW"])
        sources = _alert_center_source_summary(_alert_center_sources_for_view(view))
        rows.append({
            "VIEW": view,
            "BUTTON_LABEL": str(item["BUTTON_LABEL"]),
            "DBA_MOVE": str(item["DBA_MOVE"]),
            "WHEN": str(item["WHEN"]),
            "SOURCES": sources,
        })
    return rows


def _queue_alert_center_view(view: str) -> None:
    admin_view = _alert_admin_view_for_route(view)
    if admin_view:
        st.session_state[ALERT_CENTER_ADMIN_VIEW_KEY] = admin_view
    normalized = _normalize_alert_center_view(view)
    if normalized in ALERT_CENTER_PANES:
        st.session_state["alert_center_requested_view"] = normalized
        st.rerun()


def _apply_queued_alert_center_view() -> None:
    requested = st.session_state.pop("alert_center_requested_view", None)
    if requested:
        admin_view = _alert_admin_view_for_route(requested)
        if admin_view:
            st.session_state[ALERT_CENTER_ADMIN_VIEW_KEY] = admin_view
        st.session_state["alert_center_active_view"] = _normalize_alert_center_view(requested)


def _apply_alert_center_brief_first_default() -> None:
    if st.session_state.get("_alert_center_brief_first_version") == ALERT_CENTER_BRIEF_FIRST_VERSION:
        admin_view = _alert_admin_view_for_route(st.session_state.get("alert_center_active_view"))
        if admin_view:
            st.session_state[ALERT_CENTER_ADMIN_VIEW_KEY] = admin_view
        st.session_state["alert_center_active_view"] = _normalize_alert_center_view(
            st.session_state.get("alert_center_active_view")
        )
        return
    if st.session_state.get("alert_center_active_view") in (None, "Alert Brief", "Command Center"):
        st.session_state["alert_center_active_view"] = ALERT_CENTER_DEFAULT_VIEW
    else:
        admin_view = _alert_admin_view_for_route(st.session_state.get("alert_center_active_view"))
        if admin_view:
            st.session_state[ALERT_CENTER_ADMIN_VIEW_KEY] = admin_view
        st.session_state["alert_center_active_view"] = _normalize_alert_center_view(
            st.session_state.get("alert_center_active_view")
        )
    st.session_state["_alert_center_brief_first_version"] = ALERT_CENTER_BRIEF_FIRST_VERSION


def _render_alert_center_brief_launchpad() -> None:
    st.markdown("**Alert Investigation Workflows**")
    rows = _alert_center_brief_workflow_rows()
    for offset in range(0, len(rows), 3):
        cols = st.columns(3)
        for col, row in zip(cols, rows[offset:offset + 3]):
            with col:
                render_escaped_bold_text(row["VIEW"])
                help_text = f"{row['DBA_MOVE']} When: {row['WHEN']}"
                if st.button(
                    row["BUTTON_LABEL"],
                    key=f"alert_center_brief_{row['VIEW']}",
                    help=help_text,
                    width="stretch",
                ):
                    _queue_alert_center_view(row["VIEW"])


def _render_alert_center_action_brief(brief: dict) -> None:
    render_shell_status_strip(
        state=brief.get("state") or "Review",
        headline=brief.get("headline") or "Review Alert Center telemetry.",
        detail=brief.get("detail") or "",
    )


def _load_alert_center_view_data(
    active_view: str,
    company: str,
    environment: str,
    days: int,
    limit: int,
    required_sources: set[str],
) -> bool:
    session = _alert_center_action_session(f"load {active_view}")
    if session is None:
        return False
    st.session_state["alert_center_data"] = _load_center_data(
        session,
        company,
        environment,
        int(days),
        int(limit),
        sources=required_sources,
    )
    if isinstance(st.session_state.get("alert_center_data"), dict):
        st.session_state["alert_center_data"]["_freshness_meta"] = with_loaded_at(
            {
                "view": active_view,
                "company": company,
                "environment": environment,
                "days": int(days),
                "limit": int(limit),
                "sources": sorted(required_sources),
            },
            source=f"{active_view} loaded sources",
        )
    st.session_state["alert_center_scope"] = (company, environment, int(days), int(limit))
    st.session_state["alert_center_loaded_scope_key"] = _alert_center_scope_key(
        active_view,
        company,
        environment,
        int(days),
        int(limit),
        required_sources,
    )
    return True


def _render_alert_center_metric_rows(
    *,
    open_issues: int,
    open_alerts: int,
    critical_high: int,
    overdue: int,
    email_ready: int,
    email_logged: int,
    open_queue: int,
    loaded: bool = True,
) -> None:
    if not loaded:
        render_shell_kpi_row((
            ("Scope", "Company"),
            ("Window", "Selected"),
            ("Telemetry", "Load view"),
            ("Route", "Command"),
        ))
        return
    render_shell_kpi_row((
        ("Issues", f"{open_issues:,}"),
        ("Alerts", f"{open_alerts:,}"),
        ("Critical", f"{critical_high:,}"),
        ("Overdue", f"{overdue:,}"),
    ))
    if loaded:
        with st.expander("Delivery and queue counts", expanded=False):
            render_shell_snapshot((
                ("Email Ready", f"{email_ready:,}"),
                ("Delivered", f"{email_logged:,}"),
                ("Open Queue", f"{open_queue:,}"),
            ))


def _alert_command_lanes(
    *,
    active_view: str,
    required_sources: set[str],
    alerts: object | None = None,
    queue: object | None = None,
    issues: object | None = None,
    delivery_log: object | None = None,
    loaded: bool = False,
) -> list[dict[str, str]]:
    """Return alert monitoring lanes without loading new data."""
    if not loaded:
        source_text = ", ".join(sorted(required_sources)) if required_sources else "no source load required"
        return [
            {
                "label": "Critical / high",
                "value": "On demand",
                "state": "Severity",
                "detail": f"{active_view} will read: {source_text}.",
            },
            {
                "label": "Overdue SLA",
                "value": "On demand",
                "state": "Aging",
                "detail": "Open alerts need route, acknowledgement, suppression, or resolution.",
            },
            {
                "label": "Security risk",
                "value": "On demand",
                "state": "Security",
                "detail": "Failed logins, risky grants, exfiltration, and policy drift route here.",
            },
            {
                "label": "Cost",
                "value": "On demand",
                "state": "Spend",
                "detail": "Runaway spend, warehouse spikes, Cortex spend, and spend risk.",
            },
            {
                "label": "Performance",
                "value": "On demand",
                "state": "Queries",
                "detail": "Long, queued, failed, spilling, and blocked query signals.",
            },
            {
                "label": "Pipeline reliability",
                "value": "On demand",
                "state": "Tasks",
                "detail": "Failed, skipped, late, or suspended task/procedure paths.",
            },
            {
                "label": "Data quality",
                "value": "Configured",
                "state": "Rules",
                "detail": "Metadata-driven freshness, row count, null, duplicate, and schema checks.",
            },
            {
                "label": "Notification route",
                "value": "On demand",
                "state": "Delivery",
                "detail": "Email/webhook/native-alert delivery remains audit-backed.",
            },
        ]

    pd = _pd()
    alerts = alerts if isinstance(alerts, pd.DataFrame) else pd.DataFrame()
    queue = queue if isinstance(queue, pd.DataFrame) else pd.DataFrame()
    issues = issues if isinstance(issues, pd.DataFrame) else pd.DataFrame()
    delivery_log = delivery_log if isinstance(delivery_log, pd.DataFrame) else pd.DataFrame()
    open_alerts = _open_alert_mask(alerts) if not alerts.empty else pd.Series(dtype=bool)
    severity = alerts.get("SEVERITY", pd.Series(index=alerts.index, dtype=str)).fillna("").astype(str) if not alerts.empty else pd.Series(dtype=str)
    category = alerts.get("CATEGORY", pd.Series(index=alerts.index, dtype=str)).fillna("").astype(str).str.upper() if not alerts.empty else pd.Series(dtype=str)
    critical_high = int((severity.isin(["Critical", "High"]) & open_alerts).sum()) if not alerts.empty else 0
    overdue = 0
    if not alerts.empty and "SLA_STATE" in alerts.columns:
        overdue = int((alerts["SLA_STATE"].fillna("").astype(str).eq("Overdue") & open_alerts).sum())
    open_queue = 0
    if not queue.empty and "STATUS" in queue.columns:
        open_queue = int((~queue["STATUS"].fillna("New").astype(str).str.title().isin(["Fixed", "Ignored"])).sum())
    delivery_failures = 0
    if not delivery_log.empty and "DELIVERY_STATUS" in delivery_log.columns:
        delivery_failures = int(delivery_log["DELIVERY_STATUS"].fillna("").astype(str).str.upper().str.contains("FAILED|ERROR|BOUNCED", regex=True).sum())

    def cat_count(*needles: str) -> int:
        if category.empty:
            return 0
        mask = pd.Series(False, index=category.index)
        for needle in needles:
            mask = mask | category.str.contains(needle, regex=False)
        return int((mask & open_alerts).sum())

    return [
        {
            "label": "Critical / high",
            "value": f"{critical_high:,}",
            "state": "Severity" if critical_high else "Clear",
            "detail": f"{int(open_alerts.sum()) if not open_alerts.empty else 0:,} open alert(s) in loaded scope.",
        },
        {
            "label": "Overdue SLA",
            "value": f"{overdue:,}",
            "state": "Aging" if overdue else "Clear",
            "detail": "Overdue high-severity rows should be acknowledged or escalated first.",
        },
        {
            "label": "Security risk",
            "value": f"{cat_count('SECURITY'):,}",
            "state": "Security",
            "detail": "Login, privilege, sharing, and access anomalies.",
        },
        {
            "label": "Cost",
            "value": f"{cat_count('COST', 'COST'):,}",
            "state": "Spend",
            "detail": "Warehouse, Cortex, service-cost, and spend risk signals.",
        },
        {
            "label": "Performance",
            "value": f"{cat_count('PERFORMANCE', 'QUERY', 'WAREHOUSE'):,}",
            "state": "Queries",
            "detail": "Long, queued, failed, spilling, and blocked queries.",
        },
        {
            "label": "Pipeline reliability",
            "value": f"{cat_count('TASK', 'PIPELINE', 'PROCEDURE'):,}",
            "state": "Tasks",
            "detail": "Task/procedure failures, late runs, and recovery alerts.",
        },
        {
            "label": "Action queue",
            "value": f"{open_queue:,}",
            "state": "Routes",
            "detail": f"{len(issues):,} unified issue row(s) loaded.",
        },
        {
            "label": "Delivery failures",
            "value": f"{delivery_failures:,}",
            "state": "Delivery" if delivery_failures else "Ready",
            "detail": f"{len(delivery_log):,} notification audit row(s).",
        },
    ]


def _render_alert_command_lane_board(lanes: list[dict[str, str]]) -> None:
    pd = _pd()
    lane_rows = pd.DataFrame(lanes)
    if lane_rows.empty:
        return
    _render_priority_dataframe(
        lane_rows,
        title="Alert operating lanes",
        priority_columns=["label", "value", "state", "detail"],
        raw_label="All alert operating lanes",
        height=260,
        max_rows=8,
    )


def _render_alert_center_exception_strip(exceptions: pd.DataFrame) -> None:
    st.markdown("**Exception Strip**")
    if exceptions is None or exceptions.empty:
        st.success("No alert exceptions found for the loaded scope.")
        return
    _render_priority_dataframe(
        exceptions,
        title="Alert exceptions to work first",
        priority_columns=["SEVERITY", "SIGNAL", "COUNT", "STATE", "NEXT_ACTION", "OWNER", "ROUTE"],
        sort_by=["SEVERITY", "COUNT", "SIGNAL"],
        ascending=[True, False, True],
        max_rows=5,
        raw_label="All alert exceptions",
        height=220,
    )


def _render_alert_detection_catalog() -> None:
    render_alert_detection_catalog_tool(
        action_session_factory=_alert_center_action_session,
        format_error=_format_snowflake_error,
        threshold_rows_loader=_alert_threshold_tuning_rows,
        operations_rows_loader=lambda native_registry: _alert_operations_review_rows(
            native_registry=native_registry,
        ),
    )


def _render_alert_email_delivery_status(alerts: pd.DataFrame, delivery_log: pd.DataFrame) -> None:
    pd = _pd()
    st.markdown("**Notification Queue**")
    defer_source_note(
        "Rows are email-ready by default once the Snowflake email integration is enabled."
    )
    if alerts.empty:
        st.info("No email-ready alert rows found.")
    else:
        email_view = alerts.copy()
        if "EMAIL_TARGET" not in email_view.columns:
            email_view["EMAIL_TARGET"] = _alert_email_target()
        email_view["EMAIL_TARGET"] = email_view["EMAIL_TARGET"].replace("", _alert_email_target()).fillna(_alert_email_target())
        _render_priority_dataframe(
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
        _render_priority_dataframe(
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


def _render_alert_action_queue_routing(alerts: pd.DataFrame, queue: pd.DataFrame, company: str) -> None:
    pd = _pd()
    st.markdown("**Route Alerts To Action Queue**")
    if alerts.empty:
        st.info("Load alert history before routing alerts to the action queue.")
    else:
        from utils.alert_action_queue import alert_history_to_actions, mark_alerts_routed
        from utils.action_queue import upsert_actions

        routable = alerts[_open_alert_mask(alerts)] if not alerts.empty else alerts
        defer_source_note(f"{len(routable):,} open alert row(s) are eligible for action queue routing.")
        actions_preview = pd.DataFrame(alert_history_to_actions(routable, company=company))
        if not actions_preview.empty:
            recovery_count = int((actions_preview.get("Category", pd.Series(dtype=str)) == "Task & Procedure Reliability").sum())
            if recovery_count:
                defer_source_note(f"{recovery_count:,} task/procedure recovery action(s) include recovery SLA and telemetry status fields.")
            _render_priority_dataframe(
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
                session = _alert_center_action_session("route alerts to the action queue")
                if session is None:
                    return
                saved = upsert_actions(session, actions_preview.to_dict("records"))
                alert_ids = routable.get("ALERT_ID", pd.Series(dtype=str)).dropna().astype(str).tolist()
                mark_alerts_routed(session, alert_ids, action_count=saved, actor=_alert_actor())
                st.success(f"Saved {saved} alert action(s) to the action queue.")
                st.session_state.pop("alert_center_data", None)
            except Exception as exc:
                st.error(f"Could not save alerts to action queue: {_format_snowflake_error(exc)}")
    if not queue.empty:
        _render_priority_dataframe(
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


def _render_alert_notification_remediation(
    alerts: pd.DataFrame,
    queue: pd.DataFrame,
    delivery_log: pd.DataFrame,
    rules: pd.DataFrame,
    company: str,
    native_registry: pd.DataFrame | None = None,
    remediation_policy: pd.DataFrame | None = None,
    remediation_dry_run: pd.DataFrame | None = None,
) -> None:
    from utils.alert_boards import build_alert_remediation_contract
    from utils.alert_native_catalog import build_alert_remediation_policy_seed_rows

    pd = _pd()
    native_registry = native_registry if isinstance(native_registry, pd.DataFrame) else pd.DataFrame()
    remediation_policy = remediation_policy if isinstance(remediation_policy, pd.DataFrame) else pd.DataFrame()
    remediation_dry_run = remediation_dry_run if isinstance(remediation_dry_run, pd.DataFrame) else pd.DataFrame()
    st.subheader("Delivery & Automation")
    enabled_native = 0
    candidate_native = 0
    if not native_registry.empty:
        enabled_native = int(native_registry.get("ENABLED_BY_DEFAULT", pd.Series(dtype=bool)).fillna(False).astype(bool).sum())
        candidate_native = int(native_registry.get("STATUS", pd.Series(dtype=str)).fillna("").astype(str).str.upper().eq("CANDIDATE").sum())
    auto_policy = 0
    if not remediation_policy.empty:
        auto_policy = int(remediation_policy.get("AUTO_ELIGIBLE", pd.Series(dtype=bool)).fillna(False).astype(bool).sum())
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
            "STATE": "Ready" if not delivery_log.empty else "Review",
            "EVIDENCE": f"{len(delivery_log):,} delivery audit row(s) loaded.",
            "NEXT_ACTION": "Log delivery status for open critical/high alerts.",
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
            "STATE": "Ready" if not native_registry.empty else "Review",
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
    _render_priority_dataframe(
        pd.DataFrame(controls),
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
    _render_priority_dataframe(
        operations_rows,
        title="Alert operations readiness",
        priority_columns=["STATE", "REVIEW_AREA", "COUNT", "EVIDENCE", "NEXT_ACTION"],
        raw_label="All alert operations readiness rows",
        height=240,
        max_rows=5,
    )
    threshold_rows = _alert_threshold_tuning_rows(alerts, rules)
    _render_priority_dataframe(
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
    _render_priority_dataframe(
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
        _render_priority_dataframe(
            pd.DataFrame([contract]),
            title="Safe remediation status",
            priority_columns=[
                "REMEDIATION_MODE", "EXECUTION_BOUNDARY", "ROLLBACK_GUIDANCE",
                "VERIFY_NEXT",
            ],
            raw_label="All remediation status fields",
            height=260,
        )
    policy_rows = remediation_policy.copy() if not remediation_policy.empty else pd.DataFrame(build_alert_remediation_policy_seed_rows())
    if not policy_rows.empty:
        if "POLICY_SOURCE" not in policy_rows.columns:
            policy_rows["POLICY_SOURCE"] = "Live policy table" if not remediation_policy.empty else "Built-in seed policy"
        _render_priority_dataframe(
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
    if not native_registry.empty:
        _render_priority_dataframe(
            native_registry,
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
        _render_priority_dataframe(
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
    _render_alert_email_delivery_status(alerts, delivery_log)
    _render_alert_action_queue_routing(alerts, queue, company)


def _render_operational_ownership_coverage(company: str, environment: str) -> None:
    from utils import load_ownership_coverage_rollup

    pd = _pd()
    coverage = load_ownership_coverage_rollup(
        company,
        environment,
        surface="Alert Center",
        days=35,
    )
    if coverage is None or getattr(coverage, "empty", True):
        st.caption("Operational ownership coverage is pending. Refresh the enterprise operating model mart to show alert route gaps.")
        return
    total = int(pd.to_numeric(coverage.get("TOTAL_ITEMS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    gaps = int(pd.to_numeric(coverage.get("GAP_ITEMS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    routed = int(pd.to_numeric(coverage.get("ROUTED_ITEMS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    st.markdown("**Operational Ownership Coverage**")
    render_shell_snapshot((
        ("Alert Items", f"{total:,}"),
        ("Routed", f"{routed:,}"),
        ("Gaps", f"{gaps:,}"),
    ))
    view = coverage[[
        column for column in [
            "ENTITY_TYPE", "TOTAL_ITEMS", "ROUTED_ITEMS", "GAP_ITEMS",
            "COVERAGE_PCT", "TRUST_LEVEL", "CONFIDENCE", "TOP_GAP_ENTITY",
            "ROUTE", "NEXT_ACTION",
        ]
        if column in coverage.columns
    ]]
    st.dataframe(view, width="stretch", hide_index=True)


def _render_operational_risk_score_explanation(company: str, environment: str) -> None:
    """Expose Operational Risk Score drivers behind an explicit Load action."""
    from utils import load_executive_scorecard_detail

    pd = _pd()
    st.markdown("**Operational Risk Score**")
    st.caption("Loads alert/action ownership risk drivers from the Executive Scorecard history.")
    if st.button("Load Operational Risk Score Drivers", key="alert_center_load_operational_score_drivers", width="stretch"):
        st.session_state["alert_center_operational_score_detail"] = load_executive_scorecard_detail(
            company,
            environment,
            score_key="OPERATIONAL_RISK",
            days=180,
        )
        st.session_state["alert_center_operational_score_scope"] = (company, environment)

    detail = st.session_state.get("alert_center_operational_score_detail")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("alert_center_operational_score_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No Operational Risk Score driver rows are available for this scope yet.")
            return
        latest = detail.iloc[0]
        score = float(pd.to_numeric(pd.Series([latest.get("CURRENT_SCORE")]), errors="coerce").fillna(0).iloc[0])
        render_shell_snapshot((
            ("Score", f"{score:.0f}/100"),
            ("Status", str(latest.get("STATUS") or "Unknown")),
            ("Trend", str(latest.get("TREND") or "Stable")),
            ("Owner", str(latest.get("OWNER_ROUTE") or "Owner gap")),
        ))
        _render_priority_dataframe(
            detail,
            title="Operational Risk Score drivers",
            priority_columns=[
                "SNAPSHOT_TS", "CURRENT_SCORE", "STATUS", "TREND", "TOP_DRIVER",
                "RECOMMENDED_ACTION", "OWNER_ROUTE", "OWNER_GAP",
                "CONFIDENCE", "SOURCE_OBJECTS", "LAST_REFRESHED_TS",
            ],
            sort_by=["SNAPSHOT_TS"],
            ascending=False,
            raw_label="All operational risk score history rows",
            height=260,
            max_rows=8,
        )


def _render_alert_change_context(company: str, environment: str) -> None:
    """Show change correlations near Alert Center context without claiming causality."""
    from utils import load_change_correlation_detail

    pd = _pd()
    st.markdown("**Related Changes**")
    st.caption("Loads possible change correlations for alert, cost, security, and workload signals.")
    if st.button("Load Related Changes", key="alert_center_load_related_changes", width="stretch"):
        st.session_state["alert_center_change_correlation_detail"] = load_change_correlation_detail(
            company,
            environment,
            correlation_types=("Alert", "Cost", "Security", "Workload"),
            days=180,
        )
        st.session_state["alert_center_change_scope"] = (company, environment)

    detail = st.session_state.get("alert_center_change_correlation_detail")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("alert_center_change_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No related change correlations are available for this scope yet.")
            return
        render_shell_snapshot((
            ("Possible Links", f"{len(detail):,}"),
            ("High Risk", f"{int(pd.Series(detail.get('RISK_LEVEL', [])).astype(str).isin(['Critical', 'High']).sum()):,}"),
            ("Signals", f"{int(pd.Series(detail.get('RELATED_SIGNAL', [])).dropna().nunique()):,}"),
        ))
        _render_priority_dataframe(
            detail,
            title="Related changes and possible correlations",
            priority_columns=[
                "RELATED_TS", "CORRELATION_TYPE", "CHANGE_TYPE", "OBJECT_TYPE",
                "OBJECT_NAME", "CHANGED_BY", "RELATED_SIGNAL", "RELATED_ENTITY",
                "CORRELATION_LABEL", "RISK_LEVEL", "BUSINESS_IMPACT",
                "OWNER_ROUTE", "CONFIDENCE", "EVIDENCE",
            ],
            sort_by=["RELATED_TS", "CHANGE_TS"],
            ascending=False,
            raw_label="All related change correlation rows",
            height=320,
            max_rows=12,
        )
        st.caption("These rows are timing and entity matches only. Treat them as possible correlations until evidence proves causality.")


def _render_alert_action_workflows(company: str, environment: str) -> None:
    """Show alert/incident action workflows only after the operator loads them."""
    from utils import load_closed_loop_workflow_detail

    pd = _pd()
    st.markdown("**Alert Action Workflows**")
    st.caption(
        "Loads action workflows tied to alert and incident context. "
        "Recommended SQL/action text remains review-gated and is not executed from Alert Center."
    )
    domains = ("Alert", "Cost", "Operations", "Security", "Workload")
    if st.button("Load Alert Action Workflows", key="alert_center_load_closed_loop_workflows", width="stretch"):
        st.session_state["alert_center_closed_loop_workflows"] = load_closed_loop_workflow_detail(
            company,
            environment,
            domains=domains,
            days=180,
        )
        st.session_state["alert_center_closed_loop_scope"] = (company, environment)

    detail = st.session_state.get("alert_center_closed_loop_workflows")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("alert_center_closed_loop_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No alert action workflows are available for this scope yet.")
            return
        status = detail.get("VERIFICATION_STATUS", pd.Series(dtype=str)).fillna("").astype(str)
        approval = detail.get("APPROVAL_STATUS", pd.Series(dtype=str)).fillna("").astype(str)
        actual = pd.to_numeric(detail.get("ACTUAL_VERIFIED_SAVINGS_USD", pd.Series(dtype=float)), errors="coerce").fillna(0)
        render_shell_snapshot((
            ("Actions", f"{len(detail):,}"),
            ("Need Approval", f"{int((~approval.isin(['Approved', 'Not Required'])).sum()):,}"),
            ("Verify", f"{int((~status.isin(['Verified', 'Closed'])).sum()):,}"),
            ("Verified Value", f"${float(actual.sum()):,.0f}"),
        ))
        _render_priority_dataframe(
            detail,
            title="Alert and incident action workflows",
            priority_columns=[
                "ACTION_DOMAIN", "FINDING", "SOURCE_TELEMETRY", "ENTITY_TYPE",
                "ENTITY_NAME", "RISK_LEVEL", "OWNER_ROUTE", "APPROVAL_STATUS",
                "EXECUTION_MODE", "VERIFICATION_STATUS", "EXPECTED_SAVINGS_USD",
                "ACTUAL_VERIFIED_SAVINGS_USD", "RECOMMENDED_ACTION",
                "LAST_REFRESHED_TS",
            ],
            sort_by=["RISK_LEVEL", "LAST_REFRESHED_TS"],
            ascending=[True, False],
            raw_label="All alert closed-loop workflow rows",
            height=320,
            max_rows=12,
        )


def _render_alert_command_findings(company: str, environment: str) -> None:
    """Show related correlated findings for alert context."""
    from utils import load_command_center_finding_detail, load_command_center_recommendation_detail

    pd = _pd()
    st.markdown("**Alert Investigation Findings**")
    st.caption(
        "Loads command findings tied to alerts, failures, cost, security, workload, and possible change correlations. "
        "Recommendations remain review-gated."
    )
    types = ("Failure / SLA", "Cost Spike", "Warehouse Slow", "Security Risk", "Recent Change")
    if st.button("Load Alert Investigation Findings", key="alert_center_load_command_findings", width="stretch"):
        st.session_state["alert_center_command_findings"] = load_command_center_finding_detail(
            company,
            environment,
            investigation_types=types,
            days=180,
        )
        st.session_state["alert_center_command_recommendations"] = load_command_center_recommendation_detail(
            company,
            environment,
            investigation_types=types,
            days=180,
        )
        st.session_state["alert_center_command_scope"] = (company, environment)

    if st.session_state.get("alert_center_command_scope") != (company, environment):
        return
    findings = st.session_state.get("alert_center_command_findings")
    recommendations = st.session_state.get("alert_center_command_recommendations")
    if isinstance(findings, pd.DataFrame):
        if findings.empty:
            st.info("No alert-related correlated investigation findings are available for this scope yet.")
        else:
            _render_priority_dataframe(
                findings,
                title="Alert-related root-cause candidates",
                priority_columns=[
                    "INVESTIGATION_TYPE", "QUESTION_TEXT", "ROOT_CAUSE_CANDIDATE",
                    "CAUSALITY_LABEL", "EVIDENCE_SUMMARY", "CONFIDENCE",
                    "OWNER_ROUTE", "RELATED_CHANGES", "RELATED_ALERTS",
                    "RELATED_SCORECARD_DRIVERS", "RELATED_FORECASTS",
                    "RECOMMENDED_ACTION", "RISK_LEVEL", "EXECUTION_PLAN_REF",
                    "VERIFICATION_PATH", "LAST_REFRESHED_TS",
                ],
                sort_by=["RISK_LEVEL", "LAST_REFRESHED_TS"],
                ascending=[True, False],
                raw_label="All alert investigation findings",
                height=320,
                max_rows=10,
            )
    if isinstance(recommendations, pd.DataFrame) and not recommendations.empty:
        _render_priority_dataframe(
            recommendations,
            title="Alert investigation recommendations",
            priority_columns=[
                "INVESTIGATION_TYPE", "RECOMMENDED_ACTION", "RISK_LEVEL",
                "OWNER_ROUTE", "EXECUTION_PLAN_REF", "REVIEW_REQUIRED",
                "VERIFICATION_PATH", "SAFETY_NOTE", "LAST_REFRESHED_TS",
            ],
            sort_by=["RISK_LEVEL", "LAST_REFRESHED_TS"],
            ascending=[True, False],
            raw_label="All alert investigation recommendations",
            height=260,
            max_rows=8,
        )


def _render_advanced_alert_diagnostics(company: str, environment: str) -> None:
    """Render alert diagnostics after the active alert workflow."""
    st.divider()
    with st.expander("Advanced alert diagnostics and enterprise evidence", expanded=False):
        _render_operational_ownership_coverage(company, environment)
        _render_operational_risk_score_explanation(company, environment)
        _render_alert_change_context(company, environment)
        _render_alert_action_workflows(company, environment)
        _render_alert_command_findings(company, environment)


def _render_alert_settings_admin_pane(source_view: str = "Delivery & Automation", **kwargs) -> None:
    if source_view == "Suppression Windows":
        _render_annotations()
    elif source_view == "Detection Catalog":
        _render_alert_detection_catalog()
    elif source_view == "Delivery & Automation":
        _render_alert_notification_remediation(**kwargs)


ALERT_CENTER_RENDERERS = {
    ALERT_CENTER_DEFAULT_VIEW: _render_active_alerts,
    "Cost Alerts": render_cost_alerts_pane,
    "Reliability Alerts": render_reliability_alerts_pane,
    "Security Alerts": render_security_alerts_pane,
    "Alert History": render_alert_history_pane,
    "Alert Settings / Admin": _render_alert_settings_admin_pane,
}


ALERT_CENTER_ADMIN_RENDERERS = {
    "Detection Catalog": render_alert_detection_catalog_tool,
    "Delivery & Automation": _render_alert_notification_remediation,
    "Suppression Windows": render_suppression_windows_pane,
}


def render() -> None:
    company = get_active_company()
    environment = get_active_environment()
    _apply_alert_center_brief_first_default()
    _apply_queued_alert_center_view()

    active_view = _render_workflow_selector(
        "Alert Center view",
        "alert_center_active_view",
        ALERT_CENTER_PANES,
        labels=ALERT_CENTER_PANE_LABELS,
        columns=4,
    )
    source_view = active_view
    if active_view == "Alert Settings / Admin":
        source_view = _render_workflow_selector(
            "Advanced alert admin tool",
            ALERT_CENTER_ADMIN_VIEW_KEY,
            ALERT_CENTER_ADMIN_VIEWS,
            ALERT_CENTER_ADMIN_VIEW_DETAILS,
            columns=3,
        )

    required_sources = _alert_center_sources_for_view(source_view)

    if source_view == "Suppression Windows":
        _render_annotations()
        _render_advanced_alert_diagnostics(company, environment)
        return

    if source_view == "Detection Catalog":
        _render_alert_detection_catalog()
        _render_advanced_alert_diagnostics(company, environment)
        return

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        days = st.selectbox(
            "Alert window",
            DAY_WINDOW_OPTIONS,
            index=DAY_WINDOW_OPTIONS.index(DEFAULT_DAY_WINDOW),
            format_func=lambda value: f"{value} days",
        )
    with c2:
        limit = st.selectbox("Rows", [50, 100, 200, 500], index=2)
    data = st.session_state.get("alert_center_data")
    expected_scope = (company, environment, int(days), int(limit))
    loaded_sources = set(data.get("_loaded_sources") or []) if isinstance(data, dict) else set()
    current_data = (
        isinstance(data, dict)
        and st.session_state.get("alert_center_scope") == expected_scope
        and required_sources.issubset(loaded_sources)
    )
    alert_autoload_requested = consume_section_autoload_request("Alert Center")
    if (
        alert_autoload_requested
        and source_view not in {"Suppression Windows", "Detection Catalog"}
        and not current_data
    ):
        st.caption(
            "Alert Center opened without live Snowflake reads. "
            f"Load {source_view} when fresh alert telemetry is needed."
        )
        defer_source_note(f"Inputs on load: {_alert_center_source_summary(required_sources)}")
    render_data_freshness(
        _alert_center_loaded_meta(data, source_view) if current_data else {},
        source=f"{source_view} inputs",
        target_minutes=60,
        delayed_note="Alert Center reads bounded alert/action sources on demand; ACCOUNT_USAGE-backed inputs can lag.",
    )
    with c3:
        if st.button(f"Load {source_view}", key="alert_center_load", type="primary"):
            if _load_alert_center_view_data(source_view, company, environment, int(days), int(limit), required_sources):
                st.rerun()

    if not isinstance(data, dict):
        _render_alert_center_action_brief(_alert_center_pending_brief(source_view, required_sources))
        _render_alert_center_metric_rows(
            open_issues=0,
            open_alerts=0,
            critical_high=0,
            overdue=0,
            email_ready=0,
            email_logged=0,
            open_queue=0,
            loaded=False,
        )
        _render_alert_command_lane_board(_alert_command_lanes(active_view=source_view, required_sources=required_sources))
        st.info(f"Load {source_view} when ready.")
        defer_source_note(f"Inputs on load: {_alert_center_source_summary(required_sources)}")
        _render_advanced_alert_diagnostics(company, environment)
        return

    loaded_scope = st.session_state.get("alert_center_scope")
    if loaded_scope != expected_scope:
        _render_alert_center_action_brief(_alert_center_pending_brief(source_view, required_sources))
        _render_alert_center_metric_rows(
            open_issues=0,
            open_alerts=0,
            critical_high=0,
            overdue=0,
            email_ready=0,
            email_logged=0,
            open_queue=0,
            loaded=False,
        )
        _render_alert_command_lane_board(_alert_command_lanes(active_view=source_view, required_sources=required_sources))
        st.warning("Company, environment, or window changed after this load. Reload before triaging alerts.")
        defer_source_note(f"Loaded scope: {loaded_scope or 'none'} | Current scope: {expected_scope}")
        _render_advanced_alert_diagnostics(company, environment)
        return
    loaded_sources = set(data.get("_loaded_sources") or [])
    missing_sources = sorted(required_sources - loaded_sources)
    if missing_sources:
        _render_alert_center_action_brief(_alert_center_pending_brief(source_view, required_sources))
        _render_alert_center_metric_rows(
            open_issues=0,
            open_alerts=0,
            critical_high=0,
            overdue=0,
            email_ready=0,
            email_logged=0,
            open_queue=0,
            loaded=False,
        )
        _render_alert_command_lane_board(_alert_command_lanes(active_view=source_view, required_sources=required_sources))
        st.info(f"Load {source_view} to fetch missing input(s).")
        defer_source_note(f"Missing Alert Center input(s): {_alert_center_source_summary(set(missing_sources))}")
        _render_advanced_alert_diagnostics(company, environment)
        return

    pd = _pd()
    alerts = data.get("alerts") if isinstance(data.get("alerts"), pd.DataFrame) else pd.DataFrame()
    queue = data.get("action_queue") if isinstance(data.get("action_queue"), pd.DataFrame) else pd.DataFrame()
    issues = data.get("issues") if isinstance(data.get("issues"), pd.DataFrame) else pd.DataFrame()
    delivery_log = data.get("delivery_log") if isinstance(data.get("delivery_log"), pd.DataFrame) else pd.DataFrame()
    rules = data.get("rules") if isinstance(data.get("rules"), pd.DataFrame) else pd.DataFrame()
    native_registry = data.get("native_registry") if isinstance(data.get("native_registry"), pd.DataFrame) else pd.DataFrame()
    remediation_policy = data.get("remediation_policy") if isinstance(data.get("remediation_policy"), pd.DataFrame) else pd.DataFrame()
    remediation_dry_run = data.get("remediation_dry_run") if isinstance(data.get("remediation_dry_run"), pd.DataFrame) else pd.DataFrame()
    if data.get("alerts_error"):
        st.info("Alert history unavailable.")
        defer_source_note(
            "Enable alert history objects before relying on this monitoring source.",
            data["alerts_error"],
        )
    if data.get("queue_error"):
        defer_source_note("Action queue unavailable for this role/context.", data["queue_error"])
    if data.get("delivery_error"):
        defer_source_note("Delivery audit is not available in this environment yet.", data["delivery_error"])
    if data.get("rule_error"):
        defer_source_note("Alert rule catalog is not available in this environment yet.", data["rule_error"])
    if data.get("native_registry_error"):
        defer_source_note("Native alert registry is not available in this environment yet.", data["native_registry_error"])
    if data.get("remediation_policy_error"):
        defer_source_note("Remediation policy catalog is not available in this environment yet.", data["remediation_policy_error"])
    if data.get("remediation_dry_run_error"):
        defer_source_note("Remediation dry-run audit is not available in this environment yet.", data["remediation_dry_run_error"])
    defer_source_note(f"Loaded {data.get('loaded_at', '')}. Email target defaults to {_alert_email_target_label()}.")

    open_alerts = _open_alert_mask(alerts)
    high_alerts = pd.Series(dtype=bool)
    if not alerts.empty:
        high_alerts = alerts["SEVERITY"].isin(["Critical", "High"]) & open_alerts
    email_ready = pd.Series(dtype=bool)
    if not alerts.empty:
        email_ready = alerts["DELIVERY_STATUS"].fillna("").astype(str).str.upper().str.contains("EMAIL_READY")
    email_logged = pd.Series(dtype=bool)
    if not alerts.empty:
        email_logged = alerts["DELIVERY_STATUS"].fillna("").astype(str).str.upper().str.contains("EMAIL_LOGGED")
    overdue_alerts = pd.Series(dtype=bool)
    if not alerts.empty and "SLA_STATE" in alerts.columns:
        overdue_alerts = alerts["SLA_STATE"].fillna("").astype(str).eq("Overdue") & open_alerts
    open_queue = pd.Series(dtype=bool)
    if not queue.empty and "STATUS" in queue.columns:
        open_queue = ~queue["STATUS"].fillna("New").astype(str).str.title().isin(["Fixed", "Ignored"])

    open_issue_count = len(issues)
    open_alert_count = int(open_alerts.sum()) if len(open_alerts) else 0
    critical_high_count = int(high_alerts.sum()) if len(high_alerts) else 0
    overdue_count = int(overdue_alerts.sum()) if len(overdue_alerts) else 0
    email_ready_count = int(email_ready.sum()) if len(email_ready) else 0
    email_logged_count = int(email_logged.sum()) if len(email_logged) else 0
    open_queue_count = int(open_queue.sum()) if len(open_queue) else 0

    readiness_rows = pd.DataFrame()
    exception_rows = _alert_center_exception_rows(
        alerts=alerts,
        queue=queue,
        issues=issues,
        delivery_log=delivery_log,
        readiness_rows=readiness_rows,
    )

    _render_alert_center_action_brief(
        _alert_center_action_brief(
            open_issues=open_issue_count,
            open_alerts=open_alert_count,
            critical_high=critical_high_count,
            overdue=overdue_count,
            email_ready=email_ready_count,
            email_logged=email_logged_count,
            open_queue=open_queue_count,
            readiness_rows=readiness_rows,
        )
    )
    _render_alert_center_metric_rows(
        open_issues=open_issue_count,
        open_alerts=open_alert_count,
        critical_high=critical_high_count,
        overdue=overdue_count,
        email_ready=email_ready_count,
        email_logged=email_logged_count,
        open_queue=open_queue_count,
    )
    _render_alert_command_lane_board(
        _alert_command_lanes(
            active_view=source_view,
            required_sources=required_sources,
            alerts=alerts,
            queue=queue,
            issues=issues,
            delivery_log=delivery_log,
            loaded=True,
        )
    )
    _render_alert_center_exception_strip(exception_rows)

    if source_view == ALERT_CENTER_DEFAULT_VIEW:
        _render_active_alerts(alerts, queue, delivery_log, rules)

    elif source_view in {"Cost Alerts", "Reliability Alerts", "Security Alerts"}:
        _render_alert_domain_workbench(source_view, alerts, queue, rules)

    elif source_view == "Delivery & Automation":
        _render_alert_notification_remediation(
            alerts,
            queue,
            delivery_log,
            rules,
            company,
            native_registry=native_registry,
            remediation_policy=remediation_policy,
            remediation_dry_run=remediation_dry_run,
        )

    elif source_view == "Issue Inbox":
        st.subheader("All Active DBA Issues")
        visible = _filtered_issues(issues)
        if visible.empty:
            st.success("No active alert or action queue issues found for this scope.")
        else:
            st.caption(
                f"{len(visible):,} issue row(s) match the filters. "
                "Use the exception strip first; render row-level detail only when needed."
            )
            detail_visible = bool(st.session_state.get("alert_center_issue_detail_visible"))
            detail_label = "Hide Issue Detail" if detail_visible else "Show Issue Detail"
            if st.button(detail_label, key="alert_center_toggle_issue_detail", width="stretch"):
                detail_visible = not detail_visible
                st.session_state["alert_center_issue_detail_visible"] = detail_visible
            if st.session_state.get("alert_center_issue_detail_visible"):
                _render_priority_dataframe(
                    visible,
                    title="Unified DBA issue inbox",
                    priority_columns=[
                        "ISSUE_SOURCE", "SEVERITY", "STATUS", "DOMAIN", "SIGNAL",
                        "ENTITY", "DETAIL", "NEXT_ACTION", "OWNER", "EMAIL_TARGET",
                        "DELIVERY_STATUS", "ROUTE",
                    ],
                    sort_by=["SEVERITY", "ISSUE_SOURCE", "SIGNAL"],
                    ascending=[True, True, True],
                    raw_label="All active issues",
                    height=420,
                )
                _download_csv(visible, "overwatch_alert_center_issues.csv")

    elif source_view == "Triage Digest":
        st.subheader("DBA Triage Digest")
        if alerts.empty:
            st.info("Load alert history before preparing the operator digest.")
        else:
            from utils.alert_delivery import log_alert_digest_delivery
            from utils.alert_triage import (
                alert_escalation_candidates,
                build_alert_digest_body,
                build_alert_digest_subject,
                build_alert_digest_summary,
            )

            digest_summary = build_alert_digest_summary(alerts)
            render_shell_snapshot((
                ("Open", f"{digest_summary['open']:,}"),
                ("Critical / High", f"{digest_summary['critical_high']:,}"),
                ("Overdue", f"{digest_summary['overdue']:,}"),
                ("Due Soon", f"{digest_summary['due_soon']:,}"),
                ("Needs Route", f"{digest_summary['needs_owner']:,}"),
            ))

            digest_subject = build_alert_digest_subject(alerts, company=company, environment=environment)
            digest_body = build_alert_digest_body(
                alerts,
                company=company,
                environment=environment,
                recipient=_alert_email_target(),
                limit=10,
            )
            st.text_input("Digest email subject", value=digest_subject, key="alert_center_digest_subject")
            st.text_area("Digest email body", value=digest_body, height=340, key="alert_center_digest_body")
            with st.expander("Log digest delivery", expanded=False):
                st.caption("Use this after the email digest is sent or handed off. This records delivery status and marks included alerts as escalated.")
                with st.form("alert_center_log_digest_delivery"):
                    delivery_target = st.text_input(
                        "Delivery target",
                        value=_alert_email_target(),
                        key="alert_center_digest_target",
                    )
                    delivery_notes = st.text_area(
                        "Delivery notes",
                        key="alert_center_digest_notes",
                        placeholder="Example: Sent via Outlook to DBA on-call and platform route; INC12345 opened.",
                    )
                    submitted_delivery = st.form_submit_button("Log Digest Delivery")
                if submitted_delivery:
                    digest_alerts = alerts[_open_alert_mask(alerts)]
                    if digest_alerts.empty:
                        st.warning("No open alert rows are available to log.")
                    elif len(delivery_notes.strip()) < 10:
                        st.warning("Delivery notes are required for audit status.")
                    else:
                        try:
                            session = _alert_center_action_session("log alert digest delivery")
                            if session is None:
                                return
                            logged = log_alert_digest_delivery(
                                session,
                                digest_alerts,
                                company=company,
                                environment=environment,
                                delivery_target=delivery_target,
                                email_subject=digest_subject,
                                email_body=digest_body,
                                actor=_alert_actor(),
                                notes=delivery_notes,
                            )
                            st.success(f"Logged digest delivery for {logged:,} alert(s). Reload the Alert Center to refresh delivery state.")
                            st.session_state.pop("alert_center_data", None)
                        except Exception as exc:
                            st.error(f"Could not log digest delivery: {_format_snowflake_error(exc)}")

            candidates = alert_escalation_candidates(alerts, limit=15)
            if candidates.empty:
                st.success("No escalation candidates for this scope.")
            else:
                _render_priority_dataframe(
                    candidates,
                    title="Escalate first",
                    priority_columns=[
                        "ALERT_TS", "SLA_STATE", "ALERT_AGE_HOURS", "SEVERITY",
                        "CATEGORY", "ALERT_TYPE", "ENTITY_NAME", "OWNER",
                        "ESCALATION_TARGET", "MESSAGE", "SUGGESTED_ACTION",
                    ],
                    sort_by=["TRIAGE_PRIORITY", "ALERT_TS"],
                    ascending=[True, False],
                    raw_label="All escalation candidates",
                    height=300,
                )

            if not alerts.empty and {"CATEGORY", "SLA_STATE", "SEVERITY"}.issubset(alerts.columns):
                category_mix = (
                    alerts[_open_alert_mask(alerts)]
                    .groupby(["CATEGORY", "SLA_STATE", "SEVERITY"], dropna=False)
                    .size()
                    .reset_index(name="ALERTS")
                    .sort_values(["SLA_STATE", "SEVERITY", "ALERTS"], ascending=[True, True, False])
                )
                if not category_mix.empty:
                    _render_priority_dataframe(
                        category_mix,
                        title="Open alert mix",
                        priority_columns=["CATEGORY", "SLA_STATE", "SEVERITY", "ALERTS"],
                        sort_by=["SLA_STATE", "SEVERITY", "ALERTS"],
                        ascending=[True, True, False],
                        raw_label="All open alert mix rows",
                        height=220,
                    )

    elif source_view == "Alert History":
        render_alert_history_pane(
            alerts,
            queue,
            action_session_factory=_alert_center_action_session,
            alert_actor=_alert_actor,
            format_error=_format_snowflake_error,
        )

    _render_advanced_alert_diagnostics(company, environment)
