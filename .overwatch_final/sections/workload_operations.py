# sections/workload_operations.py - consolidated DBA workload command center
from __future__ import annotations

import streamlit as st

from utils import (
    build_mart_control_room_summary_sql,
    defer_source_note,
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
            st.info("Workload snapshot unavailable. Start with live triage or retry after source access is available.")
            defer_source_note("Workload snapshot unavailable.", st.session_state["workload_operations_snapshot_error"])


def _workload_snapshot_summary(snapshot) -> dict:
    if snapshot is None or getattr(snapshot, "empty", True):
        return {
            "loaded": False,
            "queries": 0,
            "failed": 0,
            "queued": 0,
            "spill": 0,
            "p95": 0.0,
        }
    row = snapshot.iloc[0].to_dict()
    return {
        "loaded": True,
        "queries": safe_int(row.get("TOTAL_QUERIES")),
        "failed": safe_int(row.get("FAILED_QUERIES")),
        "queued": safe_int(row.get("QUEUED_QUERIES")),
        "spill": safe_int(row.get("REMOTE_SPILL_QUERIES")),
        "p95": safe_float(row.get("P95_ELAPSED_SEC")),
    }


def _workload_action_brief(summary: dict, *, snapshot_current: bool = True, error: str = "") -> dict:
    if not summary.get("loaded") or not snapshot_current:
        state = "Refresh Needed" if not snapshot_current else "Not Loaded"
        detail = "Snapshot evidence is optional; live triage remains available for current running work."
        if error:
            detail = "Snapshot source needs review; live triage remains available for current running work."
        return {
            "state": state,
            "headline": "Refresh the workload snapshot or start live triage.",
            "detail": detail,
            "primary_label": "Refresh Snapshot",
            "workflow": "Live triage",
            "refresh": True,
        }
    if safe_int(summary.get("failed")) > 0:
        return {
            "state": "Failure Review",
            "headline": "Review failed workload evidence first.",
            "detail": f"{safe_int(summary.get('failed')):,} failed query row(s) in the loaded 24-hour snapshot.",
            "primary_label": "Open Query Diagnosis",
            "workflow": "Query diagnosis",
            "refresh": False,
        }
    if safe_int(summary.get("queued")) > 0:
        return {
            "state": "Queue Pressure",
            "headline": "Check running and queued work before deeper diagnosis.",
            "detail": f"{safe_int(summary.get('queued')):,} queued query row(s) in the loaded 24-hour snapshot.",
            "primary_label": "Open Live Triage",
            "workflow": "Live triage",
            "refresh": False,
        }
    if safe_int(summary.get("spill")) > 0:
        return {
            "state": "Spill Review",
            "headline": "Find the spilling SQL and owning workflow.",
            "detail": f"{safe_int(summary.get('spill')):,} remote-spill query row(s) in the loaded 24-hour snapshot.",
            "primary_label": "Open Query Diagnosis",
            "workflow": "Query diagnosis",
            "refresh": False,
        }
    if safe_float(summary.get("p95")) >= 60.0:
        return {
            "state": "Latency Watch",
            "headline": "Review high-latency query patterns.",
            "detail": f"P95 elapsed is {safe_float(summary.get('p95')):,.1f}s in the loaded 24-hour snapshot.",
            "primary_label": "Open Query Diagnosis",
            "workflow": "Query diagnosis",
            "refresh": False,
        }
    return {
        "state": "Clear",
        "headline": "No immediate workload blocker in the snapshot.",
        "detail": f"{safe_int(summary.get('queries')):,} query row(s) loaded for the last 24 hours.",
        "primary_label": "Open Live Triage",
        "workflow": "Live triage",
        "refresh": False,
    }


def _render_workload_action_brief(company: str, brief: dict) -> None:
    with st.container(border=True):
        label_col, detail_col, action_col = st.columns([1.1, 3.2, 1.4])
        with label_col:
            st.markdown("**Action Brief**")
            st.caption(str(brief.get("state") or "Review"))
        with detail_col:
            st.markdown(f"**{brief.get('headline') or 'Review workload evidence.'}**")
            st.caption(str(brief.get("detail") or ""))
        with action_col:
            if st.button(str(brief.get("primary_label") or "Open Live Triage"), key="workload_ops_action_brief_primary", width="stretch"):
                if bool(brief.get("refresh")):
                    _load_workload_snapshot(company, show_errors=True)
                else:
                    workflow = str(brief.get("workflow") or "Live triage")
                    if workflow in WORKFLOWS:
                        st.session_state["workload_operations_workflow"] = workflow
                st.rerun()
            if not bool(brief.get("refresh")):
                if st.button("Refresh Snapshot", key="workload_ops_action_brief_refresh", width="stretch"):
                    _load_workload_snapshot(company, show_errors=True)
                    st.rerun()


def _render_workload_metric_rows(summary: dict) -> None:
    row1 = st.columns(3)
    row1[0].metric("Queries 24h", f"{safe_int(summary.get('queries')):,}")
    row1[1].metric("Failed 24h", f"{safe_int(summary.get('failed')):,}", delta_color="inverse")
    row1[2].metric("Queued 24h", f"{safe_int(summary.get('queued')):,}", delta_color="inverse")
    row2 = st.columns(2)
    row2[0].metric("Spill 24h", f"{safe_int(summary.get('spill')):,}", delta_color="inverse")
    row2[1].metric("P95 Elapsed", f"{safe_float(summary.get('p95')):,.1f}s")


def _render_workload_snapshot(company: str) -> None:
    hours = 24
    expected_meta = _snapshot_meta(company, hours)
    snapshot = st.session_state.get("workload_operations_snapshot")
    snapshot_current = st.session_state.get("workload_operations_snapshot_meta") == expected_meta
    err = st.session_state.get("workload_operations_snapshot_error", "")
    summary = _workload_snapshot_summary(snapshot if snapshot_current else None)
    if snapshot is None or getattr(snapshot, "empty", True) or not snapshot_current:
        _render_workload_action_brief(
            company,
            _workload_action_brief(summary, snapshot_current=snapshot_current, error=str(err or "")),
        )
        return

    _render_workload_action_brief(company, _workload_action_brief(summary, snapshot_current=True))
    _render_workload_metric_rows(summary)


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
