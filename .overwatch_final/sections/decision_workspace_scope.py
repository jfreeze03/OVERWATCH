"""Shared Decision Workspace scope helpers."""

from __future__ import annotations

from datetime import date, datetime

from config import DEFAULT_DAY_WINDOW
from runtime_state import GLOBAL_END_DATE, GLOBAL_START_DATE, get_state


def _coerce_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for parser in (date.fromisoformat, datetime.fromisoformat):
        try:
            parsed = parser(text)
            return parsed.date() if isinstance(parsed, datetime) else parsed
        except Exception:
            continue
    return None


def active_decision_window_days(default: int = DEFAULT_DAY_WINDOW) -> int:
    """Return the completed-day Decision packet window for the global range."""
    fallback = int(default or DEFAULT_DAY_WINDOW or 7)
    start = _coerce_date(get_state(GLOBAL_START_DATE))
    end = _coerce_date(get_state(GLOBAL_END_DATE))
    if start is None or end is None:
        return max(1, fallback)
    return max(1, int((end - start).days))


__all__ = ["active_decision_window_days"]
