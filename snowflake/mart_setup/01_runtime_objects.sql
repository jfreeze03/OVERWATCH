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
--   - current COMPUTE_WH runtime warehouse, XSMALL, 60-second auto-suspend
--   - current runtime warehouse resource monitor with notify/suspend guardrails
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

CREATE WAREHOUSE IF NOT EXISTS COMPUTE_WH
  WAREHOUSE_SIZE = XSMALL
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  STATEMENT_TIMEOUT_IN_SECONDS = 600
  COMMENT = 'Current warehouse for OVERWATCH Streamlit app runtime and mart refresh until a dedicated warehouse is approved.';

CREATE RESOURCE MONITOR IF NOT EXISTS COMPUTE_WH_RM
  WITH CREDIT_QUOTA = 50
       FREQUENCY = MONTHLY
       START_TIMESTAMP = IMMEDIATELY
       TRIGGERS ON 80 PERCENT DO NOTIFY
                ON 100 PERCENT DO SUSPEND;

ALTER WAREHOUSE IF EXISTS COMPUTE_WH
  SET RESOURCE_MONITOR = COMPUTE_WH_RM;

USE DATABASE DBA_MAINT_DB;
USE SCHEMA OVERWATCH;

