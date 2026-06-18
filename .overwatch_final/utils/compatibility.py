# utils/compatibility.py - Snowflake account compatibility checks
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from runtime_state import (
    AVAILABLE_COLUMNS_CACHE,
    COLUMN_PROBE_CACHE,
    CURRENT_ROLE,
    UNAVAILABLE_COLUMN_VIEWS,
    ensure_default_state,
    get_state,
)

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
        "Security Monitoring",
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
        return str(get_state(CURRENT_ROLE, "") or "").upper()
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
    cache = ensure_default_state(AVAILABLE_COLUMNS_CACHE, {})
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
    unavailable = ensure_default_state(UNAVAILABLE_COLUMN_VIEWS, set())
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
    probe_cache = ensure_default_state(COLUMN_PROBE_CACHE, {})
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
    """Document OVERWATCH cost formulas against the source COST_MONITOR dashboard."""
    rows = [
        (
            "Credit price",
            "Most source-dashboard displays used session credit_price, defaulting to $2.00/credit, with a few local sections using $3.00 or $4.00.",
            "Settings-driven compute credit price, defaulting to the configured OVERWATCH rate; Cortex/AI uses a separate AI credit price.",
            "Configurable estimate",
            "Intentional rate override",
            "OVERWATCH should follow the current contract rate rather than the older dashboard's mixed local defaults.",
            "Confirm compute and AI credit rates whenever the contract rate changes.",
        ),
        (
            "Warehouse consumption",
            "WAREHOUSE_METERING_HISTORY, CREDITS_USED_COMPUTE + CREDITS_USED_CLOUD_SERVICES, excluding pseudo warehouses with WAREHOUSE_ID > 0.",
            "WAREHOUSE_METERING_HISTORY total/compute/cloud credits, with company warehouse scope and completed metering windows where the view is billing-facing.",
            "Metered / invoice-adjustment caveat",
            "Aligned with scope change",
            "Primary source for warehouse burn-rate views. Company scoping is an OVERWATCH addition.",
            "Review pseudo-warehouse filtering if a Snowflake account starts returning cloud-services-only rows with warehouse names.",
        ),
        (
            "Monthly service costs",
            "METERING_HISTORY by DATE(START_TIME), SERVICE_TYPE, compute credits, cloud-services credits, total credits, current/prior period, ending 24 hours before now.",
            "METERING_HISTORY by service type for completed 24-hour-lag current/prior windows; exposes compute, cloud-services, total credits, and estimated dollars.",
            "Official Cost Monitor basis",
            "Aligned",
            "This is the closest source-of-truth parity row between COST_MONITOR_DB and OVERWATCH.",
            "Keep this formula as the account-level service reconciliation baseline.",
        ),
        (
            "Service cost dollars",
            "TOTAL_CREDITS * session credit_price.",
            "TOTAL_CREDITS * compute credit price for Snowflake services; TOTAL_CREDITS * AI credit price for Cortex/AI service categories.",
            "Estimated dollar conversion",
            "Intentional rate split",
            "The split prevents Cortex/AI credits from being dollarized at the compute rate.",
            "Verify service-type categorization when Snowflake adds new AI or managed-service names.",
        ),
        (
            "Official currency spend",
            "Not a primary source-dashboard formula.",
            "ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY when billing roles expose it; configured credit rates otherwise.",
            "Official when billing role can access it",
            "OVERWATCH extension",
            "Snowflake exposes currency cost only to eligible organization/billing roles.",
            "Prefer official currency rows when organization billing access is granted.",
        ),
        (
            "Cloud services credits",
            "QUERY_HISTORY.CREDITS_USED_CLOUD_SERVICES for successful queries in Cloud Services analysis.",
            "METERING_HISTORY cloud-services totals for account service reconciliation; WAREHOUSE_METERING_HISTORY cloud-services split where warehouse-level views expose it.",
            "Exact when available",
            "Intentional source upgrade",
            "QUERY_HISTORY cloud-services credits are useful query overhead signals but are not the full account service bill.",
            "Keep query-level cloud-services displays labeled as overhead, not invoice spend.",
        ),
        (
            "Per-query and client cost",
            "QUERY_HISTORY joined to SESSIONS; client cost was CREDITS_USED_CLOUD_SERVICES * credit_price.",
            "Prefer QUERY_ATTRIBUTION_HISTORY compute credits when available; otherwise allocate WAREHOUSE_METERING_HISTORY compute credits by query execution share.",
            "Allocated estimate",
            "Intentional source upgrade",
            "OVERWATCH includes warehouse compute allocation, so it is closer to workload cost than the source dashboard's cloud-services-only client signal.",
            "Continue labeling query/client cost as allocated unless official attribution covers the row.",
        ),
        (
            "Company chargeback scope",
            "Source dashboard was account-wide.",
            "Apply ALFA/Trexis warehouse, database, user, role, and environment boundaries before allocating warehouse credits.",
            "Exact boundary when naming patterns are current",
            "OVERWATCH extension",
            "Prevents scoped views from inheriting spend from the other company.",
            "Run the company-scope audit after warehouse, database, user, or role naming changes.",
        ),
        (
            "Forecast run rate",
            "Year-to-date METERING_HISTORY daily credits; recent observed-day average * days remaining in year.",
            "Cost Forecast keeps the operational 30-day WAREHOUSE_METERING_HISTORY projection and adds an account-wide annual service projection from METERING_HISTORY.",
            "Estimated forecast",
            "Aligned with extension",
            "OVERWATCH now shows both near-term warehouse burn and the source dashboard's annual service run-rate pattern.",
            "Reconcile annual service totals to Snowflake Admin/Cost Management before finance signoff.",
        ),
        (
            "Storage footprint",
            "DATABASE_STORAGE_USAGE_HISTORY + STAGE_STORAGE_USAGE_HISTORY + STORAGE_USAGE hybrid/archive bytes.",
            "Storage Monitor and FACT_STORAGE_DAILY include database, failsafe, stage, hybrid, archive cool, and archive cold bytes for account-wide views; company scope remains database/failsafe only when account-level allocation is unavailable.",
            "Estimated dollar conversion",
            "Aligned with allocation caveat",
            "Hybrid and archive storage classes are account-level Snowflake telemetry and should not be force-split by company without a defensible allocation basis.",
            "Use ALL scope for account-wide storage-class reconciliation.",
        ),
        (
            "Storage dollars",
            "Standard database/stage/failsafe TB * $23/TB/month, hybrid GB * $0.34/GB/month, archive cool TB * $4/TB/month, archive cold TB * $1/TB/month.",
            "Standard database/stage/failsafe TB * configured standard rate, hybrid GB * $0.34, archive cool TB * $4, archive cold TB * $1.",
            "Estimated dollar conversion",
            "Aligned",
            "OVERWATCH now separates standard, hybrid, archive cool, and archive cold storage cost formulas.",
            "Keep regional pricing reviewed before finance signoff.",
        ),
        (
            "AI services account cost",
            "METERING_DAILY_HISTORY where SERVICE_TYPE = 'AI_SERVICES', plus source-specific Cortex usage views.",
            "METERING_HISTORY service lens groups AI/Cortex service types; Cortex Monitor details Cortex Code and optional Cortex AI Functions.",
            "Mixed",
            "Partially aligned",
            "The account service lens catches broad AI/Cortex service spend, but detailed user/source views are narrower than the old dashboard.",
            "Expand Cortex detail coverage only behind explicit load buttons so first paint stays cheap.",
        ),
        (
            "Cortex detailed sources",
            "Cortex REST API, Snowflake Intelligence, Agents, Functions, Analyst, Search, Document AI, Fine-Tuning, and Cortex Code usage histories.",
            "Cortex Monitor probes Cortex service history views on demand and renders detail when the current role can see the required columns.",
            "Mixed",
            "Coverage expanded",
            "Detailed coverage depends on Snowflake feature enablement and ACCOUNT_USAGE grants for each service history view.",
            "Use the Service Details workflow to confirm which Cortex views are exposed in the current account.",
        ),
        (
            "SPCS credits",
            "SNOWPARK_CONTAINER_SERVICES_HISTORY.CREDITS_USED by compute pool/date.",
            "SPCS tracker uses SNOWPARK_CONTAINER_SERVICES_HISTORY and the account service lens also groups Snowpark Container Services.",
            "Exact account-level",
            "Aligned",
            "Company scoping is based on compute-pool naming when available.",
            "Review pool naming filters before using SPCS for company chargeback.",
        ),
        (
            "Openflow credits",
            "METERING_HISTORY where SERVICE_TYPE = OPENFLOW_COMPUTE_SNOWFLAKE.",
            "METERING_HISTORY service lens includes Openflow as a named managed service category.",
            "Exact account-level",
            "Aligned after categorization",
            "Openflow remains account-level unless Snowflake exposes an owner dimension for the service rows.",
            "Keep Openflow out of warehouse-compute buckets.",
        ),
        (
            "Replication credits",
            "REPLICATION_GROUP_USAGE_HISTORY.CREDITS_USED by replication group/date.",
            "Account service lens uses METERING_HISTORY service rows; detail should use REPLICATION_GROUP_USAGE_HISTORY where needed.",
            "Exact account-level",
            "Aligned account-level",
            "The source dashboard had a dedicated replication analyzer; OVERWATCH currently treats it primarily as service spend movement.",
            "Add a replication drilldown only if active replication spend becomes material.",
        ),
        (
            "Automatic clustering credits",
            "AUTOMATIC_CLUSTERING_HISTORY.CREDITS_USED by table.",
            "Clustering cost helper uses AUTOMATIC_CLUSTERING_HISTORY; service summaries classify automatic clustering as a managed service.",
            "Exact account-level",
            "Aligned",
            "Detailed table-level clustering cost remains separate from broad service movement.",
            "Keep table-level clustering review behind explicit load.",
        ),
        (
            "Serverless task credits",
            "SERVERLESS_TASK_HISTORY.CREDITS_USED by task/date.",
            "Account service lens uses METERING_HISTORY service rows; task workflows show operational task health and lineage.",
            "Exact account-level",
            "Aligned account-level",
            "Dedicated task cost drilldown can be added if serverless task spend is material.",
            "Use SERVERLESS_TASK_HISTORY for task-specific cost details, not QUERY_HISTORY estimates.",
        ),
        (
            "Idle warehouse waste",
            "Not a source-dashboard metric.",
            "Finalized WAREHOUSE_METERING_HISTORY compute credits with no observed query execution windows.",
            "Estimated",
            "OVERWATCH extension",
            "Idle time is inferred from metering windows and activity history; use as a savings signal, not an invoice number.",
            "Validate recommended changes against queue, spill, p95, and failure telemetry.",
        ),
        (
            "Stored procedure/task lineage",
            "Not a source-dashboard metric.",
            "Use ROOT_QUERY_ID/ROOT_TASK_ID when exposed; fall back to query text and query type.",
            "Mixed",
            "OVERWATCH extension",
            "Shows downstream cost when Snowflake exposes lineage columns.",
            "Keep procedure cost labeled estimated unless root lineage attribution is present.",
        ),
        (
            "OVERWATCH monitoring cost",
            "Not a source-dashboard metric.",
            "Attribute app, Streamlit warehouse, Cortex, alert tasks, and usage-log activity through metering/query tags when available.",
            "Mixed",
            "OVERWATCH extension",
            "Keeps the monitor honest; exactness depends on warehouse/query-tag coverage and Cortex metering availability.",
            "Keep monitoring cost behind explicit DBA review surfaces.",
        ),
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "METRIC",
            "SOURCE_DASHBOARD_FORMULA",
            "FORMULA",
            "CONFIDENCE",
            "PARITY_STATUS",
            "NOTES",
            "NEXT_REVIEW",
        ],
    )
