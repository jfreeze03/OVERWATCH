"""Fast first-paint shell for the Cost & Contract route."""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, DEFAULTS, DEFAULT_DAY_WINDOW, DAY_WINDOW_OPTIONS, ENVIRONMENT_CONFIG
from sections.shell_helpers import action_state_label, evidence_caption, evidence_label, evidence_loaded, render_shell_snapshot, render_shell_workflows, scope_label


_FULL_WORKSPACE_KEY = "_cost_contract_full_workspace_requested"
_BRIEF_MODE_KEY = "_cost_contract_brief_mode"
_DETAIL_WORKFLOW_KEY = "_cost_contract_detail_workflow"
_COST_SPLASH_KEY = "cost_contract_splash"
_FULL_WORKSPACE_STATE_KEYS = (
    _COST_SPLASH_KEY,
    "cost_contract_cockpit",
    "cost_contract_run_rate",
    "cost_contract_queue",
    "cost_contract_verification_health",
    "cost_contract_attribution_reconciliation",
    "cost_contract_service_lens",
    "cost_contract_budget_command_center",
    "cost_contract_spike_root_cause",
    "cost_contract_change_cost_correlation",
)

_WORKFLOWS = (
    {
        "WORKFLOW": "Explain bill / attribution / contract",
        "BUTTON_LABEL": "Open Cost Overview",
        "MOVE": "Start with bill movement, warehouse ranking, service spend, Cortex, and contract pace.",
    },
    {
        "WORKFLOW": "FinOps Control Center",
        "BUTTON_LABEL": "Open FinOps",
        "MOVE": "Review governance, resource monitors, verified savings, and formula trust.",
    },
    {
        "WORKFLOW": "AI and Cortex spend",
        "BUTTON_LABEL": "Open Cortex Spend",
        "MOVE": "Review Cortex usage, model spend, users, and runaway AI cost signals.",
    },
    {
        "WORKFLOW": "Budget governance",
        "BUTTON_LABEL": "Open Budgets",
        "MOVE": "Check native Snowflake budgets, AI quota patterns, and budget actions.",
    },
    {
        "WORKFLOW": "Recommendations and action queue",
        "BUTTON_LABEL": "Open Recommendations",
        "MOVE": "Assign owned cost fixes with proof, savings, severity, and verification.",
    },
    {
        "WORKFLOW": "Snowflake value log",
        "BUTTON_LABEL": "Open Value Log",
        "MOVE": "Show DBA savings, avoided spend, and service-improvement evidence.",
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
    selected_days = st.session_state.get("cost_contract_cockpit_window", DEFAULT_DAY_WINDOW)
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


def _open_workspace(workflow: str | None = None, *, open_detail: bool = False) -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    if workflow:
        st.session_state["cost_contract_workflow"] = workflow
        if open_detail:
            st.session_state[_DETAIL_WORKFLOW_KEY] = workflow
    st.rerun()


def _delegate_full_workspace() -> None:
    from sections import cost_contract

    cost_contract.render()


def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


def _render_back_to_brief_control() -> None:
    control_col, _spacer = st.columns([1.0, 4.0])
    with control_col:
        if st.button("Back to Brief", key="cost_contract_shell_back_to_brief", width="stretch"):
            _return_to_brief()


def _render_action_brief() -> None:
    with st.container(border=True):
        label_col, detail_col, action_col = st.columns([1.0, 3.0, 1.8])
        with label_col:
            st.markdown("**Action Brief**")
            st.caption(action_state_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS))
        with detail_col:
            st.markdown("**Open Cost Overview when bill movement, Cortex spend, or contract risk needs proof.**")
            st.caption(
                evidence_caption(
                    st.session_state,
                    _FULL_WORKSPACE_STATE_KEYS,
                    "The shell stays zero-query; the full cost splash and proof workspace load on demand.",
                )
            )
        with action_col:
            if st.button("Open Cost Overview", key="cost_contract_shell_open", type="primary", width="stretch"):
                _open_workspace("Explain bill / attribution / contract")


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
        workflow = str(row["WORKFLOW"])
        _open_workspace(workflow, open_detail=workflow != "Explain bill / attribution / contract")

    render_shell_workflows(
        "Cost Investigation Workflows",
        _WORKFLOWS,
        label_key="WORKFLOW",
        key_prefix="cost_contract_shell",
        on_open=_open,
    )


def render() -> None:
    if _full_workspace_requested():
        _render_back_to_brief_control()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("cost_contract_shell_seen_at", datetime.now().isoformat(timespec="seconds"))
    _render_action_brief()
    _render_operating_snapshot()
    _render_workflow_launchpad()
