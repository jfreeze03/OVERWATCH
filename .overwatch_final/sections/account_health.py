"""Account Health: daily checklist, source readiness, and DBA morning brief."""
from __future__ import annotations

import streamlit as st
from datetime import datetime
from sections.account_health_common import *  # noqa: F403
from sections.account_health_contracts import *  # noqa: F403
from sections.account_health_data import *  # noqa: F403
from sections.account_health_checklist import *  # noqa: F403
from sections.account_health_access_hygiene import *  # noqa: F403
from sections.account_health_action_queue import *  # noqa: F403
from sections.account_health_access_hygiene_view import *  # noqa: F403
from sections.account_health_morning_view import *  # noqa: F403
from sections.account_health_models import *  # noqa: F403
from sections.account_health_source_health_view import *  # noqa: F403
from sections.account_health_sql import *  # noqa: F403
from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.navigation import apply_navigation_state
from sections.shell_helpers import render_shell_kpi_row, render_shell_snapshot
from utils.primitives import safe_float, safe_int


pd = lazy_pandas()

run_query = _lazy_util("run_query")
format_credits = _lazy_util("format_credits")
credits_to_dollars = _lazy_util("credits_to_dollars")
download_csv = _lazy_util("download_csv")
mark_loaded = _lazy_util("mark_loaded")
show_loaded_time = _lazy_util("show_loaded_time")
build_metered_credit_cte = _lazy_util("build_metered_credit_cte")
build_monitoring_cost_sql = _lazy_util("build_monitoring_cost_sql")
metric_confidence_label = _lazy_util("metric_confidence_label")
freshness_note = _lazy_util("freshness_note")
render_drillable_bar_chart = _lazy_util("render_drillable_bar_chart")
executive_health_score = _lazy_util("executive_health_score")
get_wh_filter_clause = _lazy_util("get_wh_filter_clause")
get_db_filter_clause = _lazy_util("get_db_filter_clause")
get_global_filter_clause = _lazy_util("get_global_filter_clause")
get_active_environment = _lazy_util("get_active_environment")
load_latest_control_room_mart = _lazy_util("load_latest_control_room_mart")
mart_source_caption = _lazy_util("mart_source_caption")
build_mart_account_health_storage_sql = _lazy_util("build_mart_account_health_storage_sql")
build_mart_account_health_cost_drivers_sql = _lazy_util("build_mart_account_health_cost_drivers_sql")
build_mart_account_health_change_sql = _lazy_util("build_mart_account_health_change_sql")
build_mart_control_room_task_failures_sql = _lazy_util("build_mart_control_room_task_failures_sql")
build_mart_control_room_warehouse_pressure_sql = _lazy_util("build_mart_control_room_warehouse_pressure_sql")
format_snowflake_error = _lazy_util("format_snowflake_error")
make_action_id = _lazy_util("make_action_id")
sql_literal = _lazy_util("sql_literal")
action_queue_environment_clause = _lazy_util("action_queue_environment_clause")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
render_mode_selector = _lazy_util("render_mode_selector")
day_window_selectbox = _lazy_util("day_window_selectbox")
load_shared_usage_storage_kpis = _lazy_util("load_shared_usage_storage_kpis")
load_shared_usage_metering_kpis = _lazy_util("load_shared_usage_metering_kpis")
load_shared_query_history_rollup = _lazy_util("load_shared_query_history_rollup")
load_shared_warehouse_pressure_summary = _lazy_util("load_shared_warehouse_pressure_summary")


def _drill_to(
    section: str,
    wh_filter: str = "",
    user_filter: str = "",
    workflow_key: str = "",
    workflow: str = "",
):
    apply_navigation_state(section)
    if workflow_key and workflow:
        st.session_state[workflow_key] = workflow
    if wh_filter:
        st.session_state["lm_wh"]     = wh_filter
        st.session_state["wh_filter"] = wh_filter
    if user_filter:
        st.session_state["global_user"] = user_filter
    st.rerun()


def _render_account_health_operating_snapshot(
    *,
    health_score: float,
    score_label: str,
    live_val: int,
    queued: int,
    err_count: int,
    last24: float,
    pct_delta: float,
    cost24: float,
    stor_tb: float,
    failed_tasks: int,
    hd: dict,
    live_source: str,
    control_mart_used: bool,
    control_mart_row,
) -> None:
    """Render the Account Health first-screen metrics without crowding the page."""
    render_shell_kpi_row((
        ("Health", f"{health_score:.0f} {score_label}".strip()),
        ("Failures", f"{err_count:,}"),
        ("Queue", f"{queued:,}"),
        ("Cost 24h", f"${cost24:,.0f} ({pct_delta:+.1f}%)"),
    ))
    with st.expander("Secondary metrics", expanded=False):
        render_shell_snapshot((
            ("Active", f"{live_val:,}"),
            ("Credits 24h", format_credits(last24)),
            ("Storage", f"{stor_tb:.1f} TB"),
            ("Failed Tasks", f"{failed_tasks:,}"),
        ))
        st.caption(
            " | ".join([
                metric_confidence_label("composite"),
                metric_confidence_label("exact") + " for input counts",
                str(hd.get("_control_mart_source", "Live telemetry")).replace("OVERWATCH mart", "Fast summary").replace("mart", "summary").replace("source", "input"),
                freshness_note(live_source),
            ])
        )
        if control_mart_used:
            st.caption(f"Snapshot: {control_mart_row.get('SNAPSHOT_TS', '')}")
        st.caption(f"Measurement basis: {hd.get('_account_health_detail_source', 'Unknown')}")


def _account_health_intervention_matrix(
    *,
    checklist: pd.DataFrame | None,
    control_board: pd.DataFrame | None = None,
    closure: pd.DataFrame | None = None,
    access_hygiene: pd.DataFrame | None = None,
    operability_fact: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a compact Account Health worklist from already-loaded account telemetry."""
    control = control_board if isinstance(control_board, pd.DataFrame) else pd.DataFrame()
    hygiene = access_hygiene if isinstance(access_hygiene, pd.DataFrame) else pd.DataFrame()
    fact = operability_fact if isinstance(operability_fact, pd.DataFrame) else pd.DataFrame()
    checks = pd.DataFrame() if checklist is None else _annotate_account_health_checklist_readiness(checklist)

    rows: list[dict] = []
    if not control.empty:
        for _, row in control.head(25).iterrows():
            control_state = str(row.get("CONTROL_STATE") or "Review")
            check_name = str(row.get("CHECK_NAME") or row.get("CHECK") or "Account Health")
            severity = str(row.get("SEVERITY") or "Medium")
            route = str(row.get("ROUTE") or "Account Health")
            queue_readiness = str(row.get("QUEUE_READINESS") or "")
            closure_state = "Open"
            if safe_int(row.get("OVERDUE_OPEN")) > 0:
                closure_state = "Overdue"
            elif safe_int(row.get("FIXED_WITHOUT_VERIFICATION")) > 0:
                closure_state = "Closed pending telemetry"
            elif safe_int(row.get("VERIFIED_CLOSURES")) > 0:
                closure_state = "Verified"
            scope = str(row.get("SCOPE_CONFIDENCE") or row.get("DATABASE_CONTEXT") or "Account-Level Control")

            control_upper = control_state.upper()
            if "BLOCK" in control_upper or closure_state in {"Overdue", "Closed pending telemetry"}:
                state = "Closure Block"
                rank = 0
                decision = "Hold green account-health claims until ticket, route, telemetry, and recovery status are current."
            elif queue_readiness != "Ready to Queue" or "REQUIRED" in control_upper:
                state = "Route Block"
                rank = 1
                decision = "Complete route, reviewer, and telemetry basis before queueing this account-health issue."
            elif severity.upper() in {"CRITICAL", "HIGH"}:
                state = "Intervene"
                rank = 2
                decision = "Work this high-risk account-health issue before routine monitoring."
            else:
                state = "Watch"
                rank = 4
                decision = "Keep on the daily checklist and retain trend telemetry."

            rows.append({
                "DBA_PRIORITY": f"P{rank}",
                "INTERVENTION_STATE": state,
                "SURFACE": check_name,
                "SEVERITY": severity,
                "ROUTE": route,
                "OWNER": str(row.get("OWNER") or "DBA"),
                "CONTROL_STATE": control_state,
                "QUEUE_READINESS": queue_readiness or "Unknown",
                "CLOSURE_READINESS": closure_state,
                "SCOPE_CONFIDENCE": scope,
                "COUNT": max(
                    safe_int(row.get("OPEN_ACTIONS")),
                    safe_int(row.get("ISSUE_SNAPSHOTS")),
                    safe_int(row.get("OVERDUE_OPEN")),
                    1,
                ),
                "NEXT_DECISION": decision,
                "PROOF_REQUIRED": str(row.get("PROOF_REQUIRED") or "route, ticket, telemetry status, recovery state"),
                "_RANK": rank,
            })

    existing_surfaces = {str(row["SURFACE"]).upper() for row in rows}
    if not hygiene.empty and "ACCOUNT ACCESS HYGIENE" not in existing_surfaces:
        severity_series = hygiene.get("SEVERITY", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
        high_rows = int(severity_series.isin(["CRITICAL", "HIGH"]).sum())
        route_blocks = 0
        if "QUEUE_READINESS" in hygiene.columns:
            route_blocks = int(hygiene["QUEUE_READINESS"].fillna("").astype(str).ne("Ready to Queue").sum())
        state = "Route Block" if route_blocks else "Intervene" if high_rows else "Watch"
        rank = 1 if route_blocks else 2 if high_rows else 4
        rows.append({
            "DBA_PRIORITY": f"P{rank}",
            "INTERVENTION_STATE": state,
            "SURFACE": "Account Access Hygiene",
            "SEVERITY": "High" if high_rows else "Medium",
            "ROUTE": "Security Monitoring",
            "OWNER": "DBA / Security",
            "CONTROL_STATE": "High-risk access review" if high_rows else "Access hygiene review",
            "QUEUE_READINESS": "Needs Routing Data" if route_blocks else "Ready to Queue",
            "CLOSURE_READINESS": "No recent action",
            "SCOPE_CONFIDENCE": "Account-Level Control",
            "COUNT": len(hygiene),
            "NEXT_DECISION": "Review privileged grants, failed logins, MFA gaps, and service-user exposure at account scope.",
            "PROOF_REQUIRED": "user, role/grant, MFA/IAM posture, telemetry status",
            "_RANK": rank,
        })

    if not fact.empty and "CONTROL_STATE" in fact.columns:
        blocked = fact["CONTROL_STATE"].fillna("").astype(str).str.contains("Blocked|Overdue|Required|Review", case=False, na=False)
        if int(blocked.sum()) and not rows:
            rows.append({
                "DBA_PRIORITY": "P3",
                "INTERVENTION_STATE": "Fact Review",
                "SURFACE": "Account Health control summary",
                "SEVERITY": "Medium",
                "ROUTE": "DBA Control Room",
                "OWNER": "DBA",
                "CONTROL_STATE": "Summary blocker",
                "QUEUE_READINESS": "Review",
                "CLOSURE_READINESS": "Review",
                "SCOPE_CONFIDENCE": "Mixed",
                "COUNT": int(blocked.sum()),
                "NEXT_DECISION": "Load the matching detailed surface only for the blocked control rows.",
                "PROOF_REQUIRED": "fact row, source surface, escalation route, telemetry status",
                "_RANK": 3,
            })

    if not rows and not checks.empty:
        actionable = _account_health_actionable_checklist(checks)
        if not actionable.empty:
            rows.append({
                "DBA_PRIORITY": "P4",
                "INTERVENTION_STATE": "Checklist Review",
                "SURFACE": "Daily DBA checklist",
                "SEVERITY": "Medium",
                "ROUTE": "DBA Control Room",
                "OWNER": "DBA",
                "CONTROL_STATE": "Checklist issue",
                "QUEUE_READINESS": "Review",
                "CLOSURE_READINESS": "No recent action",
                "SCOPE_CONFIDENCE": "Mixed",
                "COUNT": len(actionable),
                "NEXT_DECISION": "Queue only checklist rows with route, telemetry, and recovery expectations.",
                "PROOF_REQUIRED": "check telemetry, route, telemetry query",
                "_RANK": 4,
            })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        ["_RANK", "COUNT", "SURFACE"],
        ascending=[True, False, True],
    ).drop(columns=["_RANK"], errors="ignore").reset_index(drop=True)


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


ACCOUNT_HEALTH_RENDERERS = {
    "Morning Report": render_account_health_morning_report,
}


def render():
    credit_price = get_credit_price()
    company      = st.session_state.get("active_company", "ALFA")
    environment  = get_active_environment()
    wh_filter_q = get_wh_filter_clause("q.warehouse_name", company)
    wh_filter_m = get_wh_filter_clause("warehouse_name", company)
    db_filter_q = get_db_filter_clause("q.database_name", company)
    query_scope_filter_q = get_global_filter_clause(
        "", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name"
    )
    global_filter_q = get_global_filter_clause(
        "q.start_time", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name"
    )
    query_history_caps = None

    def _query_history_capabilities(action_session=None) -> dict:
        nonlocal query_history_caps
        if query_history_caps is None:
            if action_session is None:
                action_session = _account_health_action_session("load Account Health QUERY_HISTORY metadata")
            query_history_caps = _account_query_history_capabilities(action_session)
        return query_history_caps

    active_view = render_mode_selector(
        "Account Health view",
        "account_health_active_view",
        ACCOUNT_HEALTH_PANES,
        default=ACCOUNT_HEALTH_PANES[0],
        details=ACCOUNT_HEALTH_PANE_DETAILS,
        labels=ACCOUNT_HEALTH_PANE_LABELS,
        columns=2,
    )

    renderer = ACCOUNT_HEALTH_RENDERERS.get(active_view)
    if renderer is not None:
        renderer(company, environment, credit_price)
        return

    # -- OVERVIEW --------------------------------------------------------------
    if active_view == "Overview":
        render_operator_briefing(
            [
                ("First move", "Refresh the health snapshot and read the exception signals."),
                ("Telemetry", "Use cost drivers, failed work, warehouse pressure, and changes since yesterday."),
                ("Control", "Drill into the guarded workflow before recommending action."),
                ("Output", "Build the DBA morning brief from verified Control Room and Account Health facts."),
            ],
            columns=4,
        )
        exceptions_only = bool(st.session_state.get("exceptions_only_mode", False))
        if exceptions_only:
            st.info("Leadership exceptions-only mode is on. Heavy drilldowns stay collapsed until you ask for detail.")
        if _account_health_has_source_state(st.session_state):
            _render_account_health_source_health(company, environment)

        cache_age = 999
        filter_sig = "|".join([
            str(company),
            str(st.session_state.get("global_start_date", "")),
            str(st.session_state.get("global_end_date", "")),
            str(st.session_state.get("global_warehouse", "")),
            str(st.session_state.get("global_user", "")),
            str(st.session_state.get("global_role", "")),
            str(st.session_state.get("global_database", "")),
        ])
        last_ts = st.session_state.get("_health_ts")
        if last_ts:
            cache_age = (datetime.now() - datetime.fromisoformat(last_ts)).total_seconds()

        health_loaded = isinstance(st.session_state.get("health_data"), dict) and bool(st.session_state.get("health_data"))
        stale_scope = health_loaded and st.session_state.get("_health_filter_sig") != filter_sig
        auto_refresh_health = (
            (not health_loaded or stale_scope)
            and st.session_state.get("_account_health_auto_load_attempt_scope") != filter_sig
        )
        if auto_refresh_health:
            st.session_state["_account_health_auto_load_attempt_scope"] = filter_sig
        refresh_health = st.button("Load / Refresh Health", key="health_refresh") or auto_refresh_health
        if not refresh_health:
            if not health_loaded:
                st.info("Health snapshot is available on demand. Refresh when you need current Account Health telemetry.")
            elif stale_scope:
                st.warning("Loaded health snapshot is stale for the active filters. Refresh before acting.")
            elif cache_age > 300:
                st.caption(f"Loaded health snapshot is {cache_age / 60:.1f} minutes old. Refresh when current telemetry matters.")

        if refresh_health:
            action_session = _account_health_action_session("load Account Health")
            if action_session is None:
                return
            hd = {}
            mart_ok, mart_reason = _can_use_control_room_mart(company)
            control_mart = load_latest_control_room_mart(company) if mart_ok else None
            use_control_mart = bool(
                control_mart is not None
                and control_mart.available
                and control_mart.data is not None
                and not control_mart.data.empty
            )
            hd["_control_mart"] = control_mart.data if control_mart is not None else pd.DataFrame()
            hd["_control_mart_source"] = (
                mart_source_caption(control_mart)
                if control_mart is not None
                else f"Live fallback: {mart_reason}"
            )
            hd["_control_mart_used"] = use_control_mart
            live_df, live_source = _load_live_query_status("", "", query_scope_filter_q)
            hd["live"] = live_df
            hd["_live_source"] = live_source
            if use_control_mart:
                query_plan = [
                    ("storage", build_mart_account_health_storage_sql(company)),
                    ("cost_drivers", build_mart_account_health_cost_drivers_sql(24, company)),
                    ("failed_jobs", build_mart_control_room_task_failures_sql(24, company)),
                    ("what_changed", build_mart_account_health_change_sql(24, company)),
                ]
                hd["_account_health_detail_source"] = "Fast summary"
            else:
                qh = _query_history_capabilities(action_session)
                cost_wh_size_expr = qh["cost_wh_size_expr"]
                cost_bytes_scanned_expr = qh["cost_bytes_scanned_expr"]
                failed_pred_q = qh["failed_pred_q"]
                queued_count_expr_q = qh["queued_count_expr_q"]
                query_plan = [
                    ("cost_drivers", f"""
                    WITH {build_metered_credit_cte(hours_back=48, include_recent=True)}
                    SELECT q.user_name, q.warehouse_name, {cost_wh_size_expr} AS warehouse_size,
                           COUNT(*) AS query_count,
                           ROUND(SUM(COALESCE(pqc.metered_credits,0)), 4) AS total_credits,
                           ROUND({cost_bytes_scanned_expr}/POWER(1024,3), 2) AS gb_scanned
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                    WHERE q.start_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
                      AND q.warehouse_name IS NOT NULL
                      {global_filter_q}
                    GROUP BY q.user_name, q.warehouse_name
                    ORDER BY total_credits DESC
                    LIMIT 5
                """),
                ("failed_jobs", _task_failure_sql_or_empty(
                    action_session,
                    "scheduled_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())",
                        5,
                        company,
                    )),
                    ("what_changed", f"""
                    WITH today_q AS (
                        SELECT COUNT(*) AS q,
                               SUM(CASE WHEN {failed_pred_q} THEN 1 ELSE 0 END) AS fails
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        WHERE q.start_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
                          {query_scope_filter_q}
                    ),
                    yday_q AS (
                        SELECT COUNT(*) AS q,
                               SUM(CASE WHEN {failed_pred_q} THEN 1 ELSE 0 END) AS fails
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        WHERE q.start_time >= DATEADD('hours', -48, CURRENT_TIMESTAMP())
                          AND q.start_time <  DATEADD('hours', -24, CURRENT_TIMESTAMP())
                          {query_scope_filter_q}
                    ),
                    today_c AS (
                        SELECT SUM(credits_used) AS credits
                        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                        WHERE start_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
                          {wh_filter_m}
                    ),
                    yday_c AS (
                        SELECT SUM(credits_used) AS credits
                        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                        WHERE start_time >= DATEADD('hours', -48, CURRENT_TIMESTAMP())
                          AND start_time < DATEADD('hours', -24, CURRENT_TIMESTAMP())
                          {wh_filter_m}
                    )
                    SELECT today_q.q - yday_q.q AS query_delta,
                           ROUND(COALESCE(today_c.credits, 0) - COALESCE(yday_c.credits, 0), 4) AS credit_delta,
                           today_q.fails - yday_q.fails AS failure_delta
                    FROM today_q, yday_q, today_c, yday_c
                    """),
                ]
                hd["_account_health_detail_source"] = "Live fallback: ACCOUNT_USAGE"
            if not use_control_mart:
                burn_result = load_shared_usage_metering_kpis(
                    action_session,
                    1,
                    company,
                    force=True,
                    section="Account Health",
                )
                if not burn_result.data.empty:
                    burn_row = burn_result.data.iloc[0]
                    last_24h = safe_float(burn_row.get("TOTAL_CREDITS", 0))
                    prior_24h = safe_float(burn_row.get("PRIOR_CREDITS", 0))
                else:
                    last_24h = 0.0
                    prior_24h = 0.0
                hd["burn"] = pd.DataFrame([{
                    "LAST_24H": last_24h,
                    "PRIOR_24H": prior_24h,
                }])
                hd["_burn_source"] = burn_result.source
                query_rollup_result = load_shared_query_history_rollup(
                    action_session,
                    1,
                    company,
                    force=True,
                    section="Account Health",
                )
                query_rollup = query_rollup_result.data
                if query_rollup is not None and not query_rollup.empty:
                    rollup_row = query_rollup.iloc[0]
                else:
                    rollup_row = {}
                failed_queries = safe_int(getattr(rollup_row, "get", lambda *_: 0)("FAILED_QUERIES", 0))
                hd["errors"] = pd.DataFrame([{"ERR_COUNT": failed_queries}])
                hd["query_stats"] = pd.DataFrame([{
                    "TOTAL_QUERIES": safe_float(getattr(rollup_row, "get", lambda *_: 0)("TOTAL_QUERIES", 0)),
                    "FAILED_QUERIES": safe_float(getattr(rollup_row, "get", lambda *_: 0)("FAILED_QUERIES", 0)),
                    "QUEUED_QUERIES": safe_float(getattr(rollup_row, "get", lambda *_: 0)("QUEUED_QUERIES", 0)),
                    "AVG_ELAPSED_SEC": safe_float(getattr(rollup_row, "get", lambda *_: 0)("AVG_ELAPSED_SEC", 0)),
                }])
                hd["_query_rollup_source"] = query_rollup_result.source

                pressure_result = load_shared_warehouse_pressure_summary(
                    action_session,
                    1,
                    company,
                    force=True,
                    section="Account Health",
                )
                hd["warehouse_pressure"] = pressure_result.data
                hd["_warehouse_pressure_source"] = pressure_result.source
                storage_result = load_shared_usage_storage_kpis(
                    1,
                    company,
                    force=True,
                    section="Account Health",
                )
                storage_summary = storage_result.data
                if storage_summary is not None and not storage_summary.empty:
                    storage_row = storage_summary.iloc[0]
                    storage_tb = safe_float(storage_row.get("ACTIVE_STORAGE_TB", 0)) + safe_float(
                        storage_row.get("FAILSAFE_STORAGE_TB", 0)
                    )
                    hd["storage"] = pd.DataFrame([{"STORAGE_TB": storage_tb}])
                else:
                    hd["storage"] = pd.DataFrame(columns=["STORAGE_TB"])
                hd["_storage_source"] = storage_result.source
                query_plan = [
                ("task_health", _task_health_sql_or_empty(
                    action_session,
                    "scheduled_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())",
                    company,
                )),
                ] + query_plan
            for key, sql in query_plan:
                hd[key] = run_query(
                    sql,
                    ttl_key=f"account_health_live_{company}_{key}",
                    tier="recent",
                    section="Account Health",
                )

            st.session_state["health_data"] = hd
            st.session_state["_health_ts"]  = datetime.now().isoformat()
            st.session_state["_health_filter_sig"] = filter_sig
            st.session_state["account_health_overview_meta"] = _account_health_scope_meta(
                company, environment, window="24h"
            )
            st.session_state["account_health_live_status_meta"] = _account_health_scope_meta(
                company, environment, window="1h"
            )
            mark_loaded("account_health")

        hd = st.session_state.get("health_data", {})
        if not isinstance(hd, dict) or not hd:
            return

        live_df    = hd.get("live",    pd.DataFrame())
        live_source = hd.get("_live_source", "ACCOUNT_USAGE")
        burn_df    = hd.get("burn",    pd.DataFrame())
        err_df     = hd.get("errors",  pd.DataFrame())
        storage_df = hd.get("storage", pd.DataFrame())
        query_stats_df = hd.get("query_stats", pd.DataFrame())
        task_health_df = hd.get("task_health", pd.DataFrame())
        warehouse_pressure_df = hd.get("warehouse_pressure", pd.DataFrame())
        control_mart_df = hd.get("_control_mart", pd.DataFrame())
        control_mart_used = bool(hd.get("_control_mart_used", False)) and not control_mart_df.empty
        control_mart_row = control_mart_df.iloc[0] if control_mart_used else {}
        live_val  = safe_int(live_df["ACTIVE_COUNT"].iloc[0]) if not live_df.empty else 0
        queued    = safe_int(live_df["QUEUED_COUNT"].iloc[0]) if not live_df.empty else 0
        stor_tb   = safe_float(storage_df["STORAGE_TB"].iloc[0]) if not storage_df.empty else 0
        if control_mart_used:
            last24 = safe_float(control_mart_row.get("CREDITS_24H", 0))
            cost24 = safe_float(control_mart_row.get("COST_24H_USD", credits_to_dollars(last24, credit_price)))
            err_count = safe_int(control_mart_row.get("FAILED_QUERIES_24H", 0))
            failed_tasks = safe_int(control_mart_row.get("FAILED_TASKS_24H", 0))
            object_changes = safe_int(control_mart_row.get("OBJECT_CHANGES_24H", 0))
            queued_ms = safe_float(control_mart_row.get("QUEUED_MS_24H", 0))
            pct_delta = 0
            health_score = safe_float(control_mart_row.get("HEALTH_SCORE", 0))
            score_label = _mart_health_label(health_score)
            health_components = pd.DataFrame([
                {"Component": "Failed queries", "Observed": err_count, "Source": "Fast summary"},
                {"Component": "Failed tasks", "Observed": failed_tasks, "Source": "Fast summary"},
                {"Component": "Queued minutes", "Observed": round(queued_ms / 60000, 2), "Source": "Fast summary"},
                {"Component": "Security events", "Observed": safe_int(control_mart_row.get("SECURITY_EVENTS_24H", 0)), "Source": "Fast summary"},
                {"Component": "Object changes", "Observed": safe_int(control_mart_row.get("OBJECT_CHANGES_24H", 0)), "Source": "Fast summary"},
                {"Component": "Top risk", "Observed": control_mart_row.get("TOP_RISK", ""), "Source": "Fast summary"},
            ])
        else:
            last24 = safe_float(burn_df["LAST_24H"].iloc[0]) if not burn_df.empty else 0
            prior24 = safe_float(burn_df["PRIOR_24H"].iloc[0]) if not burn_df.empty else 0
            cost24 = credits_to_dollars(last24, credit_price)
            err_count = safe_int(err_df["ERR_COUNT"].iloc[0]) if not err_df.empty else 0
            failed_tasks = safe_int(task_health_df["FAILED_TASKS"].iloc[0]) if not task_health_df.empty else 0
            object_changes = 0
            pct_delta = ((last24 - prior24) / prior24 * 100) if prior24 > 0 else 0
            health = executive_health_score({
                "total_queries": safe_float(query_stats_df["TOTAL_QUERIES"].iloc[0]) if not query_stats_df.empty else 0,
                "failed_queries": err_count,
                "queued_queries": safe_float(query_stats_df["QUEUED_QUERIES"].iloc[0]) if not query_stats_df.empty else queued,
                "avg_elapsed_sec": safe_float(query_stats_df["AVG_ELAPSED_SEC"].iloc[0]) if not query_stats_df.empty else 0,
                "task_runs": safe_float(task_health_df["TASK_RUNS"].iloc[0]) if not task_health_df.empty else 0,
                "failed_tasks": safe_float(task_health_df["FAILED_TASKS"].iloc[0]) if not task_health_df.empty else 0,
                "active_warehouses": safe_float(warehouse_pressure_df["ACTIVE_WAREHOUSES"].iloc[0]) if not warehouse_pressure_df.empty else 0,
                "pressure_warehouses": safe_float(warehouse_pressure_df["PRESSURE_WAREHOUSES"].iloc[0]) if not warehouse_pressure_df.empty else 0,
                "current_credits": last24,
                "prior_credits": prior24,
                "current_storage_tb": stor_tb,
                "prior_storage_tb": stor_tb,
            })
            health_score = health["score"]
            score_label = health["label"]
            health_components = pd.DataFrame(health["components"])

        checklist = _build_account_health_dba_checklist(
            health_score=health_score,
            score_label=score_label,
            err_count=err_count,
            queued=queued,
            pct_delta=pct_delta,
            last24=last24,
            stor_tb=stor_tb,
            failed_tasks=failed_tasks,
            object_changes=object_changes,
            control_mart_used=control_mart_used,
            detail_source=hd.get("_account_health_detail_source", ""),
        )
        checklist = _annotate_account_health_checklist_readiness(
            checklist,
            environment=get_active_environment(),
        )
        _render_account_health_action_brief(checklist)
        _render_account_health_operating_snapshot(
            health_score=health_score,
            score_label=score_label,
            live_val=live_val,
            queued=queued,
            err_count=err_count,
            last24=last24,
            pct_delta=pct_delta,
            cost24=cost24,
            stor_tb=stor_tb,
            failed_tasks=failed_tasks,
            hd=hd,
            live_source=live_source,
            control_mart_used=control_mart_used,
            control_mart_row=control_mart_row,
        )
        if st.button("Load Control Summary", key="account_health_load_operability_fact"):
            try:
                operability_sql = _account_health_operability_fact_sql(30, company, get_active_environment())
                st.session_state["account_health_operability_fact_sql"] = operability_sql
                st.session_state["account_health_operability_fact"] = run_query(
                    operability_sql,
                    ttl_key=f"account_health_operability_fact_{company}_{get_active_environment()}_30",
                    tier="standard",
                    section="Account Health",
                )
                st.session_state["account_health_operability_fact_meta"] = _account_health_scope_meta(
                    company, environment, window="30d"
                )
                st.session_state.pop("account_health_operability_fact_error", None)
            except Exception as fact_exc:
                st.session_state["account_health_operability_fact"] = pd.DataFrame()
                st.session_state["account_health_operability_fact_error"] = format_snowflake_error(fact_exc)
        operability_fact = st.session_state.get("account_health_operability_fact")
        account_control_board = _account_health_control_board(
            checklist,
            closure=st.session_state.get("account_health_closure_analytics"),
            access_hygiene=st.session_state.get("account_health_access_hygiene"),
            trend=st.session_state.get("account_health_checklist_trend"),
            environment=get_active_environment(),
        )
        operability_gate_fact = operability_fact if (
            operability_fact is not None
            and not operability_fact.empty
            and _account_health_meta_matches(
                st.session_state.get("account_health_operability_fact_meta"),
                _account_health_scope_meta(company, environment, window="30d"),
            )
        ) else pd.DataFrame()
        account_operator_gates = _account_health_operator_next_moves(
            health_score=health_score,
            checklist=checklist,
            control_board=account_control_board,
            closure=st.session_state.get("account_health_closure_analytics"),
            access_hygiene=st.session_state.get("account_health_access_hygiene"),
            operability_fact=operability_gate_fact,
            source_health=_account_health_source_health_rows(st.session_state, company, environment),
        )
        account_intervention_matrix = _account_health_intervention_matrix(
            checklist=checklist,
            control_board=account_control_board,
            closure=st.session_state.get("account_health_closure_analytics"),
            access_hygiene=st.session_state.get("account_health_access_hygiene"),
            operability_fact=operability_gate_fact,
        )
        account_morning_exceptions = _account_health_morning_exception_rows(
            checklist=checklist,
            gates=account_operator_gates,
            interventions=account_intervention_matrix,
            control_board=account_control_board,
            health_score=health_score,
            err_count=err_count,
            queued=queued,
            pct_delta=pct_delta,
            failed_tasks=failed_tasks,
        )
        st.session_state["account_health_checklist"] = checklist
        st.session_state["account_health_operator_gates"] = account_operator_gates
        st.session_state["account_health_control_board"] = account_control_board
        st.session_state["account_health_intervention_matrix"] = account_intervention_matrix
        st.session_state["account_health_morning_exceptions"] = account_morning_exceptions
        _render_account_health_exception_strip(account_morning_exceptions)
        account_detail = st.selectbox(
            "Account Health detail",
            ("Checklist", "Gates", "Interventions", "Controls", "Operability"),
            label_visibility="collapsed",
            key="account_health_overview_detail",
        )
        if account_detail == "Checklist":
            actionable_checklist = _account_health_actionable_checklist(checklist)
            show_full_checklist = st.toggle(
                "Show full checklist",
                key="account_health_show_full_checklist",
                value=False,
                help="Default keeps morning triage focused on checklist rows that need DBA action.",
            )
            checklist_view, checklist_title, checklist_raw_label = _account_health_visible_checklist(
                checklist,
                show_full=show_full_checklist,
            )
            if checklist_view.empty and not show_full_checklist:
                st.success("No Account Health checklist exceptions for this loaded snapshot.")
            else:
                render_priority_dataframe(
                    checklist_view,
                    title=checklist_title,
                    priority_columns=[
                        "SEVERITY", "STATUS", "CHECK", "EVIDENCE", "OWNER",
                        "ESCALATION_TARGET", "ROUTE", "ENVIRONMENT_SCOPE",
                        "DATABASE_CONTEXT", "SCOPE_CONFIDENCE", "QUEUE_READINESS",
                        "QUEUE_BLOCKERS", "APPROVAL_REQUIRED", "RECOVERY_SLA_TARGET_HOURS",
                        "NEXT_ACTION", "PROOF_REQUIRED",
                    ],
                    sort_by=["SEVERITY", "CHECK"],
                    ascending=[True, True],
                    raw_label=checklist_raw_label,
                    height=300,
                    max_rows=12,
                )
        elif account_detail == "Gates":
            render_priority_dataframe(
                account_operator_gates,
                title="Account Health operator next-move gates",
                priority_columns=["GATE", "STATE", "COUNT", "PROOF_REQUIRED", "NEXT_ACTION"],
                sort_by=["GATE_RANK", "COUNT"],
                ascending=[True, False],
                raw_label="All Account Health operator gates",
                height=240,
                max_rows=5,
            )
        elif account_detail == "Interventions" and not account_intervention_matrix.empty:
            render_priority_dataframe(
                account_intervention_matrix,
                title="Account Health DBA intervention matrix",
                priority_columns=[
                    "DBA_PRIORITY", "INTERVENTION_STATE", "SURFACE", "SEVERITY", "ROUTE", "OWNER",
                    "CONTROL_STATE", "QUEUE_READINESS", "CLOSURE_READINESS",
                    "SCOPE_CONFIDENCE", "COUNT", "NEXT_DECISION", "PROOF_REQUIRED",
                ],
                sort_by=["DBA_PRIORITY", "COUNT", "SURFACE"],
                ascending=[True, False, True],
                raw_label="All Account Health DBA intervention rows",
                height=280,
                max_rows=8,
            )
        elif account_detail == "Controls" and not account_control_board.empty:
            render_priority_dataframe(
                account_control_board,
                title="Account Health control board",
                priority_columns=[
                    "CONTROL_STATE", "CHECK_NAME", "STATUS", "SEVERITY", "ROUTE",
                    "OWNER", "ENVIRONMENT_SCOPE", "DATABASE_CONTEXT", "SCOPE_CONFIDENCE",
                    "QUEUE_READINESS", "QUEUE_BLOCKERS", "OPEN_ACTIONS", "OVERDUE_OPEN",
                    "FIXED_WITHOUT_VERIFICATION", "RECOVERY_RISK_ROWS", "VERIFIED_CLOSURES",
                    "ISSUE_SNAPSHOTS", "RECOVERY_SLA_TARGET_HOURS", "NEXT_CONTROL_ACTION",
                ],
                sort_by=["CONTROL_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "OPEN_ACTIONS"],
                ascending=[True, False, False, False],
                raw_label="All Account Health control rows",
                height=320,
                max_rows=12,
            )
        elif account_detail == "Operability":
            if (
                operability_fact is not None
                and not _account_health_meta_matches(
                    st.session_state.get("account_health_operability_fact_meta"),
                    _account_health_scope_meta(company, environment, window="30d"),
                )
            ):
                st.info("Loaded Account Health control summary is stale for the active scope. Reload before acting.")
            elif operability_fact is not None and not operability_fact.empty:
                blocked_states = operability_fact["CONTROL_STATE"].astype(str).str.contains(
                    "Blocked|Overdue|Required|Review", case=False, na=False
                )
                render_shell_snapshot((
                    ("Rows", f"{len(operability_fact):,}"),
                    ("Blocked Review", f"{int(blocked_states.sum()):,}"),
                    ("Overdue", f"{int(operability_fact.get('OVERDUE_OPEN', pd.Series(dtype=int)).sum()):,}"),
                    ("Verified", f"{int(operability_fact.get('VERIFIED_CLOSURES', pd.Series(dtype=int)).sum()):,}"),
                ))
                render_priority_dataframe(
                    operability_fact,
                    title="Account Health blockers",
                    priority_columns=[
                        "SNAPSHOT_DATE", "CONTROL_STATE", "CONTROL_SOURCE", "CHECK_NAME",
                        "ROUTE", "SEVERITY", "ENVIRONMENT", "HEALTH_SCORE", "ISSUE_ROWS",
                        "ROUTE_BLOCKER_ROWS", "QUEUE_REQUIRED_ROWS", "ACCESS_HYGIENE_ROWS",
                        "FAILED_LOGIN_ROWS", "PRIVILEGED_GRANT_ROWS", "OPEN_ACTIONS",
                        "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "VERIFIED_CLOSURES",
                        "OWNER_APPROVAL_GAP_ROWS", "RECOVERY_RISK_ROWS", "NEXT_CONTROL_ACTION",
                    ],
                    sort_by=["CONTROL_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "ISSUE_ROWS"],
                    ascending=[True, False, False, False],
                    raw_label="All Account Health control rows",
                    height=320,
                    max_rows=12,
                )
                with st.expander("Account Health Control Status", expanded=False):
                    render_shell_snapshot((
                        ("Control summary", "Ready"),
                        ("Routed actions", "Review"),
                        ("Telemetry", "Required"),
                        ("Execution", "Runbook only"),
                    ))
            elif st.session_state.get("account_health_operability_fact_error"):
                st.caption("Account Health control summary is not available yet. Ask the DBA on-call to enable the fast blocker surface.")
            else:
                st.caption("Load the control summary when you need blockers, routes, and telemetry status.")
        elif account_detail in {"Interventions", "Controls"}:
            st.success(f"No {account_detail.lower()} rows for the loaded scope.")
        if account_detail == "Checklist":
            q1, q2, q3 = st.columns([1, 1, 3])
            with q1:
                if st.button(
                    "Queue Checklist Issues",
                    key="account_health_queue_checklist",
                    width="stretch",
                    disabled=actionable_checklist.empty,
                ):
                    action_session = _account_health_action_session("queue Account Health checklist issues")
                    if action_session is not None:
                        _queue_account_health_checklist(
                            action_session,
                            checklist,
                            company=company,
                            environment=get_active_environment(),
                        )
            with q2:
                if st.button(
                    "Save Checklist Snapshot",
                    key="account_health_save_checklist_snapshot",
                    width="stretch",
                ):
                    action_session = _account_health_action_session("save Account Health checklist snapshot")
                    if action_session is not None:
                        _save_account_health_checklist_snapshot(
                            action_session,
                            checklist,
                            company=company,
                            environment=get_active_environment(),
                            health_score=health_score,
                            detail_source=hd.get("_account_health_detail_source", ""),
                        )
            with q3:
                if actionable_checklist.empty:
                    st.caption("Daily checklist is clean for this snapshot; no queue item is needed. Save the snapshot for trend tracking.")
                else:
                    ready_count = int((actionable_checklist.get("QUEUE_READINESS", pd.Series(dtype=str)) == "Ready to Queue").sum())
                    st.caption(
                        f"{len(actionable_checklist):,} checklist issue(s) will be saved with route, reviewer, "
                        f"telemetry basis, and scope context. {ready_count:,} are route-ready without blockers."
                    )
        _render_account_health_access_hygiene(
            company=company,
            environment=get_active_environment(),
        )
        with st.expander("Daily DBA Checklist Trend", expanded=False):
            trend_days = day_window_selectbox(
                "Checklist trend window",
                key="account_health_checklist_trend_days",
                default=30,
            )
            if st.button("Load Checklist Trend", key="account_health_load_checklist_trend"):
                try:
                    trend_sql = _account_health_checklist_history_sql(
                        trend_days,
                        company=company,
                        environment=get_active_environment(),
                    )
                    st.session_state["account_health_checklist_trend"] = run_query(
                        trend_sql,
                        ttl_key=f"account_health_checklist_trend_{company}_{get_active_environment()}_{trend_days}",
                        tier="standard",
                        section="Account Health",
                    )
                    st.session_state["account_health_checklist_trend_sql"] = trend_sql
                    st.session_state["account_health_checklist_trend_meta"] = _account_health_scope_meta(
                        company, environment, window=f"{int(trend_days)}d"
                    )
                except Exception as exc:
                    st.warning(f"Checklist trend unavailable: {format_snowflake_error(exc)}")
            trend = st.session_state.get("account_health_checklist_trend")
            if (
                trend is not None
                and not _account_health_meta_matches(
                    st.session_state.get("account_health_checklist_trend_meta"),
                    _account_health_scope_meta(company, environment, window=f"{int(trend_days)}d"),
                )
            ):
                st.info("Loaded checklist trend is stale for the active scope. Reload before acting.")
            elif trend is not None and not trend.empty:
                render_priority_dataframe(
                    trend,
                    title="Checklist issues by recurring snapshot",
                    priority_columns=[
                        "CHECK_NAME", "ISSUE_SNAPSHOTS", "SNAPSHOT_ROWS", "LAST_STATUS",
                        "LAST_SEVERITY", "OWNER", "ESCALATION_TARGET", "ROUTE", "AVG_HEALTH_SCORE",
                        "QUEUE_READINESS", "QUEUE_BLOCKERS", "SCOPE_CONFIDENCE",
                        "CONTROL_READINESS", "CONTROL_BLOCKER_SNAPSHOTS", "NEXT_CONTROL_ACTION",
                    ],
                    sort_by=["ISSUE_SNAPSHOTS", "LAST_SNAPSHOT_TS"],
                    ascending=[False, False],
                    raw_label="All checklist trend rows",
                    height=260,
                )
            elif trend is not None:
                st.info("No checklist history rows found for the selected scope.")
        with st.expander("Daily DBA Closure Analytics", expanded=False):
            st.caption(
                "Uses Account Health action-queue rows to show whether checklist issues are still open, "
                "overdue, or waiting for telemetry to confirm closure."
            )
            closure_days = day_window_selectbox(
                "Closure analytics window",
                key="account_health_closure_days",
                default=30,
            )
            if st.button("Load Closure Analytics", key="account_health_load_closure_analytics"):
                try:
                    closure_sql = _account_health_closure_analytics_sql(
                        closure_days,
                        company=company,
                        environment=get_active_environment(),
                    )
                    st.session_state["account_health_closure_analytics_sql"] = closure_sql
                    st.session_state["account_health_closure_analytics"] = run_query(
                        closure_sql,
                        ttl_key=f"account_health_closure_analytics_{company}_{get_active_environment()}_{closure_days}",
                        tier="standard",
                        section="Account Health",
                    )
                    st.session_state["account_health_closure_analytics_meta"] = _account_health_scope_meta(
                        company, environment, window=f"{int(closure_days)}d"
                    )
                except Exception as exc:
                    st.session_state["account_health_closure_analytics"] = pd.DataFrame()
                    st.warning(f"Closure analytics unavailable: {format_snowflake_error(exc)}")
                    st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry.")
            closure = st.session_state.get("account_health_closure_analytics")
            if (
                closure is not None
                and not _account_health_meta_matches(
                    st.session_state.get("account_health_closure_analytics_meta"),
                    _account_health_scope_meta(company, environment, window=f"{int(closure_days)}d"),
                )
            ):
                st.info("Loaded closure analytics are stale for the active scope. Reload before acting.")
            elif closure is not None and not closure.empty:
                render_priority_dataframe(
                    closure,
                    title="Checklist closure status gaps",
                    priority_columns=[
                        "CHECK_NAME", "CLOSURE_READINESS", "OWNER", "APPROVER",
                        "TOTAL_ACTIONS", "OPEN_ACTIONS", "OVERDUE_OPEN",
                        "VERIFIED_CLOSURES", "FIXED_WITHOUT_VERIFICATION",
                        "OWNER_GAP_ROWS", "TICKET_GAP_ROWS", "APPROVER_GAP_ROWS",
                        "OWNER_APPROVAL_GAP_ROWS", "VERIFICATION_QUERY_GAP_ROWS",
                        "RECOVERY_RISK_ROWS", "NEXT_DUE_DATE", "LAST_STATUS", "NEXT_ACTION",
                    ],
                    sort_by=["CLOSURE_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "OPEN_ACTIONS"],
                    ascending=[True, False, False, False],
                    raw_label="All closure analytics rows",
                    height=300,
                )
                with st.expander("Closure Analytics Status", expanded=False):
                    render_shell_snapshot((
                        ("Closure status", "Ready"),
                        ("Telemetry", "Review"),
                        ("Telemetry", "Required"),
                        ("Execution", "Runbook only"),
                    ))
            elif closure is not None:
                st.info("No Account Health checklist action-queue rows found for the selected scope.")
        st.divider()
        show_loaded_time("account_health")

        st.markdown("**Quick Nav**")
        qnav_cols = st.columns(4)

        def _jump(tgt, workflow=None):
            apply_navigation_state(tgt)
            if workflow:
                st.session_state["workload_operations_workflow"] = workflow

        for idx, (lbl, tgt, workflow) in enumerate([
            ("Live", "Workload Operations", "Performance & Contention"),
            ("Query", "Workload Operations", "Query Investigation"),
            ("Cost", "Cost & Contract", None),
            ("DBA", "Security Monitoring", None),
        ]):
            with qnav_cols[idx]:
                st.button(lbl, key=f"jump_{lbl}", on_click=_jump, args=(tgt, workflow), width="stretch")

        secondary_sig = f"{filter_sig}|{environment}"
        secondary_loaded = st.session_state.get("_account_health_secondary_sig") == secondary_sig
        if st.button("Load Secondary Details", key="account_health_load_secondary_evidence"):
            st.session_state["_account_health_secondary_sig"] = secondary_sig
            secondary_loaded = True
        if not secondary_loaded:
            st.caption(
                "Secondary cost slices, monitoring-cost detail, and warehouse-pressure charts stay unloaded "
                "until they are needed for the current investigation."
            )
            return

        st.divider()
        st.markdown("**Executive Landing Signals**")
        e1, e2, e3, e4 = st.columns(4)

        with e1:
            st.markdown("**Top 5 cost drivers today**")
            cost_df = hd.get("cost_drivers", pd.DataFrame())
            if cost_df is not None and not cost_df.empty:
                cost_df["EST_COST"] = cost_df["TOTAL_CREDITS"].apply(
                    lambda x: credits_to_dollars(x, credit_price)
                )
                render_priority_dataframe(
                    cost_df,
                    title="Top cost drivers today",
                    priority_columns=[
                        "WAREHOUSE_NAME", "USER_NAME", "TOTAL_CREDITS",
                        "EST_COST", "QUERY_COUNT", "AVG_ELAPSED_SEC",
                    ],
                    sort_by=["TOTAL_CREDITS", "EST_COST"],
                    ascending=[False, False],
                    raw_label="All daily cost drivers",
                    height=220,
                )
                if "USER_NAME" in cost_df.columns:
                    sel_user = st.selectbox(
                        "-> Drill into user", ["(none)"] + cost_df["USER_NAME"].dropna().tolist(),
                        key="ah_drill_user", label_visibility="collapsed",
                    )
                    if sel_user and sel_user != "(none)":
                        if st.button(f"Open Cost & Contract for {sel_user}", key="ah_drill_user_btn"):
                            _drill_to(
                                "Cost & Contract",
                                user_filter=sel_user,
                                workflow_key="cost_contract_workflow",
                                workflow="Cost by User / Role",
                            )
            else:
                st.info("No cost driver data yet.")

        with e2:
            st.markdown("**Top 5 failed jobs/tasks**")
            failed_df = hd.get("failed_jobs", pd.DataFrame())
            if failed_df is not None and not failed_df.empty:
                render_priority_dataframe(
                    failed_df,
                    title="Failed jobs and tasks",
                    priority_columns=[
                        "NAME", "TASK_NAME", "ROOT_TASK_NAME", "STATE",
                        "QUERY_ID", "ERROR_MESSAGE", "SCHEDULED_TIME",
                    ],
                    sort_by=["SCHEDULED_TIME", "COMPLETED_TIME"],
                    ascending=[False, False],
                    raw_label="All failed jobs/tasks",
                    height=220,
                )
                if st.button("Task Management", key="ah_drill_tasks"):
                    st.session_state["workload_operations_workflow"] = "Pipeline & Task Health"
                    st.session_state["workload_operations_pipeline_focus"] = "Failed Tasks"
                    _drill_to("Workload Operations")
            else:
                st.success("No failed tasks in the last 24h.")

        with e3:
            st.markdown("**What changed since yesterday**")
            change_df = hd.get("what_changed", pd.DataFrame())
            if change_df is not None and not change_df.empty:
                row = change_df.iloc[0]
                render_shell_snapshot(
                    (
                        ("Queries", f"{safe_int(row.get('QUERY_DELTA', 0)):+,}"),
                        ("Credits", f"{safe_float(row.get('CREDIT_DELTA', 0)):+,.2f}"),
                        ("Failures", f"{safe_int(row.get('FAILURE_DELTA', 0)):+,}"),
                    )
                )
            else:
                st.info("Change summary unavailable.")

        with e4:
            st.markdown("**Recommended next action**")
            st.info("Use Cost & Contract for optimization actions, action queue triage, and Teams-ready alerting.")
            if st.button("Open Cost & Contract", key="ah_open_recommendations"):
                _drill_to(
                    "Cost & Contract",
                    workflow_key="cost_contract_workflow",
                    workflow="Cost Recommendations",
                )

        if exceptions_only:
            return

        st.divider()
        st.markdown("**Warehouse Pressure (last 1h)**")
        try:
            if control_mart_used:
                df_wp = run_query(
                    build_mart_control_room_warehouse_pressure_sql(1, company),
                    ttl_key=f"account_health_wh_pressure_mart_{company}",
                    tier="historical",
                    section="Account Health",
                )
                if df_wp is not None and not df_wp.empty:
                    df_wp = df_wp.rename(columns={
                        "TOTAL_QUERIES": "QUERIES",
                        "QUEUED_QUERIES": "QUEUED",
                    })
            else:
                qh = _query_history_capabilities()
                pressure_wh_size_expr = qh["pressure_wh_size_expr"]
                queued_count_expr_plain = qh["queued_count_expr_plain"]
                df_wp = run_query(f"""
                    SELECT warehouse_name, {pressure_wh_size_expr} AS warehouse_size, COUNT(*) AS queries,
                           {queued_count_expr_plain} AS queued
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('hours',-1,CURRENT_TIMESTAMP())
                      AND warehouse_name IS NOT NULL
                      {wh_filter_m}
                    GROUP BY warehouse_name ORDER BY queries DESC LIMIT 8
                """, ttl_key=f"account_health_wh_pressure_live_{company}", tier="recent", section="Account Health")
            if not df_wp.empty:
                top_wh = df_wp.sort_values(["QUEUED","QUERIES"], ascending=False).iloc[0]
                render_shell_snapshot(
                    (
                        ("Top pressure", top_wh["WAREHOUSE_NAME"]),
                        ("Queue / queries", f"{int(top_wh['QUEUED'])} queued / {int(top_wh['QUERIES'])} queries"),
                    )
                )
                render_drillable_bar_chart(
                    df_wp, dimension="WAREHOUSE_NAME", measure="QUERIES",
                    key="ah_warehouse_pressure", title="Warehouse pressure drill-down",
                    drilldown_column="warehouse_name", lookback_hours=24, top_n=8,
                )
                st.markdown("**Jump to Cost & Contract:**")
                wh_cols = st.columns(min(len(df_wp), 4))
                for idx, wh_row in df_wp.head(4).iterrows():
                    wh_name = wh_row["WAREHOUSE_NAME"]
                    with wh_cols[idx % 4]:
                        if st.button(wh_name, key=f"ah_wh_drill_{wh_name}"):
                            _drill_to("Cost & Contract", wh_filter=wh_name)
        except Exception as e:
            st.caption(f"Warehouse pressure unavailable: {format_snowflake_error(e)}")
