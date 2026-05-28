# sections/cost_center.py — User leaderboard, burn rate, forecast, budget, attribution, chargeback
# FIX: Chargeback tab now uses get_company_case_expr() from company_filter.py
#      instead of the old hardcoded CASE that missed WH_ALFA_* warehouses.
import streamlit as st
import pandas as pd
from datetime import datetime
from utils import (
    get_session, format_credits, credits_to_dollars,
    download_csv, build_metered_credit_cte,
    get_db_filter_clause, get_wh_filter_clause, get_user_filter_clause,
    get_global_filter_clause, get_company_case_expr,
    render_drillable_bar_chart, render_entity_query_drilldown,
    build_action_queue_ddl, make_action_id, upsert_actions,
    run_query, sql_literal, format_snowflake_error,
)


def _queue_cost_outliers(session, df: pd.DataFrame, credit_price: float, source: str) -> None:
    if df is None or df.empty:
        st.info("No cost outliers to queue.")
        return
    company = st.session_state.get("active_company", "ALFA")
    actions = []
    baseline = float(df["TOTAL_CREDITS"].median() or 0) if "TOTAL_CREDITS" in df.columns else 0
    candidates = df.sort_values("TOTAL_CREDITS", ascending=False).head(20)
    for _, row in candidates.iterrows():
        user = str(row.get("USER_NAME") or "Unknown user")
        wh = str(row.get("WAREHOUSE_NAME") or "Unknown warehouse")
        credits = float(row.get("TOTAL_CREDITS", 0) or 0)
        est_cost = credits_to_dollars(credits, credit_price)
        if baseline > 0 and credits < baseline * 2 and est_cost < 500:
            continue
        entity = f"{user} on {wh}"
        monthly_savings = max(0.0, est_cost * 0.15)
        finding = f"{entity} consumed {credits:,.2f} credits (${est_cost:,.2f}) in the selected window"
        actions.append({
            "Action ID": make_action_id("Cost Outlier", entity, finding),
            "Source": source,
            "Severity": "Medium" if est_cost < 2500 else "High",
            "Category": "Cost",
            "Entity Type": "User/Warehouse",
            "Entity": entity,
            "Owner": user if user and user != "Unknown user" else "DBA",
            "Finding": finding,
            "Action": "Review query patterns, warehouse sizing, cache use, and whether the workload can be optimized or scheduled differently.",
            "Estimated Monthly Savings": round(monthly_savings, 2),
            "Generated SQL Fix": "-- Use Cost Center drilldown to identify top query patterns before applying warehouse/query changes.",
            "Proof Query": "Cost Center metered credit attribution query.",
            "Company": company,
        })
    if not actions:
        st.success("No cost outliers crossed the queue threshold.")
        return
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} cost outliers to the action queue.")
    except Exception as e:
        st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
        st.download_button(
            "Download Action Queue DDL",
            build_action_queue_ddl(),
            file_name="overwatch_action_queue_setup.sql",
            mime="text/plain",
            key=f"cc_queue_ddl_{source}",
        )


def render():
    session = get_session()
    credit_price = st.session_state.get("credit_price", 3.00)
    company = st.session_state.get("active_company", "ALFA")

    tab_leader, tab_burn, tab_forecast, tab_budget, tab_attr, tab_chargeback, tab_contract = st.tabs([
        "User Leaderboard", "Burn Rate", "Forecast", "Budget vs Actual",
        "Attribution", "Chargeback", "📋 Contract Utilization"
    ])

    # ── USER LEADERBOARD ──────────────────────────────────────────────────────
    with tab_leader:
        st.header("💸 Credit Cost by User / Warehouse")
        days = st.slider("Lookback (days)", 1, 90, 30, key="cc_lead_days")
        gf = get_global_filter_clause(
            "q.start_time", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name"
        )

        if st.button("Load Leaderboard", key="cc_lead_load"):
            try:
                df_lead = run_query(f"""
                WITH {build_metered_credit_cte(days_back=days)}
                SELECT
                    q.user_name,
                    q.warehouse_name,
                    MAX(q.warehouse_size) AS warehouse_size,
                    COUNT(*)                                     AS query_count,
                    ROUND(AVG(q.total_elapsed_time)/1000, 2)    AS avg_elapsed_sec,
                    ROUND(SUM(pqc.metered_credits), 4)          AS total_credits,
                    ROUND(SUM(q.bytes_scanned)/POWER(1024,3),2) AS total_gb_scanned
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND q.warehouse_name IS NOT NULL
                  {gf}
                GROUP BY q.user_name, q.warehouse_name
                ORDER BY total_credits DESC
                LIMIT 200
                """, ttl_key=f"cc_lead_{company}_{days}", tier="standard")
                st.session_state["df_lead"] = df_lead
            except Exception as e:
                st.warning(f"Cost leaderboard unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("df_lead") is not None and not st.session_state["df_lead"].empty:
            df_l = st.session_state["df_lead"]
            df_l["COST"] = df_l["TOTAL_CREDITS"].apply(lambda x: credits_to_dollars(x, credit_price))
            c1, c2, c3 = st.columns(3)
            c1.metric("Distinct Users",  df_l["USER_NAME"].nunique())
            c2.metric("Total Credits",   format_credits(df_l["TOTAL_CREDITS"].sum()))
            c3.metric("Total Est. Cost", f"${df_l['COST'].sum():,.2f}")

            st.subheader("Top Users by Cost")
            user_agg = (
                df_l.groupby("USER_NAME")["COST"]
                .sum().reset_index()
                .sort_values("COST", ascending=False)
                .head(20)
            )
            render_drillable_bar_chart(
                user_agg,
                dimension="USER_NAME",
                measure="COST",
                key="cc_user_cost",
                drilldown_column="user_name",
                lookback_hours=days * 24,
            )
            st.dataframe(df_l, use_container_width=True)

            # User profile drill-through
            st.divider()
            st.subheader("User Profile Drill-Down")
            if "USER_NAME" in df_l.columns:
                sel_user = st.selectbox(
                    "Select user for full query breakdown",
                    df_l["USER_NAME"].dropna().unique().tolist(),
                    key="cc_user_profile_sel",
                )
                if sel_user:
                    render_entity_query_drilldown(
                        sel_user, key="cc_user_profile",
                        entity_column="user_name", lookback_hours=days * 24,
                    )

            download_csv(df_l, "cost_leaderboard.csv")
            if st.button("Save top cost outliers to Action Queue", key="cc_lead_queue"):
                _queue_cost_outliers(session, df_l, credit_price, "Cost Center - User Leaderboard")

    # ── BURN RATE ─────────────────────────────────────────────────────────────
    with tab_burn:
        st.header("🔥 Credit Burn Rate")
        br_days = st.slider("Lookback (days)", 1, 90, 30, key="br_days")
        if st.button("Load Burn Rate", key="br_load"):
            try:
                df_br = run_query(f"""
                    WITH latest_size AS (
                        SELECT warehouse_name, warehouse_size
                        FROM (
                            SELECT warehouse_name, warehouse_size,
                            ROW_NUMBER() OVER (PARTITION BY warehouse_name ORDER BY start_time DESC) AS rn
                            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                            WHERE start_time >= DATEADD('day', -{br_days}, CURRENT_TIMESTAMP())
                              AND warehouse_name IS NOT NULL
                              {get_wh_filter_clause("warehouse_name")}
                        )
                        WHERE rn = 1
                    )
                    SELECT DATE_TRUNC('day', m.start_time) AS day,
                           m.warehouse_name,
                           ls.warehouse_size,
                           SUM(m.credits_used) AS daily_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY m
                    LEFT JOIN latest_size ls ON m.warehouse_name = ls.warehouse_name
                    WHERE m.start_time >= DATEADD('day', -{br_days}, CURRENT_TIMESTAMP())
                    {get_wh_filter_clause("m.warehouse_name")}
                    GROUP BY day, m.warehouse_name, ls.warehouse_size
                    ORDER BY day
                """, ttl_key=f"cc_burn_{company}_{br_days}", tier="standard")
                st.session_state["df_br"] = df_br
            except Exception as e:
                st.warning(f"Burn-rate data unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("df_br") is not None and not st.session_state["df_br"].empty:
            df_b = st.session_state["df_br"]
            total_cr = df_b["DAILY_CREDITS"].sum()
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Credits",     format_credits(total_cr))
            c2.metric("Total Cost",        f"${credits_to_dollars(total_cr, credit_price):,.2f}")
            c3.metric("Avg Daily Credits", f"{total_cr / max(br_days,1):,.2f}")
            daily = df_b.groupby("DAY")["DAILY_CREDITS"].sum().reset_index()
            st.line_chart(daily.set_index("DAY")["DAILY_CREDITS"])
            by_wh = (
                df_b.groupby("WAREHOUSE_NAME")["DAILY_CREDITS"]
                .sum().reset_index()
                .sort_values("DAILY_CREDITS", ascending=False)
            )
            st.subheader("Credits by Warehouse")
            render_drillable_bar_chart(
                by_wh, dimension="WAREHOUSE_NAME", measure="DAILY_CREDITS",
                key="cc_wh_credits", drilldown_column="warehouse_name",
                lookback_hours=br_days * 24,
            )
            download_csv(df_b, "burn_rate.csv")

    # ── FORECAST ──────────────────────────────────────────────────────────────
    with tab_forecast:
        st.header("📈 Credit Forecast (30-day Linear Projection)")
        if st.button("Generate Forecast", key="fc_load"):
            try:
                df_fc = run_query(f"""
                    SELECT DATE_TRUNC('day', start_time) AS day,
                           SUM(credits_used) AS daily_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                    WHERE start_time >= DATEADD('day', -30, CURRENT_TIMESTAMP())
                    {get_wh_filter_clause("warehouse_name")}
                    GROUP BY day ORDER BY day
                """, ttl_key=f"cc_forecast_30_{company}", tier="standard")
                st.session_state["df_fc"] = df_fc
            except Exception as e:
                st.warning(f"Forecast data unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("df_fc") is not None and not st.session_state["df_fc"].empty:
            df_f = st.session_state["df_fc"].copy()
            df_f["DAY"] = pd.to_datetime(df_f["DAY"])
            full_window = pd.DataFrame({
                "DAY": pd.date_range(
                    pd.Timestamp.today().normalize() - pd.Timedelta(days=29),
                    pd.Timestamp.today().normalize(),
                    freq="D",
                )
            })
            df_f = full_window.merge(df_f, on="DAY", how="left")
            df_f["DAILY_CREDITS"] = pd.to_numeric(df_f["DAILY_CREDITS"], errors="coerce").fillna(0)
            avg_daily = df_f["DAILY_CREDITS"].mean()
            proj_30   = avg_daily * 30
            proj_cost = credits_to_dollars(proj_30, credit_price)
            c1, c2, c3 = st.columns(3)
            c1.metric("Avg Daily Credits",     f"{avg_daily:.2f}")
            c2.metric("Projected 30-day",      format_credits(proj_30))
            c3.metric("Projected 30-day Cost", f"${proj_cost:,.2f}")
            st.area_chart(df_f.set_index("DAY")["DAILY_CREDITS"])

    # ── BUDGET VS ACTUAL ──────────────────────────────────────────────────────
    with tab_budget:
        st.header("💰 Budget vs Actual")
        monthly_budget = st.number_input(
            "Monthly credit budget", min_value=0, value=10000, step=500, key="bva_budget"
        )
        if st.button("Load Budget Comparison", key="bva_load"):
            try:
                df_bva = run_query(f"""
                    SELECT DATE_TRUNC('month', start_time) AS month,
                           SUM(credits_used) AS actual_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                    WHERE start_time >= DATEADD('month', -6, CURRENT_TIMESTAMP())
                    {get_wh_filter_clause("warehouse_name")}
                    GROUP BY month ORDER BY month
                """, ttl_key=f"cc_budget_6mo_{company}", tier="standard")
                st.session_state["df_bva"] = df_bva
            except Exception as e:
                st.warning(f"Budget comparison unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("df_bva") is not None and not st.session_state["df_bva"].empty:
            df_bv = st.session_state["df_bva"]
            df_bv["BUDGET"]    = monthly_budget
            df_bv["OVER_UNDER"] = df_bv["ACTUAL_CREDITS"] - monthly_budget
            df_bv["STATUS"]    = df_bv["OVER_UNDER"].apply(
                lambda x: "🔴 Over" if x > 0 else "🟢 Under"
            )
            st.dataframe(df_bv, use_container_width=True)
            st.bar_chart(df_bv.set_index("MONTH")[["ACTUAL_CREDITS","BUDGET"]])
            download_csv(df_bv, "budget_vs_actual.csv")

    # ── ATTRIBUTION ───────────────────────────────────────────────────────────
    with tab_attr:
        st.header("Cost Attribution")
        attr_days = st.slider("Lookback (days)", 1, 90, 30, key="cc_attr_days")
        attr_mode = st.selectbox(
            "Attribution dimension",
            ["Role", "Database / Schema", "Application / Client", "Stored Procedure / Task Lineage"],
            key="cc_attr_mode",
        )
        gf = get_global_filter_clause(
            "q.start_time", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name"
        )

        if st.button("Load Attribution", key="cc_attr_load"):
            if attr_mode == "Role":
                select_cols = "COALESCE(q.role_name, 'UNKNOWN') AS dimension"
                group_cols  = "COALESCE(q.role_name, 'UNKNOWN')"
            elif attr_mode == "Database / Schema":
                select_cols = "COALESCE(q.database_name,'UNKNOWN')||'.'||COALESCE(q.schema_name,'UNKNOWN') AS dimension"
                group_cols  = "COALESCE(q.database_name,'UNKNOWN')||'.'||COALESCE(q.schema_name,'UNKNOWN')"
            elif attr_mode == "Application / Client":
                select_cols = "COALESCE(q.query_tag, 'UNTAGGED') AS dimension"
                group_cols  = "COALESCE(q.query_tag, 'UNTAGGED')"
            else:
                select_cols = "COALESCE(REGEXP_SUBSTR(q.query_text,'CALL\\\\s+([^\\\\(]+)',1,1,'i',1), q.query_type, 'ADHOC') AS dimension"
                group_cols  = "COALESCE(REGEXP_SUBSTR(q.query_text,'CALL\\\\s+([^\\\\(]+)',1,1,'i',1), q.query_type, 'ADHOC')"

            try:
                df_attr = run_query(f"""
                WITH {build_metered_credit_cte(days_back=attr_days)}
                SELECT {select_cols},
                       COUNT(*) AS query_count,
                       COUNT(DISTINCT q.user_name)      AS users,
                       COUNT(DISTINCT q.warehouse_name) AS warehouses,
                       ROUND(SUM(COALESCE(pqc.metered_credits,0)),4) AS total_credits,
                       ROUND(SUM(q.bytes_scanned)/POWER(1024,3),2)   AS gb_scanned
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                WHERE q.start_time >= DATEADD('day', -{attr_days}, CURRENT_TIMESTAMP())
                  AND q.warehouse_name IS NOT NULL
                  {gf}
                GROUP BY {group_cols}
                ORDER BY total_credits DESC
                LIMIT 200
                """, ttl_key=f"cc_attr_{company}_{attr_mode}_{attr_days}", tier="standard")
                st.session_state["df_cc_attr"] = df_attr
            except Exception as e:
                st.warning(f"Attribution data unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("df_cc_attr") is not None and not st.session_state["df_cc_attr"].empty:
            df_attr = st.session_state["df_cc_attr"]
            df_attr["EST_COST"] = df_attr["TOTAL_CREDITS"].apply(lambda x: credits_to_dollars(x, credit_price))
            st.dataframe(df_attr, use_container_width=True)
            dim_col = (
                "role_name" if attr_mode == "Role" else
                "database_schema" if attr_mode == "Database / Schema" else
                "application_client" if attr_mode == "Application / Client" else
                "lineage_dimension"
            )
            render_drillable_bar_chart(
                df_attr, dimension="DIMENSION", measure="EST_COST",
                key="cc_attr_cost", title="Attribution drill-down",
                drilldown_column=dim_col, lookback_hours=attr_days * 24,
            )
            download_csv(df_attr, "cost_attribution.csv")

    # ── CHARGEBACK — ALFA / Trexis split ─────────────────────────────────────
    with tab_chargeback:
        st.header("🏷️ ALFA / Trexis Chargeback")
        st.caption(
            "Credits split by company using the canonical warehouse/DB/user classification. "
            "Uses `get_company_case_expr()` — stays in sync with config.py warehouse inventory."
        )
        cb_days = st.slider("Lookback (days)", 1, 90, 30, key="cc_cb_days")

        if st.button("Load Chargeback", key="cc_cb_load"):
            try:
                # FIX: replaced hardcoded CASE with get_company_case_expr()
                # which reads from COMPANY_CONFIG and includes all WH_ALFA_* warehouses
                company_expr = get_company_case_expr(
                    "q.warehouse_name", "q.database_name", "q.user_name"
                )
                df_cb = run_query(f"""
                WITH {build_metered_credit_cte(days_back=cb_days)},
                query_costs AS (
                    SELECT
                        {company_expr}         AS company,
                        q.user_name,
                        q.warehouse_name,
                        MAX(q.warehouse_size) AS warehouse_size,
                        COUNT(*)               AS query_count,
                        SUM(COALESCE(pqc.metered_credits,0)) AS total_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                    WHERE q.start_time >= DATEADD('day', -{cb_days}, CURRENT_TIMESTAMP())
                      AND q.warehouse_name IS NOT NULL
                      {get_wh_filter_clause("q.warehouse_name")}
                    GROUP BY company, q.user_name, q.warehouse_name
                )
                SELECT company, user_name, warehouse_name, warehouse_size, query_count,
                       ROUND(total_credits, 4) AS total_credits
                FROM query_costs
                ORDER BY total_credits DESC
                """, ttl_key=f"cc_chargeback_{company}_{cb_days}", tier="standard")
                st.session_state["df_chargeback"] = df_cb
            except Exception as e:
                st.warning(f"Chargeback data unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("df_chargeback") is not None and not st.session_state["df_chargeback"].empty:
            df_cb = st.session_state["df_chargeback"]
            df_cb["EST_COST"] = df_cb["TOTAL_CREDITS"].apply(lambda x: credits_to_dollars(x, credit_price))

            # Summary by company — the key chargeback output
            summary = (
                df_cb.groupby("COMPANY", as_index=False)[["TOTAL_CREDITS","EST_COST","QUERY_COUNT"]]
                .sum()
                .sort_values("EST_COST", ascending=False)
            )
            c1, c2, c3 = st.columns(len(summary))
            for idx, srow in summary.iterrows():
                col = [c1, c2, c3][idx % 3]
                col.metric(
                    srow["COMPANY"],
                    f"${srow['EST_COST']:,.2f}",
                    f"{format_credits(srow['TOTAL_CREDITS'])}",
                )

            st.subheader("Summary by Company")
            st.dataframe(summary, use_container_width=True)

            st.subheader("Detail by User / Warehouse")
            company_filter = st.selectbox(
                "Filter by company", ["All"] + summary["COMPANY"].tolist(), key="cb_co_filter"
            )
            df_show = df_cb if company_filter == "All" else df_cb[df_cb["COMPANY"] == company_filter]
            st.dataframe(df_show, use_container_width=True)
            download_csv(df_show, "chargeback_detail.csv")
            if st.button("Save chargeback outliers to Action Queue", key="cc_chargeback_queue"):
                _queue_cost_outliers(session, df_show, credit_price, "Cost Center - Chargeback")

    # ── CONTRACT / COMMITMENT UTILIZATION ─────────────────────────────────────
    with tab_contract:
        st.header("📋 Contract & Commitment Utilization")
        st.caption(
            "Track consumption against your annual Snowflake committed-use contract. "
            "Projects burn rate to flag over- and under-utilization risk."
        )

        col_ct1, col_ct2, col_ct3 = st.columns(3)
        with col_ct1:
            committed_credits = st.number_input(
                "Annual committed credits",
                min_value=0, max_value=10_000_000, value=100_000, step=1_000,
                key="cc_committed_credits",
                help="Total credits in your Snowflake annual contract."
            )
        with col_ct2:
            from datetime import datetime as _dt
            contract_start = st.date_input(
                "Contract start date",
                value=_dt(datetime.now().year, 1, 1).date(),
                key="cc_contract_start",
            )
        with col_ct3:
            contract_months = st.number_input(
                "Contract length (months)", min_value=1, max_value=60, value=12,
                key="cc_contract_months",
            )

        if st.button("Calculate Utilization", key="cc_contract_calc"):
            try:
                ytd_source = "SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY" if company == "ALL" else "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
                ytd_filter = "" if company == "ALL" else get_wh_filter_clause("warehouse_name", company)
                df_ytd = run_query(f"""
                    SELECT SUM(credits_used) AS ytd_credits
                    FROM {ytd_source}
                    WHERE start_time >= TO_DATE({sql_literal(str(contract_start))})
                      AND start_time <  DATEADD('hour', -24, CURRENT_TIMESTAMP())
                      {ytd_filter}
                """, ttl_key=f"cc_contract_ytd_{company}_{contract_start}", tier="historical")
                st.session_state["cc_contract_data"] = df_ytd
                st.session_state["cc_contract_params"] = {
                    "committed": committed_credits,
                    "start": str(contract_start),
                    "months": contract_months,
                }
            except Exception as e:
                st.warning(f"Utilization data unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("cc_contract_data") is not None:
            df_c  = st.session_state["cc_contract_data"]
            params = st.session_state.get("cc_contract_params", {})
            committed = params.get("committed", committed_credits)
            start_str = params.get("start", str(contract_start))
            months    = params.get("months", contract_months)

            ytd_used = float(df_c["YTD_CREDITS"].iloc[0]) if not df_c.empty else 0

            start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
            days_elapsed   = max((datetime.now().date() - start_date).days, 1)
            days_in_contract = months * 30.44  # avg days per month
            days_remaining   = max(days_in_contract - days_elapsed, 0)

            daily_rate       = ytd_used / days_elapsed
            projected_total  = daily_rate * days_in_contract
            remaining_budget = committed - ytd_used
            pct_consumed     = (ytd_used / committed * 100) if committed > 0 else 0
            pct_time_elapsed = (days_elapsed / days_in_contract * 100) if days_in_contract > 0 else 0

            if daily_rate > 0 and remaining_budget > 0:
                days_until_exhausted = remaining_budget / daily_rate
                from datetime import timedelta as _td
                exhaust_date = (datetime.now() + _td(days=days_until_exhausted)).strftime("%Y-%m-%d")
            else:
                exhaust_date = "N/A"

            # Pacing ratio: credits consumed % vs time elapsed %
            pacing_ratio = (pct_consumed / pct_time_elapsed) if pct_time_elapsed > 0 else 1.0

            # ── KPI row ────────────────────────────────────────────────────────
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("YTD Consumed",         format_credits(ytd_used))
            k2.metric("Remaining Budget",     format_credits(remaining_budget))
            k3.metric("% Consumed",           f"{pct_consumed:.1f}%",
                      delta=f"{pct_consumed - pct_time_elapsed:+.1f}% vs time",
                      delta_color="inverse" if pct_consumed > pct_time_elapsed + 5 else "normal")
            k4.metric("Daily Burn Rate",      f"{daily_rate:,.1f} cr/day")
            k5.metric("Projected Year-End",   format_credits(projected_total))

            # ── Progress bar ───────────────────────────────────────────────────
            bar_pct = min(pct_consumed / 100, 1.0)
            st.progress(bar_pct, text=f"{pct_consumed:.1f}% of {committed:,} committed credits")

            # ── Pacing diagnosis ───────────────────────────────────────────────
            st.divider()
            if pacing_ratio > 1.15:
                st.error(
                    f"🔴 **Burning too fast** — consuming credits {pacing_ratio:.1f}x faster than the "
                    f"contract pace. At {daily_rate:,.1f} cr/day you will exhaust the commitment on "
                    f"**{exhaust_date}** ({days_until_exhausted:.0f} days from now), "
                    f"**{days_remaining - days_until_exhausted:.0f} days early**. "
                    f"Projected year-end: **{projected_total:,.0f}** vs committed **{committed:,}** "
                    f"({(projected_total/committed*100)-100:.0f}% over)."
                )
            elif pacing_ratio < 0.75:
                under_pct = 100 - (projected_total / committed * 100)
                st.warning(
                    f"🟡 **Under-utilizing** — tracking at {pacing_ratio:.2f}x the contract pace. "
                    f"Projected year-end: **{projected_total:,.0f}** of {committed:,} credits "
                    f"({under_pct:.0f}% under-utilized). "
                    f"Review with Snowflake account team — unused committed credits typically do not roll over."
                )
            else:
                st.success(
                    f"✅ **On pace** — pacing ratio {pacing_ratio:.2f}x. "
                    f"Projected year-end: **{projected_total:,.0f}** of {committed:,} credits "
                    f"({pct_consumed:.0f}% consumed, {pct_time_elapsed:.0f}% of contract elapsed)."
                )

            # ── Monthly breakdown chart ────────────────────────────────────────
            st.divider()
            st.subheader("Monthly Consumption")
            if st.button("Load Monthly Breakdown", key="cc_monthly_breakdown"):
                try:
                    monthly_source = "SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY" if company == "ALL" else "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
                    monthly_filter = "" if company == "ALL" else get_wh_filter_clause("warehouse_name", company)
                    df_monthly = run_query(f"""
                        SELECT DATE_TRUNC('month', start_time) AS month,
                               SUM(credits_used) AS monthly_credits,
                               SUM(credits_used) * {credit_price} AS monthly_cost
                        FROM {monthly_source}
                        WHERE start_time >= TO_DATE({sql_literal(start_str)})
                          AND start_time <  DATEADD('hour', -24, CURRENT_TIMESTAMP())
                          {monthly_filter}
                        GROUP BY month
                        ORDER BY month
                    """, ttl_key=f"cc_monthly_{company}_{start_str}_{credit_price}", tier="historical")
                    st.session_state["cc_monthly_data"] = df_monthly
                except Exception as e:
                    st.warning(f"Monthly breakdown unavailable in this role/context: {format_snowflake_error(e)}")

            if st.session_state.get("cc_monthly_data") is not None and not st.session_state["cc_monthly_data"].empty:
                df_m = st.session_state["cc_monthly_data"]
                df_m["BUDGET_LINE"] = committed / (months or 12)
                df_m["CUMULATIVE"]  = df_m["MONTHLY_CREDITS"].cumsum()

                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    st.caption("Monthly credits vs equal-share budget line")
                    st.bar_chart(df_m.set_index("MONTH")[["MONTHLY_CREDITS","BUDGET_LINE"]])
                with col_m2:
                    st.caption("Cumulative consumption")
                    st.line_chart(df_m.set_index("MONTH")["CUMULATIVE"])

                download_csv(df_m, "contract_utilization.csv")

            # ── By service type ────────────────────────────────────────────────
            st.divider()
            st.subheader("Consumption by Service Type")
            if company != "ALL":
                st.info("Service-type metering is account-level in Snowflake. Switch Company View to ALL for a full service breakdown.")
            else:
                if st.button("Load Service Breakdown", key="cc_service_type"):
                    try:
                        df_svc = run_query(f"""
                            SELECT service_type,
                                   SUM(credits_used) AS total_credits,
                                   ROUND(SUM(credits_used) / NULLIF({ytd_used}, 0) * 100, 1) AS pct_of_total
                            FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
                            WHERE start_time >= TO_DATE({sql_literal(start_str)})
                              AND start_time <  DATEADD('hour', -24, CURRENT_TIMESTAMP())
                            GROUP BY service_type
                            ORDER BY total_credits DESC
                        """, ttl_key=f"cc_service_{company}_{start_str}_{ytd_used}", tier="historical")
                        st.session_state["cc_svc_data"] = df_svc
                    except Exception as e:
                        st.warning(f"Service breakdown unavailable in this role/context: {format_snowflake_error(e)}")

                if st.session_state.get("cc_svc_data") is not None and not st.session_state["cc_svc_data"].empty:
                    df_sv = st.session_state["cc_svc_data"]
                    st.dataframe(df_sv, use_container_width=True)
                    st.bar_chart(df_sv.set_index("SERVICE_TYPE")["TOTAL_CREDITS"])
                    download_csv(df_sv, "contract_by_service_type.csv")
