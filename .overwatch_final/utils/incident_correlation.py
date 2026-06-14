"""Incident correlation SQL contracts for OVERWATCH."""

from __future__ import annotations

from textwrap import dedent


def build_incident_correlation_sql(hours_back: int = 24) -> str:
    """Return SQL that groups related Snowflake symptoms into one incident lane."""
    hours = max(1, min(int(hours_back or 24), 168))
    return dedent(
        f"""
        CREATE OR REPLACE VIEW OVERWATCH_INCIDENT_CORRELATION_V AS
        WITH query_symptoms AS (
            SELECT
                DATE_TRUNC('hour', start_time) AS bucket_start,
                COALESCE(warehouse_name, 'NO_WAREHOUSE') AS entity_name,
                'QUERY' AS signal_type,
                COUNT_IF(error_code IS NOT NULL) AS error_count,
                COUNT_IF(queued_overload_time > 0 OR queued_provisioning_time > 0) AS queue_count,
                COUNT_IF(bytes_spilled_to_remote_storage > 0) AS spill_count,
                MAX(total_elapsed_time) / 1000 AS max_elapsed_sec
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE start_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
            GROUP BY 1, 2, 3
        ),
        task_symptoms AS (
            SELECT
                DATE_TRUNC('hour', scheduled_time) AS bucket_start,
                COALESCE(root_task_name, name) AS entity_name,
                'TASK' AS signal_type,
                COUNT_IF(state = 'FAILED') AS error_count,
                COUNT_IF(state IN ('SKIPPED', 'CANCELLED')) AS queue_count,
                0 AS spill_count,
                MAX(DATEDIFF('second', query_start_time, completed_time)) AS max_elapsed_sec
            FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
            WHERE scheduled_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
            GROUP BY 1, 2, 3
        ),
        login_symptoms AS (
            SELECT
                DATE_TRUNC('hour', event_timestamp) AS bucket_start,
                COALESCE(user_name, 'UNKNOWN_USER') AS entity_name,
                'LOGIN' AS signal_type,
                COUNT_IF(IS_SUCCESS = 'NO') AS error_count,
                0 AS queue_count,
                0 AS spill_count,
                0 AS max_elapsed_sec
            FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
            WHERE event_timestamp >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
            GROUP BY 1, 2, 3
        ),
        all_symptoms AS (
            SELECT * FROM query_symptoms
            UNION ALL SELECT * FROM task_symptoms
            UNION ALL SELECT * FROM login_symptoms
        )
        SELECT
            bucket_start,
            entity_name,
            LISTAGG(signal_type, ', ') WITHIN GROUP (ORDER BY signal_type) AS signals,
            SUM(error_count) AS total_errors,
            SUM(queue_count) AS total_queue_or_skip,
            SUM(spill_count) AS total_spill_events,
            MAX(max_elapsed_sec) AS max_elapsed_sec,
            CASE
                WHEN SUM(error_count) >= 5 OR SUM(spill_count) >= 5 THEN 'HIGH'
                WHEN SUM(error_count) > 0 OR SUM(queue_count) > 0 THEN 'MEDIUM'
                ELSE 'LOW'
            END AS severity,
            'Investigate shared root cause before treating symptoms independently.' AS recommended_action
        FROM all_symptoms
        GROUP BY bucket_start, entity_name
        HAVING SUM(error_count) + SUM(queue_count) + SUM(spill_count) > 0;
        """
    ).strip() + "\n"
