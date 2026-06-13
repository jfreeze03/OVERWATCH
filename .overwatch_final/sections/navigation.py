"""Shared section navigation helpers.

Keep direct section-to-section jumps aligned with sidebar navigation, saved
views, and retired route compatibility.
"""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from config import compatibility_state_for_section, normalize_section_name


def apply_navigation_state(section: str, *, mark_pending: bool = True) -> str:
    """Set the active section and apply compatibility state for retired routes."""
    raw_section = str(section or "").strip()
    target = normalize_section_name(raw_section)
    current = normalize_section_name(st.session_state.get("nav_section", ""))
    if mark_pending and target != current:
        st.session_state["_overwatch_pending_section"] = target
        st.session_state["_overwatch_section_transition_started_at"] = datetime.now().isoformat(timespec="seconds")
    for key, value in compatibility_state_for_section(raw_section).items():
        st.session_state[key] = value
    st.session_state["nav_section"] = target
    return target
