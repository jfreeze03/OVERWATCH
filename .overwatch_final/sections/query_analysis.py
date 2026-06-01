# sections/query_analysis.py — Bottlenecks, plan steps, pattern degradation, AI diagnosis
import streamlit as st
from utils import (
    get_session, run_query, sql_literal,
    format_credits, download_csv,
    render_query_drilldown, build_metered_credit_cte, get_active_company, get_global_filter_clause,
    render_priority_dataframe,
    filter_existing_columns, format_snowflake_error,
    build_mart_query_bottleneck_sql, build_mart_query_degradation_sql,
    safe_float,
)
from config import THRESHOLDS


QUERY_ANALYSIS_PANES = (
    "Bottlenecks",
    "Pattern Degradation",
    "Plan Steps",
    "AI Diagnosis",
)


def _annotate_bottleneck_routes(df):
    if df is None or getattr(df, "empty", True):
        return df

    def _signal(row):
        if safe_float(row.get("QUEUED_SEC")) > 30:
            return "Warehouse Queue Pressure"
        if safe_float(row.get("REMOTE_SPILL_GB")) > THRESHOLDS["spill_warning_gb"]:
            return "Remote Spill"
        if safe_float(row.get("PARTITION_PCT")) > THRESHOLDS["partition_scan_warning_pct"]:
            return "Full/High Partition Scan"
        return "Slow Query"

    def _workflow(signal):
        if signal in ("Warehouse Queue Pressure", "Remote Spill"):
            return "Warehouse health"
        if signal == "Full/High Partition Scan":
            return "Change & drift"
        return "Query workbench"

    def _action(signal):
        if signal == "Warehouse Queue Pressure":
            return "Check concurrent load, queue trend, warehouse size/clusters, and task schedule overlap before resizing."
        if signal == "Remote Spill":
            return "Open operator stats, identify spill-heavy joins/sorts, and validate warehouse memory pressure before rerun."
        if signal == "Full/High Partition Scan":
            return "Inspect pruning, clustering/search optimization fit, recent object growth, and query predicates."
        return "Review query text, elapsed trend, warehouse context, and owner before tuning or escalation."

    routed = df.copy()
    routed["PRIMARY_SIGNAL"] = routed.apply(_signal, axis=1)
    routed["NEXT_WORKFLOW"] = routed["PRIMARY_SIGNAL"].apply(_workflow)
    routed["NEXT_ACTION"] = routed["PRIMARY_SIGNAL"].apply(_action)
    return routed


def _annotate_degradation_routes(df):
    if df is None or getattr(df, "empty", True):
        return df
    routed = df.copy()
    routed["PRIMARY_SIGNAL"] = "Query Pattern Regression"
    routed["NEXT_WORKFLOW"] = "Query workbench"
    routed["NEXT_ACTION"] = (
        "Compare this signature to the release/change window, inspect plans for representative query IDs, "
        "and confirm whether data volume or logic changed."
    )
    return routed


def render():
    session = get_session()
    company = get_active_company()
    qh_exprs = None

    def _query_history_exprs() -> dict[str, str]:
        nonlocal qh_exprs
        if qh_exprs is not None:
            return qh_exprs
        try:
            qh_cols = set(filter_existing_columns(
                session,
                "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                [
                    "WAREHOUSE_SIZE",
                    "QUEUED_OVERLOAD_TIME",
                    "BYTES_SCANNED",
                    "BYTES_SPILLED_TO_REMOTE_STORAGE",
                    "PARTITIONS_SCANNED",
                    "PARTITIONS_TOTAL",
                    "ROWS_PRODUCED",
                ],
            ))
        except Exception:
            qh_cols = set()
        qh_exprs = {
            "wh_size_expr": "q.warehouse_size AS warehouse_size" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size",
            "queued_expr": "q.queued_overload_time/1000 AS queued_sec" if "QUEUED_OVERLOAD_TIME" in qh_cols else "0::FLOAT AS queued_sec",
            "gb_expr": "q.bytes_scanned/POWER(1024,3) AS gb_scanned" if "BYTES_SCANNED" in qh_cols else "0::FLOAT AS gb_scanned",
            "spill_expr": (
                "q.bytes_spilled_to_remote_storage/POWER(1024,3) AS remote_spill_gb"
                if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols else "0::FLOAT AS remote_spill_gb"
            ),
            "partition_expr": (
                "q.partitions_scanned * 100.0 / NULLIF(q.partitions_total,0) AS partition_pct"
                if {"PARTITIONS_SCANNED", "PARTITIONS_TOTAL"}.issubset(qh_cols)
                else "0::FLOAT AS partition_pct"
            ),
            "rows_expr": "q.rows_produced AS rows_produced" if "ROWS_PRODUCED" in qh_cols else "0::NUMBER AS rows_produced",
        }
        return qh_exprs

    active_view = st.radio(
        "Query analysis view",
        QUERY_ANALYSIS_PANES,
        horizontal=True,
        label_visibility="collapsed",
        key="query_analysis_active_view",
    )

    # ── BOTTLENECKS ───────────────────────────────────────────────────────────
    if active_view == "Bottlenecks":
        st.header("🔍 Query Bottleneck Analysis")
        days = st.slider("Lookback (days)", 1, 30, 7, key="qa_days")
        qa_filters = get_global_filter_clause(
            date_col="q.start_time",
            wh_col="q.warehouse_name",
            user_col="q.user_name",
            role_col="q.role_name",
            db_col="q.database_name",
        )

        if st.button("Load Bottlenecks", key="qa_load"):
            try:
                try:
                    df_qa = run_query(
                        build_mart_query_bottleneck_sql(
                            days_back=days,
                            min_elapsed_ms=THRESHOLDS["query_duration_alert_sec"] * 1000,
                            company=company,
                            extra_filter=qa_filters,
                        ),
                        ttl_key=f"query_analysis_bottlenecks_mart_{company}_{days}",
                        tier="historical",
                    )
                    st.session_state["qa_bottleneck_source"] = "OVERWATCH mart: FACT_QUERY_DETAIL_RECENT"
                except Exception:
                    exprs = _query_history_exprs()
                    wh_size_expr = exprs["wh_size_expr"]
                    queued_expr = exprs["queued_expr"]
                    gb_expr = exprs["gb_expr"]
                    spill_expr = exprs["spill_expr"]
                    partition_expr = exprs["partition_expr"]
                    rows_expr = exprs["rows_expr"]
                    df_qa = run_query(f"""
                WITH {build_metered_credit_cte(days_back=days, include_recent=True)}
                SELECT
                    q.query_id,
                    q.user_name,
                    q.warehouse_name,
                    {wh_size_expr},
                    q.execution_status,
                    q.start_time,
                    q.total_elapsed_time/1000             AS elapsed_sec,
                    q.compilation_time/1000               AS compile_sec,
                    q.execution_time/1000                 AS exec_sec,
                    {queued_expr},
                    {gb_expr},
                    {spill_expr},
                    {partition_expr},
                    {rows_expr},
                    COALESCE(pqc.metered_credits, 0)       AS metered_credits,
                    SUBSTR(q.query_text,1,500)             AS query_text
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND q.warehouse_name IS NOT NULL
                  {qa_filters}
                  AND q.total_elapsed_time > {THRESHOLDS['query_duration_alert_sec'] * 1000}
                ORDER BY q.total_elapsed_time DESC
                LIMIT 500
                    """, ttl_key=f"query_analysis_bottlenecks_live_{company}_{days}", tier="standard")
                    st.session_state["qa_bottleneck_source"] = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"
                st.session_state["qa_df_qa"] = _annotate_bottleneck_routes(df_qa)
            except Exception as e:
                st.warning(f"Bottleneck data unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("qa_df_qa") is not None and not st.session_state["qa_df_qa"].empty:
            df = st.session_state["qa_df_qa"]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Slow Queries", f"{len(df):,}")
            c2.metric("Avg Elapsed (s)", f"{df['ELAPSED_SEC'].mean():.1f}")
            c3.metric("Total Remote Spill", f"{df['REMOTE_SPILL_GB'].sum():.1f} GB")
            c4.metric("Total Credits", format_credits(df["METERED_CREDITS"].sum()))
            st.caption(st.session_state.get("qa_bottleneck_source", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"))

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
    elif active_view == "Pattern Degradation":
        st.header("📉 Query Pattern Degradation")
        st.caption("Compare query execution time this week vs prior week by query signature.")

        if st.button("Detect Degradation", key="deg_load"):
            try:
                qa_filters = get_global_filter_clause(
                    date_col="q.start_time",
                    wh_col="q.warehouse_name",
                    user_col="q.user_name",
                    role_col="q.role_name",
                    db_col="q.database_name",
                )
                try:
                    df_deg = run_query(
                        build_mart_query_degradation_sql(company=company, extra_filter=qa_filters),
                        ttl_key=f"query_analysis_degradation_mart_{company}",
                        tier="historical",
                    )
                    st.session_state["qa_degradation_source"] = "OVERWATCH mart: FACT_QUERY_DETAIL_RECENT"
                except Exception:
                    df_deg = run_query(f"""
                    WITH sig_recent AS (
                        SELECT SUBSTR(q.query_text,1,200) AS sig,
                               AVG(q.total_elapsed_time)/1000 AS avg_sec,
                               COUNT(*) AS cnt
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        WHERE q.start_time >= DATEADD('day',-7,CURRENT_TIMESTAMP())
                          AND q.warehouse_name IS NOT NULL
                          {qa_filters}
                        GROUP BY sig HAVING cnt >= 5
                    ),
                    sig_prior AS (
                        SELECT SUBSTR(q.query_text,1,200) AS sig,
                               AVG(q.total_elapsed_time)/1000 AS avg_sec,
                               COUNT(*) AS cnt
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        WHERE q.start_time >= DATEADD('day',-14,CURRENT_TIMESTAMP())
                          AND q.start_time <  DATEADD('day',-7,CURRENT_TIMESTAMP())
                          AND q.warehouse_name IS NOT NULL
                          {qa_filters}
                        GROUP BY sig HAVING cnt >= 5
                    )
                    SELECT r.sig, r.avg_sec AS recent_sec, p.avg_sec AS prior_sec,
                           ROUND((r.avg_sec - p.avg_sec)/NULLIF(p.avg_sec,0)*100, 1) AS pct_change
                    FROM sig_recent r
                    JOIN sig_prior p ON r.sig = p.sig
                    WHERE r.avg_sec > p.avg_sec * 1.25
                      AND r.avg_sec > 5
                    ORDER BY pct_change DESC LIMIT 50
                    """, ttl_key=f"query_analysis_degradation_live_{company}", tier="standard")
                    st.session_state["qa_degradation_source"] = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"
                st.session_state["qa_df_deg"] = _annotate_degradation_routes(df_deg)
            except Exception as e:
                st.warning(f"Pattern degradation data unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("qa_df_deg") is not None:
            df_d = st.session_state["qa_df_deg"]
            if not df_d.empty:
                st.warning(f"⚠️ {len(df_d)} query patterns degraded >25% vs prior week.")
                st.caption(st.session_state.get("qa_degradation_source", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"))
                render_priority_dataframe(
                    df_d,
                    title="Query regressions to investigate first",
                    priority_columns=[
                        "SIG", "RECENT_SEC", "PRIOR_SEC", "PCT_CHANGE",
                        "PRIMARY_SIGNAL", "NEXT_WORKFLOW", "NEXT_ACTION",
                    ],
                    sort_by=["PCT_CHANGE", "RECENT_SEC"],
                    ascending=[False, False],
                    raw_label="All degraded query patterns",
                )
                download_csv(df_d, "pattern_degradation.csv")
            else:
                st.success("✅ No significant query pattern degradation detected.")

    # ── PLAN STEPS ────────────────────────────────────────────────────────────
    elif active_view == "Plan Steps":
        st.header("🗂️ Query Plan Steps (GET_QUERY_OPERATOR_STATS)")
        st.caption("Enter a Query ID to inspect operator-level statistics.")

        qid_input = st.text_input("Query ID", key="planstep_qid")
        if qid_input and st.button("Load Plan Steps", key="planstep_load"):
            try:
                df_ops = run_query(
                    f"SELECT * FROM TABLE(GET_QUERY_OPERATOR_STATS({sql_literal(qid_input)}))",
                    ttl_key=f"query_analysis_plan_{company}_{qid_input}",
                    tier="standard",
                )
                render_priority_dataframe(
                    df_ops,
                    title="Operator steps to inspect first",
                    priority_columns=[
                        "OPERATOR_ID", "OPERATOR_TYPE", "PARENT_OPERATORS",
                        "OPERATOR_STATISTICS", "EXECUTION_TIME_BREAKDOWN",
                    ],
                    raw_label="All operator stats",
                )
                download_csv(df_ops, f"plan_steps_{qid_input}.csv")
            except Exception as e:
                st.warning(f"Operator stats unavailable: {format_snowflake_error(e)}")

    # ── AI DIAGNOSIS ──────────────────────────────────────────────────────────
    elif active_view == "AI Diagnosis":
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
                    result = session.sql(
                        f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', {sql_literal(prompt)}) AS answer"
                    ).collect()
                    st.markdown(result[0]["ANSWER"])
                except Exception as e:
                    st.info(f"Cortex AI unavailable. {format_snowflake_error(e)} Ensure Cortex functions are enabled in your account.")
