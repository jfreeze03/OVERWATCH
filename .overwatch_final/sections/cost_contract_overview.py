"""Pure Cost & Contract overview decision helpers."""

from __future__ import annotations

import pandas as pd

from sections.cost_contract_dataframes import _slide_money
from utils.primitives import safe_float, safe_int


def _cost_splash_status(summary: dict) -> tuple[str, str, str]:
    delta_pct = safe_float(summary.get("delta_pct"))
    top_wh = str(summary.get("top_warehouse") or "No warehouse")
    top_delta = safe_float(summary.get("top_warehouse_delta_spend"))
    if delta_pct >= 20:
        return (
            "Attention",
            "Spend is materially above the prior window.",
            f"Start with {top_wh}; loaded movement is {_slide_money(top_delta, signed=True)}.",
        )
    if delta_pct <= -10:
        return (
            "Improving",
            "Spend is below the prior window.",
            "Verify the reduction is expected before claiming savings.",
        )
    return (
        "Stable",
        "Spend is within the current operating range.",
        f"Keep the first explanation on {top_wh}.",
    )


def _cost_splash_next_move(summary: dict) -> tuple[str, str, str]:
    delta_pct = safe_float(summary.get("delta_pct"))
    top_wh = str(summary.get("top_warehouse") or "No warehouse")
    top_wh_delta = safe_float(summary.get("top_warehouse_delta_spend"))
    cortex_spend = safe_float(summary.get("cortex_spend"))
    top_user = str(summary.get("top_cortex_user") or "No Cortex user")
    projected_30d = safe_float(summary.get("projected_30d_spend"))

    if delta_pct >= 20 or top_wh_delta > 0:
        return (
            "Cost Explorer",
            "Usage movement",
            f"{top_wh} is the first cost driver to explain ({_slide_money(top_wh_delta, signed=True)}).",
        )
    if cortex_spend > 0:
        return (
            "Cortex AI",
            "AI spend",
            f"Cortex spend is {_slide_money(cortex_spend)}; top user is {top_user}.",
        )
    if projected_30d > safe_float(summary.get("spend")):
        return (
            "Burn Rate & Forecast",
            "Run-rate check",
            f"Projected 30-day spend is {_slide_money(projected_30d)}. Explain the driver and run-rate pace.",
        )
    return (
        "Cost Recommendations",
        "Cost queue",
        "No dominant cost incident is visible. Review open cost actions or attribution.",
    )


def _cost_executive_decision_stack(summary: dict, action_summary: dict) -> pd.DataFrame:
    delta = safe_float(summary.get("spend_delta"))
    projected = safe_float(summary.get("projected_30d_spend"))
    spend = safe_float(summary.get("spend"))
    cortex = safe_float(summary.get("cortex_spend"))
    open_actions = safe_int(action_summary.get("open_actions"))
    savings = safe_float(action_summary.get("estimated_savings"))
    rows = [
        {
            "DECISION": "Explain usage movement",
            "SIGNAL": _slide_money(delta, signed=True),
            "FIRST_QUESTION": f"Is {summary.get('top_warehouse')} the real driver or just the largest warehouse mover?",
            "OWNER": "DBA / Cost attribution",
            "ROUTE": "Cost Explorer > Warehouse",
        },
        {
            "DECISION": "Validate contract burn",
            "SIGNAL": _slide_money(projected),
            "FIRST_QUESTION": "Does the 30-day run-rate fit the usage baseline and run-rate pace?",
            "OWNER": "DBA / Cost attribution",
            "ROUTE": "Burn Rate & Forecast",
        },
        {
            "DECISION": "Review Cortex usage",
            "SIGNAL": _slide_money(cortex),
            "FIRST_QUESTION": f"Is {summary.get('top_cortex_user')} expected to be the top AI spender?",
            "OWNER": "DBA / AI platform",
            "ROUTE": "Cortex AI",
        },
        {
            "DECISION": "Close owned savings",
            "SIGNAL": f"{open_actions:,} open / {_slide_money(savings)}/mo",
            "FIRST_QUESTION": "Which recommendations have telemetry status, baseline context, and current savings data?",
            "OWNER": "DBA / Service owner",
            "ROUTE": "Cost Recommendations",
        },
    ]
    frame = pd.DataFrame(rows)
    if spend <= 0 and projected <= 0 and cortex <= 0 and not open_actions:
        frame["SIGNAL"] = "Details available when needed"
    return frame
