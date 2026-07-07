"""Executive Landing v2."""

from __future__ import annotations

from typing import Any

import pandas as pd

from overwatch_app.sections._shared import section_header


EXECUTIVE_FIRST_VIEWPORT_ORDER = (
    "Executive narrative summary",
    "Platform Score with decomposition",
    "Contract Burn-Down",
    "Month-end forecast vs budget variance in dollars",
    "Critical / High issues",
    "Open Work Items",
    "Source Freshness",
    "Top cost driver",
)


def platform_score_decomposition(row: dict[str, Any] | pd.Series) -> pd.DataFrame:
    components = [
        ("Reliability", row.get("RELIABILITY_SCORE", 0), 0.25, "Task success, query failures, blocked time"),
        ("Cost", row.get("COST_SCORE", 0), 0.25, "Forecast variance, burn-down, top driver movement"),
        ("Security", row.get("SECURITY_SCORE", 0), 0.2, "Suspicious login confidence and privileged access risk"),
        ("Freshness", row.get("FRESHNESS_SCORE", 0), 0.2, "Precomputed source freshness mart status"),
        ("Action Closure", row.get("ACTION_SCORE", 0), 0.1, "Open work item SLA and verification status"),
    ]
    frame = pd.DataFrame(components, columns=["COMPONENT", "SCORE", "WEIGHT", "SOURCE_METRICS"])
    frame["WEIGHTED_SCORE"] = pd.to_numeric(frame["SCORE"], errors="coerce").fillna(0) * frame["WEIGHT"]
    return frame


def build_contract_burn_down(row: dict[str, Any] | pd.Series) -> dict[str, float | str | bool]:
    committed = float(row.get("COMMITTED_CREDITS", 0) or 0)
    consumed = float(row.get("CONSUMED_CREDITS", 0) or 0)
    elapsed = float(row.get("YEAR_ELAPSED_PCT", 0) or 0)
    projected = float(row.get("PROJECTED_PERIOD_END_CREDITS", consumed) or consumed)
    setup_required = committed <= 0
    return {
        "setup_required": setup_required,
        "setup_message": "Set ANNUAL_COMMITTED_CREDITS in OVERWATCH_SETTINGS to activate contract burn-down.",
        "committed_credits": committed,
        "consumed_credits": consumed,
        "annual_commit_burn_pct": round((consumed / committed) * 100, 2) if committed else None,
        "year_elapsed_pct": elapsed,
        "projected_period_end_credits": projected,
        "projected_over_under_credits": projected - committed,
        "projected_over_under_usd": float(row.get("PROJECTED_OVER_UNDER_USD", 0) or 0),
        "budget_source": str(row.get("BUDGET_SOURCE", "Governed budget settings")),
    }


def build_executive_actions_queue(actions: pd.DataFrame) -> pd.DataFrame:
    required = [
        "SEVERITY",
        "FINDING",
        "STATUS",
        "TICKET_ID",
        "VERIFICATION_STATUS",
        "DUE_OR_SLA",
        "NEXT_ACTION",
    ]
    if actions is None or actions.empty:
        return pd.DataFrame(columns=required)
    view = actions.copy()
    for column in required:
        if column not in view.columns:
            view[column] = ""
    return view[required]


def build_executive_view_model(summary: pd.DataFrame, actions: pd.DataFrame, freshness: pd.DataFrame) -> dict[str, Any]:
    row = summary.iloc[0] if summary is not None and not summary.empty else pd.Series(dtype=object)
    return {
        "first_viewport_order": EXECUTIVE_FIRST_VIEWPORT_ORDER,
        "narrative": str(row.get("EXECUTIVE_NARRATIVE", "OVERWATCH is waiting for the precomputed executive mart.")),
        "platform_score": float(row.get("PLATFORM_SCORE", 0) or 0),
        "platform_score_components": platform_score_decomposition(row),
        "contract_burn_down": build_contract_burn_down(row),
        "forecast_budget_variance_usd": float(row.get("FORECAST_BUDGET_VARIANCE_USD", 0) or 0),
        "critical_high_issues": int(row.get("CRITICAL_HIGH_ISSUES", 0) or 0),
        "open_work_items": build_executive_actions_queue(actions),
        "source_freshness": freshness if freshness is not None else pd.DataFrame(),
        "top_cost_driver": str(row.get("TOP_COST_DRIVER", "")),
        "overwatch_self_cost": float(row.get("OVERWATCH_SELF_COST_USD", 0) or 0),
    }


def render_executive_overview(model: dict[str, Any] | None = None) -> None:
    import streamlit as st

    model = model or build_executive_view_model(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    section_header(st, "Executive Landing", "overview")
    st.write(model["narrative"])
    st.dataframe(model["platform_score_components"], hide_index=True)
    burn_down = model["contract_burn_down"]
    if burn_down.get("setup_required"):
        st.warning(burn_down["setup_message"])
    st.dataframe(pd.DataFrame([burn_down]), hide_index=True)
    st.dataframe(model["open_work_items"], hide_index=True)
