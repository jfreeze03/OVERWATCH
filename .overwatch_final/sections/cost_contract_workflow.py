# sections/cost_contract_workflow.py - Cost & Contract workflow state and routing helpers.
from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from config import DEFAULT_DAY_WINDOW, DEFAULT_ENVIRONMENT
from sections.base import lazy_util as _lazy_util
from sections.cost_contract_contracts import (
    ADVANCED_COST_TOOL_DETAILS,
    ADVANCED_COST_TOOL_MODULES,
    COST_WORKFLOW_PRESETS,
    LEGACY_COST_ADVANCED_TOOL_ALIASES,
    LEGACY_COST_INNER_VIEW_ALIASES,
    LEGACY_COST_WORKFLOW_ALIASES,
    WORKFLOW_MODULES,
    _ADVANCED_COST_TOOLS_VISIBLE_KEY,
    _LAST_COST_WORKFLOW_KEY,
    _PRESERVE_COST_CENTER_VIEW_KEY,
)
from sections.cost_contract_helpers import get_credit_price
from sections.cost_contract_rendering import render_workflow_module
from utils.primitives import safe_float, safe_int


get_active_environment = _lazy_util("get_active_environment")
render_workflow_selector = _lazy_util("render_workflow_selector")

_COST_OVERVIEW_RENDERER: Callable[[str, float], None] | None = None


def set_cost_overview_renderer(renderer: Callable[[str, float], None] | None) -> None:
    global _COST_OVERVIEW_RENDERER
    _COST_OVERVIEW_RENDERER = renderer


def _normalize_cost_contract_workflow_state() -> None:
    current = str(st.session_state.get("cost_contract_workflow") or "")
    advanced_tool = LEGACY_COST_ADVANCED_TOOL_ALIASES.get(current)
    if advanced_tool:
        st.session_state["cost_contract_advanced_tool"] = advanced_tool
        st.session_state[_ADVANCED_COST_TOOLS_VISIBLE_KEY] = True
    inner_aliases = LEGACY_COST_INNER_VIEW_ALIASES.get(current, {})
    for key, value in inner_aliases.items():
        st.session_state[key] = value
    if "cost_center_view" in inner_aliases:
        st.session_state[_PRESERVE_COST_CENTER_VIEW_KEY] = True
    mapped = LEGACY_COST_WORKFLOW_ALIASES.get(current)
    if mapped:
        st.session_state["cost_contract_workflow"] = mapped


def _apply_cost_workflow_preset(workflow: str) -> None:
    workflow_name = str(workflow)
    presets = COST_WORKFLOW_PRESETS.get(workflow_name, {})
    workflow_changed = st.session_state.get(_LAST_COST_WORKFLOW_KEY) != workflow_name
    preserve_cost_center_view = bool(st.session_state.pop(_PRESERVE_COST_CENTER_VIEW_KEY, False))
    for key, value in presets.items():
        if (
            key in {"cost_center_view", "cc_explorer_lens"}
            and preserve_cost_center_view
            and st.session_state.get(key)
        ):
            continue
        if workflow_changed or not st.session_state.get(key):
            st.session_state[key] = value
    st.session_state[_LAST_COST_WORKFLOW_KEY] = workflow_name


def _render_advanced_cost_tools(company: str, environment: str) -> None:
    tool = render_workflow_selector(
        "Advanced cost tool",
        "cost_contract_advanced_tool",
        tuple(ADVANCED_COST_TOOL_DETAILS),
        ADVANCED_COST_TOOL_DETAILS,
        columns=2,
    )
    render_workflow_module(tool, ADVANCED_COST_TOOL_MODULES)


def _render_cost_contract_workflow(workflow: str, company: str, environment: str) -> None:
    if workflow == "Cost Overview":
        if _COST_OVERVIEW_RENDERER is None:
            st.warning("Cost Overview renderer is not registered.")
            return
        _COST_OVERVIEW_RENDERER(company, safe_float(get_credit_price()) or 3.68)
        return
    _apply_cost_workflow_preset(workflow)
    if WORKFLOW_MODULES.get(str(workflow)) == "sections.cost_center":
        st.session_state["_cost_center_embedded_in_cost_contract"] = True
    render_workflow_module(workflow, WORKFLOW_MODULES)


def _render_cost_filter_indicator() -> None:
    filters: list[str] = []
    environment = str(get_active_environment() or DEFAULT_ENVIRONMENT)
    if environment and environment != DEFAULT_ENVIRONMENT:
        filters.append(f"Environment: {environment}")
    for label, key in (
        ("Warehouse", "global_warehouse"),
        ("User", "global_user"),
        ("Role", "global_role"),
        ("Database", "global_database"),
    ):
        value = str(st.session_state.get(key) or "").strip()
        if value:
            filters.append(f"{label}: {value}")
    selected_days = safe_int(
        st.session_state.get("cost_contract_cockpit_window", DEFAULT_DAY_WINDOW),
        DEFAULT_DAY_WINDOW,
    )
    if selected_days != DEFAULT_DAY_WINDOW:
        filters.append(f"Cost window: {selected_days}d")
    if filters:
        st.caption("Filters active: " + " | ".join(filters))
    else:
        st.caption("Filters active: company and date window only.")
