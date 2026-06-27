"""Static direct-SQL scan for app performance contracts."""

from __future__ import annotations

import io
from pathlib import Path
import re
import tokenize
from typing import Iterable


_ADMIN_MARKER = "DIRECT_SQL_ADMIN_OK"
_STRUCTURED_MARKER_RE = re.compile(
    r"boundary=(?P<boundary>[A-Za-z_]+)\s+"
    r"reason=(?P<reason>[A-Za-z0-9_.:-]+)\s+"
    r"budget=(?P<budget>[A-Za-z0-9_.:-]+)\s+"
    r"owner=(?P<owner>[A-Za-z0-9_.:-]+)"
)
_ALLOWED_MARKER_BOUNDARIES = {"admin", "setup_health", "account_usage", "metadata"}
_ALLOWED_MARKER_BUDGETS = {
    "admin_setup",
    "advanced_diagnostics",
    "account_usage_fallback",
    "metadata_probe",
    "query_preview",
}


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


def _structured_marker_nearby(lines: list[str], line_no: int) -> dict[str, object] | None:
    """Return a parsed marker only when it is local to the direct SQL call."""
    start = max(0, line_no - 4)
    for idx in range(line_no - 2, start - 1, -1):
        if idx < 0 or idx >= len(lines):
            continue
        raw = lines[idx]
        if _ADMIN_MARKER not in raw:
            continue
        match = _STRUCTURED_MARKER_RE.search(raw)
        if not match:
            return {
                "marker_line": idx + 1,
                "marker_boundary": "",
                "marker_reason": "",
                "marker_budget": "",
                "marker_owner": "",
                "marker_valid": False,
            }
        boundary = str(match.group("boundary") or "").strip().lower()
        budget = str(match.group("budget") or "").strip()
        owner = str(match.group("owner") or "").strip()
        return {
            "marker_line": idx + 1,
            "marker_boundary": boundary,
            "marker_reason": str(match.group("reason") or "").strip(),
            "marker_budget": budget,
            "marker_owner": owner,
            "marker_valid": (
                boundary in _ALLOWED_MARKER_BOUNDARIES
                and budget in _ALLOWED_MARKER_BUDGETS
                and bool(owner)
            ),
        }
    return None


def _direct_sql_call_lines(text: str) -> list[int]:
    """Return source lines for code-level ``.sql(`` calls, ignoring strings/comments."""
    calls: list[int] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except tokenize.TokenError:
        return []
    useful = [
        token for token in tokens
        if token.type not in {
            tokenize.COMMENT,
            tokenize.NL,
            tokenize.NEWLINE,
            tokenize.INDENT,
            tokenize.DEDENT,
            tokenize.ENCODING,
            tokenize.ENDMARKER,
        }
    ]
    for idx, token in enumerate(useful):
        if token.type != tokenize.NAME or token.string.lower() != "sql":
            continue
        previous = useful[idx - 1] if idx > 0 else None
        following = useful[idx + 1] if idx + 1 < len(useful) else None
        if previous and previous.string == "." and following and following.string == "(":
            calls.append(int(token.start[0]))
    return sorted(set(calls))


def _allowance_for_path(
    relative_path: str,
    lines: list[str],
    line_no: int,
) -> tuple[bool, str, str, dict[str, object]]:
    normalized = relative_path.replace("\\", "/").lower()
    if normalized.endswith(".overwatch_final/direct_sql_contract.py"):
        return True, "static_scanner_self_reference", "runner", {}
    if normalized.endswith(".overwatch_final/utils/query.py") or normalized.endswith(".overwatch_final/utils/session.py"):
        return True, "central_query_runner_or_guarded_session", "runner", {}
    if _is_test_or_deployment_path(normalized):
        return True, "test_or_deployment_fixture", "test", {}
    marker = _structured_marker_nearby(lines, line_no)
    if marker and bool(marker.get("marker_valid")):
        boundary = str(marker.get("marker_boundary") or "admin")
        return True, "local_structured_admin_marker", "admin", marker
    if marker:
        return False, "invalid local DIRECT_SQL_ADMIN_OK marker", _surface_for_path(relative_path), marker
    return False, "missing local structured DIRECT_SQL_ADMIN_OK marker", _surface_for_path(relative_path), {}


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
        for line_no in _direct_sql_call_lines(text):
            allowed, reason, surface, marker = _allowance_for_path(relative, lines, line_no)
            marker_boundary = str(marker.get("marker_boundary") or "")
            findings.append({
                "path": relative,
                "line": line_no,
                "allowed": bool(allowed),
                "reason": reason,
                "surface": surface,
                "boundary": marker_boundary if marker_boundary else ("runner" if surface == "runner" else "test" if surface == "test" else "other"),
                "marker_line": marker.get("marker_line"),
                "marker_boundary": marker_boundary,
                "marker_reason": marker.get("marker_reason", ""),
                "marker_budget": marker.get("marker_budget", ""),
                "marker_owner": marker.get("marker_owner", ""),
                "marker_valid": bool(marker.get("marker_valid", False)) if marker else None,
                "runtime_context_expected": marker.get("marker_budget", "") if marker else "",
                "recommendation": ""
                if allowed
                else (
                    "Use run_query/run_query_or_raise or add a local structured marker: "
                    "# DIRECT_SQL_ADMIN_OK boundary=<admin|setup_health|account_usage|metadata> "
                    "reason=<short_reason> budget=<name> owner=<team_or_surface>."
                ),
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
