"""Data-driven scope options for the v2 shell."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from overwatch_app.data.cache import dataframe_cache


DEFAULT_COMPANIES = ("ALL", "ALFA", "Trexis")
DEFAULT_ENVIRONMENTS = ("ALL", "PROD", "NONPROD")
DEFAULT_WAREHOUSES = ("ALL",)

SCOPE_OPTIONS_SQL = """
SELECT DISTINCT COMPANY, ENVIRONMENT, WAREHOUSE_NAME
FROM (
  SELECT COMPANY, ENVIRONMENT, WAREHOUSE_NAME FROM V_COST_FORECAST
  UNION ALL
  SELECT COMPANY, ENVIRONMENT, WAREHOUSE_NAME FROM V_QUERY_ERROR_SUMMARY
  UNION ALL
  SELECT COMPANY, ENVIRONMENT, WAREHOUSE_NAME FROM V_WAREHOUSE_DAILY_CREDITS
)
WHERE COMPANY IS NOT NULL
   OR ENVIRONMENT IS NOT NULL
   OR WAREHOUSE_NAME IS NOT NULL
LIMIT 1000
""".strip()


@dataclass(frozen=True)
class ScopeOptions:
    companies: tuple[str, ...] = DEFAULT_COMPANIES
    environments: tuple[str, ...] = DEFAULT_ENVIRONMENTS
    warehouses: tuple[str, ...] = DEFAULT_WAREHOUSES
    state: str = "offline_defaults"


def _ordered_with_all(values: pd.Series, fallback: tuple[str, ...]) -> tuple[str, ...]:
    cleaned = sorted({
        str(value).strip()
        for value in values.dropna()
        if str(value).strip() and str(value).strip().upper() != "ALL"
    })
    if not cleaned:
        return fallback
    return ("ALL", *cleaned)


def _row_value(row: Any, field: str, index: int) -> Any:
    if hasattr(row, field):
        return getattr(row, field)
    try:
        return row[index]
    except Exception:
        return None


def _rows_to_frame(rows: list[Any]) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            records.append(row)
        else:
            records.append({
                "COMPANY": _row_value(row, "COMPANY", 0),
                "ENVIRONMENT": _row_value(row, "ENVIRONMENT", 1),
                "WAREHOUSE_NAME": _row_value(row, "WAREHOUSE_NAME", 2),
            })
    return pd.DataFrame(records)


@dataframe_cache
def _fetch_scope_frame(sql: str, _session: Any) -> pd.DataFrame:
    rows = _session.sql(sql).collect()
    return _rows_to_frame(list(rows))


def fetch_scope_options(session: Any = None) -> ScopeOptions:
    """Return data-driven scope options, retaining offline defaults exactly."""
    if session is None or not callable(getattr(session, "sql", None)):
        return ScopeOptions()
    try:
        frame = _fetch_scope_frame(SCOPE_OPTIONS_SQL, session)
    except Exception:
        return ScopeOptions(state="query_failed_defaults")
    if frame.empty:
        return ScopeOptions(state="empty_defaults")
    for column in ("COMPANY", "ENVIRONMENT", "WAREHOUSE_NAME"):
        if column not in frame.columns:
            frame[column] = pd.NA
    return ScopeOptions(
        companies=_ordered_with_all(frame["COMPANY"], DEFAULT_COMPANIES),
        environments=_ordered_with_all(frame["ENVIRONMENT"], DEFAULT_ENVIRONMENTS),
        warehouses=_ordered_with_all(frame["WAREHOUSE_NAME"], DEFAULT_WAREHOUSES),
        state="loaded",
    )


def clear_scope_options_cache() -> None:
    _fetch_scope_frame.clear()  # type: ignore[attr-defined]
