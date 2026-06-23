# sections/dba_tools.py - DBA admin toolkit
# -----------------------------------------------------------------------------
# Specialist workflows are selected by group so only one guarded tool renders at a time.
# -----------------------------------------------------------------------------
from html import escape as html_escape

import streamlit as st
import pandas as pd
from utils import (
    get_session, safe_sql, format_credits, download_csv,
    get_wh_filter_clause, get_db_filter_clause, get_user_company_filter_clause,
    get_active_company, get_active_environment, company_value_allowed,
    run_query, run_query_or_raise, sql_literal, safe_identifier,
    format_snowflake_error,
    run_compatibility_checks,
    build_cost_formula_audit, filter_existing_columns, build_task_history_sql,
    admin_button_disabled,
    log_admin_action,
    show_to_df, first_existing_column, ensure_column_alias,
    scope_warehouse_names, scope_metadata_df, load_task_inventory,
    load_live_task_runs, load_database_options, load_schema_options,
    load_warehouse_inventory, build_unclassified_assets_sql,
    safe_float, safe_int, render_ranked_bar_chart,
    render_chart_with_data_toggle,
    defer_source_note,
    build_schema_migration_contract, build_schema_migration_status_sql,
)
from config import (
    ALERT_DB, ALERT_SCHEMA, ALERT_TABLE,
    ACTION_QUEUE_TABLE,
)
from sections.navigation import apply_navigation_state
from utils.dba_tool_catalog import (
    DBA_TOOL_FOCUS_GROUPS,
    DBA_TOOL_FOCUS_HINTS,
    DBA_TOOL_GROUPS,
    SCALE_OPTS as _SCALE_OPTS,
    SIZE_OPTS as _SIZE_OPTS,
    SIZE_SQL as _SIZE_SQL,
    TASK_GRAPH_CONTROL_PANES,
    WH_PARAM_HELP as _WH_PARAM_HELP,
)
from utils.workflows import render_priority_dataframe, render_workflow_selector
from sections.shell_helpers import render_shell_snapshot
from sections.shell_helpers import render_setup_health_board

from sections.dba_tools_contracts import (
    ACCOUNT_PARAMETER_ADMIN_ROLES,
    DATA_COMPARE_EXECUTION_STAGES,
    SCHEMA_COMPARE_OBJECT_COVERAGE,
)
from sections.dba_tools_common import (
    _as_bool,
    _as_int,
    _current_role_allows_alter_account,
    _ensure_column_alias,
    _first_existing_column,
    _load_button,
    _load_task_inventory,
    _prioritize_query_context,
    _qualified_name,
    _query_context_expr,
    _quote_identifier,
    _require_typed_confirmation,
    _scope_metadata_df,
    _scope_warehouse_names,
    _select_option,
    _show_to_df,
    _task_history_sql,
    _typed_confirmation,
)
from sections.dba_tools_data_compare import (
    _build_data_compare_plan,
    _data_compare_bucket_sql,
    _data_compare_column_rows,
    _data_compare_column_signature,
    _data_compare_extract_summary,
    _data_compare_forensic_sql,
    _data_compare_hash_sql,
    _data_compare_normalize_tables,
    _data_compare_outcome,
    _data_compare_parse_identifiers,
    _data_compare_persistence_sql,
    _data_compare_supported_hash_column,
    _data_compare_tables_sql,
    _data_compare_where_clause,
    _recon_config_insert_sql,
    _recon_history_sql,
    _sql_number_expr,
)
from sections.dba_tools_schema_compare import (
    _build_schema_compare_frame,
    _first_present_column,
    _schema_compare_columns_sql,
    _schema_compare_coverage_label,
    _schema_compare_column_type,
    _schema_compare_ddl_script,
    _schema_compare_fetch_missing_ddl_statements,
    _schema_compare_get_ddl_type,
    _schema_compare_inventory,
    _schema_compare_missing_column_ddl,
    _schema_compare_missing_ddl,
    _schema_compare_normalize_columns,
    _schema_compare_normalize_kind,
    _schema_compare_normalize_show_objects,
    _schema_compare_numeric_text,
    _schema_compare_object_fqn,
    _schema_compare_persistence_sql,
    _schema_compare_show_objects_sql,
)
from sections.dba_tools_setup import (
    _setup_status_df,
    _table_exists,
    _task_exists,
)
from sections.dba_tools_warehouse_settings import (
    _build_warehouse_setting_plan,
    _is_unknown_setting,
    _normalize_warehouse_setting,
    _warehouse_setting_review_gate,
    _warehouse_setting_risk,
    _warehouse_settings_preflight_sql,
    _warehouse_size_sql,
)
from sections.dba_tools_data_compare_view import (
    _render_data_compare_command_model,
    render_data_compare_tool,
)
from sections.dba_tools_schema_compare_view import (
    _render_schema_compare_command_model,
    render_schema_compare_tool,
)
from sections.dba_tools_warehouse_settings_view import render_warehouse_settings_tool
from sections.dba_tools_qas_monitor_view import render_qas_monitor_tool
from sections.dba_tools_cost_health_view import (
    render_cost_formula_audit_tool,
    render_data_health_tool,
    render_serverless_costs_tool,
    render_summary_status_tool,
)
from sections.dba_tools_data_movement_view import (
    render_data_loading_tool,
    render_dynamic_tables_tool,
    render_replication_tool,
    render_snowpipe_monitor_tool,
)
from sections.dba_tools_object_monitoring_view import (
    render_network_sessions_tool,
    render_recent_objects_tool,
    render_unused_objects_tool,
)


DBA_TOOL_RENDERERS = {
    "Warehouse Settings": render_warehouse_settings_tool,
    "QAS Monitor": render_qas_monitor_tool,
    "Data Loading": render_data_loading_tool,
    "Snowpipe Monitor": render_snowpipe_monitor_tool,
    "Dynamic Tables": render_dynamic_tables_tool,
    "Replication": render_replication_tool,
    "Network & Sessions": render_network_sessions_tool,
    "Unused Objects": render_unused_objects_tool,
    "Schema Compare": render_schema_compare_tool,
    "Data Compare": render_data_compare_tool,
    "Recent Objects": render_recent_objects_tool,
    "Summary Status": render_summary_status_tool,
    "Serverless Costs": render_serverless_costs_tool,
    "Cost Formula Audit": render_cost_formula_audit_tool,
    "Data Health": render_data_health_tool,
}

INLINE_DBA_TOOL_HANDLERS = frozenset({
    "Query Kill List",
    "Cortex AI Limits",
    "Task Graph Control",
})



































def render():
    session = get_session()
    company = get_active_company()

    focus = st.session_state.get("dba_tools_focus")
    default_group = DBA_TOOL_FOCUS_GROUPS.get(str(focus), "Warehouse Ops")
    group_names = list(DBA_TOOL_GROUPS)
    focus_tool = str(st.session_state.get("dba_tools_focus_tool") or "")
    focus_tool_active = (
        focus_tool
        and default_group in DBA_TOOL_GROUPS
        and focus_tool in DBA_TOOL_GROUPS[default_group]
    )
    if focus_tool_active:
        selected_group = default_group
        tool_options = DBA_TOOL_GROUPS[selected_group]
        selected_tool = focus_tool
        focus_hint = DBA_TOOL_FOCUS_HINTS.get(
            str(focus),
            "Use the matching workflow when you need additional DBA tools.",
        )
        st.caption(f"Workflow focus: {selected_tool}. {focus_hint}")
    else:
        st.caption(
            "Guarded admin workflows are grouped to keep the high-value controls easy to find. "
            "Open a group, then choose the specific operation."
        )
        if focus:
            focus_hint = DBA_TOOL_FOCUS_HINTS.get(
                str(focus),
                "Use the matching tab group below first; other tools remain available when needed.",
            )
            st.info(f"Security Monitoring focus: {focus}. {focus_hint}")
        with st.expander("Guarded Admin Operating Model", expanded=not bool(focus)):
            risk_a, risk_b, risk_c = st.columns(3)
            with risk_a:
                st.info(
                    "Safe Observability\n\n"
                    "Read-only inventory, diagnostics, compatibility checks, schema compare, recent objects, "
                    "QAS visibility, replication, serverless costs, and action history."
                )
            with risk_b:
                st.warning(
                    "Controlled Actions\n\n"
                    "Query cancellation, task suspend/resume, warehouse setting changes, and Cortex limit updates. "
                    "These remain guarded by typed confirmation and Snowflake privileges."
                )
            with risk_c:
                st.success(
                    "Readiness and Audit\n\n"
                    "Compatibility checks, data readiness, action queue routing, and "
                    "formula audit evidence stay available without exposing deployment plumbing."
                )
        if "dba_tools_group_selector" not in st.session_state and default_group in group_names:
            st.session_state["dba_tools_group_selector"] = default_group
        selected_group = render_workflow_selector(
            "DBA workflow",
            "dba_tools_group_selector",
            group_names,
            columns=3,
            show_label=True,
        )
        tool_options = DBA_TOOL_GROUPS[selected_group]
        selected_tool = st.selectbox(
            "Open specialist tool",
            tool_options,
            key=f"dba_tools_tool_selector_{selected_group}",
        )
        st.info("Alert history, email-ready delivery rows, routing, and suppression windows now live in the consolidated Alert Center.")
        if st.button("Open Alert Center", key="dba_tools_open_alert_center"):
            apply_navigation_state("Alert Center")
            st.rerun()

    st.divider()
    if not focus_tool_active:
        st.caption(
            "Focused mode renders one specialist tool at a time. Use the workflow hubs for daily operations; "
            "use this page when you need a specific admin utility."
        )

    renderer = DBA_TOOL_RENDERERS.get(selected_tool)
    if renderer is not None:
        renderer(session, company)
        return

    qh_cols = set()
    if selected_tool in {"Query Kill List", "Task Graph Control"}:
        qh_cols = set(filter_existing_columns(
            session,
            "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
            [
                "WAREHOUSE_SIZE",
                "QUERY_TAG",
            ],
        ))
    qh_warehouse_size_expr = (
        "warehouse_size AS warehouse_size"
        if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"
    )
    qh_query_tag_expr = (
        "query_tag AS query_tag"
        if "QUERY_TAG" in qh_cols else "NULL::VARCHAR AS query_tag"
    )
    qh_task_indicator = (
        "query_tag IS NOT NULL OR LOWER(query_text) LIKE '%execute task%'"
        if "QUERY_TAG" in qh_cols else "LOWER(query_text) LIKE '%execute task%'"
    )

    # -- TAB 0: QUERY KILL LIST ------------------------------------------------
    if selected_tool == "Query Kill List":
        st.subheader("Long-Running Query Kill List")
        kill_min = st.number_input("Flag queries running > (seconds)", 60, 3600, 300, key="kill_sec")
        if _load_button("Load Kill List", "kl_load"):
            try:
                df = run_query_or_raise(f"""
                    SELECT query_id, user_name, warehouse_name, {qh_warehouse_size_expr}, execution_status, start_time,
                           DATEDIFF('second', start_time, COALESCE(end_time, CURRENT_TIMESTAMP())) AS elapsed_sec,
                           SUBSTR(query_text,1,500) AS query_text
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('hours', -2, CURRENT_TIMESTAMP())
                      AND UPPER(execution_status) IN ('RUNNING','QUEUED','BLOCKED')
                      AND DATEDIFF('second', start_time, COALESCE(end_time, CURRENT_TIMESTAMP())) > {kill_min}
                      {get_wh_filter_clause("warehouse_name")}
                    ORDER BY elapsed_sec DESC
                    LIMIT 500
                """)
                st.session_state["dba_df_kl"] = df
            except Exception as e:
                st.session_state["dba_df_kl"] = pd.DataFrame()
                st.caption(f"Query activity unavailable: {format_snowflake_error(e)}")

        if st.session_state.get("dba_df_kl") is not None and not st.session_state["dba_df_kl"].empty:
            df = st.session_state["dba_df_kl"]
            st.warning(f"{len(df)} queries running > {kill_min}s")
            render_priority_dataframe(
                df,
                title="Queries eligible for cancellation",
                priority_columns=[
                    "QUERY_ID", "USER_NAME", "WAREHOUSE_NAME", "WAREHOUSE_SIZE",
                    "EXECUTION_STATUS", "START_TIME", "ELAPSED_SEC", "QUERY_TEXT",
                ],
                sort_by=["ELAPSED_SEC", "START_TIME"],
                ascending=[False, False],
                raw_label="All kill-list query rows",
            )
            kill_id = st.selectbox("Kill query ID", df["QUERY_ID"].tolist(), key="kl_sel")
            kill_confirmed = _typed_confirmation(
                "Type CANCEL to enable query cancellation",
                "CANCEL",
                f"kl_confirm_{kill_id}",
            ) if kill_id else False
            if kill_id and st.button(
                "Cancel Query",
                type="primary",
                key="kl_kill",
                disabled=admin_button_disabled(),
            ):
                if _require_typed_confirmation(kill_confirmed, "CANCEL"):
                    try:
                        session.sql(f"SELECT SYSTEM$CANCEL_QUERY({sql_literal(kill_id)})").collect()
                        st.success(f"Cancel sent for `{kill_id}`")
                    except Exception as e:
                        st.error(f"Cancel failed: {format_snowflake_error(e)}")
        elif st.session_state.get("dba_df_kl") is not None:
            st.success(f"No queries running > {kill_min}s")

    # -- TAB 1: WAREHOUSE SETTINGS MANAGER ------------------------------------

    # -- TAB 2: DATA LOADING ---------------------------------------------------

    # -- TABS 3-13: CARRIED FORWARD (abbreviated for file size) ---------------











    # -- TAB 14: CORTEX AI LIMITS ----------------------------------------------
    if selected_tool == "Cortex AI Limits":
        st.subheader("Cortex AI Limits")
        st.caption(
            "View and modify Cortex AI service limits for your account. "
            "These control daily token thresholds, inference rate limits, and Cortex Search/Analyst access. "
            "Requires ACCOUNTADMIN or SYSADMIN with MODIFY ACCOUNT privilege."
        )

        # -- Current parameters ------------------------------------------------
        if st.button("Load Current AI Parameters", key="cortex_params_load"):
            results = {}

            # SHOW PARAMETERS - account-level Cortex controls
            try:
                df_params = run_query_or_raise("SHOW PARAMETERS LIKE '%CORTEX%' IN ACCOUNT")
                results["cortex_params"] = df_params
            except Exception as e:
                results["cortex_params"] = pd.DataFrame()
                st.caption(f"Account parameters unavailable: {format_snowflake_error(e)}")

            # Also check AI_SERVICES parameters
            try:
                df_ai = run_query_or_raise("SHOW PARAMETERS LIKE '%AI%' IN ACCOUNT")
                results["ai_params"] = df_ai
            except Exception:
                results["ai_params"] = pd.DataFrame()

            # Cortex usage today
            try:
                df_usage = run_query("""
                    WITH combined AS (
                        SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, TOKENS
                        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
                        WHERE USAGE_TIME >= CURRENT_DATE()
                        UNION ALL
                        SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, TOKENS
                        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
                        WHERE USAGE_TIME >= CURRENT_DATE()
                    )
                    SELECT COUNT(*) AS requests_today,
                           SUM(TOKEN_CREDITS) AS credits_today,
                           SUM(TOKENS)        AS tokens_today,
                           COUNT(DISTINCT USER_ID) AS active_users
                    FROM combined
                """, ttl_key=f"dba_cortex_usage_today_{company}", tier="live")
                results["usage_today"] = df_usage
            except Exception:
                results["usage_today"] = pd.DataFrame()

            st.session_state["dba_cortex_results"] = results

        res = st.session_state.get("dba_cortex_results", {})

        # Today's usage summary
        df_u = res.get("usage_today", pd.DataFrame())
        if not df_u.empty:
            st.subheader("Today's Cortex Usage")
            render_shell_snapshot((
                ("Requests Today", f"{safe_int(df_u['REQUESTS_TODAY'].iloc[0]):,}"),
                ("AI Credits Today", f"{safe_float(df_u['CREDITS_TODAY'].iloc[0]):.4f}"),
                ("Tokens Today", f"{safe_int(df_u['TOKENS_TODAY'].iloc[0]):,}"),
                ("Active Users", f"{safe_int(df_u['ACTIVE_USERS'].iloc[0])}"),
            ))

        # Current parameters
        df_cp = res.get("cortex_params", pd.DataFrame())
        df_ai = res.get("ai_params",     pd.DataFrame())

        combined_params = pd.concat([df_cp, df_ai], ignore_index=True) if not df_cp.empty or not df_ai.empty else pd.DataFrame()
        if not combined_params.empty:
            st.subheader("Current Cortex / AI Account Parameters")
            render_priority_dataframe(
                combined_params,
                title="Cortex / AI account parameters",
                priority_columns=[
                    "key", "value", "default", "level", "description",
                    "KEY", "VALUE", "DEFAULT", "LEVEL", "DESCRIPTION",
                ],
                sort_by=["KEY", "key"],
                ascending=True,
                raw_label="All Cortex account parameters",
            )
            download_csv(combined_params, "cortex_account_params.csv")
        else:
            st.info(
                "No Cortex parameters returned from SHOW PARAMETERS. "
                "This usually means Cortex AI features are not yet enabled on this account, "
                "or the current role doesn't have SHOW PARAMETERS privilege on ACCOUNT."
            )

        st.divider()

        # -- Modify parameters -------------------------------------------------
        st.subheader("Modify Cortex AI Account Parameters")
        st.caption(
            "Only account parameters returned by Snowflake can be applied here. "
            "Cortex Search, Analyst, and Intelligence access are managed through feature availability, "
            "roles, databases, services, and Snowflake readiness evidence rather than generic account toggles."
        )

        with st.expander("Set Cortex Code quota", expanded=True):
            cortex_daily_limit = st.number_input(
                "CORTEX_CODE_DAILY_CREDIT_LIMIT",
                min_value=0, max_value=100000, value=0, step=100,
                key="cortex_daily_limit",
                help="Maximum Cortex Code credits per day across all users. Use 0 to skip SQL generation.",
            )
            generated_sql = (
                "-- Cortex Code quota\n"
                "-- Run as ACCOUNTADMIN\n"
                f"ALTER ACCOUNT SET CORTEX_CODE_DAILY_CREDIT_LIMIT = {int(cortex_daily_limit)};"
                if cortex_daily_limit > 0
                else (
                    "-- Cortex Code quota\n"
                    "-- No ALTER ACCOUNT statement generated. Set a positive daily limit to generate quota SQL."
                )
            )

            readiness_rows = pd.DataFrame([
                {
                    "CAPABILITY": "Cortex Code",
                    "DASHBOARD_ACTION": "Set daily account credit limit",
                    "READINESS_PATH": "Account parameter when available in SHOW PARAMETERS",
                },
                {
                    "CAPABILITY": "Cortex Search",
                    "DASHBOARD_ACTION": "Review grants and service objects",
                    "READINESS_PATH": "Create/search service readiness and role grants outside generic account parameters",
                },
                {
                    "CAPABILITY": "Cortex Analyst / Intelligence",
                    "DASHBOARD_ACTION": "Review semantic model, object grants, and approved roles",
                    "READINESS_PATH": "Feature and object readiness outside generic account parameters",
                },
            ])
            render_priority_dataframe(
                readiness_rows,
                title="Cortex feature readiness guidance",
                priority_columns=["CAPABILITY", "DASHBOARD_ACTION", "READINESS_PATH"],
                raw_label="All Cortex readiness guidance",
            )

            col_apply, col_dl = st.columns([1, 2])
            with col_apply:
                cortex_confirmed = _typed_confirmation(
                    "Type APPLY to enable account parameter changes",
                    "APPLY",
                    "cortex_apply_confirm",
                )
                if st.button("Apply Limit", type="primary", key="cortex_apply", disabled=admin_button_disabled()):
                    if _require_typed_confirmation(cortex_confirmed, "APPLY"):
                        if cortex_daily_limit <= 0:
                            st.info("Set a positive Cortex Code daily credit limit before applying.")
                            st.stop()
                        # CALLER MODE GUARD: ALTER ACCOUNT SET requires ACCOUNTADMIN.
                        # Since execute_as=CALLER, the caller's role must have this privilege.
                        # SNOW_SYSADMINS cannot run ALTER ACCOUNT; keep this blocked
                        # before Snowflake receives account-level parameter SQL.
                        _caller_role = str(st.session_state.get("_overwatch_current_role", "") or "").strip()
                        if not _current_role_allows_alter_account(_caller_role):
                            st.error(
                                f"ALTER ACCOUNT requires ACCOUNTADMIN. "
                                f"Your current role is `{_caller_role or 'unknown'}`. "
                                f"Switch to ACCOUNTADMIN in Snowflake and reload OVERWATCH, "
                                f"or ask an ACCOUNTADMIN owner to apply the approved account parameter change."
                            )
                        else:
                            applied = []
                            failed  = []
                            for stmt in [f"ALTER ACCOUNT SET CORTEX_CODE_DAILY_CREDIT_LIMIT = {int(cortex_daily_limit)}"]:
                                try:
                                    session.sql(stmt).collect()
                                    applied.append(stmt)
                                except Exception as e:
                                    failed.append(f"{stmt} -> {format_snowflake_error(e)}")

                            if applied:
                                st.success(f"{len(applied)} parameter(s) updated successfully.")
                            if failed:
                                for f_msg in failed:
                                    st.warning(f"{f_msg}")
                                st.info("Check SHOW PARAMETERS IN ACCOUNT and confirm the current role can modify account parameters.")
            with col_dl:
                render_shell_snapshot((
                    ("Account limit", "Status review"),
                    ("Apply path", "reviewed workflow"),
                    ("Rollback", "Runbook only"),
                    ("Telemetry", "Parameter review"),
                ))

        # -- Per-user Cortex policy (Enterprise) -------------------------------
        st.divider()
        st.subheader("Per-User / Per-Role Cortex Access and Quotas")
        st.caption(
            "Use shared AI spend thresholds and route Cortex access through a controlled role "
            "when per-user monthly quota enforcement is required."
        )
        st.info(
            "Tip: To enforce user quotas, revoke the blanket `SNOWFLAKE.CORTEX_USER` grant from PUBLIC, "
            "grant it only through an approved AI role, then use OVERWATCH to queue revoke/restore review."
        )
        with st.expander("Cortex access control status"):
            render_shell_snapshot((
                ("Approved AI role", "Required"),
                ("PUBLIC access", "Review"),
                ("Quota enforcement", "Dry-run first"),
                ("Parameter review", "On demand"),
            ))

    # -- TAB 15: TASK GRAPH CONTROL --------------------------------------------
    if selected_tool == "Task Graph Control":
        st.subheader("Task Graph Control")
        st.caption(
            "Cancel running queries spawned by tasks, cancel task graphs mid-run, "
            "suspend/resume individual tasks or entire DAG trees, and restart failed tasks. "
            "Requires OPERATE privilege on tasks or ACCOUNTADMIN."
        )

        task_graph_view = render_workflow_selector(
            "Task graph control view",
            "dba_task_graph_control_view",
            TASK_GRAPH_CONTROL_PANES,
            columns=3,
            show_label=True,
        )

        # -- Running task queries -----------------------------------------------
        if task_graph_view == "Running Task Queries":
            st.subheader("Queries Currently Running Under a Task")
            st.caption(
                "Shows recent ACCOUNT_USAGE query activity where QUERY_TAG or query text "
                "indicates task execution. You can cancel individual task-spawned queries here."
            )
            if st.button("Load Running Task Queries", key="tg_run_load"):
                try:
                    df_tq = run_query_or_raise(f"""
                        SELECT query_id, database_name, schema_name, {_query_context_expr()},
                               user_name, warehouse_name, {qh_warehouse_size_expr}, execution_status,
                               start_time,
                               DATEDIFF('second', start_time, COALESCE(end_time, CURRENT_TIMESTAMP())) AS elapsed_sec,
                               {qh_query_tag_expr},
                               SUBSTR(query_text, 1, 400) AS query_text
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                        WHERE start_time >= DATEADD('hours', -2, CURRENT_TIMESTAMP())
                          AND UPPER(execution_status) IN ('RUNNING','QUEUED','BLOCKED')
                          {get_wh_filter_clause("warehouse_name")}
                          {get_user_company_filter_clause("user_name", company)}
                          AND ({qh_task_indicator})
                        ORDER BY start_time DESC
                        LIMIT 200
                    """)
                    df_tq = _prioritize_query_context(df_tq)
                    st.session_state["dba_df_tg_running"] = df_tq
                except Exception as e:
                    st.info(f"Task query activity is unavailable in this role/context: {format_snowflake_error(e)}")
                    st.session_state["dba_df_tg_running"] = pd.DataFrame()

            if st.session_state.get("dba_df_tg_running") is not None:
                df_tq = st.session_state["dba_df_tg_running"]
                if not df_tq.empty:
                    render_priority_dataframe(
                        df_tq,
                        title="Running task-spawned queries",
                        priority_columns=[
                            "QUERY_ID", "QUERY_CONTEXT", "DATABASE_NAME", "SCHEMA_NAME",
                            "USER_NAME", "WAREHOUSE_NAME", "WAREHOUSE_SIZE",
                            "EXECUTION_STATUS", "START_TIME", "ELAPSED_SEC",
                            "QUERY_TAG", "QUERY_TEXT",
                        ],
                        sort_by=["ELAPSED_SEC", "START_TIME"],
                        ascending=[False, False],
                        raw_label="All running task query rows",
                    )
                    cancel_qid = st.selectbox(
                        "Cancel query",
                        df_tq["QUERY_ID"].tolist(),
                        key="tg_cancel_qid_sel",
                    )
                    cancel_confirmed = _typed_confirmation(
                        "Type CANCEL to enable task-query cancellation",
                        "CANCEL",
                        f"tg_cancel_confirm_{cancel_qid}",
                    ) if cancel_qid else False
                    if cancel_qid and st.button(
                        "Cancel This Query",
                        type="primary",
                        key="tg_cancel_q",
                        disabled=admin_button_disabled(),
                    ):
                        if _require_typed_confirmation(cancel_confirmed, "CANCEL"):
                            try:
                                session.sql(f"SELECT SYSTEM$CANCEL_QUERY({sql_literal(cancel_qid)})").collect()
                                st.success(f"Cancel sent for `{cancel_qid}`")
                            except Exception as e:
                                st.error(f"Cancel failed: {format_snowflake_error(e)}")
                else:
                    st.success("No task-related queries currently running.")

        # -- Cancel graph / task ------------------------------------------------
        elif task_graph_view == "Cancel Graph / Task":
            st.subheader("Cancel a Running Task Graph or Individual Task Run")
            st.caption(
                "`SYSTEM$CANCEL_TASK_GRAPH(graph_run_id)` cancels an entire DAG run in progress. "
                "`SYSTEM$CANCEL_QUERY(query_id)` cancels the query spawned by a specific task run."
            )

            # Load recent task runs to get graph_run_id
            if st.button("Load Recent Task Runs", key="tg_runs_load"):
                try:
                    df_tasks = _load_task_inventory(session, force_refresh=True)
                    df_runs = load_live_task_runs(session, df_tasks, hours_back=6)
                    if df_runs.empty:
                        df_runs = run_query_or_raise(_task_history_sql(
                            session,
                            "scheduled_time >= DATEADD('hours', -6, CURRENT_TIMESTAMP())",
                            limit=200,
                        ))
                    st.session_state["dba_df_task_runs"] = df_runs
                except Exception as e:
                    st.warning(f"Task run history unavailable: {format_snowflake_error(e)}")

            if st.session_state.get("dba_df_task_runs") is not None and not st.session_state["dba_df_task_runs"].empty:
                df_r = st.session_state["dba_df_task_runs"]

                # Filter to running only
                running_runs = df_r[df_r["STATE"].isin(["EXECUTING","RUNNING"])] if "STATE" in df_r.columns else pd.DataFrame()

                if not running_runs.empty:
                    st.warning(f"{len(running_runs)} task run(s) currently executing or scheduled.")
                    render_priority_dataframe(
                        running_runs,
                        title="Running or scheduled task runs",
                        priority_columns=[
                            "DATABASE_NAME", "SCHEMA_NAME", "NAME", "STATE",
                            "SCHEDULED_TIME", "QUERY_ID", "GRAPH_RUN_GROUP_ID",
                            "DURATION_SEC", "ERROR_MESSAGE",
                        ],
                        sort_by=["SCHEDULED_TIME", "DURATION_SEC"],
                        ascending=[False, False],
                        raw_label="All active task run rows",
                    )

                    # Cancel by graph run group
                    st.markdown("**Cancel by Graph Run Group ID** (cancels all tasks in that DAG run)")
                    if "GRAPH_RUN_GROUP_ID" in running_runs.columns:
                        graph_ids = running_runs["GRAPH_RUN_GROUP_ID"].dropna().unique().tolist()
                        if graph_ids:
                            sel_graph = st.selectbox(
                                "Select Graph Run Group ID to cancel",
                                graph_ids,
                                key="tg_cancel_graph_sel",
                            )
                            col_cg1, col_cg2 = st.columns([1,3])
                            with col_cg1:
                                with st.form(f"tg_cancel_graph_form_{sel_graph}"):
                                    graph_confirm_text = st.text_input(
                                        "Type CANCEL to enable graph cancellation",
                                        key=f"tg_graph_confirm_{sel_graph}",
                                        placeholder="CANCEL",
                                    )
                                    submitted = st.form_submit_button(
                                        "Cancel Graph Run",
                                        type="primary",
                                        disabled=admin_button_disabled(),
                                    )
                                if submitted:
                                    graph_confirmed = str(graph_confirm_text or "").strip() == "CANCEL"
                                    if _require_typed_confirmation(graph_confirmed, "CANCEL"):
                                        try:
                                            session.sql(
                                                f"SELECT SYSTEM$CANCEL_TASK_GRAPH({sql_literal(str(sel_graph))})"
                                            ).collect()
                                            st.success(f"Graph run `{sel_graph}` cancelled.")
                                            st.session_state.pop("dba_df_task_runs", None)
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Cancel graph failed: {format_snowflake_error(e)}")
                                            st.info(
                                                "SYSTEM$CANCEL_TASK_GRAPH requires the task to be running and the caller to have "
                                                "OPERATE privilege on the root task, or ACCOUNTADMIN."
                                            )

                    # Cancel individual query from a task run
                    st.markdown("**Cancel individual task run query**")
                    if "QUERY_ID" in running_runs.columns:
                        query_ids = running_runs["QUERY_ID"].dropna().unique().tolist()
                        if query_ids:
                            sel_qid = st.selectbox("Select Query ID", query_ids, key="tg_cancel_run_qid")
                            with st.form(f"tg_cancel_run_query_form_{sel_qid}"):
                                run_confirm_text = st.text_input(
                                    "Type CANCEL to enable run-query cancellation",
                                    key=f"tg_run_confirm_{sel_qid}",
                                    placeholder="CANCEL",
                                )
                                submitted = st.form_submit_button(
                                    "Cancel Query",
                                    disabled=admin_button_disabled(),
                                )
                            if sel_qid and submitted:
                                run_confirmed = str(run_confirm_text or "").strip() == "CANCEL"
                                if _require_typed_confirmation(run_confirmed, "CANCEL"):
                                    try:
                                        session.sql(f"SELECT SYSTEM$CANCEL_QUERY({sql_literal(str(sel_qid))})").collect()
                                        st.success(f"Cancel sent for `{sel_qid}`")
                                    except Exception as e:
                                        st.error(f"Cancel failed: {format_snowflake_error(e)}")
                else:
                    st.success("No task runs currently executing.")
                    st.subheader("Recent History (last 6h)")
                    render_priority_dataframe(
                        df_r,
                        title="Recent task run history",
                        priority_columns=[
                            "DATABASE_NAME", "SCHEMA_NAME", "NAME", "STATE",
                            "SCHEDULED_TIME", "COMPLETED_TIME", "DURATION_SEC",
                            "QUERY_ID", "ERROR_MESSAGE",
                        ],
                        sort_by=["SCHEDULED_TIME"],
                        ascending=False,
                        max_rows=50,
                        raw_label="All recent task run rows",
                    )

        # -- Suspend / Resume --------------------------------------------------
        elif task_graph_view == "Suspend / Resume":
            st.subheader("Suspend / Resume Tasks and DAG Trees")
            st.caption(
                "Suspend or resume individual tasks or entire DAG hierarchies. "
                "Suspending a root task stops the whole graph from scheduling. "
                "Suspending a child task pauses that branch only."
            )

            # Load task list for selection
            if st.button("Load Task List", key="tg_mgmt_load"):
                try:
                    df_tasks = _load_task_inventory(session, force_refresh=True)
                    st.session_state["dba_df_tg_tasks"] = df_tasks
                except Exception as e:
                    st.warning(f"Task inventory unavailable: {format_snowflake_error(e)}")

            df_tasks = st.session_state.get("dba_df_tg_tasks", pd.DataFrame())
            if not df_tasks.empty:
                # Metrics
                started   = df_tasks[df_tasks["STATE"] == "started"]  if "STATE" in df_tasks.columns else pd.DataFrame()
                suspended = df_tasks[df_tasks["STATE"] == "suspended"] if "STATE" in df_tasks.columns else pd.DataFrame()
                render_shell_snapshot((
                    ("Total Tasks", f"{len(df_tasks):,}"),
                    ("Active", f"{len(started):,}"),
                    ("Suspended", f"{len(suspended):,}"),
                ))

                task_display_cols = (
                    ["NAME", "DATABASE_NAME", "SCHEMA_NAME", "STATE", "SCHEDULE", "WAREHOUSE"]
                    if all(c in df_tasks.columns for c in ["NAME", "DATABASE_NAME", "SCHEMA_NAME", "STATE", "SCHEDULE", "WAREHOUSE"])
                    else df_tasks.columns.tolist()
                )
                render_priority_dataframe(
                    df_tasks[task_display_cols],
                    title="Task inventory by operational state",
                    priority_columns=task_display_cols,
                    sort_by=["STATE", "DATABASE_NAME", "SCHEMA_NAME", "NAME"],
                    ascending=[True, True, True, True],
                    raw_label="All task inventory rows",
                    height=250,
                )

                st.divider()

                # Single task control
                st.subheader("Control Individual Task")
                task_names = df_tasks["NAME"].unique().tolist() if "NAME" in df_tasks.columns else []
                sel_task   = st.selectbox("Select task", task_names, key="tg_mgmt_sel")

                if sel_task:
                    task_row = df_tasks[df_tasks["NAME"] == sel_task].iloc[0]
                    db_n   = task_row.get("DATABASE_NAME","")
                    sch_n  = task_row.get("SCHEMA_NAME","")
                    state  = task_row.get("STATE","")
                    full_n = _qualified_name(db_n, sch_n, sel_task)
                    preds  = task_row.get("PREDECESSORS","")

                    st.info(f"`{full_n}` | State: **{state}** | Predecessors: `{preds or 'none (root task)'}`")
                    task_confirmed = _typed_confirmation(
                        "Type the task name to enable task controls",
                        sel_task,
                        f"tg_confirm_{sel_task}",
                    )

                    col_s1, col_s2, col_s3, col_s4 = st.columns(4)

                    with col_s1:
                        if st.button("Suspend", key="tg_suspend", disabled=admin_button_disabled(state=="suspended")):
                            if _require_typed_confirmation(task_confirmed, sel_task):
                                try:
                                    session.sql(f"ALTER TASK {full_n} SUSPEND").collect()
                                    st.success(f"`{sel_task}` suspended.")
                                    st.session_state.pop("dba_df_tg_tasks", None)
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Suspend failed: {format_snowflake_error(e)}")

                    with col_s2:
                        if st.button("Resume", key="tg_resume", disabled=admin_button_disabled(state=="started")):
                            if _require_typed_confirmation(task_confirmed, sel_task):
                                try:
                                    session.sql(f"ALTER TASK {full_n} RESUME").collect()
                                    st.success(f"`{sel_task}` resumed.")
                                    st.session_state.pop("dba_df_tg_tasks", None)
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Resume failed: {format_snowflake_error(e)}")

                    with col_s3:
                        if st.button("Execute Now", key="tg_execute", disabled=admin_button_disabled()):
                            if _require_typed_confirmation(task_confirmed, sel_task):
                                try:
                                    session.sql(f"EXECUTE TASK {full_n}").collect()
                                    st.success(f"`{sel_task}` triggered.")
                                except Exception as e:
                                    st.error(f"Execute failed: {format_snowflake_error(e)}")

                    with col_s4:
                        if st.button("Retry Last Failed", key="tg_retry", disabled=admin_button_disabled()):
                            # EXECUTE TASK WITH LAST_ERROR retry pattern
                            if _require_typed_confirmation(task_confirmed, sel_task):
                                try:
                                    session.sql(f"EXECUTE TASK {full_n}").collect()
                                    st.success(f"Retry triggered for `{sel_task}`.")
                                    st.caption(
                                        "Note: Snowflake does not have a native RETRY_LAST_FAILED command. "
                                        "This re-executes the task immediately. "
                                        "For DAG-level retry, use EXECUTE TASK on the root task."
                                    )
                                except Exception as e:
                                    st.error(f"Retry failed: {format_snowflake_error(e)}")

                st.divider()

                # Bulk suspend/resume entire DAG tree
                st.subheader("Bulk Suspend / Resume Entire DAG Tree")
                st.caption(
                    "Suspending the root task stops the entire graph from scheduling. "
                    "Select a root task (one with no predecessors) below."
                )
                root_tasks = df_tasks[
                    df_tasks.get("PREDECESSORS", pd.Series()).astype(str).str.strip().isin(["","[]","None","nan"])
                ] if "PREDECESSORS" in df_tasks.columns else df_tasks

                if not root_tasks.empty:
                    root_names = root_tasks["NAME"].unique().tolist() if "NAME" in root_tasks.columns else []
                    sel_root   = st.selectbox("Select root task (suspends entire graph)", root_names, key="tg_root_sel")

                    if sel_root:
                        root_row  = df_tasks[df_tasks["NAME"] == sel_root].iloc[0]
                        root_full = _qualified_name(
                            root_row.get("DATABASE_NAME", ""),
                            root_row.get("SCHEMA_NAME", ""),
                            sel_root,
                        )

                        # Find all children
                        children = df_tasks[
                            df_tasks.get("PREDECESSORS","").astype(str).str.contains(sel_root, na=False)
                        ] if "PREDECESSORS" in df_tasks.columns else pd.DataFrame()

                        st.info(
                            f"Root: `{root_full}` | "
                            f"Child tasks in this graph: {len(children)} | "
                            f"Total tasks affected: {len(children)+1}"
                        )
                        graph_confirmed = _typed_confirmation(
                            "Type the root task name to enable graph controls",
                            sel_root,
                            f"tg_graph_confirm_{sel_root}",
                        )

                        b1, b2 = st.columns(2)
                        with b1:
                            if st.button("Suspend Entire Graph", type="primary", key="tg_bulk_suspend", disabled=admin_button_disabled()):
                                if _require_typed_confirmation(graph_confirmed, sel_root):
                                    try:
                                        session.sql(f"ALTER TASK {root_full} SUSPEND").collect()
                                        st.success(f"Root task `{sel_root}` suspended - entire graph will stop scheduling.")
                                        st.session_state.pop("dba_df_tg_tasks", None)
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Suspend failed: {format_snowflake_error(e)}")
                        with b2:
                            if st.button("Resume Entire Graph", type="primary", key="tg_bulk_resume", disabled=admin_button_disabled()):
                                if _require_typed_confirmation(graph_confirmed, sel_root):
                                    errors_seen = []
                                    # Resume children first, then root
                                    for _, child in children.iterrows():
                                        full_child = _qualified_name(
                                            child.get("DATABASE_NAME", ""),
                                            child.get("SCHEMA_NAME", ""),
                                            child.get("NAME", ""),
                                        )
                                        try:
                                            session.sql(f"ALTER TASK {full_child} RESUME").collect()
                                        except Exception as e:
                                            errors_seen.append(f"{full_child}: {format_snowflake_error(e)}")
                                    try:
                                        session.sql(f"ALTER TASK {root_full} RESUME").collect()
                                    except Exception as e:
                                        errors_seen.append(f"{root_full}: {format_snowflake_error(e)}")

                                    if errors_seen:
                                        st.warning(f"Resumed with {len(errors_seen)} error(s):")
                                        for err in errors_seen:
                                            st.caption(err)
                                    else:
                                        st.success(f"Entire graph resumed. {len(children)+1} task(s) active.")
                                    st.session_state.pop("dba_df_tg_tasks", None)
                                    st.rerun()

        # -- DAG Inspector -----------------------------------------------------
        elif task_graph_view == "DAG Inspector":
            st.subheader("DAG Inspector")
            st.caption(
                "Visualise the task dependency tree for a selected root task. "
                "Shows each node's current state, last run result, and duration."
            )

            df_tasks = st.session_state.get("dba_df_tg_tasks", pd.DataFrame())
            if df_tasks.empty:
                st.info("Load the task list in the Suspend/Resume tab first.")
            else:
                root_tasks = df_tasks[
                    df_tasks.get("PREDECESSORS", pd.Series()).astype(str).str.strip().isin(["","[]","None","nan"])
                ] if "PREDECESSORS" in df_tasks.columns else df_tasks
                root_names = root_tasks["NAME"].unique().tolist() if not root_tasks.empty else df_tasks["NAME"].unique().tolist()
                sel_dag = st.selectbox("Select root task to inspect", root_names, key="tg_dag_sel")

                if sel_dag and st.button("Refresh DAG View", key="tg_dag_build"):
                    try:
                        df_dag = df_tasks[
                            (df_tasks["NAME"].astype(str) == str(sel_dag))
                            | df_tasks.get("PREDECESSORS", pd.Series(index=df_tasks.index, dtype=str)).astype(str).str.contains(str(sel_dag), na=False)
                        ].copy()
                        if not df_dag.empty:
                            task_names = [str(v) for v in df_dag["NAME"].dropna().unique().tolist()]
                            try:
                                df_hist = run_query_or_raise(_task_history_sql(
                                    session,
                                    "scheduled_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())",
                                    limit=500,
                                ))
                                if "DURATION_SEC" in df_hist.columns:
                                    df_hist = df_hist.rename(columns={"DURATION_SEC": "LAST_DURATION_SEC"})
                                if not df_hist.empty:
                                    if "NAME" not in df_hist.columns and "TASK_NAME" in df_hist.columns:
                                        df_hist = df_hist.rename(columns={"TASK_NAME": "NAME"})
                                    if "NAME" not in df_hist.columns:
                                        df_hist = pd.DataFrame()
                                    else:
                                        df_hist = df_hist[df_hist["NAME"].astype(str).isin(task_names)].copy()
                                    if "STATE" in df_hist.columns:
                                        df_hist = df_hist.rename(columns={"STATE": "LAST_RUN_STATE"})
                                    if "ERROR_MESSAGE" in df_hist.columns:
                                        df_hist = df_hist.rename(columns={"ERROR_MESSAGE": "LAST_ERROR"})
                                    if "SCHEDULED_TIME" in df_hist.columns:
                                        df_hist = df_hist.rename(columns={"SCHEDULED_TIME": "LAST_RUN_TIME"})
                                if not df_hist.empty and "NAME" in df_hist.columns:
                                    if "LAST_RUN_TIME" in df_hist.columns:
                                        df_hist = df_hist.sort_values("LAST_RUN_TIME", ascending=False)
                                    df_hist = df_hist.drop_duplicates("NAME")
                                    df_dag = df_dag.merge(
                                        df_hist,
                                        how="left",
                                        on="NAME",
                                    )
                            except Exception:
                                pass
                        st.session_state["dba_df_dag_view"] = df_dag
                    except Exception as e:
                        st.warning(f"DAG view unavailable in this role/context: {format_snowflake_error(e)}")

                if st.session_state.get("dba_df_dag_view") is not None and not st.session_state["dba_df_dag_view"].empty:
                    df_dag = st.session_state["dba_df_dag_view"]

                    # Visual tree using indented text
                    st.markdown("**Task Dependency Tree**")
                    for _, row in df_dag.iterrows():
                        name   = row.get("NAME","")
                        preds  = str(row.get("PREDECESSORS","") or "")
                        state  = str(row.get("STATE","")).lower()
                        lr_st  = str(row.get("LAST_RUN_STATE","") or "")
                        dur    = row.get("LAST_DURATION_SEC", 0) or 0
                        err    = str(row.get("LAST_ERROR","") or "")[:80]

                        is_root = preds.strip() in ("","[]","None","nan","")
                        indent  = "" if is_root else "- "

                        state_icon = "Started" if state=="started" else "Suspended" if state=="suspended" else "Unknown"
                        lr_icon    = "Succeeded" if lr_st=="SUCCEEDED" else ("Failed" if lr_st=="FAILED" else "Pending")

                        prefix = "    " if indent else ""
                        suffix = f" - {err}" if err and err != "nan" else ""
                        st.markdown(
                            f"{prefix}{indent}{state_icon} **{name}** | {lr_icon} last: {lr_st} "
                            f"({int(dur)}s){suffix}"
                        )

                    render_priority_dataframe(
                        df_dag,
                        title="DAG detail rows",
                        priority_columns=[
                            "NAME", "DATABASE_NAME", "SCHEMA_NAME", "STATE", "PREDECESSORS",
                            "LAST_RUN_STATE", "LAST_RUN_TIME", "LAST_DURATION_SEC", "LAST_ERROR",
                        ],
                        sort_by=["LAST_RUN_STATE", "LAST_DURATION_SEC", "LAST_RUN_TIME"],
                        ascending=[True, False, False],
                        raw_label="All DAG rows",
                    )
                    download_csv(df_dag, f"dag_{sel_dag}.csv")

    if selected_tool == "Operational Audit":
        st.subheader("Operational Audit")
        st.info("Operational audit details are reserved for DBA platform administrators.")

    # Cost formula audit

    # Data readiness and install readiness
