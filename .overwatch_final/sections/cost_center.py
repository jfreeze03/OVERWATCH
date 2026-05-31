# sections/cost_center.py — User leaderboard, burn rate, forecast, budget, attribution, chargeback
# FIX: Chargeback tab now uses get_company_case_expr() from company_filter.py
#      instead of the old hardcoded CASE that missed WH_ALFA_* warehouses.
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from utils.workflows import render_workflow_selector
from utils import (
    get_session, format_credits, credits_to_dollars,
    download_csv, build_metered_credit_cte, build_cost_reconciliation_sql,
    burn_trend_label,
    metric_confidence_label, freshness_note,
    get_wh_filter_clause, get_global_wh_filter_clause,
    get_global_filter_clause, get_company_case_expr,
    build_mart_bill_summary_sql, build_mart_bill_warehouse_delta_sql,
    filter_existing_columns,
    render_drillable_bar_chart, render_entity_query_drilldown, render_priority_dataframe,
    make_action_id, upsert_actions,
    run_query, sql_literal, format_snowflake_error,
    safe_float,
)


COST_CENTER_VIEWS = (
    "Explain This Bill",
    "User Leaderboard",
    "Burn Rate",
    "Reconciliation",
    "Forecast",
    "Budget vs Actual",
    "Attribution",
    "Chargeback",
    "Contract Utilization",
)

COST_CENTER_VIEW_DETAILS = {
    "Explain This Bill": "Narrative answer for why spend changed.",
    "User Leaderboard": "Top users and warehouses by allocated credits.",
    "Burn Rate": "Daily metered credit trend by warehouse.",
    "Reconciliation": "Metered credits vs query allocation.",
    "Forecast": "Near-term projected burn from recent usage.",
    "Budget vs Actual": "Monthly consumption against budget.",
    "Attribution": "Role, schema, client, and lineage cost views.",
    "Chargeback": "ALFA/Trexis company allocation output.",
    "Contract Utilization": "Committed-use utilization and risk.",
}


def _queue_cost_outliers(session, df: pd.DataFrame, credit_price: float, source: str) -> None:
    if df is None or df.empty:
        st.info("No cost outliers to queue.")
        return
    if "TOTAL_CREDITS" not in df.columns:
        if "ALLOCATED_CREDITS" in df.columns:
            df = df.copy()
            df["TOTAL_CREDITS"] = df["ALLOCATED_CREDITS"]
        else:
            st.info("No total-credit measure was available for cost outlier queueing.")
            return
    company = st.session_state.get("active_company", "ALFA")
    actions = []
    baseline = safe_float(df["TOTAL_CREDITS"].median()) if "TOTAL_CREDITS" in df.columns else 0
    candidates = df.sort_values("TOTAL_CREDITS", ascending=False).head(20)
    for _, row in candidates.iterrows():
        user = str(row.get("USER_NAME") or "Unknown user")
        wh = str(row.get("WAREHOUSE_NAME") or "Unknown warehouse")
        credits = safe_float(row.get("TOTAL_CREDITS", 0))
        est_cost = credits_to_dollars(credits, credit_price)
        if baseline > 0 and credits < baseline * 2 and est_cost < 500:
            continue
        entity = f"{user} on {wh}"
        monthly_savings = max(0.0, est_cost * 0.15)
        finding = f"{entity} consumed {credits:,.2f} credits (${est_cost:,.2f}) in the selected window"
        actions.append({
            "Action ID": make_action_id("Cost Outlier", entity, finding),
            "Source": source,
            "Severity": "Medium" if est_cost < 2500 else "High",
            "Category": "Cost",
            "Entity Type": "User/Warehouse",
            "Entity": entity,
            "Owner": user if user and user != "Unknown user" else "DBA",
            "Finding": finding,
            "Action": "Review query patterns, warehouse sizing, cache use, and whether the workload can be optimized or scheduled differently.",
            "Estimated Monthly Savings": round(monthly_savings, 2),
            "Generated SQL Fix": "-- Use Cost & Contract drilldown to identify top query patterns before applying warehouse/query changes.",
            "Proof Query": "Cost & Contract metered credit attribution query.",
            "Company": company,
        })
    if not actions:
        st.success("No cost outliers crossed the queue threshold.")
        return
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} cost outliers to the action queue.")
    except Exception as e:
        st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
        st.info("Deploy the Action Queue table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry this save.")


def _annotate_cost_routes(df: pd.DataFrame, finding_type: str) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    routed = df.copy()
    if finding_type == "Warehouse Delta":
        routed["NEXT_WORKFLOW"] = "Explain bill / attribution / contract"
        routed["NEXT_ACTION"] = (
            "Drill into the warehouse delta, separate workload growth from idle/service overhead, "
            "then validate top users and query types before resizing."
        )
    elif finding_type == "User Cost":
        routed["NEXT_WORKFLOW"] = "Query workbench"
        routed["NEXT_ACTION"] = (
            "Open the user drilldown, identify repeat query signatures, and confirm whether the workload can be optimized or scheduled."
        )
    elif finding_type == "Chargeback":
        routed["NEXT_WORKFLOW"] = "Cost & Contract"
        routed["NEXT_ACTION"] = (
            "Validate company scope, warehouse ownership, and allocation confidence before sending the chargeback report."
        )
    elif finding_type == "Service Cost":
        routed["NEXT_WORKFLOW"] = "Cost & Contract"
        routed["NEXT_ACTION"] = (
            "Treat as account-wide unless owner tags or service lineage prove attribution; review service-specific usage before chargeback."
        )
    else:
        routed["NEXT_WORKFLOW"] = "Cost & Contract"
        routed["NEXT_ACTION"] = "Validate confidence level, owner, and proof query before taking a cost-control action."
    return routed


def _bill_period_bounds(period_key: str) -> dict:
    periods = {
        "Last complete day": {
            "label": "last complete day",
            "current_start": "TO_TIMESTAMP_NTZ(DATEADD('day', -1, CURRENT_DATE()))",
            "current_end": "TO_TIMESTAMP_NTZ(CURRENT_DATE())",
            "prior_start": "TO_TIMESTAMP_NTZ(DATEADD('day', -2, CURRENT_DATE()))",
            "prior_end": "TO_TIMESTAMP_NTZ(DATEADD('day', -1, CURRENT_DATE()))",
            "days_back": 4,
        },
        "Last 7 complete days": {
            "label": "last 7 complete days",
            "current_start": "TO_TIMESTAMP_NTZ(DATEADD('day', -7, CURRENT_DATE()))",
            "current_end": "TO_TIMESTAMP_NTZ(CURRENT_DATE())",
            "prior_start": "TO_TIMESTAMP_NTZ(DATEADD('day', -14, CURRENT_DATE()))",
            "prior_end": "TO_TIMESTAMP_NTZ(DATEADD('day', -7, CURRENT_DATE()))",
            "days_back": 17,
        },
        "Last 30 complete days": {
            "label": "last 30 complete days",
            "current_start": "TO_TIMESTAMP_NTZ(DATEADD('day', -30, CURRENT_DATE()))",
            "current_end": "TO_TIMESTAMP_NTZ(CURRENT_DATE())",
            "prior_start": "TO_TIMESTAMP_NTZ(DATEADD('day', -60, CURRENT_DATE()))",
            "prior_end": "TO_TIMESTAMP_NTZ(DATEADD('day', -30, CURRENT_DATE()))",
            "days_back": 65,
        },
        "Current month to date": {
            "label": "current month to date",
            "current_start": "TO_TIMESTAMP_NTZ(DATE_TRUNC('month', CURRENT_DATE()))",
            "current_end": "TO_TIMESTAMP_NTZ(CURRENT_DATE())",
            "prior_start": "TO_TIMESTAMP_NTZ(DATEADD('month', -1, DATE_TRUNC('month', CURRENT_DATE())))",
            "prior_end": "TO_TIMESTAMP_NTZ(DATEADD('month', -1, CURRENT_DATE()))",
            "days_back": 65,
        },
        "Previous month": {
            "label": "previous month",
            "current_start": "TO_TIMESTAMP_NTZ(DATEADD('month', -1, DATE_TRUNC('month', CURRENT_DATE())))",
            "current_end": "TO_TIMESTAMP_NTZ(DATE_TRUNC('month', CURRENT_DATE()))",
            "prior_start": "TO_TIMESTAMP_NTZ(DATEADD('month', -2, DATE_TRUNC('month', CURRENT_DATE())))",
            "prior_end": "TO_TIMESTAMP_NTZ(DATEADD('month', -1, DATE_TRUNC('month', CURRENT_DATE())))",
            "days_back": 95,
        },
    }
    return periods.get(period_key, periods["Last 7 complete days"])


def _pct_delta(current: float, prior: float):
    if prior is None or abs(float(prior)) < 0.000001:
        return None
    return ((float(current or 0) - float(prior or 0)) / float(prior)) * 100


def _fmt_delta(value) -> str:
    if value is None:
        return "new/no baseline"
    return f"{value:+.1f}%"


def _first_value(df: pd.DataFrame, column: str, default=0.0):
    if df is None or df.empty or column not in df.columns:
        return default
    return df.iloc[0].get(column, default)


def _bill_driver_summary(
    *,
    delta_credits: float,
    current_credits: float,
    prior_credits: float,
    unallocated_pct: float,
    warehouse_deltas: pd.DataFrame,
    user_drivers: pd.DataFrame,
    query_type_drivers: pd.DataFrame,
) -> dict:
    """Build an executive-ready explanation from exact and allocated bill signals."""
    top_wh = warehouse_deltas.iloc[0].to_dict() if warehouse_deltas is not None and not warehouse_deltas.empty else {}
    top_user = user_drivers.iloc[0].to_dict() if user_drivers is not None and not user_drivers.empty else {}
    top_type = query_type_drivers.iloc[0].to_dict() if query_type_drivers is not None and not query_type_drivers.empty else {}
    delta_pct = _pct_delta(current_credits, prior_credits)

    if abs(delta_credits) < 0.01:
        headline = "Spend was essentially flat."
        reason = "No material credit movement was detected compared with the prior comparable period."
        severity = "Normal"
    elif delta_credits > 0:
        headline = f"Spend increased by {delta_credits:,.2f} credits ({_fmt_delta(delta_pct)})."
        reason = (
            f"The largest warehouse movement was {top_wh.get('WAREHOUSE_NAME', 'n/a')} "
            f"at {safe_float(top_wh.get('CREDIT_DELTA', 0)):,.2f} incremental credits. "
            f"The largest allocated workload was {top_user.get('USER_NAME', 'n/a')} on "
            f"{top_user.get('WAREHOUSE_NAME', 'n/a')}."
        )
        severity = "High" if delta_pct is not None and delta_pct >= 50 else "Watch"
    else:
        headline = f"Spend decreased by {abs(delta_credits):,.2f} credits ({_fmt_delta(delta_pct)})."
        reason = (
            f"The largest downward warehouse movement was {top_wh.get('WAREHOUSE_NAME', 'n/a')} "
            f"at {safe_float(top_wh.get('CREDIT_DELTA', 0)):,.2f} credits."
        )
        severity = "Improved"

    if unallocated_pct >= 25:
        caveat = "A large unallocated gap means idle time, non-query activity, or ACCOUNT_USAGE latency may be driving the bill."
    elif unallocated_pct >= 10:
        caveat = "Some spend is not cleanly attributable to user queries; review idle and service overhead before chargeback."
    else:
        caveat = "Most warehouse spend is attributable to query workload in this window."

    next_action = (
        f"Start with {top_wh.get('WAREHOUSE_NAME', 'the top warehouse')} and validate "
        f"{top_type.get('QUERY_TYPE', 'the top query type')} activity in Query Workbench before changing warehouse settings."
    )
    return {
        "severity": severity,
        "headline": headline,
        "reason": reason,
        "caveat": caveat,
        "next_action": next_action,
    }


def _build_bill_waterfall(
    warehouse_deltas: pd.DataFrame,
    *,
    prior_credits: float,
    current_credits: float,
    credit_price: float,
    top_n: int = 6,
) -> pd.DataFrame:
    """Build a compact bill-movement waterfall from warehouse credit deltas."""
    rows = [{
        "Driver": "Prior baseline",
        "Credits": round(float(prior_credits or 0), 4),
        "Estimated Cost": round(credits_to_dollars(prior_credits, credit_price), 2),
        "Type": "Baseline",
    }]
    delta_total = float(current_credits or 0) - float(prior_credits or 0)
    selected_delta = 0.0
    if warehouse_deltas is not None and not warehouse_deltas.empty and "CREDIT_DELTA" in warehouse_deltas.columns:
        movers = warehouse_deltas.copy()
        movers["ABS_DELTA"] = movers["CREDIT_DELTA"].fillna(0).abs()
        movers = movers.sort_values("ABS_DELTA", ascending=False).head(top_n)
        for _, row in movers.iterrows():
            delta = safe_float(row.get("CREDIT_DELTA", 0))
            if abs(delta) < 0.0001:
                continue
            selected_delta += delta
            label = str(row.get("WAREHOUSE_NAME") or "Unknown warehouse")
            rows.append({
                "Driver": label[:60],
                "Credits": round(delta, 4),
                "Estimated Cost": round(credits_to_dollars(delta, credit_price), 2),
                "Type": "Increase" if delta > 0 else "Decrease",
            })
    other_delta = delta_total - selected_delta
    if abs(other_delta) >= 0.0001:
        rows.append({
            "Driver": "Other movement",
            "Credits": round(other_delta, 4),
            "Estimated Cost": round(credits_to_dollars(other_delta, credit_price), 2),
            "Type": "Increase" if other_delta > 0 else "Decrease",
        })
    rows.append({
        "Driver": "Current total",
        "Credits": round(float(current_credits or 0), 4),
        "Estimated Cost": round(credits_to_dollars(current_credits, credit_price), 2),
        "Type": "Current",
    })
    return pd.DataFrame(rows)


def _service_cost_category(service_type: str) -> str:
    """Group Snowflake METERING_HISTORY service types into readable bill buckets."""
    value = str(service_type or "UNKNOWN").upper()
    if "CORTEX" in value or "AI" in value or "LLM" in value:
        return "AI / Cortex"
    if "SNOWPIPE" in value or "PIPE" in value or "INGEST" in value:
        return "Data loading / ingestion"
    if (
        "AUTO_CLUSTER" in value
        or "SEARCH_OPTIMIZATION" in value
        or "MATERIALIZED_VIEW" in value
        or "DYNAMIC_TABLE" in value
        or "SERVERLESS" in value
        or "TASK" in value
        or "REPLICATION" in value
    ):
        return "Serverless features"
    if "CLOUD_SERVICES" in value or "CLOUD SERVICE" in value:
        return "Cloud services / metadata"
    if "WAREHOUSE" in value or "COMPUTE" in value:
        return "Warehouse compute"
    return "Other service credits"


def _service_period_totals(service_drivers: pd.DataFrame) -> pd.DataFrame:
    if service_drivers is None or service_drivers.empty:
        return pd.DataFrame(columns=["CATEGORY", "CURRENT_CREDITS", "PRIOR_CREDITS", "DELTA_CREDITS"])
    required = {"PERIOD", "SERVICE_TYPE", "CREDITS"}
    if not required.issubset(set(service_drivers.columns)):
        return pd.DataFrame(columns=["CATEGORY", "CURRENT_CREDITS", "PRIOR_CREDITS", "DELTA_CREDITS"])
    svc = service_drivers.copy()
    svc["CATEGORY"] = svc["SERVICE_TYPE"].apply(_service_cost_category)
    pivot = (
        svc.pivot_table(
            index="CATEGORY",
            columns="PERIOD",
            values="CREDITS",
            aggfunc="sum",
            fill_value=0.0,
        )
        .reset_index()
        .rename_axis(None, axis=1)
    )
    for column in ("CURRENT", "PRIOR"):
        if column not in pivot.columns:
            pivot[column] = 0.0
    pivot["CURRENT_CREDITS"] = pivot["CURRENT"].apply(safe_float)
    pivot["PRIOR_CREDITS"] = pivot["PRIOR"].apply(safe_float)
    pivot["DELTA_CREDITS"] = pivot["CURRENT_CREDITS"] - pivot["PRIOR_CREDITS"]
    return pivot[["CATEGORY", "CURRENT_CREDITS", "PRIOR_CREDITS", "DELTA_CREDITS"]].sort_values(
        "CURRENT_CREDITS", ascending=False
    )


def _build_finance_movement_summary(
    *,
    current_credits: float,
    prior_credits: float,
    allocated_credits: float,
    unallocated_credits: float,
    service_drivers: pd.DataFrame,
    credit_price: float,
    budget: float = 0.0,
) -> pd.DataFrame:
    """Build a concise finance-facing movement bridge with confidence labels."""
    current_credits = safe_float(current_credits)
    prior_credits = safe_float(prior_credits)
    allocated_credits = safe_float(allocated_credits)
    unallocated_credits = safe_float(unallocated_credits)
    credit_price = safe_float(credit_price)
    rows = [
        {
            "Category": "Warehouse metering",
            "Basis": "Exact warehouse compute from WAREHOUSE_METERING_HISTORY",
            "Current Credits": round(current_credits, 4),
            "Prior Credits": round(prior_credits, 4),
            "Delta Credits": round(current_credits - prior_credits, 4),
            "Current Cost": round(credits_to_dollars(current_credits, credit_price), 2),
            "Delta Cost": round(credits_to_dollars(current_credits - prior_credits, credit_price), 2),
            "Confidence": "Exact",
            "Action": "Use this as the official warehouse-compute bill movement.",
        },
        {
            "Category": "Query-attributed workload",
            "Basis": "Allocated by query execution share inside each warehouse-hour",
            "Current Credits": round(allocated_credits, 4),
            "Prior Credits": None,
            "Delta Credits": None,
            "Current Cost": round(credits_to_dollars(allocated_credits, credit_price), 2),
            "Delta Cost": None,
            "Confidence": "Allocated",
            "Action": "Use for directional user, role, database, and query-type chargeback.",
        },
        {
            "Category": "Unallocated / idle / overhead",
            "Basis": "Exact warehouse credits minus allocated query credits",
            "Current Credits": round(unallocated_credits, 4),
            "Prior Credits": None,
            "Delta Credits": None,
            "Current Cost": round(credits_to_dollars(unallocated_credits, credit_price), 2),
            "Delta Cost": None,
            "Confidence": "Estimated",
            "Action": "Review auto-suspend, idle periods, non-query activity, and ACCOUNT_USAGE latency.",
        },
    ]
    service_totals = _service_period_totals(service_drivers)
    for _, row in service_totals.iterrows():
        current = safe_float(row.get("CURRENT_CREDITS", 0))
        prior = safe_float(row.get("PRIOR_CREDITS", 0))
        delta = safe_float(row.get("DELTA_CREDITS", 0))
        if abs(current) < 0.0001 and abs(prior) < 0.0001:
            continue
        rows.append({
            "Category": str(row.get("CATEGORY") or "Other service credits"),
            "Basis": "Account-wide METERING_HISTORY service credits",
            "Current Credits": round(current, 4),
            "Prior Credits": round(prior, 4),
            "Delta Credits": round(delta, 4),
            "Current Cost": round(credits_to_dollars(current, credit_price), 2),
            "Delta Cost": round(credits_to_dollars(delta, credit_price), 2),
            "Confidence": "Account-wide",
            "Action": "Do not charge back to ALFA/Trexis unless a service-specific owner tag or lineage exists.",
        })
    if budget and budget > 0:
        current_cost = credits_to_dollars(current_credits, credit_price)
        rows.append({
            "Category": "Budget variance",
            "Basis": "Configured budget minus current warehouse-compute cost",
            "Current Credits": None,
            "Prior Credits": None,
            "Delta Credits": None,
            "Current Cost": round(current_cost, 2),
            "Delta Cost": round(current_cost - safe_float(budget), 2),
            "Confidence": "Estimated",
            "Action": "Escalate if variance is positive and supported by a repeating workload driver.",
        })
    return pd.DataFrame(rows)


def _build_explain_bill_markdown(
    *,
    company: str,
    period_label: str,
    current_credits: float,
    prior_credits: float,
    credit_price: float,
    active_warehouses: int,
    allocated_credits: float,
    unallocated_credits: float,
    warehouse_deltas: pd.DataFrame,
    user_drivers: pd.DataFrame,
    query_type_drivers: pd.DataFrame,
    service_drivers: pd.DataFrame = None,
) -> str:
    def _driver_credits(row, default=0.0) -> float:
        if hasattr(row, "get"):
            return safe_float(row.get("ALLOCATED_CREDITS", row.get("TOTAL_CREDITS", default)))
        return safe_float(default)

    delta_credits = current_credits - prior_credits
    delta_pct = _pct_delta(current_credits, prior_credits)
    direction = "increased" if delta_credits > 0 else "decreased" if delta_credits < 0 else "held flat"
    top_wh = warehouse_deltas.iloc[0] if warehouse_deltas is not None and not warehouse_deltas.empty else {}
    top_user = user_drivers.iloc[0] if user_drivers is not None and not user_drivers.empty else {}
    top_type = query_type_drivers.iloc[0] if query_type_drivers is not None and not query_type_drivers.empty else {}
    service_totals = _service_period_totals(service_drivers)
    service_lines = []
    if service_totals is not None and not service_totals.empty:
        for _, row in service_totals.head(5).iterrows():
            service_lines.append(
                f"- {row.get('CATEGORY')}: {safe_float(row.get('CURRENT_CREDITS', 0)):,.2f} current credits "
                f"({safe_float(row.get('DELTA_CREDITS', 0)):+,.2f} vs baseline)."
            )

    lines = [
        f"# Explain This Bill - {company}",
        "",
        f"Period reviewed: {period_label}.",
        f"Warehouse-metered credits {direction} by {delta_credits:+,.2f} credits ({_fmt_delta(delta_pct)}), from {prior_credits:,.2f} to {current_credits:,.2f}.",
        f"Estimated current-period warehouse cost is ${credits_to_dollars(current_credits, credit_price):,.2f} at ${credit_price:,.2f}/credit.",
        f"Active warehouses in the period: {active_warehouses}.",
        "",
        "## Primary Drivers",
        f"- Largest warehouse delta: {top_wh.get('WAREHOUSE_NAME', 'n/a')} ({safe_float(top_wh.get('CREDIT_DELTA', 0)):,.2f} credit delta).",
        f"- Largest allocated user/workload: {top_user.get('USER_NAME', 'n/a')} on {top_user.get('WAREHOUSE_NAME', 'n/a')} ({_driver_credits(top_user):,.2f} allocated credits).",
        f"- Top query type by allocated credits: {top_type.get('QUERY_TYPE', 'n/a')} ({_driver_credits(top_type):,.2f} allocated credits).",
        "",
        "## Allocation Caveat",
        f"Exact warehouse credits: {current_credits:,.2f}. Query-attributed credits: {allocated_credits:,.2f}. Unallocated / idle / service-overhead gap: {unallocated_credits:,.2f} credits.",
        "Warehouse totals are exact ACCOUNT_USAGE metering. User and query-type drivers are allocated from hourly metering by query execution share, so they are directional rather than invoice-grade.",
        "",
        "## Account-Wide Service Credits",
        *(service_lines or ["- No service/serverless credit rows were available for this period."]),
        "Service credits are account-wide unless Snowflake exposes a service-specific owner dimension or your account uses reliable owner tags.",
        "",
        "## Recommended Follow-Up",
        "- Review warehouses with the largest positive deltas first.",
        "- Drill into the top user/workload and query type before resizing warehouses.",
        "- If the unallocated gap is material, review auto-suspend settings, non-query warehouse activity, and ACCOUNT_USAGE latency.",
    ]
    return "\n".join(lines)


def _queue_bill_exceptions(
    session,
    warehouse_deltas: pd.DataFrame,
    credit_price: float,
    period_label: str,
) -> None:
    if warehouse_deltas is None or warehouse_deltas.empty:
        st.info("No bill exceptions to queue.")
        return
    company = st.session_state.get("active_company", "ALFA")
    actions = []
    for _, row in warehouse_deltas.sort_values("CREDIT_DELTA", ascending=False).head(10).iterrows():
        wh = str(row.get("WAREHOUSE_NAME") or "Unknown warehouse")
        delta = safe_float(row.get("CREDIT_DELTA", 0))
        if delta <= 0:
            continue
        est_delta_cost = credits_to_dollars(delta, credit_price)
        if delta < 5 and est_delta_cost < 100:
            continue
        finding = f"{wh} increased by {delta:,.2f} credits (${est_delta_cost:,.2f}) during {period_label}"
        actions.append({
            "Action ID": make_action_id("Bill Increase", wh, finding),
            "Source": "Cost & Contract - Explain This Bill",
            "Severity": "Medium" if est_delta_cost < 1000 else "High",
            "Category": "Cost",
            "Entity Type": "Warehouse",
            "Entity": wh,
            "Owner": "DBA",
            "Finding": finding,
            "Action": "Use Cost & Contract and Query Workbench drilldowns to confirm whether the increase is workload growth, idle time, warehouse sizing, or a one-time event.",
            "Estimated Monthly Savings": round(max(0.0, est_delta_cost * 0.25), 2),
            "Generated SQL Fix": "-- Review warehouse auto-suspend, scaling policy, and top query drivers before making changes.",
            "Proof Query": "Cost & Contract Explain This Bill warehouse-delta query.",
            "Company": company,
        })
    if not actions:
        st.success("No warehouse increases crossed the exception threshold.")
        return
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} bill exceptions to the action queue.")
    except Exception as e:
        st.error(f"Could not save bill exceptions: {format_snowflake_error(e)}")


def render():
    session = get_session()
    credit_price = st.session_state.get("credit_price", 3.00)
    company = st.session_state.get("active_company", "ALFA")
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        ["WAREHOUSE_SIZE", "BYTES_SCANNED", "QUERY_TAG"],
    ))
    max_wh_size_expr = (
        "MAX(q.warehouse_size)"
        if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR"
    )
    wh_size_plain_expr = (
        "warehouse_size"
        if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"
    )
    bytes_scanned_sum_expr = (
        "SUM(q.bytes_scanned)"
        if "BYTES_SCANNED" in qh_cols else "0"
    )
    query_tag_dimension_expr = (
        "COALESCE(q.query_tag, 'UNTAGGED')"
        if "QUERY_TAG" in qh_cols else "'UNTAGGED'"
    )

    cost_view = render_workflow_selector(
        "Cost Center workflow",
        "cost_center_view",
        COST_CENTER_VIEWS,
        COST_CENTER_VIEW_DETAILS,
        columns=3,
    )
    st.caption(
        "Progressive load is enabled: each cost view runs only when its Load or Calculate button is selected."
    )

    # ── USER LEADERBOARD ──────────────────────────────────────────────────────
    if cost_view == "Explain This Bill":
        st.header("Explain This Bill")
        st.caption(
            "Start here when someone asks why Snowflake spend moved. "
            "Warehouse totals use exact ACCOUNT_USAGE metering; user and query drivers are allocated estimates."
        )
        explain_period = st.selectbox(
            "Bill period",
            [
                "Last complete day",
                "Last 7 complete days",
                "Last 30 complete days",
                "Current month to date",
                "Previous month",
            ],
            index=1,
            key="cc_explain_period",
        )
        explain_budget = st.number_input(
            "Optional budget for this period ($)",
            min_value=0.0,
            value=0.0,
            step=100.0,
            key="cc_explain_budget",
        )
        bounds = _bill_period_bounds(explain_period)
        use_mart_summary = not any([
            st.session_state.get("global_user"),
            st.session_state.get("global_role"),
            st.session_state.get("global_database"),
        ])
        warehouse_contains = str(st.session_state.get("global_warehouse") or "").strip()
        wh_filter_meter = " ".join(filter(None, [
            get_wh_filter_clause("warehouse_name"),
            get_global_wh_filter_clause("warehouse_name"),
        ]))
        wh_filter_query = get_global_filter_clause(
            "",
            "q.warehouse_name",
            "q.user_name",
            "q.role_name",
            "q.database_name",
        )
        attribution_only_filters = [
            name for name, value in {
                "user": st.session_state.get("global_user"),
                "role": st.session_state.get("global_role"),
                "database": st.session_state.get("global_database"),
            }.items()
            if value
        ]
        if attribution_only_filters:
            st.warning(
                "User, role, and database filters narrow attribution rows only. "
                "Exact warehouse metering can be scoped only by company and warehouse."
            )
        explain_filter_signature = (
            st.session_state.get("global_warehouse"),
            st.session_state.get("global_user"),
            st.session_state.get("global_role"),
            st.session_state.get("global_database"),
        )

        if st.button("Explain Bill", key="cc_explain_load", type="primary"):
            try:
                live_summary_sql = f"""
                WITH bounds AS (
                    SELECT
                        {bounds['current_start']} AS current_start,
                        {bounds['current_end']} AS current_end,
                        {bounds['prior_start']} AS prior_start,
                        {bounds['prior_end']} AS prior_end
                ),
                metering AS (
                    SELECT 'CURRENT' AS period, warehouse_name, start_time, credits_used
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY, bounds
                    WHERE start_time >= current_start
                      AND start_time < current_end
                      {wh_filter_meter}
                    UNION ALL
                    SELECT 'PRIOR' AS period, warehouse_name, start_time, credits_used
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY, bounds
                    WHERE start_time >= prior_start
                      AND start_time < prior_end
                      {wh_filter_meter}
                )
                SELECT
                    period,
                    ROUND(SUM(credits_used), 4) AS credits,
                    COUNT(DISTINCT warehouse_name) AS active_warehouses,
                    COUNT(DISTINCT TO_DATE(start_time)) AS active_days
                FROM metering
                GROUP BY period
                """
                live_wh_delta_sql = f"""
                WITH bounds AS (
                    SELECT
                        {bounds['current_start']} AS current_start,
                        {bounds['current_end']} AS current_end,
                        {bounds['prior_start']} AS prior_start,
                        {bounds['prior_end']} AS prior_end
                ),
                current_wh AS (
                    SELECT warehouse_name, SUM(credits_used) AS credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY, bounds
                    WHERE start_time >= current_start
                      AND start_time < current_end
                      {wh_filter_meter}
                    GROUP BY warehouse_name
                ),
                prior_wh AS (
                    SELECT warehouse_name, SUM(credits_used) AS credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY, bounds
                    WHERE start_time >= prior_start
                      AND start_time < prior_end
                      {wh_filter_meter}
                    GROUP BY warehouse_name
                )
                SELECT
                    COALESCE(c.warehouse_name, p.warehouse_name) AS warehouse_name,
                    ROUND(COALESCE(c.credits, 0), 4) AS current_credits,
                    ROUND(COALESCE(p.credits, 0), 4) AS prior_credits,
                    ROUND(COALESCE(c.credits, 0) - COALESCE(p.credits, 0), 4) AS credit_delta,
                    CASE
                        WHEN COALESCE(p.credits, 0) = 0 THEN NULL
                        ELSE ROUND(((COALESCE(c.credits, 0) - p.credits) / NULLIF(p.credits, 0)) * 100, 2)
                    END AS pct_delta
                FROM current_wh c
                FULL OUTER JOIN prior_wh p ON c.warehouse_name = p.warehouse_name
                ORDER BY ABS(COALESCE(c.credits, 0) - COALESCE(p.credits, 0)) DESC
                LIMIT 25
                """
                if use_mart_summary:
                    summary_sql = build_mart_bill_summary_sql(
                        bounds["current_start"],
                        bounds["current_end"],
                        bounds["prior_start"],
                        bounds["prior_end"],
                        company=company,
                        warehouse_contains=warehouse_contains,
                    )
                    wh_delta_sql = build_mart_bill_warehouse_delta_sql(
                        bounds["current_start"],
                        bounds["current_end"],
                        bounds["prior_start"],
                        bounds["prior_end"],
                        company=company,
                        warehouse_contains=warehouse_contains,
                    )
                    bill_summary_source = "OVERWATCH mart: FACT_WAREHOUSE_HOURLY"
                else:
                    summary_sql = live_summary_sql
                    wh_delta_sql = live_wh_delta_sql
                    bill_summary_source = "Live fallback: WAREHOUSE_METERING_HISTORY"
                driver_sql = f"""
                WITH bounds AS (
                    SELECT
                        {bounds['current_start']} AS current_start,
                        {bounds['current_end']} AS current_end
                ),
                {build_metered_credit_cte(days_back=bounds['days_back'], include_recent=False)}
                SELECT
                    q.user_name,
                    q.role_name,
                    q.warehouse_name,
                    {max_wh_size_expr} AS warehouse_size,
                    COUNT(*) AS query_count,
                    ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS total_credits,
                    ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS allocated_credits,
                    ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_execution_seconds,
                    ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
                    ROUND({bytes_scanned_sum_expr} / POWER(1024, 3), 2) AS gb_scanned
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                CROSS JOIN bounds
                WHERE q.start_time >= current_start
                  AND q.start_time < current_end
                  AND q.warehouse_name IS NOT NULL
                  {wh_filter_query}
                GROUP BY q.user_name, q.role_name, q.warehouse_name
                ORDER BY allocated_credits DESC
                LIMIT 50
                """
                type_sql = f"""
                WITH bounds AS (
                    SELECT
                        {bounds['current_start']} AS current_start,
                        {bounds['current_end']} AS current_end
                ),
                {build_metered_credit_cte(days_back=bounds['days_back'], include_recent=False)}
                SELECT
                    COALESCE(q.query_type, 'UNKNOWN') AS query_type,
                    COUNT(*) AS query_count,
                    ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS total_credits,
                    ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS allocated_credits,
                    ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_execution_seconds,
                    ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
                    ROUND({bytes_scanned_sum_expr} / POWER(1024, 3), 2) AS gb_scanned
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                CROSS JOIN bounds
                WHERE q.start_time >= current_start
                  AND q.start_time < current_end
                  AND q.warehouse_name IS NOT NULL
                  {wh_filter_query}
                GROUP BY COALESCE(q.query_type, 'UNKNOWN')
                ORDER BY allocated_credits DESC
                LIMIT 25
                """
                service_sql = f"""
                WITH bounds AS (
                    SELECT
                        {bounds['current_start']} AS current_start,
                        {bounds['current_end']} AS current_end,
                        {bounds['prior_start']} AS prior_start,
                        {bounds['prior_end']} AS prior_end
                ),
                metering AS (
                    SELECT 'CURRENT' AS period, service_type, start_time, credits_used
                    FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY, bounds
                    WHERE start_time >= current_start
                      AND start_time < current_end
                    UNION ALL
                    SELECT 'PRIOR' AS period, service_type, start_time, credits_used
                    FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY, bounds
                    WHERE start_time >= prior_start
                      AND start_time < prior_end
                )
                SELECT
                    period,
                    COALESCE(service_type, 'UNKNOWN') AS service_type,
                    ROUND(SUM(COALESCE(credits_used, 0)), 4) AS credits
                FROM metering
                GROUP BY period, COALESCE(service_type, 'UNKNOWN')
                ORDER BY period, credits DESC
                """
                st.session_state["cc_explain_summary"] = run_query(
                    summary_sql,
                    ttl_key=f"cc_explain_summary_{company}_{explain_period}_{'mart' if use_mart_summary else 'live'}",
                    tier="standard",
                )
                if use_mart_summary and st.session_state["cc_explain_summary"].empty:
                    bill_summary_source = "Live fallback: mart unavailable or stale"
                    st.session_state["cc_explain_summary"] = run_query(
                        live_summary_sql,
                        ttl_key=f"cc_explain_summary_{company}_{explain_period}_fallback",
                        tier="standard",
                    )
                st.session_state["cc_explain_wh_delta"] = run_query(
                    wh_delta_sql,
                    ttl_key=f"cc_explain_wh_{company}_{explain_period}_{'mart' if use_mart_summary else 'live'}",
                    tier="standard",
                )
                if use_mart_summary and st.session_state["cc_explain_wh_delta"].empty:
                    st.session_state["cc_explain_wh_delta"] = run_query(
                        live_wh_delta_sql,
                        ttl_key=f"cc_explain_wh_{company}_{explain_period}_fallback",
                        tier="standard",
                    )
                st.session_state["cc_explain_drivers"] = run_query(
                    driver_sql,
                    ttl_key=f"cc_explain_drivers_{company}_{explain_period}",
                    tier="standard",
                )
                st.session_state["cc_explain_types"] = run_query(
                    type_sql,
                    ttl_key=f"cc_explain_types_{company}_{explain_period}",
                    tier="standard",
                )
                try:
                    st.session_state["cc_explain_services"] = run_query(
                        service_sql,
                        ttl_key=f"cc_explain_services_{explain_period}",
                        tier="standard",
                    )
                    st.session_state["cc_explain_service_error"] = ""
                except Exception as service_error:
                    st.session_state["cc_explain_services"] = pd.DataFrame()
                    st.session_state["cc_explain_service_error"] = format_snowflake_error(service_error)
                st.session_state["cc_explain_meta"] = {
                    "company": company,
                    "period": explain_period,
                    "credit_price": credit_price,
                    "filters": explain_filter_signature,
                    "summary_source": bill_summary_source,
                }
            except Exception as e:
                st.error(f"Unable to explain bill: {format_snowflake_error(e)}")

        summary = st.session_state.get("cc_explain_summary")
        wh_deltas = st.session_state.get("cc_explain_wh_delta")
        drivers = st.session_state.get("cc_explain_drivers")
        type_drivers = st.session_state.get("cc_explain_types")
        service_drivers = st.session_state.get("cc_explain_services")
        service_error = st.session_state.get("cc_explain_service_error", "")
        explain_meta = st.session_state.get("cc_explain_meta", {})
        has_current_explain = (
            explain_meta.get("company") == company
            and explain_meta.get("period") == explain_period
            and explain_meta.get("filters") == explain_filter_signature
            and summary is not None
            and not summary.empty
        )
        if has_current_explain:
            current_row = summary[summary["PERIOD"] == "CURRENT"]
            prior_row = summary[summary["PERIOD"] == "PRIOR"]
            current_credits = safe_float(_first_value(current_row, "CREDITS", 0))
            prior_credits = safe_float(_first_value(prior_row, "CREDITS", 0))
            current_cost = credits_to_dollars(current_credits, credit_price)
            prior_cost = credits_to_dollars(prior_credits, credit_price)
            delta_credits = current_credits - prior_credits
            delta_cost = current_cost - prior_cost
            delta_pct = _pct_delta(current_credits, prior_credits)
            active_warehouses = int(_first_value(current_row, "ACTIVE_WAREHOUSES", 0) or 0)
            allocated_credits = (
                safe_float(drivers["ALLOCATED_CREDITS"].sum())
                if drivers is not None and not drivers.empty else 0.0
            )
            unallocated_credits = max(0.0, current_credits - allocated_credits)
            unallocated_pct = (unallocated_credits / current_credits * 100) if current_credits else 0.0

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Current Spend", f"${current_cost:,.2f}", f"{delta_cost:+,.2f}")
            c2.metric("Current Credits", format_credits(current_credits), f"{delta_credits:+,.2f}")
            c3.metric("Change vs Baseline", _fmt_delta(delta_pct))
            c4.metric("Active Warehouses", active_warehouses)
            if explain_budget > 0:
                budget_delta = current_cost - explain_budget
                st.metric(
                    "Budget Variance",
                    f"${budget_delta:+,.2f}",
                    "over budget" if budget_delta > 0 else "under budget",
                )

            st.caption(
                f"{metric_confidence_label('exact')} for warehouse totals | "
                f"{metric_confidence_label('allocated')} for user/query attribution | "
                f"{explain_meta.get('summary_source', 'Live fallback: WAREHOUSE_METERING_HISTORY')} | "
                f"{freshness_note('ACCOUNT_USAGE')}"
            )

            if delta_credits > 0:
                st.warning(
                    f"Spend increased by {delta_credits:,.2f} credits "
                    f"(${delta_cost:,.2f}) compared with the prior comparable period."
                )
            elif delta_credits < 0:
                st.success(
                    f"Spend decreased by {abs(delta_credits):,.2f} credits "
                    f"(${abs(delta_cost):,.2f}) compared with the prior comparable period."
                )
            else:
                st.info("Spend held flat versus the prior comparable period.")

            gap_level = "material" if unallocated_pct >= 20 else "moderate" if unallocated_pct >= 10 else "low"
            st.info(
                f"Unallocated / idle / service-overhead gap is {unallocated_credits:,.2f} credits "
                f"({unallocated_pct:.1f}% of exact warehouse credits), which is {gap_level}."
            )
            if service_error:
                st.warning(f"Account-wide service credits were unavailable: {service_error}")

            finance_summary = _build_finance_movement_summary(
                current_credits=current_credits,
                prior_credits=prior_credits,
                allocated_credits=allocated_credits,
                unallocated_credits=unallocated_credits,
                service_drivers=service_drivers,
                credit_price=credit_price,
                budget=explain_budget,
            )
            st.subheader("Finance Movement Summary")
            st.caption(
                "This bridge separates exact warehouse compute, allocated workload, estimated overhead, "
                "and account-wide service/serverless credits. It is designed for bill review and executive talking points."
            )
            render_priority_dataframe(
                finance_summary,
                title="Finance movement bridge",
                priority_columns=[
                    "Category", "Current Credits", "Prior Credits", "Delta Credits",
                    "Current Cost", "Delta Cost", "Confidence", "Basis", "Action",
                ],
                sort_by=["Current Credits", "Delta Credits"],
                ascending=False,
                raw_label="All finance movement rows",
            )

            narrative = _bill_driver_summary(
                delta_credits=delta_credits,
                current_credits=current_credits,
                prior_credits=prior_credits,
                unallocated_pct=unallocated_pct,
                warehouse_deltas=wh_deltas,
                user_drivers=drivers,
                query_type_drivers=type_drivers,
            )
            st.subheader("Bill Narrative")
            n1, n2 = st.columns([1, 3])
            with n1:
                st.metric("Review Status", narrative["severity"])
            with n2:
                st.markdown(f"**{narrative['headline']}**")
                st.write(narrative["reason"])
                st.caption(narrative["caveat"])
                st.info(narrative["next_action"])

            waterfall = _build_bill_waterfall(
                wh_deltas,
                prior_credits=prior_credits,
                current_credits=current_credits,
                credit_price=credit_price,
            )
            st.subheader("Bill Movement Waterfall")
            st.caption(
                "Positive bars increased the bill; negative bars reduced it. "
                "Baseline and current total are exact warehouse-metering totals."
            )
            st.bar_chart(waterfall, x="Driver", y="Credits", color="Type")
            render_priority_dataframe(
                waterfall,
                title="Bill movement drivers",
                priority_columns=["Driver", "Credits", "Estimated Cost", "Type"],
                sort_by=["Credits"],
                ascending=False,
                raw_label="All bill movement rows",
            )

            if st.session_state.get("exceptions_only_mode"):
                st.subheader("Exceptions Only")
                if wh_deltas is not None and not wh_deltas.empty:
                    exception_rows = wh_deltas[
                        (wh_deltas["CREDIT_DELTA"].fillna(0) > 0)
                        | (wh_deltas["PCT_DELTA"].fillna(0).abs() >= 25)
                    ].copy()
                    if exception_rows.empty:
                        st.success("No warehouse bill exceptions crossed the default thresholds.")
                    else:
                        exception_rows = _annotate_cost_routes(exception_rows, "Warehouse Delta")
                        exception_rows["EST_DELTA_COST"] = exception_rows["CREDIT_DELTA"].apply(
                            lambda v: credits_to_dollars(v, credit_price)
                        )
                        render_priority_dataframe(
                            exception_rows,
                            title="Bill exceptions to explain first",
                            priority_columns=[
                                "WAREHOUSE_NAME", "CURRENT_CREDITS", "PRIOR_CREDITS",
                                "CREDIT_DELTA", "PCT_DELTA", "EST_DELTA_COST",
                                "NEXT_WORKFLOW", "NEXT_ACTION",
                            ],
                            sort_by=["CREDIT_DELTA", "PCT_DELTA"],
                            ascending=[False, False],
                            raw_label="All bill exception rows",
                        )
                else:
                    st.info("No warehouse delta rows available.")
                st.stop()

            st.subheader("Warehouse Deltas")
            render_priority_dataframe(
                _annotate_cost_routes(wh_deltas, "Warehouse Delta"),
                title="Warehouse cost movement to explain first",
                priority_columns=[
                    "WAREHOUSE_NAME", "CURRENT_CREDITS", "PRIOR_CREDITS",
                    "CREDIT_DELTA", "PCT_DELTA", "NEXT_WORKFLOW", "NEXT_ACTION",
                ],
                sort_by=["CREDIT_DELTA", "PCT_DELTA"],
                ascending=[False, False],
                raw_label="All warehouse delta rows",
            )
            if wh_deltas is not None and not wh_deltas.empty:
                render_drillable_bar_chart(
                    wh_deltas.sort_values("CREDIT_DELTA", ascending=False).head(15),
                    dimension="WAREHOUSE_NAME",
                    measure="CREDIT_DELTA",
                    key="cc_explain_wh_delta_chart",
                    drilldown_column="warehouse_name",
                    lookback_hours=bounds["days_back"] * 24,
                )

            st.subheader("Top User / Warehouse Drivers")
            render_priority_dataframe(
                _annotate_cost_routes(drivers, "User Cost"),
                title="User and warehouse spend drivers",
                priority_columns=[
                    "USER_NAME", "WAREHOUSE_NAME", "TOTAL_CREDITS", "QUERY_COUNT",
                    "AVG_EXECUTION_SECONDS", "NEXT_WORKFLOW", "NEXT_ACTION",
                ],
                sort_by=["TOTAL_CREDITS", "QUERY_COUNT"],
                ascending=[False, False],
                raw_label="All user/warehouse driver rows",
            )

            st.subheader("Top Query-Type Drivers")
            render_priority_dataframe(
                _annotate_cost_routes(type_drivers, "Query Type Cost"),
                title="Query-type spend drivers",
                priority_columns=[
                    "QUERY_TYPE", "TOTAL_CREDITS", "QUERY_COUNT",
                    "AVG_EXECUTION_SECONDS", "NEXT_WORKFLOW", "NEXT_ACTION",
                ],
                sort_by=["TOTAL_CREDITS", "QUERY_COUNT"],
                ascending=[False, False],
                raw_label="All query-type driver rows",
            )

            st.subheader("Account-Wide Service / Serverless Contributors")
            st.caption(
                f"{metric_confidence_label('account-wide')} | "
                "METERING_HISTORY service credits are not company-scoped by warehouse. "
                "Use tags, ownership standards, or service-specific lineage before chargeback."
            )
            if service_drivers is not None and not service_drivers.empty:
                service_display = service_drivers.copy()
                service_display["CATEGORY"] = service_display["SERVICE_TYPE"].apply(_service_cost_category)
                service_display = _annotate_cost_routes(service_display, "Service Cost")
                render_priority_dataframe(
                    service_display,
                    title="Service and serverless contributors",
                    priority_columns=[
                        "SERVICE_TYPE", "CATEGORY", "CREDITS_USED", "EST_COST",
                        "NEXT_WORKFLOW", "NEXT_ACTION",
                    ],
                    sort_by=["CREDITS_USED"],
                    ascending=False,
                    raw_label="All service contributor rows",
                )
            else:
                st.info("No service/serverless contributor rows were available for this period.")

            report_md = _build_explain_bill_markdown(
                company=company,
                period_label=bounds["label"],
                current_credits=current_credits,
                prior_credits=prior_credits,
                credit_price=credit_price,
                active_warehouses=active_warehouses,
                allocated_credits=allocated_credits,
                unallocated_credits=unallocated_credits,
                warehouse_deltas=wh_deltas,
                user_drivers=drivers,
                query_type_drivers=type_drivers,
                service_drivers=service_drivers,
            )
            st.download_button(
                "Download Bill Explanation",
                report_md,
                file_name=f"overwatch_bill_explanation_{company.lower()}.md",
                mime="text/markdown",
                key="cc_explain_download",
            )
            if st.button("Save Bill Exceptions to Action Queue", key="cc_explain_queue"):
                _queue_bill_exceptions(session, wh_deltas, credit_price, bounds["label"])

    elif cost_view == "User Leaderboard":
        st.header("Credit Cost by User / Warehouse")
        days = st.slider("Lookback (days)", 1, 90, 30, key="cc_lead_days")
        gf = get_global_filter_clause(
            "q.start_time", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name"
        )

        if st.button("Load Leaderboard", key="cc_lead_load"):
            try:
                df_lead = run_query(f"""
                WITH {build_metered_credit_cte(days_back=days)}
                SELECT
                    q.user_name,
                    q.warehouse_name,
                    {max_wh_size_expr} AS warehouse_size,
                    COUNT(*)                                     AS query_count,
                    ROUND(AVG(q.total_elapsed_time)/1000, 2)    AS avg_elapsed_sec,
                    ROUND(SUM(pqc.metered_credits), 4)          AS total_credits,
                    ROUND({bytes_scanned_sum_expr}/POWER(1024,3),2) AS total_gb_scanned
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND q.warehouse_name IS NOT NULL
                  {gf}
                GROUP BY q.user_name, q.warehouse_name
                ORDER BY total_credits DESC
                LIMIT 200
                """, ttl_key=f"cc_lead_{company}_{days}", tier="standard")
                st.session_state["df_lead"] = df_lead
            except Exception as e:
                st.warning(f"Cost leaderboard unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("df_lead") is not None and not st.session_state["df_lead"].empty:
            df_l = st.session_state["df_lead"]
            df_l["COST"] = df_l["TOTAL_CREDITS"].apply(lambda x: credits_to_dollars(x, credit_price))
            c1, c2, c3 = st.columns(3)
            c1.metric("Distinct Users",  df_l["USER_NAME"].nunique())
            c2.metric("Total Credits",   format_credits(df_l["TOTAL_CREDITS"].sum()))
            c3.metric("Total Est. Cost", f"${df_l['COST'].sum():,.2f}")
            st.caption(f"{metric_confidence_label('allocated')} | {freshness_note('ACCOUNT_USAGE')}")

            st.subheader("Top Users by Cost")
            df_l = _annotate_cost_routes(df_l, "User Cost")
            user_agg = (
                df_l.groupby("USER_NAME")["COST"]
                .sum().reset_index()
                .sort_values("COST", ascending=False)
                .head(20)
            )
            render_drillable_bar_chart(
                user_agg,
                dimension="USER_NAME",
                measure="COST",
                key="cc_user_cost",
                drilldown_column="user_name",
                lookback_hours=days * 24,
            )
            render_priority_dataframe(
                df_l,
                title="Cost leaderboard drivers",
                priority_columns=[
                    "USER_NAME",
                    "WAREHOUSE_NAME",
                    "WAREHOUSE_SIZE",
                    "TOTAL_CREDITS",
                    "COST",
                    "QUERY_COUNT",
                    "AVG_ELAPSED_SEC",
                    "TOTAL_GB_SCANNED",
                    "NEXT_WORKFLOW",
                    "NEXT_ACTION",
                ],
                sort_by=["TOTAL_CREDITS", "COST", "QUERY_COUNT"],
                ascending=[False, False, False],
                raw_label="All user/warehouse cost rows",
            )

            # User profile drill-through
            st.divider()
            st.subheader("User Profile Drill-Down")
            if "USER_NAME" in df_l.columns:
                sel_user = st.selectbox(
                    "Select user for full query breakdown",
                    df_l["USER_NAME"].dropna().unique().tolist(),
                    key="cc_user_profile_sel",
                )
                if sel_user:
                    render_entity_query_drilldown(
                        sel_user, key="cc_user_profile",
                        entity_column="user_name", lookback_hours=days * 24,
                    )

            download_csv(df_l, "cost_leaderboard.csv")
            if st.button("Save top cost outliers to Action Queue", key="cc_lead_queue"):
                _queue_cost_outliers(session, df_l, credit_price, "Cost & Contract - User Leaderboard")

    # ── BURN RATE ─────────────────────────────────────────────────────────────
    elif cost_view == "Burn Rate":
        st.header("Credit Burn Rate")
        br_days = st.slider("Lookback (days)", 1, 90, 30, key="br_days")
        if st.button("Load Burn Rate", key="br_load"):
            try:
                df_br = run_query(f"""
                    WITH latest_size AS (
                        SELECT warehouse_name, warehouse_size
                        FROM (
                            SELECT warehouse_name, {wh_size_plain_expr},
                            ROW_NUMBER() OVER (PARTITION BY warehouse_name ORDER BY start_time DESC) AS rn
                            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                            WHERE start_time >= DATEADD('day', -{br_days}, CURRENT_TIMESTAMP())
                              AND warehouse_name IS NOT NULL
                              {get_wh_filter_clause("warehouse_name")}
                        )
                        WHERE rn = 1
                    )
                    SELECT DATE_TRUNC('day', m.start_time) AS day,
                           m.warehouse_name,
                           ls.warehouse_size,
                           SUM(m.credits_used) AS daily_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY m
                    LEFT JOIN latest_size ls ON m.warehouse_name = ls.warehouse_name
                    WHERE m.start_time >= DATEADD('day', -{br_days}, CURRENT_TIMESTAMP())
                    {get_wh_filter_clause("m.warehouse_name")}
                    GROUP BY day, m.warehouse_name, ls.warehouse_size
                    ORDER BY day
                """, ttl_key=f"cc_burn_{company}_{br_days}", tier="standard")
                st.session_state["df_br"] = df_br
            except Exception as e:
                st.warning(f"Burn-rate data unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("df_br") is not None and not st.session_state["df_br"].empty:
            df_b = st.session_state["df_br"]
            total_cr = df_b["DAILY_CREDITS"].sum()
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Credits",     format_credits(total_cr))
            c2.metric("Total Cost",        f"${credits_to_dollars(total_cr, credit_price):,.2f}")
            c3.metric("Avg Daily Credits", f"{total_cr / max(br_days,1):,.2f}")
            st.caption(f"{metric_confidence_label('exact')} | {freshness_note('WAREHOUSE_METERING_HISTORY')}")
            daily = df_b.groupby("DAY")["DAILY_CREDITS"].sum().reset_index()
            st.line_chart(daily.set_index("DAY")["DAILY_CREDITS"])
            by_wh = (
                df_b.groupby("WAREHOUSE_NAME")["DAILY_CREDITS"]
                .sum().reset_index()
                .sort_values("DAILY_CREDITS", ascending=False)
            )
            st.subheader("Credits by Warehouse")
            render_drillable_bar_chart(
                by_wh, dimension="WAREHOUSE_NAME", measure="DAILY_CREDITS",
                key="cc_wh_credits", drilldown_column="warehouse_name",
                lookback_hours=br_days * 24,
            )
            download_csv(df_b, "burn_rate.csv")

    # -- COST RECONCILIATION -------------------------------------------------
    elif cost_view == "Reconciliation":
        st.header("Cost Reconciliation")
        st.caption(
            "Compares exact warehouse metering to query-level allocated credits. "
            "Large variances usually mean idle warehouse time, non-query activity, latency, or chargeback assumptions need review."
        )
        recon_days = st.slider("Reconciliation window (days)", 7, 90, 30, key="cc_recon_days")
        if st.button("Load Reconciliation", key="cc_recon_load"):
            try:
                st.session_state["df_cc_recon"] = run_query(
                    build_cost_reconciliation_sql(recon_days),
                    ttl_key=f"cc_recon_{company}_{recon_days}",
                    tier="standard",
                    section="Cost & Contract",
                )
            except Exception as e:
                st.warning(f"Cost reconciliation unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("df_cc_recon") is not None and not st.session_state["df_cc_recon"].empty:
            df_r = st.session_state["df_cc_recon"]
            total_exact = float(df_r["EXACT_METERED_CREDITS"].sum()) if "EXACT_METERED_CREDITS" in df_r.columns else 0.0
            total_alloc = float(df_r["ALLOCATED_QUERY_CREDITS"].sum()) if "ALLOCATED_QUERY_CREDITS" in df_r.columns else 0.0
            total_var = total_exact - total_alloc
            c1, c2, c3 = st.columns(3)
            c1.metric("Exact Metered", format_credits(total_exact))
            c2.metric("Allocated to Queries", format_credits(total_alloc))
            c3.metric("Unallocated / Variance", format_credits(total_var))
            st.caption(
                f"{metric_confidence_label('exact')} for metering; "
                f"{metric_confidence_label('allocated')} for query attribution | "
                f"{freshness_note('WAREHOUSE_METERING_HISTORY')}"
            )
            if "RECONCILIATION_STATUS" in df_r.columns:
                st.bar_chart(df_r["RECONCILIATION_STATUS"].value_counts())
            render_priority_dataframe(
                df_r,
                title="Reconciliation variances to review",
                priority_columns=[
                    "WAREHOUSE_NAME",
                    "EXACT_METERED_CREDITS",
                    "ALLOCATED_QUERY_CREDITS",
                    "VARIANCE_CREDITS",
                    "VARIANCE_PCT",
                    "RECONCILIATION_STATUS",
                ],
                sort_by=["VARIANCE_CREDITS", "VARIANCE_PCT", "EXACT_METERED_CREDITS"],
                ascending=[False, False, False],
                raw_label="All reconciliation rows",
                height=420,
            )
            download_csv(df_r, "cost_reconciliation.csv")

    # ── FORECAST ──────────────────────────────────────────────────────────────
    elif cost_view == "Forecast":
        st.header("Credit Forecast (30-day Linear Projection)")
        if st.button("Generate Forecast", key="fc_load"):
            try:
                df_fc = run_query(f"""
                    SELECT DATE_TRUNC('day', start_time) AS day,
                           SUM(credits_used) AS daily_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                    WHERE start_time >= DATEADD('day', -30, CURRENT_TIMESTAMP())
                    {get_wh_filter_clause("warehouse_name")}
                    GROUP BY day ORDER BY day
                """, ttl_key=f"cc_forecast_30_{company}", tier="standard")
                st.session_state["df_fc"] = df_fc
            except Exception as e:
                st.warning(f"Forecast data unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("df_fc") is not None and not st.session_state["df_fc"].empty:
            df_f = st.session_state["df_fc"].copy()
            df_f["DAY"] = pd.to_datetime(df_f["DAY"])
            full_window = pd.DataFrame({
                "DAY": pd.date_range(
                    pd.Timestamp.today().normalize() - pd.Timedelta(days=29),
                    pd.Timestamp.today().normalize(),
                    freq="D",
                )
            })
            df_f = full_window.merge(df_f, on="DAY", how="left")
            df_f["DAILY_CREDITS"] = pd.to_numeric(df_f["DAILY_CREDITS"], errors="coerce").fillna(0)
            avg_daily = df_f["DAILY_CREDITS"].mean()
            proj_30   = avg_daily * 30
            proj_cost = credits_to_dollars(proj_30, credit_price)
            c1, c2, c3 = st.columns(3)
            c1.metric("Avg Daily Credits",     f"{avg_daily:.2f}")
            c2.metric("Projected 30-day",      format_credits(proj_30))
            c3.metric("Projected 30-day Cost", f"${proj_cost:,.2f}")
            st.area_chart(df_f.set_index("DAY")["DAILY_CREDITS"])

    # ── BUDGET VS ACTUAL ──────────────────────────────────────────────────────
    elif cost_view == "Budget vs Actual":
        st.header("Budget vs Actual")
        monthly_budget = st.number_input(
            "Monthly credit budget", min_value=0, value=10000, step=500, key="bva_budget"
        )
        if st.button("Load Budget Comparison", key="bva_load"):
            try:
                df_bva = run_query(f"""
                    SELECT DATE_TRUNC('month', start_time) AS month,
                           SUM(credits_used) AS actual_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                    WHERE start_time >= DATEADD('month', -6, CURRENT_TIMESTAMP())
                    {get_wh_filter_clause("warehouse_name")}
                    GROUP BY month ORDER BY month
                """, ttl_key=f"cc_budget_6mo_{company}", tier="standard")
                st.session_state["df_bva"] = df_bva
            except Exception as e:
                st.warning(f"Budget comparison unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("df_bva") is not None and not st.session_state["df_bva"].empty:
            df_bv = st.session_state["df_bva"]
            df_bv["BUDGET"]    = monthly_budget
            df_bv["OVER_UNDER"] = df_bv["ACTUAL_CREDITS"] - monthly_budget
            df_bv["STATUS"]    = df_bv["OVER_UNDER"].apply(
                lambda x: "Over" if x > 0 else "Under"
            )
            render_priority_dataframe(
                df_bv,
                title="Budget months to explain",
                priority_columns=["MONTH", "ACTUAL_CREDITS", "BUDGET", "OVER_UNDER", "STATUS"],
                sort_by=["OVER_UNDER", "ACTUAL_CREDITS"],
                ascending=[False, False],
                raw_label="All budget comparison rows",
            )
            st.bar_chart(df_bv.set_index("MONTH")[["ACTUAL_CREDITS","BUDGET"]])
            download_csv(df_bv, "budget_vs_actual.csv")

    # ── ATTRIBUTION ───────────────────────────────────────────────────────────
    elif cost_view == "Attribution":
        st.header("Cost Attribution")
        attr_days = st.slider("Lookback (days)", 1, 90, 30, key="cc_attr_days")
        attr_mode = st.selectbox(
            "Attribution dimension",
            ["Role", "Database / Schema", "Application / Client", "Stored Procedure / Task Lineage"],
            key="cc_attr_mode",
        )
        gf = get_global_filter_clause(
            "q.start_time", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name"
        )

        if st.button("Load Attribution", key="cc_attr_load"):
            if attr_mode == "Role":
                select_cols = "COALESCE(q.role_name, 'UNKNOWN') AS dimension"
                group_cols  = "COALESCE(q.role_name, 'UNKNOWN')"
            elif attr_mode == "Database / Schema":
                select_cols = "COALESCE(q.database_name,'UNKNOWN')||'.'||COALESCE(q.schema_name,'UNKNOWN') AS dimension"
                group_cols  = "COALESCE(q.database_name,'UNKNOWN')||'.'||COALESCE(q.schema_name,'UNKNOWN')"
            elif attr_mode == "Application / Client":
                select_cols = f"{query_tag_dimension_expr} AS dimension"
                group_cols  = query_tag_dimension_expr
            else:
                select_cols = "COALESCE(REGEXP_SUBSTR(q.query_text,'CALL\\\\s+([^\\\\(]+)',1,1,'i',1), q.query_type, 'ADHOC') AS dimension"
                group_cols  = "COALESCE(REGEXP_SUBSTR(q.query_text,'CALL\\\\s+([^\\\\(]+)',1,1,'i',1), q.query_type, 'ADHOC')"

            try:
                df_attr = run_query(f"""
                WITH {build_metered_credit_cte(days_back=attr_days)}
                SELECT {select_cols},
                       COUNT(*) AS query_count,
                       COUNT(DISTINCT q.user_name)      AS users,
                       COUNT(DISTINCT q.warehouse_name) AS warehouses,
                       ROUND(SUM(COALESCE(pqc.metered_credits,0)),4) AS total_credits,
                       ROUND({bytes_scanned_sum_expr}/POWER(1024,3),2)   AS gb_scanned
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                WHERE q.start_time >= DATEADD('day', -{attr_days}, CURRENT_TIMESTAMP())
                  AND q.warehouse_name IS NOT NULL
                  {gf}
                GROUP BY {group_cols}
                ORDER BY total_credits DESC
                LIMIT 200
                """, ttl_key=f"cc_attr_{company}_{attr_mode}_{attr_days}", tier="standard")
                st.session_state["df_cc_attr"] = df_attr
            except Exception as e:
                st.warning(f"Attribution data unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("df_cc_attr") is not None and not st.session_state["df_cc_attr"].empty:
            df_attr = st.session_state["df_cc_attr"]
            df_attr["EST_COST"] = df_attr["TOTAL_CREDITS"].apply(lambda x: credits_to_dollars(x, credit_price))
            render_priority_dataframe(
                df_attr,
                title=f"{attr_mode} cost attribution drivers",
                priority_columns=[
                    "DIMENSION",
                    "TOTAL_CREDITS",
                    "EST_COST",
                    "QUERY_COUNT",
                    "USERS",
                    "WAREHOUSES",
                    "GB_SCANNED",
                ],
                sort_by=["TOTAL_CREDITS", "EST_COST", "QUERY_COUNT"],
                ascending=[False, False, False],
                raw_label="All attribution rows",
            )
            dim_col = (
                "role_name" if attr_mode == "Role" else
                "database_schema" if attr_mode == "Database / Schema" else
                "application_client" if attr_mode == "Application / Client" else
                "lineage_dimension"
            )
            render_drillable_bar_chart(
                df_attr, dimension="DIMENSION", measure="EST_COST",
                key="cc_attr_cost", title="Attribution drill-down",
                drilldown_column=dim_col, lookback_hours=attr_days * 24,
            )
            download_csv(df_attr, "cost_attribution.csv")

    # ── CHARGEBACK — ALFA / Trexis split ─────────────────────────────────────
    elif cost_view == "Chargeback":
        st.header("ALFA / Trexis Chargeback")
        st.caption(
            "Credits split by company using the canonical warehouse/DB/user classification. "
            "Uses `get_company_case_expr()` — stays in sync with config.py warehouse inventory."
        )
        cb_days = st.slider("Lookback (days)", 1, 90, 30, key="cc_cb_days")

        if st.button("Load Chargeback", key="cc_cb_load"):
            try:
                # FIX: replaced hardcoded CASE with get_company_case_expr()
                # which reads from COMPANY_CONFIG and includes all WH_ALFA_* warehouses
                company_expr = get_company_case_expr(
                    "q.warehouse_name", "q.database_name", "q.user_name"
                )
                df_cb = run_query(f"""
                WITH {build_metered_credit_cte(days_back=cb_days)},
                query_costs AS (
                    SELECT
                        {company_expr}         AS company,
                        q.user_name,
                        q.warehouse_name,
                        {max_wh_size_expr} AS warehouse_size,
                        COUNT(*)               AS query_count,
                        SUM(COALESCE(pqc.metered_credits,0)) AS total_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                    WHERE q.start_time >= DATEADD('day', -{cb_days}, CURRENT_TIMESTAMP())
                      AND q.warehouse_name IS NOT NULL
                      {get_wh_filter_clause("q.warehouse_name")}
                    GROUP BY company, q.user_name, q.warehouse_name
                )
                SELECT company, user_name, warehouse_name, warehouse_size, query_count,
                       ROUND(total_credits, 4) AS total_credits
                FROM query_costs
                ORDER BY total_credits DESC
                """, ttl_key=f"cc_chargeback_{company}_{cb_days}", tier="standard")
                st.session_state["df_chargeback"] = df_cb
            except Exception as e:
                st.warning(f"Chargeback data unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("df_chargeback") is not None and not st.session_state["df_chargeback"].empty:
            df_cb = st.session_state["df_chargeback"]
            df_cb["EST_COST"] = df_cb["TOTAL_CREDITS"].apply(lambda x: credits_to_dollars(x, credit_price))

            # Summary by company — the key chargeback output
            summary = (
                df_cb.groupby("COMPANY", as_index=False)[["TOTAL_CREDITS","EST_COST","QUERY_COUNT"]]
                .sum()
                .sort_values("EST_COST", ascending=False)
            )
            c1, c2, c3 = st.columns(len(summary))
            for idx, srow in summary.iterrows():
                col = [c1, c2, c3][idx % 3]
                col.metric(
                    srow["COMPANY"],
                    f"${srow['EST_COST']:,.2f}",
                    f"{format_credits(srow['TOTAL_CREDITS'])}",
                )

            st.subheader("Summary by Company")
            render_priority_dataframe(
                summary,
                title="Chargeback summary",
                priority_columns=["COMPANY", "TOTAL_CREDITS", "EST_COST", "QUERY_COUNT"],
                sort_by=["EST_COST", "TOTAL_CREDITS"],
                ascending=[False, False],
                raw_label="All chargeback summary rows",
            )

            st.subheader("Detail by User / Warehouse")
            company_filter = st.selectbox(
                "Filter by company", ["All"] + summary["COMPANY"].tolist(), key="cb_co_filter"
            )
            df_show = df_cb if company_filter == "All" else df_cb[df_cb["COMPANY"] == company_filter]
            df_show = _annotate_cost_routes(df_show, "Chargeback")
            render_priority_dataframe(
                df_show,
                title="Chargeback detail drivers",
                priority_columns=[
                    "COMPANY",
                    "USER_NAME",
                    "WAREHOUSE_NAME",
                    "WAREHOUSE_SIZE",
                    "TOTAL_CREDITS",
                    "EST_COST",
                    "QUERY_COUNT",
                    "NEXT_WORKFLOW",
                    "NEXT_ACTION",
                ],
                sort_by=["EST_COST", "TOTAL_CREDITS", "QUERY_COUNT"],
                ascending=[False, False, False],
                raw_label="All chargeback detail rows",
            )
            download_csv(df_show, "chargeback_detail.csv")
            if st.button("Save chargeback outliers to Action Queue", key="cc_chargeback_queue"):
                _queue_cost_outliers(session, df_show, credit_price, "Cost & Contract - Chargeback")

    # ── CONTRACT / COMMITMENT UTILIZATION ─────────────────────────────────────
    elif cost_view == "Contract Utilization":
        st.header("Contract & Commitment Utilization")
        st.caption(
            "Track consumption against your annual Snowflake committed-use contract. "
            "Projects burn rate to flag over- and under-utilization risk. "
            "This is the canonical contract view; the standalone Credit Contract page has been consolidated here."
        )

        col_ct1, col_ct2, col_ct3 = st.columns(3)
        with col_ct1:
            committed_credits = st.number_input(
                "Annual committed credits",
                min_value=0, max_value=10_000_000, value=100_000, step=1_000,
                key="cc_committed_credits",
                help="Total credits in your Snowflake annual contract."
            )
        with col_ct2:
            from datetime import datetime as _dt
            contract_start = st.date_input(
                "Contract start date",
                value=_dt(datetime.now().year, 1, 1).date(),
                key="cc_contract_start",
            )
        with col_ct3:
            contract_months = st.number_input(
                "Contract length (months)", min_value=1, max_value=60, value=12,
                key="cc_contract_months",
            )

        if st.button("Calculate Utilization", key="cc_contract_calc"):
            try:
                ytd_source = "SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY" if company == "ALL" else "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
                ytd_filter = "" if company == "ALL" else get_wh_filter_clause("warehouse_name", company)
                df_ytd = run_query(f"""
                    SELECT TO_DATE(start_time) AS usage_date,
                           SUM(credits_used) AS credits_used
                    FROM {ytd_source}
                    WHERE start_time >= TO_DATE({sql_literal(str(contract_start))})
                      AND start_time <  DATEADD('hour', -24, CURRENT_TIMESTAMP())
                      {ytd_filter}
                    GROUP BY usage_date
                    ORDER BY usage_date
                """, ttl_key=f"cc_contract_ytd_{company}_{contract_start}", tier="historical")
                st.session_state["cc_contract_data"] = df_ytd
                st.session_state["cc_contract_params"] = {
                    "committed": committed_credits,
                    "start": str(contract_start),
                    "months": contract_months,
                }
            except Exception as e:
                st.warning(f"Utilization data unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("cc_contract_data") is not None:
            df_c  = st.session_state["cc_contract_data"]
            params = st.session_state.get("cc_contract_params", {})
            committed = params.get("committed", committed_credits)
            start_str = params.get("start", str(contract_start))
            months    = params.get("months", contract_months)

            start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
            days_in_contract = max(int(round(float(months) * 30.44)), 1)
            contract_end_date = start_date + timedelta(days=days_in_contract - 1)
            as_of_date = min(max(datetime.now().date() - timedelta(days=1), start_date), contract_end_date)

            observed_days = pd.DataFrame({
                "USAGE_DATE": pd.date_range(start_date, as_of_date, freq="D")
            })
            df_daily = df_c.copy()
            if df_daily.empty:
                df_daily = observed_days.copy()
                df_daily["CREDITS_USED"] = 0.0
            else:
                df_daily["USAGE_DATE"] = pd.to_datetime(df_daily["USAGE_DATE"]).dt.normalize()
                df_daily["CREDITS_USED"] = pd.to_numeric(df_daily["CREDITS_USED"], errors="coerce").fillna(0.0)
                df_daily = observed_days.merge(df_daily, on="USAGE_DATE", how="left")
                df_daily["CREDITS_USED"] = df_daily["CREDITS_USED"].fillna(0.0)

            ytd_used = float(df_daily["CREDITS_USED"].sum())
            days_elapsed = max(len(df_daily), 1)
            days_remaining = max((contract_end_date - as_of_date).days, 0)

            daily_rate = ytd_used / days_elapsed
            last_7_avg = float(df_daily.tail(min(7, len(df_daily)))["CREDITS_USED"].mean() or 0)
            last_30_avg = float(df_daily.tail(min(30, len(df_daily)))["CREDITS_USED"].mean() or 0)
            trend_label = burn_trend_label(last_7_avg, last_30_avg)

            future_days = pd.date_range(as_of_date + timedelta(days=1), contract_end_date, freq="D")
            future_business_days = int((future_days.dayofweek < 5).sum()) if len(future_days) else 0
            future_weekend_days = len(future_days) - future_business_days
            business_hist = df_daily[df_daily["USAGE_DATE"].dt.dayofweek < 5]
            weekend_hist = df_daily[df_daily["USAGE_DATE"].dt.dayofweek >= 5]
            business_avg = float(business_hist.tail(20)["CREDITS_USED"].mean() or last_30_avg or daily_rate)
            weekend_avg = float(weekend_hist.tail(8)["CREDITS_USED"].mean() or last_30_avg or daily_rate)

            projected_total = ytd_used + (daily_rate * days_remaining)
            projected_7 = ytd_used + (last_7_avg * days_remaining)
            projected_30 = ytd_used + (last_30_avg * days_remaining)
            projected_business = ytd_used + (business_avg * future_business_days) + (weekend_avg * future_weekend_days)
            remaining_budget = committed - ytd_used
            pct_consumed     = (ytd_used / committed * 100) if committed > 0 else 0
            pct_time_elapsed = (days_elapsed / days_in_contract * 100) if days_in_contract > 0 else 0

            runway_rate = last_7_avg if trend_label == "Accelerating" and last_7_avg > 0 else daily_rate
            if runway_rate > 0 and remaining_budget > 0:
                days_until_exhausted = remaining_budget / runway_rate
                exhaust_date = (datetime.now() + timedelta(days=days_until_exhausted)).strftime("%Y-%m-%d")
            else:
                days_until_exhausted = None
                exhaust_date = "N/A"

            # Pacing ratio: credits consumed % vs time elapsed %
            pacing_ratio = (pct_consumed / pct_time_elapsed) if pct_time_elapsed > 0 else 1.0
            projected_pct_over = ((projected_total / committed) * 100 - 100) if committed > 0 else 0.0

            # ── KPI row ────────────────────────────────────────────────────────
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("YTD Consumed",         format_credits(ytd_used))
            k2.metric("Remaining Budget",     format_credits(remaining_budget))
            k3.metric("% Consumed",           f"{pct_consumed:.1f}%",
                      delta=f"{pct_consumed - pct_time_elapsed:+.1f}% vs time",
                      delta_color="inverse" if pct_consumed > pct_time_elapsed + 5 else "normal")
            k4.metric("Daily Burn Rate",      f"{daily_rate:,.1f} cr/day")
            k5.metric("Projected Year-End",   format_credits(projected_total))
            st.caption(
                f"{metric_confidence_label('exact')} for consumed credits | "
                f"{metric_confidence_label('projection')} | "
                f"{freshness_note('WAREHOUSE_METERING_HISTORY')}"
            )

            p1, p2, p3 = st.columns(3)
            p1.metric("7-Day Projection", format_credits(projected_7), trend_label)
            p2.metric("30-Day Projection", format_credits(projected_30), burn_trend_label(last_30_avg, daily_rate))
            p3.metric("Business-Day Adjusted", format_credits(projected_business), f"{business_avg:,.1f} cr/business day")

            # ── Progress bar ───────────────────────────────────────────────────
            bar_pct = min(pct_consumed / 100, 1.0)
            st.progress(bar_pct, text=f"{pct_consumed:.1f}% of {committed:,} committed credits")

            # ── Pacing diagnosis ───────────────────────────────────────────────
            st.divider()
            if pacing_ratio > 1.15:
                exhaustion_line = (
                    f"At {runway_rate:,.1f} cr/day you will exhaust the commitment on "
                    f"**{exhaust_date}** ({days_until_exhausted:.0f} days from now), "
                    f"**{days_remaining - days_until_exhausted:.0f} days early**. "
                    if days_until_exhausted is not None
                    else "Current burn cannot calculate a reliable exhaustion date. "
                )
                st.error(
                    f"🔴 **Burning too fast** — consuming credits {pacing_ratio:.1f}x faster than the "
                    f"contract pace. {exhaustion_line}"
                    f"Projected year-end: **{projected_total:,.0f}** vs committed **{committed:,}** "
                    f"({projected_pct_over:.0f}% over)."
                )
            elif pacing_ratio < 0.75:
                under_pct = 100 - (projected_total / committed * 100) if committed > 0 else 0.0
                st.warning(
                    f"🟡 **Under-utilizing** — tracking at {pacing_ratio:.2f}x the contract pace. "
                    f"Projected year-end: **{projected_total:,.0f}** of {committed:,} credits "
                    f"({under_pct:.0f}% under-utilized). "
                    f"Review with Snowflake account team — unused committed credits typically do not roll over."
                )
            else:
                st.success(
                    f"✅ **On pace** — pacing ratio {pacing_ratio:.2f}x. "
                    f"Projected year-end: **{projected_total:,.0f}** of {committed:,} credits "
                    f"({pct_consumed:.0f}% consumed, {pct_time_elapsed:.0f}% of contract elapsed)."
                )

            # ── Monthly breakdown chart ────────────────────────────────────────
            st.divider()
            st.subheader("Monthly Consumption")
            if st.button("Load Monthly Breakdown", key="cc_monthly_breakdown"):
                try:
                    monthly_source = "SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY" if company == "ALL" else "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
                    monthly_filter = "" if company == "ALL" else get_wh_filter_clause("warehouse_name", company)
                    df_monthly = run_query(f"""
                        SELECT DATE_TRUNC('month', start_time) AS month,
                               SUM(credits_used) AS monthly_credits,
                               SUM(credits_used) * {credit_price} AS monthly_cost
                        FROM {monthly_source}
                        WHERE start_time >= TO_DATE({sql_literal(start_str)})
                          AND start_time <  DATEADD('hour', -24, CURRENT_TIMESTAMP())
                          {monthly_filter}
                        GROUP BY month
                        ORDER BY month
                    """, ttl_key=f"cc_monthly_{company}_{start_str}_{credit_price}", tier="historical")
                    st.session_state["cc_monthly_data"] = df_monthly
                except Exception as e:
                    st.warning(f"Monthly breakdown unavailable in this role/context: {format_snowflake_error(e)}")

            if st.session_state.get("cc_monthly_data") is not None and not st.session_state["cc_monthly_data"].empty:
                df_m = st.session_state["cc_monthly_data"]
                df_m["BUDGET_LINE"] = committed / (months or 12)
                df_m["CUMULATIVE"]  = df_m["MONTHLY_CREDITS"].cumsum()

                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    st.caption("Monthly credits vs equal-share budget line")
                    st.bar_chart(df_m.set_index("MONTH")[["MONTHLY_CREDITS","BUDGET_LINE"]])
                with col_m2:
                    st.caption("Cumulative consumption")
                    st.line_chart(df_m.set_index("MONTH")["CUMULATIVE"])

                download_csv(df_m, "contract_utilization.csv")

            # ── By service type ────────────────────────────────────────────────
            st.divider()
            st.subheader("Consumption by Service Type")
            if company != "ALL":
                st.info("Service-type metering is account-level in Snowflake. Switch Company View to ALL for a full service breakdown.")
            else:
                if st.button("Load Service Breakdown", key="cc_service_type"):
                    try:
                        df_svc = run_query(f"""
                            SELECT service_type,
                                   SUM(credits_used) AS total_credits,
                                   ROUND(SUM(credits_used) / NULLIF({ytd_used}, 0) * 100, 1) AS pct_of_total
                            FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
                            WHERE start_time >= TO_DATE({sql_literal(start_str)})
                              AND start_time <  DATEADD('hour', -24, CURRENT_TIMESTAMP())
                            GROUP BY service_type
                            ORDER BY total_credits DESC
                        """, ttl_key=f"cc_service_{company}_{start_str}_{ytd_used}", tier="historical")
                        st.session_state["cc_svc_data"] = df_svc
                    except Exception as e:
                        st.warning(f"Service breakdown unavailable in this role/context: {format_snowflake_error(e)}")

                if st.session_state.get("cc_svc_data") is not None and not st.session_state["cc_svc_data"].empty:
                    df_sv = st.session_state["cc_svc_data"]
                    render_priority_dataframe(
                        df_sv,
                        title="Service-type contract consumption",
                        priority_columns=["SERVICE_TYPE", "TOTAL_CREDITS", "PCT_OF_TOTAL"],
                        sort_by=["TOTAL_CREDITS", "PCT_OF_TOTAL"],
                        ascending=[False, False],
                        raw_label="All service-type rows",
                    )
                    st.bar_chart(df_sv.set_index("SERVICE_TYPE")["TOTAL_CREDITS"])
                    download_csv(df_sv, "contract_by_service_type.csv")
