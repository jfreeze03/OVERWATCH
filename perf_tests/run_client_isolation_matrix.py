#!/usr/bin/env python
"""Run clean release-profile variants that isolate local browser/client tail risk."""
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
DEFAULT_PROFILE = PERF_ROOT / "profiles" / "12_power_users_release_scored.json"
DEFAULT_CASES = (
    {"label": "shared_ramp12", "browser_launch_mode": "shared", "ramp_seconds": 12.0},
    {"label": "per_user_ramp12", "browser_launch_mode": "per_user", "ramp_seconds": 12.0},
    {"label": "shared_ramp24", "browser_launch_mode": "shared", "ramp_seconds": 24.0},
    {"label": "shared_ramp36", "browser_launch_mode": "shared", "ramp_seconds": 36.0},
    {"label": "per_user_ramp24", "browser_launch_mode": "per_user", "ramp_seconds": 24.0},
)
P95_THRESHOLD_MS = 10000.0
P99_TAIL_THRESHOLD_MS = P95_THRESHOLD_MS * 1.8
READINESS_THRESHOLD = 95


def summarize_report(report: dict[str, object], *, run_id: str, case: dict[str, object], returncode: int) -> dict[str, object]:
    summary = report.get("summary", {}) if isinstance(report, dict) else {}
    resource_samples = summary.get("resource_samples", []) if isinstance(summary, dict) else []
    last_resource = resource_samples[-1] if isinstance(resource_samples, list) and resource_samples else {}
    in_run_tails = summary.get("in_run_tail_captures", []) if isinstance(summary, dict) else []
    p95_ms = float(summary.get("p95_ms", 0) or 0)
    p99_ms = float(summary.get("p99_ms", 0) or 0)
    errors = int(summary.get("errors", 0) or 0)
    skipped_buttons = int(summary.get("skipped_buttons", 0) or 0)
    readiness_score = int(summary.get("readiness_score", 0) or 0)
    p99_tail_pass = p99_ms <= P99_TAIL_THRESHOLD_MS
    readiness_pass = readiness_score >= READINESS_THRESHOLD
    release_policy_candidate = (
        returncode == 0
        and p95_ms <= P95_THRESHOLD_MS
        and p99_tail_pass
        and readiness_pass
        and errors == 0
        and skipped_buttons == 0
    )
    return {
        "run_id": run_id,
        "label": case["label"],
        "browser_launch_mode": case["browser_launch_mode"],
        "ramp_seconds": case["ramp_seconds"],
        "returncode": returncode,
        "readiness_state": summary.get("readiness_state", "BLOCKED"),
        "readiness_score": readiness_score,
        "p95_ms": p95_ms,
        "p99_ms": p99_ms,
        "max_ms": summary.get("max_ms", 0),
        "errors": errors,
        "skipped_buttons": skipped_buttons,
        "p99_tail_pass": p99_tail_pass,
        "readiness_pass": readiness_pass,
        "release_policy_candidate": release_policy_candidate,
        "in_run_tail_capture_count": len(in_run_tails) if isinstance(in_run_tails, list) else 0,
        "host_cpu_percent": last_resource.get("cpu_percent", ""),
        "host_memory_percent": last_resource.get("memory_percent", ""),
        "browser_child_process_count": last_resource.get("browser_child_process_count", ""),
    }


def run_case(
    *,
    url: str,
    run_id: str,
    case: dict[str, object],
    profile: pathlib.Path,
    output_dir: pathlib.Path,
    tail_capture_threshold_ms: float,
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
        "--browser-launch-mode",
        str(case["browser_launch_mode"]),
        "--ramp-seconds",
        str(case["ramp_seconds"]),
        "--tail-capture-threshold-ms",
        str(tail_capture_threshold_ms),
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
    row = summarize_report(report, run_id=run_id, case=case, returncode=result.returncode)
    row["report_path"] = str(report_path) if report_path.exists() else ""
    row["stdout_tail"] = result.stdout[-1000:]
    row["stderr_tail"] = result.stderr[-1000:]
    return row


def build_payload(*, run_id_prefix: str, url: str, rows: list[dict[str, object]]) -> dict[str, object]:
    best = min(rows, key=lambda row: float(row.get("p99_ms", 0) or 0)) if rows else {}
    worst = max(rows, key=lambda row: float(row.get("p99_ms", 0) or 0)) if rows else {}
    recommendation = recommend_release_policy(rows)
    return {
        "run_id_prefix": run_id_prefix,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "url": url,
        "rows": rows,
        "conclusion": {
            "best_case": {
                "label": best.get("label", ""),
                "p95_ms": best.get("p95_ms", 0),
                "p99_ms": best.get("p99_ms", 0),
                "readiness_score": best.get("readiness_score", 0),
            },
            "worst_case": {
                "label": worst.get("label", ""),
                "p95_ms": worst.get("p95_ms", 0),
                "p99_ms": worst.get("p99_ms", 0),
                "readiness_score": worst.get("readiness_score", 0),
            },
            "p99_tail_threshold_ms": P99_TAIL_THRESHOLD_MS,
            "readiness_threshold": READINESS_THRESHOLD,
            "recommendation": recommendation,
        },
    }


def _candidate_by_label(rows: list[dict[str, object]], label: str) -> bool:
    return any(row.get("label") == label and bool(row.get("release_policy_candidate")) for row in rows)


def recommend_release_policy(rows: list[dict[str, object]]) -> str:
    """Return a stable recommendation token for release policy discussions."""

    shared_ramp12_passes = _candidate_by_label(rows, "shared_ramp12")
    shared_ramp24_passes = _candidate_by_label(rows, "shared_ramp24")
    shared_ramp36_passes = _candidate_by_label(rows, "shared_ramp36")
    per_user_passes = _candidate_by_label(rows, "per_user_ramp12") or _candidate_by_label(rows, "per_user_ramp24")
    if shared_ramp12_passes:
        return "ramp12_passes"
    if shared_ramp24_passes or shared_ramp36_passes:
        return "ramp24_passes"
    if per_user_passes:
        return "per_user_only_passes"
    return "ramp12_tail_blocked"


def write_reports(payload: dict[str, object], *, output_dir: str | pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    output = pathlib.Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    run_id_prefix = str(payload["run_id_prefix"])
    json_path = output / f"{run_id_prefix}_client_isolation_matrix.json"
    md_path = output / f"{run_id_prefix}_client_isolation_matrix.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        f"# OVERWATCH Client Isolation Matrix {run_id_prefix}",
        "",
        "- Diagnostic only; this is not the release gate.",
        f"- URL: `{payload['url']}`",
        "",
        "| Case | Browser mode | Ramp s | State | Score | p95 ms | p99 ms | Max ms | p99 tail pass | Readiness pass | Candidate | Errors | Skipped | Tail captures | CPU % | Memory % | Browser children |",
        "|---|---|---:|---|---:|---:|---:|---:|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["rows"]:
        lines.append(
            f"| {row['label']} | {row['browser_launch_mode']} | {row['ramp_seconds']} | "
            f"{row['readiness_state']} | {row['readiness_score']} | {row['p95_ms']} | {row['p99_ms']} | "
            f"{row['max_ms']} | {row['p99_tail_pass']} | {row['readiness_pass']} | {row['release_policy_candidate']} | "
            f"{row['errors']} | {row['skipped_buttons']} | {row['in_run_tail_capture_count']} | "
            f"{row['host_cpu_percent']} | {row['host_memory_percent']} | {row['browser_child_process_count']} |"
        )
    conclusion = payload.get("conclusion", {})
    if isinstance(conclusion, dict):
        lines.extend([
            "",
            "## Conclusion",
            "",
            f"- Best case: `{conclusion.get('best_case', {}).get('label', '')}`",
            f"- Worst case: `{conclusion.get('worst_case', {}).get('label', '')}`",
            f"- p99 tail threshold: `{conclusion.get('p99_tail_threshold_ms', P99_TAIL_THRESHOLD_MS)} ms`",
            f"- Recommendation: `{conclusion.get('recommendation', '')}`",
        ])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run client isolation release-profile diagnostics.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--run-id-prefix", default=f"PERF_CLIENT_ISOLATION_{uuid.uuid4().hex[:8].upper()}")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE))
    parser.add_argument("--tail-capture-threshold-ms", type=float, default=18000.0)
    parser.add_argument("--timeout-sec", type=float, default=1200.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = pathlib.Path(args.output_dir)
    rows: list[dict[str, object]] = []
    for case in DEFAULT_CASES:
        run_id = f"{args.run_id_prefix}_{case['label'].upper()}"
        rows.append(
            run_case(
                url=args.url,
                run_id=run_id,
                case=case,
                profile=pathlib.Path(args.profile),
                output_dir=output_dir,
                tail_capture_threshold_ms=args.tail_capture_threshold_ms,
                timeout_sec=args.timeout_sec,
            )
        )
    payload = build_payload(run_id_prefix=args.run_id_prefix, url=args.url, rows=rows)
    json_path, md_path = write_reports(payload, output_dir=output_dir)
    print(json.dumps({
        "run_id_prefix": args.run_id_prefix,
        "cases": len(rows),
        "conclusion": payload.get("conclusion", {}),
        "json_report": str(json_path),
        "markdown_report": str(md_path),
    }, indent=2))
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
