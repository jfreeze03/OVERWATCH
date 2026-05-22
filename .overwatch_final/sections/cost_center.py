# sections/cost_center.py — User leaderboard, burn rate, forecast, budget, attribution, chargeback
# FIX: Chargeback tab now uses get_company_case_expr() from company_filter.py
#      instead of the old hardcoded CASE that missed WH_ALFA_* warehouses.
import streamlit as st
import pandas as pd
from datetime import datetime
from utils import (
    get_session, normalize_df, format_credits, credits_to_dollars,
    download_csv, build_metered_credit_cte,
    get_db_filter_clause, get_wh_filter_clause, get_user_filter_clause,
    get_global_filter_clause, get_company_case_expr,
    render_drillable_bar_chart, render_entity_query_drilldown,
)


def render():
    session = get_session()
    credit_price = st.session_state.get("credit_price", 3.00)

    tab_leader, tab_burn, tab_forecast, tab_budget, tab_attr, tab_chargeback, tab_contract = st.tabs([
        "User Leaderboard", "Burn Rate", "Forecast", "Budget vs Actual",
        "Attribution", "Chargeback", "📋 Contract Utilization"
    ])

    # ── USER LEADERBOARD ──────────────────────────────────────────────────────
    with tab_leader:
        st.header("💸 Credit Cost by User / Warehouse")
        days = st.slider("Lookback (days)", 1, 90, 30, key="cc_lead_days")
        wf = get_wh_filter_clause("q.warehouse_name")
        uf = get_user_filter_clause("q.user_name")
        gf = get_global_filter_clause(
            "q.start_time", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name"
        )

        if st.button("Load Leaderboard", key="cc_lead_load"):
            try:
                df_lead = normalize_df(session.sql(f"""
                WITH {build_metered_credit_cte(days_back=days)}
                SELECT
                    q.user_name,
                    q.warehouse_name,
                    COUNT(*)                                     AS query_count,
                    ROUND(AVG(q.total_elapsed_time)/1000, 2)    AS avg_elapsed_sec,
                    ROUND(SUM(pqc.metered_credits), 4)          AS total_credits,
                    ROUND(SUM(q.bytes_scanned)/POWER(1024,3),2) AS total_gb_scanned
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                WHERE q.start_time >= DATEADD('days', -{days}, CURRENT_TIMESTAMP())
                  AND q.warehouse_name IS NOT NULL
                  {wf} {uf} {gf}
                GROUP BY q.user_name, q.warehouse_name
                ORDER BY total_credits DESC
                LIMIT 200
                """).to_pandas())
                st.session_state["df_lead"] = df_lead
            except Exception as e:
                st.error(f"Error: {e}")

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

    # ── BURN RATE ─────────────────────────────────────────────────────────────
    with tab_burn:
        st.header("🔥 Credit Burn Rate")
        br_days = st.slider("Lookback (days)", 1, 90, 30, key="br_days")
        wf_br   = get_wh_filter_clause()

        if st.button("Load Burn Rate", key="br_load"):
            try:
                df_br = normalize_df(session.sql(f"""
                    SELECT DATE_TRUNC('day', start_time) AS day,
                           warehouse_name,
                           SUM(credits_used) AS daily_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                    WHERE start_time >= DATEADD('days', -{br_days}, CURRENT_TIMESTAMP())
                    {wf_br}
                    GROUP BY day, warehouse_name
                    ORDER BY day
                """).to_pandas())
                st.session_state["df_br"] = df_br
            except Exception as e:
                st.error(f"Error: {e}")

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
                df_fc = normalize_df(session.sql("""
                    SELECT DATE_TRUNC('day', start_time) AS day,
                           SUM(credits_used) AS daily_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                    WHERE start_time >= DATEADD('day', -30, CURRENT_TIMESTAMP())
                    GROUP BY day ORDER BY day
                """).to_pandas())
                st.session_state["df_fc"] = df_fc
            except Exception as e:
                st.error(f"Error: {e}")

        if st.session_state.get("df_fc") is not None and not st.session_state["df_fc"].empty:
            df_f = st.session_state["df_fc"]
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
                df_bva = normalize_df(session.sql("""
                    SELECT DATE_TRUNC('month', start_time) AS month,
                           SUM(credits_used) AS actual_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                    WHERE start_time >= DATEADD('month', -6, CURRENT_TIMESTAMP())
                    GROUP BY month ORDER BY month
                """).to_pandas())
                st.session_state["df_bva"] = df_bva
            except Exception as e:
                st.error(f"Error: {e}")

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
                select_cols = "COALESCE(q.client_application_id, q.query_tag, 'UNKNOWN') AS dimension"
                group_cols  = "COALESCE(q.client_application_id, q.query_tag, 'UNKNOWN')"
            else:
                select_cols = "COALESCE(t.name, REGEXP_SUBSTR(q.query_text,'CALL\\\\s+([^\\\\(]+)',1,1,'i',1), q.root_query_id, 'ADHOC') AS dimension"
                group_cols  = "COALESCE(t.name, REGEXP_SUBSTR(q.query_text,'CALL\\\\s+([^\\\\(]+)',1,1,'i',1), q.root_query_id, 'ADHOC')"

            try:
                df_attr = normalize_df(session.sql(f"""
                WITH {build_metered_credit_cte(days_back=attr_days)}
                SELECT {select_cols},
                       COUNT(*) AS query_count,
                       COUNT(DISTINCT q.user_name)      AS users,
                       COUNT(DISTINCT q.warehouse_name) AS warehouses,
                       ROUND(SUM(COALESCE(pqc.metered_credits,0)),4) AS total_credits,
                       ROUND(SUM(q.bytes_scanned)/POWER(1024,3),2)   AS gb_scanned
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY t ON q.query_id = t.query_id
                WHERE q.start_time >= DATEADD('days', -{attr_days}, CURRENT_TIMESTAMP())
                  AND q.warehouse_name IS NOT NULL
                  {gf}
                GROUP BY {group_cols}
                ORDER BY total_credits DESC
                LIMIT 200
                """).to_pandas())
                st.session_state["df_cc_attr"] = df_attr
            except Exception as e:
                st.error(f"Attribution load failed: {e}")

        if st.session_state.get("df_cc_attr") is not None and not st.session_state["df_cc_attr"].empty:
            df_attr = st.session_state["df_cc_attr"]
            df_attr["EST_COST"] = df_attr["TOTAL_CREDITS"].apply(lambda x: credits_to_dollars(x, credit_price))
            st.dataframe(df_attr, use_container_width=True)
            dim_col = (
                "role_name" if attr_mode == "Role" else
                "database_name" if attr_mode == "Database / Schema" else
                "client_application_id" if attr_mode == "Application / Client" else
                "query_tag"
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
                df_cb = normalize_df(session.sql(f"""
                WITH {build_metered_credit_cte(days_back=cb_days)},
                query_costs AS (
                    SELECT
                        {company_expr}         AS company,
                        q.user_name,
                        q.warehouse_name,
                        COUNT(*)               AS query_count,
                        SUM(COALESCE(pqc.metered_credits,0)) AS total_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                    WHERE q.start_time >= DATEADD('days', -{cb_days}, CURRENT_TIMESTAMP())
                      AND q.warehouse_name IS NOT NULL
                    GROUP BY company, q.user_name, q.warehouse_name
                )
                SELECT company, user_name, warehouse_name, query_count,
                       ROUND(total_credits, 4) AS total_credits
                FROM query_costs
                ORDER BY total_credits DESC
                """).to_pandas())
                st.session_state["df_chargeback"] = df_cb
            except Exception as e:
                st.error(f"Chargeback failed: {e}")

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
                df_ytd = normalize_df(session.sql(f"""
                    SELECT SUM(credits_used) AS ytd_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
                    WHERE start_time >= TO_DATE('{contract_start}')
                      AND start_time <  DATEADD('hour', -24, CURRENT_TIMESTAMP())
                """).to_pandas())
                st.session_state["cc_contract_data"] = df_ytd
                st.session_state["cc_contract_params"] = {
                    "committed": committed_credits,
                    "start": str(contract_start),
                    "months": contract_months,
                }
            except Exception as e:
                st.error(f"Error loading utilization data: {e}")

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
                    df_monthly = normalize_df(session.sql(f"""
                        SELECT DATE_TRUNC('month', start_time) AS month,
                               SUM(credits_used) AS monthly_credits,
                               SUM(credits_used) * {credit_price} AS monthly_cost
                        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
                        WHERE start_time >= TO_DATE('{start_str}')
                          AND start_time <  DATEADD('hour', -24, CURRENT_TIMESTAMP())
                        GROUP BY month
                        ORDER BY month
                    """).to_pandas())
                    st.session_state["cc_monthly_data"] = df_monthly
                except Exception as e:
                    st.error(f"Monthly breakdown error: {e}")

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
            if st.button("Load Service Breakdown", key="cc_service_type"):
                try:
                    df_svc = normalize_df(session.sql(f"""
                        SELECT service_type,
                               SUM(credits_used) AS total_credits,
                               ROUND(SUM(credits_used) / NULLIF({ytd_used}, 0) * 100, 1) AS pct_of_total
                        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
                        WHERE start_time >= TO_DATE('{start_str}')
                          AND start_time <  DATEADD('hour', -24, CURRENT_TIMESTAMP())
                        GROUP BY service_type
                        ORDER BY total_credits DESC
                    """).to_pandas())
                    st.session_state["cc_svc_data"] = df_svc
                except Exception as e:
                    st.error(f"Service breakdown error: {e}")

            if st.session_state.get("cc_svc_data") is not None and not st.session_state["cc_svc_data"].empty:
                df_sv = st.session_state["cc_svc_data"]
                st.dataframe(df_sv, use_container_width=True)
                st.bar_chart(df_sv.set_index("SERVICE_TYPE")["TOTAL_CREDITS"])
                download_csv(df_sv, "contract_by_service_type.csv")
