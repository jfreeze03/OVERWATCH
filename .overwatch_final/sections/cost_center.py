# sections/cost_center.py — User leaderboard, burn rate, forecast, budget, attribution, chargeback
# FIX: Chargeback tab now uses get_company_case_expr() from company_filter.py
#      instead of the old hardcoded CASE that missed WH_ALFA_* warehouses.
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from utils import (
    get_session, format_credits, credits_to_dollars,
    download_csv, build_metered_credit_cte, build_cost_reconciliation_sql,
    burn_trend_label,
    metric_confidence_label, freshness_note,
    get_wh_filter_clause,
    get_global_filter_clause, get_company_case_expr,
    filter_existing_columns,
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
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        ["WAREHOUSE_SIZE", "BYTES_SCANNED", "QUERY_TAG"],
    ))
    max_wh_size_expr = (
        "MAX(q.warehouse_size)"
        if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR"
    )
    wh_size_plain_expr = (
        "warehouse_size"
        if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"
    )
    bytes_scanned_sum_expr = (
        "SUM(q.bytes_scanned)"
        if "BYTES_SCANNED" in qh_cols else "0"
    )
    query_tag_dimension_expr = (
        "COALESCE(q.query_tag, 'UNTAGGED')"
        if "QUERY_TAG" in qh_cols else "'UNTAGGED'"
    )

    tab_leader, tab_burn, tab_recon, tab_forecast, tab_budget, tab_attr, tab_chargeback, tab_contract = st.tabs([
        "User Leaderboard", "Burn Rate", "Reconciliation", "Forecast", "Budget vs Actual",
        "Attribution", "Chargeback", "📋 Contract Utilization"
    ])
    st.caption(
        "Progressive load is enabled: each cost view runs only when its Load or Calculate button is selected."
    )

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
                    {max_wh_size_expr} AS warehouse_size,
                    COUNT(*)                                     AS query_count,
                    ROUND(AVG(q.total_elapsed_time)/1000, 2)    AS avg_elapsed_sec,
                    ROUND(SUM(pqc.metered_credits), 4)          AS total_credits,
                    ROUND({bytes_scanned_sum_expr}/POWER(1024,3),2) AS total_gb_scanned
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
            st.caption(f"{metric_confidence_label('allocated')} | {freshness_note('ACCOUNT_USAGE')}")

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
                            SELECT warehouse_name, {wh_size_plain_expr},
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
            st.caption(f"{metric_confidence_label('exact')} | {freshness_note('WAREHOUSE_METERING_HISTORY')}")
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

    # -- COST RECONCILIATION -------------------------------------------------
    with tab_recon:
        st.header("Cost Reconciliation")
        st.caption(
            "Compares exact warehouse metering to query-level allocated credits. "
            "Large variances usually mean idle warehouse time, non-query activity, latency, or chargeback assumptions need review."
        )
        recon_days = st.slider("Reconciliation window (days)", 7, 90, 30, key="cc_recon_days")
        if st.button("Load Reconciliation", key="cc_recon_load"):
            try:
                st.session_state["df_cc_recon"] = run_query(
                    build_cost_reconciliation_sql(recon_days),
                    ttl_key=f"cc_recon_{company}_{recon_days}",
                    tier="standard",
                    section="Cost Center",
                )
            except Exception as e:
                st.warning(f"Cost reconciliation unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("df_cc_recon") is not None and not st.session_state["df_cc_recon"].empty:
            df_r = st.session_state["df_cc_recon"]
            total_exact = float(df_r["EXACT_METERED_CREDITS"].sum()) if "EXACT_METERED_CREDITS" in df_r.columns else 0.0
            total_alloc = float(df_r["ALLOCATED_QUERY_CREDITS"].sum()) if "ALLOCATED_QUERY_CREDITS" in df_r.columns else 0.0
            total_var = total_exact - total_alloc
            c1, c2, c3 = st.columns(3)
            c1.metric("Exact Metered", format_credits(total_exact))
            c2.metric("Allocated to Queries", format_credits(total_alloc))
            c3.metric("Unallocated / Variance", format_credits(total_var))
            st.caption(
                f"{metric_confidence_label('exact')} for metering; "
                f"{metric_confidence_label('allocated')} for query attribution | "
                f"{freshness_note('WAREHOUSE_METERING_HISTORY')}"
            )
            if "RECONCILIATION_STATUS" in df_r.columns:
                st.bar_chart(df_r["RECONCILIATION_STATUS"].value_counts())
            st.dataframe(df_r, use_container_width=True, height=420)
            download_csv(df_r, "cost_reconciliation.csv")

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
                select_cols = f"{query_tag_dimension_expr} AS dimension"
                group_cols  = query_tag_dimension_expr
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
                       ROUND({bytes_scanned_sum_expr}/POWER(1024,3),2)   AS gb_scanned
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
                        {max_wh_size_expr} AS warehouse_size,
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
            "Projects burn rate to flag over- and under-utilization risk. "
            "This is the canonical contract view; the standalone Credit Contract page has been consolidated here."
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
                    SELECT TO_DATE(start_time) AS usage_date,
                           SUM(credits_used) AS credits_used
                    FROM {ytd_source}
                    WHERE start_time >= TO_DATE({sql_literal(str(contract_start))})
                      AND start_time <  DATEADD('hour', -24, CURRENT_TIMESTAMP())
                      {ytd_filter}
                    GROUP BY usage_date
                    ORDER BY usage_date
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

            start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
            days_in_contract = max(int(round(float(months) * 30.44)), 1)
            contract_end_date = start_date + timedelta(days=days_in_contract - 1)
            as_of_date = min(max(datetime.now().date() - timedelta(days=1), start_date), contract_end_date)

            observed_days = pd.DataFrame({
                "USAGE_DATE": pd.date_range(start_date, as_of_date, freq="D")
            })
            df_daily = df_c.copy()
            if df_daily.empty:
                df_daily = observed_days.copy()
                df_daily["CREDITS_USED"] = 0.0
            else:
                df_daily["USAGE_DATE"] = pd.to_datetime(df_daily["USAGE_DATE"]).dt.normalize()
                df_daily["CREDITS_USED"] = pd.to_numeric(df_daily["CREDITS_USED"], errors="coerce").fillna(0.0)
                df_daily = observed_days.merge(df_daily, on="USAGE_DATE", how="left")
                df_daily["CREDITS_USED"] = df_daily["CREDITS_USED"].fillna(0.0)

            ytd_used = float(df_daily["CREDITS_USED"].sum())
            days_elapsed = max(len(df_daily), 1)
            days_remaining = max((contract_end_date - as_of_date).days, 0)

            daily_rate = ytd_used / days_elapsed
            last_7_avg = float(df_daily.tail(min(7, len(df_daily)))["CREDITS_USED"].mean() or 0)
            last_30_avg = float(df_daily.tail(min(30, len(df_daily)))["CREDITS_USED"].mean() or 0)
            trend_label = burn_trend_label(last_7_avg, last_30_avg)

            future_days = pd.date_range(as_of_date + timedelta(days=1), contract_end_date, freq="D")
            future_business_days = int((future_days.dayofweek < 5).sum()) if len(future_days) else 0
            future_weekend_days = len(future_days) - future_business_days
            business_hist = df_daily[df_daily["USAGE_DATE"].dt.dayofweek < 5]
            weekend_hist = df_daily[df_daily["USAGE_DATE"].dt.dayofweek >= 5]
            business_avg = float(business_hist.tail(20)["CREDITS_USED"].mean() or last_30_avg or daily_rate)
            weekend_avg = float(weekend_hist.tail(8)["CREDITS_USED"].mean() or last_30_avg or daily_rate)

            projected_total = ytd_used + (daily_rate * days_remaining)
            projected_7 = ytd_used + (last_7_avg * days_remaining)
            projected_30 = ytd_used + (last_30_avg * days_remaining)
            projected_business = ytd_used + (business_avg * future_business_days) + (weekend_avg * future_weekend_days)
            remaining_budget = committed - ytd_used
            pct_consumed     = (ytd_used / committed * 100) if committed > 0 else 0
            pct_time_elapsed = (days_elapsed / days_in_contract * 100) if days_in_contract > 0 else 0

            runway_rate = last_7_avg if trend_label == "Accelerating" and last_7_avg > 0 else daily_rate
            if runway_rate > 0 and remaining_budget > 0:
                days_until_exhausted = remaining_budget / runway_rate
                exhaust_date = (datetime.now() + timedelta(days=days_until_exhausted)).strftime("%Y-%m-%d")
            else:
                days_until_exhausted = None
                exhaust_date = "N/A"

            # Pacing ratio: credits consumed % vs time elapsed %
            pacing_ratio = (pct_consumed / pct_time_elapsed) if pct_time_elapsed > 0 else 1.0
            projected_pct_over = ((projected_total / committed) * 100 - 100) if committed > 0 else 0.0

            # ── KPI row ────────────────────────────────────────────────────────
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("YTD Consumed",         format_credits(ytd_used))
            k2.metric("Remaining Budget",     format_credits(remaining_budget))
            k3.metric("% Consumed",           f"{pct_consumed:.1f}%",
                      delta=f"{pct_consumed - pct_time_elapsed:+.1f}% vs time",
                      delta_color="inverse" if pct_consumed > pct_time_elapsed + 5 else "normal")
            k4.metric("Daily Burn Rate",      f"{daily_rate:,.1f} cr/day")
            k5.metric("Projected Year-End",   format_credits(projected_total))
            st.caption(
                f"{metric_confidence_label('exact')} for consumed credits | "
                f"{metric_confidence_label('projection')} | "
                f"{freshness_note('WAREHOUSE_METERING_HISTORY')}"
            )

            p1, p2, p3 = st.columns(3)
            p1.metric("7-Day Projection", format_credits(projected_7), trend_label)
            p2.metric("30-Day Projection", format_credits(projected_30), burn_trend_label(last_30_avg, daily_rate))
            p3.metric("Business-Day Adjusted", format_credits(projected_business), f"{business_avg:,.1f} cr/business day")

            # ── Progress bar ───────────────────────────────────────────────────
            bar_pct = min(pct_consumed / 100, 1.0)
            st.progress(bar_pct, text=f"{pct_consumed:.1f}% of {committed:,} committed credits")

            # ── Pacing diagnosis ───────────────────────────────────────────────
            st.divider()
            if pacing_ratio > 1.15:
                exhaustion_line = (
                    f"At {runway_rate:,.1f} cr/day you will exhaust the commitment on "
                    f"**{exhaust_date}** ({days_until_exhausted:.0f} days from now), "
                    f"**{days_remaining - days_until_exhausted:.0f} days early**. "
                    if days_until_exhausted is not None
                    else "Current burn cannot calculate a reliable exhaustion date. "
                )
                st.error(
                    f"🔴 **Burning too fast** — consuming credits {pacing_ratio:.1f}x faster than the "
                    f"contract pace. {exhaustion_line}"
                    f"Projected year-end: **{projected_total:,.0f}** vs committed **{committed:,}** "
                    f"({projected_pct_over:.0f}% over)."
                )
            elif pacing_ratio < 0.75:
                under_pct = 100 - (projected_total / committed * 100) if committed > 0 else 0.0
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
