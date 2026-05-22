# sections/cortex_monitor.py — AI & Cortex Code usage: users, trends, anomalies, predictive alerts
import streamlit as st
import pandas as pd
from utils import get_session, normalize_df, safe_strip_tz, format_credits, credits_to_dollars, download_csv, render_drillable_bar_chart
from config import DEFAULTS, THRESHOLDS


AI_CREDIT_RATE = DEFAULTS["ai_credit_price"]  # $2.20/AI credit (Table 6(d))


def render():
    session = get_session()
    credit_price = st.session_state.get("credit_price", DEFAULTS["credit_price"])

    tab_users, tab_trends, tab_anomaly, tab_alerts = st.tabs([
        "Cortex Code Users", "Daily Trends", "Anomaly Detection", "Predictive Alerts"
    ])

    # ── CORTEX CODE USERS ─────────────────────────────────────────────────────
    with tab_users:
        st.header("👤 Cortex Code User Breakdown")
        st.caption(
            "Cortex Code usage (Snowsight + CLI) by user. "
            f"AI Credits billed at **${AI_CREDIT_RATE}/credit** (Table 6(d) regional inference)."
        )

        cc_days = st.slider("Lookback (days)", 7, 90, 30, key="cc_days_users")
        if st.button("Load User Data", key="cc_users_load"):
            with st.spinner("Loading Cortex Code user data..."):
                try:
                    df_cc = normalize_df(session.sql(f"""
                        WITH combined AS (
                            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, TOKENS, 'Snowsight' AS SOURCE
                            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
                            WHERE USAGE_TIME >= DATEADD('day', -{cc_days}, CURRENT_TIMESTAMP())
                            UNION ALL
                            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, TOKENS, 'CLI' AS SOURCE
                            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
                            WHERE USAGE_TIME >= DATEADD('day', -{cc_days}, CURRENT_TIMESTAMP())
                        )
                        SELECT u.NAME AS USER_NAME, u.EMAIL, c.SOURCE,
                               COUNT(*)                                   AS TOTAL_REQUESTS,
                               SUM(c.TOKEN_CREDITS)                       AS TOTAL_CREDITS,
                               SUM(c.TOKENS)                              AS TOTAL_TOKENS,
                               ROUND(SUM(c.TOKEN_CREDITS)/NULLIF(COUNT(*),0),6) AS CREDITS_PER_REQUEST,
                               MIN(c.USAGE_TIME)                          AS FIRST_USAGE,
                               MAX(c.USAGE_TIME)                          AS LAST_USAGE
                        FROM combined c
                        LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON c.USER_ID = u.USER_ID
                        GROUP BY u.NAME, u.EMAIL, c.SOURCE
                        ORDER BY TOTAL_CREDITS DESC
                    """).to_pandas())
                    st.session_state["cm_cc_users_data"] = df_cc
                except Exception as e:
                    st.warning(f"Cortex Code data unavailable: {e}")
                    st.info("Ensure CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY is available in your account (requires Cortex features enabled).")

        if st.session_state.get("cm_cc_users_data") is not None and not st.session_state["cm_cc_users_data"].empty:
            df_cc = st.session_state["cm_cc_users_data"]
            total_credits = float(df_cc["TOTAL_CREDITS"].sum())

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Active Users",           df_cc["USER_NAME"].nunique())
            c2.metric("Total Requests",         f"{int(df_cc['TOTAL_REQUESTS'].sum()):,}")
            c3.metric("Total AI Credits",       f"{total_credits:.4f}")
            c4.metric(f"Est. Cost (${AI_CREDIT_RATE}/AI cr)", f"${total_credits * AI_CREDIT_RATE:,.2f}")

            # Cost column
            df_cc = df_cc.copy()
            df_cc["COST_USD"] = df_cc["TOTAL_CREDITS"].apply(lambda x: round(x * AI_CREDIT_RATE, 4))

            # Cost by user chart
            st.subheader("Cost by User")
            user_agg = (
                df_cc.groupby("USER_NAME")["COST_USD"]
                .sum().reset_index()
                .sort_values("COST_USD", ascending=False)
                .head(20)
            )
            render_drillable_bar_chart(
                user_agg,
                dimension="USER_NAME",
                measure="COST_USD",
                key="cortex_user_cost",
                drilldown_column="user_name",
                lookback_hours=cc_days * 24,
            )

            st.subheader("Full Breakdown")
            st.dataframe(df_cc, use_container_width=True, height=350)
            download_csv(df_cc, "cortex_code_users.csv")

            # Cost-per-request spike detection
            st.divider()
            st.subheader("Cost-per-Request Spike Detection (Last 7d vs Prior)")
            if st.button("Detect CPR Spikes", key="cc_spike_load"):
                try:
                    df_spike = normalize_df(session.sql(f"""
                        WITH combined AS (
                            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, TOKENS
                            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
                            WHERE USAGE_TIME >= DATEADD('day', -{cc_days}, CURRENT_TIMESTAMP())
                            UNION ALL
                            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, TOKENS
                            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
                            WHERE USAGE_TIME >= DATEADD('day', -{cc_days}, CURRENT_TIMESTAMP())
                        ),
                        recent AS (
                            SELECT USER_ID, COUNT(*) AS requests, SUM(TOKEN_CREDITS) AS credits
                            FROM combined WHERE USAGE_TIME >= DATEADD('day',-7,CURRENT_TIMESTAMP())
                            GROUP BY USER_ID HAVING COUNT(*) >= 3
                        ),
                        prior AS (
                            SELECT USER_ID, COUNT(*) AS requests, SUM(TOKEN_CREDITS) AS credits
                            FROM combined WHERE USAGE_TIME < DATEADD('day',-7,CURRENT_TIMESTAMP())
                            GROUP BY USER_ID HAVING COUNT(*) >= 3
                        )
                        SELECT u.NAME AS USER_NAME,
                               p.requests    AS PRIOR_REQUESTS,
                               ROUND(p.credits/NULLIF(p.requests,0),6) AS PRIOR_CPR,
                               r.requests    AS RECENT_REQUESTS,
                               ROUND(r.credits/NULLIF(r.requests,0),6) AS RECENT_CPR,
                               ROUND((r.credits/NULLIF(r.requests,0))
                                     / NULLIF(p.credits/NULLIF(p.requests,0),0)*100-100, 1) AS PCT_CHANGE
                        FROM recent r JOIN prior p ON r.USER_ID = p.USER_ID
                        LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON r.USER_ID = u.USER_ID
                        ORDER BY PCT_CHANGE DESC
                    """).to_pandas())
                    if not df_spike.empty:
                        spikes = df_spike[df_spike["PCT_CHANGE"] > 25] if "PCT_CHANGE" in df_spike.columns else df_spike
                        if not spikes.empty:
                            st.warning(f"⚠️ {len(spikes)} user(s) with >25% cost-per-request increase vs prior period.")
                        st.dataframe(df_spike, use_container_width=True)
                        download_csv(df_spike, "cortex_cpr_spikes.csv")
                    else:
                        st.success("✅ No cost-per-request spikes detected.")
                except Exception as e:
                    st.warning(f"Spike detection unavailable: {e}")

    # ── DAILY TRENDS ──────────────────────────────────────────────────────────
    with tab_trends:
        st.header("📈 Cortex Code Daily Trends")
        st.caption("Daily credits, request volume, and active users — Snowsight vs CLI split.")

        cc_trend_days = st.slider("Lookback (days)", 7, 90, 30, key="cc_trend_days")
        if st.button("Load Trends", key="cc_trends_load"):
            with st.spinner("Loading trends..."):
                try:
                    df_trend = normalize_df(session.sql(f"""
                        WITH combined AS (
                            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, TOKENS, 'Snowsight' AS SOURCE
                            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
                            WHERE USAGE_TIME >= DATEADD('day', -{cc_trend_days}, CURRENT_TIMESTAMP())
                            UNION ALL
                            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, TOKENS, 'CLI' AS SOURCE
                            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
                            WHERE USAGE_TIME >= DATEADD('day', -{cc_trend_days}, CURRENT_TIMESTAMP())
                        )
                        SELECT USAGE_TIME::DATE AS USAGE_DATE,
                               SOURCE,
                               COUNT(DISTINCT USER_ID) AS ACTIVE_USERS,
                               COUNT(*)                AS TOTAL_REQUESTS,
                               SUM(TOKEN_CREDITS)      AS TOTAL_CREDITS
                        FROM combined
                        GROUP BY USAGE_DATE, SOURCE
                        ORDER BY USAGE_DATE
                    """).to_pandas())
                    st.session_state["cm_cc_trends_data"] = df_trend
                except Exception as e:
                    st.warning(f"Trends unavailable: {e}")

        if st.session_state.get("cm_cc_trends_data") is not None and not st.session_state["cm_cc_trends_data"].empty:
            df_tr = st.session_state["cm_cc_trends_data"]
            df_tr["USAGE_DATE"] = safe_strip_tz(df_tr["USAGE_DATE"])

            daily = (
                df_tr.groupby("USAGE_DATE")
                .agg(TOTAL_CREDITS=("TOTAL_CREDITS","sum"),
                     TOTAL_REQUESTS=("TOTAL_REQUESTS","sum"),
                     ACTIVE_USERS=("ACTIVE_USERS","sum"))
                .reset_index()
            )

            col_t1, col_t2 = st.columns(2)
            with col_t1:
                st.caption("Daily AI Credits")
                st.line_chart(daily.set_index("USAGE_DATE")["TOTAL_CREDITS"])
            with col_t2:
                st.caption("Daily Active Users")
                st.line_chart(daily.set_index("USAGE_DATE")["ACTIVE_USERS"])

            st.caption("Daily Requests")
            st.bar_chart(daily.set_index("USAGE_DATE")["TOTAL_REQUESTS"])

            source_agg = df_tr.groupby("SOURCE").agg(
                TOTAL_CREDITS=("TOTAL_CREDITS","sum"),
                TOTAL_REQUESTS=("TOTAL_REQUESTS","sum")
            ).reset_index()
            st.caption("Snowsight vs CLI")
            st.dataframe(source_agg, use_container_width=True)

            # 7-day rolling average overlay
            daily["ROLLING_7D"] = daily["TOTAL_CREDITS"].rolling(7, min_periods=1).mean()
            st.caption("Credits + 7-day Rolling Avg")
            st.line_chart(daily.set_index("USAGE_DATE")[["TOTAL_CREDITS","ROLLING_7D"]])

            download_csv(df_tr, "cortex_trends.csv")

    # ── ANOMALY DETECTION ─────────────────────────────────────────────────────
    with tab_anomaly:
        st.header("🔍 Cortex Code Anomaly Detection")
        st.caption("Z-score based anomaly detection on daily per-user Cortex spend.")

        cc_anom_days = st.slider("Detection window (days)", 14, 90, 30, key="cc_anom_days")
        if st.button("Detect Anomalies", key="cc_anom_load"):
            with st.spinner("Running anomaly detection..."):
                try:
                    df_anom = normalize_df(session.sql(f"""
                        WITH combined AS (
                            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS
                            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
                            WHERE USAGE_TIME >= DATEADD('day', -{cc_anom_days}, CURRENT_TIMESTAMP())
                            UNION ALL
                            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS
                            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
                            WHERE USAGE_TIME >= DATEADD('day', -{cc_anom_days}, CURRENT_TIMESTAMP())
                        ),
                        daily AS (
                            SELECT USER_ID,
                                   USAGE_TIME::DATE AS USAGE_DATE,
                                   COUNT(*)         AS REQUESTS,
                                   SUM(TOKEN_CREDITS) AS CREDITS,
                                   ROUND(SUM(TOKEN_CREDITS)/COUNT(*),6) AS CREDITS_PER_REQ
                            FROM combined GROUP BY USER_ID, USAGE_DATE
                        ),
                        with_stats AS (
                            SELECT d.*,
                                AVG(d.CREDITS) OVER (
                                    PARTITION BY d.USER_ID
                                    ORDER BY d.USAGE_DATE
                                    ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING
                                ) AS AVG_7D,
                                STDDEV(d.CREDITS) OVER (
                                    PARTITION BY d.USER_ID
                                    ORDER BY d.USAGE_DATE
                                    ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING
                                ) AS STD_7D
                            FROM daily d
                        )
                        SELECT u.NAME AS USER_NAME,
                               s.USAGE_DATE, s.REQUESTS, s.CREDITS, s.CREDITS_PER_REQ,
                               ROUND(s.AVG_7D, 6) AS ROLLING_AVG,
                               ROUND(CASE WHEN s.STD_7D > 0
                                          THEN (s.CREDITS - s.AVG_7D) / s.STD_7D END, 2) AS ZSCORE,
                               CASE
                                   WHEN COALESCE((s.CREDITS-s.AVG_7D)/NULLIF(s.STD_7D,0), 0) > 2
                                       THEN '🔴 SPEND SPIKE'
                                   WHEN COALESCE((s.CREDITS-s.AVG_7D)/NULLIF(s.STD_7D,0), 0) > 1.5
                                       THEN '🟡 ELEVATED'
                                   ELSE NULL
                               END AS ANOMALY_FLAG
                        FROM with_stats s
                        LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON s.USER_ID = u.USER_ID
                        WHERE s.AVG_7D IS NOT NULL
                        ORDER BY s.USAGE_DATE DESC, s.CREDITS DESC
                    """).to_pandas())
                    st.session_state["cm_cc_anom_data"] = df_anom
                except Exception as e:
                    st.warning(f"Anomaly detection unavailable: {e}")

        if st.session_state.get("cm_cc_anom_data") is not None and not st.session_state["cm_cc_anom_data"].empty:
            df_an = st.session_state["cm_cc_anom_data"]
            flagged = df_an[df_an.get("ANOMALY_FLAG", pd.Series()).notna()] if "ANOMALY_FLAG" in df_an.columns else pd.DataFrame()
            spikes  = df_an[df_an.get("ANOMALY_FLAG", pd.Series()).str.startswith("🔴", na=False)] if "ANOMALY_FLAG" in df_an.columns else pd.DataFrame()

            c1, c2, c3 = st.columns(3)
            c1.metric("Days Analyzed",    len(df_an["USAGE_DATE"].unique()) if "USAGE_DATE" in df_an.columns else 0)
            c2.metric("Anomalous Days",   len(flagged), delta_color="inverse")
            c3.metric("🔴 Spend Spikes",  len(spikes),  delta_color="inverse")

            if not flagged.empty:
                st.warning(f"⚠️ {len(flagged)} anomalous Cortex Code usage day(s) detected.")
                st.dataframe(flagged, use_container_width=True)

            with st.expander("View Full Dataset"):
                st.dataframe(df_an, use_container_width=True)

            download_csv(df_an, "cortex_anomalies.csv")
        elif st.session_state.get("cm_cc_anom_data") is not None:
            st.success("✅ No anomalies detected in the analysis window.")

    # ── PREDICTIVE ALERTS ─────────────────────────────────────────────────────
    with tab_alerts:
        st.header("🔮 Predictive Cortex AI Cost Alerts")
        st.caption(
            "Projects Cortex Code spend at current trajectory. "
            "Flags accounts on course to exceed configurable monthly budget."
        )

        monthly_ai_budget = st.number_input(
            "Monthly AI credit budget", min_value=0.0, value=500.0, step=50.0, key="ai_budget"
        )

        if st.button("Run Predictive Analysis", key="cc_pred_load"):
            try:
                df_pred = normalize_df(session.sql("""
                    WITH combined AS (
                        SELECT USAGE_TIME::DATE AS d, SUM(TOKEN_CREDITS) AS credits
                        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
                        WHERE USAGE_TIME >= DATEADD('month',-1,CURRENT_TIMESTAMP())
                        GROUP BY d
                        UNION ALL
                        SELECT USAGE_TIME::DATE AS d, SUM(TOKEN_CREDITS) AS credits
                        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
                        WHERE USAGE_TIME >= DATEADD('month',-1,CURRENT_TIMESTAMP())
                        GROUP BY d
                    )
                    SELECT d AS USAGE_DATE, SUM(credits) AS DAILY_CREDITS
                    FROM combined GROUP BY d ORDER BY d
                """).to_pandas())
                st.session_state["cm_cc_pred_data"] = df_pred
            except Exception as e:
                st.warning(f"Projection data unavailable: {e}")

        if st.session_state.get("cm_cc_pred_data") is not None and not st.session_state["cm_cc_pred_data"].empty:
            df_p = st.session_state["cm_cc_pred_data"]
            avg_daily = float(df_p["DAILY_CREDITS"].mean())
            days_in_month = 30
            projected_month = avg_daily * days_in_month
            projected_cost  = projected_month * AI_CREDIT_RATE

            c1, c2, c3 = st.columns(3)
            c1.metric("Avg Daily AI Credits", f"{avg_daily:.4f}")
            c2.metric("Projected 30-day Credits", f"{projected_month:.4f}")
            c3.metric("Projected 30-day Cost",    f"${projected_cost:,.2f}")

            if projected_month > monthly_ai_budget:
                overage = projected_month - monthly_ai_budget
                st.error(
                    f"🔴 **On track to exceed budget by {overage:.2f} AI credits "
                    f"(${overage * AI_CREDIT_RATE:,.2f})**. "
                    f"Consider setting user-level quotas or reviewing heavy users."
                )
            else:
                headroom = monthly_ai_budget - projected_month
                st.success(
                    f"✅ Projected spend ({projected_month:.2f} credits) is within budget. "
                    f"Headroom: {headroom:.2f} credits."
                )

            st.caption("Daily Credit Trend (last 30 days)")
            df_p["USAGE_DATE"] = safe_strip_tz(df_p["USAGE_DATE"])
            st.line_chart(df_p.set_index("USAGE_DATE")["DAILY_CREDITS"])

            # MV Refresh History tab extra (bonus)
            st.divider()
            st.subheader("🔄 Materialized View Refresh History")
            if st.button("Load MV Refresh History", key="mv_refresh_load"):
                try:
                    df_mv = normalize_df(session.sql("""
                        SELECT database_name, schema_name, name AS mv_name,
                               credits_used, bytes_written, rows_inserted,
                               refresh_start_time, refresh_end_time,
                               DATEDIFF('second', refresh_start_time, refresh_end_time) AS duration_sec
                        FROM SNOWFLAKE.ACCOUNT_USAGE.MATERIALIZED_VIEW_REFRESH_HISTORY
                        WHERE refresh_start_time >= DATEADD('day',-7,CURRENT_TIMESTAMP())
                        ORDER BY credits_used DESC LIMIT 100
                    """).to_pandas())
                    if not df_mv.empty:
                        c1, c2 = st.columns(2)
                        c1.metric("MV Refreshes (7d)", len(df_mv))
                        c2.metric("Total Credits",     format_credits(df_mv["CREDITS_USED"].sum()))
                        st.dataframe(df_mv, use_container_width=True)
                        download_csv(df_mv, "mv_refresh_history.csv")
                    else:
                        st.info("No materialized view refresh activity in the last 7 days.")
                except Exception as e:
                    st.warning(f"MV refresh history unavailable: {e}")
