-- OVERWATCH_NATIVE_ALERT_TEMPLATES.sql
-- Optional Snowflake-native ALERT templates for the OVERWATCH command center.
--
-- Review before use:
--   1. Replace <OVERWATCH_WAREHOUSE> with the approved low-cost monitoring warehouse.
--   2. Replace <EMAIL_NOTIFICATION_INTEGRATION> and <ALERT_EMAIL> only after
--      Security/DBA approval for Snowflake notification integrations.
--   3. Keep actions notification-only until the matching Alert Center route,
--      acknowledgement, suppression, and remediation logs are deployed.
--   4. ACCOUNT_USAGE sources can lag. Use INFORMATION_SCHEMA/live workflows for
--      in-flight query cancellation or task recovery decisions.

USE DATABASE DBA_MAINT_DB;
USE SCHEMA OVERWATCH;

-- Freshness guard for the executive first-paint mart.
CREATE ALERT IF NOT EXISTS OVERWATCH_EXECUTIVE_MART_STALE_ALERT
  WAREHOUSE = <OVERWATCH_WAREHOUSE>
  SCHEDULE = '60 MINUTE'
  IF (EXISTS (
      SELECT 1
      FROM OVERWATCH_REFRESH_POLICY p
      LEFT JOIN (
          SELECT
              'Executive Landing' AS SURFACE,
              MAX(SNAPSHOT_TS) AS LATEST_REFRESH_TS
          FROM MART_EXECUTIVE_OBSERVABILITY
      ) f
        ON f.SURFACE = p.SURFACE
      WHERE p.POLICY_NAME = 'EXECUTIVE_OBSERVABILITY'
        AND p.RUN_IN_FIRST_PAINT
        AND (
             f.LATEST_REFRESH_TS IS NULL
          OR DATEDIFF('minute', f.LATEST_REFRESH_TS, CURRENT_TIMESTAMP()) > p.TARGET_FRESHNESS_MIN
        )
  ))
  THEN CALL SYSTEM$SEND_EMAIL(
      '<EMAIL_NOTIFICATION_INTEGRATION>',
      '<ALERT_EMAIL>',
      'OVERWATCH executive mart stale',
      'MART_EXECUTIVE_OBSERVABILITY missed its first-paint freshness target. Run snowflake/OVERWATCH_MART_VALIDATION.sql and refresh the mart before using executive numbers.'
  );

-- Critical/high alert backlog guard.
CREATE ALERT IF NOT EXISTS OVERWATCH_CRITICAL_ALERT_BACKLOG
  WAREHOUSE = <OVERWATCH_WAREHOUSE>
  SCHEDULE = '15 MINUTE'
  IF (EXISTS (
      SELECT 1
      FROM ALERT_EVENTS
      WHERE UPPER(COALESCE(STATUS, 'OPEN')) NOT IN ('RESOLVED', 'CLOSED', 'SUPPRESSED')
        AND UPPER(COALESCE(SEVERITY, 'LOW')) IN ('CRITICAL', 'HIGH')
        AND ALERT_TS >= DATEADD('DAY', -7, CURRENT_TIMESTAMP())
      HAVING COUNT(*) >= 1
  ))
  THEN CALL SYSTEM$SEND_EMAIL(
      '<EMAIL_NOTIFICATION_INTEGRATION>',
      '<ALERT_EMAIL>',
      'OVERWATCH critical/high alert backlog',
      'Open critical/high alert rows exist in ALERT_EVENTS. Open Alert Center, acknowledge or suppress duplicates, assign an owner, and preserve remediation proof.'
  );

-- Failed task graph guard using OVERWATCH facts. Prefer INFORMATION_SCHEMA for
-- in-flight incidents; this alert is for repeated or recently materialized risk.
CREATE ALERT IF NOT EXISTS OVERWATCH_TASK_FAILURE_ALERT
  WAREHOUSE = <OVERWATCH_WAREHOUSE>
  SCHEDULE = '30 MINUTE'
  IF (EXISTS (
      SELECT 1
      FROM FACT_TASK_RUN
      WHERE START_TIME >= DATEADD('HOUR', -4, CURRENT_TIMESTAMP())
        AND UPPER(COALESCE(STATE, '')) IN ('FAILED', 'CANCELLED', 'SKIPPED')
      HAVING COUNT(*) >= 1
  ))
  THEN CALL SYSTEM$SEND_EMAIL(
      '<EMAIL_NOTIFICATION_INTEGRATION>',
      '<ALERT_EMAIL>',
      'OVERWATCH task graph failure',
      'Recent task failures are materialized in FACT_TASK_RUN. Open Workload Operations or DBA Control Room and inspect root task, child task, error text, and retry policy.'
  );

-- Data quality configuration guard. This checks whether enabled metadata rules
-- are producing recent run proof; it does not scan business tables directly.
CREATE ALERT IF NOT EXISTS OVERWATCH_DATA_QUALITY_RUN_GAP
  WAREHOUSE = <OVERWATCH_WAREHOUSE>
  SCHEDULE = '60 MINUTE'
  IF (EXISTS (
      WITH latest_runs AS (
          SELECT
              CHECK_ID,
              MAX(RUN_TS) AS LATEST_RUN_TS
          FROM OVERWATCH_RECON_RUN
          GROUP BY CHECK_ID
      )
      SELECT 1
      FROM ALERT_DATA_QUALITY_CHECKS c
      LEFT JOIN latest_runs r
        ON r.CHECK_ID = c.CHECK_ID
      WHERE c.ENABLED
        AND (
             r.LATEST_RUN_TS IS NULL
          OR r.LATEST_RUN_TS < DATEADD('HOUR', -24, CURRENT_TIMESTAMP())
        )
  ))
  THEN CALL SYSTEM$SEND_EMAIL(
      '<EMAIL_NOTIFICATION_INTEGRATION>',
      '<ALERT_EMAIL>',
      'OVERWATCH data quality run gap',
      'At least one enabled data quality/reconciliation rule has no recent proof. Open Workload Operations and review ALERT_DATA_QUALITY_CHECKS plus OVERWATCH_RECON_RUN.'
  );

-- Optional Data Metric Function pattern.
-- If the account uses Snowflake Data Metric Functions, keep DMF schedules owned
-- by data owners and let OVERWATCH read the result/audit tables. Do not duplicate
-- expensive row-count/hash scans in Streamlit first paint.
--
-- Example deployment flow:
--   ALTER TABLE <db>.<schema>.<table>
--     ADD DATA METRIC FUNCTION <metric_name> ON (<column_or_expression>);
--   ALTER TABLE <db>.<schema>.<table>
--     SET DATA_METRIC_SCHEDULE = 'USING CRON 0 * * * * UTC';
--
-- Then materialize DMF results into ALERT_EVENTS or an OVERWATCH fact table and
-- route them through Alert Center acknowledgement, suppression, and owner logs.
