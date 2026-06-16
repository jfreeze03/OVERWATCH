"""Fast first-paint shell for the Alert Center route."""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_DAY_WINDOW, DEFAULT_ENVIRONMENT, ENVIRONMENT_CONFIG
from sections.shell_helpers import (
    full_workspace_requested,
    render_shell_kpi_row,
    render_shell_workflows,
    render_signal_lane_board,
)
from utils.command_board import load_or_reuse_command_board


_FULL_WORKSPACE_KEY = "_alert_center_full_workspace_requested"
_BRIEF_MODE_KEY = "_alert_center_brief_mode"
_FAST_ENTRY_VERSION_KEY = "_alert_center_shell_fast_entry_version"
_FAST_ENTRY_VERSION = 1
_COMMAND_BOARD_DATA_KEY = "alert_center_command_board_data"
_COMMAND_BOARD_SUMMARY_KEY = "alert_center_command_board_summary"
_COMMAND_BOARD_META_KEY = "alert_center_command_board_meta"
_COMMAND_BOARD_REFRESH_MARKER_KEY = "alert_center_command_board_refresh_marker"
_FULL_WORKSPACE_STATE_KEYS = (
    _COMMAND_BOARD_SUMMARY_KEY,
    "alert_center_data",
    "alert_center_annotations",
)

_WORKFLOWS = (
    {
        "VIEW": "Command Center",
        "BUTTON_LABEL": "Open Command Center",
        "MOVE": "Start with severity-ranked risk, category routes, freshness, and business impact.",
    },
    {
        "VIEW": "DBA Morning Brief",
        "BUTTON_LABEL": "Open Morning Brief",
        "MOVE": "Work overnight failures, security events, cost anomalies, and missed SLAs in order.",
    },
    {
        "VIEW": "Detection Catalog",
        "BUTTON_LABEL": "Open Detection Catalog",
        "MOVE": "Review Snowflake-native security, cost, performance, pipeline, data-quality, and optimization checks.",
    },
    {
        "VIEW": "Issue Inbox",
        "BUTTON_LABEL": "Open Issue Inbox",
        "MOVE": "Start with the combined alert and action-queue inbox for morning triage.",
    },
    {
        "VIEW": "Triage Digest",
        "BUTTON_LABEL": "Open Triage Digest",
        "MOVE": "Escalate critical, high, overdue, and route-ready alert rows first.",
    },
    {
        "VIEW": "Email Delivery",
        "BUTTON_LABEL": "Open Delivery",
        "MOVE": "Confirm which alerts are email-ready, sent, logged, or still waiting.",
    },
    {
        "VIEW": "Action Queue Routing",
        "BUTTON_LABEL": "Open Queue Routing",
        "MOVE": "Move alert telemetry into routed work and closure status.",
    },
    {
        "VIEW": "Notifications & Remediation",
        "BUTTON_LABEL": "Open Remediation",
        "MOVE": "Review notification routing and remediation checks before action.",
    },
)


def _active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def _active_environment() -> str:
    env = str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)
    return env if env in ENVIRONMENT_CONFIG else DEFAULT_ENVIRONMENT


def _window_label() -> str:
    start = st.session_state.get("global_start_date")
    end = st.session_state.get("global_end_date")
    if isinstance(start, date) and isinstance(end, date):
        days = max(1, (end - start).days + 1)
        return f"{days}d"
    return "Selected"


def _window_days() -> int:
    start = st.session_state.get("global_start_date")
    end = st.session_state.get("global_end_date")
    if isinstance(start, date) and isinstance(end, date):
        return max(1, (end - start).days + 1)
    return int(DEFAULT_DAY_WINDOW)


def _command_summary() -> dict:
    summary = st.session_state.get(_COMMAND_BOARD_SUMMARY_KEY)
    if isinstance(summary, dict) and summary.get("loaded"):
        return dict(summary)
    return {}


def _command_meta() -> dict:
    meta = st.session_state.get(_COMMAND_BOARD_META_KEY)
    return dict(meta) if isinstance(meta, dict) else {}


def _load_command_board() -> None:
    load_or_reuse_command_board(
        data_key=_COMMAND_BOARD_DATA_KEY,
        summary_key=_COMMAND_BOARD_SUMMARY_KEY,
        meta_key=_COMMAND_BOARD_META_KEY,
        refresh_marker_key=_COMMAND_BOARD_REFRESH_MARKER_KEY,
        company=_active_company(),
        environment=_active_environment(),
        days=_window_days(),
    )


def _full_workspace_requested() -> bool:
    """Keep Alert navigation lightweight; load command detail only from an explicit alert workflow."""
    _ = full_workspace_requested
    if st.session_state.get(_FULL_WORKSPACE_KEY):
        return True
    st.session_state.setdefault(_BRIEF_MODE_KEY, True)
    return False


def _apply_fast_entry_default() -> None:
    if st.session_state.get(_FAST_ENTRY_VERSION_KEY) == _FAST_ENTRY_VERSION:
        return
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FAST_ENTRY_VERSION_KEY] = _FAST_ENTRY_VERSION


def _is_loaded_frame(value: object) -> bool:
    return bool(hasattr(value, "empty") and not getattr(value, "empty", True))


def _loaded_data() -> dict:
    data = st.session_state.get("alert_center_data")
    return data if isinstance(data, dict) else {}


def _frame_count(data: dict, key: str) -> int:
    frame = data.get(key)
    if not _is_loaded_frame(frame):
        return 0
    try:
        return len(frame)
    except Exception:
        return 0


def _int_value(value: object, default: int = 0) -> int:
    try:
        return int(float(value if value is not None else default))
    except (TypeError, ValueError):
        return default


def _money(value: object) -> str:
    try:
        amount = float(value if value is not None else 0.0)
    except (TypeError, ValueError):
        amount = 0.0
    return f"${amount:,.0f}"


def _severity_count(data: dict, severities: tuple[str, ...]) -> int:
    alerts = data.get("alerts")
    if not _is_loaded_frame(alerts) or "SEVERITY" not in getattr(alerts, "columns", []):
        return 0
    try:
        severity = alerts["SEVERITY"].fillna("").astype(str).str.title()
        return int(severity.isin(list(severities)).sum())
    except Exception:
        return 0


def _open_queue_count(data: dict) -> int:
    queue = data.get("action_queue")
    if not _is_loaded_frame(queue):
        return 0
    try:
        if "STATUS" not in queue.columns:
            return len(queue)
        status = queue["STATUS"].fillna("").astype(str).str.title()
        return int((~status.isin(["Fixed", "Ignored", "Closed"])).sum())
    except Exception:
        return len(queue) if hasattr(queue, "__len__") else 0


def _category_count(data: dict, category_name: str) -> int:
    alerts = data.get("alerts")
    if not _is_loaded_frame(alerts) or "CATEGORY" not in getattr(alerts, "columns", []):
        return 0
    try:
        category = alerts["CATEGORY"].fillna("").astype(str).str.upper()
        return int(category.str.contains(category_name.upper(), regex=False).sum())
    except Exception:
        return 0


def _alert_shell_lanes(data: dict) -> tuple[dict[str, str], ...]:
    if not data:
        summary = _command_summary()
        if summary:
            critical_high = _int_value(summary.get("critical_high_alerts"))
            open_actions = _int_value(summary.get("open_actions"))
            failed_tasks = _int_value(summary.get("failed_tasks"))
            failed_queries = _int_value(summary.get("failed_queries"))
            queue_seconds = _int_value(summary.get("queue_seconds"))
            spend = _money(summary.get("current_cost_usd"))
            cortex = _money(summary.get("cortex_cost_usd"))
            return (
                {
                    "label": "Critical / high",
                    "value": f"{critical_high:,}",
                    "state": "Now",
                    "detail": "Severity-ranked alert pressure loads from the fast summary.",
                },
                {
                    "label": "Open actions",
                    "value": f"{open_actions:,}",
                    "state": "Routes",
                    "detail": "Routed work should have business impact, action, and current status.",
                },
                {
                    "label": "Pipeline reliability",
                    "value": f"{failed_tasks:,}",
                    "state": "Tasks",
                    "detail": "Task failures route to Task Graphs and the DBA morning brief.",
                },
                {
                    "label": "Performance risk",
                    "value": f"{failed_queries:,}",
                    "state": "Queries",
                    "detail": f"Queue time is {queue_seconds / 60.0:,.1f} minutes across the selected window.",
                },
                {
                    "label": "Cost / FinOps",
                    "value": spend,
                    "state": "Spend",
                    "detail": f"Top driver: {summary.get('top_cost_driver') or 'On demand'}.",
                },
                {
                    "label": "Cortex / AI",
                    "value": cortex,
                    "state": "AI",
                    "detail": "AI spend is included in alert triage because runaway usage becomes an incident.",
                },
                {
                    "label": "Source freshness",
                    "value": f"{_int_value(summary.get('freshness_sources')):,}",
                    "state": f"{_int_value(summary.get('stale_sources')):,} stale",
                    "detail": "Delayed telemetry is labeled before anyone acts on it.",
                },
                {
                    "label": "Remediation route",
                    "value": "Review gated",
                    "state": "Safe",
                    "detail": "Every fix needs current alert telemetry and audit logging.",
                },
            )
        return (
            {
                "label": "Critical / high",
                "value": "On demand",
                "state": "Refresh",
                "detail": "Severity-ranked incidents should be visible on first click.",
            },
            {
                "label": "Overdue SLA",
                "value": "On demand",
                "state": "SLA",
                "detail": "Aged unresolved alerts need escalation before they become outages.",
            },
            {
                "label": "Security risk",
                "value": "On demand",
                "state": "Security",
                "detail": "Login, grant, access, sharing, and policy risks get their own lane.",
            },
            {
                "label": "Cost / FinOps",
                "value": "On demand",
                "state": "Spend",
                "detail": "Cost anomalies and runaway spend route with savings telemetry.",
            },
            {
                "label": "Performance",
                "value": "On demand",
                "state": "Workload",
                "detail": "Queue, spill, runtime, and contention alerts are DBA-actionable.",
            },
            {
                "label": "Pipeline reliability",
                "value": "On demand",
                "state": "Tasks",
                "detail": "Task graph, load, dynamic table, and SLA alerts belong here.",
            },
            {
                "label": "Data quality",
                "value": "On demand",
                "state": "Trust",
                "detail": "Freshness, row count, null, duplicate, and schema checks are metadata-driven.",
            },
            {
                "label": "Remediation route",
                "value": "Review gated",
                "state": "Safe",
                "detail": "Every fix needs current alert telemetry and audit logging.",
            },
        )

    critical_high = _severity_count(data, ("Critical", "High"))
    warnings = _severity_count(data, ("Warning", "Medium"))
    overdue = _category_count(data, "SLA") + _category_count(data, "OVERDUE")
    security = _category_count(data, "SECURITY")
    cost = _category_count(data, "COST") + _category_count(data, "FINOPS")
    performance = _category_count(data, "PERFORMANCE") + _category_count(data, "QUERY")
    pipeline = _category_count(data, "PIPELINE") + _category_count(data, "TASK")
    quality = _category_count(data, "QUALITY") + _category_count(data, "FRESHNESS")
    return (
        {
            "label": "Critical / high",
            "value": f"{critical_high:,}",
            "state": "Now",
            "detail": f"{warnings:,} warning/medium alert(s) stay below the command lane.",
        },
        {
            "label": "Overdue SLA",
            "value": f"{overdue:,}" if overdue else "0",
            "state": "SLA",
            "detail": "SLA misses should route before lower-severity optimization work.",
        },
        {
            "label": "Security risk",
            "value": f"{security:,}",
            "state": "Security",
            "detail": "Failed logins, grants, sharing, sensitive access, and policy changes.",
        },
        {
            "label": "Cost / FinOps",
            "value": f"{cost:,}",
            "state": "Spend",
            "detail": "Cost anomalies need forecast, driver, and routed remediation status.",
        },
        {
            "label": "Performance",
            "value": f"{performance:,}",
            "state": "Workload",
            "detail": "Queue, spill, runtime, and contention alerts route to Workload Operations.",
        },
        {
            "label": "Pipeline reliability",
            "value": f"{pipeline:,}",
            "state": "Tasks",
            "detail": "Task graph failures, skipped runs, COPY issues, and late data arrivals.",
        },
        {
            "label": "Data quality",
            "value": f"{quality:,}",
            "state": "Trust",
            "detail": "Metadata-driven checks catch bad data before consumer incidents.",
        },
        {
            "label": "Remediation route",
            "value": f"{_open_queue_count(data):,} open",
            "state": "Review",
            "detail": "Only reviewed safe actions should execute; all actions log status.",
        },
    )


def _open_workspace(view: str | None = None) -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    if view:
        st.session_state["alert_center_requested_view"] = view
    st.rerun()


def _delegate_full_workspace() -> None:
    from sections import alert_center

    alert_center.render()


def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


def _render_back_to_brief_control() -> None:
    control_col, _spacer = st.columns([1.0, 4.0])
    with control_col:
        if st.button("Back to Brief", key="alert_center_shell_back_to_brief", width="stretch"):
            _return_to_brief()


def _render_metric_board() -> None:
    data = _loaded_data()
    loaded = bool(data)
    summary = _command_summary()
    st.markdown("**Alert Command Board**")
    render_signal_lane_board("Alert Command Board", _alert_shell_lanes(data), max_lanes=8)
    if not loaded:
        render_shell_kpi_row((
            ("Critical / High", f"{_int_value(summary.get('critical_high_alerts')):,}" if summary else "On demand"),
            ("Failed Queries", f"{_int_value(summary.get('failed_queries')):,}" if summary else "On demand"),
            ("Open Actions", f"{_int_value(summary.get('open_actions')):,}" if summary else "On demand"),
            ("Spend", _money(summary.get("current_cost_usd")) if summary else "On demand"),
        ))
        render_shell_kpi_row((
            ("Task Failures", f"{_int_value(summary.get('failed_tasks')):,}" if summary else "On demand"),
            ("Cortex", _money(summary.get("cortex_cost_usd")) if summary else "On demand"),
            ("Fresh Sources", f"{_int_value(summary.get('freshness_sources')):,}" if summary else "On demand"),
            ("Automation", "Review gated"),
        ))
        return

    render_shell_kpi_row((
        ("Critical / High", f"{_severity_count(data, ('Critical', 'High')):,}"),
        ("Warnings", f"{_severity_count(data, ('Warning', 'Medium')):,}"),
        ("Open Actions", f"{_open_queue_count(data):,}"),
        ("Delivery Routes", f"{_frame_count(data, 'delivery_log'):,}"),
    ))
    render_shell_kpi_row((
        ("Delivery Ready", f"{_frame_count(data, 'delivery_log'):,}"),
        ("Automation Health", "Loaded" if _is_loaded_frame(data.get("automation_health")) else "On demand"),
        ("Rules", f"{_frame_count(data, 'rules'):,}"),
        ("Freshness", "Loaded" if data.get("_freshness_meta") else "Loaded"),
    ))


def _render_lifecycle_board() -> None:
    data = _loaded_data()
    annotations = st.session_state.get("alert_center_annotations")
    acknowledged = _frame_count(data, "acknowledgements")
    remediation = _frame_count(data, "remediation_log")
    notification = _frame_count(data, "notification_log")
    comments = _frame_count(data, "comments") if isinstance(data, dict) else 0
    if not comments and _is_loaded_frame(annotations):
        try:
            comments = len(annotations)
        except Exception:
            comments = 0
    st.markdown("**Alert Lifecycle Board**")
    render_signal_lane_board(
        "Lifecycle Control Loop",
        (
            {
                "label": "Detect",
                "value": "Alert event",
                "state": "Signal",
                "detail": "Severity, category, source freshness, assignment, and business impact are captured once.",
            },
            {
                "label": "Deduplicate",
                "value": "Alert key",
                "state": "Noise control",
                "detail": "Recurring symptoms roll into the same key before they become a wall of alerts.",
            },
            {
                "label": "Acknowledge",
                "value": "Ack",
                "state": "Assigned",
                "detail": "Ack rows prove who took responsibility and when escalation can pause.",
            },
            {
                "label": "Suppress",
                "value": "Windowed",
                "state": "Temporary",
                "detail": "Suppression must expire and keep rationale; permanent hiding is not a control.",
            },
            {
                "label": "Remediate",
                "value": "Remediation log",
                "state": "Review",
                "detail": "Review mode, before/after state, and rollback are tracked.",
            },
            {
                "label": "Notify",
                "value": "Notification log",
                "state": "Routed",
                "detail": "Email/webhook-ready routing is recorded even when integrations are not enabled.",
            },
            {
                "label": "Resolve",
                "value": "Closure status",
                "state": "Verified",
                "detail": "Resolved means the condition cleared, not just clicked away.",
            },
            {
                "label": "Learn",
                "value": "Threshold tuning",
                "state": "Improve",
                "detail": "Repeated false positives should update ALERT_THRESHOLDS or the detection query.",
            },
        ),
        max_lanes=8,
    )
    render_shell_kpi_row((
        ("Acknowledge", f"{acknowledged:,}" if acknowledged else "Table ready"),
        ("Suppress", "Window table"),
        ("Resolve", "Closure status"),
        ("Comments", f"{comments:,}" if comments else "Audit-ready"),
    ))
    render_shell_kpi_row((
        ("Notify", f"{notification:,}" if notification else "Integration-ready"),
        ("Remediate", f"{remediation:,}" if remediation else "Review gated"),
        ("Routing", f"{_frame_count(data, 'rules'):,}" if data else "Rules"),
        ("Dedup", "Alert key"),
    ))


def _render_workflow_launchpad() -> None:
    def _open(row):
        _open_workspace(str(row["VIEW"]))

    render_shell_workflows(
        "Alert Command Workflows",
        _WORKFLOWS,
        label_key="VIEW",
        key_prefix="alert_center_shell",
        on_open=_open,
    )


def render() -> None:
    _apply_fast_entry_default()
    if _full_workspace_requested():
        _render_back_to_brief_control()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("alert_center_shell_seen_at", datetime.now().isoformat(timespec="seconds"))
    _load_command_board()
    _render_metric_board()
    _render_lifecycle_board()
    _render_workflow_launchpad()
