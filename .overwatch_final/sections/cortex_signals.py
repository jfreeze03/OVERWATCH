"""Shared Cortex AI cost and predictive-alert UI signals.

This module intentionally reads only passed dictionaries and existing
``st.session_state`` values. It must not import or call Snowflake loaders.
"""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping

import streamlit as st

from sections.base import lazy_pandas
from sections.navigation import apply_navigation_state
from sections.shell_helpers import render_shell_kpi_row, render_shell_snapshot
from utils.primitives import safe_float, safe_int


pd = lazy_pandas()

CORTEX_COST_ROUTE_STATE: tuple[tuple[str, object], ...] = (
    ("cost_contract_workflow", "Cost Overview"),
    ("cost_contract_advanced_tool", "Cortex Spend"),
    ("_cost_contract_show_advanced_tools", True),
)


def cortex_cost_route_updates() -> dict[str, object]:
    """Return state updates that open the Cortex cost-driver workflow."""
    return dict(CORTEX_COST_ROUTE_STATE)


def _money(value: object) -> str:
    number = safe_float(value)
    if abs(number) >= 1000:
        return f"${number:,.0f}"
    return f"${number:,.2f}"


def _pct(part: object, total: object) -> str:
    denominator = safe_float(total)
    if denominator <= 0:
        return "Not loaded"
    return f"{safe_float(part) / denominator * 100:.1f}%"


def _first_number(source: Mapping[str, object], keys: tuple[str, ...]) -> float:
    for key in keys:
        if key in source:
            return safe_float(source.get(key))
    return 0.0


def _first_text(source: Mapping[str, object], keys: tuple[str, ...], default: str = "") -> str:
    for key in keys:
        value = str(source.get(key) or "").strip()
        if value:
            return value
    return default


def _frame_row(frame: object) -> Mapping[str, object]:
    if isinstance(frame, pd.DataFrame) and not frame.empty:
        return frame.iloc[0].to_dict()
    return {}


def _frame_len(frame: object) -> int:
    if isinstance(frame, pd.DataFrame):
        return int(len(frame))
    return 0


def build_cortex_signal(
    summary: Mapping[str, object] | None = None,
    *,
    state: Mapping[str, object] | None = None,
    days: int = 7,
    total_spend_usd: object = 0,
) -> dict[str, object]:
    """Build a Cortex cost/risk signal from already-loaded context only."""
    source = dict(summary or {})
    state_source = state if state is not None else st.session_state
    control_summary = _frame_row(state_source.get("cortex_control_summary") if state_source is not None else None)
    control_exceptions = state_source.get("cortex_control_exceptions") if state_source is not None else None
    predictive_data = state_source.get("cm_cc_pred_data") if state_source is not None else None

    spend = _first_number(
        source,
        ("cortex_spend_usd", "cortex_cost_usd", "cortex_spend", "CORTEX_SPEND_USD"),
    )
    credits = _first_number(source, ("cortex_credits", "CORTEX_CREDITS"))
    requests = safe_int(_first_number(source, ("cortex_requests", "CORTEX_REQUESTS")))
    forecast = _first_number(
        source,
        (
            "cortex_forecast_usd",
            "cortex_projected_30d_cost",
            "projected_cortex_spend_usd",
            "PROJECTED_30D_COST",
        ),
    )
    if not forecast and control_summary:
        forecast = safe_float(control_summary.get("PROJECTED_30D_COST"))
        credits = credits or safe_float(control_summary.get("TOTAL_CREDITS"))
        requests = requests or safe_int(control_summary.get("TOTAL_REQUESTS"))
    if not forecast and spend:
        forecast = spend / max(safe_int(days, 7), 1) * 30.0

    anomaly_count = safe_int(
        _first_number(
            source,
            ("cortex_anomaly_count", "cortex_exception_count", "cortex_predictive_alerts"),
        )
    )
    anomaly_count = max(anomaly_count, _frame_len(control_exceptions), _frame_len(predictive_data))
    top_driver = _first_text(
        source,
        (
            "top_cortex_driver",
            "top_cortex_user",
            "top_cortex_service",
            "top_cortex_warehouse",
            "TOP_CORTEX_USER",
        ),
        "Not loaded",
    )
    trend = _first_text(
        source,
        ("cortex_trend", "cortex_cost_trend", "run_rate_state", "RUN_RATE_STATE"),
        "Predictive data not loaded",
    )
    loaded = any(
        (
            spend > 0,
            credits > 0,
            forecast > 0,
            anomaly_count > 0,
            requests > 0,
            top_driver not in {"", "Not loaded", "No Cortex user"},
        )
    )
    if anomaly_count:
        risk = "Predictive alerts"
    elif forecast and spend and forecast > max(spend * 1.4, spend + 100):
        risk = "Forecast watch"
    elif spend:
        risk = "Spend active"
    else:
        risk = "Not loaded"

    total_spend = safe_float(total_spend_usd) or _first_number(
        source,
        ("current_spend_usd", "spend", "total_spend_usd"),
    )
    return {
        "loaded": loaded,
        "spend_usd": spend,
        "spend_label": _money(spend) if loaded or spend else "No Cortex telemetry available",
        "trend": trend,
        "forecast_usd": forecast,
        "forecast_label": _money(forecast) if forecast else "Predictive alert data not loaded",
        "anomaly_count": anomaly_count,
        "predictive_alert_label": f"{anomaly_count:,}" if anomaly_count else ("0" if loaded else "Not loaded"),
        "top_driver": top_driver if top_driver != "No Cortex user" else "No Cortex user",
        "credits": credits,
        "requests": requests,
        "risk": risk,
        "percent_of_total": _pct(spend, total_spend),
    }


def apply_cortex_cost_route(state: MutableMapping[str, object] | None = None) -> None:
    """Route to the existing Cortex cost-driver workflow without loading data."""
    target_state = state if state is not None else st.session_state
    for key, value in CORTEX_COST_ROUTE_STATE:
        target_state[key] = value
    apply_navigation_state("Cost & Contract")


def render_cortex_signal_panel(
    signal: Mapping[str, object],
    *,
    title: str = "Cortex AI Cost Risk",
    cta_label: str = "Review Cortex AI Cost & Predictive Alerts",
    cta_key: str = "cortex_ai_signal_cta",
    route_to_cost: bool = True,
    session_state_updates: Mapping[str, object] | None = None,
) -> None:
    """Render an executive Cortex lane from already-loaded/session-only values."""
    st.markdown(f"**{title}**")
    render_shell_kpi_row(
        (
            ("Cortex AI Spend", str(signal.get("spend_label") or "No Cortex telemetry available")),
            ("Cortex AI Cost Trend", str(signal.get("trend") or "Predictive data not loaded")),
            ("Cortex Forecast", str(signal.get("forecast_label") or "Predictive alert data not loaded")),
            ("Cortex Predictive Alerts", str(signal.get("predictive_alert_label") or "Not loaded")),
        )
    )
    render_shell_snapshot(
        (
            ("Cortex Cost Risk", str(signal.get("risk") or "Not loaded")),
            ("Percent of Total Spend", str(signal.get("percent_of_total") or "Not loaded")),
            ("Top Cortex Driver", str(signal.get("top_driver") or "Not loaded")),
            ("Telemetry Boundary", "Summary uses already-loaded/session data; details require explicit Cortex load."),
        )
    )
    if st.button(cta_label, key=cta_key, width="stretch"):
        for key, value in (session_state_updates or {}).items():
            st.session_state[str(key)] = value
        if route_to_cost:
            apply_cortex_cost_route()
        st.rerun()


__all__ = [
    "CORTEX_COST_ROUTE_STATE",
    "apply_cortex_cost_route",
    "build_cortex_signal",
    "cortex_cost_route_updates",
    "render_cortex_signal_panel",
]
