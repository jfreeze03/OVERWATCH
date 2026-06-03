# sections/warehouse_health.py - Warehouse stats, scaling events, idle detection, spill, heatmap
from datetime import datetime

import streamlit as st
import pandas as pd
from utils.workflows import render_operator_briefing, render_priority_dataframe, render_workflow_selector
from utils import (
    get_session_for_action, format_credits,
    download_csv, render_drillable_bar_chart, get_wh_filter_clause,
    get_active_company, get_active_environment, get_environment_filter_clause, get_global_filter_clause,
    metric_confidence_label, freshness_note,
    build_metered_credit_cte, make_action_id, upsert_actions,
    run_query, format_snowflake_error, filter_existing_columns, render_optimization_advisor,
    build_mart_warehouse_overview_sql, build_mart_warehouse_scaling_sql,
    build_mart_warehouse_heatmap_sql,
    mart_object_name, resolve_owner_context, safe_float, safe_identifier, safe_int, sql_literal,
    action_queue_environment_clause,
)
from utils.admin import ADMIN_AUDIT_FQN
from config import ALERT_DB, ALERT_SCHEMA, ACTION_QUEUE_TABLE, THRESHOLDS


WAREHOUSE_HEALTH_VIEWS = (
    "Overview & Scaling",
    "Efficiency",
    "Spill & Memory",
    "Workload Heatmap",
    "Optimization Advisor",
)

WAREHOUSE_HEALTH_DETAILS = {
    "Overview & Scaling": "Warehouse volume, latency, spill, cache, and metering events.",
    "Efficiency": "Credits per query, queue per credit, spill per credit, and scorecard.",
    "Spill & Memory": "Local and remote spill drilldowns by warehouse.",
    "Workload Heatmap": "Concurrency by warehouse, day, and hour.",
    "Optimization Advisor": "Actionable sizing, suspend, spill, and reliability recommendations.",
}

WAREHOUSE_SETTING_REVIEW_TABLE = "OVERWATCH_WAREHOUSE_SETTING_REVIEW"
WAREHOUSE_OPERABILITY_FACT_TABLE = "FACT_WAREHOUSE_OPERABILITY_DAILY"
WAREHOUSE_SCOPE_FILTER_KEYS = (
    "global_warehouse",
    "global_user",
    "global_role",
    "global_database",
    "global_start_date",
    "global_end_date",
)


def _warehouse_action_session(action: str):
    return get_session_for_action(
        action,
        surface="Warehouse Health",
        offline_note="Warehouse shell, source summaries, and cached evidence remain visible without a live connection.",
    )


def warehouse_setting_review_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = WAREHOUSE_SETTING_REVIEW_TABLE,
) -> str:
    return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}"


def build_warehouse_setting_review_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = WAREHOUSE_SETTING_REVIEW_TABLE,
) -> str:
    fqn = warehouse_setting_review_fqn(db=db, schema=schema, table=table)
    return f"""CREATE TABLE IF NOT EXISTS {fqn} (
    SNAPSHOT_ID                  VARCHAR(64),
    SNAPSHOT_TS                  TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    COMPANY                      VARCHAR(100),
    ENVIRONMENT                  VARCHAR(100),
    WAREHOUSE_NAME               VARCHAR(300),
    SEVERITY                     VARCHAR(40),
    SIGNAL                       VARCHAR(120),
    OWNER                        VARCHAR(200),
    ESCALATION_TARGET            VARCHAR(200),
    OWNER_SOURCE                 VARCHAR(200),
    APPROVER                     VARCHAR(200),
    APPROVAL_REQUIRED            VARCHAR(20),
    ROLLBACK_REQUIRED            VARCHAR(20),
    SAFE_CHANGE_PATH             VARCHAR(4000),
    SETTING_CHANGE_CANDIDATE     VARCHAR(4000),
    CHANGE_RISK                  VARCHAR(2000),
    POST_CHANGE_VERIFICATION     VARCHAR(2000),
    PRESSURE_EVIDENCE            VARCHAR(2000),
    BASELINE_CAPACITY_SCORE      FLOAT,
    BASELINE_QUEUED_QUERIES      NUMBER,
    BASELINE_SPILL_QUERIES       NUMBER,
    BASELINE_HIGH_LATENCY_QUERIES NUMBER,
    BASELINE_P95_ELAPSED_SEC     FLOAT,
    BASELINE_METERED_CREDITS     FLOAT,
    VERIFICATION_QUERY           VARCHAR(8000),
    GENERATED_REVIEW_SQL         VARCHAR(8000),
    SAVINGS_VERIFICATION_REQUIRED VARCHAR(20),
    APPROVAL_STATE               VARCHAR(80),
    CHANGE_TICKET_ID             VARCHAR(200),
    CURRENT_SETTINGS_JSON        VARCHAR(8000),
    PROPOSED_SETTINGS_JSON       VARCHAR(8000),
    ROLLBACK_SQL                 VARCHAR(8000),
    EXECUTED_SQL_HASH            VARCHAR(80),
    EXECUTION_STATUS             VARCHAR(80),
    EXECUTED_BY                  VARCHAR(200),
    EXECUTED_AT                  TIMESTAMP_NTZ,
    POST_CHANGE_VERIFICATION_STATUS VARCHAR(80),
    POST_CHANGE_VERIFICATION_RESULT VARCHAR(4000),
    VERIFIED_MONTHLY_SAVINGS    FLOAT,
    AUDIT_READINESS              VARCHAR(100),
    AUDIT_BLOCKERS               VARCHAR(2000),
    NEXT_CONTROL_ACTION          VARCHAR(4000),
    SOURCE                       VARCHAR(500)
);"""


def build_warehouse_setting_review_migration_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = WAREHOUSE_SETTING_REVIEW_TABLE,
) -> list[str]:
    """Return additive migrations for deployed warehouse setting review tables."""
    fqn = warehouse_setting_review_fqn(db=db, schema=schema, table=table)
    return [
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS APPROVAL_STATE VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CHANGE_TICKET_ID VARCHAR(200)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CURRENT_SETTINGS_JSON VARCHAR(8000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS PROPOSED_SETTINGS_JSON VARCHAR(8000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS ROLLBACK_SQL VARCHAR(8000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS EXECUTED_SQL_HASH VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS EXECUTION_STATUS VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS EXECUTED_BY VARCHAR(200)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS EXECUTED_AT TIMESTAMP_NTZ",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS POST_CHANGE_VERIFICATION_STATUS VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS POST_CHANGE_VERIFICATION_RESULT VARCHAR(4000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS VERIFIED_MONTHLY_SAVINGS FLOAT",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS AUDIT_READINESS VARCHAR(100)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS AUDIT_BLOCKERS VARCHAR(2000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS NEXT_CONTROL_ACTION VARCHAR(4000)",
    ]


def warehouse_operability_fact_fqn(table: str = WAREHOUSE_OPERABILITY_FACT_TABLE) -> str:
    return mart_object_name(table)


def _scope_value(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value).strip()


def _warehouse_scope_meta(
    company: str,
    environment: str,
    days: int | None = None,
    state: dict | None = None,
) -> dict:
    """Return the filter scope that loaded Warehouse Health evidence must match."""
    state = state if state is not None else st.session_state
    meta = {
        "company": _scope_value(company),
        "environment": _scope_value(environment),
    }
    if days is not None:
        meta["days"] = int(days)
    for key in WAREHOUSE_SCOPE_FILTER_KEYS:
        meta[key] = _scope_value(state.get(key))
    return meta


def _warehouse_meta_matches(meta: dict | None, expected: dict | None) -> bool:
    if not isinstance(meta, dict) or not isinstance(expected, dict):
        return False
    for key, expected_value in expected.items():
        actual = meta.get(key)
        if key == "days":
            try:
                if int(actual) != int(expected_value):
                    return False
            except Exception:
                return False
        elif _scope_value(actual) != _scope_value(expected_value):
            return False
    return True


def _warehouse_sql_exprs(session) -> dict[str, str]:
    """Resolve optional ACCOUNT_USAGE columns only when a live query is requested."""
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "WAREHOUSE_SIZE",
            "QUEUED_OVERLOAD_TIME",
            "BYTES_SPILLED_TO_LOCAL_STORAGE",
            "BYTES_SPILLED_TO_REMOTE_STORAGE",
            "PERCENTAGE_SCANNED_FROM_CACHE",
            "BYTES_SCANNED",
        ],
    ))
    wm_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
        ["CREDITS_USED_COMPUTE", "CREDITS_USED_CLOUD_SERVICES"],
    ))
    return {
        "wh_size_expr": "MAX(q.warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR",
        "plain_wh_size_expr": "MAX(warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR",
        "latest_size_expr": "q.warehouse_size" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR",
        "queue_avg_expr": "AVG(q.queued_overload_time)/1000" if "QUEUED_OVERLOAD_TIME" in qh_cols else "0",
        "queue_sum_expr": "SUM(q.queued_overload_time)" if "QUEUED_OVERLOAD_TIME" in qh_cols else "0",
        "remote_spill_sum_expr": (
            "SUM(q.bytes_spilled_to_remote_storage)"
            if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
            else "0"
        ),
        "local_spill_expr": (
            "SUM(bytes_spilled_to_local_storage)"
            if "BYTES_SPILLED_TO_LOCAL_STORAGE" in qh_cols
            else "0"
        ),
        "local_spill_row_expr": (
            "bytes_spilled_to_local_storage"
            if "BYTES_SPILLED_TO_LOCAL_STORAGE" in qh_cols
            else "0"
        ),
        "remote_spill_expr": (
            "SUM(bytes_spilled_to_remote_storage)"
            if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
            else "0"
        ),
        "remote_spill_row_expr": (
            "bytes_spilled_to_remote_storage"
            if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
            else "0"
        ),
        "cache_expr": "AVG(q.percentage_scanned_from_cache)" if "PERCENTAGE_SCANNED_FROM_CACHE" in qh_cols else "0",
        "bytes_scanned_expr": "SUM(q.bytes_scanned)" if "BYTES_SCANNED" in qh_cols else "0",
        "compute_meter_expr": "m.credits_used_compute" if "CREDITS_USED_COMPUTE" in wm_cols else "m.credits_used",
        "cloud_meter_expr": "m.credits_used_cloud_services" if "CREDITS_USED_CLOUD_SERVICES" in wm_cols else "0::FLOAT",
    }


def _frame_row_count(frame) -> int:
    return len(frame) if isinstance(frame, pd.DataFrame) else 0


def _source_confidence(source: str, default: str) -> str:
    source_lower = str(source or "").lower()
    if "mart" in source_lower or "fact_" in source_lower:
        return "Pre-aggregated"
    if "fallback" in source_lower:
        return "Live fallback"
    if "account_usage" in source_lower:
        return "Live ACCOUNT_USAGE"
    return default


def _source_next_action(state: str, source: str) -> str:
    source_lower = str(source or "").lower()
    if state == "Stale":
        return "Reload after changing company, environment, lookback, or global filters."
    if state == "Unavailable":
        return "Deploy or refresh the mart/grants before relying on this surface."
    if state == "Not Loaded":
        return "Load only when this workflow is part of the current DBA investigation."
    if state == "No Rows":
        return "Confirm the selected scope has recent warehouse activity or mart rows."
    if "fallback" in source_lower:
        return "Use for investigation; prefer mart refresh for repeated daily control."
    return "Current for the active DBA scope."


def _warehouse_source_health_rows(
    state: dict,
    company: str,
    environment: str,
) -> pd.DataFrame:
    """Summarize Warehouse Health evidence freshness and source strategy."""
    definitions = [
        {
            "surface": "Capacity brief",
            "frame_key": "wh_capacity_summary",
            "meta_key": "wh_capacity_meta",
            "days_key": "wh_capacity_days",
            "default_days": 7,
            "source": "Live ACCOUNT_USAGE: QUERY_HISTORY + WAREHOUSE_METERING_HISTORY",
            "confidence": "Live aggregate",
        },
        {
            "surface": "Operability fact",
            "frame_key": "wh_operability_fact",
            "meta_key": "wh_capacity_meta",
            "days_key": "wh_capacity_days",
            "default_days": 7,
            "source": f"OVERWATCH mart: {WAREHOUSE_OPERABILITY_FACT_TABLE}",
            "confidence": "Pre-aggregated",
            "error_key": "wh_operability_fact_error",
        },
        {
            "surface": "Overview",
            "frame_key": "wh_df_wh",
            "source_key": "wh_df_wh_source",
            "meta_key": "wh_df_wh_meta",
            "days_key": "wh_days",
            "default_days": 7,
            "source": "OVERWATCH mart or live warehouse overview",
            "confidence": "Mixed",
        },
        {
            "surface": "Scaling events",
            "frame_key": "wh_scaling",
            "source_key": "wh_scaling_source",
            "meta_key": "wh_scaling_meta",
            "days_key": "wh_days",
            "default_days": 7,
            "source": "OVERWATCH mart or live WAREHOUSE_METERING_HISTORY",
            "confidence": "Mixed",
        },
        {
            "surface": "Efficiency",
            "frame_key": "wh_efficiency",
            "meta_key": "wh_efficiency_meta",
            "days_key": "wh_eff_days",
            "default_days": 7,
            "source": "Live ACCOUNT_USAGE + allocated per-query credits",
            "confidence": "Allocated",
        },
        {
            "surface": "Spill & memory",
            "frame_key": "wh_df_sp",
            "meta_key": "wh_df_sp_meta",
            "days_key": "sp_days",
            "default_days": 7,
            "source": "Live ACCOUNT_USAGE.QUERY_HISTORY",
            "confidence": "Live ACCOUNT_USAGE",
        },
        {
            "surface": "Workload heatmap",
            "frame_key": "wh_df_hm",
            "meta_key": "wh_df_hm_meta",
            "days_key": "hm_days",
            "default_days": 30,
            "source": "Live ACCOUNT_USAGE.QUERY_HISTORY",
            "confidence": "Live ACCOUNT_USAGE",
        },
        {
            "surface": "Ownership readiness",
            "frame_key": "wh_owner_inventory",
            "meta_key": "wh_owner_inventory_meta",
            "days_key": "wh_owner_inventory_days",
            "default_days": 30,
            "source": "Warehouse owner directory + tag evidence",
            "confidence": "Governed metadata",
        },
        {
            "surface": "Closure analytics",
            "frame_key": "wh_action_closure",
            "meta_key": "wh_action_closure_meta",
            "days_key": "wh_action_closure_days",
            "default_days": 30,
            "source": "Action queue closure evidence",
            "confidence": "Workflow evidence",
        },
        {
            "surface": "Execution audit",
            "frame_key": "wh_setting_execution_audit",
            "meta_key": "wh_setting_execution_audit_meta",
            "days": 30,
            "source": "Warehouse setting review + DBA admin audit",
            "confidence": "Audit evidence",
        },
    ]
    rows = []
    for item in definitions:
        source_key = item.get("source_key")
        source = str((state.get(source_key, item["source"]) if source_key else item["source"]) or item["source"])
        frame = state.get(item["frame_key"])
        error_key = item.get("error_key")
        error = state.get(error_key) if error_key else None
        days_key = item.get("days_key")
        days = item["days"] if "days" in item else (state.get(days_key, item.get("default_days")) if days_key else item.get("default_days"))
        expected_meta = _warehouse_scope_meta(company, environment, days=days, state=state)
        loaded = isinstance(frame, pd.DataFrame)
        if error:
            status = "Unavailable"
        elif not loaded:
            status = "Not Loaded"
        elif not _warehouse_meta_matches(state.get(item["meta_key"]), expected_meta):
            status = "Stale"
        elif frame.empty:
            status = "No Rows"
        else:
            status = "Loaded"
        state_rank = {
            "Unavailable": 0,
            "Stale": 1,
            "Loaded": 2,
            "No Rows": 3,
            "Not Loaded": 4,
        }.get(status, 9)
        rows.append({
            "SURFACE": item["surface"],
            "STATE": status,
            "STATE_RANK": state_rank,
            "SOURCE": source,
            "CONFIDENCE": _source_confidence(source, item["confidence"]),
            "ROWS": _frame_row_count(frame),
            "SCOPE": (
                f"{company} / {environment} / {int(days)}d"
                if days is not None
                else f"{company} / {environment}"
            ),
            "NEXT_ACTION": _source_next_action(status, source),
        })
    return pd.DataFrame(rows)


def build_warehouse_operability_fact_ddl(table: str = WAREHOUSE_OPERABILITY_FACT_TABLE) -> str:
    fqn = warehouse_operability_fact_fqn(table=table)
    return f"""CREATE TRANSIENT TABLE IF NOT EXISTS {fqn} (
    SNAPSHOT_DATE              DATE,
    COMPANY                    VARCHAR(100),
    ENVIRONMENT                VARCHAR(100),
    WAREHOUSE_NAME             VARCHAR(300),
    CONTROL_SOURCE             VARCHAR(80),
    SEVERITY                   VARCHAR(40),
    SIGNAL                     VARCHAR(120),
    CONTROL_STATE              VARCHAR(120),
    CONTROL_RANK               NUMBER,
    CAPACITY_SCORE             FLOAT,
    QUERY_ROWS                 NUMBER,
    QUEUE_PRESSURE_ROWS        NUMBER,
    SPILL_PRESSURE_ROWS        NUMBER,
    HIGH_LATENCY_ROWS          NUMBER,
    METERED_CREDITS            FLOAT,
    CREDIT_ALLOCATION_METHOD   VARCHAR(160),
    REVIEW_ROWS                NUMBER,
    APPROVAL_REQUIRED_ROWS     NUMBER,
    ROLLBACK_REQUIRED_ROWS     NUMBER,
    SAVINGS_VERIFICATION_ROWS  NUMBER,
    OPEN_ACTIONS               NUMBER,
    OVERDUE_OPEN               NUMBER,
    FIXED_WITHOUT_VERIFICATION NUMBER,
    VERIFIED_CLOSURES          NUMBER,
    OWNER_APPROVAL_GAP_ROWS    NUMBER,
    NEXT_CONTROL_ACTION        VARCHAR(4000),
    LAST_ACTIVITY_TS           TIMESTAMP_NTZ,
    LOAD_TS                    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);"""


def build_warehouse_operability_fact_migration_sql(
    table: str = WAREHOUSE_OPERABILITY_FACT_TABLE,
) -> list[str]:
    fqn = warehouse_operability_fact_fqn(table=table)
    return [
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_SOURCE VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS SIGNAL VARCHAR(120)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_STATE VARCHAR(120)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_RANK NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CAPACITY_SCORE FLOAT",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS QUERY_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS QUEUE_PRESSURE_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS SPILL_PRESSURE_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS HIGH_LATENCY_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CREDIT_ALLOCATION_METHOD VARCHAR(160)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS REVIEW_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS OWNER_APPROVAL_GAP_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS NEXT_CONTROL_ACTION VARCHAR(4000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS LAST_ACTIVITY_TS TIMESTAMP_NTZ",
    ]


def _warehouse_capacity_score(
    queued_queries: int,
    spill_queries: int,
    high_latency_queries: int,
    total_queries: int,
    credit_spike_pct: float,
) -> int:
    total = max(int(total_queries or 0), 1)
    queue_pct = safe_float(queued_queries) / total * 100
    spill_pct = safe_float(spill_queries) / total * 100
    latency_pct = safe_float(high_latency_queries) / total * 100
    spike_pct = max(safe_float(credit_spike_pct), 0)
    penalty = (
        min(queue_pct * 2.0, 28)
        + min(spill_pct * 1.8, 24)
        + min(latency_pct * 1.1, 18)
        + min(spike_pct / 4, 20)
    )
    return max(0, min(100, int(round(100 - penalty))))


def _warehouse_capacity_rating(score: int) -> str:
    if score >= 90:
        return "Healthy"
    if score >= 78:
        return "Watch"
    if score >= 65:
        return "Pressure"
    return "Capacity Risk"


def _warehouse_capacity_action_for(signal: str) -> tuple[str, str]:
    signal = str(signal or "").upper()
    if "QUEUE" in signal:
        return (
            "Review multi-cluster policy, warehouse size, auto-resume latency, and workload routing.",
            "-- Queue pressure: inspect WAREHOUSE_LOAD_HISTORY and top queued QUERY_HISTORY rows.",
        )
    if "SPILL" in signal:
        return (
            "Inspect top spilling queries and consider query rewrites, clustering, or a larger warehouse for this workload.",
            "-- Spill pressure: use GET_QUERY_OPERATOR_STATS for top remote-spill query IDs.",
        )
    if "CREDIT" in signal:
        return (
            "Compare current burn to prior period and confirm whether the spike is business demand, idle time, or runaway workload.",
            "-- Credit spike: reconcile WAREHOUSE_METERING_HISTORY with query-attributed drivers.",
        )
    return (
        "Review p95 latency, query volume, and top query patterns before changing warehouse configuration.",
        "-- Latency pressure: inspect high elapsed query signatures and warehouse load.",
    )


def _warehouse_capacity_verification_sql(
    warehouse_name: str,
    days: int = 7,
    environment: str | None = None,
    company: str | None = None,
) -> str:
    """Build read-only post-change evidence for one warehouse and environment scope."""
    wh = sql_literal(warehouse_name, 300)
    days = max(1, min(int(days or 7), 30))
    env_clause = get_environment_filter_clause(
        "database_name",
        environment=environment,
        company=company,
    )
    return f"""WITH query_window AS (
    SELECT
        warehouse_name,
        COUNT(*) AS total_queries,
        SUM(IFF(
            COALESCE(queued_overload_time, 0)
            + COALESCE(queued_provisioning_time, 0)
            + COALESCE(queued_repair_time, 0) > 0,
            1,
            0
        )) AS queued_queries,
        SUM(IFF(
            COALESCE(bytes_spilled_to_local_storage, 0)
            + COALESCE(bytes_spilled_to_remote_storage, 0) > 0,
            1,
            0
        )) AS spill_queries,
        AVG(total_elapsed_time) / 1000 AS avg_elapsed_sec,
        APPROX_PERCENTILE(total_elapsed_time / 1000, 0.95) AS p95_elapsed_sec,
        MAX(start_time) AS latest_query_time
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
      AND warehouse_name = {wh}
      {env_clause}
    GROUP BY warehouse_name
),
metering_window AS (
    SELECT
        warehouse_name,
        SUM(COALESCE(credits_used_compute, credits_used)) AS metered_credits,
        MAX(end_time) AS latest_metering_time
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
    WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
      AND warehouse_name = {wh}
    GROUP BY warehouse_name
)
SELECT
    COALESCE(q.warehouse_name, m.warehouse_name) AS warehouse_name,
    COALESCE(q.total_queries, 0) AS total_queries,
    COALESCE(q.queued_queries, 0) AS queued_queries,
    COALESCE(q.spill_queries, 0) AS spill_queries,
    ROUND(COALESCE(q.avg_elapsed_sec, 0), 2) AS avg_elapsed_sec,
    ROUND(COALESCE(q.p95_elapsed_sec, 0), 2) AS p95_elapsed_sec,
    ROUND(COALESCE(m.metered_credits, 0), 4) AS metered_credits,
    q.latest_query_time,
    m.latest_metering_time
FROM query_window q
FULL OUTER JOIN metering_window m
  ON m.warehouse_name = q.warehouse_name
ORDER BY metered_credits DESC
LIMIT 50"""


def _warehouse_owner_inventory_sql(days: int, company: str, environment: str = "ALL") -> str:
    """Return recent warehouse usage with owner/cost/environment tag evidence."""
    days = max(1, min(int(days or 30), 90))
    env_clause = get_environment_filter_clause(
        "q.database_name",
        environment=environment,
        company=company,
    )
    return f"""WITH recent_warehouse_usage AS (
    SELECT
        q.warehouse_name,
        MAX(q.warehouse_size) AS warehouse_size,
        COUNT(*) AS query_count,
        COUNT(DISTINCT q.database_name) AS database_count,
        LISTAGG(DISTINCT q.database_name, ', ') WITHIN GROUP (ORDER BY q.database_name) AS database_sample,
        MAX(q.start_time) AS last_query_time
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
    WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
      AND q.warehouse_name IS NOT NULL
      {env_clause}
    GROUP BY q.warehouse_name
),
warehouse_tags AS (
    SELECT
        object_name AS warehouse_name,
        MAX(IFF(
            UPPER(tag_name) IN ('OWNER', 'BUSINESS_OWNER', 'SERVICE_OWNER', 'DATA_OWNER', 'APPLICATION_OWNER'),
            tag_value,
            NULL
        )) AS owner_tag,
        MAX(IFF(
            UPPER(tag_name) IN ('COST_CENTER', 'COSTCENTER', 'DEPARTMENT', 'BILLING_OWNER'),
            tag_value,
            NULL
        )) AS cost_center_tag,
        MAX(IFF(
            UPPER(tag_name) IN ('ENVIRONMENT', 'ENV', 'SNOWFLAKE_ENV'),
            tag_value,
            NULL
        )) AS environment_tag,
        COUNT(*) AS tag_count
    FROM SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES
    WHERE UPPER(COALESCE(domain, '')) = 'WAREHOUSE'
    GROUP BY object_name
)
SELECT
    u.warehouse_name,
    u.warehouse_size,
    u.query_count,
    u.database_count,
    u.database_sample,
    COALESCE(t.owner_tag, '') AS owner_tag,
    COALESCE(t.cost_center_tag, '') AS cost_center_tag,
    COALESCE(t.environment_tag, '') AS environment_tag,
    COALESCE(t.tag_count, 0) AS tag_count,
    u.last_query_time
FROM recent_warehouse_usage u
LEFT JOIN warehouse_tags t
  ON UPPER(t.warehouse_name) = UPPER(u.warehouse_name)
ORDER BY
    IFF(COALESCE(t.owner_tag, '') = '', 0, 1) ASC,
    u.query_count DESC,
    u.warehouse_name
LIMIT 200""".strip()


def _annotate_warehouse_owner_inventory(inventory: pd.DataFrame) -> pd.DataFrame:
    """Add strict DBA ownership readiness to a warehouse inventory dataframe."""
    if inventory is None or inventory.empty:
        return pd.DataFrame() if inventory is None else inventory

    view = inventory.copy()
    view.columns = [str(col).upper() for col in view.columns]
    rows = []
    for _, row in view.iterrows():
        context = _warehouse_owner_context({
            "WAREHOUSE_NAME": row.get("WAREHOUSE_NAME", ""),
            "SIGNAL": "Warehouse Ownership",
        })
        owner_tag = str(row.get("OWNER_TAG") or "").strip()
        cost_tag = str(row.get("COST_CENTER_TAG") or "").strip()
        env_tag = str(row.get("ENVIRONMENT_TAG") or "").strip()
        route_ready = bool(context.get("owner_email")) and bool(
            context.get("oncall_primary") or context.get("approval_group")
        )
        if owner_tag and cost_tag and env_tag and route_ready:
            readiness = "Tagged Owner Ready"
            rank = 0
            next_action = "Use tagged owner plus owner-directory route before approving warehouse setting changes."
        elif owner_tag and route_ready:
            readiness = "Owner Tagged - Tag Gaps"
            rank = 1
            next_action = "Add cost-center and environment tags so finance and environment ownership survive audit."
        elif route_ready:
            readiness = "Directory Route Only"
            rank = 2
            next_action = "Add warehouse owner, cost-center, and environment tags; keep directory route as fallback."
        else:
            readiness = "Owner Route Blocked"
            rank = 3
            next_action = "Assign a named owner route before changing warehouse settings."
        rows.append({
            "OWNER": owner_tag or context.get("owner", ""),
            "OWNER_EMAIL": context.get("owner_email", ""),
            "ONCALL_PRIMARY": context.get("oncall_primary", ""),
            "APPROVAL_GROUP": context.get("approval_group", ""),
            "ESCALATION_TARGET": context.get("escalation", ""),
            "OWNER_SOURCE": "WAREHOUSE_TAG" if owner_tag else context.get("source", ""),
            "OWNER_EVIDENCE": (
                f"owner_tag={owner_tag or 'missing'}; "
                f"cost_center_tag={cost_tag or 'missing'}; "
                f"environment_tag={env_tag or 'missing'}; "
                f"{context.get('owner_evidence', '')}"
            ).strip(),
            "OWNER_ROUTE_READY": "Yes" if route_ready else "No",
            "OWNER_TAG_STATE": "Tagged" if owner_tag else "Missing",
            "COST_CENTER_TAG_STATE": "Tagged" if cost_tag else "Missing",
            "ENVIRONMENT_TAG_STATE": "Tagged" if env_tag else "Missing",
            "GOVERNANCE_READINESS": readiness,
            "GOVERNANCE_RANK": rank,
            "NEXT_OWNER_ACTION": next_action,
        })
    annotated = pd.concat([view.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    return annotated.sort_values(
        ["GOVERNANCE_RANK", "QUERY_COUNT", "WAREHOUSE_NAME"],
        ascending=[False, False, True],
    )


def _warehouse_owner_context(row: pd.Series | dict) -> dict:
    wh = str(row.get("WAREHOUSE_NAME") or "").upper()
    signal = str(row.get("SIGNAL") or "").upper()
    if "CREDIT" in signal:
        base = {
            "owner": "DBA / FinOps Owner",
            "escalation": "FinOps Lead / DBA Lead",
            "source": "Warehouse signal owner map",
        }
    elif any(token in wh for token in ("ETL", "LOAD", "TASK", "PIPE", "AIRFLOW", "DBT")):
        base = {
            "owner": "Data Engineering Owner",
            "escalation": "Pipeline Owner / DBA On-Call",
            "source": "Warehouse name owner hint",
        }
    elif any(token in wh for token in ("BI", "REPORT", "LOOKER", "POWERBI", "TABLEAU")):
        base = {
            "owner": "BI Platform Owner",
            "escalation": "BI Product Owner / DBA Lead",
            "source": "Warehouse name owner hint",
        }
    elif any(token in wh for token in ("DEV", "SAN", "SIT", "PHX", "SEA")):
        base = {
            "owner": "Development Platform Owner",
            "escalation": "DBA Lead",
            "source": "Warehouse name owner hint",
        }
    else:
        base = {
            "owner": "Platform DBA",
            "escalation": "DBA Lead",
            "source": "Default warehouse owner",
        }
    directory_context = resolve_owner_context(
        row,
        entity=wh,
        entity_type="WAREHOUSE",
        owner=base["owner"],
        category=signal or "Warehouse Capacity",
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


def _warehouse_approval_for(row: pd.Series | dict) -> str:
    signal = str(row.get("SIGNAL") or "").upper()
    owner = str(row.get("OWNER") or _warehouse_owner_context(row)["owner"])
    if "CREDIT" in signal:
        return "FinOps Lead / Warehouse Owner"
    if "QUEUE" in signal:
        return f"{owner} / DBA Lead"
    if "SPILL" in signal:
        return f"{owner} / Query Owner"
    return f"{owner} / DBA Lead"


def _warehouse_setting_candidate_for(row: pd.Series) -> dict:
    """Return the reviewed settings lane for a warehouse capacity exception."""
    signal = str(row.get("SIGNAL") or "").upper()
    queued = safe_int(row.get("QUEUED_QUERIES"))
    spill = safe_int(row.get("SPILL_QUERIES"))
    high_latency = safe_int(row.get("HIGH_LATENCY_QUERIES"))
    spike = safe_float(row.get("CREDIT_SPIKE_PCT"))
    p95 = safe_float(row.get("P95_ELAPSED_SEC"))

    if "QUEUE" in signal:
        candidate = "Review MAX_CLUSTER_COUNT, SCALING_POLICY, WAREHOUSE_SIZE, and workload routing."
        safe_path = (
            "Use Warehouse Settings Manager to load current settings, approve any multi-cluster or size change, "
            "capture rollback SQL, then verify queue count and p95 latency."
        )
        risk = "Scaling can improve concurrency but may multiply credit burn or hide workload design problems."
    elif "SPILL" in signal:
        candidate = "Review WAREHOUSE_SIZE only after top spilling queries, clustering, and query shape are inspected."
        safe_path = (
            "Use Query Profile evidence before resizing; if a size change is approved, capture rollback SQL and "
            "verify spill count, p95 latency, and credits after the change."
        )
        risk = "Blind resizing can mask inefficient SQL and permanently raise run-rate cost."
    elif "CREDIT" in signal:
        candidate = "Review AUTO_SUSPEND, MIN_CLUSTER_COUNT, MAX_CLUSTER_COUNT, QAS, and workload schedule alignment."
        safe_path = (
            "Use Warehouse Settings Manager to compare current settings with burn drivers, require owner approval, "
            "save rollback SQL, then verify credits and query volume after the change."
        )
        risk = "Cost controls can affect availability, queueing, or service-level expectations if applied broadly."
    else:
        candidate = "Review STATEMENT_TIMEOUT_IN_SECONDS, MAX_CONCURRENCY_LEVEL, WAREHOUSE_SIZE, and workload routing."
        safe_path = (
            "Use Warehouse Settings Manager for changed-only SQL, owner approval, rollback SQL, and post-change "
            "runtime verification."
        )
        risk = "Latency changes can shift failures, queueing, or user experience if applied without workload evidence."

    readiness = "Ready for DBA review" if str(row.get("WAREHOUSE_NAME") or "").strip() else "Missing warehouse identity"
    owner_context = _warehouse_owner_context(row)
    return {
        "ADMIN_READINESS": readiness,
        "OWNER": owner_context["owner"],
        "ESCALATION_TARGET": owner_context["escalation"],
        "OWNER_SOURCE": owner_context["source"],
        "OWNER_EMAIL": owner_context.get("owner_email", ""),
        "ONCALL_PRIMARY": owner_context.get("oncall_primary", ""),
        "ONCALL_SECONDARY": owner_context.get("oncall_secondary", ""),
        "APPROVAL_GROUP": owner_context.get("approval_group", ""),
        "OWNER_EVIDENCE": owner_context.get("owner_evidence", ""),
        "APPROVER": _warehouse_approval_for({**row.to_dict(), **owner_context} if hasattr(row, "to_dict") else row),
        "SETTING_CHANGE_CANDIDATE": candidate,
        "APPROVAL_REQUIRED": "Yes",
        "ROLLBACK_REQUIRED": "Yes",
        "SAFE_CHANGE_PATH": safe_path,
        "CHANGE_RISK": risk,
        "POST_CHANGE_VERIFICATION": (
            "Compare queued queries, spill queries, p95 latency, and metered credits for the same warehouse/environment "
            "before closing the action."
        ),
        "SAVINGS_VERIFICATION_REQUIRED": "Yes" if "CREDIT" in signal else "No",
        "PRESSURE_EVIDENCE": (
            f"queued={queued:,}; spill={spill:,}; high_latency={high_latency:,}; "
            f"credit_spike={spike:,.1f}%; p95={p95:,.2f}s"
        ),
    }


def _annotate_warehouse_admin_readiness(exceptions: pd.DataFrame) -> pd.DataFrame:
    if exceptions is None or exceptions.empty:
        return pd.DataFrame() if exceptions is None else exceptions
    rows = []
    for _, row in exceptions.iterrows():
        rows.append(_warehouse_setting_candidate_for(row))
    readiness = pd.DataFrame(rows, index=exceptions.index)
    annotated = exceptions.copy()
    for column in readiness.columns:
        annotated[column] = readiness[column]
    return annotated


def _warehouse_setting_audit_readiness_for_row(row: pd.Series | dict) -> dict:
    """Score whether a warehouse setting change has approval, execution, and verification proof."""
    owner = str(row.get("OWNER") or "").strip()
    owner_source = str(row.get("OWNER_SOURCE") or "").upper()
    approver = str(row.get("APPROVER") or row.get("APPROVAL_GROUP") or "").strip()
    approval_required = str(row.get("APPROVAL_REQUIRED") or "Yes").upper() == "YES"
    rollback_required = str(row.get("ROLLBACK_REQUIRED") or "Yes").upper() == "YES"
    savings_required = str(row.get("SAVINGS_VERIFICATION_REQUIRED") or "No").upper() == "YES"
    approval_state = str(row.get("APPROVAL_STATE") or row.get("OWNER_APPROVAL_STATUS") or "").upper()
    ticket_id = str(row.get("CHANGE_TICKET_ID") or row.get("TICKET_ID") or "").strip()
    rollback_sql = str(row.get("ROLLBACK_SQL") or "").strip()
    execution_status = str(row.get("EXECUTION_STATUS") or "Not Executed").upper()
    sql_hash = str(row.get("EXECUTED_SQL_HASH") or row.get("SQL_HASH") or "").strip()
    verification_status = str(
        row.get("POST_CHANGE_VERIFICATION_STATUS")
        or row.get("VERIFICATION_STATUS")
        or ""
    ).upper()
    verification_result = str(
        row.get("POST_CHANGE_VERIFICATION_RESULT")
        or row.get("VERIFICATION_RESULT")
        or ""
    ).strip()
    verified_savings = safe_float(row.get("VERIFIED_MONTHLY_SAVINGS"))

    blockers: list[str] = []
    generic_owners = {"", "DBA", "UNKNOWN", "N/A"}
    owner_route_ready = bool(owner) and owner.upper() not in generic_owners and bool(owner_source or approver)
    if not owner_route_ready:
        blockers.append("named owner route")
    if approval_required and approval_state not in {"APPROVED", "APPROVAL NOT REQUIRED", "NOT REQUIRED"}:
        blockers.append("owner approval")
    if not ticket_id:
        blockers.append("change ticket")
    if rollback_required and not rollback_sql:
        blockers.append("rollback SQL")

    executed = execution_status in {"SUCCESS", "EXECUTED", "COMPLETED"}
    failed = execution_status in {"FAILED", "ERROR"}
    if executed and not sql_hash:
        blockers.append("admin execution hash")
    if executed and (verification_status != "VERIFIED" or len(verification_result) < 15):
        blockers.append("post-change verification")
    if executed and savings_required and verified_savings <= 0:
        blockers.append("verified savings")

    route_blockers = {"named owner route"}
    pre_change_blockers = {"owner approval", "change ticket", "rollback SQL"}
    verification_blockers = {"admin execution hash", "post-change verification", "verified savings"}

    if failed:
        readiness = "Execution Failed"
        rank = 0
    elif any(item in route_blockers for item in blockers):
        readiness = "Owner Route Blocked"
        rank = 1
    elif any(item in pre_change_blockers for item in blockers):
        readiness = "Pre-Change Blocked"
        rank = 2
    elif any(item in verification_blockers for item in blockers):
        readiness = "Verification Blocked"
        rank = 3
    elif executed:
        readiness = "Verified Change Audit"
        rank = 8
    else:
        readiness = "Ready for Controlled Change"
        rank = 6

    if failed:
        next_action = "Open the failed admin audit row, correct the setting plan, and keep rollback evidence with the ticket."
    elif "named owner route" in blockers:
        next_action = "Assign a named warehouse owner route before approving or executing setting changes."
    elif "owner approval" in blockers:
        next_action = "Capture owner approval before running ALTER WAREHOUSE."
    elif "change ticket" in blockers:
        next_action = "Attach the approved change ticket to the warehouse setting review."
    elif "rollback SQL" in blockers:
        next_action = "Generate and retain rollback SQL from DBA Tools before execution."
    elif "post-change verification" in blockers:
        next_action = "Run queue/spill/credit verification and attach the result before closure."
    elif "verified savings" in blockers:
        next_action = "Attach measured savings evidence before closing the credit-control change."
    elif executed:
        next_action = "Retain verified execution, rollback, and post-change evidence for audit."
    else:
        next_action = "Route through DBA Tools > Warehouse Settings Manager for changed-only SQL and audit logging."

    return {
        "AUDIT_READINESS": readiness,
        "AUDIT_RANK": rank,
        "AUDIT_BLOCKERS": "; ".join(blockers) if blockers else "None",
        "OWNER_ROUTE_READY": "Yes" if owner_route_ready else "No",
        "NEXT_CONTROL_ACTION": next_action,
    }


def _warehouse_setting_control_board(
    exceptions: pd.DataFrame,
    owner_inventory: pd.DataFrame | None = None,
    closure: pd.DataFrame | None = None,
    execution_audit: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Combine capacity findings, ownership, closure, and execution audit into one DBA board."""
    if exceptions is None or exceptions.empty:
        return pd.DataFrame()

    findings = _warehouse_capacity_priority_view(exceptions)
    if findings.empty:
        return pd.DataFrame()

    owners = pd.DataFrame() if owner_inventory is None else owner_inventory.copy()
    if not owners.empty:
        owners.columns = [str(col).upper() for col in owners.columns]
        if "GOVERNANCE_READINESS" not in owners.columns:
            owners = _annotate_warehouse_owner_inventory(owners)
    closure_view = pd.DataFrame() if closure is None else closure.copy()
    if not closure_view.empty:
        closure_view.columns = [str(col).upper() for col in closure_view.columns]
    audit_view = pd.DataFrame() if execution_audit is None else execution_audit.copy()
    if not audit_view.empty:
        audit_view.columns = [str(col).upper() for col in audit_view.columns]

    owner_by_wh = {
        str(row.get("WAREHOUSE_NAME") or "").upper(): row
        for _, row in owners.iterrows()
    } if not owners.empty else {}
    closure_by_wh = {
        str(row.get("WAREHOUSE_NAME") or "").upper(): row
        for _, row in closure_view.iterrows()
    } if not closure_view.empty else {}
    audit_by_wh = {
        str(row.get("WAREHOUSE_NAME") or "").upper(): row
        for _, row in audit_view.iterrows()
    } if not audit_view.empty else {}

    rows: list[dict] = []
    for _, row in findings.iterrows():
        wh = str(row.get("WAREHOUSE_NAME") or "")
        wh_key = wh.upper()
        owner_row = owner_by_wh.get(wh_key, {})
        closure_row = closure_by_wh.get(wh_key, {})
        audit_row = audit_by_wh.get(wh_key, {})

        audit_readiness = _warehouse_setting_audit_readiness_for_row({
            **row.to_dict(),
            "APPROVAL_STATE": audit_row.get("APPROVAL_STATE", "Requested") if len(audit_row) else "Requested",
            "CHANGE_TICKET_ID": audit_row.get("CHANGE_TICKET_ID", ""),
            "ROLLBACK_SQL": audit_row.get("ROLLBACK_SQL", ""),
            "EXECUTION_STATUS": audit_row.get("LAST_EXECUTION_STATUS", audit_row.get("EXECUTION_STATUS", "Not Executed")),
            "EXECUTED_SQL_HASH": audit_row.get("LAST_SQL_HASH", audit_row.get("EXECUTED_SQL_HASH", "")),
            "POST_CHANGE_VERIFICATION_STATUS": audit_row.get("POST_CHANGE_VERIFICATION_STATUS", ""),
            "POST_CHANGE_VERIFICATION_RESULT": audit_row.get("POST_CHANGE_VERIFICATION_RESULT", ""),
            "VERIFIED_MONTHLY_SAVINGS": audit_row.get("VERIFIED_MONTHLY_SAVINGS", 0),
        })

        governance_readiness = str(owner_row.get("GOVERNANCE_READINESS") or "Not Loaded")
        closure_readiness = str(closure_row.get("CLOSURE_READINESS") or "Not Loaded")
        closure_rank = safe_int(closure_row.get("CLOSURE_RANK", 9))
        overdue = safe_int(closure_row.get("OVERDUE_OPEN", 0))
        fixed_without_verification = safe_int(closure_row.get("FIXED_WITHOUT_VERIFICATION", 0))
        failed_changes = safe_int(audit_row.get("FAILED_CHANGES", 0))
        audit_rows = safe_int(audit_row.get("AUDIT_ROWS", 0))

        if overdue:
            state, rank = "Closure Overdue", 0
            next_action = "Escalate overdue Warehouse Health action before approving more setting changes."
        elif fixed_without_verification or closure_rank in {1, 2}:
            state, rank = "Closure Evidence Blocked", 1
            next_action = str(closure_row.get("NEXT_ACTION") or "Attach verification proof before closing warehouse work.")
        elif governance_readiness == "Owner Route Blocked" or audit_readiness["AUDIT_READINESS"] == "Owner Route Blocked":
            state, rank = "Owner Route Blocked", 2
            next_action = str(owner_row.get("NEXT_OWNER_ACTION") or audit_readiness["NEXT_CONTROL_ACTION"])
        elif failed_changes:
            state, rank = "Execution Failed", 3
            next_action = "Review failed ALTER WAREHOUSE audit rows and verify rollback or no-op state."
        elif audit_readiness["AUDIT_READINESS"] in {"Pre-Change Blocked", "Verification Blocked"}:
            state, rank = audit_readiness["AUDIT_READINESS"], audit_readiness["AUDIT_RANK"]
            next_action = audit_readiness["NEXT_CONTROL_ACTION"]
        elif audit_rows:
            state, rank = "Execution Audit Linked", 7
            next_action = "Confirm post-change queue, spill, credit, and savings evidence remains attached."
        else:
            state, rank = "Ready for Controlled Change", 6
            next_action = "Open DBA Tools > Warehouse Settings Manager, generate changed-only SQL, and capture rollback proof."

        rows.append({
            "CONTROL_STATE": state,
            "CONTROL_RANK": rank,
            "WAREHOUSE_NAME": wh,
            "SEVERITY": row.get("SEVERITY", ""),
            "SIGNAL": row.get("SIGNAL", ""),
            "CAPACITY_SCORE": safe_float(row.get("CAPACITY_SCORE")),
            "METERED_CREDITS": safe_float(row.get("METERED_CREDITS")),
            "OWNER": row.get("OWNER", ""),
            "GOVERNANCE_READINESS": governance_readiness,
            "AUDIT_READINESS": audit_readiness["AUDIT_READINESS"],
            "AUDIT_BLOCKERS": audit_readiness["AUDIT_BLOCKERS"],
            "CLOSURE_READINESS": closure_readiness,
            "OVERDUE_OPEN": overdue,
            "FIXED_WITHOUT_VERIFICATION": fixed_without_verification,
            "AUDIT_ROWS": audit_rows,
            "SUCCESSFUL_CHANGES": safe_int(audit_row.get("SUCCESSFUL_CHANGES", 0)),
            "FAILED_CHANGES": failed_changes,
            "LAST_EXECUTION_STATUS": audit_row.get("LAST_EXECUTION_STATUS", "Not Loaded"),
            "LAST_EXECUTED_AT": audit_row.get("LAST_EXECUTED_AT", ""),
            "APPROVAL_REQUIRED": row.get("APPROVAL_REQUIRED", "Yes"),
            "ROLLBACK_REQUIRED": row.get("ROLLBACK_REQUIRED", "Yes"),
            "SAVINGS_VERIFICATION_REQUIRED": row.get("SAVINGS_VERIFICATION_REQUIRED", "No"),
            "SETTING_CHANGE_CANDIDATE": row.get("SETTING_CHANGE_CANDIDATE", ""),
            "NEXT_CONTROL_ACTION": next_action,
        })

    return pd.DataFrame(rows).sort_values(
        ["CONTROL_RANK", "OVERDUE_OPEN", "FAILED_CHANGES", "CAPACITY_SCORE", "METERED_CREDITS"],
        ascending=[True, False, False, True, False],
    ).reset_index(drop=True)


def _warehouse_frame_sum(frame: pd.DataFrame | None, column: str) -> int:
    if frame is None or frame.empty or column not in frame.columns:
        return 0
    return int(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())


def _warehouse_state_count(frame: pd.DataFrame | None, column: str, states: set[str]) -> int:
    if frame is None or frame.empty or column not in frame.columns:
        return 0
    normalized = {state.upper() for state in states}
    return int(frame[column].fillna("").astype(str).str.upper().isin(normalized).sum())


def _warehouse_operator_next_moves(
    *,
    score: int | float,
    exceptions: pd.DataFrame | None,
    control_board: pd.DataFrame | None = None,
    closure: pd.DataFrame | None = None,
    execution_audit: pd.DataFrame | None = None,
    operability_fact: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a no-query decision gate for the loaded warehouse evidence."""
    exception_count = 0 if exceptions is None or exceptions.empty else int(len(exceptions))
    control = pd.DataFrame() if control_board is None else control_board.copy()
    close = pd.DataFrame() if closure is None else closure.copy()
    audit = pd.DataFrame() if execution_audit is None else execution_audit.copy()
    fact = pd.DataFrame() if operability_fact is None else operability_fact.copy()
    for frame in (control, close, audit, fact):
        if not frame.empty:
            frame.columns = [str(col).upper() for col in frame.columns]

    overdue = max(
        _warehouse_frame_sum(control, "OVERDUE"),
        _warehouse_frame_sum(close, "OVERDUE_OPEN"),
        _warehouse_frame_sum(fact, "OVERDUE_OPEN"),
    )
    fixed_without_verification = max(
        _warehouse_frame_sum(control, "FIXED_WITHOUT_VERIFICATION"),
        _warehouse_frame_sum(close, "FIXED_WITHOUT_VERIFICATION"),
        _warehouse_frame_sum(fact, "FIXED_WITHOUT_VERIFICATION"),
    )
    recovery_risk = max(
        _warehouse_frame_sum(close, "RECOVERY_RISK_ROWS"),
        _warehouse_frame_sum(fact, "RECOVERY_RISK_ROWS"),
    )
    closure_blockers = max(
        _warehouse_frame_sum(control, "CLOSURE_BLOCKERS"),
        _warehouse_frame_sum(close, "CLOSURE_BLOCKER_ROWS"),
        overdue + fixed_without_verification + recovery_risk,
    )
    failed_changes = max(
        _warehouse_frame_sum(control, "FAILED_CHANGES"),
        _warehouse_frame_sum(audit, "FAILED_CHANGES"),
    )
    audit_rows = max(
        _warehouse_frame_sum(control, "AUDIT_ROWS"),
        _warehouse_frame_sum(audit, "AUDIT_ROWS"),
    )
    route_blocks = (
        _warehouse_state_count(control, "CONTROL_STATE", {"Owner Route Blocked", "Pre-Change Blocked"})
        + _warehouse_state_count(control, "AUDIT_READINESS", {"Owner Route Blocked", "Pre-Change Blocked"})
        + _warehouse_frame_sum(fact, "APPROVAL_REQUIRED_ROWS")
        + _warehouse_frame_sum(fact, "ROLLBACK_REQUIRED_ROWS")
    )
    pressure_rows = max(
        exception_count,
        _warehouse_frame_sum(fact, "QUEUE_PRESSURE_ROWS") + _warehouse_frame_sum(fact, "SPILL_PRESSURE_ROWS"),
    )

    rows: list[dict] = []
    if closure_blockers:
        state = "Blocked"
        rank = 0
        next_action = "Escalate overdue or unverified Warehouse Health work before approving more setting changes."
        count = closure_blockers
    elif exception_count and close.empty:
        state = "Load Closure Analytics"
        rank = 4
        next_action = "Load closure analytics before closing or declaring capacity actions controlled."
        count = exception_count
    else:
        state = "Clear"
        rank = 8
        next_action = "Retain verified closure evidence with the setting review history."
        count = _warehouse_frame_sum(close, "VERIFIED_CLOSURES") + _warehouse_frame_sum(fact, "VERIFIED_CLOSURES")
    rows.append({
        "GATE": "Closure proof",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "owner, ticket/change ID, owner approval, verification result, recovery evidence",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if failed_changes:
        state = "Failed Execution"
        rank = 1
        next_action = "Review failed ALTER WAREHOUSE audit rows and verify rollback or no-op state."
        count = failed_changes
    elif exception_count and not audit_rows:
        state = "Load Execution Audit"
        rank = 3
        next_action = "Load execution audit before approving warehouse changes or claiming verified savings."
        count = exception_count
    elif audit_rows:
        state = "Audit Linked"
        rank = 7
        next_action = "Confirm SQL hash, executor, rollback SQL, and post-change verification remain attached."
        count = audit_rows
    else:
        state = "No Change Evidence Needed"
        rank = 9
        next_action = "No capacity exception currently requires warehouse setting audit evidence."
        count = 0
    rows.append({
        "GATE": "Execution audit",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "SQL hash, executor, approval state, rollback SQL, post-change pressure check",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if route_blocks:
        state = "Approval Route Blocked"
        rank = 2
        next_action = "Complete named owner, approver, ticket, rollback, and savings-verification route before execution."
        count = route_blocks
    elif exception_count:
        state = "Ready for Review"
        rank = 6
        next_action = "Save the setting review snapshot, then work only changed settings through DBA Tools."
        count = exception_count
    else:
        state = "Clear"
        rank = 8
        next_action = "Keep owner inventory current for future capacity exceptions."
        count = 0
    rows.append({
        "GATE": "Owner approval route",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "named owner, approver, approval group, rollback requirement, savings evidence requirement",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if pressure_rows:
        if safe_float(score) < 65:
            state, rank = "High Pressure", 1
        elif safe_float(score) < 90:
            state, rank = "Watch Pressure", 5
        else:
            state, rank = "Exceptions Present", 6
        next_action = "Verify queue, spill, latency, and credit pressure before changing warehouse settings."
        count = pressure_rows
    else:
        state = "Clear"
        rank = 8
        next_action = "No pressured warehouse crossed the current threshold."
        count = 0
    rows.append({
        "GATE": "Capacity pressure",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "queued queries, spill queries, p95 latency, metered credits, setting candidate",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    metered_credits = 0.0
    credit_spike_rows = 0
    savings_required = 0
    if exceptions is not None and not exceptions.empty:
        metered_credits = float(pd.to_numeric(
            exceptions.get("METERED_CREDITS", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0).sum())
        credit_spike_rows = int(
            exceptions.get("SIGNAL", pd.Series(dtype=str)).fillna("").astype(str).str.upper().str.contains("CREDIT").sum()
        )
        if "SAVINGS_VERIFICATION_REQUIRED" in exceptions.columns:
            savings_required = int(
                exceptions["SAVINGS_VERIFICATION_REQUIRED"].fillna("").astype(str).str.upper().eq("YES").sum()
            )
    if not control.empty and "SAVINGS_VERIFICATION_REQUIRED" in control.columns:
        savings_required = max(
            savings_required,
            int(control["SAVINGS_VERIFICATION_REQUIRED"].fillna("").astype(str).str.upper().eq("YES").sum()),
        )

    if credit_spike_rows or savings_required:
        state = "Cost Impact Review"
        rank = 3
        count = max(credit_spike_rows, savings_required)
        next_action = "Attach credit delta, savings hypothesis, owner approval, and post-change verification before changing settings."
    elif metered_credits > 0 and exception_count:
        state = "Estimated Cost Watch"
        rank = 6
        count = exception_count
        next_action = "Keep warehouse metering and setting-review evidence together before claiming DBA savings."
    else:
        state = "Clear"
        rank = 8
        count = 0
        next_action = "No loaded warehouse action needs cost-impact proof."
    rows.append({
        "GATE": "Cost guardrail",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "metered credits, cost delta, savings hypothesis, owner approval, post-change verification",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    return pd.DataFrame(rows).sort_values(["GATE_RANK", "COUNT"], ascending=[True, False]).reset_index(drop=True)


def _warehouse_capacity_review_sql(row: pd.Series) -> str:
    candidate = row.get("SETTING_CHANGE_CANDIDATE") or _warehouse_setting_candidate_for(row)["SETTING_CHANGE_CANDIDATE"]
    safe_path = row.get("SAFE_CHANGE_PATH") or _warehouse_setting_candidate_for(row)["SAFE_CHANGE_PATH"]
    verification = row.get("POST_CHANGE_VERIFICATION") or _warehouse_setting_candidate_for(row)["POST_CHANGE_VERIFICATION"]
    return "\n".join([
        "-- Reviewed warehouse setting plan required.",
        "-- Do not execute a warehouse change from this advisory row.",
        f"-- Candidate: {candidate}",
        f"-- Safe path: {safe_path}",
        "-- Route through DBA Tools > Warehouse Settings Manager for changed-only SQL, approval, and rollback.",
        f"-- Closure evidence: {verification}",
    ])


def _warehouse_setting_review_insert_sql(
    findings: pd.DataFrame,
    *,
    company: str,
    environment: str,
    source: str = "",
    snapshot_id: str = "",
) -> str:
    if findings is None or findings.empty:
        raise ValueError("Warehouse setting review snapshot has no rows to save.")
    view = _annotate_warehouse_admin_readiness(findings)
    fqn = warehouse_setting_review_fqn()
    env_value = str(environment or "").strip() or "ALL"
    snap = snapshot_id or make_action_id(
        "Warehouse Setting Review Snapshot",
        company,
        f"{env_value}|{datetime.now().strftime('%Y%m%d%H%M%S')}",
    )
    selects = []
    for _, row in view.head(200).iterrows():
        wh = str(row.get("WAREHOUSE_NAME") or "")
        verification_sql = _warehouse_capacity_verification_sql(
            wh,
            days=7,
            environment=environment,
            company=company,
        )
        review_sql = _warehouse_capacity_review_sql(row)
        approval_required = str(row.get("APPROVAL_REQUIRED", "Yes")).upper() == "YES"
        approval_state = str(row.get("APPROVAL_STATE") or ("Requested" if approval_required else "Not Required"))
        audit_fields = _warehouse_setting_audit_readiness_for_row({
            **row.to_dict(),
            "APPROVAL_STATE": approval_state,
            "CHANGE_TICKET_ID": row.get("CHANGE_TICKET_ID", ""),
            "CURRENT_SETTINGS_JSON": row.get("CURRENT_SETTINGS_JSON", ""),
            "PROPOSED_SETTINGS_JSON": row.get("PROPOSED_SETTINGS_JSON", row.get("SETTING_CHANGE_CANDIDATE", "")),
            "ROLLBACK_SQL": row.get("ROLLBACK_SQL", ""),
            "EXECUTED_SQL_HASH": row.get("EXECUTED_SQL_HASH", ""),
            "EXECUTION_STATUS": row.get("EXECUTION_STATUS", "Not Executed"),
            "POST_CHANGE_VERIFICATION_STATUS": row.get("POST_CHANGE_VERIFICATION_STATUS", "Pending"),
            "POST_CHANGE_VERIFICATION_RESULT": row.get("POST_CHANGE_VERIFICATION_RESULT", ""),
            "VERIFIED_MONTHLY_SAVINGS": row.get("VERIFIED_MONTHLY_SAVINGS", 0),
        })
        selects.append(
            "SELECT "
            f"{sql_literal(snap, 64)} AS SNAPSHOT_ID, "
            "CURRENT_TIMESTAMP() AS SNAPSHOT_TS, "
            f"{sql_literal(company, 100)} AS COMPANY, "
            f"{sql_literal(env_value, 100)} AS ENVIRONMENT, "
            f"{sql_literal(wh, 300)} AS WAREHOUSE_NAME, "
            f"{sql_literal(row.get('SEVERITY', ''), 40)} AS SEVERITY, "
            f"{sql_literal(row.get('SIGNAL', ''), 120)} AS SIGNAL, "
            f"{sql_literal(row.get('OWNER', ''), 200)} AS OWNER, "
            f"{sql_literal(row.get('ESCALATION_TARGET', ''), 200)} AS ESCALATION_TARGET, "
            f"{sql_literal(row.get('OWNER_SOURCE', ''), 200)} AS OWNER_SOURCE, "
            f"{sql_literal(row.get('APPROVER', ''), 200)} AS APPROVER, "
            f"{sql_literal(row.get('APPROVAL_REQUIRED', ''), 20)} AS APPROVAL_REQUIRED, "
            f"{sql_literal(row.get('ROLLBACK_REQUIRED', ''), 20)} AS ROLLBACK_REQUIRED, "
            f"{sql_literal(row.get('SAFE_CHANGE_PATH', ''), 4000)} AS SAFE_CHANGE_PATH, "
            f"{sql_literal(row.get('SETTING_CHANGE_CANDIDATE', ''), 4000)} AS SETTING_CHANGE_CANDIDATE, "
            f"{sql_literal(row.get('CHANGE_RISK', ''), 2000)} AS CHANGE_RISK, "
            f"{sql_literal(row.get('POST_CHANGE_VERIFICATION', ''), 2000)} AS POST_CHANGE_VERIFICATION, "
            f"{sql_literal(row.get('PRESSURE_EVIDENCE', ''), 2000)} AS PRESSURE_EVIDENCE, "
            f"{safe_float(row.get('CAPACITY_SCORE'))}::FLOAT AS BASELINE_CAPACITY_SCORE, "
            f"{safe_int(row.get('QUEUED_QUERIES'))}::NUMBER AS BASELINE_QUEUED_QUERIES, "
            f"{safe_int(row.get('SPILL_QUERIES'))}::NUMBER AS BASELINE_SPILL_QUERIES, "
            f"{safe_int(row.get('HIGH_LATENCY_QUERIES'))}::NUMBER AS BASELINE_HIGH_LATENCY_QUERIES, "
            f"{safe_float(row.get('P95_ELAPSED_SEC'))}::FLOAT AS BASELINE_P95_ELAPSED_SEC, "
            f"{safe_float(row.get('METERED_CREDITS'))}::FLOAT AS BASELINE_METERED_CREDITS, "
            f"{sql_literal(verification_sql, 8000)} AS VERIFICATION_QUERY, "
            f"{sql_literal(review_sql, 8000)} AS GENERATED_REVIEW_SQL, "
            f"{sql_literal(row.get('SAVINGS_VERIFICATION_REQUIRED', ''), 20)} AS SAVINGS_VERIFICATION_REQUIRED, "
            f"{sql_literal(approval_state, 80)} AS APPROVAL_STATE, "
            f"{sql_literal(row.get('CHANGE_TICKET_ID', ''), 200)} AS CHANGE_TICKET_ID, "
            f"{sql_literal(row.get('CURRENT_SETTINGS_JSON', ''), 8000)} AS CURRENT_SETTINGS_JSON, "
            f"{sql_literal(row.get('PROPOSED_SETTINGS_JSON', row.get('SETTING_CHANGE_CANDIDATE', '')), 8000)} AS PROPOSED_SETTINGS_JSON, "
            f"{sql_literal(row.get('ROLLBACK_SQL', ''), 8000)} AS ROLLBACK_SQL, "
            f"{sql_literal(row.get('EXECUTED_SQL_HASH', ''), 80)} AS EXECUTED_SQL_HASH, "
            f"{sql_literal(row.get('EXECUTION_STATUS', 'Not Executed'), 80)} AS EXECUTION_STATUS, "
            f"{sql_literal(row.get('EXECUTED_BY', ''), 200)} AS EXECUTED_BY, "
            "NULL::TIMESTAMP_NTZ AS EXECUTED_AT, "
            f"{sql_literal(row.get('POST_CHANGE_VERIFICATION_STATUS', 'Pending'), 80)} AS POST_CHANGE_VERIFICATION_STATUS, "
            f"{sql_literal(row.get('POST_CHANGE_VERIFICATION_RESULT', ''), 4000)} AS POST_CHANGE_VERIFICATION_RESULT, "
            f"{safe_float(row.get('VERIFIED_MONTHLY_SAVINGS'))}::FLOAT AS VERIFIED_MONTHLY_SAVINGS, "
            f"{sql_literal(audit_fields.get('AUDIT_READINESS', ''), 100)} AS AUDIT_READINESS, "
            f"{sql_literal(audit_fields.get('AUDIT_BLOCKERS', ''), 2000)} AS AUDIT_BLOCKERS, "
            f"{sql_literal(audit_fields.get('NEXT_CONTROL_ACTION', ''), 4000)} AS NEXT_CONTROL_ACTION, "
            f"{sql_literal(source, 500)} AS SOURCE"
        )
    return f"""
INSERT INTO {fqn} (
    SNAPSHOT_ID, SNAPSHOT_TS, COMPANY, ENVIRONMENT, WAREHOUSE_NAME, SEVERITY,
    SIGNAL, OWNER, ESCALATION_TARGET, OWNER_SOURCE, APPROVER, APPROVAL_REQUIRED,
    ROLLBACK_REQUIRED, SAFE_CHANGE_PATH, SETTING_CHANGE_CANDIDATE, CHANGE_RISK,
    POST_CHANGE_VERIFICATION, PRESSURE_EVIDENCE, BASELINE_CAPACITY_SCORE,
    BASELINE_QUEUED_QUERIES, BASELINE_SPILL_QUERIES, BASELINE_HIGH_LATENCY_QUERIES,
    BASELINE_P95_ELAPSED_SEC, BASELINE_METERED_CREDITS, VERIFICATION_QUERY,
    GENERATED_REVIEW_SQL, SAVINGS_VERIFICATION_REQUIRED, APPROVAL_STATE,
    CHANGE_TICKET_ID, CURRENT_SETTINGS_JSON, PROPOSED_SETTINGS_JSON, ROLLBACK_SQL,
    EXECUTED_SQL_HASH, EXECUTION_STATUS, EXECUTED_BY, EXECUTED_AT,
    POST_CHANGE_VERIFICATION_STATUS, POST_CHANGE_VERIFICATION_RESULT,
    VERIFIED_MONTHLY_SAVINGS, AUDIT_READINESS, AUDIT_BLOCKERS, NEXT_CONTROL_ACTION,
    SOURCE
)
{" UNION ALL ".join(selects)}""".strip()


def _warehouse_setting_review_history_sql(days: int, company: str, environment: str = "ALL") -> str:
    fqn = warehouse_setting_review_fqn()
    where = [f"SNAPSHOT_TS >= DATEADD('day', -{max(1, int(days or 14))}, CURRENT_TIMESTAMP())"]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_value = str(environment or "").strip()
    if env_value and env_value.upper() != "ALL":
        where.append(f"ENVIRONMENT = {sql_literal(env_value, 100)}")
    where_clause = " AND ".join(where)
    return f"""
SELECT
    WAREHOUSE_NAME,
    OWNER,
    ESCALATION_TARGET,
    COUNT(*) AS REVIEW_ROWS,
    COUNT_IF(APPROVAL_REQUIRED = 'Yes') AS APPROVAL_REQUIRED_ROWS,
    COUNT_IF(ROLLBACK_REQUIRED = 'Yes') AS ROLLBACK_REQUIRED_ROWS,
    COUNT_IF(SAVINGS_VERIFICATION_REQUIRED = 'Yes') AS SAVINGS_VERIFICATION_ROWS,
    MIN(BASELINE_CAPACITY_SCORE) AS WORST_BASELINE_CAPACITY_SCORE,
    MAX(BASELINE_QUEUED_QUERIES) AS MAX_BASELINE_QUEUED_QUERIES,
    MAX(BASELINE_SPILL_QUERIES) AS MAX_BASELINE_SPILL_QUERIES,
    MAX(BASELINE_METERED_CREDITS) AS MAX_BASELINE_METERED_CREDITS,
    MAX(SNAPSHOT_TS) AS LAST_SNAPSHOT_TS,
    MAX_BY(SIGNAL, SNAPSHOT_TS) AS LAST_SIGNAL,
    MAX_BY(SETTING_CHANGE_CANDIDATE, SNAPSHOT_TS) AS LAST_SETTING_CHANGE_CANDIDATE
FROM {fqn}
WHERE {where_clause}
GROUP BY WAREHOUSE_NAME, OWNER, ESCALATION_TARGET
ORDER BY
    WORST_BASELINE_CAPACITY_SCORE ASC,
    APPROVAL_REQUIRED_ROWS DESC,
    LAST_SNAPSHOT_TS DESC
LIMIT 100""".strip()


def _warehouse_setting_execution_audit_sql(days: int, company: str, environment: str = "ALL") -> str:
    """Join persisted setting reviews to DBA Tools ALTER WAREHOUSE audit evidence."""
    review_fqn = warehouse_setting_review_fqn()
    days = max(1, min(int(days or 30), 180))
    review_where = [f"SNAPSHOT_TS >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())"]
    audit_where = [
        f"ACTION_TS >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())",
        "UPPER(ACTION_TYPE) = 'ALTER WAREHOUSE'",
    ]
    if str(company or "").upper() != "ALL":
        company_sql = sql_literal(company, 100)
        review_where.append(f"COMPANY = {company_sql}")
        audit_where.append(f"COMPANY = {company_sql}")
    env_clause_review = action_queue_environment_clause("ENVIRONMENT", environment)
    if env_clause_review:
        review_where.append(env_clause_review)
        audit_where.append(env_clause_review)
    return f"""
WITH review_rows AS (
    SELECT
        WAREHOUSE_NAME,
        MAX_BY(OWNER, SNAPSHOT_TS) AS OWNER,
        MAX_BY(APPROVER, SNAPSHOT_TS) AS APPROVER,
        MAX_BY(APPROVAL_STATE, SNAPSHOT_TS) AS APPROVAL_STATE,
        MAX_BY(CHANGE_TICKET_ID, SNAPSHOT_TS) AS CHANGE_TICKET_ID,
        MAX_BY(ROLLBACK_SQL, SNAPSHOT_TS) AS ROLLBACK_SQL,
        MAX_BY(POST_CHANGE_VERIFICATION_STATUS, SNAPSHOT_TS) AS POST_CHANGE_VERIFICATION_STATUS,
        MAX_BY(POST_CHANGE_VERIFICATION_RESULT, SNAPSHOT_TS) AS POST_CHANGE_VERIFICATION_RESULT,
        MAX_BY(AUDIT_READINESS, SNAPSHOT_TS) AS LAST_REVIEW_AUDIT_READINESS,
        MAX_BY(AUDIT_BLOCKERS, SNAPSHOT_TS) AS LAST_REVIEW_AUDIT_BLOCKERS,
        COUNT(*) AS REVIEW_ROWS,
        COUNT_IF(APPROVAL_REQUIRED = 'Yes') AS APPROVAL_REQUIRED_ROWS,
        COUNT_IF(ROLLBACK_REQUIRED = 'Yes') AS ROLLBACK_REQUIRED_ROWS,
        COUNT_IF(SAVINGS_VERIFICATION_REQUIRED = 'Yes') AS SAVINGS_VERIFICATION_REQUIRED_ROWS,
        MAX(SNAPSHOT_TS) AS LAST_REVIEW_TS
    FROM {review_fqn}
    WHERE {" AND ".join(review_where)}
    GROUP BY WAREHOUSE_NAME
),
audit_rows AS (
    SELECT
        TARGET_OBJECT AS WAREHOUSE_NAME,
        COUNT(*) AS AUDIT_ROWS,
        COUNT_IF(UPPER(RESULT_STATUS) = 'SUCCESS') AS SUCCESSFUL_CHANGES,
        COUNT_IF(UPPER(RESULT_STATUS) = 'FAILED') AS FAILED_CHANGES,
        MAX_BY(SQL_HASH, ACTION_TS) AS LAST_SQL_HASH,
        MAX_BY(SNOWFLAKE_USER, ACTION_TS) AS LAST_EXECUTED_BY,
        MAX_BY(SNOWFLAKE_ROLE, ACTION_TS) AS LAST_EXECUTED_ROLE,
        MAX_BY(RESULT_STATUS, ACTION_TS) AS LAST_EXECUTION_STATUS,
        MAX_BY(RESULT_MESSAGE, ACTION_TS) AS LAST_EXECUTION_MESSAGE,
        MAX_BY(CONTROL_CONTEXT, ACTION_TS) AS LAST_CONTROL_CONTEXT,
        MAX(ACTION_TS) AS LAST_EXECUTED_AT
    FROM {ADMIN_AUDIT_FQN}
    WHERE {" AND ".join(audit_where)}
    GROUP BY TARGET_OBJECT
)
SELECT
    COALESCE(r.WAREHOUSE_NAME, a.WAREHOUSE_NAME) AS WAREHOUSE_NAME,
    COALESCE(r.OWNER, '') AS OWNER,
    COALESCE(r.APPROVER, '') AS APPROVER,
    COALESCE(r.APPROVAL_STATE, '') AS APPROVAL_STATE,
    COALESCE(r.CHANGE_TICKET_ID, '') AS CHANGE_TICKET_ID,
    COALESCE(r.ROLLBACK_SQL, '') AS ROLLBACK_SQL,
    COALESCE(r.POST_CHANGE_VERIFICATION_STATUS, '') AS POST_CHANGE_VERIFICATION_STATUS,
    COALESCE(r.POST_CHANGE_VERIFICATION_RESULT, '') AS POST_CHANGE_VERIFICATION_RESULT,
    COALESCE(r.LAST_REVIEW_AUDIT_READINESS, '') AS LAST_REVIEW_AUDIT_READINESS,
    COALESCE(r.LAST_REVIEW_AUDIT_BLOCKERS, '') AS LAST_REVIEW_AUDIT_BLOCKERS,
    COALESCE(r.REVIEW_ROWS, 0) AS REVIEW_ROWS,
    COALESCE(r.APPROVAL_REQUIRED_ROWS, 0) AS APPROVAL_REQUIRED_ROWS,
    COALESCE(r.ROLLBACK_REQUIRED_ROWS, 0) AS ROLLBACK_REQUIRED_ROWS,
    COALESCE(r.SAVINGS_VERIFICATION_REQUIRED_ROWS, 0) AS SAVINGS_VERIFICATION_REQUIRED_ROWS,
    r.LAST_REVIEW_TS,
    COALESCE(a.AUDIT_ROWS, 0) AS AUDIT_ROWS,
    COALESCE(a.SUCCESSFUL_CHANGES, 0) AS SUCCESSFUL_CHANGES,
    COALESCE(a.FAILED_CHANGES, 0) AS FAILED_CHANGES,
    COALESCE(a.LAST_SQL_HASH, '') AS LAST_SQL_HASH,
    COALESCE(a.LAST_EXECUTED_BY, '') AS LAST_EXECUTED_BY,
    COALESCE(a.LAST_EXECUTED_ROLE, '') AS LAST_EXECUTED_ROLE,
    COALESCE(a.LAST_EXECUTION_STATUS, 'Not Executed') AS LAST_EXECUTION_STATUS,
    COALESCE(a.LAST_EXECUTION_MESSAGE, '') AS LAST_EXECUTION_MESSAGE,
    COALESCE(a.LAST_CONTROL_CONTEXT, '') AS LAST_CONTROL_CONTEXT,
    a.LAST_EXECUTED_AT,
    CASE
        WHEN COALESCE(a.FAILED_CHANGES, 0) > 0 THEN 'Execution failed'
        WHEN COALESCE(r.REVIEW_ROWS, 0) > 0 AND COALESCE(a.AUDIT_ROWS, 0) = 0 THEN 'Reviewed but not executed'
        WHEN COALESCE(a.SUCCESSFUL_CHANGES, 0) > 0
             AND UPPER(COALESCE(r.POST_CHANGE_VERIFICATION_STATUS, '')) <> 'VERIFIED' THEN 'Executed - verification pending'
        WHEN COALESCE(r.SAVINGS_VERIFICATION_REQUIRED_ROWS, 0) > 0
             AND LENGTH(TRIM(COALESCE(r.POST_CHANGE_VERIFICATION_RESULT, ''))) < 15 THEN 'Savings proof pending'
        WHEN COALESCE(a.SUCCESSFUL_CHANGES, 0) > 0 THEN 'Executed and audit linked'
        ELSE 'No setting review'
    END AS EXECUTION_AUDIT_READINESS,
    CASE
        WHEN COALESCE(a.FAILED_CHANGES, 0) > 0 THEN 'Open failed admin audit row and verify rollback/no-op state.'
        WHEN COALESCE(r.REVIEW_ROWS, 0) > 0 AND COALESCE(a.AUDIT_ROWS, 0) = 0 THEN 'Execute only through DBA Tools after approval, ticket, and rollback SQL are attached.'
        WHEN COALESCE(a.SUCCESSFUL_CHANGES, 0) > 0
             AND UPPER(COALESCE(r.POST_CHANGE_VERIFICATION_STATUS, '')) <> 'VERIFIED' THEN 'Run post-change verification and attach result before closure.'
        WHEN COALESCE(r.SAVINGS_VERIFICATION_REQUIRED_ROWS, 0) > 0
             AND LENGTH(TRIM(COALESCE(r.POST_CHANGE_VERIFICATION_RESULT, ''))) < 15 THEN 'Attach measured savings evidence for credit-control change.'
        WHEN COALESCE(a.SUCCESSFUL_CHANGES, 0) > 0 THEN 'Retain SQL hash, executor, role, rollback, and verification evidence.'
        ELSE 'Create a setting review snapshot before changing this warehouse.'
    END AS NEXT_CONTROL_ACTION
FROM review_rows r
FULL OUTER JOIN audit_rows a
  ON UPPER(r.WAREHOUSE_NAME) = UPPER(a.WAREHOUSE_NAME)
ORDER BY
    CASE EXECUTION_AUDIT_READINESS
        WHEN 'Execution failed' THEN 1
        WHEN 'Executed - verification pending' THEN 2
        WHEN 'Savings proof pending' THEN 3
        WHEN 'Reviewed but not executed' THEN 4
        WHEN 'No setting review' THEN 8
        ELSE 9
    END,
    LAST_EXECUTED_AT DESC NULLS LAST,
    LAST_REVIEW_TS DESC NULLS LAST
LIMIT 100""".strip()


def _warehouse_action_queue_closure_sql(days: int, company: str, environment: str = "ALL") -> str:
    fqn = f"{safe_identifier(ALERT_DB)}.{safe_identifier(ALERT_SCHEMA)}.{safe_identifier(ACTION_QUEUE_TABLE)}"
    where = [
        "SOURCE IN ('Warehouse Health - Capacity Brief', 'Warehouse Health - Efficiency')",
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
        COALESCE(ENTITY_NAME, 'Unknown warehouse') AS WAREHOUSE_NAME,
        COALESCE(SOURCE, '') AS SOURCE,
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
        WAREHOUSE_NAME,
        MAX_BY(SOURCE, LAST_ACTIVITY_TS) AS LAST_SOURCE,
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
        COUNT_IF(UPPER(OWNER) IN ('', 'DBA', 'UNKNOWN', 'N/A')) AS OWNER_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(TICKET_ID)) = 0) AS TICKET_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(APPROVER)) = 0) AS APPROVER_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(VERIFICATION_QUERY)) = 0) AS VERIFICATION_QUERY_GAP_ROWS,
        COUNT_IF(UPPER(OWNER_APPROVAL_STATUS) IN ('', 'PENDING', 'REQUESTED', 'REQUIRED')) AS OWNER_APPROVAL_GAP_ROWS,
        COUNT_IF(
            UPPER(RECOVERY_SLA_STATE) ILIKE '%BREACH%'
            OR UPPER(RECOVERY_SLA_STATE) ILIKE '%LATE%'
            OR (
                UPPER(STATUS) = 'FIXED'
                AND LENGTH(TRIM(RECOVERY_EVIDENCE)) < 15
            )
        ) AS RECOVERY_RISK_ROWS,
        MIN(IFF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED'), DUE_DATE, NULL)) AS NEXT_DUE_DATE,
        MAX(LAST_ACTIVITY_TS) AS LAST_ACTIVITY_TS,
        MAX_BY(STATUS, LAST_ACTIVITY_TS) AS LAST_STATUS,
        MAX_BY(SEVERITY, LAST_ACTIVITY_TS) AS LAST_SEVERITY
    FROM scoped_actions
    GROUP BY WAREHOUSE_NAME
)
SELECT
    WAREHOUSE_NAME,
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
    LAST_SOURCE,
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
        WHEN OVERDUE_OPEN > 0 THEN 'Escalate the warehouse owner and ticket before changing settings.'
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 'Attach post-change queue/spill/credit evidence or reopen the action.'
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 'Complete owner, ticket, approver, and verification metadata.'
        WHEN OPEN_ACTIONS > 0 THEN 'Work the open warehouse action and retain rollback plus post-change proof.'
        ELSE 'Retain verified closure evidence for capacity and cost trend review.'
    END AS NEXT_ACTION
FROM rollup
ORDER BY CLOSURE_RANK, OVERDUE_OPEN DESC, FIXED_WITHOUT_VERIFICATION DESC, OPEN_ACTIONS DESC, LAST_ACTIVITY_TS DESC
LIMIT 100""".strip()


def _warehouse_operability_fact_sql(days: int, company: str, environment: str = "ALL") -> str:
    """Read pre-aggregated warehouse capacity, setting-review, and closure blockers."""
    table = warehouse_operability_fact_fqn()
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
    WAREHOUSE_NAME,
    CONTROL_SOURCE,
    SEVERITY,
    SIGNAL,
    CONTROL_STATE,
    CONTROL_RANK,
    CAPACITY_SCORE,
    QUERY_ROWS,
    QUEUE_PRESSURE_ROWS,
    SPILL_PRESSURE_ROWS,
    HIGH_LATENCY_ROWS,
    METERED_CREDITS,
    CREDIT_ALLOCATION_METHOD,
    REVIEW_ROWS,
    APPROVAL_REQUIRED_ROWS,
    ROLLBACK_REQUIRED_ROWS,
    SAVINGS_VERIFICATION_ROWS,
    OPEN_ACTIONS,
    OVERDUE_OPEN,
    FIXED_WITHOUT_VERIFICATION,
    VERIFIED_CLOSURES,
    OWNER_APPROVAL_GAP_ROWS,
    NEXT_CONTROL_ACTION,
    LAST_ACTIVITY_TS,
    LOAD_TS
FROM {table}
WHERE {where_clause}
ORDER BY
    CONTROL_RANK,
    OVERDUE_OPEN DESC,
    FIXED_WITHOUT_VERIFICATION DESC,
    QUEUE_PRESSURE_ROWS DESC,
    SPILL_PRESSURE_ROWS DESC,
    METERED_CREDITS DESC,
    LAST_ACTIVITY_TS DESC
LIMIT 100""".strip()


def _save_warehouse_setting_review_snapshot(
    session,
    findings: pd.DataFrame,
    *,
    company: str,
    environment: str,
    source: str = "",
) -> None:
    try:
        session.sql(build_warehouse_setting_review_ddl()).collect()
        for migration_sql in build_warehouse_setting_review_migration_sql():
            session.sql(migration_sql).collect()
        session.sql(_warehouse_setting_review_insert_sql(
            findings,
            company=company,
            environment=environment,
            source=source,
        )).collect()
        st.success("Saved the Warehouse Setting Review snapshot for approval and verification tracking.")
    except Exception as exc:
        st.error(f"Could not save Warehouse Setting Review snapshot: {format_snowflake_error(exc)}")
        st.info("Deploy the warehouse setting review table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry this save.")


def _warehouse_capacity_workflow_for(signal: str) -> str:
    signal = str(signal or "").upper()
    if "SPILL" in signal:
        return "Spill & Memory"
    if "CREDIT" in signal:
        return "Efficiency"
    if "QUEUE" in signal:
        return "Workload Heatmap"
    return "Overview & Scaling"


def _warehouse_capacity_priority_view(exceptions: pd.DataFrame) -> pd.DataFrame:
    if exceptions is None or exceptions.empty:
        return pd.DataFrame()
    rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    view = _annotate_warehouse_admin_readiness(exceptions)
    view["_RANK"] = view.get("SEVERITY", pd.Series(dtype=str)).map(rank).fillna(4)
    view["NEXT_ACTION"] = view.get("SIGNAL", pd.Series(dtype=str)).apply(lambda value: _warehouse_capacity_action_for(value)[0])
    view["NEXT_WORKFLOW"] = view.get("SIGNAL", pd.Series(dtype=str)).apply(_warehouse_capacity_workflow_for)
    return view.sort_values(["_RANK", "CAPACITY_SCORE", "METERED_CREDITS"], ascending=[True, True, False]).drop(columns=["_RANK"], errors="ignore")


def _warehouse_intervention_matrix(
    exceptions: pd.DataFrame,
    control_board: pd.DataFrame | None = None,
    closure: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Rank warehouses by whether DBAs can safely intervene now or need proof first."""
    priority = _warehouse_capacity_priority_view(exceptions)
    if priority.empty:
        return pd.DataFrame()

    control = control_board if isinstance(control_board, pd.DataFrame) else pd.DataFrame()
    closure_df = closure if isinstance(closure, pd.DataFrame) else pd.DataFrame()
    control_by_wh = {
        str(row.get("WAREHOUSE_NAME") or "").upper(): row
        for _, row in control.iterrows()
    } if not control.empty else {}
    closure_by_wh = {
        str(row.get("WAREHOUSE_NAME") or "").upper(): row
        for _, row in closure_df.iterrows()
    } if not closure_df.empty else {}

    rows: list[dict] = []
    for _, item in priority.head(25).iterrows():
        wh = str(item.get("WAREHOUSE_NAME") or "Unknown warehouse")
        control_row = control_by_wh.get(wh.upper(), {})
        closure_row = closure_by_wh.get(wh.upper(), {})
        signal = str(item.get("SIGNAL") or "")
        severity = str(item.get("SEVERITY") or "Medium")
        score = safe_float(item.get("CAPACITY_SCORE"))
        credits = safe_float(item.get("METERED_CREDITS"))
        queued = safe_int(item.get("QUEUED_QUERIES"))
        spill = safe_int(item.get("SPILL_QUERIES"))
        high_latency = safe_int(item.get("HIGH_LATENCY_QUERIES"))
        readiness = str(control_row.get("CONTROL_STATE") or item.get("ADMIN_READINESS") or "Review")
        blockers = str(control_row.get("AUDIT_BLOCKERS") or item.get("ADMIN_BLOCKERS") or "")
        closure_state = str(closure_row.get("CLOSURE_READINESS") or control_row.get("CLOSURE_READINESS") or "No recent action")
        savings_required = str(
            control_row.get("SAVINGS_VERIFICATION_REQUIRED")
            or item.get("SAVINGS_VERIFICATION_REQUIRED")
            or ""
        ).upper() == "YES"
        approval_required = str(
            control_row.get("APPROVAL_REQUIRED")
            or item.get("APPROVAL_REQUIRED")
            or ""
        ).upper() == "YES"
        audit_bad = any(token in readiness.upper() for token in ("BLOCK", "FAILED", "PENDING", "NO SETTING"))
        closure_bad = any(token in closure_state.upper() for token in ("OVERDUE", "WITHOUT VERIFICATION", "GAP"))

        if audit_bad or closure_bad or approval_required:
            state = "Proof Blocked"
            rank = 0
            decision = "Hold setting change until approval, audit, rollback, and closure evidence are attached."
        elif score < 65 or severity.upper() == "CRITICAL":
            state = "Intervene"
            rank = 1
            decision = "Run DBA setting review and verify queue, spill, latency, and credit impact after the change."
        elif savings_required or credits > 0:
            state = "Cost Review"
            rank = 2
            decision = "Quantify credit delta and savings hypothesis before claiming optimization value."
        else:
            state = "Watch"
            rank = 4
            decision = "Monitor pressure; avoid touching settings without a stronger service or cost signal."

        rows.append({
            "DBA_PRIORITY": f"P{rank}",
            "INTERVENTION_STATE": state,
            "WAREHOUSE_NAME": wh,
            "SEVERITY": severity,
            "SIGNAL": signal,
            "CAPACITY_SCORE": score,
            "METERED_CREDITS": credits,
            "PRESSURE_EVIDENCE": f"queued={queued:,}; spill={spill:,}; p95/latency rows={high_latency:,}",
            "CONTROL_STATE": readiness,
            "CLOSURE_READINESS": closure_state,
            "NEXT_DECISION": decision,
            "PROOF_REQUIRED": "owner approval, rollback SQL, execution audit, post-change service/cost verification",
            "NEXT_WORKFLOW": str(item.get("NEXT_WORKFLOW") or _warehouse_capacity_workflow_for(signal)),
            "_RANK": rank,
        })

    return pd.DataFrame(rows).sort_values(
        ["_RANK", "CAPACITY_SCORE", "METERED_CREDITS"],
        ascending=[True, True, False],
    ).drop(columns=["_RANK"], errors="ignore").reset_index(drop=True)


def _render_warehouse_watch_floor(score: int, exceptions: pd.DataFrame, summary_row: dict) -> None:
    priority = _warehouse_capacity_priority_view(exceptions).head(3)
    high_risk = 0
    if exceptions is not None and not exceptions.empty and "SEVERITY" in exceptions.columns:
        high_risk = int(exceptions["SEVERITY"].isin(["Critical", "High"]).sum())

    c1, c2, c3, c4 = st.columns([1.1, 1.1, 1.1, 2.4])
    c1.metric("Warehouse Readiness", f"{score}/100", _warehouse_capacity_rating(score))
    c2.metric("High-Risk Warehouses", f"{high_risk:,}", delta_color="inverse")
    c3.metric("Remote Spill", f"{safe_float(summary_row.get('REMOTE_SPILL_GB')):,.1f} GB", delta_color="inverse")
    with c4:
        if priority.empty:
            st.success("No urgent warehouse capacity exceptions crossed the selected thresholds.")
        else:
            first = priority.iloc[0]
            st.warning(
                f"First move: {first.get('SIGNAL', 'Warehouse pressure')} on "
                f"{first.get('WAREHOUSE_NAME', 'unknown warehouse')} -> {first.get('NEXT_ACTION', 'Review warehouse pressure.')}"
            )

    st.markdown("**Warehouse Watch Floor**")
    if priority.empty:
        st.caption("Use Overview & Scaling for periodic checks, or Efficiency after a cost spike.")
        return

    cols = st.columns(len(priority))
    for idx, (_, item) in enumerate(priority.iterrows()):
        workflow = str(item.get("NEXT_WORKFLOW") or "Overview & Scaling")
        with cols[idx]:
            st.markdown(f"**{item.get('SEVERITY', 'Medium')}: {item.get('SIGNAL', '')}**")
            st.caption(f"{item.get('WAREHOUSE_NAME', 'unknown warehouse')} | Score {safe_float(item.get('CAPACITY_SCORE')):,.1f}")
            st.caption(
                f"Queued {safe_int(item.get('QUEUED_QUERIES')):,} | "
                f"Spill {safe_int(item.get('SPILL_QUERIES')):,} | "
                f"{format_credits(safe_float(item.get('METERED_CREDITS')))}"
            )
            st.write(str(item.get("NEXT_ACTION", "")))
            if st.button(f"Open {workflow}", key=f"wh_watch_floor_{idx}_{workflow}", width="stretch"):
                warehouse = str(item.get("WAREHOUSE_NAME") or "")
                if warehouse:
                    st.session_state["global_warehouse"] = warehouse
                    st.session_state["wh_filter"] = warehouse
                    st.session_state["lm_wh"] = warehouse
                    for stale_key in ["wh_df_wh", "wh_efficiency", "wh_df_sp", "wh_df_hm"]:
                        st.session_state.pop(stale_key, None)
                st.session_state["warehouse_health_view"] = workflow
                st.rerun()


def _build_warehouse_capacity_markdown(
    company: str,
    days: int,
    score: int,
    summary_row: dict,
    exceptions: pd.DataFrame,
) -> str:
    exceptions_view = _annotate_warehouse_admin_readiness(exceptions)
    lines = [
        f"# OVERWATCH Warehouse Capacity Brief - {company}",
        "",
        f"- Lookback: {days} days",
        f"- Capacity score: {score} ({_warehouse_capacity_rating(score)})",
        f"- Warehouses active: {safe_int(summary_row.get('WAREHOUSES_ACTIVE')):,}",
        f"- Queries: {safe_int(summary_row.get('TOTAL_QUERIES')):,}",
        f"- Queued queries: {safe_int(summary_row.get('QUEUED_QUERIES')):,}",
        f"- Spill queries: {safe_int(summary_row.get('SPILL_QUERIES')):,}",
        f"- Credit movement: {safe_float(summary_row.get('CREDIT_SPIKE_PCT')):,.1f}%",
        "",
        "## DBA Narrative",
        (
            "Use this brief to decide whether warehouse pressure is capacity, memory, workload shape, "
            "or cost drift. It is intended to support DBA action and executive reporting without forcing "
            "leadership through raw warehouse telemetry."
        ),
        "",
        "## Top Warehouse Exceptions",
    ]
    if exceptions is None or exceptions.empty:
        lines.append("- No warehouse capacity exceptions found for the selected scope.")
    else:
        for _, row in exceptions_view.head(10).iterrows():
            lines.append(
                "- "
                f"{row.get('SEVERITY', 'Watch')} | {row.get('SIGNAL', 'Unknown')} | "
                f"{row.get('WAREHOUSE_NAME', '')} | score {safe_float(row.get('CAPACITY_SCORE')):,.1f} | "
                f"{safe_float(row.get('METERED_CREDITS')):,.2f} credits | "
                f"{row.get('SETTING_CHANGE_CANDIDATE', 'Review warehouse settings')}"
            )
    lines.extend([
        "",
        "## Settings Change Readiness",
        (
            "- Warehouse Health findings are not direct change orders. Route setting changes through "
            "DBA Tools > Warehouse Settings Manager so current values, owner approval, rollback SQL, "
            "and post-change verification are captured."
        ),
        "",
        "## Evidence Limits",
        "- ACCOUNT_USAGE can lag; Live Monitor should be used for current in-flight warehouse pressure.",
        "- Per-warehouse pressure is inferred from query history plus metering history, not Snowsight internals.",
        "- Company scope follows configured warehouse/database/user naming rules.",
    ])
    return "\n".join(lines)


def _build_warehouse_capacity_sql(session, days: int) -> tuple[str, str]:
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "WAREHOUSE_SIZE",
            "QUEUED_OVERLOAD_TIME",
            "QUEUED_PROVISIONING_TIME",
            "QUEUED_REPAIR_TIME",
            "BYTES_SPILLED_TO_LOCAL_STORAGE",
            "BYTES_SPILLED_TO_REMOTE_STORAGE",
        ],
    ))
    wm_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
        ["CREDITS_USED_COMPUTE", "CREDITS_USED"],
    ))
    warehouse_size_expr = "MAX(q.warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR"
    queue_ms_expr = " + ".join([
        "COALESCE(q.queued_overload_time, 0)" if "QUEUED_OVERLOAD_TIME" in qh_cols else "0",
        "COALESCE(q.queued_provisioning_time, 0)" if "QUEUED_PROVISIONING_TIME" in qh_cols else "0",
        "COALESCE(q.queued_repair_time, 0)" if "QUEUED_REPAIR_TIME" in qh_cols else "0",
    ])
    local_spill_expr = (
        "COALESCE(q.bytes_spilled_to_local_storage, 0)"
        if "BYTES_SPILLED_TO_LOCAL_STORAGE" in qh_cols
        else "0"
    )
    remote_spill_expr = (
        "COALESCE(q.bytes_spilled_to_remote_storage, 0)"
        if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
        else "0"
    )
    spill_bytes_expr = f"{local_spill_expr} + {remote_spill_expr}"
    meter_expr = (
        "COALESCE(m.credits_used_compute, m.credits_used)"
        if {"CREDITS_USED_COMPUTE", "CREDITS_USED"}.issubset(wm_cols)
        else "m.credits_used"
    )
    filters_q = get_global_filter_clause(
        date_col="q.start_time",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
    )
    filters_m = get_wh_filter_clause("m.warehouse_name")
    summary_sql = f"""
        WITH query_rollup AS (
            SELECT
                q.warehouse_name,
                COUNT(*) AS total_queries,
                SUM(IFF(({queue_ms_expr}) > 0, 1, 0)) AS queued_queries,
                SUM(IFF(({spill_bytes_expr}) > 0, 1, 0)) AS spill_queries,
                SUM(IFF(q.total_elapsed_time >= 30000, 1, 0)) AS high_latency_queries,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY q.total_elapsed_time / 1000.0) AS p95_elapsed_sec,
                SUM({remote_spill_expr}) / POWER(1024, 3) AS remote_spill_gb
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {filters_q}
            GROUP BY q.warehouse_name
        ),
        metering AS (
            SELECT
                m.warehouse_name,
                SUM(IFF(m.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP()),
                        {meter_expr}, 0)) AS current_credits,
                SUM(IFF(m.start_time >= DATEADD('day', -{int(days) * 2}, CURRENT_TIMESTAMP())
                         AND m.start_time < DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP()),
                        {meter_expr}, 0)) AS prior_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY m
            WHERE m.start_time >= DATEADD('day', -{int(days) * 2}, CURRENT_TIMESTAMP())
              {filters_m}
            GROUP BY m.warehouse_name
        ),
        combined AS (
            SELECT
                COALESCE(q.warehouse_name, m.warehouse_name) AS warehouse_name,
                COALESCE(q.total_queries, 0) AS total_queries,
                COALESCE(q.queued_queries, 0) AS queued_queries,
                COALESCE(q.spill_queries, 0) AS spill_queries,
                COALESCE(q.high_latency_queries, 0) AS high_latency_queries,
                COALESCE(q.p95_elapsed_sec, 0) AS p95_elapsed_sec,
                COALESCE(q.remote_spill_gb, 0) AS remote_spill_gb,
                COALESCE(m.current_credits, 0) AS current_credits,
                COALESCE(m.prior_credits, 0) AS prior_credits,
                (COALESCE(m.current_credits, 0) - COALESCE(m.prior_credits, 0))
                    / NULLIF(COALESCE(m.prior_credits, 0), 0) * 100 AS credit_spike_pct
            FROM query_rollup q
            FULL OUTER JOIN metering m ON q.warehouse_name = m.warehouse_name
        )
        SELECT
            COUNT(DISTINCT warehouse_name) AS warehouses_active,
            SUM(total_queries) AS total_queries,
            SUM(queued_queries) AS queued_queries,
            SUM(spill_queries) AS spill_queries,
            SUM(high_latency_queries) AS high_latency_queries,
            SUM(current_credits) AS metered_credits,
            SUM(prior_credits) AS prior_credits,
            (SUM(current_credits) - SUM(prior_credits)) / NULLIF(SUM(prior_credits), 0) * 100 AS credit_spike_pct,
            MAX(p95_elapsed_sec) AS worst_p95_elapsed_sec,
            SUM(remote_spill_gb) AS remote_spill_gb
        FROM combined
    """
    exceptions_sql = f"""
        WITH query_rollup AS (
            SELECT
                q.warehouse_name,
                {warehouse_size_expr} AS warehouse_size,
                COUNT(*) AS total_queries,
                SUM(IFF(({queue_ms_expr}) > 0, 1, 0)) AS queued_queries,
                SUM(IFF(({spill_bytes_expr}) > 0, 1, 0)) AS spill_queries,
                SUM(IFF(q.total_elapsed_time >= 30000, 1, 0)) AS high_latency_queries,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY q.total_elapsed_time / 1000.0) AS p95_elapsed_sec,
                SUM({remote_spill_expr}) / POWER(1024, 3) AS remote_spill_gb
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {filters_q}
            GROUP BY q.warehouse_name
        ),
        metering AS (
            SELECT
                m.warehouse_name,
                SUM(IFF(m.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP()),
                        {meter_expr}, 0)) AS current_credits,
                SUM(IFF(m.start_time >= DATEADD('day', -{int(days) * 2}, CURRENT_TIMESTAMP())
                         AND m.start_time < DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP()),
                        {meter_expr}, 0)) AS prior_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY m
            WHERE m.start_time >= DATEADD('day', -{int(days) * 2}, CURRENT_TIMESTAMP())
              {filters_m}
            GROUP BY m.warehouse_name
        ),
        combined AS (
            SELECT
                COALESCE(q.warehouse_name, m.warehouse_name) AS warehouse_name,
                q.warehouse_size,
                COALESCE(q.total_queries, 0) AS total_queries,
                COALESCE(q.queued_queries, 0) AS queued_queries,
                COALESCE(q.spill_queries, 0) AS spill_queries,
                COALESCE(q.high_latency_queries, 0) AS high_latency_queries,
                COALESCE(q.p95_elapsed_sec, 0) AS p95_elapsed_sec,
                COALESCE(q.remote_spill_gb, 0) AS remote_spill_gb,
                COALESCE(m.current_credits, 0) AS current_credits,
                COALESCE(m.prior_credits, 0) AS prior_credits,
                (COALESCE(m.current_credits, 0) - COALESCE(m.prior_credits, 0))
                    / NULLIF(COALESCE(m.prior_credits, 0), 0) * 100 AS credit_spike_pct
            FROM query_rollup q
            FULL OUTER JOIN metering m ON q.warehouse_name = m.warehouse_name
        )
        SELECT
            CASE
                WHEN queued_queries >= 20 OR remote_spill_gb >= 20 THEN 'Critical'
                WHEN credit_spike_pct >= 50 OR spill_queries >= 10 OR high_latency_queries >= 25 THEN 'High'
                ELSE 'Medium'
            END AS severity,
            CASE
                WHEN queued_queries >= 20 THEN 'Queue Pressure'
                WHEN remote_spill_gb >= 1 THEN 'Memory Spill'
                WHEN credit_spike_pct >= 25 THEN 'Credit Spike'
                ELSE 'Latency Pressure'
            END AS signal,
            warehouse_name,
            warehouse_size,
            total_queries,
            queued_queries,
            spill_queries,
            high_latency_queries,
            ROUND(p95_elapsed_sec, 2) AS p95_elapsed_sec,
            ROUND(remote_spill_gb, 2) AS remote_spill_gb,
            ROUND(current_credits, 4) AS metered_credits,
            ROUND(prior_credits, 4) AS prior_credits,
            ROUND(COALESCE(credit_spike_pct, 0), 1) AS credit_spike_pct,
            ROUND(100
                - LEAST(queued_queries * 100.0 / NULLIF(total_queries, 0) * 2.0, 28)
                - LEAST(spill_queries * 100.0 / NULLIF(total_queries, 0) * 1.8, 24)
                - LEAST(high_latency_queries * 100.0 / NULLIF(total_queries, 0) * 1.1, 18)
                - LEAST(GREATEST(COALESCE(credit_spike_pct, 0), 0) / 4, 20), 1) AS capacity_score
        FROM combined
        WHERE queued_queries > 0
           OR spill_queries > 0
           OR high_latency_queries > 0
           OR credit_spike_pct >= 25
        ORDER BY
            CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 ELSE 3 END,
            capacity_score ASC,
            metered_credits DESC
        LIMIT 100
    """
    return summary_sql, exceptions_sql


def _queue_capacity_findings(session, exceptions: pd.DataFrame) -> int:
    if exceptions is None or exceptions.empty:
        return 0
    company = get_active_company()
    environment = get_active_environment()
    exceptions = _annotate_warehouse_admin_readiness(exceptions)
    actions = []
    for _, row in exceptions.head(50).iterrows():
        wh = str(row.get("WAREHOUSE_NAME", ""))
        signal = str(row.get("SIGNAL", "Warehouse Pressure"))
        action_text, _ = _warehouse_capacity_action_for(signal)
        verification_sql = _warehouse_capacity_verification_sql(
            wh,
            days=7,
            environment=environment,
            company=company,
        )
        finding = (
            f"{signal} on {wh}: capacity score={safe_float(row.get('CAPACITY_SCORE')):,.1f}, "
            f"queued={safe_int(row.get('QUEUED_QUERIES')):,}, spill={safe_int(row.get('SPILL_QUERIES')):,}, "
            f"credits={safe_float(row.get('METERED_CREDITS')):,.2f}; "
            f"{row.get('PRESSURE_EVIDENCE', '')}."
        )
        actions.append({
            "Action ID": make_action_id("Warehouse Capacity", wh, finding),
            "Source": "Warehouse Health - Capacity Brief",
            "Category": "Warehouse Capacity",
            "Severity": row.get("SEVERITY", "High"),
            "Entity Type": "Warehouse",
            "Entity": wh,
            "Owner": row.get("OWNER", "Platform DBA"),
            "Owner Email": row.get("OWNER_EMAIL", ""),
            "Oncall Primary": row.get("ONCALL_PRIMARY", ""),
            "Oncall Secondary": row.get("ONCALL_SECONDARY", ""),
            "Approval Group": row.get("APPROVAL_GROUP", row.get("APPROVER", "Warehouse Owner / DBA Lead")),
            "Escalation Target": row.get("ESCALATION_TARGET", "DBA Lead"),
            "Owner Source": row.get("OWNER_SOURCE", ""),
            "Owner Evidence": row.get("OWNER_EVIDENCE", ""),
            "Finding": finding,
            "Action": (
                f"{action_text} {row.get('SAFE_CHANGE_PATH', '')} "
                f"Owner approval from {row.get('APPROVER', 'Warehouse Owner / DBA Lead')} is required. "
                "Actual warehouse changes must be generated from the Warehouse Settings Manager."
            ),
            "Estimated Monthly Savings": 0,
            "Generated SQL Fix": _warehouse_capacity_review_sql(row),
            "Proof Query": verification_sql,
            "Verification Status": "Pending",
            "Verification Query": verification_sql,
            "Approver": row.get("APPROVER", "Warehouse Owner / DBA Lead"),
            "Owner Approval Status": "Requested",
            "Owner Approval Note": (
                f"{row.get('CHANGE_RISK', '')} "
                f"Escalation: {row.get('ESCALATION_TARGET', 'DBA Lead')}. "
                f"Rollback required: {row.get('ROLLBACK_REQUIRED', 'Yes')}; "
                f"savings verification required: {row.get('SAVINGS_VERIFICATION_REQUIRED', 'No')}."
            ),
            "Recovery Evidence": (
                f"Baseline: {row.get('PRESSURE_EVIDENCE', '')}. "
                f"Closure requires post-change verification: {row.get('POST_CHANGE_VERIFICATION', '')}"
            ),
            "Recovery Audit State": "Warehouse Change Verification Pending",
            "Baseline Value": safe_float(row.get("CAPACITY_SCORE")),
            "Current Value": safe_float(row.get("CAPACITY_SCORE")),
            "Measured Delta": 0,
            "Company": company,
            "Environment": environment,
        })
    return upsert_actions(session, actions)


def _render_capacity_brief(company: str, environment: str) -> None:
    with st.expander("Capacity Brief", expanded=bool(st.session_state.get("exceptions_only_mode"))):
        days = st.slider("Capacity lookback (days)", 1, 30, 7, key="wh_capacity_days")
        if st.button("Load Capacity Brief", key="wh_capacity_load"):
            with st.spinner("Building warehouse capacity brief..."):
                try:
                    session = _warehouse_action_session("load the warehouse capacity brief")
                    if session is None:
                        return
                    summary_sql, exceptions_sql = _build_warehouse_capacity_sql(session, days)
                    summary = run_query(
                        summary_sql,
                        ttl_key=f"wh_capacity_summary_{company}_{environment}_{days}",
                        tier="historical",
                        section="Warehouse Health",
                    )
                    exceptions = run_query(
                        exceptions_sql,
                        ttl_key=f"wh_capacity_exceptions_{company}_{environment}_{days}",
                        tier="historical",
                        section="Warehouse Health",
                    )
                    st.session_state["wh_capacity_summary"] = summary
                    st.session_state["wh_capacity_exceptions"] = exceptions
                    st.session_state["wh_capacity_sql"] = {
                        "summary": summary_sql,
                        "exceptions": exceptions_sql,
                    }
                    st.session_state["wh_capacity_meta"] = _warehouse_scope_meta(company, environment, days)
                    try:
                        operability_sql = _warehouse_operability_fact_sql(days, company, environment)
                        st.session_state["wh_operability_fact_sql"] = operability_sql
                        st.session_state["wh_operability_fact"] = run_query(
                            operability_sql,
                            ttl_key=f"wh_operability_fact_{company}_{environment}_{days}",
                            tier="standard",
                            section="Warehouse Health",
                        )
                        st.session_state.pop("wh_operability_fact_error", None)
                    except Exception as fact_exc:
                        st.session_state["wh_operability_fact"] = pd.DataFrame()
                        st.session_state["wh_operability_fact_error"] = format_snowflake_error(fact_exc)
                except Exception as e:
                    st.warning(f"Capacity brief unavailable in this role/context: {format_snowflake_error(e)}")

        summary = st.session_state.get("wh_capacity_summary")
        exceptions = st.session_state.get("wh_capacity_exceptions")
        meta = st.session_state.get("wh_capacity_meta", {})
        if (
            summary is None
            or summary.empty
            or meta.get("company") != company
            or meta.get("environment") != environment
            or meta.get("days") != int(days)
        ):
            return
        exceptions = _warehouse_capacity_priority_view(exceptions)
        row = summary.iloc[0].to_dict()
        score = _warehouse_capacity_score(
            queued_queries=safe_int(row.get("QUEUED_QUERIES")),
            spill_queries=safe_int(row.get("SPILL_QUERIES")),
            high_latency_queries=safe_int(row.get("HIGH_LATENCY_QUERIES")),
            total_queries=safe_int(row.get("TOTAL_QUERIES")),
            credit_spike_pct=safe_float(row.get("CREDIT_SPIKE_PCT")),
        )
        rating = _warehouse_capacity_rating(score)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Capacity Score", score, rating)
        c2.metric("Queued", f"{safe_int(row.get('QUEUED_QUERIES')):,}", delta_color="inverse")
        c3.metric("Spill", f"{safe_int(row.get('SPILL_QUERIES')):,}", delta_color="inverse")
        c4.metric("Metered Credits", format_credits(safe_float(row.get("METERED_CREDITS"))))
        if score < 65:
            st.error("Capacity risk: warehouse pressure is high enough to affect service levels or cost control.")
        elif score < 78:
            st.warning("Pressure: review exception warehouses before approving workload growth.")
        elif score < 90:
            st.info("Watch: warehouse pressure exists, but it is not currently dominant.")
        else:
            st.success("Healthy: no major warehouse pressure signal in this scope.")

        operability_fact = st.session_state.get("wh_operability_fact")
        if operability_fact is not None and not operability_fact.empty:
            st.subheader("Warehouse Operability Mart")
            f1, f2, f3, f4 = st.columns(4)
            f1.metric("Fact Rows", f"{len(operability_fact):,}")
            f2.metric("Overdue", f"{int(operability_fact.get('OVERDUE_OPEN', pd.Series(dtype=int)).sum()):,}", delta_color="inverse")
            f3.metric(
                "Pressure Signals",
                f"{int(operability_fact.get('QUEUE_PRESSURE_ROWS', pd.Series(dtype=int)).sum() + operability_fact.get('SPILL_PRESSURE_ROWS', pd.Series(dtype=int)).sum()):,}",
                delta_color="inverse",
            )
            f4.metric("Verified Closures", f"{int(operability_fact.get('VERIFIED_CLOSURES', pd.Series(dtype=int)).sum()):,}")
            render_priority_dataframe(
                operability_fact,
                title="Pre-aggregated warehouse blockers",
                priority_columns=[
                    "SNAPSHOT_DATE", "CONTROL_STATE", "CONTROL_SOURCE", "ENVIRONMENT",
                    "WAREHOUSE_NAME", "SEVERITY", "SIGNAL", "CAPACITY_SCORE",
                    "QUERY_ROWS", "QUEUE_PRESSURE_ROWS", "SPILL_PRESSURE_ROWS",
                    "HIGH_LATENCY_ROWS", "METERED_CREDITS", "CREDIT_ALLOCATION_METHOD", "REVIEW_ROWS",
                    "APPROVAL_REQUIRED_ROWS", "ROLLBACK_REQUIRED_ROWS",
                    "SAVINGS_VERIFICATION_ROWS", "OPEN_ACTIONS", "OVERDUE_OPEN",
                    "FIXED_WITHOUT_VERIFICATION", "VERIFIED_CLOSURES", "NEXT_CONTROL_ACTION",
                ],
                sort_by=["CONTROL_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "CAPACITY_SCORE"],
                ascending=[True, False, False, True],
                raw_label="All warehouse operability facts",
                height=300,
            )
            with st.expander("Warehouse operability fact query", expanded=False):
                st.code(st.session_state.get("wh_operability_fact_sql", ""), language="sql")
        elif st.session_state.get("wh_operability_fact_error"):
            st.caption(
                "Warehouse operability mart not available yet; deploy or refresh "
                "`FACT_WAREHOUSE_OPERABILITY_DAILY` to enable the fast blocker surface."
            )

        _render_warehouse_watch_floor(score, exceptions, row)
        if exceptions is not None and not exceptions.empty:
            audit_col, audit_hint_col = st.columns([1, 3])
            with audit_col:
                if st.button("Load Execution Audit", key="wh_setting_execution_audit_load", width="stretch"):
                    try:
                        audit_sql = _warehouse_setting_execution_audit_sql(30, company, environment)
                        audit = run_query(
                            audit_sql,
                            ttl_key=f"wh_setting_execution_audit_{company}_{environment}_30",
                            tier="standard",
                            section="Warehouse Health",
                        )
                        st.session_state["wh_setting_execution_audit"] = audit
                        st.session_state["wh_setting_execution_audit_sql"] = audit_sql
                        st.session_state["wh_setting_execution_audit_meta"] = _warehouse_scope_meta(
                            company, environment, 30
                        )
                    except Exception as exc:
                        st.session_state["wh_setting_execution_audit"] = pd.DataFrame()
                        st.warning(f"Warehouse execution audit unavailable: {format_snowflake_error(exc)}")
            with audit_hint_col:
                st.caption(
                    "Joins setting-review snapshots to DBA Tools ALTER WAREHOUSE audit rows so changes have "
                    "approval, rollback, SQL hash, executor, and verification evidence."
                )

            closure_days_for_board = safe_int(st.session_state.get("wh_action_closure_days", 30)) or 30
            closure_for_board = st.session_state.get("wh_action_closure")
            if not _warehouse_meta_matches(
                st.session_state.get("wh_action_closure_meta"),
                _warehouse_scope_meta(company, environment, closure_days_for_board),
            ):
                closure_for_board = pd.DataFrame()
            audit_for_board = st.session_state.get("wh_setting_execution_audit")
            if not _warehouse_meta_matches(
                st.session_state.get("wh_setting_execution_audit_meta"),
                _warehouse_scope_meta(company, environment, 30),
            ):
                audit_for_board = pd.DataFrame()

            control_board = _warehouse_setting_control_board(
                exceptions,
                owner_inventory=st.session_state.get("wh_owner_inventory"),
                closure=closure_for_board,
                execution_audit=audit_for_board,
            )
            operator_moves = _warehouse_operator_next_moves(
                score=score,
                exceptions=exceptions,
                control_board=control_board,
                closure=closure_for_board,
                execution_audit=audit_for_board,
                operability_fact=operability_fact,
            )
            render_priority_dataframe(
                operator_moves,
                title="Warehouse operator next-move gates",
                priority_columns=["GATE", "STATE", "COUNT", "PROOF_REQUIRED", "NEXT_ACTION"],
                sort_by=["GATE_RANK", "COUNT"],
                ascending=[True, False],
                raw_label="All warehouse operator gates",
                height=220,
                max_rows=5,
            )
            intervention_matrix = _warehouse_intervention_matrix(
                exceptions,
                control_board=control_board,
                closure=closure_for_board,
            )
            if not intervention_matrix.empty:
                render_priority_dataframe(
                    intervention_matrix,
                    title="Warehouse DBA intervention matrix",
                    priority_columns=[
                        "DBA_PRIORITY", "INTERVENTION_STATE", "WAREHOUSE_NAME", "SEVERITY", "SIGNAL",
                        "CAPACITY_SCORE", "METERED_CREDITS", "PRESSURE_EVIDENCE",
                        "CONTROL_STATE", "CLOSURE_READINESS", "NEXT_DECISION",
                        "PROOF_REQUIRED", "NEXT_WORKFLOW",
                    ],
                    sort_by=["DBA_PRIORITY", "CAPACITY_SCORE", "METERED_CREDITS"],
                    ascending=[True, True, False],
                    raw_label="All warehouse DBA intervention rows",
                    height=280,
                    max_rows=8,
                    column_config={
                        "CAPACITY_SCORE": st.column_config.ProgressColumn("Capacity", min_value=0, max_value=100, format="%.1f"),
                    },
                )
            if not control_board.empty:
                render_priority_dataframe(
                    control_board,
                    title="Warehouse setting control board",
                    priority_columns=[
                        "CONTROL_STATE", "WAREHOUSE_NAME", "SEVERITY", "SIGNAL",
                        "CAPACITY_SCORE", "METERED_CREDITS", "GOVERNANCE_READINESS",
                        "AUDIT_READINESS", "AUDIT_BLOCKERS", "CLOSURE_READINESS",
                        "AUDIT_ROWS", "SUCCESSFUL_CHANGES", "FAILED_CHANGES",
                        "LAST_EXECUTION_STATUS", "APPROVAL_REQUIRED", "ROLLBACK_REQUIRED",
                        "SAVINGS_VERIFICATION_REQUIRED", "NEXT_CONTROL_ACTION",
                    ],
                    sort_by=["CONTROL_RANK", "CAPACITY_SCORE", "METERED_CREDITS"],
                    ascending=[True, True, False],
                    raw_label="All warehouse setting control rows",
                    height=300,
                    max_rows=12,
                    column_config={
                        "CAPACITY_SCORE": st.column_config.ProgressColumn("Capacity", min_value=0, max_value=100, format="%.1f"),
                    },
                )
        st.divider()

        if exceptions is not None and not exceptions.empty:
            render_priority_dataframe(
                exceptions,
                title="Warehouse capacity exceptions to work first",
                priority_columns=[
                    "SEVERITY", "SIGNAL", "WAREHOUSE_NAME", "WAREHOUSE_SIZE",
                    "QUEUED_QUERIES", "SPILL_QUERIES", "HIGH_LATENCY_QUERIES",
                    "METERED_CREDITS", "ADMIN_READINESS", "SETTING_CHANGE_CANDIDATE",
                    "OWNER", "ESCALATION_TARGET", "APPROVER",
                    "APPROVAL_REQUIRED", "ROLLBACK_REQUIRED", "SAVINGS_VERIFICATION_REQUIRED", "NEXT_ACTION",
                ],
                sort_by=["QUEUED_QUERIES", "SPILL_QUERIES", "HIGH_LATENCY_QUERIES", "METERED_CREDITS"],
                ascending=[False, False, False, False],
                raw_label="All warehouse capacity exceptions",
            )
            save_col, setup_col = st.columns([1, 2])
            with save_col:
                if st.button("Save Setting Review Snapshot", key="wh_setting_review_snapshot", width="stretch"):
                    session = _warehouse_action_session("save a warehouse setting review snapshot")
                    if session is not None:
                        _save_warehouse_setting_review_snapshot(
                            session,
                            exceptions,
                            company=company,
                            environment=environment,
                            source="Warehouse Health Capacity Brief",
                        )
            with setup_col:
                st.caption(
                    "Snapshot stores owner approval path, rollback requirement, baseline pressure, and post-change verification SQL."
                )
            with st.expander("Warehouse Setting Review Trend", expanded=False):
                trend_days = st.slider("Setting review trend days", 7, 180, 30, key="wh_setting_review_trend_days")
                if st.button("Load Setting Review Trend", key="wh_setting_review_trend_load"):
                    try:
                        trend_sql = _warehouse_setting_review_history_sql(trend_days, company, environment)
                        trend = run_query(
                            trend_sql,
                            ttl_key=f"wh_setting_review_trend_{company}_{environment}_{trend_days}",
                            tier="standard",
                            section="Warehouse Health",
                        )
                        st.session_state["wh_setting_review_trend"] = trend
                        st.session_state["wh_setting_review_trend_sql"] = trend_sql
                    except Exception as exc:
                        st.error(f"Unable to load warehouse setting review trend: {format_snowflake_error(exc)}")
                trend = st.session_state.get("wh_setting_review_trend")
                if trend is not None and not trend.empty:
                    render_priority_dataframe(
                        trend,
                        title="Persistent warehouse setting review backlog",
                        priority_columns=[
                            "WAREHOUSE_NAME", "OWNER", "ESCALATION_TARGET", "REVIEW_ROWS",
                            "APPROVAL_REQUIRED_ROWS", "ROLLBACK_REQUIRED_ROWS",
                            "SAVINGS_VERIFICATION_ROWS", "WORST_BASELINE_CAPACITY_SCORE",
                            "MAX_BASELINE_QUEUED_QUERIES", "MAX_BASELINE_SPILL_QUERIES",
                            "LAST_SIGNAL", "LAST_SETTING_CHANGE_CANDIDATE",
                        ],
                        sort_by=["WORST_BASELINE_CAPACITY_SCORE", "APPROVAL_REQUIRED_ROWS", "LAST_SNAPSHOT_TS"],
                        ascending=[True, False, False],
                        raw_label="All persisted warehouse setting reviews",
                        height=260,
                    )
                with st.expander("Warehouse setting review setup SQL", expanded=False):
                    st.code(build_warehouse_setting_review_ddl(), language="sql")
            with st.expander("Warehouse Action Closure Analytics", expanded=False):
                st.caption(
                    "Uses Warehouse Health action-queue rows to show which capacity or efficiency actions are open, "
                    "overdue, missing owner approval, or closed without verification evidence."
                )
                closure_days = st.slider("Warehouse closure days", 7, 180, 30, key="wh_action_closure_days")
                if st.button("Load Warehouse Closure Analytics", key="wh_action_closure_load"):
                    try:
                        closure_sql = _warehouse_action_queue_closure_sql(closure_days, company, environment)
                        closure = run_query(
                            closure_sql,
                            ttl_key=f"wh_action_closure_{company}_{environment}_{closure_days}",
                            tier="standard",
                            section="Warehouse Health",
                        )
                        st.session_state["wh_action_closure"] = closure
                        st.session_state["wh_action_closure_sql"] = closure_sql
                        st.session_state["wh_action_closure_meta"] = _warehouse_scope_meta(
                            company, environment, closure_days
                        )
                    except Exception as exc:
                        st.session_state["wh_action_closure"] = pd.DataFrame()
                        st.warning(f"Warehouse closure analytics unavailable: {format_snowflake_error(exc)}")
                closure = st.session_state.get("wh_action_closure")
                closure_current = _warehouse_meta_matches(
                    st.session_state.get("wh_action_closure_meta"),
                    _warehouse_scope_meta(company, environment, closure_days),
                )
                if closure is not None and not closure.empty and closure_current:
                    render_priority_dataframe(
                        closure,
                        title="Warehouse closure evidence gaps",
                        priority_columns=[
                            "WAREHOUSE_NAME", "CLOSURE_READINESS", "OWNER", "APPROVER",
                            "TOTAL_ACTIONS", "OPEN_ACTIONS", "OVERDUE_OPEN",
                            "VERIFIED_CLOSURES", "FIXED_WITHOUT_VERIFICATION",
                            "OWNER_GAP_ROWS", "TICKET_GAP_ROWS", "APPROVER_GAP_ROWS",
                            "OWNER_APPROVAL_GAP_ROWS", "VERIFICATION_QUERY_GAP_ROWS",
                            "RECOVERY_RISK_ROWS", "NEXT_DUE_DATE", "LAST_STATUS", "NEXT_ACTION",
                        ],
                        sort_by=["CLOSURE_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "OPEN_ACTIONS"],
                        ascending=[True, False, False, False],
                        raw_label="All warehouse closure rows",
                        height=300,
                    )
                    with st.expander("Warehouse Closure Query", expanded=False):
                        st.code(st.session_state.get("wh_action_closure_sql", ""), language="sql")
                elif closure is not None and not closure.empty and not closure_current:
                    st.info("Loaded warehouse closure analytics are stale for the active scope. Reload closure analytics before acting.")
                elif closure is not None:
                    st.info("No Warehouse Health action-queue rows found for the selected scope.")
            with st.expander("Warehouse Execution Audit Evidence", expanded=False):
                audit = st.session_state.get("wh_setting_execution_audit")
                audit_current = _warehouse_meta_matches(
                    st.session_state.get("wh_setting_execution_audit_meta"),
                    _warehouse_scope_meta(company, environment, 30),
                )
                if audit is not None and not audit.empty and audit_current:
                    render_priority_dataframe(
                        audit,
                        title="Warehouse setting execution audit",
                        priority_columns=[
                            "WAREHOUSE_NAME", "EXECUTION_AUDIT_READINESS", "OWNER", "APPROVER",
                            "APPROVAL_STATE", "CHANGE_TICKET_ID", "REVIEW_ROWS", "AUDIT_ROWS",
                            "SUCCESSFUL_CHANGES", "FAILED_CHANGES", "LAST_SQL_HASH",
                            "LAST_EXECUTED_BY", "LAST_EXECUTED_ROLE", "LAST_EXECUTION_STATUS",
                            "LAST_EXECUTED_AT", "POST_CHANGE_VERIFICATION_STATUS",
                            "NEXT_CONTROL_ACTION",
                        ],
                        sort_by=["FAILED_CHANGES", "AUDIT_ROWS", "LAST_EXECUTED_AT"],
                        ascending=[False, False, False],
                        raw_label="All warehouse execution audit rows",
                        height=300,
                    )
                elif audit is not None and not audit.empty and not audit_current:
                    st.info("Loaded warehouse execution audit is stale for the active scope. Reload execution audit before acting.")
                elif audit is not None:
                    st.info("No warehouse setting review or ALTER WAREHOUSE audit rows found for the selected scope.")
                st.caption("Warehouse execution audit query")
                st.code(
                    st.session_state.get("wh_setting_execution_audit_sql")
                    or _warehouse_setting_execution_audit_sql(30, company, environment),
                    language="sql",
                )
            if st.button("Save Capacity Findings to Action Queue", key="wh_capacity_queue"):
                try:
                    session = _warehouse_action_session("save warehouse capacity findings to the action queue")
                    if session is not None:
                        saved = _queue_capacity_findings(session, exceptions)
                        st.success(f"Saved {saved} warehouse capacity findings to the action queue.")
                except Exception as e:
                    st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
                    st.info("Deploy the Action Queue table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry this save.")
        else:
            st.success("No warehouse capacity exceptions found for this scope.")

        st.download_button(
            "Download Capacity Brief",
            _build_warehouse_capacity_markdown(company, days, score, row, exceptions),
            file_name=f"overwatch_warehouse_capacity_{company.lower()}.md",
            mime="text/markdown",
            key="wh_capacity_download",
        )
        with st.expander("Proof SQL"):
            sql_map = st.session_state.get("wh_capacity_sql", {})
            st.code(sql_map.get("summary", ""), language="sql")
            st.code(sql_map.get("exceptions", ""), language="sql")


def _queue_efficiency_findings(session, df_eff: pd.DataFrame) -> None:
    if df_eff is None or df_eff.empty:
        st.info("No efficiency findings to queue.")
        return
    company = get_active_company()
    environment = get_active_environment()
    actions = []
    for _, row in df_eff[df_eff["EFFICIENCY_SCORE"] < 70].head(100).iterrows():
        wh = str(row.get("WAREHOUSE_NAME", ""))
        score = safe_float(row.get("EFFICIENCY_SCORE", 0))
        queue = safe_float(row.get("QUEUE_SEC_PER_CREDIT", 0))
        spill = safe_float(row.get("REMOTE_SPILL_GB_PER_CREDIT", 0))
        credits = safe_float(row.get("METERED_CREDITS", 0))
        severity = "High" if score < 50 or queue > 10 or spill > 5 else "Medium"
        owner_context = _warehouse_owner_context({
            "WAREHOUSE_NAME": wh,
            "SIGNAL": "Efficiency",
            "METERED_CREDITS": credits,
        })
        verification_sql = _warehouse_capacity_verification_sql(
            wh,
            days=7,
            environment=environment,
            company=company,
        )
        approver = _warehouse_approval_for({
            "WAREHOUSE_NAME": wh,
            "SIGNAL": "Efficiency",
            "OWNER": owner_context.get("owner", ""),
        })
        finding = (
            f"{wh} efficiency score is {score:.1f}; queue sec/credit={queue:.2f}, "
            f"spill GB/credit={spill:.2f}; metered credits={credits:.2f}."
        )
        actions.append({
            "Action ID": make_action_id("Warehouse Efficiency", wh, finding),
            "Source": "Warehouse Health - Efficiency",
            "Severity": severity,
            "Category": "Warehouse Efficiency",
            "Entity Type": "Warehouse",
            "Entity": wh,
            "Owner": owner_context.get("owner", "Platform DBA"),
            "Owner Email": owner_context.get("owner_email", ""),
            "Oncall Primary": owner_context.get("oncall_primary", ""),
            "Oncall Secondary": owner_context.get("oncall_secondary", ""),
            "Approval Group": owner_context.get("approval_group", approver),
            "Escalation Target": owner_context.get("escalation", "DBA Lead"),
            "Owner Source": owner_context.get("source", ""),
            "Owner Evidence": owner_context.get("owner_evidence", ""),
            "Finding": finding,
            "Action": (
                "Review queue, spill, cache, and credit/query patterns. Route setting changes through "
                "Warehouse Settings Manager so current values, owner approval, rollback SQL, and post-change "
                "verification are captured."
            ),
            "Estimated Monthly Savings": 0.0,
            "Generated SQL Fix": "\n".join([
                f"-- Review {wh} efficiency before changing warehouse settings.",
                "-- If queue dominates, compare multi-cluster settings and workload routing.",
                "-- If spill dominates, inspect top spilling query profiles before considering size changes.",
                "-- Do not execute warehouse DDL from this action; generate reviewed SQL in Warehouse Settings Manager.",
            ]),
            "Proof Query": verification_sql,
            "Verification Query": verification_sql,
            "Verification Status": "Pending",
            "Approver": approver,
            "Owner Approval Status": "Requested",
            "Owner Approval Note": (
                f"Efficiency score {score:.1f}. Owner evidence: {owner_context.get('owner_evidence', '')}. "
                "Setting changes require owner approval, rollback SQL, and post-change verification."
            ),
            "Recovery Evidence": (
                f"Baseline efficiency score={score:.1f}; queue sec/credit={queue:.2f}; "
                f"remote spill GB/credit={spill:.2f}; metered credits={credits:.2f}. "
                "Closure requires verified queue/spill/credit evidence for the same warehouse and environment."
            ),
            "Recovery Audit State": "Warehouse Efficiency Verification Pending",
            "Recovery SLA Target Hours": 24 if severity == "High" else 72,
            "Baseline Value": score,
            "Current Value": score,
            "Measured Delta": 0,
            "Company": company,
            "Environment": environment,
        })
    if not actions:
        st.success("No warehouses below the queue threshold.")
        return
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} warehouse efficiency findings to the action queue.")
    except Exception as e:
        st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
        st.info("Deploy the Action Queue table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry this save.")


def _render_warehouse_ownership_panel(company: str, environment: str) -> None:
    with st.expander("Warehouse Ownership Readiness", expanded=False):
        st.caption(
            "Checks recent warehouse usage against warehouse tags and the owner directory before DBA setting changes are approved."
        )
        owner_days = st.slider("Ownership usage days", 7, 90, 30, key="wh_owner_inventory_days")
        owner_query_days = min(int(owner_days), 30)
        if owner_query_days < int(owner_days):
            st.warning("Warehouse ownership readiness live fallback is capped at 30 days to avoid broad usage scans.")
        if st.button("Load Warehouse Ownership Readiness", key="wh_owner_inventory_load"):
            try:
                owner_sql = _warehouse_owner_inventory_sql(owner_query_days, company, environment)
                owner_inventory = run_query(
                    owner_sql,
                    ttl_key=f"wh_owner_inventory_{company}_{environment}_{owner_query_days}",
                    tier="standard",
                    section="Warehouse Health",
                )
                st.session_state["wh_owner_inventory"] = _annotate_warehouse_owner_inventory(owner_inventory)
                st.session_state["wh_owner_inventory_sql"] = owner_sql
                st.session_state["wh_owner_inventory_meta"] = _warehouse_scope_meta(
                    company, environment, owner_query_days
                )
            except Exception as exc:
                st.session_state["wh_owner_inventory"] = pd.DataFrame()
                st.warning(f"Warehouse ownership readiness unavailable: {format_snowflake_error(exc)}")

        owner_inventory = st.session_state.get("wh_owner_inventory")
        if owner_inventory is None:
            st.info("Load this before approving warehouse setting changes or queuing capacity actions.")
            with st.expander("Ownership readiness query", expanded=False):
                st.code(_warehouse_owner_inventory_sql(owner_query_days, company, environment), language="sql")
            return
        if owner_inventory.empty:
            st.info("No warehouse usage rows found for the selected company/environment scope.")
            return

        blocked = owner_inventory[owner_inventory["GOVERNANCE_READINESS"] == "Owner Route Blocked"]
        directory_only = owner_inventory[owner_inventory["GOVERNANCE_READINESS"] == "Directory Route Only"]
        fully_tagged = owner_inventory[owner_inventory["GOVERNANCE_READINESS"] == "Tagged Owner Ready"]
        o1, o2, o3, o4 = st.columns(4)
        o1.metric("Warehouses Reviewed", f"{len(owner_inventory):,}")
        o2.metric("Tagged Owner Ready", f"{len(fully_tagged):,}")
        o3.metric("Directory Only", f"{len(directory_only):,}", delta_color="inverse")
        o4.metric("Owner Blocked", f"{len(blocked):,}", delta_color="inverse")

        render_priority_dataframe(
            owner_inventory,
            title="Warehouse owner, tag, and route readiness",
            priority_columns=[
                "WAREHOUSE_NAME", "GOVERNANCE_READINESS", "OWNER", "OWNER_ROUTE_READY",
                "OWNER_TAG_STATE", "COST_CENTER_TAG_STATE", "ENVIRONMENT_TAG_STATE",
                "QUERY_COUNT", "DATABASE_COUNT", "WAREHOUSE_SIZE", "OWNER_EMAIL",
                "ONCALL_PRIMARY", "APPROVAL_GROUP", "OWNER_SOURCE", "NEXT_OWNER_ACTION",
            ],
            sort_by=["GOVERNANCE_RANK", "QUERY_COUNT", "WAREHOUSE_NAME"],
            ascending=[False, False, True],
            raw_label="All warehouse ownership readiness rows",
            height=300,
        )
        download_csv(owner_inventory, "warehouse_ownership_readiness.csv")
        with st.expander("Ownership readiness query", expanded=False):
            st.code(st.session_state.get("wh_owner_inventory_sql", ""), language="sql")


def _render_warehouse_source_health(company: str, environment: str) -> None:
    source_health = _warehouse_source_health_rows(st.session_state, company, environment)
    if source_health.empty:
        return
    with st.expander("Warehouse Source Health", expanded=False):
        loaded = int(source_health["STATE"].isin(["Loaded", "No Rows"]).sum())
        stale = int(source_health["STATE"].eq("Stale").sum())
        unavailable = int(source_health["STATE"].eq("Unavailable").sum())
        mart_backed = int(
            source_health[
                source_health["STATE"].isin(["Loaded", "No Rows"])
                & source_health["SOURCE"].astype(str).str.contains("mart|FACT_", case=False, regex=True)
            ].shape[0]
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Current Surfaces", f"{loaded}/{len(source_health)}")
        c2.metric("Mart-Backed", f"{mart_backed:,}")
        c3.metric("Stale", f"{stale:,}", delta_color="inverse")
        c4.metric("Unavailable", f"{unavailable:,}", delta_color="inverse")
        st.caption(
            "Use this before acting on warehouse findings. Stale rows mean the data was loaded under a different "
            "company, environment, lookback, or global filter."
        )
        render_priority_dataframe(
            source_health,
            title="Warehouse evidence source and freshness",
            priority_columns=[
                "SURFACE", "STATE", "SOURCE", "CONFIDENCE", "ROWS", "SCOPE", "NEXT_ACTION",
            ],
            sort_by=["STATE_RANK", "SURFACE"],
            ascending=[True, True],
            raw_label="All warehouse source-health rows",
            height=320,
        )


def _warehouse_support_panels_have_state() -> bool:
    return any(
        st.session_state.get(key) is not None
        for key in (
            "wh_capacity_summary",
            "wh_capacity_exceptions",
            "wh_operability_fact",
            "wh_owner_inventory",
            "wh_setting_review_snapshot",
            "wh_action_closure",
        )
    )


def render():
    credit_price = st.session_state.get("credit_price", 3.00)
    company = get_active_company()
    environment = get_active_environment()
    global_warehouse = str(st.session_state.get("global_warehouse", "") or "").strip()
    global_user = str(st.session_state.get("global_user", "") or "").strip()
    global_role = str(st.session_state.get("global_role", "") or "").strip()
    global_database = str(st.session_state.get("global_database", "") or "").strip()
    global_start_date = st.session_state.get("global_start_date")
    global_end_date = st.session_state.get("global_end_date")
    wh_query_filters = get_global_filter_clause(
        date_col="q.start_time",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
    )
    wh_plain_filters = get_global_filter_clause(
        date_col="start_time",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
    )

    render_operator_briefing(
        [
            ("First move", "Decide whether pressure is queue, spill, latency, or cost drift."),
            ("Evidence", "Use metering plus query history before changing size or clusters."),
            ("Control", "Tune routing, auto-suspend, QAS, size, or multi-cluster with proof."),
            ("Output", "Create a warehouse capacity brief for release or cost review."),
        ],
        columns=4,
    )
    warehouse_view = render_workflow_selector(
        "Warehouse Health workflow",
        "warehouse_health_view",
        WAREHOUSE_HEALTH_VIEWS,
        WAREHOUSE_HEALTH_DETAILS,
        columns=3,
    )
    show_support_panels = (
        bool(st.session_state.get("warehouse_health_support_panels_open"))
        or bool(st.session_state.get("exceptions_only_mode"))
        or _warehouse_support_panels_have_state()
    )
    if show_support_panels:
        _render_capacity_brief(company, environment)
        _render_warehouse_ownership_panel(company, environment)
        _render_warehouse_source_health(company, environment)
    elif st.button("Support Panels", key="warehouse_health_open_support_panels"):
        st.session_state["warehouse_health_support_panels_open"] = True
        st.rerun()
    if st.session_state.get("exceptions_only_mode"):
        st.stop()

    # â”€â”€ OVERVIEW â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if warehouse_view == "Overview & Scaling":
        st.header("Warehouse Health Overview")
        wh_days = st.slider("Lookback (days)", 1, 30, 7, key="wh_days")

        if st.button("Load Warehouse Data", key="wh_load"):
            try:
                mart_sql = build_mart_warehouse_overview_sql(
                    wh_days,
                    company=company,
                    warehouse_contains=global_warehouse,
                    user_contains=global_user,
                    role_contains=global_role,
                    database_contains=global_database,
                    start_date=global_start_date,
                    end_date=global_end_date,
                )
                df_w = run_query(
                    mart_sql,
                    ttl_key=f"wh_overview_mart_{company}_{wh_days}",
                    tier="historical",
                )
                source = (
                    "OVERWATCH mart: FACT_QUERY_HOURLY + FACT_WAREHOUSE_HOURLY "
                    "(cache and warehouse size require live ACCOUNT_USAGE)"
                )
                if df_w.empty:
                    session = _warehouse_action_session("load live warehouse overview fallback")
                    if session is None:
                        return
                    exprs = _warehouse_sql_exprs(session)
                    df_w = run_query(f"""
                        SELECT q.warehouse_name,
                               {exprs["wh_size_expr"]} AS warehouse_size,
                               COUNT(*)                            AS total_queries,
                               AVG(q.total_elapsed_time)/1000      AS avg_elapsed_sec,
                               PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY q.total_elapsed_time)/1000 AS p95_elapsed_sec,
                               {exprs["queue_avg_expr"]}           AS avg_queued_sec,
                               {exprs["remote_spill_sum_expr"]}/POWER(1024,3)  AS total_remote_spill_gb,
                               {exprs["cache_expr"]} AS avg_cache_pct,
                               SUM(CASE WHEN UPPER(q.execution_status)='FAILED_WITH_ERROR' THEN 1 ELSE 0 END) AS error_count,
                               {exprs["bytes_scanned_expr"]}/POWER(1024,3)  AS total_gb_scanned
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        WHERE q.start_time >= DATEADD('day', -{wh_days}, CURRENT_TIMESTAMP())
                          AND q.warehouse_name IS NOT NULL
                          {wh_query_filters}
                        GROUP BY q.warehouse_name
                        ORDER BY total_queries DESC
                    """, ttl_key=f"wh_overview_live_{company}_{wh_days}", tier="historical")
                    source = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"
                st.session_state["wh_df_wh"] = df_w
                st.session_state["wh_df_wh_source"] = source
                st.session_state["wh_df_wh_meta"] = _warehouse_scope_meta(company, environment, wh_days)
            except Exception as e:
                st.warning(f"Warehouse overview unavailable in this role/context: {format_snowflake_error(e)}")

        if (
            st.session_state.get("wh_df_wh") is not None
            and not _warehouse_meta_matches(
                st.session_state.get("wh_df_wh_meta"),
                _warehouse_scope_meta(company, environment, wh_days),
            )
        ):
            st.info("Loaded warehouse overview is stale for the active scope. Reload Warehouse Data before acting.")
        elif st.session_state.get("wh_df_wh") is not None and not st.session_state["wh_df_wh"].empty:
            df_w = st.session_state["wh_df_wh"]

            c1, c2, c3 = st.columns(3)
            c1.metric("Warehouses Active", len(df_w))
            c2.metric("Total Queries",     f"{int(df_w['TOTAL_QUERIES'].sum()):,}")
            c3.metric("Total Remote Spill", f"{df_w['TOTAL_REMOTE_SPILL_GB'].sum():.1f} GB")
            wh_source = st.session_state.get("wh_df_wh_source", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY")
            confidence = "estimated" if "mart:" in str(wh_source).lower() else "exact"
            st.caption(f"{metric_confidence_label(confidence)} | {wh_source}")

            # Flag warehouses needing attention
            for _, row in df_w.iterrows():
                issues = []
                if row.get("AVG_QUEUED_SEC", 0) > 2:
                    issues.append(f"Queue avg {row['AVG_QUEUED_SEC']:.1f}s - consider multi-cluster or upsize")
                if row.get("TOTAL_REMOTE_SPILL_GB", 0) > THRESHOLDS["spill_warning_gb"]:
                    issues.append(f"Remote spill {row['TOTAL_REMOTE_SPILL_GB']:.1f} GB - upsize")
                if issues:
                    st.warning(f"**{row['WAREHOUSE_NAME']}** ({row.get('WAREHOUSE_SIZE','')}): {' | '.join(issues)}")

            render_priority_dataframe(
                df_w,
                title="Warehouse overview ranked by pressure",
                priority_columns=[
                    "WAREHOUSE_NAME",
                    "WAREHOUSE_SIZE",
                    "TOTAL_QUERIES",
                    "AVG_QUEUED_SEC",
                    "TOTAL_REMOTE_SPILL_GB",
                    "AVG_ELAPSED_SEC",
                    "METERED_CREDITS",
                    "AVG_CACHE_PCT",
                ],
                sort_by=[
                    "AVG_QUEUED_SEC",
                    "TOTAL_REMOTE_SPILL_GB",
                    "AVG_ELAPSED_SEC",
                    "METERED_CREDITS",
                ],
                ascending=[False, False, False, False],
                raw_label="All warehouse overview rows",
            )

            # Cache efficiency chart
            cache_available = "AVG_CACHE_PCT" in df_w.columns and df_w["AVG_CACHE_PCT"].notna().any()
            if cache_available:
                st.subheader("Cache Hit % by Warehouse")
                render_drillable_bar_chart(
                    df_w,
                    dimension="WAREHOUSE_NAME",
                    measure="AVG_CACHE_PCT",
                    key="wh_cache_pct",
                    drilldown_column="warehouse_name",
                    lookback_hours=wh_days * 24,
                )
            else:
                st.info("Cache hit percentage is a live ACCOUNT_USAGE-only metric and is not stored in the hourly mart.")

            download_csv(df_w, "warehouse_health.csv")

            # Scaling events
            st.divider()
            st.subheader("Scaling Events (WAREHOUSE_METERING_HISTORY)")
            if st.button("Load Scaling Events", key="wh_scale_load"):
                try:
                    df_scale = run_query(
                        build_mart_warehouse_scaling_sql(
                            wh_days,
                            company=company,
                            warehouse_contains=global_warehouse,
                            start_date=global_start_date,
                            end_date=global_end_date,
                        ),
                        ttl_key=f"wh_scaling_mart_{company}_{wh_days}",
                        tier="historical",
                    )
                    scale_source = "OVERWATCH mart: FACT_WAREHOUSE_HOURLY"
                    if df_scale.empty:
                        session = _warehouse_action_session("load live warehouse scaling fallback")
                        if session is None:
                            return
                        exprs = _warehouse_sql_exprs(session)
                        df_scale = run_query(f"""
                            WITH latest_size AS (
                                SELECT warehouse_name, warehouse_size
                                FROM (
                                    SELECT q.warehouse_name, {exprs["latest_size_expr"]} AS warehouse_size,
                                           ROW_NUMBER() OVER (PARTITION BY q.warehouse_name ORDER BY q.start_time DESC) AS rn
                                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                                    WHERE q.start_time >= DATEADD('day', -{wh_days}, CURRENT_TIMESTAMP())
                                      AND q.warehouse_name IS NOT NULL
                                      {wh_query_filters}
                                )
                                WHERE rn = 1
                            )
                            SELECT m.warehouse_name, ls.warehouse_size, m.start_time, m.end_time,
                                   m.credits_used, {exprs["compute_meter_expr"]} AS credits_used_compute,
                                   {exprs["cloud_meter_expr"]} AS credits_used_cloud_services
                            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY m
                            LEFT JOIN latest_size ls ON m.warehouse_name = ls.warehouse_name
                            WHERE m.start_time >= DATEADD('day', -{wh_days}, CURRENT_TIMESTAMP())
                              {get_wh_filter_clause("m.warehouse_name")}
                            ORDER BY m.credits_used DESC LIMIT 200
                        """, ttl_key=f"wh_scaling_live_{company}_{wh_days}", tier="historical")
                        scale_source = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
                    st.session_state["wh_scaling"] = df_scale
                    st.session_state["wh_scaling_source"] = scale_source
                    st.session_state["wh_scaling_meta"] = _warehouse_scope_meta(company, environment, wh_days)
                except Exception as e:
                    st.warning(f"Scaling events unavailable in this role/context: {format_snowflake_error(e)}")
            df_scale = st.session_state.get("wh_scaling")
            if (
                df_scale is not None
                and not _warehouse_meta_matches(
                    st.session_state.get("wh_scaling_meta"),
                    _warehouse_scope_meta(company, environment, wh_days),
                )
            ):
                st.info("Loaded scaling events are stale for the active scope. Reload Scaling Events before acting.")
            elif df_scale is not None and not df_scale.empty:
                scale_source = st.session_state.get("wh_scaling_source", "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY")
                st.caption(f"{metric_confidence_label('exact')} | {scale_source}")
                render_priority_dataframe(
                    df_scale,
                    title="Largest scaling/metering events",
                    priority_columns=[
                        "WAREHOUSE_NAME",
                        "WAREHOUSE_SIZE",
                        "START_TIME",
                        "END_TIME",
                        "CREDITS_USED",
                        "CREDITS_USED_COMPUTE",
                        "CREDITS_USED_CLOUD_SERVICES",
                    ],
                    sort_by=["CREDITS_USED", "CREDITS_USED_COMPUTE"],
                    ascending=[False, False],
                    raw_label="All scaling events",
                )
                download_csv(df_scale, "scaling_events.csv")
            elif df_scale is not None:
                st.info("No scaling or metering events found for the selected warehouse scope.")

    elif warehouse_view == "Efficiency":
        st.header("Warehouse Efficiency Scorecard")
        eff_days = st.slider("Lookback (days)", 1, 30, 7, key="wh_eff_days")
        if st.button("Load Efficiency Metrics", key="wh_eff_load"):
            try:
                session = _warehouse_action_session("load warehouse efficiency metrics")
                if session is None:
                    return
                exprs = _warehouse_sql_exprs(session)
                df_eff = run_query(f"""
                    WITH {build_metered_credit_cte(days_back=eff_days, include_recent=True)}
                    SELECT q.warehouse_name,
                           {exprs["wh_size_expr"]} AS warehouse_size,
                           COUNT(*) AS query_count,
                           ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS metered_credits,
                           ROUND(SUM(COALESCE(pqc.metered_credits, 0)) / NULLIF(COUNT(*), 0), 6) AS credits_per_query,
                           ROUND({exprs["queue_sum_expr"]} / 1000 / NULLIF(SUM(COALESCE(pqc.metered_credits, 0)), 0), 2) AS queue_sec_per_credit,
                           ROUND({exprs["remote_spill_sum_expr"]} / POWER(1024,3) / NULLIF(SUM(COALESCE(pqc.metered_credits, 0)), 0), 2) AS remote_spill_gb_per_credit,
                           ROUND({exprs["cache_expr"]}, 2) AS avg_cache_pct,
                           ROUND(100
                                 - LEAST(COALESCE({exprs["queue_sum_expr"]} / 1000 / NULLIF(SUM(COALESCE(pqc.metered_credits, 0)), 0), 0), 25)
                                 - LEAST(COALESCE({exprs["remote_spill_sum_expr"]} / POWER(1024,3) / NULLIF(SUM(COALESCE(pqc.metered_credits, 0)), 0), 0), 25)
                                 - LEAST(COALESCE(SUM(COALESCE(pqc.metered_credits, 0)) / NULLIF(COUNT(*), 0), 0) * 10, 25),
                                 1) AS efficiency_score
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                    WHERE q.start_time >= DATEADD('day', -{eff_days}, CURRENT_TIMESTAMP())
                      AND q.warehouse_name IS NOT NULL
                      {wh_query_filters}
                    GROUP BY q.warehouse_name
                    ORDER BY efficiency_score ASC, metered_credits DESC
                    LIMIT 200
                """, ttl_key=f"wh_efficiency_{company}_{eff_days}", tier="historical")
                st.session_state["wh_efficiency"] = df_eff
                st.session_state["wh_efficiency_meta"] = _warehouse_scope_meta(company, environment, eff_days)
            except Exception as e:
                st.warning(f"Efficiency metrics unavailable in this role/context: {format_snowflake_error(e)}")

        df_eff = st.session_state.get("wh_efficiency")
        if (
            df_eff is not None
            and not _warehouse_meta_matches(
                st.session_state.get("wh_efficiency_meta"),
                _warehouse_scope_meta(company, environment, eff_days),
            )
        ):
            st.info("Loaded efficiency metrics are stale for the active scope. Reload Efficiency Metrics before acting.")
        elif df_eff is not None and not df_eff.empty:
            low = df_eff[df_eff["EFFICIENCY_SCORE"] < 70]
            c1, c2, c3 = st.columns(3)
            c1.metric("Warehouses scored", len(df_eff))
            c2.metric("Under 70 score", len(low), delta_color="inverse")
            c3.metric("Total metered credits", format_credits(float(df_eff["METERED_CREDITS"].sum())))
            st.caption(f"{metric_confidence_label('allocated')} | {freshness_note('ACCOUNT_USAGE')}")
            render_priority_dataframe(
                df_eff,
                title="Warehouse efficiency risks",
                priority_columns=[
                    "WAREHOUSE_NAME",
                    "WAREHOUSE_SIZE",
                    "EFFICIENCY_SCORE",
                    "METERED_CREDITS",
                    "CREDITS_PER_QUERY",
                    "QUEUE_SEC_PER_CREDIT",
                    "REMOTE_SPILL_GB_PER_CREDIT",
                    "AVG_CACHE_PCT",
                ],
                sort_by=["EFFICIENCY_SCORE", "METERED_CREDITS"],
                ascending=[True, False],
                raw_label="All warehouse efficiency rows",
            )
            render_drillable_bar_chart(
                df_eff,
                dimension="WAREHOUSE_NAME",
                measure="EFFICIENCY_SCORE",
                key="wh_efficiency_score",
                drilldown_column="warehouse_name",
                lookback_hours=eff_days * 24,
            )
            download_csv(df_eff, "warehouse_efficiency.csv")
            if st.button("Save low-efficiency warehouses to Action Queue", key="wh_eff_queue"):
                session = _warehouse_action_session("save warehouse efficiency findings to the action queue")
                if session is not None:
                    _queue_efficiency_findings(session, df_eff)

    # â”€â”€ SPILL â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    elif warehouse_view == "Spill & Memory":
        st.header("Spill & Memory Pressure")
        sp_days = st.slider("Lookback (days)", 1, 30, 7, key="sp_days")

        if st.button("Load Spill Data", key="sp_load"):
            try:
                session = _warehouse_action_session("load warehouse spill data")
                if session is None:
                    return
                exprs = _warehouse_sql_exprs(session)
                df_sp = run_query(f"""
                    SELECT warehouse_name, {exprs["plain_wh_size_expr"]} AS warehouse_size,
                           COUNT(*) AS spill_query_count,
                           ROUND({exprs["local_spill_expr"]}/POWER(1024,3),2)  AS local_spill_gb,
                           ROUND({exprs["remote_spill_expr"]}/POWER(1024,3),2) AS remote_spill_gb,
                           ROUND(AVG(total_elapsed_time)/1000,2)                       AS avg_elapsed_sec
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day', -{sp_days}, CURRENT_TIMESTAMP())
                      AND ({exprs["local_spill_row_expr"]} > 0 OR {exprs["remote_spill_row_expr"]} > 0)
                      AND warehouse_name IS NOT NULL
                      {wh_plain_filters}
                    GROUP BY warehouse_name
                    ORDER BY local_spill_gb + remote_spill_gb DESC
                """, ttl_key=f"wh_spill_{company}_{sp_days}", tier="historical")
                st.session_state["wh_df_sp"] = df_sp
                st.session_state["wh_df_sp_meta"] = _warehouse_scope_meta(company, environment, sp_days)
            except Exception as e:
                st.warning(f"Spill data unavailable in this role/context: {format_snowflake_error(e)}")

        if (
            st.session_state.get("wh_df_sp") is not None
            and not _warehouse_meta_matches(
                st.session_state.get("wh_df_sp_meta"),
                _warehouse_scope_meta(company, environment, sp_days),
            )
        ):
            st.info("Loaded spill data is stale for the active scope. Reload Spill Data before acting.")
        elif st.session_state.get("wh_df_sp") is not None and not st.session_state["wh_df_sp"].empty:
            df_sp = st.session_state["wh_df_sp"]
            c1, c2, c3 = st.columns(3)
            c1.metric("Spilling Warehouses", len(df_sp))
            c2.metric("Total Local Spill",  f"{df_sp['LOCAL_SPILL_GB'].sum():.1f} GB")
            c3.metric("Total Remote Spill", f"{df_sp['REMOTE_SPILL_GB'].sum():.1f} GB")
            render_priority_dataframe(
                df_sp,
                title="Spill and memory pressure",
                priority_columns=[
                    "WAREHOUSE_NAME",
                    "WAREHOUSE_SIZE",
                    "SPILL_QUERY_COUNT",
                    "LOCAL_SPILL_GB",
                    "REMOTE_SPILL_GB",
                    "AVG_ELAPSED_SEC",
                ],
                sort_by=["REMOTE_SPILL_GB", "LOCAL_SPILL_GB", "AVG_ELAPSED_SEC"],
                ascending=[False, False, False],
                raw_label="All spill rows",
            )
            df_sp["TOTAL_SPILL_GB"] = df_sp["LOCAL_SPILL_GB"] + df_sp["REMOTE_SPILL_GB"]
            render_drillable_bar_chart(
                df_sp,
                dimension="WAREHOUSE_NAME",
                measure="TOTAL_SPILL_GB",
                key="wh_spill_total",
                drilldown_column="warehouse_name",
                lookback_hours=sp_days * 24,
            )
            for _, row in df_sp.iterrows():
                if row["REMOTE_SPILL_GB"] > 10:
                    st.error(f"**{row['WAREHOUSE_NAME']}**: {row['REMOTE_SPILL_GB']:.1f} GB remote spill - upsize immediately")
            download_csv(df_sp, "spill_report.csv")

    # â”€â”€ HEATMAP â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    elif warehouse_view == "Workload Heatmap":
        st.header("Workload Concurrency Heatmap")
        hm_days = st.slider("Lookback (days)", 7, 90, 30, key="hm_days")

        if st.button("Build Heatmap", key="hm_build"):
            try:
                mart_sql = build_mart_warehouse_heatmap_sql(
                    hm_days,
                    company=company,
                    warehouse_contains=global_warehouse,
                    user_contains=global_user,
                    role_contains=global_role,
                    database_contains=global_database,
                    start_date=global_start_date,
                    end_date=global_end_date,
                )
                df_hm = run_query(
                    mart_sql,
                    ttl_key=f"wh_heatmap_mart_{company}_{hm_days}",
                    tier="historical",
                )
                source = "OVERWATCH mart: FACT_QUERY_HOURLY"
                if df_hm.empty:
                    live_days = min(int(hm_days), 30)
                    if live_days < int(hm_days):
                        st.warning("Workload heatmap live fallback is capped at 30 days to avoid broad query-history scans.")
                    df_hm = run_query(f"""
                        SELECT warehouse_name,
                               DAYOFWEEK(start_time) AS day_of_week,
                               HOUR(start_time)      AS hour_of_day,
                               COUNT(*)              AS query_count,
                               ROUND(AVG(total_elapsed_time)/1000,2) AS avg_elapsed_sec
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                        WHERE start_time >= DATEADD('day', -{live_days}, CURRENT_TIMESTAMP())
                          AND warehouse_name IS NOT NULL
                          {wh_plain_filters}
                        GROUP BY warehouse_name, day_of_week, hour_of_day
                        ORDER BY warehouse_name, day_of_week, hour_of_day
                    """, ttl_key=f"wh_heatmap_live_{company}_{live_days}", tier="historical")
                    source = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"
                st.session_state["wh_df_hm"] = df_hm
                st.session_state["wh_df_hm_meta"] = _warehouse_scope_meta(company, environment, hm_days)
                st.session_state["wh_df_hm_source"] = source
            except Exception as e:
                st.warning(f"Workload heatmap unavailable in this role/context: {format_snowflake_error(e)}")

        if (
            st.session_state.get("wh_df_hm") is not None
            and not _warehouse_meta_matches(
                st.session_state.get("wh_df_hm_meta"),
                _warehouse_scope_meta(company, environment, hm_days),
            )
        ):
            st.info("Loaded workload heatmap is stale for the active scope. Rebuild Heatmap before acting.")
        elif st.session_state.get("wh_df_hm") is not None and not st.session_state["wh_df_hm"].empty:
            df_hm = st.session_state["wh_df_hm"]
            whs = df_hm["WAREHOUSE_NAME"].unique()
            sel_wh = st.selectbox("Warehouse", whs, key="hm_wh_sel")

            if sel_wh:
                wh_data = df_hm[df_hm["WAREHOUSE_NAME"] == sel_wh]
                pivot = wh_data.pivot_table(
                    index="DAY_OF_WEEK", columns="HOUR_OF_DAY",
                    values="QUERY_COUNT", aggfunc="sum"
                ).fillna(0)
                day_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
                pivot.index = pivot.index.map(lambda x: day_names.get(int(x), str(x)))
                st.subheader(f"Query Volume Heatmap - {sel_wh}")
                st.dataframe(pivot.style.background_gradient(cmap="YlOrRd"), width="stretch")
                c1, c2, c3 = st.columns(3)
                c1.metric("Total Queries", f"{int(wh_data['QUERY_COUNT'].sum()):,}")
                c2.metric("Peak Hour",     f"{int(pivot.max().max()):,}")
                c3.metric("Avg Elapsed",   f"{wh_data['AVG_ELAPSED_SEC'].mean():.1f}s")

    elif warehouse_view == "Optimization Advisor":
        render_optimization_advisor()
