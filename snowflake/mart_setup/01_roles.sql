-- OVERWATCH mart setup: 01_roles.sql

-- Create OVERWATCH access roles. Grants are applied in 08_grants.sql after objects exist.

-- Run files in numeric order from snowflake/mart_setup/.



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
-- 1b. Access roles
-- -----------------------------------------------------------------------------

CREATE ROLE IF NOT EXISTS SNOW_ACCOUNTADMINS;

CREATE ROLE IF NOT EXISTS SNOW_SYSADMINS;

COMMENT ON ROLE SNOW_ACCOUNTADMINS IS
    'Temporary OVERWATCH admin access role for account-level DBA monitoring and guarded actions.';

COMMENT ON ROLE SNOW_SYSADMINS IS
    'Temporary OVERWATCH admin access role for system DBA monitoring and guarded actions.';

