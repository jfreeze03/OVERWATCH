"""Shared service cost loaders."""

from __future__ import annotations

from .company_filter import get_active_company, get_company_scope_key
from .cost import build_snowflake_service_cost_lens_sql, build_snowflake_service_cost_trend_sql
from .query import run_query_or_raise
from .shared_metrics_cache import _load_or_reuse
from .shared_metrics_contracts import SharedMetricResult


def load_shared_service_cost_lens(
    days: int,
    company: str | None = None,
    *,
    credit_price: float = 0.0,
    ai_credit_price: float = 0.0,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load official service cost movement once per scope for cost surfaces."""
    company = company or get_active_company()
    days = max(1, int(days or 7))
    credit_price = float(credit_price or 0)
    ai_credit_price = float(ai_credit_price or 0)

    def _loader() -> SharedMetricResult:
        df = run_query_or_raise(
            build_snowflake_service_cost_lens_sql(
                days,
                credit_price or None,
                ai_credit_price or None,
            ),
            ttl_key=get_company_scope_key(
                "shared_service_cost_lens_official",
                days,
                credit_price,
                ai_credit_price,
            ),
            tier="historical",
            section=section,
        )
        return SharedMetricResult(
            data=df,
            source="Official Cost Monitor: SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY",
            available=not df.empty,
            effective_days=days,
        )

    return _load_or_reuse(
        "shared_service_cost_lens",
        (company, days, credit_price, ai_credit_price),
        _loader,
        force=force,
    )


def load_shared_service_cost_trend(
    days: int,
    company: str | None = None,
    *,
    credit_price: float = 0.0,
    ai_credit_price: float = 0.0,
    start_date: object = None,
    end_date: object = None,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load daily official service cost once per scope for cost surfaces."""
    company = company or get_active_company()
    days = max(1, int(days or 7))
    credit_price = float(credit_price or 0)
    ai_credit_price = float(ai_credit_price or 0)

    def _loader() -> SharedMetricResult:
        df = run_query_or_raise(
            build_snowflake_service_cost_trend_sql(
                days,
                credit_price or None,
                ai_credit_price or None,
                start_date=start_date,
                end_date=end_date,
            ),
            ttl_key=get_company_scope_key(
                "shared_service_cost_trend_official",
                days,
                credit_price,
                ai_credit_price,
                start_date or "",
                end_date or "",
            ),
            tier="historical",
            section=section,
        )
        return SharedMetricResult(
            data=df,
            source="Official Cost Monitor: SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY",
            available=not df.empty,
            effective_days=days,
        )

    return _load_or_reuse(
        "shared_service_cost_trend",
        (company, days, credit_price, ai_credit_price, start_date or "", end_date or ""),
        _loader,
        force=force,
    )
