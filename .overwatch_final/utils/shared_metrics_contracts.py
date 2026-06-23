"""Shared metric result contracts."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


LIVE_STORAGE_FALLBACK_MAX_DAYS = 90


@dataclass
class SharedMetricResult:
    """Container for a shared metric frame and its source metadata."""

    data: pd.DataFrame
    source: str
    available: bool = True
    message: str = ""
    effective_days: int | None = None
