#!/usr/bin/env python
"""Run the guarded 12-heavy-power-user OVERWATCH browser benchmark."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import pathlib
import sys


PERF_ROOT = pathlib.Path(__file__).resolve().parent
PROFILE_PATH = PERF_ROOT / "profiles" / "12_power_users.json"
DEFAULT_OUTPUT_DIR = PERF_ROOT / "results"
sys.path.insert(0, str(PERF_ROOT))

import live_concurrent_runner  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run OVERWATCH's guarded 12-power-user benchmark.")
    parser.add_argument("--url", default="http://localhost:8501/", help="Dashboard URL to test.")
    parser.add_argument("--profile", default=str(PROFILE_PATH), help="Benchmark profile JSON path.")
    parser.add_argument("--run-id", default=f"PERF_12_POWER_USERS_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for JSON and Markdown reports.")
    parser.add_argument("--headed", action="store_true", help="Run with visible browser windows.")
    parser.add_argument("--allow-watch", action="store_true", help="Return success for WATCH results; default release-gate behavior treats WATCH as nonzero.")
    args, runner_args = parser.parse_known_args(argv)
    args.runner_args = runner_args
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    runner_args = [
        "--profile",
        args.profile,
        "--url",
        args.url,
        "--run-id",
        args.run_id,
        "--output-dir",
        args.output_dir,
    ]
    if args.headed:
        runner_args.append("--headed")
    runner_args.extend(args.runner_args)
    live_args = live_concurrent_runner.parse_args(runner_args)

    try:
        samples, total_elapsed_sec, resource_samples = asyncio.run(live_concurrent_runner.run_stress(live_args))
    except Exception as exc:
        print(json.dumps({"run_id": args.run_id, "readiness_state": "BLOCKED", "error": str(exc)}, indent=2))
        return 3

    trace_artifact = ""
    trace_error = ""
    if live_args.trace_slowest_initial_load:
        trace_artifact, trace_error = asyncio.run(
            live_concurrent_runner.capture_slowest_initial_load_trace(live_args, samples)
        )
    summary = live_concurrent_runner.summarize(
        samples,
        total_elapsed_sec,
        live_args,
        resource_samples=resource_samples,
        trace_artifact=trace_artifact,
        trace_error=trace_error,
    )
    json_path, md_path = live_concurrent_runner.write_reports(live_args, samples, summary)
    print(json.dumps({
        "run_id": args.run_id,
        "readiness_state": summary["readiness_state"],
        "readiness_score": summary["readiness_score"],
        "users": summary["users"],
        "iterations": summary["iterations"],
        "errors": summary["errors"],
        "error_rate": summary["error_rate"],
        "p95_ms": summary["p95_ms"],
        "p99_ms": summary["p99_ms"],
        "slowest_step": summary["slowest_step"],
        "json_report": str(json_path),
        "markdown_report": str(md_path),
    }, indent=2))
    if summary["readiness_state"] == "PASS":
        return 0
    if summary["readiness_state"] == "WATCH" and args.allow_watch:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
