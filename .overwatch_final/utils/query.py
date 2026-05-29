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

QUERY_BUDGET_THRESHOLDS = {
    "slow_elapsed_ms": 10_000,
    "large_rows": 25_000,
    "large_result_mb": 25.0,
    "repeat_warning_count": 3,
}


def _estimate_result_mb(result: pd.DataFrame) -> float:
    """Estimate result-set memory size for budget telemetry."""
    try:
        if result is None or result.empty:
            return 0.0
        return float(result.memory_usage(deep=True).sum()) / (1024 * 1024)
    except Exception:
        return 0.0


def _infer_telemetry_section(section: str = "", ttl_key: str = "") -> str:
    """Infer a useful section label for older run_query() call sites."""
    if section:
        return str(section)

    key = str(ttl_key or "").lower()
    prefix_map = [
        ("account_health", "Account Health"),
        ("ah_", "Account Health"),
        ("cc_", "Cost Center"),
        ("uo_", "Usage Overview"),
        ("wh_", "Warehouse Health"),
        ("lm_", "Live Monitor"),
        ("qa_", "Query Analysis"),
        ("qs_", "Query Search & History"),
        ("dba_", "DBA Tools"),
        ("tm_", "Task Management"),
        ("sec_", "Security & Access"),
        ("sp_", "Stored Proc Tracker"),
        ("rec_", "Recommendations & Anomalies"),
        ("cortex_", "AI & Cortex Monitor"),
        ("storage_", "Storage Monitor"),
        ("pipe_", "Pipeline Health"),
        ("value_", "Snowflake Value"),
    ]
    for prefix, label in prefix_map:
        if key.startswith(prefix):
            return label

    nav_section = str(st.session_state.get("nav_section") or "").strip()
    return nav_section or "Unknown"


def _record_query_telemetry(
    query_text: str,
    ttl_key: str,
    tier: str,
    elapsed_ms: float,
    row_count: int,
    used_cache: bool,
    result_mb: float = 0.0,
    section: str = "",
) -> None:
    """Keep a lightweight in-session trace of OVERWATCH query volume."""
    try:
        query_hash = hashlib.sha1(str(query_text).encode("utf-8", errors="ignore")).hexdigest()[:12]
        active_section = _infer_telemetry_section(section, ttl_key)
        entries = st.session_state.setdefault("_overwatch_query_telemetry", [])
        entries.append({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "section": active_section,
            "ttl_key": ttl_key,
            "tier": tier,
            "cache_enabled": bool(used_cache),
            "elapsed_ms": round(float(elapsed_ms), 2),
            "rows": int(row_count or 0),
            "result_mb": round(float(result_mb or 0), 3),
            "query_hash": query_hash,
        })
        if len(entries) > 250:
            del entries[:-250]
        _warn_on_budget_pressure(active_section, query_hash, ttl_key, elapsed_ms, row_count, result_mb)
        try:
            from .logging import log_query_event

            log_query_event(
                section=active_section,
                query_hash=query_hash,
                cache_key=ttl_key,
                cache_tier=tier,
                elapsed_ms=elapsed_ms,
                row_count=row_count,
                result_mb=result_mb,
                used_cache=used_cache,
            )
        except Exception:
            pass
    except Exception:
        pass


def _warn_on_budget_pressure(
    section: str,
    query_hash: str,
    ttl_key: str,
    elapsed_ms: float,
    row_count: int,
    result_mb: float,
) -> None:
    """Warn once a section repeats expensive query patterns in a session."""
    is_expensive = (
        float(elapsed_ms or 0) >= QUERY_BUDGET_THRESHOLDS["slow_elapsed_ms"]
        or int(row_count or 0) >= QUERY_BUDGET_THRESHOLDS["large_rows"]
        or float(result_mb or 0) >= QUERY_BUDGET_THRESHOLDS["large_result_mb"]
    )
    if not is_expensive:
        return

    budget = st.session_state.setdefault("_overwatch_query_budget_hits", {})
    key = f"{section}|{ttl_key}|{query_hash}"
    budget[key] = int(budget.get(key, 0)) + 1
    if budget[key] < QUERY_BUDGET_THRESHOLDS["repeat_warning_count"]:
        return

    seen = st.session_state.setdefault("_overwatch_query_budget_warning_hashes", set())
    warning_key = f"{section}|{ttl_key}|{query_hash}"
    if warning_key in seen:
        return
    seen.add(warning_key)
    st.warning(
        "OVERWATCH budget guardrail: this section repeatedly ran a heavy query. "
        f"Section={section}; rows={int(row_count or 0):,}; "
        f"result={float(result_mb or 0):.1f} MB; elapsed={float(elapsed_ms or 0)/1000:.1f}s."
    )


def _show_query_warning(prefix: str, error: Exception) -> None:
    message = f"{prefix}: {format_snowflake_error(error)}"
    seen = st.session_state.setdefault("_overwatch_query_warning_hashes", set())
    warning_hash = hashlib.sha1(message.encode("utf-8", errors="ignore")).hexdigest()[:12]
    if warning_hash in seen:
        return
    seen.add(warning_hash)
    st.warning(message)


def format_snowflake_error(error: Exception, max_len: int = 320) -> str:
    """Return a short UI-safe Snowflake error message."""
    text = str(error or "").strip()
    if not text:
        return "Snowflake returned an empty error."

    lower = text.lower()
    if "requested information on the current user is not accessible in stored procedure" in lower:
        return (
            "Snowflake blocked this live metadata call in the Streamlit execution context. "
            "Use the ACCOUNT_USAGE fallback or a role/context that can query live metadata."
        )
    if "invalid identifier" in lower:
        match = re.search(r"invalid identifier ['\"]?([^'\"\n]+)['\"]?", text, flags=re.IGNORECASE)
        ident = match.group(1).strip() if match else "a column"
        return f"Snowflake does not expose {ident} in this account/view for the current role."
    if "does not exist or not authorized" in lower or "not authorized" in lower:
        return "The current role cannot access this Snowflake object or operation."
    if "insufficient privileges" in lower or "insufficient privilege" in lower:
        return "The current role does not have the required Snowflake privilege for this action."

    text = re.sub(r"^\(\d+\):\s*[0-9a-f-]+:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def get_query_telemetry() -> pd.DataFrame:
    """Return recent query-run telemetry for the current Streamlit session."""
    return pd.DataFrame(st.session_state.get("_overwatch_query_telemetry", []))


def get_query_budget_summary() -> pd.DataFrame:
    """Return per-section query budget telemetry for this Streamlit session."""
    df = get_query_telemetry()
    if df.empty:
        return df
    for col in ["elapsed_ms", "rows", "result_mb"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    grouped = (
        df.groupby("section", dropna=False)
        .agg(
            calls=("query_hash", "count"),
            unique_queries=("query_hash", "nunique"),
            elapsed_sec=("elapsed_ms", lambda s: round(float(s.sum()) / 1000, 2)),
            max_rows=("rows", "max"),
            max_result_mb=("result_mb", "max"),
        )
        .reset_index()
        .sort_values(["elapsed_sec", "calls"], ascending=False)
    )
    return grouped


def clear_query_telemetry() -> None:
    """Clear current session query telemetry."""
    st.session_state["_overwatch_query_telemetry"] = []
    st.session_state["_overwatch_query_budget_hits"] = {}
    st.session_state["_overwatch_query_budget_warning_hashes"] = set()
    st.session_state.pop("_overwatch_active_query_tag", None)


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

def _build_overwatch_query_tag(section: str, ttl_key: str, tier: str) -> str:
    """Build a compact query tag for section-level OVERWATCH cost attribution."""
    section_label = _infer_telemetry_section(section, ttl_key)
    section_label = re.sub(r"[^A-Za-z0-9 _&:/.-]+", "", str(section_label)).strip() or "Unknown"
    company = str(st.session_state.get("active_company", "ALFA") or "ALFA")
    return f"OVERWATCH:v3|{company[:24]}|{section_label[:80]}|{str(tier or 'recent')[:20]}"


def _apply_overwatch_query_tag(session, query_tag: str) -> None:
    """Set QUERY_TAG only when it changes; failures are non-fatal."""
    query_tag = str(query_tag or "OVERWATCH:v3")[:250]
    if st.session_state.get("_overwatch_active_query_tag") == query_tag:
        return
    try:
        session.sql(f"ALTER SESSION SET QUERY_TAG = {sql_literal(query_tag, 250)}").collect()
        st.session_state["_overwatch_active_query_tag"] = query_tag
    except Exception:
        pass


def _execute_snowflake_query(query_text: str, query_tag: str = "") -> pd.DataFrame:
    session = get_session()
    _apply_overwatch_query_tag(session, query_tag)
    return normalize_df(session.sql(query_text).to_pandas())


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
def _cached_live(query_text: str, cache_context: str = "", cache_salt: str = "", query_tag: str = "") -> pd.DataFrame:
    try:
        return _execute_snowflake_query(query_text, query_tag)
    except Exception as e:
        _show_query_warning("Live data unavailable", e)
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TIERS["recent"], show_spinner=False)
def _cached_recent(query_text: str, cache_context: str = "", cache_salt: str = "", query_tag: str = "") -> pd.DataFrame:
    try:
        return _execute_snowflake_query(query_text, query_tag)
    except Exception as e:
        _show_query_warning("Data unavailable", e)
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TIERS["historical"], show_spinner=False)
def _cached_historical(query_text: str, cache_context: str = "", cache_salt: str = "", query_tag: str = "") -> pd.DataFrame:
    try:
        return _execute_snowflake_query(query_text, query_tag)
    except Exception as e:
        _show_query_warning("Historical data unavailable", e)
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TIERS["metadata"], show_spinner=False)
def _cached_metadata(query_text: str, cache_context: str = "", cache_salt: str = "", query_tag: str = "") -> pd.DataFrame:
    try:
        return _execute_snowflake_query(query_text, query_tag)
    except Exception as e:
        _show_query_warning("Metadata unavailable", e)
        return pd.DataFrame()


# Backward-compatible 5-min cache — for callers that don't pass tier=
@st.cache_data(ttl=CACHE_TIERS["recent"], show_spinner=False)
def run_query_cached(query_text: str, cache_context: str = "", cache_salt: str = "", query_tag: str = "") -> pd.DataFrame:
    """Backward-compatible runner. Prefer run_query(tier=...) for new code."""
    try:
        return _execute_snowflake_query(query_text, query_tag)
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
    section: str = "",
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
            query_tag = _build_overwatch_query_tag(section, ttl_key, tier)
            if use_cache:
                cache_salt = st.session_state.get(f"_refresh_salt_{ttl_key}", "")
                context = _cache_context()
                fn   = _TIER_FN.get(tier, _cached_recent)
                return fn(query_text, context, cache_salt, query_tag)
            # Bypass cache — always wrapped in try/except
            try:
                return _execute_snowflake_query(query_text, query_tag)
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
    section: str = "",
) -> pd.DataFrame:
    """Execute a query through the cached runner and log lightweight telemetry."""
    started = time.perf_counter()
    result = _run_query_base(
        query_text=query_text,
        ttl_key=ttl_key,
        use_cache=use_cache,
        spinner_msg=spinner_msg,
        tier=tier,
        section=section,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    result_mb = _estimate_result_mb(result)
    _record_query_telemetry(query_text, ttl_key, tier, elapsed_ms, len(result), use_cache, result_mb, section)
    return result


def run_query_or_raise(
    query_text: str,
    section: str = "",
    ttl_key: str = "direct",
    tier: str = "live",
) -> pd.DataFrame:
    """
    Execute SQL and return a normalized DataFrame, preserving exceptions.

    Use this for live probes and primary/fallback query paths where callers need
    the original Snowflake exception to decide whether to run a fallback query.
    """
    started = time.perf_counter()
    result = pd.DataFrame()
    query_tag = _build_overwatch_query_tag(section, ttl_key, tier)
    try:
        session = get_session()
        _apply_overwatch_query_tag(session, query_tag)
        result = normalize_df(session.sql(query_text).to_pandas())
        return result
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000
        _record_query_telemetry(
            query_text,
            ttl_key=ttl_key,
            tier=tier,
            elapsed_ms=elapsed_ms,
            row_count=len(result),
            used_cache=False,
            result_mb=_estimate_result_mb(result),
            section=section,
        )


def force_refresh(key: str):
    """Bump cache salt to force re-execution of a specific section's queries."""
    st.session_state[f"_refresh_salt_{key}"] = datetime.now().isoformat()
