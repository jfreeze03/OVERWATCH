"""Targeted Cost & Contract evidence loading."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.decision_workspace_target_filters import (
    build_target_predicate_plan,
    build_target_sql_filter,
    evidence_row_limit,
    evidence_target_label,
)
from utils.mart_names import mart_object_name
from utils.primitives import safe_float, safe_int
from utils.sql_safe import sql_literal
from utils.performance import TARGETED_EVIDENCE_DEFAULT_LIMIT, TARGETED_EVIDENCE_MAX_LIMIT


pd = lazy_pandas()

run_query_or_raise = _lazy_util("run_query_or_raise")
format_snowflake_error = _lazy_util("format_snowflake_error")


COST_EVIDENCE_COLUMNS: tuple[str, ...] = (
    "COMPANY",
    "ENVIRONMENT",
    "ENVIRONMENT_ROLLUP",
    "DATABASE_NAME",
    "USER_NAME",
    "ROLE_NAME",
    "WAREHOUSE_NAME",
    "WAREHOUSE_SIZE",
    "DEPARTMENT",
    "COST_ATTRIBUTION",
    "ALLOCATION_SOURCE",
    "ALLOCATION_BASIS",
    "ALLOCATION_CONFIDENCE",
    "ALLOCATION_BASIS",
    "CHARGEBACK_READY",
    "SCOPE_REVIEW",
    "SERVICE_CATEGORY",
    "SERVICE_TYPE",
    "TAG_VALUE",
    "APPLICATION",
    "DRIVER",
    "DIMENSION",
    "ENTITY_NAME",
    "ENTITY_ID",
    "QUERY_COUNT",
    "TOTAL_CREDITS",
    "EST_COST",
    "FIRST_USAGE_DATE",
    "LAST_USAGE_DATE",
    "ACTIVE_DAYS",
    "MART_LOAD_TS",
    "ENVIRONMENT_SCOPE_MODE",
)


def _environment_filter(environment: str, *, alias: str = "target") -> str:
    env = str(environment or "").strip()
    if not env or env.upper() in {"ALL", "ALL ENVIRONMENTS", "GLOBAL"}:
        return ""
    prefix = f"{str(alias or 'target').strip()}."
    return (
        f"AND (UPPER({prefix}ENVIRONMENT) = UPPER("
        f"{sql_literal(env, 100)}"
        f") OR UPPER({prefix}ENVIRONMENT_ROLLUP) = UPPER("
        f"{sql_literal(env, 100)}"
        "))"
    )


def _projection() -> str:
    return ",\n            ".join(COST_EVIDENCE_COLUMNS)


def _target_hash(target: dict[str, str] | None) -> str:
    payload = json.dumps(target or {}, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _target_value(target: dict[str, str] | None) -> str:
    target = target or {}
    return str(target.get("entity_id") or target.get("entity_name") or target.get("evidence_id") or "").strip()


def _chargeback_builder_kwargs(target: dict[str, str] | None) -> dict[str, str]:
    target = target or {}
    entity_type = str(target.get("entity_type") or "").strip().lower()
    value = _target_value(target)
    kwargs = {
        "warehouse_contains": "",
        "user_contains": "",
        "role_contains": "",
        "database_contains": "",
        "department_contains": "",
    }
    if not value:
        return kwargs
    if entity_type in {"warehouse", "warehouse_name"}:
        kwargs["warehouse_contains"] = value
    elif entity_type == "user":
        kwargs["user_contains"] = value
    elif entity_type == "role":
        kwargs["role_contains"] = value
    elif entity_type == "database":
        kwargs["database_contains"] = value
    elif entity_type == "department":
        kwargs["department_contains"] = value
    return kwargs


def _prefers_service_cost(target: dict[str, str] | None) -> bool:
    entity_type = str((target or {}).get("entity_type") or "").strip().lower()
    return entity_type in {
        "service",
        "service_category",
        "service_type",
        "cortex",
        "cortex_service",
        "application",
        "tag",
        "driver",
        "dimension",
    }


def _unsupported_target_reason(target: dict[str, str] | None) -> str:
    target = target or {}
    entity_type = str(target.get("entity_type") or "").strip().lower()
    if entity_type in {"tag", "application"}:
        return "This target is not supported by the installed Cost evidence marts."
    return ""


def _chargeback_evidence_sql(company: str, environment: str, days: int, target: dict[str, str] | None, limit: int) -> str:
    table = mart_object_name("MART_COST_EVIDENCE_RECENT")
    company_filter = "" if str(company or "").upper() == "ALL" else f"AND COMPANY = {sql_literal(company, 100)}"
    target_filter = build_target_sql_filter(
        "Cost & Contract",
        target or {},
        alias="target",
        available_columns=COST_EVIDENCE_COLUMNS,
    )
    env_filter = _environment_filter(environment)
    return f"""
        SELECT
            {_projection()}
        FROM (
            SELECT
                target.COMPANY,
                target.ENVIRONMENT,
                target.ENVIRONMENT AS ENVIRONMENT_ROLLUP,
                target.DATABASE_NAME,
                target.USER_NAME,
                target.ROLE_NAME,
                target.WAREHOUSE_NAME,
                NULL::VARCHAR AS WAREHOUSE_SIZE,
                target.DEPARTMENT,
                NULL::VARCHAR AS COST_ATTRIBUTION,
                'compact_cost_evidence' AS ALLOCATION_SOURCE,
                COALESCE(target.SUMMARY, 'Compact cost evidence') AS ALLOCATION_BASIS,
                'estimated' AS ALLOCATION_CONFIDENCE,
                'recent evidence mart' AS ALLOCATION_BASIS,
                TRUE AS CHARGEBACK_READY,
                COALESCE(target.EVIDENCE_KIND, 'cost evidence') AS SCOPE_REVIEW,
                target.SERVICE_CATEGORY,
                target.SERVICE_TYPE,
                NULL::VARCHAR AS TAG_VALUE,
                target.APPLICATION,
                COALESCE(target.ENTITY_NAME, target.WAREHOUSE_NAME, target.USER_NAME, target.ROLE_NAME, target.DATABASE_NAME, target.DEPARTMENT) AS DRIVER,
                COALESCE(target.EVIDENCE_KIND, 'chargeback') AS DIMENSION,
                COALESCE(target.ENTITY_NAME, target.WAREHOUSE_NAME, target.USER_NAME, target.ROLE_NAME, target.DATABASE_NAME, target.DEPARTMENT) AS ENTITY_NAME,
                COALESCE(target.ENTITY_ID, target.WAREHOUSE_NAME, target.USER_NAME, target.ROLE_NAME, target.DATABASE_NAME, target.DEPARTMENT) AS ENTITY_ID,
                target.QUERY_COUNT,
                target.TOTAL_CREDITS,
                target.EST_COST,
                TO_DATE(target.SNAPSHOT_TS) AS FIRST_USAGE_DATE,
                TO_DATE(target.SNAPSHOT_TS) AS LAST_USAGE_DATE,
                NULL::NUMBER AS ACTIVE_DAYS,
                target.LOAD_TS AS MART_LOAD_TS,
                'exact' AS ENVIRONMENT_SCOPE_MODE,
            FROM {table} target
            WHERE target.SNAPSHOT_TS >= DATEADD('DAY', -{int(days)}, CURRENT_TIMESTAMP())
              {company_filter}
        ) target
        WHERE 1 = 1
          {env_filter}
          {target_filter}
        ORDER BY EST_COST DESC, TOTAL_CREDITS DESC, QUERY_COUNT DESC
        LIMIT {int(limit)}
    """


def _service_evidence_sql(company: str, environment: str, days: int, target: dict[str, str] | None, limit: int) -> str:
    _ = environment
    table = mart_object_name("MART_COST_EVIDENCE_RECENT")
    company_filter = "" if str(company or "").upper() == "ALL" else f"AND COMPANY = {sql_literal(company, 100)}"
    target_filter = build_target_sql_filter(
        "Cost & Contract",
        target or {},
        alias="target",
        available_columns=COST_EVIDENCE_COLUMNS,
    )
    return f"""
        SELECT
            {_projection()}
        FROM (
            SELECT
                COMPANY,
                'ALL' AS ENVIRONMENT,
                'ALL' AS ENVIRONMENT_ROLLUP,
                'all_fallback' AS ENVIRONMENT_SCOPE_MODE,
                NULL::VARCHAR AS DATABASE_NAME,
                NULL::VARCHAR AS USER_NAME,
                NULL::VARCHAR AS ROLE_NAME,
                NULL::VARCHAR AS WAREHOUSE_NAME,
                NULL::VARCHAR AS WAREHOUSE_SIZE,
                NULL::VARCHAR AS DEPARTMENT,
                NULL::VARCHAR AS COST_ATTRIBUTION,
                'compact_cost_evidence' AS ALLOCATION_SOURCE,
                'service cost evidence' AS ALLOCATION_BASIS,
                'estimated' AS ALLOCATION_CONFIDENCE,
                'service daily rollup' AS ALLOCATION_BASIS,
                FALSE AS CHARGEBACK_READY,
                'service evidence' AS SCOPE_REVIEW,
                SERVICE_CATEGORY,
                SERVICE_TYPE,
                NULL::VARCHAR AS TAG_VALUE,
                NULL::VARCHAR AS APPLICATION,
                COALESCE(SERVICE_TYPE, SERVICE_CATEGORY, 'Snowflake service') AS DRIVER,
                'service' AS DIMENSION,
                COALESCE(SERVICE_TYPE, SERVICE_CATEGORY, 'Snowflake service') AS ENTITY_NAME,
                COALESCE(SERVICE_TYPE, SERVICE_CATEGORY, 'Snowflake service') AS ENTITY_ID,
                SUM(COALESCE(QUERY_COUNT, 0)) AS QUERY_COUNT,
                ROUND(SUM(COALESCE(TOTAL_CREDITS, 0)), 4) AS TOTAL_CREDITS,
                ROUND(SUM(COALESCE(EST_COST, 0)), 2) AS EST_COST,
                MIN(TO_DATE(SNAPSHOT_TS)) AS FIRST_USAGE_DATE,
                MAX(TO_DATE(SNAPSHOT_TS)) AS LAST_USAGE_DATE,
                COUNT(DISTINCT TO_DATE(SNAPSHOT_TS)) AS ACTIVE_DAYS,
                MAX(LOAD_TS) AS MART_LOAD_TS
            FROM {table}
            WHERE SNAPSHOT_TS >= DATEADD('DAY', -{int(days)}, CURRENT_TIMESTAMP())
              {company_filter}
            GROUP BY COMPANY, SERVICE_CATEGORY, SERVICE_TYPE
        ) target
        WHERE 1 = 1
          {target_filter}
        ORDER BY EST_COST DESC, TOTAL_CREDITS DESC, QUERY_COUNT DESC
        LIMIT {int(limit)}
    """


def _cost_evidence_sql(company: str, environment: str, days: int, target: dict[str, str] | None, limit: int) -> str:
    if _prefers_service_cost(target):
        return _service_evidence_sql(company, environment, days, target, limit)
    return _chargeback_evidence_sql(company, environment, days, target, limit)


def _summary(rows: object, target_label: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    if rows is None or not hasattr(rows, "empty") or getattr(rows, "empty", True):
        message = (
            f"No rows for selected finding target ({target_label})."
            if target_label else "No cost evidence rows matched the selected scope."
        )
        return message, (("Rows", "0"),)

    spend = safe_float(pd.to_numeric(rows.get("EST_COST", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    credits = safe_float(pd.to_numeric(rows.get("TOTAL_CREDITS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    query_count = safe_int(pd.to_numeric(rows.get("QUERY_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    top_driver = ""
    for column in ("WAREHOUSE_NAME", "SERVICE_CATEGORY", "SERVICE_TYPE", "ENTITY_NAME", "DRIVER", "USER_NAME", "ROLE_NAME", "DATABASE_NAME", "DEPARTMENT"):
        if column in rows.columns and not rows.empty:
            top_driver = str(rows.iloc[0].get(column) or "").strip()
            if top_driver:
                break
    return (
        f"{len(rows):,} cost evidence row(s); ${spend:,.0f} estimated spend; {credits:,.1f} credits.",
        (
            ("Rows", f"{len(rows):,}"),
            ("Spend", f"${spend:,.0f}"),
            ("Credits", f"{credits:,.1f}"),
            ("Queries", f"{query_count:,}"),
            ("Top driver", top_driver or "Unavailable"),
        ),
    )


def load_cost_evidence(
    company: str,
    environment: str,
    days: int,
    target: dict[str, str] | None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Load one bounded, target-aware Cost Evidence result."""
    requested_limit = TARGETED_EVIDENCE_DEFAULT_LIMIT if limit is None else min(int(limit), TARGETED_EVIDENCE_MAX_LIMIT)
    row_limit = evidence_row_limit(requested_limit)
    target = target or {}
    target_label = evidence_target_label(target)
    ttl_prefix = "cost_targeted_evidence" if _target_value(target) else "cost_bounded_evidence"
    unsupported_reason = _unsupported_target_reason(target)
    if unsupported_reason:
        return {
            "rows": pd.DataFrame(),
            "summary": unsupported_reason,
            "metrics": (("Rows", "0"), ("Target", target_label or "Unsupported")),
            "source": "Cost evidence mart",
            "target_label": target_label,
            "row_count": 0,
            "limit": row_limit,
            "error": "",
            "unsupported_target": True,
            "environment_scope_note": "",
        }
    sql = _cost_evidence_sql(company, environment, int(days), target, row_limit)
    target_plan = build_target_predicate_plan("Cost & Contract", target, COST_EVIDENCE_COLUMNS).with_fingerprint()
    try:
        rows = run_query_or_raise(
            sql,
            ttl_key=f"{ttl_prefix}_{company}_{environment}_{int(days)}_{_target_hash(target)}_{row_limit}",
            tier="historical",
            section="Cost & Contract",
            max_rows=row_limit,
            use_cache=False,
            query_boundary="evidence_targeted",
            target_label=target_label,
            target_context_present=bool(target),
            target_columns_used=target_plan.columns_used,
            target_fallback_used=target_plan.fallback_used,
            target_predicate_marker_present=bool(target_plan.sql_filter),
            target_predicate_plan_id=target_plan.plan_id,
        )
        error = ""
    except Exception as exc:
        rows = pd.DataFrame()
        error = format_snowflake_error(exc)
    summary, metrics = _summary(rows, target_label)
    return {
        "rows": rows,
        "summary": summary if not error else "Cost evidence is unavailable for the selected scope.",
        "metrics": metrics,
        "source": "Cost evidence mart",
        "target_label": target_label,
        "row_count": len(rows) if hasattr(rows, "__len__") else 0,
        "limit": row_limit,
        "error": error,
        "unsupported_target": False,
        "environment_scope_note": "All-environment fallback source." if _prefers_service_cost(target) else "Exact environment source.",
    }


__all__ = ["COST_EVIDENCE_COLUMNS", "load_cost_evidence"]
