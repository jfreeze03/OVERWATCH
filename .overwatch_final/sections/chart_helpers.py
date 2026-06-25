"""Section-safe chart helper imports.

Streamlit can hot-reload section modules while keeping an older ``utils.display``
module in memory. Keep section imports stable and defer helper lookup until a
loaded chart path actually needs it.
"""
from __future__ import annotations

from typing import Any

import streamlit as st


def render_time_series_chart(*args: Any, **kwargs: Any):
    try:
        from utils.display import render_time_series_chart as _render
    except ImportError:
        df = args[0] if args else None
        try:
            getattr(st, "line_chart")(df)
        except Exception:
            pass
        return df
    return _render(*args, **kwargs)


def render_area_time_series_chart(*args: Any, **kwargs: Any):
    try:
        from utils.display import render_area_time_series_chart as _render
    except ImportError:
        try:
            from utils.display import render_time_series_chart as _render_time
        except ImportError:
            df = args[0] if args else None
            try:
                getattr(st, "area_chart")(df)
            except Exception:
                pass
            return df
        return _render_time(*args, area=True, **kwargs)
    return _render(*args, **kwargs)


def render_ranked_bar_chart(*args: Any, **kwargs: Any):
    try:
        from utils.display import render_ranked_bar_chart as _render
    except ImportError:
        df = args[0] if args else None
        try:
            getattr(st, "bar_chart")(df)
        except Exception:
            pass
        return df
    return _render(*args, **kwargs)


__all__ = [
    "render_area_time_series_chart",
    "render_ranked_bar_chart",
    "render_time_series_chart",
]
