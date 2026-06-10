# sections/workload_operations.py - consolidated DBA workload command center
from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from importlib import import_module

import streamlit as st

from config import ALERT_DB, ALERT_SCHEMA, DEFAULT_COMPANY, DEFAULT_ENVIRONMENT
from sections.shell_helpers import render_shell_snapshot
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
safe_identifier = _lazy_util("safe_identifier")
sql_literal = _lazy_util("sql_literal")
render_mode_selector = _lazy_util("render_mode_selector")
render_workflow_selector = _lazy_util("render_workflow_selector")


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

WORKLOAD_STATUS_LANES = (
    {
        "label": "Task / job status",
        "workflow": "Task graphs",
        "button": "Open Task Graphs",
        "detail": "Control-M and Snowflake task runs, retries, SLA risk, downstream impact, and owner.",
    },
    {
        "label": "Performance indicators",
        "workflow": "Query diagnosis",
        "button": "Open Query Diagnosis",
        "detail": "P95 runtime, queue pressure, spill, warehouse context, and high-cost SQL patterns.",
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
    if st.session_state.get("_workload_operations_fast_entry_version") == WORKLOAD_OPERATIONS_FAST_ENTRY_VERSION:
        return
    if st.session_state.get("workload_operations_view") == "Specialist Workflows":
        st.session_state["workload_operations_view"] = WORKLOAD_OPERATIONS_VIEWS[0]
    st.session_state["_workload_operations_fast_entry_version"] = WORKLOAD_OPERATIONS_FAST_ENTRY_VERSION


def _snapshot_meta(company: str, environment: str, hours: int = 24) -> dict:
    return {"company": company, "environment": environment, "hours": int(hours)}


def _control_feed_fqn() -> str:
    return (
        f"{safe_identifier(ALERT_DB)}."
        f"{safe_identifier(ALERT_SCHEMA)}."
        f"{safe_identifier('OVERWATCH_EXTERNAL_CONTROL_FEED')}"
    )


def _build_workload_task_status_sql(company: str, environment: str, *, hours: int = 24) -> str:
    company_filter = ""
    if str(company or "").upper() not in {"", "ALL"}:
        company_filter = f"AND COMPANY = {sql_literal(str(company))}"
    environment_filter = ""
    if str(environment or "").upper() not in {"", "ALL"}:
        environment_filter = f"AND COALESCE(ENVIRONMENT, 'No Database Context') = {sql_literal(str(environment))}"
    return f"""
        SELECT
            COUNT(*) AS CONTROL_M_ROWS,
            COUNT_IF(
                UPPER(COALESCE(SEVERITY, '')) IN ('CRITICAL', 'HIGH')
                OR REGEXP_LIKE(UPPER(COALESCE(STATUS, '')), 'FAIL|ERROR|CANCEL|BLOCK|MISSED|LATE')
            ) AS CONTROL_M_ALERT_ROWS,
            COUNT_IF(
                UPPER(COALESCE(SEVERITY, '')) = 'MEDIUM'
                OR REGEXP_LIKE(UPPER(COALESCE(STATUS, '')), 'WARN|DELAY|DEGRADED|SUSPENDED|WATCH')
            ) AS CONTROL_M_WATCH_ROWS,
            MAX(LAST_SEEN_AT) AS CONTROL_M_LAST_SEEN_AT
        FROM {_control_feed_fqn()}
        WHERE UPPER(COALESCE(SOURCE_SYSTEM, '')) = 'CONTROL_M'
          AND COALESCE(LAST_SEEN_AT, FEED_TS, CURRENT_TIMESTAMP()) >= DATEADD('hour', -{int(hours)}, CURRENT_TIMESTAMP())
          {company_filter}
          {environment_filter}
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
        st.session_state["workload_operations_task_snapshot_meta"] = _snapshot_meta(company, environment, hours)
        st.session_state["workload_operations_task_snapshot_error"] = ""
    except Exception as exc:
        st.session_state["workload_operations_task_snapshot"] = None
        st.session_state["workload_operations_task_snapshot_meta"] = _snapshot_meta(company, environment, hours)
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
        st.session_state["workload_operations_snapshot_meta"] = _snapshot_meta(company, environment, hours)
        st.session_state["workload_operations_snapshot_error"] = ""
    except Exception as exc:
        st.session_state["workload_operations_snapshot"] = None
        st.session_state["workload_operations_snapshot_meta"] = _snapshot_meta(company, environment, hours)
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
            "controlm_rows": 0,
            "controlm_alerts": 0,
            "controlm_watch": 0,
            "last_seen": "",
        }
    row = snapshot.iloc[0].to_dict()
    return {
        "loaded": True,
        "controlm_rows": safe_int(row.get("CONTROL_M_ROWS")),
        "controlm_alerts": safe_int(row.get("CONTROL_M_ALERT_ROWS")),
        "controlm_watch": safe_int(row.get("CONTROL_M_WATCH_ROWS")),
        "last_seen": str(row.get("CONTROL_M_LAST_SEEN_AT") or ""),
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
    controlm_rows = safe_int(task_summary.get("controlm_rows"))
    controlm_alerts = safe_int(task_summary.get("controlm_alerts"))
    controlm_watch = safe_int(task_summary.get("controlm_watch"))

    lanes = []
    for lane in WORKLOAD_STATUS_LANES:
        label = str(lane["label"])
        state = "Open live view"
        value = "Live route"
        if label == "Task / job status" and task_loaded:
            if controlm_alerts:
                state = "Review"
                value = f"{controlm_alerts:,} scheduler alert"
            elif controlm_watch:
                state = "Watch"
                value = f"{controlm_watch:,} watch row"
            elif controlm_rows:
                state = "Ready"
                value = f"{controlm_rows:,} feed rows"
            else:
                state = "No feed"
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
    task_alerts = safe_int(task_summary.get("controlm_alerts"))
    task_watch = safe_int(task_summary.get("controlm_watch"))
    task_rows = safe_int(task_summary.get("controlm_rows"))
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
    if task_loaded and task_alerts > 0:
        return {
            "state": "Job Review",
            "headline": "Review Control-M task/job alerts before query drilldown.",
            "detail": f"{task_alerts:,} Control-M alert row(s) in the loaded scheduler feed snapshot.",
            "primary_label": "Open Task Graphs",
            "workflow": "Task graphs",
            "refresh": False,
        }
    if task_loaded and task_watch > 0 and safe_int(summary.get("failed")) == 0:
        return {
            "state": "Job Watch",
            "headline": "Check scheduler watch rows and Snowflake task status.",
            "detail": f"{task_watch:,} Control-M watch row(s) across {task_rows:,} loaded scheduler feed row(s).",
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
            f"Control-M feed rows={safe_int(task_summary.get('controlm_rows')):,}; "
            f"alerts={safe_int(task_summary.get('controlm_alerts')):,}; "
            f"watch={safe_int(task_summary.get('controlm_watch')):,}; "
            f"last_seen={task_summary.get('last_seen') or 'not reported'}"
        )
    else:
        task_line = "Control-M feed snapshot not loaded; open Task graphs for Snowflake task status."

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
        "3. Task graphs: confirm Control-M and Snowflake task status, failed run, retry state, downstream blast radius, and owner.",
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
    if not loaded:
        render_shell_snapshot((
            ("Scope", "Company"),
            ("Window", "24h"),
            ("Evidence", "Refresh"),
            ("Route", "Live triage"),
        ))
        return
    render_shell_snapshot((
        ("Queries", f"{safe_int(summary.get('queries')):,}"),
        ("Failed", f"{safe_int(summary.get('failed')):,}"),
        ("Queued", f"{safe_int(summary.get('queued')):,}"),
        ("P95", f"{safe_float(summary.get('p95')):,.1f}s"),
    ))


def _render_workload_lane_card(lane: dict) -> None:
    label = html.escape(str(lane.get("label") or "Live lane"))
    state = html.escape(str(lane.get("state") or "Review"))
    value = html.escape(str(lane.get("value") or "Live route"))
    detail = html.escape(str(lane.get("detail") or "Open the lane for current workload evidence."))
    st.markdown(
        (
            '<div class="ow-workload-lane-card">'
            f'<span class="ow-workload-lane-label">{label}</span>'
            f'<strong class="ow-workload-lane-state">{state}</strong>'
            f'<span class="ow-workload-lane-value">{value}</span>'
            f'<span class="ow-workload-lane-detail">{detail}</span>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _render_workload_status_lanes(summary: dict, task_summary: dict | None = None) -> None:
    st.markdown("**Live Workload Lanes**")
    cols = st.columns(3)
    for idx, lane in enumerate(_workload_status_lanes(summary, task_summary)):
        with cols[idx]:
            with st.container(border=True):
                _render_workload_lane_card(lane)
                if st.button(str(lane.get("button") or "Open"), key=f"workload_ops_lane_{idx}", width="stretch"):
                    workflow = str(lane.get("workflow") or "Live triage")
                    if workflow in WORKFLOWS:
                        st.session_state["workload_operations_view"] = "Specialist Workflows"
                        st.session_state["workload_operations_workflow"] = workflow
                        st.rerun()


def _render_workload_snapshot(company: str, environment: str) -> None:
    hours = 24
    expected_meta = _snapshot_meta(company, environment, hours)
    snapshot = st.session_state.get("workload_operations_snapshot")
    snapshot_current = st.session_state.get("workload_operations_snapshot_meta") == expected_meta
    task_snapshot = st.session_state.get("workload_operations_task_snapshot")
    task_snapshot_current = st.session_state.get("workload_operations_task_snapshot_meta") == expected_meta
    err = st.session_state.get("workload_operations_snapshot_error", "")
    summary = _workload_snapshot_summary(snapshot if snapshot_current else None)
    task_summary = _workload_task_summary(task_snapshot if task_snapshot_current else None)
    brief = _workload_action_brief(
        summary,
        snapshot_current=snapshot_current,
        error=str(err or ""),
        task_summary=task_summary,
    )
    _render_workload_action_brief(company, environment, brief)
    st.markdown("**Operating Snapshot**")
    _render_workload_metric_rows(summary)
    _render_workload_status_lanes(summary, task_summary)
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

    active_view = render_mode_selector(
        "Workload Operations view",
        "workload_operations_view",
        WORKLOAD_OPERATIONS_VIEWS,
        default=WORKLOAD_OPERATIONS_VIEWS[0],
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
