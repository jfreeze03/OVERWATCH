"""Account Health bounded data/load helper functions."""
from __future__ import annotations

import streamlit as st

from sections.base import lazy_pandas, lazy_util as _lazy_util


pd = lazy_pandas()

build_task_failure_summary_sql = _lazy_util("build_task_failure_summary_sql")
build_task_health_sql = _lazy_util("build_task_health_sql")
filter_existing_columns = _lazy_util("filter_existing_columns")
run_query_or_raise = _lazy_util("run_query_or_raise")


def _task_failure_sql_or_empty(session, time_predicate: str, limit: int, company: str) -> str:
    """Return TASK_HISTORY failure SQL, or an empty compatible result if unavailable."""
    try:
        return build_task_failure_summary_sql(session, time_predicate, limit=limit, company=company)
    except Exception:
        return """
            SELECT NULL::VARCHAR AS TASK_NAME,
                   NULL::VARCHAR AS DATABASE_NAME,
                   NULL::VARCHAR AS SCHEMA_NAME,
                   0::NUMBER AS FAILURES,
                   NULL::TIMESTAMP_NTZ AS LAST_FAILURE,
                   NULL::VARCHAR AS LAST_ERROR
            WHERE 1=0
        """


def _task_health_sql_or_empty(session, time_predicate: str, company: str) -> str:
    """Return TASK_HISTORY aggregate SQL, or a single zero row if unavailable."""
    try:
        return build_task_health_sql(session, time_predicate, company=company)
    except Exception:
        return """
            SELECT 0::NUMBER AS TASK_RUNS,
                   0::NUMBER AS FAILED_TASKS,
                   0::NUMBER AS SUCCEEDED_TASKS,
                   0::NUMBER AS DISTINCT_TASKS
        """


def _default_query_history_capabilities() -> dict[str, str]:
    return {
        "cost_wh_size_expr": "NULL::VARCHAR",
        "cost_bytes_scanned_expr": "0",
        "failed_pred_q": "UPPER(q.execution_status) = 'FAILED_WITH_ERROR'",
        "failed_pred_plain": "UPPER(execution_status) = 'FAILED_WITH_ERROR'",
        "queued_count_expr_q": "SUM(CASE WHEN q.execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END)",
        "queued_count_expr_plain": "SUM(CASE WHEN execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END)",
        "pressure_wh_size_expr": "NULL::VARCHAR",
    }


def _account_query_history_capabilities(session) -> dict[str, str]:
    if session is None:
        return _default_query_history_capabilities()
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "WAREHOUSE_SIZE",
            "BYTES_SCANNED",
            "ERROR_CODE",
            "QUEUED_OVERLOAD_TIME",
            "QUEUED_PROVISIONING_TIME",
            "QUEUED_REPAIR_TIME",
        ],
    ))
    queue_cols = [
        col.lower()
        for col in ["QUEUED_OVERLOAD_TIME", "QUEUED_PROVISIONING_TIME", "QUEUED_REPAIR_TIME"]
        if col in qh_cols
    ]
    queue_time_q = " + ".join([f"COALESCE(q.{col}, 0)" for col in queue_cols])
    queue_time_plain = " + ".join([f"COALESCE({col}, 0)" for col in queue_cols])
    return {
        "cost_wh_size_expr": "MAX(q.warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR",
        "cost_bytes_scanned_expr": "SUM(q.bytes_scanned)" if "BYTES_SCANNED" in qh_cols else "0",
        "failed_pred_q": (
            "q.error_code IS NOT NULL"
            if "ERROR_CODE" in qh_cols
            else "UPPER(q.execution_status) = 'FAILED_WITH_ERROR'"
        ),
        "failed_pred_plain": (
            "error_code IS NOT NULL"
            if "ERROR_CODE" in qh_cols
            else "UPPER(execution_status) = 'FAILED_WITH_ERROR'"
        ),
        "queued_count_expr_q": (
            f"SUM(CASE WHEN {queue_time_q} > 0 OR q.execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END)"
            if queue_cols
            else "SUM(CASE WHEN q.execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END)"
        ),
        "queued_count_expr_plain": (
            f"SUM(CASE WHEN {queue_time_plain} > 0 OR execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END)"
            if queue_cols
            else "SUM(CASE WHEN execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END)"
        ),
        "pressure_wh_size_expr": "MAX(warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR",
    }


def _live_query_status_sql(wh_filter: str, db_filter: str, user_filter: str) -> str:
    return f"""
        SELECT COUNT(*) AS active_count,
               SUM(IFF(
                   COALESCE(queued_overload_time, 0)
                   + COALESCE(queued_provisioning_time, 0)
                   + COALESCE(queued_repair_time, 0) > 0
                   OR execution_status ILIKE '%QUEUED%',
                   1,
                   0
               )) AS queued_count,
               SUM(IFF(execution_status ILIKE '%BLOCKED%', 1, 0)) AS blocked_count
        FROM TABLE(
            INFORMATION_SCHEMA.QUERY_HISTORY(
                END_TIME_RANGE_START=>DATEADD('hours', -1, CURRENT_TIMESTAMP()),
                RESULT_LIMIT=>10000
            )
        ) q
        WHERE execution_status IN ('RUNNING', 'QUEUED', 'BLOCKED', 'RESUMING_WAREHOUSE')
          {wh_filter} {db_filter} {user_filter}
    """


def _load_live_query_status(wh_filter: str, db_filter: str, user_filter: str) -> tuple[pd.DataFrame, str]:
    # Prefer INFORMATION_SCHEMA for the morning triage counters. ACCOUNT_USAGE
    # remains a fallback only because Snowflake-hosted Streamlit can reject some
    # table-function calls depending on role/session permissions.
    fallback_sql = f"""
        SELECT COUNT(*) AS active_count,
               SUM(CASE WHEN execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END) AS queued_count,
               SUM(CASE WHEN execution_status ILIKE '%BLOCKED%' THEN 1 ELSE 0 END) AS blocked_count
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('hours', -1, CURRENT_TIMESTAMP())
          AND UPPER(q.execution_status) IN ('RUNNING', 'QUEUED', 'BLOCKED', 'RESUMING_WAREHOUSE')
          {wh_filter} {db_filter} {user_filter}
    """
    try:
        return run_query_or_raise(_live_query_status_sql(wh_filter, db_filter, user_filter)), "INFORMATION_SCHEMA"
    except Exception:
        try:
            return run_query_or_raise(fallback_sql), "ACCOUNT_USAGE"
        except Exception:
            return pd.DataFrame(), "ACCOUNT_USAGE"


def _can_use_control_room_mart(company: str) -> tuple[bool, str]:
    """Use the mart only when section filters match its company-level grain."""
    if str(company or "").upper() == "ALL":
        return False, "ALL view needs live/account-level aggregation."
    blocking_filters = {
        "warehouse": st.session_state.get("global_warehouse"),
        "user": st.session_state.get("global_user"),
        "role": st.session_state.get("global_role"),
        "database": st.session_state.get("global_database"),
    }
    active = [name for name, value in blocking_filters.items() if str(value or "").strip()]
    if active:
        return False, f"Global {', '.join(active)} filters are active."
    return True, ""


__all__ = [
    "_account_query_history_capabilities",
    "_can_use_control_room_mart",
    "_default_query_history_capabilities",
    "_live_query_status_sql",
    "_load_live_query_status",
    "_task_failure_sql_or_empty",
    "_task_health_sql_or_empty",
]
