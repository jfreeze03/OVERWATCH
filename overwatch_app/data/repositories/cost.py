"""Cached Cost Intelligence repository."""

from __future__ import annotations

import pandas as pd

from overwatch_app.data.context import build_scope
from overwatch_app.data.sql import APP_VIEWS, scoped_view_sql
from overwatch_app.data.repositories._common import cached_first_paint, read_first_paint_view


@cached_first_paint
def load_cost_first_paint(
    company: str,
    environment: str,
    window: int,
    warehouse: str,
    workflow: str,
    role: str,
    source_version: str,
) -> pd.DataFrame:
    scope = build_scope(
        company=company,
        environment=environment,
        window=window,
        warehouse=warehouse,
        workflow=workflow,
        role=role,
        source_version=source_version,
    )
    return read_first_paint_view(
        scoped_view_sql(APP_VIEWS["cost_forecast"], company=company, environment=environment, window=window, warehouse=warehouse),
        cache_key=scope.cache_key("cost_forecast"),
        section="Cost Intelligence",
        company=company,
        environment=environment,
        window=int(window),
        warehouse=warehouse,
        workflow=workflow,
        role=role,
        source_version=source_version,
    )


@cached_first_paint
def load_contract_burn_down(
    company: str,
    environment: str,
    window: int,
    warehouse: str,
    workflow: str,
    role: str,
    source_version: str,
) -> pd.DataFrame:
    scope = build_scope(
        company=company,
        environment=environment,
        window=window,
        warehouse=warehouse,
        workflow=workflow,
        role=role,
        source_version=source_version,
    )
    return read_first_paint_view(
        scoped_view_sql(APP_VIEWS["contract_burn_down"], company=company, environment=environment, window=window, warehouse=warehouse),
        cache_key=scope.cache_key("contract_burn_down"),
        section="Cost Intelligence",
        company=company,
        environment=environment,
        window=int(window),
        warehouse=warehouse,
        workflow=workflow,
        role=role,
        source_version=source_version,
    )


@cached_first_paint
def load_cost_allocation_daily(
    company: str,
    environment: str,
    window: int,
    warehouse: str,
    workflow: str,
    role: str,
    source_version: str,
) -> pd.DataFrame:
    scope = build_scope(
        company=company,
        environment=environment,
        window=window,
        warehouse=warehouse,
        workflow=workflow,
        role=role,
        source_version=source_version,
    )
    return read_first_paint_view(
        scoped_view_sql(APP_VIEWS["cost_allocation_daily"], company=company, environment=environment, window=window, warehouse=warehouse),
        cache_key=scope.cache_key("cost_allocation"),
        section="Cost Intelligence",
        company=company,
        environment=environment,
        window=int(window),
        warehouse=warehouse,
        workflow=workflow,
        role=role,
        source_version=source_version,
    )


CACHED_REPOSITORY_FUNCTIONS = (
    load_cost_first_paint,
    load_contract_burn_down,
    load_cost_allocation_daily,
)
