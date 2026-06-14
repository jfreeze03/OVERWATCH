# utils/compatibility.py - Snowflake account compatibility checks
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Iterable

import pandas as pd
import streamlit as st

from .data import normalize_df
from .query import format_snowflake_error


_OBJECT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(\.[A-Za-z_][A-Za-z0-9_$]*){1,2}$")
_COLUMN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_COLUMN_METADATA_TTL_SECONDS = 300
_GLOBAL_COLUMN_CACHE: dict[str, tuple[float, set[str]]] = {}
_GLOBAL_COLUMN_PROBE_CACHE: dict[str, tuple[float, bool]] = {}
_GLOBAL_UNAVAILABLE_OBJECTS: dict[str, float] = {}
_GLOBAL_COLUMN_CACHE_LOCK = threading.RLock()
_GLOBAL_COLUMN_PROBE_EXECUTION_LOCK = threading.Lock()


@dataclass(frozen=True)
class ViewSpec:
    category: str
    object_name: str
    required_columns: tuple[str, ...]
    optional_columns: tuple[str, ...] = ()
    used_by: str = ""
    impact: str = ""


VIEW_SPECS: tuple[ViewSpec, ...] = (
    ViewSpec(
        "Core query monitoring",
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        (
            "QUERY_ID", "START_TIME", "USER_NAME", "ROLE_NAME", "WAREHOUSE_NAME",
            "DATABASE_NAME", "SCHEMA_NAME", "QUERY_TYPE", "EXECUTION_STATUS",
            "TOTAL_ELAPSED_TIME", "EXECUTION_TIME",
        ),
        (
            "WAREHOUSE_SIZE", "QUEUED_OVERLOAD_TIME", "QUEUED_PROVISIONING_TIME",
            "TRANSACTION_BLOCKED_TIME", "BYTES_SPILLED_TO_LOCAL_STORAGE",
            "BYTES_SPILLED_TO_REMOTE_STORAGE", "BYTES_SCANNED", "QUERY_TAG",
            "AUTHN_EVENT_ID", "IS_CLIENT_GENERATED_STATEMENT",
            "ROOT_QUERY_ID", "PARENT_QUERY_ID", "ERROR_CODE", "ERROR_MESSAGE",
        ),
        "Account Health, Workload Operations, Cost & Contract, Security Posture",
        "Missing optional columns lower drilldown detail, but should not break the app.",
    ),
    ViewSpec(
        "Warehouse cost",
        "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
        ("START_TIME", "WAREHOUSE_NAME", "CREDITS_USED"),
        ("CREDITS_USED_COMPUTE", "CREDITS_USED_CLOUD_SERVICES"),
        "Cost & Contract, Warehouse Health",
        "Exact warehouse cost comes from this view.",
    ),
    ViewSpec(
        "Official query attribution",
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY",
        ("QUERY_ID", "START_TIME", "CREDITS_ATTRIBUTED_COMPUTE"),
        ("CREDITS_USED_QUERY_ACCELERATION", "QUERY_TAG", "USER_NAME", "WAREHOUSE_NAME"),
        "Cost & Contract reconciliation, query/user cost attribution",
        "Preferred source for execution-only query compute attribution when exposed by the active role.",
    ),
    ViewSpec(
        "Storage",
        "SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY",
        ("USAGE_DATE", "DATABASE_NAME"),
        ("AVERAGE_DATABASE_BYTES", "AVERAGE_FAILSAFE_BYTES"),
        "Account Health, Cost & Contract, DBA Control Room",
        "Missing byte columns limits storage cost estimates.",
    ),
    ViewSpec(
        "Table storage",
        "SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS",
        ("TABLE_CATALOG", "TABLE_SCHEMA", "TABLE_NAME"),
        ("ACTIVE_BYTES", "TIME_TRAVEL_BYTES", "FAILSAFE_BYTES", "RETAINED_FOR_CLONE_BYTES"),
        "Cost & Contract",
        "Used for table-level storage and retention cost analysis.",
    ),
    ViewSpec(
        "Logins",
        "SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY",
        ("EVENT_TIMESTAMP", "USER_NAME", "IS_SUCCESS"),
        ("EVENT_ID", "CLIENT_IP", "REPORTED_CLIENT_TYPE", "REPORTED_CLIENT_VERSION", "ERROR_CODE"),
        "Security Posture, DBA Control Room",
        "Company scoping is user-pattern based for login-only records.",
    ),
    ViewSpec(
        "Sessions",
        "SNOWFLAKE.ACCOUNT_USAGE.SESSIONS",
        ("SESSION_ID", "CREATED_ON", "USER_NAME"),
        (
            "LOGIN_EVENT_ID", "AUTHENTICATION_METHOD", "CLIENT_APPLICATION_ID",
            "CLIENT_APPLICATION_VERSION", "CLIENT_ENVIRONMENT", "CLIENT_BUILD_ID",
            "CLIENT_VERSION", "ACCESS_TIME", "IS_OPEN", "CLOSED_REASON",
        ),
        "Security Posture, Change & Drift",
        "Session-level client metadata is the preferred source for connected-program inventory; Account Usage latency can be up to 3 hours.",
    ),
    ViewSpec(
        "Tasks",
        "SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY",
        ("SCHEDULED_TIME", "DATABASE_NAME", "SCHEMA_NAME", "QUERY_ID"),
        ("ROOT_TASK_ID", "NAME", "TASK_NAME", "STATE", "COMPLETED_TIME", "ERROR_MESSAGE"),
        "Account Health, Workload Operations, Cost & Contract",
        "Column names vary by Snowflake account/version, so optional columns are feature-gated.",
    ),
    ViewSpec(
        "Data loading",
        "SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY",
        ("LAST_LOAD_TIME", "TABLE_NAME", "STATUS"),
        ("TABLE_CATALOG_NAME", "FILE_NAME", "ROW_COUNT", "FIRST_ERROR_MESSAGE"),
        "Workload Operations, Change & Drift",
        "Used for load failure and file-volume monitoring.",
    ),
    ViewSpec(
        "Dynamic tables",
        "SNOWFLAKE.ACCOUNT_USAGE.DYNAMIC_TABLE_REFRESH_HISTORY",
        ("REFRESH_START_TIME",),
        (
            "DATABASE_NAME", "SCHEMA_NAME", "NAME", "DYNAMIC_TABLE_NAME", "STATE_CODE",
            "STATE_MESSAGE", "REFRESH_ACTION", "REFRESH_TRIGGER", "QUERY_ID",
            "TARGET_LAG_SEC",
        ),
        "Change & Drift",
        "Snowflake exposes different refresh-history columns by edition and rollout state.",
    ),
    ViewSpec(
        "Serverless",
        "SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY",
        ("START_TIME", "SERVICE_TYPE", "CREDITS_USED"),
        (),
        "Change & Drift serverless cost checks",
        "Serverless costs are account-level unless a service-specific view exposes ownership.",
    ),
    ViewSpec(
        "Governance",
        "SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS",
        ("CREATED_ON", "ROLE", "GRANTEE_NAME"),
        ("DELETED_ON", "GRANTED_BY"),
        "Security Posture, Change & Drift",
        "Grant checks are company-scoped by grantee naming when no database/warehouse exists.",
    ),
    ViewSpec(
        "Users",
        "SNOWFLAKE.ACCOUNT_USAGE.USERS",
        ("NAME", "DISABLED"),
        ("HAS_PASSWORD", "EXT_AUTHN_DUO", "LAST_SUCCESS_LOGIN"),
        "Security Posture",
        "User metadata differs across auth configurations.",
    ),
)


SHOW_CHECKS: tuple[tuple[str, str, str], ...] = (
    ("Warehouse inventory", "SHOW WAREHOUSES", "Warehouse Settings Manager"),
    ("Task inventory", "SHOW TASKS IN ACCOUNT", "Task Graph Control"),
    ("Dynamic table inventory", "SHOW DYNAMIC TABLES IN ACCOUNT", "Dynamic Tables"),
    ("User inventory", "SHOW USERS", "Access & Security and dormant user checks"),
)


def _validate_object_name(object_name: str) -> str:
    object_name = str(object_name or "").strip()
    if not _OBJECT_RE.match(object_name):
        raise ValueError(f"Unsafe Snowflake object name: {object_name}")
    return object_name


def _validate_column_name(column: str) -> str:
    column = str(column or "").strip().upper()
    if not _COLUMN_RE.match(column):
        raise ValueError(f"Unsafe Snowflake column name: {column}")
    return column


def clear_compatibility_process_cache() -> None:
    """Clear process-wide compatibility metadata caches."""
    with _GLOBAL_COLUMN_CACHE_LOCK:
        _GLOBAL_COLUMN_CACHE.clear()
        _GLOBAL_COLUMN_PROBE_CACHE.clear()
        _GLOBAL_UNAVAILABLE_OBJECTS.clear()


def _fresh_timestamp(ts: float) -> bool:
    return (time.monotonic() - ts) <= _COLUMN_METADATA_TTL_SECONDS


def _process_cached_columns(object_name: str) -> set[str] | None:
    with _GLOBAL_COLUMN_CACHE_LOCK:
        entry = _GLOBAL_COLUMN_CACHE.get(object_name)
        if not entry:
            return None
        ts, columns = entry
        if not _fresh_timestamp(ts):
            _GLOBAL_COLUMN_CACHE.pop(object_name, None)
            return None
        return set(columns)


def _mark_process_columns(object_name: str, columns: set[str]) -> None:
    with _GLOBAL_COLUMN_CACHE_LOCK:
        _GLOBAL_COLUMN_CACHE[object_name] = (time.monotonic(), set(columns))
        _GLOBAL_UNAVAILABLE_OBJECTS.pop(object_name, None)


def _role_cache_scope() -> str:
    try:
        return str(st.session_state.get("_overwatch_current_role", "") or "").upper()
    except Exception:
        return ""


def _column_probe_cache_key(object_name: str, column: str) -> str:
    return f"{_role_cache_scope()}|{object_name}|{column}"


def _process_column_probe_result(object_name: str, column: str) -> bool | None:
    key = _column_probe_cache_key(object_name, column)
    with _GLOBAL_COLUMN_CACHE_LOCK:
        entry = _GLOBAL_COLUMN_PROBE_CACHE.get(key)
        if not entry:
            return None
        ts, result = entry
        if not _fresh_timestamp(ts):
            _GLOBAL_COLUMN_PROBE_CACHE.pop(key, None)
            return None
        return bool(result)


def _mark_process_column_probe(object_name: str, column: str, result: bool) -> None:
    key = _column_probe_cache_key(object_name, column)
    with _GLOBAL_COLUMN_CACHE_LOCK:
        _GLOBAL_COLUMN_PROBE_CACHE[key] = (time.monotonic(), bool(result))


def _process_unavailable(object_name: str) -> bool:
    with _GLOBAL_COLUMN_CACHE_LOCK:
        ts = _GLOBAL_UNAVAILABLE_OBJECTS.get(object_name)
        if not ts:
            return False
        if not _fresh_timestamp(ts):
            _GLOBAL_UNAVAILABLE_OBJECTS.pop(object_name, None)
            return False
        return True


def _mark_process_unavailable(object_name: str) -> None:
    with _GLOBAL_COLUMN_CACHE_LOCK:
        _GLOBAL_UNAVAILABLE_OBJECTS[object_name] = time.monotonic()


def get_available_columns(session, object_name: str) -> set[str]:
    """Return upper-case columns exposed by an account/view without scanning data."""
    object_name = _validate_object_name(object_name)
    cache = st.session_state.setdefault("_overwatch_available_columns", {})
    if object_name in cache:
        return {str(col).upper() for col in cache.get(object_name, [])}
    cached_columns = _process_cached_columns(object_name)
    if cached_columns is not None:
        cache[object_name] = sorted(cached_columns)
        return cached_columns
    if _process_unavailable(object_name):
        raise RuntimeError(f"{object_name} unavailable in recent compatibility probe.")
    try:
        df = normalize_df(session.sql(f"SELECT * FROM {object_name} LIMIT 0").to_pandas())
    except Exception:
        _mark_process_unavailable(object_name)
        raise
    columns = {str(col).upper() for col in df.columns}
    cache[object_name] = sorted(columns)
    _mark_process_columns(object_name, columns)
    return columns


def view_supports_columns(session, object_name: str, columns: Iterable[str]) -> tuple[bool, list[str]]:
    """Return whether every requested column exists plus the missing list."""
    requested = [str(col).upper() for col in columns]
    verified = set(filter_existing_columns(session, object_name, requested))
    missing = [col for col in requested if col not in verified]
    return not missing, missing


def filter_existing_columns(session, object_name: str, columns: Iterable[str]) -> list[str]:
    """Keep only columns that the active Snowflake account exposes."""
    object_name = _validate_object_name(object_name)
    requested: list[str] = []
    seen: set[str] = set()
    for col in columns:
        col_upper = _validate_column_name(col)
        if col_upper not in seen:
            requested.append(col_upper)
            seen.add(col_upper)
    if not requested:
        return []
    unavailable = st.session_state.setdefault("_overwatch_unavailable_column_views", set())
    if object_name in unavailable:
        return []
    if _process_unavailable(object_name):
        unavailable.add(object_name)
        return []
    try:
        available = get_available_columns(session, object_name)
    except Exception:
        unavailable.add(object_name)
        return []
    probe_cache = st.session_state.setdefault("_overwatch_column_probe", {})
    candidates = [col for col in requested if col in available]
    for col in candidates:
        cache_key = f"{object_name}:{col}"
        if cache_key in probe_cache:
            continue
        process_result = _process_column_probe_result(object_name, col)
        if process_result is not None:
            probe_cache[cache_key] = process_result
    unprobed = [col for col in candidates if f"{object_name}:{col}" not in probe_cache]
    if unprobed:
        with _GLOBAL_COLUMN_PROBE_EXECUTION_LOCK:
            for col in list(unprobed):
                cache_key = f"{object_name}:{col}"
                if cache_key in probe_cache:
                    continue
                process_result = _process_column_probe_result(object_name, col)
                if process_result is not None:
                    probe_cache[cache_key] = process_result
            unprobed = [col for col in candidates if f"{object_name}:{col}" not in probe_cache]
            if unprobed:
                try:
                    session.sql(f"SELECT {', '.join(unprobed)} FROM {object_name} LIMIT 0").collect()
                    for col in unprobed:
                        probe_cache[f"{object_name}:{col}"] = True
                        _mark_process_column_probe(object_name, col, True)
                except Exception:
                    for col in unprobed:
                        cache_key = f"{object_name}:{col}"
                        if cache_key in probe_cache:
                            continue
                        try:
                            session.sql(f"SELECT {col} FROM {object_name} LIMIT 0").collect()
                            probe_cache[cache_key] = True
                        except Exception:
                            probe_cache[cache_key] = False
                        _mark_process_column_probe(object_name, col, bool(probe_cache[cache_key]))
    existing: list[str] = []
    for col in candidates:
        cache_key = f"{object_name}:{col}"
        if probe_cache.get(cache_key):
            existing.append(col)
    return existing


TASK_HISTORY_OBJECT = "SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY"


_TASK_HISTORY_CANDIDATES = (
    "SCHEDULED_TIME", "QUERY_START_TIME", "COMPLETED_TIME",
    "DATABASE_NAME", "SCHEMA_NAME", "TASK_NAME", "ROOT_TASK_ID", "STATE",
    "ERROR_CODE", "ERROR_MESSAGE", "QUERY_ID", "GRAPH_RUN_GROUP_ID",
)


def _task_history_cols(session) -> set[str]:
    # ACCOUNT_USAGE metadata can advertise optional TASK_HISTORY columns that
    # still fail at execution time for some roles/accounts. Probe candidates
    # once and only build SQL with columns that compile in this context.
    return set(filter_existing_columns(session, TASK_HISTORY_OBJECT, _TASK_HISTORY_CANDIDATES))


def _task_name_expr(cols: set[str]) -> str:
    # Some accounts advertise NAME in TASK_HISTORY metadata but reject it in
    # execution. Prefer task-specific names and stable IDs for compatibility.
    candidates = [col for col in ("TASK_NAME", "ROOT_TASK_ID", "QUERY_ID") if col in cols]
    if not candidates:
        return "'UNKNOWN_TASK'"
    return "COALESCE(" + ", ".join(f"TO_VARCHAR({col})" for col in candidates) + ")"


def _task_db_filter(cols: set[str], company: str | None = None) -> str:
    if "DATABASE_NAME" not in cols:
        return ""
    from .company_filter import get_db_filter_clause

    return get_db_filter_clause("database_name", company)


def build_task_history_sql(
    session,
    time_predicate: str,
    limit: int = 500,
    company: str | None = None,
) -> str:
    """Build a TASK_HISTORY detail query using only columns available here."""
    cols = _task_history_cols(session)
    if "SCHEDULED_TIME" not in cols:
        raise ValueError("TASK_HISTORY does not expose SCHEDULED_TIME for this role/account.")

    start_expr = "COALESCE(QUERY_START_TIME, SCHEDULED_TIME)" if "QUERY_START_TIME" in cols else "SCHEDULED_TIME"
    end_expr = "COALESCE(COMPLETED_TIME, CURRENT_TIMESTAMP())" if "COMPLETED_TIME" in cols else "CURRENT_TIMESTAMP()"
    task_expr = _task_name_expr(cols)

    select_exprs = [
        "SCHEDULED_TIME",
        f"{start_expr} AS QUERY_START_TIME",
        "COMPLETED_TIME" if "COMPLETED_TIME" in cols else "NULL::TIMESTAMP_NTZ AS COMPLETED_TIME",
        "DATABASE_NAME" if "DATABASE_NAME" in cols else "NULL::VARCHAR AS DATABASE_NAME",
        "SCHEMA_NAME" if "SCHEMA_NAME" in cols else "NULL::VARCHAR AS SCHEMA_NAME",
        f"{task_expr} AS TASK_NAME",
        f"{task_expr} AS NAME",
        "STATE" if "STATE" in cols else "NULL::VARCHAR AS STATE",
        "ERROR_CODE" if "ERROR_CODE" in cols else "NULL::VARCHAR AS ERROR_CODE",
        "ERROR_MESSAGE" if "ERROR_MESSAGE" in cols else "NULL::VARCHAR AS ERROR_MESSAGE",
        "QUERY_ID" if "QUERY_ID" in cols else "NULL::VARCHAR AS QUERY_ID",
        "ROOT_TASK_ID" if "ROOT_TASK_ID" in cols else "NULL::VARCHAR AS ROOT_TASK_ID",
        "GRAPH_RUN_GROUP_ID" if "GRAPH_RUN_GROUP_ID" in cols else "NULL::VARCHAR AS GRAPH_RUN_GROUP_ID",
        f"DATEDIFF('second', {start_expr}, {end_expr}) AS DURATION_SEC",
    ]

    return f"""
        SELECT {", ".join(select_exprs)}
        FROM {TASK_HISTORY_OBJECT}
        WHERE {time_predicate}
          {_task_db_filter(cols, company)}
        ORDER BY SCHEDULED_TIME DESC
        LIMIT {int(limit)}
    """


def build_task_failure_summary_sql(
    session,
    time_predicate: str,
    limit: int = 5,
    company: str | None = None,
) -> str:
    """Build a failed-task summary that tolerates account-specific columns."""
    cols = _task_history_cols(session)
    if "SCHEDULED_TIME" not in cols:
        raise ValueError("TASK_HISTORY does not expose SCHEDULED_TIME for this role/account.")

    task_expr = _task_name_expr(cols)
    db_expr = "DATABASE_NAME" if "DATABASE_NAME" in cols else "'UNKNOWN'"
    schema_expr = "SCHEMA_NAME" if "SCHEMA_NAME" in cols else "'UNKNOWN'"
    error_expr = "MAX(ERROR_MESSAGE)" if "ERROR_MESSAGE" in cols else "NULL::VARCHAR"
    if "STATE" in cols:
        failure_predicate = "AND UPPER(STATE) = 'FAILED'"
    elif "ERROR_MESSAGE" in cols:
        failure_predicate = "AND ERROR_MESSAGE IS NOT NULL"
    else:
        failure_predicate = ""

    return f"""
        SELECT {task_expr} AS TASK_NAME,
               {db_expr} AS DATABASE_NAME,
               {schema_expr} AS SCHEMA_NAME,
               COUNT(*) AS FAILURES,
               MAX(SCHEDULED_TIME) AS LAST_FAILURE,
               {error_expr} AS LAST_ERROR
        FROM {TASK_HISTORY_OBJECT}
        WHERE {time_predicate}
          {failure_predicate}
          {_task_db_filter(cols, company)}
        GROUP BY {task_expr}, {db_expr}, {schema_expr}
        ORDER BY FAILURES DESC, LAST_FAILURE DESC
        LIMIT {int(limit)}
    """


def build_task_health_sql(
    session,
    time_predicate: str,
    company: str | None = None,
) -> str:
    """Build a task-service health aggregate without assuming optional columns."""
    cols = _task_history_cols(session)
    if "SCHEDULED_TIME" not in cols:
        raise ValueError("TASK_HISTORY does not expose SCHEDULED_TIME for this role/account.")

    task_expr = _task_name_expr(cols)
    if "STATE" in cols:
        failed_expr = "SUM(IFF(UPPER(STATE) = 'FAILED', 1, 0))"
        succeeded_expr = "SUM(IFF(UPPER(STATE) = 'SUCCEEDED', 1, 0))"
    elif "ERROR_MESSAGE" in cols:
        failed_expr = "SUM(IFF(ERROR_MESSAGE IS NOT NULL, 1, 0))"
        succeeded_expr = "0"
    else:
        failed_expr = "0"
        succeeded_expr = "0"

    return f"""
        SELECT COUNT(*) AS TASK_RUNS,
               {failed_expr} AS FAILED_TASKS,
               {succeeded_expr} AS SUCCEEDED_TASKS,
               COUNT(DISTINCT {task_expr}) AS DISTINCT_TASKS
        FROM {TASK_HISTORY_OBJECT}
        WHERE {time_predicate}
          {_task_db_filter(cols, company)}
    """


def run_compatibility_checks(session) -> pd.DataFrame:
    """Probe required Snowflake views, optional columns, and SHOW command support."""
    rows: list[dict[str, str]] = []
    for spec in VIEW_SPECS:
        try:
            verified_required = set(filter_existing_columns(session, spec.object_name, spec.required_columns))
            verified_optional = set(filter_existing_columns(session, spec.object_name, spec.optional_columns))
            missing_required = [col for col in spec.required_columns if col not in verified_required]
            missing_optional = [col for col in spec.optional_columns if col not in verified_optional]
            if missing_required:
                status = "Missing required column"
                detail = ", ".join(missing_required)
            elif missing_optional:
                status = "Limited"
                detail = "Optional missing: " + ", ".join(missing_optional[:8])
                if len(missing_optional) > 8:
                    detail += f" (+{len(missing_optional) - 8} more)"
            else:
                status = "Ready"
                detail = "All required and optional columns are available."
        except Exception as e:
            status = "Unavailable"
            detail = format_snowflake_error(e)
        rows.append({
            "CATEGORY": spec.category,
            "CHECK": spec.object_name,
            "STATUS": status,
            "USED_BY": spec.used_by,
            "DETAIL": detail,
            "IMPACT": spec.impact,
        })

    for category, statement, used_by in SHOW_CHECKS:
        try:
            session.sql(statement).collect()
            status = "Ready"
            detail = "SHOW command succeeded."
        except Exception as e:
            status = "Unavailable"
            detail = format_snowflake_error(e)
        rows.append({
            "CATEGORY": category,
            "CHECK": statement,
            "STATUS": status,
            "USED_BY": used_by,
            "DETAIL": detail,
            "IMPACT": "Inventory auto-load falls back or becomes manual if unavailable.",
        })

    return pd.DataFrame(rows)


def build_smoke_test_checklist() -> pd.DataFrame:
    """Manual operational readiness checklist for post-deploy validation."""
    rows = [
        ("Account Health", "Refresh Health", "Metrics load without red Snowflake errors."),
        ("Usage Overview", "Load dashboard", "Credits, query counts, users, and storage reflect selected company."),
        ("Warehouse Health", "Load warehouse overview and optimization", "No Trexis warehouses appear in ALFA view; size is populated when Snowflake exposes it."),
        ("Cost & Contract", "Load Explain This Bill, cost leaderboard, and chargeback", "Credits reconcile to metering for completed billing windows."),
        ("Security Posture", "Load Login Posture and Roles & Grants", "No numeric/string conversion errors; company-scoped users/grants only."),
        ("Change & Drift", "Open Warehouse Settings", "Warehouse list auto-populates from selected company."),
        ("Change & Drift", "Open Dynamic Tables", "Missing optional columns show as limited data, not hard errors."),
        ("Change & Drift", "Open Task Graph Control", "Current-user stored procedure warning is informational, not blocking."),
        ("Settings", "Open Settings", "No material-icon text leaks are visible."),
        ("Company Selector", "Switch ALFA/Trexis/ALL", "Cache clears and all section data refreshes to the selected company."),
    ]
    return pd.DataFrame(rows, columns=["SECTION", "ACTION", "READY_CRITERIA"])


def build_cost_formula_audit() -> pd.DataFrame:
    """Document the app's cost formulas and source basis."""
    rows = [
        (
            "Warehouse credits",
            "SUM(CREDITS_USED) from WAREHOUSE_METERING_HISTORY for completed metering windows",
            "Metered / invoice-adjustment caveat",
            "Primary source for warehouse burn-rate views. Snowflake documents this as hourly metering, but final billed credits can differ because cloud-services adjustments are reconciled separately.",
        ),
        (
            "Account service credits",
            "METERING_HISTORY.CREDITS_USED for completed 24-hour-lag Cost Monitor windows",
            "Official Cost Monitor basis",
            "Use this for account-level service reconciliation. OVERWATCH applies the configured compute rate for Snowflake services and the AI rate for Cortex services.",
        ),
        (
            "Official currency spend",
            "ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY where RATING_TYPE = 'compute' and SERVICE_TYPE = 'WAREHOUSE_METERING'",
            "Official when billing role can access it",
            "Snowflake exposes currency cost only to eligible organization/billing roles; OVERWATCH falls back to ALFA's configured $3.68/credit estimate otherwise.",
        ),
        (
            "Cloud services credits",
            "Use CREDITS_USED_CLOUD_SERVICES where exposed; otherwise omitted from warehouse allocation",
            "Exact when available",
            "Keep separate from compute to avoid overstating user/query cost.",
        ),
        (
            "Per-query cost",
            "Allocate exact warehouse-hour credits by each query's EXECUTION_TIME share",
            "Allocated estimate",
            "Reconciles to warehouse-hour totals but is not Snowflake-billed at query granularity.",
        ),
        (
            "Official query attribution",
            "Prefer QUERY_ATTRIBUTION_HISTORY.CREDITS_ATTRIBUTED_COMPUTE where enabled; otherwise use OVERWATCH allocation fallback",
            "Official execution-only / no idle",
            "Snowflake attribution excludes warehouse idle time, cloud services, storage, serverless services, and AI token costs, so it should not be presented as a full invoice number.",
        ),
        (
            "Company chargeback scope",
            "Apply ALFA/Trexis warehouse/database boundary before allocating metered warehouse credits",
            "Exact boundary when naming patterns are current",
            "Prevents ALFA views from inheriting Trexis warehouse spend and keeps shared views explicit in ALL mode.",
        ),
        (
            "Idle warehouse waste",
            "Use finalized WAREHOUSE_METERING_HISTORY compute credits with no observed query execution windows",
            "Estimated",
            "Idle time is inferred from metering windows and activity history; use as a savings signal, not an invoice number.",
        ),
        (
            "Live query estimate",
            "WAREHOUSE_SIZE credit rate * elapsed seconds / 3600",
            "Estimated",
            "Used only before ACCOUNT_USAGE metering lands.",
        ),
        (
            "Stored procedure/task lineage",
            "Use ROOT_QUERY_ID/ROOT_TASK_ID when exposed; fall back to query text and query type",
            "Mixed",
            "Shows downstream cost when Snowflake exposes lineage columns.",
        ),
        (
            "Storage dollars",
            "Average bytes / 1024^4 * configured $/TB/month",
            "Estimated dollar conversion",
            "Storage is not a warehouse credit metric; present separately from compute.",
        ),
        (
            "Serverless services",
            "METERING_HISTORY by SERVICE_TYPE",
            "Exact account-level",
            "Company chargeback only when service-specific metadata provides an owner dimension.",
        ),
        (
            "Forecast run rate",
            "Fill missing calendar days with zero usage before calculating daily average and month-end forecast",
            "Estimated forecast",
            "Avoids overstating spend when Snowflake returns only days with metered activity.",
        ),
        (
            "OVERWATCH query budget",
            "Track query hash, section, elapsed time, row count, result size, and repeated expensive-call count",
            "Operational telemetry",
            "Identifies sections that repeatedly scan too much data; this is a tuning signal, not a Snowflake invoice metric.",
        ),
        (
            "OVERWATCH monitoring cost",
            "Attribute app, Streamlit warehouse, Cortex, alert tasks, and usage-log activity through metering/query tags when available",
            "Mixed",
            "Keeps the monitor honest; exactness depends on warehouse/query-tag coverage and Cortex metering availability.",
        ),
    ]
    return pd.DataFrame(rows, columns=["METRIC", "FORMULA", "CONFIDENCE", "NOTES"])
