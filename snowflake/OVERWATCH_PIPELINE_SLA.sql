-- OVERWATCH_PIPELINE_SLA.sql
-- Metadata-driven pipeline SLA and freshness contract.

CREATE TABLE IF NOT EXISTS DBA_MAINT_DB.OVERWATCH.PIPELINE_SLA_CONFIG (
    CONFIG_ID STRING DEFAULT UUID_STRING(),
    DATABASE_NAME STRING NOT NULL,
    SCHEMA_NAME STRING NOT NULL,
    OBJECT_NAME STRING NOT NULL,
    OBJECT_TYPE STRING DEFAULT 'TABLE',
    SLA_MINUTES NUMBER DEFAULT 1440,
    OWNER STRING DEFAULT 'UNASSIGNED',
    SEVERITY STRING DEFAULT 'MEDIUM',
    ENABLED BOOLEAN DEFAULT TRUE,
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE VIEW DBA_MAINT_DB.OVERWATCH.PIPELINE_SLA_STATUS_V AS
WITH configured AS (
    SELECT *
    FROM DBA_MAINT_DB.OVERWATCH.PIPELINE_SLA_CONFIG
    WHERE ENABLED
),
tables_seen AS (
    SELECT
        table_catalog AS database_name,
        table_schema AS schema_name,
        table_name AS object_name,
        last_altered,
        row_count,
        bytes
    FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
    WHERE deleted IS NULL
)
SELECT
    c.config_id,
    c.database_name,
    c.schema_name,
    c.object_name,
    c.object_type,
    c.sla_minutes,
    c.owner,
    c.severity,
    t.last_altered AS last_seen_at,
    DATEDIFF('minute', t.last_altered, CURRENT_TIMESTAMP()) AS freshness_age_minutes,
    t.row_count,
    t.bytes,
    CASE
        WHEN t.object_name IS NULL THEN 'MISSING_OBJECT'
        WHEN DATEDIFF('minute', t.last_altered, CURRENT_TIMESTAMP()) > c.sla_minutes THEN 'SLA_MISSED'
        ELSE 'OK'
    END AS sla_state,
    'SNOWFLAKE.ACCOUNT_USAGE.TABLES has delayed telemetry; use task/event tables for near-real-time failure evidence.' AS freshness_note
FROM configured c
LEFT JOIN tables_seen t
  ON UPPER(c.database_name) = UPPER(t.database_name)
 AND UPPER(c.schema_name) = UPPER(t.schema_name)
 AND UPPER(c.object_name) = UPPER(t.object_name);

CREATE OR REPLACE VIEW DBA_MAINT_DB.OVERWATCH.PIPELINE_SLA_EXECUTIVE_V AS
SELECT
    COUNT(*) AS configured_objects,
    COUNT_IF(sla_state = 'OK') AS objects_on_time,
    COUNT_IF(sla_state <> 'OK') AS objects_at_risk,
    ROUND(COUNT_IF(sla_state = 'OK') / NULLIF(COUNT(*), 0) * 100, 2) AS sla_compliance_pct,
    MAX(freshness_age_minutes) AS worst_freshness_age_minutes
FROM DBA_MAINT_DB.OVERWATCH.PIPELINE_SLA_STATUS_V;

INSERT INTO DBA_MAINT_DB.OVERWATCH.PIPELINE_SLA_CONFIG
    (DATABASE_NAME, SCHEMA_NAME, OBJECT_NAME, OBJECT_TYPE, SLA_MINUTES, OWNER, SEVERITY)
SELECT 'ALFA_EDW_PROD', 'CORE', 'FACT_POLICY', 'TABLE', 1440, 'DBA / Data Engineering', 'HIGH'
WHERE NOT EXISTS (
    SELECT 1
    FROM DBA_MAINT_DB.OVERWATCH.PIPELINE_SLA_CONFIG
    WHERE DATABASE_NAME = 'ALFA_EDW_PROD'
      AND SCHEMA_NAME = 'CORE'
      AND OBJECT_NAME = 'FACT_POLICY'
);
