# sections/workload_operations.py - consolidated DBA workload command center
from __future__ import annotations

import streamlit as st

from sections import (
    detailed_diagnosis,
    live_monitor,
    pipeline_health,
    query_analysis,
    query_search,
    stored_proc_tracker,
    task_management,
)
from utils.workflows import (
    render_operator_briefing,
    render_signal_confidence,
    render_workflow_guide,
    render_workflow_selector,
)


WORKFLOWS = (
    "Live triage",
    "Query diagnosis",
    "Task graphs",
    "Stored procedures",
    "Pipeline health",
    "History search",
)

WORKFLOW_DETAILS = {
    "Live triage": "What is running, queued, blocked, or failing right now.",
    "Query diagnosis": "Slow, spilling, expensive, failed, and scan-heavy SQL.",
    "Task graphs": "Workflow/DAG status, failures, retries, SLA, and admin control.",
    "Stored procedures": "Procedure CALL history, runtime drift, lineage, and cost attribution.",
    "Pipeline health": "Load health, copy patterns, task/pipeline signals, and backlog.",
    "History search": "Find one query, user, warehouse, task, or incident trail.",
}


def render() -> None:
    if st.session_state.get("exceptions_only_mode") and "workload_operations_workflow" not in st.session_state:
        st.session_state["workload_operations_workflow"] = "Live triage"

    # Honor older deep links from the prior Query Workbench shell.
    legacy = st.session_state.pop("query_workbench_workflow", None)
    if legacy == "Diagnosis":
        st.session_state["workload_operations_workflow"] = "Query diagnosis"
    elif legacy == "History Search":
        st.session_state["workload_operations_workflow"] = "History search"
    elif legacy == "Live Triage":
        st.session_state["workload_operations_workflow"] = "Live triage"
    elif legacy == "Patterns":
        st.session_state["workload_operations_workflow"] = "Query diagnosis"

    st.header("Workload Operations")
    st.caption(
        "One DBA operating console for live queries, query diagnosis, task graphs, stored procedures, "
        "pipeline health, and query history. This replaces the scattered monitor/search/task pages."
    )
    render_signal_confidence(
        source="ACCOUNT_USAGE",
        confidence="allocated",
        scope_note="Task and procedure cost estimates use runtime plus available warehouse size and cloud-services credits.",
    )
    render_operator_briefing(
        [
            ("First move", "Find running, queued, failed, or late work."),
            ("Evidence", "Capture query IDs, task graph runs, procedure calls, and warehouse context."),
            ("Control", "Cancel, retry, suspend, or resume only after proof and confirmation."),
            ("Output", "Send the DBA narrative to leadership, release review, or the action queue."),
        ],
        columns=4,
    )
    if st.session_state.get("exceptions_only_mode"):
        st.warning("Exceptions-only mode: start with running work, failures, SLA breaches, and release regressions.")

    render_workflow_guide(
        "Start with live triage. Move into query diagnosis, task graphs, or stored procedure tracking only when "
        "the signal requires deeper evidence or an admin action.",
        [
            ("A job is late or failed", "Use Task graphs, then drill into the stored procedure and query IDs."),
            ("A release increased runtime", "Use Stored procedures and the DBA Control Room release compare."),
            ("A warehouse is under pressure", "Use Live triage first, then Warehouse Health."),
            ("A user asks what happened", "Use History search to find the query, then document evidence."),
        ],
    )

    workflow = render_workflow_selector(
        "Workload workflow",
        "workload_operations_workflow",
        WORKFLOWS,
        WORKFLOW_DETAILS,
    )

    if workflow == "Live triage":
        live_monitor.render()
    elif workflow == "Query diagnosis":
        mode = st.radio(
            "Diagnosis mode",
            ["Root cause patterns", "Detailed diagnosis"],
            horizontal=True,
            label_visibility="collapsed",
            key="workload_query_diagnosis_mode",
        )
        if mode == "Root cause patterns":
            query_analysis.render()
        else:
            detailed_diagnosis.render()
    elif workflow == "Task graphs":
        task_management.render()
    elif workflow == "Stored procedures":
        stored_proc_tracker.render()
    elif workflow == "Pipeline health":
        pipeline_health.render()
    else:
        query_search.render()
