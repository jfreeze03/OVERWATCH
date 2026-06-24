#!/usr/bin/env python
"""Compare clean release scoring with full diagnostic capture."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import random
import statistics
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


def _median(values: list[float]) -> float:
    return round(float(statistics.median(values)), 2) if values else 0.0


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
        "max_ms": summary.get("max_ms", 0),
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


def plan_run_order(*, repeats: int, warmup: bool = False, order: str = "alternating") -> list[dict[str, object]]:
    """Return deterministic clean/diagnostic run order for A/B diagnostics."""
    repeats = max(1, int(repeats))
    planned: list[dict[str, object]] = []
    if warmup:
        planned.extend([
            {"label": "clean_scored", "repeat": 0, "warmup": True},
            {"label": "full_diagnostic", "repeat": 0, "warmup": True},
        ])
    rng = random.Random(20260624)
    for repeat in range(1, repeats + 1):
        labels = ["clean_scored", "full_diagnostic"]
        if order == "random":
            rng.shuffle(labels)
        elif repeat % 2 == 0:
            labels.reverse()
        for label in labels:
            planned.append({"label": label, "repeat": repeat, "warmup": False})
    return planned


def _aggregate_profile(label: str, rows: list[dict[str, object]]) -> dict[str, object]:
    included = [row for row in rows if row.get("label") == label and not row.get("warmup")]
    if not included:
        return {
            "label": label,
            "runs": 0,
            "median_p95_ms": 0.0,
            "median_p99_ms": 0.0,
            "median_readiness_score": 0.0,
            "median_responseStart_p95_ms": 0.0,
            "median_first_contentful_paint_p95_ms": 0.0,
            "median_server_shell_total_render_app_p95_ms": 0.0,
            "errors": 0,
            "skipped": 0,
            "diagnostic_steps_median": 0.0,
            "run_ids": [],
        }
    return {
        "label": label,
        "runs": len(included),
        "median_p95_ms": _median([float(row.get("p95_ms", 0) or 0) for row in included]),
        "median_p99_ms": _median([float(row.get("p99_ms", 0) or 0) for row in included]),
        "median_readiness_score": _median([float(row.get("readiness_score", 0) or 0) for row in included]),
        "median_responseStart_p95_ms": _median([
            float(row.get("responseStart_p95_ms", 0) or 0) for row in included
        ]),
        "median_first_contentful_paint_p95_ms": _median([
            float(row.get("first_contentful_paint_p95_ms", 0) or 0) for row in included
        ]),
        "median_server_shell_total_render_app_p95_ms": _median([
            float(row.get("server_shell_total_render_app_p95_ms", 0) or 0) for row in included
        ]),
        "errors": sum(int(row.get("errors", 0) or 0) for row in included),
        "skipped": sum(int(row.get("skipped", 0) or 0) for row in included),
        "diagnostic_steps_median": _median([float(row.get("diagnostic_steps", 0) or 0) for row in included]),
        "run_ids": [row.get("run_id", "") for row in included],
    }


def _legacy_rows(clean: dict[str, object], diagnostic: dict[str, object]) -> list[dict[str, object]]:
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
    clean_row.update({"repeat": 1, "warmup": False, "report_path": clean.get("report_path", "")})
    diagnostic_row.update({"repeat": 1, "warmup": False, "report_path": diagnostic.get("report_path", "")})
    return [clean_row, diagnostic_row]


def build_payload(
    *,
    run_id_prefix: str,
    url: str,
    runs: list[dict[str, object]] | None = None,
    clean: dict[str, object] | None = None,
    diagnostic: dict[str, object] | None = None,
    repeats: int = 1,
    warmup: bool = False,
    order: str = "alternating",
) -> dict[str, object]:
    rows = list(runs or [])
    if not rows and clean is not None and diagnostic is not None:
        rows = _legacy_rows(clean, diagnostic)
    clean_profile = _aggregate_profile("clean_scored", rows)
    diagnostic_profile = _aggregate_profile("full_diagnostic", rows)
    delta = {
        "median_p95_delta_ms": round(
            float(diagnostic_profile["median_p95_ms"] or 0) - float(clean_profile["median_p95_ms"] or 0),
            2,
        ),
        "median_p99_delta_ms": round(
            float(diagnostic_profile["median_p99_ms"] or 0) - float(clean_profile["median_p99_ms"] or 0),
            2,
        ),
        "median_responseStart_delta_ms": round(
            float(diagnostic_profile["median_responseStart_p95_ms"] or 0)
            - float(clean_profile["median_responseStart_p95_ms"] or 0),
            2,
        ),
        "median_fcp_delta_ms": round(
            float(diagnostic_profile["median_first_contentful_paint_p95_ms"] or 0)
            - float(clean_profile["median_first_contentful_paint_p95_ms"] or 0),
            2,
        ),
    }
    return {
        "run_id_prefix": run_id_prefix,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "url": url,
        "diagnostic_only": True,
        "repeats": repeats,
        "warmup": warmup,
        "order_strategy": order,
        "run_order": [
            {
                "label": row.get("label"),
                "repeat": row.get("repeat"),
                "warmup": row.get("warmup", False),
                "run_id": row.get("run_id"),
                "returncode": row.get("returncode"),
            }
            for row in rows
        ],
        "runs": rows,
        "profiles": [clean_profile, diagnostic_profile],
        "delta": delta,
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
        f"- Repeats: `{payload.get('repeats', 1)}`",
        f"- Warmup discarded: `{'yes' if payload.get('warmup') else 'no'}`",
        f"- Order strategy: `{payload.get('order_strategy', 'alternating')}`",
        "",
        "## Median Summary",
        "",
        "| Profile | Runs | Median readiness | Median p95 ms | Median p99 ms | Errors | Skipped | Diagnostic steps median | responseStart p95 median | FCP p95 median | shell total p95 median |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["profiles"]:
        lines.append(
            f"| {row['label']} | {row['runs']} | {row['median_readiness_score']} | "
            f"{row['median_p95_ms']} | {row['median_p99_ms']} | {row['errors']} | {row['skipped']} | "
            f"{row['diagnostic_steps_median']} | {row['median_responseStart_p95_ms']} | "
            f"{row['median_first_contentful_paint_p95_ms']} | "
            f"{row['median_server_shell_total_render_app_p95_ms']} |"
        )
    delta = payload["delta"]
    lines.extend([
        "",
        "## Delta",
        f"- Diagnostic minus clean median p95: `{delta['median_p95_delta_ms']} ms`",
        f"- Diagnostic minus clean median p99: `{delta['median_p99_delta_ms']} ms`",
        f"- Diagnostic minus clean median responseStart p95: `{delta['median_responseStart_delta_ms']} ms`",
        f"- Diagnostic minus clean median FCP p95: `{delta['median_fcp_delta_ms']} ms`",
        "",
        "## Run Order",
        "",
        "| Order | Profile | Repeat | Warmup | Run ID | Return code |",
        "|---:|---|---:|---|---|---:|",
    ])
    for idx, row in enumerate(payload.get("runs", []), start=1):
        lines.append(
            f"| {idx} | {row.get('label', '')} | {row.get('repeat', '')} | "
            f"{row.get('warmup', False)} | {row.get('run_id', '')} | {row.get('returncode', '')} |"
        )
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
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--warmup", action="store_true")
    parser.add_argument("--order", choices=["alternating", "random"], default="alternating")
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats must be at least 1.")
    return args


def _run_id_for(prefix: str, planned: dict[str, object]) -> str:
    label = str(planned["label"])
    suffix = "CLEAN" if label == "clean_scored" else "DIAGNOSTIC"
    if planned.get("warmup"):
        return f"{prefix}_WARMUP_{suffix}"
    return f"{prefix}_R{int(planned['repeat']):02d}_{suffix}"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = pathlib.Path(args.output_dir)
    profiles = {
        "clean_scored": pathlib.Path(args.clean_profile),
        "full_diagnostic": pathlib.Path(args.diagnostic_profile),
    }
    runs: list[dict[str, object]] = []
    for planned in plan_run_order(repeats=args.repeats, warmup=args.warmup, order=args.order):
        label = str(planned["label"])
        run_id = _run_id_for(args.run_id_prefix, planned)
        result = run_profile(
            url=args.url,
            run_id=run_id,
            profile=profiles[label],
            output_dir=output_dir,
            timeout_sec=args.timeout_sec,
        )
        row = summarize_live_report(
            result.get("report", {}),
            label=label,
            run_id=run_id,
            returncode=int(result.get("returncode", 0) or 0),
        )
        row.update({
            "repeat": planned["repeat"],
            "warmup": planned["warmup"],
            "report_path": result.get("report_path", ""),
            "stdout_tail": result.get("stdout_tail", ""),
            "stderr_tail": result.get("stderr_tail", ""),
        })
        runs.append(row)
    payload = build_payload(
        run_id_prefix=args.run_id_prefix,
        url=args.url,
        runs=runs,
        repeats=args.repeats,
        warmup=args.warmup,
        order=args.order,
    )
    json_path, md_path = write_reports(payload, output_dir=output_dir)
    print(json.dumps({
        "run_id_prefix": args.run_id_prefix,
        "runs": len(runs),
        "median_p95_delta_ms": payload["delta"]["median_p95_delta_ms"],
        "json_report": str(json_path),
        "markdown_report": str(md_path),
    }, indent=2))
    non_warmup = [row for row in runs if not row.get("warmup")]
    return 0 if non_warmup and all(row.get("report_path") for row in non_warmup) else 2


if __name__ == "__main__":
    raise SystemExit(main())
