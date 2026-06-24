#!/usr/bin/env python
"""Measure cold import times for OVERWATCH shell and section modules."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import statistics
import subprocess
import sys
import time
import uuid


PERF_ROOT = pathlib.Path(__file__).resolve().parent
REPO_ROOT = PERF_ROOT.parent
APP_ROOT = REPO_ROOT / ".overwatch_final"
DEFAULT_OUTPUT_DIR = PERF_ROOT / "results"
DEFAULT_MODULES = (
    "shell",
    "section_dispatch",
    "sections.executive_landing_shell",
    "sections.dba_control_room",
    "sections.alert_center",
    "sections.cost_contract",
    "sections.workload_operations",
    "sections.security_posture",
)


def _default_run_id() -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"IMPORT_TIMING_{stamp}_{uuid.uuid4().hex[:6]}"


def _time_module_import(module: str, *, timeout_sec: float) -> dict[str, object]:
    code = (
        "import importlib, json, pathlib, sys, time\n"
        f"sys.path.insert(0, {str(APP_ROOT)!r})\n"
        f"module_name = {module!r}\n"
        "started = time.perf_counter()\n"
        "ok = True\n"
        "error = ''\n"
        "try:\n"
        "    importlib.import_module(module_name)\n"
        "except Exception as exc:\n"
        "    ok = False\n"
        "    error = str(exc).replace('\\n', ' ')[:500]\n"
        "elapsed_ms = (time.perf_counter() - started) * 1000\n"
        "print(json.dumps({'module': module_name, 'ok': ok, 'elapsed_ms': round(elapsed_ms, 2), 'error': error}))\n"
    )
    started = time.perf_counter()
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )
    wall_ms = (time.perf_counter() - started) * 1000
    stdout_lines = [line for line in result.stdout.splitlines() if line.strip()]
    if result.returncode == 0 and stdout_lines:
        try:
            row = json.loads(stdout_lines[-1])
            row["process_wall_ms"] = round(wall_ms, 2)
            row["returncode"] = result.returncode
            row["stderr"] = result.stderr[-1000:]
            return row
        except json.JSONDecodeError:
            pass
    return {
        "module": module,
        "ok": False,
        "elapsed_ms": round(wall_ms, 2),
        "process_wall_ms": round(wall_ms, 2),
        "returncode": result.returncode,
        "error": (result.stderr or result.stdout or "import timing subprocess failed")[-1000:],
        "stderr": result.stderr[-1000:],
    }


def run_import_timing(modules: list[str], *, timeout_sec: float = 30.0) -> dict[str, object]:
    rows = [_time_module_import(module, timeout_sec=timeout_sec) for module in modules]
    elapsed = [float(row.get("elapsed_ms", 0) or 0) for row in rows if row.get("ok")]
    slowest = sorted(rows, key=lambda row: float(row.get("elapsed_ms", 0) or 0), reverse=True)
    return {
        "modules": rows,
        "summary": {
            "module_count": len(rows),
            "ok": sum(1 for row in rows if row.get("ok")),
            "failed": sum(1 for row in rows if not row.get("ok")),
            "max_ms": round(max(elapsed), 2) if elapsed else 0.0,
            "avg_ms": round(statistics.mean(elapsed), 2) if elapsed else 0.0,
            "slowest_module": str(slowest[0].get("module")) if slowest else "",
            "slowest_ms": round(float(slowest[0].get("elapsed_ms", 0) or 0), 2) if slowest else 0.0,
        },
    }


def write_reports(payload: dict[str, object], *, run_id: str, output_dir: str | pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    output = pathlib.Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    created_at = dt.datetime.now(dt.timezone.utc).isoformat()
    payload = {
        "run_id": run_id,
        "created_at": created_at,
        "app_root": str(APP_ROOT),
        **payload,
    }
    json_path = output / f"{run_id}_import_timing.json"
    md_path = output / f"{run_id}_import_timing.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    summary = payload["summary"]
    lines = [
        f"# OVERWATCH Import Timing {run_id}",
        "",
        f"- Created at: `{created_at}`",
        f"- Modules: `{summary['module_count']}`",
        f"- OK: `{summary['ok']}`",
        f"- Failed: `{summary['failed']}`",
        f"- Slowest module: `{summary['slowest_module']}` at `{summary['slowest_ms']} ms`",
        f"- Average import time: `{summary['avg_ms']} ms`",
        "",
        "## Module Timings",
        "",
        "| Module | OK | Import ms | Process wall ms | Error |",
        "|---|---:|---:|---:|---|",
    ]
    for row in sorted(payload["modules"], key=lambda item: float(item.get("elapsed_ms", 0) or 0), reverse=True):
        error = str(row.get("error") or "").replace("|", "\\|")[:180]
        lines.append(
            f"| {row['module']} | {'yes' if row.get('ok') else 'no'} | "
            f"{row.get('elapsed_ms', 0)} | {row.get('process_wall_ms', 0)} | {error} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure cold import timings for OVERWATCH modules.")
    parser.add_argument("--run-id", default=_default_run_id())
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--timeout-sec", type=float, default=30.0)
    parser.add_argument("--modules", nargs="*", default=list(DEFAULT_MODULES))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_import_timing(args.modules, timeout_sec=args.timeout_sec)
    json_path, md_path = write_reports(payload, run_id=args.run_id, output_dir=args.output_dir)
    summary = payload["summary"]
    print(json.dumps({
        "run_id": args.run_id,
        "ok": summary["ok"],
        "failed": summary["failed"],
        "slowest_module": summary["slowest_module"],
        "slowest_ms": summary["slowest_ms"],
        "json_report": str(json_path),
        "markdown_report": str(md_path),
    }, indent=2))
    return 0 if summary["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
