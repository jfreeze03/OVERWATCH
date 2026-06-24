"""Session-local performance trace helpers for guarded browser runs.

The trace is intentionally passive: normal user sessions do not collect or
render anything, and benchmark sessions keep samples only in Streamlit session
state so the app never writes generated artifacts.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import html
import json
import os
import sys
import threading
import time
from collections.abc import Iterator
from typing import Any

import streamlit as st


PERF_RUN_QUERY_PARAM = "overwatch_perf_run_id"
PERF_USER_QUERY_PARAM = "overwatch_perf_user"
PERF_ITERATION_QUERY_PARAM = "overwatch_perf_iteration"
PERF_TRACE_KEY = "_overwatch_perf_trace_samples"
PERF_RUN_ID_KEY = "_overwatch_perf_run_id"
PERF_USER_KEY = "_overwatch_perf_user"
PERF_ITERATION_KEY = "_overwatch_perf_iteration"
MAX_TRACE_SAMPLES = 96
_PROCESS_STARTED_AT = time.perf_counter()


def _query_value(key: str) -> str:
    try:
        value = st.query_params.get(key)
    except Exception:
        try:
            params = st.experimental_get_query_params()
            value = params.get(key)
        except Exception:
            return ""
    if isinstance(value, list):
        value = value[-1] if value else ""
    return str(value or "").strip()


def _sync_perf_context_from_query() -> dict[str, str]:
    """Return perf context, preferring query params over session state."""
    run_id = _query_value(PERF_RUN_QUERY_PARAM) or str(st.session_state.get(PERF_RUN_ID_KEY, "") or "")
    user = _query_value(PERF_USER_QUERY_PARAM) or str(st.session_state.get(PERF_USER_KEY, "") or "")
    iteration = _query_value(PERF_ITERATION_QUERY_PARAM) or str(
        st.session_state.get(PERF_ITERATION_KEY, "") or ""
    )
    if run_id:
        st.session_state[PERF_RUN_ID_KEY] = run_id
        if user:
            st.session_state[PERF_USER_KEY] = user
        if iteration:
            st.session_state[PERF_ITERATION_KEY] = iteration
    return {"run_id": run_id, "user": user, "iteration": iteration}


def perf_mode_active() -> bool:
    """Return whether the current session belongs to a guarded perf run."""
    return bool(_sync_perf_context_from_query()["run_id"])


def _active_section(active_section: str | None = None) -> str:
    if active_section:
        return str(active_section)
    return str(
        st.session_state.get("_overwatch_active_section")
        or st.session_state.get("nav_section")
        or ""
    )


def _jsonable_detail(detail: Any) -> Any:
    try:
        json.dumps(detail)
        return detail
    except TypeError:
        return str(detail)


def _streamlit_runtime_available() -> bool:
    try:
        from streamlit.runtime import exists

        return bool(exists())
    except Exception:
        return False


def runtime_detail(extra: Any | None = None) -> dict[str, Any]:
    """Return cheap runtime metadata for perf-only trace samples."""
    detail: dict[str, Any] = {
        "python_version": sys.version.split()[0],
        "process_id": os.getpid(),
        "thread_name": threading.current_thread().name,
        "process_uptime_ms": round((time.perf_counter() - _PROCESS_STARTED_AT) * 1000, 2),
        "streamlit_runtime_available": _streamlit_runtime_available(),
    }
    if extra is not None:
        detail["extra"] = _jsonable_detail(extra)
    return detail


def trace_samples() -> list[dict[str, Any]]:
    """Return a copy of the current session trace samples."""
    samples = st.session_state.get(PERF_TRACE_KEY, [])
    if not isinstance(samples, list):
        return []
    return [dict(sample) for sample in samples if isinstance(sample, dict)]


def record_phase(
    phase: str,
    elapsed_ms: float = 0.0,
    *,
    active_section: str | None = None,
    detail: Any | None = None,
) -> None:
    """Append one bounded perf phase sample when a perf run is active."""
    context = _sync_perf_context_from_query()
    if not context["run_id"]:
        return
    sample: dict[str, Any] = {
        "phase": str(phase),
        "elapsed_ms": round(float(elapsed_ms), 2),
        "timestamp": datetime.now(UTC).isoformat(),
        "active_section": _active_section(active_section),
        "run_id": context["run_id"],
        "runtime": runtime_detail(),
    }
    if context["user"]:
        sample["user"] = context["user"]
    if context["iteration"]:
        sample["iteration"] = context["iteration"]
    if detail is not None:
        sample["detail"] = _jsonable_detail(detail)

    samples = st.session_state.get(PERF_TRACE_KEY)
    if not isinstance(samples, list):
        samples = []
    samples.append(sample)
    if len(samples) > MAX_TRACE_SAMPLES:
        samples = samples[-MAX_TRACE_SAMPLES:]
    st.session_state[PERF_TRACE_KEY] = samples


@contextmanager
def trace(
    phase: str,
    *,
    active_section: str | None = None,
    detail: Any | None = None,
) -> Iterator[None]:
    """Time one server-side phase without affecting non-perf sessions."""
    started = time.perf_counter()
    try:
        yield
    finally:
        record_phase(
            phase,
            (time.perf_counter() - started) * 1000,
            active_section=active_section,
            detail=detail,
        )


def render_trace_marker() -> None:
    """Render hidden JSON for browser runners, only during perf sessions."""
    context = _sync_perf_context_from_query()
    if not context["run_id"]:
        return
    payload = {
        "run_id": context["run_id"],
        "user": context["user"],
        "iteration": context["iteration"],
        "samples": trace_samples(),
    }
    escaped = html.escape(json.dumps(payload, separators=(",", ":")), quote=False)
    st.markdown(
        f'<div id="overwatch-perf-trace" style="display:none" aria-hidden="true">{escaped}</div>',
        unsafe_allow_html=True,
    )
