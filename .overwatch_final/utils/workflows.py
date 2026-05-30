# utils/workflows.py - helpers for DBA workflow hub navigation
from __future__ import annotations

from collections.abc import Mapping, Sequence

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


def render_workflow_selector(
    label: str,
    key: str,
    workflows: Sequence[str],
    details: Mapping[str, str] | None = None,
    *,
    columns: int = 3,
) -> str:
    """Render a compact workflow launcher that honors deep-link state."""
    selected = coerce_workflow_state(key, workflows)
    details = details or {}
    st.caption(label)
    items = list(workflows)
    columns = max(1, min(int(columns or 3), 4))
    for start in range(0, len(items), columns):
        row = items[start:start + columns]
        cols = st.columns(len(row))
        for col, workflow in zip(cols, row):
            with col:
                is_selected = workflow == selected
                if st.button(
                    workflow,
                    key=f"{key}_{start}_{workflow}",
                    type="primary" if is_selected else "secondary",
                    use_container_width=True,
                ):
                    st.session_state[key] = workflow
                    st.rerun()
                if details.get(workflow):
                    st.caption(details[workflow])
    return str(st.session_state.get(key, selected))


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
