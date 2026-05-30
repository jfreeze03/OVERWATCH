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


def render_operator_briefing(
    rows: Sequence[tuple[str, str]],
    *,
    title: str = "Operator briefing",
    columns: int = 4,
) -> None:
    """Render a visible, low-cost operating brief for workflow hubs."""
    if not rows:
        return
    st.markdown(f"**{title}**")
    columns = max(1, min(int(columns or 4), 4))
    items = list(rows)
    for start in range(0, len(items), columns):
        cols = st.columns(len(items[start:start + columns]))
        for col, (label, detail) in zip(cols, items[start:start + columns]):
            with col:
                st.caption(label)
                st.markdown(f"**{detail}**")


def add_signal_routes(
    df,
    route_rules: Mapping[str, tuple[str, str]],
    *,
    signal_col: str = "SIGNAL",
    workflow_col: str = "NEXT_WORKFLOW",
    action_col: str = "NEXT_ACTION",
    default_workflow: str = "Investigate",
    default_action: str = "Open the source row, validate evidence, then route to the owning DBA workflow.",
):
    """Add consistent next-workflow and next-action columns to an exception dataframe."""
    if df is None or getattr(df, "empty", True):
        return df
    routed = df.copy()

    def _route(signal: object, index: int) -> str:
        workflow, action = route_rules.get(str(signal), (default_workflow, default_action))
        return workflow if index == 0 else action

    routed[workflow_col] = routed.get(signal_col, "").apply(lambda value: _route(value, 0))
    routed[action_col] = routed.get(signal_col, "").apply(lambda value: _route(value, 1))
    return routed


def render_priority_dataframe(
    df,
    *,
    title: str = "Priority view",
    priority_columns: Sequence[str] | None = None,
    sort_by: Sequence[str] | None = None,
    ascending: Sequence[bool] | bool = False,
    max_rows: int = 25,
    raw_label: str = "Full detail",
    height: int | None = None,
) -> None:
    """Show the actionable subset first, with raw detail hidden behind an expander."""
    if df is None or getattr(df, "empty", True):
        return

    view = df.copy()
    if sort_by:
        available_sort = [column for column in sort_by if column in view.columns]
        severity_rank_cols: list[str] = []
        severity_rank_indices: list[int] = []
        severity_rank = {
            "CRITICAL": 0,
            "HIGH": 1,
            "MEDIUM": 2,
            "WATCH": 3,
            "LOW": 4,
            "INFO": 5,
        }
        for idx, column in enumerate(list(available_sort)):
            if str(column).upper() == "SEVERITY":
                rank_col = f"_OVERWATCH_SEVERITY_RANK_{idx}"
                view[rank_col] = view[column].astype(str).str.upper().map(severity_rank).fillna(9)
                available_sort[idx] = rank_col
                severity_rank_cols.append(rank_col)
                severity_rank_indices.append(idx)
        if available_sort:
            sort_ascending: Sequence[bool] | bool
            if isinstance(ascending, Sequence) and not isinstance(ascending, (str, bytes)):
                sort_ascending = list(ascending)[: len(available_sort)]
                if len(sort_ascending) < len(available_sort):
                    sort_ascending = list(sort_ascending) + [False] * (len(available_sort) - len(sort_ascending))
            else:
                sort_ascending = [bool(ascending)] * len(available_sort)
            for idx in severity_rank_indices:
                if idx < len(sort_ascending):
                    sort_ascending[idx] = True
            view = view.sort_values(available_sort, ascending=sort_ascending)
        if severity_rank_cols:
            view = view.drop(columns=severity_rank_cols, errors="ignore")

    if priority_columns:
        columns = [column for column in priority_columns if column in view.columns]
        if columns:
            view = view[columns]

    st.markdown(f"**{title}**")
    st.dataframe(
        view.head(max_rows),
        use_container_width=True,
        hide_index=True,
        height=height,
    )
    if len(df) > max_rows:
        with st.expander(f"{raw_label} ({len(df):,} rows)", expanded=False):
            st.dataframe(df, use_container_width=True, hide_index=True)


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
