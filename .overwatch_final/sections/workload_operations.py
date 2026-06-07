# sections/workload_operations.py - consolidated DBA workload command center
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from importlib import import_module

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT
import utils as _utils
from utils.section_guidance import defer_section_note, defer_source_note


def _lazy_util(name: str):
    def _call(*args, **kwargs):
        return getattr(_utils, name)(*args, **kwargs)

    _call.__name__ = name
    return _call


build_mart_control_room_summary_sql = _lazy_util("build_mart_control_room_summary_sql")
format_snowflake_error = _lazy_util("format_snowflake_error")
run_query = _lazy_util("run_query")


def safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value != value:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default: int = 0) -> int:
    try:
        if value is None or value != value:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def get_active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def get_active_environment() -> str:
    return str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)


def migrate_legacy_workflow_state(
    legacy_key: str,
    target_key: str,
    mapping: Mapping[str, str],
    *,
    remove_legacy: bool = True,
) -> None:
    legacy_value = st.session_state.pop(legacy_key, None) if remove_legacy else st.session_state.get(legacy_key)
    mapped = mapping.get(str(legacy_value or ""))
    if mapped:
        st.session_state[target_key] = mapped


def render_workflow_module(workflow: str, workflow_modules: Mapping[str, str]) -> None:
    module_name = workflow_modules.get(str(workflow))
    if not module_name:
        st.warning(f"No module registered for workflow: {workflow}")
        return
    module = import_module(module_name)
    render = getattr(module, "render", None)
    if not callable(render):
        st.warning(f"Workflow module has no render() function: {module_name}")
        return
    render()


def render_workflow_guide(summary: str, rows: Sequence[tuple[str, str]]) -> None:
    defer_section_note(summary)
    for trigger, action in rows:
        defer_section_note(f"{trigger}: {action}")


def render_operator_briefing(rows: Sequence[tuple[str, str]], *, columns: int = 4) -> None:
    _ = columns
    for label, detail in rows:
        defer_section_note(f"{label}: {detail}")


def render_workflow_selector(
    label: str,
    key: str,
    workflows: Sequence[str],
    details: Mapping[str, str] | None = None,
    *,
    columns: int = 4,
) -> str:
    selected = str(st.session_state.get(key, workflows[0] if workflows else "") or "")
    if selected not in workflows:
        selected = workflows[0] if workflows else ""
        st.session_state[key] = selected

    details = details or {}
    items = list(workflows)
    columns = max(1, min(int(columns or 4), 5))
    for start in range(0, len(items), columns):
        row = items[start:start + columns]
        cols = st.columns(len(row))
        for col, workflow in zip(cols, row):
            with col:
                is_selected = workflow == selected
                if st.button(
                    workflow,
                    key=f"{key}_{start}_{workflow}",
                    type="primary" if is_selected else "secondary",
                    width="stretch",
                    help=details.get(workflow) or None,
                ):
                    st.session_state[key] = workflow
                    st.rerun()
    return str(st.session_state.get(key, selected))


WORKLOAD_OPERATIONS_VIEWS = ("Workload Brief", "Specialist Workflows")
WORKLOAD_OPERATIONS_FAST_ENTRY_VERSION = "2026-06-06-fast-brief-v1"

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


def _apply_fast_entry_default() -> None:
    """Keep first navigation fast after older sessions auto-opened live triage."""
    if st.session_state.get("_workload_operations_fast_entry_version") == WORKLOAD_OPERATIONS_FAST_ENTRY_VERSION:
        return
    if st.session_state.get("workload_operations_view") == "Specialist Workflows":
        st.session_state["workload_operations_view"] = WORKLOAD_OPERATIONS_VIEWS[0]
    st.session_state["_workload_operations_fast_entry_version"] = WORKLOAD_OPERATIONS_FAST_ENTRY_VERSION


def _snapshot_meta(company: str, environment: str, hours: int = 24) -> dict:
    return {"company": company, "environment": environment, "hours": int(hours)}


def _load_workload_snapshot(company: str, environment: str, *, hours: int = 24, show_errors: bool = False) -> None:
    try:
        snapshot = run_query(
            build_mart_control_room_summary_sql(hours, company),
            ttl_key=f"workload_operations_snapshot_{company}_{environment}_{hours}",
            tier="historical",
            section="Workload Operations",
        )
        st.session_state["workload_operations_snapshot"] = snapshot
        st.session_state["workload_operations_snapshot_meta"] = _snapshot_meta(company, environment, hours)
        st.session_state["workload_operations_snapshot_error"] = ""
    except Exception as exc:
        st.session_state["workload_operations_snapshot"] = None
        st.session_state["workload_operations_snapshot_meta"] = _snapshot_meta(company, environment, hours)
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


def _workload_runbook_filename(company: str, environment: str = "ALL") -> str:
    scope_text = f"{company}_{environment}"
    scope = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(scope_text or "all").strip())
    while "__" in scope:
        scope = scope.replace("__", "_")
    return f"overwatch_workload_runbook_{scope.strip('_') or 'scope'}.md"


def _build_workload_runbook_markdown(company: str, environment: str, summary: dict, brief: dict) -> str:
    loaded = bool(summary.get("loaded"))
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    if loaded:
        kpi_line = (
            f"{safe_int(summary.get('queries')):,} queries, "
            f"{safe_int(summary.get('failed')):,} failed, "
            f"{safe_int(summary.get('queued')):,} queued, "
            f"{safe_int(summary.get('spill')):,} remote-spill, "
            f"p95 {safe_float(summary.get('p95')):,.1f}s"
        )
    else:
        kpi_line = "Snapshot not loaded. Refresh the workload snapshot or start live triage."

    lines = [
        "# OVERWATCH Workload Operations Runbook",
        "",
        f"- Scope: {company} / {environment}",
        "- Window: 24 hours",
        f"- Generated: {generated_at}",
        f"- Snapshot: {kpi_line}",
        f"- Current signal: {brief.get('state') or 'Review'}",
        f"- Operator move: {brief.get('headline') or 'Review workload evidence.'}",
        f"- Detail: {brief.get('detail') or 'No detail loaded.'}",
        "",
        "## Slide Bullets",
        f"- Workload posture: {brief.get('state') or 'Review'} for {company} / {environment}.",
        f"- KPI line: {kpi_line}",
        f"- First action: {brief.get('primary_label') or 'Open Live Triage'}.",
        f"- Evidence owner: route to {brief.get('workflow') or 'Live triage'} in Workload Operations.",
        "",
        "## Triage Order",
        "1. Live triage: identify running, queued, blocked, or cancellable work.",
        "2. Query diagnosis: capture query ID, warehouse, user, role, database, schema, elapsed time, spill, and error text.",
        "3. Task graphs: confirm root task, failed run, retry state, downstream blast radius, and owner.",
        "4. Stored procedures: tie CALL history to query IDs, runtime drift, and cost attribution.",
        "5. Pipeline health: check load backlog, copy errors, task lag, and dynamic table refresh state.",
        "",
        "## Evidence Checklist",
        "- Query ID or task graph run ID",
        "- Warehouse, user, role, database, and schema",
        "- Start time, elapsed time, queue time, spill, and credits where available",
        "- Error text or blocking session when applicable",
        "- Owner, approval path, rollback option, and post-change verification query",
        "",
        "## Guardrails",
        "- Prefer evidence capture before cancel, retry, suspend, or resume actions.",
        "- Use DBA Control Room release compare when a deployment changed runtime or failures.",
        "- Queue an action only when the owner, proof query, and verification path are clear.",
    ]
    return "\n".join(lines) + "\n"


def _render_workload_action_brief(company: str, environment: str, brief: dict) -> None:
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
                    _load_workload_snapshot(company, environment, show_errors=True)
                else:
                    workflow = str(brief.get("workflow") or "Live triage")
                    if workflow in WORKFLOWS:
                        st.session_state["workload_operations_view"] = "Specialist Workflows"
                        st.session_state["workload_operations_workflow"] = workflow
                st.rerun()
            if not bool(brief.get("refresh")):
                if st.button("Refresh Snapshot", key="workload_ops_action_brief_refresh", width="stretch"):
                    _load_workload_snapshot(company, environment, show_errors=True)
                    st.rerun()


def _render_workload_metric_rows(summary: dict) -> None:
    loaded = bool(summary.get("loaded"))
    cols = st.columns(4)
    if not loaded:
        cols[0].metric("Scope", "Company")
        cols[1].metric("Window", "24h")
        cols[2].metric("Evidence", "Refresh")
        cols[3].metric("Route", "Live triage")
        return
    cols[0].metric("Queries", f"{safe_int(summary.get('queries')):,}")
    cols[1].metric("Failed", f"{safe_int(summary.get('failed')):,}", delta_color="inverse")
    cols[2].metric("Queued", f"{safe_int(summary.get('queued')):,}", delta_color="inverse")
    cols[3].metric("P95", f"{safe_float(summary.get('p95')):,.1f}s")


def _render_workload_snapshot(company: str, environment: str) -> None:
    hours = 24
    expected_meta = _snapshot_meta(company, environment, hours)
    snapshot = st.session_state.get("workload_operations_snapshot")
    snapshot_current = st.session_state.get("workload_operations_snapshot_meta") == expected_meta
    err = st.session_state.get("workload_operations_snapshot_error", "")
    summary = _workload_snapshot_summary(snapshot if snapshot_current else None)
    brief = _workload_action_brief(summary, snapshot_current=snapshot_current, error=str(err or ""))
    _render_workload_action_brief(company, environment, brief)
    st.markdown("**Operating Snapshot**")
    _render_workload_metric_rows(summary)
    with st.expander("Runbook export", expanded=False):
        st.caption("Download a copy-ready DBA runbook for the selected company and workload snapshot state.")
        st.download_button(
            "Download DBA runbook",
            data=_build_workload_runbook_markdown(company, environment, summary, brief),
            file_name=_workload_runbook_filename(company, environment),
            mime="text/markdown",
            key="workload_ops_runbook_download",
        )


def render() -> None:
    company = get_active_company()
    environment = get_active_environment()
    _apply_fast_entry_default()
    if st.session_state.get("exceptions_only_mode") and "workload_operations_workflow" not in st.session_state:
        st.session_state["workload_operations_workflow"] = "Live triage"
    if st.session_state.get("workload_operations_view") not in WORKLOAD_OPERATIONS_VIEWS:
        st.session_state["workload_operations_view"] = WORKLOAD_OPERATIONS_VIEWS[0]
    migrate_legacy_workflow_state(
        "query_workbench_workflow",
        "workload_operations_workflow",
        LEGACY_WORKFLOW_MAP,
    )

    _render_workload_snapshot(company, environment)
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

    active_view = st.selectbox(
        "Workload Operations view",
        WORKLOAD_OPERATIONS_VIEWS,
        key="workload_operations_view",
    )
    if active_view == "Workload Brief":
        return

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
