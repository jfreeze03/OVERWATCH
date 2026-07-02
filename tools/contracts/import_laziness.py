"""Root import laziness contract for the Streamlit shell.

The app shell is allowed to import lightweight shell/state helpers at module
load, but section modules, evidence loaders, query runners, and live Snowflake
helpers must stay behind explicit dispatch or action boundaries.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Iterable


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

IMPORT_LAZINESS_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/import_laziness_results.json"
IMPORT_LAZINESS_GATE_REL = f"{LAUNCH_READINESS_DIR}/import_laziness_gate_results.json"

ROOT_MODULES = (
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
    "version.py",
    "workflow_contracts.py",
)

FORBIDDEN_TOP_LEVEL_MODULES = (
    "sections",
    "utils.query",
    "pandas",
)

FORBIDDEN_SYMBOL_FRAGMENTS = (
    "run_query",
    "account_usage",
    "evidence_loader",
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _top_level_imports(tree: ast.Module) -> Iterable[dict[str, Any]]:
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield {
                    "module": alias.name,
                    "symbol": "",
                    "alias": alias.asname or "",
                    "line": node.lineno,
                    "import_kind": "import",
                }
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            for alias in node.names:
                yield {
                    "module": module,
                    "symbol": alias.name,
                    "alias": alias.asname or "",
                    "line": node.lineno,
                    "import_kind": "from",
                }


def _module_is_forbidden(module: str) -> bool:
    normalized = module.lstrip(".")
    return any(normalized == forbidden or normalized.startswith(f"{forbidden}.") for forbidden in FORBIDDEN_TOP_LEVEL_MODULES)


def _symbol_is_forbidden(symbol: str) -> bool:
    lowered = symbol.lower()
    return any(fragment in lowered for fragment in FORBIDDEN_SYMBOL_FRAGMENTS)


def build_import_laziness_results(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    app_root = root_path / ".overwatch_final"
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for module_name in ROOT_MODULES:
        path = app_root / module_name
        row: dict[str, Any] = {
            "module": module_name,
            "path": str(path.relative_to(root_path)).replace("\\", "/") if path.exists() else f".overwatch_final/{module_name}",
            "owner": "Streamlit shell",
            "purpose": "Root shell import boundary",
            "imported_modules": [],
            "top_level_section_import_count": 0,
            "top_level_query_import_count": 0,
            "top_level_account_usage_import_count": 0,
            "top_level_heavy_import_count": 0,
            "passed": True,
            "failure_reason": "",
            "raw_sql_included": False,
        }
        if not path.exists():
            row["passed"] = False
            row["failure_reason"] = "root module missing"
            failures.append({"module": module_name, "reason": row["failure_reason"]})
            rows.append(row)
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module_failures: list[str] = []
        imports = list(_top_level_imports(tree))
        row["imported_modules"] = imports
        for item in imports:
            imported_module = str(item.get("module") or "")
            symbol = str(item.get("symbol") or "")
            normalized_module = imported_module.lstrip(".")
            if _module_is_forbidden(imported_module):
                if normalized_module == "pandas":
                    row["top_level_heavy_import_count"] += 1
                    module_failures.append("heavy pandas import at root module load")
                elif normalized_module == "utils.query":
                    row["top_level_query_import_count"] += 1
                    module_failures.append("query helper import at root module load")
                else:
                    row["top_level_section_import_count"] += 1
                    module_failures.append("section module import at root module load")
            if _symbol_is_forbidden(symbol):
                if "account_usage" in symbol.lower():
                    row["top_level_account_usage_import_count"] += 1
                    module_failures.append("Account Usage helper import at root module load")
                else:
                    row["top_level_query_import_count"] += 1
                    module_failures.append("query/evidence helper import at root module load")
        row["passed"] = not module_failures
        row["failure_reason"] = "; ".join(dict.fromkeys(module_failures))
        if module_failures:
            failures.append(
                {
                    "module": module_name,
                    "reason": row["failure_reason"],
                    "imported_modules": imports,
                }
            )
        rows.append(row)
    return {
        "source": "import_laziness_results",
        "proof_source": "static_root_import_graph",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "module_count": len(rows),
        "root_modules_checked": list(ROOT_MODULES),
        "top_level_section_import_count": sum(int(row["top_level_section_import_count"]) for row in rows),
        "top_level_query_import_count": sum(int(row["top_level_query_import_count"]) for row in rows),
        "top_level_account_usage_import_count": sum(int(row["top_level_account_usage_import_count"]) for row in rows),
        "top_level_heavy_import_count": sum(int(row["top_level_heavy_import_count"]) for row in rows),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_import_laziness_gate(results: object) -> dict[str, Any]:
    payload = results if isinstance(results, dict) else {}
    failures = list(payload.get("failures") or [])
    if not payload:
        failures = [{"code": "IMPORT_LAZINESS_RESULTS_MISSING", "reason": "import laziness artifact is missing"}]
    elif not bool(payload.get("passed")) and not failures:
        failures = [{"code": "IMPORT_LAZINESS_FAILED", "reason": "root import laziness failed"}]
    return {
        "source": "import_laziness_gate_results",
        "proof_source": "static_root_import_graph",
        "generated_at": _now(),
        "passed": not failures and bool(payload.get("passed", False)),
        "failure_count": len(failures),
        "module_count": int(payload.get("module_count") or 0),
        "import_laziness_failure_count": len(failures),
        "top_level_section_import_count": int(payload.get("top_level_section_import_count") or 0),
        "top_level_query_import_count": int(payload.get("top_level_query_import_count") or 0),
        "top_level_account_usage_import_count": int(payload.get("top_level_account_usage_import_count") or 0),
        "top_level_heavy_import_count": int(payload.get("top_level_heavy_import_count") or 0),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_import_laziness_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_import_laziness_results(root_path)
    gate = evaluate_import_laziness_gate(results)
    _write_json(root_path / IMPORT_LAZINESS_RESULTS_REL, results)
    _write_json(root_path / IMPORT_LAZINESS_GATE_REL, gate)
    return {
        IMPORT_LAZINESS_RESULTS_REL: results,
        IMPORT_LAZINESS_GATE_REL: gate,
    }


if __name__ == "__main__":
    artifacts = write_import_laziness_artifacts(Path("."))
    if not bool(artifacts[IMPORT_LAZINESS_GATE_REL].get("passed")):
        raise SystemExit(1)


__all__ = [
    "IMPORT_LAZINESS_GATE_REL",
    "IMPORT_LAZINESS_RESULTS_REL",
    "ROOT_MODULES",
    "build_import_laziness_results",
    "evaluate_import_laziness_gate",
    "write_import_laziness_artifacts",
]
