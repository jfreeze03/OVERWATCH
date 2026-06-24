#!/usr/bin/env python
"""Generate a deterministic expert review for an OVERWATCH power-user run."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib


DEFAULT_OUTPUT_DIR = pathlib.Path(__file__).resolve().parent / "results"


def _read_json(path: str | pathlib.Path) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _summary(payload: dict) -> dict:
    return payload.get("summary", {}) if isinstance(payload, dict) else {}


def _samples(payload: dict) -> list[dict]:
    samples = payload.get("samples", []) if isinstance(payload, dict) else []
    return samples if isinstance(samples, list) else []


def _verdict(summary: dict) -> str:
    state = str(summary.get("readiness_state", "")).upper()
    if state in {"PASS", "WATCH", "FAIL", "BLOCKED"}:
        return "FAIL" if state == "BLOCKED" else state
    errors = int(summary.get("errors", 0) or 0)
    p95_ms = float(summary.get("p95_ms", 0) or 0)
    if errors:
        return "FAIL"
    if p95_ms > 10000:
        return "WATCH"
    return "PASS"


def _slowest_section(summary: dict) -> str:
    by_section = summary.get("by_section", {})
    if not by_section:
        return str(summary.get("slowest_section") or "n/a")
    section, _ = max(by_section.items(), key=lambda item: item[1].get("p95_ms", 0))
    return section


def _slowest_action(summary: dict) -> str:
    by_action = summary.get("by_action", {})
    if not by_action:
        slowest = summary.get("slowest_step", {})
        return str(slowest.get("action") or "n/a") if isinstance(slowest, dict) else "n/a"
    action, _ = max(by_action.items(), key=lambda item: item[1].get("p95_ms", 0))
    return action


def _top_slowest_steps(samples: list[dict], limit: int = 10) -> list[dict]:
    measured = [sample for sample in samples if not sample.get("skipped")]
    return sorted(measured, key=lambda sample: float(sample.get("elapsed_ms", 0) or 0), reverse=True)[:limit]


def _skipped_buttons(samples: list[dict]) -> list[str]:
    skipped = []
    for sample in samples:
        if sample.get("skipped") and str(sample.get("action", "")).startswith("load_button:"):
            skipped.append(f"{sample.get('section', 'unknown')} -> {str(sample.get('action')).split(':', 1)[-1]}")
    return sorted(set(skipped))


def _panel_rows(summary: dict, section_summary: dict | None) -> list[dict]:
    p95_ms = float(summary.get("p95_ms", 0) or 0)
    p99_ms = float(summary.get("p99_ms", 0) or 0)
    errors = int(summary.get("errors", 0) or 0)
    skipped = int(summary.get("skipped", 0) or 0)
    readiness = int(summary.get("readiness_score", 0) or 0)
    state = _verdict(summary)
    section_state = str((section_summary or {}).get("readiness_state", "")).upper()

    snowflake_verdict = "PASS" if state == "PASS" else state
    sre_verdict = "PASS" if p95_ms <= 10000 and errors == 0 else ("WATCH" if p95_ms <= 20000 else "FAIL")
    ux_verdict = "PASS" if section_state in {"", "PASS"} and p99_ms <= 18000 else "WATCH"
    finops_verdict = "WATCH" if skipped or p95_ms > 8000 else "PASS"
    security_verdict = "PASS" if errors == 0 else "WATCH"
    dba_verdict = "PASS" if readiness >= 95 and errors == 0 else ("WATCH" if readiness >= 85 else "FAIL")
    return [
        {
            "role": "Snowflake architect",
            "verdict": snowflake_verdict,
            "evidence": f"p95 {p95_ms:.2f} ms, p99 {p99_ms:.2f} ms, errors {errors}",
            "risks": "Slow live loads can indicate mart/cache misses or query-history pressure.",
            "fixes": "Compare slowest steps with Snowflake Query History and PERF_TEST_* views.",
        },
        {
            "role": "SRE/performance engineer",
            "verdict": sre_verdict,
            "evidence": f"Readiness {readiness}/100, error rate {summary.get('error_rate', 0)}",
            "risks": "Concurrency spikes can expose websocket rerun contention or cold-start gaps.",
            "fixes": "Tune slow sections first and rerun the 12-user profile before release.",
        },
        {
            "role": "Streamlit UX engineer",
            "verdict": ux_verdict,
            "evidence": f"Slowest section {_slowest_section(summary)}, slowest action {_slowest_action(summary)}",
            "risks": "Long reruns or invisible load controls create operator uncertainty.",
            "fixes": "Keep first paint mart-backed and move deep evidence behind explicit controls.",
        },
        {
            "role": "FinOps/cost reviewer",
            "verdict": finops_verdict,
            "evidence": f"Skipped load buttons {skipped}, throughput {summary.get('throughput_steps_per_sec', 0)} steps/sec",
            "risks": "Live loads can create shared-warehouse cost unless paired with query-history evidence.",
            "fixes": "Pair the browser report with Snowflake Query History for exact credit attribution.",
        },
        {
            "role": "Security/admin reviewer",
            "verdict": security_verdict,
            "evidence": "Profile uses guarded read/load buttons only.",
            "risks": "Benchmark profiles must never include queue, grant, email, task, or admin mutation controls.",
            "fixes": "Keep profile validation in place and review any new load button before enabling it.",
        },
        {
            "role": "DBA/operator",
            "verdict": dba_verdict,
            "evidence": f"Readiness state {_verdict(summary)}, slowest section {_slowest_section(summary)}",
            "risks": "Daily DBA triage slows down if navigation and default live loads exceed thresholds.",
            "fixes": "Prioritize the top slowest steps and rerun section smoke plus 12-user concurrency.",
        },
    ]


def build_review(
    live_payload: dict,
    *,
    section_payload: dict | None = None,
    snowflake_doc: str | None = None,
) -> str:
    summary = _summary(live_payload)
    samples = _samples(live_payload)
    section_summary = _summary(section_payload or {}) if section_payload else None
    run_id = live_payload.get("run_id", "unknown")
    skipped = _skipped_buttons(samples)
    slowest = _top_slowest_steps(samples)
    overall = _verdict(summary)
    meets_thresholds = (
        overall == "PASS"
        and float(summary.get("p95_ms", 0) or 0) <= float(summary.get("fail_p95_ms", 10000) or 10000)
        and float(summary.get("error_rate", 1) or 0) <= float(summary.get("fail_error_rate", 0) or 0)
        and int(summary.get("readiness_score", 0) or 0) >= 95
    )

    lines = [
        f"# OVERWATCH 12 Power User Expert Review {run_id}",
        "",
        "## Executive Summary",
        f"- Verdict: **{overall}**",
        f"- Release thresholds met: `{'yes' if meets_thresholds else 'no'}`",
        f"- Users: `{summary.get('users', 'n/a')}`",
        f"- Iterations: `{summary.get('iterations', 'n/a')}`",
        f"- p50/p95/p99/max: `{summary.get('p50_ms', 0)} / {summary.get('p95_ms', 0)} / {summary.get('p99_ms', 0)} / {summary.get('max_ms', 0)} ms`",
        f"- Error rate: `{summary.get('error_rate', 0)}`",
        f"- Slowest section: `{_slowest_section(summary)}`",
        f"- Slowest action: `{_slowest_action(summary)}`",
        "- Verdict scale: PASS / WATCH / FAIL",
        "",
        "## Threshold Assessment",
        f"- Live browser step p95 <= 10000 ms: `{'PASS' if float(summary.get('p95_ms', 0) or 0) <= 10000 else 'WATCH'}`",
        f"- Error rate == 0: `{'PASS' if float(summary.get('error_rate', 1) or 0) == 0 else 'FAIL'}`",
        f"- Readiness score >= 95: `{'PASS' if int(summary.get('readiness_score', 0) or 0) >= 95 else 'WATCH'}`",
        "",
        "## Expert Panel",
        "",
    ]
    for row in _panel_rows(summary, section_summary):
        lines.extend([
            f"### {row['role']}",
            f"- Verdict: {row['verdict']}",
            f"- Evidence: {row['evidence']}",
            f"- Top risks: {row['risks']}",
            f"- Recommended fixes: {row['fixes']}",
            "",
        ])
    lines.extend([
        "## Skipped Buttons",
        "",
    ])
    if skipped:
        lines.extend(f"- {item}" for item in skipped)
    else:
        lines.append("- None recorded.")
    lines.extend([
        "",
        "## Top 10 Slowest Steps",
        "",
        "| User | Iteration | Section | Action | Elapsed ms | Status |",
        "|---:|---:|---|---|---:|---|",
    ])
    for sample in slowest:
        lines.append(
            f"| {sample.get('user_id', '')} | {sample.get('iteration', '')} | {sample.get('section', '')} | "
            f"{sample.get('action', '')} | {float(sample.get('elapsed_ms', 0) or 0):.2f} | "
            f"{'OK' if sample.get('ok') else 'FAIL'} |"
        )
    if not slowest:
        lines.append("|  |  | n/a | n/a | 0.00 | n/a |")
    lines.extend([
        "",
        "## Recommended Next Engineering Actions",
        "- Tune the slowest section/action first, then rerun the same profile.",
        "- Pair browser latency with Snowflake Query History and PERF_TEST_* views when credentials are available.",
        "- Keep any new benchmark load button behind the forbidden-action safety guard.",
    ])
    if snowflake_doc:
        lines.extend(["", "## Snowflake Evidence", f"- Snowflake regression/results reference: `{snowflake_doc}`"])
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a deterministic expert review from OVERWATCH perf reports.")
    parser.add_argument("--live-report", required=True, help="live_concurrent_runner JSON report path.")
    parser.add_argument("--section-report", help="Optional section_smoke_runner JSON report path.")
    parser.add_argument("--snowflake-results", help="Optional Snowflake regression results doc path.")
    parser.add_argument("--output", help="Optional Markdown output path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    live_path = pathlib.Path(args.live_report)
    live_payload = _read_json(live_path)
    section_payload = _read_json(args.section_report) if args.section_report else None
    markdown = build_review(
        live_payload,
        section_payload=section_payload,
        snowflake_doc=args.snowflake_results,
    )
    run_id = live_payload.get("run_id", live_path.stem.replace("_live_concurrent", ""))
    output = pathlib.Path(args.output) if args.output else DEFAULT_OUTPUT_DIR / f"{run_id}_expert_review.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    print(str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
