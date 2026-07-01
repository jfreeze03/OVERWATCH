# sections/query_workbench.py - legacy root-cause helpers for Query Analysis
from __future__ import annotations

import pandas as pd
import streamlit as st

from runtime_state import set_state
from sections.shell_helpers import render_escaped_bold_text, render_shell_snapshot
from utils import (
    CortexRateLimitError,
    day_window_selectbox,
    defer_source_note,
    filter_existing_columns,
    format_snowflake_error,
    get_active_company,
    get_global_filter_clause,
    mart_object_name,
    make_action_id,
    render_query_drilldown,
    run_cortex_completion,
    run_query,
    safe_float,
    safe_int,
    sql_literal,
    upsert_actions,
)
from utils.evidence_mode import (
    TRIAGE_MODE_ALL_EVIDENCE,
    TRIAGE_MODE_INVESTIGATE,
    current_evidence_mode,
    evidence_mode_is_all_evidence,
    evidence_mode_is_investigation,
)
from utils.workflows import (
    render_load_status,
    render_priority_dataframe,
)

WORKLOAD_QUERY_WORKFLOW = "Query Investigation"
WORKLOAD_CONTENTION_WORKFLOW = "Performance & Contention"


def _root_cause_score(
    failed_queries: int,
    queued_queries: int,
    spill_queries: int,
    full_scan_queries: int,
    slow_queries: int,
    total_queries: int,
    blocked_queries: int = 0,
) -> int:
    total = max(int(total_queries or 0), 1)
    failed_pct = safe_float(failed_queries) / total * 100
    blocked_pct = safe_float(blocked_queries) / total * 100
    queue_pct = safe_float(queued_queries) / total * 100
    spill_pct = safe_float(spill_queries) / total * 100
    full_scan_pct = safe_float(full_scan_queries) / total * 100
    slow_pct = safe_float(slow_queries) / total * 100
    penalty = (
        min(failed_pct * 2.2, 30)
        + min(blocked_pct * 2.4, 28)
        + min(queue_pct * 1.8, 24)
        + min(spill_pct * 1.6, 20)
        + min(full_scan_pct * 0.8, 14)
        + min(slow_pct * 0.9, 18)
    )
    return max(0, min(100, int(round(100 - penalty))))


def _root_cause_action_for(cause: str) -> tuple[str, str, str]:
    cause = str(cause or "").upper()
    if "FAILED" in cause:
        return (
            "Query",
            "Review error code/message, recent deploys, role/database context, and retry pattern before rerun.",
            "-- Pull the failing query text and error details from QUERY_HISTORY, then validate object and role access.",
        )
    if "LOCK" in cause or "BLOCK" in cause or "CONTENTION" in cause:
        return (
            "Query/Transaction",
            "Open Contention Center, identify blocker transaction/session and shared target object, then apply the safe action contract before retrying.",
            "-- Verify TRANSACTION_BLOCKED_TIME, SHOW LOCKS, blocker owner, and post-fix blocked seconds before any compute change.",
        )
    if "QUEUE" in cause:
        return (
            "Warehouse",
            "Check warehouse load, multi-cluster settings, concurrency, and whether workload should be routed or resized.",
            "-- Review queued queries, warehouse load history, and auto-scaling settings for this warehouse.",
        )
    if "SPILL" in cause:
        return (
            "Query/Warehouse",
            "Open Query Investigation with query ID evidence, inspect join/sort/aggregate operators, then decide SQL-shape versus warehouse-memory fix.",
            "-- Use GET_QUERY_OPERATOR_STATS for the query and inspect spilled bytes by operator.",
        )
    if "SCAN" in cause:
        return (
            "Object/Query",
            "Open Query Investigation with query text and partition evidence, then validate pruning, predicate rewrite, clustering, or search optimization fit.",
            "-- Review PARTITIONS_SCANNED vs PARTITIONS_TOTAL and clustering depth for affected tables.",
        )
    if "SLOW" in cause:
        return (
            "Query",
            "Open Query Investigation with query ID evidence before choosing SQL rewrite, clustering, or warehouse changes.",
            "-- Load QUERY_HISTORY and GET_QUERY_OPERATOR_STATS before changing SQL or compute.",
        )
    return (
        "Query",
        "Open Query Investigation when query text is available; otherwise compare recurring signatures and inspect query profile.",
        "-- Review elapsed, execution, compilation, queue, scan, and spill components for this query.",
    )


def _root_cause_workflow_for(cause: str) -> str:
    cause = str(cause or "").upper()
    if "FAILED" in cause:
        return "History Search"
    if "LOCK" in cause or "BLOCK" in cause or "CONTENTION" in cause:
        return "Contention Center"
    if "QUEUE" in cause:
        return "Live Triage"
    if "SPILL" in cause or "SCAN" in cause or "SLOW" in cause:
        return "AI Diagnosis"
    return "Patterns"


def _root_cause_priority_view(exceptions: pd.DataFrame) -> pd.DataFrame:
    if exceptions is None or exceptions.empty:
        return pd.DataFrame()
    rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    view = exceptions.copy()
    view["_RANK"] = view.get("SEVERITY", pd.Series(dtype=str)).map(rank).fillna(4)
    view["ENTITY_TYPE"] = view.get("ROOT_CAUSE", pd.Series(dtype=str)).apply(lambda value: _root_cause_action_for(value)[0])
    view["NEXT_ACTION"] = view.get("ROOT_CAUSE", pd.Series(dtype=str)).apply(lambda value: _root_cause_action_for(value)[1])
    view["NEXT_WORKFLOW"] = view.get("ROOT_CAUSE", pd.Series(dtype=str)).apply(_root_cause_workflow_for)
    return view.sort_values(["_RANK", "IMPACT_VALUE"], ascending=[True, False]).drop(columns=["_RANK"], errors="ignore")


def _seed_ai_query_diagnosis_from_row(row, *, days: int) -> None:
    """Prepare AI Diagnosis with evidence already loaded from a root-cause row."""
    query_id = str(row.get("QUERY_ID") or "").strip()
    query_text = str(row.get("QUERY_TEXT") or "").strip()
    root_cause = str(row.get("ROOT_CAUSE") or "Query exception").strip()
    impact_value = safe_float(row.get("IMPACT_VALUE"))
    impact_unit = str(row.get("IMPACT_UNIT") or "").strip()
    evidence = {
        "QUERY_ID": query_id,
        "USER_NAME": str(row.get("USER_NAME") or ""),
        "ROLE_NAME": str(row.get("ROLE_NAME") or ""),
        "WAREHOUSE_NAME": str(row.get("WAREHOUSE_NAME") or ""),
        "WAREHOUSE_SIZE": str(row.get("WAREHOUSE_SIZE") or ""),
        "DATABASE_NAME": str(row.get("DATABASE_NAME") or ""),
        "SCHEMA_NAME": str(row.get("SCHEMA_NAME") or ""),
        "EXECUTION_STATUS": str(row.get("EXECUTION_STATUS") or ""),
        "START_TIME": str(row.get("START_TIME") or ""),
        "ELAPSED_SEC": safe_float(row.get("ELAPSED_SEC")),
        "COMPILE_SEC": safe_float(row.get("COMPILE_SEC")),
        "EXEC_SEC": safe_float(row.get("EXEC_SEC")),
        "QUEUED_SEC": safe_float(row.get("QUEUED_SEC")),
        "BLOCKED_SEC": safe_float(row.get("BLOCKED_SEC")),
        "BYTES_SCANNED_GB": safe_float(row.get("GB_SCANNED")),
        "REMOTE_SPILL_GB": safe_float(row.get("REMOTE_SPILL_GB")),
        "PARTITION_PCT": safe_float(row.get("PARTITION_PCT")),
        "ROWS_PRODUCED": safe_float(row.get("ROWS_PRODUCED")),
        "ERROR_MESSAGE": str(row.get("ERROR_MESSAGE") or ""),
        "OPERATOR_NOTES": (
            f"Root-Cause Brief routed {root_cause}; impact={impact_value:,.2f} {impact_unit}; "
            f"lookback_days={int(days)}. Operator stats still need to be loaded for final proof."
        ),
    }
    set_state("workload_operations_workflow", WORKLOAD_QUERY_WORKFLOW)
    st.session_state["query_analysis_active_view"] = "AI Diagnosis"
    st.session_state["ai_query_id"] = query_id
    st.session_state["ai_query_text"] = query_text
    st.session_state["ai_query_evidence"] = evidence
    st.session_state["ai_query_operator_stats"] = pd.DataFrame()
    st.session_state["ai_observed_ctx"] = evidence["OPERATOR_NOTES"]


def _render_query_watch_floor(score: int, exceptions: pd.DataFrame, summary_row: dict, days: int) -> None:
    priority = _root_cause_priority_view(exceptions).head(3)
    high_risk = 0
    if exceptions is not None and not exceptions.empty and "SEVERITY" in exceptions.columns:
        high_risk = int(exceptions["SEVERITY"].isin(["Critical", "High"]).sum())
    affected_warehouses = safe_int(summary_row.get("AFFECTED_WAREHOUSES"))
    affected_users = safe_int(summary_row.get("AFFECTED_USERS"))

    render_shell_snapshot((
        ("High-Risk Queries", f"{high_risk:,}"),
        ("Priority Queries", f"{len(priority):,}"),
        ("Affected Scope", f"{affected_warehouses:,} WH / {affected_users:,} users"),
    ))
    if priority.empty:
        st.success("No urgent query root-cause exceptions crossed the selected thresholds.")
    else:
        first = priority.iloc[0]
        st.warning(
            f"First move: {first.get('ROOT_CAUSE', 'Query exception')} on "
            f"{first.get('WAREHOUSE_NAME', 'unknown warehouse')} -> {first.get('NEXT_ACTION', 'Review query detail.')}"
        )

    st.markdown("**Query Watch Floor**")
    if priority.empty:
        st.caption("Use Live Triage for current activity, or History Search when a user brings a specific query ID.")
        return

    cols = st.columns(len(priority))
    for idx, (_, item) in enumerate(priority.iterrows()):
        workflow = str(item.get("NEXT_WORKFLOW") or "Diagnosis")
        query_id = str(item.get("QUERY_ID") or "")
        warehouse = str(item.get("WAREHOUSE_NAME") or "")
        root_cause = str(item.get("ROOT_CAUSE") or "")
        with cols[idx]:
            render_escaped_bold_text(f"{item.get('SEVERITY', 'Medium')}: {item.get('ROOT_CAUSE', '')}")
            st.caption(f"{item.get('QUERY_ID', '')} | {item.get('WAREHOUSE_NAME', 'unknown warehouse')}")
            st.caption(f"Impact: {safe_float(item.get('IMPACT_VALUE')):,.2f} {item.get('IMPACT_UNIT', '')}")
            next_action = str(item.get("NEXT_ACTION", "") or "")
            if st.button(
                f"Open {workflow}",
                key=f"qw_watch_floor_{idx}_{workflow}",
                help=next_action or None,
                width="stretch",
            ):
                if warehouse:
                    st.session_state["global_warehouse"] = warehouse
                    st.session_state["lm_wh"] = warehouse
                    st.session_state["wh_filter"] = warehouse
                if workflow == "History Search" and query_id:
                    st.session_state["qs_text"] = query_id
                    st.session_state["qs_status"] = "ALL"
                    st.session_state["qs_days"] = min(max(int(days), 1), 30)
                    st.session_state["qs_autorun"] = True
                    set_state("workload_operations_workflow", WORKLOAD_QUERY_WORKFLOW)
                    st.session_state["query_analysis_active_view"] = "History Search"
                elif workflow == "Contention Center":
                    set_state("workload_operations_workflow", WORKLOAD_CONTENTION_WORKFLOW)
                    st.session_state["contention_focus_query_id"] = query_id
                    st.session_state["contention_center_view"] = "Brief"
                    st.session_state["contention_active_view"] = "Brief"
                elif workflow == "AI Diagnosis":
                    _seed_ai_query_diagnosis_from_row(item, days=days)
                elif workflow == "Diagnosis":
                    mode = "Execution Time"
                    if "QUEUE" in root_cause.upper():
                        mode = "Queued Overload"
                    elif "SPILL" in root_cause.upper():
                        mode = "Remote Spill"
                    elif "SCAN" in root_cause.upper():
                        mode = "Bytes Scanned"
                    st.session_state["dd_mode"] = mode
                    st.session_state["dd_days"] = min(max(int(days), 1), 30)
                    st.session_state["dd_focus_query_id"] = query_id
                    st.session_state["query_analysis_active_view"] = "Detailed Diagnosis"
                    set_state("workload_operations_workflow", WORKLOAD_QUERY_WORKFLOW)
                elif workflow == "Patterns":
                    st.session_state["query_analysis_active_view"] = "Pattern Degradation"
                    set_state("workload_operations_workflow", WORKLOAD_QUERY_WORKFLOW)
                elif workflow == "History Search":
                    set_state("workload_operations_workflow", WORKLOAD_QUERY_WORKFLOW)
                    st.session_state["query_analysis_active_view"] = "History Search"
                elif workflow == "Live Triage":
                    set_state("workload_operations_workflow", WORKLOAD_CONTENTION_WORKFLOW)
                st.rerun()


def _build_root_cause_markdown(
    company: str,
    days: int,
    score: int,
    summary_row: dict,
    exceptions: pd.DataFrame,
) -> str:
    lines = [
        f"# OVERWATCH Query Root-Cause Brief - {company}",
        "",
        f"- Lookback: {days} days",
        f"- Total queries: {safe_int(summary_row.get('TOTAL_QUERIES')):,}",
        f"- Failed queries: {safe_int(summary_row.get('FAILED_QUERIES')):,}",
        f"- Blocked queries: {safe_int(summary_row.get('BLOCKED_QUERIES')):,}",
        f"- Queued queries: {safe_int(summary_row.get('QUEUED_QUERIES')):,}",
        f"- Spill queries: {safe_int(summary_row.get('SPILL_QUERIES')):,}",
        f"- Full-scan candidates: {safe_int(summary_row.get('FULL_SCAN_QUERIES')):,}",
        "",
        "## DBA Narrative",
        (
            "Use this brief as the first-pass triage view before opening query analysis drilldowns. "
            "It separates failure, queue, memory spill, full-scan, and slow-query pressure so the DBA can "
            "route the issue to warehouse capacity, SQL tuning, access fixes, or deployment rollback."
        ),
        "",
        "## Top Exceptions",
    ]
    if exceptions is None or exceptions.empty:
        lines.append("- No root-cause exceptions found for the selected scope.")
    else:
        for _, row in exceptions.head(10).iterrows():
            lines.append(
                "- "
                f"{row.get('SEVERITY', 'Watch')} | {row.get('ROOT_CAUSE', 'Unknown')} | "
                f"{row.get('QUERY_ID', '')} | {row.get('WAREHOUSE_NAME', '')} | "
                f"{safe_float(row.get('IMPACT_VALUE')):,.2f} {row.get('IMPACT_UNIT', '')}"
            )
    lines.extend([
        "",
        "## Evidence Limits",
        "- QUERY_HISTORY can lag in ACCOUNT_USAGE; use Live Triage for currently running statements.",
        "- Per-query root cause is inferred from available query-history counters, not from full query profile operators.",
        "- Company scope follows configured warehouse/database/user naming rules.",
    ])
    return "\n".join(lines)


def _root_cause_cortex_prompt(
    company: str,
    days: int,
    score: int,
    summary_row: dict,
    exceptions: pd.DataFrame,
) -> str:
    """Build a bounded Cortex prompt from loaded root-cause evidence."""
    top = _root_cause_priority_view(exceptions).head(5)
    evidence_lines = []
    for _, row in top.iterrows():
        evidence_lines.append(
            "- "
            f"severity={row.get('SEVERITY', 'Medium')}; "
            f"root_cause={row.get('ROOT_CAUSE', 'Unknown')}; "
            f"query_id={row.get('QUERY_ID', '')}; "
            f"warehouse={row.get('WAREHOUSE_NAME', '')}; "
            f"database={row.get('DATABASE_NAME', '')}; "
            f"schema={row.get('SCHEMA_NAME', '')}; "
            f"elapsed_sec={safe_float(row.get('ELAPSED_SEC')):.2f}; "
            f"queued_sec={safe_float(row.get('QUEUED_SEC')):.2f}; "
            f"blocked_sec={safe_float(row.get('BLOCKED_SEC')):.2f}; "
            f"remote_spill_gb={safe_float(row.get('REMOTE_SPILL_GB')):.2f}; "
            f"gb_scanned={safe_float(row.get('GB_SCANNED')):.2f}; "
            f"partition_pct={safe_float(row.get('PARTITION_PCT')):.2f}; "
            f"next_action={row.get('NEXT_ACTION', '')}"
        )
    if not evidence_lines:
        evidence_lines.append("- No root-cause exceptions crossed the configured thresholds.")

    root_cause_state = "Escalate" if score < 70 else "Review" if score < 85 else "Watch"
    return "\n".join([
        "You are OVERWATCH, a Snowflake DBA monitoring assistant.",
        "Use only the evidence below. Do not invent tables, users, tickets, or causes.",
        "Write exactly 3 concise sentences for a DBA: likely root cause, evidence, and single best next action.",
        "",
        f"Scope: company={company}; lookback_days={int(days)}; root-cause state: {root_cause_state}.",
        (
            "Summary: "
            f"total_queries={safe_int(summary_row.get('TOTAL_QUERIES'))}; "
            f"failed={safe_int(summary_row.get('FAILED_QUERIES'))}; "
            f"blocked={safe_int(summary_row.get('BLOCKED_QUERIES'))}; "
            f"queued={safe_int(summary_row.get('QUEUED_QUERIES'))}; "
            f"spill={safe_int(summary_row.get('SPILL_QUERIES'))}; "
            f"full_scan={safe_int(summary_row.get('FULL_SCAN_QUERIES'))}; "
            f"slow={safe_int(summary_row.get('SLOW_QUERIES'))}; "
            f"affected_warehouses={safe_int(summary_row.get('AFFECTED_WAREHOUSES'))}; "
            f"affected_users={safe_int(summary_row.get('AFFECTED_USERS'))}."
        ),
        "Top loaded exceptions:",
        *evidence_lines,
    ])


def _generate_root_cause_cortex_narrative(session, prompt: str) -> str:
    """Run one Cortex completion for a loaded root-cause brief."""
    return run_cortex_completion(
        session,
        prompt,
        alias="NARRATIVE",
        prompt_limit=16000,
        feature="query_workbench_root_cause",
    )


def _build_root_cause_sql(session, days: int, limit: int) -> tuple[str, str]:
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "WAREHOUSE_SIZE",
            "ERROR_CODE",
            "ERROR_MESSAGE",
            "COMPILATION_TIME",
            "EXECUTION_TIME",
            "QUEUED_OVERLOAD_TIME",
            "QUEUED_PROVISIONING_TIME",
            "QUEUED_REPAIR_TIME",
            "TRANSACTION_BLOCKED_TIME",
            "BYTES_SCANNED",
            "BYTES_SPILLED_TO_LOCAL_STORAGE",
            "BYTES_SPILLED_TO_REMOTE_STORAGE",
            "PARTITIONS_SCANNED",
            "PARTITIONS_TOTAL",
            "ROWS_PRODUCED",
            "QUERY_HASH",
        ],
    ))
    filters = get_global_filter_clause(
        date_col="q.start_time",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
        schema_col="q.schema_name",
    )

    def col_expr(name: str, default: str = "0") -> str:
        return f"q.{name.lower()}" if name.upper() in qh_cols else default

    warehouse_size_expr = col_expr("WAREHOUSE_SIZE", "NULL::VARCHAR")
    error_code_expr = col_expr("ERROR_CODE", "NULL::VARCHAR")
    error_message_expr = col_expr("ERROR_MESSAGE", "NULL::VARCHAR")
    compile_expr = col_expr("COMPILATION_TIME", "0")
    exec_expr = col_expr("EXECUTION_TIME", "0")
    queue_expr = " + ".join([
        col_expr("QUEUED_OVERLOAD_TIME", "0"),
        col_expr("QUEUED_PROVISIONING_TIME", "0"),
        col_expr("QUEUED_REPAIR_TIME", "0"),
    ])
    blocked_expr = col_expr("TRANSACTION_BLOCKED_TIME", "0")
    bytes_scanned_expr = col_expr("BYTES_SCANNED", "0")
    local_spill_expr = col_expr("BYTES_SPILLED_TO_LOCAL_STORAGE", "0")
    remote_spill_expr = col_expr("BYTES_SPILLED_TO_REMOTE_STORAGE", "0")
    rows_expr = col_expr("ROWS_PRODUCED", "0")
    partition_pct_expr = (
        "q.partitions_scanned * 100.0 / NULLIF(q.partitions_total, 0)"
        if {"PARTITIONS_SCANNED", "PARTITIONS_TOTAL"}.issubset(qh_cols)
        else "0::FLOAT"
    )
    query_hash_expr = col_expr("QUERY_HASH", "NULL::VARCHAR")

    base = f"""
        WITH base AS (
            SELECT
                q.query_id,
                {query_hash_expr} AS query_hash,
                q.user_name,
                q.role_name,
                q.warehouse_name,
                {warehouse_size_expr} AS warehouse_size,
                q.database_name,
                q.schema_name,
                q.query_type,
                q.execution_status,
                {error_code_expr} AS error_code,
                {error_message_expr} AS error_message,
                q.start_time,
                q.total_elapsed_time / 1000.0 AS elapsed_sec,
                {compile_expr} / 1000.0 AS compile_sec,
                {exec_expr} / 1000.0 AS exec_sec,
                ({queue_expr}) / 1000.0 AS queued_sec,
                {blocked_expr} / 1000.0 AS blocked_sec,
                {bytes_scanned_expr} / POWER(1024, 3) AS gb_scanned,
                {local_spill_expr} / POWER(1024, 3) AS local_spill_gb,
                {remote_spill_expr} / POWER(1024, 3) AS remote_spill_gb,
                {rows_expr} AS rows_produced,
                {partition_pct_expr} AS partition_pct,
                SUBSTR(q.query_text, 1, 4000) AS query_text
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {filters}
        )
    """
    summary_sql = f"""
        {base}
        SELECT
            COUNT(*) AS total_queries,
            SUM(IFF(UPPER(execution_status) = 'FAILED_WITH_ERROR', 1, 0)) AS failed_queries,
            SUM(IFF(blocked_sec >= 5, 1, 0)) AS blocked_queries,
            SUM(IFF(elapsed_sec >= 30, 1, 0)) AS slow_queries,
            SUM(IFF(queued_sec > 0, 1, 0)) AS queued_queries,
            SUM(IFF(local_spill_gb > 0 OR remote_spill_gb > 0, 1, 0)) AS spill_queries,
            SUM(IFF(partition_pct >= 90, 1, 0)) AS full_scan_queries,
            COUNT(DISTINCT warehouse_name) AS affected_warehouses,
            COUNT(DISTINCT user_name) AS affected_users,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY elapsed_sec) AS p95_elapsed_sec,
            MAX(queued_sec) AS max_queued_sec,
            SUM(remote_spill_gb) AS total_remote_spill_gb,
            SUM(gb_scanned) AS total_gb_scanned
        FROM base
    """
    exceptions_sql = f"""
        {base},
        scored AS (
            SELECT *,
                CASE
                    WHEN UPPER(execution_status) = 'FAILED_WITH_ERROR' THEN 'Failed Query'
                    WHEN blocked_sec >= 5 THEN 'Lock Contention'
                    WHEN queued_sec >= 30 THEN 'Warehouse Queue'
                    WHEN remote_spill_gb >= 1 THEN 'Remote Spill'
                    WHEN partition_pct >= 90 AND gb_scanned >= 10 THEN 'Full Scan'
                    WHEN elapsed_sec >= 30 THEN 'Slow Query'
                    ELSE 'Watch'
                END AS root_cause,
                CASE
                    WHEN UPPER(execution_status) = 'FAILED_WITH_ERROR' THEN 1000000 + elapsed_sec
                    WHEN blocked_sec >= 5 THEN blocked_sec
                    WHEN queued_sec >= 30 THEN queued_sec
                    WHEN remote_spill_gb >= 1 THEN remote_spill_gb
                    WHEN partition_pct >= 90 AND gb_scanned >= 10 THEN gb_scanned
                    ELSE elapsed_sec
                END AS impact_value,
                CASE
                    WHEN UPPER(execution_status) = 'FAILED_WITH_ERROR' THEN 'error'
                    WHEN blocked_sec >= 5 THEN 'seconds blocked'
                    WHEN queued_sec >= 30 THEN 'seconds queued'
                    WHEN remote_spill_gb >= 1 THEN 'GB remote spill'
                    WHEN partition_pct >= 90 AND gb_scanned >= 10 THEN 'GB scanned'
                    ELSE 'seconds elapsed'
                END AS impact_unit
            FROM base
            WHERE UPPER(execution_status) = 'FAILED_WITH_ERROR'
               OR blocked_sec >= 5
               OR queued_sec >= 30
               OR remote_spill_gb >= 1
               OR (partition_pct >= 90 AND gb_scanned >= 10)
               OR elapsed_sec >= 30
        )
        SELECT
            CASE
                WHEN root_cause = 'Failed Query' THEN 'High'
                WHEN root_cause = 'Lock Contention' AND impact_value >= 30 THEN 'Critical'
                WHEN root_cause = 'Lock Contention' THEN 'High'
                WHEN root_cause IN ('Warehouse Queue', 'Remote Spill') AND impact_value >= 60 THEN 'Critical'
                WHEN root_cause IN ('Warehouse Queue', 'Remote Spill') THEN 'High'
                WHEN root_cause = 'Full Scan' AND impact_value >= 100 THEN 'High'
                ELSE 'Medium'
            END AS severity,
            root_cause,
            query_id,
            query_hash,
            user_name,
            role_name,
            warehouse_name,
            warehouse_size,
            database_name,
            schema_name,
            query_type,
            execution_status,
            error_code,
            error_message,
            start_time,
            elapsed_sec,
            exec_sec,
            compile_sec,
            queued_sec,
            blocked_sec,
            gb_scanned,
            local_spill_gb,
            remote_spill_gb,
            rows_produced,
            partition_pct,
            impact_value,
            impact_unit,
            query_text
        FROM scored
        ORDER BY
            CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 ELSE 3 END,
            impact_value DESC
        LIMIT {int(limit)}
    """
    return summary_sql, exceptions_sql


def _build_mart_root_cause_sql(days: int, limit: int, company: str) -> tuple[str, str]:
    """Build root-cause brief SQL from OVERWATCH fast summary facts."""
    hourly = mart_object_name("FACT_QUERY_HOURLY")
    detail = mart_object_name("FACT_QUERY_DETAIL_RECENT")
    company_filter = "" if str(company or "").upper() == "ALL" else f"AND company = {sql_literal(company, 100)}"
    hourly_filters = get_global_filter_clause(
        date_col="hour_start",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
        schema_col="schema_name",
    )
    detail_filters = get_global_filter_clause(
        date_col="start_time",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
        schema_col="schema_name",
    )
    summary_sql = f"""
        WITH hourly_summary AS (
            SELECT
                COALESCE(SUM(query_count), 0) AS total_queries,
                COALESCE(SUM(failed_count), 0) AS failed_queries,
                COALESCE(SUM(IFF(p95_execution_ms >= 30000, query_count, 0)), 0) AS slow_queries,
                COALESCE(SUM(IFF(total_queued_ms > 0, query_count, 0)), 0) AS queued_queries,
                COALESCE(SUM(IFF(total_spill_bytes > 0, query_count, 0)), 0) AS spill_queries,
                COUNT(DISTINCT warehouse_name) AS affected_warehouses,
                COUNT(DISTINCT user_name) AS affected_users,
                MAX(p95_execution_ms) / 1000.0 AS p95_elapsed_sec,
                MAX(total_queued_ms) / 1000.0 AS max_queued_sec,
                SUM(total_spill_bytes) / POWER(1024, 3) AS total_remote_spill_gb,
                SUM(total_bytes_scanned) / POWER(1024, 3) AS total_gb_scanned
            FROM {hourly}
            WHERE hour_start >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
              {company_filter}
              AND warehouse_name IS NOT NULL
              {hourly_filters}
        ),
        detail_summary AS (
            SELECT
                COUNT_IF(
                    COALESCE(partitions_total, 0) > 0
                    AND partitions_scanned * 100.0 / NULLIF(partitions_total, 0) >= 90
                    AND COALESCE(bytes_scanned, 0) / POWER(1024, 3) >= 10
                ) AS full_scan_queries,
                COUNT_IF(COALESCE(transaction_blocked_time, 0) / 1000.0 >= 5) AS blocked_queries
            FROM {detail}
            WHERE start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
              {company_filter}
              AND warehouse_name IS NOT NULL
              {detail_filters}
        )
        SELECT
            h.total_queries,
            h.failed_queries,
            COALESCE(d.blocked_queries, 0) AS blocked_queries,
            h.slow_queries,
            h.queued_queries,
            h.spill_queries,
            COALESCE(d.full_scan_queries, 0) AS full_scan_queries,
            h.affected_warehouses,
            h.affected_users,
            h.p95_elapsed_sec,
            h.max_queued_sec,
            h.total_remote_spill_gb,
            h.total_gb_scanned
        FROM hourly_summary h, detail_summary d
    """
    exceptions_sql = f"""
        WITH base AS (
            SELECT
                query_id,
                query_hash,
                user_name,
                role_name,
                warehouse_name,
                warehouse_size,
                database_name,
                schema_name,
                query_type,
                execution_status,
                error_code,
                error_message,
                start_time,
                total_elapsed_time / 1000.0 AS elapsed_sec,
                compilation_time / 1000.0 AS compile_sec,
                execution_time / 1000.0 AS exec_sec,
                (
                    COALESCE(queued_overload_time, 0)
                    + COALESCE(queued_provisioning_time, 0)
                    + COALESCE(queued_repair_time, 0)
                ) / 1000.0 AS queued_sec,
                transaction_blocked_time / 1000.0 AS blocked_sec,
                COALESCE(bytes_scanned, 0) / POWER(1024, 3) AS gb_scanned,
                COALESCE(bytes_spilled_to_local_storage, 0) / POWER(1024, 3) AS local_spill_gb,
                COALESCE(bytes_spilled_to_remote_storage, 0) / POWER(1024, 3) AS remote_spill_gb,
                rows_produced,
                partitions_scanned * 100.0 / NULLIF(partitions_total, 0) AS partition_pct,
                SUBSTR(query_text, 1, 4000) AS query_text
            FROM {detail}
            WHERE start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
              {company_filter}
              AND warehouse_name IS NOT NULL
              {detail_filters}
        ),
        scored AS (
            SELECT *,
                CASE
                    WHEN UPPER(COALESCE(execution_status, '')) IN ('FAILED_WITH_ERROR', 'FAILED') THEN 'Failed Query'
                    WHEN blocked_sec >= 5 THEN 'Lock Contention'
                    WHEN queued_sec >= 30 THEN 'Warehouse Queue'
                    WHEN remote_spill_gb >= 1 THEN 'Remote Spill'
                    WHEN partition_pct >= 90 AND gb_scanned >= 10 THEN 'Full Scan'
                    WHEN elapsed_sec >= 30 THEN 'Slow Query'
                    ELSE 'Watch'
                END AS root_cause,
                CASE
                    WHEN UPPER(COALESCE(execution_status, '')) IN ('FAILED_WITH_ERROR', 'FAILED') THEN 1000000 + elapsed_sec
                    WHEN blocked_sec >= 5 THEN blocked_sec
                    WHEN queued_sec >= 30 THEN queued_sec
                    WHEN remote_spill_gb >= 1 THEN remote_spill_gb
                    WHEN partition_pct >= 90 AND gb_scanned >= 10 THEN gb_scanned
                    ELSE elapsed_sec
                END AS impact_value,
                CASE
                    WHEN UPPER(COALESCE(execution_status, '')) IN ('FAILED_WITH_ERROR', 'FAILED') THEN 'error'
                    WHEN blocked_sec >= 5 THEN 'seconds blocked'
                    WHEN queued_sec >= 30 THEN 'seconds queued'
                    WHEN remote_spill_gb >= 1 THEN 'GB remote spill'
                    WHEN partition_pct >= 90 AND gb_scanned >= 10 THEN 'GB scanned'
                    ELSE 'seconds elapsed'
                END AS impact_unit
            FROM base
            WHERE UPPER(COALESCE(execution_status, '')) IN ('FAILED_WITH_ERROR', 'FAILED')
               OR blocked_sec >= 5
               OR queued_sec >= 30
               OR remote_spill_gb >= 1
               OR (partition_pct >= 90 AND gb_scanned >= 10)
               OR elapsed_sec >= 30
        )
        SELECT
            CASE
                WHEN root_cause = 'Failed Query' THEN 'High'
                WHEN root_cause = 'Lock Contention' AND impact_value >= 30 THEN 'Critical'
                WHEN root_cause = 'Lock Contention' THEN 'High'
                WHEN root_cause IN ('Warehouse Queue', 'Remote Spill') AND impact_value >= 60 THEN 'Critical'
                WHEN root_cause IN ('Warehouse Queue', 'Remote Spill') THEN 'High'
                WHEN root_cause = 'Full Scan' AND impact_value >= 250 THEN 'High'
                ELSE 'Medium'
            END AS severity,
            root_cause,
            query_id,
            query_hash,
            user_name,
            role_name,
            warehouse_name,
            warehouse_size,
            database_name,
            schema_name,
            query_type,
            execution_status,
            error_code,
            error_message,
            start_time,
            elapsed_sec,
            exec_sec,
            compile_sec,
            queued_sec,
            blocked_sec,
            gb_scanned,
            local_spill_gb,
            remote_spill_gb,
            rows_produced,
            partition_pct,
            impact_value,
            impact_unit,
            query_text
        FROM scored
        ORDER BY
            CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 ELSE 3 END,
            impact_value DESC
        LIMIT {int(limit)}
    """
    return summary_sql, exceptions_sql


def _queue_root_cause_actions(session, exceptions: pd.DataFrame) -> int:
    if exceptions is None or exceptions.empty:
        return 0
    company = get_active_company()
    actions = []
    for _, row in exceptions.head(50).iterrows():
        qid = str(row.get("QUERY_ID", ""))
        cause = str(row.get("ROOT_CAUSE", "Query Exception"))
        entity_type, action_text, generated_sql = _root_cause_action_for(cause)
        warehouse = str(row.get("WAREHOUSE_NAME", "UNKNOWN"))
        user = str(row.get("USER_NAME", "UNKNOWN"))
        finding = (
            f"{cause} on {warehouse}: {safe_float(row.get('IMPACT_VALUE')):,.2f} "
            f"{row.get('IMPACT_UNIT', '')}; query_id={qid}."
        )
        actions.append({
            "Action ID": make_action_id("Query Root Cause", qid or warehouse, finding),
            "Source": "Query Analysis - Root Cause",
            "Category": "Query Performance",
            "Severity": row.get("SEVERITY", "High"),
            "Entity Type": entity_type,
            "Entity": qid or warehouse,
            "Owner": user or "DBA",
            "Finding": finding,
            "Action": action_text,
            "Estimated Monthly Savings": 0,
            "Generated SQL Fix": generated_sql,
            "Proof Query": (
                "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY "
                f"WHERE query_id = '{qid}';"
            ),
            "Company": company,
        })
    return upsert_actions(session, actions)


def render_root_cause_brief(session) -> None:
    company = get_active_company()
    evidence_mode = current_evidence_mode(st.session_state)
    investigation_mode = evidence_mode_is_investigation(st.session_state)
    all_evidence_mode = evidence_mode_is_all_evidence(st.session_state)
    default_limit = 100
    if evidence_mode == TRIAGE_MODE_INVESTIGATE:
        default_limit = 150
    elif evidence_mode == TRIAGE_MODE_ALL_EVIDENCE:
        default_limit = 250
    with st.expander("Root-Cause Brief", expanded=bool(st.session_state.get("exceptions_only_mode") or investigation_mode)):
        c1, c2 = st.columns([1, 1])
        with c1:
            days = day_window_selectbox("Root-cause lookback", key="qw_rc_days", default=7)
        with c2:
            limit = st.slider("Exception rows", 25, 250, default_limit, step=25, key="qw_rc_limit")

        if st.button("Load Root-Cause Brief", key="qw_rc_load"):
            with render_load_status("Building root-cause brief", "Root-cause brief ready"):
                try:
                    summary_sql, exceptions_sql = _build_mart_root_cause_sql(days, limit, company)
                    summary_df = run_query(
                        summary_sql,
                        ttl_key=f"qw_root_summary_mart_{company}_{days}",
                        tier="historical",
                        section="Query Analysis",
                    )
                    exceptions = run_query(
                        exceptions_sql,
                        ttl_key=f"qw_root_exceptions_mart_{company}_{days}_{limit}",
                        tier="historical",
                        section="Query Analysis",
                    )
                    st.session_state["qw_root_summary"] = summary_df
                    st.session_state["qw_root_exceptions"] = exceptions
                    st.session_state["qw_root_sql"] = {
                        "summary": summary_sql,
                        "exceptions": exceptions_sql,
                    }
                    st.session_state["qw_root_meta"] = {
                        "company": company,
                        "days": int(days),
                        "limit": int(limit),
                        "source": "Fast root-cause summary",
                    }
                except Exception as e:
                    try:
                        summary_sql, exceptions_sql = _build_root_cause_sql(session, days, limit)
                        summary_df = run_query(
                            summary_sql,
                            ttl_key=f"qw_root_summary_live_{company}_{days}",
                            tier="historical",
                            section="Query Analysis",
                        )
                        exceptions = run_query(
                            exceptions_sql,
                            ttl_key=f"qw_root_exceptions_live_{company}_{days}_{limit}",
                            tier="historical",
                            section="Query Analysis",
                        )
                        st.session_state["qw_root_summary"] = summary_df
                        st.session_state["qw_root_exceptions"] = exceptions
                        st.session_state["qw_root_sql"] = {
                            "summary": summary_sql,
                            "exceptions": exceptions_sql,
                        }
                        st.session_state["qw_root_meta"] = {
                            "company": company,
                            "days": int(days),
                            "limit": int(limit),
                            "source": "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                        }
                        st.info(f"Fast query summary unavailable; used live QUERY_HISTORY fallback. {format_snowflake_error(e)}")
                    except Exception as live_exc:
                        st.warning(f"Root-cause brief unavailable: {format_snowflake_error(live_exc)}")

        summary_df = st.session_state.get("qw_root_summary")
        exceptions = st.session_state.get("qw_root_exceptions")
        meta = st.session_state.get("qw_root_meta", {})
        if (
            summary_df is None
            or summary_df.empty
            or meta.get("company") != company
            or meta.get("days") != int(days)
            or meta.get("limit") != int(limit)
        ):
            return

        summary_row = summary_df.iloc[0].to_dict()
        score = _root_cause_score(
            failed_queries=safe_int(summary_row.get("FAILED_QUERIES")),
            blocked_queries=safe_int(summary_row.get("BLOCKED_QUERIES")),
            queued_queries=safe_int(summary_row.get("QUEUED_QUERIES")),
            spill_queries=safe_int(summary_row.get("SPILL_QUERIES")),
            full_scan_queries=safe_int(summary_row.get("FULL_SCAN_QUERIES")),
            slow_queries=safe_int(summary_row.get("SLOW_QUERIES")),
            total_queries=safe_int(summary_row.get("TOTAL_QUERIES")),
        )
        render_shell_snapshot((
            ("Failed", f"{safe_int(summary_row.get('FAILED_QUERIES')):,}"),
            ("Blocked", f"{safe_int(summary_row.get('BLOCKED_QUERIES')):,}"),
            ("Queued", f"{safe_int(summary_row.get('QUEUED_QUERIES')):,}"),
            ("Spill", f"{safe_int(summary_row.get('SPILL_QUERIES')):,}"),
            ("Full Scan", f"{safe_int(summary_row.get('FULL_SCAN_QUERIES')):,}"),
        ))

        if score < 65:
            st.error("Incident risk: query failures, queue pressure, spill, or scan-heavy workload needs DBA action.")
        elif score < 78:
            st.warning("Degraded: review the top exceptions before handing this off as normal workload.")
        elif score < 90:
            st.info("Watch: a few exceptions exist, but the query estate is broadly controlled.")
        else:
            st.success("Stable: no dominant query root-cause pressure in the selected scope.")
        defer_source_note(meta.get("source", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"))

        _render_query_watch_floor(score, exceptions, summary_row, days)
        st.divider()

        if exceptions is not None and not exceptions.empty:
            st.subheader("Top Query Exceptions")
            render_priority_dataframe(
                exceptions,
                title="Query exceptions to diagnose first",
                priority_columns=[
                    "SEVERITY", "ROOT_CAUSE", "QUERY_ID", "USER_NAME",
                    "WAREHOUSE_NAME", "DATABASE_NAME", "ELAPSED_SEC",
                    "BLOCKED_SEC", "QUEUED_SEC", "GB_SCANNED", "REMOTE_SPILL_GB",
                    "NEXT_ACTION",
                ],
                sort_by=["BLOCKED_SEC", "ELAPSED_SEC", "QUEUED_SEC", "GB_SCANNED", "REMOTE_SPILL_GB"],
                ascending=[False, False, False, False, False],
                raw_label="All query root-cause exceptions",
            )
            if st.button("Save Root-Cause Exceptions to Action Queue", key="qw_rc_queue"):
                try:
                    saved = _queue_root_cause_actions(session, exceptions)
                    st.success(f"Saved {saved} root-cause findings to the action queue.")
                except Exception as e:
                    st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
                    st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")
            narrative_meta = {
                "company": company,
                "days": int(days),
                "limit": int(limit),
                "score": int(score),
                "top_query": str(exceptions.iloc[0].get("QUERY_ID", "")) if not exceptions.empty else "",
            }
            with st.expander("Cortex Root-Cause Narrative", expanded=evidence_mode == TRIAGE_MODE_INVESTIGATE):
                if st.button(
                    "Generate Cortex Root-Cause Narrative",
                    key="qw_rc_cortex_narrative",
                    help=(
                        "Runs one Cortex completion against the loaded root-cause evidence. "
                        "The request is throttled and identical evidence reuses the cached answer; telemetry stores "
                        "feature, timing, and prompt hash only, not prompt text."
                    ),
                    width="stretch",
                ):
                    prompt = _root_cause_cortex_prompt(company, days, score, summary_row, exceptions)
                    try:
                        with render_load_status("Generating DBA root-cause narrative", "DBA root-cause narrative ready"):
                            st.session_state["qw_root_cortex_narrative"] = _generate_root_cause_cortex_narrative(
                                session,
                                prompt,
                            )
                            st.session_state["qw_root_cortex_meta"] = narrative_meta
                    except CortexRateLimitError as e:
                        st.info(format_snowflake_error(e))
                    except Exception as e:
                        st.info(
                            "Cortex root-cause narrative unavailable. "
                            f"{format_snowflake_error(e)} Ensure Cortex functions are enabled in this account."
                        )
                if (
                    st.session_state.get("qw_root_cortex_narrative")
                    and st.session_state.get("qw_root_cortex_meta") == narrative_meta
                ):
                    st.markdown(st.session_state["qw_root_cortex_narrative"])
            render_query_drilldown(exceptions, key="qw_root_cause_drilldown", title="Root-Cause Query Drilldown")
        else:
            st.success("No query root-cause exceptions found for this scope.")

        st.download_button(
            "Download Query Root-Cause Brief",
            _build_root_cause_markdown(company, days, score, summary_row, exceptions),
            file_name=f"overwatch_query_root_cause_{company.lower()}.md",
            mime="text/markdown",
            key="qw_rc_download",
        )
        with st.expander("Telemetry Status", expanded=all_evidence_mode):
            render_shell_snapshot((
                ("Summary telemetry", "Ready after refresh"),
                ("Exception telemetry", "Ready after refresh"),
                ("Route review", "Required"),
                ("Execution", "Runbook only"),
            ))


def _render_root_cause_brief(session) -> None:
    render_root_cause_brief(session)


def render() -> None:
    """Compatibility entry point for old imports; route users to Query Analysis."""
    st.session_state["query_analysis_active_view"] = "Root-Cause Brief"
    import importlib

    query_analysis = importlib.import_module("sections.query_analysis")
    query_analysis.render()
