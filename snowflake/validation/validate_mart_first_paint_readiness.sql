-- OVERWATCH mart first-paint readiness validation.
-- This admin validation reports source readiness without relying on daily UI labels.

WITH expected_sources AS (
    SELECT
        column1::VARCHAR AS section_name,
        column2::VARCHAR AS source_key,
        column3::VARCHAR AS source_object,
        column4::NUMBER AS target_freshness_minutes
    FROM VALUES
        ('Executive Landing', 'section_command_packet', 'MART_SECTION_DECISION_CURRENT_FLAT', 60),
        ('DBA Control Room', 'section_command_packet', 'MART_SECTION_DECISION_CURRENT_FLAT', 60),
        ('Alert Center', 'section_command_packet', 'MART_SECTION_DECISION_CURRENT_FLAT', 60),
        ('Cost & Contract', 'section_command_packet', 'MART_SECTION_DECISION_CURRENT_FLAT', 60),
        ('Workload Operations', 'section_command_packet', 'MART_SECTION_DECISION_CURRENT_FLAT', 60),
        ('Security Monitoring', 'section_command_packet', 'MART_SECTION_DECISION_CURRENT_FLAT', 60)
),
objects AS (
    SELECT
        table_name AS source_object,
        TRUE AS object_exists
    FROM INFORMATION_SCHEMA.TABLES
    WHERE table_schema = CURRENT_SCHEMA()
),
packet_rows AS (
    SELECT
        SECTION_NAME AS section_name,
        COUNT(*) AS row_count,
        MAX(APP_QUERY_LOADED_AT) AS latest_load_ts,
        MAX(PACKET_CREATED_AT) AS latest_snapshot_ts
    FROM MART_SECTION_DECISION_CURRENT_FLAT
    WHERE COALESCE(IS_ACTIVE, TRUE)
    GROUP BY SECTION_NAME
)
SELECT
    e.section_name,
    e.source_key,
    e.source_object,
    COALESCE(o.object_exists, FALSE) AS object_exists,
    COALESCE(p.row_count, 0) AS row_count,
    p.latest_load_ts,
    p.latest_snapshot_ts,
    DATEDIFF('minute', p.latest_snapshot_ts, CURRENT_TIMESTAMP()) AS freshness_minutes,
    e.target_freshness_minutes,
    CASE
        WHEN COALESCE(o.object_exists, FALSE) = FALSE THEN 'SOURCE_NOT_CONFIGURED'
        WHEN COALESCE(p.row_count, 0) = 0 THEN 'REFRESH_NOT_RUN'
        WHEN DATEDIFF('minute', p.latest_snapshot_ts, CURRENT_TIMESTAMP()) > e.target_freshness_minutes THEN 'LOADED_STALE'
        ELSE 'LOADED_CURRENT'
    END AS state
FROM expected_sources e
LEFT JOIN objects o
    ON UPPER(o.source_object) = UPPER(e.source_object)
LEFT JOIN packet_rows p
    ON UPPER(p.section_name) = UPPER(e.section_name)
ORDER BY e.section_name, e.source_key;
