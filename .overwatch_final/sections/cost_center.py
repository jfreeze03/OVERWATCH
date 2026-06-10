# sections/cost_center.py - User leaderboard, burn rate, forecast, budget, attribution, chargeback
# FIX: Chargeback tab now uses get_company_case_expr() from company_filter.py
#      instead of the old hardcoded CASE that missed WH_ALFA_* warehouses.
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from config import ALFA_DEV_DATABASES, TREXIS_DEV_DATABASES, TREXIS_PROD_DATABASES
from sections.shell_helpers import render_shell_snapshot
from utils.workflows import render_workflow_selector
from utils import (
    get_session, format_credits, credits_to_dollars,
    download_csv, build_metered_credit_cte, build_cost_reconciliation_sql,
    query_attribution_supported,
    burn_trend_label,
    metric_confidence_label, freshness_note,
    get_credit_price,
    get_wh_filter_clause, get_global_wh_filter_clause,
    get_global_filter_clause, get_company_case_expr,
    get_active_environment, get_environment_case_expr, get_environment_filter_clause,
    build_mart_bill_summary_sql, build_mart_bill_warehouse_delta_sql,
    build_mart_chargeback_sql, build_mart_cost_explorer_sql, load_mart_table, mart_source_caption,
    filter_existing_columns,
    render_drillable_bar_chart, render_entity_query_drilldown, render_priority_dataframe,
    render_ranked_bar_chart, render_chart_with_data_toggle,
    day_window_selectbox,
    make_action_id, upsert_actions,
    run_query, sql_literal, format_snowflake_error,
    resolve_owner_context,
    defer_source_note,
    safe_float,
)


COST_CENTER_VIEWS = (
    "Cost Explorer",
    "Explain This Bill",
    "User Leaderboard",
    "Burn Rate",
    "Reconciliation",
    "Forecast",
    "Budget vs Actual",
    "Attribution",
    "Chargeback",
    "Contract Utilization",
)

COST_CENTER_VIEW_DETAILS = {
    "Cost Explorer": "Pivot one loaded attribution set by company, department, warehouse, database, role, and user.",
    "Explain This Bill": "Narrative answer for why spend changed.",
    "User Leaderboard": "Top users and warehouses by allocated credits.",
    "Burn Rate": "Daily metered credit trend by warehouse.",
    "Reconciliation": "Metered credits vs query allocation.",
    "Forecast": "Near-term projected burn from recent usage.",
    "Budget vs Actual": "Monthly consumption against budget.",
    "Attribution": "Role, schema, client, and lineage cost views.",
    "Chargeback": "ALFA/Trexis company allocation output.",
    "Contract Utilization": "Committed-use utilization and risk.",
}

NO_DATABASE_CONTEXT_VALUES = {
    "",
    "NONE",
    "NULL",
    "NAN",
    "NO_DATABASE_CONTEXT",
    "NO DATABASE CONTEXT",
}

COST_EXPLORER_LENSES = (
    "Company",
    "Department / Cost Center",
    "Warehouse",
    "Database",
    "Role",
    "User",
    "Environment",
    "Company x Warehouse",
    "Database x Role",
    "Department x Warehouse",
)

COST_EXPLORER_LENS_COLUMNS = {
    "Company": ["COMPANY"],
    "Department / Cost Center": ["DEPARTMENT"],
    "Warehouse": ["WAREHOUSE_NAME"],
    "Database": ["DATABASE_NAME"],
    "Role": ["ROLE_NAME"],
    "User": ["USER_NAME"],
    "Environment": ["ENVIRONMENT_ROLLUP"],
    "Company x Warehouse": ["COMPANY", "WAREHOUSE_NAME"],
    "Database x Role": ["DATABASE_NAME", "ROLE_NAME"],
    "Department x Warehouse": ["DEPARTMENT", "WAREHOUSE_NAME"],
}


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
    if db == "ALFA_EDW_PROD" or db in TREXIS_PROD_DATABASES or env == "PROD":
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
                "Query database context allocated across metered warehouse-hour credits; owner tag proof is attached."
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
                "Trexis database context allocated across metered warehouse-hour credits; owner tag proof is attached."
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
            "ALLOCATION_BASIS": "ALFA database context exists, but the environment is outside the approved PROD/DEV family.",
            "CHARGEBACK_READY": "Review",
            "SCOPE_REVIEW": "Unmapped ALFA environment",
        }
    return {
        "ENVIRONMENT_ROLLUP": rollup,
        "ALLOCATION_CONFIDENCE": "Shared / Needs Owner",
        "ALLOCATION_BASIS": "Database context is shared, external, or unmapped; owner evidence is required before chargeback.",
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
                else "DBA / FinOps"
            ),
            axis=1,
        )
    if "OWNER_SOURCE" not in annotated.columns:
        annotated["OWNER_SOURCE"] = annotated.apply(
            lambda row: (
                "QUERY_USER"
                if _row_text(row, "USER_NAME").upper() not in {"", "UNKNOWN USER", "UNKNOWN_USER"}
                else "MISSING_OWNER"
            ),
            axis=1,
        )
    if "OWNER_EVIDENCE" not in annotated.columns:
        annotated["OWNER_EVIDENCE"] = annotated.apply(
            lambda row: (
                "Query user present; validate owner/tag evidence before billing."
                if _row_text(row, "OWNER_SOURCE").upper() == "QUERY_USER"
                else "No query user owner evidence; shared/unallocated review required."
            ),
            axis=1,
        )
    return annotated


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


def _owner_proof_label(values) -> str:
    cleaned = {str(value).strip().upper() for value in values if str(value or "").strip()}
    if not cleaned:
        return "Missing"
    if any("TAG" in value for value in cleaned):
        return "Tag Proof"
    if cleaned == {"QUERY_USER"}:
        return "Query User Only"
    if "MISSING_OWNER" in cleaned:
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
            OWNER_PROOF=("OWNER_SOURCE", _owner_proof_label),
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
            "Missing department / cost-center proof",
            dept.isin({"", "UNASSIGNED", "UNKNOWN", "NONE", "NULL"}) | ~owner_source.str.contains("TAG", na=False),
            "Tag warehouses with COST_CENTER or DEPARTMENT and keep owner-directory fallback current.",
        ),
        _gap_row(
            "No database context",
            no_context,
            "Do not split PROD/DEV or bill a database owner until query tag, session lineage, or owner proof exists.",
        ),
        _gap_row(
            "Not chargeback ready",
            readiness.isin({"NO", "REVIEW", "DIRECTIONAL", "MIXED", ""}),
            "Resolve owner proof, shared warehouse basis, and allocation source basis before sending chargeback.",
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
            "ACTION": "If one driver owns 35%+ of cost, validate budget owner, workload isolation, and warehouse settings.",
        })
    return pd.DataFrame(rows)


def _cost_explorer_live_sql(
    days: int,
    company: str,
    warehouse_size_expr: str,
    department_contains: str = "",
) -> str:
    company_expr = get_company_case_expr("q.warehouse_name", "q.database_name", "q.user_name")
    environment_expr = get_environment_case_expr("q.database_name")
    scope = get_global_filter_clause(
        "q.start_time", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name", "q.schema_name"
    )
    dept_filter = (
        f"AND COALESCE(t.cost_center_tag, t.owner_tag, '') ILIKE '%' || {sql_literal(department_contains, 300)} || '%'"
        if str(department_contains or "").strip()
        else ""
    )
    return f"""
    WITH {build_metered_credit_cte(days_back=days)},
    warehouse_tags AS (
        SELECT
            object_name AS warehouse_name,
            MAX(IFF(
                UPPER(tag_name) IN ('COST_CENTER', 'COSTCENTER', 'DEPARTMENT', 'BILLING_OWNER'),
                tag_value,
                NULL
            )) AS cost_center_tag,
            MAX(IFF(
                UPPER(tag_name) IN ('OWNER', 'BUSINESS_OWNER', 'SERVICE_OWNER', 'DATA_OWNER', 'APPLICATION_OWNER'),
                tag_value,
                NULL
            )) AS owner_tag
        FROM SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES
        WHERE UPPER(COALESCE(domain, '')) = 'WAREHOUSE'
        GROUP BY object_name
    ),
    query_costs AS (
        SELECT
            {company_expr} AS company,
            {environment_expr} AS environment,
            COALESCE(q.database_name, 'NO_DATABASE_CONTEXT') AS database_name,
            COALESCE(q.user_name, 'Unknown user') AS user_name,
            COALESCE(q.role_name, 'Unknown role') AS role_name,
            COALESCE(q.warehouse_name, 'Unknown warehouse') AS warehouse_name,
            {warehouse_size_expr} AS warehouse_size,
            COALESCE(NULLIF(t.cost_center_tag, ''), NULLIF(t.owner_tag, ''), 'Unassigned') AS department,
            COALESCE(NULLIF(t.cost_center_tag, ''), NULLIF(t.owner_tag, ''), 'Unassigned') AS cost_owner,
            IFF(COALESCE(t.cost_center_tag, t.owner_tag, '') <> '', 'WAREHOUSE_TAG', 'QUERY_USER') AS owner_source,
            IFF(COALESCE(t.cost_center_tag, t.owner_tag, '') <> '',
                'Warehouse tag evidence from TAG_REFERENCES.',
                'Query user only; validate owner or department before billing.'
            ) AS owner_evidence,
            COUNT(*) AS query_count,
            ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS total_credits,
            MIN(q.start_time::DATE) AS first_usage_date,
            MAX(q.start_time::DATE) AS last_usage_date,
            COUNT(DISTINCT q.start_time::DATE) AS active_days
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
        LEFT JOIN warehouse_tags t ON UPPER(t.warehouse_name) = UPPER(q.warehouse_name)
        WHERE q.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {scope}
          {dept_filter}
        GROUP BY 1,2,3,4,5,6,8,9,10,11
    )
    SELECT
        company,
        environment,
        database_name,
        user_name,
        role_name,
        warehouse_name,
        warehouse_size,
        department,
        cost_owner,
        owner_source,
        owner_evidence,
        query_count,
        total_credits,
        first_usage_date,
        last_usage_date,
        active_days
    FROM query_costs
    ORDER BY total_credits DESC, query_count DESC
    LIMIT 10000
    """


def _chargeback_cost_verification_sql(
    row: pd.Series,
    *,
    lookback_days: int = 30,
    company: str = "",
) -> str:
    """Build read-only evidence for a chargeback/cost-outlier queue item."""
    days = max(1, min(int(lookback_days or 30), 90))
    wh = _row_text(row, "WAREHOUSE_NAME") or "Unknown warehouse"
    user = _row_text(row, "USER_NAME")
    database = _row_text(row, "DATABASE_NAME")
    environment = _row_text(row, "ENVIRONMENT")
    row_company = _row_text(row, "COMPANY") or company
    wh_clause = f"AND q.warehouse_name = {sql_literal(wh, 300)}"
    user_clause = (
        f"AND q.user_name = {sql_literal(user, 300)}"
        if user and user.upper() not in {"UNKNOWN USER", "UNKNOWN_USER"}
        else ""
    )
    database_clause = ""
    if database and database.upper() not in NO_DATABASE_CONTEXT_VALUES:
        database_clause = f"AND q.database_name = {sql_literal(database, 300)}"
    elif environment and environment.upper() not in {"ALL", "NO DATABASE CONTEXT", "NO_DATABASE_CONTEXT"}:
        env_filter = get_environment_filter_clause(
            "q.database_name",
            environment=environment,
            company=row_company,
        )
        database_clause = env_filter

    return f"""WITH query_scope AS (
    SELECT
        q.warehouse_name,
        COALESCE(q.database_name, 'NO_DATABASE_CONTEXT') AS database_name,
        COALESCE(q.user_name, 'UNKNOWN_USER') AS user_name,
        COUNT(*) AS query_count,
        SUM(COALESCE(q.total_elapsed_time, 0)) / 1000 AS total_elapsed_sec,
        AVG(COALESCE(q.total_elapsed_time, 0)) / 1000 AS avg_elapsed_sec,
        APPROX_PERCENTILE(COALESCE(q.total_elapsed_time, 0) / 1000, 0.95) AS p95_elapsed_sec,
        SUM(COALESCE(q.bytes_scanned, 0)) / POWER(1024, 4) AS tb_scanned,
        SUM(
            COALESCE(q.bytes_spilled_to_local_storage, 0)
            + COALESCE(q.bytes_spilled_to_remote_storage, 0)
        ) / POWER(1024, 3) AS spill_gb,
        MAX(q.start_time) AS latest_query_time
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
    WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
      {wh_clause}
      {user_clause}
      {database_clause}
    GROUP BY q.warehouse_name, COALESCE(q.database_name, 'NO_DATABASE_CONTEXT'), COALESCE(q.user_name, 'UNKNOWN_USER')
),
metering_scope AS (
    SELECT
        warehouse_name,
        SUM(COALESCE(credits_used_compute, credits_used)) AS warehouse_compute_credits,
        SUM(COALESCE(credits_used_cloud_services, 0)) AS cloud_services_credits,
        MAX(end_time) AS latest_metering_time
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
    WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
      AND warehouse_name = {sql_literal(wh, 300)}
    GROUP BY warehouse_name
),
owner_tag_scope AS (
    SELECT
        domain,
        object_database,
        object_name,
        tag_name,
        tag_value
    FROM SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES
    WHERE UPPER(tag_name) IN ('COST_OWNER', 'DATA_OWNER', 'APP_OWNER', 'APPLICATION_OWNER', 'BUSINESS_OWNER', 'SERVICE_OWNER')
      AND tag_value IS NOT NULL
      AND (
        (UPPER(domain) = 'WAREHOUSE' AND UPPER(object_name) = UPPER({sql_literal(wh, 300)}))
        OR (
          UPPER(domain) = 'DATABASE'
          AND UPPER(COALESCE(object_database, object_name)) = UPPER({sql_literal(database, 300)})
        )
      )
)
SELECT
    q.warehouse_name,
    q.database_name,
    q.user_name,
    q.query_count,
    ROUND(q.total_elapsed_sec, 2) AS total_elapsed_sec,
    ROUND(q.avg_elapsed_sec, 2) AS avg_elapsed_sec,
    ROUND(q.p95_elapsed_sec, 2) AS p95_elapsed_sec,
    ROUND(q.tb_scanned, 4) AS tb_scanned,
    ROUND(q.spill_gb, 4) AS spill_gb,
    ROUND(COALESCE(m.warehouse_compute_credits, 0), 4) AS warehouse_compute_credits,
    ROUND(COALESCE(m.cloud_services_credits, 0), 4) AS cloud_services_credits,
    'Allocated / Estimated' AS allocation_confidence,
    LISTAGG(DISTINCT o.domain || ':' || o.tag_name || '=' || o.tag_value, '; ') AS owner_tag_evidence,
    q.latest_query_time,
    m.latest_metering_time
FROM query_scope q
LEFT JOIN metering_scope m
  ON m.warehouse_name = q.warehouse_name
LEFT JOIN owner_tag_scope o
  ON 1 = 1
GROUP BY
    q.warehouse_name,
    q.database_name,
    q.user_name,
    q.query_count,
    q.total_elapsed_sec,
    q.avg_elapsed_sec,
    q.p95_elapsed_sec,
    q.tb_scanned,
    q.spill_gb,
    m.warehouse_compute_credits,
    m.cloud_services_credits,
    q.latest_query_time,
    m.latest_metering_time
ORDER BY total_elapsed_sec DESC, query_count DESC
LIMIT 50"""


def _chargeback_action_owner(row: pd.Series) -> str:
    readiness = _row_text(row, "CHARGEBACK_READY").upper()
    owner_source = _row_text(row, "OWNER_SOURCE").upper()
    cost_owner = _row_text(row, "COST_OWNER")
    if "TAG" in owner_source and cost_owner:
        return cost_owner
    user = _row_text(row, "USER_NAME")
    if readiness in {"NO", "REVIEW"}:
        return "DBA / FinOps"
    return user if user and user.upper() not in {"UNKNOWN USER", "UNKNOWN_USER"} else "DBA / FinOps"


def _chargeback_action_sql_note(row: pd.Series, credits: float, est_cost: float) -> str:
    confidence = _row_text(row, "ALLOCATION_CONFIDENCE") or "Unknown"
    readiness = _row_text(row, "CHARGEBACK_READY") or "Unknown"
    basis = _row_text(row, "ALLOCATION_BASIS") or "Review allocation basis before chargeback."
    scope_review = _row_text(row, "SCOPE_REVIEW") or "None"
    database = _row_text(row, "DATABASE_NAME") or "NO_DATABASE_CONTEXT"
    env_rollup = _row_text(row, "ENVIRONMENT_ROLLUP") or _environment_rollup_for_cost(row)
    cost_owner = _row_text(row, "COST_OWNER") or "Missing"
    owner_source = _row_text(row, "OWNER_SOURCE") or "Missing"
    owner_evidence = _row_text(row, "OWNER_EVIDENCE") or "No owner evidence attached."
    return "\n".join([
        "-- Chargeback review plan, not state-changing SQL.",
        "-- Do not bill an owner from this row until allocation source basis and ownership evidence are attached.",
        f"-- Database: {database}",
        f"-- Environment rollup: {env_rollup}",
        f"-- Cost owner: {cost_owner}",
        f"-- Owner source: {owner_source}",
        f"-- Owner evidence: {owner_evidence}",
        f"-- Credits: {credits:,.4f}; estimated cost: ${est_cost:,.2f}",
        f"-- Allocation source basis: {confidence}",
        f"-- Chargeback readiness: {readiness}",
        f"-- Allocation basis: {basis}",
        f"-- Scope review: {scope_review}",
        "-- Required closure: attach owner/tag evidence or mark shared/unallocated with reason.",
    ])


def _queue_cost_outliers(session, df: pd.DataFrame, credit_price: float, source: str) -> None:
    if df is None or df.empty:
        st.info("No cost outliers to queue.")
        return
    if (
        "ALLOCATION_CONFIDENCE" not in df.columns
        or "CHARGEBACK_READY" not in df.columns
        or "ENVIRONMENT_ROLLUP" not in df.columns
    ):
        df = _annotate_allocation_quality(df)
    if "TOTAL_CREDITS" not in df.columns:
        if "ALLOCATED_CREDITS" in df.columns:
            df = df.copy()
            df["TOTAL_CREDITS"] = df["ALLOCATED_CREDITS"]
        else:
            st.info("No total-credit measure was available for cost outlier queueing.")
            return
    company = st.session_state.get("active_company", "ALFA")
    is_chargeback = "CHARGEBACK" in str(source or "").upper()
    actions = []
    baseline = safe_float(df["TOTAL_CREDITS"].median()) if "TOTAL_CREDITS" in df.columns else 0
    candidates = df.sort_values("TOTAL_CREDITS", ascending=False).head(20)
    for _, row in candidates.iterrows():
        active_env = get_active_environment()
        action_env = str(
            row.get("ENVIRONMENT_ROLLUP")
            or row.get("ENVIRONMENT")
            or (active_env if active_env != "ALL" else "")
            or ""
        )
        user = _row_text(row, "USER_NAME") or "Unknown user"
        wh = _row_text(row, "WAREHOUSE_NAME") or "Unknown warehouse"
        database = _row_text(row, "DATABASE_NAME")
        confidence = _row_text(row, "ALLOCATION_CONFIDENCE")
        readiness = _row_text(row, "CHARGEBACK_READY")
        scope_review = _row_text(row, "SCOPE_REVIEW")
        owner_source = _row_text(row, "OWNER_SOURCE")
        owner_evidence = _row_text(row, "OWNER_EVIDENCE")
        credits = safe_float(row.get("TOTAL_CREDITS", 0))
        est_cost = credits_to_dollars(credits, credit_price)
        if baseline > 0 and credits < baseline * 2 and est_cost < 500:
            continue
        if is_chargeback and database:
            entity = f"{database} / {user} on {wh}"
        else:
            entity = f"{user} on {wh}"
        monthly_savings = max(0.0, est_cost * 0.15)
        confidence_note = f" ({confidence})" if confidence else ""
        readiness_note = f"; chargeback readiness: {readiness}" if readiness else ""
        scope_note = f"; scope review: {scope_review}" if scope_review and scope_review != "None" else ""
        owner_note = f"; owner proof: {owner_source}" if owner_source else ""
        finding = (
            f"{entity} consumed {credits:,.2f} credits (${est_cost:,.2f}) "
            f"in the selected window{confidence_note}{readiness_note}{scope_note}{owner_note}"
        )
        verification_sql = _chargeback_cost_verification_sql(
            row,
            lookback_days=30,
            company=str(row.get("COMPANY") or company),
        )
        action_text = (
            "Validate owner/tag evidence, confirm whether this is billable or shared/unallocated, "
            "and rerun the verification query for the next complete period before closing."
            if is_chargeback
            else "Review query patterns, warehouse sizing, cache use, and whether the workload can be optimized or scheduled differently."
        )
        if readiness and readiness.upper() in {"NO", "REVIEW"}:
            action_text = (
                f"{action_text} This row is not cleanly chargeback-ready; resolve scope/owner evidence before billing."
            )
        if is_chargeback and "TAG" not in owner_source.upper():
            action_text = (
                f"{action_text} Missing Snowflake owner-tag proof; attach COST_OWNER/DATA_OWNER/APP_OWNER evidence "
                "or classify this as shared/unallocated."
            )
        if owner_evidence:
            action_text = f"{action_text} Owner evidence: {owner_evidence[:300]}"
        action_owner = _chargeback_action_owner(row) if is_chargeback else (user if user != "Unknown user" else "DBA")
        owner_context = resolve_owner_context(
            row,
            entity=entity,
            entity_type="Cost Control" if is_chargeback else "Warehouse",
            owner=action_owner,
            category="Cost Control",
            alert_type="Chargeback Review" if is_chargeback else "Cost Outlier",
        )
        action_owner = owner_context.get("OWNER") or action_owner
        approver = (
            owner_context.get("APPROVAL_GROUP")
            or ("FinOps Lead / Cost Owner" if is_chargeback else "FinOps Lead / Workload Owner")
        )
        owner_approval_note = (
            "Allocated/estimated chargeback requires owner/tag evidence approval before billing. "
            "Close only after the next complete period verification confirms the billable driver or documents shared/unallocated treatment."
            if is_chargeback
            else "Cost remediation requires workload-owner approval before scheduling or warehouse-setting changes. "
            "Close only after the next complete period verification confirms the measured credit delta."
        )
        actions.append({
            "Action ID": make_action_id("Cost Outlier", entity, finding),
            "Source": source,
            "Severity": "Medium" if est_cost < 2500 else "High",
            "Category": "Chargeback Review" if is_chargeback else "Cost",
            "Entity Type": "Database/User/Warehouse" if is_chargeback else "User/Warehouse",
            "Entity": entity,
            "Owner": action_owner,
            "Approver": approver,
            "Owner Email": owner_context.get("OWNER_EMAIL", ""),
            "Oncall Primary": owner_context.get("ONCALL_PRIMARY", ""),
            "Oncall Secondary": owner_context.get("ONCALL_SECONDARY", ""),
            "Approval Group": approver,
            "Escalation Target": owner_context.get("ESCALATION_TARGET", ""),
            "Owner Source": owner_context.get("OWNER_SOURCE", owner_source),
            "Owner Evidence": owner_context.get("OWNER_EVIDENCE", owner_evidence),
            "Finding": finding,
            "Action": action_text,
            "Estimated Monthly Savings": round(monthly_savings, 2),
            "Generated SQL Fix": _chargeback_action_sql_note(row, credits, est_cost)[:8000],
            "Proof Query": verification_sql[:8000],
            "Company": company,
            "Environment": action_env,
            "Verification Status": "Pending",
            "Verification Query": verification_sql[:8000],
            "Baseline Value": 0,
            "Current Value": round(credits, 4),
            "Measured Delta": round(credits, 4),
            "Owner Approval Status": "Requested",
            "Owner Approval Note": owner_approval_note,
            "Recovery SLA State": "Chargeback Evidence Pending" if is_chargeback else "Savings Verification Pending",
            "Recovery SLA Target Hours": 168.0,
        })
    if not actions:
        st.success("No cost outliers crossed the queue threshold.")
        return
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} cost outliers to the action queue.")
    except Exception as e:
        st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
        st.info("Deploy the Action Queue table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry this save.")


def _annotate_cost_routes(df: pd.DataFrame, finding_type: str) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    routed = df.copy()
    if finding_type == "Warehouse Delta":
        routed["NEXT_WORKFLOW"] = "Explain bill / attribution / contract"
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
            "Validate company scope, warehouse ownership, and allocation source basis before sending the chargeback report."
        )
    elif finding_type == "Service Cost":
        routed["NEXT_WORKFLOW"] = "Cost & Contract"
        routed["NEXT_ACTION"] = (
            "Treat as account-wide unless owner tags or service lineage prove attribution; review service-specific usage before chargeback."
        )
    else:
        routed["NEXT_WORKFLOW"] = "Cost & Contract"
        routed["NEXT_ACTION"] = "Validate source basis, owner, and proof query before taking a cost-control action."
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


def _warehouse_cost_verification_sql(warehouse_name: str, lookback_days: int = 7) -> str:
    wh = sql_literal(warehouse_name, 300)
    days = max(1, int(lookback_days or 7))
    return f"""-- Exact warehouse-metering proof and post-fix verification
WITH daily AS (
    SELECT TO_DATE(start_time) AS usage_date,
           warehouse_name,
           SUM(COALESCE(credits_used, 0)) AS credits_used,
           SUM(COALESCE(credits_used_compute, 0)) AS compute_credits,
           SUM(COALESCE(credits_used_cloud_services, 0)) AS cloud_services_credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
    WHERE warehouse_name = {wh}
      AND start_time >= DATEADD('day', -{days * 2}, CURRENT_TIMESTAMP())
    GROUP BY usage_date, warehouse_name
)
SELECT CASE WHEN usage_date >= DATEADD('day', -{days}, CURRENT_DATE()) THEN 'CURRENT' ELSE 'PRIOR' END AS period,
       warehouse_name,
       SUM(credits_used) AS credits_used,
       SUM(compute_credits) AS compute_credits,
       SUM(cloud_services_credits) AS cloud_services_credits
FROM daily
GROUP BY period, warehouse_name
ORDER BY period;

-- After remediation, rerun this query for the next complete period and attach the delta to the action queue.
"""


def _warehouse_cost_control_action(
    row: pd.Series,
    *,
    credit_price: float,
    period_label: str,
    company: str,
) -> dict:
    wh = str(row.get("WAREHOUSE_NAME") or "Unknown warehouse")
    delta = safe_float(row.get("CREDIT_DELTA", 0))
    current = safe_float(row.get("CURRENT_CREDITS", row.get("TOTAL_CREDITS", 0)))
    prior = safe_float(row.get("PRIOR_CREDITS", 0))
    est_delta_cost = credits_to_dollars(delta, credit_price)
    owner = str(
        row.get("OWNER")
        or row.get("WAREHOUSE_OWNER")
        or row.get("OWNER_ROLE")
        or "DBA / FinOps"
    )
    base_owner = owner
    owner_context = resolve_owner_context(
        row,
        entity=wh,
        entity_type="Warehouse",
        owner=owner,
        category="Cost Control",
        alert_type="Bill Increase",
    )
    owner = owner_context.get("OWNER") or owner
    confidence = "Exact warehouse metering"
    if delta < 0:
        severity = "Low"
    elif est_delta_cost >= 5000 or delta >= 1000:
        severity = "Critical"
    elif est_delta_cost >= 1000 or delta >= 100:
        severity = "High"
    else:
        severity = "Medium"
    finding = (
        f"{wh} increased by {delta:,.2f} exact metered credits "
        f"(${est_delta_cost:,.2f}) during {period_label}."
    )
    action = (
        f"Assign/confirm owner ({owner}), separate workload growth from idle/overhead, "
        "review top users/query types, and use the Warehouse Settings Manager for any ALTER WAREHOUSE change. "
        "Verify savings in the next complete period before marking fixed."
    )
    approver = (
        f"{owner} / FinOps Lead"
        if base_owner and base_owner.upper() not in {"DBA", "DBA / FINOPS", "UNKNOWN"}
        else owner_context.get("APPROVAL_GROUP") or "FinOps Lead / Warehouse Owner"
    )
    owner_approval_note = (
        f"Exact warehouse metering for {period_label}. Approval is required before any warehouse "
        "setting change; close only after the next complete period verification query proves the "
        "approved change reduced or justified the delta."
    )
    generated_sql = (
        "-- Cost-control plan, not an automatic fix.\n"
        f"-- Warehouse: {wh}\n"
        f"-- Current credits: {current:,.4f}; prior credits: {prior:,.4f}; delta credits: {delta:,.4f}\n"
        "-- If idle dominates: review auto-suspend and query schedule.\n"
        "-- If queue/spill dominates: use Warehouse Health and reviewed Warehouse Settings Manager before changing size/scaling.\n"
        "-- If workload growth dominates: route to query/procedure owner for tuning."
    )
    proof = _warehouse_cost_verification_sql(wh)
    return {
        "Action ID": make_action_id("Bill Increase", wh, finding),
        "Source": "Cost & Contract - Explain This Bill",
        "Severity": severity,
        "Category": "Cost Control",
        "Entity Type": "Warehouse",
        "Entity": wh,
        "Owner": owner,
        "Approver": approver,
        "Owner Email": owner_context.get("OWNER_EMAIL", ""),
        "Oncall Primary": owner_context.get("ONCALL_PRIMARY", ""),
        "Oncall Secondary": owner_context.get("ONCALL_SECONDARY", ""),
        "Approval Group": approver,
        "Escalation Target": owner_context.get("ESCALATION_TARGET", ""),
        "Owner Source": owner_context.get("OWNER_SOURCE", ""),
        "Owner Evidence": owner_context.get("OWNER_EVIDENCE", ""),
        "Finding": finding,
        "Action": f"{confidence}. {action}",
        "Estimated Monthly Savings": round(max(0.0, est_delta_cost * 0.25), 2),
        "Generated SQL Fix": generated_sql[:8000],
        "Proof Query": proof[:8000],
        "Company": company,
        "Environment": str(row.get("ENVIRONMENT") or ""),
        "Verification Status": "Pending",
        "Verification Query": proof[:8000],
        "Baseline Value": round(prior, 4),
        "Current Value": round(current, 4),
        "Measured Delta": round(delta, 4),
        "Owner Approval Status": "Requested",
        "Owner Approval Note": owner_approval_note,
        "Recovery SLA State": "Savings Verification Pending",
        "Recovery SLA Target Hours": 168.0,
    }


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
    if "CORTEX" in value or "AI" in value or "LLM" in value:
        return "AI / Cortex"
    if "SNOWPIPE" in value or "PIPE" in value or "INGEST" in value:
        return "Data loading / ingestion"
    if (
        "AUTO_CLUSTER" in value
        or "SEARCH_OPTIMIZATION" in value
        or "MATERIALIZED_VIEW" in value
        or "DYNAMIC_TABLE" in value
        or "SERVERLESS" in value
        or "TASK" in value
        or "REPLICATION" in value
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
    budget: float = 0.0,
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
            "Source Basis": "Exact",
            "Action": "Use this as the official warehouse-compute bill movement.",
        },
        {
            "Category": "Query-attributed workload",
            "Basis": "Allocated by query execution share inside each warehouse-hour",
            "Current Credits": round(allocated_credits, 4),
            "Prior Credits": None,
            "Delta Credits": None,
            "Current Cost": round(credits_to_dollars(allocated_credits, credit_price), 2),
            "Delta Cost": None,
            "Source Basis": "Allocated / Estimated",
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
            "Source Basis": "Estimated",
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
            "Source Basis": "Account-wide",
            "Action": "Do not charge back to ALFA/Trexis unless a service-specific owner tag or lineage exists.",
        })
    if budget and budget > 0:
        current_cost = credits_to_dollars(current_credits, credit_price)
        rows.append({
            "Category": "Budget variance",
            "Basis": "Configured budget minus current warehouse-compute cost",
            "Current Credits": None,
            "Prior Credits": None,
            "Delta Credits": None,
            "Current Cost": round(current_cost, 2),
            "Delta Cost": round(current_cost - safe_float(budget), 2),
            "Source Basis": "Estimated",
            "Action": "Escalate if variance is positive and supported by a repeating workload driver.",
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


def _queue_bill_exceptions(
    session,
    warehouse_deltas: pd.DataFrame,
    credit_price: float,
    period_label: str,
) -> None:
    if warehouse_deltas is None or warehouse_deltas.empty:
        st.info("No bill exceptions to queue.")
        return
    company = st.session_state.get("active_company", "ALFA")
    actions = []
    for _, row in warehouse_deltas.sort_values("CREDIT_DELTA", ascending=False).head(10).iterrows():
        wh = str(row.get("WAREHOUSE_NAME") or "Unknown warehouse")
        delta = safe_float(row.get("CREDIT_DELTA", 0))
        if delta <= 0:
            continue
        est_delta_cost = credits_to_dollars(delta, credit_price)
        if delta < 5 and est_delta_cost < 100:
            continue
        actions.append(_warehouse_cost_control_action(
            row,
            credit_price=credit_price,
            period_label=period_label,
            company=company,
        ))
    if not actions:
        st.success("No warehouse increases crossed the exception threshold.")
        return
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} bill exceptions to the action queue.")
    except Exception as e:
        st.error(f"Could not save bill exceptions: {format_snowflake_error(e)}")


def render():
    session = get_session()
    credit_price = get_credit_price()
    company = st.session_state.get("active_company", "ALFA")
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        ["WAREHOUSE_SIZE", "BYTES_SCANNED", "QUERY_TAG"],
    ))
    max_wh_size_expr = (
        "MAX(q.warehouse_size)"
        if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR"
    )
    wh_size_plain_expr = (
        "warehouse_size"
        if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"
    )
    bytes_scanned_sum_expr = (
        "SUM(q.bytes_scanned)"
        if "BYTES_SCANNED" in qh_cols else "0"
    )
    query_tag_dimension_expr = (
        "COALESCE(q.query_tag, 'UNTAGGED')"
        if "QUERY_TAG" in qh_cols else "'UNTAGGED'"
    )

    cost_view = render_workflow_selector(
        "Cost allocation workflow",
        "cost_center_view",
        COST_CENTER_VIEWS,
        COST_CENTER_VIEW_DETAILS,
        columns=3,
    )
    defer_source_note(
        "Progressive load is enabled: each cost view runs only when its Load or Calculate button is selected."
    )

    # -- USER LEADERBOARD ------------------------------------------------------
    if cost_view == "Cost Explorer":
        st.subheader("Cost Explorer")
        st.caption("Cost drilldown by company, owner, warehouse, database, role, and user.")

        c1, c2, c3, c4 = st.columns([1, 1.35, 1, 1.2])
        with c1:
            explorer_days = day_window_selectbox("Lookback", key="cc_explorer_days", default=30)
        with c2:
            explorer_lens = st.selectbox("Break down by", COST_EXPLORER_LENSES, key="cc_explorer_lens")
        with c3:
            min_est_cost = st.number_input(
                "Min cost",
                min_value=0.0,
                value=0.0,
                step=50.0,
                key="cc_explorer_min_cost",
            )
        with c4:
            department_contains = st.text_input(
                "Department contains",
                value="",
                key="cc_explorer_department_contains",
            )

        if st.button("Load Cost Explorer", key="cc_explorer_load", type="primary"):
            try:
                mart_sql = build_mart_cost_explorer_sql(
                    explorer_days,
                    company=company,
                    warehouse_contains=st.session_state.get("global_warehouse", ""),
                    user_contains=st.session_state.get("global_user", ""),
                    role_contains=st.session_state.get("global_role", ""),
                    database_contains=st.session_state.get("global_database", ""),
                    department_contains=department_contains,
                )
                mart_result = load_mart_table(
                    "FACT_CHARGEBACK_DAILY",
                    mart_sql,
                    source_label="FACT_CHARGEBACK_DAILY",
                )
                if mart_result.available and not mart_result.data.empty:
                    explorer_detail = mart_result.data
                    explorer_source = mart_source_caption(mart_result)
                else:
                    live_sql = _cost_explorer_live_sql(
                        explorer_days,
                        company,
                        max_wh_size_expr,
                        department_contains=department_contains,
                    )
                    explorer_detail = run_query(
                        live_sql,
                        ttl_key=(
                            f"cc_cost_explorer_{company}_{get_active_environment()}_"
                            f"{explorer_days}_{st.session_state.get('global_warehouse', '')}_"
                            f"{st.session_state.get('global_user', '')}_"
                            f"{st.session_state.get('global_role', '')}_"
                            f"{st.session_state.get('global_database', '')}_{department_contains}"
                        ),
                        tier="standard",
                    )
                    fallback_note = ""
                    if mart_result.message:
                        fallback_note = f" Fast summary unavailable: {mart_result.message[:160]}"
                    elif mart_result.available:
                        fallback_note = " Mart returned no rows for the selected scope."
                    explorer_source = (
                        "Live fallback: ACCOUNT_USAGE query allocation. "
                        "Use this for DBA triage; exact chargeback still needs warehouse metering reconciliation."
                        f"{fallback_note}"
                    )
                st.session_state["df_cost_explorer_detail"] = _normalize_cost_explorer_detail(
                    explorer_detail,
                    credit_price,
                )
                st.session_state["df_cost_explorer_source"] = explorer_source
            except Exception as e:
                st.warning(f"Cost Explorer unavailable in this role/context: {format_snowflake_error(e)}")

        detail = st.session_state.get("df_cost_explorer_detail")
        if detail is not None and not detail.empty:
            detail = _normalize_cost_explorer_detail(detail, credit_price)
            if min_est_cost > 0 and "EST_COST" in detail.columns:
                detail = detail[detail["EST_COST"] >= float(min_est_cost)].copy()
            if detail.empty:
                st.info("No cost rows match the current minimum-cost threshold.")
            else:
                summary = _cost_explorer_summary(detail, explorer_lens)
                gap_board = _cost_explorer_gap_board(detail, summary)
                total_cost = safe_float(detail["EST_COST"].sum())
                total_credits = safe_float(detail["TOTAL_CREDITS"].sum())
                denominator = max(total_cost, 0.01)
                readiness = detail["CHARGEBACK_READY"].fillna("").astype(str).str.upper()
                owner_source = detail["OWNER_SOURCE"].fillna("").astype(str).str.upper()
                database = detail["DATABASE_NAME"].fillna("").astype(str).str.upper()
                no_context = database.isin(NO_DATABASE_CONTEXT_VALUES) | detail["ENVIRONMENT_ROLLUP"].fillna("").astype(str).str.upper().eq("NO DATABASE CONTEXT")
                ready_cost = safe_float(detail.loc[readiness.eq("READY"), "EST_COST"].sum())
                tag_cost = safe_float(detail.loc[owner_source.str.contains("TAG", na=False), "EST_COST"].sum())
                no_context_cost = safe_float(detail.loc[no_context, "EST_COST"].sum())
                top_share = safe_float(summary.iloc[0].get("PCT_OF_COST")) if not summary.empty else 0.0

                render_shell_snapshot((
                    ("Estimated spend", f"${total_cost:,.0f}"),
                    ("Allocated credits", format_credits(total_credits)),
                    ("Ready cost", f"{ready_cost / denominator * 100:.0f}%"),
                    ("Tag proof", f"{tag_cost / denominator * 100:.0f}%"),
                    ("No DB context", f"${no_context_cost:,.0f}"),
                    ("Top driver", f"{top_share:.0f}%"),
                ))
                defer_source_note(st.session_state.get(
                    "df_cost_explorer_source",
                    "Cost Explorer source: not loaded",
                ))

                render_chart_with_data_toggle(
                    f"Top {explorer_lens} cost drivers",
                    f"cc_explorer_{explorer_lens.lower().replace(' ', '_')}",
                    lambda: render_ranked_bar_chart(
                        summary,
                        "DIMENSION",
                        "EST_COST",
                        top_n=20,
                        color="#0ea5e9",
                    ),
                    summary,
                    priority_columns=[
                        "DIMENSION",
                        "EST_COST",
                        "PCT_OF_COST",
                        "TOTAL_CREDITS",
                        "QUERY_COUNT",
                        "ACTIVE_DAYS",
                        "USERS",
                        "ROLES",
                        "WAREHOUSES",
                        "DATABASES",
                        "ENVIRONMENTS",
                        "CHARGEBACK_READY",
                        "OWNER_PROOF",
                        "ALLOCATION_CONFIDENCE",
                        "FIRST_USAGE_DATE",
                        "LAST_USAGE_DATE",
                    ],
                    sort_by=["EST_COST", "TOTAL_CREDITS", "QUERY_COUNT"],
                    ascending=[False, False, False],
                    max_rows=30,
                    raw_label="All cost-drilldown rows",
                )
                defer_source_note("Cost Explorer bars are sorted highest to lowest by estimated cost; switch to Data for exact rows.")
                render_priority_dataframe(
                    gap_board,
                    title="Cost attribution gaps",
                    priority_columns=["GAP", "STATE", "EST_COST", "ROWS", "TOP_DRIVER", "ACTION"],
                    sort_by=["STATE", "EST_COST"],
                    ascending=[True, False],
                    max_rows=8,
                    raw_label="All cost-attribution gaps",
                )
                render_priority_dataframe(
                    detail,
                    title="Cost explorer detail",
                    priority_columns=[
                        "COMPANY",
                        "ENVIRONMENT_ROLLUP",
                        "DATABASE_NAME",
                        "DEPARTMENT",
                        "WAREHOUSE_NAME",
                        "USER_NAME",
                        "ROLE_NAME",
                        "TOTAL_CREDITS",
                        "EST_COST",
                        "QUERY_COUNT",
                        "ALLOCATION_CONFIDENCE",
                        "CHARGEBACK_READY",
                        "OWNER_SOURCE",
                        "FIRST_USAGE_DATE",
                        "LAST_USAGE_DATE",
                    ],
                    sort_by=["EST_COST", "TOTAL_CREDITS", "QUERY_COUNT"],
                    ascending=[False, False, False],
                    max_rows=40,
                    raw_label="Raw Cost Explorer detail",
                )
                download_csv(detail, "cost_explorer_detail.csv")
                if st.button("Save cost explorer outliers to Action Queue", key="cc_explorer_queue"):
                    _queue_cost_outliers(session, detail, credit_price, "Cost & Contract - Cost Explorer")

    elif cost_view == "Explain This Bill":
        st.subheader("Explain This Bill")
        st.caption("Start here when someone asks why Snowflake spend moved.")
        defer_source_note(
            "Warehouse totals use exact ACCOUNT_USAGE metering; user and query drivers are allocated estimates."
        )
        explain_period = st.selectbox(
            "Bill period",
            [
                "Last complete day",
                "Last 7 complete days",
                "Last 30 complete days",
                "Current month to date",
                "Previous month",
            ],
            index=1,
            key="cc_explain_period",
        )
        explain_budget = st.number_input(
            "Optional budget for this period ($)",
            min_value=0.0,
            value=0.0,
            step=100.0,
            key="cc_explain_budget",
        )
        bounds = _bill_period_bounds(explain_period)
        use_mart_summary = not any([
            st.session_state.get("global_user"),
            st.session_state.get("global_role"),
            st.session_state.get("global_database"),
            st.session_state.get("global_schema"),
        ])
        warehouse_contains = str(st.session_state.get("global_warehouse") or "").strip()
        wh_filter_meter = " ".join(filter(None, [
            get_wh_filter_clause("warehouse_name"),
            get_global_wh_filter_clause("warehouse_name"),
        ]))
        wh_filter_query = get_global_filter_clause(
            "",
            "q.warehouse_name",
            "q.user_name",
            "q.role_name",
            "q.database_name",
            "q.schema_name",
        )
        attribution_only_filters = [
            name for name, value in {
                "user": st.session_state.get("global_user"),
                "role": st.session_state.get("global_role"),
                "database": st.session_state.get("global_database"),
                "schema": st.session_state.get("global_schema"),
            }.items()
            if value
        ]
        if attribution_only_filters:
            st.warning(
                "User, role, database, and schema filters narrow attribution rows only. "
                "Exact warehouse metering can be scoped only by company and warehouse."
            )
        explain_filter_signature = (
            st.session_state.get("global_warehouse"),
            st.session_state.get("global_user"),
            st.session_state.get("global_role"),
            st.session_state.get("global_database"),
            st.session_state.get("global_schema"),
        )

        if st.button("Explain Bill", key="cc_explain_load", type="primary"):
            try:
                live_summary_sql = f"""
                WITH bounds AS (
                    SELECT
                        {bounds['current_start']} AS current_start,
                        {bounds['current_end']} AS current_end,
                        {bounds['prior_start']} AS prior_start,
                        {bounds['prior_end']} AS prior_end
                ),
                metering AS (
                    SELECT 'CURRENT' AS period, warehouse_name, start_time, credits_used
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY, bounds
                    WHERE start_time >= current_start
                      AND start_time < current_end
                      {wh_filter_meter}
                    UNION ALL
                    SELECT 'PRIOR' AS period, warehouse_name, start_time, credits_used
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY, bounds
                    WHERE start_time >= prior_start
                      AND start_time < prior_end
                      {wh_filter_meter}
                )
                SELECT
                    period,
                    ROUND(SUM(credits_used), 4) AS credits,
                    COUNT(DISTINCT warehouse_name) AS active_warehouses,
                    COUNT(DISTINCT TO_DATE(start_time)) AS active_days
                FROM metering
                GROUP BY period
                """
                live_wh_delta_sql = f"""
                WITH bounds AS (
                    SELECT
                        {bounds['current_start']} AS current_start,
                        {bounds['current_end']} AS current_end,
                        {bounds['prior_start']} AS prior_start,
                        {bounds['prior_end']} AS prior_end
                ),
                current_wh AS (
                    SELECT warehouse_name, SUM(credits_used) AS credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY, bounds
                    WHERE start_time >= current_start
                      AND start_time < current_end
                      {wh_filter_meter}
                    GROUP BY warehouse_name
                ),
                prior_wh AS (
                    SELECT warehouse_name, SUM(credits_used) AS credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY, bounds
                    WHERE start_time >= prior_start
                      AND start_time < prior_end
                      {wh_filter_meter}
                    GROUP BY warehouse_name
                )
                SELECT
                    COALESCE(c.warehouse_name, p.warehouse_name) AS warehouse_name,
                    ROUND(COALESCE(c.credits, 0), 4) AS current_credits,
                    ROUND(COALESCE(p.credits, 0), 4) AS prior_credits,
                    ROUND(COALESCE(c.credits, 0) - COALESCE(p.credits, 0), 4) AS credit_delta,
                    CASE
                        WHEN COALESCE(p.credits, 0) = 0 THEN NULL
                        ELSE ROUND(((COALESCE(c.credits, 0) - p.credits) / NULLIF(p.credits, 0)) * 100, 2)
                    END AS pct_delta
                FROM current_wh c
                FULL OUTER JOIN prior_wh p ON c.warehouse_name = p.warehouse_name
                ORDER BY ABS(COALESCE(c.credits, 0) - COALESCE(p.credits, 0)) DESC
                LIMIT 25
                """
                if use_mart_summary:
                    summary_sql = build_mart_bill_summary_sql(
                        bounds["current_start"],
                        bounds["current_end"],
                        bounds["prior_start"],
                        bounds["prior_end"],
                        company=company,
                        warehouse_contains=warehouse_contains,
                    )
                    wh_delta_sql = build_mart_bill_warehouse_delta_sql(
                        bounds["current_start"],
                        bounds["current_end"],
                        bounds["prior_start"],
                        bounds["prior_end"],
                        company=company,
                        warehouse_contains=warehouse_contains,
                    )
                    bill_summary_source = "Fast billing summary"
                else:
                    summary_sql = live_summary_sql
                    wh_delta_sql = live_wh_delta_sql
                    bill_summary_source = "Live fallback: WAREHOUSE_METERING_HISTORY"
                driver_sql = f"""
                WITH bounds AS (
                    SELECT
                        {bounds['current_start']} AS current_start,
                        {bounds['current_end']} AS current_end
                ),
                {build_metered_credit_cte(days_back=bounds['days_back'], include_recent=False)}
                SELECT
                    q.user_name,
                    q.role_name,
                    q.warehouse_name,
                    {max_wh_size_expr} AS warehouse_size,
                    COUNT(*) AS query_count,
                    ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS total_credits,
                    ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS allocated_credits,
                    ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_execution_seconds,
                    ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
                    ROUND({bytes_scanned_sum_expr} / POWER(1024, 3), 2) AS gb_scanned
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                CROSS JOIN bounds
                WHERE q.start_time >= current_start
                  AND q.start_time < current_end
                  AND q.warehouse_name IS NOT NULL
                  {wh_filter_query}
                GROUP BY q.user_name, q.role_name, q.warehouse_name
                ORDER BY allocated_credits DESC
                LIMIT 50
                """
                type_sql = f"""
                WITH bounds AS (
                    SELECT
                        {bounds['current_start']} AS current_start,
                        {bounds['current_end']} AS current_end
                ),
                {build_metered_credit_cte(days_back=bounds['days_back'], include_recent=False)}
                SELECT
                    COALESCE(q.query_type, 'UNKNOWN') AS query_type,
                    COUNT(*) AS query_count,
                    ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS total_credits,
                    ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS allocated_credits,
                    ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_execution_seconds,
                    ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
                    ROUND({bytes_scanned_sum_expr} / POWER(1024, 3), 2) AS gb_scanned
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                CROSS JOIN bounds
                WHERE q.start_time >= current_start
                  AND q.start_time < current_end
                  AND q.warehouse_name IS NOT NULL
                  {wh_filter_query}
                GROUP BY COALESCE(q.query_type, 'UNKNOWN')
                ORDER BY allocated_credits DESC
                LIMIT 25
                """
                environment_sql = f"""
                WITH bounds AS (
                    SELECT
                        {bounds['current_start']} AS current_start,
                        {bounds['current_end']} AS current_end
                ),
                {build_metered_credit_cte(days_back=bounds['days_back'], include_recent=False)}
                SELECT
                    {get_environment_case_expr("q.database_name")} AS environment,
                    COALESCE(q.database_name, 'NO_DATABASE_CONTEXT') AS database_name,
                    COUNT(*) AS query_count,
                    COUNT(DISTINCT q.user_name) AS users,
                    COUNT(DISTINCT q.warehouse_name) AS warehouses,
                    ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS allocated_credits,
                    ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
                    ROUND({bytes_scanned_sum_expr} / POWER(1024, 3), 2) AS gb_scanned
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                CROSS JOIN bounds
                WHERE q.start_time >= current_start
                  AND q.start_time < current_end
                  AND q.warehouse_name IS NOT NULL
                  AND q.database_name IS NOT NULL
                  {wh_filter_query}
                GROUP BY 1, 2
                ORDER BY allocated_credits DESC
                LIMIT 100
                """
                service_sql = f"""
                WITH bounds AS (
                    SELECT
                        {bounds['current_start']} AS current_start,
                        {bounds['current_end']} AS current_end,
                        {bounds['prior_start']} AS prior_start,
                        {bounds['prior_end']} AS prior_end
                ),
                metering AS (
                    SELECT 'CURRENT' AS period, service_type, start_time, credits_used
                    FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY, bounds
                    WHERE start_time >= current_start
                      AND start_time < current_end
                    UNION ALL
                    SELECT 'PRIOR' AS period, service_type, start_time, credits_used
                    FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY, bounds
                    WHERE start_time >= prior_start
                      AND start_time < prior_end
                )
                SELECT
                    period,
                    COALESCE(service_type, 'UNKNOWN') AS service_type,
                    ROUND(SUM(COALESCE(credits_used, 0)), 4) AS credits
                FROM metering
                GROUP BY period, COALESCE(service_type, 'UNKNOWN')
                ORDER BY period, credits DESC
                """
                st.session_state["cc_explain_summary"] = run_query(
                    summary_sql,
                    ttl_key=f"cc_explain_summary_{company}_{explain_period}_{'mart' if use_mart_summary else 'live'}",
                    tier="standard",
                )
                if use_mart_summary and st.session_state["cc_explain_summary"].empty:
                    bill_summary_source = "Live fallback: fast summary unavailable or stale"
                    st.session_state["cc_explain_summary"] = run_query(
                        live_summary_sql,
                        ttl_key=f"cc_explain_summary_{company}_{explain_period}_fallback",
                        tier="standard",
                    )
                st.session_state["cc_explain_wh_delta"] = run_query(
                    wh_delta_sql,
                    ttl_key=f"cc_explain_wh_{company}_{explain_period}_{'mart' if use_mart_summary else 'live'}",
                    tier="standard",
                )
                if use_mart_summary and st.session_state["cc_explain_wh_delta"].empty:
                    st.session_state["cc_explain_wh_delta"] = run_query(
                        live_wh_delta_sql,
                        ttl_key=f"cc_explain_wh_{company}_{explain_period}_fallback",
                        tier="standard",
                    )
                st.session_state["cc_explain_drivers"] = run_query(
                    driver_sql,
                    ttl_key=f"cc_explain_drivers_{company}_{explain_period}",
                    tier="standard",
                )
                st.session_state["cc_explain_types"] = run_query(
                    type_sql,
                    ttl_key=f"cc_explain_types_{company}_{explain_period}",
                    tier="standard",
                )
                st.session_state["cc_explain_environments"] = run_query(
                    environment_sql,
                    ttl_key=(
                        f"cc_explain_env_{company}_{explain_period}_"
                        f"{get_active_environment()}_{st.session_state.get('global_database', '')}"
                    ),
                    tier="standard",
                )
                try:
                    st.session_state["cc_explain_services"] = run_query(
                        service_sql,
                        ttl_key=f"cc_explain_services_{explain_period}",
                        tier="standard",
                    )
                    st.session_state["cc_explain_service_error"] = ""
                except Exception as service_error:
                    st.session_state["cc_explain_services"] = pd.DataFrame()
                    st.session_state["cc_explain_service_error"] = format_snowflake_error(service_error)
                st.session_state["cc_explain_meta"] = {
                    "company": company,
                    "period": explain_period,
                    "credit_price": credit_price,
                    "filters": explain_filter_signature,
                    "summary_source": bill_summary_source,
                }
            except Exception as e:
                st.error(f"Unable to explain bill: {format_snowflake_error(e)}")

        summary = st.session_state.get("cc_explain_summary")
        wh_deltas = st.session_state.get("cc_explain_wh_delta")
        drivers = st.session_state.get("cc_explain_drivers")
        type_drivers = st.session_state.get("cc_explain_types")
        environment_drivers = st.session_state.get("cc_explain_environments")
        service_drivers = st.session_state.get("cc_explain_services")
        service_error = st.session_state.get("cc_explain_service_error", "")
        explain_meta = st.session_state.get("cc_explain_meta", {})
        has_current_explain = (
            explain_meta.get("company") == company
            and explain_meta.get("period") == explain_period
            and explain_meta.get("filters") == explain_filter_signature
            and summary is not None
            and not summary.empty
        )
        if has_current_explain:
            current_row = summary[summary["PERIOD"] == "CURRENT"]
            prior_row = summary[summary["PERIOD"] == "PRIOR"]
            current_credits = safe_float(_first_value(current_row, "CREDITS", 0))
            prior_credits = safe_float(_first_value(prior_row, "CREDITS", 0))
            current_cost = credits_to_dollars(current_credits, credit_price)
            prior_cost = credits_to_dollars(prior_credits, credit_price)
            delta_credits = current_credits - prior_credits
            delta_cost = current_cost - prior_cost
            delta_pct = _pct_delta(current_credits, prior_credits)
            active_warehouses = int(_first_value(current_row, "ACTIVE_WAREHOUSES", 0) or 0)
            allocated_credits = (
                safe_float(drivers["ALLOCATED_CREDITS"].sum())
                if drivers is not None and not drivers.empty else 0.0
            )
            unallocated_credits = max(0.0, current_credits - allocated_credits)
            unallocated_pct = (unallocated_credits / current_credits * 100) if current_credits else 0.0

            bill_metrics = [
                ("Current Spend", f"${current_cost:,.2f} ({delta_cost:+,.2f})"),
                ("Current Credits", f"{format_credits(current_credits)} ({delta_credits:+,.2f})"),
                ("Change vs Baseline", _fmt_delta(delta_pct)),
                ("Active Warehouses", f"{active_warehouses:,}"),
            ]
            if explain_budget > 0:
                budget_delta = current_cost - explain_budget
                bill_metrics.append(
                    (
                        "Budget Variance",
                        f"${budget_delta:+,.2f} {'over' if budget_delta > 0 else 'under'} budget",
                    )
                )
            render_shell_snapshot(tuple(bill_metrics))

            defer_source_note(
                f"{metric_confidence_label('exact')} for warehouse totals | "
                f"{metric_confidence_label('allocated')} for user/query attribution | "
                f"{explain_meta.get('summary_source', 'Live fallback: WAREHOUSE_METERING_HISTORY')} | "
                f"{freshness_note('ACCOUNT_USAGE')}"
            )

            if delta_credits > 0:
                st.warning(
                    f"Spend increased by {delta_credits:,.2f} credits "
                    f"(${delta_cost:,.2f}) compared with the prior comparable period."
                )
            elif delta_credits < 0:
                st.success(
                    f"Spend decreased by {abs(delta_credits):,.2f} credits "
                    f"(${abs(delta_cost):,.2f}) compared with the prior comparable period."
                )
            else:
                st.info("Spend held flat versus the prior comparable period.")

            gap_level = "material" if unallocated_pct >= 20 else "moderate" if unallocated_pct >= 10 else "low"
            st.info(
                f"Unallocated / idle / service-overhead gap is {unallocated_credits:,.2f} credits "
                f"({unallocated_pct:.1f}% of exact warehouse credits), which is {gap_level}."
            )
            if service_error:
                st.warning(f"Account-wide service credits were unavailable: {service_error}")

            finance_summary = _build_finance_movement_summary(
                current_credits=current_credits,
                prior_credits=prior_credits,
                allocated_credits=allocated_credits,
                unallocated_credits=unallocated_credits,
                service_drivers=service_drivers,
                credit_price=credit_price,
                budget=explain_budget,
            )
            st.subheader("Finance Movement Summary")
            defer_source_note(
                "This bridge separates exact warehouse compute, allocated workload, estimated overhead, "
                "and account-wide service/serverless credits. It is designed for bill review and executive talking points."
            )
            render_priority_dataframe(
                finance_summary,
                title="Finance movement bridge",
                priority_columns=[
                    "Category", "Current Credits", "Prior Credits", "Delta Credits",
                    "Current Cost", "Delta Cost", "Source Basis", "Basis", "Action",
                ],
                sort_by=["Current Credits", "Delta Credits"],
                ascending=False,
                raw_label="All finance movement rows",
            )

            narrative = _bill_driver_summary(
                delta_credits=delta_credits,
                current_credits=current_credits,
                prior_credits=prior_credits,
                unallocated_pct=unallocated_pct,
                warehouse_deltas=wh_deltas,
                user_drivers=drivers,
                query_type_drivers=type_drivers,
            )
            st.subheader("Bill Narrative")
            n1, n2 = st.columns([1, 3])
            with n1:
                render_shell_snapshot((("Review Status", narrative["severity"]),))
            with n2:
                st.markdown(f"**{narrative['headline']}**")
                st.write(narrative["reason"])
                st.caption(narrative["caveat"])
                st.info(narrative["next_action"])

            waterfall = _build_bill_waterfall(
                wh_deltas,
                prior_credits=prior_credits,
                current_credits=current_credits,
                credit_price=credit_price,
            )
            st.subheader("Bill Movement Waterfall")
            defer_source_note(
                "Positive bars increased the bill; negative bars reduced it. "
                "Baseline and current total are exact warehouse-metering totals."
            )
            st.bar_chart(waterfall, x="Driver", y="Credits", color="Type")
            render_priority_dataframe(
                waterfall,
                title="Bill movement drivers",
                priority_columns=["Driver", "Credits", "Estimated Cost", "Type"],
                sort_by=["Credits"],
                ascending=False,
                raw_label="All bill movement rows",
            )

            if st.session_state.get("exceptions_only_mode"):
                st.subheader("Exceptions Only")
                if wh_deltas is not None and not wh_deltas.empty:
                    exception_rows = wh_deltas[
                        (wh_deltas["CREDIT_DELTA"].fillna(0) > 0)
                        | (wh_deltas["PCT_DELTA"].fillna(0).abs() >= 25)
                    ].copy()
                    if exception_rows.empty:
                        st.success("No warehouse bill exceptions crossed the default thresholds.")
                    else:
                        exception_rows = _annotate_cost_routes(exception_rows, "Warehouse Delta")
                        exception_rows["EST_DELTA_COST"] = exception_rows["CREDIT_DELTA"].apply(
                            lambda v: credits_to_dollars(v, credit_price)
                        )
                        render_priority_dataframe(
                            exception_rows,
                            title="Bill exceptions to explain first",
                            priority_columns=[
                                "WAREHOUSE_NAME", "CURRENT_CREDITS", "PRIOR_CREDITS",
                                "CREDIT_DELTA", "PCT_DELTA", "EST_DELTA_COST",
                                "NEXT_WORKFLOW", "NEXT_ACTION",
                            ],
                            sort_by=["CREDIT_DELTA", "PCT_DELTA"],
                            ascending=[False, False],
                            raw_label="All bill exception rows",
                        )
                else:
                    st.info("No warehouse delta rows available.")
                st.stop()

            wh_delta_view = _annotate_cost_routes(wh_deltas, "Warehouse Delta")
            render_chart_with_data_toggle(
                "Warehouse cost movement to explain first",
                "cc_explain_wh_delta",
                lambda: render_drillable_bar_chart(
                    wh_deltas.sort_values("CREDIT_DELTA", ascending=False).head(15)
                    if wh_deltas is not None and not wh_deltas.empty else wh_deltas,
                    dimension="WAREHOUSE_NAME",
                    measure="CREDIT_DELTA",
                    key="cc_explain_wh_delta_chart",
                    drilldown_column="warehouse_name",
                    lookback_hours=bounds["days_back"] * 24,
                ),
                wh_delta_view,
                priority_columns=[
                    "WAREHOUSE_NAME", "CURRENT_CREDITS", "PRIOR_CREDITS",
                    "CREDIT_DELTA", "PCT_DELTA", "NEXT_WORKFLOW", "NEXT_ACTION",
                ],
                sort_by=["CREDIT_DELTA", "PCT_DELTA"],
                ascending=[False, False],
                raw_label="All warehouse delta rows",
            )

            st.subheader("Top User / Warehouse Drivers")
            render_priority_dataframe(
                _annotate_cost_routes(drivers, "User Cost"),
                title="User and warehouse spend drivers",
                priority_columns=[
                    "USER_NAME", "WAREHOUSE_NAME", "TOTAL_CREDITS", "QUERY_COUNT",
                    "AVG_EXECUTION_SECONDS", "NEXT_WORKFLOW", "NEXT_ACTION",
                ],
                sort_by=["TOTAL_CREDITS", "QUERY_COUNT"],
                ascending=[False, False],
                raw_label="All user/warehouse driver rows",
            )

            st.subheader("Top Query-Type Drivers")
            render_priority_dataframe(
                _annotate_cost_routes(type_drivers, "Query Type Cost"),
                title="Query-type spend drivers",
                priority_columns=[
                    "QUERY_TYPE", "TOTAL_CREDITS", "QUERY_COUNT",
                    "AVG_EXECUTION_SECONDS", "NEXT_WORKFLOW", "NEXT_ACTION",
                ],
                sort_by=["TOTAL_CREDITS", "QUERY_COUNT"],
                ascending=[False, False],
                raw_label="All query-type driver rows",
            )

            st.subheader("PROD vs DEV Cost Split")
            defer_source_note(
                f"{metric_confidence_label('allocated')} | Shared warehouses mean exact WAREHOUSE_METERING_HISTORY "
                "cannot split PROD and DEV by itself. This view allocates metered credits to query database context, "
                "then rolls ALFA_EDW_PROD separately from ALFA_EDW_DEV/SAN/PHX/SEA/SIT."
            )
            if environment_drivers is not None and not environment_drivers.empty:
                env_display = _annotate_allocation_quality(environment_drivers)
                env_display["EST_COST"] = env_display["ALLOCATED_CREDITS"].apply(
                    lambda x: credits_to_dollars(x, credit_price)
                )
                env_summary = (
                    env_display.groupby(
                        ["ENVIRONMENT_ROLLUP", "ALLOCATION_CONFIDENCE", "CHARGEBACK_READY"],
                        as_index=False,
                    )[
                        ["ALLOCATED_CREDITS", "EST_COST", "QUERY_COUNT", "USERS", "WAREHOUSES", "GB_SCANNED"]
                    ]
                    .sum()
                    .sort_values("EST_COST", ascending=False)
                )
                render_shell_snapshot(tuple(
                    (
                        str(row["ENVIRONMENT_ROLLUP"]),
                        f"${safe_float(row['EST_COST']):,.2f} ({safe_float(row['ALLOCATED_CREDITS']):,.2f} cr)",
                    )
                    for _, row in env_summary.head(4).iterrows()
                ))
                render_priority_dataframe(
                    env_summary,
                    title="Environment cost rollup",
                    priority_columns=[
                        "ENVIRONMENT_ROLLUP", "ALLOCATION_CONFIDENCE", "CHARGEBACK_READY",
                        "ALLOCATED_CREDITS", "EST_COST", "QUERY_COUNT", "USERS", "WAREHOUSES", "GB_SCANNED",
                    ],
                    sort_by=["EST_COST", "ALLOCATED_CREDITS"],
                    ascending=[False, False],
                    raw_label="All environment rollup rows",
                )
                dev_detail = env_display[env_display["ENVIRONMENT_ROLLUP"] == "DEV_ALL"]
                if not dev_detail.empty:
                    render_priority_dataframe(
                        dev_detail,
                        title="Individual DEV database cost",
                        priority_columns=[
                            "ENVIRONMENT", "DATABASE_NAME", "ALLOCATED_CREDITS", "EST_COST",
                            "QUERY_COUNT", "USERS", "WAREHOUSES", "ALLOCATION_CONFIDENCE", "GB_SCANNED",
                        ],
                        sort_by=["EST_COST", "ALLOCATED_CREDITS"],
                        ascending=[False, False],
                        raw_label="All individual DEV database rows",
                    )
                render_priority_dataframe(
                    env_display,
                    title="Environment cost by database",
                    priority_columns=[
                        "ENVIRONMENT_ROLLUP", "ENVIRONMENT", "DATABASE_NAME",
                        "ALLOCATION_CONFIDENCE", "CHARGEBACK_READY", "SCOPE_REVIEW",
                        "ALLOCATED_CREDITS", "EST_COST", "QUERY_COUNT", "USERS",
                        "WAREHOUSES", "AVG_ELAPSED_SEC", "GB_SCANNED",
                    ],
                    sort_by=["EST_COST", "ALLOCATED_CREDITS"],
                    ascending=[False, False],
                    raw_label="All environment/database rows",
                )
            else:
                st.info(
                    "No database-scoped query cost was available for this period. "
                    "Try a wider period or clear the database/environment filter."
                )

            st.subheader("Account-Wide Service / Serverless Contributors")
            defer_source_note(
                f"{metric_confidence_label('account-wide')} | "
                "METERING_HISTORY service credits are not company-scoped by warehouse. "
                "Use tags, ownership standards, or service-specific lineage before chargeback."
            )
            if service_drivers is not None and not service_drivers.empty:
                service_display = service_drivers.copy()
                service_display["CATEGORY"] = service_display["SERVICE_TYPE"].apply(_service_cost_category)
                service_display = _annotate_cost_routes(service_display, "Service Cost")
                render_priority_dataframe(
                    service_display,
                    title="Service and serverless contributors",
                    priority_columns=[
                        "SERVICE_TYPE", "CATEGORY", "CREDITS_USED", "EST_COST",
                        "NEXT_WORKFLOW", "NEXT_ACTION",
                    ],
                    sort_by=["CREDITS_USED"],
                    ascending=False,
                    raw_label="All service contributor rows",
                )
            else:
                st.info("No service/serverless contributor rows were available for this period.")

            report_md = _build_explain_bill_markdown(
                company=company,
                period_label=bounds["label"],
                current_credits=current_credits,
                prior_credits=prior_credits,
                credit_price=credit_price,
                active_warehouses=active_warehouses,
                allocated_credits=allocated_credits,
                unallocated_credits=unallocated_credits,
                warehouse_deltas=wh_deltas,
                user_drivers=drivers,
                query_type_drivers=type_drivers,
                service_drivers=service_drivers,
            )
            st.download_button(
                "Download Bill Explanation",
                report_md,
                file_name=f"overwatch_bill_explanation_{company.lower()}.md",
                mime="text/markdown",
                key="cc_explain_download",
            )
            if st.button("Save Bill Exceptions to Action Queue", key="cc_explain_queue"):
                _queue_bill_exceptions(session, wh_deltas, credit_price, bounds["label"])

    elif cost_view == "User Leaderboard":
        st.subheader("Credit Cost by User / Warehouse")
        days = day_window_selectbox("Lookback", key="cc_lead_days", default=30)
        gf = get_global_filter_clause(
            "q.start_time", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name", "q.schema_name"
        )

        if st.button("Load Leaderboard", key="cc_lead_load"):
            try:
                df_lead = run_query(f"""
                WITH {build_metered_credit_cte(days_back=days)}
                SELECT
                    q.user_name,
                    q.warehouse_name,
                    {max_wh_size_expr} AS warehouse_size,
                    COUNT(*)                                     AS query_count,
                    ROUND(AVG(q.total_elapsed_time)/1000, 2)    AS avg_elapsed_sec,
                    ROUND(SUM(pqc.metered_credits), 4)          AS total_credits,
                    ROUND({bytes_scanned_sum_expr}/POWER(1024,3),2) AS total_gb_scanned
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND q.warehouse_name IS NOT NULL
                  {gf}
                GROUP BY q.user_name, q.warehouse_name
                ORDER BY total_credits DESC
                LIMIT 200
                """, ttl_key=f"cc_lead_{company}_{days}", tier="standard")
                st.session_state["df_lead"] = df_lead
            except Exception as e:
                st.warning(f"Cost leaderboard unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("df_lead") is not None and not st.session_state["df_lead"].empty:
            df_l = st.session_state["df_lead"]
            df_l["COST"] = df_l["TOTAL_CREDITS"].apply(lambda x: credits_to_dollars(x, credit_price))
            render_shell_snapshot((
                ("Distinct Users", df_l["USER_NAME"].nunique()),
                ("Total Credits", format_credits(df_l["TOTAL_CREDITS"].sum())),
                ("Total Est. Cost", f"${df_l['COST'].sum():,.2f}"),
            ))
            defer_source_note(metric_confidence_label("allocated"), freshness_note("ACCOUNT_USAGE"))

            st.subheader("Top Users by Cost")
            df_l = _annotate_cost_routes(df_l, "User Cost")
            user_agg = (
                df_l.groupby("USER_NAME")["COST"]
                .sum().reset_index()
                .sort_values("COST", ascending=False)
                .head(20)
            )
            render_chart_with_data_toggle(
                "Cost leaderboard drivers",
                "cc_user_cost_driver",
                lambda: render_drillable_bar_chart(
                    user_agg,
                    dimension="USER_NAME",
                    measure="COST",
                    key="cc_user_cost",
                    drilldown_column="user_name",
                    lookback_hours=days * 24,
                ),
                df_l,
                priority_columns=[
                    "USER_NAME",
                    "WAREHOUSE_NAME",
                    "WAREHOUSE_SIZE",
                    "TOTAL_CREDITS",
                    "COST",
                    "QUERY_COUNT",
                    "AVG_ELAPSED_SEC",
                    "TOTAL_GB_SCANNED",
                    "NEXT_WORKFLOW",
                    "NEXT_ACTION",
                ],
                sort_by=["TOTAL_CREDITS", "COST", "QUERY_COUNT"],
                ascending=[False, False, False],
                raw_label="All user/warehouse cost rows",
            )

            # User profile drill-through
            st.divider()
            st.subheader("User Profile Drill-Down")
            if "USER_NAME" in df_l.columns:
                user_options = [""] + df_l["USER_NAME"].dropna().astype(str).unique().tolist()
                user_col, load_col = st.columns([4, 1])
                with user_col:
                    sel_user = st.selectbox(
                        "Select user for full query breakdown",
                        user_options,
                        key="cc_user_profile_sel",
                        format_func=lambda value: "(select user)" if not value else str(value),
                    )
                with load_col:
                    st.write("")
                    if st.button("Load", key="cc_user_profile_load", width="stretch", disabled=not bool(sel_user)):
                        st.session_state["cc_user_profile_requested"] = sel_user
                if (
                    sel_user
                    and st.session_state.get("cc_user_profile_requested") == sel_user
                ):
                    render_entity_query_drilldown(
                        sel_user, key="cc_user_profile",
                        entity_column="user_name", lookback_hours=days * 24,
                    )

            download_csv(df_l, "cost_leaderboard.csv")
            if st.button("Save top cost outliers to Action Queue", key="cc_lead_queue"):
                _queue_cost_outliers(session, df_l, credit_price, "Cost & Contract - User Leaderboard")

    # -- BURN RATE -------------------------------------------------------------
    elif cost_view == "Burn Rate":
        st.subheader("Credit Burn Rate")
        br_days = day_window_selectbox("Lookback", key="br_days", default=30)
        if st.button("Load Burn Rate", key="br_load"):
            try:
                df_br = run_query(f"""
                    WITH latest_size AS (
                        SELECT warehouse_name, warehouse_size
                        FROM (
                            SELECT warehouse_name, {wh_size_plain_expr},
                            ROW_NUMBER() OVER (PARTITION BY warehouse_name ORDER BY start_time DESC) AS rn
                            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                            WHERE start_time >= DATEADD('day', -{br_days}, CURRENT_TIMESTAMP())
                              AND warehouse_name IS NOT NULL
                              {get_wh_filter_clause("warehouse_name")}
                        )
                        WHERE rn = 1
                    )
                    SELECT DATE_TRUNC('day', m.start_time) AS day,
                           m.warehouse_name,
                           ls.warehouse_size,
                           SUM(m.credits_used) AS daily_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY m
                    LEFT JOIN latest_size ls ON m.warehouse_name = ls.warehouse_name
                    WHERE m.start_time >= DATEADD('day', -{br_days}, CURRENT_TIMESTAMP())
                    {get_wh_filter_clause("m.warehouse_name")}
                    GROUP BY day, m.warehouse_name, ls.warehouse_size
                    ORDER BY day
                """, ttl_key=f"cc_burn_{company}_{br_days}", tier="standard")
                st.session_state["df_br"] = df_br
            except Exception as e:
                st.warning(f"Burn-rate data unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("df_br") is not None and not st.session_state["df_br"].empty:
            df_b = st.session_state["df_br"]
            total_cr = df_b["DAILY_CREDITS"].sum()
            render_shell_snapshot((
                ("Total Credits", format_credits(total_cr)),
                ("Total Cost", f"${credits_to_dollars(total_cr, credit_price):,.2f}"),
                ("Avg Daily Credits", f"{total_cr / max(br_days,1):,.2f}"),
            ))
            defer_source_note(metric_confidence_label("exact"), freshness_note("WAREHOUSE_METERING_HISTORY"))
            daily = df_b.groupby("DAY")["DAILY_CREDITS"].sum().reset_index()
            st.line_chart(daily.set_index("DAY")["DAILY_CREDITS"])
            by_wh = (
                df_b.groupby("WAREHOUSE_NAME")["DAILY_CREDITS"]
                .sum().reset_index()
                .sort_values("DAILY_CREDITS", ascending=False)
            )
            st.subheader("Credits by Warehouse")
            render_drillable_bar_chart(
                by_wh, dimension="WAREHOUSE_NAME", measure="DAILY_CREDITS",
                key="cc_wh_credits", drilldown_column="warehouse_name",
                lookback_hours=br_days * 24,
            )
            download_csv(df_b, "burn_rate.csv")

    # -- COST RECONCILIATION -------------------------------------------------
    elif cost_view == "Reconciliation":
        st.subheader("Cost Reconciliation")
        defer_source_note(
            "Compares exact warehouse metering to query-level allocated credits. "
            "Large variances usually mean idle warehouse time, non-query activity, latency, or chargeback assumptions need review."
        )
        recon_days = day_window_selectbox("Reconciliation window", key="cc_recon_days", default=30)
        if st.button("Load Reconciliation", key="cc_recon_load"):
            try:
                use_official_attribution = query_attribution_supported(session)
                st.session_state["df_cc_recon"] = run_query(
                    build_cost_reconciliation_sql(
                        recon_days,
                        prefer_query_attribution=use_official_attribution,
                    ),
                    ttl_key=f"cc_recon_{company}_{recon_days}_{int(use_official_attribution)}",
                    tier="standard",
                    section="Cost & Contract",
                )
                st.session_state["cc_recon_attribution_source"] = (
                    "QUERY_ATTRIBUTION_HISTORY preferred with OVERWATCH allocation fallback"
                    if use_official_attribution
                    else "OVERWATCH allocated fallback"
                )
            except Exception as e:
                st.warning(f"Cost reconciliation unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("df_cc_recon") is not None and not st.session_state["df_cc_recon"].empty:
            df_r = st.session_state["df_cc_recon"]
            total_exact = float(df_r["EXACT_METERED_CREDITS"].sum()) if "EXACT_METERED_CREDITS" in df_r.columns else 0.0
            total_alloc = float(df_r["ALLOCATED_QUERY_CREDITS"].sum()) if "ALLOCATED_QUERY_CREDITS" in df_r.columns else 0.0
            total_var = total_exact - total_alloc
            render_shell_snapshot((
                ("Exact Metered", format_credits(total_exact)),
                ("Allocated to Queries", format_credits(total_alloc)),
                ("Unallocated / Variance", format_credits(total_var)),
            ))
            defer_source_note(
                f"{metric_confidence_label('exact')} for metering; "
                f"{metric_confidence_label('allocated')} for query attribution. "
                f"Source: {st.session_state.get('cc_recon_attribution_source', 'OVERWATCH allocated fallback')} | "
                f"{freshness_note('WAREHOUSE_METERING_HISTORY')}"
            )
            if "RECONCILIATION_STATUS" in df_r.columns:
                status_counts = (
                    df_r["RECONCILIATION_STATUS"]
                    .value_counts()
                    .rename_axis("RECONCILIATION_STATUS")
                    .reset_index(name="WAREHOUSE_COUNT")
                )
                render_chart_with_data_toggle(
                    "Reconciliation Status",
                    "cc_reconciliation_status",
                    lambda: render_ranked_bar_chart(
                        status_counts,
                        "RECONCILIATION_STATUS",
                        "WAREHOUSE_COUNT",
                        top_n=10,
                    ),
                    status_counts,
                    priority_columns=["RECONCILIATION_STATUS", "WAREHOUSE_COUNT"],
                    sort_by=["WAREHOUSE_COUNT"],
                    ascending=False,
                    max_rows=10,
                )
            render_priority_dataframe(
                df_r,
                title="Reconciliation variances to review",
                priority_columns=[
                    "WAREHOUSE_NAME",
                    "EXACT_METERED_CREDITS",
                    "ALLOCATED_QUERY_CREDITS",
                    "OFFICIAL_ATTRIBUTED_COMPUTE_CREDITS",
                    "OVERWATCH_ALLOCATED_CREDITS",
                    "OFFICIAL_ATTRIBUTED_QUERIES",
                    "ATTRIBUTION_SOURCE",
                    "VARIANCE_CREDITS",
                    "VARIANCE_PCT",
                    "RECONCILIATION_STATUS",
                ],
                sort_by=["VARIANCE_CREDITS", "VARIANCE_PCT", "EXACT_METERED_CREDITS"],
                ascending=[False, False, False],
                raw_label="All reconciliation rows",
                height=420,
            )
            download_csv(df_r, "cost_reconciliation.csv")

    # -- FORECAST --------------------------------------------------------------
    elif cost_view == "Forecast":
        st.subheader("Credit Forecast (30-day Linear Projection)")
        if st.button("Generate Forecast", key="fc_load"):
            try:
                df_fc = run_query(f"""
                    SELECT DATE_TRUNC('day', start_time) AS day,
                           SUM(credits_used) AS daily_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                    WHERE start_time >= DATEADD('day', -30, CURRENT_TIMESTAMP())
                    {get_wh_filter_clause("warehouse_name")}
                    GROUP BY day ORDER BY day
                """, ttl_key=f"cc_forecast_30_{company}", tier="standard")
                st.session_state["df_fc"] = df_fc
            except Exception as e:
                st.warning(f"Forecast data unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("df_fc") is not None and not st.session_state["df_fc"].empty:
            df_f = st.session_state["df_fc"].copy()
            df_f["DAY"] = pd.to_datetime(df_f["DAY"])
            full_window = pd.DataFrame({
                "DAY": pd.date_range(
                    pd.Timestamp.today().normalize() - pd.Timedelta(days=29),
                    pd.Timestamp.today().normalize(),
                    freq="D",
                )
            })
            df_f = full_window.merge(df_f, on="DAY", how="left")
            df_f["DAILY_CREDITS"] = pd.to_numeric(df_f["DAILY_CREDITS"], errors="coerce").fillna(0)
            avg_daily = df_f["DAILY_CREDITS"].mean()
            proj_30   = avg_daily * 30
            proj_cost = credits_to_dollars(proj_30, credit_price)
            render_shell_snapshot((
                ("Avg Daily Credits", f"{avg_daily:.2f}"),
                ("Projected 30-day", format_credits(proj_30)),
                ("Projected 30-day Cost", f"${proj_cost:,.2f}"),
            ))
            st.area_chart(df_f.set_index("DAY")["DAILY_CREDITS"])

    # -- BUDGET VS ACTUAL ------------------------------------------------------
    elif cost_view == "Budget vs Actual":
        st.subheader("Budget vs Actual")
        monthly_budget = st.number_input(
            "Monthly credit budget", min_value=0, value=10000, step=500, key="bva_budget"
        )
        if st.button("Load Budget Comparison", key="bva_load"):
            try:
                df_bva = run_query(f"""
                    SELECT DATE_TRUNC('month', start_time) AS month,
                           SUM(credits_used) AS actual_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                    WHERE start_time >= DATEADD('month', -6, CURRENT_TIMESTAMP())
                    {get_wh_filter_clause("warehouse_name")}
                    GROUP BY month ORDER BY month
                """, ttl_key=f"cc_budget_6mo_{company}", tier="standard")
                st.session_state["df_bva"] = df_bva
            except Exception as e:
                st.warning(f"Budget comparison unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("df_bva") is not None and not st.session_state["df_bva"].empty:
            df_bv = st.session_state["df_bva"]
            df_bv["BUDGET"]    = monthly_budget
            df_bv["OVER_UNDER"] = df_bv["ACTUAL_CREDITS"] - monthly_budget
            df_bv["STATUS"]    = df_bv["OVER_UNDER"].apply(
                lambda x: "Over" if x > 0 else "Under"
            )
            render_priority_dataframe(
                df_bv,
                title="Budget months to explain",
                priority_columns=["MONTH", "ACTUAL_CREDITS", "BUDGET", "OVER_UNDER", "STATUS"],
                sort_by=["OVER_UNDER", "ACTUAL_CREDITS"],
                ascending=[False, False],
                raw_label="All budget comparison rows",
            )
            st.bar_chart(df_bv.set_index("MONTH")[["ACTUAL_CREDITS","BUDGET"]])
            download_csv(df_bv, "budget_vs_actual.csv")

    # -- ATTRIBUTION -----------------------------------------------------------
    elif cost_view == "Attribution":
        st.subheader("Cost Attribution")
        attr_days = day_window_selectbox("Lookback", key="cc_attr_days", default=30)
        attr_mode = st.selectbox(
            "Attribution dimension",
            ["Role", "Database / Schema", "Application / Client", "Stored Procedure / Task Lineage"],
            key="cc_attr_mode",
        )
        gf = get_global_filter_clause(
            "q.start_time", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name"
        )

        if st.button("Load Attribution", key="cc_attr_load"):
            if attr_mode == "Role":
                select_cols = "COALESCE(q.role_name, 'UNKNOWN') AS dimension"
                group_cols  = "COALESCE(q.role_name, 'UNKNOWN')"
            elif attr_mode == "Database / Schema":
                select_cols = "COALESCE(q.database_name,'UNKNOWN')||'.'||COALESCE(q.schema_name,'UNKNOWN') AS dimension"
                group_cols  = "COALESCE(q.database_name,'UNKNOWN')||'.'||COALESCE(q.schema_name,'UNKNOWN')"
            elif attr_mode == "Application / Client":
                select_cols = f"{query_tag_dimension_expr} AS dimension"
                group_cols  = query_tag_dimension_expr
            else:
                select_cols = "COALESCE(REGEXP_SUBSTR(q.query_text,'CALL\\\\s+([^\\\\(]+)',1,1,'i',1), q.query_type, 'ADHOC') AS dimension"
                group_cols  = "COALESCE(REGEXP_SUBSTR(q.query_text,'CALL\\\\s+([^\\\\(]+)',1,1,'i',1), q.query_type, 'ADHOC')"

            try:
                df_attr = run_query(f"""
                WITH {build_metered_credit_cte(days_back=attr_days)}
                SELECT {select_cols},
                       COUNT(*) AS query_count,
                       COUNT(DISTINCT q.user_name)      AS users,
                       COUNT(DISTINCT q.warehouse_name) AS warehouses,
                       ROUND(SUM(COALESCE(pqc.metered_credits,0)),4) AS total_credits,
                       ROUND({bytes_scanned_sum_expr}/POWER(1024,3),2)   AS gb_scanned
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                WHERE q.start_time >= DATEADD('day', -{attr_days}, CURRENT_TIMESTAMP())
                  AND q.warehouse_name IS NOT NULL
                  {gf}
                GROUP BY {group_cols}
                ORDER BY total_credits DESC
                LIMIT 200
                """, ttl_key=f"cc_attr_{company}_{attr_mode}_{attr_days}", tier="standard")
                st.session_state["df_cc_attr"] = df_attr
            except Exception as e:
                st.warning(f"Attribution data unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("df_cc_attr") is not None and not st.session_state["df_cc_attr"].empty:
            df_attr = st.session_state["df_cc_attr"]
            df_attr["EST_COST"] = df_attr["TOTAL_CREDITS"].apply(lambda x: credits_to_dollars(x, credit_price))
            render_priority_dataframe(
                df_attr,
                title=f"{attr_mode} cost attribution drivers",
                priority_columns=[
                    "DIMENSION",
                    "TOTAL_CREDITS",
                    "EST_COST",
                    "QUERY_COUNT",
                    "USERS",
                    "WAREHOUSES",
                    "GB_SCANNED",
                ],
                sort_by=["TOTAL_CREDITS", "EST_COST", "QUERY_COUNT"],
                ascending=[False, False, False],
                raw_label="All attribution rows",
            )
            dim_col = (
                "role_name" if attr_mode == "Role" else
                "database_schema" if attr_mode == "Database / Schema" else
                "application_client" if attr_mode == "Application / Client" else
                "lineage_dimension"
            )
            render_drillable_bar_chart(
                df_attr, dimension="DIMENSION", measure="EST_COST",
                key="cc_attr_cost", title="Attribution drill-down",
                drilldown_column=dim_col, lookback_hours=attr_days * 24,
            )
            download_csv(df_attr, "cost_attribution.csv")

    # -- CHARGEBACK - ALFA / Trexis split -------------------------------------
    elif cost_view == "Chargeback":
        st.subheader("ALFA / Trexis Chargeback")
        st.caption("Allocated credits split by company, environment, database, user, and warehouse.")
        defer_source_note(
            "Database-attributed cost is directional because shared warehouses cannot be exactly split by PROD/DEV."
        )
        cb_days = day_window_selectbox("Lookback", key="cc_cb_days", default=30)

        if st.button("Load Chargeback", key="cc_cb_load"):
            try:
                mart_sql = build_mart_chargeback_sql(
                    cb_days,
                    company=company,
                    warehouse_contains=st.session_state.get("global_warehouse", ""),
                    user_contains=st.session_state.get("global_user", ""),
                    role_contains=st.session_state.get("global_role", ""),
                    database_contains=st.session_state.get("global_database", ""),
                )
                mart_result = load_mart_table(
                    "FACT_CHARGEBACK_DAILY",
                    mart_sql,
                    source_label="FACT_CHARGEBACK_DAILY",
                )
                if mart_result.available and not mart_result.data.empty:
                    df_cb = mart_result.data
                    source_caption = mart_source_caption(mart_result)
                else:
                    # FIX: replaced hardcoded CASE with get_company_case_expr()
                    # which reads from COMPANY_CONFIG and includes all WH_ALFA_* warehouses
                    company_expr = get_company_case_expr(
                        "q.warehouse_name", "q.database_name", "q.user_name"
                    )
                    environment_expr = get_environment_case_expr("q.database_name")
                    cb_scope = get_global_filter_clause(
                        "q.start_time", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name", "q.schema_name"
                    )
                    live_chargeback_sql = f"""
                WITH {build_metered_credit_cte(days_back=cb_days)},
                query_costs AS (
                    SELECT
                        {company_expr}         AS company,
                        {environment_expr}     AS environment,
                        COALESCE(q.database_name, 'NO_DATABASE_CONTEXT') AS database_name,
                        q.user_name,
                        q.role_name,
                        q.warehouse_name,
                        {max_wh_size_expr} AS warehouse_size,
                        COUNT(*)               AS query_count,
                        SUM(COALESCE(pqc.metered_credits,0)) AS total_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                    WHERE q.start_time >= DATEADD('day', -{cb_days}, CURRENT_TIMESTAMP())
                      AND q.warehouse_name IS NOT NULL
                      {cb_scope}
                    GROUP BY 1, 2, 3, q.user_name, q.role_name, q.warehouse_name
                )
                SELECT company, environment, database_name, user_name, role_name, warehouse_name, warehouse_size, query_count,
                       ROUND(total_credits, 4) AS total_credits
                FROM query_costs
                ORDER BY total_credits DESC
                """
                    df_cb = run_query(
                        live_chargeback_sql,
                        ttl_key=f"cc_chargeback_{company}_{get_active_environment()}_{cb_days}",
                        tier="standard",
                    )
                    fallback_note = ""
                    if mart_result.message:
                        fallback_note = f" Fast summary unavailable: {mart_result.message[:160]}"
                    elif mart_result.available:
                        fallback_note = " Mart returned no chargeback rows for the selected scope."
                    source_caption = (
                        "Live fallback: ACCOUNT_USAGE query allocation. "
                        "Database-attributed cost remains Allocated / Estimated."
                        f"{fallback_note}"
                    )
                st.session_state["df_chargeback"] = df_cb
                st.session_state["df_chargeback_source"] = source_caption
            except Exception as e:
                st.warning(f"Chargeback data unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("df_chargeback") is not None and not st.session_state["df_chargeback"].empty:
            df_cb = _annotate_allocation_quality(st.session_state["df_chargeback"])
            df_cb["EST_COST"] = df_cb["TOTAL_CREDITS"].apply(lambda x: credits_to_dollars(x, credit_price))
            defer_source_note(st.session_state.get(
                "df_chargeback_source",
                "Chargeback source: not loaded",
            ))

            # Summary by company - the key chargeback output
            summary = (
                df_cb.groupby("COMPANY", as_index=False)
                .agg(
                    TOTAL_CREDITS=("TOTAL_CREDITS", "sum"),
                    EST_COST=("EST_COST", "sum"),
                    QUERY_COUNT=("QUERY_COUNT", "sum"),
                    ALLOCATION_CONFIDENCE=("ALLOCATION_CONFIDENCE", _mixed_label),
                    CHARGEBACK_READY=("CHARGEBACK_READY", _chargeback_readiness_label),
                    OWNER_PROOF=("OWNER_SOURCE", _owner_proof_label),
                )
                .sort_values("EST_COST", ascending=False)
            )
            render_shell_snapshot(tuple(
                (
                    str(srow["COMPANY"]),
                    f"${srow['EST_COST']:,.2f} ({format_credits(srow['TOTAL_CREDITS'])})",
                )
                for _, srow in summary.iterrows()
            ))

            st.subheader("Summary by Company")
            render_priority_dataframe(
                summary,
                title="Chargeback summary",
                priority_columns=[
                    "COMPANY", "ALLOCATION_CONFIDENCE", "CHARGEBACK_READY", "OWNER_PROOF",
                    "TOTAL_CREDITS", "EST_COST", "QUERY_COUNT",
                ],
                sort_by=["EST_COST", "TOTAL_CREDITS"],
                ascending=[False, False],
                raw_label="All chargeback summary rows",
            )
            if "ENVIRONMENT" in df_cb.columns:
                st.subheader("Summary by Environment Rollup")
                env_summary = (
                    df_cb.groupby(["COMPANY", "ENVIRONMENT_ROLLUP"], as_index=False)
                    .agg(
                        TOTAL_CREDITS=("TOTAL_CREDITS", "sum"),
                        EST_COST=("EST_COST", "sum"),
                        QUERY_COUNT=("QUERY_COUNT", "sum"),
                        ALLOCATION_CONFIDENCE=("ALLOCATION_CONFIDENCE", _mixed_label),
                        CHARGEBACK_READY=("CHARGEBACK_READY", _chargeback_readiness_label),
                        OWNER_PROOF=("OWNER_SOURCE", _owner_proof_label),
                    )
                    .sort_values("EST_COST", ascending=False)
                )
                render_priority_dataframe(
                    env_summary,
                    title="Chargeback environment summary",
                    priority_columns=[
                        "COMPANY", "ENVIRONMENT_ROLLUP", "ALLOCATION_CONFIDENCE", "CHARGEBACK_READY", "OWNER_PROOF",
                        "TOTAL_CREDITS", "EST_COST", "QUERY_COUNT",
                    ],
                    sort_by=["EST_COST", "TOTAL_CREDITS"],
                    ascending=[False, False],
                    raw_label="All environment chargeback rows",
                )
                dev_rows = df_cb[df_cb["ENVIRONMENT_ROLLUP"] == "DEV_ALL"]
                if not dev_rows.empty:
                    dev_summary = (
                        dev_rows.groupby(["COMPANY", "ENVIRONMENT", "DATABASE_NAME"], as_index=False)
                        .agg(
                            TOTAL_CREDITS=("TOTAL_CREDITS", "sum"),
                            EST_COST=("EST_COST", "sum"),
                            QUERY_COUNT=("QUERY_COUNT", "sum"),
                            ALLOCATION_CONFIDENCE=("ALLOCATION_CONFIDENCE", _mixed_label),
                            OWNER_PROOF=("OWNER_SOURCE", _owner_proof_label),
                        )
                        .sort_values("EST_COST", ascending=False)
                    )
                    render_priority_dataframe(
                        dev_summary,
                        title="Chargeback individual DEV databases",
                        priority_columns=[
                            "COMPANY", "ENVIRONMENT", "DATABASE_NAME", "ALLOCATION_CONFIDENCE", "OWNER_PROOF",
                            "TOTAL_CREDITS", "EST_COST", "QUERY_COUNT",
                        ],
                        sort_by=["EST_COST", "TOTAL_CREDITS"],
                        ascending=[False, False],
                        raw_label="All chargeback individual DEV database rows",
                    )

            st.subheader("Detail by User / Warehouse")
            company_filter = st.selectbox(
                "Filter by company", ["All"] + summary["COMPANY"].tolist(), key="cb_co_filter"
            )
            df_show = df_cb if company_filter == "All" else df_cb[df_cb["COMPANY"] == company_filter]
            df_show = _annotate_cost_routes(df_show, "Chargeback")
            render_priority_dataframe(
                df_show,
                title="Chargeback detail drivers",
                priority_columns=[
                    "COMPANY",
                    "ENVIRONMENT_ROLLUP",
                    "ENVIRONMENT",
                    "DATABASE_NAME",
                    "ALLOCATION_CONFIDENCE",
                    "CHARGEBACK_READY",
                    "SCOPE_REVIEW",
                    "COST_OWNER",
                    "OWNER_SOURCE",
                    "OWNER_EVIDENCE",
                    "USER_NAME",
                    "ROLE_NAME",
                    "WAREHOUSE_NAME",
                    "WAREHOUSE_SIZE",
                    "TOTAL_CREDITS",
                    "EST_COST",
                    "QUERY_COUNT",
                    "NEXT_WORKFLOW",
                    "NEXT_ACTION",
                ],
                sort_by=["EST_COST", "TOTAL_CREDITS", "QUERY_COUNT"],
                ascending=[False, False, False],
                raw_label="All chargeback detail rows",
            )
            download_csv(df_show, "chargeback_detail.csv")
            if st.button("Save chargeback outliers to Action Queue", key="cc_chargeback_queue"):
                _queue_cost_outliers(session, df_show, credit_price, "Cost & Contract - Chargeback")

    # -- CONTRACT / COMMITMENT UTILIZATION -------------------------------------
    elif cost_view == "Contract Utilization":
        st.subheader("Contract & Commitment Utilization")
        st.caption("Track consumption against the annual Snowflake committed-use contract.")
        defer_source_note(
            "Projects burn rate to flag over- and under-utilization risk. "
            "This is the canonical contract view; contract evidence is consolidated in Cost & Contract."
        )

        col_ct1, col_ct2, col_ct3 = st.columns(3)
        with col_ct1:
            committed_credits = st.number_input(
                "Annual committed credits",
                min_value=0, max_value=10_000_000, value=100_000, step=1_000,
                key="cc_committed_credits",
                help="Total credits in your Snowflake annual contract."
            )
        with col_ct2:
            from datetime import datetime as _dt
            contract_start = st.date_input(
                "Contract start date",
                value=_dt(datetime.now().year, 1, 1).date(),
                key="cc_contract_start",
            )
        with col_ct3:
            contract_months = st.number_input(
                "Contract length (months)", min_value=1, max_value=60, value=12,
                key="cc_contract_months",
            )

        if st.button("Calculate Utilization", key="cc_contract_calc"):
            try:
                ytd_source = "SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY" if company == "ALL" else "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
                ytd_filter = "" if company == "ALL" else get_wh_filter_clause("warehouse_name", company)
                df_ytd = run_query(f"""
                    SELECT TO_DATE(start_time) AS usage_date,
                           SUM(credits_used) AS credits_used
                    FROM {ytd_source}
                    WHERE start_time >= TO_DATE({sql_literal(str(contract_start))})
                      AND start_time <  DATEADD('hour', -24, CURRENT_TIMESTAMP())
                      {ytd_filter}
                    GROUP BY usage_date
                    ORDER BY usage_date
                """, ttl_key=f"cc_contract_ytd_{company}_{contract_start}", tier="historical")
                st.session_state["cc_contract_data"] = df_ytd
                st.session_state["cc_contract_params"] = {
                    "committed": committed_credits,
                    "start": str(contract_start),
                    "months": contract_months,
                }
            except Exception as e:
                st.warning(f"Utilization data unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("cc_contract_data") is not None:
            df_c  = st.session_state["cc_contract_data"]
            params = st.session_state.get("cc_contract_params", {})
            committed = params.get("committed", committed_credits)
            start_str = params.get("start", str(contract_start))
            months    = params.get("months", contract_months)

            start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
            days_in_contract = max(int(round(float(months) * 30.44)), 1)
            contract_end_date = start_date + timedelta(days=days_in_contract - 1)
            as_of_date = min(max(datetime.now().date() - timedelta(days=1), start_date), contract_end_date)

            observed_days = pd.DataFrame({
                "USAGE_DATE": pd.date_range(start_date, as_of_date, freq="D")
            })
            df_daily = df_c.copy()
            if df_daily.empty:
                df_daily = observed_days.copy()
                df_daily["CREDITS_USED"] = 0.0
            else:
                df_daily["USAGE_DATE"] = pd.to_datetime(df_daily["USAGE_DATE"]).dt.normalize()
                df_daily["CREDITS_USED"] = pd.to_numeric(df_daily["CREDITS_USED"], errors="coerce").fillna(0.0)
                df_daily = observed_days.merge(df_daily, on="USAGE_DATE", how="left")
                df_daily["CREDITS_USED"] = df_daily["CREDITS_USED"].fillna(0.0)

            ytd_used = float(df_daily["CREDITS_USED"].sum())
            days_elapsed = max(len(df_daily), 1)
            days_remaining = max((contract_end_date - as_of_date).days, 0)

            daily_rate = ytd_used / days_elapsed
            last_7_avg = float(df_daily.tail(min(7, len(df_daily)))["CREDITS_USED"].mean() or 0)
            last_30_avg = float(df_daily.tail(min(30, len(df_daily)))["CREDITS_USED"].mean() or 0)
            trend_label = burn_trend_label(last_7_avg, last_30_avg)

            future_days = pd.date_range(as_of_date + timedelta(days=1), contract_end_date, freq="D")
            future_business_days = int((future_days.dayofweek < 5).sum()) if len(future_days) else 0
            future_weekend_days = len(future_days) - future_business_days
            business_hist = df_daily[df_daily["USAGE_DATE"].dt.dayofweek < 5]
            weekend_hist = df_daily[df_daily["USAGE_DATE"].dt.dayofweek >= 5]
            business_avg = float(business_hist.tail(20)["CREDITS_USED"].mean() or last_30_avg or daily_rate)
            weekend_avg = float(weekend_hist.tail(8)["CREDITS_USED"].mean() or last_30_avg or daily_rate)

            projected_total = ytd_used + (daily_rate * days_remaining)
            projected_7 = ytd_used + (last_7_avg * days_remaining)
            projected_30 = ytd_used + (last_30_avg * days_remaining)
            projected_business = ytd_used + (business_avg * future_business_days) + (weekend_avg * future_weekend_days)
            remaining_budget = committed - ytd_used
            pct_consumed     = (ytd_used / committed * 100) if committed > 0 else 0
            pct_time_elapsed = (days_elapsed / days_in_contract * 100) if days_in_contract > 0 else 0

            runway_rate = last_7_avg if trend_label == "Accelerating" and last_7_avg > 0 else daily_rate
            if runway_rate > 0 and remaining_budget > 0:
                days_until_exhausted = remaining_budget / runway_rate
                exhaust_date = (datetime.now() + timedelta(days=days_until_exhausted)).strftime("%Y-%m-%d")
            else:
                days_until_exhausted = None
                exhaust_date = "N/A"

            # Pacing ratio: credits consumed % vs time elapsed %
            pacing_ratio = (pct_consumed / pct_time_elapsed) if pct_time_elapsed > 0 else 1.0
            projected_pct_over = ((projected_total / committed) * 100 - 100) if committed > 0 else 0.0

            render_shell_snapshot((
                ("YTD Consumed", format_credits(ytd_used)),
                ("Remaining Budget", format_credits(remaining_budget)),
                ("% Consumed", f"{pct_consumed:.1f}% ({pct_consumed - pct_time_elapsed:+.1f}% vs time)"),
                ("Daily Burn Rate", f"{daily_rate:,.1f} cr/day"),
                ("Projected Year-End", format_credits(projected_total)),
            ))
            defer_source_note(
                f"{metric_confidence_label('exact')} for consumed credits | "
                f"{metric_confidence_label('projection')} | "
                f"{freshness_note('WAREHOUSE_METERING_HISTORY')}"
            )

            render_shell_snapshot((
                ("7-Day Projection", f"{format_credits(projected_7)} ({trend_label})"),
                ("30-Day Projection", f"{format_credits(projected_30)} ({burn_trend_label(last_30_avg, daily_rate)})"),
                ("Business-Day Adjusted", f"{format_credits(projected_business)} ({business_avg:,.1f} cr/business day)"),
            ))

            # -- Progress bar ---------------------------------------------------
            bar_pct = min(pct_consumed / 100, 1.0)
            st.progress(bar_pct, text=f"{pct_consumed:.1f}% of {committed:,} committed credits")

            # -- Pacing diagnosis -----------------------------------------------
            st.divider()
            if pacing_ratio > 1.15:
                exhaustion_line = (
                    f"At {runway_rate:,.1f} cr/day you will exhaust the commitment on "
                    f"**{exhaust_date}** ({days_until_exhausted:.0f} days from now), "
                    f"**{days_remaining - days_until_exhausted:.0f} days early**. "
                    if days_until_exhausted is not None
                    else "Current burn cannot calculate a reliable exhaustion date. "
                )
                st.error(
                    f"**Burning too fast** - consuming credits {pacing_ratio:.1f}x faster than the "
                    f"contract pace. {exhaustion_line}"
                    f"Projected year-end: **{projected_total:,.0f}** vs committed **{committed:,}** "
                    f"({projected_pct_over:.0f}% over)."
                )
            elif pacing_ratio < 0.75:
                under_pct = 100 - (projected_total / committed * 100) if committed > 0 else 0.0
                st.warning(
                    f"**Under-utilizing** - tracking at {pacing_ratio:.2f}x the contract pace. "
                    f"Projected year-end: **{projected_total:,.0f}** of {committed:,} credits "
                    f"({under_pct:.0f}% under-utilized). "
                    f"Review with Snowflake account team - unused committed credits typically do not roll over."
                )
            else:
                st.success(
                    f"**On pace** - pacing ratio {pacing_ratio:.2f}x. "
                    f"Projected year-end: **{projected_total:,.0f}** of {committed:,} credits "
                    f"({pct_consumed:.0f}% consumed, {pct_time_elapsed:.0f}% of contract elapsed)."
                )

            # -- Monthly breakdown chart ----------------------------------------
            st.divider()
            st.subheader("Monthly Consumption")
            if st.button("Load Monthly Breakdown", key="cc_monthly_breakdown"):
                try:
                    monthly_source = "SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY" if company == "ALL" else "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
                    monthly_filter = "" if company == "ALL" else get_wh_filter_clause("warehouse_name", company)
                    df_monthly = run_query(f"""
                        SELECT DATE_TRUNC('month', start_time) AS month,
                               SUM(credits_used) AS monthly_credits,
                               SUM(credits_used) * {credit_price} AS monthly_cost
                        FROM {monthly_source}
                        WHERE start_time >= TO_DATE({sql_literal(start_str)})
                          AND start_time <  DATEADD('hour', -24, CURRENT_TIMESTAMP())
                          {monthly_filter}
                        GROUP BY month
                        ORDER BY month
                    """, ttl_key=f"cc_monthly_{company}_{start_str}_{credit_price}", tier="historical")
                    st.session_state["cc_monthly_data"] = df_monthly
                except Exception as e:
                    st.warning(f"Monthly breakdown unavailable in this role/context: {format_snowflake_error(e)}")

            if st.session_state.get("cc_monthly_data") is not None and not st.session_state["cc_monthly_data"].empty:
                df_m = st.session_state["cc_monthly_data"]
                df_m["BUDGET_LINE"] = committed / (months or 12)
                df_m["CUMULATIVE"]  = df_m["MONTHLY_CREDITS"].cumsum()

                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    st.caption("Monthly credits vs equal-share budget line")
                    st.bar_chart(df_m.set_index("MONTH")[["MONTHLY_CREDITS","BUDGET_LINE"]])
                with col_m2:
                    st.caption("Cumulative consumption")
                    st.line_chart(df_m.set_index("MONTH")["CUMULATIVE"])

                download_csv(df_m, "contract_utilization.csv")

            # -- By service type ------------------------------------------------
            st.divider()
            st.subheader("Consumption by Service Type")
            if company != "ALL":
                st.info("Service-type metering is account-level in Snowflake. Switch Company View to ALL for a full service breakdown.")
            else:
                if st.button("Load Service Breakdown", key="cc_service_type"):
                    try:
                        df_svc = run_query(f"""
                            SELECT service_type,
                                   SUM(credits_used) AS total_credits,
                                   ROUND(SUM(credits_used) / NULLIF({ytd_used}, 0) * 100, 1) AS pct_of_total
                            FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
                            WHERE start_time >= TO_DATE({sql_literal(start_str)})
                              AND start_time <  DATEADD('hour', -24, CURRENT_TIMESTAMP())
                            GROUP BY service_type
                            ORDER BY total_credits DESC
                        """, ttl_key=f"cc_service_{company}_{start_str}_{ytd_used}", tier="historical")
                        st.session_state["cc_svc_data"] = df_svc
                    except Exception as e:
                        st.warning(f"Service breakdown unavailable in this role/context: {format_snowflake_error(e)}")

                if st.session_state.get("cc_svc_data") is not None and not st.session_state["cc_svc_data"].empty:
                    df_sv = st.session_state["cc_svc_data"]
                    render_chart_with_data_toggle(
                        "Service-type contract consumption",
                        "cc_contract_service_type",
                        lambda: render_ranked_bar_chart(
                            df_sv,
                            "SERVICE_TYPE",
                            "TOTAL_CREDITS",
                            top_n=12,
                        ),
                        df_sv,
                        priority_columns=["SERVICE_TYPE", "TOTAL_CREDITS", "PCT_OF_TOTAL"],
                        sort_by=["TOTAL_CREDITS", "PCT_OF_TOTAL"],
                        ascending=[False, False],
                        raw_label="All service-type rows",
                    )
                    download_csv(df_sv, "contract_by_service_type.csv")
