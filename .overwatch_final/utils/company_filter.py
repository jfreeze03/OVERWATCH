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
import hashlib

import streamlit as st
import fnmatch
from config import COMPANY_CONFIG, DEFAULT_COMPANY
from .query import sql_literal
from .state_keys import PRESERVE_STATE_EXACT, PRESERVE_STATE_PREFIXES


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
    Preserves settings, theme, navigation, and global filters.
    """
    keys_to_drop = [
        k for k in list(st.session_state.keys())
        if k not in PRESERVE_STATE_EXACT
        and not any(k.startswith(p) for p in PRESERVE_STATE_PREFIXES)
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

    ALFA:   explicit ALFA/shared warehouse allowlist, excluding Trexis
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
    Return the strongest available company boundary filter.

    Warehouse/database names are stronger company signals than user names
    because shared/admin users can operate across company-specific resources.
    User-name scoping is kept for user-only views such as login/grant reports.

    When more than one signal is available, use an OR boundary with explicit
    opposite-company exclusions. Requiring warehouse AND database to both match
    drops valid operational rows such as warehouse/session statements that have
    no database context.
    """
    company = company or get_active_company()
    if company == "ALL":
        return ""

    cfg = get_company_cfg(company)

    def _matches(column: str, patterns: list[str]) -> str:
        parts = [
            f"{column} = {sql_literal(pattern, 300)}"
            if "%" not in str(pattern)
            else f"{column} ILIKE {sql_literal(pattern, 300)}"
            for pattern in patterns
            if pattern
        ]
        return "(" + " OR ".join(parts) + ")" if parts else ""

    def _excludes(column: str, patterns: list[str]) -> str:
        parts = [
            f"{column} <> {sql_literal(pattern, 300)}"
            if "%" not in str(pattern)
            else f"{column} NOT ILIKE {sql_literal(pattern, 300)}"
            for pattern in patterns
            if pattern
        ]
        if not parts:
            return ""
        return f"({column} IS NULL OR ({' AND '.join(parts)}))"

    candidates = []
    exclusions = []
    if wh_col:
        wh_match = _matches(wh_col, cfg.get("wh_patterns", []))
        if wh_match:
            candidates.append(f"({wh_col} IS NOT NULL AND {wh_match})")
        wh_exclude = _excludes(wh_col, cfg.get("wh_exclude_patterns", []))
        if wh_exclude:
            exclusions.append(wh_exclude)
    if db_col:
        db_match = _matches(db_col, cfg.get("db_patterns", []))
        if db_match:
            candidates.append(f"({db_col} IS NOT NULL AND {db_match})")
        db_exclude = _excludes(db_col, [cfg.get("exclude_db_pattern", "")] if cfg.get("exclude_db_pattern") else [])
        if db_exclude:
            exclusions.append(db_exclude)
    if user_col:
        user_match = _matches(user_col, cfg.get("user_patterns", []))
        if user_match:
            candidates.append(f"({user_col} IS NOT NULL AND {user_match})")
        user_exclude = _excludes(user_col, cfg.get("user_exclude_patterns", []))
        if user_exclude:
            exclusions.append(user_exclude)

    if candidates:
        boundary = "(" + " OR ".join(candidates) + ")"
        if exclusions:
            boundary += " AND " + " AND ".join(exclusions)
        return "AND " + boundary

    return get_user_filter_clause(user_col, company).strip() if user_col else ""


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


def get_company_scope_key(prefix: str, *parts: object) -> str:
    """Build a cache key that includes company and global filter state."""
    payload = "|".join([
        str(prefix),
        str(get_active_company()),
        str(st.session_state.get("global_start_date", "")),
        str(st.session_state.get("global_end_date", "")),
        str(st.session_state.get("global_warehouse", "")),
        str(st.session_state.get("global_user", "")),
        str(st.session_state.get("global_role", "")),
        str(st.session_state.get("global_database", "")),
        *[str(part) for part in parts],
    ])
    return f"{prefix}_{hashlib.sha1(payload.encode('utf-8', errors='ignore')).hexdigest()[:12]}"


def company_scoped_query(
    query_text: str,
    ttl_prefix: str,
    *,
    tier: str = "recent",
    use_cache: bool = True,
    spinner_msg: str = "Loading data...",
    date_col: str = "start_time",
    wh_col: str = "warehouse_name",
    user_col: str = "user_name",
    role_col: str = "role_name",
    db_col: str = "database_name",
    include_global_filters: bool = True,
    section: str = "",
    extra_cache_parts: tuple = (),
):
    """
    Execute SQL with a consistent company/global filter placeholder and cache key.

    Put `{company_scope}` or `{global_scope}` in the SQL where a WHERE fragment
    should be injected. If no placeholder is present, the query is left unchanged.
    """
    from .query import run_query

    scope_clause = (
        get_global_filter_clause(
            date_col=date_col,
            wh_col=wh_col,
            user_col=user_col,
            role_col=role_col,
            db_col=db_col,
        )
        if include_global_filters
        else get_combined_filter_clause(db_col=db_col, wh_col=wh_col, user_col=user_col)
    )
    sql = (
        str(query_text)
        .replace("{company_scope}", scope_clause)
        .replace("{global_scope}", scope_clause)
    )
    return run_query(
        sql,
        ttl_key=get_company_scope_key(ttl_prefix, *extra_cache_parts),
        use_cache=use_cache,
        spinner_msg=spinner_msg,
        tier=tier,
        section=section,
    )
