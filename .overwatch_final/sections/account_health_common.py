"""Common Account Health helpers shared by the route and focused views."""
from __future__ import annotations

import streamlit as st

from config import DEFAULTS, normalize_section_name
from sections.base import lazy_util as _lazy_util
from utils.primitives import safe_float
from utils.section_guidance import defer_section_note


get_session_for_action = _lazy_util("get_session_for_action")


def _canonical_account_route(route: object) -> str:
    text = str(route or "DBA Control Room").strip()
    return normalize_section_name(text) or "DBA Control Room"


def get_credit_price() -> float:
    return safe_float(st.session_state.get("credit_price", DEFAULTS.get("credit_price", 3.68)), 3.68)


def render_operator_briefing(items: list[tuple[str, str]], *, columns: int = 4) -> None:
    _ = columns
    for label, detail in items:
        defer_section_note(f"{label}: {detail}")


def _account_health_action_session(action: str):
    return get_session_for_action(
        action,
        surface="Account Health",
        offline_note="Account Health shell, source summaries, and cached telemetry remain visible without a live connection.",
    )


__all__ = [
    "_account_health_action_session",
    "_canonical_account_route",
    "get_credit_price",
    "render_operator_briefing",
]
