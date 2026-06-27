"""Static direct-SQL scan for app performance contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


_ADMIN_ALLOWED_TOKENS = (
    "admin",
    "setup",
    "bootstrap",
    "dba_tools",
    "action_queue",
    "alert_catalog",
    "alert_delivery",
    "alert_lifecycle",
    "access_review",
    "history",
    "metadata.py",
    "compatibility.py",
    "cortex.py",
    "logging.py",
    "command_board.py",
    "live_monitor.py",
    "task_management",
    "warehouse_health_setting_panels.py",
)


def _surface_for_path(relative_path: str) -> str:
    path = relative_path.replace("\\", "/").lower()
    if "/sections/" in path:
        return "section"
    if "/utils/" in path:
        return "shared_helper"
    return "other"


def _allowance_for_path(relative_path: str, line: str) -> tuple[bool, str, str]:
    normalized = relative_path.replace("\\", "/").lower()
    if "DIRECT_SQL_ADMIN_OK" in line:
        return True, "explicit_admin_marker", "admin"
    if normalized.endswith(".overwatch_final/direct_sql_contract.py"):
        return True, "static_scanner_self_reference", "runner"
    if normalized.endswith(".overwatch_final/utils/query.py") or normalized.endswith(".overwatch_final/utils/session.py"):
        return True, "central_query_runner_or_guarded_session", "runner"
    if any(token in normalized for token in _ADMIN_ALLOWED_TOKENS):
        return True, "admin_setup_or_action_surface", "admin"
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
        for line_no, line in enumerate(lines, start=1):
            if ".sql(" not in line:
                continue
            allowed, reason, surface = _allowance_for_path(relative, line)
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
