# utils/query.py - Tiered cached query execution + SQL safety
# Fixes vs previous version:
#   1. safe_sql(): added 2000-char hard cap (prompt injection prevention)
#   2. run_query_cached(): wrapped bare session.sql() in try/except
#      (was unguarded - any Snowflake error caused an unhandled exception
#      that crashed the entire section render with a red error page)
#   3. Tiered cache TTLs: live=30s, standard=300s, historical=3600s, metadata=14400s
#      (previous version had a single flat 300s TTL for all query types)
import hashlib
import os
import re
import time
import streamlit as st
import pandas as pd
from datetime import datetime
from runtime_state import (
    ACTIVE_COMPANY,
    ACTIVE_QUERY_TAG,
    CURRENT_ROLE,
    GLOBAL_DATABASE,
    GLOBAL_END_DATE,
    GLOBAL_ENVIRONMENT,
    GLOBAL_ROLE,
    GLOBAL_START_DATE,
    GLOBAL_USER,
    GLOBAL_WAREHOUSE,
    NAV_SECTION,
    PERF_RUN_ID,
    QUERY_BUDGET_HITS,
    QUERY_BUDGET_WARNING_HASHES,
    QUERY_BUDGET_WINDOW_COUNT,
    QUERY_BUDGET_WINDOW_STARTED_AT,
    QUERY_BUDGET_WINDOW_WARNED,
    QUERY_LOGGING_ENABLED,
    QUERY_TELEMETRY,
    QUERY_WARNING_HASHES,
    REFRESH_SALT_GLOBAL,
    REFRESH_SALT_PREFIX,
    RESULT_GUARD_WARNING_HASHES,
    STATEMENT_TIMEOUT_SECONDS,
    ensure_default_state,
    get_state,
    pop_state,
    set_state,
)
from .session import apply_overwatch_query_tag, build_overwatch_query_tag, get_session
from .data import normalize_df
from .idle import empty_paused_result, queries_paused
from .sql_safe import sql_literal
from performance import (
    assert_first_paint_query_allowed,
    begin_direct_sql_allowance,
    current_first_paint_render_id,
    end_direct_sql_allowance,
    increment_snowflake_execution_counter,
    is_first_paint_active,
    record_query_lint_finding,
    record_ui_query_event,
)
from query_contracts import lint_query_text, query_fingerprint, resolve_query_contract

CACHE_TIERS: dict[str, int] = {
    "live":       30,     # INFORMATION_SCHEMA - real-time, 30s stale is fine
    "command_summary": 300,  # Primary-section command briefs - compact mart packet, 5-min cache
    "standard":   300,    # App marts and ordinary section reads - 5-min cache
    "recent":     300,    # ACCOUNT_USAGE last 4h - 5-min cache
    "historical": 3600,   # ACCOUNT_USAGE 7d+ - 60-min cache
    "metadata":   14400,  # SHOW WAREHOUSES, SHOW TASKS, USERS - 4-hour cache
}

STATEMENT_TIMEOUTS_SECONDS: dict[str, int] = {
    "live": 30,
    "command_summary": 30,
    "metadata": 30,
    "standard": 60,
    "recent": 120,
    "historical": 180,
    "admin": 840,
}

STANDARD_RESULT_WARNING_ROWS = 5_000
STANDARD_RESULT_WARNING_MB = 25.0
ADMIN_RESULT_HARD_ROWS = 25_000
ADMIN_RESULT_HARD_MB = 100.0
STANDARD_SQL_READ_LIMIT_ROWS = STANDARD_RESULT_WARNING_ROWS
ADMIN_SQL_READ_LIMIT_ROWS = ADMIN_RESULT_HARD_ROWS

_RESULT_SIZE_DEEP_ROW_LIMIT = 5_000
_RESULT_SIZE_SAMPLE_ROWS = 1_000

QUERY_BUDGET_THRESHOLDS = {
    "slow_elapsed_ms": 10_000,
    "large_rows": 25_000,
    "large_result_mb": 25.0,
    "repeat_warning_count": 3,
    "max_queries_per_render": 18,
}


def _perf_run_id() -> str:
    """Optional run id used by external release validation."""
    try:
        value = get_state(PERF_RUN_ID, "")
    except Exception:
        value = ""
    value = value or os.environ.get("OVERWATCH_PERF_RUN_ID", "")
    return re.sub(r"[^A-Za-z0-9_.:-]+", "", str(value or ""))[:80]


def _estimate_result_mb(result: pd.DataFrame) -> float:
    """Estimate result-set memory size for query-load telemetry."""
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
        ("account_health", "DBA Control Room"),
        ("ah_", "DBA Control Room"),
        ("cc_", "Cost & Contract"),
        ("uo_", "DBA Control Room"),
        ("wh_", "Cost & Contract"),
        ("lm_", "Workload Operations"),
        ("qa_", "Workload Operations"),
        ("qs_", "Workload Operations"),
        ("dba_control_room_", "DBA Control Room"),
        ("dba_", "Security Monitoring"),
        ("tm_", "Workload Operations"),
        ("sec_", "Security Monitoring"),
        ("sp_", "Security Monitoring"),
        ("rec_", "Cost & Contract"),
        ("cortex_", "Cost & Contract"),
        ("storage_", "Cost & Contract"),
        ("pipe_", "Workload Operations"),
        ("value_", "Cost & Contract"),
        ("arch_", "Security Monitoring"),
    ]
    for prefix, label in prefix_map:
        if key.startswith(prefix):
            return label

    nav_section = str(get_state(NAV_SECTION) or "").strip()
    return nav_section or "Unknown"


def _infer_query_boundary(query_text: str = "", ttl_key: str = "", tier: str = "") -> str:
    """Classify query purpose for first-paint budgets without storing SQL."""
    sql = str(query_text or "").upper()
    key = str(ttl_key or "").lower()
    tier_text = str(tier or "").lower()
    if key.startswith("query_search_"):
        return "query_search"
    if key.startswith("query_text_preview_"):
        return "query_preview"
    if key.startswith("section_command_packet_") or "MART_SECTION_DECISION_CURRENT" in sql:
        return "decision_packet"
    if "OVERWATCH_DECISION_SETUP_HEALTH" in sql or "setup_health" in key:
        return "setup_health"
    if "SNOWFLAKE.ACCOUNT_USAGE" in sql:
        return "account_usage"
    if tier_text == "metadata" or _query_is_metadata_probe(sql):
        return "metadata"
    if any(token in key for token in ("evidence", "proof", "detail", "history", "splash", "cockpit")):
        return "evidence"
    return "other"


_TARGET_METADATA_COLUMNS = (
    "QUERY_ID", "QUERY_HASH", "QUERY_SIGNATURE",
    "ALERT_ID", "ALERT_KEY", "EVENT_ID", "ACTION_ID",
    "WAREHOUSE_NAME", "USER_NAME", "LOGIN_NAME", "ROLE_NAME",
    "GRANTEE_NAME", "GRANT_ID", "DATABASE_NAME", "SHARE_NAME",
    "OBJECT_NAME", "TASK_NAME", "ROOT_TASK_NAME", "PROCEDURE_NAME",
    "SERVICE_CATEGORY", "SERVICE_TYPE", "DEPARTMENT", "APPLICATION",
)


def _target_metadata_from_sql(query_text: str, boundary: str) -> dict[str, object]:
    """Extract SQL-free target predicate metadata for telemetry artifacts."""
    if str(boundary or "") not in {"evidence", "query_search"}:
        return {
            "target_predicate_marker_present": None,
            "target_columns_used": [],
            "target_fallback_used": None,
        }
    masked = re.sub(r"'(?:''|[^'])*'", "''", str(query_text or ""), flags=re.DOTALL)
    upper = masked.upper()
    marker_present = "OVERWATCH_TARGET_PREDICATE" in upper
    limit_match = re.search(r"\bLIMIT\s+\d+\b", upper)
    limit_pos = limit_match.start() if limit_match else len(upper)
    marker_pos = upper.find("OVERWATCH_TARGET_PREDICATE")
    predicate_region = upper[marker_pos:limit_pos] if marker_pos >= 0 else upper[:limit_pos]
    return {
        "target_predicate_marker_present": bool(marker_present),
        "target_columns_used": [
            column for column in _TARGET_METADATA_COLUMNS
            if re.search(rf"\b{re.escape(column)}\b", predicate_region)
        ],
        "target_fallback_used": bool(" ILIKE " in predicate_region) if marker_present else None,
    }


_CRITICAL_TTL_BOUNDARIES: tuple[tuple[str, str], ...] = (
    (r"^section_command_packet_", "decision_packet"),
    (r"^query_search_recent_detail_", "query_search"),
    (r"^query_search_related_", "query_search"),
    (r"^query_text_preview_", "query_preview"),
    (r"^query_search_account_usage_", "account_usage"),
    (r"setup_health|decision_setup_health", "setup_health"),
    (r"cost_targeted_evidence|cost_bounded_evidence|cc_targeted_evidence", "evidence"),
    (r"alert_.*(evidence|history|delivery|action)", "evidence"),
    (r"dba_.*(evidence|proof|failed)|dba_control_room_.*", "evidence"),
    (r"workload_.*(evidence|pipeline)|query_search_recent_detail", "query_search"),
    (r"security_.*(evidence|proof)", "evidence"),
)


def _critical_boundary_for_ttl(ttl_key: str) -> str:
    key = str(ttl_key or "")
    for pattern, boundary in _CRITICAL_TTL_BOUNDARIES:
        if re.search(pattern, key, flags=re.IGNORECASE):
            return boundary
    return ""


def _enforce_explicit_critical_boundary(
    *,
    query_boundary: str | None,
    resolved_boundary: str,
    section: str,
    ttl_key: str,
    tier: str,
) -> object:
    required = _critical_boundary_for_ttl(ttl_key)
    if not required:
        return
    if query_boundary and str(query_boundary) == required:
        return
    message = (
        "Critical Decision Workspace query loaders must pass an explicit "
        f"{required} boundary."
    )
    record_query_lint_finding(
        fingerprint="",
        code="MISSING_EXPLICIT_BOUNDARY",
        severity="error",
        message=message,
        boundary=resolved_boundary,
        section=section,
        ttl_key=ttl_key,
        tier=tier,
    )
    if _strict_query_contract_mode():
        raise AssertionError(message)


def _first_paint_sensitive_boundary(boundary: str) -> bool:
    return str(boundary or "") in {
        "decision_packet",
        "evidence",
        "query_search",
        "query_preview",
        "metadata",
        "account_usage",
        "setup_health",
        "admin",
    }


def _strict_query_contract_mode() -> bool:
    return any(
        str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}
        for name in ("OVERWATCH_TEST_MODE", "OVERWATCH_UI_FIXTURE_MODE", "OVERWATCH_ALLOW_FIXTURE_MODE")
    )


def _enforce_query_contract(
    query_text: str,
    *,
    boundary: str,
    section: str,
    ttl_key: str,
    tier: str,
    max_rows: int | None,
) -> object:
    """Lint and optionally block query shapes before Snowflake execution."""
    contract = resolve_query_contract(boundary=boundary, section=section, ttl_key=ttl_key, tier=tier)
    findings = list(lint_query_text(query_text, contract))
    if contract.max_rows is not None and boundary in {
        "decision_packet",
        "evidence",
        "query_search",
        "query_preview",
        "account_usage",
    }:
        if max_rows is None or int(max_rows) > int(contract.max_rows):
            from query_contracts import QueryLintFinding

            findings.append(QueryLintFinding(
                code="MAX_ROWS_CONTRACT",
                severity="error",
                message=f"Query boundary {boundary} must request max_rows <= {int(contract.max_rows)}.",
                boundary=boundary,
                section=section,
            ))
    fingerprint = query_fingerprint(query_text)
    for finding in findings:
        record_query_lint_finding(
            fingerprint=fingerprint,
            code=finding.code,
            severity=finding.severity,
            message=finding.message,
            boundary=boundary,
            section=section,
            ttl_key=ttl_key,
            tier=tier,
            contract_id=str(getattr(contract, "contract_id", "") or ""),
        )
    if _strict_query_contract_mode():
        errors = [finding for finding in findings if str(finding.severity).lower() == "error"]
        if errors:
            raise AssertionError(errors[0].message)
    return contract


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
        active_section = _infer_telemetry_section(section, ttl_key)
        query_hash = f"{str(ttl_key or 'default')}|{active_section}|{str(tier or 'unknown')}"[:64]
        entries = ensure_default_state(QUERY_TELEMETRY, [])
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
        if get_state(QUERY_LOGGING_ENABLED, False):
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

    budget = ensure_default_state(QUERY_BUDGET_HITS, {})
    key = f"{section}|{ttl_key}|{query_hash}"
    budget[key] = int(budget.get(key, 0)) + 1
    if budget[key] < QUERY_BUDGET_THRESHOLDS["repeat_warning_count"]:
        return

    seen = ensure_default_state(QUERY_BUDGET_WARNING_HASHES, set())
    warning_key = f"{section}|{ttl_key}|{query_hash}"
    if warning_key in seen:
        return
    seen.add(warning_key)
    st.warning(
        "OVERWATCH query-load guardrail: this section repeatedly ran a heavy query. "
        f"Section={section}; rows={int(row_count or 0):,}; "
        f"result={float(result_mb or 0):.1f} MB; elapsed={float(elapsed_ms or 0)/1000:.1f}s."
    )


def _show_query_warning(prefix: str, error: Exception) -> None:
    message = f"{prefix}: {format_snowflake_error(error)}"
    seen = ensure_default_state(QUERY_WARNING_HASHES, set())
    warning_hash = hashlib.sha1(message.encode("utf-8", errors="ignore")).hexdigest()[:12]
    if warning_hash in seen:
        return
    seen.add(warning_hash)
    st.warning(message)


def _show_result_guard_message(message: str, level: str = "warning") -> None:
    """Show a de-duplicated result-size guardrail message."""
    normalized_level = "error" if str(level or "").lower() == "error" else "warning"
    seen = ensure_default_state(RESULT_GUARD_WARNING_HASHES, set())
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
    return pd.DataFrame(get_state(QUERY_TELEMETRY, []))


def get_query_budget_summary() -> pd.DataFrame:
    """Return per-section query-load telemetry for this Streamlit session."""
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
    set_state(QUERY_TELEMETRY, [])
    set_state(QUERY_BUDGET_HITS, {})
    set_state(QUERY_BUDGET_WARNING_HASHES, set())
    set_state(RESULT_GUARD_WARNING_HASHES, set())
    pop_state(ACTIVE_QUERY_TAG, None)


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
    return build_overwatch_query_tag(
        section=_infer_telemetry_section(section, ttl_key),
        ttl_key=ttl_key,
        tier=tier,
    )


def _apply_overwatch_query_tag(session, query_tag: str) -> None:
    """Record local query attribution without mutating Snowflake session state."""
    apply_overwatch_query_tag(session, query_tag)


def _statement_timeout_for_tier(tier: str) -> int:
    if _admin_actions_enabled():
        return STATEMENT_TIMEOUTS_SECONDS["admin"]
    return int(STATEMENT_TIMEOUTS_SECONDS.get(str(tier or "recent"), STATEMENT_TIMEOUTS_SECONDS["recent"]))


def _apply_statement_timeout(session, tier: str) -> None:
    """Record the intended timeout tier without mutating Snowflake session state.

    Streamlit-in-Snowflake can execute app code in a managed procedure context
    where ALTER SESSION is rejected. Warehouse/session timeout policy belongs in
    Snowflake configuration, while OVERWATCH uses read limits, cache tiers, and
    explicit load gates for in-app guardrails.
    """
    timeout = _statement_timeout_for_tier(tier)
    if get_state(STATEMENT_TIMEOUT_SECONDS) == timeout:
        return
    set_state(STATEMENT_TIMEOUT_SECONDS, timeout)


def _check_query_budget(tier: str, ttl_key: str, query_text: str) -> bool:
    """Return False when a non-admin render has exceeded its query-load guardrail."""
    if _admin_actions_enabled() or str(tier or "").lower() in {"metadata"}:
        return True
    try:
        now = time.time()
        started = float(get_state(QUERY_BUDGET_WINDOW_STARTED_AT, 0.0) or 0.0)
        if not started or now - started > 20:
            set_state(QUERY_BUDGET_WINDOW_STARTED_AT, now)
            set_state(QUERY_BUDGET_WINDOW_COUNT, 0)
            set_state(QUERY_BUDGET_WINDOW_WARNED, False)
        set_state(QUERY_BUDGET_WINDOW_COUNT, int(get_state(QUERY_BUDGET_WINDOW_COUNT, 0) or 0) + 1)
        limit = int(QUERY_BUDGET_THRESHOLDS["max_queries_per_render"])
        if int(get_state(QUERY_BUDGET_WINDOW_COUNT, 0) or 0) <= limit:
            return True
        if not get_state(QUERY_BUDGET_WINDOW_WARNED):
            st.warning(
                "OVERWATCH query-load guardrail: this page is loading too many Snowflake queries at once. "
                "Use a narrower filter or refresh the section after the current board finishes."
            )
            set_state(QUERY_BUDGET_WINDOW_WARNED, True)
        return False
    except Exception:
        return True


def _execute_snowflake_query(
    query_text: str,
    query_tag: str = "",
    ttl_key: str = "",
    tier: str = "recent",
    section: str = "",
    max_rows: int | None = None,
    query_boundary: str | None = None,
) -> pd.DataFrame:
    executable_query = _inject_read_limit(query_text, max_rows=max_rows)
    boundary = str(query_boundary or _infer_query_boundary(executable_query, ttl_key, tier))
    telemetry_section = _infer_telemetry_section(section, ttl_key)
    _enforce_explicit_critical_boundary(
        query_boundary=query_boundary,
        resolved_boundary=boundary,
        section=telemetry_section,
        ttl_key=ttl_key,
        tier=tier,
    )
    contract = _enforce_query_contract(
        executable_query,
        boundary=boundary,
        section=telemetry_section,
        ttl_key=ttl_key,
        tier=tier,
        max_rows=max_rows,
    )
    assert_first_paint_query_allowed(
        boundary,
        section=telemetry_section,
        ttl_key=ttl_key,
        tier=tier,
        max_rows=max_rows,
    )
    session = get_session(
        reason="query_execution",
        query_boundary=boundary,
        section=telemetry_section,
        max_rows=max_rows,
        defer_role_capture=bool(boundary == "decision_packet" and max_rows == 1 and is_first_paint_active()),
    )
    _apply_overwatch_query_tag(session, query_tag)
    _apply_statement_timeout(session, tier)
    increment_snowflake_execution_counter(
        boundary,
        section=telemetry_section,
        ttl_key=ttl_key,
        tier=tier,
    )
    token = begin_direct_sql_allowance(
        query_boundary=boundary,
        section=telemetry_section,
        ttl_key=ttl_key,
        max_rows=max_rows,
    )
    try:
        result = normalize_df(session.sql(executable_query).to_pandas())
    finally:
        end_direct_sql_allowance(token)
    return _apply_result_guard(executable_query, result, ttl_key=ttl_key, section=section, tier=tier)


def _cache_context() -> str:
    # Avoid CURRENT_USER/CURRENT_ROLE here. In Streamlit-in-Snowflake this helper
    # can run inside a managed stored-procedure context where those calls may be
    # blocked before the actual page query gets a chance to execute.
    return "|".join([
        str(get_state(ACTIVE_COMPANY, "")),
        str(get_state(GLOBAL_START_DATE, "")),
        str(get_state(GLOBAL_END_DATE, "")),
        str(get_state(GLOBAL_WAREHOUSE, "")),
        str(get_state(GLOBAL_USER, "")),
        str(get_state(GLOBAL_ROLE, "")),
        str(get_state(GLOBAL_DATABASE, "")),
        str(get_state(GLOBAL_ENVIRONMENT, "")),
        str(get_state(CURRENT_ROLE, "")),
    ])


def _cache_salt(ttl_key: str) -> str:
    """Return cache salt for global refresh plus a specific query namespace."""
    global_salt = get_state(REFRESH_SALT_GLOBAL, "")
    scoped_salt = get_state(f"{REFRESH_SALT_PREFIX}{ttl_key}", "")
    return f"{global_salt}|{scoped_salt}"


@st.cache_data(ttl=CACHE_TIERS["live"], show_spinner=False)
def _cached_live(
    query_text: str,
    cache_context: str = "",
    cache_salt: str = "",
    _query_tag: str = "",
    _ttl_key: str = "",
    _section: str = "",
    _query_boundary: str = "",
    _max_rows: int | None = None,
) -> pd.DataFrame:
    try:
        return _execute_snowflake_query(
            query_text, _query_tag, ttl_key=_ttl_key, tier="live", section=_section,
            max_rows=_max_rows, query_boundary=_query_boundary
        )
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
    _query_boundary: str = "",
    _max_rows: int | None = None,
) -> pd.DataFrame:
    try:
        return _execute_snowflake_query(
            query_text, _query_tag, ttl_key=_ttl_key, tier="recent", section=_section,
            max_rows=_max_rows, query_boundary=_query_boundary
        )
    except Exception as e:
        _show_query_warning("Data unavailable", e)
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TIERS["standard"], show_spinner=False)
def _cached_standard(
    query_text: str,
    cache_context: str = "",
    cache_salt: str = "",
    _query_tag: str = "",
    _ttl_key: str = "",
    _section: str = "",
    _query_boundary: str = "",
    _max_rows: int | None = None,
) -> pd.DataFrame:
    try:
        return _execute_snowflake_query(
            query_text, _query_tag, ttl_key=_ttl_key, tier="standard", section=_section,
            max_rows=_max_rows, query_boundary=_query_boundary
        )
    except Exception as e:
        _show_query_warning("Data unavailable", e)
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TIERS["command_summary"], show_spinner=False)
def _cached_command_summary(
    query_text: str,
    cache_context: str = "",
    cache_salt: str = "",
    _query_tag: str = "",
    _ttl_key: str = "",
    _section: str = "",
    _query_boundary: str = "",
    _max_rows: int | None = None,
) -> pd.DataFrame:
    try:
        return _execute_snowflake_query(
            query_text, _query_tag, ttl_key=_ttl_key, tier="command_summary", section=_section,
            max_rows=_max_rows, query_boundary=_query_boundary
        )
    except Exception as e:
        _show_query_warning("Command brief unavailable", e)
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TIERS["historical"], show_spinner=False)
def _cached_historical(
    query_text: str,
    cache_context: str = "",
    cache_salt: str = "",
    _query_tag: str = "",
    _ttl_key: str = "",
    _section: str = "",
    _query_boundary: str = "",
    _max_rows: int | None = None,
) -> pd.DataFrame:
    try:
        return _execute_snowflake_query(
            query_text, _query_tag, ttl_key=_ttl_key, tier="historical", section=_section,
            max_rows=_max_rows, query_boundary=_query_boundary
        )
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
    _query_boundary: str = "",
    _max_rows: int | None = None,
) -> pd.DataFrame:
    try:
        return _execute_snowflake_query(
            query_text, _query_tag, ttl_key=_ttl_key, tier="metadata", section=_section,
            max_rows=_max_rows, query_boundary=_query_boundary
        )
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
    _query_boundary: str = "",
    _max_rows: int | None = None,
) -> pd.DataFrame:
    return _execute_snowflake_query(
        query_text, _query_tag, ttl_key=_ttl_key, tier="live", section=_section,
        max_rows=_max_rows, query_boundary=_query_boundary
    )


@st.cache_data(ttl=CACHE_TIERS["recent"], show_spinner=False)
def _cached_raise_recent(
    query_text: str,
    cache_context: str = "",
    cache_salt: str = "",
    _query_tag: str = "",
    _ttl_key: str = "",
    _section: str = "",
    _query_boundary: str = "",
    _max_rows: int | None = None,
) -> pd.DataFrame:
    return _execute_snowflake_query(
        query_text, _query_tag, ttl_key=_ttl_key, tier="recent", section=_section,
        max_rows=_max_rows, query_boundary=_query_boundary
    )


@st.cache_data(ttl=CACHE_TIERS["standard"], show_spinner=False)
def _cached_raise_standard(
    query_text: str,
    cache_context: str = "",
    cache_salt: str = "",
    _query_tag: str = "",
    _ttl_key: str = "",
    _section: str = "",
    _query_boundary: str = "",
    _max_rows: int | None = None,
) -> pd.DataFrame:
    return _execute_snowflake_query(
        query_text, _query_tag, ttl_key=_ttl_key, tier="standard", section=_section,
        max_rows=_max_rows, query_boundary=_query_boundary
    )


@st.cache_data(ttl=CACHE_TIERS["command_summary"], show_spinner=False)
def _cached_raise_command_summary(
    query_text: str,
    cache_context: str = "",
    cache_salt: str = "",
    _query_tag: str = "",
    _ttl_key: str = "",
    _section: str = "",
    _query_boundary: str = "",
    _max_rows: int | None = None,
) -> pd.DataFrame:
    return _execute_snowflake_query(
        query_text, _query_tag, ttl_key=_ttl_key, tier="command_summary", section=_section,
        max_rows=_max_rows, query_boundary=_query_boundary
    )


@st.cache_data(ttl=CACHE_TIERS["historical"], show_spinner=False)
def _cached_raise_historical(
    query_text: str,
    cache_context: str = "",
    cache_salt: str = "",
    _query_tag: str = "",
    _ttl_key: str = "",
    _section: str = "",
    _query_boundary: str = "",
    _max_rows: int | None = None,
) -> pd.DataFrame:
    return _execute_snowflake_query(
        query_text, _query_tag, ttl_key=_ttl_key, tier="historical", section=_section,
        max_rows=_max_rows, query_boundary=_query_boundary
    )


@st.cache_data(ttl=CACHE_TIERS["metadata"], show_spinner=False)
def _cached_raise_metadata(
    query_text: str,
    cache_context: str = "",
    cache_salt: str = "",
    _query_tag: str = "",
    _ttl_key: str = "",
    _section: str = "",
    _query_boundary: str = "",
    _max_rows: int | None = None,
) -> pd.DataFrame:
    return _execute_snowflake_query(
        query_text, _query_tag, ttl_key=_ttl_key, tier="metadata", section=_section,
        max_rows=_max_rows, query_boundary=_query_boundary
    )


# Backward-compatible 5-min cache - for callers that don't pass tier=
@st.cache_data(ttl=CACHE_TIERS["recent"], show_spinner=False)
def run_query_cached(
    query_text: str,
    cache_context: str = "",
    cache_salt: str = "",
    _query_tag: str = "",
    _ttl_key: str = "",
    _section: str = "",
    _query_boundary: str = "",
    _max_rows: int | None = None,
) -> pd.DataFrame:
    """Backward-compatible runner. Prefer run_query(tier=...) for new code."""
    try:
        return _execute_snowflake_query(
            query_text, _query_tag, ttl_key=_ttl_key, tier="recent", section=_section,
            max_rows=_max_rows, query_boundary=_query_boundary
        )
    except Exception as e:
        _show_query_warning("Data unavailable", e)
        return pd.DataFrame()


_TIER_FN = {
    "live":       _cached_live,
    "command_summary": _cached_command_summary,
    "standard":   _cached_standard,
    "recent":     _cached_recent,
    "historical": _cached_historical,
    "metadata":   _cached_metadata,
}


_RAISE_TIER_FN = {
    "live":       _cached_raise_live,
    "command_summary": _cached_raise_command_summary,
    "standard":   _cached_raise_standard,
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
    query_boundary: str | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
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
        Normalized DataFrame and SQL-free execution metadata.
    """
    boundary = str(query_boundary or _infer_query_boundary(query_text, ttl_key, tier))
    telemetry_section = _infer_telemetry_section(section, ttl_key)
    _enforce_explicit_critical_boundary(
        query_boundary=query_boundary,
        resolved_boundary=boundary,
        section=telemetry_section,
        ttl_key=ttl_key,
        tier=tier,
    )
    executable_query = _inject_read_limit(query_text, max_rows=max_rows)
    contract = _enforce_query_contract(
        executable_query,
        boundary=boundary,
        section=telemetry_section,
        ttl_key=ttl_key,
        tier=tier,
        max_rows=max_rows,
    )
    meta: dict[str, object] = {
        "actual_query_executed": None,
        "cache_layer": "unknown",
        "query_boundary": boundary,
        "query_contract_id": str(getattr(contract, "contract_id", "") or ""),
        "first_paint_sensitive": bool(current_first_paint_render_id()) and _first_paint_sensitive_boundary(boundary),
        "error": "",
    }
    meta.update(_target_metadata_from_sql(executable_query, boundary))
    assert_first_paint_query_allowed(
        boundary,
        section=telemetry_section,
        ttl_key=ttl_key,
        tier=tier,
        max_rows=max_rows,
    )
    if queries_paused():
        meta.update(actual_query_executed=False, cache_layer="paused")
        return empty_paused_result(ttl_key=ttl_key, section=section), meta
    if not _check_query_budget(tier, ttl_key, query_text):
        meta.update(actual_query_executed=False, cache_layer="budget_blocked")
        return pd.DataFrame(), meta
    with st.spinner(spinner_msg):
        try:
            query_tag = _build_overwatch_query_tag(section, ttl_key, tier)
            if use_cache:
                cache_salt = _cache_salt(ttl_key)
                context = _cache_context()
                fn   = _TIER_FN.get(tier, _cached_recent)
                meta.update(actual_query_executed=None, cache_layer="streamlit_cache")
                return fn(executable_query, context, cache_salt, query_tag, ttl_key, section, boundary, max_rows), meta
            # Bypass cache - always wrapped in try/except
            try:
                meta.update(actual_query_executed=True, cache_layer="none")
                return _execute_snowflake_query(
                    executable_query,
                    query_tag,
                    ttl_key=ttl_key,
                    tier=tier,
                    section=section,
                    max_rows=max_rows,
                    query_boundary=boundary,
                ), meta
            except Exception as e:
                _show_query_warning("Data unavailable", e)
                meta.update(actual_query_executed=True, cache_layer="none", error=format_snowflake_error(e))
                return pd.DataFrame(), meta
        except Exception as e:
            _show_query_warning("Query runner issue", e)
            meta.update(error=format_snowflake_error(e))
            return pd.DataFrame(), meta


def run_query(
    query_text: str,
    ttl_key: str = "default",
    use_cache: bool = True,
    spinner_msg: str = "Loading data...",
    tier: str = "recent",
    section: str = "",
    max_rows: int | None = None,
    query_boundary: str | None = None,
) -> pd.DataFrame:
    """Execute a query through the cached runner and log lightweight telemetry."""
    started = time.perf_counter()
    started_at = datetime.now().isoformat(timespec="milliseconds")
    result, query_meta = _run_query_base(
        query_text=query_text,
        ttl_key=ttl_key,
        use_cache=use_cache,
        spinner_msg=spinner_msg,
        tier=tier,
        section=section,
        max_rows=max_rows,
        query_boundary=query_boundary,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    finished_at = datetime.now().isoformat(timespec="milliseconds")
    result_mb = _estimate_result_mb(result)
    _record_query_telemetry(query_text, ttl_key, tier, elapsed_ms, len(result), use_cache, result_mb, section)
    record_ui_query_event(
        section=_infer_telemetry_section(section, ttl_key),
        workflow=str(get_state(NAV_SECTION, "") or ""),
        query_tier=tier,
        ttl_key=ttl_key,
        cache_hit_or_use_cache=bool(use_cache),
        elapsed_ms=elapsed_ms,
        row_count=len(result),
        max_rows=max_rows,
        error=query_meta.get("error", ""),
        started_at=started_at,
        finished_at=finished_at,
        actual_query_executed=query_meta.get("actual_query_executed"),
        cache_layer=str(query_meta.get("cache_layer") or "unknown"),
        query_boundary=str(query_meta.get("query_boundary") or "other"),
        query_contract_id=str(query_meta.get("query_contract_id") or ""),
        target_columns_used=list(query_meta.get("target_columns_used") or []),
        target_predicate_marker_present=query_meta.get("target_predicate_marker_present"),
        target_fallback_used=query_meta.get("target_fallback_used"),
        first_paint_sensitive=bool(query_meta.get("first_paint_sensitive")),
    )
    return result


def run_query_or_raise(
    query_text: str,
    section: str = "",
    ttl_key: str = "direct",
    tier: str = "live",
    max_rows: int | None = None,
    use_cache: bool = True,
    query_boundary: str | None = None,
) -> pd.DataFrame:
    """
    Execute SQL and return a normalized DataFrame, preserving exceptions.

    Use this for live probes and primary/fallback query paths where callers need
    the original Snowflake exception to decide whether to run a fallback query.
    """
    started = time.perf_counter()
    started_at = datetime.now().isoformat(timespec="milliseconds")
    result = pd.DataFrame()
    query_tag = _build_overwatch_query_tag(section, ttl_key, tier)
    executable_query = _inject_read_limit(query_text, max_rows=max_rows)
    boundary = str(query_boundary or _infer_query_boundary(query_text, ttl_key, tier))
    telemetry_section = _infer_telemetry_section(section, ttl_key)
    _enforce_explicit_critical_boundary(
        query_boundary=query_boundary,
        resolved_boundary=boundary,
        section=telemetry_section,
        ttl_key=ttl_key,
        tier=tier,
    )
    contract = _enforce_query_contract(
        executable_query,
        boundary=boundary,
        section=telemetry_section,
        ttl_key=ttl_key,
        tier=tier,
        max_rows=max_rows,
    )
    target_metadata = _target_metadata_from_sql(executable_query, boundary)
    assert_first_paint_query_allowed(
        boundary,
        section=telemetry_section,
        ttl_key=ttl_key,
        tier=tier,
        max_rows=max_rows,
    )
    if queries_paused():
        finished_at = datetime.now().isoformat(timespec="milliseconds")
        record_ui_query_event(
            section=telemetry_section,
            workflow=str(get_state(NAV_SECTION, "") or ""),
            query_tier=tier,
            ttl_key=ttl_key,
            cache_hit_or_use_cache=bool(use_cache),
            elapsed_ms=(time.perf_counter() - started) * 1000,
            row_count=0,
            max_rows=max_rows,
            started_at=started_at,
            finished_at=finished_at,
            actual_query_executed=False,
            cache_layer="paused",
            query_boundary=boundary,
            query_contract_id=str(getattr(contract, "contract_id", "") or ""),
            target_columns_used=list(target_metadata.get("target_columns_used") or []),
            target_predicate_marker_present=target_metadata.get("target_predicate_marker_present"),
            target_fallback_used=target_metadata.get("target_fallback_used"),
            first_paint_sensitive=bool(current_first_paint_render_id()) and _first_paint_sensitive_boundary(boundary),
        )
        return empty_paused_result(ttl_key=ttl_key, section=section)
    if not _check_query_budget(tier, ttl_key, query_text):
        finished_at = datetime.now().isoformat(timespec="milliseconds")
        record_ui_query_event(
            section=telemetry_section,
            workflow=str(get_state(NAV_SECTION, "") or ""),
            query_tier=tier,
            ttl_key=ttl_key,
            cache_hit_or_use_cache=bool(use_cache),
            elapsed_ms=(time.perf_counter() - started) * 1000,
            row_count=0,
            max_rows=max_rows,
            started_at=started_at,
            finished_at=finished_at,
            actual_query_executed=False,
            cache_layer="budget_blocked",
            query_boundary=boundary,
            query_contract_id=str(getattr(contract, "contract_id", "") or ""),
            target_columns_used=list(target_metadata.get("target_columns_used") or []),
            target_predicate_marker_present=target_metadata.get("target_predicate_marker_present"),
            target_fallback_used=target_metadata.get("target_fallback_used"),
            first_paint_sensitive=bool(current_first_paint_render_id()) and _first_paint_sensitive_boundary(boundary),
        )
        return result
    error_message = ""
    try:
        if use_cache:
            cache_salt = _cache_salt(ttl_key)
            context = _cache_context()
            fn = _RAISE_TIER_FN.get(tier, _cached_raise_recent)
            result = fn(executable_query, context, cache_salt, query_tag, ttl_key, section, boundary, max_rows)
            return result
        result = _execute_snowflake_query(
            executable_query,
            query_tag,
            ttl_key=ttl_key,
            tier=tier,
            section=section,
            max_rows=max_rows,
            query_boundary=boundary,
        )
        return result
    except Exception as exc:
        error_message = format_snowflake_error(exc)
        raise
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000
        finished_at = datetime.now().isoformat(timespec="milliseconds")
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
        record_ui_query_event(
            section=telemetry_section,
            workflow=str(get_state(NAV_SECTION, "") or ""),
            query_tier=tier,
            ttl_key=ttl_key,
            cache_hit_or_use_cache=bool(use_cache),
            elapsed_ms=elapsed_ms,
            row_count=len(result),
            max_rows=max_rows,
            error=error_message,
            started_at=started_at,
            finished_at=finished_at,
            actual_query_executed=None if use_cache else True,
            cache_layer="streamlit_cache" if use_cache else "none",
            query_boundary=boundary,
            query_contract_id=str(getattr(contract, "contract_id", "") or ""),
            target_columns_used=list(target_metadata.get("target_columns_used") or []),
            target_predicate_marker_present=target_metadata.get("target_predicate_marker_present"),
            target_fallback_used=target_metadata.get("target_fallback_used"),
            first_paint_sensitive=bool(current_first_paint_render_id()) and _first_paint_sensitive_boundary(boundary),
        )


def force_refresh(key: str):
    """Bump cache salt to force re-execution of a specific section's queries."""
    set_state(f"{REFRESH_SALT_PREFIX}{key}", datetime.now().isoformat())
