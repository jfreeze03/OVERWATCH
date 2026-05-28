# sections/account_health.py — Account Health: KPIs, Resource Monitors, Morning Report, Executive Briefing
import streamlit as st
import pandas as pd
from datetime import datetime
from utils import (
    get_session, run_query, format_credits,
    credits_to_dollars, download_csv, mark_loaded, show_loaded_time,
    build_metered_credit_cte, render_drillable_bar_chart, render_query_drilldown,
    get_wh_filter_clause, get_db_filter_clause, get_user_filter_clause,
    get_global_filter_clause,
)


def _drill_to(section: str, wh_filter: str = "", user_filter: str = ""):
    st.session_state["nav_section"] = section
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

    tab_overview, tab_resmon, tab_morning, tab_briefing = st.tabs([
        "Overview", "Resource Monitors", "Morning Report", "📋 Executive Briefing"
    ])

    # ── OVERVIEW ──────────────────────────────────────────────────────────────
    with tab_overview:
        st.header("🏠 Account Health — Command Center")

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
            or cache_age > 60
            or "health_data" not in st.session_state
            or st.session_state.get("_health_filter_sig") != filter_sig
        ):
            hd = {}
            for key, sql in [
                ("live", f"""
                    SELECT COUNT(*) AS active_count,
                           SUM(CASE WHEN execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END) AS queued_count,
                           SUM(CASE WHEN execution_status ILIKE '%BLOCKED%' THEN 1 ELSE 0 END) AS blocked_count
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    WHERE q.start_time >= DATEADD('hours',-1,CURRENT_TIMESTAMP())
                      AND q.execution_status IN ('RUNNING','QUEUED','BLOCKED','RESUMING_WAREHOUSE')
                      {wh_filter_q} {db_filter_q} {user_filter_q}
                """),
                ("burn", f"""
                    SELECT SUM(CASE WHEN start_time >= DATEADD('hours',-24,CURRENT_TIMESTAMP())
                               THEN credits_used ELSE 0 END) AS last_24h,
                           SUM(CASE WHEN start_time >= DATEADD('hours',-48,CURRENT_TIMESTAMP())
                                    AND  start_time <  DATEADD('hours',-24,CURRENT_TIMESTAMP())
                               THEN credits_used ELSE 0 END) AS prior_24h
                    FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
                    WHERE start_time >= DATEADD('hours',-48,CURRENT_TIMESTAMP())
                      {get_wh_filter_clause("name", company)}
                """),
                ("errors", f"""
                    SELECT COUNT(*) AS err_count
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    WHERE q.start_time >= DATEADD('hours',-24,CURRENT_TIMESTAMP())
                      AND execution_status = 'FAILED_WITH_ERROR'
                      {wh_filter_q} {db_filter_q} {user_filter_q}
                """),
                ("storage", f"""
                    SELECT ROUND(SUM(average_database_bytes+average_failsafe_bytes)/POWER(1024,4),2) AS storage_tb
                    FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
                    WHERE usage_date = (SELECT MAX(usage_date)
                                        FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY)
                      {get_db_filter_clause("database_name", company)}
                """),
                ("cost_drivers", f"""
                    WITH {build_metered_credit_cte(hours_back=48, include_recent=True)}
                    SELECT q.user_name, q.warehouse_name, MAX(q.warehouse_size) AS warehouse_size,
                           COUNT(*) AS query_count,
                           ROUND(SUM(COALESCE(pqc.metered_credits,0)), 4) AS total_credits,
                           ROUND(SUM(q.bytes_scanned)/POWER(1024,3), 2) AS gb_scanned
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                    WHERE q.start_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
                      AND q.warehouse_name IS NOT NULL
                      {wh_filter_q} {db_filter_q} {user_filter_q} {global_filter_q}
                    GROUP BY q.user_name, q.warehouse_name
                    ORDER BY total_credits DESC
                    LIMIT 5
                """),
                ("failed_jobs", f"""
                    SELECT COALESCE(name, root_task_id, query_id) AS job_name,
                           database_name, schema_name,
                           COUNT(*) AS failures,
                           MAX(scheduled_time) AS last_failure,
                           MAX(error_message) AS last_error
                    FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
                    WHERE scheduled_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
                      AND state = 'FAILED'
                      {get_db_filter_clause("database_name", company)}
                    GROUP BY COALESCE(name, root_task_id, query_id), database_name, schema_name
                    ORDER BY failures DESC, last_failure DESC
                    LIMIT 5
                """),
                ("what_changed", f"""
                    WITH today AS (
                        SELECT COUNT(*) AS q, SUM(credits_used_cloud_services) AS cloud_cr,
                               SUM(CASE WHEN execution_status='FAILED_WITH_ERROR' THEN 1 ELSE 0 END) AS fails
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        WHERE q.start_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
                          {wh_filter_q} {db_filter_q} {user_filter_q}
                    ),
                    yday AS (
                        SELECT COUNT(*) AS q, SUM(credits_used_cloud_services) AS cloud_cr,
                               SUM(CASE WHEN execution_status='FAILED_WITH_ERROR' THEN 1 ELSE 0 END) AS fails
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        WHERE q.start_time >= DATEADD('hours', -48, CURRENT_TIMESTAMP())
                          AND q.start_time <  DATEADD('hours', -24, CURRENT_TIMESTAMP())
                          {wh_filter_q} {db_filter_q} {user_filter_q}
                    )
                    SELECT today.q - yday.q AS query_delta,
                           ROUND(today.cloud_cr - yday.cloud_cr, 4) AS cloud_credit_delta,
                           today.fails - yday.fails AS failure_delta
                    FROM today, yday
                """),
            ]:
                try:
                    hd[key] = run_query(sql, ttl_key=f"account_health_{key}_{filter_sig}", tier="live")
                except Exception:
                    hd[key] = pd.DataFrame()

            st.session_state["health_data"] = hd
            st.session_state["_health_ts"]  = datetime.now().isoformat()
            st.session_state["_health_filter_sig"] = filter_sig
            mark_loaded("account_health")

        hd = st.session_state.get("health_data", {})

        live_df    = hd.get("live",    pd.DataFrame())
        burn_df    = hd.get("burn",    pd.DataFrame())
        err_df     = hd.get("errors",  pd.DataFrame())
        storage_df = hd.get("storage", pd.DataFrame())
        live_val  = int(live_df["ACTIVE_COUNT"].iloc[0])   if not live_df.empty    else 0
        queued    = int(live_df["QUEUED_COUNT"].iloc[0])   if not live_df.empty    else 0
        last24    = float(burn_df["LAST_24H"].iloc[0])     if not burn_df.empty    else 0
        prior24   = float(burn_df["PRIOR_24H"].iloc[0])    if not burn_df.empty    else 0
        err_count = int(err_df["ERR_COUNT"].iloc[0])       if not err_df.empty     else 0
        stor_tb   = float(storage_df["STORAGE_TB"].iloc[0]) if not storage_df.empty else 0
        pct_delta = ((last24 - prior24) / prior24 * 100) if prior24 > 0 else 0
        health_score = max(0, min(100,
            100 - min(err_count,50) - min(queued*4,20)
                - min(max(pct_delta,0)/2,20) - min(live_val,10)
        ))
        score_label = "Healthy" if health_score >= 85 else ("Watch" if health_score >= 70 else "At Risk")

        k1, k2, k3, k4, k5, k6, k7 = st.columns(7)
        k1.metric("Health Score",   f"{health_score:.0f}", score_label)
        k2.metric("Active Queries", live_val)
        k3.metric("Queued",         queued)
        k4.metric("Credits (24h)",  f"{last24:,.0f}", delta=f"{pct_delta:+.1f}%")
        k5.metric("Cost (24h)",     f"${credits_to_dollars(last24):,.0f}")
        k6.metric("Storage",        f"{stor_tb:.1f} TB")
        k7.metric("Failed (24h)",   err_count, delta_color="inverse")

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
                ("💸 Cost",  "💸 Cost Center"),
                ("🛠️ DBA",  "🛠️ DBA Tools"),
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
                        if st.button(f"Open Cost Center for {sel_user}", key="ah_drill_user_btn"):
                            _drill_to("💸 Cost Center", user_filter=sel_user)
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
                st.metric("Queries",      f"{int(row.get('QUERY_DELTA',0) or 0):+,}")
                st.metric("Cloud Credits",f"{float(row.get('CLOUD_CREDIT_DELTA',0) or 0):+,.2f}")
                st.metric("Failures",     f"{int(row.get('FAILURE_DELTA',0) or 0):+,}", delta_color="inverse")
            else:
                st.info("Change summary unavailable.")

        with e4:
            st.markdown("**Recommended next action**")
            st.info("Use Recommendations & Anomalies for optimization actions and Teams-ready alerting.")
            if st.button("Open Recommendations", key="ah_open_recommendations"):
                _drill_to("💡 Recommendations & Anomalies")

        st.divider()
        st.markdown("**🏭 Warehouse Pressure (last 1h)**")
        try:
            df_wp = run_query(f"""
                SELECT warehouse_name, MAX(warehouse_size) AS warehouse_size, COUNT(*) AS queries,
                       SUM(CASE WHEN execution_status IN ('QUEUED','BLOCKED') THEN 1 ELSE 0 END) AS queued
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE start_time >= DATEADD('hours',-1,CURRENT_TIMESTAMP())
                  AND warehouse_name IS NOT NULL
                  {wh_filter_m}
                GROUP BY warehouse_name ORDER BY queries DESC LIMIT 8
            """, ttl_key=f"account_health_wh_pressure_{filter_sig}", tier="live")
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
            st.caption(f"Warehouse pressure unavailable: {e}")

    # ── RESOURCE MONITORS ─────────────────────────────────────────────────────
    with tab_resmon:
        st.header("📋 Resource Monitor Dashboard")
        st.caption("Credit quota vs. consumed — with suspend threshold validation.")

        if st.button("Load Resource Monitors", key="resmon_load"):
            try:
                df_rm = run_query("""
                    SELECT name, created, credit_quota, used_credits, remaining_credits,
                           owner, notify, suspend, suspend_immediate, warehouses
                    FROM SNOWFLAKE.ACCOUNT_USAGE.RESOURCE_MONITORS
                """, ttl_key="account_health_resource_monitors", tier="standard")
                st.session_state["ah_df_resmon"] = df_rm
            except Exception as e:
                st.error(f"Error: {e}")

        if st.session_state.get("ah_df_resmon") is not None and not st.session_state["ah_df_resmon"].empty:
            df_rm = st.session_state["ah_df_resmon"]
            total_quota = df_rm["CREDIT_QUOTA"].sum()
            total_used  = df_rm["USED_CREDITS"].sum()
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Quota",   format_credits(total_quota))
            c2.metric("Total Used",    format_credits(total_used))
            c3.metric("Overall Usage", f"{(total_used/total_quota*100) if total_quota else 0:.1f}%")

            for _, row in df_rm.iterrows():
                quota   = float(row.get("CREDIT_QUOTA",0) or 0)
                used    = float(row.get("USED_CREDITS",0) or 0)
                name    = row.get("NAME","Unknown")
                pct     = (used / quota * 100) if quota > 0 else 0
                suspend = row.get("SUSPEND","")
                s_imm   = row.get("SUSPEND_IMMEDIATE","")
                cols = st.columns(5)
                cols[0].metric(f"{name} Quota", format_credits(quota))
                cols[1].metric("Used",          format_credits(used))
                cols[2].metric("Remaining",     format_credits(float(row.get("REMAINING_CREDITS",0) or 0)))
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
                    ("failures", """
                        SELECT query_type, COUNT(*) AS fail_count,
                               COUNT(DISTINCT user_name) AS affected_users,
                               COUNT(DISTINCT warehouse_name) AS affected_wh
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                        WHERE start_time >= DATEADD('hours',-12,CURRENT_TIMESTAMP())
                          AND execution_status = 'FAILED_WITH_ERROR'
                        GROUP BY query_type ORDER BY fail_count DESC
                    """),
                    ("long_queries", """
                        SELECT query_id, user_name, warehouse_name,
                               SUBSTR(query_text,1,100) AS query_preview,
                               total_elapsed_time/1000  AS elapsed_sec,
                               execution_status
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                        WHERE start_time >= DATEADD('hours',-12,CURRENT_TIMESTAMP())
                          AND warehouse_name IS NOT NULL
                        ORDER BY total_elapsed_time DESC LIMIT 10
                    """),
                    ("credits", """
                        SELECT SUM(credits_used) AS overnight_credits
                        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
                        WHERE start_time >= DATEADD('hours',-12,CURRENT_TIMESTAMP())
                    """),
                ]:
                    try:
                        md[key] = run_query(sql, ttl_key=f"account_health_morning_{key}", tier="standard")
                    except Exception:
                        md[key] = pd.DataFrame()
                st.session_state["morning_data"] = md

        if st.session_state.get("morning_data"):
            md = st.session_state["morning_data"]
            overnight_cr = float(md["credits"]["OVERNIGHT_CREDITS"].iloc[0]) if not md["credits"].empty else 0
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
                                        AND start_time <  DATEADD('hours',-24,CURRENT_TIMESTAMP())
                                   THEN credits_used ELSE 0 END) AS period_credits,
                               SUM(CASE WHEN start_time >= DATEADD('hours',-{br_hours*2},CURRENT_TIMESTAMP())
                                        AND start_time <  DATEADD('hours',-{br_hours},CURRENT_TIMESTAMP())
                                   THEN credits_used ELSE 0 END) AS prior_period_credits
                        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
                        WHERE start_time >= DATEADD('hours',-{br_hours*2},CURRENT_TIMESTAMP())
                          AND start_time <  DATEADD('hours',-24,CURRENT_TIMESTAMP())
                    """,
                    "failures": f"""
                        SELECT COUNT(*) AS fail_count
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                        WHERE start_time >= DATEADD('hours',-{br_hours},CURRENT_TIMESTAMP())
                          AND execution_status = 'FAILED_WITH_ERROR'
                    """,
                    "top_driver": f"""
                        WITH {build_metered_credit_cte(hours_back=br_hours)}
                        SELECT q.user_name, q.warehouse_name,
                               ROUND(SUM(COALESCE(pqc.metered_credits,0)),2) AS credits
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                        WHERE q.start_time >= DATEADD('hours',-{br_hours},CURRENT_TIMESTAMP())
                          AND q.warehouse_name IS NOT NULL
                        GROUP BY q.user_name, q.warehouse_name
                        ORDER BY credits DESC LIMIT 1
                    """,
                    "failed_tasks": f"""
                        SELECT name AS task_name, COUNT(*) AS failures
                        FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
                        WHERE scheduled_time >= DATEADD('hours',-{br_hours},CURRENT_TIMESTAMP())
                          AND state = 'FAILED'
                        GROUP BY name ORDER BY failures DESC LIMIT 1
                    """,
                    "storage": """
                        SELECT ROUND(SUM(average_database_bytes+average_failsafe_bytes)/POWER(1024,4),2) AS storage_tb
                        FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
                        WHERE usage_date = (SELECT MAX(usage_date)
                                            FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY)
                    """,
                    "queued": """
                        SELECT SUM(CASE WHEN execution_status='QUEUED' THEN 1 ELSE 0 END) AS queued
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        WHERE q.start_time >= DATEADD('hours', -1, CURRENT_TIMESTAMP())
                          AND execution_status IN ('RUNNING','QUEUED','BLOCKED')
                    """,
                }

                for k, sql in metric_queries.items():
                    try:
                        br_data[k] = run_query(sql, ttl_key=f"account_health_brief_{k}_{br_hours}", tier="standard")
                    except Exception:
                        br_data[k] = pd.DataFrame()

                # Contract utilization
                try:
                    df_ytd = run_query("""
                        SELECT SUM(credits_used) AS ytd_credits
                        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
                        WHERE start_time >= DATE_TRUNC('year', CURRENT_DATE())
                          AND start_time < DATEADD('hour', -24, CURRENT_TIMESTAMP())
                    """, ttl_key="account_health_brief_contract_ytd", tier="standard")
                    committed = st.session_state.get("cc_committed_credits", 100000)
                    ytd       = float(df_ytd["YTD_CREDITS"].iloc[0]) if not df_ytd.empty else 0
                    br_data["contract_pct"] = (ytd / committed * 100) if committed > 0 else None
                except Exception:
                    br_data["contract_pct"] = None

                # ── Extract values ────────────────────────────────────────────
                cr24     = float(br_data["credits"]["PERIOD_CREDITS"].iloc[0])  if not br_data["credits"].empty else 0
                cr_prior = float(br_data["credits"]["PRIOR_PERIOD_CREDITS"].iloc[0]) if not br_data["credits"].empty else 0
                failures = int(br_data["failures"]["FAIL_COUNT"].iloc[0])       if not br_data["failures"].empty else 0
                stor_tb  = float(br_data["storage"]["STORAGE_TB"].iloc[0])      if not br_data["storage"].empty else 0
                queued   = int(br_data["queued"]["QUEUED"].iloc[0])             if not br_data["queued"].empty else 0

                top_driver      = ""
                top_driver_cost = 0.0
                if not br_data["top_driver"].empty:
                    td = br_data["top_driver"].iloc[0]
                    top_driver      = f"{td.get('USER_NAME','')} on {td.get('WAREHOUSE_NAME','')}"
                    top_driver_cost = credits_to_dollars(float(td.get("CREDITS",0) or 0), credit_price)

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
                        f"(Cortex AI unavailable: {e}. Plain summary generated from raw metrics.)"
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
                "💡 Tip: set your annual committed credits in Cost Center → Contract Utilization "
                "before generating the briefing to include contract pacing in the narrative."
            )
