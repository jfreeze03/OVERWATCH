"""Contention center: lock waits, task overlap, long DML, and queueing proof."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from utils import (
    day_window_selectbox,
    download_csv,
    format_snowflake_error,
    get_session,
    render_priority_dataframe,
    run_query,
    safe_float,
    safe_int,
    show_to_df,
)
from utils.section_guidance import defer_section_note
from utils.workflows import render_load_status, render_mode_selector


CONTENTION_CENTER_VIEWS = (
    "Brief",
    "Active Locks",
    "Historical Waits",
    "Table Hotspots",
    "Task Overlap",
    "Long DML",
    "Query -> Task Map",
)

CONTENTION_VIEW_DETAILS = {
    "Brief": "One ranked decision view: lock contention, task overlap, long DML, or warehouse queueing.",
    "Active Locks": "Live SHOW LOCKS evidence for the current incident window.",
    "Historical Waits": "LOCK_WAIT_HISTORY trend evidence for repeated table/object contention.",
    "Table Hotspots": "Objects repeatedly showing wait time, waiter volume, and blocker volume.",
    "Task Overlap": "Task runs that overlap with themselves and should be serialized or rescheduled.",
    "Long DML": "MERGE/UPDATE/DELETE/INSERT/COPY statements likely to hold locks for too long.",
    "Query -> Task Map": "Blocked query IDs mapped back to Snowflake task runs where possible.",
}

CONTENTION_STATE_KEYS = (
    "contention_active_locks",
    "contention_historical_waits",
    "contention_table_hotspots",
    "contention_task_overlap",
    "contention_long_dml",
    "contention_task_mapping",
    "contention_warehouse_pressure",
    "contention_decision_rows",
    "contention_source_errors",
)


def build_lock_wait_history_sql(days: int = 7) -> str:
    """Return historical lock-wait evidence ranked by wait duration."""
    return f"""
SELECT
    START_TIME,
    END_TIME,
    DATEDIFF('second', START_TIME, COALESCE(END_TIME, CURRENT_TIMESTAMP())) AS WAIT_SECONDS,
    DATABASE_NAME,
    SCHEMA_NAME,
    OBJECT_NAME,
    WAITER_TRANSACTION_ID,
    BLOCKER_TRANSACTION_ID,
    WAITER_QUERY_ID,
    BLOCKER_QUERIES,
    CASE
      WHEN DATEDIFF('second', START_TIME, COALESCE(END_TIME, CURRENT_TIMESTAMP())) >= 300 THEN 'Critical'
      WHEN DATEDIFF('second', START_TIME, COALESCE(END_TIME, CURRENT_TIMESTAMP())) >= 60 THEN 'High'
      ELSE 'Medium'
    END AS SEVERITY,
    'Lock contention' AS ROOT_CAUSE,
    'Identify the blocker transaction, stop overlapping writers to the same target, then serialize final writes or move writers to isolated staging tables.' AS NEXT_ACTION,
    'Re-run LOCK_WAIT_HISTORY and confirm this object no longer dominates wait_seconds.' AS VERIFY_AFTER_FIX
FROM SNOWFLAKE.ACCOUNT_USAGE.LOCK_WAIT_HISTORY
WHERE START_TIME >= DATEADD('day', -{max(1, int(days or 7))}, CURRENT_TIMESTAMP())
ORDER BY WAIT_SECONDS DESC, START_TIME DESC
LIMIT 200
"""


def build_table_hotspot_sql(days: int = 7) -> str:
    """Return objects that repeatedly accumulate lock wait time."""
    return f"""
SELECT
    DATABASE_NAME,
    SCHEMA_NAME,
    OBJECT_NAME,
    COUNT(*) AS WAIT_EVENTS,
    COUNT(DISTINCT WAITER_TRANSACTION_ID) AS WAITER_TRANSACTIONS,
    COUNT(DISTINCT BLOCKER_TRANSACTION_ID) AS BLOCKER_TRANSACTIONS,
    SUM(DATEDIFF('second', START_TIME, COALESCE(END_TIME, CURRENT_TIMESTAMP()))) AS TOTAL_WAIT_SECONDS,
    MAX(DATEDIFF('second', START_TIME, COALESCE(END_TIME, CURRENT_TIMESTAMP()))) AS MAX_WAIT_SECONDS,
    MIN(START_TIME) AS FIRST_WAIT_AT,
    MAX(COALESCE(END_TIME, START_TIME)) AS LAST_WAIT_AT,
    CASE
      WHEN SUM(DATEDIFF('second', START_TIME, COALESCE(END_TIME, CURRENT_TIMESTAMP()))) >= 1800 THEN 'Critical'
      WHEN SUM(DATEDIFF('second', START_TIME, COALESCE(END_TIME, CURRENT_TIMESTAMP()))) >= 300 THEN 'High'
      ELSE 'Medium'
    END AS SEVERITY,
    'Hot locked object' AS ROOT_CAUSE,
    'Find writers targeting this object, move heavy transforms to staging, and serialize the final publish step to this table.' AS NEXT_ACTION,
    'Confirm this object no longer appears in the top LOCK_WAIT_HISTORY wait_seconds objects for the same lookback.' AS VERIFY_AFTER_FIX
FROM SNOWFLAKE.ACCOUNT_USAGE.LOCK_WAIT_HISTORY
WHERE START_TIME >= DATEADD('day', -{max(1, int(days or 7))}, CURRENT_TIMESTAMP())
GROUP BY DATABASE_NAME, SCHEMA_NAME, OBJECT_NAME
ORDER BY TOTAL_WAIT_SECONDS DESC, WAIT_EVENTS DESC, MAX_WAIT_SECONDS DESC
LIMIT 100
"""


def build_task_overlap_sql(days: int = 7) -> str:
    """Return task executions that overlap with another run of the same task."""
    return f"""
WITH task_runs AS (
    SELECT
        DATABASE_NAME,
        SCHEMA_NAME,
        NAME AS TASK_NAME,
        QUERY_ID,
        STATE,
        SCHEDULED_TIME,
        COALESCE(QUERY_START_TIME, SCHEDULED_TIME) AS RUN_START,
        COALESCE(COMPLETED_TIME, CURRENT_TIMESTAMP()) AS RUN_END
    FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
    WHERE SCHEDULED_TIME >= DATEADD('day', -{max(1, int(days or 7))}, CURRENT_TIMESTAMP())
      AND QUERY_ID IS NOT NULL
),
overlaps AS (
    SELECT
        a.DATABASE_NAME,
        a.SCHEMA_NAME,
        a.TASK_NAME,
        a.QUERY_ID AS RUN_1_QUERY_ID,
        b.QUERY_ID AS RUN_2_QUERY_ID,
        a.RUN_START AS RUN_1_START,
        a.RUN_END AS RUN_1_END,
        b.RUN_START AS RUN_2_START,
        b.RUN_END AS RUN_2_END,
        DATEDIFF('second', GREATEST(a.RUN_START, b.RUN_START), LEAST(a.RUN_END, b.RUN_END)) AS OVERLAP_SECONDS,
        a.STATE AS RUN_1_STATE,
        b.STATE AS RUN_2_STATE
    FROM task_runs a
    JOIN task_runs b
      ON a.DATABASE_NAME = b.DATABASE_NAME
     AND a.SCHEMA_NAME = b.SCHEMA_NAME
     AND a.TASK_NAME = b.TASK_NAME
     AND a.QUERY_ID < b.QUERY_ID
     AND a.RUN_START < b.RUN_END
     AND b.RUN_START < a.RUN_END
)
SELECT
    *,
    CASE
      WHEN OVERLAP_SECONDS >= 900 THEN 'Critical'
      WHEN OVERLAP_SECONDS >= 300 THEN 'High'
      ELSE 'Medium'
    END AS SEVERITY,
    'Task overlap' AS ROOT_CAUSE,
    'Set the root task to NO_OVERLAP or widen the schedule; keep parallel read/transform tasks but serialize the final shared-table publish step.' AS NEXT_ACTION,
    'Verify TASK_HISTORY shows no overlapping RUN_START/RUN_END windows for this task.' AS VERIFY_AFTER_FIX
FROM overlaps
WHERE OVERLAP_SECONDS > 0
ORDER BY OVERLAP_SECONDS DESC, RUN_1_START DESC
LIMIT 200
"""


def build_blocked_query_task_map_sql(days: int = 7) -> str:
    """Return blocked queries mapped to task ownership when TASK_HISTORY exposes the query ID."""
    return f"""
WITH blocked_queries AS (
    SELECT
        QUERY_ID,
        USER_NAME,
        ROLE_NAME,
        WAREHOUSE_NAME,
        DATABASE_NAME,
        SCHEMA_NAME,
        QUERY_TYPE,
        START_TIME,
        END_TIME,
        TOTAL_ELAPSED_TIME / 1000.0 AS ELAPSED_SECONDS,
        COALESCE(TRANSACTION_BLOCKED_TIME, 0) / 1000.0 AS BLOCKED_SECONDS,
        LEFT(QUERY_TEXT, 1000) AS QUERY_TEXT
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE START_TIME >= DATEADD('day', -{max(1, int(days or 7))}, CURRENT_TIMESTAMP())
      AND COALESCE(TRANSACTION_BLOCKED_TIME, 0) > 0
),
task_runs AS (
    SELECT
        DATABASE_NAME AS TASK_DATABASE_NAME,
        SCHEMA_NAME AS TASK_SCHEMA_NAME,
        NAME AS TASK_NAME,
        QUERY_ID AS TASK_QUERY_ID,
        STATE AS TASK_STATE,
        SCHEDULED_TIME,
        QUERY_START_TIME,
        COMPLETED_TIME,
        ERROR_MESSAGE
    FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
    WHERE SCHEDULED_TIME >= DATEADD('day', -{max(1, int(days or 7))}, CURRENT_TIMESTAMP())
      AND QUERY_ID IS NOT NULL
),
wait_objects AS (
    SELECT
        WAITER_QUERY_ID AS QUERY_ID,
        COUNT(*) AS LOCK_WAIT_ROWS,
        MAX(DATEDIFF('second', START_TIME, COALESCE(END_TIME, CURRENT_TIMESTAMP()))) AS MAX_LOCK_WAIT_SECONDS,
        LISTAGG(DISTINCT DATABASE_NAME || '.' || SCHEMA_NAME || '.' || OBJECT_NAME, ', ')
            WITHIN GROUP (ORDER BY DATABASE_NAME || '.' || SCHEMA_NAME || '.' || OBJECT_NAME) AS WAIT_OBJECTS
    FROM SNOWFLAKE.ACCOUNT_USAGE.LOCK_WAIT_HISTORY
    WHERE START_TIME >= DATEADD('day', -{max(1, int(days or 7))}, CURRENT_TIMESTAMP())
      AND WAITER_QUERY_ID IS NOT NULL
    GROUP BY WAITER_QUERY_ID
)
SELECT
    b.QUERY_ID,
    b.USER_NAME,
    b.ROLE_NAME,
    b.WAREHOUSE_NAME,
    b.DATABASE_NAME,
    b.SCHEMA_NAME,
    b.QUERY_TYPE,
    b.START_TIME,
    b.END_TIME,
    b.ELAPSED_SECONDS,
    b.BLOCKED_SECONDS,
    w.LOCK_WAIT_ROWS,
    w.MAX_LOCK_WAIT_SECONDS,
    w.WAIT_OBJECTS,
    t.TASK_DATABASE_NAME,
    t.TASK_SCHEMA_NAME,
    t.TASK_NAME,
    t.TASK_STATE,
    t.SCHEDULED_TIME,
    t.COMPLETED_TIME,
    t.ERROR_MESSAGE,
    b.QUERY_TEXT,
    CASE
      WHEN b.BLOCKED_SECONDS >= 300 THEN 'Critical'
      WHEN b.BLOCKED_SECONDS >= 60 THEN 'High'
      ELSE 'Medium'
    END AS SEVERITY,
    CASE
      WHEN t.TASK_NAME IS NOT NULL THEN 'Task-owned blocked write'
      ELSE 'Blocked user/session DML'
    END AS ROOT_CAUSE,
    CASE
      WHEN t.TASK_NAME IS NOT NULL THEN 'Open Task graphs for the task, confirm schedule overlap, then serialize the final table write or set NO_OVERLAP on the root graph.'
      ELSE 'Use active locks to identify the blocker, then shorten or batch the blocked DML and prevent concurrent writers to the same target.'
    END AS NEXT_ACTION,
    CASE
      WHEN t.TASK_NAME IS NOT NULL THEN 'Verify the next TASK_HISTORY run has no blocked_seconds and no overlapping publish window.'
      ELSE 'Verify QUERY_HISTORY blocked_seconds returns to zero for the query pattern and target object.'
    END AS VERIFY_AFTER_FIX
FROM blocked_queries b
LEFT JOIN task_runs t
  ON b.QUERY_ID = t.TASK_QUERY_ID
LEFT JOIN wait_objects w
  ON b.QUERY_ID = w.QUERY_ID
ORDER BY b.BLOCKED_SECONDS DESC, b.ELAPSED_SECONDS DESC
LIMIT 200
"""


def build_long_dml_sql(days: int = 7) -> str:
    """Return long-running DML that can lengthen table lock windows."""
    return f"""
SELECT
    QUERY_ID,
    USER_NAME,
    WAREHOUSE_NAME,
    DATABASE_NAME,
    SCHEMA_NAME,
    QUERY_TYPE,
    START_TIME,
    END_TIME,
    TOTAL_ELAPSED_TIME / 1000.0 AS ELAPSED_SECONDS,
    COALESCE(TRANSACTION_BLOCKED_TIME, 0) / 1000.0 AS BLOCKED_SECONDS,
    COALESCE(QUEUED_OVERLOAD_TIME, 0) / 1000.0 AS QUEUED_OVERLOAD_SECONDS,
    LEFT(QUERY_TEXT, 1000) AS QUERY_TEXT,
    CASE
      WHEN COALESCE(TRANSACTION_BLOCKED_TIME, 0) >= 60000 THEN 'High'
      WHEN TOTAL_ELAPSED_TIME >= 1800000 THEN 'High'
      ELSE 'Medium'
    END AS SEVERITY,
    CASE
      WHEN COALESCE(TRANSACTION_BLOCKED_TIME, 0) > 0 THEN 'Blocked DML'
      WHEN COALESCE(QUEUED_OVERLOAD_TIME, 0) > 0 THEN 'Warehouse queueing'
      ELSE 'Long DML lock window'
    END AS ROOT_CAUSE,
    CASE
      WHEN COALESCE(TRANSACTION_BLOCKED_TIME, 0) > 0 THEN 'Inspect blocker locks and refactor writers so final MERGE/UPDATE/DELETE steps do not collide on the same target table.'
      WHEN COALESCE(QUEUED_OVERLOAD_TIME, 0) > 0 THEN 'Treat as compute concurrency first: review warehouse size, multi-cluster, and workload isolation before changing task ordering.'
      ELSE 'Shorten transaction scope: stage heavy transforms first, then run a smaller final write; batch large MERGE/UPDATE work by date, hash bucket, or batch id.'
    END AS NEXT_ACTION,
    'Confirm QUERY_HISTORY no longer shows high blocked_seconds or repeated long DML against the same target.' AS VERIFY_AFTER_FIX
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE START_TIME >= DATEADD('day', -{max(1, int(days or 7))}, CURRENT_TIMESTAMP())
  AND QUERY_TYPE IN ('INSERT', 'UPDATE', 'DELETE', 'MERGE', 'COPY')
ORDER BY BLOCKED_SECONDS DESC, ELAPSED_SECONDS DESC
LIMIT 200
"""


def build_warehouse_pressure_sql(days: int = 1) -> str:
    """Return warehouse load evidence to distinguish queueing from lock contention."""
    return f"""
SELECT
    WAREHOUSE_NAME,
    COUNT(*) AS SAMPLE_COUNT,
    AVG(AVG_RUNNING) AS AVG_RUNNING,
    AVG(AVG_QUEUED_LOAD) AS AVG_QUEUED_LOAD,
    AVG(AVG_BLOCKED) AS AVG_BLOCKED,
    MAX(AVG_QUEUED_LOAD) AS MAX_QUEUED_LOAD,
    MAX(AVG_BLOCKED) AS MAX_BLOCKED,
    CASE
      WHEN MAX(AVG_BLOCKED) > 0 THEN 'High'
      WHEN MAX(AVG_QUEUED_LOAD) > 0 THEN 'Medium'
      ELSE 'Info'
    END AS SEVERITY,
    CASE
      WHEN MAX(AVG_BLOCKED) > 0 THEN 'Warehouse blocked load'
      WHEN MAX(AVG_QUEUED_LOAD) > 0 THEN 'Warehouse queueing'
      ELSE 'No warehouse pressure'
    END AS ROOT_CAUSE,
    CASE
      WHEN MAX(AVG_BLOCKED) > 0 THEN 'Correlate blocked load with active locks and task writers before resizing compute.'
      WHEN MAX(AVG_QUEUED_LOAD) > 0 THEN 'Review warehouse size, multi-cluster, and workload isolation; this is queue pressure, not necessarily lock contention.'
      ELSE 'No warehouse pressure action needed from this sample.'
    END AS NEXT_ACTION
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY
WHERE START_TIME >= DATEADD('day', -{max(1, int(days or 1))}, CURRENT_TIMESTAMP())
GROUP BY WAREHOUSE_NAME
HAVING MAX(AVG_QUEUED_LOAD) > 0 OR MAX(AVG_BLOCKED) > 0
ORDER BY MAX_BLOCKED DESC, MAX_QUEUED_LOAD DESC
LIMIT 100
"""


def _safe_frame(value) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value
    return pd.DataFrame()


def _source_error_key(key: str) -> str:
    return f"{key}_error"


def _run_contention_query(key: str, label: str, sql: str, *, ttl_key: str, tier: str = "historical") -> pd.DataFrame:
    try:
        frame = run_query(sql, ttl_key=ttl_key, tier=tier, section="Contention Center")
    except Exception as exc:
        message = format_snowflake_error(exc)
        st.session_state[_source_error_key(key)] = message
        st.session_state.setdefault("contention_source_errors", {})[label] = message
        return pd.DataFrame()
    st.session_state[_source_error_key(key)] = ""
    return frame


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if frame is None or frame.empty or column not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0)


def _severity_rank(value: object) -> int:
    return {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "WATCH": 3, "INFO": 4}.get(str(value or "").upper(), 9)


def _decision_rows(
    lock_waits: pd.DataFrame,
    task_overlap: pd.DataFrame,
    long_dml: pd.DataFrame,
    warehouse_pressure: pd.DataFrame,
    table_hotspots: pd.DataFrame | None = None,
    task_mapping: pd.DataFrame | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    table_hotspots = _safe_frame(table_hotspots)
    task_mapping = _safe_frame(task_mapping)

    if not lock_waits.empty:
        top = lock_waits.head(10)
        for _, row in top.iterrows():
            rows.append({
                "SEVERITY": row.get("SEVERITY", "High"),
                "SIGNAL": "Lock wait",
                "ENTITY": ".".join(
                    part for part in [
                        str(row.get("DATABASE_NAME") or ""),
                        str(row.get("SCHEMA_NAME") or ""),
                        str(row.get("OBJECT_NAME") or ""),
                    ] if part
                ) or "Locked object",
                "EVIDENCE": f"{safe_int(row.get('WAIT_SECONDS')):,} seconds waiting; waiter query {row.get('WAITER_QUERY_ID', '')}",
                "NEXT_ACTION": row.get("NEXT_ACTION", ""),
                "VERIFY_AFTER_FIX": row.get("VERIFY_AFTER_FIX", ""),
            })

    if not table_hotspots.empty:
        for _, row in table_hotspots.head(10).iterrows():
            rows.append({
                "SEVERITY": row.get("SEVERITY", "High"),
                "SIGNAL": "Hot locked object",
                "ENTITY": ".".join(
                    part for part in [
                        str(row.get("DATABASE_NAME") or ""),
                        str(row.get("SCHEMA_NAME") or ""),
                        str(row.get("OBJECT_NAME") or ""),
                    ] if part
                ) or "Hot object",
                "EVIDENCE": (
                    f"{safe_int(row.get('WAIT_EVENTS')):,} waits; "
                    f"{safe_int(row.get('TOTAL_WAIT_SECONDS')):,} total wait seconds; "
                    f"{safe_int(row.get('BLOCKER_TRANSACTIONS')):,} blocker transactions"
                ),
                "NEXT_ACTION": row.get("NEXT_ACTION", ""),
                "VERIFY_AFTER_FIX": row.get("VERIFY_AFTER_FIX", ""),
            })

    if not task_overlap.empty:
        for _, row in task_overlap.head(10).iterrows():
            rows.append({
                "SEVERITY": row.get("SEVERITY", "High"),
                "SIGNAL": "Task overlap",
                "ENTITY": row.get("TASK_NAME", "Task"),
                "EVIDENCE": f"{safe_int(row.get('OVERLAP_SECONDS')):,} seconds overlapping; runs {row.get('RUN_1_QUERY_ID', '')} and {row.get('RUN_2_QUERY_ID', '')}",
                "NEXT_ACTION": row.get("NEXT_ACTION", ""),
                "VERIFY_AFTER_FIX": row.get("VERIFY_AFTER_FIX", ""),
            })

    if not task_mapping.empty:
        for _, row in task_mapping.head(10).iterrows():
            owner = row.get("TASK_NAME") or row.get("USER_NAME") or "Blocked query"
            rows.append({
                "SEVERITY": row.get("SEVERITY", "High"),
                "SIGNAL": row.get("ROOT_CAUSE", "Blocked query"),
                "ENTITY": owner,
                "EVIDENCE": (
                    f"query {row.get('QUERY_ID', '')}; "
                    f"{safe_float(row.get('BLOCKED_SECONDS')):,.0f}s blocked; "
                    f"objects {row.get('WAIT_OBJECTS') or 'not mapped'}"
                ),
                "NEXT_ACTION": row.get("NEXT_ACTION", ""),
                "VERIFY_AFTER_FIX": row.get("VERIFY_AFTER_FIX", ""),
            })

    if not long_dml.empty:
        blocked_seconds = _numeric_series(long_dml, "BLOCKED_SECONDS")
        elapsed_seconds = _numeric_series(long_dml, "ELAPSED_SECONDS")
        dml = long_dml[(blocked_seconds > 0) | (elapsed_seconds >= 900)].head(10)
        for _, row in dml.iterrows():
            rows.append({
                "SEVERITY": row.get("SEVERITY", "Medium"),
                "SIGNAL": row.get("ROOT_CAUSE", "Long DML"),
                "ENTITY": row.get("QUERY_ID", "Query"),
                "EVIDENCE": (
                    f"{safe_float(row.get('ELAPSED_SECONDS')):,.0f}s elapsed; "
                    f"{safe_float(row.get('BLOCKED_SECONDS')):,.0f}s blocked; {row.get('QUERY_TYPE', '')}"
                ),
                "NEXT_ACTION": row.get("NEXT_ACTION", ""),
                "VERIFY_AFTER_FIX": row.get("VERIFY_AFTER_FIX", ""),
            })

    if not warehouse_pressure.empty:
        for _, row in warehouse_pressure.head(10).iterrows():
            rows.append({
                "SEVERITY": row.get("SEVERITY", "Medium"),
                "SIGNAL": row.get("ROOT_CAUSE", "Warehouse pressure"),
                "ENTITY": row.get("WAREHOUSE_NAME", "Warehouse"),
                "EVIDENCE": (
                    f"max blocked {safe_float(row.get('MAX_BLOCKED')):,.2f}; "
                    f"max queued load {safe_float(row.get('MAX_QUEUED_LOAD')):,.2f}"
                ),
                "NEXT_ACTION": row.get("NEXT_ACTION", ""),
                "VERIFY_AFTER_FIX": "Confirm warehouse load and query blocked time clear after remediation.",
            })

    decision = pd.DataFrame(rows)
    if decision.empty:
        return decision
    decision["_RANK"] = decision["SEVERITY"].map(_severity_rank)
    decision = decision.sort_values(["_RANK", "SIGNAL", "ENTITY"]).drop(columns=["_RANK"])
    return decision


def _load_contention_evidence(days: int) -> None:
    st.session_state["contention_source_errors"] = {}
    lock_waits = _run_contention_query(
        "contention_historical_waits",
        "Historical waits",
        build_lock_wait_history_sql(days),
        ttl_key=f"contention_lock_waits_{days}",
    )
    table_hotspots = _run_contention_query(
        "contention_table_hotspots",
        "Table hotspots",
        build_table_hotspot_sql(days),
        ttl_key=f"contention_table_hotspots_{days}",
    )
    task_overlap = _run_contention_query(
        "contention_task_overlap",
        "Task overlap",
        build_task_overlap_sql(days),
        ttl_key=f"contention_task_overlap_{days}",
    )
    long_dml = _run_contention_query(
        "contention_long_dml",
        "Long DML",
        build_long_dml_sql(days),
        ttl_key=f"contention_long_dml_{days}",
    )
    task_mapping = _run_contention_query(
        "contention_task_mapping",
        "Query to task map",
        build_blocked_query_task_map_sql(days),
        ttl_key=f"contention_task_mapping_{days}",
    )
    warehouse_pressure = _run_contention_query(
        "contention_warehouse_pressure",
        "Warehouse pressure",
        build_warehouse_pressure_sql(min(days, 14)),
        ttl_key=f"contention_warehouse_pressure_{days}",
    )

    st.session_state["contention_historical_waits"] = lock_waits
    st.session_state["contention_table_hotspots"] = table_hotspots
    st.session_state["contention_task_overlap"] = task_overlap
    st.session_state["contention_long_dml"] = long_dml
    st.session_state["contention_task_mapping"] = task_mapping
    st.session_state["contention_warehouse_pressure"] = warehouse_pressure
    st.session_state["contention_decision_rows"] = _decision_rows(
        lock_waits,
        task_overlap,
        long_dml,
        warehouse_pressure,
        table_hotspots=table_hotspots,
        task_mapping=task_mapping,
    )


def _check_active_locks() -> None:
    session = get_session()
    try:
        locks = show_to_df(session, "SHOW LOCKS IN ACCOUNT", force_refresh=True)
    except Exception as exc:
        st.session_state["contention_active_locks_error"] = format_snowflake_error(exc)
        locks = pd.DataFrame()
    st.session_state["contention_active_locks"] = locks


def _render_metric_strip() -> None:
    locks = _safe_frame(st.session_state.get("contention_active_locks"))
    waits = _safe_frame(st.session_state.get("contention_historical_waits"))
    hotspots = _safe_frame(st.session_state.get("contention_table_hotspots"))
    overlap = _safe_frame(st.session_state.get("contention_task_overlap"))
    dml = _safe_frame(st.session_state.get("contention_long_dml"))
    task_mapping = _safe_frame(st.session_state.get("contention_task_mapping"))

    worst_wait = 0
    if not waits.empty and "WAIT_SECONDS" in waits.columns:
        worst_wait = int(pd.to_numeric(waits["WAIT_SECONDS"], errors="coerce").fillna(0).max())
    blocked_queries = len(task_mapping)
    if not blocked_queries and not dml.empty and "BLOCKED_SECONDS" in dml.columns:
        blocked_queries = int((pd.to_numeric(dml["BLOCKED_SECONDS"], errors="coerce").fillna(0) > 0).sum())

    cols = st.columns(5)
    values = (
        ("Active locks", f"{len(locks):,}"),
        ("Worst wait", f"{worst_wait:,}s"),
        ("Hot objects", f"{len(hotspots):,}"),
        ("Task overlaps", f"{len(overlap):,}"),
        ("Blocked queries", f"{blocked_queries:,}"),
    )
    for col, (label, value) in zip(cols, values):
        with col:
            st.markdown(f"**{label}**")
            st.caption(str(value))


def _render_brief() -> None:
    decision = _safe_frame(st.session_state.get("contention_decision_rows"))
    source_errors = st.session_state.get("contention_source_errors") or {}
    if source_errors:
        with st.expander("Unavailable evidence sources", expanded=False):
            for label, message in source_errors.items():
                st.caption(f"{label}: {message}")
    if decision.empty:
        st.info("Load contention evidence to rank blockers, task overlap, long DML, and warehouse pressure.")
        return
    render_priority_dataframe(
        decision,
        title="Contention decision queue",
        priority_columns=["SEVERITY", "SIGNAL", "ENTITY", "EVIDENCE", "NEXT_ACTION", "VERIFY_AFTER_FIX"],
        sort_by=["SEVERITY", "SIGNAL"],
        max_rows=20,
        raw_label="All contention decisions",
    )
    download_csv(decision, "overwatch_contention_decisions.csv")


def _render_active_locks() -> None:
    locks = _safe_frame(st.session_state.get("contention_active_locks"))
    if locks.empty:
        error = st.session_state.get("contention_active_locks_error")
        if error:
            st.warning(f"Active lock check unavailable: {error}")
        else:
            st.info("No active lock rows loaded. Run the live check during an incident.")
        return
    render_priority_dataframe(
        locks,
        title="Active locks right now",
        max_rows=50,
        raw_label="All SHOW LOCKS rows",
    )
    download_csv(locks, "overwatch_active_locks.csv")


def _render_named_frame(key: str, title: str, priority_columns: list[str], raw_label: str) -> None:
    frame = _safe_frame(st.session_state.get(key))
    if frame.empty:
        error = st.session_state.get(_source_error_key(key))
        if error:
            st.warning(f"{title} unavailable: {error}")
            return
        st.info(f"No {title.lower()} evidence loaded for this window.")
        return
    render_priority_dataframe(
        frame,
        title=title,
        priority_columns=priority_columns,
        sort_by=["SEVERITY"],
        max_rows=40,
        raw_label=raw_label,
    )
    download_csv(frame, f"overwatch_{key}.csv")


def render() -> None:
    st.subheader("Contention Center")
    defer_section_note(
        "Use this when tasks or users report bottlenecks: prove lock waits, task overlap, long DML, "
        "or warehouse queueing before changing compute or task schedules."
    )
    defer_section_note(
        "Default fix pattern: parallelize reads and transforms, then serialize the final write to shared target tables."
    )

    days = day_window_selectbox(
        "Contention lookback",
        key="contention_center_days",
        default=7,
        help="Historical lock waits and task overlap use Account Usage, which can lag. Active locks are checked separately.",
    )

    c_load, c_live = st.columns([1, 1])
    with c_load:
        if st.button("Load Contention Evidence", key="contention_load", type="primary", width="stretch"):
            with render_load_status("Loading contention evidence", "Contention evidence ready"):
                _load_contention_evidence(days)
    with c_live:
        if st.button("Check Active Locks Now", key="contention_active_locks", width="stretch"):
            with render_load_status("Checking active locks", "Active lock check complete"):
                _check_active_locks()

    _render_metric_strip()

    active_view = render_mode_selector(
        "Contention view",
        "contention_center_view",
        CONTENTION_CENTER_VIEWS,
        default=CONTENTION_CENTER_VIEWS[0],
        details=CONTENTION_VIEW_DETAILS,
        columns=5,
    )

    if active_view == "Brief":
        _render_brief()
    elif active_view == "Active Locks":
        _render_active_locks()
    elif active_view == "Historical Waits":
        _render_named_frame(
            "contention_historical_waits",
            "Historical lock waits",
            ["SEVERITY", "DATABASE_NAME", "SCHEMA_NAME", "OBJECT_NAME", "WAIT_SECONDS", "WAITER_QUERY_ID", "NEXT_ACTION"],
            "All historical lock waits",
        )
    elif active_view == "Table Hotspots":
        _render_named_frame(
            "contention_table_hotspots",
            "Table hotspots",
            [
                "SEVERITY",
                "DATABASE_NAME",
                "SCHEMA_NAME",
                "OBJECT_NAME",
                "WAIT_EVENTS",
                "TOTAL_WAIT_SECONDS",
                "MAX_WAIT_SECONDS",
                "NEXT_ACTION",
                "VERIFY_AFTER_FIX",
            ],
            "All table hotspot rows",
        )
    elif active_view == "Task Overlap":
        _render_named_frame(
            "contention_task_overlap",
            "Self-overlapping task runs",
            ["SEVERITY", "TASK_NAME", "OVERLAP_SECONDS", "RUN_1_QUERY_ID", "RUN_2_QUERY_ID", "NEXT_ACTION"],
            "All task overlap rows",
        )
    elif active_view == "Long DML":
        _render_named_frame(
            "contention_long_dml",
            "Long or blocked DML",
            ["SEVERITY", "ROOT_CAUSE", "QUERY_ID", "QUERY_TYPE", "ELAPSED_SECONDS", "BLOCKED_SECONDS", "NEXT_ACTION"],
            "All long DML rows",
        )
    else:
        _render_named_frame(
            "contention_task_mapping",
            "Blocked query to task map",
            [
                "SEVERITY",
                "ROOT_CAUSE",
                "QUERY_ID",
                "TASK_NAME",
                "USER_NAME",
                "WAREHOUSE_NAME",
                "BLOCKED_SECONDS",
                "WAIT_OBJECTS",
                "NEXT_ACTION",
                "VERIFY_AFTER_FIX",
            ],
            "All blocked query mapping rows",
        )
