# utils/company_filter.py — Multi-tenant company filtering (ALFA / Trexis)
# ─────────────────────────────────────────────────────────────────────────────
# Warehouse naming convention (confirmed from Snowflake UI 2025-05-20):
#   ALFA:   WH_ALFA_*, BI_COMPUTE_WH, COMPUTE_WH, CROWDSTRIKE_WH,
#           DOC_AI_WH, POSIT_WORKBENCH, SNOWFLAKE_LEARNING_WH, SYSTEM$STREAMLIT*
#   Trexis: WH_TRXS_* only
#
# Filter strategy per mode:
#   ALFA  → all non-Trexis warehouses, plus ALFA database/user patterns
#   Trexis → WH_TRXS_* only
#   ALL   → no filter, but get_company_case_expr() labels every row
# ─────────────────────────────────────────────────────────────────────────────
import streamlit as st
import fnmatch
from config import COMPANY_CONFIG, DEFAULT_COMPANY
from .query import sql_literal


def get_active_company() -> str:
    """Return currently selected company key. Defaults to ALFA (never ALL)."""
    return st.session_state.get("active_company", DEFAULT_COMPANY)


def get_company_cfg(company: str = None) -> dict:
    """Return config dict for the given (or active) company."""
    company = company or get_active_company()
    return COMPANY_CONFIG.get(company, COMPANY_CONFIG["ALL"])


# ── Cache invalidation ────────────────────────────────────────────────────────

def invalidate_company_cache():
    """
    Clear all section data from session_state when the company filter changes.
    Without this, stale Trexis data lingers in ALFA view (and vice versa).
    Preserves settings (credit_price, rt_interval, nav_section, etc.).
    """
    _preserve_prefixes = (
        "nav_", "_prev_nav_", "active_company", "_prev_active_company",
        "credit_price", "_credit_price", "storage_cost", "rt_interval",
        "global_start", "global_end", "global_warehouse", "global_user",
        "global_role", "global_database",
    )
    keys_to_drop = [
        k for k in list(st.session_state.keys())
        if not any(k.startswith(p) for p in _preserve_prefixes)
        and k not in ("active_company", "nav_section")
    ]
    for k in keys_to_drop:
        del st.session_state[k]
    try:
        st.cache_data.clear()
    except Exception:
        pass


# ── WHERE clause builders ─────────────────────────────────────────────────────

def get_wh_filter_clause(column: str = "warehouse_name", company: str = None) -> str:
    """
    Return SQL WHERE fragment to filter by warehouse.

    ALFA:   AND (col ILIKE '%') AND (col NOT ILIKE 'WH_TRXS_%')
    Trexis: AND (col ILIKE 'WH_TRXS_%')
    ALL:    '' — no filter; use get_company_case_expr() to label rows instead
    """
    cfg = get_company_cfg(company)
    include = cfg.get("wh_patterns", [])
    exclude = cfg.get("wh_exclude_patterns", [])

    clauses = []
    if include:
        # Exact names (no wildcards) use = for precision; patterns use ILIKE
        like_parts = " OR ".join(
            f"{column} = '{p}'" if "%" not in p else f"{column} ILIKE '{p}'"
            for p in include
        )
        clauses.append(f"({like_parts})")
    if exclude:
        not_parts = " AND ".join(
            f"{column} <> '{p}'" if "%" not in p else f"{column} NOT ILIKE '{p}'"
            for p in exclude
        )
        clauses.append(f"({not_parts})")

    return "AND " + " AND ".join(clauses) if clauses else ""


def get_db_filter_clause(column: str = "database_name", company: str = None) -> str:
    """Return SQL WHERE fragment to filter databases by company."""
    cfg = get_company_cfg(company)
    patterns   = cfg.get("db_patterns", [])
    exclude_pt = cfg.get("exclude_db_pattern", "")

    if not patterns and not exclude_pt:
        return ""

    clauses = []
    if patterns:
        like_parts = " OR ".join(f"{column} ILIKE '{p}'" for p in patterns)
        clauses.append(f"({like_parts})")
    if exclude_pt:
        clauses.append(f"{column} NOT ILIKE '{exclude_pt}'")

    return "AND " + " AND ".join(clauses) if clauses else ""


def get_user_filter_clause(column: str = "user_name", company: str = None) -> str:
    """Return SQL WHERE fragment to filter users by company."""
    cfg = get_company_cfg(company)
    patterns = cfg.get("user_patterns", [])
    exclude = cfg.get("user_exclude_patterns", [])
    clauses = []
    if patterns:
        like_parts = " OR ".join(f"{column} ILIKE '{p}'" for p in patterns)
        clauses.append(f"({like_parts})")
    if exclude:
        not_parts = " AND ".join(f"{column} NOT ILIKE '{p}'" for p in exclude)
        clauses.append(f"({not_parts})")
    return "AND " + " AND ".join(clauses) if clauses else ""


def get_role_filter_clause(column: str = "role_name", company: str = None) -> str:
    """Return SQL WHERE fragment to filter role-like names by company."""
    return get_user_filter_clause(column, company)


def company_value_allowed(value: str, kind: str = "database", company: str = None) -> bool:
    """Return whether an entered DB/user/warehouse value belongs to the active company."""
    company = company or get_active_company()
    if company == "ALL":
        return True
    cfg = get_company_cfg(company)
    text = str(value or "").upper()
    if not text:
        return False
    if kind == "warehouse":
        include = cfg.get("wh_patterns", [])
        exclude = cfg.get("wh_exclude_patterns", [])
    elif kind == "user":
        include = cfg.get("user_patterns", [])
        exclude = cfg.get("user_exclude_patterns", [])
    else:
        include = cfg.get("db_patterns", [])
        exclude = [cfg.get("exclude_db_pattern", "")] if cfg.get("exclude_db_pattern") else []

    def _match(pattern: str) -> bool:
        return fnmatch.fnmatchcase(text, str(pattern or "").upper().replace("%", "*"))

    if any(_match(pattern) for pattern in exclude):
        return False
    return any(_match(pattern) for pattern in include) if include else True


def get_combined_filter_clause(
    db_col: str = "database_name",
    wh_col: str = "warehouse_name",
    user_col: str = "user_name",
    company: str = None,
) -> str:
    """
    Return every available company boundary filter.

    Queries that expose more than one company-bearing dimension should be
    constrained by all of them. This keeps ALFA/Trexis selection from leaking
    through a user, warehouse, or database column that happened not to be the
    single preferred filter.
    """
    company = company or get_active_company()
    return " ".join(filter(None, [
        get_wh_filter_clause(wh_col, company) if wh_col else "",
        get_db_filter_clause(db_col, company) if db_col else "",
        get_user_filter_clause(user_col, company) if user_col else "",
    ])).strip()


# ── ALL-mode classification expression ───────────────────────────────────────

def get_company_case_expr(
    wh_col: str = "warehouse_name",
    db_col: str = "database_name",
    user_col: str = "user_name",
) -> str:
    """
    SQL CASE expression that classifies every row as 'ALFA', 'Trexis',
    or 'Shared/Unclassified'.

    Use this in ALL-mode queries so one query returns both companies labeled —
    enabling split bar charts with green ALFA bars and purple Trexis bars.

    Trexis is checked first (more specific). Exact warehouse names are used
    for the ALFA infrastructure WHs to avoid false matches.

    Example usage:
        company_col = get_company_case_expr() + " AS company"
        query = f"SELECT {company_col}, SUM(credits) FROM ... GROUP BY company"
    """
    return f"""CASE
        WHEN {wh_col} ILIKE 'WH_TRXS_%'
          OR {db_col} ILIKE 'TRXS_%'
          OR {user_col} ILIKE 'TRXS_%'
            THEN 'Trexis'
        WHEN {wh_col} ILIKE 'WH_ALFA_%'
          OR {wh_col} = 'BI_COMPUTE_WH'
          OR {wh_col} = 'COMPUTE_WH'
          OR {wh_col} = 'CROWDSTRIKE_WH'
          OR {wh_col} = 'DOC_AI_WH'
          OR {wh_col} = 'POSIT_WORKBENCH'
          OR {wh_col} = 'SNOWFLAKE_LEARNING_WH'
          OR {wh_col} ILIKE 'SYSTEM$STREAMLIT%'
          OR {db_col} ILIKE 'ALFA_%'
          OR {db_col} ILIKE 'ALFA_EDW%'
          OR {db_col} = 'ADMIN'
            THEN 'ALFA'
        ELSE 'Shared/Unclassified'
    END"""


# ── Global sidebar filter helpers ─────────────────────────────────────────────
# These read from session_state keys set by the sidebar in app.py.

def _text_filter_clause(value: str, column: str) -> str:
    """Build a safe ILIKE filter for a free-text sidebar input."""
    value = (value or "").strip()
    return f"AND {column} ILIKE {sql_literal('%' + value + '%')}" if value else ""


def get_global_date_clause(column: str = "start_time") -> str:
    start = st.session_state.get("global_start_date")
    end   = st.session_state.get("global_end_date")
    clauses = []
    if start:
        clauses.append(f"{column} >= TO_TIMESTAMP_NTZ('{start} 00:00:00')")
    if end:
        clauses.append(f"{column} < DATEADD('day', 1, TO_TIMESTAMP_NTZ('{end} 00:00:00'))")
    return "AND " + " AND ".join(clauses) if clauses else ""


def get_global_wh_filter_clause(column: str = "warehouse_name") -> str:
    return _text_filter_clause(st.session_state.get("global_warehouse"), column)


def get_global_user_filter_clause(column: str = "user_name") -> str:
    return _text_filter_clause(st.session_state.get("global_user"), column)


def get_global_role_filter_clause(column: str = "role_name") -> str:
    return _text_filter_clause(st.session_state.get("global_role"), column)


def get_global_db_filter_clause(column: str = "database_name") -> str:
    return _text_filter_clause(st.session_state.get("global_database"), column)


def get_global_filter_clause(
    date_col: str = "start_time",
    wh_col: str = "warehouse_name",
    user_col: str = "user_name",
    role_col: str = "role_name",
    db_col: str = "database_name",
) -> str:
    """Combine all active global sidebar filters into one WHERE fragment."""
    return " ".join(filter(None, [
        get_combined_filter_clause(db_col=db_col, wh_col=wh_col, user_col=user_col),
        get_global_date_clause(date_col)      if date_col  else "",
        get_global_wh_filter_clause(wh_col)   if wh_col    else "",
        get_global_user_filter_clause(user_col) if user_col else "",
        get_global_role_filter_clause(role_col) if role_col else "",
        get_global_db_filter_clause(db_col)   if db_col    else "",
    ])).strip()
