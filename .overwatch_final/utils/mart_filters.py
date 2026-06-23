"""Pure filter helpers for optional OVERWATCH mart SQL builders."""

from __future__ import annotations

from config import DEFAULT_ENVIRONMENT, ENVIRONMENT_CONFIG
from runtime_state import GLOBAL_ENVIRONMENT, get_state
from .company_filter import get_environment_db_patterns
from .query import sql_literal


def _mart_text_filter(column: str, value: str = "") -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    return f"AND {column} ILIKE '%' || {sql_literal(value, 300)} || '%'"


def _mart_company_filter(company: str = "ALFA") -> str:
    if str(company or "").upper() == "ALL":
        return ""
    return f"AND COMPANY = {sql_literal(company, 100)}"


def _active_environment() -> str:
    try:
        env = str(get_state(GLOBAL_ENVIRONMENT, DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)
    except Exception:
        env = DEFAULT_ENVIRONMENT
    return env if env in ENVIRONMENT_CONFIG else DEFAULT_ENVIRONMENT


def _mart_environment_column(column: str = "ENVIRONMENT") -> str:
    """Return the environment column matching a mart database column or alias."""
    raw = str(column or "ENVIRONMENT").strip()
    if not raw:
        return "ENVIRONMENT"
    parts = raw.split(".")
    leaf = parts[-1].strip('"').upper()
    if leaf in {"DATABASE_NAME", "PROCEDURE_CATALOG", "TABLE_CATALOG", "TABLE_CATALOG_NAME"}:
        return ".".join(parts[:-1] + ["environment"]) if len(parts) > 1 else "ENVIRONMENT"
    return raw


def _mart_environment_filter(column: str = "ENVIRONMENT", company: str = "ALFA") -> str:
    environment = _active_environment()
    if environment.upper() == "ALL":
        return ""
    env_col = _mart_environment_column(column)
    values = [environment]
    values.extend(get_environment_db_patterns(environment, company))
    if environment == "DEV_ALL":
        values.extend(["ALL DEV/SIT", "OTHER ALFA NON-PROD"])
    if not values:
        return ""
    parts = [f"UPPER({env_col}) = {sql_literal(str(value).upper(), 300)}" for value in dict.fromkeys(values)]
    return "AND (" + " OR ".join(parts) + ")"


def _mart_database_filter(column: str = "DATABASE_NAME", value: str = "", company: str = "ALFA") -> str:
    return " ".join(
        filter(
            None,
            [
                _mart_text_filter(column, value),
                _mart_environment_filter(column, company),
            ],
        )
    )


def _mart_window_condition(column: str, days_back: int, start_date: object = None, end_date: object = None) -> str:
    clauses = [f"{column} >= DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())"]
    if start_date:
        clauses.append(f"{column} >= TO_TIMESTAMP_NTZ({sql_literal(str(start_date) + ' 00:00:00', 40)})")
    if end_date:
        clauses.append(
            f"{column} < DATEADD('DAY', 1, TO_TIMESTAMP_NTZ({sql_literal(str(end_date) + ' 00:00:00', 40)}))"
        )
    return " AND ".join(clauses)


def _mart_window_filter(column: str, days_back: int, start_date: object = None, end_date: object = None) -> str:
    return "AND " + _mart_window_condition(column, days_back, start_date, end_date)


__all__ = [
    "_active_environment",
    "_mart_company_filter",
    "_mart_database_filter",
    "_mart_environment_column",
    "_mart_environment_filter",
    "_mart_text_filter",
    "_mart_window_condition",
    "_mart_window_filter",
]
