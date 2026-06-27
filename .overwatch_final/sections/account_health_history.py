"""Account Health checklist history, closure, and snapshot persistence helpers."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from sections.account_health_checklist import (
    _account_health_actionable_checklist,
    _account_health_control_board,
    _annotate_account_health_checklist_readiness,
)
from sections.account_health_contracts import (
    ACCOUNT_HEALTH_ACCESS_HYGIENE_SOURCE,
    ACCOUNT_HEALTH_ACTION_SOURCE,
)
from sections.account_health_sql import (
    account_health_action_queue_fqn,
    account_health_checklist_history_fqn,
    account_health_operability_fact_fqn,
    build_account_health_checklist_history_ddl,
    build_account_health_checklist_history_migration_sql,
)
from sections.base import lazy_pandas, lazy_util as _lazy_util
from utils.primitives import safe_float


pd = lazy_pandas()

action_queue_environment_clause = _lazy_util("action_queue_environment_clause")
format_snowflake_error = _lazy_util("format_snowflake_error")
make_action_id = _lazy_util("make_action_id")
sql_literal = _lazy_util("sql_literal")


def _account_health_checklist_history_insert_sql(
    checklist: pd.DataFrame,
    *,
    company: str,
    environment: str,
    health_score: float,
    detail_source: str = "",
    snapshot_id: str = "",
) -> str:
    if checklist is None or checklist.empty:
        raise ValueError("Daily DBA Checklist snapshot has no rows to save.")
    fqn = account_health_checklist_history_fqn()
    env_value = str(environment or "").strip() or "ALL"
    snap = snapshot_id or make_action_id(
        "Account Health Checklist Snapshot",
        company,
        f"{env_value}|{datetime.now().strftime('%Y%m%d%H%M%S')}",
    )
    checklist = _annotate_account_health_checklist_readiness(checklist, environment=env_value)
    control_board = _account_health_control_board(checklist, environment=env_value)
    control_by_check = {
        str(row.get("CHECK_NAME") or "").upper(): row
        for _, row in control_board.iterrows()
    } if not control_board.empty else {}
    selects = []
    actionable = _account_health_actionable_checklist(checklist)
    actionable_checks = set(actionable.get("CHECK", pd.Series(dtype=str)).astype(str).tolist())
    for _, row in checklist.head(100).iterrows():
        check = str(row.get("CHECK") or "")
        control = control_by_check.get(check.upper(), {})
        selects.append(
            "SELECT "
            f"{sql_literal(snap, 64)} AS SNAPSHOT_ID, "
            "CURRENT_TIMESTAMP() AS SNAPSHOT_TS, "
            f"{sql_literal(company, 100)} AS COMPANY, "
            f"{sql_literal(env_value, 100)} AS ENVIRONMENT, "
            f"{sql_literal(check, 200)} AS CHECK_NAME, "
            f"{sql_literal(row.get('STATUS', ''), 80)} AS STATUS, "
            f"{sql_literal(row.get('SEVERITY', ''), 40)} AS SEVERITY, "
            f"{sql_literal(row.get('EVIDENCE', ''), 2000)} AS EVIDENCE, "
            f"{sql_literal(row.get('OWNER', ''), 200)} AS OWNER, "
            f"{sql_literal(row.get('ESCALATION_TARGET', ''), 200)} AS ESCALATION_TARGET, "
            f"{sql_literal(row.get('OWNER_SOURCE', ''), 200)} AS OWNER_SOURCE, "
            f"{sql_literal(row.get('ROUTE', ''), 120)} AS ROUTE, "
            f"{sql_literal(row.get('NEXT_ACTION', ''), 4000)} AS NEXT_ACTION, "
            f"{sql_literal(row.get('PROOF_REQUIRED', ''), 2000)} AS PROOF_REQUIRED, "
            f"{sql_literal(row.get('ENVIRONMENT_SCOPE', ''), 100)} AS ENVIRONMENT_SCOPE, "
            f"{sql_literal(row.get('DATABASE_CONTEXT', ''), 80)} AS DATABASE_CONTEXT, "
            f"{sql_literal(row.get('SCOPE_CONFIDENCE', ''), 160)} AS SCOPE_CONFIDENCE, "
            f"{sql_literal(row.get('SCOPE_EVIDENCE', ''), 2000)} AS SCOPE_EVIDENCE, "
            f"{sql_literal(row.get('APPROVAL_REQUIRED', ''), 20)} AS APPROVAL_REQUIRED, "
            f"{sql_literal(row.get('QUEUE_READINESS', ''), 80)} AS QUEUE_READINESS, "
            f"{sql_literal(row.get('QUEUE_BLOCKERS', ''), 2000)} AS QUEUE_BLOCKERS, "
            f"{sql_literal(row.get('VERIFICATION_QUERY', ''), 8000)} AS VERIFICATION_QUERY, "
            f"{safe_float(row.get('RECOVERY_SLA_TARGET_HOURS'))}::FLOAT AS RECOVERY_SLA_TARGET_HOURS, "
            f"{sql_literal(control.get('CONTROL_STATE', ''), 100)} AS CONTROL_READINESS, "
            f"{sql_literal(row.get('QUEUE_BLOCKERS', ''), 2000)} AS CONTROL_BLOCKERS, "
            f"{sql_literal(control.get('NEXT_CONTROL_ACTION', row.get('NEXT_ACTION', '')), 4000)} AS NEXT_CONTROL_ACTION, "
            f"{safe_float(health_score)}::FLOAT AS HEALTH_SCORE, "
            f"{sql_literal(detail_source, 500)} AS DETAIL_SOURCE, "
            f"{'TRUE' if check in actionable_checks else 'FALSE'} AS ACTIONABLE"
        )
    return f"""
INSERT INTO {fqn} (
    SNAPSHOT_ID, SNAPSHOT_TS, COMPANY, ENVIRONMENT, CHECK_NAME, STATUS,
    SEVERITY, EVIDENCE, OWNER, ESCALATION_TARGET, OWNER_SOURCE, ROUTE,
    NEXT_ACTION, PROOF_REQUIRED, ENVIRONMENT_SCOPE, DATABASE_CONTEXT,
    SCOPE_CONFIDENCE, SCOPE_EVIDENCE, APPROVAL_REQUIRED, QUEUE_READINESS,
    QUEUE_BLOCKERS, VERIFICATION_QUERY, RECOVERY_SLA_TARGET_HOURS,
    CONTROL_READINESS, CONTROL_BLOCKERS, NEXT_CONTROL_ACTION, HEALTH_SCORE,
    DETAIL_SOURCE, ACTIONABLE
)
{" UNION ALL ".join(selects)}""".strip()


def _account_health_checklist_history_sql(days: int, company: str, environment: str = "ALL") -> str:
    fqn = account_health_checklist_history_fqn()
    where = [f"SNAPSHOT_TS >= DATEADD('day', -{max(1, int(days or 14))}, CURRENT_TIMESTAMP())"]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_value = str(environment or "").strip()
    if env_value and env_value.upper() != "ALL":
        where.append(f"ENVIRONMENT = {sql_literal(env_value, 100)}")
    where_clause = " AND ".join(where)
    return f"""
SELECT
    CHECK_NAME,
    COUNT(*) AS SNAPSHOT_ROWS,
    COUNT_IF(ACTIONABLE) AS ISSUE_SNAPSHOTS,
    MAX(SNAPSHOT_TS) AS LAST_SNAPSHOT_TS,
    MAX_BY(STATUS, SNAPSHOT_TS) AS LAST_STATUS,
    MAX_BY(SEVERITY, SNAPSHOT_TS) AS LAST_SEVERITY,
    MAX_BY(OWNER, SNAPSHOT_TS) AS OWNER,
    MAX_BY(ESCALATION_TARGET, SNAPSHOT_TS) AS ESCALATION_TARGET,
    MAX_BY(ROUTE, SNAPSHOT_TS) AS ROUTE,
    MAX_BY(QUEUE_READINESS, SNAPSHOT_TS) AS QUEUE_READINESS,
    MAX_BY(QUEUE_BLOCKERS, SNAPSHOT_TS) AS QUEUE_BLOCKERS,
    MAX_BY(SCOPE_CONFIDENCE, SNAPSHOT_TS) AS SCOPE_CONFIDENCE,
    MAX_BY(CONTROL_READINESS, SNAPSHOT_TS) AS CONTROL_READINESS,
    MAX_BY(NEXT_CONTROL_ACTION, SNAPSHOT_TS) AS NEXT_CONTROL_ACTION,
    COUNT_IF(QUEUE_READINESS <> 'Ready to Queue') AS ROUTE_BLOCKER_SNAPSHOTS,
    COUNT_IF(CONTROL_READINESS IN ('Closure Overdue', 'Closure Status Pending', 'Route Metadata Blocked', 'Queue Required')) AS CONTROL_BLOCKER_SNAPSHOTS,
    ROUND(AVG(HEALTH_SCORE), 1) AS AVG_HEALTH_SCORE
FROM {fqn}
WHERE {where_clause}
GROUP BY CHECK_NAME
ORDER BY CONTROL_BLOCKER_SNAPSHOTS DESC, ISSUE_SNAPSHOTS DESC, LAST_SNAPSHOT_TS DESC, CHECK_NAME
LIMIT 100""".strip()


def _account_health_closure_analytics_sql(days: int, company: str, environment: str = "ALL") -> str:
    fqn = account_health_action_queue_fqn()
    where = [
        (
            "SOURCE IN ("
            f"{sql_literal(ACCOUNT_HEALTH_ACTION_SOURCE, 100)}, "
            f"{sql_literal(ACCOUNT_HEALTH_ACCESS_HYGIENE_SOURCE, 100)}"
            ")"
        ),
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
        COALESCE(ENTITY_NAME, 'Daily DBA checklist') AS CHECK_NAME,
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
        CHECK_NAME,
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
        COUNT_IF(UPPER(OWNER) IN ('', 'DBA', 'UNKNOWN', 'N/A', 'DBA / COST OWNER', 'DBA / DATA ENGINEERING')) AS OWNER_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(TICKET_ID)) = 0) AS TICKET_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(APPROVER)) = 0) AS APPROVER_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(VERIFICATION_QUERY)) = 0) AS VERIFICATION_QUERY_GAP_ROWS,
        COUNT_IF(UPPER(OWNER_APPROVAL_STATUS) IN ('', 'PENDING', 'REQUESTED', 'REQUIRED')) AS OWNER_APPROVAL_GAP_ROWS,
        COUNT_IF(
            UPPER(RECOVERY_SLA_STATE) ILIKE '%BREACH%'
            OR UPPER(RECOVERY_SLA_STATE) ILIKE '%LATE%'
            OR (
                UPPER(RECOVERY_SLA_STATE) IN ('OPEN FAILURE', 'RECOVERY SLA BREACH')
                AND LENGTH(TRIM(RECOVERY_EVIDENCE)) = 0
            )
        ) AS RECOVERY_RISK_ROWS,
        MIN(IFF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED'), DUE_DATE, NULL)) AS NEXT_DUE_DATE,
        MAX(LAST_ACTIVITY_TS) AS LAST_ACTIVITY_TS,
        MAX_BY(STATUS, LAST_ACTIVITY_TS) AS LAST_STATUS,
        MAX_BY(SEVERITY, LAST_ACTIVITY_TS) AS LAST_SEVERITY
    FROM scoped_actions
    GROUP BY CHECK_NAME
)
SELECT
    CHECK_NAME,
    CASE
        WHEN OVERDUE_OPEN > 0 THEN 'Overdue closure'
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 'Closed pending telemetry'
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 'Control metadata gap'
        WHEN OPEN_ACTIONS > 0 THEN 'Open'
        WHEN VERIFIED_CLOSURES > 0 THEN 'Telemetry closure'
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
        WHEN OVERDUE_OPEN > 0 THEN 'Escalate owner and due date before lower-risk checklist work.'
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 'Reopen the checklist action or wait for telemetry to confirm closure.'
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 'Complete route, ticket, reviewer, and telemetry metadata.'
        WHEN OPEN_ACTIONS > 0 THEN 'Work the open checklist action and keep telemetry current before closing.'
        ELSE 'Keep closure status visible for trend review.'
    END AS NEXT_ACTION
FROM rollup
ORDER BY CLOSURE_RANK, OVERDUE_OPEN DESC, FIXED_WITHOUT_VERIFICATION DESC, OPEN_ACTIONS DESC, LAST_ACTIVITY_TS DESC
LIMIT 100""".strip()


def _account_health_operability_fact_sql(days: int, company: str, environment: str = "ALL") -> str:
    """Read Account Health checklist, hygiene, and closure blockers from the fast summary."""
    table = account_health_operability_fact_fqn()
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
    CHECK_NAME,
    ROUTE,
    SEVERITY,
    CONTROL_STATE,
    CONTROL_RANK,
    HEALTH_SCORE,
    ISSUE_ROWS,
    ROUTE_BLOCKER_ROWS,
    QUEUE_REQUIRED_ROWS,
    ACCESS_HYGIENE_ROWS,
    FAILED_LOGIN_ROWS,
    PRIVILEGED_GRANT_ROWS,
    OPEN_ACTIONS,
    OVERDUE_OPEN,
    FIXED_WITHOUT_VERIFICATION,
    VERIFIED_CLOSURES,
    OWNER_APPROVAL_GAP_ROWS,
    RECOVERY_RISK_ROWS,
    NEXT_CONTROL_ACTION,
    LAST_ACTIVITY_TS,
    LOAD_TS
FROM {table}
WHERE {where_clause}
ORDER BY
    CONTROL_RANK,
    OVERDUE_OPEN DESC,
    FIXED_WITHOUT_VERIFICATION DESC,
    ROUTE_BLOCKER_ROWS DESC,
    ISSUE_ROWS DESC,
    LAST_ACTIVITY_TS DESC
LIMIT 100""".strip()


def _save_account_health_checklist_snapshot(
    session,
    checklist: pd.DataFrame,
    *,
    company: str,
    environment: str,
    health_score: float,
    detail_source: str = "",
) -> None:
    try:
        session.sql(build_account_health_checklist_history_ddl()).collect()
        for migration_sql in build_account_health_checklist_history_migration_sql():
            session.sql(migration_sql).collect()
        session.sql(_account_health_checklist_history_insert_sql(
            checklist,
            company=company,
            environment=environment,
            health_score=health_score,
            detail_source=detail_source,
        )).collect()
        st.success("Saved the Daily DBA Checklist snapshot for trend tracking.")
    except Exception as exc:
        st.error(f"Could not save Daily DBA Checklist snapshot: {format_snowflake_error(exc)}")
        st.info("Checklist history is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")


__all__ = [
    "_account_health_checklist_history_insert_sql",
    "_account_health_checklist_history_sql",
    "_account_health_closure_analytics_sql",
    "_account_health_operability_fact_sql",
    "_save_account_health_checklist_snapshot",
]
