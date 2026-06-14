-- OVERWATCH_AVAILABILITY.sql
-- Self-health checks for the OVERWATCH command center.

CREATE OR REPLACE VIEW DBA_MAINT_DB.OVERWATCH.OVERWATCH_SELF_HEALTH_V AS
WITH refresh_policy AS (
    SELECT
        surface,
        target_freshness_minutes,
        owner
    FROM DBA_MAINT_DB.OVERWATCH.OVERWATCH_REFRESH_POLICY
),
freshness AS (
    SELECT
        surface,
        MAX(refreshed_at) AS last_refreshed_at
    FROM DBA_MAINT_DB.OVERWATCH.OVERWATCH_SOURCE_FRESHNESS
    GROUP BY 1
),
query_cost AS (
    SELECT
        DATE(start_time) AS usage_date,
        COUNT(*) AS overwatch_queries,
        SUM(total_elapsed_time) / 1000 AS elapsed_sec,
        COUNT_IF(error_code IS NOT NULL) AS failed_queries
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE start_time >= DATEADD('day', -1, CURRENT_TIMESTAMP())
      AND query_tag ILIKE 'OVERWATCH%'
    GROUP BY 1
)
SELECT
    p.surface,
    p.owner,
    p.target_freshness_minutes,
    f.last_refreshed_at,
    DATEDIFF('minute', f.last_refreshed_at, CURRENT_TIMESTAMP()) AS freshness_age_minutes,
    CASE
        WHEN f.last_refreshed_at IS NULL THEN 'MISSING'
        WHEN DATEDIFF('minute', f.last_refreshed_at, CURRENT_TIMESTAMP()) > p.target_freshness_minutes THEN 'STALE'
        ELSE 'OK'
    END AS self_health_state,
    (SELECT SUM(overwatch_queries) FROM query_cost) AS last_24h_overwatch_queries,
    (SELECT SUM(failed_queries) FROM query_cost) AS last_24h_overwatch_query_failures
FROM refresh_policy p
LEFT JOIN freshness f
  ON p.surface = f.surface;
