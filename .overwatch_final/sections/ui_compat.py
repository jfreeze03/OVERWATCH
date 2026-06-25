"""Snowflake-browser-safe UI compatibility wrappers for section shells."""

from __future__ import annotations

from contextlib import nullcontext
from collections.abc import Iterator

import streamlit as st


def _text(value: object) -> str:
    return str(value or "").strip()


def safe_caption(value: object) -> None:
    """Render optional caption copy without forcing callers to guard empties."""
    text = _text(value)
    if text:
        st.caption(text)


def safe_info(value: object) -> None:
    """Render optional informational copy."""
    text = _text(value)
    if text:
        st.info(text)


def safe_warning(value: object) -> None:
    """Render optional warning copy."""
    text = _text(value)
    if text:
        st.warning(text)


def safe_button(
    label: object,
    *,
    key: str,
    width: str = "stretch",
    type: str = "secondary",
    help: str | None = None,
) -> bool:
    """Render a button while preserving the caller-owned stable key."""
    text = _text(label)
    if not text:
        return False
    return bool(st.button(text, key=key, width=width, type=type, help=help))


def safe_expander(label: object, *, expanded: bool = False) -> Iterator[object]:
    """Return an expander context, or a no-op context if the label is empty."""
    text = _text(label)
    if not text:
        return nullcontext()
    return st.expander(text, expanded=expanded)


__all__ = [
    "safe_button",
    "safe_caption",
    "safe_expander",
    "safe_info",
    "safe_warning",
]
