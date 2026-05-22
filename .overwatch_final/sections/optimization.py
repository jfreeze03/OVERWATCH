# sections/optimization.py — Idle costs, duplicate queries, right-sizing advisor
import streamlit as st
import pandas as pd
from utils import (
    get_session, normalize_df, format_credits, credits_to_dollars, download_csv,
    render_drillable_bar_chart, get_wh_filter_clause,
)
from config import THRESHOLDS


def render():
    session = get_session()
    credit_price = st.session_state.get("credit_price", 3.00)

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
                df_idle = normalize_df(session.sql(f"""
                WITH metering AS (
                    SELECT warehouse_name,
                           DATE_TRUNC('hour', start_time) AS hour_bucket,
                           SUM(credits_used) AS hourly_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                    WHERE start_time >= DATEADD('day', -{idle_days}, CURRENT_TIMESTAMP())
                      AND start_time <  DATEADD('hour', -24, CURRENT_TIMESTAMP())
                      {get_wh_filter_clause("warehouse_name")}
                    GROUP BY warehouse_name, hour_bucket
                ),
                query_activity AS (
                    SELECT warehouse_name,
                           MAX(warehouse_size) AS warehouse_size,
                           DATE_TRUNC('hour', start_time) AS hour_bucket,
                           COUNT(*) AS query_count
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day', -{idle_days}, CURRENT_TIMESTAMP())
                      AND warehouse_name IS NOT NULL
                      {get_wh_filter_clause("warehouse_name")}
                    GROUP BY warehouse_name, hour_bucket
                )
                SELECT m.warehouse_name,
                       MAX(qa.warehouse_size) AS warehouse_size,
                       SUM(m.hourly_credits) AS idle_credits,
                       COUNT(*)              AS idle_hours
                FROM metering m
                LEFT JOIN query_activity qa
                  ON m.warehouse_name = qa.warehouse_name
                 AND m.hour_bucket    = qa.hour_bucket
                WHERE COALESCE(qa.query_count, 0) = 0
                GROUP BY m.warehouse_name
                HAVING idle_credits > {THRESHOLDS['idle_credit_waste_min']}
                ORDER BY idle_credits DESC
                """).to_pandas())
                st.session_state["opt_df_idle"] = df_idle
            except Exception as e:
                st.error(f"Error: {e}")

        if st.session_state.get("opt_df_idle") is not None and not st.session_state["opt_df_idle"].empty:
            df_i = st.session_state["opt_df_idle"]
            total_idle = df_i["IDLE_CREDITS"].sum()
            c1, c2, c3 = st.columns(3)
            c1.metric("Warehouses Wasting", len(df_i))
            c2.metric("Total Idle Credits", format_credits(total_idle))
            c3.metric("Idle Cost",          f"${credits_to_dollars(total_idle, credit_price):,.2f}")
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
                df_dup = normalize_df(session.sql(f"""
                    SELECT SUBSTR(query_text,1,200) AS query_sig,
                           COUNT(DISTINCT user_name) AS user_count,
                           COUNT(*)                  AS execution_count,
                           SUM(total_elapsed_time)/1000/COUNT(*) AS avg_elapsed_sec,
                           SUM(total_elapsed_time)/1000          AS total_wasted_sec,
                           SUM(credits_used_cloud_services)      AS cloud_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day', -{dup_days}, CURRENT_TIMESTAMP())
                      AND execution_status = 'SUCCESS'
                      AND warehouse_name IS NOT NULL
                      {get_wh_filter_clause("warehouse_name")}
                    GROUP BY query_sig
                    HAVING COUNT(*) >= 5
                    ORDER BY execution_count DESC
                    LIMIT 100
                """).to_pandas())
                st.session_state["opt_df_dup"] = df_dup
            except Exception as e:
                st.error(f"Error: {e}")

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
                df_sz = normalize_df(session.sql(f"""
                    SELECT q.warehouse_name,
                           q.warehouse_size,
                           COUNT(*)                                AS total_queries,
                           AVG(q.queued_overload_time)/1000        AS avg_queue_sec,
                           SUM(q.bytes_spilled_to_remote_storage)/POWER(1024,3) AS remote_spill_gb,
                           AVG(q.percentage_scanned_from_cache)    AS avg_cache_pct,
                           SUM(m.credits_used)                     AS total_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY m
                      ON q.warehouse_name = m.warehouse_name
                     AND DATE_TRUNC('hour', q.start_time) = DATE_TRUNC('hour', m.start_time)
                    WHERE q.start_time >= DATEADD('day', -{sz_days}, CURRENT_TIMESTAMP())
                      AND q.warehouse_name IS NOT NULL
                      {get_wh_filter_clause("q.warehouse_name")}
                    GROUP BY q.warehouse_name, q.warehouse_size
                    ORDER BY total_credits DESC
                """).to_pandas())
                st.session_state["opt_df_sz"] = df_sz
            except Exception as e:
                st.error(f"Error: {e}")

        if st.session_state.get("opt_df_sz") is not None and not st.session_state["opt_df_sz"].empty:
            df_s = st.session_state["opt_df_sz"]
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
