# sections/recommendations.py - recommendations, persistent action queue, and anomalies
import pandas as pd
import streamlit as st

from config import THRESHOLDS, ETL_AUDIT_DB, ETL_AUDIT_SCHEMA
from utils import (
    build_idle_warehouse_sql,
    build_mart_recommendation_failed_tasks_sql,
    build_mart_recommendation_idle_sql,
    build_mart_recommendation_query_errors_sql,
    build_mart_recommendation_spill_sql,
    build_safe_verification_query,
    build_task_failure_summary_sql,
    credits_to_dollars,
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
from utils.workflows import render_priority_dataframe


RECOMMENDATION_PANES = (
    "Recommendations",
    "Automation Readiness",
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
    return f"""-- Idle warehouse post-fix verification
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
    return f"""-- Remote spill post-fix verification
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
    return f"""-- Task failure post-fix verification
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
    return f"""-- Query failure post-fix verification
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
            "AUTOMATION_LANE": "Ready for Guided Execution",
            "WHAT_IT_MEANS": "Safe SQL shape, owner route, approval, and verification query are present.",
            "DBA_ACTION": "Execute only through the owning admin workflow, then run verification before closure.",
        },
        {
            "AUTOMATION_LANE": "Approval Required",
            "WHAT_IT_MEANS": "The action looks automatable, but owner approval or approver metadata is missing.",
            "DBA_ACTION": "Capture approval first; do not run SQL from the recommendation text alone.",
        },
        {
            "AUTOMATION_LANE": "Evidence Required",
            "WHAT_IT_MEANS": "The action lacks verification query, owner route, or proof needed for audit.",
            "DBA_ACTION": "Complete evidence fields, then rerun the automation board.",
        },
        {
            "AUTOMATION_LANE": "Manual Only",
            "WHAT_IT_MEANS": "The action touches security, task execution, failover, clustering proof, or unsafe SQL.",
            "DBA_ACTION": "Keep human-controlled and use OVERWATCH only for evidence, routing, and closure tracking.",
        },
        {
            "AUTOMATION_LANE": "Auto-Close Candidate",
            "WHAT_IT_MEANS": "The action is already fixed and has verified closure evidence.",
            "DBA_ACTION": "Review owner agreement, then move it out of active work queues.",
        },
    ])


def _render_automation_readiness(session):
    st.header("Automation Readiness")
    st.caption("DBA-safe automation lanes for recommendations and action queue items.")
    c_load, c_hint = st.columns([1, 3])
    with c_load:
        if st.button("Load Action Queue", key="automation_queue_load"):
            try:
                st.session_state["rec_action_queue"] = load_action_queue(session)
            except Exception as e:
                st.info(f"Action queue table not found. Run the setup DDL first. ({format_snowflake_error(e)})")
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

    ready = int((board["AUTOMATION_LANE"] == "Ready for Guided Execution").sum())
    approval = int((board["AUTOMATION_LANE"] == "Approval Required").sum())
    evidence = int((board["AUTOMATION_LANE"] == "Evidence Required").sum())
    manual = int((board["AUTOMATION_LANE"] == "Manual Only").sum())
    auto_close = int((board["AUTOMATION_LANE"] == "Auto-Close Candidate").sum())
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Candidates", f"{len(board):,}")
    m2.metric("Guided Ready", f"{ready:,}")
    m3.metric("Approval Needed", f"{approval:,}", delta_color="inverse")
    m4.metric("Evidence Needed", f"{evidence:,}", delta_color="inverse")
    m5.metric("Manual Only", f"{manual:,}")
    m6.metric("Auto-Close", f"{auto_close:,}")

    first = board.iloc[0]
    st.warning(
        f"Automation first move: {first['AUTOMATION_LANE']} for {first['ENTITY']}. "
        f"Blockers: {first['BLOCKERS']}. Next: {first['SAFE_AUTOMATION_STEP']}"
    )
    render_priority_dataframe(
        board,
        title="Automation readiness board",
        priority_columns=[
            "AUTOMATION_LANE", "AUTOMATION_SCORE", "SEVERITY", "CATEGORY", "ENTITY",
            "DECISION", "BLOCKERS", "APPROVAL_STATE", "SAFE_GUIDED_SQL",
            "STATE_CHANGING_SQL", "SAFE_AUTOMATION_STEP", "PROOF_REQUIRED", "DO_NOT_DO",
        ],
        sort_by=["AUTOMATION_LANE", "AUTOMATION_SCORE", "SEVERITY"],
        ascending=[True, False, True],
        raw_label="All automation readiness rows",
        height=440,
    )
    download_csv(board, "automation_readiness_board.csv")

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
    st.header("Persistent Action Queue")
    st.caption("Owner, status, savings, generated SQL, and proof query for every actionable finding.")
    st.info("Action Queue setup is managed by `snowflake/OVERWATCH_MART_SETUP.sql`.")

    if st.button("Load Action Queue", key="queue_load"):
        try:
            st.session_state["rec_action_queue"] = load_action_queue(session)
        except Exception as e:
            st.info(f"Action queue table not found. Run the setup DDL first. ({format_snowflake_error(e)})")
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
    verified_fixed_mask = fixed_mask & (verification_status == "Verified")
    soft_fixed_mask = fixed_mask & (verification_status != "Verified")
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
    evidence_gap_mask = ~evidence_gap.isin(["Ready to work", "Verified closure", "Ignored with reason"])
    overdue_mask = open_mask & (due_state == "Overdue")
    q1, q2, q3, q4, q5, q6 = st.columns(6)
    q1.metric("Open", int(open_mask.sum()))
    q2.metric("High/Critical", int(high_mask.sum()))
    q3.metric("Overdue", int(overdue_mask.sum()), delta_color="inverse")
    q4.metric("Evidence Gaps", int(evidence_gap_mask.sum()), delta_color="inverse")
    q5.metric("Verified Fixed", int(verified_fixed_mask.sum()))
    q6.metric("Savings Queue", f"${float(df_queue['EST_MONTHLY_SAVINGS'].fillna(0).sum()):,.0f}")
    if int(soft_fixed_mask.sum()):
        st.warning(f"{int(soft_fixed_mask.sum())} fixed action(s) are missing verified closure evidence.")

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
            "VERIFICATION_STATUS", "CATEGORY", "ENVIRONMENT", "ENTITY_NAME",
            "FINDING", "OWNER", "TICKET_ID", "APPROVER",
            "OWNER_APPROVAL_STATUS", "RECOVERY_SLA_STATE", "RECOVERY_SLA_HOURS",
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

    selected = st.selectbox("Update action", show_df["ACTION_ID"].astype(str).tolist(), key="queue_action_select")
    row = show_df[show_df["ACTION_ID"].astype(str) == selected].iloc[0]
    st.markdown(f"**{row['ENTITY_NAME']}** - {row['FINDING']}")
    st.code(str(row.get("GENERATED_SQL_FIX", "")), language="sql")
    st.caption(str(row.get("PROOF_QUERY", "")))

    st.subheader("Closure Evidence")
    st.caption("Fixed items require verification notes and before/after evidence. Use the proof query as the starting point.")
    default_query = _row_text(row, "VERIFICATION_QUERY") or _row_text(row, "PROOF_QUERY")
    safety_issues = verification_query_safety_issues(default_query)
    if safety_issues:
        st.warning("Stored verification query is not runnable from the app: " + "; ".join(safety_issues))
    elif st.button("Run stored verification query", key=f"queue_run_verification_{selected}"):
        try:
            verification_sql = build_safe_verification_query(default_query)
            evidence_df = run_query_or_raise(
                verification_sql,
                section="Action Queue",
                ttl_key=f"action_queue_verify_{selected}",
                tier="live",
            )
            st.session_state[f"queue_verification_result_prefill_{selected}"] = summarize_verification_frame(evidence_df)
            st.session_state[f"queue_verification_query_prefill_{selected}"] = verification_sql
            st.success("Verification query ran. Review the summarized evidence before closing the item.")
            st.rerun()
        except Exception as e:
            st.error(f"Could not run verification query: {format_snowflake_error(e)}")

    verification_query_default = st.session_state.get(
        f"queue_verification_query_prefill_{selected}",
        default_query,
    )
    verification_result_default = st.session_state.get(
        f"queue_verification_result_prefill_{selected}",
        _row_text(row, "VERIFICATION_RESULT"),
    )
    with st.form(f"queue_status_evidence_form_{selected}"):
        c_status, c_meta = st.columns([1, 2])
        with c_status:
            new_status = st.selectbox(
                "New status",
                ["Acknowledged", "In Progress", "Fixed", "Ignored", "New"],
                key=f"queue_new_status_{selected}",
            )
        with c_meta:
            reason = st.text_input(
                "Reason / note",
                value=_row_text(row, "IGNORED_REASON"),
                key=f"queue_status_reason_{selected}",
            )
        c_ticket, c_approver, c_due = st.columns(3)
        with c_ticket:
            ticket_id = st.text_input("Ticket / change ID", value=_row_text(row, "TICKET_ID"), key=f"queue_ticket_id_{selected}")
        with c_approver:
            approver = st.text_input("Approver / reviewer", value=_row_text(row, "APPROVER"), key=f"queue_approver_{selected}")
        with c_due:
            due_date = st.text_input(
                "Due date",
                value=_row_text(row, "DUE_DATE"),
                key=f"queue_due_date_{selected}",
                placeholder="YYYY-MM-DD",
            )

        verification_query = st.text_area(
            "Verification query",
            value=verification_query_default,
            key=f"queue_verification_query_{selected}",
            height=150,
        )
        verification_result = st.text_area(
            "Verification result",
            value=verification_result_default,
            key=f"queue_verification_result_{selected}",
            placeholder="Paste summarized query result, runtime/cost delta, or task/procedure success evidence.",
            height=120,
        )
        verification_notes = st.text_area(
            "Verification notes",
            value=_row_text(row, "VERIFICATION_NOTES"),
            key=f"queue_verification_notes_{selected}",
            placeholder="What changed, who approved it, and why the finding can be closed.",
            height=90,
        )
        c_base, c_current, c_delta = st.columns(3)
        with c_base:
            baseline_value = st.text_input(
                "Baseline value",
                value=_row_text(row, "BASELINE_VALUE"),
                key=f"queue_baseline_value_{selected}",
            )
        with c_current:
            current_value = st.text_input(
                "Current value",
                value=_row_text(row, "CURRENT_VALUE"),
                key=f"queue_current_value_{selected}",
            )
        with c_delta:
            measured_delta = st.text_input(
                "Measured delta",
                value=_row_text(row, "MEASURED_DELTA"),
                key=f"queue_measured_delta_{selected}",
            )
        st.markdown("**Task / Procedure Reliability Evidence**")
        c_owner_status, c_recovery_state, c_recovery_hours = st.columns(3)
        approval_options = ["", "Requested", "Approved", "Rejected", "Not Required"]
        current_approval = _row_text(row, "OWNER_APPROVAL_STATUS")
        approval_lookup = {option.upper(): option for option in approval_options}
        current_approval = approval_lookup.get(current_approval.upper(), current_approval)
        approval_index = approval_options.index(current_approval) if current_approval in approval_options else 0
        with c_owner_status:
            owner_approval_status = st.selectbox(
                "Owner approval status",
                approval_options,
                index=approval_index,
                key=f"queue_owner_approval_status_{selected}",
            )
        with c_recovery_state:
            recovery_sla_state = st.text_input(
                "Recovery SLA state",
                value=_row_text(row, "RECOVERY_SLA_STATE"),
                key=f"queue_recovery_sla_state_{selected}",
            )
        with c_recovery_hours:
            recovery_sla_hours = st.text_input(
                "Recovery hours",
                value=_row_text(row, "RECOVERY_SLA_HOURS"),
                key=f"queue_recovery_sla_hours_{selected}",
            )
        c_recovery_target, c_owner_note = st.columns([1, 2])
        with c_recovery_target:
            recovery_sla_target_hours = st.text_input(
                "Recovery target hours",
                value=_row_text(row, "RECOVERY_SLA_TARGET_HOURS"),
                key=f"queue_recovery_sla_target_{selected}",
            )
        with c_owner_note:
            owner_approval_note = st.text_input(
                "Owner approval note",
                value=_row_text(row, "OWNER_APPROVAL_NOTE"),
                key=f"queue_owner_approval_note_{selected}",
            )
        recovery_evidence = st.text_area(
            "Recovery evidence",
            value=_row_text(row, "RECOVERY_EVIDENCE"),
            key=f"queue_recovery_evidence_{selected}",
            placeholder="Recovery timestamp, latest successful TASK_HISTORY evidence, owner sign-off, and any remaining risk.",
            height=90,
        )
        submitted = st.form_submit_button("Update action with evidence", type="primary")

    if submitted:
        try:
            update_action_status_with_evidence(
                session,
                selected,
                new_status,
                reason=reason,
                verification_notes=verification_notes,
                verification_result=verification_result,
                verification_query=verification_query,
                ticket_id=ticket_id,
                approver=approver,
                due_date=due_date,
                baseline_value=_float_text_or_none(baseline_value),
                current_value=_float_text_or_none(current_value),
                measured_delta=_float_text_or_none(measured_delta),
                owner_approval_status=owner_approval_status,
                owner_approval_note=owner_approval_note,
                recovery_sla_state=recovery_sla_state,
                recovery_sla_hours=_float_text_or_none(recovery_sla_hours),
                recovery_sla_target_hours=_float_text_or_none(recovery_sla_target_hours),
                recovery_evidence=recovery_evidence,
            )
            st.success("Action updated with closure evidence.")
            st.session_state["rec_action_queue"] = load_action_queue(session)
            st.rerun()
        except ValueError as e:
            st.warning(str(e))
        except Exception as e:
            st.error(f"Could not update action: {format_snowflake_error(e)}")

    if row.get("STATUS") == "Fixed" and safe_float(row.get("EST_MONTHLY_SAVINGS")) > 0:
        st.divider()
        st.subheader("Log Fixed Action to Snowflake Value")
        monthly_savings = safe_float(row.get("EST_MONTHLY_SAVINGS"))
        savings_credits = monthly_savings / 30 / max(st.session_state.get("credit_price", 3.00), 0.01)
        if st.button("Create Snowflake Value entry", key="queue_log_value"):
            try:
                value_table = (
                    f"{safe_identifier(ETL_AUDIT_DB)}."
                    f"{safe_identifier(ETL_AUDIT_SCHEMA)}."
                    f"{safe_identifier('OVERWATCH_ROI_LOG')}"
                )
                desc = sql_literal(row.get("RECOMMENDED_ACTION") or row.get("FINDING") or "", 1000)
                entity = sql_literal(row.get("ENTITY_NAME") or "", 500)
                notes = sql_literal(f"Created from action queue item {selected}", 1000)
                session.sql(f"""
                    INSERT INTO {value_table}
                        (CATEGORY, DESCRIPTION, ENTITY, BASELINE_CREDITS,
                         CURRENT_CREDITS, SAVINGS_CREDITS, SAVINGS_MONTHLY, VERIFIED, NOTES)
                    VALUES (
                        'Action Queue', {desc}, {entity},
                        {savings_credits}, 0, {savings_credits},
                        {monthly_savings}, TRUE, {notes}
                    )
                """).collect()
                st.success(f"Logged ${monthly_savings:,.2f}/month to Snowflake Value.")
            except Exception as e:
                st.error(f"Could not log Snowflake Value: {format_snowflake_error(e)}")
                st.info("Run the Snowflake Value setup DDL first.")


def render():
    session = get_session()
    credit_price = st.session_state.get("credit_price", 3.00)

    active_view = st.radio(
        "Recommendation view",
        RECOMMENDATION_PANES,
        horizontal=True,
        label_visibility="collapsed",
        key="recommendations_active_view",
    )

    if active_view == "Recommendations":
        st.header("Automated Recommendations Feed")
        st.caption("Prioritized findings that can be saved into a persistent owner/status queue.")

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
                    source_notes.append("Idle warehouses: OVERWATCH mart")
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
                    source_notes.append("Remote spill: OVERWATCH mart")
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
                    source_notes.append("Failed tasks: OVERWATCH mart")
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
                    source_notes.append("Query failures: OVERWATCH mart")
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
            proof_ready = int(df_recs["Proof Query"].astype(str).str.strip().ne("").sum()) if "Proof Query" in df_recs.columns else 0
            sql_ready = int(
                df_recs["Generated SQL Fix"].astype(str).str.strip().ne("").sum()
            ) if "Generated SQL Fix" in df_recs.columns else 0
            no_auto_fix = int(
                df_recs["Generated SQL Fix"].astype(str).str.contains("No safe automatic SQL fix", case=False, na=False).sum()
            ) if "Generated SQL Fix" in df_recs.columns else 0
            decisive_pct = proof_ready / max(len(df_recs), 1) * 100
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("High/Critical", len(high))
            c2.metric("Open Findings", len(df_recs))
            c3.metric("Est. Monthly Savings", f"${monthly:,.0f}")
            c4.metric("Proof-Ready", f"{proof_ready:,}", delta=f"{decisive_pct:.0f}%")
            c5.metric("SQL Fix Candidates", f"{max(sql_ready - no_auto_fix, 0):,}", delta=f"{no_auto_fix:,} manual")
            defer_source_note(
                metric_confidence_label("estimated"),
                freshness_note("ACCOUNT_USAGE"),
                "Savings are directional until the action is fixed and logged to Snowflake Value.",
            )
            top_rec = df_recs.iloc[0]
            st.warning(
                f"Work first: {top_rec['Decision']} for {top_rec['Entity']}. "
                f"{top_rec['Evidence Packet']} Next: {top_rec['Safe Next Action']}"
            )
            source_notes = st.session_state.get("rec_recommendation_sources", [])
            if source_notes:
                defer_source_note("Recommendation sources: " + "; ".join(source_notes))
            render_priority_dataframe(
                df_recs,
                title="Recommendations to work first",
                priority_columns=[
                    "Severity", "Decision Gate", "Decision", "Category", "Entity",
                    "Evidence Packet", "Safe Next Action", "Proof Required",
                    "Do Not Do", "Estimated Monthly Savings", "Owner Route", "Status",
                ],
                sort_by=["Severity", "Estimated Monthly Savings"],
                ascending=[True, False],
                raw_label="All recommendation rows",
                height=420,
            )
            download_csv(df_recs, "recommendations.csv")

            with st.expander("Generated SQL fixes and proof queries"):
                for _, rec in df_recs.iterrows():
                    st.markdown(f"**{rec['Severity']} - {rec['Decision']} - {rec['Entity']}**")
                    st.caption(f"{rec['Evidence Packet']} | {rec['Do Not Do']}")
                    st.code(rec["Generated SQL Fix"], language="sql")
                    st.caption(rec["Proof Query"])

            if st.button("Save / refresh these findings in Action Queue", key="rec_save_queue", type="primary"):
                try:
                    saved = upsert_actions(session, df_recs.to_dict("records"))
                    st.success(f"Saved {saved} findings to the persistent action queue.")
                    st.session_state.pop("rec_action_queue", None)
                except Exception as e:
                    st.error(f"Action queue save failed: {format_snowflake_error(e)}")
                    st.info("Deploy the Action Queue table through `snowflake/OVERWATCH_MART_SETUP.sql`, then retry.")
        elif st.session_state.get("rec_recommendations") == []:
            st.success("No actionable findings. Account looks healthy.")

    elif active_view == "Automation Readiness":
        _render_automation_readiness(session)

    elif active_view == "Action Queue":
        _render_queue(session)

    elif active_view == "Anomaly Log":
        st.header("Anomaly Log")
        st.caption("Z-score based credit spike detection per warehouse using a rolling 7-day baseline.")
        anom_days = st.slider("Detection window (days)", 14, 90, 30, key="anom_days")

        if st.button("Detect Anomalies", key="anom_detect"):
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
