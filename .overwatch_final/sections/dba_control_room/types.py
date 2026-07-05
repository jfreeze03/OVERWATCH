"""Shared constants, lazy utility bindings, and small pure helpers for the DBA Control Room."""
from __future__ import annotations

import streamlit as st
from config import (
    DEFAULTS,
    DEFAULT_ENVIRONMENT,
    SECTION_BY_TITLE,
    normalize_section_name,
)
from utils.performance import SECTION_ROUTE_QUERY_BUDGET, query_budget_context
from runtime_state import set_state
from utils.primitives import (
    safe_float,
    safe_int,
)
from utils.section_guidance import (
    defer_section_note,
)
from sections.navigation import apply_navigation_state
from sections.base import lazy_pandas, lazy_util as _lazy_util, lazy_util_attr

pd = lazy_pandas()

def get_active_environment() -> str:
    return str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)


def get_credit_price() -> float:
    return safe_float(st.session_state.get("credit_price", DEFAULTS.get("credit_price", 3.68)), 3.68)


def metric_confidence_label(kind: str) -> str:
    labels = {
        "exact": "Measurement: Exact",
        "allocated": "Measurement: Allocated from warehouse metering",
        "estimated": "Measurement: Estimated",
        "forecast": "Measurement: Forecast from recent observed burn",
        "projection": "Measurement: Projection from recent observed burn",
        "composite": "Measurement: Composite rollup from operational signals",
        "account": "Measurement: Account-wide",
        "account-wide": "Measurement: Account-wide",
    }
    return labels.get(str(kind or "").lower(), "Measurement depends on available account metadata")


def freshness_note(source: str) -> str:
    source_key = str(source or "").lower()
    if "information_schema" in source_key or source_key in {"live", "is"}:
        return "Freshness: live INFORMATION_SCHEMA view"
    if "account_usage" in source_key or source_key in {"account", "query_history", "warehouse_metering_history"}:
        return "Freshness: ACCOUNT_USAGE can lag up to about 45-90 minutes"
    if "organization_usage" in source_key:
        return "Freshness: ORGANIZATION_USAGE can lag several hours"
    if "session" in source_key:
        return "Freshness: current Streamlit session only"
    return "Freshness: depends on source view availability"


def _gate_state_from_counts(blocked: int, review: int) -> str:
    if safe_int(blocked):
        return "Blocked"
    if safe_int(review):
        return "Review"
    return "Ready"


def render_operator_briefing(items: list[tuple[str, str]], *, columns: int = 4) -> None:
    for label, detail in items:
        defer_section_note(f"{label}: {detail}")


build_metered_credit_cte = _lazy_util("build_metered_credit_cte")


build_task_failure_summary_sql = _lazy_util("build_task_failure_summary_sql")


build_task_history_sql = _lazy_util("build_task_history_sql")


credits_to_dollars = _lazy_util("credits_to_dollars")


dba_control_plane_section_scorecards = _lazy_util("dba_control_plane_section_scorecards")


dba_effective_readiness_score = _lazy_util("dba_effective_readiness_score")


download_csv = _lazy_util("download_csv")


enrich_action_queue_view = _lazy_util("enrich_action_queue_view")


format_credits = _lazy_util("format_credits")


format_snowflake_error = _lazy_util("format_snowflake_error")


filter_existing_columns = _lazy_util("filter_existing_columns")


get_db_filter_clause = _lazy_util("get_db_filter_clause")


get_active_company = _lazy_util("get_active_company")


get_global_filter_clause = _lazy_util("get_global_filter_clause")


get_session = _lazy_util("get_session")


get_user_company_filter_clause = _lazy_util("get_user_company_filter_clause")


get_wh_filter_clause = _lazy_util("get_wh_filter_clause")


get_owner_context_columns = lazy_util_attr("OWNER_CONTEXT_COLUMNS")


build_mart_control_room_summary_sql = _lazy_util("build_mart_control_room_summary_sql")


build_mart_control_room_credits_sql = _lazy_util("build_mart_control_room_credits_sql")


build_mart_control_room_cost_drivers_sql = _lazy_util("build_mart_control_room_cost_drivers_sql")


build_mart_control_room_warehouse_pressure_sql = _lazy_util("build_mart_control_room_warehouse_pressure_sql")


build_mart_control_room_failed_queries_sql = _lazy_util("build_mart_control_room_failed_queries_sql")


build_mart_control_room_object_changes_sql = _lazy_util("build_mart_control_room_object_changes_sql")


build_mart_control_room_failed_logins_sql = _lazy_util("build_mart_control_room_failed_logins_sql")


build_mart_control_room_task_failures_sql = _lazy_util("build_mart_control_room_task_failures_sql")


build_mart_query_detail_recent_sql = _lazy_util("build_mart_query_detail_recent_sql")


build_mart_task_history_sql = _lazy_util("build_mart_task_history_sql")


build_mart_procedure_sla_sql = _lazy_util("build_mart_procedure_sla_sql")


build_schema_migration_status_sql = _lazy_util("build_schema_migration_status_sql")


load_latest_control_room_mart = _lazy_util("load_latest_control_room_mart")


load_task_inventory = _lazy_util("load_task_inventory")


load_action_queue = _lazy_util("load_action_queue")


load_app_observability_detail = _lazy_util("load_app_observability_detail")


load_change_correlation_detail = _lazy_util("load_change_correlation_detail")


load_change_event_detail = _lazy_util("load_change_event_detail")


load_closed_loop_execution_plan_detail = _lazy_util("load_closed_loop_execution_plan_detail")


load_closed_loop_verification_detail = _lazy_util("load_closed_loop_verification_detail")


load_closed_loop_workflow_detail = _lazy_util("load_closed_loop_workflow_detail")


load_command_center_evidence_detail = _lazy_util("load_command_center_evidence_detail")


load_command_center_finding_detail = _lazy_util("load_command_center_finding_detail")


load_command_center_recommendation_detail = _lazy_util("load_command_center_recommendation_detail")


load_data_trust_detail = _lazy_util("load_data_trust_detail")


load_executive_scorecard_detail = _lazy_util("load_executive_scorecard_detail")


load_forecast_detail = _lazy_util("load_forecast_detail")


load_production_validation_detail = _lazy_util("load_production_validation_detail")


run_query = _lazy_util("run_query")


sql_literal = _lazy_util("sql_literal")


resolve_owner_context = _lazy_util("resolve_owner_context")


render_priority_dataframe = _lazy_util("render_priority_dataframe")


render_load_status = _lazy_util("render_load_status")


render_workflow_selector = _lazy_util("render_workflow_selector")


DBA_CONTROL_SCOPE_FILTER_KEYS = (
    "global_warehouse",
    "global_user",
    "global_role",
    "global_database",
    "global_start_date",
    "global_end_date",
)


MORNING_COCKPIT_WORKFLOW = "Morning Cockpit"
FAILURE_TRIAGE_WORKFLOW = "Failure Triage"
COST_WATCH_WORKFLOW = "Cost Watch"
PERFORMANCE_WATCH_WORKFLOW = "Performance Watch"
CHANGE_WATCH_WORKFLOW = "Change Watch"
ACTION_QUEUE_WORKFLOW = "Action Queue"
CONTROL_ROOM_ADMIN_WORKFLOW = "Control Room Admin / Advanced"


DBA_CONTROL_ROOM_PANES = (
    MORNING_COCKPIT_WORKFLOW,
    FAILURE_TRIAGE_WORKFLOW,
    COST_WATCH_WORKFLOW,
    PERFORMANCE_WATCH_WORKFLOW,
    CHANGE_WATCH_WORKFLOW,
    ACTION_QUEUE_WORKFLOW,
    CONTROL_ROOM_ADMIN_WORKFLOW,
)


DBA_CONTROL_ROOM_PANE_LABELS = {
    MORNING_COCKPIT_WORKFLOW: "Morning",
    FAILURE_TRIAGE_WORKFLOW: "Failures",
    COST_WATCH_WORKFLOW: "Cost",
    PERFORMANCE_WATCH_WORKFLOW: "Performance",
    CHANGE_WATCH_WORKFLOW: "Changes",
    ACTION_QUEUE_WORKFLOW: "Actions",
    CONTROL_ROOM_ADMIN_WORKFLOW: "Advanced",
}


DBA_CONTROL_ROOM_PANE_DETAILS = {
    MORNING_COCKPIT_WORKFLOW: "Start with the operator snapshot, queue posture, and morning handoff.",
    FAILURE_TRIAGE_WORKFLOW: "Review failed queries, task failures, incidents, and escalation context.",
    COST_WATCH_WORKFLOW: "Check credit movement, cost exceptions, and forecast pressure.",
    PERFORMANCE_WATCH_WORKFLOW: "Inspect queueing, contention, and workload health signals.",
    CHANGE_WATCH_WORKFLOW: "Compare release movement, drift, and change-linked risk.",
    ACTION_QUEUE_WORKFLOW: "Load routed DBA actions, closure status, and review evidence.",
    CONTROL_ROOM_ADMIN_WORKFLOW: "Open guarded diagnostics and typed/admin DBA tooling.",
}


DBA_CONTROL_ROOM_LEGACY_PANE_ALIASES = {
    "Command Center": MORNING_COCKPIT_WORKFLOW,
    "Account Health": MORNING_COCKPIT_WORKFLOW,
    "Usage Overview": COST_WATCH_WORKFLOW,
    "Service Health": CONTROL_ROOM_ADMIN_WORKFLOW,
    "Fast Watch": MORNING_COCKPIT_WORKFLOW,
    "Morning Brief": MORNING_COCKPIT_WORKFLOW,
    "Operations Detail": ACTION_QUEUE_WORKFLOW,
    "Triage": FAILURE_TRIAGE_WORKFLOW,
    "Drill Routes": MORNING_COCKPIT_WORKFLOW,
    "Release Compare": CHANGE_WATCH_WORKFLOW,
    "Service Posture": CONTROL_ROOM_ADMIN_WORKFLOW,
    "Admin Tools": CONTROL_ROOM_ADMIN_WORKFLOW,
}


def normalize_dba_control_room_pane(value: object) -> str:
    """Map retired DBA Control Room pane names to the workflow-first names."""
    text = str(value or "").strip()
    mapped = DBA_CONTROL_ROOM_LEGACY_PANE_ALIASES.get(text, text)
    return mapped if mapped in DBA_CONTROL_ROOM_PANES else MORNING_COCKPIT_WORKFLOW


DBA_CONTROL_ROOM_DETAIL_PANES = (
    "Failed Queries",
    "Task Failures",
    "Task SLA/Cost",
    "Procedure SLA/Cost",
    "Cortex Cost",
    "Failed Logins",
    "Object Changes",
    "Action Queue",
)


DBA_CONTROL_ROOM_DERIVED_STATE_KEYS = (
    "dba_control_room_incident_board",
    "dba_control_room_handoff",
    "dba_control_room_morning_brief",
    "dba_control_room_morning_brief_markdown",
    "dba_control_room_escalation_packet",
    "dba_control_room_escalation_packet_markdown",
    "dba_operations_priority_index",
    "dba_operator_runbook",
    "dba_operator_runbook_markdown",
    "dba_control_room_ops_scope_key",
    "dba_control_room_ops_ready",
)


DBA_CONTROL_ROOM_LIVE_FALLBACK_CAP_HOURS = 24


DBA_CONTROL_ROOM_LIVE_FALLBACK_KEYS = {
    "credits",
    "failed_queries",
    "failed_logins",
}


def _live_fallback_deferred_message(source: str, mart_exc: Exception | None = None) -> str:
    detail = format_snowflake_error(mart_exc) if mart_exc is not None else ""
    suffix = f" Summary error: {detail}" if detail else ""
    return (
        f"{source} telemetry is unavailable for the loaded scope. "
        f"Use the guarded drilldown workflow or refresh the fast summary for this surface.{suffix}"
    )


def _clear_dba_control_room_derived_state() -> None:
    """Clear derived boards when the loaded telemetry scope changes."""
    for key in DBA_CONTROL_ROOM_DERIVED_STATE_KEYS:
        st.session_state.pop(key, None)


def _jump(title: str, *, warehouse: str = "", user: str = "", workflow: str = "") -> None:
    """Navigate to a registered section and carry useful filter context."""
    with query_budget_context("route_action", section="DBA Control Room", workflow=workflow, budget=SECTION_ROUTE_QUERY_BUDGET):
        raw_target = SECTION_BY_TITLE.get(title, title)
        target = normalize_section_name(raw_target)
        if target not in set(SECTION_BY_TITLE.values()):
            return
        apply_navigation_state(raw_target)
        if workflow:
            if title in {"Query Workbench", "Workload Operations"}:
                st.session_state["_workload_operations_explicit_workflow_request"] = True
                if workflow == "Diagnosis":
                    set_state("workload_operations_workflow", "Query Investigation")
                elif workflow == "History Search":
                    set_state("workload_operations_workflow", "Query Investigation")
                    st.session_state["query_analysis_active_view"] = "History Search"
                else:
                    set_state("workload_operations_workflow", workflow)
            elif title == "DBA Control Room":
                st.session_state["dba_control_room_active_view"] = normalize_dba_control_room_pane(workflow)
            elif title == "Cost & Contract":
                set_state("cost_contract_workflow", workflow)
            elif title == "Security Monitoring":
                security_workflow = workflow if workflow in {
                    "Security Overview",
                    "Failed Logins",
                    "Risky Grants",
                    "Privilege Sprawl",
                    "Access Changes",
                    "Data Sharing Exposure",
                    "Security Alerts",
                    "Security Admin / Advanced",
                } else "Security Overview"
                set_state("security_posture_view", security_workflow)
                st.session_state["security_posture_workflow"] = security_workflow
            elif title == "Security Posture":
                set_state("security_posture_view", workflow)
                st.session_state["security_posture_workflow"] = workflow
        if warehouse:
            st.session_state["global_warehouse"] = warehouse
            st.session_state["wh_filter"] = warehouse
        if user:
            st.session_state["global_user"] = user
    st.rerun()


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame()


def _frame_or_empty(data: dict, key: str) -> pd.DataFrame:
    value = data.get(key, _empty_df()) if isinstance(data, dict) else _empty_df()
    return value if isinstance(value, pd.DataFrame) else _empty_df()


def _row_value(row, *names: str, default: object = "") -> object:
    for name in names:
        try:
            value = row.get(name)
        except AttributeError:
            value = None
        if value is None:
            continue
        if isinstance(value, float) and value != value:
            continue
        text = str(value).strip()
        if text and text.upper() not in {"NAN", "NONE", "NULL"}:
            return value
    return default


def _snapshot_metric(df: pd.DataFrame, column: str) -> float:
    if df is None or df.empty or column not in df.columns:
        return 0.0
    return safe_float(pd.to_numeric(df[column], errors="coerce").fillna(0).sum())


def _scalar_frame_value(data: dict, key: str, column: str, default=0):
    df = data.get(key, _empty_df())
    if df is None or df.empty or column not in df.columns:
        return default
    return df.iloc[0].get(column, default)


def _clean_release_text(values: pd.Series, limit: int = 5) -> str:
    if values is None or values.empty:
        return ""
    seen: list[str] = []
    for raw in values.dropna().astype(str):
        for piece in raw.split(","):
            item = piece.strip()
            if item and item not in seen:
                seen.append(item)
            if len(seen) >= limit:
                return ", ".join(seen)
    return ", ".join(seen)


def _pct_change(before: float, after: float) -> float:
    before = safe_float(before)
    after = safe_float(after)
    if before == 0:
        return 100.0 if after > 0 else 0.0
    return round((after - before) / before * 100, 1)


def _command_queue_route(category: object) -> str:
    value = str(category or "").upper()
    if "COST" in value:
        return "Cost & Contract"
    if "ACCOUNT" in value or "CHECKLIST" in value:
        return "DBA Control Room"
    if "TASK" in value or "PROCEDURE" in value or "RELIABILITY" in value:
        return "Workload Operations"
    if "SECURITY" in value or "ACCESS" in value or "GRANT" in value:
        return "Security Monitoring"
    if "CHANGE" in value or "DRIFT" in value:
        return "Security Monitoring"
    if "WAREHOUSE" in value or "CAPACITY" in value:
        return "Cost & Contract"
    return "Alert Center"


def _canonical_dba_route(route: object) -> str:
    """Fold retired route labels into the current six-surface command model."""
    text = str(route or "").strip()
    upper_text = text.upper()
    if any(token in upper_text for token in ("CHANGE & DRIFT", "CHANGE DRIFT", "CONTROLLED DBA ACTION")):
        return "Workload Operations"
    return normalize_section_name(text) or "DBA Control Room"


def _command_value_present(row: pd.Series, *columns: str) -> bool:
    """Return whether any queue metadata column has a non-placeholder value."""
    for column in columns:
        value = row.get(column)
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except Exception:
            pass
        text = str(value).strip()
        if text and text.upper() not in {"N/A", "NONE", "NULL", "NAN", "<NA>", "UNKNOWN"}:
            return True
    return False


def _command_text_present(value: object, min_length: int = 1) -> bool:
    try:
        if value is None or pd.isna(value):
            return False
    except Exception:
        if value is None:
            return False
    text = str(value).strip()
    return len(text) >= max(1, int(min_length))


def _command_named_owner(row: pd.Series) -> bool:
    owner = str(row.get("OWNER") or "").strip().upper()
    return bool(owner and owner not in {
        "N/A",
        "NONE",
        "NULL",
        "UNKNOWN",
        "UNKNOWN USER",
        "UNKNOWN WAREHOUSE",
        "DBA",
        "DBA LEAD",
        "DBA / COST OWNER",
        "DBA / PLATFORM",
        "DBA / SECURITY",
        "DBA / WORKLOAD OWNER",
        "DBA / PIPELINE OWNER",
        "DBA / PROCEDURE OWNER",
        "DBA / DATA ENGINEERING",
        "DBA CHANGE OWNER",
        "DBA QUERY TRIAGE",
        "PLATFORM DBA",
        "SECURITY/DBA",
    })


def _command_requires_approval(row: pd.Series) -> bool:
    category = str(row.get("CATEGORY") or "").upper()
    severity = str(row.get("SEVERITY") or "").upper()
    source = str(row.get("SOURCE") or "").upper()
    controlled_domains = (
        "COST",
        "WAREHOUSE",
        "SECURITY",
        "ACCESS",
        "GRANT",
        "CHANGE",
        "DRIFT",
        "TASK",
        "PROCEDURE",
        "RELIABILITY",
    )
    return severity in {"CRITICAL", "HIGH"} or any(token in category or token in source for token in controlled_domains)


def _dba_section_proof_required(section: object, lowest_component: object = "") -> str:
    """Return the minimum telemetry contract for a section to remain credibly 95+."""
    name = str(section or "").upper()
    component = str(lowest_component or "").lower()
    if "WAREHOUSE" in name:
        return "capacity telemetry, setting review snapshot, review status, rollback SQL, post-change telemetry"
    if "CHANGE" in name or "DRIFT" in name:
        return "change ticket, query_id, release-note/rollback status, blast-radius review, closure status"
    if "COST" in name:
        return "allocated cost basis, warehouse capacity telemetry, cost attribution, impact telemetry, rollback SQL, finance-ready closure status"
    if "SECURITY" in name:
        return "role/grant route, reviewer, ticket, least-privilege telemetry, access closure status"
    if "ACCOUNT" in name:
        return "checklist route, hygiene telemetry, reviewed remediation, closure status"
    if "ALERT" in name:
        return "alert data health, routed contact, email status, suppression/acknowledgement history"
    if "WORKLOAD" in name:
        return "task/procedure failure telemetry, route, runbook, recovery SLA, successful retry status"
    if "DBA CONTROL" in name or "operability" in component:
        return "current data health, command queue route, ticket metadata, closure status"
    return "route, ticket, reviewer, telemetry query, closure status"


def _dba_incident_type(route: object, signal: object) -> str:
    route_text = str(route or "").upper()
    signal_text = str(signal or "").upper()
    text = f"{route_text} {signal_text}"
    if any(token in text for token in ("WAREHOUSE", "QUEUE", "SPILL", "CAPACITY", "LATENCY")):
        return "Warehouse Capacity"
    if any(token in text for token in ("CREDIT", "COST", "CORTEX", "AI")):
        return "Cost Runaway"
    if any(token in text for token in ("TASK", "PROCEDURE", "PIPELINE", "SLA", "REGRESSION")):
        return "Workload Reliability"
    if any(token in text for token in ("QUERY FAIL", "FAILED QUERY", "P95", "DURATION")):
        return "Query Reliability"
    if any(token in text for token in ("SECURITY", "LOGIN", "ACCESS", "GRANT", "ROLE")):
        return "Security / Access"
    if any(token in text for token in ("CHANGE", "DRIFT", "DDL", "OBJECT")):
        return "Change Control"
    if any(token in text for token in ("CLOSURE", "TELEMETRY", "STATUS")):
        return "Control Closure"
    if any(token in text for token in ("SOURCE", "STALE", "UNAVAILABLE", "MART")):
        return "Data Quality"
    return "DBA Operations"


def _dba_incident_rank(severity: object) -> int:
    return {
        "CRITICAL": 0,
        "HIGH": 1,
        "MEDIUM": 2,
        "LOW": 3,
        "INFO": 4,
    }.get(str(severity or "").upper(), 3)


def _dba_incident_sla_target(incident_type: object, severity: object) -> str:
    incident = str(incident_type or "").upper()
    rank = _dba_incident_rank(severity)
    if rank <= 0:
        return "Contain within 15 minutes; executive DBA update within 30 minutes."
    if rank == 1 and any(token in incident for token in ("SECURITY", "RELIABILITY", "CAPACITY")):
        return "Contain within 30 minutes; recovery or confirmed mitigation within 4 hours."
    if rank == 1:
        return "Contain same shift; current mitigation plan before handoff."
    if rank == 2:
        return "Triage same business day; queue action with route, due date, and telemetry."
    return "Monitor during next DBA review cycle."


def _dba_incident_containment_action(incident_type: object) -> str:
    incident = str(incident_type or "").upper()
    if "COST" in incident:
        return "Freeze broad scaling changes, identify top cost driver, and require review status before mitigation."
    if "WAREHOUSE" in incident:
        return "Stabilize queue/spill pressure first; route setting changes through Warehouse Settings Manager."
    if "WORKLOAD" in incident or "QUERY" in incident:
        return "Separate failing workload from platform issue, capture query/task telemetry, and protect downstream SLAs."
    if "SECURITY" in incident:
        return "Preserve telemetry, validate requester/reviewer, and avoid grant changes until escalation route is clear."
    if "CHANGE" in incident:
        return "Hold closure until ticket, query_id, review, rollback, and blast-radius status are current."
    if "CLOSURE" in incident:
        return "Reopen or block closure until telemetry, recovery, and review status are present."
    if "DATA" in incident or "TELEMETRY" in incident:
        return "Refresh summary/source telemetry before taking irreversible DBA action."
    return "Assign DBA on-call, capture telemetry, and route to the specialist workflow."


def _dba_incident_investigation_path(route: object, workflow: object = "") -> str:
    route_text = str(route or "DBA Control Room")
    workflow_text = str(workflow or "").strip()
    if workflow_text:
        return f"{route_text} -> {workflow_text}"
    return route_text


def _dba_operations_priority_state(row: pd.Series | dict) -> tuple[str, str]:
    """Return a concise operating state and first move for a section priority row."""
    overdue = safe_int(row.get("OVERDUE", 0))
    proof_blocks = safe_int(row.get("PROOF_BLOCKS", 0))
    metadata_blocks = safe_int(row.get("METADATA_BLOCKS", 0))
    approval_blocks = safe_int(row.get("APPROVAL_BLOCKS", 0))
    source_issues = safe_int(row.get("SOURCE_ISSUES", 0))
    execution_ready = safe_int(row.get("EXECUTION_READY", 0))
    section_score = safe_float(row.get("SCORE", 0))
    effective_score = safe_float(row.get("EFFECTIVE_SCORE", section_score))
    gate_drivers = str(row.get("GATE_DRIVERS") or "").strip()
    incident_status = str(row.get("WORST_INCIDENT_STATUS") or "")
    incident_action = str(row.get("INCIDENT_CONTAINMENT") or "").strip()
    section_action = str(row.get("SECTION_NEXT_ACTION") or "").strip()
    next_99 = str(row.get("NEXT_99_MOVE") or "").strip()
    if overdue or "Containment" in incident_status:
        return "Contain Now", incident_action or "Escalate overdue work and capture route, ticket, and telemetry status."
    if proof_blocks or source_issues:
        return "Restore Control Telemetry", incident_action or "Refresh blocked telemetry before DBA execution."
    if metadata_blocks:
        return "Unblock Route Metadata", "Complete route, ticket, reviewer, and telemetry metadata."
    if approval_blocks:
        return "Review Required", "Collect review status before executing DBA-controlled action."
    if execution_ready:
        return "Execute Ready Work", "Work execution-ready items, then monitor before/after telemetry."
    if effective_score < section_score:
        detail = f"Resolve gate driver(s): {gate_drivers}." if gate_drivers and gate_drivers != "none" else "Resolve active deployment gate driver(s)."
        return "Deployment Gate", detail
    if effective_score < 99:
        return "Review Route", next_99 or section_action or "Harden the lowest control component and preserve closure status."
    return "Monitor", "Maintain data health, escalation route, and closure status."


def _dba_escalation_priority_level(priority: float, state: object = "") -> str:
    text = str(state or "").upper()
    score = safe_float(priority)
    if score >= 90 or any(token in text for token in ("BLOCK", "CONTAIN", "OVERDUE")):
        return "Escalate Now"
    if score >= 70 or any(token in text for token in ("REFRESH", "INVESTIGATE", "HIGH")):
        return "Same Shift"
    if score >= 40 or any(token in text for token in ("REVIEW", "APPROVAL", "TRIAGE")):
        return "Route Review"
    return "Monitor"


def _dba_escalation_go_no_go(level: str, source_signals: list[str]) -> str:
    signal_text = " ".join(source_signals).upper()
    level_text = str(level or "").upper()
    if "ESCALATE" in level_text or "RELEASE GATE" in signal_text:
        return "No-Go until blocker telemetry is current."
    if "SOURCE HEALTH" in signal_text or "EVIDENCE" in signal_text:
        return "No-Go for irreversible action until telemetry is refreshed."
    if "SAME SHIFT" in level_text:
        return "Go only through the owning specialist workflow."
    return "Go for monitoring and normal DBA review."


def _control_room_score(
    exceptions: pd.DataFrame,
    row: pd.Series | dict,
    credit_delta: float,
    regression_count: int,
    cortex_exception_count: int,
) -> int:
    if exceptions is None or exceptions.empty:
        high_count = medium_count = 0
    else:
        severities = exceptions.get("Severity", pd.Series(dtype=str)).astype(str)
        high_count = int((severities == "High").sum())
        medium_count = int((severities == "Medium").sum())
    failed_queries = safe_int(row.get("FAILED_QUERIES", 0))
    queued_queries = safe_int(row.get("QUEUED_QUERIES", 0))
    remote_spill = safe_int(row.get("REMOTE_SPILL_QUERIES", 0))
    penalty = (
        high_count * 12
        + medium_count * 6
        + min(failed_queries / 10, 10)
        + min(queued_queries / 10, 8)
        + min(remote_spill / 20, 8)
        + min(max(credit_delta, 0) / 5, 10)
        + min(safe_int(regression_count) * 3, 12)
        + min(safe_int(cortex_exception_count) * 2, 10)
    )
    return max(0, min(100, int(round(100 - penalty))))

