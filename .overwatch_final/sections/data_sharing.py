# sections/data_sharing.py — Data transfer credits, shared databases
import streamlit as st
from utils import (
    get_active_company,
    get_db_filter_clause,
    get_session,
    format_credits,
    credits_to_dollars,
    download_csv,
    format_snowflake_error,
    run_query,
)
from utils.workflows import render_priority_dataframe


def render():
    session = get_session()
    credit_price = st.session_state.get("credit_price", 3.00)
    company = get_active_company()

    st.header("🌐 Data Sharing Monitor")
    st.caption("DATA_TRANSFER_HISTORY credit consumption and shared database visibility.")

    ds_days = st.slider("Lookback (days)", 1, 90, 30, key="ds_days")

    c1, c2 = st.columns(2)
    with c1:
        if company != "ALL":
            st.info(
                "Data transfer history is account-level in Snowflake and does not expose "
                "a reliable ALFA/Trexis ownership column. Switch Company View to ALL for transfer costs."
            )
        elif st.button("Load Transfer History", key="ds_load"):
            try:
                df_dt = run_query(f"""
                    SELECT source_cloud, source_region,
                           target_cloud, target_region,
                           DATE_TRUNC('day', start_time) AS day,
                           SUM(bytes_transferred)/POWER(1024,3) AS gb_transferred,
                           SUM(credits_used)                    AS credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.DATA_TRANSFER_HISTORY
                    WHERE start_time >= DATEADD('day', -{ds_days}, CURRENT_TIMESTAMP())
                    GROUP BY source_cloud, source_region, target_cloud, target_region, day
                    ORDER BY credits DESC
                """, ttl_key=f"data_sharing_transfer_{company}_{ds_days}", tier="standard")
                st.session_state["ds_df_dt"] = df_dt
            except Exception as e:
                st.warning(f"Data-share usage unavailable in this role/context: {format_snowflake_error(e)}")

    with c2:
        if st.button("Load Shared Databases", key="ds_db_load"):
            try:
                df_db = run_query(f"""
                    SELECT database_name, database_id, type,
                           created, last_altered,
                           comment
                    FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASES
                    WHERE type IN ('IMPORTED DATABASE', 'SHARE')
                      {get_db_filter_clause("database_name")}
                    ORDER BY created DESC
                """, ttl_key=f"data_sharing_databases_{company}", tier="standard")
                st.session_state["ds_df_shared_db"] = df_db
            except Exception as e:
                st.warning(f"Data-share metadata unavailable in this role/context: {format_snowflake_error(e)}")

    if st.session_state.get("ds_df_dt") is not None and not st.session_state["ds_df_dt"].empty:
        df_d = st.session_state["ds_df_dt"]
        total_cr = df_d["CREDITS"].sum()
        total_gb = df_d["GB_TRANSFERRED"].sum()
        c1, c2, c3 = st.columns(3)
        c1.metric("Total GB Transferred", f"{total_gb:,.1f}")
        c2.metric("Transfer Credits",     format_credits(total_cr))
        c3.metric("Transfer Cost",        f"${credits_to_dollars(total_cr, credit_price):,.2f}")
        st.subheader("Daily Transfer Trend")
        daily = df_d.groupby("DAY")[["GB_TRANSFERRED","CREDITS"]].sum().reset_index()
        st.line_chart(daily.set_index("DAY"))
        render_priority_dataframe(
            df_d,
            title="Data transfer cost drivers",
            priority_columns=[
                "SOURCE_CLOUD", "SOURCE_REGION", "TARGET_CLOUD", "TARGET_REGION",
                "DAY", "GB_TRANSFERRED", "CREDITS",
            ],
            sort_by=["CREDITS", "GB_TRANSFERRED"],
            ascending=[False, False],
            raw_label="All data transfer rows",
        )
        download_csv(df_d, "data_transfer_history.csv")

    if st.session_state.get("ds_df_shared_db") is not None and not st.session_state["ds_df_shared_db"].empty:
        df_shared = st.session_state["ds_df_shared_db"]
        st.subheader("Shared / Imported Databases")
        render_priority_dataframe(
            df_shared,
            title="Shared/imported databases",
            priority_columns=["DATABASE_NAME", "TYPE", "CREATED", "LAST_ALTERED", "COMMENT"],
            sort_by=["LAST_ALTERED", "CREATED"],
            ascending=[False, False],
            raw_label="All shared database rows",
        )
        download_csv(df_shared, "shared_databases.csv")
