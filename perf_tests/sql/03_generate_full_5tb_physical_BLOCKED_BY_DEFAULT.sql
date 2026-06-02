-- OVERWATCH full physical 5TB test mode
-- This script is intentionally blocked by default. Do not run it unless DBA,
-- FinOps, and platform owners have approved the compute and storage cost.

USE DATABASE DBA_MAINT_DB;
USE SCHEMA OVERWATCH;
USE WAREHOUSE COMPUTE_WH;

-- Required explicit changes before any physical 5TB creation:
--   1. Confirm resource monitor and budget approval.
--   2. Confirm COMPUTE_WH size/auto-suspend or switch to an approved isolated
--      PERF_TEST warehouse.
--   3. Change ALLOW_FULL_5TB below to TRUE.
--   4. Uncomment the CTAS block at the bottom.

SET ALLOW_FULL_5TB = FALSE;

CALL SP_PERF_TEST_GUARDRAIL_CHECK('FULL_5TB', $ALLOW_FULL_5TB);

-- Keep this block commented until the guardrail call returns OK and approval is recorded.
--
-- CREATE OR REPLACE TABLE PERF_TEST_5TB_PHYSICAL_FACT
-- CLUSTER BY (EVENT_DATE, WAREHOUSE_NAME, DATABASE_NAME)
-- AS
-- SELECT
--     DATEADD('day', -MOD(SEQ4(), 365), CURRENT_DATE()) AS EVENT_DATE,
--     'WH_' || LPAD(MOD(SEQ4(), 60)::VARCHAR, 3, '0') AS WAREHOUSE_NAME,
--     'PERF_TEST_DB_' || LPAD(MOD(SEQ4(), 16)::VARCHAR, 2, '0') AS DATABASE_NAME,
--     'USER_' || LPAD(MOD(SEQ4(), 2000)::VARCHAR, 5, '0') AS USER_NAME,
--     'ROLE_' || LPAD(MOD(SEQ4(), 300)::VARCHAR, 4, '0') AS ROLE_NAME,
--     UNIFORM(0, 1000000000000, RANDOM()) AS BYTES_SCANNED,
--     UNIFORM(0, 500000, RANDOM()) AS ELAPSED_MS,
--     RPAD(SHA2(SEQ4()::VARCHAR), 4096, 'X') AS PAYLOAD_4KB
-- FROM TABLE(GENERATOR(ROWCOUNT => 1342177280));
--
-- The rowcount above is approximately 5 TiB at 4 KiB payload per row before
-- compression. Actual Snowflake storage can differ materially because of
-- compression and micro-partition encoding. Validate storage with:
--
-- SELECT TABLE_NAME, ACTIVE_BYTES / POWER(1024, 4) AS ACTIVE_TB
-- FROM INFORMATION_SCHEMA.TABLE_STORAGE_METRICS
-- WHERE TABLE_NAME = 'PERF_TEST_5TB_PHYSICAL_FACT';
