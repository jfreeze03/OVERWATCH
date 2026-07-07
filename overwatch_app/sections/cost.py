"""Cost Intelligence v2."""

from __future__ import annotations

import pandas as pd

from overwatch_app.sections._shared import section_header


COST_FIRST_VIEWPORT_ORDER = (
    "Cost narrative",
    "Contract Burn-Down chart",
    "Month-end forecast chart with budget line and upper/lower band",
    "Top Cost Drivers",
    "KPI row",
)


def build_forecast_chart_frame(forecast: pd.DataFrame) -> pd.DataFrame:
    if forecast is None or forecast.empty:
        return pd.DataFrame(columns=["DAY", "FORECAST_CREDITS", "BUDGET_CREDITS", "LOWER_BOUND_CREDITS", "UPPER_BOUND_CREDITS"])
    view = forecast.copy()
    for column in ("BUDGET_CREDITS", "LOWER_BOUND_CREDITS", "UPPER_BOUND_CREDITS"):
        if column not in view.columns:
            view[column] = pd.NA
    view["METHOD_LABEL"] = view.get("METHOD_LABEL", "Seasonal fallback")
    view["CONFIDENCE_LABEL"] = view.get("CONFIDENCE_LABEL", "Directional")
    view["SOURCE_FRESHNESS"] = view.get("SOURCE_FRESHNESS", "Precomputed cost forecast mart")
    view["BUDGET_SOURCE"] = view.get("BUDGET_SOURCE", "Governed budget settings")
    return view


def top_cost_drivers(drivers: pd.DataFrame, limit: int = 5) -> pd.DataFrame:
    if drivers is None or drivers.empty:
        return pd.DataFrame(columns=["DRIVER", "CREDITS", "COST_USD", "EXPLANATION"])
    sort_col = "COST_USD" if "COST_USD" in drivers.columns else drivers.columns[-1]
    return drivers.sort_values(sort_col, ascending=False).head(limit)


def build_tag_free_chargeback(
    usage: pd.DataFrame,
    allocation_rules: pd.DataFrame,
) -> pd.DataFrame:
    """Apply governed warehouse/database/role/user/query-tag rules without owner tags."""
    columns = [
        "USAGE_DATE",
        "COMPANY",
        "BUSINESS_UNIT",
        "MATCH_TYPE",
        "MATCH_PATTERN",
        "ALLOCATED_CREDITS",
        "ALLOCATION_CONFIDENCE",
    ]
    if usage is None or usage.empty or allocation_rules is None or allocation_rules.empty:
        return pd.DataFrame(columns=columns + ["UNALLOCATED_CREDITS"])
    rules = allocation_rules[allocation_rules.get("IS_ACTIVE", True).astype(bool)].copy()
    rows: list[dict] = []
    for _, item in usage.iterrows():
        matched = False
        for _, rule in rules.sort_values("PRIORITY", ascending=True).iterrows():
            match_type = str(rule.get("MATCH_TYPE") or "").upper()
            pattern = str(rule.get("MATCH_PATTERN") or "").upper()
            source_value = str(item.get(f"{match_type}_NAME") or item.get(match_type) or "").upper()
            if pattern and pattern in source_value:
                pct = float(rule.get("ALLOCATION_PCT", 100) or 100) / 100.0
                rows.append({
                    "USAGE_DATE": item.get("USAGE_DATE"),
                    "COMPANY": rule.get("COMPANY", item.get("COMPANY", "ALL")),
                    "BUSINESS_UNIT": rule.get("BUSINESS_UNIT", "Unassigned"),
                    "MATCH_TYPE": match_type,
                    "MATCH_PATTERN": pattern,
                    "ALLOCATED_CREDITS": float(item.get("CREDITS", 0) or 0) * pct,
                    "ALLOCATION_CONFIDENCE": "High" if match_type in {"WAREHOUSE", "DATABASE"} else "Medium",
                    "UNALLOCATED_CREDITS": 0.0,
                })
                matched = True
                break
        if not matched:
            rows.append({
                "USAGE_DATE": item.get("USAGE_DATE"),
                "COMPANY": item.get("COMPANY", "ALL"),
                "BUSINESS_UNIT": "Unallocated",
                "MATCH_TYPE": "UNALLOCATED",
                "MATCH_PATTERN": "",
                "ALLOCATED_CREDITS": 0.0,
                "ALLOCATION_CONFIDENCE": "Low",
                "UNALLOCATED_CREDITS": float(item.get("CREDITS", 0) or 0),
            })
    return pd.DataFrame(rows, columns=columns + ["UNALLOCATED_CREDITS"])


def build_cost_view_model(forecast: pd.DataFrame, burn_down: pd.DataFrame, drivers: pd.DataFrame) -> dict:
    chart = build_forecast_chart_frame(forecast)
    return {
        "first_viewport_order": COST_FIRST_VIEWPORT_ORDER,
        "forecast_chart": chart,
        "forecast_has_budget_line": "BUDGET_CREDITS" in chart.columns,
        "forecast_has_bounds_band": {"LOWER_BOUND_CREDITS", "UPPER_BOUND_CREDITS"}.issubset(chart.columns),
        "contract_burn_down": burn_down if burn_down is not None else pd.DataFrame(),
        "top_cost_drivers": top_cost_drivers(drivers),
    }


def render_cost_overview(model: dict | None = None) -> None:
    import streamlit as st

    section_header(st, "Cost Intelligence", "overview")
    model = model or build_cost_view_model(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    st.dataframe(model["contract_burn_down"], hide_index=True)
    st.dataframe(model["forecast_chart"], hide_index=True)
    st.dataframe(model["top_cost_drivers"], hide_index=True)
    st.caption("Dollar figures use the configured credit rate (OVERWATCH_SETTINGS: CREDIT_PRICE_USD).")


def render_chargeback_showback(allocation: pd.DataFrame | None = None) -> None:
    import streamlit as st

    section_header(st, "Chargeback / Showback", "allocation")
    st.dataframe(allocation if allocation is not None else pd.DataFrame(), hide_index=True)
    st.caption("Dollar figures use the configured credit rate (OVERWATCH_SETTINGS: CREDIT_PRICE_USD).")
