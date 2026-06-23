"""Shared stored-procedure telemetry metric loaders."""

from __future__ import annotations

from .company_filter import get_active_company, get_company_scope_key
from .mart import (
    build_mart_procedure_calls_sql,
    build_mart_procedure_inventory_sql,
    build_mart_procedure_sla_sql,
)
from .query import run_query
from .shared_metrics_cache import _empty_result, _load_or_reuse
from .shared_metrics_contracts import SharedMetricResult


def load_shared_procedure_inventory(
    company: str | None = None,
    *,
    database_contains: str = "",
    live_sql: str = "",
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load stored procedure inventory once, preferring the procedure snapshot mart."""

    company = company or get_active_company()
    database_contains = str(database_contains or "").strip()

    def _loader() -> SharedMetricResult:
        mart_message = ""
        try:
            df = run_query(
                build_mart_procedure_inventory_sql(company=company, database_contains=database_contains),
                ttl_key=get_company_scope_key("shared_procedure_inventory_mart", database_contains),
                tier="metadata",
                section=section,
            )
            if not df.empty:
                return SharedMetricResult(data=df, source="Fast procedure inventory", available=True)
            mart_message = "Procedure inventory mart returned no rows."
        except Exception as exc:
            mart_message = str(exc)

        live_sql_value = live_sql() if callable(live_sql) else live_sql
        if not live_sql_value:
            return _empty_result("Procedure inventory", mart_message)
        try:
            df = run_query(
                live_sql_value,
                ttl_key=get_company_scope_key("shared_procedure_inventory_live", database_contains),
                tier="metadata",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.PROCEDURES",
                available=not df.empty,
                message="" if not df.empty else mart_message,
            )
        except Exception as exc:
            return _empty_result("Procedure inventory", f"{mart_message} Live fallback unavailable: {exc}")

    return _load_or_reuse("shared_procedure_inventory", (company, database_contains), _loader, force=force)


def load_shared_procedure_calls(
    company: str | None = None,
    *,
    days: int = 7,
    live_sql: str = "",
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load stored procedure call summary once, preferring FACT_PROCEDURE_RUN."""

    company = company or get_active_company()
    days = max(1, int(days or 7))

    def _loader() -> SharedMetricResult:
        mart_message = ""
        try:
            df = run_query(
                build_mart_procedure_calls_sql(days, company=company),
                ttl_key=get_company_scope_key("shared_procedure_calls_mart", days),
                tier="standard",
                section=section,
            )
            if not df.empty:
                return SharedMetricResult(data=df, source="Fast procedure run summary", available=True, effective_days=days)
            mart_message = "Procedure call mart returned no rows."
        except Exception as exc:
            mart_message = str(exc)

        live_sql_value = live_sql() if callable(live_sql) else live_sql
        if not live_sql_value:
            return _empty_result("Procedure call summary", mart_message, effective_days=days)
        try:
            df = run_query(
                live_sql_value,
                ttl_key=get_company_scope_key("shared_procedure_calls_live", days),
                tier="standard",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                available=not df.empty,
                message="" if not df.empty else mart_message,
                effective_days=days,
            )
        except Exception as exc:
            return _empty_result("Procedure call summary", f"{mart_message} Live fallback unavailable: {exc}", effective_days=days)

    return _load_or_reuse("shared_procedure_calls", (company, days), _loader, force=force)


def load_shared_procedure_sla(
    company: str | None = None,
    *,
    days: int = 7,
    live_sql: str = "",
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load procedure SLA/cost detail once, preferring FACT_PROCEDURE_RUN."""

    company = company or get_active_company()
    days = max(1, int(days or 7))

    def _loader() -> SharedMetricResult:
        mart_message = ""
        try:
            df = run_query(
                build_mart_procedure_sla_sql(days, company=company),
                ttl_key=get_company_scope_key("shared_procedure_sla_mart", days),
                tier="standard",
                section=section,
            )
            if not df.empty:
                return SharedMetricResult(data=df, source="Fast procedure SLA summary", available=True, effective_days=days)
            mart_message = "Procedure SLA mart returned no rows."
        except Exception as exc:
            mart_message = str(exc)

        live_sql_value = live_sql() if callable(live_sql) else live_sql
        if not live_sql_value:
            return _empty_result("Procedure SLA/cost watch", mart_message, effective_days=days)
        try:
            df = run_query(
                live_sql_value,
                ttl_key=get_company_scope_key("shared_procedure_sla_live", days),
                tier="standard",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                available=not df.empty,
                message="" if not df.empty else mart_message,
                effective_days=days,
            )
        except Exception as exc:
            return _empty_result("Procedure SLA/cost watch", f"{mart_message} Live fallback unavailable: {exc}", effective_days=days)

    return _load_or_reuse("shared_procedure_sla", (company, days), _loader, force=force)
