"""Settings and advanced diagnostics for the simplified OVERWATCH product."""

from __future__ import annotations

import importlib

import streamlit as st

from runtime_state import OPERATOR_SETTINGS_LOADED_TOOL, get_state, set_state


ADVANCED_TOOLS = {
    "Alert setup": {
        "module": "sections.alert_center",
        "state": {"alert_center_active_view": "Delivery & Automation"},
        "description": "Alert recipients, delivery status, and notification setup.",
    },
    "Suppression windows": {
        "module": "sections.alert_center",
        "state": {"alert_center_active_view": "Suppression Windows"},
        "description": "Alert suppression configuration.",
    },
    "Schema and data compare": {
        "module": "sections.dba_tools",
        "state": {"workload_operations_workflow": "Schema & data compare"},
        "description": "Admin utility for object/data comparison and missing-object script generation.",
    },
    "Warehouse settings review": {
        "module": "sections.cost_contract",
        "state": {"cost_contract_workflow": "Recommendations and action queue"},
        "description": "Guarded warehouse setting recommendations and reviewable SQL.",
    },
    "Refresh diagnostics": {
        "module": "sections.dba_control_room",
        "state": {"dba_control_room_active_view": "Service Posture"},
        "description": "Refresh health, source freshness, and stale telemetry checks.",
    },
    "App observability": {
        "module": "sections.dba_control_room",
        "state": {"dba_control_room_active_view": "Admin Tools"},
        "description": "App diagnostics and admin-only operating status.",
    },
}


def _load_advanced_tool(tool_name: str) -> None:
    tool = ADVANCED_TOOLS.get(tool_name, {})
    for key, value in dict(tool.get("state") or {}).items():
        set_state(key, value)
    module_name = str(tool.get("module") or "")
    if not module_name:
        return
    module = importlib.import_module(module_name)
    render = getattr(module, "render", None)
    if callable(render):
        render()
    else:
        st.warning(f"{tool_name} is not available in this build.")


def render() -> None:
    """Render admin-only settings and advanced tools."""
    st.markdown("### SETTINGS")
    st.caption("Configuration, diagnostics, and legacy deep-dive tools live here.")

    setup_cols = st.columns(3)
    with setup_cols[0]:
        st.markdown("#### Alerting")
        st.write("Alert email, delivery setup, thresholds, and suppression windows.")
    with setup_cols[1]:
        st.markdown("#### Data and Roles")
        st.write("Schema/data compare, role readiness, grant guidance, and validation runbooks.")
    with setup_cols[2]:
        st.markdown("#### Refresh and Diagnostics")
        st.write("Refresh health, stale telemetry checks, and app diagnostics.")

    with st.expander("Role readiness and grant guidance", expanded=False):
        st.write(
            "Target roles remain OVERWATCH_VIEWER, OVERWATCH_OPERATOR, and OVERWATCH_ADMIN. "
            "SNOW_ACCOUNTADMINS and SNOW_SYSADMINS are the approved transitional access model. "
            "Generate and review grant SQL outside normal operator triage; do not execute grants silently."
        )

    with st.expander("Mart validation and retirement plan", expanded=False):
        st.write(
            "The simplified UI is now the guiding product surface. Existing legacy objects should be "
            "measured for use, marked deprecated when overmodeled, and retired only after explicit approval."
        )
        st.write(
            "Target slim model: 28 to 34 tables centered on cost, workload, security, change, incidents, "
            "recommendations, settings, and refresh audit."
        )

    st.markdown("#### Advanced Tools")
    selected = st.selectbox(
        "Tool",
        tuple(ADVANCED_TOOLS),
        format_func=lambda item: f"{item} - {ADVANCED_TOOLS[item]['description']}",
        key="operator_settings_advanced_tool",
    )
    if st.button("Load Advanced Tool", key="operator_settings_load_advanced_tool", width="stretch"):
        set_state(OPERATOR_SETTINGS_LOADED_TOOL, selected)

    loaded = get_state(OPERATOR_SETTINGS_LOADED_TOOL)
    if loaded:
        st.divider()
        st.caption("Advanced diagnostics are intentionally loaded only after this explicit action.")
        _load_advanced_tool(str(loaded))
