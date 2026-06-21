-- OVERWATCH mart setup split: 09_validation.sql

-- Run smoke checks and optional initial refresh calls.

-- Source bundle: snowflake/OVERWATCH_MART_SETUP.sql



USE DATABASE DBA_MAINT_DB;
USE SCHEMA OVERWATCH;



-- Validation includes smoke SELECTs and initial refresh CALLs; run after tasks/procedures are created.




MERGE INTO OVERWATCH_SETTINGS tgt
USING (
  SELECT * FROM VALUES
    ('CREDIT_PRICE_USD', '3.68', 'NUMBER', 'Contract credit price used for estimated cost display.'),
    ('AI_CREDIT_PRICE_USD', '2.20', 'NUMBER', 'Cortex AI/token credit price used for estimated AI cost display.'),
    ('STORAGE_COST_PER_TB_USD', '23.00', 'NUMBER', 'Standard storage cost per TB-month used for estimated storage cost display.'),
    ('MART_QUERY_RETENTION_DAYS', '35', 'NUMBER', 'Rolling window reloaded from ACCOUNT_USAGE query history.'),
    ('DETAIL_RETENTION_DAYS', '30', 'NUMBER', 'Retention for recent query/task/procedure detail marts.'),
    ('AGG_RETENTION_DAYS', '730', 'NUMBER', 'Retention for hourly and daily aggregate marts.'),
    ('SLA_DURATION_MULTIPLIER', '1.5', 'NUMBER', 'Flags task/procedure latest duration over this multiple of historical average.'),
    ('DEFAULT_ALERT_EMAIL', 'jdees@alfains.com', 'STRING', 'Approved default email recipient list for OVERWATCH alert messages. Override only through governance-approved Snowflake settings.'),
    ('ALERT_DELIVERY_METHOD', 'EMAIL', 'STRING', 'Alert delivery channel used by the OVERWATCH anomaly task.'),
    ('ALERT_EMAIL_NOTIFICATION_INTEGRATION', 'OVERWATCH_EMAIL_INT', 'STRING', 'Approved Snowflake notification integration name for optional Alert Center email delivery.')
) src(SETTING_NAME, SETTING_VALUE, SETTING_TYPE, DESCRIPTION)
ON tgt.SETTING_NAME = src.SETTING_NAME
WHEN MATCHED THEN UPDATE SET
  SETTING_VALUE = CASE
    WHEN src.SETTING_NAME = 'DEFAULT_ALERT_EMAIL'
      THEN IFF(NULLIF(TRIM(COALESCE(tgt.SETTING_VALUE, '')), '') IS NULL OR COALESCE(tgt.SETTING_VALUE, '') ILIKE '%yourcompany.com%', src.SETTING_VALUE, tgt.SETTING_VALUE)
    ELSE tgt.SETTING_VALUE
  END,
  SETTING_TYPE = src.SETTING_TYPE,
  DESCRIPTION = src.DESCRIPTION
WHEN NOT MATCHED THEN INSERT (SETTING_NAME, SETTING_VALUE, SETTING_TYPE, DESCRIPTION)
VALUES (src.SETTING_NAME, src.SETTING_VALUE, src.SETTING_TYPE, src.DESCRIPTION);


MERGE INTO OVERWATCH_SCHEMA_MIGRATION tgt
USING (
  SELECT
    '2026.06.13-executive-observability-mart' AS MIGRATION_VERSION,
    'Executive observability mart, cost telemetry, procedure context, alert delivery, and migration ledger' AS MIGRATION_NAME,
    'snowflake/OVERWATCH_MART_SETUP.sql' AS SOURCE_FILE,
    'Baseline setup ledger row for the app release, including the executive first-paint observability mart, cost telemetry marts, procedure database/schema context, alert delivery, and migration tracking.' AS NOTES
) src
ON tgt.MIGRATION_VERSION = src.MIGRATION_VERSION
WHEN MATCHED THEN UPDATE SET
  MIGRATION_NAME = src.MIGRATION_NAME,
  SOURCE_FILE = src.SOURCE_FILE,
  NOTES = src.NOTES
WHEN NOT MATCHED THEN INSERT (MIGRATION_VERSION, MIGRATION_NAME, SOURCE_FILE, NOTES)
VALUES (src.MIGRATION_VERSION, src.MIGRATION_NAME, src.SOURCE_FILE, src.NOTES);


MERGE INTO OVERWATCH_SCHEMA_MIGRATION tgt
USING (
  SELECT
    '2026.06.17-enterprise-operating-model' AS MIGRATION_VERSION,
    'Data trust, operational ownership, value ledger, and app self-observability marts' AS MIGRATION_NAME,
    'snowflake/OVERWATCH_MART_SETUP.sql' AS SOURCE_FILE,
    'Adds the Phase 1 enterprise operating model: Finding -> Owner -> Trust Level -> Business Impact -> Action -> Value Verified. First-paint surfaces read compact marts; detail evidence remains explicit-load only.' AS NOTES
) src
ON tgt.MIGRATION_VERSION = src.MIGRATION_VERSION
WHEN MATCHED THEN UPDATE SET
  MIGRATION_NAME = src.MIGRATION_NAME,
  SOURCE_FILE = src.SOURCE_FILE,
  NOTES = src.NOTES
WHEN NOT MATCHED THEN INSERT (MIGRATION_VERSION, MIGRATION_NAME, SOURCE_FILE, NOTES)
VALUES (src.MIGRATION_VERSION, src.MIGRATION_NAME, src.SOURCE_FILE, src.NOTES);


MERGE INTO OVERWATCH_SCHEMA_MIGRATION tgt
USING (
  SELECT
    '2026.06.18-production-readiness' AS MIGRATION_VERSION,
    'Production readiness dashboard, role/privilege/readiness validation, and refresh health marts' AS MIGRATION_NAME,
    'snowflake/OVERWATCH_MART_SETUP.sql' AS SOURCE_FILE,
    'Adds Phase 2A live production validation. First-paint surfaces read a compact readiness mart; role, privilege, validation, and refresh proof rows remain explicit-load diagnostics.' AS NOTES
) src
ON tgt.MIGRATION_VERSION = src.MIGRATION_VERSION
WHEN MATCHED THEN UPDATE SET
  MIGRATION_NAME = src.MIGRATION_NAME,
  SOURCE_FILE = src.SOURCE_FILE,
  NOTES = src.NOTES
WHEN NOT MATCHED THEN INSERT (MIGRATION_VERSION, MIGRATION_NAME, SOURCE_FILE, NOTES)
VALUES (src.MIGRATION_VERSION, src.MIGRATION_NAME, src.SOURCE_FILE, src.NOTES);


MERGE INTO OVERWATCH_SCHEMA_MIGRATION tgt
USING (
  SELECT
    '2026.06.18-executive-scorecard' AS MIGRATION_VERSION,
    'Executive Scorecard leadership health scoring across health, cost, security, risk, trust, and production readiness' AS MIGRATION_NAME,
    'snowflake/OVERWATCH_MART_SETUP.sql' AS SOURCE_FILE,
    'Adds Phase 2B Executive Scorecard. First-paint surfaces read compact scorecard marts; driver evidence remains explicit-load only.' AS NOTES
) src
ON tgt.MIGRATION_VERSION = src.MIGRATION_VERSION
WHEN MATCHED THEN UPDATE SET
  MIGRATION_NAME = src.MIGRATION_NAME,
  SOURCE_FILE = src.SOURCE_FILE,
  NOTES = src.NOTES
WHEN NOT MATCHED THEN INSERT (MIGRATION_VERSION, MIGRATION_NAME, SOURCE_FILE, NOTES)
VALUES (src.MIGRATION_VERSION, src.MIGRATION_NAME, src.SOURCE_FILE, src.NOTES);


MERGE INTO OVERWATCH_SCHEMA_MIGRATION tgt
USING (
  SELECT
    '2026.06.18-executive-forecasting' AS MIGRATION_VERSION,
    'Executive forecasting for cost, contract burn, storage, queue pressure, and SLA risk' AS MIGRATION_NAME,
    'snowflake/OVERWATCH_MART_SETUP.sql' AS SOURCE_FILE,
    'Adds Phase 2C Forecasting. First-paint surfaces read compact forecast summaries; historical forecast drivers and evidence remain explicit-load only. Forecasts are estimates and are not counted as verified savings.' AS NOTES
) src
ON tgt.MIGRATION_VERSION = src.MIGRATION_VERSION
WHEN MATCHED THEN UPDATE SET
  MIGRATION_NAME = src.MIGRATION_NAME,
  SOURCE_FILE = src.SOURCE_FILE,
  NOTES = src.NOTES
WHEN NOT MATCHED THEN INSERT (MIGRATION_VERSION, MIGRATION_NAME, SOURCE_FILE, NOTES)
VALUES (src.MIGRATION_VERSION, src.MIGRATION_NAME, src.SOURCE_FILE, src.NOTES);


MERGE INTO OVERWATCH_SCHEMA_MIGRATION tgt
USING (
  SELECT
    '2026.06.18-change-intelligence' AS MIGRATION_VERSION,
    'Change Intelligence for warehouse, access, object, task, procedure, policy, and integration changes' AS MIGRATION_NAME,
    'snowflake/OVERWATCH_MART_SETUP.sql' AS SOURCE_FILE,
    'Adds Phase 2D Change Intelligence. First-paint surfaces read compact change-risk summaries; change evidence and possible correlations remain explicit-load only. Correlations are not root-cause claims.' AS NOTES
) src
ON tgt.MIGRATION_VERSION = src.MIGRATION_VERSION
WHEN MATCHED THEN UPDATE SET
  MIGRATION_NAME = src.MIGRATION_NAME,
  SOURCE_FILE = src.SOURCE_FILE,
  NOTES = src.NOTES
WHEN NOT MATCHED THEN INSERT (MIGRATION_VERSION, MIGRATION_NAME, SOURCE_FILE, NOTES)
VALUES (src.MIGRATION_VERSION, src.MIGRATION_NAME, src.SOURCE_FILE, src.NOTES);


MERGE INTO OVERWATCH_SCHEMA_MIGRATION tgt
USING (
  SELECT
    '2026.06.18-closed-loop-operations' AS MIGRATION_VERSION,
    'Closed Loop Operations for action, approval, execution-plan, verification, and value evidence' AS MIGRATION_NAME,
    'snowflake/OVERWATCH_MART_SETUP.sql' AS SOURCE_FILE,
    'Adds Phase 2E Closed Loop Operations. First-paint surfaces read compact action workflow summaries; approval, review SQL, evidence, and verification detail remain explicit-load only. No remediation SQL is executed by the refresh procedure.' AS NOTES
) src
ON tgt.MIGRATION_VERSION = src.MIGRATION_VERSION
WHEN MATCHED THEN UPDATE SET
  MIGRATION_NAME = src.MIGRATION_NAME,
  SOURCE_FILE = src.SOURCE_FILE,
  NOTES = src.NOTES
WHEN NOT MATCHED THEN INSERT (MIGRATION_VERSION, MIGRATION_NAME, SOURCE_FILE, NOTES)
VALUES (src.MIGRATION_VERSION, src.MIGRATION_NAME, src.SOURCE_FILE, src.NOTES);


MERGE INTO OVERWATCH_SCHEMA_MIGRATION tgt
USING (
  SELECT
    '2026.06.18-command-center' AS MIGRATION_VERSION,
    'Command Center correlation for cost, performance, alert, ownership, trust, security, change, forecast, value, and action evidence' AS MIGRATION_NAME,
    'snowflake/OVERWATCH_MART_SETUP.sql' AS SOURCE_FILE,
    'Adds Phase 2F Command Center. First-paint surfaces read compact command findings; investigation evidence and recommendations remain explicit-load only. Root-cause language is candidate/correlation based and no remediation is executed.' AS NOTES
) src
ON tgt.MIGRATION_VERSION = src.MIGRATION_VERSION
WHEN MATCHED THEN UPDATE SET
  MIGRATION_NAME = src.MIGRATION_NAME,
  SOURCE_FILE = src.SOURCE_FILE,
  NOTES = src.NOTES
WHEN NOT MATCHED THEN INSERT (MIGRATION_VERSION, MIGRATION_NAME, SOURCE_FILE, NOTES)
VALUES (src.MIGRATION_VERSION, src.MIGRATION_NAME, src.SOURCE_FILE, src.NOTES);


MERGE INTO OVERWATCH_SCHEMA_MIGRATION tgt
USING (
  SELECT
    '2026.06.18-governance-alignment-rc' AS MIGRATION_VERSION,
    'Governance Alignment Release Candidate for approved alert route, target roles, interim access, Trexis coverage, and drift classification' AS MIGRATION_NAME,
    'snowflake/OVERWATCH_MART_SETUP.sql' AS SOURCE_FILE,
    'Aligns production readiness scoring with approved governance assumptions without executing grants or dropping legacy objects. True telemetry freshness gaps remain review items.' AS NOTES
) src
ON tgt.MIGRATION_VERSION = src.MIGRATION_VERSION
WHEN MATCHED THEN UPDATE SET
  MIGRATION_NAME = src.MIGRATION_NAME,
  SOURCE_FILE = src.SOURCE_FILE,
  NOTES = src.NOTES
WHEN NOT MATCHED THEN INSERT (MIGRATION_VERSION, MIGRATION_NAME, SOURCE_FILE, NOTES)
VALUES (src.MIGRATION_VERSION, src.MIGRATION_NAME, src.SOURCE_FILE, src.NOTES);


MERGE INTO OVERWATCH_OWNER_TAG_NAMES tgt
USING (
  SELECT * FROM VALUES
    ('COST_OWNER',        'COST',        10, TRUE, 'Preferred chargeback owner tag.'),
    ('DATA_OWNER',        'DATA',        20, TRUE, 'Database/schema/table data owner fallback.'),
    ('APP_OWNER',         'APPLICATION', 30, TRUE, 'Application owner fallback.'),
    ('APPLICATION_OWNER', 'APPLICATION', 35, TRUE, 'Alternate application owner tag.'),
    ('BUSINESS_OWNER',    'BUSINESS',    40, TRUE, 'Business owner fallback.'),
    ('SERVICE_OWNER',     'SERVICE',     50, TRUE, 'Service owner fallback.')
) src(TAG_NAME, OWNER_TYPE, PRIORITY, IS_ACTIVE, NOTES)
ON UPPER(tgt.TAG_NAME) = UPPER(src.TAG_NAME)
WHEN MATCHED THEN UPDATE SET
  OWNER_TYPE = src.OWNER_TYPE,
  PRIORITY = src.PRIORITY,
  IS_ACTIVE = src.IS_ACTIVE,
  NOTES = src.NOTES
WHEN NOT MATCHED THEN INSERT (TAG_NAME, OWNER_TYPE, PRIORITY, IS_ACTIVE, NOTES)
VALUES (src.TAG_NAME, src.OWNER_TYPE, src.PRIORITY, src.IS_ACTIVE, src.NOTES);


MERGE INTO ALERT_DATA_QUALITY_CHECKS tgt
USING (
  SELECT * FROM VALUES
    ('DQ_ORDER_FRESHNESS', 'ALFA_EDW_PROD', 'CURATED', 'FACT_ORDER', 'LOAD_TS', 'FRESHNESS_SLA_HOURS', 24, '>', 'High', 'Data Owner', 'DATA_QUALITY', FALSE),
    ('DQ_POLICY_NULL_RATE', 'ALFA_EDW_PROD', 'CURATED', 'DIM_POLICY', 'POLICY_ID', 'NULL_RATE_PCT', 0, '>', 'Critical', 'Data Owner', 'DATA_QUALITY', FALSE),
    ('DQ_CLAIM_VOLUME_DROP', 'ALFA_EDW_PROD', 'CURATED', 'FACT_CLAIM', '*', 'ROW_COUNT_DROP_PCT', 35, '>', 'High', 'Data Owner', 'DATA_QUALITY', FALSE)
) src(CHECK_KEY, DATABASE_NAME, SCHEMA_NAME, TABLE_NAME, COLUMN_NAME, CHECK_TYPE, THRESHOLD_VALUE, COMPARISON_OPERATOR, SEVERITY, OWNER, NOTIFICATION_CHANNEL, ENABLED)
ON tgt.CHECK_KEY = src.CHECK_KEY
WHEN MATCHED THEN UPDATE SET
  DATABASE_NAME = src.DATABASE_NAME,
  SCHEMA_NAME = src.SCHEMA_NAME,
  TABLE_NAME = src.TABLE_NAME,
  COLUMN_NAME = src.COLUMN_NAME,
  CHECK_TYPE = src.CHECK_TYPE,
  THRESHOLD_VALUE = src.THRESHOLD_VALUE,
  COMPARISON_OPERATOR = src.COMPARISON_OPERATOR,
  SEVERITY = src.SEVERITY,
  OWNER = src.OWNER,
  NOTIFICATION_CHANNEL = src.NOTIFICATION_CHANNEL,
  UPDATED_AT = CURRENT_TIMESTAMP(),
  UPDATED_BY = CURRENT_USER()
WHEN NOT MATCHED THEN INSERT
  (CHECK_KEY, DATABASE_NAME, SCHEMA_NAME, TABLE_NAME, COLUMN_NAME, CHECK_TYPE, THRESHOLD_VALUE, COMPARISON_OPERATOR, SEVERITY, OWNER, NOTIFICATION_CHANNEL, ENABLED)
VALUES
  (src.CHECK_KEY, src.DATABASE_NAME, src.SCHEMA_NAME, src.TABLE_NAME, src.COLUMN_NAME, src.CHECK_TYPE, src.THRESHOLD_VALUE, src.COMPARISON_OPERATOR, src.SEVERITY, src.OWNER, src.NOTIFICATION_CHANNEL, src.ENABLED);


MERGE INTO ALERT_NATIVE_OBJECT_REGISTRY tgt
USING (
  SELECT * FROM VALUES
    ('NATIVE_COST_CORTEX_SPEND_SPIKE', 'COST_CORTEX_SPEND_SPIKE', 'Cost', 'OVERWATCH_ALERT_CORTEX_SPEND_SPIKE', 'Cost & Contract', 'OVERWATCH_WH', '60 MINUTE', 'CANDIDATE', 'FACT_CORTEX_DAILY company-labeled 7-day spend vs shared threshold', 'Insert recommend-only event into ALERT_EVENTS', 'CREATE OR REPLACE ALERT OVERWATCH_ALERT_CORTEX_SPEND_SPIKE WAREHOUSE = OVERWATCH_WH SCHEDULE = ''60 MINUTE'' IF (EXISTS (SELECT 1 FROM FACT_CORTEX_DAILY WHERE USAGE_DATE >= DATEADD(''day'', -7, CURRENT_DATE()) GROUP BY COMPANY HAVING SUM(EST_COST_USD) > 25)) THEN INSERT INTO ALERT_EVENTS (COMPANY, ENVIRONMENT, ALERT_KEY, CATEGORY, SEVERITY, STATUS, OWNER, RECOMMENDED_ACTION, ENTITY_TYPE, ENTITY_NAME, REMEDIATION_MODE) SELECT COALESCE(COMPANY, ''Account-Wide''), ''ALL'', ''COST_CORTEX_SPEND_SPIKE'', ''Cost'', ''High'', ''New'', ''DBA / AI cost route'', ''Review Cortex user/source spend, quota settings, grants, and company scope before changing access.'', ''CORTEX'', ''CORTEX'', ''RECOMMEND'' FROM FACT_CORTEX_DAILY WHERE USAGE_DATE >= DATEADD(''day'', -7, CURRENT_DATE()) GROUP BY COMPANY HAVING SUM(EST_COST_USD) > 25;', 'DROP ALERT IF EXISTS OVERWATCH_ALERT_CORTEX_SPEND_SPIKE;', FALSE, 'Recommend-only. Do not alter Cortex access automatically.'),
    ('NATIVE_COST_WAREHOUSE_CREDIT_SPIKE', 'COST_WAREHOUSE_CREDIT_SPIKE', 'Cost', 'OVERWATCH_ALERT_WAREHOUSE_CREDIT_SPIKE', 'Cost & Contract', 'OVERWATCH_WH', '60 MINUTE', 'CANDIDATE', 'FACT_WAREHOUSE_HOURLY company-labeled current-day CREDITS_USED by warehouse', 'Insert recommend-only cost movement event into ALERT_EVENTS', 'CREATE OR REPLACE ALERT OVERWATCH_ALERT_WAREHOUSE_CREDIT_SPIKE WAREHOUSE = OVERWATCH_WH SCHEDULE = ''60 MINUTE'' IF (EXISTS (SELECT 1 FROM FACT_WAREHOUSE_HOURLY WHERE HOUR_START >= DATEADD(''hour'', -24, CURRENT_TIMESTAMP()) GROUP BY COMPANY, WAREHOUSE_NAME HAVING SUM(CREDITS_USED) > 10)) THEN INSERT INTO ALERT_EVENTS (COMPANY, ENVIRONMENT, ALERT_KEY, CATEGORY, SEVERITY, STATUS, OWNER, RECOMMENDED_ACTION, ENTITY_TYPE, ENTITY_NAME, WAREHOUSE_NAME, CURRENT_VALUE, REMEDIATION_MODE, EVIDENCE, DEDUPE_KEY) SELECT COALESCE(COMPANY, ''Shared/Unclassified''), ''ALL'', ''COST_WAREHOUSE_CREDIT_SPIKE'', ''Cost'', ''High'', ''New'', ''DBA / Cost owner'', ''Explain warehouse credit spike before changing capacity.'', ''WAREHOUSE'', WAREHOUSE_NAME, WAREHOUSE_NAME, SUM(CREDITS_USED), ''RECOMMEND'', ''Native candidate detected warehouse credits above threshold.'', SHA2(''COST_WAREHOUSE_CREDIT_SPIKE|'' || COALESCE(COMPANY, ''Shared/Unclassified'') || ''|'' || WAREHOUSE_NAME || ''|'' || TO_VARCHAR(CURRENT_DATE()), 256) FROM FACT_WAREHOUSE_HOURLY WHERE HOUR_START >= DATEADD(''hour'', -24, CURRENT_TIMESTAMP()) GROUP BY COMPANY, WAREHOUSE_NAME HAVING SUM(CREDITS_USED) > 10;', 'DROP ALERT IF EXISTS OVERWATCH_ALERT_WAREHOUSE_CREDIT_SPIKE;', FALSE, 'Recommend-only. Do not resize, suspend, or alter warehouses automatically.'),
    ('NATIVE_SECURITY_PRIVILEGE_ESCALATION', 'SECURITY_PRIVILEGE_ESCALATION', 'Security', 'OVERWATCH_ALERT_PRIVILEGE_ESCALATION', 'Security Monitoring', 'OVERWATCH_WH', '60 MINUTE', 'CANDIDATE', 'FACT_GRANT_DAILY company-labeled privileged role grants', 'Insert status-review event into ALERT_EVENTS', 'CREATE OR REPLACE ALERT OVERWATCH_ALERT_PRIVILEGE_ESCALATION WAREHOUSE = OVERWATCH_WH SCHEDULE = ''60 MINUTE'' IF (EXISTS (SELECT 1 FROM FACT_GRANT_DAILY WHERE SNAPSHOT_DATE >= DATEADD(''day'', -2, CURRENT_DATE()) AND CREATED_ON >= DATEADD(''hour'', -24, CURRENT_TIMESTAMP()) AND DELETED_ON IS NULL AND UPPER(ROLE_NAME) IN (''ACCOUNTADMIN'', ''SECURITYADMIN'', ''SYSADMIN'', ''ORGADMIN''))) THEN INSERT INTO ALERT_EVENTS (COMPANY, ENVIRONMENT, ALERT_KEY, CATEGORY, SEVERITY, STATUS, OWNER, RECOMMENDED_ACTION, ENTITY_TYPE, REMEDIATION_MODE) SELECT COALESCE(COMPANY, ''Shared/Unclassified''), ''No Database Context'', ''SECURITY_PRIVILEGE_ESCALATION'', ''Security'', ''Critical'', ''New'', ''Security Reviewer'', ''Validate ticket, reviewer, MFA posture, and access purpose before accepting the privileged grant.'', ''USER'', ''STATUS_REVIEW'' FROM FACT_GRANT_DAILY WHERE SNAPSHOT_DATE >= DATEADD(''day'', -2, CURRENT_DATE()) AND CREATED_ON >= DATEADD(''hour'', -24, CURRENT_TIMESTAMP()) AND DELETED_ON IS NULL AND UPPER(ROLE_NAME) IN (''ACCOUNTADMIN'', ''SECURITYADMIN'', ''SYSADMIN'', ''ORGADMIN'');', 'DROP ALERT IF EXISTS OVERWATCH_ALERT_PRIVILEGE_ESCALATION;', FALSE, 'Status-review only. Never auto-revoke from this alert.'),
    ('NATIVE_PIPELINE_TASK_FAILURE', 'PIPELINE_TASK_FAILURE', 'Task / Pipeline', 'OVERWATCH_ALERT_TASK_FAILURE', 'Workload Operations', 'OVERWATCH_WH', '30 MINUTE', 'CANDIDATE', 'FACT_TASK_RUN company/environment-labeled failed/skipped task graph rows', 'Insert status-review event into ALERT_EVENTS', 'CREATE OR REPLACE ALERT OVERWATCH_ALERT_TASK_FAILURE WAREHOUSE = OVERWATCH_WH SCHEDULE = ''30 MINUTE'' IF (EXISTS (SELECT 1 FROM FACT_TASK_RUN WHERE SCHEDULED_TIME >= DATEADD(''hour'', -2, CURRENT_TIMESTAMP()) AND UPPER(COALESCE(STATE, '''')) IN (''FAILED'', ''FAILED_WITH_ERROR'', ''SKIPPED'', ''CANCELLED''))) THEN INSERT INTO ALERT_EVENTS (COMPANY, ENVIRONMENT, ALERT_KEY, CATEGORY, SEVERITY, STATUS, OWNER, RECOMMENDED_ACTION, ENTITY_TYPE, REMEDIATION_MODE) SELECT COALESCE(COMPANY, ''Shared/Unclassified''), COALESCE(ENVIRONMENT, ''No Database Context''), ''PIPELINE_TASK_FAILURE'', ''Task / Pipeline'', ''Critical'', ''New'', ''DBA / Pipeline Owner'', ''Identify root task, failed child, last success, downstream SLA, and safe rerun conditions.'', ''TASK'', ''STATUS_REVIEW'' FROM FACT_TASK_RUN WHERE SCHEDULED_TIME >= DATEADD(''hour'', -2, CURRENT_TIMESTAMP()) AND UPPER(COALESCE(STATE, '''')) IN (''FAILED'', ''FAILED_WITH_ERROR'', ''SKIPPED'', ''CANCELLED'');', 'DROP ALERT IF EXISTS OVERWATCH_ALERT_TASK_FAILURE;', FALSE, 'Status-review only. Reruns require task graph safety checks.'),
    ('NATIVE_BEHAVIOR_USER_QUERY_ANOMALY', 'BEHAVIOR_USER_QUERY_ANOMALY', 'Behavior', 'OVERWATCH_ALERT_USER_QUERY_BEHAVIOR', 'Workload Operations', 'OVERWATCH_WH', '60 MINUTE', 'CANDIDATE', 'FACT_QUERY_DETAIL_RECENT company/environment-labeled user failure, runtime, spill, and warehouse pressure patterns', 'Insert status-review behavior event into ALERT_EVENTS', 'CREATE OR REPLACE ALERT OVERWATCH_ALERT_USER_QUERY_BEHAVIOR WAREHOUSE = OVERWATCH_WH SCHEDULE = ''60 MINUTE'' IF (EXISTS (SELECT 1 FROM FACT_QUERY_DETAIL_RECENT WHERE START_TIME >= DATEADD(''hour'', -2, CURRENT_TIMESTAMP()) GROUP BY COMPANY, ENVIRONMENT, USER_NAME, ROLE_NAME, WAREHOUSE_NAME HAVING COUNT(*) >= 10)) THEN INSERT INTO ALERT_EVENTS (COMPANY, ENVIRONMENT, ALERT_KEY, CATEGORY, SEVERITY, STATUS, OWNER, RECOMMENDED_ACTION, ENTITY_TYPE, REMEDIATION_MODE) SELECT COALESCE(COMPANY, ''Shared/Unclassified''), COALESCE(ENVIRONMENT, ''No Database Context''), ''BEHAVIOR_USER_QUERY_ANOMALY'', ''Behavior'', ''High'', ''New'', ''DBA / Workload reviewer'', ''Review repeated user query behavior before controls.'', ''USER'', ''STATUS_REVIEW'' FROM FACT_QUERY_DETAIL_RECENT WHERE START_TIME >= DATEADD(''hour'', -2, CURRENT_TIMESTAMP()) GROUP BY COMPANY, ENVIRONMENT, USER_NAME, ROLE_NAME, WAREHOUSE_NAME HAVING COUNT(*) >= 10;', 'DROP ALERT IF EXISTS OVERWATCH_ALERT_USER_QUERY_BEHAVIOR;', FALSE, 'Status-review only. Do not cancel queries, disable users, or change grants automatically.')
) src(REGISTRY_KEY, ALERT_KEY, CATEGORY, ALERT_OBJECT_NAME, TARGET_ROUTE, WAREHOUSE_NAME, SCHEDULE_TEXT, STATUS, CONDITION_SOURCE, ACTION_SOURCE, GENERATED_CREATE_SQL, GENERATED_DROP_SQL, ENABLED_BY_DEFAULT, SAFETY_NOTE)
ON tgt.REGISTRY_KEY = src.REGISTRY_KEY
WHEN MATCHED THEN UPDATE SET
  ALERT_KEY = src.ALERT_KEY,
  CATEGORY = src.CATEGORY,
  ALERT_OBJECT_NAME = src.ALERT_OBJECT_NAME,
  TARGET_ROUTE = src.TARGET_ROUTE,
  WAREHOUSE_NAME = src.WAREHOUSE_NAME,
  SCHEDULE_TEXT = src.SCHEDULE_TEXT,
  STATUS = src.STATUS,
  CONDITION_SOURCE = src.CONDITION_SOURCE,
  ACTION_SOURCE = src.ACTION_SOURCE,
  GENERATED_CREATE_SQL = src.GENERATED_CREATE_SQL,
  GENERATED_DROP_SQL = src.GENERATED_DROP_SQL,
  ENABLED_BY_DEFAULT = src.ENABLED_BY_DEFAULT,
  SAFETY_NOTE = src.SAFETY_NOTE,
  UPDATED_AT = CURRENT_TIMESTAMP(),
  UPDATED_BY = CURRENT_USER()
WHEN NOT MATCHED THEN INSERT
  (REGISTRY_KEY, ALERT_KEY, CATEGORY, ALERT_OBJECT_NAME, TARGET_ROUTE, WAREHOUSE_NAME, SCHEDULE_TEXT, STATUS, CONDITION_SOURCE, ACTION_SOURCE, GENERATED_CREATE_SQL, GENERATED_DROP_SQL, ENABLED_BY_DEFAULT, SAFETY_NOTE)
VALUES
  (src.REGISTRY_KEY, src.ALERT_KEY, src.CATEGORY, src.ALERT_OBJECT_NAME, src.TARGET_ROUTE, src.WAREHOUSE_NAME, src.SCHEDULE_TEXT, src.STATUS, src.CONDITION_SOURCE, src.ACTION_SOURCE, src.GENERATED_CREATE_SQL, src.GENERATED_DROP_SQL, src.ENABLED_BY_DEFAULT, src.SAFETY_NOTE);


MERGE INTO ALERT_THRESHOLDS tgt
USING (
  SELECT * FROM VALUES
    ('SECURITY_FAILED_LOGIN_SPIKE', 'Security', 'Failed login spike', 'High', 10, 14, 60, 'DBA / Security', 'DBA_SECURITY'),
    ('SECURITY_PRIVILEGE_ESCALATION', 'Security', 'Privileged role grant', 'Critical', 1, 7, 1440, 'Security Approver', 'DBA_SECURITY'),
    ('COST_WAREHOUSE_CREDIT_SPIKE', 'Cost', 'Warehouse credit spike', 'High', 1.5, 30, 1440, 'DBA / Cost owner', 'COST'),
    ('COST_CORTEX_SPEND_SPIKE', 'Cost', 'Cortex spend spike', 'High', 25, 30, 10080, 'DBA / AI cost route', 'COST'),
    ('BEHAVIOR_USER_QUERY_ANOMALY', 'Behavior', 'User query behavior anomaly', 'High', 10, 14, 120, 'DBA / Workload reviewer', 'DBA_ONCALL'),
    ('PERF_QUEUE_PRESSURE', 'Performance', 'Warehouse queue pressure', 'High', 300, 14, 60, 'DBA / Platform', 'DBA_ONCALL'),
    ('PIPELINE_TASK_FAILURE', 'Task / Pipeline', 'Production task failure', 'Critical', 1, 7, 1440, 'DBA / Pipeline Owner', 'PIPELINE_ONCALL'),
    ('DQ_FRESHNESS_SLA', 'Data Quality', 'Freshness SLA missed', 'High', 1, 7, 1440, 'Data Owner', 'DATA_QUALITY'),
    ('OPT_UNUSED_WAREHOUSE', 'Optimization', 'Unused or oversized warehouse', 'Medium', 14, 30, 1440, 'DBA / Cost owner', 'COST')
) src(THRESHOLD_KEY, CATEGORY, SIGNAL_NAME, SEVERITY, THRESHOLD_VALUE, BASELINE_WINDOW_DAYS, CURRENT_WINDOW_MINUTES, OWNER, NOTIFICATION_CHANNEL)
ON tgt.THRESHOLD_KEY = src.THRESHOLD_KEY
WHEN MATCHED THEN UPDATE SET
  CATEGORY = src.CATEGORY,
  SIGNAL_NAME = src.SIGNAL_NAME,
  SEVERITY = src.SEVERITY,
  THRESHOLD_VALUE = src.THRESHOLD_VALUE,
  BASELINE_WINDOW_DAYS = src.BASELINE_WINDOW_DAYS,
  CURRENT_WINDOW_MINUTES = src.CURRENT_WINDOW_MINUTES,
  OWNER = src.OWNER,
  NOTIFICATION_CHANNEL = src.NOTIFICATION_CHANNEL,
  UPDATED_AT = CURRENT_TIMESTAMP(),
  UPDATED_BY = CURRENT_USER()
WHEN NOT MATCHED THEN INSERT
  (THRESHOLD_KEY, CATEGORY, SIGNAL_NAME, SEVERITY, THRESHOLD_VALUE, BASELINE_WINDOW_DAYS, CURRENT_WINDOW_MINUTES, OWNER, NOTIFICATION_CHANNEL)
VALUES
  (src.THRESHOLD_KEY, src.CATEGORY, src.SIGNAL_NAME, src.SEVERITY, src.THRESHOLD_VALUE, src.BASELINE_WINDOW_DAYS, src.CURRENT_WINDOW_MINUTES, src.OWNER, src.NOTIFICATION_CHANNEL);


MERGE INTO ALERT_CONFIG tgt
USING (
  SELECT * FROM VALUES
    ('SECURITY_FAILED_LOGIN_SPIKE', 'Security', 'Failed login spike', 'High', 'DBA / Security', 'Security Monitoring', 'DBA_SECURITY'),
    ('SECURITY_PRIVILEGE_ESCALATION', 'Security', 'Privileged role grant', 'Critical', 'Security Reviewer', 'Security Monitoring', 'DBA_SECURITY'),
    ('COST_WAREHOUSE_CREDIT_SPIKE', 'Cost', 'Warehouse credit spike', 'High', 'DBA / Cost owner', 'Cost & Contract', 'COST'),
    ('COST_CORTEX_SPEND_SPIKE', 'Cost', 'Cortex spend spike', 'High', 'DBA / AI cost route', 'Cost & Contract', 'COST'),
    ('BEHAVIOR_USER_QUERY_ANOMALY', 'Behavior', 'User query behavior anomaly', 'High', 'DBA / Workload reviewer', 'Workload Operations', 'DBA_ONCALL'),
    ('PERF_QUEUE_PRESSURE', 'Performance', 'Warehouse queue pressure', 'High', 'DBA / Platform', 'Workload Operations', 'DBA_ONCALL'),
    ('PIPELINE_TASK_FAILURE', 'Task / Pipeline', 'Production task failure', 'Critical', 'DBA / Pipeline Owner', 'Workload Operations', 'PIPELINE_ONCALL'),
    ('DQ_FRESHNESS_SLA', 'Data Quality', 'Freshness SLA missed', 'High', 'Data Owner', 'Workload Operations', 'DATA_QUALITY'),
    ('OPT_UNUSED_WAREHOUSE', 'Optimization', 'Unused or oversized warehouse', 'Medium', 'DBA / Cost owner', 'Cost & Contract', 'COST')
) src(ALERT_KEY, CATEGORY, SIGNAL_NAME, DEFAULT_SEVERITY, OWNER, ROUTE, NOTIFICATION_CHANNEL)
ON tgt.ALERT_KEY = src.ALERT_KEY
WHEN MATCHED THEN UPDATE SET
  CATEGORY = src.CATEGORY,
  SIGNAL_NAME = src.SIGNAL_NAME,
  DEFAULT_SEVERITY = src.DEFAULT_SEVERITY,
  OWNER = src.OWNER,
  ROUTE = src.ROUTE,
  NOTIFICATION_CHANNEL = src.NOTIFICATION_CHANNEL,
  UPDATED_AT = CURRENT_TIMESTAMP(),
  UPDATED_BY = CURRENT_USER()
WHEN NOT MATCHED THEN INSERT
  (ALERT_KEY, CATEGORY, SIGNAL_NAME, DEFAULT_SEVERITY, OWNER, ROUTE, NOTIFICATION_CHANNEL, TELEMETRY_LATENCY)
VALUES
  (src.ALERT_KEY, src.CATEGORY, src.SIGNAL_NAME, src.DEFAULT_SEVERITY, src.OWNER, src.ROUTE, src.NOTIFICATION_CHANNEL, 'ACCOUNT_USAGE delayed unless otherwise documented');


MERGE INTO OVERWATCH_ALERT_RULES tgt
USING (
  SELECT * FROM VALUES
    ('COST_CREDIT_SPIKE', 'Cost Control', 'Credit Spike', 'Medium', 24, 'DBA / Cost owner', 'Cost & Contract', 'Explain the bill movement, identify owner-backed drivers, and route cost-control actions.'),
    ('QUERY_HIGH_ERROR_RATE', 'Reliability', 'High Query Error Rate', 'High', 8, 'DBA / Workload Owner', 'Workload Operations', 'Group failures by error code/query text and assign the owning team.'),
    ('TASK_FAILURE', 'Reliability', 'Task Failure', 'High', 8, 'DBA / Pipeline Owner', 'Workload Operations', 'Review task graph impact, retry only after root cause, and verify the next run.'),
    ('PROCEDURE_FAILURE_OR_SPIKE', 'Reliability', 'Stored Procedure Failure / Runtime Spike', 'High', 8, 'DBA / Procedure Owner', 'Workload Operations', 'Compare release windows, inspect child queries, and verify runtime/cost return to baseline.'),
    ('WAREHOUSE_PRESSURE', 'Capacity', 'Warehouse Pressure', 'Medium', 24, 'DBA / Platform', 'Cost & Contract', 'Inspect queue/spill telemetry and route changed-only warehouse setting recommendations.'),
    ('GRANT_REVOKE_ACTIVITY', 'Change Tracking', 'Grant/Revoke Activity', 'Medium', 24, 'DBA / Security', 'Security Monitoring', 'Review least-privilege telemetry, actor, object, and review date.'),
    ('WAREHOUSE_SETTING_CHANGE', 'Change Tracking', 'Warehouse Setting Change', 'Medium', 24, 'DBA / Platform', 'Cost & Contract', 'Review changed-only SQL, rollback SQL, and post-change telemetry.'),
    ('SECURITY_PRIVILEGE_ESCALATION', 'Security', 'Privileged Role Grant', 'Critical', 4, 'Security Reviewer', 'Security Monitoring', 'Validate ticket, reviewer, MFA posture, service-account purpose, and review date before accepting privileged role expansion.'),
    ('SECURITY_SENSITIVE_EXPORT', 'Security', 'Sensitive Access Or Export', 'High', 8, 'DBA / Security', 'Security Monitoring', 'Inspect source IP, role, query_id, destination stage, object access, and masking policy coverage.'),
    ('PERF_QUERY_PRESSURE', 'Performance', 'Query Pressure', 'High', 8, 'DBA / Platform', 'Workload Operations', 'Open Query Diagnosis or Contention Center with query_id, queue/spill/lock telemetry, owner, and specific optimization path.'),
    ('PIPELINE_COPY_FAILURE', 'Task / Pipeline', 'Copy Load Failure', 'High', 8, 'DBA / Data Engineering', 'Workload Operations', 'Group by table/stage/error, fix load cause, confirm downstream task graph freshness, and document SLA recovery.'),
    ('DQ_FRESHNESS_SLA', 'Data Quality', 'Freshness SLA Missed', 'High', 8, 'Data Owner', 'Workload Operations', 'Use configured database/schema/table/column/check threshold, prove latest update/load volume, and route to data owner.'),
    ('OPT_UNUSED_OR_OVERSIZED_WAREHOUSE', 'Optimization', 'Unused Or Oversized Warehouse', 'Medium', 24, 'DBA / Cost owner', 'Cost & Contract', 'Attach metering/query telemetry, owner route, rollback SQL, and expected savings before changing warehouse settings.'),
    ('WAREHOUSE_COST_MOVEMENT', 'Cost Control', 'WAREHOUSE_COST_MOVEMENT', 'High', 8, 'DBA / Cost owner', 'Cost & Contract', 'Explain the 7d warehouse cost movement, assign the owner, and route action after telemetry review.'),
    ('CORTEX_SPEND_AND_QUOTA', 'Cost Control', 'CORTEX_SPEND_AND_QUOTA', 'Medium', 24, 'DBA / AI cost route', 'Cost & Contract', 'Review shared AI spend threshold, per-user quota, first/last usage, and access expansion before enforcing controls.'),
    ('CHANGE_COST_CORRELATION', 'Cost Control', 'CHANGE_COST_CORRELATION', 'High', 8, 'DBA / Cost owner', 'Cost & Contract', 'Compare warehouse change query_id, actor, rollback telemetry, and cost movement before tuning.')
) src(RULE_ID, CATEGORY, ALERT_TYPE, DEFAULT_SEVERITY, SLA_HOURS, OWNER, ROUTE, RUNBOOK)
ON tgt.RULE_ID = src.RULE_ID
WHEN MATCHED THEN UPDATE SET
  CATEGORY = src.CATEGORY,
  ALERT_TYPE = src.ALERT_TYPE,
  DEFAULT_SEVERITY = src.DEFAULT_SEVERITY,
  SLA_HOURS = src.SLA_HOURS,
  OWNER = src.OWNER,
  ROUTE = src.ROUTE,
  RUNBOOK = src.RUNBOOK,
  IS_ACTIVE = TRUE
WHEN NOT MATCHED THEN INSERT
  (RULE_ID, CATEGORY, ALERT_TYPE, DEFAULT_SEVERITY, SLA_HOURS, OWNER, ROUTE, RUNBOOK)
VALUES
  (src.RULE_ID, src.CATEGORY, src.ALERT_TYPE, src.DEFAULT_SEVERITY, src.SLA_HOURS, src.OWNER, src.ROUTE, src.RUNBOOK);


MERGE INTO OVERWATCH_DATA_TRUST_SOURCE tgt
USING (
  SELECT * FROM VALUES
    ('FACT_COST_DAILY', 'Cost facts', 'FACT_COST_DAILY', 'MART', 'Cost & Contract', 1440, 'allocated', 'Cost and contract metrics may be incomplete or stale.', 'DBA / Cost owner', TRUE),
    ('FACT_CORTEX_DAILY', 'Cortex facts', 'FACT_CORTEX_DAILY', 'MART', 'Cost & Contract', 1440, 'allocated', 'Cortex spend and anomaly alerts may understate AI cost exposure.', 'DBA / AI cost route', TRUE),
    ('FACT_QUERY_HOURLY', 'Query performance facts', 'FACT_QUERY_HOURLY', 'MART', 'Workload Operations', 120, 'allocated', 'Runtime, queue, spill, and warehouse pressure may be stale.', 'DBA / Workload owner', TRUE),
    ('FACT_QUERY_DETAIL_RECENT', 'Query detail facts', 'FACT_QUERY_DETAIL_RECENT', 'MART', 'Workload Operations', 120, 'exact', 'Failure/root-cause samples may be stale for drilldowns.', 'DBA / Workload owner', TRUE),
    ('FACT_TASK_RUN', 'Task run facts', 'FACT_TASK_RUN', 'MART', 'Workload Operations', 120, 'exact', 'Task failure and dependency views may miss current failures.', 'DBA / Pipeline owner', TRUE),
    ('ALERT_EVENTS', 'Alert events', 'ALERT_EVENTS', 'APP_TABLE', 'Alert Center', 60, 'exact', 'Alert Center may miss active incidents or routed ownership gaps.', 'DBA / Alert owner', TRUE),
    ('OVERWATCH_ACTION_QUEUE', 'Action queue', 'OVERWATCH_ACTION_QUEUE', 'APP_TABLE', 'DBA Control Room', 60, 'estimated', 'Owned action, closure, and savings proof may be incomplete.', 'DBA On-Call', TRUE),
    ('MART_DBA_CONTROL_ROOM', 'Control-room summary', 'MART_DBA_CONTROL_ROOM', 'MART', 'DBA Control Room', 120, 'allocated', 'Executive and DBA triage may not reflect the latest operational state.', 'DBA On-Call', TRUE),
    ('MART_EXECUTIVE_OBSERVABILITY', 'Executive observability', 'MART_EXECUTIVE_OBSERVABILITY', 'MART', 'Executive Landing', 120, 'allocated', 'Leadership first paint may be stale or incomplete.', 'DBA / Platform', TRUE),
    ('OVERWATCH_USAGE_LOG', 'App usage and query log', 'OVERWATCH_USAGE_LOG', 'APP_TABLE', 'DBA Control Room', 1440, 'fallback', 'App self-observability may have no query-tag/runtime evidence.', 'DBA / Platform', TRUE)
  AS t(SOURCE_KEY, SOURCE_NAME, SOURCE_OBJECT, SOURCE_CLASS, SURFACE, TARGET_FRESHNESS_MIN, DEFAULT_CONFIDENCE, BUSINESS_IMPACT, OWNER_ROUTE, ENABLED)
) src
ON tgt.SOURCE_KEY = src.SOURCE_KEY
WHEN MATCHED THEN UPDATE SET
  SOURCE_NAME = src.SOURCE_NAME,
  SOURCE_OBJECT = src.SOURCE_OBJECT,
  SOURCE_CLASS = src.SOURCE_CLASS,
  SURFACE = src.SURFACE,
  TARGET_FRESHNESS_MIN = src.TARGET_FRESHNESS_MIN,
  DEFAULT_CONFIDENCE = src.DEFAULT_CONFIDENCE,
  BUSINESS_IMPACT = src.BUSINESS_IMPACT,
  OWNER_ROUTE = src.OWNER_ROUTE,
  ENABLED = src.ENABLED,
  UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
  SOURCE_KEY, SOURCE_NAME, SOURCE_OBJECT, SOURCE_CLASS, SURFACE,
  TARGET_FRESHNESS_MIN, DEFAULT_CONFIDENCE, BUSINESS_IMPACT, OWNER_ROUTE, ENABLED
)
VALUES (
  src.SOURCE_KEY, src.SOURCE_NAME, src.SOURCE_OBJECT, src.SOURCE_CLASS, src.SURFACE,
  src.TARGET_FRESHNESS_MIN, src.DEFAULT_CONFIDENCE, src.BUSINESS_IMPACT, src.OWNER_ROUTE, src.ENABLED
);


MERGE INTO OVERWATCH_OPERATIONAL_OWNER_MAP tgt
USING (
  SELECT * FROM VALUES
    ('WAREHOUSE', '*', 'ALL', 'ALL', 'DBA / Cost owner', NULL, NULL, 'DBA On-Call', 'default-route', TRUE),
    ('TASK', '*', 'ALL', 'ALL', 'DBA / Pipeline owner', NULL, NULL, 'DBA On-Call', 'default-route', TRUE),
    ('PROCEDURE', '*', 'ALL', 'ALL', 'DBA / Workload owner', NULL, NULL, 'DBA On-Call', 'default-route', TRUE),
    ('USER', '*', 'ALL', 'ALL', 'IAM / Security route', NULL, NULL, 'Security On-Call', 'default-route', TRUE),
    ('ROLE', '*', 'ALL', 'ALL', 'IAM / Security route', NULL, NULL, 'Security On-Call', 'default-route', TRUE),
    ('DATABASE', '*', 'ALL', 'ALL', 'Data owner route', NULL, NULL, 'DBA On-Call', 'default-route', TRUE),
    ('SCHEMA', '*', 'ALL', 'ALL', 'Data owner route', NULL, NULL, 'DBA On-Call', 'default-route', TRUE),
    ('ALERT', '*', 'ALL', 'ALL', 'DBA / Alert owner', NULL, NULL, 'DBA On-Call', 'default-route', TRUE),
    ('ACTION', '*', 'ALL', 'ALL', 'DBA On-Call', NULL, NULL, 'DBA On-Call', 'default-route', TRUE),
    ('CORTEX', '*', 'ALL', 'ALL', 'DBA / AI cost route', NULL, NULL, 'DBA On-Call', 'default-route', TRUE)
  AS t(ENTITY_TYPE, ENTITY_PATTERN, COMPANY, ENVIRONMENT, OWNER_ROUTE, OWNER_EMAIL, ONCALL_PRIMARY, ESCALATION_TARGET, SOURCE, ACTIVE)
) src
ON UPPER(tgt.ENTITY_TYPE) = UPPER(src.ENTITY_TYPE)
AND COALESCE(tgt.ENTITY_PATTERN, '*') = COALESCE(src.ENTITY_PATTERN, '*')
AND COALESCE(tgt.COMPANY, 'ALL') = COALESCE(src.COMPANY, 'ALL')
AND COALESCE(tgt.ENVIRONMENT, 'ALL') = COALESCE(src.ENVIRONMENT, 'ALL')
WHEN MATCHED THEN UPDATE SET
  OWNER_ROUTE = src.OWNER_ROUTE,
  OWNER_EMAIL = src.OWNER_EMAIL,
  ONCALL_PRIMARY = src.ONCALL_PRIMARY,
  ESCALATION_TARGET = src.ESCALATION_TARGET,
  SOURCE = src.SOURCE,
  ACTIVE = src.ACTIVE,
  UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
  ENTITY_TYPE, ENTITY_PATTERN, COMPANY, ENVIRONMENT, OWNER_ROUTE, OWNER_EMAIL,
  ONCALL_PRIMARY, ESCALATION_TARGET, SOURCE, ACTIVE
)
VALUES (
  src.ENTITY_TYPE, src.ENTITY_PATTERN, src.COMPANY, src.ENVIRONMENT, src.OWNER_ROUTE,
  src.OWNER_EMAIL, src.ONCALL_PRIMARY, src.ESCALATION_TARGET, src.SOURCE, src.ACTIVE
);


MERGE INTO OVERWATCH_PRODUCTION_CHECKLIST tgt
USING (
  SELECT * FROM VALUES
    ('DEPLOYMENT_VERSION', 'Deployment', 'Deployment version recorded', 'Executive Landing', 'High', 'OVERWATCH_SCHEMA_MIGRATION', TRUE, FALSE, 'Ready', 'DBA / Platform', 'Confirm the latest setup migration row matches the deployed app bundle.', TRUE),
    ('VALIDATION_RUN', 'Validation', 'Production validation run recorded', 'Executive Landing', 'High', 'MART_PRODUCTION_READINESS_SUMMARY', TRUE, FALSE, 'Ready', 'DBA / Platform', 'Run OVERWATCH_MART_VALIDATION.sql after setup and after material refresh changes.', TRUE),
    ('ROLE_READINESS', 'Role Readiness', 'OVERWATCH role model reviewed', 'DBA Control Room', 'Medium', 'OVERWATCH_ROLE_READINESS_REQUIREMENT', FALSE, TRUE, 'Ready', 'Security / DBA', 'Confirm OVERWATCH_VIEWER, OVERWATCH_OPERATOR, OVERWATCH_ADMIN, and OVERWATCH_BREAKGLASS are either deployed or explicitly mapped to legacy admin roles.', TRUE),
    ('PRIVILEGE_READINESS', 'Privilege Readiness', 'Required Snowflake privileges reviewed', 'DBA Control Room', 'High', 'OVERWATCH_PRIVILEGE_READINESS_REQUIREMENT', FALSE, TRUE, 'Ready', 'Security / DBA', 'Confirm imported SNOWFLAKE privileges, warehouse usage, schema usage, table DML, view select, procedure usage, and task ownership are granted to the runtime roles.', TRUE),
    ('REFRESH_HEALTH', 'Refresh Health', 'Mart refresh jobs healthy', 'DBA Control Room', 'High', 'OVERWATCH_LOAD_AUDIT', TRUE, TRUE, 'Ready', 'DBA On-Call', 'Review failed OVERWATCH_LOAD_AUDIT rows before trusting first-paint summaries.', TRUE),
    ('SUMMARY_MART_DATA', 'Refresh Health', 'Summary mart rows available', 'Executive Landing', 'High', 'MART_*', TRUE, FALSE, 'Ready', 'DBA / Platform', 'Run the mart refresh procedures and confirm each first-paint mart has recent rows.', TRUE),
    ('DATA_FRESHNESS', 'Data Freshness', 'Data trust sources fresh', 'Executive Landing', 'High', 'MART_DATA_TRUST_SUMMARY', TRUE, FALSE, 'Ready', 'DBA / Platform', 'Refresh stale sources or disclose telemetry lag before operational action.', TRUE),
    ('CONFIG_DRIFT', 'Configuration Drift', 'Required settings customized and present', 'DBA Control Room', 'Medium', 'OVERWATCH_SETTINGS', TRUE, TRUE, 'Ready', 'DBA / Platform', 'Review placeholder alert settings and required pricing/retention settings after deployment.', TRUE),
    ('ENVIRONMENT_READINESS', 'Environment Readiness', 'Runtime context has database/schema/warehouse/role', 'Executive Landing', 'High', 'CURRENT_CONTEXT', TRUE, FALSE, 'Ready', 'DBA / Platform', 'Confirm the app runs in the intended database, schema, warehouse, and role context.', TRUE)
  AS t(CHECK_KEY, CHECK_DOMAIN, CHECK_NAME, SURFACE, SEVERITY, REQUIRED_OBJECT, FIRST_PAINT_SAFE, EXPLICIT_LOAD_REQUIRED, EXPECTED_STATE, OWNER_ROUTE, RUNBOOK_STEP, ENABLED)
) src
ON tgt.CHECK_KEY = src.CHECK_KEY
WHEN MATCHED THEN UPDATE SET
  CHECK_DOMAIN = src.CHECK_DOMAIN,
  CHECK_NAME = src.CHECK_NAME,
  SURFACE = src.SURFACE,
  SEVERITY = src.SEVERITY,
  REQUIRED_OBJECT = src.REQUIRED_OBJECT,
  FIRST_PAINT_SAFE = src.FIRST_PAINT_SAFE,
  EXPLICIT_LOAD_REQUIRED = src.EXPLICIT_LOAD_REQUIRED,
  EXPECTED_STATE = src.EXPECTED_STATE,
  OWNER_ROUTE = src.OWNER_ROUTE,
  RUNBOOK_STEP = src.RUNBOOK_STEP,
  ENABLED = src.ENABLED,
  UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
  CHECK_KEY, CHECK_DOMAIN, CHECK_NAME, SURFACE, SEVERITY, REQUIRED_OBJECT,
  FIRST_PAINT_SAFE, EXPLICIT_LOAD_REQUIRED, EXPECTED_STATE, OWNER_ROUTE, RUNBOOK_STEP, ENABLED
)
VALUES (
  src.CHECK_KEY, src.CHECK_DOMAIN, src.CHECK_NAME, src.SURFACE, src.SEVERITY,
  src.REQUIRED_OBJECT, src.FIRST_PAINT_SAFE, src.EXPLICIT_LOAD_REQUIRED,
  src.EXPECTED_STATE, src.OWNER_ROUTE, src.RUNBOOK_STEP, src.ENABLED
);


MERGE INTO OVERWATCH_ROLE_READINESS_REQUIREMENT tgt
USING (
  SELECT * FROM VALUES
    ('OVERWATCH_VIEWER', 'Target', 'Read-only monitoring and executive scorecards', TRUE, FALSE, 'SHOW ROLES LIKE ''OVERWATCH_VIEWER''; verify USAGE on app database/schema and SELECT on marts.', 'Security / DBA', TRUE),
    ('OVERWATCH_OPERATOR', 'Target', 'Operational triage, alert acknowledgement, and action queue updates', TRUE, FALSE, 'SHOW ROLES LIKE ''OVERWATCH_OPERATOR''; verify action queue DML and procedure usage.', 'Security / DBA', TRUE),
    ('OVERWATCH_ADMIN', 'Target', 'Settings, refresh controls, and guarded DBA administration', TRUE, FALSE, 'SHOW ROLES LIKE ''OVERWATCH_ADMIN''; verify warehouse/task/procedure control grants.', 'Security / DBA', TRUE),
    ('OVERWATCH_BREAKGLASS', 'Target', 'Emergency DBA intervention with explicit audit trail', FALSE, FALSE, 'SHOW ROLES LIKE ''OVERWATCH_BREAKGLASS''; verify it is disabled or tightly controlled until approved.', 'Security / DBA', TRUE),
    ('SNOW_SYSADMINS', 'Legacy Compatibility', 'Legacy admin compatibility during transition', FALSE, TRUE, 'Confirm SNOW_SYSADMINS remains intentionally mapped while OVERWATCH roles are adopted.', 'Security / DBA', TRUE),
    ('SNOW_ACCOUNTADMINS', 'Legacy Compatibility', 'Legacy account-admin compatibility during transition', FALSE, TRUE, 'Confirm SNOW_ACCOUNTADMINS remains intentionally mapped while OVERWATCH roles are adopted.', 'Security / DBA', TRUE)
  AS t(ROLE_NAME, ROLE_CLASS, REQUIRED_FOR, REQUIRED, LEGACY_COMPAT, CHECK_METHOD, OWNER_ROUTE, ENABLED)
) src
ON UPPER(tgt.ROLE_NAME) = UPPER(src.ROLE_NAME)
WHEN MATCHED THEN UPDATE SET
  ROLE_CLASS = src.ROLE_CLASS,
  REQUIRED_FOR = src.REQUIRED_FOR,
  REQUIRED = src.REQUIRED,
  LEGACY_COMPAT = src.LEGACY_COMPAT,
  CHECK_METHOD = src.CHECK_METHOD,
  OWNER_ROUTE = src.OWNER_ROUTE,
  ENABLED = src.ENABLED,
  UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
  ROLE_NAME, ROLE_CLASS, REQUIRED_FOR, REQUIRED, LEGACY_COMPAT, CHECK_METHOD, OWNER_ROUTE, ENABLED
)
VALUES (
  src.ROLE_NAME, src.ROLE_CLASS, src.REQUIRED_FOR, src.REQUIRED, src.LEGACY_COMPAT,
  src.CHECK_METHOD, src.OWNER_ROUTE, src.ENABLED
);


MERGE INTO OVERWATCH_PRIVILEGE_READINESS_REQUIREMENT tgt
USING (
  SELECT * FROM VALUES
    ('SNOWFLAKE_IMPORTED_PRIVILEGES', 'SNOWFLAKE', 'DATABASE', 'IMPORTED PRIVILEGES', 'ACCOUNT_USAGE-backed mart refreshes', TRUE, 'SHOW GRANTS ON DATABASE SNOWFLAKE;', 'Security / DBA', 'Grant imported privileges to the approved OVERWATCH runtime/admin roles after security review.', TRUE),
    ('OVERWATCH_WH_USAGE', 'OVERWATCH_WH', 'WAREHOUSE', 'USAGE', 'Scheduled mart refresh and Streamlit runtime queries', TRUE, 'SHOW GRANTS ON WAREHOUSE OVERWATCH_WH;', 'Security / DBA', 'Grant USAGE on OVERWATCH_WH to the runtime roles and keep AUTO_SUSPEND controlled.', TRUE),
    ('APP_DB_USAGE', 'DBA_MAINT_DB', 'DATABASE', 'USAGE', 'Read OVERWATCH mart objects', TRUE, 'SHOW GRANTS ON DATABASE DBA_MAINT_DB;', 'Security / DBA', 'Grant USAGE on the app database to runtime roles.', TRUE),
    ('APP_SCHEMA_USAGE', 'DBA_MAINT_DB.OVERWATCH', 'SCHEMA', 'USAGE', 'Read OVERWATCH mart schema', TRUE, 'SHOW GRANTS ON SCHEMA DBA_MAINT_DB.OVERWATCH;', 'Security / DBA', 'Grant USAGE on the app schema to runtime roles.', TRUE),
    ('APP_TABLE_SELECT', 'DBA_MAINT_DB.OVERWATCH.*', 'TABLE', 'SELECT', 'First-paint dashboards and explicit-load detail panels', TRUE, 'SHOW GRANTS TO ROLE <role_name>;', 'Security / DBA', 'Grant SELECT on all/future OVERWATCH tables to viewer/operator/admin roles.', TRUE),
    ('APP_ACTION_DML', 'OVERWATCH_ACTION_QUEUE', 'TABLE', 'INSERT, UPDATE', 'Review-gated action, value, and alert workflow updates', TRUE, 'SHOW GRANTS ON TABLE OVERWATCH_ACTION_QUEUE;', 'Security / DBA', 'Grant DML only to operator/admin roles that own review workflows.', TRUE),
    ('APP_PROCEDURE_USAGE', 'SP_OVERWATCH_*', 'PROCEDURE', 'USAGE', 'Manual and scheduled mart refresh procedures', TRUE, 'SHOW PROCEDURES LIKE ''SP_OVERWATCH_%''; SHOW GRANTS TO ROLE <role_name>;', 'Security / DBA', 'Grant procedure usage to approved refresh/admin roles only.', TRUE),
    ('APP_TASK_OPERATE', 'OVERWATCH_*', 'TASK', 'OPERATE/OWNERSHIP', 'Scheduled mart health and recovery', TRUE, 'SHOW TASKS IN SCHEMA; SHOW GRANTS TO ROLE <role_name>;', 'Security / DBA', 'Keep task ownership with the DBA/admin role; do not grant broad task control to viewers.', TRUE)
  AS t(PRIVILEGE_KEY, OBJECT_NAME, OBJECT_TYPE, REQUIRED_PRIVILEGE, REQUIRED_FOR, REQUIRED, CHECK_METHOD, OWNER_ROUTE, REMEDIATION_HINT, ENABLED)
) src
ON tgt.PRIVILEGE_KEY = src.PRIVILEGE_KEY
WHEN MATCHED THEN UPDATE SET
  OBJECT_NAME = src.OBJECT_NAME,
  OBJECT_TYPE = src.OBJECT_TYPE,
  REQUIRED_PRIVILEGE = src.REQUIRED_PRIVILEGE,
  REQUIRED_FOR = src.REQUIRED_FOR,
  REQUIRED = src.REQUIRED,
  CHECK_METHOD = src.CHECK_METHOD,
  OWNER_ROUTE = src.OWNER_ROUTE,
  REMEDIATION_HINT = src.REMEDIATION_HINT,
  ENABLED = src.ENABLED,
  UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
  PRIVILEGE_KEY, OBJECT_NAME, OBJECT_TYPE, REQUIRED_PRIVILEGE, REQUIRED_FOR,
  REQUIRED, CHECK_METHOD, OWNER_ROUTE, REMEDIATION_HINT, ENABLED
)
VALUES (
  src.PRIVILEGE_KEY, src.OBJECT_NAME, src.OBJECT_TYPE, src.REQUIRED_PRIVILEGE,
  src.REQUIRED_FOR, src.REQUIRED, src.CHECK_METHOD, src.OWNER_ROUTE,
  src.REMEDIATION_HINT, src.ENABLED
);


MERGE INTO OVERWATCH_EXECUTIVE_SCORECARD_CONFIG tgt
USING (
  SELECT * FROM VALUES
    ('SNOWFLAKE_HEALTH', 'Snowflake Health Score', 10, 'Platform Health', 70, 85, 'DBA / Platform', 'MART_DBA_CONTROL_ROOM; MART_APP_OBSERVABILITY_SUMMARY; MART_PRODUCTION_READINESS_SUMMARY', 'Open DBA Control Room and resolve failed refresh, app health, or control-room blocker rows.', TRUE),
    ('COST_EFFICIENCY', 'Cost Efficiency Score', 20, 'Cost', 70, 85, 'DBA / Cost owner', 'FACT_COST_MONITORING_SIGNAL; ALERT_EVENTS; MART_EXECUTIVE_VALUE_LEDGER', 'Open Cost & Contract, explain top cost drivers, and route verified savings work.', TRUE),
    ('SECURITY', 'Security Score', 30, 'Security', 75, 88, 'Security / DBA', 'ALERT_EVENTS; MART_OPERATIONAL_OWNER_COVERAGE', 'Open Security Monitoring and review privileged, access, ownership, and route-gap drivers.', TRUE),
    ('OPERATIONAL_RISK', 'Operational Risk Score', 40, 'Operations', 70, 85, 'DBA On-Call', 'ALERT_EVENTS; MART_OPERATIONAL_OWNER_COVERAGE; OVERWATCH_ACTION_QUEUE', 'Open Alert Center and DBA Control Room to assign owner, SLA, and next action.', TRUE),
    ('DATA_TRUST', 'Data Trust Score', 50, 'Data Trust', 75, 90, 'DBA / Platform', 'MART_DATA_TRUST_SUMMARY', 'Open DBA Control Room data trust diagnostics and refresh stale source marts.', TRUE),
    ('PRODUCTION_READINESS', 'Production Readiness Score', 60, 'Production Readiness', 75, 90, 'DBA / Platform', 'MART_PRODUCTION_READINESS_SUMMARY; OVERWATCH_PRODUCTION_VALIDATION_STATUS', 'Open DBA Control Room production readiness validation before expanding usage.', TRUE)
  AS t(SCORE_KEY, SCORE_NAME, DISPLAY_ORDER, SCORE_DOMAIN, RED_BELOW, YELLOW_BELOW, OWNER_ROUTE, DRIVER_SOURCE, RECOMMENDED_ACTION, ENABLED)
) src
ON tgt.SCORE_KEY = src.SCORE_KEY
WHEN MATCHED THEN UPDATE SET
  SCORE_NAME = src.SCORE_NAME,
  DISPLAY_ORDER = src.DISPLAY_ORDER,
  SCORE_DOMAIN = src.SCORE_DOMAIN,
  RED_BELOW = src.RED_BELOW,
  YELLOW_BELOW = src.YELLOW_BELOW,
  OWNER_ROUTE = src.OWNER_ROUTE,
  DRIVER_SOURCE = src.DRIVER_SOURCE,
  RECOMMENDED_ACTION = src.RECOMMENDED_ACTION,
  ENABLED = src.ENABLED,
  UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
  SCORE_KEY, SCORE_NAME, DISPLAY_ORDER, SCORE_DOMAIN, RED_BELOW, YELLOW_BELOW,
  OWNER_ROUTE, DRIVER_SOURCE, RECOMMENDED_ACTION, ENABLED
)
VALUES (
  src.SCORE_KEY, src.SCORE_NAME, src.DISPLAY_ORDER, src.SCORE_DOMAIN,
  src.RED_BELOW, src.YELLOW_BELOW, src.OWNER_ROUTE, src.DRIVER_SOURCE,
  src.RECOMMENDED_ACTION, src.ENABLED
);


MERGE INTO OVERWATCH_FORECAST_CONFIG tgt
USING (
  SELECT * FROM VALUES
    ('EOM_SPEND', 'End-of-month Snowflake spend forecast', 10, 'Cost', 'USD', 'DBA / Cost owner', 'FACT_COST_DAILY; FACT_CORTEX_DAILY', 'Month-to-date observed spend plus average observed daily spend projected through month end.', 'Open Cost & Contract, explain the top spend drivers, and route owner-backed cost actions.', 'High >= 14 observed days, Medium >= 7 observed days, otherwise Low.', TRUE),
    ('EOQ_SPEND', 'End-of-quarter spend forecast', 20, 'Cost', 'USD', 'DBA / Cost owner', 'FACT_COST_DAILY; FACT_CORTEX_DAILY', 'Quarter-to-date observed spend plus average observed daily spend projected through quarter end.', 'Review quarter run-rate, contract exposure, and cost action queue before the next operating review.', 'High >= 30 observed quarter days, Medium >= 14 observed quarter days, otherwise Low.', TRUE),
    ('CONTRACT_BURN', 'Contract burn projection', 30, 'Cost', 'percent', 'DBA / Contract owner', 'FACT_COST_DAILY; FACT_CORTEX_DAILY; OVERWATCH_SETTINGS', 'Projected quarter spend divided by configured contract or budget target.', 'Set or validate contract targets, then route spend above target to Cost & Contract ownership.', 'Low when no contract target is configured; otherwise follows quarter spend confidence.', TRUE),
    ('CREDIT_ANOMALY', 'Credit anomaly projection', 40, 'Cost', 'percent', 'DBA / Cost owner', 'FACT_COST_DAILY; FACT_CORTEX_DAILY', 'Recent seven-day credit burn compared with the 30-day daily credit baseline.', 'Investigate warehouses, users, or Cortex demand causing recent credit burn to diverge from baseline.', 'High >= 21 observed baseline days, Medium >= 10 baseline days, otherwise Low.', TRUE),
    ('STORAGE_GROWTH', 'Storage growth forecast', 50, 'Storage', 'TB', 'DBA / Data owner', 'FACT_STORAGE_DAILY', 'Latest storage footprint plus recent daily storage growth projected 30 days forward.', 'Review database/storage owners, retention, stage cleanup, and archive policy for rising storage.', 'High >= 21 days of storage trend, Medium >= 7 days, otherwise Low.', TRUE),
    ('WAREHOUSE_PRESSURE', 'Warehouse saturation / queue pressure forecast', 60, 'Workload', 'seconds', 'DBA / Workload owner', 'FACT_QUERY_HOURLY', 'Last seven days of queue pressure adjusted by movement versus the prior seven days.', 'Open Workload Operations and review warehouse sizing, queue, spill, and concurrency drivers.', 'High >= 500 recent queries, Medium >= 100 recent queries, otherwise Low.', TRUE),
    ('SLA_RISK', 'SLA risk forecast', 70, 'Operations', 'count', 'DBA On-Call', 'FACT_TASK_RUN; FACT_PROCEDURE_RUN', 'Recent task and procedure failures projected into the next seven-day operating window.', 'Open Workload Operations and assign owners for late, failed, or retrying task/procedure chains.', 'High >= 10 recent incidents, Medium >= 3 recent incidents, otherwise Low.', TRUE)
  AS t(
    FORECAST_KEY, FORECAST_NAME, DISPLAY_ORDER, FORECAST_DOMAIN, VALUE_UNIT,
    OWNER_ROUTE, SOURCE_OBJECTS, METHODOLOGY, RECOMMENDED_ACTION,
    CONFIDENCE_RULE, ENABLED
  )
) src
ON tgt.FORECAST_KEY = src.FORECAST_KEY
WHEN MATCHED THEN UPDATE SET
  FORECAST_NAME = src.FORECAST_NAME,
  DISPLAY_ORDER = src.DISPLAY_ORDER,
  FORECAST_DOMAIN = src.FORECAST_DOMAIN,
  VALUE_UNIT = src.VALUE_UNIT,
  OWNER_ROUTE = src.OWNER_ROUTE,
  SOURCE_OBJECTS = src.SOURCE_OBJECTS,
  METHODOLOGY = src.METHODOLOGY,
  RECOMMENDED_ACTION = src.RECOMMENDED_ACTION,
  CONFIDENCE_RULE = src.CONFIDENCE_RULE,
  ENABLED = src.ENABLED,
  UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
  FORECAST_KEY, FORECAST_NAME, DISPLAY_ORDER, FORECAST_DOMAIN, VALUE_UNIT,
  OWNER_ROUTE, SOURCE_OBJECTS, METHODOLOGY, RECOMMENDED_ACTION,
  CONFIDENCE_RULE, ENABLED
)
VALUES (
  src.FORECAST_KEY, src.FORECAST_NAME, src.DISPLAY_ORDER, src.FORECAST_DOMAIN,
  src.VALUE_UNIT, src.OWNER_ROUTE, src.SOURCE_OBJECTS, src.METHODOLOGY,
  src.RECOMMENDED_ACTION, src.CONFIDENCE_RULE, src.ENABLED
);


MERGE INTO OVERWATCH_CHANGE_RULE tgt
USING (
  SELECT * FROM VALUES
    ('WAREHOUSE_CHANGE', 'Warehouse changes', 'WAREHOUSE', 'Medium', 'Warehouse setting changes can alter cost, queueing, auto-suspend, timeout, and workload behavior.', 'DBA / Cost owner', 'allocated', 'FACT_OBJECT_CHANGE; FACT_COST_MONITORING_SIGNAL; ALERT_EVENTS', 'WAREHOUSE keywords in object-change telemetry', TRUE),
    ('ROLE_CHANGE', 'Role changes', 'ROLE', 'High', 'Role changes can alter access boundaries and incident blast radius.', 'IAM / Security route', 'allocated', 'FACT_OBJECT_CHANGE; FACT_GRANT_DAILY; ALERT_EVENTS', 'ROLE keywords or role grants', TRUE),
    ('GRANT_CHANGE', 'Grant changes', 'GRANT', 'High', 'Grant changes can introduce privilege drift, access exceptions, or audit findings.', 'IAM / Security route', 'allocated', 'FACT_GRANT_DAILY; FACT_OBJECT_CHANGE; ALERT_EVENTS', 'GRANT or REVOKE telemetry', TRUE),
    ('TASK_CHANGE', 'Task changes', 'TASK', 'Medium', 'Task changes can affect pipeline freshness, downstream SLA, and orchestration reliability.', 'DBA / Pipeline owner', 'estimated', 'FACT_OBJECT_CHANGE; DIM_TASK_SNAPSHOT; FACT_TASK_RUN; ALERT_EVENTS', 'TASK keywords or task snapshots', TRUE),
    ('PROCEDURE_CHANGE', 'Procedure changes', 'PROCEDURE', 'Medium', 'Procedure changes can alter workload behavior, stored procedure cost, and downstream task outcomes.', 'DBA / Workload owner', 'estimated', 'FACT_OBJECT_CHANGE; DIM_PROCEDURE_SNAPSHOT; FACT_PROCEDURE_RUN; ALERT_EVENTS', 'PROCEDURE keywords or procedure snapshots', TRUE),
    ('NETWORK_POLICY_CHANGE', 'Network policy changes', 'NETWORK POLICY', 'High', 'Network policy changes can affect access controls and connectivity posture.', 'Security / DBA', 'allocated', 'FACT_OBJECT_CHANGE; ALERT_EVENTS', 'NETWORK POLICY keywords', TRUE),
    ('INTEGRATION_CHANGE', 'Integration changes', 'INTEGRATION', 'High', 'Integration changes can affect external access, storage integration, notification, or data movement paths.', 'Security / Platform', 'allocated', 'FACT_OBJECT_CHANGE; ALERT_EVENTS', 'INTEGRATION keywords', TRUE),
    ('OBJECT_CHANGE', 'Database/schema/object changes', 'OBJECT', 'Medium', 'Object changes can break dependent workloads, alter data contracts, or explain incident timing.', 'Data owner route', 'allocated', 'FACT_OBJECT_CHANGE; ALERT_EVENTS', 'DATABASE, SCHEMA, TABLE, VIEW, or object DDL keywords', TRUE),
    ('SECURITY_SENSITIVE_CHANGE', 'Security-sensitive changes', 'SECURITY', 'Critical', 'Security-sensitive changes require audit review because they may alter privileged access or exposure.', 'Security / DBA', 'allocated', 'FACT_OBJECT_CHANGE; FACT_GRANT_DAILY; ALERT_EVENTS', 'SECURITY, POLICY, INTEGRATION, OWNERSHIP, ADMIN, or privileged grant keywords', TRUE)
  AS t(CHANGE_TYPE, CHANGE_CATEGORY, OBJECT_TYPE, RISK_LEVEL, BUSINESS_IMPACT, OWNER_ROUTE, CONFIDENCE, SOURCE_OBJECTS, MATCH_HINT, ENABLED)
) src
ON tgt.CHANGE_TYPE = src.CHANGE_TYPE
WHEN MATCHED THEN UPDATE SET
  CHANGE_CATEGORY = src.CHANGE_CATEGORY,
  OBJECT_TYPE = src.OBJECT_TYPE,
  RISK_LEVEL = src.RISK_LEVEL,
  BUSINESS_IMPACT = src.BUSINESS_IMPACT,
  OWNER_ROUTE = src.OWNER_ROUTE,
  CONFIDENCE = src.CONFIDENCE,
  SOURCE_OBJECTS = src.SOURCE_OBJECTS,
  MATCH_HINT = src.MATCH_HINT,
  ENABLED = src.ENABLED,
  UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
  CHANGE_TYPE, CHANGE_CATEGORY, OBJECT_TYPE, RISK_LEVEL, BUSINESS_IMPACT,
  OWNER_ROUTE, CONFIDENCE, SOURCE_OBJECTS, MATCH_HINT, ENABLED
)
VALUES (
  src.CHANGE_TYPE, src.CHANGE_CATEGORY, src.OBJECT_TYPE, src.RISK_LEVEL,
  src.BUSINESS_IMPACT, src.OWNER_ROUTE, src.CONFIDENCE, src.SOURCE_OBJECTS,
  src.MATCH_HINT, src.ENABLED
);


MERGE INTO OVERWATCH_COMMAND_CENTER_QUESTION tgt
USING (
  SELECT * FROM VALUES
    ('COST_SPIKE', 'Cost Spike', 'Why did costs spike?', 10, 'MART_EXECUTIVE_OBSERVABILITY; MART_EXECUTIVE_FORECAST_SUMMARY; MART_EXECUTIVE_VALUE_LEDGER; OVERWATCH_ACTION_WORKFLOW', 'DBA / Cost owner', 'High', 'allocated', 'Open Cost & Contract, confirm the spend driver, route an owner-backed savings action, and verify value after the change.', TRUE),
    ('WAREHOUSE_SLOW', 'Warehouse Slow', 'Why is this warehouse slow?', 20, 'MART_EXECUTIVE_OBSERVABILITY; MART_EXECUTIVE_FORECAST_SUMMARY; OVERWATCH_ACTION_WORKFLOW', 'DBA / Workload owner', 'High', 'allocated', 'Open Workload Operations, review queue/spill/pressure evidence, and create a review-gated action plan.', TRUE),
    ('RECENT_CHANGE', 'Recent Change', 'What changed recently?', 30, 'MART_CHANGE_INTELLIGENCE_SUMMARY; OVERWATCH_CHANGE_CORRELATION', 'DBA / Platform', 'Medium', 'estimated', 'Review recent high-risk changes and treat timing/entity matches as possible correlation until proven.', TRUE),
    ('FAILURE_SLA', 'Failure / SLA', 'Why did this fail?', 40, 'ALERT_EVENTS; MART_EXECUTIVE_OBSERVABILITY; OVERWATCH_ACTION_WORKFLOW', 'DBA On-Call', 'High', 'allocated', 'Open Alert Center and Workload Operations, assign the owner, capture evidence, and verify recovery.', TRUE),
    ('SECURITY_RISK', 'Security Risk', 'What security risk needs action?', 50, 'ALERT_EVENTS; MART_OPERATIONAL_OWNER_COVERAGE; MART_EXECUTIVE_SCORECARD_SUMMARY; MART_CHANGE_INTELLIGENCE_SUMMARY', 'Security / DBA', 'High', 'allocated', 'Open Security Monitoring, validate ownership gaps, and route approval-gated access actions.', TRUE),
    ('EXECUTIVE_RISK', 'Executive Risk', 'What should leadership worry about?', 60, 'MART_EXECUTIVE_SCORECARD_SUMMARY; MART_PRODUCTION_READINESS_SUMMARY; MART_DATA_TRUST_SUMMARY; MART_CLOSED_LOOP_OPERATIONS_SUMMARY', 'DBA / Platform', 'Medium', 'estimated', 'Use the scorecard, readiness, trust, and action lifecycle evidence to decide the next operating move.', TRUE)
  AS t(QUESTION_KEY, INVESTIGATION_TYPE, QUESTION_TEXT, DISPLAY_ORDER, SOURCE_OBJECTS, DEFAULT_OWNER_ROUTE, DEFAULT_RISK_LEVEL, DEFAULT_CONFIDENCE, DEFAULT_ACTION, ENABLED)
) src
ON tgt.QUESTION_KEY = src.QUESTION_KEY
WHEN MATCHED THEN UPDATE SET
  INVESTIGATION_TYPE = src.INVESTIGATION_TYPE,
  QUESTION_TEXT = src.QUESTION_TEXT,
  DISPLAY_ORDER = src.DISPLAY_ORDER,
  SOURCE_OBJECTS = src.SOURCE_OBJECTS,
  DEFAULT_OWNER_ROUTE = src.DEFAULT_OWNER_ROUTE,
  DEFAULT_RISK_LEVEL = src.DEFAULT_RISK_LEVEL,
  DEFAULT_CONFIDENCE = src.DEFAULT_CONFIDENCE,
  DEFAULT_ACTION = src.DEFAULT_ACTION,
  ENABLED = src.ENABLED,
  UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
  QUESTION_KEY, INVESTIGATION_TYPE, QUESTION_TEXT, DISPLAY_ORDER, SOURCE_OBJECTS,
  DEFAULT_OWNER_ROUTE, DEFAULT_RISK_LEVEL, DEFAULT_CONFIDENCE, DEFAULT_ACTION, ENABLED
)
VALUES (
  src.QUESTION_KEY, src.INVESTIGATION_TYPE, src.QUESTION_TEXT, src.DISPLAY_ORDER,
  src.SOURCE_OBJECTS, src.DEFAULT_OWNER_ROUTE, src.DEFAULT_RISK_LEVEL,
  src.DEFAULT_CONFIDENCE, src.DEFAULT_ACTION, src.ENABLED
);


-- -----------------------------------------------------------------------------
-- 7. Smoke checks
-- -----------------------------------------------------------------------------

SHOW TASKS LIKE 'OVERWATCH_%' IN SCHEMA DBA_MAINT_DB.OVERWATCH;


SELECT 'FACT_WAREHOUSE_HOURLY' AS TABLE_NAME, COUNT(*) AS ROWS_LOADED FROM FACT_WAREHOUSE_HOURLY
UNION ALL
SELECT 'FACT_QUERY_HOURLY', COUNT(*) FROM FACT_QUERY_HOURLY
UNION ALL
SELECT 'FACT_QUERY_DETAIL_RECENT', COUNT(*) FROM FACT_QUERY_DETAIL_RECENT
UNION ALL
SELECT 'DIM_TABLE_SNAPSHOT', COUNT(*) FROM DIM_TABLE_SNAPSHOT
UNION ALL
SELECT 'FACT_COPY_LOAD_DAILY', COUNT(*) FROM FACT_COPY_LOAD_DAILY
UNION ALL
SELECT 'FACT_COST_DAILY', COUNT(*) FROM FACT_COST_DAILY
UNION ALL
SELECT 'FACT_COST_SOURCE_HEALTH_DAILY', COUNT(*) FROM FACT_COST_SOURCE_HEALTH_DAILY
UNION ALL
SELECT 'FACT_COST_MONITORING_SIGNAL', COUNT(*) FROM FACT_COST_MONITORING_SIGNAL
UNION ALL
SELECT 'FACT_COST_INCIDENT_TIMELINE', COUNT(*) FROM FACT_COST_INCIDENT_TIMELINE
UNION ALL
SELECT 'MART_EXECUTIVE_OBSERVABILITY', COUNT(*) FROM MART_EXECUTIVE_OBSERVABILITY
UNION ALL
SELECT 'MART_DBA_CONTROL_ROOM', COUNT(*) FROM MART_DBA_CONTROL_ROOM
UNION ALL
SELECT 'MART_DATA_TRUST_SUMMARY', COUNT(*) FROM MART_DATA_TRUST_SUMMARY
UNION ALL
SELECT 'MART_OPERATIONAL_OWNER_COVERAGE', COUNT(*) FROM MART_OPERATIONAL_OWNER_COVERAGE
UNION ALL
SELECT 'MART_EXECUTIVE_VALUE_LEDGER', COUNT(*) FROM MART_EXECUTIVE_VALUE_LEDGER
UNION ALL
SELECT 'MART_APP_OBSERVABILITY_SUMMARY', COUNT(*) FROM MART_APP_OBSERVABILITY_SUMMARY
UNION ALL
SELECT 'MART_PRODUCTION_READINESS_SUMMARY', COUNT(*) FROM MART_PRODUCTION_READINESS_SUMMARY
UNION ALL
SELECT 'MART_EXECUTIVE_SCORECARD_SUMMARY', COUNT(*) FROM MART_EXECUTIVE_SCORECARD_SUMMARY
UNION ALL
SELECT 'MART_EXECUTIVE_FORECAST_SUMMARY', COUNT(*) FROM MART_EXECUTIVE_FORECAST_SUMMARY
UNION ALL
SELECT 'MART_CHANGE_INTELLIGENCE_SUMMARY', COUNT(*) FROM MART_CHANGE_INTELLIGENCE_SUMMARY
UNION ALL
SELECT 'MART_CLOSED_LOOP_OPERATIONS_SUMMARY', COUNT(*) FROM MART_CLOSED_LOOP_OPERATIONS_SUMMARY
UNION ALL
SELECT 'MART_COMMAND_CENTER_SUMMARY', COUNT(*) FROM MART_COMMAND_CENTER_SUMMARY;





CALL SP_OVERWATCH_LOAD_HOURLY();

CALL SP_OVERWATCH_LOAD_CORTEX();

CALL SP_OVERWATCH_REFRESH_CONTROL_ROOM();

CALL SP_OVERWATCH_REFRESH_COST_MONITORING();

CALL SP_OVERWATCH_LOAD_DAILY();

CALL SP_OVERWATCH_REFRESH_EXECUTIVE_OBSERVABILITY();

CALL SP_OVERWATCH_REFRESH_ENTERPRISE_OPERATING_MODEL();

CALL SP_OVERWATCH_REFRESH_PRODUCTION_READINESS();

CALL SP_OVERWATCH_REFRESH_EXECUTIVE_SCORECARD();

CALL SP_OVERWATCH_REFRESH_FORECASTING();

CALL SP_OVERWATCH_REFRESH_CHANGE_INTELLIGENCE();

CALL SP_OVERWATCH_REFRESH_CLOSED_LOOP_OPERATIONS();

CALL SP_OVERWATCH_REFRESH_COMMAND_CENTER();
