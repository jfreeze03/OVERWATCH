"""Daily-safe leadership monitoring query facade.

The helpers in this module read app-facing secure views over OVERWATCH compact
facts. They are intended for first-screen summary panels and bounded
drill-through starts, so they do not embed source-history scans or raw query
text.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from utils.performance import SUMMARY_AUTOLOAD_QUERY_BUDGET, query_budget_context
from utils.query import run_query
from utils.sql_safe import sql_literal


DEFAULT_LIMIT = 200

LEADERSHIP_VIEW_SPECS: dict[str, dict[str, str]] = {
    "credit_daily": {
        "view": "V_LEADERSHIP_CREDIT_DAILY",
        "section": "Cost & Contract",
        "workflow": "Credit Burn Rate",
        "date_column": "USAGE_DATE",
        "columns": (
            "COMPANY, ENVIRONMENT, USAGE_DATE, SERVICE_TYPE, WAREHOUSE_NAME, "
            "CREDITS_USED, CREDITS_USED_COMPUTE, CREDITS_USED_CLOUD_SERVICES, "
            "ESTIMATED_COST_USD, UPDATED_AT"
        ),
    },
    "credit_comparison": {
        "view": "V_LEADERSHIP_CREDIT_COMPARISON_24H",
        "section": "Cost & Contract",
        "workflow": "24h Credit Comparison",
        "date_column": "",
        "columns": (
            "COMPANY, ENVIRONMENT, CONTRIBUTOR_TYPE, CONTRIBUTOR_NAME, "
            "CURRENT_24H_CREDITS, PRIOR_24H_CREDITS, CREDIT_DELTA, PCT_DELTA, "
            "ESTIMATED_COST_DELTA_USD, UPDATED_AT"
        ),
    },
    "login_security": {
        "view": "V_LEADERSHIP_LOGIN_SECURITY",
        "section": "Security Monitoring",
        "workflow": "Login Security",
        "date_column": "EVENT_DATE",
        "columns": (
            "COMPANY, ENVIRONMENT, EVENT_DATE, EVENT_HOUR, USER_NAME, CLIENT_IP, "
            "REPORTED_CLIENT_TYPE, IS_SUCCESS, ERROR_CODE, ERROR_MESSAGE, LOGIN_COUNT, "
            "FAILED_COUNT, FIRST_SEEN, LAST_SEEN, RISK_REASON, RISK_SCORE, UPDATED_AT"
        ),
    },
    "query_errors": {
        "view": "V_LEADERSHIP_QUERY_ERRORS",
        "section": "Workload Operations",
        "workflow": "Query Errors",
        "date_column": "EVENT_HOUR",
        "columns": (
            "COMPANY, ENVIRONMENT, EVENT_DATE, EVENT_HOUR, WAREHOUSE_NAME, USER_NAME, "
            "ROLE_NAME, DATABASE_NAME, SCHEMA_NAME, ERROR_CODE, ERROR_MESSAGE, "
            "FAILED_QUERY_COUNT, TOTAL_QUERY_COUNT, FAILURE_RATE, LATEST_QUERY_ID, "
            "LATEST_OCCURRENCE, UPDATED_AT"
        ),
    },
    "storage_daily": {
        "view": "V_LEADERSHIP_STORAGE_DAILY",
        "section": "Cost & Contract",
        "workflow": "Storage Growth",
        "date_column": "USAGE_DATE",
        "columns": (
            "COMPANY, ENVIRONMENT, USAGE_DATE, DATABASE_NAME, DATABASE_BYTES, "
            "FAILSAFE_BYTES, TOTAL_BYTES, DATABASE_TB, FAILSAFE_TB, TOTAL_TB, "
            "DAILY_GROWTH_BYTES, DAILY_GROWTH_PCT, UPDATED_AT"
        ),
    },
    "cortex_code": {
        "view": "V_LEADERSHIP_CORTEX_CODE_USAGE",
        "section": "Cost & Contract",
        "workflow": "Cortex Code Usage",
        "date_column": "USAGE_DATE",
        "columns": (
            "COMPANY, ENVIRONMENT, USAGE_DATE, USER_NAME, USER_DISPLAY_NAME, "
            "USER_CHART_LABEL, CLIENT_SOURCE, SERVICE_TYPE, MODEL_NAME, REQUEST_COUNT, "
            "TOKEN_COUNT, CREDITS_USED, ESTIMATED_COST_USD, UPDATED_AT"
        ),
    },
    "role_grant": {
        "view": "V_LEADERSHIP_ROLE_GRANT_AUDIT",
        "section": "Security Monitoring",
        "workflow": "Role / Grant Audit",
        "date_column": "CREATED_ON",
        "columns": (
            "COMPANY, ENVIRONMENT, ROLE_NAME, GRANTEE_NAME, GRANTEE_TYPE, PRIVILEGE, "
            "GRANTED_ON, OBJECT_DATABASE, OBJECT_SCHEMA, OBJECT_NAME, GRANTED_BY, "
            "CREATED_ON, DELETED_ON, IS_ACTIVE, UPDATED_AT"
        ),
    },
}


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame()


def _limit(value: int | None = None) -> int:
    try:
        parsed = int(value if value is not None else DEFAULT_LIMIT)
    except (TypeError, ValueError):
        parsed = DEFAULT_LIMIT
    return max(1, min(parsed, DEFAULT_LIMIT))


def _sql_date(value: date | datetime | str | None) -> str:
    if isinstance(value, datetime):
        return sql_literal(value.date().isoformat(), 40)
    if isinstance(value, date):
        return sql_literal(value.isoformat(), 40)
    text = str(value or "").strip()
    return sql_literal(text[:40], 40) if text else "NULL"


def _date_filter(column: str, start_date: object, end_date: object) -> str:
    if not column:
        return ""
    start = _sql_date(start_date)
    end = _sql_date(end_date)
    clauses: list[str] = []
    if start != "NULL":
        clauses.append(f"{column} >= TO_DATE({start})")
    if end != "NULL":
        clauses.append(f"{column} <= TO_DATE({end})")
    return "\n  AND " + "\n  AND ".join(clauses) if clauses else ""


def _timestamp_filter(column: str, expression: str) -> str:
    return f"\n  AND {column} >= {expression}" if column else ""


def _optional_equals(column: str, value: object, *, max_length: int = 200) -> str:
    text = str(value or "").strip()
    if not text or text.upper() in {"ALL", "ALL ENVIRONMENTS", "ALL SCOPED WAREHOUSES"}:
        return ""
    return f"\n  AND {column} = {sql_literal(text, max_length)}"


def _optional_like(column: str, value: object, *, default: str = "") -> str:
    text = str(value or default or "").strip()
    if not text:
        return ""
    return f"\n  AND {column} ILIKE {sql_literal(text, 200)}"


def _environment_filter(environment: object) -> str:
    text = str(environment or "").strip()
    if not text or text.upper() in {"ALL", "ALL ENVIRONMENTS"}:
        return ""
    return f"\n  AND ENVIRONMENT = {sql_literal(text, 100)}"


def _leadership_sql(
    domain: str,
    company: str,
    environment: str,
    *,
    start_date: object | None = None,
    end_date: object | None = None,
    filters: str = "",
    order_by: str = "UPDATED_AT DESC",
    limit: int = DEFAULT_LIMIT,
) -> str:
    spec = LEADERSHIP_VIEW_SPECS[domain]
    date_filter = _date_filter(spec["date_column"], start_date, end_date) if start_date or end_date else ""
    return f"""
SELECT {spec["columns"]}
FROM {spec["view"]}
WHERE COMPANY = {sql_literal(company, 100)}
  {_environment_filter(environment)}
  {date_filter}
  {filters}
ORDER BY {order_by}
LIMIT {_limit(limit)}
"""


def _run(domain: str, sql: str, *, ttl_key: str, limit: int = DEFAULT_LIMIT) -> pd.DataFrame:
    spec = LEADERSHIP_VIEW_SPECS[domain]
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
                spinner_msg="Reading current summary...",
                tier="section_summary",
                section=spec["section"],
                max_rows=_limit(limit),
                query_boundary="section_summary_autoload",
            )
        except Exception:
            return _empty_frame()
    return result if isinstance(result, pd.DataFrame) else _empty_frame()


def get_credit_daily(
    company: str,
    environment: str,
    start_date: object,
    end_date: object,
    warehouse: str | None = None,
) -> pd.DataFrame:
    sql = _leadership_sql(
        "credit_daily",
        company,
        environment,
        start_date=start_date,
        end_date=end_date,
        filters=_optional_equals("WAREHOUSE_NAME", warehouse),
        order_by="USAGE_DATE DESC, CREDITS_USED DESC, SERVICE_TYPE",
    )
    return _run(
        "credit_daily",
        sql,
        ttl_key=f"leadership_credit_daily_{company}_{environment}_{start_date}_{end_date}_{warehouse}",
    )


def get_credit_comparison_24h(
    company: str,
    environment: str,
    warehouse: str | None = None,
) -> pd.DataFrame:
    filters = _optional_equals("CONTRIBUTOR_NAME", warehouse) if warehouse else ""
    sql = _leadership_sql(
        "credit_comparison",
        company,
        environment,
        filters=filters,
        order_by="ABS(CREDIT_DELTA) DESC, CURRENT_24H_CREDITS DESC",
    )
    return _run(
        "credit_comparison",
        sql,
        ttl_key=f"leadership_credit_comparison_{company}_{environment}_{warehouse}",
    )


def get_login_security(
    company: str,
    environment: str,
    start_date: object,
    end_date: object,
    user: str | None = None,
) -> pd.DataFrame:
    sql = _leadership_sql(
        "login_security",
        company,
        environment,
        start_date=start_date,
        end_date=end_date,
        filters=_optional_equals("USER_NAME", user),
        order_by="EVENT_DATE DESC, FAILED_COUNT DESC, USER_NAME",
    )
    return _run(
        "login_security",
        sql,
        ttl_key=f"leadership_login_security_{company}_{environment}_{start_date}_{end_date}_{user}",
    )


def get_failed_logins_last_hour(company: str, environment: str) -> pd.DataFrame:
    sql = _leadership_sql(
        "login_security",
        company,
        environment,
        filters=(
            _timestamp_filter("EVENT_HOUR", "DATEADD('hour', -1, CURRENT_TIMESTAMP())")
            + "\n  AND FAILED_COUNT > 0"
        ),
        order_by="FAILED_COUNT DESC, LAST_SEEN DESC",
        limit=50,
    )
    return _run(
        "login_security",
        sql,
        ttl_key=f"leadership_failed_logins_last_hour_{company}_{environment}",
        limit=50,
    )


def get_suspicious_logins(
    company: str,
    environment: str,
    start_date: object,
    end_date: object,
) -> pd.DataFrame:
    sql = _leadership_sql(
        "login_security",
        company,
        environment,
        start_date=start_date,
        end_date=end_date,
        filters="\n  AND COALESCE(RISK_SCORE, 0) > 0",
        order_by="RISK_SCORE DESC, FAILED_COUNT DESC, LAST_SEEN DESC",
        limit=100,
    )
    return _run(
        "login_security",
        sql,
        ttl_key=f"leadership_suspicious_logins_{company}_{environment}_{start_date}_{end_date}",
        limit=100,
    )


def get_query_errors(
    company: str,
    environment: str,
    start_date: object,
    end_date: object,
    warehouse: str | None = None,
    user: str | None = None,
    database: str | None = None,
    schema: str | None = None,
) -> pd.DataFrame:
    filters = "".join(
        (
            _optional_equals("WAREHOUSE_NAME", warehouse),
            _optional_equals("USER_NAME", user),
            _optional_equals("DATABASE_NAME", database),
            _optional_equals("SCHEMA_NAME", schema),
        )
    )
    sql = _leadership_sql(
        "query_errors",
        company,
        environment,
        start_date=start_date,
        end_date=end_date,
        filters=filters,
        order_by="FAILED_QUERY_COUNT DESC, LATEST_OCCURRENCE DESC",
    )
    return _run(
        "query_errors",
        sql,
        ttl_key=f"leadership_query_errors_{company}_{environment}_{start_date}_{end_date}_{warehouse}_{user}_{database}_{schema}",
    )


def get_storage_daily(
    company: str,
    environment: str,
    start_date: object,
    end_date: object,
    database: str | None = None,
) -> pd.DataFrame:
    sql = _leadership_sql(
        "storage_daily",
        company,
        environment,
        start_date=start_date,
        end_date=end_date,
        filters=_optional_equals("DATABASE_NAME", database),
        order_by="USAGE_DATE DESC, TOTAL_TB DESC, DATABASE_NAME",
    )
    return _run(
        "storage_daily",
        sql,
        ttl_key=f"leadership_storage_daily_{company}_{environment}_{start_date}_{end_date}_{database}",
    )


def get_cortex_code_usage(
    company: str,
    environment: str,
    start_date: object,
    end_date: object,
    user: str | None = None,
) -> pd.DataFrame:
    sql = _leadership_sql(
        "cortex_code",
        company,
        environment,
        start_date=start_date,
        end_date=end_date,
        filters=_optional_equals("USER_NAME", user),
        order_by="USAGE_DATE DESC, TOKEN_COUNT DESC, USER_CHART_LABEL",
    )
    return _run(
        "cortex_code",
        sql,
        ttl_key=f"leadership_cortex_code_{company}_{environment}_{start_date}_{end_date}_{user}",
    )


def get_role_grant_audit(
    company: str,
    environment: str,
    role_pattern: str = "TF_O_DEV_%",
    database: str = "ALFA_EDW_SAN",
) -> pd.DataFrame:
    filters = _optional_like("ROLE_NAME", role_pattern, default="TF_O_DEV_%")
    if database:
        filters += _optional_equals("OBJECT_DATABASE", database)
    sql = _leadership_sql(
        "role_grant",
        company,
        environment,
        filters=filters,
        order_by="ROLE_NAME, CREATED_ON DESC, GRANTEE_NAME",
    )
    return _run(
        "role_grant",
        sql,
        ttl_key=f"leadership_role_grant_{company}_{environment}_{role_pattern}_{database}",
    )


def default_window(days: int = 7) -> tuple[date, date]:
    end = date.today()
    return end - timedelta(days=max(1, int(days)) - 1), end


__all__ = [
    "DEFAULT_LIMIT",
    "LEADERSHIP_VIEW_SPECS",
    "default_window",
    "get_cortex_code_usage",
    "get_credit_comparison_24h",
    "get_credit_daily",
    "get_failed_logins_last_hour",
    "get_login_security",
    "get_query_errors",
    "get_role_grant_audit",
    "get_storage_daily",
    "get_suspicious_logins",
]
