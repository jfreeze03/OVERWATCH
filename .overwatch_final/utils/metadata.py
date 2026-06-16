# utils/metadata.py - shared Snowflake metadata helpers
import time

import pandas as pd
import streamlit as st

from config import COMPANY_CONFIG
from .admin import safe_identifier, sql_literal
from .company_filter import company_value_allowed, get_active_company
from .data import normalize_df


_SHOW_CACHE_TTL_SECONDS = 300
_SHOW_CACHE_MAX_ENTRIES = 12


def _show_cache_key(stmt: str) -> str:
    role = str(st.session_state.get("_overwatch_current_role", "") or "").upper()
    normalized_stmt = " ".join(str(stmt or "").strip().split()).upper()
    return f"{role}|{normalized_stmt}"


def _prune_show_cache(cache: dict) -> None:
    overflow = max(0, len(cache) - _SHOW_CACHE_MAX_ENTRIES)
    if not overflow:
        return
    for key, _entry in sorted(
        cache.items(),
        key=lambda item: float(item[1].get("loaded_at", 0) or 0),
    )[:overflow]:
        cache.pop(key, None)


def clear_show_statement_cache(stmt: str | None = None) -> None:
    """Clear cached SHOW/DESC metadata after explicit DBA refresh or changes."""
    if stmt is None:
        st.session_state.pop("_overwatch_show_statement_cache", None)
        return
    cache = st.session_state.get("_overwatch_show_statement_cache", {})
    cache.pop(_show_cache_key(stmt), None)


def show_to_df(session, stmt: str, force_refresh: bool = False) -> pd.DataFrame:
    """Run a SHOW/DESC statement and return a normalized DataFrame."""
    now = time.time()
    cache_key = _show_cache_key(stmt)
    cache = st.session_state.setdefault("_overwatch_show_statement_cache", {})
    cached = cache.get(cache_key)
    if not force_refresh and cached:
        age_sec = now - float(cached.get("loaded_at", 0) or 0)
        frame = cached.get("frame")
        if age_sec <= _SHOW_CACHE_TTL_SECONDS and isinstance(frame, pd.DataFrame):
            return frame.copy()

    try:
        df = normalize_df(session.sql(stmt).to_pandas())
    except Exception:
        return pd.DataFrame()
    df.columns = [str(col).strip('"').upper() for col in df.columns]
    cache[cache_key] = {"loaded_at": now, "frame": df.copy()}
    _prune_show_cache(cache)
    return df.copy()


def first_existing_column(df: pd.DataFrame, candidates: list[str]) -> str:
    """Return the first matching column from a mixed-case Snowflake result."""
    if df is None or df.empty:
        return ""
    cols = {str(col).upper(): col for col in df.columns}
    for candidate in candidates:
        found = cols.get(str(candidate).upper())
        if found:
            return str(found)
    return ""


def ensure_column_alias(
    df: pd.DataFrame,
    target: str,
    candidates: list[str],
    default="",
) -> pd.DataFrame:
    """Ensure target exists by copying the first existing candidate column."""
    if df is None or df.empty:
        return df
    target = str(target).upper()
    if target in df.columns:
        return df
    source = first_existing_column(df, candidates)
    df[target] = df[source] if source else default
    return df


def scope_warehouse_names(
    df: pd.DataFrame,
    name_col: str = "name",
    company: str | None = None,
) -> pd.DataFrame:
    """Apply company warehouse visibility to SHOW-style result sets."""
    if df is None or df.empty or name_col not in df.columns:
        return df
    active_company = company or get_active_company()
    return df[df[name_col].apply(lambda value: company_value_allowed(value, "warehouse", active_company))].copy()


def scope_metadata_df(df: pd.DataFrame, company: str | None = None) -> pd.DataFrame:
    """Apply company visibility to generic metadata result sets."""
    if df is None or df.empty:
        return df
    active_company = company or get_active_company()
    scoped = df.copy()
    for col in ("DATABASE_NAME", "DATABASE", "TABLE_CATALOG", "TABLE_DATABASE"):
        if col in scoped.columns:
            scoped = scoped[scoped[col].apply(lambda value: company_value_allowed(value, "database", active_company))]
            break
    for col in ("WAREHOUSE", "WAREHOUSE_NAME"):
        if col in scoped.columns:
            scoped = scoped[
                scoped[col].isna()
                | (scoped[col].astype(str).str.strip() == "")
                | scoped[col].apply(lambda value: company_value_allowed(value, "warehouse", active_company))
            ]
            break
    for col in ("USER_NAME", "USER", "GRANTEE_NAME", "CREATED_BY"):
        if col in scoped.columns and active_company != "ALL":
            scoped = scoped[
                scoped[col].isna()
                | (scoped[col].astype(str).str.strip() == "")
                | scoped[col].apply(lambda value: company_value_allowed(value, "user", active_company))
            ]
            break
    return scoped.copy()


def metadata_name_options(df: pd.DataFrame, candidates: list[str]) -> list[str]:
    """Return sorted unique names from a SHOW-style metadata frame."""
    if df is None or df.empty:
        return []
    col = first_existing_column(df, candidates)
    if not col:
        return []
    names = [
        str(value or "").strip()
        for value in df[col].tolist()
        if str(value or "").strip()
    ]
    return sorted(dict.fromkeys(names), key=str.upper)


def load_database_options(
    session,
    company: str | None = None,
    force_refresh: bool = False,
) -> list[str]:
    """Load scoped database names for metadata-driven filters."""
    df = show_to_df(session, "SHOW DATABASES", force_refresh=force_refresh)
    if df is None or df.empty:
        return []
    db_col = first_existing_column(df, ["NAME", "DATABASE_NAME"])
    if not db_col:
        return []
    view = df.copy()
    view["DATABASE_NAME"] = view[db_col]
    return metadata_name_options(scope_metadata_df(view, company), ["DATABASE_NAME", "NAME"])


def load_schema_options(
    session,
    database_name: str,
    company: str | None = None,
    force_refresh: bool = False,
) -> list[str]:
    """Load schema names from one scoped database for cascading selectors."""
    db = str(database_name or "").strip()
    if not db or not company_value_allowed(db, "database", company):
        return []
    df = show_to_df(
        session,
        f"SHOW SCHEMAS IN DATABASE {safe_identifier(db)}",
        force_refresh=force_refresh,
    )
    if df is None or df.empty:
        return []
    return [
        name
        for name in metadata_name_options(df, ["NAME", "SCHEMA_NAME"])
        if name.upper() != "INFORMATION_SCHEMA"
    ]


def load_warehouse_options(
    session,
    company: str | None = None,
    force_refresh: bool = False,
) -> list[str]:
    """Load scoped warehouse names for metadata-driven filters."""
    df = load_warehouse_inventory(session, company=company, force_refresh=force_refresh)
    return metadata_name_options(df, ["NAME", "WAREHOUSE_NAME"])


def load_warehouse_inventory(
    session,
    company: str | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Load warehouse metadata with consistent column aliases and company scope."""
    df = show_to_df(session, "SHOW WAREHOUSES", force_refresh=force_refresh)
    if df.empty:
        return df
    df.columns = [str(col).upper() for col in df.columns]
    for col in [
        "NAME", "WAREHOUSE_SIZE", "STATE", "AUTO_SUSPEND", "AUTO_RESUME",
        "MIN_CLUSTER_COUNT", "MAX_CLUSTER_COUNT", "SCALING_POLICY",
        "STATEMENT_TIMEOUT_IN_SECONDS", "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS",
        "MAX_CONCURRENCY_LEVEL", "ENABLE_QUERY_ACCELERATION",
        "QUERY_ACCELERATION_MAX_SCALE_FACTOR", "COMMENT",
    ]:
        if col not in df.columns:
            df[col] = ""
    return scope_warehouse_names(df, "NAME", company)


def load_task_inventory(
    session,
    company: str | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Load task metadata with consistent aliases and company scope."""
    df = show_to_df(session, "SHOW TASKS IN ACCOUNT", force_refresh=force_refresh)
    if df.empty:
        return df
    df = ensure_column_alias(df, "NAME", ["NAME", "TASK_NAME"])
    df = ensure_column_alias(df, "DATABASE_NAME", ["DATABASE_NAME", "DATABASE"])
    df = ensure_column_alias(df, "SCHEMA_NAME", ["SCHEMA_NAME", "SCHEMA"])
    for col in ["NAME", "DATABASE_NAME", "SCHEMA_NAME", "STATE", "SCHEDULE", "WAREHOUSE", "PREDECESSORS", "DEFINITION"]:
        if col not in df.columns:
            df[col] = ""
    df = scope_metadata_df(df, company)
    if df.empty or "NAME" not in df.columns:
        return pd.DataFrame()
    df["NAME"] = df["NAME"].astype(str).str.strip()
    return df[df["NAME"] != ""].copy()


def load_live_task_runs(
    session,
    task_inventory: pd.DataFrame,
    hours_back: int = 6,
    result_limit_per_task: int = 10,
    max_tasks: int = 150,
) -> pd.DataFrame:
    """Load currently running task executions from database INFORMATION_SCHEMA.

    ACCOUNT_USAGE.TASK_HISTORY can lag, and database-wide INFORMATION_SCHEMA
    calls can be dominated by scheduled future rows. For live cancellation, use
    the visible task inventory as an index and ask each task directly.
    """
    if task_inventory is None or task_inventory.empty:
        return pd.DataFrame()

    db_col = first_existing_column(task_inventory, ["DATABASE_NAME", "DATABASE"])
    task_col = first_existing_column(task_inventory, ["NAME", "TASK_NAME"])
    schema_col = first_existing_column(task_inventory, ["SCHEMA_NAME", "SCHEMA"])
    if not db_col or not task_col:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    seen_tasks: set[tuple[str, str, str]] = set()
    per_task_limit = max(1, min(100, int(result_limit_per_task or 10)))
    task_limit = max(1, min(500, int(max_tasks or 150)))

    for _, row in task_inventory.head(task_limit).iterrows():
        database_name = str(row.get(db_col) or "").strip()
        schema_name = str(row.get(schema_col) or "").strip() if schema_col else ""
        task_name = str(row.get(task_col) or "").strip()
        task_key = (database_name.upper(), schema_name.upper(), task_name.upper())
        if not database_name or not task_name or task_key in seen_tasks:
            continue
        seen_tasks.add(task_key)
        try:
            database_ident = safe_identifier(database_name)
        except Exception:
            continue

        sql = f"""
            SELECT SCHEDULED_TIME,
                   COALESCE(QUERY_START_TIME, SCHEDULED_TIME) AS QUERY_START_TIME,
                   COMPLETED_TIME,
                   COALESCE(DATABASE_NAME, {sql_literal(database_name, 512)}) AS DATABASE_NAME,
                   COALESCE(SCHEMA_NAME, {sql_literal(schema_name, 512)}) AS SCHEMA_NAME,
                   NAME AS TASK_NAME,
                   NAME,
                   STATE,
                   ERROR_CODE,
                   ERROR_MESSAGE,
                   QUERY_ID,
                   ROOT_TASK_ID,
                   GRAPH_RUN_GROUP_ID,
                   DATEDIFF(
                       'second',
                       COALESCE(QUERY_START_TIME, SCHEDULED_TIME),
                       COALESCE(COMPLETED_TIME, CURRENT_TIMESTAMP())
                   ) AS DURATION_SEC,
                   'INFORMATION_SCHEMA.TASK_HISTORY' AS SOURCE
            FROM TABLE({database_ident}.INFORMATION_SCHEMA.TASK_HISTORY(
                TASK_NAME => {sql_literal(task_name, 512)},
                RESULT_LIMIT => {per_task_limit}
            ))
            ORDER BY SCHEDULED_TIME DESC
        """
        try:
            rows = session.sql(sql).collect()
        except Exception:
            continue
        df = pd.DataFrame([row.as_dict() for row in rows])
        if df.empty:
            continue
        df.columns = [str(col).strip('"').upper() for col in df.columns]
        if schema_name and "SCHEMA_NAME" in df.columns:
            df = df[df["SCHEMA_NAME"].fillna("").astype(str).str.upper() == schema_name.upper()]
        if "STATE" in df.columns:
            df = df[df["STATE"].fillna("").astype(str).str.upper().isin(["EXECUTING", "RUNNING"])]
        if df.empty:
            continue
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    dedupe_cols = [
        col for col in ["DATABASE_NAME", "SCHEMA_NAME", "NAME", "QUERY_ID", "GRAPH_RUN_GROUP_ID"]
        if col in combined.columns
    ]
    if dedupe_cols:
        combined = combined.drop_duplicates(subset=dedupe_cols, keep="first")
    return combined.copy()


def _like_predicate(column: str, patterns: list[str], negate: bool = False) -> str:
    clauses = [f"{column} ILIKE '{str(pattern).replace(chr(39), chr(39) + chr(39))}'" for pattern in patterns if pattern]
    if not clauses:
        return ""
    joined = " OR ".join(clauses)
    return f"NOT ({joined})" if negate else f"({joined})"


def build_unclassified_assets_sql(days_back: int = 30) -> str:
    """Return SQL that surfaces warehouses/databases not matched to ALFA or Trexis scope."""
    days_back = max(1, int(days_back or 30))
    company_configs = [cfg for name, cfg in COMPANY_CONFIG.items() if name != "ALL"]
    wh_patterns = []
    db_patterns = []
    for cfg in company_configs:
        wh_patterns.extend([p for p in cfg.get("wh_patterns", []) if p and p != "%"])
        db_patterns.extend([p for p in cfg.get("db_patterns", []) if p and p != "%"])
    alfa_catches_remaining_warehouses = any(
        not cfg.get("wh_patterns") and cfg.get("wh_exclude_patterns")
        for name, cfg in COMPANY_CONFIG.items()
        if name.upper() == "ALFA"
    )
    wh_unmatched = (
        "1=0"
        if alfa_catches_remaining_warehouses
        else (_like_predicate("warehouse_name", wh_patterns, negate=True) or "1=1")
    )
    db_unmatched = _like_predicate("database_name", db_patterns, negate=True) or "1=1"
    return f"""
    WITH warehouse_usage AS (
        SELECT
            'WAREHOUSE' AS object_type,
            warehouse_name AS object_name,
            NULL::VARCHAR AS database_name,
            ROUND(SUM(credits_used), 4) AS credits_30d,
            'Warehouse does not match any company allowlist' AS reason
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          AND {wh_unmatched}
        GROUP BY warehouse_name
    ),
    databases AS (
        SELECT
            'DATABASE' AS object_type,
            database_name AS object_name,
            database_name,
            NULL::NUMBER AS credits_30d,
            'Database does not match any company allowlist' AS reason
        FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASES
        WHERE deleted IS NULL
          AND database_name IS NOT NULL
          AND database_name NOT ILIKE 'SNOWFLAKE%'
          AND {db_unmatched}
    )
    SELECT * FROM warehouse_usage
    UNION ALL
    SELECT * FROM databases
    ORDER BY object_type, credits_30d DESC NULLS LAST, object_name
    LIMIT 500
    """
