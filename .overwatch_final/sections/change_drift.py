# sections/change_drift.py - Consolidated change, drift, and lineage workflow
from __future__ import annotations

import streamlit as st

from sections import dba_tools, object_change_monitor, stored_proc_tracker
from utils.workflows import render_signal_confidence, render_workflow_guide, render_workflow_selector

WORKFLOWS = (
    "Object and access changes",
    "Stored procedure lineage",
    "Schema and object drift",
    "Data movement and replication",
    "Controlled DBA actions",
)


def render() -> None:
    if st.session_state.get("exceptions_only_mode") and "change_drift_workflow" not in st.session_state:
        st.session_state["change_drift_workflow"] = "Object and access changes"
    st.header("Change & Drift")
    st.caption(
        "One workflow for who-changed-what investigations, stored procedure lineage, "
        "schema/object drift, dynamic tables, replication, and controlled DBA maintenance."
    )
    render_signal_confidence(
        source="ACCOUNT_USAGE",
        confidence="estimated",
        scope_note="DDL/change detection is query-history based; SHOW commands fill live metadata gaps.",
    )
    if st.session_state.get("exceptions_only_mode"):
        st.warning("Exceptions-only mode: prioritize recent DDL, grant, owner, policy, replication, and task-control issues.")
    render_workflow_guide(
        "Confirm who changed what, trace stored procedure blast radius, then use DBA toolkit checks "
        "for drift, replication, dynamic tables, and controlled actions.",
        [
            ("DDL, grant, owner, or policy changed", "Use Object and access changes."),
            ("A stored procedure drove unexpected cost or changes", "Use Stored procedure lineage."),
            ("Schemas, objects, or unused assets may have drifted", "Use Schema and object drift."),
            ("Loads, pipes, dynamic tables, or replication are suspect", "Use Data movement and replication."),
            ("A query, task, warehouse, or setup action is required", "Use Controlled DBA actions."),
        ],
    )

    workflow = render_workflow_selector(
        "Change workflow",
        "change_drift_workflow",
        WORKFLOWS,
    )

    if workflow == "Object and access changes":
        object_change_monitor.render()
    elif workflow == "Stored procedure lineage":
        stored_proc_tracker.render()
    elif workflow == "Schema and object drift":
        st.session_state["dba_tools_focus"] = "Governance"
        st.info("Focused toolkit: schema compare, recent objects, unused objects, object inventory, and drift checks.")
        dba_tools.render()
    elif workflow == "Data movement and replication":
        st.session_state["dba_tools_focus"] = "Data Movement"
        st.info("Focused toolkit: data loading, Snowpipe, dynamic tables, and replication checks.")
        dba_tools.render()
    else:
        st.session_state["dba_tools_focus"] = "Controlled Actions"
        st.info("Focused toolkit: query cancellation, warehouse settings, task graph control, setup, and audit evidence.")
        dba_tools.render()
