# sections/storage_monitor.py — Storage overview, data freshness, iceberg, egress
import streamlit as st
from utils import (
    get_active_company,
    get_db_filter_clause,
    get_session,
    metric_confidence_label,
    freshness_note,
    download_csv,
    format_snowflake_error,
    run_query,
    safe_float,
)


def render():
    session = get_session()
    credit_price = st.session_state.get("credit_price", 3.00)
    storage_cost_per_tb = st.session_state.get("storage_cost_per_tb", 23.00)
    company = get_active_company()

    st.header("🗄️ Storage Monitor")
    st.caption("Database & stage storage with cost estimates ($23/TB/month default).")

    stor_days = st.slider("Lookback (days)", 7, 180, 90, key="stor_days")

    if st.button("Load Storage Data", key="stor_load"):
        try:
            if company != "ALL":
                st.info("Stage storage is account-level in Snowflake, so this company view shows database and failsafe storage only.")
            stage_storage_cte = (
                f"""
            stage_storage AS (
                SELECT usage_date, SUM(average_stage_bytes) AS stage_bytes
                FROM SNOWFLAKE.ACCOUNT_USAGE.STAGE_STORAGE_USAGE_HISTORY
                WHERE usage_date >= DATEADD('day', -{stor_days}, CURRENT_DATE())
                GROUP BY usage_date
            )
                """
                if company == "ALL"
                else """
            stage_storage AS (
                SELECT usage_date, 0 AS stage_bytes
                FROM database_storage
            )
                """
            )
            df_stor = run_query(f"""
            WITH database_storage AS (
                SELECT usage_date,
                       SUM(average_database_bytes) AS storage_bytes,
                       SUM(average_failsafe_bytes) AS failsafe_bytes
                FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
                WHERE usage_date >= DATEADD('day', -{stor_days}, CURRENT_DATE())
                  {get_db_filter_clause("database_name")}
                GROUP BY usage_date
            ),
            {stage_storage_cte}
            SELECT COALESCE(d.usage_date, s.usage_date)        AS usage_date,
                   COALESCE(d.storage_bytes,  0)/POWER(1024,3) AS storage_gb,
                   COALESCE(d.failsafe_bytes, 0)/POWER(1024,3) AS failsafe_gb,
                   COALESCE(s.stage_bytes,    0)/POWER(1024,3) AS stage_gb,
                   (COALESCE(d.storage_bytes,0)+COALESCE(d.failsafe_bytes,0)+COALESCE(s.stage_bytes,0))
                       /POWER(1024,4)                           AS total_storage_tb
            FROM database_storage d
            FULL OUTER JOIN stage_storage s ON d.usage_date = s.usage_date
            ORDER BY usage_date
            """, ttl_key=f"storage_trend_{company}_{stor_days}", tier="historical")
            st.session_state["stor_df_stor"] = df_stor
        except Exception as e:
            st.warning(f"Storage data unavailable in this role/context: {format_snowflake_error(e)}")

    if st.session_state.get("stor_df_stor") is not None and not st.session_state["stor_df_stor"].empty:
        df_st = st.session_state["stor_df_stor"]
        latest = df_st.iloc[-1] if not df_st.empty else None

        if latest is not None:
            total_tb = safe_float(latest.get("TOTAL_STORAGE_TB", 0))
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Database GB",  f"{safe_float(latest.get('STORAGE_GB',0)):,.1f}")
            c2.metric("Failsafe GB",  f"{safe_float(latest.get('FAILSAFE_GB',0)):,.1f}")
            c3.metric("Stage GB",     f"{safe_float(latest.get('STAGE_GB',0)):,.1f}")
            c4.metric("Est Monthly Cost", f"${total_tb * storage_cost_per_tb:,.2f}")
            confidence = "account-wide" if company != "ALL" else "exact"
            st.caption(f"{metric_confidence_label(confidence)} | {freshness_note('ACCOUNT_USAGE')}")

        st.subheader("Storage Trend")
        st.area_chart(df_st.set_index("USAGE_DATE")[["STORAGE_GB","FAILSAFE_GB","STAGE_GB"]])

        # Per-database breakdown
        st.divider()
        st.subheader("Per-Database Storage")
        if st.button("Load DB Detail", key="stor_db_detail"):
            try:
                df_db = run_query(f"""
                    SELECT database_name,
                           usage_date,
                           average_database_bytes/POWER(1024,3) AS database_gb,
                           average_failsafe_bytes/POWER(1024,3) AS failsafe_gb
                    FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
                    WHERE usage_date = (SELECT MAX(usage_date)
                                        FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY)
                      {get_db_filter_clause("database_name")}
                    ORDER BY database_gb DESC
                    LIMIT 50
                """, ttl_key=f"storage_db_detail_{get_active_company()}", tier="standard")
                st.dataframe(df_db, use_container_width=True)
                download_csv(df_db, "db_storage_detail.csv")
            except Exception as e:
                st.warning(f"Large table data unavailable in this role/context: {format_snowflake_error(e)}")

        download_csv(df_st, "storage_trend.csv")

    # Table-level storage
    st.divider()
    st.subheader("🗃️ Table Storage Metrics (Top 50 by size)")
    if st.button("Load Table Metrics", key="tbl_stor_load"):
        try:
            df_tbl = run_query(f"""
                SELECT table_catalog, table_schema, table_name,
                       active_bytes/POWER(1024,3)          AS active_gb,
                       time_travel_bytes/POWER(1024,3)     AS time_travel_gb,
                       failsafe_bytes/POWER(1024,3)        AS failsafe_gb,
                       retained_for_clone_bytes/POWER(1024,3) AS clone_gb
                FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS
                WHERE (deleted IS NULL OR deleted = FALSE)
                  {get_db_filter_clause("table_catalog")}
                ORDER BY active_gb DESC
                LIMIT 50
            """, ttl_key=f"storage_table_metrics_{get_active_company()}", tier="standard")
            st.dataframe(df_tbl, use_container_width=True)
            download_csv(df_tbl, "table_storage.csv")
        except Exception as e:
            st.warning(f"Time Travel/Failsafe data unavailable in this role/context: {format_snowflake_error(e)}")
