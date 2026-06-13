"""Shared Cortex completion guardrails for operator-triggered AI calls."""

from __future__ import annotations

import os
import re
import threading
import time


DEFAULT_CORTEX_COOLDOWN_SECONDS = 20
_CORTEX_CALL_GUARD = threading.Lock()
_CORTEX_LAST_CALL_MONOTONIC = 0.0


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


def _safe_alias(alias: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_]+", "_", str(alias or "ANSWER")).strip("_").upper()
    if not text or not re.match(r"^[A-Z_]", text):
        text = f"CORTEX_{text or 'ANSWER'}"
    return text[:80]


def reserve_cortex_completion(*, feature: str = "", cooldown_seconds: int | float | None = None) -> None:
    """Reserve the next manual Cortex completion slot for this process."""
    del feature  # Feature names are kept at call sites for telemetry-friendly signatures.
    global _CORTEX_LAST_CALL_MONOTONIC
    cooldown = _configured_cooldown_seconds(cooldown_seconds)
    if cooldown <= 0:
        return

    now = time.monotonic()
    with _CORTEX_CALL_GUARD:
        elapsed = now - _CORTEX_LAST_CALL_MONOTONIC
        remaining = cooldown - elapsed
        if remaining > 0:
            wait_seconds = max(1, int(round(remaining)))
            raise CortexRateLimitError(
                f"Cortex request throttled. Try again in about {wait_seconds} seconds."
            )
        _CORTEX_LAST_CALL_MONOTONIC = now


def run_cortex_completion(
    session,
    prompt: str,
    *,
    alias: str = "ANSWER",
    model: str = "mistral-large2",
    prompt_limit: int = 16000,
    feature: str = "",
    cooldown_seconds: int | float | None = None,
) -> str:
    """Run one guarded Snowflake Cortex completion and return the response text."""
    from .query import sql_literal

    reserve_cortex_completion(feature=feature, cooldown_seconds=cooldown_seconds)
    column_alias = _safe_alias(alias)
    sql = (
        "SELECT SNOWFLAKE.CORTEX.COMPLETE("
        f"{sql_literal(model, 80)}, {sql_literal(prompt, prompt_limit)}"
        f") AS {column_alias}"
    )
    result = session.sql(sql).collect()
    if not result:
        return ""
    first = result[0]
    try:
        return str(first[column_alias] or "").strip()
    except Exception:
        return str(getattr(first, column_alias, "") or "").strip()
