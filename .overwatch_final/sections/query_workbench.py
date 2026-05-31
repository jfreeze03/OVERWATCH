# sections/query_workbench.py - Consolidated query investigation workflow
from __future__ import annotations

import pandas as pd
import streamlit as st

from sections import detailed_diagnosis, live_monitor, query_analysis, query_search
from utils import (
    filter_existing_columns,
    format_snowflake_error,
    get_active_company,
    get_global_filter_clause,
    get_session,
    mart_object_name,
    make_action_id,
    render_query_drilldown,
    run_query,
    safe_float,
    safe_int,
    sql_literal,
    upsert_actions,
)
from utils.workflows import (
    render_priority_dataframe,
    render_signal_confidence,
    render_workflow_guide,
    render_workflow_selector,
)

WORKFLOWS = (
    "Live Triage",
    "Diagnosis",
    "Patterns",
    "History Search",
)


def _root_cause_score(
    failed_queries: int,
    queued_queries: int,
    spill_queries: int,
    full_scan_queries: int,
    slow_queries: int,
    total_queries: int,
) -> int:
    total = max(int(total_queries or 0), 1)
    failed_pct = safe_float(failed_queries) / total * 100
    queue_pct = safe_float(queued_queries) / total * 100
    spill_pct = safe_float(spill_queries) / total * 100
    full_scan_pct = safe_float(full_scan_queries) / total * 100
    slow_pct = safe_float(slow_queries) / total * 100
    penalty = (
        min(failed_pct * 2.2, 30)
        + min(queue_pct * 1.8, 24)
        + min(spill_pct * 1.6, 20)
        + min(full_scan_pct * 0.8, 14)
        + min(slow_pct * 0.9, 18)
    )
    return max(0, min(100, int(round(100 - penalty))))


def _root_cause_rating(score: int) -> str:
    if score >= 90:
        return "Stable"
    if score >= 78:
        return "Watch"
    if score >= 65:
        return "Degraded"
    return "Incident Risk"


def _root_cause_action_for(cause: str) -> tuple[str, str, str]:
    cause = str(cause or "").upper()
    if "FAILED" in cause:
        return (
            "Query",
            "Review error code/message, recent deploys, role/database context, and retry pattern before rerun.",
            "-- Pull the failing query text and error details from QUERY_HISTORY, then validate object and role access.",
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
            "Inspect join/order/group operators and warehouse size; remote spill usually means memory pressure or large reshuffle.",
            "-- Use GET_QUERY_OPERATOR_STATS for the query and inspect spilled bytes by operator.",
        )
    if "SCAN" in cause:
        return (
            "Object/Query",
            "Check pruning, clustering, filters, search optimization, and whether the query is scanning avoidable partitions.",
            "-- Review PARTITIONS_SCANNED vs PARTITIONS_TOTAL and clustering depth for affected tables.",
        )
    return (
        "Query",
        "Open the detailed diagnosis row, compare recurring signatures, and inspect query profile.",
        "-- Review elapsed, execution, compilation, queue, scan, and spill components for this query.",
    )


def _root_cause_workflow_for(cause: str) -> str:
    cause = str(cause or "").upper()
    if "FAILED" in cause:
        return "History Search"
    if "QUEUE" in cause:
        return "Live Triage"
    if "SPILL" in cause or "SCAN" in cause or "SLOW" in cause:
        return "Diagnosis"
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


def _render_query_watch_floor(score: int, exceptions: pd.DataFrame, summary_row: dict, days: int) -> None:
    priority = _root_cause_priority_view(exceptions).head(3)
    high_risk = 0
    if exceptions is not None and not exceptions.empty and "SEVERITY" in exceptions.columns:
        high_risk = int(exceptions["SEVERITY"].isin(["Critical", "High"]).sum())
    affected_warehouses = safe_int(summary_row.get("AFFECTED_WAREHOUSES"))
    affected_users = safe_int(summary_row.get("AFFECTED_USERS"))

    c1, c2, c3, c4 = st.columns([1.1, 1.1, 1.1, 2.4])
    c1.metric("Workbench Readiness", f"{score}/100", _root_cause_rating(score))
    c2.metric("High-Risk Queries", f"{high_risk:,}", delta_color="inverse")
    c3.metric("Affected Scope", f"{affected_warehouses:,} WH / {affected_users:,} users")
    with c4:
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
            st.markdown(f"**{item.get('SEVERITY', 'Medium')}: {item.get('ROOT_CAUSE', '')}**")
            st.caption(f"{item.get('QUERY_ID', '')} | {item.get('WAREHOUSE_NAME', 'unknown warehouse')}")
            st.caption(f"Impact: {safe_float(item.get('IMPACT_VALUE')):,.2f} {item.get('IMPACT_UNIT', '')}")
            st.write(str(item.get("NEXT_ACTION", "")))
            if st.button(f"Open {workflow}", key=f"qw_watch_floor_{idx}_{workflow}", use_container_width=True):
                if warehouse:
                    st.session_state["global_warehouse"] = warehouse
                    st.session_state["lm_wh"] = warehouse
                    st.session_state["wh_filter"] = warehouse
                if workflow == "History Search" and query_id:
                    st.session_state["qs_text"] = query_id
                    st.session_state["qs_status"] = "ALL"
                    st.session_state["qs_days"] = min(max(int(days), 1), 30)
                    st.session_state["qs_autorun"] = True
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
                    st.session_state["workload_query_diagnosis_mode"] = "Detailed diagnosis"
                elif workflow == "Patterns":
                    st.session_state["workload_query_diagnosis_mode"] = "Root cause patterns"
                st.session_state["query_workbench_workflow"] = workflow
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
        f"- Root-cause score: {score} ({_root_cause_rating(score)})",
        f"- Total queries: {safe_int(summary_row.get('TOTAL_QUERIES')):,}",
        f"- Failed queries: {safe_int(summary_row.get('FAILED_QUERIES')):,}",
        f"- Queued queries: {safe_int(summary_row.get('QUEUED_QUERIES')):,}",
        f"- Spill queries: {safe_int(summary_row.get('SPILL_QUERIES')):,}",
        f"- Full-scan candidates: {safe_int(summary_row.get('FULL_SCAN_QUERIES')):,}",
        "",
        "## DBA Narrative",
        (
            "Use this brief as the first-pass triage view before opening Query Workbench drilldowns. "
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
                    WHEN queued_sec >= 30 THEN 'Warehouse Queue'
                    WHEN remote_spill_gb >= 1 THEN 'Remote Spill'
                    WHEN partition_pct >= 90 AND gb_scanned >= 10 THEN 'Full Scan'
                    WHEN elapsed_sec >= 30 THEN 'Slow Query'
                    ELSE 'Watch'
                END AS root_cause,
                CASE
                    WHEN UPPER(execution_status) = 'FAILED_WITH_ERROR' THEN 1000000 + elapsed_sec
                    WHEN queued_sec >= 30 THEN queued_sec
                    WHEN remote_spill_gb >= 1 THEN remote_spill_gb
                    WHEN partition_pct >= 90 AND gb_scanned >= 10 THEN gb_scanned
                    ELSE elapsed_sec
                END AS impact_value,
                CASE
                    WHEN UPPER(execution_status) = 'FAILED_WITH_ERROR' THEN 'error'
                    WHEN queued_sec >= 30 THEN 'seconds queued'
                    WHEN remote_spill_gb >= 1 THEN 'GB remote spill'
                    WHEN partition_pct >= 90 AND gb_scanned >= 10 THEN 'GB scanned'
                    ELSE 'seconds elapsed'
                END AS impact_unit
            FROM base
            WHERE UPPER(execution_status) = 'FAILED_WITH_ERROR'
               OR queued_sec >= 30
               OR remote_spill_gb >= 1
               OR (partition_pct >= 90 AND gb_scanned >= 10)
               OR elapsed_sec >= 30
        )
        SELECT
            CASE
                WHEN root_cause = 'Failed Query' THEN 'High'
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
    """Build root-cause brief SQL from OVERWATCH mart facts."""
    hourly = mart_object_name("FACT_QUERY_HOURLY")
    detail = mart_object_name("FACT_QUERY_DETAIL_RECENT")
    company_filter = "" if str(company or "").upper() == "ALL" else f"AND company = {sql_literal(company, 100)}"
    hourly_filters = get_global_filter_clause(
        date_col="hour_start",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
    )
    detail_filters = get_global_filter_clause(
        date_col="start_time",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
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
                ) AS full_scan_queries
            FROM {detail}
            WHERE start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
              {company_filter}
              AND warehouse_name IS NOT NULL
              {detail_filters}
        )
        SELECT
            h.total_queries,
            h.failed_queries,
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
                    WHEN queued_sec >= 30 THEN 'Warehouse Queue'
                    WHEN remote_spill_gb >= 1 THEN 'Remote Spill'
                    WHEN partition_pct >= 90 AND gb_scanned >= 10 THEN 'Full Scan'
                    WHEN elapsed_sec >= 30 THEN 'Slow Query'
                    ELSE 'Watch'
                END AS root_cause,
                CASE
                    WHEN UPPER(COALESCE(execution_status, '')) IN ('FAILED_WITH_ERROR', 'FAILED') THEN 1000000 + elapsed_sec
                    WHEN queued_sec >= 30 THEN queued_sec
                    WHEN remote_spill_gb >= 1 THEN remote_spill_gb
                    WHEN partition_pct >= 90 AND gb_scanned >= 10 THEN gb_scanned
                    ELSE elapsed_sec
                END AS impact_value,
                CASE
                    WHEN UPPER(COALESCE(execution_status, '')) IN ('FAILED_WITH_ERROR', 'FAILED') THEN 'error'
                    WHEN queued_sec >= 30 THEN 'seconds queued'
                    WHEN remote_spill_gb >= 1 THEN 'GB remote spill'
                    WHEN partition_pct >= 90 AND gb_scanned >= 10 THEN 'GB scanned'
                    ELSE 'seconds elapsed'
                END AS impact_unit
            FROM base
            WHERE UPPER(COALESCE(execution_status, '')) IN ('FAILED_WITH_ERROR', 'FAILED')
               OR queued_sec >= 30
               OR remote_spill_gb >= 1
               OR (partition_pct >= 90 AND gb_scanned >= 10)
               OR elapsed_sec >= 30
        )
        SELECT
            CASE
                WHEN root_cause = 'Failed Query' THEN 'High'
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
            "Source": "Query Workbench - Root Cause",
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


def _render_root_cause_brief(session) -> None:
    company = get_active_company()
    with st.expander("Root-Cause Brief", expanded=bool(st.session_state.get("exceptions_only_mode"))):
        c1, c2 = st.columns([1, 1])
        with c1:
            days = st.slider("Root-cause lookback (days)", 1, 30, 7, key="qw_rc_days")
        with c2:
            limit = st.slider("Exception rows", 25, 250, 100, step=25, key="qw_rc_limit")

        if st.button("Load Root-Cause Brief", key="qw_rc_load"):
            with st.spinner("Building root-cause brief..."):
                try:
                    summary_sql, exceptions_sql = _build_mart_root_cause_sql(days, limit, company)
                    summary_df = run_query(
                        summary_sql,
                        ttl_key=f"qw_root_summary_mart_{company}_{days}",
                        tier="historical",
                        section="Query Workbench",
                    )
                    exceptions = run_query(
                        exceptions_sql,
                        ttl_key=f"qw_root_exceptions_mart_{company}_{days}_{limit}",
                        tier="historical",
                        section="Query Workbench",
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
                        "source": "OVERWATCH mart: FACT_QUERY_HOURLY + FACT_QUERY_DETAIL_RECENT",
                    }
                except Exception as e:
                    try:
                        summary_sql, exceptions_sql = _build_root_cause_sql(session, days, limit)
                        summary_df = run_query(
                            summary_sql,
                            ttl_key=f"qw_root_summary_live_{company}_{days}",
                            tier="historical",
                            section="Query Workbench",
                        )
                        exceptions = run_query(
                            exceptions_sql,
                            ttl_key=f"qw_root_exceptions_live_{company}_{days}_{limit}",
                            tier="historical",
                            section="Query Workbench",
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
                        st.info(f"Query mart unavailable; used live QUERY_HISTORY fallback. {format_snowflake_error(e)}")
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
            queued_queries=safe_int(summary_row.get("QUEUED_QUERIES")),
            spill_queries=safe_int(summary_row.get("SPILL_QUERIES")),
            full_scan_queries=safe_int(summary_row.get("FULL_SCAN_QUERIES")),
            slow_queries=safe_int(summary_row.get("SLOW_QUERIES")),
            total_queries=safe_int(summary_row.get("TOTAL_QUERIES")),
        )
        rating = _root_cause_rating(score)
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Root-Cause Score", score, rating)
        c2.metric("Failed", f"{safe_int(summary_row.get('FAILED_QUERIES')):,}", delta_color="inverse")
        c3.metric("Queued", f"{safe_int(summary_row.get('QUEUED_QUERIES')):,}", delta_color="inverse")
        c4.metric("Spill", f"{safe_int(summary_row.get('SPILL_QUERIES')):,}", delta_color="inverse")
        c5.metric("Full Scan", f"{safe_int(summary_row.get('FULL_SCAN_QUERIES')):,}", delta_color="inverse")

        if score < 65:
            st.error("Incident risk: query failures, queue pressure, spill, or scan-heavy workload needs DBA action.")
        elif score < 78:
            st.warning("Degraded: review the top exceptions before handing this off as normal workload.")
        elif score < 90:
            st.info("Watch: a few exceptions exist, but the query estate is broadly controlled.")
        else:
            st.success("Stable: no dominant query root-cause pressure in the selected scope.")
        st.caption(meta.get("source", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"))

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
                    "QUEUED_SEC", "GB_SCANNED", "REMOTE_SPILL_GB",
                    "NEXT_ACTION",
                ],
                sort_by=["ELAPSED_SEC", "QUEUED_SEC", "GB_SCANNED", "REMOTE_SPILL_GB"],
                ascending=[False, False, False, False],
                raw_label="All query root-cause exceptions",
            )
            if st.button("Save Root-Cause Exceptions to Action Queue", key="qw_rc_queue"):
                try:
                    saved = _queue_root_cause_actions(session, exceptions)
                    st.success(f"Saved {saved} root-cause findings to the action queue.")
                except Exception as e:
                    st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
                    st.info("Deploy the Action Queue table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry this save.")
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
        with st.expander("Proof SQL"):
            sql_map = st.session_state.get("qw_root_sql", {})
            st.code(sql_map.get("summary", ""), language="sql")
            st.code(sql_map.get("exceptions", ""), language="sql")


def render() -> None:
    session = get_session()
    if st.session_state.get("exceptions_only_mode") and "query_workbench_workflow" not in st.session_state:
        st.session_state["query_workbench_workflow"] = "Diagnosis"
    st.header("Query Workbench")
    st.caption(
        "One place for live query triage, slow-query diagnosis, pattern analysis, "
        "and historical query search. Use this before jumping into cost, warehouse, "
        "or security follow-up."
    )
    render_signal_confidence(
        source="INFORMATION_SCHEMA",
        confidence="exact",
        scope_note="Current activity is live; history is ACCOUNT_USAGE-backed.",
    )
    if st.session_state.get("exceptions_only_mode"):
        st.warning("Exceptions-only mode: start with Diagnosis unless you need currently running queries.")

    render_workflow_guide(
        "Confirm whether the query is still running, diagnose the bottleneck, "
        "compare recurring patterns, then pull exact query text/history for evidence.",
        [
            ("Something is running now", "Use Live Triage."),
            ("Something was slow, queued, blocked, or spilling", "Use Diagnosis."),
            ("A user, role, warehouse, or query type keeps recurring", "Use Patterns."),
            ("You have a query ID or need exact SQL text", "Use History Search."),
        ],
    )

    _render_root_cause_brief(session)
    if st.session_state.get("exceptions_only_mode"):
        st.stop()

    workflow = render_workflow_selector(
        "Query workflow",
        "query_workbench_workflow",
        WORKFLOWS,
    )

    if workflow == "Live Triage":
        live_monitor.render()
    elif workflow == "Diagnosis":
        detailed_diagnosis.render()
    elif workflow == "Patterns":
        query_analysis.render()
    else:
        query_search.render()
