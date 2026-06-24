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
import os
import pathlib
import statistics
import time
import urllib.parse
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
    diagnostic: bool = False
    detail: dict[str, object] = dataclasses.field(default_factory=dict)


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


def load_psutil():
    """Import psutil lazily; resource telemetry is best effort."""
    try:
        import psutil

        return psutil, None
    except Exception as exc:
        return None, exc


def collect_resource_sample(label: str, *, psutil_module=None, detail: dict[str, object] | None = None) -> dict[str, object]:
    """Collect host pressure telemetry without making psutil a dependency."""
    sample: dict[str, object] = {
        "label": label,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "psutil_available": psutil_module is not None,
        "detail": detail or {},
    }
    if psutil_module is None:
        return sample
    try:
        process = psutil_module.Process(os.getpid())
        children = process.children(recursive=True)
        browser_names = ("chrome", "chromium", "msedge", "playwright")
        browser_child_count = 0
        for child in children:
            try:
                name = child.name().lower()
            except Exception:
                name = ""
            if any(token in name for token in browser_names):
                browser_child_count += 1
        sample.update({
            "cpu_percent": psutil_module.cpu_percent(interval=None),
            "memory_percent": psutil_module.virtual_memory().percent,
            "process_count": len(psutil_module.pids()),
            "python_child_process_count": len(children),
            "browser_child_process_count": browser_child_count,
        })
    except Exception as exc:
        sample["error"] = str(exc)[:240]
    return sample


class ResourceRecorder:
    """Thread-safe-ish resource timeline for concurrent Playwright users."""

    def __init__(self, users: int):
        self.users = int(users)
        self.psutil, _ = load_psutil()
        if self.psutil is not None:
            try:
                self.psutil.cpu_percent(interval=None)
            except Exception:
                pass
        self.samples: list[dict[str, object]] = []
        self._lock = asyncio.Lock()
        self._pages_opened = 0
        self._initial_loads_completed = 0

    async def record(self, label: str, **detail: object) -> None:
        async with self._lock:
            self.samples.append(collect_resource_sample(label, psutil_module=self.psutil, detail=detail))

    async def mark_page_open(self, user_id: int) -> None:
        async with self._lock:
            self._pages_opened += 1
            self.samples.append(
                collect_resource_sample(
                    "page_open",
                    psutil_module=self.psutil,
                    detail={"user_id": user_id, "pages_opened": self._pages_opened},
                )
            )
            if self._pages_opened == self.users:
                self.samples.append(
                    collect_resource_sample("after_all_pages_open", psutil_module=self.psutil)
                )

    async def mark_initial_load(self, user_id: int, elapsed_ms: float) -> None:
        async with self._lock:
            self._initial_loads_completed += 1
            self.samples.append(
                collect_resource_sample(
                    "initial_load_complete",
                    psutil_module=self.psutil,
                    detail={
                        "user_id": user_id,
                        "elapsed_ms": round(float(elapsed_ms), 2),
                        "initial_loads_completed": self._initial_loads_completed,
                    },
                )
            )
            if self._initial_loads_completed == self.users:
                self.samples.append(
                    collect_resource_sample("after_initial_load", psutil_module=self.psutil)
                )


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
        "initial_load_substeps": False,
        "section_nav_substeps": False,
        "wait_initial_idle": False,
        "trace_slowest_initial_load": False,
        "single_initial_load": False,
        "chromium_args": [],
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
    if "chromium_args" in profile:
        chromium_args = profile["chromium_args"]
        if not isinstance(chromium_args, list) or not all(isinstance(item, str) for item in chromium_args):
            raise ValueError("profile chromium_args must be a string list")
    return profile


def perf_run_url(url: str, *, run_id: str, user_id: int, iteration: int) -> str:
    """Append perf identifiers while preserving existing query parameters."""
    split = urllib.parse.urlsplit(str(url))
    pairs = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(split.query, keep_blank_values=True)
        if key not in {"overwatch_perf_run_id", "overwatch_perf_user", "overwatch_perf_iteration"}
    ]
    pairs.extend([
        ("overwatch_perf_run_id", str(run_id)),
        ("overwatch_perf_user", str(user_id)),
        ("overwatch_perf_iteration", str(iteration)),
    ])
    query = urllib.parse.urlencode(pairs)
    return urllib.parse.urlunsplit((split.scheme, split.netloc, split.path, query, split.fragment))


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


async def wait_for_transition_clear(page, timeout_ms: int) -> None:
    """Wait until the section transition is gone from the visible page."""
    await page.wait_for_function(
        """() => {
            const visible = (element) => {
                if (!element) return false;
                const style = window.getComputedStyle(element);
                return style.visibility !== "hidden"
                    && style.display !== "none"
                    && element.getClientRects().length > 0;
            };
            return Array.from(document.querySelectorAll(".ow-section-transition")).every(
                (element) => !visible(element)
            );
        }""",
        timeout=timeout_ms,
    )


async def wait_for_section_title_visible(page, section: str, timeout_ms: int) -> None:
    title = page.locator(".ow-section-title").filter(has_text=section).first
    await title.wait_for(state="visible", timeout=timeout_ms)


async def wait_for_active_section_container_visible(page, timeout_ms: int) -> None:
    await wait_for_transition_clear(page, timeout_ms)
    await page.locator(".ow-section-title").first.wait_for(state="visible", timeout=timeout_ms)


async def wait_for_section(page, section: str, timeout_ms: int) -> None:
    await wait_for_section_title_visible(page, section, timeout_ms)
    try:
        await wait_for_transition_clear(page, timeout_ms)
    except Exception:
        pass


async def wait_for_app_ready(page, timeout_ms: int) -> None:
    await page.locator(".ow-section-title").first.wait_for(state="visible", timeout=timeout_ms)
    try:
        await wait_for_transition_clear(page, timeout_ms)
    except Exception:
        pass


async def wait_for_shell_title_visible(page, timeout_ms: int) -> None:
    await page.locator(".ow-section-title").first.wait_for(state="visible", timeout=timeout_ms)


async def wait_for_topbar_visible(page, timeout_ms: int) -> None:
    await page.locator(".ow-topbar").first.wait_for(state="visible", timeout=timeout_ms)
    await page.locator(".ow-filter-strip-shell").first.wait_for(state="visible", timeout=timeout_ms)


async def wait_for_sidebar_visible(page, timeout_ms: int) -> None:
    await page.locator(".ow-sidebar-brand").first.wait_for(state="visible", timeout=timeout_ms)


async def wait_for_section_container_visible(page, timeout_ms: int) -> None:
    await wait_for_transition_clear(page, timeout_ms)
    await page.locator(
        ".ow-shell-snapshot-grid, .ow-signal-board, #overwatch-perf-trace"
    ).first.wait_for(state="attached", timeout=timeout_ms)


async def collect_browser_navigation_timing(page) -> dict[str, float]:
    try:
        return await page.evaluate(
            """() => {
                const nav = performance.getEntriesByType("navigation")[0];
                if (!nav) return {};
                const fields = [
                    "startTime", "responseStart", "responseEnd", "domInteractive",
                    "domContentLoadedEventEnd", "loadEventEnd", "transferSize", "encodedBodySize"
                ];
                const out = {};
                for (const field of fields) {
                    const value = nav[field];
                    if (typeof value === "number" && Number.isFinite(value)) {
                        out[field] = Math.round(value * 100) / 100;
                    }
                }
                return out;
            }"""
        )
    except Exception:
        return {}


async def collect_browser_paint_timing(page) -> dict[str, float]:
    try:
        return await page.evaluate(
            """() => {
                const out = {};
                for (const entry of performance.getEntriesByType("paint")) {
                    out[entry.name] = Math.round(entry.startTime * 100) / 100;
                }
                return out;
            }"""
        )
    except Exception:
        return {}


async def collect_frontend_metrics(page) -> dict[str, object]:
    """Collect paint/DOM pressure signals without requiring browser-only APIs."""
    try:
        metrics = await page.evaluate(
            """() => {
                const visible = (element) => {
                    if (!element) return false;
                    const style = window.getComputedStyle(element);
                    return style.visibility !== "hidden"
                        && style.display !== "none"
                        && element.getClientRects().length > 0;
                };
                const dom = {
                    node_count: document.querySelectorAll("*").length,
                    visible_button_count: Array.from(document.querySelectorAll("button, [role='button']")).filter(visible).length,
                    script_count: document.scripts ? document.scripts.length : 0,
                    style_count: document.querySelectorAll("style").length,
                    link_stylesheet_count: document.querySelectorAll("link[rel='stylesheet']").length,
                    stylesheet_count: document.styleSheets ? document.styleSheets.length : 0,
                    css_rule_count: 0,
                    css_rule_error_count: 0,
                };
                try {
                    for (const sheet of Array.from(document.styleSheets || [])) {
                        try {
                            dom.css_rule_count += sheet.cssRules ? sheet.cssRules.length : 0;
                        } catch (error) {
                            dom.css_rule_error_count += 1;
                        }
                    }
                } catch (error) {
                    dom.css_rule_error_count += 1;
                }
                const resourceTiming = {};
                for (const entry of performance.getEntriesByType("resource") || []) {
                    const key = entry.initiatorType || "other";
                    if (!resourceTiming[key]) {
                        resourceTiming[key] = {count: 0, total_duration_ms: 0, transfer_size: 0};
                    }
                    resourceTiming[key].count += 1;
                    resourceTiming[key].total_duration_ms += Number(entry.duration || 0);
                    resourceTiming[key].transfer_size += Number(entry.transferSize || 0);
                }
                for (const row of Object.values(resourceTiming)) {
                    row.total_duration_ms = Math.round(row.total_duration_ms * 100) / 100;
                    row.transfer_size = Math.round(row.transfer_size);
                }
                const longTasks = performance.getEntriesByType("longtask") || [];
                const layoutShifts = (performance.getEntriesByType("layout-shift") || [])
                    .filter(entry => !entry.hadRecentInput);
                const memory = performance.memory ? {
                    used_js_heap_size: performance.memory.usedJSHeapSize,
                    total_js_heap_size: performance.memory.totalJSHeapSize,
                    js_heap_size_limit: performance.memory.jsHeapSizeLimit,
                } : {};
                return {
                    dom,
                    resource_timing_by_type: resourceTiming,
                    long_tasks: {
                        count: longTasks.length,
                        total_duration_ms: Math.round(longTasks.reduce((sum, entry) => sum + Number(entry.duration || 0), 0) * 100) / 100,
                        max_duration_ms: Math.round(longTasks.reduce((max, entry) => Math.max(max, Number(entry.duration || 0)), 0) * 100) / 100,
                    },
                    layout_shift: {
                        count: layoutShifts.length,
                        score: Math.round(layoutShifts.reduce((sum, entry) => sum + Number(entry.value || 0), 0) * 10000) / 10000,
                    },
                    heap: memory,
                };
            }"""
        )
        return metrics if isinstance(metrics, dict) else {}
    except Exception as exc:
        return {"error": str(exc)[:240]}


async def collect_perf_trace_payload(page) -> dict[str, object]:
    try:
        payload = await page.evaluate(
            """() => {
                const marker = document.querySelector("#overwatch-perf-trace");
                if (!marker) return {};
                try {
                    return JSON.parse(marker.textContent || "{}");
                } catch (error) {
                    return {error: String(error)};
                }
            }"""
        )
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        return {"error": str(exc)[:240]}


async def collect_initial_load_diagnostics(page) -> dict[str, object]:
    return {
        "perf_trace": await collect_perf_trace_payload(page),
        "navigation_timing": await collect_browser_navigation_timing(page),
        "paint_timing": await collect_browser_paint_timing(page),
        "frontend_metrics": await collect_frontend_metrics(page),
    }


async def collect_section_nav_diagnostics(page) -> dict[str, object]:
    return {
        "perf_trace": await collect_perf_trace_payload(page),
        "frontend_metrics": await collect_frontend_metrics(page),
    }


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


def _safe_artifact_token(value: object) -> str:
    text = "".join(ch if ch.isalnum() else "_" for ch in str(value or "").strip())
    return "_".join(part for part in text.split("_") if part)[:80] or "unknown"


async def collect_skipped_button_diagnostics(
    page,
    *,
    section: str,
    label: str,
    output_dir: str | pathlib.Path,
    run_id: str,
    user_id: int,
    iteration: int,
    expanded_load_surfaces: bool,
) -> dict[str, object]:
    """Capture local UI context for a configured load button that is missing."""
    try:
        context = await page.evaluate(
            """() => {
                const visible = (element) => {
                    if (!element) return false;
                    const style = window.getComputedStyle(element);
                    return style.visibility !== "hidden"
                        && style.display !== "none"
                        && element.getClientRects().length > 0;
                };
                const text = (element) => (element && element.innerText ? element.innerText.replace(/\\s+/g, " ").trim() : "");
                const buttons = Array.from(document.querySelectorAll("button, [role='button']"))
                    .filter(visible)
                    .map(text)
                    .filter(Boolean)
                    .slice(0, 80);
                const headings = Array.from(document.querySelectorAll(
                    "h1,h2,h3,h4,h5,h6,.ow-section-title,.ow-section-subtitle,[data-testid='stCaptionContainer']"
                ))
                    .filter(visible)
                    .map(text)
                    .filter(Boolean)
                    .slice(0, 80);
                const activeTitle = text(document.querySelector(".ow-section-title"));
                const spinners = Array.from(document.querySelectorAll('[data-testid="stSpinner"], .stSpinner')).filter(visible).length;
                const transitions = Array.from(document.querySelectorAll(".ow-section-transition")).filter(visible).length;
                return {
                    active_section_title: activeTitle,
                    visible_button_labels: buttons,
                    visible_headings_and_captions: headings,
                    spinner_count: spinners,
                    transition_count: transitions,
                };
            }"""
        )
        detail = context if isinstance(context, dict) else {}
    except Exception as exc:
        detail = {"context_error": str(exc)[:240]}
    detail.update({
        "configured_section": section,
        "configured_label": label,
        "expand_hidden_load_surfaces_called": expanded_load_surfaces,
    })
    screenshot_path = pathlib.Path(output_dir) / (
        f"{_safe_artifact_token(run_id)}_skipped_button_user{user_id:02d}_iter{iteration}_"
        f"{_safe_artifact_token(section)}_{_safe_artifact_token(label)}.png"
    )
    try:
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(screenshot_path), full_page=True)
        detail["screenshot_path"] = str(screenshot_path)
    except Exception as exc:
        detail["screenshot_error"] = str(exc)[:240]
    return detail


async def click_optional_load_button(
    page,
    *,
    section: str,
    label: str,
    args: argparse.Namespace,
    user_id: int,
    iteration: int,
) -> str | dict[str, object] | None:
    """Click a configured read-only load button or return skip diagnostics."""
    await wait_for_section_title_visible(page, section, args.timeout_ms)
    try:
        await wait_for_transition_clear(page, args.timeout_ms)
    except Exception:
        pass
    await wait_for_streamlit_idle(page, args.timeout_ms, min(args.action_settle_ms, 250))
    await wait_for_active_section_container_visible(page, args.timeout_ms)
    expanded = False
    if args.expand_load_surfaces:
        await expand_hidden_load_surfaces(page)
        expanded = True
    button_wait_ms = args.timeout_ms if args.missing_load_button == "fail" else min(
        args.timeout_ms,
        args.missing_load_button_wait_ms,
    )
    try:
        button = await wait_for_named_button(page, label, button_wait_ms)
    except Exception as exc:
        detail = await collect_skipped_button_diagnostics(
            page,
            section=section,
            label=label,
            output_dir=args.output_dir,
            run_id=args.run_id,
            user_id=user_id,
            iteration=iteration,
            expanded_load_surfaces=expanded,
        )
        detail["wait_error"] = str(exc)[:240]
        if args.missing_load_button == "skip":
            return {"status": "skipped", "detail": detail}
        raise RuntimeError(json.dumps(detail, separators=(",", ":"))) from exc
    await button.click(timeout=args.timeout_ms)
    await wait_for_streamlit_idle(page, args.timeout_ms, args.action_settle_ms)
    await wait_for_section(page, section, args.timeout_ms)
    return None


async def timed_step(
    *,
    page,
    user_id: int,
    iteration: int,
    section: str,
    action: str,
    browser_errors: list[str],
    operation,
    diagnostic: bool = False,
) -> StepSample:
    before_browser_errors = len(browser_errors)
    started = time.perf_counter()
    try:
        result = await operation()
        elapsed_ms = (time.perf_counter() - started) * 1000
        visible_error = await collect_visible_error(page)
        new_browser_messages = browser_errors[before_browser_errors:]
        new_browser_errors = len(new_browser_messages)
        result_detail: dict[str, object] = {}
        skipped = result == "skipped"
        if isinstance(result, dict):
            skipped = result.get("status") == "skipped"
            detail = result.get("detail", result)
            result_detail = detail if isinstance(detail, dict) else {"detail": detail}
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
            diagnostic=diagnostic,
            detail=result_detail,
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
            diagnostic=diagnostic,
        )


async def timed_diagnostic_step(
    *,
    user_id: int,
    iteration: int,
    section: str,
    action: str,
    browser_errors: list[str],
    operation,
) -> StepSample:
    """Time a real phase without adding extra DOM probes to the scored step."""
    before_browser_errors = len(browser_errors)
    started = time.perf_counter()
    try:
        result = await operation()
        elapsed_ms = (time.perf_counter() - started) * 1000
        new_browser_messages = browser_errors[before_browser_errors:]
        return StepSample(
            user_id=user_id,
            iteration=iteration,
            section=section,
            action=action,
            elapsed_ms=elapsed_ms,
            ok=len(new_browser_messages) == 0,
            browser_errors=len(new_browser_messages),
            browser_error_messages=[message[:500] for message in new_browser_messages[:5]],
            diagnostic=True,
            detail=result if isinstance(result, dict) else {},
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        new_browser_messages = browser_errors[before_browser_errors:]
        return StepSample(
            user_id=user_id,
            iteration=iteration,
            section=section,
            action=action,
            elapsed_ms=elapsed_ms,
            ok=False,
            error=str(exc).replace("\n", " ")[:500],
            browser_errors=len(new_browser_messages),
            browser_error_messages=[message[:500] for message in new_browser_messages[:5]],
            diagnostic=True,
        )


async def run_initial_load(
    *,
    page,
    args: argparse.Namespace,
    user_id: int,
    iteration: int,
    browser_errors: list[str],
    samples: list[StepSample],
) -> None:
    target_url = perf_run_url(args.url, run_id=args.run_id, user_id=user_id, iteration=iteration)

    async def run_phase(action: str, operation) -> None:
        sample = await timed_diagnostic_step(
            user_id=user_id,
            iteration=iteration,
            section="App Shell",
            action=action,
            browser_errors=browser_errors,
            operation=operation,
        )
        samples.append(sample)
        if not sample.ok:
            raise RuntimeError(sample.error or f"{action} failed")

    if args.initial_load_substeps:
        await run_phase(
            "initial_load:goto_commit",
            lambda: page.goto(target_url, wait_until="commit", timeout=args.timeout_ms),
        )
        await run_phase(
            "initial_load:domcontentloaded",
            lambda: page.wait_for_load_state("domcontentloaded", timeout=args.timeout_ms),
        )
        await run_phase(
            "initial_load:initial_wait",
            lambda: page.wait_for_timeout(args.initial_wait_ms),
        )
        await run_phase(
            "initial_load:shell_title_visible",
            lambda: wait_for_shell_title_visible(page, args.timeout_ms),
        )
        await run_phase(
            "initial_load:topbar_visible",
            lambda: wait_for_topbar_visible(page, args.timeout_ms),
        )
        await run_phase(
            "initial_load:sidebar_visible",
            lambda: wait_for_sidebar_visible(page, args.timeout_ms),
        )
        await run_phase(
            "initial_load:app_ready",
            lambda: wait_for_app_ready(page, args.timeout_ms),
        )
        await run_phase(
            "initial_load:section_container_visible",
            lambda: wait_for_section_container_visible(page, args.timeout_ms),
        )
        await run_phase(
            "initial_load:perf_trace_collected",
            lambda: collect_initial_load_diagnostics(page),
        )
        if args.wait_initial_idle:
            await run_phase(
                "initial_load:idle_wait",
                lambda: wait_for_streamlit_idle(page, args.timeout_ms, args.action_settle_ms),
            )
        return

    await page.goto(target_url, wait_until="domcontentloaded", timeout=args.timeout_ms)
    await page.wait_for_timeout(args.initial_wait_ms)
    await wait_for_app_ready(page, args.timeout_ms)
    if args.wait_initial_idle:
        await wait_for_streamlit_idle(page, args.timeout_ms, args.action_settle_ms)


async def run_user(
    browser,
    args: argparse.Namespace,
    user_id: int,
    resource_recorder: ResourceRecorder | None = None,
) -> list[StepSample]:
    samples: list[StepSample] = []
    browser_errors: list[str] = []
    load_button_map = active_load_button_map(args.load_buttons)
    context = await browser.new_context(
        viewport={"width": args.width, "height": args.height},
        extra_http_headers={"X-OVERWATCH-PERF-RUN-ID": args.run_id},
    )
    page = await context.new_page()
    if resource_recorder is not None:
        await resource_recorder.mark_page_open(user_id)
    page.set_default_timeout(args.timeout_ms)
    page.on("pageerror", lambda exc: browser_errors.append(str(exc)[:500]))
    if args.fail_console_errors:
        page.on(
            "console",
            lambda msg: browser_errors.append(msg.text[:500]) if msg.type == "error" else None,
        )

    try:
        if args.single_initial_load:
            async def initial_load():
                await run_initial_load(
                    page=page,
                    args=args,
                    user_id=user_id,
                    iteration=1,
                    browser_errors=browser_errors,
                    samples=samples,
                )

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
            if resource_recorder is not None:
                await resource_recorder.mark_initial_load(user_id, initial_sample.elapsed_ms)
            if not initial_sample.ok and args.stop_user_on_error:
                return samples

        for iteration in range(1, args.iterations + 1):
            if not args.single_initial_load:
                async def initial_load(iteration_number=iteration):
                    await run_initial_load(
                        page=page,
                        args=args,
                        user_id=user_id,
                        iteration=iteration_number,
                        browser_errors=browser_errors,
                        samples=samples,
                    )

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
                if iteration == 1 and resource_recorder is not None:
                    await resource_recorder.mark_initial_load(user_id, initial_sample.elapsed_ms)
                if not initial_sample.ok and args.stop_user_on_error:
                    break

            for section in args.sections:

                async def section_nav(section_name=section):
                    if await section_is_visible(page, section_name):
                        return None
                    if args.section_nav_substeps:
                        click_sample = await timed_diagnostic_step(
                            user_id=user_id,
                            iteration=iteration,
                            section=section_name,
                            action=f"section_nav:{section_name}:click",
                            browser_errors=browser_errors,
                            operation=lambda: click_named_button(page, section_name, args.timeout_ms),
                        )
                        samples.append(click_sample)
                        if not click_sample.ok:
                            raise RuntimeError(click_sample.error or f"section_nav:{section_name}:click failed")

                        title_sample = await timed_diagnostic_step(
                            user_id=user_id,
                            iteration=iteration,
                            section=section_name,
                            action=f"section_nav:{section_name}:title_visible",
                            browser_errors=browser_errors,
                            operation=lambda: wait_for_section_title_visible(page, section_name, args.timeout_ms),
                        )
                        samples.append(title_sample)
                        if not title_sample.ok:
                            raise RuntimeError(title_sample.error or f"section_nav:{section_name}:title_visible failed")

                        transition_sample = await timed_diagnostic_step(
                            user_id=user_id,
                            iteration=iteration,
                            section=section_name,
                            action=f"section_nav:{section_name}:transition_clear",
                            browser_errors=browser_errors,
                            operation=lambda: wait_for_transition_clear(page, args.timeout_ms),
                        )
                        samples.append(transition_sample)
                        if not transition_sample.ok:
                            raise RuntimeError(transition_sample.error or f"section_nav:{section_name}:transition_clear failed")

                        container_sample = await timed_diagnostic_step(
                            user_id=user_id,
                            iteration=iteration,
                            section=section_name,
                            action=f"section_nav:{section_name}:section_container_visible",
                            browser_errors=browser_errors,
                            operation=lambda: wait_for_active_section_container_visible(page, args.timeout_ms),
                        )
                        samples.append(container_sample)
                        if not container_sample.ok:
                            raise RuntimeError(container_sample.error or f"section_nav:{section_name}:section_container_visible failed")
                    else:
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
                if args.section_nav_substeps and nav_sample.ok and not nav_sample.skipped:
                    trace_sample = await timed_diagnostic_step(
                        user_id=user_id,
                        iteration=iteration,
                        section=section,
                        action=f"section_nav:{section}:perf_trace_collected",
                        browser_errors=browser_errors,
                        operation=lambda: collect_section_nav_diagnostics(page),
                    )
                    samples.append(trace_sample)
                if not nav_sample.ok and args.stop_user_on_error:
                    break

                load_label = load_button_map.get(section)
                if load_label:

                    async def load_live_data(section_name=section, button_label=load_label):
                        return await click_optional_load_button(
                            page,
                            section=section_name,
                            label=button_label,
                            args=args,
                            user_id=user_id,
                            iteration=iteration,
                        )

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


async def run_stress(args: argparse.Namespace) -> tuple[list[StepSample], float, list[dict[str, object]]]:
    async_playwright, import_error = load_playwright()
    if import_error:
        raise RuntimeError(
            "Playwright is required for live concurrent browser stress tests. "
            "Install it or use perf_runner.py for HTTP-only load tests."
        ) from import_error

    started = time.perf_counter()
    resource_recorder = ResourceRecorder(args.users)
    await resource_recorder.record("before_launch")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=not args.headed, args=list(args.chromium_args or []))
        await resource_recorder.record("after_browser_launch")

        async def delayed_user(user_id: int) -> list[StepSample]:
            if args.ramp_seconds > 0 and args.users > 1:
                await asyncio.sleep(((user_id - 1) / (args.users - 1)) * args.ramp_seconds)
            return await run_user(browser, args, user_id, resource_recorder)

        grouped_samples = await asyncio.gather(*(delayed_user(user_id) for user_id in range(1, args.users + 1)))
        await browser.close()
    elapsed_sec = time.perf_counter() - started
    await resource_recorder.record("after_run_completion", total_elapsed_sec=round(elapsed_sec, 3))
    return [sample for group in grouped_samples for sample in group], elapsed_sec, resource_recorder.samples


def _metric_p95_rows(rows: list[dict[str, object]], label_key: str, value_key: str = "elapsed_ms") -> list[dict[str, object]]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        label = str(row.get(label_key) or "")
        if not label:
            continue
        value = row.get(value_key)
        if isinstance(value, int | float):
            grouped.setdefault(label, []).append(float(value))
    return [
        {
            label_key: label,
            "steps": len(values),
            "p95_ms": round(percentile(values, 95), 2),
            "max_ms": round(max(values), 2) if values else 0.0,
        }
        for label, values in sorted(grouped.items(), key=lambda item: percentile(item[1], 95), reverse=True)
    ]


def _server_phase_rows(diagnostic_samples: list[StepSample]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[tuple[object, object, object, object, object]] = set()
    for sample in diagnostic_samples:
        trace_payload = sample.detail.get("perf_trace") if isinstance(sample.detail, dict) else None
        if not isinstance(trace_payload, dict):
            continue
        for phase in trace_payload.get("samples", []):
            if not isinstance(phase, dict):
                continue
            key = (
                phase.get("phase"),
                phase.get("timestamp"),
                phase.get("run_id"),
                phase.get("user"),
                phase.get("iteration"),
            )
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "phase": phase.get("phase"),
                "elapsed_ms": phase.get("elapsed_ms"),
                "active_section": phase.get("active_section", ""),
                "user_id": sample.user_id,
                "iteration": sample.iteration,
            })
    return _metric_p95_rows(rows, "phase")


def _timing_metric_rows(diagnostic_samples: list[StepSample], detail_key: str) -> list[dict[str, object]]:
    grouped: dict[str, list[float]] = {}
    for sample in diagnostic_samples:
        detail = sample.detail if isinstance(sample.detail, dict) else {}
        timing = detail.get(detail_key)
        if not isinstance(timing, dict):
            continue
        for metric, value in timing.items():
            if isinstance(value, int | float):
                grouped.setdefault(str(metric), []).append(float(value))
    return [
        {
            "metric": metric,
            "samples": len(values),
            "p95_ms": round(percentile(values, 95), 2),
            "max_ms": round(max(values), 2) if values else 0.0,
        }
        for metric, values in sorted(grouped.items(), key=lambda item: percentile(item[1], 95), reverse=True)
    ]


def _frontend_metric_rows(
    diagnostic_samples: list[StepSample],
    group_key: str,
    *,
    value_prefix: str = "",
) -> list[dict[str, object]]:
    grouped: dict[str, list[float]] = {}
    for sample in diagnostic_samples:
        detail = sample.detail if isinstance(sample.detail, dict) else {}
        frontend = detail.get("frontend_metrics")
        if not isinstance(frontend, dict):
            continue
        group = frontend.get(group_key)
        if not isinstance(group, dict):
            continue
        for metric, value in group.items():
            if isinstance(value, int | float):
                label = f"{value_prefix}{metric}" if value_prefix else str(metric)
                grouped.setdefault(label, []).append(float(value))
    return [
        {
            "metric": metric,
            "samples": len(values),
            "p95": round(percentile(values, 95), 2),
            "max": round(max(values), 2) if values else 0.0,
        }
        for metric, values in sorted(grouped.items(), key=lambda item: percentile(item[1], 95), reverse=True)
    ]


def _frontend_resource_timing_rows(diagnostic_samples: list[StepSample]) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, list[float]]] = {}
    for sample in diagnostic_samples:
        detail = sample.detail if isinstance(sample.detail, dict) else {}
        frontend = detail.get("frontend_metrics")
        if not isinstance(frontend, dict):
            continue
        resources = frontend.get("resource_timing_by_type")
        if not isinstance(resources, dict):
            continue
        for initiator, row in resources.items():
            if not isinstance(row, dict):
                continue
            bucket = grouped.setdefault(str(initiator), {"count": [], "duration": [], "transfer": []})
            for source_key, target_key in (
                ("count", "count"),
                ("total_duration_ms", "duration"),
                ("transfer_size", "transfer"),
            ):
                value = row.get(source_key)
                if isinstance(value, int | float):
                    bucket[target_key].append(float(value))
    output = []
    for initiator, values in grouped.items():
        output.append({
            "initiator_type": initiator,
            "samples": max((len(items) for items in values.values()), default=0),
            "count_p95": round(percentile(values["count"], 95), 2),
            "duration_p95_ms": round(percentile(values["duration"], 95), 2),
            "transfer_size_p95": round(percentile(values["transfer"], 95), 2),
        })
    return sorted(output, key=lambda row: float(row.get("duration_p95_ms", 0) or 0), reverse=True)


def _phase_rows_matching(diagnostic_samples: list[StepSample], prefix: str) -> list[dict[str, object]]:
    rows = _server_phase_rows(diagnostic_samples)
    return [row for row in rows if str(row.get("phase", "")).startswith(prefix)]


def _flatten_perf_trace_samples(sample: StepSample) -> list[dict[str, object]]:
    detail = sample.detail if isinstance(sample.detail, dict) else {}
    trace_payload = detail.get("perf_trace")
    if not isinstance(trace_payload, dict):
        return []
    trace_samples = trace_payload.get("samples", [])
    return [dict(item) for item in trace_samples if isinstance(item, dict)]


def _top_server_phase_for_sample(sample: StepSample) -> dict[str, object]:
    trace_samples = _flatten_perf_trace_samples(sample)
    if not trace_samples:
        return {}
    return max(trace_samples, key=lambda row: float(row.get("elapsed_ms", 0) or 0))


def _initial_load_matrix(release_samples: list[StepSample], diagnostic_samples: list[StepSample]) -> list[dict[str, object]]:
    by_key: dict[tuple[int, int], dict[str, object]] = {}
    for sample in release_samples:
        if sample.action != "initial_load":
            continue
        by_key[(sample.user_id, sample.iteration)] = {
            "user_id": sample.user_id,
            "iteration": sample.iteration,
            "release_initial_load_ms": round(sample.elapsed_ms, 2),
            "ok": sample.ok,
        }
    for sample in diagnostic_samples:
        if not sample.action.startswith("initial_load:"):
            continue
        key = (sample.user_id, sample.iteration)
        row = by_key.setdefault(key, {
            "user_id": sample.user_id,
            "iteration": sample.iteration,
            "release_initial_load_ms": 0.0,
            "ok": True,
        })
        phase = sample.action.split(":", 1)[1]
        row[phase] = round(sample.elapsed_ms, 2)
        detail = sample.detail if isinstance(sample.detail, dict) else {}
        if "navigation_timing" in detail:
            row["browser_navigation_timing"] = detail.get("navigation_timing")
        if "paint_timing" in detail:
            row["browser_paint_timing"] = detail.get("paint_timing")
        if "frontend_metrics" in detail:
            row["frontend_metrics"] = detail.get("frontend_metrics")
        top_phase = _top_server_phase_for_sample(sample)
        if top_phase:
            row["top_server_phase"] = {
                "phase": top_phase.get("phase", ""),
                "elapsed_ms": top_phase.get("elapsed_ms", 0),
            }
            app_entry = [
                phase_row for phase_row in _flatten_perf_trace_samples(sample)
                if str(phase_row.get("phase", "")).startswith("app_entry:")
            ]
            if app_entry:
                slow_app_entry = max(app_entry, key=lambda item: float(item.get("elapsed_ms", 0) or 0))
                row["top_app_entry_phase"] = {
                    "phase": slow_app_entry.get("phase", ""),
                    "elapsed_ms": slow_app_entry.get("elapsed_ms", 0),
                }
    return sorted(by_key.values(), key=lambda row: float(row.get("release_initial_load_ms", 0) or 0), reverse=True)


def _section_nav_matrix(release_samples: list[StepSample], diagnostic_samples: list[StepSample]) -> list[dict[str, object]]:
    rows: dict[tuple[int, int, str], dict[str, object]] = {}
    for sample in release_samples:
        if sample.action != "section_nav":
            continue
        key = (sample.user_id, sample.iteration, sample.section)
        rows[key] = {
            "user_id": sample.user_id,
            "iteration": sample.iteration,
            "section": sample.section,
            "release_section_nav_ms": round(sample.elapsed_ms, 2),
            "ok": sample.ok,
        }
    for sample in diagnostic_samples:
        if not sample.action.startswith("section_nav:"):
            continue
        parts = sample.action.split(":")
        if len(parts) < 3:
            continue
        section = parts[1]
        phase = parts[2]
        key = (sample.user_id, sample.iteration, section)
        row = rows.setdefault(key, {
            "user_id": sample.user_id,
            "iteration": sample.iteration,
            "section": section,
            "release_section_nav_ms": 0.0,
            "ok": True,
        })
        row[phase] = round(sample.elapsed_ms, 2)
        detail = sample.detail if isinstance(sample.detail, dict) else {}
        if "frontend_metrics" in detail:
            row["frontend_metrics"] = detail.get("frontend_metrics")
        top_phase = _top_server_phase_for_sample(sample)
        if top_phase:
            row["top_server_phase"] = {
                "phase": top_phase.get("phase", ""),
                "elapsed_ms": top_phase.get("elapsed_ms", 0),
            }
    return sorted(rows.values(), key=lambda row: float(row.get("release_section_nav_ms", 0) or 0), reverse=True)


def summarize(
    samples: list[StepSample],
    total_elapsed_sec: float,
    args: argparse.Namespace,
    *,
    resource_samples: list[dict[str, object]] | None = None,
    trace_artifact: str = "",
    trace_error: str = "",
) -> dict:
    release_samples = [sample for sample in samples if not sample.diagnostic]
    diagnostic_samples = [sample for sample in samples if sample.diagnostic]
    measured_samples = [sample for sample in release_samples if not sample.skipped]
    elapsed = [sample.elapsed_ms for sample in measured_samples]
    errors = sum(1 for sample in measured_samples if not sample.ok)
    error_rate = errors / len(measured_samples) if measured_samples else 1.0
    skipped = sum(1 for sample in release_samples if sample.skipped)
    p95_ms = percentile(elapsed, 95)
    p99_ms = percentile(elapsed, 99)
    browser_error_steps = sum(1 for sample in release_samples if sample.browser_errors)
    browser_error_messages: dict[str, int] = {}
    visible_errors: dict[str, int] = {}
    for sample in release_samples:
        if sample.visible_error:
            visible_errors[sample.visible_error] = visible_errors.get(sample.visible_error, 0) + 1
        for message in sample.browser_error_messages:
            browser_error_messages[message] = browser_error_messages.get(message, 0) + 1
    step_counts = {
        "initial_load": sum(1 for sample in release_samples if sample.action == "initial_load"),
        "section_nav": sum(1 for sample in release_samples if sample.action == "section_nav"),
        "load_button": sum(1 for sample in release_samples if sample.action.startswith("load_button:")),
    }
    skipped_by_label: dict[str, int] = {}
    skipped_button_details: list[dict[str, object]] = []
    for sample in release_samples:
        if not sample.skipped:
            continue
        label = sample.action.split(":", 1)[1] if sample.action.startswith("load_button:") else sample.action
        skipped_by_label[label] = skipped_by_label.get(label, 0) + 1
        skipped_button_details.append({
            "user_id": sample.user_id,
            "iteration": sample.iteration,
            "section": sample.section,
            "action": sample.action,
            "detail": sample.detail,
        })

    by_action = {}
    for action in sorted({sample.action for sample in release_samples}):
        action_samples = [sample for sample in release_samples if sample.action == action]
        action_elapsed = [sample.elapsed_ms for sample in action_samples if not sample.skipped]
        by_action[action] = {
            "steps": len(action_samples),
            "errors": sum(1 for sample in action_samples if not sample.ok and not sample.skipped),
            "skipped": sum(1 for sample in action_samples if sample.skipped),
            "p95_ms": round(percentile(action_elapsed, 95), 2),
            "max_ms": round(max(action_elapsed), 2) if action_elapsed else 0.0,
        }

    by_section = {}
    for section in sorted({sample.section for sample in release_samples}):
        section_samples = [sample for sample in release_samples if sample.section == section]
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
    diagnostic_by_action = {}
    for action in sorted({sample.action for sample in diagnostic_samples}):
        action_samples = [sample for sample in diagnostic_samples if sample.action == action]
        action_elapsed = [sample.elapsed_ms for sample in action_samples if not sample.skipped]
        diagnostic_by_action[action] = {
            "steps": len(action_samples),
            "errors": sum(1 for sample in action_samples if not sample.ok and not sample.skipped),
            "skipped": sum(1 for sample in action_samples if sample.skipped),
            "p95_ms": round(percentile(action_elapsed, 95), 2),
            "max_ms": round(max(action_elapsed), 2) if action_elapsed else 0.0,
        }
    initial_load_breakdown = [
        {"action": action, **row}
        for action, row in sorted(
            diagnostic_by_action.items(),
            key=lambda item: item[1]["p95_ms"],
            reverse=True,
        )
        if action.startswith("initial_load:")
    ]
    section_nav_breakdown = [
        {"action": action, **row}
        for action, row in sorted(
            diagnostic_by_action.items(),
            key=lambda item: item[1]["p95_ms"],
            reverse=True,
        )
        if action.startswith("section_nav:")
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
    release_throughput = round((len(release_samples) - errors) / total_elapsed_sec, 3) if total_elapsed_sec else 0.0
    diagnostic_throughput = round(len(diagnostic_samples) / total_elapsed_sec, 3) if total_elapsed_sec else 0.0
    total_throughput = round(len(samples) / total_elapsed_sec, 3) if total_elapsed_sec else 0.0
    return {
        "users": args.users,
        "iterations": args.iterations,
        "steps": len(release_samples),
        "diagnostic_steps": len(diagnostic_samples),
        "total_samples": len(samples),
        "measured_steps": len(measured_samples),
        "skipped": skipped,
        "errors": errors,
        "error_rate": round(error_rate, 4),
        "p50_ms": round(statistics.median(elapsed), 2) if elapsed else 0.0,
        "p95_ms": round(p95_ms, 2),
        "p99_ms": round(p99_ms, 2),
        "max_ms": round(max(elapsed), 2) if elapsed else 0.0,
        "avg_ms": round(statistics.mean(elapsed), 2) if elapsed else 0.0,
        "throughput_steps_per_sec": release_throughput,
        "release_throughput_steps_per_sec": release_throughput,
        "diagnostic_throughput_steps_per_sec": diagnostic_throughput,
        "total_throughput_samples_per_sec": total_throughput,
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
        "diagnostic_by_action": diagnostic_by_action,
        "initial_load_breakdown": initial_load_breakdown,
        "section_nav_breakdown": section_nav_breakdown,
        "server_phase_breakdown": _server_phase_rows(diagnostic_samples),
        "app_entry_phase_breakdown": _phase_rows_matching(diagnostic_samples, "app_entry:"),
        "browser_navigation_timing": _timing_metric_rows(diagnostic_samples, "navigation_timing"),
        "browser_paint_timing": _timing_metric_rows(diagnostic_samples, "paint_timing"),
        "frontend_dom_metrics": _frontend_metric_rows(diagnostic_samples, "dom"),
        "frontend_heap_metrics": _frontend_metric_rows(diagnostic_samples, "heap"),
        "frontend_long_tasks": _frontend_metric_rows(diagnostic_samples, "long_tasks"),
        "frontend_layout_shift": _frontend_metric_rows(diagnostic_samples, "layout_shift"),
        "frontend_resource_timing": _frontend_resource_timing_rows(diagnostic_samples),
        "initial_load_matrix": _initial_load_matrix(release_samples, diagnostic_samples),
        "section_nav_matrix": _section_nav_matrix(release_samples, diagnostic_samples),
        "skipped_button_details": skipped_button_details,
        "resource_samples": resource_samples or [],
        "slowest_initial_load_trace": trace_artifact,
        "slowest_initial_load_trace_error": trace_error,
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

    measured_samples = [sample for sample in samples if not sample.skipped and not sample.diagnostic]
    diagnostic_samples = [sample for sample in samples if sample.diagnostic]
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
        f"- Release steps: {summary['steps']} total, {summary['measured_steps']} measured, {summary['skipped']} skipped, {summary['errors']} errors ({summary['error_rate'] * 100:.2f}%)",
        f"- Diagnostic samples: {summary['diagnostic_steps']}",
        f"- Step counts: initial_load {summary['step_counts']['initial_load']}, section_nav {summary['step_counts']['section_nav']}, load_button {summary['step_counts']['load_button']}",
        f"- Latency: p50 {summary['p50_ms']} ms, p95 {summary['p95_ms']} ms, p99 {summary['p99_ms']} ms, max {summary['max_ms']} ms",
        f"- Release throughput: {summary['release_throughput_steps_per_sec']} successful release steps/sec",
        f"- Diagnostic throughput: {summary['diagnostic_throughput_steps_per_sec']} diagnostic samples/sec",
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
    md.extend([
        "",
        "## Diagnostic Action P95",
        "",
    ])
    if summary["diagnostic_by_action"]:
        md.extend([
            "| Action | Steps | Errors | P95 ms | Max ms |",
            "|---|---:|---:|---:|---:|",
        ])
        for action, row in sorted(summary["diagnostic_by_action"].items(), key=lambda item: item[1]["p95_ms"], reverse=True):
            md.append(f"| {action} | {row['steps']} | {row['errors']} | {row['p95_ms']} | {row['max_ms']} |")
    else:
        md.append("No diagnostic action samples were recorded.")
    md.extend([
        "",
        "## Initial Load Breakdown",
        "",
    ])
    if summary["initial_load_breakdown"]:
        md.extend([
            "| Phase | Steps | Errors | P95 ms | Max ms |",
            "|---|---:|---:|---:|---:|",
        ])
        for row in summary["initial_load_breakdown"]:
            phase = str(row["action"]).split(":", 1)[1]
            md.append(f"| {phase} | {row['steps']} | {row['errors']} | {row['p95_ms']} | {row['max_ms']} |")
    else:
        md.append("Initial-load diagnostic substeps were not enabled for this run.")
    md.extend([
        "",
        "## Section Navigation Breakdown",
        "",
    ])
    if summary.get("section_nav_breakdown"):
        md.extend([
            "| Phase | Steps | Errors | P95 ms | Max ms |",
            "|---|---:|---:|---:|---:|",
        ])
        for row in summary["section_nav_breakdown"][:30]:
            phase = str(row["action"]).split(":", 1)[1]
            md.append(f"| {phase} | {row['steps']} | {row['errors']} | {row['p95_ms']} | {row['max_ms']} |")
    else:
        md.append("Section navigation diagnostic substeps were not enabled for this run.")
    if diagnostic_samples:
        diagnostic_slowest = sorted(diagnostic_samples, key=lambda item: item.elapsed_ms, reverse=True)[:10]
        md.extend([
            "",
            "### Slowest Diagnostic Samples",
            "",
            "| User | Iteration | Phase | Status | Elapsed ms | Error |",
            "|---:|---:|---|---|---:|---|",
        ])
        for sample in diagnostic_slowest:
            phase = sample.action.split(":", 1)[1] if ":" in sample.action else sample.action
            md.append(
                f"| {sample.user_id} | {sample.iteration} | {phase} | "
                f"{'OK' if sample.ok else 'FAIL'} | {sample.elapsed_ms:.2f} | {sample.error[:160]} |"
            )
    md.extend([
        "",
        "## Server Phase Breakdown",
        "",
    ])
    if summary.get("server_phase_breakdown"):
        md.extend(["| Phase | Samples | P95 ms | Max ms |", "|---|---:|---:|---:|"])
        for row in summary["server_phase_breakdown"][:20]:
            md.append(f"| {row['phase']} | {row['steps']} | {row['p95_ms']} | {row['max_ms']} |")
    else:
        md.append("No server-side phase trace was collected.")
    md.extend([
        "",
        "## App Entry Phase Breakdown",
        "",
    ])
    if summary.get("app_entry_phase_breakdown"):
        md.extend(["| Phase | Samples | P95 ms | Max ms |", "|---|---:|---:|---:|"])
        for row in summary["app_entry_phase_breakdown"]:
            md.append(f"| {row['phase']} | {row['steps']} | {row['p95_ms']} | {row['max_ms']} |")
    else:
        md.append("No app-entry import phase trace was collected.")
    md.extend([
        "",
        "## Browser Navigation Timing",
        "",
    ])
    if summary.get("browser_navigation_timing"):
        md.extend(["| Metric | Samples | P95 ms/bytes | Max ms/bytes |", "|---|---:|---:|---:|"])
        for row in summary["browser_navigation_timing"]:
            md.append(f"| {row['metric']} | {row['samples']} | {row['p95_ms']} | {row['max_ms']} |")
    else:
        md.append("No browser navigation timing was collected.")
    md.extend([
        "",
        "## Browser Paint Timing",
        "",
    ])
    if summary.get("browser_paint_timing"):
        md.extend(["| Metric | Samples | P95 ms | Max ms |", "|---|---:|---:|---:|"])
        for row in summary["browser_paint_timing"]:
            md.append(f"| {row['metric']} | {row['samples']} | {row['p95_ms']} | {row['max_ms']} |")
    else:
        md.append("No browser paint timing was collected.")
    md.extend([
        "",
        "## Frontend Paint Metrics",
        "",
    ])
    if summary.get("frontend_dom_metrics"):
        md.extend(["### DOM And CSS", "", "| Metric | Samples | P95 | Max |", "|---|---:|---:|---:|"])
        for row in summary["frontend_dom_metrics"]:
            md.append(f"| {row['metric']} | {row['samples']} | {row['p95']} | {row['max']} |")
    else:
        md.append("No frontend DOM/CSS metrics were collected.")
    if summary.get("frontend_heap_metrics"):
        md.extend(["", "### JS Heap", "", "| Metric | Samples | P95 | Max |", "|---|---:|---:|---:|"])
        for row in summary["frontend_heap_metrics"]:
            md.append(f"| {row['metric']} | {row['samples']} | {row['p95']} | {row['max']} |")
    if summary.get("frontend_long_tasks"):
        md.extend(["", "### Long Tasks", "", "| Metric | Samples | P95 | Max |", "|---|---:|---:|---:|"])
        for row in summary["frontend_long_tasks"]:
            md.append(f"| {row['metric']} | {row['samples']} | {row['p95']} | {row['max']} |")
    if summary.get("frontend_layout_shift"):
        md.extend(["", "### Layout Shift", "", "| Metric | Samples | P95 | Max |", "|---|---:|---:|---:|"])
        for row in summary["frontend_layout_shift"]:
            md.append(f"| {row['metric']} | {row['samples']} | {row['p95']} | {row['max']} |")
    if summary.get("frontend_resource_timing"):
        md.extend(["", "### Resource Timing", "", "| Initiator | Samples | Count p95 | Duration p95 ms | Transfer p95 |", "|---|---:|---:|---:|---:|"])
        for row in summary["frontend_resource_timing"]:
            md.append(
                f"| {row['initiator_type']} | {row['samples']} | {row['count_p95']} | "
                f"{row['duration_p95_ms']} | {row['transfer_size_p95']} |"
            )
    md.extend([
        "",
        "## Slowest User Correlation",
        "",
    ])
    if summary.get("initial_load_matrix"):
        md.extend([
            "| User | Initial load ms | goto_commit | shell_title_visible | responseStart | FCP | Top app-entry phase | Top server phase |",
            "|---:|---:|---:|---:|---:|---:|---|---|",
        ])
        for row in summary["initial_load_matrix"][:12]:
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
            md.append(
                f"| {row.get('user_id', '')} | {row.get('release_initial_load_ms', '')} | "
                f"{row.get('goto_commit', '')} | {row.get('shell_title_visible', '')} | "
                f"{response_start} | {fcp} | {app_phase} | {server_phase} |"
            )
    else:
        md.append("No initial-load correlation rows were collected.")
    md.extend([
        "",
        "## Section Navigation Matrix",
        "",
    ])
    if summary.get("section_nav_matrix"):
        md.extend([
            "| User | Iteration | Section | Section nav ms | Title visible | Container visible | Top server phase |",
            "|---:|---:|---|---:|---:|---:|---|",
        ])
        for row in summary["section_nav_matrix"][:20]:
            server = row.get("top_server_phase") if isinstance(row, dict) else {}
            server_phase = (
                f"{server.get('phase', '')} {server.get('elapsed_ms', '')} ms"
                if isinstance(server, dict) and server else ""
            )
            md.append(
                f"| {row.get('user_id', '')} | {row.get('iteration', '')} | {row.get('section', '')} | "
                f"{row.get('release_section_nav_ms', '')} | {row.get('title_visible', '')} | "
                f"{row.get('section_container_visible', '')} | {server_phase} |"
            )
    else:
        md.append("No section navigation correlation rows were collected.")
    md.extend([
        "",
        "## Resource Samples",
        "",
    ])
    if summary.get("resource_samples"):
        md.extend([
            "| Label | CPU % | Memory % | Processes | Browser children | Detail |",
            "|---|---:|---:|---:|---:|---|",
        ])
        for row in summary["resource_samples"]:
            detail = json.dumps(row.get("detail", {}), separators=(",", ":"))[:180]
            md.append(
                f"| {row.get('label', '')} | {row.get('cpu_percent', '')} | "
                f"{row.get('memory_percent', '')} | {row.get('process_count', '')} | "
                f"{row.get('browser_child_process_count', '')} | `{detail}` |"
            )
    else:
        md.append("No host resource telemetry was collected.")
    if summary.get("slowest_initial_load_trace"):
        md.extend([
            "",
            "## Slowest Initial Load Trace",
            "",
            f"- Trace artifact: `{summary['slowest_initial_load_trace']}`",
        ])
    elif summary.get("slowest_initial_load_trace_error"):
        md.extend([
            "",
            "## Slowest Initial Load Trace",
            "",
            f"- Trace capture failed: `{summary['slowest_initial_load_trace_error']}`",
        ])
    md.extend(["", "## Slowest Release Steps", "", "| User | Iteration | Section | Action | Status | Elapsed ms | Error |", "|---:|---:|---|---|---:|---:|---|"])
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
        if summary.get("skipped_button_details"):
            md.extend(["", "### Skipped Button Context", ""])
            for row in summary["skipped_button_details"][:10]:
                detail = row.get("detail", {}) if isinstance(row, dict) else {}
                if not isinstance(detail, dict):
                    detail = {}
                buttons = ", ".join(str(item) for item in detail.get("visible_button_labels", [])[:12])
                headings = ", ".join(str(item) for item in detail.get("visible_headings_and_captions", [])[:8])
                md.extend([
                    f"- User `{row.get('user_id')}` iteration `{row.get('iteration')}` section `{row.get('section')}` action `{row.get('action')}`",
                    f"  - Active title: `{detail.get('active_section_title', '')}`",
                    f"  - Visible buttons: `{buttons}`",
                    f"  - Visible headings/captions: `{headings}`",
                    f"  - Expanded hidden load surfaces: `{detail.get('expand_hidden_load_surfaces_called', '')}`",
                    f"  - Screenshot: `{detail.get('screenshot_path', '')}`",
                ])
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


async def capture_slowest_initial_load_trace(args: argparse.Namespace, samples: list[StepSample]) -> tuple[str, str]:
    """Capture a Playwright trace for one slow initial-load replay."""
    slow_initial = sorted(
        [sample for sample in samples if not sample.diagnostic and sample.action == "initial_load"],
        key=lambda sample: sample.elapsed_ms,
        reverse=True,
    )
    if not slow_initial:
        return "", "no initial_load sample available"
    slowest = slow_initial[0]
    async_playwright, import_error = load_playwright()
    if import_error:
        return "", str(import_error)[:240]
    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    trace_path = output_dir / (
        f"{args.run_id}_slowest_initial_load_user{slowest.user_id:02d}_iter{slowest.iteration}_trace.zip"
    )
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=not args.headed)
            context = await browser.new_context(
                viewport={"width": args.width, "height": args.height},
                extra_http_headers={"X-OVERWATCH-PERF-RUN-ID": args.run_id},
            )
            await context.tracing.start(screenshots=True, snapshots=True, sources=False)
            page = await context.new_page()
            page.set_default_timeout(args.timeout_ms)
            target_url = perf_run_url(
                args.url,
                run_id=f"{args.run_id}_TRACE",
                user_id=slowest.user_id,
                iteration=slowest.iteration,
            )
            await page.goto(target_url, wait_until="domcontentloaded", timeout=args.timeout_ms)
            await page.wait_for_timeout(args.initial_wait_ms)
            await wait_for_app_ready(page, args.timeout_ms)
            if args.wait_initial_idle:
                await wait_for_streamlit_idle(page, args.timeout_ms, args.action_settle_ms)
            await context.tracing.stop(path=str(trace_path))
            await context.close()
            await browser.close()
        return str(trace_path), ""
    except Exception as exc:
        return "", str(exc).replace("\n", " ")[:500]


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
    parser.add_argument("--initial-load-substeps", action=argparse.BooleanOptionalAction, default=argparse.SUPPRESS, help="Record diagnostic-only initial load phase timings without changing release scoring.")
    parser.add_argument("--section-nav-substeps", action=argparse.BooleanOptionalAction, default=argparse.SUPPRESS, help="Record diagnostic-only section navigation phase timings without changing release scoring.")
    parser.add_argument("--wait-initial-idle", action=argparse.BooleanOptionalAction, default=argparse.SUPPRESS, help="After initial app readiness, wait for Streamlit idle before recording the step.")
    parser.add_argument("--trace-slowest-initial-load", action=argparse.BooleanOptionalAction, default=argparse.SUPPRESS, help="After the run, capture one Playwright trace replay for the slowest initial-load user.")
    parser.add_argument("--single-initial-load", action=argparse.BooleanOptionalAction, default=argparse.SUPPRESS, help="Load the app once per user, then repeat in-app section flows without hard page reloads.")
    parser.add_argument("--action-settle-ms", type=int, default=argparse.SUPPRESS, help="Minimum wait after clicks before spinner checks.")
    parser.add_argument("--ramp-seconds", type=float, default=argparse.SUPPRESS, help="Ramp users across this many seconds.")
    parser.add_argument("--width", type=int, default=argparse.SUPPRESS, help="Browser viewport width.")
    parser.add_argument("--height", type=int, default=argparse.SUPPRESS, help="Browser viewport height.")
    parser.add_argument("--headed", action=argparse.BooleanOptionalAction, default=argparse.SUPPRESS, help="Run with visible browser windows.")
    parser.add_argument("--chromium-arg", action="append", dest="chromium_args", default=argparse.SUPPRESS, help="Extra Chromium launch argument. Repeat for multiple arguments.")
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
        samples, total_elapsed_sec, resource_samples = asyncio.run(run_stress(args))
    except Exception as exc:
        print(json.dumps({
            "run_id": args.run_id,
            "readiness_state": "BLOCKED",
            "error": str(exc),
        }, indent=2))
        return 3

    trace_artifact = ""
    trace_error = ""
    if args.trace_slowest_initial_load:
        trace_artifact, trace_error = asyncio.run(capture_slowest_initial_load_trace(args, samples))
    summary = summarize(
        samples,
        total_elapsed_sec,
        args,
        resource_samples=resource_samples,
        trace_artifact=trace_artifact,
        trace_error=trace_error,
    )
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
