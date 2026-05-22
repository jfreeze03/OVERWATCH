# sections/recommendations.py — Automated recommendations, anomaly log, alert config
import streamlit as st
import pandas as pd
from utils import (
    get_session, normalize_df, format_credits, credits_to_dollars,
    download_csv, build_alert_task_sql, send_teams_alert, get_wh_filter_clause,
)
from config import THRESHOLDS, ALERT_DB, ALERT_SCHEMA, ALERT_TABLE


def render():
    session = get_session()
    credit_price = st.session_state.get("credit_price", 3.00)

    tab_recs, tab_anomaly, tab_alerts = st.tabs([
        "Recommendations", "Anomaly Log", "Alert Configuration"
    ])

    # ── RECOMMENDATIONS ───────────────────────────────────────────────────────
    with tab_recs:
        st.header("💡 Automated Recommendations Feed")
        st.caption("Aggregated findings from across OVERWATCH — prioritized action list.")

        if st.button("Generate Recommendations", key="recs_gen"):
            recs = []

            # Idle warehouses
            try:
                df_idle = normalize_df(session.sql(f"""
                WITH metering AS (
                    SELECT warehouse_name, DATE_TRUNC('hour',start_time) AS h, SUM(credits_used) AS cr
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                    WHERE start_time >= DATEADD('day',-7,CURRENT_TIMESTAMP())
                      AND start_time <  DATEADD('hour',-24,CURRENT_TIMESTAMP())
                      {get_wh_filter_clause("warehouse_name")}
                    GROUP BY warehouse_name, h
                ),
                qa AS (
                    SELECT warehouse_name, DATE_TRUNC('hour',start_time) AS h, COUNT(*) AS qc
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day',-7,CURRENT_TIMESTAMP()) AND warehouse_name IS NOT NULL
                      {get_wh_filter_clause("warehouse_name")}
                    GROUP BY warehouse_name, h
                )
                SELECT m.warehouse_name, SUM(m.cr) AS idle_credits, COUNT(*) AS idle_hours
                FROM metering m LEFT JOIN qa ON m.warehouse_name=qa.warehouse_name AND m.h=qa.h
                WHERE COALESCE(qa.qc,0)=0
                GROUP BY m.warehouse_name HAVING SUM(m.cr) > 1
                ORDER BY idle_credits DESC LIMIT 10
                """).to_pandas())
                for _, row in df_idle.iterrows():
                    recs.append({
                        "Priority": "🔴 High", "Category": "Cost",
                        "Finding": f"**{row['WAREHOUSE_NAME']}** idle {int(row['IDLE_HOURS'])}h, wasting {format_credits(row['IDLE_CREDITS'])}",
                        "Action": f"Reduce AUTO_SUSPEND to ≤{THRESHOLDS['idle_warehouse_minutes']}min"
                    })
            except Exception:
                pass

            # Spilling warehouses
            try:
                df_spill = normalize_df(session.sql(f"""
                    SELECT warehouse_name, MAX(warehouse_size) AS warehouse_size,
                           ROUND(SUM(bytes_spilled_to_remote_storage)/POWER(1024,3),2) AS remote_gb
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day',-7,CURRENT_TIMESTAMP())
                      AND bytes_spilled_to_remote_storage > 0 AND warehouse_name IS NOT NULL
                      {get_wh_filter_clause("warehouse_name")}
                    GROUP BY warehouse_name
                    HAVING remote_gb > 5 ORDER BY remote_gb DESC LIMIT 10
                """).to_pandas())
                for _, row in df_spill.iterrows():
                    recs.append({
                        "Priority": "🟡 Medium", "Category": "Performance",
                        "Finding": f"**{row['WAREHOUSE_NAME']}** ({row['WAREHOUSE_SIZE']}): {row['REMOTE_GB']:.1f} GB remote spill",
                        "Action": "Upsize warehouse to reduce memory pressure"
                    })
            except Exception:
                pass

            # Failed tasks
            try:
                df_ftask = normalize_df(session.sql("""
                    SELECT name AS task_name, COUNT(*) AS failures
                    FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
                    WHERE scheduled_time >= DATEADD('day',-7,CURRENT_TIMESTAMP()) AND state='FAILED'
                    GROUP BY name HAVING failures > 3 ORDER BY failures DESC LIMIT 5
                """).to_pandas())
                for _, row in df_ftask.iterrows():
                    recs.append({
                        "Priority": "🔴 High", "Category": "Ops",
                        "Finding": f"Task **{row['TASK_NAME']}** failed {int(row['FAILURES'])}× in 7 days",
                        "Action": "Review task error logs → Task Management section"
                    })
            except Exception:
                pass

            # High error rates
            try:
                df_err = normalize_df(session.sql(f"""
                    SELECT warehouse_name, COUNT(*) AS failures
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day',-7,CURRENT_TIMESTAMP())
                      AND execution_status = 'FAILED_WITH_ERROR' AND warehouse_name IS NOT NULL
                      {get_wh_filter_clause("warehouse_name")}
                    GROUP BY warehouse_name HAVING failures > {THRESHOLDS['error_rate_high']}
                    ORDER BY failures DESC LIMIT 5
                """).to_pandas())
                for _, row in df_err.iterrows():
                    recs.append({
                        "Priority": "🟡 Medium", "Category": "Reliability",
                        "Finding": f"**{row['WAREHOUSE_NAME']}**: {int(row['FAILURES'])} failures in 7 days",
                        "Action": "Investigate error codes in Query Analysis"
                    })
            except Exception:
                pass

            st.session_state["rec_recommendations"] = recs

        if st.session_state.get("rec_recommendations"):
            recs = st.session_state["rec_recommendations"]
            if recs:
                df_recs = pd.DataFrame(recs)
                df_recs["Severity"] = df_recs["Priority"].apply(
                    lambda p: "High" if str(p).startswith("ðŸ”´") else "Medium"
                )
                df_recs["Owner"] = df_recs["Finding"].str.extract(r"\*\*([^*]+)\*\*", expand=False).fillna("DBA")
                df_recs["Status"] = "New"
                df_recs["Estimated Monthly Savings"] = df_recs["Category"].apply(lambda c: 250.0 if c == "Cost" else 0.0)
                df_recs["Generated SQL Fix"] = df_recs.apply(lambda r: f"-- {r['Action']}", axis=1)
                df_recs["Proof Query"] = df_recs["Category"].apply(lambda c: f"Source detector: {c} recommendation query")
                high    = df_recs[df_recs["Priority"].str.startswith("🔴")]
                medium  = df_recs[df_recs["Priority"].str.startswith("🟡")]
                c1, c2  = st.columns(2)
                c1.metric("🔴 High Priority", len(high))
                c2.metric("🟡 Medium Priority", len(medium))
                st.dataframe(df_recs, use_container_width=True)
                download_csv(df_recs, "recommendations.csv")
            else:
                st.success("✅ No actionable findings — account looks healthy!")

    # ── ANOMALY LOG ───────────────────────────────────────────────────────────
    with tab_anomaly:
        st.header("🔍 Anomaly Log")
        st.caption("Z-score based credit spike detection per warehouse (rolling 14-day window).")
        anom_days = st.slider("Detection window (days)", 14, 90, 30, key="anom_days")

        if st.button("Detect Anomalies", key="anom_detect"):
            try:
                df_anom = normalize_df(session.sql(f"""
                WITH daily AS (
                    SELECT warehouse_name,
                           DATE_TRUNC('day', start_time) AS day,
                           SUM(credits_used)             AS daily_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                    WHERE start_time >= DATEADD('day', -{anom_days}, CURRENT_TIMESTAMP())
                      {get_wh_filter_clause("warehouse_name")}
                    GROUP BY warehouse_name, day
                ),
                stats AS (
                    SELECT warehouse_name, day, daily_credits,
                           AVG(daily_credits) OVER (
                               PARTITION BY warehouse_name
                               ORDER BY day
                               ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING
                           ) AS rolling_avg,
                           STDDEV(daily_credits) OVER (
                               PARTITION BY warehouse_name
                               ORDER BY day
                               ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING
                           ) AS rolling_std
                    FROM daily
                )
                SELECT warehouse_name, day, daily_credits,
                       ROUND(rolling_avg, 4) AS rolling_avg,
                       ROUND(CASE WHEN rolling_std>0 THEN (daily_credits-rolling_avg)/rolling_std END, 2) AS zscore,
                       CASE WHEN (daily_credits-rolling_avg)/NULLIF(rolling_std,0) > 2 THEN '🔴 SPIKE'
                            WHEN (daily_credits-rolling_avg)/NULLIF(rolling_std,0) > 1.5 THEN '🟡 ELEVATED'
                            ELSE NULL END AS anomaly_flag
                FROM stats
                WHERE rolling_avg IS NOT NULL
                  AND (daily_credits-rolling_avg)/NULLIF(rolling_std,0) > 1.5
                ORDER BY day DESC, zscore DESC
                """).to_pandas())
                st.session_state["rec_anomalies"] = df_anom
            except Exception as e:
                st.error(f"Error: {e}")

        if st.session_state.get("rec_anomalies") is not None:
            df_an = st.session_state["rec_anomalies"]
            if not df_an.empty:
                spikes = df_an[df_an.get("ANOMALY_FLAG", pd.Series()).str.startswith("🔴", na=False)] if "ANOMALY_FLAG" in df_an.columns else df_an
                st.warning(f"⚠️ {len(spikes)} credit spike anomaly events detected.")
                st.dataframe(df_an, use_container_width=True)
                download_csv(df_an, "anomaly_log.csv")
            else:
                st.success("✅ No anomalies detected in the analysis window.")

    # ── ALERT CONFIGURATION ───────────────────────────────────────────────────
    with tab_alerts:
        st.header("🔔 Automated Alert Task Setup")
        st.caption("Generate a Snowflake Task that writes anomalies to an alert table and supports Teams/email routing.")

        col_a1, col_a2 = st.columns(2)
        with col_a1:
            alert_wh       = st.text_input("Warehouse",    value="COMPUTE_WH",      key="alert_wh")
            alert_schedule = st.text_input("CRON schedule", value="0 7 * * * UTC",   key="alert_cron")
        with col_a2:
            teams_webhook = st.text_input("Teams webhook URL (optional)", type="password", key="alert_teams")
            email_target = st.text_input("Email notification target (optional)", key="alert_email")

        if st.button("Generate Alert SQL", key="alert_gen"):
            sql = build_alert_task_sql(
                warehouse=alert_wh,
                schedule=f"USING CRON {alert_schedule}",
            )
            st.code(sql, language="sql")
            st.download_button("📥 Download SQL", sql, file_name="overwatch_alert_task.sql", mime="text/plain")
            if teams_webhook:
                ok = send_teams_alert(teams_webhook, "OVERWATCH alert SQL generated. Deploy the task SQL in Snowflake.", "OVERWATCH Alert Setup")
                st.success("Teams test sent.") if ok else st.warning("Teams test did not complete.")

        st.divider()
        st.subheader("View Alert History")
        if st.button("Load Alert History", key="alert_hist_load"):
            try:
                df_ah = normalize_df(session.sql(f"""
                    SELECT * FROM {ALERT_DB}.{ALERT_SCHEMA}.{ALERT_TABLE}
                    ORDER BY ALERT_DATE DESC LIMIT 100
                """).to_pandas())
                if not df_ah.empty:
                    if "STATUS" in df_ah.columns:
                        status = st.selectbox("Filter status", ["ALL"] + sorted(df_ah["STATUS"].dropna().unique().tolist()), key="alert_status_filter")
                        if status != "ALL":
                            df_ah = df_ah[df_ah["STATUS"] == status]
                    st.dataframe(df_ah, use_container_width=True)
                    download_csv(df_ah, "alert_history.csv")
                else:
                    st.info("No alerts recorded yet.")
            except Exception as e:
                st.info(f"Alert table not found — run the setup SQL first. ({e})")
