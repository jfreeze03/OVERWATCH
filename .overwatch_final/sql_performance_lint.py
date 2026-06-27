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


def _has_time_predicate(window: str) -> bool:
    return bool(
        re.search(
            r"\b(DATEADD|CURRENT_DATE|CURRENT_TIMESTAMP|START_TIME|END_TIME|USAGE_DATE|QUERY_START_TIME|"
            r"SNAPSHOT_DATE|LOGIN_DATE|COMPLETED_TIME|SCHEDULED_TIME|EVENT_TS|LOAD_TS)\b",
            window,
        )
    )


def lint_sql_text(sql: str, *, path: str = "") -> list[dict[str, object]]:
    """Return SQL-free performance findings for deployment SQL."""
    text = _strip_literals(sql)
    upper = text.upper()
    findings: list[dict[str, object]] = []

    def add(code: str, severity: str, message: str) -> None:
        findings.append({
            "path": path,
            "code": code,
            "severity": severity,
            "message": message,
            "raw_sql_included": False,
        })

    fast_body = _body_between(
        upper,
        "CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS_FAST_IMPL()",
        "CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS_FULL_IMPL()",
    )
    if fast_body:
        if "CALL SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS(" in fast_body:
            add("FAST_IMPL_SHARED_CORE_CALL", "error", "FAST_IMPL must not call the shared full-heavy command brief procedure.")
        if re.search(r"\b(14|30|60|90)\b", fast_body):
            add("FAST_IMPL_FULL_WINDOW", "error", "FAST_IMPL must not contain full-only windows.")
        if re.search(r"\bTMP_FAST_SECTION_DECISION_PACKET_FLAT\b[\s\S]{0,600}\bFROM\s+MART_SECTION_DECISION_CURRENT_FLAT\b", fast_body):
            add("FAST_IMPL_REPUBLISH_CURRENT_FLAT", "error", "FAST_IMPL flat packet staging must not source from current flat packets.")
        if re.search(r"\bARRAY_AGG\s*\(", fast_body) and not re.search(r"\b(ROW_NUMBER|QUALIFY|LIMIT|ARRAY_SLICE)\b", fast_body):
            add("FAST_IMPL_UNBOUNDED_ARRAY_AGG", "error", "FAST_IMPL array aggregation must be capped for first viewport packets.")
    for match in re.finditer(r"\bFROM\s+SNOWFLAKE\.ACCOUNT_USAGE\.[A-Z0-9_]+", upper):
        window = upper[match.start():match.start() + 1200]
        has_bound = _has_time_predicate(window)
        has_limit = bool(re.search(r"\bLIMIT\s+\d+\b", window))
        if not has_bound:
            add("ACCOUNT_USAGE_UNBOUNDED", "error", "Account Usage reads must include a time predicate.")
        elif not has_limit:
            add("ACCOUNT_USAGE_NO_LIMIT", "warning", "Account Usage reads should include LIMIT on app-facing/fallback paths.")
    if re.search(r"\bSELECT\s+\*", upper):
        severity = "error" if "APP_FACING" in upper else "warning"
        add("APP_FACING_SELECT_STAR", severity, "Wildcard projection is forbidden in app-facing deployment SQL unless explicitly allowlisted.")
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
    return findings


def lint_sql_files(paths: Iterable[Path], *, root: Path) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for path in paths:
        path = Path(path)
        if not path.exists() or path.suffix.lower() != ".sql":
            continue
        try:
            relative = str(path.relative_to(root))
        except ValueError:
            relative = str(path)
        findings.extend(lint_sql_text(path.read_text(encoding="utf-8", errors="ignore"), path=relative))
    return findings


__all__ = ["lint_sql_files", "lint_sql_text"]
