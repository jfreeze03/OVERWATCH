# sections/detailed_diagnosis.py - detailed operational diagnosis for query issues
import streamlit as st

from utils import (
    defer_source_note,
    download_csv,
    format_snowflake_error,
    get_active_company,
    get_global_filter_clause,
    get_session,
    filter_existing_columns,
    mart_object_name,
    render_query_drilldown,
    run_query,
    safe_float,
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


DIAGNOSIS_ROUTES = {
    "Execution Time": (
        "Query workbench",
        "Inspect query text, release timing, warehouse size, and operator stats; compare against historical baseline before tuning.",
    ),
    "Queued Overload": (
        "Warehouse health",
        "Check concurrent load, cluster limits, queued overload time, and auto-suspend/resume settings before resizing.",
    ),
    "Blocked Transactions": (
        "Query workbench",
        "Find blocker sessions and transaction scope; coordinate cancellation or release with the owning team.",
    ),
    "Compilation Time": (
        "Query workbench",
        "Review dynamic SQL, object count, view nesting, and query text complexity before rewriting.",
    ),
    "Remote Spill": (
        "Warehouse health",
        "Inspect operator stats, join strategy, warehouse memory pressure, and scan volume before rerun.",
    ),
    "Bytes Scanned": (
        "Change & drift",
        "Check pruning, clustering/search optimization fit, object growth, and recent schema/data changes.",
    ),
}


def _annotate_diagnosis_routes(df, mode: str):
    if df is None or df.empty:
        return df
    workflow, action = DIAGNOSIS_ROUTES.get(
        mode,
        ("Query workbench", "Open the query drilldown, validate the query profile, and route to the owning workflow."),
    )
    routed = df.copy()
    routed["NEXT_WORKFLOW"] = workflow
    routed["NEXT_ACTION"] = action
    return routed


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
    company_filter = "" if str(company or "").upper() == "ALL" else f"AND q.company = {sql_literal(company, 100)}"
    try:
        mart_table = mart_object_name("FACT_QUERY_DETAIL_RECENT")
        df = run_query(f"""
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
                COALESCE(q.compilation_time, 0) / 1000 AS compile_sec,
                COALESCE(q.execution_time, 0) / 1000 AS exec_sec,
                COALESCE(q.queued_overload_time, 0) / 1000 AS queued_sec,
                COALESCE(q.queued_provisioning_time, 0) / 1000 AS queued_provisioning_sec,
                COALESCE(q.transaction_blocked_time, 0) / 1000 AS blocked_sec,
                COALESCE(q.bytes_scanned, 0) / POWER(1024, 3) AS gb_scanned,
                COALESCE(q.bytes_spilled_to_local_storage, 0) / POWER(1024, 3) AS local_spill_gb,
                COALESCE(q.bytes_spilled_to_remote_storage, 0) / POWER(1024, 3) AS remote_spill_gb,
                COALESCE(q.rows_produced, 0) AS rows_produced,
                COALESCE(q.partitions_scanned, 0) AS partitions_scanned,
                COALESCE(q.partitions_total, 0) AS partitions_total,
                0::FLOAT AS cloud_credits,
                SUBSTR(COALESCE(q.query_text, ''), 1, 4000) AS query_text
            FROM {mart_table} q
            WHERE q.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              AND COALESCE(q.{order_col}, 0) > 0
              {company_filter}
              {filters}
            ORDER BY q.{order_col} DESC
            LIMIT {int(limit)}
        """, ttl_key=f"dd_mart_{company}_{mode}_{days}_{limit}", tier="historical")
        st.session_state["dd_source"] = "OVERWATCH mart: FACT_QUERY_DETAIL_RECENT"
        return df
    except Exception:
        st.session_state["dd_source"] = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"

    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "WAREHOUSE_SIZE", "ERROR_CODE", "ERROR_MESSAGE", "COMPILATION_TIME",
            "EXECUTION_TIME", "QUEUED_OVERLOAD_TIME", "QUEUED_PROVISIONING_TIME",
            "TRANSACTION_BLOCKED_TIME", "BYTES_SCANNED",
            "BYTES_SPILLED_TO_LOCAL_STORAGE", "BYTES_SPILLED_TO_REMOTE_STORAGE",
            "ROWS_PRODUCED", "PARTITIONS_SCANNED", "PARTITIONS_TOTAL",
            "CREDITS_USED_CLOUD_SERVICES", "PERCENTAGE_SCANNED_FROM_CACHE",
        ],
    ))
    if order_col.upper() not in qh_cols and order_col.upper() not in {
        "TOTAL_ELAPSED_TIME",
        "START_TIME",
    }:
        raise ValueError(f"{mode} diagnosis requires {order_col}, which this Snowflake account does not expose.")

    def _num_expr(column: str, alias: str, divisor: str | None = None) -> str:
        if column.upper() not in qh_cols:
            return f"0::FLOAT AS {alias}"
        expr = f"q.{column.lower()}"
        if divisor:
            expr = f"{expr} / {divisor}"
        return f"{expr} AS {alias}"

    warehouse_size_expr = (
        "q.warehouse_size"
        if "WAREHOUSE_SIZE" in qh_cols
        else "NULL::VARCHAR AS warehouse_size"
    )
    error_code_expr = (
        "q.error_code"
        if "ERROR_CODE" in qh_cols
        else "NULL::VARCHAR AS error_code"
    )
    error_message_expr = (
        "q.error_message"
        if "ERROR_MESSAGE" in qh_cols
        else "NULL::VARCHAR AS error_message"
    )
    cloud_expr = (
        "q.credits_used_cloud_services AS cloud_credits"
        if "CREDITS_USED_CLOUD_SERVICES" in qh_cols
        else "0::FLOAT AS cloud_credits"
    )
    return run_query(f"""
        SELECT
            q.query_id,
            q.user_name,
            q.role_name,
            q.warehouse_name,
            {warehouse_size_expr},
            q.database_name,
            q.schema_name,
            q.query_type,
            q.execution_status,
            {error_code_expr},
            {error_message_expr},
            q.start_time,
            q.total_elapsed_time / 1000 AS elapsed_sec,
            {_num_expr("COMPILATION_TIME", "compile_sec", "1000")},
            {_num_expr("EXECUTION_TIME", "exec_sec", "1000")},
            {_num_expr("QUEUED_OVERLOAD_TIME", "queued_sec", "1000")},
            {_num_expr("QUEUED_PROVISIONING_TIME", "queued_provisioning_sec", "1000")},
            {_num_expr("TRANSACTION_BLOCKED_TIME", "blocked_sec", "1000")},
            {_num_expr("BYTES_SCANNED", "gb_scanned", "POWER(1024, 3)")},
            {_num_expr("BYTES_SPILLED_TO_LOCAL_STORAGE", "local_spill_gb", "POWER(1024, 3)")},
            {_num_expr("BYTES_SPILLED_TO_REMOTE_STORAGE", "remote_spill_gb", "POWER(1024, 3)")},
            {_num_expr("ROWS_PRODUCED", "rows_produced")},
            {_num_expr("PARTITIONS_SCANNED", "partitions_scanned")},
            {_num_expr("PARTITIONS_TOTAL", "partitions_total")},
            {cloud_expr},
            SUBSTR(q.query_text, 1, 4000) AS query_text
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          AND COALESCE(q.{order_col}, 0) > 0
          {filters}
        ORDER BY q.{order_col} DESC
        LIMIT {limit}
    """, ttl_key=f"dd_live_{company}_{mode}_{days}_{limit}", tier="historical")


def _queue_diagnosis(session, df, mode: str):
    if df is None or df.empty:
        st.info("No diagnosis rows are loaded yet.")
        return
    _, metric_col, finding_name = DIAG_MODES[mode]
    next_workflow, next_action = DIAGNOSIS_ROUTES.get(
        mode,
        ("Query workbench", "Open the query drilldown, validate the query profile, and route to the owning workflow."),
    )
    company = get_active_company()
    actions = []
    for _, row in df.head(20).iterrows():
        qid = str(row.get("QUERY_ID", ""))
        wh = str(row.get("WAREHOUSE_NAME", "UNKNOWN"))
        user = str(row.get("USER_NAME", "UNKNOWN"))
        metric_value = safe_float(row.get(metric_col, 0))
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
            "Action": f"{next_workflow}: {next_action}",
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
    focus_query_id = str(st.session_state.get("dd_focus_query_id") or "")
    if focus_query_id:
        st.info(f"Routed from Query Watch Floor for query `{focus_query_id}`. Load diagnosis to compare it against the highest-signal rows in this mode.")

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
                st.session_state["dd_df"] = _annotate_diagnosis_routes(_load_diagnosis(session, days, mode, limit), mode)
                st.session_state["dd_loaded_mode"] = mode
            except Exception as e:
                st.warning(f"Diagnosis data unavailable: {format_snowflake_error(e)}")

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
    c2.metric("Worst", f"{safe_float(df[metric_col].max()):,.2f}")
    c3.metric("Affected Warehouses", f"{df['WAREHOUSE_NAME'].nunique():,}")
    c4.metric("Affected Users", f"{df['USER_NAME'].nunique():,}")
    defer_source_note(st.session_state.get("dd_source", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"))

    if st.button("Send diagnosis findings to Action Queue", key="dd_queue"):
        _queue_diagnosis(session, df, loaded_mode)

    render_query_drilldown(df, key="dd_query", title=f"Query Drill Down - {loaded_mode}")
    download_csv(df, f"detailed_diagnosis_{loaded_mode.lower().replace(' ', '_')}.csv")
