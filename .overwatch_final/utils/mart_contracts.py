"""Small contracts for optional OVERWATCH mart access."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class MartResult:
    data: pd.DataFrame
    available: bool
    source: str
    message: str = ""


def mart_source_caption(result: MartResult, fallback_source: str = "ACCOUNT_USAGE") -> str:
    """Human-readable fast-summary/fallback source label for captions."""
    if result.available and not result.data.empty:
        return "Fast summary"
    return fallback_source


__all__ = ["MartResult", "mart_source_caption"]
