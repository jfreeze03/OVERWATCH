# sections/recommendations.py - recommendations, persistent action queue, and anomalies
import pandas as pd
import streamlit as st

from config import DEFAULTS, THRESHOLDS
from sections.shell_helpers import _clean_display_text, render_shell_snapshot
from utils import (
    build_idle_warehouse_sql,
    build_mart_recommendation_failed_tasks_sql,
    build_mart_recommendation_idle_sql,
    build_mart_recommendation_query_errors_sql,
    build_mart_recommendation_spill_sql,
    build_safe_verification_query,
    build_task_failure_summary_sql,
    credits_to_dollars,
    day_window_selectbox,
    defer_source_note,
    download_csv,
    filter_existing_columns,
    format_snowflake_error,
    format_credits,
    get_global_filter_clause,
    get_session,
    get_wh_filter_clause,
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
    "Automation Health",
    "Action Queue",
    "Anomaly Log",
)


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
    st.subheader("Automation Health")
    st.caption("DBA-safe automation lanes for recommendations and action queue items.")
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
        st.info("No automation candidates loaded. Generate recommendations or load the action queue first.")
        render_priority_dataframe(
            _automation_playbook_frame(),
            title="Automation lane definitions",
            priority_columns=["AUTOMATION_LANE", "WHAT_IT_MEANS", "DBA_ACTION"],
            sort_by=["AUTOMATION_LANE"],
            ascending=True,
            raw_label="All automation lane definitions",
            height=260,
        )
        return

    ready = int((board["AUTOMATION_LANE"] == "Ready").sum())
    approval = int((board["AUTOMATION_LANE"] == "Telemetry Pending").sum())
    evidence = int((board["AUTOMATION_LANE"] == "Needs Data").sum())
    manual = int((board["AUTOMATION_LANE"] == "DBA Review").sum())
    auto_close = int((board["AUTOMATION_LANE"] == "Resolved Candidate").sum())
    render_shell_snapshot((
        ("Candidates", f"{len(board):,}"),
        ("Guided Ready", f"{ready:,}"),
        ("Telemetry Pending", f"{approval:,}"),
        ("Needs Data", f"{evidence:,}"),
        ("DBA Review", f"{manual:,}"),
        ("Resolved", f"{auto_close:,}"),
    ))

    first = board.iloc[0]
    st.warning(
        f"Automation first move: {first['AUTOMATION_LANE']} for {first['ENTITY']}. "
        f"Blockers: {first['BLOCKERS']}. Next: {first['SAFE_AUTOMATION_STEP']}"
    )
    render_priority_dataframe(
        board,
        title="Automation health board",
        priority_columns=[
            "AUTOMATION_LANE", "SEVERITY", "CATEGORY", "ENTITY",
            "DECISION", "BLOCKERS", "APPROVAL_STATE", "SAFE_GUIDED_SQL",
            "STATE_CHANGING_SQL", "SAFE_AUTOMATION_STEP", "APPROVAL_GATE",
            "EVIDENCE_PACKAGE", "VERIFY_NEXT", "EXECUTION_BOUNDARY", "CLOSURE_RULE",
            "PROOF_REQUIRED", "DO_NOT_DO",
        ],
        sort_by=["AUTOMATION_LANE", "SEVERITY"],
        ascending=[True, True],
        raw_label="All automation health rows",
        height=440,
    )
    download_csv(board, "automation_health_board.csv")

    with st.expander("Automation lane definitions", expanded=False):
        render_priority_dataframe(
            _automation_playbook_frame(),
            title="Automation playbook",
            priority_columns=["AUTOMATION_LANE", "WHAT_IT_MEANS", "DBA_ACTION"],
            sort_by=["AUTOMATION_LANE"],
            ascending=True,
            raw_label="All automation playbook rows",
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
    st.markdown(f"**{row['ENTITY_NAME']}** - {row['FINDING']}")
    st.caption(str(row.get("NEXT_ACTION", "Review the route and current telemetry before action.")))
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
                try:
                    df_idle = run_query(
                        build_mart_recommendation_idle_sql(company),
                        ttl_key=f"rec_idle_mart_{company}",
                        tier="historical",
                    )
                    source_notes.append("Idle warehouses: Fast summary")
                except Exception:
                    df_idle = run_query(
                        build_idle_warehouse_sql(
                            days_back=7,
                            wh_filter=get_wh_filter_clause("warehouse_name"),
                            min_idle_credits=1.0,
                        ) + "\nLIMIT 10",
                        ttl_key=f"rec_idle_live_{company}",
                        tier="historical",
                    )
                    source_notes.append("Idle warehouses: live ACCOUNT_USAGE fallback")
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
                try:
                    df_spill = run_query(
                        build_mart_recommendation_spill_sql(company),
                        ttl_key=f"rec_spill_mart_{company}",
                        tier="historical",
                    )
                    source_notes.append("Remote spill: Fast summary")
                except Exception:
                    qh_cols = set(filter_existing_columns(
                        session,
                        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                        ["WAREHOUSE_SIZE", "BYTES_SPILLED_TO_REMOTE_STORAGE"],
                    ))
                    if "BYTES_SPILLED_TO_REMOTE_STORAGE" not in qh_cols:
                        raise ValueError("Remote spill column is not exposed in QUERY_HISTORY.")
                    spill_wh_size_expr = (
                        "MAX(warehouse_size)"
                        if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR"
                    )
                    df_spill = run_query(f"""
                        SELECT warehouse_name, {spill_wh_size_expr} AS warehouse_size,
                               ROUND(SUM(bytes_spilled_to_remote_storage)/POWER(1024,3), 2) AS remote_gb
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                        WHERE start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
                          AND bytes_spilled_to_remote_storage > 0
                          AND warehouse_name IS NOT NULL
                          {query_filters}
                        GROUP BY warehouse_name
                        HAVING remote_gb > 5
                        ORDER BY remote_gb DESC
                        LIMIT 10
                    """, ttl_key=f"rec_spill_live_{company}", tier="historical")
                    source_notes.append("Remote spill: live ACCOUNT_USAGE fallback")
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
                try:
                    df_ftask = run_query(
                        build_mart_recommendation_failed_tasks_sql(company),
                        ttl_key=f"rec_failed_tasks_mart_{company}",
                        tier="historical",
                    )
                    source_notes.append("Failed tasks: Fast summary")
                except Exception:
                    failed_task_sql = build_task_failure_summary_sql(
                        session,
                        "scheduled_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())",
                        limit=25,
                        company=company,
                    )
                    df_ftask = run_query(
                        f"WITH failed_tasks AS ({failed_task_sql}) "
                        "SELECT * FROM failed_tasks WHERE failures > 3 ORDER BY failures DESC LIMIT 5",
                        ttl_key=f"rec_failed_tasks_live_{company}",
                        tier="historical",
                    )
                    source_notes.append("Failed tasks: live ACCOUNT_USAGE fallback")
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
                try:
                    df_err = run_query(
                        build_mart_recommendation_query_errors_sql(
                            company,
                            min_failures=THRESHOLDS["error_rate_high"],
                        ),
                        ttl_key=f"rec_query_errors_mart_{company}",
                        tier="historical",
                    )
                    source_notes.append("Query failures: Fast summary")
                except Exception:
                    df_err = run_query(f"""
                        SELECT warehouse_name, COUNT(*) AS failures
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                        WHERE start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
                          AND UPPER(execution_status) = 'FAILED_WITH_ERROR'
                          AND warehouse_name IS NOT NULL
                          {query_filters}
                        GROUP BY warehouse_name
                        HAVING failures > {THRESHOLDS['error_rate_high']}
                        ORDER BY failures DESC
                        LIMIT 5
                    """, ttl_key=f"rec_query_errors_live_{company}", tier="historical")
                    source_notes.append("Query failures: live ACCOUNT_USAGE fallback")
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
                    st.markdown(
                        f"**{_clean_display_text(rec['Severity'])} - {_clean_display_text(rec['Decision'])} - {_clean_display_text(rec['Entity'])}**"
                    )
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

    elif active_view == "Automation Health":
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
