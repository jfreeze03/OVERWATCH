# sections/workload_operations.py - consolidated DBA workload command center
from __future__ import annotations

import streamlit as st

from utils.workflows import (
    migrate_legacy_workflow_state,
    render_operator_briefing,
    render_signal_confidence,
    render_workflow_module,
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

WORKFLOW_MODULES = {
    "Live triage": "sections.live_monitor",
    "Query diagnosis": "sections.query_analysis",
    "Root cause patterns": "sections.query_analysis",
    "Detailed diagnosis": "sections.detailed_diagnosis",
    "Task graphs": "sections.task_management",
    "Stored procedures": "sections.stored_proc_tracker",
    "Pipeline health": "sections.pipeline_health",
    "History search": "sections.query_search",
}

LEGACY_WORKFLOW_MAP = {
    "Diagnosis": "Query diagnosis",
    "History Search": "History search",
    "Live Triage": "Live triage",
    "Patterns": "Query diagnosis",
}


def render() -> None:
    if st.session_state.get("exceptions_only_mode") and "workload_operations_workflow" not in st.session_state:
        st.session_state["workload_operations_workflow"] = "Live triage"
    migrate_legacy_workflow_state(
        "query_workbench_workflow",
        "workload_operations_workflow",
        LEGACY_WORKFLOW_MAP,
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
        columns=3,
    )

    if workflow == "Live triage":
        render_workflow_module(workflow, WORKFLOW_MODULES)
    elif workflow == "Query diagnosis":
        if st.session_state.pop("workload_query_diagnosis_mode", "") == "Detailed diagnosis":
            st.session_state["query_analysis_active_view"] = "Detailed Diagnosis"
        render_workflow_module(workflow, WORKFLOW_MODULES)
    else:
        render_workflow_module(workflow, WORKFLOW_MODULES)
