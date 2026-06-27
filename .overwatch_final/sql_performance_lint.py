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
        if "CALL SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS('')" in fast_body:
            add("FAST_IMPL_SHARED_CORE_CALL", "error", "FAST_IMPL must not call the shared full-heavy command brief procedure.")
        if re.search(r"\b(14|30|60|90)\b", fast_body):
            add("FAST_IMPL_FULL_WINDOW", "error", "FAST_IMPL must not contain full-only windows.")
    for match in re.finditer(r"\bFROM\s+SNOWFLAKE\.ACCOUNT_USAGE\.[A-Z0-9_]+", upper):
        window = upper[match.start():match.start() + 1200]
        has_bound = bool(
            re.search(
                r"\b(DATEADD|CURRENT_DATE|CURRENT_TIMESTAMP|START_TIME|END_TIME|USAGE_DATE|QUERY_START_TIME|SNAPSHOT_DATE|LOGIN_DATE|COMPLETED_TIME|SCHEDULED_TIME)\b",
                window,
            )
        )
        if not has_bound and "LIMIT" not in window:
            add("ACCOUNT_USAGE_UNBOUNDED", "error", "Account Usage reads must be time-bounded or row-bounded.")
    if "EVIDENCE_QUERY" in upper and re.search(r"\b(CALL|EXECUTE IMMEDIATE)\b[\s\S]{0,120}EVIDENCE_QUERY", upper):
        add("EXECUTABLE_EVIDENCE_QUERY", "error", "Packet EVIDENCE_QUERY must never be executable SQL.")
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
