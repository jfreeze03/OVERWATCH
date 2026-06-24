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
    measured = [sample for sample in samples if not sample.get("skipped") and not sample.get("diagnostic")]
    return sorted(measured, key=lambda sample: float(sample.get("elapsed_ms", 0) or 0), reverse=True)[:limit]


def _top_slowest_diagnostic_steps(samples: list[dict], limit: int = 10) -> list[dict]:
    measured = [sample for sample in samples if sample.get("diagnostic")]
    return sorted(measured, key=lambda sample: float(sample.get("elapsed_ms", 0) or 0), reverse=True)[:limit]


def _skipped_buttons(samples: list[dict]) -> list[str]:
    skipped = []
    for sample in samples:
        if sample.get("skipped") and str(sample.get("action", "")).startswith("load_button:"):
            skipped.append(f"{sample.get('section', 'unknown')} -> {str(sample.get('action')).split(':', 1)[-1]}")
    return sorted(set(skipped))


def _release_blockers(summary: dict) -> list[dict]:
    blockers = summary.get("release_blockers", [])
    return blockers if isinstance(blockers, list) else []


def _top_rows(summary: dict, key: str, label_key: str, limit: int = 5) -> list[dict]:
    rows = summary.get(key, [])
    if isinstance(rows, list):
        return rows[:limit]
    legacy_key = "by_action" if label_key == "action" else "by_section"
    legacy = summary.get(legacy_key, {})
    if not isinstance(legacy, dict):
        return []
    return [
        {label_key: label, **row}
        for label, row in sorted(
            legacy.items(),
            key=lambda item: float(item[1].get("p95_ms", 0) or 0),
            reverse=True,
        )[:limit]
    ]


def _initial_load_breakdown(summary: dict) -> list[dict]:
    breakdown = summary.get("initial_load_breakdown", [])
    if isinstance(breakdown, list) and breakdown:
        return breakdown
    diagnostic_by_action = summary.get("diagnostic_by_action", {})
    if not isinstance(diagnostic_by_action, dict):
        return []
    rows = [
        {"action": action, **row}
        for action, row in diagnostic_by_action.items()
        if str(action).startswith("initial_load:")
    ]
    return sorted(rows, key=lambda row: float(row.get("p95_ms", 0) or 0), reverse=True)


def _summary_rows(summary: dict, key: str, label_key: str, limit: int = 10) -> list[dict]:
    rows = summary.get(key, [])
    if isinstance(rows, list):
        return rows[:limit]
    return []


def _row_value(rows: list[dict], label_key: str, label: str) -> float:
    for row in rows:
        if row.get(label_key) == label:
            return float(row.get("p95_ms", 0) or 0)
    return 0.0


def _diagnostic_recommendations(summary: dict) -> list[str]:
    recommendations: list[str] = []
    breakdown = _initial_load_breakdown(summary)
    phase_p95 = {
        str(row.get("action", "")).split(":", 1)[-1]: float(row.get("p95_ms", 0) or 0)
        for row in breakdown
    }
    if phase_p95.get("app_ready", 0) > 10000 and (
        phase_p95.get("goto_domcontentloaded", 0) > 10000
        or phase_p95.get("goto_commit", 0) > 10000
        or phase_p95.get("domcontentloaded", 0) > 10000
    ):
        recommendations.append(
            "App-ready and browser response phases are both high; prioritize server first response and Streamlit cold render tuning."
        )
    server_rows = _summary_rows(summary, "server_phase_breakdown", "phase", limit=20)
    server_by_phase = {str(row.get("phase")): float(row.get("p95_ms", 0) or 0) for row in server_rows}
    probe_ms = server_by_phase.get("shell:probe_snowflake_available", 0)
    if probe_ms > 1000:
        recommendations.append(
            "shell:probe_snowflake_available is elevated; tune or cache the connection availability probe before release reruns."
        )
    import_rows = [
        (phase, p95)
        for phase, p95 in server_by_phase.items()
        if phase.startswith("section_dispatch:module_import:")
    ]
    if import_rows:
        phase, p95 = max(import_rows, key=lambda item: item[1])
        if p95 > 1000:
            recommendations.append(
                f"{phase} dominates section dispatch import time; split module imports or move optional dependencies behind workflow load."
            )
    nav_rows = _summary_rows(summary, "browser_navigation_timing", "metric", limit=20)
    paint_rows = _summary_rows(summary, "browser_paint_timing", "metric", limit=20)
    response_start = _row_value(nav_rows, "metric", "responseStart")
    fcp = _row_value(paint_rows, "metric", "first-contentful-paint")
    server_total = server_by_phase.get("shell:total_render_app", 0)
    app_entry_rows = _summary_rows(summary, "app_entry_phase_breakdown", "phase", limit=20)
    app_entry_max = max((float(row.get("p95_ms", 0) or 0) for row in app_entry_rows), default=0.0)
    if response_start > 5000 and fcp > 10000 and server_total < 1500 and app_entry_max < 5000:
        recommendations.append(
            "Server render and app-entry phases are low while responseStart/FCP are high; prioritize Streamlit server concurrency/runtime and browser host capacity before section-code trimming."
        )
    return recommendations


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
    slowest_diagnostic = _top_slowest_diagnostic_steps(samples)
    server_rows = _summary_rows(summary, "server_phase_breakdown", "phase")
    app_entry_rows = _summary_rows(summary, "app_entry_phase_breakdown", "phase")
    nav_rows = _summary_rows(summary, "browser_navigation_timing", "metric")
    paint_rows = _summary_rows(summary, "browser_paint_timing", "metric")
    server_total_p95 = _row_value(server_rows, "phase", "shell:total_render_app")
    app_entry_import_p95 = _row_value(app_entry_rows, "phase", "app_entry:import_shell")
    response_start_p95 = _row_value(nav_rows, "metric", "responseStart")
    fcp_p95 = _row_value(paint_rows, "metric", "first-contentful-paint")
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
        f"- Server render p95: `{server_total_p95} ms`",
        f"- App-entry shell import p95: `{app_entry_import_p95} ms`",
        f"- Browser responseStart p95: `{response_start_p95} ms`",
        f"- Browser first-contentful-paint p95: `{fcp_p95} ms`",
        "- Verdict scale: PASS / WATCH / FAIL",
        "",
        "## Threshold Assessment",
        f"- Live browser step p95 <= 10000 ms: `{'PASS' if float(summary.get('p95_ms', 0) or 0) <= 10000 else 'WATCH'}`",
        f"- Error rate == 0: `{'PASS' if float(summary.get('error_rate', 1) or 0) == 0 else 'FAIL'}`",
        f"- Readiness score >= 95: `{'PASS' if int(summary.get('readiness_score', 0) or 0) >= 95 else 'WATCH'}`",
        "",
        "## Release Blockers",
        "",
    ]
    blockers = _release_blockers(summary)
    if blockers:
        lines.extend(
            f"- `{item.get('type', 'blocker')}`: {item.get('message', '')}"
            for item in blockers
        )
    else:
        lines.append("- None recorded.")
    lines.extend([
        "",
        "## Diagnostic Overhead A/B",
        "",
    ])
    overhead = summary.get("diagnostic_overhead")
    if isinstance(overhead, dict):
        lines.extend([
            f"- Clean profile p95: `{overhead.get('clean_p95_ms', 0)} ms`",
            f"- Diagnostic profile p95: `{overhead.get('diagnostic_p95_ms', 0)} ms`",
            f"- Diagnostic delta: `{overhead.get('p95_delta_ms', 0)} ms`",
        ])
        if float(overhead.get("p95_delta_ms", 0) or 0) > 2500:
            lines.append("- Recommendation: keep diagnostic capture outside the scored release gate.")
    else:
        lines.append("- No diagnostic overhead A/B payload was attached to this live report.")
    lines.extend([
        "",
        "## Top Slowest Sections",
        "",
        "| Section | Steps | Skipped | Errors | P95 ms | Max ms |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    top_sections = _top_rows(summary, "top_slowest_sections", "section")
    for row in top_sections:
        lines.append(
            f"| {row.get('section', '')} | {row.get('steps', '')} | {row.get('skipped', '')} | "
            f"{row.get('errors', '')} | {row.get('p95_ms', 0)} | {row.get('max_ms', 0)} |"
        )
    if not top_sections:
        lines.append("| n/a | 0 | 0 | 0 | 0 | 0 |")
    lines.extend([
        "",
        "## Top Slowest Actions",
        "",
        "| Action | Steps | Skipped | Errors | P95 ms | Max ms |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    top_actions = _top_rows(summary, "top_slowest_actions", "action")
    for row in top_actions:
        lines.append(
            f"| {row.get('action', '')} | {row.get('steps', '')} | {row.get('skipped', '')} | "
            f"{row.get('errors', '')} | {row.get('p95_ms', 0)} | {row.get('max_ms', 0)} |"
        )
    if not top_actions:
        lines.append("| n/a | 0 | 0 | 0 | 0 | 0 |")
    breakdown = _initial_load_breakdown(summary)
    if breakdown:
        slowest_phase = max(breakdown, key=lambda row: float(row.get("p95_ms", 0) or 0))
        phase_name = str(slowest_phase.get("action", "")).split(":", 1)[-1]
        lines.extend([
            "",
            "## Initial Load Breakdown",
            "",
            "| Phase | Steps | Errors | P95 ms | Max ms |",
            "|---|---:|---:|---:|---:|",
        ])
        for row in breakdown:
            phase = str(row.get("action", "")).split(":", 1)[-1]
            lines.append(
                f"| {phase} | {row.get('steps', '')} | {row.get('errors', '')} | "
                f"{row.get('p95_ms', 0)} | {row.get('max_ms', 0)} |"
            )
        lines.extend([
            "",
            f"- Slowest initial-load phase: `{phase_name}`.",
            f"- Recommendation: tune `{phase_name}` first, then rerun the same 12-user profile so release p95 remains comparable.",
        ])
    lines.extend([
        "",
        "## Server Phase Breakdown",
        "",
    ])
    if server_rows:
        lines.extend(["| Phase | Samples | P95 ms | Max ms |", "|---|---:|---:|---:|"])
        for row in server_rows:
            lines.append(f"| {row.get('phase', '')} | {row.get('steps', '')} | {row.get('p95_ms', 0)} | {row.get('max_ms', 0)} |")
    else:
        lines.append("- No server-side phase trace was collected.")
    lines.extend([
        "",
        "## App Entry Phase Breakdown",
        "",
    ])
    if app_entry_rows:
        lines.extend(["| Phase | Samples | P95 ms | Max ms |", "|---|---:|---:|---:|"])
        for row in app_entry_rows:
            lines.append(
                f"| {row.get('phase', '')} | {row.get('steps', '')} | {row.get('p95_ms', 0)} | {row.get('max_ms', 0)} |"
            )
    else:
        lines.append("- No app-entry import phase trace was collected.")
    lines.extend([
        "",
        "## Browser Navigation Timing",
        "",
    ])
    if nav_rows:
        lines.extend(["| Metric | Samples | P95 ms/bytes | Max ms/bytes |", "|---|---:|---:|---:|"])
        for row in nav_rows:
            lines.append(f"| {row.get('metric', '')} | {row.get('samples', '')} | {row.get('p95_ms', 0)} | {row.get('max_ms', 0)} |")
    else:
        lines.append("- No browser navigation timing was collected.")
    lines.extend([
        "",
        "## Browser Paint Timing",
        "",
    ])
    if paint_rows:
        lines.extend(["| Metric | Samples | P95 ms | Max ms |", "|---|---:|---:|---:|"])
        for row in paint_rows:
            lines.append(f"| {row.get('metric', '')} | {row.get('samples', '')} | {row.get('p95_ms', 0)} | {row.get('max_ms', 0)} |")
    else:
        lines.append("- No browser paint timing was collected.")
    lines.extend([
        "",
        "## Frontend Paint Metrics",
        "",
    ])
    dom_rows = summary.get("frontend_dom_metrics", [])
    if isinstance(dom_rows, list) and dom_rows:
        lines.extend(["| DOM/CSS metric | Samples | P95 | Max |", "|---|---:|---:|---:|"])
        for row in dom_rows:
            lines.append(
                f"| {row.get('metric', '')} | {row.get('samples', '')} | {row.get('p95', 0)} | {row.get('max', 0)} |"
            )
    else:
        lines.append("- No frontend DOM/CSS metrics were collected.")
    resource_rows = summary.get("frontend_resource_timing", [])
    if isinstance(resource_rows, list) and resource_rows:
        lines.extend([
            "",
            "| Resource initiator | Samples | Count p95 | Duration p95 ms | Transfer p95 |",
            "|---|---:|---:|---:|---:|",
        ])
        for row in resource_rows:
            lines.append(
                f"| {row.get('initiator_type', '')} | {row.get('samples', '')} | {row.get('count_p95', 0)} | "
                f"{row.get('duration_p95_ms', 0)} | {row.get('transfer_size_p95', 0)} |"
            )
    lines.extend([
        "",
        "## Slowest User Correlation",
        "",
    ])
    matrix = summary.get("initial_load_matrix", [])
    if isinstance(matrix, list) and matrix:
        lines.extend([
            "| User | Initial load ms | responseStart | FCP | Top app-entry phase | Top server phase |",
            "|---:|---:|---:|---:|---|---|",
        ])
        for row in matrix[:10]:
            nav = row.get("browser_navigation_timing") if isinstance(row, dict) else {}
            paint = row.get("browser_paint_timing") if isinstance(row, dict) else {}
            app_entry = row.get("top_app_entry_phase") if isinstance(row, dict) else {}
            server = row.get("top_server_phase") if isinstance(row, dict) else {}
            response_start = nav.get("responseStart", "") if isinstance(nav, dict) else ""
            fcp = paint.get("first-contentful-paint", "") if isinstance(paint, dict) else ""
            app_phase = (
                f"{app_entry.get('phase', '')} {app_entry.get('elapsed_ms', '')} ms"
                if isinstance(app_entry, dict) and app_entry else ""
            )
            server_phase = (
                f"{server.get('phase', '')} {server.get('elapsed_ms', '')} ms"
                if isinstance(server, dict) and server else ""
            )
            lines.append(
                f"| {row.get('user_id', '')} | {row.get('release_initial_load_ms', '')} | "
                f"{response_start} | {fcp} | {app_phase} | {server_phase} |"
            )
    else:
        lines.append("- No per-user initial-load correlation rows were collected.")
    lines.extend([
        "",
        "## Playwright Host Resource Samples",
        "",
    ])
    resource_samples = summary.get("resource_samples", [])
    if isinstance(resource_samples, list) and resource_samples:
        lines.extend(["| Label | CPU % | Memory % | Processes | Browser children |", "|---|---:|---:|---:|---:|"])
        for row in resource_samples[:20]:
            lines.append(
                f"| {row.get('label', '')} | {row.get('cpu_percent', '')} | {row.get('memory_percent', '')} | "
                f"{row.get('process_count', '')} | {row.get('browser_child_process_count', '')} |"
            )
    else:
        lines.append("- No Playwright host resource samples were collected.")
    lines.extend([
        "",
        "## Expert Panel",
        "",
    ])
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
        "## Skipped Button Context",
        "",
    ])
    skipped_details = summary.get("skipped_button_details", [])
    if isinstance(skipped_details, list) and skipped_details:
        for row in skipped_details[:10]:
            detail = row.get("detail", {}) if isinstance(row, dict) else {}
            if not isinstance(detail, dict):
                detail = {}
            buttons = ", ".join(str(item) for item in detail.get("visible_button_labels", [])[:12])
            lines.extend([
                f"- User `{row.get('user_id')}` iteration `{row.get('iteration')}` section `{row.get('section')}` action `{row.get('action')}`",
                f"  - Active title: `{detail.get('active_section_title', '')}`",
                f"  - Visible buttons: `{buttons}`",
                f"  - Screenshot: `{detail.get('screenshot_path', '')}`",
            ])
    else:
        lines.append("- No skipped-button context was captured.")
    lines.extend([
        "",
        "## Top 10 Slowest Release Steps",
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
        "## Top 10 Slowest Diagnostic Steps",
        "",
        "| User | Iteration | Section | Action | Elapsed ms | Status |",
        "|---:|---:|---|---|---:|---|",
    ])
    for sample in slowest_diagnostic:
        lines.append(
            f"| {sample.get('user_id', '')} | {sample.get('iteration', '')} | {sample.get('section', '')} | "
            f"{sample.get('action', '')} | {float(sample.get('elapsed_ms', 0) or 0):.2f} | "
            f"{'OK' if sample.get('ok') else 'FAIL'} |"
        )
    if not slowest_diagnostic:
        lines.append("|  |  | n/a | n/a | 0.00 | n/a |")
    diagnostic_recommendations = _diagnostic_recommendations(summary)
    lines.extend([
        "",
        "## Recommended Next Engineering Actions",
        "- Tune the slowest section/action first, then rerun the same profile.",
        "- Pair browser latency with Snowflake Query History and PERF_TEST_* views when credentials are available.",
        "- Keep any new benchmark load button behind the forbidden-action safety guard.",
    ])
    lines.extend(f"- {item}" for item in diagnostic_recommendations)
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
