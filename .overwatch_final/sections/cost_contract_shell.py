"""Fast first-paint shell for the Cost & Contract route."""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, DEFAULTS, DEFAULT_DAY_WINDOW, DAY_WINDOW_OPTIONS, ENVIRONMENT_CONFIG
from sections.shell_helpers import action_state_label, evidence_caption, evidence_label, evidence_loaded, full_workspace_requested, render_shell_kpi_row, render_shell_status_strip, render_shell_workflows, scope_label


_FULL_WORKSPACE_KEY = "_cost_contract_full_workspace_requested"
_BRIEF_MODE_KEY = "_cost_contract_brief_mode"
_FAST_ENTRY_VERSION_KEY = "_cost_contract_shell_fast_entry_version"
_FAST_ENTRY_VERSION = 1
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
        "WORKFLOW": "Storage cost and retention",
        "BUTTON_LABEL": "Open Storage Cost",
        "MOVE": "Review database, failsafe, stage, and table storage cost evidence from Snowflake storage usage views.",
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
    """Keep Cost navigation lightweight; open heavy proof only from a selected cost workflow."""
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


def _open_workspace(workflow: str | None = None) -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    if workflow:
        st.session_state["cost_contract_workflow"] = workflow
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


def _render_status_strip() -> None:
    detail = evidence_caption(
        st.session_state,
        _FULL_WORKSPACE_STATE_KEYS,
        "Cost, Cortex, budget, contract, and verification proof are loaded when a workflow is opened.",
    )
    render_shell_status_strip(
        state=action_state_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS),
        headline="Cost command view: bill movement, Cortex spend, budget risk, and contract burn.",
        detail=detail,
    )


def _render_kpi_row() -> None:
    render_shell_kpi_row((
        ("Scope", scope_label(_active_company(), _active_environment())),
        ("Window", _window_label()),
        ("Compute $/credit", f"{_credit_price():.2f}"),
        ("Evidence", evidence_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS)),
    ))


def _render_workflow_launchpad() -> None:
    def _open(row):
        _open_workspace(str(row["WORKFLOW"]))

    render_shell_workflows(
        "Cost Investigation Workflows",
        _WORKFLOWS,
        label_key="WORKFLOW",
        key_prefix="cost_contract_shell",
        on_open=_open,
    )


def render() -> None:
    _apply_fast_entry_default()
    if _full_workspace_requested():
        _render_back_to_brief_control()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("cost_contract_shell_seen_at", datetime.now().isoformat(timespec="seconds"))
    _render_status_strip()
    _render_kpi_row()
    _render_workflow_launchpad()
