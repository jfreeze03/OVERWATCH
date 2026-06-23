"""Shared task-health and task-history metric loaders."""

from __future__ import annotations

import pandas as pd

from .company_filter import get_active_company, get_company_scope_key
from .compatibility import build_task_health_sql, build_task_history_sql
from .mart import build_mart_task_history_sql
from .query import run_query
from .shared_metrics_cache import _empty_result, _load_or_reuse
from .shared_metrics_contracts import SharedMetricResult


def load_shared_task_health_summary(
    session: object,
    days: int,
    company: str | None = None,
    *,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load reusable TASK_HISTORY health counters for DBA summary surfaces."""

    company = company or get_active_company()
    days = int(days)

    def _loader() -> SharedMetricResult:
        try:
            df = run_query(
                build_task_health_sql(
                    session,
                    f"scheduled_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())",
                    company=company,
                ),
                ttl_key=get_company_scope_key("shared_task_health", days),
                tier="historical",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY",
                available=not df.empty,
                effective_days=days,
            )
        except Exception as exc:
            return SharedMetricResult(
                data=pd.DataFrame([{
                    "TASK_RUNS": 0,
                    "FAILED_TASKS": 0,
                    "SUCCEEDED_TASKS": 0,
                    "DISTINCT_TASKS": 0,
                }]),
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY",
                available=False,
                message=str(exc),
                effective_days=days,
            )

    return _load_or_reuse("shared_task_health", (company, days), _loader, force=force)


def load_shared_task_history_detail(
    session: object,
    days: int,
    company: str | None = None,
    *,
    database_contains: str = "",
    limit: int = 1000,
    allow_live_fallback: bool = True,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load task-history detail once for Task Management and DBA detail paths."""

    company = company or get_active_company()
    days = max(1, int(days or 7))
    database_contains = str(database_contains or "").strip()
    limit = max(1, int(limit or 1000))

    def _loader() -> SharedMetricResult:
        mart_message = ""
        try:
            mart_df = run_query(
                build_mart_task_history_sql(
                    days,
                    company=company,
                    database_contains=database_contains,
                    limit=limit,
                ),
                ttl_key=get_company_scope_key("shared_task_history_detail_mart", company, days, database_contains, limit),
                tier="historical",
                section=section,
            )
            if not mart_df.empty:
                return SharedMetricResult(
                    data=mart_df,
                    source="Fast task run summary",
                    available=True,
                    effective_days=days,
                )
            mart_message = "Fast task run summary returned no rows."
        except Exception as exc:
            mart_message = f"Fast task run summary unavailable: {exc}"

        if not allow_live_fallback:
            return _empty_result("Fast task run summary", mart_message, effective_days=days)

        try:
            live_df = run_query(
                build_task_history_sql(
                    session,
                    f"scheduled_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())",
                    limit=limit,
                    company=company,
                ),
                ttl_key=get_company_scope_key("shared_task_history_detail_live", company, days, database_contains, limit),
                tier="historical",
                section=section,
            )
            return SharedMetricResult(
                data=live_df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY",
                available=not live_df.empty,
                message=mart_message,
                effective_days=days,
            )
        except Exception as exc:
            message = f"{mart_message} Live fallback unavailable: {exc}".strip()
            return _empty_result(
                "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY",
                message,
                effective_days=days,
            )

    return _load_or_reuse(
        "shared_task_history_detail",
        (company, days, database_contains, limit, allow_live_fallback),
        _loader,
        force=force,
    )
