# sections/warehouse_health.py - Warehouse stats, scaling events, idle detection, spill, heatmap
import streamlit as st
import pandas as pd
from utils.workflows import render_workflow_selector
from utils import (
    get_session, format_credits,
    download_csv, render_drillable_bar_chart, get_wh_filter_clause,
    get_active_company, get_global_filter_clause,
    metric_confidence_label, freshness_note,
    build_metered_credit_cte, build_action_queue_ddl, make_action_id, upsert_actions,
    run_query, format_snowflake_error, filter_existing_columns, render_optimization_advisor,
    build_mart_warehouse_overview_sql, build_mart_warehouse_scaling_sql,
    safe_float, safe_int,
)
from config import THRESHOLDS


WAREHOUSE_HEALTH_VIEWS = (
    "Overview & Scaling",
    "Efficiency",
    "Spill & Memory",
    "Workload Heatmap",
    "Optimization Advisor",
)

WAREHOUSE_HEALTH_DETAILS = {
    "Overview & Scaling": "Warehouse volume, latency, spill, cache, and metering events.",
    "Efficiency": "Credits per query, queue per credit, spill per credit, and scorecard.",
    "Spill & Memory": "Local and remote spill drilldowns by warehouse.",
    "Workload Heatmap": "Concurrency by warehouse, day, and hour.",
    "Optimization Advisor": "Actionable sizing, suspend, spill, and reliability recommendations.",
}


def _warehouse_capacity_score(
    queued_queries: int,
    spill_queries: int,
    high_latency_queries: int,
    total_queries: int,
    credit_spike_pct: float,
) -> int:
    total = max(int(total_queries or 0), 1)
    queue_pct = safe_float(queued_queries) / total * 100
    spill_pct = safe_float(spill_queries) / total * 100
    latency_pct = safe_float(high_latency_queries) / total * 100
    spike_pct = max(safe_float(credit_spike_pct), 0)
    penalty = (
        min(queue_pct * 2.0, 28)
        + min(spill_pct * 1.8, 24)
        + min(latency_pct * 1.1, 18)
        + min(spike_pct / 4, 20)
    )
    return max(0, min(100, int(round(100 - penalty))))


def _warehouse_capacity_rating(score: int) -> str:
    if score >= 90:
        return "Healthy"
    if score >= 78:
        return "Watch"
    if score >= 65:
        return "Pressure"
    return "Capacity Risk"


def _warehouse_capacity_action_for(signal: str) -> tuple[str, str]:
    signal = str(signal or "").upper()
    if "QUEUE" in signal:
        return (
            "Review multi-cluster policy, warehouse size, auto-resume latency, and workload routing.",
            "-- Queue pressure: inspect WAREHOUSE_LOAD_HISTORY and top queued QUERY_HISTORY rows.",
        )
    if "SPILL" in signal:
        return (
            "Inspect top spilling queries and consider query rewrites, clustering, or a larger warehouse for this workload.",
            "-- Spill pressure: use GET_QUERY_OPERATOR_STATS for top remote-spill query IDs.",
        )
    if "CREDIT" in signal:
        return (
            "Compare current burn to prior period and confirm whether the spike is business demand, idle time, or runaway workload.",
            "-- Credit spike: reconcile WAREHOUSE_METERING_HISTORY with query-attributed drivers.",
        )
    return (
        "Review p95 latency, query volume, and top query patterns before changing warehouse configuration.",
        "-- Latency pressure: inspect high elapsed query signatures and warehouse load.",
    )


def _warehouse_capacity_workflow_for(signal: str) -> str:
    signal = str(signal or "").upper()
    if "SPILL" in signal:
        return "Spill & Memory"
    if "CREDIT" in signal:
        return "Efficiency"
    if "QUEUE" in signal:
        return "Workload Heatmap"
    return "Overview & Scaling"


def _warehouse_capacity_priority_view(exceptions: pd.DataFrame) -> pd.DataFrame:
    if exceptions is None or exceptions.empty:
        return pd.DataFrame()
    rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    view = exceptions.copy()
    view["_RANK"] = view.get("SEVERITY", pd.Series(dtype=str)).map(rank).fillna(4)
    view["NEXT_ACTION"] = view.get("SIGNAL", pd.Series(dtype=str)).apply(lambda value: _warehouse_capacity_action_for(value)[0])
    view["NEXT_WORKFLOW"] = view.get("SIGNAL", pd.Series(dtype=str)).apply(_warehouse_capacity_workflow_for)
    return view.sort_values(["_RANK", "CAPACITY_SCORE", "METERED_CREDITS"], ascending=[True, True, False]).drop(columns=["_RANK"], errors="ignore")


def _render_warehouse_watch_floor(score: int, exceptions: pd.DataFrame, summary_row: dict) -> None:
    priority = _warehouse_capacity_priority_view(exceptions).head(3)
    high_risk = 0
    if exceptions is not None and not exceptions.empty and "SEVERITY" in exceptions.columns:
        high_risk = int(exceptions["SEVERITY"].isin(["Critical", "High"]).sum())

    c1, c2, c3, c4 = st.columns([1.1, 1.1, 1.1, 2.4])
    c1.metric("Warehouse Readiness", f"{score}/100", _warehouse_capacity_rating(score))
    c2.metric("High-Risk Warehouses", f"{high_risk:,}", delta_color="inverse")
    c3.metric("Remote Spill", f"{safe_float(summary_row.get('REMOTE_SPILL_GB')):,.1f} GB", delta_color="inverse")
    with c4:
        if priority.empty:
            st.success("No urgent warehouse capacity exceptions crossed the selected thresholds.")
        else:
            first = priority.iloc[0]
            st.warning(
                f"First move: {first.get('SIGNAL', 'Warehouse pressure')} on "
                f"{first.get('WAREHOUSE_NAME', 'unknown warehouse')} -> {first.get('NEXT_ACTION', 'Review warehouse pressure.')}"
            )

    st.markdown("**Warehouse Watch Floor**")
    if priority.empty:
        st.caption("Use Overview & Scaling for periodic checks, or Efficiency after a cost spike.")
        return

    cols = st.columns(len(priority))
    for idx, (_, item) in enumerate(priority.iterrows()):
        workflow = str(item.get("NEXT_WORKFLOW") or "Overview & Scaling")
        with cols[idx]:
            st.markdown(f"**{item.get('SEVERITY', 'Medium')}: {item.get('SIGNAL', '')}**")
            st.caption(f"{item.get('WAREHOUSE_NAME', 'unknown warehouse')} | Score {safe_float(item.get('CAPACITY_SCORE')):,.1f}")
            st.caption(
                f"Queued {safe_int(item.get('QUEUED_QUERIES')):,} | "
                f"Spill {safe_int(item.get('SPILL_QUERIES')):,} | "
                f"{format_credits(safe_float(item.get('METERED_CREDITS')))}"
            )
            st.write(str(item.get("NEXT_ACTION", "")))
            if st.button(f"Open {workflow}", key=f"wh_watch_floor_{idx}_{workflow}", use_container_width=True):
                warehouse = str(item.get("WAREHOUSE_NAME") or "")
                if warehouse:
                    st.session_state["global_warehouse"] = warehouse
                    st.session_state["wh_filter"] = warehouse
                    st.session_state["lm_wh"] = warehouse
                    for stale_key in ["wh_df_wh", "wh_efficiency", "wh_df_sp", "wh_df_hm"]:
                        st.session_state.pop(stale_key, None)
                st.session_state["warehouse_health_view"] = workflow
                st.rerun()


def _build_warehouse_capacity_markdown(
    company: str,
    days: int,
    score: int,
    summary_row: dict,
    exceptions: pd.DataFrame,
) -> str:
    lines = [
        f"# OVERWATCH Warehouse Capacity Brief - {company}",
        "",
        f"- Lookback: {days} days",
        f"- Capacity score: {score} ({_warehouse_capacity_rating(score)})",
        f"- Warehouses active: {safe_int(summary_row.get('WAREHOUSES_ACTIVE')):,}",
        f"- Queries: {safe_int(summary_row.get('TOTAL_QUERIES')):,}",
        f"- Queued queries: {safe_int(summary_row.get('QUEUED_QUERIES')):,}",
        f"- Spill queries: {safe_int(summary_row.get('SPILL_QUERIES')):,}",
        f"- Credit movement: {safe_float(summary_row.get('CREDIT_SPIKE_PCT')):,.1f}%",
        "",
        "## DBA Narrative",
        (
            "Use this brief to decide whether warehouse pressure is capacity, memory, workload shape, "
            "or cost drift. It is intended to support DBA action and executive reporting without forcing "
            "leadership through raw warehouse telemetry."
        ),
        "",
        "## Top Warehouse Exceptions",
    ]
    if exceptions is None or exceptions.empty:
        lines.append("- No warehouse capacity exceptions found for the selected scope.")
    else:
        for _, row in exceptions.head(10).iterrows():
            lines.append(
                "- "
                f"{row.get('SEVERITY', 'Watch')} | {row.get('SIGNAL', 'Unknown')} | "
                f"{row.get('WAREHOUSE_NAME', '')} | score {safe_float(row.get('CAPACITY_SCORE')):,.1f} | "
                f"{safe_float(row.get('METERED_CREDITS')):,.2f} credits"
            )
    lines.extend([
        "",
        "## Evidence Limits",
        "- ACCOUNT_USAGE can lag; Live Monitor should be used for current in-flight warehouse pressure.",
        "- Per-warehouse pressure is inferred from query history plus metering history, not Snowsight internals.",
        "- Company scope follows configured warehouse/database/user naming rules.",
    ])
    return "\n".join(lines)


def _build_warehouse_capacity_sql(session, days: int) -> tuple[str, str]:
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "WAREHOUSE_SIZE",
            "QUEUED_OVERLOAD_TIME",
            "QUEUED_PROVISIONING_TIME",
            "QUEUED_REPAIR_TIME",
            "BYTES_SPILLED_TO_LOCAL_STORAGE",
            "BYTES_SPILLED_TO_REMOTE_STORAGE",
        ],
    ))
    wm_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
        ["CREDITS_USED_COMPUTE", "CREDITS_USED"],
    ))
    warehouse_size_expr = "MAX(q.warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR"
    queue_ms_expr = " + ".join([
        "COALESCE(q.queued_overload_time, 0)" if "QUEUED_OVERLOAD_TIME" in qh_cols else "0",
        "COALESCE(q.queued_provisioning_time, 0)" if "QUEUED_PROVISIONING_TIME" in qh_cols else "0",
        "COALESCE(q.queued_repair_time, 0)" if "QUEUED_REPAIR_TIME" in qh_cols else "0",
    ])
    local_spill_expr = (
        "COALESCE(q.bytes_spilled_to_local_storage, 0)"
        if "BYTES_SPILLED_TO_LOCAL_STORAGE" in qh_cols
        else "0"
    )
    remote_spill_expr = (
        "COALESCE(q.bytes_spilled_to_remote_storage, 0)"
        if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
        else "0"
    )
    spill_bytes_expr = f"{local_spill_expr} + {remote_spill_expr}"
    meter_expr = (
        "COALESCE(m.credits_used_compute, m.credits_used)"
        if {"CREDITS_USED_COMPUTE", "CREDITS_USED"}.issubset(wm_cols)
        else "m.credits_used"
    )
    filters_q = get_global_filter_clause(
        date_col="q.start_time",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
    )
    filters_m = get_wh_filter_clause("m.warehouse_name")
    summary_sql = f"""
        WITH query_rollup AS (
            SELECT
                q.warehouse_name,
                COUNT(*) AS total_queries,
                SUM(IFF(({queue_ms_expr}) > 0, 1, 0)) AS queued_queries,
                SUM(IFF(({spill_bytes_expr}) > 0, 1, 0)) AS spill_queries,
                SUM(IFF(q.total_elapsed_time >= 30000, 1, 0)) AS high_latency_queries,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY q.total_elapsed_time / 1000.0) AS p95_elapsed_sec,
                SUM({remote_spill_expr}) / POWER(1024, 3) AS remote_spill_gb
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {filters_q}
            GROUP BY q.warehouse_name
        ),
        metering AS (
            SELECT
                m.warehouse_name,
                SUM(IFF(m.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP()),
                        {meter_expr}, 0)) AS current_credits,
                SUM(IFF(m.start_time >= DATEADD('day', -{int(days) * 2}, CURRENT_TIMESTAMP())
                         AND m.start_time < DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP()),
                        {meter_expr}, 0)) AS prior_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY m
            WHERE m.start_time >= DATEADD('day', -{int(days) * 2}, CURRENT_TIMESTAMP())
              {filters_m}
            GROUP BY m.warehouse_name
        ),
        combined AS (
            SELECT
                COALESCE(q.warehouse_name, m.warehouse_name) AS warehouse_name,
                COALESCE(q.total_queries, 0) AS total_queries,
                COALESCE(q.queued_queries, 0) AS queued_queries,
                COALESCE(q.spill_queries, 0) AS spill_queries,
                COALESCE(q.high_latency_queries, 0) AS high_latency_queries,
                COALESCE(q.p95_elapsed_sec, 0) AS p95_elapsed_sec,
                COALESCE(q.remote_spill_gb, 0) AS remote_spill_gb,
                COALESCE(m.current_credits, 0) AS current_credits,
                COALESCE(m.prior_credits, 0) AS prior_credits,
                (COALESCE(m.current_credits, 0) - COALESCE(m.prior_credits, 0))
                    / NULLIF(COALESCE(m.prior_credits, 0), 0) * 100 AS credit_spike_pct
            FROM query_rollup q
            FULL OUTER JOIN metering m ON q.warehouse_name = m.warehouse_name
        )
        SELECT
            COUNT(DISTINCT warehouse_name) AS warehouses_active,
            SUM(total_queries) AS total_queries,
            SUM(queued_queries) AS queued_queries,
            SUM(spill_queries) AS spill_queries,
            SUM(high_latency_queries) AS high_latency_queries,
            SUM(current_credits) AS metered_credits,
            SUM(prior_credits) AS prior_credits,
            (SUM(current_credits) - SUM(prior_credits)) / NULLIF(SUM(prior_credits), 0) * 100 AS credit_spike_pct,
            MAX(p95_elapsed_sec) AS worst_p95_elapsed_sec,
            SUM(remote_spill_gb) AS remote_spill_gb
        FROM combined
    """
    exceptions_sql = f"""
        WITH query_rollup AS (
            SELECT
                q.warehouse_name,
                {warehouse_size_expr} AS warehouse_size,
                COUNT(*) AS total_queries,
                SUM(IFF(({queue_ms_expr}) > 0, 1, 0)) AS queued_queries,
                SUM(IFF(({spill_bytes_expr}) > 0, 1, 0)) AS spill_queries,
                SUM(IFF(q.total_elapsed_time >= 30000, 1, 0)) AS high_latency_queries,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY q.total_elapsed_time / 1000.0) AS p95_elapsed_sec,
                SUM({remote_spill_expr}) / POWER(1024, 3) AS remote_spill_gb
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {filters_q}
            GROUP BY q.warehouse_name
        ),
        metering AS (
            SELECT
                m.warehouse_name,
                SUM(IFF(m.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP()),
                        {meter_expr}, 0)) AS current_credits,
                SUM(IFF(m.start_time >= DATEADD('day', -{int(days) * 2}, CURRENT_TIMESTAMP())
                         AND m.start_time < DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP()),
                        {meter_expr}, 0)) AS prior_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY m
            WHERE m.start_time >= DATEADD('day', -{int(days) * 2}, CURRENT_TIMESTAMP())
              {filters_m}
            GROUP BY m.warehouse_name
        ),
        combined AS (
            SELECT
                COALESCE(q.warehouse_name, m.warehouse_name) AS warehouse_name,
                q.warehouse_size,
                COALESCE(q.total_queries, 0) AS total_queries,
                COALESCE(q.queued_queries, 0) AS queued_queries,
                COALESCE(q.spill_queries, 0) AS spill_queries,
                COALESCE(q.high_latency_queries, 0) AS high_latency_queries,
                COALESCE(q.p95_elapsed_sec, 0) AS p95_elapsed_sec,
                COALESCE(q.remote_spill_gb, 0) AS remote_spill_gb,
                COALESCE(m.current_credits, 0) AS current_credits,
                COALESCE(m.prior_credits, 0) AS prior_credits,
                (COALESCE(m.current_credits, 0) - COALESCE(m.prior_credits, 0))
                    / NULLIF(COALESCE(m.prior_credits, 0), 0) * 100 AS credit_spike_pct
            FROM query_rollup q
            FULL OUTER JOIN metering m ON q.warehouse_name = m.warehouse_name
        )
        SELECT
            CASE
                WHEN queued_queries >= 20 OR remote_spill_gb >= 20 THEN 'Critical'
                WHEN credit_spike_pct >= 50 OR spill_queries >= 10 OR high_latency_queries >= 25 THEN 'High'
                ELSE 'Medium'
            END AS severity,
            CASE
                WHEN queued_queries >= 20 THEN 'Queue Pressure'
                WHEN remote_spill_gb >= 1 THEN 'Memory Spill'
                WHEN credit_spike_pct >= 25 THEN 'Credit Spike'
                ELSE 'Latency Pressure'
            END AS signal,
            warehouse_name,
            warehouse_size,
            total_queries,
            queued_queries,
            spill_queries,
            high_latency_queries,
            ROUND(p95_elapsed_sec, 2) AS p95_elapsed_sec,
            ROUND(remote_spill_gb, 2) AS remote_spill_gb,
            ROUND(current_credits, 4) AS metered_credits,
            ROUND(prior_credits, 4) AS prior_credits,
            ROUND(COALESCE(credit_spike_pct, 0), 1) AS credit_spike_pct,
            ROUND(100
                - LEAST(queued_queries * 100.0 / NULLIF(total_queries, 0) * 2.0, 28)
                - LEAST(spill_queries * 100.0 / NULLIF(total_queries, 0) * 1.8, 24)
                - LEAST(high_latency_queries * 100.0 / NULLIF(total_queries, 0) * 1.1, 18)
                - LEAST(GREATEST(COALESCE(credit_spike_pct, 0), 0) / 4, 20), 1) AS capacity_score
        FROM combined
        WHERE queued_queries > 0
           OR spill_queries > 0
           OR high_latency_queries > 0
           OR credit_spike_pct >= 25
        ORDER BY
            CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 ELSE 3 END,
            capacity_score ASC,
            metered_credits DESC
        LIMIT 100
    """
    return summary_sql, exceptions_sql


def _queue_capacity_findings(session, exceptions: pd.DataFrame) -> int:
    if exceptions is None or exceptions.empty:
        return 0
    company = get_active_company()
    actions = []
    for _, row in exceptions.head(50).iterrows():
        wh = str(row.get("WAREHOUSE_NAME", ""))
        signal = str(row.get("SIGNAL", "Warehouse Pressure"))
        action_text, generated_sql = _warehouse_capacity_action_for(signal)
        finding = (
            f"{signal} on {wh}: capacity score={safe_float(row.get('CAPACITY_SCORE')):,.1f}, "
            f"queued={safe_int(row.get('QUEUED_QUERIES')):,}, spill={safe_int(row.get('SPILL_QUERIES')):,}, "
            f"credits={safe_float(row.get('METERED_CREDITS')):,.2f}."
        )
        actions.append({
            "Action ID": make_action_id("Warehouse Capacity", wh, finding),
            "Source": "Warehouse Health - Capacity Brief",
            "Category": "Warehouse Capacity",
            "Severity": row.get("SEVERITY", "High"),
            "Entity Type": "Warehouse",
            "Entity": wh,
            "Owner": "DBA",
            "Finding": finding,
            "Action": action_text,
            "Estimated Monthly Savings": 0,
            "Generated SQL Fix": generated_sql,
            "Proof Query": "Review QUERY_HISTORY and WAREHOUSE_METERING_HISTORY for this warehouse and period.",
            "Company": company,
        })
    return upsert_actions(session, actions)


def _render_capacity_brief(session, company: str) -> None:
    with st.expander("Capacity Brief", expanded=bool(st.session_state.get("exceptions_only_mode"))):
        days = st.slider("Capacity lookback (days)", 1, 30, 7, key="wh_capacity_days")
        if st.button("Load Capacity Brief", key="wh_capacity_load"):
            with st.spinner("Building warehouse capacity brief..."):
                try:
                    summary_sql, exceptions_sql = _build_warehouse_capacity_sql(session, days)
                    summary = run_query(
                        summary_sql,
                        ttl_key=f"wh_capacity_summary_{company}_{days}",
                        tier="historical",
                        section="Warehouse Health",
                    )
                    exceptions = run_query(
                        exceptions_sql,
                        ttl_key=f"wh_capacity_exceptions_{company}_{days}",
                        tier="historical",
                        section="Warehouse Health",
                    )
                    st.session_state["wh_capacity_summary"] = summary
                    st.session_state["wh_capacity_exceptions"] = exceptions
                    st.session_state["wh_capacity_sql"] = {
                        "summary": summary_sql,
                        "exceptions": exceptions_sql,
                    }
                    st.session_state["wh_capacity_meta"] = {
                        "company": company,
                        "days": int(days),
                    }
                except Exception as e:
                    st.warning(f"Capacity brief unavailable in this role/context: {format_snowflake_error(e)}")

        summary = st.session_state.get("wh_capacity_summary")
        exceptions = st.session_state.get("wh_capacity_exceptions")
        meta = st.session_state.get("wh_capacity_meta", {})
        if (
            summary is None
            or summary.empty
            or meta.get("company") != company
            or meta.get("days") != int(days)
        ):
            return
        row = summary.iloc[0].to_dict()
        score = _warehouse_capacity_score(
            queued_queries=safe_int(row.get("QUEUED_QUERIES")),
            spill_queries=safe_int(row.get("SPILL_QUERIES")),
            high_latency_queries=safe_int(row.get("HIGH_LATENCY_QUERIES")),
            total_queries=safe_int(row.get("TOTAL_QUERIES")),
            credit_spike_pct=safe_float(row.get("CREDIT_SPIKE_PCT")),
        )
        rating = _warehouse_capacity_rating(score)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Capacity Score", score, rating)
        c2.metric("Queued", f"{safe_int(row.get('QUEUED_QUERIES')):,}", delta_color="inverse")
        c3.metric("Spill", f"{safe_int(row.get('SPILL_QUERIES')):,}", delta_color="inverse")
        c4.metric("Metered Credits", format_credits(safe_float(row.get("METERED_CREDITS"))))
        if score < 65:
            st.error("Capacity risk: warehouse pressure is high enough to affect service levels or cost control.")
        elif score < 78:
            st.warning("Pressure: review exception warehouses before approving workload growth.")
        elif score < 90:
            st.info("Watch: warehouse pressure exists, but it is not currently dominant.")
        else:
            st.success("Healthy: no major warehouse pressure signal in this scope.")

        _render_warehouse_watch_floor(score, exceptions, row)
        st.divider()

        if exceptions is not None and not exceptions.empty:
            st.dataframe(exceptions, use_container_width=True, hide_index=True)
            if st.button("Save Capacity Findings to Action Queue", key="wh_capacity_queue"):
                try:
                    saved = _queue_capacity_findings(session, exceptions)
                    st.success(f"Saved {saved} warehouse capacity findings to the action queue.")
                except Exception as e:
                    st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
                    st.download_button(
                        "Download Action Queue DDL",
                        build_action_queue_ddl(),
                        file_name="overwatch_action_queue_setup.sql",
                        mime="text/plain",
                        key="wh_capacity_ddl",
                    )
        else:
            st.success("No warehouse capacity exceptions found for this scope.")

        st.download_button(
            "Download Capacity Brief",
            _build_warehouse_capacity_markdown(company, days, score, row, exceptions),
            file_name=f"overwatch_warehouse_capacity_{company.lower()}.md",
            mime="text/markdown",
            key="wh_capacity_download",
        )
        with st.expander("Proof SQL"):
            sql_map = st.session_state.get("wh_capacity_sql", {})
            st.code(sql_map.get("summary", ""), language="sql")
            st.code(sql_map.get("exceptions", ""), language="sql")


def _queue_efficiency_findings(session, df_eff: pd.DataFrame) -> None:
    if df_eff is None or df_eff.empty:
        st.info("No efficiency findings to queue.")
        return
    company = st.session_state.get("active_company", "ALFA")
    actions = []
    for _, row in df_eff[df_eff["EFFICIENCY_SCORE"] < 70].head(100).iterrows():
        wh = str(row.get("WAREHOUSE_NAME", ""))
        score = safe_float(row.get("EFFICIENCY_SCORE", 0))
        queue = safe_float(row.get("QUEUE_SEC_PER_CREDIT", 0))
        spill = safe_float(row.get("REMOTE_SPILL_GB_PER_CREDIT", 0))
        credits = safe_float(row.get("METERED_CREDITS", 0))
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
        st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
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
    global_warehouse = str(st.session_state.get("global_warehouse", "") or "").strip()
    global_user = str(st.session_state.get("global_user", "") or "").strip()
    global_role = str(st.session_state.get("global_role", "") or "").strip()
    global_database = str(st.session_state.get("global_database", "") or "").strip()
    global_start_date = st.session_state.get("global_start_date")
    global_end_date = st.session_state.get("global_end_date")
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
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "WAREHOUSE_SIZE",
            "QUEUED_OVERLOAD_TIME",
            "BYTES_SPILLED_TO_LOCAL_STORAGE",
            "BYTES_SPILLED_TO_REMOTE_STORAGE",
            "PERCENTAGE_SCANNED_FROM_CACHE",
            "BYTES_SCANNED",
        ],
    ))
    wm_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
        ["CREDITS_USED_COMPUTE", "CREDITS_USED_CLOUD_SERVICES"],
    ))
    wh_size_expr = "MAX(q.warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR"
    plain_wh_size_expr = "MAX(warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR"
    latest_size_expr = "q.warehouse_size" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR"
    queue_avg_expr = "AVG(q.queued_overload_time)/1000" if "QUEUED_OVERLOAD_TIME" in qh_cols else "0"
    queue_sum_expr = "SUM(q.queued_overload_time)" if "QUEUED_OVERLOAD_TIME" in qh_cols else "0"
    remote_spill_sum_expr = (
        "SUM(q.bytes_spilled_to_remote_storage)"
        if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
        else "0"
    )
    local_spill_expr = (
        "SUM(bytes_spilled_to_local_storage)"
        if "BYTES_SPILLED_TO_LOCAL_STORAGE" in qh_cols
        else "0"
    )
    local_spill_row_expr = (
        "bytes_spilled_to_local_storage"
        if "BYTES_SPILLED_TO_LOCAL_STORAGE" in qh_cols
        else "0"
    )
    remote_spill_expr = (
        "SUM(bytes_spilled_to_remote_storage)"
        if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
        else "0"
    )
    remote_spill_row_expr = (
        "bytes_spilled_to_remote_storage"
        if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
        else "0"
    )
    cache_expr = "AVG(q.percentage_scanned_from_cache)" if "PERCENTAGE_SCANNED_FROM_CACHE" in qh_cols else "0"
    bytes_scanned_expr = "SUM(q.bytes_scanned)" if "BYTES_SCANNED" in qh_cols else "0"
    compute_meter_expr = "m.credits_used_compute" if "CREDITS_USED_COMPUTE" in wm_cols else "m.credits_used"
    cloud_meter_expr = "m.credits_used_cloud_services" if "CREDITS_USED_CLOUD_SERVICES" in wm_cols else "0::FLOAT"

    _render_capacity_brief(session, company)
    if st.session_state.get("exceptions_only_mode"):
        st.stop()

    warehouse_view = render_workflow_selector(
        "Warehouse Health workflow",
        "warehouse_health_view",
        WAREHOUSE_HEALTH_VIEWS,
        WAREHOUSE_HEALTH_DETAILS,
        columns=3,
    )

    # ── OVERVIEW ──────────────────────────────────────────────────────────────
    if warehouse_view == "Overview & Scaling":
        st.header("Warehouse Health Overview")
        wh_days = st.slider("Lookback (days)", 1, 30, 7, key="wh_days")

        if st.button("Load Warehouse Data", key="wh_load"):
            try:
                mart_sql = build_mart_warehouse_overview_sql(
                    wh_days,
                    company=company,
                    warehouse_contains=global_warehouse,
                    user_contains=global_user,
                    role_contains=global_role,
                    database_contains=global_database,
                    start_date=global_start_date,
                    end_date=global_end_date,
                )
                df_w = run_query(
                    mart_sql,
                    ttl_key=f"wh_overview_mart_{company}_{wh_days}",
                    tier="historical",
                )
                source = (
                    "OVERWATCH mart: FACT_QUERY_HOURLY + FACT_WAREHOUSE_HOURLY "
                    "(cache and warehouse size require live ACCOUNT_USAGE)"
                )
                if df_w.empty:
                    df_w = run_query(f"""
                        SELECT q.warehouse_name,
                               {wh_size_expr} AS warehouse_size,
                               COUNT(*)                            AS total_queries,
                               AVG(q.total_elapsed_time)/1000      AS avg_elapsed_sec,
                               PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY q.total_elapsed_time)/1000 AS p95_elapsed_sec,
                               {queue_avg_expr}                    AS avg_queued_sec,
                               {remote_spill_sum_expr}/POWER(1024,3)  AS total_remote_spill_gb,
                               {cache_expr} AS avg_cache_pct,
                               SUM(CASE WHEN UPPER(q.execution_status)='FAILED_WITH_ERROR' THEN 1 ELSE 0 END) AS error_count,
                               {bytes_scanned_expr}/POWER(1024,3)  AS total_gb_scanned
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        WHERE q.start_time >= DATEADD('day', -{wh_days}, CURRENT_TIMESTAMP())
                          AND q.warehouse_name IS NOT NULL
                          {wh_query_filters}
                        GROUP BY q.warehouse_name
                        ORDER BY total_queries DESC
                    """, ttl_key=f"wh_overview_live_{company}_{wh_days}", tier="historical")
                    source = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"
                st.session_state["wh_df_wh"] = df_w
                st.session_state["wh_df_wh_source"] = source
            except Exception as e:
                st.warning(f"Warehouse overview unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("wh_df_wh") is not None and not st.session_state["wh_df_wh"].empty:
            df_w = st.session_state["wh_df_wh"]

            c1, c2, c3 = st.columns(3)
            c1.metric("Warehouses Active", len(df_w))
            c2.metric("Total Queries",     f"{int(df_w['TOTAL_QUERIES'].sum()):,}")
            c3.metric("Total Remote Spill", f"{df_w['TOTAL_REMOTE_SPILL_GB'].sum():.1f} GB")
            wh_source = st.session_state.get("wh_df_wh_source", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY")
            confidence = "estimated" if "mart:" in str(wh_source).lower() else "exact"
            st.caption(f"{metric_confidence_label(confidence)} | {wh_source}")

            # Flag warehouses needing attention
            for _, row in df_w.iterrows():
                issues = []
                if row.get("AVG_QUEUED_SEC", 0) > 2:
                    issues.append(f"Queue avg {row['AVG_QUEUED_SEC']:.1f}s - consider multi-cluster or upsize")
                if row.get("TOTAL_REMOTE_SPILL_GB", 0) > THRESHOLDS["spill_warning_gb"]:
                    issues.append(f"Remote spill {row['TOTAL_REMOTE_SPILL_GB']:.1f} GB - upsize")
                if issues:
                    st.warning(f"**{row['WAREHOUSE_NAME']}** ({row.get('WAREHOUSE_SIZE','')}): {' | '.join(issues)}")

            st.dataframe(df_w, use_container_width=True)

            # Cache efficiency chart
            cache_available = "AVG_CACHE_PCT" in df_w.columns and df_w["AVG_CACHE_PCT"].notna().any()
            if cache_available:
                st.subheader("Cache Hit % by Warehouse")
                render_drillable_bar_chart(
                    df_w,
                    dimension="WAREHOUSE_NAME",
                    measure="AVG_CACHE_PCT",
                    key="wh_cache_pct",
                    drilldown_column="warehouse_name",
                    lookback_hours=wh_days * 24,
                )
            else:
                st.info("Cache hit percentage is a live ACCOUNT_USAGE-only metric and is not stored in the hourly mart.")

            download_csv(df_w, "warehouse_health.csv")

            # Scaling events
            st.divider()
            st.subheader("Scaling Events (WAREHOUSE_METERING_HISTORY)")
            if st.button("Load Scaling Events", key="wh_scale_load"):
                try:
                    df_scale = run_query(
                        build_mart_warehouse_scaling_sql(
                            wh_days,
                            company=company,
                            warehouse_contains=global_warehouse,
                            start_date=global_start_date,
                            end_date=global_end_date,
                        ),
                        ttl_key=f"wh_scaling_mart_{company}_{wh_days}",
                        tier="historical",
                    )
                    scale_source = "OVERWATCH mart: FACT_WAREHOUSE_HOURLY"
                    if df_scale.empty:
                        df_scale = run_query(f"""
                            WITH latest_size AS (
                                SELECT warehouse_name, warehouse_size
                                FROM (
                                    SELECT q.warehouse_name, {latest_size_expr} AS warehouse_size,
                                           ROW_NUMBER() OVER (PARTITION BY q.warehouse_name ORDER BY q.start_time DESC) AS rn
                                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                                    WHERE q.start_time >= DATEADD('day', -{wh_days}, CURRENT_TIMESTAMP())
                                      AND q.warehouse_name IS NOT NULL
                                      {wh_query_filters}
                                )
                                WHERE rn = 1
                            )
                            SELECT m.warehouse_name, ls.warehouse_size, m.start_time, m.end_time,
                                   m.credits_used, {compute_meter_expr} AS credits_used_compute,
                                   {cloud_meter_expr} AS credits_used_cloud_services
                            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY m
                            LEFT JOIN latest_size ls ON m.warehouse_name = ls.warehouse_name
                            WHERE m.start_time >= DATEADD('day', -{wh_days}, CURRENT_TIMESTAMP())
                              {get_wh_filter_clause("m.warehouse_name")}
                            ORDER BY m.credits_used DESC LIMIT 200
                        """, ttl_key=f"wh_scaling_live_{company}_{wh_days}", tier="historical")
                        scale_source = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
                    st.caption(f"{metric_confidence_label('exact')} | {scale_source}")
                    st.dataframe(df_scale, use_container_width=True)
                    download_csv(df_scale, "scaling_events.csv")
                except Exception as e:
                    st.warning(f"Scaling events unavailable in this role/context: {format_snowflake_error(e)}")

    elif warehouse_view == "Efficiency":
        st.header("Warehouse Efficiency Scorecard")
        eff_days = st.slider("Lookback (days)", 1, 30, 7, key="wh_eff_days")
        if st.button("Load Efficiency Metrics", key="wh_eff_load"):
            try:
                df_eff = run_query(f"""
                    WITH {build_metered_credit_cte(days_back=eff_days, include_recent=True)}
                    SELECT q.warehouse_name,
                           {wh_size_expr} AS warehouse_size,
                           COUNT(*) AS query_count,
                           ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS metered_credits,
                           ROUND(SUM(COALESCE(pqc.metered_credits, 0)) / NULLIF(COUNT(*), 0), 6) AS credits_per_query,
                           ROUND({queue_sum_expr} / 1000 / NULLIF(SUM(COALESCE(pqc.metered_credits, 0)), 0), 2) AS queue_sec_per_credit,
                           ROUND({remote_spill_sum_expr} / POWER(1024,3) / NULLIF(SUM(COALESCE(pqc.metered_credits, 0)), 0), 2) AS remote_spill_gb_per_credit,
                           ROUND({cache_expr}, 2) AS avg_cache_pct,
                           ROUND(100
                                 - LEAST(COALESCE({queue_sum_expr} / 1000 / NULLIF(SUM(COALESCE(pqc.metered_credits, 0)), 0), 0), 25)
                                 - LEAST(COALESCE({remote_spill_sum_expr} / POWER(1024,3) / NULLIF(SUM(COALESCE(pqc.metered_credits, 0)), 0), 0), 25)
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
                st.warning(f"Efficiency metrics unavailable in this role/context: {format_snowflake_error(e)}")

        df_eff = st.session_state.get("wh_efficiency")
        if df_eff is not None and not df_eff.empty:
            low = df_eff[df_eff["EFFICIENCY_SCORE"] < 70]
            c1, c2, c3 = st.columns(3)
            c1.metric("Warehouses scored", len(df_eff))
            c2.metric("Under 70 score", len(low), delta_color="inverse")
            c3.metric("Total metered credits", format_credits(float(df_eff["METERED_CREDITS"].sum())))
            st.caption(f"{metric_confidence_label('allocated')} | {freshness_note('ACCOUNT_USAGE')}")
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
    elif warehouse_view == "Spill & Memory":
        st.header("Spill & Memory Pressure")
        sp_days = st.slider("Lookback (days)", 1, 30, 7, key="sp_days")

        if st.button("Load Spill Data", key="sp_load"):
            try:
                df_sp = run_query(f"""
                    SELECT warehouse_name, {plain_wh_size_expr} AS warehouse_size,
                           COUNT(*) AS spill_query_count,
                           ROUND({local_spill_expr}/POWER(1024,3),2)  AS local_spill_gb,
                           ROUND({remote_spill_expr}/POWER(1024,3),2) AS remote_spill_gb,
                           ROUND(AVG(total_elapsed_time)/1000,2)                       AS avg_elapsed_sec
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day', -{sp_days}, CURRENT_TIMESTAMP())
                      AND ({local_spill_row_expr} > 0 OR {remote_spill_row_expr} > 0)
                      AND warehouse_name IS NOT NULL
                      {wh_plain_filters}
                    GROUP BY warehouse_name
                    ORDER BY local_spill_gb + remote_spill_gb DESC
                """, ttl_key=f"wh_spill_{company}_{sp_days}", tier="historical")
                st.session_state["wh_df_sp"] = df_sp
            except Exception as e:
                st.warning(f"Spill data unavailable in this role/context: {format_snowflake_error(e)}")

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
                    st.error(f"**{row['WAREHOUSE_NAME']}**: {row['REMOTE_SPILL_GB']:.1f} GB remote spill - upsize immediately")
            download_csv(df_sp, "spill_report.csv")

    # ── HEATMAP ───────────────────────────────────────────────────────────────
    elif warehouse_view == "Workload Heatmap":
        st.header("Workload Concurrency Heatmap")
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
                st.warning(f"Workload heatmap unavailable in this role/context: {format_snowflake_error(e)}")

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
                st.subheader(f"Query Volume Heatmap - {sel_wh}")
                st.dataframe(pivot.style.background_gradient(cmap="YlOrRd"), use_container_width=True)
                c1, c2, c3 = st.columns(3)
                c1.metric("Total Queries", f"{int(wh_data['QUERY_COUNT'].sum()):,}")
                c2.metric("Peak Hour",     f"{int(pivot.max().max()):,}")
                c3.metric("Avg Elapsed",   f"{wh_data['AVG_ELAPSED_SEC'].mean():.1f}s")

    elif warehouse_view == "Optimization Advisor":
        render_optimization_advisor()
