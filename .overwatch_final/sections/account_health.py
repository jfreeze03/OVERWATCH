"""Account Health: daily checklist, source readiness, and DBA morning brief."""
from __future__ import annotations

import streamlit as st
from datetime import datetime
from config import ALERT_DB, ALERT_SCHEMA, ACTION_QUEUE_TABLE, DEFAULTS, normalize_section_name
from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.navigation import apply_navigation_state
from sections.shell_helpers import render_shell_kpi_row, render_shell_snapshot, render_shell_status_strip
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_section_note


pd = lazy_pandas()

get_session_for_action = _lazy_util("get_session_for_action")
run_query = _lazy_util("run_query")
run_query_or_raise = _lazy_util("run_query_or_raise")
format_credits = _lazy_util("format_credits")
credits_to_dollars = _lazy_util("credits_to_dollars")
download_csv = _lazy_util("download_csv")
mark_loaded = _lazy_util("mark_loaded")
show_loaded_time = _lazy_util("show_loaded_time")
build_metered_credit_cte = _lazy_util("build_metered_credit_cte")
build_monitoring_cost_sql = _lazy_util("build_monitoring_cost_sql")
metric_confidence_label = _lazy_util("metric_confidence_label")
freshness_note = _lazy_util("freshness_note")
render_drillable_bar_chart = _lazy_util("render_drillable_bar_chart")
build_task_failure_summary_sql = _lazy_util("build_task_failure_summary_sql")
build_task_health_sql = _lazy_util("build_task_health_sql")
executive_health_score = _lazy_util("executive_health_score")
get_wh_filter_clause = _lazy_util("get_wh_filter_clause")
get_db_filter_clause = _lazy_util("get_db_filter_clause")
get_user_filter_clause = _lazy_util("get_user_filter_clause")
get_global_filter_clause = _lazy_util("get_global_filter_clause")
get_active_environment = _lazy_util("get_active_environment")
load_latest_control_room_mart = _lazy_util("load_latest_control_room_mart")
mart_source_caption = _lazy_util("mart_source_caption")
build_mart_account_health_storage_sql = _lazy_util("build_mart_account_health_storage_sql")
build_mart_account_health_cost_drivers_sql = _lazy_util("build_mart_account_health_cost_drivers_sql")


def _canonical_account_route(route: object) -> str:
    text = str(route or "DBA Control Room").strip()
    return normalize_section_name(text) or "DBA Control Room"
build_mart_account_health_change_sql = _lazy_util("build_mart_account_health_change_sql")
build_mart_control_room_task_failures_sql = _lazy_util("build_mart_control_room_task_failures_sql")
build_mart_control_room_warehouse_pressure_sql = _lazy_util("build_mart_control_room_warehouse_pressure_sql")
format_snowflake_error = _lazy_util("format_snowflake_error")
filter_existing_columns = _lazy_util("filter_existing_columns")
make_action_id = _lazy_util("make_action_id")
safe_identifier = _lazy_util("safe_identifier")
sql_literal = _lazy_util("sql_literal")
upsert_actions = _lazy_util("upsert_actions")
action_queue_environment_clause = _lazy_util("action_queue_environment_clause")
resolve_owner_context = _lazy_util("resolve_owner_context")
mart_object_name = _lazy_util("mart_object_name")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
render_load_status = _lazy_util("render_load_status")
render_mode_selector = _lazy_util("render_mode_selector")
day_window_selectbox = _lazy_util("day_window_selectbox")


def get_credit_price() -> float:
    return safe_float(st.session_state.get("credit_price", DEFAULTS.get("credit_price", 3.68)), 3.68)


def render_operator_briefing(items: list[tuple[str, str]], *, columns: int = 4) -> None:
    for label, detail in items:
        defer_section_note(f"{label}: {detail}")

CHECKLIST_HISTORY_TABLE = "OVERWATCH_DBA_CHECKLIST_HISTORY"
ACCOUNT_HEALTH_OPERABILITY_FACT_TABLE = "FACT_ACCOUNT_HEALTH_OPERABILITY_DAILY"
ACCOUNT_HEALTH_ACTION_SOURCE = "Account Health - Daily DBA Checklist"
ACCOUNT_HEALTH_ACCESS_HYGIENE_SOURCE = "Account Health - Account Access Hygiene"
ACCOUNT_HEALTH_PANES = (
    "Overview",
    "Morning Report",
)
ACCOUNT_HEALTH_PANE_LABELS = {
    "Overview": "Health Workspace",
    "Morning Report": "DBA Morning Brief",
}
ACCOUNT_HEALTH_PANE_DETAILS = {
    "Overview": "Daily account cockpit: checklist state, source readiness, exception signals, and escalation routes.",
    "Morning Report": "Copy-ready DBA morning packet built from Control Room blockers, handoff rows, and route status.",
}
ACCOUNT_HEALTH_SCOPE_FILTER_KEYS = (
    "global_start_date",
    "global_end_date",
    "global_warehouse",
    "global_user",
    "global_role",
    "global_database",
)


def _account_health_action_session(action: str):
    return get_session_for_action(
        action,
        surface="Account Health",
        offline_note="Account Health shell, source summaries, and cached telemetry remain visible without a live connection.",
    )


def _account_health_scope_value(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value).strip()


def _account_health_scope_meta(
    company: str,
    environment: str,
    window: str = "",
    state: dict | None = None,
    ignore_environment: bool = False,
    filter_keys: tuple[str, ...] | None = None,
) -> dict:
    """Return the filter scope that loaded Account Health telemetry must match."""
    state = state if state is not None else st.session_state
    meta = {
        "company": _account_health_scope_value(company),
        "environment": "No Database Context" if ignore_environment else _account_health_scope_value(environment),
    }
    if window:
        meta["window"] = _account_health_scope_value(window)
    for key in (ACCOUNT_HEALTH_SCOPE_FILTER_KEYS if filter_keys is None else filter_keys):
        meta[key] = _account_health_scope_value(state.get(key))
    return meta


def _account_health_meta_matches(meta: dict | None, expected: dict | None) -> bool:
    if not isinstance(meta, dict) or not isinstance(expected, dict):
        return False
    for key, expected_value in expected.items():
        if _account_health_scope_value(meta.get(key)) != _account_health_scope_value(expected_value):
            return False
    return True


def _account_health_row_count(value) -> int:
    if isinstance(value, pd.DataFrame):
        return len(value)
    if isinstance(value, dict):
        return sum(len(frame) for frame in value.values() if isinstance(frame, pd.DataFrame))
    if isinstance(value, str):
        return 1 if value.strip() else 0
    return 0


def _account_health_loaded(value) -> bool:
    return isinstance(value, (pd.DataFrame, dict, str))


def _account_health_is_empty(value) -> bool:
    if isinstance(value, pd.DataFrame):
        return value.empty
    if isinstance(value, dict):
        frames = [frame for frame in value.values() if isinstance(frame, pd.DataFrame)]
        return not frames or all(frame.empty for frame in frames)
    if isinstance(value, str):
        return not value.strip()
    return True


def _account_health_source_confidence(source: str, default: str) -> str:
    source_lower = str(source or "").lower()
    if ("fast" in source_lower and "summary" in source_lower) or "mart" in source_lower or "fact_" in source_lower:
        return "Fast summary"
    if "fallback" in source_lower:
        return "Live fallback"
    if "account_usage" in source_lower or "information_schema" in source_lower:
        return "Live Snowflake metadata"
    return default


def _account_health_source_next_action(state: str, source: str) -> str:
    source_lower = str(source or "").lower()
    if state == "Stale":
        return "Reload after changing company, environment, lookback, or triage filters."
    if state == "Unavailable":
        return "Deploy or refresh the summary/grants before relying on this surface."
    if state == "On demand":
        return "Refresh only when this workflow is part of the current DBA investigation."
    if state == "No Rows":
        return "Confirm the selected scope has recent account activity or persisted telemetry."
    if "fallback" in source_lower:
        return "Use for investigation; prefer summary refresh for repeated morning control."
    return "Current for the active Account Health scope."


def _account_health_has_source_state(state: dict) -> bool:
    """Return True once Account Health has telemetry or source errors to summarize."""
    health_data = state.get("health_data")
    if isinstance(health_data, dict) and bool(health_data):
        return True
    for key in (
        "account_health_operability_fact",
        "account_health_operability_fact_error",
        "account_health_access_hygiene",
        "account_health_access_hygiene_error",
        "account_health_checklist_trend",
        "account_health_checklist_trend_error",
        "account_health_closure_analytics",
        "account_health_closure_analytics_error",
        "morning_data",
        "morning_data_error",
    ):
        value = state.get(key)
        if isinstance(value, str):
            if value.strip():
                return True
            continue
        if value is not None:
            return True
    return False


def _account_health_source_health_rows(
    state: dict,
    company: str,
    environment: str,
) -> pd.DataFrame:
    """Summarize Account Health telemetry freshness and source strategy."""
    health_data = state.get("health_data", {})
    if not isinstance(health_data, dict):
        health_data = {}
    definitions = [
        {
            "surface": "Overview snapshot",
            "value": health_data,
            "source": health_data.get("_account_health_detail_source", "Fast summary or live account history"),
            "meta_key": "account_health_overview_meta",
            "window": "24h",
            "confidence": "Mixed",
        },
        {
            "surface": "Control-room summary",
            "value": health_data.get("_control_mart"),
            "source": health_data.get("_control_mart_source", "Fast control-room summary"),
            "meta_key": "account_health_overview_meta",
            "window": "24h",
            "confidence": "Fast summary",
        },
        {
            "surface": "Live status probe",
            "value": health_data.get("live"),
            "source": health_data.get("_live_source", "ACCOUNT_USAGE"),
            "meta_key": "account_health_live_status_meta",
            "window": "1h",
            "confidence": "Live Snowflake metadata",
        },
        {
            "surface": "Control summary",
            "value": state.get("account_health_operability_fact"),
            "source": "Fast Account Health control summary",
            "meta_key": "account_health_operability_fact_meta",
            "window": "30d",
            "confidence": "Fast summary",
            "error_key": "account_health_operability_fact_error",
        },
        {
            "surface": "Access hygiene",
            "value": state.get("account_health_access_hygiene"),
            "source": "Live ACCOUNT_USAGE users, logins, and grants",
            "meta_key": "account_health_access_hygiene_meta",
            "window_key": "account_health_access_hygiene_days",
            "default_window": "30d",
            "confidence": "Account-level control",
            "ignore_environment": True,
            "filter_keys": ("global_user",),
        },
        {
            "surface": "Checklist trend",
            "value": state.get("account_health_checklist_trend"),
            "source": "Workflow telemetry",
            "meta_key": "account_health_checklist_trend_meta",
            "window_key": "account_health_checklist_trend_days",
            "default_window": "30d",
            "confidence": "Workflow telemetry",
        },
        {
            "surface": "Closure analytics",
            "value": state.get("account_health_closure_analytics"),
            "source": "Action queue closure status",
            "meta_key": "account_health_closure_analytics_meta",
            "window_key": "account_health_closure_days",
            "default_window": "30d",
            "confidence": "Workflow telemetry",
        },
        {
            "surface": "DBA Morning Brief",
            "value": state.get("morning_data"),
            "source": state.get("morning_data_source", "DBA Control Room telemetry"),
            "meta_key": "morning_data_meta",
            "window_key": "account_health_morning_lookback",
            "default_window": "24h",
            "window_unit": "h",
            "confidence": "Control Room telemetry",
        },
    ]
    rows = []
    for item in definitions:
        raw_window = item.get("window")
        if raw_window is None:
            window_key = item.get("window_key")
            raw_window = state.get(window_key, item.get("default_window", "")) if window_key else item.get("default_window", "")
            raw_window_text = _account_health_scope_value(raw_window)
            if window_key and raw_window_text.isdigit():
                raw_window = f"{int(raw_window_text)}{item.get('window_unit', 'd')}"
        window = _account_health_scope_value(raw_window)
        expected_meta = _account_health_scope_meta(company, environment, window=window, state=state)
        if item.get("ignore_environment"):
            expected_meta = _account_health_scope_meta(
                company,
                environment,
                window=window,
                state=state,
                ignore_environment=True,
                filter_keys=item.get("filter_keys"),
            )
        value = item.get("value")
        error_key = item.get("error_key")
        error = state.get(error_key) if error_key else None
        if error:
            status = "Unavailable"
        elif not _account_health_loaded(value):
            status = "On demand"
        elif not _account_health_meta_matches(state.get(item["meta_key"]), expected_meta):
            status = "Stale"
        elif _account_health_is_empty(value):
            status = "No Rows"
        else:
            status = "Loaded"
        scope_environment = "No Database Context" if item.get("ignore_environment") else environment
        rows.append({
            "SURFACE": item["surface"],
            "STATE": status,
            "STATE_RANK": {
                "Unavailable": 0,
                "Stale": 1,
                "Loaded": 2,
                "No Rows": 3,
                "On demand": 4,
            }.get(status, 9),
            "SOURCE": item["source"],
            "CONFIDENCE": _account_health_source_confidence(item["source"], item["confidence"]),
            "ROWS": _account_health_row_count(value),
            "SCOPE": f"{company} / {scope_environment} / {window}",
            "NEXT_ACTION": _account_health_source_next_action(status, item["source"]),
        })
    return pd.DataFrame(rows)


def _drill_to(
    section: str,
    wh_filter: str = "",
    user_filter: str = "",
    workflow_key: str = "",
    workflow: str = "",
):
    apply_navigation_state(section)
    if workflow_key and workflow:
        st.session_state[workflow_key] = workflow
    if wh_filter:
        st.session_state["lm_wh"]     = wh_filter
        st.session_state["wh_filter"] = wh_filter
    if user_filter:
        st.session_state["global_user"] = user_filter
    st.rerun()


def _task_failure_sql_or_empty(session, time_predicate: str, limit: int, company: str) -> str:
    """Return TASK_HISTORY failure SQL, or an empty compatible result if unavailable."""
    try:
        return build_task_failure_summary_sql(session, time_predicate, limit=limit, company=company)
    except Exception:
        return """
            SELECT NULL::VARCHAR AS TASK_NAME,
                   NULL::VARCHAR AS DATABASE_NAME,
                   NULL::VARCHAR AS SCHEMA_NAME,
                   0::NUMBER AS FAILURES,
                   NULL::TIMESTAMP_NTZ AS LAST_FAILURE,
                   NULL::VARCHAR AS LAST_ERROR
            WHERE 1=0
        """


def _task_health_sql_or_empty(session, time_predicate: str, company: str) -> str:
    """Return TASK_HISTORY aggregate SQL, or a single zero row if unavailable."""
    try:
        return build_task_health_sql(session, time_predicate, company=company)
    except Exception:
        return """
            SELECT 0::NUMBER AS TASK_RUNS,
                   0::NUMBER AS FAILED_TASKS,
                   0::NUMBER AS SUCCEEDED_TASKS,
                   0::NUMBER AS DISTINCT_TASKS
        """


def _default_query_history_capabilities() -> dict[str, str]:
    return {
        "cost_wh_size_expr": "NULL::VARCHAR",
        "cost_bytes_scanned_expr": "0",
        "failed_pred_q": "UPPER(q.execution_status) = 'FAILED_WITH_ERROR'",
        "failed_pred_plain": "UPPER(execution_status) = 'FAILED_WITH_ERROR'",
        "queued_count_expr_q": "SUM(CASE WHEN q.execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END)",
        "queued_count_expr_plain": "SUM(CASE WHEN execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END)",
        "pressure_wh_size_expr": "NULL::VARCHAR",
    }


def _account_query_history_capabilities(session) -> dict[str, str]:
    if session is None:
        return _default_query_history_capabilities()
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "WAREHOUSE_SIZE",
            "BYTES_SCANNED",
            "ERROR_CODE",
            "QUEUED_OVERLOAD_TIME",
            "QUEUED_PROVISIONING_TIME",
            "QUEUED_REPAIR_TIME",
        ],
    ))
    queue_cols = [
        col.lower()
        for col in ["QUEUED_OVERLOAD_TIME", "QUEUED_PROVISIONING_TIME", "QUEUED_REPAIR_TIME"]
        if col in qh_cols
    ]
    queue_time_q = " + ".join([f"COALESCE(q.{col}, 0)" for col in queue_cols])
    queue_time_plain = " + ".join([f"COALESCE({col}, 0)" for col in queue_cols])
    return {
        "cost_wh_size_expr": "MAX(q.warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR",
        "cost_bytes_scanned_expr": "SUM(q.bytes_scanned)" if "BYTES_SCANNED" in qh_cols else "0",
        "failed_pred_q": (
            "q.error_code IS NOT NULL"
            if "ERROR_CODE" in qh_cols
            else "UPPER(q.execution_status) = 'FAILED_WITH_ERROR'"
        ),
        "failed_pred_plain": (
            "error_code IS NOT NULL"
            if "ERROR_CODE" in qh_cols
            else "UPPER(execution_status) = 'FAILED_WITH_ERROR'"
        ),
        "queued_count_expr_q": (
            f"SUM(CASE WHEN {queue_time_q} > 0 OR q.execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END)"
            if queue_cols
            else "SUM(CASE WHEN q.execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END)"
        ),
        "queued_count_expr_plain": (
            f"SUM(CASE WHEN {queue_time_plain} > 0 OR execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END)"
            if queue_cols
            else "SUM(CASE WHEN execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END)"
        ),
        "pressure_wh_size_expr": "MAX(warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR",
    }


def _live_query_status_sql(wh_filter: str, db_filter: str, user_filter: str) -> str:
    return f"""
        SELECT COUNT(*) AS active_count,
               SUM(IFF(
                   COALESCE(queued_overload_time, 0)
                   + COALESCE(queued_provisioning_time, 0)
                   + COALESCE(queued_repair_time, 0) > 0
                   OR execution_status ILIKE '%QUEUED%',
                   1,
                   0
               )) AS queued_count,
               SUM(IFF(execution_status ILIKE '%BLOCKED%', 1, 0)) AS blocked_count
        FROM TABLE(
            INFORMATION_SCHEMA.QUERY_HISTORY(
                END_TIME_RANGE_START=>DATEADD('hours', -1, CURRENT_TIMESTAMP()),
                RESULT_LIMIT=>10000
            )
        ) q
        WHERE execution_status IN ('RUNNING', 'QUEUED', 'BLOCKED', 'RESUMING_WAREHOUSE')
          {wh_filter} {db_filter} {user_filter}
    """


def _load_live_query_status(wh_filter: str, db_filter: str, user_filter: str) -> tuple[pd.DataFrame, str]:
    # Prefer INFORMATION_SCHEMA for the morning triage counters. ACCOUNT_USAGE
    # remains a fallback only because Snowflake-hosted Streamlit can reject some
    # table-function calls depending on role/session permissions.
    fallback_sql = f"""
        SELECT COUNT(*) AS active_count,
               SUM(CASE WHEN execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END) AS queued_count,
               SUM(CASE WHEN execution_status ILIKE '%BLOCKED%' THEN 1 ELSE 0 END) AS blocked_count
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('hours', -1, CURRENT_TIMESTAMP())
          AND UPPER(q.execution_status) IN ('RUNNING', 'QUEUED', 'BLOCKED', 'RESUMING_WAREHOUSE')
          {wh_filter} {db_filter} {user_filter}
    """
    try:
        return run_query_or_raise(_live_query_status_sql(wh_filter, db_filter, user_filter)), "INFORMATION_SCHEMA"
    except Exception:
        try:
            return run_query_or_raise(fallback_sql), "ACCOUNT_USAGE"
        except Exception:
            return pd.DataFrame(), "ACCOUNT_USAGE"


def _can_use_control_room_mart(company: str) -> tuple[bool, str]:
    """Use the mart only when section filters match its company-level grain."""
    if str(company or "").upper() == "ALL":
        return False, "ALL view needs live/account-level aggregation."
    blocking_filters = {
        "warehouse": st.session_state.get("global_warehouse"),
        "user": st.session_state.get("global_user"),
        "role": st.session_state.get("global_role"),
        "database": st.session_state.get("global_database"),
    }
    active = [name for name, value in blocking_filters.items() if str(value or "").strip()]
    if active:
        return False, f"Global {', '.join(active)} filters are active."
    return True, ""


def _mart_health_label(score: float) -> str:
    if score >= 90:
        return "Healthy"
    if score >= 75:
        return "Watch"
    if score >= 60:
        return "Degraded"
    return "Critical"


def _check_status(ok: bool, watch: bool = False) -> str:
    if ok:
        return "OK"
    if watch:
        return "Watch"
    return "Needs DBA"


def account_health_checklist_history_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHECKLIST_HISTORY_TABLE,
) -> str:
    return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}"


def account_health_action_queue_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = ACTION_QUEUE_TABLE,
) -> str:
    return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}"


def account_health_operability_fact_fqn(table: str = ACCOUNT_HEALTH_OPERABILITY_FACT_TABLE) -> str:
    return mart_object_name(table)


def build_account_health_checklist_history_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHECKLIST_HISTORY_TABLE,
) -> str:
    fqn = account_health_checklist_history_fqn(db=db, schema=schema, table=table)
    return f"""CREATE TABLE IF NOT EXISTS {fqn} (
    SNAPSHOT_ID       VARCHAR(64),
    SNAPSHOT_TS       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    COMPANY           VARCHAR(100),
    ENVIRONMENT       VARCHAR(100),
    CHECK_NAME        VARCHAR(200),
    STATUS            VARCHAR(80),
    SEVERITY          VARCHAR(40),
    EVIDENCE          VARCHAR(2000),
    OWNER             VARCHAR(200),
    ESCALATION_TARGET VARCHAR(200),
    OWNER_SOURCE      VARCHAR(200),
    ROUTE             VARCHAR(120),
    NEXT_ACTION       VARCHAR(4000),
    PROOF_REQUIRED    VARCHAR(2000),
    ENVIRONMENT_SCOPE VARCHAR(100),
    DATABASE_CONTEXT  VARCHAR(80),
    SCOPE_CONFIDENCE  VARCHAR(160),
    SCOPE_EVIDENCE    VARCHAR(2000),
    APPROVAL_REQUIRED VARCHAR(20),
    QUEUE_READINESS   VARCHAR(80),
    QUEUE_BLOCKERS    VARCHAR(2000),
    VERIFICATION_QUERY VARCHAR(8000),
    RECOVERY_SLA_TARGET_HOURS FLOAT,
    CONTROL_READINESS VARCHAR(100),
    CONTROL_BLOCKERS  VARCHAR(2000),
    NEXT_CONTROL_ACTION VARCHAR(4000),
    HEALTH_SCORE      FLOAT,
    DETAIL_SOURCE     VARCHAR(500),
    ACTIONABLE        BOOLEAN
);"""


def build_account_health_operability_fact_ddl(table: str = ACCOUNT_HEALTH_OPERABILITY_FACT_TABLE) -> str:
    fqn = account_health_operability_fact_fqn(table=table)
    return f"""CREATE TRANSIENT TABLE IF NOT EXISTS {fqn} (
    SNAPSHOT_DATE                   DATE,
    COMPANY                         VARCHAR(100),
    ENVIRONMENT                     VARCHAR(100),
    CONTROL_SOURCE                  VARCHAR(80),
    CHECK_NAME                      VARCHAR(200),
    ROUTE                           VARCHAR(120),
    SEVERITY                        VARCHAR(40),
    CONTROL_STATE                   VARCHAR(120),
    CONTROL_RANK                    NUMBER,
    HEALTH_SCORE                    FLOAT,
    ISSUE_ROWS                      NUMBER,
    ROUTE_BLOCKER_ROWS              NUMBER,
    QUEUE_REQUIRED_ROWS             NUMBER,
    ACCESS_HYGIENE_ROWS             NUMBER,
    FAILED_LOGIN_ROWS               NUMBER,
    PRIVILEGED_GRANT_ROWS           NUMBER,
    OPEN_ACTIONS                    NUMBER,
    OVERDUE_OPEN                    NUMBER,
    FIXED_WITHOUT_VERIFICATION      NUMBER,
    VERIFIED_CLOSURES               NUMBER,
    OWNER_APPROVAL_GAP_ROWS         NUMBER,
    RECOVERY_RISK_ROWS              NUMBER,
    NEXT_CONTROL_ACTION             VARCHAR(4000),
    LAST_ACTIVITY_TS                TIMESTAMP_NTZ,
    LOAD_TS                         TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);"""


def build_account_health_operability_fact_migration_sql(
    table: str = ACCOUNT_HEALTH_OPERABILITY_FACT_TABLE,
) -> list[str]:
    fqn = account_health_operability_fact_fqn(table=table)
    return [
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_SOURCE VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_STATE VARCHAR(120)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_RANK NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS HEALTH_SCORE FLOAT",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS ISSUE_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS ROUTE_BLOCKER_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS QUEUE_REQUIRED_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS ACCESS_HYGIENE_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS FAILED_LOGIN_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS PRIVILEGED_GRANT_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS OWNER_APPROVAL_GAP_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS RECOVERY_RISK_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS NEXT_CONTROL_ACTION VARCHAR(4000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS LAST_ACTIVITY_TS TIMESTAMP_NTZ",
    ]


def build_account_health_checklist_history_migration_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHECKLIST_HISTORY_TABLE,
) -> list[str]:
    """Return additive migrations for existing Daily DBA Checklist history tables."""
    fqn = account_health_checklist_history_fqn(db=db, schema=schema, table=table)
    return [
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS ENVIRONMENT_SCOPE VARCHAR(100)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS DATABASE_CONTEXT VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS SCOPE_CONFIDENCE VARCHAR(160)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS SCOPE_EVIDENCE VARCHAR(2000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS APPROVAL_REQUIRED VARCHAR(20)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS QUEUE_READINESS VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS QUEUE_BLOCKERS VARCHAR(2000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS VERIFICATION_QUERY VARCHAR(8000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS RECOVERY_SLA_TARGET_HOURS FLOAT",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_READINESS VARCHAR(100)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_BLOCKERS VARCHAR(2000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS NEXT_CONTROL_ACTION VARCHAR(4000)",
    ]


def _account_health_owner_entity_type(check: object, route: object = "") -> str:
    text = f"{check or ''} {route or ''}".lower()
    if "cost" in text:
        return "COST_CONTROL"
    if "task" in text or "procedure" in text:
        return "TASK"
    if "warehouse" in text or "queue" in text:
        return "WAREHOUSE"
    if "change" in text or "drift" in text:
        return "CHANGE_CONTROL"
    if "security" in text or "grant" in text:
        return "SECURITY"
    return "ACCOUNT_HEALTH"


def _account_health_owner_context(check: object, route: object = "") -> dict:
    name = str(check or "").lower()
    route_text = str(route or "")
    if "query failure" in name:
        base = {
            "owner": "DBA Query Triage",
            "escalation": "Application Route / DBA On-Call",
            "source": "Checklist route map",
        }
    elif "queue pressure" in name:
        base = {
            "owner": "Platform DBA",
            "escalation": "Warehouse Route / DBA On-Call",
            "source": "Checklist route map",
        }
    elif "cost spike" in name:
        base = {
            "owner": "DBA / Cost owner Route",
            "escalation": "Cost owner",
            "source": "Checklist route map",
        }
    elif "task" in name or "procedure" in name:
        base = {
            "owner": "Data Engineering On-Call",
            "escalation": "Pipeline Route / DBA On-Call",
            "source": "Checklist route map",
        }
    elif "change" in name or "drift" in name:
        base = {
            "owner": "DBA Change Route",
            "escalation": "Security Route / Data Stewardship",
            "source": "Checklist route map",
        }
    elif "storage" in name or "monitor" in name:
        base = {
            "owner": "Platform DBA",
            "escalation": "DBA Lead",
            "source": "Checklist route map",
        }
    elif "source readiness" in name or "source confidence" in name:
        base = {
            "owner": "OVERWATCH Platform Route",
            "escalation": "DBA Lead",
            "source": "Checklist route map",
        }
    else:
        base = {
            "owner": "DBA Lead" if route_text == "DBA Control Room" else "DBA",
            "escalation": "DBA Lead",
            "source": "Default DBA team",
        }

    directory_context = resolve_owner_context(
        {
            "ENTITY_NAME": check,
            "CATEGORY": route_text or "Daily DBA Checklist",
            "OWNER": base["owner"],
        },
        entity=check,
        entity_type=_account_health_owner_entity_type(check, route),
        owner=base["owner"],
        category=route_text or "Daily DBA Checklist",
    )
    return {
        "owner": directory_context.get("OWNER") or base["owner"],
        "escalation": base["escalation"] or directory_context.get("ESCALATION_TARGET", ""),
        "source": f"{base['source']}; {directory_context.get('OWNER_SOURCE', '')}".strip("; "),
        "owner_email": directory_context.get("OWNER_EMAIL", ""),
        "oncall_primary": directory_context.get("ONCALL_PRIMARY", ""),
        "oncall_secondary": directory_context.get("ONCALL_SECONDARY", ""),
        "approval_group": base["escalation"] or directory_context.get("APPROVAL_GROUP", ""),
        "owner_evidence": directory_context.get("OWNER_EVIDENCE", ""),
    }


def _enrich_account_health_checklist_owners(checklist: pd.DataFrame) -> pd.DataFrame:
    if checklist is None or checklist.empty:
        return checklist
    view = checklist.copy()
    contexts = view.apply(lambda row: _account_health_owner_context(row.get("CHECK"), row.get("ROUTE")), axis=1)
    view["OWNER"] = contexts.apply(lambda item: item["owner"])
    view["ESCALATION_TARGET"] = contexts.apply(lambda item: item["escalation"])
    view["OWNER_SOURCE"] = contexts.apply(lambda item: item["source"])
    view["OWNER_EMAIL"] = contexts.apply(lambda item: item.get("owner_email", ""))
    view["ONCALL_PRIMARY"] = contexts.apply(lambda item: item.get("oncall_primary", ""))
    view["ONCALL_SECONDARY"] = contexts.apply(lambda item: item.get("oncall_secondary", ""))
    view["APPROVAL_GROUP"] = contexts.apply(lambda item: item.get("approval_group", ""))
    view["OWNER_EVIDENCE"] = contexts.apply(lambda item: item.get("owner_evidence", ""))
    return view


def _build_account_health_dba_checklist(
    *,
    health_score: float,
    score_label: str,
    err_count: int,
    queued: int,
    pct_delta: float,
    last24: float,
    stor_tb: float,
    failed_tasks: int = 0,
    object_changes: int = 0,
    control_mart_used: bool = False,
    detail_source: str = "",
) -> pd.DataFrame:
    """Convert the broad account snapshot into a daily DBA operating checklist."""
    score = safe_float(health_score)
    failures = safe_int(err_count)
    queued_count = safe_int(queued)
    failed_task_count = safe_int(failed_tasks)
    change_count = safe_int(object_changes)
    delta = safe_float(pct_delta)
    rows = [
        {
            "CHECK": "Refresh source readiness",
            "STATUS": "OK" if control_mart_used else "Verify source",
            "SEVERITY": "Low" if control_mart_used else "Medium",
            "EVIDENCE": detail_source or ("Fast summary" if control_mart_used else "Current account telemetry"),
            "OWNER": "DBA",
            "ROUTE": "DBA Control Room",
            "NEXT_ACTION": "Use the latest telemetry snapshot for morning control; document source state before acting.",
            "PROOF_REQUIRED": "Snapshot timestamp or source-state note",
        },
        {
            "CHECK": "Query failure review",
            "STATUS": _check_status(failures == 0, failures <= 10),
            "SEVERITY": "High" if failures > 10 else ("Medium" if failures > 0 else "Info"),
            "EVIDENCE": f"{failures:,} failed queries in last 24h",
            "OWNER": "DBA / App Owner",
            "ROUTE": "Workload Operations",
            "NEXT_ACTION": "Open Query diagnosis, group repeat error signatures, and queue recurring failures.",
            "PROOF_REQUIRED": "query_id, error code/message, affected user/warehouse",
        },
        {
            "CHECK": "Queue pressure review",
            "STATUS": _check_status(queued_count == 0, queued_count <= 5),
            "SEVERITY": "High" if queued_count > 20 else ("Medium" if queued_count > 0 else "Info"),
            "EVIDENCE": f"{queued_count:,} queued/running pressure signals",
            "OWNER": "DBA / Platform",
            "ROUTE": "Cost & Contract",
            "NEXT_ACTION": "Confirm whether pressure is sizing, concurrency, lock, or workload-shape driven before changing warehouses.",
            "PROOF_REQUIRED": "warehouse, queued time, query count, before/after setting",
        },
        {
            "CHECK": "Cost spike review",
            "STATUS": _check_status(delta <= 20, delta <= 40),
            "SEVERITY": "High" if delta > 60 else ("Medium" if delta > 20 else "Info"),
            "EVIDENCE": f"{last24:,.2f} credits in last 24h; {delta:+.1f}% vs prior window",
            "OWNER": "DBA / Cost owner",
            "ROUTE": "Cost & Contract",
            "NEXT_ACTION": "Explain top drivers, classify allocated/estimated cost, and monitor any savings action later.",
            "PROOF_REQUIRED": "driver row, credit/cost formula, review for warehouse changes",
        },
        {
            "CHECK": "Task and procedure reliability",
            "STATUS": _check_status(failed_task_count == 0),
            "SEVERITY": "High" if failed_task_count > 0 else "Info",
            "EVIDENCE": f"{failed_task_count:,} failed task groups in last 24h",
            "OWNER": "DBA / Data Engineering",
            "ROUTE": "Workload Operations",
            "NEXT_ACTION": "Open task graphs and confirm recovery SLA, downstream impact, and retry review.",
            "PROOF_REQUIRED": "task history, root cause, telemetry status, recovery state",
        },
        {
            "CHECK": "Change and drift review",
            "STATUS": _check_status(change_count == 0, change_count <= 10),
            "SEVERITY": "Medium" if change_count > 0 else "Info",
            "EVIDENCE": f"{change_count:,} object/access change signals in last 24h",
            "OWNER": "DBA / Security Owner",
            "ROUTE": "Security Monitoring",
            "NEXT_ACTION": "Validate query IDs against change tickets, approvers, and release-note/rollback state.",
            "PROOF_REQUIRED": "query_id, approver, change ticket, dependency note",
        },
        {
            "CHECK": "Storage and monitor posture",
            "STATUS": _check_status(stor_tb > 0, stor_tb == 0),
            "SEVERITY": "Low" if stor_tb > 0 else "Medium",
            "EVIDENCE": f"{safe_float(stor_tb):.1f} TB latest storage reading",
            "OWNER": "DBA / Platform",
            "ROUTE": "Cost & Contract",
            "NEXT_ACTION": "Review cost controls for quota, notification, suspend, and suspend-immediate coverage.",
            "PROOF_REQUIRED": "resource monitor thresholds and warehouse scope",
        },
    ]
    if score < 75:
        rows.insert(0, {
            "CHECK": "Overall health escalation",
            "STATUS": "Needs DBA",
            "SEVERITY": "High" if score < 60 else "Medium",
            "EVIDENCE": f"Health state {score_label}; account pressure crossed DBA threshold",
            "OWNER": "DBA Lead",
            "ROUTE": "DBA Control Room",
            "NEXT_ACTION": "Run DBA Control Room triage and convert active signals into owned action queue items.",
            "PROOF_REQUIRED": "control-room exception row and action queue ID",
        })
    rank = {"High": 0, "Medium": 1, "Low": 2, "Info": 3}
    checklist = pd.DataFrame(rows)
    checklist = _enrich_account_health_checklist_owners(checklist)
    checklist["_RANK"] = checklist["SEVERITY"].map(rank).fillna(4)
    return checklist.sort_values(["_RANK", "CHECK"]).drop(columns=["_RANK"])


def _account_health_verification_sql(check: object, evidence: object = "") -> str:
    """Build a read-only source query for a daily DBA checklist action."""
    name = str(check or "").lower()
    if "refresh source readiness" in name or "refresh source confidence" in name:
        usage_fqn = f"{safe_identifier(ALERT_DB)}.{safe_identifier(ALERT_SCHEMA)}.OVERWATCH_USAGE_LOG"
        return f"""
SELECT
    LOG_TIME,
    COMPANY_VIEW,
    SECTION,
    EVENT_TYPE,
    QUERY_DURATION_MS,
    QUERY_HASH
FROM {usage_fqn}
WHERE SECTION = 'Account Health'
ORDER BY LOG_TIME DESC
LIMIT 50""".strip()
    if "query failure" in name:
        return """
SELECT
    query_id,
    start_time,
    user_name,
    role_name,
    warehouse_name,
    database_name,
    query_type,
    execution_status,
    error_code,
    error_message
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
  AND (error_code IS NOT NULL OR UPPER(execution_status) = 'FAILED_WITH_ERROR')
ORDER BY start_time DESC
LIMIT 50""".strip()
    if "queue pressure" in name:
        return """
SELECT
    query_id,
    start_time,
    user_name,
    warehouse_name,
    execution_status,
    COALESCE(queued_overload_time, 0)
      + COALESCE(queued_provisioning_time, 0)
      + COALESCE(queued_repair_time, 0) AS queued_ms,
    total_elapsed_time
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
  AND (
      COALESCE(queued_overload_time, 0)
      + COALESCE(queued_provisioning_time, 0)
      + COALESCE(queued_repair_time, 0) > 0
      OR execution_status ILIKE '%QUEUED%'
  )
ORDER BY queued_ms DESC
LIMIT 50""".strip()
    if "cost spike" in name:
        return """
SELECT
    warehouse_name,
    DATE_TRUNC('hour', start_time) AS usage_hour,
    SUM(credits_used) AS credits_used
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE start_time >= DATEADD('hours', -48, CURRENT_TIMESTAMP())
GROUP BY warehouse_name, DATE_TRUNC('hour', start_time)
ORDER BY credits_used DESC
LIMIT 50""".strip()
    if "task" in name or "procedure" in name:
        return """
SELECT
    database_name,
    schema_name,
    name AS task_name,
    state,
    scheduled_time,
    completed_time,
    query_id,
    error_message
FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
WHERE scheduled_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
  AND UPPER(state) = 'FAILED'
ORDER BY scheduled_time DESC
LIMIT 50""".strip()
    if "change" in name or "drift" in name:
        return """
SELECT
    query_id,
    start_time,
    user_name,
    role_name,
    database_name,
    schema_name,
    query_type,
    query_tag,
    query_text
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
  AND (
      query_text ILIKE 'CREATE%'
      OR query_text ILIKE 'ALTER%'
      OR query_text ILIKE 'DROP%'
      OR query_text ILIKE 'GRANT%'
      OR query_text ILIKE 'REVOKE%'
      OR query_text ILIKE '%OWNERSHIP%'
      OR query_text ILIKE '%MASKING POLICY%'
      OR query_text ILIKE '%ROW ACCESS POLICY%'
      OR query_text ILIKE '%TAG%'
  )
ORDER BY start_time DESC
LIMIT 50""".strip()
    if "storage" in name or "monitor" in name:
        return """
SELECT
    database_name,
    usage_date,
    ROUND((COALESCE(average_database_bytes, 0) + COALESCE(average_failsafe_bytes, 0)) / POWER(1024, 4), 4) AS storage_tb
FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
WHERE usage_date >= DATEADD('day', -7, CURRENT_DATE())
ORDER BY usage_date DESC, storage_tb DESC
LIMIT 50""".strip()
    return f"""
SELECT
    CURRENT_TIMESTAMP() AS verification_ts,
    {sql_literal(str(check or 'Account Health checklist'), 500)} AS check_name,
    {sql_literal(str(evidence or ''), 1000)} AS observed_evidence
LIMIT 50""".strip()


def _account_health_actionable_checklist(checklist: pd.DataFrame) -> pd.DataFrame:
    if checklist is None or checklist.empty:
        return pd.DataFrame()
    view = checklist.copy()
    status = view.get("STATUS", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.upper()
    severity = view.get("SEVERITY", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.upper()
    return view[(status != "OK") & (severity != "INFO")].copy()


def _account_health_visible_checklist(
    checklist: pd.DataFrame,
    *,
    show_full: bool = False,
) -> tuple[pd.DataFrame, str, str]:
    """Return the default Account Health checklist view for DBA triage."""
    full = pd.DataFrame() if checklist is None else checklist.copy()
    if show_full:
        return full, "Daily DBA checklist", "All daily DBA checklist rows"
    actionable = _account_health_actionable_checklist(full)
    return actionable, "Daily DBA checklist exceptions", "Full daily DBA checklist rows"


def _account_health_scope_context(check: object, route: object = "", environment: str = "") -> dict:
    """Classify whether a checklist row has database context or account-only scope."""
    name = str(check or "").lower()
    route_text = str(route or "").lower()
    env_value = str(environment or "").strip() or "ALL"
    if env_value.upper() == "ALL":
        env_scope = "ALL"
    else:
        env_scope = env_value

    database_checks = (
        "query failure",
        "queue pressure",
        "task",
        "procedure",
        "change",
        "drift",
        "storage",
    )
    if any(token in name for token in database_checks):
        if env_scope == "ALL":
            confidence = "Database Context - All Environments"
            evidence = "Checklist source includes database-aware Snowflake facts and is not narrowed to a single environment."
        else:
            confidence = "Database Context"
            evidence = f"Checklist source can be checked against database-aware Snowflake facts scoped to {env_scope}."
        return {
            "ENVIRONMENT_SCOPE": env_scope,
            "DATABASE_CONTEXT": "Yes",
            "SCOPE_CONFIDENCE": confidence,
            "SCOPE_EVIDENCE": evidence,
        }

    if "cost" in name or "contract" in route_text:
        return {
            "ENVIRONMENT_SCOPE": env_scope,
            "DATABASE_CONTEXT": "Allocated / Estimated",
            "SCOPE_CONFIDENCE": "Allocated Estimate",
            "SCOPE_EVIDENCE": (
                "Warehouse metering is shared across database workloads; environment cost is DBA-attributed "
                "and must be treated as allocated/estimated."
            ),
        }

    return {
        "ENVIRONMENT_SCOPE": "No Database Context" if env_scope == "ALL" else env_scope,
        "DATABASE_CONTEXT": "No",
        "SCOPE_CONFIDENCE": "Account-Level Control",
        "SCOPE_EVIDENCE": "Checklist item is an account-level DBA control and should not be filtered as a database fact.",
    }


def _account_health_recovery_target_hours(severity: object) -> int:
    sev = str(severity or "").upper()
    if sev == "CRITICAL":
        return 12
    if sev == "HIGH":
        return 24
    if sev == "MEDIUM":
        return 72
    return 168


def _account_health_readiness_for_row(row: pd.Series | dict) -> dict:
    owner = str(row.get("OWNER") or "").strip()
    severity = str(row.get("SEVERITY") or "").upper()
    approval_group = str(row.get("APPROVAL_GROUP") or row.get("ESCALATION_TARGET") or "").strip()
    proof = str(row.get("PROOF_REQUIRED") or "").strip()
    scope_confidence = str(row.get("SCOPE_CONFIDENCE") or "").strip()
    verification = _account_health_verification_sql(row.get("CHECK"), row.get("EVIDENCE"))
    blockers = []

    generic_owners = {"", "DBA", "UNKNOWN", "N/A", "DBA / COST OWNER", "DBA / DATA ENGINEERING"}
    if owner.upper() in generic_owners and not approval_group:
        blockers.append("escalation route")
    approval_required = severity in {"CRITICAL", "HIGH", "MEDIUM"}
    if approval_required and not approval_group:
        blockers.append("review group")
    if not proof:
        blockers.append("telemetry basis")
    verification_upper = verification.upper()
    if not verification or not any(
        token in verification_upper
        for token in ("SNOWFLAKE.ACCOUNT_USAGE", "INFORMATION_SCHEMA", "OVERWATCH")
    ):
        blockers.append("source telemetry")
    if not scope_confidence:
        blockers.append("scope confidence")

    return {
        "APPROVAL_REQUIRED": "Yes" if approval_required else "No",
        "RECOVERY_SLA_TARGET_HOURS": _account_health_recovery_target_hours(severity),
        "VERIFICATION_QUERY": verification,
        "QUEUE_READINESS": "Ready to Queue" if not blockers else "Needs Routing Data",
        "QUEUE_BLOCKERS": "; ".join(blockers) if blockers else "None",
    }


def _annotate_account_health_checklist_readiness(
    checklist: pd.DataFrame,
    environment: str = "ALL",
) -> pd.DataFrame:
    """Add DBA routing, scope, and queue-readiness telemetry to checklist rows."""
    if checklist is None or checklist.empty:
        return pd.DataFrame() if checklist is None else checklist
    view = checklist.copy()
    if "OWNER_SOURCE" not in view.columns:
        view = _enrich_account_health_checklist_owners(view)
    scope_rows = view.apply(
        lambda row: _account_health_scope_context(row.get("CHECK"), row.get("ROUTE"), environment),
        axis=1,
    )
    for column in ["ENVIRONMENT_SCOPE", "DATABASE_CONTEXT", "SCOPE_CONFIDENCE", "SCOPE_EVIDENCE"]:
        view[column] = scope_rows.apply(lambda item, col=column: item.get(col, ""))
    readiness_rows = view.apply(_account_health_readiness_for_row, axis=1)
    for column in ["APPROVAL_REQUIRED", "RECOVERY_SLA_TARGET_HOURS", "VERIFICATION_QUERY", "QUEUE_READINESS", "QUEUE_BLOCKERS"]:
        view[column] = readiness_rows.apply(lambda item, col=column: item.get(col, ""))
    return view


def _account_health_control_board(
    checklist: pd.DataFrame,
    closure: pd.DataFrame | None = None,
    access_hygiene: pd.DataFrame | None = None,
    trend: pd.DataFrame | None = None,
    environment: str = "ALL",
) -> pd.DataFrame:
    """Combine checklist, account hygiene, history, and closure blockers into one DBA operating board."""
    if checklist is None or checklist.empty:
        base = pd.DataFrame()
    else:
        base = _annotate_account_health_checklist_readiness(checklist, environment=environment)

    closure_view = pd.DataFrame() if closure is None else closure.copy()
    if not closure_view.empty:
        closure_view.columns = [str(col).upper() for col in closure_view.columns]
    trend_view = pd.DataFrame() if trend is None else trend.copy()
    if not trend_view.empty:
        trend_view.columns = [str(col).upper() for col in trend_view.columns]

    closure_by_check = {
        str(row.get("CHECK_NAME") or "").upper(): row
        for _, row in closure_view.iterrows()
    } if not closure_view.empty else {}
    trend_by_check = {
        str(row.get("CHECK_NAME") or "").upper(): row
        for _, row in trend_view.iterrows()
    } if not trend_view.empty else {}

    rows: list[dict] = []
    if not base.empty:
        actionable_checks = set(_account_health_actionable_checklist(base).get("CHECK", pd.Series(dtype=str)).astype(str))
        for _, row in base.iterrows():
            check = str(row.get("CHECK") or "")
            check_key = check.upper()
            close = closure_by_check.get(check_key, {})
            trend_row = trend_by_check.get(check_key, {})
            status = str(row.get("STATUS") or "")
            queue_readiness = str(row.get("QUEUE_READINESS") or "")
            queue_blockers = str(row.get("QUEUE_BLOCKERS") or "")
            open_actions = safe_int(close.get("OPEN_ACTIONS", 0))
            overdue = safe_int(close.get("OVERDUE_OPEN", 0))
            fixed_without_verification = safe_int(close.get("FIXED_WITHOUT_VERIFICATION", 0))
            recovery_risk = safe_int(close.get("RECOVERY_RISK_ROWS", 0))
            verified = safe_int(close.get("VERIFIED_CLOSURES", 0))
            issue_snapshots = safe_int(trend_row.get("ISSUE_SNAPSHOTS", 0))
            closure_rank = safe_int(close.get("CLOSURE_RANK", 9))

            if overdue:
                state, rank = "Closure Overdue", 0
                next_action = "Escalate owner and due date before accepting the checklist control."
            elif fixed_without_verification or recovery_risk or closure_rank in {1, 2}:
                state, rank = "Closure Status Pending", 1
                next_action = str(close.get("NEXT_ACTION") or "Reopen the action for DBA review or wait for telemetry to confirm recovery.")
            elif queue_readiness != "Ready to Queue":
                state, rank = "Route Metadata Blocked", 2
                next_action = f"Complete checklist route metadata: {queue_blockers or 'route, ticket, or telemetry basis'}."
            elif check in actionable_checks and open_actions == 0:
                state, rank = "Queue Required", 3
                next_action = "Save this checklist issue to the action queue with route and telemetry context."
            elif open_actions > 0:
                state, rank = "Work Open Action", 4
                next_action = str(close.get("NEXT_ACTION") or row.get("NEXT_ACTION") or "Work open checklist action.")
            elif issue_snapshots > 1:
                state, rank = "Recurring Watch", 6
                next_action = "Review repeated checklist snapshots and create a durable control if the issue recurs."
            elif verified:
                state, rank = "Closed", 8
                next_action = "Keep closure status visible in the trend review."
            else:
                state, rank = "Controlled", 9
                next_action = str(row.get("NEXT_ACTION") or "No action needed for this snapshot.")

            rows.append({
                "CONTROL_STATE": state,
                "CONTROL_RANK": rank,
                "CHECK_NAME": check,
                "STATUS": status,
                "SEVERITY": row.get("SEVERITY", ""),
                "ROUTE": row.get("ROUTE", ""),
                "OWNER": row.get("OWNER", ""),
                "ESCALATION_TARGET": row.get("ESCALATION_TARGET", ""),
                "ENVIRONMENT_SCOPE": row.get("ENVIRONMENT_SCOPE", ""),
                "DATABASE_CONTEXT": row.get("DATABASE_CONTEXT", ""),
                "SCOPE_CONFIDENCE": row.get("SCOPE_CONFIDENCE", ""),
                "QUEUE_READINESS": queue_readiness,
                "QUEUE_BLOCKERS": queue_blockers,
                "APPROVAL_REQUIRED": row.get("APPROVAL_REQUIRED", ""),
                "RECOVERY_SLA_TARGET_HOURS": safe_float(row.get("RECOVERY_SLA_TARGET_HOURS")),
                "OPEN_ACTIONS": open_actions,
                "OVERDUE_OPEN": overdue,
                "FIXED_WITHOUT_VERIFICATION": fixed_without_verification,
                "RECOVERY_RISK_ROWS": recovery_risk,
                "VERIFIED_CLOSURES": verified,
                "ISSUE_SNAPSHOTS": issue_snapshots,
                "PROOF_REQUIRED": row.get("PROOF_REQUIRED", ""),
                "NEXT_CONTROL_ACTION": next_action,
            })

    hygiene = pd.DataFrame() if access_hygiene is None else access_hygiene.copy()
    if not hygiene.empty:
        hygiene = _annotate_account_health_access_hygiene(hygiene)
        severity = hygiene.get("SEVERITY", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
        high = int(severity.eq("HIGH").sum())
        medium = int(severity.eq("MEDIUM").sum())
        queue_blocks = int((hygiene.get("QUEUE_READINESS", pd.Series(dtype=str)).astype(str) != "Ready to Queue").sum())
        approval_blocks = int((hygiene.get("APPROVAL_REQUIRED", pd.Series(dtype=str)).astype(str) == "Yes").sum())
        if queue_blocks:
            state, rank = "Access Route Blocked", 1
            next_action = "Complete route, review, and telemetry metadata for account-level access hygiene rows."
        elif high:
            state, rank = "High-Risk Access Review", 2
            next_action = "Queue high-risk admin, MFA, stale, or failed-login user hygiene items for Security/DBA review."
        else:
            state, rank = "Access Hygiene Watch", 6
            next_action = "Review medium-risk account hygiene rows and keep account-level telemetry current."
        rows.append({
            "CONTROL_STATE": state,
            "CONTROL_RANK": rank,
            "CHECK_NAME": "Account access hygiene",
            "STATUS": "Needs DBA",
            "SEVERITY": "High" if high else "Medium",
            "ROUTE": "Security Monitoring",
            "OWNER": "DBA / Security",
            "ESCALATION_TARGET": "Security Lead",
            "ENVIRONMENT_SCOPE": "No Database Context",
            "DATABASE_CONTEXT": "No",
            "SCOPE_CONFIDENCE": "Account-Level Control",
            "QUEUE_READINESS": "Needs Routing Data" if queue_blocks else "Ready to Queue",
            "QUEUE_BLOCKERS": f"{queue_blocks:,} route blocker row(s)" if queue_blocks else "None",
            "APPROVAL_REQUIRED": "Yes" if approval_blocks else "No",
            "RECOVERY_SLA_TARGET_HOURS": 24 if high else 72,
            "OPEN_ACTIONS": 0,
            "OVERDUE_OPEN": 0,
            "FIXED_WITHOUT_VERIFICATION": 0,
            "RECOVERY_RISK_ROWS": 0,
            "VERIFIED_CLOSURES": 0,
            "ISSUE_SNAPSHOTS": 0,
            "PROOF_REQUIRED": "user, IAM ticket, admin-role/MFA posture, telemetry status",
            "NEXT_CONTROL_ACTION": (
                f"{len(hygiene):,} user hygiene row(s): {high:,} high, {medium:,} medium. {next_action}"
            ),
        })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        ["CONTROL_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "OPEN_ACTIONS", "SEVERITY", "CHECK_NAME"],
        ascending=[True, False, False, False, True, True],
    ).reset_index(drop=True)


def _account_health_frame_sum(frame: pd.DataFrame | None, column: str) -> int:
    if frame is None or frame.empty or column not in frame.columns:
        return 0
    return int(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())


def _account_health_operator_next_moves(
    *,
    health_score: int | float,
    checklist: pd.DataFrame | None,
    control_board: pd.DataFrame | None = None,
    closure: pd.DataFrame | None = None,
    access_hygiene: pd.DataFrame | None = None,
    operability_fact: pd.DataFrame | None = None,
    source_health: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a no-query action gate for loaded Account Health telemetry."""
    checks = pd.DataFrame() if checklist is None else checklist.copy()
    control = pd.DataFrame() if control_board is None else control_board.copy()
    close = pd.DataFrame() if closure is None else closure.copy()
    hygiene = pd.DataFrame() if access_hygiene is None else access_hygiene.copy()
    fact = pd.DataFrame() if operability_fact is None else operability_fact.copy()
    sources = pd.DataFrame() if source_health is None else source_health.copy()
    for frame in (control, close, hygiene, fact, sources):
        if not frame.empty:
            frame.columns = [str(col).upper() for col in frame.columns]

    actionable = 0
    if not checks.empty:
        annotated = _annotate_account_health_checklist_readiness(checks)
        actionable = len(_account_health_actionable_checklist(annotated))
    issue_rows = max(actionable, _account_health_frame_sum(fact, "ISSUE_ROWS"))
    route_blocks = max(
        int((control.get("QUEUE_READINESS", pd.Series(dtype=str)).astype(str) != "Ready to Queue").sum()) if not control.empty and "QUEUE_READINESS" in control.columns else 0,
        _account_health_frame_sum(fact, "ROUTE_BLOCKER_ROWS"),
        _account_health_frame_sum(fact, "QUEUE_REQUIRED_ROWS"),
    )
    overdue = max(
        _account_health_frame_sum(control, "OVERDUE_OPEN"),
        _account_health_frame_sum(close, "OVERDUE_OPEN"),
        _account_health_frame_sum(fact, "OVERDUE_OPEN"),
    )
    fixed_without_verification = max(
        _account_health_frame_sum(control, "FIXED_WITHOUT_VERIFICATION"),
        _account_health_frame_sum(close, "FIXED_WITHOUT_VERIFICATION"),
        _account_health_frame_sum(fact, "FIXED_WITHOUT_VERIFICATION"),
    )
    recovery_risk = max(
        _account_health_frame_sum(control, "RECOVERY_RISK_ROWS"),
        _account_health_frame_sum(close, "RECOVERY_RISK_ROWS"),
        _account_health_frame_sum(fact, "RECOVERY_RISK_ROWS"),
    )
    verified = max(
        _account_health_frame_sum(control, "VERIFIED_CLOSURES"),
        _account_health_frame_sum(close, "VERIFIED_CLOSURES"),
        _account_health_frame_sum(fact, "VERIFIED_CLOSURES"),
    )
    access_rows = max(
        0 if hygiene.empty else int(len(hygiene)),
        _account_health_frame_sum(fact, "ACCESS_HYGIENE_ROWS"),
        _account_health_frame_sum(fact, "FAILED_LOGIN_ROWS"),
        _account_health_frame_sum(fact, "PRIVILEGED_GRANT_ROWS"),
    )
    access_route_blocks = 0
    if not hygiene.empty and "QUEUE_READINESS" in hygiene.columns:
        access_route_blocks = int(hygiene["QUEUE_READINESS"].astype(str).ne("Ready to Queue").sum())
    if not control.empty and "CHECK_NAME" in control.columns:
        access_route_blocks = max(
            access_route_blocks,
            int(
                (
                    control["CHECK_NAME"].astype(str).str.upper().eq("ACCOUNT ACCESS HYGIENE")
                    & control.get("QUEUE_READINESS", pd.Series(dtype=str)).astype(str).ne("Ready to Queue")
                ).sum()
            ),
        )
    high_access = 0
    if not hygiene.empty and "SEVERITY" in hygiene.columns:
        high_access = int(hygiene["SEVERITY"].fillna("").astype(str).str.upper().isin(["CRITICAL", "HIGH"]).sum())

    stale_sources = 0
    unavailable_sources = 0
    if not sources.empty and "STATE" in sources.columns:
        state = sources["STATE"].fillna("").astype(str).str.upper()
        stale_sources = int(state.eq("STALE").sum())
        unavailable_sources = int(state.eq("UNAVAILABLE").sum())

    rows: list[dict] = []
    closure_blocks = overdue + fixed_without_verification + recovery_risk
    if closure_blocks:
        state, rank, count = "Closure Blocked", 0, closure_blocks
        next_action = "Escalate overdue or telemetry-pending Account Health actions before claiming the account is controlled."
    elif issue_rows and close.empty and fact.empty:
        state, rank, count = "Load Closure Analytics", 4, issue_rows
        next_action = "Load closure analytics before accepting checklist or access-hygiene work as complete."
    else:
        state, rank, count = "Clear", 8, verified
        next_action = "Keep closure status visible in Account Health trends."
    rows.append({
        "GATE": "Closure status",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "telemetry status, ticket, recovery state, closure timestamp",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if route_blocks:
        state, rank, count = "Route Blocked", 1, route_blocks
        next_action = "Complete route, reviewer, scope basis, and telemetry query before queueing."
    elif issue_rows:
        state, rank, count = "Queue Ready", 6, issue_rows
        next_action = "Queue only actionable checklist rows with route and telemetry context attached."
    else:
        state, rank, count = "Clear", 8, 0
        next_action = "No checklist route currently needs DBA action."
    rows.append({
        "GATE": "Checklist route",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "route, reviewer, scope basis, source telemetry, recovery SLA",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if access_route_blocks:
        state, rank, count = "Access Route Blocked", 1, access_route_blocks
        next_action = "Complete IAM/security route, escalation, and review context before queueing account-level access work."
    elif high_access:
        state, rank, count = "High-Risk Access Review", 2, high_access
        next_action = "Prioritize admin-role, MFA, stale-login, and failed-login rows for DBA/Security review."
    elif access_rows:
        state, rank, count = "Access Hygiene Watch", 6, access_rows
        next_action = "Keep account-level telemetry current and queue only medium-or-higher rows."
    else:
        state, rank, count = "Clear", 8, 0
        next_action = "No account-level access hygiene rows are loaded for action."
    rows.append({
        "GATE": "Access hygiene",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "user, IAM ticket, admin-role/MFA posture, failed-login context, telemetry status",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if unavailable_sources:
        state, rank, count = "Source Unavailable", 2, unavailable_sources
        next_action = "Deploy or grant missing Account Health mart/source objects before relying on the board."
    elif stale_sources:
        state, rank, count = "Source Stale", 3, stale_sources
        next_action = "Reload stale Account Health telemetry before queueing or closing work."
    else:
        state, rank, count = "Current", 8, 0
        next_action = "Loaded sources are current for the active Account Health scope."
    rows.append({
        "GATE": "Source readiness",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "fresh source state, load timestamp, scope match, account-level disclosure where needed",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if safe_float(health_score) < 75 or issue_rows:
        state = "Account Review Required" if safe_float(health_score) < 75 else "Checklist Review"
        rank = 5
        count = max(issue_rows, 1)
        next_action = "Work Account Health issues before lower-risk optimization work."
    else:
        state, rank, count = "Controlled", 8, 0
        next_action = "No account-level health pressure crossed the current action threshold."
    rows.append({
        "GATE": "Account pressure",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "health state, failed queries/tasks, queue pressure, storage/cost/change signals",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    return pd.DataFrame(rows).sort_values(["GATE_RANK", "COUNT"], ascending=[True, False]).reset_index(drop=True)


def _account_health_morning_exception_rows(
    *,
    checklist: pd.DataFrame | None,
    gates: pd.DataFrame | None,
    interventions: pd.DataFrame | None,
    control_board: pd.DataFrame | None,
    health_score: float,
    err_count: int,
    queued: int,
    pct_delta: float,
    failed_tasks: int,
) -> pd.DataFrame:
    """Return the compact first-screen exceptions a DBA should triage first."""
    rows: list[dict] = []

    def _add(
        severity: str,
        signal: str,
        entity: str,
        evidence: str,
        next_action: str,
        route: str = "DBA Control Room",
        priority: int = 50,
    ) -> None:
        rows.append({
            "PRIORITY": priority,
            "SEVERITY": severity,
            "SIGNAL": signal,
            "ENTITY": entity,
            "EVIDENCE": evidence,
            "NEXT_ACTION": next_action,
            "ROUTE": _canonical_account_route(route),
        })

    if safe_float(health_score) < 75:
        _add(
            "High",
            "Account pressure",
            "Account",
            "Account pressure crossed the DBA threshold; review blockers before publishing a clean brief.",
            "Work the highest-ranked Account Health gate before lower-priority dashboard review.",
            priority=0,
        )
    if safe_int(err_count) > 0:
        _add(
            "High" if safe_int(err_count) >= 10 else "Medium",
            "Query failures",
            "Workload",
            f"{safe_int(err_count):,} failed query signal(s) in the loaded Account Health snapshot.",
            "Open Workload Operations query diagnosis and validate route, query text, and recovery status.",
            route="Workload Operations",
            priority=5 if safe_int(err_count) >= 10 else 18,
        )
    if safe_int(failed_tasks) > 0:
        _add(
            "High",
            "Task failures",
            "Task graph",
            f"{safe_int(failed_tasks):,} failed task signal(s) in the loaded Account Health snapshot.",
            "Open Workload Operations task graphs and capture Snowflake task/task recovery status.",
            route="Workload Operations",
            priority=6,
        )
    if safe_int(queued) > 0:
        _add(
            "Medium",
            "Queue pressure",
            "Warehouses",
            f"{safe_int(queued):,} queued workload signal(s) are visible in the loaded snapshot.",
            "Review warehouse pressure before resizing or changing workload routing.",
            route="Cost & Contract",
            priority=20,
        )
    if safe_float(pct_delta) > 30:
        _add(
            "Medium",
            "Credit spike",
            "Cost",
            f"24-hour credit movement is +{safe_float(pct_delta):.0f}%.",
            "Open Cost & Contract attribution before treating the account as cost-stable.",
            route="Cost & Contract",
            priority=22,
        )

    gate_view = pd.DataFrame() if gates is None else gates.copy()
    if not gate_view.empty:
        gate_view.columns = [str(col).upper() for col in gate_view.columns]
        if "GATE_RANK" in gate_view.columns:
            gate_view["_RANK"] = pd.to_numeric(gate_view["GATE_RANK"], errors="coerce").fillna(99)
        else:
            gate_view["_RANK"] = 99
        gate_state = gate_view.get("STATE", pd.Series([""] * len(gate_view), index=gate_view.index)).fillna("").astype(str)
        gate_focus = gate_view[
            ~gate_state.str.upper().isin(["CLEAR", "CURRENT", "CONTROLLED"])
        ].sort_values(["_RANK", "COUNT"], ascending=[True, False])
        for _, row in gate_focus.head(3).iterrows():
            rank = safe_int(row.get("_RANK", 9))
            _add(
                "High" if rank <= 1 else "Medium",
                str(row.get("STATE") or "Gate review"),
                str(row.get("GATE") or "Account Health gate"),
                f"{safe_int(row.get('COUNT', 0)):,} row(s) need attention. Telemetry basis: {row.get('PROOF_REQUIRED', '')}",
                str(row.get("NEXT_ACTION") or "Open the Account Health gate and validate telemetry."),
                route="DBA Control Room",
                priority=2 + rank,
            )

    intervention_view = pd.DataFrame() if interventions is None else interventions.copy()
    if not intervention_view.empty:
        intervention_view.columns = [str(col).upper() for col in intervention_view.columns]
        priority_series = intervention_view.get("DBA_PRIORITY", pd.Series([""] * len(intervention_view), index=intervention_view.index))
        focus = intervention_view[priority_series.fillna("").astype(str).str.upper().isin(["P0", "P1"])].copy()
        priority_rank = {"P0": 0, "P1": 1}
        if not focus.empty:
            focus["_RANK"] = focus["DBA_PRIORITY"].astype(str).str.upper().map(priority_rank).fillna(9)
            for _, row in focus.sort_values(["_RANK", "COUNT"], ascending=[True, False]).head(3).iterrows():
                _add(
                    "High" if str(row.get("DBA_PRIORITY", "")).upper() == "P0" else "Medium",
                    str(row.get("INTERVENTION_STATE") or "Intervention"),
                    str(row.get("SURFACE") or row.get("ROUTE") or "Account Health"),
                    str(row.get("NEXT_DECISION") or row.get("NEXT_CONTROL_ACTION") or "DBA intervention required."),
                    str(row.get("PROOF_REQUIRED") or "Route, ticket, review, and telemetry status needed."),
                    route=_canonical_account_route(row.get("ROUTE")),
                    priority=12 + safe_int(row.get("_RANK", 9)),
                )

    control_view = pd.DataFrame() if control_board is None else control_board.copy()
    if not control_view.empty:
        control_view.columns = [str(col).upper() for col in control_view.columns]
        if "CONTROL_RANK" in control_view.columns:
            control_view["_RANK"] = pd.to_numeric(control_view["CONTROL_RANK"], errors="coerce").fillna(99)
            focus = control_view[control_view["_RANK"] <= 3].copy()
        else:
            focus = pd.DataFrame()
        for _, row in focus.sort_values(["_RANK", "OVERDUE_OPEN", "OPEN_ACTIONS"], ascending=[True, False, False]).head(3).iterrows():
            _add(
                "High" if safe_int(row.get("_RANK", 9)) <= 1 else "Medium",
                str(row.get("CONTROL_STATE") or "Control review"),
                str(row.get("CHECK_NAME") or "Account Health control"),
                str(row.get("NEXT_CONTROL_ACTION") or row.get("QUEUE_BLOCKERS") or "Control board review required."),
                str(row.get("PROOF_REQUIRED") or "Source telemetry and closure status needed."),
                route=_canonical_account_route(row.get("ROUTE")),
                priority=16 + safe_int(row.get("_RANK", 9)),
            )

    checklist_view = _account_health_actionable_checklist(checklist)
    if not checklist_view.empty:
        checklist_view = checklist_view.copy()
        checklist_view.columns = [str(col).upper() for col in checklist_view.columns]
        severity_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        checklist_view["_RANK"] = checklist_view.get("SEVERITY", pd.Series([""] * len(checklist_view), index=checklist_view.index)).fillna("").astype(str).str.upper().map(severity_rank).fillna(9)
        for _, row in checklist_view.sort_values(["_RANK", "CHECK"], ascending=[True, True]).head(4).iterrows():
            severity = str(row.get("SEVERITY") or "Medium")
            _add(
                severity if severity.upper() in {"CRITICAL", "HIGH", "MEDIUM"} else "Medium",
                str(row.get("CHECK") or "Checklist issue"),
                str(row.get("ROUTE") or row.get("OWNER") or "Account Health"),
                str(row.get("EVIDENCE") or "Checklist exception needs review."),
                str(row.get("NEXT_ACTION") or "Queue or resolve the checklist exception with telemetry context."),
                route=_canonical_account_route(row.get("ROUTE")),
                priority=24 + safe_int(row.get("_RANK", 9)),
            )

    if not rows:
        return pd.DataFrame(columns=["PRIORITY", "SEVERITY", "SIGNAL", "ENTITY", "EVIDENCE", "NEXT_ACTION", "ROUTE"])

    frame = pd.DataFrame(rows)
    frame["_DEDUP"] = (
        frame["SIGNAL"].fillna("").astype(str).str.upper()
        + "|"
        + frame["ENTITY"].fillna("").astype(str).str.upper()
    )
    frame = frame.sort_values(["PRIORITY", "SEVERITY", "SIGNAL"], ascending=[True, True, True])
    frame = frame.drop_duplicates("_DEDUP", keep="first").drop(columns=["_DEDUP"])
    return frame.head(6).reset_index(drop=True)


def _render_account_health_exception_strip(rows: pd.DataFrame | None) -> None:
    st.markdown("**Morning Exceptions**")
    if rows is None or rows.empty:
        st.success("No immediate Account Health exceptions in the loaded snapshot.")
        return
    for _, row in rows.head(5).iterrows():
        severity = str(row.get("SEVERITY") or "Medium")
        signal = str(row.get("SIGNAL") or "Account Health signal")
        entity = str(row.get("ENTITY") or "Account")
        evidence = str(row.get("EVIDENCE") or "")
        next_action = str(row.get("NEXT_ACTION") or "")
        route = _canonical_account_route(row.get("ROUTE"))
        message = f"{severity}: {signal} - {entity}. {evidence} Next: {next_action} Route: {route}."
        if severity.upper() in {"CRITICAL", "HIGH"}:
            st.warning(message)
        else:
            st.info(message)


def _account_health_action_brief(checklist: pd.DataFrame | None) -> dict:
    """Choose the single Account Health move to show above detailed telemetry."""
    if checklist is None or checklist.empty:
        return {
            "state": "On demand",
            "headline": "Load health telemetry before acting.",
            "detail": "No Account Health checklist rows are loaded for this scope.",
            "primary_label": "Load Health",
            "target": "Overview",
            "workflow": "",
        }
    view = checklist.copy()
    view.columns = [str(col).upper() for col in view.columns]
    if "CHECK" not in view.columns:
        view["CHECK"] = "Account Health"
    severity_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "INFO": 3}
    state_rank = {"NEEDS DBA": 0, "VERIFY SOURCE": 1, "WATCH": 2, "OK": 8, "HEALTHY": 8, "CLEAR": 8}
    status = view.get("STATUS", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str)
    severity = view.get("SEVERITY", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str)
    view["_SEVERITY_RANK"] = severity.str.upper().map(severity_rank).fillna(4)
    view["_STATE_RANK"] = status.str.upper().map(state_rank).fillna(3)
    actionable = view[
        ~status.str.upper().isin(["OK", "HEALTHY", "CLEAR"])
    ].sort_values(["_SEVERITY_RANK", "_STATE_RANK", "CHECK"])
    if actionable.empty:
        return {
            "state": "Clear",
            "headline": "No immediate Account Health blocker.",
            "detail": "Use Morning Report when you need the brief.",
            "primary_label": "Morning Report",
            "target": "Morning Report",
            "workflow": "",
        }
    row = actionable.iloc[0]
    route = _canonical_account_route(row.get("ROUTE"))
    check = str(row.get("CHECK") or "Account Health")
    action = str(row.get("NEXT_ACTION") or "Review the guarded drilldown workflow.")
    evidence = str(row.get("EVIDENCE") or "")
    return {
        "state": str(row.get("STATUS") or row.get("SEVERITY") or "Review"),
        "headline": action,
        "detail": f"{check}: {evidence}".strip(": "),
        "primary_label": f"Open {route}",
        "target": route,
        "workflow": check,
    }


def _render_account_health_action_brief(checklist: pd.DataFrame | None) -> None:
    brief = _account_health_action_brief(checklist)
    render_shell_status_strip(
        state=brief["state"],
        headline=brief["headline"],
        detail=brief["detail"],
    )


def _build_account_health_dba_morning_brief(
    action_session,
    *,
    company: str,
    environment: str,
    credit_price: float,
    lookback_hours: int,
    cortex_budget_usd: float,
    allow_live_fallback: bool = False,
) -> dict:
    """Build the DBA Morning Brief using the Control Room telemetry model."""
    from sections import dba_control_room as dba

    data = dba._load_control_room(
        action_session,
        company,
        credit_price,
        int(lookback_hours),
        safe_float(cortex_budget_usd),
        include_deep_evidence=False,
        allow_live_fallback=bool(allow_live_fallback),
    )
    exceptions = dba._severity_rows(data, credit_price)
    action_queue = data.get("action_queue", pd.DataFrame()) if isinstance(data, dict) else pd.DataFrame()
    command_queue = dba._build_command_queue(action_queue)
    closure_rollup = dba._command_queue_closure_readiness(action_queue)
    source_health = dba._dba_control_source_health_rows(
        data,
        st.session_state,
        company,
        environment,
        int(lookback_hours),
        safe_float(cortex_budget_usd),
        False,
        bool(allow_live_fallback),
    )
    incident_board = dba._dba_incident_board(
        exceptions,
        command_queue,
        closure_rollup,
        source_health,
    )
    section_board = dba._dba_section_operability_board(
        command_queue=command_queue,
        closure_rollup=closure_rollup,
        source_health=source_health,
    )
    operations_priority = dba._dba_operations_priority_index(
        section_board,
        incident_board,
        command_queue,
        source_health,
    )
    handoff_rows = dba._dba_handoff_rows(
        exceptions,
        command_queue,
        closure_rollup,
        source_health,
    )
    _release_gate_summary, release_gate_rows = dba._build_auto_release_readiness_gate(
        data,
        source_health,
    )
    escalation_packet = dba._dba_escalation_packet(
        operations_priority,
        incident_board,
        handoff_rows,
        release_gate_rows,
        company=company,
        environment=environment,
        lookback_hours=int(lookback_hours),
    )
    brief = dba._dba_morning_brief_rows(
        operations_priority,
        escalation_packet,
        handoff_rows,
    )
    markdown = dba._build_dba_morning_brief_markdown(
        brief,
        company=company,
        environment=environment,
        lookback_hours=int(lookback_hours),
    )
    return {
        "data": data,
        "exceptions": exceptions,
        "source_health": source_health,
        "operations_priority": operations_priority,
        "handoff": handoff_rows,
        "escalation_packet": escalation_packet,
        "brief": brief,
        "markdown": markdown,
    }


def _render_account_health_operating_snapshot(
    *,
    health_score: float,
    score_label: str,
    live_val: int,
    queued: int,
    err_count: int,
    last24: float,
    pct_delta: float,
    cost24: float,
    stor_tb: float,
    failed_tasks: int,
    hd: dict,
    live_source: str,
    control_mart_used: bool,
    control_mart_row,
) -> None:
    """Render the Account Health first-screen metrics without crowding the page."""
    render_shell_kpi_row((
        ("Health", f"{health_score:.0f} {score_label}".strip()),
        ("Failures", f"{err_count:,}"),
        ("Queue", f"{queued:,}"),
        ("Cost 24h", f"${cost24:,.0f} ({pct_delta:+.1f}%)"),
    ))
    with st.expander("Secondary metrics", expanded=False):
        render_shell_snapshot((
            ("Active", f"{live_val:,}"),
            ("Credits 24h", format_credits(last24)),
            ("Storage", f"{stor_tb:.1f} TB"),
            ("Failed Tasks", f"{failed_tasks:,}"),
        ))
        st.caption(
            " | ".join([
                metric_confidence_label("composite"),
                metric_confidence_label("exact") + " for input counts",
                str(hd.get("_control_mart_source", "Live telemetry")).replace("OVERWATCH mart", "Fast summary").replace("mart", "summary").replace("source", "input"),
                freshness_note(live_source),
            ])
        )
        if control_mart_used:
            st.caption(f"Snapshot: {control_mart_row.get('SNAPSHOT_TS', '')}")
        st.caption(f"Measurement basis: {hd.get('_account_health_detail_source', 'Unknown')}")


def _account_health_intervention_matrix(
    *,
    checklist: pd.DataFrame | None,
    control_board: pd.DataFrame | None = None,
    closure: pd.DataFrame | None = None,
    access_hygiene: pd.DataFrame | None = None,
    operability_fact: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a compact Account Health worklist from already-loaded account telemetry."""
    control = control_board if isinstance(control_board, pd.DataFrame) else pd.DataFrame()
    hygiene = access_hygiene if isinstance(access_hygiene, pd.DataFrame) else pd.DataFrame()
    fact = operability_fact if isinstance(operability_fact, pd.DataFrame) else pd.DataFrame()
    checks = pd.DataFrame() if checklist is None else _annotate_account_health_checklist_readiness(checklist)

    rows: list[dict] = []
    if not control.empty:
        for _, row in control.head(25).iterrows():
            control_state = str(row.get("CONTROL_STATE") or "Review")
            check_name = str(row.get("CHECK_NAME") or row.get("CHECK") or "Account Health")
            severity = str(row.get("SEVERITY") or "Medium")
            route = str(row.get("ROUTE") or "Account Health")
            queue_readiness = str(row.get("QUEUE_READINESS") or "")
            closure_state = "Open"
            if safe_int(row.get("OVERDUE_OPEN")) > 0:
                closure_state = "Overdue"
            elif safe_int(row.get("FIXED_WITHOUT_VERIFICATION")) > 0:
                closure_state = "Closed pending telemetry"
            elif safe_int(row.get("VERIFIED_CLOSURES")) > 0:
                closure_state = "Verified"
            scope = str(row.get("SCOPE_CONFIDENCE") or row.get("DATABASE_CONTEXT") or "Account-Level Control")

            control_upper = control_state.upper()
            if "BLOCK" in control_upper or closure_state in {"Overdue", "Closed pending telemetry"}:
                state = "Closure Block"
                rank = 0
                decision = "Hold green account-health claims until ticket, route, telemetry, and recovery status are current."
            elif queue_readiness != "Ready to Queue" or "REQUIRED" in control_upper:
                state = "Route Block"
                rank = 1
                decision = "Complete route, reviewer, and telemetry basis before queueing this account-health issue."
            elif severity.upper() in {"CRITICAL", "HIGH"}:
                state = "Intervene"
                rank = 2
                decision = "Work this high-risk account-health issue before routine monitoring."
            else:
                state = "Watch"
                rank = 4
                decision = "Keep on the daily checklist and retain trend telemetry."

            rows.append({
                "DBA_PRIORITY": f"P{rank}",
                "INTERVENTION_STATE": state,
                "SURFACE": check_name,
                "SEVERITY": severity,
                "ROUTE": route,
                "OWNER": str(row.get("OWNER") or "DBA"),
                "CONTROL_STATE": control_state,
                "QUEUE_READINESS": queue_readiness or "Unknown",
                "CLOSURE_READINESS": closure_state,
                "SCOPE_CONFIDENCE": scope,
                "COUNT": max(
                    safe_int(row.get("OPEN_ACTIONS")),
                    safe_int(row.get("ISSUE_SNAPSHOTS")),
                    safe_int(row.get("OVERDUE_OPEN")),
                    1,
                ),
                "NEXT_DECISION": decision,
                "PROOF_REQUIRED": str(row.get("PROOF_REQUIRED") or "route, ticket, telemetry status, recovery state"),
                "_RANK": rank,
            })

    existing_surfaces = {str(row["SURFACE"]).upper() for row in rows}
    if not hygiene.empty and "ACCOUNT ACCESS HYGIENE" not in existing_surfaces:
        severity_series = hygiene.get("SEVERITY", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
        high_rows = int(severity_series.isin(["CRITICAL", "HIGH"]).sum())
        route_blocks = 0
        if "QUEUE_READINESS" in hygiene.columns:
            route_blocks = int(hygiene["QUEUE_READINESS"].fillna("").astype(str).ne("Ready to Queue").sum())
        state = "Route Block" if route_blocks else "Intervene" if high_rows else "Watch"
        rank = 1 if route_blocks else 2 if high_rows else 4
        rows.append({
            "DBA_PRIORITY": f"P{rank}",
            "INTERVENTION_STATE": state,
            "SURFACE": "Account Access Hygiene",
            "SEVERITY": "High" if high_rows else "Medium",
            "ROUTE": "Security Monitoring",
            "OWNER": "DBA / Security",
            "CONTROL_STATE": "High-risk access review" if high_rows else "Access hygiene review",
            "QUEUE_READINESS": "Needs Routing Data" if route_blocks else "Ready to Queue",
            "CLOSURE_READINESS": "No recent action",
            "SCOPE_CONFIDENCE": "Account-Level Control",
            "COUNT": len(hygiene),
            "NEXT_DECISION": "Review privileged grants, failed logins, MFA gaps, and service-user exposure at account scope.",
            "PROOF_REQUIRED": "user, role/grant, MFA/IAM posture, telemetry status",
            "_RANK": rank,
        })

    if not fact.empty and "CONTROL_STATE" in fact.columns:
        blocked = fact["CONTROL_STATE"].fillna("").astype(str).str.contains("Blocked|Overdue|Required|Review", case=False, na=False)
        if int(blocked.sum()) and not rows:
            rows.append({
                "DBA_PRIORITY": "P3",
                "INTERVENTION_STATE": "Fact Review",
                "SURFACE": "Account Health control summary",
                "SEVERITY": "Medium",
                "ROUTE": "DBA Control Room",
                "OWNER": "DBA",
                "CONTROL_STATE": "Summary blocker",
                "QUEUE_READINESS": "Review",
                "CLOSURE_READINESS": "Review",
                "SCOPE_CONFIDENCE": "Mixed",
                "COUNT": int(blocked.sum()),
                "NEXT_DECISION": "Load the matching detailed surface only for the blocked control rows.",
                "PROOF_REQUIRED": "fact row, source surface, escalation route, telemetry status",
                "_RANK": 3,
            })

    if not rows and not checks.empty:
        actionable = _account_health_actionable_checklist(checks)
        if not actionable.empty:
            rows.append({
                "DBA_PRIORITY": "P4",
                "INTERVENTION_STATE": "Checklist Review",
                "SURFACE": "Daily DBA checklist",
                "SEVERITY": "Medium",
                "ROUTE": "DBA Control Room",
                "OWNER": "DBA",
                "CONTROL_STATE": "Checklist issue",
                "QUEUE_READINESS": "Review",
                "CLOSURE_READINESS": "No recent action",
                "SCOPE_CONFIDENCE": "Mixed",
                "COUNT": len(actionable),
                "NEXT_DECISION": "Queue only checklist rows with route, telemetry, and recovery expectations.",
                "PROOF_REQUIRED": "check telemetry, route, telemetry query",
                "_RANK": 4,
            })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        ["_RANK", "COUNT", "SURFACE"],
        ascending=[True, False, True],
    ).drop(columns=["_RANK"], errors="ignore").reset_index(drop=True)


def _account_health_access_hygiene_sql(session, days: int, company: str, environment: str = "ALL") -> str:
    """Build account-level user/auth hygiene SQL for the daily DBA command center.

    Login and user metadata do not carry database context, so this intentionally
    ignores the selected PROD/DEV database environment and labels the scope.
    """
    lookback_days = max(1, int(days or 30))
    user_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.USERS",
        ["HAS_PASSWORD", "EXT_AUTHN_DUO", "LAST_SUCCESS_LOGIN"],
    ))
    has_password_expr = (
        "COALESCE(TO_VARCHAR(u.has_password), 'false')"
        if "HAS_PASSWORD" in user_cols else "'unknown'"
    )
    mfa_expr = (
        "COALESCE(TO_VARCHAR(u.ext_authn_duo), 'unknown')"
        if "EXT_AUTHN_DUO" in user_cols else "'unknown'"
    )
    last_success_expr = (
        "u.last_success_login"
        if "LAST_SUCCESS_LOGIN" in user_cols else "NULL::TIMESTAMP_NTZ"
    )
    user_filter_u = get_user_filter_clause("u.name", company)
    user_filter_lh = get_user_filter_clause("lh.user_name", company)
    user_filter_g = get_user_filter_clause("g.grantee_name", company)
    env_label = sql_literal(str(environment or "ALL"), 100)
    return f"""
WITH login_rollup AS (
    SELECT
        lh.user_name,
        COUNT_IF(lh.is_success = 'NO') AS failed_logins,
        COUNT(DISTINCT IFF(lh.is_success = 'NO', lh.client_ip, NULL)) AS failed_ips,
        MAX(IFF(lh.is_success = 'YES', lh.event_timestamp, NULL)) AS last_login_from_history
    FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY lh
    WHERE lh.event_timestamp >= DATEADD('day', -{lookback_days}, CURRENT_TIMESTAMP())
      {user_filter_lh}
    GROUP BY lh.user_name
),
admin_grants AS (
    SELECT
        g.grantee_name AS user_name,
        COUNT(DISTINCT g.role) AS admin_role_count,
        LISTAGG(DISTINCT g.role, ', ') WITHIN GROUP (ORDER BY g.role) AS admin_roles
    FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS g
    WHERE g.deleted_on IS NULL
      {user_filter_g}
      AND (
          UPPER(g.role) IN ('ACCOUNTADMIN', 'ORGADMIN', 'SECURITYADMIN', 'SYSADMIN', 'USERADMIN')
          OR UPPER(g.role) LIKE '%ADMIN%'
          OR UPPER(g.role) LIKE '%SECURITY%'
      )
    GROUP BY g.grantee_name
),
user_posture AS (
    SELECT
        u.name AS user_name,
        COALESCE(TO_VARCHAR(u.disabled), 'false') AS disabled,
        {has_password_expr} AS has_password,
        {mfa_expr} AS mfa_signal,
        COALESCE(lr.last_login_from_history, {last_success_expr}, u.created_on) AS last_seen,
        COALESCE(lr.failed_logins, 0) AS failed_logins,
        COALESCE(lr.failed_ips, 0) AS failed_ips,
        COALESCE(ag.admin_role_count, 0) AS admin_role_count,
        COALESCE(ag.admin_roles, '') AS admin_roles
    FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
    LEFT JOIN login_rollup lr ON UPPER(u.name) = UPPER(lr.user_name)
    LEFT JOIN admin_grants ag ON UPPER(u.name) = UPPER(ag.user_name)
    WHERE u.deleted_on IS NULL
      {user_filter_u}
)
SELECT
    user_name,
    disabled,
    has_password,
    mfa_signal,
    last_seen,
    failed_logins,
    failed_ips,
    admin_role_count,
    admin_roles,
    DATEDIFF('day', last_seen, CURRENT_TIMESTAMP()) AS days_since_seen,
    CASE
        WHEN failed_logins >= 25 OR failed_ips >= 5 THEN 'High'
        WHEN admin_role_count > 0 AND (mfa_signal = 'unknown' OR LOWER(mfa_signal) <> 'true') THEN 'High'
        WHEN DATEDIFF('day', last_seen, CURRENT_TIMESTAMP()) >= 90 THEN 'Medium'
        WHEN failed_logins > 0 OR admin_role_count > 0 OR (mfa_signal <> 'unknown' AND LOWER(mfa_signal) <> 'true') THEN 'Medium'
        ELSE 'Low'
    END AS severity,
    CONCAT_WS('; ',
        IFF(disabled = 'true', 'disabled user retained in account', NULL),
        IFF(failed_logins > 0, failed_logins || ' failed login(s)', NULL),
        IFF(failed_ips >= 5, failed_ips || ' failed login source IP(s)', NULL),
        IFF(admin_role_count > 0, admin_role_count || ' privileged role grant(s)', NULL),
        IFF(mfa_signal <> 'unknown' AND LOWER(mfa_signal) <> 'true', 'MFA signal missing', NULL),
        IFF(DATEDIFF('day', last_seen, CURRENT_TIMESTAMP()) >= 90, 'dormant >= 90 days', NULL)
    ) AS posture_findings,
    'No Database Context' AS database_context,
    'No Database Context' AS environment_scope,
    {env_label} AS selected_environment,
    'Account-Level Control' AS scope_confidence,
    'USERS, LOGIN_HISTORY, and GRANTS_TO_USERS do not expose database context; company scope uses user naming only.' AS scope_evidence,
    'Confirm IAM route, admin-role business need, MFA posture, and recent login telemetry before disabling users or changing grants.' AS next_action,
    'user, IAM ticket, failed login context, MFA/admin-role telemetry' AS proof_required
FROM user_posture
WHERE
    failed_logins > 0
    OR admin_role_count > 0
    OR (mfa_signal <> 'unknown' AND LOWER(mfa_signal) <> 'true')
    OR DATEDIFF('day', last_seen, CURRENT_TIMESTAMP()) >= 90
ORDER BY
    CASE severity WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
    failed_logins DESC,
    admin_role_count DESC,
    days_since_seen DESC
LIMIT 100
""".strip()


def _annotate_account_health_access_hygiene(hygiene: pd.DataFrame) -> pd.DataFrame:
    """Add owner, queue, and scope readiness to account-level access hygiene rows."""
    if hygiene is None or hygiene.empty:
        return pd.DataFrame() if hygiene is None else hygiene
    view = hygiene.copy()
    view.columns = [str(col).upper() for col in view.columns]

    def _context(row: pd.Series) -> dict:
        return resolve_owner_context(
            {
                "ENTITY_NAME": row.get("USER_NAME", ""),
                "CATEGORY": "Account Health Access Hygiene",
                "OWNER": "DBA / Security",
            },
            entity=row.get("USER_NAME", ""),
            entity_type="SECURITY",
            owner="DBA / Security",
            category="Account Health Access Hygiene",
        )

    contexts = view.apply(_context, axis=1)
    view["OWNER"] = contexts.apply(lambda item: item.get("OWNER") or "DBA / Security")
    view["OWNER_EMAIL"] = contexts.apply(lambda item: item.get("OWNER_EMAIL", ""))
    view["ONCALL_PRIMARY"] = contexts.apply(lambda item: item.get("ONCALL_PRIMARY", ""))
    view["APPROVAL_GROUP"] = contexts.apply(lambda item: item.get("APPROVAL_GROUP", "Security Approver"))
    view["ESCALATION_TARGET"] = contexts.apply(lambda item: item.get("ESCALATION_TARGET", "Security Lead"))
    view["OWNER_SOURCE"] = contexts.apply(lambda item: item.get("OWNER_SOURCE", "Default security route"))
    view["OWNER_EVIDENCE"] = contexts.apply(lambda item: item.get("OWNER_EVIDENCE", ""))

    if "DATABASE_CONTEXT" not in view.columns:
        view["DATABASE_CONTEXT"] = "No Database Context"
    if "ENVIRONMENT_SCOPE" not in view.columns:
        view["ENVIRONMENT_SCOPE"] = "No Database Context"
    if "SCOPE_CONFIDENCE" not in view.columns:
        view["SCOPE_CONFIDENCE"] = "Account-Level Control"
    if "SCOPE_EVIDENCE" not in view.columns:
        view["SCOPE_EVIDENCE"] = (
            "USERS, LOGIN_HISTORY, and GRANTS_TO_USERS do not expose database context; "
            "company scope uses user naming only."
        )

    severity = view.get("SEVERITY", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.upper()
    proof = view.get("PROOF_REQUIRED", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str)
    owner = view["OWNER"].fillna("").astype(str).str.upper()
    approval_group = view["APPROVAL_GROUP"].fillna("").astype(str)
    route_ready = (~owner.isin({"", "DBA", "UNKNOWN", "N/A"})) | (approval_group.str.len() > 0)
    approval_required = severity.isin({"HIGH", "MEDIUM"})
    proof_ready = proof.str.len() > 0
    view["APPROVAL_REQUIRED"] = approval_required.map({True: "Yes", False: "No"})
    view["QUEUE_READINESS"] = (
        route_ready & proof_ready & (~approval_required | (approval_group.str.len() > 0))
    ).map({True: "Ready to Queue", False: "Needs Routing Data"})
    view["QUEUE_BLOCKERS"] = "None"
    view.loc[~route_ready, "QUEUE_BLOCKERS"] = "escalation route"
    view.loc[~proof_ready, "QUEUE_BLOCKERS"] = view.loc[~proof_ready, "QUEUE_BLOCKERS"].replace("None", "telemetry basis")
    view.loc[approval_required & (approval_group.str.len() == 0), "QUEUE_BLOCKERS"] = "review group"
    rank = {"HIGH": 1, "MEDIUM": 2, "LOW": 3}
    view["ACCESS_RISK_RANK"] = severity.map(rank).fillna(4).astype(int)
    view["RECOVERY_SLA_TARGET_HOURS"] = severity.apply(_account_health_recovery_target_hours)
    return view


def _account_health_checklist_history_insert_sql(
    checklist: pd.DataFrame,
    *,
    company: str,
    environment: str,
    health_score: float,
    detail_source: str = "",
    snapshot_id: str = "",
) -> str:
    if checklist is None or checklist.empty:
        raise ValueError("Daily DBA Checklist snapshot has no rows to save.")
    fqn = account_health_checklist_history_fqn()
    env_value = str(environment or "").strip() or "ALL"
    snap = snapshot_id or make_action_id(
        "Account Health Checklist Snapshot",
        company,
        f"{env_value}|{datetime.now().strftime('%Y%m%d%H%M%S')}",
    )
    checklist = _annotate_account_health_checklist_readiness(checklist, environment=env_value)
    control_board = _account_health_control_board(checklist, environment=env_value)
    control_by_check = {
        str(row.get("CHECK_NAME") or "").upper(): row
        for _, row in control_board.iterrows()
    } if not control_board.empty else {}
    selects = []
    actionable = _account_health_actionable_checklist(checklist)
    actionable_checks = set(actionable.get("CHECK", pd.Series(dtype=str)).astype(str).tolist())
    for _, row in checklist.head(100).iterrows():
        check = str(row.get("CHECK") or "")
        control = control_by_check.get(check.upper(), {})
        selects.append(
            "SELECT "
            f"{sql_literal(snap, 64)} AS SNAPSHOT_ID, "
            "CURRENT_TIMESTAMP() AS SNAPSHOT_TS, "
            f"{sql_literal(company, 100)} AS COMPANY, "
            f"{sql_literal(env_value, 100)} AS ENVIRONMENT, "
            f"{sql_literal(check, 200)} AS CHECK_NAME, "
            f"{sql_literal(row.get('STATUS', ''), 80)} AS STATUS, "
            f"{sql_literal(row.get('SEVERITY', ''), 40)} AS SEVERITY, "
            f"{sql_literal(row.get('EVIDENCE', ''), 2000)} AS EVIDENCE, "
            f"{sql_literal(row.get('OWNER', ''), 200)} AS OWNER, "
            f"{sql_literal(row.get('ESCALATION_TARGET', ''), 200)} AS ESCALATION_TARGET, "
            f"{sql_literal(row.get('OWNER_SOURCE', ''), 200)} AS OWNER_SOURCE, "
            f"{sql_literal(row.get('ROUTE', ''), 120)} AS ROUTE, "
            f"{sql_literal(row.get('NEXT_ACTION', ''), 4000)} AS NEXT_ACTION, "
            f"{sql_literal(row.get('PROOF_REQUIRED', ''), 2000)} AS PROOF_REQUIRED, "
            f"{sql_literal(row.get('ENVIRONMENT_SCOPE', ''), 100)} AS ENVIRONMENT_SCOPE, "
            f"{sql_literal(row.get('DATABASE_CONTEXT', ''), 80)} AS DATABASE_CONTEXT, "
            f"{sql_literal(row.get('SCOPE_CONFIDENCE', ''), 160)} AS SCOPE_CONFIDENCE, "
            f"{sql_literal(row.get('SCOPE_EVIDENCE', ''), 2000)} AS SCOPE_EVIDENCE, "
            f"{sql_literal(row.get('APPROVAL_REQUIRED', ''), 20)} AS APPROVAL_REQUIRED, "
            f"{sql_literal(row.get('QUEUE_READINESS', ''), 80)} AS QUEUE_READINESS, "
            f"{sql_literal(row.get('QUEUE_BLOCKERS', ''), 2000)} AS QUEUE_BLOCKERS, "
            f"{sql_literal(row.get('VERIFICATION_QUERY', ''), 8000)} AS VERIFICATION_QUERY, "
            f"{safe_float(row.get('RECOVERY_SLA_TARGET_HOURS'))}::FLOAT AS RECOVERY_SLA_TARGET_HOURS, "
            f"{sql_literal(control.get('CONTROL_STATE', ''), 100)} AS CONTROL_READINESS, "
            f"{sql_literal(row.get('QUEUE_BLOCKERS', ''), 2000)} AS CONTROL_BLOCKERS, "
            f"{sql_literal(control.get('NEXT_CONTROL_ACTION', row.get('NEXT_ACTION', '')), 4000)} AS NEXT_CONTROL_ACTION, "
            f"{safe_float(health_score)}::FLOAT AS HEALTH_SCORE, "
            f"{sql_literal(detail_source, 500)} AS DETAIL_SOURCE, "
            f"{'TRUE' if check in actionable_checks else 'FALSE'} AS ACTIONABLE"
        )
    return f"""
INSERT INTO {fqn} (
    SNAPSHOT_ID, SNAPSHOT_TS, COMPANY, ENVIRONMENT, CHECK_NAME, STATUS,
    SEVERITY, EVIDENCE, OWNER, ESCALATION_TARGET, OWNER_SOURCE, ROUTE,
    NEXT_ACTION, PROOF_REQUIRED, ENVIRONMENT_SCOPE, DATABASE_CONTEXT,
    SCOPE_CONFIDENCE, SCOPE_EVIDENCE, APPROVAL_REQUIRED, QUEUE_READINESS,
    QUEUE_BLOCKERS, VERIFICATION_QUERY, RECOVERY_SLA_TARGET_HOURS,
    CONTROL_READINESS, CONTROL_BLOCKERS, NEXT_CONTROL_ACTION, HEALTH_SCORE,
    DETAIL_SOURCE, ACTIONABLE
)
{" UNION ALL ".join(selects)}""".strip()


def _account_health_checklist_history_sql(days: int, company: str, environment: str = "ALL") -> str:
    fqn = account_health_checklist_history_fqn()
    where = [f"SNAPSHOT_TS >= DATEADD('day', -{max(1, int(days or 14))}, CURRENT_TIMESTAMP())"]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_value = str(environment or "").strip()
    if env_value and env_value.upper() != "ALL":
        where.append(f"ENVIRONMENT = {sql_literal(env_value, 100)}")
    where_clause = " AND ".join(where)
    return f"""
SELECT
    CHECK_NAME,
    COUNT(*) AS SNAPSHOT_ROWS,
    COUNT_IF(ACTIONABLE) AS ISSUE_SNAPSHOTS,
    MAX(SNAPSHOT_TS) AS LAST_SNAPSHOT_TS,
    MAX_BY(STATUS, SNAPSHOT_TS) AS LAST_STATUS,
    MAX_BY(SEVERITY, SNAPSHOT_TS) AS LAST_SEVERITY,
    MAX_BY(OWNER, SNAPSHOT_TS) AS OWNER,
    MAX_BY(ESCALATION_TARGET, SNAPSHOT_TS) AS ESCALATION_TARGET,
    MAX_BY(ROUTE, SNAPSHOT_TS) AS ROUTE,
    MAX_BY(QUEUE_READINESS, SNAPSHOT_TS) AS QUEUE_READINESS,
    MAX_BY(QUEUE_BLOCKERS, SNAPSHOT_TS) AS QUEUE_BLOCKERS,
    MAX_BY(SCOPE_CONFIDENCE, SNAPSHOT_TS) AS SCOPE_CONFIDENCE,
    MAX_BY(CONTROL_READINESS, SNAPSHOT_TS) AS CONTROL_READINESS,
    MAX_BY(NEXT_CONTROL_ACTION, SNAPSHOT_TS) AS NEXT_CONTROL_ACTION,
    COUNT_IF(QUEUE_READINESS <> 'Ready to Queue') AS ROUTE_BLOCKER_SNAPSHOTS,
    COUNT_IF(CONTROL_READINESS IN ('Closure Overdue', 'Closure Status Pending', 'Route Metadata Blocked', 'Queue Required')) AS CONTROL_BLOCKER_SNAPSHOTS,
    ROUND(AVG(HEALTH_SCORE), 1) AS AVG_HEALTH_SCORE
FROM {fqn}
WHERE {where_clause}
GROUP BY CHECK_NAME
ORDER BY CONTROL_BLOCKER_SNAPSHOTS DESC, ISSUE_SNAPSHOTS DESC, LAST_SNAPSHOT_TS DESC, CHECK_NAME
LIMIT 100""".strip()


def _account_health_closure_analytics_sql(days: int, company: str, environment: str = "ALL") -> str:
    fqn = account_health_action_queue_fqn()
    where = [
        (
            "SOURCE IN ("
            f"{sql_literal(ACCOUNT_HEALTH_ACTION_SOURCE, 100)}, "
            f"{sql_literal(ACCOUNT_HEALTH_ACCESS_HYGIENE_SOURCE, 100)}"
            ")"
        ),
        f"COALESCE(UPDATED_AT, CREATED_AT) >= DATEADD('day', -{max(1, int(days or 30))}, CURRENT_TIMESTAMP())",
    ]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_clause = action_queue_environment_clause("ENVIRONMENT", environment)
    if env_clause:
        where.append(env_clause)
    where_clause = " AND ".join(where)
    return f"""
WITH scoped_actions AS (
    SELECT
        COALESCE(ENTITY_NAME, 'Daily DBA checklist') AS CHECK_NAME,
        COALESCE(OWNER, '') AS OWNER,
        COALESCE(APPROVER, '') AS APPROVER,
        COALESCE(STATUS, 'New') AS STATUS,
        COALESCE(SEVERITY, 'Medium') AS SEVERITY,
        COALESCE(TICKET_ID, '') AS TICKET_ID,
        DUE_DATE,
        COALESCE(VERIFICATION_STATUS, '') AS VERIFICATION_STATUS,
        COALESCE(VERIFICATION_QUERY, PROOF_QUERY, '') AS VERIFICATION_QUERY,
        COALESCE(VERIFICATION_RESULT, '') AS VERIFICATION_RESULT,
        COALESCE(OWNER_APPROVAL_STATUS, '') AS OWNER_APPROVAL_STATUS,
        COALESCE(RECOVERY_SLA_STATE, '') AS RECOVERY_SLA_STATE,
        COALESCE(RECOVERY_EVIDENCE, '') AS RECOVERY_EVIDENCE,
        COALESCE(UPDATED_AT, CREATED_AT) AS LAST_ACTIVITY_TS
    FROM {fqn}
    WHERE {where_clause}
),
rollup AS (
    SELECT
        CHECK_NAME,
        MAX_BY(OWNER, LAST_ACTIVITY_TS) AS OWNER,
        MAX_BY(APPROVER, LAST_ACTIVITY_TS) AS APPROVER,
        COUNT(*) AS TOTAL_ACTIONS,
        COUNT_IF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED')) AS OPEN_ACTIONS,
        COUNT_IF(UPPER(STATUS) = 'FIXED') AS FIXED_ACTIONS,
        COUNT_IF(
            UPPER(STATUS) = 'FIXED'
            AND UPPER(VERIFICATION_STATUS) = 'VERIFIED'
            AND LENGTH(TRIM(VERIFICATION_RESULT)) >= 15
        ) AS VERIFIED_CLOSURES,
        COUNT_IF(
            UPPER(STATUS) = 'FIXED'
            AND (
                UPPER(VERIFICATION_STATUS) <> 'VERIFIED'
                OR LENGTH(TRIM(VERIFICATION_RESULT)) < 15
            )
        ) AS FIXED_WITHOUT_VERIFICATION,
        COUNT_IF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) AS OVERDUE_OPEN,
        COUNT_IF(UPPER(OWNER) IN ('', 'DBA', 'UNKNOWN', 'N/A', 'DBA / COST OWNER', 'DBA / DATA ENGINEERING')) AS OWNER_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(TICKET_ID)) = 0) AS TICKET_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(APPROVER)) = 0) AS APPROVER_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(VERIFICATION_QUERY)) = 0) AS VERIFICATION_QUERY_GAP_ROWS,
        COUNT_IF(UPPER(OWNER_APPROVAL_STATUS) IN ('', 'PENDING', 'REQUESTED', 'REQUIRED')) AS OWNER_APPROVAL_GAP_ROWS,
        COUNT_IF(
            UPPER(RECOVERY_SLA_STATE) ILIKE '%BREACH%'
            OR UPPER(RECOVERY_SLA_STATE) ILIKE '%LATE%'
            OR (
                UPPER(RECOVERY_SLA_STATE) IN ('OPEN FAILURE', 'RECOVERY SLA BREACH')
                AND LENGTH(TRIM(RECOVERY_EVIDENCE)) = 0
            )
        ) AS RECOVERY_RISK_ROWS,
        MIN(IFF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED'), DUE_DATE, NULL)) AS NEXT_DUE_DATE,
        MAX(LAST_ACTIVITY_TS) AS LAST_ACTIVITY_TS,
        MAX_BY(STATUS, LAST_ACTIVITY_TS) AS LAST_STATUS,
        MAX_BY(SEVERITY, LAST_ACTIVITY_TS) AS LAST_SEVERITY
    FROM scoped_actions
    GROUP BY CHECK_NAME
)
SELECT
    CHECK_NAME,
    CASE
        WHEN OVERDUE_OPEN > 0 THEN 'Overdue closure'
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 'Closed pending telemetry'
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 'Control metadata gap'
        WHEN OPEN_ACTIONS > 0 THEN 'Open'
        WHEN VERIFIED_CLOSURES > 0 THEN 'Telemetry closure'
        ELSE 'No recent action'
    END AS CLOSURE_READINESS,
    CASE
        WHEN OVERDUE_OPEN > 0 THEN 0
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 1
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 2
        WHEN OPEN_ACTIONS > 0 THEN 3
        WHEN VERIFIED_CLOSURES > 0 THEN 8
        ELSE 9
    END AS CLOSURE_RANK,
    OWNER,
    APPROVER,
    TOTAL_ACTIONS,
    OPEN_ACTIONS,
    FIXED_ACTIONS,
    VERIFIED_CLOSURES,
    FIXED_WITHOUT_VERIFICATION,
    OVERDUE_OPEN,
    OWNER_GAP_ROWS,
    TICKET_GAP_ROWS,
    APPROVER_GAP_ROWS,
    VERIFICATION_QUERY_GAP_ROWS,
    OWNER_APPROVAL_GAP_ROWS,
    RECOVERY_RISK_ROWS,
    NEXT_DUE_DATE,
    LAST_STATUS,
    LAST_SEVERITY,
    LAST_ACTIVITY_TS,
    CASE
        WHEN OVERDUE_OPEN > 0 THEN 'Escalate owner and due date before lower-risk checklist work.'
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 'Reopen the checklist action or wait for telemetry to confirm closure.'
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 'Complete route, ticket, reviewer, and telemetry metadata.'
        WHEN OPEN_ACTIONS > 0 THEN 'Work the open checklist action and keep telemetry current before closing.'
        ELSE 'Keep closure status visible for trend review.'
    END AS NEXT_ACTION
FROM rollup
ORDER BY CLOSURE_RANK, OVERDUE_OPEN DESC, FIXED_WITHOUT_VERIFICATION DESC, OPEN_ACTIONS DESC, LAST_ACTIVITY_TS DESC
LIMIT 100""".strip()


def _account_health_operability_fact_sql(days: int, company: str, environment: str = "ALL") -> str:
    """Read Account Health checklist, hygiene, and closure blockers from the fast summary."""
    table = account_health_operability_fact_fqn()
    where = [f"SNAPSHOT_DATE >= DATEADD('day', -{max(1, int(days or 30))}, CURRENT_DATE())"]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_clause = action_queue_environment_clause("ENVIRONMENT", environment)
    if env_clause:
        where.append(env_clause)
    where_clause = " AND ".join(where)
    return f"""
SELECT
    SNAPSHOT_DATE,
    COMPANY,
    ENVIRONMENT,
    CONTROL_SOURCE,
    CHECK_NAME,
    ROUTE,
    SEVERITY,
    CONTROL_STATE,
    CONTROL_RANK,
    HEALTH_SCORE,
    ISSUE_ROWS,
    ROUTE_BLOCKER_ROWS,
    QUEUE_REQUIRED_ROWS,
    ACCESS_HYGIENE_ROWS,
    FAILED_LOGIN_ROWS,
    PRIVILEGED_GRANT_ROWS,
    OPEN_ACTIONS,
    OVERDUE_OPEN,
    FIXED_WITHOUT_VERIFICATION,
    VERIFIED_CLOSURES,
    OWNER_APPROVAL_GAP_ROWS,
    RECOVERY_RISK_ROWS,
    NEXT_CONTROL_ACTION,
    LAST_ACTIVITY_TS,
    LOAD_TS
FROM {table}
WHERE {where_clause}
ORDER BY
    CONTROL_RANK,
    OVERDUE_OPEN DESC,
    FIXED_WITHOUT_VERIFICATION DESC,
    ROUTE_BLOCKER_ROWS DESC,
    ISSUE_ROWS DESC,
    LAST_ACTIVITY_TS DESC
LIMIT 100""".strip()


def _save_account_health_checklist_snapshot(
    session,
    checklist: pd.DataFrame,
    *,
    company: str,
    environment: str,
    health_score: float,
    detail_source: str = "",
) -> None:
    try:
        session.sql(build_account_health_checklist_history_ddl()).collect()
        for migration_sql in build_account_health_checklist_history_migration_sql():
            session.sql(migration_sql).collect()
        session.sql(_account_health_checklist_history_insert_sql(
            checklist,
            company=company,
            environment=environment,
            health_score=health_score,
            detail_source=detail_source,
        )).collect()
        st.success("Saved the Daily DBA Checklist snapshot for trend tracking.")
    except Exception as exc:
        st.error(f"Could not save Daily DBA Checklist snapshot: {format_snowflake_error(exc)}")
        st.info("Checklist history is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")


def _account_health_checklist_action_payload(row: pd.Series | dict, company: str, environment: str = "") -> dict:
    if "QUEUE_READINESS" not in row or "SCOPE_CONFIDENCE" not in row:
        annotated = _annotate_account_health_checklist_readiness(pd.DataFrame([dict(row)]), environment=environment)
        if annotated is not None and not annotated.empty:
            row = annotated.iloc[0].to_dict()
    check = str(row.get("CHECK") or "Daily DBA checklist")
    evidence = str(row.get("EVIDENCE") or "")
    severity = str(row.get("SEVERITY") or "Medium")
    owner = str(row.get("OWNER") or "DBA")
    escalation = str(row.get("ESCALATION_TARGET") or "DBA Lead")
    route = str(row.get("ROUTE") or "DBA Control Room")
    approval_group = str(row.get("APPROVAL_GROUP") or escalation or owner)
    verification_query = _account_health_verification_sql(check, evidence)
    action = str(row.get("NEXT_ACTION") or "Review the failed Account Health checklist item and keep telemetry current.")
    approval_required = severity.upper() in {"CRITICAL", "HIGH", "MEDIUM"}
    env_value = str(environment or "").strip()
    if not env_value or env_value.upper() == "ALL":
        env_value = "No Database Context"
    return {
        "Action ID": make_action_id("Account Health Checklist", check, f"{company}|{evidence}"),
        "Source": ACCOUNT_HEALTH_ACTION_SOURCE,
        "Severity": "Low" if severity.upper() == "INFO" else severity,
        "Category": "Daily DBA Checklist",
        "Entity Type": "DBA Checklist",
        "Entity": check,
        "Owner": owner,
        "Owner Email": row.get("OWNER_EMAIL", ""),
        "Oncall Primary": row.get("ONCALL_PRIMARY", ""),
        "Oncall Secondary": row.get("ONCALL_SECONDARY", ""),
        "Review Group": approval_group,
        "Escalation Target": escalation,
        "Owner Source": row.get("OWNER_SOURCE", ""),
        "Owner Evidence": row.get("OWNER_EVIDENCE", ""),
        "Finding": f"{check}: {evidence}",
        "Action": action,
        "Estimated Monthly Savings": 0.0,
        "Generated SQL Fix": "\n".join([
            "-- Daily DBA checklist action. Do not execute state-changing SQL from this row.",
            f"-- Route: {route}",
            f"-- Telemetry basis: {row.get('PROOF_REQUIRED', 'telemetry status')}",
            f"-- Queue readiness: {row.get('QUEUE_READINESS', 'Ready to Queue')}",
            f"-- Scope basis: {row.get('SCOPE_CONFIDENCE', 'Account-Level Control')}",
        ]),
        "Proof Query": verification_query,
        "Verification Query": verification_query,
        "Verification Status": "Pending",
        "Approver": approval_group if approval_required else owner,
        "Verification Status": "Requested" if approval_required else "Not Required",
        "Verification Note": (
            f"Checklist status: {row.get('STATUS', '')}. Route: {route}. "
            f"Escalation: {escalation}. Route basis: {row.get('OWNER_EVIDENCE', '')}. "
            f"Queue readiness: {row.get('QUEUE_READINESS', '')}; blockers: {row.get('QUEUE_BLOCKERS', '')}. "
            f"Scope: {row.get('SCOPE_CONFIDENCE', '')}."
        ),
        "Recovery Evidence": (
            f"Telemetry basis: {row.get('PROOF_REQUIRED', 'telemetry status')}. Detail: {evidence}. "
            f"Scope basis: {row.get('SCOPE_EVIDENCE', '')}."
        ),
        "Recovery Audit State": "Checklist Telemetry Pending",
        "Recovery SLA Target Hours": row.get("RECOVERY_SLA_TARGET_HOURS", _account_health_recovery_target_hours(severity)),
        "Company": company,
        "Environment": env_value,
    }


def _queue_account_health_checklist(session, checklist: pd.DataFrame, company: str, environment: str) -> None:
    checklist = _annotate_account_health_checklist_readiness(checklist, environment=environment)
    actionable = _account_health_actionable_checklist(checklist)
    if actionable.empty:
        st.info("No Daily DBA Checklist issues need queueing for the current snapshot.")
        return
    actions = [
        _account_health_checklist_action_payload(row, company=company, environment=environment)
        for _, row in actionable.head(25).iterrows()
    ]
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} Daily DBA Checklist issue(s) to the action queue.")
    except Exception as exc:
        st.error(f"Could not save Daily DBA Checklist issues: {format_snowflake_error(exc)}")
        st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")


def _account_health_access_hygiene_verification_sql(row: pd.Series | dict, days: int = 30) -> str:
    """Read-only verification for a user/auth hygiene action."""
    user_name = str(row.get("USER_NAME") or row.get("Entity") or "").strip()
    user_lit = sql_literal(user_name, 256)
    lookback = max(1, int(days or 30))
    return f"""
WITH selected_user AS (
    SELECT {user_lit} AS user_name
),
login_rollup AS (
    SELECT
        lh.user_name,
        COUNT_IF(lh.is_success = 'NO') AS failed_logins,
        COUNT(DISTINCT IFF(lh.is_success = 'NO', lh.client_ip, NULL)) AS failed_ips,
        MAX(IFF(lh.is_success = 'YES', lh.event_timestamp, NULL)) AS last_success_login
    FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY lh
    JOIN selected_user su ON UPPER(lh.user_name) = UPPER(su.user_name)
    WHERE lh.event_timestamp >= DATEADD('day', -{lookback}, CURRENT_TIMESTAMP())
    GROUP BY lh.user_name
),
admin_grants AS (
    SELECT
        g.grantee_name AS user_name,
        LISTAGG(DISTINCT g.role, ', ') WITHIN GROUP (ORDER BY g.role) AS admin_roles,
        COUNT(DISTINCT g.role) AS admin_role_count
    FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS g
    JOIN selected_user su ON UPPER(g.grantee_name) = UPPER(su.user_name)
    WHERE g.deleted_on IS NULL
      AND (
          UPPER(g.role) IN ('ACCOUNTADMIN', 'ORGADMIN', 'SECURITYADMIN', 'SYSADMIN', 'USERADMIN')
          OR UPPER(g.role) LIKE '%ADMIN%'
          OR UPPER(g.role) LIKE '%SECURITY%'
      )
    GROUP BY g.grantee_name
)
SELECT
    su.user_name,
    COALESCE(TO_VARCHAR(u.disabled), 'unknown') AS disabled,
    COALESCE(TO_VARCHAR(u.has_password), 'unknown') AS has_password,
    COALESCE(TO_VARCHAR(u.ext_authn_duo), 'unknown') AS mfa_signal,
    COALESCE(lr.failed_logins, 0) AS failed_logins,
    COALESCE(lr.failed_ips, 0) AS failed_ips,
    COALESCE(ag.admin_role_count, 0) AS admin_role_count,
    COALESCE(ag.admin_roles, '') AS admin_roles,
    COALESCE(lr.last_success_login, u.last_success_login, u.created_on) AS last_seen,
    'No Database Context' AS environment_scope,
    'Account-Level Control' AS scope_confidence
FROM selected_user su
LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON UPPER(u.name) = UPPER(su.user_name)
LEFT JOIN login_rollup lr ON UPPER(lr.user_name) = UPPER(su.user_name)
LEFT JOIN admin_grants ag ON UPPER(ag.user_name) = UPPER(su.user_name)
""".strip()


def _account_health_access_hygiene_action_payload(
    row: pd.Series | dict,
    company: str,
    days: int = 30,
) -> dict:
    """Build a review-only action queue item for account-level user/auth hygiene."""
    if "QUEUE_READINESS" not in row:
        annotated = _annotate_account_health_access_hygiene(pd.DataFrame([dict(row)]))
        if annotated is not None and not annotated.empty:
            row = annotated.iloc[0].to_dict()
    user_name = str(row.get("USER_NAME") or "Unknown User")
    severity = str(row.get("SEVERITY") or "Medium")
    findings = str(row.get("POSTURE_FINDINGS") or "Account access hygiene review required.")
    owner = str(row.get("OWNER") or "DBA / Security")
    approval_group = str(row.get("APPROVAL_GROUP") or "Security Approver")
    verification_query = _account_health_access_hygiene_verification_sql(row, days=days)
    return {
        "Action ID": make_action_id("Account Health Access Hygiene", user_name, f"{company}|{findings}"),
        "Source": ACCOUNT_HEALTH_ACCESS_HYGIENE_SOURCE,
        "Severity": severity,
        "Category": "Account Access Hygiene",
        "Entity Type": "User",
        "Entity": user_name,
        "Owner": owner,
        "Owner Email": row.get("OWNER_EMAIL", ""),
        "Oncall Primary": row.get("ONCALL_PRIMARY", ""),
        "Oncall Secondary": row.get("ONCALL_SECONDARY", ""),
        "Review Group": approval_group,
        "Escalation Target": row.get("ESCALATION_TARGET", "Security Lead"),
        "Owner Source": row.get("OWNER_SOURCE", ""),
        "Owner Evidence": row.get("OWNER_EVIDENCE", ""),
        "Finding": f"{user_name}: {findings}",
        "Action": str(row.get("NEXT_ACTION") or "Confirm IAM route, MFA posture, privileged grants, and recent login telemetry."),
        "Estimated Monthly Savings": 0.0,
        "Generated SQL Fix": "\n".join([
            "-- Account access hygiene action. Review only; do not grant, revoke, disable, or alter users from this queue row.",
            f"-- User: {user_name}",
            f"-- Findings: {findings}",
            f"-- Queue readiness: {row.get('QUEUE_READINESS', 'Ready to Queue')}",
            f"-- Blockers: {row.get('QUEUE_BLOCKERS', 'None')}",
            "-- Use IAM/Snowflake review workflow before any access change.",
        ]),
        "Proof Query": verification_query,
        "Verification Query": verification_query,
        "Verification Status": "Pending",
        "Approver": approval_group,
        "Verification Status": "Requested" if severity.upper() in {"CRITICAL", "HIGH", "MEDIUM"} else "Not Required",
        "Verification Note": (
            f"Account-level user/auth hygiene review. Scope: {row.get('SCOPE_CONFIDENCE', 'Account-Level Control')}. "
            f"Scope basis: {row.get('SCOPE_EVIDENCE', '')}. Queue blockers: {row.get('QUEUE_BLOCKERS', '')}."
        ),
        "Recovery Evidence": (
            f"Telemetry basis: {row.get('PROOF_REQUIRED', 'user, IAM ticket, failed login context, MFA/admin-role telemetry')}. "
            f"Current findings: {findings}."
        ),
        "Recovery Audit State": "Access Hygiene Telemetry Pending",
        "Recovery SLA Target Hours": row.get("RECOVERY_SLA_TARGET_HOURS", _account_health_recovery_target_hours(severity)),
        "Company": company,
        "Environment": "No Database Context",
    }


def _queue_account_health_access_hygiene(
    session,
    hygiene: pd.DataFrame,
    company: str,
    days: int = 30,
) -> None:
    hygiene = _annotate_account_health_access_hygiene(hygiene)
    if hygiene is None or hygiene.empty:
        st.info("No Account Access Hygiene rows are loaded for queueing.")
        return
    severity = hygiene.get("SEVERITY", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
    actionable = hygiene[severity.isin({"CRITICAL", "HIGH", "MEDIUM"})].copy()
    if actionable.empty:
        st.info("No medium-or-higher Account Access Hygiene issues need queueing.")
        return
    actions = [
        _account_health_access_hygiene_action_payload(row, company=company, days=days)
        for _, row in actionable.head(50).iterrows()
    ]
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} Account Access Hygiene review(s) to the action queue.")
    except Exception as exc:
        st.error(f"Could not save Account Access Hygiene reviews: {format_snowflake_error(exc)}")
        st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")


def _render_account_health_access_hygiene(company: str, environment: str) -> None:
    with st.expander("Account Access Hygiene", expanded=False):
        st.caption(
            "Account-level user/auth posture is intentionally not database-filtered. "
            "Rows are labeled No Database Context so PROD/DEV selections do not imply false precision."
        )
        days = day_window_selectbox(
            "Access hygiene lookback",
            key="account_health_access_hygiene_days",
            default=30,
        )
        if st.button("Load Access Hygiene", key="account_health_access_hygiene_load"):
            action_session = _account_health_action_session("load Account Access Hygiene")
            if action_session is None:
                return
            try:
                sql = _account_health_access_hygiene_sql(
                    action_session,
                    days,
                    company=company,
                    environment=environment,
                )
                raw = run_query(
                    sql,
                    ttl_key=f"account_health_access_hygiene_{company}_{environment}_{days}",
                    tier="standard",
                    section="Account Health",
                )
                st.session_state["account_health_access_hygiene_sql"] = sql
                st.session_state["account_health_access_hygiene"] = _annotate_account_health_access_hygiene(raw)
                st.session_state["account_health_access_hygiene_meta"] = _account_health_scope_meta(
                    company,
                    environment,
                    window=f"{int(days)}d",
                    ignore_environment=True,
                    filter_keys=("global_user",),
                )
            except Exception as exc:
                st.session_state["account_health_access_hygiene"] = pd.DataFrame()
                st.warning(f"Account access hygiene unavailable: {format_snowflake_error(exc)}")

        hygiene = st.session_state.get("account_health_access_hygiene")
        if (
            hygiene is not None
            and not _account_health_meta_matches(
                st.session_state.get("account_health_access_hygiene_meta"),
                _account_health_scope_meta(
                    company,
                    environment,
                    window=f"{int(days)}d",
                    ignore_environment=True,
                    filter_keys=("global_user",),
                ),
            )
        ):
            st.info("Loaded access hygiene is stale for the active scope. Reload before queuing access work.")
            with st.expander("Access Hygiene Status", expanded=False):
                render_shell_snapshot((
                    ("Scope", "Stale"),
                    ("Refresh", "Required"),
                    ("Queue reviews", "After refresh"),
                    ("Execution", "Runbook only"),
                ))
        elif hygiene is not None and not hygiene.empty:
            high = int((hygiene.get("SEVERITY", pd.Series(dtype=str)).astype(str).str.upper() == "HIGH").sum())
            failed = int((pd.to_numeric(hygiene.get("FAILED_LOGINS", pd.Series(dtype=float)), errors="coerce").fillna(0) > 0).sum())
            admins = int((pd.to_numeric(hygiene.get("ADMIN_ROLE_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0) > 0).sum())
            render_shell_snapshot((
                ("Users Review", f"{len(hygiene):,}"),
                ("High Risk", f"{high:,}"),
                ("Failed Logins", f"{failed:,}"),
                ("Admin Reviews", f"{admins:,}"),
            ))
            render_priority_dataframe(
                hygiene,
                title="Account-level user/auth hygiene candidates",
                priority_columns=[
                    "SEVERITY", "USER_NAME", "POSTURE_FINDINGS", "FAILED_LOGINS",
                    "FAILED_IPS", "ADMIN_ROLE_COUNT", "ADMIN_ROLES", "MFA_SIGNAL",
                    "DAYS_SINCE_SEEN", "DATABASE_CONTEXT", "ENVIRONMENT_SCOPE",
                    "SCOPE_CONFIDENCE", "OWNER", "APPROVAL_GROUP", "QUEUE_READINESS",
                    "QUEUE_BLOCKERS", "NEXT_ACTION", "PROOF_REQUIRED",
                ],
                sort_by=["ACCESS_RISK_RANK", "FAILED_LOGINS", "ADMIN_ROLE_COUNT", "DAYS_SINCE_SEEN"],
                ascending=[True, False, False, False],
                raw_label="All account access hygiene rows",
                height=320,
            )
            actionable = hygiene[
                hygiene.get("SEVERITY", pd.Series(dtype=str)).fillna("").astype(str).str.upper().isin(
                    {"CRITICAL", "HIGH", "MEDIUM"}
                )
            ]
            b1, b2 = st.columns([1, 3])
            with b1:
                if st.button(
                    "Queue Access Hygiene Reviews",
                    key="account_health_queue_access_hygiene",
                    width="stretch",
                    disabled=actionable.empty,
                ):
                    action_session = _account_health_action_session("queue Account Access Hygiene reviews")
                    if action_session is not None:
                        _queue_account_health_access_hygiene(
                            action_session,
                            hygiene,
                            company=company,
                            days=days,
                        )
            with b2:
                route_ready = int((hygiene.get("QUEUE_READINESS", pd.Series(dtype=str)) == "Ready to Queue").sum())
                st.caption(
                    f"{len(actionable):,} medium-or-higher user/auth review(s) can be saved with read-only telemetry "
                    f"and No Database Context scope. {route_ready:,} loaded row(s) are route-ready."
                )
            with st.expander("Access Hygiene Status", expanded=False):
                render_shell_snapshot((
                    ("Telemetry", "Read-only"),
                    ("Status", "Required"),
                    ("Queue action", "Available"),
                    ("Execution", "Runbook only"),
                ))
        elif hygiene is not None:
            st.success("No account-level access hygiene candidates found for the selected lookback.")


def _render_account_health_source_health(company: str, environment: str) -> None:
    source_health = _account_health_source_health_rows(st.session_state, company, environment)
    if source_health.empty:
        return
    with st.expander("Account Health Data Health", expanded=False):
        current = int(source_health["STATE"].isin(["Loaded", "No Rows"]).sum())
        stale = int(source_health["STATE"].eq("Stale").sum())
        unavailable = int(source_health["STATE"].eq("Unavailable").sum())
        mart_backed = int(
            source_health[
                source_health["STATE"].isin(["Loaded", "No Rows"])
                & source_health["SOURCE"].astype(str).str.contains("mart|FACT_", case=False, regex=True)
            ].shape[0]
        )
        render_shell_snapshot((
            ("Current", f"{current}/{len(source_health)}"),
            ("Fast Summary", f"{mart_backed:,}"),
            ("Stale", f"{stale:,}"),
            ("Unavailable", f"{unavailable:,}"),
        ))
        st.caption(
            "Use this before publishing the morning report or queueing checklist work. "
            "Account-level controls stay visible under environment filters when Snowflake has no database context."
        )
        render_priority_dataframe(
            source_health,
            title="Account Health telemetry freshness",
            priority_columns=[
                "SURFACE", "STATE", "SOURCE", "CONFIDENCE", "ROWS", "SCOPE", "NEXT_ACTION",
            ],
            sort_by=["STATE_RANK", "SURFACE"],
            ascending=[True, True],
            raw_label="All Account Health data-health rows",
            height=320,
        )


def render():
    credit_price = get_credit_price()
    company      = st.session_state.get("active_company", "ALFA")
    environment  = get_active_environment()
    wh_filter_q = get_wh_filter_clause("q.warehouse_name", company)
    wh_filter_m = get_wh_filter_clause("warehouse_name", company)
    db_filter_q = get_db_filter_clause("q.database_name", company)
    user_filter_q = get_user_filter_clause("q.user_name", company)
    global_filter_q = get_global_filter_clause(
        "q.start_time", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name"
    )
    query_history_caps = None

    def _query_history_capabilities(action_session=None) -> dict:
        nonlocal query_history_caps
        if query_history_caps is None:
            if action_session is None:
                action_session = _account_health_action_session("load Account Health QUERY_HISTORY metadata")
            query_history_caps = _account_query_history_capabilities(action_session)
        return query_history_caps

    active_view = render_mode_selector(
        "Account Health view",
        "account_health_active_view",
        ACCOUNT_HEALTH_PANES,
        default=ACCOUNT_HEALTH_PANES[0],
        details=ACCOUNT_HEALTH_PANE_DETAILS,
        labels=ACCOUNT_HEALTH_PANE_LABELS,
        columns=2,
    )

    # -- OVERVIEW --------------------------------------------------------------
    if active_view == "Overview":
        render_operator_briefing(
            [
                ("First move", "Refresh the health snapshot and read the exception signals."),
                ("Telemetry", "Use cost drivers, failed work, warehouse pressure, and changes since yesterday."),
                ("Control", "Drill into the guarded workflow before recommending action."),
                ("Output", "Build the DBA morning brief from verified Control Room and Account Health facts."),
            ],
            columns=4,
        )
        exceptions_only = bool(st.session_state.get("exceptions_only_mode", False))
        if exceptions_only:
            st.info("Leadership exceptions-only mode is on. Heavy drilldowns stay collapsed until you ask for detail.")
        if _account_health_has_source_state(st.session_state):
            _render_account_health_source_health(company, environment)

        cache_age = 999
        filter_sig = "|".join([
            str(company),
            str(st.session_state.get("global_start_date", "")),
            str(st.session_state.get("global_end_date", "")),
            str(st.session_state.get("global_warehouse", "")),
            str(st.session_state.get("global_user", "")),
            str(st.session_state.get("global_role", "")),
            str(st.session_state.get("global_database", "")),
        ])
        last_ts = st.session_state.get("_health_ts")
        if last_ts:
            cache_age = (datetime.now() - datetime.fromisoformat(last_ts)).total_seconds()

        health_loaded = isinstance(st.session_state.get("health_data"), dict) and bool(st.session_state.get("health_data"))
        stale_scope = health_loaded and st.session_state.get("_health_filter_sig") != filter_sig
        auto_refresh_health = (
            (not health_loaded or stale_scope)
            and st.session_state.get("_account_health_auto_load_attempt_scope") != filter_sig
        )
        if auto_refresh_health:
            st.session_state["_account_health_auto_load_attempt_scope"] = filter_sig
        refresh_health = st.button("Load / Refresh Health", key="health_refresh") or auto_refresh_health
        if not refresh_health:
            if not health_loaded:
                st.info("Health snapshot is available on demand. Refresh when you need current Account Health telemetry.")
            elif stale_scope:
                st.warning("Loaded health snapshot is stale for the active filters. Refresh before acting.")
            elif cache_age > 300:
                st.caption(f"Loaded health snapshot is {cache_age / 60:.1f} minutes old. Refresh when current telemetry matters.")

        if refresh_health:
            action_session = _account_health_action_session("load Account Health")
            if action_session is None:
                return
            hd = {}
            mart_ok, mart_reason = _can_use_control_room_mart(company)
            control_mart = load_latest_control_room_mart(company) if mart_ok else None
            use_control_mart = bool(
                control_mart is not None
                and control_mart.available
                and control_mart.data is not None
                and not control_mart.data.empty
            )
            hd["_control_mart"] = control_mart.data if control_mart is not None else pd.DataFrame()
            hd["_control_mart_source"] = (
                mart_source_caption(control_mart)
                if control_mart is not None
                else f"Live fallback: {mart_reason}"
            )
            hd["_control_mart_used"] = use_control_mart
            live_df, live_source = _load_live_query_status(wh_filter_q, db_filter_q, user_filter_q)
            hd["live"] = live_df
            hd["_live_source"] = live_source
            if use_control_mart:
                query_plan = [
                    ("storage", build_mart_account_health_storage_sql(company)),
                    ("cost_drivers", build_mart_account_health_cost_drivers_sql(24, company)),
                    ("failed_jobs", build_mart_control_room_task_failures_sql(24, company)),
                    ("what_changed", build_mart_account_health_change_sql(24, company)),
                ]
                hd["_account_health_detail_source"] = "Fast summary"
            else:
                qh = _query_history_capabilities(action_session)
                cost_wh_size_expr = qh["cost_wh_size_expr"]
                cost_bytes_scanned_expr = qh["cost_bytes_scanned_expr"]
                failed_pred_q = qh["failed_pred_q"]
                queued_count_expr_q = qh["queued_count_expr_q"]
                query_plan = [
                    ("storage", f"""
                    SELECT COALESCE(
                        ROUND(SUM(COALESCE(average_database_bytes,0)+COALESCE(average_failsafe_bytes,0))/POWER(1024,4),2),
                        0
                    ) AS storage_tb
                    FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
                    WHERE usage_date = (SELECT MAX(usage_date)
                                        FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY)
                      {get_db_filter_clause("database_name", company)}
                """),
                ("cost_drivers", f"""
                    WITH {build_metered_credit_cte(hours_back=48, include_recent=True)}
                    SELECT q.user_name, q.warehouse_name, {cost_wh_size_expr} AS warehouse_size,
                           COUNT(*) AS query_count,
                           ROUND(SUM(COALESCE(pqc.metered_credits,0)), 4) AS total_credits,
                           ROUND({cost_bytes_scanned_expr}/POWER(1024,3), 2) AS gb_scanned
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                    WHERE q.start_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
                      AND q.warehouse_name IS NOT NULL
                      {global_filter_q}
                    GROUP BY q.user_name, q.warehouse_name
                    ORDER BY total_credits DESC
                    LIMIT 5
                """),
                ("failed_jobs", _task_failure_sql_or_empty(
                    action_session,
                    "scheduled_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())",
                        5,
                        company,
                    )),
                    ("what_changed", f"""
                    WITH today_q AS (
                        SELECT COUNT(*) AS q,
                               SUM(CASE WHEN {failed_pred_q} THEN 1 ELSE 0 END) AS fails
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        WHERE q.start_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
                          {wh_filter_q} {db_filter_q} {user_filter_q}
                    ),
                    yday_q AS (
                        SELECT COUNT(*) AS q,
                               SUM(CASE WHEN {failed_pred_q} THEN 1 ELSE 0 END) AS fails
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        WHERE q.start_time >= DATEADD('hours', -48, CURRENT_TIMESTAMP())
                          AND q.start_time <  DATEADD('hours', -24, CURRENT_TIMESTAMP())
                          {wh_filter_q} {db_filter_q} {user_filter_q}
                    ),
                    today_c AS (
                        SELECT SUM(credits_used) AS credits
                        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                        WHERE start_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
                          {wh_filter_m}
                    ),
                    yday_c AS (
                        SELECT SUM(credits_used) AS credits
                        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                        WHERE start_time >= DATEADD('hours', -48, CURRENT_TIMESTAMP())
                          AND start_time < DATEADD('hours', -24, CURRENT_TIMESTAMP())
                          {wh_filter_m}
                    )
                    SELECT today_q.q - yday_q.q AS query_delta,
                           ROUND(COALESCE(today_c.credits, 0) - COALESCE(yday_c.credits, 0), 4) AS credit_delta,
                           today_q.fails - yday_q.fails AS failure_delta
                    FROM today_q, yday_q, today_c, yday_c
                    """),
                ]
                hd["_account_health_detail_source"] = "Live fallback: ACCOUNT_USAGE"
            if not use_control_mart:
                query_plan = [
                ("burn", f"""
                    SELECT SUM(CASE WHEN start_time >= DATEADD('hours',-24,CURRENT_TIMESTAMP())
                               THEN credits_used ELSE 0 END) AS last_24h,
                           SUM(CASE WHEN start_time >= DATEADD('hours',-48,CURRENT_TIMESTAMP())
                                    AND  start_time <  DATEADD('hours',-24,CURRENT_TIMESTAMP())
                               THEN credits_used ELSE 0 END) AS prior_24h
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                    WHERE start_time >= DATEADD('hours',-48,CURRENT_TIMESTAMP())
                      {wh_filter_m}
                """),
                ("errors", f"""
                    SELECT COUNT(*) AS err_count
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    WHERE q.start_time >= DATEADD('hours',-24,CURRENT_TIMESTAMP())
                      AND {failed_pred_q}
                      {wh_filter_q} {db_filter_q} {user_filter_q}
                """),
                ("query_stats", f"""
                    SELECT COUNT(*) AS total_queries,
                           SUM(CASE WHEN {failed_pred_q} THEN 1 ELSE 0 END) AS failed_queries,
                           {queued_count_expr_q} AS queued_queries,
                           ROUND(AVG(total_elapsed_time) / 1000, 2) AS avg_elapsed_sec
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    WHERE q.start_time >= DATEADD('hours',-24,CURRENT_TIMESTAMP())
                      AND q.warehouse_name IS NOT NULL
                      {wh_filter_q} {db_filter_q} {user_filter_q}
                """),
                ("warehouse_pressure", f"""
                    WITH wh AS (
                        SELECT q.warehouse_name,
                               COUNT(*) AS total_queries,
                               SUM(CASE WHEN {failed_pred_q} THEN 1 ELSE 0 END) AS failed_queries,
                               {queued_count_expr_q} AS queued_queries
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        WHERE q.start_time >= DATEADD('hours',-24,CURRENT_TIMESTAMP())
                          AND q.warehouse_name IS NOT NULL
                          {wh_filter_q} {db_filter_q} {user_filter_q}
                        GROUP BY q.warehouse_name
                    )
                    SELECT COUNT(*) AS active_warehouses,
                           SUM(IFF(failed_queries > 0 OR queued_queries > 0, 1, 0)) AS pressure_warehouses
                    FROM wh
                """),
                ("task_health", _task_health_sql_or_empty(
                    action_session,
                    "scheduled_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())",
                    company,
                )),
                ] + query_plan
            for key, sql in query_plan:
                hd[key] = run_query(
                    sql,
                    ttl_key=f"account_health_live_{company}_{key}",
                    tier="recent",
                    section="Account Health",
                )

            st.session_state["health_data"] = hd
            st.session_state["_health_ts"]  = datetime.now().isoformat()
            st.session_state["_health_filter_sig"] = filter_sig
            st.session_state["account_health_overview_meta"] = _account_health_scope_meta(
                company, environment, window="24h"
            )
            st.session_state["account_health_live_status_meta"] = _account_health_scope_meta(
                company, environment, window="1h"
            )
            mark_loaded("account_health")

        hd = st.session_state.get("health_data", {})
        if not isinstance(hd, dict) or not hd:
            return

        live_df    = hd.get("live",    pd.DataFrame())
        live_source = hd.get("_live_source", "ACCOUNT_USAGE")
        burn_df    = hd.get("burn",    pd.DataFrame())
        err_df     = hd.get("errors",  pd.DataFrame())
        storage_df = hd.get("storage", pd.DataFrame())
        query_stats_df = hd.get("query_stats", pd.DataFrame())
        task_health_df = hd.get("task_health", pd.DataFrame())
        warehouse_pressure_df = hd.get("warehouse_pressure", pd.DataFrame())
        control_mart_df = hd.get("_control_mart", pd.DataFrame())
        control_mart_used = bool(hd.get("_control_mart_used", False)) and not control_mart_df.empty
        control_mart_row = control_mart_df.iloc[0] if control_mart_used else {}
        live_val  = safe_int(live_df["ACTIVE_COUNT"].iloc[0]) if not live_df.empty else 0
        queued    = safe_int(live_df["QUEUED_COUNT"].iloc[0]) if not live_df.empty else 0
        stor_tb   = safe_float(storage_df["STORAGE_TB"].iloc[0]) if not storage_df.empty else 0
        if control_mart_used:
            last24 = safe_float(control_mart_row.get("CREDITS_24H", 0))
            cost24 = safe_float(control_mart_row.get("COST_24H_USD", credits_to_dollars(last24, credit_price)))
            err_count = safe_int(control_mart_row.get("FAILED_QUERIES_24H", 0))
            failed_tasks = safe_int(control_mart_row.get("FAILED_TASKS_24H", 0))
            object_changes = safe_int(control_mart_row.get("OBJECT_CHANGES_24H", 0))
            queued_ms = safe_float(control_mart_row.get("QUEUED_MS_24H", 0))
            pct_delta = 0
            health_score = safe_float(control_mart_row.get("HEALTH_SCORE", 0))
            score_label = _mart_health_label(health_score)
            health_components = pd.DataFrame([
                {"Component": "Failed queries", "Observed": err_count, "Source": "Fast summary"},
                {"Component": "Failed tasks", "Observed": failed_tasks, "Source": "Fast summary"},
                {"Component": "Queued minutes", "Observed": round(queued_ms / 60000, 2), "Source": "Fast summary"},
                {"Component": "Security events", "Observed": safe_int(control_mart_row.get("SECURITY_EVENTS_24H", 0)), "Source": "Fast summary"},
                {"Component": "Object changes", "Observed": safe_int(control_mart_row.get("OBJECT_CHANGES_24H", 0)), "Source": "Fast summary"},
                {"Component": "Top risk", "Observed": control_mart_row.get("TOP_RISK", ""), "Source": "Fast summary"},
            ])
        else:
            last24 = safe_float(burn_df["LAST_24H"].iloc[0]) if not burn_df.empty else 0
            prior24 = safe_float(burn_df["PRIOR_24H"].iloc[0]) if not burn_df.empty else 0
            cost24 = credits_to_dollars(last24, credit_price)
            err_count = safe_int(err_df["ERR_COUNT"].iloc[0]) if not err_df.empty else 0
            failed_tasks = safe_int(task_health_df["FAILED_TASKS"].iloc[0]) if not task_health_df.empty else 0
            object_changes = 0
            pct_delta = ((last24 - prior24) / prior24 * 100) if prior24 > 0 else 0
            health = executive_health_score({
                "total_queries": safe_float(query_stats_df["TOTAL_QUERIES"].iloc[0]) if not query_stats_df.empty else 0,
                "failed_queries": err_count,
                "queued_queries": safe_float(query_stats_df["QUEUED_QUERIES"].iloc[0]) if not query_stats_df.empty else queued,
                "avg_elapsed_sec": safe_float(query_stats_df["AVG_ELAPSED_SEC"].iloc[0]) if not query_stats_df.empty else 0,
                "task_runs": safe_float(task_health_df["TASK_RUNS"].iloc[0]) if not task_health_df.empty else 0,
                "failed_tasks": safe_float(task_health_df["FAILED_TASKS"].iloc[0]) if not task_health_df.empty else 0,
                "active_warehouses": safe_float(warehouse_pressure_df["ACTIVE_WAREHOUSES"].iloc[0]) if not warehouse_pressure_df.empty else 0,
                "pressure_warehouses": safe_float(warehouse_pressure_df["PRESSURE_WAREHOUSES"].iloc[0]) if not warehouse_pressure_df.empty else 0,
                "current_credits": last24,
                "prior_credits": prior24,
                "current_storage_tb": stor_tb,
                "prior_storage_tb": stor_tb,
            })
            health_score = health["score"]
            score_label = health["label"]
            health_components = pd.DataFrame(health["components"])

        checklist = _build_account_health_dba_checklist(
            health_score=health_score,
            score_label=score_label,
            err_count=err_count,
            queued=queued,
            pct_delta=pct_delta,
            last24=last24,
            stor_tb=stor_tb,
            failed_tasks=failed_tasks,
            object_changes=object_changes,
            control_mart_used=control_mart_used,
            detail_source=hd.get("_account_health_detail_source", ""),
        )
        checklist = _annotate_account_health_checklist_readiness(
            checklist,
            environment=get_active_environment(),
        )
        _render_account_health_action_brief(checklist)
        _render_account_health_operating_snapshot(
            health_score=health_score,
            score_label=score_label,
            live_val=live_val,
            queued=queued,
            err_count=err_count,
            last24=last24,
            pct_delta=pct_delta,
            cost24=cost24,
            stor_tb=stor_tb,
            failed_tasks=failed_tasks,
            hd=hd,
            live_source=live_source,
            control_mart_used=control_mart_used,
            control_mart_row=control_mart_row,
        )
        if st.button("Load Control Summary", key="account_health_load_operability_fact"):
            try:
                operability_sql = _account_health_operability_fact_sql(30, company, get_active_environment())
                st.session_state["account_health_operability_fact_sql"] = operability_sql
                st.session_state["account_health_operability_fact"] = run_query(
                    operability_sql,
                    ttl_key=f"account_health_operability_fact_{company}_{get_active_environment()}_30",
                    tier="standard",
                    section="Account Health",
                )
                st.session_state["account_health_operability_fact_meta"] = _account_health_scope_meta(
                    company, environment, window="30d"
                )
                st.session_state.pop("account_health_operability_fact_error", None)
            except Exception as fact_exc:
                st.session_state["account_health_operability_fact"] = pd.DataFrame()
                st.session_state["account_health_operability_fact_error"] = format_snowflake_error(fact_exc)
        operability_fact = st.session_state.get("account_health_operability_fact")
        account_control_board = _account_health_control_board(
            checklist,
            closure=st.session_state.get("account_health_closure_analytics"),
            access_hygiene=st.session_state.get("account_health_access_hygiene"),
            trend=st.session_state.get("account_health_checklist_trend"),
            environment=get_active_environment(),
        )
        operability_gate_fact = operability_fact if (
            operability_fact is not None
            and not operability_fact.empty
            and _account_health_meta_matches(
                st.session_state.get("account_health_operability_fact_meta"),
                _account_health_scope_meta(company, environment, window="30d"),
            )
        ) else pd.DataFrame()
        account_operator_gates = _account_health_operator_next_moves(
            health_score=health_score,
            checklist=checklist,
            control_board=account_control_board,
            closure=st.session_state.get("account_health_closure_analytics"),
            access_hygiene=st.session_state.get("account_health_access_hygiene"),
            operability_fact=operability_gate_fact,
            source_health=_account_health_source_health_rows(st.session_state, company, environment),
        )
        account_intervention_matrix = _account_health_intervention_matrix(
            checklist=checklist,
            control_board=account_control_board,
            closure=st.session_state.get("account_health_closure_analytics"),
            access_hygiene=st.session_state.get("account_health_access_hygiene"),
            operability_fact=operability_gate_fact,
        )
        account_morning_exceptions = _account_health_morning_exception_rows(
            checklist=checklist,
            gates=account_operator_gates,
            interventions=account_intervention_matrix,
            control_board=account_control_board,
            health_score=health_score,
            err_count=err_count,
            queued=queued,
            pct_delta=pct_delta,
            failed_tasks=failed_tasks,
        )
        st.session_state["account_health_checklist"] = checklist
        st.session_state["account_health_operator_gates"] = account_operator_gates
        st.session_state["account_health_control_board"] = account_control_board
        st.session_state["account_health_intervention_matrix"] = account_intervention_matrix
        st.session_state["account_health_morning_exceptions"] = account_morning_exceptions
        _render_account_health_exception_strip(account_morning_exceptions)
        account_detail = st.selectbox(
            "Account Health detail",
            ("Checklist", "Gates", "Interventions", "Controls", "Operability"),
            label_visibility="collapsed",
            key="account_health_overview_detail",
        )
        if account_detail == "Checklist":
            actionable_checklist = _account_health_actionable_checklist(checklist)
            show_full_checklist = st.toggle(
                "Show full checklist",
                key="account_health_show_full_checklist",
                value=False,
                help="Default keeps morning triage focused on checklist rows that need DBA action.",
            )
            checklist_view, checklist_title, checklist_raw_label = _account_health_visible_checklist(
                checklist,
                show_full=show_full_checklist,
            )
            if checklist_view.empty and not show_full_checklist:
                st.success("No Account Health checklist exceptions for this loaded snapshot.")
            else:
                render_priority_dataframe(
                    checklist_view,
                    title=checklist_title,
                    priority_columns=[
                        "SEVERITY", "STATUS", "CHECK", "EVIDENCE", "OWNER",
                        "ESCALATION_TARGET", "ROUTE", "ENVIRONMENT_SCOPE",
                        "DATABASE_CONTEXT", "SCOPE_CONFIDENCE", "QUEUE_READINESS",
                        "QUEUE_BLOCKERS", "APPROVAL_REQUIRED", "RECOVERY_SLA_TARGET_HOURS",
                        "NEXT_ACTION", "PROOF_REQUIRED",
                    ],
                    sort_by=["SEVERITY", "CHECK"],
                    ascending=[True, True],
                    raw_label=checklist_raw_label,
                    height=300,
                    max_rows=12,
                )
        elif account_detail == "Gates":
            render_priority_dataframe(
                account_operator_gates,
                title="Account Health operator next-move gates",
                priority_columns=["GATE", "STATE", "COUNT", "PROOF_REQUIRED", "NEXT_ACTION"],
                sort_by=["GATE_RANK", "COUNT"],
                ascending=[True, False],
                raw_label="All Account Health operator gates",
                height=240,
                max_rows=5,
            )
        elif account_detail == "Interventions" and not account_intervention_matrix.empty:
            render_priority_dataframe(
                account_intervention_matrix,
                title="Account Health DBA intervention matrix",
                priority_columns=[
                    "DBA_PRIORITY", "INTERVENTION_STATE", "SURFACE", "SEVERITY", "ROUTE", "OWNER",
                    "CONTROL_STATE", "QUEUE_READINESS", "CLOSURE_READINESS",
                    "SCOPE_CONFIDENCE", "COUNT", "NEXT_DECISION", "PROOF_REQUIRED",
                ],
                sort_by=["DBA_PRIORITY", "COUNT", "SURFACE"],
                ascending=[True, False, True],
                raw_label="All Account Health DBA intervention rows",
                height=280,
                max_rows=8,
            )
        elif account_detail == "Controls" and not account_control_board.empty:
            render_priority_dataframe(
                account_control_board,
                title="Account Health control board",
                priority_columns=[
                    "CONTROL_STATE", "CHECK_NAME", "STATUS", "SEVERITY", "ROUTE",
                    "OWNER", "ENVIRONMENT_SCOPE", "DATABASE_CONTEXT", "SCOPE_CONFIDENCE",
                    "QUEUE_READINESS", "QUEUE_BLOCKERS", "OPEN_ACTIONS", "OVERDUE_OPEN",
                    "FIXED_WITHOUT_VERIFICATION", "RECOVERY_RISK_ROWS", "VERIFIED_CLOSURES",
                    "ISSUE_SNAPSHOTS", "RECOVERY_SLA_TARGET_HOURS", "NEXT_CONTROL_ACTION",
                ],
                sort_by=["CONTROL_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "OPEN_ACTIONS"],
                ascending=[True, False, False, False],
                raw_label="All Account Health control rows",
                height=320,
                max_rows=12,
            )
        elif account_detail == "Operability":
            if (
                operability_fact is not None
                and not _account_health_meta_matches(
                    st.session_state.get("account_health_operability_fact_meta"),
                    _account_health_scope_meta(company, environment, window="30d"),
                )
            ):
                st.info("Loaded Account Health control summary is stale for the active scope. Reload before acting.")
            elif operability_fact is not None and not operability_fact.empty:
                blocked_states = operability_fact["CONTROL_STATE"].astype(str).str.contains(
                    "Blocked|Overdue|Required|Review", case=False, na=False
                )
                render_shell_snapshot((
                    ("Rows", f"{len(operability_fact):,}"),
                    ("Blocked Review", f"{int(blocked_states.sum()):,}"),
                    ("Overdue", f"{int(operability_fact.get('OVERDUE_OPEN', pd.Series(dtype=int)).sum()):,}"),
                    ("Verified", f"{int(operability_fact.get('VERIFIED_CLOSURES', pd.Series(dtype=int)).sum()):,}"),
                ))
                render_priority_dataframe(
                    operability_fact,
                    title="Account Health blockers",
                    priority_columns=[
                        "SNAPSHOT_DATE", "CONTROL_STATE", "CONTROL_SOURCE", "CHECK_NAME",
                        "ROUTE", "SEVERITY", "ENVIRONMENT", "HEALTH_SCORE", "ISSUE_ROWS",
                        "ROUTE_BLOCKER_ROWS", "QUEUE_REQUIRED_ROWS", "ACCESS_HYGIENE_ROWS",
                        "FAILED_LOGIN_ROWS", "PRIVILEGED_GRANT_ROWS", "OPEN_ACTIONS",
                        "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "VERIFIED_CLOSURES",
                        "OWNER_APPROVAL_GAP_ROWS", "RECOVERY_RISK_ROWS", "NEXT_CONTROL_ACTION",
                    ],
                    sort_by=["CONTROL_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "ISSUE_ROWS"],
                    ascending=[True, False, False, False],
                    raw_label="All Account Health control rows",
                    height=320,
                    max_rows=12,
                )
                with st.expander("Account Health Control Status", expanded=False):
                    render_shell_snapshot((
                        ("Control summary", "Ready"),
                        ("Routed actions", "Review"),
                        ("Telemetry", "Required"),
                        ("Execution", "Runbook only"),
                    ))
            elif st.session_state.get("account_health_operability_fact_error"):
                st.caption("Account Health control summary is not available yet. Ask the DBA on-call to enable the fast blocker surface.")
            else:
                st.caption("Load the control summary when you need blockers, routes, and telemetry status.")
        elif account_detail in {"Interventions", "Controls"}:
            st.success(f"No {account_detail.lower()} rows for the loaded scope.")
        if account_detail == "Checklist":
            q1, q2, q3 = st.columns([1, 1, 3])
            with q1:
                if st.button(
                    "Queue Checklist Issues",
                    key="account_health_queue_checklist",
                    width="stretch",
                    disabled=actionable_checklist.empty,
                ):
                    action_session = _account_health_action_session("queue Account Health checklist issues")
                    if action_session is not None:
                        _queue_account_health_checklist(
                            action_session,
                            checklist,
                            company=company,
                            environment=get_active_environment(),
                        )
            with q2:
                if st.button(
                    "Save Checklist Snapshot",
                    key="account_health_save_checklist_snapshot",
                    width="stretch",
                ):
                    action_session = _account_health_action_session("save Account Health checklist snapshot")
                    if action_session is not None:
                        _save_account_health_checklist_snapshot(
                            action_session,
                            checklist,
                            company=company,
                            environment=get_active_environment(),
                            health_score=health_score,
                            detail_source=hd.get("_account_health_detail_source", ""),
                        )
            with q3:
                if actionable_checklist.empty:
                    st.caption("Daily checklist is clean for this snapshot; no queue item is needed. Save the snapshot for trend tracking.")
                else:
                    ready_count = int((actionable_checklist.get("QUEUE_READINESS", pd.Series(dtype=str)) == "Ready to Queue").sum())
                    st.caption(
                        f"{len(actionable_checklist):,} checklist issue(s) will be saved with route, reviewer, "
                        f"telemetry basis, and scope context. {ready_count:,} are route-ready without blockers."
                    )
        _render_account_health_access_hygiene(
            company=company,
            environment=get_active_environment(),
        )
        with st.expander("Daily DBA Checklist Trend", expanded=False):
            trend_days = day_window_selectbox(
                "Checklist trend window",
                key="account_health_checklist_trend_days",
                default=30,
            )
            if st.button("Load Checklist Trend", key="account_health_load_checklist_trend"):
                try:
                    trend_sql = _account_health_checklist_history_sql(
                        trend_days,
                        company=company,
                        environment=get_active_environment(),
                    )
                    st.session_state["account_health_checklist_trend"] = run_query(
                        trend_sql,
                        ttl_key=f"account_health_checklist_trend_{company}_{get_active_environment()}_{trend_days}",
                        tier="standard",
                        section="Account Health",
                    )
                    st.session_state["account_health_checklist_trend_sql"] = trend_sql
                    st.session_state["account_health_checklist_trend_meta"] = _account_health_scope_meta(
                        company, environment, window=f"{int(trend_days)}d"
                    )
                except Exception as exc:
                    st.warning(f"Checklist trend unavailable: {format_snowflake_error(exc)}")
            trend = st.session_state.get("account_health_checklist_trend")
            if (
                trend is not None
                and not _account_health_meta_matches(
                    st.session_state.get("account_health_checklist_trend_meta"),
                    _account_health_scope_meta(company, environment, window=f"{int(trend_days)}d"),
                )
            ):
                st.info("Loaded checklist trend is stale for the active scope. Reload before acting.")
            elif trend is not None and not trend.empty:
                render_priority_dataframe(
                    trend,
                    title="Checklist issues by recurring snapshot",
                    priority_columns=[
                        "CHECK_NAME", "ISSUE_SNAPSHOTS", "SNAPSHOT_ROWS", "LAST_STATUS",
                        "LAST_SEVERITY", "OWNER", "ESCALATION_TARGET", "ROUTE", "AVG_HEALTH_SCORE",
                        "QUEUE_READINESS", "QUEUE_BLOCKERS", "SCOPE_CONFIDENCE",
                        "CONTROL_READINESS", "CONTROL_BLOCKER_SNAPSHOTS", "NEXT_CONTROL_ACTION",
                    ],
                    sort_by=["ISSUE_SNAPSHOTS", "LAST_SNAPSHOT_TS"],
                    ascending=[False, False],
                    raw_label="All checklist trend rows",
                    height=260,
                )
            elif trend is not None:
                st.info("No checklist history rows found for the selected scope.")
        with st.expander("Daily DBA Closure Analytics", expanded=False):
            st.caption(
                "Uses Account Health action-queue rows to show whether checklist issues are still open, "
                "overdue, or waiting for telemetry to confirm closure."
            )
            closure_days = day_window_selectbox(
                "Closure analytics window",
                key="account_health_closure_days",
                default=30,
            )
            if st.button("Load Closure Analytics", key="account_health_load_closure_analytics"):
                try:
                    closure_sql = _account_health_closure_analytics_sql(
                        closure_days,
                        company=company,
                        environment=get_active_environment(),
                    )
                    st.session_state["account_health_closure_analytics_sql"] = closure_sql
                    st.session_state["account_health_closure_analytics"] = run_query(
                        closure_sql,
                        ttl_key=f"account_health_closure_analytics_{company}_{get_active_environment()}_{closure_days}",
                        tier="standard",
                        section="Account Health",
                    )
                    st.session_state["account_health_closure_analytics_meta"] = _account_health_scope_meta(
                        company, environment, window=f"{int(closure_days)}d"
                    )
                except Exception as exc:
                    st.session_state["account_health_closure_analytics"] = pd.DataFrame()
                    st.warning(f"Closure analytics unavailable: {format_snowflake_error(exc)}")
                    st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry.")
            closure = st.session_state.get("account_health_closure_analytics")
            if (
                closure is not None
                and not _account_health_meta_matches(
                    st.session_state.get("account_health_closure_analytics_meta"),
                    _account_health_scope_meta(company, environment, window=f"{int(closure_days)}d"),
                )
            ):
                st.info("Loaded closure analytics are stale for the active scope. Reload before acting.")
            elif closure is not None and not closure.empty:
                render_priority_dataframe(
                    closure,
                    title="Checklist closure status gaps",
                    priority_columns=[
                        "CHECK_NAME", "CLOSURE_READINESS", "OWNER", "APPROVER",
                        "TOTAL_ACTIONS", "OPEN_ACTIONS", "OVERDUE_OPEN",
                        "VERIFIED_CLOSURES", "FIXED_WITHOUT_VERIFICATION",
                        "OWNER_GAP_ROWS", "TICKET_GAP_ROWS", "APPROVER_GAP_ROWS",
                        "OWNER_APPROVAL_GAP_ROWS", "VERIFICATION_QUERY_GAP_ROWS",
                        "RECOVERY_RISK_ROWS", "NEXT_DUE_DATE", "LAST_STATUS", "NEXT_ACTION",
                    ],
                    sort_by=["CLOSURE_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "OPEN_ACTIONS"],
                    ascending=[True, False, False, False],
                    raw_label="All closure analytics rows",
                    height=300,
                )
                with st.expander("Closure Analytics Status", expanded=False):
                    render_shell_snapshot((
                        ("Closure status", "Ready"),
                        ("Telemetry", "Review"),
                        ("Telemetry", "Required"),
                        ("Execution", "Runbook only"),
                    ))
            elif closure is not None:
                st.info("No Account Health checklist action-queue rows found for the selected scope.")
        st.divider()
        show_loaded_time("account_health")

        st.markdown("**Quick Nav**")
        qnav_cols = st.columns(4)

        def _jump(tgt, workflow=None):
            apply_navigation_state(tgt)
            if workflow:
                st.session_state["workload_operations_workflow"] = workflow

        for idx, (lbl, tgt, workflow) in enumerate([
            ("Live", "Workload Operations", "Live triage"),
            ("Query", "Workload Operations", "Query diagnosis"),
            ("Cost", "Cost & Contract", None),
            ("DBA", "Security Monitoring", None),
        ]):
            with qnav_cols[idx]:
                st.button(lbl, key=f"jump_{lbl}", on_click=_jump, args=(tgt, workflow), width="stretch")

        secondary_sig = f"{filter_sig}|{environment}"
        secondary_loaded = st.session_state.get("_account_health_secondary_sig") == secondary_sig
        if st.button("Load Secondary Details", key="account_health_load_secondary_evidence"):
            st.session_state["_account_health_secondary_sig"] = secondary_sig
            secondary_loaded = True
        if not secondary_loaded:
            st.caption(
                "Secondary cost slices, monitoring-cost detail, and warehouse-pressure charts stay unloaded "
                "until they are needed for the current investigation."
            )
            return

        st.divider()
        st.markdown("**Executive Landing Signals**")
        e1, e2, e3, e4 = st.columns(4)

        with e1:
            st.markdown("**Top 5 cost drivers today**")
            cost_df = hd.get("cost_drivers", pd.DataFrame())
            if cost_df is not None and not cost_df.empty:
                cost_df["EST_COST"] = cost_df["TOTAL_CREDITS"].apply(
                    lambda x: credits_to_dollars(x, credit_price)
                )
                render_priority_dataframe(
                    cost_df,
                    title="Top cost drivers today",
                    priority_columns=[
                        "WAREHOUSE_NAME", "USER_NAME", "TOTAL_CREDITS",
                        "EST_COST", "QUERY_COUNT", "AVG_ELAPSED_SEC",
                    ],
                    sort_by=["TOTAL_CREDITS", "EST_COST"],
                    ascending=[False, False],
                    raw_label="All daily cost drivers",
                    height=220,
                )
                if "USER_NAME" in cost_df.columns:
                    sel_user = st.selectbox(
                        "-> Drill into user", ["(none)"] + cost_df["USER_NAME"].dropna().tolist(),
                        key="ah_drill_user", label_visibility="collapsed",
                    )
                    if sel_user and sel_user != "(none)":
                        if st.button(f"Open Cost & Contract for {sel_user}", key="ah_drill_user_btn"):
                            _drill_to(
                                "Cost & Contract",
                                user_filter=sel_user,
                                workflow_key="cost_contract_workflow",
                                workflow="Usage attribution and run-rate",
                            )
            else:
                st.info("No cost driver data yet.")

        with e2:
            st.markdown("**Top 5 failed jobs/tasks**")
            failed_df = hd.get("failed_jobs", pd.DataFrame())
            if failed_df is not None and not failed_df.empty:
                render_priority_dataframe(
                    failed_df,
                    title="Failed jobs and tasks",
                    priority_columns=[
                        "NAME", "TASK_NAME", "ROOT_TASK_NAME", "STATE",
                        "QUERY_ID", "ERROR_MESSAGE", "SCHEDULED_TIME",
                    ],
                    sort_by=["SCHEDULED_TIME", "COMPLETED_TIME"],
                    ascending=[False, False],
                    raw_label="All failed jobs/tasks",
                    height=220,
                )
                if st.button("Task Management", key="ah_drill_tasks"):
                    st.session_state["workload_operations_workflow"] = "Task graphs"
                    _drill_to("Workload Operations")
            else:
                st.success("No failed tasks in the last 24h.")

        with e3:
            st.markdown("**What changed since yesterday**")
            change_df = hd.get("what_changed", pd.DataFrame())
            if change_df is not None and not change_df.empty:
                row = change_df.iloc[0]
                render_shell_snapshot(
                    (
                        ("Queries", f"{safe_int(row.get('QUERY_DELTA', 0)):+,}"),
                        ("Credits", f"{safe_float(row.get('CREDIT_DELTA', 0)):+,.2f}"),
                        ("Failures", f"{safe_int(row.get('FAILURE_DELTA', 0)):+,}"),
                    )
                )
            else:
                st.info("Change summary unavailable.")

        with e4:
            st.markdown("**Recommended next action**")
            st.info("Use Cost & Contract for optimization actions, action queue triage, and Teams-ready alerting.")
            if st.button("Open Cost & Contract", key="ah_open_recommendations"):
                _drill_to(
                    "Cost & Contract",
                    workflow_key="cost_contract_workflow",
                    workflow="Recommendations and action queue",
                )

        if exceptions_only:
            st.caption("Landing default stops here to avoid loading lower-priority drilldowns.")
            return

        st.divider()
        st.markdown("**Warehouse Pressure (last 1h)**")
        try:
            if control_mart_used:
                df_wp = run_query(
                    build_mart_control_room_warehouse_pressure_sql(1, company),
                    ttl_key=f"account_health_wh_pressure_mart_{company}",
                    tier="historical",
                    section="Account Health",
                )
                if df_wp is not None and not df_wp.empty:
                    df_wp = df_wp.rename(columns={
                        "TOTAL_QUERIES": "QUERIES",
                        "QUEUED_QUERIES": "QUEUED",
                    })
            else:
                qh = _query_history_capabilities()
                pressure_wh_size_expr = qh["pressure_wh_size_expr"]
                queued_count_expr_plain = qh["queued_count_expr_plain"]
                df_wp = run_query(f"""
                    SELECT warehouse_name, {pressure_wh_size_expr} AS warehouse_size, COUNT(*) AS queries,
                           {queued_count_expr_plain} AS queued
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('hours',-1,CURRENT_TIMESTAMP())
                      AND warehouse_name IS NOT NULL
                      {wh_filter_m}
                    GROUP BY warehouse_name ORDER BY queries DESC LIMIT 8
                """, ttl_key=f"account_health_wh_pressure_live_{company}", tier="recent", section="Account Health")
            if not df_wp.empty:
                top_wh = df_wp.sort_values(["QUEUED","QUERIES"], ascending=False).iloc[0]
                render_shell_snapshot(
                    (
                        ("Top pressure", top_wh["WAREHOUSE_NAME"]),
                        ("Queue / queries", f"{int(top_wh['QUEUED'])} queued / {int(top_wh['QUERIES'])} queries"),
                    )
                )
                render_drillable_bar_chart(
                    df_wp, dimension="WAREHOUSE_NAME", measure="QUERIES",
                    key="ah_warehouse_pressure", title="Warehouse pressure drill-down",
                    drilldown_column="warehouse_name", lookback_hours=24, top_n=8,
                )
                st.markdown("**Jump to Cost & Contract:**")
                wh_cols = st.columns(min(len(df_wp), 4))
                for idx, wh_row in df_wp.head(4).iterrows():
                    wh_name = wh_row["WAREHOUSE_NAME"]
                    with wh_cols[idx % 4]:
                        if st.button(wh_name, key=f"ah_wh_drill_{wh_name}"):
                            _drill_to("Cost & Contract", wh_filter=wh_name)
        except Exception as e:
            st.caption(f"Warehouse pressure unavailable: {format_snowflake_error(e)}")

    # -- MORNING REPORT --------------------------------------------------------
    elif active_view == "Morning Report":
        st.subheader("DBA Morning Brief")
        st.caption(
            "Telemetry-ranked DBA packet built from Control Room blockers, data readiness, handoff rows, "
            "deployment gates, and action-queue closure status."
        )

        brief_cols = st.columns([1, 1, 2])
        with brief_cols[0]:
            morning_lookback = st.selectbox(
                "Brief window",
                [12, 24, 48, 168],
                index=1,
                key="account_health_morning_lookback",
                format_func=lambda h: f"{h} hours",
            )
        with brief_cols[1]:
            allow_brief_live_fallback = st.toggle(
                "Bounded live fallback",
                key="account_health_morning_live_fallback",
                value=False,
                help=(
                    "Use limited 24-hour ACCOUNT_USAGE checks when the fast summary is incomplete. "
                    "Leave off for the cheapest morning packet."
                ),
            )
        with brief_cols[2]:
            render_shell_snapshot((("Scope", f"{company} / {environment}"),))

        if st.button("Refresh DBA Morning Brief", key="morning_gen", type="primary"):
            action_session = _account_health_action_session("refresh DBA Morning Brief")
            if action_session is None:
                return
            with render_load_status("Refreshing DBA Morning Brief", "DBA Morning Brief ready"):
                cortex_budget_usd = float(
                    st.session_state.get(
                        "dba_control_room_cortex_budget_usd",
                        st.session_state.get("cortex_control_budget_usd", 5000.0),
                    )
                )
                packet = _build_account_health_dba_morning_brief(
                    action_session,
                    company=company,
                    environment=environment,
                    credit_price=credit_price,
                    lookback_hours=int(morning_lookback),
                    cortex_budget_usd=safe_float(cortex_budget_usd),
                    allow_live_fallback=bool(allow_brief_live_fallback),
                )
                packet["_source"] = (
                    "DBA Control Room fast summary + bounded live fallback"
                    if allow_brief_live_fallback
                    else "DBA Control Room fast summary"
                )
                st.session_state["morning_data"] = packet
                st.session_state["morning_data_source"] = packet["_source"]
                st.session_state["morning_data_meta"] = _account_health_scope_meta(
                    company, environment, window=f"{int(morning_lookback)}h"
                )
                st.session_state["dba_control_room_morning_brief"] = packet["brief"]
                st.session_state["dba_control_room_morning_brief_markdown"] = packet["markdown"]
                st.session_state["dba_operations_priority_index"] = packet["operations_priority"]
                st.session_state["dba_control_room_handoff"] = packet["handoff"]
                st.session_state["dba_control_room_escalation_packet"] = packet["escalation_packet"]

        morning_packet = st.session_state.get("morning_data")
        expected_meta = _account_health_scope_meta(company, environment, window=f"{int(morning_lookback)}h")
        if not morning_packet:
            st.info("Refresh the morning brief when the on-call DBA needs a ranked operating packet.")
        elif not _account_health_meta_matches(st.session_state.get("morning_data_meta"), expected_meta):
            st.warning("Loaded DBA Morning Brief is stale for the active scope. Refresh before using it.")
        else:
            from sections import dba_control_room as dba

            st.caption(f"Measurement: {morning_packet.get('_source', 'DBA Control Room telemetry')}")
            dba._render_dba_morning_brief(
                morning_packet.get("brief", pd.DataFrame()),
                str(morning_packet.get("markdown") or ""),
            )
            source_health = morning_packet.get("source_health", pd.DataFrame())
            if source_health is not None and not source_health.empty:
                with st.expander("Brief inputs", expanded=False):
                    render_priority_dataframe(
                        source_health,
                        title="Morning brief input readiness",
                        priority_columns=[
                            "PRIORITY_RANK", "SURFACE", "STATE", "EVIDENCE",
                            "OWNER_OR_ROUTE", "NEXT_ACTION", "PROOF_REQUIRED", "SOURCE",
                        ],
                        sort_by=["PRIORITY_RANK", "SURFACE"],
                        ascending=[True, True],
                        raw_label="All morning brief input rows",
                        height=260,
                        max_rows=8,
                    )
