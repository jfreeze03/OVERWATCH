# sections/change_drift_sql.py - Change Drift SQL/evidence builders
from sections.base import lazy_util as _lazy_util
from config import ALERT_DB, ALERT_SCHEMA, ACTION_QUEUE_TABLE
from sections.change_drift_contracts import (
    CHANGE_CONTROL_EVIDENCE_TABLE,
    CHANGE_CONTROL_OPERABILITY_FACT_TABLE,
)

filter_existing_columns = _lazy_util("filter_existing_columns")
get_environment_case_expr = _lazy_util("get_environment_case_expr")
get_global_filter_clause = _lazy_util("get_global_filter_clause")
mart_object_name = _lazy_util("mart_object_name")
safe_identifier = _lazy_util("safe_identifier")
sql_literal = _lazy_util("sql_literal")
action_queue_environment_clause = _lazy_util("action_queue_environment_clause")

def change_control_evidence_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHANGE_CONTROL_EVIDENCE_TABLE,
) -> str:
    return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}"

def build_change_control_evidence_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHANGE_CONTROL_EVIDENCE_TABLE,
) -> str:
    fqn = change_control_evidence_fqn(db=db, schema=schema, table=table)
    return f"""CREATE TABLE IF NOT EXISTS {fqn} (
    SNAPSHOT_ID              VARCHAR(64),
    SNAPSHOT_TS              TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    COMPANY                  VARCHAR(100),
    ENVIRONMENT              VARCHAR(100),
    FINDING_TYPE             VARCHAR(120),
    SEVERITY                 VARCHAR(40),
    ENTITY                   VARCHAR(500),
    USER_NAME                VARCHAR(300),
    ROLE_NAME                VARCHAR(300),
    QUERY_ID                 VARCHAR(200),
    QUERY_TAG                VARCHAR(1000),
    LAST_SEEN                VARCHAR(100),
    CHANGE_CONTROL_STATE     VARCHAR(120),
    CONTROL_GAP              VARCHAR(1000),
    CHANGE_TICKET_ID         VARCHAR(200),
    CHANGE_TICKET_STATE      VARCHAR(120),
    IAC_RECONCILIATION_STATE VARCHAR(160),
    EXECUTION_AUDIT_STATE    VARCHAR(160),
    OWNER                    VARCHAR(200),
    ESCALATION_TARGET        VARCHAR(200),
    OWNER_SOURCE             VARCHAR(200),
    APPROVER                 VARCHAR(200),
    OWNER_APPROVAL_STATUS    VARCHAR(40),
    APPROVAL_REQUIRED        VARCHAR(20),
    TICKET_REQUIRED          VARCHAR(20),
    BLAST_RADIUS_REQUIRED    VARCHAR(20),
    APPROVAL_ROUTE_READY     VARCHAR(20),
    CHANGE_EVIDENCE_READINESS VARCHAR(80),
    EVIDENCE_BLOCKERS        VARCHAR(2000),
    REVIEW_SLA_HOURS         NUMBER,
    NEXT_CONTROL_ACTION      VARCHAR(4000),
    PROOF_REQUIRED           VARCHAR(2000),
    VERIFICATION_QUERY       VARCHAR(8000),
    BLAST_RADIUS_QUERY       VARCHAR(8000),
    SOURCE                   VARCHAR(500)
);"""

def build_change_control_evidence_migration_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHANGE_CONTROL_EVIDENCE_TABLE,
) -> list[str]:
    """Return additive migrations for previously deployed telemetry tables."""
    fqn = change_control_evidence_fqn(db=db, schema=schema, table=table)
    return [
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS APPROVAL_ROUTE_READY VARCHAR(20)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CHANGE_EVIDENCE_READINESS VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS EVIDENCE_BLOCKERS VARCHAR(2000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS REVIEW_SLA_HOURS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS NEXT_CONTROL_ACTION VARCHAR(4000)",
    ]

def change_control_operability_fact_fqn(table: str = CHANGE_CONTROL_OPERABILITY_FACT_TABLE) -> str:
    return mart_object_name(table)

def build_change_control_operability_fact_ddl(table: str = CHANGE_CONTROL_OPERABILITY_FACT_TABLE) -> str:
    fqn = change_control_operability_fact_fqn(table=table)
    return f"""CREATE TRANSIENT TABLE IF NOT EXISTS {fqn} (
    SNAPSHOT_DATE              DATE,
    COMPANY                    VARCHAR(100),
    ENVIRONMENT                VARCHAR(100),
    CONTROL_SOURCE             VARCHAR(80),
    CONTROL_KEY                VARCHAR(500),
    FINDING_TYPE               VARCHAR(120),
    ENTITY                     VARCHAR(500),
    OWNER                      VARCHAR(200),
    ESCALATION_TARGET          VARCHAR(200),
    SEVERITY                   VARCHAR(40),
    EVIDENCE_ROWS              NUMBER,
    HIGH_RISK_CHANGES          NUMBER,
    ROUTE_BLOCKED              NUMBER,
    CLOSURE_BLOCKED            NUMBER,
    REVIEW_READY               NUMBER,
    MISSING_TICKET_ROWS        NUMBER,
    IAC_GAP_ROWS               NUMBER,
    MISSING_QUERY_ID_ROWS      NUMBER,
    OPEN_ACTIONS               NUMBER,
    OVERDUE_OPEN               NUMBER,
    FIXED_WITHOUT_VERIFICATION NUMBER,
    VERIFIED_CLOSURES          NUMBER,
    OWNER_APPROVAL_GAP_ROWS    NUMBER,
    CONTROL_STATE              VARCHAR(120),
    CONTROL_RANK               NUMBER,
    NEXT_CONTROL_ACTION        VARCHAR(4000),
    LAST_ACTIVITY_TS           TIMESTAMP_NTZ,
    LOAD_TS                    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);"""

def build_change_control_operability_fact_migration_sql(
    table: str = CHANGE_CONTROL_OPERABILITY_FACT_TABLE,
) -> list[str]:
    fqn = change_control_operability_fact_fqn(table=table)
    return [
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_SOURCE VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_KEY VARCHAR(500)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS HIGH_RISK_CHANGES NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS ROUTE_BLOCKED NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CLOSURE_BLOCKED NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS REVIEW_READY NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS OWNER_APPROVAL_GAP_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_STATE VARCHAR(120)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_RANK NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS NEXT_CONTROL_ACTION VARCHAR(4000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS LAST_ACTIVITY_TS TIMESTAMP_NTZ",
    ]

def _change_scope_clause(
    date_col: str,
    wh_col: str,
    user_col: str,
    role_col: str,
    db_col: str,
    schema_col: str = "schema_name",
) -> str:
    """Apply company and triage filters while keeping account-level changes under environment scopes."""
    return get_global_filter_clause(
        date_col=date_col,
        wh_col=wh_col,
        user_col=user_col,
        role_col=role_col,
        db_col=db_col,
        schema_col=schema_col,
        preserve_no_database_context=True,
    )

def _bare_sql_predicate(fragment: str) -> str:
    """Return a WHERE-list predicate without a leading conjunction."""
    text = str(fragment or "").strip()
    while text.upper().startswith(("AND ", "OR ")):
        text = text.split(None, 1)[1].strip()
    return text

def _build_change_drift_sql(session, days: int, company: str) -> tuple[str, str]:
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        ["QUERY_TAG"],
    ))
    query_tag_expr = "query_tag" if "QUERY_TAG" in qh_cols else "NULL::VARCHAR"
    manual_drift_predicate = (
        "AND COALESCE(query_tag, '') NOT ILIKE '%deployment%'"
        if "QUERY_TAG" in qh_cols else ""
    )
    scope = _change_scope_clause(
        date_col="start_time",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
    )
    base_where = f"""
        start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
        {scope}
    """
    summary_sql = f"""
    WITH changes AS (
        SELECT
            query_id,
            user_name,
            role_name,
            warehouse_name,
            database_name,
            schema_name,
            start_time,
            {query_tag_expr} AS query_tag,
            query_text,
            CASE
                WHEN query_text ILIKE 'DROP%' THEN 'DESTRUCTIVE'
                WHEN query_text ILIKE '%MASKING POLICY%' OR query_text ILIKE '%ROW ACCESS POLICY%' OR query_text ILIKE '%TAG%' THEN 'POLICY'
                WHEN query_text ILIKE '%OWNERSHIP%' THEN 'OWNER'
                WHEN query_text ILIKE 'GRANT%' OR query_text ILIKE 'REVOKE%' OR query_text ILIKE 'CREATE%ROLE%' OR query_text ILIKE 'ALTER%ROLE%' OR query_text ILIKE 'DROP%ROLE%' THEN 'ACCESS'
                WHEN query_text ILIKE 'CREATE%' OR query_text ILIKE 'ALTER%' THEN 'OBJECT'
                ELSE 'OTHER'
            END AS change_family
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE {base_where}
          AND (
            query_text ILIKE 'CREATE%' OR query_text ILIKE 'ALTER%' OR query_text ILIKE 'DROP%'
            OR query_text ILIKE 'GRANT%' OR query_text ILIKE 'REVOKE%' OR query_text ILIKE '%OWNERSHIP%'
            OR query_text ILIKE '%MASKING POLICY%' OR query_text ILIKE '%ROW ACCESS POLICY%' OR query_text ILIKE '%TAG%'
          )
    )
    SELECT
        '{company}' AS company,
        COUNT_IF(change_family IN ('OBJECT', 'DESTRUCTIVE')) AS object_changes,
        COUNT_IF(change_family IN ('ACCESS', 'OWNER')) AS access_changes,
        COUNT_IF(change_family = 'OWNER') AS owner_changes,
        COUNT_IF(change_family = 'POLICY') AS policy_changes,
        COUNT_IF(change_family = 'DESTRUCTIVE') AS destructive_changes,
        COUNT_IF(change_family <> 'OTHER' {manual_drift_predicate}) AS manual_drift,
        COUNT(DISTINCT user_name) AS actors,
        COUNT(DISTINCT database_name) AS affected_databases,
        COUNT_IF(database_name IS NULL) AS account_scope_changes
    FROM changes
    """
    exceptions_sql = f"""
    WITH changes AS (
        SELECT
            query_id,
            user_name,
            role_name,
            warehouse_name,
            database_name,
            schema_name,
            start_time,
            {query_tag_expr} AS query_tag,
            SUBSTR(query_text, 1, 1500) AS query_text,
            CASE
                WHEN query_text ILIKE 'DROP%' THEN 'Destructive Object Change'
                WHEN query_text ILIKE '%MASKING POLICY%' OR query_text ILIKE '%ROW ACCESS POLICY%' OR query_text ILIKE '%TAG%' THEN 'Policy or Tag Change'
                WHEN query_text ILIKE '%OWNERSHIP%' THEN 'Owner Change'
                WHEN query_text ILIKE 'GRANT%' OR query_text ILIKE 'REVOKE%' OR query_text ILIKE 'CREATE%ROLE%' OR query_text ILIKE 'ALTER%ROLE%' OR query_text ILIKE 'DROP%ROLE%' THEN 'Grant or Role Change'
                WHEN query_text ILIKE 'CREATE%' OR query_text ILIKE 'ALTER%' THEN 'Object Change'
                ELSE 'Other Change'
            END AS finding_type
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE {base_where}
          AND (
            query_text ILIKE 'CREATE%' OR query_text ILIKE 'ALTER%' OR query_text ILIKE 'DROP%'
            OR query_text ILIKE 'GRANT%' OR query_text ILIKE 'REVOKE%' OR query_text ILIKE '%OWNERSHIP%'
            OR query_text ILIKE '%MASKING POLICY%' OR query_text ILIKE '%ROW ACCESS POLICY%' OR query_text ILIKE '%TAG%'
          )
          {manual_drift_predicate}
    )
    SELECT
        finding_type,
        CASE
            WHEN finding_type IN ('Destructive Object Change', 'Policy or Tag Change', 'Owner Change') THEN 'High'
            WHEN finding_type = 'Grant or Role Change' THEN 'Medium'
            ELSE 'Low'
        END AS severity,
        COALESCE(database_name || '.' || schema_name, database_name, query_id) AS entity,
        user_name,
        role_name,
        query_id,
        start_time AS last_seen,
        1 AS event_count,
        'QUERY_HISTORY query_id = ' || query_id AS proof_query,
        database_name,
        IFF(database_name IS NULL, FALSE, TRUE) AS database_context,
        {get_environment_case_expr("database_name")} AS environment,
        IFF(database_name IS NULL, 'Account/Role Context', 'Database Context') AS scope_confidence,
        IFF(database_name IS NULL, 'No database context; retained under environment scope', 'Database=' || database_name) AS scope_evidence,
        query_text
    FROM changes
    WHERE finding_type <> 'Other Change'
    ORDER BY
        CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END,
        start_time DESC
    LIMIT 100
    """
    return summary_sql, exceptions_sql

def _build_mart_change_drift_sql(days: int, company: str) -> tuple[str, str]:
    """Build change/drift brief SQL from the OVERWATCH object-change fact."""
    table = mart_object_name("FACT_OBJECT_CHANGE")
    company_filter = "" if str(company or "").upper() == "ALL" else f"AND company = {sql_literal(company, 100)}"
    scope = _change_scope_clause(
        date_col="start_time",
        wh_col="",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
    )
    base_where = f"""
        start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
        {company_filter}
        {scope}
    """
    summary_sql = f"""
    SELECT
        '{company}' AS company,
        COUNT_IF(change_category IN ('CREATE', 'ALTER', 'DROP')) AS object_changes,
        COUNT_IF(change_category IN ('GRANT', 'OWNER')) AS access_changes,
        COUNT_IF(change_category = 'OWNER') AS owner_changes,
        COUNT_IF(change_category = 'POLICY') AS policy_changes,
        COUNT_IF(change_category = 'DROP') AS destructive_changes,
        COUNT_IF(COALESCE(query_tag, '') NOT ILIKE '%deployment%') AS manual_drift,
        COUNT(DISTINCT user_name) AS actors,
        COUNT(DISTINCT database_name) AS affected_databases,
        COUNT_IF(database_name IS NULL) AS account_scope_changes
    FROM {table}
    WHERE {base_where}
    """
    exceptions_sql = f"""
    SELECT
        CASE
            WHEN change_category = 'DROP' THEN 'Destructive Object Change'
            WHEN change_category = 'POLICY' THEN 'Policy or Tag Change'
            WHEN change_category = 'OWNER' THEN 'Owner Change'
            WHEN change_category = 'GRANT' THEN 'Grant or Role Change'
            WHEN change_category IN ('CREATE', 'ALTER') THEN 'Object Change'
            ELSE 'Other Change'
        END AS finding_type,
        CASE
            WHEN change_category IN ('DROP', 'POLICY', 'OWNER') THEN 'High'
            WHEN change_category = 'GRANT' THEN 'Medium'
            ELSE 'Low'
        END AS severity,
        COALESCE(database_name || '.' || schema_name, database_name, query_id) AS entity,
        user_name,
        role_name,
        query_id,
        start_time AS last_seen,
        1 AS event_count,
        'FACT_OBJECT_CHANGE query_id = ' || query_id AS proof_query,
        database_name,
        IFF(database_name IS NULL, FALSE, TRUE) AS database_context,
        {get_environment_case_expr("database_name")} AS environment,
        IFF(database_name IS NULL, 'Account/Role Context', 'Database Context') AS scope_confidence,
        IFF(database_name IS NULL, 'No database context; retained under environment scope', 'Database=' || database_name) AS scope_evidence,
        query_tag,
        SUBSTR(query_text, 1, 1500) AS query_text
    FROM {table}
    WHERE {base_where}
      AND change_category <> 'OTHER'
      AND COALESCE(query_tag, '') NOT ILIKE '%deployment%'
    ORDER BY
        CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END,
        start_time DESC
    LIMIT 100
    """
    return summary_sql, exceptions_sql

def _change_control_evidence_history_sql(days: int, company: str, environment: str = "ALL") -> str:
    fqn = change_control_evidence_fqn()
    where = [f"SNAPSHOT_TS >= DATEADD('day', -{max(1, int(days or 14))}, CURRENT_TIMESTAMP())"]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_value = str(environment or "").strip()
    if env_value and env_value.upper() != "ALL":
        where.append(f"ENVIRONMENT = {sql_literal(env_value, 100)}")
    where_clause = " AND ".join(where)
    return f"""
SELECT
    FINDING_TYPE,
    SEVERITY,
    OWNER,
    ESCALATION_TARGET,
    COUNT(*) AS EVIDENCE_ROWS,
    COUNT_IF(CHANGE_TICKET_STATE ILIKE 'Missing%') AS MISSING_TICKET_ROWS,
    COUNT_IF(IAC_RECONCILIATION_STATE ILIKE '%required%' OR IAC_RECONCILIATION_STATE ILIKE '%Reconcile%') AS IAC_GAP_ROWS,
    COUNT_IF(EXECUTION_AUDIT_STATE ILIKE 'Missing%') AS MISSING_QUERY_ID_ROWS,
    MAX(SNAPSHOT_TS) AS LAST_SNAPSHOT_TS,
    MAX_BY(CHANGE_CONTROL_STATE, SNAPSHOT_TS) AS LAST_CONTROL_STATE,
    MAX_BY(CONTROL_GAP, SNAPSHOT_TS) AS LAST_CONTROL_GAP
FROM {fqn}
WHERE {where_clause}
GROUP BY FINDING_TYPE, SEVERITY, OWNER, ESCALATION_TARGET
ORDER BY
    MISSING_TICKET_ROWS DESC,
    IAC_GAP_ROWS DESC,
    MISSING_QUERY_ID_ROWS DESC,
    LAST_SNAPSHOT_TS DESC
LIMIT 100""".strip()

def _change_ticket_sql_expr(query_tag_col: str = "QUERY_TAG", query_text_col: str = "QUERY_TEXT") -> str:
    return (
        "UPPER(COALESCE(REGEXP_SUBSTR("
        f"COALESCE({query_tag_col}, '') || ' ' || COALESCE({query_text_col}, ''), "
        "'(CHG|CHANGE|INC|REQ|RFC|OWNER_APPROVAL)[-_]?[0-9]+|[A-Z][A-Z0-9]+-[0-9]+', 1, 1, 'i'"
        "), ''))"
    )

def _change_object_where(days: int, company: str) -> list[str]:
    lookback = max(1, int(days or 14))
    object_where = [
        f"START_TIME >= DATEADD('day', -{lookback}, CURRENT_TIMESTAMP())",
        "CHANGE_CATEGORY <> 'OTHER'",
    ]
    if str(company or "").upper() != "ALL":
        object_where.append(f"COMPANY = {sql_literal(company, 100)}")
    object_scope = _change_scope_clause(
        date_col="start_time",
        wh_col="",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
    )
    if object_scope:
        object_where.append(_bare_sql_predicate(object_scope))
    return object_where

def _change_action_queue_closure_sql(days: int, company: str, environment: str = "ALL") -> str:
    fqn = f"{safe_identifier(ALERT_DB)}.{safe_identifier(ALERT_SCHEMA)}.{safe_identifier(ACTION_QUEUE_TABLE)}"
    where = [
        "SOURCE = 'Change & Drift - Brief'",
        f"COALESCE(UPDATED_AT, CREATED_AT) >= DATEADD('day', -{max(1, int(days or 30))}, CURRENT_TIMESTAMP())",
    ]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_clause = action_queue_environment_clause("ENVIRONMENT", environment)
    if env_clause:
        where.append(env_clause)
    where_clause = " AND ".join(where)
    return f"""
WITH scoped_actions AS (
    SELECT
        COALESCE(CATEGORY, 'Object Change Monitoring') AS CATEGORY,
        COALESCE(ENTITY_TYPE, 'Change') AS ENTITY_TYPE,
        COALESCE(ENTITY_NAME, 'Unknown') AS ENTITY,
        COALESCE(OWNER, '') AS OWNER,
        COALESCE(APPROVER, '') AS APPROVER,
        COALESCE(STATUS, 'New') AS STATUS,
        COALESCE(SEVERITY, 'Medium') AS SEVERITY,
        COALESCE(TICKET_ID, '') AS TICKET_ID,
        DUE_DATE,
        COALESCE(VERIFICATION_STATUS, '') AS VERIFICATION_STATUS,
        COALESCE(VERIFICATION_QUERY, PROOF_QUERY, '') AS VERIFICATION_QUERY,
        COALESCE(VERIFICATION_RESULT, '') AS VERIFICATION_RESULT,
        COALESCE(OWNER_APPROVAL_STATUS, '') AS OWNER_APPROVAL_STATUS,
        COALESCE(RECOVERY_SLA_STATE, '') AS RECOVERY_SLA_STATE,
        COALESCE(RECOVERY_EVIDENCE, '') AS RECOVERY_EVIDENCE,
        COALESCE(UPDATED_AT, CREATED_AT) AS LAST_ACTIVITY_TS
    FROM {fqn}
    WHERE {where_clause}
),
rollup AS (
    SELECT
        CATEGORY,
        ENTITY_TYPE,
        ENTITY,
        MAX_BY(OWNER, LAST_ACTIVITY_TS) AS OWNER,
        MAX_BY(APPROVER, LAST_ACTIVITY_TS) AS APPROVER,
        COUNT(*) AS TOTAL_ACTIONS,
        COUNT_IF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED')) AS OPEN_ACTIONS,
        COUNT_IF(UPPER(STATUS) = 'FIXED') AS FIXED_ACTIONS,
        COUNT_IF(
            UPPER(STATUS) = 'FIXED'
            AND UPPER(VERIFICATION_STATUS) = 'VERIFIED'
            AND LENGTH(TRIM(VERIFICATION_RESULT)) >= 15
        ) AS VERIFIED_CLOSURES,
        COUNT_IF(
            UPPER(STATUS) = 'FIXED'
            AND (
                UPPER(VERIFICATION_STATUS) <> 'VERIFIED'
                OR LENGTH(TRIM(VERIFICATION_RESULT)) < 15
            )
        ) AS FIXED_WITHOUT_VERIFICATION,
        COUNT_IF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) AS OVERDUE_OPEN,
        COUNT_IF(UPPER(OWNER) IN ('', 'DBA', 'UNKNOWN', 'N/A', 'DBA CHANGE OWNER')) AS OWNER_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(TICKET_ID)) = 0) AS TICKET_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(APPROVER)) = 0) AS APPROVER_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(VERIFICATION_QUERY)) = 0) AS VERIFICATION_QUERY_GAP_ROWS,
        COUNT_IF(UPPER(OWNER_APPROVAL_STATUS) IN ('', 'PENDING', 'REQUESTED', 'REQUIRED')) AS OWNER_APPROVAL_GAP_ROWS,
        COUNT_IF(
            UPPER(RECOVERY_SLA_STATE) ILIKE '%BREACH%'
            OR UPPER(RECOVERY_SLA_STATE) ILIKE '%LATE%'
            OR (
                UPPER(STATUS) = 'FIXED'
                AND LENGTH(TRIM(RECOVERY_EVIDENCE)) < 15
            )
        ) AS RECOVERY_RISK_ROWS,
        MIN(IFF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED'), DUE_DATE, NULL)) AS NEXT_DUE_DATE,
        MAX(LAST_ACTIVITY_TS) AS LAST_ACTIVITY_TS,
        MAX_BY(STATUS, LAST_ACTIVITY_TS) AS LAST_STATUS,
        MAX_BY(SEVERITY, LAST_ACTIVITY_TS) AS LAST_SEVERITY
    FROM scoped_actions
    GROUP BY CATEGORY, ENTITY_TYPE, ENTITY
)
SELECT
    CATEGORY,
    ENTITY_TYPE,
    ENTITY,
    CASE
        WHEN OVERDUE_OPEN > 0 THEN 'Overdue closure'
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 'Closed pending telemetry'
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 'Control metadata gap'
        WHEN OPEN_ACTIONS > 0 THEN 'Open'
        WHEN VERIFIED_CLOSURES > 0 THEN 'Telemetry-confirmed closure'
        ELSE 'No recent action'
    END AS CLOSURE_READINESS,
    CASE
        WHEN OVERDUE_OPEN > 0 THEN 0
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 1
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 2
        WHEN OPEN_ACTIONS > 0 THEN 3
        WHEN VERIFIED_CLOSURES > 0 THEN 8
        ELSE 9
    END AS CLOSURE_RANK,
    OWNER,
    APPROVER,
    TOTAL_ACTIONS,
    OPEN_ACTIONS,
    FIXED_ACTIONS,
    VERIFIED_CLOSURES,
    FIXED_WITHOUT_VERIFICATION,
    OVERDUE_OPEN,
    OWNER_GAP_ROWS,
    TICKET_GAP_ROWS,
    APPROVER_GAP_ROWS,
    VERIFICATION_QUERY_GAP_ROWS,
    OWNER_APPROVAL_GAP_ROWS,
    RECOVERY_RISK_ROWS,
    NEXT_DUE_DATE,
    LAST_STATUS,
    LAST_SEVERITY,
    LAST_ACTIVITY_TS,
    CASE
        WHEN OVERDUE_OPEN > 0 THEN 'Escalate the change route and ticket before accepting more drift.'
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 'Record query, ticket, rollback, and blast-radius telemetry or reopen the action.'
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 'Complete route, ticket, reviewer, and telemetry metadata.'
        WHEN OPEN_ACTIONS > 0 THEN 'Work the open change action and retain review or rollback status.'
        ELSE 'Retain closure telemetry for audit review.'
    END AS NEXT_ACTION
FROM rollup
ORDER BY CLOSURE_RANK, OVERDUE_OPEN DESC, FIXED_WITHOUT_VERIFICATION DESC, OPEN_ACTIONS DESC, LAST_ACTIVITY_TS DESC
LIMIT 100""".strip()

def _change_control_operability_fact_sql(days: int, company: str, environment: str = "ALL") -> str:
    """Read object-change blockers from the fast summary."""
    table = change_control_operability_fact_fqn()
    where = [f"SNAPSHOT_DATE >= DATEADD('day', -{max(1, int(days or 30))}, CURRENT_DATE())"]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_clause = action_queue_environment_clause("ENVIRONMENT", environment)
    if env_clause:
        where.append(env_clause)
    where_clause = " AND ".join(where)
    return f"""
SELECT
    SNAPSHOT_DATE,
    COMPANY,
    ENVIRONMENT,
    CONTROL_SOURCE,
    CONTROL_KEY,
    FINDING_TYPE,
    ENTITY,
    OWNER,
    ESCALATION_TARGET,
    SEVERITY,
    EVIDENCE_ROWS,
    HIGH_RISK_CHANGES,
    ROUTE_BLOCKED,
    CLOSURE_BLOCKED,
    REVIEW_READY,
    MISSING_TICKET_ROWS,
    IAC_GAP_ROWS,
    MISSING_QUERY_ID_ROWS,
    OPEN_ACTIONS,
    OVERDUE_OPEN,
    FIXED_WITHOUT_VERIFICATION,
    VERIFIED_CLOSURES,
    OWNER_APPROVAL_GAP_ROWS,
    CONTROL_STATE,
    CONTROL_RANK,
    NEXT_CONTROL_ACTION,
    LAST_ACTIVITY_TS,
    LOAD_TS
FROM {table}
WHERE {where_clause}
ORDER BY
    CONTROL_RANK,
    OVERDUE_OPEN DESC,
    FIXED_WITHOUT_VERIFICATION DESC,
    ROUTE_BLOCKED DESC,
    CLOSURE_BLOCKED DESC,
    HIGH_RISK_CHANGES DESC,
    LAST_ACTIVITY_TS DESC
LIMIT 100""".strip()

__all__ = ['change_control_evidence_fqn', 'build_change_control_evidence_ddl', 'build_change_control_evidence_migration_sql', 'change_control_operability_fact_fqn', 'build_change_control_operability_fact_ddl', 'build_change_control_operability_fact_migration_sql', '_change_scope_clause', '_bare_sql_predicate', '_build_change_drift_sql', '_build_mart_change_drift_sql', '_change_control_evidence_history_sql', '_change_ticket_sql_expr', '_change_object_where', '_change_action_queue_closure_sql', '_change_control_operability_fact_sql']
