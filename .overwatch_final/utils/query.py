# utils/query.py — Tiered cached query execution + SQL safety
# ─────────────────────────────────────────────────────────────────────────────
# FIXES vs previous version:
#   1. safe_sql(): added 2000-char hard cap (prompt injection prevention)
#   2. run_query_cached(): wrapped bare session.sql() in try/except
#      (was unguarded — any Snowflake error caused an unhandled exception
#      that crashed the entire section render with a red error page)
#   3. Tiered cache TTLs: live=30s, recent=300s, historical=1800s, metadata=14400s
#      (previous version had a single flat 300s TTL for all query types)
# ─────────────────────────────────────────────────────────────────────────────
import re
import streamlit as st
import pandas as pd
from datetime import datetime
from .session import get_session
from .data import normalize_df

CACHE_TIERS: dict[str, int] = {
    "live":       30,     # INFORMATION_SCHEMA — real-time, 30s stale is fine
    "recent":     300,    # ACCOUNT_USAGE last 4h — 5-min cache
    "historical": 1800,   # ACCOUNT_USAGE 7d+  — 30-min cache
    "metadata":   14400,  # SHOW WAREHOUSES, SHOW TASKS, USERS — 4-hour cache
}


def safe_sql(value: str) -> str:
    """
    Sanitize user input before embedding in SQL or Cortex prompts.
    - Strips SQL comment injection tokens (--, /* */, ;)
    - Escapes single quotes (value is embedded inside a SQL string literal)
    - Hard cap at 2000 chars — prevents prompt injection via oversized input
    """
    if not value:
        return ""
    sanitized = re.sub(r"(--|/\*|\*/|;)", "", str(value))
    sanitized = sanitized.replace("'", "''").strip()
    return sanitized[:2000]


# ── Per-tier cache functions ───────────────────────────────────────────────────
# Each tier must be a separate decorated function because @st.cache_data TTL
# is fixed at decoration time — it cannot be passed as a runtime argument.

def _cache_context() -> str:
    try:
        sess = get_session()
        row = sess.sql("""
            SELECT CURRENT_USER() AS user_name, CURRENT_ROLE() AS role_name
        """).collect()[0]
        user_name = row[0]
        role_name = row[1]
    except Exception:
        user_name = "unknown"
        role_name = "unknown"
    return "|".join([
        str(user_name),
        str(role_name),
        str(st.session_state.get("active_company", "")),
        str(st.session_state.get("global_start_date", "")),
        str(st.session_state.get("global_end_date", "")),
        str(st.session_state.get("global_warehouse", "")),
        str(st.session_state.get("global_user", "")),
        str(st.session_state.get("global_role", "")),
        str(st.session_state.get("global_database", "")),
    ])


@st.cache_data(ttl=CACHE_TIERS["live"], show_spinner=False)
def _cached_live(query_text: str, cache_context: str = "", cache_salt: str = "") -> pd.DataFrame:
    try:
        return normalize_df(get_session().sql(query_text).to_pandas())
    except Exception as e:
        st.error(f"Live query error: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TIERS["recent"], show_spinner=False)
def _cached_recent(query_text: str, cache_context: str = "", cache_salt: str = "") -> pd.DataFrame:
    try:
        return normalize_df(get_session().sql(query_text).to_pandas())
    except Exception as e:
        st.error(f"Query error: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TIERS["historical"], show_spinner=False)
def _cached_historical(query_text: str, cache_context: str = "", cache_salt: str = "") -> pd.DataFrame:
    try:
        return normalize_df(get_session().sql(query_text).to_pandas())
    except Exception as e:
        st.error(f"Query error: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TIERS["metadata"], show_spinner=False)
def _cached_metadata(query_text: str, cache_context: str = "", cache_salt: str = "") -> pd.DataFrame:
    try:
        return normalize_df(get_session().sql(query_text).to_pandas())
    except Exception as e:
        st.error(f"Metadata query error: {e}")
        return pd.DataFrame()


# Backward-compatible 5-min cache — for callers that don't pass tier=
@st.cache_data(ttl=CACHE_TIERS["recent"], show_spinner=False)
def run_query_cached(query_text: str, cache_context: str = "", cache_salt: str = "") -> pd.DataFrame:
    """Backward-compatible runner. Prefer run_query(tier=...) for new code."""
    try:
        return normalize_df(get_session().sql(query_text).to_pandas())
    except Exception as e:
        st.error(f"Query error: {e}")
        return pd.DataFrame()


_TIER_FN = {
    "live":       _cached_live,
    "recent":     _cached_recent,
    "historical": _cached_historical,
    "metadata":   _cached_metadata,
}


def run_query(
    query_text: str,
    ttl_key: str = "default",
    use_cache: bool = True,
    spinner_msg: str = "Loading data...",
    tier: str = "recent",
) -> pd.DataFrame:
    """
    Central query runner with tiered caching and full error handling.

    Args:
        query_text:  SQL to execute.
        ttl_key:     Cache salt namespace (per section, per parameter set).
        use_cache:   False to bypass cache entirely (explicit refresh).
        spinner_msg: Shown while executing.
        tier:        'live' | 'recent' | 'historical' | 'metadata'
                     Default 'recent' (300s) for backward compatibility.

    Returns:
        Normalized DataFrame. Empty DataFrame on any error (never raises).
    """
    with st.spinner(spinner_msg):
        try:
            if use_cache:
                cache_salt = st.session_state.get(f"_refresh_salt_{ttl_key}", "")
                context = _cache_context()
                fn   = _TIER_FN.get(tier, _cached_recent)
                return fn(query_text, context, cache_salt)
            # Bypass cache — always wrapped in try/except
            try:
                return normalize_df(get_session().sql(query_text).to_pandas())
            except Exception as e:
                st.error(f"Query error: {e}")
                return pd.DataFrame()
        except Exception as e:
            st.error(f"Query runner error: {e}")
            return pd.DataFrame()


def force_refresh(key: str):
    """Bump cache salt to force re-execution of a specific section's queries."""
    st.session_state[f"_refresh_salt_{key}"] = datetime.now().isoformat()
