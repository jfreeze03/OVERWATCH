"""Fast first-paint shell for the Architecture Readiness route."""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, ENVIRONMENT_CONFIG
from sections.shell_helpers import action_state_label, evidence_caption, evidence_label, evidence_loaded, full_workspace_requested, render_shell_kpi_row, render_shell_status_strip, render_shell_workflows, scope_label


_FULL_WORKSPACE_KEY = "_architecture_readiness_full_workspace_requested"
_BRIEF_MODE_KEY = "_architecture_readiness_brief_mode"
_FULL_WORKSPACE_STATE_KEYS = (
    "arch_objectives_df",
    "arch_iso_df",
    "arch_cluster_df",
    "arch_cache_df",
    "arch_dr_data",
    "arch_source_health",
    "arch_futures_board",
    "arch_agentic_cockpit",
    "arch_adaptive_compute",
    "arch_ai_inventory",
    "arch_ai_usage",
    "arch_ai_security_guardrails",
    "arch_openflow_operations",
    "arch_horizon_readiness",
    "arch_forward_controls",
)

_WORKFLOWS = (
    {
        "PANE": "Workload Isolation",
        "BUTTON_LABEL": "Open Isolation",
        "MOVE": "Find databases and warehouses that should be isolated before tuning.",
    },
    {
        "PANE": "Clustering Strategy",
        "BUTTON_LABEL": "Open Clustering",
        "MOVE": "Review large tables where pruning, clustering, or ownership needs attention.",
    },
    {
        "PANE": "Cache Optimization",
        "BUTTON_LABEL": "Open Cache",
        "MOVE": "Check cache misses, scan pressure, and warehouse behavior before resizing.",
    },
    {
        "PANE": "DR Readiness",
        "BUTTON_LABEL": "Open DR",
        "MOVE": "Validate replication, failover signals, RPO/RTO ownership, and gaps.",
    },
    {
        "PANE": "AI & Platform Futures",
        "BUTTON_LABEL": "Open AI Futures",
        "MOVE": "Review Cortex, serverless, agents, and forward platform guardrails.",
    },
    {
        "PANE": "Objectives & Owners",
        "BUTTON_LABEL": "Open Owners",
        "MOVE": "Load owner, policy, RPO/RTO, and architecture objective context.",
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


def _full_workspace_requested() -> bool:
    return full_workspace_requested(st.session_state, _FULL_WORKSPACE_KEY, _BRIEF_MODE_KEY)


def _open_workspace(pane: str = "Architecture Brief") -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    st.session_state["architecture_readiness_pane"] = pane
    st.rerun()


def _delegate_full_workspace() -> None:
    from sections import architecture_readiness

    architecture_readiness.render()


def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


def _render_back_to_brief_control() -> None:
    control_col, _spacer = st.columns([1.0, 4.0])
    with control_col:
        if st.button("Back to Brief", key="architecture_shell_back_to_brief", width="stretch"):
            _return_to_brief()


def _render_status_strip() -> None:
    detail = evidence_caption(
        st.session_state,
        _FULL_WORKSPACE_STATE_KEYS,
        "Isolation, clustering, cache, DR, AI futures, objectives, and owner evidence open from the workflow grid.",
    )
    render_shell_status_strip(
        state=action_state_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS),
        headline="Architecture command view: isolation, DR, clustering, cache, AI futures, and owners.",
        detail=detail,
    )


def _render_kpi_row() -> None:
    render_shell_kpi_row((
        ("Scope", scope_label(_active_company(), _active_environment())),
        ("Window", _window_label()),
        ("Evidence", evidence_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS)),
        ("Primary route", "Isolation"),
    ))


def _render_workflow_launchpad() -> None:
    def _open(row):
        _open_workspace(str(row["PANE"]))

    render_shell_workflows(
        "Architecture Investigation Workflows",
        _WORKFLOWS,
        label_key="PANE",
        key_prefix="architecture_shell",
        on_open=_open,
    )


def render() -> None:
    if _full_workspace_requested():
        _render_back_to_brief_control()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("architecture_shell_seen_at", datetime.now().isoformat(timespec="seconds"))
    _render_status_strip()
    _render_kpi_row()
    _render_workflow_launchpad()
