"""OVERWATCH v2 Streamlit entrypoint."""

from __future__ import annotations

import importlib

import pandas as pd
import streamlit as st

from overwatch_app.data.access_control import is_admin
from overwatch_app.registry import SECTIONS, Workflow, visible_workflows
from overwatch_app.security.rbac import context_from_session


def _active_session() -> object | None:
    try:
        from snowflake.snowpark.context import get_active_session  # type: ignore
    except Exception:
        return None
    try:
        return get_active_session()
    except Exception:
        return None


def _query_param(name: str) -> str:
    try:
        value = st.query_params.get(name, "")
    except Exception:
        return ""
    if isinstance(value, list):
        return str(value[0] if value else "")
    return str(value or "")


def _set_query_param(name: str, value: str) -> None:
    try:
        st.query_params[name] = value
    except Exception:
        return


def _scope_controls() -> dict[str, object]:
    st.sidebar.divider()
    st.sidebar.caption("APP CONTROLS")
    with st.sidebar.expander("Advanced Scope", expanded=False):
        company = st.selectbox("Company", ("ALL", "ALFA", "Trexis"), index=0)
        environment = st.selectbox("Environment", ("ALL", "PROD", "NONPROD"), index=0)
        window = st.selectbox("Window", (7, 30, 90), index=1)
        warehouse = st.text_input("Warehouse", value="ALL")
    with st.sidebar.expander("Settings", expanded=False):
        st.caption("Admin workflows are controlled by Snowflake role.")
    st.sidebar.caption("OVERWATCH v2")
    return {
        "company": company,
        "environment": environment,
        "window": int(window),
        "warehouse": warehouse or "ALL",
        "source_version": "current",
    }


def _load_frame(loader: object, scope: dict[str, object], workflow: Workflow, role: str) -> pd.DataFrame:
    return loader(  # type: ignore[misc]
        str(scope["company"]),
        str(scope["environment"]),
        int(scope["window"]),
        str(scope["warehouse"]),
        workflow.title,
        role,
        str(scope["source_version"]),
    )


def _render_workflow(section_key: str, workflow: Workflow, context: object, scope: dict[str, object]) -> None:
    section = next((item for item in SECTIONS if item.key == section_key), SECTIONS[0])
    module = importlib.import_module(section.module)
    renderer = getattr(module, workflow.renderer)
    role = getattr(context, "role", "")

    if section.key == "executive":
        from overwatch_app.data.repositories.executive import load_executive_first_paint, load_source_freshness
        from overwatch_app.sections.executive import build_executive_view_model

        renderer(build_executive_view_model(
            _load_frame(load_executive_first_paint, scope, workflow, role),
            pd.DataFrame(),
            _load_frame(load_source_freshness, scope, workflow, role),
        ))
    elif section.key == "cost" and workflow.key == "allocation":
        from overwatch_app.data.repositories.cost import load_cost_allocation_daily

        renderer(_load_frame(load_cost_allocation_daily, scope, workflow, role))
    elif section.key == "cost":
        from overwatch_app.data.repositories.cost import (
            load_contract_burn_down,
            load_cost_allocation_daily,
            load_cost_first_paint,
        )
        from overwatch_app.sections.cost import build_cost_view_model

        renderer(build_cost_view_model(
            _load_frame(load_cost_first_paint, scope, workflow, role),
            _load_frame(load_contract_burn_down, scope, workflow, role),
            _load_frame(load_cost_allocation_daily, scope, workflow, role),
        ))
    elif section.key == "alerts":
        from overwatch_app.data.repositories.alerts import load_alert_center_first_paint

        renderer(_load_frame(load_alert_center_first_paint, scope, workflow, role))
    elif section.key == "dba" and workflow.key == "live":
        from overwatch_app.data.repositories.dba import load_dba_morning_cockpit
        from overwatch_app.sections.dba import build_live_mode_model

        renderer(build_live_mode_model(_load_frame(load_dba_morning_cockpit, scope, workflow, role), context))
    elif section.key == "dba":
        from overwatch_app.data.repositories.dba import load_dba_morning_cockpit

        renderer(_load_frame(load_dba_morning_cockpit, scope, workflow, role))
    elif section.key == "workload":
        from overwatch_app.data.repositories.workload import load_query_error_summary, load_workload_first_paint

        frame = pd.concat(
            [
                _load_frame(load_workload_first_paint, scope, workflow, role),
                _load_frame(load_query_error_summary, scope, workflow, role),
            ],
            ignore_index=True,
            sort=False,
        )
        renderer(frame)
    elif section.key == "security":
        from overwatch_app.data.repositories.security import load_security_first_paint

        renderer(_load_frame(load_security_first_paint, scope, workflow, role))
    else:
        renderer()


def main() -> None:
    st.set_page_config(page_title="OVERWATCH", layout="wide")
    session = _active_session()
    rbac_context = context_from_session(session)
    st.session_state["overwatch_rbac_context"] = rbac_context
    include_admin = is_admin(session)
    st.sidebar.title("OVERWATCH")
    section_labels = {section.title: section.key for section in SECTIONS}
    section_keys = tuple(section_labels.values())
    requested_section = _query_param("section")
    selected_section_key = requested_section if requested_section in section_keys else SECTIONS[0].key
    selected_title_default = next(title for title, key in section_labels.items() if key == selected_section_key)
    selected_title = st.sidebar.radio(
        "Section",
        tuple(section_labels),
        index=tuple(section_labels).index(selected_title_default),
    )
    section_key = section_labels[selected_title]
    workflows = visible_workflows(section_key, include_admin=include_admin)
    workflow_labels = {workflow.title: workflow.key for workflow in workflows}
    requested_workflow = _query_param("workflow")
    selected_workflow_key = requested_workflow if requested_workflow in workflow_labels.values() else workflows[0].key
    selected_workflow_default = next(title for title, key in workflow_labels.items() if key == selected_workflow_key)
    selected_workflow = st.sidebar.radio(
        "Workflow",
        tuple(workflow_labels),
        index=tuple(workflow_labels).index(selected_workflow_default),
    )
    _set_query_param("section", section_key)
    _set_query_param("workflow", workflow_labels[selected_workflow])
    scope = _scope_controls()
    workflow = next(item for item in workflows if item.key == workflow_labels[selected_workflow])
    _render_workflow(section_key, workflow, rbac_context, scope)


if __name__ == "__main__":
    main()
