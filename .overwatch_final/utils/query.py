# utils/query.py - Tiered cached query execution + SQL safety
# Fixes vs previous version:
#   1. safe_sql(): added 2000-char hard cap (prompt injection prevention)
#   2. run_query_cached(): wrapped bare session.sql() in try/except
#      (was unguarded - any Snowflake error caused an unhandled exception
#      that crashed the entire section render with a red error page)
#   3. Tiered cache TTLs: live=30s, recent=300s, historical=1800s, metadata=14400s
#      (previous version had a single flat 300s TTL for all query types)
import hashlib
import os
import re
import threading
import time
import streamlit as st
import pandas as pd
from datetime import datetime
from .session import get_session
from .data import normalize_df

CACHE_TIERS: dict[str, int] = {
    "live":       30,     # INFORMATION_SCHEMA - real-time, 30s stale is fine
    "recent":     300,    # ACCOUNT_USAGE last 4h - 5-min cache
    "historical": 1800,   # ACCOUNT_USAGE 7d+ - 30-min cache
    "metadata":   14400,  # SHOW WAREHOUSES, SHOW TASKS, USERS - 4-hour cache
}

STANDARD_RESULT_WARNING_ROWS = 5_000
STANDARD_RESULT_WARNING_MB = 25.0
ADMIN_RESULT_HARD_ROWS = 25_000
ADMIN_RESULT_HARD_MB = 100.0
STANDARD_SQL_READ_LIMIT_ROWS = STANDARD_RESULT_WARNING_ROWS
ADMIN_SQL_READ_LIMIT_ROWS = ADMIN_RESULT_HARD_ROWS

_QUERY_CACHE_LOCKS: dict[str, threading.Lock] = {}
_QUERY_CACHE_LOCKS_GUARD = threading.Lock()

_RESULT_SIZE_DEEP_ROW_LIMIT = 5_000
_RESULT_SIZE_SAMPLE_ROWS = 1_000

QUERY_BUDGET_THRESHOLDS = {
    "slow_elapsed_ms": 10_000,
    "large_rows": 25_000,
    "large_result_mb": 25.0,
    "repeat_warning_count": 3,
}


def _perf_run_id() -> str:
    """Optional run id used by external release validation."""
    try:
        value = st.session_state.get("_overwatch_perf_run_id", "")
    except Exception:
        value = ""
    value = value or os.environ.get("OVERWATCH_PERF_RUN_ID", "")
    return re.sub(r"[^A-Za-z0-9_.:-]+", "", str(value or ""))[:80]


def _estimate_result_mb(result: pd.DataFrame) -> float:
    """Estimate result-set memory size for budget telemetry."""
    try:
        if result is None or result.empty:
            return 0.0
        row_count = len(result)
        if row_count <= _RESULT_SIZE_DEEP_ROW_LIMIT:
            return float(result.memory_usage(deep=True).sum()) / (1024 * 1024)

        object_cols = list(result.select_dtypes(include=["object", "string"]).columns)
        if not object_cols:
            return float(result.memory_usage(deep=False).sum()) / (1024 * 1024)

        non_object_cols = [col for col in result.columns if col not in object_cols]
        non_object_bytes = (
            result[non_object_cols].memory_usage(index=False, deep=False).sum()
            if non_object_cols else 0
        )
        sample_rows = min(_RESULT_SIZE_SAMPLE_ROWS, row_count)
        object_sample_bytes = result[object_cols].head(sample_rows).memory_usage(index=False, deep=True).sum()
        estimated_object_bytes = (float(object_sample_bytes) / max(sample_rows, 1)) * row_count
        index_bytes = result.index.memory_usage(deep=False)
        return float(non_object_bytes + estimated_object_bytes + index_bytes) / (1024 * 1024)
    except Exception:
        return 0.0


def _admin_actions_enabled() -> bool:
    """Return whether the admin gate is open without introducing an import cycle."""
    try:
        from .admin import admin_actions_enabled

        return bool(admin_actions_enabled())
    except Exception:
        return False


def _query_is_metadata_probe(query_text: str) -> bool:
    """Return True for safe metadata probes that should not be size-guarded."""
    sql = str(query_text or "").strip().upper()
    if not sql:
        return False
    if sql.startswith("SHOW ") or sql.startswith("DESC ") or sql.startswith("DESCRIBE "):
        return True
    return "LIMIT 0" in sql


def _query_starts_with_read(sql: str) -> bool:
    """Return True for plain read statements that can safely accept LIMIT."""
    text = str(sql or "")
    idx = 0
    length = len(text)
    while idx < length:
        while idx < length and text[idx].isspace():
            idx += 1
        if text.startswith("--", idx):
            idx += 2
            while idx < length and text[idx] not in "\r\n":
                idx += 1
            continue
        if text.startswith("/*", idx):
            end = text.find("*/", idx + 2)
            if end < 0:
                return False
            idx = end + 2
            continue
        break

    for keyword in ("SELECT", "WITH"):
        end = idx + len(keyword)
        if text[idx:end].upper() == keyword:
            if end >= length or not (text[end].isalnum() or text[end] == "_"):
                return True
    return False


def _has_extra_statement_separator(sql: str) -> bool:
    """Return True when a statement has semicolons beyond an optional terminator."""
    text = str(sql or "").strip()
    if text.endswith(";"):
        text = text[:-1]
    return ";" in text


def _strip_sql_literals(sql: str) -> str:
    """Mask single-quoted literals before lightweight keyword checks."""
    return re.sub(r"'(?:''|[^'])*'", "''", str(sql or ""), flags=re.DOTALL)


def _query_already_has_limit(sql: str) -> bool:
    """Return True when the SQL text already contains an explicit LIMIT clause."""
    return bool(re.search(r"\bLIMIT\s+\d+\b", _strip_sql_literals(sql), flags=re.IGNORECASE))


def _default_sql_read_limit() -> int:
    """Return the SQL-side row cap for the current operator mode."""
    return ADMIN_SQL_READ_LIMIT_ROWS if _admin_actions_enabled() else STANDARD_SQL_READ_LIMIT_ROWS


def _inject_read_limit(query_text: str, max_rows: int | None = None) -> str:
    """Append a conservative LIMIT to unbounded read SQL before execution."""
    sql = str(query_text or "")
    if not sql.strip():
        return sql
    if _query_is_metadata_probe(sql):
        return sql
    if not _query_starts_with_read(sql):
        return sql
    if _has_extra_statement_separator(sql):
        return sql
    if _query_already_has_limit(sql):
        return sql

    try:
        row_cap = int(max_rows or _default_sql_read_limit())
    except Exception:
        row_cap = STANDARD_SQL_READ_LIMIT_ROWS
    if row_cap <= 0:
        return sql

    return f"{sql.rstrip().rstrip(';')}\nLIMIT {row_cap}"


def _is_expensive_query(elapsed_ms: float, row_count: int, result_mb: float) -> bool:
    return (
        float(elapsed_ms or 0) >= QUERY_BUDGET_THRESHOLDS["slow_elapsed_ms"]
        or int(row_count or 0) >= QUERY_BUDGET_THRESHOLDS["large_rows"]
        or float(result_mb or 0) >= QUERY_BUDGET_THRESHOLDS["large_result_mb"]
    )


def _budget_risk_label(
    calls: int,
    elapsed_sec: float,
    max_rows: int,
    max_result_mb: float,
    expensive_calls: int,
) -> str:
    if (
        int(expensive_calls or 0) >= QUERY_BUDGET_THRESHOLDS["repeat_warning_count"]
        or float(elapsed_sec or 0) >= 60
        or float(max_result_mb or 0) >= QUERY_BUDGET_THRESHOLDS["large_result_mb"] * 4
    ):
        return "High"
    if (
        int(expensive_calls or 0) > 0
        or float(elapsed_sec or 0) >= 20
        or int(max_rows or 0) >= QUERY_BUDGET_THRESHOLDS["large_rows"]
        or int(calls or 0) >= 25
    ):
        return "Watch"
    return "Normal"


def _infer_telemetry_section(section: str = "", ttl_key: str = "") -> str:
    """Infer a useful section label for older run_query() call sites."""
    if section:
        return str(section)

    key = str(ttl_key or "").lower()
    prefix_map = [
        ("account_health", "Account Health"),
        ("ah_", "Account Health"),
        ("cc_", "Cost & Contract"),
        ("uo_", "DBA Control Room"),
        ("wh_", "Warehouse Health"),
        ("lm_", "Workload Operations"),
        ("qa_", "Workload Operations"),
        ("qs_", "Workload Operations"),
        ("dba_control_room_", "DBA Control Room"),
        ("dba_", "Change & Drift"),
        ("tm_", "Workload Operations"),
        ("sec_", "Security Posture"),
        ("sp_", "Change & Drift"),
        ("rec_", "Cost & Contract"),
        ("cortex_", "Cost & Contract"),
        ("storage_", "Cost & Contract"),
        ("pipe_", "Workload Operations"),
        ("value_", "Cost & Contract"),
        ("arch_", "Architecture Readiness"),
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
            "perf_run_id": _perf_run_id(),
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
        if st.session_state.get("_query_logging_enabled", False):
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
    is_expensive = _is_expensive_query(elapsed_ms, row_count, result_mb)
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


def _show_result_guard_message(message: str, level: str = "warning") -> None:
    """Show a de-duplicated result-size guardrail message."""
    normalized_level = "error" if str(level or "").lower() == "error" else "warning"
    seen = st.session_state.setdefault("_overwatch_result_guard_warning_hashes", set())
    warning_hash = hashlib.sha1(f"{normalized_level}|{message}".encode("utf-8", errors="ignore")).hexdigest()[:12]
    if warning_hash in seen:
        return
    seen.add(warning_hash)
    if normalized_level == "error":
        st.error(message)
    else:
        st.warning(message)


def _apply_result_guard(
    query_text: str,
    result: pd.DataFrame,
    ttl_key: str = "",
    section: str = "",
    tier: str = "recent",
) -> pd.DataFrame:
    """Warn or clamp overly large query results before callers consume them."""
    if result is None:
        return pd.DataFrame()
    if not isinstance(result, pd.DataFrame) or result.empty:
        return result if isinstance(result, pd.DataFrame) else pd.DataFrame()
    if _query_is_metadata_probe(query_text):
        return result

    row_count = len(result)
    result_mb = _estimate_result_mb(result)
    active_section = _infer_telemetry_section(section, ttl_key)
    admin_mode = _admin_actions_enabled()

    if admin_mode:
        if row_count > ADMIN_RESULT_HARD_ROWS or result_mb > ADMIN_RESULT_HARD_MB:
            _show_result_guard_message(
                (
                    "OVERWATCH admin result guard: "
                    f"{active_section} query returned {row_count:,} rows / {result_mb:.1f} MB; "
                    f"ceiling is {ADMIN_RESULT_HARD_ROWS:,} rows or {ADMIN_RESULT_HARD_MB:.0f} MB. "
                    "Refine the filters before loading this result."
                ),
                level="error",
            )
            return pd.DataFrame()
    elif row_count > STANDARD_RESULT_WARNING_ROWS or result_mb > STANDARD_RESULT_WARNING_MB:
        _show_result_guard_message(
            (
                "OVERWATCH result guard: "
                f"{active_section} query returned {row_count:,} rows / {result_mb:.1f} MB; "
                f"standard dashboard guardrail is {STANDARD_RESULT_WARNING_ROWS:,} rows or {STANDARD_RESULT_WARNING_MB:.0f} MB. "
                "Tighten filters before rerunning."
            ),
            level="warning",
        )

    return result


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
    df["expensive_call"] = df.apply(
        lambda row: _is_expensive_query(row["elapsed_ms"], row["rows"], row["result_mb"]),
        axis=1,
    )
    grouped = (
        df.groupby("section", dropna=False)
        .agg(
            calls=("query_hash", "count"),
            unique_queries=("query_hash", "nunique"),
            expensive_calls=("expensive_call", "sum"),
            elapsed_sec=("elapsed_ms", lambda s: round(float(s.sum()) / 1000, 2)),
            max_rows=("rows", "max"),
            max_result_mb=("result_mb", "max"),
        )
        .reset_index()
        .sort_values(["elapsed_sec", "calls"], ascending=False)
    )
    grouped["budget_risk"] = grouped.apply(
        lambda row: _budget_risk_label(
            row["calls"],
            row["elapsed_sec"],
            row["max_rows"],
            row["max_result_mb"],
            row["expensive_calls"],
        ),
        axis=1,
    )
    ordered_cols = [
        "section",
        "budget_risk",
        "calls",
        "unique_queries",
        "expensive_calls",
        "elapsed_sec",
        "max_rows",
        "max_result_mb",
    ]
    grouped = grouped[ordered_cols]
    return grouped


def clear_query_telemetry() -> None:
    """Clear current session query telemetry."""
    st.session_state["_overwatch_query_telemetry"] = []
    st.session_state["_overwatch_query_budget_hits"] = {}
    st.session_state["_overwatch_query_budget_warning_hashes"] = set()
    st.session_state["_overwatch_result_guard_warning_hashes"] = set()
    st.session_state.pop("_overwatch_active_query_tag", None)


def safe_sql(value: str) -> str:
    """
    Sanitize user input before embedding in SQL or Cortex prompts.
    - Strips SQL comment injection tokens (--, /* */, ;)
    - Escapes single quotes (value is embedded inside a SQL string literal)
    - Hard cap at 2000 chars - prevents prompt injection via oversized input
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
    ident_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,254}$")
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


# Per-tier cache functions
# Each tier must be a separate decorated function because @st.cache_data TTL
# is fixed at decoration time - it cannot be passed as a runtime argument.

def _build_overwatch_query_tag(section: str, ttl_key: str, tier: str) -> str:
    """Build a compact query tag for section-level OVERWATCH cost attribution."""
    if not st.session_state.get("_detailed_query_tags_enabled", False):
        return "OVERWATCH"
    section_label = _infer_telemetry_section(section, ttl_key)
    section_label = re.sub(r"[^A-Za-z0-9 _&:/.-]+", "", str(section_label)).strip() or "Unknown"
    company = str(st.session_state.get("active_company", "ALFA") or "ALFA")
    perf = _perf_run_id()
    tag = f"OVERWATCH|{company[:24]}|{section_label[:80]}|{str(tier or 'recent')[:20]}"
    if perf:
        tag = f"{tag}|PERF:{perf[:48]}"
    return tag[:250]


def _apply_overwatch_query_tag(session, query_tag: str) -> None:
    """Set QUERY_TAG only when it changes; failures are non-fatal."""
    query_tag = str(query_tag or "OVERWATCH")[:250]
    if st.session_state.get("_overwatch_active_query_tag") == query_tag:
        return
    try:
        session.sql(f"ALTER SESSION SET QUERY_TAG = {sql_literal(query_tag, 250)}").collect()
        st.session_state["_overwatch_active_query_tag"] = query_tag
    except Exception:
        pass


def _execute_snowflake_query(
    query_text: str,
    query_tag: str = "",
    ttl_key: str = "",
    tier: str = "recent",
    section: str = "",
) -> pd.DataFrame:
    executable_query = _inject_read_limit(query_text)
    session = get_session()
    _apply_overwatch_query_tag(session, query_tag)
    result = normalize_df(session.sql(executable_query).to_pandas())
    return _apply_result_guard(executable_query, result, ttl_key=ttl_key, section=section, tier=tier)


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
        str(st.session_state.get("global_environment", "")),
        str(st.session_state.get("_overwatch_current_role", "")),
    ])


def _cache_salt(ttl_key: str) -> str:
    """Return cache salt for global refresh plus a specific query namespace."""
    global_salt = st.session_state.get("_refresh_salt_global", "")
    scoped_salt = st.session_state.get(f"_refresh_salt_{ttl_key}", "")
    return f"{global_salt}|{scoped_salt}"


def _get_query_cache_lock(query_text: str, cache_context: str, cache_salt: str, tier: str) -> threading.Lock:
    """Return a process-wide lock for identical in-flight cached queries."""
    key_basis = "\n".join([str(tier or ""), str(cache_context or ""), str(cache_salt or ""), str(query_text or "")])
    key = hashlib.sha1(key_basis.encode("utf-8", errors="ignore")).hexdigest()
    with _QUERY_CACHE_LOCKS_GUARD:
        lock = _QUERY_CACHE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _QUERY_CACHE_LOCKS[key] = lock
        return lock


@st.cache_data(ttl=CACHE_TIERS["live"], show_spinner=False)
def _cached_live(
    query_text: str,
    cache_context: str = "",
    cache_salt: str = "",
    _query_tag: str = "",
    _ttl_key: str = "",
    _section: str = "",
) -> pd.DataFrame:
    try:
        return _execute_snowflake_query(query_text, _query_tag, ttl_key=_ttl_key, tier="live", section=_section)
    except Exception as e:
        _show_query_warning("Live data unavailable", e)
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TIERS["recent"], show_spinner=False)
def _cached_recent(
    query_text: str,
    cache_context: str = "",
    cache_salt: str = "",
    _query_tag: str = "",
    _ttl_key: str = "",
    _section: str = "",
) -> pd.DataFrame:
    try:
        return _execute_snowflake_query(query_text, _query_tag, ttl_key=_ttl_key, tier="recent", section=_section)
    except Exception as e:
        _show_query_warning("Data unavailable", e)
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TIERS["historical"], show_spinner=False)
def _cached_historical(
    query_text: str,
    cache_context: str = "",
    cache_salt: str = "",
    _query_tag: str = "",
    _ttl_key: str = "",
    _section: str = "",
) -> pd.DataFrame:
    try:
        return _execute_snowflake_query(query_text, _query_tag, ttl_key=_ttl_key, tier="historical", section=_section)
    except Exception as e:
        _show_query_warning("Historical data unavailable", e)
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TIERS["metadata"], show_spinner=False)
def _cached_metadata(
    query_text: str,
    cache_context: str = "",
    cache_salt: str = "",
    _query_tag: str = "",
    _ttl_key: str = "",
    _section: str = "",
) -> pd.DataFrame:
    try:
        return _execute_snowflake_query(query_text, _query_tag, ttl_key=_ttl_key, tier="metadata", section=_section)
    except Exception as e:
        _show_query_warning("Metadata unavailable", e)
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TIERS["live"], show_spinner=False)
def _cached_raise_live(
    query_text: str,
    cache_context: str = "",
    cache_salt: str = "",
    _query_tag: str = "",
    _ttl_key: str = "",
    _section: str = "",
) -> pd.DataFrame:
    return _execute_snowflake_query(query_text, _query_tag, ttl_key=_ttl_key, tier="live", section=_section)


@st.cache_data(ttl=CACHE_TIERS["recent"], show_spinner=False)
def _cached_raise_recent(
    query_text: str,
    cache_context: str = "",
    cache_salt: str = "",
    _query_tag: str = "",
    _ttl_key: str = "",
    _section: str = "",
) -> pd.DataFrame:
    return _execute_snowflake_query(query_text, _query_tag, ttl_key=_ttl_key, tier="recent", section=_section)


@st.cache_data(ttl=CACHE_TIERS["historical"], show_spinner=False)
def _cached_raise_historical(
    query_text: str,
    cache_context: str = "",
    cache_salt: str = "",
    _query_tag: str = "",
    _ttl_key: str = "",
    _section: str = "",
) -> pd.DataFrame:
    return _execute_snowflake_query(query_text, _query_tag, ttl_key=_ttl_key, tier="historical", section=_section)


@st.cache_data(ttl=CACHE_TIERS["metadata"], show_spinner=False)
def _cached_raise_metadata(
    query_text: str,
    cache_context: str = "",
    cache_salt: str = "",
    _query_tag: str = "",
    _ttl_key: str = "",
    _section: str = "",
) -> pd.DataFrame:
    return _execute_snowflake_query(query_text, _query_tag, ttl_key=_ttl_key, tier="metadata", section=_section)


# Backward-compatible 5-min cache - for callers that don't pass tier=
@st.cache_data(ttl=CACHE_TIERS["recent"], show_spinner=False)
def run_query_cached(
    query_text: str,
    cache_context: str = "",
    cache_salt: str = "",
    _query_tag: str = "",
    _ttl_key: str = "",
    _section: str = "",
) -> pd.DataFrame:
    """Backward-compatible runner. Prefer run_query(tier=...) for new code."""
    try:
        return _execute_snowflake_query(query_text, _query_tag, ttl_key=_ttl_key, tier="recent", section=_section)
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


_RAISE_TIER_FN = {
    "live":       _cached_raise_live,
    "standard":   _cached_raise_historical,
    "recent":     _cached_raise_recent,
    "historical": _cached_raise_historical,
    "metadata":   _cached_raise_metadata,
}


def _run_query_base(
    query_text: str,
    ttl_key: str = "default",
    use_cache: bool = True,
    spinner_msg: str = "Loading data...",
    tier: str = "recent",
    section: str = "",
    max_rows: int | None = None,
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
        max_rows:    Optional SQL-side read cap for unbounded SELECT/WITH queries.

    Returns:
        Normalized DataFrame. Empty DataFrame on any error (never raises).
    """
    with st.spinner(spinner_msg):
        try:
            executable_query = _inject_read_limit(query_text, max_rows=max_rows)
            query_tag = _build_overwatch_query_tag(section, ttl_key, tier)
            if use_cache:
                cache_salt = _cache_salt(ttl_key)
                context = _cache_context()
                fn   = _TIER_FN.get(tier, _cached_recent)
                with _get_query_cache_lock(executable_query, context, cache_salt, tier):
                    return fn(executable_query, context, cache_salt, query_tag, ttl_key, section)
            # Bypass cache - always wrapped in try/except
            try:
                return _execute_snowflake_query(executable_query, query_tag, ttl_key=ttl_key, tier=tier, section=section)
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
    max_rows: int | None = None,
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
        max_rows=max_rows,
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
    max_rows: int | None = None,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    Execute SQL and return a normalized DataFrame, preserving exceptions.

    Use this for live probes and primary/fallback query paths where callers need
    the original Snowflake exception to decide whether to run a fallback query.
    """
    started = time.perf_counter()
    result = pd.DataFrame()
    query_tag = _build_overwatch_query_tag(section, ttl_key, tier)
    executable_query = _inject_read_limit(query_text, max_rows=max_rows)
    try:
        if use_cache:
            cache_salt = _cache_salt(ttl_key)
            context = _cache_context()
            fn = _RAISE_TIER_FN.get(tier, _cached_raise_recent)
            with _get_query_cache_lock(executable_query, context, cache_salt, tier):
                result = fn(executable_query, context, cache_salt, query_tag, ttl_key, section)
                return result
        session = get_session()
        _apply_overwatch_query_tag(session, query_tag)
        result = normalize_df(session.sql(executable_query).to_pandas())
        return _apply_result_guard(executable_query, result, ttl_key=ttl_key, section=section, tier=tier)
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000
        _record_query_telemetry(
            query_text,
            ttl_key=ttl_key,
            tier=tier,
            elapsed_ms=elapsed_ms,
            row_count=len(result),
            used_cache=use_cache,
            result_mb=_estimate_result_mb(result),
            section=section,
        )


def force_refresh(key: str):
    """Bump cache salt to force re-execution of a specific section's queries."""
    st.session_state[f"_refresh_salt_{key}"] = datetime.now().isoformat()
