# sections/service_health.py - service availability and operational posture
import pandas as pd
import streamlit as st

from sections.shell_helpers import render_shell_snapshot
from utils import (
    defer_source_note,
    download_csv,
    get_active_company,
    get_session,
    load_shared_service_login_health,
    load_shared_service_pipe_health,
    load_shared_service_query_health,
    load_shared_service_task_health,
    load_shared_service_warehouse_health,
    metric_confidence_label,
    freshness_note,
    format_snowflake_error,
    safe_float,
    service_health_scorecard,
    upsert_actions,
)
from utils.workflows import render_load_status, render_priority_dataframe


def _load_service_health(session, hours: int) -> dict:
    company = get_active_company()
    query_result = load_shared_service_query_health(
        session,
        hours,
        company,
        section="Service Health",
    )
    warehouse_result = load_shared_service_warehouse_health(
        session,
        hours,
        company,
        section="Service Health",
    )
    login_result = load_shared_service_login_health(
        hours,
        company,
        section="Service Health",
    )
    task_result = load_shared_service_task_health(
        session,
        hours,
        company,
        section="Service Health",
    )
    pipe_result = load_shared_service_pipe_health(
        hours,
        company,
        section="Service Health",
    )

    return {
        "query_health": query_result.data,
        "warehouse_health": warehouse_result.data,
        "login_health": login_result.data,
        "task_health": task_result.data,
        "pipe_health": pipe_result.data,
        "sources": {
            "query": query_result.source,
            "warehouse": warehouse_result.source,
            "login": login_result.source,
            "task": task_result.source,
            "pipe": pipe_result.source,
        },
    }


def _value(df, col: str) -> float:
    if df is None or df.empty or col not in df.columns:
        return 0.0
    return safe_float(df.iloc[0].get(col, 0))


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
            "Finding": f"{service} service signal: {row['SIGNAL']}",
            "Action": str(row["ACTION"]),
            "Estimated Monthly Savings": 0,
            "Generated SQL Fix": "-- Investigate the linked Snowflake ACCOUNT_USAGE views before changing capacity or access controls.",
            "Proof Query": str(row["PROOF"]),
            "Company": company,
        })
    saved = upsert_actions(session, actions)
    st.success(f"Saved {saved} service health findings to the action queue.")


def render():
    # SESSION_OPEN_ADMIN_OK boundary=admin reason=legacy_session budget=advanced_diagnostics owner=platform
    session = get_session()
    st.subheader("Service Health")
    st.caption("Availability-style posture across query execution, warehouses, login/auth, tasks, and data loading.")

    hours = st.slider("Lookback hours", 1, 168, 24, key="svc_hours")
    if st.button("Load Service Health", key="svc_load"):
        with render_load_status("Loading service posture", "Service posture ready"):
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
        "Warehouse Availability": ("Review Cost & Contract warehouse efficiency and pressure metrics.", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY grouped by warehouse"),
        "Login/Auth": ("Review Security Monitoring login audit and MFA coverage.", "SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY"),
        "Task Service": ("Review Task Management failed jobs and DAG health.", "SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY"),
        "Data Load": ("Review Pipeline Health load failures and freshness.", "SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY"),
    }
    services["ACTION"] = services["SERVICE"].map(lambda name: action_map.get(name, ("Review source detail.", "ACCOUNT_USAGE"))[0])
    services["PROOF"] = services["SERVICE"].map(lambda name: action_map.get(name, ("Review source detail.", "ACCOUNT_USAGE"))[1])

    risk_services = services[services["SCORE"] < 90] if "SCORE" in services.columns else pd.DataFrame()
    critical_services = services[services["SCORE"] < 60] if "SCORE" in services.columns else pd.DataFrame()
    render_shell_snapshot((
        ("Services", f"{len(services):,}"),
        ("Watch / At Risk", f"{len(risk_services):,}"),
        ("Critical", f"{len(critical_services):,}"),
    ))
    source_text = " | ".join(v for v in data.get("sources", {}).values() if v)
    defer_source_note(metric_confidence_label("composite"), source_text, freshness_note("ACCOUNT_USAGE"))

    if (services["SCORE"] < 95).any() and st.button("Send service findings to Action Queue", key="svc_queue"):
        _queue_service_findings(session, services)

    st.subheader("Service Risk Detail")
    service_risk_view = services.rename(columns={"SCORE": "RISK_VALUE"})
    render_priority_dataframe(
        service_risk_view,
        title="Service risks to work first",
        priority_columns=["SERVICE", "SIGNAL", "ACTION", "PROOF"],
        sort_by=["RISK_VALUE"],
        ascending=True,
        raw_label="All service risk rows",
        height=260,
    )
    download_csv(service_risk_view.drop(columns=["RISK_VALUE"], errors="ignore"), "service_health_risk_detail.csv")

    st.subheader("Warehouse Pressure Detail")
    if wh_df.empty:
        st.info("No warehouse activity found for the selected window.")
    else:
        render_priority_dataframe(
            wh_df,
            title="Warehouse service pressure",
            priority_columns=[
                "WAREHOUSE_NAME", "WAREHOUSE_SIZE", "TOTAL_QUERIES",
                "FAILED_QUERIES", "QUEUED_SEC", "REMOTE_SPILL_GB", "AVG_CACHE_PCT",
            ],
            sort_by=["FAILED_QUERIES", "QUEUED_SEC", "REMOTE_SPILL_GB"],
            ascending=[False, False, False],
            raw_label="All warehouse pressure rows",
            height=360,
        )
        download_csv(wh_df, "service_health_warehouse_pressure.csv")
