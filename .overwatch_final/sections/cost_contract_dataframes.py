"""Pure Cost & Contract dataframe helpers.

These helpers shape already-loaded telemetry for charts and decision tables.
They intentionally do not render Streamlit UI, mutate session state, or run
Snowflake SQL.
"""

from __future__ import annotations

import pandas as pd

from utils.cost import credits_to_dollars
from utils.primitives import safe_float, safe_int


def _short_label(value: object, limit: int = 28) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def _looks_like_frame(value) -> bool:
    """Return True for dataframe-like values without importing pandas in callers."""
    return hasattr(value, "empty") and hasattr(value, "iloc") and hasattr(value, "columns")


def _has_columns(df: pd.DataFrame, columns: list[str]) -> bool:
    return isinstance(df, pd.DataFrame) and not df.empty and all(col in df.columns for col in columns)


def _loaded_rows(frame: pd.DataFrame | None) -> int:
    return int(len(frame)) if isinstance(frame, pd.DataFrame) and not frame.empty else 0


def _slide_money(value: float, *, signed: bool = False) -> str:
    amount = safe_float(value)
    if signed:
        sign = "+" if amount >= 0 else "-"
        return f"{sign}${abs(amount):,.0f}"
    return f"${amount:,.0f}"


def _cost_spend_trend_rows(trend: pd.DataFrame | None, credit_price: float) -> pd.DataFrame:
    if not _looks_like_frame(trend) or trend.empty or not {"USAGE_DATE", "DAILY_CREDITS"}.issubset(set(trend.columns)):
        return pd.DataFrame(columns=["USAGE_DATE", "DAILY_CREDITS", "SPEND_USD", "ROLLING_SPEND_USD"])

    columns = ["USAGE_DATE", "DAILY_CREDITS"]
    if "DAILY_SPEND_USD" in trend.columns:
        columns.append("DAILY_SPEND_USD")
    rows = trend[columns].copy()
    rows["USAGE_DATE"] = pd.to_datetime(rows["USAGE_DATE"], errors="coerce")
    rows["DAILY_CREDITS"] = pd.to_numeric(rows["DAILY_CREDITS"], errors="coerce").fillna(0)
    if "DAILY_SPEND_USD" in rows.columns:
        rows["SPEND_USD"] = pd.to_numeric(rows["DAILY_SPEND_USD"], errors="coerce").fillna(0)
        rows = rows.drop(columns=["DAILY_SPEND_USD"])
    else:
        rows["SPEND_USD"] = rows["DAILY_CREDITS"].apply(
            lambda value: credits_to_dollars(safe_float(value), credit_price)
        )
    rows = rows.dropna(subset=["USAGE_DATE"]).sort_values("USAGE_DATE")
    if rows.empty:
        return rows
    rows["ROLLING_SPEND_USD"] = rows["SPEND_USD"].rolling(
        window=min(7, max(1, len(rows))),
        min_periods=1,
    ).mean()
    return rows


def _cost_warehouse_ranking_rows(
    warehouse_delta: pd.DataFrame | None,
    credit_price: float,
    *,
    limit: int = 8,
) -> pd.DataFrame:
    required = {"WAREHOUSE_NAME", "CURRENT_CREDITS"}
    if (
        not _looks_like_frame(warehouse_delta)
        or warehouse_delta.empty
        or not required.issubset(set(warehouse_delta.columns))
    ):
        return pd.DataFrame(
            columns=[
                "WAREHOUSE_NAME", "CURRENT_CREDITS", "PRIOR_CREDITS", "CREDIT_DELTA",
                "CURRENT_SPEND_USD", "PRIOR_SPEND_USD", "DELTA_SPEND_USD", "CURRENT_SPEND_LABEL",
            ]
        )

    rows = warehouse_delta.copy()
    for column in ("CURRENT_CREDITS", "PRIOR_CREDITS", "CREDIT_DELTA", "PCT_DELTA"):
        if column not in rows.columns:
            rows[column] = 0
        rows[column] = pd.to_numeric(rows[column], errors="coerce").fillna(0)
    rows["CURRENT_SPEND_USD"] = rows["CURRENT_CREDITS"].apply(
        lambda value: credits_to_dollars(safe_float(value), credit_price)
    )
    rows["PRIOR_SPEND_USD"] = rows["PRIOR_CREDITS"].apply(
        lambda value: credits_to_dollars(safe_float(value), credit_price)
    )
    rows["DELTA_SPEND_USD"] = rows["CREDIT_DELTA"].apply(
        lambda value: credits_to_dollars(safe_float(value), credit_price)
    )
    rows["WAREHOUSE_NAME"] = rows["WAREHOUSE_NAME"].astype(str)
    rows["CURRENT_SPEND_LABEL"] = rows["CURRENT_SPEND_USD"].apply(lambda value: f"${safe_float(value):,.0f}")
    rows["DELTA_SPEND_LABEL"] = rows["DELTA_SPEND_USD"].apply(lambda value: _slide_money(value, signed=True))
    return rows.sort_values(["CURRENT_SPEND_USD", "DELTA_SPEND_USD"], ascending=[False, False]).head(limit)


def _service_lens_movement_rows(service_lens: pd.DataFrame | None, credit_price: float, limit: int = 8) -> pd.DataFrame:
    columns = [
        "SERVICE_CATEGORY", "SERVICE_TYPE", "CURRENT_SPEND_USD", "PRIOR_SPEND_USD",
        "COST_DELTA_USD", "CREDIT_DELTA", "DELTA_LABEL", "SORT_VALUE",
    ]
    if not _looks_like_frame(service_lens) or service_lens.empty:
        return pd.DataFrame(columns=columns)

    view = service_lens.copy()
    if "SERVICE_TYPE" not in view.columns:
        return pd.DataFrame(columns=columns)
    for column in ("SERVICE_CATEGORY",):
        if column not in view.columns:
            view[column] = "Other"

    def numeric_column(name: str) -> pd.Series:
        return pd.to_numeric(view.get(name, pd.Series([0] * len(view), index=view.index)), errors="coerce").fillna(0)

    current_credits = numeric_column("CREDITS_BILLED")
    prior_credits = numeric_column("CREDITS_BILLED_PRIOR")
    credit_delta = numeric_column("CREDIT_DELTA")
    current_spend = numeric_column("ESTIMATED_COST_USD")
    prior_spend = numeric_column("PRIOR_ESTIMATED_COST_USD")
    cost_delta = numeric_column("COST_DELTA_USD")

    current_spend = current_spend.where(current_spend.abs() > 0, current_credits * safe_float(credit_price, 3.68))
    prior_spend = prior_spend.where(prior_spend.abs() > 0, prior_credits * safe_float(credit_price, 3.68))
    cost_delta = cost_delta.where(cost_delta.abs() > 0, current_spend - prior_spend)
    credit_delta = credit_delta.where(credit_delta.abs() > 0, current_credits - prior_credits)

    movement = pd.DataFrame({
        "SERVICE_CATEGORY": view["SERVICE_CATEGORY"].fillna("Other").astype(str),
        "SERVICE_TYPE": view["SERVICE_TYPE"].fillna("Unknown").astype(str),
        "CURRENT_SPEND_USD": current_spend,
        "PRIOR_SPEND_USD": prior_spend,
        "COST_DELTA_USD": cost_delta,
        "CREDIT_DELTA": credit_delta,
    })
    movement["DELTA_LABEL"] = movement["COST_DELTA_USD"].apply(lambda value: _slide_money(value, signed=True))
    movement["SORT_VALUE"] = movement["COST_DELTA_USD"].abs()
    movement = movement[
        (movement["CURRENT_SPEND_USD"].abs() + movement["PRIOR_SPEND_USD"].abs() + movement["COST_DELTA_USD"].abs()) > 0
    ].sort_values(["SORT_VALUE", "CURRENT_SPEND_USD"], ascending=[False, False])
    return movement.head(max(1, int(limit or 8)))[columns].reset_index(drop=True)


def _cost_column(frame: pd.DataFrame, candidates: list[str]) -> str:
    if frame is None or getattr(frame, "empty", True):
        return ""
    columns = {str(col).upper(): str(col) for col in frame.columns}
    for candidate in candidates:
        column = columns.get(str(candidate).upper())
        if column:
            return column
    return ""


def _cost_metric_column(frame: pd.DataFrame) -> str:
    return _cost_column(
        frame,
        [
            "EST_COST", "COST_USD", "ESTIMATED_COST_USD", "TOTAL_COST_USD",
            "TOTAL_CREDITS", "ALLOCATED_CREDITS", "CREDITS_USED", "CREDITS",
        ],
    )


def _cost_metric_to_usd(metric_column: str, value: float, credit_price: float) -> float:
    metric = str(metric_column or "").upper()
    if "USD" in metric or "COST" in metric:
        return safe_float(value)
    return credits_to_dollars(safe_float(value), credit_price)


def _top_loaded_cost_driver(
    frame: pd.DataFrame,
    dimensions: list[str],
    *,
    credit_price: float,
) -> dict:
    dim = _cost_column(frame, dimensions)
    metric = _cost_metric_column(frame)
    if not dim or not metric or frame is None or getattr(frame, "empty", True):
        return {
            "dimension": "",
            "entity": "",
            "metric": "",
            "value": 0.0,
            "value_usd": 0.0,
            "rows": 0,
        }
    work = frame[[dim, metric]].copy()
    work[dim] = work[dim].fillna("").astype(str).str.strip()
    work = work[work[dim].ne("")]
    if work.empty:
        return {
            "dimension": dim,
            "entity": "",
            "metric": metric,
            "value": 0.0,
            "value_usd": 0.0,
            "rows": 0,
        }
    work[metric] = pd.to_numeric(work[metric], errors="coerce").fillna(0.0)
    grouped = work.groupby(dim, dropna=False, as_index=False).agg(
        VALUE=(metric, "sum"),
        ROWS=(metric, "size"),
    )
    grouped = grouped.sort_values(["VALUE", "ROWS"], ascending=[False, False])
    row = grouped.iloc[0]
    value = safe_float(row.get("VALUE"))
    return {
        "dimension": dim,
        "entity": str(row.get(dim) or "").strip(),
        "metric": metric,
        "value": value,
        "value_usd": round(_cost_metric_to_usd(metric, value, credit_price), 2),
        "rows": safe_int(row.get("ROWS")),
    }
