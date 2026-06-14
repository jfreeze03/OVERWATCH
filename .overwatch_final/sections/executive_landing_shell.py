"""Fast first-paint shell for the Executive Landing route."""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, DEFAULTS, DEFAULT_DAY_WINDOW, DAY_WINDOW_OPTIONS, ENVIRONMENT_CONFIG
from sections.navigation import apply_navigation_state
from sections.shell_helpers import (
    action_state_label,
    evidence_caption,
    evidence_loaded,
    full_workspace_requested,
    render_setup_health_board,
    render_shell_kpi_row,
    render_shell_status_strip,
    render_shell_workflows,
    render_signal_lane_board,
)


_FULL_WORKSPACE_KEY = "_executive_landing_full_workspace_requested"
_BRIEF_MODE_KEY = "_executive_landing_brief_mode"
_FULL_WORKSPACE_STATE_KEYS = ("executive_landing_snapshot",)
_PLATFORM_SUMMARY_KEY = "executive_landing_platform_summary"

_SECTION_WORKSPACE_KEYS = {
    "Alert Center": ("_alert_center_full_workspace_requested", "_alert_center_brief_mode"),
    "Cost & Contract": ("_cost_contract_full_workspace_requested", "_cost_contract_brief_mode"),
    "DBA Control Room": ("_dba_control_room_full_workspace_requested", "_dba_control_room_brief_mode"),
    "Change & Drift": ("_change_drift_full_workspace_requested", "_change_drift_brief_mode"),
}

_WORKFLOWS = (
    {
        "WORKFLOW": "Executive snapshot",
        "BUTTON_LABEL": "Open Snapshot",
        "MOVE": "Load leadership-ready risk, cost movement, action closure, and deployment trust evidence.",
    },
    {
        "WORKFLOW": "PowerPoint export",
        "BUTTON_LABEL": "Open PowerPoint",
        "MOVE": "Prepare slide bullets, KPI rows, chart data, and a downloadable PowerPoint deck.",
    },
    {
        "WORKFLOW": "Alert automation",
        "BUTTON_LABEL": "Open Alerts",
        "MOVE": "Jump to alert delivery readiness and owner escalation proof before leadership review.",
    },
    {
        "WORKFLOW": "FinOps controls",
        "BUTTON_LABEL": "Open FinOps",
        "MOVE": "Open cost governance, verified savings, contract pacing, and budget-control evidence.",
    },
    {
        "WORKFLOW": "DBA queue",
        "BUTTON_LABEL": "Open DBA Queue",
        "MOVE": "Review owned action items, closure status, and verification evidence.",
    },
    {
        "WORKFLOW": "Setup status",
        "BUTTON_LABEL": "Open Setup",
        "MOVE": "Open deployment trust and setup blockers that may affect production readiness.",
    },
)


def _active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def _active_environment() -> str:
    env = str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)
    return env if env in ENVIRONMENT_CONFIG else DEFAULT_ENVIRONMENT


def _credit_price() -> float:
    try:
        return float(st.session_state.get("credit_price", DEFAULTS.get("credit_price", 3.68)) or 3.68)
    except (TypeError, ValueError):
        return 3.68


def _int_label(value: object, default: int = 0) -> str:
    try:
        return f"{int(round(float(value)))}"
    except (TypeError, ValueError):
        return f"{default}"


def _float_value(value: object, default: float = 0.0) -> float:
    try:
        number = float(value if value is not None else default)
        return default if number != number else number
    except (TypeError, ValueError):
        return default


def _window_label() -> str:
    selected_days = st.session_state.get("executive_landing_window", DEFAULT_DAY_WINDOW)
    try:
        days = int(selected_days)
    except (TypeError, ValueError):
        days = int(DEFAULT_DAY_WINDOW)
    if days in DAY_WINDOW_OPTIONS:
        return f"{days}d"
    start = st.session_state.get("global_start_date")
    end = st.session_state.get("global_end_date")
    if isinstance(start, date) and isinstance(end, date):
        return f"{max(1, (end - start).days + 1)}d"
    return f"{int(DEFAULT_DAY_WINDOW)}d"


def _full_workspace_requested() -> bool:
    return full_workspace_requested(st.session_state, _FULL_WORKSPACE_KEY, _BRIEF_MODE_KEY)


def _open_workspace() -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    st.rerun()


def _open_target_workspace(section: str) -> None:
    workspace_keys = _SECTION_WORKSPACE_KEYS.get(section)
    if not workspace_keys:
        return
    workspace_key, brief_key = workspace_keys
    st.session_state[workspace_key] = True
    st.session_state[brief_key] = False


def _navigate(section: str, state_updates: dict[str, str] | None = None, *, open_workspace: bool = True) -> None:
    section = apply_navigation_state(section)
    for key, value in (state_updates or {}).items():
        st.session_state[key] = value
    if open_workspace:
        _open_target_workspace(section)
    st.rerun()


def _open_workflow(workflow: str) -> None:
    if workflow in {"Executive snapshot", "PowerPoint export"}:
        _open_workspace()
        return
    if workflow == "Alert automation":
        _navigate("Alert Center", {"alert_center_requested_view": "Automation Readiness"})
        return
    if workflow == "FinOps controls":
        _navigate(
            "Cost & Contract",
            {
                "cost_contract_workflow": "FinOps Control Center",
                "_cost_contract_detail_workflow": "FinOps Control Center",
                "_cost_contract_pending_detail_workflow": "FinOps Control Center",
            },
        )
        return
    if workflow == "DBA queue":
        _navigate("DBA Control Room", {"dba_control_room_active_view": "Operations Board"})
        return
    if workflow == "Setup status":
        _navigate(
            "Change & Drift",
            {
                "change_drift_requested_view": "Change Workflows",
                "change_drift_requested_workflow": "Controlled DBA actions",
                "change_drift_workflow": "Controlled DBA actions",
                "dba_tools_focus": "Cost",
                "dba_tools_group_selector": "Cost & Setup",
                "dba_tools_tool_selector_Cost & Setup": "Setup Status",
            },
        )


def _delegate_full_workspace() -> None:
    from sections import executive_landing

    executive_landing.render()


def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


def _render_back_to_brief_control() -> None:
    control_col, _spacer = st.columns([1.0, 4.0])
    with control_col:
        if st.button("Back to Brief", key="executive_landing_shell_back_to_brief", width="stretch"):
            _return_to_brief()


def _render_status_strip() -> None:
    detail = evidence_caption(
        st.session_state,
        _FULL_WORKSPACE_STATE_KEYS,
        "Leadership snapshot, PowerPoint export, alert automation, FinOps, DBA queue, and setup proof open from the workflow grid.",
    )
    render_shell_status_strip(
        state=action_state_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS),
        headline="Executive command view: platform score, risk posture, FinOps, alerts, and DBA queue.",
        detail=detail,
    )


def _render_platform_score_preview() -> None:
    summary = st.session_state.get(_PLATFORM_SUMMARY_KEY)
    has_summary = isinstance(summary, dict) and evidence_loaded(st.session_state, _FULL_WORKSPACE_STATE_KEYS)
    if has_summary:
        cap_value = _int_label(summary.get("score_cap"), 100)
        cap_label = "None" if cap_value == "100" else f"{cap_value}/100"
        metrics = (
            ("Score", f"{_int_label(summary.get('score'))}/100"),
            ("State", str(summary.get("state") or "Review")),
            ("Raw", f"{_int_label(summary.get('raw_score'))}/100"),
            ("Cap", cap_label),
        )
    else:
        metrics = (
            ("Score", "Load snapshot"),
            ("State", "Evidence gated"),
            ("Drivers", "Cost / Alerts / Actions / Deploy"),
            ("Cap", "Source health"),
        )
    st.markdown("**Platform Operating Score**")
    render_shell_kpi_row(metrics)


def _render_kpi_row() -> None:
    _render_platform_score_preview()


def _render_command_wall_preview() -> None:
    summary = st.session_state.get(_PLATFORM_SUMMARY_KEY)
    has_summary = isinstance(summary, dict) and evidence_loaded(st.session_state, _FULL_WORKSPACE_STATE_KEYS)
    if has_summary:
        metrics = (
            ("Cost", f"${_float_value(summary.get('current_credits')) * _credit_price():,.0f}"),
            ("Alerts", _int_label(summary.get("critical_high_alerts"))),
            ("Actions", _int_label(summary.get("open_actions"))),
            ("Deploy Risk", _int_label(summary.get("migration_blockers"))),
        )
    else:
        metrics = (
            ("Cost", "Board refresh"),
            ("Alerts", "Board refresh"),
            ("Actions", "Board refresh"),
            ("Deploy Risk", "Board refresh"),
        )
    st.markdown("**Executive Command Wall**")
    render_shell_kpi_row(metrics)
    render_setup_health_board(
        "Executive Mart Health",
        (
            ("Executive mart", "MART_EXECUTIVE_OBSERVABILITY"),
            ("Cost facts", "FACT_COST_DAILY"),
            ("Cortex facts", "FACT_CORTEX_DAILY"),
            ("Alert facts", "ALERT_EVENTS"),
        ),
        cadence="60 min mart refresh",
        fallback="No live ACCOUNT_USAGE scan on first paint",
        owner="DBA / FinOps",
    )


def _executive_shell_lanes() -> tuple[dict[str, str], ...]:
    summary = st.session_state.get(_PLATFORM_SUMMARY_KEY)
    has_summary = isinstance(summary, dict) and evidence_loaded(st.session_state, _FULL_WORKSPACE_STATE_KEYS)
    if not has_summary:
        return (
            {
                "label": "Credits used / dollars",
                "value": "Not loaded",
                "state": "Refresh",
                "detail": "MART_EXECUTIVE_OBSERVABILITY feeds the first-paint spend board.",
            },
            {
                "label": "Cortex dollars",
                "value": "Not loaded",
                "state": "Refresh",
                "detail": "FACT_CORTEX_DAILY keeps AI spend separate from warehouse compute.",
            },
            {
                "label": "Alert pressure",
                "value": "Not loaded",
                "state": "Refresh",
                "detail": "Critical/high alerts and open owner actions drive the risk score.",
            },
            {
                "label": "DBA queue",
                "value": "Not loaded",
                "state": "Refresh",
                "detail": "Morning actions, failed tasks, source health, and release blockers.",
            },
            {
                "label": "Warehouse pressure",
                "value": "Not loaded",
                "state": "Refresh",
                "detail": "Queue, runtime, spillage, and saturation roll into the pressure board.",
            },
            {
                "label": "Contract burn",
                "value": "Not loaded",
                "state": "Refresh",
                "detail": "Run-rate and forecast facts power the executive cost story.",
            },
            {
                "label": "Reliability",
                "value": "Not loaded",
                "state": "Refresh",
                "detail": "Task failures, late-risk, and incident handoff become leader-visible.",
            },
            {
                "label": "Setup trust",
                "value": "Not loaded",
                "state": "Refresh",
                "detail": "Source freshness and deployment blockers cap the platform score.",
            },
        )

    score = _int_label(summary.get("score"))
    current_spend = _float_value(summary.get("current_credits")) * _credit_price()
    prior_spend = _float_value(summary.get("prior_credits")) * _credit_price()
    delta = current_spend - prior_spend
    critical_high = _int_label(summary.get("critical_high_alerts"))
    open_actions = _int_label(summary.get("open_actions"))
    high_actions = _int_label(summary.get("high_actions"))
    deploy_blockers = _int_label(summary.get("migration_blockers"))
    state = str(summary.get("state") or "Review")
    return (
        {
            "label": "Platform score",
            "value": f"{score}/100",
            "state": state,
            "detail": str(summary.get("cap_reason") or "Cost, alerts, actions, and setup trust are scored together."),
        },
        {
            "label": "Credits used / dollars",
            "value": f"${current_spend:,.0f}",
            "state": _window_label(),
            "detail": f"Compute credits converted at ${_credit_price():.2f}/credit.",
        },
        {
            "label": "Spend movement",
            "value": f"{'+' if delta >= 0 else '-'}${abs(delta):,.0f}",
            "state": "Delta",
            "detail": "Movement versus the prior comparison window.",
        },
        {
            "label": "Alert pressure",
            "value": f"{critical_high} critical/high",
            "state": "Risk",
            "detail": f"{open_actions} open owner actions need routing or closure proof.",
        },
        {
            "label": "DBA queue",
            "value": f"{open_actions} open",
            "state": "Actions",
            "detail": f"{high_actions} high-priority actions are leadership-visible.",
        },
        {
            "label": "Deploy trust",
            "value": f"{deploy_blockers} blocker(s)",
            "state": "Setup",
            "detail": "Setup and migration blockers cap the score until cleared.",
        },
        {
            "label": "Contract burn",
            "value": "Cost board",
            "state": "Linked",
            "detail": "Open Cost & Contract for forecast, budget, and verified value proof.",
        },
        {
            "label": "Workload pressure",
            "value": "Workload board",
            "state": "Linked",
            "detail": "Runtime, queue, spillage, and task status live in Workload Operations.",
        },
    )


def _render_executive_summary_grid() -> None:
    render_signal_lane_board("Executive Summary Grid", _executive_shell_lanes(), max_lanes=8)


def _render_workflow_launchpad() -> None:
    def _open(row):
        _open_workflow(str(row["WORKFLOW"]))

    render_shell_workflows(
        "Executive Briefing Workflows",
        _WORKFLOWS,
        label_key="WORKFLOW",
        key_prefix="executive_landing_shell",
        on_open=_open,
    )


def render() -> None:
    if _full_workspace_requested():
        _render_back_to_brief_control()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("executive_landing_shell_seen_at", datetime.now().isoformat(timespec="seconds"))
    _render_status_strip()
    _render_kpi_row()
    _render_command_wall_preview()
    _render_executive_summary_grid()
    _render_workflow_launchpad()
