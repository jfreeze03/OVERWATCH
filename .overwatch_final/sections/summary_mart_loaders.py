"""Bounded loaders for compact section summary marts.

These helpers are intentionally separate from first-paint packet loading. They
are used after a user navigates into a section or explicitly requests a compact
summary, and every query is scoped to the section-summary boundary.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from utils.performance import SUMMARY_AUTOLOAD_QUERY_BUDGET, query_budget_context
from utils.query import run_query


DEFAULT_SUMMARY_LIMIT = 200
SUMMARY_TTL_SECONDS = 300


def _sql_literal(value: Any) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def _limit(value: int | None) -> int:
    try:
        parsed = int(value if value is not None else DEFAULT_SUMMARY_LIMIT)
    except (TypeError, ValueError):
        parsed = DEFAULT_SUMMARY_LIMIT
    return max(1, min(parsed, DEFAULT_SUMMARY_LIMIT))


def _summary_query(
    *,
    section: str,
    workflow: str,
    ttl_key: str,
    sql: str,
    limit: int | None = None,
) -> pd.DataFrame:
    max_rows = _limit(limit)
    with query_budget_context(
        "section_summary_autoload",
        section=section,
        workflow=workflow,
        budget=SUMMARY_AUTOLOAD_QUERY_BUDGET,
    ):
        return run_query(
            sql,
            ttl_key=ttl_key,
            use_cache=True,
            spinner_msg="Loading summary...",
            tier="section_summary",
            section=section,
            max_rows=max_rows,
            query_boundary="section_summary_autoload",
        )


@st.cache_data(ttl=SUMMARY_TTL_SECONDS, show_spinner=False)
def load_query_daily_summary(
    company: str,
    environment: str,
    window_days: int,
    *,
    limit: int = DEFAULT_SUMMARY_LIMIT,
) -> pd.DataFrame:
    sql = f"""
        SELECT
          COMPANY,
          ENVIRONMENT,
          WINDOW_START_DATE,
          WINDOW_END_DATE,
          QUERY_COUNT,
          FAILED_QUERY_COUNT,
          QUEUED_QUERY_COUNT,
          TOTAL_ELAPSED_MS,
          BYTES_SCANNED,
          CREDITS_ESTIMATE,
          TOP_WAREHOUSE_NAME,
          TOP_USER_NAME,
          UPDATED_AT
        FROM OVERWATCH_QUERY_DAILY_SUMMARY
        WHERE COMPANY = {_sql_literal(company)}
          AND ENVIRONMENT = {_sql_literal(environment)}
          AND WINDOW_END_DATE >= DATEADD('day', -{int(window_days)}, CURRENT_DATE())
        ORDER BY WINDOW_END_DATE DESC
        LIMIT {_limit(limit)}
    """
    return _summary_query(
        section="Workload Operations",
        workflow="Workload Overview",
        ttl_key=f"summary_mart_query_daily_{company}_{environment}_{window_days}",
        sql=sql,
        limit=limit,
    )


@st.cache_data(ttl=SUMMARY_TTL_SECONDS, show_spinner=False)
def load_warehouse_daily_credits(
    company: str,
    environment: str,
    window_days: int,
    *,
    limit: int = DEFAULT_SUMMARY_LIMIT,
) -> pd.DataFrame:
    sql = f"""
        SELECT
          COMPANY,
          ENVIRONMENT,
          USAGE_DATE,
          WAREHOUSE_NAME,
          CREDITS_USED,
          COST_USD,
          QUERY_COUNT,
          QUEUED_SECONDS,
          SPILL_BYTES,
          UPDATED_AT
        FROM OVERWATCH_WAREHOUSE_DAILY_CREDITS
        WHERE COMPANY = {_sql_literal(company)}
          AND ENVIRONMENT = {_sql_literal(environment)}
          AND USAGE_DATE >= DATEADD('day', -{int(window_days)}, CURRENT_DATE())
        ORDER BY USAGE_DATE DESC, CREDITS_USED DESC, WAREHOUSE_NAME
        LIMIT {_limit(limit)}
    """
    return _summary_query(
        section="Cost & Contract",
        workflow="Cost Overview",
        ttl_key=f"summary_mart_warehouse_credits_{company}_{environment}_{window_days}",
        sql=sql,
        limit=limit,
    )


@st.cache_data(ttl=SUMMARY_TTL_SECONDS, show_spinner=False)
def load_cortex_daily_usage(
    company: str,
    environment: str,
    window_days: int,
    *,
    limit: int = DEFAULT_SUMMARY_LIMIT,
) -> pd.DataFrame:
    sql = f"""
        SELECT
          COMPANY,
          ENVIRONMENT,
          USAGE_DATE,
          USER_NAME,
          USER_DISPLAY_NAME,
          USER_CHART_LABEL,
          SERVICE_TYPE,
          TOTAL_TOKENS,
          TOTAL_REQUESTS,
          TOTAL_CREDITS,
          COST_USD,
          TOKENS_PER_REQUEST,
          TOKENS_PER_DOLLAR,
          COST_PER_1K_TOKENS_USD,
          AI_CREDITS_PER_1K_TOKENS,
          UPDATED_AT
        FROM OVERWATCH_CORTEX_DAILY_USAGE
        WHERE COMPANY = {_sql_literal(company)}
          AND ENVIRONMENT = {_sql_literal(environment)}
          AND USAGE_DATE >= DATEADD('day', -{int(window_days)}, CURRENT_DATE())
        ORDER BY USAGE_DATE DESC, COST_USD DESC, USER_CHART_LABEL
        LIMIT {_limit(limit)}
    """
    return _summary_query(
        section="Cost & Contract",
        workflow="Cortex Efficiency",
        ttl_key=f"summary_mart_cortex_daily_{company}_{environment}_{window_days}",
        sql=sql,
        limit=limit,
    )


@st.cache_data(ttl=SUMMARY_TTL_SECONDS, show_spinner=False)
def load_user_display_dim(*, limit: int = DEFAULT_SUMMARY_LIMIT) -> pd.DataFrame:
    sql = f"""
        SELECT
          USER_NAME,
          USER_DISPLAY_NAME,
          USER_CHART_LABEL,
          LOGIN_NAME,
          DISPLAY_NAME,
          NAME,
          UPDATED_AT
        FROM OVERWATCH_USER_DISPLAY_DIM
        ORDER BY USER_CHART_LABEL, USER_NAME
        LIMIT {_limit(limit)}
    """
    return _summary_query(
        section="Shared User Display",
        workflow="Summary Label Dimension",
        ttl_key="summary_mart_user_display_dim",
        sql=sql,
        limit=limit,
    )


@st.cache_data(ttl=SUMMARY_TTL_SECONDS, show_spinner=False)
def load_login_security_daily(
    company: str,
    environment: str,
    window_days: int,
    *,
    limit: int = DEFAULT_SUMMARY_LIMIT,
) -> pd.DataFrame:
    sql = f"""
        SELECT
          COMPANY,
          ENVIRONMENT,
          EVENT_DATE,
          FAILED_LOGIN_COUNT,
          SUCCESS_LOGIN_COUNT,
          AFFECTED_USER_COUNT,
          MFA_GAP_USER_COUNT,
          SUSPICIOUS_IP_COUNT,
          UPDATED_AT
        FROM OVERWATCH_LOGIN_SECURITY_DAILY
        WHERE COMPANY = {_sql_literal(company)}
          AND ENVIRONMENT = {_sql_literal(environment)}
          AND EVENT_DATE >= DATEADD('day', -{int(window_days)}, CURRENT_DATE())
        ORDER BY EVENT_DATE DESC
        LIMIT {_limit(limit)}
    """
    return _summary_query(
        section="Security Monitoring",
        workflow="Security Overview",
        ttl_key=f"summary_mart_login_security_{company}_{environment}_{window_days}",
        sql=sql,
        limit=limit,
    )


@st.cache_data(ttl=SUMMARY_TTL_SECONDS, show_spinner=False)
def load_task_status_daily(
    company: str,
    environment: str,
    window_days: int,
    *,
    limit: int = DEFAULT_SUMMARY_LIMIT,
) -> pd.DataFrame:
    sql = f"""
        SELECT
          COMPANY,
          ENVIRONMENT,
          EVENT_DATE,
          FAILED_TASK_COUNT,
          FAILED_PROCEDURE_COUNT,
          SLA_BREACH_COUNT,
          QUEUED_RUN_COUNT,
          RECOVERY_ACTION_COUNT,
          UPDATED_AT
        FROM OVERWATCH_TASK_STATUS_DAILY
        WHERE COMPANY = {_sql_literal(company)}
          AND ENVIRONMENT = {_sql_literal(environment)}
          AND EVENT_DATE >= DATEADD('day', -{int(window_days)}, CURRENT_DATE())
        ORDER BY EVENT_DATE DESC
        LIMIT {_limit(limit)}
    """
    return _summary_query(
        section="DBA Control Room",
        workflow="Morning Cockpit",
        ttl_key=f"summary_mart_task_status_{company}_{environment}_{window_days}",
        sql=sql,
        limit=limit,
    )


@st.cache_data(ttl=SUMMARY_TTL_SECONDS, show_spinner=False)
def load_security_posture_daily(
    company: str,
    environment: str,
    window_days: int,
    *,
    limit: int = DEFAULT_SUMMARY_LIMIT,
) -> pd.DataFrame:
    sql = f"""
        SELECT
          COMPANY,
          ENVIRONMENT,
          EVENT_DATE,
          CRITICAL_FINDING_COUNT,
          HIGH_FINDING_COUNT,
          MEDIUM_FINDING_COUNT,
          CREDENTIAL_EXPIRATION_RISK_COUNT,
          EXPIRED_CREDENTIAL_COUNT,
          EXPIRING_30D_CREDENTIAL_COUNT,
          UPDATED_AT
        FROM OVERWATCH_SECURITY_POSTURE_DAILY
        WHERE COMPANY = {_sql_literal(company)}
          AND ENVIRONMENT = {_sql_literal(environment)}
          AND EVENT_DATE >= DATEADD('day', -{int(window_days)}, CURRENT_DATE())
        ORDER BY EVENT_DATE DESC
        LIMIT {_limit(limit)}
    """
    return _summary_query(
        section="Security Monitoring",
        workflow="Security Overview",
        ttl_key=f"summary_mart_security_posture_{company}_{environment}_{window_days}",
        sql=sql,
        limit=limit,
    )


@st.cache_data(ttl=SUMMARY_TTL_SECONDS, show_spinner=False)
def load_executive_packet_current(
    company: str,
    environment: str,
    window_days: int,
    *,
    limit: int = 20,
) -> pd.DataFrame:
    sql = f"""
        SELECT
          COMPANY,
          ENVIRONMENT,
          SECTION,
          WINDOW_DAYS,
          SUMMARY_JSON,
          TOP_FINDINGS_JSON,
          TOP_ACTIONS_JSON,
          UPDATED_AT
        FROM OVERWATCH_EXECUTIVE_PACKET_CURRENT
        WHERE COMPANY = {_sql_literal(company)}
          AND ENVIRONMENT = {_sql_literal(environment)}
          AND WINDOW_DAYS = {int(window_days)}
        ORDER BY UPDATED_AT DESC, SECTION
        LIMIT {_limit(limit)}
    """
    return _summary_query(
        section="Executive Landing",
        workflow="Overview",
        ttl_key=f"summary_mart_executive_packet_{company}_{environment}_{window_days}",
        sql=sql,
        limit=limit,
    )


__all__ = [
    "load_cortex_daily_usage",
    "load_executive_packet_current",
    "load_login_security_daily",
    "load_query_daily_summary",
    "load_security_posture_daily",
    "load_task_status_daily",
    "load_user_display_dim",
    "load_warehouse_daily_credits",
]
