"""DataFrame cache helpers for OVERWATCH v2 repositories."""

from __future__ import annotations

from functools import wraps
from typing import Callable, Iterable, TypeVar

import pandas as pd
import streamlit as st


F = TypeVar("F", bound=Callable[..., pd.DataFrame])

UNCACHEABLE_STATES = {
    "CONNECTION_UNAVAILABLE",
    "SETUP_REQUIRED",
    "QUERY_FAILED",
}


def sorted_param_items(params: dict[str, object]) -> tuple[tuple[str, str], ...]:
    """Return stable, Streamlit-cache-friendly params."""
    return tuple(sorted((str(key), str(value)) for key, value in params.items()))


def _copy_frame(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.copy(deep=True)


def has_uncacheable_state(frame: pd.DataFrame) -> bool:
    """Detect explicit failure-state rows that should retry next run."""
    if frame is None or frame.empty:
        return False
    for column in ("DATA_STATE", "STATE", "SUMMARY_STATE"):
        if column in frame.columns:
            states: Iterable[str] = frame[column].dropna().astype(str).str.upper()
            if any(state in UNCACHEABLE_STATES for state in states):
                return True
    return False


def dataframe_cache(func: F) -> F:
    """Wrap a DataFrame function with a 5-minute Streamlit cache and copy-out."""
    cached = st.cache_data(ttl=300, show_spinner=False)(func)

    @wraps(func)
    def wrapper(*args: object, **kwargs: object) -> pd.DataFrame:
        frame = cached(*args, **kwargs)
        if has_uncacheable_state(frame):
            cached.clear()
            return _copy_frame(frame)
        return _copy_frame(frame)

    wrapper.clear = cached.clear  # type: ignore[attr-defined]
    return wrapper  # type: ignore[return-value]
