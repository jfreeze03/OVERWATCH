-- OVERWATCH_EXECUTIVE_DIGEST.sql
-- Board-ready daily digest payload generated inside Snowflake.

CREATE TABLE IF NOT EXISTS DBA_MAINT_DB.OVERWATCH.EXECUTIVE_DIGEST_HISTORY (
    DIGEST_ID STRING DEFAULT UUID_STRING(),
    DIGEST_DATE DATE DEFAULT CURRENT_DATE(),
    GENERATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    TOTAL_SPEND_USD NUMBER(18,2),
    DAILY_BURN_USD NUMBER(18,2),
    CRITICAL_HIGH_ALERTS NUMBER,
    PIPELINE_SLA_COMPLIANCE_PCT NUMBER(8,2),
    PLATFORM_HEALTH_SCORE NUMBER(5,2),
    ACTIVE_ISSUES NUMBER,
    DIGEST_TEXT STRING,
    SOURCE_FRESHNESS STRING
);

CREATE OR REPLACE PROCEDURE DBA_MAINT_DB.OVERWATCH.SP_OVERWATCH_EXECUTIVE_DIGEST()
RETURNS STRING
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
    digest_text STRING;
BEGIN
    INSERT INTO DBA_MAINT_DB.OVERWATCH.EXECUTIVE_DIGEST_HISTORY (
        TOTAL_SPEND_USD,
        DAILY_BURN_USD,
        CRITICAL_HIGH_ALERTS,
        PIPELINE_SLA_COMPLIANCE_PCT,
        PLATFORM_HEALTH_SCORE,
        ACTIVE_ISSUES,
        DIGEST_TEXT,
        SOURCE_FRESHNESS
    )
    WITH executive AS (
        SELECT *
        FROM DBA_MAINT_DB.OVERWATCH.MART_EXECUTIVE_OBSERVABILITY
        QUALIFY ROW_NUMBER() OVER (ORDER BY refreshed_at DESC NULLS LAST) = 1
    ),
    sla AS (
        SELECT *
        FROM DBA_MAINT_DB.OVERWATCH.PIPELINE_SLA_EXECUTIVE_V
    ),
    alerts AS (
        SELECT COUNT_IF(severity IN ('CRITICAL', 'HIGH') AND status IN ('OPEN', 'ACKNOWLEDGED')) AS critical_high_alerts
        FROM DBA_MAINT_DB.OVERWATCH.ALERT_EVENTS
    )
    SELECT
        COALESCE(e.total_spend_usd, 0),
        COALESCE(e.daily_burn_usd, 0),
        COALESCE(a.critical_high_alerts, 0),
        COALESCE(s.sla_compliance_pct, 0),
        COALESCE(e.platform_health_score, 0),
        COALESCE(e.active_issues, 0),
        'Spend $' || COALESCE(e.total_spend_usd, 0)::STRING
            || '; burn $' || COALESCE(e.daily_burn_usd, 0)::STRING
            || '; critical/high alerts ' || COALESCE(a.critical_high_alerts, 0)::STRING
            || '; pipeline SLA ' || COALESCE(s.sla_compliance_pct, 0)::STRING || '%'
            || '; health score ' || COALESCE(e.platform_health_score, 0)::STRING
            || '; active issues ' || COALESCE(e.active_issues, 0)::STRING,
        COALESCE(e.source_freshness, 'Unknown')
    FROM executive e
    CROSS JOIN sla s
    CROSS JOIN alerts a;

    SELECT DIGEST_TEXT
      INTO :digest_text
    FROM DBA_MAINT_DB.OVERWATCH.EXECUTIVE_DIGEST_HISTORY
    QUALIFY ROW_NUMBER() OVER (ORDER BY GENERATED_AT DESC) = 1;

    RETURN digest_text;
END;
$$;

CREATE TASK IF NOT EXISTS DBA_MAINT_DB.OVERWATCH.TASK_OVERWATCH_EXECUTIVE_DIGEST
    WAREHOUSE = OVERWATCH_WH
    SCHEDULE = 'USING CRON 30 12 * * * UTC'
AS
    CALL DBA_MAINT_DB.OVERWATCH.SP_OVERWATCH_EXECUTIVE_DIGEST();

-- Keep TASK_OVERWATCH_EXECUTIVE_DIGEST suspended until MART_EXECUTIVE_OBSERVABILITY,
-- PIPELINE_SLA_EXECUTIVE_V, and ALERT_EVENTS are deployed in the target account.
