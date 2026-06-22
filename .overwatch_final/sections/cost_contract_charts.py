"""Reusable Cost & Contract chart render helpers.

The helpers here keep chart plumbing out of the main workflow shell. They may
render Streamlit chart/table controls, but they do not run Snowflake SQL or own
workflow routing.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from sections.cost_contract_advisor import _cost_advisor_category_summary
from sections.cost_contract_dataframes import (
    _cost_spend_trend_rows,
    _cost_warehouse_ranking_rows,
    _service_lens_movement_rows,
)
from sections.shell_helpers import render_escaped_bold_text
from utils.workflows import render_mode_selector, render_priority_dataframe


def _altair():
    """Import Altair only when the cost splash actually renders charts."""
    import altair as alt

    return alt


def _cost_chart_palette() -> dict[str, str]:
    theme_key = str(st.session_state.get("active_theme", "carbon") or "carbon")
    palettes = {
        "carbon": {
            "bar": "#29B5E8",
            "line": "#71D3DC",
            "risk": "#F97316",
            "text": "#eef8fb",
            "muted": "#9bddea",
            "grid": "rgba(113, 211, 220, 0.18)",
        },
        "terminal": {
            "bar": "#0068B7",
            "line": "#29B5E8",
            "risk": "#B45309",
            "text": "#102a43",
            "muted": "#31566b",
            "grid": "rgba(0, 104, 183, 0.18)",
        },
    }
    return palettes.get(theme_key, palettes["carbon"])


def _finalize_cost_chart(chart, *, height: int):
    palette = _cost_chart_palette()
    return (
        chart
        .properties(height=int(height), background="transparent")
        .configure_axis(
            labelColor=palette["muted"],
            titleColor=palette["text"],
            gridColor=palette["grid"],
            domainColor=palette["grid"],
            tickColor=palette["grid"],
            labelFontSize=11,
            titleFontSize=12,
        )
        .configure_view(strokeWidth=0)
        .configure_legend(labelColor=palette["text"], titleColor=palette["text"])
    )


def _render_spend_trend_chart(trend: pd.DataFrame, credit_price: float) -> None:
    trend_plot = _cost_spend_trend_rows(trend, credit_price)
    if trend_plot.empty:
        st.caption("No daily spend trend rows loaded for this scope.")
        return

    palette = _cost_chart_palette()
    alt = _altair()
    base = alt.Chart(trend_plot).encode(
        x=alt.X(
            "USAGE_DATE:T",
            title=None,
            axis=alt.Axis(format="%b %d", labelAngle=-35, labelOverlap=True),
        )
    )
    bars = base.mark_bar(color=palette["bar"], opacity=0.68, cornerRadiusTopLeft=2, cornerRadiusTopRight=2).encode(
        y=alt.Y("SPEND_USD:Q", title="Spend", axis=alt.Axis(format="$,.0f")),
        tooltip=[
            alt.Tooltip("USAGE_DATE:T", title="Date", format="%Y-%m-%d"),
            alt.Tooltip("SPEND_USD:Q", title="Daily spend", format="$,.2f"),
            alt.Tooltip("ROLLING_SPEND_USD:Q", title="Rolling avg", format="$,.2f"),
        ],
    )
    line = base.mark_line(color=palette["line"], strokeWidth=3).encode(
        y=alt.Y("ROLLING_SPEND_USD:Q", title="Spend"),
    )
    points = base.mark_point(color=palette["line"], filled=True, size=42).encode(
        y="ROLLING_SPEND_USD:Q",
    )
    st.altair_chart(_finalize_cost_chart(bars + line + points, height=265), width="stretch")


def _render_cost_chart_with_data_toggle(
    title: str,
    key: str,
    chart_renderer,
    data_rows: pd.DataFrame,
    *,
    priority_columns: list[str] | None = None,
    sort_by: list[str] | None = None,
    max_rows: int = 25,
) -> None:
    """Render a cost chart with an in-place table mode and a clear return path."""
    render_escaped_bold_text(title)
    mode_key = f"{key}_chart_data_mode"
    requested_key = f"{key}_chart_data_requested"
    requested_mode = st.session_state.pop(requested_key, None)
    if requested_mode in {"Chart", "Data"}:
        st.session_state[mode_key] = requested_mode
    mode = render_mode_selector(
        "Cost chart view",
        mode_key,
        ("Chart", "Data"),
        default="Chart",
    )
    if mode == "Data":
        back_col, note_col = st.columns([1, 4])
        with back_col:
            if st.button("Back to chart", key=f"{key}_back_to_chart", width="stretch"):
                st.session_state[requested_key] = "Chart"
                st.rerun()
        with note_col:
            st.caption(f"Showing table rows behind {title}.")
        render_priority_dataframe(
            data_rows,
            title=f"{title} data",
            priority_columns=priority_columns,
            sort_by=sort_by,
            max_rows=max_rows,
            raw_label=f"{title} full data",
            height=260,
        )
        return
    chart_renderer()


def _render_warehouse_ranking_chart(warehouse_delta: pd.DataFrame, credit_price: float) -> None:
    ranking = _cost_warehouse_ranking_rows(warehouse_delta, credit_price)
    if ranking.empty:
        st.caption("No warehouse ranking rows loaded for this scope.")
        return

    palette = _cost_chart_palette()
    alt = _altair()
    base = alt.Chart(ranking).encode(
        y=alt.Y(
            "WAREHOUSE_NAME:N",
            sort=alt.SortField(field="CURRENT_SPEND_USD", order="descending"),
            title=None,
            axis=alt.Axis(labelLimit=210),
        )
    )
    bars = (
        base
        .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
        .encode(
            x=alt.X("CURRENT_SPEND_USD:Q", title="Current spend", axis=alt.Axis(format="$,.0f")),
            color=alt.condition(
                "datum.DELTA_SPEND_USD > 0",
                alt.value(palette["risk"]),
                alt.value(palette["bar"]),
            ),
            tooltip=[
                alt.Tooltip("WAREHOUSE_NAME:N", title="Warehouse"),
                alt.Tooltip("CURRENT_SPEND_USD:Q", title="Current spend", format="$,.2f"),
                alt.Tooltip("PRIOR_SPEND_USD:Q", title="Prior spend", format="$,.2f"),
                alt.Tooltip("DELTA_SPEND_USD:Q", title="Spend delta ($)", format="+,.2f"),
                alt.Tooltip("PCT_DELTA:Q", title="Delta %", format="+.1f"),
            ],
        )
    )
    labels = base.mark_text(align="left", dx=6, baseline="middle", color=palette["text"], fontWeight="bold").encode(
        x=alt.X("CURRENT_SPEND_USD:Q"),
        text="CURRENT_SPEND_LABEL:N",
    )
    chart = _finalize_cost_chart(bars + labels, height=max(230, min(360, 34 * len(ranking) + 54)))
    st.altair_chart(chart, width="stretch")


def _render_service_cost_movement_chart(service_lens: pd.DataFrame, credit_price: float) -> None:
    movement = _service_lens_movement_rows(service_lens, credit_price, limit=8)
    if movement.empty:
        st.caption("No service movement rows loaded for this scope.")
        return
    palette = _cost_chart_palette()
    alt = _altair()
    base = alt.Chart(movement).encode(
        y=alt.Y(
            "SERVICE_TYPE:N",
            sort=alt.SortField(field="SORT_VALUE", order="descending"),
            title=None,
            axis=alt.Axis(labelLimit=190),
        )
    )
    bars = base.mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4, opacity=0.72).encode(
        x=alt.X("CURRENT_SPEND_USD:Q", title="Current spend", axis=alt.Axis(format="$,.0f")),
        color=alt.condition("datum.COST_DELTA_USD > 0", alt.value(palette["risk"]), alt.value(palette["bar"])),
        tooltip=[
            alt.Tooltip("SERVICE_TYPE:N", title="Service"),
            alt.Tooltip("CURRENT_SPEND_USD:Q", title="Current", format="$,.2f"),
            alt.Tooltip("PRIOR_SPEND_USD:Q", title="Prior", format="$,.2f"),
            alt.Tooltip("COST_DELTA_USD:Q", title="Delta ($)", format="+,.2f"),
            alt.Tooltip("CREDIT_DELTA:Q", title="Credit delta", format="+,.2f"),
        ],
    )
    prior_ticks = base.mark_tick(color=palette["line"], thickness=3, size=20).encode(
        x=alt.X("PRIOR_SPEND_USD:Q", title="Current spend"),
    )
    labels = base.mark_text(align="left", dx=6, color=palette["text"], fontWeight="bold").encode(
        x="CURRENT_SPEND_USD:Q",
        text="DELTA_LABEL:N",
    )
    chart = _finalize_cost_chart(bars + prior_ticks + labels, height=max(210, min(360, 34 * len(movement) + 58)))
    st.altair_chart(chart, width="stretch")


def _render_cost_advisor_category_chart(board: pd.DataFrame) -> None:
    summary = _cost_advisor_category_summary(board)
    if summary.empty:
        return
    palette = _cost_chart_palette()
    alt = _altair()
    base = alt.Chart(summary).encode(
        y=alt.Y(
            "CATEGORY:N",
            sort=alt.SortField(field="EST_MONTHLY_SAVINGS_USD", order="descending"),
            title=None,
            axis=alt.Axis(labelLimit=190),
        )
    )
    bars = base.mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4, opacity=0.76).encode(
        x=alt.X("EST_MONTHLY_SAVINGS_USD:Q", title="Estimated monthly dollars", axis=alt.Axis(format="$,.0f")),
        color=alt.value(palette["bar"]),
        tooltip=[
            alt.Tooltip("CATEGORY:N", title="Category"),
            alt.Tooltip("TOP_PRIORITY:N", title="Top priority"),
            alt.Tooltip("FINDINGS:Q", title="Findings", format=","),
            alt.Tooltip("HIGH_FINDINGS:Q", title="High", format=","),
            alt.Tooltip("EST_MONTHLY_SAVINGS_USD:Q", title="Savings / mo", format="$,.2f"),
            alt.Tooltip("EST_MONTHLY_IMPACT_USD:Q", title="Value at risk", format="$,.2f"),
        ],
    )
    impact_ticks = base.mark_tick(color=palette["risk"], thickness=3, size=20).encode(
        x=alt.X("EST_MONTHLY_IMPACT_USD:Q", title="Estimated monthly dollars"),
        tooltip=[
            alt.Tooltip("CATEGORY:N", title="Category"),
            alt.Tooltip("EST_MONTHLY_IMPACT_USD:Q", title="Value at risk", format="$,.2f"),
        ],
    )
    st.altair_chart(
        _finalize_cost_chart(bars + impact_ticks, height=max(190, min(330, 32 * len(summary) + 58))),
        width="stretch",
    )
