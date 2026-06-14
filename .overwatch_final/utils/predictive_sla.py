"""Predictive SLA SQL contracts for Snowflake task and freshness risk."""

from __future__ import annotations

from textwrap import dedent


def build_predictive_sla_sql(days_back: int = 14) -> str:
    """Return SQL that predicts late task/freshness risk from recent runtimes."""
    days = max(2, min(int(days_back or 14), 60))
    return dedent(
        f"""
        CREATE OR REPLACE VIEW OVERWATCH_PREDICTIVE_SLA_V AS
        WITH task_runs AS (
            SELECT
                database_name,
                schema_name,
                name AS task_name,
                root_task_name,
                scheduled_time,
                state,
                DATEDIFF('second', query_start_time, completed_time) AS duration_sec
            FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
            WHERE scheduled_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
              AND query_start_time IS NOT NULL
              AND completed_time IS NOT NULL
        ),
        baseline AS (
            SELECT
                database_name,
                schema_name,
                task_name,
                root_task_name,
                AVG(duration_sec) AS avg_duration_sec,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_sec) AS p95_duration_sec,
                COUNT_IF(state = 'FAILED') AS failed_runs,
                COUNT(*) AS total_runs
            FROM task_runs
            GROUP BY 1, 2, 3, 4
        ),
        latest AS (
            SELECT *
            FROM task_runs
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY database_name, schema_name, task_name
                ORDER BY scheduled_time DESC
            ) = 1
        )
        SELECT
            b.database_name,
            b.schema_name,
            b.task_name,
            b.root_task_name,
            l.scheduled_time AS last_run_time,
            l.state AS last_state,
            b.avg_duration_sec,
            b.p95_duration_sec,
            b.failed_runs,
            b.total_runs,
            ROUND(b.failed_runs / NULLIF(b.total_runs, 0) * 100, 2) AS failure_rate_pct,
            CASE
                WHEN l.state = 'FAILED' THEN 'CRITICAL'
                WHEN b.failed_runs >= 3 THEN 'HIGH'
                WHEN b.p95_duration_sec > b.avg_duration_sec * 2 THEN 'MEDIUM'
                ELSE 'LOW'
            END AS predicted_sla_risk,
            CASE
                WHEN l.state = 'FAILED' THEN 'Open task graph failure console and inspect child task error.'
                WHEN b.failed_runs >= 3 THEN 'Review repeated failure pattern before next scheduled run.'
                WHEN b.p95_duration_sec > b.avg_duration_sec * 2 THEN 'Check runtime skew, warehouse queueing, and downstream freshness SLA.'
                ELSE 'Monitor'
            END AS recommended_action
        FROM baseline b
        LEFT JOIN latest l
          ON b.database_name = l.database_name
         AND b.schema_name = l.schema_name
         AND b.task_name = l.task_name;
        """
    ).strip() + "\n"
