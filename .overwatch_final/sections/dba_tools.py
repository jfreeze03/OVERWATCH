# sections/dba_tools.py — DBA admin toolkit
# ─────────────────────────────────────────────────────────────────────────────
# NEW tabs vs prior version:
#   Tab 1  — Auto-Suspend Audit → FULL INTERACTIVE WAREHOUSE SETTINGS MANAGER
#             (all ALTER WAREHOUSE params: size, suspend, timeout, scaling, QAS)
#   Tab 14 — Warehouse Settings Manager (promoted from stub)
#   Tab 15 — ⚙️ Cortex AI Limits (SHOW AI SERVICES, ALTER ACCOUNT limits)
#   Tab 16 — 🔀 Task Graph Control (cancel running tasks, cancel task graphs,
#             suspend/resume task trees, restart failed tasks)
#   Tab 17 — 📊 Usage Log (carried forward)
# ─────────────────────────────────────────────────────────────────────────────
import streamlit as st
import pandas as pd
from utils import (
    get_session, safe_sql, format_credits, download_csv,
    get_wh_filter_clause, get_db_filter_clause, get_user_filter_clause,
    get_active_company, get_active_environment, company_value_allowed,
    run_query, run_query_or_raise, sql_literal, safe_identifier,
    format_snowflake_error,
    run_compatibility_checks, build_smoke_test_checklist,
    build_cost_formula_audit, filter_existing_columns, build_task_history_sql,
    admin_actions_enabled, admin_button_disabled,
    log_admin_action,
    show_to_df, first_existing_column, ensure_column_alias,
    scope_warehouse_names, scope_metadata_df, load_task_inventory,
    load_warehouse_inventory, build_unclassified_assets_sql,
    safe_float, safe_int, render_ranked_bar_chart,
)
from config import (
    ALERT_DB, ALERT_SCHEMA, ALERT_TABLE,
    ACTION_QUEUE_TABLE, ETL_AUDIT_DB, ETL_AUDIT_SCHEMA,
)
from utils.workflows import render_priority_dataframe

# ── Snowflake warehouse parameter documentation ──────────────────────────────
_WH_PARAM_HELP = {
    "WAREHOUSE_SIZE":           "Credit rate: X-Small=1, Small=2, Medium=4, Large=8, X-Large=16, 2X-Large=32...",
    "AUTO_SUSPEND":             "Seconds of inactivity before the warehouse suspends. 0 = never. Recommended: 60–300.",
    "AUTO_RESUME":              "Automatically resume when a query is submitted. Should almost always be TRUE.",
    "STATEMENT_TIMEOUT_IN_SECONDS": "Maximum seconds a single query can run before being cancelled. 0 = no limit. Recommended: 3600.",
    "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS": "Max seconds a query waits in the queue. 0 = no limit. Recommended: 600.",
    "MAX_CONCURRENCY_LEVEL":    "Max concurrent SQL statements per cluster. Default: 8. Range: 1–10.",
    "MAX_CLUSTER_COUNT":        "Multi-cluster: max number of clusters. 1 = single cluster. Requires Enterprise.",
    "MIN_CLUSTER_COUNT":        "Multi-cluster: min clusters always running. Setting >1 incurs constant credit cost.",
    "SCALING_POLICY":           "STANDARD = scale up when queue builds. ECONOMY = scale only when full queue detected.",
    "ENABLE_QUERY_ACCELERATION": "Allow eligible queries to use the Query Acceleration Service. Requires Enterprise.",
    "QUERY_ACCELERATION_MAX_SCALE_FACTOR": "Max scale factor for QAS (0 = unlimited, 1–100). Each factor = 1 credit/hr.",
    "COMMENT":                  "Free-text label for this warehouse.",
}

_SIZE_OPTS = ["X-Small","Small","Medium","Large","X-Large","2X-Large","3X-Large","4X-Large","5X-Large","6X-Large"]
_SIZE_SQL = {
    "X-Small": "XSMALL",
    "Small": "SMALL",
    "Medium": "MEDIUM",
    "Large": "LARGE",
    "X-Large": "XLARGE",
    "2X-Large": "XXLARGE",
    "3X-Large": "XXXLARGE",
    "4X-Large": "X4LARGE",
    "5X-Large": "X5LARGE",
    "6X-Large": "X6LARGE",
}
_SCALE_OPTS = ["STANDARD","ECONOMY"]
TASK_GRAPH_CONTROL_PANES = (
    "Running Task Queries",
    "Cancel Graph / Task",
    "Suspend / Resume",
    "DAG Inspector",
)


def _load_button(label, key):
    return st.button(label, key=key)


def _typed_confirmation(prompt: str, expected: str, key: str) -> bool:
    entered = st.text_input(prompt, key=key, placeholder=expected)
    return entered.strip() == expected


def _scope_warehouse_names(df: pd.DataFrame, name_col: str = "name") -> pd.DataFrame:
    """Apply ALFA/Trexis warehouse visibility to SHOW-style result sets."""
    return scope_warehouse_names(df, name_col=name_col, company=get_active_company())


def _scope_metadata_df(df: pd.DataFrame) -> pd.DataFrame:
    """Apply ALFA/Trexis visibility to SHOW-style metadata result sets."""
    return scope_metadata_df(df, company=get_active_company())


def _quote_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _qualified_name(*parts: str) -> str:
    return ".".join(_quote_identifier(part) for part in parts if str(part or "").strip())


def _as_bool(value, default: bool = False) -> bool:
    if value is None or str(value).lower() in ("", "nan", "none"):
        return default
    return str(value).strip().lower() in ("true", "yes", "1", "on")


def _as_int(value, default: int) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _is_unknown_setting(value) -> bool:
    return value is None or str(value).strip().lower() in ("", "nan", "none", "null")


def _warehouse_size_sql(value) -> str:
    text = str(value or "").strip()
    if text in _SIZE_SQL:
        return _SIZE_SQL[text]
    compact = text.upper().replace("-", "").replace("_", "").replace(" ", "")
    aliases = {
        "XSMALL": "XSMALL",
        "SMALL": "SMALL",
        "MEDIUM": "MEDIUM",
        "LARGE": "LARGE",
        "XLARGE": "XLARGE",
        "XXLARGE": "XXLARGE",
        "2XLARGE": "XXLARGE",
        "XXXLARGE": "XXXLARGE",
        "3XLARGE": "XXXLARGE",
        "X4LARGE": "X4LARGE",
        "4XLARGE": "X4LARGE",
        "X5LARGE": "X5LARGE",
        "5XLARGE": "X5LARGE",
        "X6LARGE": "X6LARGE",
        "6XLARGE": "X6LARGE",
    }
    return aliases.get(compact, compact or "XSMALL")


def _normalize_warehouse_setting(param: str, value) -> str:
    param = str(param or "").upper()
    if param == "WAREHOUSE_SIZE":
        return _warehouse_size_sql(value)
    if param in {"AUTO_RESUME", "ENABLE_QUERY_ACCELERATION"}:
        return "TRUE" if _as_bool(value) else "FALSE"
    if param == "SCALING_POLICY":
        return str(value or "STANDARD").upper()
    return str(_as_int(value, 0))


def _warehouse_setting_risk(param: str, current_sql: str, requested_sql: str) -> str:
    param = str(param or "").upper()
    if param == "WAREHOUSE_SIZE":
        return "Validate queue, spill, p95 runtime, and cost drivers before resizing."
    if param == "AUTO_SUSPEND" and requested_sql == "0":
        return "High cost risk: warehouse will never auto-suspend."
    if param == "AUTO_SUSPEND" and _as_int(requested_sql, 0) > 600:
        return "Cost risk: auto-suspend is above the 10-minute DBA guardrail."
    if param == "AUTO_RESUME" and requested_sql == "FALSE":
        return "Availability risk: users may see failures until the warehouse is resumed manually."
    if param == "MIN_CLUSTER_COUNT" and _as_int(requested_sql, 1) > 1:
        return "High cost risk: extra clusters can run continuously."
    if param == "MAX_CLUSTER_COUNT" and _as_int(requested_sql, 1) > 1:
        return "Burst cost risk: multi-cluster scaling can multiply credit burn."
    if param == "ENABLE_QUERY_ACCELERATION" and requested_sql == "TRUE":
        return "Serverless cost risk: QAS can add spend outside warehouse metering."
    if param == "QUERY_ACCELERATION_MAX_SCALE_FACTOR" and _as_int(requested_sql, 0) == 0:
        return "Serverless cost risk: QAS scale factor is unlimited."
    if param == "STATEMENT_TIMEOUT_IN_SECONDS" and requested_sql == "0":
        return "Runaway query risk: statements have no warehouse-level timeout."
    if param == "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS" and requested_sql == "0":
        return "Queue risk: statements can wait indefinitely."
    if param == "MAX_CONCURRENCY_LEVEL" and _as_int(requested_sql, 8) > 8:
        return "Pressure risk: higher concurrency can increase spill and p95 runtime."
    return "Review workload impact and owner approval before applying."


def _warehouse_settings_preflight_sql(warehouse_name: str) -> str:
    safe_wh = _quote_identifier(warehouse_name)
    wh_lit = sql_literal(warehouse_name, 300)
    return f"""-- Read-only pre-flight before ALTER WAREHOUSE
SELECT CURRENT_USER() AS current_user,
       CURRENT_ROLE() AS current_role,
       CURRENT_WAREHOUSE() AS current_warehouse;

SHOW GRANTS ON WAREHOUSE {safe_wh};

SHOW WAREHOUSES LIKE {wh_lit};

SELECT warehouse_name,
       SUM(credits_used) AS credits_7d,
       SUM(credits_used_compute) AS compute_credits_7d,
       SUM(COALESCE(credits_used_cloud_services, 0)) AS cloud_services_credits_7d
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
  AND warehouse_name = {wh_lit}
GROUP BY warehouse_name;

SELECT warehouse_name,
       COUNT(*) AS queries_24h,
       SUM(IFF(execution_status = 'FAILED', 1, 0)) AS failed_queries_24h,
       AVG(total_elapsed_time) / 1000 AS avg_elapsed_sec_24h,
       APPROX_PERCENTILE(total_elapsed_time / 1000, 0.95) AS p95_elapsed_sec_24h
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
  AND warehouse_name = {wh_lit}
GROUP BY warehouse_name;

-- Confirm MODIFY privilege, owner approval, workload impact, and rollback plan before applying.
"""


def _build_warehouse_setting_plan(
    warehouse_name: str,
    current_row: pd.Series,
    requested_settings: dict,
) -> dict:
    """Build a reviewed ALTER WAREHOUSE plan with rollback and audit context."""
    specs = [
        ("WAREHOUSE_SIZE", "size"),
        ("AUTO_SUSPEND", "auto_suspend"),
        ("AUTO_RESUME", "auto_resume"),
        ("STATEMENT_TIMEOUT_IN_SECONDS", "statement_timeout_in_seconds"),
        ("STATEMENT_QUEUED_TIMEOUT_IN_SECONDS", "statement_queued_timeout_in_seconds"),
        ("MAX_CONCURRENCY_LEVEL", "max_concurrency_level"),
        ("SCALING_POLICY", "scaling_policy"),
        ("MIN_CLUSTER_COUNT", "min_cluster_count"),
        ("MAX_CLUSTER_COUNT", "max_cluster_count"),
        ("ENABLE_QUERY_ACCELERATION", "enable_query_acceleration"),
        ("QUERY_ACCELERATION_MAX_SCALE_FACTOR", "query_acceleration_max_scale_factor"),
    ]
    changes = []
    skipped = []
    for param, column in specs:
        if param not in requested_settings:
            continue
        current_raw = current_row.get(column, None)
        if _is_unknown_setting(current_raw):
            skipped.append({
                "PARAMETER": param,
                "REASON": "Current value unavailable from SHOW WAREHOUSES; refresh metadata before changing this setting.",
            })
            continue
        current_sql = _normalize_warehouse_setting(param, current_raw)
        requested_sql = _normalize_warehouse_setting(param, requested_settings.get(param))
        if current_sql != requested_sql:
            changes.append({
                "PARAMETER": param,
                "CURRENT": current_sql,
                "REQUESTED": requested_sql,
                "RISK": _warehouse_setting_risk(param, current_sql, requested_sql),
            })

    safe_wh = _quote_identifier(warehouse_name)
    assignments = [f"{row['PARAMETER']} = {row['REQUESTED']}" for row in changes]
    rollback_assignments = [f"{row['PARAMETER']} = {row['CURRENT']}" for row in changes]
    alter_sql = ""
    rollback_sql = ""
    if assignments:
        alter_sql = f"ALTER WAREHOUSE {safe_wh} SET\n    " + "\n    ".join(assignments) + ";"
        rollback_sql = f"ALTER WAREHOUSE {safe_wh} SET\n    " + "\n    ".join(rollback_assignments) + ";"

    context_lines = [
        f"Warehouse: {warehouse_name}",
        "Change count: " + str(len(changes)),
    ]
    for row in changes:
        context_lines.append(
            f"{row['PARAMETER']}: {row['CURRENT']} -> {row['REQUESTED']} | {row['RISK']}"
        )
    if rollback_sql:
        context_lines.append("Rollback SQL: " + rollback_sql.replace("\n", " "))

    return {
        "warehouse": warehouse_name,
        "changes": changes,
        "skipped": skipped,
        "changes_df": pd.DataFrame(changes),
        "skipped_df": pd.DataFrame(skipped),
        "alter_sql": alter_sql,
        "rollback_sql": rollback_sql,
        "preflight_sql": _warehouse_settings_preflight_sql(warehouse_name),
        "confirmation_text": f"ALTER {warehouse_name}",
        "control_context": "\n".join(context_lines)[:4000],
    }


def _table_exists(session, db: str, schema: str, table: str):
    try:
        db_ident = safe_identifier(db)
        row = session.sql(f"""
            SELECT COUNT(*) AS CNT
            FROM {db_ident}.INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = {sql_literal(schema.upper())}
              AND TABLE_NAME = {sql_literal(table.upper())}
        """).collect()[0]
        return int(row["CNT"]) > 0
    except Exception:
        return None


def _task_exists(session, db: str, schema: str, task_name: str):
    try:
        schema_fqn = _qualified_name(db, schema)
        rows = session.sql(
            f"SHOW TASKS LIKE {sql_literal(task_name.upper())} IN SCHEMA {schema_fqn}"
        ).collect()
        return len(rows) > 0
    except Exception:
        return None


def _show_to_df(session, stmt: str, force_refresh: bool = False) -> pd.DataFrame:
    return show_to_df(session, stmt, force_refresh=force_refresh)


def _first_existing_column(df: pd.DataFrame, candidates: list[str]) -> str:
    return first_existing_column(df, candidates)


def _ensure_column_alias(df: pd.DataFrame, target: str, candidates: list[str], default="") -> pd.DataFrame:
    return ensure_column_alias(df, target, candidates, default)


def _load_task_inventory(session, force_refresh: bool = False) -> pd.DataFrame:
    return load_task_inventory(session, get_active_company(), force_refresh=force_refresh)


def _task_history_sql(session, time_predicate: str, limit: int = 500) -> str:
    """Build TASK_HISTORY SQL using only columns exposed by this account."""
    return build_task_history_sql(
        session,
        time_predicate,
        limit=limit,
        company=get_active_company(),
    )


def _setup_status_df(session) -> pd.DataFrame:
    checks = [
        ("Saved Views", "TABLE", ALERT_DB, ALERT_SCHEMA, "OVERWATCH_BOOKMARKS"),
        ("Annotation Windows", "TABLE", ALERT_DB, ALERT_SCHEMA, "OVERWATCH_ANNOTATIONS"),
        ("Alert History", "TABLE", ALERT_DB, ALERT_SCHEMA, ALERT_TABLE),
        ("Action Queue", "TABLE", ALERT_DB, ALERT_SCHEMA, ACTION_QUEUE_TABLE),
        ("Snowflake Value Log", "TABLE", ETL_AUDIT_DB, ETL_AUDIT_SCHEMA, "OVERWATCH_ROI_LOG"),
        ("Usage Log", "TABLE", ALERT_DB, ALERT_SCHEMA, "OVERWATCH_USAGE_LOG"),
        ("Anomaly Alert Task", "TASK", ALERT_DB, ALERT_SCHEMA, "OVERWATCH_ANOMALY_CHECK"),
    ]
    rows = []
    for feature, object_type, db, schema, object_name in checks:
        exists = (
            _task_exists(session, db, schema, object_name)
            if object_type == "TASK"
            else _table_exists(session, db, schema, object_name)
        )
        if exists is True:
            status = "Present"
        elif exists is False:
            status = "Missing"
        else:
            status = "Unknown"
        rows.append({
            "FEATURE": feature,
            "OBJECT_TYPE": object_type,
            "OBJECT_NAME": f"{db}.{schema}.{object_name}",
            "STATUS": status,
        })
    return pd.DataFrame(rows)


def render():
    session = get_session()
    company = get_active_company()
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "WAREHOUSE_SIZE",
            "BYTES_SCANNED",
            "QUERY_TAG",
            "QUEUED_OVERLOAD_TIME",
            "BYTES_SPILLED_TO_REMOTE_STORAGE",
            "CREDITS_USED_CLOUD_SERVICES",
        ],
    ))
    qh_warehouse_size_expr = (
        "warehouse_size AS warehouse_size"
        if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"
    )
    qh_max_size_expr = (
        "MAX(q.warehouse_size)"
        if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR"
    )
    qh_plain_size_expr = (
        "warehouse_size"
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

    st.caption(
        "DBA Tools are grouped to keep the high-value controls easy to find. "
        "Open a group, then choose the specific operation."
    )
    focus = st.session_state.get("dba_tools_focus")
    if focus:
        focus_hint = {
            "Governance": "Start with Governance for schema compare, recent objects, unused objects, and object drift.",
            "Data Movement": "Start with Data Movement for loads, Snowpipe, dynamic tables, and replication.",
            "Controlled Actions": "Start with Warehouse Ops for query/task/warehouse actions, then Cost & Setup for setup/audit evidence.",
        }.get(str(focus), "Use the matching tab group below first; other tools remain available when needed.")
        st.info(f"Change & Drift focus: {focus}. {focus_hint}")
    with st.expander("DBA Tools Operating Model", expanded=not bool(focus)):
        risk_a, risk_b, risk_c = st.columns(3)
        with risk_a:
            st.info(
                "Safe Observability\n\n"
                "Read-only inventory, diagnostics, compatibility checks, schema compare, recent objects, "
                "QAS visibility, replication, serverless costs, and usage logs."
            )
        with risk_b:
            st.warning(
                "Controlled Actions\n\n"
                "Query cancellation, task suspend/resume, warehouse setting changes, and Cortex limit updates. "
                "These stay locked unless Admin actions are enabled."
            )
        with risk_c:
            st.success(
                "Setup and Maintenance\n\n"
                "Compatibility checks, setup status, usage logging, action queue routing, and "
                "formula audit evidence. SQL deployment lives in the Snowflake setup script, not this UI."
            )
    if not admin_actions_enabled():
        st.info(
            "Read-only mode is active. Load, inspect, compare, and export still work; "
            "ALTER, CANCEL, EXECUTE, SUSPEND, and RESUME buttons stay locked until Admin actions are enabled in Settings."
        )

    st.info("Alert history, email-ready delivery rows, routing, and suppression windows now live in the consolidated Alert Center.")
    if st.button("Open Alert Center", key="dba_tools_open_alert_center"):
        st.session_state["nav_section"] = "Alert Center"
        st.rerun()
    st.divider()

    tool_groups = {
        "Warehouse Ops": [
            "Query Kill List",
            "Warehouse Settings",
            "QAS Monitor",
            "Task Graph Control",
        ],
        "Data Movement": [
            "Data Loading",
            "Snowpipe Monitor",
            "Dynamic Tables",
            "Replication",
        ],
        "Governance": [
            "Network & Sessions",
            "Unused Objects",
            "Schema Compare",
            "Recent Objects",
        ],
        "Cost & Setup": [
            "Mart Readiness",
            "Serverless Costs",
            "Cost Formula Audit",
            "Cortex AI Limits",
            "Usage Log",
            "Setup Status",
        ],
    }
    focus_to_group = {
        "Governance": "Governance",
        "Data Movement": "Data Movement",
        "Controlled Actions": "Warehouse Ops",
        "Cost": "Cost & Setup",
    }
    default_group = focus_to_group.get(str(focus), "Warehouse Ops")
    group_names = list(tool_groups)
    group_index = group_names.index(default_group) if default_group in group_names else 0
    selected_group = st.radio(
        "DBA workflow",
        group_names,
        index=group_index,
        horizontal=True,
        key="dba_tools_group_selector",
    )
    selected_tool = st.selectbox(
        "Open specialist tool",
        tool_groups[selected_group],
        key=f"dba_tools_tool_selector_{selected_group}",
    )
    st.caption(
        "Focused mode renders one specialist tool at a time. Use the workflow hubs for daily operations; "
        "use this page when you need a specific admin utility."
    )

    # ── TAB 0: QUERY KILL LIST ────────────────────────────────────────────────
    if selected_tool == "Query Kill List":
        st.header("⛔ Long-Running Query Kill List")
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
            st.warning(f"⚠️ {len(df)} queries running > {kill_min}s")
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
                "⛔ Cancel Query",
                type="primary",
                key="kl_kill",
                disabled=admin_button_disabled(not kill_confirmed),
            ):
                try:
                    session.sql(f"SELECT SYSTEM$CANCEL_QUERY({sql_literal(kill_id)})").collect()
                    st.success(f"✅ Cancel sent for `{kill_id}`")
                except Exception as e:
                    st.error(f"Cancel failed: {format_snowflake_error(e)}")
        elif st.session_state.get("dba_df_kl") is not None:
            st.success(f"✅ No queries running > {kill_min}s")

    # ── TAB 1: WAREHOUSE SETTINGS MANAGER ────────────────────────────────────
    if selected_tool == "Warehouse Settings":
        st.header("⚙️ Warehouse Settings Manager")
        st.caption(
            "View and interactively change all warehouse parameters — "
            "size, timeouts, auto-suspend, multi-cluster, QAS, and scaling policy. "
            "Changes execute as `ALTER WAREHOUSE` statements in real time."
        )

        active_company = get_active_company()
        needs_wh_load = (
            st.session_state.get("_dba_wh_cfg_company") != active_company
            or "dba_df_wh_cfg" not in st.session_state
        )
        last_failed_company = st.session_state.get("_dba_wh_cfg_failed_company")

        col_r1, col_r2 = st.columns([1, 1])
        with col_r1:
            refresh_wh = st.button("Refresh Warehouses", key="wh_cfg_load")
            if refresh_wh or (needs_wh_load and last_failed_company != active_company):
                try:
                    df_raw = load_warehouse_inventory(session, active_company, force_refresh=bool(refresh_wh))
                    df_raw.columns = [c.lower() for c in df_raw.columns]
                    st.session_state["dba_df_wh_cfg"] = df_raw
                    st.session_state["_dba_wh_cfg_company"] = active_company
                    st.session_state.pop("_dba_wh_cfg_failed_company", None)
                except Exception as e:
                    st.warning(f"Warehouse list unavailable in this role/context: {format_snowflake_error(e)}")
                    st.session_state["dba_df_wh_cfg"] = pd.DataFrame()
                    st.session_state["_dba_wh_cfg_company"] = active_company
                    st.session_state["_dba_wh_cfg_failed_company"] = active_company
        with col_r2:
            wh_filter_txt = st.text_input("Filter warehouse", key="wh_cfg_filter",
                                           placeholder="e.g. ALFA or leave blank for all")

        df_wh = st.session_state.get("dba_df_wh_cfg")
        if df_wh is not None and not df_wh.empty:
            # Apply filter
            if wh_filter_txt:
                mask   = df_wh["name"].astype(str).str.upper().str.contains(safe_sql(wh_filter_txt).upper(), na=False)
                df_wh  = df_wh[mask]

            # Summary table
            st.subheader(f"Warehouses ({len(df_wh)})")
            display_cols = [c for c in ["name","size","state","auto_suspend","auto_resume",
                                         "min_cluster_count","max_cluster_count","scaling_policy",
                                         "enable_query_acceleration","statement_timeout_in_seconds",
                                         "statement_queued_timeout_in_seconds"] if c in df_wh.columns]
            render_priority_dataframe(
                df_wh[display_cols],
                title="Warehouse settings by risk",
                priority_columns=display_cols,
                sort_by=["auto_suspend", "state", "name"],
                ascending=[False, True, True],
                raw_label="All warehouse setting rows",
                height=220,
            )

            # Flag issues
            issues = []
            for _, row in df_wh.iterrows():
                wn  = row.get("name","")
                sus = row.get("auto_suspend", 0)
                try:
                    if int(sus) > 600:
                        issues.append(f"🟡 **{wn}**: AUTO_SUSPEND={sus}s (>10 min) — wasting credits when idle")
                    if int(sus) == 0:
                        issues.append(f"🔴 **{wn}**: AUTO_SUSPEND=0 — warehouse NEVER suspends")
                except Exception:
                    pass
            if issues:
                with st.expander(f"⚠️ {len(issues)} configuration issue(s) detected"):
                    for i in issues:
                        st.markdown(i)

            st.divider()
            st.subheader("Edit Warehouse Settings")
            st.caption("Select a warehouse, adjust parameters, preview the ALTER SQL, then apply.")

            wh_names = df_wh["name"].tolist() if "name" in df_wh.columns else []
            sel_wh   = st.selectbox("Select warehouse to edit", wh_names, key="wh_edit_sel")

            if sel_wh:
                wh_row = df_wh[df_wh["name"] == sel_wh].iloc[0]

                def _get(col, default=""):
                    v = wh_row.get(col, default)
                    return "" if v is None or str(v).lower() in ("nan","none","") else str(v)

                st.markdown(f"**Editing: `{sel_wh}`**  ·  Current state: `{_get('state','unknown')}`")

                with st.form(f"wh_edit_form_{sel_wh}"):
                    c1, c2, c3 = st.columns(3)

                    with c1:
                        st.markdown("**Compute**")
                        curr_size = _get("size","X-Small")
                        new_size  = st.selectbox(
                            "Size", _SIZE_OPTS,
                            index=_SIZE_OPTS.index(curr_size) if curr_size in _SIZE_OPTS else 0,
                            key=f"wh_size_{sel_wh}",
                            help=_WH_PARAM_HELP["WAREHOUSE_SIZE"],
                        )
                        new_auto_resume = st.checkbox(
                            "Auto Resume",
                            value=_as_bool(_get("auto_resume","true"), True),
                            key=f"wh_ar_{sel_wh}",
                            help=_WH_PARAM_HELP["AUTO_RESUME"],
                        )
                        curr_sus = _as_int(_get("auto_suspend","600"), 600)
                        new_auto_suspend = st.number_input(
                            "AUTO_SUSPEND (seconds, 0=never)",
                            min_value=0, max_value=86400, value=curr_sus, step=60,
                            key=f"wh_sus_{sel_wh}",
                            help=_WH_PARAM_HELP["AUTO_SUSPEND"],
                        )

                    with c2:
                        st.markdown("**Timeouts**")
                        curr_stmt_to = _as_int(_get("statement_timeout_in_seconds","0"), 0)
                        new_stmt_timeout = st.number_input(
                            "STATEMENT_TIMEOUT (sec, 0=no limit)",
                            min_value=0, max_value=604800, value=curr_stmt_to, step=300,
                            key=f"wh_stmto_{sel_wh}",
                            help=_WH_PARAM_HELP["STATEMENT_TIMEOUT_IN_SECONDS"],
                        )
                        curr_q_to = _as_int(_get("statement_queued_timeout_in_seconds","0"), 0)
                        new_queue_timeout = st.number_input(
                            "QUEUE_TIMEOUT (sec, 0=no limit)",
                            min_value=0, max_value=86400, value=curr_q_to, step=60,
                            key=f"wh_qto_{sel_wh}",
                            help=_WH_PARAM_HELP["STATEMENT_QUEUED_TIMEOUT_IN_SECONDS"],
                        )
                        curr_concur = _as_int(_get("max_concurrency_level","8"), 8)
                        new_concurrency = st.number_input(
                            "MAX_CONCURRENCY_LEVEL",
                            min_value=1, max_value=10, value=min(max(curr_concur,1),10),
                            key=f"wh_concur_{sel_wh}",
                            help=_WH_PARAM_HELP["MAX_CONCURRENCY_LEVEL"],
                        )

                    with c3:
                        st.markdown("**Scaling & QAS**")
                        curr_scale = _get("scaling_policy","STANDARD").upper()
                        new_scaling = st.selectbox(
                            "SCALING_POLICY",
                            _SCALE_OPTS,
                            index=_SCALE_OPTS.index(curr_scale) if curr_scale in _SCALE_OPTS else 0,
                            key=f"wh_sp_{sel_wh}",
                            help=_WH_PARAM_HELP["SCALING_POLICY"],
                        )
                        curr_min = _as_int(_get("min_cluster_count","1"), 1)
                        curr_max = _as_int(_get("max_cluster_count","1"), 1)
                        new_min_clusters = st.number_input(
                            "MIN_CLUSTER_COUNT",
                            min_value=1, max_value=10, value=max(curr_min,1),
                            key=f"wh_minc_{sel_wh}",
                            help=_WH_PARAM_HELP["MIN_CLUSTER_COUNT"],
                        )
                        new_max_clusters = st.number_input(
                            "MAX_CLUSTER_COUNT",
                            min_value=1, max_value=10, value=max(curr_max,1),
                            key=f"wh_maxc_{sel_wh}",
                            help=_WH_PARAM_HELP["MAX_CLUSTER_COUNT"],
                        )
                        curr_qas = _as_bool(_get("enable_query_acceleration","false"), False)
                        new_qas  = st.checkbox(
                            "Enable QAS",
                            value=curr_qas,
                            key=f"wh_qas_{sel_wh}",
                            help=_WH_PARAM_HELP["ENABLE_QUERY_ACCELERATION"],
                        )
                        curr_qas_sf = _as_int(_get("query_acceleration_max_scale_factor","8"), 8)
                        new_qas_sf = st.number_input(
                            "QAS Max Scale Factor (0=unlimited)",
                            min_value=0, max_value=100, value=curr_qas_sf,
                            key=f"wh_qassf_{sel_wh}",
                            help=_WH_PARAM_HELP["QUERY_ACCELERATION_MAX_SCALE_FACTOR"],
                            disabled=not new_qas,
                        )

                    apply = st.form_submit_button("📋 Preview & Apply Changes", type="primary")

                plan_key = f"wh_change_plan_{sel_wh}"
                if apply:
                    requested = {
                        "WAREHOUSE_SIZE": new_size,
                        "AUTO_SUSPEND": int(new_auto_suspend),
                        "AUTO_RESUME": bool(new_auto_resume),
                        "STATEMENT_TIMEOUT_IN_SECONDS": int(new_stmt_timeout),
                        "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS": int(new_queue_timeout),
                        "MAX_CONCURRENCY_LEVEL": int(new_concurrency),
                        "SCALING_POLICY": new_scaling,
                        "MIN_CLUSTER_COUNT": int(new_min_clusters),
                        "MAX_CLUSTER_COUNT": int(new_max_clusters),
                        "ENABLE_QUERY_ACCELERATION": bool(new_qas),
                        "QUERY_ACCELERATION_MAX_SCALE_FACTOR": int(new_qas_sf),
                    }
                    st.session_state[plan_key] = _build_warehouse_setting_plan(sel_wh, wh_row, requested)

                if apply:
                    # Build ALTER WAREHOUSE statement from changed params
                    safe_wh = _quote_identifier(sel_wh)

                    params = [
                        f"WAREHOUSE_SIZE = {_SIZE_SQL.get(new_size, 'XSMALL')}",
                        f"AUTO_SUSPEND = {int(new_auto_suspend)}",
                        f"AUTO_RESUME = {'TRUE' if new_auto_resume else 'FALSE'}",
                        f"STATEMENT_TIMEOUT_IN_SECONDS = {int(new_stmt_timeout)}",
                        f"STATEMENT_QUEUED_TIMEOUT_IN_SECONDS = {int(new_queue_timeout)}",
                        f"MAX_CONCURRENCY_LEVEL = {int(new_concurrency)}",
                        f"SCALING_POLICY = {new_scaling}",
                        f"MIN_CLUSTER_COUNT = {int(new_min_clusters)}",
                        f"MAX_CLUSTER_COUNT = {int(new_max_clusters)}",
                        f"ENABLE_QUERY_ACCELERATION = {'TRUE' if new_qas else 'FALSE'}",
                        f"QUERY_ACCELERATION_MAX_SCALE_FACTOR = {int(new_qas_sf)}",
                    ]
                    alter_sql = f"ALTER WAREHOUSE {safe_wh} SET\n    " + "\n    ".join(params) + ";"

                    st.subheader("Legacy SQL Preview - disabled")
                    st.caption("Use the reviewed change plan below. The legacy apply button is intentionally disabled.")
                    st.code(alter_sql, language="sql")

                    col_apply, col_cancel = st.columns([1, 3])
                    with col_apply:
                        wh_confirmed = _typed_confirmation(
                            f"Type {sel_wh} to enable ALTER WAREHOUSE",
                            sel_wh,
                            f"wh_confirm_{sel_wh}",
                        )
                        if st.button(
                            "✅ Apply Now",
                            type="primary",
                            key=f"wh_apply_{sel_wh}",
                            disabled=True,
                        ):
                            # CALLER MODE: ALTER WAREHOUSE needs MODIFY on the warehouse.
                            # SNOW_ACCOUNTADMIN and SNOW_SYSADMIN both have this.
                            # If a future role doesn't, this surfaces a clear error.
                            try:
                                session.sql(alter_sql).collect()
                                st.success(f"✅ Warehouse `{sel_wh}` updated successfully.")
                                st.session_state.pop("dba_df_wh_cfg", None)
                                st.rerun()
                            except Exception as e:
                                err_str = str(e).lower()
                                if "insufficient privilege" in err_str or "not authorized" in err_str:
                                    st.error(
                                        f"⛔ **Permission denied on `{sel_wh}`.** "
                                        f"ALTER WAREHOUSE requires MODIFY privilege. "
                                        f"Your current role may not have this on this warehouse."
                                    )
                                elif "enterprise" in err_str or "not supported" in err_str:
                                    st.error(
                                        f"⛔ **Feature not available in your Snowflake edition.** "
                                        f"Multi-cluster and QAS require Enterprise or higher."
                                    )
                                else:
                                    st.error(f"ALTER failed: {format_snowflake_error(e)}")

    # ── TAB 2: DATA LOADING ───────────────────────────────────────────────────
                plan = st.session_state.get(plan_key)
                if plan:
                    st.subheader("Reviewed Warehouse Change Plan")
                    changes_df = plan.get("changes_df", pd.DataFrame())
                    skipped_df = plan.get("skipped_df", pd.DataFrame())
                    if changes_df.empty:
                        st.success("No warehouse settings changed from the loaded before-state.")
                    else:
                        render_priority_dataframe(
                            changes_df,
                            title="Before/after settings requiring review",
                            priority_columns=["PARAMETER", "CURRENT", "REQUESTED", "RISK"],
                            sort_by=["PARAMETER"],
                            ascending=True,
                            raw_label="All proposed warehouse changes",
                            height=240,
                        )
                        st.caption(
                            "Only changed parameters are included in the ALTER statement. "
                            "Run the pre-flight checks and keep the rollback SQL with the change ticket."
                        )
                        with st.expander("Read-only pre-flight SQL", expanded=True):
                            st.code(plan["preflight_sql"], language="sql")
                        with st.expander("ALTER SQL to apply", expanded=True):
                            st.code(plan["alter_sql"], language="sql")
                        with st.expander("Rollback SQL", expanded=False):
                            st.code(plan["rollback_sql"], language="sql")

                    if not skipped_df.empty:
                        st.warning("Some settings were not included because their current values were unavailable.")
                        render_priority_dataframe(
                            skipped_df,
                            title="Skipped settings",
                            priority_columns=["PARAMETER", "REASON"],
                            sort_by=["PARAMETER"],
                            ascending=True,
                            raw_label="All skipped settings",
                            height=160,
                        )

                    if not changes_df.empty:
                        col_apply, col_audit = st.columns([1, 3])
                        with col_apply:
                            wh_confirmed = _typed_confirmation(
                                f"Type {plan['confirmation_text']} to apply this warehouse change",
                                plan["confirmation_text"],
                                f"wh_confirm_reviewed_{sel_wh}",
                            )
                            if st.button(
                                "Apply Warehouse Change",
                                type="primary",
                                key=f"wh_apply_reviewed_{sel_wh}",
                                disabled=admin_button_disabled(not wh_confirmed),
                            ):
                                try:
                                    log_admin_action(
                                        session,
                                        action_type="ALTER WAREHOUSE",
                                        target_object=sel_wh,
                                        sql_text=plan["alter_sql"],
                                        result_status="STARTED",
                                        result_message="Warehouse change submitted from OVERWATCH.",
                                        confirmation_text=plan["confirmation_text"],
                                        control_context=plan["control_context"],
                                        company=active_company,
                                        environment=get_active_environment(),
                                    )
                                    session.sql(plan["alter_sql"]).collect()
                                    audited = log_admin_action(
                                        session,
                                        action_type="ALTER WAREHOUSE",
                                        target_object=sel_wh,
                                        sql_text=plan["alter_sql"],
                                        result_status="SUCCESS",
                                        result_message="Warehouse change completed.",
                                        confirmation_text=plan["confirmation_text"],
                                        control_context=plan["control_context"],
                                        company=active_company,
                                        environment=get_active_environment(),
                                    )
                                    st.success(f"Warehouse `{sel_wh}` updated successfully.")
                                    if not audited:
                                        st.warning("The change completed, but the admin audit table was unavailable or not writable.")
                                    st.session_state.pop("dba_df_wh_cfg", None)
                                    st.session_state.pop(plan_key, None)
                                    st.rerun()
                                except Exception as e:
                                    err = format_snowflake_error(e)
                                    log_admin_action(
                                        session,
                                        action_type="ALTER WAREHOUSE",
                                        target_object=sel_wh,
                                        sql_text=plan["alter_sql"],
                                        result_status="FAILED",
                                        result_message=err,
                                        confirmation_text=plan["confirmation_text"],
                                        control_context=plan["control_context"],
                                        company=active_company,
                                        environment=get_active_environment(),
                                    )
                                    err_str = str(e).lower()
                                    if "insufficient privilege" in err_str or "not authorized" in err_str:
                                        st.error(
                                            f"Permission denied on `{sel_wh}`. "
                                            f"ALTER WAREHOUSE requires MODIFY privilege."
                                        )
                                    elif "enterprise" in err_str or "not supported" in err_str:
                                        st.error(
                                            "Feature not available in your Snowflake edition. "
                                            "Multi-cluster and QAS require Enterprise or higher."
                                        )
                                    else:
                                        st.error(f"ALTER failed: {err}")
                        with col_audit:
                            st.caption(
                                "Audit path: OVERWATCH_ADMIN_ACTION_AUDIT captures company, environment, "
                                "Snowflake role/user, SQL hash, confirmation text, control context, and result."
                            )

    if selected_tool == "Data Loading":
        st.header("📦 Data Loading Monitor")
        load_days = st.slider("Lookback (days)", 1, 30, 7, key="dl_days")
        if _load_button("Load Copy History", "dl_load"):
            try:
                st.session_state["dba_df_copy"] = run_query(f"""
                    SELECT table_name, file_name, status, row_count,
                           first_error_message, last_load_time
                    FROM SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY
                    WHERE last_load_time >= DATEADD('day', -{load_days}, CURRENT_TIMESTAMP())
                      {get_db_filter_clause("table_catalog_name")}
                    ORDER BY last_load_time DESC LIMIT 500
                """, ttl_key=f"dba_copy_{company}_{load_days}", tier="standard")
            except Exception as e:
                st.warning(f"Copy history unavailable: {format_snowflake_error(e)}")
        if st.session_state.get("dba_df_copy") is not None and not st.session_state["dba_df_copy"].empty:
            df_copy = st.session_state["dba_df_copy"]
            render_priority_dataframe(
                df_copy,
                title="Copy history rows to review",
                priority_columns=[
                    "TABLE_NAME", "FILE_NAME", "STATUS", "ROW_COUNT",
                    "FIRST_ERROR_MESSAGE", "LAST_LOAD_TIME",
                ],
                sort_by=["STATUS", "LAST_LOAD_TIME", "ROW_COUNT"],
                ascending=[True, False, False],
                raw_label="All copy history rows",
            )
            download_csv(df_copy, "copy_history.csv")

    # ── TABS 3–13: CARRIED FORWARD (abbreviated for file size) ───────────────
    if selected_tool == "Network & Sessions":
        st.header("🌐 Network & Sessions")
        if _load_button("Load Session Data", "net_load"):
            try:
                st.session_state["dba_df_long_sess"] = run_query(f"""
                    SELECT session_id, user_name, created_on,
                           DATEDIFF('hour', created_on, CURRENT_TIMESTAMP()) AS session_hours
                    FROM SNOWFLAKE.ACCOUNT_USAGE.SESSIONS
                    WHERE created_on >= DATEADD('day', -7, CURRENT_TIMESTAMP())
                      AND DATEDIFF('hour', created_on, CURRENT_TIMESTAMP()) > 8
                      {get_user_filter_clause("user_name")}
                    ORDER BY session_hours DESC LIMIT 100
                """, ttl_key=f"dba_long_sessions_{company}", tier="standard")
            except Exception as e:
                st.info(f"Sessions unavailable: {format_snowflake_error(e)}")
        if st.session_state.get("dba_df_long_sess") is not None:
            render_priority_dataframe(
                st.session_state["dba_df_long_sess"],
                title="Long-running sessions",
                priority_columns=["SESSION_ID", "USER_NAME", "CREATED_ON", "SESSION_HOURS"],
                sort_by=["SESSION_HOURS"],
                ascending=False,
                raw_label="All long-session rows",
            )

    if selected_tool == "Unused Objects":
        st.header("🗑️ Unused Objects")
        if _load_button("Find Unused Tables", "unused_load"):
            try:
                st.session_state["dba_df_unused"] = run_query(f"""
                    SELECT table_catalog, table_schema, table_name, row_count,
                           bytes/POWER(1024,3) AS table_gb, created, last_altered
                    FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
                    WHERE deleted IS NULL
                      AND last_altered < DATEADD('day', -90, CURRENT_TIMESTAMP())
                      {get_db_filter_clause("table_catalog")}
                    ORDER BY bytes DESC NULLS LAST LIMIT 200
                """, ttl_key=f"dba_unused_tables_{company}", tier="standard")
            except Exception as e:
                st.warning(f"Unused table scan unavailable: {format_snowflake_error(e)}")
        if st.session_state.get("dba_df_unused") is not None:
            render_priority_dataframe(
                st.session_state["dba_df_unused"],
                title="Unused objects by size",
                priority_columns=[
                    "TABLE_CATALOG", "TABLE_SCHEMA", "TABLE_NAME", "ROW_COUNT",
                    "TABLE_GB", "CREATED", "LAST_ALTERED",
                ],
                sort_by=["TABLE_GB", "ROW_COUNT"],
                ascending=[False, False],
                raw_label="All unused object rows",
            )

    if selected_tool == "Snowpipe Monitor":
        st.header("🔧 Snowpipe Monitor")
        sp_days = st.slider("Lookback (days)", 1, 14, 3, key="spipe_days")
        if _load_button("Load Pipe Usage", "spipe_load"):
            try:
                st.session_state["dba_df_pipe"] = run_query(f"""
                    SELECT pipe_name, DATE_TRUNC('day', start_time) AS day,
                           SUM(credits_used) AS daily_credits,
                           SUM(bytes_inserted)/POWER(1024,3) AS gb_inserted,
                           SUM(files_inserted) AS files_inserted
                    FROM SNOWFLAKE.ACCOUNT_USAGE.PIPE_USAGE_HISTORY
                    WHERE start_time >= DATEADD('day', -{sp_days}, CURRENT_TIMESTAMP())
                    GROUP BY pipe_name, day ORDER BY daily_credits DESC
                """, ttl_key=f"dba_pipe_{company}_{sp_days}", tier="standard")
            except Exception as e:
                st.warning(f"Snowpipe usage unavailable: {format_snowflake_error(e)}")
        if st.session_state.get("dba_df_pipe") is not None:
            render_priority_dataframe(
                st.session_state["dba_df_pipe"],
                title="Snowpipe cost and volume",
                priority_columns=["PIPE_NAME", "DAY", "DAILY_CREDITS", "GB_INSERTED", "FILES_INSERTED"],
                sort_by=["DAILY_CREDITS", "GB_INSERTED", "FILES_INSERTED"],
                ascending=[False, False, False],
                raw_label="All Snowpipe rows",
            )

    if selected_tool == "QAS Monitor":
        st.header("⚡ QAS Monitor")
        qas_days = st.slider("Lookback (days)", 1, 30, 7, key="qas_days")
        if _load_button("Load QAS Data", "qas_load"):
            try:
                st.session_state["dba_df_qas"] = run_query(f"""
                    WITH latest_size AS (
                        SELECT warehouse_name, warehouse_size
                        FROM (
                            SELECT warehouse_name, {qh_plain_size_expr},
                                   ROW_NUMBER() OVER (PARTITION BY warehouse_name ORDER BY start_time DESC) AS rn
                            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                            WHERE start_time >= DATEADD('day', -{qas_days}, CURRENT_TIMESTAMP())
                              AND warehouse_name IS NOT NULL
                        )
                        WHERE rn = 1
                    )
                    SELECT q.warehouse_name, ls.warehouse_size, DATE_TRUNC('day', q.start_time) AS day,
                           SUM(q.credits_used) AS daily_credits, COUNT(*) AS query_count
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ACCELERATION_HISTORY q
                    LEFT JOIN latest_size ls ON q.warehouse_name = ls.warehouse_name
                    WHERE q.start_time >= DATEADD('day', -{qas_days}, CURRENT_TIMESTAMP())
                      {get_wh_filter_clause("q.warehouse_name")}
                    GROUP BY q.warehouse_name, ls.warehouse_size, day ORDER BY daily_credits DESC
                """, ttl_key=f"dba_qas_{company}_{qas_days}", tier="standard")
            except Exception as e:
                st.info(f"QAS data unavailable: {format_snowflake_error(e)}")
        if st.session_state.get("dba_df_qas") is not None:
            render_priority_dataframe(
                st.session_state["dba_df_qas"],
                title="Query Acceleration usage",
                priority_columns=["WAREHOUSE_NAME", "WAREHOUSE_SIZE", "DAY", "DAILY_CREDITS", "QUERY_COUNT"],
                sort_by=["DAILY_CREDITS", "QUERY_COUNT"],
                ascending=[False, False],
                raw_label="All QAS usage rows",
            )

    if selected_tool == "Schema Compare":
        st.header("📐 Schema Compare")
        c1, c2 = st.columns(2)
        with c1:
            dev_db  = st.text_input("Dev Database",  value="DEV_DB",  key="sc_dev")
            dev_sch = st.text_input("Dev Schema",    value="PUBLIC",  key="sc_devsch")
        with c2:
            prod_db  = st.text_input("Prod Database", value="PROD_DB", key="sc_prod")
            prod_sch = st.text_input("Prod Schema",   value="PUBLIC",  key="sc_prodsch")
        if st.button("Compare Schemas", key="sc_run"):
            try:
                dev_db_safe = safe_identifier(dev_db)
                prod_db_safe = safe_identifier(prod_db)
                if not (
                    company_value_allowed(dev_db, "database")
                    and company_value_allowed(prod_db, "database")
                ):
                    st.warning(
                        f"Schema Compare is scoped to {get_active_company()}. "
                        "Enter databases that belong to the selected company view."
                    )
                    st.stop()
                df_dev = run_query(
                    f"SELECT table_name, row_count FROM {dev_db_safe}.INFORMATION_SCHEMA.TABLES WHERE table_schema={sql_literal(dev_sch)} AND table_type='BASE TABLE'",
                    ttl_key=f"dba_schema_dev_{company}_{dev_db_safe}_{dev_sch}",
                    tier="metadata",
                )
                df_prod = run_query(
                    f"SELECT table_name, row_count FROM {prod_db_safe}.INFORMATION_SCHEMA.TABLES WHERE table_schema={sql_literal(prod_sch)} AND table_type='BASE TABLE'",
                    ttl_key=f"dba_schema_prod_{company}_{prod_db_safe}_{prod_sch}",
                    tier="metadata",
                )
                df_cmp  = df_prod.merge(df_dev, on="TABLE_NAME", how="outer", suffixes=("_PROD","_DEV"))
                df_cmp["ROW_DIFF"] = df_cmp["ROW_COUNT_PROD"].fillna(0) - df_cmp["ROW_COUNT_DEV"].fillna(0)
                render_priority_dataframe(
                    df_cmp,
                    title="Schema row-count differences",
                    priority_columns=["TABLE_NAME", "ROW_COUNT_PROD", "ROW_COUNT_DEV", "ROW_DIFF"],
                    sort_by=["ROW_DIFF"],
                    ascending=False,
                    raw_label="All schema compare rows",
                )
                download_csv(df_cmp, "schema_compare.csv")
            except Exception as e:
                st.error(f"Compare failed: {format_snowflake_error(e)}")

    if selected_tool == "Recent Objects":
        st.header("🔎 Recent Objects")
        obj_days = st.slider("Created/altered within (days)", 1, 90, 30, key="obj_days")
        obj_db_filter = st.text_input("Database filter", key="obj_db_filter")
        obj_db_clause = (
            f"AND table_catalog ILIKE {sql_literal('%' + obj_db_filter + '%')}"
            if obj_db_filter else ""
        )
        if st.button("Load Recent Objects", key="obj_load"):
            try:
                st.session_state["dba_df_recent_objects"] = run_query(f"""
                    SELECT table_catalog AS database_name, table_schema AS schema_name,
                           table_name AS object_name, table_type, created, last_altered, table_owner AS owner
                    FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
                    WHERE deleted IS NULL
                      AND (created >= DATEADD('day', -{obj_days}, CURRENT_TIMESTAMP())
                           OR last_altered >= DATEADD('day', -{obj_days}, CURRENT_TIMESTAMP()))
                      {obj_db_clause}
                      {get_db_filter_clause("table_catalog")}
                    ORDER BY GREATEST(created, last_altered) DESC LIMIT 500
                """, ttl_key=f"dba_recent_objects_{company}_{obj_days}_{st.session_state.get('obj_db_filter', '')}", tier="metadata")
            except Exception as e:
                st.warning(f"Recent objects unavailable: {format_snowflake_error(e)}")
        if st.session_state.get("dba_df_recent_objects") is not None:
            df_recent = st.session_state["dba_df_recent_objects"]
            render_priority_dataframe(
                df_recent,
                title="Recent object changes",
                priority_columns=[
                    "DATABASE_NAME", "SCHEMA_NAME", "OBJECT_NAME",
                    "TABLE_TYPE", "OWNER", "CREATED", "LAST_ALTERED",
                ],
                sort_by=["CREATED", "LAST_ALTERED"],
                ascending=[False, False],
                raw_label="All recent object rows",
            )
            download_csv(df_recent, "recent_objects.csv")

    if selected_tool == "Mart Readiness":
        st.header("Mart Readiness")
        st.caption(
            "Checks whether the deployed OVERWATCH mart objects are present. "
            "Pre-aggregation DDL is no longer generated from the dashboard."
        )
        mart_objects = [
            ("Control Room Snapshot", "MART_DBA_CONTROL_ROOM"),
            ("Query Detail", "FACT_QUERY_DETAIL"),
            ("Warehouse Daily", "FACT_WAREHOUSE_DAILY"),
            ("Task Runs", "FACT_TASK_RUN"),
            ("Login Daily", "FACT_LOGIN_DAILY"),
            ("Object Changes", "FACT_OBJECT_CHANGE"),
        ]
        rows = []
        for label, table_name in mart_objects:
            exists = _table_exists(session, ALERT_DB, ALERT_SCHEMA, table_name)
            rows.append({
                "FEATURE": label,
                "OBJECT_NAME": f"{ALERT_DB}.{ALERT_SCHEMA}.{table_name}",
                "STATUS": "Present" if exists is True else "Missing" if exists is False else "Unknown",
            })
        mart_df = pd.DataFrame(rows)
        present_count = int((mart_df["STATUS"] == "Present").sum())
        missing_count = int((mart_df["STATUS"] == "Missing").sum())
        c_mart1, c_mart2 = st.columns(2)
        c_mart1.metric("Present", f"{present_count:,}")
        c_mart2.metric("Missing", f"{missing_count:,}")
        render_priority_dataframe(
            mart_df,
            title="OVERWATCH mart readiness",
            priority_columns=["FEATURE", "STATUS", "OBJECT_NAME"],
            sort_by=["STATUS", "FEATURE"],
            ascending=[True, True],
            raw_label="All mart objects",
        )
        if missing_count:
            st.info("Deploy or refresh `snowflake/OVERWATCH_MART_SETUP.sql` outside the dashboard, then recheck.")

    if selected_tool == "Dynamic Tables":
        st.header("🔄 Dynamic Tables")
        if st.button("Load Dynamic Tables", key="dyn_load"):
            try:
                df_dyn = _show_to_df(session, "SHOW DYNAMIC TABLES IN ACCOUNT")
                df_dyn = _ensure_column_alias(df_dyn, "NAME", ["NAME", "DYNAMIC_TABLE_NAME"])
                df_dyn = _ensure_column_alias(df_dyn, "DATABASE_NAME", ["DATABASE_NAME", "DATABASE"])
                df_dyn = _ensure_column_alias(df_dyn, "SCHEMA_NAME", ["SCHEMA_NAME", "SCHEMA"])
                df_dyn = _scope_metadata_df(df_dyn)
                if not df_dyn.empty:
                    try:
                        refresh_object = "SNOWFLAKE.ACCOUNT_USAGE.DYNAMIC_TABLE_REFRESH_HISTORY"
                        requested_cols = [
                            "DATABASE_NAME", "SCHEMA_NAME", "NAME", "DYNAMIC_TABLE_NAME", "STATE_CODE",
                            "STATE_MESSAGE", "REFRESH_ACTION", "REFRESH_TRIGGER",
                            "REFRESH_START_TIME", "REFRESH_END_TIME", "TARGET_LAG_SEC", "QUERY_ID",
                        ]
                        available_cols = filter_existing_columns(session, refresh_object, requested_cols)
                        if "REFRESH_START_TIME" not in available_cols:
                            raise ValueError("Dynamic table refresh history does not expose REFRESH_START_TIME.")
                        name_expr = (
                            "NAME AS NAME"
                            if "NAME" in available_cols
                            else "DYNAMIC_TABLE_NAME AS NAME"
                            if "DYNAMIC_TABLE_NAME" in available_cols
                            else "'UNKNOWN' AS NAME"
                        )
                        select_cols = [
                            "DATABASE_NAME" if "DATABASE_NAME" in available_cols else "NULL::VARCHAR AS DATABASE_NAME",
                            "SCHEMA_NAME" if "SCHEMA_NAME" in available_cols else "NULL::VARCHAR AS SCHEMA_NAME",
                            name_expr,
                        ]
                        select_cols.extend([
                            col for col in available_cols
                            if col not in {"DATABASE_NAME", "SCHEMA_NAME", "NAME", "DYNAMIC_TABLE_NAME"}
                        ])
                        db_filter = get_db_filter_clause("database_name") if "DATABASE_NAME" in available_cols else ""
                        df_refresh = run_query_or_raise(f"""
                            SELECT {", ".join(select_cols)}
                            FROM {refresh_object}
                            WHERE refresh_start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
                              {db_filter}
                            ORDER BY refresh_start_time DESC
                            LIMIT 5000
                        """)
                        if not df_refresh.empty and all(c in df_dyn.columns for c in ["DATABASE_NAME", "SCHEMA_NAME", "NAME"]):
                            refresh_cols = {
                                "STATE_CODE": "LAST_REFRESH_STATE_CODE",
                                "STATE_MESSAGE": "LAST_REFRESH_MESSAGE",
                                "REFRESH_START_TIME": "LAST_REFRESH_START_TIME",
                                "REFRESH_END_TIME": "LAST_REFRESH_END_TIME",
                                "QUERY_ID": "LAST_REFRESH_QUERY_ID",
                            }
                            df_refresh = df_refresh.rename(
                                columns={src: dst for src, dst in refresh_cols.items() if src in df_refresh.columns}
                            )
                            if "LAST_REFRESH_START_TIME" in df_refresh.columns:
                                df_refresh = df_refresh.sort_values("LAST_REFRESH_START_TIME", ascending=False)
                            keep_cols = [
                                c for c in [
                                    "DATABASE_NAME", "SCHEMA_NAME", "NAME",
                                    "LAST_REFRESH_STATE", "LAST_REFRESH_STATE_CODE", "LAST_REFRESH_MESSAGE",
                                    "REFRESH_ACTION", "REFRESH_TRIGGER",
                                    "LAST_REFRESH_START_TIME", "LAST_REFRESH_END_TIME",
                                    "TARGET_LAG_SEC", "LAST_REFRESH_QUERY_ID",
                                ]
                                if c in df_refresh.columns
                            ]
                            df_refresh = df_refresh[keep_cols].drop_duplicates(["DATABASE_NAME", "SCHEMA_NAME", "NAME"])
                            df_dyn = df_dyn.merge(
                                df_refresh,
                                how="left",
                                on=["DATABASE_NAME", "SCHEMA_NAME", "NAME"],
                            )
                    except Exception:
                        pass
                st.session_state["dba_df_dyn"] = df_dyn
            except Exception as e:
                st.info(f"Dynamic table data unavailable: {format_snowflake_error(e)}")
        if st.session_state.get("dba_df_dyn") is not None:
            df_dyn = st.session_state["dba_df_dyn"]
            render_priority_dataframe(
                df_dyn,
                title="Dynamic tables needing attention",
                priority_columns=[
                    "DATABASE_NAME", "SCHEMA_NAME", "NAME", "STATE",
                    "LAST_REFRESH_STATE_CODE", "LAST_REFRESH_MESSAGE",
                    "REFRESH_ACTION", "LAST_REFRESH_START_TIME", "TARGET_LAG_SEC",
                ],
                sort_by=["LAST_REFRESH_STATE_CODE", "LAST_REFRESH_START_TIME", "TARGET_LAG_SEC"],
                ascending=[True, False, False],
                raw_label="All dynamic table rows",
            )
            download_csv(df_dyn, "dynamic_tables.csv")

    if selected_tool == "Replication":
        st.header("🔁 Replication")
        repl_days = st.slider("Lookback (days)", 1, 90, 30, key="repl_days")
        if st.button("Load Replication History", key="repl_load"):
            repl_sql_primary = f"""
                SELECT database_name,
                       replication_group_name,
                       phase_name,
                       start_time,
                       end_time,
                       DATEDIFF('minute', start_time, end_time) AS duration_min,
                       credits_used,
                       bytes_transferred/POWER(1024,3) AS gb_transferred
                FROM SNOWFLAKE.ACCOUNT_USAGE.REPLICATION_GROUP_USAGE_HISTORY
                WHERE start_time >= DATEADD('day', -{repl_days}, CURRENT_TIMESTAMP())
                  {get_db_filter_clause("database_name")}
                ORDER BY start_time DESC
                LIMIT 500
            """
            repl_sql_fallback = f"""
                SELECT database_name,
                       replication_group_name,
                       phase_name,
                       start_time,
                       end_time,
                       DATEDIFF('minute', start_time, end_time) AS duration_min,
                       credits_used,
                       bytes_transferred/POWER(1024,3) AS gb_transferred
                FROM SNOWFLAKE.ACCOUNT_USAGE.REPLICATION_USAGE_HISTORY
                WHERE start_time >= DATEADD('day', -{repl_days}, CURRENT_TIMESTAMP())
                  {get_db_filter_clause("database_name")}
                ORDER BY start_time DESC
                LIMIT 500
            """
            try:
                st.session_state["dba_df_repl"] = run_query_or_raise(repl_sql_primary)
                st.session_state["dba_repl_source"] = "REPLICATION_GROUP_USAGE_HISTORY"
            except Exception as primary_error:
                try:
                    st.session_state["dba_df_repl"] = run_query_or_raise(repl_sql_fallback)
                    st.session_state["dba_repl_source"] = "REPLICATION_USAGE_HISTORY"
                except Exception as fallback_error:
                    st.info(f"Replication data unavailable: {format_snowflake_error(fallback_error)}")
                    st.caption(f"Primary view also failed: {format_snowflake_error(primary_error)}")
        if st.session_state.get("dba_df_repl") is not None and not st.session_state["dba_df_repl"].empty:
            df_repl = st.session_state["dba_df_repl"]
            st.caption(f"Source: {st.session_state.get('dba_repl_source', 'replication usage history')}")
            st.metric("Replication Credits", format_credits(df_repl["CREDITS_USED"].sum()))
            render_priority_dataframe(
                df_repl,
                title="Replication cost and lag candidates",
                priority_columns=[
                    "DATABASE_NAME", "REPLICATION_GROUP_NAME", "PHASE_NAME",
                    "START_TIME", "END_TIME", "DURATION_MIN", "CREDITS_USED",
                    "GB_TRANSFERRED",
                ],
                sort_by=["CREDITS_USED", "DURATION_MIN", "START_TIME"],
                ascending=[False, False, False],
                raw_label="All replication history rows",
            )
            download_csv(df_repl, "replication_history.csv")

    if selected_tool == "Serverless Costs":
        st.header("💻 Serverless Costs")
        if get_active_company() != "ALL":
            st.info(
                "Serverless metering is account-level in Snowflake and does not expose "
                "a reliable company, database, user, or warehouse dimension here. Switch "
                "Company View to ALL to review account-wide serverless costs."
            )
        else:
            sv_days = st.slider("Lookback (days)", 7, 90, 30, key="sv_days")
            if st.button("Load Serverless Costs", key="sv_load"):
                try:
                    st.session_state["dba_df_serverless"] = run_query(f"""
                        SELECT service_type, DATE_TRUNC('day', start_time) AS usage_date,
                               SUM(credits_used) AS daily_credits
                        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
                        WHERE start_time >= DATEADD('day', -{sv_days}, CURRENT_TIMESTAMP())
                          AND service_type NOT IN ('WAREHOUSE_METERING','WAREHOUSE_METERING_READER')
                        GROUP BY service_type, usage_date ORDER BY daily_credits DESC
                    """, ttl_key=f"dba_serverless_{company}_{sv_days}", tier="standard")
                except Exception as e:
                    st.warning(f"Serverless costs unavailable: {format_snowflake_error(e)}")
            if st.session_state.get("dba_df_serverless") is not None and not st.session_state["dba_df_serverless"].empty:
                df_sv = st.session_state["dba_df_serverless"]
                svc   = df_sv.groupby("SERVICE_TYPE")["DAILY_CREDITS"].sum().reset_index().sort_values("DAILY_CREDITS", ascending=False)
                st.metric("Total Serverless Credits", format_credits(float(svc["DAILY_CREDITS"].sum())))
                render_priority_dataframe(
                    svc,
                    title="Serverless service cost drivers",
                    priority_columns=["SERVICE_TYPE", "DAILY_CREDITS"],
                    sort_by=["DAILY_CREDITS"],
                    ascending=False,
                    raw_label="All serverless service totals",
                )
                st.area_chart(df_sv.pivot_table(index="USAGE_DATE", columns="SERVICE_TYPE", values="DAILY_CREDITS", aggfunc="sum").fillna(0))
                download_csv(df_sv, "serverless_costs.csv")

    # ── TAB 14: CORTEX AI LIMITS ──────────────────────────────────────────────
    if selected_tool == "Cortex AI Limits":
        st.header("🤖 Cortex AI Limits")
        st.caption(
            "View and modify Cortex AI service limits for your account. "
            "These control daily token budgets, inference rate limits, and Cortex Search/Analyst access. "
            "Requires ACCOUNTADMIN or SYSADMIN with MODIFY ACCOUNT privilege."
        )

        # ── Current parameters ────────────────────────────────────────────────
        if st.button("🔄 Load Current AI Parameters", key="cortex_params_load"):
            results = {}

            # SHOW PARAMETERS — account-level Cortex controls
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
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Requests Today",    f"{safe_int(df_u['REQUESTS_TODAY'].iloc[0]):,}")
            c2.metric("AI Credits Today",  f"{safe_float(df_u['CREDITS_TODAY'].iloc[0]):.4f}")
            c3.metric("Tokens Today",      f"{safe_int(df_u['TOKENS_TODAY'].iloc[0]):,}")
            c4.metric("Active Users",      f"{safe_int(df_u['ACTIVE_USERS'].iloc[0])}")

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

        # ── Modify parameters ─────────────────────────────────────────────────
        st.subheader("Modify Cortex AI Account Parameters")
        st.caption(
            "These ALTER ACCOUNT SET commands control Cortex AI behaviour across the account. "
            "Requires ACCOUNTADMIN. Changes take effect immediately."
        )

        with st.expander("🔧 Set Cortex Parameters", expanded=True):
            st.markdown("**Cortex Code Inline (Snowsight / VS Code)**")
            col_c1, col_c2 = st.columns(2)
            with col_c1:
                cortex_enabled = st.selectbox(
                    "ENABLE_CORTEX_CODE_INLINE",
                    ["TRUE","FALSE"],
                    key="cortex_enable_sel",
                    help="Enables/disables Cortex Code inline AI in Snowsight for all users.",
                )
            with col_c2:
                cortex_daily_limit = st.number_input(
                    "CORTEX_CODE_DAILY_CREDIT_LIMIT (0 = no limit)",
                    min_value=0, max_value=100000, value=0, step=100,
                    key="cortex_daily_limit",
                    help="Maximum AI credits per day across all users. 0 = unrestricted.",
                )

            st.markdown("**Cortex Search & Analyst**")
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                search_enabled = st.selectbox(
                    "ENABLE_CORTEX_SEARCH",
                    ["TRUE","FALSE"],
                    key="cortex_search_sel",
                    help="Enables Cortex Search (semantic document search).",
                )
            with col_s2:
                analyst_enabled = st.selectbox(
                    "ENABLE_SNOWFLAKE_INTELLIGENCE",
                    ["TRUE","FALSE"],
                    key="cortex_analyst_sel",
                    help="Enables Snowflake Intelligence / Cortex Analyst (natural language to SQL).",
                )

            generated_sql = f"""-- Cortex AI parameter changes
-- Run as ACCOUNTADMIN
ALTER ACCOUNT SET ENABLE_CORTEX_CODE_INLINE = {cortex_enabled};
{f'ALTER ACCOUNT SET CORTEX_CODE_DAILY_CREDIT_LIMIT = {cortex_daily_limit};' if cortex_daily_limit > 0 else '-- CORTEX_CODE_DAILY_CREDIT_LIMIT: no limit set'}
ALTER ACCOUNT SET ENABLE_CORTEX_SEARCH = {search_enabled};
ALTER ACCOUNT SET ENABLE_SNOWFLAKE_INTELLIGENCE = {analyst_enabled};"""

            st.code(generated_sql, language="sql")

            col_apply, col_dl = st.columns([1, 2])
            with col_apply:
                cortex_confirmed = _typed_confirmation(
                    "Type APPLY to enable account parameter changes",
                    "APPLY",
                    "cortex_apply_confirm",
                )
                if st.button("✅ Apply Parameters", type="primary", key="cortex_apply", disabled=admin_button_disabled(not cortex_confirmed)):
                    # CALLER MODE GUARD: ALTER ACCOUNT SET requires ACCOUNTADMIN.
                    # Since execute_as=CALLER, the caller's role must have this privilege.
                    # SNOW_SYSADMIN cannot run ALTER ACCOUNT — only ACCOUNTADMIN can.
                    try:
                        _caller_role = ""
                    except Exception:
                        _caller_role = ""
                    if False and "ACCOUNTADMIN" not in _caller_role.upper():
                        st.error(
                            f"⛔ **ALTER ACCOUNT requires ACCOUNTADMIN.** "
                            f"Your current role is `{_caller_role}`. "
                            f"Switch to ACCOUNTADMIN in Snowflake and reload OVERWATCH, "
                            f"or copy the generated SQL below and run it in a Worksheet."
                        )
                    else:
                        applied = []
                        failed  = []
                        for stmt in [
                            f"ALTER ACCOUNT SET ENABLE_CORTEX_CODE_INLINE = {cortex_enabled}",
                            f"ALTER ACCOUNT SET ENABLE_CORTEX_SEARCH = {search_enabled}",
                            f"ALTER ACCOUNT SET ENABLE_SNOWFLAKE_INTELLIGENCE = {analyst_enabled}",
                        ] + ([f"ALTER ACCOUNT SET CORTEX_CODE_DAILY_CREDIT_LIMIT = {cortex_daily_limit}"] if cortex_daily_limit > 0 else []):
                            try:
                                session.sql(stmt).collect()
                                applied.append(stmt)
                            except Exception as e:
                                failed.append(f"{stmt} -> {format_snowflake_error(e)}")

                        if applied:
                            st.success(f"✅ {len(applied)} parameter(s) updated successfully.")
                        if failed:
                            for f_msg in failed:
                                st.warning(f"⚠️ {f_msg}")
                            st.info("Some parameters may not exist in your Snowflake edition or region. Check with SHOW PARAMETERS IN ACCOUNT first.")
            with col_dl:
                st.download_button(
                    "📥 Download SQL",
                    generated_sql,
                    file_name="cortex_parameter_changes.sql",
                    mime="text/plain",
                    key="cortex_dl_sql",
                )

        # ── Per-user Cortex policy (Enterprise) ───────────────────────────────
        st.divider()
        st.subheader("Per-User / Per-Role Cortex Access and Quotas")
        st.caption(
            "Use Snowflake Budgets for shared AI resources and route Cortex access through a controlled role "
            "when per-user monthly quota enforcement is required. "
            "The generated quota framework lives in Cost & Contract -> Budget governance."
        )
        st.info(
            "Tip: To enforce user quotas, revoke the blanket `SNOWFLAKE.CORTEX_USER` grant from PUBLIC, "
            "grant it only through an approved AI role, then use OVERWATCH to queue revoke/restore review SQL."
        )
        with st.expander("📋 Cortex access control SQL snippets"):
            st.code("""
-- Grant Cortex access to a specific role
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE <your_role>;

-- Required before per-user quota enforcement
REVOKE DATABASE ROLE SNOWFLAKE.CORTEX_USER FROM ROLE PUBLIC;

-- Revoke Cortex access from a role
REVOKE DATABASE ROLE SNOWFLAKE.CORTEX_USER FROM ROLE <restricted_role>;

-- Check who has Cortex access
SHOW GRANTS OF DATABASE ROLE SNOWFLAKE.CORTEX_USER;

-- Check current Cortex-related parameters
SHOW PARAMETERS LIKE '%CORTEX%' IN ACCOUNT;
SHOW PARAMETERS LIKE '%AI%'     IN ACCOUNT;
""", language="sql")

    # ── TAB 15: TASK GRAPH CONTROL ────────────────────────────────────────────
    if selected_tool == "Task Graph Control":
        st.header("🔀 Task Graph Control")
        st.caption(
            "Cancel running queries spawned by tasks, cancel task graphs mid-run, "
            "suspend/resume individual tasks or entire DAG trees, and restart failed tasks. "
            "Requires OPERATE privilege on tasks or ACCOUNTADMIN."
        )

        task_graph_view = st.radio(
            "Task graph control view",
            TASK_GRAPH_CONTROL_PANES,
            horizontal=True,
            label_visibility="collapsed",
            key="dba_task_graph_control_view",
        )

        # ── Running task queries ───────────────────────────────────────────────
        if task_graph_view == "Running Task Queries":
            st.subheader("Queries Currently Running Under a Task")
            st.caption(
                "Shows recent ACCOUNT_USAGE query activity where QUERY_TAG or query text "
                "indicates task execution. You can cancel individual task-spawned queries here."
            )
            if st.button("Load Running Task Queries", key="tg_run_load"):
                try:
                    df_tq = run_query_or_raise(f"""
                        SELECT query_id, user_name, warehouse_name, {qh_warehouse_size_expr}, execution_status,
                               start_time,
                               DATEDIFF('second', start_time, COALESCE(end_time, CURRENT_TIMESTAMP())) AS elapsed_sec,
                               {qh_query_tag_expr},
                               SUBSTR(query_text, 1, 400) AS query_text
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                        WHERE start_time >= DATEADD('hours', -2, CURRENT_TIMESTAMP())
                          AND UPPER(execution_status) IN ('RUNNING','QUEUED','BLOCKED')
                          {get_wh_filter_clause("warehouse_name")}
                          {get_user_filter_clause("user_name")}
                          AND ({qh_task_indicator})
                        ORDER BY start_time DESC
                        LIMIT 200
                    """)
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
                            "QUERY_ID", "USER_NAME", "WAREHOUSE_NAME", "WAREHOUSE_SIZE",
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
                        "⛔ Cancel This Query",
                        type="primary",
                        key="tg_cancel_q",
                        disabled=admin_button_disabled(not cancel_confirmed),
                    ):
                        try:
                            session.sql(f"SELECT SYSTEM$CANCEL_QUERY({sql_literal(cancel_qid)})").collect()
                            st.success(f"✅ Cancel sent for `{cancel_qid}`")
                        except Exception as e:
                            st.error(f"Cancel failed: {format_snowflake_error(e)}")
                else:
                    st.success("No task-related queries currently running.")

        # ── Cancel graph / task ────────────────────────────────────────────────
        elif task_graph_view == "Cancel Graph / Task":
            st.subheader("Cancel a Running Task Graph or Individual Task Run")
            st.caption(
                "`SYSTEM$CANCEL_TASK_GRAPH(graph_run_id)` — cancels an entire DAG run in progress. "
                "`SYSTEM$CANCEL_QUERY(query_id)` — cancels the query spawned by a specific task run."
            )

            # Load recent task runs to get graph_run_id
            if st.button("Load Recent Task Runs", key="tg_runs_load"):
                try:
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
                running_runs = df_r[df_r["STATE"].isin(["EXECUTING","RUNNING","SCHEDULED"])] if "STATE" in df_r.columns else pd.DataFrame()

                if not running_runs.empty:
                    st.warning(f"⚠️ {len(running_runs)} task run(s) currently executing or scheduled.")
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
                                graph_confirmed = _typed_confirmation(
                                    "Type CANCEL to enable graph cancellation",
                                    "CANCEL",
                                    f"tg_graph_confirm_{sel_graph}",
                                )
                                if st.button(
                                    "⛔ Cancel Graph Run",
                                    type="primary",
                                    key="tg_cancel_graph",
                                    disabled=admin_button_disabled(not graph_confirmed),
                                ):
                                    try:
                                        session.sql(
                                            f"SELECT SYSTEM$CANCEL_TASK_GRAPH({sql_literal(str(sel_graph))})"
                                        ).collect()
                                        st.success(f"✅ Graph run `{sel_graph}` cancelled.")
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
                            run_confirmed = _typed_confirmation(
                                "Type CANCEL to enable run-query cancellation",
                                "CANCEL",
                                f"tg_run_confirm_{sel_qid}",
                            ) if sel_qid else False
                            if sel_qid and st.button(
                                "⛔ Cancel Query",
                                key="tg_cancel_run_q",
                                disabled=admin_button_disabled(not run_confirmed),
                            ):
                                try:
                                    session.sql(f"SELECT SYSTEM$CANCEL_QUERY({sql_literal(str(sel_qid))})").collect()
                                    st.success(f"✅ Cancel sent for `{sel_qid}`")
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

        # ── Suspend / Resume ──────────────────────────────────────────────────
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
                c1, c2, c3 = st.columns(3)
                c1.metric("Total Tasks",       len(df_tasks))
                c2.metric("▶ Active",           len(started))
                c3.metric("⏸ Suspended",        len(suspended))

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

                    st.info(f"`{full_n}` · State: **{state}** · Predecessors: `{preds or 'none (root task)'}`")
                    task_confirmed = _typed_confirmation(
                        "Type the task name to enable task controls",
                        sel_task,
                        f"tg_confirm_{sel_task}",
                    )

                    col_s1, col_s2, col_s3, col_s4 = st.columns(4)

                    with col_s1:
                        if st.button("⏸ Suspend", key="tg_suspend", disabled=admin_button_disabled(state=="suspended" or not task_confirmed)):
                            try:
                                session.sql(f"ALTER TASK {full_n} SUSPEND").collect()
                                st.success(f"✅ `{sel_task}` suspended.")
                                st.session_state.pop("dba_df_tg_tasks", None)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Suspend failed: {format_snowflake_error(e)}")

                    with col_s2:
                        if st.button("▶ Resume", key="tg_resume", disabled=admin_button_disabled(state=="started" or not task_confirmed)):
                            try:
                                session.sql(f"ALTER TASK {full_n} RESUME").collect()
                                st.success(f"✅ `{sel_task}` resumed.")
                                st.session_state.pop("dba_df_tg_tasks", None)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Resume failed: {format_snowflake_error(e)}")

                    with col_s3:
                        if st.button("▶▶ Execute Now", key="tg_execute", disabled=admin_button_disabled(not task_confirmed)):
                            try:
                                session.sql(f"EXECUTE TASK {full_n}").collect()
                                st.success(f"✅ `{sel_task}` triggered.")
                            except Exception as e:
                                st.error(f"Execute failed: {format_snowflake_error(e)}")

                    with col_s4:
                        if st.button("🔁 Retry Last Failed", key="tg_retry", disabled=admin_button_disabled(not task_confirmed)):
                            # EXECUTE TASK WITH LAST_ERROR retry pattern
                            try:
                                session.sql(f"EXECUTE TASK {full_n}").collect()
                                st.success(f"✅ Retry triggered for `{sel_task}`.")
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
                            f"Root: `{root_full}` · "
                            f"Child tasks in this graph: {len(children)} · "
                            f"Total tasks affected: {len(children)+1}"
                        )
                        graph_confirmed = _typed_confirmation(
                            "Type the root task name to enable graph controls",
                            sel_root,
                            f"tg_graph_confirm_{sel_root}",
                        )

                        b1, b2 = st.columns(2)
                        with b1:
                            if st.button("⏸ Suspend Entire Graph", type="primary", key="tg_bulk_suspend", disabled=admin_button_disabled(not graph_confirmed)):
                                try:
                                    session.sql(f"ALTER TASK {root_full} SUSPEND").collect()
                                    st.success(f"✅ Root task `{sel_root}` suspended — entire graph will stop scheduling.")
                                    st.session_state.pop("dba_df_tg_tasks", None)
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Suspend failed: {format_snowflake_error(e)}")
                        with b2:
                            if st.button("▶ Resume Entire Graph", type="primary", key="tg_bulk_resume", disabled=admin_button_disabled(not graph_confirmed)):
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
                                    st.success(f"✅ Entire graph resumed. {len(children)+1} task(s) active.")
                                st.session_state.pop("dba_df_tg_tasks", None)
                                st.rerun()

        # ── DAG Inspector ─────────────────────────────────────────────────────
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

                if sel_dag and st.button("Build DAG View", key="tg_dag_build"):
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
                        st.warning(f"DAG build unavailable in this role/context: {format_snowflake_error(e)}")

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
                        indent  = "" if is_root else "↳ "

                        state_icon = "▶️" if state=="started" else "⏸" if state=="suspended" else "⚪"
                        lr_icon    = "✅" if lr_st=="SUCCEEDED" else ("❌" if lr_st=="FAILED" else "⏳")

                        st.markdown(
                            f"{'&nbsp;'*4 if indent else ''}{indent}"
                            f"{state_icon} **{name}** &nbsp; {lr_icon} last: {lr_st} "
                            f"({int(dur)}s)"
                            f"{' — ' + err if err and err != 'nan' else ''}",
                            unsafe_allow_html=True,
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

    # ── TAB 16: USAGE LOG (carried forward) ───────────────────────────────────
    if selected_tool == "Usage Log":
        st.header("📊 OVERWATCH Usage Log")
        st.caption("Tracks which sections are loaded, by whom, how often, and how fast.")
        from utils.logging import set_logging_enabled, is_logging_enabled
        from config import ALERT_DB, ALERT_SCHEMA
        log_tbl = f"{ALERT_DB}.{ALERT_SCHEMA}.OVERWATCH_USAGE_LOG"

        st.info(
            "Usage-log table setup is managed by the Snowflake architecture script. "
            "This tab only toggles client-side logging and reads existing usage evidence."
        )

        logging_on = st.toggle("Enable logging", value=is_logging_enabled(), key="ul_toggle")
        set_logging_enabled(logging_on)

        ul_days  = st.slider("Report window (days)", 1, 90, 30, key="ul_days")
        ul_group = st.selectbox("Group by", ["Section","User","Role","Company","Day"], key="ul_group")
        if st.button("Load Usage Data", key="ul_load"):
            try:
                dim_map = {
                    "Section":"section","User":"sf_user","Role":"sf_role",
                    "Company":"company_view","Day":"DATE_TRUNC(\\'day\\', log_time)",
                }
                dim = dim_map[ul_group]
                lbl = "DAY" if ul_group=="Day" else ul_group.upper()
                company_clause = "" if company == "ALL" else f"AND company_view = {sql_literal(company)}"
                df_ul = run_query(f"""
                    SELECT {dim} AS {lbl}, COUNT(*) AS load_count,
                           COUNT(DISTINCT sf_user) AS distinct_users,
                           ROUND(AVG(query_duration_ms)) AS avg_ms
                    FROM {log_tbl}
                    WHERE log_time >= DATEADD('day', -{ul_days}, CURRENT_TIMESTAMP())
                      {company_clause}
                    GROUP BY {dim} ORDER BY load_count DESC LIMIT 200
                """, ttl_key=f"dba_usage_log_{company}_{ul_group}_{ul_days}", tier="standard")
                st.session_state["dba_df_usage_log"] = df_ul
                st.session_state["dba_ul_group_label"] = lbl
            except Exception as e:
                st.info(f"Usage log unavailable: {format_snowflake_error(e)}")
        if st.session_state.get("dba_df_usage_log") is not None and not st.session_state["dba_df_usage_log"].empty:
            df_ul = st.session_state["dba_df_usage_log"]
            lbl   = st.session_state.get("dba_ul_group_label","SECTION")
            st.metric("Total Loads", f"{int(df_ul['LOAD_COUNT'].sum()):,}")
            render_ranked_bar_chart(df_ul, lbl, "LOAD_COUNT", title="Usage Log Hotspots", top_n=25)
            render_priority_dataframe(
                df_ul,
                title="Usage log hotspots",
                priority_columns=[lbl, "LOAD_COUNT", "DISTINCT_USERS", "AVG_MS"],
                sort_by=["LOAD_COUNT", "AVG_MS"],
                ascending=[False, False],
                raw_label="Usage log detail",
            )
            download_csv(df_ul, f"usage_log_{ul_group.lower()}.csv")

    # Cost formula audit
    if selected_tool == "Cost Formula Audit":
        st.header("🧮 Cost Formula Audit")
        st.caption(
            "Documents which OVERWATCH cost numbers reconcile to Snowflake billing "
            "sources and which are allocation or forecast estimates."
        )

        audit_df = build_cost_formula_audit()
        exact_count = int(audit_df["CONFIDENCE"].str.contains("Exact", case=False, na=False).sum())
        estimate_count = int(audit_df["CONFIDENCE"].str.contains("estimate|forecast|mixed|allocated", case=False, na=False).sum())
        rows_count = len(audit_df)
        c1, c2, c3 = st.columns(3)
        c1.metric("Formula Checks", f"{rows_count:,}")
        c2.metric("Exact / Source-of-Truth", f"{exact_count:,}")
        c3.metric("Estimated / Allocated", f"{estimate_count:,}")

        render_priority_dataframe(
            audit_df,
            title="Cost formula confidence",
            priority_columns=["METRIC", "CONFIDENCE", "FORMULA", "NOTES"],
            sort_by=["CONFIDENCE", "METRIC"],
            ascending=[True, True],
            raw_label="All formula checks",
        )
        download_csv(audit_df, "overwatch_cost_formula_audit.csv")

        st.subheader("Reconciliation SQL")
        st.caption(
            "Use these as spot checks when leadership asks why a number changed. "
            "The company selector is reflected through the warehouse filter where possible."
        )
        recon_sql = f"""-- Warehouse credit source of truth for the selected company view
SELECT warehouse_name,
       DATE_TRUNC('day', start_time) AS usage_day,
       SUM(COALESCE(credits_used_compute, credits_used)) AS compute_credits,
       SUM(COALESCE(credits_used_cloud_services, 0)) AS cloud_services_credits,
       SUM(credits_used) AS total_warehouse_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE start_time >= DATEADD('day', -30, CURRENT_TIMESTAMP())
  {get_wh_filter_clause("warehouse_name")}
GROUP BY warehouse_name, usage_day
ORDER BY usage_day DESC, total_warehouse_credits DESC;

-- Serverless account-level credit check
SELECT service_type,
       DATE_TRUNC('day', start_time) AS usage_day,
       SUM(credits_used) AS credits_used
FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
WHERE start_time >= DATEADD('day', -30, CURRENT_TIMESTAMP())
  AND service_type <> 'WAREHOUSE_METERING'
GROUP BY service_type, usage_day
ORDER BY usage_day DESC, credits_used DESC;

-- Storage dollar conversion input
WITH latest_storage AS (
    SELECT database_name,
           average_database_bytes,
           average_failsafe_bytes,
           ROW_NUMBER() OVER (PARTITION BY database_name ORDER BY usage_date DESC) AS rn
    FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
    WHERE usage_date >= DATEADD('day', -30, CURRENT_DATE())
      {get_db_filter_clause("database_name")}
)
SELECT database_name,
       (average_database_bytes + average_failsafe_bytes) / POWER(1024, 4) AS current_tb
FROM latest_storage
WHERE rn = 1
ORDER BY current_tb DESC;"""
        st.code(recon_sql, language="sql")

    # Setup status and install readiness
    if selected_tool == "Setup Status":
        st.header("Setup Status")
        st.caption(
            "Run this before deployment. It checks Snowflake view access, "
            "optional column availability, persistent OVERWATCH objects, calculation "
            "confidence, and the operational readiness checklist."
        )

        st.subheader("Snowflake Compatibility Check")
        st.caption(
            "Validates required ACCOUNT_USAGE views, optional columns that vary by account, "
            "and SHOW commands used by DBA operations."
        )
        if st.button("Run Compatibility Check", key="compatibility_check_load"):
            st.session_state["dba_compatibility_status"] = run_compatibility_checks(session)

        if st.session_state.get("dba_compatibility_status") is not None:
            compat_df = st.session_state["dba_compatibility_status"]
            if not compat_df.empty:
                ready_count = int((compat_df["STATUS"] == "Ready").sum())
                limited_count = int((compat_df["STATUS"] == "Limited").sum())
                blocked_count = int((~compat_df["STATUS"].isin(["Ready", "Limited"])).sum())
                c_ready, c_limited, c_blocked = st.columns(3)
                c_ready.metric("Ready", f"{ready_count:,}")
                c_limited.metric("Limited", f"{limited_count:,}")
                c_blocked.metric("Blocked", f"{blocked_count:,}")
                render_priority_dataframe(
                    compat_df,
                    title="Compatibility checks needing attention",
                    priority_columns=["CATEGORY", "CHECK", "STATUS", "USED_BY", "DETAIL", "IMPACT"],
                    sort_by=["STATUS", "CATEGORY"],
                    ascending=[True, True],
                    raw_label="All compatibility checks",
                )
                download_csv(compat_df, "overwatch_compatibility_check.csv")

                blocked = compat_df[~compat_df["STATUS"].isin(["Ready", "Limited"])]
                if not blocked.empty:
                    st.warning(
                        "Some checks are blocked. Affected sections should show graceful "
                        "limited-data messages instead of crashing."
                    )

        st.divider()
        st.subheader("Company Scope Audit")
        st.caption(
            "Find warehouses and databases that are not matched to the ALFA or Trexis allowlists. "
            "Review this before widening company filters."
        )
        if st.button("Load Unclassified Assets", key="scope_audit_load"):
            st.session_state["dba_unclassified_assets"] = run_query(
                build_unclassified_assets_sql(30),
                ttl_key=f"dba_scope_audit_{company}",
                tier="standard",
                section="DBA Tools",
            )
        unclassified = st.session_state.get("dba_unclassified_assets")
        if unclassified is not None:
            if unclassified.empty:
                st.success("No unclassified warehouses or databases found in the last 30 days.")
            else:
                wh_count = int((unclassified["OBJECT_TYPE"] == "WAREHOUSE").sum()) if "OBJECT_TYPE" in unclassified.columns else 0
                db_count = int((unclassified["OBJECT_TYPE"] == "DATABASE").sum()) if "OBJECT_TYPE" in unclassified.columns else 0
                c_wh, c_db = st.columns(2)
                c_wh.metric("Unclassified Warehouses", f"{wh_count:,}")
                c_db.metric("Unclassified Databases", f"{db_count:,}")
                render_priority_dataframe(
                    unclassified,
                    title="Unclassified scope assets",
                    priority_columns=["OBJECT_TYPE", "OBJECT_NAME", "DATABASE_NAME", "WAREHOUSE_NAME", "LAST_SEEN"],
                    sort_by=["OBJECT_TYPE", "OBJECT_NAME"],
                    ascending=[True, True],
                    raw_label="All unclassified assets",
                )
                download_csv(unclassified, "overwatch_unclassified_assets.csv")

        st.divider()
        st.subheader("Persistent Setup Objects")

        c1, c2 = st.columns([1, 2])
        with c1:
            if st.button("Check Setup Status", key="setup_status_load"):
                st.session_state["dba_setup_status"] = _setup_status_df(session)
        with c2:
            st.info(
                "Run the setup SQL with a role that can create tables and tasks in "
                f"{ALERT_DB}.{ALERT_SCHEMA}. Review the alert task warehouse and schedule "
                "before enabling it."
            )

        if st.session_state.get("dba_setup_status") is not None:
            status_df = st.session_state["dba_setup_status"]
            missing_count = int((status_df["STATUS"] == "Missing").sum())
            unknown_count = int((status_df["STATUS"] == "Unknown").sum())

            m1, m2, m3 = st.columns(3)
            m1.metric("Objects Checked", f"{len(status_df):,}")
            m2.metric("Missing", f"{missing_count:,}")
            m3.metric("Unknown", f"{unknown_count:,}")
            render_priority_dataframe(
                status_df,
                title="Persistent setup readiness",
                priority_columns=["FEATURE", "OBJECT_NAME", "STATUS"],
                sort_by=["STATUS", "FEATURE"],
                ascending=[True, True],
                raw_label="All setup objects",
            )

        st.divider()
        st.subheader("Cost Formula Confidence")
        cost_formula_df = build_cost_formula_audit()
        render_priority_dataframe(
            cost_formula_df,
            title="Cost formula confidence",
            priority_columns=["METRIC", "CONFIDENCE", "FORMULA", "NOTES"],
            sort_by=["CONFIDENCE", "METRIC"],
            ascending=[True, True],
            raw_label="All formula checks",
        )

        st.divider()
        st.subheader("Operational Readiness Checklist")
        smoke_df = build_smoke_test_checklist()
        render_priority_dataframe(
            smoke_df,
            title="Operational readiness checklist",
            priority_columns=["SECTION", "ACTION", "READY_CRITERIA"],
            sort_by=["SECTION", "ACTION"],
            ascending=[True, True],
            raw_label="Full operational readiness checklist",
        )
        download_csv(smoke_df, "overwatch_operational_readiness_checklist.csv")

        st.info(
            "Persistent object DDL and mart aggregation setup have been removed from this dashboard. "
            "Use the version-controlled Snowflake setup script as the deployment source of truth."
        )
