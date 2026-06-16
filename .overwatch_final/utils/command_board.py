"""Shared first-paint command board readers.

These helpers keep the top-level sections data-first without making each shell
hand-roll its own Snowflake query. They prefer compact executive summary facts
and fail closed to data-safe frames when the summary is not ready yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd
import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, DEFAULT_DAY_WINDOW
from .deployment import build_schema_migration_contract, build_schema_migration_status_sql
from .mart import mart_object_name
from .query import run_query, sql_literal
from .scorecards import platform_operating_score_from_signals


COMMAND_BOARD_VERSION = "2026-06-14-command-board-v1"

BOARD_COLUMNS = (
    "PANEL",
    "METRIC",
    "DIMENSION",
    "PERIOD_START",
    "VALUE",
    "VALUE_USD",
    "UNIT",
    "SORT_ORDER",
    "SOURCE",
)


@dataclass(frozen=True)
class CommandBoard:
    data: pd.DataFrame
    summary: dict[str, object]
    meta: dict[str, object]


def command_board_scope(
    company: str = DEFAULT_COMPANY,
    environment: str = DEFAULT_ENVIRONMENT,
    days: int = DEFAULT_DAY_WINDOW,
) -> tuple[str, str, int]:
    """Return the cache scope for a first-paint command board."""
    return (
        str(company or DEFAULT_COMPANY).upper(),
        str(environment or DEFAULT_ENVIRONMENT).upper(),
        max(1, int(days or DEFAULT_DAY_WINDOW)),
    )


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        number = float(value if value is not None else default)
        return default if number != number else number
    except (TypeError, ValueError):
        return default


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(round(float(value if value is not None else default)))
    except (TypeError, ValueError):
        return default


def _normalize_board(frame: pd.DataFrame | None) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame(columns=BOARD_COLUMNS)
    rows = frame.copy()
    for column in BOARD_COLUMNS:
        if column not in rows.columns:
            rows[column] = None
    rows["SORT_ORDER"] = pd.to_numeric(rows["SORT_ORDER"], errors="coerce").fillna(9999)
    rows["VALUE"] = pd.to_numeric(rows["VALUE"], errors="coerce")
    rows["VALUE_USD"] = pd.to_numeric(rows["VALUE_USD"], errors="coerce")
    return rows[list(BOARD_COLUMNS)].sort_values(
        ["PANEL", "SORT_ORDER", "PERIOD_START", "DIMENSION"],
        na_position="last",
    ).reset_index(drop=True)


def empty_command_board(
    company: str = DEFAULT_COMPANY,
    environment: str = DEFAULT_ENVIRONMENT,
    days: int = DEFAULT_DAY_WINDOW,
    *,
    state: str = "Cached fallback",
) -> CommandBoard:
    """Return an immediate no-Snowflake command board frame for first paint."""
    scope = command_board_scope(company, environment, days)
    data = pd.DataFrame(columns=BOARD_COLUMNS)
    summary = summarize_command_board(data)
    summary["state"] = state
    summary["cap_reason"] = (
        "Use Refresh to hydrate MART_EXECUTIVE_OBSERVABILITY. The section frame is rendered before "
        "Snowflake facts so navigation stays fast when marts are cold or privileges are missing."
    )
    return CommandBoard(
        data=data,
        summary=summary,
        meta={
            "source": "MART_EXECUTIVE_OBSERVABILITY",
            "available": False,
            "first_paint": True,
            "state": state,
            "company": scope[0],
            "environment": scope[1],
            "days": scope[2],
        },
    )


def _rows(board: pd.DataFrame, panel: str, metric: str | None = None) -> pd.DataFrame:
    if not isinstance(board, pd.DataFrame) or board.empty:
        return pd.DataFrame(columns=BOARD_COLUMNS)
    rows = board[board["PANEL"].astype(str).str.upper().eq(str(panel).upper())].copy()
    if metric:
        rows = rows[rows["METRIC"].astype(str).str.upper().eq(str(metric).upper())].copy()
    return rows


def board_rows(board: pd.DataFrame, panel: str, metric: str | None = None) -> pd.DataFrame:
    """Return normalized rows for one executive observability panel."""
    return _rows(_normalize_board(board), panel, metric)


def _metric_row(board: pd.DataFrame, metric: str) -> pd.Series | None:
    rows = _rows(board, "KPI", metric)
    if rows.empty:
        return None
    try:
        return rows.iloc[0]
    except Exception:
        return None


def _metric_value(board: pd.DataFrame, metric: str, column: str = "VALUE") -> float:
    row = _metric_row(board, metric)
    if row is None:
        return 0.0
    try:
        return _safe_float(row.get(column))
    except Exception:
        return 0.0


def _top_dimension(board: pd.DataFrame, panel: str, metric: str | None = None) -> tuple[str, float, float]:
    rows = _rows(board, panel, metric)
    if rows.empty:
        return "On demand", 0.0, 0.0
    try:
        ranked = rows.sort_values(["VALUE_USD", "VALUE"], ascending=[False, False], na_position="last")
        row = ranked.iloc[0]
        return (
            str(row.get("DIMENSION") or "On demand"),
            _safe_float(row.get("VALUE")),
            _safe_float(row.get("VALUE_USD")),
        )
    except Exception:
        return "On demand", 0.0, 0.0


def build_executive_command_board_sql(
    company: str = DEFAULT_COMPANY,
    environment: str = DEFAULT_ENVIRONMENT,
    days: int = DEFAULT_DAY_WINDOW,
) -> str:
    """Build the compact mart query used by first-paint command boards."""
    table = mart_object_name("MART_EXECUTIVE_OBSERVABILITY")
    company_value = "ALL" if str(company or "").upper() == "ALL" else str(company or DEFAULT_COMPANY)
    environment_value = "ALL" if str(environment or "").upper() == "ALL" else str(environment or DEFAULT_ENVIRONMENT)
    company_lit = sql_literal(company_value.upper(), 100)
    environment_lit = sql_literal(environment_value.upper(), 100)
    days = max(1, int(days or DEFAULT_DAY_WINDOW))
    return f"""
WITH candidates AS (
    SELECT
        PANEL,
        METRIC,
        DIMENSION,
        PERIOD_START,
        VALUE,
        VALUE_USD,
        UNIT,
        SORT_ORDER,
        SOURCE,
        COMPANY,
        ENVIRONMENT,
        SNAPSHOT_TS
    FROM {table}
    WHERE WINDOW_DAYS = {days}
      AND UPPER(COMPANY) IN ({company_lit}, 'ALL')
      AND (
          UPPER(COALESCE(ENVIRONMENT, 'ALL')) = 'ALL'
          OR UPPER(COALESCE(ENVIRONMENT, 'ALL')) = {environment_lit}
      )
      AND SNAPSHOT_TS >= DATEADD('DAY', -14, CURRENT_TIMESTAMP())
),
ranked AS (
    SELECT
        PANEL,
        METRIC,
        DIMENSION,
        PERIOD_START,
        VALUE,
        VALUE_USD,
        UNIT,
        SORT_ORDER,
        SOURCE,
        ROW_NUMBER() OVER (
            PARTITION BY PANEL, METRIC, DIMENSION, PERIOD_START, SORT_ORDER
            ORDER BY
                IFF(UPPER(COMPANY) = {company_lit}, 0, 1),
                IFF(UPPER(COALESCE(ENVIRONMENT, 'ALL')) = {environment_lit}, 0, 1),
                SNAPSHOT_TS DESC
        ) AS RN
    FROM candidates
)
SELECT PANEL, METRIC, DIMENSION, PERIOD_START, VALUE, VALUE_USD, UNIT, SORT_ORDER, SOURCE
FROM ranked
WHERE RN = 1
ORDER BY PANEL, SORT_ORDER, PERIOD_START, VALUE_USD DESC, VALUE DESC
"""


def summarize_command_board(board: pd.DataFrame) -> dict[str, object]:
    """Return app-facing summary metrics from MART_EXECUTIVE_OBSERVABILITY rows."""
    rows = _normalize_board(board)
    current_credits = _metric_value(rows, "Credits Used")
    current_cost = _metric_value(rows, "Credits Used", "VALUE_USD")
    spend_delta_credits = _metric_value(rows, "Spend Delta")
    spend_delta_cost = _metric_value(rows, "Spend Delta", "VALUE_USD")
    cost_driver, driver_credits, driver_cost = _top_dimension(rows, "COST_DRIVER")
    pressure_rows = _rows(rows, "WAREHOUSE_PRESSURE", "Queue Seconds")
    spill_rows = _rows(rows, "WAREHOUSE_PRESSURE", "Remote Spill GB")
    top_queue = _top_dimension(rows, "WAREHOUSE_PRESSURE", "Queue Seconds")
    top_spill = _top_dimension(rows, "WAREHOUSE_PRESSURE", "Remote Spill GB")
    freshness = _rows(rows, "FRESHNESS")
    stale_sources = 0
    if not freshness.empty and "PERIOD_START" in freshness.columns:
        stale_sources = int(freshness["PERIOD_START"].isna().sum())
    summary = {
        "loaded": not rows.empty,
        "current_credits": current_credits,
        "current_cost_usd": current_cost,
        "prior_credits": max(0.0, current_credits - spend_delta_credits),
        "prior_cost_usd": max(0.0, current_cost - spend_delta_cost),
        "spend_delta_credits": spend_delta_credits,
        "spend_delta_cost_usd": spend_delta_cost,
        "cortex_credits": _metric_value(rows, "Cortex Spend"),
        "cortex_cost_usd": _metric_value(rows, "Cortex Spend", "VALUE_USD"),
        "total_queries": _safe_int(_metric_value(rows, "Total Queries")),
        "avg_runtime_sec": _metric_value(rows, "Avg Runtime"),
        "p95_runtime_sec": _metric_value(rows, "P95 Runtime"),
        "queue_seconds": _metric_value(rows, "Queue Time"),
        "remote_spill_gb": _metric_value(rows, "Remote Spill"),
        "failed_queries": _safe_int(_metric_value(rows, "Failed Queries")),
        "failed_tasks": _safe_int(_metric_value(rows, "Failed Tasks")),
        "critical_high_alerts": _safe_int(_metric_value(rows, "Critical High Alerts")),
        "open_actions": _safe_int(_metric_value(rows, "Open Actions")),
        "high_actions": _safe_int(_metric_value(rows, "Critical High Alerts")),
        "storage_tb": _metric_value(rows, "Storage"),
        "storage_cost_usd": _metric_value(rows, "Storage", "VALUE_USD"),
        "top_cost_driver": cost_driver,
        "top_cost_driver_credits": driver_credits,
        "top_cost_driver_usd": driver_cost,
        "top_queue_warehouse": top_queue[0],
        "top_queue_seconds": top_queue[1],
        "top_spill_warehouse": top_spill[0],
        "top_spill_gb": top_spill[1],
        "pressure_lanes": int(len(pressure_rows) + len(spill_rows)),
        "freshness_sources": int(len(freshness)),
        "stale_sources": stale_sources,
    }
    score = platform_operating_score_from_signals(summary)
    summary.update({
        "score": score["score"],
        "raw_score": score["raw_score"],
        "state": score["state"] if not rows.empty else "On demand",
        "score_cap": score["score_cap"],
        "cap_reason": score["cap_reason"] if not rows.empty else (
            "Executive observability summary is available after refresh for this scope."
        ),
        "platform_score_drivers": score["platform_score_drivers"],
    })
    return summary


def load_executive_command_board(
    company: str = DEFAULT_COMPANY,
    environment: str = DEFAULT_ENVIRONMENT,
    days: int = DEFAULT_DAY_WINDOW,
) -> CommandBoard:
    """Load the first-paint executive command mart."""
    sql = build_executive_command_board_sql(company, environment, days)
    frame = run_query(
        sql,
        ttl_key=f"command_board_{company}_{environment}_{int(days)}",
        tier="standard",
        section="Command Board",
        max_rows=500,
    )
    board = _normalize_board(frame)
    loaded_at = datetime.now().isoformat(timespec="seconds")
    return CommandBoard(
        data=board,
        summary=summarize_command_board(board),
        meta={
            "source": "MART_EXECUTIVE_OBSERVABILITY",
            "loaded_at": loaded_at,
            "company": company,
            "environment": environment,
            "days": int(days),
            "available": not board.empty,
        },
    )


def _scope_matches(meta: dict[str, object], scope: tuple[str, str, int]) -> bool:
    return (
        str(meta.get("company") or "").upper() == scope[0]
        and str(meta.get("environment") or "").upper() == scope[1]
        and int(meta.get("days") or 0) == scope[2]
    )


def read_command_board_state(
    data_key: str,
    summary_key: str,
    meta_key: str,
    company: str = DEFAULT_COMPANY,
    environment: str = DEFAULT_ENVIRONMENT,
    days: int = DEFAULT_DAY_WINDOW,
) -> CommandBoard:
    """Read a command board from session state or return an immediate fallback."""
    scope = command_board_scope(company, environment, days)
    meta = st.session_state.get(meta_key)
    summary = st.session_state.get(summary_key)
    data = st.session_state.get(data_key)
    if isinstance(meta, dict) and isinstance(summary, dict) and _scope_matches(meta, scope):
        board = _normalize_board(data if isinstance(data, pd.DataFrame) else pd.DataFrame())
        return CommandBoard(data=board, summary=dict(summary), meta=dict(meta))
    return empty_command_board(company, environment, days)


def store_command_board_state(
    payload: CommandBoard,
    *,
    data_key: str,
    summary_key: str,
    meta_key: str,
) -> CommandBoard:
    """Persist command board state for other top-level surfaces to reuse."""
    st.session_state[data_key] = payload.data
    st.session_state[summary_key] = payload.summary
    st.session_state[meta_key] = payload.meta
    return payload


def _global_refresh_changed(marker_key: str) -> bool:
    current = str(st.session_state.get("_refresh_salt_global", "") or "")
    previous = st.session_state.get(marker_key)
    if previous is None:
        st.session_state[marker_key] = current
        return False
    if previous != current:
        st.session_state[marker_key] = current
        return True
    return False


def load_or_reuse_command_board(
    *,
    data_key: str,
    summary_key: str,
    meta_key: str,
    refresh_marker_key: str,
    company: str = DEFAULT_COMPANY,
    environment: str = DEFAULT_ENVIRONMENT,
    days: int = DEFAULT_DAY_WINDOW,
    force: bool = False,
) -> CommandBoard:
    """Return cached/fallback board immediately; query Snowflake only after explicit Refresh."""
    cached = read_command_board_state(data_key, summary_key, meta_key, company, environment, days)
    if not (force or _global_refresh_changed(refresh_marker_key)):
        return store_command_board_state(cached, data_key=data_key, summary_key=summary_key, meta_key=meta_key)

    payload = load_executive_command_board(company, environment, days)
    if not payload.summary.get("loaded"):
        payload = empty_command_board(company, environment, days, state="No mart rows")
    return store_command_board_state(payload, data_key=data_key, summary_key=summary_key, meta_key=meta_key)


def build_pipeline_sla_summary_sql(company: str = DEFAULT_COMPANY) -> str:
    """Build a tiny optional Pipeline SLA summary query."""
    company_clause = "" if str(company or "").upper() == "ALL" else f"AND UPPER(COMPANY) = {sql_literal(str(company).upper(), 100)}"
    return f"""
SELECT
    AVG(COALESCE(SLA_COMPLIANCE_PCT, 0)) AS PIPELINE_SLA_COMPLIANCE_PCT,
    SUM(COALESCE(MISSED_SLA_COUNT, 0)) AS MISSED_SLA_COUNT,
    MAX(LOAD_TS) AS LOAD_TS
FROM DBA_MAINT_DB.OVERWATCH.PIPELINE_SLA_EXECUTIVE_V
WHERE 1 = 1
  {company_clause}
"""


def load_setup_readiness(use_live: bool = False) -> pd.DataFrame:
    """Return live data readiness when available, otherwise static contract rows."""
    if use_live:
        live = run_query(
            build_schema_migration_status_sql(),
            ttl_key="data_readiness_status",
            tier="metadata",
            section="Data Health",
            max_rows=100,
        )
        if isinstance(live, pd.DataFrame) and not live.empty:
            return live
    contract = build_schema_migration_contract()
    if contract.empty:
        return contract
    fallback = contract.copy()
    fallback["OBJECT_STATE"] = "Unknown"
    fallback["MIGRATION_STATE"] = "Not checked"
    fallback["NEXT_ACTION"] = "Refresh data health after Snowflake access is available."
    return fallback
