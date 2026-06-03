# sections/spcs_tracker.py - Snowpark Container Services cost tracking
import streamlit as st
import pandas as pd
from utils import (
    format_snowflake_error,
    get_active_company,
    format_credits,
    credits_to_dollars,
    download_csv,
    run_query,
)
from utils.workflows import render_priority_dataframe


def _spcs_pool_filter(company: str) -> str:
    if company == "Trexis":
        return "AND compute_pool_name ILIKE '%TRXS%'"
    if company == "ALFA":
        return "AND compute_pool_name NOT ILIKE '%TRXS%'"
    return ""


def _spcs_scope_meta(company: str, days: int) -> dict:
    return {"company": company, "days": int(days)}


def _load_spcs_usage(company: str, days: int, *, show_errors: bool = True) -> bool:
    try:
        pool_filter = _spcs_pool_filter(company)
        df_spcs = run_query(f"""
            SELECT compute_pool_name,
                   DATE_TRUNC('day', start_time) AS usage_date,
                   SUM(credits_used)             AS daily_credits,
                   COUNT(*)                      AS service_count,
                   MAX(end_time)                 AS last_seen_at
            FROM SNOWFLAKE.ACCOUNT_USAGE.SNOWPARK_CONTAINER_SERVICES_HISTORY
            WHERE start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
              {pool_filter}
            GROUP BY compute_pool_name, usage_date
            ORDER BY usage_date DESC, daily_credits DESC
        """, ttl_key=f"spcs_usage_{company}_{days}", tier="standard")
        st.session_state["spcs_df_spcs"] = df_spcs
        st.session_state["spcs_meta"] = _spcs_scope_meta(company, days)
        st.session_state["spcs_error"] = ""
        return True
    except Exception as exc:
        st.session_state["spcs_df_spcs"] = pd.DataFrame()
        st.session_state["spcs_meta"] = _spcs_scope_meta(company, days)
        st.session_state["spcs_error"] = format_snowflake_error(exc)
        if show_errors:
            st.warning(
                "SPCS history is not available for this role/account. "
                f"{st.session_state['spcs_error']}"
            )
        return False


def render():
    credit_price = st.session_state.get("credit_price", 3.00)
    company = get_active_company()

    st.header("SPCS Cost Tracker")
    st.caption("Snowpark Container Services credit usage and cost breakdown.")

    spcs_days = st.slider("Lookback (days)", 1, 90, 30, key="spcs_days")

    expected_meta = _spcs_scope_meta(company, spcs_days)
    current_meta = st.session_state.get("spcs_meta", {})
    if current_meta != expected_meta and not st.session_state.get(f"spcs_auto_attempted_{company}_{spcs_days}"):
        st.session_state[f"spcs_auto_attempted_{company}_{spcs_days}"] = True
        _load_spcs_usage(company, spcs_days, show_errors=False)

    if st.button("Load SPCS Data", key="spcs_load"):
        _load_spcs_usage(company, spcs_days, show_errors=True)

    if st.session_state.get("spcs_df_spcs") is not None and not st.session_state["spcs_df_spcs"].empty:
        df_s = st.session_state["spcs_df_spcs"]
        total_cr = df_s["DAILY_CREDITS"].sum()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Compute Pools Active", df_s["COMPUTE_POOL_NAME"].nunique())
        c2.metric("Total SPCS Credits", format_credits(total_cr))
        c3.metric("Total Cost", f"${credits_to_dollars(total_cr, credit_price):,.2f}")
        c4.metric("Service Events", f"{int(df_s['SERVICE_COUNT'].sum()):,}")

        pool_agg = df_s.groupby("COMPUTE_POOL_NAME")["DAILY_CREDITS"].sum().reset_index().sort_values("DAILY_CREDITS", ascending=False)
        pool_agg["COST"] = pool_agg["DAILY_CREDITS"].apply(lambda x: f"${credits_to_dollars(x, credit_price):,.2f}")
        pool_agg["AVG_DAILY_CREDITS"] = pool_agg["DAILY_CREDITS"] / max(1, int(spcs_days))
        last_seen = df_s.groupby("COMPUTE_POOL_NAME")["LAST_SEEN_AT"].max().reset_index()
        pool_agg = pool_agg.merge(last_seen, on="COMPUTE_POOL_NAME", how="left")
        st.subheader("Credits by Compute Pool")
        st.bar_chart(pool_agg.set_index("COMPUTE_POOL_NAME")["DAILY_CREDITS"])
        render_priority_dataframe(
            pool_agg,
            title="Compute pool cost drivers",
            priority_columns=["COMPUTE_POOL_NAME", "DAILY_CREDITS", "AVG_DAILY_CREDITS", "COST", "LAST_SEEN_AT"],
            sort_by=["DAILY_CREDITS"],
            ascending=False,
            raw_label="All compute pool cost rows",
        )

        st.subheader("Daily Trend")
        daily = df_s.groupby("USAGE_DATE")["DAILY_CREDITS"].sum().reset_index()
        st.area_chart(daily.set_index("USAGE_DATE")["DAILY_CREDITS"])

        download_csv(df_s, "spcs_usage.csv")
    elif st.session_state.get("spcs_df_spcs") is not None:
        err = st.session_state.get("spcs_error", "")
        if err:
            st.info(
                "No SPCS usage is visible for this scope. The active role may not have access, "
                "or Snowpark Container Services may not be enabled in this account."
            )
            st.caption(err)
        else:
            st.info("No SPCS usage data found in the selected period.")
