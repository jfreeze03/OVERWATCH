# sections/optimization.py — shared Warehouse Health optimization advisor helpers
import streamlit as st
import pandas as pd
from utils import (
    get_session, format_credits, credits_to_dollars, download_csv,
    format_snowflake_error,
    render_drillable_bar_chart, get_active_company, get_wh_filter_clause,
    get_global_filter_clause, run_query, build_idle_warehouse_sql,
    metric_confidence_label, filter_existing_columns,
)
from config import THRESHOLDS


def render_optimization_advisor():
    session = get_session()
    credit_price = st.session_state.get("credit_price", 3.00)
    company = get_active_company()
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "CREDITS_USED_CLOUD_SERVICES",
            "QUEUED_OVERLOAD_TIME",
            "BYTES_SPILLED_TO_REMOTE_STORAGE",
            "PERCENTAGE_SCANNED_FROM_CACHE",
            "WAREHOUSE_SIZE",
        ],
    ))
    duplicate_cloud_expr = (
        "SUM(credits_used_cloud_services)"
        if "CREDITS_USED_CLOUD_SERVICES" in qh_cols
        else "0"
    )
    sizing_wh_size_expr = (
        "MAX(warehouse_size)"
        if "WAREHOUSE_SIZE" in qh_cols
        else "NULL::VARCHAR"
    )
    sizing_queue_expr = (
        "AVG(queued_overload_time) / 1000"
        if "QUEUED_OVERLOAD_TIME" in qh_cols
        else "0"
    )
    sizing_spill_expr = (
        "SUM(bytes_spilled_to_remote_storage) / POWER(1024, 3)"
        if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
        else "0"
    )
    sizing_cache_expr = (
        "AVG(percentage_scanned_from_cache)"
        if "PERCENTAGE_SCANNED_FROM_CACHE" in qh_cols
        else "0"
    )
    query_filters = get_global_filter_clause(
        date_col="start_time",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
    )

    tab_idle, tab_dups, tab_sizing = st.tabs([
        "Idle Warehouse Costs", "Duplicate Queries", "Right-Sizing Advisor"
    ])

    # ── IDLE WAREHOUSE COSTS ──────────────────────────────────────────────────
    with tab_idle:
        st.header("💤 Idle Warehouse Cost Detection")
        st.caption("Identifies credit spend during hours with zero query activity.")
        idle_days = st.slider("Lookback (days)", 1, 30, 7, key="idle_days")

        if st.button("Find Idle Credits", key="idle_load"):
            try:
                df_idle = run_query(
                    build_idle_warehouse_sql(
                        days_back=idle_days,
                        wh_filter=get_wh_filter_clause("warehouse_name"),
                        min_idle_credits=THRESHOLDS["idle_credit_waste_min"],
                    ),
                    ttl_key=f"optimization_idle_{company}_{idle_days}",
                    tier="historical",
                )
                st.session_state["opt_df_idle"] = df_idle
            except Exception as e:
                st.warning(f"Idle warehouse scan unavailable: {format_snowflake_error(e)}")

        if st.session_state.get("opt_df_idle") is not None and not st.session_state["opt_df_idle"].empty:
            df_i = st.session_state["opt_df_idle"]
            total_idle = df_i["IDLE_CREDITS"].sum()
            c1, c2, c3 = st.columns(3)
            c1.metric("Warehouses Wasting", len(df_i))
            c2.metric("Total Idle Credits", format_credits(total_idle))
            c3.metric("Idle Cost",          f"${credits_to_dollars(total_idle, credit_price):,.2f}")
            st.caption(metric_confidence_label("exact"))
            st.dataframe(df_i, use_container_width=True)
            render_drillable_bar_chart(
                df_i,
                dimension="WAREHOUSE_NAME",
                measure="IDLE_CREDITS",
                key="opt_idle_credits",
                drilldown_column="warehouse_name",
                lookback_hours=idle_days * 24,
            )
            for _, row in df_i.iterrows():
                st.warning(
                    f"**{row['WAREHOUSE_NAME']}**: {int(row['IDLE_HOURS'])} idle hours, "
                    f"{format_credits(row['IDLE_CREDITS'])} wasted — "
                    f"reduce AUTO_SUSPEND to ≤{THRESHOLDS['idle_warehouse_minutes']} min"
                )
            download_csv(df_i, "idle_warehouses.csv")
        elif st.session_state.get("opt_df_idle") is not None:
            st.success("✅ No significant idle warehouse credits detected.")

    # ── DUPLICATE QUERIES ─────────────────────────────────────────────────────
    with tab_dups:
        st.header("♻️ Duplicate & Redundant Query Detection")
        st.caption("Same query text executed multiple times within a time window — candidates for result caching or materialization.")
        dup_days = st.slider("Lookback (days)", 1, 14, 7, key="dup_days")

        if st.button("Find Duplicates", key="dup_load"):
            try:
                df_dup = run_query(f"""
                    SELECT SUBSTR(query_text,1,200) AS query_sig,
                           COUNT(DISTINCT user_name) AS user_count,
                           COUNT(*)                  AS execution_count,
                           SUM(total_elapsed_time)/1000/COUNT(*) AS avg_elapsed_sec,
                           SUM(total_elapsed_time)/1000          AS total_wasted_sec,
                           {duplicate_cloud_expr}                AS cloud_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day', -{dup_days}, CURRENT_TIMESTAMP())
                      AND execution_status = 'SUCCESS'
                      AND warehouse_name IS NOT NULL
                      {query_filters}
                    GROUP BY query_sig
                    HAVING COUNT(*) >= 5
                    ORDER BY execution_count DESC
                    LIMIT 100
                """, ttl_key=f"optimization_duplicates_{company}_{dup_days}", tier="standard")
                st.session_state["opt_df_dup"] = df_dup
            except Exception as e:
                st.warning(f"Duplicate query analysis unavailable: {format_snowflake_error(e)}")

        if st.session_state.get("opt_df_dup") is not None and not st.session_state["opt_df_dup"].empty:
            df_d = st.session_state["opt_df_dup"]
            st.metric("Duplicate Query Patterns", len(df_d))
            st.info("💡 Enable result caching (`USE_CACHED_RESULT = TRUE`) or create a materialized view for the top patterns.")
            st.dataframe(df_d, use_container_width=True)
            download_csv(df_d, "duplicate_queries.csv")

    # ── RIGHT-SIZING ADVISOR ──────────────────────────────────────────────────
    with tab_sizing:
        st.header("📐 Warehouse Right-Sizing Advisor")
        st.caption("Warehouses with low utilization or persistent spill — downsize or upsize candidates.")
        sz_days = st.slider("Lookback (days)", 7, 30, 14, key="sz_days")

        if st.button("Analyze Sizing", key="sz_load"):
            try:
                df_sz = run_query(f"""
                    WITH query_stats AS (
                        SELECT
                            warehouse_name,
                            {sizing_wh_size_expr} AS warehouse_size,
                            COUNT(*) AS total_queries,
                            {sizing_queue_expr} AS avg_queue_sec,
                            {sizing_spill_expr} AS remote_spill_gb,
                            {sizing_cache_expr} AS avg_cache_pct
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                        WHERE start_time >= DATEADD('day', -{sz_days}, CURRENT_TIMESTAMP())
                          AND warehouse_name IS NOT NULL
                          {query_filters}
                        GROUP BY warehouse_name
                    ),
                    metering AS (
                        SELECT
                            warehouse_name,
                            ROUND(SUM(credits_used), 4) AS total_credits
                        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                        WHERE start_time >= DATEADD('day', -{sz_days}, CURRENT_TIMESTAMP())
                          AND start_time <  DATEADD('hour', -24, CURRENT_TIMESTAMP())
                          {get_wh_filter_clause("warehouse_name")}
                        GROUP BY warehouse_name
                    )
                    SELECT
                        q.warehouse_name,
                        q.warehouse_size,
                        q.total_queries,
                        ROUND(q.avg_queue_sec, 2) AS avg_queue_sec,
                        ROUND(q.remote_spill_gb, 2) AS remote_spill_gb,
                        ROUND(q.avg_cache_pct, 2) AS avg_cache_pct,
                        COALESCE(m.total_credits, 0) AS total_credits
                    FROM query_stats q
                    LEFT JOIN metering m
                      ON q.warehouse_name = m.warehouse_name
                    ORDER BY total_credits DESC
                """, ttl_key=f"optimization_sizing_{company}_{sz_days}", tier="historical")
                st.session_state["opt_df_sz"] = df_sz
            except Exception as e:
                st.warning(f"Warehouse recommendation scan unavailable: {format_snowflake_error(e)}")

        if st.session_state.get("opt_df_sz") is not None and not st.session_state["opt_df_sz"].empty:
            df_s = st.session_state["opt_df_sz"]
            st.caption(metric_confidence_label("exact"))
            st.dataframe(df_s, use_container_width=True)

            st.subheader("Recommendations")
            for _, row in df_s.iterrows():
                wh   = row.get("WAREHOUSE_NAME", "")
                sz   = row.get("WAREHOUSE_SIZE", "")
                spill= float(row.get("REMOTE_SPILL_GB", 0) or 0)
                q    = float(row.get("AVG_QUEUE_SEC", 0) or 0)
                cred = float(row.get("TOTAL_CREDITS", 0) or 0)

                if spill > THRESHOLDS["spill_warning_gb"] and q > 5:
                    st.error(f"**{wh}** ({sz}): spilling + heavy queue — upsize and consider multi-cluster")
                elif spill > THRESHOLDS["spill_warning_gb"]:
                    st.warning(f"**{wh}** ({sz}): {spill:.1f} GB remote spill — upsize to reduce memory pressure")
                elif q > 5:
                    st.warning(f"**{wh}** ({sz}): avg queue {q:.1f}s — enable multi-cluster or upsize")
                elif cred < 1 and sz not in ("", "X-Small"):
                    st.info(f"**{wh}** ({sz}): very low credit usage ({cred:.2f}) — consider downsizing to X-Small")

            download_csv(df_s, "right_sizing.csv")


def render():
    """Backward-compatible entry point; navigation now routes users to Warehouse Health."""
    st.info("Optimization Advisor now lives inside Warehouse Health.")
    render_optimization_advisor()
