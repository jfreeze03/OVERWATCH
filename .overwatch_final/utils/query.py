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
import hashlib
import re
import time
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


def _record_query_telemetry(query_text: str, ttl_key: str, tier: str, elapsed_ms: float, row_count: int, used_cache: bool) -> None:
    """Keep a lightweight in-session trace of OVERWATCH query volume."""
    try:
        entries = st.session_state.setdefault("_overwatch_query_telemetry", [])
        entries.append({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "ttl_key": ttl_key,
            "tier": tier,
            "cache_enabled": bool(used_cache),
            "elapsed_ms": round(float(elapsed_ms), 2),
            "rows": int(row_count or 0),
            "query_hash": hashlib.sha1(str(query_text).encode("utf-8", errors="ignore")).hexdigest()[:12],
        })
        if len(entries) > 250:
            del entries[:-250]
    except Exception:
        pass


def _show_query_warning(prefix: str, error: Exception) -> None:
    message = f"{prefix}: {error}"
    seen = st.session_state.setdefault("_overwatch_query_warning_hashes", set())
    warning_hash = hashlib.sha1(message.encode("utf-8", errors="ignore")).hexdigest()[:12]
    if warning_hash in seen:
        return
    seen.add(warning_hash)
    st.warning(message)


def get_query_telemetry() -> pd.DataFrame:
    """Return recent query-run telemetry for the current Streamlit session."""
    return pd.DataFrame(st.session_state.get("_overwatch_query_telemetry", []))


def clear_query_telemetry() -> None:
    """Clear current session query telemetry."""
    st.session_state["_overwatch_query_telemetry"] = []


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


def sql_literal(value, max_len: int = 8000) -> str:
    """Return a quoted SQL string literal for generated DML/DDL."""
    if value is None:
        return "NULL"
    text = str(value).replace("\x00", "")[:max_len]
    return "'" + text.replace("'", "''") + "'"


def safe_identifier(value: str, allow_qualified: bool = False) -> str:
    """Validate a Snowflake identifier before embedding it into generated SQL."""
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Identifier cannot be blank")
    parts = raw.split(".") if allow_qualified else [raw]
    ident_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,254}$")
    if any(not ident_re.match(part) for part in parts):
        raise ValueError(f"Unsafe Snowflake identifier: {raw}")
    return ".".join(parts)


def safe_schedule(value: str) -> str:
    """Allow only Snowflake task schedule syntax characters used by generated SQL."""
    schedule = str(value or "").strip()
    if not schedule:
        raise ValueError("Schedule cannot be blank")
    if not re.match(r"^[A-Za-z0-9_*/?,#LW +:-]+$", schedule):
        raise ValueError("Schedule contains unsafe characters")
    if ";" in schedule or "'" in schedule or '"' in schedule:
        raise ValueError("Schedule contains unsafe quote or statement separator")
    return schedule


# ── Per-tier cache functions ───────────────────────────────────────────────────
# Each tier must be a separate decorated function because @st.cache_data TTL
# is fixed at decoration time — it cannot be passed as a runtime argument.

def _cache_context() -> str:
    # Avoid CURRENT_USER/CURRENT_ROLE here. In Streamlit-in-Snowflake this helper
    # can run inside a managed stored-procedure context where those calls may be
    # blocked before the actual page query gets a chance to execute.
    return "|".join([
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
        _show_query_warning("Live data unavailable", e)
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TIERS["recent"], show_spinner=False)
def _cached_recent(query_text: str, cache_context: str = "", cache_salt: str = "") -> pd.DataFrame:
    try:
        return normalize_df(get_session().sql(query_text).to_pandas())
    except Exception as e:
        _show_query_warning("Data unavailable", e)
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TIERS["historical"], show_spinner=False)
def _cached_historical(query_text: str, cache_context: str = "", cache_salt: str = "") -> pd.DataFrame:
    try:
        return normalize_df(get_session().sql(query_text).to_pandas())
    except Exception as e:
        _show_query_warning("Historical data unavailable", e)
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TIERS["metadata"], show_spinner=False)
def _cached_metadata(query_text: str, cache_context: str = "", cache_salt: str = "") -> pd.DataFrame:
    try:
        return normalize_df(get_session().sql(query_text).to_pandas())
    except Exception as e:
        _show_query_warning("Metadata unavailable", e)
        return pd.DataFrame()


# Backward-compatible 5-min cache — for callers that don't pass tier=
@st.cache_data(ttl=CACHE_TIERS["recent"], show_spinner=False)
def run_query_cached(query_text: str, cache_context: str = "", cache_salt: str = "") -> pd.DataFrame:
    """Backward-compatible runner. Prefer run_query(tier=...) for new code."""
    try:
        return normalize_df(get_session().sql(query_text).to_pandas())
    except Exception as e:
        _show_query_warning("Data unavailable", e)
        return pd.DataFrame()


_TIER_FN = {
    "live":       _cached_live,
    "standard":   _cached_historical,
    "recent":     _cached_recent,
    "historical": _cached_historical,
    "metadata":   _cached_metadata,
}


def _run_query_base(
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
        tier:        'live' | 'recent' | 'standard' | 'historical' | 'metadata'
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
                _show_query_warning("Data unavailable", e)
                return pd.DataFrame()
        except Exception as e:
            _show_query_warning("Query runner issue", e)
            return pd.DataFrame()


def run_query(
    query_text: str,
    ttl_key: str = "default",
    use_cache: bool = True,
    spinner_msg: str = "Loading data...",
    tier: str = "recent",
) -> pd.DataFrame:
    """Execute a query through the cached runner and log lightweight telemetry."""
    started = time.perf_counter()
    result = _run_query_base(
        query_text=query_text,
        ttl_key=ttl_key,
        use_cache=use_cache,
        spinner_msg=spinner_msg,
        tier=tier,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    _record_query_telemetry(query_text, ttl_key, tier, elapsed_ms, len(result), use_cache)
    return result


def run_query_or_raise(query_text: str) -> pd.DataFrame:
    """
    Execute SQL and return a normalized DataFrame, preserving exceptions.

    Use this for live probes and primary/fallback query paths where callers need
    the original Snowflake exception to decide whether to run a fallback query.
    """
    return normalize_df(get_session().sql(query_text).to_pandas())


def force_refresh(key: str):
    """Bump cache salt to force re-execution of a specific section's queries."""
    st.session_state[f"_refresh_salt_{key}"] = datetime.now().isoformat()
