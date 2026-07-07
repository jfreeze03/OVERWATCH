"""Cached Executive Landing repository."""

from __future__ import annotations

import pandas as pd

from overwatch_app.data.context import build_scope
from overwatch_app.data.sql import APP_VIEWS, scoped_view_sql
from overwatch_app.data.repositories._common import cached_first_paint, read_first_paint_view


@cached_first_paint
def load_executive_first_paint(
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
        scoped_view_sql(APP_VIEWS["executive_summary"], company=company, environment=environment, window=window, warehouse=warehouse),
        cache_key=scope.cache_key("executive"),
        section="Executive Landing",
        company=company,
        environment=environment,
        window=int(window),
        warehouse=warehouse,
        workflow=workflow,
        role=role,
        source_version=source_version,
    )


@cached_first_paint
def load_source_freshness(
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
        scoped_view_sql(APP_VIEWS["source_freshness"], company=company, environment=environment, window=window, warehouse=warehouse),
        cache_key=scope.cache_key("source_freshness"),
        section="Executive Landing",
        company=company,
        environment=environment,
        window=int(window),
        warehouse=warehouse,
        workflow=workflow,
        role=role,
        source_version=source_version,
    )


CACHED_REPOSITORY_FUNCTIONS = (load_executive_first_paint, load_source_freshness)
