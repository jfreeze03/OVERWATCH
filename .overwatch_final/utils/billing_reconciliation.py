"""Snowsight-aligned account billing reconciliation helpers."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

import pandas as pd

from config import DEFAULTS
from .cortex_service_types import cortex_service_type_mask
from .sql_safe import sql_literal


BILLING_RECONCILIATION_PACKET_FIELDS = (
    "ACCOUNT_BILLED_CREDITS",
    "ACCOUNT_BILLED_COST_USD",
    "ACCOUNT_USED_CREDITS",
    "COMPUTE_CREDITS",
    "CLOUD_SERVICES_CREDITS",
    "CLOUD_SERVICES_ADJUSTMENT",
    "ACCOUNT_CLOUD_SERVICES_ADJUSTMENT",
    "WAREHOUSE_CREDITS",
    "WAREHOUSE_COST_ESTIMATE_USD",
    "WAREHOUSE_COST_USD",
    "SERVICE_OTHER_CREDITS",
    "SERVICE_OTHER_COST_USD",
    "BILLING_BRIDGE_DELTA_CREDITS",
    "BILLING_BRIDGE_DELTA_USD",
    "BILLING_BRIDGE_STATUS",
    "CORTEX_AI_CREDITS",
    "CORTEX_AI_COST_USD",
    "BILLING_RECONCILIATION_STATUS",
    "BILLING_WINDOW_START",
    "BILLING_WINDOW_END",
    "BILLING_WINDOW_COMPLETE",
    "BILLING_SOURCE_FRESHNESS_TS",
    "BILLING_LATENCY_NOTE",
    "BILLING_RECONCILIATION_WINDOW_START",
    "BILLING_RECONCILIATION_WINDOW_END",
    "BILLING_RECONCILIATION_FRESHNESS",
)

DAILY_SAFE_BILLING_LABELS = {
    "account_billed": "Completed account billing history",
    "warehouse_bridge": "Warehouse metering bridge",
    "service_other": "Service and other account charges",
    "snowsight_reference": "Snowsight Admin Cost Management",
}


def _coerce_date(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def build_account_billing_reconciliation_sql(
    days_back: int = 7,
    *,
    credit_price: float | None = None,
    start_date: object = None,
    end_date: object = None,
    include_partial_current_day: bool = False,
) -> str:
    """Return account-level billed-credit SQL aligned to Snowsight totals.

    This intentionally uses account daily billing history as the primary total.
    Warehouse metering belongs in the bridge, not as the account total.
    """

    days_back = max(1, int(days_back or 7))
    price = float(credit_price if credit_price is not None else DEFAULTS["credit_price"])
    selected_start = _coerce_date(start_date)
    selected_end = _coerce_date(end_date)
    if selected_start and selected_end:
        start_literal = sql_literal(selected_start, 16)
        end_literal = sql_literal(selected_end, 16)
        window_filter = f"""
            usage_date >= TO_DATE({start_literal})
            AND usage_date <= TO_DATE({end_literal})
        """
    else:
        window_filter = f"""
            usage_date >= DATEADD('day', -{days_back}, CURRENT_DATE())
            AND usage_date < CURRENT_DATE()
        """
    if not include_partial_current_day:
        window_filter = f"""
            {window_filter}
            AND usage_date < CURRENT_DATE()
        """
    return f"""
        WITH account_daily AS (
            SELECT
                usage_date,
                UPPER(COALESCE(service_type, 'UNKNOWN')) AS service_type,
                SUM(COALESCE(credits_billed, credits_used, 0)) AS credits_billed,
                SUM(COALESCE(credits_used, 0)) AS credits_used,
                SUM(COALESCE(credits_used_compute, 0)) AS credits_used_compute,
                SUM(COALESCE(credits_used_cloud_services, 0)) AS credits_used_cloud_services,
                SUM(COALESCE(credits_adjustment_cloud_services, 0)) AS credits_adjustment_cloud_services,
                COUNT(*) AS billing_rows
            FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
            WHERE {window_filter}
            GROUP BY usage_date, UPPER(COALESCE(service_type, 'UNKNOWN'))
        ),
        service_breakdown AS (
            SELECT
                usage_date,
                service_type,
                credits_billed,
                credits_used,
                credits_used_compute,
                credits_used_cloud_services,
                credits_adjustment_cloud_services,
                credits_billed * {price:.6f} AS billed_cost_usd,
                billing_rows
            FROM account_daily
        )
        SELECT
            usage_date,
            service_type,
            credits_billed AS daily_credits,
            credits_billed,
            credits_used,
            credits_used_compute,
            credits_used_cloud_services,
            credits_adjustment_cloud_services,
            billed_cost_usd AS daily_spend_usd,
            billed_cost_usd,
            SUM(credits_billed) OVER () AS account_billed_credits,
            SUM(credits_billed * {price:.6f}) OVER () AS account_billed_cost_usd,
            SUM(credits_used) OVER () AS account_used_credits,
            SUM(credits_used_compute) OVER () AS compute_credits,
            SUM(COALESCE(credits_used_cloud_services, 0)) OVER () AS cloud_services_credits,
            SUM(COALESCE(credits_adjustment_cloud_services, 0)) OVER () AS cloud_services_adjustment,
            SUM(COALESCE(credits_adjustment_cloud_services, 0)) OVER () AS account_cloud_services_adjustment,
            MIN(usage_date) OVER () AS billing_reconciliation_window_start,
            MAX(usage_date) OVER () AS billing_reconciliation_window_end,
            COUNT(DISTINCT usage_date) OVER () AS observed_billing_days,
            'completed_account_billing_history' AS billing_reconciliation_freshness,
            'account_billing_primary' AS reconciliation_role
        FROM service_breakdown
        ORDER BY usage_date, service_type
    """


def build_warehouse_billing_bridge_sql(
    days_back: int = 7,
    company: str = "ALL",
    *,
    credit_price: float | None = None,
    start_date: object = None,
    end_date: object = None,
    company_filter_sql: str = "1=1",
) -> str:
    """Return warehouse-credit bridge SQL for account billing reconciliation."""

    days_back = max(1, int(days_back or 7))
    price = float(credit_price if credit_price is not None else DEFAULTS["credit_price"])
    selected_start = _coerce_date(start_date)
    selected_end = _coerce_date(end_date)
    if selected_start and selected_end:
        start_literal = sql_literal(f"{selected_start} 00:00:00", 32)
        end_literal = sql_literal(f"{selected_end} 00:00:00", 32)
        window_filter = f"""
            start_time >= TO_TIMESTAMP_NTZ({start_literal})
            AND start_time < LEAST(
                DATEADD('day', 1, TO_TIMESTAMP_NTZ({end_literal})),
                CURRENT_DATE()
            )
        """
    else:
        window_filter = f"""
            start_time >= DATEADD('day', -{days_back}, CURRENT_DATE())
            AND start_time < CURRENT_DATE()
        """
    scope_label = sql_literal(str(company or "ALL"), 80)
    return f"""
        SELECT
            DATE(start_time) AS usage_date,
            warehouse_name,
            {scope_label} AS company_scope,
            SUM(COALESCE(credits_used_compute, 0) + COALESCE(credits_used_cloud_services, 0)) AS warehouse_credits,
            SUM(COALESCE(credits_used_compute, 0) + COALESCE(credits_used_cloud_services, 0)) * {price:.6f} AS warehouse_cost_usd,
            SUM(COALESCE(credits_used_compute, 0)) AS compute_credits,
            SUM(COALESCE(credits_used_cloud_services, 0)) AS cloud_services_credits,
            COUNT(*) AS metering_rows,
            'warehouse_bridge_breakdown' AS reconciliation_role
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE {window_filter}
          AND ({company_filter_sql})
          AND COALESCE(warehouse_id, 0) > 0
          AND NULLIF(TRIM(warehouse_name), '') IS NOT NULL
        GROUP BY DATE(start_time), warehouse_name
        HAVING SUM(COALESCE(credits_used_compute, 0) + COALESCE(credits_used_cloud_services, 0)) > 0
        ORDER BY usage_date, warehouse_credits DESC, warehouse_name
    """


def _numeric_sum(frame: pd.DataFrame | None, *columns: str) -> float:
    if frame is None or frame.empty:
        return 0.0
    for column in columns:
        if column in frame.columns:
            return float(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())
    return 0.0


def _numeric_sum_where(frame: pd.DataFrame | None, mask: pd.Series, *columns: str) -> float:
    if frame is None or frame.empty:
        return 0.0
    filtered = frame.loc[mask]
    if filtered.empty:
        return 0.0
    return _numeric_sum(filtered, *columns)


def _first_value(frame: pd.DataFrame | None, *columns: str) -> Any:
    if frame is None or frame.empty:
        return None
    for column in columns:
        if column in frame.columns and not frame[column].empty:
            value = frame[column].dropna()
            if not value.empty:
                return value.iloc[0]
    return None


def _first_numeric(frame: pd.DataFrame | None, column: str) -> float | None:
    if frame is None or frame.empty or column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.iloc[0])


def summarize_billing_reconciliation(
    account_billing: pd.DataFrame | None,
    warehouse_bridge: pd.DataFrame | None,
    *,
    credit_price: float | None = None,
) -> dict[str, Any]:
    """Summarize account billed totals and warehouse bridge without double-counting."""

    price = float(credit_price if credit_price is not None else DEFAULTS["credit_price"])
    account_billed = _numeric_sum(account_billing, "CREDITS_BILLED", "DAILY_CREDITS")
    account_used = _numeric_sum(account_billing, "CREDITS_USED")
    account_billed = _first_numeric(account_billing, "ACCOUNT_BILLED_CREDITS") or account_billed
    account_used = _first_numeric(account_billing, "ACCOUNT_USED_CREDITS") or account_used
    account_cost = _numeric_sum(account_billing, "ACCOUNT_BILLED_COST_USD", "BILLED_COST_USD", "DAILY_SPEND_USD")
    account_cost = _first_numeric(account_billing, "ACCOUNT_BILLED_COST_USD") or account_cost
    if account_cost == 0.0 and account_billed:
        account_cost = round(account_billed * price, 2)
    adjustment = _numeric_sum(account_billing, "ACCOUNT_CLOUD_SERVICES_ADJUSTMENT", "CREDITS_ADJUSTMENT_CLOUD_SERVICES")
    compute_credits = _numeric_sum(account_billing, "COMPUTE_CREDITS", "CREDITS_USED_COMPUTE")
    cloud_services = _numeric_sum(account_billing, "CLOUD_SERVICES_CREDITS", "CREDITS_USED_CLOUD_SERVICES")
    cloud_adjustment = _numeric_sum(
        account_billing,
        "CLOUD_SERVICES_ADJUSTMENT",
        "ACCOUNT_CLOUD_SERVICES_ADJUSTMENT",
        "CREDITS_ADJUSTMENT_CLOUD_SERVICES",
    )
    cortex_mask = cortex_service_type_mask(account_billing)
    cortex_credits = _numeric_sum_where(account_billing, cortex_mask, "CORTEX_AI_CREDITS", "CREDITS_BILLED", "DAILY_CREDITS")
    cortex_cost = _numeric_sum_where(
        account_billing,
        cortex_mask,
        "CORTEX_AI_COST_USD",
        "BILLED_COST_USD",
        "DAILY_SPEND_USD",
    )
    if cortex_cost == 0.0 and cortex_credits:
        cortex_cost = round(cortex_credits * price, 2)
    warehouse_credits = _numeric_sum(warehouse_bridge, "WAREHOUSE_CREDITS", "DAILY_CREDITS")
    if warehouse_credits == 0.0 and warehouse_bridge is not None and not warehouse_bridge.empty:
        warehouse_credits = _numeric_sum(warehouse_bridge, "CREDITS_USED_COMPUTE") + _numeric_sum(
            warehouse_bridge,
            "CREDITS_USED_CLOUD_SERVICES",
        )
    warehouse_cost = _numeric_sum(warehouse_bridge, "WAREHOUSE_COST_USD", "DAILY_SPEND_USD")
    if warehouse_cost == 0.0 and warehouse_credits:
        warehouse_cost = round(warehouse_credits * price, 2)
    bridge_delta = account_billed - warehouse_credits
    service_other = max(bridge_delta, 0.0)
    service_other_cost = round(service_other * price, 2)
    bridge_delta_cost = round(bridge_delta * price, 2)
    window_start = _first_value(account_billing, "BILLING_RECONCILIATION_WINDOW_START", "USAGE_DATE", "usage_date")
    window_end = None
    if account_billing is not None and not account_billing.empty:
        for column in ("BILLING_RECONCILIATION_WINDOW_END", "USAGE_DATE", "usage_date"):
            if column in account_billing.columns:
                values = account_billing[column].dropna()
                if not values.empty:
                    window_end = values.max()
                    break
    observed_days = int(_numeric_sum(account_billing, "OBSERVED_BILLING_DAYS")) or (
        int(account_billing["USAGE_DATE"].nunique()) if account_billing is not None and "USAGE_DATE" in account_billing.columns else 0
    )
    if not (account_billed > 0 or observed_days > 0):
        status = "pending"
    elif abs(bridge_delta) <= 0.000001:
        status = "matched"
    elif bridge_delta > 0:
        status = "warehouse_lower_than_billed"
    else:
        status = "warehouse_higher_than_billed"
    window_start_text = "" if window_start is None else str(window_start)[:10]
    window_end_text = "" if window_end is None else str(window_end)[:10]
    latency_note = "Completed UTC billing days only; current partial day excluded by default."
    return {
        "ACCOUNT_BILLED_CREDITS": round(account_billed, 6),
        "ACCOUNT_BILLED_COST_USD": round(account_cost, 2),
        "ACCOUNT_USED_CREDITS": round(account_used, 6),
        "COMPUTE_CREDITS": round(compute_credits, 6),
        "CLOUD_SERVICES_CREDITS": round(cloud_services, 6),
        "CLOUD_SERVICES_ADJUSTMENT": round(cloud_adjustment, 6),
        "ACCOUNT_CLOUD_SERVICES_ADJUSTMENT": round(adjustment, 6),
        "WAREHOUSE_CREDITS": round(warehouse_credits, 6),
        "WAREHOUSE_COST_ESTIMATE_USD": round(warehouse_cost, 2),
        "WAREHOUSE_COST_USD": round(warehouse_cost, 2),
        "SERVICE_OTHER_CREDITS": round(service_other, 6),
        "SERVICE_OTHER_COST_USD": service_other_cost,
        "BILLING_BRIDGE_DELTA_CREDITS": round(bridge_delta, 6),
        "BILLING_BRIDGE_DELTA_USD": bridge_delta_cost,
        "BILLING_BRIDGE_STATUS": status,
        "CORTEX_AI_CREDITS": round(cortex_credits, 6),
        "CORTEX_AI_COST_USD": round(cortex_cost, 2),
        "BILLING_RECONCILIATION_STATUS": status,
        "BILLING_WINDOW_START": window_start_text,
        "BILLING_WINDOW_END": window_end_text,
        "BILLING_WINDOW_COMPLETE": bool(observed_days),
        "BILLING_SOURCE_FRESHNESS_TS": window_end_text,
        "BILLING_LATENCY_NOTE": latency_note,
        "BILLING_RECONCILIATION_WINDOW_START": window_start_text,
        "BILLING_RECONCILIATION_WINDOW_END": window_end_text,
        "BILLING_RECONCILIATION_FRESHNESS": "completed account billing history",
        "OBSERVED_BILLING_DAYS": observed_days,
        "WAREHOUSE_BRIDGE_IS_PRIMARY_TOTAL": False,
        "raw_sql_included": False,
    }


def daily_safe_billing_labels() -> Mapping[str, str]:
    return dict(DAILY_SAFE_BILLING_LABELS)


def billing_reconciliation_contract_results(summary: Mapping[str, Any]) -> dict[str, Any]:
    missing = [
        field
        for field in BILLING_RECONCILIATION_PACKET_FIELDS
        if field not in summary or summary.get(field) in (None, "")
    ]
    failures: list[dict[str, Any]] = []
    if missing:
        failures.append({"code": "BILLING_PACKET_FIELD_MISSING", "fields": missing})
    if bool(summary.get("WAREHOUSE_BRIDGE_IS_PRIMARY_TOTAL")):
        failures.append({"code": "WAREHOUSE_TOTAL_USED_AS_ACCOUNT_TOTAL"})
    status = str(summary.get("BILLING_RECONCILIATION_STATUS") or "")
    if (
        float(summary.get("ACCOUNT_BILLED_COST_USD") or 0) == 0
        and float(summary.get("CORTEX_AI_COST_USD") or 0) > 0
        and status != "pending"
    ):
        failures.append({"code": "ACCOUNT_TOTAL_ZERO_WITH_CORTEX_SPEND"})
    if status not in {
        "matched",
        "warehouse_lower_than_billed",
        "warehouse_higher_than_billed",
        "pending",
    }:
        failures.append({"code": "UNKNOWN_BILLING_RECONCILIATION_STATUS"})
    if str(summary.get("BILLING_BRIDGE_STATUS") or "") != str(summary.get("BILLING_RECONCILIATION_STATUS") or ""):
        failures.append({"code": "BILLING_BRIDGE_STATUS_MISMATCH"})
    return {
        "source": "billing_reconciliation_contract",
        "proof_source": "formula_recompute",
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "summary": dict(summary),
        "raw_sql_included": False,
    }


__all__ = [
    "BILLING_RECONCILIATION_PACKET_FIELDS",
    "DAILY_SAFE_BILLING_LABELS",
    "billing_reconciliation_contract_results",
    "build_account_billing_reconciliation_sql",
    "build_warehouse_billing_bridge_sql",
    "daily_safe_billing_labels",
    "summarize_billing_reconciliation",
]
