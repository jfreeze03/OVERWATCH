-- OVERWATCH safe performance-test setup
-- Target: DBA_MAINT_DB.OVERWATCH
-- Safety model:
--   * Creates only PERF_TEST_* objects.
--   * Full 5TB physical data generation is blocked unless explicitly enabled
--     in the full-scale script.
--   * Use COMPUTE_WH by default because it is the app execution warehouse.

USE DATABASE DBA_MAINT_DB;
USE SCHEMA OVERWATCH;
USE WAREHOUSE COMPUTE_WH;

CREATE TABLE IF NOT EXISTS PERF_TEST_RUN_CONTROL (
    CONTROL_NAME        VARCHAR(100) PRIMARY KEY,
    CONTROL_VALUE       VARCHAR(500),
    CONTROL_TYPE        VARCHAR(50),
    NOTES               VARCHAR(1000),
    UPDATED_AT          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

MERGE INTO PERF_TEST_RUN_CONTROL tgt
USING (
    SELECT * FROM VALUES
        ('DEFAULT_MODE', 'LIGHTWEIGHT_METADATA', 'STRING', 'Default mode creates metadata-scale proof plus bounded synthetic rows.'),
        ('MEDIUM_ROW_CAP', '5000000', 'NUMBER', 'Maximum generated rows for medium test mode without separate approval.'),
        ('FULL_5TB_ALLOWED', 'FALSE', 'BOOLEAN', 'Must be TRUE before running the physical 5TB script.'),
        ('APP_WAREHOUSE', 'COMPUTE_WH', 'STRING', 'Warehouse that runs OVERWATCH Streamlit app code.'),
        ('MAX_ALLOWED_WAREHOUSE_SIZE', 'MEDIUM', 'STRING', 'Do not run performance generation on larger warehouses without DBA approval.'),
        ('REQUIRE_AUTO_SUSPEND_SECONDS', '600', 'NUMBER', 'Warehouse should auto-suspend at or below this value for tests.')
) src(CONTROL_NAME, CONTROL_VALUE, CONTROL_TYPE, NOTES)
ON tgt.CONTROL_NAME = src.CONTROL_NAME
WHEN MATCHED THEN UPDATE SET
    CONTROL_VALUE = src.CONTROL_VALUE,
    CONTROL_TYPE = src.CONTROL_TYPE,
    NOTES = src.NOTES,
    UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (CONTROL_NAME, CONTROL_VALUE, CONTROL_TYPE, NOTES)
VALUES (src.CONTROL_NAME, src.CONTROL_VALUE, src.CONTROL_TYPE, src.NOTES);

CREATE TABLE IF NOT EXISTS PERF_TEST_RUNS (
    PERF_RUN_ID             VARCHAR(100) PRIMARY KEY,
    TEST_MODE               VARCHAR(50),
    STARTED_AT              TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    ENDED_AT                TIMESTAMP_NTZ,
    APP_URL                 VARCHAR(1000),
    CONCURRENT_USERS        NUMBER,
    ITERATIONS_PER_USER     NUMBER,
    TARGET_ENVIRONMENT      VARCHAR(50),
    TARGET_DATA_SCALE_TB    NUMBER(10,2),
    STATUS                  VARCHAR(50),
    NOTES                   VARCHAR(2000)
);

CREATE TABLE IF NOT EXISTS PERF_TEST_BENCHMARK_RESULTS (
    PERF_RUN_ID         VARCHAR(100),
    RECORDED_AT         TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    SOURCE              VARCHAR(100),
    METRIC_NAME         VARCHAR(200),
    METRIC_VALUE        FLOAT,
    METRIC_UNIT         VARCHAR(50),
    PASS_FAIL           VARCHAR(20),
    DETAILS             VARCHAR(2000)
);

CREATE TABLE IF NOT EXISTS PERF_TEST_RISK_REGISTER (
    RISK_ID             VARCHAR(100) PRIMARY KEY,
    RISK_AREA           VARCHAR(100),
    RISK_LEVEL          VARCHAR(20),
    RISK_DESCRIPTION    VARCHAR(2000),
    MITIGATION          VARCHAR(2000),
    OWNER               VARCHAR(200),
    STATUS              VARCHAR(50) DEFAULT 'Open'
);

MERGE INTO PERF_TEST_RISK_REGISTER tgt
USING (
    SELECT * FROM VALUES
        ('PERF_COST_001', 'Cost', 'High', 'Full-scale physical data can create storage and compute cost if executed accidentally.', 'Full 5TB script is blocked by default and separated from lightweight generation.', 'DBA / FinOps'),
        ('PERF_WH_001', 'Warehouse', 'High', 'Load tests can resume or keep COMPUTE_WH running longer than expected.', 'Validate warehouse size and auto-suspend before generation; prefer short bounded tests.', 'DBA'),
        ('PERF_CACHE_001', 'Result Cache', 'Medium', 'Repeated benchmark runs can look faster because Snowflake result cache is warm.', 'Run cold/warm phases separately and record QUERY_TAG/PERF_RUN_ID.', 'DBA Performance'),
        ('PERF_APP_001', 'Streamlit', 'Medium', 'Warehouse-runtime Streamlit starts a personal instance per viewer, which can increase load time.', 'Measure concurrent first-load latency and compare with warm reload latency.', 'DBA Platform')
) src(RISK_ID, RISK_AREA, RISK_LEVEL, RISK_DESCRIPTION, MITIGATION, OWNER)
ON tgt.RISK_ID = src.RISK_ID
WHEN MATCHED THEN UPDATE SET
    RISK_AREA = src.RISK_AREA,
    RISK_LEVEL = src.RISK_LEVEL,
    RISK_DESCRIPTION = src.RISK_DESCRIPTION,
    MITIGATION = src.MITIGATION,
    OWNER = src.OWNER
WHEN NOT MATCHED THEN INSERT (RISK_ID, RISK_AREA, RISK_LEVEL, RISK_DESCRIPTION, MITIGATION, OWNER)
VALUES (src.RISK_ID, src.RISK_AREA, src.RISK_LEVEL, src.RISK_DESCRIPTION, src.MITIGATION, src.OWNER);

CREATE OR REPLACE PROCEDURE SP_PERF_TEST_GUARDRAIL_CHECK(
    REQUESTED_MODE VARCHAR,
    ALLOW_FULL_5TB BOOLEAN
)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
    wh_size VARCHAR DEFAULT '';
    wh_state VARCHAR DEFAULT '';
    wh_auto_suspend NUMBER DEFAULT NULL;
BEGIN
    SHOW WAREHOUSES LIKE 'COMPUTE_WH';

    SELECT
        COALESCE("size", ''),
        COALESCE("state", ''),
        TRY_TO_NUMBER(TO_VARCHAR("auto_suspend"))
    INTO :wh_size, :wh_state, :wh_auto_suspend
    FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))
    LIMIT 1;

    IF (UPPER(:REQUESTED_MODE) = 'FULL_5TB' AND NOT :ALLOW_FULL_5TB) THEN
        RETURN 'BLOCKED: FULL_5TB requested but ALLOW_FULL_5TB is FALSE.';
    END IF;

    IF (UPPER(:wh_size) NOT IN ('X-SMALL', 'XSMALL', 'SMALL', 'MEDIUM')) THEN
        RETURN 'BLOCKED: COMPUTE_WH is larger than MEDIUM. Current size=' || :wh_size;
    END IF;

    IF (:wh_auto_suspend IS NULL OR :wh_auto_suspend > 600) THEN
        RETURN 'BLOCKED: COMPUTE_WH AUTO_SUSPEND must be <= 600 seconds for tests. Current=' || COALESCE(TO_VARCHAR(:wh_auto_suspend), 'NULL');
    END IF;

    RETURN 'OK: COMPUTE_WH state=' || :wh_state || ', size=' || :wh_size || ', auto_suspend=' || TO_VARCHAR(:wh_auto_suspend);
END;
$$;

CREATE OR REPLACE VIEW PERF_TEST_CONTROL_SUMMARY_V AS
SELECT
    CONTROL_NAME,
    CONTROL_VALUE,
    CONTROL_TYPE,
    NOTES,
    UPDATED_AT
FROM PERF_TEST_RUN_CONTROL
ORDER BY CONTROL_NAME;

-- Manual preflight:
-- CALL SP_PERF_TEST_GUARDRAIL_CHECK('LIGHTWEIGHT_METADATA', FALSE);
