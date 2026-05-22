# sections/spcs_tracker.py — Snowpark Container Services cost tracking
import streamlit as st
import pandas as pd
from utils import get_session, normalize_df, format_credits, credits_to_dollars, download_csv, render_drillable_bar_chart


def render():
    session = get_session()
    credit_price = st.session_state.get("credit_price", 3.00)

    st.header("🐳 SPCS Cost Tracker")
    st.caption("Snowpark Container Services credit usage and cost breakdown.")

    spcs_days = st.slider("Lookback (days)", 1, 90, 30, key="spcs_days")

    if st.button("Load SPCS Data", key="spcs_load"):
        try:
            df_spcs = normalize_df(session.sql(f"""
                SELECT compute_pool_name,
                       DATE_TRUNC('day', start_time) AS usage_date,
                       SUM(credits_used)             AS daily_credits,
                       COUNT(*)                      AS service_count
                FROM SNOWFLAKE.ACCOUNT_USAGE.SNOWPARK_CONTAINER_SERVICES_HISTORY
                WHERE start_time >= DATEADD('day', -{spcs_days}, CURRENT_TIMESTAMP())
                GROUP BY compute_pool_name, usage_date
                ORDER BY usage_date DESC, daily_credits DESC
            """).to_pandas())
            st.session_state["spcs_df_spcs"] = df_spcs
        except Exception as e:
            st.warning(f"SPCS history unavailable: {e}. Requires SPCS configured in your account.")
            st.session_state["spcs_df_spcs"] = pd.DataFrame()

    if st.session_state.get("spcs_df_spcs") is not None and not st.session_state["spcs_df_spcs"].empty:
        df_s = st.session_state["spcs_df_spcs"]
        total_cr = df_s["DAILY_CREDITS"].sum()
        c1, c2, c3 = st.columns(3)
        c1.metric("Compute Pools Active", df_s["COMPUTE_POOL_NAME"].nunique())
        c2.metric("Total SPCS Credits",   format_credits(total_cr))
        c3.metric("Total Cost",           f"${credits_to_dollars(total_cr, credit_price):,.2f}")

        # By pool
        pool_agg = df_s.groupby("COMPUTE_POOL_NAME")["DAILY_CREDITS"].sum().reset_index().sort_values("DAILY_CREDITS", ascending=False)
        pool_agg["COST"] = pool_agg["DAILY_CREDITS"].apply(lambda x: f"${credits_to_dollars(x, credit_price):,.2f}")
        st.subheader("Credits by Compute Pool")
        render_drillable_bar_chart(
            pool_agg,
            dimension="COMPUTE_POOL_NAME",
            measure="DAILY_CREDITS",
            key="spcs_pool_credits",
            drilldown_column="query_tag",
            lookback_hours=spcs_days * 24,
        )
        st.dataframe(pool_agg, use_container_width=True)

        # Daily trend
        st.subheader("Daily Trend")
        daily = df_s.groupby("USAGE_DATE")["DAILY_CREDITS"].sum().reset_index()
        st.area_chart(daily.set_index("USAGE_DATE")["DAILY_CREDITS"])

        download_csv(df_s, "spcs_usage.csv")
    elif st.session_state.get("spcs_df_spcs") is not None:
        st.info("No SPCS usage data found in the selected period.")
