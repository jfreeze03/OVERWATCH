# sections/spcs_tracker.py - Snowpark Container Services cost tracking
import streamlit as st
import pandas as pd
from config import DEFAULTS
from sections.shell_helpers import render_shell_snapshot
from sections.chart_helpers import render_area_time_series_chart, render_ranked_bar_chart
from utils import (
    day_window_selectbox,
    format_snowflake_error,
    get_active_company,
    format_credits,
    credits_to_dollars,
    download_csv,
    render_chart_with_data_toggle,
    run_query,
)


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
    credit_price = st.session_state.get("credit_price", DEFAULTS["credit_price"])
    company = get_active_company()

    st.subheader("SPCS Cost Tracker")
    st.caption("Snowpark Container Services credit usage and cost breakdown.")

    spcs_days = day_window_selectbox("Lookback", key="spcs_days", default=30)

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
        render_shell_snapshot((
            ("Compute Pools Active", f"{df_s['COMPUTE_POOL_NAME'].nunique():,}"),
            ("Total SPCS Credits", format_credits(total_cr)),
            ("Total Cost", f"${credits_to_dollars(total_cr, credit_price):,.2f}"),
            ("Service Events", f"{int(df_s['SERVICE_COUNT'].sum()):,}"),
        ))

        pool_agg = df_s.groupby("COMPUTE_POOL_NAME")["DAILY_CREDITS"].sum().reset_index().sort_values("DAILY_CREDITS", ascending=False)
        pool_agg["COST_USD"] = pool_agg["DAILY_CREDITS"].apply(lambda x: credits_to_dollars(x, credit_price))
        pool_agg["AVG_DAILY_CREDITS"] = pool_agg["DAILY_CREDITS"] / max(1, int(spcs_days))
        last_seen = df_s.groupby("COMPUTE_POOL_NAME")["LAST_SEEN_AT"].max().reset_index()
        pool_agg = pool_agg.merge(last_seen, on="COMPUTE_POOL_NAME", how="left")
        render_chart_with_data_toggle(
            "Credits by Compute Pool",
            "spcs_credits_by_pool",
            lambda: render_ranked_bar_chart(pool_agg, "COMPUTE_POOL_NAME", "DAILY_CREDITS"),
            pool_agg,
            priority_columns=["COMPUTE_POOL_NAME", "DAILY_CREDITS", "COST_USD", "AVG_DAILY_CREDITS", "LAST_SEEN_AT"],
            sort_by=["DAILY_CREDITS"],
            ascending=False,
            raw_label="All compute pool cost rows",
        )

        daily = df_s.groupby("USAGE_DATE")["DAILY_CREDITS"].sum().reset_index()
        daily["DAILY_COST_USD"] = daily["DAILY_CREDITS"].apply(lambda x: credits_to_dollars(x, credit_price))
        render_chart_with_data_toggle(
            "Daily Trend",
            "spcs_daily_trend",
            lambda: render_area_time_series_chart(daily, "USAGE_DATE", "DAILY_CREDITS"),
            daily,
            priority_columns=["USAGE_DATE", "DAILY_CREDITS", "DAILY_COST_USD"],
            sort_by=["USAGE_DATE"],
            ascending=True,
            max_rows=90,
            raw_label="All SPCS daily trend rows",
        )

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
