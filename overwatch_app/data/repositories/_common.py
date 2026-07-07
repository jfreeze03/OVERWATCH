"""Common repository cache helpers."""

from __future__ import annotations

from functools import wraps
import re
from typing import Callable

import pandas as pd

from overwatch_app.data.cache import dataframe_cache, sorted_param_items
from overwatch_app.data.query import run_query


def cached_first_paint(func: Callable[..., pd.DataFrame]) -> Callable[..., pd.DataFrame]:
    """Expose a repository-level clear hook while caching at the SQL boundary."""

    @wraps(func)
    def wrapper(*args: object, **kwargs: object) -> pd.DataFrame:
        frame = func(*args, **kwargs)
        return frame.copy(deep=True) if isinstance(frame, pd.DataFrame) else frame

    wrapper.clear = clear_first_paint_cache  # type: ignore[attr-defined]
    return wrapper


def _source_object_from_sql(sql: str) -> str:
    match = re.search(r"\bFROM\s+([A-Z0-9_.$]+)", sql, flags=re.IGNORECASE)
    return match.group(1).upper() if match else "UNKNOWN"


@dataframe_cache
def _cached_run_query(
    query_key: str,
    source_object: str,
    sql: str,
    params: tuple[tuple[str, str], ...],
) -> pd.DataFrame:
    del query_key, source_object
    return run_query(sql, **dict(params))


def clear_first_paint_cache() -> None:
    _cached_run_query.clear()  # type: ignore[attr-defined]


def read_first_paint_view(
    sql: str,
    *,
    cache_key: str,
    section: str,
    company: str,
    environment: str,
    window: int,
    warehouse: str,
    workflow: str,
    role: str,
    source_version: str,
) -> pd.DataFrame:
    params = {
        "ttl_key": cache_key,
        "tier": "v2_first_paint",
        "section": section,
        "max_rows": 500,
        "query_boundary": "v2_first_paint_mart",
        "company": company,
        "environment": environment,
        "window": window,
        "warehouse": warehouse,
        "workflow": workflow,
        "role": role,
        "source_version": source_version,
    }
    return _cached_run_query(
        cache_key,
        _source_object_from_sql(sql),
        sql,
        sorted_param_items(params),
    )
