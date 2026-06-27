# DIRECT_SQL_ADMIN_OK: explicit post-click/admin Snowflake action; never first-paint.
"""Shared first-paint monitoring summary readers.

These helpers keep the top-level sections data-first without making each shell
hand-roll its own Snowflake query. They prefer compact executive summary facts
and fail closed to data-safe frames when the summary is not ready yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from config import DEFAULTS, DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, DEFAULT_DAY_WINDOW
from runtime_state import (
    AI_CREDIT_PRICE,
    CONNECTION_AVAILABLE,
    CONNECTION_UNAVAILABLE,
    CREDIT_PRICE,
    REFRESH_SALT_GLOBAL,
    get_state,
    set_state,
)
from .company_filter import (
    get_combined_filter_clause,
    get_user_company_filter_clause,
    get_wh_filter_clause,
)
from .data import normalize_df
from .deployment import build_schema_migration_contract, build_schema_migration_status_sql
from .mart import mart_object_name
from .query import run_query, run_query_or_raise, sql_literal
from .scorecards import platform_operating_score_from_signals
from .session import apply_overwatch_query_tag, build_overwatch_query_tag, get_session, snowflake_connection_known_unavailable


COMMAND_BOARD_VERSION = "2026-06-15-shared-first-paint-v2"
FIRST_PAINT_RECENT_HOURS = 24
FIRST_PAINT_CACHE_KEY = "_overwatch_shared_first_paint_command_board"
FIRST_PAINT_SCOPE_KEY = "_overwatch_shared_first_paint_command_board_scope"
FIRST_PAINT_REFRESH_KEY = "_overwatch_shared_first_paint_command_board_refresh"

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
    """Return the cache scope for a first-paint monitoring summary."""
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
    """Return an immediate no-Snowflake monitoring summary frame for first paint."""
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


def _credit_price() -> float:
    return _safe_float(get_state(CREDIT_PRICE, DEFAULTS.get("credit_price", 3.68)), 3.68)


def _ai_credit_price() -> float:
    return _safe_float(get_state(AI_CREDIT_PRICE, DEFAULTS.get("ai_credit_price", 2.20)), 2.20)


def _first_paint_refresh_salt() -> str:
    return str(get_state(REFRESH_SALT_GLOBAL, "") or "")


def _bounded_query(sql: str, max_rows: int) -> str:
    body = str(sql or "").strip().rstrip(";")
    return f"SELECT * FROM (\n{body}\n) AS FIRST_PAINT_BOARD\nLIMIT {max(1, int(max_rows))}"


def _quiet_first_paint_query(sql: str, *, section: str, max_rows: int = 500) -> tuple[pd.DataFrame, bool]:
    """Run a bounded first-paint query without surfacing panel-level errors."""
    if snowflake_connection_known_unavailable():
        return pd.DataFrame(), False
    try:
        session = get_session()
        tag = build_overwatch_query_tag(section=section, tier="first_paint")
        apply_overwatch_query_tag(session, tag, section=section)
        frame = session.sql(_bounded_query(sql, max_rows)).to_pandas()
        return normalize_df(frame), True
    except BaseException as exc:
        if exc.__class__.__name__ == "StopException":
            set_state(CONNECTION_UNAVAILABLE, True)
            set_state(CONNECTION_AVAILABLE, False)
        return pd.DataFrame(), False


def _source_name() -> str:
    return "Snowflake Account Usage"


def _null_period() -> str:
    return "CAST(NULL AS TIMESTAMP_NTZ) AS PERIOD_START"


def build_first_paint_metering_board_sql(
    company: str = DEFAULT_COMPANY,
    days: int = DEFAULT_DAY_WINDOW,
    credit_price: float | None = None,
) -> str:
    """Return board rows from bounded warehouse metering history."""
    days = max(1, int(days or DEFAULT_DAY_WINDOW))
    rate = _safe_float(credit_price, DEFAULTS.get("credit_price", 3.68))
    wh_filter = get_wh_filter_clause("warehouse_name", company)
    source = sql_literal(_source_name(), 120)
    return f"""
WITH scoped AS (
    SELECT
        COALESCE(warehouse_name, 'No warehouse') AS warehouse_name,
        start_time,
        DATE_TRUNC('DAY', start_time) AS usage_day,
        DATE_TRUNC('MONTH', start_time) AS usage_month,
        COALESCE(credits_used, 0) AS credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
    WHERE start_time >= DATEADD('DAY', -{days * 2}, CURRENT_TIMESTAMP())
      {wh_filter}
),
rollup AS (
    SELECT
        COALESCE(SUM(IFF(start_time >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP()), credits, 0)), 0) AS current_credits,
        COALESCE(SUM(IFF(start_time < DATEADD('DAY', -{days}, CURRENT_TIMESTAMP()), credits, 0)), 0) AS prior_credits,
        COUNT(DISTINCT IFF(start_time >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP()), warehouse_name, NULL)) AS active_warehouses
    FROM scoped
),
top_wh AS (
    SELECT warehouse_name, SUM(credits) AS credits
    FROM scoped
    WHERE start_time >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
    GROUP BY warehouse_name
    ORDER BY credits DESC
    LIMIT 1
),
daily AS (
    SELECT usage_day, SUM(credits) AS credits
    FROM scoped
    WHERE start_time >= DATEADD('DAY', -LEAST({days}, 14), CURRENT_TIMESTAMP())
    GROUP BY usage_day
),
monthly AS (
    SELECT usage_month, SUM(credits) AS credits
    FROM scoped
    WHERE start_time >= DATEADD('MONTH', -6, CURRENT_TIMESTAMP())
    GROUP BY usage_month
)
SELECT 'KPI' AS PANEL, 'Credits Used' AS METRIC, 'Current' AS DIMENSION, {_null_period()},
       current_credits AS VALUE, current_credits * {rate} AS VALUE_USD, 'credits' AS UNIT, 10 AS SORT_ORDER, {source} AS SOURCE
FROM rollup
UNION ALL
SELECT 'KPI', 'Spend Delta', 'Current vs prior', {_null_period()},
       current_credits - prior_credits, (current_credits - prior_credits) * {rate}, 'credits', 20, {source}
FROM rollup
UNION ALL
SELECT 'KPI', 'Active Warehouses', 'Current', {_null_period()},
       active_warehouses, 0, 'warehouses', 30, {source}
FROM rollup
UNION ALL
SELECT 'COST_DRIVER', 'Cost Drivers', COALESCE((SELECT warehouse_name FROM top_wh), 'No warehouse'), {_null_period()},
       COALESCE((SELECT credits FROM top_wh), 0), COALESCE((SELECT credits FROM top_wh), 0) * {rate}, 'credits', 10, {source}
FROM rollup
UNION ALL
SELECT 'DAILY_COST', 'Daily Spend', TO_VARCHAR(usage_day), usage_day::TIMESTAMP_NTZ,
       credits, credits * {rate}, 'USD', 10, {source}
FROM daily
UNION ALL
SELECT 'MONTHLY_COST', 'Monthly Spend', TO_VARCHAR(usage_month), usage_month::TIMESTAMP_NTZ,
       credits, credits * {rate}, 'USD', 10, {source}
FROM monthly
"""


def build_first_paint_query_board_sql(company: str = DEFAULT_COMPANY) -> str:
    """Return board rows from the recent query-history monitoring window."""
    scope_filter = get_combined_filter_clause(
        db_col="database_name",
        wh_col="warehouse_name",
        user_col="user_name",
        company=company,
    )
    source = sql_literal(_source_name(), 120)
    hours = max(1, int(FIRST_PAINT_RECENT_HOURS))
    failure_expr = "error_code IS NOT NULL OR UPPER(COALESCE(execution_status, '')) LIKE 'FAIL%'"
    queue_expr = (
        "COALESCE(queued_overload_time, 0) + "
        "COALESCE(queued_provisioning_time, 0) + "
        "COALESCE(queued_repair_time, 0)"
    )
    return f"""
WITH scoped AS (
    SELECT
        COALESCE(warehouse_name, 'No warehouse') AS warehouse_name,
        COALESCE(database_name, 'No database') AS database_name,
        COALESCE(query_type, 'Unknown') AS query_type,
        CASE WHEN {failure_expr} THEN 'Failed' ELSE 'Succeeded' END AS execution_state,
        start_time,
        DATE_TRUNC('DAY', start_time) AS usage_day,
        COALESCE(total_elapsed_time, 0) / 1000.0 AS elapsed_sec,
        ({queue_expr}) / 1000.0 AS queue_sec,
        COALESCE(bytes_spilled_to_remote_storage, 0) / POWER(1024, 3) AS remote_spill_gb
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE start_time >= DATEADD('HOUR', -{hours}, CURRENT_TIMESTAMP())
      {scope_filter}
),
summary AS (
    SELECT
        COUNT(*) AS total_queries,
        COUNT_IF(execution_state = 'Failed') AS failed_queries,
        COALESCE(AVG(elapsed_sec), 0) AS avg_runtime_sec,
        COALESCE(APPROX_PERCENTILE(elapsed_sec, 0.95), 0) AS p95_runtime_sec,
        COALESCE(SUM(queue_sec), 0) AS queue_seconds,
        COUNT_IF(queue_sec > 0) AS queued_queries,
        COALESCE(SUM(remote_spill_gb), 0) AS remote_spill_gb,
        COUNT_IF(remote_spill_gb > 0) AS spill_queries
    FROM scoped
),
top_queue AS (
    SELECT warehouse_name, SUM(queue_sec) AS queue_seconds
    FROM scoped
    GROUP BY warehouse_name
    ORDER BY queue_seconds DESC
    LIMIT 1
),
top_spill AS (
    SELECT warehouse_name, SUM(remote_spill_gb) AS remote_spill_gb
    FROM scoped
    GROUP BY warehouse_name
    ORDER BY remote_spill_gb DESC
    LIMIT 1
),
daily AS (
    SELECT usage_day, COALESCE(APPROX_PERCENTILE(elapsed_sec, 0.95), 0) AS p95_runtime_sec, COUNT(*) AS query_count
    FROM scoped
    GROUP BY usage_day
),
query_types AS (
    SELECT query_type, COUNT(*) AS query_count
    FROM scoped
    GROUP BY query_type
),
database_mix AS (
    SELECT database_name, COUNT(*) AS query_count
    FROM scoped
    GROUP BY database_name
),
status_mix AS (
    SELECT execution_state, COUNT(*) AS query_count
    FROM scoped
    GROUP BY execution_state
)
SELECT 'KPI' AS PANEL, 'Total Queries' AS METRIC, 'Recent' AS DIMENSION, {_null_period()},
       total_queries AS VALUE, 0 AS VALUE_USD, 'queries' AS UNIT, 100 AS SORT_ORDER, {source} AS SOURCE
FROM summary
UNION ALL
SELECT 'KPI', 'Failed Queries', 'Recent', {_null_period()},
       failed_queries, 0, 'queries', 110, {source}
FROM summary
UNION ALL
SELECT 'KPI', 'Avg Runtime', 'Recent', {_null_period()},
       avg_runtime_sec, 0, 'seconds', 120, {source}
FROM summary
UNION ALL
SELECT 'KPI', 'P95 Runtime', 'Recent', {_null_period()},
       p95_runtime_sec, 0, 'seconds', 130, {source}
FROM summary
UNION ALL
SELECT 'KPI', 'Queue Time', 'Recent', {_null_period()},
       queue_seconds, 0, 'seconds', 140, {source}
FROM summary
UNION ALL
SELECT 'KPI', 'Queued Queries', 'Recent', {_null_period()},
       queued_queries, 0, 'queries', 145, {source}
FROM summary
UNION ALL
SELECT 'KPI', 'Remote Spill', 'Recent', {_null_period()},
       remote_spill_gb, 0, 'GB', 150, {source}
FROM summary
UNION ALL
SELECT 'KPI', 'Spill Queries', 'Recent', {_null_period()},
       spill_queries, 0, 'queries', 155, {source}
FROM summary
UNION ALL
SELECT 'WAREHOUSE_PRESSURE', 'Queue Seconds', COALESCE((SELECT warehouse_name FROM top_queue), 'No warehouse'), {_null_period()},
       COALESCE((SELECT queue_seconds FROM top_queue), 0), 0, 'seconds', 10, {source}
FROM summary
UNION ALL
SELECT 'WAREHOUSE_PRESSURE', 'Remote Spill GB', COALESCE((SELECT warehouse_name FROM top_spill), 'No warehouse'), {_null_period()},
       COALESCE((SELECT remote_spill_gb FROM top_spill), 0), 0, 'GB', 20, {source}
FROM summary
UNION ALL
SELECT 'DAILY_WORKLOAD', 'P95 Runtime', TO_VARCHAR(usage_day), usage_day::TIMESTAMP_NTZ,
       p95_runtime_sec, 0, 'seconds', 10, {source}
FROM daily
UNION ALL
SELECT 'DAILY_WORKLOAD', 'Query Count', TO_VARCHAR(usage_day), usage_day::TIMESTAMP_NTZ,
       query_count, 0, 'queries', 20, {source}
FROM daily
UNION ALL
SELECT 'QUERY_TYPE', 'Queries by Type', query_type, {_null_period()},
       query_count, 0, 'queries', 10, {source}
FROM query_types
UNION ALL
SELECT 'QUERY_DATABASE', 'Queries by Database', database_name, {_null_period()},
       query_count, 0, 'queries', 10, {source}
FROM database_mix
UNION ALL
SELECT 'EXEC_STATUS', 'Execution Status', execution_state, {_null_period()},
       query_count, 0, 'queries', 10, {source}
FROM status_mix
"""


def build_first_paint_task_board_sql(company: str = DEFAULT_COMPANY) -> str:
    """Return board rows from recent task history."""
    scope_filter = get_combined_filter_clause(db_col="database_name", wh_col=None, user_col=None, company=company)
    source = sql_literal(_source_name(), 120)
    hours = max(1, int(FIRST_PAINT_RECENT_HOURS))
    return f"""
WITH scoped AS (
    SELECT COALESCE(state, 'UNKNOWN') AS state
    FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
    WHERE scheduled_time >= DATEADD('HOUR', -{hours}, CURRENT_TIMESTAMP())
      {scope_filter}
),
summary AS (
    SELECT
        COUNT(*) AS task_runs,
        COUNT_IF(UPPER(state) IN ('FAILED', 'FAILED_WITH_ERROR', 'CANCELLED')) AS failed_tasks
    FROM scoped
)
SELECT 'KPI' AS PANEL, 'Task Runs' AS METRIC, 'Recent' AS DIMENSION, {_null_period()},
       task_runs AS VALUE, 0 AS VALUE_USD, 'runs' AS UNIT, 210 AS SORT_ORDER, {source} AS SOURCE
FROM summary
UNION ALL
SELECT 'KPI', 'Failed Tasks', 'Recent', {_null_period()},
       failed_tasks, 0, 'runs', 220, {source}
FROM summary
"""


def build_first_paint_security_board_sql(company: str = DEFAULT_COMPANY) -> str:
    """Return board rows from identity and grant monitoring sources."""
    login_filter = get_user_company_filter_clause("user_name", company)
    user_filter = get_user_company_filter_clause("name", company)
    grant_filter = get_user_company_filter_clause("grantee_name", company)
    source = sql_literal(_source_name(), 120)
    hours = max(1, int(FIRST_PAINT_RECENT_HOURS))
    return f"""
WITH login_summary AS (
    SELECT
        COUNT(*) AS login_events,
        COUNT_IF(NOT (UPPER(TO_VARCHAR(is_success)) IN ('TRUE', 'YES', '1'))) AS failed_logins
    FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
    WHERE event_timestamp >= DATEADD('HOUR', -{hours}, CURRENT_TIMESTAMP())
      {login_filter}
),
user_summary AS (
    SELECT
        COUNT_IF(COALESCE(disabled, FALSE) = FALSE) AS active_users,
        COUNT_IF(
            COALESCE(disabled, FALSE) = FALSE
            AND (last_success_login IS NULL OR last_success_login < DATEADD('DAY', -90, CURRENT_TIMESTAMP()))
        ) AS dormant_users
    FROM SNOWFLAKE.ACCOUNT_USAGE.USERS
    WHERE deleted_on IS NULL
      {user_filter}
),
grant_summary AS (
    SELECT COUNT(*) AS privileged_grants
    FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS
    WHERE deleted_on IS NULL
      AND UPPER(role) IN ('ACCOUNTADMIN', 'SECURITYADMIN', 'SYSADMIN', 'ORGADMIN')
      {grant_filter}
)
SELECT 'KPI' AS PANEL, 'Login Events' AS METRIC, 'Recent' AS DIMENSION, {_null_period()},
       login_events AS VALUE, 0 AS VALUE_USD, 'events' AS UNIT, 300 AS SORT_ORDER, {source} AS SOURCE
FROM login_summary
UNION ALL
SELECT 'KPI', 'Failed Logins', 'Recent', {_null_period()},
       failed_logins, 0, 'events', 310, {source}
FROM login_summary
UNION ALL
SELECT 'KPI', 'Active Users', 'Current', {_null_period()},
       active_users, 0, 'users', 320, {source}
FROM user_summary
UNION ALL
SELECT 'KPI', 'Dormant Users', 'Current', {_null_period()},
       dormant_users, 0, 'users', 330, {source}
FROM user_summary
UNION ALL
SELECT 'KPI', 'Privileged Grants', 'Current', {_null_period()},
       privileged_grants, 0, 'grants', 340, {source}
FROM grant_summary
"""


def build_first_paint_cortex_board_sql(
    days: int = DEFAULT_DAY_WINDOW,
    ai_credit_price: float | None = None,
) -> str:
    """Return board rows from account-level Cortex service metering."""
    days = max(1, int(days or DEFAULT_DAY_WINDOW))
    rate = _safe_float(ai_credit_price, DEFAULTS.get("ai_credit_price", 2.20))
    source = sql_literal(_source_name(), 120)
    return f"""
WITH scoped AS (
    SELECT COALESCE(credits_used, 0) AS credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
    WHERE start_time >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
      AND (
          UPPER(COALESCE(service_type, '')) ILIKE '%CORTEX%'
          OR UPPER(COALESCE(service_type, '')) ILIKE '%AI%'
          OR UPPER(COALESCE(service_type, '')) ILIKE '%INTELLIGENCE%'
      )
),
summary AS (
    SELECT COALESCE(SUM(credits), 0) AS cortex_credits
    FROM scoped
)
SELECT 'KPI' AS PANEL, 'Cortex Spend' AS METRIC, 'Current' AS DIMENSION, {_null_period()},
       cortex_credits AS VALUE, cortex_credits * {rate} AS VALUE_USD, 'credits' AS UNIT, 40 AS SORT_ORDER, {source} AS SOURCE
FROM summary
"""


def _append_board_metric(
    rows: list[dict[str, object]],
    *,
    panel: str,
    metric: str,
    dimension: str,
    value: float,
    value_usd: float = 0.0,
    unit: str = "count",
    sort_order: int = 900,
    source: str = "Snowflake Account Usage",
) -> None:
    rows.append({
        "PANEL": panel,
        "METRIC": metric,
        "DIMENSION": dimension,
        "PERIOD_START": None,
        "VALUE": value,
        "VALUE_USD": value_usd,
        "UNIT": unit,
        "SORT_ORDER": sort_order,
        "SOURCE": source,
    })


def _with_first_paint_action_rows(board: pd.DataFrame) -> pd.DataFrame:
    """Add derived monitoring pressure rows from first-paint facts."""
    rows = _normalize_board(board)
    if rows.empty:
        return rows
    failed_queries = _safe_int(_metric_value(rows, "Failed Queries"))
    failed_tasks = _safe_int(_metric_value(rows, "Failed Tasks"))
    failed_logins = _safe_int(_metric_value(rows, "Failed Logins"))
    privileged_grants = _safe_int(_metric_value(rows, "Privileged Grants"))
    dormant_users = _safe_int(_metric_value(rows, "Dormant Users"))
    queue_seconds = _safe_float(_metric_value(rows, "Queue Time"))
    remote_spill_gb = _safe_float(_metric_value(rows, "Remote Spill"))
    signal_flags = (
        failed_queries > 0,
        failed_tasks > 0,
        failed_logins > 0,
        privileged_grants > 0,
        dormant_users > 0,
        queue_seconds > 0,
        remote_spill_gb > 0,
    )
    critical_high = int(sum(signal_flags))
    derived_rows: list[dict[str, object]] = []
    _append_board_metric(
        derived_rows,
        panel="KPI",
        metric="Critical High Alerts",
        dimension="Derived monitoring signals",
        value=critical_high,
        unit="signals",
        sort_order=400,
    )
    _append_board_metric(
        derived_rows,
        panel="KPI",
        metric="Open Actions",
        dimension="Derived monitoring signals",
        value=critical_high,
        unit="actions",
        sort_order=410,
    )
    _append_board_metric(
        derived_rows,
        panel="KPI",
        metric="High Actions",
        dimension="Derived monitoring signals",
        value=critical_high,
        unit="actions",
        sort_order=420,
    )
    return _normalize_board(pd.concat([rows, pd.DataFrame(derived_rows)], ignore_index=True))


def placeholder_command_board(
    company: str = DEFAULT_COMPANY,
    environment: str = DEFAULT_ENVIRONMENT,
    days: int = DEFAULT_DAY_WINDOW,
) -> CommandBoard:
    """Return an instant command frame while scheduled facts or refresh hydrate."""
    scope = command_board_scope(company, environment, days)
    source = "Monitoring telemetry"
    rows: list[dict[str, object]] = []
    metrics = (
        ("Credits Used", 0.0, 0.0, "credits", 10),
        ("Spend Delta", 0.0, 0.0, "credits", 20),
        ("Cortex Spend", 0.0, 0.0, "credits", 40),
        ("Total Queries", 0.0, 0.0, "queries", 100),
        ("Failed Queries", 0.0, 0.0, "queries", 110),
        ("Avg Runtime", 0.0, 0.0, "seconds", 120),
        ("P95 Runtime", 0.0, 0.0, "seconds", 130),
        ("Queue Time", 0.0, 0.0, "seconds", 140),
        ("Queued Queries", 0.0, 0.0, "queries", 145),
        ("Remote Spill", 0.0, 0.0, "GB", 150),
        ("Spill Queries", 0.0, 0.0, "queries", 155),
        ("Task Runs", 0.0, 0.0, "runs", 210),
        ("Failed Tasks", 0.0, 0.0, "runs", 220),
        ("Login Events", 0.0, 0.0, "events", 300),
        ("Failed Logins", 0.0, 0.0, "events", 310),
        ("Active Users", 0.0, 0.0, "users", 320),
        ("Dormant Users", 0.0, 0.0, "users", 330),
        ("Privileged Grants", 0.0, 0.0, "grants", 340),
        ("Active Warehouses", 0.0, 0.0, "warehouses", 350),
        ("Critical High Alerts", 0.0, 0.0, "signals", 400),
        ("Open Actions", 0.0, 0.0, "actions", 410),
        ("High Actions", 0.0, 0.0, "actions", 420),
        ("Storage", 0.0, 0.0, "TB", 430),
    )
    for metric, value, value_usd, unit, sort_order in metrics:
        _append_board_metric(
            rows,
            panel="KPI",
            metric=metric,
            dimension="Current",
            value=value,
            value_usd=value_usd,
            unit=unit,
            sort_order=sort_order,
            source=source,
        )
    _append_board_metric(
        rows,
        panel="COST_DRIVER",
        metric="Cost Drivers",
        dimension="None",
        value=0.0,
        value_usd=0.0,
        unit="credits",
        sort_order=10,
        source=source,
    )
    _append_board_metric(
        rows,
        panel="WAREHOUSE_PRESSURE",
        metric="Queue Seconds",
        dimension="No warehouse",
        value=0.0,
        unit="seconds",
        sort_order=10,
        source=source,
    )
    _append_board_metric(
        rows,
        panel="WAREHOUSE_PRESSURE",
        metric="Remote Spill GB",
        dimension="No warehouse",
        value=0.0,
        unit="GB",
        sort_order=20,
        source=source,
    )
    _append_board_metric(
        rows,
        panel="EXEC_STATUS",
        metric="Execution Status",
        dimension="Succeeded",
        value=0.0,
        unit="queries",
        sort_order=10,
        source=source,
    )
    today = pd.Timestamp.today().normalize()
    for offset in range(6, -1, -1):
        day = today - pd.Timedelta(days=offset)
        rows.append({
            "PANEL": "DAILY_COST",
            "METRIC": "Daily Spend",
            "DIMENSION": day.strftime("%Y-%m-%d"),
            "PERIOD_START": day,
            "VALUE": 0.0,
            "VALUE_USD": 0.0,
            "UNIT": "USD",
            "SORT_ORDER": 10,
            "SOURCE": source,
        })
        rows.append({
            "PANEL": "DAILY_WORKLOAD",
            "METRIC": "P95 Runtime",
            "DIMENSION": day.strftime("%Y-%m-%d"),
            "PERIOD_START": day,
            "VALUE": 0.0,
            "VALUE_USD": 0.0,
            "UNIT": "seconds",
            "SORT_ORDER": 10,
            "SOURCE": source,
        })
    board = _normalize_board(pd.DataFrame(rows))
    summary = summarize_command_board(board)
    summary["state"] = "Telemetry pending"
    summary["cap_reason"] = "Scheduled monitoring facts or an explicit refresh will hydrate this shared monitoring summary."
    return CommandBoard(
        data=board,
        summary=summary,
        meta={
            "source": source,
            "available": False,
            "first_paint": True,
            "placeholder": True,
            "state": "Telemetry pending",
            "company": scope[0],
            "environment": scope[1],
            "days": scope[2],
        },
    )


def load_first_paint_command_board(
    company: str = DEFAULT_COMPANY,
    environment: str = DEFAULT_ENVIRONMENT,
    days: int = DEFAULT_DAY_WINDOW,
) -> CommandBoard:
    """Load and cache the shared first-paint monitoring board for all primary sections."""
    scope = command_board_scope(company, environment, days)
    refresh_salt = _first_paint_refresh_salt()
    cached = get_state(FIRST_PAINT_CACHE_KEY)
    cached_scope = get_state(FIRST_PAINT_SCOPE_KEY)
    cached_refresh = get_state(FIRST_PAINT_REFRESH_KEY)
    if (
        isinstance(cached, CommandBoard)
        and cached_scope == scope
        and cached_refresh == refresh_salt
    ):
        return cached

    frames: list[pd.DataFrame] = []
    successes = 0
    queries = (
        (
            build_first_paint_metering_board_sql(company, days, _credit_price()),
            "Monitoring Summary",
            700,
        ),
        (
            build_first_paint_query_board_sql(company),
            "Monitoring Summary",
            700,
        ),
        (
            build_first_paint_task_board_sql(company),
            "Monitoring Summary",
            100,
        ),
        (
            build_first_paint_security_board_sql(company),
            "Monitoring Summary",
            100,
        ),
        (
            build_first_paint_cortex_board_sql(days, _ai_credit_price()),
            "Monitoring Summary",
            100,
        ),
    )
    for sql, section, max_rows in queries:
        frame, ok = _quiet_first_paint_query(sql, section=section, max_rows=max_rows)
        successes += int(ok)
        if isinstance(frame, pd.DataFrame) and not frame.empty:
            frames.append(frame)

    if frames:
        board = _with_first_paint_action_rows(pd.concat(frames, ignore_index=True))
        loaded_at = datetime.now().isoformat(timespec="seconds")
        payload = CommandBoard(
            data=board,
            summary=summarize_command_board(board),
            meta={
                "source": "SNOWFLAKE.ACCOUNT_USAGE",
                "loaded_at": loaded_at,
                "company": scope[0],
                "environment": scope[1],
                "days": scope[2],
                "available": True,
                "first_paint": True,
                "successes": successes,
            },
        )
    else:
        payload = empty_command_board(company, environment, days, state="Telemetry unavailable")
        payload.summary["cap_reason"] = (
            "Monitoring telemetry is unavailable for this scope. The summary remains open while "
            "Snowflake access or account-usage history catches up."
        )
        payload.meta["source"] = "SNOWFLAKE.ACCOUNT_USAGE"
        payload.meta["successes"] = successes

    set_state(FIRST_PAINT_CACHE_KEY, payload)
    set_state(FIRST_PAINT_SCOPE_KEY, scope)
    set_state(FIRST_PAINT_REFRESH_KEY, refresh_salt)
    return payload


def build_executive_command_board_sql(
    company: str = DEFAULT_COMPANY,
    environment: str = DEFAULT_ENVIRONMENT,
    days: int = DEFAULT_DAY_WINDOW,
) -> str:
    """Build the compact mart query used by first-paint monitoring summaries."""
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
        "queued_queries": _safe_int(_metric_value(rows, "Queued Queries")),
        "remote_spill_gb": _metric_value(rows, "Remote Spill"),
        "spill_queries": _safe_int(_metric_value(rows, "Spill Queries")),
        "failed_queries": _safe_int(_metric_value(rows, "Failed Queries")),
        "task_runs": _safe_int(_metric_value(rows, "Task Runs")),
        "failed_tasks": _safe_int(_metric_value(rows, "Failed Tasks")),
        "login_events": _safe_int(_metric_value(rows, "Login Events")),
        "failed_logins": _safe_int(_metric_value(rows, "Failed Logins")),
        "active_users": _safe_int(_metric_value(rows, "Active Users")),
        "dormant_users": _safe_int(_metric_value(rows, "Dormant Users")),
        "privileged_grants": _safe_int(_metric_value(rows, "Privileged Grants")),
        "active_warehouses": _safe_int(_metric_value(rows, "Active Warehouses")),
        "critical_high_alerts": _safe_int(_metric_value(rows, "Critical High Alerts")),
        "open_actions": _safe_int(_metric_value(rows, "Open Actions")),
        "high_actions": _safe_int(_metric_value(rows, "High Actions")) or _safe_int(_metric_value(rows, "Critical High Alerts")),
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
    summary["oldest_alert_age"] = "Current window" if summary["critical_high_alerts"] else "No active signal"
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
    try:
        frame = run_query_or_raise(
            sql,
            ttl_key=f"command_board_{company}_{environment}_{int(days)}",
            tier="standard",
            section="Monitoring Summary",
            max_rows=500,
        )
    except Exception:
        return empty_command_board(company, environment, days, state="Mart unavailable")
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
    """Read a monitoring summary from session state or return an immediate fallback."""
    scope = command_board_scope(company, environment, days)
    meta = get_state(meta_key)
    summary = get_state(summary_key)
    data = get_state(data_key)
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
    """Persist monitoring summary state for other top-level surfaces to reuse."""
    set_state(data_key, payload.data)
    set_state(summary_key, payload.summary)
    set_state(meta_key, payload.meta)
    return payload


def _global_refresh_changed(marker_key: str) -> bool:
    current = str(get_state(REFRESH_SALT_GLOBAL, "") or "")
    previous = get_state(marker_key)
    if previous is None:
        set_state(marker_key, current)
        return False
    if previous != current:
        set_state(marker_key, current)
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
    """Return the shared monitoring summary, preferring marts and using bounded first-paint telemetry."""
    cached = read_command_board_state(data_key, summary_key, meta_key, company, environment, days)
    refresh_changed = _global_refresh_changed(refresh_marker_key)
    if cached.summary.get("loaded") and not (force or refresh_changed):
        return store_command_board_state(cached, data_key=data_key, summary_key=summary_key, meta_key=meta_key)

    payload = load_executive_command_board(company, environment, days)
    if not payload.summary.get("loaded"):
        payload = load_first_paint_command_board(company, environment, days)
    if not payload.summary.get("loaded"):
        payload = empty_command_board(company, environment, days, state="No monitoring rows")
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
# DIRECT_SQL_ADMIN_OK: explicit post-click/admin Snowflake action; never first-paint.
