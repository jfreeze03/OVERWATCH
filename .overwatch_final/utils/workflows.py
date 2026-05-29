# utils/workflows.py - helpers for DBA workflow hub navigation
from __future__ import annotations

from collections.abc import Sequence

import streamlit as st

from .cost import freshness_note, metric_confidence_label


def coerce_workflow_state(key: str, workflows: Sequence[str]) -> str:
    """Return a valid workflow selection for a session-state key."""
    if not workflows:
        raise ValueError("workflows must contain at least one entry")
    selected = st.session_state.get(key, workflows[0])
    if selected not in workflows:
        selected = workflows[0]
        st.session_state[key] = selected
    return str(selected)


def render_workflow_selector(label: str, key: str, workflows: Sequence[str]) -> str:
    """Render a horizontal workflow selector that honors deep-link state."""
    selected = coerce_workflow_state(key, workflows)
    return st.radio(
        label,
        list(workflows),
        horizontal=True,
        label_visibility="collapsed",
        key=key,
        index=list(workflows).index(selected),
    )


def render_workflow_guide(summary: str, rows: Sequence[tuple[str, str]]) -> None:
    """Render a compact, collapsible DBA decision guide."""
    with st.expander("DBA path", expanded=False):
        st.caption(summary)
        for trigger, action in rows:
            st.markdown(f"**{trigger}**: {action}")


def render_signal_confidence(
    *,
    source: str = "ACCOUNT_USAGE",
    confidence: str = "allocated",
    scope_note: str = "",
) -> None:
    """Render a consistent confidence/freshness strip for workflow hubs."""
    parts = [
        freshness_note(source),
        metric_confidence_label(confidence),
    ]
    if scope_note:
        parts.append(scope_note)
    st.caption(" | ".join(parts))
