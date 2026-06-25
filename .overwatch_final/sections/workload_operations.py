# sections/workload_operations.py - consolidated DBA workload monitor
from __future__ import annotations

from collections.abc import Mapping, Sequence
from importlib import import_module

import streamlit as st

from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.command_deck import render_command_deck
from sections.command_deck_contracts import get_command_deck_contract
from sections.navigation import apply_section_workflow_navigation
from sections.shell_helpers import build_first_paint_summary_spec, render_section_first_paint_shell
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_section_note

pd = lazy_pandas()

get_active_company = _lazy_util("get_active_company")
get_active_environment = _lazy_util("get_active_environment")
load_change_correlation_detail = _lazy_util("load_change_correlation_detail")
load_change_event_detail = _lazy_util("load_change_event_detail")
load_closed_loop_execution_plan_detail = _lazy_util("load_closed_loop_execution_plan_detail")
load_closed_loop_workflow_detail = _lazy_util("load_closed_loop_workflow_detail")
load_command_center_finding_detail = _lazy_util("load_command_center_finding_detail")
load_command_center_recommendation_detail = _lazy_util("load_command_center_recommendation_detail")
load_forecast_detail = _lazy_util("load_forecast_detail")
render_workflow_selector = _lazy_util("render_workflow_selector")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
build_loaded_section_alert_signal_board = _lazy_util("build_loaded_section_alert_signal_board")


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


def _render_loaded_workload_alert_context() -> None:
    board = build_loaded_section_alert_signal_board(st.session_state, section="Workload Operations", limit=8)
    if board.empty:
        return
    st.markdown("**Loaded Reliability Alerts**")
    render_priority_dataframe(
        board,
        title="Loaded workload alert context",
        priority_columns=[
            "SECTION_FOCUS", "SEVERITY", "SLA_STATE", "CATEGORY", "SIGNAL",
            "ENTITY", "OWNER", "FIRST_RESPONSE", "RECOMMENDED_ACTION",
            "SOURCE_FRESHNESS", "OPEN_PATH", "DRILLDOWN_HINT",
            "AUTOMATION_READINESS", "QUEUE_STATE", "TICKET_ID",
        ],
        sort_by=["PRIORITY"],
        ascending=True,
        raw_label="All loaded workload alert rows",
        height=260,
        max_rows=6,
    )
    top = board.iloc[0]
    cols = st.columns(2)
    with cols[0]:
        if st.button("Open Alert Lane", key="workload_alert_open_alert_lane", width="stretch"):
            apply_section_workflow_navigation(
                "Alert Center",
                alert_center_view=str(top.get("ALERT_CENTER_VIEW") or "Reliability"),
            )
            st.rerun()
    with cols[1]:
        if st.button("Open Workload Drilldown", key="workload_alert_open_drilldown", width="stretch"):
            apply_section_workflow_navigation(
                str(top.get("DESTINATION_SECTION") or "Workload Operations"),
                workflow=str(top.get("DESTINATION_WORKFLOW") or PIPELINE_TASK_HEALTH_WORKFLOW),
            )
            st.rerun()


def _render_workload_forecast_detail(company: str, environment: str) -> None:
    """Expose workload pressure and SLA forecasts only after operator request."""
    st.markdown("**Workload Forecast Drivers**")
    st.caption(
        "Loads warehouse pressure and SLA risk forecast history from OVERWATCH_FORECAST_HISTORY. "
        "No live Snowflake scan or remediation is executed."
    )
    if st.button("Load Workload Forecast Drivers", key="workload_load_forecast_drivers", width="stretch"):
        st.session_state["workload_forecast_detail"] = load_forecast_detail(
            company,
            environment,
            forecast_keys=("WAREHOUSE_PRESSURE", "SLA_RISK"),
            days=180,
        )
        st.session_state["workload_forecast_scope"] = (company, environment)

    detail = st.session_state.get("workload_forecast_detail")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("workload_forecast_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No workload forecast rows are available for this scope yet.")
            return
        trend = detail.get("TREND_DIRECTION", pd.Series(dtype=str)).fillna("").astype(str)
        confidence = detail.get("CONFIDENCE", pd.Series(dtype=str)).fillna("").astype(str)
        risk = pd.to_numeric(detail.get("VALUE_AT_RISK_USD", pd.Series(dtype=float)), errors="coerce").fillna(0)
        st.caption(
            f"{safe_int(trend.eq('Up').sum()):,} forecast(s) trending up; "
            f"{safe_int(confidence.eq('Low').sum()):,} low-confidence forecast(s); "
            f"${safe_float(risk.sum()):,.0f} value/risk tagged."
        )
        render_priority_dataframe(
            detail,
            title="Warehouse pressure and SLA forecast drivers",
            priority_columns=[
                "FORECAST_NAME", "FORECAST_VALUE", "VALUE_UNIT", "CURRENT_ACTUAL",
                "PRIOR_PERIOD_VALUE", "TREND_DIRECTION", "CONFIDENCE",
                "MAIN_DRIVER", "RECOMMENDED_ACTION", "OWNER_ROUTE",
                "LAST_REFRESHED_TS",
            ],
            sort_by=["SNAPSHOT_TS", "FORECAST_KEY"],
            ascending=[False, True],
            raw_label="All workload forecast history rows",
            height=280,
            max_rows=8,
        )


def _render_workload_change_detail(company: str, environment: str) -> None:
    """Expose task/procedure/object changes and workload correlations behind Load."""
    st.markdown("**Workload Change Intelligence**")
    st.caption("Loads task, procedure, and object changes plus possible workload correlations. No live metadata scan is run.")
    if st.button("Load Workload Changes", key="workload_load_change_intelligence", width="stretch"):
        change_types = ("TASK_CHANGE", "PROCEDURE_CHANGE", "OBJECT_CHANGE")
        st.session_state["workload_change_event_detail"] = load_change_event_detail(
            company,
            environment,
            change_types=change_types,
            days=180,
        )
        st.session_state["workload_change_correlation_detail"] = load_change_correlation_detail(
            company,
            environment,
            change_types=change_types,
            correlation_types=("Workload", "Alert"),
            days=180,
        )
        st.session_state["workload_change_scope"] = (company, environment)

    if st.session_state.get("workload_change_scope") != (company, environment):
        return
    events = st.session_state.get("workload_change_event_detail")
    correlations = st.session_state.get("workload_change_correlation_detail")
    if isinstance(events, pd.DataFrame):
        if events.empty:
            st.info("No workload change events are available for this scope yet.")
        else:
            render_priority_dataframe(
                events,
                title="Task, procedure, and object changes",
                priority_columns=[
                    "CHANGE_TS", "CHANGE_TYPE", "OBJECT_TYPE", "OBJECT_NAME",
                    "CHANGED_BY", "RISK_LEVEL", "BUSINESS_IMPACT", "OWNER_ROUTE",
                    "RELATED_ALERT_COUNT", "CONFIDENCE",
                ],
                sort_by=["CHANGE_TS"],
                ascending=False,
                raw_label="All workload change rows",
                height=280,
                max_rows=10,
            )
    if isinstance(correlations, pd.DataFrame):
        if correlations.empty:
            st.info("No workload change correlations are available for this scope yet.")
        else:
            render_priority_dataframe(
                correlations,
                title="Possible workload correlations after changes",
                priority_columns=[
                    "RELATED_TS", "CHANGE_TS", "CHANGE_TYPE", "OBJECT_NAME",
                    "RELATED_SIGNAL", "RELATED_ENTITY", "CORRELATION_LABEL",
                    "EVIDENCE", "OWNER_ROUTE", "CONFIDENCE",
                ],
                sort_by=["RELATED_TS", "CHANGE_TS"],
                ascending=[False, False],
                raw_label="All workload change correlations",
                height=280,
                max_rows=10,
            )


def _render_workload_closed_loop_detail(company: str, environment: str) -> None:
    """Expose operational remediation workflows behind an explicit Load action."""
    st.markdown("**Operational Action Workflow**")
    st.caption(
        "Loads workload and operations action workflows plus review-only execution plans. "
        "OVERWATCH does not execute remediation SQL from this panel."
    )
    domains = ("Workload", "Operations")
    if st.button("Load Operational Actions", key="workload_load_closed_loop_actions", width="stretch"):
        st.session_state["workload_closed_loop_workflow_detail"] = load_closed_loop_workflow_detail(
            company,
            environment,
            domains=domains,
            days=180,
        )
        st.session_state["workload_closed_loop_execution_plan_detail"] = load_closed_loop_execution_plan_detail(
            company,
            environment,
            domains=domains,
            days=180,
        )
        st.session_state["workload_closed_loop_scope"] = (company, environment)

    if st.session_state.get("workload_closed_loop_scope") != (company, environment):
        return
    workflows = st.session_state.get("workload_closed_loop_workflow_detail")
    execution_plans = st.session_state.get("workload_closed_loop_execution_plan_detail")
    if isinstance(workflows, pd.DataFrame):
        if workflows.empty:
            st.info("No workload or operations action workflows are available for this scope yet.")
        else:
            render_priority_dataframe(
                workflows,
                title="Operational remediation workflow",
                priority_columns=[
                    "ACTION_DOMAIN", "FINDING", "ENTITY_TYPE", "ENTITY_NAME",
                    "RISK_LEVEL", "OWNER_ROUTE", "APPROVAL_STATUS",
                    "EXECUTION_MODE", "VERIFICATION_STATUS", "BUSINESS_IMPACT",
                    "RECOMMENDED_ACTION", "LAST_REFRESHED_TS",
                ],
                sort_by=["RISK_LEVEL", "LAST_REFRESHED_TS"],
                ascending=[True, False],
                raw_label="All workload closed-loop workflow rows",
                height=300,
                max_rows=10,
            )
    if isinstance(execution_plans, pd.DataFrame):
        if execution_plans.empty:
            st.info("No workload review plans are available for this scope yet.")
        else:
            render_priority_dataframe(
                execution_plans,
                title="Review-only workload action plans",
                priority_columns=[
                    "ACTION_DOMAIN", "EXECUTION_MODE", "EXECUTION_STATUS",
                    "DANGEROUS_ACTION_FLAG", "EXECUTION_ALLOWED_IN_APP",
                    "REVIEW_SQL_TEXT", "REVIEW_ACTION_TEXT",
                    "ROLLBACK_GUIDANCE", "VERIFICATION_STEPS",
                ],
                sort_by=["DANGEROUS_ACTION_FLAG", "LAST_REFRESHED_TS"],
                ascending=[False, False],
                raw_label="All workload closed-loop execution plans",
                height=280,
                max_rows=8,
            )


def _render_workload_command_findings(company: str, environment: str) -> None:
    """Expose warehouse slowdown and failure/SLA investigation findings behind Load."""
    st.markdown("**Workload Investigation Findings**")
    st.caption("Loads root-cause candidates for slow warehouses, queue pressure, task/query failures, and SLA risk.")
    types = ("Warehouse Slow", "Failure / SLA")
    if st.button("Load Workload Investigation Findings", key="workload_load_command_center", width="stretch"):
        st.session_state["workload_command_findings"] = load_command_center_finding_detail(
            company,
            environment,
            investigation_types=types,
            days=180,
        )
        st.session_state["workload_command_recommendations"] = load_command_center_recommendation_detail(
            company,
            environment,
            investigation_types=types,
            days=180,
        )
        st.session_state["workload_command_scope"] = (company, environment)

    if st.session_state.get("workload_command_scope") != (company, environment):
        return
    findings = st.session_state.get("workload_command_findings")
    recommendations = st.session_state.get("workload_command_recommendations")
    if isinstance(findings, pd.DataFrame):
        if findings.empty:
            st.info("No workload investigation findings are available for this scope yet.")
        else:
            render_priority_dataframe(
                findings,
                title="Workload root-cause candidates",
                priority_columns=[
                    "INVESTIGATION_TYPE", "QUESTION_TEXT", "ROOT_CAUSE_CANDIDATE",
                    "CAUSALITY_LABEL", "EVIDENCE_SUMMARY", "CONFIDENCE",
                    "TECHNICAL_IMPACT", "OWNER_ROUTE", "RELATED_CHANGES",
                    "RELATED_ALERTS", "RELATED_FORECASTS", "RECOMMENDED_ACTION",
                    "RISK_LEVEL", "EXECUTION_PLAN_REF", "VERIFICATION_PATH",
                ],
                sort_by=["RISK_LEVEL", "LAST_REFRESHED_TS"],
                ascending=[True, False],
                raw_label="All workload investigation findings",
                height=300,
                max_rows=8,
            )
    if isinstance(recommendations, pd.DataFrame) and not recommendations.empty:
        render_priority_dataframe(
            recommendations,
            title="Workload investigation recommendations",
            priority_columns=[
                "INVESTIGATION_TYPE", "RECOMMENDED_ACTION", "RISK_LEVEL",
                "OWNER_ROUTE", "EXECUTION_PLAN_REF", "REVIEW_REQUIRED",
                "VERIFICATION_PATH", "SAFETY_NOTE", "LAST_REFRESHED_TS",
            ],
            sort_by=["RISK_LEVEL", "LAST_REFRESHED_TS"],
            ascending=[True, False],
            raw_label="All workload investigation recommendations",
            height=260,
            max_rows=6,
        )


WORKLOAD_OPERATIONS_FAST_ENTRY_VERSION = "2026-06-22-workload-flow-v2"
WORKLOAD_OPERATIONS_EXPLICIT_WORKFLOW_KEY = "_workload_operations_explicit_workflow_request"
WORKLOAD_OVERVIEW_WORKFLOW = "Workload Overview"
QUERY_INVESTIGATION_WORKFLOW = "Query Investigation"
PIPELINE_TASK_HEALTH_WORKFLOW = "Pipeline & Task Health"
CONTENTION_PERFORMANCE_WORKFLOW = "Performance & Contention"
CHANGE_DRIFT_WORKFLOW = "Change Analysis"
ADVANCED_DBA_TOOLS_WORKFLOW = "Advanced DBA Tools"
AI_QUERY_DIAGNOSIS_WORKFLOW = QUERY_INVESTIGATION_WORKFLOW
PIPELINE_FOCUS_KEY = "workload_operations_pipeline_focus"
PIPELINE_TASK_FOCUS = "Failed Tasks"
PIPELINE_STORED_PROC_FOCUS = "Failed Procedures"
PIPELINE_LOAD_FOCUS = "Load Issues & SLA"
_LEGACY_TRIAGE_FOCUS_KEY = "workload_operations_triage_focus"

WORKFLOWS = (
    WORKLOAD_OVERVIEW_WORKFLOW,
    QUERY_INVESTIGATION_WORKFLOW,
    PIPELINE_TASK_HEALTH_WORKFLOW,
    CONTENTION_PERFORMANCE_WORKFLOW,
    CHANGE_DRIFT_WORKFLOW,
    ADVANCED_DBA_TOOLS_WORKFLOW,
)

WORKFLOW_DETAILS = {
    WORKLOAD_OVERVIEW_WORKFLOW: "Fast workload triage: failures, slow SQL, queue pressure, pipeline issues, and recent changes.",
    QUERY_INVESTIGATION_WORKFLOW: "One front door for SQL text, query ID lookup, history search, operator stats, cost, elapsed time, bytes, queue, spill, and scans.",
    PIPELINE_TASK_HEALTH_WORKFLOW: "Tasks, procedures, load failures, freshness SLA, dynamic tables, Snowpipe, and downstream backlog.",
    CONTENTION_PERFORMANCE_WORKFLOW: "Queue pressure, blocked queries, warehouse saturation, concurrency, spilling, hot warehouses, and regressions.",
    CHANGE_DRIFT_WORKFLOW: "What changed before the problem started: task, procedure, object, schema, and deployment changes.",
    ADVANCED_DBA_TOOLS_WORKFLOW: "Schema compare, data compare, generated SQL, validation utilities, and admin/debug tools.",
}

WORKFLOW_MODULES = {
    QUERY_INVESTIGATION_WORKFLOW: "sections.query_analysis",
    CONTENTION_PERFORMANCE_WORKFLOW: "sections.contention_center",
    ADVANCED_DBA_TOOLS_WORKFLOW: "sections.dba_tools",
}

PIPELINE_FOCUS_DETAILS = {
    PIPELINE_TASK_FOCUS: "Task graph job status, failures, retries, SLA drift, cancellation controls, and linked query detail.",
    PIPELINE_STORED_PROC_FOCUS: "Stored procedure inventory, calls, runtime/cost regressions, task linkage, and child-query drilldown.",
    PIPELINE_LOAD_FOCUS: "Freshness SLA, copy/load failures, dynamic tables, Snowpipe usage, volume watch, and downstream backlog.",
}

QUERY_DIAGNOSIS_ALIASES = {
    "Query diagnosis",
    "Query Investigation",
    "Query Analysis",
    "Query Search & History",
    "Query Workbench",
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
    "Contention Telemetry",
    "Contention & Performance",
    "Performance & Contention",
}

PIPELINE_TASK_ALIASES = {
    "Task & procedure health",
    "Task, procedure & pipeline health",
    "Task graphs",
    "Task Management",
    "Failed tasks & procedures",
    "Failed Tasks",
}

PIPELINE_STORED_PROC_ALIASES = {
    "Stored procedures",
    "Stored procedure lineage",
    "Stored Proc Tracker",
    "Stored procedure analysis",
    "Failed Procedures",
}

PIPELINE_LOAD_ALIASES = {
    "Pipeline health",
    "Pipeline / SLA risk",
    "Pipeline & Task Health",
    "Pipeline loads & SLA",
    "Load Issues & SLA",
}

CHANGE_DRIFT_ALIASES = {
    "Change & Drift",
    "Change Drift",
    "Change Workflows",
    "Object Change Monitor",
    "Object Monitoring",
    "Change Analysis",
}

ADVANCED_DBA_ALIASES = {
    "Schema & data compare",
    "Schema Compare",
    "Data Compare",
    "DBA Tools",
    "Advanced DBA Tools",
}

CONSOLIDATED_WORKFLOW_ALIASES = {
    **{alias: QUERY_INVESTIGATION_WORKFLOW for alias in QUERY_DIAGNOSIS_ALIASES},
    **{alias: CONTENTION_PERFORMANCE_WORKFLOW for alias in QUERY_CONTENTION_ALIASES},
    **{alias: PIPELINE_TASK_HEALTH_WORKFLOW for alias in PIPELINE_TASK_ALIASES},
    **{alias: PIPELINE_TASK_HEALTH_WORKFLOW for alias in PIPELINE_STORED_PROC_ALIASES},
    **{alias: PIPELINE_TASK_HEALTH_WORKFLOW for alias in PIPELINE_LOAD_ALIASES},
    **{alias: CHANGE_DRIFT_WORKFLOW for alias in CHANGE_DRIFT_ALIASES},
    **{alias: ADVANCED_DBA_TOOLS_WORKFLOW for alias in ADVANCED_DBA_ALIASES},
}

PIPELINE_FOCUS_ALIASES = {
    **{alias: PIPELINE_TASK_FOCUS for alias in PIPELINE_TASK_ALIASES},
    **{alias: PIPELINE_STORED_PROC_FOCUS for alias in PIPELINE_STORED_PROC_ALIASES},
    **{alias: PIPELINE_LOAD_FOCUS for alias in PIPELINE_LOAD_ALIASES},
}

LEGACY_WORKFLOW_MAP = {
    "Diagnosis": QUERY_INVESTIGATION_WORKFLOW,
    "History Search": QUERY_INVESTIGATION_WORKFLOW,
    "AI Diagnosis": QUERY_INVESTIGATION_WORKFLOW,
    "Live Triage": CONTENTION_PERFORMANCE_WORKFLOW,
    "Contention": CONTENTION_PERFORMANCE_WORKFLOW,
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
    pipeline_focus = PIPELINE_FOCUS_ALIASES.get(current)
    if pipeline_focus:
        st.session_state[PIPELINE_FOCUS_KEY] = pipeline_focus
    mapped = CONSOLIDATED_WORKFLOW_ALIASES.get(current)
    if mapped:
        st.session_state["workload_operations_workflow"] = mapped
    legacy_focus = str(st.session_state.pop(_LEGACY_TRIAGE_FOCUS_KEY, "") or "")
    existing_pipeline_focus = str(st.session_state.get(PIPELINE_FOCUS_KEY, "") or "")
    if existing_pipeline_focus in PIPELINE_FOCUS_ALIASES:
        st.session_state[PIPELINE_FOCUS_KEY] = PIPELINE_FOCUS_ALIASES[existing_pipeline_focus]
    focus_workflow = CONSOLIDATED_WORKFLOW_ALIASES.get(legacy_focus)
    if focus_workflow and current not in WORKFLOWS:
        st.session_state["workload_operations_workflow"] = focus_workflow


def _set_workload_workflow(workflow: str, *, pipeline_focus: str = "") -> None:
    st.session_state["workload_operations_workflow"] = workflow
    if pipeline_focus:
        st.session_state[PIPELINE_FOCUS_KEY] = pipeline_focus
    st.rerun()


def _render_workload_overview(company: str, environment: str) -> None:
    board = build_loaded_section_alert_signal_board(st.session_state, section="Workload Operations", limit=12)
    if isinstance(board, pd.DataFrame) and not board.empty:
        severity = board.get("SEVERITY", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
        category = board.get("CATEGORY", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
        render_section_first_paint_shell(
            build_first_paint_summary_spec(
                section="Workload Operations",
                state="Loaded context",
                headline="Workload Overview is ready for triage.",
                detail="Loaded reliability alert context is already in session; specialist evidence stays behind explicit workflow actions.",
                metrics=(
                    ("Active workload items", f"{len(board):,}"),
                    ("Critical / High", f"{safe_int(severity.isin(['CRITICAL', 'HIGH']).sum()):,}"),
                    ("Query / contention", f"{safe_int(category.str.contains('QUERY|CONTENTION|PERFORMANCE', regex=True).sum()):,}"),
                    ("Pipeline / task", f"{safe_int(category.str.contains('TASK|PIPELINE|PROCEDURE|LOAD', regex=True).sum()):,}"),
                ),
                snapshot=(
                    ("Scope", f"{company} / {environment}"),
                    ("Freshness", "Session alert context"),
                ),
            )
        )
        _render_loaded_workload_alert_context()
    else:
        render_section_first_paint_shell(
            build_first_paint_summary_spec(
                section="Workload Operations",
                state="Ready",
                headline="Workload Overview is ready for explicit triage.",
                detail="No live Snowflake reads run on entry. Choose a workflow when an issue starts.",
                metrics=(
                    ("Active workload items", "0"),
                    ("Critical / High", "0"),
                    ("Query / contention", "0"),
                    ("Pipeline / task", "0"),
                ),
                snapshot=(
                    ("Scope", f"{company} / {environment}"),
                    ("Freshness", "No workload alert context loaded"),
                ),
            )
        )
        st.info("No loaded workload incidents are in session. Use Query Investigation, Pipeline & Task Health, or Performance & Contention when an issue starts.")

    render_command_deck(
        get_command_deck_contract("Workload Operations"),
        key_prefix="workload_command_deck",
    )


def _render_query_investigation_surface() -> None:
    st.session_state.setdefault("query_analysis_active_view", "AI Diagnosis")
    if st.session_state.pop("workload_query_diagnosis_mode", "") == "Detailed diagnosis":
        st.session_state["query_analysis_active_view"] = "Detailed Diagnosis"
    render_workflow_module(QUERY_INVESTIGATION_WORKFLOW, WORKFLOW_MODULES)


def _render_pipeline_task_health_surface() -> None:
    focus = render_workflow_selector(
        "Pipeline & task focus",
        PIPELINE_FOCUS_KEY,
        (PIPELINE_TASK_FOCUS, PIPELINE_STORED_PROC_FOCUS, PIPELINE_LOAD_FOCUS),
        PIPELINE_FOCUS_DETAILS,
        columns=3,
    )
    if focus == PIPELINE_STORED_PROC_FOCUS:
        render_workflow_module(focus, {focus: "sections.stored_proc_tracker"})
        return
    if focus == PIPELINE_LOAD_FOCUS:
        st.session_state.setdefault("pipeline_health_active_view", "Load Failures")
        render_workflow_module(focus, {focus: "sections.pipeline_health"})
        return
    st.session_state.setdefault("task_management_view", "Job Status Brief")
    render_workflow_module(focus, {focus: "sections.task_management"})


def _render_change_drift_surface(company: str, environment: str) -> None:
    render_workflow_guide(
        "Use this when an incident follows a release, object change, task/procedure edit, schema drift, or deployment window.",
        [
            ("Problem started after a release", "Load workload changes and check task/procedure/object changes in the same window."),
            ("Failures began after object edits", "Review possible correlations before rerun or rollback."),
            ("Need full object comparison", "Use Advanced DBA Tools for Schema Compare and Data Compare."),
        ],
    )
    _render_workload_change_detail(company, environment)


def _render_advanced_workload_tools(company: str, environment: str) -> None:
    st.session_state.setdefault("dba_tools_focus", "Object Monitoring")
    st.session_state.setdefault("dba_tools_focus_tool", "Schema Compare")
    st.session_state.setdefault("dba_tools_group_selector", "Object Monitoring")
    render_workflow_module(ADVANCED_DBA_TOOLS_WORKFLOW, WORKFLOW_MODULES)

    with st.expander("Advanced workload evidence and admin diagnostics", expanded=False):
        render_workflow_guide(
            "Admin-only diagnostics stay here so daily workload triage remains focused.",
            [
                ("Forecast or SLA risk detail", "Load only when explaining future pressure or SLA risk."),
                ("Closed-loop workflow evidence", "Review action state and generated SQL without executing remediation."),
                ("Command findings", "Load root-cause candidates only when a cross-domain investigation needs them."),
            ],
        )
        _render_workload_forecast_detail(company, environment)
        _render_workload_closed_loop_detail(company, environment)
        _render_workload_command_findings(company, environment)


def _render_workload_surface(workflow: str, company: str, environment: str) -> None:
    if workflow == WORKLOAD_OVERVIEW_WORKFLOW:
        _render_workload_overview(company, environment)
        return
    if workflow == QUERY_INVESTIGATION_WORKFLOW:
        _render_query_investigation_surface()
        return
    if workflow == PIPELINE_TASK_HEALTH_WORKFLOW:
        _render_pipeline_task_health_surface()
        return
    if workflow == CHANGE_DRIFT_WORKFLOW:
        _render_change_drift_surface(company, environment)
        return
    if workflow == ADVANCED_DBA_TOOLS_WORKFLOW:
        _render_advanced_workload_tools(company, environment)
        return
    render_workflow_module(workflow, WORKFLOW_MODULES)


def render() -> None:
    _apply_fast_entry_default()
    if st.session_state.get("exceptions_only_mode") and "workload_operations_workflow" not in st.session_state:
        st.session_state["workload_operations_workflow"] = WORKLOAD_OVERVIEW_WORKFLOW
    migrate_legacy_workflow_state(
        "query_workbench_workflow",
        "workload_operations_workflow",
        LEGACY_WORKFLOW_MAP,
    )
    _normalize_workload_workflow_state()
    if st.session_state.get("workload_operations_workflow") not in WORKFLOWS:
        st.session_state["workload_operations_workflow"] = WORKLOAD_OVERVIEW_WORKFLOW

    company = get_active_company()
    environment = get_active_environment()

    workflow = render_workflow_selector(
        "Workload workflow",
        "workload_operations_workflow",
        WORKFLOWS,
        WORKFLOW_DETAILS,
        columns=5,
    )

    _render_workload_surface(workflow, company, environment)
