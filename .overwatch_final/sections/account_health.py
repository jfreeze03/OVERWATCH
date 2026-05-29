# sections/account_health.py — Account Health: KPIs, Resource Monitors, Morning Report, Executive Briefing
import streamlit as st
import pandas as pd
from datetime import datetime
from utils import (
    get_session, run_query, run_query_or_raise, format_credits,
    credits_to_dollars, download_csv, mark_loaded, show_loaded_time,
    build_metered_credit_cte, build_monitoring_cost_sql,
    metric_confidence_label, freshness_note,
    render_drillable_bar_chart,
    build_task_failure_summary_sql, build_task_health_sql,
    executive_health_score,
    get_wh_filter_clause, get_db_filter_clause, get_user_filter_clause,
    get_global_filter_clause, company_value_allowed,
    format_snowflake_error, filter_existing_columns, safe_float, safe_int,
)


def _drill_to(
    section: str,
    wh_filter: str = "",
    user_filter: str = "",
    workflow_key: str = "",
    workflow: str = "",
):
    st.session_state["nav_section"] = section
    if workflow_key and workflow:
        st.session_state[workflow_key] = workflow
    if wh_filter:
        st.session_state["lm_wh"]     = wh_filter
        st.session_state["wh_filter"] = wh_filter
    if user_filter:
        st.session_state["global_user"] = user_filter
    st.rerun()


def _build_briefing_prompt(data: dict, credit_price: float, company: str) -> str:
    """Build the Cortex prompt from collected health metrics."""
    cr24     = data.get("cr24",     0)
    cr_prior = data.get("cr_prior", 0)
    cr_delta = ((cr24 - cr_prior) / cr_prior * 100) if cr_prior > 0 else 0
    cost24   = credits_to_dollars(cr24, credit_price)
    failures = data.get("failures", 0)
    queued   = data.get("queued",   0)
    stor_tb  = data.get("stor_tb",  0)
    contract_pct = data.get("contract_pct", None)
    top_driver    = data.get("top_driver",   "")
    top_driver_cost = data.get("top_driver_cost", 0)
    failed_task   = data.get("failed_task",   "")

    contract_line = (
        f"Contract utilization is at {contract_pct:.1f}% of annual committed credits."
        if contract_pct is not None
        else "Contract utilization data not available."
    )
    task_line = (
        f"A task failure was detected: {failed_task}."
        if failed_task
        else "No critical task failures overnight."
    )

    return f"""You are OVERWATCH, a Snowflake monitoring assistant for ALFA Insurance.
Write a concise executive briefing (3–4 short paragraphs, plain English, no bullet points, no markdown headers).
The audience is senior IT leadership — not technical DBAs.
Tone: professional, direct, factual. Flag risks clearly. Quantify in dollars where possible.
Do NOT invent data. Only use the numbers provided. Do NOT use markdown headers or bullet points.
Today is {datetime.now().strftime('%A, %B %d %Y')}.
Company: {company}

Data:
- Credits consumed (last 24h): {cr24:,.0f} (${cost24:,.2f} at ${credit_price:.2f}/credit)
- Credit change vs prior 24h: {cr_delta:+.1f}%
- Top cost driver: {top_driver} (${top_driver_cost:,.2f} yesterday)
- Query failures (last 24h): {failures}
- Queued queries (current): {queued}
- Storage: {stor_tb:.1f} TB
- {contract_line}
- {task_line}

Write the briefing now. Start with yesterday's overall performance summary, then highlight risks,
then one recommended action for leadership."""


def _task_failure_sql_or_empty(session, time_predicate: str, limit: int, company: str) -> str:
    """Return TASK_HISTORY failure SQL, or an empty compatible result if unavailable."""
    try:
        return build_task_failure_summary_sql(session, time_predicate, limit=limit, company=company)
    except Exception:
        return """
            SELECT NULL::VARCHAR AS TASK_NAME,
                   NULL::VARCHAR AS DATABASE_NAME,
                   NULL::VARCHAR AS SCHEMA_NAME,
                   0::NUMBER AS FAILURES,
                   NULL::TIMESTAMP_NTZ AS LAST_FAILURE,
                   NULL::VARCHAR AS LAST_ERROR
            WHERE 1=0
        """


def _task_health_sql_or_empty(session, time_predicate: str, company: str) -> str:
    """Return TASK_HISTORY aggregate SQL, or a single zero row if unavailable."""
    try:
        return build_task_health_sql(session, time_predicate, company=company)
    except Exception:
        return """
            SELECT 0::NUMBER AS TASK_RUNS,
                   0::NUMBER AS FAILED_TASKS,
                   0::NUMBER AS SUCCEEDED_TASKS,
                   0::NUMBER AS DISTINCT_TASKS
        """


def _live_query_status_sql(wh_filter: str, db_filter: str, user_filter: str) -> str:
    return f"""
        SELECT COUNT(*) AS active_count,
               SUM(IFF(
                   COALESCE(queued_overload_time, 0)
                   + COALESCE(queued_provisioning_time, 0)
                   + COALESCE(queued_repair_time, 0) > 0
                   OR execution_status ILIKE '%QUEUED%',
                   1,
                   0
               )) AS queued_count,
               SUM(IFF(execution_status ILIKE '%BLOCKED%', 1, 0)) AS blocked_count
        FROM TABLE(
            INFORMATION_SCHEMA.QUERY_HISTORY(
                END_TIME_RANGE_START=>DATEADD('hours', -1, CURRENT_TIMESTAMP()),
                RESULT_LIMIT=>10000
            )
        ) q
        WHERE execution_status IN ('RUNNING', 'QUEUED', 'BLOCKED', 'RESUMING_WAREHOUSE')
          {wh_filter} {db_filter} {user_filter}
    """


def _load_live_query_status(wh_filter: str, db_filter: str, user_filter: str) -> tuple[pd.DataFrame, str]:
    try:
        return run_query_or_raise(_live_query_status_sql(wh_filter, db_filter, user_filter)), "INFORMATION_SCHEMA"
    except Exception:
        fallback_sql = f"""
            SELECT COUNT(*) AS active_count,
                   SUM(CASE WHEN execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END) AS queued_count,
                   SUM(CASE WHEN execution_status ILIKE '%BLOCKED%' THEN 1 ELSE 0 END) AS blocked_count
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('hours', -1, CURRENT_TIMESTAMP())
              AND UPPER(q.execution_status) IN ('RUNNING', 'QUEUED', 'BLOCKED', 'RESUMING_WAREHOUSE')
              {wh_filter} {db_filter} {user_filter}
        """
        try:
            return run_query_or_raise(fallback_sql), "ACCOUNT_USAGE"
        except Exception:
            return pd.DataFrame(), "ACCOUNT_USAGE"


def render():
    session      = get_session()
    credit_price = st.session_state.get("credit_price", 3.00)
    company      = st.session_state.get("active_company", "ALFA")
    wh_filter_q = get_wh_filter_clause("q.warehouse_name", company)
    wh_filter_m = get_wh_filter_clause("warehouse_name", company)
    db_filter_q = get_db_filter_clause("q.database_name", company)
    user_filter_q = get_user_filter_clause("q.user_name", company)
    global_filter_q = get_global_filter_clause(
        "q.start_time", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name"
    )
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "WAREHOUSE_SIZE",
            "BYTES_SCANNED",
            "ERROR_CODE",
            "QUEUED_OVERLOAD_TIME",
            "QUEUED_PROVISIONING_TIME",
            "QUEUED_REPAIR_TIME",
        ],
    ))
    cost_wh_size_expr = (
        "MAX(q.warehouse_size)"
        if "WAREHOUSE_SIZE" in qh_cols
        else "NULL::VARCHAR"
    )
    cost_bytes_scanned_expr = (
        "SUM(q.bytes_scanned)"
        if "BYTES_SCANNED" in qh_cols
        else "0"
    )
    failed_pred_q = (
        "q.error_code IS NOT NULL"
        if "ERROR_CODE" in qh_cols
        else "UPPER(q.execution_status) = 'FAILED_WITH_ERROR'"
    )
    failed_pred_plain = (
        "error_code IS NOT NULL"
        if "ERROR_CODE" in qh_cols
        else "UPPER(execution_status) = 'FAILED_WITH_ERROR'"
    )
    queue_cols = [
        col.lower()
        for col in ["QUEUED_OVERLOAD_TIME", "QUEUED_PROVISIONING_TIME", "QUEUED_REPAIR_TIME"]
        if col in qh_cols
    ]
    queue_time_q = " + ".join([f"COALESCE(q.{col}, 0)" for col in queue_cols])
    queue_time_plain = " + ".join([f"COALESCE({col}, 0)" for col in queue_cols])
    queued_count_expr_q = (
        f"SUM(CASE WHEN {queue_time_q} > 0 OR q.execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END)"
        if queue_cols
        else "SUM(CASE WHEN q.execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END)"
    )
    queued_count_expr_plain = (
        f"SUM(CASE WHEN {queue_time_plain} > 0 OR execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END)"
        if queue_cols
        else "SUM(CASE WHEN execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END)"
    )
    pressure_wh_size_expr = (
        "MAX(warehouse_size)"
        if "WAREHOUSE_SIZE" in qh_cols
        else "NULL::VARCHAR"
    )

    tab_overview, tab_resmon, tab_morning, tab_briefing = st.tabs([
        "Overview", "Resource Monitors", "Morning Report", "📋 Executive Briefing"
    ])

    # ── OVERVIEW ──────────────────────────────────────────────────────────────
    with tab_overview:
        st.header("🏠 Account Health — Command Center")
        exceptions_only = bool(st.session_state.get("exceptions_only_mode", False))
        if exceptions_only:
            st.info("Leadership exceptions-only mode is on. Heavy drilldowns stay collapsed until you ask for detail.")

        cache_age = 999
        filter_sig = "|".join([
            str(company),
            str(st.session_state.get("global_start_date", "")),
            str(st.session_state.get("global_end_date", "")),
            str(st.session_state.get("global_warehouse", "")),
            str(st.session_state.get("global_user", "")),
            str(st.session_state.get("global_role", "")),
            str(st.session_state.get("global_database", "")),
        ])
        last_ts = st.session_state.get("_health_ts")
        if last_ts:
            cache_age = (datetime.now() - datetime.fromisoformat(last_ts)).total_seconds()

        refresh_health = st.button("🔄 Refresh Health", key="health_refresh")
        if (
            refresh_health
            or cache_age > 300
            or "health_data" not in st.session_state
            or st.session_state.get("_health_filter_sig") != filter_sig
        ):
            hd = {}
            live_df, live_source = _load_live_query_status(wh_filter_q, db_filter_q, user_filter_q)
            hd["live"] = live_df
            hd["_live_source"] = live_source
            for key, sql in [
                ("burn", f"""
                    SELECT SUM(CASE WHEN start_time >= DATEADD('hours',-24,CURRENT_TIMESTAMP())
                               THEN credits_used ELSE 0 END) AS last_24h,
                           SUM(CASE WHEN start_time >= DATEADD('hours',-48,CURRENT_TIMESTAMP())
                                    AND  start_time <  DATEADD('hours',-24,CURRENT_TIMESTAMP())
                               THEN credits_used ELSE 0 END) AS prior_24h
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                    WHERE start_time >= DATEADD('hours',-48,CURRENT_TIMESTAMP())
                      {wh_filter_m}
                """),
                ("errors", f"""
                    SELECT COUNT(*) AS err_count
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    WHERE q.start_time >= DATEADD('hours',-24,CURRENT_TIMESTAMP())
                      AND {failed_pred_q}
                      {wh_filter_q} {db_filter_q} {user_filter_q}
                """),
                ("query_stats", f"""
                    SELECT COUNT(*) AS total_queries,
                           SUM(CASE WHEN {failed_pred_q} THEN 1 ELSE 0 END) AS failed_queries,
                           {queued_count_expr_q} AS queued_queries,
                           ROUND(AVG(total_elapsed_time) / 1000, 2) AS avg_elapsed_sec
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    WHERE q.start_time >= DATEADD('hours',-24,CURRENT_TIMESTAMP())
                      AND q.warehouse_name IS NOT NULL
                      {wh_filter_q} {db_filter_q} {user_filter_q}
                """),
                ("warehouse_pressure", f"""
                    WITH wh AS (
                        SELECT q.warehouse_name,
                               COUNT(*) AS total_queries,
                               SUM(CASE WHEN {failed_pred_q} THEN 1 ELSE 0 END) AS failed_queries,
                               {queued_count_expr_q} AS queued_queries
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        WHERE q.start_time >= DATEADD('hours',-24,CURRENT_TIMESTAMP())
                          AND q.warehouse_name IS NOT NULL
                          {wh_filter_q} {db_filter_q} {user_filter_q}
                        GROUP BY q.warehouse_name
                    )
                    SELECT COUNT(*) AS active_warehouses,
                           SUM(IFF(failed_queries > 0 OR queued_queries > 0, 1, 0)) AS pressure_warehouses
                    FROM wh
                """),
                ("storage", f"""
                    SELECT COALESCE(
                        ROUND(SUM(COALESCE(average_database_bytes,0)+COALESCE(average_failsafe_bytes,0))/POWER(1024,4),2),
                        0
                    ) AS storage_tb
                    FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
                    WHERE usage_date = (SELECT MAX(usage_date)
                                        FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY)
                      {get_db_filter_clause("database_name", company)}
                """),
                ("cost_drivers", f"""
                    WITH {build_metered_credit_cte(hours_back=48, include_recent=True)}
                    SELECT q.user_name, q.warehouse_name, {cost_wh_size_expr} AS warehouse_size,
                           COUNT(*) AS query_count,
                           ROUND(SUM(COALESCE(pqc.metered_credits,0)), 4) AS total_credits,
                           ROUND({cost_bytes_scanned_expr}/POWER(1024,3), 2) AS gb_scanned
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                    WHERE q.start_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
                      AND q.warehouse_name IS NOT NULL
                      {global_filter_q}
                    GROUP BY q.user_name, q.warehouse_name
                    ORDER BY total_credits DESC
                    LIMIT 5
                """),
                ("failed_jobs", _task_failure_sql_or_empty(
                    session,
                    "scheduled_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())",
                    5,
                    company,
                )),
                ("task_health", _task_health_sql_or_empty(
                    session,
                    "scheduled_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())",
                    company,
                )),
                ("what_changed", f"""
                    WITH today_q AS (
                        SELECT COUNT(*) AS q,
                               SUM(CASE WHEN {failed_pred_q} THEN 1 ELSE 0 END) AS fails
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        WHERE q.start_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
                          {wh_filter_q} {db_filter_q} {user_filter_q}
                    ),
                    yday_q AS (
                        SELECT COUNT(*) AS q,
                               SUM(CASE WHEN {failed_pred_q} THEN 1 ELSE 0 END) AS fails
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        WHERE q.start_time >= DATEADD('hours', -48, CURRENT_TIMESTAMP())
                          AND q.start_time <  DATEADD('hours', -24, CURRENT_TIMESTAMP())
                          {wh_filter_q} {db_filter_q} {user_filter_q}
                    ),
                    today_c AS (
                        SELECT SUM(credits_used) AS credits
                        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                        WHERE start_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
                          {wh_filter_m}
                    ),
                    yday_c AS (
                        SELECT SUM(credits_used) AS credits
                        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                        WHERE start_time >= DATEADD('hours', -48, CURRENT_TIMESTAMP())
                          AND start_time < DATEADD('hours', -24, CURRENT_TIMESTAMP())
                          {wh_filter_m}
                    )
                    SELECT today_q.q - yday_q.q AS query_delta,
                           ROUND(COALESCE(today_c.credits, 0) - COALESCE(yday_c.credits, 0), 4) AS credit_delta,
                           today_q.fails - yday_q.fails AS failure_delta
                    FROM today_q, yday_q, today_c, yday_c
                """),
            ]:
                try:
                    hd[key] = run_query_or_raise(sql)
                except Exception:
                    hd[key] = pd.DataFrame()

            st.session_state["health_data"] = hd
            st.session_state["_health_ts"]  = datetime.now().isoformat()
            st.session_state["_health_filter_sig"] = filter_sig
            mark_loaded("account_health")

        hd = st.session_state.get("health_data", {})

        live_df    = hd.get("live",    pd.DataFrame())
        live_source = hd.get("_live_source", "ACCOUNT_USAGE")
        burn_df    = hd.get("burn",    pd.DataFrame())
        err_df     = hd.get("errors",  pd.DataFrame())
        storage_df = hd.get("storage", pd.DataFrame())
        query_stats_df = hd.get("query_stats", pd.DataFrame())
        task_health_df = hd.get("task_health", pd.DataFrame())
        warehouse_pressure_df = hd.get("warehouse_pressure", pd.DataFrame())
        live_val  = safe_int(live_df["ACTIVE_COUNT"].iloc[0]) if not live_df.empty else 0
        queued    = safe_int(live_df["QUEUED_COUNT"].iloc[0]) if not live_df.empty else 0
        last24    = safe_float(burn_df["LAST_24H"].iloc[0]) if not burn_df.empty else 0
        prior24   = safe_float(burn_df["PRIOR_24H"].iloc[0]) if not burn_df.empty else 0
        err_count = safe_int(err_df["ERR_COUNT"].iloc[0]) if not err_df.empty else 0
        stor_tb   = safe_float(storage_df["STORAGE_TB"].iloc[0]) if not storage_df.empty else 0
        pct_delta = ((last24 - prior24) / prior24 * 100) if prior24 > 0 else 0
        health = executive_health_score({
            "total_queries": safe_float(query_stats_df["TOTAL_QUERIES"].iloc[0]) if not query_stats_df.empty else 0,
            "failed_queries": err_count,
            "queued_queries": safe_float(query_stats_df["QUEUED_QUERIES"].iloc[0]) if not query_stats_df.empty else queued,
            "avg_elapsed_sec": safe_float(query_stats_df["AVG_ELAPSED_SEC"].iloc[0]) if not query_stats_df.empty else 0,
            "task_runs": safe_float(task_health_df["TASK_RUNS"].iloc[0]) if not task_health_df.empty else 0,
            "failed_tasks": safe_float(task_health_df["FAILED_TASKS"].iloc[0]) if not task_health_df.empty else 0,
            "active_warehouses": safe_float(warehouse_pressure_df["ACTIVE_WAREHOUSES"].iloc[0]) if not warehouse_pressure_df.empty else 0,
            "pressure_warehouses": safe_float(warehouse_pressure_df["PRESSURE_WAREHOUSES"].iloc[0]) if not warehouse_pressure_df.empty else 0,
            "current_credits": last24,
            "prior_credits": prior24,
            "current_storage_tb": stor_tb,
            "prior_storage_tb": stor_tb,
        })
        health_score = health["score"]
        score_label = health["label"]

        k1, k2, k3, k4, k5, k6, k7 = st.columns(7)
        k1.metric("Health Score",   f"{health_score:.0f}", score_label)
        k2.metric("Active Queries", live_val)
        k3.metric("Queued",         queued)
        k4.metric("Credits (24h)",  f"{last24:,.0f}", delta=f"{pct_delta:+.1f}%")
        k5.metric("Cost (24h)",     f"${credits_to_dollars(last24):,.0f}")
        k6.metric("Storage",        f"{stor_tb:.1f} TB")
        k7.metric("Failed (24h)",   err_count, delta_color="inverse")
        st.caption(
            " | ".join([
                metric_confidence_label("composite"),
                metric_confidence_label("exact") + " for source counts",
                freshness_note(live_source),
            ])
        )
        with st.expander("Health score contributors", expanded=False):
            st.dataframe(pd.DataFrame(health["components"]), use_container_width=True, height=260)

        st.divider()
        show_loaded_time("account_health")

        r1, r2 = st.columns([2, 1])
        with r1:
            st.markdown("**🚨 Alert Center**")
            alerts = []
            if err_count > 10:  alerts.append({"Severity": "🔴", "Alert": "High error rate",  "Detail": f"{err_count} failures"})
            if pct_delta > 30:  alerts.append({"Severity": "🟡", "Alert": "Credit spike",      "Detail": f"+{pct_delta:.0f}%"})
            if queued > 5:      alerts.append({"Severity": "🟡", "Alert": "Queue pressure",    "Detail": f"{queued} queued"})
            if alerts:
                st.dataframe(pd.DataFrame(alerts), use_container_width=True)
            else:
                st.success("✅ No active alerts")

        with r2:
            st.markdown("**⚡ Quick Nav**")
            def _jump(tgt): st.session_state["nav_section"] = tgt
            for lbl, tgt in [
                ("🔴 Live",  "🔴 Live Monitor"),
                ("🔍 Query", "🔍 Query Analysis"),
                ("💸 Cost",  "💸 Cost & Contract"),
                ("🛠️ DBA",  "🔀 Change & Drift"),
            ]:
                st.button(lbl, key=f"jump_{lbl}", on_click=_jump, args=(tgt,))

        st.divider()
        st.markdown("**Executive Landing Signals**")
        e1, e2, e3, e4 = st.columns(4)

        with e1:
            st.markdown("**Top 5 cost drivers today**")
            cost_df = hd.get("cost_drivers", pd.DataFrame())
            if cost_df is not None and not cost_df.empty:
                cost_df["EST_COST"] = cost_df["TOTAL_CREDITS"].apply(
                    lambda x: credits_to_dollars(x, credit_price)
                )
                st.dataframe(cost_df, use_container_width=True, height=220)
                if "USER_NAME" in cost_df.columns:
                    sel_user = st.selectbox(
                        "→ Drill into user", ["(none)"] + cost_df["USER_NAME"].dropna().tolist(),
                        key="ah_drill_user", label_visibility="collapsed",
                    )
                    if sel_user and sel_user != "(none)":
                        if st.button(f"Open Cost & Contract for {sel_user}", key="ah_drill_user_btn"):
                            _drill_to(
                                "💸 Cost & Contract",
                                user_filter=sel_user,
                                workflow_key="cost_contract_workflow",
                                workflow="Explain bill / attribution / contract",
                            )
            else:
                st.info("No cost driver data yet.")

        with e2:
            st.markdown("**Top 5 failed jobs/tasks**")
            failed_df = hd.get("failed_jobs", pd.DataFrame())
            if failed_df is not None and not failed_df.empty:
                st.dataframe(failed_df, use_container_width=True, height=220)
                if st.button("→ Task Management", key="ah_drill_tasks"):
                    _drill_to("⚙️ Task Management")
            else:
                st.success("No failed tasks in the last 24h.")

        with e3:
            st.markdown("**What changed since yesterday**")
            change_df = hd.get("what_changed", pd.DataFrame())
            if change_df is not None and not change_df.empty:
                row = change_df.iloc[0]
                st.metric("Queries",      f"{safe_int(row.get('QUERY_DELTA',0)):+,}")
                st.metric("Credits",      f"{safe_float(row.get('CREDIT_DELTA',0)):+,.2f}")
                st.metric("Failures",     f"{safe_int(row.get('FAILURE_DELTA',0)):+,}", delta_color="inverse")
            else:
                st.info("Change summary unavailable.")

        with e4:
            st.markdown("**Recommended next action**")
            st.info("Use Cost & Contract for optimization actions, action queue triage, and Teams-ready alerting.")
            if st.button("Open Cost & Contract", key="ah_open_recommendations"):
                _drill_to(
                    "💸 Cost & Contract",
                    workflow_key="cost_contract_workflow",
                    workflow="Recommendations and action queue",
                )

        st.divider()
        st.markdown("**OVERWATCH Cost of Monitoring**")
        mon_days = st.slider("Monitoring cost lookback days", 1, 30, 7, key="ah_monitoring_cost_days")
        if st.button("Load monitoring cost", key="ah_monitoring_cost_load"):
            mon_df = run_query(
                build_monitoring_cost_sql(mon_days),
                ttl_key=f"ah_monitoring_cost_{company}_{mon_days}",
                tier="historical",
                section="Account Health",
            )
            st.session_state["ah_monitoring_cost"] = mon_df
        mon_df = st.session_state.get("ah_monitoring_cost")
        if mon_df is not None and not mon_df.empty:
            mon_df = mon_df.copy()
            mon_df["EST_COST"] = mon_df["CREDITS"].apply(lambda x: credits_to_dollars(x, credit_price))
            m1, m2, m3 = st.columns(3)
            m1.metric("Observed Components", len(mon_df))
            m2.metric("Credits", format_credits(safe_float(mon_df["CREDITS"].sum())))
            m3.metric("Estimated Cost", f"${safe_float(mon_df['EST_COST'].sum()):,.2f}")
            st.caption("Keeps the monitor honest: app-tagged queries, Streamlit warehouse, Cortex, and alert task cost.")
            st.dataframe(mon_df, use_container_width=True, height=220)
            download_csv(mon_df, "overwatch_monitoring_cost.csv")
        elif mon_df is not None:
            st.info("No tagged OVERWATCH monitoring cost found in the selected window.")

        if exceptions_only:
            st.caption("Exceptions-only mode intentionally stops here to avoid loading lower-priority drilldowns.")
            return

        st.divider()
        st.markdown("**🏭 Warehouse Pressure (last 1h)**")
        try:
            df_wp = run_query_or_raise(f"""
                SELECT warehouse_name, {pressure_wh_size_expr} AS warehouse_size, COUNT(*) AS queries,
                       {queued_count_expr_plain} AS queued
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE start_time >= DATEADD('hours',-1,CURRENT_TIMESTAMP())
                  AND warehouse_name IS NOT NULL
                  {wh_filter_m}
                GROUP BY warehouse_name ORDER BY queries DESC LIMIT 8
            """)
            if not df_wp.empty:
                top_wh = df_wp.sort_values(["QUEUED","QUERIES"], ascending=False).iloc[0]
                st.metric(
                    "Top warehouse under pressure",
                    top_wh["WAREHOUSE_NAME"],
                    f"{int(top_wh['QUEUED'])} queued / {int(top_wh['QUERIES'])} queries",
                    delta_color="inverse",
                )
                render_drillable_bar_chart(
                    df_wp, dimension="WAREHOUSE_NAME", measure="QUERIES",
                    key="ah_warehouse_pressure", title="Warehouse pressure drill-down",
                    drilldown_column="warehouse_name", lookback_hours=24, top_n=8,
                )
                st.markdown("**→ Jump to Warehouse Health:**")
                wh_cols = st.columns(min(len(df_wp), 4))
                for idx, wh_row in df_wp.head(4).iterrows():
                    wh_name = wh_row["WAREHOUSE_NAME"]
                    with wh_cols[idx % 4]:
                        if st.button(wh_name, key=f"ah_wh_drill_{wh_name}"):
                            _drill_to("🏭 Warehouse Health", wh_filter=wh_name)
        except Exception as e:
            st.caption(f"Warehouse pressure unavailable: {format_snowflake_error(e)}")

    # ── RESOURCE MONITORS ─────────────────────────────────────────────────────
    with tab_resmon:
        st.header("📋 Resource Monitor Dashboard")
        st.caption("Credit quota vs. consumed — with suspend threshold validation.")

        if st.button("Load Resource Monitors", key="resmon_load"):
            try:
                rm_object = "SNOWFLAKE.ACCOUNT_USAGE.RESOURCE_MONITORS"
                rm_cols = set(filter_existing_columns(
                    session,
                    rm_object,
                    [
                        "NAME", "CREATED", "CREDIT_QUOTA", "USED_CREDITS",
                        "REMAINING_CREDITS", "OWNER", "NOTIFY", "SUSPEND",
                        "SUSPEND_IMMEDIATE", "WAREHOUSES",
                    ],
                ))
                if "NAME" not in rm_cols:
                    raise ValueError("RESOURCE_MONITORS does not expose NAME for this role/account.")

                def _rm_expr(col: str, fallback: str, alias: str | None = None) -> str:
                    output = alias or col.lower()
                    if col in rm_cols:
                        if col == "WAREHOUSES":
                            return f"TO_VARCHAR({col.lower()}) AS {output}"
                        return f"{col.lower()} AS {output}"
                    return f"{fallback} AS {output}"

                df_rm = run_query(f"""
                    SELECT {_rm_expr("NAME", "NULL::VARCHAR")},
                           {_rm_expr("CREATED", "NULL::TIMESTAMP_NTZ")},
                           {_rm_expr("CREDIT_QUOTA", "0::FLOAT")},
                           {_rm_expr("USED_CREDITS", "0::FLOAT")},
                           {_rm_expr("REMAINING_CREDITS", "0::FLOAT")},
                           {_rm_expr("OWNER", "NULL::VARCHAR")},
                           {_rm_expr("NOTIFY", "NULL::VARCHAR")},
                           {_rm_expr("SUSPEND", "NULL::VARCHAR")},
                           {_rm_expr("SUSPEND_IMMEDIATE", "NULL::VARCHAR")},
                           {_rm_expr("WAREHOUSES", "NULL::VARCHAR")}
                    FROM SNOWFLAKE.ACCOUNT_USAGE.RESOURCE_MONITORS
                """, ttl_key="account_health_resource_monitors", tier="standard")
                if company != "ALL" and not df_rm.empty and "WAREHOUSES" in df_rm.columns:
                    def _monitor_in_company(value) -> bool:
                        text = str(value or "")
                        if not text.strip():
                            return False
                        tokens = [part.strip(" []'\"") for part in text.replace(",", " ").split()]
                        return any(company_value_allowed(token, "warehouse", company) for token in tokens)

                    df_rm = df_rm[df_rm["WAREHOUSES"].apply(_monitor_in_company)]
                st.session_state["ah_df_resmon"] = df_rm
            except Exception as e:
                st.warning(f"Resource monitor data unavailable: {format_snowflake_error(e)}")

        if st.session_state.get("ah_df_resmon") is not None and not st.session_state["ah_df_resmon"].empty:
            df_rm = st.session_state["ah_df_resmon"]
            total_quota = df_rm["CREDIT_QUOTA"].sum()
            total_used  = df_rm["USED_CREDITS"].sum()
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Quota",   format_credits(total_quota))
            c2.metric("Total Used",    format_credits(total_used))
            c3.metric("Overall Usage", f"{(total_used/total_quota*100) if total_quota else 0:.1f}%")

            for _, row in df_rm.iterrows():
                quota   = safe_float(row.get("CREDIT_QUOTA",0))
                used    = safe_float(row.get("USED_CREDITS",0))
                name    = row.get("NAME","Unknown")
                pct     = (used / quota * 100) if quota > 0 else 0
                suspend = row.get("SUSPEND","")
                s_imm   = row.get("SUSPEND_IMMEDIATE","")
                cols = st.columns(5)
                cols[0].metric(f"{name} Quota", format_credits(quota))
                cols[1].metric("Used",          format_credits(used))
                cols[2].metric("Remaining",     format_credits(safe_float(row.get("REMAINING_CREDITS",0))))
                cols[3].metric("Usage %",       f"{pct:.1f}%")
                cols[4].metric("Est. $",        f"${credits_to_dollars(used):,.2f}")
                if pct > 100:  st.error(f"**{name}** OVER BUDGET at {pct:.0f}%")
                elif pct > 80: st.warning(f"**{name}** at {pct:.0f}% — approaching limit")
                else:          st.success(f"**{name}** at {pct:.0f}% — on track")
                if not suspend and not s_imm:
                    st.warning(f"⚠️ **{name}** has no suspend threshold.")
            download_csv(df_rm, "resource_monitors.csv")

    # ── MORNING REPORT ────────────────────────────────────────────────────────
    with tab_morning:
        st.header("☀️ Morning Health Report")
        st.caption("Overnight summary: failures, cost spikes, longest queries (last 12h).")

        if st.button("Generate Morning Report", key="morning_gen"):
            with st.spinner("Generating overnight report..."):
                md = {}
                for key, sql in [
                    ("failures", f"""
                        SELECT query_type, COUNT(*) AS fail_count,
                               COUNT(DISTINCT user_name) AS affected_users,
                               COUNT(DISTINCT warehouse_name) AS affected_wh
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                        WHERE start_time >= DATEADD('hours',-12,CURRENT_TIMESTAMP())
                          AND {failed_pred_plain}
                          {wh_filter_m} {get_db_filter_clause("database_name", company)} {get_user_filter_clause("user_name", company)}
                        GROUP BY query_type ORDER BY fail_count DESC
                    """),
                    ("long_queries", f"""
                        SELECT query_id, user_name, warehouse_name,
                               SUBSTR(query_text,1,100) AS query_preview,
                               total_elapsed_time/1000  AS elapsed_sec,
                               execution_status
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                        WHERE start_time >= DATEADD('hours',-12,CURRENT_TIMESTAMP())
                          AND warehouse_name IS NOT NULL
                          {wh_filter_m} {get_db_filter_clause("database_name", company)} {get_user_filter_clause("user_name", company)}
                        ORDER BY total_elapsed_time DESC LIMIT 10
                    """),
                    ("credits", f"""
                        SELECT SUM(credits_used) AS overnight_credits
                        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                        WHERE start_time >= DATEADD('hours',-12,CURRENT_TIMESTAMP())
                          {wh_filter_m}
                    """),
                ]:
                    try:
                        md[key] = run_query(sql, ttl_key=f"account_health_morning_{company}_{key}", tier="recent")
                    except Exception:
                        md[key] = pd.DataFrame()
                st.session_state["morning_data"] = md

        if st.session_state.get("morning_data"):
            md = st.session_state["morning_data"]
            overnight_cr = safe_float(md["credits"]["OVERNIGHT_CREDITS"].iloc[0]) if not md["credits"].empty else 0
            st.metric("Overnight Credits (12h)", format_credits(overnight_cr))
            if not md["failures"].empty:
                st.subheader("❌ Overnight Failures by Type")
                st.dataframe(md["failures"], use_container_width=True)
                download_csv(md["failures"], "morning_failures.csv")
            else:
                st.success("✅ No query failures overnight")
            if not md["long_queries"].empty:
                st.subheader("🐌 Longest Running Queries")
                st.dataframe(md["long_queries"], use_container_width=True)
                download_csv(md["long_queries"], "morning_long_queries.csv")
            brief_lines = [
                "# OVERWATCH Morning Brief",
                f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"Overnight credits: {format_credits(overnight_cr)}",
                f"Failure groups: {0 if md['failures'].empty else len(md['failures'])}",
                f"Long-query watchlist: {0 if md['long_queries'].empty else len(md['long_queries'])}",
            ]
            st.download_button(
                "Export Morning Brief",
                "\n".join(brief_lines),
                file_name=f"overwatch_morning_brief_{datetime.now().strftime('%Y%m%d')}.md",
                mime="text/markdown",
                key="morning_brief_export",
            )

    # ── EXECUTIVE BRIEFING (NEW) ───────────────────────────────────────────────
    with tab_briefing:
        st.header("📋 Executive Briefing")
        st.caption(
            "Plain-English summary generated by Cortex AI from live OVERWATCH data. "
            "Designed to be copied into an email or Teams message to leadership — no dashboard login required."
        )

        briefing_window = st.selectbox(
            "Report window",
            ["Last 24 hours", "Last 7 days", "Last 30 days"],
            key="br_window",
        )

        hours_map = {"Last 24 hours": 24, "Last 7 days": 168, "Last 30 days": 720}
        br_hours  = hours_map[briefing_window]

        if st.button("✨ Generate Executive Briefing", key="br_generate", type="primary"):
            with st.spinner("Collecting metrics and generating briefing via Cortex AI..."):
                br_data = {}

                # ── Collect metrics ────────────────────────────────────────────
                metric_queries = {
                    "credits": f"""
                        SELECT SUM(CASE WHEN start_time >= DATEADD('hours',-{br_hours},CURRENT_TIMESTAMP())
                                        AND start_time <  CURRENT_TIMESTAMP()
                                   THEN credits_used ELSE 0 END) AS period_credits,
                               SUM(CASE WHEN start_time >= DATEADD('hours',-{br_hours*2},CURRENT_TIMESTAMP())
                                        AND start_time <  DATEADD('hours',-{br_hours},CURRENT_TIMESTAMP())
                                   THEN credits_used ELSE 0 END) AS prior_period_credits
                        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                        WHERE start_time >= DATEADD('hours',-{br_hours*2},CURRENT_TIMESTAMP())
                          AND start_time <  CURRENT_TIMESTAMP()
                          {wh_filter_m}
                    """,
                    "failures": f"""
                        SELECT COUNT(*) AS fail_count
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                        WHERE start_time >= DATEADD('hours',-{br_hours},CURRENT_TIMESTAMP())
                          AND {failed_pred_plain}
                          {wh_filter_m} {get_db_filter_clause("database_name", company)} {get_user_filter_clause("user_name", company)}
                    """,
                    "top_driver": f"""
                        WITH {build_metered_credit_cte(hours_back=br_hours, include_recent=True)}
                        SELECT q.user_name, q.warehouse_name,
                               ROUND(SUM(COALESCE(pqc.metered_credits,0)),2) AS credits
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                        WHERE q.start_time >= DATEADD('hours',-{br_hours},CURRENT_TIMESTAMP())
                          AND q.warehouse_name IS NOT NULL
                          {wh_filter_q} {db_filter_q} {user_filter_q}
                        GROUP BY q.user_name, q.warehouse_name
                        ORDER BY credits DESC LIMIT 1
                    """,
                    "failed_tasks": _task_failure_sql_or_empty(
                        session,
                        f"scheduled_time >= DATEADD('hours',-{int(br_hours)},CURRENT_TIMESTAMP())",
                        1,
                        company,
                    ),
                    "storage": f"""
                        SELECT COALESCE(
                            ROUND(SUM(COALESCE(average_database_bytes,0)+COALESCE(average_failsafe_bytes,0))/POWER(1024,4),2),
                            0
                        ) AS storage_tb
                        FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
                        WHERE usage_date = (SELECT MAX(usage_date)
                                            FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY)
                          {get_db_filter_clause("database_name", company)}
                    """,
                    "queued": f"""
                        SELECT {queued_count_expr_q} AS queued
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        WHERE q.start_time >= DATEADD('hours', -1, CURRENT_TIMESTAMP())
                          AND UPPER(q.execution_status) IN ('RUNNING','QUEUED','BLOCKED')
                          {wh_filter_q} {db_filter_q} {user_filter_q}
                    """,
                }

                for k, sql in metric_queries.items():
                    try:
                        br_data[k] = run_query(sql, ttl_key=f"account_health_brief_{company}_{k}_{br_hours}", tier="recent")
                    except Exception:
                        br_data[k] = pd.DataFrame()

                # Contract utilization
                try:
                    ytd_source = "SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY" if company == "ALL" else "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
                    ytd_filter = "" if company == "ALL" else wh_filter_m
                    df_ytd = run_query(f"""
                        SELECT SUM(credits_used) AS ytd_credits
                        FROM {ytd_source}
                        WHERE start_time >= DATE_TRUNC('year', CURRENT_DATE())
                          AND start_time < DATEADD('hour', -24, CURRENT_TIMESTAMP())
                          {ytd_filter}
                    """, ttl_key=f"account_health_brief_contract_ytd_{company}", tier="historical")
                    committed = st.session_state.get("cc_committed_credits", 100000)
                    ytd       = safe_float(df_ytd["YTD_CREDITS"].iloc[0]) if not df_ytd.empty else 0
                    br_data["contract_pct"] = (ytd / committed * 100) if committed > 0 else None
                except Exception:
                    br_data["contract_pct"] = None

                # ── Extract values ────────────────────────────────────────────
                cr24     = safe_float(br_data["credits"]["PERIOD_CREDITS"].iloc[0]) if not br_data["credits"].empty else 0
                cr_prior = safe_float(br_data["credits"]["PRIOR_PERIOD_CREDITS"].iloc[0]) if not br_data["credits"].empty else 0
                failures = safe_int(br_data["failures"]["FAIL_COUNT"].iloc[0]) if not br_data["failures"].empty else 0
                stor_tb  = safe_float(br_data["storage"]["STORAGE_TB"].iloc[0]) if not br_data["storage"].empty else 0
                queued   = safe_int(br_data["queued"]["QUEUED"].iloc[0]) if not br_data["queued"].empty else 0

                top_driver      = ""
                top_driver_cost = 0.0
                if not br_data["top_driver"].empty:
                    td = br_data["top_driver"].iloc[0]
                    top_driver      = f"{td.get('USER_NAME','')} on {td.get('WAREHOUSE_NAME','')}"
                    top_driver_cost = credits_to_dollars(safe_float(td.get("CREDITS",0)), credit_price)

                failed_task = ""
                if not br_data["failed_tasks"].empty:
                    failed_task = str(br_data["failed_tasks"]["TASK_NAME"].iloc[0])

                metric_payload = {
                    "cr24": cr24, "cr_prior": cr_prior,
                    "failures": failures, "queued": queued,
                    "stor_tb": stor_tb,
                    "contract_pct": br_data.get("contract_pct"),
                    "top_driver": top_driver,
                    "top_driver_cost": top_driver_cost,
                    "failed_task": failed_task,
                }

                # ── Call Cortex ────────────────────────────────────────────────
                prompt = _build_briefing_prompt(metric_payload, credit_price, company)
                prompt_esc = prompt.replace("'", "''")

                try:
                    result = session.sql(
                        f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', '{prompt_esc}') AS briefing"
                    ).collect()
                    briefing_text = result[0]["BRIEFING"] or ""
                except Exception as e:
                    # Graceful fallback — structured text brief if Cortex unavailable
                    cr_delta = ((cr24 - cr_prior) / cr_prior * 100) if cr_prior > 0 else 0
                    briefing_text = (
                        f"OVERWATCH Executive Briefing — {datetime.now().strftime('%B %d, %Y')}\n\n"
                        f"ALFA Insurance Snowflake consumed {cr24:,.0f} credits "
                        f"(${credits_to_dollars(cr24, credit_price):,.2f}) "
                        f"over the {briefing_window.lower()}, "
                        f"{'up' if cr_delta > 0 else 'down'} {abs(cr_delta):.1f}% vs the prior period. "
                        f"The top cost driver was {top_driver} at ${top_driver_cost:,.2f}. "
                        f"There were {failures} query failures recorded. "
                        f"Storage stands at {stor_tb:.1f} TB.\n\n"
                        f"(Cortex AI unavailable: {format_snowflake_error(e)}. Plain summary generated from raw metrics.)"
                    )

                st.session_state["ah_briefing_text"] = briefing_text
                st.session_state["ah_briefing_ts"]   = datetime.now().strftime("%Y-%m-%d %H:%M")
                st.session_state["ah_briefing_window"] = briefing_window

        # ── Render briefing ────────────────────────────────────────────────────
        if st.session_state.get("ah_briefing_text"):
            briefing_text   = st.session_state["ah_briefing_text"]
            briefing_ts     = st.session_state.get("ah_briefing_ts", "")
            briefing_window = st.session_state.get("ah_briefing_window", "")

            st.divider()

            # Visual card
            st.markdown(f"""
            <div style="background:rgba(56,189,248,0.05);border:1px solid rgba(56,189,248,0.2);
                        border-radius:12px;padding:24px;margin:8px 0;">
                <div style="font-size:0.7rem;color:#64748b;margin-bottom:12px;letter-spacing:1px;text-transform:uppercase;">
                    OVERWATCH Executive Briefing · {company} · {briefing_window} · Generated {briefing_ts}
                </div>
                <div style="color:#e2e8f0;font-size:0.95rem;line-height:1.7;white-space:pre-wrap;">{briefing_text}</div>
            </div>
            """, unsafe_allow_html=True)

            # Export options
            st.divider()
            st.subheader("Export & Share")
            col_e1, col_e2, col_e3 = st.columns(3)

            # Plain text download
            full_text = (
                f"OVERWATCH Executive Briefing\n"
                f"Company: {company}\n"
                f"Period: {briefing_window}\n"
                f"Generated: {briefing_ts}\n"
                f"{'─'*60}\n\n"
                f"{briefing_text}\n\n"
                f"{'─'*60}\n"
                f"Source: OVERWATCH V3 — Snowflake DBA Command Center\n"
                f"Data from: SNOWFLAKE.ACCOUNT_USAGE\n"
            )
            with col_e1:
                st.download_button(
                    "📄 Download .txt",
                    full_text,
                    file_name=f"overwatch_executive_brief_{datetime.now().strftime('%Y%m%d')}.txt",
                    mime="text/plain",
                    key="br_dl_txt",
                    use_container_width=True,
                )

            # Markdown download
            md_text = (
                f"# OVERWATCH Executive Briefing\n\n"
                f"**Company:** {company}  \n"
                f"**Period:** {briefing_window}  \n"
                f"**Generated:** {briefing_ts}  \n\n"
                f"---\n\n"
                f"{briefing_text}\n\n"
                f"---\n\n"
                f"*Generated by OVERWATCH V3 — Snowflake DBA Command Center*\n"
            )
            with col_e2:
                st.download_button(
                    "📝 Download .md",
                    md_text,
                    file_name=f"overwatch_brief_{datetime.now().strftime('%Y%m%d')}.md",
                    mime="text/markdown",
                    key="br_dl_md",
                    use_container_width=True,
                )

            # Copy-ready Teams/email text
            with col_e3:
                if st.button("📋 Copy to clipboard", key="br_copy", use_container_width=True):
                    st.code(briefing_text, language=None)
                    st.caption("Select all text above and copy.")

            # Regenerate note
            st.caption(
                "💡 Tip: set your annual committed credits in Cost & Contract → Contract Utilization "
                "before generating the briefing to include contract pacing in the narrative."
            )
