"""Static direct-SQL scan for app performance contracts."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable


_DIRECT_SQL_RE = re.compile(r"(?:\bget_session\s*\(\s*\)|\b[a-zA-Z_][a-zA-Z0-9_]*|\))\s*\.\s*sql\s*\(", re.IGNORECASE)
_ADMIN_MARKER = "DIRECT_SQL_ADMIN_OK"


def _surface_for_path(relative_path: str) -> str:
    path = relative_path.replace("\\", "/").lower()
    if "/sections/" in path:
        return "section"
    if "/utils/" in path:
        return "shared_helper"
    return "other"


def _is_test_or_deployment_path(normalized: str) -> bool:
    return (
        normalized.startswith("tests/")
        or "/tests/" in normalized
        or normalized.startswith("deployment/")
        or "/deployment/" in normalized
        or normalized.startswith("scripts/")
        or "/scripts/" in normalized
    )


def _line_no_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, max(offset, 0)) + 1


def _has_admin_marker(lines: list[str], line_no: int) -> bool:
    start = max(0, line_no - 5)
    nearby = lines[start:line_no]
    if any(_ADMIN_MARKER in line for line in nearby):
        return True
    header = lines[:20]
    return any(_ADMIN_MARKER in line for line in header)


def _allowance_for_path(relative_path: str, lines: list[str], line_no: int) -> tuple[bool, str, str]:
    normalized = relative_path.replace("\\", "/").lower()
    if normalized.endswith(".overwatch_final/direct_sql_contract.py"):
        return True, "static_scanner_self_reference", "runner"
    if normalized.endswith(".overwatch_final/utils/query.py") or normalized.endswith(".overwatch_final/utils/session.py"):
        return True, "central_query_runner_or_guarded_session", "runner"
    if _is_test_or_deployment_path(normalized):
        return True, "test_or_deployment_fixture", "test"
    if _has_admin_marker(lines, line_no):
        return True, "explicit_admin_marker", "admin"
    return False, "unallowlisted direct session.sql", _surface_for_path(relative_path)


def scan_direct_sql_usage(
    paths: Iterable[Path],
    *,
    root: Path,
) -> list[dict[str, object]]:
    """Return SQL-free findings for direct ``session.sql`` usage."""
    findings: list[dict[str, object]] = []
    root = Path(root)
    for path in paths:
        path = Path(path)
        if not path.exists() or path.suffix.lower() != ".py":
            continue
        try:
            relative = str(path.relative_to(root))
        except ValueError:
            relative = str(path)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            lines = path.read_text(errors="ignore").splitlines()
        text = "\n".join(lines)
        for match in _DIRECT_SQL_RE.finditer(text):
            line_no = _line_no_for_offset(text, match.start())
            if line_no <= len(lines) and lines[line_no - 1].lstrip().startswith("#"):
                continue
            allowed, reason, surface = _allowance_for_path(relative, lines, line_no)
            findings.append({
                "path": relative,
                "line": line_no,
                "allowed": bool(allowed),
                "reason": reason,
                "surface": surface,
                "boundary": "admin" if allowed and surface == "admin" else "other",
                "recommendation": ""
                if allowed
                else "Use run_query/run_query_or_raise or move direct SQL behind an explicit admin/setup action.",
            })
    return findings


def direct_sql_scan_artifact(findings: list[dict[str, object]], scanned_files: Iterable[Path], *, root: Path) -> dict[str, object]:
    scanned: list[str] = []
    for path in scanned_files:
        try:
            scanned.append(str(Path(path).relative_to(root)))
        except ValueError:
            scanned.append(str(path))
    return {
        "scanned_files": sorted(set(scanned)),
        "findings": findings,
        "blocked_count": sum(1 for finding in findings if not bool(finding.get("allowed"))),
        "raw_sql_included": False,
    }


__all__ = ["direct_sql_scan_artifact", "scan_direct_sql_usage"]
