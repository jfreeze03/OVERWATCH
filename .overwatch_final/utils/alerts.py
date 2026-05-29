# utils/alerts.py — Teams webhook + Snowflake Task DDL + Annotation DDL
# NEW: build_annotation_ddl() generates the OVERWATCH_ANNOTATIONS table + helpers
import json
import urllib.request
import streamlit as st
from config import ALERT_DB, ALERT_SCHEMA, ALERT_TABLE, THRESHOLDS
from .query import format_snowflake_error, safe_identifier, safe_schedule, sql_literal


ANNOTATION_TABLE = "OVERWATCH_ANNOTATIONS"


def send_teams_alert(webhook_url: str, message: str, title: str = "OVERWATCH Alert") -> bool:
    """Send a Microsoft Teams message via incoming webhook."""
    if not webhook_url:
        return False
    payload = json.dumps({
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": title,
        "themeColor": "38BDF8",
        "title": title,
        "text": message,
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        st.warning(f"Teams alert failed: {format_snowflake_error(e)}")
        return False


def build_annotation_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    """Generate DDL for the OVERWATCH_ANNOTATIONS table.

    Annotations let DBAs mark known events (load tests, deployments,
    planned downtime) so the anomaly log and alert task can suppress
    re-alerting during those windows.

    Usage in anomaly queries:
        LEFT JOIN {db}.{schema}.OVERWATCH_ANNOTATIONS ann
          ON entity = ann.entity
         AND :check_time BETWEEN ann.window_start AND ann.window_end
        WHERE ann.annotation_id IS NULL   -- exclude annotated windows
    """
    return f"""-- ─────────────────────────────────────────────────────────────────
-- OVERWATCH Annotation System
-- Prevents re-alerting on known events (load tests, deployments, etc.)
-- Run once as SYSADMIN or DBA role.
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS {safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(ANNOTATION_TABLE)} (
    ANNOTATION_ID   NUMBER AUTOINCREMENT PRIMARY KEY,
    CREATED_BY      VARCHAR(200),
    CREATED_AT      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    ENTITY          VARCHAR(500),        -- warehouse name, task name, user name, or '*' for global
    ENTITY_TYPE     VARCHAR(50),         -- WAREHOUSE | TASK | USER | GLOBAL
    WINDOW_START    TIMESTAMP_NTZ NOT NULL,
    WINDOW_END      TIMESTAMP_NTZ NOT NULL,
    ANNOTATION_TYPE VARCHAR(100),        -- DEPLOYMENT | LOAD_TEST | PLANNED_MAINTENANCE | OTHER
    DESCRIPTION     VARCHAR(2000),
    SUPPRESS_ALERTS BOOLEAN DEFAULT TRUE,
    ACTIVE          BOOLEAN DEFAULT TRUE
);

-- Example annotations for planned Snowflake load windows:
-- INSERT INTO {safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(ANNOTATION_TABLE)}
--     (ENTITY, ENTITY_TYPE, WINDOW_START, WINDOW_END, ANNOTATION_TYPE, DESCRIPTION)
-- VALUES
--     ('WH_ALFA_LOAD', 'WAREHOUSE',
--      '2025-06-01 00:00:00'::TIMESTAMP_NTZ,
--      '2025-06-03 23:59:59'::TIMESTAMP_NTZ,
--      'LOAD_TEST', 'Large Snowflake backfill on WH_ALFA_LOAD - expect elevated credit usage');

-- View active annotations:
-- SELECT * FROM {safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(ANNOTATION_TABLE)}
-- WHERE ACTIVE = TRUE AND WINDOW_END >= CURRENT_TIMESTAMP()
-- ORDER BY WINDOW_START;
"""


def build_alert_task_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = ALERT_TABLE,
    warehouse: str = "COMPUTE_WH",
    schedule: str = "USING CRON 0 7 * * * UTC",
) -> str:
    """Generate DDL + DML for the OVERWATCH anomaly alert Snowflake Task.
    Now annotation-aware: skips alerting on entities with an active annotation window.
    """
    db = safe_identifier(db)
    schema = safe_identifier(schema)
    table = safe_identifier(table)
    annotation_table = safe_identifier(ANNOTATION_TABLE)
    warehouse = safe_identifier(warehouse)
    schedule = safe_schedule(schedule)
    spike_pct = THRESHOLDS["credit_spike_pct"]
    return f"""-- ─────────────────────────────────────────────────────────────────
-- OVERWATCH Automated Alert Task (annotation-aware)
-- Target: {db}.{schema}.{table}
-- Schedule: {schedule}
-- Run as: ACCOUNTADMIN or role with EXECUTE TASK privilege
-- ─────────────────────────────────────────────────────────────────

-- 1. Create alert table (idempotent)
CREATE TABLE IF NOT EXISTS {db}.{schema}.{table} (
    ALERT_ID         NUMBER AUTOINCREMENT PRIMARY KEY,
    ALERT_DATE       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    ALERT_TYPE       VARCHAR(100),
    SEVERITY         VARCHAR(20),
    ENTITY           VARCHAR(500),
    DETAIL           VARCHAR(2000),
    SUGGESTED_ACTION VARCHAR(1000),
    OWNER            VARCHAR(200),
    STATUS           VARCHAR(30) DEFAULT 'NEW',
    TEAMS_TARGET     VARCHAR(500),
    EMAIL_TARGET     VARCHAR(500),
    RESOLVED         BOOLEAN DEFAULT FALSE
);

-- 2. Create monitoring task
CREATE OR REPLACE TASK {db}.{schema}.OVERWATCH_ANOMALY_CHECK
    WAREHOUSE = {warehouse}
    SCHEDULE  = {sql_literal(schedule)}
AS
INSERT INTO {db}.{schema}.{table}
    (ALERT_TYPE, SEVERITY, ENTITY, DETAIL, SUGGESTED_ACTION)

WITH daily_credits AS (
    SELECT warehouse_name,
           DATE_TRUNC('day', start_time) AS day,
           SUM(credits_used)             AS daily_credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
    WHERE start_time >= DATEADD('day', -15, CURRENT_TIMESTAMP())
    GROUP BY warehouse_name, day
),
stats AS (
    SELECT warehouse_name,
           AVG(daily_credits)    AS avg_credits,
           STDDEV(daily_credits) AS std_credits,
           MAX(day)              AS latest_day
    FROM daily_credits
    GROUP BY warehouse_name
),
spikes AS (
    SELECT d.warehouse_name, d.daily_credits, s.avg_credits,
           ROUND(d.daily_credits / NULLIF(s.avg_credits, 0), 2) AS spike_ratio
    FROM daily_credits d
    JOIN stats s ON d.warehouse_name = s.warehouse_name
    WHERE d.day = s.latest_day
      AND d.daily_credits > s.avg_credits * (1 + {spike_pct}/100.0)
      AND s.avg_credits > 0.1
      -- Skip annotated windows (load tests, deployments, planned maintenance)
      AND NOT EXISTS (
          SELECT 1 FROM {db}.{schema}.{annotation_table} ann
          WHERE ann.active = TRUE
            AND ann.suppress_alerts = TRUE
            AND (ann.entity = d.warehouse_name OR ann.entity_type = 'GLOBAL')
            AND CURRENT_TIMESTAMP() BETWEEN ann.window_start AND ann.window_end
      )
)
SELECT
    'Credit Spike'                                                   AS ALERT_TYPE,
    CASE WHEN spike_ratio > 3 THEN 'HIGH' ELSE 'MEDIUM' END         AS SEVERITY,
    warehouse_name                                                    AS ENTITY,
    'Credits: ' || ROUND(daily_credits,2) || ' (' || spike_ratio
        || 'x rolling avg of ' || ROUND(avg_credits,2) || ')'       AS DETAIL,
    'Review warehouse activity in OVERWATCH Cost & Contract → Explain bill / attribution / contract → Burn Rate' AS SUGGESTED_ACTION
FROM spikes

UNION ALL

SELECT
    'High Error Rate'                              AS ALERT_TYPE,
    'HIGH'                                         AS SEVERITY,
    warehouse_name                                 AS ENTITY,
    'Failed queries in last 24h: ' || failures     AS DETAIL,
    'Investigate error codes in Query Analysis'    AS SUGGESTED_ACTION
FROM (
    SELECT warehouse_name, COUNT(*) AS failures
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE start_time >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
      AND UPPER(execution_status) = 'FAILED_WITH_ERROR'
      AND warehouse_name IS NOT NULL
    GROUP BY warehouse_name
    HAVING COUNT(*) > {THRESHOLDS['error_rate_high']}
)
WHERE NOT EXISTS (
    SELECT 1 FROM {db}.{schema}.{annotation_table} ann
    WHERE ann.active = TRUE AND ann.suppress_alerts = TRUE
      AND (ann.entity = warehouse_name OR ann.entity_type = 'GLOBAL')
      AND CURRENT_TIMESTAMP() BETWEEN ann.window_start AND ann.window_end
);

-- 3. Resume the task
ALTER TASK {db}.{schema}.OVERWATCH_ANOMALY_CHECK RESUME;

-- 4. Verify
SHOW TASKS LIKE 'OVERWATCH_ANOMALY_CHECK' IN SCHEMA {db}.{schema};
"""
