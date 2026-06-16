# sections/workload_operations.py - consolidated DBA workload command center
from __future__ import annotations

from collections.abc import Mapping, Sequence
from importlib import import_module

import streamlit as st

from sections.base import lazy_util as _lazy_util
from utils.evidence_mode import (
    TRIAGE_MODE_ALL_EVIDENCE,
    TRIAGE_MODE_INVESTIGATE,
    TRIAGE_MODE_TRIAGE,
    current_evidence_mode,
)
from utils.section_guidance import defer_section_note

render_mode_selector = _lazy_util("render_mode_selector")
render_workflow_selector = _lazy_util("render_workflow_selector")


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


WORKLOAD_OPERATIONS_FAST_ENTRY_VERSION = "2026-06-16-workload-board-v1"
WORKLOAD_OPERATIONS_EXPLICIT_WORKFLOW_KEY = "_workload_operations_explicit_workflow_request"
QUERY_TRIAGE_WORKFLOW = "Query & contention triage"
PIPELINE_HEALTH_WORKFLOW = "Task, procedure & pipeline health"
TRIAGE_FOCUS_KEY = "workload_operations_triage_focus"
PIPELINE_FOCUS_KEY = "workload_operations_pipeline_focus"

WORKFLOWS = (
    QUERY_TRIAGE_WORKFLOW,
    PIPELINE_HEALTH_WORKFLOW,
)

TRIAGE_FOCI = (
    "Live triage",
    "Contention Center",
    "Query diagnosis",
)

PIPELINE_FOCI = (
    "Task graphs",
    "Stored procedures",
    "Pipeline health",
)

WORKFLOW_DETAILS = {
    QUERY_TRIAGE_WORKFLOW: "One path for running work, queue pressure, failed SQL, slow SQL, spill, blockers, and safe contention fixes.",
    PIPELINE_HEALTH_WORKFLOW: "One path for Snowflake task graphs, procedure drift, load health, backlog, and recovery order.",
}

TRIAGE_FOCUS_DETAILS = {
    "Live triage": "What is running, queued, blocked, or failing right now.",
    "Contention Center": "Lock waits, task overlap, long DML, warehouse queueing, and safe fix guidance.",
    "Query diagnosis": "Slow, spilling, expensive, failed, scan-heavy SQL, root cause, plan steps, and history search.",
}

PIPELINE_FOCUS_DETAILS = {
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
    "Live triage": (QUERY_TRIAGE_WORKFLOW, "Live triage", ""),
    "Contention Center": (QUERY_TRIAGE_WORKFLOW, "Contention Center", ""),
    "Query diagnosis": (QUERY_TRIAGE_WORKFLOW, "Query diagnosis", ""),
    "History search": (QUERY_TRIAGE_WORKFLOW, "Query diagnosis", "History Search"),
    "History Search": (QUERY_TRIAGE_WORKFLOW, "Query diagnosis", "History Search"),
    "Root cause patterns": (QUERY_TRIAGE_WORKFLOW, "Query diagnosis", "Root-Cause Brief"),
    "Detailed diagnosis": (QUERY_TRIAGE_WORKFLOW, "Query diagnosis", "Detailed Diagnosis"),
    "AI Diagnosis": (QUERY_TRIAGE_WORKFLOW, "Query diagnosis", "AI Diagnosis"),
    "Task graphs": (PIPELINE_HEALTH_WORKFLOW, "Task graphs", ""),
    "Stored procedures": (PIPELINE_HEALTH_WORKFLOW, "Stored procedures", ""),
    "Pipeline health": (PIPELINE_HEALTH_WORKFLOW, "Pipeline health", ""),
}

LEGACY_WORKFLOW_MAP = {
    "Diagnosis": "Query diagnosis",
    "History Search": "History Search",
    "AI Diagnosis": "AI Diagnosis",
    "Live Triage": "Live triage",
    "Contention": "Contention Center",
    "Patterns": "Root cause patterns",
}


def _apply_fast_entry_default() -> None:
    """Keep first navigation fast after older sessions auto-opened live triage."""
    st.session_state.pop(WORKLOAD_OPERATIONS_EXPLICIT_WORKFLOW_KEY, None)
    if st.session_state.get("_workload_operations_fast_entry_version") == WORKLOAD_OPERATIONS_FAST_ENTRY_VERSION:
        return
    st.session_state["_workload_operations_fast_entry_version"] = WORKLOAD_OPERATIONS_FAST_ENTRY_VERSION


def _normalize_workload_workflow_state() -> None:
    current = str(st.session_state.get("workload_operations_workflow") or "")
    mapped = CONSOLIDATED_WORKFLOW_ALIASES.get(current)
    if not mapped:
        return
    workflow, focus, query_view = mapped
    st.session_state["workload_operations_workflow"] = workflow
    if focus in TRIAGE_FOCI:
        st.session_state[TRIAGE_FOCUS_KEY] = focus
    elif focus in PIPELINE_FOCI:
        st.session_state[PIPELINE_FOCUS_KEY] = focus
    if query_view:
        st.session_state["query_analysis_active_view"] = query_view


def _apply_workload_evidence_mode_defaults(mode: str) -> None:
    marker_key = "_workload_operations_evidence_mode_defaults"
    if st.session_state.get(marker_key) == mode:
        return
    if mode == TRIAGE_MODE_TRIAGE:
        st.session_state.setdefault("workload_operations_workflow", QUERY_TRIAGE_WORKFLOW)
        st.session_state.setdefault(TRIAGE_FOCUS_KEY, "Live triage")
    elif mode == TRIAGE_MODE_INVESTIGATE:
        st.session_state["workload_operations_workflow"] = QUERY_TRIAGE_WORKFLOW
        st.session_state[TRIAGE_FOCUS_KEY] = "Contention Center"
    elif mode == TRIAGE_MODE_ALL_EVIDENCE:
        st.session_state["workload_operations_workflow"] = QUERY_TRIAGE_WORKFLOW
        st.session_state[TRIAGE_FOCUS_KEY] = "Query diagnosis"
        st.session_state["query_analysis_active_view"] = "Root-Cause Brief"
    st.session_state[marker_key] = mode


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


def _render_query_contention_triage() -> None:
    if st.session_state.get(TRIAGE_FOCUS_KEY) not in TRIAGE_FOCI:
        st.session_state[TRIAGE_FOCUS_KEY] = TRIAGE_FOCI[0]
    focus = render_mode_selector(
        "Triage focus",
        TRIAGE_FOCUS_KEY,
        TRIAGE_FOCI,
        default=TRIAGE_FOCI[0],
        details=TRIAGE_FOCUS_DETAILS,
        columns=3,
    )
    if focus == "Query diagnosis" and st.session_state.pop("workload_query_diagnosis_mode", "") == "Detailed diagnosis":
        st.session_state["query_analysis_active_view"] = "Detailed Diagnosis"
    render_workflow_module(focus, WORKFLOW_MODULES)


def _render_task_pipeline_health() -> None:
    if st.session_state.get(PIPELINE_FOCUS_KEY) not in PIPELINE_FOCI:
        st.session_state[PIPELINE_FOCUS_KEY] = PIPELINE_FOCI[0]
    focus = render_mode_selector(
        "Pipeline focus",
        PIPELINE_FOCUS_KEY,
        PIPELINE_FOCI,
        default=PIPELINE_FOCI[0],
        details=PIPELINE_FOCUS_DETAILS,
        columns=3,
    )
    render_workflow_module(focus, WORKFLOW_MODULES)


def render() -> None:
    evidence_mode = current_evidence_mode(st.session_state)
    _apply_fast_entry_default()
    _apply_workload_evidence_mode_defaults(evidence_mode)
    if st.session_state.get("exceptions_only_mode") and "workload_operations_workflow" not in st.session_state:
        st.session_state["workload_operations_workflow"] = QUERY_TRIAGE_WORKFLOW
        st.session_state[TRIAGE_FOCUS_KEY] = "Live triage"
    migrate_legacy_workflow_state(
        "query_workbench_workflow",
        "workload_operations_workflow",
        LEGACY_WORKFLOW_MAP,
    )
    _normalize_workload_workflow_state()
    if st.session_state.get("workload_operations_workflow") not in WORKFLOWS:
        st.session_state["workload_operations_workflow"] = QUERY_TRIAGE_WORKFLOW

    if evidence_mode == TRIAGE_MODE_TRIAGE:
        defer_section_note("Start with running work, failures, SLA breaches, and release regressions.")
    elif evidence_mode == TRIAGE_MODE_INVESTIGATE:
        defer_section_note("Investigation detail opens specialist workflows for contention and root-cause analysis.")
    elif evidence_mode == TRIAGE_MODE_ALL_EVIDENCE:
        defer_section_note("Full telemetry depth opens Query diagnosis with root-cause context ready.")

    render_workflow_guide(
        "Pick the investigation intent first. Query and contention triage handles in-flight SQL pressure; task, procedure, "
        "and pipeline health handles job recovery and downstream impact.",
        [
            ("Running, queued, blocked, slow, spilling, or failed SQL", "Use Query and contention triage."),
            ("Late task, failed task, procedure drift, load backlog, or downstream impact", "Use Task, procedure and pipeline health."),
        ],
    )

    workflow = render_workflow_selector(
        "Workload workflow",
        "workload_operations_workflow",
        WORKFLOWS,
        WORKFLOW_DETAILS,
        columns=3,
    )

    if workflow == QUERY_TRIAGE_WORKFLOW:
        _render_query_contention_triage()
    elif workflow == PIPELINE_HEALTH_WORKFLOW:
        _render_task_pipeline_health()
