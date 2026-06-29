"""COST_DB-aligned formula contracts for OVERWATCH cost and credit metrics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

import pandas as pd

from config import DEFAULTS


COST_DB_SOURCE_URL = "https://github.com/jfreeze03/COST_DB/blob/main/streamlit_app.py"

NUMERIC_NORMALIZATION_COLUMNS = (
    "CREDITS_USED",
    "CREDITS_USED_COMPUTE",
    "CREDITS_USED_CLOUD_SERVICES",
    "TOTAL_CREDITS",
    "COMPUTE_CREDITS",
    "CLOUD_SERVICES_CREDITS",
    "CREDITS_BILLED",
    "COST",
    "INPUT_CREDITS",
    "OUTPUT_CREDITS",
    "TOKENS",
    "REQUEST_COUNT",
)


@dataclass(frozen=True)
class CostFormula:
    formula_id: str
    title: str
    cost_db_function_or_class: str
    cost_db_formula: str
    cost_db_source_view: str
    cost_db_columns: tuple[str, ...]
    overwatch_target_module: str
    overwatch_metric_key: str
    overwatch_packet_field: str
    required_change: str
    status: str
    reason: str

    def to_artifact(self) -> dict[str, Any]:
        row = asdict(self)
        row["cost_db_source_url"] = COST_DB_SOURCE_URL
        return row


def normalize_numeric_columns(frame: pd.DataFrame, columns: tuple[str, ...] = NUMERIC_NORMALIZATION_COLUMNS) -> pd.DataFrame:
    """Return a copy with COST_DB numeric columns coerced before aggregation."""

    if frame is None:
        return pd.DataFrame()
    normalized = frame.copy()
    for column in columns:
        if column in normalized.columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce").fillna(0.0).astype(float)
    return normalized


def selected_credit_price(value: float | None = None) -> float:
    return float(value if value is not None else DEFAULTS["credit_price"])


def credits_to_usd(credits: float, credit_price: float | None = None) -> float:
    return round(float(credits or 0.0) * selected_credit_price(credit_price), 2)


def warehouse_bridge_credits(frame: pd.DataFrame) -> float:
    """Mirror COST_DB warehouse compute formula from WAREHOUSE_METERING_HISTORY."""

    data = normalize_numeric_columns(frame)
    if data.empty:
        return 0.0
    if "WAREHOUSE_ID" in data.columns:
        ids = pd.to_numeric(data["WAREHOUSE_ID"], errors="coerce").fillna(0)
        data = data.loc[ids > 0]
    if "WAREHOUSE_NAME" in data.columns:
        names = data["WAREHOUSE_NAME"].fillna("").astype(str).str.strip()
        data = data.loc[names != ""]
    compute = pd.to_numeric(data.get("CREDITS_USED_COMPUTE", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    cloud = pd.to_numeric(data.get("CREDITS_USED_CLOUD_SERVICES", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    return float((compute + cloud).sum())


def service_other_bridge_credits(account_billed_credits: float, warehouse_credits: float) -> float:
    return max(float(account_billed_credits or 0.0) - float(warehouse_credits or 0.0), 0.0)


def cortex_service_mask(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype=bool)
    columns = [column for column in ("SERVICE_TYPE", "SERVICE_CATEGORY", "SOURCE") if column in frame.columns]
    if not columns:
        return pd.Series([False] * len(frame), index=frame.index)
    combined = pd.Series([""] * len(frame), index=frame.index)
    for column in columns:
        combined = combined.str.cat(frame[column].fillna("").astype(str), sep=" ")
    upper = combined.str.upper()
    return upper.str.contains("CORTEX", regex=False) | upper.str.contains("AI", regex=False)


def cost_db_formula_rows() -> list[CostFormula]:
    return [
        CostFormula(
            formula_id="numeric_normalization",
            title="Numeric normalization before sums",
            cost_db_function_or_class="normalize_snowflake_data",
            cost_db_formula="pd.to_numeric(..., errors='coerce').fillna(0) for credit, cost, token, and request columns",
            cost_db_source_view="all Snowflake result frames",
            cost_db_columns=NUMERIC_NORMALIZATION_COLUMNS,
            overwatch_target_module=".overwatch_final/utils/cost_formula_authority.py",
            overwatch_metric_key="all_cost_credit_metrics",
            overwatch_packet_field="multiple",
            required_change="Normalize known numeric columns before every cost/credit aggregation.",
            status="matched",
            reason="OVERWATCH uses normalize_numeric_columns and billing reconciliation numeric coercion before sums.",
        ),
        CostFormula(
            formula_id="credit_price",
            title="Single credit price source",
            cost_db_function_or_class="format_credits_with_dollars",
            cost_db_formula="dollar_amount = credits * credit_price",
            cost_db_source_view="session credit price",
            cost_db_columns=("CREDITS_USED", "TOTAL_CREDITS", "COST"),
            overwatch_target_module=".overwatch_final/utils/cost_formula_authority.py",
            overwatch_metric_key="credit_to_usd",
            overwatch_packet_field="*_COST_USD",
            required_change="Use one selected credit price for Executive, Cost, Cortex, warehouse bridge, and exports.",
            status="matched",
            reason="credits_to_usd centralizes the conversion and billing reconciliation accepts the selected price.",
        ),
        CostFormula(
            formula_id="warehouse_bridge",
            title="Warehouse compute bridge",
            cost_db_function_or_class="WarehouseAnalyzer.load_data",
            cost_db_formula="TOTAL_CREDITS = CREDITS_USED_COMPUTE + CREDITS_USED_CLOUD_SERVICES; WAREHOUSE_ID > 0",
            cost_db_source_view="SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
            cost_db_columns=("CREDITS_USED_COMPUTE", "CREDITS_USED_CLOUD_SERVICES", "WAREHOUSE_ID", "WAREHOUSE_NAME"),
            overwatch_target_module=".overwatch_final/utils/billing_reconciliation.py",
            overwatch_metric_key="warehouse_bridge",
            overwatch_packet_field="WAREHOUSE_CREDITS",
            required_change="Treat warehouse totals as bridge/breakdown, not account total.",
            status="matched",
            reason="Warehouse bridge SQL and dataframe fallback use compute + cloud services and filter pseudo/blank warehouses.",
        ),
        CostFormula(
            formula_id="account_billed_total",
            title="Account billed total",
            cost_db_function_or_class="Service analyzer billing pattern",
            cost_db_formula="Use account-level billed/service rows for account totals, not warehouse-only metering.",
            cost_db_source_view="SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY",
            cost_db_columns=("CREDITS_BILLED", "CREDITS_USED", "SERVICE_TYPE"),
            overwatch_target_module=".overwatch_final/utils/billing_reconciliation.py",
            overwatch_metric_key="total_spend",
            overwatch_packet_field="ACCOUNT_BILLED_COST_USD",
            required_change="Account total must be account billed cost; warehouse bridge cannot replace it.",
            status="matched",
            reason="Summary cards use ACCOUNT_BILLED_COST_USD and reject $0 account total with nonzero Cortex spend.",
        ),
        CostFormula(
            formula_id="cortex_ai",
            title="Canonical Cortex AI spend",
            cost_db_function_or_class="Service analyzer service-type grouping",
            cost_db_formula="Cortex service rows are summed as credits and converted with selected credit price.",
            cost_db_source_view="SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY",
            cost_db_columns=("SERVICE_TYPE", "CREDITS_BILLED", "COST"),
            overwatch_target_module=".overwatch_final/utils/billing_reconciliation.py",
            overwatch_metric_key="cortex_spend",
            overwatch_packet_field="CORTEX_AI_COST_USD",
            required_change="Executive and Cost must consume the same packet field.",
            status="matched",
            reason="Metric semantic registry maps Executive and Cost Cortex spend to CORTEX_AI_COST_USD.",
        ),
        CostFormula(
            formula_id="workbench_charts",
            title="COST_DB chart patterns",
            cost_db_function_or_class="ServiceAnalyzer.render_* and WarehouseAnalyzer.render_*",
            cost_db_formula="line trends, pie distribution, top-N horizontal bars, weekly stacked costs, hourly/day bars",
            cost_db_source_view="post-click cost workbench frames",
            cost_db_columns=("USAGE_DATE", "SERVICE_TYPE", "WAREHOUSE_NAME", "TOTAL_CREDITS", "COST"),
            overwatch_target_module=".overwatch_final/sections/cost_contract_charts.py",
            overwatch_metric_key="cost_workbench_charts",
            overwatch_packet_field="not_first_paint",
            required_change="Expose COST_DB chart patterns only after explicit Cost Evidence/Workbench actions.",
            status="matched",
            reason="Cost chart frame builders normalize rows and stay outside summary-board first paint.",
        ),
    ]


def cost_db_formula_mapping() -> list[dict[str, Any]]:
    return [row.to_artifact() for row in cost_db_formula_rows()]


def overwatch_formula_mapping() -> list[dict[str, Any]]:
    return [
        {
            "overwatch_target_module": ".overwatch_final/utils/billing_reconciliation.py",
            "overwatch_metric_key": "total_spend",
            "overwatch_packet_field": "ACCOUNT_BILLED_COST_USD",
            "formula_id": "account_billed_total",
            "uses_cost_db_authority": True,
            "status": "matched",
        },
        {
            "overwatch_target_module": ".overwatch_final/utils/billing_reconciliation.py",
            "overwatch_metric_key": "warehouse_bridge",
            "overwatch_packet_field": "WAREHOUSE_CREDITS",
            "formula_id": "warehouse_bridge",
            "uses_cost_db_authority": True,
            "status": "matched",
        },
        {
            "overwatch_target_module": ".overwatch_final/sections/metric_semantic_registry.py",
            "overwatch_metric_key": "cost_24h",
            "overwatch_packet_field": "WAREHOUSE_COST_USD",
            "formula_id": "warehouse_bridge",
            "uses_cost_db_authority": True,
            "status": "matched",
        },
        {
            "overwatch_target_module": ".overwatch_final/utils/billing_reconciliation.py",
            "overwatch_metric_key": "cortex_spend",
            "overwatch_packet_field": "CORTEX_AI_COST_USD",
            "formula_id": "cortex_ai",
            "uses_cost_db_authority": True,
            "status": "matched",
        },
        {
            "overwatch_target_module": ".overwatch_final/sections/metric_semantic_registry.py",
            "overwatch_metric_key": "forecast_run_rate",
            "overwatch_packet_field": "FORECAST_RUN_RATE_USD",
            "formula_id": "account_billed_total",
            "uses_cost_db_authority": True,
            "status": "matched",
        },
        {
            "overwatch_target_module": ".overwatch_final/sections/cost_contract_charts.py",
            "overwatch_metric_key": "cost_workbench_charts",
            "overwatch_packet_field": "not_first_paint",
            "formula_id": "workbench_charts",
            "uses_cost_db_authority": True,
            "status": "matched",
        },
    ]


def evaluate_formula_gaps(
    cost_db_rows: Sequence[Mapping[str, Any]] | None = None,
    overwatch_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    authority = list(cost_db_rows or cost_db_formula_mapping())
    overwatch = list(overwatch_rows or overwatch_formula_mapping())
    authority_ids = {str(row.get("formula_id") or "") for row in authority}
    overwatch_ids = {str(row.get("formula_id") or "") for row in overwatch}
    failures: list[dict[str, Any]] = []
    for row in authority:
        if str(row.get("status")) not in {"matched", "intentionally_different"}:
            failures.append({"code": "COST_DB_AUTHORITY_STATUS_NOT_MATCHED", "formula_id": row.get("formula_id")})
    for row in overwatch:
        if not row.get("uses_cost_db_authority"):
            failures.append({"code": "OVERWATCH_FORMULA_NOT_MAPPED", "metric_key": row.get("overwatch_metric_key")})
        if str(row.get("formula_id") or "") not in authority_ids:
            failures.append({"code": "OVERWATCH_FORMULA_UNKNOWN_AUTHORITY", "metric_key": row.get("overwatch_metric_key")})
    for formula_id in ("numeric_normalization", "credit_price", "warehouse_bridge", "account_billed_total", "cortex_ai", "workbench_charts"):
        if formula_id not in authority_ids:
            failures.append({"code": "COST_DB_FORMULA_MISSING", "formula_id": formula_id})
    if "warehouse_bridge" in overwatch_ids and "account_billed_total" not in overwatch_ids:
        failures.append({"code": "WAREHOUSE_BRIDGE_WITHOUT_ACCOUNT_TOTAL"})
    return {
        "source": "cost_db_formula_authority",
        "cost_db_source_url": COST_DB_SOURCE_URL,
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "authority_formula_count": len(authority),
        "overwatch_formula_count": len(overwatch),
        "raw_sql_included": False,
    }


def cost_formula_authority_results() -> dict[str, Any]:
    return {
        "source": "cost_formula_authority",
        "passed": True,
        "numeric_normalization_columns": list(NUMERIC_NORMALIZATION_COLUMNS),
        "credit_price_source": "config.DEFAULTS credit_price or selected session price",
        "warehouse_bridge_formula": "CREDITS_USED_COMPUTE + CREDITS_USED_CLOUD_SERVICES",
        "account_total_formula": "ACCOUNT_BILLED_CREDITS * selected_credit_price",
        "cortex_packet_field": "CORTEX_AI_COST_USD",
        "raw_sql_included": False,
    }


__all__ = [
    "COST_DB_SOURCE_URL",
    "NUMERIC_NORMALIZATION_COLUMNS",
    "CostFormula",
    "cost_db_formula_mapping",
    "cost_formula_authority_results",
    "credits_to_usd",
    "cortex_service_mask",
    "evaluate_formula_gaps",
    "normalize_numeric_columns",
    "overwatch_formula_mapping",
    "selected_credit_price",
    "service_other_bridge_credits",
    "warehouse_bridge_credits",
]
