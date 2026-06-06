# utils/workflows.py - helpers for DBA workflow hub navigation
from __future__ import annotations

import hashlib
import html
import inspect
from importlib import import_module
from collections.abc import Mapping, Sequence

import streamlit as st

from .cost import freshness_note, get_credit_price, metric_confidence_label
from .section_guidance import defer_section_note, defer_source_note


WORKFLOWS_VERSION = "2026-06-05-cost-companion-guard-v1"
CONTEXT_PRIORITY_COLUMNS = ("ENVIRONMENT", "DATABASE_NAME", "SCHEMA_NAME")
_CREDIT_COST_COMPANION_LIMIT = 10


def prioritize_context_columns(
    df,
    *,
    leading_columns: Sequence[str] = (),
    context_columns: Sequence[str] = CONTEXT_PRIORITY_COLUMNS,
):
    """Keep scope columns visible before wide operational evidence."""
    if df is None or getattr(df, "empty", True):
        return df
    leading = [column for column in leading_columns if column in df.columns]
    context = [
        column for column in context_columns
        if column in df.columns and column not in leading
    ]
    if not leading and not context:
        return df
    ordered = leading + context
    return df[ordered + [column for column in df.columns if column not in ordered]]


def _credit_metric_column(column: str) -> bool:
    upper = str(column or "").upper()
    if "CREDIT" not in upper:
        return False
    if any(token in upper for token in (
        "PRICE", "RATE", "PCT", "PERCENT", "COST", "USD", "DOLLAR",
        "PER_CREDIT", "CREDIT_TYPE", "METHOD", "SCORE", "RANK",
    )):
        return False
    return True


def add_cost_companion_columns(df, *, credit_price: float | None = None, max_columns: int = _CREDIT_COST_COMPANION_LIMIT):
    """Add cost-dollar companions for obvious credit metrics in display tables."""
    if df is None or getattr(df, "empty", True):
        return df
    frame = df.copy()
    try:
        import pandas as pd
    except Exception:
        return frame
    try:
        price = float(get_credit_price() if credit_price is None else credit_price)
    except Exception:
        return frame
    added = 0
    for column in list(frame.columns):
        if added >= int(max_columns or _CREDIT_COST_COMPANION_LIMIT):
            break
        if not _credit_metric_column(str(column)):
            continue
        cost_column = f"{str(column).upper()}_COST_USD"
        if cost_column in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.notna().sum() == 0:
            continue
        if "RATE_USD" in frame.columns:
            rates = pd.to_numeric(frame["RATE_USD"], errors="coerce").fillna(price)
            cost_values = (values.fillna(0) * rates).round(2)
        else:
            cost_values = (values.fillna(0) * price).round(2)
        insert_at = min(len(frame.columns), list(frame.columns).index(column) + 1)
        frame.insert(insert_at, cost_column, cost_values)
        added += 1
    return frame


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
    columns: int = 4,
    show_label: bool = False,
) -> str:
    """Render a compact workflow launcher that honors deep-link state."""
    selected = coerce_workflow_state(key, workflows)
    details = details or {}
    if label and show_label:
        st.caption(label)
    items = list(workflows)
    columns = max(1, min(int(columns or 4), 5))
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
                    width="stretch",
                    help=details.get(workflow) or None,
                ):
                    st.session_state[key] = workflow
                    st.rerun()
    return str(st.session_state.get(key, selected))


def migrate_legacy_workflow_state(
    legacy_key: str,
    target_key: str,
    mapping: Mapping[str, str],
    *,
    remove_legacy: bool = True,
) -> None:
    """Move one old workflow key into a consolidated workflow state key."""
    if remove_legacy:
        legacy_value = st.session_state.pop(legacy_key, None)
    else:
        legacy_value = st.session_state.get(legacy_key)
    mapped = mapping.get(str(legacy_value or ""))
    if mapped:
        st.session_state[target_key] = mapped


def render_workflow_module(workflow: str, workflow_modules: Mapping[str, str]) -> None:
    """Import and render only the specialist module selected by a workflow hub."""
    module_name = workflow_modules.get(str(workflow))
    if not module_name:
        st.warning(f"No module registered for workflow: {workflow}")
        return
    module = import_module(module_name)
    render = getattr(module, "render", None)
    if not callable(render):
        st.warning(f"Workflow module has no render() function: {module_name}")
        return
    render()


def render_workflow_guide(summary: str, rows: Sequence[tuple[str, str]]) -> None:
    """Collect DBA decision-guide text for the bottom notes area."""
    defer_section_note(summary)
    for trigger, action in rows:
        defer_section_note(f"{trigger}: {action}")


def render_operator_briefing(
    rows: Sequence[tuple[str, str]],
    *,
    title: str = "Operating notes",
    columns: int = 4,
) -> None:
    """Collect operating brief text for the bottom notes area."""
    if not rows:
        return
    for label, detail in rows:
        defer_section_note(f"{label}: {detail}")


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
    column_config: Mapping | None = None,
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
        priority = [column for column in priority_columns if column in view.columns]
        context_columns = [
            column for column in CONTEXT_PRIORITY_COLUMNS
            if column in view.columns and column not in priority
        ]
        columns = context_columns + priority
        if columns:
            view = view[columns]
    view = prioritize_context_columns(view)
    view = add_cost_companion_columns(view)

    visible_rows = min(len(view), int(max_rows or 25))
    st.markdown(
        f"""
        <div class="ow-table-heading">
            <span>{html.escape(str(title))}</span>
            <span>Showing {visible_rows:,} of {len(df):,}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    dataframe_kwargs = {
        "use_container_width": True,
        "hide_index": True,
    }
    if height is not None:
        dataframe_kwargs["height"] = height
    default_column_config = {
        "CONFIDENCE": st.column_config.TextColumn("Source Basis"),
        "ALLOCATION_CONFIDENCE": st.column_config.TextColumn("Allocation Source Basis"),
        "SCOPE_CONFIDENCE": st.column_config.TextColumn("Scope Basis"),
        "SOURCE_CONFIDENCE": st.column_config.TextColumn("Source Basis"),
    }
    active_column_config = {
        column: config
        for column, config in default_column_config.items()
        if column in view.columns
    }
    if column_config:
        active_column_config.update(column_config)
    if active_column_config:
        dataframe_kwargs["column_config"] = active_column_config
    st.dataframe(view.head(max_rows), **dataframe_kwargs)
    if len(df) > max_rows:
        with st.expander(f"{raw_label} ({len(df):,} rows)", expanded=False):
            st.caption(
                "Full detail rendering is deferred to keep page navigation fast. "
                "Load it only when you need raw row-level evidence."
            )
            frame = inspect.currentframe()
            caller = frame.f_back if frame is not None else None
            key_basis = "|".join([
                str(getattr(getattr(caller, "f_code", None), "co_filename", "")),
                str(getattr(caller, "f_lineno", "")),
                str(title),
                str(raw_label),
            ])
            button_key = f"ow_raw_detail_{hashlib.sha1(key_basis.encode('utf-8', errors='ignore')).hexdigest()[:12]}"
            if st.button("Render full detail", key=button_key):
                raw_kwargs = {"use_container_width": True, "hide_index": True}
                if active_column_config:
                    raw_kwargs["column_config"] = active_column_config
                st.dataframe(add_cost_companion_columns(prioritize_context_columns(df)), **raw_kwargs)


def render_signal_confidence(
    *,
    source: str = "ACCOUNT_USAGE",
    confidence: str = "allocated",
    scope_note: str = "",
) -> None:
    """Collect consistent source/freshness notes for workflow hubs."""
    parts = [
        freshness_note(source),
        metric_confidence_label(confidence),
    ]
    if scope_note:
        parts.append(scope_note)
    defer_source_note(*parts)
