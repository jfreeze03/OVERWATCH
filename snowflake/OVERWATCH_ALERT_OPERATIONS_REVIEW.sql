-- OVERWATCH alert operations review.
-- Run from the OVERWATCH mart schema after setup/refresh when reviewing
-- native alert promotion, threshold tuning, company scope, and dynamic-table
-- risk before operational changes. This script is read-only.

-- 1) Core alert object readiness.
WITH required_objects(OBJECT_TYPE, OBJECT_NAME, PURPOSE) AS (
    SELECT * FROM VALUES
        ('TABLE', 'ALERT_EVENTS', 'Alert lifecycle event sink'),
        ('TABLE', 'ALERT_THRESHOLDS', 'DBA-owned threshold configuration'),
        ('TABLE', 'ALERT_NATIVE_OBJECT_REGISTRY', 'Native alert candidate registry'),
        ('TABLE', 'ALERT_REMEDIATION_POLICY', 'Dry-run and automation policy catalog'),
        ('TABLE', 'ALERT_REMEDIATION_DRY_RUN', 'Dry-run audit trail'),
        ('VIEW', 'ALERT_NATIVE_DEPLOYMENT_REVIEW_V', 'Native alert deployment review view'),
        ('PROCEDURE', 'SP_OVERWATCH_STAGE_ALERT_REMEDIATION_DRY_RUN', 'Dry-run staging procedure'),
        ('TABLE', 'FACT_CORTEX_DAILY', 'Cortex spend facts'),
        ('TABLE', 'FACT_WAREHOUSE_HOURLY', 'Warehouse credit and setting facts'),
        ('TABLE', 'FACT_QUERY_DETAIL_RECENT', 'User/query behavior facts'),
        ('TABLE', 'FACT_TASK_RUN', 'Task reliability facts'),
        ('TABLE', 'FACT_GRANT_DAILY', 'Access and privileged grant facts')
),
found_objects AS (
    SELECT 'TABLE' AS OBJECT_TYPE, TABLE_NAME AS OBJECT_NAME
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_SCHEMA = CURRENT_SCHEMA()
    UNION ALL
    SELECT 'VIEW' AS OBJECT_TYPE, TABLE_NAME AS OBJECT_NAME
    FROM INFORMATION_SCHEMA.VIEWS
    WHERE TABLE_SCHEMA = CURRENT_SCHEMA()
    UNION ALL
    SELECT 'PROCEDURE' AS OBJECT_TYPE, PROCEDURE_NAME AS OBJECT_NAME
    FROM INFORMATION_SCHEMA.PROCEDURES
    WHERE PROCEDURE_SCHEMA = CURRENT_SCHEMA()
)
SELECT
    'OBJECT_READINESS' AS REVIEW_AREA,
    r.OBJECT_TYPE,
    r.OBJECT_NAME,
    IFF(f.OBJECT_NAME IS NULL, 'MISSING', 'PRESENT') AS REVIEW_STATE,
    r.PURPOSE,
    CASE
        WHEN f.OBJECT_NAME IS NULL THEN 'Re-run mart setup or grant the active role visibility before promotion review.'
        ELSE 'Ready for operator review.'
    END AS NEXT_OPERATOR_STEP
FROM required_objects r
LEFT JOIN found_objects f
    ON f.OBJECT_TYPE = r.OBJECT_TYPE
   AND f.OBJECT_NAME = r.OBJECT_NAME
ORDER BY r.OBJECT_TYPE, r.OBJECT_NAME;

-- 2) Native alert promotion readiness from the registry.
SELECT
    'NATIVE_ALERT_PROMOTION_REVIEW' AS REVIEW_AREA,
    CATEGORY,
    ALERT_KEY,
    ALERT_OBJECT_NAME,
    TARGET_ROUTE,
    WAREHOUSE_NAME,
    SCHEDULE_TEXT,
    STATUS,
    ENABLED_BY_DEFAULT,
    CASE
        WHEN COALESCE(ENABLED_BY_DEFAULT, FALSE) THEN 'BLOCKED_ENABLED_BY_DEFAULT'
        WHEN UPPER(COALESCE(STATUS, 'CANDIDATE')) IN ('APPROVED', 'READY', 'READY_TO_DEPLOY') THEN 'READY_FOR_MANUAL_PROMOTION'
        WHEN UPPER(COALESCE(STATUS, 'CANDIDATE')) IN ('DEPLOYED', 'ACTIVE') THEN 'MONITOR_DEPLOYED_OBJECT'
        ELSE 'CANDIDATE_REVIEW_REQUIRED'
    END AS REVIEW_STATE,
    LENGTH(COALESCE(GENERATED_CREATE_SQL, '')) > 0 AS PROMOTION_SQL_PRESENT,
    LENGTH(COALESCE(GENERATED_DROP_SQL, '')) > 0 AS ROLLBACK_SQL_PRESENT,
    SAFETY_NOTE,
    CASE
        WHEN COALESCE(ENABLED_BY_DEFAULT, FALSE) THEN 'Set ENABLED_BY_DEFAULT to false and repeat review.'
        WHEN UPPER(COALESCE(STATUS, 'CANDIDATE')) IN ('APPROVED', 'READY', 'READY_TO_DEPLOY') THEN 'Review reviewer, threshold, warehouse, route, and rollback evidence before manual promotion.'
        WHEN UPPER(COALESCE(STATUS, 'CANDIDATE')) IN ('DEPLOYED', 'ACTIVE') THEN 'Compare event volume, delivery log, dry-run status, and false-positive rate.'
        ELSE 'Tune threshold and workflow route before marking ready.'
    END AS NEXT_OPERATOR_STEP
FROM ALERT_NATIVE_OBJECT_REGISTRY
ORDER BY
    CASE
        WHEN COALESCE(ENABLED_BY_DEFAULT, FALSE) THEN 0
        WHEN UPPER(COALESCE(STATUS, 'CANDIDATE')) IN ('APPROVED', 'READY', 'READY_TO_DEPLOY') THEN 1
        WHEN UPPER(COALESCE(STATUS, 'CANDIDATE')) IN ('DEPLOYED', 'ACTIVE') THEN 3
        ELSE 2
    END,
    CATEGORY,
    ALERT_KEY;

-- 3) Threshold tuning candidates from current marts.
WITH threshold_cfg AS (
    SELECT
        THRESHOLD_KEY,
        CATEGORY,
        SIGNAL_NAME,
        SEVERITY,
        THRESHOLD_VALUE,
        BASELINE_WINDOW_DAYS,
        CURRENT_WINDOW_MINUTES,
        OWNER,
        NOTIFICATION_CHANNEL
    FROM ALERT_THRESHOLDS
),
warehouse_current AS (
    SELECT
        COALESCE(NULLIF(COMPANY, ''), 'Shared/Unclassified') AS COMPANY,
        SUM(COALESCE(CREDITS_USED, 0)) AS CURRENT_VALUE
    FROM FACT_WAREHOUSE_HOURLY
    WHERE HOUR_START >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
    GROUP BY COALESCE(NULLIF(COMPANY, ''), 'Shared/Unclassified')
),
warehouse_baseline AS (
    SELECT
        COMPANY,
        AVG(DAILY_CREDITS) AS BASELINE_VALUE
    FROM (
        SELECT
            COALESCE(NULLIF(COMPANY, ''), 'Shared/Unclassified') AS COMPANY,
            TO_DATE(HOUR_START) AS USAGE_DAY,
            SUM(COALESCE(CREDITS_USED, 0)) AS DAILY_CREDITS
        FROM FACT_WAREHOUSE_HOURLY
        WHERE HOUR_START >= DATEADD('day', -31, CURRENT_TIMESTAMP())
          AND HOUR_START < DATEADD('day', -1, CURRENT_TIMESTAMP())
        GROUP BY COALESCE(NULLIF(COMPANY, ''), 'Shared/Unclassified'), TO_DATE(HOUR_START)
    )
    GROUP BY COMPANY
),
cortex_current AS (
    SELECT
        COALESCE(NULLIF(COMPANY, ''), 'Shared/Unclassified') AS COMPANY,
        SUM(COALESCE(EST_COST_USD, 0)) AS CURRENT_VALUE
    FROM FACT_CORTEX_DAILY
    WHERE USAGE_DATE >= DATEADD('day', -7, CURRENT_DATE())
    GROUP BY COALESCE(NULLIF(COMPANY, ''), 'Shared/Unclassified')
),
cortex_baseline AS (
    SELECT
        COALESCE(NULLIF(COMPANY, ''), 'Shared/Unclassified') AS COMPANY,
        AVG(DAILY_COST) * 7 AS BASELINE_VALUE
    FROM (
        SELECT
            COALESCE(NULLIF(COMPANY, ''), 'Shared/Unclassified') AS COMPANY,
            USAGE_DATE,
            SUM(COALESCE(EST_COST_USD, 0)) AS DAILY_COST
        FROM FACT_CORTEX_DAILY
        WHERE USAGE_DATE >= DATEADD('day', -37, CURRENT_DATE())
          AND USAGE_DATE < DATEADD('day', -7, CURRENT_DATE())
        GROUP BY COALESCE(NULLIF(COMPANY, ''), 'Shared/Unclassified'), USAGE_DATE
    )
    GROUP BY COMPANY
),
behavior_current AS (
    SELECT
        COMPANY,
        MAX(USER_PATTERN_COUNT) AS CURRENT_VALUE
    FROM (
        SELECT
            COALESCE(NULLIF(COMPANY, ''), 'Shared/Unclassified') AS COMPANY,
            USER_NAME,
            ROLE_NAME,
            WAREHOUSE_NAME,
            COUNT(*) AS USER_PATTERN_COUNT
        FROM FACT_QUERY_DETAIL_RECENT
        WHERE START_TIME >= DATEADD('hour', -2, CURRENT_TIMESTAMP())
        GROUP BY
            COALESCE(NULLIF(COMPANY, ''), 'Shared/Unclassified'),
            USER_NAME,
            ROLE_NAME,
            WAREHOUSE_NAME
    )
    GROUP BY COMPANY
),
task_current AS (
    SELECT
        COALESCE(NULLIF(COMPANY, ''), 'Shared/Unclassified') AS COMPANY,
        COUNT(*) AS CURRENT_VALUE
    FROM FACT_TASK_RUN
    WHERE SCHEDULED_TIME >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
      AND UPPER(COALESCE(STATE, '')) IN ('FAILED', 'FAILED_WITH_ERROR', 'SKIPPED', 'CANCELLED')
    GROUP BY COALESCE(NULLIF(COMPANY, ''), 'Shared/Unclassified')
),
security_current AS (
    SELECT
        COALESCE(NULLIF(COMPANY, ''), 'Shared/Unclassified') AS COMPANY,
        COUNT(*) AS CURRENT_VALUE
    FROM FACT_GRANT_DAILY
    WHERE SNAPSHOT_DATE >= DATEADD('day', -2, CURRENT_DATE())
      AND CREATED_ON >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
      AND DELETED_ON IS NULL
      AND UPPER(COALESCE(ROLE_NAME, '')) IN ('ACCOUNTADMIN', 'SECURITYADMIN', 'SYSADMIN', 'ORGADMIN')
    GROUP BY COALESCE(NULLIF(COMPANY, ''), 'Shared/Unclassified')
),
tuning_rows AS (
    SELECT
        t.THRESHOLD_KEY,
        t.CATEGORY,
        t.SIGNAL_NAME,
        t.SEVERITY,
        c.COMPANY,
        c.CURRENT_VALUE,
        b.BASELINE_VALUE,
        t.THRESHOLD_VALUE,
        'FACT_CORTEX_DAILY' AS SOURCE_OBJECT
    FROM threshold_cfg t
    LEFT JOIN cortex_current c ON TRUE
    LEFT JOIN cortex_baseline b ON b.COMPANY = c.COMPANY
    WHERE t.THRESHOLD_KEY = 'COST_CORTEX_SPEND_SPIKE'
    UNION ALL
    SELECT
        t.THRESHOLD_KEY,
        t.CATEGORY,
        t.SIGNAL_NAME,
        t.SEVERITY,
        c.COMPANY,
        c.CURRENT_VALUE,
        b.BASELINE_VALUE,
        t.THRESHOLD_VALUE,
        'FACT_WAREHOUSE_HOURLY' AS SOURCE_OBJECT
    FROM threshold_cfg t
    LEFT JOIN warehouse_current c ON TRUE
    LEFT JOIN warehouse_baseline b ON b.COMPANY = c.COMPANY
    WHERE t.THRESHOLD_KEY = 'COST_WAREHOUSE_CREDIT_SPIKE'
    UNION ALL
    SELECT
        t.THRESHOLD_KEY,
        t.CATEGORY,
        t.SIGNAL_NAME,
        t.SEVERITY,
        c.COMPANY,
        c.CURRENT_VALUE,
        NULL AS BASELINE_VALUE,
        t.THRESHOLD_VALUE,
        'FACT_QUERY_DETAIL_RECENT' AS SOURCE_OBJECT
    FROM threshold_cfg t
    LEFT JOIN behavior_current c ON TRUE
    WHERE t.THRESHOLD_KEY = 'BEHAVIOR_USER_QUERY_ANOMALY'
    UNION ALL
    SELECT
        t.THRESHOLD_KEY,
        t.CATEGORY,
        t.SIGNAL_NAME,
        t.SEVERITY,
        c.COMPANY,
        c.CURRENT_VALUE,
        NULL AS BASELINE_VALUE,
        t.THRESHOLD_VALUE,
        'FACT_TASK_RUN' AS SOURCE_OBJECT
    FROM threshold_cfg t
    LEFT JOIN task_current c ON TRUE
    WHERE t.THRESHOLD_KEY = 'PIPELINE_TASK_FAILURE'
    UNION ALL
    SELECT
        t.THRESHOLD_KEY,
        t.CATEGORY,
        t.SIGNAL_NAME,
        t.SEVERITY,
        c.COMPANY,
        c.CURRENT_VALUE,
        NULL AS BASELINE_VALUE,
        t.THRESHOLD_VALUE,
        'FACT_GRANT_DAILY' AS SOURCE_OBJECT
    FROM threshold_cfg t
    LEFT JOIN security_current c ON TRUE
    WHERE t.THRESHOLD_KEY = 'SECURITY_PRIVILEGE_ESCALATION'
)
SELECT
    'THRESHOLD_TUNING_REVIEW' AS REVIEW_AREA,
    THRESHOLD_KEY,
    CATEGORY,
    SIGNAL_NAME,
    SEVERITY,
    COALESCE(COMPANY, 'No recent scoped rows') AS COMPANY,
    COALESCE(CURRENT_VALUE, 0) AS CURRENT_VALUE,
    COALESCE(BASELINE_VALUE, 0) AS BASELINE_VALUE,
    THRESHOLD_VALUE,
    SOURCE_OBJECT,
    CASE
        WHEN CURRENT_VALUE IS NULL THEN 'NO_RECENT_SIGNAL'
        WHEN THRESHOLD_KEY = 'COST_WAREHOUSE_CREDIT_SPIKE'
             AND CURRENT_VALUE > GREATEST(10, COALESCE(BASELINE_VALUE, 0) * THRESHOLD_VALUE) THEN 'REVIEW_THRESHOLD_OR_INCIDENT'
        WHEN THRESHOLD_KEY = 'COST_CORTEX_SPEND_SPIKE'
             AND CURRENT_VALUE > GREATEST(THRESHOLD_VALUE, COALESCE(BASELINE_VALUE, 0) * 1.5) THEN 'REVIEW_THRESHOLD_OR_INCIDENT'
        WHEN CURRENT_VALUE >= THRESHOLD_VALUE THEN 'ACTIVE_SIGNAL'
        ELSE 'WATCH_BASELINE'
    END AS REVIEW_STATE,
    CASE
        WHEN CURRENT_VALUE IS NULL THEN 'Keep current threshold; no recent scoped rows in the mart.'
        WHEN THRESHOLD_KEY LIKE 'COST_%' THEN 'Compare ALFA/Trexis split, Snowflake Admin cost view, and workflow route before threshold changes.'
        ELSE 'Compare current rows with workflow expectations before threshold changes.'
    END AS NEXT_OPERATOR_STEP
FROM tuning_rows
ORDER BY REVIEW_STATE, CATEGORY, THRESHOLD_KEY, COMPANY;

-- 4) Company and environment scope quality for ALFA/Trexis alert routing.
WITH scoped_rows AS (
    SELECT
        'ALERT_EVENTS' AS SOURCE_OBJECT,
        COALESCE(NULLIF(COMPANY, ''), 'Shared/Unclassified') AS COMPANY,
        COALESCE(NULLIF(ENVIRONMENT, ''), 'No Environment') AS ENVIRONMENT,
        ALERT_TS AS OBSERVED_AT
    FROM ALERT_EVENTS
    WHERE ALERT_TS >= DATEADD('day', -14, CURRENT_TIMESTAMP())
    UNION ALL
    SELECT
        'FACT_WAREHOUSE_HOURLY' AS SOURCE_OBJECT,
        COALESCE(NULLIF(COMPANY, ''), 'Shared/Unclassified') AS COMPANY,
        'ALL' AS ENVIRONMENT,
        HOUR_START AS OBSERVED_AT
    FROM FACT_WAREHOUSE_HOURLY
    WHERE HOUR_START >= DATEADD('day', -14, CURRENT_TIMESTAMP())
    UNION ALL
    SELECT
        'FACT_QUERY_DETAIL_RECENT' AS SOURCE_OBJECT,
        COALESCE(NULLIF(COMPANY, ''), 'Shared/Unclassified') AS COMPANY,
        COALESCE(NULLIF(ENVIRONMENT, ''), 'No Environment') AS ENVIRONMENT,
        START_TIME AS OBSERVED_AT
    FROM FACT_QUERY_DETAIL_RECENT
    WHERE START_TIME >= DATEADD('day', -14, CURRENT_TIMESTAMP())
    UNION ALL
    SELECT
        'FACT_TASK_RUN' AS SOURCE_OBJECT,
        COALESCE(NULLIF(COMPANY, ''), 'Shared/Unclassified') AS COMPANY,
        COALESCE(NULLIF(ENVIRONMENT, ''), 'No Environment') AS ENVIRONMENT,
        SCHEDULED_TIME AS OBSERVED_AT
    FROM FACT_TASK_RUN
    WHERE SCHEDULED_TIME >= DATEADD('day', -14, CURRENT_TIMESTAMP())
    UNION ALL
    SELECT
        'FACT_CORTEX_DAILY' AS SOURCE_OBJECT,
        COALESCE(NULLIF(COMPANY, ''), 'Shared/Unclassified') AS COMPANY,
        'ALL' AS ENVIRONMENT,
        USAGE_DATE::TIMESTAMP_NTZ AS OBSERVED_AT
    FROM FACT_CORTEX_DAILY
    WHERE USAGE_DATE >= DATEADD('day', -14, CURRENT_DATE())
    UNION ALL
    SELECT
        'FACT_GRANT_DAILY' AS SOURCE_OBJECT,
        COALESCE(NULLIF(COMPANY, ''), 'Shared/Unclassified') AS COMPANY,
        'No Database Context' AS ENVIRONMENT,
        SNAPSHOT_DATE::TIMESTAMP_NTZ AS OBSERVED_AT
    FROM FACT_GRANT_DAILY
    WHERE SNAPSHOT_DATE >= DATEADD('day', -14, CURRENT_DATE())
)
SELECT
    'COMPANY_SCOPE_REVIEW' AS REVIEW_AREA,
    SOURCE_OBJECT,
    COMPANY,
    ENVIRONMENT,
    COUNT(*) AS ROW_COUNT,
    MIN(OBSERVED_AT) AS FIRST_OBSERVED_AT,
    MAX(OBSERVED_AT) AS LAST_OBSERVED_AT,
    CASE
        WHEN UPPER(COMPANY) IN ('ALFA', 'TREXIS') THEN 'COMPANY_SCOPED'
        WHEN UPPER(COMPANY) IN ('SHARED/UNCLASSIFIED', 'ACCOUNT-WIDE', 'NO RECENT SCOPED ROWS') THEN 'SCOPE_REVIEW'
        ELSE 'CUSTOM_COMPANY_VALUE'
    END AS REVIEW_STATE,
    CASE
        WHEN UPPER(COMPANY) = 'TREXIS' THEN 'Confirm TRXS role/warehouse mapping still explains this row set.'
        WHEN UPPER(COMPANY) = 'ALFA' THEN 'Confirm non-TRXS role/warehouse mapping still explains this row set.'
        WHEN UPPER(COMPANY) = 'SHARED/UNCLASSIFIED' THEN 'Improve role, warehouse, or owner mapping before company-specific alert routing.'
        ELSE 'Review company mapping taxonomy.'
    END AS NEXT_OPERATOR_STEP
FROM scoped_rows
GROUP BY SOURCE_OBJECT, COMPANY, ENVIRONMENT
ORDER BY SOURCE_OBJECT, REVIEW_STATE, ROW_COUNT DESC;

-- 5) Dynamic table compatibility reminder for alert marts.
SELECT
    'DYNAMIC_TABLE_COMPATIBILITY_REVIEW' AS REVIEW_AREA,
    'Run OVERWATCH_DYNAMIC_TABLE_SECURE_VIEW_AUDIT.sql from this schema.' AS REVIEW_STEP,
    'Alert and cost marts should remain physical tables loaded by procedures/tasks when any source dependency can include secure views.' AS WHY_THIS_MATTERS,
    'Review generated table, procedure, and task stubs from that audit before rebuilding marts.' AS NEXT_OPERATOR_STEP;
