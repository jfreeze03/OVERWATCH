"""Timezone and freshness helpers for v2."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd


DISPLAY_TIMEZONE = "America/Chicago"
STORAGE_TIMEZONE = "UTC"


def to_display_timezone(value: object, display_timezone: str = DISPLAY_TIMEZONE) -> pd.Timestamp:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return pd.NaT
    if ts.tzinfo is None:
        ts = ts.tz_localize(ZoneInfo(STORAGE_TIMEZONE))
    return ts.tz_convert(ZoneInfo(display_timezone))


def freshness_minutes(value: object, *, now: datetime | None = None, source_timezone: str = STORAGE_TIMEZONE) -> float:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return float("inf")
    if ts.tzinfo is None:
        ts = ts.tz_localize(ZoneInfo(source_timezone))
    current = pd.Timestamp(now or datetime.now(ZoneInfo(STORAGE_TIMEZONE)))
    if current.tzinfo is None:
        current = current.tz_localize(ZoneInfo(STORAGE_TIMEZONE))
    return max(0.0, (current.tz_convert("UTC") - ts.tz_convert("UTC")).total_seconds() / 60.0)


def freshness_minutes_from_row(
    row: pd.Series | dict,
    timestamp_field: str = "SNAPSHOT_TS",
    *,
    now: datetime | None = None,
    source_timezone: str = STORAGE_TIMEZONE,
) -> float:
    age = row.get("AGE_MINUTES") if isinstance(row, dict) else row.get("AGE_MINUTES", None)
    if age is not None and not pd.isna(age):
        try:
            return max(0.0, float(age))
        except (TypeError, ValueError):
            pass
    value = row.get(timestamp_field) if isinstance(row, dict) else row.get(timestamp_field, None)
    return freshness_minutes(value, now=now, source_timezone=source_timezone)
