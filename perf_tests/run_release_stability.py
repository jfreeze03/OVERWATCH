#!/usr/bin/env python
"""Repeat the clean scored 12-user release profile to measure tail stability."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import statistics
import subprocess
import sys
import uuid


PERF_ROOT = pathlib.Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = PERF_ROOT / "results"
DEFAULT_PROFILE = PERF_ROOT / "profiles" / "12_power_users_release_scored.json"


def _slowest_initial_load(samples: list[dict[str, object]]) -> dict[str, object]:
    initial_loads = [
        sample for sample in samples
        if not sample.get("diagnostic") and not sample.get("skipped") and sample.get("action") == "initial_load"
    ]
    if not initial_loads:
        return {}
    sample = max(initial_loads, key=lambda row: float(row.get("elapsed_ms", 0) or 0))
    return {
        "user_id": sample.get("user_id"),
        "iteration": sample.get("iteration"),
        "elapsed_ms": round(float(sample.get("elapsed_ms", 0) or 0), 2),
        "ok": sample.get("ok", False),
    }


def summarize_report(report: dict[str, object], *, run_id: str, returncode: int) -> dict[str, object]:
    summary = report.get("summary", {}) if isinstance(report, dict) else {}
    samples = report.get("samples", []) if isinstance(report, dict) else []
    return {
        "run_id": run_id,
        "returncode": returncode,
        "readiness_state": summary.get("readiness_state", "BLOCKED"),
        "readiness_score": summary.get("readiness_score", 0),
        "p95_ms": summary.get("p95_ms", 0),
        "p99_ms": summary.get("p99_ms", 0),
        "max_ms": summary.get("max_ms", 0),
        "errors": summary.get("errors", 0),
        "skipped": summary.get("skipped", 0),
        "slowest_initial_load": _slowest_initial_load(samples if isinstance(samples, list) else []),
        "readiness_penalties": summary.get("readiness_penalties", []),
        "release_blockers": summary.get("release_blockers", []),
    }


def _median(rows: list[dict[str, object]], key: str) -> float:
    values = [float(row.get(key, 0) or 0) for row in rows]
    return round(float(statistics.median(values)), 2) if values else 0.0


def build_payload(*, run_id_prefix: str, url: str, profile: str, rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "run_id_prefix": run_id_prefix,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "url": url,
        "profile": profile,
        "diagnostic_only": True,
        "runs": rows,
        "summary": {
            "runs": len(rows),
            "median_p95_ms": _median(rows, "p95_ms"),
            "median_p99_ms": _median(rows, "p99_ms"),
            "median_max_ms": _median(rows, "max_ms"),
            "median_readiness_score": _median(rows, "readiness_score"),
            "pass_count": sum(1 for row in rows if row.get("readiness_state") == "PASS"),
            "watch_count": sum(1 for row in rows if row.get("readiness_state") == "WATCH"),
            "fail_count": sum(1 for row in rows if row.get("readiness_state") == "FAIL"),
            "errors": sum(int(row.get("errors", 0) or 0) for row in rows),
            "skipped": sum(int(row.get("skipped", 0) or 0) for row in rows),
        },
    }


def run_once(
    *,
    url: str,
    run_id: str,
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
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    row = summarize_report(report, run_id=run_id, returncode=result.returncode)
    row["report_path"] = str(report_path) if report_path.exists() else ""
    row["stdout_tail"] = result.stdout[-1000:]
    row["stderr_tail"] = result.stderr[-1000:]
    return row


def write_reports(payload: dict[str, object], *, output_dir: str | pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    output = pathlib.Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    run_id_prefix = str(payload["run_id_prefix"])
    json_path = output / f"{run_id_prefix}_release_stability.json"
    md_path = output / f"{run_id_prefix}_release_stability.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    summary = payload["summary"]
    lines = [
        f"# OVERWATCH Clean Release Stability {run_id_prefix}",
        "",
        "- Diagnostic only; this is not the release gate.",
        f"- URL: `{payload['url']}`",
        f"- Profile: `{payload['profile']}`",
        "",
        "## Summary",
        f"- Runs: `{summary['runs']}`",
        f"- Median p95/p99/max: `{summary['median_p95_ms']} / {summary['median_p99_ms']} / {summary['median_max_ms']} ms`",
        f"- Median readiness: `{summary['median_readiness_score']}/100`",
        f"- PASS/WATCH/FAIL: `{summary['pass_count']} / {summary['watch_count']} / {summary['fail_count']}`",
        f"- Errors/skipped: `{summary['errors']} / {summary['skipped']}`",
        "",
        "## Runs",
        "",
        "| Run ID | State | Readiness | p95 ms | p99 ms | Max ms | Errors | Skipped | Slowest initial_load ms |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["runs"]:
        slow = row.get("slowest_initial_load", {}) if isinstance(row, dict) else {}
        slow_ms = slow.get("elapsed_ms", "") if isinstance(slow, dict) else ""
        lines.append(
            f"| {row.get('run_id', '')} | {row.get('readiness_state', '')} | {row.get('readiness_score', '')} | "
            f"{row.get('p95_ms', '')} | {row.get('p99_ms', '')} | {row.get('max_ms', '')} | "
            f"{row.get('errors', '')} | {row.get('skipped', '')} | {slow_ms} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repeat the clean scored 12-user release profile.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--run-id-prefix", default=f"PERF_RELEASE_STABILITY_{uuid.uuid4().hex[:8].upper()}")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout-sec", type=float, default=1200.0)
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats must be at least 1.")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = pathlib.Path(args.output_dir)
    profile = pathlib.Path(args.profile)
    rows = []
    for idx in range(1, args.repeats + 1):
        rows.append(
            run_once(
                url=args.url,
                run_id=f"{args.run_id_prefix}_{idx:02d}",
                profile=profile,
                output_dir=output_dir,
                timeout_sec=args.timeout_sec,
            )
        )
    payload = build_payload(run_id_prefix=args.run_id_prefix, url=args.url, profile=str(profile), rows=rows)
    json_path, md_path = write_reports(payload, output_dir=output_dir)
    print(json.dumps({
        "run_id_prefix": args.run_id_prefix,
        "runs": len(rows),
        "median_p95_ms": payload["summary"]["median_p95_ms"],
        "median_p99_ms": payload["summary"]["median_p99_ms"],
        "median_readiness_score": payload["summary"]["median_readiness_score"],
        "json_report": str(json_path),
        "markdown_report": str(md_path),
    }, indent=2))
    return 0 if rows and all(row.get("report_path") for row in rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())
