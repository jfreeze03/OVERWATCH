"""Contention center: lock waits, task overlap, long DML, and queueing proof."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import streamlit as st

from sections.navigation import apply_navigation_state
from sections.shell_helpers import render_escaped_bold_text, render_shell_snapshot
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
    sql_literal,
)
from utils.section_guidance import defer_section_note
from utils.workflows import render_load_status, render_mode_selector


CONTENTION_CENTER_VIEWS = (
    "Brief",
    "Live Incident",
    "Active Locks",
    "Historical Waits",
    "Table Hotspots",
    "Task Overlap",
    "Long DML",
    "Query -> Task Map",
)

CONTENTION_VIEW_DETAILS = {
    "Brief": "One ranked decision view: lock contention, task overlap, long DML, or warehouse queueing.",
    "Live Incident": "Read-only current blockers: SHOW locks/transactions, recent blocked or queued queries, current task graphs, and warehouse load.",
    "Active Locks": "Live SHOW LOCKS evidence for the current incident window.",
    "Historical Waits": "LOCK_WAIT_HISTORY trend evidence for repeated table/object contention.",
    "Table Hotspots": "Objects repeatedly showing wait time, waiter volume, and blocker volume.",
    "Task Overlap": "Task runs that overlap with themselves and should be serialized or rescheduled.",
    "Long DML": "MERGE/UPDATE/DELETE/INSERT/COPY statements likely to hold locks for too long.",
    "Query -> Task Map": "Blocked query IDs mapped back to Snowflake task runs where possible.",
}

CONTENTION_STATE_KEYS = (
    "contention_active_locks",
    "contention_live_transactions",
    "contention_live_queries",
    "contention_live_task_graphs",
    "contention_live_warehouse_load",
    "contention_live_decision_rows",
    "contention_live_source_errors",
    "contention_live_snapshot_meta",
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
    """Return blocked queries mapped to task route context when TASK_HISTORY exposes the query ID."""
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


def build_live_query_incident_sql(minutes: int = 30, warehouse_name: str = "") -> str:
    """Return recent blocked, queued, or running query evidence from Information Schema."""
    minutes = max(5, min(int(minutes or 30), 240))
    warehouse_filter = ""
    if str(warehouse_name or "").strip():
        warehouse_filter = f"AND WAREHOUSE_NAME = {sql_literal(str(warehouse_name), 200)}"
    return f"""
SELECT
    CURRENT_TIMESTAMP() AS SNAPSHOT_TS,
    QUERY_ID,
    USER_NAME,
    ROLE_NAME,
    WAREHOUSE_NAME,
    DATABASE_NAME,
    SCHEMA_NAME,
    QUERY_TYPE,
    START_TIME,
    END_TIME,
    EXECUTION_STATUS,
    TOTAL_ELAPSED_TIME / 1000.0 AS ELAPSED_SECONDS,
    COALESCE(QUEUED_OVERLOAD_TIME, 0) / 1000.0 AS QUEUED_OVERLOAD_SECONDS,
    COALESCE(QUEUED_PROVISIONING_TIME, 0) / 1000.0 AS QUEUED_PROVISIONING_SECONDS,
    COALESCE(TRANSACTION_BLOCKED_TIME, 0) / 1000.0 AS BLOCKED_SECONDS,
    LEFT(QUERY_TEXT, 1200) AS QUERY_TEXT,
    CASE
      WHEN COALESCE(TRANSACTION_BLOCKED_TIME, 0) >= 300000 THEN 'Critical'
      WHEN COALESCE(TRANSACTION_BLOCKED_TIME, 0) >= 60000 THEN 'High'
      WHEN COALESCE(QUEUED_OVERLOAD_TIME, 0) > 0 THEN 'Medium'
      ELSE 'Watch'
    END AS SEVERITY,
    CASE
      WHEN COALESCE(TRANSACTION_BLOCKED_TIME, 0) > 0 THEN 'Live blocked query'
      WHEN COALESCE(QUEUED_OVERLOAD_TIME, 0) > 0 THEN 'Live warehouse queueing'
      ELSE 'Live running query'
    END AS ROOT_CAUSE
FROM TABLE(
    INFORMATION_SCHEMA.QUERY_HISTORY(
        END_TIME_RANGE_START => DATEADD('minute', -{minutes}, CURRENT_TIMESTAMP()),
        END_TIME_RANGE_END => CURRENT_TIMESTAMP(),
        RESULT_LIMIT => 1000
    )
)
WHERE (
        EXECUTION_STATUS IN ('RUNNING', 'QUEUED', 'BLOCKED')
        OR COALESCE(TRANSACTION_BLOCKED_TIME, 0) > 0
        OR COALESCE(QUEUED_OVERLOAD_TIME, 0) > 0
      )
  {warehouse_filter}
ORDER BY BLOCKED_SECONDS DESC, QUEUED_OVERLOAD_SECONDS DESC, ELAPSED_SECONDS DESC
LIMIT 200
"""


def build_live_task_graphs_sql(root_task_name: str = "") -> str:
    """Return currently executing or scheduled task graph evidence."""
    root_filter = ""
    if str(root_task_name or "").strip():
        root_filter = f"WHERE ROOT_TASK_NAME = {sql_literal(str(root_task_name), 500)}"
    return f"""
SELECT
    CURRENT_TIMESTAMP() AS SNAPSHOT_TS,
    *
FROM TABLE(INFORMATION_SCHEMA.CURRENT_TASK_GRAPHS())
{root_filter}
LIMIT 200
"""


def build_live_warehouse_load_sql(minutes: int = 30, warehouse_name: str = "") -> str:
    """Return warehouse pressure evidence for the live incident window."""
    minutes = max(5, min(int(minutes or 30), 240))
    warehouse = str(warehouse_name or "").strip()
    if warehouse:
        return f"""
SELECT
    CURRENT_TIMESTAMP() AS SNAPSHOT_TS,
    WAREHOUSE_NAME,
    START_TIME,
    END_TIME,
    AVG_RUNNING,
    AVG_QUEUED_LOAD,
    AVG_QUEUED_PROVISIONING,
    AVG_BLOCKED,
    CASE
      WHEN AVG_BLOCKED > 0 THEN 'High'
      WHEN AVG_QUEUED_LOAD > 0 THEN 'Medium'
      ELSE 'Info'
    END AS SEVERITY,
    CASE
      WHEN AVG_BLOCKED > 0 THEN 'Live blocked warehouse load'
      WHEN AVG_QUEUED_LOAD > 0 THEN 'Live warehouse queueing'
      ELSE 'No live warehouse pressure'
    END AS ROOT_CAUSE
FROM TABLE(
    INFORMATION_SCHEMA.WAREHOUSE_LOAD_HISTORY(
        DATE_RANGE_START => DATEADD('minute', -{minutes}, CURRENT_TIMESTAMP()),
        DATE_RANGE_END => DATEADD('minute', -1, CURRENT_TIMESTAMP()),
        WAREHOUSE_NAME => {sql_literal(warehouse, 200)}
    )
)
ORDER BY START_TIME DESC
LIMIT 200
"""
    return f"""
SELECT
    CURRENT_TIMESTAMP() AS SNAPSHOT_TS,
    WAREHOUSE_NAME,
    START_TIME,
    END_TIME,
    AVG_RUNNING,
    AVG_QUEUED_LOAD,
    AVG_QUEUED_PROVISIONING,
    AVG_BLOCKED,
    CASE
      WHEN AVG_BLOCKED > 0 THEN 'High'
      WHEN AVG_QUEUED_LOAD > 0 THEN 'Medium'
      ELSE 'Info'
    END AS SEVERITY,
    CASE
      WHEN AVG_BLOCKED > 0 THEN 'Recent blocked warehouse load'
      WHEN AVG_QUEUED_LOAD > 0 THEN 'Recent warehouse queueing'
      ELSE 'No recent warehouse pressure'
    END AS ROOT_CAUSE
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY
WHERE START_TIME >= DATEADD('minute', -{minutes}, CURRENT_TIMESTAMP())
  AND (COALESCE(AVG_QUEUED_LOAD, 0) > 0 OR COALESCE(AVG_BLOCKED, 0) > 0)
ORDER BY AVG_BLOCKED DESC, AVG_QUEUED_LOAD DESC, START_TIME DESC
LIMIT 200
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


def _normalize_contention_view_state() -> None:
    legacy_view = st.session_state.get("contention_active_view")
    current_view = st.session_state.get("contention_center_view")
    if current_view in CONTENTION_CENTER_VIEWS:
        return
    if legacy_view in CONTENTION_CENTER_VIEWS:
        st.session_state["contention_center_view"] = legacy_view


def _focus_query_id() -> str:
    return str(st.session_state.get("contention_focus_query_id") or "").strip()


def _focus_handoff_frame(frame: pd.DataFrame, focus_query_id: str = "") -> pd.DataFrame:
    view = _safe_frame(frame)
    focus = str(focus_query_id or "").strip()
    if view.empty or not focus:
        return view
    query_columns = [
        column for column in (
            "QUERY_ID",
            "WAITER_QUERY_ID",
            "BLOCKER_QUERY_ID",
            "TASK_QUERY_ID",
            "RUN_1_QUERY_ID",
            "RUN_2_QUERY_ID",
        )
        if column in view.columns
    ]
    if not query_columns:
        return view
    focused = view.copy()
    match = pd.Series(False, index=focused.index)
    for column in query_columns:
        match = match | focused[column].astype(str).str.strip().eq(focus)
    if not bool(match.any()):
        focused["HANDOFF_MATCH"] = ""
        return focused
    focused["HANDOFF_MATCH"] = match.map({True: "Selected query", False: ""})
    return focused.sort_values("HANDOFF_MATCH", ascending=False, kind="stable")


def _render_handoff_context(frame: pd.DataFrame, *, source: str) -> None:
    focus = _focus_query_id()
    if not focus:
        return
    focused = _focus_handoff_frame(frame, focus)
    matched = int(focused.get("HANDOFF_MATCH", pd.Series(dtype=str)).astype(str).eq("Selected query").sum())
    if matched:
        st.caption(f"Handoff query {focus} matched {matched:,} {source.lower()} row(s). Review the matched row before changing compute.")
    else:
        st.caption(f"Handoff query {focus} is queued for contention telemetry. Load telemetry or capture a live incident to find the blocker.")


def _contention_target_object(row: dict | pd.Series | None) -> str:
    row = row if row is not None else {}
    parts = [
        str(row.get("DATABASE_NAME") or "").strip(),
        str(row.get("SCHEMA_NAME") or "").strip(),
        str(row.get("OBJECT_NAME") or "").strip(),
    ]
    target = ".".join(part for part in parts if part and part.lower() != "nan")
    if target:
        return target
    wait_objects = str(row.get("WAIT_OBJECTS") or "").strip()
    if wait_objects and wait_objects.lower() != "nan":
        return wait_objects.split(",")[0].strip()
    query_text = str(row.get("QUERY_TEXT") or "")
    if not query_text:
        return ""
    import re

    pattern = re.compile(
        r"\b(?:MERGE\s+INTO|UPDATE|DELETE\s+FROM|INSERT\s+INTO|COPY\s+INTO)\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*){0,2})",
        re.IGNORECASE,
    )
    match = pattern.search(query_text)
    return match.group(1).strip() if match else ""


def _contention_fix_fields(signal: str, row: dict | pd.Series | None = None) -> dict[str, str]:
    row = row if row is not None else {}
    signal_text = str(signal or row.get("ROOT_CAUSE") or "").upper()
    target = _contention_target_object(row)
    query_id = str(row.get("QUERY_ID") or row.get("WAITER_QUERY_ID") or "").strip()
    warehouse = str(row.get("WAREHOUSE_NAME") or "").strip()

    fields = {
        "BOTTLENECK_TYPE": "Contention investigation",
        "OWNER_ROUTE": "Contention Center",
        "FIRST_MOVE": "Load active locks, identify the blocker, and confirm whether this is lock wait, task overlap, or queueing.",
        "SAFE_FIX": "Capture telemetry before canceling work; change one scheduling or write-path control at a time.",
        "COMPUTE_DECISION": "Do not resize until blocked seconds are separated from queued load.",
        "PROOF_REQUIRED": "SHOW LOCKS, LOCK_WAIT_HISTORY, QUERY_HISTORY, TASK_HISTORY, and WAREHOUSE_LOAD_HISTORY.",
        "TARGET_OBJECT": target,
        "QUERY_ID": query_id,
        "WAITER_QUERY_ID": str(row.get("WAITER_QUERY_ID") or query_id).strip(),
        "RUN_1_QUERY_ID": str(row.get("RUN_1_QUERY_ID") or "").strip(),
        "RUN_2_QUERY_ID": str(row.get("RUN_2_QUERY_ID") or "").strip(),
        "TASK_QUERY_ID": str(row.get("TASK_QUERY_ID") or "").strip(),
        "WAREHOUSE_NAME": warehouse,
        "WAITER_TRANSACTION_ID": str(row.get("WAITER_TRANSACTION_ID") or "").strip(),
        "BLOCKER_TRANSACTION_ID": str(row.get("BLOCKER_TRANSACTION_ID") or "").strip(),
        "TRANSACTION_ID": str(row.get("TRANSACTION_ID") or row.get("TRANSACTION") or row.get("ID") or "").strip(),
    }
    if "TASK-OWNED" in signal_text or "TASK OVERLAP" in signal_text:
        fields.update({
            "BOTTLENECK_TYPE": "Task graph overlap / blocked task write",
            "OWNER_ROUTE": "Task graphs",
            "FIRST_MOVE": "Open Task graphs, find the overlapping root task/window, and pause or reschedule only the colliding graph.",
            "SAFE_FIX": "Set OVERLAP_POLICY = NO_OVERLAP on the root task or widen the schedule; keep parallel reads/transforms but serialize the final shared-table publish.",
            "COMPUTE_DECISION": "Task overlap is a scheduling/write-path problem first; bigger compute can make overlap happen faster.",
            "PROOF_REQUIRED": "TASK_HISTORY run windows, blocked task query ID, target table, and next successful non-overlapping run.",
        })
    elif "HOT LOCKED OBJECT" in signal_text:
        fields.update({
            "BOTTLENECK_TYPE": "Repeated table/object lock hotspot",
            "OWNER_ROUTE": "Contention Center",
            "FIRST_MOVE": "Name the shared target object and identify every writer touching it in the same window.",
            "SAFE_FIX": "Move parallel writers into isolated staging tables and use one downstream publish/MERGE task for the shared target.",
            "COMPUTE_DECISION": "Repeated object waits are lock telemetry; bigger warehouse will not release a blocker transaction.",
            "PROOF_REQUIRED": "LOCK_WAIT_HISTORY total wait seconds by object plus writer query/task IDs before and after the schedule change.",
        })
    elif "LOCK WAIT" in signal_text or "BLOCKED" in signal_text:
        fields.update({
            "BOTTLENECK_TYPE": "Lock wait / blocked transaction",
            "OWNER_ROUTE": "Active Locks",
            "FIRST_MOVE": "Run Check Active Locks Now, identify blocker transaction/session, then stop overlapping writers to the same object.",
            "SAFE_FIX": "Shorten the write transaction, stage transforms before the final write, and batch large MERGE/UPDATE/DELETE work by date, hash bucket, tenant, or batch id.",
            "COMPUTE_DECISION": "Blocked seconds are transaction wait; do not resize solely because a query is blocked.",
            "PROOF_REQUIRED": "SHOW LOCKS, LOCK_WAIT_HISTORY waiter/blocker IDs, and QUERY_HISTORY TRANSACTION_BLOCKED_TIME returning to zero.",
        })
    elif "WAREHOUSE QUEUE" in signal_text or "QUEUEING" in signal_text:
        fields.update({
            "BOTTLENECK_TYPE": "Warehouse queue pressure",
            "OWNER_ROUTE": "Cost & Contract",
            "FIRST_MOVE": "Check active query concurrency and WAREHOUSE_LOAD_HISTORY before changing SQL or task ordering.",
            "SAFE_FIX": "Use workload isolation, multi-cluster, or right-sized compute only when queued load is present and blocked seconds are not the dominant signal.",
            "COMPUTE_DECISION": "This is compute concurrency telemetry; resizing or isolation may help if lock waits are not driving the delay.",
            "PROOF_REQUIRED": "WAREHOUSE_LOAD_HISTORY AVG_QUEUED_LOAD and QUERY_HISTORY QUEUED_OVERLOAD_TIME before and after the change.",
        })
    elif "LONG DML" in signal_text:
        fields.update({
            "BOTTLENECK_TYPE": "Long DML lock window",
            "OWNER_ROUTE": "Query diagnosis",
            "FIRST_MOVE": "Open Query Diagnosis for the DML query ID and identify the target table plus longest write step.",
            "SAFE_FIX": "Do heavy transforms outside the transaction, then run a smaller final write; split large MERGE/UPDATE/DELETE into bounded batches.",
            "COMPUTE_DECISION": "Long elapsed DML can hold locks; check queue time separately before treating this as compute.",
            "PROOF_REQUIRED": "QUERY_HISTORY elapsed/blocked seconds, target object, and rerun showing shorter write window.",
        })
    return fields


def _contention_precheck_sql(
    *,
    query_id: str = "",
    transaction_id: str = "",
    blocker_transaction_id: str = "",
    target_object: str = "",
    warehouse_name: str = "",
    include_locks: bool = False,
    include_tasks: bool = False,
    include_warehouse: bool = False,
) -> str:
    """Build read-only SQL that must be reviewed before a guarded cleanup action."""
    query_id = str(query_id or "").strip()
    transaction_id = str(transaction_id or "").strip()
    blocker_transaction_id = str(blocker_transaction_id or transaction_id or "").strip()
    target_object = str(target_object or "").strip()
    warehouse_name = str(warehouse_name or "").strip()
    statements: list[str] = []

    if query_id:
        statements.append(
            "\n".join([
                "-- Precheck selected query state before any cancel decision",
                "SELECT",
                "    QUERY_ID, USER_NAME, ROLE_NAME, WAREHOUSE_NAME, EXECUTION_STATUS,",
                "    TRANSACTION_BLOCKED_TIME / 1000.0 AS BLOCKED_SECONDS,",
                "    QUEUED_OVERLOAD_TIME / 1000.0 AS QUEUED_SECONDS,",
                "    ERROR_MESSAGE, LEFT(QUERY_TEXT, 1000) AS QUERY_TEXT_SAMPLE",
                "FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                "WHERE START_TIME >= DATEADD('hour', -4, CURRENT_TIMESTAMP())",
                f"  AND QUERY_ID = {sql_literal(query_id, 120)}",
                "ORDER BY START_TIME DESC",
                "LIMIT 5;",
            ])
        )

    if include_locks or blocker_transaction_id or target_object:
        filters = []
        if query_id:
            filters.append(f"WAITER_QUERY_ID = {sql_literal(query_id, 120)}")
        if blocker_transaction_id:
            filters.append(f"BLOCKER_TRANSACTION_ID = {sql_literal(blocker_transaction_id, 120)}")
        if target_object:
            filters.append(
                "DATABASE_NAME || '.' || SCHEMA_NAME || '.' || OBJECT_NAME ILIKE "
                f"{sql_literal(target_object, 500)}"
            )
        where_extra = "\n  AND (" + "\n       OR ".join(filters) + ")" if filters else ""
        statements.append(
            "\n".join([
                "-- Precheck lock telemetry and blocker/waiter relationship",
                "SELECT",
                "    START_TIME, END_TIME, DATABASE_NAME, SCHEMA_NAME, OBJECT_NAME,",
                "    WAITER_TRANSACTION_ID, BLOCKER_TRANSACTION_ID, WAITER_QUERY_ID,",
                "    DATEDIFF('second', START_TIME, COALESCE(END_TIME, CURRENT_TIMESTAMP())) AS WAIT_SECONDS",
                "FROM SNOWFLAKE.ACCOUNT_USAGE.LOCK_WAIT_HISTORY",
                "WHERE START_TIME >= DATEADD('hour', -4, CURRENT_TIMESTAMP())" + where_extra,
                "ORDER BY START_TIME DESC",
                "LIMIT 50;",
            ])
        )

    if transaction_id or blocker_transaction_id:
        statements.append(
            "\n".join([
                "-- Precheck active transaction and lock ownership in the current incident",
                "SHOW TRANSACTIONS IN ACCOUNT;",
                "SHOW LOCKS IN ACCOUNT;",
                f"-- Confirm transaction id: {blocker_transaction_id or transaction_id}",
            ])
        )

    if include_tasks and query_id:
        statements.append(
            "\n".join([
                "-- Precheck task route context for the blocked or overlapping query",
                "SELECT",
                "    DATABASE_NAME, SCHEMA_NAME, NAME AS TASK_NAME, STATE,",
                "    QUERY_ID, SCHEDULED_TIME, QUERY_START_TIME, COMPLETED_TIME, ERROR_MESSAGE",
                "FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY",
                "WHERE SCHEDULED_TIME >= DATEADD('hour', -8, CURRENT_TIMESTAMP())",
                f"  AND QUERY_ID = {sql_literal(query_id, 120)}",
                "ORDER BY SCHEDULED_TIME DESC",
                "LIMIT 20;",
            ])
        )

    if include_warehouse or warehouse_name:
        warehouse_filter = (
            f"\n  AND WAREHOUSE_NAME = {sql_literal(warehouse_name, 255)}"
            if warehouse_name else ""
        )
        statements.append(
            "\n".join([
                "-- Precheck warehouse queue pressure before treating this as compute",
                "SELECT",
                "    START_TIME, END_TIME, WAREHOUSE_NAME, AVG_RUNNING, AVG_QUEUED_LOAD, AVG_BLOCKED",
                "FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY",
                "WHERE START_TIME >= DATEADD('hour', -4, CURRENT_TIMESTAMP())" + warehouse_filter,
                "ORDER BY START_TIME DESC",
                "LIMIT 24;",
            ])
        )

    return "\n\n".join(statements)


def _contention_verify_sql(
    *,
    query_id: str = "",
    transaction_id: str = "",
    blocker_transaction_id: str = "",
    target_object: str = "",
    warehouse_name: str = "",
    include_locks: bool = False,
    include_tasks: bool = False,
    include_warehouse: bool = False,
) -> str:
    """Build read-only SQL to confirm the incident cleared after a guarded or routed fix."""
    query_id = str(query_id or "").strip()
    transaction_id = str(transaction_id or "").strip()
    blocker_transaction_id = str(blocker_transaction_id or transaction_id or "").strip()
    target_object = str(target_object or "").strip()
    warehouse_name = str(warehouse_name or "").strip()
    statements: list[str] = []

    if query_id:
        statements.append(
            "\n".join([
                "-- Verify selected query is no longer blocked or running unexpectedly",
                "SELECT",
                "    QUERY_ID, EXECUTION_STATUS, ERROR_MESSAGE,",
                "    TRANSACTION_BLOCKED_TIME / 1000.0 AS BLOCKED_SECONDS,",
                "    QUEUED_OVERLOAD_TIME / 1000.0 AS QUEUED_SECONDS, END_TIME",
                "FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                "WHERE START_TIME >= DATEADD('hour', -4, CURRENT_TIMESTAMP())",
                f"  AND QUERY_ID = {sql_literal(query_id, 120)}",
                "ORDER BY START_TIME DESC",
                "LIMIT 5;",
            ])
        )

    if include_locks or blocker_transaction_id or target_object:
        filters = []
        if query_id:
            filters.append(f"WAITER_QUERY_ID = {sql_literal(query_id, 120)}")
        if blocker_transaction_id:
            filters.append(f"BLOCKER_TRANSACTION_ID = {sql_literal(blocker_transaction_id, 120)}")
        if target_object:
            filters.append(
                "DATABASE_NAME || '.' || SCHEMA_NAME || '.' || OBJECT_NAME ILIKE "
                f"{sql_literal(target_object, 500)}"
            )
        where_extra = "\n  AND (" + "\n       OR ".join(filters) + ")" if filters else ""
        statements.append(
            "\n".join([
                "-- Verify lock wait rows stopped accumulating for the selected incident",
                "SELECT",
                "    COUNT(*) AS RECENT_WAIT_EVENTS,",
                "    COALESCE(MAX(DATEDIFF('second', START_TIME, COALESCE(END_TIME, CURRENT_TIMESTAMP()))), 0) AS MAX_WAIT_SECONDS",
                "FROM SNOWFLAKE.ACCOUNT_USAGE.LOCK_WAIT_HISTORY",
                "WHERE START_TIME >= DATEADD('minute', -30, CURRENT_TIMESTAMP())" + where_extra + ";",
            ])
        )

    if transaction_id or blocker_transaction_id:
        statements.append(
            "\n".join([
                "-- Verify blocker transaction is gone from live transaction and lock lists",
                "SHOW TRANSACTIONS IN ACCOUNT;",
                "SHOW LOCKS IN ACCOUNT;",
                f"-- Confirm transaction id is absent: {blocker_transaction_id or transaction_id}",
            ])
        )

    if include_tasks and query_id:
        statements.append(
            "\n".join([
                "-- Verify the task-owned query reran or cleared without another overlap",
                "SELECT",
                "    DATABASE_NAME, SCHEMA_NAME, NAME AS TASK_NAME, STATE, QUERY_ID,",
                "    SCHEDULED_TIME, QUERY_START_TIME, COMPLETED_TIME, ERROR_MESSAGE",
                "FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY",
                "WHERE SCHEDULED_TIME >= DATEADD('hour', -8, CURRENT_TIMESTAMP())",
                f"  AND QUERY_ID = {sql_literal(query_id, 120)}",
                "ORDER BY SCHEDULED_TIME DESC",
                "LIMIT 20;",
            ])
        )

    if include_warehouse or warehouse_name:
        warehouse_filter = (
            f"\n  AND WAREHOUSE_NAME = {sql_literal(warehouse_name, 255)}"
            if warehouse_name else ""
        )
        statements.append(
            "\n".join([
                "-- Verify queue pressure reduced after isolation or capacity action",
                "SELECT",
                "    START_TIME, END_TIME, WAREHOUSE_NAME, AVG_RUNNING, AVG_QUEUED_LOAD, AVG_BLOCKED",
                "FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY",
                "WHERE START_TIME >= DATEADD('hour', -2, CURRENT_TIMESTAMP())" + warehouse_filter,
                "ORDER BY START_TIME DESC",
                "LIMIT 24;",
            ])
        )

    return "\n\n".join(statements)


def build_contention_safe_action_contract(row: dict | pd.Series | None, signal: str = "") -> dict[str, str]:
    """Return the guarded action contract for a contention row without executing SQL."""
    row = row if row is not None else {}
    signal_text = str(signal or _first_value(row, "SIGNAL", "ROOT_CAUSE", default="")).upper()
    route = str(_first_value(row, "OWNER_ROUTE", default="Contention Center") or "Contention Center")
    query_id = str(_first_value(row, "QUERY_ID", "WAITER_QUERY_ID", default="")).strip()
    blocker_tx = str(_first_value(row, "BLOCKER_TRANSACTION_ID", default="")).strip()
    transaction_id = str(_first_value(row, "TRANSACTION_ID", "TRANSACTION", "ID", default="")).strip()
    target = str(_first_value(row, "TARGET_OBJECT", "ENTITY", default="")).strip()
    warehouse = str(_first_value(row, "WAREHOUSE_NAME", default="")).strip()
    blocked = max(
        safe_float(_first_value(row, "BLOCKED_SECONDS", default=0)),
        safe_float(_first_value(row, "WAIT_SECONDS", default=0)),
        safe_float(_first_value(row, "MAX_LOCK_WAIT_SECONDS", default=0)),
    )
    queued = max(
        safe_float(_first_value(row, "QUEUED_OVERLOAD_SECONDS", default=0)),
        safe_float(_first_value(row, "MAX_QUEUED_LOAD", default=0)),
    )

    action_type = "Hold and gather telemetry"
    readiness = "Blocked - identify blocker"
    manual_sql = ""
    confirmation = "No cancel action"
    prechecks = (
        "Confirm query or transaction identity, owner, target object, business impact, "
        "and ticket/review before cleanup."
    )
    when_not_to_run = (
        "Do not cancel or abort for pure warehouse queueing, unknown ownership, or missing "
        "query/transaction identity."
    )
    approval_gate = (
        "DBA on-call acknowledgement, current telemetry, and incident/ticket reference required "
        "before any guarded cleanup SQL."
    )
    audit_evidence = (
        "Save precheck result, selected query or transaction ID, copied action SQL, "
        "executor, timestamp, post-action Query History or lock telemetry, and status query result."
    )
    recovery_plan = (
        "Monitor dependent workload, capture post-action Query History and lock telemetry, and route "
        "retry/recovery to the owning team."
    )
    execution_boundary = (
        "OVERWATCH displays action SQL only; execute from a Snowflake worksheet or DBA runbook "
        "after review."
    )
    verification = (
        "Refresh active locks and Query History; blocked seconds should clear and the owner "
        "should confirm the dependent workload recovered."
    )
    precheck_sql = _contention_precheck_sql(
        query_id=query_id,
        transaction_id=transaction_id,
        blocker_transaction_id=blocker_tx,
        target_object=target,
        warehouse_name=warehouse,
    )
    verify_sql = _contention_verify_sql(
        query_id=query_id,
        transaction_id=transaction_id,
        blocker_transaction_id=blocker_tx,
        target_object=target,
        warehouse_name=warehouse,
    )

    if route in {"Warehouse Health", "Cost & Contract"} or ("QUEUE" in signal_text and blocked <= 0 and queued > 0):
        action_type = "No cancel - capacity review"
        readiness = "Route to Cost & Contract"
        approval_gate = "Warehouse telemetry review required before resize, isolation, or schedule change. No cleanup SQL."
        audit_evidence = "Save warehouse load history before and after, owner decision, change ticket, and cost note."
        recovery_plan = "Use Cost & Contract capacity/isolation telemetry, then confirm queued load and blocked load fall."
        execution_boundary = "No cancel or abort SQL is generated for pure warehouse queueing."
        verification = "Confirm AVG_QUEUED_LOAD and QUEUED_OVERLOAD_TIME fall after capacity or isolation change."
        precheck_sql = _contention_precheck_sql(
            query_id=query_id,
            target_object=target,
            warehouse_name=warehouse,
            include_warehouse=True,
        )
        verify_sql = _contention_verify_sql(
            query_id=query_id,
            target_object=target,
            warehouse_name=warehouse,
            include_warehouse=True,
        )
    elif blocker_tx:
        action_type = "Abort blocker transaction candidate"
        readiness = "Ready for DBA review"
        manual_sql = f"SELECT SYSTEM$ABORT_TRANSACTION({sql_literal(blocker_tx, 120)});"
        confirmation = "Type ABORT TRANSACTION in the guarded DBA flow."
        approval_gate = (
            "Application/data review, DBA on-call acknowledgement, and incident ticket required; "
            "confirm rollback impact before abort."
        )
        recovery_plan = (
            "Confirm lock release, confirm dependent workload outcome, and coordinate retry or data repair "
            "through the blocker route."
        )
        prechecks = (
            "Confirm the blocker transaction is still active, owns the lock, belongs to the expected "
            "user/workload, and can be rolled back without data loss."
        )
        verification = "Run SHOW LOCKS and SHOW TRANSACTIONS again; the blocker transaction should disappear."
        precheck_sql = _contention_precheck_sql(
            transaction_id=blocker_tx,
            blocker_transaction_id=blocker_tx,
            target_object=target,
            warehouse_name=warehouse,
            include_locks=True,
        )
        verify_sql = _contention_verify_sql(
            transaction_id=blocker_tx,
            blocker_transaction_id=blocker_tx,
            target_object=target,
            warehouse_name=warehouse,
            include_locks=True,
        )
    elif transaction_id and ("ACTIVE LOCK" in signal_text or "TRANSACTION" in signal_text):
        action_type = "Abort active transaction candidate"
        readiness = "Ready for DBA review"
        manual_sql = f"SELECT SYSTEM$ABORT_TRANSACTION({sql_literal(transaction_id, 120)});"
        confirmation = "Type ABORT TRANSACTION in the guarded DBA flow."
        approval_gate = (
            "Application/data review, DBA on-call acknowledgement, and incident ticket required; "
            "confirm the transaction is the blocker before abort."
        )
        recovery_plan = (
            "Confirm lock release, confirm waiters resumed or failed cleanly, and assign retry/recovery "
            "to the workload route."
        )
        prechecks = (
            "Confirm this transaction is the blocker, not merely a waiter, and get review "
            "before aborting."
        )
        verification = "Run SHOW LOCKS and SHOW TRANSACTIONS again; dependent blocked queries should resume or fail cleanly."
        precheck_sql = _contention_precheck_sql(
            transaction_id=transaction_id,
            blocker_transaction_id=transaction_id,
            target_object=target,
            warehouse_name=warehouse,
            include_locks=True,
        )
        verify_sql = _contention_verify_sql(
            transaction_id=transaction_id,
            blocker_transaction_id=transaction_id,
            target_object=target,
            warehouse_name=warehouse,
            include_locks=True,
        )
    elif route == "Task graphs" or "TASK" in signal_text:
        action_type = "Task schedule cleanup"
        readiness = "Route to Task graphs"
        approval_gate = "Task route or scheduler review required before changing graph timing or retry behavior."
        audit_evidence = "Save task graph overlap telemetry, schedule decision, and next-run status."
        recovery_plan = "Serialize or reschedule the task graph, then confirm the next TASK_HISTORY run has no overlap."
        execution_boundary = "No task cancel is executed from Contention Center; route changes through Task graphs."
        prechecks = "Identify the root task, overlapping graph run, final shared target, and reviewed schedule change."
        verification = "Next TASK_HISTORY run should show no overlap and no blocked publish query."
        precheck_sql = _contention_precheck_sql(
            query_id=query_id,
            target_object=target,
            warehouse_name=warehouse,
            include_tasks=True,
        )
        verify_sql = _contention_verify_sql(
            query_id=query_id,
            target_object=target,
            warehouse_name=warehouse,
            include_tasks=True,
        )
    elif query_id and ("BLOCK" in signal_text or blocked > 0):
        action_type = "Cancel blocked query candidate"
        readiness = "Ready for DBA review"
        manual_sql = f"SELECT SYSTEM$CANCEL_QUERY({sql_literal(query_id, 120)});"
        confirmation = "Type CANCEL QUERY in the guarded DBA flow."
        approval_gate = (
            "Query route or application review and DBA on-call acknowledgement required; confirm whether "
            "the query is a waiter or blocker before cancel."
        )
        recovery_plan = (
            "Confirm cancellation state, watch whether the blocker remains, and route retry/recovery to the "
            "query route."
        )
        prechecks = (
            "Confirm whether this query is the blocker or the waiter. Canceling a waiter stops wasted runtime "
            "but does not release the blocker lock."
        )
        verification = "Query History should show the selected query canceled and blocked seconds should stop increasing."
        precheck_sql = _contention_precheck_sql(
            query_id=query_id,
            target_object=target,
            warehouse_name=warehouse,
            include_locks=True,
        )
        verify_sql = _contention_verify_sql(
            query_id=query_id,
            target_object=target,
            warehouse_name=warehouse,
            include_locks=True,
        )

    return {
        "ACTION_GUARDRAIL": "DBA-controlled action; OVERWATCH does not auto-cancel from this view.",
        "CLEANUP_DECISION": action_type,
        "CLEANUP_READINESS": readiness,
        "MANUAL_ACTION_SQL": manual_sql,
        "OPERATOR_CONFIRMATION": confirmation,
        "APPROVAL_GATE": approval_gate,
        "AUDIT_EVIDENCE_REQUIRED": audit_evidence,
        "RECOVERY_PLAN": recovery_plan,
        "EXECUTION_BOUNDARY": execution_boundary,
        "PRECHECKS": prechecks,
        "PRECHECK_SQL": precheck_sql,
        "WHEN_NOT_TO_RUN": when_not_to_run,
        "VERIFY_AFTER_CLEANUP": verification,
        "VERIFY_SQL": verify_sql,
        "CLEANUP_CONTEXT": "; ".join(
            part for part in [
                f"route={route}",
                f"target={target}" if target else "",
                f"warehouse={warehouse}" if warehouse else "",
                f"blocked={blocked:,.0f}s" if blocked else "",
                f"queued={queued:,.2f}" if queued else "",
            ] if part
        ),
    }


def _add_safe_action_contracts(decision: pd.DataFrame) -> pd.DataFrame:
    if decision.empty:
        return decision
    contracts = [
        build_contention_safe_action_contract(row, str(row.get("SIGNAL", "")))
        for row in decision.to_dict("records")
    ]
    contract_df = pd.DataFrame(contracts)
    for column in contract_df.columns:
        decision[column] = contract_df[column].values
    return decision


def build_contention_solution_summary(decision: pd.DataFrame | None) -> pd.DataFrame:
    """Collapse detailed contention evidence into DBA-first solution routes."""
    work = _safe_frame(decision)
    columns = [
        "SOLUTION_ROUTE",
        "OPEN_SIGNALS",
        "TOP_SEVERITY",
        "PRIMARY_ENTITY",
        "FIRST_ACTION",
        "PROOF_REQUIRED",
        "OWNER_ROUTE",
    ]
    if work.empty:
        return pd.DataFrame(columns=columns)
    if "_ROUTE_RANK" not in work.columns:
        work = work.copy()
        work["_ROUTE_RANK"] = work.get("SEVERITY", pd.Series([""] * len(work))).map(_severity_rank)
    route_defs = (
        (
            "Clean up blocker",
            work.get("CLEANUP_DECISION", pd.Series([""] * len(work))).astype(str).str.contains("Abort|Cancel", case=False, regex=True)
            | work.get("BOTTLENECK_TYPE", pd.Series([""] * len(work))).astype(str).str.contains("lock|blocked transaction", case=False, regex=True),
        ),
        (
            "Serialize task graph",
            work.get("BOTTLENECK_TYPE", pd.Series([""] * len(work))).astype(str).str.contains("task", case=False, regex=False)
            | work.get("SIGNAL", pd.Series([""] * len(work))).astype(str).str.contains("task", case=False, regex=False),
        ),
        (
            "Shorten DML transaction",
            work.get("BOTTLENECK_TYPE", pd.Series([""] * len(work))).astype(str).str.contains("Long DML", case=False, regex=False)
            | work.get("SIGNAL", pd.Series([""] * len(work))).astype(str).str.contains("Long DML", case=False, regex=False),
        ),
        (
            "Fix warehouse pressure",
            work.get("OWNER_ROUTE", pd.Series([""] * len(work))).astype(str).str.contains("Cost & Contract|Warehouse", case=False, regex=True)
            | work.get("SIGNAL", pd.Series([""] * len(work))).astype(str).str.contains("queue", case=False, regex=False),
        ),
    )
    rows: list[dict[str, object]] = []
    used = pd.Series([False] * len(work), index=work.index)
    for route, mask in route_defs:
        routed = work[mask.fillna(False)]
        used = used | mask.fillna(False)
        if routed.empty:
            continue
        top = routed.sort_values(["_ROUTE_RANK", "SIGNAL"], ascending=[True, True]).iloc[0]
        rows.append({
            "SOLUTION_ROUTE": route,
            "OPEN_SIGNALS": len(routed),
            "TOP_SEVERITY": str(top.get("SEVERITY") or "Watch"),
            "PRIMARY_ENTITY": str(top.get("TARGET_OBJECT") or top.get("ENTITY") or ""),
            "FIRST_ACTION": str(top.get("FIRST_MOVE") or top.get("NEXT_ACTION") or ""),
            "PROOF_REQUIRED": str(top.get("PROOF_REQUIRED") or top.get("VERIFY_AFTER_FIX") or ""),
            "OWNER_ROUTE": str(top.get("OWNER_ROUTE") or "Contention Center"),
        })
    remainder = work[~used]
    if not remainder.empty:
        top = remainder.sort_values(["_ROUTE_RANK", "SIGNAL"], ascending=[True, True]).iloc[0]
        rows.append({
            "SOLUTION_ROUTE": "Investigate remaining signal",
            "OPEN_SIGNALS": len(remainder),
            "TOP_SEVERITY": str(top.get("SEVERITY") or "Watch"),
            "PRIMARY_ENTITY": str(top.get("TARGET_OBJECT") or top.get("ENTITY") or ""),
            "FIRST_ACTION": str(top.get("FIRST_MOVE") or top.get("NEXT_ACTION") or ""),
            "PROOF_REQUIRED": str(top.get("PROOF_REQUIRED") or top.get("VERIFY_AFTER_FIX") or ""),
            "OWNER_ROUTE": str(top.get("OWNER_ROUTE") or "Contention Center"),
        })
    summary = pd.DataFrame(rows, columns=columns)
    if summary.empty:
        return summary
    summary["_RANK"] = summary["TOP_SEVERITY"].map(_severity_rank)
    return summary.sort_values(["_RANK", "OPEN_SIGNALS"], ascending=[True, False]).drop(columns=["_RANK"]).reset_index(drop=True)


def build_contention_top_fix_path(decision: pd.DataFrame | None) -> pd.DataFrame:
    """Return the single safest top-path row for the current contention incident."""
    work = _safe_frame(decision)
    columns = [
        "TOP_ROUTE",
        "TOP_SEVERITY",
        "ENTITY",
        "BLOCKER",
        "WAITER",
        "FIRST_SAFE_MOVE",
        "CLEANUP_DECISION",
        "APPROVAL_GATE",
        "PRECHECK_REQUIRED",
        "MANUAL_SQL_STATE",
        "VERIFY_AFTER",
        "WHEN_NOT_TO_RUN",
    ]
    if work.empty:
        return pd.DataFrame(columns=columns)
    if "_ROUTE_RANK" not in work.columns:
        work = work.copy()
        work["_ROUTE_RANK"] = work.get("SEVERITY", pd.Series([""] * len(work))).map(_severity_rank)
    for sort_column in ("HANDOFF_MATCH", "SIGNAL"):
        if sort_column not in work.columns:
            work[sort_column] = ""
    top = work.sort_values(["_ROUTE_RANK", "HANDOFF_MATCH", "SIGNAL"], ascending=[True, False, True]).iloc[0]
    manual_sql = str(top.get("MANUAL_ACTION_SQL") or "").strip()
    precheck_sql = str(top.get("PRECHECK_SQL") or "").strip()
    verify_sql = str(top.get("VERIFY_SQL") or "").strip()
    rows = [{
        "TOP_ROUTE": str(top.get("OWNER_ROUTE") or "Contention Center"),
        "TOP_SEVERITY": str(top.get("SEVERITY") or "Watch"),
        "ENTITY": str(top.get("TARGET_OBJECT") or top.get("ENTITY") or top.get("WAREHOUSE_NAME") or ""),
        "BLOCKER": _incident_blocker(top),
        "WAITER": _incident_waiter(top),
        "FIRST_SAFE_MOVE": str(top.get("FIRST_MOVE") or top.get("NEXT_ACTION") or ""),
        "CLEANUP_DECISION": str(top.get("CLEANUP_DECISION") or "Telemetry review"),
        "APPROVAL_GATE": str(top.get("APPROVAL_GATE") or "Current telemetry and review required."),
        "PRECHECK_REQUIRED": "Yes" if precheck_sql else "Load live telemetry first",
        "MANUAL_SQL_STATE": "Available after review" if manual_sql else "No cancel/abort SQL",
        "VERIFY_AFTER": str(top.get("VERIFY_AFTER_CLEANUP") or top.get("VERIFY_AFTER_FIX") or "Re-run contention telemetry."),
        "WHEN_NOT_TO_RUN": str(top.get("WHEN_NOT_TO_RUN") or "Do not run state-changing SQL without current blocker/waiter telemetry."),
        "PRECHECK_SQL": precheck_sql,
        "MANUAL_ACTION_SQL": manual_sql,
        "VERIFY_SQL": verify_sql,
    }]
    return pd.DataFrame(rows)


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
            entry = {
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
            }
            entry.update(_contention_fix_fields(str(entry["SIGNAL"]), row))
            rows.append(entry)

    if not table_hotspots.empty:
        for _, row in table_hotspots.head(10).iterrows():
            entry = {
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
            }
            entry.update(_contention_fix_fields(str(entry["SIGNAL"]), row))
            rows.append(entry)

    if not task_overlap.empty:
        for _, row in task_overlap.head(10).iterrows():
            entry = {
                "SEVERITY": row.get("SEVERITY", "High"),
                "SIGNAL": "Task overlap",
                "ENTITY": row.get("TASK_NAME", "Task"),
                "EVIDENCE": f"{safe_int(row.get('OVERLAP_SECONDS')):,} seconds overlapping; runs {row.get('RUN_1_QUERY_ID', '')} and {row.get('RUN_2_QUERY_ID', '')}",
                "NEXT_ACTION": row.get("NEXT_ACTION", ""),
                "VERIFY_AFTER_FIX": row.get("VERIFY_AFTER_FIX", ""),
            }
            entry.update(_contention_fix_fields(str(entry["SIGNAL"]), row))
            rows.append(entry)

    if not task_mapping.empty:
        for _, row in task_mapping.head(10).iterrows():
            owner = row.get("TASK_NAME") or row.get("USER_NAME") or "Blocked query"
            entry = {
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
            }
            entry.update(_contention_fix_fields(str(entry["SIGNAL"]), row))
            rows.append(entry)

    if not long_dml.empty:
        blocked_seconds = _numeric_series(long_dml, "BLOCKED_SECONDS")
        elapsed_seconds = _numeric_series(long_dml, "ELAPSED_SECONDS")
        dml = long_dml[(blocked_seconds > 0) | (elapsed_seconds >= 900)].head(10)
        for _, row in dml.iterrows():
            entry = {
                "SEVERITY": row.get("SEVERITY", "Medium"),
                "SIGNAL": row.get("ROOT_CAUSE", "Long DML"),
                "ENTITY": row.get("QUERY_ID", "Query"),
                "EVIDENCE": (
                    f"{safe_float(row.get('ELAPSED_SECONDS')):,.0f}s elapsed; "
                    f"{safe_float(row.get('BLOCKED_SECONDS')):,.0f}s blocked; {row.get('QUERY_TYPE', '')}"
                ),
                "NEXT_ACTION": row.get("NEXT_ACTION", ""),
                "VERIFY_AFTER_FIX": row.get("VERIFY_AFTER_FIX", ""),
            }
            entry.update(_contention_fix_fields(str(entry["SIGNAL"]), row))
            rows.append(entry)

    if not warehouse_pressure.empty:
        for _, row in warehouse_pressure.head(10).iterrows():
            entry = {
                "SEVERITY": row.get("SEVERITY", "Medium"),
                "SIGNAL": row.get("ROOT_CAUSE", "Warehouse pressure"),
                "ENTITY": row.get("WAREHOUSE_NAME", "Warehouse"),
                "EVIDENCE": (
                    f"max blocked {safe_float(row.get('MAX_BLOCKED')):,.2f}; "
                    f"max queued load {safe_float(row.get('MAX_QUEUED_LOAD')):,.2f}"
                ),
                "NEXT_ACTION": row.get("NEXT_ACTION", ""),
                "VERIFY_AFTER_FIX": "Confirm warehouse load and query blocked time clear after remediation.",
            }
            entry.update(_contention_fix_fields(str(entry["SIGNAL"]), row))
            rows.append(entry)

    decision = pd.DataFrame(rows)
    if decision.empty:
        return decision
    decision["_RANK"] = decision["SEVERITY"].map(_severity_rank)
    decision = decision.sort_values(["_RANK", "SIGNAL", "ENTITY"]).drop(columns=["_RANK"])
    decision = _add_safe_action_contracts(decision)
    return decision


def _first_value(row: dict | pd.Series, *names: str, default=""):
    for name in names:
        for candidate in (name, str(name).upper(), str(name).lower()):
            if candidate in row:
                value = row.get(candidate)
                try:
                    if pd.isna(value):
                        continue
                except Exception:
                    pass
                if value not in (None, ""):
                    return value
    return default


def _live_incident_rows(
    active_locks: pd.DataFrame | None,
    transactions: pd.DataFrame | None,
    live_queries: pd.DataFrame | None,
    task_graphs: pd.DataFrame | None,
    warehouse_load: pd.DataFrame | None,
) -> pd.DataFrame:
    """Rank current incident evidence from read-only live Snowflake sources."""
    rows: list[dict[str, object]] = []
    active_locks = _safe_frame(active_locks)
    transactions = _safe_frame(transactions)
    live_queries = _safe_frame(live_queries)
    task_graphs = _safe_frame(task_graphs)
    warehouse_load = _safe_frame(warehouse_load)

    for _, row in active_locks.head(10).iterrows():
        row_dict = row.to_dict()
        target = _first_value(row_dict, "RESOURCE", "OBJECT_NAME", "OBJECT", "LOCK_OBJECT", default="Active lock")
        transaction_id = _first_value(row_dict, "TRANSACTION", "TRANSACTION_ID", "ID", default="")
        user_name = _first_value(row_dict, "USER", "USER_NAME", default="")
        entry = {
            "SEVERITY": "High",
            "SIGNAL": "Active lock",
            "ENTITY": target,
            "EVIDENCE": f"transaction {transaction_id or 'unknown'}; user {user_name or 'unknown'}",
            "FIRST_MOVE": "Open Active Locks and identify the blocker transaction before canceling or retrying dependent work.",
            "SAFE_FIX": "Coordinate with the owning session; pause overlapping writers and shorten the final shared-table write window.",
            "COMPUTE_DECISION": "An active lock is transaction contention; resize only after blocked seconds are ruled out.",
            "PROOF_REQUIRED": "SHOW LOCKS, SHOW TRANSACTIONS, blocker owner, target object, and post-fix blocked seconds.",
            "OWNER_ROUTE": "Active Locks",
            "QUERY_ID": "",
            "WAREHOUSE_NAME": "",
            "TARGET_OBJECT": str(target or ""),
            "TRANSACTION_ID": str(transaction_id or ""),
        }
        rows.append(entry)

    for _, row in live_queries.head(20).iterrows():
        row_dict = row.to_dict()
        blocked = safe_float(_first_value(row_dict, "BLOCKED_SECONDS", default=0))
        queued = safe_float(_first_value(row_dict, "QUEUED_OVERLOAD_SECONDS", default=0))
        elapsed = safe_float(_first_value(row_dict, "ELAPSED_SECONDS", default=0))
        query_id = str(_first_value(row_dict, "QUERY_ID", default="")).strip()
        warehouse = str(_first_value(row_dict, "WAREHOUSE_NAME", default="")).strip()
        root_cause = str(_first_value(row_dict, "ROOT_CAUSE", default="Live query"))
        if blocked <= 0 and queued <= 0 and str(_first_value(row_dict, "EXECUTION_STATUS", default="")).upper() not in {"RUNNING", "QUEUED", "BLOCKED"}:
            continue
        severity = "Critical" if blocked >= 300 else "High" if blocked >= 60 else "Medium" if queued > 0 else "Watch"
        owner_route = "Active Locks" if blocked > 0 else "Cost & Contract" if queued > 0 else "Query diagnosis"
        first_move = (
            "Run active locks, identify blocker transaction/session, and stop overlapping writers to the same target."
            if blocked > 0
            else "Check warehouse load and running-query concurrency before changing SQL or task ordering."
            if queued > 0
            else "Open Query Diagnosis and inspect the running query profile before tuning."
        )
        safe_fix = (
            "Serialize final writes, batch the DML, or shorten transaction scope; do not resize solely on blocked seconds."
            if blocked > 0
            else "Use workload isolation, multi-cluster, or right-sized compute only when queued load is the dominant signal."
            if queued > 0
            else "Capture query ID, owner, and operator stats before cancel/retry decisions."
        )
        proof = (
            "SHOW LOCKS plus QUERY_HISTORY TRANSACTION_BLOCKED_TIME returning to zero."
            if blocked > 0
            else "WAREHOUSE_LOAD_HISTORY AVG_QUEUED_LOAD and QUERY_HISTORY QUEUED_OVERLOAD_TIME before/after."
            if queued > 0
            else "QUERY_HISTORY execution status and query profile telemetry."
        )
        rows.append({
            "SEVERITY": severity,
            "SIGNAL": root_cause,
            "ENTITY": query_id or warehouse or "Live query",
            "EVIDENCE": f"{elapsed:,.0f}s elapsed; {blocked:,.0f}s blocked; {queued:,.0f}s queued; warehouse {warehouse or 'unknown'}",
            "FIRST_MOVE": first_move,
            "SAFE_FIX": safe_fix,
            "COMPUTE_DECISION": (
                "Blocked query: transaction fix first."
                if blocked > 0 else "Queue pressure: compute/isolation may help after lock waits are ruled out."
                if queued > 0 else "Need profile telemetry before compute decision."
            ),
            "PROOF_REQUIRED": proof,
            "OWNER_ROUTE": owner_route,
            "QUERY_ID": query_id,
            "WAREHOUSE_NAME": warehouse,
            "TARGET_OBJECT": _contention_target_object(row_dict),
        })

    for _, row in task_graphs.head(10).iterrows():
        row_dict = row.to_dict()
        task_name = str(_first_value(row_dict, "ROOT_TASK_NAME", "TASK_NAME", "NAME", default="Task graph"))
        state = str(_first_value(row_dict, "STATE", "GRAPH_STATE", default="current"))
        rows.append({
            "SEVERITY": "High" if state.upper() in {"FAILED", "CANCELLED", "BLOCKED"} else "Medium",
            "SIGNAL": "Current task graph",
            "ENTITY": task_name,
            "EVIDENCE": f"state {state}; graph {_first_value(row_dict, 'GRAPH_RUN_GROUP_ID', 'GRAPH_ID', default='')}",
            "FIRST_MOVE": "Open Task graphs and confirm whether this graph overlaps with another run or shares a final write table.",
            "SAFE_FIX": "Pause or reschedule only the colliding graph; set OVERLAP_POLICY = NO_OVERLAP when graph instances collide.",
            "COMPUTE_DECISION": "Task graph overlap is scheduling/write-path first, not compute first.",
            "PROOF_REQUIRED": "CURRENT_TASK_GRAPHS, TASK_HISTORY run windows, root task, final target table, and next clean run.",
            "OWNER_ROUTE": "Task graphs",
            "QUERY_ID": str(_first_value(row_dict, "QUERY_ID", "GRAPH_RUN_GROUP_ID", default="")),
            "WAREHOUSE_NAME": "",
            "TARGET_OBJECT": "",
        })

    for _, row in warehouse_load.head(10).iterrows():
        row_dict = row.to_dict()
        blocked = safe_float(_first_value(row_dict, "AVG_BLOCKED", default=0))
        queued = safe_float(_first_value(row_dict, "AVG_QUEUED_LOAD", default=0))
        if blocked <= 0 and queued <= 0:
            continue
        warehouse = str(_first_value(row_dict, "WAREHOUSE_NAME", default="Warehouse"))
        rows.append({
            "SEVERITY": "High" if blocked > 0 else "Medium",
            "SIGNAL": "Live warehouse pressure",
            "ENTITY": warehouse,
            "EVIDENCE": f"avg blocked {blocked:,.2f}; avg queued load {queued:,.2f}",
            "FIRST_MOVE": "Compare warehouse pressure with live blocked queries before resizing.",
            "SAFE_FIX": "Use warehouse isolation or multi-cluster for queue pressure; use lock/task remediation when blocked load is present.",
            "COMPUTE_DECISION": "Queue pressure can justify compute changes only when lock waits are not the primary signal.",
            "PROOF_REQUIRED": "WAREHOUSE_LOAD_HISTORY AVG_BLOCKED/AVG_QUEUED_LOAD and matching live query blocked/queued seconds.",
            "OWNER_ROUTE": "Cost & Contract",
            "QUERY_ID": "",
            "WAREHOUSE_NAME": warehouse,
            "TARGET_OBJECT": "",
        })

    if transactions is not None and not transactions.empty and not rows:
        rows.append({
            "SEVERITY": "Watch",
            "SIGNAL": "Active transactions",
            "ENTITY": f"{len(transactions):,} transaction(s)",
            "EVIDENCE": "SHOW TRANSACTIONS returned rows but no lock/query pressure was classified.",
            "FIRST_MOVE": "Review active transactions alongside Query History if users report a hang.",
            "SAFE_FIX": "Coordinate with the owning sessions before canceling transactions.",
            "COMPUTE_DECISION": "No compute decision without blocked or queued evidence.",
            "PROOF_REQUIRED": "SHOW TRANSACTIONS plus matching query IDs or lock rows.",
            "OWNER_ROUTE": "Active Locks",
            "QUERY_ID": "",
            "WAREHOUSE_NAME": "",
            "TARGET_OBJECT": "",
        })

    decision = pd.DataFrame(rows)
    if decision.empty:
        return decision
    decision["_RANK"] = decision["SEVERITY"].map(_severity_rank)
    decision = decision.sort_values(["_RANK", "SIGNAL", "ENTITY"]).drop(columns=["_RANK"])
    decision = _add_safe_action_contracts(decision)
    return decision


def _run_live_incident_query(key: str, label: str, sql: str) -> pd.DataFrame:
    try:
        frame = run_query(
            sql,
            ttl_key=f"{key}_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            use_cache=False,
            tier="live",
            section="Contention Center",
        )
    except Exception as exc:
        message = format_snowflake_error(exc)
        st.session_state[_source_error_key(key)] = message
        st.session_state.setdefault("contention_live_source_errors", {})[label] = message
        return pd.DataFrame()
    st.session_state[_source_error_key(key)] = ""
    return frame


def _load_live_incident_snapshot(minutes: int, warehouse_name: str = "", root_task_name: str = "") -> None:
    session = get_session()
    st.session_state["contention_live_source_errors"] = {}
    try:
        active_locks = show_to_df(session, "SHOW LOCKS IN ACCOUNT", force_refresh=True)
    except Exception as exc:
        st.session_state.setdefault("contention_live_source_errors", {})["SHOW LOCKS"] = format_snowflake_error(exc)
        active_locks = pd.DataFrame()
    try:
        transactions = show_to_df(session, "SHOW TRANSACTIONS IN ACCOUNT", force_refresh=True)
    except Exception as exc:
        st.session_state.setdefault("contention_live_source_errors", {})["SHOW TRANSACTIONS"] = format_snowflake_error(exc)
        transactions = pd.DataFrame()

    live_queries = _run_live_incident_query(
        "contention_live_queries",
        "Live queries",
        build_live_query_incident_sql(minutes, warehouse_name),
    )
    task_graphs = _run_live_incident_query(
        "contention_live_task_graphs",
        "Current task graphs",
        build_live_task_graphs_sql(root_task_name),
    )
    warehouse_load = _run_live_incident_query(
        "contention_live_warehouse_load",
        "Live warehouse load",
        build_live_warehouse_load_sql(minutes, warehouse_name),
    )

    st.session_state["contention_active_locks"] = active_locks
    st.session_state["contention_live_transactions"] = transactions
    st.session_state["contention_live_queries"] = live_queries
    st.session_state["contention_live_task_graphs"] = task_graphs
    st.session_state["contention_live_warehouse_load"] = warehouse_load
    st.session_state["contention_live_decision_rows"] = _live_incident_rows(
        active_locks,
        transactions,
        live_queries,
        task_graphs,
        warehouse_load,
    )
    st.session_state["contention_live_snapshot_meta"] = {
        "captured_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "minutes": int(minutes),
        "warehouse": str(warehouse_name or ""),
        "root_task": str(root_task_name or ""),
    }


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


def _open_contention_owner_route(row: pd.Series | dict) -> None:
    route = str(row.get("OWNER_ROUTE") or "Contention Center")
    query_id = str(row.get("QUERY_ID") or "").strip()
    warehouse = str(row.get("WAREHOUSE_NAME") or "").strip()
    target_object = str(row.get("TARGET_OBJECT") or "").strip()
    if warehouse:
        st.session_state["global_warehouse"] = warehouse
        st.session_state["wh_filter"] = warehouse
    if route == "Active Locks":
        st.session_state["contention_center_view"] = "Active Locks"
    elif route == "Task graphs":
        st.session_state["workload_operations_workflow"] = "Pipeline & Task Health"
        st.session_state["workload_operations_pipeline_focus"] = "Failed Tasks"
    elif route == "Query diagnosis":
        st.session_state["workload_operations_workflow"] = "Query Investigation"
        st.session_state["query_analysis_active_view"] = "AI Diagnosis"
        if query_id:
            st.session_state["ai_query_id"] = query_id
        if target_object:
            st.session_state["ai_object_ctx"] = target_object
    elif route in {"Warehouse Health", "Cost & Contract"}:
        apply_navigation_state("Cost & Contract")
        st.session_state["cost_contract_workflow"] = "Recommendations"
    else:
        st.session_state["contention_center_view"] = "Brief"
    st.rerun()


def _render_fix_plan_actions(decision: pd.DataFrame) -> None:
    if decision.empty:
        return
    st.markdown("**Contention Fix Plan**")
    top = decision.head(3)
    cols = st.columns(len(top))
    for idx, (_, row) in enumerate(top.iterrows()):
        route = str(row.get("OWNER_ROUTE") or "Contention Center")
        label = f"Open {route}"
        help_text = "\n".join(
            part for part in [
                f"Bottleneck: {row.get('BOTTLENECK_TYPE', '')}",
                f"Telemetry: {row.get('EVIDENCE', '')}",
                f"First move: {row.get('FIRST_MOVE', '')}",
                f"Safe fix: {row.get('SAFE_FIX', '')}",
                f"Compute decision: {row.get('COMPUTE_DECISION', '')}",
                f"Telemetry basis: {row.get('PROOF_REQUIRED', '')}",
                f"Cleanup decision: {row.get('CLEANUP_DECISION', '')}",
                f"Review gate: {row.get('APPROVAL_GATE', '')}",
                f"Prechecks: {row.get('PRECHECKS', '')}",
                f"Precheck SQL: {row.get('PRECHECK_SQL', '')}",
                f"Action SQL: {row.get('MANUAL_ACTION_SQL', '')}",
                f"Audit telemetry: {row.get('AUDIT_EVIDENCE_REQUIRED', '')}",
                f"Recovery plan: {row.get('RECOVERY_PLAN', '')}",
                f"Verify after cleanup: {row.get('VERIFY_AFTER_CLEANUP', '')}",
                f"Verify SQL: {row.get('VERIFY_SQL', '')}",
            ] if part.split(": ", 1)[-1]
        )
        with cols[idx]:
            if st.button(label, key=f"contention_fix_plan_open_{idx}_{route}", help=help_text, width="stretch"):
                _open_contention_owner_route(row)


def _cleanup_contract_view(decision: pd.DataFrame, max_rows: int = 3) -> pd.DataFrame:
    view = _safe_frame(decision)
    if view.empty:
        return view
    contract_columns = [
        "SEVERITY",
        "HANDOFF_MATCH",
        "SIGNAL",
        "ENTITY",
        "TARGET_OBJECT",
        "QUERY_ID",
        "WAREHOUSE_NAME",
        "CLEANUP_DECISION",
        "CLEANUP_READINESS",
        "ACTION_GUARDRAIL",
        "APPROVAL_GATE",
        "PRECHECKS",
        "PRECHECK_SQL",
        "MANUAL_ACTION_SQL",
        "AUDIT_EVIDENCE_REQUIRED",
        "RECOVERY_PLAN",
        "EXECUTION_BOUNDARY",
        "WHEN_NOT_TO_RUN",
        "VERIFY_AFTER_CLEANUP",
        "VERIFY_SQL",
    ]
    available = [column for column in contract_columns if column in view.columns]
    if not available:
        return view.head(max_rows).copy()
    return view[available].head(max_rows).copy()


def _incident_owner_route(route: str) -> str:
    route_text = str(route or "").strip()
    if route_text == "Active Locks":
        return "DBA on-call + blocker route"
    if route_text == "Task graphs":
        return "Task route / scheduler"
    if route_text in {"Warehouse Health", "Cost & Contract"}:
        return "Warehouse route"
    if route_text == "Query diagnosis":
        return "Query route / DBA performance reviewer"
    return "DBA on-call"


def _incident_blocker(row: dict | pd.Series) -> str:
    route = str(_first_value(row, "OWNER_ROUTE", default=""))
    blocker_tx = str(_first_value(row, "BLOCKER_TRANSACTION_ID", default="")).strip()
    transaction_id = str(_first_value(row, "TRANSACTION_ID", "TRANSACTION", "ID", default="")).strip()
    signal = str(_first_value(row, "SIGNAL", "BOTTLENECK_TYPE", default="")).upper()
    if blocker_tx:
        return f"transaction {blocker_tx}"
    if transaction_id:
        return f"transaction {transaction_id}"
    if route in {"Warehouse Health", "Cost & Contract"}:
        return "No blocker proven"
    if route == "Task graphs":
        entity = str(_first_value(row, "ENTITY", default="task graph")).strip()
        run_1 = str(_first_value(row, "RUN_1_QUERY_ID", default="")).strip()
        run_2 = str(_first_value(row, "RUN_2_QUERY_ID", default="")).strip()
        runs = " / ".join(part for part in [run_1, run_2] if part)
        return f"{entity} ({runs})" if runs else entity
    if "LONG DML" in signal:
        query_id = str(_first_value(row, "QUERY_ID", default="")).strip()
        return f"query {query_id}" if query_id else "Long DML writer"
    return "Unknown - load active locks"


def _incident_waiter(row: dict | pd.Series) -> str:
    route = str(_first_value(row, "OWNER_ROUTE", default=""))
    waiter_query = str(_first_value(row, "WAITER_QUERY_ID", "QUERY_ID", default="")).strip()
    waiter_tx = str(_first_value(row, "WAITER_TRANSACTION_ID", default="")).strip()
    if waiter_query:
        return f"query {waiter_query}"
    if waiter_tx:
        return f"transaction {waiter_tx}"
    if route in {"Warehouse Health", "Cost & Contract"}:
        return "Queued workload"
    if route == "Task graphs":
        return "Overlapping graph run"
    return "Not mapped"


def _incident_decision_gate(row: dict | pd.Series) -> str:
    manual_sql = str(_first_value(row, "MANUAL_ACTION_SQL", default="")).strip()
    route = str(_first_value(row, "OWNER_ROUTE", default=""))
    if manual_sql:
        return "Run the precheck, confirm current telemetry, then use the guarded action only if blocker/waiter details match."
    if route in {"Warehouse Health", "Cost & Contract"}:
        return "Do not cancel; confirm queued load and absence of blocker locks before compute change."
    if route == "Task graphs":
        return "Route schedule or overlap fix; do not cancel the task graph from this cockpit."
    return "Gather missing blocker, waiter, route, and recovery telemetry before action."


def _incident_cockpit_view(decision: pd.DataFrame, max_rows: int = 5) -> pd.DataFrame:
    view = _safe_frame(decision)
    if view.empty:
        return view
    rows: list[dict[str, object]] = []
    for _, row in view.head(max_rows).iterrows():
        rows.append({
            "SEVERITY": row.get("SEVERITY", ""),
            "HANDOFF_MATCH": row.get("HANDOFF_MATCH", ""),
            "INCIDENT_CLASS": row.get("BOTTLENECK_TYPE", row.get("SIGNAL", "")),
            "BLOCKER": _incident_blocker(row),
            "WAITER": _incident_waiter(row),
            "LOCKED_OBJECT": row.get("TARGET_OBJECT") or row.get("ENTITY", ""),
            "WAREHOUSE_NAME": row.get("WAREHOUSE_NAME", ""),
            "INCIDENT_OWNER": _incident_owner_route(str(row.get("OWNER_ROUTE") or "")),
            "EXACT_NEXT_MOVE": row.get("FIRST_MOVE") or row.get("NEXT_ACTION", ""),
            "DECISION_GATE": _incident_decision_gate(row),
            "APPROVAL_GATE": row.get("APPROVAL_GATE", ""),
            "RECOVERY_PLAN": row.get("RECOVERY_PLAN", ""),
            "PRECHECK_SQL": row.get("PRECHECK_SQL", ""),
            "MANUAL_ACTION_SQL": row.get("MANUAL_ACTION_SQL", ""),
            "VERIFY_SQL": row.get("VERIFY_SQL", ""),
        })
    return pd.DataFrame(rows)


def _render_incident_cockpit(decision: pd.DataFrame) -> None:
    cockpit = _incident_cockpit_view(decision)
    if cockpit.empty:
        return
    st.markdown("**Incident Cockpit**")
    st.caption("Use this as the operator model: blocker, waiter, locked object, escalation route, exact next move, precheck, reviewed action, and status plan.")
    render_priority_dataframe(
        cockpit,
        title="Blocker/waiter action model",
        priority_columns=[
            "SEVERITY",
            "HANDOFF_MATCH",
            "INCIDENT_CLASS",
            "BLOCKER",
            "WAITER",
            "LOCKED_OBJECT",
            "WAREHOUSE_NAME",
            "INCIDENT_OWNER",
            "EXACT_NEXT_MOVE",
            "DECISION_GATE",
            "APPROVAL_GATE",
            "RECOVERY_PLAN",
            "PRECHECK_SQL",
            "MANUAL_ACTION_SQL",
            "VERIFY_SQL",
        ],
        sort_by=["HANDOFF_MATCH", "SEVERITY"],
        ascending=[False, True],
        max_rows=5,
        raw_label="All incident cockpit rows",
        height=280,
    )


def _render_cleanup_contract(decision: pd.DataFrame) -> None:
    contract = _cleanup_contract_view(decision)
    if contract.empty:
        return
    st.markdown("**Safe Cleanup Contract**")
    st.caption("DBA-controlled action only. Prechecks must be current before canceling a query or aborting a transaction.")
    render_priority_dataframe(
        contract,
        title="Guarded cleanup decisions",
        priority_columns=[
            "SEVERITY",
            "HANDOFF_MATCH",
            "SIGNAL",
            "ENTITY",
            "TARGET_OBJECT",
            "QUERY_ID",
            "WAREHOUSE_NAME",
            "CLEANUP_DECISION",
            "CLEANUP_READINESS",
            "APPROVAL_GATE",
            "PRECHECKS",
            "PRECHECK_SQL",
            "MANUAL_ACTION_SQL",
            "AUDIT_EVIDENCE_REQUIRED",
            "RECOVERY_PLAN",
            "EXECUTION_BOUNDARY",
            "VERIFY_AFTER_CLEANUP",
            "VERIFY_SQL",
            "ACTION_GUARDRAIL",
        ],
        sort_by=["HANDOFF_MATCH", "SEVERITY"],
        ascending=[False, True],
        max_rows=3,
        raw_label="All safe cleanup contract rows",
        height=260,
    )


def _render_contention_top_fix_path(decision: pd.DataFrame) -> None:
    path = build_contention_top_fix_path(decision)
    if path.empty:
        return
    row = path.iloc[0]
    st.markdown("**Top Fix Path**")
    render_shell_snapshot((
        ("Route", str(row.get("TOP_ROUTE") or "Contention Center")),
        ("Severity", str(row.get("TOP_SEVERITY") or "Watch")),
        ("Action SQL", str(row.get("MANUAL_SQL_STATE") or "No cancel/abort SQL")),
        ("Precheck", str(row.get("PRECHECK_REQUIRED") or "Required")),
    ))
    render_priority_dataframe(
        path,
        title="Current best contention fix path",
        priority_columns=[
            "TOP_ROUTE", "TOP_SEVERITY", "ENTITY", "BLOCKER", "WAITER",
            "FIRST_SAFE_MOVE", "CLEANUP_DECISION", "APPROVAL_GATE",
            "PRECHECK_REQUIRED", "MANUAL_SQL_STATE", "VERIFY_AFTER", "WHEN_NOT_TO_RUN",
        ],
        sort_by=["TOP_SEVERITY", "TOP_ROUTE"],
        ascending=[True, True],
        raw_label="All top fix path rows",
        height=220,
        max_rows=1,
    )
    sql_parts = [
        str(row.get("PRECHECK_SQL") or "").strip(),
        str(row.get("MANUAL_ACTION_SQL") or "").strip(),
        str(row.get("VERIFY_SQL") or "").strip(),
    ]
    if any(sql_parts):
        with st.expander("Top Fix Precheck", expanded=False):
            render_shell_snapshot((
                ("Precheck", "Required"),
                ("Reviewed action", "Review gated"),
                ("Status check", "Required"),
                ("Execution", "Runbook only"),
            ))


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
            render_escaped_bold_text(label)
            st.caption(str(value))


def _render_brief() -> None:
    decision = _focus_handoff_frame(_safe_frame(st.session_state.get("contention_decision_rows")), _focus_query_id())
    source_errors = st.session_state.get("contention_source_errors") or {}
    if source_errors:
        with st.expander("Unavailable telemetry inputs", expanded=False):
            for label, message in source_errors.items():
                st.caption(f"{label}: {message}")
    _render_handoff_context(decision, source="contention decision")
    if decision.empty:
        st.info("Load contention telemetry to rank blockers, task overlap, long DML, and warehouse pressure.")
        return
    _render_contention_top_fix_path(decision)
    solution_summary = build_contention_solution_summary(decision)
    if not solution_summary.empty:
        render_priority_dataframe(
            solution_summary,
            title="Contention solution routes",
            priority_columns=[
                "SOLUTION_ROUTE",
                "OPEN_SIGNALS",
                "TOP_SEVERITY",
                "PRIMARY_ENTITY",
                "FIRST_ACTION",
                "PROOF_REQUIRED",
                "OWNER_ROUTE",
            ],
            sort_by=["TOP_SEVERITY", "OPEN_SIGNALS"],
            ascending=[True, False],
            max_rows=6,
            raw_label="All contention solution routes",
            height=220,
        )
    _render_incident_cockpit(decision)
    _render_fix_plan_actions(decision)
    _render_cleanup_contract(decision)
    render_priority_dataframe(
        decision,
        title="Telemetry-ranked contention fixes",
        priority_columns=[
            "SEVERITY",
            "HANDOFF_MATCH",
            "BOTTLENECK_TYPE",
            "ENTITY",
            "TARGET_OBJECT",
            "EVIDENCE",
            "FIRST_MOVE",
            "SAFE_FIX",
            "COMPUTE_DECISION",
            "CLEANUP_DECISION",
            "CLEANUP_READINESS",
            "PROOF_REQUIRED",
            "VERIFY_AFTER_FIX",
            "OWNER_ROUTE",
        ],
        sort_by=["HANDOFF_MATCH", "SEVERITY", "SIGNAL"],
        ascending=[False, True, False],
        max_rows=20,
        raw_label="All contention decisions and status rows",
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


def _render_live_raw_frame(key: str, title: str, priority_columns: list[str]) -> None:
    frame = _focus_handoff_frame(_safe_frame(st.session_state.get(key)), _focus_query_id())
    if frame.empty:
        error = st.session_state.get(_source_error_key(key))
        if error:
            st.warning(f"{title} unavailable: {error}")
        else:
            st.info(f"No {title.lower()} rows in the last live snapshot.")
        return
    render_priority_dataframe(
        frame,
        title=title,
        priority_columns=["HANDOFF_MATCH"] + priority_columns,
        sort_by=["HANDOFF_MATCH", "SEVERITY"],
        ascending=[False, True],
        max_rows=40,
        raw_label=f"All {title.lower()} rows",
    )
    download_csv(frame, f"overwatch_{key}.csv")


def _render_live_incident() -> None:
    meta = st.session_state.get("contention_live_snapshot_meta") or {}
    decision = _focus_handoff_frame(_safe_frame(st.session_state.get("contention_live_decision_rows")), _focus_query_id())
    locks = _safe_frame(st.session_state.get("contention_active_locks"))
    transactions = _safe_frame(st.session_state.get("contention_live_transactions"))
    live_queries = _safe_frame(st.session_state.get("contention_live_queries"))
    task_graphs = _safe_frame(st.session_state.get("contention_live_task_graphs"))
    warehouse_load = _safe_frame(st.session_state.get("contention_live_warehouse_load"))
    source_errors = st.session_state.get("contention_live_source_errors") or {}

    render_shell_snapshot((
        ("Captured", str(meta.get("captured_at") or "On demand")),
        ("Locks", f"{len(locks):,}"),
        ("Queries", f"{len(live_queries):,}"),
        ("Actions", f"{len(decision):,}"),
    ))
    if source_errors:
        with st.expander("Unavailable live inputs", expanded=False):
            for label, message in source_errors.items():
                st.caption(f"{label}: {message}")
    _render_handoff_context(decision, source="live incident action")

    if decision.empty:
        st.info("Capture a live incident snapshot to rank current locks, transactions, blocked queries, task graphs, and warehouse pressure.")
    else:
        _render_incident_cockpit(decision)
        _render_fix_plan_actions(decision)
        _render_cleanup_contract(decision)
        render_priority_dataframe(
            decision,
            title="Live incident action queue",
            priority_columns=[
                "SEVERITY",
                "HANDOFF_MATCH",
                "SIGNAL",
                "ENTITY",
                "EVIDENCE",
                "FIRST_MOVE",
                "SAFE_FIX",
                "COMPUTE_DECISION",
                "CLEANUP_DECISION",
                "CLEANUP_READINESS",
                "PROOF_REQUIRED",
                "OWNER_ROUTE",
                "QUERY_ID",
                "WAREHOUSE_NAME",
                "TARGET_OBJECT",
            ],
            sort_by=["HANDOFF_MATCH", "SEVERITY", "SIGNAL"],
            ascending=[False, True, False],
            max_rows=20,
            raw_label="All live incident actions",
        )
        download_csv(decision, "overwatch_live_incident_actions.csv")

    with st.expander("Live query telemetry", expanded=False):
        _render_live_raw_frame(
            "contention_live_queries",
            "Live blocked, queued, or running queries",
            [
                "SEVERITY",
                "ROOT_CAUSE",
                "QUERY_ID",
                "WAREHOUSE_NAME",
                "EXECUTION_STATUS",
                "ELAPSED_SECONDS",
                "BLOCKED_SECONDS",
                "QUEUED_OVERLOAD_SECONDS",
                "QUERY_TYPE",
                "USER_NAME",
                "ROLE_NAME",
            ],
        )
    with st.expander("Task graph and warehouse telemetry", expanded=False):
        _render_live_raw_frame(
            "contention_live_task_graphs",
            "Current task graphs",
            ["STATE", "ROOT_TASK_NAME", "GRAPH_RUN_GROUP_ID", "DATABASE_NAME", "SCHEMA_NAME", "SCHEDULED_TIME"],
        )
        _render_live_raw_frame(
            "contention_live_warehouse_load",
            "Live warehouse load",
            ["SEVERITY", "ROOT_CAUSE", "WAREHOUSE_NAME", "AVG_RUNNING", "AVG_QUEUED_LOAD", "AVG_BLOCKED", "START_TIME", "END_TIME"],
        )
    with st.expander("Active locks and transactions", expanded=False):
        _render_live_raw_frame(
            "contention_active_locks",
            "Active locks",
            ["DATABASE", "SCHEMA", "RESOURCE", "OBJECT_NAME", "TRANSACTION", "TRANSACTION_ID", "USER", "STATUS"],
        )
        _render_live_raw_frame(
            "contention_live_transactions",
            "Active transactions",
            ["ID", "TRANSACTION_ID", "USER", "USER_NAME", "STATE", "STATUS", "STARTED_ON", "DATABASE", "SCHEMA"],
        )


def _render_named_frame(key: str, title: str, priority_columns: list[str], raw_label: str) -> None:
    frame = _focus_handoff_frame(_safe_frame(st.session_state.get(key)), _focus_query_id())
    if frame.empty:
        error = st.session_state.get(_source_error_key(key))
        if error:
            st.warning(f"{title} unavailable: {error}")
            return
        st.info(f"No {title.lower()} telemetry loaded for this window.")
        return
    _render_handoff_context(frame, source=title)
    render_priority_dataframe(
        frame,
        title=title,
        priority_columns=["HANDOFF_MATCH"] + priority_columns,
        sort_by=["HANDOFF_MATCH", "SEVERITY"],
        ascending=[False, True],
        max_rows=40,
        raw_label=raw_label,
    )
    download_csv(frame, f"overwatch_{key}.csv")


def render() -> None:
    st.subheader("Contention Center")
    _normalize_contention_view_state()
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
    l1, l2, l3 = st.columns([1, 1, 1])
    with l1:
        live_minutes = int(st.selectbox(
            "Live incident window",
            (15, 30, 60, 120),
            index=1,
            key="contention_live_minutes",
            format_func=lambda value: f"{int(value)} minutes",
            help="Recent Information Schema query/task telemetry for an active incident.",
        ))
    with l2:
        live_warehouse = st.text_input(
            "Live warehouse",
            value=str(st.session_state.get("global_warehouse") or ""),
            key="contention_live_warehouse",
            help="Optional. Use a specific warehouse for the most current warehouse-load history.",
        )
    with l3:
        live_root_task = st.text_input(
            "Root task",
            key="contention_live_root_task",
            help="Optional. Filter CURRENT_TASK_GRAPHS to one root task name.",
        )

    c_load, c_capture, c_live = st.columns([1, 1, 1])
    with c_load:
        if st.button("Load Contention Telemetry", key="contention_load", type="primary", width="stretch"):
            with render_load_status("Loading contention telemetry", "Contention telemetry ready"):
                _load_contention_evidence(days)
    with c_capture:
        if st.button("Capture Live Incident", key="contention_capture_live_incident", width="stretch"):
            with render_load_status("Capturing live incident telemetry", "Live incident snapshot ready"):
                _load_live_incident_snapshot(live_minutes, live_warehouse, live_root_task)
    with c_live:
        if st.button("Check Active Locks Now", key="contention_active_locks_button", width="stretch"):
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
    elif active_view == "Live Incident":
        _render_live_incident()
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
