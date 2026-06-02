#!/usr/bin/env python
"""Browser-driven OVERWATCH section smoke runner.

The HTTP runner proves the Streamlit server can answer requests. This runner
uses a real browser to click the primary navigation buttons and measure visible
section switch time. It does not create Snowflake objects or run Snowflake SQL.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import math
import pathlib
import time
import uuid


DEFAULT_OUTPUT_DIR = pathlib.Path(__file__).resolve().parent / "results"
DEFAULT_SECTIONS = [
    "DBA Control Room",
    "Alert Center",
    "Account Health",
    "Workload Operations",
    "Warehouse Health",
    "Architecture Readiness",
    "Cost & Contract",
    "Security Posture",
    "Change & Drift",
]


@dataclasses.dataclass
class SectionSample:
    section: str
    elapsed_ms: float
    ok: bool
    error: str = ""


def percentile(values: list[float], pct: float) -> float:
    clean = sorted(float(value) for value in values if value is not None)
    if not clean:
        return 0.0
    rank = math.ceil((pct / 100.0) * len(clean)) - 1
    return clean[max(0, min(rank, len(clean) - 1))]


def load_playwright():
    """Import Playwright lazily so unit tests and HTTP-only runs stay lightweight."""
    try:
        from playwright.sync_api import sync_playwright

        return sync_playwright, None
    except Exception as exc:
        return None, exc


def wait_for_section(page, section: str, timeout_ms: int) -> None:
    title = page.locator(".ow-section-title").filter(has_text=section).first
    title.wait_for(state="visible", timeout=timeout_ms)
    try:
        page.locator(".ow-section-transition").wait_for(state="detached", timeout=timeout_ms)
    except Exception:
        pass


def wait_for_app_ready(page, timeout_ms: int) -> None:
    """Wait until the Streamlit shell has finished initial header hydration."""
    page.locator(".ow-section-title").first.wait_for(state="visible", timeout=timeout_ms)
    try:
        page.locator(".ow-section-transition").wait_for(state="detached", timeout=timeout_ms)
    except Exception:
        pass


def run_sections(args: argparse.Namespace) -> list[SectionSample]:
    sync_playwright, import_error = load_playwright()
    if import_error:
        raise RuntimeError(
            "Playwright is required for section smoke tests. Install it in the test environment "
            "or use perf_runner.py for HTTP-only load tests."
        ) from import_error

    samples: list[SectionSample] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed)
        context = browser.new_context(
            viewport={"width": args.width, "height": args.height},
            extra_http_headers={"X-OVERWATCH-PERF-RUN-ID": args.run_id},
        )
        page = context.new_page()
        page.goto(args.url, wait_until="domcontentloaded", timeout=args.timeout_ms)
        page.wait_for_timeout(args.initial_wait_ms)
        wait_for_app_ready(page, args.timeout_ms)

        for section in args.sections:
            started = time.perf_counter()
            try:
                page.get_by_role("button", name=section, exact=True).click(timeout=args.timeout_ms)
                wait_for_section(page, section, args.timeout_ms)
                elapsed_ms = (time.perf_counter() - started) * 1000
                samples.append(SectionSample(section=section, elapsed_ms=elapsed_ms, ok=True))
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - started) * 1000
                samples.append(
                    SectionSample(
                        section=section,
                        elapsed_ms=elapsed_ms,
                        ok=False,
                        error=str(exc).replace("\n", " ")[:500],
                    )
                )
        context.close()
        browser.close()
    return samples


def summarize(samples: list[SectionSample], fail_p95_ms: float, fail_error_rate: float) -> dict:
    elapsed = [sample.elapsed_ms for sample in samples]
    errors = sum(1 for sample in samples if not sample.ok)
    error_rate = errors / len(samples) if samples else 1.0
    p95_ms = percentile(elapsed, 95)
    score = 100
    if p95_ms > fail_p95_ms:
        score -= min(40, int((p95_ms - fail_p95_ms) / max(fail_p95_ms, 1) * 40) + 10)
    if error_rate > fail_error_rate:
        score -= min(45, int((error_rate - fail_error_rate) * 100) + 20)
    score = max(0, min(100, score))
    state = "PASS" if score >= 95 and error_rate <= fail_error_rate and p95_ms <= fail_p95_ms else "WATCH"
    if score < 85:
        state = "FAIL"
    slowest = max(samples, key=lambda sample: sample.elapsed_ms).section if samples else ""
    return {
        "sections": len(samples),
        "errors": errors,
        "error_rate": round(error_rate, 4),
        "p50_ms": round(percentile(elapsed, 50), 2),
        "p95_ms": round(p95_ms, 2),
        "max_ms": round(max(elapsed), 2) if elapsed else 0.0,
        "slowest_section": slowest,
        "readiness_score": score,
        "readiness_state": state,
        "fail_p95_ms": fail_p95_ms,
        "fail_error_rate": fail_error_rate,
    }


def write_reports(args: argparse.Namespace, samples: list[SectionSample], summary: dict) -> tuple[pathlib.Path, pathlib.Path]:
    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": args.run_id,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "url": args.url,
        "summary": summary,
        "samples": [dataclasses.asdict(sample) for sample in samples],
    }
    json_path = output_dir / f"{args.run_id}_sections.json"
    md_path = output_dir / f"{args.run_id}_sections.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    md = [
        f"# OVERWATCH Section Smoke Run {args.run_id}",
        "",
        f"- URL: `{args.url}`",
        f"- Readiness: **{summary['readiness_state']}** ({summary['readiness_score']}/100)",
        f"- Sections: {summary['sections']} total, {summary['errors']} errors ({summary['error_rate'] * 100:.2f}%)",
        f"- Latency: p50 {summary['p50_ms']} ms, p95 {summary['p95_ms']} ms, max {summary['max_ms']} ms",
        f"- Slowest section: {summary['slowest_section'] or 'n/a'}",
        "",
        "## Section Results",
        "",
        "| Section | Status | Elapsed ms | Error |",
        "|---|---:|---:|---|",
    ]
    for sample in sorted(samples, key=lambda item: item.elapsed_ms, reverse=True):
        md.append(
            f"| {sample.section} | {'OK' if sample.ok else 'FAIL'} | "
            f"{sample.elapsed_ms:.2f} | {sample.error[:160]} |"
        )
    md.extend([
        "",
        "## How To Use This",
        "",
        "- A slow section here means the DBA feels lag after clicking navigation, even if the HTTP runner passes.",
        "- Pair slow section names with `PERF_TEST_APP_USAGE_REPORT_V` and `PERF_TEST_SNOWFLAKE_QUERY_REPORT_V` to find the query or render path.",
        "- Keep this run small and repeatable; use it after interface, caching, or architecture changes.",
    ])
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return json_path, md_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Click primary OVERWATCH sections and measure visible render time.")
    parser.add_argument("--url", default="http://localhost:8501/", help="Dashboard URL to test.")
    parser.add_argument("--sections", nargs="*", default=DEFAULT_SECTIONS, help="Section button labels to click.")
    parser.add_argument("--timeout-ms", type=int, default=15000, help="Per-section browser timeout.")
    parser.add_argument("--initial-wait-ms", type=int, default=1000, help="Initial page settle time before clicking.")
    parser.add_argument("--width", type=int, default=1440, help="Browser viewport width.")
    parser.add_argument("--height", type=int, default=1000, help="Browser viewport height.")
    parser.add_argument("--headed", action="store_true", help="Run with a visible browser window.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for JSON and Markdown reports.")
    parser.add_argument("--run-id", default=f"PERF_TEST_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}")
    parser.add_argument("--fail-p95-ms", type=float, default=7500.0, help="Fail threshold for section switch p95.")
    parser.add_argument("--fail-error-rate", type=float, default=0.0, help="Fail threshold for section click errors.")
    args = parser.parse_args()
    if args.timeout_ms < 1000:
        parser.error("--timeout-ms must be at least 1000.")
    return args


def main() -> int:
    args = parse_args()
    try:
        samples = run_sections(args)
    except Exception as exc:
        print(json.dumps({
            "run_id": args.run_id,
            "readiness_state": "BLOCKED",
            "error": str(exc),
        }, indent=2))
        return 3
    summary = summarize(samples, args.fail_p95_ms, args.fail_error_rate)
    json_path, md_path = write_reports(args, samples, summary)
    print(json.dumps({
        "run_id": args.run_id,
        "readiness_state": summary["readiness_state"],
        "readiness_score": summary["readiness_score"],
        "p95_ms": summary["p95_ms"],
        "slowest_section": summary["slowest_section"],
        "json_report": str(json_path),
        "markdown_report": str(md_path),
    }, indent=2))
    return 0 if summary["readiness_state"] in {"PASS", "WATCH"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
