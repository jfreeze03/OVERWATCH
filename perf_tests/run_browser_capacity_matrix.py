#!/usr/bin/env python
"""Run initial-load browser capacity diagnostics across viewport/runtime variants."""
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
DEFAULT_VIEWPORTS = ((1440, 1000), (1280, 800))
DEFAULT_CHROMIUM_VARIANTS = {
    "default": [],
    "disable_dev_shm_usage": ["--disable-dev-shm-usage"],
    "disable_gpu": ["--disable-gpu"],
}


def _row_metric(rows: list[dict[str, object]], metric: str) -> float:
    for row in rows:
        if row.get("metric") == metric:
            return float(row.get("p95_ms", 0) or 0)
    return 0.0


def _frontend_metric(rows: list[dict[str, object]], metric: str) -> float:
    for row in rows:
        if row.get("metric") == metric:
            return float(row.get("p95", 0) or 0)
    return 0.0


def summarize_report(report: dict[str, object], *, run_id: str, users: int, viewport: str, chromium_variant: str, returncode: int) -> dict[str, object]:
    summary = report.get("summary", {}) if isinstance(report, dict) else {}
    nav = summary.get("browser_navigation_timing", []) if isinstance(summary, dict) else []
    paint = summary.get("browser_paint_timing", []) if isinstance(summary, dict) else []
    dom = summary.get("frontend_dom_metrics", []) if isinstance(summary, dict) else []
    resources = summary.get("frontend_resource_timing", []) if isinstance(summary, dict) else []
    resource_count = sum(float(row.get("count_p95", 0) or 0) for row in resources if isinstance(row, dict))
    samples = summary.get("resource_samples", []) if isinstance(summary, dict) else []
    last_resource = samples[-1] if isinstance(samples, list) and samples else {}
    return {
        "run_id": run_id,
        "users": users,
        "viewport": viewport,
        "chromium_variant": chromium_variant,
        "returncode": returncode,
        "readiness_state": summary.get("readiness_state", "BLOCKED"),
        "readiness_score": summary.get("readiness_score", 0),
        "p95_ms": summary.get("p95_ms", 0),
        "p99_ms": summary.get("p99_ms", 0),
        "errors": summary.get("errors", 0),
        "responseStart_p95_ms": _row_metric(nav if isinstance(nav, list) else [], "responseStart"),
        "first_contentful_paint_p95_ms": _row_metric(
            paint if isinstance(paint, list) else [],
            "first-contentful-paint",
        ),
        "dom_node_count_p95": _frontend_metric(dom if isinstance(dom, list) else [], "node_count"),
        "resource_count_p95": round(resource_count, 2),
        "host_cpu_percent": last_resource.get("cpu_percent", ""),
        "host_memory_percent": last_resource.get("memory_percent", ""),
        "browser_child_process_count": last_resource.get("browser_child_process_count", ""),
    }


def run_case(
    *,
    url: str,
    run_id: str,
    users: int,
    width: int,
    height: int,
    chromium_variant: str,
    chromium_args: list[str],
    profile: pathlib.Path,
    output_dir: pathlib.Path,
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
        "--width",
        str(width),
        "--height",
        str(height),
    ]
    for arg in chromium_args:
        command.append(f"--chromium-arg={arg}")
    result = subprocess.run(
        command,
        cwd=str(PERF_ROOT.parent),
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )
    report_path = output_dir / f"{run_id}_live_concurrent.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    row = summarize_report(
        report,
        run_id=run_id,
        users=users,
        viewport=f"{width}x{height}",
        chromium_variant=chromium_variant,
        returncode=result.returncode,
    )
    row["report_path"] = str(report_path) if report_path.exists() else ""
    row["stdout_tail"] = result.stdout[-1000:]
    row["stderr_tail"] = result.stderr[-1000:]
    return row


def build_payload(*, run_id_prefix: str, url: str, rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "run_id_prefix": run_id_prefix,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "url": url,
        "rows": rows,
    }


def write_reports(payload: dict[str, object], *, output_dir: str | pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    output = pathlib.Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    run_id_prefix = str(payload["run_id_prefix"])
    json_path = output / f"{run_id_prefix}_browser_capacity_matrix.json"
    md_path = output / f"{run_id_prefix}_browser_capacity_matrix.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        f"# OVERWATCH Browser Capacity Matrix {run_id_prefix}",
        "",
        "- Diagnostic only; this is not the release gate.",
        f"- URL: `{payload['url']}`",
        "",
        "| Users | Viewport | Chromium | State | p95 ms | responseStart p95 | FCP p95 | DOM nodes p95 | Resource count p95 | CPU % | Memory % | Browser children |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["rows"]:
        lines.append(
            f"| {row['users']} | {row['viewport']} | {row['chromium_variant']} | {row['readiness_state']} | "
            f"{row['p95_ms']} | {row['responseStart_p95_ms']} | {row['first_contentful_paint_p95_ms']} | "
            f"{row['dom_node_count_p95']} | {row['resource_count_p95']} | {row['host_cpu_percent']} | "
            f"{row['host_memory_percent']} | {row['browser_child_process_count']} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run browser capacity diagnostic matrix.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--run-id-prefix", default=f"PERF_BROWSER_CAPACITY_{uuid.uuid4().hex[:8].upper()}")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE))
    parser.add_argument("--users", nargs="*", type=int, default=list(DEFAULT_USERS))
    parser.add_argument("--timeout-sec", type=float, default=600.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = pathlib.Path(args.output_dir)
    rows = []
    for width, height in DEFAULT_VIEWPORTS:
        for variant, chromium_args in DEFAULT_CHROMIUM_VARIANTS.items():
            for users in args.users:
                run_id = f"{args.run_id_prefix}_{width}x{height}_{variant}_U{users:02d}"
                rows.append(
                    run_case(
                        url=args.url,
                        run_id=run_id,
                        users=users,
                        width=width,
                        height=height,
                        chromium_variant=variant,
                        chromium_args=chromium_args,
                        profile=pathlib.Path(args.profile),
                        output_dir=output_dir,
                        timeout_sec=args.timeout_sec,
                    )
                )
    payload = build_payload(run_id_prefix=args.run_id_prefix, url=args.url, rows=rows)
    json_path, md_path = write_reports(payload, output_dir=output_dir)
    slowest = max(rows, key=lambda row: float(row.get("p95_ms", 0) or 0)) if rows else {}
    print(json.dumps({
        "run_id_prefix": args.run_id_prefix,
        "cases": len(rows),
        "slowest_case": {
            "users": slowest.get("users"),
            "viewport": slowest.get("viewport"),
            "chromium_variant": slowest.get("chromium_variant"),
            "p95_ms": slowest.get("p95_ms"),
        },
        "json_report": str(json_path),
        "markdown_report": str(md_path),
    }, indent=2))
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
