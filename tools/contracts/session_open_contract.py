"""Static Snowflake session-open scan for first-paint and route safety."""

from __future__ import annotations

import io
from pathlib import Path
import re
import tokenize
import ast
from typing import Iterable

from contracts.session_open_allowlist import SESSION_OPEN_ALLOWLIST


_MARKER = "SESSION_OPEN" + "_ADMIN_OK"
_MARKER_RE = re.compile(
    r"boundary=(?P<boundary>[A-Za-z_]+)\s+"
    r"reason=(?P<reason>[A-Za-z0-9_.:-]+)\s+"
    r"budget=(?P<budget>[A-Za-z0-9_.:-]+)\s+"
    r"owner=(?P<owner>[A-Za-z0-9_.:-]+)"
)
_ALLOWED_BOUNDARIES = {"admin", "setup_health", "account_usage", "metadata", "advanced_diagnostics"}
_ALLOWED_BUDGETS = {"admin_setup", "advanced_diagnostics", "account_usage_fallback", "metadata_probe"}
_CENTRAL_FILES = {
    ".overwatch_final/utils/query.py",
    ".overwatch_final/utils/session.py",
    "tools/contracts/session_open_contract.py",
}
_PRIMARY_SURFACE_PATTERNS = (
    ".overwatch_final/sections/executive",
    ".overwatch_final/sections/dba_control_room",
    ".overwatch_final/sections/alert_center",
    ".overwatch_final/sections/cost_contract",
    ".overwatch_final/sections/query_search.py",
    ".overwatch_final/sections/workload_operations",
    ".overwatch_final/sections/security_posture",
    ".overwatch_final/route_registry.py",
)


def _is_test_or_deployment_path(normalized: str) -> bool:
    return (
        normalized.startswith("tests/")
        or "/tests/" in normalized
        or normalized.startswith("deployment/")
        or "/deployment/" in normalized
        or normalized.startswith("scripts/")
        or "/scripts/" in normalized
    )


def _structured_marker_nearby(lines: list[str], line_no: int) -> dict[str, object] | None:
    start = max(0, line_no - 4)
    for idx in range(line_no - 2, start - 1, -1):
        if idx < 0 or idx >= len(lines):
            continue
        raw = lines[idx]
        if _MARKER not in raw:
            continue
        match = _MARKER_RE.search(raw)
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
            "marker_valid": boundary in _ALLOWED_BOUNDARIES and budget in _ALLOWED_BUDGETS and bool(owner),
        }
    return None


def _function_for_line(text: str, line_no: int) -> str:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return "<module>"
    selected = ("<module>", 0)

    class _Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            nonlocal selected
            end_lineno = int(getattr(node, "end_lineno", node.lineno) or node.lineno)
            if int(node.lineno) <= line_no <= end_lineno and int(node.lineno) >= selected[1]:
                selected = (str(node.name), int(node.lineno))
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            nonlocal selected
            end_lineno = int(getattr(node, "end_lineno", node.lineno) or node.lineno)
            if int(node.lineno) <= line_no <= end_lineno and int(node.lineno) >= selected[1]:
                selected = (str(node.name), int(node.lineno))
            self.generic_visit(node)

    _Visitor().visit(tree)
    return selected[0]


def _session_open_calls(text: str) -> list[dict[str, object]]:
    try:
        tokens = [
            token for token in tokenize.generate_tokens(io.StringIO(text).readline)
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
    except tokenize.TokenError:
        return []
    calls: list[dict[str, object]] = []
    for idx, token in enumerate(tokens):
        following = tokens[idx + 1] if idx + 1 < len(tokens) else None
        previous = tokens[idx - 1] if idx > 0 else None
        name = token.string
        if token.type == tokenize.NAME and name in {"get_session", "_make_session", "make_session"}:
            if following and following.string == "(":
                calls.append({"line": int(token.start[0]), "call_type": name})
        if token.type == tokenize.NAME and name == "Session":
            dot = tokens[idx + 1] if idx + 1 < len(tokens) else None
            builder = tokens[idx + 2] if idx + 2 < len(tokens) else None
            if dot and dot.string == "." and builder and builder.string == "builder":
                calls.append({"line": int(token.start[0]), "call_type": "Session.builder"})
        if token.type == tokenize.NAME and name == "connection" and previous and previous.string == ".":
            owner = tokens[idx - 2] if idx >= 2 else None
            if owner and owner.string == "st" and following and following.string == "(":
                calls.append({"line": int(token.start[0]), "call_type": "st.connection"})
        if token.type == tokenize.NAME and name == "session" and previous and previous.string == ".":
            if following and following.string == "(":
                calls.append({"line": int(token.start[0]), "call_type": ".session()"})
        if token.type == tokenize.NAME and name == "action_session_factory":
            if following and following.string == "(":
                calls.append({"line": int(token.start[0]), "call_type": "action_session_factory"})
    return sorted(calls, key=lambda item: (int(str(item["line"])), str(item["call_type"])))


def _is_primary_surface(normalized: str) -> bool:
    return any(pattern in normalized for pattern in _PRIMARY_SURFACE_PATTERNS)


def _registry_allowance(relative_path: str, function_name: str, call_type: str) -> dict[str, object] | None:
    normalized = relative_path.replace("\\", "/")
    for entry in SESSION_OPEN_ALLOWLIST:
        if str(entry.get("module") or "") != normalized:
            continue
        if str(entry.get("function") or "") != str(function_name or ""):
            continue
        expected_call = str(entry.get("call_type") or "")
        if expected_call and expected_call != str(call_type or ""):
            continue
        return dict(entry)
    return None


def _allowance_for_path(
    relative_path: str,
    lines: list[str],
    line_no: int,
    function_name: str,
    call_type: str,
) -> tuple[bool, str, str, dict[str, object]]:
    normalized = relative_path.replace("\\", "/").lower()
    if normalized in _CENTRAL_FILES:
        return True, "central_query_runner_or_session_utility", "runner", {}
    if _is_test_or_deployment_path(normalized):
        return True, "test_or_deployment_fixture", "test", {}
    registry = _registry_allowance(relative_path, function_name, call_type)
    if registry:
        return True, "sidecar_contract_registry", "admin", {
            "marker_line": None,
            "marker_boundary": registry.get("boundary", ""),
            "marker_reason": registry.get("reason", ""),
            "marker_budget": registry.get("budget", ""),
            "marker_owner": registry.get("owner", ""),
            "marker_valid": True,
            "expected_runtime_context": registry.get("expected_runtime_context", registry.get("budget", "")),
            "registry_function": registry.get("function", ""),
        }
    marker = _structured_marker_nearby(lines, line_no)
    if marker and bool(marker.get("marker_valid")):
        return True, "local_structured_session_marker", "admin", marker
    if marker:
        return False, "invalid local structured session marker", "primary" if _is_primary_surface(normalized) else "helper", marker
    if _is_primary_surface(normalized):
        return False, "unmarked primary-surface session open", "primary", {}
    return False, "unmarked helper session open", "helper", {}


def scan_session_open_usage(paths: Iterable[Path], *, root: Path) -> list[dict[str, object]]:
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
        calls = _session_open_calls("\n".join(lines))
        text = "\n".join(lines)
        for call in calls:
            line_no = int(str(call["line"]))
            function_name = _function_for_line(text, line_no)
            call_type = str(call["call_type"])
            allowed, reason, surface, marker = _allowance_for_path(
                relative,
                lines,
                line_no,
                function_name,
                call_type,
            )
            findings.append({
                "path": relative,
                "line": line_no,
                "function": function_name,
                "call_type": call_type,
                "allowed": bool(allowed),
                "reason": reason,
                "surface": surface,
                "marker_line": marker.get("marker_line"),
                "marker_boundary": marker.get("marker_boundary", ""),
                "marker_reason": marker.get("marker_reason", ""),
                "marker_budget": marker.get("marker_budget", ""),
                "marker_owner": marker.get("marker_owner", ""),
                "runtime_context_expected": marker.get("expected_runtime_context", marker.get("marker_budget", "")) if marker else "",
                "recommendation": ""
                if allowed
                else (
                    "Use run_query/run_query_or_raise, defer session creation until an explicit click, "
                    "or add a local structured marker: "
                    f"# {_MARKER} boundary=<admin|setup_health|account_usage|metadata> "
                    "reason=<short_reason> budget=<name> owner=<team_or_surface>."
                ),
            })
    return findings


def session_open_scan_artifact(findings: list[dict[str, object]], scanned_files: Iterable[Path], *, root: Path) -> dict[str, object]:
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
        "credentials_included": False,
    }


__all__ = ["scan_session_open_usage", "session_open_scan_artifact"]
