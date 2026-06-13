"""Canonical small conversion helpers for OVERWATCH.

Keep these dependency-light so workspace sections can import them without
pulling in pandas or Snowflake clients during first paint.
"""

from __future__ import annotations


def _looks_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(value != value)
    except Exception:
        return False


def safe_float(value: object, default: float = 0.0) -> float:
    """Convert a value to float safely, returning ``default`` on failure."""
    if _looks_missing(value):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: object, default: int = 0) -> int:
    """Convert a value to int safely, returning ``default`` on failure."""
    if _looks_missing(value):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_str(value: object, default: str = "") -> str:
    """Convert a value to stripped text while treating null-like text as empty."""
    if _looks_missing(value):
        return default
    text = str(value).strip()
    return text if text and text.upper() not in {"NONE", "NAN", "NULL", "<NA>"} else default


def safe_bool(value: object, default: bool = False) -> bool:
    """Convert common truthy/falsey values to bool safely."""
    if _looks_missing(value):
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "on"}:
        return True
    if text in {"false", "0", "no", "n", "off"}:
        return False
    return default


def safe_strip_tz(series):
    """Strip timezone metadata from a pandas datetime series when present."""
    try:
        if hasattr(series.dt, "tz") and series.dt.tz is not None:
            return series.dt.tz_localize(None)
    except (AttributeError, TypeError):
        pass
    return series


def coerce_numeric(series, default: float = 0.0):
    """Coerce a pandas series to numeric, filling missing values."""
    import pandas as pd

    return pd.to_numeric(series, errors="coerce").fillna(default)
