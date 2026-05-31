# utils/data.py — DataFrame normalization: Decimal/Timestamp handling
import pandas as pd
import streamlit as st
from config import COMPANY_CONFIG, DEFAULT_COMPANY

# Columns that should always be numeric
_NUMERIC_COLS = {
    'CREDITS_USED', 'CREDITS_USED_COMPUTE', 'CREDITS_USED_CLOUD_SERVICES',
    'TOTAL_CREDITS', 'COMPUTE_CREDITS', 'CLOUD_CREDITS', 'CLOUD_SERVICES_CREDITS',
    'TOTAL_ELAPSED_TIME', 'BYTES_SCANNED', 'BYTES_WRITTEN',
    'CREDITS_PER_QUERY', 'COST', 'CREDITS_BILLED', 'CREDITS',
    'EST_COMPUTE_CREDITS', 'TOTAL_EST_CREDITS', 'ELAPSED_SEC',
    'EXEC_SEC', 'COMPILE_SEC', 'QUEUED_SEC', 'MB_SCANNED',
    'ROWS_PRODUCED', 'LOCAL_SPILL_GB', 'REMOTE_SPILL_GB', 'GB_SCANNED',
    'AVG_ELAPSED_SEC', 'P95_ELAPSED_SEC', 'MAX_ELAPSED_SEC',
    'METERED_CREDITS', 'EST_CREDITS', 'DAY_CREDITS', 'DAILY_CREDITS',
    'HYBRID_TABLE_GB', 'ARCHIVE_COOL_GB', 'ARCHIVE_COLD_GB',
    'STORAGE_GB', 'STAGE_GB', 'FAILSAFE_GB', 'TOTAL_STORAGE_GB',
    'TOKEN_CREDITS', 'TOTAL_TOKENS', 'CREDITS_BILLED',
    'IDLE_CREDITS', 'IDLE_HOURS', 'REMOTE_SPILL_GB',
    'CREDIT_QUOTA', 'USED_CREDITS', 'REMAINING_CREDITS',
    'QUERY_COUNT', 'FAIL_COUNT', 'FAILURES', 'ERR_COUNT',
    'ACTIVE_COUNT', 'QUEUED_COUNT', 'BLOCKED_COUNT',
    'STORAGE_BYTES', 'FAILSAFE_BYTES', 'STAGE_BYTES',
    'HOURLY_COMPUTE_CREDITS', 'EXEC_MS', 'HOUR_TOTAL_EXEC_MS',
    'EXACT_METERED_CREDITS', 'ALLOCATED_QUERY_CREDITS',
    'VARIANCE_CREDITS', 'VARIANCE_PCT',
}

# Columns that should always be datetime
_DATE_COLS = {
    'START_TIME', 'END_TIME', 'USAGE_DATE', 'DATE',
    'TIME_BUCKET', 'HOUR_BUCKET', 'SCHEDULED_TIME',
    'COMPLETED_TIME', 'LAST_LOGIN', 'CREATED_ON',
    'LAST_QUERY_TIME', 'FIRST_USAGE', 'LAST_USAGE',
    'LAST_LOAD_TIME', 'USAGE_TIME',
}


def _company_warehouse_mask(series: pd.Series, company: str) -> pd.Series:
    cfg = COMPANY_CONFIG.get(company, COMPANY_CONFIG.get(DEFAULT_COMPANY, {}))
    values = series.fillna("").astype(str).str.upper()
    include = [str(p).upper() for p in cfg.get("wh_patterns", [])]
    exclude = [str(p).upper() for p in cfg.get("wh_exclude_patterns", [])]

    if company == "ALL" or (not include and not exclude):
        return pd.Series(True, index=series.index)

    mask = pd.Series(False if include else True, index=series.index)
    for pattern in include:
        if pattern == "%":
            mask = pd.Series(True, index=series.index)
        elif pattern.endswith("%"):
            mask = mask | values.str.startswith(pattern[:-1])
        else:
            mask = mask | values.eq(pattern)

    for pattern in exclude:
        if pattern.endswith("%"):
            mask = mask & ~values.str.startswith(pattern[:-1])
        else:
            mask = mask & ~values.eq(pattern)
    return mask


def _company_database_mask(series: pd.Series, company: str) -> pd.Series:
    cfg = COMPANY_CONFIG.get(company, COMPANY_CONFIG.get(DEFAULT_COMPANY, {}))
    values = series.fillna("").astype(str).str.upper()
    include = [str(p).upper() for p in cfg.get("db_patterns", [])]
    exclude = str(cfg.get("exclude_db_pattern", "")).upper()

    if company == "ALL" or (not include and not exclude):
        return pd.Series(True, index=series.index)

    mask = pd.Series(False if include else True, index=series.index)
    for pattern in include:
        if pattern == "%":
            mask = pd.Series(True, index=series.index)
        elif pattern.endswith("%"):
            mask = mask | values.str.startswith(pattern[:-1])
        else:
            mask = mask | values.eq(pattern)

    if exclude:
        if exclude.endswith("%"):
            mask = mask & ~values.str.startswith(exclude[:-1])
        else:
            mask = mask & ~values.eq(exclude)
    return mask


def _company_user_mask(series: pd.Series, company: str) -> pd.Series:
    cfg = COMPANY_CONFIG.get(company, COMPANY_CONFIG.get(DEFAULT_COMPANY, {}))
    values = series.fillna("").astype(str).str.upper()
    include = [str(p).upper() for p in cfg.get("user_patterns", [])]
    exclude = [str(p).upper() for p in cfg.get("user_exclude_patterns", [])]

    if company == "ALL" or (not include and not exclude):
        return pd.Series(True, index=series.index)

    mask = pd.Series(False if include else True, index=series.index)
    for pattern in include:
        if pattern == "%":
            mask = pd.Series(True, index=series.index)
        elif pattern.endswith("%"):
            mask = mask | values.str.startswith(pattern[:-1])
        else:
            mask = mask | values.eq(pattern)

    for pattern in exclude:
        if pattern.endswith("%"):
            mask = mask & ~values.str.startswith(pattern[:-1])
        else:
            mask = mask & ~values.eq(pattern)
    return mask


def _has_value(series: pd.Series) -> pd.Series:
    return series.notna() & (series.astype(str).str.strip() != "")


def _apply_company_scope(df: pd.DataFrame) -> pd.DataFrame:
    company = st.session_state.get("active_company", DEFAULT_COMPANY)
    if company == "ALL" or df is None or df.empty:
        return df

    strong_checks = []
    for col in ("WAREHOUSE_NAME", "WAREHOUSE"):
        if col in df.columns:
            strong_checks.append((_has_value(df[col]), _company_warehouse_mask(df[col], company)))
            break
    for col in ("DATABASE_NAME", "DATABASE", "TABLE_CATALOG"):
        if col in df.columns:
            strong_checks.append((_has_value(df[col]), _company_database_mask(df[col], company)))
            break

    checks = strong_checks
    if not checks:
        for col in ("USER_NAME", "GRANTEE_NAME"):
            if col in df.columns:
                checks.append((_has_value(df[col]), _company_user_mask(df[col], company)))
                break

    if not checks:
        return df

    any_company_signal = pd.Series(False, index=df.index)
    allowed = pd.Series(True, index=df.index)
    for has_signal, mask in checks:
        any_company_signal = any_company_signal | has_signal
        allowed = allowed & (~has_signal | mask)

    return df[any_company_signal & allowed].copy()


def _has_company_scope_columns(columns: set[str]) -> bool:
    if st.session_state.get("active_company", DEFAULT_COMPANY) == "ALL":
        return False
    return bool(columns & {
        "WAREHOUSE_NAME", "WAREHOUSE",
        "DATABASE_NAME", "DATABASE", "TABLE_CATALOG",
        "USER_NAME", "GRANTEE_NAME",
    })


def normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize Snowflake Decimal/Timestamp types for Pandas compatibility.
    - Upper-cases all column names (Snowflake returns uppercase by default)
    - Converts known numeric columns to float
    - Converts known timestamp columns to timezone-naive datetime
    """
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()

    upper_columns = [str(c).upper() for c in df.columns]
    upper_set = set(upper_columns)
    numeric_cols = upper_set & _NUMERIC_COLS
    date_cols = upper_set & _DATE_COLS
    needs_uppercase = list(df.columns) != upper_columns
    needs_scope = _has_company_scope_columns(upper_set)

    if not (needs_uppercase or numeric_cols or date_cols or needs_scope):
        return df

    df = df.copy()
    if needs_uppercase:
        df.columns = upper_columns

    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(float)

    for col in date_cols:
        df[col] = pd.to_datetime(df[col], errors='coerce')
        if hasattr(df[col], 'dt') and df[col].dt.tz is not None:
            df[col] = df[col].dt.tz_convert(None)

    return _apply_company_scope(df) if needs_scope else df


def safe_strip_tz(series: pd.Series) -> pd.Series:
    """Safely strip timezone info from a datetime Series without raising errors."""
    s = pd.to_datetime(series, errors='coerce')
    if hasattr(s, 'dt') and s.dt.tz is not None:
        return s.dt.tz_convert(None)
    return s
