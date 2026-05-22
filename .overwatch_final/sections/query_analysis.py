# sections/query_analysis.py — Bottlenecks, plan steps, pattern degradation, AI diagnosis
import streamlit as st
import pandas as pd
from utils import (
    get_session, run_query, normalize_df, safe_sql,
    format_credits, credits_to_dollars, download_csv,
    render_query_drilldown, build_metered_credit_cte, get_wh_filter_clause,
)
from config import THRESHOLDS


def render():
    session = get_session()
    credit_price = st.session_state.get("credit_price", 3.00)

    tab_bottleneck, tab_patterns, tab_plansteps, tab_ai = st.tabs([
        "Bottlenecks", "Pattern Degradation", "Plan Steps", "AI Diagnosis"
    ])

    # ── BOTTLENECKS ───────────────────────────────────────────────────────────
    with tab_bottleneck:
        st.header("🔍 Query Bottleneck Analysis")
        days = st.slider("Lookback (days)", 1, 30, 7, key="qa_days")

        if st.button("Load Bottlenecks", key="qa_load"):
            try:
                df_qa = normalize_df(session.sql(f"""
                WITH {build_metered_credit_cte(days_back=days)}
                SELECT
                    q.query_id,
                    q.user_name,
                    q.warehouse_name,
                    q.warehouse_size,
                    q.execution_status,
                    q.start_time,
                    q.total_elapsed_time/1000             AS elapsed_sec,
                    q.compilation_time/1000               AS compile_sec,
                    q.execution_time/1000                 AS exec_sec,
                    q.queued_overload_time/1000            AS queued_sec,
                    q.bytes_scanned/POWER(1024,3)          AS gb_scanned,
                    q.bytes_spilled_to_remote_storage/POWER(1024,3) AS remote_spill_gb,
                    q.partitions_scanned * 100.0 / NULLIF(q.partitions_total,0) AS partition_pct,
                    q.rows_produced,
                    COALESCE(pqc.metered_credits, 0)       AS metered_credits,
                    SUBSTR(q.query_text,1,500)             AS query_text
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND q.warehouse_name IS NOT NULL
                  {get_wh_filter_clause("q.warehouse_name")}
                  AND q.total_elapsed_time > {THRESHOLDS['query_duration_alert_sec'] * 1000}
                ORDER BY q.total_elapsed_time DESC
                LIMIT 500
                """).to_pandas())
                st.session_state["qa_df_qa"] = df_qa
            except Exception as e:
                st.error(f"Error: {e}")

        if st.session_state.get("qa_df_qa") is not None and not st.session_state["qa_df_qa"].empty:
            df = st.session_state["qa_df_qa"]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Slow Queries", f"{len(df):,}")
            c2.metric("Avg Elapsed (s)", f"{df['ELAPSED_SEC'].mean():.1f}")
            c3.metric("Total Remote Spill", f"{df['REMOTE_SPILL_GB'].sum():.1f} GB")
            c4.metric("Total Credits", format_credits(df["METERED_CREDITS"].sum()))

            # Flag high-impact queries
            flagged = df[
                (df["REMOTE_SPILL_GB"] > THRESHOLDS["spill_warning_gb"]) |
                (df["PARTITION_PCT"] > THRESHOLDS["partition_scan_warning_pct"]) |
                (df["QUEUED_SEC"] > 30)
            ]
            if not flagged.empty:
                st.warning(f"⚠️ {len(flagged)} queries with spill, full-scan, or heavy queue time.")

            render_query_drilldown(df, key="qa_bottleneck")
            download_csv(df, "bottleneck_queries.csv")

    # ── PATTERN DEGRADATION ───────────────────────────────────────────────────
    with tab_patterns:
        st.header("📉 Query Pattern Degradation")
        st.caption("Compare query execution time this week vs prior week by query signature.")

        if st.button("Detect Degradation", key="deg_load"):
            try:
                df_deg = normalize_df(session.sql(f"""
                WITH sig_recent AS (
                    SELECT SUBSTR(query_text,1,200) AS sig,
                           AVG(total_elapsed_time)/1000 AS avg_sec,
                           COUNT(*) AS cnt
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day',-7,CURRENT_TIMESTAMP())
                      AND warehouse_name IS NOT NULL
                      {get_wh_filter_clause("warehouse_name")}
                    GROUP BY sig HAVING cnt >= 5
                ),
                sig_prior AS (
                    SELECT SUBSTR(query_text,1,200) AS sig,
                           AVG(total_elapsed_time)/1000 AS avg_sec,
                           COUNT(*) AS cnt
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day',-14,CURRENT_TIMESTAMP())
                      AND start_time <  DATEADD('day',-7,CURRENT_TIMESTAMP())
                      AND warehouse_name IS NOT NULL
                      {get_wh_filter_clause("warehouse_name")}
                    GROUP BY sig HAVING cnt >= 5
                )
                SELECT r.sig, r.avg_sec AS recent_sec, p.avg_sec AS prior_sec,
                       ROUND((r.avg_sec - p.avg_sec)/NULLIF(p.avg_sec,0)*100, 1) AS pct_change
                FROM sig_recent r
                JOIN sig_prior p ON r.sig = p.sig
                WHERE r.avg_sec > p.avg_sec * 1.25
                  AND r.avg_sec > 5
                ORDER BY pct_change DESC LIMIT 50
                """).to_pandas())
                st.session_state["qa_df_deg"] = df_deg
            except Exception as e:
                st.error(f"Error: {e}")

        if st.session_state.get("qa_df_deg") is not None:
            df_d = st.session_state["qa_df_deg"]
            if not df_d.empty:
                st.warning(f"⚠️ {len(df_d)} query patterns degraded >25% vs prior week.")
                st.dataframe(df_d, use_container_width=True)
                download_csv(df_d, "pattern_degradation.csv")
            else:
                st.success("✅ No significant query pattern degradation detected.")

    # ── PLAN STEPS ────────────────────────────────────────────────────────────
    with tab_plansteps:
        st.header("🗂️ Query Plan Steps (GET_QUERY_OPERATOR_STATS)")
        st.caption("Enter a Query ID to inspect operator-level statistics.")

        qid_input = st.text_input("Query ID", key="planstep_qid")
        if qid_input and st.button("Load Plan Steps", key="planstep_load"):
            try:
                df_ops = session.sql(
                    f"SELECT * FROM TABLE(GET_QUERY_OPERATOR_STATS('{safe_sql(qid_input)}'))"
                ).to_pandas()
                st.dataframe(normalize_df(df_ops), use_container_width=True)
                download_csv(normalize_df(df_ops), f"plan_steps_{qid_input}.csv")
            except Exception as e:
                st.warning(f"Operator stats unavailable: {e}")

    # ── AI DIAGNOSIS ──────────────────────────────────────────────────────────
    with tab_ai:
        st.header("🤖 AI Query Diagnosis (Cortex)")
        st.caption("Paste a slow query to get AI-powered optimization recommendations.")

        query_text = st.text_area("SQL to diagnose", height=200, key="ai_query_text")
        wh_ctx     = st.text_input("Warehouse (optional context)", key="ai_wh_ctx")

        if query_text and st.button("Diagnose with AI", key="ai_diagnose"):
            with st.spinner("Running Cortex analysis..."):
                try:
                    prompt = f"""You are a Snowflake performance expert. Analyze this SQL query and provide:
1. Top 3 performance issues (spill, full-scan, missing clustering, etc.)
2. Concrete optimization recommendations with Snowflake syntax
3. Estimated impact of each fix
Warehouse context: {wh_ctx or 'unknown'}
Query:
{query_text[:3000]}
Be concise, technical, Snowflake-specific."""
                    prompt_escaped = prompt.replace("'", "''")
                    result = session.sql(
                        f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', '{prompt_escaped}') AS answer"
                    ).collect()
                    st.markdown(result[0]["ANSWER"])
                except Exception as e:
                    st.info(f"Cortex AI unavailable ({e}). Ensure Cortex functions are enabled in your account.")
