"""Small opt-in helpers for explicit dataframe loads and exports."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import streamlit as st


def _empty_frame(empty_factory: Callable[[], pd.DataFrame]) -> pd.DataFrame:
    frame = empty_factory()
    if isinstance(frame, pd.DataFrame):
        return frame
    return pd.DataFrame(frame)


def explicit_load_dataframe(
    *,
    button_label: str,
    button_key: str,
    state_key: str,
    loader: Callable[[], pd.DataFrame],
    empty_factory: Callable[[], pd.DataFrame] = pd.DataFrame,
    on_error: Callable[[Exception], None] | None = None,
    status_label: str | None = None,
    force: bool = False,
) -> pd.DataFrame | None:
    """Run a dataframe loader only after explicit user action or force=True."""

    clicked = bool(force) or bool(st.button(button_label, key=button_key))
    if not clicked and state_key in st.session_state:
        cached = st.session_state[state_key]
        return cached if isinstance(cached, pd.DataFrame) else pd.DataFrame(cached)
    if not clicked:
        return None

    try:
        if status_label:
            from .workflows import render_load_status

            with render_load_status(status_label, f"{status_label} ready"):
                result = loader()
        else:
            result = loader()
        frame = result if isinstance(result, pd.DataFrame) else pd.DataFrame(result)
    except Exception as exc:
        frame = _empty_frame(empty_factory)
        if on_error is not None:
            on_error(exc)

    st.session_state[state_key] = frame
    return frame


def render_export_controls(
    df: pd.DataFrame | None,
    filename: str,
    *,
    label: str = "Download CSV",
) -> bool:
    """Render a CSV export control for non-empty dataframes."""

    if df is None or getattr(df, "empty", True):
        return False
    from .downloads import download_csv

    download_csv(df, filename, label=label)
    return True


__all__ = ["explicit_load_dataframe", "render_export_controls"]
