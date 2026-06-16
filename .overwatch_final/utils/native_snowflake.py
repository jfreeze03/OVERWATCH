"""Snowflake-native capability contracts for production command boards."""

from __future__ import annotations

from textwrap import dedent


NATIVE_SNOWFLAKE_CONTRACT_VERSION = "2026-06-14-native-snowflake-contract-v1"


def _sql(text: str) -> str:
    return dedent(text).strip() + "\n"


def native_capability_lanes() -> tuple[dict[str, str], ...]:
    """Return the next native Snowflake proof lanes that make OVERWATCH credible."""
    return (
        {
            "label": "Data Quality / DMF",
            "value": "DATA_METRIC_FUNCTIONS",
            "state": "Next",
            "detail": "Use Snowflake DMF references and monitoring results where enabled; fall back to metadata checks.",
        },
        {
            "label": "Native alerts",
            "value": "SHOW ALERTS",
            "state": "Deployable",
            "detail": "Register alert objects, schedules, warehouses, actions, and last run state.",
        },
        {
            "label": "Tag allocation",
            "value": "TAG_REFERENCES",
            "state": "reviewed",
            "detail": "Prove owner, cost center, criticality, and untagged spend risk.",
        },
        {
            "label": "OVERWATCH self-cost",
            "value": "QUERY_TAG",
            "state": "Required",
            "detail": "Track app queries, p95, failures, bytes scanned, and warehouse cost by section.",
        },
        {
            "label": "Executive digest",
            "value": "EXECUTIVE_DIGEST_HISTORY",
            "state": "Push",
            "detail": "Daily digest history should match the boss-page numbers and owner actions.",
        },
        {
            "label": "Org rollup",
            "value": "ORGANIZATION_USAGE",
            "state": "Optional",
            "detail": "Expose only when ORGADMIN privileges exist; otherwise stay single-account.",
        },
    )


def native_capability_setup_objects() -> tuple[tuple[str, str], ...]:
    """Return setup objects supporting the native Snowflake capability lanes."""
    return (
        ("DMF proof", "SNOWFLAKE.ACCOUNT_USAGE.DATA_METRIC_FUNCTION_REFERENCES"),
        ("Alert registry", "SHOW ALERTS / ALERT_HISTORY"),
        ("Tag coverage", "OVERWATCH_TAG_COVERAGE_V"),
        ("Self-health", "OVERWATCH_SELF_HEALTH_V"),
        ("Digest", "EXECUTIVE_DIGEST_HISTORY"),
        ("Org usage", "SNOWFLAKE.ORGANIZATION_USAGE"),
    )


def build_data_quality_dmf_sql(days: int = 7) -> str:
    """Build a DMF/data-quality registry query with friendly fallback semantics."""
    days = max(1, int(days or 7))
    return _sql(f"""
        -- Data Metric Function registry. Some accounts expose these views only
        -- after DMFs are enabled; handle privilege gaps gracefully in the app.
        SELECT
            database_name,
            schema_name,
            table_name,
            metric_name,
            schedule,
            state,
            last_run_time,
            DATEDIFF('HOUR', last_run_time, CURRENT_TIMESTAMP()) AS hours_since_last_run,
            CASE
                WHEN state ILIKE 'FAILED%' THEN 'HIGH'
                WHEN last_run_time < DATEADD('DAY', -{days}, CURRENT_TIMESTAMP()) THEN 'MEDIUM'
                ELSE 'LOW'
            END AS severity,
            CASE
                WHEN state ILIKE 'FAILED%' THEN 'Open Data Quality checks and inspect latest DMF failure.'
                WHEN last_run_time < DATEADD('DAY', -{days}, CURRENT_TIMESTAMP()) THEN 'Refresh or reschedule stale DMF.'
                ELSE 'DMF proof is current.'
            END AS recommended_action
        FROM SNOWFLAKE.ACCOUNT_USAGE.DATA_METRIC_FUNCTION_REFERENCES
        ORDER BY
            CASE severity WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END,
            hours_since_last_run DESC;
    """)


def build_alert_object_registry_sql() -> str:
    """Build native Snowflake ALERT object inventory SQL."""
    return _sql("""
        -- Native ALERT object registry. Use SHOW ALERTS for current state and
        -- ALERT_HISTORY for recent execution proof when available.
        SHOW ALERTS IN ACCOUNT;

        SELECT
            name,
            database_name,
            schema_name,
            state,
            scheduled_time,
            completed_time,
            error_code,
            error_message,
            CASE
                WHEN state = 'FAILED' THEN 'HIGH'
                WHEN state = 'SUSPENDED' THEN 'MEDIUM'
                ELSE 'LOW'
            END AS severity
        FROM TABLE(INFORMATION_SCHEMA.ALERT_HISTORY(
            SCHEDULED_TIME_RANGE_START => DATEADD('DAY', -7, CURRENT_TIMESTAMP())
        ))
        ORDER BY scheduled_time DESC;
    """)


def build_tag_allocation_sql() -> str:
    """Build tag coverage SQL for owner/cost-center allocation proof."""
    return _sql("""
        SELECT
            object_database,
            object_schema,
            object_name,
            domain AS object_type,
            tag_name,
            tag_value,
            COUNT(*) OVER (PARTITION BY object_database, object_schema) AS tagged_objects_in_schema
        FROM SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES
        WHERE tag_name IN ('OVERWATCH_OWNER', 'OVERWATCH_COST_CENTER', 'OVERWATCH_CRITICALITY')
        ORDER BY object_database, object_schema, object_name, tag_name;
    """)


def build_overwatch_self_cost_sql(days: int = 7) -> str:
    """Build OVERWATCH self-cost and reliability evidence from app query tags."""
    days = max(1, int(days or 7))
    return _sql(f"""
        WITH app_queries AS (
            SELECT
                query_id,
                start_time,
                warehouse_name,
                query_tag,
                execution_status,
                total_elapsed_time / 1000 AS elapsed_sec,
                bytes_scanned,
                error_message,
                REGEXP_SUBSTR(query_tag, 'section=([^|]+)', 1, 1, 'e', 1) AS section_name
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE start_time >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
              AND query_tag ILIKE 'OVERWATCH%'
        )
        SELECT
            COALESCE(section_name, 'UNKNOWN') AS section_name,
            COUNT(*) AS query_count,
            COUNT_IF(execution_status = 'FAIL') AS failed_queries,
            ROUND(AVG(elapsed_sec), 2) AS avg_elapsed_sec,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY elapsed_sec), 2) AS p95_elapsed_sec,
            ROUND(SUM(bytes_scanned) / POWER(1024, 3), 2) AS gb_scanned,
            MAX_BY(query_id, elapsed_sec) AS slowest_query_id,
            MAX_BY(error_message, start_time) AS latest_error,
            CASE
                WHEN COUNT_IF(execution_status = 'FAIL') > 0 THEN 'Fix failing OVERWATCH query or missing privilege.'
                WHEN PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY elapsed_sec) > 15 THEN 'Move this section behind a mart or tighter cache.'
                WHEN SUM(bytes_scanned) > POWER(1024, 4) THEN 'Review app query cost before expanding this surface.'
                ELSE 'Healthy'
            END AS recommended_action
        FROM app_queries
        GROUP BY COALESCE(section_name, 'UNKNOWN')
        ORDER BY failed_queries DESC, p95_elapsed_sec DESC, gb_scanned DESC;
    """)


def build_executive_digest_history_sql(days: int = 14) -> str:
    """Build read-only executive digest history query."""
    days = max(1, int(days or 14))
    return _sql(f"""
        SELECT
            digest_ts,
            company,
            environment,
            platform_score,
            critical_high_alerts,
            open_actions,
            current_cost_usd,
            cortex_cost_usd,
            summary_text,
            next_action
        FROM DBA_MAINT_DB.OVERWATCH.EXECUTIVE_DIGEST_HISTORY
        WHERE digest_ts >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
        ORDER BY digest_ts DESC;
    """)


def build_org_rollup_sql(days: int = 30) -> str:
    """Build optional organization-level cost rollup SQL."""
    days = max(1, int(days or 30))
    return _sql(f"""
        -- Requires ORGADMIN or equivalent ORGANIZATION_USAGE privileges.
        SELECT
            account_name,
            service_type,
            SUM(credits_used) AS credits_used,
            ROUND(SUM(credits_used) * 3.68, 2) AS estimated_usd,
            MIN(usage_date) AS first_usage_date,
            MAX(usage_date) AS last_usage_date
        FROM SNOWFLAKE.ORGANIZATION_USAGE.METERING_DAILY_HISTORY
        WHERE usage_date >= DATEADD('DAY', -{days}, CURRENT_DATE())
        GROUP BY account_name, service_type
        ORDER BY estimated_usd DESC;
    """)
