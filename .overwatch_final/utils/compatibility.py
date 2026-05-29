# utils/compatibility.py - Snowflake account compatibility checks
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

import pandas as pd
import streamlit as st

from .data import normalize_df
from .query import format_snowflake_error


_OBJECT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(\.[A-Za-z_][A-Za-z0-9_$]*){1,2}$")


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
            "ROOT_QUERY_ID", "PARENT_QUERY_ID", "ERROR_CODE", "ERROR_MESSAGE",
        ),
        "Account Health, Live Monitor, Query Analysis, Cost Center, Security",
        "Missing optional columns lower drilldown detail, but should not break the app.",
    ),
    ViewSpec(
        "Warehouse cost",
        "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
        ("START_TIME", "WAREHOUSE_NAME", "CREDITS_USED"),
        ("CREDITS_USED_COMPUTE", "CREDITS_USED_CLOUD_SERVICES"),
        "Cost Center, Warehouse Health, Contract Utilization, Recommendations",
        "Exact warehouse cost comes from this view.",
    ),
    ViewSpec(
        "Storage",
        "SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY",
        ("USAGE_DATE", "DATABASE_NAME"),
        ("AVERAGE_DATABASE_BYTES", "AVERAGE_FAILSAFE_BYTES"),
        "Account Health, Storage Monitor, Usage Overview",
        "Missing byte columns limits storage cost estimates.",
    ),
    ViewSpec(
        "Table storage",
        "SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS",
        ("TABLE_CATALOG", "TABLE_SCHEMA", "TABLE_NAME"),
        ("ACTIVE_BYTES", "TIME_TRAVEL_BYTES", "FAILSAFE_BYTES", "RETAINED_FOR_CLONE_BYTES"),
        "Storage Monitor",
        "Used for table-level storage and retention cost analysis.",
    ),
    ViewSpec(
        "Logins",
        "SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY",
        ("EVENT_TIMESTAMP", "USER_NAME", "IS_SUCCESS"),
        ("CLIENT_IP", "REPORTED_CLIENT_TYPE", "REPORTED_CLIENT_VERSION", "ERROR_CODE"),
        "Security & Access, Service Health",
        "Company scoping is user-pattern based for login-only records.",
    ),
    ViewSpec(
        "Tasks",
        "SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY",
        ("SCHEDULED_TIME", "DATABASE_NAME", "SCHEMA_NAME", "QUERY_ID"),
        ("ROOT_TASK_ID", "NAME", "TASK_NAME", "STATE", "COMPLETED_TIME", "ERROR_MESSAGE"),
        "Account Health, Task Management, Task Graph Control, Recommendations",
        "Column names vary by Snowflake account/version, so optional columns are feature-gated.",
    ),
    ViewSpec(
        "Data loading",
        "SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY",
        ("LAST_LOAD_TIME", "TABLE_NAME", "STATUS"),
        ("TABLE_CATALOG_NAME", "FILE_NAME", "ROW_COUNT", "FIRST_ERROR_MESSAGE"),
        "Pipeline Health, DBA Tools",
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
        "DBA Tools",
        "Snowflake exposes different refresh-history columns by edition and rollout state.",
    ),
    ViewSpec(
        "Serverless",
        "SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY",
        ("START_TIME", "SERVICE_TYPE", "CREDITS_USED"),
        (),
        "DBA Tools Serverless Costs",
        "Serverless costs are account-level unless a service-specific view exposes ownership.",
    ),
    ViewSpec(
        "Governance",
        "SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS",
        ("CREATED_ON", "ROLE", "GRANTEE_NAME"),
        ("DELETED_ON", "GRANTED_BY"),
        "Security & Access, Platform Topology",
        "Grant checks are company-scoped by grantee naming when no database/warehouse exists.",
    ),
    ViewSpec(
        "Users",
        "SNOWFLAKE.ACCOUNT_USAGE.USERS",
        ("NAME", "DISABLED"),
        ("HAS_PASSWORD", "EXT_AUTHN_DUO", "LAST_SUCCESS_LOGIN"),
        "Security & Access",
        "User metadata differs across auth configurations.",
    ),
)


SHOW_CHECKS: tuple[tuple[str, str, str], ...] = (
    ("Warehouse inventory", "SHOW WAREHOUSES", "Warehouse Settings Manager"),
    ("Task inventory", "SHOW TASKS IN ACCOUNT", "Task Graph Control"),
    ("Dynamic table inventory", "SHOW DYNAMIC TABLES IN ACCOUNT", "Dynamic Tables"),
    ("User inventory", "SHOW USERS", "Security posture and dormant user checks"),
)


def _validate_object_name(object_name: str) -> str:
    object_name = str(object_name or "").strip()
    if not _OBJECT_RE.match(object_name):
        raise ValueError(f"Unsafe Snowflake object name: {object_name}")
    return object_name


def get_available_columns(session, object_name: str) -> set[str]:
    """Return upper-case columns exposed by an account/view without scanning data."""
    object_name = _validate_object_name(object_name)
    cache = st.session_state.setdefault("_overwatch_available_columns", {})
    cached = cache.get(object_name)
    if cached:
        return {str(col).upper() for col in cached}
    df = normalize_df(session.sql(f"SELECT * FROM {object_name} LIMIT 0").to_pandas())
    columns = {str(col).upper() for col in df.columns}
    cache[object_name] = sorted(columns)
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
    unavailable = st.session_state.setdefault("_overwatch_unavailable_column_views", set())
    if object_name in unavailable:
        return []
    try:
        available = get_available_columns(session, object_name)
    except Exception:
        unavailable.add(object_name)
        return []
    probe_cache = st.session_state.setdefault("_overwatch_column_probe", {})
    existing: list[str] = []
    for col in columns:
        col_upper = str(col).upper()
        if col_upper not in available:
            continue
        cache_key = f"{object_name}:{col_upper}"
        if cache_key not in probe_cache:
            try:
                session.sql(f"SELECT {col_upper} FROM {object_name} LIMIT 0").collect()
                probe_cache[cache_key] = True
            except Exception:
                probe_cache[cache_key] = False
        if probe_cache.get(cache_key):
            existing.append(col_upper)
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
    """Manual live smoke-test checklist for post-deploy validation."""
    rows = [
        ("Account Health", "Refresh Health", "Metrics load without red Snowflake errors."),
        ("Usage Overview", "Load dashboard", "Credits, query counts, users, and storage reflect selected company."),
        ("Warehouse Health", "Load warehouse overview and optimization", "No Trexis warehouses appear in ALFA view; size is populated when Snowflake exposes it."),
        ("Cost Center", "Load cost leaderboard and chargeback", "Credits reconcile to metering for completed billing windows."),
        ("Security & Access", "Load Login Posture and Roles & Grants", "No numeric/string conversion errors; company-scoped users/grants only."),
        ("DBA Tools", "Open Warehouse Settings", "Warehouse list auto-populates from selected company."),
        ("DBA Tools", "Open Dynamic Tables", "Missing optional columns show as limited data, not hard errors."),
        ("DBA Tools", "Open Task Graph Control", "Current-user stored procedure warning is informational, not blocking."),
        ("Settings", "Open Settings and Saved Views", "No material-icon text leaks are visible."),
        ("Company Selector", "Switch ALFA/Trexis/ALL", "Cache clears and all section data refreshes to the selected company."),
    ]
    return pd.DataFrame(rows, columns=["SECTION", "ACTION", "PASS_CRITERIA"])


def build_cost_formula_audit() -> pd.DataFrame:
    """Document the app's cost formulas and confidence level."""
    rows = [
        (
            "Warehouse credits",
            "SUM(CREDITS_USED) from WAREHOUSE_METERING_HISTORY for completed billing windows",
            "Exact",
            "Primary source for warehouse chargeback and burn-rate views. Includes total billed warehouse credits so optional compute-only columns cannot break the app.",
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
            "Company chargeback scope",
            "Apply ALFA/Trexis warehouse/database boundary before allocating metered warehouse credits",
            "Exact boundary when naming patterns are current",
            "Prevents ALFA views from inheriting Trexis warehouse spend and keeps shared views explicit in ALL mode.",
        ),
        (
            "Idle warehouse waste",
            "Use finalized WAREHOUSE_METERING_HISTORY compute credits minus observed query execution windows",
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
    ]
    return pd.DataFrame(rows, columns=["METRIC", "FORMULA", "CONFIDENCE", "NOTES"])
