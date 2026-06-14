-- OVERWATCH_FRESHNESS_ALERT.sql
-- Optional native Snowflake alert for configured pipeline SLA misses.
-- Replace OVERWATCH_WH and notification action after account approval.

CREATE ALERT IF NOT EXISTS DBA_MAINT_DB.OVERWATCH.ALERT_PIPELINE_SLA_MISS
    WAREHOUSE = OVERWATCH_WH
    SCHEDULE = 'USING CRON 0 * * * * UTC'
IF (
    EXISTS (
        SELECT 1
        FROM DBA_MAINT_DB.OVERWATCH.PIPELINE_SLA_STATUS_V
        WHERE sla_state <> 'OK'
          AND severity IN ('CRITICAL', 'HIGH')
    )
)
THEN
    INSERT INTO DBA_MAINT_DB.OVERWATCH.ALERT_EVENTS (
        ALERT_ID,
        CATEGORY,
        SEVERITY,
        STATUS,
        TITLE,
        DESCRIPTION,
        OWNER,
        SOURCE_VIEW,
        FIRST_SEEN_AT,
        LAST_SEEN_AT,
        RECOMMENDED_ACTION
    )
    SELECT
        'PIPELINE_SLA_' || config_id,
        'PIPELINE',
        severity,
        'OPEN',
        'Pipeline SLA missed: ' || database_name || '.' || schema_name || '.' || object_name,
        'Freshness age minutes=' || COALESCE(freshness_age_minutes::STRING, 'unknown')
            || '; SLA minutes=' || sla_minutes::STRING,
        owner,
        'PIPELINE_SLA_STATUS_V',
        CURRENT_TIMESTAMP(),
        CURRENT_TIMESTAMP(),
        'Open Workload Operations, check task graph status, failed COPY/load history, and downstream freshness risk.'
    FROM DBA_MAINT_DB.OVERWATCH.PIPELINE_SLA_STATUS_V
    WHERE sla_state <> 'OK'
      AND severity IN ('CRITICAL', 'HIGH');

-- For external notifications, add a separate approved notification integration
-- action after owner routing, quiet hours, and deduplication policy are approved.
