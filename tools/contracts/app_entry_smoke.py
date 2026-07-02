"""Production app-entry smoke proof.

The Streamlit entrypoint must be lazy when imported as a module, but still
execute the real main() sequence when Streamlit runs the file. This contract
uses a clean subprocess with stubbed Streamlit/shell/timing modules so the
proof is runtime-backed without starting a browser or Snowflake session.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

APP_ENTRY_SMOKE_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/app_entry_smoke_results.json"
APP_ENTRY_SMOKE_GATE_REL = f"{LAUNCH_READINESS_DIR}/app_entry_smoke_gate_results.json"

PRODUCER = "app_entry_smoke"
FORBIDDEN_IMPORT_PREFIXES = (
    "streamlit",
    "shell",
    "sections",
    "utils.query",
    "pandas",
)
FORBIDDEN_EVIDENCE_MARKERS = ("evidence_load", "cost_contract_evidence_load")


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git_sha(root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except Exception:
        return ""


def _producer_signature(row: Mapping[str, Any]) -> str:
    import hashlib

    payload = json.dumps(
        {
            "producer": PRODUCER,
            "check": row.get("check"),
            "section": row.get("section", "App Entry"),
            "workflow": row.get("workflow", "Smoke"),
            "passed": row.get("passed"),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _probe_script(app_root: Path) -> str:
    return f"""
import importlib
import json
import sys
import types

sys.path.insert(0, {str(app_root)!r})
before = set(sys.modules)
app = importlib.import_module("app")
after_import = set(sys.modules)

def imported(prefix):
    return sorted(name for name in after_import - before if name == prefix or name.startswith(prefix + "."))

import_row = {{
    "check": "module_import_lazy",
    "imported_streamlit": bool(imported("streamlit")),
    "imported_shell": bool(imported("shell")),
    "imported_section_modules": imported("sections"),
    "imported_query_modules": imported("utils.query"),
    "imported_pandas": bool(imported("pandas")),
    "imported_evidence_loaders": sorted(
        name for name in after_import - before
        if "evidence_load" in name or "cost_contract_evidence_load" in name
    ),
}}

calls = {{"set_page_config": 0, "render_app": 0, "record_app_entry_timings": 0}}
streamlit_stub = types.ModuleType("streamlit")
def set_page_config(**kwargs):
    calls["set_page_config"] += 1
    calls["page_config_kwargs"] = kwargs
streamlit_stub.set_page_config = set_page_config
sys.modules["streamlit"] = streamlit_stub

shell_stub = types.ModuleType("shell")
def render_app():
    calls["render_app"] += 1
shell_stub.render_app = render_app
sys.modules["shell"] = shell_stub

timing_stub = types.ModuleType("app_entry_timing")
def record_app_entry_timings(*args):
    calls["record_app_entry_timings"] += 1
    calls["timing_arg_count"] = len(args)
timing_stub.record_app_entry_timings = record_app_entry_timings
sys.modules["app_entry_timing"] = timing_stub

app.main()
after_main = set(sys.modules)
main_row = {{
    "check": "streamlit_style_main_execution",
    "set_page_config_count": calls["set_page_config"],
    "page_config_kwargs": calls.get("page_config_kwargs", {{}}),
    "render_app_count": calls["render_app"],
    "record_app_entry_timing_count": calls["record_app_entry_timings"],
    "timing_arg_count": calls.get("timing_arg_count", 0),
    "imported_section_modules": sorted(name for name in after_main - after_import if name.startswith("sections.")),
    "imported_query_modules": sorted(name for name in after_main - after_import if name == "utils.query" or name.startswith("utils.query.")),
    "imported_evidence_loaders": sorted(
        name for name in after_main - after_import
        if "evidence_load" in name or "cost_contract_evidence_load" in name
    ),
}}
print(json.dumps({{"rows": [import_row, main_row]}}))
"""


def build_app_entry_smoke_results(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    app_root = root_path / ".overwatch_final"
    commit_sha = _git_sha(root_path)
    proc = subprocess.run(
        [sys.executable, "-c", _probe_script(app_root)],
        cwd=root_path,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    if proc.returncode != 0:
        failures.append({"code": "APP_ENTRY_PROBE_FAILED", "sanitized_error": "App entry smoke subprocess failed."})
    else:
        for line in reversed([line.strip() for line in proc.stdout.splitlines() if line.strip()]):
            if not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            raw_rows = payload.get("rows", [])
            if isinstance(raw_rows, list):
                rows = [dict(row) for row in raw_rows if isinstance(row, dict)]
            break
    if not rows and not failures:
        failures.append({"code": "APP_ENTRY_PROBE_OUTPUT_MISSING", "sanitized_error": "App entry smoke produced no rows."})

    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        check = str(row.get("check") or "")
        failure_reasons: list[str] = []
        if check == "module_import_lazy":
            if row.get("imported_streamlit"):
                failure_reasons.append("importing app imported Streamlit")
            if row.get("imported_shell"):
                failure_reasons.append("importing app imported shell")
            if row.get("imported_section_modules"):
                failure_reasons.append("importing app imported sections")
            if row.get("imported_query_modules"):
                failure_reasons.append("importing app imported query helpers")
            if row.get("imported_pandas"):
                failure_reasons.append("importing app imported pandas")
            if row.get("imported_evidence_loaders"):
                failure_reasons.append("importing app imported evidence loaders")
        elif check == "streamlit_style_main_execution":
            if int(row.get("set_page_config_count") or 0) != 1:
                failure_reasons.append("main did not set page config exactly once")
            if int(row.get("render_app_count") or 0) != 1:
                failure_reasons.append("main did not call render_app exactly once")
            if int(row.get("record_app_entry_timing_count") or 0) != 1:
                failure_reasons.append("main did not record app entry timing exactly once")
            if int(row.get("timing_arg_count") or 0) != 9:
                failure_reasons.append("app entry timing argument contract changed")
            if row.get("imported_section_modules"):
                failure_reasons.append("main imported sections before dispatch")
            if row.get("imported_query_modules"):
                failure_reasons.append("main imported query helpers before dispatch")
            if row.get("imported_evidence_loaders"):
                failure_reasons.append("main imported evidence loaders before dispatch")
        else:
            failure_reasons.append("unknown app entry smoke row")

        normalized = {
            **row,
            "producer": PRODUCER,
            "provenance_origin": "producer",
            "commit_sha": commit_sha,
            "generated_at": _utc_now(),
            "source": "app_entry_smoke",
            "runtime_source": "subprocess_app_entry_probe",
            "section": "App Entry",
            "workflow": "Production startup",
            "raw_sql_included": False,
            "passed": not failure_reasons,
            "failure_reason": "; ".join(failure_reasons),
        }
        normalized["producer_signature"] = _producer_signature(normalized)
        normalized_rows.append(normalized)
        if failure_reasons:
            failures.append({"code": "APP_ENTRY_SMOKE_FAILED", "check": check, "failure_reason": normalized["failure_reason"]})

    return {
        "source": "app_entry_smoke",
        "producer": PRODUCER,
        "generated_at": _utc_now(),
        "commit_sha": commit_sha,
        "passed": not failures,
        "failure_count": len(failures),
        "row_count": len(normalized_rows),
        "rows": normalized_rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_app_entry_smoke_gate(payload: object) -> dict[str, Any]:
    mapped = payload if isinstance(payload, dict) else {}
    failures = list(mapped.get("failures") or [])
    if not mapped:
        failures = [{"code": "APP_ENTRY_SMOKE_RESULTS_MISSING", "failure_reason": "App entry smoke artifact is missing."}]
    elif not bool(mapped.get("passed")) and not failures:
        failures = [{"code": "APP_ENTRY_SMOKE_FAILED", "failure_reason": "App entry smoke failed."}]
    return {
        "source": "app_entry_smoke_gate_results",
        "producer": PRODUCER,
        "generated_at": _utc_now(),
        "passed": not failures and bool(mapped.get("passed")),
        "app_entry_smoke_passed": not failures and bool(mapped.get("passed")),
        "failure_count": len(failures),
        "row_count": int(mapped.get("row_count") or 0),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_app_entry_smoke_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_app_entry_smoke_results(root_path)
    gate = evaluate_app_entry_smoke_gate(results)
    for rel, payload in ((APP_ENTRY_SMOKE_RESULTS_REL, results), (APP_ENTRY_SMOKE_GATE_REL, gate)):
        path = root_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {APP_ENTRY_SMOKE_RESULTS_REL: results, APP_ENTRY_SMOKE_GATE_REL: gate}


if __name__ == "__main__":
    artifacts = write_app_entry_smoke_artifacts(Path("."))
    gate = artifacts[APP_ENTRY_SMOKE_GATE_REL]
    print(json.dumps(gate, indent=2, sort_keys=True))
    raise SystemExit(0 if gate.get("passed") else 1)


__all__ = [
    "APP_ENTRY_SMOKE_GATE_REL",
    "APP_ENTRY_SMOKE_RESULTS_REL",
    "build_app_entry_smoke_results",
    "evaluate_app_entry_smoke_gate",
    "write_app_entry_smoke_artifacts",
]
