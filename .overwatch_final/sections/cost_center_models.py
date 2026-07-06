"""Cost Center dataframe and allocation model helpers."""
from __future__ import annotations

import pandas as pd

from config import ALFA_DEV_DATABASES, TREXIS_DEV_DATABASES, TREXIS_PROD_DATABASES
from sections.cost_center_contracts import COST_EXPLORER_LENS_COLUMNS, NO_DATABASE_CONTEXT_VALUES
from utils import credits_to_dollars, safe_float


def _row_text(row, *columns: str) -> str:
    """Read a row value using Snowflake/Pandas column casing defensively."""
    if row is None:
        return ""
    keys = []
    for column in columns:
        keys.extend([column, column.upper(), column.lower(), column.title()])
    for key in keys:
        try:
            if key in row:
                value = row.get(key)
                if pd.notna(value):
                    return str(value).strip()
        except Exception:
            continue
    return ""


def _environment_rollup_for_cost(row) -> str:
    """Return the DBA chargeback rollup for a database-scoped cost row."""
    env = _row_text(row, "ENVIRONMENT").upper()
    db = _row_text(row, "DATABASE_NAME").upper()
    if db in NO_DATABASE_CONTEXT_VALUES or env in NO_DATABASE_CONTEXT_VALUES:
        return "No Database Context"
    if db == "ALFA_EDW_PRD" or db in TREXIS_PROD_DATABASES or env == "PROD":
        return "PROD"
    if (
        db in ALFA_DEV_DATABASES
        or db in TREXIS_DEV_DATABASES
        or env in ALFA_DEV_DATABASES
        or env in TREXIS_DEV_DATABASES
        or env == "DEV_ALL"
    ):
        return "DEV_ALL"
    if db.startswith("ALFA_EDW_") or env == "OTHER ALFA NON-PROD":
        return "Other ALFA Non-Prod"
    if db.startswith("TRXS_"):
        return "Trexis"
    return "Other / Shared"


def _cost_allocation_quality(row) -> dict:
    """Describe whether a cost row is safe for chargeback or only directional."""
    db = _row_text(row, "DATABASE_NAME").upper()
    company = _row_text(row, "COMPANY").upper()
    rollup = _environment_rollup_for_cost(row)
    owner_source = _row_text(row, "OWNER_SOURCE").upper()
    cost_owner = _row_text(row, "COST_OWNER")
    has_owner_tag = "TAG" in owner_source and bool(cost_owner)

    if db in NO_DATABASE_CONTEXT_VALUES or rollup == "No Database Context":
        return {
            "ENVIRONMENT_ROLLUP": "No Database Context",
            "ALLOCATION_CONFIDENCE": "Account-wide / Shared",
            "ALLOCATION_BASIS": "No database context; do not split PROD/DEV without tags or session lineage.",
            "CHARGEBACK_READY": "No",
            "SCOPE_REVIEW": "Missing database context",
        }
    if rollup in {"PROD", "DEV_ALL"}:
        return {
            "ENVIRONMENT_ROLLUP": rollup,
            "ALLOCATION_CONFIDENCE": "Allocated / Estimated",
            "ALLOCATION_BASIS": (
                "Query database context allocated across metered warehouse-hour credits; route-tag telemetry is attached."
                if has_owner_tag
                else "Query database context allocated across metered warehouse-hour credits."
            ),
            "CHARGEBACK_READY": "Ready" if has_owner_tag else "Directional",
            "SCOPE_REVIEW": "None",
        }
    if rollup == "Trexis" and company in {"TREXIS", "ALL", ""}:
        return {
            "ENVIRONMENT_ROLLUP": rollup,
            "ALLOCATION_CONFIDENCE": "Allocated / Estimated",
            "ALLOCATION_BASIS": (
                "Trexis database context allocated across metered warehouse-hour credits; route-tag telemetry is attached."
                if has_owner_tag
                else "Trexis database context allocated across metered warehouse-hour credits."
            ),
            "CHARGEBACK_READY": "Ready" if has_owner_tag else "Directional",
            "SCOPE_REVIEW": "None",
        }
    if rollup == "Other ALFA Non-Prod":
        return {
            "ENVIRONMENT_ROLLUP": rollup,
            "ALLOCATION_CONFIDENCE": "Allocated / Estimated",
            "ALLOCATION_BASIS": "ALFA database context exists, but the environment is outside the reviewed PROD/DEV family.",
            "CHARGEBACK_READY": "Review",
            "SCOPE_REVIEW": "Unmapped ALFA environment",
        }
    return {
        "ENVIRONMENT_ROLLUP": rollup,
            "ALLOCATION_CONFIDENCE": "Shared / Needs route",
            "ALLOCATION_BASIS": "Database context is shared, external, or unmapped; route telemetry is required before chargeback.",
        "CHARGEBACK_READY": "Review",
        "SCOPE_REVIEW": "Shared or unmapped database",
    }


def _annotate_allocation_quality(df: pd.DataFrame) -> pd.DataFrame:
    """Add DBA chargeback rollup and allocation-source columns to cost attribution rows."""
    if df is None or df.empty:
        return df
    annotated = df.copy()
    quality = pd.DataFrame(
        [_cost_allocation_quality(row) for _, row in annotated.iterrows()],
        index=annotated.index,
    )
    for column in quality.columns:
        annotated[column] = quality[column]
    if "COST_OWNER" not in annotated.columns:
        annotated["COST_OWNER"] = annotated.apply(
            lambda row: (
                _row_text(row, "USER_NAME")
                if _row_text(row, "USER_NAME").upper() not in {"", "UNKNOWN USER", "UNKNOWN_USER"}
                else "DBA / Cost owner"
            ),
            axis=1,
        )
    if "OWNER_SOURCE" not in annotated.columns:
        annotated["OWNER_SOURCE"] = annotated.apply(
            lambda row: (
                "QUERY_USER"
                if _row_text(row, "USER_NAME").upper() not in {"", "UNKNOWN USER", "UNKNOWN_USER"}
                else "MISSING_ROUTE"
            ),
            axis=1,
        )
    if "OWNER_EVIDENCE" not in annotated.columns:
        annotated["OWNER_EVIDENCE"] = annotated.apply(
            lambda row: (
                "Query user present; review route/tag telemetry before billing."
                if _row_text(row, "OWNER_SOURCE").upper() == "QUERY_USER"
                else "No query user route telemetry; shared/unallocated review required."
            ),
            axis=1,
        )
    return annotated


def _prepare_cost_forecast_rows(df_fc: pd.DataFrame | None, *, today: object | None = None) -> pd.DataFrame:
    """Return a complete 30-day forecast window with timezone-safe day keys."""
    end_day = pd.Timestamp(today) if today is not None else pd.Timestamp.today()
    if end_day.tzinfo is not None:
        end_day = end_day.tz_convert(None)
    end_day = end_day.normalize()
    full_window = pd.DataFrame({
        "DAY": pd.date_range(
            end_day - pd.Timedelta(days=29),
            end_day,
            freq="D",
        )
    })
    full_window["DAY"] = pd.to_datetime(full_window["DAY"], errors="coerce").dt.normalize()

    if df_fc is None or df_fc.empty:
        full_window["DAILY_CREDITS"] = 0.0
        return full_window

    rows = df_fc.copy()
    day_col = next((col for col in rows.columns if str(col).upper() == "DAY"), None)
    credit_col = next((col for col in rows.columns if str(col).upper() == "DAILY_CREDITS"), None)
    if day_col is None or credit_col is None:
        full_window["DAILY_CREDITS"] = 0.0
        return full_window

    rows["DAY"] = (
        pd.to_datetime(rows[day_col], errors="coerce", utc=True)
        .dt.tz_convert(None)
        .dt.normalize()
    )
    rows["DAILY_CREDITS"] = pd.to_numeric(rows[credit_col], errors="coerce").fillna(0)
    rows = (
        rows.dropna(subset=["DAY"])
        .groupby("DAY", as_index=False)["DAILY_CREDITS"]
        .sum()
    )
    merged = full_window.merge(rows, on="DAY", how="left")
    merged["DAILY_CREDITS"] = pd.to_numeric(merged["DAILY_CREDITS"], errors="coerce").fillna(0)
    return merged


def _annual_service_projection_metrics(data: pd.DataFrame, period_days: int) -> dict:
    """Calculate an annual projection from observed YTD service-metering days."""
    if data is None or data.empty or "USAGE_DATE" not in data.columns or "DAILY_CREDITS" not in data.columns:
        return {}
    rows = data.copy()
    rows["USAGE_DATE"] = pd.to_datetime(rows["USAGE_DATE"], errors="coerce")
    rows["DAILY_CREDITS"] = pd.to_numeric(rows["DAILY_CREDITS"], errors="coerce").fillna(0)
    rows = rows.dropna(subset=["USAGE_DATE"]).sort_values("USAGE_DATE")
    if rows.empty:
        return {}

    latest_date = rows["USAGE_DATE"].max().normalize()
    recent_cutoff = latest_date - pd.Timedelta(days=max(1, int(period_days)))
    recent = rows[rows["USAGE_DATE"] >= recent_cutoff]
    if recent.empty:
        return {}

    ytd_actual = float(rows["DAILY_CREDITS"].sum())
    daily_average = float(recent["DAILY_CREDITS"].mean())
    year_end = pd.Timestamp(latest_date.year, 12, 31)
    days_remaining = max(int((year_end - latest_date).days), 0)
    projected_remaining = daily_average * days_remaining
    projected_total = ytd_actual + projected_remaining
    return {
        "YTD_ACTUAL_CREDITS": ytd_actual,
        "RECENT_DAILY_AVG_CREDITS": daily_average,
        "PROJECTED_REMAINING_CREDITS": projected_remaining,
        "PROJECTED_YEAR_CREDITS": projected_total,
        "DAYS_REMAINING": days_remaining,
        "OBSERVED_DAYS_USED": int(len(recent)),
        "LATEST_USAGE_DATE": latest_date.date().isoformat(),
    }


def _mixed_label(values, *, default: str = "Unknown") -> str:
    cleaned = [str(value).strip() for value in values if str(value or "").strip()]
    unique = sorted(set(cleaned))
    if not unique:
        return default
    return unique[0] if len(unique) == 1 else "Mixed"


def _chargeback_readiness_label(values) -> str:
    cleaned = {str(value).strip().upper() for value in values if str(value or "").strip()}
    if not cleaned:
        return "Unknown"
    if "NO" in cleaned:
        return "Review Required"
    if "REVIEW" in cleaned:
        return "Review"
    if cleaned == {"READY"}:
        return "Ready"
    if cleaned == {"DIRECTIONAL"}:
        return "Directional"
    return "Mixed"


def _route_telemetry_label(values) -> str:
    cleaned = {str(value).strip().upper() for value in values if str(value or "").strip()}
    if not cleaned:
        return "Missing"
    if any("TAG" in value for value in cleaned):
        return "Tag Telemetry"
    if cleaned == {"QUERY_USER"}:
        return "Query User Only"
    if "MISSING_OWNER" in cleaned or "MISSING_ROUTE" in cleaned:
        return "Missing"
    return "Mixed"


def _cost_explorer_dimension_columns(lens: str) -> list[str]:
    return COST_EXPLORER_LENS_COLUMNS.get(str(lens or ""), ["WAREHOUSE_NAME"])


def _cost_explorer_dimension_label(row, columns: list[str]) -> str:
    parts = []
    for column in columns:
        value = _row_text(row, column)
        parts.append(value if value else "Unassigned")
    return " / ".join(parts)


def _normalize_cost_explorer_detail(df: pd.DataFrame, credit_price: float) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    detail = df.copy()
    detail.columns = [str(col).upper() for col in detail.columns]
    env_rollup_missing = "ENVIRONMENT_ROLLUP" not in detail.columns
    defaults = {
        "COMPANY": "Unassigned",
        "ENVIRONMENT": "No Database Context",
        "ENVIRONMENT_ROLLUP": "No Database Context",
        "DATABASE_NAME": "NO_DATABASE_CONTEXT",
        "USER_NAME": "Unknown user",
        "ROLE_NAME": "Unknown role",
        "WAREHOUSE_NAME": "Unknown warehouse",
        "WAREHOUSE_SIZE": "",
        "DEPARTMENT": "",
        "COST_OWNER": "",
        "OWNER_SOURCE": "",
        "OWNER_EVIDENCE": "",
        "ALLOCATION_CONFIDENCE": "",
        "ALLOCATION_BASIS": "",
        "CHARGEBACK_READY": "",
        "SCOPE_REVIEW": "",
        "QUERY_COUNT": 0,
        "TOTAL_CREDITS": 0.0,
        "EST_COST": 0.0,
    }
    for column, default in defaults.items():
        if column not in detail.columns:
            detail[column] = default
    detail["TOTAL_CREDITS"] = pd.to_numeric(detail["TOTAL_CREDITS"], errors="coerce").fillna(0.0)
    if "EST_COST" not in detail.columns or pd.to_numeric(detail["EST_COST"], errors="coerce").fillna(0).sum() == 0:
        detail["EST_COST"] = detail["TOTAL_CREDITS"].apply(lambda x: credits_to_dollars(x, credit_price))
    else:
        detail["EST_COST"] = pd.to_numeric(detail["EST_COST"], errors="coerce").fillna(0.0)
    detail["QUERY_COUNT"] = pd.to_numeric(detail["QUERY_COUNT"], errors="coerce").fillna(0).astype(int)
    detail["ACTIVE_DAYS"] = pd.to_numeric(detail["ACTIVE_DAYS"], errors="coerce").fillna(0).astype(int)
    detail["DEPARTMENT"] = detail.apply(
        lambda row: (
            _row_text(row, "DEPARTMENT")
            or _row_text(row, "COST_OWNER")
            or "Unassigned"
        ),
        axis=1,
    )
    if env_rollup_missing:
        detail["ENVIRONMENT_ROLLUP"] = detail.apply(_environment_rollup_for_cost, axis=1)
    else:
        detail["ENVIRONMENT_ROLLUP"] = detail.apply(
            lambda row: _row_text(row, "ENVIRONMENT_ROLLUP") or _environment_rollup_for_cost(row),
            axis=1,
        )
    detail = _annotate_allocation_quality(detail)
    return detail


def _cost_explorer_summary(detail: pd.DataFrame, lens: str) -> pd.DataFrame:
    if detail is None or detail.empty:
        return pd.DataFrame()
    columns = _cost_explorer_dimension_columns(lens)
    for column in columns:
        if column not in detail.columns:
            detail[column] = "Unassigned"
    for column in ("FIRST_USAGE_DATE", "LAST_USAGE_DATE"):
        if column not in detail.columns:
            detail[column] = ""
    if "ACTIVE_DAYS" not in detail.columns:
        detail["ACTIVE_DAYS"] = 0
    summary = (
        detail.groupby(columns, dropna=False)
        .agg(
            TOTAL_CREDITS=("TOTAL_CREDITS", "sum"),
            EST_COST=("EST_COST", "sum"),
            QUERY_COUNT=("QUERY_COUNT", "sum"),
            ACTIVE_DAYS=("ACTIVE_DAYS", "max"),
            USERS=("USER_NAME", "nunique"),
            ROLES=("ROLE_NAME", "nunique"),
            WAREHOUSES=("WAREHOUSE_NAME", "nunique"),
            DATABASES=("DATABASE_NAME", "nunique"),
            ENVIRONMENTS=("ENVIRONMENT_ROLLUP", "nunique"),
            ALLOCATION_CONFIDENCE=("ALLOCATION_CONFIDENCE", _mixed_label),
            CHARGEBACK_READY=("CHARGEBACK_READY", _chargeback_readiness_label),
            ROUTE_TELEMETRY=("OWNER_SOURCE", _route_telemetry_label),
            FIRST_USAGE_DATE=("FIRST_USAGE_DATE", "min"),
            LAST_USAGE_DATE=("LAST_USAGE_DATE", "max"),
        )
        .reset_index()
    )
    total_cost = max(float(summary["EST_COST"].sum()), 0.01)
    summary["PCT_OF_COST"] = (summary["EST_COST"] / total_cost * 100).round(1)
    summary["DIMENSION"] = summary.apply(lambda row: _cost_explorer_dimension_label(row, columns), axis=1)
    summary["EST_COST"] = summary["EST_COST"].round(2)
    summary["TOTAL_CREDITS"] = summary["TOTAL_CREDITS"].round(4)
    return summary.sort_values(["EST_COST", "TOTAL_CREDITS", "QUERY_COUNT"], ascending=[False, False, False])


def _cost_explorer_gap_board(detail: pd.DataFrame, lens_summary: pd.DataFrame) -> pd.DataFrame:
    if detail is None or detail.empty:
        return pd.DataFrame()

    def _gap_row(gap: str, mask: pd.Series, action: str) -> dict:
        scoped = detail[mask].copy()
        if scoped.empty:
            return {
                "GAP": gap,
                "STATE": "Clear",
                "ROWS": 0,
                "EST_COST": 0.0,
                "TOP_DRIVER": "None",
                "ACTION": "No action needed for the loaded scope.",
            }
        top = scoped.sort_values("EST_COST", ascending=False).iloc[0]
        top_driver = (
            _row_text(top, "WAREHOUSE_NAME")
            or _row_text(top, "DATABASE_NAME")
            or _row_text(top, "USER_NAME")
            or "Unknown"
        )
        return {
            "GAP": gap,
            "STATE": "Action Needed",
            "ROWS": len(scoped),
            "EST_COST": round(float(scoped["EST_COST"].sum()), 2),
            "TOP_DRIVER": top_driver,
            "ACTION": action,
        }

    dept = detail["DEPARTMENT"].fillna("").astype(str).str.upper()
    owner_source = detail["OWNER_SOURCE"].fillna("").astype(str).str.upper()
    readiness = detail["CHARGEBACK_READY"].fillna("").astype(str).str.upper()
    confidence = detail["ALLOCATION_CONFIDENCE"].fillna("").astype(str).str.upper()
    database = detail["DATABASE_NAME"].fillna("").astype(str).str.upper()
    no_context = database.isin(NO_DATABASE_CONTEXT_VALUES) | detail["ENVIRONMENT_ROLLUP"].fillna("").astype(str).str.upper().eq("NO DATABASE CONTEXT")
    rows = [
        _gap_row(
            "Missing department / cost-center telemetry",
            dept.isin({"", "UNASSIGNED", "UNKNOWN", "NONE", "NULL"}) | ~owner_source.str.contains("TAG", na=False),
            "Tag warehouses with COST_CENTER or DEPARTMENT and keep escalation routing current.",
        ),
        _gap_row(
            "No database context",
            no_context,
            "Do not split PROD/DEV or bill a database route until query tag, session lineage, or route telemetry exists.",
        ),
        _gap_row(
            "Not chargeback ready",
            readiness.isin({"NO", "REVIEW", "DIRECTIONAL", "MIXED", ""}),
            "Resolve route telemetry, shared warehouse basis, and allocation measurement before sending chargeback.",
        ),
        _gap_row(
            "Shared / needs-owner allocation",
            confidence.str.contains("SHARED|ACCOUNT-WIDE|NEEDS OWNER", na=False),
            "Keep these rows in estimated review and attach service-specific lineage before charging a team.",
        ),
    ]
    if lens_summary is not None and not lens_summary.empty:
        top = lens_summary.iloc[0]
        rows.append({
            "GAP": "Cost concentration",
            "STATE": "Action Needed" if safe_float(top.get("PCT_OF_COST")) >= 35 else "Watch",
            "ROWS": 1,
            "EST_COST": safe_float(top.get("EST_COST")),
            "TOP_DRIVER": str(top.get("DIMENSION") or "Unknown"),
            "ACTION": "If one driver owns 35%+ of cost, validate workload isolation, chargeback basis, and warehouse settings.",
        })
    return pd.DataFrame(rows)


def _annotate_cost_routes(df: pd.DataFrame, finding_type: str) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    routed = df.copy()
    if finding_type == "Warehouse Delta":
        routed["NEXT_WORKFLOW"] = "Cost Explorer"
        routed["NEXT_ACTION"] = (
            "Drill into the warehouse delta, separate workload growth from idle/service overhead, "
            "then validate top users and query types before resizing."
        )
    elif finding_type == "User Cost":
        routed["NEXT_WORKFLOW"] = "Query workbench"
        routed["NEXT_ACTION"] = (
            "Open the user drilldown, identify repeat query signatures, and confirm whether the workload can be optimized or scheduled."
        )
    elif finding_type == "Chargeback":
        routed["NEXT_WORKFLOW"] = "Cost & Contract"
        routed["NEXT_ACTION"] = (
            "Validate company scope, warehouse route, and allocation measurement before sending the chargeback report."
        )
    elif finding_type == "Service Cost":
        routed["NEXT_WORKFLOW"] = "Cost & Contract"
        routed["NEXT_ACTION"] = (
            "Treat as account-wide unless owner tags or service lineage prove attribution; review service-specific usage before chargeback."
        )
    else:
        routed["NEXT_WORKFLOW"] = "Cost & Contract"
        routed["NEXT_ACTION"] = "Validate measurement basis, owner, and proof query before taking a cost-control action."
    return routed


def _bill_period_bounds(period_key: str) -> dict:
    periods = {
        "Last complete day": {
            "label": "last complete day",
            "current_start": "TO_TIMESTAMP_NTZ(DATEADD('day', -1, CURRENT_DATE()))",
            "current_end": "TO_TIMESTAMP_NTZ(CURRENT_DATE())",
            "prior_start": "TO_TIMESTAMP_NTZ(DATEADD('day', -2, CURRENT_DATE()))",
            "prior_end": "TO_TIMESTAMP_NTZ(DATEADD('day', -1, CURRENT_DATE()))",
            "days_back": 4,
        },
        "Last 7 complete days": {
            "label": "last 7 complete days",
            "current_start": "TO_TIMESTAMP_NTZ(DATEADD('day', -7, CURRENT_DATE()))",
            "current_end": "TO_TIMESTAMP_NTZ(CURRENT_DATE())",
            "prior_start": "TO_TIMESTAMP_NTZ(DATEADD('day', -14, CURRENT_DATE()))",
            "prior_end": "TO_TIMESTAMP_NTZ(DATEADD('day', -7, CURRENT_DATE()))",
            "days_back": 17,
        },
        "Last 30 complete days": {
            "label": "last 30 complete days",
            "current_start": "TO_TIMESTAMP_NTZ(DATEADD('day', -30, CURRENT_DATE()))",
            "current_end": "TO_TIMESTAMP_NTZ(CURRENT_DATE())",
            "prior_start": "TO_TIMESTAMP_NTZ(DATEADD('day', -60, CURRENT_DATE()))",
            "prior_end": "TO_TIMESTAMP_NTZ(DATEADD('day', -30, CURRENT_DATE()))",
            "days_back": 65,
        },
        "Current month to date": {
            "label": "current month to date",
            "current_start": "TO_TIMESTAMP_NTZ(DATE_TRUNC('month', CURRENT_DATE()))",
            "current_end": "TO_TIMESTAMP_NTZ(CURRENT_DATE())",
            "prior_start": "TO_TIMESTAMP_NTZ(DATEADD('month', -1, DATE_TRUNC('month', CURRENT_DATE())))",
            "prior_end": "TO_TIMESTAMP_NTZ(DATEADD('month', -1, CURRENT_DATE()))",
            "days_back": 65,
        },
        "Previous month": {
            "label": "previous month",
            "current_start": "TO_TIMESTAMP_NTZ(DATEADD('month', -1, DATE_TRUNC('month', CURRENT_DATE())))",
            "current_end": "TO_TIMESTAMP_NTZ(DATE_TRUNC('month', CURRENT_DATE()))",
            "prior_start": "TO_TIMESTAMP_NTZ(DATEADD('month', -2, DATE_TRUNC('month', CURRENT_DATE())))",
            "prior_end": "TO_TIMESTAMP_NTZ(DATEADD('month', -1, DATE_TRUNC('month', CURRENT_DATE())))",
            "days_back": 95,
        },
    }
    return periods.get(period_key, periods["Last 7 complete days"])


def _pct_delta(current: float, prior: float):
    if prior is None or abs(float(prior)) < 0.000001:
        return None
    return ((float(current or 0) - float(prior or 0)) / float(prior)) * 100


def _fmt_delta(value) -> str:
    if value is None:
        return "new/no baseline"
    return f"{value:+.1f}%"


def _first_value(df: pd.DataFrame, column: str, default=0.0):
    if df is None or df.empty or column not in df.columns:
        return default
    return df.iloc[0].get(column, default)


def _bill_driver_summary(
    *,
    delta_credits: float,
    current_credits: float,
    prior_credits: float,
    unallocated_pct: float,
    warehouse_deltas: pd.DataFrame,
    user_drivers: pd.DataFrame,
    query_type_drivers: pd.DataFrame,
) -> dict:
    """Build an executive-ready explanation from exact and allocated bill signals."""
    top_wh = warehouse_deltas.iloc[0].to_dict() if warehouse_deltas is not None and not warehouse_deltas.empty else {}
    top_user = user_drivers.iloc[0].to_dict() if user_drivers is not None and not user_drivers.empty else {}
    top_type = query_type_drivers.iloc[0].to_dict() if query_type_drivers is not None and not query_type_drivers.empty else {}
    delta_pct = _pct_delta(current_credits, prior_credits)

    if abs(delta_credits) < 0.01:
        headline = "Spend was essentially flat."
        reason = "No material credit movement was detected compared with the prior comparable period."
        severity = "Normal"
    elif delta_credits > 0:
        headline = f"Spend increased by {delta_credits:,.2f} credits ({_fmt_delta(delta_pct)})."
        reason = (
            f"The largest warehouse movement was {top_wh.get('WAREHOUSE_NAME', 'n/a')} "
            f"at {safe_float(top_wh.get('CREDIT_DELTA', 0)):,.2f} incremental credits. "
            f"The largest allocated workload was {top_user.get('USER_NAME', 'n/a')} on "
            f"{top_user.get('WAREHOUSE_NAME', 'n/a')}."
        )
        severity = "High" if delta_pct is not None and delta_pct >= 50 else "Watch"
    else:
        headline = f"Spend decreased by {abs(delta_credits):,.2f} credits ({_fmt_delta(delta_pct)})."
        reason = (
            f"The largest downward warehouse movement was {top_wh.get('WAREHOUSE_NAME', 'n/a')} "
            f"at {safe_float(top_wh.get('CREDIT_DELTA', 0)):,.2f} credits."
        )
        severity = "Improved"

    if unallocated_pct >= 25:
        caveat = "A large unallocated gap means idle time, non-query activity, or ACCOUNT_USAGE latency may be driving the bill."
    elif unallocated_pct >= 10:
        caveat = "Some spend is not cleanly attributable to user queries; review idle and service overhead before chargeback."
    else:
        caveat = "Most warehouse spend is attributable to query workload in this window."

    next_action = (
        f"Start with {top_wh.get('WAREHOUSE_NAME', 'the top warehouse')} and validate "
        f"{top_type.get('QUERY_TYPE', 'the top query type')} activity in Query Analysis before changing warehouse settings."
    )
    return {
        "severity": severity,
        "headline": headline,
        "reason": reason,
        "caveat": caveat,
        "next_action": next_action,
    }


def _build_bill_waterfall(
    warehouse_deltas: pd.DataFrame,
    *,
    prior_credits: float,
    current_credits: float,
    credit_price: float,
    top_n: int = 6,
) -> pd.DataFrame:
    """Build a compact bill-movement waterfall from warehouse credit deltas."""
    rows = [{
        "Driver": "Prior baseline",
        "Credits": round(float(prior_credits or 0), 4),
        "Estimated Cost": round(credits_to_dollars(prior_credits, credit_price), 2),
        "Type": "Baseline",
    }]
    delta_total = float(current_credits or 0) - float(prior_credits or 0)
    selected_delta = 0.0
    if warehouse_deltas is not None and not warehouse_deltas.empty and "CREDIT_DELTA" in warehouse_deltas.columns:
        movers = warehouse_deltas.copy()
        movers["ABS_DELTA"] = movers["CREDIT_DELTA"].fillna(0).abs()
        movers = movers.sort_values("ABS_DELTA", ascending=False).head(top_n)
        for _, row in movers.iterrows():
            delta = safe_float(row.get("CREDIT_DELTA", 0))
            if abs(delta) < 0.0001:
                continue
            selected_delta += delta
            label = str(row.get("WAREHOUSE_NAME") or "Unknown warehouse")
            rows.append({
                "Driver": label[:60],
                "Credits": round(delta, 4),
                "Estimated Cost": round(credits_to_dollars(delta, credit_price), 2),
                "Type": "Increase" if delta > 0 else "Decrease",
            })
    other_delta = delta_total - selected_delta
    if abs(other_delta) >= 0.0001:
        rows.append({
            "Driver": "Other movement",
            "Credits": round(other_delta, 4),
            "Estimated Cost": round(credits_to_dollars(other_delta, credit_price), 2),
            "Type": "Increase" if other_delta > 0 else "Decrease",
        })
    rows.append({
        "Driver": "Current total",
        "Credits": round(float(current_credits or 0), 4),
        "Estimated Cost": round(credits_to_dollars(current_credits, credit_price), 2),
        "Type": "Current",
    })
    return pd.DataFrame(rows)


def _service_cost_category(service_type: str) -> str:
    """Group Snowflake METERING_HISTORY service types into readable bill buckets."""
    value = str(service_type or "UNKNOWN").upper()
    if (
        "CORTEX" in value
        or "INTELLIGENCE" in value
        or "LLM" in value
        or value == "AI_SERVICES"
        or value.startswith("AI_")
        or "_AI_" in value
        or value.endswith("_AI")
    ):
        return "AI / Cortex"
    if "OPENFLOW" in value:
        return "Data integration / Openflow"
    if "SNOWPIPE" in value or "PIPE" in value or "INGEST" in value:
        return "Data loading / ingestion"
    if (
        "AUTO_CLUSTER" in value
        or "AUTOMATIC_CLUSTERING" in value
        or "CLUSTERING" in value
        or "SEARCH_OPTIMIZATION" in value
        or "MATERIALIZED_VIEW" in value
        or "DYNAMIC_TABLE" in value
        or "SERVERLESS" in value
        or "TASK" in value
        or "REPLICATION" in value
        or "SNOWPARK_CONTAINER" in value
        or "CONTAINER_SERVICES" in value
    ):
        return "Serverless features"
    if "CLOUD_SERVICES" in value or "CLOUD SERVICE" in value:
        return "Cloud services / metadata"
    if "WAREHOUSE" in value or "COMPUTE" in value:
        return "Warehouse compute"
    return "Other service credits"


def _service_period_totals(service_drivers: pd.DataFrame) -> pd.DataFrame:
    if service_drivers is None or service_drivers.empty:
        return pd.DataFrame(columns=["CATEGORY", "CURRENT_CREDITS", "PRIOR_CREDITS", "DELTA_CREDITS"])
    required = {"PERIOD", "SERVICE_TYPE", "CREDITS"}
    if not required.issubset(set(service_drivers.columns)):
        return pd.DataFrame(columns=["CATEGORY", "CURRENT_CREDITS", "PRIOR_CREDITS", "DELTA_CREDITS"])
    svc = service_drivers.copy()
    svc["CATEGORY"] = svc["SERVICE_TYPE"].apply(_service_cost_category)
    pivot = (
        svc.pivot_table(
            index="CATEGORY",
            columns="PERIOD",
            values="CREDITS",
            aggfunc="sum",
            fill_value=0.0,
        )
        .reset_index()
        .rename_axis(None, axis=1)
    )
    for column in ("CURRENT", "PRIOR"):
        if column not in pivot.columns:
            pivot[column] = 0.0
    pivot["CURRENT_CREDITS"] = pivot["CURRENT"].apply(safe_float)
    pivot["PRIOR_CREDITS"] = pivot["PRIOR"].apply(safe_float)
    pivot["DELTA_CREDITS"] = pivot["CURRENT_CREDITS"] - pivot["PRIOR_CREDITS"]
    return pivot[["CATEGORY", "CURRENT_CREDITS", "PRIOR_CREDITS", "DELTA_CREDITS"]].sort_values(
        "CURRENT_CREDITS", ascending=False
    )


def _build_finance_movement_summary(
    *,
    current_credits: float,
    prior_credits: float,
    allocated_credits: float,
    unallocated_credits: float,
    service_drivers: pd.DataFrame,
    credit_price: float,
) -> pd.DataFrame:
    """Build a concise finance-facing movement bridge with source-basis labels."""
    current_credits = safe_float(current_credits)
    prior_credits = safe_float(prior_credits)
    allocated_credits = safe_float(allocated_credits)
    unallocated_credits = safe_float(unallocated_credits)
    credit_price = safe_float(credit_price)
    rows = [
        {
            "Category": "Warehouse metering",
            "Basis": "Exact warehouse compute from WAREHOUSE_METERING_HISTORY",
            "Current Credits": round(current_credits, 4),
            "Prior Credits": round(prior_credits, 4),
            "Delta Credits": round(current_credits - prior_credits, 4),
            "Current Cost": round(credits_to_dollars(current_credits, credit_price), 2),
            "Delta Cost": round(credits_to_dollars(current_credits - prior_credits, credit_price), 2),
            "Measurement Basis": "Exact",
            "Action": "Use this as the official warehouse-compute usage movement.",
        },
        {
            "Category": "Query-attributed workload",
            "Basis": "Allocated by query execution share inside each warehouse-hour",
            "Current Credits": round(allocated_credits, 4),
            "Prior Credits": None,
            "Delta Credits": None,
            "Current Cost": round(credits_to_dollars(allocated_credits, credit_price), 2),
            "Delta Cost": None,
            "Measurement Basis": "Allocated / Estimated",
            "Action": "Use for directional user, role, database, and query-type chargeback.",
        },
        {
            "Category": "Unallocated / idle / overhead",
            "Basis": "Exact warehouse credits minus allocated query credits",
            "Current Credits": round(unallocated_credits, 4),
            "Prior Credits": None,
            "Delta Credits": None,
            "Current Cost": round(credits_to_dollars(unallocated_credits, credit_price), 2),
            "Delta Cost": None,
            "Measurement Basis": "Estimated",
            "Action": "Review auto-suspend, idle periods, non-query activity, and ACCOUNT_USAGE latency.",
        },
    ]
    service_totals = _service_period_totals(service_drivers)
    for _, row in service_totals.iterrows():
        current = safe_float(row.get("CURRENT_CREDITS", 0))
        prior = safe_float(row.get("PRIOR_CREDITS", 0))
        delta = safe_float(row.get("DELTA_CREDITS", 0))
        if abs(current) < 0.0001 and abs(prior) < 0.0001:
            continue
        rows.append({
            "Category": str(row.get("CATEGORY") or "Other service credits"),
            "Basis": "Account-wide METERING_HISTORY service credits",
            "Current Credits": round(current, 4),
            "Prior Credits": round(prior, 4),
            "Delta Credits": round(delta, 4),
            "Current Cost": round(credits_to_dollars(current, credit_price), 2),
            "Delta Cost": round(credits_to_dollars(delta, credit_price), 2),
            "Measurement Basis": "Account-wide",
            "Action": "Do not charge back to ALFA/Trexis unless a service-specific owner tag or lineage exists.",
        })
    return pd.DataFrame(rows)


def _build_explain_bill_markdown(
    *,
    company: str,
    period_label: str,
    current_credits: float,
    prior_credits: float,
    credit_price: float,
    active_warehouses: int,
    allocated_credits: float,
    unallocated_credits: float,
    warehouse_deltas: pd.DataFrame,
    user_drivers: pd.DataFrame,
    query_type_drivers: pd.DataFrame,
    service_drivers: pd.DataFrame = None,
) -> str:
    def _driver_credits(row, default=0.0) -> float:
        if hasattr(row, "get"):
            return safe_float(row.get("ALLOCATED_CREDITS", row.get("TOTAL_CREDITS", default)))
        return safe_float(default)

    delta_credits = current_credits - prior_credits
    delta_pct = _pct_delta(current_credits, prior_credits)
    direction = "increased" if delta_credits > 0 else "decreased" if delta_credits < 0 else "held flat"
    top_wh = warehouse_deltas.iloc[0] if warehouse_deltas is not None and not warehouse_deltas.empty else {}
    top_user = user_drivers.iloc[0] if user_drivers is not None and not user_drivers.empty else {}
    top_type = query_type_drivers.iloc[0] if query_type_drivers is not None and not query_type_drivers.empty else {}
    service_totals = _service_period_totals(service_drivers)
    service_lines = []
    if service_totals is not None and not service_totals.empty:
        for _, row in service_totals.head(5).iterrows():
            service_lines.append(
                f"- {row.get('CATEGORY')}: {safe_float(row.get('CURRENT_CREDITS', 0)):,.2f} current credits "
                f"({safe_float(row.get('DELTA_CREDITS', 0)):+,.2f} vs baseline)."
            )

    lines = [
        f"# Explain This Bill - {company}",
        "",
        f"Period reviewed: {period_label}.",
        f"Warehouse-metered credits {direction} by {delta_credits:+,.2f} credits ({_fmt_delta(delta_pct)}), from {prior_credits:,.2f} to {current_credits:,.2f}.",
        f"Estimated current-period warehouse cost is ${credits_to_dollars(current_credits, credit_price):,.2f} at ${credit_price:,.2f}/credit.",
        f"Active warehouses in the period: {active_warehouses}.",
        "",
        "## Primary Drivers",
        f"- Largest warehouse delta: {top_wh.get('WAREHOUSE_NAME', 'n/a')} ({safe_float(top_wh.get('CREDIT_DELTA', 0)):,.2f} credit delta).",
        f"- Largest allocated user/workload: {top_user.get('USER_NAME', 'n/a')} on {top_user.get('WAREHOUSE_NAME', 'n/a')} ({_driver_credits(top_user):,.2f} allocated credits).",
        f"- Top query type by allocated credits: {top_type.get('QUERY_TYPE', 'n/a')} ({_driver_credits(top_type):,.2f} allocated credits).",
        "",
        "## Allocation Caveat",
        f"Exact warehouse credits: {current_credits:,.2f}. Query-attributed credits: {allocated_credits:,.2f}. Unallocated / idle / service-overhead gap: {unallocated_credits:,.2f} credits.",
        "Warehouse totals are exact ACCOUNT_USAGE metering. User and query-type drivers are allocated from hourly metering by query execution share, so they are directional rather than invoice-grade.",
        "",
        "## Account-Wide Service Credits",
        *(service_lines or ["- No service/serverless credit rows were available for this period."]),
        "Service credits are account-wide unless Snowflake exposes a service-specific owner dimension or your account uses reliable owner tags.",
        "",
        "## Recommended Follow-Up",
        "- Review warehouses with the largest positive deltas first.",
        "- Drill into the top user/workload and query type before resizing warehouses.",
        "- If the unallocated gap is material, review auto-suspend settings, non-query warehouse activity, and ACCOUNT_USAGE latency.",
    ]
    return "\n".join(lines)


__all__ = ['_row_text', '_environment_rollup_for_cost', '_cost_allocation_quality', '_annotate_allocation_quality', '_prepare_cost_forecast_rows', '_annual_service_projection_metrics', '_mixed_label', '_chargeback_readiness_label', '_route_telemetry_label', '_cost_explorer_dimension_columns', '_cost_explorer_dimension_label', '_normalize_cost_explorer_detail', '_cost_explorer_summary', '_cost_explorer_gap_board', '_annotate_cost_routes', '_bill_period_bounds', '_pct_delta', '_fmt_delta', '_first_value', '_bill_driver_summary', '_build_bill_waterfall', '_service_cost_category', '_service_period_totals', '_build_finance_movement_summary', '_build_explain_bill_markdown']
