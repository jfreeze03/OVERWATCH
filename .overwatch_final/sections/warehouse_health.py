# sections/warehouse_health.py — Warehouse stats, scaling events, idle detection, spill, heatmap
import streamlit as st
import pandas as pd
from utils import (
    get_session, format_credits, credits_to_dollars,
    download_csv, render_drillable_bar_chart, get_wh_filter_clause,
    get_active_company, get_global_filter_clause,
    build_metered_credit_cte, build_action_queue_ddl, make_action_id, upsert_actions,
    run_query,
)
from config import THRESHOLDS


def _queue_efficiency_findings(session, df_eff: pd.DataFrame) -> None:
    if df_eff is None or df_eff.empty:
        st.info("No efficiency findings to queue.")
        return
    company = st.session_state.get("active_company", "ALFA")
    actions = []
    for _, row in df_eff[df_eff["EFFICIENCY_SCORE"] < 70].head(100).iterrows():
        wh = str(row.get("WAREHOUSE_NAME", ""))
        score = float(row.get("EFFICIENCY_SCORE", 0) or 0)
        queue = float(row.get("QUEUE_SEC_PER_CREDIT", 0) or 0)
        spill = float(row.get("REMOTE_SPILL_GB_PER_CREDIT", 0) or 0)
        credits = float(row.get("METERED_CREDITS", 0) or 0)
        severity = "High" if score < 50 or queue > 10 or spill > 5 else "Medium"
        finding = f"{wh} efficiency score is {score:.1f}; queue sec/credit={queue:.2f}, spill GB/credit={spill:.2f}"
        actions.append({
            "Action ID": make_action_id("Warehouse Efficiency", wh, finding),
            "Source": "Warehouse Health - Efficiency",
            "Severity": severity,
            "Category": "Performance",
            "Entity Type": "Warehouse",
            "Entity": wh,
            "Owner": "DBA",
            "Finding": finding,
            "Action": "Review queue, spill, cache, and credit/query patterns; tune size, clustering, workload routing, or query design.",
            "Estimated Monthly Savings": 0.0,
            "Generated SQL Fix": f"-- Review {wh}. If queue dominates, consider multi-cluster or larger size. If spill dominates, inspect top spilling queries.",
            "Proof Query": f"Warehouse efficiency scorecard over recent query history; metered credits={credits:.2f}.",
            "Company": company,
        })
    if not actions:
        st.success("No warehouses below the queue threshold.")
        return
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} warehouse efficiency findings to the action queue.")
    except Exception as e:
        st.error(f"Could not save to action queue: {e}")
        st.download_button(
            "Download Action Queue DDL",
            build_action_queue_ddl(),
            file_name="overwatch_action_queue_setup.sql",
            mime="text/plain",
            key="wh_eff_queue_ddl",
        )


def render():
    session = get_session()
    credit_price = st.session_state.get("credit_price", 3.00)
    company = get_active_company()
    wh_query_filters = get_global_filter_clause(
        date_col="q.start_time",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
    )
    wh_plain_filters = get_global_filter_clause(
        date_col="start_time",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
    )

    tab_overview, tab_efficiency, tab_spill, tab_heatmap, tab_optimization = st.tabs([
        "Overview & Scaling", "Efficiency", "Spill & Memory", "Workload Heatmap", "Optimization Advisor"
    ])

    # ── OVERVIEW ──────────────────────────────────────────────────────────────
    with tab_overview:
        st.header("🏭 Warehouse Health Overview")
        wh_days = st.slider("Lookback (days)", 1, 30, 7, key="wh_days")

        if st.button("Load Warehouse Data", key="wh_load"):
            try:
                df_w = run_query(f"""
                    SELECT q.warehouse_name,
                           MAX(q.warehouse_size) AS warehouse_size,
                           COUNT(*)                            AS total_queries,
                           AVG(q.total_elapsed_time)/1000      AS avg_elapsed_sec,
                           PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY q.total_elapsed_time)/1000 AS p95_elapsed_sec,
                           AVG(q.queued_overload_time)/1000    AS avg_queued_sec,
                           SUM(q.bytes_spilled_to_remote_storage)/POWER(1024,3)  AS total_remote_spill_gb,
                           AVG(q.percentage_scanned_from_cache) AS avg_cache_pct,
                           SUM(CASE WHEN q.execution_status='FAILED_WITH_ERROR' THEN 1 ELSE 0 END) AS error_count,
                           SUM(q.bytes_scanned)/POWER(1024,3)  AS total_gb_scanned
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    WHERE q.start_time >= DATEADD('day', -{wh_days}, CURRENT_TIMESTAMP())
                      AND q.warehouse_name IS NOT NULL
                      {wh_query_filters}
                    GROUP BY q.warehouse_name
                    ORDER BY total_queries DESC
                """, ttl_key=f"wh_overview_{company}_{wh_days}", tier="historical")
                st.session_state["wh_df_wh"] = df_w
            except Exception as e:
                st.warning(f"Warehouse overview unavailable in this role/context: {e}")

        if st.session_state.get("wh_df_wh") is not None and not st.session_state["wh_df_wh"].empty:
            df_w = st.session_state["wh_df_wh"]

            c1, c2, c3 = st.columns(3)
            c1.metric("Warehouses Active", len(df_w))
            c2.metric("Total Queries",     f"{int(df_w['TOTAL_QUERIES'].sum()):,}")
            c3.metric("Total Remote Spill", f"{df_w['TOTAL_REMOTE_SPILL_GB'].sum():.1f} GB")

            # Flag warehouses needing attention
            for _, row in df_w.iterrows():
                issues = []
                if row.get("AVG_QUEUED_SEC", 0) > 2:
                    issues.append(f"Queue avg {row['AVG_QUEUED_SEC']:.1f}s — consider multi-cluster or upsize")
                if row.get("TOTAL_REMOTE_SPILL_GB", 0) > THRESHOLDS["spill_warning_gb"]:
                    issues.append(f"Remote spill {row['TOTAL_REMOTE_SPILL_GB']:.1f} GB — upsize")
                if issues:
                    st.warning(f"**{row['WAREHOUSE_NAME']}** ({row.get('WAREHOUSE_SIZE','')}): {' | '.join(issues)}")

            st.dataframe(df_w, use_container_width=True)

            # Cache efficiency chart
            st.subheader("Cache Hit % by Warehouse")
            render_drillable_bar_chart(
                df_w,
                dimension="WAREHOUSE_NAME",
                measure="AVG_CACHE_PCT",
                key="wh_cache_pct",
                drilldown_column="warehouse_name",
                lookback_hours=wh_days * 24,
            )

            download_csv(df_w, "warehouse_health.csv")

            # Scaling events
            st.divider()
            st.subheader("Scaling Events (WAREHOUSE_METERING_HISTORY)")
            if st.button("Load Scaling Events", key="wh_scale_load"):
                try:
                    df_scale = run_query(f"""
                        WITH latest_size AS (
                            SELECT warehouse_name, warehouse_size
                            FROM (
                                SELECT q.warehouse_name, q.warehouse_size,
                                       ROW_NUMBER() OVER (PARTITION BY q.warehouse_name ORDER BY q.start_time DESC) AS rn
                                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                                WHERE q.start_time >= DATEADD('day', -{wh_days}, CURRENT_TIMESTAMP())
                                  AND q.warehouse_name IS NOT NULL
                                  {wh_query_filters}
                            )
                            WHERE rn = 1
                        )
                        SELECT m.warehouse_name, ls.warehouse_size, m.start_time, m.end_time,
                               m.credits_used, m.credits_used_compute,
                               m.credits_used_cloud_services
                        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY m
                        LEFT JOIN latest_size ls ON m.warehouse_name = ls.warehouse_name
                        WHERE m.start_time >= DATEADD('day', -{wh_days}, CURRENT_TIMESTAMP())
                          {get_wh_filter_clause("m.warehouse_name")}
                        ORDER BY m.credits_used DESC LIMIT 200
                    """, ttl_key=f"wh_scaling_{company}_{wh_days}", tier="historical")
                    st.dataframe(df_scale, use_container_width=True)
                    download_csv(df_scale, "scaling_events.csv")
                except Exception as e:
                    st.warning(f"Scaling events unavailable in this role/context: {e}")

    with tab_efficiency:
        st.header("Warehouse Efficiency Scorecard")
        eff_days = st.slider("Lookback (days)", 1, 30, 7, key="wh_eff_days")
        if st.button("Load Efficiency Metrics", key="wh_eff_load"):
            try:
                df_eff = run_query(f"""
                    WITH {build_metered_credit_cte(days_back=eff_days, include_recent=True)}
                    SELECT q.warehouse_name,
                           MAX(q.warehouse_size) AS warehouse_size,
                           COUNT(*) AS query_count,
                           ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS metered_credits,
                           ROUND(SUM(COALESCE(pqc.metered_credits, 0)) / NULLIF(COUNT(*), 0), 6) AS credits_per_query,
                           ROUND(SUM(q.queued_overload_time) / 1000 / NULLIF(SUM(COALESCE(pqc.metered_credits, 0)), 0), 2) AS queue_sec_per_credit,
                           ROUND(SUM(q.bytes_spilled_to_remote_storage) / POWER(1024,3) / NULLIF(SUM(COALESCE(pqc.metered_credits, 0)), 0), 2) AS remote_spill_gb_per_credit,
                           ROUND(AVG(q.percentage_scanned_from_cache), 2) AS avg_cache_pct,
                           ROUND(100
                                 - LEAST(COALESCE(SUM(q.queued_overload_time) / 1000 / NULLIF(SUM(COALESCE(pqc.metered_credits, 0)), 0), 0), 25)
                                 - LEAST(COALESCE(SUM(q.bytes_spilled_to_remote_storage) / POWER(1024,3) / NULLIF(SUM(COALESCE(pqc.metered_credits, 0)), 0), 0), 25)
                                 - LEAST(COALESCE(SUM(COALESCE(pqc.metered_credits, 0)) / NULLIF(COUNT(*), 0), 0) * 10, 25),
                                 1) AS efficiency_score
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                    WHERE q.start_time >= DATEADD('day', -{eff_days}, CURRENT_TIMESTAMP())
                      AND q.warehouse_name IS NOT NULL
                      {wh_query_filters}
                    GROUP BY q.warehouse_name
                    ORDER BY efficiency_score ASC, metered_credits DESC
                    LIMIT 200
                """, ttl_key=f"wh_efficiency_{company}_{eff_days}", tier="historical")
                st.session_state["wh_efficiency"] = df_eff
            except Exception as e:
                st.warning(f"Efficiency metrics unavailable in this role/context: {e}")

        df_eff = st.session_state.get("wh_efficiency")
        if df_eff is not None and not df_eff.empty:
            low = df_eff[df_eff["EFFICIENCY_SCORE"] < 70]
            c1, c2, c3 = st.columns(3)
            c1.metric("Warehouses scored", len(df_eff))
            c2.metric("Under 70 score", len(low), delta_color="inverse")
            c3.metric("Total metered credits", format_credits(float(df_eff["METERED_CREDITS"].sum())))
            st.dataframe(df_eff, use_container_width=True)
            render_drillable_bar_chart(
                df_eff,
                dimension="WAREHOUSE_NAME",
                measure="EFFICIENCY_SCORE",
                key="wh_efficiency_score",
                drilldown_column="warehouse_name",
                lookback_hours=eff_days * 24,
            )
            download_csv(df_eff, "warehouse_efficiency.csv")
            if st.button("Save low-efficiency warehouses to Action Queue", key="wh_eff_queue"):
                _queue_efficiency_findings(session, df_eff)

    # ── SPILL ─────────────────────────────────────────────────────────────────
    with tab_spill:
        st.header("⚡ Spill & Memory Pressure")
        sp_days = st.slider("Lookback (days)", 1, 30, 7, key="sp_days")

        if st.button("Load Spill Data", key="sp_load"):
            try:
                df_sp = run_query(f"""
                    SELECT warehouse_name, MAX(warehouse_size) AS warehouse_size,
                           COUNT(*) AS spill_query_count,
                           ROUND(SUM(bytes_spilled_to_local_storage)/POWER(1024,3),2)  AS local_spill_gb,
                           ROUND(SUM(bytes_spilled_to_remote_storage)/POWER(1024,3),2) AS remote_spill_gb,
                           ROUND(AVG(total_elapsed_time)/1000,2)                       AS avg_elapsed_sec
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day', -{sp_days}, CURRENT_TIMESTAMP())
                      AND (bytes_spilled_to_local_storage > 0 OR bytes_spilled_to_remote_storage > 0)
                      AND warehouse_name IS NOT NULL
                      {wh_plain_filters}
                    GROUP BY warehouse_name
                    ORDER BY local_spill_gb + remote_spill_gb DESC
                """, ttl_key=f"wh_spill_{company}_{sp_days}", tier="historical")
                st.session_state["wh_df_sp"] = df_sp
            except Exception as e:
                st.warning(f"Spill data unavailable in this role/context: {e}")

        if st.session_state.get("wh_df_sp") is not None and not st.session_state["wh_df_sp"].empty:
            df_sp = st.session_state["wh_df_sp"]
            c1, c2, c3 = st.columns(3)
            c1.metric("Spilling Warehouses", len(df_sp))
            c2.metric("Total Local Spill",  f"{df_sp['LOCAL_SPILL_GB'].sum():.1f} GB")
            c3.metric("Total Remote Spill", f"{df_sp['REMOTE_SPILL_GB'].sum():.1f} GB")
            st.dataframe(df_sp, use_container_width=True)
            df_sp["TOTAL_SPILL_GB"] = df_sp["LOCAL_SPILL_GB"] + df_sp["REMOTE_SPILL_GB"]
            render_drillable_bar_chart(
                df_sp,
                dimension="WAREHOUSE_NAME",
                measure="TOTAL_SPILL_GB",
                key="wh_spill_total",
                drilldown_column="warehouse_name",
                lookback_hours=sp_days * 24,
            )
            for _, row in df_sp.iterrows():
                if row["REMOTE_SPILL_GB"] > 10:
                    st.error(f"**{row['WAREHOUSE_NAME']}**: {row['REMOTE_SPILL_GB']:.1f} GB remote spill — upsize immediately")
            download_csv(df_sp, "spill_report.csv")

    # ── HEATMAP ───────────────────────────────────────────────────────────────
    with tab_heatmap:
        st.header("🌡️ Workload Concurrency Heatmap")
        hm_days = st.slider("Lookback (days)", 7, 90, 30, key="hm_days")

        if st.button("Build Heatmap", key="hm_build"):
            try:
                df_hm = run_query(f"""
                    SELECT warehouse_name,
                           DAYOFWEEK(start_time) AS day_of_week,
                           HOUR(start_time)      AS hour_of_day,
                           COUNT(*)              AS query_count,
                           ROUND(AVG(total_elapsed_time)/1000,2) AS avg_elapsed_sec
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day', -{hm_days}, CURRENT_TIMESTAMP())
                      AND warehouse_name IS NOT NULL
                      {wh_plain_filters}
                    GROUP BY warehouse_name, day_of_week, hour_of_day
                    ORDER BY warehouse_name, day_of_week, hour_of_day
                """, ttl_key=f"wh_heatmap_{company}_{hm_days}", tier="historical")
                st.session_state["wh_df_hm"] = df_hm
            except Exception as e:
                st.warning(f"Workload heatmap unavailable in this role/context: {e}")

        if st.session_state.get("wh_df_hm") is not None and not st.session_state["wh_df_hm"].empty:
            df_hm = st.session_state["wh_df_hm"]
            whs = df_hm["WAREHOUSE_NAME"].unique()
            sel_wh = st.selectbox("Warehouse", whs, key="hm_wh_sel")

            if sel_wh:
                wh_data = df_hm[df_hm["WAREHOUSE_NAME"] == sel_wh]
                pivot = wh_data.pivot_table(
                    index="DAY_OF_WEEK", columns="HOUR_OF_DAY",
                    values="QUERY_COUNT", aggfunc="sum"
                ).fillna(0)
                day_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
                pivot.index = pivot.index.map(lambda x: day_names.get(int(x), str(x)))
                st.subheader(f"Query Volume Heatmap — {sel_wh}")
                st.dataframe(pivot.style.background_gradient(cmap="YlOrRd"), use_container_width=True)
                c1, c2, c3 = st.columns(3)
                c1.metric("Total Queries", f"{int(wh_data['QUERY_COUNT'].sum()):,}")
                c2.metric("Peak Hour",     f"{int(pivot.max().max()):,}")
                c3.metric("Avg Elapsed",   f"{wh_data['AVG_ELAPSED_SEC'].mean():.1f}s")

    with tab_optimization:
        from sections.optimization import render as render_optimization

        render_optimization()
