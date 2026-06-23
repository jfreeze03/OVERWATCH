# sections/change_drift_workflows_view.py - Change Workflows renderer
from __future__ import annotations

import streamlit as st

from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.shell_helpers import (
    consume_section_autoload_request,
    render_data_freshness,
    render_escaped_bold_text,
    render_shell_kpi_row,
    render_shell_snapshot,
    render_shell_status_strip,
    with_loaded_at,
)
from sections.change_drift_action_queue import *
from sections.change_drift_common import *
from sections.change_drift_contracts import *
from sections.change_drift_models import *
from sections.change_drift_sql import *
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_source_note

pd = lazy_pandas()
format_snowflake_error = _lazy_util("format_snowflake_error")
get_session = _lazy_util("get_session")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
run_query = _lazy_util("run_query")
day_window_selectbox = _lazy_util("day_window_selectbox")
render_workflow_selector = _lazy_util("render_workflow_selector")

def _render_change_source_health(company: str, environment: str) -> None:
    source_health = _change_source_health_rows(st.session_state, company, environment)
    if source_health.empty:
        return
    with st.expander("Change Data Health", expanded=False):
        current = int(source_health["STATE"].isin(["Loaded", "No Rows"]).sum())
        stale = int(source_health["STATE"].eq("Stale").sum())
        unavailable = int(source_health["STATE"].eq("Unavailable").sum())
        fast_summary = int(
            source_health[
            source_health["STATE"].isin(["Loaded", "No Rows"])
            & source_health["CONFIDENCE"].astype(str).str.contains("Fast summary", case=False, regex=False)
        ].shape[0]
        )
        render_shell_snapshot((
            ("Current Surfaces", f"{current}/{len(source_health)}"),
            ("Fast Summary", f"{fast_summary:,}"),
            ("Stale", f"{stale:,}"),
            ("Unavailable", f"{unavailable:,}"),
        ))
        defer_source_note(
            "Use this before acting on change findings. Object/access-change detection is text-pattern based, "
            "and account/role-only events are intentionally retained when no database context exists."
        )
        render_priority_dataframe(
            source_health,
            title="Change telemetry freshness",
            priority_columns=[
                "STATE", "SURFACE", "CONFIDENCE", "ROWS", "SCOPE", "SOURCE", "NEXT_ACTION",
            ],
            sort_by=["STATE_RANK", "SURFACE"],
            ascending=[True, True],
            raw_label="All change data-health rows",
            height=260,
        )

def render_change_workflows(company: str, environment: str, days: int | None = None) -> None:
    if _change_has_source_state(st.session_state):
        _render_change_source_health(company, environment)
    workflow = render_workflow_selector(
        "Change workflow",
        "change_drift_workflow",
        WORKFLOWS,
        WORKFLOW_DETAILS,
        columns=5,
    )

    if workflow == "Object and access changes":
        render_workflow_module(workflow, WORKFLOW_MODULES)
    elif workflow == "Stored procedure lineage":
        render_workflow_module(workflow, WORKFLOW_MODULES)
    elif workflow == "Schema and object drift":
        st.session_state["dba_tools_focus"] = "Object Monitoring"
        st.session_state["dba_tools_focus_tool"] = "Schema Compare"
        st.info("Focused toolkit: schema compare, recent objects, unused objects, object inventory, and drift checks.")
        render_workflow_module(workflow, WORKFLOW_MODULES)
    elif workflow == "Data movement and replication":
        st.session_state["dba_tools_focus"] = "Data Movement"
        st.session_state["dba_tools_focus_tool"] = "Data Loading"
        st.info("Focused toolkit: data loading, Snowpipe, dynamic tables, and replication checks.")
        render_workflow_module(workflow, WORKFLOW_MODULES)
    else:
        st.session_state["dba_tools_focus"] = "Controlled Actions"
        st.session_state["dba_tools_focus_tool"] = "Task Graph Control"
        st.info("Focused toolkit: query cancellation, warehouse settings, task graph control, status checks, and audit telemetry.")
        render_workflow_module(workflow, WORKFLOW_MODULES)


__all__ = ['_render_change_source_health', 'render_change_workflows']
