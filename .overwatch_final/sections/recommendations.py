# sections/recommendations.py - recommendations, persistent action queue, anomalies, alerts
import pandas as pd
import streamlit as st

from config import THRESHOLDS, ALERT_DB, ALERT_SCHEMA, ALERT_TABLE, ETL_AUDIT_DB, ETL_AUDIT_SCHEMA
from utils import (
    build_idle_warehouse_sql,
    build_mart_recommendation_failed_tasks_sql,
    build_mart_recommendation_idle_sql,
    build_mart_recommendation_query_errors_sql,
    build_mart_recommendation_spill_sql,
    build_task_failure_summary_sql,
    company_value_allowed,
    credits_to_dollars,
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
    safe_float,
    safe_identifier,
    sql_literal,
    update_action_status_with_evidence,
    upsert_actions,
)
from utils.workflows import render_priority_dataframe


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
    q1, q2, q3, q4, q5 = st.columns(5)
    q1.metric("Open", int(open_mask.sum()))
    q2.metric("High/Critical", int(high_mask.sum()))
    q3.metric("Monthly Savings", f"${float(df_queue['EST_MONTHLY_SAVINGS'].fillna(0).sum()):,.0f}")
    q4.metric("Verified Fixed", int(verified_fixed_mask.sum()))
    q5.metric("Soft Fixed", int(soft_fixed_mask.sum()), delta_color="inverse")

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
            "SEVERITY", "STATUS", "VERIFICATION_STATUS", "CATEGORY", "ENVIRONMENT",
            "ENTITY_NAME", "FINDING", "OWNER", "TICKET_ID", "APPROVER",
            "EST_MONTHLY_SAVINGS", "MEASURED_DELTA", "UPDATED_AT", "NEXT_ACTION",
        ],
        sort_by=["SEVERITY", "EST_MONTHLY_SAVINGS", "UPDATED_AT"],
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
    with st.form("queue_status_evidence_form"):
        c_status, c_meta = st.columns([1, 2])
        with c_status:
            new_status = st.selectbox(
                "New status",
                ["Acknowledged", "In Progress", "Fixed", "Ignored", "New"],
                key="queue_new_status",
            )
        with c_meta:
            reason = st.text_input(
                "Reason / note",
                value=_row_text(row, "IGNORED_REASON"),
                key="queue_status_reason",
            )
        c_ticket, c_approver = st.columns(2)
        with c_ticket:
            ticket_id = st.text_input("Ticket / change ID", value=_row_text(row, "TICKET_ID"), key="queue_ticket_id")
        with c_approver:
            approver = st.text_input("Approver / reviewer", value=_row_text(row, "APPROVER"), key="queue_approver")

        default_query = _row_text(row, "VERIFICATION_QUERY") or _row_text(row, "PROOF_QUERY")
        verification_query = st.text_area(
            "Verification query",
            value=default_query,
            key="queue_verification_query",
            height=150,
        )
        verification_result = st.text_area(
            "Verification result",
            value=_row_text(row, "VERIFICATION_RESULT"),
            key="queue_verification_result",
            placeholder="Paste summarized query result, runtime/cost delta, or task/procedure success evidence.",
            height=120,
        )
        verification_notes = st.text_area(
            "Verification notes",
            value=_row_text(row, "VERIFICATION_NOTES"),
            key="queue_verification_notes",
            placeholder="What changed, who approved it, and why the finding can be closed.",
            height=90,
        )
        c_base, c_current, c_delta = st.columns(3)
        with c_base:
            baseline_value = st.text_input(
                "Baseline value",
                value=_row_text(row, "BASELINE_VALUE"),
                key="queue_baseline_value",
            )
        with c_current:
            current_value = st.text_input(
                "Current value",
                value=_row_text(row, "CURRENT_VALUE"),
                key="queue_current_value",
            )
        with c_delta:
            measured_delta = st.text_input(
                "Measured delta",
                value=_row_text(row, "MEASURED_DELTA"),
                key="queue_measured_delta",
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
                baseline_value=_float_text_or_none(baseline_value),
                current_value=_float_text_or_none(current_value),
                measured_delta=_float_text_or_none(measured_delta),
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


def _alert_actions(df_alerts: pd.DataFrame) -> list[dict]:
    actions = []
    company = _active_company()
    for _, row in df_alerts.head(200).iterrows():
        alert_type = str(row.get("ALERT_TYPE") or "Alert")
        severity = str(row.get("SEVERITY") or "Medium").title()
        if severity.upper() == "HIGH":
            severity = "High"
        elif severity.upper() == "MEDIUM":
            severity = "Medium"
        entity = str(row.get("ENTITY") or "Snowflake account")
        detail = str(row.get("DETAIL") or "")
        alert_id = str(row.get("ALERT_ID") or row.get("ALERT_DATE") or "")
        actions.append({
            "Action ID": make_action_id("Alert", entity, f"{alert_type}|{detail}|{alert_id}"),
            "Source": "Alert History",
            "Severity": severity if severity in ["Critical", "High", "Medium", "Low"] else "Medium",
            "Category": "Alert",
            "Entity Type": "Alert Entity",
            "Entity": entity,
            "Owner": str(row.get("OWNER") or "DBA"),
            "Finding": f"{alert_type}: {detail}",
            "Action": str(row.get("SUGGESTED_ACTION") or "Review alert detail and related dashboard drilldown."),
            "Estimated Monthly Savings": 0.0,
            "Generated SQL Fix": "-- Review alert evidence before applying a fix.",
            "Proof Query": f"SELECT * FROM {ALERT_DB}.{ALERT_SCHEMA}.{ALERT_TABLE} WHERE ALERT_ID = {alert_id};" if alert_id.isdigit() else "OVERWATCH alert history row.",
            "Company": company,
        })
    return actions


def _render_annotations(session):
    table_name = (
        f"{safe_identifier(ALERT_DB)}."
        f"{safe_identifier(ALERT_SCHEMA)}."
        f"{safe_identifier('OVERWATCH_ANNOTATIONS')}"
    )

    st.header("Annotation Windows")
    st.caption(
        "Mark deployments, load tests, maintenance windows, or known incidents so "
        "automated alerts can suppress repeat noise during that window."
    )

    with st.form("annotation_create_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            entity_type = st.selectbox(
                "Entity type",
                ["WAREHOUSE", "TASK", "USER", "GLOBAL"],
                key="annotation_entity_type",
            )
            entity = st.text_input(
                "Entity",
                value="*" if entity_type == "GLOBAL" else "",
                key="annotation_entity",
                placeholder="Warehouse, task, user, or *",
            )
        with c2:
            window_start = st.text_input(
                "Window start",
                key="annotation_start",
                placeholder="2026-05-28 22:00:00",
            )
            window_end = st.text_input(
                "Window end",
                key="annotation_end",
                placeholder="2026-05-29 02:00:00",
            )
        with c3:
            annotation_type = st.selectbox(
                "Reason",
                ["DEPLOYMENT", "LOAD_TEST", "PLANNED_MAINTENANCE", "INCIDENT", "OTHER"],
                key="annotation_type",
            )
            suppress_alerts = st.checkbox("Suppress alerts", value=True, key="annotation_suppress")

        description = st.text_area("Description", key="annotation_description")
        submitted = st.form_submit_button("Create Annotation")

    if submitted:
        if not entity.strip() or not window_start.strip() or not window_end.strip():
            st.warning("Entity, window start, and window end are required.")
        else:
            try:
                session.sql(f"""
                    INSERT INTO {table_name}
                        (ENTITY, ENTITY_TYPE, WINDOW_START, WINDOW_END,
                         ANNOTATION_TYPE, DESCRIPTION, SUPPRESS_ALERTS, ACTIVE)
                    SELECT
                        {sql_literal(entity, 500)},
                        {sql_literal(entity_type, 50)},
                        TO_TIMESTAMP_NTZ({sql_literal(window_start, 50)}),
                        TO_TIMESTAMP_NTZ({sql_literal(window_end, 50)}),
                        {sql_literal(annotation_type, 100)},
                        {sql_literal(description, 2000)},
                        {str(bool(suppress_alerts)).upper()},
                        TRUE
                    WHERE TRY_TO_TIMESTAMP_NTZ({sql_literal(window_start, 50)}) IS NOT NULL
                      AND TRY_TO_TIMESTAMP_NTZ({sql_literal(window_end, 50)}) IS NOT NULL
                      AND TRY_TO_TIMESTAMP_NTZ({sql_literal(window_end, 50)})
                            > TRY_TO_TIMESTAMP_NTZ({sql_literal(window_start, 50)})
                """).collect()
                st.success("Annotation created.")
                st.session_state.pop("rec_annotations", None)
            except Exception as e:
                st.info(f"Annotation table unavailable or insert failed. Run the setup DDL first. ({format_snowflake_error(e)})")

    if st.button("Load Annotations", key="annotation_load"):
        try:
            st.session_state["rec_annotations"] = run_query(f"""
                SELECT ANNOTATION_ID, CREATED_BY, CREATED_AT, ENTITY, ENTITY_TYPE,
                       WINDOW_START, WINDOW_END, ANNOTATION_TYPE, DESCRIPTION,
                       SUPPRESS_ALERTS, ACTIVE
                FROM {table_name}
                ORDER BY ACTIVE DESC, WINDOW_START DESC
                LIMIT 200
            """, ttl_key="rec_annotations", tier="metadata")
        except Exception as e:
            st.info(f"Annotation table not found. Run the setup DDL first. ({format_snowflake_error(e)})")
            st.session_state["rec_annotations"] = pd.DataFrame()

    df_ann = st.session_state.get("rec_annotations")
    if df_ann is not None and not df_ann.empty:
        active_count = int(df_ann["ACTIVE"].fillna(False).astype(bool).sum()) if "ACTIVE" in df_ann.columns else 0
        st.metric("Active Annotation Windows", active_count)
        render_priority_dataframe(
            df_ann,
            title="Active annotation windows",
            priority_columns=[
                "ACTIVE", "ENTITY", "ENTITY_TYPE", "WINDOW_START", "WINDOW_END",
                "ANNOTATION_TYPE", "SUPPRESS_ALERTS", "DESCRIPTION", "CREATED_BY",
            ],
            sort_by=["ACTIVE", "WINDOW_START"],
            ascending=[False, False],
            raw_label="All annotation rows",
        )
        download_csv(df_ann, "annotation_windows.csv")

        ids = df_ann["ANNOTATION_ID"].dropna().astype(int).tolist() if "ANNOTATION_ID" in df_ann.columns else []
        if ids:
            selected_id = st.selectbox("Annotation to deactivate", ids, key="annotation_deactivate_id")
            if st.button("Deactivate Annotation", key="annotation_deactivate"):
                try:
                    session.sql(f"""
                        UPDATE {table_name}
                        SET ACTIVE = FALSE
                        WHERE ANNOTATION_ID = {int(selected_id)}
                    """).collect()
                    st.success(f"Annotation {int(selected_id)} deactivated.")
                    st.session_state.pop("rec_annotations", None)
                except Exception as e:
                    st.error(f"Deactivate failed: {format_snowflake_error(e)}")


def render():
    session = get_session()
    credit_price = st.session_state.get("credit_price", 3.00)

    tab_recs, tab_queue, tab_anomaly, tab_alerts, tab_annotations = st.tabs([
        "Recommendations", "Action Queue", "Anomaly Log", "Alert Configuration", "Annotations"
    ])

    with tab_recs:
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
                    monthly_savings = credits_to_dollars(float(row["IDLE_CREDITS"] or 0) / 7 * 30, credit_price)
                    recs.append({
                        "Source": "Idle warehouse detector",
                        "Severity": "High",
                        "Category": "Cost",
                        "Entity Type": "Warehouse",
                        "Entity": wh_name,
                        "Owner": "DBA",
                        "Finding": f"{wh_name} idle {int(row['IDLE_HOURS'])}h, wasting {format_credits(row['IDLE_CREDITS'])}",
                        "Action": f"Reduce AUTO_SUSPEND to <= {THRESHOLDS['idle_warehouse_minutes']} minutes",
                        "Estimated Monthly Savings": round(monthly_savings, 2),
                        "Generated SQL Fix": f"ALTER WAREHOUSE {wh_ident} SET AUTO_SUSPEND = {THRESHOLDS['idle_warehouse_minutes'] * 60};",
                        "Proof Query": "WAREHOUSE_METERING_HISTORY joined to QUERY_HISTORY by hour where query count = 0.",
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
                    recs.append({
                        "Source": "Remote spill detector",
                        "Severity": "Medium",
                        "Category": "Performance",
                        "Entity Type": "Warehouse",
                        "Entity": wh_name,
                        "Owner": "DBA",
                        "Finding": f"{wh_name} ({row['WAREHOUSE_SIZE']}): {row['REMOTE_GB']:.1f} GB remote spill",
                        "Action": "Review query profile; upsize or split workload if spill persists.",
                        "Estimated Monthly Savings": 0.0,
                        "Generated SQL Fix": f"-- Review memory pressure on {wh_name}; consider ALTER WAREHOUSE {safe_identifier(wh_name)} SET WAREHOUSE_SIZE = '<NEXT_SIZE>';",
                        "Proof Query": "QUERY_HISTORY bytes_spilled_to_remote_storage over the last 7 days.",
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
                    recs.append({
                        "Source": "Task failure detector",
                        "Severity": "High",
                        "Category": "Reliability",
                        "Entity Type": "Task",
                        "Entity": task_name,
                        "Owner": "Data Engineering",
                        "Finding": f"Task {task_name} failed {int(row['FAILURES'])} times in 7 days",
                        "Action": "Review task error logs in Task Management and fix root cause.",
                        "Estimated Monthly Savings": 0.0,
                        "Generated SQL Fix": f"-- Inspect task: {task_name}\n-- EXECUTE TASK <database>.<schema>.{safe_identifier(task_name)};",
                        "Proof Query": "TASK_HISTORY state = FAILED over the last 7 days.",
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
                        "Proof Query": "QUERY_HISTORY UPPER(execution_status) = 'FAILED_WITH_ERROR' over the last 7 days.",
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
            c1, c2, c3 = st.columns(3)
            c1.metric("High/Critical", len(high))
            c2.metric("Open Findings", len(df_recs))
            c3.metric("Est. Monthly Savings", f"${monthly:,.0f}")
            st.caption(
                f"{metric_confidence_label('estimated')} | {freshness_note('ACCOUNT_USAGE')} | "
                "Savings are directional until the action is fixed and logged to Snowflake Value."
            )
            source_notes = st.session_state.get("rec_recommendation_sources", [])
            if source_notes:
                st.caption("Recommendation sources: " + "; ".join(source_notes))
            render_priority_dataframe(
                df_recs,
                title="Recommendations to work first",
                priority_columns=[
                    "Severity", "Category", "Entity Type", "Entity", "Finding",
                    "Action", "Estimated Monthly Savings", "Owner", "Status",
                ],
                sort_by=["Estimated Monthly Savings"],
                ascending=False,
                raw_label="All recommendation rows",
            )
            download_csv(df_recs, "recommendations.csv")

            with st.expander("Generated SQL fixes and proof queries"):
                for _, rec in df_recs.iterrows():
                    st.markdown(f"**{rec['Severity']} - {rec['Entity']}**")
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

    with tab_queue:
        _render_queue(session)

    with tab_anomaly:
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

    with tab_alerts:
        st.header("Alert History")
        st.caption(
            "Reads the deployed OVERWATCH alert table. Alert task/table DDL is maintained outside the dashboard "
            "in the Snowflake setup script."
        )
        if st.button("Load Alert History", key="alert_hist_load"):
            try:
                cols = set(filter_existing_columns(
                    session,
                    f"{ALERT_DB}.{ALERT_SCHEMA}.{ALERT_TABLE}",
                    [
                        "ALERT_ID", "ALERT_TS", "ALERT_DATE", "COMPANY", "CATEGORY", "ALERT_TYPE",
                        "SEVERITY", "ENTITY_NAME", "ENTITY", "MESSAGE", "DETAIL", "PROOF_QUERY",
                        "OWNER", "STATUS", "DELIVERY_STATUS",
                    ],
                ))
                if not cols:
                    raise ValueError("No recognized columns found in alert history table.")
                ts_col = "ALERT_TS" if "ALERT_TS" in cols else "ALERT_DATE" if "ALERT_DATE" in cols else "CURRENT_TIMESTAMP()"
                category_col = "CATEGORY" if "CATEGORY" in cols else "ALERT_TYPE" if "ALERT_TYPE" in cols else "'Alert'"
                entity_col = "ENTITY_NAME" if "ENTITY_NAME" in cols else "ENTITY" if "ENTITY" in cols else "'Snowflake account'"
                message_col = "MESSAGE" if "MESSAGE" in cols else "DETAIL" if "DETAIL" in cols else "''"
                proof_col = "PROOF_QUERY" if "PROOF_QUERY" in cols else "''"
                owner_col = "OWNER" if "OWNER" in cols else "'DBA'"
                status_col = "STATUS" if "STATUS" in cols else "'New'"
                company_expr = "COMPANY" if "COMPANY" in cols else f"{sql_literal(_active_company())} AS COMPANY"
                company_filter = "" if _active_company() == "ALL" or "COMPANY" not in cols else f"AND COMPANY = {sql_literal(_active_company())}"
                df_ah = run_query(f"""
                    SELECT
                        ALERT_ID,
                        {ts_col} AS ALERT_TS,
                        {company_expr},
                        {category_col} AS CATEGORY,
                        COALESCE(SEVERITY, 'Medium') AS SEVERITY,
                        {entity_col} AS ENTITY_NAME,
                        {message_col} AS MESSAGE,
                        {proof_col} AS PROOF_QUERY,
                        {owner_col} AS OWNER,
                        {status_col} AS STATUS
                    FROM {ALERT_DB}.{ALERT_SCHEMA}.{ALERT_TABLE}
                    WHERE 1 = 1
                      {company_filter}
                    ORDER BY ALERT_TS DESC
                    LIMIT 100
                """, ttl_key=f"rec_alert_history_{_active_company()}", tier="recent")
                if not df_ah.empty:
                    company = _active_company()
                    if company != "ALL":
                        if "COMPANY" in df_ah.columns:
                            df_ah = df_ah[df_ah["COMPANY"].fillna("ALFA") == company]
                        elif "ENTITY" in df_ah.columns:
                            df_ah = df_ah[
                                df_ah["ENTITY"].apply(lambda value: company_value_allowed(value, "warehouse", company))
                                | df_ah["ENTITY"].apply(lambda value: company_value_allowed(value, "database", company))
                            ]
                    if "STATUS" in df_ah.columns:
                        status = st.selectbox(
                            "Filter status",
                            ["ALL"] + sorted(df_ah["STATUS"].dropna().unique().tolist()),
                            key="alert_status_filter",
                        )
                        if status != "ALL":
                            df_ah = df_ah[df_ah["STATUS"] == status]
                    render_priority_dataframe(
                        df_ah,
                        title="Alert history to triage first",
                        priority_columns=[
                            "SEVERITY", "STATUS", "ALERT_TS", "CATEGORY",
                            "ENTITY_NAME", "MESSAGE", "OWNER", "PROOF_QUERY",
                        ],
                        sort_by=["ALERT_TS"],
                        ascending=False,
                        raw_label="All alert history rows",
                    )
                    download_csv(df_ah, "alert_history.csv")
                    st.session_state["rec_alert_history"] = df_ah
                else:
                    st.info("No alerts recorded yet.")
                    st.session_state["rec_alert_history"] = pd.DataFrame()
            except Exception as e:
                st.info(f"Alert table not found. Run the setup SQL first. ({format_snowflake_error(e)})")

        df_alerts = st.session_state.get("rec_alert_history")
        if df_alerts is not None and not df_alerts.empty:
            if st.button("Save alert history to Action Queue", key="alert_history_to_queue"):
                try:
                    saved = upsert_actions(session, _alert_actions(df_alerts))
                    st.success(f"Saved {saved} alert actions to the persistent action queue.")
                    st.session_state.pop("rec_action_queue", None)
                except Exception as e:
                    st.error(f"Could not save alerts to action queue: {format_snowflake_error(e)}")
                    st.info("Deploy the Action Queue table through `snowflake/OVERWATCH_MART_SETUP.sql`, then retry.")

    with tab_annotations:
        _render_annotations(session)
