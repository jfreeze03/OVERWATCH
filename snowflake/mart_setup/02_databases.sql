-- OVERWATCH mart setup split: 02_databases.sql

-- Create runtime database, app warehouse, and resource monitor.

-- Source bundle: snowflake/OVERWATCH_MART_SETUP.sql



-- OVERWATCH Snowflake Mart Setup
-- Purpose:
--   Build the low-cost Snowflake architecture behind the OVERWATCH Streamlit app.
--   Streamlit should read these compact mart tables for history/cost/security
--   pages and reserve live INFORMATION_SCHEMA queries for true operations.
--
-- Run as a role that can:
--   - CREATE DATABASE / SCHEMA / WAREHOUSE / TASK / PROCEDURE
--   - SELECT from SNOWFLAKE.ACCOUNT_USAGE views
--   - MONITOR ACCOUNT for operational metadata
--
-- Cost posture:
--   - dedicated OVERWATCH app warehouse, XSMALL, 60-second auto-suspend
--   - dedicated app warehouse resource monitor with notify/suspend guardrails
--   - transient mart tables for rebuildable data
--   - permanent audit/action tables for telemetry and DBA-entered status
--   - hourly refresh, offset from the top of the hour for ACCOUNT_USAGE latency
--   - task/procedure-loaded tables instead of Dynamic Tables when a source path
--     can include secure views; Dynamic Tables cannot safely depend on secure
--     views in that Snowflake pattern.

-- -----------------------------------------------------------------------------
-- 1. Runtime objects
-- -----------------------------------------------------------------------------

CREATE DATABASE IF NOT EXISTS DBA_MAINT_DB;


CREATE WAREHOUSE IF NOT EXISTS OVERWATCH_WH
  WAREHOUSE_SIZE = XSMALL
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  STATEMENT_TIMEOUT_IN_SECONDS = 600
  COMMENT = 'Dedicated warehouse for OVERWATCH Streamlit app runtime and isolated cost attribution.';


CREATE RESOURCE MONITOR IF NOT EXISTS OVERWATCH_WH_RM
  WITH CREDIT_QUOTA = 50
       FREQUENCY = MONTHLY
       START_TIMESTAMP = IMMEDIATELY
       TRIGGERS ON 80 PERCENT DO NOTIFY
                ON 100 PERCENT DO SUSPEND;


ALTER WAREHOUSE IF EXISTS OVERWATCH_WH
  SET RESOURCE_MONITOR = OVERWATCH_WH_RM;


MERGE INTO ALERT_REMEDIATION_POLICY tgt
USING (
  SELECT * FROM VALUES
    ('POLICY_CORTEX_QUOTA_REVIEW', 'COST_CORTEX_SPEND_SPIKE', 'Cost', 'Cortex quota or access review', 'RECOMMEND', FALSE, 'DBA / AI cost route plus Security when grants change', 'SHOW PARAMETERS LIKE ''CORTEX%'' IN ACCOUNT;', '-- Review top FACT_CORTEX_DAILY users/sources and candidate quota setting; do not execute from Alert Center.', '-- No automatic Cortex access change. Use approved DBA workflow after review.', 'Restore prior Cortex parameter, role grant, or quota setting captured in before-state notes.', 'SELECT * FROM FACT_CORTEX_DAILY WHERE USAGE_DATE >= DATEADD(''day'', -7, CURRENT_DATE()) ORDER BY EST_COST_USD DESC LIMIT 100;'),
    ('POLICY_IDLE_WAREHOUSE_TIMEOUT_REVIEW', 'OPT_UNUSED_WAREHOUSE', 'Optimization', 'Warehouse auto-suspend timeout review', 'STATUS_REVIEW', FALSE, 'DBA / Cost owner', 'SHOW WAREHOUSES;', '-- Generate ALTER WAREHOUSE <name> SET AUTO_SUSPEND = <seconds> after route review.', 'ALTER WAREHOUSE IDENTIFIER(''<warehouse_name>'') SET AUTO_SUSPEND = <seconds>;', 'Reset AUTO_SUSPEND to the captured before-state value.', 'SHOW WAREHOUSES LIKE ''<warehouse_name>'';'),
    ('POLICY_WAREHOUSE_SPIKE_COST_REVIEW', 'COST_WAREHOUSE_CREDIT_SPIKE', 'Cost', 'Warehouse cost spike review', 'RECOMMEND', FALSE, 'DBA / Cost owner plus workload owner', 'SELECT * FROM FACT_WAREHOUSE_HOURLY WHERE WAREHOUSE_NAME = ''<warehouse_name>'' ORDER BY HOUR_START DESC LIMIT 168;', '-- Compare current/prior run-rate, top query hashes, warehouse settings, and company scope; no ALTER WAREHOUSE from Alert Center.', '-- No automatic warehouse change. Use guarded Admin workflow if a setting change is approved.', 'Restore prior warehouse settings only through guarded Admin review with before-state evidence.', 'SELECT * FROM FACT_WAREHOUSE_HOURLY WHERE WAREHOUSE_NAME = ''<warehouse_name>'' ORDER BY HOUR_START DESC LIMIT 168;'),
    ('POLICY_USER_QUERY_BEHAVIOR_REVIEW', 'BEHAVIOR_USER_QUERY_ANOMALY', 'Behavior', 'User/query behavior review', 'STATUS_REVIEW', FALSE, 'DBA / Workload reviewer', 'SELECT USER_NAME, ROLE_NAME, WAREHOUSE_NAME, QUERY_ID, EXECUTION_STATUS, TOTAL_ELAPSED_TIME, QUERY_TEXT FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE USER_NAME = ''<user_name>'' ORDER BY START_TIME DESC LIMIT 100;', '-- Compare repeated query hash, failures, role, warehouse, and recent coaching/change source before any control action.', '-- No automatic cancel, disable, revoke, or warehouse change from behavior alerts.', 'If a manual control was applied, restore access/settings only after verified query behavior and owner approval.', 'SELECT USER_NAME, ROLE_NAME, WAREHOUSE_NAME, COUNT(*) AS QUERY_COUNT FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE START_TIME >= DATEADD(''day'', -1, CURRENT_TIMESTAMP()) GROUP BY 1,2,3 ORDER BY QUERY_COUNT DESC;'),
    ('POLICY_TASK_RERUN_STATUS_REVIEW', 'PIPELINE_TASK_FAILURE', 'Task / Pipeline', 'Task rerun review', 'STATUS_REVIEW', FALSE, 'DBA / Pipeline Owner', 'SELECT * FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY()) ORDER BY SCHEDULED_TIME DESC LIMIT 100;', '-- Confirm root cause, dependency state, and downstream idempotency before EXECUTE TASK.', 'EXECUTE TASK IDENTIFIER(''<database.schema.task_name>'');', 'Record downstream cleanup plan or rerun blocker before manual execution.', 'SELECT * FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY()) ORDER BY SCHEDULED_TIME DESC LIMIT 100;'),
    ('POLICY_SECURITY_ACCESS_STATUS_REVIEW', 'SECURITY_PRIVILEGE_ESCALATION', 'Security', 'Access rollback review', 'STATUS_REVIEW', FALSE, 'Security Reviewer', 'SHOW GRANTS TO USER <user_name>;', '-- Compare grant, ticket, reviewer, and MFA posture before any revoke.', '-- Revoke SQL is intentionally not generated for AUTO mode.', 'Re-grant only after reviewer approval and ticket evidence.', 'SHOW GRANTS TO USER <user_name>;')
) src(POLICY_ID, ALERT_KEY, CATEGORY, ACTION_TYPE, REMEDIATION_MODE, AUTO_ELIGIBLE, REQUIRED_REVIEW, BEFORE_STATE_SQL, DRY_RUN_SQL, EXECUTION_SQL_TEMPLATE, ROLLBACK_GUIDANCE, VERIFICATION_SQL)
ON tgt.POLICY_ID = src.POLICY_ID
WHEN MATCHED THEN UPDATE SET
  ALERT_KEY = src.ALERT_KEY,
  CATEGORY = src.CATEGORY,
  ACTION_TYPE = src.ACTION_TYPE,
  REMEDIATION_MODE = src.REMEDIATION_MODE,
  AUTO_ELIGIBLE = src.AUTO_ELIGIBLE,
  REQUIRED_REVIEW = src.REQUIRED_REVIEW,
  BEFORE_STATE_SQL = src.BEFORE_STATE_SQL,
  DRY_RUN_SQL = src.DRY_RUN_SQL,
  EXECUTION_SQL_TEMPLATE = src.EXECUTION_SQL_TEMPLATE,
  ROLLBACK_GUIDANCE = src.ROLLBACK_GUIDANCE,
  VERIFICATION_SQL = src.VERIFICATION_SQL,
  UPDATED_AT = CURRENT_TIMESTAMP(),
  UPDATED_BY = CURRENT_USER()
WHEN NOT MATCHED THEN INSERT
  (POLICY_ID, ALERT_KEY, CATEGORY, ACTION_TYPE, REMEDIATION_MODE, AUTO_ELIGIBLE, REQUIRED_REVIEW, BEFORE_STATE_SQL, DRY_RUN_SQL, EXECUTION_SQL_TEMPLATE, ROLLBACK_GUIDANCE, VERIFICATION_SQL)
VALUES
  (src.POLICY_ID, src.ALERT_KEY, src.CATEGORY, src.ACTION_TYPE, src.REMEDIATION_MODE, src.AUTO_ELIGIBLE, src.REQUIRED_REVIEW, src.BEFORE_STATE_SQL, src.DRY_RUN_SQL, src.EXECUTION_SQL_TEMPLATE, src.ROLLBACK_GUIDANCE, src.VERIFICATION_SQL);


CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_COST_MONITORING()
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
DECLARE
  alert_email VARCHAR DEFAULT NULL;
BEGIN
  SELECT MAX(NULLIF(SETTING_VALUE, ''))
    INTO :alert_email
  FROM OVERWATCH_SETTINGS
  WHERE SETTING_NAME = 'DEFAULT_ALERT_EMAIL';

  DELETE FROM FACT_COST_MONITORING_SIGNAL
  WHERE SNAPSHOT_TS >= DATEADD('DAY', -2, CURRENT_TIMESTAMP());

  DELETE FROM FACT_COST_INCIDENT_TIMELINE
  WHERE EVENT_TS >= DATEADD('DAY', -2, CURRENT_TIMESTAMP());

  INSERT INTO FACT_COST_MONITORING_SIGNAL (
    SNAPSHOT_TS, COMPANY, ENVIRONMENT, SIGNAL_TYPE, SEVERITY, ENTITY_TYPE, ENTITY_NAME,
    CONTROL_SURFACE, CONTROL_SCOPE, EVIDENCE, NEXT_ACTION, PROOF_QUERY, VALUE_AT_RISK_USD, SOURCE
  )
  WITH recent AS (
    SELECT COMPANY, WAREHOUSE_NAME, SUM(COALESCE(CREDITS_USED, 0)) AS CREDITS_7D
    FROM FACT_WAREHOUSE_HOURLY
    WHERE HOUR_START >= DATEADD('DAY', -7, DATE_TRUNC('DAY', CURRENT_TIMESTAMP()))
      AND HOUR_START < DATE_TRUNC('DAY', CURRENT_TIMESTAMP())
    GROUP BY COMPANY, WAREHOUSE_NAME
  ),
  baseline AS (
    SELECT COMPANY, WAREHOUSE_NAME, SUM(COALESCE(CREDITS_USED, 0)) AS BASELINE_CREDITS_7D
    FROM FACT_WAREHOUSE_HOURLY
    WHERE HOUR_START >= DATEADD('DAY', -14, DATE_TRUNC('DAY', CURRENT_TIMESTAMP()))
      AND HOUR_START < DATEADD('DAY', -7, DATE_TRUNC('DAY', CURRENT_TIMESTAMP()))
    GROUP BY COMPANY, WAREHOUSE_NAME
  ),
  priced AS (
    SELECT
      r.COMPANY,
      r.WAREHOUSE_NAME,
      r.CREDITS_7D,
      COALESCE(b.BASELINE_CREDITS_7D, 0) AS BASELINE_CREDITS_7D,
      r.CREDITS_7D - COALESCE(b.BASELINE_CREDITS_7D, 0) AS CREDIT_DELTA,
      COALESCE((SELECT MAX(TRY_TO_DOUBLE(SETTING_VALUE)) FROM OVERWATCH_SETTINGS WHERE SETTING_NAME = 'CREDIT_PRICE_USD'), 3.68) AS CREDIT_PRICE_USD
    FROM recent r
    LEFT JOIN baseline b
      ON COALESCE(r.COMPANY, '') = COALESCE(b.COMPANY, '')
     AND r.WAREHOUSE_NAME = b.WAREHOUSE_NAME
    WHERE r.CREDITS_7D > GREATEST(COALESCE(b.BASELINE_CREDITS_7D, 0) * 1.25, COALESCE(b.BASELINE_CREDITS_7D, 0) + 10)
  )
  SELECT
    CURRENT_TIMESTAMP(),
    COMPANY,
    'No Database Context',
    'WAREHOUSE_COST_MOVEMENT',
    CASE WHEN CREDIT_DELTA >= 100 OR CREDITS_7D >= BASELINE_CREDITS_7D * 2 THEN 'High' ELSE 'Medium' END,
    'WAREHOUSE',
    WAREHOUSE_NAME,
    'OVERWATCH Cost Monitoring',
    'Exact warehouse metering',
    '7d complete-window credits ' || ROUND(CREDITS_7D, 2) || ' vs prior 7d ' || ROUND(BASELINE_CREDITS_7D, 2) || '; delta ' || ROUND(CREDIT_DELTA, 2) || ' credits.',
    'Open Cost & Contract root cause, assign owner, and route action after telemetry review.',
    'SELECT * FROM FACT_WAREHOUSE_HOURLY WHERE WAREHOUSE_NAME = ''' || WAREHOUSE_NAME || ''' ORDER BY HOUR_START DESC LIMIT 100;',
    ROUND(GREATEST(CREDIT_DELTA, 0) * CREDIT_PRICE_USD, 2),
    'FACT_WAREHOUSE_HOURLY'
  FROM priced;

  INSERT INTO FACT_COST_MONITORING_SIGNAL (
    SNAPSHOT_TS, COMPANY, ENVIRONMENT, SIGNAL_TYPE, SEVERITY, ENTITY_TYPE, ENTITY_NAME,
    CONTROL_SURFACE, CONTROL_SCOPE, EVIDENCE, NEXT_ACTION, PROOF_QUERY, VALUE_AT_RISK_USD, SOURCE
  )
  SELECT
    CURRENT_TIMESTAMP(),
    COMPANY,
    'No Database Context',
    'CORTEX_SPEND_AND_QUOTA',
    CASE WHEN SUM(COALESCE(EST_COST_USD, 0)) >= 500 THEN 'High' ELSE 'Medium' END,
    'USER_OR_AI_SERVICE',
    COALESCE(USER_ID, 'CORTEX'),
    'AI Spend Threshold + Per-User AI Quota',
    'AI and shared resource spend threshold',
    'Cortex 7d spend $' || ROUND(SUM(COALESCE(EST_COST_USD, 0)), 2) || ' across ' || SUM(COALESCE(REQUEST_COUNT, 0)) || ' request(s).',
    'Review shared AI spend threshold, per-user quota, and first/last usage before broadening access.',
    'SELECT * FROM FACT_CORTEX_DAILY WHERE USAGE_DATE >= DATEADD(''DAY'', -7, CURRENT_DATE()) ORDER BY EST_COST_USD DESC LIMIT 100;',
    ROUND(SUM(COALESCE(EST_COST_USD, 0)), 2),
    'FACT_CORTEX_DAILY'
  FROM FACT_CORTEX_DAILY
  WHERE USAGE_DATE >= DATEADD('DAY', -7, CURRENT_DATE())
  GROUP BY COMPANY, USER_ID
  HAVING SUM(COALESCE(EST_COST_USD, 0)) > 0;

  INSERT INTO FACT_COST_MONITORING_SIGNAL (
    SNAPSHOT_TS, COMPANY, ENVIRONMENT, SIGNAL_TYPE, SEVERITY, ENTITY_TYPE, ENTITY_NAME,
    CONTROL_SURFACE, CONTROL_SCOPE, EVIDENCE, NEXT_ACTION, PROOF_QUERY, VALUE_AT_RISK_USD, SOURCE
  )
  SELECT
    CURRENT_TIMESTAMP(),
    COMPANY,
    COALESCE(ENVIRONMENT, 'No Database Context'),
    'CHANGE_COST_CORRELATION',
    'High',
    'WAREHOUSE',
    COALESCE(REGEXP_SUBSTR(QUERY_TEXT, 'ALTER\\s+WAREHOUSE\\s+([^\\s;]+)', 1, 1, 'i', 1), 'WAREHOUSE_SETTING_CHANGE'),
    'Change + Cost Correlation',
    'Change telemetry',
    COUNT(*) || ' ALTER WAREHOUSE statement(s) in the last 48h by ' || COALESCE(MAX(USER_NAME), 'unknown user') || '.',
    'Compare the warehouse change query_id, actor, ticket, and rollback telemetry to cost movement before tuning.',
    'SELECT * FROM FACT_OBJECT_CHANGE WHERE QUERY_TEXT ILIKE ''ALTER WAREHOUSE %'' ORDER BY START_TIME DESC LIMIT 100;',
    0,
    'FACT_OBJECT_CHANGE'
  FROM FACT_OBJECT_CHANGE
  WHERE START_TIME >= DATEADD('HOUR', -48, CURRENT_TIMESTAMP())
    AND QUERY_TEXT ILIKE 'ALTER WAREHOUSE %'
  GROUP BY
    COMPANY,
    COALESCE(ENVIRONMENT, 'No Database Context'),
    COALESCE(REGEXP_SUBSTR(QUERY_TEXT, 'ALTER\\s+WAREHOUSE\\s+([^\\s;]+)', 1, 1, 'i', 1), 'WAREHOUSE_SETTING_CHANGE');

  INSERT INTO FACT_COST_INCIDENT_TIMELINE (
    INCIDENT_ID, EVENT_TS, EVENT_ORDER, COMPANY, ENVIRONMENT, ENTITY_NAME, EVENT_TYPE,
    SEVERITY, EVIDENCE, NEXT_ACTION, PROOF_QUERY, SOURCE
  )
  SELECT
    'COST-' || MD5(COALESCE(COMPANY, '') || '|' || COALESCE(ENTITY_NAME, '') || '|' || TO_VARCHAR(DATE_TRUNC('DAY', SNAPSHOT_TS))),
    SNAPSHOT_TS,
    CASE SIGNAL_TYPE
      WHEN 'WAREHOUSE_COST_MOVEMENT' THEN 1
      WHEN 'CHANGE_COST_CORRELATION' THEN 2
      WHEN 'CORTEX_SPEND_AND_QUOTA' THEN 3
      ELSE 4
    END,
    COMPANY,
    ENVIRONMENT,
    ENTITY_NAME,
    SIGNAL_TYPE,
    SEVERITY,
    EVIDENCE,
    NEXT_ACTION,
    PROOF_QUERY,
    SOURCE
  FROM FACT_COST_MONITORING_SIGNAL
  WHERE SNAPSHOT_TS >= DATEADD('DAY', -2, CURRENT_TIMESTAMP());

  INSERT INTO OVERWATCH_ALERTS (
    ALERT_TS, COMPANY, ENVIRONMENT, WAREHOUSE_NAME, CATEGORY, ALERT_TYPE, SEVERITY,
    ENTITY_NAME, ENTITY, MESSAGE, DETAIL, SUGGESTED_ACTION, PROOF_QUERY, OWNER,
    STATUS, DELIVERY_METHOD, DELIVERY_TARGET, EMAIL_TARGET, EMAIL_SUBJECT, EMAIL_BODY, DELIVERY_STATUS
  )
  SELECT
    SNAPSHOT_TS,
    COMPANY,
    ENVIRONMENT,
    IFF(ENTITY_TYPE = 'WAREHOUSE', ENTITY_NAME, NULL),
    'Cost Control',
    SIGNAL_TYPE,
    SEVERITY,
    ENTITY_NAME,
    ENTITY_NAME,
    EVIDENCE,
    EVIDENCE,
    NEXT_ACTION,
    PROOF_QUERY,
    'DBA / Cost owner',
    'New',
    'EMAIL',
    :alert_email,
    :alert_email,
    'OVERWATCH ' || SEVERITY || ': Cost Monitoring - ' || ENTITY_NAME,
    'Company: ' || COMPANY || CHAR(10)
      || 'Environment: ' || ENVIRONMENT || CHAR(10)
      || 'Signal: ' || SIGNAL_TYPE || CHAR(10)
      || 'Entity: ' || ENTITY_NAME || CHAR(10) || CHAR(10)
      || EVIDENCE || CHAR(10) || CHAR(10)
      || 'Next action: ' || NEXT_ACTION || CHAR(10) || CHAR(10)
      || 'Proof query: ' || PROOF_QUERY,
    IFF(:alert_email IS NULL, 'CONFIG_REQUIRED', 'EMAIL_READY')
  FROM FACT_COST_MONITORING_SIGNAL s
  WHERE SNAPSHOT_TS >= DATEADD('DAY', -2, CURRENT_TIMESTAMP())
    AND SEVERITY IN ('Critical', 'High')
    AND NOT EXISTS (
      SELECT 1
      FROM OVERWATCH_ALERTS existing
      WHERE existing.ALERT_TS >= DATEADD('HOUR', -24, CURRENT_TIMESTAMP())
        AND COALESCE(existing.ALERT_TYPE, '') = s.SIGNAL_TYPE
        AND COALESCE(existing.ENTITY_NAME, existing.ENTITY, '') = s.ENTITY_NAME
        AND UPPER(COALESCE(existing.STATUS, 'New')) NOT IN ('FIXED', 'IGNORED', 'RESOLVED')
    );

  RETURN 'OVERWATCH cost monitoring refresh complete';
END;
$$;


-- -----------------------------------------------------------------------------
-- 5. Alert framework
-- -----------------------------------------------------------------------------

CREATE OR REPLACE TASK OVERWATCH_ANOMALY_CHECK
  WAREHOUSE = OVERWATCH_WH
  SCHEDULE = 'USING CRON 5 * * * * America/Chicago'
AS
INSERT INTO OVERWATCH_ALERTS (
  ALERT_TS, COMPANY, ENVIRONMENT, DATABASE_NAME, SCHEMA_NAME, WAREHOUSE_NAME,
  CATEGORY, ALERT_TYPE, SEVERITY, ENTITY_NAME, ENTITY, MESSAGE, DETAIL,
  SUGGESTED_ACTION, PROOF_QUERY, OWNER, STATUS, DELIVERY_METHOD,
  DELIVERY_TARGET, EMAIL_TARGET, EMAIL_SUBJECT, EMAIL_BODY, DELIVERY_STATUS
)
WITH alert_config AS (
  SELECT MAX(NULLIF(SETTING_VALUE, '')) AS EMAIL_TARGET
  FROM OVERWATCH_SETTINGS
  WHERE SETTING_NAME = 'DEFAULT_ALERT_EMAIL'
),
credit_recent AS (
  SELECT COMPANY, WAREHOUSE_NAME, SUM(CREDITS_USED) AS CURRENT_CREDITS
  FROM FACT_WAREHOUSE_HOURLY
  WHERE HOUR_START >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
  GROUP BY COMPANY, WAREHOUSE_NAME
),
credit_baseline AS (
  SELECT COMPANY, WAREHOUSE_NAME, SUM(CREDITS_USED) / 7 AS AVG_DAILY_CREDITS
  FROM FACT_WAREHOUSE_HOURLY
  WHERE HOUR_START >= DATEADD('day', -8, CURRENT_TIMESTAMP())
    AND HOUR_START < DATEADD('day', -1, CURRENT_TIMESTAMP())
  GROUP BY COMPANY, WAREHOUSE_NAME
),
daily_spend_model AS (
  SELECT
    COMPANY,
    WAREHOUSE_NAME,
    TO_DATE(HOUR_START) AS SPEND_DAY,
    SUM(CREDITS_USED) AS DAILY_CREDITS
  FROM FACT_WAREHOUSE_HOURLY
  WHERE HOUR_START >= DATEADD('day', -45, CURRENT_TIMESTAMP())
    AND HOUR_START < DATE_TRUNC('day', CURRENT_TIMESTAMP())
    AND WAREHOUSE_NAME IS NOT NULL
  GROUP BY COMPANY, WAREHOUSE_NAME, TO_DATE(HOUR_START)
),
cost_anomaly_model AS (
  SELECT
    COMPANY,
    WAREHOUSE_NAME,
    SPEND_DAY,
    DAILY_CREDITS,
    AVG(DAILY_CREDITS) OVER (
      PARTITION BY COMPANY, WAREHOUSE_NAME
      ORDER BY SPEND_DAY
      ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING
    ) AS BASELINE_CREDITS,
    STDDEV(DAILY_CREDITS) OVER (
      PARTITION BY COMPANY, WAREHOUSE_NAME
      ORDER BY SPEND_DAY
      ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING
    ) AS SIGMA_CREDITS,
    COUNT(*) OVER (
      PARTITION BY COMPANY, WAREHOUSE_NAME
      ORDER BY SPEND_DAY
      ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING
    ) AS BASELINE_DAYS
  FROM daily_spend_model
),
predictive_cost_anomalies AS (
  SELECT
    COMPANY,
    WAREHOUSE_NAME,
    SPEND_DAY,
    DAILY_CREDITS,
    BASELINE_CREDITS,
    COALESCE(SIGMA_CREDITS, 0) AS SIGMA_CREDITS,
    DAILY_CREDITS * 30 AS PROJECTED_30D_CREDITS,
    IFF(BASELINE_CREDITS > 0, DAILY_CREDITS / NULLIF(BASELINE_CREDITS, 0), NULL) AS BURN_RATE_MULTIPLE
  FROM cost_anomaly_model
  WHERE SPEND_DAY = CURRENT_DATE() - 1
    AND BASELINE_DAYS >= 14
    AND BASELINE_CREDITS > 0.1
    AND (
      DAILY_CREDITS > BASELINE_CREDITS + 2.5 * COALESCE(SIGMA_CREDITS, 0)
      OR DAILY_CREDITS > BASELINE_CREDITS * 1.5
    )
),
query_failures AS (
  SELECT
    COMPANY, ENVIRONMENT, DATABASE_NAME, SCHEMA_NAME, WAREHOUSE_NAME,
    COUNT(*) AS FAILURES,
    MAX(LEFT(ERROR_MESSAGE, 500)) AS SAMPLE_ERROR
  FROM FACT_QUERY_DETAIL_RECENT
  WHERE START_TIME >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
    AND (ERROR_CODE IS NOT NULL OR UPPER(EXECUTION_STATUS) = 'FAILED_WITH_ERROR')
  GROUP BY COMPANY, ENVIRONMENT, DATABASE_NAME, SCHEMA_NAME, WAREHOUSE_NAME
  HAVING COUNT(*) >= 10
),
warehouse_pressure AS (
  SELECT
    COMPANY, ENVIRONMENT, DATABASE_NAME, WAREHOUSE_NAME,
    SUM(QUERY_COUNT) AS QUERY_COUNT,
    SUM(TOTAL_QUEUED_MS) AS TOTAL_QUEUED_MS,
    MAX(P95_EXECUTION_MS) AS P95_EXECUTION_MS
  FROM FACT_QUERY_HOURLY
  WHERE HOUR_START >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
    AND WAREHOUSE_NAME IS NOT NULL
  GROUP BY COMPANY, ENVIRONMENT, DATABASE_NAME, WAREHOUSE_NAME
  HAVING SUM(TOTAL_QUEUED_MS) >= 60000 OR MAX(P95_EXECUTION_MS) >= 120000
),
task_failures AS (
  SELECT
    COMPANY, ENVIRONMENT, DATABASE_NAME, SCHEMA_NAME, WAREHOUSE_NAME, TASK_NAME,
    COUNT(*) AS FAILURES,
    MAX(LEFT(ERROR_MESSAGE, 500)) AS SAMPLE_ERROR
  FROM FACT_TASK_RUN
  WHERE SCHEDULED_TIME >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
    AND UPPER(STATE) = 'FAILED'
  GROUP BY COMPANY, ENVIRONMENT, DATABASE_NAME, SCHEMA_NAME, WAREHOUSE_NAME, TASK_NAME
),
proc_recent AS (
  SELECT
    COMPANY, ENVIRONMENT, DATABASE_NAME, SCHEMA_NAME, PROCEDURE_NAME,
    COUNT(*) AS CALL_COUNT,
    SUM(CASE WHEN STATUS ILIKE '%FAIL%' OR ERROR_MESSAGE IS NOT NULL THEN 1 ELSE 0 END) AS FAILURES,
    AVG(TOTAL_DURATION_MS) AS AVG_DURATION_MS,
    MAX(LEFT(ERROR_MESSAGE, 500)) AS SAMPLE_ERROR
  FROM FACT_PROCEDURE_RUN
  WHERE START_TIME >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
  GROUP BY COMPANY, ENVIRONMENT, DATABASE_NAME, SCHEMA_NAME, PROCEDURE_NAME
),
proc_baseline AS (
  SELECT
    COMPANY, DATABASE_NAME, SCHEMA_NAME, PROCEDURE_NAME,
    AVG(TOTAL_DURATION_MS) AS BASELINE_DURATION_MS
  FROM FACT_PROCEDURE_RUN
  WHERE START_TIME >= DATEADD('day', -8, CURRENT_TIMESTAMP())
    AND START_TIME < DATEADD('hour', -24, CURRENT_TIMESTAMP())
  GROUP BY COMPANY, DATABASE_NAME, SCHEMA_NAME, PROCEDURE_NAME
),
procedure_risk AS (
  SELECT
    r.COMPANY, r.ENVIRONMENT, r.DATABASE_NAME, r.SCHEMA_NAME, r.PROCEDURE_NAME,
    r.CALL_COUNT, r.FAILURES, r.AVG_DURATION_MS, b.BASELINE_DURATION_MS, r.SAMPLE_ERROR
  FROM proc_recent r
  LEFT JOIN proc_baseline b
    ON COALESCE(r.COMPANY, '') = COALESCE(b.COMPANY, '')
   AND COALESCE(r.DATABASE_NAME, '') = COALESCE(b.DATABASE_NAME, '')
   AND COALESCE(r.SCHEMA_NAME, '') = COALESCE(b.SCHEMA_NAME, '')
   AND r.PROCEDURE_NAME = b.PROCEDURE_NAME
  WHERE r.FAILURES > 0
     OR (r.AVG_DURATION_MS >= 60000 AND b.BASELINE_DURATION_MS > 0 AND r.AVG_DURATION_MS > b.BASELINE_DURATION_MS * 1.5)
),
grant_changes AS (
  SELECT
    COMPANY, ENVIRONMENT, DATABASE_NAME, SCHEMA_NAME, USER_NAME, ROLE_NAME,
    COUNT(*) AS CHANGE_COUNT
  FROM FACT_OBJECT_CHANGE
  WHERE START_TIME >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
    AND (QUERY_TYPE ILIKE 'GRANT%' OR QUERY_TYPE ILIKE 'REVOKE%' OR QUERY_TEXT ILIKE 'GRANT %' OR QUERY_TEXT ILIKE 'REVOKE %')
  GROUP BY COMPANY, ENVIRONMENT, DATABASE_NAME, SCHEMA_NAME, USER_NAME, ROLE_NAME
),
warehouse_changes AS (
  SELECT
    COMPANY, USER_NAME, ROLE_NAME,
    COALESCE(REGEXP_SUBSTR(QUERY_TEXT, 'ALTER\\s+WAREHOUSE\\s+([^\\s;]+)', 1, 1, 'i', 1), 'WAREHOUSE') AS WAREHOUSE_NAME,
    COUNT(*) AS CHANGE_COUNT
  FROM FACT_OBJECT_CHANGE
  WHERE START_TIME >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
    AND QUERY_TEXT ILIKE 'ALTER WAREHOUSE %'
  GROUP BY COMPANY, USER_NAME, ROLE_NAME, WAREHOUSE_NAME
),
candidates AS (
  SELECT
    r.COMPANY,
    'No Database Context' AS ENVIRONMENT,
    NULL AS DATABASE_NAME,
    NULL AS SCHEMA_NAME,
    r.WAREHOUSE_NAME,
    'Cost Control' AS CATEGORY,
    'Credit Spike' AS ALERT_TYPE,
    CASE WHEN r.CURRENT_CREDITS / NULLIF(b.AVG_DAILY_CREDITS, 0) >= 3 THEN 'High' ELSE 'Medium' END AS SEVERITY,
    r.WAREHOUSE_NAME AS ENTITY_NAME,
    r.WAREHOUSE_NAME AS ENTITY,
    'Warehouse used ' || ROUND(r.CURRENT_CREDITS, 2) || ' credits in 24 hours vs ' || ROUND(b.AVG_DAILY_CREDITS, 2) || ' average daily credits.' AS MESSAGE,
    'Warehouse used ' || ROUND(r.CURRENT_CREDITS, 2) || ' credits in 24 hours vs ' || ROUND(b.AVG_DAILY_CREDITS, 2) || ' average daily credits.' AS DETAIL,
    'Open Cost & Contract, explain the bill movement, then route owner-backed cost-control actions.' AS SUGGESTED_ACTION,
    'SELECT * FROM FACT_WAREHOUSE_HOURLY WHERE WAREHOUSE_NAME = ''' || r.WAREHOUSE_NAME || ''' ORDER BY HOUR_START DESC LIMIT 100;' AS PROOF_QUERY,
    'DBA' AS OWNER
  FROM credit_recent r
  JOIN credit_baseline b ON r.COMPANY = b.COMPANY AND r.WAREHOUSE_NAME = b.WAREHOUSE_NAME
  WHERE b.AVG_DAILY_CREDITS > 0.1
    AND r.CURRENT_CREDITS > b.AVG_DAILY_CREDITS * 1.5

  UNION ALL

  SELECT
    COMPANY,
    'No Database Context' AS ENVIRONMENT,
    NULL AS DATABASE_NAME,
    NULL AS SCHEMA_NAME,
    WAREHOUSE_NAME,
    'Cost Forecast' AS CATEGORY,
    'Predictive Cost Anomaly' AS ALERT_TYPE,
    CASE WHEN BURN_RATE_MULTIPLE >= 2 OR DAILY_CREDITS > BASELINE_CREDITS + 3 * SIGMA_CREDITS THEN 'High' ELSE 'Medium' END AS SEVERITY,
    WAREHOUSE_NAME || ' predictive cost anomaly' AS ENTITY_NAME,
    WAREHOUSE_NAME AS ENTITY,
    'Warehouse ' || WAREHOUSE_NAME || ' used ' || ROUND(DAILY_CREDITS, 2)
      || ' credits yesterday vs 30-day baseline ' || ROUND(BASELINE_CREDITS, 2)
      || ' (sigma ' || ROUND(SIGMA_CREDITS, 2) || '). Projected 30-day burn '
      || ROUND(PROJECTED_30D_CREDITS, 2) || ' credits.' AS MESSAGE,
    'Predictive anomaly model uses the last complete day against a rolling 30-day baseline plus sigma. '
      || 'Burn-rate multiple: ' || ROUND(BURN_RATE_MULTIPLE, 2) || 'x.' AS DETAIL,
    'Open Cost & Contract, explain the top driver, validate demand, and route an Alert Center or action-queue item before contract pace overshoot.',
    'WITH daily AS (SELECT TO_DATE(HOUR_START) AS spend_day, SUM(CREDITS_USED) AS credits FROM FACT_WAREHOUSE_HOURLY WHERE WAREHOUSE_NAME = '''
      || WAREHOUSE_NAME || ''' GROUP BY TO_DATE(HOUR_START)) SELECT * FROM daily ORDER BY spend_day DESC LIMIT 45;',
    'DBA / Cost owner'
  FROM predictive_cost_anomalies

  UNION ALL

  SELECT
    COMPANY, ENVIRONMENT, DATABASE_NAME, SCHEMA_NAME, WAREHOUSE_NAME,
    'Reliability', 'High Query Error Rate', 'High',
    COALESCE(DATABASE_NAME || '.' || SCHEMA_NAME, WAREHOUSE_NAME),
    COALESCE(DATABASE_NAME || '.' || SCHEMA_NAME, WAREHOUSE_NAME),
    FAILURES || ' failed queries in the last 24 hours. Sample: ' || COALESCE(SAMPLE_ERROR, 'No sample error captured.'),
    FAILURES || ' failed queries in the last 24 hours. Sample: ' || COALESCE(SAMPLE_ERROR, 'No sample error captured.'),
    'Open Workload Operations, group by error code/query text, and assign the owning team.',
    'SELECT * FROM FACT_QUERY_DETAIL_RECENT WHERE START_TIME >= DATEADD(''hour'', -24, CURRENT_TIMESTAMP()) AND WAREHOUSE_NAME = ''' || WAREHOUSE_NAME || ''' ORDER BY START_TIME DESC LIMIT 100;',
    'DBA'
  FROM query_failures

  UNION ALL

  SELECT
    COMPANY, ENVIRONMENT, DATABASE_NAME, NULL, WAREHOUSE_NAME,
    'Capacity', 'Warehouse Pressure',
    CASE WHEN TOTAL_QUEUED_MS >= 300000 OR P95_EXECUTION_MS >= 300000 THEN 'High' ELSE 'Medium' END,
    WAREHOUSE_NAME,
    WAREHOUSE_NAME,
    ROUND(TOTAL_QUEUED_MS / 1000, 0) || ' queued seconds; p95 execution ' || ROUND(P95_EXECUTION_MS / 1000, 0) || 's in the last 24 hours.',
    ROUND(TOTAL_QUEUED_MS / 1000, 0) || ' queued seconds; p95 execution ' || ROUND(P95_EXECUTION_MS / 1000, 0) || 's in the last 24 hours.',
    'Open Cost & Contract, inspect pressure telemetry, and route changed-only warehouse setting recommendations.',
    'SELECT * FROM FACT_QUERY_HOURLY WHERE WAREHOUSE_NAME = ''' || WAREHOUSE_NAME || ''' ORDER BY HOUR_START DESC LIMIT 100;',
    'DBA'
  FROM warehouse_pressure

  UNION ALL

  SELECT
    COMPANY, ENVIRONMENT, DATABASE_NAME, SCHEMA_NAME, WAREHOUSE_NAME,
    'Reliability', 'Task Failure', 'High',
    DATABASE_NAME || '.' || SCHEMA_NAME || '.' || TASK_NAME,
    DATABASE_NAME || '.' || SCHEMA_NAME || '.' || TASK_NAME,
    FAILURES || ' failed task run(s) in the last 24 hours. Sample: ' || COALESCE(SAMPLE_ERROR, 'No sample error captured.'),
    FAILURES || ' failed task run(s) in the last 24 hours. Sample: ' || COALESCE(SAMPLE_ERROR, 'No sample error captured.'),
    'Open Workload Operations task graphs, review downstream impact, and decide retry/suspend/escalate.',
    'SELECT * FROM FACT_TASK_RUN WHERE TASK_NAME = ''' || TASK_NAME || ''' ORDER BY SCHEDULED_TIME DESC LIMIT 100;',
    'DBA'
  FROM task_failures

  UNION ALL

  SELECT
    COMPANY, ENVIRONMENT, DATABASE_NAME, SCHEMA_NAME, NULL,
    'Reliability',
    CASE WHEN FAILURES > 0 THEN 'Stored Procedure Failure' ELSE 'Stored Procedure Runtime Spike' END,
    CASE WHEN FAILURES > 0 OR AVG_DURATION_MS >= 300000 THEN 'High' ELSE 'Medium' END,
    COALESCE(DATABASE_NAME || '.' || SCHEMA_NAME || '.', DATABASE_NAME || '.', '') || PROCEDURE_NAME,
    COALESCE(DATABASE_NAME || '.' || SCHEMA_NAME || '.', DATABASE_NAME || '.', '') || PROCEDURE_NAME,
    CASE
      WHEN FAILURES > 0 THEN FAILURES || ' failed CALL(s) in the last 24 hours. Sample: ' || COALESCE(SAMPLE_ERROR, 'No sample error captured.')
      ELSE 'Average CALL duration ' || ROUND(AVG_DURATION_MS / 1000, 1) || 's vs baseline ' || ROUND(BASELINE_DURATION_MS / 1000, 1) || 's.'
    END,
    CASE
      WHEN FAILURES > 0 THEN FAILURES || ' failed CALL(s) in the last 24 hours. Sample: ' || COALESCE(SAMPLE_ERROR, 'No sample error captured.')
      ELSE 'Average CALL duration ' || ROUND(AVG_DURATION_MS / 1000, 1) || 's vs baseline ' || ROUND(BASELINE_DURATION_MS / 1000, 1) || 's.'
    END,
    'Open Workload Operations stored procedures, compare release windows, and assign remediation.',
    'SELECT * FROM FACT_PROCEDURE_RUN WHERE PROCEDURE_NAME = ''' || PROCEDURE_NAME || ''''
      || ' AND COALESCE(DATABASE_NAME, '''') = ''' || COALESCE(DATABASE_NAME, '') || ''''
      || ' AND COALESCE(SCHEMA_NAME, '''') = ''' || COALESCE(SCHEMA_NAME, '') || ''''
      || ' ORDER BY START_TIME DESC LIMIT 100;',
    'DBA'
  FROM procedure_risk

  UNION ALL

  SELECT
    COMPANY, ENVIRONMENT, DATABASE_NAME, SCHEMA_NAME, NULL,
    'Object Change Monitoring', 'Grant/Revoke Activity', 'Medium',
    COALESCE(DATABASE_NAME || '.' || SCHEMA_NAME, ROLE_NAME, USER_NAME, 'Account grant activity'),
    COALESCE(DATABASE_NAME || '.' || SCHEMA_NAME, ROLE_NAME, USER_NAME, 'Account grant activity'),
    CHANGE_COUNT || ' grant/revoke statement(s) by ' || COALESCE(USER_NAME, 'unknown user') || ' using role ' || COALESCE(ROLE_NAME, 'unknown role') || '.',
    CHANGE_COUNT || ' grant/revoke statement(s) by ' || COALESCE(USER_NAME, 'unknown user') || ' using role ' || COALESCE(ROLE_NAME, 'unknown role') || '.',
    'Open Security Monitoring and review least-privilege telemetry, actor, object, and review date.',
    'SELECT * FROM FACT_OBJECT_CHANGE WHERE START_TIME >= DATEADD(''hour'', -24, CURRENT_TIMESTAMP()) AND (QUERY_TYPE ILIKE ''GRANT%'' OR QUERY_TYPE ILIKE ''REVOKE%'') ORDER BY START_TIME DESC LIMIT 100;',
    'DBA'
  FROM grant_changes

  UNION ALL

  SELECT
    COMPANY, 'No Database Context', NULL, NULL, WAREHOUSE_NAME,
    'Object Change Monitoring', 'Warehouse Setting Change', 'Medium',
    WAREHOUSE_NAME,
    WAREHOUSE_NAME,
    CHANGE_COUNT || ' ALTER WAREHOUSE statement(s) by ' || COALESCE(USER_NAME, 'unknown user') || ' using role ' || COALESCE(ROLE_NAME, 'unknown role') || '.',
    CHANGE_COUNT || ' ALTER WAREHOUSE statement(s) by ' || COALESCE(USER_NAME, 'unknown user') || ' using role ' || COALESCE(ROLE_NAME, 'unknown role') || '.',
    'Open DBA Tools warehouse settings manager and review changed-only SQL, rollback path, and post-change telemetry.',
    'SELECT * FROM FACT_OBJECT_CHANGE WHERE QUERY_TEXT ILIKE ''ALTER WAREHOUSE %'' ORDER BY START_TIME DESC LIMIT 100;',
    'DBA'
  FROM warehouse_changes
)
SELECT
  CURRENT_TIMESTAMP(),
  c.COMPANY,
  COALESCE(c.ENVIRONMENT, 'No Database Context'),
  c.DATABASE_NAME,
  c.SCHEMA_NAME,
  c.WAREHOUSE_NAME,
  c.CATEGORY,
  c.ALERT_TYPE,
  c.SEVERITY,
  c.ENTITY_NAME,
  c.ENTITY,
  c.MESSAGE,
  c.DETAIL,
  c.SUGGESTED_ACTION,
  c.PROOF_QUERY,
  c.OWNER,
  'New',
  'EMAIL',
  cfg.EMAIL_TARGET,
  cfg.EMAIL_TARGET,
  'OVERWATCH ' || c.SEVERITY || ': ' || c.ALERT_TYPE || ' - ' || c.ENTITY_NAME,
  'Company: ' || c.COMPANY || CHAR(10)
    || 'Environment: ' || COALESCE(c.ENVIRONMENT, 'No Database Context') || CHAR(10)
    || 'Severity: ' || c.SEVERITY || CHAR(10)
    || 'Alert: ' || c.ALERT_TYPE || CHAR(10)
    || 'Entity: ' || c.ENTITY_NAME || CHAR(10) || CHAR(10)
    || 'Detail:' || CHAR(10) || c.MESSAGE || CHAR(10) || CHAR(10)
    || 'Next action:' || CHAR(10) || c.SUGGESTED_ACTION || CHAR(10) || CHAR(10)
    || 'Proof query:' || CHAR(10) || c.PROOF_QUERY,
  IFF(cfg.EMAIL_TARGET IS NULL, 'CONFIG_REQUIRED', 'EMAIL_READY')
FROM candidates c
CROSS JOIN alert_config cfg
WHERE NOT EXISTS (
  SELECT 1
  FROM OVERWATCH_ANNOTATIONS ann
  WHERE ann.ACTIVE = TRUE
    AND ann.SUPPRESS_ALERTS = TRUE
    AND (UPPER(ann.ENTITY) = UPPER(c.ENTITY_NAME)
         OR UPPER(ann.ENTITY) = UPPER(COALESCE(c.WAREHOUSE_NAME, ''))
         OR UPPER(ann.ENTITY_TYPE) = 'GLOBAL')
    AND CURRENT_TIMESTAMP() BETWEEN ann.WINDOW_START AND ann.WINDOW_END
)
AND NOT EXISTS (
  SELECT 1
  FROM OVERWATCH_ALERTS existing
  WHERE existing.ALERT_TS >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
    AND COALESCE(existing.CATEGORY, existing.ALERT_TYPE, '') = c.CATEGORY
    AND COALESCE(existing.ENTITY_NAME, existing.ENTITY, '') = c.ENTITY_NAME
    AND UPPER(COALESCE(existing.STATUS, 'New')) NOT IN ('FIXED', 'IGNORED', 'RESOLVED')
);
