# sections/workload_operations.py - consolidated DBA workload command center
from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from importlib import import_module

import streamlit as st

from config import ALERT_DB, ALERT_SCHEMA, DEFAULT_COMPANY, DEFAULT_ENVIRONMENT
from sections.base import lazy_util as _lazy_util
from sections.shell_helpers import (
    consume_section_autoload_request,
    render_data_freshness,
    render_shell_kpi_row,
    render_shell_snapshot,
    render_shell_status_strip,
    with_loaded_at,
)
from utils.evidence_mode import (
    TRIAGE_MODE_ALL_EVIDENCE,
    TRIAGE_MODE_INVESTIGATE,
    TRIAGE_MODE_TRIAGE,
    current_evidence_mode,
)
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_section_note, defer_source_note

_LANE_CARD_STYLE = (
    "min-height:7.1rem;"
    "display:flex;"
    "flex-direction:column;"
    "gap:0.24rem;"
)
_LANE_LABEL_STYLE = (
    "display:block;"
    "color:var(--text-muted, #7b9cab);"
    "font-size:0.66rem;"
    "font-weight:850;"
    "letter-spacing:0.05em;"
    "line-height:1.2;"
    "text-transform:uppercase;"
    "overflow-wrap:anywhere;"
)
_LANE_STATE_STYLE = (
    "display:block;"
    "color:var(--text-primary, #eef8fb);"
    "font-size:1.02rem;"
    "font-weight:850;"
    "line-height:1.2;"
    "overflow-wrap:anywhere;"
)
_LANE_VALUE_STYLE = (
    "display:block;"
    "color:var(--accent2, #8deeff);"
    "font-size:0.9rem;"
    "font-weight:800;"
    "line-height:1.25;"
    "overflow-wrap:anywhere;"
)


build_mart_control_room_summary_sql = _lazy_util("build_mart_control_room_summary_sql")
format_snowflake_error = _lazy_util("format_snowflake_error")
run_query = _lazy_util("run_query")
safe_identifier = _lazy_util("safe_identifier")
sql_literal = _lazy_util("sql_literal")
render_mode_selector = _lazy_util("render_mode_selector")
render_workflow_selector = _lazy_util("render_workflow_selector")
render_priority_dataframe = _lazy_util("render_priority_dataframe")


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


WORKLOAD_OPERATIONS_VIEWS = ("Workload Brief", "Specialist Workflows")
WORKLOAD_OPERATIONS_VIEW_DETAILS = {
    "Workload Brief": "Default cockpit: status strip, KPI row, and task/job lanes without loading every specialist workflow.",
    "Specialist Workflows": "Open live triage, query diagnosis, task graphs, stored procedures, pipeline health, or history search when evidence needs drilldown.",
}
WORKLOAD_OPERATIONS_FAST_ENTRY_VERSION = "2026-06-06-fast-brief-v1"
WORKLOAD_OPERATIONS_EXPLICIT_WORKFLOW_KEY = "_workload_operations_explicit_workflow_request"

WORKFLOWS = (
    "Live triage",
    "Contention Center",
    "Query diagnosis",
    "Task graphs",
    "Stored procedures",
    "Pipeline health",
)

WORKFLOW_DETAILS = {
    "Live triage": "What is running, queued, blocked, or failing right now.",
    "Contention Center": "Prove lock waits, task overlap, long DML, or warehouse queueing and pick the safest fix.",
    "Query diagnosis": "Slow, spilling, expensive, failed, scan-heavy SQL, root cause, plan steps, and history search.",
    "Task graphs": "Workflow/DAG status, failures, retries, SLA, and admin control.",
    "Stored procedures": "Procedure CALL history, runtime drift, lineage, and cost attribution.",
    "Pipeline health": "Load health, copy patterns, task/pipeline signals, and backlog.",
}

WORKFLOW_MODULES = {
    "Live triage": "sections.live_monitor",
    "Contention Center": "sections.contention_center",
    "Query diagnosis": "sections.query_analysis",
    "Task graphs": "sections.task_management",
    "Stored procedures": "sections.stored_proc_tracker",
    "Pipeline health": "sections.pipeline_health",
}

CONSOLIDATED_WORKFLOW_ALIASES = {
    "History search": ("Query diagnosis", "History Search"),
    "History Search": ("Query diagnosis", "History Search"),
    "Root cause patterns": ("Query diagnosis", "Root-Cause Brief"),
    "Detailed diagnosis": ("Query diagnosis", "Detailed Diagnosis"),
    "AI Diagnosis": ("Query diagnosis", "AI Diagnosis"),
}

LEGACY_WORKFLOW_MAP = {
    "Diagnosis": "Query diagnosis",
    "History Search": "Query diagnosis",
    "AI Diagnosis": "Query diagnosis",
    "Live Triage": "Live triage",
    "Contention": "Contention Center",
    "Patterns": "Query diagnosis",
}

WORKLOAD_STATUS_LANES = (
    {
        "label": "Task / job status",
        "workflow": "Task graphs",
        "button": "Open Task Graphs",
        "detail": "Snowflake task and Snowflake task runs, retries, SLA risk, downstream impact, and owner.",
    },
    {
        "label": "Performance indicators",
        "workflow": "Query diagnosis",
        "button": "Open Query Diagnosis",
        "detail": "P95 runtime, queue pressure, spill, warehouse context, and high-cost SQL patterns.",
    },
    {
        "label": "Contention",
        "workflow": "Contention Center",
        "button": "Open Contention",
        "detail": "Lock waits, overlapping tasks, long DML, warehouse queueing, and safe fix guidance.",
    },
    {
        "label": "Errors",
        "workflow": "Live triage",
        "button": "Open Live Triage",
        "detail": "Failed work, blocked work, cancellable queries, and exact error evidence.",
    },
)


def _apply_fast_entry_default() -> None:
    """Keep first navigation fast after older sessions auto-opened live triage."""
    explicit_workflow_request = bool(st.session_state.pop(WORKLOAD_OPERATIONS_EXPLICIT_WORKFLOW_KEY, False))
    if st.session_state.get("_workload_operations_fast_entry_version") == WORKLOAD_OPERATIONS_FAST_ENTRY_VERSION:
        return
    if st.session_state.get("workload_operations_view") == "Specialist Workflows" and not explicit_workflow_request:
        st.session_state["workload_operations_view"] = WORKLOAD_OPERATIONS_VIEWS[0]
    st.session_state["_workload_operations_fast_entry_version"] = WORKLOAD_OPERATIONS_FAST_ENTRY_VERSION


def _normalize_workload_workflow_state() -> None:
    current = str(st.session_state.get("workload_operations_workflow") or "")
    mapped = CONSOLIDATED_WORKFLOW_ALIASES.get(current)
    if not mapped:
        return
    workflow, query_view = mapped
    st.session_state["workload_operations_workflow"] = workflow
    st.session_state["query_analysis_active_view"] = query_view


def _apply_workload_evidence_mode_defaults(mode: str) -> None:
    marker_key = "_workload_operations_evidence_mode_defaults"
    if st.session_state.get(marker_key) == mode:
        return
    if mode == TRIAGE_MODE_TRIAGE:
        st.session_state.setdefault("workload_operations_workflow", "Live triage")
    elif mode == TRIAGE_MODE_INVESTIGATE:
        st.session_state["workload_operations_view"] = "Specialist Workflows"
        st.session_state["workload_operations_workflow"] = "Contention Center"
    elif mode == TRIAGE_MODE_ALL_EVIDENCE:
        st.session_state["workload_operations_view"] = "Specialist Workflows"
        st.session_state["workload_operations_workflow"] = "Query diagnosis"
        st.session_state["query_analysis_active_view"] = "Root-Cause Brief"
    st.session_state[marker_key] = mode


def _snapshot_meta(company: str, environment: str, hours: int = 24) -> dict:
    return {"company": company, "environment": environment, "hours": int(hours)}


def _snapshot_meta_matches(meta: Mapping | None, expected: Mapping) -> bool:
    if not isinstance(meta, Mapping):
        return False
    return all(meta.get(key) == value for key, value in expected.items())


def _build_workload_task_status_sql(company: str, environment: str, *, hours: int = 24) -> str:
    return f"""
        SELECT
            COUNT(*) AS TASK_STATUS_ROWS,
            COUNT_IF(
                UPPER(COALESCE(STATE, '')) IN ('FAILED', 'FAILED_WITH_ERROR', 'CANCELLED')
                OR ERROR_MESSAGE IS NOT NULL
            ) AS TASK_STATUS_FAILURE_ROWS,
            COUNT_IF(
                DATEDIFF('minute', SCHEDULED_TIME, COALESCE(COMPLETED_TIME, CURRENT_TIMESTAMP())) > 60
                AND UPPER(COALESCE(STATE, '')) NOT IN ('SUCCEEDED', 'SUCCESS', 'COMPLETED')
            ) AS TASK_STATUS_LATE_ROWS,
            COUNT_IF(
                UPPER(COALESCE(STATE, '')) IN ('FAILED', 'FAILED_WITH_ERROR', 'CANCELLED')
                OR ERROR_MESSAGE IS NOT NULL
            ) AS TASK_STATUS_ALERT_ROWS,
            COUNT_IF(
                UPPER(COALESCE(STATE, '')) IN ('SKIPPED', 'SCHEDULED')
                OR (
                    DATEDIFF('minute', SCHEDULED_TIME, COALESCE(COMPLETED_TIME, CURRENT_TIMESTAMP())) > 30
                    AND UPPER(COALESCE(STATE, '')) NOT IN ('SUCCEEDED', 'SUCCESS', 'COMPLETED')
                )
            ) AS TASK_STATUS_WATCH_ROWS,
            MAX(COALESCE(COMPLETED_TIME, QUERY_START_TIME, SCHEDULED_TIME)) AS TASK_STATUS_LAST_SEEN_AT
        FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
        WHERE SCHEDULED_TIME >= DATEADD('hour', -{int(hours)}, CURRENT_TIMESTAMP())
    """


def _load_workload_task_snapshot(company: str, environment: str, *, hours: int = 24) -> None:
    try:
        snapshot = run_query(
            _build_workload_task_status_sql(company, environment, hours=hours),
            ttl_key=f"workload_operations_task_snapshot_{company}_{environment}_{hours}",
            tier="metadata",
            section="Workload Operations",
        )
        st.session_state["workload_operations_task_snapshot"] = snapshot
        st.session_state["workload_operations_task_snapshot_meta"] = with_loaded_at(
            _snapshot_meta(company, environment, hours),
            source="Snowflake TASK_HISTORY status summary",
        )
        st.session_state["workload_operations_task_snapshot_error"] = ""
    except Exception as exc:
        st.session_state["workload_operations_task_snapshot"] = None
        st.session_state["workload_operations_task_snapshot_meta"] = with_loaded_at(
            _snapshot_meta(company, environment, hours),
            source="Snowflake TASK_HISTORY status summary",
        )
        st.session_state["workload_operations_task_snapshot_error"] = format_snowflake_error(exc)


def _load_workload_snapshot(company: str, environment: str, *, hours: int = 24, show_errors: bool = False) -> None:
    try:
        snapshot = run_query(
            build_mart_control_room_summary_sql(hours, company),
            ttl_key=f"workload_operations_snapshot_{company}_{environment}_{hours}",
            tier="historical",
            section="Workload Operations",
        )
        st.session_state["workload_operations_snapshot"] = snapshot
        st.session_state["workload_operations_snapshot_meta"] = with_loaded_at(
            _snapshot_meta(company, environment, hours),
            source="Fast workload mart summary",
        )
        st.session_state["workload_operations_snapshot_error"] = ""
    except Exception as exc:
        st.session_state["workload_operations_snapshot"] = None
        st.session_state["workload_operations_snapshot_meta"] = with_loaded_at(
            _snapshot_meta(company, environment, hours),
            source="Fast workload mart summary",
        )
        st.session_state["workload_operations_snapshot_error"] = format_snowflake_error(exc)
        if show_errors:
            st.info("Workload snapshot unavailable. Start with live triage or retry after source access is available.")
            defer_source_note("Workload snapshot unavailable.", st.session_state["workload_operations_snapshot_error"])
    _load_workload_task_snapshot(company, environment, hours=hours)


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


def _workload_task_summary(snapshot) -> dict:
    if snapshot is None or getattr(snapshot, "empty", True):
        return {
            "loaded": False,
            "task_status_rows": 0,
            "task_status_failures": 0,
            "task_status_late": 0,
            "task_status_alerts": 0,
            "task_status_watch": 0,
            "last_seen": "",
        }
    row = snapshot.iloc[0].to_dict()
    return {
        "loaded": True,
        "task_status_rows": safe_int(row.get("TASK_STATUS_ROWS")),
        "task_status_failures": safe_int(row.get("TASK_STATUS_FAILURE_ROWS")),
        "task_status_late": safe_int(row.get("TASK_STATUS_LATE_ROWS")),
        "task_status_alerts": safe_int(row.get("TASK_STATUS_ALERT_ROWS")),
        "task_status_watch": safe_int(row.get("TASK_STATUS_WATCH_ROWS")),
        "last_seen": str(row.get("TASK_STATUS_LAST_SEEN_AT") or ""),
    }


def _workload_status_lanes(summary: dict, task_summary: dict | None = None) -> list[dict]:
    """Summarize the three live workload questions managers ask first."""
    loaded = bool(summary.get("loaded"))
    failed = safe_int(summary.get("failed"))
    queued = safe_int(summary.get("queued"))
    spill = safe_int(summary.get("spill"))
    p95 = safe_float(summary.get("p95"))
    task_summary = task_summary or {}
    task_loaded = bool(task_summary.get("loaded"))
    task_status_rows = safe_int(task_summary.get("task_status_rows"))
    task_status_failures = safe_int(task_summary.get("task_status_failures"))
    task_status_late = safe_int(task_summary.get("task_status_late"))
    task_status_alerts = safe_int(task_summary.get("task_status_alerts"))
    task_status_watch = safe_int(task_summary.get("task_status_watch"))

    lanes = []
    for lane in WORKLOAD_STATUS_LANES:
        label = str(lane["label"])
        state = "Open live view"
        value = "Live route"
        if label == "Task / job status" and task_loaded:
            if task_status_failures:
                state = "Review"
                value = f"{task_status_failures:,} failed or blocked"
            elif task_status_late:
                state = "SLA Risk"
                value = f"{task_status_late:,} late or missed"
            elif task_status_alerts:
                state = "Review"
                value = f"{task_status_alerts:,} task alert"
            elif task_status_watch:
                state = "Watch"
                value = f"{task_status_watch:,} watch row"
            elif task_status_rows:
                state = "Ready"
                value = f"{task_status_rows:,} task runs"
            else:
                state = "No runs"
                value = "Open task graph"
        elif loaded and label == "Task / job status":
            state = "Open live view"
            value = "Task graph"
        elif loaded and label == "Performance indicators":
            state = "Review" if queued or spill or p95 >= 60.0 else "Ready"
            value = f"p95 {p95:,.1f}s"
        elif loaded and label == "Errors":
            state = "Review" if failed else "Ready"
            value = f"{failed:,} failed"
        lanes.append({
            **lane,
            "state": state,
            "value": value,
        })
    return lanes


def _workload_action_brief(
    summary: dict,
    *,
    snapshot_current: bool = True,
    error: str = "",
    task_summary: dict | None = None,
) -> dict:
    task_summary = task_summary or {}
    task_loaded = bool(task_summary.get("loaded"))
    task_failures = safe_int(task_summary.get("task_status_failures"))
    task_late = safe_int(task_summary.get("task_status_late"))
    task_alerts = safe_int(task_summary.get("task_status_alerts"))
    task_watch = safe_int(task_summary.get("task_status_watch"))
    task_rows = safe_int(task_summary.get("task_status_rows"))
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
    if task_loaded and task_failures > 0:
        return {
            "state": "Job Review",
            "headline": "Review failed or blocked Snowflake task jobs before query drilldown.",
            "detail": f"{task_failures:,} failed/blocked task run(s) in Snowflake TASK_HISTORY.",
            "primary_label": "Open Task Graphs",
            "workflow": "Task graphs",
            "refresh": False,
        }
    if task_loaded and task_late > 0:
        return {
            "state": "SLA Risk",
            "headline": "Check late or missed task runs before declaring the workload healthy.",
            "detail": f"{task_late:,} late, missed, overdue, or SLA-risk Snowflake task run(s) in TASK_HISTORY.",
            "primary_label": "Open Task Graphs",
            "workflow": "Task graphs",
            "refresh": False,
        }
    if task_loaded and task_alerts > 0:
        return {
            "state": "Job Review",
            "headline": "Review high-severity Snowflake task alerts before query drilldown.",
            "detail": f"{task_alerts:,} Snowflake task alert run(s) in TASK_HISTORY.",
            "primary_label": "Open Task Graphs",
            "workflow": "Task graphs",
            "refresh": False,
        }
    if task_loaded and task_watch > 0 and safe_int(summary.get("failed")) == 0:
        return {
            "state": "Job Watch",
            "headline": "Check task watch rows and Snowflake task status.",
            "detail": f"{task_watch:,} Snowflake task watch row(s) across {task_rows:,} recent task run(s).",
            "primary_label": "Open Task Graphs",
            "workflow": "Task graphs",
            "refresh": False,
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


def _build_workload_runbook_markdown(
    company: str,
    environment: str,
    summary: dict,
    brief: dict,
    task_summary: dict | None = None,
) -> str:
    loaded = bool(summary.get("loaded"))
    task_summary = task_summary or {}
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
    if task_summary.get("loaded"):
        task_line = (
            f"Snowflake TASK_HISTORY runs={safe_int(task_summary.get('task_status_rows')):,}; "
            f"failed_blocked={safe_int(task_summary.get('task_status_failures')):,}; "
            f"late_or_missed={safe_int(task_summary.get('task_status_late')):,}; "
            f"alerts={safe_int(task_summary.get('task_status_alerts')):,}; "
            f"watch={safe_int(task_summary.get('task_status_watch')):,}; "
            f"last_seen={task_summary.get('last_seen') or 'not reported'}"
        )
    else:
        task_line = "Snowflake TASK_HISTORY snapshot not loaded; open Task graphs for task status."

    lines = [
        "# OVERWATCH Workload Operations Runbook",
        "",
        f"- Scope: {company} / {environment}",
        "- Window: 24 hours",
        f"- Generated: {generated_at}",
        f"- Snapshot: {kpi_line}",
        f"- Task/job status: {task_line}",
        f"- Current signal: {brief.get('state') or 'Review'}",
        f"- Operator move: {brief.get('headline') or 'Review workload evidence.'}",
        f"- Detail: {brief.get('detail') or 'No detail loaded.'}",
        "",
        "## Slide Bullets",
        f"- Workload posture: {brief.get('state') or 'Review'} for {company} / {environment}.",
        f"- KPI line: {kpi_line}",
        f"- Task/job line: {task_line}",
        f"- First action: {brief.get('primary_label') or 'Open Live Triage'}.",
        f"- Evidence owner: route to {brief.get('workflow') or 'Live triage'} in Workload Operations.",
        "",
        "## Triage Order",
        "1. Live triage: identify running, queued, blocked, or cancellable work.",
        "2. Query diagnosis: capture query ID, warehouse, user, role, database, schema, elapsed time, spill, and error text.",
        "3. Task graphs: confirm Snowflake task and Snowflake task status, failed run, retry state, downstream blast radius, and owner.",
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
    render_shell_status_strip(
        state=brief.get("state") or "Review",
        headline=brief.get("headline") or "Review workload evidence.",
        detail=brief.get("detail") or "",
    )


def _render_workload_metric_rows(summary: dict) -> None:
    loaded = bool(summary.get("loaded"))
    if not loaded:
        render_shell_kpi_row((
            ("Scope", "Company"),
            ("Window", "24h"),
            ("Evidence", "Refresh"),
            ("Route", "Live triage"),
        ))
        return
    render_shell_kpi_row((
        ("Queries", f"{safe_int(summary.get('queries')):,}"),
        ("Failed", f"{safe_int(summary.get('failed')):,}"),
        ("Queued", f"{safe_int(summary.get('queued')):,}"),
        ("P95", f"{safe_float(summary.get('p95')):,.1f}s"),
    ))


def _render_workload_lane_card(lane: dict) -> None:
    label = html.escape(str(lane.get("label") or "Live lane"))
    state = html.escape(str(lane.get("state") or "Review"))
    value = html.escape(str(lane.get("value") or "Live route"))
    st.markdown(
        (
            f'<div class="ow-workload-lane-card" style="{_LANE_CARD_STYLE}">'
            f'<span class="ow-workload-lane-label" style="{_LANE_LABEL_STYLE}">{label}</span>'
            f'<strong class="ow-workload-lane-state" style="{_LANE_STATE_STYLE}">{state}</strong>'
            f'<span class="ow-workload-lane-value" style="{_LANE_VALUE_STYLE}">{value}</span>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _render_workload_status_lanes(summary: dict, task_summary: dict | None = None) -> None:
    st.markdown("**Live Workload Lanes**")
    lanes = _workload_status_lanes(summary, task_summary)
    columns = 4
    for start in range(0, len(lanes), columns):
        row = lanes[start:start + columns]
        cols = st.columns(len(row))
        for offset, lane in enumerate(row):
            idx = start + offset
            with cols[offset]:
                with st.container(border=True):
                    _render_workload_lane_card(lane)
                    if st.button(
                        str(lane.get("button") or "Open"),
                        key=f"workload_ops_lane_{idx}",
                        help=str(lane.get("detail") or "Open the lane for current workload evidence."),
                        width="stretch",
                    ):
                        workflow = str(lane.get("workflow") or "Live triage")
                        if workflow in WORKFLOWS:
                            st.session_state["workload_operations_view"] = "Specialist Workflows"
                            st.session_state["workload_operations_workflow"] = workflow
                            st.rerun()


def _render_workload_intelligence_contract(company: str, environment: str) -> None:
    """Show the no-touch workload intelligence contracts before drilldown."""
    import pandas as pd

    from utils.operational_intelligence import (
        build_ai_query_diagnosis_contract_rows,
        build_data_reconciliation_runner_sql,
        build_task_critical_path_brain_sql,
    )

    rows = pd.DataFrame(
        [
            {
                "SIGNAL": "Task critical path",
                "STATE": "Ready",
                "PRIMARY_SOURCE": "TASK_HISTORY / INFORMATION_SCHEMA.TASK_HISTORY",
                "WHY_IT_MATTERS": "Ranks failed, skipped, late, and long-running task graph paths before retry.",
                "NEXT_ACTION": "Open Task graphs when a root task, child failure, or SLA risk appears.",
            },
            {
                "SIGNAL": "Schema/data reconciliation",
                "STATE": "Config-driven",
                "PRIMARY_SOURCE": "INFORMATION_SCHEMA plus configured table checks",
                "WHY_IT_MATTERS": "Compares row counts and hashes between database/schema pairs for sameness and likeness.",
                "NEXT_ACTION": "Use DBA Tools data compare for target tables, then persist results in recon tables.",
            },
            {
                "SIGNAL": "Fact-grounded AI query diagnosis",
                "STATE": "Guarded",
                "PRIMARY_SOURCE": "QUERY_HISTORY, profile facts, object context",
                "WHY_IT_MATTERS": "Cortex recommendations must cite exact scan, spill, pruning, queue, and owner evidence.",
                "NEXT_ACTION": "Open Query diagnosis only after a query_id or repeatable query hash is identified.",
            },
        ]
    )
    render_priority_dataframe(
        rows,
        title="Workload intelligence contracts",
        priority_columns=[
            "SIGNAL", "STATE", "PRIMARY_SOURCE", "WHY_IT_MATTERS", "NEXT_ACTION",
        ],
        raw_label="All workload intelligence contracts",
        height=220,
        max_rows=3,
    )
    with st.expander("Workload intelligence SQL and AI evidence contract", expanded=False):
        sql_choice = st.selectbox(
            "Preview",
            ["Task critical path SQL", "Data reconciliation SQL", "AI query diagnosis evidence"],
            key="workload_intelligence_contract_preview",
        )
        if sql_choice == "Task critical path SQL":
            st.code(build_task_critical_path_brain_sql(hours=24), language="sql")
        elif sql_choice == "Data reconciliation SQL":
            st.code(build_data_reconciliation_runner_sql(), language="sql")
        else:
            render_priority_dataframe(
                pd.DataFrame(build_ai_query_diagnosis_contract_rows()),
                title="AI Query Diagnosis required evidence",
                priority_columns=["EVIDENCE", "REQUIRED_FIELDS", "WHY_REQUIRED"],
                raw_label="All AI query evidence fields",
                height=280,
                max_rows=6,
            )
    defer_source_note(
        f"Workload intelligence contract shown for {company} / {environment}; SQL previews do not execute until the workflow is loaded."
    )


def _render_workload_snapshot(company: str, environment: str) -> None:
    hours = 24
    expected_meta = _snapshot_meta(company, environment, hours)
    snapshot = st.session_state.get("workload_operations_snapshot")
    snapshot_meta = st.session_state.get("workload_operations_snapshot_meta")
    snapshot_current = _snapshot_meta_matches(snapshot_meta, expected_meta)
    task_snapshot = st.session_state.get("workload_operations_task_snapshot")
    task_snapshot_meta = st.session_state.get("workload_operations_task_snapshot_meta")
    task_snapshot_current = _snapshot_meta_matches(task_snapshot_meta, expected_meta)
    if (
        consume_section_autoload_request("Workload Operations")
        and not (snapshot_current and task_snapshot_current)
    ):
        st.caption("Workload Operations opened in fast mode. Refresh the snapshot when current task/query proof is needed.")
    err = st.session_state.get("workload_operations_snapshot_error", "")
    summary = _workload_snapshot_summary(snapshot if snapshot_current else None)
    task_summary = _workload_task_summary(task_snapshot if task_snapshot_current else None)
    freshness_meta = {}
    if summary.get("loaded") and snapshot_current:
        freshness_meta = snapshot_meta if isinstance(snapshot_meta, Mapping) else {}
    elif task_summary.get("loaded") and task_snapshot_current:
        freshness_meta = task_snapshot_meta if isinstance(task_snapshot_meta, Mapping) else {}
    brief = _workload_action_brief(
        summary,
        snapshot_current=snapshot_current,
        error=str(err or ""),
        task_summary=task_summary,
    )
    _render_workload_action_brief(company, environment, brief)
    _render_workload_metric_rows(summary)
    render_data_freshness(
        freshness_meta,
        source="Workload snapshot",
        target_minutes=30,
        delayed_note="Workload snapshot uses mart and TASK_HISTORY summaries; open live triage for in-flight incidents.",
    )
    if err and not summary.get("loaded"):
        defer_source_note("Workload snapshot unavailable.", str(err))
    if st.button("Refresh Workload Snapshot", key="workload_operations_snapshot_refresh", type="primary"):
        _load_workload_snapshot(company, environment, hours=hours)
        st.rerun()
    _render_workload_status_lanes(summary, task_summary)
    _render_workload_intelligence_contract(company, environment)
    with st.expander("Runbook export", expanded=False):
        st.caption("Download a copy-ready DBA runbook for the selected company and workload snapshot state.")
        st.download_button(
            "Download DBA runbook",
            data=_build_workload_runbook_markdown(company, environment, summary, brief, task_summary),
            file_name=_workload_runbook_filename(company, environment),
            mime="text/markdown",
            key="workload_ops_runbook_download",
        )


def render() -> None:
    company = get_active_company()
    environment = get_active_environment()
    evidence_mode = current_evidence_mode(st.session_state)
    _apply_fast_entry_default()
    _normalize_workload_workflow_state()
    _apply_workload_evidence_mode_defaults(evidence_mode)
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
    if evidence_mode == TRIAGE_MODE_TRIAGE:
        st.warning("Landing default: start with running work, failures, SLA breaches, and release regressions.")
    elif evidence_mode == TRIAGE_MODE_INVESTIGATE:
        defer_section_note("Investigation detail opens specialist workflows for contention and root-cause analysis.")
    elif evidence_mode == TRIAGE_MODE_ALL_EVIDENCE:
        defer_section_note("Full proof depth opens Query diagnosis with root-cause context ready.")

    active_view = render_mode_selector(
        "Workload Operations view",
        "workload_operations_view",
        WORKLOAD_OPERATIONS_VIEWS,
        default=WORKLOAD_OPERATIONS_VIEWS[0],
        details=WORKLOAD_OPERATIONS_VIEW_DETAILS,
        columns=2,
    )
    if active_view == "Workload Brief":
        return

    render_workflow_guide(
        "Start with live triage. Move into contention, query diagnosis, task graphs, or stored procedure tracking only when "
        "the signal requires deeper evidence or an admin action.",
        [
            ("A job is late or failed", "Use Task graphs, then drill into the stored procedure and query IDs."),
            ("A table or task is bottlenecked", "Use Contention Center to separate lock waits from warehouse queueing before resizing."),
            ("A release increased runtime", "Use Stored procedures and the DBA Control Room release compare."),
            ("A warehouse is under pressure", "Use Live triage first, then Cost & Contract capacity evidence."),
            ("A user asks what happened", "Use Query diagnosis history search to find and document evidence."),
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
