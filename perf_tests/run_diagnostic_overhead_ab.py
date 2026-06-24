#!/usr/bin/env python
"""Compare clean release scoring with full diagnostic capture."""
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
CLEAN_PROFILE = PERF_ROOT / "profiles" / "12_power_users_release_scored.json"
DIAGNOSTIC_PROFILE = PERF_ROOT / "profiles" / "12_power_users_diagnostic.json"


def _row_metric(rows: list[dict[str, object]], key: str, value: str) -> float:
    for row in rows:
        if row.get(key) == value:
            return float(row.get("p95_ms", 0) or 0)
    return 0.0


def _phase_metric(rows: list[dict[str, object]], phase: str) -> float:
    for row in rows:
        if row.get("phase") == phase:
            return float(row.get("p95_ms", 0) or 0)
    return 0.0


def summarize_live_report(report: dict[str, object], *, label: str, run_id: str, returncode: int) -> dict[str, object]:
    summary = report.get("summary", {}) if isinstance(report, dict) else {}
    nav = summary.get("browser_navigation_timing", []) if isinstance(summary, dict) else []
    paint = summary.get("browser_paint_timing", []) if isinstance(summary, dict) else []
    server = summary.get("server_phase_breakdown", []) if isinstance(summary, dict) else []
    return {
        "label": label,
        "run_id": run_id,
        "returncode": returncode,
        "readiness_state": summary.get("readiness_state", "BLOCKED"),
        "readiness_score": summary.get("readiness_score", 0),
        "p95_ms": summary.get("p95_ms", 0),
        "p99_ms": summary.get("p99_ms", 0),
        "errors": summary.get("errors", 0),
        "skipped": summary.get("skipped", 0),
        "diagnostic_steps": summary.get("diagnostic_steps", 0),
        "responseStart_p95_ms": _row_metric(nav if isinstance(nav, list) else [], "metric", "responseStart"),
        "first_contentful_paint_p95_ms": _row_metric(
            paint if isinstance(paint, list) else [],
            "metric",
            "first-contentful-paint",
        ),
        "server_shell_total_render_app_p95_ms": _phase_metric(
            server if isinstance(server, list) else [],
            "shell:total_render_app",
        ),
        "resource_samples": summary.get("resource_samples", []),
    }


def run_profile(
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
    return {
        "run_id": run_id,
        "returncode": result.returncode,
        "report_path": str(report_path) if report_path.exists() else "",
        "stdout_tail": result.stdout[-1200:],
        "stderr_tail": result.stderr[-1200:],
        "report": report,
    }


def build_payload(*, run_id_prefix: str, url: str, clean: dict[str, object], diagnostic: dict[str, object]) -> dict[str, object]:
    clean_row = summarize_live_report(
        clean.get("report", {}),
        label="clean_scored",
        run_id=str(clean.get("run_id", "")),
        returncode=int(clean.get("returncode", 0) or 0),
    )
    diagnostic_row = summarize_live_report(
        diagnostic.get("report", {}),
        label="full_diagnostic",
        run_id=str(diagnostic.get("run_id", "")),
        returncode=int(diagnostic.get("returncode", 0) or 0),
    )
    delta = {
        "p95_delta_ms": round(float(diagnostic_row["p95_ms"] or 0) - float(clean_row["p95_ms"] or 0), 2),
        "p99_delta_ms": round(float(diagnostic_row["p99_ms"] or 0) - float(clean_row["p99_ms"] or 0), 2),
        "responseStart_delta_ms": round(
            float(diagnostic_row["responseStart_p95_ms"] or 0) - float(clean_row["responseStart_p95_ms"] or 0),
            2,
        ),
        "fcp_delta_ms": round(
            float(diagnostic_row["first_contentful_paint_p95_ms"] or 0)
            - float(clean_row["first_contentful_paint_p95_ms"] or 0),
            2,
        ),
    }
    return {
        "run_id_prefix": run_id_prefix,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "url": url,
        "profiles": [clean_row, diagnostic_row],
        "delta": delta,
        "artifacts": {
            "clean_report": clean.get("report_path", ""),
            "diagnostic_report": diagnostic.get("report_path", ""),
        },
    }


def write_reports(payload: dict[str, object], *, output_dir: str | pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    output = pathlib.Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    run_id_prefix = str(payload["run_id_prefix"])
    json_path = output / f"{run_id_prefix}_diagnostic_overhead_ab.json"
    md_path = output / f"{run_id_prefix}_diagnostic_overhead_ab.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        f"# OVERWATCH Diagnostic Overhead A/B {run_id_prefix}",
        "",
        "- Diagnostic only; this is not the release gate.",
        f"- URL: `{payload['url']}`",
        "",
        "| Profile | Run ID | State | Readiness | p95 ms | p99 ms | Errors | Skipped | Diagnostic steps | responseStart p95 | FCP p95 | shell total p95 |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["profiles"]:
        lines.append(
            f"| {row['label']} | {row['run_id']} | {row['readiness_state']} | {row['readiness_score']} | "
            f"{row['p95_ms']} | {row['p99_ms']} | {row['errors']} | {row['skipped']} | "
            f"{row['diagnostic_steps']} | {row['responseStart_p95_ms']} | "
            f"{row['first_contentful_paint_p95_ms']} | {row['server_shell_total_render_app_p95_ms']} |"
        )
    delta = payload["delta"]
    lines.extend([
        "",
        "## Delta",
        f"- Diagnostic minus clean p95: `{delta['p95_delta_ms']} ms`",
        f"- Diagnostic minus clean p99: `{delta['p99_delta_ms']} ms`",
        f"- Diagnostic minus clean responseStart p95: `{delta['responseStart_delta_ms']} ms`",
        f"- Diagnostic minus clean FCP p95: `{delta['fcp_delta_ms']} ms`",
    ])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run clean-vs-diagnostic 12-user benchmark comparison.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--run-id-prefix", default=f"PERF_DIAGNOSTIC_OVERHEAD_{uuid.uuid4().hex[:8].upper()}")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--clean-profile", default=str(CLEAN_PROFILE))
    parser.add_argument("--diagnostic-profile", default=str(DIAGNOSTIC_PROFILE))
    parser.add_argument("--timeout-sec", type=float, default=1200.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = pathlib.Path(args.output_dir)
    clean = run_profile(
        url=args.url,
        run_id=f"{args.run_id_prefix}_CLEAN",
        profile=pathlib.Path(args.clean_profile),
        output_dir=output_dir,
        timeout_sec=args.timeout_sec,
    )
    diagnostic = run_profile(
        url=args.url,
        run_id=f"{args.run_id_prefix}_DIAGNOSTIC",
        profile=pathlib.Path(args.diagnostic_profile),
        output_dir=output_dir,
        timeout_sec=args.timeout_sec,
    )
    payload = build_payload(run_id_prefix=args.run_id_prefix, url=args.url, clean=clean, diagnostic=diagnostic)
    json_path, md_path = write_reports(payload, output_dir=output_dir)
    print(json.dumps({
        "run_id_prefix": args.run_id_prefix,
        "profiles": len(payload["profiles"]),
        "p95_delta_ms": payload["delta"]["p95_delta_ms"],
        "json_report": str(json_path),
        "markdown_report": str(md_path),
    }, indent=2))
    return 0 if clean.get("report_path") and diagnostic.get("report_path") else 2


if __name__ == "__main__":
    raise SystemExit(main())
