"""Fast first-paint shell for the Warehouse Health route."""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, ENVIRONMENT_CONFIG
from sections.shell_helpers import action_state_label, evidence_caption, evidence_label, evidence_loaded, render_shell_snapshot, scope_label


_FULL_WORKSPACE_KEY = "_warehouse_health_full_workspace_requested"
_BRIEF_MODE_KEY = "_warehouse_health_brief_mode"
_FULL_WORKSPACE_STATE_KEYS = (
    "wh_df_wh",
    "wh_capacity_summary",
    "wh_capacity_exceptions",
    "wh_scaling",
    "wh_efficiency",
    "wh_df_sp",
    "wh_df_hm",
    "wh_owner_inventory",
    "wh_settings_inventory",
    "wh_setting_execution_audit",
    "warehouse_health_support_panels_open",
)

_WORKFLOWS = (
    {
        "VIEW": "Overview & Scaling",
        "BUTTON_LABEL": "Open Overview",
        "MOVE": "Start with warehouse pressure, metering movement, and guardrail coverage.",
    },
    {
        "VIEW": "Efficiency",
        "BUTTON_LABEL": "Open Efficiency",
        "MOVE": "Rank credits per query, queue per credit, and spill per credit.",
    },
    {
        "VIEW": "Spill & Memory",
        "BUTTON_LABEL": "Open Spill",
        "MOVE": "Check local and remote spill before changing warehouse size.",
    },
    {
        "VIEW": "Workload Heatmap",
        "BUTTON_LABEL": "Open Heatmap",
        "MOVE": "Find peak hours and concurrency pressure by warehouse.",
    },
    {
        "VIEW": "Optimization Advisor",
        "BUTTON_LABEL": "Open Advisor",
        "MOVE": "Move from loaded evidence to recommended warehouse actions.",
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
    if st.session_state.get(_BRIEF_MODE_KEY):
        return False
    if st.session_state.get(_FULL_WORKSPACE_KEY):
        return True
    return False


def _open_workspace(view: str = "Overview & Scaling") -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    st.session_state["warehouse_health_view"] = view
    st.rerun()


def _delegate_full_workspace() -> None:
    from sections import warehouse_health

    warehouse_health.render()


def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


def _render_back_to_brief_control() -> None:
    control_col, _spacer = st.columns([1.0, 4.0])
    with control_col:
        if st.button("Back to Brief", key="warehouse_health_shell_back_to_brief", width="stretch"):
            _return_to_brief()


def _render_action_brief() -> None:
    with st.container(border=True):
        label_col, detail_col, action_col = st.columns([1.0, 3.0, 1.8])
        with label_col:
            st.markdown("**Action Brief**")
            st.caption(action_state_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS))
        with detail_col:
            st.markdown("**Open Warehouse Health when pressure evidence or setting changes need proof.**")
            st.caption(
                evidence_caption(
                    st.session_state,
                    _FULL_WORKSPACE_STATE_KEYS,
                    "The shell stays zero-query; the full workspace loads only after a workflow is selected.",
                )
            )
        with action_col:
            if st.button("Open Warehouse Workspace", key="warehouse_health_shell_open", type="primary", width="stretch"):
                _open_workspace()


def _render_operating_snapshot() -> None:
    metrics = (
        ("Scope", scope_label(_active_company(), _active_environment())),
        ("Window", _window_label()),
        ("Evidence", evidence_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS)),
        ("Focus", "Pressure"),
    )
    st.markdown("**Operating Snapshot**")
    render_shell_snapshot(metrics)


def _render_workflow_launchpad() -> None:
    st.markdown("**Warehouse Investigation Workflows**")
    visible = _WORKFLOWS[:3]
    cols = st.columns(3)
    for col, row in zip(cols, visible):
        with col:
            st.markdown(f"**{row['VIEW']}**")
            st.caption(row["MOVE"])
            if st.button(row["BUTTON_LABEL"], key=f"warehouse_health_shell_{row['VIEW']}", width="stretch"):
                _open_workspace(str(row["VIEW"]))

    show_all = bool(st.session_state.get("warehouse_health_shell_show_all"))
    if not show_all and st.button("More Warehouse Workflows", key="warehouse_health_shell_more"):
        st.session_state["warehouse_health_shell_show_all"] = True
        st.rerun()

    if show_all:
        extra_cols = st.columns(2)
        for col, row in zip(extra_cols, _WORKFLOWS[3:]):
            with col:
                st.markdown(f"**{row['VIEW']}**")
                st.caption(row["MOVE"])
                if st.button(row["BUTTON_LABEL"], key=f"warehouse_health_shell_extra_{row['VIEW']}", width="stretch"):
                    _open_workspace(str(row["VIEW"]))
        if st.button("Hide Warehouse Workflows", key="warehouse_health_shell_hide"):
            st.session_state["warehouse_health_shell_show_all"] = False
            st.rerun()


def render() -> None:
    if _full_workspace_requested():
        _render_back_to_brief_control()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("warehouse_health_shell_seen_at", datetime.now().isoformat(timespec="seconds"))
    _render_action_brief()
    _render_operating_snapshot()
    _render_workflow_launchpad()
