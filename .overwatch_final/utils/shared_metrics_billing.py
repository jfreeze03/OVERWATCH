"""Shared billing reconciliation loaders."""

from __future__ import annotations

from .billing_reconciliation import build_account_billing_reconciliation_sql
from .company_filter import get_active_company, get_company_scope_key
from .query import run_query_or_raise
from .shared_metrics_cache import _load_or_reuse
from .shared_metrics_contracts import SharedMetricResult


def load_shared_account_billing_reconciliation(
    days: int,
    company: str | None = None,
    *,
    credit_price: float = 0.0,
    start_date: object = None,
    end_date: object = None,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load completed account-level billed credits for Snowsight reconciliation."""

    company = company or get_active_company()
    days = max(1, int(days or 7))
    credit_price = float(credit_price or 0)

    def _loader() -> SharedMetricResult:
        df = run_query_or_raise(
            build_account_billing_reconciliation_sql(
                days,
                credit_price=credit_price or None,
                start_date=start_date,
                end_date=end_date,
            ),
            ttl_key=get_company_scope_key(
                "shared_account_billing_reconciliation",
                days,
                credit_price,
                start_date or "",
                end_date or "",
            ),
            tier="historical",
            section=section,
        )
        return SharedMetricResult(
            data=df,
            source="Completed account billing history",
            available=not df.empty,
            effective_days=days,
        )

    return _load_or_reuse(
        "shared_account_billing_reconciliation",
        (company, days, credit_price, start_date or "", end_date or ""),
        _loader,
        force=force,
    )


__all__ = ["load_shared_account_billing_reconciliation"]
