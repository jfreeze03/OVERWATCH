"""App-facing v2 first-paint SQL."""

from __future__ import annotations


APP_VIEWS = {
    "executive_summary": "V_EXECUTIVE_SUMMARY",
    "dba_morning_cockpit": "V_DBA_MORNING_COCKPIT",
    "source_freshness": "V_SOURCE_FRESHNESS",
    "alert_intelligence": "V_ALERT_INTELLIGENCE",
    "task_status_daily": "V_TASK_STATUS_DAILY",
    "warehouse_daily_credits": "V_WAREHOUSE_DAILY_CREDITS",
    "cost_forecast": "V_COST_FORECAST",
    "contract_burn_down": "V_CONTRACT_BURN_DOWN",
    "login_security_daily": "V_LOGIN_SECURITY_DAILY",
    "query_error_summary": "V_QUERY_ERROR_SUMMARY",
    "storage_daily": "V_STORAGE_DAILY",
    "cortex_code_usage_daily": "V_CORTEX_CODE_USAGE_DAILY",
    "cost_allocation_daily": "V_COST_ALLOCATION_DAILY",
    "app_self_cost": "V_OVERWATCH_APP_SELF_COST_DAILY",
}


def sql_literal(value: object, max_len: int = 500) -> str:
    text = str(value if value is not None else "")[:max_len]
    return "'" + text.replace("'", "''") + "'"


def scoped_view_sql(
    view_name: str,
    *,
    company: str = "ALL",
    environment: str = "ALL",
    window: int = 30,
    warehouse: str = "ALL",
    limit: int = 500,
) -> str:
    """Return a bounded first-paint select against an app-facing view."""
    if view_name not in set(APP_VIEWS.values()):
        raise ValueError(f"Unknown v2 app-facing view: {view_name}")
    company_lit = sql_literal(company or "ALL", 100)
    environment_lit = sql_literal(environment or "ALL", 100)
    warehouse_lit = sql_literal(warehouse or "ALL", 200)
    return f"""
SELECT *
FROM {view_name}
WHERE UPPER(COALESCE(COMPANY, 'ALL')) IN ('ALL', UPPER({company_lit}))
  AND UPPER(COALESCE(ENVIRONMENT, 'ALL')) IN ('ALL', UPPER({environment_lit}))
  AND COALESCE(WINDOW_DAYS, {int(window or 30)}) <= {int(window or 30)}
  AND UPPER(COALESCE(WAREHOUSE_NAME, 'ALL')) IN ('ALL', UPPER({warehouse_lit}))
ORDER BY SNAPSHOT_TS DESC
LIMIT {int(limit)}
""".strip()


def first_paint_view_names() -> tuple[str, ...]:
    return tuple(APP_VIEWS.values())
