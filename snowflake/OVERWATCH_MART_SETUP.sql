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
--   - permanent audit/action tables for evidence
--   - hourly refresh, offset from the top of the hour for ACCOUNT_USAGE latency

-- -----------------------------------------------------------------------------
-- 1. Runtime objects
-- -----------------------------------------------------------------------------

CREATE DATABASE IF NOT EXISTS DBA_MAINT_DB;
CREATE SCHEMA IF NOT EXISTS DBA_MAINT_DB.OVERWATCH;

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

USE DATABASE DBA_MAINT_DB;
USE SCHEMA OVERWATCH;

-- -----------------------------------------------------------------------------
-- 2. Configuration and audit tables
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS OVERWATCH_SETTINGS (
  SETTING_NAME        VARCHAR(200) PRIMARY KEY,
  SETTING_VALUE       VARCHAR(4000),
  SETTING_TYPE        VARCHAR(50),
  DESCRIPTION         VARCHAR(1000),
  UPDATED_AT          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_BY          VARCHAR(200) DEFAULT CURRENT_USER()
);

MERGE INTO OVERWATCH_SETTINGS tgt
USING (
  SELECT * FROM VALUES
    ('CREDIT_PRICE_USD', '3.68', 'NUMBER', 'Contract credit price used for estimated cost display.'),
    ('AI_CREDIT_PRICE_USD', '2.20', 'NUMBER', 'Cortex AI/token credit price used for estimated AI cost display.'),
    ('MART_QUERY_RETENTION_DAYS', '35', 'NUMBER', 'Rolling window reloaded from ACCOUNT_USAGE query history.'),
    ('DETAIL_RETENTION_DAYS', '30', 'NUMBER', 'Retention for recent query/task/procedure detail marts.'),
    ('AGG_RETENTION_DAYS', '730', 'NUMBER', 'Retention for hourly and daily aggregate marts.'),
    ('SLA_DURATION_MULTIPLIER', '1.5', 'NUMBER', 'Flags task/procedure latest duration over this multiple of historical average.'),
    ('DEFAULT_ALERT_EMAIL', 'dba-alerts@yourcompany.com', 'STRING', 'Default email recipient list for OVERWATCH alert messages until Teams/webhook delivery is configured.'),
    ('ALERT_DELIVERY_METHOD', 'EMAIL', 'STRING', 'Alert delivery channel used by the OVERWATCH anomaly task.'),
    ('ALERT_EMAIL_NOTIFICATION_INTEGRATION', 'OVERWATCH_EMAIL_INT', 'STRING', 'Approved Snowflake notification integration name for optional Alert Center email delivery.')
) src(SETTING_NAME, SETTING_VALUE, SETTING_TYPE, DESCRIPTION)
ON tgt.SETTING_NAME = src.SETTING_NAME
WHEN MATCHED THEN UPDATE SET
  SETTING_VALUE = CASE
    WHEN src.SETTING_NAME = 'DEFAULT_ALERT_EMAIL' THEN src.SETTING_VALUE
    ELSE tgt.SETTING_VALUE
  END,
  SETTING_TYPE = src.SETTING_TYPE,
  DESCRIPTION = src.DESCRIPTION
WHEN NOT MATCHED THEN INSERT (SETTING_NAME, SETTING_VALUE, SETTING_TYPE, DESCRIPTION)
VALUES (src.SETTING_NAME, src.SETTING_VALUE, src.SETTING_TYPE, src.DESCRIPTION);

CREATE TABLE IF NOT EXISTS OVERWATCH_SCHEMA_MIGRATION (
  MIGRATION_VERSION   VARCHAR(100) NOT NULL,
  MIGRATION_NAME      VARCHAR(300) NOT NULL,
  APPLIED_AT          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  APPLIED_BY          VARCHAR(200) DEFAULT CURRENT_USER(),
  SOURCE_FILE         VARCHAR(500),
  NOTES               VARCHAR(1000)
);

MERGE INTO OVERWATCH_SCHEMA_MIGRATION tgt
USING (
  SELECT
    '2026.06.04-cost-proof-mart' AS MIGRATION_VERSION,
    'Cost proof mart, procedure context, evidence feed health, alert automation, and migration ledger' AS MIGRATION_NAME,
    'snowflake/OVERWATCH_MART_SETUP.sql' AS SOURCE_FILE,
    'Baseline setup ledger row for the app release, including cost proof marts, procedure database/schema context, and Terraform/Jira evidence feed ingress.' AS NOTES
) src
ON tgt.MIGRATION_VERSION = src.MIGRATION_VERSION
WHEN MATCHED THEN UPDATE SET
  MIGRATION_NAME = src.MIGRATION_NAME,
  SOURCE_FILE = src.SOURCE_FILE,
  NOTES = src.NOTES
WHEN NOT MATCHED THEN INSERT (MIGRATION_VERSION, MIGRATION_NAME, SOURCE_FILE, NOTES)
VALUES (src.MIGRATION_VERSION, src.MIGRATION_NAME, src.SOURCE_FILE, src.NOTES);

CREATE TABLE IF NOT EXISTS OVERWATCH_COMPANY_SCOPE (
  COMPANY              VARCHAR(100) NOT NULL,
  SCOPE_TYPE           VARCHAR(100) NOT NULL,
  SCOPE_PATTERN        VARCHAR(500) NOT NULL,
  MATCH_MODE           VARCHAR(20) DEFAULT 'ILIKE', -- ILIKE, NOT_ILIKE, EQUALS
  ENVIRONMENT          VARCHAR(50),
  IS_ACTIVE            BOOLEAN DEFAULT TRUE,
  NOTES                VARCHAR(1000),
  CREATED_AT           TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  CREATED_BY           VARCHAR(200) DEFAULT CURRENT_USER()
);

MERGE INTO OVERWATCH_COMPANY_SCOPE tgt
USING (
  SELECT * FROM VALUES
    ('ALFA',   'WAREHOUSE', 'WH_TRXS_%',             'NOT_ILIKE', NULL, 'Exclude Trexis warehouses from ALFA.'),
    ('ALFA',   'DATABASE',  'TRXS_%',                'NOT_ILIKE', NULL, 'Exclude Trexis databases from ALFA.'),
    ('ALFA',   'DATABASE',  'ALFA%',                 'ILIKE',     NULL, 'ALFA database naming convention.'),
    ('ALFA',   'DATABASE',  'ADMIN',                 'ILIKE',     NULL, 'Shared admin database used by ALFA DBAs.'),
    ('ALFA',   'DATABASE',  'ALFA_EDW_PROD',         'EQUALS',    'PROD', 'ALFA PROD EDW database.'),
    ('ALFA',   'DATABASE',  'ALFA_EDW_MGM',          'EQUALS',    'PROD', 'ALFA PRE-PROD EDW database.'),
    ('ALFA',   'DATABASE',  'ALFA_EDW_DEV',          'EQUALS',    'ALFA_EDW_DEV', 'ALFA DEV EDW database.'),
    ('ALFA',   'DATABASE',  'ALFA_EDW_SAN',          'EQUALS',    'ALFA_EDW_SAN', 'ALFA SAN EDW database.'),
    ('ALFA',   'DATABASE',  'ALFA_EDW_PHX',          'EQUALS',    'ALFA_EDW_PHX', 'ALFA PHX EDW database.'),
    ('ALFA',   'DATABASE',  'ALFA_EDW_SEA',          'EQUALS',    'ALFA_EDW_SEA', 'ALFA SEA EDW database.'),
    ('ALFA',   'DATABASE',  'ALFA_EDW_SIT',          'EQUALS',    'ALFA_EDW_SIT', 'ALFA SIT EDW database.'),
    ('Trexis', 'WAREHOUSE', 'WH_TRXS_%',             'ILIKE',     NULL, 'Trexis warehouses.'),
    ('Trexis', 'DATABASE',  'TRXS_%',                'ILIKE',     NULL, 'Trexis databases.')
) src(COMPANY, SCOPE_TYPE, SCOPE_PATTERN, MATCH_MODE, ENVIRONMENT, NOTES)
ON tgt.COMPANY = src.COMPANY
AND tgt.SCOPE_TYPE = src.SCOPE_TYPE
AND tgt.SCOPE_PATTERN = src.SCOPE_PATTERN
AND tgt.MATCH_MODE = src.MATCH_MODE
WHEN NOT MATCHED THEN INSERT (COMPANY, SCOPE_TYPE, SCOPE_PATTERN, MATCH_MODE, ENVIRONMENT, NOTES)
VALUES (src.COMPANY, src.SCOPE_TYPE, src.SCOPE_PATTERN, src.MATCH_MODE, src.ENVIRONMENT, src.NOTES);

CREATE TABLE IF NOT EXISTS OVERWATCH_OWNER_TAG_NAMES (
  TAG_NAME             VARCHAR(300) PRIMARY KEY,
  OWNER_TYPE           VARCHAR(100),
  PRIORITY             NUMBER,
  IS_ACTIVE            BOOLEAN DEFAULT TRUE,
  NOTES                VARCHAR(1000),
  UPDATED_AT           TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_BY           VARCHAR(200) DEFAULT CURRENT_USER()
);

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

CREATE TABLE IF NOT EXISTS OVERWATCH_OWNER_DIRECTORY (
  OWNER_KEY         VARCHAR(200) PRIMARY KEY,
  ENTITY_TYPE       VARCHAR(100),
  ENTITY_PATTERN    VARCHAR(500),
  OWNER_NAME        VARCHAR(200),
  OWNER_EMAIL       VARCHAR(500),
  ONCALL_PRIMARY    VARCHAR(200),
  ONCALL_SECONDARY  VARCHAR(200),
  APPROVAL_GROUP    VARCHAR(200),
  ESCALATION_TARGET VARCHAR(200),
  DEFAULT_ROUTE     VARCHAR(200),
  SERVICE_TIER      VARCHAR(50),
  MATCH_PRIORITY    NUMBER DEFAULT 0,
  IS_ACTIVE         BOOLEAN DEFAULT TRUE,
  UPDATED_AT        TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_BY        VARCHAR(200) DEFAULT CURRENT_USER(),
  NOTES             VARCHAR(2000)
);

MERGE INTO OVERWATCH_OWNER_DIRECTORY tgt
USING (
  SELECT * FROM VALUES
    ('COST_CONTROL_DEFAULT', 'COST_CONTROL', '*', 'DBA / FinOps', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'FinOps Backup', 'FinOps Lead / Cost Owner', 'FinOps Lead', 'Cost & Contract', 'Tier 1', 80, 'Default route for bill movement, chargeback, savings verification, and cost-control actions.'),
    ('COST_VERIFIER_TASK', 'TASK', '*OVERWATCH_COST_SAVINGS_VERIFY*', 'DBA / FinOps', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'FinOps Backup', 'FinOps Lead', 'FinOps Lead', 'Cost & Contract', 'Tier 0', 200, 'Owner route for the scheduled savings-verification task.'),
    ('TASK_DEFAULT', 'TASK', '*', 'DBA / Pipeline Owner', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'Pipeline Owner Backup', 'Pipeline Owner', 'DBA Lead', 'Workload Operations', 'Tier 0', 70, 'Default route for failed or late task graph recovery.'),
    ('PROCEDURE_DEFAULT', 'PROCEDURE', '*', 'DBA / Procedure Owner', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'Procedure Owner Backup', 'Procedure Owner', 'DBA Lead', 'Workload Operations', 'Tier 1', 70, 'Default route for stored procedure runtime, orchestration, and cost regressions.'),
    ('WAREHOUSE_DEFAULT', 'WAREHOUSE', '*', 'DBA / Platform', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'Platform DBA Backup', 'Platform DBA Lead', 'DBA Lead', 'Warehouse Health', 'Tier 1', 60, 'Default route for warehouse pressure, capacity, and setting-change controls.'),
    ('OVERWATCH_WH_EXECUTION', 'WAREHOUSE', 'OVERWATCH_WH', 'OVERWATCH Platform Owner', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'Platform DBA Backup', 'DBA Lead / OVERWATCH Platform Owner', 'DBA Lead', 'Architecture Readiness', 'Tier 1', 215, 'Dedicated OVERWATCH Streamlit app execution warehouse; monitor separately from business workload warehouses.'),
    ('COMPUTE_WH_EXECUTION', 'WAREHOUSE', 'COMPUTE_WH', 'OVERWATCH Platform Owner', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'Platform DBA Backup', 'DBA Lead / OVERWATCH Platform Owner', 'DBA Lead', 'Architecture Readiness', 'Tier 1', 205, 'Legacy OVERWATCH mart task and utility warehouse; monitor separately from business workload warehouses.'),
    ('ADAPTIVE_COMPUTE_DEFAULT', 'ADAPTIVE_COMPUTE', '*', 'DBA / Platform Architecture', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'FinOps Backup', 'DBA Lead / FinOps Lead', 'DBA Lead', 'Architecture Readiness', 'Tier 1', 158, 'Default route for Adaptive Compute candidate review, pilot approval, cost baseline, and rollback proof.'),
    ('ALFA_EDW_PROD_DATABASE', 'DATABASE', 'ALFA_EDW_PROD', 'ALFA EDW Data Owner', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'Data Platform Backup', 'DBA Lead / ALFA EDW Data Owner', 'DBA Lead', 'Architecture Readiness', 'Tier 0', 220, 'Owner route for PROD EDW isolation, clustering, cache, and DR architecture decisions.'),
    ('ALFA_EDW_DEV_DATABASES', 'DATABASE', 'ALFA_EDW_%', 'ALFA Development Data Owner', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'Development Platform Backup', 'DBA Lead / Development Platform Owner', 'DBA Lead', 'Architecture Readiness', 'Tier 2', 120, 'Fallback route for ALFA DEV/Sandbox EDW database architecture decisions.'),
    ('ARCHITECTURE_DEFAULT', 'ARCHITECTURE', '*', 'DBA / Platform Architecture', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'Platform DBA Backup', 'DBA Lead', 'DBA Lead', 'Architecture Readiness', 'Tier 1', 65, 'Fallback route for architecture objective, workload isolation, clustering, cache, and DR findings.'),
    ('AI_AGENT_DEFAULT', 'AI_AGENT', '*', 'DBA / AI Governance', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'Security Backup', 'DBA Lead / Security Approver', 'Security Lead', 'Architecture Readiness', 'Tier 0', 160, 'Default route for Cortex Agent inventory, Snowflake Intelligence usage, MCP tool exposure, and AI governance actions.'),
    ('MCP_SERVER_DEFAULT', 'MCP_SERVER', '*', 'DBA / AI Governance', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'Security Backup', 'DBA Lead / Security Approver', 'Security Lead', 'Architecture Readiness', 'Tier 0', 170, 'Default route for MCP server owner, tool-scope, role-scope, and blast-radius review.'),
    ('CORTEX_SENSE_DEFAULT', 'CORTEX_SENSE', '*', 'DBA / AI Governance', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'Data Governance Backup', 'DBA Lead / Data Governance Lead', 'Data Governance Lead', 'Architecture Readiness', 'Tier 0', 168, 'Default route for Cortex Sense shared context, business definitions, semantic source, connector, citation, and regression-test governance.'),
    ('COWORK_ARTIFACT_DEFAULT', 'COWORK_ARTIFACT', '*', 'DBA / Analytics Governance', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'Analytics Owner Backup', 'Analytics Owner / DBA Lead', 'Analytics Owner', 'Architecture Readiness', 'Tier 1', 166, 'Default route for CoWork Artifact publisher, certified source, sharing scope, freshness, sensitivity, and retirement governance.'),
    ('AI_COST_DEFAULT', 'AI_USAGE', '*', 'DBA / FinOps', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'FinOps Backup', 'FinOps Lead / DBA Lead', 'FinOps Lead', 'Cost & Contract', 'Tier 1', 155, 'Default route for AI token-credit spend, Snowflake Intelligence usage, and Cortex Agent cost guardrails.'),
    ('AI_SECURITY_DEFAULT', 'AI_SECURITY', '*', 'DBA / AI Governance', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'Security Backup', 'DBA Lead / Security Approver', 'Security Lead', 'Architecture Readiness', 'Tier 0', 156, 'Default route for Cortex AI Guardrails, PUBLIC AI access, per-function privileges, and sensitive-data report readiness.'),
    ('OPENFLOW_DEFAULT', 'OPENFLOW', '*', 'DBA / Integration Platform', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'Data Engineering Backup', 'Data Engineering Lead / DBA Lead', 'Data Engineering Lead', 'Architecture Readiness', 'Tier 1', 150, 'Default route for Openflow runtime, data-plane, auth, cost, and recovery evidence.'),
    ('HORIZON_GOVERNANCE_DEFAULT', 'GOVERNANCE_VIEW', '*', 'DBA / Data Governance', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'Security Backup', 'Data Governance Lead / Security Approver', 'Data Governance Lead', 'Security Posture', 'Tier 0', 145, 'Default route for Horizon catalog, classification, policy, lineage, access-history, and governance-readiness gaps.'),
    ('SEMANTIC_TRUST_DEFAULT', 'SEMANTIC_TRUST', '*', 'DBA / Analytics Governance', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'Analytics Owner Backup', 'Analytics Owner / DBA Lead', 'Analytics Owner', 'Architecture Readiness', 'Tier 1', 140, 'Default route for semantic model ownership, certification, verified query tests, and AI answer trust.'),
    ('BCDR_DRILL_DEFAULT', 'BCDR_DRILL', '*', 'DBA / Platform Architecture', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'Infrastructure Backup', 'DBA Lead / Infrastructure Owner', 'Infrastructure Owner', 'Architecture Readiness', 'Tier 0', 135, 'Default route for DR drill ledger, recovery proof, RPO/RTO validation, and failover/replication evidence.'),
    ('AI_CHANGE_GOVERNANCE_DEFAULT', 'AI_CHANGE_GOVERNANCE', '*', 'DBA Change Owner', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'Change Advisory Backup', 'Change Advisory / DBA Lead', 'DBA Lead / Change Advisory', 'Change & Drift', 'Tier 0', 130, 'Default route for Cortex Code, AISQL, and AI-assisted admin change governance.'),
    ('SECURITY_DEFAULT', 'SECURITY', '*', 'DBA / Security', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'Security Backup', 'Security Approver', 'Security Lead', 'Security Posture', 'Tier 0', 60, 'Default route for grant, revoke, role, and rights controls.'),
    ('ALERT_DEFAULT', 'ALERT', '*', 'DBA', 'dba-alerts@yourcompany.com', 'DBA On-Call', 'DBA Backup', 'DBA Lead', 'DBA Lead', 'Alert Center', 'Tier 1', 10, 'Fallback route for alerts without a more specific owner.')
) src(OWNER_KEY, ENTITY_TYPE, ENTITY_PATTERN, OWNER_NAME, OWNER_EMAIL, ONCALL_PRIMARY,
      ONCALL_SECONDARY, APPROVAL_GROUP, ESCALATION_TARGET, DEFAULT_ROUTE, SERVICE_TIER,
      MATCH_PRIORITY, NOTES)
ON UPPER(tgt.OWNER_KEY) = UPPER(src.OWNER_KEY)
WHEN MATCHED THEN UPDATE SET
  ENTITY_TYPE = src.ENTITY_TYPE,
  ENTITY_PATTERN = src.ENTITY_PATTERN,
  OWNER_NAME = src.OWNER_NAME,
  OWNER_EMAIL = src.OWNER_EMAIL,
  ONCALL_PRIMARY = src.ONCALL_PRIMARY,
  ONCALL_SECONDARY = src.ONCALL_SECONDARY,
  APPROVAL_GROUP = src.APPROVAL_GROUP,
  ESCALATION_TARGET = src.ESCALATION_TARGET,
  DEFAULT_ROUTE = src.DEFAULT_ROUTE,
  SERVICE_TIER = src.SERVICE_TIER,
  MATCH_PRIORITY = src.MATCH_PRIORITY,
  IS_ACTIVE = TRUE,
  NOTES = src.NOTES
WHEN NOT MATCHED THEN INSERT
  (OWNER_KEY, ENTITY_TYPE, ENTITY_PATTERN, OWNER_NAME, OWNER_EMAIL, ONCALL_PRIMARY,
   ONCALL_SECONDARY, APPROVAL_GROUP, ESCALATION_TARGET, DEFAULT_ROUTE, SERVICE_TIER,
   MATCH_PRIORITY, NOTES)
VALUES
  (src.OWNER_KEY, src.ENTITY_TYPE, src.ENTITY_PATTERN, src.OWNER_NAME, src.OWNER_EMAIL,
   src.ONCALL_PRIMARY, src.ONCALL_SECONDARY, src.APPROVAL_GROUP, src.ESCALATION_TARGET,
   src.DEFAULT_ROUTE, src.SERVICE_TIER, src.MATCH_PRIORITY, src.NOTES);

CREATE OR REPLACE VIEW OVERWATCH_OWNER_DIRECTORY_ACTIVE_V AS
SELECT
  OWNER_KEY,
  UPPER(COALESCE(ENTITY_TYPE, 'GLOBAL')) AS ENTITY_TYPE,
  COALESCE(ENTITY_PATTERN, '*') AS ENTITY_PATTERN,
  OWNER_NAME,
  OWNER_EMAIL,
  ONCALL_PRIMARY,
  ONCALL_SECONDARY,
  APPROVAL_GROUP,
  ESCALATION_TARGET,
  DEFAULT_ROUTE,
  SERVICE_TIER,
  COALESCE(MATCH_PRIORITY, 0) AS MATCH_PRIORITY,
  NOTES,
  UPDATED_AT,
  UPDATED_BY
FROM OVERWATCH_OWNER_DIRECTORY
WHERE COALESCE(IS_ACTIVE, TRUE);

CREATE OR REPLACE FUNCTION OVERWATCH_DATABASE_ENVIRONMENT(DATABASE_NAME VARCHAR)
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
  CASE
    WHEN UPPER(DATABASE_NAME) = 'ALFA_EDW_PROD' THEN 'PROD'
    WHEN UPPER(DATABASE_NAME) = 'ALFA_EDW_MGM' THEN 'PROD'
    WHEN UPPER(DATABASE_NAME) = 'ALFA_EDW_DEV' THEN 'ALFA_EDW_DEV'
    WHEN UPPER(DATABASE_NAME) = 'ALFA_EDW_SAN' THEN 'ALFA_EDW_SAN'
    WHEN UPPER(DATABASE_NAME) = 'ALFA_EDW_PHX' THEN 'ALFA_EDW_PHX'
    WHEN UPPER(DATABASE_NAME) = 'ALFA_EDW_SEA' THEN 'ALFA_EDW_SEA'
    WHEN UPPER(DATABASE_NAME) = 'ALFA_EDW_SIT' THEN 'ALFA_EDW_SIT'
    WHEN DATABASE_NAME ILIKE 'ALFA_EDW_%' THEN 'Other ALFA Non-Prod'
    WHEN DATABASE_NAME IS NULL THEN 'No Database Context'
    ELSE 'Other / Shared'
  END
$$;

CREATE TABLE IF NOT EXISTS OVERWATCH_LOAD_AUDIT (
  LOAD_ID              NUMBER AUTOINCREMENT PRIMARY KEY,
  LOAD_NAME            VARCHAR(200),
  LOAD_STARTED_AT      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  LOAD_FINISHED_AT     TIMESTAMP_NTZ,
  STATUS               VARCHAR(40),
  ROWS_LOADED          NUMBER,
  MESSAGE              VARCHAR(4000)
);

CREATE TABLE IF NOT EXISTS OVERWATCH_ADMIN_ACTION_AUDIT (
  ACTION_ID            NUMBER AUTOINCREMENT PRIMARY KEY,
  ACTION_TS            TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  COMPANY              VARCHAR(100),
  ENVIRONMENT          VARCHAR(50),
  APP_USER             VARCHAR(200),
  SNOWFLAKE_USER       VARCHAR(200),
  SNOWFLAKE_ROLE       VARCHAR(200),
  ACTION_TYPE          VARCHAR(100),
  TARGET_OBJECT        VARCHAR(1000),
  SQL_TEXT             VARCHAR,
  SQL_HASH             VARCHAR(80),
  CONFIRMATION_TEXT    VARCHAR(1000),
  CONTROL_CONTEXT      VARCHAR(4000),
  RESULT_STATUS        VARCHAR(40),
  RESULT_MESSAGE       VARCHAR(4000)
);

CREATE TABLE IF NOT EXISTS OVERWATCH_USAGE_LOG (
  RUN_ID               NUMBER AUTOINCREMENT PRIMARY KEY,
  LOG_TIME             TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  SF_USER              VARCHAR(200),
  SF_ROLE              VARCHAR(200),
  COMPANY_VIEW         VARCHAR(100),
  SECTION              VARCHAR(200),
  QUERY_DURATION_MS    NUMBER,
  APP_VERSION          VARCHAR(20) DEFAULT '3.0',
  SESSION_ID           VARCHAR(200),
  EVENT_TYPE           VARCHAR(50) DEFAULT 'SECTION_LOAD',
  QUERY_HASH           VARCHAR(80),
  CACHE_KEY            VARCHAR(300),
  CACHE_TIER           VARCHAR(50),
  ROW_COUNT            NUMBER,
  RESULT_MB            NUMBER(18,4),
  USED_CACHE           BOOLEAN,
  MESSAGE              VARCHAR(1000)
);

CREATE TABLE IF NOT EXISTS OVERWATCH_ACTION_QUEUE (
  ACTION_ID                 VARCHAR(64) PRIMARY KEY,
  CREATED_AT                TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_AT                TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  SOURCE                    VARCHAR(100),
  CATEGORY                  VARCHAR(100),
  SEVERITY                  VARCHAR(20),
  ENTITY_TYPE               VARCHAR(100),
  ENTITY_NAME               VARCHAR(500),
  OWNER                     VARCHAR(200),
  STATUS                    VARCHAR(40) DEFAULT 'New',
  FINDING                   VARCHAR(4000),
  RECOMMENDED_ACTION        VARCHAR(4000),
  EST_MONTHLY_SAVINGS       FLOAT,
  GENERATED_SQL_FIX         VARCHAR(8000),
  PROOF_QUERY               VARCHAR(8000),
  COMPANY                   VARCHAR(100),
  ENVIRONMENT               VARCHAR(100),
  TICKET_ID                 VARCHAR(200),
  APPROVER                  VARCHAR(200),
  DUE_DATE                  DATE,
  VERIFICATION_STATUS       VARCHAR(40) DEFAULT 'Pending',
  VERIFICATION_NOTES        VARCHAR(4000),
  VERIFICATION_QUERY        VARCHAR(8000),
  VERIFICATION_RESULT       VARCHAR(8000),
  BASELINE_VALUE            FLOAT,
  CURRENT_VALUE             FLOAT,
  MEASURED_DELTA            FLOAT,
  VERIFIED_BY               VARCHAR(200),
  VERIFIED_AT               TIMESTAMP_NTZ,
  OWNER_APPROVAL_STATUS      VARCHAR(40),
  OWNER_APPROVAL_BY          VARCHAR(200),
  OWNER_APPROVAL_AT          TIMESTAMP_NTZ,
  OWNER_APPROVAL_NOTE        VARCHAR(2000),
  RECOVERY_SLA_STATE         VARCHAR(100),
  RECOVERY_SLA_HOURS         FLOAT,
  RECOVERY_SLA_TARGET_HOURS  FLOAT,
  RECOVERY_EVIDENCE          VARCHAR(8000),
  OWNER_EMAIL                VARCHAR(500),
  ONCALL_PRIMARY             VARCHAR(200),
  ONCALL_SECONDARY           VARCHAR(200),
  APPROVAL_GROUP             VARCHAR(200),
  ESCALATION_TARGET          VARCHAR(200),
  OWNER_SOURCE               VARCHAR(200),
  OWNER_EVIDENCE             VARCHAR(2000),
  RECOVERY_AUDIT_STATE       VARCHAR(100),
  ACKNOWLEDGED_BY           VARCHAR(200),
  ACKNOWLEDGED_AT           TIMESTAMP_NTZ,
  FIXED_BY                  VARCHAR(200),
  FIXED_AT                  TIMESTAMP_NTZ,
  IGNORED_REASON            VARCHAR(2000),
  LAST_SEEN_AT              TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  SEEN_COUNT                NUMBER DEFAULT 1
);

-- Upgrade older action queue installs to the current owner/environment and
-- verification contract without rebuilding existing evidence.
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS TICKET_ID VARCHAR(200);
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS APPROVER VARCHAR(200);
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS DUE_DATE DATE;
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS VERIFICATION_STATUS VARCHAR(40);
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS VERIFICATION_NOTES VARCHAR(4000);
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS VERIFICATION_QUERY VARCHAR(8000);
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS VERIFICATION_RESULT VARCHAR(8000);
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS BASELINE_VALUE FLOAT;
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS CURRENT_VALUE FLOAT;
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS MEASURED_DELTA FLOAT;
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS VERIFIED_BY VARCHAR(200);
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS VERIFIED_AT TIMESTAMP_NTZ;
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS OWNER_APPROVAL_STATUS VARCHAR(40);
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS OWNER_APPROVAL_BY VARCHAR(200);
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS OWNER_APPROVAL_AT TIMESTAMP_NTZ;
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS OWNER_APPROVAL_NOTE VARCHAR(2000);
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS RECOVERY_SLA_STATE VARCHAR(100);
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS RECOVERY_SLA_HOURS FLOAT;
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS RECOVERY_SLA_TARGET_HOURS FLOAT;
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS RECOVERY_EVIDENCE VARCHAR(8000);
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS OWNER_EMAIL VARCHAR(500);
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS ONCALL_PRIMARY VARCHAR(200);
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS ONCALL_SECONDARY VARCHAR(200);
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS APPROVAL_GROUP VARCHAR(200);
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS ESCALATION_TARGET VARCHAR(200);
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS OWNER_SOURCE VARCHAR(200);
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS OWNER_EVIDENCE VARCHAR(2000);
ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS RECOVERY_AUDIT_STATE VARCHAR(100);


CREATE TABLE IF NOT EXISTS OVERWATCH_WORKLOAD_RECOVERY_AUDIT (
  RECOVERY_AUDIT_ID         NUMBER AUTOINCREMENT PRIMARY KEY,
  RECOVERY_AUDIT_TS         TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  ACTION_ID                 VARCHAR(64),
  COMPANY                   VARCHAR(100),
  ENVIRONMENT               VARCHAR(100),
  ENTITY_TYPE               VARCHAR(100),
  ENTITY_NAME               VARCHAR(500),
  INCIDENT_TYPE             VARCHAR(200),
  INCIDENT_PRIORITY         VARCHAR(100),
  OWNER                     VARCHAR(200),
  OWNER_EMAIL               VARCHAR(500),
  ONCALL_PRIMARY            VARCHAR(200),
  APPROVAL_GROUP            VARCHAR(200),
  APPROVER                  VARCHAR(200),
  OWNER_APPROVAL_STATUS     VARCHAR(40),
  RECOVERY_SLA_STATE        VARCHAR(100),
  RECOVERY_SLA_HOURS        FLOAT,
  RECOVERY_SLA_TARGET_HOURS FLOAT,
  TICKET_ID                 VARCHAR(200),
  ACTION_TAKEN              VARCHAR(4000),
  BEFORE_STATE              VARCHAR(4000),
  AFTER_STATE               VARCHAR(4000),
  VERIFICATION_QUERY        VARCHAR(8000),
  VERIFICATION_RESULT       VARCHAR(8000),
  RECOVERY_EVIDENCE         VARCHAR(8000),
  EXECUTED_BY               VARCHAR(200) DEFAULT CURRENT_USER(),
  SOURCE                    VARCHAR(200),
  SOURCE_QUERY_ID           VARCHAR(200),
  NOTES                     VARCHAR(4000)
);

CREATE OR REPLACE VIEW OVERWATCH_WORKLOAD_RECOVERY_AUDIT_LATEST_V AS
SELECT *
FROM OVERWATCH_WORKLOAD_RECOVERY_AUDIT
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY COALESCE(ACTION_ID, ENTITY_NAME), ENTITY_TYPE
  ORDER BY RECOVERY_AUDIT_TS DESC, RECOVERY_AUDIT_ID DESC
) = 1;

CREATE TABLE IF NOT EXISTS OVERWATCH_PLATFORM_FUTURES_CONTROL_REGISTER (
  CONTROL_ID          VARCHAR(200) PRIMARY KEY,
  CONTROL_AREA        VARCHAR(200),
  OWNER               VARCHAR(200),
  OWNER_KEY           VARCHAR(200),
  APPROVAL_GROUP      VARCHAR(200),
  PRIMARY_EVIDENCE    VARCHAR(1000),
  SOURCE_OBJECTS      VARCHAR(1000),
  RISK_IF_MISSING     VARCHAR(2000),
  DBA_DECISION        VARCHAR(2000),
  AUTOMATION_BOUNDARY VARCHAR(2000),
  MATCH_PRIORITY      NUMBER DEFAULT 0,
  IS_ACTIVE           BOOLEAN DEFAULT TRUE,
  UPDATED_AT          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_BY          VARCHAR(200) DEFAULT CURRENT_USER()
);

MERGE INTO OVERWATCH_PLATFORM_FUTURES_CONTROL_REGISTER tgt
USING (
  SELECT * FROM VALUES
    ('ADAPTIVE_COMPUTE_READINESS', 'Adaptive Compute Readiness', 'DBA / Platform Architecture', 'ADAPTIVE_COMPUTE_DEFAULT', 'DBA Lead / FinOps Lead', 'SHOW WAREHOUSES; SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY; WAREHOUSE_METERING_HISTORY', 'Standard warehouse transition candidates', 'Warehouse conversion decisions can be made without workload pressure, cost baseline, owner approval, or rollback evidence.', 'Require owner-approved pilot, preview-limitation screen, before/after p95/queue/spill/cost proof, and rollback path before conversion.', 'Advisor only. Do not create, convert, or drop adaptive warehouses from dashboard automation.', 245),
    ('AI_AGENT_MCP_GOVERNANCE', 'Agent & MCP Governance', 'DBA / AI Governance', 'AI_AGENT_DEFAULT', 'DBA Lead / Security Approver', 'SHOW AGENTS IN ACCOUNT; SHOW MCP SERVERS IN ACCOUNT', 'Cortex Agents, MCP Servers', 'Agents or MCP tool endpoints can be created without owner, tool-scope review, or blast-radius evidence.', 'Require owner, approved tool purpose, role scope, semantic source, and rollback plan before production use.', 'Inventory and queue only. Do not alter or drop agents/MCP servers from dashboard automation.', 240),
    ('CORTEX_SENSE_CONTEXT_GOVERNANCE', 'Cortex Sense Context Governance', 'DBA / AI Governance', 'CORTEX_SENSE_DEFAULT', 'DBA Lead / Data Governance Lead', 'Cortex Sense context inventory when available; SEMANTIC_VIEWS; SEMANTIC_TABLES; SEMANTIC_METRICS; MCP server inventory; policy/access history', 'Cortex Sense shared context, business definitions, semantic sources, MCP connectors, agent skills', 'Agents can appear trustworthy while using stale definitions, unowned semantic sources, or unapproved connector/tool context.', 'Require context owner, semantic source certification, connector/tool approval, data classification proof, citation policy, and regression test set before production adoption.', 'Readiness and queue only. Do not publish or mutate Cortex Sense context, skills, semantic models, or MCP connectors from dashboard automation.', 238),
    ('COWORK_ARTIFACT_GOVERNANCE', 'CoWork Artifact Governance', 'DBA / Analytics Governance', 'COWORK_ARTIFACT_DEFAULT', 'Analytics Owner / DBA Lead', 'CoWork Artifact inventory when available; Snowflake Intelligence usage; semantic view ownership; dashboard/share/access policy evidence', 'CoWork Artifacts, publishable dashboards, saved/shared AI outputs, governed live-data views', 'Knowledge workers can create shared dashboards or artifacts that look official while bypassing certified metrics, data owner approval, or access-review evidence.', 'Require owner, certified data source, semantic test set, sensitivity classification, sharing scope, freshness SLA, and retirement plan before publishing artifacts broadly.', 'Inventory, readiness, and queue only. Do not publish, share, delete, or alter CoWork Artifacts from dashboard automation.', 236),
    ('AI_SPEND_TOKEN_GUARDRAILS', 'AI Spend & Token Guardrails', 'DBA / FinOps', 'AI_COST_DEFAULT', 'FinOps Lead / DBA Lead', 'SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY; SNOWFLAKE_INTELLIGENCE_USAGE_HISTORY', 'Cortex Agent usage, Snowflake Intelligence usage', 'AI usage can create token-credit spend with weak user, role, interface, or owner accountability.', 'Route high-credit, external-interface, or privileged-role usage to owners with Snowflake budget, quota, and custom-action review.', 'Generate budget and quota deployment SQL, alert, and queue only. Do not auto-revoke AI access or change budget limits without approval.', 230),
    ('AI_SECURITY_GUARDRAILS', 'AI Security Guardrails', 'DBA / AI Governance', 'AI_SECURITY_DEFAULT', 'DBA Lead / Security Approver', 'AI_SETTINGS; CORTEX_ENABLED_CROSS_REGION; SHOW GRANTS TO ROLE PUBLIC; SNOWFLAKE.DATA_SECURITY reports', 'Cortex AI Guardrails, AI function privileges, sensitive-data entitlement/access reports', 'AI workloads can run without prompt-injection guardrails, granular function privileges, or proof of who can access sensitive data.', 'Require account-level AI guardrails, narrow per-function grants, no PUBLIC blanket AI access, and sensitive-data report visibility before production AI expansion.', 'Readiness and queue only. Do not change account parameters or revoke/grant AI privileges from dashboard automation.', 225),
    ('OPENFLOW_OPERABILITY', 'Openflow Operations', 'DBA / Integration Platform', 'OPENFLOW_DEFAULT', 'Data Engineering Lead / DBA Lead', 'SNOWFLAKE.ACCOUNT_USAGE.OPENFLOW_USAGE_HISTORY', 'Openflow data planes and runtimes', 'Managed ingestion runtimes can consume credits or move sensitive data without DBA operating evidence.', 'Track runtime credits, data-plane type, owner, secret/auth posture, and recovery playbook before expanding.', 'Observe and queue. Do not stop runtimes or deployments from the dashboard.', 220),
    ('HORIZON_GOVERNANCE_READINESS', 'Horizon Governance Readiness', 'DBA / Data Governance', 'HORIZON_GOVERNANCE_DEFAULT', 'Data Governance Lead / Security Approver', 'DATA_CLASSIFICATION_LATEST, POLICY_REFERENCES, ACCESS_HISTORY, OBJECT_DEPENDENCIES', 'Classification, policies, lineage, access history', 'The account may not be ready to prove classification, policy coverage, lineage, and access behavior across engines.', 'Make governance observability visible before adopting broader Horizon, Marketplace, or cross-engine access patterns.', 'Readiness only. Do not change policies or tags automatically.', 210),
    ('SEMANTIC_TRUST_VALIDATION', 'Semantic Trust & Verified Query Testing', 'DBA / Analytics Governance', 'SEMANTIC_TRUST_DEFAULT', 'Analytics Owner / DBA Lead', 'SEMANTIC_VIEWS, SEMANTIC_TABLES, SEMANTIC_METRICS', 'Semantic model metadata', 'Agent or analyst answers can look authoritative while using unowned or untested semantic definitions.', 'Require owner, certified model, test query set, freshness proof, and regression checks before trusted use.', 'Validate and queue only. Do not rewrite semantic models automatically.', 200),
    ('BCDR_DRILL_LEDGER', 'BCDR Drill Ledger', 'DBA / Platform Architecture', 'BCDR_DRILL_DEFAULT', 'DBA Lead / Infrastructure Owner', 'SHOW FAILOVER GROUPS; SHOW REPLICATION GROUPS; REPLICATION_GROUP_USAGE_HISTORY; BACKUP_OPERATION_HISTORY', 'Failover groups, replication groups, backup operation history', 'DR can be configured but unproven, with no RPO/RTO drill record or recovery owner.', 'Keep a drill ledger with protected scope, target account, last success, failure notes, and next drill date.', 'Never execute failover from dashboard automation.', 190),
    ('AI_CHANGE_GOVERNANCE', 'AI Change Governance', 'DBA Change Owner', 'AI_CHANGE_GOVERNANCE_DEFAULT', 'Change Advisory / DBA Lead', 'CORTEX_CODE_CLI_USAGE_HISTORY; CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY; CORTEX_AISQL_USAGE_HISTORY', 'Cortex Code, Cortex AISQL, AI-assisted SQL', 'AI-assisted code or SQL can bypass source-control, approval, and deployment evidence.', 'Treat AI-generated DDL/SQL like any other change: ticket, source, reviewer, rollout, rollback, and verification.', 'Observe usage and route to Change & Drift. Do not execute generated changes automatically.', 180)
) src(CONTROL_ID, CONTROL_AREA, OWNER, OWNER_KEY, APPROVAL_GROUP, PRIMARY_EVIDENCE,
      SOURCE_OBJECTS, RISK_IF_MISSING, DBA_DECISION, AUTOMATION_BOUNDARY, MATCH_PRIORITY)
ON UPPER(tgt.CONTROL_ID) = UPPER(src.CONTROL_ID)
WHEN MATCHED THEN UPDATE SET
  CONTROL_AREA = src.CONTROL_AREA,
  OWNER = src.OWNER,
  OWNER_KEY = src.OWNER_KEY,
  APPROVAL_GROUP = src.APPROVAL_GROUP,
  PRIMARY_EVIDENCE = src.PRIMARY_EVIDENCE,
  SOURCE_OBJECTS = src.SOURCE_OBJECTS,
  RISK_IF_MISSING = src.RISK_IF_MISSING,
  DBA_DECISION = src.DBA_DECISION,
  AUTOMATION_BOUNDARY = src.AUTOMATION_BOUNDARY,
  MATCH_PRIORITY = src.MATCH_PRIORITY,
  IS_ACTIVE = TRUE,
  UPDATED_AT = CURRENT_TIMESTAMP(),
  UPDATED_BY = CURRENT_USER()
WHEN NOT MATCHED THEN INSERT
  (CONTROL_ID, CONTROL_AREA, OWNER, OWNER_KEY, APPROVAL_GROUP, PRIMARY_EVIDENCE,
   SOURCE_OBJECTS, RISK_IF_MISSING, DBA_DECISION, AUTOMATION_BOUNDARY, MATCH_PRIORITY)
VALUES
  (src.CONTROL_ID, src.CONTROL_AREA, src.OWNER, src.OWNER_KEY, src.APPROVAL_GROUP,
   src.PRIMARY_EVIDENCE, src.SOURCE_OBJECTS, src.RISK_IF_MISSING, src.DBA_DECISION,
   src.AUTOMATION_BOUNDARY, src.MATCH_PRIORITY);

CREATE TABLE IF NOT EXISTS OVERWATCH_PLATFORM_FUTURES_EVIDENCE (
  EVIDENCE_ID          NUMBER AUTOINCREMENT PRIMARY KEY,
  CAPTURED_AT          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  CONTROL_ID           VARCHAR(200),
  CONTROL_AREA         VARCHAR(200),
  EVIDENCE_SURFACE     VARCHAR(200),
  SOURCE_TYPE          VARCHAR(200),
  ENTITY_TYPE          VARCHAR(200),
  ENTITY_NAME          VARCHAR(500),
  COMPANY              VARCHAR(100),
  ENVIRONMENT          VARCHAR(100),
  SEVERITY             VARCHAR(40),
  FINDING              VARCHAR(4000),
  DBA_ACTION           VARCHAR(4000),
  OWNER                VARCHAR(200),
  OWNER_EMAIL          VARCHAR(500),
  APPROVAL_GROUP       VARCHAR(200),
  APPROVAL_STATUS      VARCHAR(100),
  TICKET_ID            VARCHAR(200),
  SOURCE_OBJECTS       VARCHAR(1000),
  SOURCE_FRESHNESS     VARCHAR(200),
  EVIDENCE_CONFIDENCE  VARCHAR(200),
  VERIFICATION_QUERY   VARCHAR(8000),
  VERIFICATION_RESULT  VARCHAR(8000),
  AUTOMATION_BOUNDARY  VARCHAR(2000),
  ACTION_ID            VARCHAR(64),
  SOURCE_QUERY_ID      VARCHAR(200),
  RAW_EVIDENCE         VARIANT,
  CAPTURED_BY          VARCHAR(200) DEFAULT CURRENT_USER(),
  NOTES                VARCHAR(4000)
);

CREATE OR REPLACE VIEW OVERWATCH_PLATFORM_FUTURES_EVIDENCE_LATEST_V AS
SELECT *
FROM OVERWATCH_PLATFORM_FUTURES_EVIDENCE
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY COALESCE(CONTROL_ID, CONTROL_AREA), COALESCE(ENTITY_NAME, EVIDENCE_SURFACE), COALESCE(EVIDENCE_SURFACE, SOURCE_TYPE)
  ORDER BY CAPTURED_AT DESC, EVIDENCE_ID DESC
) = 1;

CREATE OR REPLACE VIEW OVERWATCH_PLATFORM_FUTURES_CONTROL_COVERAGE_V AS
SELECT
  r.CONTROL_ID,
  r.CONTROL_AREA,
  r.OWNER,
  r.OWNER_KEY,
  r.APPROVAL_GROUP,
  r.PRIMARY_EVIDENCE,
  r.SOURCE_OBJECTS,
  r.RISK_IF_MISSING,
  r.DBA_DECISION,
  r.AUTOMATION_BOUNDARY,
  r.MATCH_PRIORITY,
  e.CAPTURED_AT AS LAST_EVIDENCE_AT,
  e.EVIDENCE_SURFACE,
  e.SOURCE_TYPE,
  e.ENTITY_NAME,
  e.SEVERITY,
  e.FINDING,
  e.APPROVAL_STATUS,
  e.TICKET_ID,
  e.VERIFICATION_RESULT,
  CASE
    WHEN e.EVIDENCE_ID IS NULL THEN 'Evidence Not Captured'
    WHEN UPPER(COALESCE(e.SEVERITY, '')) IN ('CRITICAL', 'HIGH')
     AND UPPER(COALESCE(e.APPROVAL_STATUS, '')) NOT IN ('APPROVED', 'NOT REQUIRED', 'VERIFIED')
      THEN 'Action Open'
    WHEN UPPER(COALESCE(e.VERIFICATION_RESULT, '')) = '' THEN 'Proof Needed'
    ELSE 'Evidence Captured'
  END AS COVERAGE_STATE
FROM OVERWATCH_PLATFORM_FUTURES_CONTROL_REGISTER r
LEFT JOIN OVERWATCH_PLATFORM_FUTURES_EVIDENCE_LATEST_V e
  ON UPPER(COALESCE(e.CONTROL_ID, e.CONTROL_AREA)) IN (UPPER(r.CONTROL_ID), UPPER(r.CONTROL_AREA))
WHERE COALESCE(r.IS_ACTIVE, TRUE);

CREATE TABLE IF NOT EXISTS OVERWATCH_COST_SAVINGS_VERIFICATION_RUN (
  RUN_ID                    NUMBER AUTOINCREMENT PRIMARY KEY,
  RUN_TS                    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  ACTION_ID                 VARCHAR(64),
  COMPANY                   VARCHAR(100),
  ENVIRONMENT               VARCHAR(100),
  CATEGORY                  VARCHAR(100),
  ENTITY_TYPE               VARCHAR(100),
  ENTITY_NAME               VARCHAR(500),
  OWNER                     VARCHAR(200),
  OWNER_APPROVAL_STATUS     VARCHAR(40),
  STATUS_BEFORE             VARCHAR(40),
  BASELINE_VALUE            FLOAT,
  DETECTION_CURRENT_VALUE   FLOAT,
  POST_PERIOD_VALUE         FLOAT,
  MEASURED_DELTA            FLOAT,
  EST_MONTHLY_SAVINGS       FLOAT,
  VERIFICATION_OUTCOME      VARCHAR(100),
  VERIFICATION_RESULT       VARCHAR(8000),
  SOURCE_QUERY              VARCHAR(8000)
);

CREATE OR REPLACE PROCEDURE SP_OVERWATCH_VERIFY_COST_SAVINGS()
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  candidate_count NUMBER DEFAULT 0;
  verified_count NUMBER DEFAULT 0;
  evidence_required_count NUMBER DEFAULT 0;
BEGIN
  CREATE OR REPLACE TEMPORARY TABLE TMP_OVERWATCH_COST_SAVINGS_VERIFY AS
  WITH candidates AS (
    SELECT
      ACTION_ID,
      COMPANY,
      ENVIRONMENT,
      CATEGORY,
      ENTITY_TYPE,
      ENTITY_NAME,
      OWNER,
      OWNER_APPROVAL_STATUS,
      STATUS,
      BASELINE_VALUE,
      CURRENT_VALUE,
      EST_MONTHLY_SAVINGS,
      VERIFICATION_QUERY,
      REGEXP_REPLACE(ENTITY_NAME, '^"|"$', '') AS WAREHOUSE_NAME
    FROM OVERWATCH_ACTION_QUEUE
    WHERE UPPER(COALESCE(STATUS, '')) NOT IN ('IGNORED')
      AND (
        UPPER(COALESCE(CATEGORY, '')) IN ('COST', 'COST CONTROL')
        OR UPPER(COALESCE(SOURCE, '')) LIKE 'COST & CONTRACT%'
      )
      AND UPPER(COALESCE(ENTITY_TYPE, '')) = 'WAREHOUSE'
      AND COALESCE(EST_MONTHLY_SAVINGS, 0) > 0
      AND UPPER(COALESCE(VERIFICATION_STATUS, 'PENDING')) IN ('', 'PENDING', 'EVIDENCE REQUIRED')
  ),
  post_period AS (
    SELECT
      WAREHOUSE_NAME,
      SUM(COALESCE(CREDITS_USED, 0)) AS POST_PERIOD_CREDITS
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
    WHERE START_TIME >= DATEADD('DAY', -7, CURRENT_DATE())
      AND START_TIME < CURRENT_DATE()
    GROUP BY WAREHOUSE_NAME
  ),
  scored AS (
    SELECT
      c.*,
      p.POST_PERIOD_CREDITS,
      p.POST_PERIOD_CREDITS - c.CURRENT_VALUE AS MEASURED_DELTA,
      CASE
        WHEN UPPER(COALESCE(c.OWNER_APPROVAL_STATUS, '')) NOT IN ('APPROVED', 'NOT REQUIRED')
          THEN 'Approval Required'
        WHEN p.POST_PERIOD_CREDITS IS NULL
          THEN 'No Metering Evidence'
        WHEN c.BASELINE_VALUE IS NULL OR c.CURRENT_VALUE IS NULL
          THEN 'Baseline Required'
        WHEN p.POST_PERIOD_CREDITS <= c.BASELINE_VALUE
          THEN 'Verified Savings'
        WHEN p.POST_PERIOD_CREDITS < c.CURRENT_VALUE
          THEN 'Improvement Needs Review'
        ELSE 'No Savings Yet'
      END AS VERIFICATION_OUTCOME
    FROM candidates c
    LEFT JOIN post_period p
      ON UPPER(p.WAREHOUSE_NAME) = UPPER(c.WAREHOUSE_NAME)
  )
  SELECT
    ACTION_ID,
    COMPANY,
    ENVIRONMENT,
    CATEGORY,
    ENTITY_TYPE,
    ENTITY_NAME,
    OWNER,
    OWNER_APPROVAL_STATUS,
    STATUS AS STATUS_BEFORE,
    BASELINE_VALUE,
    CURRENT_VALUE AS DETECTION_CURRENT_VALUE,
    POST_PERIOD_CREDITS AS POST_PERIOD_VALUE,
    MEASURED_DELTA,
    EST_MONTHLY_SAVINGS,
    VERIFICATION_OUTCOME,
    'Automated post-period verification: last 7 complete days for ' || ENTITY_NAME ||
      '. Baseline=' || COALESCE(TO_VARCHAR(BASELINE_VALUE), 'missing') ||
      '; detection current=' || COALESCE(TO_VARCHAR(CURRENT_VALUE), 'missing') ||
      '; post-period=' || COALESCE(TO_VARCHAR(POST_PERIOD_CREDITS), 'missing') ||
      '; outcome=' || VERIFICATION_OUTCOME AS VERIFICATION_RESULT,
    'SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY last 7 complete days by warehouse' AS SOURCE_QUERY
  FROM scored;

  SELECT COUNT(*) INTO :candidate_count FROM TMP_OVERWATCH_COST_SAVINGS_VERIFY;
  SELECT COUNT_IF(VERIFICATION_OUTCOME = 'Verified Savings') INTO :verified_count
  FROM TMP_OVERWATCH_COST_SAVINGS_VERIFY;
  SELECT COUNT_IF(VERIFICATION_OUTCOME <> 'Verified Savings') INTO :evidence_required_count
  FROM TMP_OVERWATCH_COST_SAVINGS_VERIFY;

  INSERT INTO OVERWATCH_COST_SAVINGS_VERIFICATION_RUN (
    ACTION_ID, COMPANY, ENVIRONMENT, CATEGORY, ENTITY_TYPE, ENTITY_NAME,
    OWNER, OWNER_APPROVAL_STATUS, STATUS_BEFORE, BASELINE_VALUE,
    DETECTION_CURRENT_VALUE, POST_PERIOD_VALUE, MEASURED_DELTA,
    EST_MONTHLY_SAVINGS, VERIFICATION_OUTCOME, VERIFICATION_RESULT, SOURCE_QUERY
  )
  SELECT
    ACTION_ID, COMPANY, ENVIRONMENT, CATEGORY, ENTITY_TYPE, ENTITY_NAME,
    OWNER, OWNER_APPROVAL_STATUS, STATUS_BEFORE, BASELINE_VALUE,
    DETECTION_CURRENT_VALUE, POST_PERIOD_VALUE, MEASURED_DELTA,
    EST_MONTHLY_SAVINGS, VERIFICATION_OUTCOME, VERIFICATION_RESULT, SOURCE_QUERY
  FROM TMP_OVERWATCH_COST_SAVINGS_VERIFY;

  UPDATE OVERWATCH_ACTION_QUEUE q
  SET
    UPDATED_AT = CURRENT_TIMESTAMP(),
    CURRENT_VALUE = v.POST_PERIOD_VALUE,
    MEASURED_DELTA = v.MEASURED_DELTA,
    VERIFICATION_STATUS = IFF(v.VERIFICATION_OUTCOME = 'Verified Savings', 'Verified', 'Evidence Required'),
    VERIFICATION_RESULT = v.VERIFICATION_RESULT,
    VERIFIED_BY = IFF(v.VERIFICATION_OUTCOME = 'Verified Savings', 'SP_OVERWATCH_VERIFY_COST_SAVINGS', q.VERIFIED_BY),
    VERIFIED_AT = IFF(v.VERIFICATION_OUTCOME = 'Verified Savings', CURRENT_TIMESTAMP(), q.VERIFIED_AT),
    RECOVERY_SLA_STATE = CASE
      WHEN v.VERIFICATION_OUTCOME = 'Verified Savings' THEN 'Savings Verified'
      WHEN v.VERIFICATION_OUTCOME = 'Improvement Needs Review' THEN 'Savings Improvement Needs Review'
      ELSE 'Savings Evidence Required'
    END,
    RECOVERY_EVIDENCE = IFF(v.VERIFICATION_OUTCOME = 'Verified Savings', v.VERIFICATION_RESULT, q.RECOVERY_EVIDENCE)
  FROM TMP_OVERWATCH_COST_SAVINGS_VERIFY v
  WHERE q.ACTION_ID = v.ACTION_ID;

  RETURN 'OVERWATCH cost savings verification complete. candidates=' || candidate_count ||
         ', verified=' || verified_count ||
         ', evidence_required=' || evidence_required_count;
END;
$$;

CREATE OR REPLACE VIEW OVERWATCH_COST_SAVINGS_VERIFICATION_V AS
SELECT *
FROM OVERWATCH_COST_SAVINGS_VERIFICATION_RUN
QUALIFY ROW_NUMBER() OVER (PARTITION BY ACTION_ID ORDER BY RUN_TS DESC, RUN_ID DESC) = 1;

CREATE OR REPLACE VIEW OVERWATCH_COST_SAVINGS_VERIFICATION_HEALTH_V AS
WITH latest_task AS (
  SELECT
    MAX(SCHEDULED_TIME) AS LAST_TASK_SCHEDULED_AT,
    MAX(COMPLETED_TIME) AS LAST_TASK_COMPLETED_AT,
    MAX_BY(STATE, SCHEDULED_TIME) AS LAST_TASK_STATE,
    MAX_BY(ERROR_MESSAGE, SCHEDULED_TIME) AS LAST_TASK_ERROR,
    COUNT_IF(UPPER(COALESCE(STATE, '')) IN ('FAILED', 'FAILED_WITH_ERROR', 'CANCELLED')) AS FAILED_RUNS_7D
  FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
  WHERE UPPER(NAME) = 'OVERWATCH_COST_SAVINGS_VERIFY'
    AND SCHEDULED_TIME >= DATEADD('DAY', -7, CURRENT_TIMESTAMP())
),
latest_run AS (
  SELECT
    MAX(RUN_TS) AS LAST_VERIFICATION_RUN_AT,
    COUNT_IF(RUN_TS >= DATEADD('DAY', -7, CURRENT_TIMESTAMP())) AS LEDGER_RUN_ROWS_7D
  FROM OVERWATCH_COST_SAVINGS_VERIFICATION_RUN
),
latest_outcome AS (
  SELECT
    RUN_TS,
    COUNT(*) AS CANDIDATES_LAST_RUN,
    COUNT_IF(VERIFICATION_OUTCOME = 'Verified Savings') AS VERIFIED_LAST_RUN,
    COUNT_IF(VERIFICATION_OUTCOME <> 'Verified Savings') AS EVIDENCE_REQUIRED_LAST_RUN
  FROM OVERWATCH_COST_SAVINGS_VERIFICATION_RUN
  WHERE RUN_TS = (SELECT MAX(RUN_TS) FROM OVERWATCH_COST_SAVINGS_VERIFICATION_RUN)
  GROUP BY RUN_TS
)
SELECT
  'Cost & Contract Savings Verification' AS CONTROL_NAME,
  'OVERWATCH_COST_SAVINGS_VERIFY' AS TASK_NAME,
  CASE
    WHEN latest_task.LAST_TASK_SCHEDULED_AT IS NULL THEN 'Task Not Seen'
    WHEN UPPER(COALESCE(latest_task.LAST_TASK_STATE, '')) IN ('FAILED', 'FAILED_WITH_ERROR', 'CANCELLED') THEN 'Task Failed'
    WHEN latest_task.LAST_TASK_SCHEDULED_AT < DATEADD('HOUR', -36, CURRENT_TIMESTAMP()) THEN 'Task Stale'
    WHEN latest_run.LAST_VERIFICATION_RUN_AT IS NULL THEN 'No Verification Ledger'
    ELSE 'Healthy'
  END AS TASK_HEALTH_STATE,
  latest_task.LAST_TASK_STATE,
  latest_task.LAST_TASK_SCHEDULED_AT,
  latest_task.LAST_TASK_COMPLETED_AT,
  latest_task.LAST_TASK_ERROR,
  latest_task.FAILED_RUNS_7D,
  latest_run.LAST_VERIFICATION_RUN_AT,
  latest_run.LEDGER_RUN_ROWS_7D,
  COALESCE(latest_outcome.CANDIDATES_LAST_RUN, 0) AS CANDIDATES_LAST_RUN,
  COALESCE(latest_outcome.VERIFIED_LAST_RUN, 0) AS VERIFIED_LAST_RUN,
  COALESCE(latest_outcome.EVIDENCE_REQUIRED_LAST_RUN, 0) AS EVIDENCE_REQUIRED_LAST_RUN,
  CASE
    WHEN latest_task.LAST_TASK_SCHEDULED_AT IS NULL THEN 'Deploy and resume OVERWATCH_COST_SAVINGS_VERIFY after review.'
    WHEN UPPER(COALESCE(latest_task.LAST_TASK_STATE, '')) IN ('FAILED', 'FAILED_WITH_ERROR', 'CANCELLED') THEN 'Open Workload Operations, inspect TASK_HISTORY error, and fix the verification task.'
    WHEN latest_task.LAST_TASK_SCHEDULED_AT < DATEADD('HOUR', -36, CURRENT_TIMESTAMP()) THEN 'Resume or investigate the stale verification task schedule.'
    WHEN latest_run.LAST_VERIFICATION_RUN_AT IS NULL THEN 'Task has run but no ledger rows exist; confirm privileges and candidate query scope.'
    ELSE 'Review evidence-required cost actions and close verified savings only with owner approval.'
  END AS NEXT_ACTION
FROM latest_task
CROSS JOIN latest_run
LEFT JOIN latest_outcome
  ON latest_outcome.RUN_TS = latest_run.LAST_VERIFICATION_RUN_AT;

CREATE OR REPLACE TASK OVERWATCH_COST_SAVINGS_VERIFY
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = 'USING CRON 20 7 * * * America/Chicago'
AS
  CALL SP_OVERWATCH_VERIFY_COST_SAVINGS();

-- Review first, then enable when ready:
-- ALTER TASK OVERWATCH_COST_SAVINGS_VERIFY RESUME;

CREATE TABLE IF NOT EXISTS OVERWATCH_DBA_CHECKLIST_HISTORY (
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
);

CREATE TABLE IF NOT EXISTS OVERWATCH_CHANGE_CONTROL_EVIDENCE (
  SNAPSHOT_ID              VARCHAR(64),
  SNAPSHOT_TS              TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  COMPANY                  VARCHAR(100),
  ENVIRONMENT              VARCHAR(100),
  FINDING_TYPE             VARCHAR(120),
  SEVERITY                 VARCHAR(40),
  ENTITY                   VARCHAR(500),
  USER_NAME                VARCHAR(300),
  ROLE_NAME                VARCHAR(300),
  QUERY_ID                 VARCHAR(200),
  QUERY_TAG                VARCHAR(1000),
  LAST_SEEN                VARCHAR(100),
  CHANGE_CONTROL_STATE     VARCHAR(120),
  CONTROL_GAP              VARCHAR(1000),
  CHANGE_TICKET_ID         VARCHAR(200),
  CHANGE_TICKET_STATE      VARCHAR(120),
  IAC_RECONCILIATION_STATE VARCHAR(160),
  EXECUTION_AUDIT_STATE    VARCHAR(160),
  OWNER                    VARCHAR(200),
  ESCALATION_TARGET        VARCHAR(200),
  OWNER_SOURCE             VARCHAR(200),
  APPROVER                 VARCHAR(200),
  OWNER_APPROVAL_STATUS    VARCHAR(40),
  APPROVAL_REQUIRED        VARCHAR(20),
  TICKET_REQUIRED          VARCHAR(20),
  BLAST_RADIUS_REQUIRED    VARCHAR(20),
  APPROVAL_ROUTE_READY     VARCHAR(20),
  CHANGE_EVIDENCE_READINESS VARCHAR(80),
  EVIDENCE_BLOCKERS        VARCHAR(2000),
  REVIEW_SLA_HOURS         NUMBER,
  NEXT_CONTROL_ACTION      VARCHAR(4000),
  PROOF_REQUIRED           VARCHAR(2000),
  VERIFICATION_QUERY       VARCHAR(8000),
  BLAST_RADIUS_QUERY       VARCHAR(8000),
  SOURCE                   VARCHAR(500)
);

CREATE TABLE IF NOT EXISTS OVERWATCH_SOURCE_CONTROL_CHANGE (
  SNAPSHOT_TS          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  COMPANY              VARCHAR(100),
  ENVIRONMENT          VARCHAR(100),
  SOURCE_SYSTEM        VARCHAR(80),
  REPOSITORY           VARCHAR(500),
  BRANCH_NAME          VARCHAR(500),
  COMMIT_SHA           VARCHAR(120),
  PR_ID                VARCHAR(120),
  PR_URL               VARCHAR(1000),
  CHANGE_TICKET_ID     VARCHAR(200),
  OBJECT_DATABASE      VARCHAR(300),
  OBJECT_SCHEMA        VARCHAR(300),
  OBJECT_NAME          VARCHAR(500),
  OBJECT_TYPE          VARCHAR(120),
  OBJECT_FQN           VARCHAR(1000),
  TERRAFORM_ADDRESS    VARCHAR(1000),
  PLANNED_ACTION       VARCHAR(80),
  APPLY_STATUS         VARCHAR(120),
  DEPLOYED_BY          VARCHAR(300),
  APPLY_TS             TIMESTAMP_NTZ,
  EVIDENCE_URL         VARCHAR(1000),
  NOTES                VARCHAR(4000)
);

CREATE TABLE IF NOT EXISTS OVERWATCH_ITSM_TICKET (
  SNAPSHOT_TS           TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  COMPANY               VARCHAR(100),
  ENVIRONMENT           VARCHAR(100),
  TICKET_ID             VARCHAR(200),
  TICKET_URL            VARCHAR(1000),
  SUMMARY               VARCHAR(2000),
  STATUS                VARCHAR(120),
  ASSIGNEE              VARCHAR(300),
  REQUESTER             VARCHAR(300),
  APPROVER              VARCHAR(300),
  APPROVAL_STATUS       VARCHAR(120),
  RISK                  VARCHAR(120),
  CHANGE_WINDOW_START   TIMESTAMP_NTZ,
  CHANGE_WINDOW_END     TIMESTAMP_NTZ,
  LINKED_REPOSITORY     VARCHAR(500),
  LINKED_COMMIT_SHA     VARCHAR(120),
  LINKED_PR_URL         VARCHAR(1000),
  UPDATED_AT            TIMESTAMP_NTZ,
  NOTES                 VARCHAR(4000)
);

CREATE FILE FORMAT IF NOT EXISTS OVERWATCH_CHANGE_EVIDENCE_CSV_FORMAT
  TYPE = CSV
  FIELD_OPTIONALLY_ENCLOSED_BY = '"'
  SKIP_HEADER = 1
  NULL_IF = ('', 'NULL', 'null')
  EMPTY_FIELD_AS_NULL = TRUE
  TIMESTAMP_FORMAT = 'AUTO';

CREATE STAGE IF NOT EXISTS OVERWATCH_SOURCE_CONTROL_CHANGE_STAGE
  FILE_FORMAT = OVERWATCH_CHANGE_EVIDENCE_CSV_FORMAT;

CREATE STAGE IF NOT EXISTS OVERWATCH_ITSM_TICKET_STAGE
  FILE_FORMAT = OVERWATCH_CHANGE_EVIDENCE_CSV_FORMAT;


CREATE TABLE IF NOT EXISTS OVERWATCH_WAREHOUSE_SETTING_REVIEW (
  SNAPSHOT_ID                   VARCHAR(64),
  SNAPSHOT_TS                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  COMPANY                       VARCHAR(100),
  ENVIRONMENT                   VARCHAR(100),
  WAREHOUSE_NAME                VARCHAR(300),
  SEVERITY                      VARCHAR(40),
  SIGNAL                        VARCHAR(120),
  OWNER                         VARCHAR(200),
  ESCALATION_TARGET             VARCHAR(200),
  OWNER_SOURCE                  VARCHAR(200),
  APPROVER                      VARCHAR(200),
  APPROVAL_REQUIRED             VARCHAR(20),
  ROLLBACK_REQUIRED             VARCHAR(20),
  SAFE_CHANGE_PATH              VARCHAR(4000),
  SETTING_CHANGE_CANDIDATE      VARCHAR(4000),
  CHANGE_RISK                   VARCHAR(2000),
  POST_CHANGE_VERIFICATION      VARCHAR(2000),
  PRESSURE_EVIDENCE             VARCHAR(2000),
  BASELINE_CAPACITY_SCORE       FLOAT,
  BASELINE_QUEUED_QUERIES       NUMBER,
  BASELINE_SPILL_QUERIES        NUMBER,
  BASELINE_HIGH_LATENCY_QUERIES NUMBER,
  BASELINE_P95_ELAPSED_SEC      FLOAT,
  BASELINE_METERED_CREDITS      FLOAT,
  VERIFICATION_QUERY            VARCHAR(8000),
  GENERATED_REVIEW_SQL          VARCHAR(8000),
  SAVINGS_VERIFICATION_REQUIRED VARCHAR(20),
  APPROVAL_STATE                VARCHAR(80),
  CHANGE_TICKET_ID              VARCHAR(200),
  CURRENT_SETTINGS_JSON         VARCHAR(8000),
  PROPOSED_SETTINGS_JSON        VARCHAR(8000),
  ROLLBACK_SQL                  VARCHAR(8000),
  EXECUTED_SQL_HASH             VARCHAR(80),
  EXECUTION_STATUS              VARCHAR(80),
  EXECUTED_BY                   VARCHAR(200),
  EXECUTED_AT                   TIMESTAMP_NTZ,
  POST_CHANGE_VERIFICATION_STATUS VARCHAR(80),
  POST_CHANGE_VERIFICATION_RESULT VARCHAR(4000),
  VERIFIED_MONTHLY_SAVINGS     FLOAT,
  AUDIT_READINESS               VARCHAR(100),
  AUDIT_BLOCKERS                VARCHAR(2000),
  NEXT_CONTROL_ACTION           VARCHAR(4000),
  SOURCE                        VARCHAR(500)
);

CREATE TABLE IF NOT EXISTS OVERWATCH_SECURITY_ACCESS_REVIEW (
  SNAPSHOT_ID             VARCHAR(64),
  SNAPSHOT_TS             TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  COMPANY                 VARCHAR(100),
  ENVIRONMENT             VARCHAR(100),
  DATABASE_CONTEXT        BOOLEAN,
  FINDING_TYPE            VARCHAR(120),
  SEVERITY                VARCHAR(40),
  ENTITY_TYPE             VARCHAR(120),
  ENTITY                  VARCHAR(500),
  EVENT_COUNT             NUMBER,
  DISTINCT_SOURCES        NUMBER,
  LAST_SEEN               VARCHAR(100),
  OWNER                   VARCHAR(200),
  ESCALATION_TARGET       VARCHAR(200),
  OWNER_SOURCE            VARCHAR(200),
  APPROVER                VARCHAR(200),
  OWNER_APPROVAL_STATUS   VARCHAR(40),
  ACCESS_REVIEW_STATE     VARCHAR(160),
  ROLE_CAPABILITY_STATE   VARCHAR(200),
  TICKET_REQUIRED         VARCHAR(20),
  REVIEW_BY_REQUIRED      VARCHAR(20),
  PROOF_REQUIRED          VARCHAR(2000),
  VERIFICATION_QUERY      VARCHAR(8000),
  ACCESS_TICKET_ID        VARCHAR(200),
  REVIEW_BY_DATE          VARCHAR(100),
  IAM_APPROVAL_STATE      VARCHAR(120),
  REVIEW_READINESS        VARCHAR(100),
  REVIEW_BLOCKERS         VARCHAR(2000),
  REVIEW_SLA_HOURS        NUMBER,
  VERIFICATION_STATUS     VARCHAR(80),
  VERIFICATION_RESULT     VARCHAR(4000),
  CONTROL_READINESS       VARCHAR(100),
  CONTROL_BLOCKERS        VARCHAR(2000),
  NEXT_CONTROL_ACTION     VARCHAR(4000),
  NEXT_ACTION             VARCHAR(4000),
  PROOF_QUERY             VARCHAR(4000),
  SOURCE                  VARCHAR(500)
);


CREATE TABLE IF NOT EXISTS OVERWATCH_ALERTS (
  ALERT_ID             NUMBER AUTOINCREMENT PRIMARY KEY,
  ALERT_TS             TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  COMPANY              VARCHAR(100),
  ENVIRONMENT          VARCHAR(100),
  DATABASE_NAME        VARCHAR(300),
  SCHEMA_NAME          VARCHAR(300),
  WAREHOUSE_NAME       VARCHAR(300),
  CATEGORY             VARCHAR(100),
  ALERT_TYPE           VARCHAR(100),
  SEVERITY             VARCHAR(20),
  ENTITY_NAME          VARCHAR(500),
  ENTITY               VARCHAR(500),
  MESSAGE              VARCHAR(4000),
  DETAIL               VARCHAR(4000),
  SUGGESTED_ACTION     VARCHAR(2000),
  PROOF_QUERY          VARCHAR(8000),
  OWNER                VARCHAR(200),
  STATUS               VARCHAR(40) DEFAULT 'New',
  DELIVERY_METHOD      VARCHAR(40) DEFAULT 'EMAIL',
  DELIVERY_TARGET      VARCHAR(500),
  EMAIL_TARGET         VARCHAR(500),
  EMAIL_SUBJECT        VARCHAR(1000),
  EMAIL_BODY           VARCHAR(16000),
  DELIVERY_STATUS      VARCHAR(100),
  ACKNOWLEDGED_BY      VARCHAR(200),
  ACKNOWLEDGED_AT      TIMESTAMP_NTZ,
  RESOLVED             BOOLEAN DEFAULT FALSE,
  STATUS_REASON        VARCHAR(2000),
  LAST_STATUS_BY       VARCHAR(200),
  LAST_STATUS_AT       TIMESTAMP_NTZ,
  LAST_DELIVERY_AT     TIMESTAMP_NTZ,
  LAST_DELIVERY_BY     VARCHAR(200),
  DELIVERY_LOG_COUNT   NUMBER DEFAULT 0,
  ESCALATED_TO         VARCHAR(200),
  ESCALATED_AT         TIMESTAMP_NTZ,
  ESCALATION_ACK_BY    VARCHAR(200),
  ESCALATION_ACK_AT    TIMESTAMP_NTZ,
  ESCALATION_ACK_NOTE  VARCHAR(2000),
  ROUTED_TO_ACTION_QUEUE_AT TIMESTAMP_NTZ,
  ROUTED_ACTION_COUNT  NUMBER DEFAULT 0
);

-- Upgrade older Alert Center installs to the current routing/status contract.
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS DATABASE_NAME VARCHAR(300);
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS SCHEMA_NAME VARCHAR(300);
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS WAREHOUSE_NAME VARCHAR(300);
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS ALERT_TYPE VARCHAR(100);
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS ENTITY VARCHAR(500);
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS DETAIL VARCHAR(4000);
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS SUGGESTED_ACTION VARCHAR(2000);
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS OWNER VARCHAR(200);
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS STATUS VARCHAR(40);
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS DELIVERY_METHOD VARCHAR(40);
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS EMAIL_TARGET VARCHAR(500);
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS EMAIL_SUBJECT VARCHAR(1000);
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS EMAIL_BODY VARCHAR(16000);
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS RESOLVED BOOLEAN;
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS STATUS_REASON VARCHAR(2000);
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS LAST_STATUS_BY VARCHAR(200);
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS LAST_STATUS_AT TIMESTAMP_NTZ;
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS LAST_DELIVERY_AT TIMESTAMP_NTZ;
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS LAST_DELIVERY_BY VARCHAR(200);
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS DELIVERY_LOG_COUNT NUMBER;
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS ESCALATED_TO VARCHAR(200);
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS ESCALATED_AT TIMESTAMP_NTZ;
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS ESCALATION_ACK_BY VARCHAR(200);
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS ESCALATION_ACK_AT TIMESTAMP_NTZ;
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS ESCALATION_ACK_NOTE VARCHAR(2000);
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS ROUTED_TO_ACTION_QUEUE_AT TIMESTAMP_NTZ;
ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS ROUTED_ACTION_COUNT NUMBER;


CREATE TABLE IF NOT EXISTS OVERWATCH_ANNOTATIONS (
  ANNOTATION_ID     NUMBER AUTOINCREMENT PRIMARY KEY,
  CREATED_BY        VARCHAR(200),
  CREATED_AT        TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  ENTITY            VARCHAR(500),
  ENTITY_TYPE       VARCHAR(50),
  WINDOW_START      TIMESTAMP_NTZ NOT NULL,
  WINDOW_END        TIMESTAMP_NTZ NOT NULL,
  ANNOTATION_TYPE   VARCHAR(100),
  DESCRIPTION       VARCHAR(2000),
  SUPPRESS_ALERTS   BOOLEAN DEFAULT TRUE,
  ACTIVE            BOOLEAN DEFAULT TRUE
);


CREATE TABLE IF NOT EXISTS OVERWATCH_ALERT_DELIVERY_LOG (
  DELIVERY_ID      NUMBER AUTOINCREMENT PRIMARY KEY,
  DELIVERY_TS      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  COMPANY          VARCHAR(100),
  ENVIRONMENT      VARCHAR(100),
  ALERT_IDS        VARIANT,
  ALERT_COUNT      NUMBER,
  DELIVERY_METHOD  VARCHAR(40) DEFAULT 'EMAIL',
  DELIVERY_TARGET  VARCHAR(500),
  EMAIL_SUBJECT    VARCHAR(1000),
  EMAIL_BODY       VARCHAR(16000),
  DELIVERY_STATUS  VARCHAR(100),
  DELIVERY_BY      VARCHAR(200),
  DELIVERY_NOTES   VARCHAR(4000)
);

CREATE OR REPLACE PROCEDURE SP_OVERWATCH_SEND_ALERT_DIGEST(
  P_COMPANY VARCHAR DEFAULT 'ALFA',
  P_ENVIRONMENT VARCHAR DEFAULT 'ALL',
  P_RECIPIENT VARCHAR DEFAULT 'dba-alerts@yourcompany.com',
  P_DRY_RUN BOOLEAN DEFAULT TRUE
)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  alert_count NUMBER DEFAULT 0;
  alert_ids VARIANT DEFAULT PARSE_JSON('[]');
  subject VARCHAR DEFAULT '';
  body VARCHAR DEFAULT '';
  delivery_status VARCHAR DEFAULT 'EMAIL_DRY_RUN';
BEGIN
  CREATE OR REPLACE TEMPORARY TABLE TMP_OVERWATCH_ALERT_DIGEST AS
  SELECT
    ALERT_ID,
    COMPANY,
    ENVIRONMENT,
    SEVERITY,
    CATEGORY,
    ALERT_TYPE,
    ENTITY_NAME,
    OWNER,
    COALESCE(EMAIL_SUBJECT, 'OVERWATCH ' || COALESCE(SEVERITY, 'Medium') || ' alert digest') AS EMAIL_SUBJECT,
    COALESCE(
      EMAIL_BODY,
      COALESCE(SEVERITY, 'Medium') || ' | ' || COALESCE(CATEGORY, 'Alert') || ' | ' ||
      COALESCE(ALERT_TYPE, CATEGORY, 'Alert') || ' | ' || COALESCE(ENTITY_NAME, ENTITY, 'Snowflake account') ||
      '\nAction: ' || COALESCE(SUGGESTED_ACTION, 'Review in Alert Center.')
    ) AS EMAIL_BODY
  FROM OVERWATCH_ALERTS
  WHERE UPPER(REPLACE(COALESCE(STATUS, 'New'), ' ', '_')) IN ('NEW', 'OPEN', 'ACTIVE', 'EMAIL_READY', 'EMAIL_QUEUED', 'PENDING', 'ACKNOWLEDGED', 'IN_PROGRESS')
    AND (P_COMPANY = 'ALL' OR COMPANY = P_COMPANY)
    AND (
      P_ENVIRONMENT = 'ALL'
      OR COALESCE(ENVIRONMENT, 'No Database Context') = P_ENVIRONMENT
      OR (P_ENVIRONMENT = 'DEV_ALL' AND COALESCE(ENVIRONMENT, '') IN ('DEV_ALL', 'ALFA_EDW_DEV', 'ALFA_EDW_SAN', 'ALFA_EDW_PHX', 'ALFA_EDW_SEA', 'ALFA_EDW_SIT', 'OTHER ALFA NON-PROD'))
    )
  ORDER BY
    CASE UPPER(COALESCE(SEVERITY, 'Medium'))
      WHEN 'CRITICAL' THEN 0
      WHEN 'HIGH' THEN 1
      WHEN 'MEDIUM' THEN 2
      WHEN 'LOW' THEN 3
      ELSE 4
    END,
    ALERT_TS DESC
  LIMIT 25;

  SELECT
    COUNT(*),
    TO_VARIANT(ARRAY_AGG(ALERT_ID)),
    'OVERWATCH alert digest - ' || P_COMPANY || ' / ' || P_ENVIRONMENT || ' - ' || COUNT(*) || ' open issue(s)',
    LISTAGG(
      '[' || COALESCE(SEVERITY, 'Medium') || '] ' || COALESCE(ALERT_TYPE, CATEGORY, 'Alert') ||
      ' | ' || COALESCE(ENTITY_NAME, 'Snowflake account') ||
      ' | Owner: ' || COALESCE(OWNER, 'DBA') ||
      '\n' || EMAIL_BODY,
      '\n\n---\n\n'
    ) WITHIN GROUP (ORDER BY ALERT_ID)
  INTO :alert_count, :alert_ids, :subject, :body
  FROM TMP_OVERWATCH_ALERT_DIGEST;

  IF (alert_count = 0) THEN
    RETURN 'No open OVERWATCH alerts matched the requested scope.';
  END IF;

  IF (P_DRY_RUN) THEN
    delivery_status := 'EMAIL_DRY_RUN';
  ELSE
    CALL SYSTEM$SEND_EMAIL('OVERWATCH_EMAIL_INT', :P_RECIPIENT, :subject, :body);
    delivery_status := 'EMAIL_SENT';
  END IF;

  INSERT INTO OVERWATCH_ALERT_DELIVERY_LOG
    (COMPANY, ENVIRONMENT, ALERT_IDS, ALERT_COUNT, DELIVERY_METHOD, DELIVERY_TARGET,
     EMAIL_SUBJECT, EMAIL_BODY, DELIVERY_STATUS, DELIVERY_BY, DELIVERY_NOTES)
  VALUES
    (P_COMPANY, P_ENVIRONMENT, alert_ids, alert_count, 'EMAIL', P_RECIPIENT,
     subject, body, delivery_status, CURRENT_USER(),
     IFF(P_DRY_RUN, 'Dry-run replay package prepared; SYSTEM$SEND_EMAIL was not called.',
                    'Delivered through approved Snowflake email notification integration OVERWATCH_EMAIL_INT.'));

  UPDATE OVERWATCH_ALERTS
  SET
    DELIVERY_STATUS = delivery_status,
    DELIVERY_TARGET = P_RECIPIENT,
    EMAIL_TARGET = COALESCE(NULLIF(EMAIL_TARGET, ''), P_RECIPIENT),
    LAST_DELIVERY_AT = CURRENT_TIMESTAMP(),
    LAST_DELIVERY_BY = CURRENT_USER(),
    DELIVERY_LOG_COUNT = COALESCE(DELIVERY_LOG_COUNT, 0) + 1,
    LAST_STATUS_BY = CURRENT_USER(),
    LAST_STATUS_AT = CURRENT_TIMESTAMP()
  WHERE ARRAY_CONTAINS(ALERT_ID::VARIANT, alert_ids);

  RETURN 'OVERWATCH alert digest ' || delivery_status || ': ' || alert_count || ' alert(s) for ' || P_RECIPIENT;
END;
$$;

CREATE TABLE IF NOT EXISTS OVERWATCH_ALERT_RULE_AUDIT (
  AUDIT_ID                NUMBER AUTOINCREMENT PRIMARY KEY,
  AUDIT_TS                TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  RULE_ID                 VARCHAR(200),
  ACTION                  VARCHAR(40),
  PRIOR_DEFAULT_SEVERITY  VARCHAR(20),
  NEW_DEFAULT_SEVERITY    VARCHAR(20),
  PRIOR_SLA_HOURS         NUMBER,
  NEW_SLA_HOURS           NUMBER,
  PRIOR_OWNER             VARCHAR(200),
  NEW_OWNER               VARCHAR(200),
  PRIOR_ROUTE             VARCHAR(200),
  NEW_ROUTE               VARCHAR(200),
  PRIOR_RUNBOOK           VARCHAR(2000),
  NEW_RUNBOOK             VARCHAR(2000),
  PRIOR_IS_ACTIVE         BOOLEAN,
  NEW_IS_ACTIVE           BOOLEAN,
  CHANGED_BY              VARCHAR(200),
  CHANGE_REASON           VARCHAR(2000)
);

CREATE TABLE IF NOT EXISTS OVERWATCH_ALERT_RULES (
  RULE_ID              VARCHAR(200) PRIMARY KEY,
  CATEGORY             VARCHAR(100),
  ALERT_TYPE           VARCHAR(100),
  DEFAULT_SEVERITY     VARCHAR(20),
  SLA_HOURS            NUMBER,
  OWNER                VARCHAR(200),
  ROUTE                VARCHAR(200),
  RUNBOOK              VARCHAR(2000),
  IS_ACTIVE            BOOLEAN DEFAULT TRUE,
  UPDATED_AT           TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_BY           VARCHAR(200) DEFAULT CURRENT_USER()
);

MERGE INTO OVERWATCH_ALERT_RULES tgt
USING (
  SELECT * FROM VALUES
    ('COST_CREDIT_SPIKE', 'Cost Control', 'Credit Spike', 'Medium', 24, 'DBA / FinOps', 'Cost & Contract', 'Explain the bill movement, identify owner-backed drivers, and route savings actions.'),
    ('COST_SAVINGS_VERIFIER_FAILURE', 'Cost Control', 'Cost Savings Verification Failure', 'High', 8, 'DBA / FinOps', 'Cost & Contract', 'Inspect the savings verifier task, keep savings estimated, and restore ledger-backed verification before claiming value.'),
    ('QUERY_HIGH_ERROR_RATE', 'Reliability', 'High Query Error Rate', 'High', 8, 'DBA / Workload Owner', 'Workload Operations', 'Group failures by error code/query text and assign the owning team.'),
    ('TASK_FAILURE', 'Reliability', 'Task Failure', 'High', 8, 'DBA / Pipeline Owner', 'Workload Operations', 'Review task graph impact, retry only after root cause, and verify the next run.'),
    ('PROCEDURE_FAILURE_OR_SPIKE', 'Reliability', 'Stored Procedure Failure / Runtime Spike', 'High', 8, 'DBA / Procedure Owner', 'Workload Operations', 'Compare release windows, inspect child queries, and verify runtime/cost return to baseline.'),
    ('WAREHOUSE_PRESSURE', 'Capacity', 'Warehouse Pressure', 'Medium', 24, 'DBA / Platform', 'Warehouse Health', 'Inspect queue/spill evidence and route changed-only warehouse setting recommendations.'),
    ('GRANT_REVOKE_ACTIVITY', 'Change Control', 'Grant/Revoke Activity', 'Medium', 24, 'DBA / Security', 'Security Posture', 'Verify least-privilege approval, owner, ticket, approver, and review date.'),
    ('WAREHOUSE_SETTING_CHANGE', 'Change Control', 'Warehouse Setting Change', 'Medium', 24, 'DBA / Platform', 'Change & Drift', 'Verify changed-only SQL, approval, rollback SQL, and post-change evidence.'),
    ('WAREHOUSE_COST_MOVEMENT', 'Cost Control', 'WAREHOUSE_COST_MOVEMENT', 'High', 8, 'DBA / FinOps', 'Cost & Contract', 'Explain the 7d warehouse cost movement, assign the owner, and route verified action only after proof.'),
    ('CORTEX_BUDGET_AND_QUOTA', 'Cost Control', 'CORTEX_BUDGET_AND_QUOTA', 'Medium', 24, 'DBA / AI FinOps', 'Cost & Contract', 'Review shared AI budget, per-user quota, first/last usage, and access expansion before enforcing controls.'),
    ('CHANGE_COST_CORRELATION', 'Cost Control', 'CHANGE_COST_CORRELATION', 'High', 8, 'DBA / FinOps', 'Change & Drift', 'Compare warehouse change query_id, actor, ticket, rollback evidence, and cost movement before tuning.')
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

CREATE OR REPLACE VIEW OVERWATCH_ALERT_TRIAGE_V AS
WITH base AS (
  SELECT
    a.*,
    COALESCE(od.OWNER_NAME, r.OWNER, a.OWNER, 'DBA') AS ROUTED_OWNER,
    od.OWNER_EMAIL,
    od.ONCALL_PRIMARY,
    od.ONCALL_SECONDARY,
    COALESCE(od.APPROVAL_GROUP, r.OWNER, a.OWNER, 'DBA Lead') AS APPROVAL_GROUP,
    COALESCE(od.ESCALATION_TARGET, od.APPROVAL_GROUP, r.OWNER, a.OWNER, 'DBA Lead') AS OWNER_ESCALATION_TARGET,
    CASE WHEN od.OWNER_KEY IS NOT NULL THEN 'OWNER_DIRECTORY:' || od.OWNER_KEY ELSE 'ALERT_RULE' END AS OWNER_SOURCE,
    CASE WHEN od.OWNER_KEY IS NOT NULL THEN 'Matched ' || od.ENTITY_TYPE || ' pattern ' || od.ENTITY_PATTERN ELSE 'Matched alert rule owner' END AS OWNER_EVIDENCE,
    COALESCE(
      r.SLA_HOURS,
      CASE UPPER(COALESCE(a.SEVERITY, 'Medium'))
        WHEN 'CRITICAL' THEN 4
        WHEN 'HIGH' THEN 8
        WHEN 'LOW' THEN 72
        ELSE 24
      END
    ) AS SLA_TARGET_HOURS,
    GREATEST(0, COALESCE(DATEDIFF('hour', a.ALERT_TS, CURRENT_TIMESTAMP()), 0)) AS ALERT_AGE_HOURS,
    COALESCE(r.ROUTE, 'Alert Center') AS ALERT_ROUTE,
    COALESCE(r.RUNBOOK, a.SUGGESTED_ACTION, 'Review the Alert Center issue and route it through the DBA action queue.') AS ALERT_RUNBOOK
  FROM OVERWATCH_ALERTS a
  LEFT JOIN OVERWATCH_ALERT_RULES r
    ON UPPER(COALESCE(a.ALERT_TYPE, a.CATEGORY, '')) = UPPER(COALESCE(r.ALERT_TYPE, r.CATEGORY, ''))
   AND COALESCE(r.IS_ACTIVE, TRUE)
  LEFT JOIN OVERWATCH_OWNER_DIRECTORY_ACTIVE_V od
    ON (
      od.ENTITY_TYPE IN ('GLOBAL', 'ALERT')
      OR od.ENTITY_TYPE = UPPER(COALESCE(a.CATEGORY, r.CATEGORY, ''))
      OR (od.ENTITY_TYPE = 'COST_CONTROL' AND UPPER(COALESCE(a.CATEGORY, a.ALERT_TYPE, '')) LIKE '%COST%')
      OR (od.ENTITY_TYPE = 'TASK' AND UPPER(COALESCE(a.ALERT_TYPE, a.CATEGORY, a.ENTITY_NAME, '')) LIKE '%TASK%')
      OR (od.ENTITY_TYPE = 'PROCEDURE' AND UPPER(COALESCE(a.ALERT_TYPE, a.CATEGORY, a.ENTITY_NAME, '')) LIKE '%PROCEDURE%')
      OR (od.ENTITY_TYPE = 'WAREHOUSE' AND UPPER(COALESCE(a.ALERT_TYPE, a.CATEGORY, a.ENTITY_NAME, '')) LIKE '%WAREHOUSE%')
      OR (od.ENTITY_TYPE = 'SECURITY' AND UPPER(COALESCE(a.ALERT_TYPE, a.CATEGORY, '')) REGEXP 'GRANT|REVOKE|ROLE|SECURITY')
    )
   AND (
      UPPER(COALESCE(a.ENTITY_NAME, a.ENTITY, '')) LIKE REPLACE(UPPER(od.ENTITY_PATTERN), '*', '%')
      OR UPPER(COALESCE(a.ALERT_TYPE, a.CATEGORY, '')) LIKE REPLACE(UPPER(od.ENTITY_PATTERN), '*', '%')
      OR od.ENTITY_PATTERN IN ('*', '%')
   )
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY COALESCE(TO_VARCHAR(a.ALERT_ID), TO_VARCHAR(a.ALERT_TS), COALESCE(a.ENTITY_NAME, a.ENTITY, 'UNKNOWN'))
    ORDER BY COALESCE(od.MATCH_PRIORITY, 0) DESC, od.OWNER_KEY
  ) = 1
),
sla AS (
  SELECT
    base.*,
    CASE
      WHEN UPPER(REPLACE(COALESCE(STATUS, 'New'), ' ', '_')) IN ('FIXED', 'IGNORED', 'RESOLVED') THEN 'Closed'
      WHEN ALERT_AGE_HOURS > SLA_TARGET_HOURS THEN 'Overdue'
      WHEN ALERT_AGE_HOURS >= (SLA_TARGET_HOURS * 0.75) THEN 'Due Soon'
      ELSE 'Within SLA'
    END AS SLA_STATE
  FROM base
)
SELECT
  sla.*,
  CASE
    WHEN SLA_STATE = 'Overdue' AND UPPER(COALESCE(SEVERITY, 'Medium')) IN ('CRITICAL', 'HIGH') THEN COALESCE(OWNER_ESCALATION_TARGET, ESCALATED_TO, 'DBA Lead')
    ELSE COALESCE(OWNER_ESCALATION_TARGET, ROUTED_OWNER, OWNER, 'DBA')
  END AS ESCALATION_TARGET,
  (
    CASE UPPER(COALESCE(SEVERITY, 'Medium'))
      WHEN 'CRITICAL' THEN 0
      WHEN 'HIGH' THEN 1
      WHEN 'MEDIUM' THEN 2
      WHEN 'LOW' THEN 3
      ELSE 4
    END * 100
    + CASE SLA_STATE
      WHEN 'Overdue' THEN 0
      WHEN 'Due Soon' THEN 1
      WHEN 'Within SLA' THEN 2
      WHEN 'Closed' THEN 9
      ELSE 5
    END * 10
    + CASE UPPER(REPLACE(COALESCE(STATUS, 'New'), ' ', '_'))
      WHEN 'NEW' THEN 0
      WHEN 'EMAIL_READY' THEN 0
      WHEN 'EMAIL_QUEUED' THEN 0
      WHEN 'OPEN' THEN 0
      WHEN 'ACTIVE' THEN 0
      WHEN 'PENDING' THEN 0
      WHEN 'ACKNOWLEDGED' THEN 1
      WHEN 'IN_PROGRESS' THEN 1
      WHEN 'FIXED' THEN 3
      WHEN 'RESOLVED' THEN 3
      WHEN 'IGNORED' THEN 4
      ELSE 2
    END
  ) AS TRIAGE_PRIORITY
FROM sla;

CREATE TABLE IF NOT EXISTS OVERWATCH_ROI_LOG (
  ROI_ID               NUMBER AUTOINCREMENT PRIMARY KEY,
  LOGGED_DATE          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  LOGGED_BY            VARCHAR(200),
  CATEGORY             VARCHAR(100),
  DESCRIPTION          VARCHAR(1000),
  ENTITY               VARCHAR(500),
  BASELINE_CREDITS     FLOAT,
  CURRENT_CREDITS      FLOAT,
  SAVINGS_CREDITS      FLOAT,
  SAVINGS_MONTHLY      FLOAT,
  VERIFIED             BOOLEAN DEFAULT FALSE,
  COMPANY              VARCHAR(100),
  NOTES                VARCHAR(2000)
);

-- -----------------------------------------------------------------------------
-- 3. Transient mart tables
-- -----------------------------------------------------------------------------

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_WAREHOUSE_HOURLY (
  HOUR_START                   TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  WAREHOUSE_NAME               VARCHAR(300),
  CREDITS_USED                 NUMBER(18,6),
  CREDITS_USED_COMPUTE         NUMBER(18,6),
  CREDITS_USED_CLOUD_SERVICES  NUMBER(18,6),
  EST_COST_USD                 NUMBER(18,2),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_WAREHOUSE_OPERABILITY_DAILY (
  SNAPSHOT_DATE                DATE,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  WAREHOUSE_NAME               VARCHAR(300),
  CONTROL_SOURCE               VARCHAR(80),
  SEVERITY                     VARCHAR(40),
  SIGNAL                       VARCHAR(120),
  CONTROL_STATE                VARCHAR(120),
  CONTROL_RANK                 NUMBER,
  CAPACITY_SCORE               FLOAT,
  QUERY_ROWS                   NUMBER,
  QUEUE_PRESSURE_ROWS          NUMBER,
  SPILL_PRESSURE_ROWS          NUMBER,
  HIGH_LATENCY_ROWS            NUMBER,
  METERED_CREDITS              FLOAT,
  CREDIT_ALLOCATION_METHOD     VARCHAR(160),
  REVIEW_ROWS                  NUMBER,
  APPROVAL_REQUIRED_ROWS       NUMBER,
  ROLLBACK_REQUIRED_ROWS       NUMBER,
  SAVINGS_VERIFICATION_ROWS    NUMBER,
  OPEN_ACTIONS                 NUMBER,
  OVERDUE_OPEN                 NUMBER,
  FIXED_WITHOUT_VERIFICATION   NUMBER,
  VERIFIED_CLOSURES            NUMBER,
  OWNER_APPROVAL_GAP_ROWS      NUMBER,
  NEXT_CONTROL_ACTION          VARCHAR(4000),
  LAST_ACTIVITY_TS             TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_SECURITY_OPERABILITY_DAILY (
  SNAPSHOT_DATE                DATE,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  CONTROL_SOURCE               VARCHAR(80),
  FINDING_TYPE                 VARCHAR(120),
  ENTITY                       VARCHAR(500),
  ENTITY_TYPE                  VARCHAR(120),
  SEVERITY                     VARCHAR(40),
  CONTROL_STATE                VARCHAR(120),
  CONTROL_RANK                 NUMBER,
  EVENT_ROWS                   NUMBER,
  REVIEW_ROWS                  NUMBER,
  REVIEW_BLOCKER_ROWS          NUMBER,
  TICKET_REQUIRED_ROWS         NUMBER,
  REVIEW_BY_REQUIRED_ROWS      NUMBER,
  CAPABILITY_PROOF_ROWS        NUMBER,
  NO_DATABASE_CONTEXT_ROWS     NUMBER,
  OPEN_ACTIONS                 NUMBER,
  OVERDUE_OPEN                 NUMBER,
  FIXED_WITHOUT_VERIFICATION   NUMBER,
  VERIFIED_CLOSURES            NUMBER,
  OWNER_APPROVAL_GAP_ROWS      NUMBER,
  NEXT_CONTROL_ACTION          VARCHAR(4000),
  LAST_ACTIVITY_TS             TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_ACCOUNT_HEALTH_OPERABILITY_DAILY (
  SNAPSHOT_DATE                DATE,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  CONTROL_SOURCE               VARCHAR(80),
  CHECK_NAME                   VARCHAR(200),
  ROUTE                        VARCHAR(120),
  SEVERITY                     VARCHAR(40),
  CONTROL_STATE                VARCHAR(120),
  CONTROL_RANK                 NUMBER,
  HEALTH_SCORE                 FLOAT,
  ISSUE_ROWS                   NUMBER,
  ROUTE_BLOCKER_ROWS           NUMBER,
  QUEUE_REQUIRED_ROWS          NUMBER,
  ACCESS_HYGIENE_ROWS          NUMBER,
  FAILED_LOGIN_ROWS            NUMBER,
  PRIVILEGED_GRANT_ROWS        NUMBER,
  OPEN_ACTIONS                 NUMBER,
  OVERDUE_OPEN                 NUMBER,
  FIXED_WITHOUT_VERIFICATION   NUMBER,
  VERIFIED_CLOSURES            NUMBER,
  OWNER_APPROVAL_GAP_ROWS      NUMBER,
  RECOVERY_RISK_ROWS           NUMBER,
  NEXT_CONTROL_ACTION          VARCHAR(4000),
  LAST_ACTIVITY_TS             TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_QUERY_HOURLY (
  HOUR_START                   TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  WAREHOUSE_NAME               VARCHAR(300),
  WAREHOUSE_SIZE               VARCHAR(100),
  USER_NAME                    VARCHAR(300),
  ROLE_NAME                    VARCHAR(300),
  DATABASE_NAME                VARCHAR(300),
  ENVIRONMENT                  VARCHAR(100),
  SCHEMA_NAME                  VARCHAR(300),
  QUERY_TYPE                   VARCHAR(100),
  QUERY_COUNT                  NUMBER,
  FAILED_COUNT                 NUMBER,
  AVG_EXECUTION_MS             NUMBER(18,2),
  P95_EXECUTION_MS             NUMBER(18,2),
  TOTAL_ELAPSED_MS             NUMBER,
  TOTAL_QUEUED_MS              NUMBER,
  TOTAL_SPILL_BYTES            NUMBER,
  TOTAL_BYTES_SCANNED          NUMBER,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_QUERY_DETAIL_RECENT (
  QUERY_ID                     VARCHAR(200),
  START_TIME                   TIMESTAMP_NTZ,
  END_TIME                     TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  WAREHOUSE_NAME               VARCHAR(300),
  USER_NAME                    VARCHAR(300),
  ROLE_NAME                    VARCHAR(300),
  DATABASE_NAME                VARCHAR(300),
  ENVIRONMENT                  VARCHAR(100),
  SCHEMA_NAME                  VARCHAR(300),
  QUERY_TYPE                   VARCHAR(100),
  EXECUTION_STATUS             VARCHAR(100),
  WAREHOUSE_SIZE               VARCHAR(100),
  ERROR_CODE                   VARCHAR(100),
  ERROR_MESSAGE                VARCHAR,
  TOTAL_ELAPSED_TIME           NUMBER,
  COMPILATION_TIME             NUMBER,
  EXECUTION_TIME               NUMBER,
  QUEUED_OVERLOAD_TIME         NUMBER,
  QUEUED_PROVISIONING_TIME     NUMBER,
  QUEUED_REPAIR_TIME           NUMBER,
  TRANSACTION_BLOCKED_TIME     NUMBER,
  BYTES_SCANNED                NUMBER,
  BYTES_SPILLED_TO_LOCAL_STORAGE NUMBER,
  BYTES_SPILLED_TO_REMOTE_STORAGE NUMBER,
  PARTITIONS_SCANNED           NUMBER,
  PARTITIONS_TOTAL             NUMBER,
  ROWS_PRODUCED                NUMBER,
  QUERY_HASH                   VARCHAR(300),
  QUERY_TEXT                   VARCHAR,
  QUERY_TAG                    VARCHAR,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_CHARGEBACK_DAILY (
  USAGE_DATE                   DATE,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  ENVIRONMENT_ROLLUP           VARCHAR(100),
  DATABASE_NAME                VARCHAR(300),
  USER_NAME                    VARCHAR(300),
  ROLE_NAME                    VARCHAR(300),
  WAREHOUSE_NAME               VARCHAR(300),
  WAREHOUSE_SIZE               VARCHAR(100),
  QUERY_COUNT                  NUMBER,
  ALLOCATED_CREDITS            NUMBER(18,6),
  EST_COST_USD                 NUMBER(18,2),
  ALLOCATION_CONFIDENCE        VARCHAR(100),
  ALLOCATION_BASIS             VARCHAR(1000),
  CHARGEBACK_READY             VARCHAR(100),
  SCOPE_REVIEW                 VARCHAR(1000),
  COST_OWNER                   VARCHAR(300),
  OWNER_SOURCE                 VARCHAR(100),
  OWNER_EVIDENCE               VARCHAR(1000),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS DIM_COST_OWNER_TAG (
  SNAPSHOT_DATE                DATE,
  OWNER_SCOPE                  VARCHAR(100),
  OBJECT_DATABASE              VARCHAR(300),
  OBJECT_SCHEMA                VARCHAR(300),
  OBJECT_NAME                  VARCHAR(500),
  TAG_NAME                     VARCHAR(300),
  TAG_VALUE                    VARCHAR(1000),
  OWNER_TYPE                   VARCHAR(100),
  PRIORITY                     NUMBER,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_TASK_RUN (
  SCHEDULED_TIME               TIMESTAMP_NTZ,
  COMPLETED_TIME               TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  DATABASE_NAME                VARCHAR(300),
  ENVIRONMENT                  VARCHAR(100),
  SCHEMA_NAME                  VARCHAR(300),
  ROOT_TASK_NAME               VARCHAR(500),
  TASK_NAME                    VARCHAR(500),
  STATE                        VARCHAR(100),
  QUERY_ID                     VARCHAR(200),
  ERROR_CODE                   VARCHAR(100),
  ERROR_MESSAGE                VARCHAR,
  DURATION_MS                  NUMBER,
  WAREHOUSE_NAME               VARCHAR(300),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_TASK_CRITICAL_PATH (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  DATABASE_NAME                VARCHAR(300),
  ENVIRONMENT                  VARCHAR(100),
  ROOT_TASK_NAME               VARCHAR(500),
  CRITICAL_PATH_STATE          VARCHAR(100),
  CRITICAL_PATH_SCORE          NUMBER(18,1),
  TASK_COUNT                   NUMBER,
  DOWNSTREAM_TASK_COUNT        NUMBER,
  SUSPENDED_TASKS              NUMBER,
  RUNS_7D                      NUMBER,
  FAILURES_7D                  NUMBER,
  SUCCESSES_7D                 NUMBER,
  MAX_DURATION_SEC             NUMBER(18,2),
  LAST_RUN_AT                  TIMESTAMP_NTZ,
  BLAST_RADIUS                 VARCHAR(100),
  WAREHOUSES                   VARCHAR,
  PROCEDURES                   VARCHAR,
  OWNER_ROLE                   VARCHAR(300),
  APPROVAL_PATH                VARCHAR(1000),
  SOURCE_FRESHNESS             VARCHAR(1000),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS DIM_TASK_SNAPSHOT (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  DATABASE_NAME                VARCHAR(300),
  ENVIRONMENT                  VARCHAR(100),
  SCHEMA_NAME                  VARCHAR(300),
  TASK_NAME                    VARCHAR(500),
  ROOT_TASK_NAME               VARCHAR(500),
  STATE                        VARCHAR(100),
  SCHEDULE                     VARCHAR,
  WAREHOUSE_NAME               VARCHAR(300),
  PREDECESSORS                 VARIANT,
  DEFINITION                   VARCHAR,
  PROCEDURE_NAME               VARCHAR
);

CREATE TRANSIENT TABLE IF NOT EXISTS DIM_PROCEDURE_SNAPSHOT (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  DATABASE_NAME                VARCHAR(300),
  ENVIRONMENT                  VARCHAR(100),
  SCHEMA_NAME                  VARCHAR(300),
  PROCEDURE_NAME               VARCHAR(500),
  OWNER_ROLE                   VARCHAR(300),
  PROCEDURE_LANGUAGE           VARCHAR(100),
  ARGUMENT_SIGNATURE           VARCHAR,
  LAST_ALTERED                 TIMESTAMP_NTZ,
  IS_ORPHAN_CANDIDATE          BOOLEAN
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_PROCEDURE_RUN (
  START_TIME                   TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  DATABASE_NAME                VARCHAR(300),
  ENVIRONMENT                  VARCHAR(100),
  SCHEMA_NAME                  VARCHAR(300),
  PROCEDURE_NAME               VARCHAR(500),
  CALL_QUERY_ID                VARCHAR(200),
  ROOT_QUERY_ID                VARCHAR(200),
  CHILD_QUERY_COUNT            NUMBER,
  TOTAL_DURATION_MS            NUMBER,
  EST_CREDITS                  NUMBER(18,6),
  EST_COST_USD                 NUMBER(18,2),
  STATUS                       VARCHAR(100),
  ERROR_MESSAGE                VARCHAR,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_LOGIN_DAILY (
  LOGIN_DATE                   DATE,
  COMPANY                      VARCHAR(100),
  USER_NAME                    VARCHAR(300),
  CLIENT_IP                    VARCHAR(300),
  REPORTED_CLIENT_TYPE         VARCHAR(300),
  REPORTED_CLIENT_VERSION      VARCHAR(300),
  SUCCESS_COUNT                NUMBER,
  FAILURE_COUNT                NUMBER,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_OBJECT_CHANGE (
  START_TIME                   TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  QUERY_ID                     VARCHAR(200),
  USER_NAME                    VARCHAR(300),
  ROLE_NAME                    VARCHAR(300),
  DATABASE_NAME                VARCHAR(300),
  ENVIRONMENT                  VARCHAR(100),
  SCHEMA_NAME                  VARCHAR(300),
  CHANGE_CATEGORY              VARCHAR(100),
  QUERY_TYPE                   VARCHAR(100),
  QUERY_TAG                    VARCHAR,
  QUERY_TEXT                   VARCHAR,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_CHANGE_CONTROL_OPERABILITY_DAILY (
  SNAPSHOT_DATE                DATE,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  CONTROL_SOURCE               VARCHAR(80),
  CONTROL_KEY                  VARCHAR(500),
  FINDING_TYPE                 VARCHAR(120),
  ENTITY                       VARCHAR(500),
  OWNER                        VARCHAR(200),
  ESCALATION_TARGET            VARCHAR(200),
  SEVERITY                     VARCHAR(40),
  EVIDENCE_ROWS                NUMBER,
  HIGH_RISK_CHANGES            NUMBER,
  ROUTE_BLOCKED                NUMBER,
  CLOSURE_BLOCKED              NUMBER,
  REVIEW_READY                 NUMBER,
  MISSING_TICKET_ROWS          NUMBER,
  IAC_GAP_ROWS                 NUMBER,
  MISSING_QUERY_ID_ROWS        NUMBER,
  OPEN_ACTIONS                 NUMBER,
  OVERDUE_OPEN                 NUMBER,
  FIXED_WITHOUT_VERIFICATION   NUMBER,
  VERIFIED_CLOSURES            NUMBER,
  OWNER_APPROVAL_GAP_ROWS      NUMBER,
  CONTROL_STATE                VARCHAR(120),
  CONTROL_RANK                 NUMBER,
  NEXT_CONTROL_ACTION          VARCHAR(4000),
  LAST_ACTIVITY_TS             TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_GRANT_DAILY (
  SNAPSHOT_DATE                DATE,
  COMPANY                      VARCHAR(100),
  ROLE_NAME                    VARCHAR(300),
  GRANTEE_NAME                 VARCHAR(300),
  GRANTED_TO                   VARCHAR(100),
  CREATED_ON                   TIMESTAMP_NTZ,
  DELETED_ON                   TIMESTAMP_NTZ,
  GRANT_COUNT                  NUMBER,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

ALTER TABLE IF EXISTS FACT_GRANT_DAILY ADD COLUMN IF NOT EXISTS CREATED_ON TIMESTAMP_NTZ;


CREATE TRANSIENT TABLE IF NOT EXISTS FACT_STORAGE_DAILY (
  SNAPSHOT_DATE                DATE,
  COMPANY                      VARCHAR(100),
  DATABASE_NAME                VARCHAR(300),
  ENVIRONMENT                  VARCHAR(100),
  ACTIVE_BYTES                 NUMBER,
  TIME_TRAVEL_BYTES            NUMBER,
  FAILSAFE_BYTES               NUMBER,
  RETAINED_FOR_CLONE_BYTES     NUMBER,
  EST_STORAGE_TB               NUMBER(18,4),
  EST_COST_USD                 NUMBER(18,2),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS DIM_TABLE_SNAPSHOT (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  DATABASE_NAME                VARCHAR(300),
  ENVIRONMENT                  VARCHAR(100),
  SCHEMA_NAME                  VARCHAR(300),
  TABLE_NAME                   VARCHAR(500),
  TABLE_TYPE                   VARCHAR(100),
  ROW_COUNT                    NUMBER,
  BYTES                        NUMBER,
  LAST_ALTERED                 TIMESTAMP_LTZ,
  CREATED                      TIMESTAMP_LTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_COPY_LOAD_DAILY (
  LOAD_DATE                    DATE,
  COMPANY                      VARCHAR(100),
  DATABASE_NAME                VARCHAR(300),
  ENVIRONMENT                  VARCHAR(100),
  SCHEMA_NAME                  VARCHAR(300),
  TABLE_NAME                   VARCHAR(500),
  STATUS                       VARCHAR(100),
  FILE_COUNT                   NUMBER,
  ROW_COUNT                    NUMBER,
  ROW_PARSED                   NUMBER,
  ERROR_COUNT                  NUMBER,
  FILE_SIZE_BYTES              NUMBER,
  BYTES_BILLED                 NUMBER,
  LAST_SEEN                    TIMESTAMP_LTZ,
  LATEST_ERROR                 VARCHAR,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);


CREATE TRANSIENT TABLE IF NOT EXISTS FACT_CORTEX_DAILY (
  USAGE_DATE                   DATE,
  COMPANY                      VARCHAR(100),
  USER_ID                      VARCHAR(300),
  SOURCE                       VARCHAR(100),
  CREDITS_USED                 NUMBER(18,6),
  EST_COST_USD                 NUMBER(18,2),
  REQUEST_COUNT                NUMBER,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_MONITORING_COST_DAILY (
  USAGE_DATE                   DATE,
  COMPANY                      VARCHAR(100),
  COST_COMPONENT               VARCHAR(100),
  CREDITS_USED                 NUMBER(18,6),
  EST_COST_USD                 NUMBER(18,2),
  SOURCE                       VARCHAR(1000),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_COST_DAILY (
  USAGE_DATE                         DATE,
  COMPANY                            VARCHAR(100),
  SERVICE_CATEGORY                   VARCHAR(120),
  SERVICE_TYPE                       VARCHAR(200),
  CREDITS_USED_COMPUTE               NUMBER(18,6),
  CREDITS_USED_CLOUD_SERVICES        NUMBER(18,6),
  CREDITS_ADJUSTMENT_CLOUD_SERVICES  NUMBER(18,6),
  CREDITS_BILLED                     NUMBER(18,6),
  EST_COST_USD                       NUMBER(18,2),
  SOURCE_VIEW                        VARCHAR(300),
  LOAD_TS                            TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_COST_SOURCE_HEALTH_DAILY (
  SNAPSHOT_DATE                 DATE,
  SOURCE_NAME                   VARCHAR(200),
  SOURCE_SCOPE                  VARCHAR(200),
  STATUS                        VARCHAR(80),
  EXPECTED_LATENCY_HOURS        NUMBER,
  OBSERVED_ROWS                 NUMBER,
  LAST_DATA_DATE                DATE,
  ERROR_MESSAGE                 VARCHAR(4000),
  LOAD_TS                       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_COST_GOVERNANCE_SIGNAL (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  SIGNAL_TYPE                  VARCHAR(120),
  SEVERITY                     VARCHAR(40),
  ENTITY_TYPE                  VARCHAR(120),
  ENTITY_NAME                  VARCHAR(500),
  CONTROL_SURFACE              VARCHAR(200),
  CONTROL_SCOPE                VARCHAR(200),
  EVIDENCE                     VARCHAR(4000),
  NEXT_ACTION                  VARCHAR(4000),
  PROOF_QUERY                  VARCHAR(8000),
  VALUE_AT_RISK_USD            NUMBER(18,2),
  SOURCE                       VARCHAR(200),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_COST_INCIDENT_TIMELINE (
  INCIDENT_ID                  VARCHAR(200),
  EVENT_TS                     TIMESTAMP_NTZ,
  EVENT_ORDER                  NUMBER,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  ENTITY_NAME                  VARCHAR(500),
  EVENT_TYPE                   VARCHAR(160),
  SEVERITY                     VARCHAR(40),
  EVIDENCE                     VARCHAR(4000),
  NEXT_ACTION                  VARCHAR(4000),
  PROOF_QUERY                  VARCHAR(8000),
  SOURCE                       VARCHAR(200),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_DBA_CONTROL_ROOM (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  HEALTH_SCORE                 NUMBER(5,2),
  FAILED_QUERIES_24H           NUMBER,
  FAILED_TASKS_24H             NUMBER,
  QUEUED_MS_24H                NUMBER,
  CREDITS_24H                  NUMBER(18,6),
  COST_24H_USD                 NUMBER(18,2),
  CORTEX_COST_7D_USD           NUMBER(18,2),
  SECURITY_EVENTS_24H          NUMBER,
  OBJECT_CHANGES_24H           NUMBER,
  TOP_RISK                     VARCHAR(1000),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Existing installs may have been created before environment dimensions and
-- detailed query telemetry were added. CREATE TABLE IF NOT EXISTS will not
-- evolve those tables, so keep this upgrade block idempotent.
ALTER TABLE IF EXISTS FACT_QUERY_HOURLY ADD COLUMN IF NOT EXISTS WAREHOUSE_SIZE VARCHAR(100);
ALTER TABLE IF EXISTS FACT_QUERY_HOURLY ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);

ALTER TABLE IF EXISTS FACT_QUERY_DETAIL_RECENT ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS FACT_QUERY_DETAIL_RECENT ADD COLUMN IF NOT EXISTS WAREHOUSE_SIZE VARCHAR(100);
ALTER TABLE IF EXISTS FACT_QUERY_DETAIL_RECENT ADD COLUMN IF NOT EXISTS COMPILATION_TIME NUMBER;
ALTER TABLE IF EXISTS FACT_QUERY_DETAIL_RECENT ADD COLUMN IF NOT EXISTS EXECUTION_TIME NUMBER;
ALTER TABLE IF EXISTS FACT_QUERY_DETAIL_RECENT ADD COLUMN IF NOT EXISTS TRANSACTION_BLOCKED_TIME NUMBER;
ALTER TABLE IF EXISTS FACT_QUERY_DETAIL_RECENT ADD COLUMN IF NOT EXISTS BYTES_SPILLED_TO_LOCAL_STORAGE NUMBER;
ALTER TABLE IF EXISTS FACT_QUERY_DETAIL_RECENT ADD COLUMN IF NOT EXISTS PARTITIONS_SCANNED NUMBER;
ALTER TABLE IF EXISTS FACT_QUERY_DETAIL_RECENT ADD COLUMN IF NOT EXISTS PARTITIONS_TOTAL NUMBER;
ALTER TABLE IF EXISTS FACT_QUERY_DETAIL_RECENT ADD COLUMN IF NOT EXISTS ROWS_PRODUCED NUMBER;
ALTER TABLE IF EXISTS FACT_QUERY_DETAIL_RECENT ADD COLUMN IF NOT EXISTS QUERY_HASH VARCHAR(300);

ALTER TABLE IF EXISTS FACT_TASK_RUN ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS DIM_TASK_SNAPSHOT ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS DIM_PROCEDURE_SNAPSHOT ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS FACT_PROCEDURE_RUN ADD COLUMN IF NOT EXISTS DATABASE_NAME VARCHAR(300);
ALTER TABLE IF EXISTS FACT_PROCEDURE_RUN ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS FACT_PROCEDURE_RUN ADD COLUMN IF NOT EXISTS SCHEMA_NAME VARCHAR(300);
ALTER TABLE IF EXISTS FACT_OBJECT_CHANGE ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS FACT_OBJECT_CHANGE ADD COLUMN IF NOT EXISTS QUERY_TAG VARCHAR;
ALTER TABLE IF EXISTS FACT_STORAGE_DAILY ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS DIM_TABLE_SNAPSHOT ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS FACT_COPY_LOAD_DAILY ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS FACT_CHARGEBACK_DAILY ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS FACT_CHARGEBACK_DAILY ADD COLUMN IF NOT EXISTS ENVIRONMENT_ROLLUP VARCHAR(100);

-- -----------------------------------------------------------------------------
-- 4. Load procedures
-- -----------------------------------------------------------------------------

CREATE OR REPLACE PROCEDURE SP_OVERWATCH_PRUNE()
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
DECLARE
  detail_days NUMBER DEFAULT 30;
  agg_days NUMBER DEFAULT 730;
BEGIN
  SELECT TRY_TO_NUMBER(SETTING_VALUE) INTO :detail_days
  FROM OVERWATCH_SETTINGS
  WHERE SETTING_NAME = 'DETAIL_RETENTION_DAYS';

  SELECT TRY_TO_NUMBER(SETTING_VALUE) INTO :agg_days
  FROM OVERWATCH_SETTINGS
  WHERE SETTING_NAME = 'AGG_RETENTION_DAYS';

  detail_days := COALESCE(detail_days, 30);
  agg_days := COALESCE(agg_days, 730);

  DELETE FROM FACT_QUERY_DETAIL_RECENT WHERE START_TIME < DATEADD('DAY', -1 * :detail_days, CURRENT_TIMESTAMP());
  DELETE FROM FACT_TASK_RUN WHERE SCHEDULED_TIME < DATEADD('DAY', -1 * :detail_days, CURRENT_TIMESTAMP());
  DELETE FROM FACT_TASK_CRITICAL_PATH WHERE SNAPSHOT_TS < DATEADD('DAY', -1 * :detail_days, CURRENT_TIMESTAMP());
  DELETE FROM FACT_PROCEDURE_RUN WHERE START_TIME < DATEADD('DAY', -1 * :detail_days, CURRENT_TIMESTAMP());
  DELETE FROM FACT_WAREHOUSE_HOURLY WHERE HOUR_START < DATEADD('DAY', -1 * :agg_days, CURRENT_TIMESTAMP());
  DELETE FROM FACT_WAREHOUSE_OPERABILITY_DAILY WHERE SNAPSHOT_DATE < DATEADD('DAY', -1 * :agg_days, CURRENT_DATE());
  DELETE FROM FACT_SECURITY_OPERABILITY_DAILY WHERE SNAPSHOT_DATE < DATEADD('DAY', -1 * :agg_days, CURRENT_DATE());
  DELETE FROM FACT_ACCOUNT_HEALTH_OPERABILITY_DAILY WHERE SNAPSHOT_DATE < DATEADD('DAY', -1 * :agg_days, CURRENT_DATE());
  DELETE FROM FACT_QUERY_HOURLY WHERE HOUR_START < DATEADD('DAY', -1 * :agg_days, CURRENT_TIMESTAMP());
  DELETE FROM FACT_LOGIN_DAILY WHERE LOGIN_DATE < DATEADD('DAY', -1 * :agg_days, CURRENT_DATE());
  DELETE FROM FACT_OBJECT_CHANGE WHERE START_TIME < DATEADD('DAY', -1 * :agg_days, CURRENT_TIMESTAMP());
  DELETE FROM FACT_GRANT_DAILY WHERE SNAPSHOT_DATE < DATEADD('DAY', -1 * :agg_days, CURRENT_DATE());
  DELETE FROM FACT_STORAGE_DAILY WHERE SNAPSHOT_DATE < DATEADD('DAY', -1 * :agg_days, CURRENT_DATE());
  DELETE FROM FACT_CHARGEBACK_DAILY WHERE USAGE_DATE < DATEADD('DAY', -1 * :agg_days, CURRENT_DATE());
  DELETE FROM DIM_COST_OWNER_TAG WHERE SNAPSHOT_DATE < DATEADD('DAY', -1 * :agg_days, CURRENT_DATE());
  DELETE FROM DIM_TABLE_SNAPSHOT WHERE SNAPSHOT_TS < DATEADD('DAY', -1 * :agg_days, CURRENT_TIMESTAMP());
  DELETE FROM FACT_COPY_LOAD_DAILY WHERE LOAD_DATE < DATEADD('DAY', -1 * :agg_days, CURRENT_DATE());
  DELETE FROM FACT_CORTEX_DAILY WHERE USAGE_DATE < DATEADD('DAY', -1 * :agg_days, CURRENT_DATE());
  DELETE FROM FACT_MONITORING_COST_DAILY WHERE USAGE_DATE < DATEADD('DAY', -1 * :agg_days, CURRENT_DATE());
  DELETE FROM FACT_COST_DAILY WHERE USAGE_DATE < DATEADD('DAY', -1 * :agg_days, CURRENT_DATE());
  DELETE FROM FACT_COST_SOURCE_HEALTH_DAILY WHERE SNAPSHOT_DATE < DATEADD('DAY', -1 * :agg_days, CURRENT_DATE());
  DELETE FROM FACT_COST_GOVERNANCE_SIGNAL WHERE SNAPSHOT_TS < DATEADD('DAY', -1 * :agg_days, CURRENT_TIMESTAMP());
  DELETE FROM FACT_COST_INCIDENT_TIMELINE WHERE EVENT_TS < DATEADD('DAY', -1 * :agg_days, CURRENT_TIMESTAMP());

  RETURN 'OVERWATCH prune complete';
END;
$$;

CREATE OR REPLACE PROCEDURE SP_OVERWATCH_LOAD_HOURLY()
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
DECLARE
  credit_price NUMBER(18,4) DEFAULT 3.68;
  started_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP();
  rows_loaded NUMBER DEFAULT 0;
BEGIN
  SELECT TRY_TO_NUMBER(SETTING_VALUE) INTO :credit_price
  FROM OVERWATCH_SETTINGS
  WHERE SETTING_NAME = 'CREDIT_PRICE_USD';

  credit_price := COALESCE(credit_price, 3.68);

  INSERT INTO OVERWATCH_LOAD_AUDIT (LOAD_NAME, LOAD_STARTED_AT, STATUS, MESSAGE)
  VALUES ('SP_OVERWATCH_LOAD_HOURLY', :started_at, 'RUNNING', 'Started hourly mart load.');

  DELETE FROM FACT_WAREHOUSE_HOURLY
  WHERE HOUR_START >= DATEADD('DAY', -35, CURRENT_TIMESTAMP());

  INSERT INTO FACT_WAREHOUSE_HOURLY (
    HOUR_START, COMPANY, WAREHOUSE_NAME, CREDITS_USED,
    CREDITS_USED_COMPUTE, CREDITS_USED_CLOUD_SERVICES, EST_COST_USD
  )
  SELECT
    DATE_TRUNC('HOUR', START_TIME) AS HOUR_START,
    CASE WHEN WAREHOUSE_NAME ILIKE 'WH_TRXS_%' THEN 'Trexis' ELSE 'ALFA' END AS COMPANY,
    WAREHOUSE_NAME,
    SUM(CREDITS_USED) AS CREDITS_USED,
    SUM(CREDITS_USED_COMPUTE) AS CREDITS_USED_COMPUTE,
    SUM(CREDITS_USED_CLOUD_SERVICES) AS CREDITS_USED_CLOUD_SERVICES,
    ROUND(SUM(CREDITS_USED) * :credit_price, 2) AS EST_COST_USD
  FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
  WHERE START_TIME >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())
  GROUP BY 1, 2, 3;

  rows_loaded := rows_loaded + SQLROWCOUNT;

  DELETE FROM FACT_QUERY_HOURLY
  WHERE HOUR_START >= DATEADD('DAY', -35, CURRENT_TIMESTAMP());

  INSERT INTO FACT_QUERY_HOURLY (
    HOUR_START, COMPANY, WAREHOUSE_NAME, WAREHOUSE_SIZE, USER_NAME, ROLE_NAME, DATABASE_NAME,
    ENVIRONMENT, SCHEMA_NAME, QUERY_TYPE, QUERY_COUNT, FAILED_COUNT, AVG_EXECUTION_MS,
    P95_EXECUTION_MS, TOTAL_ELAPSED_MS, TOTAL_QUEUED_MS, TOTAL_SPILL_BYTES,
    TOTAL_BYTES_SCANNED
  )
  SELECT
    DATE_TRUNC('HOUR', START_TIME) AS HOUR_START,
    CASE
      WHEN WAREHOUSE_NAME ILIKE 'WH_TRXS_%' OR DATABASE_NAME ILIKE 'TRXS_%' OR USER_NAME ILIKE 'TRXS_%' THEN 'Trexis'
      ELSE 'ALFA'
    END AS COMPANY,
    WAREHOUSE_NAME,
    WAREHOUSE_SIZE,
    USER_NAME,
    ROLE_NAME,
    DATABASE_NAME,
    OVERWATCH_DATABASE_ENVIRONMENT(DATABASE_NAME) AS ENVIRONMENT,
    SCHEMA_NAME,
    QUERY_TYPE,
    COUNT(*) AS QUERY_COUNT,
    SUM(IFF(UPPER(COALESCE(EXECUTION_STATUS, '')) IN ('FAILED_WITH_ERROR', 'FAILED'), 1, 0)) AS FAILED_COUNT,
    AVG(TOTAL_ELAPSED_TIME) AS AVG_EXECUTION_MS,
    APPROX_PERCENTILE(TOTAL_ELAPSED_TIME, 0.95) AS P95_EXECUTION_MS,
    SUM(TOTAL_ELAPSED_TIME) AS TOTAL_ELAPSED_MS,
    SUM(COALESCE(QUEUED_OVERLOAD_TIME, 0) + COALESCE(QUEUED_PROVISIONING_TIME, 0) + COALESCE(QUEUED_REPAIR_TIME, 0)) AS TOTAL_QUEUED_MS,
    SUM(COALESCE(BYTES_SPILLED_TO_REMOTE_STORAGE, 0)) AS TOTAL_SPILL_BYTES,
    SUM(COALESCE(BYTES_SCANNED, 0)) AS TOTAL_BYTES_SCANNED
  FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
  WHERE START_TIME >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())
  GROUP BY 1,2,3,4,5,6,7,8,9,10;

  rows_loaded := rows_loaded + SQLROWCOUNT;

  DELETE FROM DIM_TASK_SNAPSHOT
  WHERE SNAPSHOT_TS >= DATEADD('HOUR', -2, CURRENT_TIMESTAMP());

  INSERT INTO DIM_TASK_SNAPSHOT (
    SNAPSHOT_TS, COMPANY, DATABASE_NAME, ENVIRONMENT, SCHEMA_NAME, TASK_NAME,
    ROOT_TASK_NAME, STATE, SCHEDULE, WAREHOUSE_NAME, PREDECESSORS,
    DEFINITION, PROCEDURE_NAME
  )
  SELECT
    CURRENT_TIMESTAMP() AS SNAPSHOT_TS,
    CASE WHEN TASK_DATABASE ILIKE 'TRXS_%' OR TASK_NAME ILIKE 'TRXS_%' THEN 'Trexis' ELSE 'ALFA' END AS COMPANY,
    TASK_DATABASE AS DATABASE_NAME,
    OVERWATCH_DATABASE_ENVIRONMENT(TASK_DATABASE) AS ENVIRONMENT,
    TASK_SCHEMA AS SCHEMA_NAME,
    TASK_NAME,
    IFF(COALESCE(ARRAY_SIZE(PREDECESSORS), 0) = 0, TASK_NAME, NULL) AS ROOT_TASK_NAME,
    STATE,
    SCHEDULE,
    WAREHOUSE AS WAREHOUSE_NAME,
    PREDECESSORS,
    DEFINITION,
    REGEXP_SUBSTR(DEFINITION, 'CALL[[:space:]]+([^[:space:];(]+)', 1, 1, 'ie', 1) AS PROCEDURE_NAME
  FROM SNOWFLAKE.ACCOUNT_USAGE.TASKS
  WHERE DELETED IS NULL;

  rows_loaded := rows_loaded + SQLROWCOUNT;

  DELETE FROM DIM_PROCEDURE_SNAPSHOT
  WHERE SNAPSHOT_TS >= DATEADD('HOUR', -2, CURRENT_TIMESTAMP());

  INSERT INTO DIM_PROCEDURE_SNAPSHOT (
    SNAPSHOT_TS, COMPANY, DATABASE_NAME, ENVIRONMENT, SCHEMA_NAME, PROCEDURE_NAME,
    OWNER_ROLE, PROCEDURE_LANGUAGE, ARGUMENT_SIGNATURE, LAST_ALTERED, IS_ORPHAN_CANDIDATE
  )
  WITH recent_calls AS (
    SELECT DISTINCT UPPER(COALESCE(PROCEDURE_NAME, '')) AS PROCEDURE_NAME
    FROM FACT_PROCEDURE_RUN
    WHERE START_TIME >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())
  )
  SELECT
    CURRENT_TIMESTAMP() AS SNAPSHOT_TS,
    CASE WHEN p.PROCEDURE_CATALOG ILIKE 'TRXS_%' OR p.PROCEDURE_NAME ILIKE 'TRXS_%' THEN 'Trexis' ELSE 'ALFA' END AS COMPANY,
    p.PROCEDURE_CATALOG AS DATABASE_NAME,
    OVERWATCH_DATABASE_ENVIRONMENT(p.PROCEDURE_CATALOG) AS ENVIRONMENT,
    p.PROCEDURE_SCHEMA AS SCHEMA_NAME,
    p.PROCEDURE_NAME,
    p.PROCEDURE_OWNER AS OWNER_ROLE,
    p.PROCEDURE_LANGUAGE AS PROCEDURE_LANGUAGE,
    p.ARGUMENT_SIGNATURE,
    p.LAST_ALTERED,
    IFF(rc.PROCEDURE_NAME IS NULL, TRUE, FALSE) AS IS_ORPHAN_CANDIDATE
  FROM SNOWFLAKE.ACCOUNT_USAGE.PROCEDURES p
  LEFT JOIN recent_calls rc
    ON rc.PROCEDURE_NAME ILIKE '%' || UPPER(p.PROCEDURE_NAME) || '%'
  WHERE p.DELETED IS NULL;

  rows_loaded := rows_loaded + SQLROWCOUNT;

  DELETE FROM FACT_QUERY_DETAIL_RECENT
  WHERE START_TIME >= DATEADD('DAY', -30, CURRENT_TIMESTAMP());

  INSERT INTO FACT_QUERY_DETAIL_RECENT (
    QUERY_ID, START_TIME, END_TIME, COMPANY, WAREHOUSE_NAME, USER_NAME, ROLE_NAME,
    DATABASE_NAME, ENVIRONMENT, SCHEMA_NAME, QUERY_TYPE, EXECUTION_STATUS, ERROR_CODE,
    ERROR_MESSAGE, TOTAL_ELAPSED_TIME, COMPILATION_TIME, EXECUTION_TIME,
    QUEUED_OVERLOAD_TIME, QUEUED_PROVISIONING_TIME, QUEUED_REPAIR_TIME,
    TRANSACTION_BLOCKED_TIME, BYTES_SCANNED, BYTES_SPILLED_TO_LOCAL_STORAGE,
    BYTES_SPILLED_TO_REMOTE_STORAGE, PARTITIONS_SCANNED, PARTITIONS_TOTAL,
    ROWS_PRODUCED, QUERY_HASH, WAREHOUSE_SIZE, QUERY_TEXT, QUERY_TAG
  )
  SELECT
    QUERY_ID,
    START_TIME,
    END_TIME,
    CASE
      WHEN WAREHOUSE_NAME ILIKE 'WH_TRXS_%' OR DATABASE_NAME ILIKE 'TRXS_%' OR USER_NAME ILIKE 'TRXS_%' THEN 'Trexis'
      ELSE 'ALFA'
    END AS COMPANY,
    WAREHOUSE_NAME,
    USER_NAME,
    ROLE_NAME,
    DATABASE_NAME,
    OVERWATCH_DATABASE_ENVIRONMENT(DATABASE_NAME) AS ENVIRONMENT,
    SCHEMA_NAME,
    QUERY_TYPE,
    EXECUTION_STATUS,
    ERROR_CODE,
    ERROR_MESSAGE,
    TOTAL_ELAPSED_TIME,
    COMPILATION_TIME,
    EXECUTION_TIME,
    QUEUED_OVERLOAD_TIME,
    QUEUED_PROVISIONING_TIME,
    QUEUED_REPAIR_TIME,
    TRANSACTION_BLOCKED_TIME,
    BYTES_SCANNED,
    BYTES_SPILLED_TO_LOCAL_STORAGE,
    BYTES_SPILLED_TO_REMOTE_STORAGE,
    PARTITIONS_SCANNED,
    PARTITIONS_TOTAL,
    ROWS_PRODUCED,
    QUERY_HASH,
    WAREHOUSE_SIZE,
    QUERY_TEXT,
    QUERY_TAG
  FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
  WHERE START_TIME >= DATEADD('DAY', -30, CURRENT_TIMESTAMP())
    AND (
      UPPER(COALESCE(EXECUTION_STATUS, '')) IN ('FAILED_WITH_ERROR', 'FAILED')
      OR COALESCE(TOTAL_ELAPSED_TIME, 0) >= 300000
      OR COALESCE(QUEUED_OVERLOAD_TIME, 0) + COALESCE(QUEUED_PROVISIONING_TIME, 0) + COALESCE(QUEUED_REPAIR_TIME, 0) > 0
      OR COALESCE(BYTES_SPILLED_TO_REMOTE_STORAGE, 0) > 0
      OR QUERY_TAG ILIKE 'OVERWATCH:%'
    );

  rows_loaded := rows_loaded + SQLROWCOUNT;

  DELETE FROM FACT_OBJECT_CHANGE
  WHERE START_TIME >= DATEADD('DAY', -35, CURRENT_TIMESTAMP());

  INSERT INTO FACT_OBJECT_CHANGE (
    START_TIME, COMPANY, QUERY_ID, USER_NAME, ROLE_NAME, DATABASE_NAME,
    ENVIRONMENT, SCHEMA_NAME, CHANGE_CATEGORY, QUERY_TYPE, QUERY_TAG, QUERY_TEXT
  )
  SELECT
    START_TIME,
    CASE
      WHEN DATABASE_NAME ILIKE 'TRXS_%' OR USER_NAME ILIKE 'TRXS_%' THEN 'Trexis'
      ELSE 'ALFA'
    END AS COMPANY,
    QUERY_ID,
    USER_NAME,
    ROLE_NAME,
    DATABASE_NAME,
    OVERWATCH_DATABASE_ENVIRONMENT(DATABASE_NAME) AS ENVIRONMENT,
    SCHEMA_NAME,
    CASE
      WHEN QUERY_TEXT ILIKE 'GRANT%' OR QUERY_TEXT ILIKE 'REVOKE%' THEN 'GRANT'
      WHEN QUERY_TEXT ILIKE '%MASKING POLICY%' OR QUERY_TEXT ILIKE '%ROW ACCESS POLICY%' OR QUERY_TEXT ILIKE '% TAG %' THEN 'POLICY'
      WHEN QUERY_TEXT ILIKE '%OWNERSHIP%' THEN 'OWNER'
      WHEN QUERY_TEXT ILIKE 'DROP%' THEN 'DROP'
      WHEN QUERY_TEXT ILIKE 'ALTER%' THEN 'ALTER'
      WHEN QUERY_TEXT ILIKE 'CREATE%' THEN 'CREATE'
      ELSE 'OTHER'
    END AS CHANGE_CATEGORY,
    QUERY_TYPE,
    QUERY_TAG,
    QUERY_TEXT
  FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
  WHERE START_TIME >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())
    AND (
      QUERY_TEXT ILIKE 'CREATE%'
      OR QUERY_TEXT ILIKE 'ALTER%'
      OR QUERY_TEXT ILIKE 'DROP%'
      OR QUERY_TEXT ILIKE 'GRANT%'
      OR QUERY_TEXT ILIKE 'REVOKE%'
    );

  rows_loaded := rows_loaded + SQLROWCOUNT;

  BEGIN
    DELETE FROM FACT_TASK_RUN
    WHERE SCHEDULED_TIME >= DATEADD('DAY', -30, CURRENT_TIMESTAMP());

    INSERT INTO FACT_TASK_RUN (
      SCHEDULED_TIME, COMPLETED_TIME, COMPANY, DATABASE_NAME, ENVIRONMENT, SCHEMA_NAME,
      ROOT_TASK_NAME, TASK_NAME, STATE, QUERY_ID, ERROR_CODE, ERROR_MESSAGE,
      DURATION_MS, WAREHOUSE_NAME
    )
    SELECT
      SCHEDULED_TIME,
      COMPLETED_TIME,
      CASE WHEN DATABASE_NAME ILIKE 'TRXS_%' THEN 'Trexis' ELSE 'ALFA' END AS COMPANY,
      h.DATABASE_NAME,
      OVERWATCH_DATABASE_ENVIRONMENT(h.DATABASE_NAME) AS ENVIRONMENT,
      h.SCHEMA_NAME,
      COALESCE(root_task.TASK_NAME, h.NAME) AS ROOT_TASK_NAME,
      h.NAME AS TASK_NAME,
      h.STATE,
      h.QUERY_ID,
      h.ERROR_CODE,
      h.ERROR_MESSAGE,
      DATEDIFF('MILLISECOND', h.SCHEDULED_TIME, h.COMPLETED_TIME) AS DURATION_MS,
      NULL::VARCHAR AS WAREHOUSE_NAME
    FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY h
    LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.TASKS root_task
      ON h.ROOT_TASK_ID = root_task.ID
    WHERE h.SCHEDULED_TIME >= DATEADD('DAY', -30, CURRENT_TIMESTAMP());

    rows_loaded := rows_loaded + SQLROWCOUNT;
  EXCEPTION
    WHEN OTHER THEN
      INSERT INTO OVERWATCH_LOAD_AUDIT (LOAD_NAME, LOAD_STARTED_AT, LOAD_FINISHED_AT, STATUS, MESSAGE)
      VALUES ('FACT_TASK_RUN', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), 'SKIPPED', :SQLERRM);
  END;

  BEGIN
    DELETE FROM FACT_TASK_CRITICAL_PATH
    WHERE SNAPSHOT_TS >= DATEADD('HOUR', -2, CURRENT_TIMESTAMP());

    INSERT INTO FACT_TASK_CRITICAL_PATH (
      SNAPSHOT_TS, COMPANY, DATABASE_NAME, ENVIRONMENT, ROOT_TASK_NAME,
      CRITICAL_PATH_STATE, CRITICAL_PATH_SCORE, TASK_COUNT, DOWNSTREAM_TASK_COUNT,
      SUSPENDED_TASKS, RUNS_7D, FAILURES_7D, SUCCESSES_7D, MAX_DURATION_SEC,
      LAST_RUN_AT, BLAST_RADIUS, WAREHOUSES, PROCEDURES, OWNER_ROLE,
      APPROVAL_PATH, SOURCE_FRESHNESS
    )
    WITH RECURSIVE latest AS (
      SELECT MAX(SNAPSHOT_TS) AS SNAPSHOT_TS
      FROM DIM_TASK_SNAPSHOT
    ),
    tasks AS (
      SELECT
        t.SNAPSHOT_TS,
        t.COMPANY,
        t.DATABASE_NAME,
        t.ENVIRONMENT,
        t.SCHEMA_NAME,
        t.TASK_NAME,
        COALESCE(t.ROOT_TASK_NAME, t.TASK_NAME) AS ROOT_TASK_NAME,
        t.STATE,
        t.WAREHOUSE_NAME,
        t.PREDECESSORS,
        t.PROCEDURE_NAME
      FROM DIM_TASK_SNAPSHOT t
      JOIN latest l ON t.SNAPSHOT_TS = l.SNAPSHOT_TS
    ),
    edges AS (
      SELECT
        child.COMPANY,
        child.DATABASE_NAME,
        child.SCHEMA_NAME,
        child.TASK_NAME,
        SPLIT_PART(REPLACE(pred.value::string, '"', ''), '.', -1) AS PREDECESSOR_NAME
      FROM tasks child,
           LATERAL FLATTEN(input => child.PREDECESSORS) pred
      WHERE SPLIT_PART(REPLACE(pred.value::string, '"', ''), '.', -1) IS NOT NULL
    ),
    roots AS (
      SELECT *
      FROM tasks
      WHERE COALESCE(ARRAY_SIZE(PREDECESSORS), 0) = 0
    ),
    walk (COMPANY, DATABASE_NAME, ENVIRONMENT, ROOT_TASK_NAME, TASK_NAME, DEPTH) AS (
      SELECT COMPANY, DATABASE_NAME, ENVIRONMENT, TASK_NAME, TASK_NAME, 0
      FROM roots
      UNION ALL
      SELECT
        w.COMPANY,
        w.DATABASE_NAME,
        w.ENVIRONMENT,
        w.ROOT_TASK_NAME,
        e.TASK_NAME,
        w.DEPTH + 1
      FROM walk w
      JOIN edges e
        ON e.COMPANY = w.COMPANY
       AND e.DATABASE_NAME = w.DATABASE_NAME
       AND UPPER(e.PREDECESSOR_NAME) = UPPER(w.TASK_NAME)
      WHERE w.DEPTH < 20
    ),
    task_roots AS (
      SELECT
        t.*,
        COALESCE(w.ROOT_TASK_NAME, t.ROOT_TASK_NAME, t.TASK_NAME) AS RESOLVED_ROOT_TASK_NAME
      FROM tasks t
      LEFT JOIN walk w
        ON w.COMPANY = t.COMPANY
       AND w.DATABASE_NAME = t.DATABASE_NAME
       AND UPPER(w.TASK_NAME) = UPPER(t.TASK_NAME)
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY t.COMPANY, t.DATABASE_NAME, t.SCHEMA_NAME, t.TASK_NAME
        ORDER BY w.DEPTH DESC NULLS LAST
      ) = 1
    ),
    graph_summary AS (
      SELECT
        CURRENT_TIMESTAMP() AS SNAPSHOT_TS,
        COMPANY,
        DATABASE_NAME,
        MAX(ENVIRONMENT) AS ENVIRONMENT,
        RESOLVED_ROOT_TASK_NAME AS ROOT_TASK_NAME,
        COUNT(DISTINCT TASK_NAME) AS TASK_COUNT,
        GREATEST(COUNT(DISTINCT TASK_NAME) - 1, 0) AS DOWNSTREAM_TASK_COUNT,
        SUM(IFF(UPPER(COALESCE(STATE, '')) = 'SUSPENDED', 1, 0)) AS SUSPENDED_TASKS,
        LISTAGG(DISTINCT WAREHOUSE_NAME, ', ') WITHIN GROUP (ORDER BY WAREHOUSE_NAME) AS WAREHOUSES,
        LISTAGG(DISTINCT PROCEDURE_NAME, ', ') WITHIN GROUP (ORDER BY PROCEDURE_NAME) AS PROCEDURES
      FROM task_roots
      GROUP BY COMPANY, DATABASE_NAME, RESOLVED_ROOT_TASK_NAME
    ),
    hist_with_root AS (
      SELECT
        h.COMPANY,
        h.DATABASE_NAME,
        h.ENVIRONMENT,
        COALESCE(tr.RESOLVED_ROOT_TASK_NAME, h.ROOT_TASK_NAME, h.TASK_NAME) AS ROOT_TASK_NAME,
        h.TASK_NAME,
        h.STATE,
        h.SCHEDULED_TIME,
        h.DURATION_MS
      FROM FACT_TASK_RUN h
      LEFT JOIN task_roots tr
        ON tr.COMPANY = h.COMPANY
       AND tr.DATABASE_NAME = h.DATABASE_NAME
       AND tr.SCHEMA_NAME = h.SCHEMA_NAME
       AND UPPER(tr.TASK_NAME) = UPPER(h.TASK_NAME)
      WHERE h.SCHEDULED_TIME >= DATEADD('DAY', -7, CURRENT_TIMESTAMP())
    ),
    hist_summary AS (
      SELECT
        COMPANY,
        DATABASE_NAME,
        MAX(ENVIRONMENT) AS ENVIRONMENT,
        ROOT_TASK_NAME,
        COUNT(*) AS RUNS_7D,
        SUM(IFF(UPPER(COALESCE(STATE, '')) IN ('FAILED', 'FAILED_WITH_ERROR'), 1, 0)) AS FAILURES_7D,
        SUM(IFF(UPPER(COALESCE(STATE, '')) IN ('SUCCEEDED', 'SUCCESS', 'COMPLETED'), 1, 0)) AS SUCCESSES_7D,
        ROUND(MAX(COALESCE(DURATION_MS, 0)) / 1000, 2) AS MAX_DURATION_SEC,
        MAX(SCHEDULED_TIME) AS LAST_RUN_AT
      FROM hist_with_root
      GROUP BY COMPANY, DATABASE_NAME, ROOT_TASK_NAME
    ),
    scored AS (
      SELECT
        g.SNAPSHOT_TS,
        g.COMPANY,
        g.DATABASE_NAME,
        COALESCE(g.ENVIRONMENT, h.ENVIRONMENT, 'No Database Context') AS ENVIRONMENT,
        g.ROOT_TASK_NAME,
        g.TASK_COUNT,
        g.DOWNSTREAM_TASK_COUNT,
        g.SUSPENDED_TASKS,
        COALESCE(h.RUNS_7D, 0) AS RUNS_7D,
        COALESCE(h.FAILURES_7D, 0) AS FAILURES_7D,
        COALESCE(h.SUCCESSES_7D, 0) AS SUCCESSES_7D,
        COALESCE(h.MAX_DURATION_SEC, 0) AS MAX_DURATION_SEC,
        h.LAST_RUN_AT,
        CASE
          WHEN g.DOWNSTREAM_TASK_COUNT >= 5 THEN 'High'
          WHEN g.DOWNSTREAM_TASK_COUNT >= 1 THEN 'Medium'
          ELSE 'Local'
        END AS BLAST_RADIUS,
        g.WAREHOUSES,
        g.PROCEDURES,
        ROUND(
          COALESCE(h.FAILURES_7D, 0) * 12
          + COALESCE(g.SUSPENDED_TASKS, 0) * 10
          + COALESCE(g.DOWNSTREAM_TASK_COUNT, 0) * 5
          + LEAST(COALESCE(h.MAX_DURATION_SEC, 0) / 300, 20),
          1
        ) AS CRITICAL_PATH_SCORE
      FROM graph_summary g
      LEFT JOIN hist_summary h
        ON h.COMPANY = g.COMPANY
       AND h.DATABASE_NAME = g.DATABASE_NAME
       AND h.ROOT_TASK_NAME = g.ROOT_TASK_NAME
    )
    SELECT
      SNAPSHOT_TS,
      COMPANY,
      DATABASE_NAME,
      ENVIRONMENT,
      ROOT_TASK_NAME,
      CASE
        WHEN FAILURES_7D > 0 OR SUSPENDED_TASKS > 0 THEN 'Incident Path'
        WHEN DOWNSTREAM_TASK_COUNT >= 3 OR MAX_DURATION_SEC >= 900 THEN 'Watch Path'
        ELSE 'Stable Path'
      END AS CRITICAL_PATH_STATE,
      CRITICAL_PATH_SCORE,
      TASK_COUNT,
      DOWNSTREAM_TASK_COUNT,
      SUSPENDED_TASKS,
      RUNS_7D,
      FAILURES_7D,
      SUCCESSES_7D,
      MAX_DURATION_SEC,
      LAST_RUN_AT,
      BLAST_RADIUS,
      WAREHOUSES,
      PROCEDURES,
      'DBA / Pipeline Owner' AS OWNER_ROLE,
      CASE
        WHEN FAILURES_7D > 0 OR SUSPENDED_TASKS > 0
          THEN 'Owner approval required before retry or recovery.'
        WHEN DOWNSTREAM_TASK_COUNT >= 3
          THEN 'Owner review required before graph-level changes.'
        ELSE 'Standard DBA review.'
      END AS APPROVAL_PATH,
      'Latest DIM_TASK_SNAPSHOT plus 7-day FACT_TASK_RUN history.' AS SOURCE_FRESHNESS
    FROM scored;

    rows_loaded := rows_loaded + SQLROWCOUNT;
  EXCEPTION
    WHEN OTHER THEN
      INSERT INTO OVERWATCH_LOAD_AUDIT (LOAD_NAME, LOAD_STARTED_AT, LOAD_FINISHED_AT, STATUS, MESSAGE)
      VALUES ('FACT_TASK_CRITICAL_PATH', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), 'SKIPPED', :SQLERRM);
  END;

  DELETE FROM FACT_PROCEDURE_RUN
  WHERE START_TIME >= DATEADD('DAY', -30, CURRENT_TIMESTAMP());

  INSERT INTO FACT_PROCEDURE_RUN (
    START_TIME, COMPANY, DATABASE_NAME, ENVIRONMENT, SCHEMA_NAME, PROCEDURE_NAME, CALL_QUERY_ID, ROOT_QUERY_ID,
    CHILD_QUERY_COUNT, TOTAL_DURATION_MS, EST_CREDITS, EST_COST_USD, STATUS, ERROR_MESSAGE
  )
  SELECT
    q.START_TIME,
    CASE
      WHEN q.WAREHOUSE_NAME ILIKE 'WH_TRXS_%' OR q.DATABASE_NAME ILIKE 'TRXS_%' OR q.USER_NAME ILIKE 'TRXS_%' THEN 'Trexis'
      ELSE 'ALFA'
    END AS COMPANY,
    q.DATABASE_NAME,
    OVERWATCH_DATABASE_ENVIRONMENT(q.DATABASE_NAME) AS ENVIRONMENT,
    q.SCHEMA_NAME,
    REGEXP_SUBSTR(q.QUERY_TEXT, 'CALL[[:space:]]+([^[:space:];(]+)', 1, 1, 'ie', 1) AS PROCEDURE_NAME,
    q.QUERY_ID AS CALL_QUERY_ID,
    NULL::VARCHAR AS ROOT_QUERY_ID,
    0 AS CHILD_QUERY_COUNT,
    q.TOTAL_ELAPSED_TIME AS TOTAL_DURATION_MS,
    NULL::NUMBER(18,6) AS EST_CREDITS,
    NULL::NUMBER(18,2) AS EST_COST_USD,
    q.EXECUTION_STATUS AS STATUS,
    q.ERROR_MESSAGE
  FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
  WHERE q.START_TIME >= DATEADD('DAY', -30, CURRENT_TIMESTAMP())
    AND UPPER(COALESCE(q.QUERY_TYPE, '')) = 'CALL';

  rows_loaded := rows_loaded + SQLROWCOUNT;

  UPDATE OVERWATCH_LOAD_AUDIT
  SET LOAD_FINISHED_AT = CURRENT_TIMESTAMP(),
      STATUS = 'SUCCEEDED',
      ROWS_LOADED = :rows_loaded,
      MESSAGE = 'Hourly mart load complete.'
  WHERE LOAD_NAME = 'SP_OVERWATCH_LOAD_HOURLY'
    AND LOAD_STARTED_AT = :started_at;

  RETURN 'OVERWATCH hourly mart load complete: ' || rows_loaded || ' rows.';

EXCEPTION
  WHEN OTHER THEN
    UPDATE OVERWATCH_LOAD_AUDIT
    SET LOAD_FINISHED_AT = CURRENT_TIMESTAMP(),
        STATUS = 'FAILED',
        MESSAGE = :SQLERRM
    WHERE LOAD_NAME = 'SP_OVERWATCH_LOAD_HOURLY'
      AND LOAD_STARTED_AT = :started_at;
    RAISE;
END;
$$;

CREATE OR REPLACE PROCEDURE SP_OVERWATCH_LOAD_DAILY()
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
DECLARE
  credit_price NUMBER(18,4) DEFAULT 3.68;
  started_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP();
  rows_loaded NUMBER DEFAULT 0;
BEGIN
  SELECT TRY_TO_NUMBER(SETTING_VALUE) INTO :credit_price
  FROM OVERWATCH_SETTINGS
  WHERE SETTING_NAME = 'CREDIT_PRICE_USD';

  credit_price := COALESCE(credit_price, 3.68);

  INSERT INTO OVERWATCH_LOAD_AUDIT (LOAD_NAME, LOAD_STARTED_AT, STATUS, MESSAGE)
  VALUES ('SP_OVERWATCH_LOAD_DAILY', :started_at, 'RUNNING', 'Started daily mart load.');

  BEGIN
    DELETE FROM FACT_COST_DAILY
    WHERE USAGE_DATE >= DATEADD('DAY', -35, CURRENT_DATE());

    INSERT INTO FACT_COST_DAILY (
      USAGE_DATE, COMPANY, SERVICE_CATEGORY, SERVICE_TYPE,
      CREDITS_USED_COMPUTE, CREDITS_USED_CLOUD_SERVICES,
      CREDITS_ADJUSTMENT_CLOUD_SERVICES, CREDITS_BILLED,
      EST_COST_USD, SOURCE_VIEW
    )
    SELECT
      USAGE_DATE,
      'Account-Wide' AS COMPANY,
      CASE
        WHEN UPPER(COALESCE(SERVICE_TYPE, 'UNKNOWN')) ILIKE '%CORTEX%'
          OR UPPER(COALESCE(SERVICE_TYPE, 'UNKNOWN')) ILIKE '%AI%'
          OR UPPER(COALESCE(SERVICE_TYPE, 'UNKNOWN')) ILIKE '%INTELLIGENCE%'
          THEN 'AI / Cortex'
        WHEN UPPER(COALESCE(SERVICE_TYPE, 'UNKNOWN')) IN (
          'AUTOMATIC_CLUSTERING', 'COPY_FILES', 'MATERIALIZED_VIEW',
          'QUERY_ACCELERATION', 'SEARCH_OPTIMIZATION', 'SERVERLESS_ALERTS',
          'SERVERLESS_TASK', 'SNOWPIPE', 'SNOWPIPE_STREAMING',
          'SNOWPARK_CONTAINER_SERVICES', 'REPLICATION'
        )
          THEN 'Serverless / Managed Compute'
        WHEN UPPER(COALESCE(SERVICE_TYPE, 'UNKNOWN')) ILIKE '%STORAGE%' THEN 'Storage'
        WHEN UPPER(COALESCE(SERVICE_TYPE, 'UNKNOWN')) ILIKE '%DATA_TRANSFER%'
          OR UPPER(COALESCE(SERVICE_TYPE, 'UNKNOWN')) ILIKE '%PRIVATELINK%'
          THEN 'Data Transfer / Network'
        WHEN UPPER(COALESCE(SERVICE_TYPE, 'UNKNOWN')) = 'WAREHOUSE_METERING' THEN 'Warehouse'
        ELSE 'Other'
      END AS SERVICE_CATEGORY,
      UPPER(COALESCE(SERVICE_TYPE, 'UNKNOWN')) AS SERVICE_TYPE,
      ROUND(SUM(COALESCE(CREDITS_USED_COMPUTE, 0)), 6) AS CREDITS_USED_COMPUTE,
      ROUND(SUM(COALESCE(CREDITS_USED_CLOUD_SERVICES, 0)), 6) AS CREDITS_USED_CLOUD_SERVICES,
      ROUND(SUM(COALESCE(CREDITS_ADJUSTMENT_CLOUD_SERVICES, 0)), 6) AS CREDITS_ADJUSTMENT_CLOUD_SERVICES,
      ROUND(SUM(COALESCE(CREDITS_BILLED, 0)), 6) AS CREDITS_BILLED,
      ROUND(SUM(COALESCE(CREDITS_BILLED, 0)) * :credit_price, 2) AS EST_COST_USD,
      'SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY' AS SOURCE_VIEW
    FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
    WHERE USAGE_DATE >= DATEADD('DAY', -35, CURRENT_DATE())
      AND USAGE_DATE < CURRENT_DATE()
    GROUP BY 1,2,3,4;

    rows_loaded := rows_loaded + SQLROWCOUNT;
  EXCEPTION
    WHEN OTHER THEN
      INSERT INTO OVERWATCH_LOAD_AUDIT (LOAD_NAME, LOAD_STARTED_AT, LOAD_FINISHED_AT, STATUS, MESSAGE)
      VALUES ('FACT_COST_DAILY', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), 'SKIPPED', :SQLERRM);
  END;

  BEGIN
    DELETE FROM FACT_COST_SOURCE_HEALTH_DAILY
    WHERE SNAPSHOT_DATE = CURRENT_DATE();

    INSERT INTO FACT_COST_SOURCE_HEALTH_DAILY (
      SNAPSHOT_DATE, SOURCE_NAME, SOURCE_SCOPE, STATUS, EXPECTED_LATENCY_HOURS,
      OBSERVED_ROWS, LAST_DATA_DATE, ERROR_MESSAGE
    )
    SELECT
      CURRENT_DATE(),
      'WAREHOUSE_METERING_HISTORY',
      'Account Usage - warehouse metering',
      IFF(COUNT(*) > 0, 'Ready', 'No Recent Rows'),
      24,
      COUNT(*),
      MAX(TO_DATE(START_TIME)),
      NULL::VARCHAR
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
    WHERE START_TIME >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())

    UNION ALL

    SELECT
      CURRENT_DATE(),
      'METERING_DAILY_HISTORY',
      'Account Usage - billed service costs',
      IFF(COUNT(*) > 0, 'Ready', 'No Recent Rows'),
      24,
      COUNT(*),
      MAX(USAGE_DATE),
      NULL::VARCHAR
    FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
    WHERE USAGE_DATE >= DATEADD('DAY', -35, CURRENT_DATE())

    UNION ALL

    SELECT
      CURRENT_DATE(),
      'FACT_COST_DAILY',
      'OVERWATCH mart - service cost lens',
      IFF(COUNT(*) > 0, 'Ready', 'No Recent Rows'),
      24,
      COUNT(*),
      MAX(USAGE_DATE),
      NULL::VARCHAR
    FROM FACT_COST_DAILY
    WHERE USAGE_DATE >= DATEADD('DAY', -35, CURRENT_DATE());

    rows_loaded := rows_loaded + SQLROWCOUNT;
  EXCEPTION
    WHEN OTHER THEN
      INSERT INTO OVERWATCH_LOAD_AUDIT (LOAD_NAME, LOAD_STARTED_AT, LOAD_FINISHED_AT, STATUS, MESSAGE)
      VALUES ('FACT_COST_SOURCE_HEALTH_DAILY', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), 'SKIPPED', :SQLERRM);
  END;

  DELETE FROM FACT_LOGIN_DAILY
  WHERE LOGIN_DATE >= DATEADD('DAY', -35, CURRENT_DATE());

  INSERT INTO FACT_LOGIN_DAILY (
    LOGIN_DATE, COMPANY, USER_NAME, CLIENT_IP, REPORTED_CLIENT_TYPE,
    REPORTED_CLIENT_VERSION, SUCCESS_COUNT, FAILURE_COUNT
  )
  SELECT
    TO_DATE(EVENT_TIMESTAMP) AS LOGIN_DATE,
    CASE WHEN USER_NAME ILIKE 'TRXS_%' THEN 'Trexis' ELSE 'ALFA' END AS COMPANY,
    USER_NAME,
    CLIENT_IP,
    REPORTED_CLIENT_TYPE,
    REPORTED_CLIENT_VERSION,
    SUM(IFF(IS_SUCCESS = 'YES', 1, 0)) AS SUCCESS_COUNT,
    SUM(IFF(IS_SUCCESS = 'NO', 1, 0)) AS FAILURE_COUNT
  FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
  WHERE EVENT_TIMESTAMP >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())
  GROUP BY 1,2,3,4,5,6;

  rows_loaded := rows_loaded + SQLROWCOUNT;

  DELETE FROM FACT_GRANT_DAILY
  WHERE SNAPSHOT_DATE = CURRENT_DATE();

  INSERT INTO FACT_GRANT_DAILY (
    SNAPSHOT_DATE, COMPANY, ROLE_NAME, GRANTEE_NAME, GRANTED_TO, CREATED_ON, DELETED_ON, GRANT_COUNT
  )
  SELECT
    CURRENT_DATE() AS SNAPSHOT_DATE,
    CASE WHEN "ROLE" ILIKE 'TRXS_%' OR GRANTEE_NAME ILIKE 'TRXS_%' THEN 'Trexis' ELSE 'ALFA' END AS COMPANY,
    "ROLE" AS ROLE_NAME,
    GRANTEE_NAME,
    GRANTED_TO,
    CREATED_ON,
    DELETED_ON,
    COUNT(*) AS GRANT_COUNT
  FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS
  GROUP BY 1,2,3,4,5,6,7;

  rows_loaded := rows_loaded + SQLROWCOUNT;

  DELETE FROM FACT_STORAGE_DAILY
  WHERE SNAPSHOT_DATE >= DATEADD('DAY', -35, CURRENT_DATE());

  INSERT INTO FACT_STORAGE_DAILY (
    SNAPSHOT_DATE, COMPANY, DATABASE_NAME, ENVIRONMENT, ACTIVE_BYTES, TIME_TRAVEL_BYTES,
    FAILSAFE_BYTES, RETAINED_FOR_CLONE_BYTES, EST_STORAGE_TB, EST_COST_USD
  )
  SELECT
    USAGE_DATE AS SNAPSHOT_DATE,
    CASE WHEN DATABASE_NAME ILIKE 'TRXS_%' THEN 'Trexis' ELSE 'ALFA' END AS COMPANY,
    DATABASE_NAME,
    OVERWATCH_DATABASE_ENVIRONMENT(DATABASE_NAME) AS ENVIRONMENT,
    SUM(AVERAGE_DATABASE_BYTES) AS ACTIVE_BYTES,
    0 AS TIME_TRAVEL_BYTES,
    SUM(AVERAGE_FAILSAFE_BYTES) AS FAILSAFE_BYTES,
    0 AS RETAINED_FOR_CLONE_BYTES,
    ROUND(SUM(AVERAGE_DATABASE_BYTES + AVERAGE_FAILSAFE_BYTES) / POWER(1024, 4), 4) AS EST_STORAGE_TB,
    ROUND(SUM(AVERAGE_DATABASE_BYTES + AVERAGE_FAILSAFE_BYTES) / POWER(1024, 4) * 23, 2) AS EST_COST_USD
  FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
  WHERE USAGE_DATE >= DATEADD('DAY', -35, CURRENT_DATE())
  GROUP BY 1,2,3,4;

  rows_loaded := rows_loaded + SQLROWCOUNT;

  DELETE FROM DIM_TABLE_SNAPSHOT
  WHERE SNAPSHOT_TS::DATE = CURRENT_DATE();

  INSERT INTO DIM_TABLE_SNAPSHOT (
    SNAPSHOT_TS, COMPANY, DATABASE_NAME, ENVIRONMENT, SCHEMA_NAME, TABLE_NAME, TABLE_TYPE,
    ROW_COUNT, BYTES, LAST_ALTERED, CREATED
  )
  SELECT
    CURRENT_TIMESTAMP() AS SNAPSHOT_TS,
    CASE WHEN TABLE_CATALOG ILIKE 'TRXS_%' THEN 'Trexis' ELSE 'ALFA' END AS COMPANY,
    TABLE_CATALOG AS DATABASE_NAME,
    OVERWATCH_DATABASE_ENVIRONMENT(TABLE_CATALOG) AS ENVIRONMENT,
    TABLE_SCHEMA AS SCHEMA_NAME,
    TABLE_NAME,
    TABLE_TYPE,
    ROW_COUNT,
    BYTES,
    LAST_ALTERED,
    CREATED
  FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
  WHERE DELETED IS NULL
    AND TABLE_SCHEMA <> 'INFORMATION_SCHEMA';

  rows_loaded := rows_loaded + SQLROWCOUNT;

  DELETE FROM FACT_COPY_LOAD_DAILY
  WHERE LOAD_DATE >= DATEADD('DAY', -35, CURRENT_DATE());

  INSERT INTO FACT_COPY_LOAD_DAILY (
    LOAD_DATE, COMPANY, DATABASE_NAME, ENVIRONMENT, SCHEMA_NAME, TABLE_NAME, STATUS,
    FILE_COUNT, ROW_COUNT, ROW_PARSED, ERROR_COUNT, FILE_SIZE_BYTES,
    BYTES_BILLED, LAST_SEEN, LATEST_ERROR
  )
  SELECT
    TO_DATE(LAST_LOAD_TIME) AS LOAD_DATE,
    CASE WHEN TABLE_CATALOG_NAME ILIKE 'TRXS_%' THEN 'Trexis' ELSE 'ALFA' END AS COMPANY,
    TABLE_CATALOG_NAME AS DATABASE_NAME,
    OVERWATCH_DATABASE_ENVIRONMENT(TABLE_CATALOG_NAME) AS ENVIRONMENT,
    TABLE_SCHEMA_NAME AS SCHEMA_NAME,
    TABLE_NAME,
    STATUS,
    COUNT(*) AS FILE_COUNT,
    SUM(COALESCE(ROW_COUNT, 0)) AS ROW_COUNT,
    SUM(COALESCE(ROW_PARSED, 0)) AS ROW_PARSED,
    SUM(COALESCE(ERROR_COUNT, 0)) AS ERROR_COUNT,
    SUM(COALESCE(FILE_SIZE, 0)) AS FILE_SIZE_BYTES,
    0 AS BYTES_BILLED,
    MAX(LAST_LOAD_TIME) AS LAST_SEEN,
    MAX(FIRST_ERROR_MESSAGE) AS LATEST_ERROR
  FROM SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY
  WHERE LAST_LOAD_TIME >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())
  GROUP BY 1,2,3,4,5,6,7;

  rows_loaded := rows_loaded + SQLROWCOUNT;

  BEGIN
    DELETE FROM DIM_COST_OWNER_TAG
    WHERE SNAPSHOT_DATE = CURRENT_DATE();

    INSERT INTO DIM_COST_OWNER_TAG (
      SNAPSHOT_DATE, OWNER_SCOPE, OBJECT_DATABASE, OBJECT_SCHEMA, OBJECT_NAME,
      TAG_NAME, TAG_VALUE, OWNER_TYPE, PRIORITY
    )
    SELECT
      CURRENT_DATE() AS SNAPSHOT_DATE,
      UPPER(t.DOMAIN) AS OWNER_SCOPE,
      t.OBJECT_DATABASE,
      t.OBJECT_SCHEMA,
      t.OBJECT_NAME,
      t.TAG_NAME,
      t.TAG_VALUE,
      cfg.OWNER_TYPE,
      cfg.PRIORITY
    FROM SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES t
    JOIN OVERWATCH_OWNER_TAG_NAMES cfg
      ON UPPER(t.TAG_NAME) = UPPER(cfg.TAG_NAME)
     AND cfg.IS_ACTIVE = TRUE
    WHERE UPPER(t.DOMAIN) IN ('DATABASE', 'SCHEMA', 'TABLE', 'WAREHOUSE')
      AND t.TAG_VALUE IS NOT NULL;

    rows_loaded := rows_loaded + SQLROWCOUNT;
  EXCEPTION
    WHEN OTHER THEN
      INSERT INTO OVERWATCH_LOAD_AUDIT (LOAD_NAME, LOAD_STARTED_AT, LOAD_FINISHED_AT, STATUS, MESSAGE)
      VALUES ('DIM_COST_OWNER_TAG', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), 'SKIPPED', :SQLERRM);
  END;

  DELETE FROM FACT_CHARGEBACK_DAILY
  WHERE USAGE_DATE >= DATEADD('DAY', -35, CURRENT_DATE());

  INSERT INTO FACT_CHARGEBACK_DAILY (
    USAGE_DATE, COMPANY, ENVIRONMENT, ENVIRONMENT_ROLLUP, DATABASE_NAME,
    USER_NAME, ROLE_NAME, WAREHOUSE_NAME, WAREHOUSE_SIZE, QUERY_COUNT,
    ALLOCATED_CREDITS, EST_COST_USD, ALLOCATION_CONFIDENCE, ALLOCATION_BASIS,
    CHARGEBACK_READY, SCOPE_REVIEW, COST_OWNER, OWNER_SOURCE, OWNER_EVIDENCE
  )
  WITH query_hour AS (
    SELECT
      HOUR_START,
      COMPANY,
      WAREHOUSE_NAME,
      WAREHOUSE_SIZE,
      USER_NAME,
      ROLE_NAME,
      COALESCE(DATABASE_NAME, 'NO_DATABASE_CONTEXT') AS DATABASE_NAME,
      COALESCE(ENVIRONMENT, 'No Database Context') AS ENVIRONMENT,
      SUM(COALESCE(QUERY_COUNT, 0)) AS QUERY_COUNT,
      SUM(COALESCE(TOTAL_ELAPSED_MS, 0)) AS ELAPSED_MS
    FROM FACT_QUERY_HOURLY
    WHERE HOUR_START >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())
      AND WAREHOUSE_NAME IS NOT NULL
    GROUP BY 1,2,3,4,5,6,7,8
  ),
  warehouse_elapsed AS (
    SELECT
      HOUR_START,
      WAREHOUSE_NAME,
      SUM(ELAPSED_MS) AS WAREHOUSE_ELAPSED_MS
    FROM query_hour
    GROUP BY 1,2
  ),
  warehouse_credits AS (
    SELECT
      HOUR_START,
      WAREHOUSE_NAME,
      SUM(COALESCE(CREDITS_USED_COMPUTE, CREDITS_USED, 0)) AS CREDITS_USED
    FROM FACT_WAREHOUSE_HOURLY
    WHERE HOUR_START >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())
    GROUP BY 1,2
  ),
  allocated AS (
    SELECT
      TO_DATE(q.HOUR_START) AS USAGE_DATE,
      q.COMPANY,
      q.ENVIRONMENT,
      q.DATABASE_NAME,
      q.USER_NAME,
      q.ROLE_NAME,
      q.WAREHOUSE_NAME,
      q.WAREHOUSE_SIZE,
      SUM(q.QUERY_COUNT) AS QUERY_COUNT,
      SUM(
        COALESCE(wc.CREDITS_USED, 0)
        * q.ELAPSED_MS
        / NULLIF(we.WAREHOUSE_ELAPSED_MS, 0)
      ) AS ALLOCATED_CREDITS
    FROM query_hour q
    LEFT JOIN warehouse_elapsed we
      ON q.HOUR_START = we.HOUR_START
     AND q.WAREHOUSE_NAME = we.WAREHOUSE_NAME
    LEFT JOIN warehouse_credits wc
      ON q.HOUR_START = wc.HOUR_START
     AND q.WAREHOUSE_NAME = wc.WAREHOUSE_NAME
    GROUP BY 1,2,3,4,5,6,7,8
  ),
  classified AS (
    SELECT
      *,
      CASE
        WHEN UPPER(COALESCE(DATABASE_NAME, '')) IN ('', 'NONE', 'NULL', 'NAN', 'NO_DATABASE_CONTEXT', 'NO DATABASE CONTEXT')
          OR UPPER(COALESCE(ENVIRONMENT, '')) IN ('', 'NONE', 'NULL', 'NAN', 'NO_DATABASE_CONTEXT', 'NO DATABASE CONTEXT')
          THEN 'No Database Context'
       -- WHEN UPPER(DATABASE_NAME) = 'ALFA_EDW_PROD' OR UPPER(ENVIRONMENT) = 'PROD' THEN 'PROD'
        WHEN UPPER(DATABASE_NAME) IN ('ALFA_EDW_PROD','ALFA_EDW_MGM') OR UPPER(ENVIRONMENT) = 'PROD' THEN 'PROD'
        WHEN UPPER(DATABASE_NAME) IN ('ALFA_EDW_DEV', 'ALFA_EDW_SAN', 'ALFA_EDW_PHX', 'ALFA_EDW_SEA', 'ALFA_EDW_SIT')
          OR UPPER(ENVIRONMENT) IN ('ALFA_EDW_DEV', 'ALFA_EDW_SAN', 'ALFA_EDW_PHX', 'ALFA_EDW_SEA', 'ALFA_EDW_SIT', 'DEV_ALL')
          THEN 'DEV_ALL'
        WHEN UPPER(DATABASE_NAME) LIKE 'ALFA_EDW_%' OR UPPER(ENVIRONMENT) = 'OTHER ALFA NON-PROD' THEN 'Other ALFA Non-Prod'
        WHEN UPPER(DATABASE_NAME) LIKE 'TRXS_%' THEN 'Trexis'
        ELSE 'Other / Shared'
      END AS ENVIRONMENT_ROLLUP
    FROM allocated
  ),
  owner_tags AS (
    SELECT
      OWNER_SCOPE,
      UPPER(COALESCE(NULLIF(OBJECT_DATABASE, ''), OBJECT_NAME)) AS DATABASE_NAME,
      UPPER(OBJECT_NAME) AS OBJECT_NAME,
      TAG_NAME,
      TAG_VALUE,
      OWNER_TYPE,
      PRIORITY,
      ROW_NUMBER() OVER (
        PARTITION BY OWNER_SCOPE,
          UPPER(COALESCE(NULLIF(OBJECT_DATABASE, ''), OBJECT_NAME)),
          UPPER(OBJECT_NAME)
        ORDER BY PRIORITY, TAG_NAME
      ) AS RN
    FROM DIM_COST_OWNER_TAG
    WHERE SNAPSHOT_DATE = CURRENT_DATE()
      AND TAG_VALUE IS NOT NULL
  ),
  database_owners AS (
    SELECT DATABASE_NAME, TAG_NAME, TAG_VALUE, OWNER_TYPE
    FROM owner_tags
    WHERE OWNER_SCOPE = 'DATABASE'
      AND RN = 1
  ),
  warehouse_owners AS (
    SELECT OBJECT_NAME AS WAREHOUSE_NAME, TAG_NAME, TAG_VALUE, OWNER_TYPE
    FROM owner_tags
    WHERE OWNER_SCOPE = 'WAREHOUSE'
      AND RN = 1
  )
  SELECT
    c.USAGE_DATE,
    c.COMPANY,
    c.ENVIRONMENT,
    c.ENVIRONMENT_ROLLUP,
    c.DATABASE_NAME,
    c.USER_NAME,
    c.ROLE_NAME,
    c.WAREHOUSE_NAME,
    c.WAREHOUSE_SIZE,
    c.QUERY_COUNT,
    ROUND(COALESCE(c.ALLOCATED_CREDITS, 0), 6) AS ALLOCATED_CREDITS,
    ROUND(COALESCE(c.ALLOCATED_CREDITS, 0) * :credit_price, 2) AS EST_COST_USD,
    CASE
      WHEN c.ENVIRONMENT_ROLLUP = 'No Database Context' THEN 'Account-wide / Shared'
      WHEN c.ENVIRONMENT_ROLLUP IN ('PROD', 'DEV_ALL', 'Trexis', 'Other ALFA Non-Prod') THEN 'Allocated / Estimated'
      ELSE 'Shared / Needs Owner'
    END AS ALLOCATION_CONFIDENCE,
    CASE
      WHEN c.ENVIRONMENT_ROLLUP = 'No Database Context' THEN 'No database context; do not split PROD/DEV without tags or session lineage.'
      WHEN c.ENVIRONMENT_ROLLUP = 'Trexis' AND COALESCE(wo.TAG_VALUE, dbo.TAG_VALUE) IS NOT NULL
        THEN 'Trexis database context allocated across metered warehouse-hour credits; owner tag proof is attached.'
      WHEN c.ENVIRONMENT_ROLLUP = 'Trexis' THEN 'Trexis database context allocated across metered warehouse-hour credits.'
      WHEN c.ENVIRONMENT_ROLLUP = 'Other ALFA Non-Prod' THEN 'ALFA database context exists, but the environment is outside the approved PROD/DEV family.'
      WHEN c.ENVIRONMENT_ROLLUP IN ('PROD', 'DEV_ALL') AND COALESCE(wo.TAG_VALUE, dbo.TAG_VALUE) IS NOT NULL
        THEN 'Query database context allocated across metered warehouse-hour credits; owner tag proof is attached.'
      WHEN c.ENVIRONMENT_ROLLUP IN ('PROD', 'DEV_ALL') THEN 'Query database context allocated across metered warehouse-hour credits.'
      ELSE 'Shared warehouse/query context requires owner validation before billing.'
    END AS ALLOCATION_BASIS,
    CASE
      WHEN c.ENVIRONMENT_ROLLUP = 'No Database Context' THEN 'No'
      WHEN c.ENVIRONMENT_ROLLUP IN ('PROD', 'DEV_ALL', 'Trexis')
        AND COALESCE(wo.TAG_VALUE, dbo.TAG_VALUE) IS NOT NULL THEN 'Ready'
      WHEN c.ENVIRONMENT_ROLLUP IN ('PROD', 'DEV_ALL', 'Trexis') THEN 'Directional'
      ELSE 'Review'
    END AS CHARGEBACK_READY,
    CASE
      WHEN c.ENVIRONMENT_ROLLUP = 'No Database Context' THEN 'Missing database context'
      WHEN c.ENVIRONMENT_ROLLUP = 'Other ALFA Non-Prod' THEN 'Unmapped ALFA environment'
      WHEN c.ENVIRONMENT_ROLLUP = 'Other / Shared' THEN 'Shared or non-company scope'
      ELSE 'None'
    END AS SCOPE_REVIEW,
    CASE
      WHEN wo.TAG_VALUE IS NOT NULL THEN wo.TAG_VALUE
      WHEN dbo.TAG_VALUE IS NOT NULL THEN dbo.TAG_VALUE
      WHEN c.USER_NAME IS NOT NULL AND UPPER(c.USER_NAME) NOT IN ('', 'UNKNOWN_USER') THEN c.USER_NAME
      ELSE 'DBA / FinOps'
    END AS COST_OWNER,
    CASE
      WHEN wo.TAG_VALUE IS NOT NULL THEN 'WAREHOUSE_TAG:' || wo.TAG_NAME
      WHEN dbo.TAG_VALUE IS NOT NULL THEN 'DATABASE_TAG:' || dbo.TAG_NAME
      WHEN c.USER_NAME IS NOT NULL AND UPPER(c.USER_NAME) NOT IN ('', 'UNKNOWN_USER') THEN 'QUERY_USER'
      ELSE 'MISSING_OWNER'
    END AS OWNER_SOURCE,
    CASE
      WHEN wo.TAG_VALUE IS NOT NULL THEN 'Warehouse owner tag ' || wo.TAG_NAME || '=' || wo.TAG_VALUE || ' from SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES.'
      WHEN dbo.TAG_VALUE IS NOT NULL THEN 'Database owner tag ' || dbo.TAG_NAME || '=' || dbo.TAG_VALUE || ' from SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES.'
      WHEN c.USER_NAME IS NOT NULL AND UPPER(c.USER_NAME) NOT IN ('', 'UNKNOWN_USER')
        THEN 'Query user present; validate owner/tag evidence before billing.'
      ELSE 'No query user owner evidence; shared/unallocated review required.'
    END AS OWNER_EVIDENCE
  FROM classified c
  LEFT JOIN warehouse_owners wo
    ON UPPER(c.WAREHOUSE_NAME) = wo.WAREHOUSE_NAME
  LEFT JOIN database_owners dbo
    ON UPPER(c.DATABASE_NAME) = dbo.DATABASE_NAME;

  rows_loaded := rows_loaded + SQLROWCOUNT;

  DELETE FROM FACT_MONITORING_COST_DAILY
  WHERE USAGE_DATE >= DATEADD('DAY', -35, CURRENT_DATE());

  INSERT INTO FACT_MONITORING_COST_DAILY (
    USAGE_DATE, COMPANY, COST_COMPONENT, CREDITS_USED, EST_COST_USD, SOURCE
  )
  SELECT
    TO_DATE(START_TIME) AS USAGE_DATE,
    CASE WHEN WAREHOUSE_NAME ILIKE 'WH_TRXS_%' THEN 'Trexis' ELSE 'ALFA' END AS COMPANY,
    CASE
      WHEN WAREHOUSE_NAME = 'OVERWATCH_WH' THEN 'APP_RUNTIME'
      WHEN WAREHOUSE_NAME = 'COMPUTE_WH' THEN 'MART_REFRESH'
      WHEN WAREHOUSE_NAME ILIKE '%STREAMLIT%' THEN 'STREAMLIT_APP'
      ELSE 'OVERWATCH_TAGGED'
    END AS COST_COMPONENT,
    SUM(CREDITS_USED) AS CREDITS_USED,
    ROUND(SUM(CREDITS_USED) * :credit_price, 2) AS EST_COST_USD,
    'WAREHOUSE_METERING_HISTORY filtered to OVERWATCH_WH, COMPUTE_WH, and Streamlit-style warehouses' AS SOURCE
  FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
  WHERE START_TIME >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())
    AND (
      WAREHOUSE_NAME = 'OVERWATCH_WH'
      OR WAREHOUSE_NAME = 'COMPUTE_WH'
      OR WAREHOUSE_NAME ILIKE '%STREAMLIT%'
    )
  GROUP BY 1,2,3;

  rows_loaded := rows_loaded + SQLROWCOUNT;

  DELETE FROM FACT_WAREHOUSE_OPERABILITY_DAILY
  WHERE SNAPSHOT_DATE >= DATEADD('DAY', -35, CURRENT_DATE());

  INSERT INTO FACT_WAREHOUSE_OPERABILITY_DAILY (
    SNAPSHOT_DATE, COMPANY, ENVIRONMENT, WAREHOUSE_NAME, CONTROL_SOURCE,
    SEVERITY, SIGNAL, CONTROL_STATE, CONTROL_RANK, CAPACITY_SCORE,
    QUERY_ROWS, QUEUE_PRESSURE_ROWS, SPILL_PRESSURE_ROWS, HIGH_LATENCY_ROWS,
    METERED_CREDITS, CREDIT_ALLOCATION_METHOD, REVIEW_ROWS, APPROVAL_REQUIRED_ROWS, ROLLBACK_REQUIRED_ROWS,
    SAVINGS_VERIFICATION_ROWS, OPEN_ACTIONS, OVERDUE_OPEN, FIXED_WITHOUT_VERIFICATION,
    VERIFIED_CLOSURES, OWNER_APPROVAL_GAP_ROWS, NEXT_CONTROL_ACTION, LAST_ACTIVITY_TS
  )
  WITH query_daily AS (
    SELECT
      TO_DATE(HOUR_START) AS SNAPSHOT_DATE,
      COMPANY,
      COALESCE(ENVIRONMENT, 'No Database Context') AS ENVIRONMENT,
      WAREHOUSE_NAME,
      SUM(QUERY_COUNT) AS QUERY_ROWS,
      SUM(SUM(QUERY_COUNT)) OVER (
        PARTITION BY TO_DATE(HOUR_START), COMPANY, WAREHOUSE_NAME
      ) AS WAREHOUSE_QUERY_ROWS,
      COUNT_IF(COALESCE(TOTAL_QUEUED_MS, 0) > 0) AS QUEUE_PRESSURE_ROWS,
      COUNT_IF(COALESCE(TOTAL_SPILL_BYTES, 0) > 0) AS SPILL_PRESSURE_ROWS,
      COUNT_IF(COALESCE(P95_EXECUTION_MS, 0) >= 120000) AS HIGH_LATENCY_ROWS,
      MAX(HOUR_START) AS LAST_ACTIVITY_TS
    FROM FACT_QUERY_HOURLY
    WHERE HOUR_START >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())
      AND WAREHOUSE_NAME IS NOT NULL
    GROUP BY TO_DATE(HOUR_START), COMPANY, COALESCE(ENVIRONMENT, 'No Database Context'), WAREHOUSE_NAME
  ),
  credit_daily AS (
    SELECT
      TO_DATE(HOUR_START) AS SNAPSHOT_DATE,
      COMPANY,
      WAREHOUSE_NAME,
      SUM(CREDITS_USED) AS METERED_CREDITS
    FROM FACT_WAREHOUSE_HOURLY
    WHERE HOUR_START >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())
    GROUP BY TO_DATE(HOUR_START), COMPANY, WAREHOUSE_NAME
  ),
  capacity_rollup AS (
    SELECT
      q.SNAPSHOT_DATE,
      q.COMPANY,
      q.ENVIRONMENT,
      q.WAREHOUSE_NAME,
      'Capacity Fact' AS CONTROL_SOURCE,
      CASE
        WHEN q.QUEUE_PRESSURE_ROWS >= 8 OR q.SPILL_PRESSURE_ROWS >= 8 OR q.HIGH_LATENCY_ROWS >= 8 THEN 'High'
        WHEN q.QUEUE_PRESSURE_ROWS + q.SPILL_PRESSURE_ROWS + q.HIGH_LATENCY_ROWS > 0 THEN 'Medium'
        ELSE 'Low'
      END AS SEVERITY,
      CASE
        WHEN q.QUEUE_PRESSURE_ROWS >= GREATEST(q.SPILL_PRESSURE_ROWS, q.HIGH_LATENCY_ROWS) AND q.QUEUE_PRESSURE_ROWS > 0 THEN 'Queue Pressure'
        WHEN q.SPILL_PRESSURE_ROWS >= GREATEST(q.QUEUE_PRESSURE_ROWS, q.HIGH_LATENCY_ROWS) AND q.SPILL_PRESSURE_ROWS > 0 THEN 'Memory Spill'
        WHEN q.HIGH_LATENCY_ROWS > 0 THEN 'Latency Pressure'
        ELSE 'No Capacity Pressure'
      END AS SIGNAL,
      CASE
        WHEN q.QUEUE_PRESSURE_ROWS >= 8 OR q.SPILL_PRESSURE_ROWS >= 8 OR q.HIGH_LATENCY_ROWS >= 8 THEN 'Capacity Pressure'
        WHEN q.QUEUE_PRESSURE_ROWS + q.SPILL_PRESSURE_ROWS + q.HIGH_LATENCY_ROWS > 0 THEN 'Capacity Watch'
        ELSE 'Controlled'
      END AS CONTROL_STATE,
      CASE
        WHEN q.QUEUE_PRESSURE_ROWS >= 8 OR q.SPILL_PRESSURE_ROWS >= 8 OR q.HIGH_LATENCY_ROWS >= 8 THEN 2
        WHEN q.QUEUE_PRESSURE_ROWS + q.SPILL_PRESSURE_ROWS + q.HIGH_LATENCY_ROWS > 0 THEN 5
        ELSE 9
      END AS CONTROL_RANK,
      GREATEST(
        0,
        100
        - LEAST(q.QUEUE_PRESSURE_ROWS * 2, 30)
        - LEAST(q.SPILL_PRESSURE_ROWS * 2, 24)
        - LEAST(q.HIGH_LATENCY_ROWS * 1.5, 20)
        - LEAST(
            COALESCE(c.METERED_CREDITS, 0) * (q.QUERY_ROWS / NULLIF(q.WAREHOUSE_QUERY_ROWS, 0)) / 10,
            10
          )
      ) AS CAPACITY_SCORE,
      q.QUERY_ROWS,
      q.QUEUE_PRESSURE_ROWS,
      q.SPILL_PRESSURE_ROWS,
      q.HIGH_LATENCY_ROWS,
      COALESCE(c.METERED_CREDITS, 0)
        * (q.QUERY_ROWS / NULLIF(q.WAREHOUSE_QUERY_ROWS, 0)) AS METERED_CREDITS,
      'Estimated from warehouse metering allocated by query share' AS CREDIT_ALLOCATION_METHOD,
      0 AS REVIEW_ROWS,
      0 AS APPROVAL_REQUIRED_ROWS,
      0 AS ROLLBACK_REQUIRED_ROWS,
      0 AS SAVINGS_VERIFICATION_ROWS,
      0 AS OPEN_ACTIONS,
      0 AS OVERDUE_OPEN,
      0 AS FIXED_WITHOUT_VERIFICATION,
      0 AS VERIFIED_CLOSURES,
      0 AS OWNER_APPROVAL_GAP_ROWS,
      CASE
        WHEN q.QUEUE_PRESSURE_ROWS > 0 THEN 'Open Warehouse Health, inspect queue evidence, and route changed-only scaling recommendations.'
        WHEN q.SPILL_PRESSURE_ROWS > 0 THEN 'Inspect top spilling query shapes before increasing warehouse size.'
        WHEN q.HIGH_LATENCY_ROWS > 0 THEN 'Review p95 latency, warehouse size, and workload burst pattern.'
        ELSE 'No warehouse capacity action needed for this snapshot.'
      END AS NEXT_CONTROL_ACTION,
      q.LAST_ACTIVITY_TS
    FROM query_daily q
    LEFT JOIN credit_daily c
      ON q.SNAPSHOT_DATE = c.SNAPSHOT_DATE
     AND q.COMPANY = c.COMPANY
     AND q.WAREHOUSE_NAME = c.WAREHOUSE_NAME
  ),
  setting_rollup AS (
    SELECT
      TO_DATE(SNAPSHOT_TS) AS SNAPSHOT_DATE,
      COMPANY,
      COALESCE(ENVIRONMENT, 'No Database Context') AS ENVIRONMENT,
      WAREHOUSE_NAME,
      'Setting Review' AS CONTROL_SOURCE,
      MAX_BY(SEVERITY, SNAPSHOT_TS) AS SEVERITY,
      MAX_BY(SIGNAL, SNAPSHOT_TS) AS SIGNAL,
      CASE
        WHEN COUNT_IF(AUDIT_READINESS IN ('Owner Route Blocked', 'Pre-Change Blocked', 'Verification Blocked')) > 0 THEN 'Setting Review Blocked'
        WHEN COUNT_IF(APPROVAL_REQUIRED = 'Yes' OR ROLLBACK_REQUIRED = 'Yes' OR SAVINGS_VERIFICATION_REQUIRED = 'Yes') > 0 THEN 'Setting Review Required'
        ELSE 'Setting Review Ready'
      END AS CONTROL_STATE,
      CASE
        WHEN COUNT_IF(AUDIT_READINESS IN ('Owner Route Blocked', 'Pre-Change Blocked', 'Verification Blocked')) > 0 THEN 1
        WHEN COUNT_IF(APPROVAL_REQUIRED = 'Yes' OR ROLLBACK_REQUIRED = 'Yes' OR SAVINGS_VERIFICATION_REQUIRED = 'Yes') > 0 THEN 3
        ELSE 8
      END AS CONTROL_RANK,
      MIN(BASELINE_CAPACITY_SCORE) AS CAPACITY_SCORE,
      0 AS QUERY_ROWS,
      MAX(BASELINE_QUEUED_QUERIES) AS QUEUE_PRESSURE_ROWS,
      MAX(BASELINE_SPILL_QUERIES) AS SPILL_PRESSURE_ROWS,
      MAX(BASELINE_HIGH_LATENCY_QUERIES) AS HIGH_LATENCY_ROWS,
      MAX(BASELINE_METERED_CREDITS) AS METERED_CREDITS,
      'Estimated from setting-review baseline window' AS CREDIT_ALLOCATION_METHOD,
      COUNT(*) AS REVIEW_ROWS,
      COUNT_IF(APPROVAL_REQUIRED = 'Yes') AS APPROVAL_REQUIRED_ROWS,
      COUNT_IF(ROLLBACK_REQUIRED = 'Yes') AS ROLLBACK_REQUIRED_ROWS,
      COUNT_IF(SAVINGS_VERIFICATION_REQUIRED = 'Yes') AS SAVINGS_VERIFICATION_ROWS,
      0 AS OPEN_ACTIONS,
      0 AS OVERDUE_OPEN,
      0 AS FIXED_WITHOUT_VERIFICATION,
      0 AS VERIFIED_CLOSURES,
      COUNT_IF(UPPER(COALESCE(APPROVAL_STATE, '')) IN ('', 'REQUESTED', 'PENDING', 'REQUIRED')) AS OWNER_APPROVAL_GAP_ROWS,
      MAX_BY(NEXT_CONTROL_ACTION, SNAPSHOT_TS) AS NEXT_CONTROL_ACTION,
      MAX(SNAPSHOT_TS) AS LAST_ACTIVITY_TS
    FROM OVERWATCH_WAREHOUSE_SETTING_REVIEW
    WHERE SNAPSHOT_TS >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())
    GROUP BY TO_DATE(SNAPSHOT_TS), COMPANY, COALESCE(ENVIRONMENT, 'No Database Context'), WAREHOUSE_NAME
  ),
  action_rollup AS (
    SELECT
      TO_DATE(COALESCE(UPDATED_AT, CREATED_AT)) AS SNAPSHOT_DATE,
      COMPANY,
      COALESCE(ENVIRONMENT, 'No Database Context') AS ENVIRONMENT,
      COALESCE(ENTITY_NAME, 'Unknown warehouse') AS WAREHOUSE_NAME,
      'Action Queue' AS CONTROL_SOURCE,
      MAX_BY(SEVERITY, COALESCE(UPDATED_AT, CREATED_AT)) AS SEVERITY,
      MAX_BY(SOURCE, COALESCE(UPDATED_AT, CREATED_AT)) AS SIGNAL,
      CASE
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) > 0 THEN 'Closure Overdue'
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), '') = 'FIXED' AND (UPPER(COALESCE(VERIFICATION_STATUS, '')) <> 'VERIFIED' OR LENGTH(TRIM(COALESCE(VERIFICATION_RESULT, ''))) < 15)) > 0 THEN 'Closure Evidence Blocked'
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED')) > 0 THEN 'Work Open Action'
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), '') = 'FIXED' AND UPPER(COALESCE(VERIFICATION_STATUS, '')) = 'VERIFIED') > 0 THEN 'Verified Closure'
        ELSE 'No Recent Action'
      END AS CONTROL_STATE,
      CASE
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) > 0 THEN 0
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), '') = 'FIXED' AND (UPPER(COALESCE(VERIFICATION_STATUS, '')) <> 'VERIFIED' OR LENGTH(TRIM(COALESCE(VERIFICATION_RESULT, ''))) < 15)) > 0 THEN 1
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED')) > 0 THEN 4
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), '') = 'FIXED' AND UPPER(COALESCE(VERIFICATION_STATUS, '')) = 'VERIFIED') > 0 THEN 8
        ELSE 9
      END AS CONTROL_RANK,
      NULL::FLOAT AS CAPACITY_SCORE,
      0 AS QUERY_ROWS,
      0 AS QUEUE_PRESSURE_ROWS,
      0 AS SPILL_PRESSURE_ROWS,
      0 AS HIGH_LATENCY_ROWS,
      0 AS METERED_CREDITS,
      'No warehouse metering allocation on action rows' AS CREDIT_ALLOCATION_METHOD,
      0 AS REVIEW_ROWS,
      0 AS APPROVAL_REQUIRED_ROWS,
      0 AS ROLLBACK_REQUIRED_ROWS,
      0 AS SAVINGS_VERIFICATION_ROWS,
      COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED')) AS OPEN_ACTIONS,
      COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) AS OVERDUE_OPEN,
      COUNT_IF(COALESCE(UPPER(STATUS), '') = 'FIXED' AND (UPPER(COALESCE(VERIFICATION_STATUS, '')) <> 'VERIFIED' OR LENGTH(TRIM(COALESCE(VERIFICATION_RESULT, ''))) < 15)) AS FIXED_WITHOUT_VERIFICATION,
      COUNT_IF(COALESCE(UPPER(STATUS), '') = 'FIXED' AND UPPER(COALESCE(VERIFICATION_STATUS, '')) = 'VERIFIED') AS VERIFIED_CLOSURES,
      COUNT_IF(UPPER(COALESCE(OWNER_APPROVAL_STATUS, '')) IN ('', 'PENDING', 'REQUESTED', 'REQUIRED')) AS OWNER_APPROVAL_GAP_ROWS,
      CASE
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) > 0 THEN 'Escalate overdue warehouse action with owner, ticket, rollback, and post-change proof.'
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), '') = 'FIXED' AND (UPPER(COALESCE(VERIFICATION_STATUS, '')) <> 'VERIFIED' OR LENGTH(TRIM(COALESCE(VERIFICATION_RESULT, ''))) < 15)) > 0 THEN 'Attach post-change queue, spill, credit, and savings evidence before closure.'
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED')) > 0 THEN 'Work open warehouse action and retain rollback plus verification proof.'
        ELSE 'Retain verified closure evidence for capacity and cost trend review.'
      END AS NEXT_CONTROL_ACTION,
      MAX(COALESCE(UPDATED_AT, CREATED_AT)) AS LAST_ACTIVITY_TS
    FROM OVERWATCH_ACTION_QUEUE
    WHERE SOURCE IN ('Warehouse Health - Capacity Brief', 'Warehouse Health - Efficiency')
      AND COALESCE(UPDATED_AT, CREATED_AT) >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())
    GROUP BY TO_DATE(COALESCE(UPDATED_AT, CREATED_AT)), COMPANY, COALESCE(ENVIRONMENT, 'No Database Context'), COALESCE(ENTITY_NAME, 'Unknown warehouse')
  )
  SELECT * FROM capacity_rollup
  UNION ALL
  SELECT * FROM setting_rollup
  UNION ALL
  SELECT * FROM action_rollup;

  rows_loaded := rows_loaded + SQLROWCOUNT;

  DELETE FROM FACT_SECURITY_OPERABILITY_DAILY
  WHERE SNAPSHOT_DATE >= DATEADD('DAY', -35, CURRENT_DATE());

  INSERT INTO FACT_SECURITY_OPERABILITY_DAILY (
    SNAPSHOT_DATE, COMPANY, ENVIRONMENT, CONTROL_SOURCE, FINDING_TYPE,
    ENTITY, ENTITY_TYPE, SEVERITY, CONTROL_STATE, CONTROL_RANK,
    EVENT_ROWS, REVIEW_ROWS, REVIEW_BLOCKER_ROWS, TICKET_REQUIRED_ROWS,
    REVIEW_BY_REQUIRED_ROWS, CAPABILITY_PROOF_ROWS, NO_DATABASE_CONTEXT_ROWS,
    OPEN_ACTIONS, OVERDUE_OPEN, FIXED_WITHOUT_VERIFICATION, VERIFIED_CLOSURES,
    OWNER_APPROVAL_GAP_ROWS, NEXT_CONTROL_ACTION, LAST_ACTIVITY_TS
  )
  WITH access_rollup AS (
    SELECT
      TO_DATE(SNAPSHOT_TS) AS SNAPSHOT_DATE,
      COMPANY,
      COALESCE(ENVIRONMENT, 'No Database Context') AS ENVIRONMENT,
      'Access Review' AS CONTROL_SOURCE,
      FINDING_TYPE,
      ENTITY,
      ENTITY_TYPE,
      MAX_BY(SEVERITY, SNAPSHOT_TS) AS SEVERITY,
      CASE
        WHEN COUNT_IF(
          UPPER(COALESCE(REVIEW_READINESS, '')) LIKE '%BLOCKED%'
          OR UPPER(COALESCE(CONTROL_READINESS, '')) LIKE '%BLOCKED%'
        ) > 0 THEN 'Access Review Blocked'
        WHEN COUNT_IF(
          UPPER(COALESCE(TICKET_REQUIRED, '')) = 'YES'
          OR UPPER(COALESCE(REVIEW_BY_REQUIRED, '')) = 'YES'
          OR UPPER(COALESCE(ROLE_CAPABILITY_STATE, '')) LIKE '%PROOF%'
        ) > 0 THEN 'Access Review Required'
        WHEN COUNT_IF(UPPER(COALESCE(VERIFICATION_STATUS, '')) = 'VERIFIED') > 0 THEN 'Verified Review'
        ELSE 'Access Review Ready'
      END AS CONTROL_STATE,
      CASE
        WHEN COUNT_IF(
          UPPER(COALESCE(REVIEW_READINESS, '')) LIKE '%BLOCKED%'
          OR UPPER(COALESCE(CONTROL_READINESS, '')) LIKE '%BLOCKED%'
        ) > 0 THEN 1
        WHEN COUNT_IF(
          UPPER(COALESCE(TICKET_REQUIRED, '')) = 'YES'
          OR UPPER(COALESCE(REVIEW_BY_REQUIRED, '')) = 'YES'
          OR UPPER(COALESCE(ROLE_CAPABILITY_STATE, '')) LIKE '%PROOF%'
        ) > 0 THEN 3
        WHEN COUNT_IF(UPPER(COALESCE(VERIFICATION_STATUS, '')) = 'VERIFIED') > 0 THEN 8
        ELSE 9
      END AS CONTROL_RANK,
      SUM(COALESCE(EVENT_COUNT, 0)) AS EVENT_ROWS,
      COUNT(*) AS REVIEW_ROWS,
      COUNT_IF(
        UPPER(COALESCE(REVIEW_READINESS, '')) LIKE '%BLOCKED%'
        OR UPPER(COALESCE(CONTROL_READINESS, '')) LIKE '%BLOCKED%'
      ) AS REVIEW_BLOCKER_ROWS,
      COUNT_IF(UPPER(COALESCE(TICKET_REQUIRED, '')) = 'YES') AS TICKET_REQUIRED_ROWS,
      COUNT_IF(UPPER(COALESCE(REVIEW_BY_REQUIRED, '')) = 'YES') AS REVIEW_BY_REQUIRED_ROWS,
      COUNT_IF(UPPER(COALESCE(ROLE_CAPABILITY_STATE, '')) LIKE '%PROOF%') AS CAPABILITY_PROOF_ROWS,
      COUNT_IF(COALESCE(DATABASE_CONTEXT, FALSE) = FALSE) AS NO_DATABASE_CONTEXT_ROWS,
      0 AS OPEN_ACTIONS,
      0 AS OVERDUE_OPEN,
      0 AS FIXED_WITHOUT_VERIFICATION,
      0 AS VERIFIED_CLOSURES,
      COUNT_IF(
        UPPER(COALESCE(OWNER_APPROVAL_STATUS, IAM_APPROVAL_STATE, '')) IN ('', 'PENDING', 'REQUESTED', 'REQUIRED')
      ) AS OWNER_APPROVAL_GAP_ROWS,
      MAX_BY(COALESCE(NEXT_CONTROL_ACTION, NEXT_ACTION), SNAPSHOT_TS) AS NEXT_CONTROL_ACTION,
      MAX(SNAPSHOT_TS) AS LAST_ACTIVITY_TS
    FROM OVERWATCH_SECURITY_ACCESS_REVIEW
    WHERE SNAPSHOT_TS >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())
    GROUP BY TO_DATE(SNAPSHOT_TS), COMPANY, COALESCE(ENVIRONMENT, 'No Database Context'), FINDING_TYPE, ENTITY, ENTITY_TYPE
  ),
  action_rollup AS (
    SELECT
      TO_DATE(COALESCE(UPDATED_AT, CREATED_AT)) AS SNAPSHOT_DATE,
      COMPANY,
      COALESCE(ENVIRONMENT, 'No Database Context') AS ENVIRONMENT,
      'Action Queue' AS CONTROL_SOURCE,
      MAX_BY(COALESCE(CATEGORY, SOURCE), COALESCE(UPDATED_AT, CREATED_AT)) AS FINDING_TYPE,
      COALESCE(ENTITY_NAME, 'Unknown security entity') AS ENTITY,
      MAX_BY(COALESCE(ENTITY_TYPE, 'Security Finding'), COALESCE(UPDATED_AT, CREATED_AT)) AS ENTITY_TYPE,
      MAX_BY(SEVERITY, COALESCE(UPDATED_AT, CREATED_AT)) AS SEVERITY,
      CASE
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) > 0 THEN 'Closure Overdue'
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), '') = 'FIXED' AND (UPPER(COALESCE(VERIFICATION_STATUS, '')) <> 'VERIFIED' OR LENGTH(TRIM(COALESCE(VERIFICATION_RESULT, ''))) < 15)) > 0 THEN 'Closure Evidence Blocked'
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED')) > 0 THEN 'Work Open Action'
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), '') = 'FIXED' AND UPPER(COALESCE(VERIFICATION_STATUS, '')) = 'VERIFIED') > 0 THEN 'Verified Closure'
        ELSE 'No Recent Action'
      END AS CONTROL_STATE,
      CASE
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) > 0 THEN 0
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), '') = 'FIXED' AND (UPPER(COALESCE(VERIFICATION_STATUS, '')) <> 'VERIFIED' OR LENGTH(TRIM(COALESCE(VERIFICATION_RESULT, ''))) < 15)) > 0 THEN 1
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED')) > 0 THEN 4
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), '') = 'FIXED' AND UPPER(COALESCE(VERIFICATION_STATUS, '')) = 'VERIFIED') > 0 THEN 8
        ELSE 9
      END AS CONTROL_RANK,
      0 AS EVENT_ROWS,
      0 AS REVIEW_ROWS,
      0 AS REVIEW_BLOCKER_ROWS,
      0 AS TICKET_REQUIRED_ROWS,
      0 AS REVIEW_BY_REQUIRED_ROWS,
      0 AS CAPABILITY_PROOF_ROWS,
      COUNT_IF(UPPER(COALESCE(ENVIRONMENT, '')) IN ('', 'NO DATABASE CONTEXT')) AS NO_DATABASE_CONTEXT_ROWS,
      COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED')) AS OPEN_ACTIONS,
      COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) AS OVERDUE_OPEN,
      COUNT_IF(COALESCE(UPPER(STATUS), '') = 'FIXED' AND (UPPER(COALESCE(VERIFICATION_STATUS, '')) <> 'VERIFIED' OR LENGTH(TRIM(COALESCE(VERIFICATION_RESULT, ''))) < 15)) AS FIXED_WITHOUT_VERIFICATION,
      COUNT_IF(COALESCE(UPPER(STATUS), '') = 'FIXED' AND UPPER(COALESCE(VERIFICATION_STATUS, '')) = 'VERIFIED') AS VERIFIED_CLOSURES,
      COUNT_IF(UPPER(COALESCE(OWNER_APPROVAL_STATUS, '')) IN ('', 'PENDING', 'REQUESTED', 'REQUIRED')) AS OWNER_APPROVAL_GAP_ROWS,
      CASE
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) > 0 THEN 'Escalate overdue security action with owner, ticket, approval, and verification proof.'
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), '') = 'FIXED' AND (UPPER(COALESCE(VERIFICATION_STATUS, '')) <> 'VERIFIED' OR LENGTH(TRIM(COALESCE(VERIFICATION_RESULT, ''))) < 15)) > 0 THEN 'Attach IAM/Snowflake verification evidence before accepting closure.'
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED')) > 0 THEN 'Work open security action and retain least-privilege evidence.'
        ELSE 'Retain verified closure evidence for audit review.'
      END AS NEXT_CONTROL_ACTION,
      MAX(COALESCE(UPDATED_AT, CREATED_AT)) AS LAST_ACTIVITY_TS
    FROM OVERWATCH_ACTION_QUEUE
    WHERE SOURCE = 'Security Posture - Security Brief'
      AND COALESCE(UPDATED_AT, CREATED_AT) >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())
    GROUP BY TO_DATE(COALESCE(UPDATED_AT, CREATED_AT)), COMPANY, COALESCE(ENVIRONMENT, 'No Database Context'), COALESCE(ENTITY_NAME, 'Unknown security entity')
  )
  SELECT * FROM access_rollup
  UNION ALL
  SELECT * FROM action_rollup;

  rows_loaded := rows_loaded + SQLROWCOUNT;

  DELETE FROM FACT_ACCOUNT_HEALTH_OPERABILITY_DAILY
  WHERE SNAPSHOT_DATE >= DATEADD('DAY', -35, CURRENT_DATE());

  INSERT INTO FACT_ACCOUNT_HEALTH_OPERABILITY_DAILY (
    SNAPSHOT_DATE, COMPANY, ENVIRONMENT, CONTROL_SOURCE, CHECK_NAME,
    ROUTE, SEVERITY, CONTROL_STATE, CONTROL_RANK, HEALTH_SCORE,
    ISSUE_ROWS, ROUTE_BLOCKER_ROWS, QUEUE_REQUIRED_ROWS, ACCESS_HYGIENE_ROWS,
    FAILED_LOGIN_ROWS, PRIVILEGED_GRANT_ROWS, OPEN_ACTIONS, OVERDUE_OPEN,
    FIXED_WITHOUT_VERIFICATION, VERIFIED_CLOSURES, OWNER_APPROVAL_GAP_ROWS,
    RECOVERY_RISK_ROWS, NEXT_CONTROL_ACTION, LAST_ACTIVITY_TS
  )
  WITH checklist_rollup AS (
    SELECT
      TO_DATE(SNAPSHOT_TS) AS SNAPSHOT_DATE,
      COMPANY,
      COALESCE(ENVIRONMENT, 'No Database Context') AS ENVIRONMENT,
      'Checklist History' AS CONTROL_SOURCE,
      CHECK_NAME,
      MAX_BY(ROUTE, SNAPSHOT_TS) AS ROUTE,
      MAX_BY(SEVERITY, SNAPSHOT_TS) AS SEVERITY,
      CASE
        WHEN COUNT_IF(UPPER(COALESCE(CONTROL_READINESS, '')) IN ('CLOSURE OVERDUE', 'CLOSURE EVIDENCE BLOCKED', 'ROUTE METADATA BLOCKED')) > 0 THEN 'Checklist Control Blocked'
        WHEN COUNT_IF(UPPER(COALESCE(QUEUE_READINESS, '')) <> 'READY TO QUEUE') > 0 THEN 'Route Metadata Blocked'
        WHEN COUNT_IF(COALESCE(ACTIONABLE, FALSE)) > 0 THEN 'Queue Required'
        ELSE 'Controlled'
      END AS CONTROL_STATE,
      CASE
        WHEN COUNT_IF(UPPER(COALESCE(CONTROL_READINESS, '')) IN ('CLOSURE OVERDUE', 'CLOSURE EVIDENCE BLOCKED', 'ROUTE METADATA BLOCKED')) > 0 THEN 1
        WHEN COUNT_IF(UPPER(COALESCE(QUEUE_READINESS, '')) <> 'READY TO QUEUE') > 0 THEN 2
        WHEN COUNT_IF(COALESCE(ACTIONABLE, FALSE)) > 0 THEN 3
        ELSE 9
      END AS CONTROL_RANK,
      ROUND(AVG(HEALTH_SCORE), 1) AS HEALTH_SCORE,
      COUNT_IF(COALESCE(ACTIONABLE, FALSE)) AS ISSUE_ROWS,
      COUNT_IF(UPPER(COALESCE(QUEUE_READINESS, '')) <> 'READY TO QUEUE') AS ROUTE_BLOCKER_ROWS,
      COUNT_IF(COALESCE(ACTIONABLE, FALSE) AND UPPER(COALESCE(QUEUE_READINESS, '')) = 'READY TO QUEUE') AS QUEUE_REQUIRED_ROWS,
      0 AS ACCESS_HYGIENE_ROWS,
      0 AS FAILED_LOGIN_ROWS,
      0 AS PRIVILEGED_GRANT_ROWS,
      0 AS OPEN_ACTIONS,
      0 AS OVERDUE_OPEN,
      0 AS FIXED_WITHOUT_VERIFICATION,
      0 AS VERIFIED_CLOSURES,
      COUNT_IF(UPPER(COALESCE(APPROVAL_REQUIRED, '')) = 'YES') AS OWNER_APPROVAL_GAP_ROWS,
      0 AS RECOVERY_RISK_ROWS,
      MAX_BY(COALESCE(NEXT_CONTROL_ACTION, NEXT_ACTION), SNAPSHOT_TS) AS NEXT_CONTROL_ACTION,
      MAX(SNAPSHOT_TS) AS LAST_ACTIVITY_TS
    FROM OVERWATCH_DBA_CHECKLIST_HISTORY
    WHERE SNAPSHOT_TS >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())
    GROUP BY TO_DATE(SNAPSHOT_TS), COMPANY, COALESCE(ENVIRONMENT, 'No Database Context'), CHECK_NAME
  ),
  action_rollup AS (
    SELECT
      TO_DATE(COALESCE(UPDATED_AT, CREATED_AT)) AS SNAPSHOT_DATE,
      COMPANY,
      COALESCE(ENVIRONMENT, 'No Database Context') AS ENVIRONMENT,
      'Action Queue' AS CONTROL_SOURCE,
      COALESCE(ENTITY_NAME, 'Daily DBA checklist') AS CHECK_NAME,
      MAX_BY(COALESCE(CATEGORY, 'Account Health'), COALESCE(UPDATED_AT, CREATED_AT)) AS ROUTE,
      MAX_BY(SEVERITY, COALESCE(UPDATED_AT, CREATED_AT)) AS SEVERITY,
      CASE
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) > 0 THEN 'Closure Overdue'
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), '') = 'FIXED' AND (UPPER(COALESCE(VERIFICATION_STATUS, '')) <> 'VERIFIED' OR LENGTH(TRIM(COALESCE(VERIFICATION_RESULT, ''))) < 15)) > 0 THEN 'Closure Evidence Blocked'
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED')) > 0 THEN 'Work Open Action'
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), '') = 'FIXED' AND UPPER(COALESCE(VERIFICATION_STATUS, '')) = 'VERIFIED') > 0 THEN 'Verified Closure'
        ELSE 'No Recent Action'
      END AS CONTROL_STATE,
      CASE
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) > 0 THEN 0
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), '') = 'FIXED' AND (UPPER(COALESCE(VERIFICATION_STATUS, '')) <> 'VERIFIED' OR LENGTH(TRIM(COALESCE(VERIFICATION_RESULT, ''))) < 15)) > 0 THEN 1
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED')) > 0 THEN 4
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), '') = 'FIXED' AND UPPER(COALESCE(VERIFICATION_STATUS, '')) = 'VERIFIED') > 0 THEN 8
        ELSE 9
      END AS CONTROL_RANK,
      NULL::FLOAT AS HEALTH_SCORE,
      0 AS ISSUE_ROWS,
      0 AS ROUTE_BLOCKER_ROWS,
      0 AS QUEUE_REQUIRED_ROWS,
      0 AS ACCESS_HYGIENE_ROWS,
      0 AS FAILED_LOGIN_ROWS,
      0 AS PRIVILEGED_GRANT_ROWS,
      COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED')) AS OPEN_ACTIONS,
      COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) AS OVERDUE_OPEN,
      COUNT_IF(COALESCE(UPPER(STATUS), '') = 'FIXED' AND (UPPER(COALESCE(VERIFICATION_STATUS, '')) <> 'VERIFIED' OR LENGTH(TRIM(COALESCE(VERIFICATION_RESULT, ''))) < 15)) AS FIXED_WITHOUT_VERIFICATION,
      COUNT_IF(COALESCE(UPPER(STATUS), '') = 'FIXED' AND UPPER(COALESCE(VERIFICATION_STATUS, '')) = 'VERIFIED') AS VERIFIED_CLOSURES,
      COUNT_IF(UPPER(COALESCE(OWNER_APPROVAL_STATUS, '')) IN ('', 'PENDING', 'REQUESTED', 'REQUIRED')) AS OWNER_APPROVAL_GAP_ROWS,
      COUNT_IF(
        UPPER(COALESCE(RECOVERY_SLA_STATE, '')) ILIKE '%BREACH%'
        OR UPPER(COALESCE(RECOVERY_SLA_STATE, '')) ILIKE '%LATE%'
        OR (UPPER(COALESCE(RECOVERY_SLA_STATE, '')) IN ('OPEN FAILURE', 'RECOVERY SLA BREACH') AND LENGTH(TRIM(COALESCE(RECOVERY_EVIDENCE, ''))) = 0)
      ) AS RECOVERY_RISK_ROWS,
      CASE
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) > 0 THEN 'Escalate overdue Account Health checklist action with owner, ticket, and proof.'
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), '') = 'FIXED' AND (UPPER(COALESCE(VERIFICATION_STATUS, '')) <> 'VERIFIED' OR LENGTH(TRIM(COALESCE(VERIFICATION_RESULT, ''))) < 15)) > 0 THEN 'Attach verification notes/result or reopen the checklist action.'
        WHEN COUNT_IF(COALESCE(UPPER(STATUS), 'OPEN') NOT IN ('FIXED', 'IGNORED')) > 0 THEN 'Work the open checklist action and attach proof before closing.'
        ELSE 'Retain verified closure evidence for audit trend review.'
      END AS NEXT_CONTROL_ACTION,
      MAX(COALESCE(UPDATED_AT, CREATED_AT)) AS LAST_ACTIVITY_TS
    FROM OVERWATCH_ACTION_QUEUE
    WHERE SOURCE = 'Account Health - Daily DBA Checklist'
      AND COALESCE(UPDATED_AT, CREATED_AT) >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())
    GROUP BY TO_DATE(COALESCE(UPDATED_AT, CREATED_AT)), COMPANY, COALESCE(ENVIRONMENT, 'No Database Context'), COALESCE(ENTITY_NAME, 'Daily DBA checklist')
  ),
  failed_login_rollup AS (
    SELECT
      LOGIN_DATE AS SNAPSHOT_DATE,
      COMPANY,
      'No Database Context' AS ENVIRONMENT,
      'Access Hygiene Fact' AS CONTROL_SOURCE,
      'Failed login hygiene' AS CHECK_NAME,
      'Security Posture' AS ROUTE,
      CASE WHEN SUM(FAILURE_COUNT) >= 10 OR COUNT(DISTINCT USER_NAME) >= 3 THEN 'High' ELSE 'Medium' END AS SEVERITY,
      CASE WHEN SUM(FAILURE_COUNT) >= 10 OR COUNT(DISTINCT USER_NAME) >= 3 THEN 'High-Risk Access Review' ELSE 'Access Hygiene Watch' END AS CONTROL_STATE,
      CASE WHEN SUM(FAILURE_COUNT) >= 10 OR COUNT(DISTINCT USER_NAME) >= 3 THEN 2 ELSE 6 END AS CONTROL_RANK,
      NULL::FLOAT AS HEALTH_SCORE,
      SUM(FAILURE_COUNT) AS ISSUE_ROWS,
      0 AS ROUTE_BLOCKER_ROWS,
      0 AS QUEUE_REQUIRED_ROWS,
      COUNT(DISTINCT USER_NAME) AS ACCESS_HYGIENE_ROWS,
      SUM(FAILURE_COUNT) AS FAILED_LOGIN_ROWS,
      0 AS PRIVILEGED_GRANT_ROWS,
      0 AS OPEN_ACTIONS,
      0 AS OVERDUE_OPEN,
      0 AS FIXED_WITHOUT_VERIFICATION,
      0 AS VERIFIED_CLOSURES,
      0 AS OWNER_APPROVAL_GAP_ROWS,
      0 AS RECOVERY_RISK_ROWS,
      'Review failed login users and source IPs; retain IAM/Snowflake evidence before queueing access remediation.' AS NEXT_CONTROL_ACTION,
      TO_TIMESTAMP_NTZ(LOGIN_DATE) AS LAST_ACTIVITY_TS
    FROM FACT_LOGIN_DAILY
    WHERE LOGIN_DATE >= DATEADD('DAY', -35, CURRENT_DATE())
      AND COALESCE(FAILURE_COUNT, 0) > 0
    GROUP BY LOGIN_DATE, COMPANY
  ),
  privileged_grant_rollup AS (
    SELECT
      SNAPSHOT_DATE,
      COMPANY,
      'No Database Context' AS ENVIRONMENT,
      'Access Hygiene Fact' AS CONTROL_SOURCE,
      'Privileged role grant hygiene' AS CHECK_NAME,
      'Security Posture' AS ROUTE,
      'High' AS SEVERITY,
      'High-Risk Access Review' AS CONTROL_STATE,
      2 AS CONTROL_RANK,
      NULL::FLOAT AS HEALTH_SCORE,
      SUM(GRANT_COUNT) AS ISSUE_ROWS,
      0 AS ROUTE_BLOCKER_ROWS,
      0 AS QUEUE_REQUIRED_ROWS,
      COUNT(DISTINCT GRANTEE_NAME) AS ACCESS_HYGIENE_ROWS,
      0 AS FAILED_LOGIN_ROWS,
      SUM(GRANT_COUNT) AS PRIVILEGED_GRANT_ROWS,
      0 AS OPEN_ACTIONS,
      0 AS OVERDUE_OPEN,
      0 AS FIXED_WITHOUT_VERIFICATION,
      0 AS VERIFIED_CLOSURES,
      SUM(GRANT_COUNT) AS OWNER_APPROVAL_GAP_ROWS,
      0 AS RECOVERY_RISK_ROWS,
      'Verify privileged role business need, owner approval, and least-privilege evidence before accepting the account posture.' AS NEXT_CONTROL_ACTION,
      MAX(CREATED_ON) AS LAST_ACTIVITY_TS
    FROM FACT_GRANT_DAILY
    WHERE SNAPSHOT_DATE >= DATEADD('DAY', -35, CURRENT_DATE())
      AND DELETED_ON IS NULL
      AND UPPER(ROLE_NAME) IN ('ACCOUNTADMIN', 'SECURITYADMIN', 'SYSADMIN', 'ORGADMIN')
    GROUP BY SNAPSHOT_DATE, COMPANY
  )
  SELECT * FROM checklist_rollup
  UNION ALL
  SELECT * FROM action_rollup
  UNION ALL
  SELECT * FROM failed_login_rollup
  UNION ALL
  SELECT * FROM privileged_grant_rollup;

  rows_loaded := rows_loaded + SQLROWCOUNT;

  DELETE FROM FACT_CHANGE_CONTROL_OPERABILITY_DAILY
  WHERE SNAPSHOT_DATE >= DATEADD('DAY', -35, CURRENT_DATE());

  INSERT INTO FACT_CHANGE_CONTROL_OPERABILITY_DAILY (
    SNAPSHOT_DATE, COMPANY, ENVIRONMENT, CONTROL_SOURCE, CONTROL_KEY,
    FINDING_TYPE, ENTITY, OWNER, ESCALATION_TARGET, SEVERITY,
    EVIDENCE_ROWS, HIGH_RISK_CHANGES, ROUTE_BLOCKED, CLOSURE_BLOCKED,
    REVIEW_READY, MISSING_TICKET_ROWS, IAC_GAP_ROWS, MISSING_QUERY_ID_ROWS,
    OPEN_ACTIONS, OVERDUE_OPEN, FIXED_WITHOUT_VERIFICATION, VERIFIED_CLOSURES,
    OWNER_APPROVAL_GAP_ROWS, CONTROL_STATE, CONTROL_RANK, NEXT_CONTROL_ACTION,
    LAST_ACTIVITY_TS
  )
  WITH evidence_rollup AS (
    SELECT
      TO_DATE(SNAPSHOT_TS) AS SNAPSHOT_DATE,
      COMPANY,
      COALESCE(ENVIRONMENT, 'No Database Context') AS ENVIRONMENT,
      'Evidence Snapshot' AS CONTROL_SOURCE,
      FINDING_TYPE || '|' || COALESCE(OWNER, 'Unknown') AS CONTROL_KEY,
      FINDING_TYPE,
      NULL::VARCHAR AS ENTITY,
      MAX_BY(OWNER, SNAPSHOT_TS) AS OWNER,
      MAX_BY(ESCALATION_TARGET, SNAPSHOT_TS) AS ESCALATION_TARGET,
      MAX_BY(SEVERITY, SNAPSHOT_TS) AS SEVERITY,
      COUNT(*) AS EVIDENCE_ROWS,
      COUNT_IF(UPPER(SEVERITY) IN ('CRITICAL', 'HIGH')) AS HIGH_RISK_CHANGES,
      COUNT_IF(CHANGE_CONTROL_STATE = 'Route Blocked') AS ROUTE_BLOCKED,
      COUNT_IF(CHANGE_CONTROL_STATE = 'Closure Blocked') AS CLOSURE_BLOCKED,
      COUNT_IF(CHANGE_CONTROL_STATE = 'Review Ready') AS REVIEW_READY,
      COUNT_IF(CHANGE_TICKET_STATE ILIKE 'Missing%') AS MISSING_TICKET_ROWS,
      COUNT_IF(IAC_RECONCILIATION_STATE ILIKE '%required%' OR IAC_RECONCILIATION_STATE ILIKE '%Reconcile%') AS IAC_GAP_ROWS,
      COUNT_IF(EXECUTION_AUDIT_STATE ILIKE 'Missing%') AS MISSING_QUERY_ID_ROWS,
      0 AS OPEN_ACTIONS,
      0 AS OVERDUE_OPEN,
      0 AS FIXED_WITHOUT_VERIFICATION,
      0 AS VERIFIED_CLOSURES,
      COUNT_IF(UPPER(OWNER_APPROVAL_STATUS) IN ('', 'PENDING', 'REQUESTED', 'REQUIRED')) AS OWNER_APPROVAL_GAP_ROWS,
      CASE
        WHEN COUNT_IF(CHANGE_CONTROL_STATE = 'Route Blocked') > 0 THEN 'Route Blocked'
        WHEN COUNT_IF(CHANGE_CONTROL_STATE = 'Closure Blocked') > 0 THEN 'Closure Blocked'
        WHEN COUNT_IF(CHANGE_CONTROL_STATE = 'Review Ready') > 0 THEN 'Review Ready'
        ELSE 'Review Required'
      END AS CONTROL_STATE,
      CASE
        WHEN COUNT_IF(CHANGE_CONTROL_STATE = 'Route Blocked') > 0 THEN 0
        WHEN COUNT_IF(CHANGE_CONTROL_STATE = 'Closure Blocked') > 0 THEN 1
        WHEN COUNT_IF(CHANGE_CONTROL_STATE = 'Review Ready') > 0 THEN 8
        ELSE 5
      END AS CONTROL_RANK,
      MAX_BY(CONTROL_GAP, SNAPSHOT_TS) AS NEXT_CONTROL_ACTION,
      MAX(SNAPSHOT_TS) AS LAST_ACTIVITY_TS
    FROM OVERWATCH_CHANGE_CONTROL_EVIDENCE
    WHERE SNAPSHOT_TS >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())
    GROUP BY TO_DATE(SNAPSHOT_TS), COMPANY, COALESCE(ENVIRONMENT, 'No Database Context'), FINDING_TYPE, COALESCE(OWNER, 'Unknown')
  ),
  action_rollup AS (
    SELECT
      TO_DATE(COALESCE(UPDATED_AT, CREATED_AT)) AS SNAPSHOT_DATE,
      COMPANY,
      COALESCE(ENVIRONMENT, 'No Database Context') AS ENVIRONMENT,
      'Action Queue' AS CONTROL_SOURCE,
      COALESCE(ENTITY_NAME, 'Unknown') || ' | ' || COALESCE(CATEGORY, 'Change Control') AS CONTROL_KEY,
      COALESCE(CATEGORY, 'Change Control') AS FINDING_TYPE,
      COALESCE(ENTITY_NAME, 'Unknown') AS ENTITY,
      MAX_BY(OWNER, COALESCE(UPDATED_AT, CREATED_AT)) AS OWNER,
      MAX_BY(ESCALATION_TARGET, COALESCE(UPDATED_AT, CREATED_AT)) AS ESCALATION_TARGET,
      MAX_BY(SEVERITY, COALESCE(UPDATED_AT, CREATED_AT)) AS SEVERITY,
      0 AS EVIDENCE_ROWS,
      COUNT_IF(UPPER(SEVERITY) IN ('CRITICAL', 'HIGH')) AS HIGH_RISK_CHANGES,
      0 AS ROUTE_BLOCKED,
      COUNT_IF(
        UPPER(STATUS) = 'FIXED'
        AND (
          UPPER(COALESCE(VERIFICATION_STATUS, '')) <> 'VERIFIED'
          OR LENGTH(TRIM(COALESCE(VERIFICATION_RESULT, ''))) < 15
        )
      ) AS CLOSURE_BLOCKED,
      0 AS REVIEW_READY,
      COUNT_IF(LENGTH(TRIM(COALESCE(TICKET_ID, ''))) = 0) AS MISSING_TICKET_ROWS,
      0 AS IAC_GAP_ROWS,
      COUNT_IF(LENGTH(TRIM(COALESCE(VERIFICATION_QUERY, PROOF_QUERY, ''))) = 0) AS MISSING_QUERY_ID_ROWS,
      COUNT_IF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED')) AS OPEN_ACTIONS,
      COUNT_IF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) AS OVERDUE_OPEN,
      COUNT_IF(
        UPPER(STATUS) = 'FIXED'
        AND (
          UPPER(COALESCE(VERIFICATION_STATUS, '')) <> 'VERIFIED'
          OR LENGTH(TRIM(COALESCE(VERIFICATION_RESULT, ''))) < 15
        )
      ) AS FIXED_WITHOUT_VERIFICATION,
      COUNT_IF(UPPER(STATUS) = 'FIXED' AND UPPER(COALESCE(VERIFICATION_STATUS, '')) = 'VERIFIED') AS VERIFIED_CLOSURES,
      COUNT_IF(UPPER(COALESCE(OWNER_APPROVAL_STATUS, '')) IN ('', 'PENDING', 'REQUESTED', 'REQUIRED')) AS OWNER_APPROVAL_GAP_ROWS,
      CASE
        WHEN COUNT_IF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) > 0 THEN 'Closure Overdue'
        WHEN COUNT_IF(UPPER(STATUS) = 'FIXED' AND (UPPER(COALESCE(VERIFICATION_STATUS, '')) <> 'VERIFIED' OR LENGTH(TRIM(COALESCE(VERIFICATION_RESULT, ''))) < 15)) > 0 THEN 'Closure Evidence Blocked'
        WHEN COUNT_IF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED')) > 0 THEN 'Work Open Action'
        WHEN COUNT_IF(UPPER(STATUS) = 'FIXED' AND UPPER(COALESCE(VERIFICATION_STATUS, '')) = 'VERIFIED') > 0 THEN 'Verified Closure'
        ELSE 'No Recent Action'
      END AS CONTROL_STATE,
      CASE
        WHEN COUNT_IF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) > 0 THEN 0
        WHEN COUNT_IF(UPPER(STATUS) = 'FIXED' AND (UPPER(COALESCE(VERIFICATION_STATUS, '')) <> 'VERIFIED' OR LENGTH(TRIM(COALESCE(VERIFICATION_RESULT, ''))) < 15)) > 0 THEN 1
        WHEN COUNT_IF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED')) > 0 THEN 4
        WHEN COUNT_IF(UPPER(STATUS) = 'FIXED' AND UPPER(COALESCE(VERIFICATION_STATUS, '')) = 'VERIFIED') > 0 THEN 8
        ELSE 9
      END AS CONTROL_RANK,
      CASE
        WHEN COUNT_IF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) > 0 THEN 'Escalate overdue change action with owner, ticket, and rollback proof.'
        WHEN COUNT_IF(UPPER(STATUS) = 'FIXED' AND (UPPER(COALESCE(VERIFICATION_STATUS, '')) <> 'VERIFIED' OR LENGTH(TRIM(COALESCE(VERIFICATION_RESULT, ''))) < 15)) > 0 THEN 'Attach verification, source-control, and blast-radius evidence before closure.'
        WHEN COUNT_IF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED')) > 0 THEN 'Work open change action and retain approval evidence.'
        ELSE 'Retain verified closure evidence for audit review.'
      END AS NEXT_CONTROL_ACTION,
      MAX(COALESCE(UPDATED_AT, CREATED_AT)) AS LAST_ACTIVITY_TS
    FROM OVERWATCH_ACTION_QUEUE
    WHERE SOURCE = 'Change & Drift - Brief'
      AND COALESCE(UPDATED_AT, CREATED_AT) >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())
    GROUP BY TO_DATE(COALESCE(UPDATED_AT, CREATED_AT)), COMPANY, COALESCE(ENVIRONMENT, 'No Database Context'), COALESCE(CATEGORY, 'Change Control'), COALESCE(ENTITY_NAME, 'Unknown')
  )
  SELECT * FROM evidence_rollup
  UNION ALL
  SELECT * FROM action_rollup;

  rows_loaded := rows_loaded + SQLROWCOUNT;

  CALL SP_OVERWATCH_PRUNE();

  UPDATE OVERWATCH_LOAD_AUDIT
  SET LOAD_FINISHED_AT = CURRENT_TIMESTAMP(),
      STATUS = 'SUCCEEDED',
      ROWS_LOADED = :rows_loaded,
      MESSAGE = 'Daily mart load complete.'
  WHERE LOAD_NAME = 'SP_OVERWATCH_LOAD_DAILY'
    AND LOAD_STARTED_AT = :started_at;

  RETURN 'OVERWATCH daily mart load complete: ' || rows_loaded || ' rows.';

EXCEPTION
  WHEN OTHER THEN
    UPDATE OVERWATCH_LOAD_AUDIT
    SET LOAD_FINISHED_AT = CURRENT_TIMESTAMP(),
        STATUS = 'FAILED',
        MESSAGE = :SQLERRM
    WHERE LOAD_NAME = 'SP_OVERWATCH_LOAD_DAILY'
      AND LOAD_STARTED_AT = :started_at;
    RAISE;
END;
$$;

CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_CONTROL_ROOM()
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
BEGIN
  DELETE FROM MART_DBA_CONTROL_ROOM
  WHERE SNAPSHOT_TS >= DATEADD('HOUR', -2, CURRENT_TIMESTAMP());

  INSERT INTO MART_DBA_CONTROL_ROOM (
    SNAPSHOT_TS, COMPANY, HEALTH_SCORE, FAILED_QUERIES_24H, FAILED_TASKS_24H,
    QUEUED_MS_24H, CREDITS_24H, COST_24H_USD, CORTEX_COST_7D_USD,
    SECURITY_EVENTS_24H, OBJECT_CHANGES_24H, TOP_RISK
  )
  WITH companies AS (
    SELECT 'ALFA' AS company UNION ALL SELECT 'Trexis'
  ),
  q AS (
    SELECT
      company,
      SUM(failed_count) AS failed_queries,
      SUM(total_queued_ms) AS queued_ms
    FROM FACT_QUERY_HOURLY
    WHERE hour_start >= DATEADD('HOUR', -24, CURRENT_TIMESTAMP())
    GROUP BY company
  ),
  wh AS (
    SELECT
      company,
      SUM(credits_used) AS credits,
      SUM(est_cost_usd) AS cost_usd
    FROM FACT_WAREHOUSE_HOURLY
    WHERE hour_start >= DATEADD('HOUR', -24, CURRENT_TIMESTAMP())
    GROUP BY company
  ),
  oc AS (
    SELECT company, COUNT(*) AS object_changes
    FROM FACT_OBJECT_CHANGE
    WHERE start_time >= DATEADD('HOUR', -24, CURRENT_TIMESTAMP())
    GROUP BY company
  ),
  task_failures AS (
    SELECT company, COUNT(*) AS failed_tasks
    FROM FACT_TASK_RUN
    WHERE scheduled_time >= DATEADD('HOUR', -24, CURRENT_TIMESTAMP())
      AND UPPER(COALESCE(state, '')) IN ('FAILED', 'FAILED_WITH_ERROR')
    GROUP BY company
  ),
  sec AS (
    SELECT company, SUM(failure_count) AS security_events
    FROM FACT_LOGIN_DAILY
    WHERE login_date >= DATEADD('DAY', -1, CURRENT_DATE())
    GROUP BY company
  ),
  cx AS (
    SELECT company, SUM(est_cost_usd) AS cortex_cost
    FROM FACT_CORTEX_DAILY
    WHERE usage_date >= DATEADD('DAY', -7, CURRENT_DATE())
    GROUP BY company
  )
  SELECT
    CURRENT_TIMESTAMP(),
    c.company,
    GREATEST(
      0,
      100
      - LEAST(COALESCE(q.failed_queries, 0) * 2, 25)
      - LEAST(COALESCE(task_failures.failed_tasks, 0) * 4, 25)
      - LEAST(COALESCE(q.queued_ms, 0) / 60000, 20)
      - LEAST(COALESCE(sec.security_events, 0) * 0.5, 20)
      - LEAST(COALESCE(oc.object_changes, 0) * 0.25, 10)
    ) AS health_score,
    COALESCE(q.failed_queries, 0),
    COALESCE(task_failures.failed_tasks, 0) AS failed_tasks_24h,
    COALESCE(q.queued_ms, 0),
    COALESCE(wh.credits, 0),
    COALESCE(wh.cost_usd, 0),
    COALESCE(cx.cortex_cost, 0),
    COALESCE(sec.security_events, 0),
    COALESCE(oc.object_changes, 0),
    CASE
      WHEN COALESCE(task_failures.failed_tasks, 0) > 0 THEN 'Failed tasks'
      WHEN COALESCE(q.failed_queries, 0) > 0 THEN 'Failed queries'
      WHEN COALESCE(q.queued_ms, 0) > 0 THEN 'Queue pressure'
      WHEN COALESCE(sec.security_events, 0) > 0 THEN 'Login/security events'
      WHEN COALESCE(oc.object_changes, 0) > 0 THEN 'Object changes'
      ELSE 'No immediate exception'
    END AS top_risk
  FROM companies c
  LEFT JOIN q ON c.company = q.company
  LEFT JOIN wh ON c.company = wh.company
  LEFT JOIN oc ON c.company = oc.company
  LEFT JOIN task_failures ON c.company = task_failures.company
  LEFT JOIN sec ON c.company = sec.company
  LEFT JOIN cx ON c.company = cx.company;

  RETURN 'OVERWATCH control room mart refreshed.';
END;
$$;

-- Optional Cortex load. This is isolated because Cortex Code usage views might
-- not exist in every account/edition.
CREATE OR REPLACE PROCEDURE SP_OVERWATCH_LOAD_CORTEX()
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
DECLARE
  ai_credit_price NUMBER(18,4) DEFAULT 2.20;
BEGIN
  SELECT TRY_TO_NUMBER(SETTING_VALUE) INTO :ai_credit_price
  FROM OVERWATCH_SETTINGS
  WHERE SETTING_NAME = 'AI_CREDIT_PRICE_USD';

  ai_credit_price := COALESCE(ai_credit_price, 2.20);

  DELETE FROM FACT_CORTEX_DAILY
  WHERE USAGE_DATE >= DATEADD('DAY', -35, CURRENT_DATE());

  BEGIN
    INSERT INTO FACT_CORTEX_DAILY (
      USAGE_DATE, COMPANY, USER_ID, SOURCE, CREDITS_USED, EST_COST_USD, REQUEST_COUNT
    )
    SELECT
      raw.USAGE_DATE,
      CASE WHEN COALESCE(u.NAME, raw.USER_ID::VARCHAR) ILIKE 'TRXS_%' THEN 'Trexis' ELSE 'ALFA' END AS COMPANY,
      raw.USER_ID::VARCHAR AS USER_ID,
      raw.SOURCE,
      SUM(raw.CREDITS_USED) AS CREDITS_USED,
      ROUND(SUM(raw.CREDITS_USED) * :ai_credit_price, 2) AS EST_COST_USD,
      COUNT(*) AS REQUEST_COUNT
    FROM (
      SELECT TO_DATE(USAGE_TIME) AS USAGE_DATE, USER_ID, 'SNOWSIGHT' AS SOURCE, TOKEN_CREDITS AS CREDITS_USED
      FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
      WHERE USAGE_TIME >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())
      UNION ALL
      SELECT TO_DATE(USAGE_TIME) AS USAGE_DATE, USER_ID, 'CLI' AS SOURCE, TOKEN_CREDITS AS CREDITS_USED
      FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
      WHERE USAGE_TIME >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())
    ) raw
    LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON raw.USER_ID = u.USER_ID
    GROUP BY 1,2,3,4;
  EXCEPTION
    WHEN OTHER THEN
      INSERT INTO OVERWATCH_LOAD_AUDIT (LOAD_NAME, LOAD_STARTED_AT, LOAD_FINISHED_AT, STATUS, MESSAGE)
      VALUES ('SP_OVERWATCH_LOAD_CORTEX', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), 'SKIPPED', :SQLERRM);
  END;

  RETURN 'OVERWATCH Cortex load complete or skipped if usage views are unavailable.';
END;
$$;

CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_COST_GOVERNANCE()
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
DECLARE
  alert_email VARCHAR DEFAULT 'dba-alerts@yourcompany.com';
BEGIN
  SELECT COALESCE(
           MAX(CASE WHEN SETTING_NAME = 'DEFAULT_ALERT_EMAIL' THEN SETTING_VALUE END),
           'dba-alerts@yourcompany.com'
         )
    INTO :alert_email
  FROM OVERWATCH_SETTINGS;

  DELETE FROM FACT_COST_GOVERNANCE_SIGNAL
  WHERE SNAPSHOT_TS >= DATEADD('DAY', -2, CURRENT_TIMESTAMP());

  DELETE FROM FACT_COST_INCIDENT_TIMELINE
  WHERE EVENT_TS >= DATEADD('DAY', -2, CURRENT_TIMESTAMP());

  INSERT INTO FACT_COST_GOVERNANCE_SIGNAL (
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
    'OVERWATCH Cost Governance',
    'Exact warehouse metering',
    '7d complete-window credits ' || ROUND(CREDITS_7D, 2) || ' vs prior 7d ' || ROUND(BASELINE_CREDITS_7D, 2) || '; delta ' || ROUND(CREDIT_DELTA, 2) || ' credits.',
    'Open Cost & Contract root cause, assign owner, and route verified action only after proof.',
    'SELECT * FROM FACT_WAREHOUSE_HOURLY WHERE WAREHOUSE_NAME = ''' || WAREHOUSE_NAME || ''' ORDER BY HOUR_START DESC LIMIT 100;',
    ROUND(GREATEST(CREDIT_DELTA, 0) * CREDIT_PRICE_USD, 2),
    'FACT_WAREHOUSE_HOURLY'
  FROM priced;

  INSERT INTO FACT_COST_GOVERNANCE_SIGNAL (
    SNAPSHOT_TS, COMPANY, ENVIRONMENT, SIGNAL_TYPE, SEVERITY, ENTITY_TYPE, ENTITY_NAME,
    CONTROL_SURFACE, CONTROL_SCOPE, EVIDENCE, NEXT_ACTION, PROOF_QUERY, VALUE_AT_RISK_USD, SOURCE
  )
  SELECT
    CURRENT_TIMESTAMP(),
    COMPANY,
    'No Database Context',
    'CORTEX_BUDGET_AND_QUOTA',
    CASE WHEN SUM(COALESCE(EST_COST_USD, 0)) >= 500 THEN 'High' ELSE 'Medium' END,
    'USER_OR_AI_SERVICE',
    COALESCE(USER_ID, 'CORTEX'),
    'Snowflake Budget + Per-User AI Quota',
    'AI and shared resource budget',
    'Cortex 7d spend $' || ROUND(SUM(COALESCE(EST_COST_USD, 0)), 2) || ' across ' || SUM(COALESCE(REQUEST_COUNT, 0)) || ' request(s).',
    'Review shared AI budget, per-user quota, and first/last usage before broadening access.',
    'SELECT * FROM FACT_CORTEX_DAILY WHERE USAGE_DATE >= DATEADD(''DAY'', -7, CURRENT_DATE()) ORDER BY EST_COST_USD DESC LIMIT 100;',
    ROUND(SUM(COALESCE(EST_COST_USD, 0)), 2),
    'FACT_CORTEX_DAILY'
  FROM FACT_CORTEX_DAILY
  WHERE USAGE_DATE >= DATEADD('DAY', -7, CURRENT_DATE())
  GROUP BY COMPANY, USER_ID
  HAVING SUM(COALESCE(EST_COST_USD, 0)) > 0;

  INSERT INTO FACT_COST_GOVERNANCE_SIGNAL (
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
    'Change evidence',
    COUNT(*) || ' ALTER WAREHOUSE statement(s) in the last 48h by ' || COALESCE(MAX(USER_NAME), 'unknown user') || '.',
    'Compare the warehouse change query_id, actor, ticket, and rollback evidence to cost movement before tuning.',
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
      WHEN 'CORTEX_BUDGET_AND_QUOTA' THEN 3
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
  FROM FACT_COST_GOVERNANCE_SIGNAL
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
    'DBA / FinOps',
    'New',
    'EMAIL',
    :alert_email,
    :alert_email,
    'OVERWATCH ' || SEVERITY || ': Cost Governance - ' || ENTITY_NAME,
    'Company: ' || COMPANY || CHAR(10)
      || 'Environment: ' || ENVIRONMENT || CHAR(10)
      || 'Signal: ' || SIGNAL_TYPE || CHAR(10)
      || 'Entity: ' || ENTITY_NAME || CHAR(10) || CHAR(10)
      || EVIDENCE || CHAR(10) || CHAR(10)
      || 'Next action: ' || NEXT_ACTION || CHAR(10) || CHAR(10)
      || 'Proof query: ' || PROOF_QUERY,
    'EMAIL_READY'
  FROM FACT_COST_GOVERNANCE_SIGNAL s
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

  RETURN 'OVERWATCH cost governance refresh complete';
END;
$$;

-- -----------------------------------------------------------------------------
-- 5. Alert framework
-- -----------------------------------------------------------------------------

CREATE OR REPLACE TASK OVERWATCH_ANOMALY_CHECK
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = 'USING CRON 5 * * * * America/Chicago'
AS
INSERT INTO OVERWATCH_ALERTS (
  ALERT_TS, COMPANY, ENVIRONMENT, DATABASE_NAME, SCHEMA_NAME, WAREHOUSE_NAME,
  CATEGORY, ALERT_TYPE, SEVERITY, ENTITY_NAME, ENTITY, MESSAGE, DETAIL,
  SUGGESTED_ACTION, PROOF_QUERY, OWNER, STATUS, DELIVERY_METHOD,
  DELIVERY_TARGET, EMAIL_TARGET, EMAIL_SUBJECT, EMAIL_BODY, DELIVERY_STATUS
)
WITH alert_config AS (
  SELECT COALESCE(
           MAX(CASE WHEN SETTING_NAME = 'DEFAULT_ALERT_EMAIL' THEN SETTING_VALUE END),
           'dba-alerts@yourcompany.com'
         ) AS EMAIL_TARGET
  FROM OVERWATCH_SETTINGS
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
    AND UPPER(TASK_NAME) <> 'OVERWATCH_COST_SAVINGS_VERIFY'
  GROUP BY COMPANY, ENVIRONMENT, DATABASE_NAME, SCHEMA_NAME, WAREHOUSE_NAME, TASK_NAME
),
cost_savings_verifier_failures AS (
  SELECT
    DATABASE_NAME,
    SCHEMA_NAME,
    NAME AS TASK_NAME,
    COUNT(*) AS FAILURES,
    MAX(STATE) AS LATEST_STATE,
    MAX(SCHEDULED_TIME) AS LATEST_SCHEDULED_TIME,
    MAX(LEFT(ERROR_MESSAGE, 500)) AS SAMPLE_ERROR
  FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
  WHERE SCHEDULED_TIME >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
    AND UPPER(NAME) = 'OVERWATCH_COST_SAVINGS_VERIFY'
    AND UPPER(COALESCE(STATE, '')) IN ('FAILED', 'FAILED_WITH_ERROR', 'CANCELLED')
  GROUP BY DATABASE_NAME, SCHEMA_NAME, NAME
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
    'Open Cost & Contract, explain the bill movement, then route owner-backed savings actions.' AS SUGGESTED_ACTION,
    'SELECT * FROM FACT_WAREHOUSE_HOURLY WHERE WAREHOUSE_NAME = ''' || r.WAREHOUSE_NAME || ''' ORDER BY HOUR_START DESC LIMIT 100;' AS PROOF_QUERY,
    'DBA' AS OWNER
  FROM credit_recent r
  JOIN credit_baseline b ON r.COMPANY = b.COMPANY AND r.WAREHOUSE_NAME = b.WAREHOUSE_NAME
  WHERE b.AVG_DAILY_CREDITS > 0.1
    AND r.CURRENT_CREDITS > b.AVG_DAILY_CREDITS * 1.5

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
    'Open Warehouse Health, inspect pressure evidence, and route changed-only warehouse setting recommendations.',
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
    'ALFA',
    'No Database Context',
    DATABASE_NAME,
    SCHEMA_NAME,
    NULL,
    'Cost Control',
    'Cost Savings Verification Failure',
    CASE WHEN FAILURES >= 2 THEN 'Critical' ELSE 'High' END,
    COALESCE(DATABASE_NAME || '.' || SCHEMA_NAME || '.', '') || TASK_NAME,
    COALESCE(DATABASE_NAME || '.' || SCHEMA_NAME || '.', '') || TASK_NAME,
    FAILURES || ' failed savings verification task run(s) in the last 24 hours. Latest state: ' || COALESCE(LATEST_STATE, 'unknown') || '. Sample: ' || COALESCE(SAMPLE_ERROR, 'No sample error captured.'),
    FAILURES || ' failed savings verification task run(s) in the last 24 hours. Latest state: ' || COALESCE(LATEST_STATE, 'unknown') || '. Sample: ' || COALESCE(SAMPLE_ERROR, 'No sample error captured.'),
    'Open Cost & Contract verifier health, inspect TASK_HISTORY, keep savings estimated, and restore scheduled verification before claiming value.',
    'SELECT DATABASE_NAME, SCHEMA_NAME, NAME, STATE, SCHEDULED_TIME, COMPLETED_TIME, QUERY_ID, ERROR_MESSAGE FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY WHERE UPPER(NAME) = ''OVERWATCH_COST_SAVINGS_VERIFY'' ORDER BY SCHEDULED_TIME DESC LIMIT 100;',
    'DBA / FinOps'
  FROM cost_savings_verifier_failures

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
    'Change Control', 'Grant/Revoke Activity', 'Medium',
    COALESCE(DATABASE_NAME || '.' || SCHEMA_NAME, ROLE_NAME, USER_NAME, 'Account grant activity'),
    COALESCE(DATABASE_NAME || '.' || SCHEMA_NAME, ROLE_NAME, USER_NAME, 'Account grant activity'),
    CHANGE_COUNT || ' grant/revoke statement(s) by ' || COALESCE(USER_NAME, 'unknown user') || ' using role ' || COALESCE(ROLE_NAME, 'unknown role') || '.',
    CHANGE_COUNT || ' grant/revoke statement(s) by ' || COALESCE(USER_NAME, 'unknown user') || ' using role ' || COALESCE(ROLE_NAME, 'unknown role') || '.',
    'Open Security Posture, verify least-privilege approval, owner, ticket, and review date.',
    'SELECT * FROM FACT_OBJECT_CHANGE WHERE START_TIME >= DATEADD(''hour'', -24, CURRENT_TIMESTAMP()) AND (QUERY_TYPE ILIKE ''GRANT%'' OR QUERY_TYPE ILIKE ''REVOKE%'') ORDER BY START_TIME DESC LIMIT 100;',
    'DBA'
  FROM grant_changes

  UNION ALL

  SELECT
    COMPANY, 'No Database Context', NULL, NULL, WAREHOUSE_NAME,
    'Change Control', 'Warehouse Setting Change', 'Medium',
    WAREHOUSE_NAME,
    WAREHOUSE_NAME,
    CHANGE_COUNT || ' ALTER WAREHOUSE statement(s) by ' || COALESCE(USER_NAME, 'unknown user') || ' using role ' || COALESCE(ROLE_NAME, 'unknown role') || '.',
    CHANGE_COUNT || ' ALTER WAREHOUSE statement(s) by ' || COALESCE(USER_NAME, 'unknown user') || ' using role ' || COALESCE(ROLE_NAME, 'unknown role') || '.',
    'Open DBA Tools warehouse settings manager and verify changed-only SQL, approval, and rollback evidence.',
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
  'EMAIL_READY'
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

-- -----------------------------------------------------------------------------
-- 6. Task graph
-- -----------------------------------------------------------------------------

CREATE OR REPLACE TASK OVERWATCH_LOAD_HOURLY
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = 'USING CRON 25 * * * * America/Chicago'
AS
  CALL SP_OVERWATCH_LOAD_HOURLY();

CREATE OR REPLACE TASK OVERWATCH_LOAD_CORTEX
  WAREHOUSE = COMPUTE_WH
  AFTER OVERWATCH_LOAD_HOURLY
AS
  CALL SP_OVERWATCH_LOAD_CORTEX();

CREATE OR REPLACE TASK OVERWATCH_REFRESH_CONTROL_ROOM
  WAREHOUSE = COMPUTE_WH
  AFTER OVERWATCH_LOAD_CORTEX
AS
  CALL SP_OVERWATCH_REFRESH_CONTROL_ROOM();

CREATE OR REPLACE TASK OVERWATCH_COST_GOVERNANCE_REFRESH
  WAREHOUSE = COMPUTE_WH
  AFTER OVERWATCH_REFRESH_CONTROL_ROOM
AS
  CALL SP_OVERWATCH_REFRESH_COST_GOVERNANCE();

CREATE OR REPLACE TASK OVERWATCH_LOAD_DAILY
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = 'USING CRON 15 6 * * * America/Chicago'
AS
  CALL SP_OVERWATCH_LOAD_DAILY();

-- Resume child tasks first, then root scheduled tasks.
ALTER TASK OVERWATCH_LOAD_CORTEX RESUME;
ALTER TASK OVERWATCH_REFRESH_CONTROL_ROOM RESUME;
ALTER TASK OVERWATCH_COST_GOVERNANCE_REFRESH RESUME;
ALTER TASK OVERWATCH_ANOMALY_CHECK RESUME;
ALTER TASK OVERWATCH_LOAD_HOURLY RESUME;
ALTER TASK OVERWATCH_LOAD_DAILY RESUME;

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
SELECT 'FACT_COST_GOVERNANCE_SIGNAL', COUNT(*) FROM FACT_COST_GOVERNANCE_SIGNAL
UNION ALL
SELECT 'FACT_COST_INCIDENT_TIMELINE', COUNT(*) FROM FACT_COST_INCIDENT_TIMELINE
UNION ALL
SELECT 'MART_DBA_CONTROL_ROOM', COUNT(*) FROM MART_DBA_CONTROL_ROOM;




CALL SP_OVERWATCH_LOAD_HOURLY();
CALL SP_OVERWATCH_LOAD_CORTEX();
CALL SP_OVERWATCH_REFRESH_CONTROL_ROOM();
CALL SP_OVERWATCH_REFRESH_COST_GOVERNANCE();
CALL SP_OVERWATCH_LOAD_DAILY();
