# sections/warehouse_health.py - Warehouse stats, scaling events, idle detection, spill, heatmap
from __future__ import annotations

from datetime import datetime

import streamlit as st
from sections.base import lazy_pandas, lazy_util as _lazy_util
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_section_note, defer_source_note
from config import DEFAULT_COMPANY, DEFAULTS, DEFAULT_ENVIRONMENT, THRESHOLDS
from sections.shell_helpers import (
    consume_section_autoload_request,
    render_data_freshness,
    render_escaped_bold_text,
    render_escaped_labeled_text,
    render_shell_kpi_row,
    render_shell_snapshot,
    render_shell_status_strip,
    with_loaded_at,
)

from sections.warehouse_health_contracts import (
    WAREHOUSE_HEALTH_BRIEF_FIRST_VERSION,
    WAREHOUSE_HEALTH_BRIEF_WORKFLOWS,
    WAREHOUSE_HEALTH_DETAILS,
    WAREHOUSE_HEALTH_FAST_ENTRY_VERSION,
    WAREHOUSE_HEALTH_VIEWS,
    WAREHOUSE_OPERABILITY_FACT_TABLE,
    WAREHOUSE_SCOPE_FILTER_KEYS,
    WAREHOUSE_SETTING_REVIEW_TABLE,
)
from sections.warehouse_health_dataframes import (
    _frame_row_count,
    _scope_value,
    _source_confidence,
    _source_next_action,
    _warehouse_bool_setting,
    _warehouse_column_average,
    _warehouse_column_sum,
    _warehouse_first_setting,
    _warehouse_frame_has_rows,
    _warehouse_frame_len,
    _warehouse_frame_sum,
    _warehouse_looks_like_frame,
    _warehouse_meta_matches,
    _warehouse_operator_next_moves,
    _warehouse_overview_exceptions,
    _warehouse_period_movement,
    _warehouse_row_by_name,
    _warehouse_scope_meta,
    _warehouse_setting_present,
    _warehouse_state_count,
    _warehouse_source_health_rows,
    _warehouse_text,
    _warehouse_upper_frame,
    _warehouse_value_count,
)
from sections.warehouse_health_helpers import (
    _warehouse_capacity_action_for,
    _warehouse_capacity_score,
    _warehouse_capacity_workflow_for,
)
from sections.warehouse_health_sql import (
    _admin_audit_fqn,
    _overwatch_dedicated_warehouse_setup_sql,
    _warehouse_action_queue_closure_sql,
    _warehouse_capacity_verification_sql,
    _warehouse_cost_control_review_sql,
    _warehouse_operability_fact_sql,
    _warehouse_setting_execution_audit_sql,
    _warehouse_setting_review_history_sql,
    _warehouse_setting_review_sql,
    _warehouse_sql_identifier,
    build_warehouse_operability_fact_ddl,
    build_warehouse_operability_fact_migration_sql,
    build_warehouse_setting_review_ddl,
    build_warehouse_setting_review_migration_sql,
    warehouse_operability_fact_fqn,
    warehouse_setting_review_fqn,
)


pd = lazy_pandas()

get_session_for_action = _lazy_util("get_session_for_action")
format_credits = _lazy_util("format_credits")
download_csv = _lazy_util("download_csv")
render_drillable_bar_chart = _lazy_util("render_drillable_bar_chart")
get_wh_filter_clause = _lazy_util("get_wh_filter_clause")
get_global_filter_clause = _lazy_util("get_global_filter_clause")
metric_confidence_label = _lazy_util("metric_confidence_label")
freshness_note = _lazy_util("freshness_note")
make_action_id = _lazy_util("make_action_id")
upsert_actions = _lazy_util("upsert_actions")
run_query = _lazy_util("run_query")
format_snowflake_error = _lazy_util("format_snowflake_error")
filter_existing_columns = _lazy_util("filter_existing_columns")
render_optimization_advisor = _lazy_util("render_optimization_advisor")
load_shared_warehouse_overview = _lazy_util("load_shared_warehouse_overview")
load_shared_warehouse_scaling_events = _lazy_util("load_shared_warehouse_scaling_events")
load_shared_warehouse_efficiency = _lazy_util("load_shared_warehouse_efficiency")
load_shared_warehouse_spill = _lazy_util("load_shared_warehouse_spill")
load_shared_warehouse_heatmap = _lazy_util("load_shared_warehouse_heatmap")
load_warehouse_inventory = _lazy_util("load_warehouse_inventory")
resolve_owner_context = _lazy_util("resolve_owner_context")
sql_literal = _lazy_util("sql_literal")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
render_load_status = _lazy_util("render_load_status")
render_workflow_selector = _lazy_util("render_workflow_selector")
day_window_selectbox = _lazy_util("day_window_selectbox")


def get_active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def get_active_environment() -> str:
    return str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)


def render_operator_briefing(items: list[tuple[str, str]], *, columns: int = 4) -> None:
    for label, detail in items:
        defer_section_note(f"{label}: {detail}")


def _warehouse_action_session(action: str):
    return get_session_for_action(
        action,
        surface="Warehouse Health",
        offline_note="Warehouse shell, source summaries, and cached telemetry remain visible without a live connection.",
    )


def _warehouse_action_brief(company: str, environment: str, days: int) -> dict:
    overview = st.session_state.get("wh_df_wh")
    overview_meta = st.session_state.get("wh_df_wh_meta")
    overview_expected = _warehouse_scope_meta(company, environment, days)
    overview_loaded = _warehouse_looks_like_frame(overview)
    overview_current = overview_loaded and _warehouse_meta_matches(overview_meta, overview_expected)

    capacity_days = safe_int(st.session_state.get("wh_capacity_days", 7), 7) or 7
    capacity_meta = st.session_state.get("wh_capacity_meta")
    capacity_expected = _warehouse_scope_meta(company, environment, capacity_days)
    capacity_current = _warehouse_meta_matches(capacity_meta, capacity_expected)
    summary = st.session_state.get("wh_capacity_summary")
    exceptions = st.session_state.get("wh_capacity_exceptions")
    high_risk = _warehouse_value_count(exceptions, "SEVERITY", {"Critical", "High"}) if capacity_current else 0

    if overview_loaded and not overview_current:
        return {
            "state": "Stale",
            "headline": "Reload Warehouse Data before acting.",
            "detail": "Loaded warehouse telemetry does not match the active company, environment, lookback, or triage filters.",
        }
    if high_risk:
        queued = 0
        spill = 0
        if _warehouse_frame_has_rows(summary):
            row = summary.iloc[0]
            queued = safe_int(row.get("QUEUED_QUERIES", 0))
            spill = safe_int(row.get("SPILL_QUERIES", 0))
        return {
            "state": "Capacity Review",
            "headline": "Review high-risk warehouse pressure first.",
            "detail": (
                f"{high_risk:,} Critical/High exception(s); confirm "
                f"{queued:,} queued and {spill:,} spill signal(s) before settings changes."
            ),
        }
    if overview_current and _warehouse_frame_has_rows(overview):
        warehouses = _warehouse_frame_len(overview)
        total_queries = int(_warehouse_column_sum(overview, "TOTAL_QUERIES"))
        remote_spill = _warehouse_column_sum(overview, "TOTAL_REMOTE_SPILL_GB")
        return {
            "state": "Loaded",
            "headline": "Use the loaded overview before changing warehouse settings.",
            "detail": (
                f"{warehouses:,} warehouse(s), {total_queries:,} queries, "
                f"and {remote_spill:,.1f} GB remote spill in the selected window."
            ),
        }
    if overview_current and overview_loaded:
        return {
            "state": "No Rows",
            "headline": "No warehouse activity found for this scope.",
            "detail": "Confirm filters before opening specialist warehouse workflows.",
        }
    if st.session_state.get("wh_settings_inventory_error"):
        return {
            "state": "Metadata Gap",
            "headline": "Warehouse metadata needs access before guardrails are complete.",
            "detail": "Load overview telemetry when Snowflake grants are ready; specialist workflows stay gated.",
        }
    return {
        "state": "Ready",
        "headline": "Load Warehouse Data before changing size, clusters, or suspend policy.",
        "detail": "The overview stays quiet until the selected DBA scope is requested.",
    }


def _render_warehouse_action_brief(brief: dict) -> None:
    render_shell_status_strip(
        state=brief.get("state") or "Review",
        headline=brief.get("headline") or "Review warehouse telemetry.",
        detail=brief.get("detail") or "",
    )


def _warehouse_operating_snapshot(company: str, environment: str, days: int) -> dict:
    overview = st.session_state.get("wh_df_wh")
    expected_meta = _warehouse_scope_meta(company, environment, days)
    if not _warehouse_looks_like_frame(overview) or not _warehouse_meta_matches(
        st.session_state.get("wh_df_wh_meta"),
        expected_meta,
    ):
        return {
            "loaded": False,
            "scope": str(company or "All"),
            "window": f"{safe_int(days, 14):d}d",
            "evidence": "Load overview",
            "focus": "Pressure",
        }
    return {
        "loaded": True,
        "warehouses": _warehouse_frame_len(overview),
        "queries": safe_int(_warehouse_column_sum(overview, "TOTAL_QUERIES")),
        "spill_gb": _warehouse_column_sum(overview, "TOTAL_REMOTE_SPILL_GB"),
        "avg_queue": _warehouse_column_average(overview, "AVG_QUEUED_SEC"),
    }


def _render_warehouse_operating_snapshot(snapshot: dict) -> None:
    loaded = bool(snapshot.get("loaded"))
    if not loaded:
        render_shell_kpi_row((
            ("Scope", str(snapshot.get("scope") or "All")),
            ("Window", str(snapshot.get("window") or "14d")),
            ("Telemetry", str(snapshot.get("evidence") or "Load overview")),
        ))
        return
    render_shell_kpi_row((
        ("Warehouses", f"{safe_int(snapshot.get('warehouses')):,}"),
        ("Queries", f"{safe_int(snapshot.get('queries')):,}"),
        ("Spill GB", f"{safe_float(snapshot.get('spill_gb')):,.1f}"),
        ("Avg Queue", f"{safe_float(snapshot.get('avg_queue')):,.1f}s"),
    ))


def _queue_warehouse_health_view(view: str) -> None:
    if view in WAREHOUSE_HEALTH_VIEWS:
        st.session_state["warehouse_health_requested_view"] = view
        st.rerun()


def _apply_queued_warehouse_health_view() -> None:
    requested_view = st.session_state.pop("warehouse_health_requested_view", None)
    if requested_view in WAREHOUSE_HEALTH_VIEWS:
        st.session_state["warehouse_health_view"] = requested_view


def _apply_warehouse_brief_first_default() -> None:
    if st.session_state.get("_warehouse_health_brief_first_version") == WAREHOUSE_HEALTH_BRIEF_FIRST_VERSION:
        return
    has_overview_rows = _warehouse_frame_has_rows(st.session_state.get("wh_df_wh"))
    if (
        not has_overview_rows
        and not _warehouse_support_panels_have_state()
        and st.session_state.get("warehouse_health_view") not in (None, "Overview & Scaling")
    ):
        st.session_state["warehouse_health_view"] = "Overview & Scaling"
    st.session_state["_warehouse_health_brief_first_version"] = WAREHOUSE_HEALTH_BRIEF_FIRST_VERSION


def _warehouse_brief_workflow_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in WAREHOUSE_HEALTH_BRIEF_WORKFLOWS:
        view = str(item["VIEW"])
        rows.append({
            "VIEW": view,
            "BUTTON_LABEL": str(item["BUTTON_LABEL"]),
            "DBA_MOVE": str(item["DBA_MOVE"]),
            "WHEN": str(item["WHEN"]),
            "SOURCES": WAREHOUSE_HEALTH_DETAILS.get(view, "Warehouse workflow detail"),
        })
    return rows


def _render_warehouse_brief_launchpad() -> None:
    st.markdown("**Warehouse Investigation Workflows**")
    rows = _warehouse_brief_workflow_rows()
    for offset in range(0, len(rows), 3):
        cols = st.columns(3)
        for col, row in zip(cols, rows[offset:offset + 3]):
            with col:
                render_escaped_bold_text(row["VIEW"])
                help_text = f"{row['DBA_MOVE']} When: {row['WHEN']}"
                if st.button(
                    row["BUTTON_LABEL"],
                    key=f"warehouse_brief_{row['VIEW']}",
                    help=help_text,
                    width="stretch",
                ):
                    _queue_warehouse_health_view(row["VIEW"])


def _warehouse_sql_exprs(session) -> dict[str, str]:
    """Resolve optional ACCOUNT_USAGE columns only when a live query is requested."""
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "WAREHOUSE_SIZE",
            "QUEUED_OVERLOAD_TIME",
            "BYTES_SPILLED_TO_LOCAL_STORAGE",
            "BYTES_SPILLED_TO_REMOTE_STORAGE",
            "PERCENTAGE_SCANNED_FROM_CACHE",
            "BYTES_SCANNED",
        ],
    ))
    wm_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
        ["CREDITS_USED_COMPUTE", "CREDITS_USED_CLOUD_SERVICES"],
    ))
    return {
        "wh_size_expr": "MAX(q.warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR",
        "plain_wh_size_expr": "MAX(warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR",
        "latest_size_expr": "q.warehouse_size" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR",
        "queue_avg_expr": "AVG(q.queued_overload_time)/1000" if "QUEUED_OVERLOAD_TIME" in qh_cols else "0",
        "queue_sum_expr": "SUM(q.queued_overload_time)" if "QUEUED_OVERLOAD_TIME" in qh_cols else "0",
        "remote_spill_sum_expr": (
            "SUM(q.bytes_spilled_to_remote_storage)"
            if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
            else "0"
        ),
        "local_spill_expr": (
            "SUM(bytes_spilled_to_local_storage)"
            if "BYTES_SPILLED_TO_LOCAL_STORAGE" in qh_cols
            else "0"
        ),
        "local_spill_row_expr": (
            "bytes_spilled_to_local_storage"
            if "BYTES_SPILLED_TO_LOCAL_STORAGE" in qh_cols
            else "0"
        ),
        "remote_spill_expr": (
            "SUM(bytes_spilled_to_remote_storage)"
            if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
            else "0"
        ),
        "remote_spill_row_expr": (
            "bytes_spilled_to_remote_storage"
            if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
            else "0"
        ),
        "cache_expr": "AVG(q.percentage_scanned_from_cache)" if "PERCENTAGE_SCANNED_FROM_CACHE" in qh_cols else "0",
        "bytes_scanned_expr": "SUM(q.bytes_scanned)" if "BYTES_SCANNED" in qh_cols else "0",
        "compute_meter_expr": "m.credits_used_compute" if "CREDITS_USED_COMPUTE" in wm_cols else "m.credits_used",
        "cloud_meter_expr": "m.credits_used_cloud_services" if "CREDITS_USED_CLOUD_SERVICES" in wm_cols else "0::FLOAT",
    }


def _route_label(value: object, default: str = "Platform DBA") -> str:
    text = str(value or default).strip() or default
    text = text.replace("Owner", "Route").replace("owner", "route")
    for duplicate in ("Route Route", "Route route", "route Route", "route route"):
        while duplicate in text:
            text = text.replace(duplicate, "Route")
    return text.replace("Cost route", "Cost Route")


def _warehouse_owner_context(row: pd.Series | dict) -> dict:
    wh = str(row.get("WAREHOUSE_NAME") or "").upper()
    signal = str(row.get("SIGNAL") or "").upper()
    if "CREDIT" in signal:
        base = {
            "owner": "DBA / Cost owner Route",
            "escalation": "Cost owner / DBA Lead",
            "source": "Warehouse signal route map",
        }
    elif any(token in wh for token in ("ETL", "LOAD", "TASK", "PIPE", "AIRFLOW", "DBT")):
        base = {
            "owner": "Data Engineering Route",
            "escalation": "Pipeline Route / DBA On-Call",
            "source": "Warehouse name route hint",
        }
    elif any(token in wh for token in ("BI", "REPORT", "LOOKER", "POWERBI", "TABLEAU")):
        base = {
            "owner": "BI Platform Route",
            "escalation": "BI Product Route / DBA Lead",
            "source": "Warehouse name route hint",
        }
    elif any(token in wh for token in ("DEV", "SAN", "SIT", "PHX", "SEA")):
        base = {
            "owner": "Development Platform Route",
            "escalation": "DBA Lead",
            "source": "Warehouse name route hint",
        }
    else:
        base = {
            "owner": "Platform DBA",
            "escalation": "DBA Lead",
            "source": "Default warehouse route",
        }
    directory_context = resolve_owner_context(
        row,
        entity=wh,
        entity_type="WAREHOUSE",
        owner=base["owner"],
        category=signal or "Warehouse Capacity",
    )
    return {
        "owner": _route_label(directory_context.get("OWNER") or base["owner"]),
        "escalation": base["escalation"] or directory_context.get("ESCALATION_TARGET", ""),
        "source": _route_label(f"{base['source']}; {directory_context.get('OWNER_SOURCE', '')}".strip("; ")),
        "owner_email": directory_context.get("OWNER_EMAIL", ""),
        "oncall_primary": directory_context.get("ONCALL_PRIMARY", ""),
        "oncall_secondary": directory_context.get("ONCALL_SECONDARY", ""),
        "approval_group": base["escalation"] or directory_context.get("APPROVAL_GROUP", ""),
        "owner_evidence": _route_label(directory_context.get("OWNER_EVIDENCE", "")),
    }


def _warehouse_approval_for(row: pd.Series | dict) -> str:
    signal = str(row.get("SIGNAL") or "").upper()
    owner = _route_label(row.get("OWNER") or _warehouse_owner_context(row)["owner"])
    if "CREDIT" in signal:
        return "Cost owner / Warehouse Route"
    if "QUEUE" in signal:
        return f"{owner} / DBA Lead"
    if "SPILL" in signal:
        return f"{owner} / Query Route"
    return f"{owner} / DBA Lead"


def _warehouse_setting_candidate_for(row: pd.Series) -> dict:
    """Return the reviewed settings lane for a warehouse capacity exception."""
    signal = str(row.get("SIGNAL") or "").upper()
    queued = safe_int(row.get("QUEUED_QUERIES"))
    spill = safe_int(row.get("SPILL_QUERIES"))
    high_latency = safe_int(row.get("HIGH_LATENCY_QUERIES"))
    spike = safe_float(row.get("CREDIT_SPIKE_PCT"))
    p95 = safe_float(row.get("P95_ELAPSED_SEC"))

    if "QUEUE" in signal:
        candidate = "Review MAX_CLUSTER_COUNT, SCALING_POLICY, WAREHOUSE_SIZE, and workload routing."
        safe_path = (
            "Use Warehouse Settings Manager to load current settings, review any multi-cluster or size change, "
            "capture rollback SQL, then verify queue count and p95 latency."
        )
        risk = "Scaling can improve concurrency but may multiply credit burn or hide workload design problems."
    elif "SPILL" in signal:
        candidate = "Review WAREHOUSE_SIZE only after top spilling queries, clustering, and query shape are inspected."
        safe_path = (
            "Use Query Profile telemetry before resizing; if a size change is planned, capture rollback SQL and "
            "monitor spill count, p95 latency, and credits after the change."
        )
        risk = "Blind resizing can mask inefficient SQL and permanently raise run-rate cost."
    elif "CREDIT" in signal:
        candidate = "Review AUTO_SUSPEND, MIN_CLUSTER_COUNT, MAX_CLUSTER_COUNT, QAS, and workload schedule alignment."
        safe_path = (
            "Use Warehouse Settings Manager to compare current settings with burn drivers, require review status, "
            "save rollback SQL, then monitor credits and query volume after the change."
        )
        risk = "Cost controls can affect availability, queueing, or service-level expectations if applied broadly."
    else:
        candidate = "Review STATEMENT_TIMEOUT_IN_SECONDS, MAX_CONCURRENCY_LEVEL, WAREHOUSE_SIZE, and workload routing."
        safe_path = (
            "Use Warehouse Settings Manager for changed-only SQL, review status, rollback SQL, and post-change "
            "runtime telemetry."
        )
        risk = "Latency changes can shift failures, queueing, or user experience if applied without workload telemetry."

    readiness = "Ready for DBA review" if str(row.get("WAREHOUSE_NAME") or "").strip() else "Missing warehouse identity"
    owner_context = _warehouse_owner_context(row)
    return {
        "ADMIN_READINESS": readiness,
        "OWNER": owner_context["owner"],
        "ESCALATION_TARGET": owner_context["escalation"],
        "OWNER_SOURCE": owner_context["source"],
        "OWNER_EMAIL": owner_context.get("owner_email", ""),
        "ONCALL_PRIMARY": owner_context.get("oncall_primary", ""),
        "ONCALL_SECONDARY": owner_context.get("oncall_secondary", ""),
        "APPROVAL_GROUP": owner_context.get("approval_group", ""),
        "OWNER_EVIDENCE": owner_context.get("owner_evidence", ""),
        "APPROVER": _warehouse_approval_for({**row.to_dict(), **owner_context} if hasattr(row, "to_dict") else row),
        "SETTING_CHANGE_CANDIDATE": candidate,
        "APPROVAL_REQUIRED": "Yes",
        "ROLLBACK_REQUIRED": "Yes",
        "SAFE_CHANGE_PATH": safe_path,
        "CHANGE_RISK": risk,
        "POST_CHANGE_VERIFICATION": (
            "Compare queued queries, spill queries, p95 latency, and metered credits for the same warehouse/environment "
            "before closing the action."
        ),
        "IMPACT_TELEMETRY_REQUIRED": "Yes" if "CREDIT" in signal else "No",
        "PRESSURE_EVIDENCE": (
            f"queued={queued:,}; spill={spill:,}; high_latency={high_latency:,}; "
            f"credit_spike={spike:,.1f}%; p95={p95:,.2f}s"
        ),
    }


def _annotate_warehouse_admin_readiness(exceptions: pd.DataFrame) -> pd.DataFrame:
    if exceptions is None or exceptions.empty:
        return pd.DataFrame() if exceptions is None else exceptions
    rows = []
    for _, row in exceptions.iterrows():
        rows.append(_warehouse_setting_candidate_for(row))
    readiness = pd.DataFrame(rows, index=exceptions.index)
    annotated = exceptions.copy()
    for column in readiness.columns:
        annotated[column] = readiness[column]
    return annotated


def _warehouse_setting_audit_readiness_for_row(row: pd.Series | dict) -> dict:
    """Score whether a warehouse setting change has review, execution, and telemetry status."""
    owner = str(row.get("OWNER") or "").strip()
    owner_source = str(row.get("OWNER_SOURCE") or "").upper()
    approver = str(row.get("APPROVER") or row.get("APPROVAL_GROUP") or "").strip()
    approval_required = str(row.get("APPROVAL_REQUIRED") or "Yes").upper() == "YES"
    rollback_required = str(row.get("ROLLBACK_REQUIRED") or "Yes").upper() == "YES"
    savings_required = str(row.get("IMPACT_TELEMETRY_REQUIRED") or "No").upper() == "YES"
    approval_state = str(row.get("APPROVAL_STATE") or row.get("OWNER_APPROVAL_STATUS") or "").upper()
    ticket_id = str(row.get("CHANGE_TICKET_ID") or row.get("TICKET_ID") or "").strip()
    rollback_sql = str(row.get("ROLLBACK_SQL") or "").strip()
    execution_status = str(row.get("EXECUTION_STATUS") or "Not Executed").upper()
    sql_hash = str(row.get("EXECUTED_SQL_HASH") or row.get("SQL_HASH") or "").strip()
    verification_status = str(
        row.get("POST_CHANGE_VERIFICATION_STATUS")
        or row.get("VERIFICATION_STATUS")
        or ""
    ).upper()
    verification_result = str(
        row.get("POST_CHANGE_VERIFICATION_RESULT")
        or row.get("VERIFICATION_RESULT")
        or ""
    ).strip()
    verified_savings = safe_float(row.get("VERIFIED_MONTHLY_SAVINGS"))

    blockers: list[str] = []
    generic_owners = {"", "DBA", "UNKNOWN", "N/A"}
    owner_route_ready = bool(owner) and owner.upper() not in generic_owners and bool(owner_source or approver)
    if not owner_route_ready:
        blockers.append("escalation route")
    if approval_required and approval_state not in {"APPROVED", "APPROVAL NOT REQUIRED", "NOT REQUIRED"}:
        blockers.append("review status")
    if not ticket_id:
        blockers.append("change ticket")
    if rollback_required and not rollback_sql:
        blockers.append("rollback SQL")

    executed = execution_status in {"SUCCESS", "EXECUTED", "COMPLETED"}
    failed = execution_status in {"FAILED", "ERROR"}
    if executed and not sql_hash:
        blockers.append("admin execution hash")
    if executed and (verification_status != "VERIFIED" or len(verification_result) < 15):
        blockers.append("post-change telemetry")
    if executed and savings_required and verified_savings <= 0:
        blockers.append("impact telemetry")

    route_blockers = {"escalation route"}
    pre_change_blockers = {"review status", "change ticket", "rollback SQL"}
    verification_blockers = {"admin execution hash", "post-change telemetry", "impact telemetry"}

    if failed:
        readiness = "Execution Failed"
        rank = 0
    elif any(item in route_blockers for item in blockers):
        readiness = "Route Metadata Blocked"
        rank = 1
    elif any(item in pre_change_blockers for item in blockers):
        readiness = "Pre-Change Blocked"
        rank = 2
    elif any(item in verification_blockers for item in blockers):
        readiness = "Telemetry Pending"
        rank = 3
    elif executed:
        readiness = "Change Audit Linked"
        rank = 8
    else:
        readiness = "Ready for Controlled Change"
        rank = 6

    if failed:
        next_action = "Open the failed admin audit row, correct the setting plan, and keep rollback status with the ticket."
    elif "escalation route" in blockers:
        next_action = "Add DBA escalation context before executing warehouse setting changes."
    elif "review status" in blockers:
        next_action = "Capture review status before running ALTER WAREHOUSE."
    elif "change ticket" in blockers:
        next_action = "Add the change ticket to the warehouse setting review."
    elif "rollback SQL" in blockers:
        next_action = "Generate and retain rollback SQL from the guarded warehouse settings workflow before execution."
    elif "post-change telemetry" in blockers:
        next_action = "Refresh queue/spill/credit telemetry before closure."
    elif "impact telemetry" in blockers:
        next_action = "Wait for measured impact telemetry before closing the credit-control change."
    elif executed:
        next_action = "Keep execution, rollback, and post-change telemetry with the audit trail."
    else:
        next_action = "Route through the guarded warehouse settings workflow for changed-only SQL and audit logging."

    return {
        "AUDIT_READINESS": readiness,
        "AUDIT_RANK": rank,
        "AUDIT_BLOCKERS": "; ".join(blockers) if blockers else "None",
        "OWNER_ROUTE_READY": "Yes" if owner_route_ready else "No",
        "NEXT_CONTROL_ACTION": next_action,
    }


def _warehouse_setting_control_board(
    exceptions: pd.DataFrame,
    owner_inventory: pd.DataFrame | None = None,
    closure: pd.DataFrame | None = None,
    execution_audit: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Combine capacity findings, closure, and execution audit into one DBA board."""
    if exceptions is None or exceptions.empty:
        return pd.DataFrame()

    findings = _warehouse_capacity_priority_view(exceptions)
    if findings.empty:
        return pd.DataFrame()

    owners = pd.DataFrame() if owner_inventory is None else owner_inventory.copy()
    if not owners.empty:
        owners.columns = [str(col).upper() for col in owners.columns]
    closure_view = pd.DataFrame() if closure is None else closure.copy()
    if not closure_view.empty:
        closure_view.columns = [str(col).upper() for col in closure_view.columns]
    audit_view = pd.DataFrame() if execution_audit is None else execution_audit.copy()
    if not audit_view.empty:
        audit_view.columns = [str(col).upper() for col in audit_view.columns]

    owner_by_wh = {
        str(row.get("WAREHOUSE_NAME") or "").upper(): row
        for _, row in owners.iterrows()
    } if not owners.empty else {}
    closure_by_wh = {
        str(row.get("WAREHOUSE_NAME") or "").upper(): row
        for _, row in closure_view.iterrows()
    } if not closure_view.empty else {}
    audit_by_wh = {
        str(row.get("WAREHOUSE_NAME") or "").upper(): row
        for _, row in audit_view.iterrows()
    } if not audit_view.empty else {}

    rows: list[dict] = []
    for _, row in findings.iterrows():
        wh = str(row.get("WAREHOUSE_NAME") or "")
        wh_key = wh.upper()
        owner_row = owner_by_wh.get(wh_key, {})
        closure_row = closure_by_wh.get(wh_key, {})
        audit_row = audit_by_wh.get(wh_key, {})

        audit_readiness = _warehouse_setting_audit_readiness_for_row({
            **row.to_dict(),
            "APPROVAL_STATE": audit_row.get("APPROVAL_STATE", "Requested") if len(audit_row) else "Requested",
            "CHANGE_TICKET_ID": audit_row.get("CHANGE_TICKET_ID", ""),
            "ROLLBACK_SQL": audit_row.get("ROLLBACK_SQL", ""),
            "EXECUTION_STATUS": audit_row.get("LAST_EXECUTION_STATUS", audit_row.get("EXECUTION_STATUS", "Not Executed")),
            "EXECUTED_SQL_HASH": audit_row.get("LAST_SQL_HASH", audit_row.get("EXECUTED_SQL_HASH", "")),
            "POST_CHANGE_VERIFICATION_STATUS": audit_row.get("POST_CHANGE_VERIFICATION_STATUS", ""),
            "POST_CHANGE_VERIFICATION_RESULT": audit_row.get("POST_CHANGE_VERIFICATION_RESULT", ""),
            "VERIFIED_MONTHLY_SAVINGS": audit_row.get("VERIFIED_MONTHLY_SAVINGS", 0),
        })

        route_readiness = str(owner_row.get("ROUTE_READINESS") or "Monitoring")
        closure_readiness = str(closure_row.get("CLOSURE_READINESS") or "On demand")
        closure_rank = safe_int(closure_row.get("CLOSURE_RANK", 9))
        overdue = safe_int(closure_row.get("OVERDUE_OPEN", 0))
        fixed_without_verification = safe_int(closure_row.get("FIXED_WITHOUT_VERIFICATION", 0))
        failed_changes = safe_int(audit_row.get("FAILED_CHANGES", 0))
        audit_rows = safe_int(audit_row.get("AUDIT_ROWS", 0))

        if overdue:
            state, rank = "Closure Overdue", 0
            next_action = "Escalate overdue warehouse capacity action before planning more setting changes."
        elif fixed_without_verification or closure_rank in {1, 2}:
            state, rank = "Closure Status Pending", 1
            next_action = str(closure_row.get("NEXT_ACTION") or "Reopen warehouse work or wait for telemetry to confirm closure.")
        elif audit_readiness["AUDIT_READINESS"] == "Route Metadata Blocked":
            state, rank = "Route Metadata Blocked", 2
            next_action = audit_readiness["NEXT_CONTROL_ACTION"]
        elif failed_changes:
            state, rank = "Execution Failed", 3
            next_action = "Review failed ALTER WAREHOUSE audit rows and confirm rollback or no-op state."
        elif audit_readiness["AUDIT_READINESS"] in {"Pre-Change Blocked", "Telemetry Pending"}:
            state, rank = audit_readiness["AUDIT_READINESS"], audit_readiness["AUDIT_RANK"]
            next_action = audit_readiness["NEXT_CONTROL_ACTION"]
        elif audit_rows:
            state, rank = "Execution Audit Linked", 7
            next_action = "Confirm post-change queue, spill, credit, and impact telemetry remains current."
        else:
            state, rank = "Ready for Controlled Change", 6
            next_action = "Open the guarded warehouse settings workflow, generate changed-only SQL, and keep rollback status current."

        rows.append({
            "CONTROL_STATE": state,
            "CONTROL_RANK": rank,
            "WAREHOUSE_NAME": wh,
            "SEVERITY": row.get("SEVERITY", ""),
            "SIGNAL": row.get("SIGNAL", ""),
            "CAPACITY_SCORE": safe_float(row.get("CAPACITY_SCORE")),
            "METERED_CREDITS": safe_float(row.get("METERED_CREDITS")),
            "OWNER": row.get("OWNER", ""),
            "ROUTE_READINESS": route_readiness,
            "AUDIT_READINESS": audit_readiness["AUDIT_READINESS"],
            "AUDIT_BLOCKERS": audit_readiness["AUDIT_BLOCKERS"],
            "CLOSURE_READINESS": closure_readiness,
            "OVERDUE_OPEN": overdue,
            "FIXED_WITHOUT_VERIFICATION": fixed_without_verification,
            "AUDIT_ROWS": audit_rows,
            "SUCCESSFUL_CHANGES": safe_int(audit_row.get("SUCCESSFUL_CHANGES", 0)),
            "FAILED_CHANGES": failed_changes,
            "LAST_EXECUTION_STATUS": audit_row.get("LAST_EXECUTION_STATUS", "On demand"),
            "LAST_EXECUTED_AT": audit_row.get("LAST_EXECUTED_AT", ""),
            "APPROVAL_REQUIRED": row.get("APPROVAL_REQUIRED", "No"),
            "ROLLBACK_REQUIRED": row.get("ROLLBACK_REQUIRED", "Yes"),
            "IMPACT_TELEMETRY_REQUIRED": row.get("IMPACT_TELEMETRY_REQUIRED", "No"),
            "SETTING_CHANGE_CANDIDATE": row.get("SETTING_CHANGE_CANDIDATE", ""),
            "NEXT_CONTROL_ACTION": next_action,
        })

    return pd.DataFrame(rows).sort_values(
        ["CONTROL_RANK", "OVERDUE_OPEN", "FAILED_CHANGES", "CAPACITY_SCORE", "METERED_CREDITS"],
        ascending=[True, False, False, True, False],
    ).reset_index(drop=True)


def _build_warehouse_cost_control_posture(
    settings_inventory: pd.DataFrame | None,
    overview: pd.DataFrame | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Build current warehouse suspend/resume posture from SHOW WAREHOUSES metadata."""
    columns = [
        "WAREHOUSE_NAME", "COST_CONTROL_STATE", "IDLE_RISK", "AUTO_SUSPEND_SEC",
        "AUTO_RESUME", "WAREHOUSE_SIZE", "STATE", "METERED_CREDITS",
        "RECOMMENDED_AUTO_SUSPEND_SEC", "RECOMMENDED_ACTION", "REVIEW_SQL",
        "POSTURE_RANK",
    ]
    settings = _warehouse_upper_frame(settings_inventory)
    if settings.empty:
        return {
            "warehouses": 0,
            "blocked": 0,
            "review": 0,
            "ready": 0,
            "overwatch_candidates": 0,
        }, pd.DataFrame(columns=columns)

    overview_by_wh = _warehouse_row_by_name(_warehouse_upper_frame(overview))
    rows: list[dict[str, object]] = []
    for _, row in settings.iterrows():
        wh_name = _warehouse_text(row.get("NAME") or row.get("WAREHOUSE_NAME"))
        if not wh_name:
            continue
        wh_key = wh_name.upper()
        suspend_value = row.get("AUTO_SUSPEND")
        auto_suspend = safe_int(suspend_value, -1) if _warehouse_setting_present(suspend_value) else None
        auto_resume = _warehouse_bool_setting(row.get("AUTO_RESUME"))
        overview_row = overview_by_wh.get(wh_key, {})
        metered = safe_float(overview_row.get("METERED_CREDITS"))
        recommended_suspend = 60 if wh_key in {"COMPUTE_WH", "COMPUTE_WH"} or "OVERWATCH" in wh_key else 300

        reasons: list[str] = []
        rank = 8
        if auto_suspend is None:
            state = "Data Missing"
            idle_risk = "Unknown"
            reasons.append("AUTO_SUSPEND was not available from SHOW WAREHOUSES.")
            rank = 4
        elif auto_suspend == 0:
            state = "Blocked"
            idle_risk = "Never suspends"
            reasons.append("AUTO_SUSPEND is disabled, so idle compute can continue burning credits.")
            rank = 0
        elif auto_suspend > 1000:
            state = "Needs Review"
            idle_risk = "Longer than current 1000s session timeout"
            reasons.append("AUTO_SUSPEND exceeds the current COMPUTE_WH session-timeout context.")
            rank = 1
        elif auto_suspend > 600:
            state = "Needs Review"
            idle_risk = "Over 10 minutes"
            reasons.append("AUTO_SUSPEND is above ten minutes; verify the cache/performance tradeoff is intentional.")
            rank = 2
        elif auto_suspend > 300:
            state = "Watch"
            idle_risk = "Over 5 minutes"
            reasons.append("AUTO_SUSPEND is conservative but may be high for DBA monitoring workloads.")
            rank = 5
        else:
            state = "Ready"
            idle_risk = "Bounded"
            reasons.append("AUTO_SUSPEND is inside the recommended DBA monitoring range.")

        if auto_resume is False:
            state = "Blocked"
            rank = min(rank, 0)
            reasons.append("AUTO_RESUME is disabled; operators may hit avoidable startup failures.")
        elif auto_resume is None:
            if state == "Ready":
                state = "Data Missing"
            rank = min(rank, 4)
            reasons.append("AUTO_RESUME was not available from SHOW WAREHOUSES.")

        if wh_key == "COMPUTE_WH":
            if state == "Ready":
                state = "Watch"
                rank = min(rank, 5)
            reasons.append("This is the current shared OVERWATCH warehouse; prefer idle guard plus short auto-suspend.")
        elif "OVERWATCH" in wh_key:
            reasons.append("This appears to be an OVERWATCH-dedicated warehouse; keep it small, auto-resuming, and fast-suspending.")

        if state == "Blocked":
            action = f"Review and set AUTO_SUSPEND={recommended_suspend}, AUTO_RESUME=TRUE, then monitor the next complete window."
        elif state in {"Needs Review", "Watch"}:
            action = f"Validate workload impact, then consider AUTO_SUSPEND={recommended_suspend} with AUTO_RESUME=TRUE."
        elif state == "Data Missing":
            action = "Reload warehouse metadata or verify role can see SHOW WAREHOUSES settings."
        else:
            action = "Keep current suspend/resume policy visible in warehouse cost-control reviews."

        rows.append({
            "WAREHOUSE_NAME": wh_name,
            "COST_CONTROL_STATE": state,
            "IDLE_RISK": idle_risk,
            "AUTO_SUSPEND_SEC": auto_suspend,
            "AUTO_RESUME": auto_resume,
            "WAREHOUSE_SIZE": row.get("WAREHOUSE_SIZE", ""),
            "STATE": row.get("STATE", ""),
            "METERED_CREDITS": metered,
            "RECOMMENDED_AUTO_SUSPEND_SEC": recommended_suspend,
            "RECOMMENDED_ACTION": " ".join(reasons + [action]),
            "REVIEW_SQL": _warehouse_cost_control_review_sql(wh_name, recommended_suspend),
            "POSTURE_RANK": rank,
        })

    if not rows:
        return {
            "warehouses": 0,
            "blocked": 0,
            "review": 0,
            "ready": 0,
            "overwatch_candidates": 0,
        }, pd.DataFrame(columns=columns)
    posture = pd.DataFrame(rows).sort_values(
        ["POSTURE_RANK", "METERED_CREDITS", "WAREHOUSE_NAME"],
        ascending=[True, False, True],
    ).reset_index(drop=True)
    state_series = posture["COST_CONTROL_STATE"].astype(str)
    summary = {
        "warehouses": int(len(posture)),
        "blocked": int(state_series.eq("Blocked").sum()),
        "review": int(state_series.isin(["Needs Review", "Watch", "Data Missing"]).sum()),
        "ready": int(state_series.eq("Ready").sum()),
        "overwatch_candidates": int(posture["WAREHOUSE_NAME"].astype(str).str.upper().str.contains("OVERWATCH|COMPUTE_WH").sum()),
    }
    return summary, posture[columns]


def _build_warehouse_guardrail_coverage(
    overview: pd.DataFrame | None,
    owner_inventory: pd.DataFrame | None = None,
    setting_control: pd.DataFrame | None = None,
    settings_inventory: pd.DataFrame | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Build an auto-derived warehouse guardrail board from loaded telemetry."""
    _ = owner_inventory
    overview_view = _warehouse_upper_frame(overview)
    control_view = _warehouse_upper_frame(setting_control)
    settings_view = _warehouse_upper_frame(settings_inventory)

    overview_by_wh = _warehouse_row_by_name(overview_view)
    settings_by_wh = _warehouse_row_by_name(settings_view, preferred_name_col="NAME")
    control_by_wh = _warehouse_row_by_name(control_view)

    warehouses = sorted(set(overview_by_wh) | set(settings_by_wh) | set(control_by_wh))
    if not warehouses:
        return {
            "warehouses": 0,
            "blocked": 0,
            "review": 0,
            "unknown": 0,
            "ready": 0,
            "score": 100,
        }, pd.DataFrame()

    spill_threshold = safe_float(THRESHOLDS.get("spill_warning_gb", 10), 10.0)
    rows: list[dict] = []

    for wh_key in warehouses:
        overview_row = overview_by_wh.get(wh_key, {})
        settings_row = settings_by_wh.get(wh_key, {})
        control_row = control_by_wh.get(wh_key, {})
        wh_name = (
            _warehouse_text(overview_row.get("WAREHOUSE_NAME"))
            or _warehouse_text(settings_row.get("NAME"))
            or _warehouse_text(control_row.get("WAREHOUSE_NAME"))
            or wh_key
        )

        metered = safe_float(
            overview_row.get("METERED_CREDITS", control_row.get("METERED_CREDITS", 0))
        )
        credit_delta = safe_float(overview_row.get("CREDIT_DELTA"))
        credit_delta_pct = safe_float(overview_row.get("CREDIT_DELTA_PCT"))
        queued = safe_float(overview_row.get("AVG_QUEUED_SEC"))
        spill = safe_float(overview_row.get("TOTAL_REMOTE_SPILL_GB"))
        p95 = safe_float(overview_row.get("P95_ELAPSED_SEC"))
        total_queries = safe_int(overview_row.get("TOTAL_QUERIES"))

        monitor_value, monitor_known = _warehouse_first_setting(
            settings_row,
            ("RESOURCE_MONITOR", "RESOURCE_MONITOR_NAME", "MONITOR_NAME"),
        )
        if not monitor_known:
            monitor_state = "Unknown"
            monitor_action = "Load warehouse metadata to verify resource monitor coverage."
            monitor_deduction = 10
        elif _warehouse_setting_present(monitor_value):
            monitor_state = "Ready"
            monitor_action = "Keep resource monitor assignment with the warehouse review."
            monitor_deduction = 0
        elif "OVERWATCH" in wh_key or wh_key == "COMPUTE_WH":
            monitor_state = "Blocked"
            monitor_action = "Assign COMPUTE_WH to COMPUTE_WH_RM before declaring release compute guarded."
            monitor_deduction = 28
        elif metered >= 50 or credit_delta > 0:
            monitor_state = "Review"
            monitor_action = "Review resource monitor assignment for this active or rising-cost warehouse."
            monitor_deduction = 16
        else:
            monitor_state = "Review"
            monitor_action = "Confirm whether this low-volume warehouse should share or receive a resource monitor."
            monitor_deduction = 12

        suspend_value, suspend_known = _warehouse_first_setting(settings_row, ("AUTO_SUSPEND",))
        if not suspend_known or not _warehouse_setting_present(suspend_value):
            suspend_state = "Unknown"
            suspend_action = "Load warehouse metadata to verify AUTO_SUSPEND."
            suspend_deduction = 10
        else:
            auto_suspend = safe_int(suspend_value, -1)
            if auto_suspend == 0:
                suspend_state = "Blocked" if metered > 0 else "Review"
                suspend_action = "Route AUTO_SUSPEND=0 through review and rollback status."
                suspend_deduction = 24 if metered > 0 else 14
            elif auto_suspend > 3600:
                suspend_state = "Review"
                suspend_action = "Review long auto-suspend against idle burn and service-level needs."
                suspend_deduction = 16
            elif auto_suspend > 600 and metered > 0:
                suspend_state = "Review"
                suspend_action = "Validate whether auto-suspend above ten minutes is intentional for this workload."
                suspend_deduction = 12
            else:
                suspend_state = "Ready"
                suspend_action = "AUTO_SUSPEND is inside the normal guardrail range."
                suspend_deduction = 0

        statement_timeout_value, statement_timeout_known = _warehouse_first_setting(
            settings_row,
            ("STATEMENT_TIMEOUT_IN_SECONDS", "STATEMENT_TIMEOUT"),
        )
        queued_timeout_value, queued_timeout_known = _warehouse_first_setting(
            settings_row,
            ("STATEMENT_QUEUED_TIMEOUT_IN_SECONDS", "STATEMENT_QUEUED_TIMEOUT"),
        )
        statement_timeout = None
        queued_timeout = None
        if not statement_timeout_known and not queued_timeout_known:
            timeout_state = "Unknown"
            timeout_action = "Load warehouse metadata to verify statement and queued timeout guardrails."
            timeout_deduction = 8
        else:
            statement_timeout = safe_int(statement_timeout_value, -1) if statement_timeout_known else -1
            queued_timeout = safe_int(queued_timeout_value, -1) if queued_timeout_known else -1
            timeout_risks = []
            if statement_timeout_known and statement_timeout == 0:
                timeout_risks.append("statement timeout is disabled")
            elif statement_timeout_known and statement_timeout > 14400:
                timeout_risks.append("statement timeout exceeds four hours")
            if queued_timeout_known and queued_timeout == 0 and queued > 0:
                timeout_risks.append("queued timeout is disabled while queue pressure exists")
            elif queued_timeout_known and queued_timeout > 3600 and queued > 0:
                timeout_risks.append("queued timeout exceeds one hour with queue pressure")
            if timeout_risks:
                timeout_state = "Review"
                timeout_action = "Review timeout settings before workload growth or capacity changes: " + "; ".join(timeout_risks) + "."
                timeout_deduction = 12 if queued > 0 or p95 > 60 else 8
            else:
                timeout_state = "Ready"
                timeout_action = "Statement and queued timeout guardrails are present for loaded metadata."
                timeout_deduction = 0

        control_state = str(control_row.get("CONTROL_STATE") or "").strip()
        audit_state = str(control_row.get("AUDIT_READINESS") or "").strip()
        if "Route Metadata Blocked" in {control_state, audit_state}:
            route_state = "Review"
            route_action = str(control_row.get("NEXT_CONTROL_ACTION") or "Add DBA escalation context before execution.")
            route_deduction = 4
        else:
            route_state = "Ready"
            route_action = "Escalation uses the loaded warehouse signal and DBA on-call context."
            route_deduction = 0

        pressure_reasons: list[str] = []
        if queued > 2:
            pressure_reasons.append(f"avg queue {queued:.1f}s")
        if spill > spill_threshold:
            pressure_reasons.append(f"remote spill {spill:.1f} GB")
        if p95 > 60:
            pressure_reasons.append(f"p95 {p95:.1f}s")
        if pressure_reasons:
            capacity_state = "Review"
            capacity_action = "Verify queue, spill, latency, and settings before changing warehouse capacity."
            capacity_deduction = 15
        elif total_queries:
            capacity_state = "Ready"
            capacity_action = "No loaded pressure signal crosses the warehouse review threshold."
            capacity_deduction = 0
        else:
            capacity_state = "Unknown"
            capacity_action = "Load warehouse overview data to verify pressure coverage."
            capacity_deduction = 6

        if credit_delta_pct > 50 or credit_delta >= 25:
            cost_state = "Review"
            cost_action = "Review credit delta and impact telemetry before changing cost-related settings."
            cost_deduction = 12
        elif metered > 0:
            cost_state = "Ready"
            cost_action = "Metering telemetry is loaded for this warehouse."
            cost_deduction = 0
        else:
            cost_state = "Unknown"
            cost_action = "Load warehouse metering telemetry before declaring cost guardrails covered."
            cost_deduction = 6

        states = [monitor_state, suspend_state, timeout_state, route_state, capacity_state, cost_state]
        if "Blocked" in states:
            guardrail_state = "Blocked"
            severity = "High"
            rank = 0
        elif "Review" in states:
            guardrail_state = "Needs Review"
            severity = "Medium"
            rank = 2
        elif "Unknown" in states:
            guardrail_state = "Data Missing"
            severity = "Medium"
            rank = 4
        else:
            guardrail_state = "Ready"
            severity = "Low"
            rank = 8

        deduction = (
            monitor_deduction
            + suspend_deduction
            + timeout_deduction
            + route_deduction
            + capacity_deduction
            + cost_deduction
        )
        score = max(0, 100 - deduction)
        next_actions = [
            action
            for state, action in [
                (monitor_state, monitor_action),
                (suspend_state, suspend_action),
                (timeout_state, timeout_action),
                (route_state, route_action),
                (capacity_state, capacity_action),
                (cost_state, cost_action),
            ]
            if state in {"Blocked", "Review", "Unknown"}
        ]
        evidence_parts = [
            f"resource_monitor={monitor_value if monitor_known else 'on demand'}",
            f"auto_suspend={suspend_value if suspend_known else 'on demand'}",
            f"statement_timeout={statement_timeout_value if statement_timeout_known else 'on demand'}",
            f"queued_timeout={queued_timeout_value if queued_timeout_known else 'on demand'}",
            f"route={control_state or 'DBA on-call'}",
            f"queued={queued:.2f}s",
            f"spill={spill:.2f} GB",
            f"p95={p95:.2f}s",
            f"credits={metered:.2f}",
            f"credit_delta={credit_delta:.2f}",
        ]

        rows.append({
            "WAREHOUSE_NAME": wh_name,
            "GUARDRAIL_STATE": guardrail_state,
            "GUARDRAIL_SCORE": score,
            "SEVERITY": severity,
            "RESOURCE_MONITOR_STATE": monitor_state,
            "RESOURCE_MONITOR": str(monitor_value or "") if monitor_known else "",
            "AUTO_SUSPEND_STATE": suspend_state,
            "AUTO_SUSPEND_SEC": auto_suspend if suspend_known else None,
            "TIMEOUT_STATE": timeout_state,
            "STATEMENT_TIMEOUT_SEC": statement_timeout,
            "QUEUED_TIMEOUT_SEC": queued_timeout,
            "ESCALATION_ROUTE_STATE": route_state,
            "CAPACITY_STATE": capacity_state,
            "COST_STATE": cost_state,
            "METERED_CREDITS": metered,
            "CREDIT_DELTA": credit_delta,
            "CREDIT_DELTA_PCT": credit_delta_pct,
            "AVG_QUEUED_SEC": queued,
            "TOTAL_REMOTE_SPILL_GB": spill,
            "P95_ELAPSED_SEC": p95,
            "PROOF_REQUIRED": "SHOW WAREHOUSES metadata, timeout settings, resource monitor assignment, metering, queue, spill, p95, and escalation route",
            "EVIDENCE": "; ".join(evidence_parts),
            "NEXT_ACTION": next_actions[0] if next_actions else "Guardrail coverage is ready for this warehouse.",
            "GUARDRAIL_RANK": rank,
        })

    board = pd.DataFrame(rows).sort_values(
        ["GUARDRAIL_RANK", "GUARDRAIL_SCORE", "METERED_CREDITS", "WAREHOUSE_NAME"],
        ascending=[True, True, False, True],
    ).reset_index(drop=True)
    summary = {
        "warehouses": int(len(board)),
        "blocked": int(board["GUARDRAIL_STATE"].eq("Blocked").sum()),
        "review": int(board["GUARDRAIL_STATE"].eq("Needs Review").sum()),
        "unknown": int(board["GUARDRAIL_STATE"].eq("Data Missing").sum()),
        "ready": int(board["GUARDRAIL_STATE"].eq("Ready").sum()),
        "score": int(round(float(pd.to_numeric(board["GUARDRAIL_SCORE"], errors="coerce").fillna(0).mean()))),
    }
    return summary, board


def _warehouse_setting_action_plan(guardrail_board: pd.DataFrame | None) -> pd.DataFrame:
    """Return advisory setting moves from loaded guardrail coverage."""
    columns = [
        "PRIORITY", "WAREHOUSE_NAME", "ACTION_TYPE", "CURRENT_STATE", "CURRENT_SETTING",
        "SAFE_SETTING_MOVE", "WHY", "PROOF_REQUIRED", "ROLLBACK_CHECK", "REVIEW_SQL",
    ]
    if guardrail_board is None or getattr(guardrail_board, "empty", True):
        return pd.DataFrame(columns=columns)
    view = guardrail_board.copy()
    rows: list[dict[str, object]] = []

    def add_row(
        source: pd.Series,
        *,
        action_type: str,
        state_col: str,
        current_setting: str,
        safe_move: str,
        why: str,
        rollback_check: str,
    ) -> None:
        state = str(source.get(state_col) or "Unknown")
        if state not in {"Blocked", "Review", "Unknown"} and state != "Data Missing":
            return
        priority = "High" if state == "Blocked" else "Medium" if state in {"Review", "Unknown", "Data Missing"} else "Low"
        rows.append({
            "PRIORITY": priority,
            "WAREHOUSE_NAME": source.get("WAREHOUSE_NAME", "Unknown warehouse"),
            "ACTION_TYPE": action_type,
            "CURRENT_STATE": state,
            "CURRENT_SETTING": current_setting,
            "SAFE_SETTING_MOVE": safe_move,
            "WHY": why,
            "PROOF_REQUIRED": source.get("PROOF_REQUIRED", ""),
            "ROLLBACK_CHECK": rollback_check,
            "REVIEW_SQL": _warehouse_setting_review_sql(source.get("WAREHOUSE_NAME", ""), action_type),
            "_SORT": {"High": 0, "Medium": 1, "Low": 2}.get(priority, 9),
            "_SCORE": safe_float(source.get("GUARDRAIL_SCORE")),
            "_CREDITS": safe_float(source.get("METERED_CREDITS")),
        })

    for _, row in view.iterrows():
        wh = str(row.get("WAREHOUSE_NAME") or "Unknown warehouse")
        add_row(
            row,
            action_type="Resource monitor coverage",
            state_col="RESOURCE_MONITOR_STATE",
            current_setting=str(row.get("RESOURCE_MONITOR") or "not loaded / not set"),
            safe_move="Assign or confirm a resource monitor before treating the warehouse as guarded.",
            why=f"{wh} cannot be considered cost-guarded without monitor coverage for active or rising usage.",
            rollback_check="Confirm monitor assignment in SHOW WAREHOUSES and verify no unexpected suspension events.",
        )
        add_row(
            row,
            action_type="Auto-suspend review",
            state_col="AUTO_SUSPEND_STATE",
            current_setting=str(row.get("AUTO_SUSPEND_SEC") if row.get("AUTO_SUSPEND_SEC") is not None else "not loaded"),
            safe_move="Review idle burn and workload latency, then test one conservative AUTO_SUSPEND change.",
            why=f"{wh} has auto-suspend coverage that needs DBA review before cost tuning.",
            rollback_check="Compare idle credits, p95 runtime, queue seconds, and failed queries after the next complete window.",
        )
        add_row(
            row,
            action_type="Timeout guardrail review",
            state_col="TIMEOUT_STATE",
            current_setting=(
                f"statement={row.get('STATEMENT_TIMEOUT_SEC') if row.get('STATEMENT_TIMEOUT_SEC') is not None else 'not loaded'}, "
                f"queued={row.get('QUEUED_TIMEOUT_SEC') if row.get('QUEUED_TIMEOUT_SEC') is not None else 'not loaded'}"
            ),
            safe_move="Set or confirm statement and queued timeout guardrails before workload growth.",
            why=f"{wh} needs timeout context so capacity changes do not mask runaway or queued workloads.",
            rollback_check="Verify queue failures, p95 runtime, and timeout errors stay inside the expected range.",
        )
        add_row(
            row,
            action_type="Capacity change review",
            state_col="CAPACITY_STATE",
            current_setting=(
                f"queue={safe_float(row.get('AVG_QUEUED_SEC')):,.1f}s, "
                f"spill={safe_float(row.get('TOTAL_REMOTE_SPILL_GB')):,.1f} GB, "
                f"p95={safe_float(row.get('P95_ELAPSED_SEC')):,.1f}s"
            ),
            safe_move="Inspect top query profiles before resizing, changing clusters, or enabling acceleration.",
            why=f"{wh} has loaded queue, spill, or latency pressure that may be query shape rather than warehouse size.",
            rollback_check="After any setting change, confirm credits, queue, remote spill, p95, and failures in the same workload window.",
        )
        add_row(
            row,
            action_type="Cost movement review",
            state_col="COST_STATE",
            current_setting=(
                f"credits={safe_float(row.get('METERED_CREDITS')):,.1f}, "
                f"delta={safe_float(row.get('CREDIT_DELTA')):+,.1f}"
            ),
            safe_move="Explain credit movement before changing suspend, size, or routing policy.",
            why=f"{wh} has material spend movement that should be separated from performance pressure.",
            rollback_check="Confirm the next completed window shows lower burn without higher queue, spill, or failure rates.",
        )

    if not rows:
        return pd.DataFrame(columns=columns)
    plan = pd.DataFrame(rows).sort_values(
        ["_SORT", "_SCORE", "_CREDITS", "WAREHOUSE_NAME", "ACTION_TYPE"],
        ascending=[True, True, False, True, True],
    )
    return plan[columns].reset_index(drop=True)


def _warehouse_setting_route(action_type: str) -> str:
    action = str(action_type or "").lower()
    if "capacity" in action or "cost movement" in action:
        return "Efficiency"
    if "timeout" in action or "auto-suspend" in action or "resource monitor" in action:
        return "Optimization Advisor"
    return "Overview & Scaling"


def _warehouse_setting_detail_options(plan: pd.DataFrame | None) -> pd.DataFrame:
    if plan is None or getattr(plan, "empty", True):
        return pd.DataFrame()
    view = plan.copy().reset_index(drop=True)
    view["DETAIL_LABEL"] = view.apply(
        lambda row: (
            f"{row.get('PRIORITY', 'Review')} | "
            f"{row.get('ACTION_TYPE', 'Setting review')} | "
            f"{row.get('WAREHOUSE_NAME', 'Unknown warehouse')}"
        ),
        axis=1,
    )
    view["WORKFLOW_ROUTE"] = view["ACTION_TYPE"].apply(_warehouse_setting_route)
    return view


def _render_warehouse_setting_action_detail(plan: pd.DataFrame | None) -> None:
    options = _warehouse_setting_detail_options(plan)
    if options.empty:
        return
    st.markdown("**Open Warehouse Setting Action**")
    selected_label = st.selectbox(
        "Warehouse setting action",
        options["DETAIL_LABEL"].tolist(),
        key="warehouse_setting_action_select",
    )
    selected = options[options["DETAIL_LABEL"].eq(selected_label)]
    if selected.empty:
        return
    row = selected.iloc[0]
    render_shell_snapshot((
        ("Priority", str(row.get("PRIORITY") or "Review")),
        ("Warehouse", str(row.get("WAREHOUSE_NAME") or "Unknown")),
        ("State", str(row.get("CURRENT_STATE") or "Review")),
        ("Route", str(row.get("WORKFLOW_ROUTE") or "Overview & Scaling")),
    ))
    st.caption(str(row.get("WHY") or "Review the loaded warehouse telemetry before changing settings."))
    render_escaped_labeled_text(
        "Safe move",
        row.get("SAFE_SETTING_MOVE") or "Review telemetry before changing this warehouse.",
    )
    render_escaped_labeled_text(
        "Rollback check",
        row.get("ROLLBACK_CHECK") or "Compare credits, runtime, queue, spill, and failures after the change.",
    )
    review_sql = str(row.get("REVIEW_SQL") or "").strip()
    if review_sql:
        st.code(review_sql, language="sql")
    proof = str(row.get("PROOF_REQUIRED") or "").strip()
    if proof:
        st.caption(f"Proof: {proof}")
    route = str(row.get("WORKFLOW_ROUTE") or "").strip()
    if route in WAREHOUSE_HEALTH_VIEWS and st.button(f"Open {route}", key="warehouse_setting_action_route", width="stretch"):
        st.session_state["warehouse_health_view"] = route
        st.rerun()


def _render_warehouse_cost_control_posture(
    settings_inventory: pd.DataFrame | None,
    overview: pd.DataFrame | None = None,
) -> None:
    summary, posture = _build_warehouse_cost_control_posture(settings_inventory, overview)
    st.subheader("Warehouse Cost-Control Posture")
    if posture.empty:
        st.info("Load warehouse metadata to review AUTO_SUSPEND and AUTO_RESUME posture.")
        return

    render_shell_snapshot((
        ("Warehouses", f"{summary['warehouses']:,}"),
        ("Blocked", f"{summary['blocked']:,}"),
        ("Needs Review", f"{summary['review']:,}"),
        ("OVERWATCH candidates", f"{summary['overwatch_candidates']:,}"),
    ))
    render_priority_dataframe(
        posture,
        title="Suspend and resume posture",
        priority_columns=[
            "WAREHOUSE_NAME", "COST_CONTROL_STATE", "IDLE_RISK", "AUTO_SUSPEND_SEC",
            "AUTO_RESUME", "WAREHOUSE_SIZE", "STATE", "METERED_CREDITS",
            "RECOMMENDED_AUTO_SUSPEND_SEC", "RECOMMENDED_ACTION",
        ],
        sort_by=["POSTURE_RANK", "METERED_CREDITS", "WAREHOUSE_NAME"],
        ascending=[True, False, True],
        raw_label="All warehouse cost-control rows",
        height=320,
        max_rows=12,
    )
    download_csv(posture, "warehouse_cost_control_posture.csv")

    options = posture["WAREHOUSE_NAME"].astype(str).tolist()
    if options:
        selected_wh = st.selectbox(
            "Warehouse review SQL",
            options,
            key="warehouse_cost_control_sql_select",
        )
        selected = posture[posture["WAREHOUSE_NAME"].astype(str).eq(selected_wh)]
        if not selected.empty:
            st.code(str(selected.iloc[0].get("REVIEW_SQL") or ""), language="sql")

    with st.expander("Future dedicated OVERWATCH warehouse", expanded=False):
        st.code(_overwatch_dedicated_warehouse_setup_sql(), language="sql")


def _warehouse_capacity_review_sql(row: pd.Series) -> str:
    candidate = row.get("SETTING_CHANGE_CANDIDATE") or _warehouse_setting_candidate_for(row)["SETTING_CHANGE_CANDIDATE"]
    safe_path = row.get("SAFE_CHANGE_PATH") or _warehouse_setting_candidate_for(row)["SAFE_CHANGE_PATH"]
    verification = row.get("POST_CHANGE_VERIFICATION") or _warehouse_setting_candidate_for(row)["POST_CHANGE_VERIFICATION"]
    return "\n".join([
        "-- Reviewed warehouse setting plan required.",
        "-- Do not execute a warehouse change from this advisory row.",
        f"-- Candidate: {candidate}",
        f"-- Safe path: {safe_path}",
        "-- Route through the guarded warehouse settings workflow for changed-only SQL, review, and rollback.",
        f"-- Closure telemetry: {verification}",
    ])


def _warehouse_setting_review_insert_sql(
    findings: pd.DataFrame,
    *,
    company: str,
    environment: str,
    source: str = "",
    snapshot_id: str = "",
) -> str:
    if findings is None or findings.empty:
        raise ValueError("Warehouse setting review snapshot has no rows to save.")
    view = _annotate_warehouse_admin_readiness(findings)
    fqn = warehouse_setting_review_fqn()
    env_value = str(environment or "").strip() or "ALL"
    snap = snapshot_id or make_action_id(
        "Warehouse Setting Review Snapshot",
        company,
        f"{env_value}|{datetime.now().strftime('%Y%m%d%H%M%S')}",
    )
    selects = []
    for _, row in view.head(200).iterrows():
        wh = str(row.get("WAREHOUSE_NAME") or "")
        verification_sql = _warehouse_capacity_verification_sql(
            wh,
            days=7,
            environment=environment,
            company=company,
        )
        review_sql = _warehouse_capacity_review_sql(row)
        approval_required = str(row.get("APPROVAL_REQUIRED", "Yes")).upper() == "YES"
        approval_state = str(row.get("APPROVAL_STATE") or ("Requested" if approval_required else "Not Required"))
        audit_fields = _warehouse_setting_audit_readiness_for_row({
            **row.to_dict(),
            "APPROVAL_STATE": approval_state,
            "CHANGE_TICKET_ID": row.get("CHANGE_TICKET_ID", ""),
            "CURRENT_SETTINGS_JSON": row.get("CURRENT_SETTINGS_JSON", ""),
            "PROPOSED_SETTINGS_JSON": row.get("PROPOSED_SETTINGS_JSON", row.get("SETTING_CHANGE_CANDIDATE", "")),
            "ROLLBACK_SQL": row.get("ROLLBACK_SQL", ""),
            "EXECUTED_SQL_HASH": row.get("EXECUTED_SQL_HASH", ""),
            "EXECUTION_STATUS": row.get("EXECUTION_STATUS", "Not Executed"),
            "POST_CHANGE_VERIFICATION_STATUS": row.get("POST_CHANGE_VERIFICATION_STATUS", "Pending"),
            "POST_CHANGE_VERIFICATION_RESULT": row.get("POST_CHANGE_VERIFICATION_RESULT", ""),
            "VERIFIED_MONTHLY_SAVINGS": row.get("VERIFIED_MONTHLY_SAVINGS", 0),
        })
        selects.append(
            "SELECT "
            f"{sql_literal(snap, 64)} AS SNAPSHOT_ID, "
            "CURRENT_TIMESTAMP() AS SNAPSHOT_TS, "
            f"{sql_literal(company, 100)} AS COMPANY, "
            f"{sql_literal(env_value, 100)} AS ENVIRONMENT, "
            f"{sql_literal(wh, 300)} AS WAREHOUSE_NAME, "
            f"{sql_literal(row.get('SEVERITY', ''), 40)} AS SEVERITY, "
            f"{sql_literal(row.get('SIGNAL', ''), 120)} AS SIGNAL, "
            f"{sql_literal(row.get('OWNER', ''), 200)} AS OWNER, "
            f"{sql_literal(row.get('ESCALATION_TARGET', ''), 200)} AS ESCALATION_TARGET, "
            f"{sql_literal(row.get('OWNER_SOURCE', ''), 200)} AS OWNER_SOURCE, "
            f"{sql_literal(row.get('APPROVER', ''), 200)} AS APPROVER, "
            f"{sql_literal(row.get('APPROVAL_REQUIRED', ''), 20)} AS APPROVAL_REQUIRED, "
            f"{sql_literal(row.get('ROLLBACK_REQUIRED', ''), 20)} AS ROLLBACK_REQUIRED, "
            f"{sql_literal(row.get('SAFE_CHANGE_PATH', ''), 4000)} AS SAFE_CHANGE_PATH, "
            f"{sql_literal(row.get('SETTING_CHANGE_CANDIDATE', ''), 4000)} AS SETTING_CHANGE_CANDIDATE, "
            f"{sql_literal(row.get('CHANGE_RISK', ''), 2000)} AS CHANGE_RISK, "
            f"{sql_literal(row.get('POST_CHANGE_VERIFICATION', ''), 2000)} AS POST_CHANGE_VERIFICATION, "
            f"{sql_literal(row.get('PRESSURE_EVIDENCE', ''), 2000)} AS PRESSURE_EVIDENCE, "
            f"{safe_float(row.get('CAPACITY_SCORE'))}::FLOAT AS BASELINE_CAPACITY_SCORE, "
            f"{safe_int(row.get('QUEUED_QUERIES'))}::NUMBER AS BASELINE_QUEUED_QUERIES, "
            f"{safe_int(row.get('SPILL_QUERIES'))}::NUMBER AS BASELINE_SPILL_QUERIES, "
            f"{safe_int(row.get('HIGH_LATENCY_QUERIES'))}::NUMBER AS BASELINE_HIGH_LATENCY_QUERIES, "
            f"{safe_float(row.get('P95_ELAPSED_SEC'))}::FLOAT AS BASELINE_P95_ELAPSED_SEC, "
            f"{safe_float(row.get('METERED_CREDITS'))}::FLOAT AS BASELINE_METERED_CREDITS, "
            f"{sql_literal(verification_sql, 8000)} AS VERIFICATION_QUERY, "
            f"{sql_literal(review_sql, 8000)} AS GENERATED_REVIEW_SQL, "
            f"{sql_literal(row.get('IMPACT_TELEMETRY_REQUIRED', ''), 20)} AS IMPACT_TELEMETRY_REQUIRED, "
            f"{sql_literal(approval_state, 80)} AS APPROVAL_STATE, "
            f"{sql_literal(row.get('CHANGE_TICKET_ID', ''), 200)} AS CHANGE_TICKET_ID, "
            f"{sql_literal(row.get('CURRENT_SETTINGS_JSON', ''), 8000)} AS CURRENT_SETTINGS_JSON, "
            f"{sql_literal(row.get('PROPOSED_SETTINGS_JSON', row.get('SETTING_CHANGE_CANDIDATE', '')), 8000)} AS PROPOSED_SETTINGS_JSON, "
            f"{sql_literal(row.get('ROLLBACK_SQL', ''), 8000)} AS ROLLBACK_SQL, "
            f"{sql_literal(row.get('EXECUTED_SQL_HASH', ''), 80)} AS EXECUTED_SQL_HASH, "
            f"{sql_literal(row.get('EXECUTION_STATUS', 'Not Executed'), 80)} AS EXECUTION_STATUS, "
            f"{sql_literal(row.get('EXECUTED_BY', ''), 200)} AS EXECUTED_BY, "
            "NULL::TIMESTAMP_NTZ AS EXECUTED_AT, "
            f"{sql_literal(row.get('POST_CHANGE_VERIFICATION_STATUS', 'Pending'), 80)} AS POST_CHANGE_VERIFICATION_STATUS, "
            f"{sql_literal(row.get('POST_CHANGE_VERIFICATION_RESULT', ''), 4000)} AS POST_CHANGE_VERIFICATION_RESULT, "
            f"{safe_float(row.get('VERIFIED_MONTHLY_SAVINGS'))}::FLOAT AS VERIFIED_MONTHLY_SAVINGS, "
            f"{sql_literal(audit_fields.get('AUDIT_READINESS', ''), 100)} AS AUDIT_READINESS, "
            f"{sql_literal(audit_fields.get('AUDIT_BLOCKERS', ''), 2000)} AS AUDIT_BLOCKERS, "
            f"{sql_literal(audit_fields.get('NEXT_CONTROL_ACTION', ''), 4000)} AS NEXT_CONTROL_ACTION, "
            f"{sql_literal(source, 500)} AS SOURCE"
        )
    return f"""
INSERT INTO {fqn} (
    SNAPSHOT_ID, SNAPSHOT_TS, COMPANY, ENVIRONMENT, WAREHOUSE_NAME, SEVERITY,
    SIGNAL, OWNER, ESCALATION_TARGET, OWNER_SOURCE, APPROVER, APPROVAL_REQUIRED,
    ROLLBACK_REQUIRED, SAFE_CHANGE_PATH, SETTING_CHANGE_CANDIDATE, CHANGE_RISK,
    POST_CHANGE_VERIFICATION, PRESSURE_EVIDENCE, BASELINE_CAPACITY_SCORE,
    BASELINE_QUEUED_QUERIES, BASELINE_SPILL_QUERIES, BASELINE_HIGH_LATENCY_QUERIES,
    BASELINE_P95_ELAPSED_SEC, BASELINE_METERED_CREDITS, VERIFICATION_QUERY,
    GENERATED_REVIEW_SQL, IMPACT_TELEMETRY_REQUIRED, APPROVAL_STATE,
    CHANGE_TICKET_ID, CURRENT_SETTINGS_JSON, PROPOSED_SETTINGS_JSON, ROLLBACK_SQL,
    EXECUTED_SQL_HASH, EXECUTION_STATUS, EXECUTED_BY, EXECUTED_AT,
    POST_CHANGE_VERIFICATION_STATUS, POST_CHANGE_VERIFICATION_RESULT,
    VERIFIED_MONTHLY_SAVINGS, AUDIT_READINESS, AUDIT_BLOCKERS, NEXT_CONTROL_ACTION,
    SOURCE
)
{" UNION ALL ".join(selects)}""".strip()


def _save_warehouse_setting_review_snapshot(
    session,
    findings: pd.DataFrame,
    *,
    company: str,
    environment: str,
    source: str = "",
) -> None:
    try:
        session.sql(build_warehouse_setting_review_ddl()).collect()
        for migration_sql in build_warehouse_setting_review_migration_sql():
            session.sql(migration_sql).collect()
        session.sql(_warehouse_setting_review_insert_sql(
            findings,
            company=company,
            environment=environment,
            source=source,
        )).collect()
        st.success("Saved the Warehouse Setting Review snapshot for review and telemetry tracking.")
    except Exception as exc:
        st.error(f"Could not save Warehouse Setting Review snapshot: {format_snowflake_error(exc)}")
        st.info("Warehouse setting review history is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")


def _warehouse_capacity_priority_view(exceptions: pd.DataFrame) -> pd.DataFrame:
    if exceptions is None or exceptions.empty:
        return pd.DataFrame()
    rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    view = _annotate_warehouse_admin_readiness(exceptions)
    view["_RANK"] = view.get("SEVERITY", pd.Series(dtype=str)).map(rank).fillna(4)
    view["NEXT_ACTION"] = view.get("SIGNAL", pd.Series(dtype=str)).apply(lambda value: _warehouse_capacity_action_for(value)[0])
    view["NEXT_WORKFLOW"] = view.get("SIGNAL", pd.Series(dtype=str)).apply(_warehouse_capacity_workflow_for)
    return view.sort_values(["_RANK", "CAPACITY_SCORE", "METERED_CREDITS"], ascending=[True, True, False]).drop(columns=["_RANK"], errors="ignore")


def _warehouse_intervention_matrix(
    exceptions: pd.DataFrame,
    control_board: pd.DataFrame | None = None,
    closure: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Rank warehouses by whether DBAs can safely intervene now or need telemetry first."""
    priority = _warehouse_capacity_priority_view(exceptions)
    if priority.empty:
        return pd.DataFrame()

    control = control_board if isinstance(control_board, pd.DataFrame) else pd.DataFrame()
    closure_df = closure if isinstance(closure, pd.DataFrame) else pd.DataFrame()
    control_by_wh = {
        str(row.get("WAREHOUSE_NAME") or "").upper(): row
        for _, row in control.iterrows()
    } if not control.empty else {}
    closure_by_wh = {
        str(row.get("WAREHOUSE_NAME") or "").upper(): row
        for _, row in closure_df.iterrows()
    } if not closure_df.empty else {}

    rows: list[dict] = []
    for _, item in priority.head(25).iterrows():
        wh = str(item.get("WAREHOUSE_NAME") or "Unknown warehouse")
        control_row = control_by_wh.get(wh.upper(), {})
        closure_row = closure_by_wh.get(wh.upper(), {})
        signal = str(item.get("SIGNAL") or "")
        severity = str(item.get("SEVERITY") or "Medium")
        score = safe_float(item.get("CAPACITY_SCORE"))
        credits = safe_float(item.get("METERED_CREDITS"))
        queued = safe_int(item.get("QUEUED_QUERIES"))
        spill = safe_int(item.get("SPILL_QUERIES"))
        high_latency = safe_int(item.get("HIGH_LATENCY_QUERIES"))
        readiness = str(control_row.get("CONTROL_STATE") or item.get("ADMIN_READINESS") or "Review")
        blockers = str(control_row.get("AUDIT_BLOCKERS") or item.get("ADMIN_BLOCKERS") or "")
        closure_state = str(closure_row.get("CLOSURE_READINESS") or control_row.get("CLOSURE_READINESS") or "No recent action")
        savings_required = str(
            control_row.get("IMPACT_TELEMETRY_REQUIRED")
            or item.get("IMPACT_TELEMETRY_REQUIRED")
            or ""
        ).upper() == "YES"
        approval_required = str(
            control_row.get("APPROVAL_REQUIRED")
            or item.get("APPROVAL_REQUIRED")
            or ""
        ).upper() == "YES"
        audit_bad = any(token in readiness.upper() for token in ("BLOCK", "FAILED", "PENDING", "NO SETTING"))
        closure_bad = any(token in closure_state.upper() for token in ("OVERDUE", "WITHOUT VERIFICATION", "GAP"))

        if audit_bad or closure_bad or approval_required:
            state = "Telemetry Blocked"
            rank = 0
            decision = "Hold setting change until review, audit, rollback, and closure status are current."
        elif score < 65 or severity.upper() == "CRITICAL":
            state = "Intervene"
            rank = 1
            decision = "Run DBA setting review and monitor queue, spill, latency, and credit impact after the change."
        elif savings_required or credits > 0:
            state = "Cost Review"
            rank = 2
            decision = "Quantify credit delta and savings hypothesis before claiming optimization value."
        else:
            state = "Watch"
            rank = 4
            decision = "Monitor pressure; avoid touching settings without a stronger service or cost signal."

        rows.append({
            "DBA_PRIORITY": f"P{rank}",
            "INTERVENTION_STATE": state,
            "WAREHOUSE_NAME": wh,
            "SEVERITY": severity,
            "SIGNAL": signal,
            "CAPACITY_SCORE": score,
            "METERED_CREDITS": credits,
            "PRESSURE_EVIDENCE": f"queued={queued:,}; spill={spill:,}; p95/latency rows={high_latency:,}",
            "CONTROL_STATE": readiness,
            "CLOSURE_READINESS": closure_state,
            "NEXT_DECISION": decision,
            "PROOF_REQUIRED": "review status, rollback SQL, execution audit, post-change service/cost telemetry",
            "NEXT_WORKFLOW": str(item.get("NEXT_WORKFLOW") or _warehouse_capacity_workflow_for(signal)),
            "_RANK": rank,
        })

    return pd.DataFrame(rows).sort_values(
        ["_RANK", "CAPACITY_SCORE", "METERED_CREDITS"],
        ascending=[True, True, False],
    ).drop(columns=["_RANK"], errors="ignore").reset_index(drop=True)


def _render_warehouse_watch_floor(score: int, exceptions: pd.DataFrame, summary_row: dict) -> None:
    priority = _warehouse_capacity_priority_view(exceptions).head(3)
    high_risk = 0
    if exceptions is not None and not exceptions.empty and "SEVERITY" in exceptions.columns:
        high_risk = int(exceptions["SEVERITY"].isin(["Critical", "High"]).sum())

    render_shell_snapshot((
        ("High-Risk Warehouses", f"{high_risk:,}"),
        ("Remote Spill", f"{safe_float(summary_row.get('REMOTE_SPILL_GB')):,.1f} GB"),
        ("Queued Queries", f"{safe_int(summary_row.get('QUEUED_QUERIES')):,}"),
    ))
    if priority.empty:
        st.success("No urgent warehouse capacity exceptions crossed the selected thresholds.")
    else:
        first = priority.iloc[0]
        st.warning(
            f"First move: {first.get('SIGNAL', 'Warehouse pressure')} on "
            f"{first.get('WAREHOUSE_NAME', 'unknown warehouse')} -> {first.get('NEXT_ACTION', 'Review warehouse pressure.')}"
        )

    st.markdown("**Warehouse Watch Floor**")
    if priority.empty:
        defer_source_note("Use Overview & Scaling for periodic checks, or Efficiency after a cost spike.")
        return

    cols = st.columns(len(priority))
    for idx, (_, item) in enumerate(priority.iterrows()):
        workflow = str(item.get("NEXT_WORKFLOW") or "Overview & Scaling")
        with cols[idx]:
            render_escaped_bold_text(f"{item.get('SEVERITY', 'Medium')}: {item.get('SIGNAL', '')}")
            st.caption(
                f"{item.get('WAREHOUSE_NAME', 'unknown warehouse')} | "
                f"Queued {safe_int(item.get('QUEUED_QUERIES')):,} | "
                f"Spill {safe_int(item.get('SPILL_QUERIES')):,} | "
                f"{format_credits(safe_float(item.get('METERED_CREDITS')))}"
            )
            next_action = str(item.get("NEXT_ACTION", "") or "")
            if st.button(
                f"Open {workflow}",
                key=f"wh_watch_floor_{idx}_{workflow}",
                help=next_action or None,
                width="stretch",
            ):
                warehouse = str(item.get("WAREHOUSE_NAME") or "")
                if warehouse:
                    st.session_state["global_warehouse"] = warehouse
                    st.session_state["wh_filter"] = warehouse
                    st.session_state["lm_wh"] = warehouse
                    for stale_key in ["wh_df_wh", "wh_efficiency", "wh_df_sp", "wh_df_hm"]:
                        st.session_state.pop(stale_key, None)
                _queue_warehouse_health_view(workflow)


def _build_warehouse_capacity_markdown(
    company: str,
    days: int,
    score: int,
    summary_row: dict,
    exceptions: pd.DataFrame,
) -> str:
    exceptions_view = _annotate_warehouse_admin_readiness(exceptions)
    lines = [
        f"# OVERWATCH Warehouse Capacity Brief - {company}",
        "",
        f"- Lookback: {days} days",
        f"- Warehouses active: {safe_int(summary_row.get('WAREHOUSES_ACTIVE')):,}",
        f"- Queries: {safe_int(summary_row.get('TOTAL_QUERIES')):,}",
        f"- Queued queries: {safe_int(summary_row.get('QUEUED_QUERIES')):,}",
        f"- Spill queries: {safe_int(summary_row.get('SPILL_QUERIES')):,}",
        f"- Credit movement: {safe_float(summary_row.get('CREDIT_SPIKE_PCT')):,.1f}%",
        "",
        "## DBA Narrative",
        (
            "Use this brief to decide whether warehouse pressure is capacity, memory, workload shape, "
            "or cost drift. It is intended to support DBA action and executive reporting without forcing "
            "leadership through raw warehouse telemetry."
        ),
        "",
        "## Top Warehouse Exceptions",
    ]
    if exceptions is None or exceptions.empty:
        lines.append("- No warehouse capacity exceptions found for the selected scope.")
    else:
        for _, row in exceptions_view.head(10).iterrows():
            lines.append(
                "- "
                f"{row.get('SEVERITY', 'Watch')} | {row.get('SIGNAL', 'Unknown')} | "
                f"{row.get('WAREHOUSE_NAME', '')} | "
                f"{safe_float(row.get('METERED_CREDITS')):,.2f} credits | "
                f"{row.get('SETTING_CHANGE_CANDIDATE', 'Review warehouse settings')}"
            )
    lines.extend([
        "",
        "## Settings Change Status",
        (
            "- Warehouse capacity findings are not direct change orders. Route setting changes through "
            "the guarded warehouse settings workflow so current values, review status, rollback SQL, "
            "and post-change telemetry are captured."
        ),
        "",
        "## Telemetry Limits",
        "- ACCOUNT_USAGE can lag; Live Monitor should be used for current in-flight warehouse pressure.",
        "- Per-warehouse pressure is inferred from query history plus metering history, not Snowsight implementation details.",
        "- Company scope follows configured warehouse/database/user naming rules.",
    ])
    return "\n".join(lines)


def _build_warehouse_capacity_sql(session, days: int) -> tuple[str, str]:
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "WAREHOUSE_SIZE",
            "QUEUED_OVERLOAD_TIME",
            "QUEUED_PROVISIONING_TIME",
            "QUEUED_REPAIR_TIME",
            "BYTES_SPILLED_TO_LOCAL_STORAGE",
            "BYTES_SPILLED_TO_REMOTE_STORAGE",
        ],
    ))
    wm_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
        ["CREDITS_USED_COMPUTE", "CREDITS_USED"],
    ))
    warehouse_size_expr = "MAX(q.warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR"
    queue_ms_expr = " + ".join([
        "COALESCE(q.queued_overload_time, 0)" if "QUEUED_OVERLOAD_TIME" in qh_cols else "0",
        "COALESCE(q.queued_provisioning_time, 0)" if "QUEUED_PROVISIONING_TIME" in qh_cols else "0",
        "COALESCE(q.queued_repair_time, 0)" if "QUEUED_REPAIR_TIME" in qh_cols else "0",
    ])
    local_spill_expr = (
        "COALESCE(q.bytes_spilled_to_local_storage, 0)"
        if "BYTES_SPILLED_TO_LOCAL_STORAGE" in qh_cols
        else "0"
    )
    remote_spill_expr = (
        "COALESCE(q.bytes_spilled_to_remote_storage, 0)"
        if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
        else "0"
    )
    spill_bytes_expr = f"{local_spill_expr} + {remote_spill_expr}"
    meter_expr = (
        "COALESCE(m.credits_used_compute, m.credits_used)"
        if {"CREDITS_USED_COMPUTE", "CREDITS_USED"}.issubset(wm_cols)
        else "m.credits_used"
    )
    filters_q = get_global_filter_clause(
        date_col="q.start_time",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
    )
    filters_m = get_wh_filter_clause("m.warehouse_name")
    summary_sql = f"""
        WITH query_rollup AS (
            SELECT
                q.warehouse_name,
                COUNT(*) AS total_queries,
                SUM(IFF(({queue_ms_expr}) > 0, 1, 0)) AS queued_queries,
                SUM(IFF(({spill_bytes_expr}) > 0, 1, 0)) AS spill_queries,
                SUM(IFF(q.total_elapsed_time >= 30000, 1, 0)) AS high_latency_queries,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY q.total_elapsed_time / 1000.0) AS p95_elapsed_sec,
                SUM({remote_spill_expr}) / POWER(1024, 3) AS remote_spill_gb
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {filters_q}
            GROUP BY q.warehouse_name
        ),
        metering AS (
            SELECT
                m.warehouse_name,
                SUM(IFF(m.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP()),
                        {meter_expr}, 0)) AS current_credits,
                SUM(IFF(m.start_time >= DATEADD('day', -{int(days) * 2}, CURRENT_TIMESTAMP())
                         AND m.start_time < DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP()),
                        {meter_expr}, 0)) AS prior_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY m
            WHERE m.start_time >= DATEADD('day', -{int(days) * 2}, CURRENT_TIMESTAMP())
              {filters_m}
            GROUP BY m.warehouse_name
        ),
        combined AS (
            SELECT
                COALESCE(q.warehouse_name, m.warehouse_name) AS warehouse_name,
                COALESCE(q.total_queries, 0) AS total_queries,
                COALESCE(q.queued_queries, 0) AS queued_queries,
                COALESCE(q.spill_queries, 0) AS spill_queries,
                COALESCE(q.high_latency_queries, 0) AS high_latency_queries,
                COALESCE(q.p95_elapsed_sec, 0) AS p95_elapsed_sec,
                COALESCE(q.remote_spill_gb, 0) AS remote_spill_gb,
                COALESCE(m.current_credits, 0) AS current_credits,
                COALESCE(m.prior_credits, 0) AS prior_credits,
                (COALESCE(m.current_credits, 0) - COALESCE(m.prior_credits, 0))
                    / NULLIF(COALESCE(m.prior_credits, 0), 0) * 100 AS credit_spike_pct
            FROM query_rollup q
            FULL OUTER JOIN metering m ON q.warehouse_name = m.warehouse_name
        )
        SELECT
            COUNT(DISTINCT warehouse_name) AS warehouses_active,
            SUM(total_queries) AS total_queries,
            SUM(queued_queries) AS queued_queries,
            SUM(spill_queries) AS spill_queries,
            SUM(high_latency_queries) AS high_latency_queries,
            SUM(current_credits) AS metered_credits,
            SUM(prior_credits) AS prior_credits,
            (SUM(current_credits) - SUM(prior_credits)) / NULLIF(SUM(prior_credits), 0) * 100 AS credit_spike_pct,
            MAX(p95_elapsed_sec) AS worst_p95_elapsed_sec,
            SUM(remote_spill_gb) AS remote_spill_gb
        FROM combined
    """
    exceptions_sql = f"""
        WITH query_rollup AS (
            SELECT
                q.warehouse_name,
                {warehouse_size_expr} AS warehouse_size,
                COUNT(*) AS total_queries,
                SUM(IFF(({queue_ms_expr}) > 0, 1, 0)) AS queued_queries,
                SUM(IFF(({spill_bytes_expr}) > 0, 1, 0)) AS spill_queries,
                SUM(IFF(q.total_elapsed_time >= 30000, 1, 0)) AS high_latency_queries,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY q.total_elapsed_time / 1000.0) AS p95_elapsed_sec,
                SUM({remote_spill_expr}) / POWER(1024, 3) AS remote_spill_gb
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {filters_q}
            GROUP BY q.warehouse_name
        ),
        metering AS (
            SELECT
                m.warehouse_name,
                SUM(IFF(m.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP()),
                        {meter_expr}, 0)) AS current_credits,
                SUM(IFF(m.start_time >= DATEADD('day', -{int(days) * 2}, CURRENT_TIMESTAMP())
                         AND m.start_time < DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP()),
                        {meter_expr}, 0)) AS prior_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY m
            WHERE m.start_time >= DATEADD('day', -{int(days) * 2}, CURRENT_TIMESTAMP())
              {filters_m}
            GROUP BY m.warehouse_name
        ),
        combined AS (
            SELECT
                COALESCE(q.warehouse_name, m.warehouse_name) AS warehouse_name,
                q.warehouse_size,
                COALESCE(q.total_queries, 0) AS total_queries,
                COALESCE(q.queued_queries, 0) AS queued_queries,
                COALESCE(q.spill_queries, 0) AS spill_queries,
                COALESCE(q.high_latency_queries, 0) AS high_latency_queries,
                COALESCE(q.p95_elapsed_sec, 0) AS p95_elapsed_sec,
                COALESCE(q.remote_spill_gb, 0) AS remote_spill_gb,
                COALESCE(m.current_credits, 0) AS current_credits,
                COALESCE(m.prior_credits, 0) AS prior_credits,
                (COALESCE(m.current_credits, 0) - COALESCE(m.prior_credits, 0))
                    / NULLIF(COALESCE(m.prior_credits, 0), 0) * 100 AS credit_spike_pct
            FROM query_rollup q
            FULL OUTER JOIN metering m ON q.warehouse_name = m.warehouse_name
        )
        SELECT
            CASE
                WHEN queued_queries >= 20 OR remote_spill_gb >= 20 THEN 'Critical'
                WHEN credit_spike_pct >= 50 OR spill_queries >= 10 OR high_latency_queries >= 25 THEN 'High'
                ELSE 'Medium'
            END AS severity,
            CASE
                WHEN queued_queries >= 20 THEN 'Queue Pressure'
                WHEN remote_spill_gb >= 1 THEN 'Memory Spill'
                WHEN credit_spike_pct >= 25 THEN 'Credit Spike'
                ELSE 'Latency Pressure'
            END AS signal,
            warehouse_name,
            warehouse_size,
            total_queries,
            queued_queries,
            spill_queries,
            high_latency_queries,
            ROUND(p95_elapsed_sec, 2) AS p95_elapsed_sec,
            ROUND(remote_spill_gb, 2) AS remote_spill_gb,
            ROUND(current_credits, 4) AS metered_credits,
            ROUND(prior_credits, 4) AS prior_credits,
            ROUND(COALESCE(credit_spike_pct, 0), 1) AS credit_spike_pct,
            ROUND(100
                - LEAST(queued_queries * 100.0 / NULLIF(total_queries, 0) * 2.0, 28)
                - LEAST(spill_queries * 100.0 / NULLIF(total_queries, 0) * 1.8, 24)
                - LEAST(high_latency_queries * 100.0 / NULLIF(total_queries, 0) * 1.1, 18)
                - LEAST(GREATEST(COALESCE(credit_spike_pct, 0), 0) / 4, 20), 1) AS capacity_score
        FROM combined
        WHERE queued_queries > 0
           OR spill_queries > 0
           OR high_latency_queries > 0
           OR credit_spike_pct >= 25
        ORDER BY
            CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 ELSE 3 END,
            capacity_score ASC,
            metered_credits DESC
        LIMIT 100
    """
    return summary_sql, exceptions_sql


def _queue_capacity_findings(session, exceptions: pd.DataFrame) -> int:
    if exceptions is None or exceptions.empty:
        return 0
    company = get_active_company()
    environment = get_active_environment()
    exceptions = _annotate_warehouse_admin_readiness(exceptions)
    actions = []
    for _, row in exceptions.head(50).iterrows():
        wh = str(row.get("WAREHOUSE_NAME", ""))
        signal = str(row.get("SIGNAL", "Warehouse Pressure"))
        action_text, _ = _warehouse_capacity_action_for(signal)
        verification_sql = _warehouse_capacity_verification_sql(
            wh,
            days=7,
            environment=environment,
            company=company,
        )
        finding = (
            f"{signal} on {wh}: "
            f"queued={safe_int(row.get('QUEUED_QUERIES')):,}, spill={safe_int(row.get('SPILL_QUERIES')):,}, "
            f"credits={safe_float(row.get('METERED_CREDITS')):,.2f}; "
            f"{row.get('PRESSURE_EVIDENCE', '')}."
        )
        actions.append({
            "Action ID": make_action_id("Warehouse Capacity", wh, finding),
            "Source": "Warehouse Health - Capacity Brief",
            "Category": "Warehouse Capacity",
            "Severity": row.get("SEVERITY", "High"),
            "Entity Type": "Warehouse",
            "Entity": wh,
            "Route": _route_label(row.get("OWNER", "Platform DBA")),
            "Route Email": row.get("OWNER_EMAIL", ""),
            "Oncall Primary": row.get("ONCALL_PRIMARY", ""),
            "Oncall Secondary": row.get("ONCALL_SECONDARY", ""),
            "Escalation": _route_label(row.get("APPROVAL_GROUP", row.get("APPROVER", "Warehouse Route / DBA Lead"))),
            "Escalation Target": row.get("ESCALATION_TARGET", "DBA Lead"),
            "Route Basis": _route_label(row.get("OWNER_SOURCE", "")),
            "Route Detail": _route_label(row.get("OWNER_EVIDENCE", "")),
            "Finding": finding,
            "Action": (
                f"{action_text} {row.get('SAFE_CHANGE_PATH', '')} "
                f"Review from {_route_label(row.get('APPROVER', 'Warehouse DBA Lead'))} is required. "
                "Actual warehouse changes must be generated from the Warehouse Settings Manager."
            ),
            "Estimated Monthly Savings": 0,
            "Generated SQL Fix": _warehouse_capacity_review_sql(row),
            "Telemetry Query": verification_sql,
            "Reviewer": _route_label(row.get("APPROVER", "Warehouse Route / DBA Lead")),
            "Telemetry Status": "Requested",
            "Status Note": (
                f"{row.get('CHANGE_RISK', '')} "
                f"Escalation: {row.get('ESCALATION_TARGET', 'DBA Lead')}. "
                f"Rollback required: {row.get('ROLLBACK_REQUIRED', 'Yes')}; "
                f"impact telemetry required: {row.get('IMPACT_TELEMETRY_REQUIRED', 'No')}."
            ),
            "Recovery Status": (
                f"Baseline: {row.get('PRESSURE_EVIDENCE', '')}. "
                f"Closure uses post-change telemetry: {row.get('POST_CHANGE_VERIFICATION', '')}"
            ),
            "Recovery Audit State": "Warehouse Change Telemetry Pending",
            "Baseline Value": safe_float(row.get("CAPACITY_SCORE")),
            "Current Value": safe_float(row.get("CAPACITY_SCORE")),
            "Measured Delta": 0,
            "Company": company,
            "Environment": environment,
        })
    return upsert_actions(session, actions)


def _render_capacity_brief(company: str, environment: str) -> None:
    with st.expander("Capacity Brief", expanded=bool(st.session_state.get("exceptions_only_mode"))):
        days = day_window_selectbox("Capacity lookback", key="wh_capacity_days", default=7)
        if st.button("Load Capacity Brief", key="wh_capacity_load"):
            with render_load_status("Building warehouse capacity brief", "Warehouse capacity brief ready"):
                try:
                    session = _warehouse_action_session("load the warehouse capacity brief")
                    if session is None:
                        return
                    summary_sql, exceptions_sql = _build_warehouse_capacity_sql(session, days)
                    summary = run_query(
                        summary_sql,
                        ttl_key=f"wh_capacity_summary_{company}_{environment}_{days}",
                        tier="historical",
                        section="Warehouse Health",
                    )
                    exceptions = run_query(
                        exceptions_sql,
                        ttl_key=f"wh_capacity_exceptions_{company}_{environment}_{days}",
                        tier="historical",
                        section="Warehouse Health",
                    )
                    st.session_state["wh_capacity_summary"] = summary
                    st.session_state["wh_capacity_exceptions"] = exceptions
                    st.session_state["wh_capacity_sql"] = {
                        "summary": summary_sql,
                        "exceptions": exceptions_sql,
                    }
                    st.session_state["wh_capacity_meta"] = _warehouse_scope_meta(company, environment, days)
                    try:
                        operability_sql = _warehouse_operability_fact_sql(days, company, environment)
                        st.session_state["wh_operability_fact_sql"] = operability_sql
                        st.session_state["wh_operability_fact"] = run_query(
                            operability_sql,
                            ttl_key=f"wh_operability_fact_{company}_{environment}_{days}",
                            tier="standard",
                            section="Warehouse Health",
                        )
                        st.session_state.pop("wh_operability_fact_error", None)
                    except Exception as fact_exc:
                        st.session_state["wh_operability_fact"] = pd.DataFrame()
                        st.session_state["wh_operability_fact_error"] = format_snowflake_error(fact_exc)
                except Exception as e:
                    st.warning(f"Capacity brief unavailable in this role/context: {format_snowflake_error(e)}")

        summary = st.session_state.get("wh_capacity_summary")
        exceptions = st.session_state.get("wh_capacity_exceptions")
        meta = st.session_state.get("wh_capacity_meta", {})
        if (
            summary is None
            or summary.empty
            or meta.get("company") != company
            or meta.get("environment") != environment
            or meta.get("days") != int(days)
        ):
            return
        exceptions = _warehouse_capacity_priority_view(exceptions)
        row = summary.iloc[0].to_dict()
        score = _warehouse_capacity_score(
            queued_queries=safe_int(row.get("QUEUED_QUERIES")),
            spill_queries=safe_int(row.get("SPILL_QUERIES")),
            high_latency_queries=safe_int(row.get("HIGH_LATENCY_QUERIES")),
            total_queries=safe_int(row.get("TOTAL_QUERIES")),
            credit_spike_pct=safe_float(row.get("CREDIT_SPIKE_PCT")),
        )
        render_shell_snapshot((
            ("Queued", f"{safe_int(row.get('QUEUED_QUERIES')):,}"),
            ("Spill", f"{safe_int(row.get('SPILL_QUERIES')):,}"),
            ("Metered Credits", format_credits(safe_float(row.get("METERED_CREDITS")))),
        ))
        if score < 65:
            st.error("Capacity risk: warehouse pressure is high enough to affect service levels or cost control.")
        elif score < 78:
            st.warning("Pressure: review exception warehouses before expanding workload growth.")
        elif score < 90:
            st.info("Watch: warehouse pressure exists, but it is not currently dominant.")
        else:
            st.success("Healthy: no major warehouse pressure signal in this scope.")

        operability_fact = st.session_state.get("wh_operability_fact")
        if operability_fact is not None and not operability_fact.empty:
            st.subheader("Warehouse Control Summary")
            render_shell_snapshot((
                ("Rows", f"{len(operability_fact):,}"),
                ("Overdue", f"{int(operability_fact.get('OVERDUE_OPEN', pd.Series(dtype=int)).sum()):,}"),
                (
                    "Pressure Signals",
                    f"{int(operability_fact.get('QUEUE_PRESSURE_ROWS', pd.Series(dtype=int)).sum() + operability_fact.get('SPILL_PRESSURE_ROWS', pd.Series(dtype=int)).sum()):,}",
                ),
                ("Closed", f"{int(operability_fact.get('VERIFIED_CLOSURES', pd.Series(dtype=int)).sum()):,}"),
            ))
            render_priority_dataframe(
                operability_fact,
                title="Warehouse blockers",
                priority_columns=[
                    "SNAPSHOT_DATE", "CONTROL_STATE", "CONTROL_SOURCE", "ENVIRONMENT",
                    "WAREHOUSE_NAME", "SEVERITY", "SIGNAL",
                    "QUERY_ROWS", "QUEUE_PRESSURE_ROWS", "SPILL_PRESSURE_ROWS",
                    "HIGH_LATENCY_ROWS", "METERED_CREDITS", "CREDIT_ALLOCATION_METHOD", "REVIEW_ROWS",
                    "APPROVAL_REQUIRED_ROWS", "ROLLBACK_REQUIRED_ROWS",
                    "IMPACT_TELEMETRY_ROWS", "OPEN_ACTIONS", "OVERDUE_OPEN",
                    "FIXED_WITHOUT_VERIFICATION", "VERIFIED_CLOSURES", "NEXT_CONTROL_ACTION",
                ],
                sort_by=["CONTROL_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "METERED_CREDITS"],
                ascending=[True, False, False, False],
                raw_label="All warehouse control rows",
                height=300,
            )
            with st.expander("Warehouse Control Status", expanded=False):
                render_shell_snapshot((
                    ("Control summary", "Ready"),
                    ("Escalation route", "Review"),
                    ("Closure status", "Required"),
                    ("Execution", "Runbook only"),
                ))
        elif st.session_state.get("wh_operability_fact_error"):
            defer_source_note(
                "Warehouse control summary is not available yet; refresh data health to enable the fast blocker surface."
            )

        _render_warehouse_watch_floor(score, exceptions, row)
        if exceptions is not None and not exceptions.empty:
            audit_col, audit_hint_col = st.columns([1, 3])
            with audit_col:
                if st.button("Load Execution Audit", key="wh_setting_execution_audit_load", width="stretch"):
                    try:
                        audit_sql = _warehouse_setting_execution_audit_sql(30, company, environment)
                        audit = run_query(
                            audit_sql,
                            ttl_key=f"wh_setting_execution_audit_{company}_{environment}_30",
                            tier="standard",
                            section="Warehouse Health",
                        )
                        st.session_state["wh_setting_execution_audit"] = audit
                        st.session_state["wh_setting_execution_audit_sql"] = audit_sql
                        st.session_state["wh_setting_execution_audit_meta"] = _warehouse_scope_meta(
                            company, environment, 30
                        )
                    except Exception as exc:
                        st.session_state["wh_setting_execution_audit"] = pd.DataFrame()
                        st.warning(f"Warehouse execution audit unavailable: {format_snowflake_error(exc)}")
            with audit_hint_col:
                defer_source_note(
                    "Joins setting-review snapshots to guarded ALTER WAREHOUSE audit rows so changes have "
                    "review status, rollback, SQL hash, executor, and post-change telemetry."
                )

            closure_days_for_board = safe_int(st.session_state.get("wh_action_closure_days", 30)) or 30
            closure_for_board = st.session_state.get("wh_action_closure")
            if not _warehouse_meta_matches(
                st.session_state.get("wh_action_closure_meta"),
                _warehouse_scope_meta(company, environment, closure_days_for_board),
            ):
                closure_for_board = pd.DataFrame()
            audit_for_board = st.session_state.get("wh_setting_execution_audit")
            if not _warehouse_meta_matches(
                st.session_state.get("wh_setting_execution_audit_meta"),
                _warehouse_scope_meta(company, environment, 30),
            ):
                audit_for_board = pd.DataFrame()

            control_board = _warehouse_setting_control_board(
                exceptions,
                closure=closure_for_board,
                execution_audit=audit_for_board,
            )
            operator_moves = _warehouse_operator_next_moves(
                score=score,
                exceptions=exceptions,
                control_board=control_board,
                closure=closure_for_board,
                execution_audit=audit_for_board,
                operability_fact=operability_fact,
            )
            render_priority_dataframe(
                operator_moves,
                title="Warehouse operator next-move gates",
                priority_columns=["GATE", "STATE", "COUNT", "PROOF_REQUIRED", "NEXT_ACTION"],
                sort_by=["GATE_RANK", "COUNT"],
                ascending=[True, False],
                raw_label="All warehouse operator gates",
                height=220,
                max_rows=5,
            )
            intervention_matrix = _warehouse_intervention_matrix(
                exceptions,
                control_board=control_board,
                closure=closure_for_board,
            )
            if not intervention_matrix.empty:
                render_priority_dataframe(
                    intervention_matrix,
                    title="Warehouse DBA intervention matrix",
                    priority_columns=[
                        "DBA_PRIORITY", "INTERVENTION_STATE", "WAREHOUSE_NAME", "SEVERITY", "SIGNAL",
                        "METERED_CREDITS", "PRESSURE_EVIDENCE",
                        "CONTROL_STATE", "CLOSURE_READINESS", "NEXT_DECISION",
                        "PROOF_REQUIRED", "NEXT_WORKFLOW",
                    ],
                    sort_by=["DBA_PRIORITY", "METERED_CREDITS"],
                    ascending=[True, False],
                    raw_label="All warehouse DBA intervention rows",
                    height=280,
                    max_rows=8,
                )
            if not control_board.empty:
                render_priority_dataframe(
                    control_board,
                    title="Warehouse setting control board",
                    priority_columns=[
                        "CONTROL_STATE", "WAREHOUSE_NAME", "SEVERITY", "SIGNAL",
                        "METERED_CREDITS", "ROUTE_READINESS",
                        "AUDIT_READINESS", "AUDIT_BLOCKERS", "CLOSURE_READINESS",
                        "AUDIT_ROWS", "SUCCESSFUL_CHANGES", "FAILED_CHANGES",
                        "LAST_EXECUTION_STATUS", "APPROVAL_REQUIRED", "ROLLBACK_REQUIRED",
                        "IMPACT_TELEMETRY_REQUIRED", "NEXT_CONTROL_ACTION",
                    ],
                    sort_by=["CONTROL_RANK", "METERED_CREDITS"],
                    ascending=[True, False],
                    raw_label="All warehouse setting control rows",
                    height=300,
                    max_rows=12,
                )
        st.divider()

        if exceptions is not None and not exceptions.empty:
            render_priority_dataframe(
                exceptions,
                title="Warehouse capacity exceptions to work first",
                priority_columns=[
                    "SEVERITY", "SIGNAL", "WAREHOUSE_NAME", "WAREHOUSE_SIZE",
                    "QUEUED_QUERIES", "SPILL_QUERIES", "HIGH_LATENCY_QUERIES",
                    "METERED_CREDITS", "ADMIN_READINESS", "SETTING_CHANGE_CANDIDATE",
                    "OWNER", "ESCALATION_TARGET", "APPROVER",
                    "APPROVAL_REQUIRED", "ROLLBACK_REQUIRED", "IMPACT_TELEMETRY_REQUIRED", "NEXT_ACTION",
                ],
                sort_by=["QUEUED_QUERIES", "SPILL_QUERIES", "HIGH_LATENCY_QUERIES", "METERED_CREDITS"],
                ascending=[False, False, False, False],
                raw_label="All warehouse capacity exceptions",
            )
            save_col, review_col = st.columns([1, 2])
            with save_col:
                if st.button("Save Setting Review Snapshot", key="wh_setting_review_snapshot", width="stretch"):
                    session = _warehouse_action_session("save a warehouse setting review snapshot")
                    if session is not None:
                        _save_warehouse_setting_review_snapshot(
                            session,
                            exceptions,
                            company=company,
                            environment=environment,
                            source="Warehouse Health Capacity Brief",
                        )
            with review_col:
                defer_source_note(
                    "Snapshot stores review path, rollback requirement, baseline pressure, and post-change telemetry."
                )
            with st.expander("Warehouse Setting Review Trend", expanded=False):
                trend_days = day_window_selectbox(
                    "Setting review trend window",
                    key="wh_setting_review_trend_days",
                    default=30,
                )
                if st.button("Load Setting Review Trend", key="wh_setting_review_trend_load"):
                    try:
                        trend_sql = _warehouse_setting_review_history_sql(trend_days, company, environment)
                        trend = run_query(
                            trend_sql,
                            ttl_key=f"wh_setting_review_trend_{company}_{environment}_{trend_days}",
                            tier="standard",
                            section="Warehouse Health",
                        )
                        st.session_state["wh_setting_review_trend"] = trend
                        st.session_state["wh_setting_review_trend_sql"] = trend_sql
                    except Exception as exc:
                        st.error(f"Unable to load warehouse setting review trend: {format_snowflake_error(exc)}")
                trend = st.session_state.get("wh_setting_review_trend")
                if trend is not None and not trend.empty:
                    render_priority_dataframe(
                        trend,
                        title="Persistent warehouse setting review backlog",
                        priority_columns=[
                            "WAREHOUSE_NAME", "OWNER", "ESCALATION_TARGET", "REVIEW_ROWS",
                            "APPROVAL_REQUIRED_ROWS", "ROLLBACK_REQUIRED_ROWS",
                            "IMPACT_TELEMETRY_ROWS", "WORST_BASELINE_CAPACITY_SCORE",
                            "MAX_BASELINE_QUEUED_QUERIES", "MAX_BASELINE_SPILL_QUERIES",
                            "LAST_SIGNAL", "LAST_SETTING_CHANGE_CANDIDATE",
                        ],
                        sort_by=["WORST_BASELINE_CAPACITY_SCORE", "APPROVAL_REQUIRED_ROWS", "LAST_SNAPSHOT_TS"],
                        ascending=[True, False, False],
                        raw_label="All persisted warehouse setting reviews",
                        height=260,
                    )
                defer_source_note(
                    "Warehouse setting-review history is owned by the DBA platform team for this environment."
                )
            with st.expander("Warehouse Action Closure Analytics", expanded=False):
                defer_source_note(
                    "Uses Cost & Contract warehouse action-queue rows to show which capacity or efficiency actions are open, "
                    "overdue, telemetry-pending, or recently closed."
                )
                closure_days = day_window_selectbox(
                    "Warehouse closure window",
                    key="wh_action_closure_days",
                    default=30,
                )
                if st.button("Load Warehouse Closure Analytics", key="wh_action_closure_load"):
                    try:
                        closure_sql = _warehouse_action_queue_closure_sql(closure_days, company, environment)
                        closure = run_query(
                            closure_sql,
                            ttl_key=f"wh_action_closure_{company}_{environment}_{closure_days}",
                            tier="standard",
                            section="Warehouse Health",
                        )
                        st.session_state["wh_action_closure"] = closure
                        st.session_state["wh_action_closure_sql"] = closure_sql
                        st.session_state["wh_action_closure_meta"] = _warehouse_scope_meta(
                            company, environment, closure_days
                        )
                    except Exception as exc:
                        st.session_state["wh_action_closure"] = pd.DataFrame()
                        st.warning(f"Warehouse closure analytics unavailable: {format_snowflake_error(exc)}")
                closure = st.session_state.get("wh_action_closure")
                closure_current = _warehouse_meta_matches(
                    st.session_state.get("wh_action_closure_meta"),
                    _warehouse_scope_meta(company, environment, closure_days),
                )
                if closure is not None and not closure.empty and closure_current:
                    render_priority_dataframe(
                        closure,
                        title="Warehouse closure status gaps",
                        priority_columns=[
                            "WAREHOUSE_NAME", "CLOSURE_READINESS", "OWNER", "APPROVER",
                            "TOTAL_ACTIONS", "OPEN_ACTIONS", "OVERDUE_OPEN",
                            "VERIFIED_CLOSURES", "FIXED_WITHOUT_VERIFICATION",
                            "OWNER_GAP_ROWS", "TICKET_GAP_ROWS", "APPROVER_GAP_ROWS",
                            "OWNER_APPROVAL_GAP_ROWS", "VERIFICATION_QUERY_GAP_ROWS",
                            "RECOVERY_RISK_ROWS", "NEXT_DUE_DATE", "LAST_STATUS", "NEXT_ACTION",
                        ],
                        sort_by=["CLOSURE_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "OPEN_ACTIONS"],
                        ascending=[True, False, False, False],
                        raw_label="All warehouse closure rows",
                        height=300,
                    )
                    with st.expander("Warehouse Closure Status", expanded=False):
                        render_shell_snapshot((
                            ("Closure status", "Ready"),
                            ("Telemetry", "Review"),
                            ("Telemetry", "Required"),
                            ("Execution", "Runbook only"),
                        ))
                elif closure is not None and not closure.empty and not closure_current:
                    st.info("Loaded warehouse closure analytics are stale for the active scope. Reload closure analytics before acting.")
                elif closure is not None:
                    st.info("No warehouse capacity action-queue rows found for the selected scope.")
            with st.expander("Warehouse Execution Audit Detail", expanded=False):
                audit = st.session_state.get("wh_setting_execution_audit")
                audit_current = _warehouse_meta_matches(
                    st.session_state.get("wh_setting_execution_audit_meta"),
                    _warehouse_scope_meta(company, environment, 30),
                )
                if audit is not None and not audit.empty and audit_current:
                    render_priority_dataframe(
                        audit,
                        title="Warehouse setting execution audit",
                        priority_columns=[
                            "WAREHOUSE_NAME", "EXECUTION_AUDIT_READINESS", "OWNER", "APPROVER",
                            "APPROVAL_STATE", "CHANGE_TICKET_ID", "REVIEW_ROWS", "AUDIT_ROWS",
                            "SUCCESSFUL_CHANGES", "FAILED_CHANGES", "LAST_SQL_HASH",
                            "LAST_EXECUTED_BY", "LAST_EXECUTED_ROLE", "LAST_EXECUTION_STATUS",
                            "LAST_EXECUTED_AT", "POST_CHANGE_VERIFICATION_STATUS",
                            "NEXT_CONTROL_ACTION",
                        ],
                        sort_by=["FAILED_CHANGES", "AUDIT_ROWS", "LAST_EXECUTED_AT"],
                        ascending=[False, False, False],
                        raw_label="All warehouse execution audit rows",
                        height=300,
                    )
                elif audit is not None and not audit.empty and not audit_current:
                    st.info("Loaded warehouse execution audit is stale for the active scope. Reload execution audit before acting.")
                elif audit is not None:
                    st.info("No warehouse setting review or ALTER WAREHOUSE audit rows found for the selected scope.")
                defer_source_note("Warehouse execution audit detail is available through the reviewed runbook.")
            if st.button("Save Capacity Findings to Action Queue", key="wh_capacity_queue"):
                try:
                    session = _warehouse_action_session("save warehouse capacity findings to the action queue")
                    if session is not None:
                        saved = _queue_capacity_findings(session, exceptions)
                        st.success(f"Saved {saved} warehouse capacity findings to the action queue.")
                except Exception as e:
                    st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
                    st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")
        else:
            st.success("No warehouse capacity exceptions found for this scope.")

        st.download_button(
            "Download Capacity Brief",
            _build_warehouse_capacity_markdown(company, days, score, row, exceptions),
            file_name=f"overwatch_warehouse_capacity_{company.lower()}.md",
            mime="text/markdown",
            key="wh_capacity_download",
        )
        with st.expander("Data Health"):
            render_shell_snapshot((
                ("Summary telemetry", "Ready after refresh"),
                ("Exception telemetry", "Ready after refresh"),
                ("Route review", "Required"),
                ("Execution", "Runbook only"),
            ))


def _queue_efficiency_findings(session, df_eff: pd.DataFrame) -> None:
    if df_eff is None or df_eff.empty:
        st.info("No efficiency findings to queue.")
        return
    company = get_active_company()
    environment = get_active_environment()
    actions = []
    for _, row in df_eff[df_eff["EFFICIENCY_SCORE"] < 70].head(100).iterrows():
        wh = str(row.get("WAREHOUSE_NAME", ""))
        score = safe_float(row.get("EFFICIENCY_SCORE", 0))
        queue = safe_float(row.get("QUEUE_SEC_PER_CREDIT", 0))
        spill = safe_float(row.get("REMOTE_SPILL_GB_PER_CREDIT", 0))
        credits = safe_float(row.get("METERED_CREDITS", 0))
        severity = "High" if score < 50 or queue > 10 or spill > 5 else "Medium"
        owner_context = _warehouse_owner_context({
            "WAREHOUSE_NAME": wh,
            "SIGNAL": "Efficiency",
            "METERED_CREDITS": credits,
        })
        verification_sql = _warehouse_capacity_verification_sql(
            wh,
            days=7,
            environment=environment,
            company=company,
        )
        approver = _warehouse_approval_for({
            "WAREHOUSE_NAME": wh,
            "SIGNAL": "Efficiency",
            "OWNER": owner_context.get("owner", ""),
        })
        finding = (
            f"{wh} efficiency review: queue sec/credit={queue:.2f}, "
            f"spill GB/credit={spill:.2f}; metered credits={credits:.2f}."
        )
        actions.append({
            "Action ID": make_action_id("Warehouse Efficiency", wh, finding),
            "Source": "Warehouse Health - Efficiency",
            "Severity": severity,
            "Category": "Warehouse Efficiency",
            "Entity Type": "Warehouse",
            "Entity": wh,
            "Route": _route_label(owner_context.get("owner", "Platform DBA")),
            "Route Email": owner_context.get("owner_email", ""),
            "Oncall Primary": owner_context.get("oncall_primary", ""),
            "Oncall Secondary": owner_context.get("oncall_secondary", ""),
            "Escalation": _route_label(owner_context.get("approval_group", approver)),
            "Escalation Target": owner_context.get("escalation", "DBA Lead"),
            "Route Basis": _route_label(owner_context.get("source", "")),
            "Route Detail": _route_label(owner_context.get("owner_evidence", "")),
            "Finding": finding,
            "Action": (
                "Review queue, spill, cache, and credit/query patterns. Route setting changes through "
                "Warehouse Settings Manager so current values, review status, rollback plan, and post-change "
                "telemetry are captured."
            ),
            "Estimated Monthly Savings": 0.0,
            "Generated SQL Fix": "\n".join([
                f"-- Review {wh} efficiency before changing warehouse settings.",
                "-- If queue dominates, compare multi-cluster settings and workload routing.",
                "-- If spill dominates, inspect top spilling query profiles before considering size changes.",
            "-- Do not execute warehouse changes from this action; use Warehouse Settings Manager after review.",
            ]),
            "Telemetry Query": verification_sql,
            "Reviewer": _route_label(approver),
            "Telemetry Status": "Requested",
            "Status Note": (
                f"Efficiency review basis attached. Route basis: {owner_context.get('owner_evidence', '')}. "
                "Setting changes require review status, rollback SQL, and post-change telemetry."
            ),
            "Recovery Status": (
                f"Baseline queue sec/credit={queue:.2f}; "
                f"remote spill GB/credit={spill:.2f}; metered credits={credits:.2f}. "
                "Closure uses queue/spill/credit telemetry for the same warehouse and environment."
            ),
            "Recovery Audit State": "Warehouse Efficiency Telemetry Pending",
            "Recovery SLA Target Hours": 24 if severity == "High" else 72,
            "Baseline Value": score,
            "Current Value": score,
            "Measured Delta": 0,
            "Company": company,
            "Environment": environment,
        })
    if not actions:
        st.success("No warehouses below the queue threshold.")
        return
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} warehouse efficiency findings to the action queue.")
    except Exception as e:
        st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
        st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")


def _render_warehouse_source_health(company: str, environment: str) -> None:
    source_health = _warehouse_source_health_rows(st.session_state, company, environment)
    if source_health.empty:
        return
    with st.expander("Warehouse Telemetry Health", expanded=False):
        loaded = int(source_health["STATE"].isin(["Loaded", "No Rows"]).sum())
        stale = int(source_health["STATE"].eq("Stale").sum())
        unavailable = int(source_health["STATE"].eq("Unavailable").sum())
        fast_summary = int(
            source_health[
            source_health["STATE"].isin(["Loaded", "No Rows"])
            & source_health["CONFIDENCE"].astype(str).str.contains("Fast summary", case=False, regex=False)
        ].shape[0]
        )
        render_shell_snapshot((
            ("Current Surfaces", f"{loaded}/{len(source_health)}"),
            ("Fast Summary", f"{fast_summary:,}"),
            ("Stale", f"{stale:,}"),
            ("Unavailable", f"{unavailable:,}"),
        ))
        defer_source_note(
            "Use this before acting on warehouse findings. Stale rows mean the data was loaded under a different "
            "company, environment, lookback, or triage filter."
        )
        render_priority_dataframe(
            source_health,
            title="Warehouse telemetry source and freshness",
            priority_columns=[
                "SURFACE", "STATE", "SOURCE", "CONFIDENCE", "ROWS", "SCOPE", "NEXT_ACTION",
            ],
            sort_by=["STATE_RANK", "SURFACE"],
            ascending=[True, True],
            raw_label="All warehouse source-health rows",
            height=320,
        )


def _warehouse_support_panels_have_state() -> bool:
    return any(
        st.session_state.get(key) is not None
        for key in (
            "wh_capacity_summary",
            "wh_capacity_exceptions",
            "wh_operability_fact",
            "wh_setting_review_snapshot",
            "wh_action_closure",
        )
    )


def _apply_warehouse_fast_entry_default() -> None:
    """Keep first Warehouse Health navigation from replaying heavy support panels."""
    if st.session_state.get("_warehouse_health_fast_entry_version") == WAREHOUSE_HEALTH_FAST_ENTRY_VERSION:
        return
    st.session_state.pop("warehouse_health_support_panels_open", None)
    st.session_state["_warehouse_health_fast_entry_version"] = WAREHOUSE_HEALTH_FAST_ENTRY_VERSION


def _render_warehouse_overview_exception_strip(df: pd.DataFrame | None) -> None:
    exceptions = _warehouse_overview_exceptions(df)
    st.markdown("**Exception Strip**")
    if not exceptions:
        st.success("No urgent warehouse queue, spill, latency, or credit movement exceptions in the loaded overview.")
        return
    for item in exceptions:
        message = (
            f"{item['severity']}: {item['warehouse']} - {item['signal']}. "
            f"{item['next_action']}"
        )
        if item["severity"] == "Critical":
            st.error(message)
        elif item["severity"] == "High":
            st.warning(message)
        else:
            st.info(message)


def render():
    credit_price = st.session_state.get("credit_price", DEFAULTS["credit_price"])
    company = get_active_company()
    environment = get_active_environment()
    _apply_warehouse_fast_entry_default()
    _apply_warehouse_brief_first_default()
    _apply_queued_warehouse_health_view()
    global_warehouse = str(st.session_state.get("global_warehouse", "") or "").strip()
    global_user = str(st.session_state.get("global_user", "") or "").strip()
    global_role = str(st.session_state.get("global_role", "") or "").strip()
    global_database = str(st.session_state.get("global_database", "") or "").strip()
    global_start_date = st.session_state.get("global_start_date")
    global_end_date = st.session_state.get("global_end_date")

    selected_days = safe_int(st.session_state.get("wh_days", 7), 7) or 7
    if selected_days < 1 or selected_days > 30:
        selected_days = 7
    _render_warehouse_action_brief(_warehouse_action_brief(company, environment, selected_days))
    _render_warehouse_operating_snapshot(_warehouse_operating_snapshot(company, environment, selected_days))

    render_operator_briefing(
        [
            ("First move", "Decide whether pressure is queue, spill, latency, or cost drift."),
            ("Telemetry", "Use metering plus query history before changing size or clusters."),
            ("Control", "Tune routing, auto-suspend, QAS, size, or multi-cluster with measured context."),
            ("Output", "Create a warehouse capacity brief for release or cost review."),
        ],
        columns=4,
    )
    warehouse_view = render_workflow_selector(
        "Warehouse capacity workflow",
        "warehouse_health_view",
        WAREHOUSE_HEALTH_VIEWS,
        WAREHOUSE_HEALTH_DETAILS,
        columns=3,
    )
    if warehouse_view == "Overview & Scaling" and not _warehouse_frame_has_rows(st.session_state.get("wh_df_wh")):
        _render_warehouse_brief_launchpad()
    show_support_panels = bool(st.session_state.get("warehouse_health_support_panels_open"))
    if show_support_panels:
        if st.button("Hide Detail Panels", key="warehouse_health_hide_support_panels"):
            st.session_state["warehouse_health_support_panels_open"] = False
            st.rerun()
        _render_capacity_brief(company, environment)
        _render_warehouse_source_health(company, environment)
    elif st.button("Detail Panels", key="warehouse_health_open_support_panels"):
        st.session_state["warehouse_health_support_panels_open"] = True
        st.rerun()
    if st.session_state.get("exceptions_only_mode") and warehouse_view != "Overview & Scaling":
        return

    # -- OVERVIEW --------------------------------------------------------------
    if warehouse_view == "Overview & Scaling":
        st.subheader("Warehouse Capacity Overview")
        wh_days = day_window_selectbox("Lookback", key="wh_days", default=7)

        def _load_warehouse_overview() -> None:
            try:
                session = _warehouse_action_session("load warehouse overview")
                if session is None:
                    return
                overview_result = load_shared_warehouse_overview(
                    session,
                    wh_days,
                    company,
                    force=True,
                    section="Warehouse Health",
                )
                df_w = overview_result.data
                source = overview_result.source
                try:
                    st.session_state["wh_settings_inventory"] = load_warehouse_inventory(
                        session,
                        company,
                    )
                    st.session_state["wh_settings_inventory_meta"] = with_loaded_at(
                        _warehouse_scope_meta(
                            company,
                            environment,
                            wh_days,
                        ),
                        source="Warehouse guardrail metadata",
                    )
                    st.session_state.pop("wh_settings_inventory_error", None)
                except Exception as metadata_exc:
                    st.session_state["wh_settings_inventory"] = pd.DataFrame()
                    st.session_state["wh_settings_inventory_error"] = format_snowflake_error(metadata_exc)
                st.session_state["wh_df_wh"] = df_w
                st.session_state["wh_df_wh_source"] = source
                st.session_state["wh_df_wh_meta"] = with_loaded_at(
                    _warehouse_scope_meta(company, environment, wh_days),
                    source=source,
                )
            except Exception as e:
                st.warning(f"Warehouse overview unavailable in this role/context: {format_snowflake_error(e)}")

        wh_expected_meta = _warehouse_scope_meta(company, environment, wh_days)
        loaded_wh_meta = st.session_state.get("wh_df_wh_meta", {})
        wh_current = (
            st.session_state.get("wh_df_wh") is not None
            and _warehouse_meta_matches(loaded_wh_meta, wh_expected_meta)
        )
        if consume_section_autoload_request("Warehouse Health") and not wh_current:
            st.caption("Warehouse capacity opened with a lightweight summary. Load warehouse data when current capacity detail is needed.")
        render_data_freshness(
            loaded_wh_meta if wh_current else {},
            source=st.session_state.get("wh_df_wh_source", "Warehouse overview"),
            target_minutes=30,
            delayed_note="Warehouse overview prefers fast summary telemetry; live account history refresh is explicit.",
        )

        if st.button("Load Warehouse Data", key="wh_load"):
            _load_warehouse_overview()

        if (
            st.session_state.get("wh_df_wh") is not None
            and not _warehouse_meta_matches(
                st.session_state.get("wh_df_wh_meta"),
                _warehouse_scope_meta(company, environment, wh_days),
            )
        ):
            st.info("Loaded warehouse overview is stale for the active scope. Reload Warehouse Data before acting.")
        elif st.session_state.get("wh_df_wh") is not None and not st.session_state["wh_df_wh"].empty:
            df_w = st.session_state["wh_df_wh"]

            render_shell_snapshot((
                ("Warehouses Active", len(df_w)),
                ("Total Queries", f"{int(df_w['TOTAL_QUERIES'].sum()):,}"),
                ("Total Remote Spill", f"{df_w['TOTAL_REMOTE_SPILL_GB'].sum():.1f} GB"),
                ("Credit Delta", format_credits(float(df_w.get("CREDIT_DELTA", pd.Series(dtype=float)).sum()))),
            ))
            wh_source = st.session_state.get("wh_df_wh_source", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY")
            wh_source_lower = str(wh_source).lower()
            confidence = "estimated" if "fast" in wh_source_lower and "summary" in wh_source_lower else "exact"
            defer_source_note(metric_confidence_label(confidence), wh_source)
            _render_warehouse_overview_exception_strip(df_w)
            detail_key = "warehouse_health_show_overview_evidence"
            detail_open = bool(st.session_state.get(detail_key))
            detail_col, _ = st.columns([1.2, 4.0])
            with detail_col:
                if detail_open:
                    if st.button("Hide Warehouse Detail", key="warehouse_health_hide_overview_evidence", width="stretch"):
                        st.session_state[detail_key] = False
                        st.rerun()
                elif st.button("Show Warehouse Detail", key="warehouse_health_show_overview_evidence_button", width="stretch"):
                    st.session_state[detail_key] = True
                    st.rerun()
            if not detail_open:
                return

            movement = _warehouse_period_movement(df_w)
            if not movement.empty:
                st.subheader("Warehouse Period Movement")
                render_priority_dataframe(
                    movement,
                    title="Current vs prior warehouse movement",
                    priority_columns=[
                        "WAREHOUSE_NAME", "MOVEMENT_STATE", "METERED_CREDITS",
                        "PRIOR_METERED_CREDITS", "CREDIT_DELTA", "CREDIT_DELTA_PCT",
                        "AVG_QUEUED_SEC", "TOTAL_REMOTE_SPILL_GB", "NEXT_ACTION",
                    ],
                    sort_by=["CREDIT_DELTA", "METERED_CREDITS"],
                    ascending=[False, False],
                    raw_label="All warehouse period movement rows",
                    height=320,
                )
            else:
                defer_source_note("Current/prior warehouse movement appears when the fast warehouse summary is available.")

            settings_inventory = st.session_state.get("wh_settings_inventory")
            if not _warehouse_meta_matches(
                st.session_state.get("wh_settings_inventory_meta"),
                _warehouse_scope_meta(company, environment, wh_days),
            ):
                settings_inventory = pd.DataFrame()

            guardrail_summary, guardrail_board = _build_warehouse_guardrail_coverage(
                df_w,
                settings_inventory=settings_inventory,
            )
            if not guardrail_board.empty:
                st.subheader("Warehouse Guardrail Coverage")
                render_shell_snapshot((
                    ("Guardrail State", "Stable" if guardrail_summary["score"] >= 90 else "Review" if guardrail_summary["score"] >= 70 else "Critical"),
                    ("Blocked", f"{guardrail_summary['blocked']:,}"),
                    ("Needs Review", f"{guardrail_summary['review']:,}"),
                    ("Data Missing", f"{guardrail_summary['unknown']:,}"),
                ))
                render_priority_dataframe(
                    guardrail_board,
                    title="Auto-derived warehouse guardrail coverage",
                    priority_columns=[
                        "WAREHOUSE_NAME", "GUARDRAIL_STATE", "GUARDRAIL_SCORE", "SEVERITY",
                        "RESOURCE_MONITOR_STATE", "AUTO_SUSPEND_STATE", "TIMEOUT_STATE",
                        "ESCALATION_ROUTE_STATE", "CAPACITY_STATE", "COST_STATE",
                        "METERED_CREDITS", "CREDIT_DELTA",
                        "AVG_QUEUED_SEC", "TOTAL_REMOTE_SPILL_GB", "P95_ELAPSED_SEC",
                        "NEXT_ACTION", "PROOF_REQUIRED",
                    ],
                    sort_by=["GUARDRAIL_RANK", "GUARDRAIL_SCORE", "METERED_CREDITS"],
                    ascending=[True, True, False],
                    raw_label="All warehouse guardrail coverage rows",
                    height=320,
                    max_rows=12,
                )
                download_csv(guardrail_board, "warehouse_guardrail_coverage.csv")
                setting_plan = _warehouse_setting_action_plan(guardrail_board)
                st.session_state["wh_settings_action_plan"] = setting_plan
                if not setting_plan.empty:
                    st.subheader("Warehouse Setting Action Plan")
                    render_priority_dataframe(
                        setting_plan,
                        title="Recommended warehouse setting controls",
                        priority_columns=[
                            "PRIORITY", "WAREHOUSE_NAME", "ACTION_TYPE", "CURRENT_STATE",
                            "CURRENT_SETTING", "SAFE_SETTING_MOVE", "WHY", "ROLLBACK_CHECK",
                        ],
                        sort_by=["PRIORITY", "WAREHOUSE_NAME", "ACTION_TYPE"],
                        ascending=[True, True, True],
                        raw_label="All warehouse setting action rows",
                        height=320,
                        max_rows=12,
                    )
                    download_csv(setting_plan, "warehouse_setting_action_plan.csv")
                    _render_warehouse_setting_action_detail(setting_plan)
                _render_warehouse_cost_control_posture(settings_inventory, df_w)
                if st.session_state.get("wh_settings_inventory_error"):
                    defer_source_note(
                        "Warehouse metadata was unavailable for resource-monitor, timeout, and auto-suspend checks: "
                        f"{st.session_state.get('wh_settings_inventory_error')}"
                    )
                elif settings_inventory is None or settings_inventory.empty:
                    defer_source_note("Resource-monitor, timeout, and AUTO_SUSPEND checks need SHOW WAREHOUSES metadata.")

            render_priority_dataframe(
                df_w,
                title="Warehouse overview ranked by pressure",
                priority_columns=[
                    "WAREHOUSE_NAME",
                    "WAREHOUSE_SIZE",
                    "TOTAL_QUERIES",
                    "AVG_QUEUED_SEC",
                    "TOTAL_REMOTE_SPILL_GB",
                    "AVG_ELAPSED_SEC",
                    "METERED_CREDITS",
                    "PRIOR_METERED_CREDITS",
                    "CREDIT_DELTA",
                    "AVG_CACHE_PCT",
                ],
                sort_by=[
                    "AVG_QUEUED_SEC",
                    "TOTAL_REMOTE_SPILL_GB",
                    "AVG_ELAPSED_SEC",
                    "METERED_CREDITS",
                ],
                ascending=[False, False, False, False],
                raw_label="All warehouse overview rows",
            )

            # Cache efficiency chart
            cache_available = "AVG_CACHE_PCT" in df_w.columns and df_w["AVG_CACHE_PCT"].notna().any()
            if cache_available:
                st.subheader("Cache Hit % by Warehouse")
                render_drillable_bar_chart(
                    df_w,
                    dimension="WAREHOUSE_NAME",
                    measure="AVG_CACHE_PCT",
                    key="wh_cache_pct",
                    drilldown_column="warehouse_name",
                    lookback_hours=wh_days * 24,
                )
            else:
                defer_source_note("Cache hit percentage is a live ACCOUNT_USAGE-only metric and is not included in the fast warehouse summary.")

            download_csv(df_w, "warehouse_health.csv")

            # Scaling events
            st.divider()
            st.subheader("Scaling Events (WAREHOUSE_METERING_HISTORY)")
            if st.button("Load Scaling Events", key="wh_scale_load"):
                try:
                    session = _warehouse_action_session("load warehouse scaling events")
                    if session is None:
                        return
                    scale_result = load_shared_warehouse_scaling_events(
                        session,
                        wh_days,
                        company,
                        force=True,
                        section="Warehouse Health",
                    )
                    st.session_state["wh_scaling"] = scale_result.data
                    st.session_state["wh_scaling_source"] = scale_result.source
                    st.session_state["wh_scaling_meta"] = _warehouse_scope_meta(company, environment, wh_days)
                except Exception as e:
                    st.warning(f"Scaling events unavailable in this role/context: {format_snowflake_error(e)}")
            df_scale = st.session_state.get("wh_scaling")
            if (
                df_scale is not None
                and not _warehouse_meta_matches(
                    st.session_state.get("wh_scaling_meta"),
                    _warehouse_scope_meta(company, environment, wh_days),
                )
            ):
                st.info("Loaded scaling events are stale for the active scope. Reload Scaling Events before acting.")
            elif df_scale is not None and not df_scale.empty:
                scale_source = st.session_state.get("wh_scaling_source", "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY")
                defer_source_note(metric_confidence_label("exact"), scale_source)
                render_priority_dataframe(
                    df_scale,
                    title="Largest scaling/metering events",
                    priority_columns=[
                        "WAREHOUSE_NAME",
                        "WAREHOUSE_SIZE",
                        "START_TIME",
                        "END_TIME",
                        "CREDITS_USED",
                        "CREDITS_USED_COMPUTE",
                        "CREDITS_USED_CLOUD_SERVICES",
                    ],
                    sort_by=["CREDITS_USED", "CREDITS_USED_COMPUTE"],
                    ascending=[False, False],
                    raw_label="All scaling events",
                )
                download_csv(df_scale, "scaling_events.csv")
            elif df_scale is not None:
                st.info("No scaling or metering events found for the selected warehouse scope.")

    elif warehouse_view == "Efficiency":
        st.subheader("Warehouse Efficiency Risks")
        eff_days = day_window_selectbox("Lookback", key="wh_eff_days", default=7)
        if st.button("Load Efficiency Metrics", key="wh_eff_load"):
            try:
                session = _warehouse_action_session("load warehouse efficiency metrics")
                if session is None:
                    return
                result = load_shared_warehouse_efficiency(
                    session,
                    eff_days,
                    company,
                    force=True,
                    section="Warehouse Health",
                )
                st.session_state["wh_efficiency"] = result.data
                st.session_state["wh_efficiency_meta"] = _warehouse_scope_meta(company, environment, eff_days)
                st.session_state["wh_efficiency_source"] = result.source
            except Exception as e:
                st.warning(f"Efficiency metrics unavailable in this role/context: {format_snowflake_error(e)}")

        df_eff = st.session_state.get("wh_efficiency")
        if (
            df_eff is not None
            and not _warehouse_meta_matches(
                st.session_state.get("wh_efficiency_meta"),
                _warehouse_scope_meta(company, environment, eff_days),
            )
        ):
            st.info("Loaded efficiency metrics are stale for the active scope. Reload Efficiency Metrics before acting.")
        elif df_eff is not None and not df_eff.empty:
            low = df_eff[df_eff["EFFICIENCY_SCORE"] < 70]
            render_shell_snapshot((
                ("Warehouses Reviewed", len(df_eff)),
                ("Needs Review", len(low)),
                ("Total metered credits", format_credits(float(df_eff["METERED_CREDITS"].sum()))),
            ))
            defer_source_note(
                metric_confidence_label("allocated"),
                st.session_state.get("wh_efficiency_source", freshness_note("ACCOUNT_USAGE")),
            )
            df_eff_display = df_eff.rename(columns={"EFFICIENCY_SCORE": "REVIEW_PRIORITY"})
            render_priority_dataframe(
                df_eff_display,
                title="Warehouse efficiency risks",
                priority_columns=[
                    "WAREHOUSE_NAME",
                    "WAREHOUSE_SIZE",
                    "REVIEW_PRIORITY",
                    "METERED_CREDITS",
                    "CREDITS_PER_QUERY",
                    "QUEUE_SEC_PER_CREDIT",
                    "REMOTE_SPILL_GB_PER_CREDIT",
                    "AVG_CACHE_PCT",
                ],
                sort_by=["REVIEW_PRIORITY", "METERED_CREDITS"],
                ascending=[True, False],
                raw_label="All warehouse efficiency rows",
            )
            render_drillable_bar_chart(
                df_eff_display,
                dimension="WAREHOUSE_NAME",
                measure="REVIEW_PRIORITY",
                key="wh_efficiency_review_priority",
                drilldown_column="warehouse_name",
                lookback_hours=eff_days * 24,
            )
            download_csv(df_eff, "warehouse_efficiency.csv")
            if st.button("Save low-efficiency warehouses to Action Queue", key="wh_eff_queue"):
                session = _warehouse_action_session("save warehouse efficiency findings to the action queue")
                if session is not None:
                    _queue_efficiency_findings(session, df_eff)

    # -- SPILL -----------------------------------------------------------------
    elif warehouse_view == "Spill & Memory":
        st.subheader("Spill & Memory Pressure")
        sp_days = day_window_selectbox("Lookback", key="sp_days", default=7)

        if st.button("Load Spill Data", key="sp_load"):
            try:
                session = _warehouse_action_session("load warehouse spill data")
                if session is None:
                    return
                result = load_shared_warehouse_spill(
                    session,
                    sp_days,
                    company,
                    force=True,
                    section="Warehouse Health",
                )
                st.session_state["wh_df_sp"] = result.data
                st.session_state["wh_df_sp_meta"] = _warehouse_scope_meta(company, environment, sp_days)
                st.session_state["wh_df_sp_source"] = result.source
            except Exception as e:
                st.warning(f"Spill data unavailable in this role/context: {format_snowflake_error(e)}")

        if (
            st.session_state.get("wh_df_sp") is not None
            and not _warehouse_meta_matches(
                st.session_state.get("wh_df_sp_meta"),
                _warehouse_scope_meta(company, environment, sp_days),
            )
        ):
            st.info("Loaded spill data is stale for the active scope. Reload Spill Data before acting.")
        elif st.session_state.get("wh_df_sp") is not None and not st.session_state["wh_df_sp"].empty:
            df_sp = st.session_state["wh_df_sp"]
            render_shell_snapshot((
                ("Spilling Warehouses", len(df_sp)),
                ("Total Local Spill", f"{df_sp['LOCAL_SPILL_GB'].sum():.1f} GB"),
                ("Total Remote Spill", f"{df_sp['REMOTE_SPILL_GB'].sum():.1f} GB"),
            ))
            defer_source_note(st.session_state.get("wh_df_sp_source", "Live: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"))
            render_priority_dataframe(
                df_sp,
                title="Spill and memory pressure",
                priority_columns=[
                    "WAREHOUSE_NAME",
                    "WAREHOUSE_SIZE",
                    "SPILL_QUERY_COUNT",
                    "LOCAL_SPILL_GB",
                    "REMOTE_SPILL_GB",
                    "AVG_ELAPSED_SEC",
                ],
                sort_by=["REMOTE_SPILL_GB", "LOCAL_SPILL_GB", "AVG_ELAPSED_SEC"],
                ascending=[False, False, False],
                raw_label="All spill rows",
            )
            df_sp["TOTAL_SPILL_GB"] = df_sp["LOCAL_SPILL_GB"] + df_sp["REMOTE_SPILL_GB"]
            render_drillable_bar_chart(
                df_sp,
                dimension="WAREHOUSE_NAME",
                measure="TOTAL_SPILL_GB",
                key="wh_spill_total",
                drilldown_column="warehouse_name",
                lookback_hours=sp_days * 24,
            )
            for _, row in df_sp.iterrows():
                if row["REMOTE_SPILL_GB"] > 10:
                    st.error(f"**{row['WAREHOUSE_NAME']}**: {row['REMOTE_SPILL_GB']:.1f} GB remote spill - upsize immediately")
            download_csv(df_sp, "spill_report.csv")

    # -- HEATMAP ---------------------------------------------------------------
    elif warehouse_view == "Workload Heatmap":
        st.subheader("Workload Concurrency Heatmap")
        hm_days = day_window_selectbox("Lookback", key="hm_days", default=30)

        if st.button("Refresh Heatmap", key="hm_build"):
            try:
                result = load_shared_warehouse_heatmap(
                    hm_days,
                    company,
                    warehouse_contains=global_warehouse,
                    user_contains=global_user,
                    role_contains=global_role,
                    database_contains=global_database,
                    start_date=global_start_date,
                    end_date=global_end_date,
                    force=True,
                    section="Warehouse Health",
                )
                if result.message:
                    st.warning(result.message)
                st.session_state["wh_df_hm"] = result.data
                st.session_state["wh_df_hm_meta"] = _warehouse_scope_meta(company, environment, hm_days)
                st.session_state["wh_df_hm_source"] = result.source
            except Exception as e:
                st.warning(f"Workload heatmap unavailable in this role/context: {format_snowflake_error(e)}")

        if (
            st.session_state.get("wh_df_hm") is not None
            and not _warehouse_meta_matches(
                st.session_state.get("wh_df_hm_meta"),
                _warehouse_scope_meta(company, environment, hm_days),
            )
        ):
            st.info("Loaded workload heatmap is stale for the active scope. Refresh Heatmap before acting.")
        elif st.session_state.get("wh_df_hm") is not None and not st.session_state["wh_df_hm"].empty:
            df_hm = st.session_state["wh_df_hm"]
            if st.session_state.get("wh_df_hm_source"):
                defer_source_note(str(st.session_state.get("wh_df_hm_source")))
            whs = df_hm["WAREHOUSE_NAME"].unique()
            sel_wh = st.selectbox("Warehouse", whs, key="hm_wh_sel")

            if sel_wh:
                wh_data = df_hm[df_hm["WAREHOUSE_NAME"] == sel_wh]
                pivot = wh_data.pivot_table(
                    index="DAY_OF_WEEK", columns="HOUR_OF_DAY",
                    values="QUERY_COUNT", aggfunc="sum"
                ).fillna(0)
                day_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
                pivot.index = pivot.index.map(lambda x: day_names.get(int(x), str(x)))
                st.subheader(f"Query Volume Heatmap - {sel_wh}")
                st.dataframe(pivot.style.background_gradient(cmap="YlOrRd"), width="stretch")
                render_shell_snapshot((
                    ("Total Queries", f"{int(wh_data['QUERY_COUNT'].sum()):,}"),
                    ("Peak Hour", f"{int(pivot.max().max()):,}"),
                    ("Avg Elapsed", f"{wh_data['AVG_ELAPSED_SEC'].mean():.1f}s"),
                ))

    elif warehouse_view == "Optimization Advisor":
        render_optimization_advisor()
