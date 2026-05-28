# sections/detailed_diagnosis.py - detailed operational diagnosis for query issues
import streamlit as st

from utils import (
    download_csv,
    get_active_company,
    get_global_filter_clause,
    get_session,
    render_query_drilldown,
    run_query,
    sql_literal,
    upsert_actions,
)


DIAG_MODES = {
    "Execution Time": ("total_elapsed_time", "ELAPSED_SEC", "Slow query execution"),
    "Queued Overload": ("queued_overload_time", "QUEUED_SEC", "Warehouse queue pressure"),
    "Blocked Transactions": ("transaction_blocked_time", "BLOCKED_SEC", "Blocked transaction"),
    "Compilation Time": ("compilation_time", "COMPILE_SEC", "High compilation time"),
    "Remote Spill": ("bytes_spilled_to_remote_storage", "REMOTE_SPILL_GB", "Remote disk spill"),
    "Bytes Scanned": ("bytes_scanned", "GB_SCANNED", "Large table scan"),
}


def _load_diagnosis(session, days: int, mode: str, limit: int):
    company = get_active_company()
    order_col, _, _ = DIAG_MODES[mode]
    filters = get_global_filter_clause(
        date_col="q.start_time",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
    )
    return run_query(f"""
        SELECT
            q.query_id,
            q.user_name,
            q.role_name,
            q.warehouse_name,
            q.warehouse_size,
            q.database_name,
            q.schema_name,
            q.query_type,
            q.execution_status,
            q.error_code,
            q.error_message,
            q.start_time,
            q.total_elapsed_time / 1000 AS elapsed_sec,
            q.compilation_time / 1000 AS compile_sec,
            q.execution_time / 1000 AS exec_sec,
            q.queued_overload_time / 1000 AS queued_sec,
            q.queued_provisioning_time / 1000 AS queued_provisioning_sec,
            q.transaction_blocked_time / 1000 AS blocked_sec,
            q.bytes_scanned / POWER(1024, 3) AS gb_scanned,
            q.bytes_spilled_to_local_storage / POWER(1024, 3) AS local_spill_gb,
            q.bytes_spilled_to_remote_storage / POWER(1024, 3) AS remote_spill_gb,
            q.rows_produced,
            q.partitions_scanned,
            q.partitions_total,
            q.credits_used_cloud_services AS cloud_credits,
            SUBSTR(q.query_text, 1, 4000) AS query_text
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          AND COALESCE(q.{order_col}, 0) > 0
          {filters}
        ORDER BY q.{order_col} DESC
        LIMIT {limit}
    """, ttl_key=f"dd_{company}_{mode}_{days}_{limit}", tier="historical")


def _queue_diagnosis(session, df, mode: str):
    if df is None or df.empty:
        st.info("No diagnosis rows are loaded yet.")
        return
    _, metric_col, finding_name = DIAG_MODES[mode]
    company = get_active_company()
    actions = []
    for _, row in df.head(20).iterrows():
        qid = str(row.get("QUERY_ID", ""))
        wh = str(row.get("WAREHOUSE_NAME", "UNKNOWN"))
        user = str(row.get("USER_NAME", "UNKNOWN"))
        metric_value = float(row.get(metric_col, 0) or 0)
        if not qid:
            continue
        severity = "Critical" if mode in ("Queued Overload", "Remote Spill") and metric_value >= 60 else "High"
        actions.append({
            "Source": "Detailed Diagnosis",
            "Category": "Query Performance",
            "Severity": severity,
            "Entity Type": "Query",
            "Entity": qid,
            "Owner": user,
            "Finding": f"{finding_name}: {metric_col}={metric_value:,.2f} on {wh}.",
            "Action": "Review query text, warehouse pressure, scanned bytes, and operator stats before rerun.",
            "Estimated Monthly Savings": 0,
            "Generated SQL Fix": "-- Use Query Profile and GET_QUERY_OPERATOR_STATS for the selected query.",
            "Proof Query": "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY "
                           f"WHERE query_id = {sql_literal(qid)};",
            "Company": company,
        })
    created = upsert_actions(session, actions)
    st.success(f"Added or refreshed {created} diagnosis actions.")


def render():
    session = get_session()
    st.header("Detailed Diagnosis")
    st.caption("High-signal drilldowns for slow, queued, blocked, spilling, and scan-heavy queries.")

    c1, c2, c3 = st.columns(3)
    with c1:
        days = st.slider("Lookback days", 1, 30, 7, key="dd_days")
    with c2:
        mode = st.selectbox("Diagnosis type", list(DIAG_MODES.keys()), key="dd_mode")
    with c3:
        limit = st.slider("Rows", 50, 500, 200, step=50, key="dd_limit")

    if st.button("Load Diagnosis", key="dd_load"):
        with st.spinner("Loading detailed diagnosis..."):
            try:
                st.session_state["dd_df"] = _load_diagnosis(session, days, mode, limit)
                st.session_state["dd_loaded_mode"] = mode
            except Exception as e:
                st.warning(f"Diagnosis data unavailable in this role/context: {e}")

    df = st.session_state.get("dd_df")
    loaded_mode = st.session_state.get("dd_loaded_mode", mode)
    if df is None:
        return
    if df.empty:
        st.success("No diagnosis findings for the selected filters.")
        return

    _, metric_col, _ = DIAG_MODES.get(loaded_mode, DIAG_MODES["Execution Time"])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Findings", f"{len(df):,}")
    c2.metric("Worst", f"{float(df[metric_col].max() or 0):,.2f}")
    c3.metric("Affected Warehouses", f"{df['WAREHOUSE_NAME'].nunique():,}")
    c4.metric("Affected Users", f"{df['USER_NAME'].nunique():,}")

    if st.button("Send diagnosis findings to Action Queue", key="dd_queue"):
        _queue_diagnosis(session, df, loaded_mode)

    render_query_drilldown(df, key="dd_query", title=f"Query Drill Down - {loaded_mode}")
    download_csv(df, f"detailed_diagnosis_{loaded_mode.lower().replace(' ', '_')}.csv")
