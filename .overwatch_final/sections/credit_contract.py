# sections/credit_contract.py - contract burn-down and credit forecast
from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from utils import (
    download_csv,
    format_credits,
    get_active_company,
    get_session,
    get_wh_filter_clause,
    run_query,
    sql_literal,
    upsert_actions,
)


def _load_daily_credits(session, start_date: date, end_date: date):
    wh_filter = get_wh_filter_clause("warehouse_name")
    return run_query(f"""
        SELECT
            TO_DATE(start_time) AS usage_date,
            ROUND(SUM(credits_used), 4) AS credits_used,
            ROUND(SUM(credits_used_compute), 4) AS compute_credits,
            ROUND(SUM(credits_used_cloud_services), 4) AS cloud_service_credits,
            COUNT(DISTINCT warehouse_name) AS active_warehouses
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= TO_TIMESTAMP_NTZ({sql_literal(start_date.isoformat() + " 00:00:00")})
          AND start_time < DATEADD('day', 1, TO_TIMESTAMP_NTZ({sql_literal(end_date.isoformat() + " 00:00:00")}))
          {wh_filter}
        GROUP BY TO_DATE(start_time)
        ORDER BY usage_date
    """, ttl_key=f"credit_contract_daily_{start_date}_{end_date}", tier="standard")


def _queue_contract_risk(session, projected_credits: float, purchased_credits: float, runout: str):
    company = get_active_company()
    overage = projected_credits - purchased_credits
    action = {
        "Source": "Credit Contract",
        "Category": "Contract Risk",
        "Severity": "High" if overage > purchased_credits * 0.1 else "Medium",
        "Entity Type": "Snowflake Contract",
        "Entity": f"{company} credit commitment",
        "Owner": "Leadership/DBA",
        "Finding": f"Projected annual usage is {projected_credits:,.0f} credits against {purchased_credits:,.0f} purchased credits.",
        "Action": "Review top cost drivers, active warehouses, and optimization backlog before committing to additional spend.",
        "Estimated Monthly Savings": 0,
        "Generated SQL Fix": "-- Use OVERWATCH Cost Center and Usage Overview to identify candidates for right-sizing.",
        "Proof Query": "SELECT TO_DATE(start_time), SUM(credits_used) "
                       "FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY GROUP BY 1 ORDER BY 1;",
        "Company": company,
    }
    if runout:
        action["Finding"] += f" Current run-rate exhausts remaining credits around {runout}."
    saved = upsert_actions(session, [action])
    st.success(f"Saved {saved} contract risk item to the action queue.")


def render():
    session = get_session()
    credit_price = st.session_state.get("credit_price", 3.0)

    st.header("Credit Contract")
    st.caption("Track purchased credits, burn-down pace, projected overage, and remaining runway.")

    today = date.today()
    default_start = date(today.year, 1, 1)
    c1, c2, c3 = st.columns(3)
    with c1:
        purchased = st.number_input("Purchased credits", min_value=0.0, value=100000.0, step=1000.0, key="contract_purchased")
    with c2:
        contract_start = st.date_input("Contract start", value=default_start, key="contract_start")
    with c3:
        contract_end = st.date_input("Contract end", value=default_start + timedelta(days=364), key="contract_end")

    if contract_end <= contract_start:
        st.warning("Contract end must be after contract start.")
        return

    if st.button("Load Contract Burn", key="contract_load"):
        with st.spinner("Loading credit burn-down..."):
            try:
                st.session_state["contract_daily"] = _load_daily_credits(session, contract_start, min(today, contract_end))
            except Exception as e:
                st.error(f"Unable to load credit contract data: {e}")

    df = st.session_state.get("contract_daily")
    if df is None:
        return
    if df.empty:
        st.info("No warehouse metering found for the selected contract window.")
        return

    df = df.copy()
    df["USAGE_DATE"] = pd.to_datetime(df["USAGE_DATE"])
    df["CUMULATIVE_CREDITS"] = pd.to_numeric(df["CREDITS_USED"], errors="coerce").fillna(0).cumsum()
    elapsed_days = max((min(today, contract_end) - contract_start).days + 1, 1)
    contract_days = max((contract_end - contract_start).days + 1, 1)
    used_to_date = float(df["CREDITS_USED"].sum())
    avg_daily = used_to_date / elapsed_days
    projected = avg_daily * contract_days
    remaining = purchased - used_to_date
    runout_date = ""
    if avg_daily > 0 and remaining > 0:
        runout_date = (min(today, contract_end) + timedelta(days=int(remaining / avg_daily))).isoformat()

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Purchased", format_credits(purchased))
    k2.metric("Used To Date", format_credits(used_to_date), f"${used_to_date * credit_price:,.0f}")
    k3.metric("Remaining", format_credits(max(remaining, 0)))
    k4.metric("Projected Annual", format_credits(projected), f"{projected - purchased:+,.0f}")
    k5.metric("Runway", runout_date or "Full term")

    planned = pd.DataFrame({
        "USAGE_DATE": pd.date_range(contract_start, contract_end, freq="D"),
    })
    planned["PLANNED_CREDITS"] = purchased * ((planned.index + 1) / contract_days)
    chart_df = df.merge(planned, on="USAGE_DATE", how="left")

    actual = alt.Chart(chart_df).mark_area(opacity=0.35, color="#38bdf8").encode(
        x=alt.X("USAGE_DATE:T", title=None),
        y=alt.Y("CUMULATIVE_CREDITS:Q", title="Credits"),
        tooltip=["USAGE_DATE:T", "CUMULATIVE_CREDITS:Q", "CREDITS_USED:Q"],
    )
    target = alt.Chart(chart_df).mark_line(color="#f59e0b", strokeDash=[6, 4]).encode(
        x="USAGE_DATE:T",
        y="PLANNED_CREDITS:Q",
        tooltip=["USAGE_DATE:T", "PLANNED_CREDITS:Q"],
    )
    st.altair_chart((actual + target).properties(height=340), use_container_width=True)

    if projected > purchased:
        st.warning(f"Projected overage is {projected - purchased:,.0f} credits at current run-rate.")
        if st.button("Send contract risk to Action Queue", key="contract_queue"):
            _queue_contract_risk(session, projected, purchased, runout_date)
    else:
        st.success("Current run-rate is within the purchased credit commitment.")

    st.subheader("Daily Credit Burn")
    daily = alt.Chart(df).mark_bar(color="#818cf8").encode(
        x=alt.X("USAGE_DATE:T", title=None),
        y=alt.Y("CREDITS_USED:Q", title="Daily Credits"),
        tooltip=["USAGE_DATE:T", "CREDITS_USED:Q", "COMPUTE_CREDITS:Q", "CLOUD_SERVICE_CREDITS:Q", "ACTIVE_WAREHOUSES:Q"],
    ).properties(height=260)
    st.altair_chart(daily, use_container_width=True)
    st.dataframe(df, use_container_width=True, height=300)
    download_csv(df, "credit_contract_daily_burn.csv")
