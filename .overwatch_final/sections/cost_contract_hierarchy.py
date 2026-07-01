"""Cost & Contract local information architecture helpers."""
from __future__ import annotations

import streamlit as st

from config import DEFAULT_DAY_WINDOW
from runtime_state import set_state
from sections.cost_center_contracts import COST_EXPLORER_LENSES
from sections.cost_contract_contracts import (
    LEGACY_COST_ADVANCED_TOOL_ALIASES,
    LEGACY_COST_INNER_VIEW_ALIASES,
    LEGACY_COST_WORKFLOW_ALIASES,
    WORKFLOW_DETAILS,
    WORKFLOWS,
    _ADVANCED_COST_TOOLS_VISIBLE_KEY,
    _DETAIL_WORKFLOW_KEY,
    _PENDING_DETAIL_WORKFLOW_KEY,
    _PRESERVE_COST_CENTER_VIEW_KEY,
)
from sections.cost_contract_helpers import get_credit_price
from sections.cost_contract_splash import _cached_cost_splash, _cost_splash_summary
from sections.cortex_signals import build_cortex_signal
from sections.decision_workspace_scope import active_decision_window_days
from sections.shell_helpers import render_action_cards, render_primary_section_tabs, render_secondary_lens_pills
from utils.primitives import safe_float, safe_int


COST_EXPLORER_PRIMARY_LENSES = (
    "Warehouse",
    "User / Role",
    "Database",
    "Service",
    "Tag / Application",
    "Department / Cost Center",
    "Environment",
)

COST_PRIMARY_NAV = (
    "Cost Overview",
    "Cost Explorer",
    "Burn Rate & Forecast",
    "Budget vs Actual",
    "Chargeback / Company Split",
    "Cost Recommendations",
    "Cortex AI",
)

COST_LOCAL_MENU = (
    {
        "group": "Main sections",
        "label": "Overview",
        "value": "Cost Overview",
        "detail": "Spend, movement, Cortex, and budget risk.",
    },
    {
        "label": "Cost Explorer",
        "value": "Cost Explorer",
        "detail": "Warehouse, user, database, service, and tag lenses.",
    },
    {
        "label": "Forecast",
        "value": "Burn Rate & Forecast",
        "detail": "Run-rate and projected month-end spend.",
    },
    {
        "label": "Budget vs Actual",
        "value": "Budget vs Actual",
        "detail": "Official totals, allocation, and reconciliation.",
    },
    {
        "label": "Chargeback",
        "value": "Chargeback / Company Split",
        "detail": "Company split and billing-ready rows.",
    },
    {
        "label": "Recommendations",
        "value": "Cost Recommendations",
        "detail": "Savings actions and optimization candidates.",
    },
    {
        "label": "Cortex AI",
        "value": "Cortex AI",
        "detail": "AI spend, forecast, top drivers, and predictive alerts.",
    },
    {
        "group": "Advanced evidence",
        "label": "Waste Detection",
        "value": "Waste Detection",
        "detail": "Idle, anomaly, and avoidable usage review.",
    },
)


def format_money(value: object, *, default: str = "On demand") -> str:
    number = safe_float(value)
    if not number:
        return default
    return f"${number:,.0f}" if abs(number) >= 1000 else f"${number:,.2f}"


def format_pct(value: object, *, default: str = "On demand") -> str:
    number = safe_float(value)
    if not number:
        return default
    return f"{number:+.1f}%"


def active_cost_days() -> int:
    return active_decision_window_days(DEFAULT_DAY_WINDOW)


def build_cost_hero_metrics(company: str) -> tuple[dict[str, str], ...]:
    days = active_cost_days()
    credit_price = safe_float(get_credit_price()) or 3.68
    splash = _cached_cost_splash(company, days, credit_price)
    summary = _cost_splash_summary(splash, credit_price, days)
    has_data = bool(summary.get("has_data"))
    cortex_signal = build_cortex_signal(summary, days=days, total_spend_usd=summary.get("spend"))
    top_driver = str(summary.get("top_warehouse") or "On demand")
    if not has_data:
        top_driver = "On demand"
    return (
        {
            "label": "Total Spend",
            "value": format_money(summary.get("spend")) if has_data else "On demand",
            "detail": "Refresh Cost loads the official cost story.",
        },
        {
            "label": "Spend Movement",
            "value": format_pct(summary.get("delta_pct")) if has_data else "On demand",
            "detail": "Selected window vs prior window.",
        },
        {
            "label": "Forecast / Run-rate",
            "value": format_money(summary.get("projected_30d_spend")) if has_data else "On demand",
            "detail": str(summary.get("run_rate_state") or "Projected after load."),
        },
        {
            "label": "Cortex AI Spend",
            "value": str(cortex_signal.get("spend_label") or "Cortex summary pending"),
            "detail": str(cortex_signal.get("percent_of_total") or "Percent loads with cost facts."),
            "tone": "cortex",
        },
        {
            "label": "Cortex Predictive Alerts",
            "value": str(cortex_signal.get("predictive_alert_label") or "Pending"),
            "detail": str(cortex_signal.get("risk") or "Pending."),
            "tone": "cortex",
        },
        {
            "label": "Contract / Budget Risk",
            "value": "On demand" if not has_data else str(summary.get("yoy_state") or "Loaded"),
            "detail": "Budget proof stays behind explicit detail loads.",
        },
        {
            "label": "Top Driver",
            "value": top_driver,
            "detail": "Warehouse, service, or Cortex driver after load.",
        },
        {
            "label": "Open Savings Actions",
            "value": "On demand",
            "detail": "Recommendations remain review-only and explicit.",
        },
    )


def workflow_label(workflow: str) -> str:
    labels = {
        "Cost Overview": "Overview",
        "Cost Explorer": "Explorer",
        "Burn Rate & Forecast": "Forecast",
        "Budget vs Actual": "Budget",
        "Chargeback / Company Split": "Chargeback",
        "Cost Recommendations": "Recommendations",
    }
    return labels.get(str(workflow), str(workflow))


def lens_label(lens: object) -> str:
    """Return compact labels for the Explorer lens control."""
    if str(lens) == "Department / Cost Center":
        return "Department"
    return str(lens)


def render_cost_primary_tabs(active_workflow: str) -> str:
    """Render the Cost & Contract primary navigation as one horizontal control."""
    return render_primary_section_tabs(
        label="Primary navigation",
        options=COST_PRIMARY_NAV,
        active_value=active_workflow,
        key="cost_contract_workflow",
        format_func=workflow_label,
    )


def render_cost_explorer_lens_pills(active_lens: str) -> str:
    """Render the Cost Explorer lenses as one horizontal control."""
    return render_secondary_lens_pills(
        label="Explore Cost By",
        options=COST_EXPLORER_PRIMARY_LENSES,
        active_value=active_lens,
        key="cc_explorer_lens",
        format_func=lambda value: lens_label(value),
    )


def set_cost_workflow(workflow: str) -> None:
    set_state("cost_contract_workflow", workflow)
    if workflow == "Cost Explorer":
        set_state("cost_center_view", "Cost Explorer")
        if st.session_state.get("cc_explorer_lens") not in COST_EXPLORER_LENSES:
            set_state("cc_explorer_lens", "Warehouse")
    st.rerun()


def set_cost_lens(lens: str) -> None:
    set_state("cc_explorer_lens", lens)
    st.rerun()


def set_cost_action(action: dict[str, object]) -> None:
    workflow = str(action.get("workflow") or "Cost Overview")
    lens = str(action.get("lens") or "")
    set_state("cost_contract_workflow", workflow)
    if workflow == "Cost Explorer":
        set_state("cost_center_view", "Cost Explorer")
    if lens:
        set_state("cc_explorer_lens", lens)
    st.rerun()


def render_cost_action_cards() -> None:
    st.html('<div class="ow-cost-action-strip" aria-label="Recommended Cost actions"></div>')
    render_action_cards(
        (
            {
                "label": "Investigate Cost Spike",
                "reason": "Start with warehouse drivers before reconciliation detail.",
                "cta": "Open Warehouse Drivers",
                "workflow": "Cost Explorer",
                "lens": "Warehouse",
            },
            {
                "label": "Review Cortex AI Costs",
                "reason": "AI spend, forecast, and predictive alerts are a first-class cost lane.",
                "cta": "View Cortex AI",
                "workflow": "Cortex AI",
            },
            {
                "label": "Check Budget Risk",
                "reason": "Compare official totals, allocation, and contract posture.",
                "cta": "Open Budget vs Actual",
                "workflow": "Budget vs Actual",
            },
            {
                "label": "Review Savings Actions",
                "reason": "Read-only recommendations keep optimization work routed.",
                "cta": "Open Recommendations",
                "workflow": "Cost Recommendations",
            },
        ),
        key_prefix="cost_contract_action_card",
        on_select=set_cost_action,
    )


def apply_pending_cost_routes(current_workflow: str) -> str:
    routed_workflow = st.session_state.pop(_PENDING_DETAIL_WORKFLOW_KEY, None)
    legacy_detail_workflow = st.session_state.pop(_DETAIL_WORKFLOW_KEY, None)
    for raw_workflow in (routed_workflow, legacy_detail_workflow):
        advanced_tool = LEGACY_COST_ADVANCED_TOOL_ALIASES.get(str(raw_workflow or ""))
        if advanced_tool:
            st.session_state["cost_contract_advanced_tool"] = advanced_tool
            st.session_state[_ADVANCED_COST_TOOLS_VISIBLE_KEY] = True
        inner_aliases = LEGACY_COST_INNER_VIEW_ALIASES.get(str(raw_workflow or ""), {})
        for key, value in inner_aliases.items():
            st.session_state[key] = value
        if "cost_center_view" in inner_aliases:
            st.session_state[_PRESERVE_COST_CENTER_VIEW_KEY] = True
    routed_workflow = LEGACY_COST_WORKFLOW_ALIASES.get(str(routed_workflow or ""), routed_workflow)
    legacy_detail_workflow = LEGACY_COST_WORKFLOW_ALIASES.get(str(legacy_detail_workflow or ""), legacy_detail_workflow)
    target = routed_workflow if routed_workflow in WORKFLOWS else legacy_detail_workflow
    if target in WORKFLOWS:
        return str(target)
    return current_workflow
