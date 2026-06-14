-- OVERWATCH_TAG_SETUP.sql
-- Optional Snowflake-native cost and ownership allocation tags.

CREATE TAG IF NOT EXISTS DBA_MAINT_DB.OVERWATCH.OVERWATCH_OWNER
    COMMENT = 'Business or DBA owner used by OVERWATCH routing and chargeback.';

CREATE TAG IF NOT EXISTS DBA_MAINT_DB.OVERWATCH.OVERWATCH_COST_CENTER
    COMMENT = 'FinOps cost center used by OVERWATCH allocation reports.';

CREATE TAG IF NOT EXISTS DBA_MAINT_DB.OVERWATCH.OVERWATCH_CRITICALITY
    ALLOWED_VALUES 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'
    COMMENT = 'Operational criticality used by OVERWATCH alert priority and SLA scoring.';

CREATE OR REPLACE VIEW DBA_MAINT_DB.OVERWATCH.OVERWATCH_TAG_COVERAGE_V AS
WITH coverage AS (
    SELECT
        object_database,
        object_schema,
        object_name,
        object_domain,
        COUNT_IF(tag_name = 'OVERWATCH_OWNER') AS owner_tagged,
        COUNT_IF(tag_name = 'OVERWATCH_COST_CENTER') AS cost_center_tagged,
        COUNT_IF(tag_name = 'OVERWATCH_CRITICALITY') AS criticality_tagged
    FROM SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES
    WHERE tag_database = 'DBA_MAINT_DB'
      AND tag_schema = 'OVERWATCH'
    GROUP BY 1, 2, 3, 4
)
SELECT
    object_database,
    object_schema,
    object_name,
    object_domain,
    owner_tagged,
    cost_center_tagged,
    criticality_tagged,
    CASE
        WHEN owner_tagged > 0 AND cost_center_tagged > 0 AND criticality_tagged > 0 THEN 'COMPLETE'
        WHEN owner_tagged > 0 OR cost_center_tagged > 0 OR criticality_tagged > 0 THEN 'PARTIAL'
        ELSE 'MISSING'
    END AS tag_readiness
FROM coverage;

-- Example:
-- ALTER WAREHOUSE WH_ALFA_LOAD SET TAG DBA_MAINT_DB.OVERWATCH.OVERWATCH_OWNER = 'DBA';
-- ALTER WAREHOUSE WH_ALFA_LOAD SET TAG DBA_MAINT_DB.OVERWATCH.OVERWATCH_COST_CENTER = 'ALFA_EDW';
-- ALTER WAREHOUSE WH_ALFA_LOAD SET TAG DBA_MAINT_DB.OVERWATCH.OVERWATCH_CRITICALITY = 'HIGH';
