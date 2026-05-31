"""Account Health: KPIs, Resource Monitors, Morning Report, and executive briefing."""
import html
import streamlit as st
import pandas as pd
from datetime import datetime
from config import ALERT_DB, ALERT_SCHEMA, ACTION_QUEUE_TABLE
from utils import (
    get_session, run_query, run_query_or_raise, format_credits,
    credits_to_dollars, download_csv, mark_loaded, show_loaded_time,
    build_metered_credit_cte, build_monitoring_cost_sql,
    metric_confidence_label, freshness_note,
    render_drillable_bar_chart,
    build_task_failure_summary_sql, build_task_health_sql,
    executive_health_score,
    get_credit_price,
    get_wh_filter_clause, get_db_filter_clause, get_user_filter_clause,
    get_global_filter_clause, company_value_allowed, get_active_environment,
    load_latest_control_room_mart, mart_source_caption,
    build_mart_account_health_storage_sql, build_mart_account_health_cost_drivers_sql,
    build_mart_account_health_change_sql, build_mart_control_room_task_failures_sql,
    build_mart_control_room_warehouse_pressure_sql,
    build_mart_account_health_failure_types_sql, build_mart_account_health_long_queries_sql,
    build_mart_account_health_credits_sql, build_mart_account_health_failure_count_sql,
    build_mart_account_health_top_driver_sql, build_mart_account_health_queued_sql,
    build_mart_account_health_ytd_credits_sql,
    format_snowflake_error, filter_existing_columns, make_action_id, safe_float, safe_identifier, safe_int,
    sql_literal, upsert_actions, action_queue_environment_clause, resolve_owner_context, mart_object_name,
)
from utils.workflows import render_operator_briefing, render_priority_dataframe

CHECKLIST_HISTORY_TABLE = "OVERWATCH_DBA_CHECKLIST_HISTORY"
ACCOUNT_HEALTH_OPERABILITY_FACT_TABLE = "FACT_ACCOUNT_HEALTH_OPERABILITY_DAILY"
ACCOUNT_HEALTH_ACTION_SOURCE = "Account Health - Daily DBA Checklist"
ACCOUNT_HEALTH_SCOPE_FILTER_KEYS = (
    "global_start_date",
    "global_end_date",
    "global_warehouse",
    "global_user",
    "global_role",
    "global_database",
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
) -> dict:
    """Return the filter scope that loaded Account Health evidence must match."""
    state = state if state is not None else st.session_state
    meta = {
        "company": _account_health_scope_value(company),
        "environment": _account_health_scope_value(environment),
    }
    if window:
        meta["window"] = _account_health_scope_value(window)
    for key in ACCOUNT_HEALTH_SCOPE_FILTER_KEYS:
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
    if "mart" in source_lower or "fact_" in source_lower:
        return "Pre-aggregated"
    if "fallback" in source_lower:
        return "Live fallback"
    if "account_usage" in source_lower or "information_schema" in source_lower:
        return "Live Snowflake metadata"
    return default


def _account_health_source_next_action(state: str, source: str) -> str:
    source_lower = str(source or "").lower()
    if state == "Stale":
        return "Reload after changing company, environment, lookback, or global filters."
    if state == "Unavailable":
        return "Deploy or refresh the mart/grants before relying on this surface."
    if state == "Not Loaded":
        return "Load only when this workflow is part of the current DBA investigation."
    if state == "No Rows":
        return "Confirm the selected scope has recent account activity or persisted evidence."
    if "fallback" in source_lower:
        return "Use for investigation; prefer mart refresh for repeated morning control."
    return "Current for the active Account Health scope."


def _account_health_source_health_rows(
    state: dict,
    company: str,
    environment: str,
) -> pd.DataFrame:
    """Summarize Account Health evidence freshness and source strategy."""
    health_data = state.get("health_data", {})
    if not isinstance(health_data, dict):
        health_data = {}
    definitions = [
        {
            "surface": "Overview snapshot",
            "value": health_data,
            "source": health_data.get("_account_health_detail_source", "OVERWATCH mart or live ACCOUNT_USAGE"),
            "meta_key": "account_health_overview_meta",
            "window": "24h",
            "confidence": "Mixed",
        },
        {
            "surface": "Control-room mart",
            "value": health_data.get("_control_mart"),
            "source": health_data.get("_control_mart_source", "OVERWATCH control-room mart"),
            "meta_key": "account_health_overview_meta",
            "window": "24h",
            "confidence": "Pre-aggregated",
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
            "surface": "Operability fact",
            "value": state.get("account_health_operability_fact"),
            "source": f"OVERWATCH mart: {ACCOUNT_HEALTH_OPERABILITY_FACT_TABLE}",
            "meta_key": "account_health_operability_fact_meta",
            "window": "30d",
            "confidence": "Pre-aggregated",
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
        },
        {
            "surface": "Checklist trend",
            "value": state.get("account_health_checklist_trend"),
            "source": f"Workflow mart: {CHECKLIST_HISTORY_TABLE}",
            "meta_key": "account_health_checklist_trend_meta",
            "window_key": "account_health_checklist_trend_days",
            "default_window": "30d",
            "confidence": "Workflow evidence",
        },
        {
            "surface": "Closure analytics",
            "value": state.get("account_health_closure_analytics"),
            "source": "Action queue closure evidence",
            "meta_key": "account_health_closure_analytics_meta",
            "window_key": "account_health_closure_days",
            "default_window": "30d",
            "confidence": "Workflow evidence",
        },
        {
            "surface": "Morning report",
            "value": state.get("morning_data"),
            "source": state.get("morning_data_source", "OVERWATCH mart or live ACCOUNT_USAGE"),
            "meta_key": "morning_data_meta",
            "window": "12h",
            "confidence": "Mixed",
        },
        {
            "surface": "Executive briefing",
            "value": state.get("ah_briefing_text"),
            "source": state.get("ah_briefing_source", "OVERWATCH mart or live ACCOUNT_USAGE"),
            "meta_key": "ah_briefing_meta",
            "window_key": "ah_briefing_window",
            "default_window": "24h",
            "confidence": "Mixed",
        },
    ]
    rows = []
    for item in definitions:
        window = _account_health_scope_value(
            item.get("window", state.get(item.get("window_key"), item.get("default_window", "")))
        )
        expected_meta = _account_health_scope_meta(company, environment, window=window, state=state)
        value = item.get("value")
        error = state.get(item.get("error_key", ""))
        if error:
            status = "Unavailable"
        elif not _account_health_loaded(value):
            status = "Not Loaded"
        elif not _account_health_meta_matches(state.get(item["meta_key"]), expected_meta):
            status = "Stale"
        elif _account_health_is_empty(value):
            status = "No Rows"
        else:
            status = "Loaded"
        rows.append({
            "SURFACE": item["surface"],
            "STATE": status,
            "STATE_RANK": {
                "Unavailable": 0,
                "Stale": 1,
                "Loaded": 2,
                "No Rows": 3,
                "Not Loaded": 4,
            }.get(status, 9),
            "SOURCE": item["source"],
            "CONFIDENCE": _account_health_source_confidence(item["source"], item["confidence"]),
            "ROWS": _account_health_row_count(value),
            "SCOPE": f"{company} / {environment} / {window}",
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
    st.session_state["nav_section"] = section
    if workflow_key and workflow:
        st.session_state[workflow_key] = workflow
    if wh_filter:
        st.session_state["lm_wh"]     = wh_filter
        st.session_state["wh_filter"] = wh_filter
    if user_filter:
        st.session_state["global_user"] = user_filter
    st.rerun()


def _build_briefing_prompt(data: dict, credit_price: float, company: str) -> str:
    """Build the Cortex prompt from collected health metrics."""
    cr24     = data.get("cr24",     0)
    cr_prior = data.get("cr_prior", 0)
    cr_delta = ((cr24 - cr_prior) / cr_prior * 100) if cr_prior > 0 else 0
    cost24   = credits_to_dollars(cr24, credit_price)
    failures = data.get("failures", 0)
    queued   = data.get("queued",   0)
    stor_tb  = data.get("stor_tb",  0)
    contract_pct = data.get("contract_pct", None)
    top_driver    = data.get("top_driver",   "")
    top_driver_cost = data.get("top_driver_cost", 0)
    failed_task   = data.get("failed_task",   "")

    contract_line = (
        f"Contract utilization is at {contract_pct:.1f}% of annual committed credits."
        if contract_pct is not None
        else "Contract utilization data not available."
    )
    task_line = (
        f"A task failure was detected: {failed_task}."
        if failed_task
        else "No critical task failures overnight."
    )

    return f"""You are OVERWATCH, a Snowflake monitoring assistant for ALFA Insurance.
Write a concise executive briefing (3–4 short paragraphs, plain English, no bullet points, no markdown headers).
The audience is senior IT leadership — not technical DBAs.
Tone: professional, direct, factual. Flag risks clearly. Quantify in dollars where possible.
Do NOT invent data. Only use the numbers provided. Do NOT use markdown headers or bullet points.
Today is {datetime.now().strftime('%A, %B %d %Y')}.
Company: {company}

Data:
- Credits consumed (last 24h): {cr24:,.0f} (${cost24:,.2f} at ${credit_price:.2f}/credit)
- Credit change vs prior 24h: {cr_delta:+.1f}%
- Top cost driver: {top_driver} (${top_driver_cost:,.2f} yesterday)
- Query failures (last 24h): {failures}
- Queued queries (current): {queued}
- Storage: {stor_tb:.1f} TB
- {contract_line}
- {task_line}

Write the briefing now. Start with yesterday's overall performance summary, then highlight risks,
then one recommended action for leadership."""


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
    # Snowflake-hosted Streamlit can reject INFORMATION_SCHEMA table functions
    # that reveal current-user session details. ACCOUNT_USAGE is lagged, but it
    # is the safer default for the landing page and avoids noisy startup errors.
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
        return run_query_or_raise(fallback_sql), "ACCOUNT_USAGE"
    except Exception:
        try:
            return run_query_or_raise(_live_query_status_sql(wh_filter, db_filter, user_filter)), "INFORMATION_SCHEMA"
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
            "escalation": "Application Owner / DBA On-Call",
            "source": "Checklist owner map",
        }
    elif "queue pressure" in name:
        base = {
            "owner": "Platform DBA",
            "escalation": "Warehouse Owner / DBA On-Call",
            "source": "Checklist owner map",
        }
    elif "cost spike" in name:
        base = {
            "owner": "DBA / FinOps Owner",
            "escalation": "FinOps Lead",
            "source": "Checklist owner map",
        }
    elif "task" in name or "procedure" in name:
        base = {
            "owner": "Data Engineering On-Call",
            "escalation": "Pipeline Owner / DBA On-Call",
            "source": "Checklist owner map",
        }
    elif "change" in name or "drift" in name:
        base = {
            "owner": "DBA Change Owner",
            "escalation": "Security Owner / Data Governance",
            "source": "Checklist owner map",
        }
    elif "storage" in name or "monitor" in name:
        base = {
            "owner": "Platform DBA",
            "escalation": "DBA Lead",
            "source": "Checklist owner map",
        }
    elif "source confidence" in name:
        base = {
            "owner": "OVERWATCH Platform Owner",
            "escalation": "DBA Lead",
            "source": "Checklist owner map",
        }
    else:
        base = {
            "owner": "DBA Lead" if route_text == "DBA Control Room" else "DBA",
            "escalation": "DBA Lead",
            "source": "Default DBA owner",
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
            "CHECK": "Refresh source confidence",
            "STATUS": "OK" if control_mart_used else "Verify fallback",
            "SEVERITY": "Low" if control_mart_used else "Medium",
            "EVIDENCE": detail_source or ("OVERWATCH mart facts" if control_mart_used else "Live ACCOUNT_USAGE fallback"),
            "OWNER": "DBA",
            "ROUTE": "DBA Control Room",
            "NEXT_ACTION": "Use mart snapshot for morning control when filters allow it; document live fallback before acting.",
            "PROOF_REQUIRED": "Snapshot timestamp or fallback source note",
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
            "ROUTE": "Warehouse Health",
            "NEXT_ACTION": "Confirm whether pressure is sizing, concurrency, lock, or workload-shape driven before changing warehouses.",
            "PROOF_REQUIRED": "warehouse, queued time, query count, before/after setting",
        },
        {
            "CHECK": "Cost spike review",
            "STATUS": _check_status(delta <= 20, delta <= 40),
            "SEVERITY": "High" if delta > 60 else ("Medium" if delta > 20 else "Info"),
            "EVIDENCE": f"{last24:,.2f} credits in last 24h; {delta:+.1f}% vs prior window",
            "OWNER": "DBA / FinOps",
            "ROUTE": "Cost & Contract",
            "NEXT_ACTION": "Explain top drivers, classify allocated/estimated cost, and verify any savings action later.",
            "PROOF_REQUIRED": "driver row, credit/cost formula, approval for warehouse changes",
        },
        {
            "CHECK": "Task and procedure reliability",
            "STATUS": _check_status(failed_task_count == 0),
            "SEVERITY": "High" if failed_task_count > 0 else "Info",
            "EVIDENCE": f"{failed_task_count:,} failed task groups in last 24h",
            "OWNER": "DBA / Data Engineering",
            "ROUTE": "Workload Operations",
            "NEXT_ACTION": "Open task graphs and verify recovery SLA, downstream impact, and retry approval.",
            "PROOF_REQUIRED": "task history, root cause, owner approval, recovery evidence",
        },
        {
            "CHECK": "Change and drift review",
            "STATUS": _check_status(change_count == 0, change_count <= 10),
            "SEVERITY": "Medium" if change_count > 0 else "Info",
            "EVIDENCE": f"{change_count:,} object/access change signals in last 24h",
            "OWNER": "DBA / Security Owner",
            "ROUTE": "Change & Drift",
            "NEXT_ACTION": "Validate query IDs against change tickets, approvers, and IaC/source-control state.",
            "PROOF_REQUIRED": "query_id, approver, change ticket, dependency note",
        },
        {
            "CHECK": "Storage and monitor posture",
            "STATUS": _check_status(stor_tb > 0, stor_tb == 0),
            "SEVERITY": "Low" if stor_tb > 0 else "Medium",
            "EVIDENCE": f"{safe_float(stor_tb):.1f} TB latest storage reading",
            "OWNER": "DBA / Platform",
            "ROUTE": "Account Health",
            "NEXT_ACTION": "Review Resource Monitors for quota, notify, suspend, and suspend-immediate coverage.",
            "PROOF_REQUIRED": "resource monitor thresholds and warehouse scope",
        },
    ]
    if score < 75:
        rows.insert(0, {
            "CHECK": "Overall health escalation",
            "STATUS": "Needs DBA",
            "SEVERITY": "High" if score < 60 else "Medium",
            "EVIDENCE": f"Health score {score:.0f} ({score_label})",
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
    if "refresh source confidence" in name:
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
            evidence = f"Checklist source can be validated against database-aware Snowflake facts scoped to {env_scope}."
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
    owner_source = str(row.get("OWNER_SOURCE") or "")
    severity = str(row.get("SEVERITY") or "").upper()
    approval_group = str(row.get("APPROVAL_GROUP") or row.get("ESCALATION_TARGET") or "").strip()
    proof = str(row.get("PROOF_REQUIRED") or "").strip()
    scope_confidence = str(row.get("SCOPE_CONFIDENCE") or "").strip()
    verification = _account_health_verification_sql(row.get("CHECK"), row.get("EVIDENCE"))
    blockers = []

    generic_owners = {"", "DBA", "UNKNOWN", "N/A", "DBA / FINOPS", "DBA / DATA ENGINEERING"}
    if owner.upper() in generic_owners or "OWNER_DIRECTORY" not in owner_source.upper():
        blockers.append("owner directory evidence")
    approval_required = severity in {"CRITICAL", "HIGH", "MEDIUM"}
    if approval_required and not approval_group:
        blockers.append("approver or approval group")
    if not proof:
        blockers.append("proof requirement")
    verification_upper = verification.upper()
    if not verification or not any(
        token in verification_upper
        for token in ("SNOWFLAKE.ACCOUNT_USAGE", "INFORMATION_SCHEMA", "OVERWATCH")
    ):
        blockers.append("source verification SQL")
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
    """Add DBA routing, scope, and queue-readiness evidence to checklist rows."""
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
                state, rank = "Closure Evidence Blocked", 1
                next_action = str(close.get("NEXT_ACTION") or "Attach verification and recovery evidence before closure.")
            elif queue_readiness != "Ready to Queue":
                state, rank = "Route Metadata Blocked", 2
                next_action = f"Complete checklist route metadata: {queue_blockers or 'owner, approval, or proof evidence'}."
            elif check in actionable_checks and open_actions == 0:
                state, rank = "Queue Required", 3
                next_action = "Save this checklist issue to the action queue with proof and owner approval context."
            elif open_actions > 0:
                state, rank = "Work Open Action", 4
                next_action = str(close.get("NEXT_ACTION") or row.get("NEXT_ACTION") or "Work open checklist action.")
            elif issue_snapshots > 1:
                state, rank = "Recurring Watch", 6
                next_action = "Review repeated checklist snapshots and create a durable control if the issue recurs."
            elif verified:
                state, rank = "Verified Closure", 8
                next_action = "Retain verified closure evidence for audit trend review."
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
            next_action = "Complete owner, approval, and proof metadata for account-level access hygiene rows."
        elif high:
            state, rank = "High-Risk Access Review", 2
            next_action = "Queue high-risk admin, MFA, stale, or failed-login user hygiene items for Security/DBA review."
        else:
            state, rank = "Access Hygiene Watch", 6
            next_action = "Review medium-risk account hygiene rows and retain account-level evidence."
        rows.append({
            "CONTROL_STATE": state,
            "CONTROL_RANK": rank,
            "CHECK_NAME": "Account access hygiene",
            "STATUS": "Needs DBA",
            "SEVERITY": "High" if high else "Medium",
            "ROUTE": "Security Posture",
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
            "PROOF_REQUIRED": "user, IAM ticket, admin-role/MFA evidence, owner approval",
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
    'Confirm IAM owner, admin-role business need, MFA posture, and recent login evidence before disabling users or changing grants.' AS next_action,
    'user, IAM ticket, failed login context, MFA/admin-role evidence, owner approval' AS proof_required
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
    view["OWNER_SOURCE"] = contexts.apply(lambda item: item.get("OWNER_SOURCE", "Default security owner"))
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
    owner_source = view["OWNER_SOURCE"].fillna("").astype(str).str.upper()
    owner = view["OWNER"].fillna("").astype(str).str.upper()
    approval_group = view["APPROVAL_GROUP"].fillna("").astype(str)
    owner_ready = (~owner.isin({"", "DBA", "UNKNOWN", "N/A"})) & owner_source.str.contains("OWNER_DIRECTORY", na=False)
    approval_required = severity.isin({"HIGH", "MEDIUM"})
    proof_ready = proof.str.len() > 0
    view["APPROVAL_REQUIRED"] = approval_required.map({True: "Yes", False: "No"})
    view["QUEUE_READINESS"] = (
        owner_ready & proof_ready & (~approval_required | (approval_group.str.len() > 0))
    ).map({True: "Ready to Queue", False: "Needs Routing Data"})
    view["QUEUE_BLOCKERS"] = "None"
    view.loc[~owner_ready, "QUEUE_BLOCKERS"] = "owner directory evidence"
    view.loc[~proof_ready, "QUEUE_BLOCKERS"] = view.loc[~proof_ready, "QUEUE_BLOCKERS"].replace("None", "proof requirement")
    view.loc[approval_required & (approval_group.str.len() == 0), "QUEUE_BLOCKERS"] = "approver or approval group"
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
    COUNT_IF(CONTROL_READINESS IN ('Closure Overdue', 'Closure Evidence Blocked', 'Route Metadata Blocked', 'Queue Required')) AS CONTROL_BLOCKER_SNAPSHOTS,
    ROUND(AVG(HEALTH_SCORE), 1) AS AVG_HEALTH_SCORE
FROM {fqn}
WHERE {where_clause}
GROUP BY CHECK_NAME
ORDER BY CONTROL_BLOCKER_SNAPSHOTS DESC, ISSUE_SNAPSHOTS DESC, LAST_SNAPSHOT_TS DESC, CHECK_NAME
LIMIT 100""".strip()


def _account_health_closure_analytics_sql(days: int, company: str, environment: str = "ALL") -> str:
    fqn = account_health_action_queue_fqn()
    where = [
        f"SOURCE = {sql_literal(ACCOUNT_HEALTH_ACTION_SOURCE, 100)}",
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
        COUNT_IF(UPPER(OWNER) IN ('', 'DBA', 'UNKNOWN', 'N/A', 'DBA / FINOPS', 'DBA / DATA ENGINEERING')) AS OWNER_GAP_ROWS,
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
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 'Fixed without verification'
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 'Control metadata gap'
        WHEN OPEN_ACTIONS > 0 THEN 'Open'
        WHEN VERIFIED_CLOSURES > 0 THEN 'Verified closure'
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
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 'Attach verification notes/result or reopen the checklist action.'
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 'Complete owner, ticket, approver, and verification metadata.'
        WHEN OPEN_ACTIONS > 0 THEN 'Work the open checklist action and attach proof before closing.'
        ELSE 'Retain verified closure evidence for audit trend review.'
    END AS NEXT_ACTION
FROM rollup
ORDER BY CLOSURE_RANK, OVERDUE_OPEN DESC, FIXED_WITHOUT_VERIFICATION DESC, OPEN_ACTIONS DESC, LAST_ACTIVITY_TS DESC
LIMIT 100""".strip()


def _account_health_operability_fact_sql(days: int, company: str, environment: str = "ALL") -> str:
    """Read pre-aggregated Account Health checklist, hygiene, and closure blockers."""
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
        st.info("Deploy the checklist history table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry this save.")


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
    action = str(row.get("NEXT_ACTION") or "Review the failed Account Health checklist item and attach proof.")
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
        "Approval Group": approval_group,
        "Escalation Target": escalation,
        "Owner Source": row.get("OWNER_SOURCE", ""),
        "Owner Evidence": row.get("OWNER_EVIDENCE", ""),
        "Finding": f"{check}: {evidence}",
        "Action": action,
        "Estimated Monthly Savings": 0.0,
        "Generated SQL Fix": "\n".join([
            "-- Daily DBA checklist action. Do not execute state-changing SQL from this row.",
            f"-- Route: {route}",
            f"-- Proof required: {row.get('PROOF_REQUIRED', 'verification evidence')}",
            f"-- Queue readiness: {row.get('QUEUE_READINESS', 'Ready to Queue')}",
            f"-- Scope confidence: {row.get('SCOPE_CONFIDENCE', 'Account-Level Control')}",
        ]),
        "Proof Query": verification_query,
        "Verification Query": verification_query,
        "Verification Status": "Pending",
        "Approver": approval_group if approval_required else owner,
        "Owner Approval Status": "Requested" if approval_required else "Not Required",
        "Owner Approval Note": (
            f"Checklist status: {row.get('STATUS', '')}. Route: {route}. "
            f"Escalation: {escalation}. Owner evidence: {row.get('OWNER_EVIDENCE', '')}. "
            f"Queue readiness: {row.get('QUEUE_READINESS', '')}; blockers: {row.get('QUEUE_BLOCKERS', '')}. "
            f"Scope: {row.get('SCOPE_CONFIDENCE', '')}."
        ),
        "Recovery Evidence": (
            f"Proof required: {row.get('PROOF_REQUIRED', 'verification evidence')}. Evidence: {evidence}. "
            f"Scope evidence: {row.get('SCOPE_EVIDENCE', '')}."
        ),
        "Recovery Audit State": "Checklist Verification Pending",
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
        st.info("Deploy the Action Queue table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry this save.")


def _render_account_health_access_hygiene(session, company: str, environment: str) -> None:
    with st.expander("Account Access Hygiene", expanded=False):
        st.caption(
            "Account-level user/auth posture is intentionally not database-filtered. "
            "Rows are labeled No Database Context so PROD/DEV selections do not imply false precision."
        )
        days = st.slider("Access hygiene lookback days", 7, 120, 30, key="account_health_access_hygiene_days")
        if st.button("Load Access Hygiene", key="account_health_access_hygiene_load"):
            try:
                sql = _account_health_access_hygiene_sql(
                    session,
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
                    company, environment, window=f"{int(days)}d"
                )
            except Exception as exc:
                st.session_state["account_health_access_hygiene"] = pd.DataFrame()
                st.warning(f"Account access hygiene unavailable: {format_snowflake_error(exc)}")

        hygiene = st.session_state.get("account_health_access_hygiene")
        if (
            hygiene is not None
            and not _account_health_meta_matches(
                st.session_state.get("account_health_access_hygiene_meta"),
                _account_health_scope_meta(company, environment, window=f"{int(days)}d"),
            )
        ):
            st.info("Loaded access hygiene is stale for the active scope. Reload before queuing access work.")
            with st.expander("Access Hygiene Query", expanded=False):
                st.code(
                    st.session_state.get("account_health_access_hygiene_sql", "-- Reload access hygiene to regenerate SQL."),
                    language="sql",
                )
        elif hygiene is not None and not hygiene.empty:
            h1, h2, h3, h4 = st.columns(4)
            h1.metric("Users to Review", f"{len(hygiene):,}")
            high = int((hygiene.get("SEVERITY", pd.Series(dtype=str)).astype(str).str.upper() == "HIGH").sum())
            h2.metric("High Risk", f"{high:,}", delta_color="inverse")
            failed = int((pd.to_numeric(hygiene.get("FAILED_LOGINS", pd.Series(dtype=float)), errors="coerce").fillna(0) > 0).sum())
            h3.metric("Failed Login Users", f"{failed:,}")
            admins = int((pd.to_numeric(hygiene.get("ADMIN_ROLE_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0) > 0).sum())
            h4.metric("Admin Role Reviews", f"{admins:,}")
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
            with st.expander("Access Hygiene Query", expanded=False):
                st.code(st.session_state.get("account_health_access_hygiene_sql", ""), language="sql")
        elif hygiene is not None:
            st.success("No account-level access hygiene candidates found for the selected lookback.")


def _render_account_health_source_health(company: str, environment: str) -> None:
    source_health = _account_health_source_health_rows(dict(st.session_state), company, environment)
    if source_health.empty:
        return
    with st.expander("Account Health Source Health", expanded=False):
        current = int(source_health["STATE"].isin(["Loaded", "No Rows"]).sum())
        stale = int(source_health["STATE"].eq("Stale").sum())
        unavailable = int(source_health["STATE"].eq("Unavailable").sum())
        mart_backed = int(
            source_health[
                source_health["STATE"].isin(["Loaded", "No Rows"])
                & source_health["SOURCE"].astype(str).str.contains("mart|FACT_", case=False, regex=True)
            ].shape[0]
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Current Surfaces", f"{current}/{len(source_health)}")
        c2.metric("Mart-Backed", f"{mart_backed:,}")
        c3.metric("Stale", f"{stale:,}", delta_color="inverse")
        c4.metric("Unavailable", f"{unavailable:,}", delta_color="inverse")
        st.caption(
            "Use this before publishing the morning report or queueing checklist work. "
            "Account-level controls stay visible under environment filters when Snowflake has no database context."
        )
        render_priority_dataframe(
            source_health,
            title="Account Health evidence source and freshness",
            priority_columns=[
                "SURFACE", "STATE", "SOURCE", "CONFIDENCE", "ROWS", "SCOPE", "NEXT_ACTION",
            ],
            sort_by=["STATE_RANK", "SURFACE"],
            ascending=[True, True],
            raw_label="All Account Health source-health rows",
            height=320,
        )


def render():
    session      = get_session()
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
    cost_wh_size_expr = (
        "MAX(q.warehouse_size)"
        if "WAREHOUSE_SIZE" in qh_cols
        else "NULL::VARCHAR"
    )
    cost_bytes_scanned_expr = (
        "SUM(q.bytes_scanned)"
        if "BYTES_SCANNED" in qh_cols
        else "0"
    )
    failed_pred_q = (
        "q.error_code IS NOT NULL"
        if "ERROR_CODE" in qh_cols
        else "UPPER(q.execution_status) = 'FAILED_WITH_ERROR'"
    )
    failed_pred_plain = (
        "error_code IS NOT NULL"
        if "ERROR_CODE" in qh_cols
        else "UPPER(execution_status) = 'FAILED_WITH_ERROR'"
    )
    queue_cols = [
        col.lower()
        for col in ["QUEUED_OVERLOAD_TIME", "QUEUED_PROVISIONING_TIME", "QUEUED_REPAIR_TIME"]
        if col in qh_cols
    ]
    queue_time_q = " + ".join([f"COALESCE(q.{col}, 0)" for col in queue_cols])
    queue_time_plain = " + ".join([f"COALESCE({col}, 0)" for col in queue_cols])
    queued_count_expr_q = (
        f"SUM(CASE WHEN {queue_time_q} > 0 OR q.execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END)"
        if queue_cols
        else "SUM(CASE WHEN q.execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END)"
    )
    queued_count_expr_plain = (
        f"SUM(CASE WHEN {queue_time_plain} > 0 OR execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END)"
        if queue_cols
        else "SUM(CASE WHEN execution_status ILIKE '%QUEUED%' THEN 1 ELSE 0 END)"
    )
    pressure_wh_size_expr = (
        "MAX(warehouse_size)"
        if "WAREHOUSE_SIZE" in qh_cols
        else "NULL::VARCHAR"
    )

    tab_overview, tab_resmon, tab_morning, tab_briefing = st.tabs([
        "Overview", "Resource Monitors", "Morning Report", "Executive Briefing"
    ])

    # ── OVERVIEW ──────────────────────────────────────────────────────────────
    with tab_overview:
        st.header("Account Health - Command Center")
        render_operator_briefing(
            [
                ("First move", "Refresh the health snapshot and read the exception signals."),
                ("Evidence", "Use cost drivers, failed work, warehouse pressure, and changes since yesterday."),
                ("Control", "Drill into the owning workflow before recommending action."),
                ("Output", "Generate the morning report or executive briefing from verified facts."),
            ],
            columns=4,
        )
        exceptions_only = bool(st.session_state.get("exceptions_only_mode", False))
        if exceptions_only:
            st.info("Leadership exceptions-only mode is on. Heavy drilldowns stay collapsed until you ask for detail.")
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

        refresh_health = st.button("Refresh Health", key="health_refresh")
        if (
            refresh_health
            or cache_age > 300
            or "health_data" not in st.session_state
            or st.session_state.get("_health_filter_sig") != filter_sig
        ):
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
                hd["_account_health_detail_source"] = "OVERWATCH mart facts"
            else:
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
                    session,
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
                    session,
                    "scheduled_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())",
                    company,
                )),
                ] + query_plan
            for key, sql in query_plan:
                try:
                    hd[key] = run_query_or_raise(sql)
                except Exception:
                    hd[key] = pd.DataFrame()

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
                {"Component": "Failed queries", "Observed": err_count, "Source": "MART_DBA_CONTROL_ROOM"},
                {"Component": "Failed tasks", "Observed": failed_tasks, "Source": "MART_DBA_CONTROL_ROOM"},
                {"Component": "Queued minutes", "Observed": round(queued_ms / 60000, 2), "Source": "MART_DBA_CONTROL_ROOM"},
                {"Component": "Security events", "Observed": safe_int(control_mart_row.get("SECURITY_EVENTS_24H", 0)), "Source": "MART_DBA_CONTROL_ROOM"},
                {"Component": "Object changes", "Observed": safe_int(control_mart_row.get("OBJECT_CHANGES_24H", 0)), "Source": "MART_DBA_CONTROL_ROOM"},
                {"Component": "Top risk", "Observed": control_mart_row.get("TOP_RISK", ""), "Source": "MART_DBA_CONTROL_ROOM"},
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

        k1, k2, k3, k4, k5, k6, k7 = st.columns(7)
        k1.metric("Health Score",   f"{health_score:.0f}", score_label)
        k2.metric("Active Queries", live_val)
        k3.metric("Queued",         queued)
        k4.metric("Credits (24h)",  f"{last24:,.0f}", delta=f"{pct_delta:+.1f}%")
        k5.metric("Cost (24h)",     f"${cost24:,.0f}")
        k6.metric("Storage",        f"{stor_tb:.1f} TB")
        k7.metric("Failed (24h)",   err_count, delta_color="inverse")
        st.caption(
            " | ".join([
                metric_confidence_label("composite"),
                metric_confidence_label("exact") + " for source counts",
                hd.get("_control_mart_source", "Live fallback"),
                freshness_note(live_source),
            ])
        )
        if control_mart_used:
            st.caption(f"Mart snapshot: {control_mart_row.get('SNAPSHOT_TS', '')}")
        st.caption(f"Landing signal detail source: {hd.get('_account_health_detail_source', 'Unknown')}")
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
        render_priority_dataframe(
            checklist,
            title="Daily DBA checklist",
            priority_columns=[
                "SEVERITY", "STATUS", "CHECK", "EVIDENCE", "OWNER",
                "ESCALATION_TARGET", "ROUTE", "ENVIRONMENT_SCOPE",
                "DATABASE_CONTEXT", "SCOPE_CONFIDENCE", "QUEUE_READINESS",
                "QUEUE_BLOCKERS", "APPROVAL_REQUIRED", "RECOVERY_SLA_TARGET_HOURS",
                "NEXT_ACTION", "PROOF_REQUIRED",
            ],
            sort_by=["SEVERITY", "CHECK"],
            ascending=[True, True],
            raw_label="All daily DBA checklist rows",
            height=300,
            max_rows=12,
        )
        operability_fact = st.session_state.get("account_health_operability_fact")
        if operability_fact is not None and not operability_fact.empty:
            st.subheader("Account Health Operability Mart")
            f1, f2, f3, f4 = st.columns(4)
            blocked_states = operability_fact["CONTROL_STATE"].astype(str).str.contains(
                "Blocked|Overdue|Required|Review", case=False, na=False
            )
            f1.metric("Fact Rows", f"{len(operability_fact):,}")
            f2.metric("Blocked / Review", f"{int(blocked_states.sum()):,}", delta_color="inverse")
            f3.metric("Overdue", f"{int(operability_fact.get('OVERDUE_OPEN', pd.Series(dtype=int)).sum()):,}", delta_color="inverse")
            f4.metric("Verified Closures", f"{int(operability_fact.get('VERIFIED_CLOSURES', pd.Series(dtype=int)).sum()):,}")
            render_priority_dataframe(
                operability_fact,
                title="Pre-aggregated Account Health blockers",
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
                raw_label="All Account Health operability facts",
                height=320,
                max_rows=12,
            )
            with st.expander("Account Health operability fact query", expanded=False):
                st.code(st.session_state.get("account_health_operability_fact_sql", ""), language="sql")
        elif st.session_state.get("account_health_operability_fact_error"):
            st.caption(
                "Account Health operability mart not available yet; deploy or refresh "
                "`FACT_ACCOUNT_HEALTH_OPERABILITY_DAILY` to enable the fast blocker surface."
            )
        account_control_board = _account_health_control_board(
            checklist,
            closure=st.session_state.get("account_health_closure_analytics"),
            access_hygiene=st.session_state.get("account_health_access_hygiene"),
            trend=st.session_state.get("account_health_checklist_trend"),
            environment=get_active_environment(),
        )
        if not account_control_board.empty:
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
        actionable_checklist = _account_health_actionable_checklist(checklist)
        q1, q2, q3 = st.columns([1, 1, 3])
        with q1:
            if st.button(
                "Queue Checklist Issues",
                key="account_health_queue_checklist",
                use_container_width=True,
                disabled=actionable_checklist.empty,
            ):
                _queue_account_health_checklist(
                    session,
                    checklist,
                    company=company,
                    environment=get_active_environment(),
                )
        with q2:
            if st.button(
                "Save Checklist Snapshot",
                key="account_health_save_checklist_snapshot",
                use_container_width=True,
            ):
                _save_account_health_checklist_snapshot(
                    session,
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
                    f"{len(actionable_checklist):,} checklist issue(s) will be saved with owner, approver, "
                    f"verification SQL, proof requirements, and scope evidence. {ready_count:,} are route-ready without blockers."
                )
        _render_account_health_access_hygiene(
            session,
            company=company,
            environment=get_active_environment(),
        )
        with st.expander("Daily DBA Checklist Trend", expanded=False):
            trend_days = st.slider("Checklist trend days", 7, 90, 30, key="account_health_checklist_trend_days")
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
            with st.expander("Checklist history setup SQL", expanded=False):
                st.code(build_account_health_checklist_history_ddl(), language="sql")
        with st.expander("Daily DBA Closure Analytics", expanded=False):
            st.caption(
                "Uses Account Health action-queue rows to show whether checklist issues are still open, "
                "overdue, or closed without verification evidence."
            )
            closure_days = st.slider("Closure analytics days", 7, 120, 30, key="account_health_closure_days")
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
                    st.info("Deploy the latest Action Queue table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry.")
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
                    title="Checklist closure evidence gaps",
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
                with st.expander("Closure Analytics Query", expanded=False):
                    st.code(st.session_state.get("account_health_closure_analytics_sql", ""), language="sql")
            elif closure is not None:
                st.info("No Account Health checklist action-queue rows found for the selected scope.")
        with st.expander("Health score contributors", expanded=False):
            render_priority_dataframe(
                health_components,
                title="Health score components",
                priority_columns=["COMPONENT", "SCORE", "WEIGHT", "SIGNAL"],
                sort_by=["SCORE"],
                ascending=True,
                raw_label="All health score components",
                height=260,
            )

        st.divider()
        show_loaded_time("account_health")

        r1, r2 = st.columns([2, 1])
        with r1:
            st.markdown("**Exception Signals**")
            alerts = []
            if err_count > 10:  alerts.append({"Severity": "High", "Alert": "High error rate",  "Detail": f"{err_count} failures"})
            if pct_delta > 30:  alerts.append({"Severity": "Medium", "Alert": "Credit spike",      "Detail": f"+{pct_delta:.0f}%"})
            if queued > 5:      alerts.append({"Severity": "Medium", "Alert": "Queue pressure",    "Detail": f"{queued} queued"})
            if alerts:
                render_priority_dataframe(
                    pd.DataFrame(alerts),
                    title="Active exception signals",
                    priority_columns=["Severity", "Alert", "Detail"],
                    sort_by=["Severity", "Alert"],
                    ascending=[True, True],
                    raw_label="All active signals",
                )
            else:
                st.success("No active alerts")

        with r2:
            st.markdown("**Quick Nav**")
            def _jump(tgt, workflow=None):
                st.session_state["nav_section"] = tgt
                if workflow:
                    st.session_state["workload_operations_workflow"] = workflow
            for lbl, tgt, workflow in [
                ("Live",  "Workload Operations", "Live triage"),
                ("Query", "Workload Operations", "Query diagnosis"),
                ("Cost",  "Cost & Contract", None),
                ("DBA",  "Change & Drift", None),
            ]:
                st.button(lbl, key=f"jump_{lbl}", on_click=_jump, args=(tgt, workflow))

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
                        "→ Drill into user", ["(none)"] + cost_df["USER_NAME"].dropna().tolist(),
                        key="ah_drill_user", label_visibility="collapsed",
                    )
                    if sel_user and sel_user != "(none)":
                        if st.button(f"Open Cost & Contract for {sel_user}", key="ah_drill_user_btn"):
                            _drill_to(
                                "💸 Cost & Contract",
                                user_filter=sel_user,
                                workflow_key="cost_contract_workflow",
                                workflow="Explain bill / attribution / contract",
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
                st.metric("Queries",      f"{safe_int(row.get('QUERY_DELTA',0)):+,}")
                st.metric("Credits",      f"{safe_float(row.get('CREDIT_DELTA',0)):+,.2f}")
                st.metric("Failures",     f"{safe_int(row.get('FAILURE_DELTA',0)):+,}", delta_color="inverse")
            else:
                st.info("Change summary unavailable.")

        with e4:
            st.markdown("**Recommended next action**")
            st.info("Use Cost & Contract for optimization actions, action queue triage, and Teams-ready alerting.")
            if st.button("Open Cost & Contract", key="ah_open_recommendations"):
                _drill_to(
                    "💸 Cost & Contract",
                    workflow_key="cost_contract_workflow",
                    workflow="Recommendations and action queue",
                )

        st.divider()
        st.markdown("**OVERWATCH Cost of Monitoring**")
        mon_days = st.slider("Monitoring cost lookback days", 1, 30, 7, key="ah_monitoring_cost_days")
        if st.button("Load monitoring cost", key="ah_monitoring_cost_load"):
            mon_df = run_query(
                build_monitoring_cost_sql(mon_days),
                ttl_key=f"ah_monitoring_cost_{company}_{mon_days}",
                tier="historical",
                section="Account Health",
            )
            st.session_state["ah_monitoring_cost"] = mon_df
        mon_df = st.session_state.get("ah_monitoring_cost")
        if mon_df is not None and not mon_df.empty:
            mon_df = mon_df.copy()
            mon_df["EST_COST"] = mon_df["CREDITS"].apply(lambda x: credits_to_dollars(x, credit_price))
            m1, m2, m3 = st.columns(3)
            m1.metric("Observed Components", len(mon_df))
            m2.metric("Credits", format_credits(safe_float(mon_df["CREDITS"].sum())))
            m3.metric("Estimated Cost", f"${safe_float(mon_df['EST_COST'].sum()):,.2f}")
            st.caption("Keeps the monitor honest: app-tagged queries, Streamlit warehouse, Cortex, and alert task cost.")
            render_priority_dataframe(
                mon_df,
                title="Monitoring cost components",
                priority_columns=["COMPONENT", "CREDITS", "EST_COST", "SOURCE", "CONFIDENCE"],
                sort_by=["EST_COST", "CREDITS"],
                ascending=[False, False],
                raw_label="All monitoring cost rows",
                height=220,
            )
            download_csv(mon_df, "overwatch_monitoring_cost.csv")
        elif mon_df is not None:
            st.info("No tagged OVERWATCH monitoring cost found in the selected window.")

        if exceptions_only:
            st.caption("Exceptions-only mode intentionally stops here to avoid loading lower-priority drilldowns.")
            return

        st.divider()
        st.markdown("**🏭 Warehouse Pressure (last 1h)**")
        try:
            if control_mart_used:
                df_wp = run_query_or_raise(build_mart_control_room_warehouse_pressure_sql(1, company))
                if df_wp is not None and not df_wp.empty:
                    df_wp = df_wp.rename(columns={
                        "TOTAL_QUERIES": "QUERIES",
                        "QUEUED_QUERIES": "QUEUED",
                    })
            else:
                df_wp = run_query_or_raise(f"""
                    SELECT warehouse_name, {pressure_wh_size_expr} AS warehouse_size, COUNT(*) AS queries,
                           {queued_count_expr_plain} AS queued
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('hours',-1,CURRENT_TIMESTAMP())
                      AND warehouse_name IS NOT NULL
                      {wh_filter_m}
                    GROUP BY warehouse_name ORDER BY queries DESC LIMIT 8
                """)
            if not df_wp.empty:
                top_wh = df_wp.sort_values(["QUEUED","QUERIES"], ascending=False).iloc[0]
                st.metric(
                    "Top warehouse under pressure",
                    top_wh["WAREHOUSE_NAME"],
                    f"{int(top_wh['QUEUED'])} queued / {int(top_wh['QUERIES'])} queries",
                    delta_color="inverse",
                )
                render_drillable_bar_chart(
                    df_wp, dimension="WAREHOUSE_NAME", measure="QUERIES",
                    key="ah_warehouse_pressure", title="Warehouse pressure drill-down",
                    drilldown_column="warehouse_name", lookback_hours=24, top_n=8,
                )
                st.markdown("**→ Jump to Warehouse Health:**")
                wh_cols = st.columns(min(len(df_wp), 4))
                for idx, wh_row in df_wp.head(4).iterrows():
                    wh_name = wh_row["WAREHOUSE_NAME"]
                    with wh_cols[idx % 4]:
                        if st.button(wh_name, key=f"ah_wh_drill_{wh_name}"):
                            _drill_to("🏭 Warehouse Health", wh_filter=wh_name)
        except Exception as e:
            st.caption(f"Warehouse pressure unavailable: {format_snowflake_error(e)}")

    # ── RESOURCE MONITORS ─────────────────────────────────────────────────────
    with tab_resmon:
        st.header("Resource Monitor Dashboard")
        st.caption("Credit quota vs. consumed — with suspend threshold validation.")

        if st.button("Load Resource Monitors", key="resmon_load"):
            try:
                rm_object = "SNOWFLAKE.ACCOUNT_USAGE.RESOURCE_MONITORS"
                rm_cols = set(filter_existing_columns(
                    session,
                    rm_object,
                    [
                        "NAME", "CREATED", "CREDIT_QUOTA", "USED_CREDITS",
                        "REMAINING_CREDITS", "OWNER", "NOTIFY", "SUSPEND",
                        "SUSPEND_IMMEDIATE", "WAREHOUSES",
                    ],
                ))
                if "NAME" not in rm_cols:
                    raise ValueError("RESOURCE_MONITORS does not expose NAME for this role/account.")

                def _rm_expr(col: str, fallback: str, alias: str | None = None) -> str:
                    output = alias or col.lower()
                    if col in rm_cols:
                        if col == "WAREHOUSES":
                            return f"TO_VARCHAR({col.lower()}) AS {output}"
                        return f"{col.lower()} AS {output}"
                    return f"{fallback} AS {output}"

                df_rm = run_query(f"""
                    SELECT {_rm_expr("NAME", "NULL::VARCHAR")},
                           {_rm_expr("CREATED", "NULL::TIMESTAMP_NTZ")},
                           {_rm_expr("CREDIT_QUOTA", "0::FLOAT")},
                           {_rm_expr("USED_CREDITS", "0::FLOAT")},
                           {_rm_expr("REMAINING_CREDITS", "0::FLOAT")},
                           {_rm_expr("OWNER", "NULL::VARCHAR")},
                           {_rm_expr("NOTIFY", "NULL::VARCHAR")},
                           {_rm_expr("SUSPEND", "NULL::VARCHAR")},
                           {_rm_expr("SUSPEND_IMMEDIATE", "NULL::VARCHAR")},
                           {_rm_expr("WAREHOUSES", "NULL::VARCHAR")}
                    FROM SNOWFLAKE.ACCOUNT_USAGE.RESOURCE_MONITORS
                """, ttl_key="account_health_resource_monitors", tier="standard")
                if company != "ALL" and not df_rm.empty and "WAREHOUSES" in df_rm.columns:
                    def _monitor_in_company(value) -> bool:
                        text = str(value or "")
                        if not text.strip():
                            return False
                        tokens = [part.strip(" []'\"") for part in text.replace(",", " ").split()]
                        return any(company_value_allowed(token, "warehouse", company) for token in tokens)

                    df_rm = df_rm[df_rm["WAREHOUSES"].apply(_monitor_in_company)]
                st.session_state["ah_df_resmon"] = df_rm
            except Exception as e:
                st.warning(f"Resource monitor data unavailable: {format_snowflake_error(e)}")

        if st.session_state.get("ah_df_resmon") is not None and not st.session_state["ah_df_resmon"].empty:
            df_rm = st.session_state["ah_df_resmon"]
            total_quota = df_rm["CREDIT_QUOTA"].sum()
            total_used  = df_rm["USED_CREDITS"].sum()
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Quota",   format_credits(total_quota))
            c2.metric("Total Used",    format_credits(total_used))
            c3.metric("Overall Usage", f"{(total_used/total_quota*100) if total_quota else 0:.1f}%")

            for _, row in df_rm.iterrows():
                quota   = safe_float(row.get("CREDIT_QUOTA",0))
                used    = safe_float(row.get("USED_CREDITS",0))
                name    = row.get("NAME","Unknown")
                pct     = (used / quota * 100) if quota > 0 else 0
                suspend = row.get("SUSPEND","")
                s_imm   = row.get("SUSPEND_IMMEDIATE","")
                cols = st.columns(5)
                cols[0].metric(f"{name} Quota", format_credits(quota))
                cols[1].metric("Used",          format_credits(used))
                cols[2].metric("Remaining",     format_credits(safe_float(row.get("REMAINING_CREDITS",0))))
                cols[3].metric("Usage %",       f"{pct:.1f}%")
                cols[4].metric("Est. $",        f"${credits_to_dollars(used):,.2f}")
                if pct > 100:  st.error(f"**{name}** OVER BUDGET at {pct:.0f}%")
                elif pct > 80: st.warning(f"**{name}** at {pct:.0f}% - approaching limit")
                else:          st.success(f"**{name}** at {pct:.0f}% - on track")
                if not suspend and not s_imm:
                    st.warning(f"**{name}** has no suspend threshold.")
            download_csv(df_rm, "resource_monitors.csv")

    # ── MORNING REPORT ────────────────────────────────────────────────────────
    with tab_morning:
        st.header("Morning Health Report")
        st.caption("Overnight summary: failures, cost spikes, longest queries (last 12h).")

        if st.button("Generate Morning Report", key="morning_gen"):
            with st.spinner("Generating overnight report..."):
                md = {}
                morning_mart_ok, morning_mart_reason = _can_use_control_room_mart(company)
                morning_live_queries = {
                    "failures": f"""
                        SELECT query_type, COUNT(*) AS fail_count,
                               COUNT(DISTINCT user_name) AS affected_users,
                               COUNT(DISTINCT warehouse_name) AS affected_wh
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                        WHERE start_time >= DATEADD('hours',-12,CURRENT_TIMESTAMP())
                          AND {failed_pred_plain}
                          {wh_filter_m} {get_db_filter_clause("database_name", company)} {get_user_filter_clause("user_name", company)}
                        GROUP BY query_type ORDER BY fail_count DESC
                    """,
                    "long_queries": f"""
                        SELECT query_id, user_name, warehouse_name,
                               SUBSTR(query_text,1,100) AS query_preview,
                               total_elapsed_time/1000  AS elapsed_sec,
                               execution_status
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                        WHERE start_time >= DATEADD('hours',-12,CURRENT_TIMESTAMP())
                          AND warehouse_name IS NOT NULL
                          {wh_filter_m} {get_db_filter_clause("database_name", company)} {get_user_filter_clause("user_name", company)}
                        ORDER BY total_elapsed_time DESC LIMIT 10
                    """,
                    "credits": f"""
                        SELECT SUM(credits_used) AS overnight_credits
                        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                        WHERE start_time >= DATEADD('hours',-12,CURRENT_TIMESTAMP())
                          {wh_filter_m}
                    """,
                }
                morning_mart_queries = {
                    "failures": build_mart_account_health_failure_types_sql(12, company),
                    "long_queries": build_mart_account_health_long_queries_sql(12, company, limit=10),
                    "credits": build_mart_account_health_credits_sql(12, company),
                }
                morning_source = "OVERWATCH mart facts" if morning_mart_ok else f"Live fallback: {morning_mart_reason}"
                for key, live_sql in morning_live_queries.items():
                    try:
                        if morning_mart_ok:
                            md[key] = run_query(
                                morning_mart_queries[key],
                                ttl_key=f"account_health_morning_mart_{company}_{key}",
                                tier="historical",
                                section="Account Health",
                            )
                        else:
                            raise RuntimeError(morning_mart_reason)
                    except Exception as mart_exc:
                        try:
                            md[key] = run_query(
                                live_sql,
                                ttl_key=f"account_health_morning_live_{company}_{key}",
                                tier="recent",
                                section="Account Health",
                            )
                            if morning_mart_ok:
                                morning_source = f"Live fallback: {format_snowflake_error(mart_exc)}"
                        except Exception:
                            md[key] = pd.DataFrame()
                md["_source"] = morning_source
                st.session_state["morning_data"] = md
                st.session_state["morning_data_source"] = morning_source
                st.session_state["morning_data_meta"] = _account_health_scope_meta(
                    company, environment, window="12h"
                )

        if st.session_state.get("morning_data"):
            md = st.session_state["morning_data"]
            overnight_cr = safe_float(
                md["credits"].iloc[0].get("OVERNIGHT_CREDITS", md["credits"].iloc[0].get("PERIOD_CREDITS", 0))
            ) if not md["credits"].empty else 0
            st.metric("Overnight Credits (12h)", format_credits(overnight_cr))
            if md.get("_source"):
                st.caption(f"Source: {md['_source']}")
            if not md["failures"].empty:
                st.subheader("❌ Overnight Failures by Type")
                render_priority_dataframe(
                    md["failures"],
                    title="Overnight failure groups",
                    priority_columns=["QUERY_TYPE", "FAIL_COUNT", "AFFECTED_USERS", "AFFECTED_WH"],
                    sort_by=["FAIL_COUNT", "AFFECTED_USERS", "AFFECTED_WH"],
                    ascending=[False, False, False],
                    raw_label="All overnight failure groups",
                )
                download_csv(md["failures"], "morning_failures.csv")
            else:
                st.success("No query failures overnight")
            if not md["long_queries"].empty:
                st.subheader("🐌 Longest Running Queries")
                render_priority_dataframe(
                    md["long_queries"],
                    title="Longest overnight queries",
                    priority_columns=[
                        "QUERY_ID",
                        "USER_NAME",
                        "WAREHOUSE_NAME",
                        "ELAPSED_SEC",
                        "EXECUTION_STATUS",
                        "QUERY_PREVIEW",
                    ],
                    sort_by=["ELAPSED_SEC"],
                    ascending=False,
                    raw_label="All long overnight query rows",
                )
                download_csv(md["long_queries"], "morning_long_queries.csv")
            brief_lines = [
                "# OVERWATCH Morning Brief",
                f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"Overnight credits: {format_credits(overnight_cr)}",
                f"Failure groups: {0 if md['failures'].empty else len(md['failures'])}",
                f"Long-query watchlist: {0 if md['long_queries'].empty else len(md['long_queries'])}",
            ]
            st.download_button(
                "Export Morning Brief",
                "\n".join(brief_lines),
                file_name=f"overwatch_morning_brief_{datetime.now().strftime('%Y%m%d')}.md",
                mime="text/markdown",
                key="morning_brief_export",
            )

    # ── EXECUTIVE BRIEFING (NEW) ───────────────────────────────────────────────
    with tab_briefing:
        st.header("Executive Briefing")
        st.caption(
            "Plain-English summary generated by Cortex AI from live OVERWATCH data. "
            "Designed to be copied into an email or Teams message to leadership — no dashboard login required."
        )

        briefing_window = st.selectbox(
            "Report window",
            ["Last 24 hours", "Last 7 days", "Last 30 days"],
            key="br_window",
        )

        hours_map = {"Last 24 hours": 24, "Last 7 days": 168, "Last 30 days": 720}
        br_hours  = hours_map[briefing_window]

        if st.button("Generate Executive Briefing", key="br_generate", type="primary"):
            with st.spinner("Collecting metrics and generating briefing via Cortex AI..."):
                br_data = {}

                # ── Collect metrics ────────────────────────────────────────────
                briefing_mart_ok, briefing_mart_reason = _can_use_control_room_mart(company)
                metric_queries = {
                    "credits": f"""
                        SELECT SUM(CASE WHEN start_time >= DATEADD('hours',-{br_hours},CURRENT_TIMESTAMP())
                                        AND start_time <  CURRENT_TIMESTAMP()
                                   THEN credits_used ELSE 0 END) AS period_credits,
                               SUM(CASE WHEN start_time >= DATEADD('hours',-{br_hours*2},CURRENT_TIMESTAMP())
                                        AND start_time <  DATEADD('hours',-{br_hours},CURRENT_TIMESTAMP())
                                   THEN credits_used ELSE 0 END) AS prior_period_credits
                        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                        WHERE start_time >= DATEADD('hours',-{br_hours*2},CURRENT_TIMESTAMP())
                          AND start_time <  CURRENT_TIMESTAMP()
                          {wh_filter_m}
                    """,
                    "failures": f"""
                        SELECT COUNT(*) AS fail_count
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                        WHERE start_time >= DATEADD('hours',-{br_hours},CURRENT_TIMESTAMP())
                          AND {failed_pred_plain}
                          {wh_filter_m} {get_db_filter_clause("database_name", company)} {get_user_filter_clause("user_name", company)}
                    """,
                    "top_driver": f"""
                        WITH {build_metered_credit_cte(hours_back=br_hours, include_recent=True)}
                        SELECT q.user_name, q.warehouse_name,
                               ROUND(SUM(COALESCE(pqc.metered_credits,0)),2) AS credits
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                        WHERE q.start_time >= DATEADD('hours',-{br_hours},CURRENT_TIMESTAMP())
                          AND q.warehouse_name IS NOT NULL
                          {wh_filter_q} {db_filter_q} {user_filter_q}
                        GROUP BY q.user_name, q.warehouse_name
                        ORDER BY credits DESC LIMIT 1
                    """,
                    "failed_tasks": _task_failure_sql_or_empty(
                        session,
                        f"scheduled_time >= DATEADD('hours',-{int(br_hours)},CURRENT_TIMESTAMP())",
                        1,
                        company,
                    ),
                    "storage": f"""
                        SELECT COALESCE(
                            ROUND(SUM(COALESCE(average_database_bytes,0)+COALESCE(average_failsafe_bytes,0))/POWER(1024,4),2),
                            0
                        ) AS storage_tb
                        FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
                        WHERE usage_date = (SELECT MAX(usage_date)
                                            FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY)
                          {get_db_filter_clause("database_name", company)}
                    """,
                    "queued": f"""
                        SELECT {queued_count_expr_q} AS queued
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        WHERE q.start_time >= DATEADD('hours', -1, CURRENT_TIMESTAMP())
                          AND UPPER(q.execution_status) IN ('RUNNING','QUEUED','BLOCKED')
                          {wh_filter_q} {db_filter_q} {user_filter_q}
                    """,
                }
                mart_metric_queries = {
                    "credits": build_mart_account_health_credits_sql(br_hours, company),
                    "failures": build_mart_account_health_failure_count_sql(br_hours, company),
                    "top_driver": build_mart_account_health_top_driver_sql(br_hours, company),
                    "failed_tasks": build_mart_control_room_task_failures_sql(br_hours, company),
                    "storage": build_mart_account_health_storage_sql(company),
                    "queued": build_mart_account_health_queued_sql(1, company),
                }
                briefing_source = "OVERWATCH mart facts" if briefing_mart_ok else f"Live fallback: {briefing_mart_reason}"

                for k, sql in metric_queries.items():
                    try:
                        if briefing_mart_ok:
                            br_data[k] = run_query(
                                mart_metric_queries[k],
                                ttl_key=f"account_health_brief_mart_{company}_{k}_{br_hours}",
                                tier="historical",
                                section="Account Health",
                            )
                        else:
                            raise RuntimeError(briefing_mart_reason)
                    except Exception as mart_exc:
                        try:
                            br_data[k] = run_query(
                                sql,
                                ttl_key=f"account_health_brief_live_{company}_{k}_{br_hours}",
                                tier="recent",
                                section="Account Health",
                            )
                            if briefing_mart_ok:
                                briefing_source = f"Live fallback: {format_snowflake_error(mart_exc)}"
                        except Exception:
                            br_data[k] = pd.DataFrame()

                # Contract utilization
                try:
                    if briefing_mart_ok:
                        try:
                            df_ytd = run_query(
                                build_mart_account_health_ytd_credits_sql(company),
                                ttl_key=f"account_health_brief_contract_ytd_mart_{company}",
                                tier="historical",
                                section="Account Health",
                            )
                        except Exception:
                            ytd_source = "SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY" if company == "ALL" else "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
                            ytd_filter = "" if company == "ALL" else wh_filter_m
                            df_ytd = run_query(f"""
                                SELECT SUM(credits_used) AS ytd_credits
                                FROM {ytd_source}
                                WHERE start_time >= DATE_TRUNC('year', CURRENT_DATE())
                                  AND start_time < DATEADD('hour', -24, CURRENT_TIMESTAMP())
                                  {ytd_filter}
                            """, ttl_key=f"account_health_brief_contract_ytd_live_{company}", tier="historical", section="Account Health")
                    else:
                        ytd_source = "SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY" if company == "ALL" else "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
                        ytd_filter = "" if company == "ALL" else wh_filter_m
                        df_ytd = run_query(f"""
                            SELECT SUM(credits_used) AS ytd_credits
                            FROM {ytd_source}
                            WHERE start_time >= DATE_TRUNC('year', CURRENT_DATE())
                              AND start_time < DATEADD('hour', -24, CURRENT_TIMESTAMP())
                              {ytd_filter}
                        """, ttl_key=f"account_health_brief_contract_ytd_live_{company}", tier="historical", section="Account Health")
                    committed = st.session_state.get("cc_committed_credits", 100000)
                    ytd       = safe_float(df_ytd["YTD_CREDITS"].iloc[0]) if not df_ytd.empty else 0
                    br_data["contract_pct"] = (ytd / committed * 100) if committed > 0 else None
                except Exception:
                    br_data["contract_pct"] = None

                # ── Extract values ────────────────────────────────────────────
                cr24     = safe_float(br_data["credits"]["PERIOD_CREDITS"].iloc[0]) if not br_data["credits"].empty else 0
                cr_prior = safe_float(br_data["credits"]["PRIOR_PERIOD_CREDITS"].iloc[0]) if not br_data["credits"].empty else 0
                failures = safe_int(br_data["failures"]["FAIL_COUNT"].iloc[0]) if not br_data["failures"].empty else 0
                stor_tb  = safe_float(br_data["storage"]["STORAGE_TB"].iloc[0]) if not br_data["storage"].empty else 0
                queued   = safe_int(br_data["queued"]["QUEUED"].iloc[0]) if not br_data["queued"].empty else 0

                top_driver      = ""
                top_driver_cost = 0.0
                if not br_data["top_driver"].empty:
                    td = br_data["top_driver"].iloc[0]
                    top_driver      = f"{td.get('USER_NAME','')} on {td.get('WAREHOUSE_NAME','')}"
                    top_driver_cost = credits_to_dollars(safe_float(td.get("CREDITS",0)), credit_price)

                failed_task = ""
                if not br_data["failed_tasks"].empty:
                    failed_task = str(br_data["failed_tasks"]["TASK_NAME"].iloc[0])

                metric_payload = {
                    "cr24": cr24, "cr_prior": cr_prior,
                    "failures": failures, "queued": queued,
                    "stor_tb": stor_tb,
                    "contract_pct": br_data.get("contract_pct"),
                    "top_driver": top_driver,
                    "top_driver_cost": top_driver_cost,
                    "failed_task": failed_task,
                }

                # ── Call Cortex ────────────────────────────────────────────────
                prompt = _build_briefing_prompt(metric_payload, credit_price, company)
                prompt_esc = prompt.replace("'", "''")

                try:
                    result = session.sql(
                        f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', '{prompt_esc}') AS briefing"
                    ).collect()
                    briefing_text = result[0]["BRIEFING"] or ""
                except Exception as e:
                    # Graceful fallback: structured text brief if Cortex unavailable.
                    cr_delta = ((cr24 - cr_prior) / cr_prior * 100) if cr_prior > 0 else 0
                    briefing_text = (
                        f"OVERWATCH Executive Briefing - {datetime.now().strftime('%B %d, %Y')}\n\n"
                        f"ALFA Insurance Snowflake consumed {cr24:,.0f} credits "
                        f"(${credits_to_dollars(cr24, credit_price):,.2f}) "
                        f"over the {briefing_window.lower()}, "
                        f"{'up' if cr_delta > 0 else 'down'} {abs(cr_delta):.1f}% vs the prior period. "
                        f"The top cost driver was {top_driver} at ${top_driver_cost:,.2f}. "
                        f"There were {failures} query failures recorded. "
                        f"Storage stands at {stor_tb:.1f} TB.\n\n"
                        f"(Cortex AI unavailable: {format_snowflake_error(e)}. Plain summary generated from raw metrics.)"
                    )

                st.session_state["ah_briefing_text"] = briefing_text
                st.session_state["ah_briefing_ts"]   = datetime.now().strftime("%Y-%m-%d %H:%M")
                st.session_state["ah_briefing_window"] = briefing_window
                st.session_state["ah_briefing_source"] = briefing_source
                st.session_state["ah_briefing_meta"] = _account_health_scope_meta(
                    company, environment, window=briefing_window
                )

        # ── Render briefing ────────────────────────────────────────────────────
        if st.session_state.get("ah_briefing_text"):
            briefing_text   = st.session_state["ah_briefing_text"]
            briefing_ts     = st.session_state.get("ah_briefing_ts", "")
            briefing_window = st.session_state.get("ah_briefing_window", "")
            briefing_source = st.session_state.get("ah_briefing_source", "Live fallback")
            safe_briefing_text = html.escape(str(briefing_text))
            safe_company = html.escape(str(company))
            safe_window = html.escape(str(briefing_window))
            safe_ts = html.escape(str(briefing_ts))
            safe_source = html.escape(str(briefing_source))

            st.divider()

            # Visual card
            st.markdown(f"""
            <div style="background:rgba(56,189,248,0.05);border:1px solid rgba(56,189,248,0.2);
                        border-radius:12px;padding:24px;margin:8px 0;">
                <div style="font-size:0.7rem;color:#64748b;margin-bottom:12px;letter-spacing:1px;text-transform:uppercase;">
                    OVERWATCH Executive Briefing - {safe_company} - {safe_window} - Generated {safe_ts} - Source {safe_source}
                </div>
                <div style="color:#e2e8f0;font-size:0.95rem;line-height:1.7;white-space:pre-wrap;">{safe_briefing_text}</div>
            </div>
            """, unsafe_allow_html=True)

            # Export options
            st.divider()
            st.subheader("Export & Share")
            col_e1, col_e2, col_e3 = st.columns(3)

            # Plain text download
            full_text = (
                f"OVERWATCH Executive Briefing\n"
                f"Company: {company}\n"
                f"Period: {briefing_window}\n"
                f"Generated: {briefing_ts}\n"
                f"{'-'*60}\n\n"
                f"{briefing_text}\n\n"
                f"{'-'*60}\n"
                f"Source: OVERWATCH V3 - Snowflake DBA Command Center\n"
                f"Data from: SNOWFLAKE.ACCOUNT_USAGE\n"
            )
            with col_e1:
                st.download_button(
                    "Download .txt",
                    full_text,
                    file_name=f"overwatch_executive_brief_{datetime.now().strftime('%Y%m%d')}.txt",
                    mime="text/plain",
                    key="br_dl_txt",
                    use_container_width=True,
                )

            # Markdown download
            md_text = (
                f"# OVERWATCH Executive Briefing\n\n"
                f"**Company:** {company}  \n"
                f"**Period:** {briefing_window}  \n"
                f"**Generated:** {briefing_ts}  \n\n"
                f"---\n\n"
                f"{briefing_text}\n\n"
                f"---\n\n"
                f"*Generated by OVERWATCH V3 - Snowflake DBA Command Center*\n"
            )
            with col_e2:
                st.download_button(
                    "Download .md",
                    md_text,
                    file_name=f"overwatch_brief_{datetime.now().strftime('%Y%m%d')}.md",
                    mime="text/markdown",
                    key="br_dl_md",
                    use_container_width=True,
                )

            # Copy-ready Teams/email text
            with col_e3:
                if st.button("Copy to clipboard", key="br_copy", use_container_width=True):
                    st.code(briefing_text, language=None)
                    st.caption("Select all text above and copy.")

            # Regenerate note
            st.caption(
                "Tip: set your annual committed credits in Cost & Contract -> Contract Utilization "
                "before generating the briefing to include contract pacing in the narrative."
            )
