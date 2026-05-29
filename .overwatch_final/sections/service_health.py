# sections/service_health.py - service availability and operational posture
import pandas as pd
import streamlit as st

from utils import (
    build_task_health_sql,
    download_csv,
    filter_existing_columns,
    get_active_company,
    get_db_filter_clause,
    get_session,
    get_user_filter_clause,
    get_wh_filter_clause,
    metric_confidence_label,
    freshness_note,
    format_snowflake_error,
    run_query,
    service_health_scorecard,
    upsert_actions,
)


def _load_service_health(session, hours: int) -> dict:
    company = get_active_company()
    wh_q = get_wh_filter_clause("q.warehouse_name")
    db_q = get_db_filter_clause("q.database_name")
    user_q = get_user_filter_clause("q.user_name")
    user_l = get_user_filter_clause("user_name")
    db_copy = get_db_filter_clause("table_catalog_name")
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "ERROR_CODE",
            "WAREHOUSE_SIZE",
            "QUEUED_OVERLOAD_TIME",
            "TRANSACTION_BLOCKED_TIME",
            "BYTES_SPILLED_TO_REMOTE_STORAGE",
            "PERCENTAGE_SCANNED_FROM_CACHE",
        ],
    ))
    error_pred = (
        "q.error_code IS NOT NULL"
        if "ERROR_CODE" in qh_cols else "UPPER(q.execution_status) = 'FAILED_WITH_ERROR'"
    )
    queued_pred = (
        "q.queued_overload_time > 0"
        if "QUEUED_OVERLOAD_TIME" in qh_cols else "FALSE"
    )
    blocked_pred = (
        "q.transaction_blocked_time > 0"
        if "TRANSACTION_BLOCKED_TIME" in qh_cols else "FALSE"
    )
    wh_size_expr = (
        "MAX(q.warehouse_size)"
        if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR"
    )
    queued_sec_expr = (
        "ROUND(SUM(q.queued_overload_time) / 1000, 2)"
        if "QUEUED_OVERLOAD_TIME" in qh_cols else "0::FLOAT"
    )
    remote_spill_expr = (
        "ROUND(SUM(q.bytes_spilled_to_remote_storage) / POWER(1024, 3), 2)"
        if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols else "0::FLOAT"
    )
    cache_expr = (
        "ROUND(AVG(q.percentage_scanned_from_cache), 2)"
        if "PERCENTAGE_SCANNED_FROM_CACHE" in qh_cols else "0::FLOAT"
    )

    query_health = run_query(f"""
        SELECT
            COUNT(*) AS total_queries,
            SUM(IFF({error_pred}, 1, 0)) AS failed_queries,
            SUM(IFF({queued_pred}, 1, 0)) AS queued_queries,
            SUM(IFF({blocked_pred}, 1, 0)) AS blocked_queries,
            ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY q.total_elapsed_time) / 1000, 2) AS p95_elapsed_sec
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {wh_q} {db_q} {user_q}
    """, ttl_key=f"svc_query_{company}_{hours}", tier="recent")

    warehouse_health = run_query(f"""
        SELECT
            q.warehouse_name,
            {wh_size_expr} AS warehouse_size,
            COUNT(*) AS total_queries,
            SUM(IFF({error_pred}, 1, 0)) AS failed_queries,
            {queued_sec_expr} AS queued_sec,
            {remote_spill_expr} AS remote_spill_gb,
            {cache_expr} AS avg_cache_pct
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {wh_q} {db_q} {user_q}
        GROUP BY q.warehouse_name
        ORDER BY queued_sec DESC, remote_spill_gb DESC, failed_queries DESC
        LIMIT 100
    """, ttl_key=f"svc_warehouse_{company}_{hours}", tier="recent")

    login_health = run_query(f"""
        SELECT
            COUNT(*) AS login_events,
            SUM(IFF(is_success = 'NO', 1, 0)) AS failed_logins,
            COUNT(DISTINCT user_name) AS login_users,
            COUNT(DISTINCT client_ip) AS distinct_ips
        FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
        WHERE event_timestamp >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
          {user_l}
    """, ttl_key=f"svc_login_{company}_{hours}", tier="recent")

    try:
        task_health = run_query(
            build_task_health_sql(
                session,
                f"scheduled_time >= DATEADD('hour', -{int(hours)}, CURRENT_TIMESTAMP())",
                company=company,
            ),
            ttl_key=f"svc_task_{company}_{hours}",
            tier="recent",
        )
    except Exception:
        task_health = pd.DataFrame([{
            "TASK_RUNS": 0,
            "FAILED_TASKS": 0,
            "SUCCEEDED_TASKS": 0,
            "DISTINCT_TASKS": 0,
        }])

    pipe_health = run_query(f"""
        SELECT
            COUNT(*) AS load_events,
            SUM(IFF(status = 'LOAD_FAILED', 1, 0)) AS failed_loads,
            ROUND(SUM(row_count), 0) AS rows_loaded,
            ROUND(SUM(file_size) / POWER(1024, 3), 2) AS gb_loaded
        FROM SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY
        WHERE last_load_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
          {db_copy}
    """, ttl_key=f"svc_pipe_{company}_{hours}", tier="recent")

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
                st.warning(f"Service health data unavailable in this role/context: {format_snowflake_error(e)}")

    data = st.session_state.get("svc_data")
    if not data:
        return

    qh = data["query_health"]
    lh = data["login_health"]
    th = data["task_health"]
    ph = data["pipe_health"]
    wh_df = data["warehouse_health"]
    wh_bad = 0 if wh_df.empty else len(wh_df[(wh_df["QUEUED_SEC"] > 60) | (wh_df["REMOTE_SPILL_GB"] > 1) | (wh_df["FAILED_QUERIES"] > 0)])
    scorecard = service_health_scorecard({
        "total_queries": _value(qh, "TOTAL_QUERIES"),
        "failed_queries": _value(qh, "FAILED_QUERIES"),
        "queued_queries": _value(qh, "QUEUED_QUERIES"),
        "blocked_queries": _value(qh, "BLOCKED_QUERIES"),
        "p95_elapsed_sec": _value(qh, "P95_ELAPSED_SEC"),
        "warehouse_count": len(wh_df),
        "pressured_warehouses": wh_bad,
        "task_runs": _value(th, "TASK_RUNS"),
        "failed_tasks": _value(th, "FAILED_TASKS"),
        "login_events": _value(lh, "LOGIN_EVENTS"),
        "failed_logins": _value(lh, "FAILED_LOGINS"),
        "load_events": _value(ph, "LOAD_EVENTS"),
        "failed_loads": _value(ph, "FAILED_LOADS"),
    })
    services = pd.DataFrame(scorecard["components"])
    action_map = {
        "Query Processor": ("Review failed and queued queries in Detailed Diagnosis.", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"),
        "Warehouse Availability": ("Review Warehouse Health efficiency and pressure metrics.", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY grouped by warehouse"),
        "Login/Auth": ("Review Security & Access login audit and MFA coverage.", "SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY"),
        "Task Service": ("Review Task Management failed jobs and DAG health.", "SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY"),
        "Data Load": ("Review Pipeline Health load failures and freshness.", "SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY"),
    }
    services["ACTION"] = services["SERVICE"].map(lambda name: action_map.get(name, ("Review source detail.", "ACCOUNT_USAGE"))[0])
    services["PROOF"] = services["SERVICE"].map(lambda name: action_map.get(name, ("Review source detail.", "ACCOUNT_USAGE"))[1])

    cols = st.columns(5)
    for idx, row in services.iterrows():
        label = "Healthy" if row["SCORE"] >= 90 else ("Watch" if row["SCORE"] >= 75 else ("At Risk" if row["SCORE"] >= 60 else "Critical"))
        cols[idx].metric(row["SERVICE"], f"{row['SCORE']:.1f}", label)
    st.metric("Overall Service Score", f"{scorecard['score']:.1f}", scorecard["label"])
    st.caption(f"{metric_confidence_label('composite')} | {freshness_note('ACCOUNT_USAGE')}")

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
