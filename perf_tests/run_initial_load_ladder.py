#!/usr/bin/env python
"""Run the initial-load-only profile across a small concurrency ladder."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import subprocess
import sys
import uuid


PERF_ROOT = pathlib.Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = PERF_ROOT / "results"
DEFAULT_PROFILE = PERF_ROOT / "profiles" / "12_power_users_initial_load_only.json"
DEFAULT_USERS = (1, 3, 6, 9, 12)


def _row_metric(rows: list[dict[str, object]], metric: str) -> float:
    for row in rows:
        if row.get("metric") == metric:
            return float(row.get("p95_ms", 0) or 0)
    return 0.0


def _phase_metric(rows: list[dict[str, object]], phase: str) -> float:
    for row in rows:
        if row.get("phase") == phase:
            return float(row.get("p95_ms", 0) or 0)
    return 0.0


def _slowest_app_entry(rows: list[dict[str, object]]) -> dict[str, object]:
    app_rows = [row for row in rows if str(row.get("phase", "")).startswith("app_entry:")]
    if not app_rows:
        return {"phase": "", "p95_ms": 0.0}
    return max(app_rows, key=lambda row: float(row.get("p95_ms", 0) or 0))


def summarize_report(report: dict[str, object], *, users: int, run_id: str) -> dict[str, object]:
    summary = report.get("summary", {}) if isinstance(report, dict) else {}
    nav_rows = summary.get("browser_navigation_timing", []) if isinstance(summary, dict) else []
    paint_rows = summary.get("browser_paint_timing", []) if isinstance(summary, dict) else []
    server_rows = summary.get("server_phase_breakdown", []) if isinstance(summary, dict) else []
    app_entry = _slowest_app_entry(server_rows if isinstance(server_rows, list) else [])
    return {
        "run_id": run_id,
        "users": users,
        "readiness_state": summary.get("readiness_state", ""),
        "readiness_score": summary.get("readiness_score", 0),
        "p50_ms": summary.get("p50_ms", 0),
        "p95_ms": summary.get("p95_ms", 0),
        "p99_ms": summary.get("p99_ms", 0),
        "errors": summary.get("errors", 0),
        "responseStart_p95_ms": _row_metric(nav_rows if isinstance(nav_rows, list) else [], "responseStart"),
        "domContentLoadedEventEnd_p95_ms": _row_metric(
            nav_rows if isinstance(nav_rows, list) else [],
            "domContentLoadedEventEnd",
        ),
        "first_contentful_paint_p95_ms": _row_metric(
            paint_rows if isinstance(paint_rows, list) else [],
            "first-contentful-paint",
        ),
        "server_shell_total_render_app_p95_ms": _phase_metric(
            server_rows if isinstance(server_rows, list) else [],
            "shell:total_render_app",
        ),
        "slowest_app_entry_phase": app_entry.get("phase", ""),
        "slowest_app_entry_p95_ms": app_entry.get("p95_ms", 0),
    }


def run_level(
    *,
    url: str,
    run_id: str,
    users: int,
    output_dir: pathlib.Path,
    profile: pathlib.Path,
    timeout_sec: float,
) -> dict[str, object]:
    command = [
        sys.executable,
        str(PERF_ROOT / "run_12_power_users.py"),
        "--url",
        url,
        "--run-id",
        run_id,
        "--output-dir",
        str(output_dir),
        "--profile",
        str(profile),
        "--users",
        str(users),
    ]
    result = subprocess.run(
        command,
        cwd=str(PERF_ROOT.parent),
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )
    report_path = output_dir / f"{run_id}_live_concurrent.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        row = summarize_report(report, users=users, run_id=run_id)
    else:
        row = {
            "run_id": run_id,
            "users": users,
            "readiness_state": "BLOCKED",
            "readiness_score": 0,
            "p50_ms": 0,
            "p95_ms": 0,
            "p99_ms": 0,
            "errors": 1,
            "responseStart_p95_ms": 0.0,
            "domContentLoadedEventEnd_p95_ms": 0.0,
            "first_contentful_paint_p95_ms": 0.0,
            "server_shell_total_render_app_p95_ms": 0.0,
            "slowest_app_entry_phase": "",
            "slowest_app_entry_p95_ms": 0.0,
        }
    row["returncode"] = result.returncode
    row["stdout_tail"] = result.stdout[-1000:]
    row["stderr_tail"] = result.stderr[-1000:]
    return row


def build_payload(*, run_id_prefix: str, url: str, rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "run_id_prefix": run_id_prefix,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "url": url,
        "levels": rows,
    }


def write_reports(payload: dict[str, object], *, output_dir: str | pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    output = pathlib.Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    run_id_prefix = str(payload["run_id_prefix"])
    json_path = output / f"{run_id_prefix}_initial_load_ladder.json"
    md_path = output / f"{run_id_prefix}_initial_load_ladder.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        f"# OVERWATCH Initial Load Ladder {run_id_prefix}",
        "",
        f"- URL: `{payload['url']}`",
        "- Diagnostic only; this is not the release gate.",
        "",
        "| Users | State | p50 ms | p95 ms | p99 ms | responseStart p95 | DCL p95 | FCP p95 | shell total p95 | slowest app-entry phase |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in payload["levels"]:
        lines.append(
            f"| {row['users']} | {row['readiness_state']} | {row['p50_ms']} | {row['p95_ms']} | "
            f"{row['p99_ms']} | {row['responseStart_p95_ms']} | "
            f"{row['domContentLoadedEventEnd_p95_ms']} | {row['first_contentful_paint_p95_ms']} | "
            f"{row['server_shell_total_render_app_p95_ms']} | "
            f"{row['slowest_app_entry_phase']} {row['slowest_app_entry_p95_ms']} ms |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run initial-load-only concurrency ladder.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--run-id-prefix", default=f"PERF_INITIAL_LOAD_LADDER_{uuid.uuid4().hex[:8].upper()}")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE))
    parser.add_argument("--users", nargs="*", type=int, default=list(DEFAULT_USERS))
    parser.add_argument("--timeout-sec", type=float, default=600.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = pathlib.Path(args.output_dir)
    rows = []
    for users in args.users:
        run_id = f"{args.run_id_prefix}_U{users:02d}"
        rows.append(
            run_level(
                url=args.url,
                run_id=run_id,
                users=users,
                output_dir=output_dir,
                profile=pathlib.Path(args.profile),
                timeout_sec=args.timeout_sec,
            )
        )
    payload = build_payload(run_id_prefix=args.run_id_prefix, url=args.url, rows=rows)
    json_path, md_path = write_reports(payload, output_dir=output_dir)
    slowest = max(rows, key=lambda row: float(row.get("p95_ms", 0) or 0)) if rows else {}
    print(json.dumps({
        "run_id_prefix": args.run_id_prefix,
        "levels": len(rows),
        "slowest_users": slowest.get("users", 0),
        "slowest_p95_ms": slowest.get("p95_ms", 0),
        "json_report": str(json_path),
        "markdown_report": str(md_path),
    }, indent=2))
    return 0 if all(int(row.get("returncode", 0) or 0) in (0, 2) for row in rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())
