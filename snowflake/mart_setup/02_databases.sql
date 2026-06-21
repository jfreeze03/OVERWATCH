-- OVERWATCH mart setup: 02_databases.sql

-- Create database, warehouse, resource monitor, and database context.

-- Run files in numeric order from snowflake/mart_setup/.



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

USE DATABASE DBA_MAINT_DB;

