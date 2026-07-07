"""Central Account Usage access facade.

Daily UI code should call these helpers instead of embedding source-history SQL
inside section modules. Summary helpers read app-facing secure views over compact
task-loaded marts. Detail helpers stay bounded and read recent mart tables only.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd
import streamlit as st

from utils.performance import EVIDENCE_CLICK_QUERY_BUDGET, SUMMARY_AUTOLOAD_QUERY_BUDGET, query_budget_context
from utils.query import run_query
from utils.sql_safe import sql_literal


DEFAULT_SUMMARY_LIMIT = 200
DEFAULT_DETAIL_LIMIT = 200
MAX_DETAIL_LIMIT = 500

SUMMARY_VIEW_SPECS: dict[str, dict[str, str]] = {
    "query_daily_summary": {
        "view": "V_QUERY_DAILY_SUMMARY",
        "section": "Workload Operations",
        "workflow": "Workload Overview",
        "date_column": "WINDOW_END_DATE",
        "columns": (
            "COMPANY, ENVIRONMENT, WINDOW_START_DATE, WINDOW_END_DATE, QUERY_COUNT, "
            "FAILED_QUERY_COUNT, QUEUED_QUERY_COUNT, TOTAL_ELAPSED_MS, BYTES_SCANNED, "
            "CREDITS_ESTIMATE, TOP_WAREHOUSE_NAME, TOP_USER_NAME, SOURCE_FAMILY, "
            "REFRESH_BOUNDARY, UPDATED_AT"
        ),
    },
    "warehouse_credits": {
        "view": "V_WAREHOUSE_DAILY_CREDITS",
        "section": "Cost & Contract",
        "workflow": "Cost Overview",
        "date_column": "USAGE_DATE",
        "columns": (
            "COMPANY, ENVIRONMENT, USAGE_DATE, WAREHOUSE_NAME, CREDITS_USED, COST_USD, "
            "QUERY_COUNT, QUEUED_SECONDS, SPILL_BYTES, SOURCE_FAMILY, REFRESH_BOUNDARY, UPDATED_AT"
        ),
    },
    "cortex_usage": {
        "view": "V_CORTEX_DAILY_USAGE",
        "section": "Cost & Contract",
        "workflow": "Cortex Efficiency",
        "date_column": "USAGE_DATE",
        "columns": (
            "COMPANY, ENVIRONMENT, USAGE_DATE, USER_NAME, USER_DISPLAY_NAME, USER_CHART_LABEL, "
            "SERVICE_TYPE, TOTAL_TOKENS, TOTAL_REQUESTS, TOTAL_CREDITS, COST_USD, "
            "TOKENS_PER_REQUEST, TOKENS_PER_DOLLAR, COST_PER_1K_TOKENS_USD, "
            "AI_CREDITS_PER_1K_TOKENS, SOURCE_FAMILY, REFRESH_BOUNDARY, UPDATED_AT"
        ),
    },
    "login_security": {
        "view": "V_LOGIN_SECURITY_DAILY",
        "section": "Security Monitoring",
        "workflow": "Security Overview",
        "date_column": "EVENT_DATE",
        "columns": (
            "COMPANY, ENVIRONMENT, EVENT_DATE, FAILED_LOGIN_COUNT, SUCCESS_LOGIN_COUNT, "
            "AFFECTED_USER_COUNT, MFA_GAP_USER_COUNT, SUSPICIOUS_IP_COUNT, SOURCE_FAMILY, "
            "REFRESH_BOUNDARY, UPDATED_AT"
        ),
    },
    "task_status": {
        "view": "V_TASK_STATUS_DAILY",
        "section": "Workload Operations",
        "workflow": "Task Health",
        "date_column": "EVENT_DATE",
        "columns": (
            "COMPANY, ENVIRONMENT, EVENT_DATE, FAILED_TASK_COUNT, FAILED_PROCEDURE_COUNT, "
            "SLA_BREACH_COUNT, QUEUED_RUN_COUNT, RECOVERY_ACTION_COUNT, SOURCE_FAMILY, "
            "REFRESH_BOUNDARY, UPDATED_AT"
        ),
    },
}


def _as_sql_date(value: date | datetime | str | None) -> str:
    if isinstance(value, datetime):
        return sql_literal(value.date().isoformat(), 40)
    if isinstance(value, date):
        return sql_literal(value.isoformat(), 40)
    text = str(value or "").strip()
    return sql_literal(text[:40], 40) if text else "NULL"


def _limit(value: int | None, *, maximum: int = DEFAULT_SUMMARY_LIMIT) -> int:
    try:
        parsed = int(value if value is not None else maximum)
    except (TypeError, ValueError):
        parsed = maximum
    return max(1, min(parsed, maximum))


def _optional_equals(column: str, value: object) -> str:
    text = str(value or "").strip()
    if not text or text.upper() in {"ALL", "ALL ENVIRONMENTS", "ALL SCOPED WAREHOUSES"}:
        return ""
    return f"\n  AND {column} = {sql_literal(text, 200)}"


def _date_range_filter(column: str, start_date: object, end_date: object) -> str:
    start = _as_sql_date(start_date)
    end = _as_sql_date(end_date)
    if start == "NULL" and end == "NULL":
        return ""
    clauses: list[str] = []
    if start != "NULL":
        clauses.append(f"{column} >= TO_DATE({start})")
    if end != "NULL":
        clauses.append(f"{column} <= TO_DATE({end})")
    return "\n  AND " + "\n  AND ".join(clauses)


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame()


def _run_summary(
    *,
    domain: str,
    sql: str,
    ttl_key: str,
    limit: int,
) -> pd.DataFrame:
    spec = SUMMARY_VIEW_SPECS[domain]
    with query_budget_context(
        "section_summary_autoload",
        section=spec["section"],
        workflow=spec["workflow"],
        budget=SUMMARY_AUTOLOAD_QUERY_BUDGET,
    ):
        try:
            result = run_query(
                sql,
                ttl_key=ttl_key,
                use_cache=True,
                spinner_msg="",
                tier="section_summary",
                section=spec["section"],
                max_rows=_limit(limit),
                query_boundary="section_summary_autoload",
            )
        except Exception:
            return _empty_frame()
    return result if isinstance(result, pd.DataFrame) else _empty_frame()


def _summary_sql(
    domain: str,
    company: str,
    environment: str,
    start_date: object,
    end_date: object,
    *,
    filters: str = "",
    order_by: str = "UPDATED_AT DESC",
    limit: int = DEFAULT_SUMMARY_LIMIT,
) -> str:
    spec = SUMMARY_VIEW_SPECS[domain]
    view = spec["view"]
    date_column = spec["date_column"]
    return f"""
SELECT {spec["columns"]}
FROM {view}
WHERE COMPANY = {sql_literal(company, 100)}
  AND ENVIRONMENT = {sql_literal(environment, 100)}
  {_date_range_filter(date_column, start_date, end_date)}
  {filters}
ORDER BY {order_by}
LIMIT {_limit(limit)}
"""


def get_query_daily_summary(
    company: str,
    environment: str,
    start_date: object,
    end_date: object,
    warehouse: str | None = None,
    user: str | None = None,
    role: str | None = None,
    database: str | None = None,
    schema: str | None = None,
    *,
    limit: int = DEFAULT_SUMMARY_LIMIT,
) -> pd.DataFrame:
    filters = "".join(
        (
            _optional_equals("TOP_WAREHOUSE_NAME", warehouse),
            _optional_equals("TOP_USER_NAME", user),
        )
    )
    sql = _summary_sql(
        "query_daily_summary",
        company,
        environment,
        start_date,
        end_date,
        filters=filters,
        order_by="WINDOW_END_DATE DESC, QUERY_COUNT DESC",
        limit=limit,
    )
    return _run_summary(
        domain="query_daily_summary",
        sql=sql,
        ttl_key=f"v_query_daily_summary_{company}_{environment}_{start_date}_{end_date}_{warehouse}_{user}_{role}_{database}_{schema}",
        limit=limit,
    )


def get_warehouse_credits(
    company: str,
    environment: str,
    start_date: object,
    end_date: object,
    warehouse: str | None = None,
    *,
    limit: int = DEFAULT_SUMMARY_LIMIT,
) -> pd.DataFrame:
    sql = _summary_sql(
        "warehouse_credits",
        company,
        environment,
        start_date,
        end_date,
        filters=_optional_equals("WAREHOUSE_NAME", warehouse),
        order_by="USAGE_DATE DESC, CREDITS_USED DESC, WAREHOUSE_NAME",
        limit=limit,
    )
    return _run_summary(
        domain="warehouse_credits",
        sql=sql,
        ttl_key=f"v_warehouse_credits_{company}_{environment}_{start_date}_{end_date}_{warehouse}",
        limit=limit,
    )


def get_cortex_usage(
    company: str,
    environment: str,
    start_date: object,
    end_date: object,
    user: str | None = None,
    *,
    limit: int = DEFAULT_SUMMARY_LIMIT,
) -> pd.DataFrame:
    sql = _summary_sql(
        "cortex_usage",
        company,
        environment,
        start_date,
        end_date,
        filters=_optional_equals("USER_NAME", user),
        order_by="USAGE_DATE DESC, COST_USD DESC, USER_CHART_LABEL",
        limit=limit,
    )
    return _run_summary(
        domain="cortex_usage",
        sql=sql,
        ttl_key=f"v_cortex_usage_{company}_{environment}_{start_date}_{end_date}_{user}",
        limit=limit,
    )


def get_login_security(
    company: str,
    environment: str,
    start_date: object,
    end_date: object,
    user: str | None = None,
    *,
    limit: int = DEFAULT_SUMMARY_LIMIT,
) -> pd.DataFrame:
    sql = _summary_sql(
        "login_security",
        company,
        environment,
        start_date,
        end_date,
        filters="",
        order_by="EVENT_DATE DESC",
        limit=limit,
    )
    return _run_summary(
        domain="login_security",
        sql=sql,
        ttl_key=f"v_login_security_{company}_{environment}_{start_date}_{end_date}_{user}",
        limit=limit,
    )


def get_task_status(
    company: str,
    environment: str,
    start_date: object,
    end_date: object,
    database: str | None = None,
    schema: str | None = None,
    *,
    limit: int = DEFAULT_SUMMARY_LIMIT,
) -> pd.DataFrame:
    sql = _summary_sql(
        "task_status",
        company,
        environment,
        start_date,
        end_date,
        filters="",
        order_by="EVENT_DATE DESC, FAILED_TASK_COUNT DESC",
        limit=limit,
    )
    return _run_summary(
        domain="task_status",
        sql=sql,
        ttl_key=f"v_task_status_{company}_{environment}_{start_date}_{end_date}_{database}_{schema}",
        limit=limit,
    )


def _run_detail(sql: str, *, ttl_key: str, section: str, workflow: str, limit: int) -> pd.DataFrame:
    max_rows = _limit(limit, maximum=MAX_DETAIL_LIMIT)
    with query_budget_context("evidence_click", section=section, workflow=workflow, budget=EVIDENCE_CLICK_QUERY_BUDGET):
        try:
            result = run_query(
                sql,
                ttl_key=ttl_key,
                use_cache=True,
                spinner_msg="Loading detail...",
                tier="recent",
                section=section,
                max_rows=max_rows,
                query_boundary="evidence_action",
            )
        except Exception:
            return _empty_frame()
    return result if isinstance(result, pd.DataFrame) else _empty_frame()


def get_recent_query_detail(
    company: str,
    environment: str,
    start_date: object,
    end_date: object,
    *,
    query_id: str | None = None,
    query_signature: str | None = None,
    warehouse: str | None = None,
    user: str | None = None,
    limit: int = DEFAULT_DETAIL_LIMIT,
) -> pd.DataFrame:
    filters = "".join(
        (
            _optional_equals("QUERY_ID", query_id),
            _optional_equals("QUERY_SIGNATURE", query_signature),
            _optional_equals("WAREHOUSE_NAME", warehouse),
            _optional_equals("USER_NAME", user),
        )
    )
    sql = f"""
SELECT
  COMPANY, ENVIRONMENT, QUERY_ID, QUERY_HASH, QUERY_SIGNATURE, WAREHOUSE_NAME,
  USER_NAME, ROLE_NAME, DATABASE_NAME, SCHEMA_NAME, EXECUTION_STATUS,
  TOTAL_ELAPSED_TIME, BYTES_SCANNED, ROWS_PRODUCED, START_TIME
FROM FACT_QUERY_DETAIL_RECENT
WHERE COMPANY = {sql_literal(company, 100)}
  AND ENVIRONMENT = {sql_literal(environment, 100)}
  {_date_range_filter("START_TIME", start_date, end_date)}
  {filters}
ORDER BY START_TIME DESC, TOTAL_ELAPSED_TIME DESC
LIMIT {_limit(limit, maximum=MAX_DETAIL_LIMIT)}
"""
    return _run_detail(
        sql,
        ttl_key=f"recent_query_detail_{company}_{environment}_{start_date}_{end_date}_{query_id}_{query_signature}_{warehouse}_{user}",
        section="Workload Operations",
        workflow="Query Investigation",
        limit=limit,
    )


def get_recent_task_detail(
    company: str,
    environment: str,
    start_date: object,
    end_date: object,
    *,
    task_name: str | None = None,
    database: str | None = None,
    schema: str | None = None,
    limit: int = DEFAULT_DETAIL_LIMIT,
) -> pd.DataFrame:
    filters = "".join(
        (
            _optional_equals("TASK_NAME", task_name),
            _optional_equals("DATABASE_NAME", database),
            _optional_equals("SCHEMA_NAME", schema),
        )
    )
    sql = f"""
SELECT
  COMPANY, ENVIRONMENT, TASK_NAME, ROOT_TASK_NAME, DATABASE_NAME, SCHEMA_NAME,
  STATE, ERROR_CODE, ERROR_MESSAGE, SCHEDULED_TIME, COMPLETED_TIME,
  DATEDIFF('millisecond', SCHEDULED_TIME, COMPLETED_TIME) AS DURATION_MS
FROM FACT_TASK_RUN
WHERE COMPANY = {sql_literal(company, 100)}
  AND ENVIRONMENT = {sql_literal(environment, 100)}
  {_date_range_filter("SCHEDULED_TIME", start_date, end_date)}
  {filters}
ORDER BY SCHEDULED_TIME DESC, TASK_NAME
LIMIT {_limit(limit, maximum=MAX_DETAIL_LIMIT)}
"""
    return _run_detail(
        sql,
        ttl_key=f"recent_task_detail_{company}_{environment}_{start_date}_{end_date}_{task_name}_{database}_{schema}",
        section="Workload Operations",
        workflow="Task Detail",
        limit=limit,
    )


__all__ = [
    "DEFAULT_DETAIL_LIMIT",
    "DEFAULT_SUMMARY_LIMIT",
    "MAX_DETAIL_LIMIT",
    "SUMMARY_VIEW_SPECS",
    "get_cortex_usage",
    "get_login_security",
    "get_query_daily_summary",
    "get_recent_query_detail",
    "get_recent_task_detail",
    "get_task_status",
    "get_warehouse_credits",
]
