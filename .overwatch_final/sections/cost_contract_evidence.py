"""Targeted Cost & Contract evidence loading."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.decision_workspace_target_filters import (
    build_target_sql_filter,
    evidence_row_limit,
    evidence_target_label,
)
from utils.mart_cost import build_mart_cost_explorer_sql
from utils.primitives import safe_float, safe_int
from utils.sql_safe import sql_literal
from performance import TARGETED_EVIDENCE_DEFAULT_LIMIT, TARGETED_EVIDENCE_MAX_LIMIT


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
    "COST_OWNER",
    "OWNER_SOURCE",
    "OWNER_EVIDENCE",
    "ALLOCATION_CONFIDENCE",
    "ALLOCATION_BASIS",
    "CHARGEBACK_READY",
    "SCOPE_REVIEW",
    "QUERY_COUNT",
    "TOTAL_CREDITS",
    "EST_COST",
    "FIRST_USAGE_DATE",
    "LAST_USAGE_DATE",
    "ACTIVE_DAYS",
    "MART_LOAD_TS",
)


def _environment_filter(environment: str) -> str:
    env = str(environment or "").strip()
    if not env or env.upper() in {"ALL", "ALL ENVIRONMENTS", "GLOBAL"}:
        return ""
    return (
        "AND (UPPER(target.ENVIRONMENT) = UPPER("
        f"{sql_literal(env, 100)}"
        ") OR UPPER(target.ENVIRONMENT_ROLLUP) = UPPER("
        f"{sql_literal(env, 100)}"
        "))"
    )


def _target_hash(target: dict[str, str] | None) -> str:
    payload = json.dumps(target or {}, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _cost_evidence_sql(company: str, environment: str, days: int, target: dict[str, str] | None, limit: int) -> str:
    base_sql = build_mart_cost_explorer_sql(days_back=int(days), company=company)
    target_filter = build_target_sql_filter(
        "Cost & Contract",
        target or {},
        alias="target",
        available_columns=COST_EVIDENCE_COLUMNS,
    )
    env_filter = _environment_filter(environment)
    return f"""
        SELECT *
        FROM (
            {base_sql}
        ) target
        WHERE 1 = 1
          {env_filter}
          {target_filter}
        ORDER BY EST_COST DESC, TOTAL_CREDITS DESC, QUERY_COUNT DESC
        LIMIT {int(limit)}
    """


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
    for column in ("WAREHOUSE_NAME", "SERVICE_CATEGORY", "USER_NAME", "ROLE_NAME", "DATABASE_NAME", "DEPARTMENT"):
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
    sql = _cost_evidence_sql(company, environment, int(days), target, row_limit)
    try:
        rows = run_query_or_raise(
            sql,
            ttl_key=f"cost_evidence_{company}_{environment}_{int(days)}_{_target_hash(target)}_{row_limit}",
            tier="historical",
            section="Cost & Contract",
            max_rows=row_limit,
            use_cache=False,
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
    }


__all__ = ["COST_EVIDENCE_COLUMNS", "load_cost_evidence"]
