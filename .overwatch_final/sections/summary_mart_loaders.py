"""Bounded loaders for compact section summary marts.

These helpers are intentionally separate from first-paint packet loading. They
are used after a user navigates into a section or explicitly requests a compact
summary, and every query is scoped to the section-summary boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import re
from typing import Any

import pandas as pd
import streamlit as st

from runtime_state import (
    PENDING_AUTOLOAD_SECTION,
    PENDING_AUTOLOAD_STARTED_AT,
    get_state,
    pop_state,
    set_state,
)
from utils.company_filter import get_environment_db_patterns
from utils.data_state import DataState, data_state_label
from utils.performance import SUMMARY_AUTOLOAD_QUERY_BUDGET, query_budget_context
from utils.query import run_query


DEFAULT_SUMMARY_LIMIT = 200
SUMMARY_TTL_SECONDS = 300


@dataclass(frozen=True)
class SummaryResult:
    data: pd.DataFrame
    state: DataState
    source_object: str
    snapshot_ts: str | None
    freshness_minutes: float | None
    row_count: int
    safe_error: str
    is_fallback: bool


def _sql_literal(value: Any) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def _limit(value: int | None) -> int:
    try:
        parsed = int(value if value is not None else DEFAULT_SUMMARY_LIMIT)
    except (TypeError, ValueError):
        parsed = DEFAULT_SUMMARY_LIMIT
    return max(1, min(parsed, DEFAULT_SUMMARY_LIMIT))


def _source_object_from_sql(sql: str) -> str:
    match = re.search(r"\bFROM\s+([A-Z0-9_.$]+)", str(sql or ""), flags=re.IGNORECASE)
    if not match:
        return "summary_mart"
    return match.group(1).split(".")[-1].upper()


def _safe_summary_error(exc: BaseException | None) -> str:
    if exc is None:
        return ""
    text = str(exc or "").lower()
    if "does not exist" in text or "not exist" in text or "invalid identifier" in text:
        return "Required source object is missing or not configured."
    if "connection" in text or "session" in text or "auth" in text:
        return "Snowflake connection is unavailable."
    if "permission" in text or "access" in text:
        return "This summary query failed. Review Setup Health for safe details."
    return "This summary query failed. Review Setup Health for safe details."


class _SummaryAutoloadMarker:
    def __init__(self, section: str) -> None:
        self.section = section
        self.previous_section: Any = None
        self.previous_started_at: Any = None

    def __enter__(self) -> None:
        self.previous_section = get_state(PENDING_AUTOLOAD_SECTION)
        self.previous_started_at = get_state(PENDING_AUTOLOAD_STARTED_AT)
        set_state(PENDING_AUTOLOAD_SECTION, self.section)
        set_state(PENDING_AUTOLOAD_STARTED_AT, datetime.now(UTC).isoformat(timespec="seconds"))

    def __exit__(self, *_exc: object) -> None:
        if self.previous_section is None:
            pop_state(PENDING_AUTOLOAD_SECTION, None)
        else:
            set_state(PENDING_AUTOLOAD_SECTION, self.previous_section)
        if self.previous_started_at is None:
            pop_state(PENDING_AUTOLOAD_STARTED_AT, None)
        else:
            set_state(PENDING_AUTOLOAD_STARTED_AT, self.previous_started_at)


def _state_from_exception(exc: BaseException) -> DataState:
    text = str(exc or "").lower()
    if "does not exist" in text or "not exist" in text or "invalid identifier" in text:
        return DataState.SETUP_REQUIRED
    if "connection" in text or "session" in text or "auth" in text:
        return DataState.CONNECTION_UNAVAILABLE
    return DataState.QUERY_FAILED


def _result_frame(result: SummaryResult, *, section: str, workflow: str, max_rows: int) -> pd.DataFrame:
    frame = result.data.copy()
    state = result.state
    status = data_state_label(state)
    frame.attrs.update(
        {
            "SECTION": section,
            "WORKFLOW": workflow,
            "SOURCE_STATUS": status,
            "SUMMARY_STATUS": status,
            "DATA_STATE": state.value,
            "FRESHNESS_TS": result.snapshot_ts or datetime.now(UTC).isoformat(timespec="seconds"),
            "SOURCE_FAMILY": "summary_mart",
            "SOURCE_OBJECT": result.source_object,
            "IS_FALLBACK": bool(result.is_fallback),
            "ROW_LIMIT": max_rows,
            "ROW_COUNT": result.row_count,
            "RAW_SQL_INCLUDED": False,
            "SAFE_ERROR": result.safe_error,
        }
    )
    return frame


def _summary_result(
    *,
    section: str,
    workflow: str,
    ttl_key: str,
    sql: str,
    limit: int | None = None,
) -> SummaryResult:
    max_rows = _limit(limit)
    source_object = _source_object_from_sql(sql)
    with query_budget_context(
        "section_summary_autoload",
        section=section,
        workflow=workflow,
        budget=SUMMARY_AUTOLOAD_QUERY_BUDGET,
    ):
        try:
            with _SummaryAutoloadMarker(section):
                result = run_query(
                    sql,
                    ttl_key=ttl_key,
                    use_cache=True,
                    spinner_msg="",
                    tier="section_summary",
                    section=section,
                    max_rows=max_rows,
                    query_boundary="section_summary_autoload",
                )
            if isinstance(result, pd.DataFrame) and not result.empty:
                frame = result.head(max_rows).copy()
                return SummaryResult(
                    data=frame,
                    state=DataState.LOADED_CURRENT,
                    source_object=source_object,
                    snapshot_ts=datetime.now(UTC).isoformat(timespec="seconds"),
                    freshness_minutes=None,
                    row_count=len(frame),
                    safe_error="",
                    is_fallback=False,
                )
            return SummaryResult(
                data=pd.DataFrame(),
                state=DataState.REFRESH_REQUIRED,
                source_object=source_object,
                snapshot_ts=datetime.now(UTC).isoformat(timespec="seconds"),
                freshness_minutes=None,
                row_count=0,
                safe_error="",
                is_fallback=True,
            )
        except Exception as exc:
            return SummaryResult(
                data=pd.DataFrame(),
                state=_state_from_exception(exc),
                source_object=source_object,
                snapshot_ts=datetime.now(UTC).isoformat(timespec="seconds"),
                freshness_minutes=None,
                row_count=0,
                safe_error=_safe_summary_error(exc),
                is_fallback=True,
            )


def _summary_query(
    *,
    section: str,
    workflow: str,
    ttl_key: str,
    sql: str,
    limit: int | None = None,
) -> pd.DataFrame:
    max_rows = _limit(limit)
    result = _summary_result(
        section=section,
        workflow=workflow,
        ttl_key=ttl_key,
        sql=sql,
        limit=max_rows,
    )
    return _result_frame(result, section=section, workflow=workflow, max_rows=max_rows)


def _safe_window_days(value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 7
    return max(1, min(parsed, 365))


def _environment_summary_filter(column: str, environment: str, company: str) -> str:
    env = str(environment or "").strip().upper()
    if not env or env == "ALL":
        return ""
    patterns = tuple(str(value).upper() for value in get_environment_db_patterns(env, company))
    literals = tuple(dict.fromkeys(value for value in (env, *patterns) if value))
    if not literals:
        return ""
    values = ", ".join(_sql_literal(value) for value in literals)
    return f"AND UPPER(COALESCE({column}, '')) IN ({values})"


@st.cache_data(ttl=SUMMARY_TTL_SECONDS, show_spinner=False)
def load_query_daily_summary(
    company: str,
    environment: str,
    window_days: int,
    *,
    limit: int = DEFAULT_SUMMARY_LIMIT,
) -> pd.DataFrame:
    days = _safe_window_days(window_days)
    env_filter = _environment_summary_filter("ENVIRONMENT", environment, company)
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
        FROM V_QUERY_DAILY_SUMMARY
        WHERE COMPANY = {_sql_literal(company)}
          {env_filter}
          AND WINDOW_END_DATE >= DATEADD('day', -{days}, CURRENT_DATE())
        ORDER BY WINDOW_END_DATE DESC
        LIMIT {_limit(limit)}
    """
    return _summary_query(
        section="Workload Operations",
        workflow="Workload Overview",
        ttl_key=f"summary_mart_query_daily_{company}_{environment}_{days}",
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
    days = _safe_window_days(window_days)
    env_filter = _environment_summary_filter("ENVIRONMENT", environment, company)
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
        FROM V_WAREHOUSE_DAILY_CREDITS
        WHERE COMPANY = {_sql_literal(company)}
          {env_filter}
          AND USAGE_DATE >= DATEADD('day', -{days}, CURRENT_DATE())
        ORDER BY USAGE_DATE DESC, CREDITS_USED DESC, WAREHOUSE_NAME
        LIMIT {_limit(limit)}
    """
    return _summary_query(
        section="Cost & Contract",
        workflow="Cost Overview",
        ttl_key=f"summary_mart_warehouse_credits_{company}_{environment}_{days}",
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
    days = _safe_window_days(window_days)
    env_filter = _environment_summary_filter("ENVIRONMENT", environment, company)
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
        FROM V_CORTEX_DAILY_USAGE
        WHERE COMPANY = {_sql_literal(company)}
          {env_filter}
          AND USAGE_DATE >= DATEADD('day', -{days}, CURRENT_DATE())
        ORDER BY USAGE_DATE DESC, COST_USD DESC, USER_CHART_LABEL
        LIMIT {_limit(limit)}
    """
    return _summary_query(
        section="Cost & Contract",
        workflow="Cortex Efficiency",
        ttl_key=f"summary_mart_cortex_daily_{company}_{environment}_{days}",
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
        FROM V_USER_DISPLAY_DIM
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
    days = _safe_window_days(window_days)
    env_filter = _environment_summary_filter("ENVIRONMENT", environment, company)
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
        FROM V_LOGIN_SECURITY_DAILY
        WHERE COMPANY = {_sql_literal(company)}
          {env_filter}
          AND EVENT_DATE >= DATEADD('day', -{days}, CURRENT_DATE())
        ORDER BY EVENT_DATE DESC
        LIMIT {_limit(limit)}
    """
    return _summary_query(
        section="Security Monitoring",
        workflow="Security Overview",
        ttl_key=f"summary_mart_login_security_{company}_{environment}_{days}",
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
    days = _safe_window_days(window_days)
    env_filter = _environment_summary_filter("ENVIRONMENT", environment, company)
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
        FROM V_TASK_STATUS_DAILY
        WHERE COMPANY = {_sql_literal(company)}
          {env_filter}
          AND EVENT_DATE >= DATEADD('day', -{days}, CURRENT_DATE())
        ORDER BY EVENT_DATE DESC
        LIMIT {_limit(limit)}
    """
    return _summary_query(
        section="DBA Control Room",
        workflow="Morning Cockpit",
        ttl_key=f"summary_mart_task_status_{company}_{environment}_{days}",
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
    days = _safe_window_days(window_days)
    env_filter = _environment_summary_filter("ENVIRONMENT", environment, company)
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
        FROM V_SECURITY_POSTURE_DAILY
        WHERE COMPANY = {_sql_literal(company)}
          {env_filter}
          AND EVENT_DATE >= DATEADD('day', -{days}, CURRENT_DATE())
        ORDER BY EVENT_DATE DESC
        LIMIT {_limit(limit)}
    """
    return _summary_query(
        section="Security Monitoring",
        workflow="Security Overview",
        ttl_key=f"summary_mart_security_posture_{company}_{environment}_{days}",
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
    days = _safe_window_days(window_days)
    env_filter = _environment_summary_filter("ENVIRONMENT", environment, company)
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
        FROM V_EXECUTIVE_PACKET_CURRENT
        WHERE COMPANY = {_sql_literal(company)}
          {env_filter}
          AND WINDOW_DAYS = {days}
        ORDER BY UPDATED_AT DESC, SECTION
        LIMIT {_limit(limit)}
    """
    return _summary_query(
        section="Executive Landing",
        workflow="Overview",
        ttl_key=f"summary_mart_executive_packet_{company}_{environment}_{days}",
        sql=sql,
        limit=limit,
    )


__all__ = [
    "SummaryResult",
    "load_cortex_daily_usage",
    "load_executive_packet_current",
    "load_login_security_daily",
    "load_query_daily_summary",
    "load_security_posture_daily",
    "load_task_status_daily",
    "load_user_display_dim",
    "load_warehouse_daily_credits",
]
