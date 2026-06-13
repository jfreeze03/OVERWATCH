"""Fast first-paint shell for the Executive Landing route."""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, DEFAULTS, DEFAULT_DAY_WINDOW, DAY_WINDOW_OPTIONS, ENVIRONMENT_CONFIG
from sections.shell_helpers import action_state_label, evidence_caption, evidence_label, evidence_loaded, render_shell_snapshot, render_shell_workflows, scope_label


_FULL_WORKSPACE_KEY = "_executive_landing_full_workspace_requested"
_BRIEF_MODE_KEY = "_executive_landing_brief_mode"
_FULL_WORKSPACE_STATE_KEYS = ("executive_landing_snapshot",)

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
    if st.session_state.get(_BRIEF_MODE_KEY):
        return False
    if st.session_state.get(_FULL_WORKSPACE_KEY):
        return True
    return False


def _open_workspace() -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    st.rerun()


def _navigate(section: str, state_updates: dict[str, str] | None = None) -> None:
    st.session_state["nav_section"] = section
    for key, value in (state_updates or {}).items():
        st.session_state[key] = value
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


def _render_action_brief() -> None:
    snapshot_help = evidence_caption(
        st.session_state,
        _FULL_WORKSPACE_STATE_KEYS,
        "The shell stays zero-query; PowerPoint evidence and live source health load only on demand.",
    )
    with st.container(border=True):
        label_col, detail_col, action_col = st.columns([1.0, 3.0, 1.8])
        with label_col:
            st.markdown("**Action Brief**")
            st.caption(action_state_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS))
        with detail_col:
            st.markdown("**Open Executive Snapshot when leaders need a board-ready status package.**")
        with action_col:
            if st.button(
                "Open Executive Snapshot",
                key="executive_landing_shell_open",
                help=snapshot_help,
                type="primary",
                width="stretch",
            ):
                _open_workspace()


def _render_operating_snapshot() -> None:
    metrics = (
        ("Scope", scope_label(_active_company(), _active_environment())),
        ("Window", _window_label()),
        ("Rate", f"${_credit_price():.2f}"),
        ("Evidence", evidence_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS)),
    )
    st.markdown("**Operating Snapshot**")
    render_shell_snapshot(metrics)


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
    _render_action_brief()
    _render_operating_snapshot()
    _render_workflow_launchpad()
