# sections/alert_center.py - single alert inbox and email-first alert operations
from __future__ import annotations

import streamlit as st

from config import DAY_WINDOW_OPTIONS, DEFAULT_ALERT_EMAIL, DEFAULT_DAY_WINDOW
from sections.shell_helpers import (
    consume_section_autoload_request,
    render_first_paint_summary_shell,
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
from sections.alert_center_admin_delivery_view import (
    _render_alert_action_queue_routing,
    _render_alert_email_delivery_status,
    _render_alert_notification_remediation,
    render_alert_delivery_automation_pane,
)
from sections.alert_center_admin_suppression_view import (
    ANNOTATION_TABLE,
    _annotation_table_name,
    render_suppression_windows_pane,
)
from sections.alert_center_diagnostics_view import (
    _render_advanced_alert_diagnostics,
    _render_alert_action_workflows,
    _render_alert_change_context,
    _render_alert_command_findings,
    _render_operational_ownership_coverage,
    _render_operational_risk_score_explanation,
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


def _summary_count_label(summary: dict, *keys: str) -> tuple[str, int | None]:
    for key in keys:
        value = summary.get(key)
        if value in (None, ""):
            continue
        try:
            count = int(float(str(value).replace(",", "")))
            return f"{count:,}", count
        except (TypeError, ValueError):
            return str(value), None
    return "On demand", None


def _alert_center_cached_summary_for_scope(
    summary: object,
    *,
    source_view: str,
    company: str,
    environment: str,
    days: int,
    limit: int,
) -> dict | None:
    if not isinstance(summary, dict):
        return None
    expected = (
        ("source_view", source_view), ("company", company), ("environment", environment), ("days", int(days)), ("limit", int(limit)),
    )
    return summary if all(key not in summary or summary.get(key) == value for key, value in expected) else None


def _alert_center_first_paint_summary(
    data: dict | None,
    source_view: str,
    *,
    cached_summary: dict | None = None,
) -> dict[str, str]:
    """Summarize already-loaded Alert Center facts without reading Snowflake."""
    if not isinstance(data, dict):
        if isinstance(cached_summary, dict):
            critical_high, critical_count = _summary_count_label(cached_summary, "critical_high", "critical_high_count")
            overdue, overdue_count = _summary_count_label(cached_summary, "overdue", "overdue_count")
            open_queue, queue_count = _summary_count_label(cached_summary, "open_queue", "open_queue_count")
            top_lane = str(cached_summary.get("top_lane") or "").strip()
            if not top_lane:
                top_lane = next(
                    (label for label, count in (
                        ("Critical / high", critical_count),
                        ("Overdue SLA", overdue_count),
                        ("Action queue", queue_count),
                    ) if count),
                    "Operating lanes",
                )
            return {
                "critical_high": critical_high,
                "overdue": overdue,
                "open_queue": open_queue,
                "top_lane": top_lane,
                "freshness": str(cached_summary.get("freshness") or cached_summary.get("loaded_at") or "Cached summary"),
            }
        return dict(critical_high="On demand", overdue="On demand", open_queue="On demand", top_lane="Selected view", freshness="Not loaded")
    meta = _alert_center_loaded_meta(data, source_view)
    freshness = str(meta.get("loaded_at") or data.get("loaded_at") or "Loaded previously")
    pd = _pd()
    alerts = data.get("alerts") if isinstance(data.get("alerts"), pd.DataFrame) else pd.DataFrame()
    queue = data.get("action_queue") if isinstance(data.get("action_queue"), pd.DataFrame) else pd.DataFrame()
    open_alerts = _open_alert_mask(alerts) if not alerts.empty else pd.Series(dtype=bool)
    severity = alerts.get("SEVERITY", pd.Series(index=alerts.index, dtype=str)).fillna("").astype(str) if not alerts.empty else pd.Series(dtype=str)
    critical_high = int((severity.isin(["Critical", "High"]) & open_alerts).sum()) if not alerts.empty else 0
    overdue = 0
    if not alerts.empty and "SLA_STATE" in alerts.columns:
        overdue = int((alerts["SLA_STATE"].fillna("").astype(str).eq("Overdue") & open_alerts).sum())
    open_queue = 0
    if not queue.empty and "STATUS" in queue.columns:
        open_queue = int((~queue["STATUS"].fillna("New").astype(str).str.title().isin(["Fixed", "Ignored"])).sum())
    top_lane = next(
        (label for label, count in (
            ("Critical / high", critical_high),
            ("Overdue SLA", overdue),
            ("Action queue", open_queue),
        ) if count),
        "Operating lanes",
    )
    return {
        "critical_high": f"{critical_high:,}",
        "overdue": f"{overdue:,}",
        "open_queue": f"{open_queue:,}",
        "top_lane": top_lane,
        "freshness": freshness,
    }


def _render_alert_center_first_paint_shell(
    *,
    source_view: str,
    company: str,
    environment: str,
    days: int,
    limit: int,
    required_sources: set[str],
    data: dict | None = None,
    cached_summary: dict | None = None,
    state: str = "Load on demand",
    note: str = "",
) -> None:
    """Render a useful Alert Center shell while detailed rows remain behind Load."""
    summary = _alert_center_first_paint_summary(data, source_view, cached_summary=cached_summary)
    source_summary = _alert_center_source_summary(required_sources)
    render_first_paint_summary_shell(  # First paint does not query Snowflake; cached/session facts only.
        state=state,
        headline=f"{source_view} is ready for explicit load.",
        detail=note or f"Load {source_view} reads {source_summary} for {company} / {environment}.",
        metrics=(
            ("Active View", source_view),
            ("Critical / High", summary["critical_high"]),
            ("Overdue", summary["overdue"]),
            ("Open Queue", summary["open_queue"]),
        ),
        snapshot=(
            ("Inputs", source_summary),
            ("Window", f"{int(days)} days / {int(limit)} rows"),
            ("Top Lane", summary["top_lane"]),
            ("Freshness", summary["freshness"]),
        ),
    )
    loaded_for_summary = isinstance(data, dict)
    _render_alert_command_lane_board(
        _alert_command_lanes(
            active_view=source_view,
            required_sources=required_sources,
            alerts=data.get("alerts") if loaded_for_summary else None,
            queue=data.get("action_queue") if loaded_for_summary else None,
            issues=data.get("issues") if loaded_for_summary else None,
            delivery_log=data.get("delivery_log") if loaded_for_summary else None,
            loaded=loaded_for_summary,
        )
    )
    st.info(f"Use {cta_label} for detailed Alert Center rows. First paint does not query Snowflake.")


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


def _render_alert_settings_admin_pane(source_view: str = "Delivery & Automation", **kwargs) -> None:
    if source_view == "Suppression Windows":
        _render_annotations()
    elif source_view == "Detection Catalog":
        _render_alert_detection_catalog()
    elif source_view == "Delivery & Automation":
        render_alert_delivery_automation_pane(**kwargs)


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
    "Delivery & Automation": render_alert_delivery_automation_pane,
    "Suppression Windows": render_suppression_windows_pane,
}


def _render_admin_alert_center_pane(source_view: str) -> None:
    renderer = ALERT_CENTER_ADMIN_RENDERERS.get(source_view)
    if source_view == "Suppression Windows" and renderer is not None:
        renderer(
            action_session_factory=_alert_center_action_session,
            format_error=_format_snowflake_error,
        )
    elif source_view == "Detection Catalog" and renderer is not None:
        renderer(
            action_session_factory=_alert_center_action_session,
            format_error=_format_snowflake_error,
            threshold_rows_loader=_alert_threshold_tuning_rows,
            operations_rows_loader=lambda native_registry: _alert_operations_review_rows(
                native_registry=native_registry,
            ),
        )


def _render_loaded_alert_center_pane(
    source_view: str,
    alerts: pd.DataFrame,
    queue: pd.DataFrame,
    delivery_log: pd.DataFrame,
    rules: pd.DataFrame,
    company: str,
    native_registry: pd.DataFrame,
    remediation_policy: pd.DataFrame,
    remediation_dry_run: pd.DataFrame,
    *,
    renderers: dict[str, object] | None = None,
) -> bool:
    renderers = renderers or ALERT_CENTER_RENDERERS
    if source_view == ALERT_CENTER_DEFAULT_VIEW:
        renderers[source_view](alerts, queue, delivery_log, rules)
        return True
    if source_view == "Cost Alerts":
        renderers[source_view](alerts, queue, rules)
        return True
    if source_view == "Reliability Alerts":
        renderers[source_view](alerts, queue, rules)
        return True
    if source_view == "Security Alerts":
        renderers[source_view](alerts, queue, rules)
        return True
    if source_view == "Alert History":
        renderers[source_view](
            alerts,
            queue,
            action_session_factory=_alert_center_action_session,
            alert_actor=_alert_actor,
            format_error=_format_snowflake_error,
        )
        return True
    if source_view == "Delivery & Automation":
        ALERT_CENTER_ADMIN_RENDERERS[source_view](
            alerts,
            queue,
            delivery_log,
            rules,
            company,
            native_registry=native_registry,
            remediation_policy=remediation_policy,
            remediation_dry_run=remediation_dry_run,
            action_session_factory=_alert_center_action_session,
            alert_actor=_alert_actor,
            format_error=_format_snowflake_error,
            email_target=_alert_email_target,
            email_target_label=_alert_email_target_label,
        )
        return True
    return False


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
            compact_details=True,
            collapse_after=1,
            collapsed_label="More alert admin tools",
        )

    required_sources = _alert_center_sources_for_view(source_view)

    if source_view in {"Suppression Windows", "Detection Catalog"}:
        _render_admin_alert_center_pane(source_view)
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
    cached_summary = _alert_center_cached_summary_for_scope(
        st.session_state.get("alert_center_cached_summary"),
        source_view=source_view,
        company=company,
        environment=environment,
        days=int(days),
        limit=int(limit),
    )
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
        _render_alert_center_first_paint_shell(
            source_view=source_view,
            company=company,
            environment=environment,
            days=int(days),
            limit=int(limit),
            required_sources=required_sources,
            cached_summary=cached_summary,
        )
        defer_source_note(f"Inputs on load: {_alert_center_source_summary(required_sources)}")
        _render_advanced_alert_diagnostics(company, environment)
        return

    loaded_scope = st.session_state.get("alert_center_scope")
    if loaded_scope != expected_scope:
        _render_alert_center_first_paint_shell(
            source_view=source_view,
            company=company,
            environment=environment,
            days=int(days),
            limit=int(limit),
            required_sources=required_sources,
            data=data,
            cached_summary=cached_summary,
            state="Scope changed",
            note="Company, environment, or window changed after this load. Reload before triaging alerts.",
        )
        defer_source_note(f"Loaded scope: {loaded_scope or 'none'} | Current scope: {expected_scope}")
        _render_advanced_alert_diagnostics(company, environment)
        return
    loaded_sources = set(data.get("_loaded_sources") or [])
    missing_sources = sorted(required_sources - loaded_sources)
    if missing_sources:
        _render_alert_center_first_paint_shell(
            source_view=source_view,
            company=company,
            environment=environment,
            days=int(days),
            limit=int(limit),
            required_sources=required_sources,
            data=data,
            cached_summary=cached_summary,
            state="Inputs needed",
            note=f"Load {source_view} to fetch missing input(s): {_alert_center_source_summary(set(missing_sources))}.",
        )
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
    loaded_summary = _alert_center_first_paint_summary(data, source_view)
    st.session_state["alert_center_cached_summary"] = {
        **loaded_summary,
        "source_view": source_view,
        "company": company,
        "environment": environment,
        "days": int(days),
        "limit": int(limit),
    }

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

    _render_loaded_alert_center_pane(
        source_view,
        alerts,
        queue,
        delivery_log,
        rules,
        company,
        native_registry,
        remediation_policy,
        remediation_dry_run,
    )

    _render_advanced_alert_diagnostics(company, environment)
