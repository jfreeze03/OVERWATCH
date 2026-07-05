"""Static query-boundary lint for release-critical run_query call sites."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable


FULL_APP_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

QUERY_BOUNDARY_LINT_RESULTS_REL = f"{FULL_APP_DIR}/query_boundary_lint_results.json"
QUERY_BOUNDARY_LINT_GATE_REL = f"{LAUNCH_READINESS_DIR}/query_boundary_lint_gate_results.json"

CRITICAL_QUERY_PATH_SUFFIXES = (
    "sections/section_command_brief.py",
    "sections/query_search.py",
    "sections/decision_workspace_target_filters.py",
    "sections/cost_contract_evidence.py",
    "sections/dba_control_room/render.py",
    "sections/security_posture_privilege_sprawl_view.py",
    "utils/action_queue.py",
    "utils/alert_delivery.py",
    "utils/alert_triage.py",
)

SELECTED_TOOL_PATH_SUFFIXES = (
    "tools/contracts/full_app_runtime_validation.py",
    "tools/contracts/performance_budget_gate.py",
    "tools/contracts/first_paint_slo.py",
    "tools/contracts/launch_readiness.py",
    "tools/contracts/production_release_candidate.py",
    "tools/contracts/ci_artifact_reality.py",
    "tools/contracts/ui_system_grade.py",
)

_FALLBACK_ALLOWED_QUERY_BOUNDARIES = {
    "decision_packet",
    "evidence_targeted",
    "query_search_exact",
    "query_search_broad_explicit",
    "setup_admin",
    "live_validation",
    "refresh_fast",
    "refresh_full",
    "export_case",
    "admin_setup_health",
    "explicit_connection_test",
    "metadata_bounded",
}


def _load_allowed_query_boundaries(root: Path) -> set[str]:
    app_boundary_path = root / ".overwatch_final" / "runtime_boundaries.py"
    if app_boundary_path.exists():
        spec = importlib.util.spec_from_file_location("_overwatch_runtime_boundaries", app_boundary_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            boundaries = getattr(module, "APPROVED_RELEASE_EXECUTION_BOUNDARIES", None)
            if boundaries:
                return {str(item) for item in boundaries}
    return set(_FALLBACK_ALLOWED_QUERY_BOUNDARIES)


ALLOWED_QUERY_BOUNDARIES = set(_FALLBACK_ALLOWED_QUERY_BOUNDARIES)

DIRECT_SQL_RELEASE_BLOCKING_SUFFIXES = (
    "app.py",
    "shell.py",
    "navigation.py",
    "route_registry.py",
    "runtime_state.py",
    "section_dispatch.py",
    "access_control.py",
    "filters.py",
    "layout.py",
    "refresh.py",
    "perf_trace.py",
    "performance.py",
    "app_entry_timing.py",
    "workflow_contracts.py",
    "sections/section_command_brief.py",
    "sections/query_search.py",
    "sections/decision_workspace_target_filters.py",
    "sections/cost_contract_evidence.py",
    "sections/dba_control_room/render.py",
    "sections/security_posture_privilege_sprawl_view.py",
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _norm(path: Path) -> str:
    return path.as_posix().replace("\\", "/")


def _is_critical(path: Path, suffixes: Iterable[str] = CRITICAL_QUERY_PATH_SUFFIXES) -> bool:
    normalized = _norm(path)
    return any(normalized.endswith(suffix) for suffix in suffixes)


def _is_direct_sql_release_blocking(path: Path) -> bool:
    normalized = _norm(path)
    return any(normalized.endswith(suffix) for suffix in DIRECT_SQL_RELEASE_BLOCKING_SUFFIXES)


def _selected_scan_files(root: Path) -> list[Path]:
    files = list((root / ".overwatch_final").rglob("*.py"))
    for suffix in SELECTED_TOOL_PATH_SUFFIXES:
        path = root / suffix
        if path.exists() and path.is_file():
            files.append(path)
    return sorted({path.resolve() for path in files})


def _is_selected_tool_file(path: Path) -> bool:
    normalized = _norm(path)
    return any(normalized.endswith(suffix) for suffix in SELECTED_TOOL_PATH_SUFFIXES)


def _run_query_aliases(tree: ast.AST) -> set[str]:
    aliases = {"run_query"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("utils.query"):
            for alias in node.names:
                if alias.name == "run_query":
                    aliases.add(alias.asname or alias.name)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Name):
                continue
            if node.value.id not in aliases:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id not in aliases:
                    aliases.add(target.id)
                    changed = True
    return aliases


def _is_run_query_call(node: ast.Call, aliases: set[str]) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in aliases
    if isinstance(func, ast.Attribute):
        return func.attr == "run_query"
    return False


def _is_session_sql_call(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "sql":
        return False
    value = func.value
    if isinstance(value, ast.Name):
        return value.id in {"session", "sess", "sf_session"}
    if isinstance(value, ast.Attribute):
        return value.attr.lower().endswith("session")
    if isinstance(value, ast.Call):
        inner = value.func
        if isinstance(inner, ast.Name):
            return inner.id == "get_session"
        if isinstance(inner, ast.Attribute):
            return inner.attr == "get_session"
    return False


def _keyword_literal(node: ast.Call, keyword_name: str) -> str:
    for keyword in node.keywords:
        if keyword.arg != keyword_name:
            continue
        value = keyword.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    return ""


def lint_query_boundary_paths(root: Path | str = ".", *, critical_suffixes: Iterable[str] = CRITICAL_QUERY_PATH_SUFFIXES) -> dict[str, Any]:
    root_path = Path(root).resolve()
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    scanned_files = 0
    critical_file_count = 0
    app_file_count = 0
    selected_tool_file_count = 0
    run_query_call_count = 0
    direct_session_sql_call_count = 0
    direct_session_sql_violation_count = 0
    commit_sha = _git_commit(root_path)
    allowed_boundaries = _load_allowed_query_boundaries(root_path)
    for path in _selected_scan_files(root_path):
        rel = path.relative_to(root_path)
        app_file = rel.as_posix().startswith(".overwatch_final/")
        selected_tool_file = _is_selected_tool_file(rel)
        app_file_count += 1 if app_file else 0
        selected_tool_file_count += 1 if selected_tool_file else 0
        critical = _is_critical(rel, critical_suffixes)
        direct_sql_release_blocking = _is_direct_sql_release_blocking(rel)
        scanned_files += 1
        if critical:
            critical_file_count += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(rel))
        except SyntaxError as exc:
            failure = {
                "file": rel.as_posix(),
                "line": int(getattr(exc, "lineno", 0) or 0),
                "failure_reason": "critical query file could not be parsed",
            }
            failures.append(failure)
            rows.append({**failure, "passed": False, "raw_sql_included": False})
            continue
        aliases = _run_query_aliases(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _is_run_query_call(node, aliases):
                run_query_call_count += 1
                boundary_value = _keyword_literal(node, "query_boundary")
                has_boundary = any(keyword.arg == "query_boundary" for keyword in node.keywords)
                invalid_boundary = bool(boundary_value) and boundary_value not in allowed_boundaries
                release_blocking = critical
                reasons: list[str] = []
                if release_blocking and not has_boundary:
                    reasons.append("critical run_query call lacks query_boundary")
                if release_blocking and invalid_boundary:
                    reasons.append(f"critical run_query call uses unapproved query_boundary '{boundary_value}'")
                row = {
                    "file": rel.as_posix(),
                    "line": int(getattr(node, "lineno", 0) or 0),
                    "call": "run_query",
                    "producer": "query_boundary_lint",
                    "producer_signature": "query_boundary_lint::ast_scan",
                    "provenance_origin": "producer",
                    "commit_sha": commit_sha,
                    "app_file": app_file,
                    "selected_tool_file": selected_tool_file,
                    "aliases_detected": sorted(aliases - {"run_query"}),
                    "query_boundary_present": has_boundary,
                    "query_boundary": boundary_value,
                    "release_blocking_path": release_blocking,
                    "passed": not reasons,
                    "failure_reason": "; ".join(reasons),
                    "raw_sql_included": False,
                }
                rows.append(row)
                if reasons:
                    failures.append({"file": row["file"], "line": row["line"], "failure_reason": row["failure_reason"]})
                continue
            if _is_session_sql_call(node):
                direct_session_sql_call_count += 1
                release_blocking = direct_sql_release_blocking
                reason = "direct session.sql call in first-paint/query-critical path" if release_blocking else ""
                row = {
                    "file": rel.as_posix(),
                    "line": int(getattr(node, "lineno", 0) or 0),
                    "call": "session.sql",
                    "producer": "query_boundary_lint",
                    "producer_signature": "query_boundary_lint::ast_scan",
                    "provenance_origin": "producer",
                    "commit_sha": commit_sha,
                    "app_file": app_file,
                    "selected_tool_file": selected_tool_file,
                    "release_blocking_path": release_blocking,
                    "passed": not release_blocking,
                    "failure_reason": reason,
                    "raw_sql_included": False,
                }
                rows.append(row)
                if release_blocking:
                    direct_session_sql_violation_count += 1
                    failures.append({"file": row["file"], "line": row["line"], "failure_reason": reason})
    return {
        "source": "query_boundary_lint",
        "producer": "query_boundary_lint",
        "producer_signature": "query_boundary_lint::v2",
        "provenance_origin": "producer",
        "commit_sha": commit_sha,
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "app_file_count": app_file_count,
        "selected_tool_file_count": selected_tool_file_count,
        "scanned_file_count": scanned_files,
        "critical_file_count": critical_file_count,
        "run_query_call_count": run_query_call_count,
        "direct_session_sql_call_count": direct_session_sql_call_count,
        "direct_session_sql_violation_count": direct_session_sql_violation_count,
        "missing_query_boundary_count": len(failures),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def write_query_boundary_lint_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = lint_query_boundary_paths(root_path)
    gate = {
        "source": "query_boundary_lint_gate",
        "producer": "query_boundary_lint",
        "producer_signature": "query_boundary_lint_gate::v2",
        "provenance_origin": "producer",
        "commit_sha": str(results.get("commit_sha") or ""),
        "generated_at": _now(),
        "passed": bool(results.get("passed")),
        "failure_count": int(results.get("failure_count") or 0),
        "missing_query_boundary_count": int(results.get("missing_query_boundary_count") or 0),
        "critical_file_count": int(results.get("critical_file_count") or 0),
        "selected_tool_file_count": int(results.get("selected_tool_file_count") or 0),
        "scanned_file_count": int(results.get("scanned_file_count") or 0),
        "app_file_count": int(results.get("app_file_count") or 0),
        "run_query_call_count": int(results.get("run_query_call_count") or 0),
        "direct_session_sql_call_count": int(results.get("direct_session_sql_call_count") or 0),
        "direct_session_sql_violation_count": int(results.get("direct_session_sql_violation_count") or 0),
        "rows": results.get("rows", []),
        "failures": results.get("failures", []),
        "raw_sql_included": False,
    }
    _write_json(root_path / QUERY_BOUNDARY_LINT_RESULTS_REL, results)
    _write_json(root_path / QUERY_BOUNDARY_LINT_GATE_REL, gate)
    return {
        QUERY_BOUNDARY_LINT_RESULTS_REL: results,
        QUERY_BOUNDARY_LINT_GATE_REL: gate,
    }


if __name__ == "__main__":
    artifacts = write_query_boundary_lint_artifacts(Path("."))
    if not bool(artifacts[QUERY_BOUNDARY_LINT_GATE_REL].get("passed")):
        raise SystemExit(1)


__all__ = [
    "QUERY_BOUNDARY_LINT_GATE_REL",
    "QUERY_BOUNDARY_LINT_RESULTS_REL",
    "ALLOWED_QUERY_BOUNDARIES",
    "lint_query_boundary_paths",
    "write_query_boundary_lint_artifacts",
]
