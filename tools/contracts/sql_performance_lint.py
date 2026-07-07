"""Static SQL performance linter for OVERWATCH deployment files."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable


def _strip_literals(sql: str) -> str:
    return re.sub(r"'(?:''|[^'])*'", "''", str(sql or ""), flags=re.DOTALL)


def _body_between(sql: str, start: str, end: str) -> str:
    upper = sql.upper()
    start_pos = upper.find(start.upper())
    if start_pos < 0:
        return ""
    end_pos = upper.find(end.upper(), start_pos + len(start))
    return sql[start_pos:end_pos if end_pos >= 0 else len(sql)]


_TIME_PRUNING_COLUMNS = (
    "START_TIME",
    "END_TIME",
    "USAGE_DATE",
    "USAGE_TIME",
    "QUERY_START_TIME",
    "SNAPSHOT_DATE",
    "LOGIN_DATE",
    "COMPLETED_TIME",
    "SCHEDULED_TIME",
    "EVENT_TS",
    "LOAD_TS",
    "LAST_ALTERED",
    "CREATED_ON",
    "EXPIRATION_DATE",
)


def _has_always_true_time_predicate(window: str) -> bool:
    current_expr = r"CURRENT_(?:TIMESTAMP|DATE)\s*(?:\(\s*\))?"
    return bool(
        re.search(rf"\b{current_expr}\s*(?:>=|>|<=|<|=)\s*DATEADD\s*\(", window)
        or re.search(rf"\bDATEADD\s*\([^)]*{current_expr}[^)]*\)\s*(?:>=|>|<=|<|=)\s*{current_expr}", window)
    )


def _has_time_predicate(window: str) -> bool:
    columns = "|".join(_TIME_PRUNING_COLUMNS)
    return bool(
        re.search(rf"\b({columns})\b\s*(?:>=|>|<=|<|=|BETWEEN)\s+", window)
        or re.search(rf"\bDATE(?:ADD|_TRUNC)\s*\([^)]*\b({columns})\b", window)
    )


def _has_order_before_limit(window: str) -> bool:
    order_pos = window.find("ORDER BY")
    limit_pos = window.find("LIMIT")
    return order_pos >= 0 and (limit_pos < 0 or order_pos < limit_pos)


def _is_bounded_admin_account_usage_scan(table_name: str, marker_window: str, query_window: str) -> bool:
    return (
        table_name == "OBJECT_DEPENDENCIES"
        and "OVERWATCH_ADMIN_BOUNDED_ACCOUNT_USAGE_SCAN" in marker_window
        and _has_order_before_limit(query_window)
        and bool(re.search(r"\bLIMIT\s+\d+\b", query_window))
    )


def _is_current_object_snapshot_scan(table_name: str, marker_window: str, query_window: str) -> bool:
    return (
        table_name in {"TASKS", "PROCEDURES", "GRANTS_TO_USERS"}
        and "OVERWATCH_CURRENT_OBJECT_SNAPSHOT_SCAN" in marker_window
        and ("DELETED IS NULL" in query_window or "DELETED_ON IS NULL" in query_window)
    )


def _infer_mode(path: str, upper: str) -> str:
    normalized = str(path or "").replace("\\", "/").lower()
    if "fast_impl" in normalized:
        return "refresh_fast"
    if "full_impl" in normalized:
        return "refresh_full"
    if "account_usage" in normalized:
        return "account_usage_fallback"
    if "query_search" in normalized:
        return "query_search"
    if "evidence" in normalized:
        return "evidence"
    if "/validation/" in normalized or normalized.startswith("snowflake/validation/"):
        return "deployment_validation"
    if "first_paint" in normalized or "packet_lookup" in normalized:
        return "app_first_paint"
    if "SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS_FAST_IMPL" in upper:
        return "auto"
    return "auto"


def _limit_value(upper: str) -> int | None:
    matches = re.findall(r"\bLIMIT\s+(\d+)\b", upper)
    if not matches:
        return None
    try:
        return int(matches[-1])
    except Exception:
        return None


def _marker_before_limit(upper: str) -> bool:
    marker_pos = upper.find("OVERWATCH_TARGET_PREDICATE")
    if marker_pos < 0:
        return False
    limit_pos = upper.find("LIMIT", marker_pos)
    return limit_pos >= 0


_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def _risk_score(code: str, severity: str, mode: str) -> int:
    score = {"error": 90, "warning": 55, "info": 20}.get(str(severity or "").lower(), 40)
    if str(mode or "") in {"app_first_paint", "refresh_fast", "account_usage_fallback"}:
        score += 8
    if any(token in str(code or "") for token in ("ACCOUNT_USAGE", "SELECT_STAR", "UNBOUNDED", "FULL_WINDOW")):
        score += 5
    return min(score, 100)


def _expected_pruning_key(code: str, mode: str) -> str:
    code = str(code or "")
    if "ACCOUNT_USAGE" in code:
        return "source time predicate plus LIMIT; OBJECT_DEPENDENCIES requires documented admin marker, ORDER BY, and LIMIT"
    if str(mode or "") == "app_first_paint":
        return "IS_ACTIVE, SECTION_NAME_NORM, COMPANY_NORM, ENVIRONMENT_NORM, WINDOW_DAYS_NORM"
    if str(mode or "") == "evidence":
        return "OVERWATCH_TARGET_PREDICATE and target lookup columns"
    if str(mode or "") == "query_search":
        return "QUERY_ID, QUERY_HASH, QUERY_SIGNATURE, WAREHOUSE_NAME"
    if str(mode or "") == "refresh_fast":
        return "1/7 day compact source facts"
    return "bounded scope predicate"


def _recommendation_for(code: str, mode: str) -> str:
    code = str(code or "")
    if "METRIC" in code or "TREND" in code:
        return "Keep metric candidate branches column-aligned, project CONFIDENCE, and join trend rows through the documented unique key."
    if "COALESCE_MIXED_TYPE" in code:
        return "Cast mixed identifier/key COALESCE arguments to a common VARCHAR type before combining them."
    if "ACCOUNT_USAGE" in code:
        return "Move to confirmed fallback/admin path and include a real source time predicate plus LIMIT; if no source timestamp exists, add an explicit admin-only marker, ORDER BY, and LIMIT."
    if "SELECT_STAR" in code:
        return "Project only app-facing columns required by the view or proof artifact."
    if "TARGET_MARKER" in code:
        return "Build predicates through the target predicate planner before LIMIT."
    if "QUERY_TEXT" in code:
        return "Load query text only through the explicit query_preview action."
    if str(mode or "") == "refresh_fast":
        return "Use compact source snapshots and first-viewport staging instead of full refresh branches."
    return "Add bounded predicates and route heavy work behind an explicit action."


def lint_sql_text(
    sql: str,
    *,
    path: str = "",
    mode: str = "auto",
    target_context_present: bool = False,
    metadata_probe_declared: bool = False,
) -> list[dict[str, object]]:
    """Return SQL-free performance findings for deployment SQL."""
    text = _strip_literals(sql)
    upper = text.upper()
    mode = str(mode or "auto").strip().lower()
    if mode == "auto":
        mode = _infer_mode(path, upper)
    findings: list[dict[str, object]] = []

    def add(code: str, severity: str, message: str) -> None:
        normalized_severity = str(severity or "").lower()
        findings.append({
            "path": path,
            "mode": mode,
            "code": code,
            "severity": normalized_severity,
            "risk_score": _risk_score(code, normalized_severity, mode),
            "surface": mode,
            "estimated_bytes_risk": "high" if normalized_severity == "error" else "medium",
            "expected_pruning_key": _expected_pruning_key(code, mode),
            "recommended_replacement": _recommendation_for(code, mode),
            "message": message,
            "raw_sql_included": False,
        })

    if str(sql or "").startswith("\ufeff") or text.startswith("\ufeff"):
        add("SQL_FILE_BOM", "error", "Snowflake SQL files must be UTF-8 without a byte-order mark.")
    if "\ufffd" in str(sql or ""):
        add("SQL_REPLACEMENT_CHARACTER", "error", "Snowflake SQL files must not contain replacement characters.")
    if any(token in str(sql or "") for token in ("\u00e2", "\u00c3", "\u00c2")):
        add("SQL_MOJIBAKE_RISK", "error", "Snowflake SQL files must not contain mojibake characters.")

    if re.search(r"\bCOALESCE\s*\([^)]*(?<![:])\b[A-Z0-9_]*_ID\b(?!\s*(?:::|AS)\s*VARCHAR)[^)]*\b[A-Z0-9_]*_KEY\b", upper):
        add("COALESCE_MIXED_TYPE_RISK", "error", "COALESCE between identifier and key columns must cast to a common type.")
    if "INSERT INTO MART_SECTION_COMMAND_METRIC" in upper:
        try:
            from tools.contracts.snowflake_execution_validation import validate_metric_candidate_union_shape

            metric_shape = validate_metric_candidate_union_shape(sql)
        except Exception:
            metric_shape = {"passed": False, "failures": [{"code": "METRIC_SHAPE_VALIDATION_ERROR"}]}
        for failure in metric_shape.get("failures", []):
            if not isinstance(failure, dict):
                continue
            code = str(failure.get("code") or "METRIC_SHAPE_FAILURE")
            add(code, "error", "Command metric candidate UNION shape is not safe for stored procedure compilation.")

    fast_body = _body_between(
        upper,
        "CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS_FAST_IMPL()",
        "CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS_FULL_IMPL()",
    )
    fast_region = fast_body if fast_body else (upper if mode == "refresh_fast" else "")
    if fast_region:
        if "CALL SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS(" in fast_region:
            add("FAST_IMPL_SHARED_CORE_CALL", "error", "FAST_IMPL must not call the shared full-heavy command brief procedure.")
        if re.search(r"\b(14|30|60|90)\b", fast_region):
            add("FAST_IMPL_FULL_WINDOW", "error", "FAST_IMPL must not contain full-only windows.")
        if re.search(r"\bTMP_FAST_SECTION_DECISION_PACKET_FLAT\b[\s\S]{0,900}\bFROM\s+MART_SECTION_DECISION_CURRENT_FLAT\b", fast_region):
            add("FAST_IMPL_REPUBLISH_CURRENT_FLAT", "error", "FAST_IMPL flat packet staging must not source from current flat packets.")
        if "DATE_SPINE" in fast_region or "CALENDAR_SPINE" in fast_region:
            add("FAST_IMPL_HISTORICAL_DATE_SPINE", "error", "FAST_IMPL must not build broad historical date spines.")
        if re.search(r"\bARRAY_AGG\s*\(", fast_region) and not re.search(r"\b(ROW_NUMBER|QUALIFY|LIMIT|ARRAY_SLICE|TMP_FAST_SECTION_COMMAND_)\b", fast_region):
            add("FAST_IMPL_UNBOUNDED_ARRAY_AGG", "error", "FAST_IMPL array aggregation must be capped for first viewport packets.")
        reads_command_marts = bool(re.search(r"\bFROM\s+MART_SECTION_COMMAND_", fast_region))
        has_fresh_snapshot = "TMP_FAST_SOURCE_SNAPSHOT" in fast_region or "REUSE_LATEST_COMPACT_SOURCE" in fast_region
        if reads_command_marts and not has_fresh_snapshot:
            add("FAST_IMPL_REUSES_COMMAND_MARTS_WITHOUT_SOURCE_SNAPSHOT", "warning", "FAST_IMPL command reuse must be backed by a fresh compact source snapshot.")
        if reads_command_marts and "TMP_FAST_COMMAND_FRESHNESS" not in fast_region:
            add("FAST_IMPL_COMMAND_FRESHNESS_UNPROVEN", "error", "FAST_IMPL command reuse must emit fresh/reused/stale command-row proof.")
        has_source_ts_audit = bool(
            re.search(r"\bOBJECT_AGG\s*\(\s*SOURCE_KEY\s*,\s*(?:TO_VARIANT\s*\(\s*)?SOURCE_FACT_MAX_TS", fast_region)
        )
        if reads_command_marts and not has_source_ts_audit:
            add("FAST_IMPL_SOURCE_TS_AUDIT_MISSING", "error", "FAST_IMPL audit must include source fact max timestamps by source.")
        if "TMP_FAST_SOURCE_SNAPSHOT" in fast_region:
            source_tokens = (
                "FACT_QUERY_DETAIL_RECENT",
                "FACT_QUERY_HOURLY",
                "ALERT_EVENTS",
                "FACT_COST_DAILY",
                "FACT_GRANT_DAILY",
                "FACT_LOGIN_DAILY",
                "MART_QUERY_EVIDENCE_RECENT",
                "MART_ALERT_EVIDENCE_RECENT",
                "MART_SECURITY_EVIDENCE_RECENT",
                "MART_COST_EVIDENCE_RECENT",
                "MART_DBA_EVIDENCE_RECENT",
            )
            if not any(token in fast_region for token in source_tokens):
                add("FAST_IMPL_SOURCE_SNAPSHOT_NOT_FACT_BACKED", "error", "FAST source snapshot must read compact source facts or recent evidence marts.")
    for match in re.finditer(r"\bFROM\s+SNOWFLAKE\.ACCOUNT_USAGE\.([A-Z0-9_]+)", upper):
        table_name = match.group(1)
        marker_window = upper[max(0, match.start() - 500):match.start() + 1600]
        query_window = upper[match.start():match.start() + 1600]
        if _has_always_true_time_predicate(marker_window):
            add("ALWAYS_TRUE_TIME_PREDICATE", "error", "Time predicates must compare source timestamp columns, not CURRENT_TIMESTAMP to DATEADD of itself.")
        has_bound = _has_time_predicate(query_window)
        has_limit = bool(re.search(r"\bLIMIT\s+\d+\b", query_window))
        has_bounded_admin_scan = _is_bounded_admin_account_usage_scan(table_name, marker_window, query_window)
        has_current_object_snapshot_scan = _is_current_object_snapshot_scan(table_name, marker_window, query_window)
        if not has_bound and has_limit and not _has_order_before_limit(query_window):
            add("ACCOUNT_USAGE_LIMIT_WITHOUT_ORDER_OR_PREDICATE", "warning", "LIMIT-only Account Usage scans need deterministic ORDER BY or a real source time predicate.")
        if not has_bound and not has_bounded_admin_scan and not has_current_object_snapshot_scan:
            add("ACCOUNT_USAGE_UNBOUNDED", "error", "Account Usage reads must include a time predicate.")
        elif has_bound and not has_limit:
            add("ACCOUNT_USAGE_NO_LIMIT", "warning", "Account Usage reads should include LIMIT on app-facing/fallback paths.")
    if re.search(r"\bSELECT\s+\*", upper):
        severity = "error" if "APP_FACING" in upper else "warning"
        add("APP_FACING_SELECT_STAR", severity, "Wildcard projection is forbidden in app-facing deployment SQL unless explicitly allowlisted.")
    if mode == "app_first_paint":
        if 'DECISION_PACKET:"' in upper:
            add("FIRST_PAINT_VARIANT_EXTRACTION", "error", "First-paint packet lookup must read materialized flat columns.")
        if re.search(r"\bSELECT\s+\*", upper):
            add("FIRST_PAINT_SELECT_STAR", "error", "First-paint packet lookup must use explicit columns.")
        if "SNOWFLAKE.ACCOUNT_USAGE" in upper:
            add("FIRST_PAINT_ACCOUNT_USAGE", "error", "First paint must not read Account Usage.")
        if re.search(r"\b(SHOW|DESCRIBE|DESC)\b", upper):
            add("FIRST_PAINT_METADATA_PROBE", "error", "First paint must not run metadata probes.")
        limit = _limit_value(upper)
        if limit != 1:
            add("FIRST_PAINT_LIMIT_ONE_REQUIRED", "error", "First-paint packet lookup must use LIMIT 1.")
    if mode == "evidence":
        limit = _limit_value(upper)
        if limit is None or limit > 500:
            add("EVIDENCE_LIMIT_REQUIRED", "error", "Evidence queries must be bounded to 500 rows or fewer.")
        if target_context_present and not _marker_before_limit(upper):
            add("EVIDENCE_TARGET_MARKER_REQUIRED", "error", "Targeted evidence SQL must include the target predicate marker before LIMIT.")
        if "EVIDENCE_QUERY" in upper and re.search(r"\b(CALL|EXECUTE IMMEDIATE|SESSION\.SQL)\b", upper):
            add("EXECUTABLE_EVIDENCE_QUERY", "error", "Packet EVIDENCE_QUERY must never be executable SQL.")
        if "SNOWFLAKE.ACCOUNT_USAGE" in upper and "DEEP_FALLBACK" not in upper:
            add("EVIDENCE_ACCOUNT_USAGE_FORBIDDEN", "error", "Normal evidence clicks must use compact marts, not Account Usage.")
    if mode == "account_usage_fallback":
        if "SNOWFLAKE.ACCOUNT_USAGE" in upper:
            if _has_always_true_time_predicate(upper):
                add("ALWAYS_TRUE_TIME_PREDICATE", "error", "Account Usage fallback must use a source timestamp predicate, not CURRENT_TIMESTAMP tautologies.")
            if not _has_time_predicate(upper):
                add("ACCOUNT_USAGE_UNBOUNDED", "error", "Account Usage fallback must include a time predicate.")
            if _limit_value(upper) is None:
                add("ACCOUNT_USAGE_NO_LIMIT", "error", "Account Usage fallback must include LIMIT.")
        if not metadata_probe_declared and re.search(r"\b(SHOW|DESCRIBE|DESC|LIMIT\s+0)\b", upper):
            add("ACCOUNT_USAGE_METADATA_PROBE_UNDECLARED", "error", "Account Usage fallback metadata probes must be declared in budget artifacts.")
    if mode == "query_search":
        limit = _limit_value(upper)
        if re.search(r"\bQUERY_ID\s*=", upper) and limit != 1 and "QUERY_ID <>" not in upper:
            add("QUERY_SEARCH_EXACT_LIMIT_ONE", "error", "Exact query-id search must default to LIMIT 1.")
        if re.search(r"\b(QUERY_HASH|QUERY_SIGNATURE)\s*=", upper) and limit is not None and limit > 200:
            add("QUERY_SEARCH_SIGNATURE_LIMIT", "error", "Query signature search must cap rows at 200 or fewer.")
        if "QUERY_SEARCH_RELATED" in upper and limit is not None and limit > 50:
            add("QUERY_SEARCH_RELATED_LIMIT", "error", "Related executions search must cap rows at 50 or fewer.")
        if "QUERY_TEXT" in upper and "QUERY_TEXT_PREVIEW" not in upper:
            add("QUERY_SEARCH_QUERY_TEXT_PROJECTION", "error", "Default Query Search results and exports must not project query_text.")
    first_paint_region = _body_between(
        upper,
        "CREATE TRANSIENT TABLE IF NOT EXISTS MART_SECTION_DECISION_CURRENT_FLAT",
        "CREATE TABLE IF NOT EXISTS OVERWATCH_DECISION_SETUP_HEALTH",
    )
    if first_paint_region.count('DECISION_PACKET:"') > 35:
        add("REPEATED_PACKET_VARIANT_EXTRACTION", "warning", "Backfill may extract packet fields, but app first-paint lookup must use flat columns.")
    if re.search(r"\bEVIDENCE_QUERY\b[\s\S]{0,160}\b(CALL|EXECUTE IMMEDIATE)\b", upper) or (
        "EVIDENCE_QUERY" in upper and re.search(r"\b(CALL|EXECUTE IMMEDIATE)\b[\s\S]{0,160}EVIDENCE_QUERY", upper)
    ):
        add("EXECUTABLE_EVIDENCE_QUERY", "error", "Packet EVIDENCE_QUERY must never be executable SQL.")
    if re.search(r"ILIKE\s+'%[^']*%'", upper):
        add("BROAD_ILIKE_TARGET_CONTEXT", "warning", "Broad ILIKE contains filters are forbidden in route/target contexts.")
    for match in re.finditer(r"\bORDER\s+BY\b", upper):
        window = upper[max(0, match.start() - 500):match.start() + 500]
        has_limit = bool(re.search(r"\bLIMIT\s+\d+\b", window))
        has_scope = bool(re.search(r"\b(SECTION_NAME_NORM|COMPANY_NORM|ENVIRONMENT_NORM|WINDOW_DAYS_NORM|QUERY_ID|ALERT_ID|EVENT_ID|GRANT_ID)\b", window))
        if not has_limit and not has_scope:
            add("ORDER_BY_BEFORE_PRUNING", "warning", "ORDER BY should follow scope pruning or LIMIT on app-facing paths.")
    return sorted(
        findings,
        key=lambda finding: (
            _SEVERITY_ORDER.get(str(finding.get("severity") or "").lower(), 9),
            -int(str(finding.get("risk_score") or 0)),
            str(finding.get("code") or ""),
        ),
    )


def lint_sql_files(paths: Iterable[Path], *, root: Path, mode_by_path: dict[str, str] | None = None) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    mode_by_path = mode_by_path or {}
    for path in paths:
        path = Path(path)
        if not path.exists() or path.suffix.lower() != ".sql":
            continue
        try:
            relative = str(path.relative_to(root))
        except ValueError:
            relative = str(path)
        normalized = relative.replace("\\", "/")
        findings.extend(
            lint_sql_text(
                path.read_text(encoding="utf-8", errors="ignore"),
                path=relative,
                mode=mode_by_path.get(normalized, mode_by_path.get(path.name, "auto")),
            )
        )
    return sorted(
        findings,
        key=lambda finding: (
            _SEVERITY_ORDER.get(str(finding.get("severity") or "").lower(), 9),
            -int(str(finding.get("risk_score") or 0)),
            str(finding.get("code") or ""),
        ),
    )


__all__ = ["lint_sql_files", "lint_sql_text"]
