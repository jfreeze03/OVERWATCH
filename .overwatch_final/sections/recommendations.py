# sections/recommendations.py - recommendations, persistent action queue, anomalies, alerts
import pandas as pd
import streamlit as st

from config import THRESHOLDS, ALERT_DB, ALERT_SCHEMA, ALERT_TABLE
from utils import (
    build_action_queue_ddl,
    build_alert_task_sql,
    credits_to_dollars,
    download_csv,
    format_credits,
    get_session,
    get_wh_filter_clause,
    load_action_queue,
    make_action_id,
    normalize_df,
    send_teams_alert,
    update_action_status,
    upsert_actions,
)


def _active_company() -> str:
    return st.session_state.get("active_company", "ALFA")


def _recommendation_frame(recs: list[dict]) -> pd.DataFrame:
    if not recs:
        return pd.DataFrame()
    df = pd.DataFrame(recs)
    df["Action ID"] = df.apply(
        lambda r: make_action_id(r["Category"], r["Entity"], r["Finding"]),
        axis=1,
    )
    df["Status"] = "New"
    sort_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    df["_sort"] = df["Severity"].map(sort_order).fillna(9)
    return df.sort_values(["_sort", "Estimated Monthly Savings"], ascending=[True, False]).drop(columns=["_sort"])


def _render_queue(session):
    st.header("Persistent Action Queue")
    st.caption("Owner, status, savings, generated SQL, and proof query for every actionable finding.")

    st.download_button(
        "Download Action Queue DDL",
        build_action_queue_ddl(),
        file_name="overwatch_action_queue_setup.sql",
        mime="text/plain",
        key="queue_ddl_download",
    )

    if st.button("Load Action Queue", key="queue_load"):
        try:
            st.session_state["rec_action_queue"] = load_action_queue(session)
        except Exception as e:
            st.info(f"Action queue table not found. Run the setup DDL first. ({e})")
            st.session_state["rec_action_queue"] = pd.DataFrame()

    df_queue = st.session_state.get("rec_action_queue")
    if df_queue is None:
        return
    if df_queue.empty:
        st.info("No persistent actions found yet.")
        return

    open_mask = ~df_queue["STATUS"].isin(["Fixed", "Ignored"])
    high_mask = df_queue["SEVERITY"].isin(["Critical", "High"]) & open_mask
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Open", int(open_mask.sum()))
    q2.metric("High/Critical", int(high_mask.sum()))
    q3.metric("Monthly Savings", f"${float(df_queue['EST_MONTHLY_SAVINGS'].fillna(0).sum()):,.0f}")
    q4.metric("Fixed", int((df_queue["STATUS"] == "Fixed").sum()))

    status_filter = st.selectbox(
        "Status filter",
        ["All", "New", "Acknowledged", "In Progress", "Fixed", "Ignored"],
        key="queue_status_filter",
    )
    show_df = df_queue if status_filter == "All" else df_queue[df_queue["STATUS"] == status_filter]
    st.dataframe(show_df, use_container_width=True, height=360)
    download_csv(show_df, "overwatch_action_queue.csv")

    if show_df.empty:
        return

    selected = st.selectbox("Update action", show_df["ACTION_ID"].astype(str).tolist(), key="queue_action_select")
    row = show_df[show_df["ACTION_ID"].astype(str) == selected].iloc[0]
    st.markdown(f"**{row['ENTITY_NAME']}** - {row['FINDING']}")
    st.code(str(row.get("GENERATED_SQL_FIX", "")), language="sql")
    st.caption(str(row.get("PROOF_QUERY", "")))

    c_status, c_reason = st.columns([1, 2])
    with c_status:
        new_status = st.selectbox(
            "New status",
            ["Acknowledged", "In Progress", "Fixed", "Ignored", "New"],
            key="queue_new_status",
        )
    with c_reason:
        reason = st.text_input("Reason / note", key="queue_status_reason")
    if st.button("Update status", key="queue_update_status", type="primary"):
        update_action_status(session, selected, new_status, reason)
        st.success("Action updated.")
        st.session_state["rec_action_queue"] = load_action_queue(session)
        st.rerun()


def render():
    session = get_session()
    credit_price = st.session_state.get("credit_price", 3.00)

    tab_recs, tab_queue, tab_anomaly, tab_alerts = st.tabs([
        "Recommendations", "Action Queue", "Anomaly Log", "Alert Configuration"
    ])

    with tab_recs:
        st.header("Automated Recommendations Feed")
        st.caption("Prioritized findings that can be saved into a persistent owner/status queue.")

        if st.button("Generate Recommendations", key="recs_gen"):
            recs = []
            company = _active_company()

            try:
                df_idle = normalize_df(session.sql(f"""
                WITH metering AS (
                    SELECT warehouse_name, DATE_TRUNC('hour', start_time) AS h, SUM(credits_used) AS cr
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                    WHERE start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
                      AND start_time < DATEADD('hour', -24, CURRENT_TIMESTAMP())
                      {get_wh_filter_clause("warehouse_name")}
                    GROUP BY warehouse_name, h
                ),
                qa AS (
                    SELECT warehouse_name, DATE_TRUNC('hour', start_time) AS h, COUNT(*) AS qc
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
                      AND warehouse_name IS NOT NULL
                      {get_wh_filter_clause("warehouse_name")}
                    GROUP BY warehouse_name, h
                )
                SELECT m.warehouse_name, SUM(m.cr) AS idle_credits, COUNT(*) AS idle_hours
                FROM metering m
                LEFT JOIN qa ON m.warehouse_name = qa.warehouse_name AND m.h = qa.h
                WHERE COALESCE(qa.qc, 0) = 0
                GROUP BY m.warehouse_name
                HAVING SUM(m.cr) > 1
                ORDER BY idle_credits DESC
                LIMIT 10
                """).to_pandas())
                for _, row in df_idle.iterrows():
                    monthly_savings = credits_to_dollars(float(row["IDLE_CREDITS"] or 0) / 7 * 30, credit_price)
                    recs.append({
                        "Source": "Idle warehouse detector",
                        "Severity": "High",
                        "Category": "Cost",
                        "Entity Type": "Warehouse",
                        "Entity": row["WAREHOUSE_NAME"],
                        "Owner": "DBA",
                        "Finding": f"{row['WAREHOUSE_NAME']} idle {int(row['IDLE_HOURS'])}h, wasting {format_credits(row['IDLE_CREDITS'])}",
                        "Action": f"Reduce AUTO_SUSPEND to <= {THRESHOLDS['idle_warehouse_minutes']} minutes",
                        "Estimated Monthly Savings": round(monthly_savings, 2),
                        "Generated SQL Fix": f"ALTER WAREHOUSE {row['WAREHOUSE_NAME']} SET AUTO_SUSPEND = {THRESHOLDS['idle_warehouse_minutes'] * 60};",
                        "Proof Query": "WAREHOUSE_METERING_HISTORY joined to QUERY_HISTORY by hour where query count = 0.",
                        "Company": company,
                    })
            except Exception:
                pass

            try:
                df_spill = normalize_df(session.sql(f"""
                    SELECT warehouse_name, MAX(warehouse_size) AS warehouse_size,
                           ROUND(SUM(bytes_spilled_to_remote_storage)/POWER(1024,3), 2) AS remote_gb
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
                      AND bytes_spilled_to_remote_storage > 0
                      AND warehouse_name IS NOT NULL
                      {get_wh_filter_clause("warehouse_name")}
                    GROUP BY warehouse_name
                    HAVING remote_gb > 5
                    ORDER BY remote_gb DESC
                    LIMIT 10
                """).to_pandas())
                for _, row in df_spill.iterrows():
                    recs.append({
                        "Source": "Remote spill detector",
                        "Severity": "Medium",
                        "Category": "Performance",
                        "Entity Type": "Warehouse",
                        "Entity": row["WAREHOUSE_NAME"],
                        "Owner": "DBA",
                        "Finding": f"{row['WAREHOUSE_NAME']} ({row['WAREHOUSE_SIZE']}): {row['REMOTE_GB']:.1f} GB remote spill",
                        "Action": "Review query profile; upsize or split workload if spill persists.",
                        "Estimated Monthly Savings": 0.0,
                        "Generated SQL Fix": f"-- Review memory pressure on {row['WAREHOUSE_NAME']}; consider ALTER WAREHOUSE ... SET WAREHOUSE_SIZE = '<NEXT_SIZE>';",
                        "Proof Query": "QUERY_HISTORY bytes_spilled_to_remote_storage over the last 7 days.",
                        "Company": company,
                    })
            except Exception:
                pass

            try:
                df_ftask = normalize_df(session.sql("""
                    SELECT name AS task_name, COUNT(*) AS failures
                    FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
                    WHERE scheduled_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
                      AND state = 'FAILED'
                    GROUP BY name
                    HAVING failures > 3
                    ORDER BY failures DESC
                    LIMIT 5
                """).to_pandas())
                for _, row in df_ftask.iterrows():
                    recs.append({
                        "Source": "Task failure detector",
                        "Severity": "High",
                        "Category": "Reliability",
                        "Entity Type": "Task",
                        "Entity": row["TASK_NAME"],
                        "Owner": "Data Engineering",
                        "Finding": f"Task {row['TASK_NAME']} failed {int(row['FAILURES'])} times in 7 days",
                        "Action": "Review task error logs in Task Management and fix root cause.",
                        "Estimated Monthly Savings": 0.0,
                        "Generated SQL Fix": f"-- Inspect task: {row['TASK_NAME']}\n-- EXECUTE TASK <database>.<schema>.{row['TASK_NAME']};",
                        "Proof Query": "TASK_HISTORY state = FAILED over the last 7 days.",
                        "Company": company,
                    })
            except Exception:
                pass

            try:
                df_err = normalize_df(session.sql(f"""
                    SELECT warehouse_name, COUNT(*) AS failures
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
                      AND execution_status = 'FAILED_WITH_ERROR'
                      AND warehouse_name IS NOT NULL
                      {get_wh_filter_clause("warehouse_name")}
                    GROUP BY warehouse_name
                    HAVING failures > {THRESHOLDS['error_rate_high']}
                    ORDER BY failures DESC
                    LIMIT 5
                """).to_pandas())
                for _, row in df_err.iterrows():
                    recs.append({
                        "Source": "Query failure detector",
                        "Severity": "Medium",
                        "Category": "Reliability",
                        "Entity Type": "Warehouse",
                        "Entity": row["WAREHOUSE_NAME"],
                        "Owner": "DBA",
                        "Finding": f"{row['WAREHOUSE_NAME']}: {int(row['FAILURES'])} failed queries in 7 days",
                        "Action": "Investigate error codes in Query Analysis.",
                        "Estimated Monthly Savings": 0.0,
                        "Generated SQL Fix": "-- No safe automatic SQL fix. Review failed query texts and owners.",
                        "Proof Query": "QUERY_HISTORY execution_status = FAILED_WITH_ERROR over the last 7 days.",
                        "Company": company,
                    })
            except Exception:
                pass

            st.session_state["rec_recommendations"] = recs

        recs = st.session_state.get("rec_recommendations", [])
        if recs:
            df_recs = _recommendation_frame(recs)
            high = df_recs[df_recs["Severity"].isin(["Critical", "High"])]
            monthly = float(df_recs["Estimated Monthly Savings"].sum())
            c1, c2, c3 = st.columns(3)
            c1.metric("High/Critical", len(high))
            c2.metric("Open Findings", len(df_recs))
            c3.metric("Est. Monthly Savings", f"${monthly:,.0f}")
            st.dataframe(df_recs, use_container_width=True)
            download_csv(df_recs, "recommendations.csv")

            with st.expander("Generated SQL fixes and proof queries"):
                for _, rec in df_recs.iterrows():
                    st.markdown(f"**{rec['Severity']} - {rec['Entity']}**")
                    st.code(rec["Generated SQL Fix"], language="sql")
                    st.caption(rec["Proof Query"])

            st.download_button(
                "Setup Action Queue Table",
                build_action_queue_ddl(),
                file_name="overwatch_action_queue_setup.sql",
                mime="text/plain",
                key="rec_action_queue_ddl",
            )
            if st.button("Save / refresh these findings in Action Queue", key="rec_save_queue", type="primary"):
                try:
                    saved = upsert_actions(session, df_recs.to_dict("records"))
                    st.success(f"Saved {saved} findings to the persistent action queue.")
                    st.session_state.pop("rec_action_queue", None)
                except Exception as e:
                    st.error(f"Action queue save failed: {e}")
                    st.info("Run the Action Queue setup DDL first.")
        elif st.session_state.get("rec_recommendations") == []:
            st.success("No actionable findings. Account looks healthy.")

    with tab_queue:
        _render_queue(session)

    with tab_anomaly:
        st.header("Anomaly Log")
        st.caption("Z-score based credit spike detection per warehouse using a rolling 7-day baseline.")
        anom_days = st.slider("Detection window (days)", 14, 90, 30, key="anom_days")

        if st.button("Detect Anomalies", key="anom_detect"):
            try:
                df_anom = normalize_df(session.sql(f"""
                WITH daily AS (
                    SELECT warehouse_name,
                           DATE_TRUNC('day', start_time) AS day,
                           SUM(credits_used) AS daily_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                    WHERE start_time >= DATEADD('day', -{anom_days}, CURRENT_TIMESTAMP())
                      {get_wh_filter_clause("warehouse_name")}
                    GROUP BY warehouse_name, day
                ),
                stats AS (
                    SELECT warehouse_name, day, daily_credits,
                           AVG(daily_credits) OVER (
                               PARTITION BY warehouse_name
                               ORDER BY day ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING
                           ) AS rolling_avg,
                           STDDEV(daily_credits) OVER (
                               PARTITION BY warehouse_name
                               ORDER BY day ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING
                           ) AS rolling_std
                    FROM daily
                )
                SELECT warehouse_name, day, daily_credits,
                       ROUND(rolling_avg, 4) AS rolling_avg,
                       ROUND(CASE WHEN rolling_std > 0 THEN (daily_credits - rolling_avg) / rolling_std END, 2) AS zscore,
                       CASE WHEN (daily_credits - rolling_avg) / NULLIF(rolling_std, 0) > 2 THEN 'SPIKE'
                            WHEN (daily_credits - rolling_avg) / NULLIF(rolling_std, 0) > 1.5 THEN 'ELEVATED'
                            ELSE NULL END AS anomaly_flag
                FROM stats
                WHERE rolling_avg IS NOT NULL
                  AND (daily_credits - rolling_avg) / NULLIF(rolling_std, 0) > 1.5
                ORDER BY day DESC, zscore DESC
                """).to_pandas())
                st.session_state["rec_anomalies"] = df_anom
            except Exception as e:
                st.error(f"Error: {e}")

        df_an = st.session_state.get("rec_anomalies")
        if df_an is not None:
            if not df_an.empty:
                spikes = df_an[df_an.get("ANOMALY_FLAG", pd.Series(dtype=str)).astype(str) == "SPIKE"] if "ANOMALY_FLAG" in df_an.columns else df_an
                st.warning(f"{len(spikes)} spike events detected.")
                st.dataframe(df_an, use_container_width=True)
                download_csv(df_an, "anomaly_log.csv")
            else:
                st.success("No anomalies detected in the analysis window.")

    with tab_alerts:
        st.header("Automated Alert Task Setup")
        st.caption("Generate a Snowflake task that writes anomalies to alert history and supports Teams/email routing.")

        col_a1, col_a2 = st.columns(2)
        with col_a1:
            alert_wh = st.text_input("Warehouse", value="COMPUTE_WH", key="alert_wh")
            alert_schedule = st.text_input("CRON schedule", value="0 7 * * * UTC", key="alert_cron")
        with col_a2:
            teams_webhook = st.text_input("Teams webhook URL (optional)", type="password", key="alert_teams")
            st.text_input("Email notification target (optional)", key="alert_email")

        if st.button("Generate Alert SQL", key="alert_gen"):
            sql = build_alert_task_sql(warehouse=alert_wh, schedule=f"USING CRON {alert_schedule}")
            st.code(sql, language="sql")
            st.download_button("Download SQL", sql, file_name="overwatch_alert_task.sql", mime="text/plain")
            if teams_webhook:
                ok = send_teams_alert(
                    teams_webhook,
                    "OVERWATCH alert SQL generated. Deploy the task SQL in Snowflake.",
                    "OVERWATCH Alert Setup",
                )
                st.success("Teams test sent.") if ok else st.warning("Teams test did not complete.")

        st.divider()
        st.subheader("View Alert History")
        if st.button("Load Alert History", key="alert_hist_load"):
            try:
                df_ah = normalize_df(session.sql(f"""
                    SELECT * FROM {ALERT_DB}.{ALERT_SCHEMA}.{ALERT_TABLE}
                    ORDER BY ALERT_DATE DESC
                    LIMIT 100
                """).to_pandas())
                if not df_ah.empty:
                    if "STATUS" in df_ah.columns:
                        status = st.selectbox(
                            "Filter status",
                            ["ALL"] + sorted(df_ah["STATUS"].dropna().unique().tolist()),
                            key="alert_status_filter",
                        )
                        if status != "ALL":
                            df_ah = df_ah[df_ah["STATUS"] == status]
                    st.dataframe(df_ah, use_container_width=True)
                    download_csv(df_ah, "alert_history.csv")
                else:
                    st.info("No alerts recorded yet.")
            except Exception as e:
                st.info(f"Alert table not found. Run the setup SQL first. ({e})")
