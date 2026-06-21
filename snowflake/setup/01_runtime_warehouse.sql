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

