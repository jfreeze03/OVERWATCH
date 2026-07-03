"""Static query-boundary lint for release-critical run_query call sites."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
import json
from pathlib import Path
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


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _norm(path: Path) -> str:
    return path.as_posix().replace("\\", "/")


def _is_critical(path: Path, suffixes: Iterable[str] = CRITICAL_QUERY_PATH_SUFFIXES) -> bool:
    normalized = _norm(path)
    return any(normalized.endswith(suffix) for suffix in suffixes)


def _is_run_query_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "run_query"
    if isinstance(func, ast.Attribute):
        return func.attr == "run_query"
    return False


def lint_query_boundary_paths(root: Path | str = ".", *, critical_suffixes: Iterable[str] = CRITICAL_QUERY_PATH_SUFFIXES) -> dict[str, Any]:
    root_path = Path(root).resolve()
    app_root = root_path / ".overwatch_final"
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    scanned_files = 0
    run_query_call_count = 0
    for path in sorted(app_root.rglob("*.py")):
        rel = path.relative_to(root_path)
        if not _is_critical(rel, critical_suffixes):
            continue
        scanned_files += 1
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
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_run_query_call(node):
                continue
            run_query_call_count += 1
            has_boundary = any(keyword.arg == "query_boundary" for keyword in node.keywords)
            row = {
                "file": rel.as_posix(),
                "line": int(getattr(node, "lineno", 0) or 0),
                "call": "run_query",
                "query_boundary_present": has_boundary,
                "passed": has_boundary,
                "failure_reason": "" if has_boundary else "critical run_query call lacks query_boundary",
                "raw_sql_included": False,
            }
            rows.append(row)
            if not has_boundary:
                failures.append({"file": row["file"], "line": row["line"], "failure_reason": row["failure_reason"]})
    return {
        "source": "query_boundary_lint",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "critical_file_count": scanned_files,
        "run_query_call_count": run_query_call_count,
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
        "generated_at": _now(),
        "passed": bool(results.get("passed")),
        "failure_count": int(results.get("failure_count") or 0),
        "missing_query_boundary_count": int(results.get("missing_query_boundary_count") or 0),
        "critical_file_count": int(results.get("critical_file_count") or 0),
        "run_query_call_count": int(results.get("run_query_call_count") or 0),
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
    "lint_query_boundary_paths",
    "write_query_boundary_lint_artifacts",
]
