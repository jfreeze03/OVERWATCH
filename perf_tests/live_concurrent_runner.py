#!/usr/bin/env python
"""Concurrent browser stress runner for live OVERWATCH data paths.

This runner uses real browser contexts so Streamlit websocket sessions, reruns,
section navigation, and live-data load buttons are exercised together. It is
intended for bounded DBA performance tests; it does not click admin actions,
grant buttons, warehouse setting changes, email delivery, or queue mutations.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime as dt
import json
import math
import pathlib
import statistics
import time
import uuid


DEFAULT_OUTPUT_DIR = pathlib.Path(__file__).resolve().parent / "results"

DEFAULT_SECTIONS = [
    "DBA Control Room",
    "Alert Center",
    "Cost & Contract",
    "Workload Operations",
    "Security Monitoring",
]

# Default live actions must match the current top-level DBA landing flow. Deep
# drilldown buttons can still be tested with section-specific browser scripts,
# but they should not appear as skipped work in the broad concurrency profile.
DEFAULT_LOAD_BUTTONS = {
    "Alert Center": "Load Active Alerts",
    "Cost & Contract": "Refresh Cost",
}

FORBIDDEN_LOAD_BUTTON_TOKENS = (
    "grant",
    "save",
    "queue",
    "email",
    "send",
    "retry",
    "suspend",
    "resume",
    "execute",
    "cancel",
    "drop",
    "alter",
    "create",
    "delete",
    "deactivate",
    "route to action queue",
)

VISIBLE_ERROR_PATTERNS = (
    "Traceback",
    "StreamlitAPIException",
    "NameError",
    "TypeError",
    "ValueError",
    "ProgrammingError",
    "OperationalError",
    "DatabaseError",
    "SQL compilation error",
    "object does not exist",
    "not authorized",
)


@dataclasses.dataclass
class StepSample:
    user_id: int
    iteration: int
    section: str
    action: str
    elapsed_ms: float
    ok: bool
    error: str = ""
    visible_error: str = ""
    browser_errors: int = 0
    browser_error_messages: list[str] = dataclasses.field(default_factory=list)
    skipped: bool = False


def percentile(values: list[float], pct: float) -> float:
    clean = sorted(float(value) for value in values if value is not None)
    if not clean:
        return 0.0
    if pct <= 0:
        return clean[0]
    if pct >= 100:
        return clean[-1]
    rank = math.ceil((pct / 100.0) * len(clean)) - 1
    return clean[max(0, min(rank, len(clean) - 1))]


def load_playwright():
    """Import Playwright lazily so normal unit tests stay lightweight."""
    try:
        from playwright.async_api import async_playwright

        return async_playwright, None
    except Exception as exc:
        return None, exc


def _default_config() -> dict:
    return {
        "url": "http://localhost:8501/",
        "users": 8,
        "iterations": 1,
        "sections": list(DEFAULT_SECTIONS),
        "load_buttons": True,
        "expand_load_surfaces": True,
        "missing_load_button": "skip",
        "missing_load_button_wait_ms": 3000,
        "stop_user_on_error": False,
        "fail_console_errors": False,
        "timeout_ms": 60000,
        "initial_wait_ms": 1200,
        "wait_initial_idle": False,
        "single_initial_load": False,
        "action_settle_ms": 900,
        "ramp_seconds": 5.0,
        "width": 1440,
        "height": 1000,
        "headed": False,
        "allow_large_run": False,
        "output_dir": str(DEFAULT_OUTPUT_DIR),
        "run_id": f"PERF_LIVE_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
        "fail_p95_ms": 20000.0,
        "fail_error_rate": 0.0,
        "profile": None,
    }


def validate_safe_load_button_label(label: str) -> str:
    text = str(label or "").strip()
    if not text:
        raise ValueError("load button labels must be non-empty strings")
    lowered = text.lower()
    for token in FORBIDDEN_LOAD_BUTTON_TOKENS:
        if token in lowered:
            raise ValueError(f"unsafe load button label rejected: {text!r}")
    return text


def normalize_load_buttons(value) -> bool | dict[str, str]:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        normalized: dict[str, str] = {}
        for section, label in value.items():
            section_text = str(section or "").strip()
            if not section_text:
                raise ValueError("load button mapping sections must be non-empty strings")
            normalized[section_text] = validate_safe_load_button_label(str(label))
        return normalized
    raise ValueError("load_buttons must be true, false, or a section-to-button mapping")


def active_load_button_map(value) -> dict[str, str]:
    normalized = normalize_load_buttons(value)
    if normalized is True:
        return dict(DEFAULT_LOAD_BUTTONS)
    if normalized is False:
        return {}
    return dict(normalized)


def load_profile_defaults(profile_path: str | pathlib.Path) -> dict:
    path = pathlib.Path(profile_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("profile must be a JSON object")
    allowed = set(_default_config()) - {"run_id", "profile"}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"unsupported profile keys: {', '.join(unknown)}")
    profile = dict(data)
    if "sections" in profile:
        sections = profile["sections"]
        if not isinstance(sections, list) or not all(str(item).strip() for item in sections):
            raise ValueError("profile sections must be a non-empty string list")
        profile["sections"] = [str(item).strip() for item in sections]
    if "load_buttons" in profile:
        profile["load_buttons"] = normalize_load_buttons(profile["load_buttons"])
    return profile


async def collect_visible_error(page) -> str:
    """Return the first visible app exception signal, if one is present."""
    try:
        return await page.evaluate(
            """patterns => {
                const text = document.body ? document.body.innerText : "";
                for (const pattern of patterns) {
                    const index = text.indexOf(pattern);
                    if (index >= 0) {
                        const start = Math.max(0, index - 120);
                        const end = Math.min(text.length, index + 360);
                        return text.slice(start, end).replace(/\\s+/g, " ").trim();
                    }
                }
                return "";
            }""",
            list(VISIBLE_ERROR_PATTERNS),
        )
    except Exception as exc:
        return f"visible-error-check-failed: {str(exc)[:240]}"


async def expand_hidden_load_surfaces(page) -> None:
    """Open collapsed Streamlit expanders so safe load buttons are reachable."""
    try:
        await page.evaluate(
            """() => {
                document.querySelectorAll("details:not([open])").forEach(detail => {
                    detail.open = true;
                });
            }"""
        )
    except Exception:
        # Expander opening is a convenience, not a test blocker.
        return


async def wait_for_streamlit_idle(page, timeout_ms: int, settle_ms: int) -> None:
    """Wait for Streamlit spinner-like elements to clear after a click."""
    await page.wait_for_timeout(settle_ms)
    deadline = time.perf_counter() + timeout_ms / 1000.0
    observed_busy = False
    while time.perf_counter() < deadline:
        try:
            busy = await page.evaluate(
                """() => {
                    const visible = (element) => {
                        if (!element) return false;
                        const style = window.getComputedStyle(element);
                        return style.visibility !== "hidden"
                            && style.display !== "none"
                            && element.getClientRects().length > 0;
                    };
                    const spinners = Array.from(
                        document.querySelectorAll('[data-testid="stSpinner"], .stSpinner')
                    ).filter(visible);
                    const statuses = Array.from(
                        document.querySelectorAll('[data-testid="stStatusWidget"], [data-testid="stStatus"]')
                    ).filter((element) => visible(element) && /running|loading|please wait/i.test(element.innerText || ""));
                    return spinners.length > 0 || statuses.length > 0;
                }"""
            )
        except Exception:
            return
        if not busy:
            if observed_busy:
                await page.wait_for_timeout(250)
            return
        observed_busy = True
        await page.wait_for_timeout(500)


async def wait_for_section(page, section: str, timeout_ms: int) -> None:
    title = page.locator(".ow-section-title").filter(has_text=section).first
    await title.wait_for(state="visible", timeout=timeout_ms)
    try:
        await page.locator(".ow-section-transition").wait_for(state="detached", timeout=timeout_ms)
    except Exception:
        pass


async def wait_for_app_ready(page, timeout_ms: int) -> None:
    await page.locator(".ow-section-title").first.wait_for(state="visible", timeout=timeout_ms)
    try:
        await page.locator(".ow-section-transition").wait_for(state="detached", timeout=timeout_ms)
    except Exception:
        pass


async def section_is_visible(page, section: str) -> bool:
    try:
        title = page.locator(".ow-section-title").filter(has_text=section).first
        return await title.is_visible(timeout=250)
    except Exception:
        return False


async def wait_for_named_button(page, label: str, timeout_ms: int):
    button = page.get_by_role("button", name=label, exact=True)
    deadline = time.perf_counter() + timeout_ms / 1000.0
    last_error = ""
    while time.perf_counter() < deadline:
        try:
            count = await button.count()
            if count > 0:
                return button.first
        except Exception as exc:
            last_error = str(exc).replace("\n", " ")[:240]
        await page.wait_for_timeout(250)
    suffix = f" ({last_error})" if last_error else ""
    raise RuntimeError(f"button not found: {label}{suffix}")


async def click_named_button(page, label: str, timeout_ms: int) -> None:
    button = await wait_for_named_button(page, label, timeout_ms)
    await button.click(timeout=timeout_ms)


async def click_optional_named_button(page, label: str, timeout_ms: int, missing_behavior: str, missing_wait_ms: int) -> bool:
    button_wait_ms = timeout_ms if missing_behavior == "fail" else min(timeout_ms, missing_wait_ms)
    try:
        button = await wait_for_named_button(page, label, button_wait_ms)
    except Exception:
        if missing_behavior == "skip":
            return False
        raise
    await button.click(timeout=timeout_ms)
    return True


async def timed_step(
    *,
    page,
    user_id: int,
    iteration: int,
    section: str,
    action: str,
    browser_errors: list[str],
    operation,
) -> StepSample:
    before_browser_errors = len(browser_errors)
    started = time.perf_counter()
    try:
        result = await operation()
        elapsed_ms = (time.perf_counter() - started) * 1000
        visible_error = await collect_visible_error(page)
        new_browser_messages = browser_errors[before_browser_errors:]
        new_browser_errors = len(new_browser_messages)
        skipped = result == "skipped"
        ok = skipped or (not visible_error and new_browser_errors == 0)
        return StepSample(
            user_id=user_id,
            iteration=iteration,
            section=section,
            action=action,
            elapsed_ms=elapsed_ms,
            ok=ok,
            visible_error=visible_error[:500],
            browser_errors=max(0, new_browser_errors),
            browser_error_messages=[message[:500] for message in new_browser_messages[:5]],
            skipped=skipped,
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        visible_error = await collect_visible_error(page)
        new_browser_messages = browser_errors[before_browser_errors:]
        return StepSample(
            user_id=user_id,
            iteration=iteration,
            section=section,
            action=action,
            elapsed_ms=elapsed_ms,
            ok=False,
            error=str(exc).replace("\n", " ")[:500],
            visible_error=visible_error[:500],
            browser_errors=max(0, len(new_browser_messages)),
            browser_error_messages=[message[:500] for message in new_browser_messages[:5]],
        )


async def run_user(browser, args: argparse.Namespace, user_id: int) -> list[StepSample]:
    samples: list[StepSample] = []
    browser_errors: list[str] = []
    load_button_map = active_load_button_map(args.load_buttons)
    context = await browser.new_context(
        viewport={"width": args.width, "height": args.height},
        extra_http_headers={"X-OVERWATCH-PERF-RUN-ID": args.run_id},
    )
    page = await context.new_page()
    page.set_default_timeout(args.timeout_ms)
    page.on("pageerror", lambda exc: browser_errors.append(str(exc)[:500]))
    if args.fail_console_errors:
        page.on(
            "console",
            lambda msg: browser_errors.append(msg.text[:500]) if msg.type == "error" else None,
        )

    try:
        async def initial_load():
            await page.goto(args.url, wait_until="domcontentloaded", timeout=args.timeout_ms)
            await page.wait_for_timeout(args.initial_wait_ms)
            await wait_for_app_ready(page, args.timeout_ms)
            if args.wait_initial_idle:
                await wait_for_streamlit_idle(page, args.timeout_ms, args.action_settle_ms)

        if args.single_initial_load:
            initial_sample = await timed_step(
                page=page,
                user_id=user_id,
                iteration=1,
                section="App Shell",
                action="initial_load",
                browser_errors=browser_errors,
                operation=initial_load,
            )
            samples.append(initial_sample)
            if not initial_sample.ok and args.stop_user_on_error:
                return samples

        for iteration in range(1, args.iterations + 1):
            if not args.single_initial_load:
                initial_sample = await timed_step(
                    page=page,
                    user_id=user_id,
                    iteration=iteration,
                    section="App Shell",
                    action="initial_load",
                    browser_errors=browser_errors,
                    operation=initial_load,
                )
                samples.append(initial_sample)
                if not initial_sample.ok and args.stop_user_on_error:
                    break

            for section in args.sections:

                async def section_nav(section_name=section):
                    if await section_is_visible(page, section_name):
                        return None
                    await click_named_button(page, section_name, args.timeout_ms)
                    await wait_for_section(page, section_name, args.timeout_ms)
                    await page.wait_for_timeout(args.action_settle_ms)

                nav_sample = await timed_step(
                    page=page,
                    user_id=user_id,
                    iteration=iteration,
                    section=section,
                    action="section_nav",
                    browser_errors=browser_errors,
                    operation=section_nav,
                )
                samples.append(nav_sample)
                if not nav_sample.ok and args.stop_user_on_error:
                    break

                load_label = load_button_map.get(section)
                if load_label:

                    async def load_live_data(section_name=section, button_label=load_label):
                        if args.expand_load_surfaces:
                            await expand_hidden_load_surfaces(page)
                        clicked = await click_optional_named_button(
                            page,
                            button_label,
                            args.timeout_ms,
                            args.missing_load_button,
                            args.missing_load_button_wait_ms,
                        )
                        if not clicked:
                            return "skipped"
                        await wait_for_streamlit_idle(page, args.timeout_ms, args.action_settle_ms)
                        await wait_for_section(page, section_name, args.timeout_ms)

                    load_sample = await timed_step(
                        page=page,
                        user_id=user_id,
                        iteration=iteration,
                        section=section,
                        action=f"load_button:{load_label}",
                        browser_errors=browser_errors,
                        operation=load_live_data,
                    )
                    samples.append(load_sample)
                    if not load_sample.ok and args.stop_user_on_error:
                        break
    finally:
        await context.close()
    return samples


async def run_stress(args: argparse.Namespace) -> tuple[list[StepSample], float]:
    async_playwright, import_error = load_playwright()
    if import_error:
        raise RuntimeError(
            "Playwright is required for live concurrent browser stress tests. "
            "Install it or use perf_runner.py for HTTP-only load tests."
        ) from import_error

    started = time.perf_counter()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=not args.headed)

        async def delayed_user(user_id: int) -> list[StepSample]:
            if args.ramp_seconds > 0 and args.users > 1:
                await asyncio.sleep(((user_id - 1) / (args.users - 1)) * args.ramp_seconds)
            return await run_user(browser, args, user_id)

        grouped_samples = await asyncio.gather(*(delayed_user(user_id) for user_id in range(1, args.users + 1)))
        await browser.close()
    elapsed_sec = time.perf_counter() - started
    return [sample for group in grouped_samples for sample in group], elapsed_sec


def summarize(samples: list[StepSample], total_elapsed_sec: float, args: argparse.Namespace) -> dict:
    measured_samples = [sample for sample in samples if not sample.skipped]
    elapsed = [sample.elapsed_ms for sample in measured_samples]
    errors = sum(1 for sample in measured_samples if not sample.ok)
    error_rate = errors / len(measured_samples) if measured_samples else 1.0
    skipped = sum(1 for sample in samples if sample.skipped)
    p95_ms = percentile(elapsed, 95)
    p99_ms = percentile(elapsed, 99)
    browser_error_steps = sum(1 for sample in samples if sample.browser_errors)
    browser_error_messages: dict[str, int] = {}
    visible_errors: dict[str, int] = {}
    for sample in samples:
        if sample.visible_error:
            visible_errors[sample.visible_error] = visible_errors.get(sample.visible_error, 0) + 1
        for message in sample.browser_error_messages:
            browser_error_messages[message] = browser_error_messages.get(message, 0) + 1
    step_counts = {
        "initial_load": sum(1 for sample in samples if sample.action == "initial_load"),
        "section_nav": sum(1 for sample in samples if sample.action == "section_nav"),
        "load_button": sum(1 for sample in samples if sample.action.startswith("load_button:")),
    }
    skipped_by_label: dict[str, int] = {}
    for sample in samples:
        if not sample.skipped:
            continue
        label = sample.action.split(":", 1)[1] if sample.action.startswith("load_button:") else sample.action
        skipped_by_label[label] = skipped_by_label.get(label, 0) + 1

    by_action = {}
    for action in sorted({sample.action for sample in samples}):
        action_samples = [sample for sample in samples if sample.action == action]
        action_elapsed = [sample.elapsed_ms for sample in action_samples if not sample.skipped]
        by_action[action] = {
            "steps": len(action_samples),
            "errors": sum(1 for sample in action_samples if not sample.ok and not sample.skipped),
            "skipped": sum(1 for sample in action_samples if sample.skipped),
            "p95_ms": round(percentile(action_elapsed, 95), 2),
            "max_ms": round(max(action_elapsed), 2) if action_elapsed else 0.0,
        }

    by_section = {}
    for section in sorted({sample.section for sample in samples}):
        section_samples = [sample for sample in samples if sample.section == section]
        section_elapsed = [sample.elapsed_ms for sample in section_samples if not sample.skipped]
        by_section[section] = {
            "steps": len(section_samples),
            "errors": sum(1 for sample in section_samples if not sample.ok and not sample.skipped),
            "skipped": sum(1 for sample in section_samples if sample.skipped),
            "p95_ms": round(percentile(section_elapsed, 95), 2),
            "max_ms": round(max(section_elapsed), 2) if section_elapsed else 0.0,
        }

    top_slowest_actions = [
        {"action": action, **row}
        for action, row in sorted(by_action.items(), key=lambda item: item[1]["p95_ms"], reverse=True)
    ]
    top_slowest_sections = [
        {"section": section, **row}
        for section, row in sorted(by_section.items(), key=lambda item: item[1]["p95_ms"], reverse=True)
    ]

    score = 100
    if p95_ms > args.fail_p95_ms:
        score -= min(35, int((p95_ms - args.fail_p95_ms) / max(args.fail_p95_ms, 1) * 35) + 10)
    if p99_ms > args.fail_p95_ms * 1.8:
        score -= 8
    if error_rate > args.fail_error_rate:
        score -= min(45, int((error_rate - args.fail_error_rate) * 100) + 20)
    if browser_error_steps:
        score -= min(20, browser_error_steps * 2)
    score = max(0, min(100, score))
    if score >= 95 and error_rate <= args.fail_error_rate and p95_ms <= args.fail_p95_ms:
        state = "PASS"
    elif score >= 85:
        state = "WATCH"
    else:
        state = "FAIL"

    release_blockers: list[dict[str, object]] = []
    if p95_ms > args.fail_p95_ms:
        release_blockers.append({
            "type": "p95_threshold",
            "message": f"p95 {round(p95_ms, 2)} ms exceeded threshold {args.fail_p95_ms} ms",
        })
    if error_rate > args.fail_error_rate:
        release_blockers.append({
            "type": "error_rate",
            "message": f"error rate {round(error_rate, 4)} exceeded threshold {args.fail_error_rate}",
            "errors": errors,
        })
    if skipped:
        release_blockers.append({
            "type": "skipped_load_buttons",
            "message": f"{skipped} configured load button step(s) were skipped",
            "skipped_by_label": skipped_by_label,
        })
    if browser_error_steps:
        release_blockers.append({
            "type": "browser_errors",
            "message": f"{browser_error_steps} browser step(s) recorded console/runtime errors",
            "browser_error_messages": [
                {"message": message, "count": count}
                for message, count in sorted(browser_error_messages.items(), key=lambda item: item[1], reverse=True)[:5]
            ],
        })
    if score < 95:
        release_blockers.append({
            "type": "readiness_score",
            "message": f"readiness score {score}/100 is below the 95/100 release target",
        })

    slowest_sample = max(measured_samples, key=lambda item: item.elapsed_ms) if measured_samples else None
    return {
        "users": args.users,
        "iterations": args.iterations,
        "steps": len(samples),
        "measured_steps": len(measured_samples),
        "skipped": skipped,
        "errors": errors,
        "error_rate": round(error_rate, 4),
        "p50_ms": round(statistics.median(elapsed), 2) if elapsed else 0.0,
        "p95_ms": round(p95_ms, 2),
        "p99_ms": round(p99_ms, 2),
        "max_ms": round(max(elapsed), 2) if elapsed else 0.0,
        "avg_ms": round(statistics.mean(elapsed), 2) if elapsed else 0.0,
        "throughput_steps_per_sec": round((len(samples) - errors) / total_elapsed_sec, 3) if total_elapsed_sec else 0.0,
        "total_elapsed_sec": round(total_elapsed_sec, 3),
        "browser_error_steps": browser_error_steps,
        "browser_error_messages": [
            {"message": message, "count": count}
            for message, count in sorted(browser_error_messages.items(), key=lambda item: item[1], reverse=True)
        ],
        "visible_errors": [
            {"message": message, "count": count}
            for message, count in sorted(visible_errors.items(), key=lambda item: item[1], reverse=True)
        ],
        "slowest_step": dataclasses.asdict(slowest_sample) if slowest_sample else {},
        "step_counts": step_counts,
        "skipped_by_label": skipped_by_label,
        "top_slowest_actions": top_slowest_actions,
        "top_slowest_sections": top_slowest_sections,
        "release_blockers": release_blockers,
        "by_action": by_action,
        "by_section": by_section,
        "readiness_score": score,
        "readiness_state": state,
        "fail_p95_ms": args.fail_p95_ms,
        "fail_error_rate": args.fail_error_rate,
    }


def build_recommendations(summary: dict) -> list[str]:
    recommendations: list[str] = []
    if summary.get("errors", 0):
        recommendations.append(
            "Investigate failed steps before increasing concurrency; visible app exceptions or missing load buttons mean the DBA flow is not release-ready."
        )
    if float(summary.get("p95_ms", 0)) > float(summary.get("fail_p95_ms", 0)):
        recommendations.append(
            "Live browser p95 is above threshold. Compare the slowest section with Snowflake query history and push that data path behind a mart or explicit drilldown."
        )
    by_section = summary.get("by_section", {})
    if by_section:
        slow_section = max(by_section, key=lambda key: by_section[key].get("p95_ms", 0))
        recommendations.append(
            f"Start tuning with {slow_section}; it has the highest section p95 in this run."
        )
    if summary.get("browser_error_steps", 0):
        recommendations.append(
            "Browser runtime errors occurred. Treat them as UI reliability defects even if the Snowflake query finished."
        )
    if summary.get("skipped", 0):
        recommendations.append(
            "Some configured load buttons were not visible. Remove stale controls from the default profile or test those deep paths with a targeted section workflow."
        )
    return recommendations or [
        "No immediate live browser stress bottleneck was detected. Increase users gradually and attach Snowflake query-history evidence for cost."
    ]


def write_reports(args: argparse.Namespace, samples: list[StepSample], summary: dict) -> tuple[pathlib.Path, pathlib.Path]:
    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    recommendations = build_recommendations(summary)
    payload = {
        "run_id": args.run_id,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "url": args.url,
        "sections": args.sections,
        "load_buttons": args.load_buttons,
        "summary": summary,
        "recommendations": recommendations,
        "samples": [dataclasses.asdict(sample) for sample in sorted(samples, key=lambda item: (item.user_id, item.iteration, item.section, item.action))],
    }
    json_path = output_dir / f"{args.run_id}_live_concurrent.json"
    md_path = output_dir / f"{args.run_id}_live_concurrent.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    measured_samples = [sample for sample in samples if not sample.skipped]
    slowest = sorted(measured_samples, key=lambda item: item.elapsed_ms, reverse=True)[:15]
    failures = [sample for sample in measured_samples if not sample.ok][:15]
    md = [
        f"# OVERWATCH Live Concurrent Run {args.run_id}",
        "",
        f"- URL: `{args.url}`",
        f"- Users: `{args.users}`",
        f"- Iterations per user: `{args.iterations}`",
        f"- Sections: `{', '.join(args.sections)}`",
        f"- Live load buttons: `{'enabled' if args.load_buttons else 'disabled'}`",
        f"- Readiness: **{summary['readiness_state']}** ({summary['readiness_score']}/100)",
        f"- Steps: {summary['steps']} total, {summary['measured_steps']} measured, {summary['skipped']} skipped, {summary['errors']} errors ({summary['error_rate'] * 100:.2f}%)",
        f"- Step counts: initial_load {summary['step_counts']['initial_load']}, section_nav {summary['step_counts']['section_nav']}, load_button {summary['step_counts']['load_button']}",
        f"- Latency: p50 {summary['p50_ms']} ms, p95 {summary['p95_ms']} ms, p99 {summary['p99_ms']} ms, max {summary['max_ms']} ms",
        f"- Throughput: {summary['throughput_steps_per_sec']} successful browser steps/sec",
        "",
        "## Release Blockers",
        "",
    ]
    if summary["release_blockers"]:
        md.extend(f"- `{item['type']}`: {item['message']}" for item in summary["release_blockers"])
    else:
        md.append("No release blockers were detected.")
    md.extend([
        "",
        "## Section P95",
        "",
        "| Section | Steps | Skipped | Errors | P95 ms | Max ms |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for section, row in sorted(summary["by_section"].items(), key=lambda item: item[1]["p95_ms"], reverse=True):
        md.append(f"| {section} | {row['steps']} | {row['skipped']} | {row['errors']} | {row['p95_ms']} | {row['max_ms']} |")
    md.extend([
        "",
        "## Action P95",
        "",
        "| Action | Steps | Skipped | Errors | P95 ms | Max ms |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for action, row in sorted(summary["by_action"].items(), key=lambda item: item[1]["p95_ms"], reverse=True):
        md.append(f"| {action} | {row['steps']} | {row['skipped']} | {row['errors']} | {row['p95_ms']} | {row['max_ms']} |")
    md.extend(["", "## Slowest Steps", "", "| User | Iteration | Section | Action | Status | Elapsed ms | Error |", "|---:|---:|---|---|---:|---:|---|"])
    for sample in slowest:
        md.append(
            f"| {sample.user_id} | {sample.iteration} | {sample.section} | {sample.action} | "
            f"{'OK' if sample.ok else 'FAIL'} | {sample.elapsed_ms:.2f} | {(sample.error or sample.visible_error)[:160]} |"
        )
    md.extend(["", "## Failures", ""])
    if failures:
        md.extend([
            "| User | Iteration | Section | Action | Elapsed ms | Error | Visible error | Browser error |",
            "|---:|---:|---|---|---:|---|---|---|",
        ])
        for sample in failures:
            browser_error = "; ".join(sample.browser_error_messages)[:180]
            md.append(
                f"| {sample.user_id} | {sample.iteration} | {sample.section} | {sample.action} | "
                f"{sample.elapsed_ms:.2f} | {sample.error[:140]} | {sample.visible_error[:180]} | {browser_error} |"
            )
    else:
        md.append("No browser-step failures.")
    md.extend(["", "## Browser Errors", ""])
    if summary["browser_error_messages"]:
        md.extend(["| Message | Count |", "|---|---:|"])
        for item in summary["browser_error_messages"][:10]:
            md.append(f"| {item['message'][:240]} | {item['count']} |")
    else:
        md.append("No browser console or page errors were captured.")
    md.extend(["", "## Visible Errors", ""])
    if summary["visible_errors"]:
        md.extend(["| Message | Count |", "|---|---:|"])
        for item in summary["visible_errors"][:10]:
            md.append(f"| {item['message'][:240]} | {item['count']} |")
    else:
        md.append("No visible Streamlit error text was captured.")
    skipped_samples = [sample for sample in samples if sample.skipped]
    md.extend(["", "## Skipped Live Buttons", ""])
    if skipped_samples:
        if summary["skipped_by_label"]:
            md.extend(["| Label | Skipped |", "|---|---:|"])
            for label, count in sorted(summary["skipped_by_label"].items(), key=lambda item: item[1], reverse=True):
                md.append(f"| {label} | {count} |")
            md.append("")
        md.extend(["| User | Iteration | Section | Action |", "|---:|---:|---|---|"])
        for sample in skipped_samples[:20]:
            md.append(f"| {sample.user_id} | {sample.iteration} | {sample.section} | {sample.action} |")
    else:
        md.append("No configured live buttons were skipped.")
    md.extend(["", "## Recommended Next Actions", ""])
    md.extend(f"- {item}" for item in recommendations)
    md.extend([
        "",
        "## Cost Notes",
        "",
        "- This run intentionally clicks live-data buttons and can issue real Snowflake queries.",
        "- Shared warehouse metering is estimated unless OVERWATCH runs on an isolated benchmark warehouse.",
        "- Pair this report with Snowflake query history and OVERWATCH usage logs for exact slow-query attribution.",
    ])
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return json_path, md_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run concurrent live browser users against OVERWATCH.")
    parser.add_argument("--profile", default=argparse.SUPPRESS, help="JSON profile with default runner settings.")
    parser.add_argument("--url", default=argparse.SUPPRESS, help="Dashboard URL to test.")
    parser.add_argument("--users", type=int, default=argparse.SUPPRESS, help="Concurrent simulated browser users.")
    parser.add_argument("--iterations", type=int, default=argparse.SUPPRESS, help="Full section passes per user.")
    parser.add_argument("--sections", nargs="*", default=argparse.SUPPRESS, help="Section button labels to click.")
    parser.add_argument("--load-buttons", action=argparse.BooleanOptionalAction, default=argparse.SUPPRESS, help="Click safe live-data load buttons.")
    parser.add_argument("--expand-load-surfaces", action=argparse.BooleanOptionalAction, default=argparse.SUPPRESS, help="Open collapsed expanders before clicking safe load buttons.")
    parser.add_argument("--missing-load-button", choices=["skip", "fail"], default=argparse.SUPPRESS, help="How to handle configured load buttons that are not visible in the active section view.")
    parser.add_argument("--missing-load-button-wait-ms", type=int, default=argparse.SUPPRESS, help="How long to wait before skipping a non-visible optional load button.")
    parser.add_argument("--stop-user-on-error", action=argparse.BooleanOptionalAction, default=argparse.SUPPRESS, help="Stop a user's flow after the first failed step.")
    parser.add_argument("--fail-console-errors", action=argparse.BooleanOptionalAction, default=argparse.SUPPRESS, help="Treat browser console errors as failed steps.")
    parser.add_argument("--timeout-ms", type=int, default=argparse.SUPPRESS, help="Per-step browser timeout.")
    parser.add_argument("--initial-wait-ms", type=int, default=argparse.SUPPRESS, help="Initial page settle time.")
    parser.add_argument("--wait-initial-idle", action=argparse.BooleanOptionalAction, default=argparse.SUPPRESS, help="After initial app readiness, wait for Streamlit idle before recording the step.")
    parser.add_argument("--single-initial-load", action=argparse.BooleanOptionalAction, default=argparse.SUPPRESS, help="Load the app once per user, then repeat in-app section flows without hard page reloads.")
    parser.add_argument("--action-settle-ms", type=int, default=argparse.SUPPRESS, help="Minimum wait after clicks before spinner checks.")
    parser.add_argument("--ramp-seconds", type=float, default=argparse.SUPPRESS, help="Ramp users across this many seconds.")
    parser.add_argument("--width", type=int, default=argparse.SUPPRESS, help="Browser viewport width.")
    parser.add_argument("--height", type=int, default=argparse.SUPPRESS, help="Browser viewport height.")
    parser.add_argument("--headed", action=argparse.BooleanOptionalAction, default=argparse.SUPPRESS, help="Run with visible browser windows.")
    parser.add_argument("--allow-large-run", action=argparse.BooleanOptionalAction, default=argparse.SUPPRESS, help="Allow more than 40 concurrent users.")
    parser.add_argument("--output-dir", default=argparse.SUPPRESS, help="Directory for JSON and Markdown reports.")
    parser.add_argument("--run-id", default=argparse.SUPPRESS)
    parser.add_argument("--fail-p95-ms", type=float, default=argparse.SUPPRESS, help="Fail threshold for live browser step p95.")
    parser.add_argument("--fail-error-rate", type=float, default=argparse.SUPPRESS, help="Fail threshold for browser-step error rate.")
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    profile_parser = argparse.ArgumentParser(add_help=False)
    profile_parser.add_argument("--profile")
    profile_args, _ = profile_parser.parse_known_args(argv)

    config = _default_config()
    if profile_args.profile:
        config.update(load_profile_defaults(profile_args.profile))
        config["profile"] = profile_args.profile

    parser = _build_parser()
    cli_args = parser.parse_args(argv)
    config.update(vars(cli_args))
    config["load_buttons"] = normalize_load_buttons(config["load_buttons"])
    args = argparse.Namespace(**config)
    if args.users < 1 or args.iterations < 1:
        parser.error("--users and --iterations must be positive integers.")
    if args.timeout_ms < 5000:
        parser.error("--timeout-ms must be at least 5000 for live browser tests.")
    if args.users > 40 and not args.allow_large_run:
        parser.error("--users above 40 requires --allow-large-run to avoid surprise Snowflake and local CPU load.")
    return args


def main() -> int:
    args = parse_args()
    try:
        samples, total_elapsed_sec = asyncio.run(run_stress(args))
    except Exception as exc:
        print(json.dumps({
            "run_id": args.run_id,
            "readiness_state": "BLOCKED",
            "error": str(exc),
        }, indent=2))
        return 3

    summary = summarize(samples, total_elapsed_sec, args)
    json_path, md_path = write_reports(args, samples, summary)
    print(json.dumps({
        "run_id": args.run_id,
        "readiness_state": summary["readiness_state"],
        "readiness_score": summary["readiness_score"],
        "users": summary["users"],
        "steps": summary["steps"],
        "measured_steps": summary["measured_steps"],
        "skipped": summary["skipped"],
        "errors": summary["errors"],
        "p95_ms": summary["p95_ms"],
        "slowest_step": summary["slowest_step"],
        "json_report": str(json_path),
        "markdown_report": str(md_path),
    }, indent=2))
    return 0 if summary["readiness_state"] in {"PASS", "WATCH"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
