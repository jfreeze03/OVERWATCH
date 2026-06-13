"""Shared Cortex completion guardrails for operator-triggered AI calls."""

from __future__ import annotations

import os
import re
import threading
import time
from datetime import UTC, datetime


DEFAULT_CORTEX_COOLDOWN_SECONDS = 20
DEFAULT_CORTEX_DAILY_CALL_LIMIT = 25
_CORTEX_CALL_GUARD = threading.Lock()
_CORTEX_LAST_CALL_MONOTONIC = 0.0
_CORTEX_LAST_CALL_BY_FEATURE: dict[str, float] = {}


class CortexRateLimitError(RuntimeError):
    """Raised when a manual Cortex request is fired before the cooldown expires."""


def _configured_cooldown_seconds(cooldown_seconds: int | float | None = None) -> float:
    if cooldown_seconds is not None:
        try:
            return max(0.0, float(cooldown_seconds))
        except Exception:
            return float(DEFAULT_CORTEX_COOLDOWN_SECONDS)

    raw_value = os.environ.get("OVERWATCH_CORTEX_COOLDOWN_SECONDS", "")
    try:
        return max(0.0, float(raw_value)) if raw_value else float(DEFAULT_CORTEX_COOLDOWN_SECONDS)
    except Exception:
        return float(DEFAULT_CORTEX_COOLDOWN_SECONDS)


def _configured_daily_call_limit(daily_call_limit: int | None = None) -> int:
    if daily_call_limit is not None:
        try:
            return max(0, int(daily_call_limit))
        except Exception:
            return int(DEFAULT_CORTEX_DAILY_CALL_LIMIT)

    raw_value = os.environ.get("OVERWATCH_CORTEX_DAILY_CALL_LIMIT", "")
    try:
        return max(0, int(raw_value)) if raw_value else int(DEFAULT_CORTEX_DAILY_CALL_LIMIT)
    except Exception:
        return int(DEFAULT_CORTEX_DAILY_CALL_LIMIT)


def _safe_alias(alias: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_]+", "_", str(alias or "ANSWER")).strip("_").upper()
    if not text or not re.match(r"^[A-Z_]", text):
        text = f"CORTEX_{text or 'ANSWER'}"
    return text[:80]


def _safe_feature(feature: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(feature or "manual_cortex")).strip("_").lower()
    return text[:100] or "manual_cortex"


def _today_key() -> str:
    return datetime.now(UTC).date().isoformat()


def _session_state():
    try:
        import streamlit as st

        return st.session_state
    except Exception:
        return None


def _usage_state() -> dict:
    state = _session_state()
    if state is None:
        return {"date": _today_key(), "total_calls": 0, "feature_counts": {}}

    today = _today_key()
    usage = state.setdefault(
        "_overwatch_cortex_usage",
        {"date": today, "total_calls": 0, "feature_counts": {}},
    )
    if usage.get("date") != today:
        usage.clear()
        usage.update({"date": today, "total_calls": 0, "feature_counts": {}})
    usage.setdefault("feature_counts", {})
    usage.setdefault("total_calls", 0)
    return usage


def _reserve_daily_slot(feature: str, daily_call_limit: int) -> None:
    if daily_call_limit <= 0:
        return
    usage = _usage_state()
    total_calls = int(usage.get("total_calls") or 0)
    if total_calls >= daily_call_limit:
        raise CortexRateLimitError(
            f"Cortex session limit reached for today ({daily_call_limit} manual requests)."
        )
    feature_counts = usage.setdefault("feature_counts", {})
    usage["total_calls"] = total_calls + 1
    feature_counts[feature] = int(feature_counts.get(feature, 0) or 0) + 1


def get_cortex_usage_summary() -> dict:
    """Return current session Cortex usage counters without exposing prompt text."""
    usage = dict(_usage_state())
    usage["feature_counts"] = dict(usage.get("feature_counts") or {})
    usage["daily_call_limit"] = _configured_daily_call_limit()
    usage["cooldown_seconds"] = _configured_cooldown_seconds()
    return usage


def get_cortex_telemetry() -> list[dict]:
    """Return recent Cortex request telemetry for the current Streamlit session."""
    state = _session_state()
    if state is None:
        return []
    return list(state.get("_overwatch_cortex_telemetry", []))


def clear_cortex_usage() -> None:
    """Clear current session Cortex counters and telemetry."""
    global _CORTEX_LAST_CALL_MONOTONIC
    state = _session_state()
    if state is not None:
        state["_overwatch_cortex_usage"] = {"date": _today_key(), "total_calls": 0, "feature_counts": {}}
        state["_overwatch_cortex_telemetry"] = []
    with _CORTEX_CALL_GUARD:
        _CORTEX_LAST_CALL_MONOTONIC = 0.0
        _CORTEX_LAST_CALL_BY_FEATURE.clear()


def _record_cortex_event(
    *,
    feature: str,
    model: str,
    alias: str,
    prompt: str,
    status: str,
    elapsed_ms: float = 0.0,
    error: str = "",
    query_tag: str = "",
) -> None:
    state = _session_state()
    if state is None:
        return
    import hashlib

    prompt_text = str(prompt or "")
    entries = state.setdefault("_overwatch_cortex_telemetry", [])
    entries.append({
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "feature": _safe_feature(feature),
        "model": str(model or ""),
        "alias": _safe_alias(alias),
        "status": str(status or "unknown"),
        "elapsed_ms": round(float(elapsed_ms or 0), 2),
        "prompt_chars": len(prompt_text),
        "prompt_hash": hashlib.sha1(prompt_text.encode("utf-8", errors="ignore")).hexdigest()[:12],
        "error": str(error or "")[:240],
        "query_tag": str(query_tag or "")[:250],
    })
    if len(entries) > 100:
        del entries[:-100]


def _cortex_query_tag(session, *, feature: str) -> str:
    try:
        from .session import apply_overwatch_query_tag, build_overwatch_query_tag

        section = f"Cortex {feature.replace('_', ' ').title()}"[:72]
        tag = build_overwatch_query_tag(section=section, tier="cortex")
        apply_overwatch_query_tag(session, tag, section=section)
        return tag
    except Exception:
        return ""


def reserve_cortex_completion(
    *,
    feature: str = "",
    cooldown_seconds: int | float | None = None,
    daily_call_limit: int | None = None,
) -> None:
    """Reserve the next manual Cortex completion slot for this process."""
    normalized_feature = _safe_feature(feature)
    global _CORTEX_LAST_CALL_MONOTONIC
    cooldown = _configured_cooldown_seconds(cooldown_seconds)
    daily_limit = _configured_daily_call_limit(daily_call_limit)

    now = time.monotonic()
    with _CORTEX_CALL_GUARD:
        if cooldown > 0:
            elapsed = now - _CORTEX_LAST_CALL_MONOTONIC
            remaining = cooldown - elapsed
            if remaining > 0:
                wait_seconds = max(1, int(round(remaining)))
                raise CortexRateLimitError(
                    f"Cortex request throttled. Try again in about {wait_seconds} seconds."
                )

            feature_elapsed = now - float(_CORTEX_LAST_CALL_BY_FEATURE.get(normalized_feature, 0.0))
            feature_remaining = cooldown - feature_elapsed
            if feature_remaining > 0:
                wait_seconds = max(1, int(round(feature_remaining)))
                raise CortexRateLimitError(
                    f"Cortex request for {normalized_feature} is throttled. Try again in about {wait_seconds} seconds."
                )

        _reserve_daily_slot(normalized_feature, daily_limit)
        _CORTEX_LAST_CALL_MONOTONIC = now
        _CORTEX_LAST_CALL_BY_FEATURE[normalized_feature] = now


def run_cortex_completion(
    session,
    prompt: str,
    *,
    alias: str = "ANSWER",
    model: str = "mistral-large2",
    prompt_limit: int = 16000,
    feature: str = "",
    cooldown_seconds: int | float | None = None,
    daily_call_limit: int | None = None,
) -> str:
    """Run one guarded Snowflake Cortex completion and return the response text."""
    from .query import sql_literal

    normalized_feature = _safe_feature(feature)
    started = time.perf_counter()
    query_tag = ""
    try:
        reserve_cortex_completion(
            feature=normalized_feature,
            cooldown_seconds=cooldown_seconds,
            daily_call_limit=daily_call_limit,
        )
    except CortexRateLimitError as exc:
        _record_cortex_event(
            feature=normalized_feature,
            model=model,
            alias=alias,
            prompt=prompt,
            status="throttled",
            error=str(exc),
        )
        raise

    column_alias = _safe_alias(alias)
    sql = (
        "SELECT SNOWFLAKE.CORTEX.COMPLETE("
        f"{sql_literal(model, 80)}, {sql_literal(prompt, prompt_limit)}"
        f") AS {column_alias}"
    )
    try:
        query_tag = _cortex_query_tag(session, feature=normalized_feature)
        result = session.sql(sql).collect()
        if not result:
            answer = ""
        else:
            first = result[0]
            try:
                answer = str(first[column_alias] or "").strip()
            except Exception:
                answer = str(getattr(first, column_alias, "") or "").strip()
        _record_cortex_event(
            feature=normalized_feature,
            model=model,
            alias=alias,
            prompt=prompt,
            status="success",
            elapsed_ms=(time.perf_counter() - started) * 1000,
            query_tag=query_tag,
        )
        return answer
    except Exception as exc:
        _record_cortex_event(
            feature=normalized_feature,
            model=model,
            alias=alias,
            prompt=prompt,
            status="error",
            elapsed_ms=(time.perf_counter() - started) * 1000,
            error=str(exc),
            query_tag=query_tag,
        )
        raise
