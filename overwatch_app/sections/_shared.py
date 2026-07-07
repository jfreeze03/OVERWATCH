"""Shared section rendering helpers."""

from __future__ import annotations

from typing import Any


LATENCY_CAPTION = "Mart-backed - source latency up to ~3h (ACCOUNT_USAGE)"


def workflow_marker(st: Any, workflow_key: str) -> None:
    st.markdown(f'<span class="ow-wf" data-wf="{workflow_key}"></span>', unsafe_allow_html=True)


def section_header(st: Any, title: str, workflow_key: str) -> None:
    workflow_marker(st, workflow_key)
    st.title(title)
    st.caption(LATENCY_CAPTION)
