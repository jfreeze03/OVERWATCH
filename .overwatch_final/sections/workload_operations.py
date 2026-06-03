# sections/workload_operations.py - consolidated DBA workload command center
from __future__ import annotations

import streamlit as st

from utils import (
    build_mart_control_room_summary_sql,
    format_snowflake_error,
    get_active_company,
    run_query,
    safe_float,
    safe_int,
)
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


def _snapshot_meta(company: str, hours: int = 24) -> dict:
    return {"company": company, "hours": int(hours)}


def _load_workload_snapshot(company: str, *, hours: int = 24, show_errors: bool = False) -> None:
    try:
        snapshot = run_query(
            build_mart_control_room_summary_sql(hours, company),
            ttl_key=f"workload_operations_snapshot_{company}_{hours}",
            tier="historical",
            section="Workload Operations",
        )
        st.session_state["workload_operations_snapshot"] = snapshot
        st.session_state["workload_operations_snapshot_meta"] = _snapshot_meta(company, hours)
        st.session_state["workload_operations_snapshot_error"] = ""
    except Exception as exc:
        st.session_state["workload_operations_snapshot"] = None
        st.session_state["workload_operations_snapshot_meta"] = _snapshot_meta(company, hours)
        st.session_state["workload_operations_snapshot_error"] = format_snowflake_error(exc)
        if show_errors:
            st.warning(f"Workload snapshot unavailable: {st.session_state['workload_operations_snapshot_error']}")


def _render_workload_snapshot(company: str) -> None:
    hours = 24
    expected_meta = _snapshot_meta(company, hours)
    snapshot = st.session_state.get("workload_operations_snapshot")
    snapshot_current = st.session_state.get("workload_operations_snapshot_meta") == expected_meta
    if snapshot is None or getattr(snapshot, "empty", True) or not snapshot_current:
        cols = st.columns([1, 3])
        with cols[0]:
            if st.button("Refresh Ops Snapshot", key="workload_ops_snapshot_refresh"):
                _load_workload_snapshot(company, hours=hours, show_errors=True)
                st.rerun()
        with cols[1]:
            err = st.session_state.get("workload_operations_snapshot_error", "")
            st.caption(
                "Load a 24-hour workload snapshot when you need router-level failure, queue, spill, and p95 context. "
                "Use the workflows below for live or source-specific evidence."
            )
            if err:
                st.caption(err)
        return

    row = snapshot.iloc[0].to_dict()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Queries 24h", f"{safe_int(row.get('TOTAL_QUERIES')):,}")
    c2.metric("Failed 24h", f"{safe_int(row.get('FAILED_QUERIES')):,}", delta_color="inverse")
    c3.metric("Queued 24h", f"{safe_int(row.get('QUEUED_QUERIES')):,}", delta_color="inverse")
    c4.metric("Spill 24h", f"{safe_int(row.get('REMOTE_SPILL_QUERIES')):,}", delta_color="inverse")
    c5.metric("P95 Elapsed", f"{safe_float(row.get('P95_ELAPSED_SEC')):,.1f}s")


def render() -> None:
    company = get_active_company()
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
    _render_workload_snapshot(company)
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
