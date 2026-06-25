"""Shared empty/loading states for Snowflake-browser-safe section surfaces."""

from __future__ import annotations

from html import escape as _escape_markup

import streamlit as st


def render_chart_empty_state(title: object = "", detail: object = "") -> None:
    """Render a compact chart empty state without invoking chart libraries."""
    safe_title = _escape_markup(str(title or "No chart data loaded"))
    safe_detail = _escape_markup(
        str(detail or "Load evidence or narrow the scope before charting this surface.")
    )
    st.html(
        '<div class="ow-chart-empty" role="status">'
        f'<div class="ow-chart-empty-title">{safe_title}</div>'
        f'<div class="ow-chart-empty-detail">{safe_detail}</div>'
        "</div>"
    )


__all__ = ["render_chart_empty_state"]
