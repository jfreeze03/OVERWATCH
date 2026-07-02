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
import subprocess
import sys
from typing import Any, Iterable


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

IMPORT_LAZINESS_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/import_laziness_results.json"
RUNTIME_IMPORT_GRAPH_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/runtime_import_graph_results.json"
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

RUNTIME_TRANSITIVE_PANDAS_ALLOWLIST = {
    "shell": {
        "owner": "Streamlit shell",
        "reason": "Streamlit imports pandas transitively; shell does not directly import pandas or dataframes.",
    },
    "layout": {
        "owner": "Streamlit shell",
        "reason": "Streamlit imports pandas transitively; layout does not directly import pandas or dataframes.",
    },
}


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


def _module_import_name(module_name: str) -> str:
    return Path(module_name).stem


def _probe_runtime_import(root_path: Path, module_name: str) -> dict[str, Any]:
    module = _module_import_name(module_name)
    probe = r"""
from pathlib import Path
import importlib
import json
import sys
import time

root = Path(sys.argv[1]).resolve()
app_root = root / ".overwatch_final"
module = sys.argv[2]
sys.path.insert(0, str(app_root))
sys.path.insert(0, str(root))
before = set(sys.modules)
started = time.perf_counter()
error = ""
try:
    importlib.import_module(module)
except BaseException as exc:
    error = f"{type(exc).__name__}: {exc}"
elapsed_ms = int((time.perf_counter() - started) * 1000)
after = set(sys.modules) - before
payload = {
    "module": module,
    "import_error": error,
    "elapsed_ms": elapsed_ms,
    "imported_section_modules": sorted(name for name in after if name == "sections" or name.startswith("sections.")),
    "imported_query_modules": sorted(name for name in after if name == "utils.query" or name.startswith("utils.query.")),
    "imported_pandas": any(name == "pandas" or name.startswith("pandas.") for name in after),
    "imported_account_usage_helpers": sorted(name for name in after if "account_usage" in name.lower()),
    "imported_evidence_loaders": sorted(
        name for name in after
        if (name == "sections" or name.startswith("sections."))
        and ("evidence" in name.lower() or "loader" in name.lower())
    ),
}
print(json.dumps(payload, sort_keys=True))
"""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", probe, str(root_path), module],
            cwd=str(root_path),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "module": module,
            "import_error": "timeout",
            "elapsed_ms": 30000,
            "imported_section_modules": [],
            "imported_query_modules": [],
            "imported_pandas": False,
            "imported_account_usage_helpers": [],
            "imported_evidence_loaders": [],
        }
    stdout_lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    payload: dict[str, Any] = {}
    for line in reversed(stdout_lines):
        if line.startswith("{") and line.endswith("}"):
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                payload = parsed
                break
    if not payload:
        payload = {
            "module": module,
            "import_error": "runtime import probe produced no JSON",
            "elapsed_ms": 0,
            "imported_section_modules": [],
            "imported_query_modules": [],
            "imported_pandas": False,
            "imported_account_usage_helpers": [],
            "imported_evidence_loaders": [],
        }
    if proc.returncode not in (0, None) and not payload.get("import_error"):
        payload["import_error"] = f"probe exited with code {proc.returncode}"
    return payload


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


def build_runtime_import_graph_results(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for module_name in ROOT_MODULES:
        module = _module_import_name(module_name)
        probed = _probe_runtime_import(root_path, module_name)
        section_modules = list(probed.get("imported_section_modules") or [])
        query_modules = list(probed.get("imported_query_modules") or [])
        account_usage_helpers = list(probed.get("imported_account_usage_helpers") or [])
        evidence_loaders = list(probed.get("imported_evidence_loaders") or [])
        imported_pandas = bool(probed.get("imported_pandas"))
        pandas_allowance = RUNTIME_TRANSITIVE_PANDAS_ALLOWLIST.get(module) if imported_pandas else None
        failure_reasons: list[str] = []
        if probed.get("import_error"):
            failure_reasons.append("runtime import failed")
        if section_modules:
            failure_reasons.append("runtime import pulled section modules")
        if query_modules:
            failure_reasons.append("runtime import pulled query modules")
        if account_usage_helpers:
            failure_reasons.append("runtime import pulled Account Usage helpers")
        if evidence_loaders:
            failure_reasons.append("runtime import pulled evidence loaders")
        if imported_pandas and not pandas_allowance:
            failure_reasons.append("runtime import pulled pandas without allowlist")
        row = {
            "module": module,
            "source_file": module_name,
            "imported_section_modules": section_modules,
            "imported_query_modules": query_modules,
            "imported_pandas": imported_pandas,
            "pandas_import_allowed": bool(pandas_allowance),
            "pandas_import_owner": str((pandas_allowance or {}).get("owner") or ""),
            "pandas_import_reason": str((pandas_allowance or {}).get("reason") or ""),
            "imported_account_usage_helpers": account_usage_helpers,
            "imported_evidence_loaders": evidence_loaders,
            "elapsed_ms": int(probed.get("elapsed_ms") or 0),
            "passed": not failure_reasons,
            "failure_reason": "; ".join(failure_reasons),
            "raw_sql_included": False,
        }
        rows.append(row)
        if failure_reasons:
            failures.append(
                {
                    "module": module,
                    "source_file": module_name,
                    "reason": row["failure_reason"],
                    "import_error": str(probed.get("import_error") or ""),
                }
            )
    return {
        "source": "runtime_import_graph_results",
        "proof_source": "runtime_root_import_graph",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "module_count": len(rows),
        "runtime_import_graph_failure_count": len(failures),
        "runtime_section_import_count": sum(len(row["imported_section_modules"]) for row in rows),
        "runtime_query_import_count": sum(len(row["imported_query_modules"]) for row in rows),
        "runtime_account_usage_import_count": sum(len(row["imported_account_usage_helpers"]) for row in rows),
        "runtime_evidence_loader_import_count": sum(len(row["imported_evidence_loaders"]) for row in rows),
        "runtime_unallowed_pandas_import_count": sum(
            1 for row in rows if row["imported_pandas"] and not row["pandas_import_allowed"]
        ),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_import_laziness_gate(results: object, runtime_results: object | None = None) -> dict[str, Any]:
    payload = results if isinstance(results, dict) else {}
    runtime_payload = runtime_results if isinstance(runtime_results, dict) else {}
    failures = list(payload.get("failures") or [])
    if not payload:
        failures = [{"code": "IMPORT_LAZINESS_RESULTS_MISSING", "reason": "import laziness artifact is missing"}]
    elif not bool(payload.get("passed")) and not failures:
        failures = [{"code": "IMPORT_LAZINESS_FAILED", "reason": "root import laziness failed"}]
    runtime_failures = list(runtime_payload.get("failures") or [])
    if runtime_results is not None:
        if not runtime_payload:
            runtime_failures = [
                {"code": "RUNTIME_IMPORT_GRAPH_RESULTS_MISSING", "reason": "runtime import graph artifact is missing"}
            ]
        elif not bool(runtime_payload.get("passed")) and not runtime_failures:
            runtime_failures = [{"code": "RUNTIME_IMPORT_GRAPH_FAILED", "reason": "runtime import graph failed"}]
    failures.extend(runtime_failures)
    return {
        "source": "import_laziness_gate_results",
        "proof_source": "static_and_runtime_root_import_graph",
        "generated_at": _now(),
        "passed": (
            not failures
            and bool(payload.get("passed", False))
            and (runtime_results is None or bool(runtime_payload.get("passed", False)))
        ),
        "failure_count": len(failures),
        "module_count": int(payload.get("module_count") or 0),
        "runtime_module_count": int(runtime_payload.get("module_count") or 0),
        "import_laziness_failure_count": len(list(payload.get("failures") or [])),
        "runtime_import_graph_failure_count": len(runtime_failures),
        "top_level_section_import_count": int(payload.get("top_level_section_import_count") or 0),
        "top_level_query_import_count": int(payload.get("top_level_query_import_count") or 0),
        "top_level_account_usage_import_count": int(payload.get("top_level_account_usage_import_count") or 0),
        "top_level_heavy_import_count": int(payload.get("top_level_heavy_import_count") or 0),
        "runtime_section_import_count": int(runtime_payload.get("runtime_section_import_count") or 0),
        "runtime_query_import_count": int(runtime_payload.get("runtime_query_import_count") or 0),
        "runtime_account_usage_import_count": int(runtime_payload.get("runtime_account_usage_import_count") or 0),
        "runtime_evidence_loader_import_count": int(runtime_payload.get("runtime_evidence_loader_import_count") or 0),
        "runtime_unallowed_pandas_import_count": int(runtime_payload.get("runtime_unallowed_pandas_import_count") or 0),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_import_laziness_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_import_laziness_results(root_path)
    runtime_results = build_runtime_import_graph_results(root_path)
    gate = evaluate_import_laziness_gate(results, runtime_results)
    _write_json(root_path / IMPORT_LAZINESS_RESULTS_REL, results)
    _write_json(root_path / RUNTIME_IMPORT_GRAPH_RESULTS_REL, runtime_results)
    _write_json(root_path / IMPORT_LAZINESS_GATE_REL, gate)
    return {
        IMPORT_LAZINESS_RESULTS_REL: results,
        RUNTIME_IMPORT_GRAPH_RESULTS_REL: runtime_results,
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
    "RUNTIME_IMPORT_GRAPH_RESULTS_REL",
    "build_import_laziness_results",
    "build_runtime_import_graph_results",
    "evaluate_import_laziness_gate",
    "write_import_laziness_artifacts",
]
