"""Snowflake-native command intelligence contracts for OVERWATCH.

These helpers keep the production hardening backlog executable without forcing
every section to import Snowflake or pandas during Streamlit startup. The UI
uses the rows immediately while DBA-owned Snowflake objects provide durable
summary facts.
"""
from __future__ import annotations

from textwrap import dedent


COMMAND_INTELLIGENCE_VERSION = "2026.06.14-capability-register-v1"


def _sql(text: str) -> str:
    return dedent(text).strip() + "\n"


def build_capability_register_rows() -> list[dict[str, object]]:
    """Return the ranked production capability plan."""
    return [
        {
            "RANK": 1,
            "CAPABILITY": "Detection and Root-Cause Engine",
            "STATUS": "Foundation",
            "WHERE_IT_LANDS": "Alert Center, DBA Control Room",
            "WHY_IT_MATTERS": "Finds the shared cause behind cost, query, task, login, and object-change symptoms.",
            "NEXT_ACTION": "Materialize signal correlation and route one incident, not five disconnected alerts.",
            "SNOWFLAKE_SOURCES": "QUERY_HISTORY, TASK_HISTORY, LOGIN_HISTORY, ACCESS_HISTORY, WAREHOUSE_METERING_HISTORY",
            "OWNER": "DBA On-Call",
            "PRODUCTION_GUARDRAIL": "Correlation is telemetry ranking only; remediation remains review-gated.",
        },
        {
            "RANK": 2,
            "CAPABILITY": "Task/Pipeline Critical Path Brain",
            "STATUS": "Foundation",
            "WHERE_IT_LANDS": "Workload Operations, DBA Morning Brief",
            "WHY_IT_MATTERS": "Shows the root task, child failure, late-risk, retry pattern, and downstream blast radius.",
            "NEXT_ACTION": "Use task graph facts before retrying, resuming, or calling a pipeline healthy.",
            "SNOWFLAKE_SOURCES": "TASK_HISTORY, INFORMATION_SCHEMA.TASK_HISTORY, EVENT TABLES",
            "OWNER": "DBA / Data Engineering",
            "PRODUCTION_GUARDRAIL": "Retry and resume actions require route policy and run ledger telemetry.",
        },
        {
            "RANK": 3,
            "CAPABILITY": "Data Quality and Reconciliation Center",
            "STATUS": "New",
            "WHERE_IT_LANDS": "Workload Operations",
            "WHY_IT_MATTERS": "Compares row counts, hash buckets, schema drift, freshness, and sample diffs by database/schema.",
            "NEXT_ACTION": "Create metadata-driven reconciliation rules and store per-table results.",
            "SNOWFLAKE_SOURCES": "INFORMATION_SCHEMA, QUERY_HISTORY, configured table checks",
            "OWNER": "DBA / Data Owner",
            "PRODUCTION_GUARDRAIL": "Hash large tables by bucket/key, then sample mismatches before full scans.",
        },
        {
            "RANK": 4,
            "CAPABILITY": "Predictive FinOps and Automated Value Log",
            "STATUS": "Foundation",
            "WHERE_IT_LANDS": "Cost & Contract, Snowflake Value",
            "WHY_IT_MATTERS": "Forecasts burn, ranks contract risk, and auto-captures measured DBA value instead of relying on one-off notes.",
            "NEXT_ACTION": "Derive value candidates from action queue, metering deltas, alert closures, and workload recovery telemetry.",
            "SNOWFLAKE_SOURCES": "WAREHOUSE_METERING_HISTORY, METERING_DAILY_HISTORY, OVERWATCH_ACTION_QUEUE, OVERWATCH_ROI_LOG",
            "OWNER": "DBA / FinOps",
            "PRODUCTION_GUARDRAIL": "Estimated value cannot become measured until post-period telemetry exists.",
        },
        {
            "RANK": 5,
            "CAPABILITY": "Alert Lifecycle 2.0",
            "STATUS": "Foundation",
            "WHERE_IT_LANDS": "Alert Center",
            "WHY_IT_MATTERS": "Turns alerts into acknowledged, owned, suppressed, resolved, commented, and audited work.",
            "NEXT_ACTION": "Normalize lifecycle state and route repeated issues to the same owner/action.",
            "SNOWFLAKE_SOURCES": "ALERT_EVENTS, ALERT_ACKNOWLEDGEMENTS, ALERT_RUN_HISTORY, ALERT_REMEDIATION_LOG",
            "OWNER": "DBA Lead",
            "PRODUCTION_GUARDRAIL": "Deduplicate aggressively and show freshness/source lag on every board.",
        },
        {
            "RANK": 6,
            "CAPABILITY": "Fact-Grounded AI Query Diagnosis",
            "STATUS": "Contract",
            "WHERE_IT_LANDS": "Workload Operations, Query diagnosis",
            "WHY_IT_MATTERS": "Cortex can explain why a query is slow only when fed real profile facts and optimization constraints.",
            "NEXT_ACTION": "Pass query telemetry, table context, spill/pruning metrics, and expected output shape into the prompt contract.",
            "SNOWFLAKE_SOURCES": "QUERY_HISTORY, QUERY_PROFILE when available, ACCESS_HISTORY, TABLE_STORAGE_METRICS",
            "OWNER": "DBA / Query Owner",
            "PRODUCTION_GUARDRAIL": "No generic AI answer; recommendations must cite exact metrics and SQL telemetry.",
        },
        {
            "RANK": 7,
            "CAPABILITY": "Bounded Refresh Guardrails",
            "STATUS": "New",
            "WHERE_IT_LANDS": "Cost & Contract, Alert Center",
            "WHY_IT_MATTERS": "Keeps refresh cadence bounded so monitoring workflows do not become the cost problem.",
            "NEXT_ACTION": "Use scoped summaries, explicit refresh, and status-checked live telemetry when needed.",
            "SNOWFLAKE_SOURCES": "Scoped summaries and bounded ACCOUNT_USAGE checks",
            "OWNER": "DBA Platform",
            "PRODUCTION_GUARDRAIL": "Never auto-enable expensive refresh without warehouse, lag, and cost review.",
        },
        {
            "RANK": 8,
            "CAPABILITY": "Fast Summary Layer With Fallback",
            "STATUS": "Foundation",
            "WHERE_IT_LANDS": "Data Health, DBA Control Room, Cost & Contract",
            "WHY_IT_MATTERS": "Keeps first paint fast and makes live ACCOUNT_USAGE scans explicit instead of accidental.",
            "NEXT_ACTION": "Add optional dynamic tables where supported and fallback views/tasks everywhere else.",
            "SNOWFLAKE_SOURCES": "ACCOUNT_USAGE, Dynamic Tables, Streams/Tasks, OVERWATCH_FACT tables",
            "OWNER": "DBA Platform",
            "PRODUCTION_GUARDRAIL": "Never auto-enable expensive refresh without warehouse, lag, and cost review.",
        },
        {
            "RANK": 9,
            "CAPABILITY": "Security Risk Monitoring",
            "STATUS": "New",
            "WHERE_IT_LANDS": "Security Monitoring, Executive Landing",
            "WHY_IT_MATTERS": "Leaders need a defensible view of admin grants, dormant users, policy drift, and risky shares.",
            "NEXT_ACTION": "Materialize security risk signals with telemetry rows and escalation paths.",
            "SNOWFLAKE_SOURCES": "GRANTS_TO_USERS, GRANTS_TO_ROLES, LOGIN_HISTORY, ACCESS_HISTORY, POLICIES, SHARES",
            "OWNER": "Security Route",
            "PRODUCTION_GUARDRAIL": "Security risk monitoring is advisory; access changes stay in guarded workflows.",
        },
        {
            "RANK": 10,
            "CAPABILITY": "Multi-Account / Org View",
            "STATUS": "Contract",
            "WHERE_IT_LANDS": "Executive Landing, Cost & Contract",
            "WHY_IT_MATTERS": "If leadership owns multiple Snowflake accounts, cost/risk must roll up above one account.",
            "NEXT_ACTION": "Provide optional ORGADMIN views and a no-ORG fallback that stays single-account.",
            "SNOWFLAKE_SOURCES": "ORGANIZATION_USAGE, ACCOUNT_USAGE, account registry config",
            "OWNER": "Snowflake Platform Owner",
            "PRODUCTION_GUARDRAIL": "Hide org views when the role lacks ORGADMIN/organization usage privileges.",
        },
        {
            "RANK": 11,
            "CAPABILITY": "Data-First Navigation Contract",
            "STATUS": "Foundation",
            "WHERE_IT_LANDS": "App shell, every primary section",
            "WHY_IT_MATTERS": "DBAs should see scoped KPIs, risks, and summaries on the first section click without saved-view state or mode toggles.",
            "NEXT_ACTION": "Keep section autoload bounded to fast summaries and make heavy telemetry an explicit local action.",
            "SNOWFLAKE_SOURCES": "Streamlit session state, fast OVERWATCH summaries, ACCOUNT_USAGE fallback",
            "OWNER": "OVERWATCH Maintainer",
            "PRODUCTION_GUARDRAIL": "Do not persist navigation state or create saved-state tables; unknown roles stay restrictive.",
        },
        {
            "RANK": 12,
            "CAPABILITY": "Monitoring Docs and Runbooks",
            "STATUS": "New",
            "WHERE_IT_LANDS": "README, Data Health Runbook",
            "WHY_IT_MATTERS": "A production DBA command center needs data health, privileges, failure modes, rollback, and operating rules.",
            "NEXT_ACTION": "Keep a DBA runbook, data model map, precompute decision, and remediation safety model with the code.",
            "SNOWFLAKE_SOURCES": "Repository docs, status ledger, migration ledger",
            "OWNER": "DBA Lead",
            "PRODUCTION_GUARDRAIL": "Docs must match approved operating behavior before release.",
        },
    ]


def build_detection_root_cause_sql(hours: int = 24) -> str:
    """Build a Snowflake-native correlation query for incident root-cause ranking."""
    hours = max(1, int(hours or 24))
    return _sql(f"""
        -- OVERWATCH root-cause correlation. ACCOUNT_USAGE can lag; use live workflows
        -- for in-flight cancellation or lock action.
        WITH query_signals AS (
            SELECT
                'PERFORMANCE' AS signal_family,
                COALESCE(warehouse_name, 'NO_WAREHOUSE') AS entity_name,
                COUNT(*) AS signal_count,
                COUNT_IF(execution_status = 'FAIL') AS failure_count,
                AVG(total_elapsed_time) / 1000 AS avg_elapsed_sec,
                MAX(total_elapsed_time) / 1000 AS max_elapsed_sec,
                MAX(start_time) AS last_seen,
                MAX_BY(query_id, total_elapsed_time) AS sample_query_id,
                MAX_BY(SUBSTR(query_text, 1, 500), total_elapsed_time) AS evidence
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE start_time >= DATEADD('HOUR', -{hours}, CURRENT_TIMESTAMP())
              AND (
                    execution_status = 'FAIL'
                 OR total_elapsed_time > 600000
                 OR bytes_spilled_to_remote_storage > 0
                 OR queued_overload_time > 0
                 OR error_message ILIKE '%lock%'
              )
            GROUP BY COALESCE(warehouse_name, 'NO_WAREHOUSE')
        ),
        task_signals AS (
            SELECT
                'TASK_PIPELINE' AS signal_family,
                COALESCE(root_task_name, name) AS entity_name,
                COUNT(*) AS signal_count,
                COUNT_IF(state IN ('FAILED', 'CANCELLED')) AS failure_count,
                AVG(DATEDIFF('SECOND', query_start_time, completed_time)) AS avg_elapsed_sec,
                MAX(DATEDIFF('SECOND', query_start_time, completed_time)) AS max_elapsed_sec,
                MAX(scheduled_time) AS last_seen,
                MAX_BY(query_id, scheduled_time) AS sample_query_id,
                MAX_BY(error_message, scheduled_time) AS evidence
            FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
            WHERE scheduled_time >= DATEADD('HOUR', -{hours}, CURRENT_TIMESTAMP())
              AND state IN ('FAILED', 'CANCELLED', 'SKIPPED')
            GROUP BY COALESCE(root_task_name, name)
        ),
        security_signals AS (
            SELECT
                'SECURITY' AS signal_family,
                COALESCE(user_name, 'UNKNOWN_USER') AS entity_name,
                COUNT(*) AS signal_count,
                COUNT_IF(is_success = 'NO') AS failure_count,
                0::FLOAT AS avg_elapsed_sec,
                0::FLOAT AS max_elapsed_sec,
                MAX(event_timestamp) AS last_seen,
                NULL::VARCHAR AS sample_query_id,
                MAX_BY(client_ip, event_timestamp) AS evidence
            FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
            WHERE event_timestamp >= DATEADD('HOUR', -{hours}, CURRENT_TIMESTAMP())
              AND (is_success = 'NO' OR first_authentication_factor = 'PASSWORD')
            GROUP BY COALESCE(user_name, 'UNKNOWN_USER')
        ),
        all_signals AS (
            SELECT * FROM query_signals
            UNION ALL SELECT * FROM task_signals
            UNION ALL SELECT * FROM security_signals
        )
        SELECT
            signal_family,
            entity_name,
            signal_count,
            failure_count,
            ROUND(avg_elapsed_sec, 1) AS avg_elapsed_sec,
            ROUND(max_elapsed_sec, 1) AS max_elapsed_sec,
            last_seen,
            sample_query_id,
            evidence,
            CASE
                WHEN signal_family = 'SECURITY' AND failure_count >= 10 THEN 'CRITICAL'
                WHEN failure_count > 0 AND signal_count >= 3 THEN 'HIGH'
                WHEN max_elapsed_sec >= 1800 THEN 'HIGH'
                WHEN signal_count >= 3 THEN 'MEDIUM'
                ELSE 'LOW'
            END AS severity,
            CASE
                WHEN signal_family = 'TASK_PIPELINE' THEN 'Open Workload Operations task graph and inspect child failure/root task.'
                WHEN signal_family = 'PERFORMANCE' THEN 'Open Query diagnosis or Contention Center with the sample query_id.'
                WHEN signal_family = 'SECURITY' THEN 'Open Security Monitoring and verify IP, role, MFA, and service account behavior.'
                ELSE 'Open Alert Center incident board.'
            END AS recommended_action
        FROM all_signals
        ORDER BY
            CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
            failure_count DESC,
            signal_count DESC,
            last_seen DESC;
    """)


def build_task_critical_path_brain_sql(hours: int = 24) -> str:
    """Build the task graph status and late-risk SQL contract."""
    hours = max(1, int(hours or 24))
    return _sql(f"""
        -- Task critical path brain. Prefer INFORMATION_SCHEMA.TASK_HISTORY for
        -- near-real-time checks; ACCOUNT_USAGE.TASK_HISTORY can lag.
        WITH task_runs AS (
            SELECT
                database_name,
                schema_name,
                COALESCE(root_task_name, name) AS root_task_name,
                name AS task_name,
                state,
                scheduled_time,
                query_start_time,
                completed_time,
                query_id,
                error_code,
                error_message,
                DATEDIFF('SECOND', query_start_time, completed_time) AS duration_sec
            FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
            WHERE scheduled_time >= DATEADD('HOUR', -{hours}, CURRENT_TIMESTAMP())
        ),
        baselines AS (
            SELECT
                database_name,
                schema_name,
                root_task_name,
                task_name,
                AVG(duration_sec) AS avg_duration_sec,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_sec) AS p95_duration_sec
            FROM task_runs
            WHERE state = 'SUCCEEDED'
              AND duration_sec IS NOT NULL
            GROUP BY database_name, schema_name, root_task_name, task_name
        ),
        ranked AS (
            SELECT
                r.*,
                b.avg_duration_sec,
                b.p95_duration_sec,
                ROW_NUMBER() OVER (
                    PARTITION BY r.database_name, r.schema_name, r.root_task_name, r.task_name
                    ORDER BY r.scheduled_time DESC
                ) AS rn
            FROM task_runs r
            LEFT JOIN baselines b
              ON r.database_name = b.database_name
             AND r.schema_name = b.schema_name
             AND r.root_task_name = b.root_task_name
             AND r.task_name = b.task_name
        )
        SELECT
            database_name,
            schema_name,
            root_task_name,
            task_name,
            state,
            scheduled_time,
            query_id,
            duration_sec,
            ROUND(avg_duration_sec, 1) AS avg_duration_sec,
            ROUND(p95_duration_sec, 1) AS p95_duration_sec,
            error_code,
            error_message,
            CASE
                WHEN state IN ('FAILED', 'CANCELLED') THEN 'CRITICAL'
                WHEN state = 'SKIPPED' THEN 'HIGH'
                WHEN duration_sec > COALESCE(p95_duration_sec, avg_duration_sec) * 1.5 THEN 'MEDIUM'
                ELSE 'LOW'
            END AS severity,
            CASE
                WHEN state IN ('FAILED', 'CANCELLED') THEN 'Open failed query_id, error message, owner, and downstream task list before retry.'
                WHEN state = 'SKIPPED' THEN 'Check predecessor state, schedule overlap, and warehouse availability.'
                WHEN duration_sec > COALESCE(p95_duration_sec, avg_duration_sec) * 1.5 THEN 'Compare procedure/query profile to baseline before resizing.'
                ELSE 'No immediate action.'
            END AS recommended_action
        FROM ranked
        WHERE rn = 1
        ORDER BY
            CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
            scheduled_time DESC;
    """)


def build_data_reconciliation_config_ddl() -> str:
    """Return config and result tables for schema/table sameness checks."""
    return _sql("""
        CREATE TABLE IF NOT EXISTS OVERWATCH_RECON_CONFIG (
          CHECK_ID             NUMBER AUTOINCREMENT PRIMARY KEY,
          CHECK_NAME           VARCHAR(300),
          SOURCE_DATABASE      VARCHAR(300),
          SOURCE_SCHEMA        VARCHAR(300),
          TARGET_DATABASE      VARCHAR(300),
          TARGET_SCHEMA        VARCHAR(300),
          TABLE_PATTERN        VARCHAR(300) DEFAULT '%',
          KEY_COLUMNS          VARCHAR(2000),
          EXCLUDE_COLUMNS      VARCHAR(2000),
          WHERE_CLAUSE         VARCHAR(4000),
          HASH_BUCKET_COUNT    NUMBER DEFAULT 64,
          CHECK_MODE           VARCHAR(50) DEFAULT 'COUNT_AND_HASH',
          SEVERITY             VARCHAR(40) DEFAULT 'MEDIUM',
          OWNER                VARCHAR(300),
          ENABLED              BOOLEAN DEFAULT TRUE,
          CREATED_AT           TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        );

        CREATE TABLE IF NOT EXISTS OVERWATCH_RECON_RUN (
          RUN_ID               NUMBER AUTOINCREMENT PRIMARY KEY,
          CHECK_ID             NUMBER,
          RUN_TS               TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
          RUN_STATUS           VARCHAR(40),
          SOURCE_ROW_COUNT     NUMBER,
          TARGET_ROW_COUNT     NUMBER,
          SOURCE_HASH          VARCHAR(200),
          TARGET_HASH          VARCHAR(200),
          MISMATCH_COUNT       NUMBER,
          SAMPLE_DIFF_SQL      VARCHAR(16000),
          RECOMMENDED_ACTION   VARCHAR(2000)
        );

        CREATE TABLE IF NOT EXISTS OVERWATCH_SCHEMA_DIFF_RESULT (
          RUN_TS               TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
          SOURCE_DATABASE      VARCHAR(300),
          SOURCE_SCHEMA        VARCHAR(300),
          TARGET_DATABASE      VARCHAR(300),
          TARGET_SCHEMA        VARCHAR(300),
          OBJECT_TYPE          VARCHAR(100),
          OBJECT_NAME          VARCHAR(1000),
          DIFF_TYPE            VARCHAR(100),
          GENERATED_DDL        VARCHAR(16000),
          OWNER                VARCHAR(300),
          SEVERITY             VARCHAR(40)
        );
    """)


def build_data_reconciliation_runner_sql() -> str:
    """Return SQL that generates table-level count/hash commands from config."""
    return _sql("""
        -- Generates bounded count/hash SQL by configured schema pair.
        -- ACCOUNT_USAGE.TABLES lets one query enumerate across databases. It is
        -- delayed telemetry; use SHOW/INFORMATION_SCHEMA in Workload Operations for live
        -- object work.
        WITH source_tables AS (
            SELECT
                table_catalog,
                table_schema,
                table_name,
                table_type
            FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
            WHERE deleted IS NULL
              AND table_type IN ('BASE TABLE', 'EXTERNAL TABLE', 'DYNAMIC TABLE')
        ),
        target_tables AS (
            SELECT
                table_catalog,
                table_schema,
                table_name,
                table_type
            FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
            WHERE deleted IS NULL
              AND table_type IN ('BASE TABLE', 'EXTERNAL TABLE', 'DYNAMIC TABLE')
        )
        SELECT
            c.check_id,
            c.check_name,
            c.source_database,
            c.source_schema,
            c.target_database,
            c.target_schema,
            s.table_name,
            s.table_type,
            IFF(t.table_name IS NULL, 'TARGET_TABLE_MISSING', 'COMPARE_READY') AS compare_state,
            'SELECT COUNT(*) AS ROW_COUNT, HASH_AGG(*) AS TABLE_HASH FROM "' ||
                c.source_database || '"."' || c.source_schema || '"."' || s.table_name || '"' ||
                IFF(NULLIF(c.where_clause, '') IS NULL, '', ' WHERE ' || c.where_clause) AS source_count_hash_sql,
            IFF(
                t.table_name IS NULL,
                NULL,
                'SELECT COUNT(*) AS ROW_COUNT, HASH_AGG(*) AS TABLE_HASH FROM "' ||
                    c.target_database || '"."' || c.target_schema || '"."' || s.table_name || '"' ||
                    IFF(NULLIF(c.where_clause, '') IS NULL, '', ' WHERE ' || c.where_clause)
            ) AS target_count_hash_sql,
            CASE
                WHEN t.table_name IS NULL THEN 'Run Schema Compare to review the missing target table before data compare.'
                WHEN c.check_mode = 'COUNT_ONLY' THEN 'Compare row counts first, then escalate to hash only if counts differ.'
                ELSE 'Use bucketed HASH_AGG over key columns for tables too large for full hash in one pass.'
            END AS recommended_action
        FROM OVERWATCH_RECON_CONFIG c
        JOIN source_tables s
          ON UPPER(s.table_catalog) = UPPER(c.source_database)
         AND UPPER(s.table_schema) = UPPER(c.source_schema)
         AND s.table_name ILIKE c.table_pattern
        LEFT JOIN target_tables t
          ON UPPER(t.table_catalog) = UPPER(c.target_database)
         AND UPPER(t.table_schema) = UPPER(c.target_schema)
         AND UPPER(t.table_name) = UPPER(s.table_name)
        WHERE c.enabled = TRUE
        ORDER BY compare_state DESC, c.check_name, s.table_name;
    """)


def build_predictive_finops_sql(days: int = 90) -> str:
    """Build contract burn, run-rate, and driver forecast SQL."""
    days = max(7, int(days or 90))
    return _sql(f"""
        WITH daily AS (
            SELECT
                usage_date,
                warehouse_name,
                SUM(COALESCE(credits_used_compute, credits_used)) AS compute_credits,
                SUM(credits_used) AS total_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE usage_date >= DATEADD('DAY', -{days}, CURRENT_DATE())
            GROUP BY usage_date, warehouse_name
        ),
        rollup AS (
            SELECT
                usage_date,
                SUM(total_credits) AS account_credits,
                SUM(compute_credits) AS compute_credits
            FROM daily
            GROUP BY usage_date
        ),
        settings AS (
            SELECT
                MAX(IFF(setting_name = 'CREDIT_PRICE_USD', TRY_TO_DOUBLE(setting_value), NULL)) AS credit_price_usd,
                MAX(IFF(setting_name = 'MONTHLY_CONTRACT_CREDITS', TRY_TO_DOUBLE(setting_value), NULL)) AS monthly_contract_credits
            FROM OVERWATCH_SETTINGS
        ),
        forecast AS (
            SELECT
                AVG(IFF(usage_date >= DATEADD('DAY', -7, CURRENT_DATE()), account_credits, NULL)) AS avg_7d_credits,
                AVG(IFF(usage_date >= DATEADD('DAY', -30, CURRENT_DATE()), account_credits, NULL)) AS avg_30d_credits,
                SUM(IFF(usage_date >= DATE_TRUNC('MONTH', CURRENT_DATE()), account_credits, 0)) AS month_to_date_credits
            FROM rollup
        ),
        top_driver AS (
            SELECT
                warehouse_name,
                SUM(total_credits) AS credits_30d
            FROM daily
            WHERE usage_date >= DATEADD('DAY', -30, CURRENT_DATE())
            GROUP BY warehouse_name
            ORDER BY credits_30d DESC
            LIMIT 1
        ),
        projected AS (
            SELECT
                f.avg_7d_credits,
                f.avg_30d_credits,
                f.month_to_date_credits,
                f.month_to_date_credits
                  + f.avg_7d_credits * GREATEST(0, DATEDIFF('DAY', CURRENT_DATE(), LAST_DAY(CURRENT_DATE()))) AS projected_month_end_credits,
                s.monthly_contract_credits,
                ROUND((f.month_to_date_credits
                  + f.avg_7d_credits * GREATEST(0, DATEDIFF('DAY', CURRENT_DATE(), LAST_DAY(CURRENT_DATE()))))
                  * COALESCE(s.credit_price_usd, 3.68), 2) AS projected_month_end_usd,
                t.warehouse_name AS top_driver,
                t.credits_30d AS top_driver_credits_30d
            FROM forecast f
            CROSS JOIN settings s
            LEFT JOIN top_driver t ON TRUE
        )
        SELECT
            *,
            CASE
                WHEN monthly_contract_credits IS NULL THEN 'Set MONTHLY_CONTRACT_CREDITS in OVERWATCH_SETTINGS.'
                WHEN projected_month_end_credits > monthly_contract_credits THEN 'Contract burn risk. Work top driver and action queue now.'
                WHEN projected_month_end_credits > monthly_contract_credits * 0.9 THEN 'Approaching contract pace. Validate budget actions.'
                ELSE 'Contract pace within current threshold.'
            END AS recommended_action
        FROM projected;
    """)


def build_alert_lifecycle_sql() -> str:
    """Build the Alert Lifecycle 2.0 readiness query."""
    return _sql("""
        WITH events AS (
            SELECT
                event_id,
                category,
                severity,
                status,
                owner,
                entity_name,
                event_ts,
                resolved_at
            FROM ALERT_EVENTS
            WHERE event_ts >= DATEADD('DAY', -30, CURRENT_TIMESTAMP())
        ),
        ack AS (
            SELECT event_id, MAX(acknowledged_at) AS acknowledged_at
            FROM ALERT_ACKNOWLEDGEMENTS
            GROUP BY event_id
        ),
        comments AS (
            SELECT event_id, COUNT(*) AS comment_count
            FROM ALERT_REMEDIATION_LOG
            GROUP BY event_id
        )
        SELECT
            e.event_id,
            e.category,
            e.severity,
            e.status,
            e.owner,
            e.entity_name,
            e.event_ts,
            a.acknowledged_at,
            e.resolved_at,
            DATEDIFF('MINUTE', e.event_ts, a.acknowledged_at) AS minutes_to_ack,
            DATEDIFF('MINUTE', e.event_ts, e.resolved_at) AS minutes_to_resolve,
            COALESCE(c.comment_count, 0) AS comment_count,
            CASE
                WHEN UPPER(e.status) IN ('OPEN', 'NEW') AND a.acknowledged_at IS NULL THEN 'ACK_REQUIRED'
                WHEN UPPER(e.status) IN ('OPEN', 'NEW', 'ACKNOWLEDGED') AND e.owner IS NULL THEN 'OWNER_REQUIRED'
                WHEN UPPER(e.status) IN ('RESOLVED', 'CLOSED') AND e.resolved_at IS NULL THEN 'RESOLUTION_TIMESTAMP_REQUIRED'
                ELSE 'LIFECYCLE_READY'
            END AS lifecycle_state
        FROM events e
        LEFT JOIN ack a USING (event_id)
        LEFT JOIN comments c USING (event_id)
        ORDER BY
            CASE e.severity WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
            e.event_ts DESC;
    """)


def build_ai_query_diagnosis_contract_rows() -> list[dict[str, str]]:
    """Return the telemetry contract for Cortex-backed query diagnosis."""
    return [
        {
            "EVIDENCE": "Query identity",
            "REQUIRED_FIELDS": "query_id, query_hash, user_name, role_name, warehouse_name, database_name, schema_name",
            "WHY_REQUIRED": "The advice must target a real workload route and repeatable query pattern.",
        },
        {
            "EVIDENCE": "Runtime profile",
            "REQUIRED_FIELDS": "elapsed_sec, compilation_sec, execution_sec, queue_sec, rows_produced",
            "WHY_REQUIRED": "Separates SQL rewrite problems from warehouse pressure or compilation overhead.",
        },
        {
            "EVIDENCE": "Scan efficiency",
            "REQUIRED_FIELDS": "bytes_scanned, partitions_scanned, partitions_total, pruning_pct",
            "WHY_REQUIRED": "Prevents generic advice and points to clustering, search optimization, or filters only when telemetry supports it.",
        },
        {
            "EVIDENCE": "Spill and memory",
            "REQUIRED_FIELDS": "bytes_spilled_local, bytes_spilled_remote, warehouse_size, join/order/group hints",
            "WHY_REQUIRED": "Identifies explosive joins, sort pressure, and sizing issues.",
        },
        {
            "EVIDENCE": "Object context",
            "REQUIRED_FIELDS": "tables_accessed, row counts, storage bytes, clustering keys, search optimization flags",
            "WHY_REQUIRED": "Recommendations need object-level telemetry, not only query text.",
        },
        {
            "EVIDENCE": "Required answer shape",
            "REQUIRED_FIELDS": "root_cause, exact_fix, SQL rewrite sketch, risk, status_query, team_action",
            "WHY_REQUIRED": "Forces specific DBA action and post-change telemetry.",
        },
    ]


def build_ai_query_diagnosis_prompt_contract() -> str:
    return _sql("""
        You are OVERWATCH Query Diagnosis. Use only the provided Snowflake telemetry.

        Required output:
        1. Root cause, with the exact metric that proves it.
        2. Specific SQL or object change recommendation.
        3. Why cheaper/simple alternatives are not enough.
        4. Risk and rollback note.
        5. Status query to run after the fix.

        Refuse generic advice. If telemetry is missing, say exactly which Snowflake
        fields are needed before recommending clustering, search optimization,
        warehouse resizing, rewrite, task change, or query cancellation.
    """)


def build_overwatch_self_monitoring_sql(days: int = 7) -> str:
    """Build app-runtime health and cost evidence from OVERWATCH query tags."""
    days = max(1, int(days or 7))
    return _sql(f"""
        WITH app_queries AS (
            SELECT
                start_time,
                query_id,
                query_tag,
                execution_status,
                warehouse_name,
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
                WHEN COUNT_IF(execution_status = 'FAIL') > 0 THEN 'Fix failing app queries or missing privileges.'
                WHEN PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY elapsed_sec) > 15 THEN 'Cache or mart this section before expanding features.'
                WHEN SUM(bytes_scanned) > POWER(1024, 4) THEN 'Review app query cost and add precompute.'
                ELSE 'Healthy'
            END AS recommended_action
        FROM app_queries
        GROUP BY COALESCE(section_name, 'UNKNOWN')
        ORDER BY failed_queries DESC, p95_elapsed_sec DESC, gb_scanned DESC;
    """)


def build_precompute_contract_sql() -> str:
    """Return optional dynamic-table and fallback view contracts."""
    return _sql("""
        -- Optional dynamic table path. Enable only after refresh lag, warehouse,
        -- and cost ownership are approved.
        CREATE DYNAMIC TABLE IF NOT EXISTS DT_OVERWATCH_QUERY_HEALTH_HOURLY
          TARGET_LAG = '60 minutes'
          WAREHOUSE = OVERWATCH_WH
        AS
        SELECT
            DATE_TRUNC('HOUR', start_time) AS hour_start,
            warehouse_name,
            user_name,
            role_name,
            database_name,
            COUNT(*) AS query_count,
            COUNT_IF(execution_status = 'FAIL') AS failed_count,
            AVG(total_elapsed_time) AS avg_elapsed_ms,
            SUM(bytes_scanned) AS bytes_scanned,
            SUM(bytes_spilled_to_remote_storage) AS bytes_spilled_remote
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE start_time >= DATEADD('DAY', -14, CURRENT_TIMESTAMP())
        GROUP BY 1, 2, 3, 4, 5;

        -- Fallback path for accounts that cannot use Dynamic Tables.
        CREATE OR REPLACE VIEW OVERWATCH_QUERY_HEALTH_HOURLY_V AS
        SELECT
            DATE_TRUNC('HOUR', start_time) AS hour_start,
            warehouse_name,
            user_name,
            role_name,
            database_name,
            COUNT(*) AS query_count,
            COUNT_IF(execution_status = 'FAIL') AS failed_count,
            AVG(total_elapsed_time) AS avg_elapsed_ms,
            SUM(bytes_scanned) AS bytes_scanned,
            SUM(bytes_spilled_to_remote_storage) AS bytes_spilled_remote
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE start_time >= DATEADD('DAY', -14, CURRENT_TIMESTAMP())
        GROUP BY 1, 2, 3, 4, 5;
    """)


def build_compliance_readiness_sql(days: int = 30) -> str:
    """Build admin/security compliance scorecard evidence."""
    days = max(1, int(days or 30))
    return _sql(f"""
        WITH admin_grants AS (
            SELECT
                grantee_name AS user_name,
                role AS granted_role,
                granted_on,
                created_on
            FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS
            WHERE deleted_on IS NULL
              AND role IN ('ACCOUNTADMIN', 'SECURITYADMIN', 'SYSADMIN', 'ORGADMIN')
        ),
        dormant_active AS (
            SELECT
                user_name,
                MIN(event_timestamp) AS first_seen,
                MAX(event_timestamp) AS last_seen,
                COUNT(*) AS logins
            FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
            WHERE event_timestamp >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
              AND is_success = 'YES'
            GROUP BY user_name
        ),
        access_spikes AS (
            SELECT
                user_name,
                COUNT(*) AS accessed_objects
            FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY
            WHERE query_start_time >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
            GROUP BY user_name
        ),
        rollup AS (
            SELECT
                COALESCE(a.user_name, d.user_name, s.user_name) AS user_name,
                LISTAGG(DISTINCT a.granted_role, ', ') WITHIN GROUP (ORDER BY a.granted_role) AS admin_roles,
                MAX(d.logins) AS successful_logins,
                MAX(s.accessed_objects) AS accessed_objects
            FROM admin_grants a
            FULL OUTER JOIN dormant_active d ON a.user_name = d.user_name
            FULL OUTER JOIN access_spikes s ON COALESCE(a.user_name, d.user_name) = s.user_name
            GROUP BY COALESCE(a.user_name, d.user_name, s.user_name)
        )
        SELECT
            user_name,
            admin_roles,
            successful_logins,
            accessed_objects,
            CASE
                WHEN admin_roles IS NOT NULL THEN 'HIGH'
                WHEN successful_logins > 0 AND accessed_objects > 1000 THEN 'MEDIUM'
                ELSE 'LOW'
            END AS severity,
            CASE
                WHEN admin_roles IS NOT NULL THEN 'Validate owner, break-glass need, MFA, and approval for admin role.'
                WHEN accessed_objects > 1000 THEN 'Review sensitive object access and workload route.'
                ELSE 'No immediate action.'
            END AS recommended_action
        FROM rollup
        ORDER BY CASE severity WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END, accessed_objects DESC;
    """)


def build_multi_account_org_sql(days: int = 30) -> str:
    """Build optional organization-level rollup SQL."""
    days = max(1, int(days or 30))
    return _sql(f"""
        -- Requires organization usage privileges. Hide this view when unavailable.
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
        ORDER BY credits_used DESC;
    """)


def build_data_first_navigation_contract_sql() -> str:
    """Return the no-persistence contract for section navigation."""
    return _sql("""
        -- Data-first navigation contract:
        -- 1. No saved-state table.
        -- 2. No persisted global evidence or exception preference.
        -- 3. Section navigation may hydrate only bounded fast summaries.
        -- 4. Heavy proof, remediation, and export actions remain explicit local actions.
    """)


def build_snowflake_value_auto_ddl() -> str:
    """Return DDL/procedure contract for no-touch value log capture."""
    return _sql("""
        ALTER TABLE IF EXISTS OVERWATCH_ROI_LOG ADD COLUMN IF NOT EXISTS VALUE_SOURCE VARCHAR(100);
        ALTER TABLE IF EXISTS OVERWATCH_ROI_LOG ADD COLUMN IF NOT EXISTS EVIDENCE_SOURCE VARCHAR(200);
        ALTER TABLE IF EXISTS OVERWATCH_ROI_LOG ADD COLUMN IF NOT EXISTS EVIDENCE_ID VARCHAR(500);
        ALTER TABLE IF EXISTS OVERWATCH_ROI_LOG ADD COLUMN IF NOT EXISTS VALUE_STATE VARCHAR(60) DEFAULT 'ESTIMATED';
        ALTER TABLE IF EXISTS OVERWATCH_ROI_LOG ADD COLUMN IF NOT EXISTS BUSINESS_IMPACT VARCHAR(2000);
        ALTER TABLE IF EXISTS OVERWATCH_ROI_LOG ADD COLUMN IF NOT EXISTS OWNER VARCHAR(300);
        ALTER TABLE IF EXISTS OVERWATCH_ROI_LOG ADD COLUMN IF NOT EXISTS VERIFIED_TS TIMESTAMP_NTZ;

        CREATE TABLE IF NOT EXISTS OVERWATCH_VALUE_AUTOMATION_RUN (
          RUN_ID               NUMBER AUTOINCREMENT PRIMARY KEY,
          RUN_TS               TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
          RUN_STATUS           VARCHAR(40),
          CANDIDATE_COUNT      NUMBER,
          INSERTED_COUNT       NUMBER,
          VERIFIED_COUNT       NUMBER,
          MESSAGE              VARCHAR(4000)
        );

        CREATE OR REPLACE VIEW OVERWATCH_VALUE_CANDIDATE_V AS
        WITH cost_actions AS (
            SELECT
                'ACTION_QUEUE' AS value_source,
                'OVERWATCH_ACTION_QUEUE' AS evidence_source,
                action_id AS evidence_id,
                COALESCE(category, 'Cost action') AS category,
                COALESCE(entity_name, category, 'Snowflake action') AS entity,
                COALESCE(recommended_action, category, 'OVERWATCH action') AS description,
                COALESCE(owner, owner_email, approval_group, 'DBA / FinOps') AS owner,
                COALESCE(est_monthly_savings, 0) AS savings_monthly,
                CASE
                    WHEN UPPER(COALESCE(verification_status, '')) = 'VERIFIED' THEN TRUE
                    ELSE FALSE
                END AS verified,
                verification_result AS notes,
                'Cost avoided from verified action queue item.' AS business_impact
            FROM OVERWATCH_ACTION_QUEUE
            WHERE COALESCE(est_monthly_savings, 0) > 0
              AND UPPER(COALESCE(status, '')) IN ('FIXED', 'COMPLETED', 'DONE')
        ),
        alert_prevention AS (
            SELECT
                'ALERT_CLOSURE' AS value_source,
                'ALERT_EVENTS' AS evidence_source,
                TO_VARCHAR(event_id) AS evidence_id,
                COALESCE(category, 'Alert prevention') AS category,
                COALESCE(entity_name, category, 'Snowflake alert') AS entity,
                COALESCE(recommended_action, alert_key, 'Resolved OVERWATCH alert') AS description,
                COALESCE(owner, 'DBA On-Call') AS owner,
                CASE
                    WHEN UPPER(COALESCE(severity, '')) = 'CRITICAL' THEN 25000
                    WHEN UPPER(COALESCE(severity, '')) = 'HIGH' THEN 10000
                    WHEN UPPER(COALESCE(severity, '')) = 'MEDIUM' THEN 2500
                    ELSE 0
                END AS savings_monthly,
                TRUE AS verified,
                COALESCE(evidence, business_impact, impact_estimate, 'Resolved alert with OVERWATCH evidence.') AS notes,
                'Incident risk retired by alert triage and closure.' AS business_impact
            FROM ALERT_EVENTS
            WHERE UPPER(COALESCE(status, '')) IN ('RESOLVED', 'CLOSED')
              AND UPPER(COALESCE(severity, '')) IN ('CRITICAL', 'HIGH', 'MEDIUM')
        )
        SELECT * FROM cost_actions
        UNION ALL
        SELECT * FROM alert_prevention;

        CREATE OR REPLACE VIEW OVERWATCH_VALUE_AUTOMATION_HEALTH_V AS
        WITH candidates AS (
            SELECT
                COUNT(*) AS candidate_count,
                COUNT_IF(verified) AS verified_candidate_count,
                ROUND(SUM(COALESCE(savings_monthly, 0)), 2) AS candidate_monthly_value,
                ROUND(SUM(IFF(verified, COALESCE(savings_monthly, 0), 0)), 2) AS verified_candidate_monthly_value
            FROM OVERWATCH_VALUE_CANDIDATE_V
        ),
        ledger AS (
            SELECT
                COUNT(*) AS automated_ledger_rows,
                COUNT_IF(verified) AS verified_ledger_rows,
                ROUND(SUM(COALESCE(savings_monthly, 0)), 2) AS ledger_monthly_value,
                MAX(logged_date) AS latest_logged_date
            FROM OVERWATCH_ROI_LOG
            WHERE value_source IS NOT NULL
        ),
        last_run AS (
            SELECT
                run_ts AS latest_run_ts,
                run_status AS latest_run_status,
                candidate_count AS latest_candidate_count,
                inserted_count AS latest_inserted_count,
                verified_count AS latest_verified_count,
                message AS latest_message
            FROM OVERWATCH_VALUE_AUTOMATION_RUN
            QUALIFY ROW_NUMBER() OVER (ORDER BY run_ts DESC) = 1
        )
        SELECT
            c.candidate_count,
            c.verified_candidate_count,
            c.candidate_monthly_value,
            c.verified_candidate_monthly_value,
            l.automated_ledger_rows,
            l.verified_ledger_rows,
            l.ledger_monthly_value,
            l.latest_logged_date,
            r.latest_run_ts,
            r.latest_run_status,
            r.latest_candidate_count,
            r.latest_inserted_count,
            r.latest_verified_count,
            CASE
                WHEN r.latest_run_ts IS NULL THEN 'Deploy and run SP_OVERWATCH_AUTOMATE_VALUE_LOG.'
                WHEN r.latest_run_status <> 'SUCCESS' THEN 'Inspect OVERWATCH_VALUE_AUTOMATION_RUN before trusting value automation.'
                WHEN c.candidate_count > l.automated_ledger_rows THEN 'Run SP_OVERWATCH_AUTOMATE_VALUE_LOG to merge new candidates.'
                ELSE 'Automation ledger is current for visible candidates.'
            END AS next_action
        FROM candidates c
        CROSS JOIN ledger l
        LEFT JOIN last_run r ON TRUE;

        CREATE OR REPLACE PROCEDURE SP_OVERWATCH_AUTOMATE_VALUE_LOG()
        RETURNS VARCHAR
        LANGUAGE SQL
        EXECUTE AS CALLER
        AS
        $$
        DECLARE
          candidate_count NUMBER DEFAULT 0;
          inserted_count NUMBER DEFAULT 0;
          verified_count NUMBER DEFAULT 0;
        BEGIN
          SELECT COUNT(*), COUNT_IF(verified)
            INTO :candidate_count, :verified_count
          FROM OVERWATCH_VALUE_CANDIDATE_V;

          MERGE INTO OVERWATCH_ROI_LOG tgt
          USING (
            SELECT
                value_source,
                evidence_source,
                evidence_id,
                category,
                description,
                entity,
                owner,
                savings_monthly,
                verified,
                notes,
                business_impact
            FROM OVERWATCH_VALUE_CANDIDATE_V
          ) src
          ON COALESCE(tgt.evidence_id, '') = COALESCE(src.evidence_id, '')
             AND COALESCE(tgt.evidence_source, '') = COALESCE(src.evidence_source, '')
          WHEN NOT MATCHED THEN INSERT (
              logged_by, category, description, entity, baseline_credits,
              current_credits, savings_credits, savings_monthly, verified,
              company, notes, value_source, evidence_source, evidence_id,
              value_state, business_impact, owner, verified_ts
          )
          VALUES (
              'OVERWATCH_AUTOMATION', src.category, src.description, src.entity,
              NULL, NULL, NULL, src.savings_monthly, src.verified,
              NULL, src.notes, src.value_source, src.evidence_source, src.evidence_id,
              IFF(src.verified, 'VERIFIED', 'ESTIMATED'), src.business_impact,
              src.owner, IFF(src.verified, CURRENT_TIMESTAMP(), NULL)
          );

          inserted_count := SQLROWCOUNT;

          INSERT INTO OVERWATCH_VALUE_AUTOMATION_RUN (
              run_status, candidate_count, inserted_count, verified_count, message
          )
          VALUES (
              'SUCCESS', :candidate_count, :inserted_count, :verified_count,
              'Automated Snowflake value capture completed.'
          );

          RETURN 'OVERWATCH value automation complete. candidates=' || candidate_count ||
                 ', inserted=' || inserted_count || ', verified=' || verified_count;
        END;
        $$;
    """)


def build_snowflake_value_candidate_sql(limit: int = 100) -> str:
    """Return the read-only query for current no-touch value candidates."""
    limit = max(1, int(limit or 100))
    return _sql(f"""
        SELECT
            value_source,
            evidence_source,
            evidence_id,
            category,
            entity,
            owner,
            ROUND(savings_monthly, 2) AS savings_monthly,
            IFF(verified, 'VERIFIED', 'ESTIMATED') AS value_state,
            business_impact,
            notes
        FROM OVERWATCH_VALUE_CANDIDATE_V
        ORDER BY verified DESC, savings_monthly DESC, value_source, evidence_id
        LIMIT {limit};
    """)


def build_snowflake_value_automation_health_sql() -> str:
    """Return the read-only query for value automation freshness/readiness."""
    return _sql("""
        SELECT
            candidate_count,
            verified_candidate_count,
            candidate_monthly_value,
            verified_candidate_monthly_value,
            automated_ledger_rows,
            verified_ledger_rows,
            ledger_monthly_value,
            latest_logged_date,
            latest_run_ts,
            latest_run_status,
            latest_candidate_count,
            latest_inserted_count,
            latest_verified_count,
            next_action
        FROM OVERWATCH_VALUE_AUTOMATION_HEALTH_V;
    """)


def build_snowflake_value_automation_rows() -> list[dict[str, str]]:
    """Return the value automation model used by the UI."""
    return [
        {
            "VALUE_SIGNAL": "Measured cost action",
            "EVIDENCE_SOURCE": "OVERWATCH_ACTION_QUEUE",
            "VALUE_STATE": "Estimated until post-period measurement marks it measured",
            "CAPTURE_RULE": "Fixed/completed action with estimated monthly savings and measurement state.",
            "WHY_IT_MATTERS": "DBAs should not retype savings already measured by the queue.",
        },
        {
            "VALUE_SIGNAL": "Resolved alert with value at risk",
            "EVIDENCE_SOURCE": "ALERT_EVENTS",
            "VALUE_STATE": "Measured when alert is closed with resolution notes",
            "CAPTURE_RULE": "Closed/resolved alert with business impact or value_at_risk_usd.",
            "WHY_IT_MATTERS": "Incident prevention belongs in the value ledger, not only cost cuts.",
        },
        {
            "VALUE_SIGNAL": "Workload recovery",
            "EVIDENCE_SOURCE": "OVERWATCH_WORKLOAD_RECOVERY_AUDIT",
            "VALUE_STATE": "Estimated until duration/queue/error baseline improves",
            "CAPTURE_RULE": "Recovery audit rows with before/after runtime or SLA telemetry.",
            "WHY_IT_MATTERS": "Reliability wins are DBA value even when credits are flat.",
        },
        {
            "VALUE_SIGNAL": "Query optimization",
            "EVIDENCE_SOURCE": "QUERY_HISTORY / action queue",
            "VALUE_STATE": "Estimated until same query hash improves after change",
            "CAPTURE_RULE": "Query hash with reduced elapsed, spill, bytes scanned, or credit allocation.",
            "WHY_IT_MATTERS": "Specific SQL improvements need measured post-change telemetry.",
        },
    ]


def build_operational_intelligence_sql_catalog() -> list[dict[str, str]]:
    """Return SQL contracts for the twelve-command-intelligence foundation."""
    return [
        {
            "CAPABILITY": "Detection and Root-Cause Engine",
            "SQL_NAME": "Root-cause correlation",
            "TELEMETRY": "Delayed ACCOUNT_USAGE",
            "SQL": build_detection_root_cause_sql(),
        },
        {
            "CAPABILITY": "Task/Pipeline Critical Path Brain",
            "SQL_NAME": "Task critical path",
            "TELEMETRY": "TASK_HISTORY delayed plus INFORMATION_SCHEMA live option",
            "SQL": build_task_critical_path_brain_sql(),
        },
        {
            "CAPABILITY": "Data Quality and Reconciliation Center",
            "SQL_NAME": "Reconciliation config and runner",
            "TELEMETRY": "Metadata-driven",
            "SQL": build_data_reconciliation_config_ddl() + "\n" + build_data_reconciliation_runner_sql(),
        },
        {
            "CAPABILITY": "Predictive FinOps and Automated Value Log",
            "SQL_NAME": "Contract burn forecast and value automation",
            "TELEMETRY": "Metering plus action telemetry",
            "SQL": build_predictive_finops_sql() + "\n" + build_snowflake_value_auto_ddl(),
        },
        {
            "CAPABILITY": "Alert Lifecycle 2.0",
            "SQL_NAME": "Alert lifecycle status",
            "TELEMETRY": "Alert tables",
            "SQL": build_alert_lifecycle_sql(),
        },
        {
            "CAPABILITY": "Fact-Grounded AI Query Diagnosis",
            "SQL_NAME": "Cortex prompt contract",
            "TELEMETRY": "Query/profile telemetry",
            "SQL": build_ai_query_diagnosis_prompt_contract(),
        },
        {
            "CAPABILITY": "Bounded Refresh Guardrails",
            "SQL_NAME": "Refresh guardrail summary",
            "TELEMETRY": "Scoped summaries and bounded ACCOUNT_USAGE checks",
            "SQL": build_overwatch_self_monitoring_sql(),
        },
        {
            "CAPABILITY": "Fast Summary Layer With Fallback",
            "SQL_NAME": "Summary refresh and fallback view",
            "TELEMETRY": "Precompute contract",
            "SQL": build_precompute_contract_sql(),
        },
        {
            "CAPABILITY": "Security Risk Monitoring",
            "SQL_NAME": "Security risk monitoring",
            "TELEMETRY": "Security metadata",
            "SQL": build_compliance_readiness_sql(),
        },
        {
            "CAPABILITY": "Multi-Account / Org View",
            "SQL_NAME": "Organization usage rollup",
            "TELEMETRY": "Optional ORGADMIN",
            "SQL": build_multi_account_org_sql(),
        },
        {
            "CAPABILITY": "Data-First Navigation Contract",
            "SQL_NAME": "No saved-state navigation contract",
            "TELEMETRY": "App shell",
            "SQL": build_data_first_navigation_contract_sql(),
        },
        {
            "CAPABILITY": "Monitoring Docs and Runbooks",
            "SQL_NAME": "Status bundle",
            "TELEMETRY": "Repository docs",
            "SQL": "-- See docs/OVERWATCH_COMMAND_INTELLIGENCE_RUNBOOK.md and snowflake/PRECOMPUTE.sql.",
        },
    ]


def build_capability_setup_sql() -> str:
    """Return a single status bundle for the new command-intelligence objects."""
    return "\n\n".join(
        [
            "-- OVERWATCH command intelligence foundation",
            build_data_reconciliation_config_ddl(),
            build_data_first_navigation_contract_sql(),
            build_snowflake_value_auto_ddl(),
            build_precompute_contract_sql(),
            "-- Deploy views above only after privilege and refresh-cost review.",
        ]
    ).strip() + "\n"


def build_command_intelligence_runbook_markdown() -> str:
    """Return a compact DBA runbook for the twelve capabilities."""
    lines = [
        "# OVERWATCH Command Intelligence Runbook",
        "",
        f"Version: {COMMAND_INTELLIGENCE_VERSION}",
        "",
        "## Operating Rule",
        "",
        "Data should appear first. Buttons are for action or drilldown, not for hiding the main point of a section.",
        "",
        "## Priority Capabilities",
    ]
    for row in build_capability_register_rows():
        lines.extend(
            [
                "",
                f"### {row['RANK']}. {row['CAPABILITY']}",
                f"- Lands in: {row['WHERE_IT_LANDS']}",
                f"- Why it matters: {row['WHY_IT_MATTERS']}",
                f"- Next action: {row['NEXT_ACTION']}",
                f"- Snowflake sources: {row['SNOWFLAKE_SOURCES']}",
                f"- Guardrail: {row['PRODUCTION_GUARDRAIL']}",
            ]
        )
    lines.extend(
        [
            "",
            "## Automated Snowflake Value Log",
            "",
            "OVERWATCH should capture value candidates from action queue closure, alert resolution, workload recovery, and query optimization telemetry. One-off entries stay available for exceptional wins, but the default path is automated and telemetry-backed.",
            "",
            "Estimated value is directional. Measured value requires post-period telemetry and a recorded status result.",
        ]
    )
    return "\n".join(lines).strip() + "\n"
