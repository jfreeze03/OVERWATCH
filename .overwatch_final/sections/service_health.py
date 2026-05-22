# sections/service_health.py - service availability and operational posture
import pandas as pd
import streamlit as st

from utils import (
    download_csv,
    get_active_company,
    get_db_filter_clause,
    get_session,
    get_wh_filter_clause,
    normalize_df,
    upsert_actions,
)


def _load_service_health(session, hours: int) -> dict:
    wh_q = get_wh_filter_clause("q.warehouse_name")
    db_task = get_db_filter_clause("database_name")
    db_copy = get_db_filter_clause("table_catalog_name")

    query_health = normalize_df(session.sql(f"""
        SELECT
            COUNT(*) AS total_queries,
            SUM(IFF(q.error_code IS NOT NULL, 1, 0)) AS failed_queries,
            SUM(IFF(q.queued_overload_time > 0, 1, 0)) AS queued_queries,
            SUM(IFF(q.transaction_blocked_time > 0, 1, 0)) AS blocked_queries,
            ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY q.total_elapsed_time) / 1000, 2) AS p95_elapsed_sec
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {wh_q}
    """).to_pandas())

    warehouse_health = normalize_df(session.sql(f"""
        SELECT
            q.warehouse_name,
            MAX(q.warehouse_size) AS warehouse_size,
            COUNT(*) AS total_queries,
            SUM(IFF(q.error_code IS NOT NULL, 1, 0)) AS failed_queries,
            ROUND(SUM(q.queued_overload_time) / 1000, 2) AS queued_sec,
            ROUND(SUM(q.bytes_spilled_to_remote_storage) / POWER(1024, 3), 2) AS remote_spill_gb,
            ROUND(AVG(q.percentage_scanned_from_cache), 2) AS avg_cache_pct
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {wh_q}
        GROUP BY q.warehouse_name
        ORDER BY queued_sec DESC, remote_spill_gb DESC, failed_queries DESC
        LIMIT 100
    """).to_pandas())

    login_health = normalize_df(session.sql(f"""
        SELECT
            COUNT(*) AS login_events,
            SUM(IFF(is_success = 'NO', 1, 0)) AS failed_logins,
            COUNT(DISTINCT user_name) AS login_users,
            COUNT(DISTINCT client_ip) AS distinct_ips
        FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
        WHERE event_timestamp >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
    """).to_pandas())

    task_health = normalize_df(session.sql(f"""
        SELECT
            COUNT(*) AS task_runs,
            SUM(IFF(state = 'FAILED', 1, 0)) AS failed_tasks,
            SUM(IFF(state = 'SUCCEEDED', 1, 0)) AS succeeded_tasks,
            COUNT(DISTINCT name) AS distinct_tasks
        FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
        WHERE scheduled_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
          {db_task}
    """).to_pandas())

    pipe_health = normalize_df(session.sql(f"""
        SELECT
            COUNT(*) AS load_events,
            SUM(IFF(status = 'LOAD_FAILED', 1, 0)) AS failed_loads,
            ROUND(SUM(row_count), 0) AS rows_loaded,
            ROUND(SUM(file_size) / POWER(1024, 3), 2) AS gb_loaded
        FROM SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY
        WHERE last_load_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
          {db_copy}
    """).to_pandas())

    return {
        "query_health": query_health,
        "warehouse_health": warehouse_health,
        "login_health": login_health,
        "task_health": task_health,
        "pipe_health": pipe_health,
    }


def _value(df, col: str) -> float:
    if df is None or df.empty or col not in df.columns:
        return 0.0
    return float(df.iloc[0].get(col, 0) or 0)


def _score(total: float, bad: float, penalty: float = 100.0) -> float:
    if total <= 0:
        return 100.0
    return max(0.0, min(100.0, 100.0 - (bad / total * penalty)))


def _queue_service_findings(session, services: pd.DataFrame):
    if services is None or services.empty:
        return
    company = get_active_company()
    actions = []
    for _, row in services[services["SCORE"] < 95].iterrows():
        service = str(row["SERVICE"])
        actions.append({
            "Source": "Service Health",
            "Category": "Availability",
            "Severity": "Critical" if float(row["SCORE"]) < 80 else "High",
            "Entity Type": "Snowflake Service",
            "Entity": service,
            "Owner": "DBA",
            "Finding": f"{service} score is {float(row['SCORE']):.1f}. {row['SIGNAL']}",
            "Action": str(row["ACTION"]),
            "Estimated Monthly Savings": 0,
            "Generated SQL Fix": "-- Investigate the linked Snowflake ACCOUNT_USAGE views before changing capacity or access controls.",
            "Proof Query": str(row["PROOF"]),
            "Company": company,
        })
    saved = upsert_actions(session, actions)
    st.success(f"Saved {saved} service health findings to the action queue.")


def render():
    session = get_session()
    st.header("Service Health")
    st.caption("Availability-style posture across query execution, warehouses, login/auth, tasks, and data loading.")

    hours = st.slider("Lookback hours", 1, 168, 24, key="svc_hours")
    if st.button("Load Service Health", key="svc_load"):
        with st.spinner("Loading service posture..."):
            try:
                st.session_state["svc_data"] = _load_service_health(session, hours)
            except Exception as e:
                st.error(f"Unable to load service health: {e}")

    data = st.session_state.get("svc_data")
    if not data:
        return

    qh = data["query_health"]
    lh = data["login_health"]
    th = data["task_health"]
    ph = data["pipe_health"]

    query_score = _score(_value(qh, "TOTAL_QUERIES"), _value(qh, "FAILED_QUERIES") + _value(qh, "QUEUED_QUERIES") * 0.25)
    login_score = _score(_value(lh, "LOGIN_EVENTS"), _value(lh, "FAILED_LOGINS"))
    task_score = _score(_value(th, "TASK_RUNS"), _value(th, "FAILED_TASKS"))
    load_score = _score(_value(ph, "LOAD_EVENTS"), _value(ph, "FAILED_LOADS"))
    wh_df = data["warehouse_health"]
    wh_bad = 0 if wh_df.empty else len(wh_df[(wh_df["QUEUED_SEC"] > 60) | (wh_df["REMOTE_SPILL_GB"] > 1) | (wh_df["FAILED_QUERIES"] > 0)])
    wh_score = _score(max(len(wh_df), 1), wh_bad)

    services = pd.DataFrame([
        {"SERVICE": "Query Processor", "SCORE": query_score, "SIGNAL": f"{_value(qh, 'FAILED_QUERIES'):,.0f} failed, {_value(qh, 'QUEUED_QUERIES'):,.0f} queued.", "ACTION": "Review failed and queued queries in Detailed Diagnosis.", "PROOF": "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"},
        {"SERVICE": "Warehouse Availability", "SCORE": wh_score, "SIGNAL": f"{wh_bad} warehouses have queue, spill, or failures.", "ACTION": "Review Warehouse Health efficiency and pressure metrics.", "PROOF": "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY grouped by warehouse"},
        {"SERVICE": "Login/Auth", "SCORE": login_score, "SIGNAL": f"{_value(lh, 'FAILED_LOGINS'):,.0f} failed login events.", "ACTION": "Review Security & Access login audit and MFA coverage.", "PROOF": "SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY"},
        {"SERVICE": "Task Service", "SCORE": task_score, "SIGNAL": f"{_value(th, 'FAILED_TASKS'):,.0f} failed task runs.", "ACTION": "Review Task Management failed jobs and DAG health.", "PROOF": "SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY"},
        {"SERVICE": "Data Load", "SCORE": load_score, "SIGNAL": f"{_value(ph, 'FAILED_LOADS'):,.0f} failed load events.", "ACTION": "Review Pipeline Health load failures and freshness.", "PROOF": "SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY"},
    ])

    cols = st.columns(5)
    for idx, row in services.iterrows():
        label = "Healthy" if row["SCORE"] >= 95 else ("Watch" if row["SCORE"] >= 80 else "At Risk")
        cols[idx].metric(row["SERVICE"], f"{row['SCORE']:.1f}", label)

    if (services["SCORE"] < 95).any() and st.button("Send service findings to Action Queue", key="svc_queue"):
        _queue_service_findings(session, services)

    st.subheader("Service Scorecard")
    st.dataframe(services, use_container_width=True, height=260)
    download_csv(services, "service_health_scorecard.csv")

    st.subheader("Warehouse Pressure Detail")
    if wh_df.empty:
        st.info("No warehouse activity found for the selected window.")
    else:
        st.dataframe(wh_df, use_container_width=True, height=360)
        download_csv(wh_df, "service_health_warehouse_pressure.csv")
