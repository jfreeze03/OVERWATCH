# utils/company_filter.py - multi-tenant company filtering for ALFA and Trexis.
#
# Warehouse strategy:
#   ALFA: every warehouse except the exact Trexis allowlist.
#   Trexis: WH_TRXS_LOAD, WH_TRXS_QUERY, WH_TRXS_TRANSFORM, WH_TRXS_UNLOAD.
# Database strategy:
#   ALFA: ALFA/ADMIN databases, excluding the exact Trexis database allowlist.
#   Trexis: exact TRXS database families, split into PROD and DEV/SIT.
# Role/user strategy:
#   Trexis: TRXS_* users and roles containing TRXS when telemetry exposes them.
#   ALL: no filter; get_company_case_expr() labels each row.
import hashlib
import re
from datetime import datetime

import streamlit as st
import fnmatch
from config import (
    COMPANY_CONFIG,
    DEFAULT_COMPANY,
    ENVIRONMENT_CONFIG,
    ENVIRONMENT_OPTIONS_BY_COMPANY,
    DEFAULT_ENVIRONMENT,
)
from runtime_state import (
    ACTIVE_COMPANY,
    GLOBAL_DATABASE,
    GLOBAL_END_DATE,
    GLOBAL_ENVIRONMENT,
    GLOBAL_ROLE,
    GLOBAL_SCHEMA,
    GLOBAL_START_DATE,
    GLOBAL_USER,
    GLOBAL_WAREHOUSE,
    REFRESH_SALT_GLOBAL,
    get_state,
    pop_state,
    set_state,
)
from .state_keys import PRESERVE_STATE_EXACT, PRESERVE_STATE_PREFIXES
from .sql_safe import sql_literal


_SAFE_FILTER_PATTERN = re.compile(r"^[A-Za-z0-9_%@.\- ]{0,128}$")
_BLOCKED_SQL_PATTERN = re.compile(
    r"(;|--|/\*|\*/|\bUNION\b|\bSELECT\b|\bINSERT\b|\bUPDATE\b|\bDELETE\b|\bDROP\b|\bALTER\b|\bGRANT\b|\bREVOKE\b|\bCALL\b)",
    re.IGNORECASE,
)


def validate_filter_input(value: object, *, max_len: int = 128) -> str:
    """Return a conservative free-text filter value for sidebar search boxes."""
    text = str(value or "").strip()[:max_len]
    if not text:
        return ""
    text = re.sub(r"[^A-Za-z0-9_%@.\- ]", "", text)
    if _BLOCKED_SQL_PATTERN.search(text) or not _SAFE_FILTER_PATTERN.match(text):
        return ""
    return text


def assert_no_sql_injection(clause: str) -> str:
    """Fail closed if a generated filter clause contains SQL-control tokens."""
    text = str(clause or "")
    stripped = re.sub(r"'(?:''|[^'])*'", "''", text)
    if _BLOCKED_SQL_PATTERN.search(stripped):
        raise ValueError("Unsafe SQL filter clause rejected")
    return text


def _match_any_sql(column: str, patterns: list[str]) -> str:
    values = [str(pattern or "").strip() for pattern in patterns if str(pattern or "").strip()]
    if not values:
        return ""
    if all("%" not in value for value in values):
        literals = ", ".join(sql_literal(value.upper(), 300) for value in values)
        return f"UPPER({column}) IN ({literals})"
    parts = [
        f"UPPER({column}) = {sql_literal(value.upper(), 300)}"
        if "%" not in value
        else f"{column} ILIKE {sql_literal(value, 300)}"
        for value in values
    ]
    return "(" + " OR ".join(parts) + ")"


def _exclude_all_sql(column: str, patterns: list[str], *, allow_null: bool = False) -> str:
    values = [str(pattern or "").strip() for pattern in patterns if str(pattern or "").strip()]
    if not values:
        return ""
    if all("%" not in value for value in values):
        literals = ", ".join(sql_literal(value.upper(), 300) for value in values)
        predicate = f"UPPER({column}) NOT IN ({literals})"
    else:
        parts = [
            f"UPPER({column}) <> {sql_literal(value.upper(), 300)}"
            if "%" not in value
            else f"{column} NOT ILIKE {sql_literal(value, 300)}"
            for value in values
        ]
        predicate = "(" + " AND ".join(parts) + ")"
    return f"({column} IS NULL OR {predicate})" if allow_null else predicate


def get_active_company() -> str:
    """Return currently selected company key. Defaults to ALFA (never ALL)."""
    return get_state(ACTIVE_COMPANY, DEFAULT_COMPANY)


def get_company_cfg(company: str = None) -> dict:
    """Return config dict for the given (or active) company."""
    company = company or get_active_company()
    return COMPANY_CONFIG.get(company, COMPANY_CONFIG["ALL"])


def get_active_environment() -> str:
    """Return the selected environment scope for the active company."""
    env = str(get_state(GLOBAL_ENVIRONMENT, DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)
    if env not in ENVIRONMENT_CONFIG:
        return DEFAULT_ENVIRONMENT
    company = get_state(ACTIVE_COMPANY, DEFAULT_COMPANY)
    options = ENVIRONMENT_OPTIONS_BY_COMPANY.get(company, ENVIRONMENT_OPTIONS_BY_COMPANY.get("ALL", (DEFAULT_ENVIRONMENT,)))
    return env if env in options else DEFAULT_ENVIRONMENT


def get_environment_cfg(environment: str = None) -> dict:
    """Return config dict for the given (or active) environment scope."""
    environment = environment or get_active_environment()
    return ENVIRONMENT_CONFIG.get(environment, ENVIRONMENT_CONFIG[DEFAULT_ENVIRONMENT])


def get_environment_options_for_company(company: str = None) -> tuple[str, ...]:
    """Return sidebar environment options for the selected company scope."""
    company = company or get_active_company()
    options = ENVIRONMENT_OPTIONS_BY_COMPANY.get(company, ENVIRONMENT_OPTIONS_BY_COMPANY.get("ALL", (DEFAULT_ENVIRONMENT,)))
    return tuple(key for key in options if key in ENVIRONMENT_CONFIG) or (DEFAULT_ENVIRONMENT,)


def get_environment_label(environment: str = None, company: str = None) -> str:
    """Return the display label for an environment key in the active company scope."""
    environment = environment or get_active_environment()
    cfg = get_environment_cfg(environment)
    if str(company or get_active_company()).upper() == "TREXIS" and cfg.get("trexis_label"):
        return str(cfg["trexis_label"])
    return str(cfg.get("label", environment))


def get_environment_db_patterns(environment: str = None, company: str = None) -> list[str]:
    """Return database names/patterns for an environment under the company scope."""
    environment = environment or get_active_environment()
    if str(environment or "").upper() == "ALL":
        return []
    cfg = get_environment_cfg(environment)
    company_key = company or get_active_company()
    company_patterns = cfg.get("company_db_patterns", {}).get(company_key)
    if company_patterns is not None:
        return list(company_patterns)
    return list(cfg.get("db_patterns", []))


def _all_environment_db_patterns(environment: str) -> list[str]:
    cfg = get_environment_cfg(environment)
    values = list(cfg.get("db_patterns", []))
    for patterns in cfg.get("company_db_patterns", {}).values():
        values.extend(patterns)
    return list(dict.fromkeys(str(value).upper() for value in values if value))


# Cache invalidation

_METADATA_CACHE_PREFIXES = (
    "_overwatch_available_columns",
    "_overwatch_unavailable_column_views",
    "_overwatch_column_probe",
    "_overwatch_qh_detail_exprs",
)


def invalidate_company_cache(
    *,
    clear_streamlit_cache: bool = False,
    clear_metadata: bool = False,
):
    """
    Clear all section data from session_state when the company filter changes.
    Without this, stale Trexis data lingers in ALFA view (and vice versa).
    Preserves settings, theme, navigation, and triage filters.

    The query cache already includes active company in its context, so normal
    company switches only drop loaded panel state. A hard refresh can still
    purge st.cache_data through utils.cache.clear_all_cache().
    """
    keys_to_drop = [
        k for k in list(st.session_state.keys())
        if k not in PRESERVE_STATE_EXACT
        and not any(k.startswith(p) for p in PRESERVE_STATE_PREFIXES)
        and (clear_metadata or not any(k.startswith(p) for p in _METADATA_CACHE_PREFIXES))
    ]
    for k in keys_to_drop:
        pop_state(k, None)
    if clear_streamlit_cache:
        set_state(REFRESH_SALT_GLOBAL, datetime.now().isoformat())


# WHERE clause builders

def get_wh_filter_clause(column: str = "warehouse_name", company: str = None) -> str:
    """
    Return SQL WHERE fragment to filter by warehouse.

    ALFA:   explicit ALFA/shared warehouse allowlist, excluding Trexis
    Trexis: exact WH_TRXS_LOAD / QUERY / TRANSFORM / UNLOAD allowlist
    ALL:    '' - no filter; use get_company_case_expr() to label rows instead
    """
    cfg = get_company_cfg(company)
    include = cfg.get("wh_patterns", [])
    exclude = cfg.get("wh_exclude_patterns", [])

    clauses = []
    if include:
        clauses.append(f"({_match_any_sql(column, include)})")
    if exclude:
        clauses.append(f"({_exclude_all_sql(column, exclude)})")

    return "AND " + " AND ".join(clauses) if clauses else ""


def get_db_filter_clause(column: str = "database_name", company: str = None) -> str:
    """Return SQL WHERE fragment to filter databases by company and environment."""
    cfg = get_company_cfg(company)
    patterns   = cfg.get("db_patterns", [])
    exclude_pt = cfg.get("exclude_db_pattern", "")
    excludes = list(cfg.get("db_exclude_patterns", []))
    if exclude_pt:
        excludes.append(exclude_pt)

    clauses = []
    if patterns:
        clauses.append(f"({_match_any_sql(column, patterns)})")
    if excludes:
        clauses.append(f"({_exclude_all_sql(column, excludes)})")
    env_clause = get_environment_filter_clause(column, company=company)
    if env_clause:
        clauses.append(env_clause.removeprefix("AND ").strip())

    return "AND " + " AND ".join(clauses) if clauses else ""


def get_user_filter_clause(column: str = "user_name", company: str = None) -> str:
    """Return SQL WHERE fragment to filter users by company."""
    cfg = get_company_cfg(company)
    patterns = cfg.get("user_patterns", [])
    exclude = cfg.get("user_exclude_patterns", [])
    clauses = []
    if patterns:
        clauses.append(f"({_match_any_sql(column, patterns)})")
    if exclude:
        clauses.append(f"({_exclude_all_sql(column, exclude)})")
    return "AND " + " AND ".join(clauses) if clauses else ""


def get_role_filter_clause(column: str = "role_name", company: str = None) -> str:
    """Return SQL WHERE fragment to filter role-like names by company."""
    cfg = get_company_cfg(company)
    patterns = cfg.get("role_patterns", cfg.get("user_patterns", []))
    exclude = cfg.get("role_exclude_patterns", cfg.get("user_exclude_patterns", []))
    clauses = []
    if patterns:
        clauses.append(f"({_match_any_sql(column, patterns)})")
    if exclude:
        clauses.append(f"({_exclude_all_sql(column, exclude)})")
    return "AND " + " AND ".join(clauses) if clauses else ""


def _active_role_membership_sql(user_col: str, role_patterns: list[str]) -> str:
    role_match = _match_any_sql('role_scope."ROLE"', role_patterns)
    if not role_match:
        return ""
    return (
        "EXISTS ("
        "SELECT 1 FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS role_scope "
        "WHERE role_scope.DELETED_ON IS NULL "
        f"AND UPPER(role_scope.GRANTEE_NAME) = UPPER(TO_VARCHAR({user_col})) "
        f"AND {role_match}"
        ")"
    )


def get_user_company_filter_clause(column: str = "user_name", company: str = None) -> str:
    """Return a user filter using both username and active role membership signals."""
    company = company or get_active_company()
    if company == "ALL":
        return ""
    cfg = get_company_cfg(company)
    candidates = []
    exclusions = []

    user_match = _match_any_sql(column, cfg.get("user_patterns", []))
    if user_match:
        candidates.append(f"({column} IS NOT NULL AND {user_match})")
    role_match = _active_role_membership_sql(column, cfg.get("role_patterns", []))
    if role_match:
        candidates.append(role_match)

    user_exclude = _exclude_all_sql(column, cfg.get("user_exclude_patterns", []), allow_null=True)
    if user_exclude:
        exclusions.append(user_exclude)
    role_exclude = _active_role_membership_sql(column, cfg.get("role_exclude_patterns", []))
    if role_exclude:
        exclusions.append(f"NOT {role_exclude}")

    if candidates:
        boundary = "(" + " OR ".join(candidates) + ")"
        if exclusions:
            boundary += " AND " + " AND ".join(exclusions)
        return "AND " + boundary
    if exclusions:
        return "AND " + " AND ".join(exclusions)
    return get_user_filter_clause(column, company)


def company_value_allowed(value: str, kind: str = "database", company: str = None) -> bool:
    """Return whether an entered DB/user/warehouse value belongs to the active scope."""
    company = company or get_active_company()
    if company == "ALL":
        company_allowed = True
    else:
        company_allowed = None
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
    elif kind == "role":
        include = cfg.get("role_patterns", cfg.get("user_patterns", []))
        exclude = cfg.get("role_exclude_patterns", cfg.get("user_exclude_patterns", []))
    else:
        include = cfg.get("db_patterns", [])
        exclude = list(cfg.get("db_exclude_patterns", []))
        if cfg.get("exclude_db_pattern"):
            exclude.append(cfg.get("exclude_db_pattern", ""))

    def _match(pattern: str) -> bool:
        return fnmatch.fnmatchcase(text, str(pattern or "").upper().replace("%", "*"))

    if any(_match(pattern) for pattern in exclude):
        return False
    if company_allowed is None:
        company_allowed = any(_match(pattern) for pattern in include) if include else True
    if not company_allowed:
        return False
    if kind == "database" and not environment_value_allowed(value, company=company):
        return False
    return True


def environment_value_allowed(value: str, environment: str = None, company: str = None) -> bool:
    """Return whether a database/environment value belongs to the selected scope."""
    company = company or get_active_company()
    environment = environment or get_active_environment()
    if str(environment or "").upper() == "ALL":
        return True
    env = str(environment or "").upper()
    patterns = get_environment_db_patterns(environment, company)
    if not patterns:
        return True
    text = str(value or "").upper()
    if not text:
        return False
    if env == "PROD" and text == "PROD":
        return True
    if env == "DEV_ALL" and text in {"DEV_ALL", "ALL DEV/SANDBOX", "ALL DEV/SIT"}:
        return True

    def _match(pattern: str) -> bool:
        return fnmatch.fnmatchcase(text, str(pattern or "").upper().replace("%", "*"))

    return any(_match(pattern) for pattern in patterns)


def get_combined_filter_clause(
    db_col: str = "database_name",
    wh_col: str = "warehouse_name",
    user_col: str = "user_name",
    role_col: str = "role_name",
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

    candidates = []
    exclusions = []
    if wh_col:
        wh_match = _match_any_sql(wh_col, cfg.get("wh_patterns", []))
        if wh_match:
            candidates.append(f"({wh_col} IS NOT NULL AND {wh_match})")
        wh_exclude = _exclude_all_sql(wh_col, cfg.get("wh_exclude_patterns", []), allow_null=True)
        if not wh_match and cfg.get("wh_exclude_patterns"):
            wh_allowed = _exclude_all_sql(wh_col, cfg.get("wh_exclude_patterns", []))
            if wh_allowed:
                candidates.append(f"({wh_col} IS NOT NULL AND TRIM(TO_VARCHAR({wh_col})) <> '' AND {wh_allowed})")
        if wh_exclude:
            exclusions.append(wh_exclude)
    if db_col:
        db_match = _match_any_sql(db_col, cfg.get("db_patterns", []))
        if db_match:
            candidates.append(f"({db_col} IS NOT NULL AND {db_match})")
        db_excludes = list(cfg.get("db_exclude_patterns", []))
        if cfg.get("exclude_db_pattern"):
            db_excludes.append(cfg.get("exclude_db_pattern", ""))
        db_exclude = _exclude_all_sql(db_col, db_excludes, allow_null=True)
        if db_exclude:
            exclusions.append(db_exclude)
    if user_col:
        user_match = _match_any_sql(user_col, cfg.get("user_patterns", []))
        if user_match:
            candidates.append(f"({user_col} IS NOT NULL AND {user_match})")
        user_exclude = _exclude_all_sql(user_col, cfg.get("user_exclude_patterns", []), allow_null=True)
        if user_exclude:
            exclusions.append(user_exclude)
    if role_col:
        role_match = _match_any_sql(role_col, cfg.get("role_patterns", cfg.get("user_patterns", [])))
        if role_match:
            candidates.append(f"({role_col} IS NOT NULL AND {role_match})")
        role_exclude = _exclude_all_sql(
            role_col,
            cfg.get("role_exclude_patterns", cfg.get("user_exclude_patterns", [])),
            allow_null=True,
        )
        if role_exclude:
            exclusions.append(role_exclude)

    if candidates:
        boundary = "(" + " OR ".join(candidates) + ")"
        if exclusions:
            boundary += " AND " + " AND ".join(exclusions)
        return "AND " + boundary

    fallback = get_user_filter_clause(user_col, company).strip() if user_col else ""
    if fallback:
        return fallback
    return get_role_filter_clause(role_col, company).strip() if role_col else ""


# ALL-mode classification expression

def get_company_case_expr(
    wh_col: str = "warehouse_name",
    db_col: str = "database_name",
    user_col: str = "user_name",
    role_col: str = "role_name",
) -> str:
    """
    SQL CASE expression that classifies every row as 'ALFA', 'Trexis',
    or 'Shared/Unclassified'.

    Use this in ALL-mode queries so one query returns both companies labeled -
    enabling split bar charts with green ALFA bars and purple Trexis bars.

    Trexis is checked first (more specific). Exact warehouse names are used
    for the ALFA infrastructure WHs to avoid false matches.

    Example usage:
        company_col = get_company_case_expr() + " AS company"
        query = f"SELECT {company_col}, SUM(credits) FROM ... GROUP BY company"
    """
    trexis_cfg = COMPANY_CONFIG.get("Trexis", {})
    trexis_wh_predicate = _match_any_sql(wh_col, trexis_cfg.get("wh_patterns", [])) or "1 = 0"
    trexis_db_predicate = _match_any_sql(db_col, trexis_cfg.get("db_patterns", [])) or "1 = 0"
    role_predicate = f"OR {role_col} ILIKE '%TRXS%'" if role_col else ""
    return f"""CASE
        WHEN ({trexis_wh_predicate})
          OR ({trexis_db_predicate})
          OR {user_col} ILIKE 'TRXS_%'
          {role_predicate}
            THEN 'Trexis'
        WHEN NULLIF(TRIM(TO_VARCHAR({wh_col})), '') IS NOT NULL
          OR {db_col} ILIKE 'ALFA_%'
          OR {db_col} ILIKE 'ALFA_EDW%'
          OR {db_col} = 'ADMIN'
            THEN 'ALFA'
        ELSE 'Shared/Unclassified'
    END"""


# Global sidebar filter helpers
# These read from session_state keys set by the sidebar in app.py.

def _text_filter_clause(value: str, column: str) -> str:
    """Build a safe ILIKE filter for a free-text sidebar input."""
    value = validate_filter_input(value)
    clause = f"AND {column} ILIKE {sql_literal('%' + value + '%')}" if value else ""
    return assert_no_sql_injection(clause) if clause else ""


def get_global_date_clause(column: str = "start_time") -> str:
    start = get_state(GLOBAL_START_DATE)
    end = get_state(GLOBAL_END_DATE)
    clauses = []
    if start:
        clauses.append(f"{column} >= TO_TIMESTAMP_NTZ('{start} 00:00:00')")
    if end:
        clauses.append(f"{column} < DATEADD('day', 1, TO_TIMESTAMP_NTZ('{end} 00:00:00'))")
    return "AND " + " AND ".join(clauses) if clauses else ""


def get_global_wh_filter_clause(column: str = "warehouse_name") -> str:
    return _text_filter_clause(get_state(GLOBAL_WAREHOUSE), column)


def get_global_user_filter_clause(column: str = "user_name") -> str:
    return _text_filter_clause(get_state(GLOBAL_USER), column)


def get_global_role_filter_clause(column: str = "role_name") -> str:
    return _text_filter_clause(get_state(GLOBAL_ROLE), column)


def get_global_db_filter_clause(column: str = "database_name") -> str:
    return _text_filter_clause(get_state(GLOBAL_DATABASE), column)


def get_global_schema_filter_clause(column: str = "schema_name") -> str:
    return _text_filter_clause(get_state(GLOBAL_SCHEMA), column)


def get_environment_filter_clause(
    column: str = "database_name",
    environment: str = None,
    company: str = None,
) -> str:
    """Return SQL WHERE fragment for PROD/DEV database-family filtering."""
    company = company or get_active_company()
    environment = environment or get_active_environment()
    if str(environment or "").upper() == "ALL":
        return ""
    patterns = get_environment_db_patterns(environment, company)
    if not patterns:
        return ""
    return f"AND ({_match_any_sql(column, patterns)})"


def get_environment_filter_or_no_database_clause(
    column: str = "database_name",
    environment: str = None,
    company: str = None,
) -> str:
    """Filter database-context rows by environment while retaining account-scope rows."""
    env_clause = get_environment_filter_clause(column, environment=environment, company=company)
    if not env_clause:
        return ""
    env_predicate = env_clause.removeprefix("AND ").strip()
    return f"AND ({column} IS NULL OR TRIM(TO_VARCHAR({column})) = '' OR {env_predicate})"


def environment_label_for_database(database_name: object) -> str:
    """Return the display environment label for a Snowflake database name."""
    db = str(database_name or "").strip().upper()
    if not db:
        return "No Database Context"
    if db in set(_all_environment_db_patterns("PROD")):
        return "PROD"
    trexis_dev = set(str(value).upper() for value in get_environment_db_patterns("DEV_ALL", "Trexis"))
    if db in trexis_dev:
        return "DEV_ALL"
    alfa_dev = set(str(value).upper() for value in get_environment_db_patterns("DEV_ALL", "ALFA"))
    if db in alfa_dev:
        return db
    if db.startswith("ALFA_EDW_"):
        return "Other ALFA Non-Prod"
    return "Other / Shared"


def get_environment_case_expr(db_col: str = "database_name") -> str:
    """Classify databases into PROD, DEV/SIT, individual ALFA DEV, or Other."""
    prod_predicate = _match_any_sql(db_col, _all_environment_db_patterns("PROD")) or "1 = 0"
    trexis_dev_predicate = _match_any_sql(db_col, get_environment_db_patterns("DEV_ALL", "Trexis")) or "1 = 0"
    return f"""CASE
        WHEN {prod_predicate} THEN 'PROD'
        WHEN {trexis_dev_predicate} THEN 'DEV_ALL'
        WHEN UPPER({db_col}) = 'ALFA_EDW_DEV' THEN 'ALFA_EDW_DEV'
        WHEN UPPER({db_col}) = 'ALFA_EDW_SAN' THEN 'ALFA_EDW_SAN'
        WHEN UPPER({db_col}) = 'ALFA_EDW_PHX' THEN 'ALFA_EDW_PHX'
        WHEN UPPER({db_col}) = 'ALFA_EDW_SEA' THEN 'ALFA_EDW_SEA'
        WHEN UPPER({db_col}) = 'ALFA_EDW_SIT' THEN 'ALFA_EDW_SIT'
        WHEN {db_col} ILIKE 'ALFA_EDW_%' THEN 'Other ALFA Non-Prod'
        WHEN {db_col} IS NULL THEN 'No Database Context'
        ELSE 'Other / Shared'
    END"""


def get_global_filter_clause(
    date_col: str = "start_time",
    wh_col: str = "warehouse_name",
    user_col: str = "user_name",
    role_col: str = "role_name",
    db_col: str = "database_name",
    schema_col: str = "",
    *,
    include_company_scope: bool = True,
    include_environment_scope: bool = True,
    preserve_no_database_context: bool = False,
) -> str:
    """Combine active sidebar filters into one WHERE fragment.

    By default this includes company and environment scope for backward
    compatibility. Callers that already apply their own company boundary can
    set include_company_scope=False to avoid duplicate predicates.
    """
    environment_clause = ""
    if include_environment_scope and db_col:
        environment_clause = (
            get_environment_filter_or_no_database_clause(db_col)
            if preserve_no_database_context
            else get_environment_filter_clause(db_col)
        )
    company_clause = (
        get_combined_filter_clause(db_col=db_col, wh_col=wh_col, user_col=user_col, role_col=role_col)
        if include_company_scope
        else ""
    )
    return " ".join(filter(None, [
        company_clause,
        environment_clause,
        get_global_date_clause(date_col)      if date_col  else "",
        get_global_wh_filter_clause(wh_col)   if wh_col    else "",
        get_global_user_filter_clause(user_col) if user_col else "",
        get_global_role_filter_clause(role_col) if role_col else "",
        get_global_db_filter_clause(db_col)   if db_col    else "",
        get_global_schema_filter_clause(schema_col) if schema_col else "",
    ])).strip()


def get_company_scope_key(prefix: str, *parts: object) -> str:
    """Build a cache key that includes company and global filter state."""
    payload = "|".join([
        str(prefix),
        str(get_active_company()),
        str(get_state(GLOBAL_START_DATE, "")),
        str(get_state(GLOBAL_END_DATE, "")),
        str(get_state(GLOBAL_WAREHOUSE, "")),
        str(get_state(GLOBAL_USER, "")),
        str(get_state(GLOBAL_ROLE, "")),
        str(get_state(GLOBAL_DATABASE, "")),
        str(get_state(GLOBAL_SCHEMA, "")),
        str(get_active_environment()),
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
    schema_col: str = "",
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
            schema_col=schema_col,
        )
        if include_global_filters
        else get_combined_filter_clause(db_col=db_col, wh_col=wh_col, user_col=user_col, role_col=role_col)
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
