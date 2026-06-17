# sections/workload_operations.py - consolidated DBA workload monitor
from __future__ import annotations

from collections.abc import Mapping, Sequence
from importlib import import_module

import streamlit as st

from sections.base import lazy_util as _lazy_util
from utils.section_guidance import defer_section_note

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
QUERY_INVESTIGATION_WORKFLOW = "Query investigation"
QUERY_CONTENTION_WORKFLOW = QUERY_INVESTIGATION_WORKFLOW
TASK_PROCEDURE_WORKFLOW = "Task & procedure health"
STORED_PROCEDURES_WORKFLOW = "Stored procedures"
PIPELINE_SLA_WORKFLOW = "Pipeline / SLA risk"
SCHEMA_COMPARE_WORKFLOW = "Schema & data compare"
AI_QUERY_DIAGNOSIS_WORKFLOW = QUERY_INVESTIGATION_WORKFLOW
QUERY_FOCUS_KEY = "workload_operations_query_focus"
QUERY_FOCUS_DIAGNOSIS = "AI Query Diagnosis"
QUERY_FOCUS_CONTENTION = "Contention Telemetry"
_LEGACY_TRIAGE_FOCUS_KEY = "workload_operations_triage_focus"
_LEGACY_PIPELINE_FOCUS_KEY = "workload_operations_pipeline_focus"

WORKFLOWS = (
    QUERY_INVESTIGATION_WORKFLOW,
    TASK_PROCEDURE_WORKFLOW,
    STORED_PROCEDURES_WORKFLOW,
    PIPELINE_SLA_WORKFLOW,
    SCHEMA_COMPARE_WORKFLOW,
)

WORKFLOW_DETAILS = {
    QUERY_INVESTIGATION_WORKFLOW: "One front door for running, queued, blocked, slow, spilling, failed, high-cost, and AI-diagnosed SQL.",
    TASK_PROCEDURE_WORKFLOW: "Task graph and procedure health with late runs, failures, retry state, and recovery order.",
    STORED_PROCEDURES_WORKFLOW: "Stored procedure inventory, task linkage, runtime/cost regressions, advisor signals, and child-query drilldown.",
    PIPELINE_SLA_WORKFLOW: "Freshness SLA, load failures, dynamic tables, Snowpipe usage, and downstream backlog.",
    SCHEMA_COMPARE_WORKFLOW: "Schema and data compare for missing objects, row counts, and object/data likeness.",
}

WORKFLOW_MODULES = {
    QUERY_INVESTIGATION_WORKFLOW: "sections.query_analysis",
    TASK_PROCEDURE_WORKFLOW: "sections.task_management",
    STORED_PROCEDURES_WORKFLOW: "sections.stored_proc_tracker",
    PIPELINE_SLA_WORKFLOW: "sections.pipeline_health",
    SCHEMA_COMPARE_WORKFLOW: "sections.dba_tools",
}

QUERY_FOCUS_DETAILS = {
    QUERY_FOCUS_DIAGNOSIS: "Bottlenecks, history search, plan steps, and AI-assisted Snowflake query recommendations.",
    QUERY_FOCUS_CONTENTION: "Live incidents, active locks, historical waits, hotspots, task overlap, long DML, and blocker maps.",
}

QUERY_DIAGNOSIS_ALIASES = {
    "Query diagnosis",
    "History search",
    "History Search",
    "Root cause patterns",
    "Detailed diagnosis",
    "AI Diagnosis",
    "AI query diagnosis",
    "Diagnosis",
    "Patterns",
}

QUERY_CONTENTION_ALIASES = {
    "Query & contention",
    "Query & contention triage",
    "Live triage",
    "Live Triage",
    "Contention",
    "Contention Center",
}

CONSOLIDATED_WORKFLOW_ALIASES = {
    **{alias: QUERY_INVESTIGATION_WORKFLOW for alias in QUERY_DIAGNOSIS_ALIASES},
    **{alias: QUERY_INVESTIGATION_WORKFLOW for alias in QUERY_CONTENTION_ALIASES},
    "Task, procedure & pipeline health": TASK_PROCEDURE_WORKFLOW,
    "Task graphs": TASK_PROCEDURE_WORKFLOW,
    "Stored procedure lineage": STORED_PROCEDURES_WORKFLOW,
    "Pipeline health": PIPELINE_SLA_WORKFLOW,
}

LEGACY_WORKFLOW_MAP = {
    "Diagnosis": QUERY_INVESTIGATION_WORKFLOW,
    "History Search": QUERY_INVESTIGATION_WORKFLOW,
    "AI Diagnosis": QUERY_INVESTIGATION_WORKFLOW,
    "Live Triage": QUERY_INVESTIGATION_WORKFLOW,
    "Contention": QUERY_INVESTIGATION_WORKFLOW,
    "Patterns": QUERY_INVESTIGATION_WORKFLOW,
}


def _apply_fast_entry_default() -> None:
    """Keep first navigation fast after older sessions auto-opened live triage."""
    st.session_state.pop(WORKLOAD_OPERATIONS_EXPLICIT_WORKFLOW_KEY, None)
    if st.session_state.get("_workload_operations_fast_entry_version") == WORKLOAD_OPERATIONS_FAST_ENTRY_VERSION:
        return
    st.session_state["_workload_operations_fast_entry_version"] = WORKLOAD_OPERATIONS_FAST_ENTRY_VERSION


def _normalize_workload_workflow_state() -> None:
    current = str(st.session_state.get("workload_operations_workflow") or "")
    if current in QUERY_CONTENTION_ALIASES:
        st.session_state[QUERY_FOCUS_KEY] = QUERY_FOCUS_CONTENTION
    elif current in QUERY_DIAGNOSIS_ALIASES:
        st.session_state[QUERY_FOCUS_KEY] = QUERY_FOCUS_DIAGNOSIS
    mapped = CONSOLIDATED_WORKFLOW_ALIASES.get(current)
    if mapped:
        st.session_state["workload_operations_workflow"] = mapped
    legacy_focus = str(st.session_state.pop(_LEGACY_TRIAGE_FOCUS_KEY, "") or "")
    pipeline_focus = str(st.session_state.pop(_LEGACY_PIPELINE_FOCUS_KEY, "") or "")
    if legacy_focus in QUERY_CONTENTION_ALIASES:
        st.session_state[QUERY_FOCUS_KEY] = QUERY_FOCUS_CONTENTION
    elif legacy_focus in QUERY_DIAGNOSIS_ALIASES:
        st.session_state[QUERY_FOCUS_KEY] = QUERY_FOCUS_DIAGNOSIS
    focus_workflow = CONSOLIDATED_WORKFLOW_ALIASES.get(legacy_focus) or CONSOLIDATED_WORKFLOW_ALIASES.get(pipeline_focus)
    if focus_workflow and current not in WORKFLOWS:
        st.session_state["workload_operations_workflow"] = focus_workflow


def _render_query_investigation_surface() -> None:
    focus = render_workflow_selector(
        "Query investigation focus",
        QUERY_FOCUS_KEY,
        (QUERY_FOCUS_DIAGNOSIS, QUERY_FOCUS_CONTENTION),
        QUERY_FOCUS_DETAILS,
        columns=2,
    )
    if focus == QUERY_FOCUS_CONTENTION:
        render_workflow_module(QUERY_FOCUS_CONTENTION, {QUERY_FOCUS_CONTENTION: "sections.contention_center"})
        return
    st.session_state.setdefault("query_analysis_active_view", "AI Diagnosis")
    if st.session_state.pop("workload_query_diagnosis_mode", "") == "Detailed diagnosis":
        st.session_state["query_analysis_active_view"] = "Detailed Diagnosis"
    render_workflow_module(QUERY_FOCUS_DIAGNOSIS, {QUERY_FOCUS_DIAGNOSIS: "sections.query_analysis"})


def _render_workload_surface(workflow: str) -> None:
    if workflow == QUERY_INVESTIGATION_WORKFLOW:
        _render_query_investigation_surface()
        return
    if workflow == TASK_PROCEDURE_WORKFLOW:
        st.session_state.setdefault("task_management_view", "Job Status Brief")
    elif workflow == PIPELINE_SLA_WORKFLOW:
        st.session_state.setdefault("pipeline_health_active_view", "Freshness SLA")
    elif workflow == SCHEMA_COMPARE_WORKFLOW:
        st.session_state["dba_tools_focus"] = "Object Monitoring"
        st.session_state["dba_tools_focus_tool"] = "Schema Compare"
        st.session_state["dba_tools_group_selector"] = "Object Monitoring"
    render_workflow_module(workflow, WORKFLOW_MODULES)


def render() -> None:
    _apply_fast_entry_default()
    if st.session_state.get("exceptions_only_mode") and "workload_operations_workflow" not in st.session_state:
        st.session_state["workload_operations_workflow"] = QUERY_CONTENTION_WORKFLOW
    migrate_legacy_workflow_state(
        "query_workbench_workflow",
        "workload_operations_workflow",
        LEGACY_WORKFLOW_MAP,
    )
    _normalize_workload_workflow_state()
    if st.session_state.get("workload_operations_workflow") not in WORKFLOWS:
        st.session_state["workload_operations_workflow"] = QUERY_CONTENTION_WORKFLOW

    render_workflow_guide(
        "Pick the operator surface that matches the incident. Each route opens one specialist path instead of a nested brief.",
        [
            ("Running, queued, blocked, slow, spilling, or failed SQL", "Use Query investigation, then choose diagnosis or contention focus."),
            ("Late task, failed procedure, load backlog, or downstream SLA risk", "Use Task & procedure health, Stored procedures, or Pipeline / SLA risk."),
            ("Mismatch between environments or releases", "Use Schema & data compare."),
        ],
    )

    workflow = render_workflow_selector(
        "Workload surface",
        "workload_operations_workflow",
        WORKFLOWS,
        WORKFLOW_DETAILS,
        columns=5,
    )

    _render_workload_surface(workflow)
