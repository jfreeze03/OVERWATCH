# sections/recommendations.py - recommendations, persistent action queue, and anomalies
from html import escape as html_escape

import pandas as pd
import streamlit as st

from config import DEFAULTS, THRESHOLDS
from sections.shell_helpers import _clean_display_text, render_escaped_bold_text, render_shell_snapshot
from utils import (
    build_clustering_cost_sql,
    build_safe_verification_query,
    credits_to_dollars,
    day_window_selectbox,
    defer_source_note,
    download_csv,
    filter_existing_columns,
    format_snowflake_error,
    format_credits,
    get_db_filter_clause,
    get_storage_cost_per_tb,
    get_global_filter_clause,
    get_session,
    get_wh_filter_clause,
    load_shared_recommendation_failed_tasks,
    load_shared_recommendation_idle_warehouses,
    load_shared_recommendation_query_failures,
    load_shared_recommendation_spill_warehouses,
    load_action_queue,
    make_action_id,
    metric_confidence_label,
    freshness_note,
    run_query,
    run_query_or_raise,
    safe_float,
    safe_identifier,
    sql_literal,
    update_action_status_with_evidence,
    upsert_actions,
    summarize_verification_frame,
    verification_query_safety_issues,
)
from utils.recommendation_intelligence import build_automation_readiness_board, harden_recommendation
from utils.workflows import clean_operator_display_text, render_load_status, render_priority_dataframe, render_workflow_selector


RECOMMENDATION_PANES = (
    "Recommendations",
    "Queue Health",
    "Action Queue",
    "Anomaly Log",
)


def _plain_html(value: object) -> str:
    """Render generated object/action text literally inside small HTML fragments."""
    return html_escape(_clean_display_text(value), quote=False)


def _active_company() -> str:
    return st.session_state.get("active_company", "ALFA")


def _recommendation_frame(recs: list[dict]) -> pd.DataFrame:
    if not recs:
        return pd.DataFrame()
    df = pd.DataFrame([harden_recommendation(rec) for rec in recs])
    df["Action ID"] = df.apply(
        lambda r: make_action_id(r["Category"], r["Entity"], r["Finding"]),
        axis=1,
    )
    df["Status"] = "New"
    sort_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    df["_sort"] = df["Severity"].map(sort_order).fillna(9)
    return df.sort_values(["_sort", "Estimated Monthly Savings"], ascending=[True, False]).drop(columns=["_sort"])


def _row_text(row, column: str, default: str = "") -> str:
    value = row.get(column, default)
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    return str(value)


def _float_text_or_none(value: str):
    text = str(value or "").strip()
    return None if not text else safe_float(text)


def _idle_warehouse_verification_sql(warehouse_name: str, days: int = 7) -> str:
    wh = sql_literal(warehouse_name, 300)
    return f"""-- Idle warehouse post-fix telemetry
WITH metering AS (
    SELECT DATE_TRUNC('hour', start_time) AS usage_hour,
           warehouse_name,
           SUM(COALESCE(credits_used, 0)) AS credits_used
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
    WHERE warehouse_name = {wh}
      AND start_time >= DATEADD('day', -{max(1, int(days or 7))}, CURRENT_TIMESTAMP())
    GROUP BY usage_hour, warehouse_name
),
queries AS (
    SELECT DATE_TRUNC('hour', start_time) AS usage_hour,
           warehouse_name,
           COUNT(*) AS query_count
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE warehouse_name = {wh}
      AND start_time >= DATEADD('day', -{max(1, int(days or 7))}, CURRENT_TIMESTAMP())
    GROUP BY usage_hour, warehouse_name
)
SELECT m.warehouse_name,
       COUNT_IF(COALESCE(q.query_count, 0) = 0) AS idle_hours,
       ROUND(SUM(IFF(COALESCE(q.query_count, 0) = 0, m.credits_used, 0)), 4) AS idle_credits,
       ROUND(SUM(m.credits_used), 4) AS total_credits
FROM metering m
LEFT JOIN queries q
  ON m.warehouse_name = q.warehouse_name
 AND m.usage_hour = q.usage_hour
GROUP BY m.warehouse_name
ORDER BY idle_credits DESC
LIMIT 50;
"""


def _remote_spill_verification_sql(warehouse_name: str, days: int = 7) -> str:
    wh = sql_literal(warehouse_name, 300)
    return f"""-- Remote spill post-fix telemetry
SELECT warehouse_name,
       COUNT(*) AS spilling_queries,
       ROUND(SUM(COALESCE(bytes_spilled_to_remote_storage, 0)) / POWER(1024, 3), 2) AS remote_spill_gb,
       MAX(start_time) AS last_spill_time
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE warehouse_name = {wh}
  AND start_time >= DATEADD('day', -{max(1, int(days or 7))}, CURRENT_TIMESTAMP())
  AND COALESCE(bytes_spilled_to_remote_storage, 0) > 0
GROUP BY warehouse_name
ORDER BY remote_spill_gb DESC
LIMIT 50;
"""


def _task_failure_verification_sql(task_name: str, days: int = 7) -> str:
    task = sql_literal(task_name, 500)
    return f"""-- Task failure post-fix telemetry
SELECT name,
       database_name,
       schema_name,
       state,
       COUNT(*) AS runs,
       COUNT_IF(state = 'FAILED') AS failed_runs,
       MAX(scheduled_time) AS latest_scheduled_time,
       MAX(completed_time) AS latest_completed_time
FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
WHERE scheduled_time >= DATEADD('day', -{max(1, int(days or 7))}, CURRENT_TIMESTAMP())
  AND name = {task}
GROUP BY name, database_name, schema_name, state
ORDER BY failed_runs DESC, latest_scheduled_time DESC
LIMIT 50;
"""


def _query_failure_verification_sql(warehouse_name: str, days: int = 7) -> str:
    wh = sql_literal(warehouse_name, 300)
    return f"""-- Query failure post-fix telemetry
SELECT warehouse_name,
       error_code,
       COUNT(*) AS failures,
       MAX(start_time) AS latest_failure_time,
       SUBSTR(MAX(error_message), 1, 1000) AS sample_error_message
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE warehouse_name = {wh}
  AND start_time >= DATEADD('day', -{max(1, int(days or 7))}, CURRENT_TIMESTAMP())
  AND UPPER(execution_status) = 'FAILED_WITH_ERROR'
GROUP BY warehouse_name, error_code
ORDER BY failures DESC
LIMIT 50;
"""


def _storage_retention_verification_sql(database_name: str) -> str:
    db = sql_literal(database_name, 300)
    return f"""-- Storage retention telemetry
SELECT table_catalog AS database_name,
       ROUND(SUM(COALESCE(active_bytes, 0)) / POWER(1024, 4), 3) AS active_tb,
       ROUND(SUM(COALESCE(time_travel_bytes, 0)) / POWER(1024, 4), 3) AS time_travel_tb,
       ROUND(SUM(COALESCE(failsafe_bytes, 0)) / POWER(1024, 4), 3) AS failsafe_tb
FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS
WHERE deleted = FALSE
  AND table_catalog = {db}
GROUP BY table_catalog
ORDER BY time_travel_tb DESC;
"""


def _clustering_verification_sql(table_name: str, days: int = 7) -> str:
    table = sql_literal(table_name, 1000)
    return f"""-- Automatic clustering cost telemetry
SELECT database_name || '.' || schema_name || '.' || table_name AS table_name,
       ROUND(SUM(COALESCE(credits_used, 0)), 4) AS clustering_credits,
       ROUND(SUM(COALESCE(num_bytes_reclustered, 0)) / POWER(1024, 4), 4) AS tb_reclustered,
       SUM(COALESCE(num_rows_reclustered, 0)) AS rows_reclustered,
       MAX(start_time) AS latest_cluster_event
FROM SNOWFLAKE.ACCOUNT_USAGE.AUTOMATIC_CLUSTERING_HISTORY
WHERE start_time >= DATEADD('day', -{max(1, int(days or 7))}, CURRENT_TIMESTAMP())
  AND database_name || '.' || schema_name || '.' || table_name = {table}
GROUP BY database_name, schema_name, table_name
ORDER BY clustering_credits DESC;
"""


def _repeated_query_verification_sql(query_hash: str, hash_column: str, days: int = 7) -> str:
    qh = sql_literal(query_hash, 300)
    column = safe_identifier(hash_column)
    return f"""-- Repeated query pattern telemetry
SELECT {column} AS query_hash,
       COUNT(*) AS runs,
       COUNT(DISTINCT user_name) AS users,
       ROUND(SUM(COALESCE(total_elapsed_time, 0)) / 1000 / 3600, 2) AS total_exec_hours,
       ROUND(SUM(COALESCE(bytes_scanned, 0)) / POWER(1024, 4), 2) AS tb_scanned,
       MAX(start_time) AS latest_run,
       SUBSTR(MAX(query_text), 1, 1000) AS sample_query
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD('day', -{max(1, int(days or 7))}, CURRENT_TIMESTAMP())
  AND {column} = {qh}
GROUP BY {column}
ORDER BY runs DESC;
"""


def _automation_playbook_frame() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "AUTOMATION_LANE": "Ready",
            "WHAT_IT_MEANS": "Safe SQL shape, escalation route, rollback boundary, and telemetry are present.",
            "DBA_ACTION": "Use the guarded admin workflow when action is still needed.",
        },
        {
            "AUTOMATION_LANE": "Telemetry Pending",
            "WHAT_IT_MEANS": "The action looks automatable, but fresh telemetry has not confirmed the state.",
            "DBA_ACTION": "Wait for the next telemetry refresh before action.",
        },
        {
            "AUTOMATION_LANE": "Needs Data",
            "WHAT_IT_MEANS": "The action lacks enough telemetry or routing context.",
            "DBA_ACTION": "Load the missing data before routing.",
        },
        {
            "AUTOMATION_LANE": "DBA Review",
            "WHAT_IT_MEANS": "The action touches security, task execution, failover, clustering telemetry, or unsafe SQL.",
            "DBA_ACTION": "Keep it in the guarded DBA workflow.",
        },
        {
            "AUTOMATION_LANE": "Resolved Candidate",
            "WHAT_IT_MEANS": "The action is already closed in telemetry.",
            "DBA_ACTION": "Keep it out of active work queues.",
        },
    ])


def _render_automation_health(session):
    st.subheader("Queue Health")
    st.caption("DBA-safe queue lanes for recommendations and action queue items.")
    c_load, c_hint = st.columns([1, 3])
    with c_load:
        if st.button("Load Action Queue", key="automation_queue_load"):
            with render_load_status("Loading action queue", "Action queue ready"):
                try:
                    st.session_state["rec_action_queue"] = load_action_queue(session)
                except Exception as e:
                    st.info(f"The action queue is not available in this environment yet. Ask the DBA on-call to enable it, then retry. ({format_snowflake_error(e)})")
                    st.session_state["rec_action_queue"] = pd.DataFrame()
    with c_hint:
        st.caption("Generate recommendations and/or load the action queue, then use this board to decide what can be safely packaged.")

    recs = st.session_state.get("rec_recommendations", [])
    queue = st.session_state.get("rec_action_queue")
    board = build_automation_readiness_board(recs, queue if isinstance(queue, pd.DataFrame) else None)
    st.session_state["rec_automation_board"] = board

    if board.empty:
        st.info("No queue candidates loaded. Generate recommendations or load the action queue first.")
        playbook = _automation_playbook_frame().rename(columns={
            "AUTOMATION_LANE": "QUEUE_LANE",
        })
        render_priority_dataframe(
            playbook,
            title="Queue lane definitions",
            priority_columns=["QUEUE_LANE", "WHAT_IT_MEANS", "DBA_ACTION"],
            sort_by=["QUEUE_LANE"],
            ascending=True,
            raw_label="All queue lane definitions",
            height=260,
        )
        return

    ready = int((board["AUTOMATION_LANE"] == "Ready").sum())
    telemetry_pending = int((board["AUTOMATION_LANE"] == "Telemetry Pending").sum())
    needs_data = int((board["AUTOMATION_LANE"] == "Needs Data").sum())
    dba_review = int((board["AUTOMATION_LANE"] == "DBA Review").sum())
    auto_close = int((board["AUTOMATION_LANE"] == "Resolved Candidate").sum())
    render_shell_snapshot((
        ("Candidates", f"{len(board):,}"),
        ("Guided Ready", f"{ready:,}"),
        ("Telemetry Pending", f"{telemetry_pending:,}"),
        ("Needs Data", f"{needs_data:,}"),
        ("DBA Review", f"{dba_review:,}"),
        ("Resolved", f"{auto_close:,}"),
    ))

    first = board.iloc[0]
    st.warning(
        f"Queue first move: {first['AUTOMATION_LANE']} for {first['ENTITY']}. "
        f"Blockers: {first['BLOCKERS']}. Next: {first['SAFE_AUTOMATION_STEP']}"
    )
    display_board = board.rename(columns={
        "AUTOMATION_LANE": "QUEUE_LANE",
        "AUTOMATION_MODE": "QUEUE_MODE",
        "APPROVAL_STATE": "REVIEW_STATE",
        "SAFE_AUTOMATION_STEP": "SAFE_NEXT_STEP",
        "APPROVAL_GATE": "REVIEW_GATE",
        "EVIDENCE_PACKAGE": "TELEMETRY_PACKAGE",
        "PROOF_REQUIRED": "TELEMETRY_REQUIRED",
    }).drop(columns=["SAFE_GUIDED_SQL", "STATE_CHANGING_SQL"], errors="ignore")
    render_priority_dataframe(
        display_board,
        title="Queue health board",
        priority_columns=[
            "QUEUE_LANE", "SEVERITY", "CATEGORY", "ENTITY",
            "DECISION", "BLOCKERS", "REVIEW_STATE", "SAFE_NEXT_STEP", "REVIEW_GATE",
            "TELEMETRY_PACKAGE", "VERIFY_NEXT", "EXECUTION_BOUNDARY", "CLOSURE_RULE",
            "TELEMETRY_REQUIRED", "DO_NOT_DO",
        ],
        sort_by=["QUEUE_LANE", "SEVERITY"],
        ascending=[True, True],
        raw_label="All queue health rows",
        height=440,
    )
    download_csv(display_board, "queue_health_board.csv")

    with st.expander("Queue lane definitions", expanded=False):
        playbook = _automation_playbook_frame().rename(columns={
            "AUTOMATION_LANE": "QUEUE_LANE",
        })
        render_priority_dataframe(
            playbook,
            title="Queue playbook",
            priority_columns=["QUEUE_LANE", "WHAT_IT_MEANS", "DBA_ACTION"],
            sort_by=["QUEUE_LANE"],
            ascending=True,
            raw_label="All queue playbook rows",
            height=260,
        )


def _render_queue(session):
    st.subheader("Persistent Action Queue")
    st.caption("Route, status, savings, review path, and telemetry state for every actionable finding.")
    st.info("Action queue persistence is owned by the DBA platform team for this environment.")

    if st.button("Load Action Queue", key="queue_load"):
        with render_load_status("Loading action queue", "Action queue ready"):
            try:
                st.session_state["rec_action_queue"] = load_action_queue(session)
            except Exception as e:
                st.info(f"The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry. ({format_snowflake_error(e)})")
                st.session_state["rec_action_queue"] = pd.DataFrame()

    df_queue = st.session_state.get("rec_action_queue")
    if df_queue is None:
        return
    if df_queue.empty:
        st.info("No persistent actions found yet.")
        return

    open_mask = ~df_queue["STATUS"].isin(["Fixed", "Ignored"])
    high_mask = df_queue["SEVERITY"].isin(["Critical", "High"]) & open_mask
    verification_status = (
        df_queue["VERIFICATION_STATUS"].fillna("").astype(str)
        if "VERIFICATION_STATUS" in df_queue.columns
        else pd.Series([""] * len(df_queue), index=df_queue.index)
    )
    fixed_mask = df_queue["STATUS"] == "Fixed"
    closed_mask = fixed_mask
    due_state = (
        df_queue["DUE_STATE"].fillna("").astype(str)
        if "DUE_STATE" in df_queue.columns
        else pd.Series([""] * len(df_queue), index=df_queue.index)
    )
    evidence_gap = (
        df_queue["EVIDENCE_GAP"].fillna("").astype(str)
        if "EVIDENCE_GAP" in df_queue.columns
        else pd.Series([""] * len(df_queue), index=df_queue.index)
    )
    evidence_gap_mask = ~evidence_gap.isin(["Ready to work", "Telemetry closure", "Ignored with reason"])
    overdue_mask = open_mask & (due_state == "Overdue")
    render_shell_snapshot((
        ("Open", f"{int(open_mask.sum()):,}"),
        ("High / Critical", f"{int(high_mask.sum()):,}"),
        ("Overdue", f"{int(overdue_mask.sum()):,}"),
        ("Control Gaps", f"{int(evidence_gap_mask.sum()):,}"),
        ("Closed", f"{int(closed_mask.sum()):,}"),
        ("Savings Queue", f"${float(df_queue['EST_MONTHLY_SAVINGS'].fillna(0).sum()):,.0f}"),
    ))

    status_filter = st.selectbox(
        "Status filter",
        ["All", "New", "Acknowledged", "In Progress", "Fixed", "Ignored"],
        key="queue_status_filter",
    )
    show_df = df_queue if status_filter == "All" else df_queue[df_queue["STATUS"] == status_filter]
    category_options = ["All"] + sorted(show_df["CATEGORY"].dropna().astype(str).unique().tolist())
    category_filter = st.selectbox("Category filter", category_options, key="queue_category_filter")
    if category_filter != "All":
        show_df = show_df[show_df["CATEGORY"].astype(str) == category_filter]
    render_priority_dataframe(
        show_df,
        title="Action queue items to work first",
        priority_columns=[
            "SEVERITY", "STATUS", "DUE_STATE", "DUE_DATE", "EVIDENCE_GAP",
            "CATEGORY", "ENVIRONMENT", "ENTITY_NAME",
            "FINDING", "OWNER", "TICKET_ID", "APPROVER",
            "EST_MONTHLY_SAVINGS", "MEASURED_DELTA", "NEXT_ACTION", "UPDATED_AT",
        ],
        sort_by=["QUEUE_PRIORITY", "EST_MONTHLY_SAVINGS", "UPDATED_AT"],
        ascending=[True, False, False],
        raw_label="All action queue rows",
        height=360,
    )
    download_csv(show_df, "overwatch_action_queue.csv")

    if show_df.empty:
        return

    selected = st.selectbox("Inspect action", show_df["ACTION_ID"].astype(str).tolist(), key="queue_action_select")
    row = show_df[show_df["ACTION_ID"].astype(str) == selected].iloc[0]
    st.html(
        "<div style='font-size:1rem; line-height:1.45; margin:0 0 .35rem 0;'>"
        f"<strong>{_plain_html(row.get('ENTITY_NAME', ''))}</strong> - {_plain_html(row.get('FINDING', ''))}"
        "</div>"
    )
    st.caption(_clean_display_text(row.get("NEXT_ACTION", "Review the route and current telemetry before action.")))
    render_shell_snapshot((
        ("Status", _row_text(row, "STATUS") or "New"),
        ("Severity", _row_text(row, "SEVERITY") or "Medium"),
        ("Due", _row_text(row, "DUE_STATE") or _row_text(row, "DUE_DATE") or "Open"),
        ("Savings", f"${safe_float(row.get('EST_MONTHLY_SAVINGS')):,.0f}"),
    ))
    detail_cols = [
        column for column in [
            "CATEGORY", "ENVIRONMENT", "ENTITY_TYPE", "ENTITY_NAME",
            "FINDING", "NEXT_ACTION", "TICKET_ID", "UPDATED_AT",
        ]
        if column in row.index
    ]
    if detail_cols:
        render_priority_dataframe(
            pd.DataFrame([row[detail_cols].to_dict()]),
            title="Selected action context",
            priority_columns=detail_cols,
            max_rows=1,
            height=120,
        )


def render():
    session = get_session()
    credit_price = st.session_state.get("credit_price", DEFAULTS["credit_price"])

    active_view = render_workflow_selector(
        "Recommendation view",
        "recommendations_active_view",
        RECOMMENDATION_PANES,
        columns=4,
        show_label=True,
    )

    if active_view == "Recommendations":
        st.subheader("Automated Recommendations Feed")
        st.caption("Prioritized findings that can be saved into a persistent route/status queue.")

        if st.button("Generate Recommendations", key="recs_gen"):
            recs = []
            source_notes = []
            company = _active_company()
            query_filters = get_global_filter_clause(
                date_col="start_time",
                wh_col="warehouse_name",
                user_col="user_name",
                role_col="role_name",
                db_col="database_name",
            )

            try:
                idle_result = load_shared_recommendation_idle_warehouses(
                    company,
                    days=7,
                    min_idle_credits=1.0,
                    section="Recommendations",
                )
                df_idle = idle_result.data
                source_notes.append(f"Idle warehouses: {idle_result.source}")
                for _, row in df_idle.iterrows():
                    wh_name = str(row["WAREHOUSE_NAME"])
                    wh_ident = safe_identifier(wh_name)
                    verification_sql = _idle_warehouse_verification_sql(wh_name)
                    monthly_savings = credits_to_dollars(float(row["IDLE_CREDITS"] or 0) / 7 * 30, credit_price)
                    recs.append({
                        "Source": "Idle warehouse detector",
                        "Severity": "High",
                        "Category": "Cost Control",
                        "Entity Type": "Warehouse",
                        "Entity": wh_name,
                        "Owner": "DBA",
                        "Finding": f"{wh_name} idle {int(row['IDLE_HOURS'])}h, wasting {format_credits(row['IDLE_CREDITS'])}",
                        "Action": f"Reduce AUTO_SUSPEND to <= {THRESHOLDS['idle_warehouse_minutes']} minutes",
                        "Idle Hours": int(row["IDLE_HOURS"]),
                        "Estimated Monthly Savings": round(monthly_savings, 2),
                        "Generated SQL Fix": f"ALTER WAREHOUSE {wh_ident} SET AUTO_SUSPEND = {THRESHOLDS['idle_warehouse_minutes'] * 60};",
                        "Proof Query": verification_sql,
                        "Verification Query": verification_sql,
                        "Baseline Value": round(safe_float(row.get("IDLE_CREDITS")), 4),
                        "Current Value": round(safe_float(row.get("IDLE_CREDITS")), 4),
                        "Measured Delta": 0.0,
                        "Company": company,
                    })
            except Exception:
                pass

            try:
                spill_result = load_shared_recommendation_spill_warehouses(
                    session,
                    company,
                    days=7,
                    min_remote_gb=5.0,
                    section="Recommendations",
                )
                df_spill = spill_result.data
                source_notes.append(f"Remote spill: {spill_result.source}")
                for _, row in df_spill.iterrows():
                    wh_name = str(row["WAREHOUSE_NAME"])
                    verification_sql = _remote_spill_verification_sql(wh_name)
                    recs.append({
                        "Source": "Remote spill detector",
                        "Severity": "Medium",
                        "Category": "Performance",
                        "Entity Type": "Warehouse",
                        "Entity": wh_name,
                        "Owner": "DBA",
                        "Finding": f"{wh_name} ({row['WAREHOUSE_SIZE']}): {row['REMOTE_GB']:.1f} GB remote spill",
                        "Action": "Review query profile; upsize or split workload if spill persists.",
                        "Remote Spill GB": round(safe_float(row.get("REMOTE_GB")), 4),
                        "Estimated Monthly Savings": 0.0,
                        "Generated SQL Fix": f"-- Review memory pressure on {wh_name}; consider ALTER WAREHOUSE {safe_identifier(wh_name)} SET WAREHOUSE_SIZE = '<NEXT_SIZE>';",
                        "Proof Query": verification_sql,
                        "Verification Query": verification_sql,
                        "Current Value": round(safe_float(row.get("REMOTE_GB")), 4),
                        "Company": company,
                    })
            except Exception:
                pass

            try:
                failed_task_result = load_shared_recommendation_failed_tasks(
                    session,
                    company,
                    days=7,
                    min_failures=3,
                    section="Recommendations",
                )
                df_ftask = failed_task_result.data
                source_notes.append(f"Failed tasks: {failed_task_result.source}")
                for _, row in df_ftask.iterrows():
                    task_name = str(row["TASK_NAME"])
                    verification_sql = _task_failure_verification_sql(task_name)
                    recs.append({
                        "Source": "Task failure detector",
                        "Severity": "High",
                        "Category": "Task & Procedure Reliability",
                        "Entity Type": "Task",
                        "Entity": task_name,
                        "Owner": "Data Engineering",
                        "Finding": f"Task {task_name} failed {int(row['FAILURES'])} times in 7 days",
                        "Action": "Review task error logs in Task Management and fix root cause.",
                        "Failures": int(row["FAILURES"]),
                        "Estimated Monthly Savings": 0.0,
                        "Generated SQL Fix": f"-- Inspect task: {task_name}\n-- EXECUTE TASK <database>.<schema>.{safe_identifier(task_name)};",
                        "Proof Query": verification_sql,
                        "Verification Query": verification_sql,
                        "Baseline Value": 0.0,
                        "Current Value": round(safe_float(row.get("FAILURES")), 4),
                        "Measured Delta": round(safe_float(row.get("FAILURES")), 4),
                        "Company": company,
                    })
            except Exception:
                pass

            try:
                query_failure_result = load_shared_recommendation_query_failures(
                    company,
                    days=7,
                    min_failures=THRESHOLDS["error_rate_high"],
                    section="Recommendations",
                )
                df_err = query_failure_result.data
                source_notes.append(f"Query failures: {query_failure_result.source}")
                for _, row in df_err.iterrows():
                    wh_name = str(row["WAREHOUSE_NAME"])
                    verification_sql = _query_failure_verification_sql(wh_name)
                    recs.append({
                        "Source": "Query failure detector",
                        "Severity": "Medium",
                        "Category": "Reliability",
                        "Entity Type": "Warehouse",
                        "Entity": wh_name,
                        "Owner": "DBA",
                        "Finding": f"{wh_name}: {int(row['FAILURES'])} failed queries in 7 days",
                        "Action": "Investigate error codes in Query Analysis.",
                        "Failures": int(row["FAILURES"]),
                        "Estimated Monthly Savings": 0.0,
                        "Generated SQL Fix": "-- No safe automatic SQL fix. Review failed query texts and owners.",
                        "Proof Query": verification_sql,
                        "Verification Query": verification_sql,
                        "Current Value": round(safe_float(row.get("FAILURES")), 4),
                        "Company": company,
                    })
            except Exception:
                pass

            try:
                storage_rate = get_storage_cost_per_tb()
                df_storage = run_query(f"""
                    SELECT table_catalog AS database_name,
                           ROUND(SUM(COALESCE(active_bytes, 0)) / POWER(1024, 4), 3) AS active_tb,
                           ROUND(SUM(COALESCE(time_travel_bytes, 0)) / POWER(1024, 4), 3) AS time_travel_tb,
                           ROUND(SUM(COALESCE(failsafe_bytes, 0)) / POWER(1024, 4), 3) AS failsafe_tb
                    FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS
                    WHERE deleted = FALSE
                      AND table_catalog IS NOT NULL
                      {get_db_filter_clause("table_catalog", company)}
                    GROUP BY table_catalog
                    HAVING time_travel_tb >= 0.25
                       AND time_travel_tb >= active_tb * 0.25
                    ORDER BY time_travel_tb DESC
                    LIMIT 10
                """, ttl_key=f"rec_storage_retention_{company}", tier="historical")
                source_notes.append("Storage retention: live ACCOUNT_USAGE.TABLE_STORAGE_METRICS")
                for _, row in df_storage.iterrows():
                    db_name = str(row["DATABASE_NAME"])
                    active_tb = safe_float(row.get("ACTIVE_TB"))
                    time_travel_tb = safe_float(row.get("TIME_TRAVEL_TB"))
                    estimated_storage = time_travel_tb * storage_rate
                    verification_sql = _storage_retention_verification_sql(db_name)
                    recs.append({
                        "Source": "Time travel retention detector",
                        "Severity": "High" if estimated_storage >= 1000 else "Medium",
                        "Category": "Storage Retention",
                        "Entity Type": "Database",
                        "Entity": db_name,
                        "Owner": "DBA",
                        "Finding": (
                            f"{db_name}: {time_travel_tb:.2f} TB time-travel storage "
                            f"vs {active_tb:.2f} TB active"
                        ),
                        "Action": "Confirm recovery, cloning, and compliance requirements before changing retention.",
                        "Estimated Monthly Savings": round(estimated_storage, 2),
                        "Generated SQL Fix": (
                            f"-- Review only for {db_name}.\n"
                            "-- If approved, change DATA_RETENTION_TIME_IN_DAYS at the narrowest safe scope."
                        ),
                        "Proof Query": verification_sql,
                        "Verification Query": verification_sql,
                        "Current Value": round(time_travel_tb, 4),
                        "TIME_TRAVEL_TB": round(time_travel_tb, 4),
                        "ACTIVE_TB": round(active_tb, 4),
                        "Company": company,
                    })
            except Exception:
                pass

            try:
                df_cluster = run_query(
                    build_clustering_cost_sql(
                        7,
                        company=company,
                        credit_price=credit_price,
                        top=10,
                    ),
                    ttl_key=f"rec_clustering_cost_{company}_{credit_price}",
                    tier="historical",
                )
                source_notes.append("Clustering: live ACCOUNT_USAGE.AUTOMATIC_CLUSTERING_HISTORY")
                for _, row in df_cluster.iterrows():
                    table_name = str(row["TABLE_NAME"])
                    clustering_cost = safe_float(row.get("CLUSTERING_COST_USD"))
                    if clustering_cost < 25:
                        continue
                    reclustered_tb = safe_float(row.get("TB_RECLUSTERED"))
                    verification_sql = _clustering_verification_sql(table_name)
                    recs.append({
                        "Source": "Clustering cost detector",
                        "Severity": "High" if clustering_cost >= 500 else "Medium",
                        "Category": "Clustering",
                        "Entity Type": "Table",
                        "Entity": table_name,
                        "Owner": "DBA",
                        "Finding": (
                            f"{table_name}: ${clustering_cost:,.0f} automatic clustering cost, "
                            f"{reclustered_tb:.2f} TB reclustered"
                        ),
                        "Action": "Review clustering depth, DML churn, pruning benefit, and query demand before changing clustering.",
                        "Estimated Monthly Savings": 0.0,
                        "Generated SQL Fix": (
                            "-- Review only. Do not suspend reclustering until pruning benefit and DML churn are confirmed."
                        ),
                        "Proof Query": verification_sql,
                        "Verification Query": verification_sql,
                        "Current Value": round(clustering_cost, 2),
                        "CLUSTERING_COST_USD": round(clustering_cost, 2),
                        "TB_RECLUSTERED": round(reclustered_tb, 4),
                        "Company": company,
                    })
            except Exception:
                pass

            try:
                qh_columns = set(filter_existing_columns(
                    session,
                    "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                    ["QUERY_PARAMETERIZED_HASH", "QUERY_HASH"],
                ))
                hash_column = (
                    "QUERY_PARAMETERIZED_HASH"
                    if "QUERY_PARAMETERIZED_HASH" in qh_columns
                    else "QUERY_HASH" if "QUERY_HASH" in qh_columns else ""
                )
                if not hash_column:
                    raise ValueError("No query hash column is exposed in QUERY_HISTORY.")
                hash_ident = safe_identifier(hash_column)
                df_repeated = run_query(f"""
                    SELECT {hash_ident} AS query_hash,
                           COUNT(*) AS runs,
                           COUNT(DISTINCT user_name) AS user_count,
                           ROUND(SUM(COALESCE(total_elapsed_time, 0)) / 1000 / 3600, 2) AS total_exec_hours,
                           ROUND(SUM(COALESCE(bytes_scanned, 0)) / POWER(1024, 4), 2) AS tb_scanned,
                           SUBSTR(MAX(query_text), 1, 500) AS sample_query
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
                      AND warehouse_name IS NOT NULL
                      AND UPPER(COALESCE(execution_status, '')) = 'SUCCESS'
                      AND {hash_ident} IS NOT NULL
                      {query_filters}
                    GROUP BY {hash_ident}
                    HAVING runs >= 50 OR total_exec_hours >= 2
                    ORDER BY total_exec_hours DESC, runs DESC
                    LIMIT 10
                """, ttl_key=f"rec_repeated_queries_{company}_{hash_column}", tier="historical")
                source_notes.append("Repeated query patterns: live ACCOUNT_USAGE.QUERY_HISTORY")
                for _, row in df_repeated.iterrows():
                    query_hash = str(row["QUERY_HASH"])
                    runs = int(safe_float(row.get("RUNS")))
                    total_hours = safe_float(row.get("TOTAL_EXEC_HOURS"))
                    scanned_tb = safe_float(row.get("TB_SCANNED"))
                    verification_sql = _repeated_query_verification_sql(query_hash, hash_column)
                    recs.append({
                        "Source": "Repeated query detector",
                        "Severity": "Medium",
                        "Category": "Query Optimization",
                        "Entity Type": "Query Pattern",
                        "Entity": query_hash[:120],
                        "Owner": "Query reviewer / DBA lead",
                        "Finding": (
                            f"{runs:,} executions, {total_hours:.2f} execution hours, "
                            f"{scanned_tb:.2f} TB scanned"
                        ),
                        "Action": "Confirm reuse, freshness, and owner before materialization or rewrite.",
                        "Estimated Monthly Savings": 0.0,
                        "Generated SQL Fix": (
                            "-- No automatic SQL fix. Review sample query, ownership, freshness, and result reuse."
                        ),
                        "Proof Query": verification_sql,
                        "Verification Query": verification_sql,
                        "RUNS": runs,
                        "TOTAL_EXEC_HOURS": round(total_hours, 2),
                        "TB_SCANNED": round(scanned_tb, 2),
                        "Current Value": round(total_hours, 2),
                        "Company": company,
                    })
            except Exception:
                pass

            st.session_state["rec_recommendations"] = recs
            st.session_state["rec_recommendation_sources"] = source_notes

        recs = st.session_state.get("rec_recommendations", [])
        if recs:
            df_recs = _recommendation_frame(recs)
            high = df_recs[df_recs["Severity"].isin(["Critical", "High"])]
            monthly = float(df_recs["Estimated Monthly Savings"].sum())
            telemetry_ready = int(df_recs["Proof Query"].astype(str).str.strip().ne("").sum()) if "Proof Query" in df_recs.columns else 0
            decisive_pct = telemetry_ready / max(len(df_recs), 1) * 100
            render_shell_snapshot((
                ("High / Critical", f"{len(high):,}"),
                ("Open Findings", f"{len(df_recs):,}"),
                ("Est. Monthly Savings", f"${monthly:,.0f}"),
                ("Telemetry Ready", f"{telemetry_ready:,} ({decisive_pct:.0f}%)"),
                ("DBA Routes", f"{len(df_recs):,}"),
            ))
            defer_source_note(
                metric_confidence_label("estimated"),
                freshness_note("ACCOUNT_USAGE"),
                "Savings are directional until post-period telemetry confirms the action outcome.",
            )
            top_rec = df_recs.iloc[0]
            st.warning(
                f"Work first: {_clean_display_text(top_rec['Decision'])} for {_clean_display_text(top_rec['Entity'])}. "
                f"{_clean_display_text(top_rec['Evidence Packet'])} Next: {_clean_display_text(top_rec['Safe Next Action'])}"
            )
            source_notes = st.session_state.get("rec_recommendation_sources", [])
            if source_notes:
                defer_source_note("Recommendation sources: " + "; ".join(source_notes))
            render_priority_dataframe(
                df_recs,
                title="Recommendations to work first",
                priority_columns=[
                    "Severity", "Decision Gate", "Decision", "Category", "Entity",
                    "Telemetry Summary", "Safe Next Action", "Review Gate",
                    "Telemetry Package", "Verify Next", "Execution Boundary", "Closure Rule",
                    "Telemetry Basis", "Do Not Do", "Estimated Monthly Savings", "Escalation Route", "Status",
                ],
                sort_by=["Severity", "Estimated Monthly Savings"],
                ascending=[True, False],
                raw_label="All recommendation rows",
                height=420,
            )
            export_recs = df_recs.drop(
                columns=[
                    "Generated SQL Fix", "Generated SQL", "Proof Query", "Verification Query",
                    "APPROVAL_GATE", "PROOF_QUERY", "VERIFICATION_QUERY", "Generated DDL",
                    "Owner", "Owner Route", "Owner Evidence", "Owner Source",
                ],
                errors="ignore",
            )
            download_csv(clean_operator_display_text(export_recs), "recommendations.csv")

            with st.expander("Action review details"):
                for _, rec in df_recs.iterrows():
                    render_escaped_bold_text(f"{rec['Severity']} - {rec['Decision']} - {rec['Entity']}")
                    st.caption(
                        f"{_clean_display_text(rec['Evidence Packet'])} | Review: {_clean_display_text(rec.get('Review Gate', rec.get('Approval Gate', '')))} | "
                        f"Boundary: {_clean_display_text(rec['Execution Boundary'])} | {_clean_display_text(rec['Do Not Do'])}"
                    )
                    st.caption(f"Watch: {_clean_display_text(rec['Verify Next'])}")

            if st.button("Save / refresh these findings in Action Queue", key="rec_save_queue", type="primary"):
                try:
                    saved = upsert_actions(session, df_recs.to_dict("records"))
                    st.success(f"Saved {saved} findings to the persistent action queue.")
                    st.session_state.pop("rec_action_queue", None)
                except Exception as e:
                    st.error(f"Action queue save failed: {format_snowflake_error(e)}")
                    st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry.")
        elif st.session_state.get("rec_recommendations") == []:
            st.success("No actionable findings. Account looks healthy.")

    elif active_view == "Queue Health":
        _render_automation_health(session)

    elif active_view == "Action Queue":
        _render_queue(session)

    elif active_view == "Anomaly Log":
        st.subheader("Anomaly Log")
        st.caption("Flags warehouse credit spikes against a rolling 7-day baseline.")
        anom_days = day_window_selectbox("Detection window", key="anom_days", default=30)

        if st.button("Detect Anomalies", key="anom_detect"):
            with render_load_status("Detecting credit anomalies", "Anomaly scan ready"):
                try:
                    df_anom = run_query(f"""
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
                    """, ttl_key=f"rec_anomaly_{_active_company()}_{anom_days}", tier="historical")
                    st.session_state["rec_anomalies"] = df_anom
                except Exception as e:
                    st.warning(f"Recommendation scan unavailable in this role/context: {format_snowflake_error(e)}")

        df_an = st.session_state.get("rec_anomalies")
        if df_an is not None:
            if not df_an.empty:
                spikes = df_an[df_an.get("ANOMALY_FLAG", pd.Series(dtype=str)).astype(str) == "SPIKE"] if "ANOMALY_FLAG" in df_an.columns else df_an
                st.warning(f"{len(spikes)} spike events detected.")
                render_priority_dataframe(
                    df_an,
                    title="Credit anomalies to investigate first",
                    priority_columns=[
                        "WAREHOUSE_NAME", "DAY", "DAILY_CREDITS",
                        "ROLLING_AVG", "ZSCORE", "ANOMALY_FLAG",
                    ],
                    sort_by=["ZSCORE", "DAILY_CREDITS"],
                    ascending=[False, False],
                    raw_label="All anomaly rows",
                )
                download_csv(df_an, "anomaly_log.csv")
            else:
                st.success("No anomalies detected in the analysis window.")
