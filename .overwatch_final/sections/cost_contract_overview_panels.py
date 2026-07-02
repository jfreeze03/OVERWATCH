"""Cost & Contract overview render panels.

These helpers render already-loaded cost overview telemetry.  They do not run
Snowflake SQL or own workflow routing; ``cost_contract.py`` remains the
workflow shell and re-exports these helpers for compatibility.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from runtime_state import set_state
from sections.cost_contract_advisor import _open_cost_action_frame
from sections.cost_contract_dataframes import _short_label, _slide_money
from sections.cost_contract_overview import (
    _cost_executive_decision_stack,
    _cost_splash_next_move,
    _cost_splash_status,
)
from sections.shell_helpers import render_escaped_bold_text, render_shell_snapshot
from utils.cost import credits_to_dollars
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_source_note
from utils.workflows import render_priority_dataframe


def _render_cost_splash_narrative(summary: dict, *, days: int) -> None:
    state, headline, detail = _cost_splash_status(summary)
    top_wh_display = _short_label(summary.get("top_warehouse"), 24)
    top_user = str(summary.get("top_cortex_user") or "No Cortex user")
    top_user_display = _short_label(top_user, 26)
    render_escaped_bold_text(f"{state}: {headline}")
    st.caption(detail)
    metrics = [
        ("Spend", f"${safe_float(summary.get('spend')):,.0f} ({_slide_money(summary.get('spend_delta'), signed=True)})"),
        ("Change", f"{_slide_money(summary.get('spend_delta'), signed=True)} ({safe_float(summary.get('delta_pct')):+.1f}%)"),
        ("Driver", f"{top_wh_display} ({_slide_money(summary.get('top_warehouse_delta_spend'), signed=True)})"),
        ("30d Run", f"{_slide_money(summary.get('projected_30d_spend'))} {str(summary.get('run_rate_state') or '').strip()}".strip()),
    ]
    render_shell_snapshot(tuple(metrics))
    render_shell_snapshot((
        ("Avg / Day", f"${safe_float(summary.get('avg_daily')):,.0f}"),
        ("Peak Day", f"${safe_float(summary.get('peak_day')):,.0f}"),
        ("Cortex Spend", f"${safe_float(summary.get('cortex_spend')):,.0f} ({safe_int(summary.get('cortex_requests')):,} req)"),
        ("Top AI User", f"{top_user_display} (${safe_float(summary.get('top_cortex_user_spend')):,.0f})"),
    ))
    notes = [f"{int(days)}-day window", str(summary.get("cost_basis") or "Warehouse metering total")]
    if safe_int(summary.get("active_services")):
        notes.append(f"{safe_int(summary.get('active_services')):,} active service(s)")
    notes.append(f"{safe_int(summary.get('active_warehouses')):,} active warehouse(s)")
    if top_wh_display != str(summary.get("top_warehouse")):
        notes.append(f"Top warehouse: {summary.get('top_warehouse')}")
    if top_user_display != top_user:
        notes.append(f"Top Cortex user: {top_user}")
    st.caption(" | ".join(notes))


def _render_cost_splash_next_move(summary: dict) -> None:
    workflow, state, detail = _cost_splash_next_move(summary)
    with st.container(border=True):
        label_col, detail_col, action_col = st.columns([1.15, 4.2, 1.2])
        with label_col:
            st.markdown("**Next Cost Move**")
            st.caption(state)
        with detail_col:
            render_escaped_bold_text(workflow)
        with action_col:
            st.write("")
            if st.button(
                "Open workflow",
                key="cost_contract_evidence_load_next_workflow",
                help=detail,
                width="stretch",
            ):
                set_state("cost_contract_workflow", workflow)
                st.rerun()


def _cost_snapshot_action_summary(queue: pd.DataFrame | None) -> dict:
    open_cost_queue = _open_cost_action_frame(queue)
    if open_cost_queue.empty:
        return {"open_actions": 0, "high_actions": 0, "estimated_savings": 0.0}
    severity = open_cost_queue.get("SEVERITY", pd.Series(dtype=str)).fillna("").astype(str).str.title()
    savings = pd.to_numeric(open_cost_queue.get("EST_MONTHLY_SAVINGS", pd.Series(dtype=float)), errors="coerce").fillna(0)
    return {
        "open_actions": int(len(open_cost_queue)),
        "high_actions": int(severity.isin(["Critical", "High"]).sum()),
        "estimated_savings": safe_float(savings.sum()),
    }


def _render_cost_executive_decision_stack(summary: dict) -> None:
    action_summary = _cost_snapshot_action_summary(st.session_state.get("cost_contract_queue", pd.DataFrame()))
    render_priority_dataframe(
        _cost_executive_decision_stack(summary, action_summary),
        title="Cost executive decision stack",
        priority_columns=["DECISION", "SIGNAL", "FIRST_QUESTION", "OWNER", "ROUTE"],
        raw_label="All cost executive decision rows",
        height=230,
        max_rows=4,
    )


def _nullable_float(row: pd.Series, column: str) -> float | None:
    value = row.get(column)
    if value is None or pd.isna(value):
        return None
    return safe_float(value)


def _format_optional_pct(value: float | None, empty: str = "No baseline") -> str:
    if value is None:
        return empty
    return f"{value:+.1f}%"


def _render_metric_items(items: list[dict]) -> None:
    """Render a compact metric row from already-filtered headline items."""
    visible = [item for item in items if item]
    if not visible:
        return
    metrics = []
    for item in visible:
        value = str(item.get("value") or "")
        delta = item.get("delta")
        if delta:
            value = f"{value} ({delta})"
        metrics.append((str(item.get("label") or ""), value))
    render_shell_snapshot(tuple(metrics))


def _render_cost_run_rate_lens(run_rate: pd.DataFrame | None, credit_price: float, error: str = "") -> None:
    st.markdown("**Run-Rate and YOY**")
    if error:
        st.info("Run-rate trend unavailable.")
        defer_source_note(error)
        return
    if run_rate is None or getattr(run_rate, "empty", True):
        defer_source_note("Load the cockpit to show complete-day 7-day averages, 30-day context, and prior-year comparison.")
        return

    row = run_rate.iloc[0]
    avg_7d = safe_float(row.get("AVG_DAILY_7D"))
    avg_30d = safe_float(row.get("AVG_DAILY_30D"))
    credits_7d = safe_float(row.get("CREDITS_7D"))
    projected_30d = safe_float(row.get("PROJECTED_30D_FROM_7D"))
    pct_vs_30d = _nullable_float(row, "PCT_VS_30D_AVG")
    yoy_7d_pct = _nullable_float(row, "YOY_7D_PCT")
    yoy_30d_pct = _nullable_float(row, "YOY_30D_PCT")
    yoy_days_7d = safe_int(row.get("YOY_DAYS_7D"))
    yoy_days_30d = safe_int(row.get("YOY_DAYS_30D"))
    run_state = str(row.get("RUN_RATE_STATE") or "Unknown")
    yoy_state = str(row.get("YOY_STATE") or "Unknown")

    metrics = [
        {
            "label": "7d Avg",
            "value": f"{avg_7d:,.1f} cr/day",
            "delta": _format_optional_pct(pct_vs_30d, run_state) + " vs 30d",
            "delta_color": "inverse",
        },
        {
            "label": "7d Cost",
            "value": f"${credits_to_dollars(credits_7d, credit_price):,.0f}",
            "delta": f"${credits_to_dollars(avg_7d, credit_price):,.0f}/day",
        },
        {
            "label": "30d Run-Rate",
            "value": f"${credits_to_dollars(projected_30d, credit_price):,.0f}/30d",
            "delta": run_state,
        },
    ]
    if yoy_7d_pct is not None and yoy_days_7d > 0:
        metrics.append({
            "label": "7d YOY",
            "value": _format_optional_pct(yoy_7d_pct),
            "delta": f"{yoy_days_7d}/7 PY days",
            "delta_color": "inverse",
        })
    if yoy_30d_pct is not None and yoy_days_30d > 0:
        metrics.append({
            "label": "30d YOY",
            "value": _format_optional_pct(yoy_30d_pct),
            "delta": f"{yoy_days_30d}/30 PY days",
            "delta_color": "inverse",
        })
    _render_metric_items(metrics)

    top_wh = str(row.get("TOP_YOY_INCREASE_WAREHOUSE") or "No warehouse baseline")
    top_delta = safe_float(row.get("TOP_YOY_INCREASE_CREDITS"))
    defer_source_note(
        f"{yoy_state}. Top same-week YOY increase: {top_wh} "
        f"({top_delta:+,.2f} credits). Uses complete days only."
    )


def _build_cost_period_explanation(
    cockpit: pd.DataFrame | None,
    run_rate: pd.DataFrame | None,
    queue: pd.DataFrame | None,
    credit_price: float,
) -> pd.DataFrame:
    """Summarize cost movement, likely driver, and next workflow for executives."""
    rows: list[dict] = []
    cockpit_row = cockpit.iloc[0] if isinstance(cockpit, pd.DataFrame) and not cockpit.empty else pd.Series(dtype=object)
    run_row = run_rate.iloc[0] if isinstance(run_rate, pd.DataFrame) and not run_rate.empty else pd.Series(dtype=object)
    current_credits = safe_float(cockpit_row.get("CURRENT_CREDITS"))
    prior_credits = safe_float(cockpit_row.get("PRIOR_CREDITS"))
    credit_delta = current_credits - prior_credits
    delta_pct = (credit_delta / prior_credits * 100) if prior_credits else None
    top_wh = str(cockpit_row.get("TOP_INCREASE_WAREHOUSE") or "No warehouse loaded")
    top_delta = safe_float(cockpit_row.get("TOP_INCREASE_CREDITS"))
    pct_vs_30d = _nullable_float(run_row, "PCT_VS_30D_AVG") if not run_row.empty else None
    yoy_7d = _nullable_float(run_row, "YOY_7D_PCT") if not run_row.empty else None
    yoy_state = str(run_row.get("YOY_STATE") or "No YOY baseline")
    open_savings = 0.0
    open_count = 0
    if isinstance(queue, pd.DataFrame) and not queue.empty:
        status = queue.get("STATUS", pd.Series(dtype=str)).astype(str)
        open_mask = ~status.isin(["Fixed", "Ignored"])
        open_count = int(open_mask.sum())
        if "EST_MONTHLY_SAVINGS" in queue.columns:
            open_savings = safe_float(pd.to_numeric(queue.loc[open_mask, "EST_MONTHLY_SAVINGS"], errors="coerce").fillna(0).sum())

    rows.append({
        "QUESTION": "Did the bill move?",
        "ANSWER": f"{credit_delta:+,.2f} credits ({_format_optional_pct(delta_pct)}) vs prior window.",
        "DOLLAR_IMPACT": f"${credits_to_dollars(credit_delta, credit_price):+,.0f}",
        "EVIDENCE": f"Current {current_credits:,.2f} credits; prior {prior_credits:,.2f} credits.",
        "NEXT_ACTION": "If the move is above 10%, explain the bill before tuning warehouses or changing workload schedules.",
    })
    rows.append({
        "QUESTION": "What likely changed?",
        "ANSWER": f"{top_wh} is the largest loaded increase at {top_delta:+,.2f} credits.",
        "DOLLAR_IMPACT": f"${credits_to_dollars(top_delta, credit_price):+,.0f}",
        "EVIDENCE": "Cost cockpit current/prior warehouse movement.",
        "NEXT_ACTION": "Open Cost & Contract recommendations to confirm queue, spill, p95, settings, and dollar telemetry for that warehouse.",
    })
    rows.append({
        "QUESTION": "Is this a short spike or trend?",
        "ANSWER": f"7d vs 30d {_format_optional_pct(pct_vs_30d)}; YOY7 {_format_optional_pct(yoy_7d)}; {yoy_state}.",
        "DOLLAR_IMPACT": "Trend telemetry",
        "EVIDENCE": "Complete-day 7d, 30d, and prior-year metering.",
        "NEXT_ACTION": "Use the run-rate lens before calling same-day partial metering a real cost incident.",
    })
    rows.append({
        "QUESTION": "Is there already a fix path?",
        "ANSWER": f"{open_count:,} open action(s), ${open_savings:,.0f}/mo estimated savings.",
        "DOLLAR_IMPACT": f"${open_savings:,.0f}/mo",
        "EVIDENCE": "Open Cost & Contract action queue rows.",
        "NEXT_ACTION": "Work measured actions first and confirm savings with post-period metering.",
    })
    return pd.DataFrame(rows)


def _render_cost_period_explanation(
    cockpit: pd.DataFrame | None,
    run_rate: pd.DataFrame | None,
    queue: pd.DataFrame | None,
    credit_price: float,
) -> None:
    st.markdown("**Why Did Cost Change?**")
    render_priority_dataframe(
        _build_cost_period_explanation(cockpit, run_rate, queue, credit_price),
        title="Cost movement explanation",
        priority_columns=["QUESTION", "ANSWER", "DOLLAR_IMPACT", "EVIDENCE", "NEXT_ACTION"],
        raw_label="All cost movement explanation rows",
        height=260,
    )
