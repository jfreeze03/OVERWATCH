"""Shared metric cache keys, state reuse, and global filter helpers."""

from __future__ import annotations

from typing import Callable

import pandas as pd
from runtime_state import (
    GLOBAL_DATABASE,
    GLOBAL_END_DATE,
    GLOBAL_ROLE,
    GLOBAL_START_DATE,
    GLOBAL_USER,
    GLOBAL_WAREHOUSE,
    get_state,
    set_state,
)

from .company_filter import get_company_scope_key
from .query import sql_literal
from .shared_metrics_contracts import SharedMetricResult


def _empty_result(source: str, message: str = "", effective_days: int | None = None) -> SharedMetricResult:
    return SharedMetricResult(
        data=pd.DataFrame(),
        source=source,
        available=False,
        message=message,
        effective_days=effective_days,
    )


def _shared_state_key(metric: str, *parts: object) -> str:
    return f"_shared_metric_{get_company_scope_key(metric, *parts)}"


def _get_cached_result(state_key: str) -> SharedMetricResult | None:
    result = get_state(state_key)
    return result if isinstance(result, SharedMetricResult) else None


def _store_result(state_key: str, result: SharedMetricResult) -> SharedMetricResult:
    set_state(state_key, result)
    return result


def _global_filter_values() -> tuple[str, str, str, str, object, object]:
    """Return shared global filters through the session-state gateway."""
    return (
        str(get_state(GLOBAL_WAREHOUSE, "") or "").strip(),
        str(get_state(GLOBAL_USER, "") or "").strip(),
        str(get_state(GLOBAL_ROLE, "") or "").strip(),
        str(get_state(GLOBAL_DATABASE, "") or "").strip(),
        get_state(GLOBAL_START_DATE),
        get_state(GLOBAL_END_DATE),
    )


def _load_or_reuse(
    metric: str,
    parts: tuple[object, ...],
    loader: Callable[[], SharedMetricResult],
    *,
    force: bool = False,
) -> SharedMetricResult:
    state_key = _shared_state_key(metric, *parts)
    if not force:
        cached = _get_cached_result(state_key)
        if cached is not None:
            return cached
    return _store_result(state_key, loader())


def _company_column_filter(column: str, company: str | None) -> str:
    if not company or str(company).upper() == "ALL":
        return ""
    return f"AND UPPER({column}) = UPPER({sql_literal(company, 100)})"
