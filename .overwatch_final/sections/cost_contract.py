# sections/cost_contract.py - Consolidated cost and contract workflow
from __future__ import annotations

import pandas as pd
import streamlit as st

from sections import (
    cortex_monitor,
    cost_center,
    recommendations,
    snowflake_value,
    spcs_tracker,
)
from utils import (
    credits_to_dollars,
    format_snowflake_error,
    get_active_company,
    get_session,
    get_wh_filter_clause,
    load_action_queue,
    run_query,
    safe_float,
    safe_int,
)
from utils.workflows import render_signal_confidence, render_workflow_guide, render_workflow_selector

WORKFLOWS = (
    "Explain bill / attribution / contract",
    "Recommendations and action queue",
    "Snowflake value log",
    "AI and Cortex spend",
    "SPCS spend",
)

WORKFLOW_DETAILS = {
    "Explain bill / attribution / contract": "Start here: bill movement, chargeback, contract pacing, and cost drivers.",
    "Recommendations and action queue": "Owned fixes with severity, proof, savings, and status.",
    "Snowflake value log": "Evidence that DBA changes avoided spend or improved service.",
    "AI and Cortex spend": "Cortex usage, model spend, users, and runaway AI cost signals.",
    "SPCS spend": "Snowpark Container Services usage and service cost exposure.",
}


def _cost_score(current_credits: float, prior_credits: float, open_actions: int, high_actions: int, cortex_exceptions: int) -> int:
    delta_pct = ((safe_float(current_credits) - safe_float(prior_credits)) / safe_float(prior_credits) * 100) if safe_float(prior_credits) > 0 else 0.0
    penalty = (
        min(max(delta_pct, 0) / 2, 24)
        + min(safe_int(open_actions) * 1.5, 18)
        + min(safe_int(high_actions) * 5, 28)
        + min(safe_int(cortex_exceptions) * 4, 22)
    )
    return max(0, min(100, int(round(100 - penalty))))


def _cost_rating(score: int) -> str:
    if score >= 92:
        return "Controlled"
    if score >= 82:
        return "Watch"
    if score >= 70:
        return "Pressure"
    return "Cost Incident"


def _build_cost_cockpit_sql(company: str, days: int) -> str:
    wh_filter = get_wh_filter_clause("warehouse_name", company)
    return f"""
    WITH current_period AS (
        SELECT
            warehouse_name,
            SUM(COALESCE(credits_used, 0)) AS credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          AND start_time < CURRENT_TIMESTAMP()
          {wh_filter}
        GROUP BY warehouse_name
    ),
    prior_period AS (
        SELECT
            warehouse_name,
            SUM(COALESCE(credits_used, 0)) AS credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{int(days) * 2}, CURRENT_TIMESTAMP())
          AND start_time < DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          {wh_filter}
        GROUP BY warehouse_name
    ),
    deltas AS (
        SELECT
            COALESCE(c.warehouse_name, p.warehouse_name) AS warehouse_name,
            COALESCE(c.credits, 0) AS current_credits,
            COALESCE(p.credits, 0) AS prior_credits,
            COALESCE(c.credits, 0) - COALESCE(p.credits, 0) AS credit_delta
        FROM current_period c
        FULL OUTER JOIN prior_period p
            ON c.warehouse_name = p.warehouse_name
    )
    SELECT
        SUM(current_credits) AS current_credits,
        SUM(prior_credits) AS prior_credits,
        COUNT_IF(current_credits > 0) AS active_warehouses,
        MAX_BY(warehouse_name, credit_delta) AS top_increase_warehouse,
        MAX(credit_delta) AS top_increase_credits
    FROM deltas
    """


def _loaded_cortex_state() -> tuple[float, int]:
    summary = st.session_state.get("cortex_control_summary")
    exceptions = st.session_state.get("cortex_control_exceptions")
    projected = 0.0
    if isinstance(summary, pd.DataFrame) and not summary.empty:
        projected = safe_float(summary.iloc[0].get("PROJECTED_30D_COST", 0))
    exception_count = len(exceptions) if isinstance(exceptions, pd.DataFrame) and not exceptions.empty else 0
    return projected, exception_count


def _render_cost_watch_floor(session, company: str, credit_price: float) -> None:
    st.subheader("Cost Control Cockpit")
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        days = st.selectbox("Cost cockpit window", [7, 14, 30], index=0, format_func=lambda d: f"{d} days")
    with c2:
        if st.button("Load Cost Cockpit", key="cost_contract_cockpit_load", type="primary"):
            try:
                st.session_state["cost_contract_cockpit"] = run_query(
                    _build_cost_cockpit_sql(company, int(days)),
                    ttl_key=f"cost_contract_cockpit_{company}_{days}",
                    tier="standard",
                    section="Cost & Contract",
                )
                st.session_state["cost_contract_cockpit_meta"] = {"company": company, "days": int(days)}
                st.session_state["cost_contract_cockpit_error"] = ""
            except Exception as exc:
                st.session_state["cost_contract_cockpit_error"] = format_snowflake_error(exc)
                st.session_state["cost_contract_cockpit"] = pd.DataFrame()
                st.session_state["cost_contract_queue"] = pd.DataFrame()
            try:
                st.session_state["cost_contract_queue"] = load_action_queue(session)
                st.session_state["cost_contract_queue_error"] = ""
            except Exception as exc:
                st.session_state["cost_contract_queue"] = pd.DataFrame()
                st.session_state["cost_contract_queue_error"] = format_snowflake_error(exc)
    with c3:
        st.info("Use this cockpit to decide whether to explain the bill, work the action queue, inspect Cortex spend, or log verified savings.")

    data = st.session_state.get("cost_contract_cockpit")
    meta = st.session_state.get("cost_contract_cockpit_meta", {})
    err = st.session_state.get("cost_contract_cockpit_error", "")
    if err:
        st.warning(f"Cost cockpit unavailable: {err}")
    if not isinstance(data, pd.DataFrame) or data.empty or meta.get("company") != company:
        st.caption("Load the cost cockpit for a fast first move. Specialist pages still load their own detailed data.")
        return

    row = data.iloc[0]
    queue = st.session_state.get("cost_contract_queue", pd.DataFrame())
    queue_err = st.session_state.get("cost_contract_queue_error", "")
    if queue_err:
        st.caption(f"Action queue unavailable for this role/context: {queue_err}")
    open_actions = high_actions = 0
    total_savings = 0.0
    if isinstance(queue, pd.DataFrame) and not queue.empty and "STATUS" in queue.columns:
        open_mask = ~queue["STATUS"].isin(["Fixed", "Ignored"])
        open_actions = int(open_mask.sum())
        high_actions = int((queue.get("SEVERITY", pd.Series(dtype=str)).isin(["Critical", "High"]) & open_mask).sum())
        if "EST_MONTHLY_SAVINGS" in queue.columns:
            total_savings = safe_float(pd.to_numeric(queue.loc[open_mask, "EST_MONTHLY_SAVINGS"], errors="coerce").fillna(0).sum())
    current_credits = safe_float(row.get("CURRENT_CREDITS", 0))
    prior_credits = safe_float(row.get("PRIOR_CREDITS", 0))
    delta_pct = ((current_credits - prior_credits) / prior_credits * 100) if prior_credits > 0 else 0.0
    cortex_projected, cortex_exception_count = _loaded_cortex_state()
    score = _cost_score(current_credits, prior_credits, open_actions, high_actions, cortex_exception_count)

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Cost Score", f"{score}/100", _cost_rating(score))
    k2.metric("Current Window", f"${credits_to_dollars(current_credits, credit_price):,.0f}", f"{delta_pct:+.1f}%", delta_color="inverse")
    k3.metric("Open Actions", f"{open_actions:,}", f"{high_actions:,} high", delta_color="inverse")
    k4.metric("Savings Queue", f"${total_savings:,.0f}/mo")
    k5.metric("Cortex Projection", f"${cortex_projected:,.0f}/30d", f"{cortex_exception_count:,} exceptions", delta_color="inverse")

    moves = []
    if delta_pct >= 20 or safe_float(row.get("TOP_INCREASE_CREDITS", 0)) > 0:
        moves.append((
            "Explain the bill movement",
            f"Top increase: {row.get('TOP_INCREASE_WAREHOUSE', 'unknown')} "
            f"({safe_float(row.get('TOP_INCREASE_CREDITS', 0)):,.2f} credits).",
            "Explain bill / attribution / contract",
        ))
    if high_actions > 0 or total_savings > 0:
        moves.append((
            "Work the action queue",
            f"{high_actions:,} high-priority action(s), ${total_savings:,.0f}/month potential savings.",
            "Recommendations and action queue",
        ))
    if cortex_exception_count > 0 or cortex_projected > 0:
        moves.append((
            "Inspect AI / Cortex spend",
            f"Projected Cortex spend ${cortex_projected:,.0f}/30d with {cortex_exception_count:,} exception(s).",
            "AI and Cortex spend",
        ))
    if not moves:
        moves.append((
            "Log value or review attribution",
            "No dominant cost incident in this cockpit window. Use value log for verified DBA wins or attribution for chargeback.",
            "Snowflake value log",
        ))

    st.markdown("**Next Cost Moves**")
    cols = st.columns(min(len(moves), 3))
    for idx, (title, evidence, workflow) in enumerate(moves[:3]):
        with cols[idx]:
            st.markdown(f"**{title}**")
            st.caption(evidence)
            if st.button(f"Open {workflow}", key=f"cost_contract_next_{idx}_{workflow}", use_container_width=True):
                st.session_state["cost_contract_workflow"] = workflow
                st.rerun()


def render() -> None:
    session = get_session()
    company = get_active_company()
    credit_price = safe_float(st.session_state.get("credit_price", 3.0)) or 3.0
    if st.session_state.get("exceptions_only_mode") and "cost_contract_workflow" not in st.session_state:
        st.session_state["cost_contract_workflow"] = "Explain bill / attribution / contract"
    st.header("Cost & Contract")
    st.caption(
        "One operating workflow for bill explanation, cost attribution, contract pacing, "
        "optimization actions, AI/Cortex usage, and Snowpark Container Services spend."
    )
    render_signal_confidence(
        source="ACCOUNT_USAGE",
        confidence="allocated",
        scope_note="Warehouse totals are exact; user/query chargeback is allocated unless noted.",
    )
    if st.session_state.get("exceptions_only_mode"):
        st.warning("Exceptions-only mode: prioritize bill deltas, open action queue items, and contract risk.")
    render_workflow_guide(
        "Explain the bill first, convert findings into owned actions, log validated savings, "
        "then inspect special-cost surfaces like Cortex and SPCS.",
        [
            ("Why did the bill move?", "Use Explain bill / attribution / contract."),
            ("What should we fix first?", "Use Recommendations and action queue."),
            ("How do we prove savings?", "Use Snowflake value log."),
            ("Are AI costs controlled?", "Use AI and Cortex spend."),
            ("Are container services costing us?", "Use SPCS spend."),
        ],
    )
    _render_cost_watch_floor(session, company, credit_price)

    workflow = render_workflow_selector(
        "Cost workflow",
        "cost_contract_workflow",
        WORKFLOWS,
        WORKFLOW_DETAILS,
    )

    if workflow == "Explain bill / attribution / contract":
        cost_center.render()
    elif workflow == "Recommendations and action queue":
        recommendations.render()
    elif workflow == "Snowflake value log":
        snowflake_value.render()
    elif workflow == "AI and Cortex spend":
        cortex_monitor.render()
    else:
        spcs_tracker.render()
