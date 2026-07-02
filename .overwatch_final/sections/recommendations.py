# sections/recommendations.py - recommendations, persistent action queue, and anomalies
from html import escape as html_escape

import pandas as pd
import streamlit as st

from config import DEFAULTS, THRESHOLDS, WAREHOUSE_ADVISOR_CONFIG
from sections.warehouse_health import (
    _build_warehouse_cost_control_posture,
    _build_warehouse_guardrail_coverage,
    _warehouse_setting_action_plan,
)
from sections.shell_helpers import render_escaped_bold_text, render_shell_snapshot
from utils import (
    credits_to_dollars,
    day_window_selectbox,
    defer_source_note,
    download_csv,
    format_snowflake_error,
    format_credits,
    get_storage_cost_per_tb,
    get_session,
    load_shared_recommendation_failed_tasks,
    load_shared_recommendation_idle_warehouses,
    load_shared_recommendation_query_failures,
    load_shared_recommendation_spill_warehouses,
    load_shared_recommendation_storage_retention,
    load_shared_recommendation_clustering_cost,
    load_shared_recommendation_repeated_queries,
    load_shared_warehouse_overview,
    load_shared_warehouse_credit_anomalies,
    load_warehouse_inventory,
    load_action_queue,
    make_action_id,
    metric_confidence_label,
    freshness_note,
    safe_float,
    safe_int,
    safe_identifier,
    sql_literal,
    upsert_actions,
)
from utils.display_safety import clean_display_text
from utils.recommendation_intelligence import build_automation_readiness_board, harden_recommendation
from utils.workflows import clean_operator_display_text, render_load_status, render_priority_dataframe, render_workflow_selector


RECOMMENDATION_PANES = (
    "Recommendations",
    "Warehouse Advisor",
    "Queue Health",
    "Action Queue",
    "Anomaly Log",
)


def _plain_html(value: object) -> str:
    """Render generated object/action text literally inside small HTML fragments."""
    return html_escape(clean_display_text(value), quote=False)


def _active_company() -> str:
    return st.session_state.get("active_company", "ALFA")


def _recommendation_frame(recs: list[dict]) -> pd.DataFrame:
    if not recs:
        return pd.DataFrame()
    df = pd.DataFrame([harden_recommendation(rec) for rec in recs])
    df["Action ID"] = df.apply(
        lambda r: make_action_id(r["Category"], r["Entity"], r["Finding"]),
        axis=1,
    )
    df["Status"] = "New"
    sort_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    df["_sort"] = df["Severity"].map(sort_order).fillna(9)
    return df.sort_values(["_sort", "Estimated Monthly Savings"], ascending=[True, False]).drop(columns=["_sort"])


def _row_text(row, column: str, default: str = "") -> str:
    value = row.get(column, default)
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    return str(value)


def _float_text_or_none(value: str):
    text = str(value or "").strip()
    return None if not text else safe_float(text)


def _idle_warehouse_verification_sql(warehouse_name: str, days: int = 7) -> str:
    wh = sql_literal(warehouse_name, 300)
    return f"""-- Idle warehouse post-fix telemetry
WITH metering AS (
    SELECT DATE_TRUNC('hour', start_time) AS usage_hour,
           warehouse_name,
           SUM(COALESCE(credits_used, 0)) AS credits_used
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
    WHERE warehouse_name = {wh}
      AND start_time >= DATEADD('day', -{max(1, int(days or 7))}, CURRENT_TIMESTAMP())
    GROUP BY usage_hour, warehouse_name
),
queries AS (
    SELECT DATE_TRUNC('hour', start_time) AS usage_hour,
           warehouse_name,
           COUNT(*) AS query_count
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE warehouse_name = {wh}
      AND start_time >= DATEADD('day', -{max(1, int(days or 7))}, CURRENT_TIMESTAMP())
    GROUP BY usage_hour, warehouse_name
)
SELECT m.warehouse_name,
       COUNT_IF(COALESCE(q.query_count, 0) = 0) AS idle_hours,
       ROUND(SUM(IFF(COALESCE(q.query_count, 0) = 0, m.credits_used, 0)), 4) AS idle_credits,
       ROUND(SUM(m.credits_used), 4) AS total_credits
FROM metering m
LEFT JOIN queries q
  ON m.warehouse_name = q.warehouse_name
 AND m.usage_hour = q.usage_hour
GROUP BY m.warehouse_name
ORDER BY idle_credits DESC
LIMIT 50;
"""


def _remote_spill_verification_sql(warehouse_name: str, days: int = 7) -> str:
    wh = sql_literal(warehouse_name, 300)
    return f"""-- Remote spill post-fix telemetry
SELECT warehouse_name,
       COUNT(*) AS spilling_queries,
       ROUND(SUM(COALESCE(bytes_spilled_to_remote_storage, 0)) / POWER(1024, 3), 2) AS remote_spill_gb,
       MAX(start_time) AS last_spill_time
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE warehouse_name = {wh}
  AND start_time >= DATEADD('day', -{max(1, int(days or 7))}, CURRENT_TIMESTAMP())
  AND COALESCE(bytes_spilled_to_remote_storage, 0) > 0
GROUP BY warehouse_name
ORDER BY remote_spill_gb DESC
LIMIT 50;
"""


def _task_failure_verification_sql(task_name: str, days: int = 7) -> str:
    task = sql_literal(task_name, 500)
    return f"""-- Task failure post-fix telemetry
SELECT name,
       database_name,
       schema_name,
       state,
       COUNT(*) AS runs,
       COUNT_IF(state = 'FAILED') AS failed_runs,
       MAX(scheduled_time) AS latest_scheduled_time,
       MAX(completed_time) AS latest_completed_time
FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
WHERE scheduled_time >= DATEADD('day', -{max(1, int(days or 7))}, CURRENT_TIMESTAMP())
  AND name = {task}
GROUP BY name, database_name, schema_name, state
ORDER BY failed_runs DESC, latest_scheduled_time DESC
LIMIT 50;
"""


def _query_failure_verification_sql(warehouse_name: str, days: int = 7) -> str:
    wh = sql_literal(warehouse_name, 300)
    return f"""-- Query failure post-fix telemetry
SELECT warehouse_name,
       error_code,
       COUNT(*) AS failures,
       MAX(start_time) AS latest_failure_time,
       SUBSTR(MAX(error_message), 1, 1000) AS sample_error_message
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE warehouse_name = {wh}
  AND start_time >= DATEADD('day', -{max(1, int(days or 7))}, CURRENT_TIMESTAMP())
  AND UPPER(execution_status) = 'FAILED_WITH_ERROR'
GROUP BY warehouse_name, error_code
ORDER BY failures DESC
LIMIT 50;
"""


def _storage_retention_verification_sql(database_name: str) -> str:
    db = sql_literal(database_name, 300)
    return f"""-- Storage retention telemetry
SELECT table_catalog AS database_name,
       ROUND(SUM(COALESCE(active_bytes, 0)) / POWER(1024, 4), 3) AS active_tb,
       ROUND(SUM(COALESCE(time_travel_bytes, 0)) / POWER(1024, 4), 3) AS time_travel_tb,
       ROUND(SUM(COALESCE(failsafe_bytes, 0)) / POWER(1024, 4), 3) AS failsafe_tb
FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS
WHERE deleted = FALSE
  AND table_catalog = {db}
GROUP BY table_catalog
ORDER BY time_travel_tb DESC;
"""


def _clustering_verification_sql(table_name: str, days: int = 7) -> str:
    table = sql_literal(table_name, 1000)
    return f"""-- Automatic clustering cost telemetry
SELECT database_name || '.' || schema_name || '.' || table_name AS table_name,
       ROUND(SUM(COALESCE(credits_used, 0)), 4) AS clustering_credits,
       ROUND(SUM(COALESCE(num_bytes_reclustered, 0)) / POWER(1024, 4), 4) AS tb_reclustered,
       SUM(COALESCE(num_rows_reclustered, 0)) AS rows_reclustered,
       MAX(start_time) AS latest_cluster_event
FROM SNOWFLAKE.ACCOUNT_USAGE.AUTOMATIC_CLUSTERING_HISTORY
WHERE start_time >= DATEADD('day', -{max(1, int(days or 7))}, CURRENT_TIMESTAMP())
  AND database_name || '.' || schema_name || '.' || table_name = {table}
GROUP BY database_name, schema_name, table_name
ORDER BY clustering_credits DESC;
"""


def _repeated_query_verification_sql(query_hash: str, hash_column: str, days: int = 7) -> str:
    qh = sql_literal(query_hash, 300)
    column = safe_identifier(hash_column)
    return f"""-- Repeated query pattern telemetry
SELECT {column} AS query_hash,
       COUNT(*) AS runs,
       COUNT(DISTINCT user_name) AS users,
       ROUND(SUM(COALESCE(total_elapsed_time, 0)) / 1000 / 3600, 2) AS total_exec_hours,
       ROUND(SUM(COALESCE(bytes_scanned, 0)) / POWER(1024, 4), 2) AS tb_scanned,
       MAX(start_time) AS latest_run,
       SUBSTR(MAX(query_text), 1, 1000) AS sample_query
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD('day', -{max(1, int(days or 7))}, CURRENT_TIMESTAMP())
  AND {column} = {qh}
GROUP BY {column}
ORDER BY runs DESC;
"""


def _automation_playbook_frame() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "AUTOMATION_LANE": "Ready",
            "WHAT_IT_MEANS": "Safe SQL shape, escalation route, rollback boundary, and telemetry are present.",
            "DBA_ACTION": "Use the guarded admin workflow when action is still needed.",
        },
        {
            "AUTOMATION_LANE": "Telemetry Pending",
            "WHAT_IT_MEANS": "The action looks automatable, but fresh telemetry has not confirmed the state.",
            "DBA_ACTION": "Wait for the next telemetry refresh before action.",
        },
        {
            "AUTOMATION_LANE": "Needs Data",
            "WHAT_IT_MEANS": "The action lacks enough telemetry or routing context.",
            "DBA_ACTION": "Load the missing data before routing.",
        },
        {
            "AUTOMATION_LANE": "DBA Review",
            "WHAT_IT_MEANS": "The action touches security, task execution, failover, clustering telemetry, or unsafe SQL.",
            "DBA_ACTION": "Keep it in the guarded DBA workflow.",
        },
        {
            "AUTOMATION_LANE": "Resolved Candidate",
            "WHAT_IT_MEANS": "The action is already closed in telemetry.",
            "DBA_ACTION": "Keep it out of active work queues.",
        },
    ])


def _warehouse_control_scope(company: str, days: int) -> dict:
    return {
        "company": str(company or "").strip(),
        "days": int(days),
        "warehouse": str(st.session_state.get("global_warehouse", "") or "").strip(),
        "environment": str(st.session_state.get("global_environment", "") or "").strip(),
    }


def _warehouse_control_scope_matches(meta: dict | None, expected: dict) -> bool:
    if not isinstance(meta, dict):
        return False
    for key, value in expected.items():
        if key == "days":
            try:
                if int(meta.get(key)) != int(value):
                    return False
            except Exception:
                return False
        elif str(meta.get(key, "") or "").strip() != str(value or "").strip():
            return False
    return True


def _load_warehouse_control_plan(session, company: str, days: int) -> None:
    overview_result = load_shared_warehouse_overview(
        session,
        days,
        company,
        force=True,
        section="Recommendations",
    )
    inventory = load_warehouse_inventory(session, company)
    summary, guardrail_board = _build_warehouse_guardrail_coverage(
        overview_result.data,
        settings_inventory=inventory,
    )
    cost_summary, cost_posture = _build_warehouse_cost_control_posture(
        inventory,
        overview_result.data,
    )
    setting_plan = _warehouse_setting_action_plan(guardrail_board)
    st.session_state["rec_warehouse_control_overview"] = overview_result.data
    st.session_state["rec_warehouse_control_inventory"] = inventory
    st.session_state["rec_warehouse_control_guardrails"] = guardrail_board
    st.session_state["rec_warehouse_control_summary"] = summary
    st.session_state["rec_warehouse_cost_control_summary"] = cost_summary
    st.session_state["rec_warehouse_cost_control_posture"] = cost_posture
    st.session_state["rec_warehouse_control_plan"] = setting_plan
    st.session_state["rec_warehouse_control_source"] = overview_result.source
    st.session_state["rec_warehouse_control_meta"] = _warehouse_control_scope(company, days)
    st.session_state["rec_warehouse_control_error"] = ""


def _warehouse_size_rank(size: object) -> int:
    order = {
        "XSMALL": 0,
        "X-SMALL": 0,
        "SMALL": 1,
        "MEDIUM": 2,
        "LARGE": 3,
        "XLARGE": 4,
        "X-LARGE": 4,
        "XXLARGE": 5,
        "2X-LARGE": 5,
        "XXXLARGE": 6,
        "3X-LARGE": 6,
        "4X-LARGE": 7,
        "5X-LARGE": 8,
        "6X-LARGE": 9,
    }
    return order.get(str(size or "").strip().upper(), -1)


def _warehouse_monthly_run_rate(metered_credits: object, days: int, credit_price: float) -> float:
    days = max(1, int(days or 1))
    return round(credits_to_dollars(safe_float(metered_credits) / days * 30.0, credit_price), 2)


def _row_first_float(row: object, *columns: str) -> float:
    if not hasattr(row, "get"):
        return 0.0
    for column in columns:
        value = row.get(column)
        if value is None:
            continue
        numeric = safe_float(value)
        if numeric != 0.0:
            return numeric
    return 0.0


def _row_first_int(row: object, *columns: str) -> int:
    if not hasattr(row, "get"):
        return 0
    for column in columns:
        value = row.get(column)
        if value is None:
            continue
        numeric = safe_int(value)
        if numeric:
            return numeric
    return 0


def _auto_suspend_savings_rate(auto_suspend: object) -> float:
    if auto_suspend is None:
        return 0.0
    seconds = safe_int(auto_suspend, -1)
    if seconds == 0:
        return safe_float(dict(WAREHOUSE_ADVISOR_CONFIG["auto_suspend_savings_rates"]).get(0, 0.50))
    for floor_seconds, rate in sorted(WAREHOUSE_ADVISOR_CONFIG["auto_suspend_savings_rates"], reverse=True):
        if int(floor_seconds) == 0:
            continue
        if seconds >= int(floor_seconds):
            return safe_float(rate)
    return 0.0


def _warehouse_advisor_verification_window() -> int:
    return max(1, safe_int(WAREHOUSE_ADVISOR_CONFIG.get("verification_window_days"), 7))


def _advisor_priority(severity: str) -> int:
    return {"High": 0, "Medium": 1, "Low": 2, "Info": 3}.get(str(severity or ""), 9)


def _warehouse_advisor_impact_display(row: object) -> str:
    savings = safe_float(row.get("EST_MONTHLY_SAVINGS_USD")) if hasattr(row, "get") else 0.0
    value_at_risk = safe_float(row.get("VALUE_AT_RISK_USD")) if hasattr(row, "get") else 0.0
    if savings > 0:
        return f"${savings:,.0f}/mo savings"
    if value_at_risk > 0:
        return f"${value_at_risk:,.0f}/mo value at risk"
    return "Pressure evidence captured"


def _build_warehouse_advisor_recommendations(
    plan: pd.DataFrame | None,
    posture: pd.DataFrame | None,
    overview: pd.DataFrame | None,
    *,
    days: int,
    credit_price: float,
) -> pd.DataFrame:
    """Build presentation-safe warehouse recommendations without generated DDL."""
    columns = [
        "PRIORITY", "WAREHOUSE_NAME", "ADVISOR_TYPE", "RECOMMENDATION",
        "WHY", "CURRENT_SIGNAL", "CURRENT_SETTING", "EST_MONTHLY_COST_BASIS_USD",
        "MONTHLY_RUN_RATE_USD", "EST_MONTHLY_SAVINGS_USD", "VALUE_AT_RISK_USD",
        "VERIFIED_MONTHLY_SAVINGS_USD", "SAVINGS_STATUS", "SAVINGS_ASSUMPTION",
        "SAVINGS_TYPE", "IMPACT_DISPLAY", "REMOTE_SPILL_GB", "AVG_QUEUE_SEC", "P95_ELAPSED_SEC", "PERFORMANCE_RISK",
        "ACTION_POSTURE", "SAFE_NEXT_STEP",
        "ADMIN_WORKFLOW", "VERIFY_NEXT", "VERIFICATION_WINDOW_DAYS", "CONFIDENCE",
        "EXPECTED_VERIFICATION_IMPACT", "DO_NOT_EXECUTE_UNTIL",
    ]
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()

    def add(row: dict[str, object]) -> None:
        wh = str(row.get("WAREHOUSE_NAME") or "Unknown warehouse").strip() or "Unknown warehouse"
        kind = str(row.get("ADVISOR_TYPE") or row.get("RECOMMENDATION") or "Recommendation").strip()
        key = (wh.upper(), kind.upper())
        if key in seen:
            return
        seen.add(key)
        normalized = {column: row.get(column, "") for column in columns}
        normalized["WAREHOUSE_NAME"] = wh
        normalized["EST_MONTHLY_SAVINGS_USD"] = round(safe_float(normalized.get("EST_MONTHLY_SAVINGS_USD")), 2)
        normalized["VERIFIED_MONTHLY_SAVINGS_USD"] = round(safe_float(normalized.get("VERIFIED_MONTHLY_SAVINGS_USD")), 2)
        normalized["MONTHLY_RUN_RATE_USD"] = round(safe_float(normalized.get("MONTHLY_RUN_RATE_USD")), 2)
        normalized["EST_MONTHLY_COST_BASIS_USD"] = round(
            safe_float(normalized.get("EST_MONTHLY_COST_BASIS_USD"))
            or safe_float(normalized.get("MONTHLY_RUN_RATE_USD")),
            2,
        )
        value_at_risk = safe_float(normalized.get("VALUE_AT_RISK_USD"))
        pressure_value = max(
            safe_float(normalized.get("EST_MONTHLY_COST_BASIS_USD")),
            safe_float(normalized.get("MONTHLY_RUN_RATE_USD")),
        )
        if value_at_risk <= 0 and safe_float(normalized.get("EST_MONTHLY_SAVINGS_USD")) <= 0:
            value_at_risk = pressure_value
        normalized["VALUE_AT_RISK_USD"] = round(max(0.0, value_at_risk), 2)
        normalized["REMOTE_SPILL_GB"] = round(safe_float(normalized.get("REMOTE_SPILL_GB")), 2)
        normalized["AVG_QUEUE_SEC"] = round(safe_float(normalized.get("AVG_QUEUE_SEC")), 2)
        normalized["P95_ELAPSED_SEC"] = round(safe_float(normalized.get("P95_ELAPSED_SEC")), 2)
        normalized["SAVINGS_STATUS"] = normalized.get("SAVINGS_STATUS") or (
            "Needs Verification" if normalized["EST_MONTHLY_SAVINGS_USD"] else "Not Claimed"
        )
        normalized["SAVINGS_TYPE"] = normalized.get("SAVINGS_TYPE") or (
            "Estimated recoverable savings" if normalized["EST_MONTHLY_SAVINGS_USD"] else "No savings claimed"
        )
        normalized["ACTION_POSTURE"] = normalized.get("ACTION_POSTURE") or (
            "Guarded admin change candidate" if normalized["EST_MONTHLY_SAVINGS_USD"] else "Review only"
        )
        normalized["IMPACT_DISPLAY"] = normalized.get("IMPACT_DISPLAY") or _warehouse_advisor_impact_display(normalized)
        normalized["EXPECTED_VERIFICATION_IMPACT"] = (
            normalized.get("EXPECTED_VERIFICATION_IMPACT")
            or "Post-change telemetry should show lower credits without worse queue, spill, p95, or failures."
        )
        normalized["DO_NOT_EXECUTE_UNTIL"] = (
            normalized.get("DO_NOT_EXECUTE_UNTIL")
            or "Do not execute until workload context and rollback evidence are reviewed."
        )
        normalized["VERIFICATION_WINDOW_DAYS"] = safe_int(
            normalized.get("VERIFICATION_WINDOW_DAYS"),
            _warehouse_advisor_verification_window(),
        )
        rows.append(normalized)

    posture_view = posture if isinstance(posture, pd.DataFrame) else pd.DataFrame()
    for _, row in posture_view.iterrows():
        state = str(row.get("COST_CONTROL_STATE") or "").strip()
        if state not in {"Blocked", "Needs Review", "Watch"}:
            continue
        wh = str(row.get("WAREHOUSE_NAME") or "Unknown warehouse")
        recommended_suspend = (
            safe_int(row.get("RECOMMENDED_AUTO_SUSPEND_SEC"), WAREHOUSE_ADVISOR_CONFIG["default_auto_suspend_sec"])
            or WAREHOUSE_ADVISOR_CONFIG["default_auto_suspend_sec"]
        )
        monthly = _warehouse_monthly_run_rate(
            _row_first_float(row, "METERED_CREDITS", "TOTAL_CREDITS", "CREDITS_USED", "CREDITS_USED_COMPUTE"),
            days,
            credit_price,
        )
        savings_rate = _auto_suspend_savings_rate(row.get("AUTO_SUSPEND_SEC"))
        savings = round(monthly * savings_rate, 2)
        auto_resume = row.get("AUTO_RESUME")
        if auto_resume is False and savings <= 0:
            savings = 0.0
        add({
            "PRIORITY": "High" if state == "Blocked" else "Medium",
            "WAREHOUSE_NAME": wh,
            "ADVISOR_TYPE": "Auto-suspend savings",
            "RECOMMENDATION": f"Target AUTO_SUSPEND={recommended_suspend}s after workload review.",
            "WHY": str(row.get("RECOMMENDED_ACTION") or "Auto-suspend or auto-resume settings need DBA review."),
            "CURRENT_SIGNAL": str(row.get("IDLE_RISK") or state),
            "CURRENT_SETTING": (
                f"AUTO_SUSPEND={row.get('AUTO_SUSPEND_SEC') if row.get('AUTO_SUSPEND_SEC') is not None else 'not loaded'}, "
                f"AUTO_RESUME={row.get('AUTO_RESUME') if row.get('AUTO_RESUME') is not None else 'not loaded'}"
            ),
            "EST_MONTHLY_SAVINGS_USD": savings,
            "EST_MONTHLY_COST_BASIS_USD": monthly,
            "VERIFIED_MONTHLY_SAVINGS_USD": 0.0,
            "SAVINGS_STATUS": "Needs Verification" if savings else "Not Claimed",
            "SAVINGS_ASSUMPTION": f"{savings_rate:.0%} recoverable idle/suspend run-rate from loaded metering.",
            "SAVINGS_TYPE": "Estimated idle/suspend savings" if savings else "No savings claimed",
            "MONTHLY_RUN_RATE_USD": monthly,
            "REMOTE_SPILL_GB": _row_first_float(row, "TOTAL_REMOTE_SPILL_GB", "REMOTE_SPILL_GB"),
            "AVG_QUEUE_SEC": _row_first_float(row, "AVG_QUEUED_SEC", "AVG_QUEUE_SEC", "QUEUE_SECONDS"),
            "P95_ELAPSED_SEC": _row_first_float(row, "P95_ELAPSED_SEC", "P95_SEC", "P95_RUNTIME_SEC"),
            "PERFORMANCE_RISK": "Validate p95, queue, spill, and failed-query behavior before shortening suspend.",
            "ACTION_POSTURE": "Guarded admin change candidate",
            "SAFE_NEXT_STEP": "Open DBA Control Room > Admin > Warehouse Settings, preview the change, and use typed confirmation only after review.",
            "ADMIN_WORKFLOW": "DBA Control Room > Admin > Warehouse Settings",
            "VERIFY_NEXT": "Compare next complete-window idle credits, p95 runtime, queue seconds, spill GB, and failures.",
            "VERIFICATION_WINDOW_DAYS": _warehouse_advisor_verification_window(),
            "CONFIDENCE": "Medium - savings are directional until post-change metering confirms lower idle burn.",
            "EXPECTED_VERIFICATION_IMPACT": "Lower idle credits with no increase in failures, queue seconds, spill GB, or p95 runtime.",
            "DO_NOT_EXECUTE_UNTIL": "Do not shorten suspend until workload schedule, auto-resume behavior, and owner expectations are confirmed.",
        })

    overview_view = overview if isinstance(overview, pd.DataFrame) else pd.DataFrame()
    overview_by_wh = {
        str(r.get("WAREHOUSE_NAME") or "").upper(): r
        for _, r in overview_view.iterrows()
        if str(r.get("WAREHOUSE_NAME") or "").strip()
    }
    posture_by_wh = {
        str(r.get("WAREHOUSE_NAME") or "").upper(): r
        for _, r in posture_view.iterrows()
        if str(r.get("WAREHOUSE_NAME") or "").strip()
    }
    spill_threshold = safe_float(WAREHOUSE_ADVISOR_CONFIG.get("pressure_spill_gb"), 10.0)
    queue_threshold = safe_float(WAREHOUSE_ADVISOR_CONFIG.get("pressure_queue_sec"), 5.0)
    p95_threshold = safe_float(WAREHOUSE_ADVISOR_CONFIG.get("pressure_p95_sec"), 120.0)
    downsize_min_monthly = safe_float(WAREHOUSE_ADVISOR_CONFIG.get("downsize_min_monthly_usd"), 100.0)
    downsize_queue_max = safe_float(WAREHOUSE_ADVISOR_CONFIG.get("downsize_max_queue_sec"), 1.0)
    downsize_spill_max = safe_float(WAREHOUSE_ADVISOR_CONFIG.get("downsize_max_spill_gb"), 1.0)
    downsize_p95_max = safe_float(WAREHOUSE_ADVISOR_CONFIG.get("downsize_max_p95_sec"), 30.0)
    downsize_rate = safe_float(WAREHOUSE_ADVISOR_CONFIG.get("downsize_recoverable_rate"), 0.40)
    for _, row in overview_view.iterrows():
        wh = str(row.get("WAREHOUSE_NAME") or "Unknown warehouse")
        posture_row = posture_by_wh.get(wh.upper(), {})
        metered = _row_first_float(row, "METERED_CREDITS", "TOTAL_CREDITS", "CREDITS_USED", "CREDITS_USED_COMPUTE")
        monthly = _warehouse_monthly_run_rate(metered, days, credit_price)
        queue = _row_first_float(row, "AVG_QUEUED_SEC", "AVG_QUEUE_SEC", "QUEUE_SECONDS")
        spill = _row_first_float(row, "TOTAL_REMOTE_SPILL_GB", "REMOTE_SPILL_GB")
        p95 = _row_first_float(row, "P95_ELAPSED_SEC", "P95_SEC", "P95_RUNTIME_SEC")
        total_queries = _row_first_int(row, "TOTAL_QUERIES", "QUERY_COUNT", "QUERIES")
        size = row.get("WAREHOUSE_SIZE") or posture_row.get("WAREHOUSE_SIZE", "")
        if spill >= spill_threshold or queue >= queue_threshold or p95 >= p95_threshold:
            signals = []
            if spill >= spill_threshold:
                signals.append(f"{spill:.1f} GB remote spill")
            if queue >= queue_threshold:
                signals.append(f"{queue:.1f}s avg queue")
            if p95 >= p95_threshold:
                signals.append(f"{p95:.1f}s p95 runtime")
            add({
                "PRIORITY": "High" if spill >= spill_threshold else "Medium",
                "WAREHOUSE_NAME": wh,
                "ADVISOR_TYPE": "Capacity or size review",
                "RECOMMENDATION": "Review query profiles before resizing, clustering, or multi-cluster changes.",
                "WHY": " and ".join(signals) + " indicates pressure that may be warehouse sizing, concurrency, or query shape.",
                "CURRENT_SIGNAL": f"size={size or 'not loaded'}, credits={metered:.2f}, queries={total_queries:,}",
                "CURRENT_SETTING": f"size={size or 'not loaded'}",
                "EST_MONTHLY_SAVINGS_USD": 0.0,
                "EST_MONTHLY_COST_BASIS_USD": monthly,
                "VALUE_AT_RISK_USD": monthly,
                "VERIFIED_MONTHLY_SAVINGS_USD": 0.0,
                "SAVINGS_STATUS": "Pressure evidence",
                "SAVINGS_ASSUMPTION": "No savings claimed for pressure or upsize reviews.",
                "SAVINGS_TYPE": "Value at risk",
                "MONTHLY_RUN_RATE_USD": monthly,
                "REMOTE_SPILL_GB": spill,
                "AVG_QUEUE_SEC": queue,
                "P95_ELAPSED_SEC": p95,
                "PERFORMANCE_RISK": "Upsize can improve reliability but should not be counted as savings until runtime and credits are measured.",
                "ACTION_POSTURE": "Performance review before settings change",
                "SAFE_NEXT_STEP": "Use Warehouse Health query/profile detail first; if a setting change is still justified, execute through Admin.",
                "ADMIN_WORKFLOW": "DBA Control Room > Admin > Warehouse Settings",
                "VERIFY_NEXT": "Recheck spill, queue, p95, total credits, and failure rate after one comparable workload window.",
                "VERIFICATION_WINDOW_DAYS": _warehouse_advisor_verification_window(),
                "CONFIDENCE": "Medium - pressure is telemetry-backed, but root cause still needs query/profile review.",
                "EXPECTED_VERIFICATION_IMPACT": "Pressure should fall without disproportionate credit growth if a setting change is justified.",
                "DO_NOT_EXECUTE_UNTIL": "Do not resize until query/profile evidence separates concurrency pressure from query-shape problems.",
            })
        elif (
            total_queries > 0
            and monthly >= downsize_min_monthly
            and queue <= downsize_queue_max
            and spill < downsize_spill_max
            and p95 <= downsize_p95_max
            and _warehouse_size_rank(size) > 0
        ):
            savings = round(monthly * downsize_rate, 2)
            add({
                "PRIORITY": "Medium" if savings < 500 else "High",
                "WAREHOUSE_NAME": wh,
                "ADVISOR_TYPE": "Downsize savings candidate",
                "RECOMMENDATION": "Test one-size-down only if workload latency tolerance is confirmed.",
                "WHY": (
                    f"No loaded queue or spill pressure, p95 {p95:.1f}s, and about ${monthly:,.0f}/mo run-rate "
                    "make this a conservative savings candidate."
                ),
                "CURRENT_SIGNAL": f"size={size or 'not loaded'}, queue={queue:.1f}s, spill={spill:.1f} GB, p95={p95:.1f}s",
                "CURRENT_SETTING": f"size={size or 'not loaded'}",
                "EST_MONTHLY_SAVINGS_USD": savings,
                "EST_MONTHLY_COST_BASIS_USD": monthly,
                "VERIFIED_MONTHLY_SAVINGS_USD": 0.0,
                "SAVINGS_STATUS": "Needs Verification",
                "SAVINGS_ASSUMPTION": f"{downsize_rate:.0%} one-step-down recoverable rate from monthly run-rate.",
                "SAVINGS_TYPE": "Estimated right-size savings",
                "MONTHLY_RUN_RATE_USD": monthly,
                "REMOTE_SPILL_GB": spill,
                "AVG_QUEUE_SEC": queue,
                "P95_ELAPSED_SEC": p95,
                "PERFORMANCE_RISK": "Downsize can increase runtime or queueing; treat savings as estimated until post-change telemetry is clean.",
                "ACTION_POSTURE": "Guarded one-step test candidate",
                "SAFE_NEXT_STEP": "Confirm owners and workload windows, then use Admin to preview a one-step size test.",
                "ADMIN_WORKFLOW": "DBA Control Room > Admin > Warehouse Settings",
                "VERIFY_NEXT": "Compare p95, queue, spill, failures, and credits against the prior complete period.",
                "VERIFICATION_WINDOW_DAYS": _warehouse_advisor_verification_window(),
                "CONFIDENCE": "Low - savings use a conservative one-step-down assumption and require validation.",
                "EXPECTED_VERIFICATION_IMPACT": "Credits should fall while p95, queue, spill, and failures stay within baseline tolerance.",
                "DO_NOT_EXECUTE_UNTIL": "Do not downsize until workload owner confirms latency tolerance and a rollback window exists.",
            })

    plan_view = plan if isinstance(plan, pd.DataFrame) else pd.DataFrame()
    for _, row in plan_view.iterrows():
        action_type = str(row.get("ACTION_TYPE") or "Setting review")
        if action_type == "Auto-suspend review":
            continue
        wh = str(row.get("WAREHOUSE_NAME") or "Unknown warehouse")
        state = str(row.get("CURRENT_STATE") or "Review")
        overview_row = overview_by_wh.get(wh.upper(), {})
        overview_present = hasattr(overview_row, "get") and bool(str(overview_row.get("WAREHOUSE_NAME") or "").strip())
        monthly = (
            _warehouse_monthly_run_rate(
                _row_first_float(overview_row, "METERED_CREDITS", "TOTAL_CREDITS", "CREDITS_USED", "CREDITS_USED_COMPUTE"),
                days,
                credit_price,
            )
            if overview_present
            else 0.0
        )
        add({
            "PRIORITY": "High" if state == "Blocked" else "Medium",
            "WAREHOUSE_NAME": wh,
            "ADVISOR_TYPE": action_type,
            "RECOMMENDATION": str(row.get("SAFE_SETTING_MOVE") or "Review warehouse setting posture."),
            "WHY": str(row.get("WHY") or "Loaded guardrail telemetry indicates a warehouse setting needs review."),
            "CURRENT_SIGNAL": state,
            "CURRENT_SETTING": str(row.get("CURRENT_SETTING") or "not loaded"),
            "EST_MONTHLY_SAVINGS_USD": 0.0,
            "EST_MONTHLY_COST_BASIS_USD": monthly,
            "VALUE_AT_RISK_USD": monthly,
            "VERIFIED_MONTHLY_SAVINGS_USD": 0.0,
            "SAVINGS_STATUS": "Not Claimed",
            "SAVINGS_ASSUMPTION": "Guardrail finding only; no savings claimed.",
            "SAVINGS_TYPE": "No savings claimed",
            "MONTHLY_RUN_RATE_USD": monthly,
            "REMOTE_SPILL_GB": _row_first_float(overview_row, "TOTAL_REMOTE_SPILL_GB", "REMOTE_SPILL_GB") if overview_present else 0.0,
            "AVG_QUEUE_SEC": _row_first_float(overview_row, "AVG_QUEUED_SEC", "AVG_QUEUE_SEC", "QUEUE_SECONDS") if overview_present else 0.0,
            "P95_ELAPSED_SEC": _row_first_float(overview_row, "P95_ELAPSED_SEC", "P95_SEC", "P95_RUNTIME_SEC") if overview_present else 0.0,
            "PERFORMANCE_RISK": str(row.get("ROLLBACK_CHECK") or "Verify workload telemetry after any change."),
            "ACTION_POSTURE": "Guardrail review",
            "SAFE_NEXT_STEP": "Route the recommendation through the guarded Admin workflow if a setting change is still needed.",
            "ADMIN_WORKFLOW": "DBA Control Room > Admin > Warehouse Settings",
            "VERIFY_NEXT": str(row.get("ROLLBACK_CHECK") or "Compare credits, queue, spill, p95, and failures."),
            "VERIFICATION_WINDOW_DAYS": _warehouse_advisor_verification_window(),
            "CONFIDENCE": "Medium - guardrail finding is loaded, savings are not claimed for this control.",
            "EXPECTED_VERIFICATION_IMPACT": str(row.get("ROLLBACK_CHECK") or "Guardrail telemetry should improve without worse cost or workload reliability."),
            "DO_NOT_EXECUTE_UNTIL": "Do not apply guardrail changes until preview, typed confirmation, and rollback context are ready.",
        })

    if not rows:
        return pd.DataFrame(columns=columns)
    advisor = pd.DataFrame(rows)
    advisor["_PRIORITY_SORT"] = advisor["PRIORITY"].map(_advisor_priority).fillna(9)
    advisor = advisor.sort_values(
        ["_PRIORITY_SORT", "EST_MONTHLY_SAVINGS_USD", "VALUE_AT_RISK_USD", "MONTHLY_RUN_RATE_USD", "WAREHOUSE_NAME"],
        ascending=[True, False, False, False, True],
    ).drop(columns=["_PRIORITY_SORT"])
    return advisor[columns].reset_index(drop=True)


def _render_warehouse_advisor_detail(advisor: pd.DataFrame) -> None:
    if advisor.empty:
        return
    options = advisor.copy().reset_index(drop=True)
    options["DETAIL_LABEL"] = options.apply(
        lambda row: (
            f"{row.get('PRIORITY', 'Review')} | "
            f"{row.get('IMPACT_DISPLAY') or _warehouse_advisor_impact_display(row)} | "
            f"{row.get('WAREHOUSE_NAME', 'Unknown warehouse')} | "
            f"{row.get('ADVISOR_TYPE', 'Recommendation')}"
        ),
        axis=1,
    )
    selected = st.selectbox(
        "Warehouse recommendation",
        options["DETAIL_LABEL"].tolist(),
        key="rec_warehouse_advisor_select",
    )
    row = options[options["DETAIL_LABEL"].eq(selected)].iloc[0]
    posture = str(row.get("ACTION_POSTURE") or "Review")
    posture_card = (
        "Guarded"
        if posture.lower().startswith("guarded")
        else "Performance"
        if "performance" in posture.lower()
        else "Review"
    )
    render_shell_snapshot((
        ("Priority", str(row.get("PRIORITY") or "Review")),
        ("Warehouse", str(row.get("WAREHOUSE_NAME") or "Unknown")),
        ("Posture", posture_card),
        ("Cost Basis / Mo", f"${safe_float(row.get('EST_MONTHLY_COST_BASIS_USD')):,.0f}"),
        ("Savings / Mo", f"${safe_float(row.get('EST_MONTHLY_SAVINGS_USD')):,.0f}"),
        ("Value at Risk / Mo", f"${safe_float(row.get('VALUE_AT_RISK_USD')):,.0f}"),
        ("Remote Spill", f"{safe_float(row.get('REMOTE_SPILL_GB')):,.1f} GB"),
        ("Avg Queue", f"{safe_float(row.get('AVG_QUEUE_SEC')):,.1f}s"),
        ("Status", str(row.get("SAVINGS_STATUS") or "Needs Verification")),
    ))
    st.caption(f"Action posture: {clean_display_text(posture)}")
    st.markdown("**Recommendation**")
    st.caption(clean_display_text(row.get("RECOMMENDATION") or "Review warehouse telemetry."))
    st.markdown("**Why this matters**")
    st.caption(clean_display_text(row.get("WHY") or "Loaded telemetry indicates the warehouse should be reviewed."))
    st.markdown("**Safe next step**")
    st.caption(clean_display_text(row.get("SAFE_NEXT_STEP") or "Review before changing settings."))
    st.markdown("**Execution guardrail**")
    st.caption(clean_display_text(row.get("DO_NOT_EXECUTE_UNTIL") or "Do not execute until workload context and rollback evidence are reviewed."))
    st.markdown("**Validation**")
    st.caption(clean_display_text(row.get("VERIFY_NEXT") or "Compare credits and performance after a complete window."))
    st.markdown("**Expected impact**")
    st.caption(clean_display_text(row.get("EXPECTED_VERIFICATION_IMPACT") or "Post-change telemetry should improve without worse performance or reliability."))
    assumption = str(row.get("SAVINGS_ASSUMPTION") or "").strip()
    if assumption:
        st.caption(
            f"Savings type: {clean_display_text(row.get('SAVINGS_TYPE') or 'No savings claimed')} | "
            f"Basis: {clean_display_text(assumption)} "
            f"Verification window: {safe_int(row.get('VERIFICATION_WINDOW_DAYS'), _warehouse_advisor_verification_window())} day(s)."
        )
    st.caption(f"Execution path: {clean_display_text(row.get('ADMIN_WORKFLOW') or 'DBA Control Room > Admin')}")


def _render_warehouse_controls(session) -> None:
    st.subheader("Warehouse Advisor")
    st.caption("Prioritized warehouse recommendations with estimated savings, pressure signals, and safe execution routing.")
    company = _active_company()
    days = day_window_selectbox("Advisor window", key="rec_wh_control_days", default=7)
    expected = _warehouse_control_scope(company, days)
    current = _warehouse_control_scope_matches(st.session_state.get("rec_warehouse_control_meta"), expected)

    if st.button("Load Warehouse Advisor", key="rec_wh_control_load", type="primary"):
        with render_load_status("Loading warehouse advisor", "Warehouse advisor ready"):
            try:
                _load_warehouse_control_plan(session, company, days)
                current = True
            except Exception as exc:
                st.session_state["rec_warehouse_control_error"] = format_snowflake_error(exc)
                st.session_state["rec_warehouse_control_plan"] = pd.DataFrame()
                st.session_state["rec_warehouse_advisor_recommendations"] = pd.DataFrame()
                current = False

    error = str(st.session_state.get("rec_warehouse_control_error") or "").strip()
    if error:
        st.warning(f"Warehouse advisor unavailable in this role/context: {error}")

    if not current:
        st.info("Load Warehouse Advisor to rank suspend, sizing, timeout, and guardrail recommendations before using Admin controls.")
        return

    summary = st.session_state.get("rec_warehouse_control_summary") or {}
    cost_summary = st.session_state.get("rec_warehouse_cost_control_summary") or {}
    guardrails = st.session_state.get("rec_warehouse_control_guardrails")
    posture = st.session_state.get("rec_warehouse_cost_control_posture")
    plan = st.session_state.get("rec_warehouse_control_plan")
    plan = plan if isinstance(plan, pd.DataFrame) else pd.DataFrame()
    guardrails = guardrails if isinstance(guardrails, pd.DataFrame) else pd.DataFrame()
    posture = posture if isinstance(posture, pd.DataFrame) else pd.DataFrame()
    overview = st.session_state.get("rec_warehouse_control_overview")
    overview = overview if isinstance(overview, pd.DataFrame) else pd.DataFrame()
    advisor = _build_warehouse_advisor_recommendations(
        plan,
        posture,
        overview,
        days=days,
        credit_price=safe_float(st.session_state.get("credit_price", DEFAULTS["credit_price"])),
    )
    st.session_state["rec_warehouse_advisor_recommendations"] = advisor
    advisor_savings = safe_float(advisor["EST_MONTHLY_SAVINGS_USD"].sum()) if not advisor.empty else 0.0
    advisor_cost_basis = safe_float(advisor["EST_MONTHLY_COST_BASIS_USD"].sum()) if not advisor.empty else 0.0
    advisor_value_at_risk = safe_float(advisor["VALUE_AT_RISK_USD"].sum()) if not advisor.empty and "VALUE_AT_RISK_USD" in advisor.columns else 0.0
    high_advisor = int(advisor["PRIORITY"].astype(str).isin(["High", "Critical"]).sum()) if not advisor.empty else 0
    savings_candidates = int((advisor["EST_MONTHLY_SAVINGS_USD"] > 0).sum()) if not advisor.empty else 0
    guarded_changes = (
        int(advisor["ACTION_POSTURE"].astype(str).str.contains("Guarded", case=False, na=False).sum())
        if not advisor.empty and "ACTION_POSTURE" in advisor.columns else 0
    )
    render_shell_snapshot((
        ("Recommendations", f"{len(advisor):,}"),
        ("Savings Candidates", f"{savings_candidates:,}"),
        ("Est. Savings / Mo", f"${advisor_savings:,.0f}"),
        ("Value at Risk / Mo", f"${advisor_value_at_risk:,.0f}"),
        ("Cost Basis / Mo", f"${advisor_cost_basis:,.0f}"),
        ("Guarded Changes", f"{guarded_changes:,}"),
    ))
    if advisor_savings > 0:
        if high_advisor:
            st.caption(f"High-priority recommendations: {high_advisor:,}. Annualized estimated savings: ${advisor_savings * 12:,.0f}.")
        else:
            st.caption(f"Annualized estimated savings: ${advisor_savings * 12:,.0f}.")
    elif advisor_value_at_risk > 0:
        st.caption(f"Value at risk under review: ${advisor_value_at_risk:,.0f}/mo. Savings are shown only when a formula is supportable.")
    else:
        st.caption("Recommendations are review-only for this scope; no savings formula is currently supportable.")
    source = str(st.session_state.get("rec_warehouse_control_source") or "Warehouse advisor")
    defer_source_note(
        metric_confidence_label("estimated"),
        f"Warehouse advisor loaded from {source}; savings are estimated until post-change telemetry confirms the result.",
    )

    if not advisor.empty:
        render_priority_dataframe(
            advisor,
            title="Warehouse recommendations ranked by impact",
            priority_columns=[
                "PRIORITY", "WAREHOUSE_NAME", "ADVISOR_TYPE", "RECOMMENDATION",
                "IMPACT_DISPLAY",
                "EST_MONTHLY_COST_BASIS_USD", "MONTHLY_RUN_RATE_USD",
                "EST_MONTHLY_SAVINGS_USD", "VALUE_AT_RISK_USD", "VERIFIED_MONTHLY_SAVINGS_USD",
                "REMOTE_SPILL_GB", "AVG_QUEUE_SEC", "P95_ELAPSED_SEC",
                "SAVINGS_STATUS", "SAVINGS_TYPE", "SAVINGS_ASSUMPTION",
                "CURRENT_SIGNAL", "CURRENT_SETTING", "PERFORMANCE_RISK",
                "ACTION_POSTURE", "SAFE_NEXT_STEP", "ADMIN_WORKFLOW", "VERIFY_NEXT",
                "EXPECTED_VERIFICATION_IMPACT", "DO_NOT_EXECUTE_UNTIL",
                "VERIFICATION_WINDOW_DAYS", "CONFIDENCE",
            ],
            sort_by=["PRIORITY", "EST_MONTHLY_SAVINGS_USD", "VALUE_AT_RISK_USD"],
            ascending=[True, False, False],
            raw_label="All warehouse advisor rows",
            height=420,
            max_rows=12,
        )
        download_csv(clean_operator_display_text(advisor), "warehouse_advisor_recommendations.csv")
        _render_warehouse_advisor_detail(advisor)
    else:
        st.success("No warehouse recommendations crossed the advisor thresholds for this scope.")

    if not plan.empty:
        render_priority_dataframe(
            plan,
            title="Supporting guardrail findings",
            priority_columns=[
                "PRIORITY", "WAREHOUSE_NAME", "ACTION_TYPE", "CURRENT_STATE",
                "CURRENT_SETTING", "SAFE_SETTING_MOVE", "WHY", "ROLLBACK_CHECK",
            ],
            sort_by=["PRIORITY", "WAREHOUSE_NAME", "ACTION_TYPE"],
            ascending=[True, True, True],
            raw_label="All warehouse setting control rows",
            height=340,
            max_rows=12,
        )
        download_csv(
            clean_operator_display_text(plan.drop(columns=["REVIEW_SQL"], errors="ignore")),
            "warehouse_guardrail_findings.csv",
        )
    elif not guardrails.empty:
        st.success("Loaded warehouse guardrails are ready; no changed setting action is currently required.")
    else:
        st.info("No warehouse overview rows were available for the active scope.")

    if not posture.empty:
        st.subheader("Suspend / Resume Evidence")
        render_shell_snapshot((
            ("Warehouses", f"{int(cost_summary.get('warehouses', len(posture))):,}"),
            ("Blocked", f"{int(cost_summary.get('blocked', 0)):,}"),
            ("Needs Review", f"{int(cost_summary.get('review', 0)):,}"),
            ("OVERWATCH candidates", f"{int(cost_summary.get('overwatch_candidates', 0)):,}"),
        ))
        render_priority_dataframe(
            posture,
            title="Warehouse suspend and resume posture",
            priority_columns=[
                "WAREHOUSE_NAME", "COST_CONTROL_STATE", "IDLE_RISK", "AUTO_SUSPEND_SEC",
                "AUTO_RESUME", "WAREHOUSE_SIZE", "STATE", "METERED_CREDITS",
                "RECOMMENDED_AUTO_SUSPEND_SEC", "RECOMMENDED_ACTION",
            ],
            sort_by=["POSTURE_RANK", "METERED_CREDITS", "WAREHOUSE_NAME"],
            ascending=[True, False, True],
            raw_label="All warehouse suspend/resume rows",
            height=340,
            max_rows=12,
        )
        download_csv(
            clean_operator_display_text(posture.drop(columns=["REVIEW_SQL"], errors="ignore")),
            "warehouse_suspend_resume_evidence.csv",
        )


def _render_automation_health(session):
    st.subheader("Queue Health")
    st.caption("DBA-safe queue lanes for recommendations and action queue items.")
    c_load, c_hint = st.columns([1, 3])
    with c_load:
        if st.button("Load Action Queue", key="automation_queue_load"):
            with render_load_status("Loading action queue", "Action queue ready"):
                try:
                    st.session_state["rec_action_queue"] = load_action_queue(session)
                except Exception as e:
                    st.info(f"The action queue is not available in this environment yet. Ask the DBA on-call to enable it, then retry. ({format_snowflake_error(e)})")
                    st.session_state["rec_action_queue"] = pd.DataFrame()
    with c_hint:
        st.caption("Generate recommendations and/or load the action queue, then use this board to decide what can be safely packaged.")

    recs = st.session_state.get("rec_recommendations", [])
    queue = st.session_state.get("rec_action_queue")
    board = build_automation_readiness_board(recs, queue if isinstance(queue, pd.DataFrame) else None)
    st.session_state["rec_automation_board"] = board

    if board.empty:
        st.info("No queue candidates loaded. Generate recommendations or load the action queue first.")
        playbook = _automation_playbook_frame().rename(columns={
            "AUTOMATION_LANE": "QUEUE_LANE",
        })
        render_priority_dataframe(
            playbook,
            title="Queue lane definitions",
            priority_columns=["QUEUE_LANE", "WHAT_IT_MEANS", "DBA_ACTION"],
            sort_by=["QUEUE_LANE"],
            ascending=True,
            raw_label="All queue lane definitions",
            height=260,
        )
        return

    ready = int((board["AUTOMATION_LANE"] == "Ready").sum())
    telemetry_pending = int((board["AUTOMATION_LANE"] == "Telemetry Pending").sum())
    needs_data = int((board["AUTOMATION_LANE"] == "Needs Data").sum())
    dba_review = int((board["AUTOMATION_LANE"] == "DBA Review").sum())
    auto_close = int((board["AUTOMATION_LANE"] == "Resolved Candidate").sum())
    render_shell_snapshot((
        ("Candidates", f"{len(board):,}"),
        ("Guided Ready", f"{ready:,}"),
        ("Telemetry Pending", f"{telemetry_pending:,}"),
        ("Needs Data", f"{needs_data:,}"),
        ("DBA Review", f"{dba_review:,}"),
        ("Resolved", f"{auto_close:,}"),
    ))

    first = board.iloc[0]
    st.warning(
        f"Queue first move: {first['AUTOMATION_LANE']} for {first['ENTITY']}. "
        f"Blockers: {first['BLOCKERS']}. Next: {first['SAFE_AUTOMATION_STEP']}"
    )
    display_board = board.rename(columns={
        "AUTOMATION_LANE": "QUEUE_LANE",
        "AUTOMATION_MODE": "QUEUE_MODE",
        "APPROVAL_STATE": "REVIEW_STATE",
        "SAFE_AUTOMATION_STEP": "SAFE_NEXT_STEP",
        "APPROVAL_GATE": "REVIEW_GATE",
        "EVIDENCE_PACKAGE": "TELEMETRY_PACKAGE",
        "PROOF_REQUIRED": "TELEMETRY_REQUIRED",
    }).drop(columns=["SAFE_GUIDED_SQL", "STATE_CHANGING_SQL"], errors="ignore")
    render_priority_dataframe(
        display_board,
        title="Queue health board",
        priority_columns=[
            "QUEUE_LANE", "SEVERITY", "CATEGORY", "ENTITY",
            "DECISION", "BLOCKERS", "REVIEW_STATE", "SAFE_NEXT_STEP", "REVIEW_GATE",
            "TELEMETRY_PACKAGE", "VERIFY_NEXT", "EXECUTION_BOUNDARY", "CLOSURE_RULE",
            "TELEMETRY_REQUIRED", "DO_NOT_DO",
        ],
        sort_by=["QUEUE_LANE", "SEVERITY"],
        ascending=[True, True],
        raw_label="All queue health rows",
        height=440,
    )
    download_csv(display_board, "queue_health_board.csv")

    with st.expander("Queue lane definitions", expanded=False):
        playbook = _automation_playbook_frame().rename(columns={
            "AUTOMATION_LANE": "QUEUE_LANE",
        })
        render_priority_dataframe(
            playbook,
            title="Queue playbook",
            priority_columns=["QUEUE_LANE", "WHAT_IT_MEANS", "DBA_ACTION"],
            sort_by=["QUEUE_LANE"],
            ascending=True,
            raw_label="All queue playbook rows",
            height=260,
        )


def _render_queue(session):
    st.subheader("Persistent Action Queue")
    st.caption("Route, status, savings, review path, and telemetry state for every actionable finding.")
    st.info("Action queue persistence is owned by the DBA platform team for this environment.")

    if st.button("Load Action Queue", key="queue_load"):
        with render_load_status("Loading action queue", "Action queue ready"):
            try:
                st.session_state["rec_action_queue"] = load_action_queue(session)
            except Exception as e:
                st.info(f"The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry. ({format_snowflake_error(e)})")
                st.session_state["rec_action_queue"] = pd.DataFrame()

    df_queue = st.session_state.get("rec_action_queue")
    if df_queue is None:
        return
    if df_queue.empty:
        st.info("No persistent actions found yet.")
        return

    open_mask = ~df_queue["STATUS"].isin(["Fixed", "Ignored"])
    high_mask = df_queue["SEVERITY"].isin(["Critical", "High"]) & open_mask
    verification_status = (
        df_queue["VERIFICATION_STATUS"].fillna("").astype(str)
        if "VERIFICATION_STATUS" in df_queue.columns
        else pd.Series([""] * len(df_queue), index=df_queue.index)
    )
    fixed_mask = df_queue["STATUS"] == "Fixed"
    closed_mask = fixed_mask
    due_state = (
        df_queue["DUE_STATE"].fillna("").astype(str)
        if "DUE_STATE" in df_queue.columns
        else pd.Series([""] * len(df_queue), index=df_queue.index)
    )
    evidence_gap = (
        df_queue["EVIDENCE_GAP"].fillna("").astype(str)
        if "EVIDENCE_GAP" in df_queue.columns
        else pd.Series([""] * len(df_queue), index=df_queue.index)
    )
    evidence_gap_mask = ~evidence_gap.isin(["Ready to work", "Telemetry closure", "Ignored with reason"])
    overdue_mask = open_mask & (due_state == "Overdue")
    render_shell_snapshot((
        ("Open", f"{int(open_mask.sum()):,}"),
        ("High / Critical", f"{int(high_mask.sum()):,}"),
        ("Overdue", f"{int(overdue_mask.sum()):,}"),
        ("Control Gaps", f"{int(evidence_gap_mask.sum()):,}"),
        ("Closed", f"{int(closed_mask.sum()):,}"),
        ("Savings Queue", f"${float(df_queue['EST_MONTHLY_SAVINGS'].fillna(0).sum()):,.0f}"),
    ))

    status_filter = st.selectbox(
        "Status filter",
        ["All", "New", "Acknowledged", "In Progress", "Fixed", "Ignored"],
        key="queue_status_filter",
    )
    show_df = df_queue if status_filter == "All" else df_queue[df_queue["STATUS"] == status_filter]
    category_options = ["All"] + sorted(show_df["CATEGORY"].dropna().astype(str).unique().tolist())
    category_filter = st.selectbox("Category filter", category_options, key="queue_category_filter")
    if category_filter != "All":
        show_df = show_df[show_df["CATEGORY"].astype(str) == category_filter]
    render_priority_dataframe(
        show_df,
        title="Action queue items to work first",
        priority_columns=[
            "SEVERITY", "STATUS", "DUE_STATE", "DUE_DATE", "EVIDENCE_GAP",
            "CATEGORY", "ENVIRONMENT", "ENTITY_NAME",
            "FINDING", "OWNER", "TICKET_ID", "APPROVER",
            "EST_MONTHLY_SAVINGS", "MEASURED_DELTA", "NEXT_ACTION", "UPDATED_AT",
        ],
        sort_by=["QUEUE_PRIORITY", "EST_MONTHLY_SAVINGS", "UPDATED_AT"],
        ascending=[True, False, False],
        raw_label="All action queue rows",
        height=360,
    )
    download_csv(show_df, "overwatch_action_queue.csv")

    if show_df.empty:
        return

    selected = st.selectbox("Inspect action", show_df["ACTION_ID"].astype(str).tolist(), key="queue_action_select")
    row = show_df[show_df["ACTION_ID"].astype(str) == selected].iloc[0]
    st.html(
        "<div style='font-size:1rem; line-height:1.45; margin:0 0 .35rem 0;'>"
        f"<strong>{_plain_html(row.get('ENTITY_NAME', ''))}</strong> - {_plain_html(row.get('FINDING', ''))}"
        "</div>"
    )
    st.caption(clean_display_text(row.get("NEXT_ACTION", "Review the route and current telemetry before action.")))
    render_shell_snapshot((
        ("Status", _row_text(row, "STATUS") or "New"),
        ("Severity", _row_text(row, "SEVERITY") or "Medium"),
        ("Due", _row_text(row, "DUE_STATE") or _row_text(row, "DUE_DATE") or "Open"),
        ("Savings", f"${safe_float(row.get('EST_MONTHLY_SAVINGS')):,.0f}"),
    ))
    detail_cols = [
        column for column in [
            "CATEGORY", "ENVIRONMENT", "ENTITY_TYPE", "ENTITY_NAME",
            "FINDING", "NEXT_ACTION", "TICKET_ID", "UPDATED_AT",
        ]
        if column in row.index
    ]
    if detail_cols:
        render_priority_dataframe(
            pd.DataFrame([row[detail_cols].to_dict()]),
            title="Selected action context",
            priority_columns=detail_cols,
            max_rows=1,
            height=120,
        )


def render():
    session = get_session()
    credit_price = st.session_state.get("credit_price", DEFAULTS["credit_price"])

    active_view = render_workflow_selector(
        "Recommendation view",
        "recommendations_active_view",
        RECOMMENDATION_PANES,
        columns=5,
        show_label=True,
    )

    if active_view == "Recommendations":
        st.subheader("Automated Recommendations Feed")
        st.caption("Fast mode reads advisor summaries. Deep mode runs bounded account-history scans only when detail is needed.")

        scan_cols = st.columns([1.1, 1.2, 3.0])
        with scan_cols[0]:
            run_fast_scan = st.button("Generate Fast Recommendations", key="recs_gen", type="primary")
        with scan_cols[1]:
            run_deep_scan = st.button("Run Deep Account History Scan", key="recs_deep_gen")

        if run_fast_scan or run_deep_scan:
            recs = []
            source_notes = []
            company = _active_company()
            include_live = bool(run_deep_scan)
            scan_mode = "deep account-history scan" if include_live else "fast advisor-summary scan"
            source_notes.append(f"Scan mode: {scan_mode}")

            try:
                idle_result = load_shared_recommendation_idle_warehouses(
                    company,
                    days=7,
                    min_idle_credits=1.0,
                    allow_live_fallback=include_live,
                    section="Recommendations",
                )
                df_idle = idle_result.data
                source_notes.append(f"Idle warehouses: {idle_result.source}")
                for _, row in df_idle.iterrows():
                    wh_name = str(row["WAREHOUSE_NAME"])
                    wh_ident = safe_identifier(wh_name)
                    verification_sql = _idle_warehouse_verification_sql(wh_name)
                    monthly_savings = credits_to_dollars(float(row["IDLE_CREDITS"] or 0) / 7 * 30, credit_price)
                    recs.append({
                        "Source": "Idle warehouse detector",
                        "Severity": "High",
                        "Category": "Cost Control",
                        "Entity Type": "Warehouse",
                        "Entity": wh_name,
                        "Owner": "DBA",
                        "Finding": f"{wh_name} idle {int(row['IDLE_HOURS'])}h, wasting {format_credits(row['IDLE_CREDITS'])}",
                        "Action": f"Reduce AUTO_SUSPEND to <= {THRESHOLDS['idle_warehouse_minutes']} minutes",
                        "Idle Hours": int(row["IDLE_HOURS"]),
                        "Estimated Monthly Savings": round(monthly_savings, 2),
                        "Generated SQL Fix": f"ALTER WAREHOUSE {wh_ident} SET AUTO_SUSPEND = {THRESHOLDS['idle_warehouse_minutes'] * 60};",
                        "Proof Query": verification_sql,
                        "Verification Query": verification_sql,
                        "Baseline Value": round(safe_float(row.get("IDLE_CREDITS")), 4),
                        "Current Value": round(safe_float(row.get("IDLE_CREDITS")), 4),
                        "Measured Delta": 0.0,
                        "Company": company,
                    })
            except Exception:
                pass

            try:
                spill_result = load_shared_recommendation_spill_warehouses(
                    session,
                    company,
                    days=7,
                    min_remote_gb=5.0,
                    allow_live_fallback=include_live,
                    section="Recommendations",
                )
                df_spill = spill_result.data
                source_notes.append(f"Remote spill: {spill_result.source}")
                for _, row in df_spill.iterrows():
                    wh_name = str(row["WAREHOUSE_NAME"])
                    verification_sql = _remote_spill_verification_sql(wh_name)
                    recs.append({
                        "Source": "Remote spill detector",
                        "Severity": "Medium",
                        "Category": "Performance",
                        "Entity Type": "Warehouse",
                        "Entity": wh_name,
                        "Owner": "DBA",
                        "Finding": f"{wh_name} ({row['WAREHOUSE_SIZE']}): {row['REMOTE_GB']:.1f} GB remote spill",
                        "Action": "Review query profile; upsize or split workload if spill persists.",
                        "Remote Spill GB": round(safe_float(row.get("REMOTE_GB")), 4),
                        "Estimated Monthly Savings": 0.0,
                        "Generated SQL Fix": f"-- Review memory pressure on {wh_name}; consider ALTER WAREHOUSE {safe_identifier(wh_name)} SET WAREHOUSE_SIZE = '<NEXT_SIZE>';",
                        "Proof Query": verification_sql,
                        "Verification Query": verification_sql,
                        "Current Value": round(safe_float(row.get("REMOTE_GB")), 4),
                        "Company": company,
                    })
            except Exception:
                pass

            try:
                failed_task_result = load_shared_recommendation_failed_tasks(
                    session,
                    company,
                    days=7,
                    min_failures=3,
                    allow_live_fallback=include_live,
                    section="Recommendations",
                )
                df_ftask = failed_task_result.data
                source_notes.append(f"Failed tasks: {failed_task_result.source}")
                for _, row in df_ftask.iterrows():
                    task_name = str(row["TASK_NAME"])
                    verification_sql = _task_failure_verification_sql(task_name)
                    recs.append({
                        "Source": "Task failure detector",
                        "Severity": "High",
                        "Category": "Task & Procedure Reliability",
                        "Entity Type": "Task",
                        "Entity": task_name,
                        "Owner": "Data Engineering",
                        "Finding": f"Task {task_name} failed {int(row['FAILURES'])} times in 7 days",
                        "Action": "Review task error logs in Task Management and fix root cause.",
                        "Failures": int(row["FAILURES"]),
                        "Estimated Monthly Savings": 0.0,
                        "Generated SQL Fix": f"-- Inspect task: {task_name}\n-- EXECUTE TASK <database>.<schema>.{safe_identifier(task_name)};",
                        "Proof Query": verification_sql,
                        "Verification Query": verification_sql,
                        "Baseline Value": 0.0,
                        "Current Value": round(safe_float(row.get("FAILURES")), 4),
                        "Measured Delta": round(safe_float(row.get("FAILURES")), 4),
                        "Company": company,
                    })
            except Exception:
                pass

            try:
                query_failure_result = load_shared_recommendation_query_failures(
                    company,
                    days=7,
                    min_failures=THRESHOLDS["error_rate_high"],
                    allow_live_fallback=include_live,
                    section="Recommendations",
                )
                df_err = query_failure_result.data
                source_notes.append(f"Query failures: {query_failure_result.source}")
                for _, row in df_err.iterrows():
                    wh_name = str(row["WAREHOUSE_NAME"])
                    verification_sql = _query_failure_verification_sql(wh_name)
                    recs.append({
                        "Source": "Query failure detector",
                        "Severity": "Medium",
                        "Category": "Reliability",
                        "Entity Type": "Warehouse",
                        "Entity": wh_name,
                        "Owner": "DBA",
                        "Finding": f"{wh_name}: {int(row['FAILURES'])} failed queries in 7 days",
                        "Action": "Investigate error codes in Query Analysis.",
                        "Failures": int(row["FAILURES"]),
                        "Estimated Monthly Savings": 0.0,
                        "Generated SQL Fix": "-- No safe automatic SQL fix. Review failed query texts and owners.",
                        "Proof Query": verification_sql,
                        "Verification Query": verification_sql,
                        "Current Value": round(safe_float(row.get("FAILURES")), 4),
                        "Company": company,
                    })
            except Exception:
                pass

            if include_live:
                try:
                    storage_rate = get_storage_cost_per_tb()
                    storage_result = load_shared_recommendation_storage_retention(
                        company,
                        min_time_travel_tb=0.25,
                        min_time_travel_ratio=0.25,
                        section="Recommendations",
                    )
                    df_storage = storage_result.data
                    source_notes.append(f"Storage retention: {storage_result.source}")
                    for _, row in df_storage.iterrows():
                        db_name = str(row["DATABASE_NAME"])
                        active_tb = safe_float(row.get("ACTIVE_TB"))
                        time_travel_tb = safe_float(row.get("TIME_TRAVEL_TB"))
                        estimated_storage = time_travel_tb * storage_rate
                        verification_sql = _storage_retention_verification_sql(db_name)
                        recs.append({
                            "Source": "Time travel retention detector",
                            "Severity": "High" if estimated_storage >= 1000 else "Medium",
                            "Category": "Storage Retention",
                            "Entity Type": "Database",
                            "Entity": db_name,
                            "Owner": "DBA",
                            "Finding": (
                                f"{db_name}: {time_travel_tb:.2f} TB time-travel storage "
                                f"vs {active_tb:.2f} TB active"
                            ),
                            "Action": "Confirm recovery, cloning, and compliance requirements before changing retention.",
                            "Estimated Monthly Savings": round(estimated_storage, 2),
                            "Generated SQL Fix": (
                                f"-- Review only for {db_name}.\n"
                                "-- If approved, change DATA_RETENTION_TIME_IN_DAYS at the narrowest safe scope."
                            ),
                            "Proof Query": verification_sql,
                            "Verification Query": verification_sql,
                            "Current Value": round(time_travel_tb, 4),
                            "TIME_TRAVEL_TB": round(time_travel_tb, 4),
                            "ACTIVE_TB": round(active_tb, 4),
                            "Company": company,
                        })
                except Exception:
                    pass
            else:
                source_notes.append("Storage retention: deep scan not run")

            if include_live:
                try:
                    cluster_result = load_shared_recommendation_clustering_cost(
                        company,
                        days=7,
                        credit_price=credit_price,
                        top=10,
                        section="Recommendations",
                    )
                    df_cluster = cluster_result.data
                    source_notes.append(f"Clustering: {cluster_result.source}")
                    for _, row in df_cluster.iterrows():
                        table_name = str(row["TABLE_NAME"])
                        clustering_cost = safe_float(row.get("CLUSTERING_COST_USD"))
                        if clustering_cost < 25:
                            continue
                        reclustered_tb = safe_float(row.get("TB_RECLUSTERED"))
                        verification_sql = _clustering_verification_sql(table_name)
                        recs.append({
                            "Source": "Clustering cost detector",
                            "Severity": "High" if clustering_cost >= 500 else "Medium",
                            "Category": "Clustering",
                            "Entity Type": "Table",
                            "Entity": table_name,
                            "Owner": "DBA",
                            "Finding": (
                                f"{table_name}: ${clustering_cost:,.0f} automatic clustering cost, "
                                f"{reclustered_tb:.2f} TB reclustered"
                            ),
                            "Action": "Review clustering depth, DML churn, pruning benefit, and query demand before changing clustering.",
                            "Estimated Monthly Savings": 0.0,
                            "Generated SQL Fix": (
                                "-- Review only. Do not suspend reclustering until pruning benefit and DML churn are confirmed."
                            ),
                            "Proof Query": verification_sql,
                            "Verification Query": verification_sql,
                            "Current Value": round(clustering_cost, 2),
                            "CLUSTERING_COST_USD": round(clustering_cost, 2),
                            "TB_RECLUSTERED": round(reclustered_tb, 4),
                            "Company": company,
                        })
                except Exception:
                    pass
            else:
                source_notes.append("Clustering: deep scan not run")

            try:
                repeated_result = load_shared_recommendation_repeated_queries(
                    session,
                    company,
                    days=7,
                    min_runs=50,
                    min_total_exec_hours=2.0,
                    allow_live_fallback=include_live,
                    section="Recommendations",
                )
                df_repeated = repeated_result.data
                source_notes.append(f"Repeated query patterns: {repeated_result.source}")
                for _, row in df_repeated.iterrows():
                    query_hash = str(row["QUERY_HASH"])
                    hash_column = str(row.get("HASH_COLUMN") or "QUERY_HASH")
                    runs = int(safe_float(row.get("RUNS")))
                    total_hours = safe_float(row.get("TOTAL_EXEC_HOURS"))
                    scanned_tb = safe_float(row.get("TB_SCANNED"))
                    verification_sql = _repeated_query_verification_sql(query_hash, hash_column)
                    recs.append({
                        "Source": "Repeated query detector",
                        "Severity": "Medium",
                        "Category": "Query Optimization",
                        "Entity Type": "Query Pattern",
                        "Entity": query_hash[:120],
                        "Owner": "Query reviewer / DBA lead",
                        "Finding": (
                            f"{runs:,} executions, {total_hours:.2f} execution hours, "
                            f"{scanned_tb:.2f} TB scanned"
                        ),
                        "Action": "Confirm reuse, freshness, and owner before materialization or rewrite.",
                        "Estimated Monthly Savings": 0.0,
                        "Generated SQL Fix": (
                            "-- No automatic SQL fix. Review sample query, ownership, freshness, and result reuse."
                        ),
                        "Proof Query": verification_sql,
                        "Verification Query": verification_sql,
                        "RUNS": runs,
                        "TOTAL_EXEC_HOURS": round(total_hours, 2),
                        "TB_SCANNED": round(scanned_tb, 2),
                        "Current Value": round(total_hours, 2),
                        "Company": company,
                    })
            except Exception:
                pass

            st.session_state["rec_recommendations"] = recs
            st.session_state["rec_recommendation_sources"] = source_notes

        recs = st.session_state.get("rec_recommendations", [])
        if recs:
            df_recs = _recommendation_frame(recs)
            high = df_recs[df_recs["Severity"].isin(["Critical", "High"])]
            monthly = float(df_recs["Estimated Monthly Savings"].sum())
            telemetry_ready = int(df_recs["Proof Query"].astype(str).str.strip().ne("").sum()) if "Proof Query" in df_recs.columns else 0
            decisive_pct = telemetry_ready / max(len(df_recs), 1) * 100
            render_shell_snapshot((
                ("High / Critical", f"{len(high):,}"),
                ("Open Findings", f"{len(df_recs):,}"),
                ("Est. Monthly Savings", f"${monthly:,.0f}"),
                ("Telemetry Ready", f"{telemetry_ready:,} ({decisive_pct:.0f}%)"),
                ("DBA Routes", f"{len(df_recs):,}"),
            ))
            defer_source_note(
                metric_confidence_label("estimated"),
                "Completed account history and advisor telemetry",
                "Savings are directional until post-period telemetry confirms the action outcome.",
            )
            top_rec = df_recs.iloc[0]
            st.warning(
                f"Work first: {clean_display_text(top_rec['Decision'])} for {clean_display_text(top_rec['Entity'])}. "
                f"{clean_display_text(top_rec['Evidence Packet'])} Next: {clean_display_text(top_rec['Safe Next Action'])}"
            )
            source_notes = st.session_state.get("rec_recommendation_sources", [])
            if source_notes:
                defer_source_note("Recommendation sources: " + "; ".join(source_notes))
            render_priority_dataframe(
                df_recs,
                title="Recommendations to work first",
                priority_columns=[
                    "Severity", "Decision Gate", "Decision", "Category", "Entity",
                    "Telemetry Summary", "Safe Next Action", "Review Gate",
                    "Telemetry Package", "Verify Next", "Execution Boundary", "Closure Rule",
                    "Telemetry Basis", "Do Not Do", "Estimated Monthly Savings", "Escalation Route", "Status",
                ],
                sort_by=["Severity", "Estimated Monthly Savings"],
                ascending=[True, False],
                raw_label="All recommendation rows",
                height=420,
            )
            export_recs = df_recs.drop(
                columns=[
                    "Generated SQL Fix", "Generated SQL", "Proof Query", "Verification Query",
                    "APPROVAL_GATE", "PROOF_QUERY", "VERIFICATION_QUERY", "Generated DDL",
                    "Owner", "Owner Route", "Owner Evidence", "Owner Source",
                ],
                errors="ignore",
            )
            download_csv(clean_operator_display_text(export_recs), "recommendations.csv")

            with st.expander("Action review details"):
                for _, rec in df_recs.iterrows():
                    render_escaped_bold_text(f"{rec['Severity']} - {rec['Decision']} - {rec['Entity']}")
                    st.caption(
                        f"{clean_display_text(rec['Evidence Packet'])} | Review: {clean_display_text(rec.get('Review Gate', rec.get('Approval Gate', '')))} | "
                        f"Boundary: {clean_display_text(rec['Execution Boundary'])} | {clean_display_text(rec['Do Not Do'])}"
                    )
                    st.caption(f"Watch: {clean_display_text(rec['Verify Next'])}")

            if st.button("Save / refresh these findings in Action Queue", key="rec_save_queue", type="primary"):
                try:
                    saved = upsert_actions(session, df_recs.to_dict("records"))
                    st.success(f"Saved {saved} findings to the persistent action queue.")
                    st.session_state.pop("rec_action_queue", None)
                except Exception as e:
                    st.error(f"Action queue save failed: {format_snowflake_error(e)}")
                    st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry.")
        elif st.session_state.get("rec_recommendations") == []:
            st.success("No actionable findings. Account looks healthy.")

    elif active_view == "Warehouse Advisor":
        _render_warehouse_controls(session)

    elif active_view == "Queue Health":
        _render_automation_health(session)

    elif active_view == "Action Queue":
        _render_queue(session)

    elif active_view == "Anomaly Log":
        st.subheader("Anomaly Log")
        st.caption("Flags completed-day warehouse credit spikes against a rolling 7-day baseline.")
        anom_days = day_window_selectbox("Detection window", key="anom_days", default=30)

        if st.button("Detect Anomalies", key="anom_detect"):
            with render_load_status("Detecting credit anomalies", "Anomaly scan ready"):
                try:
                    anomaly_result = load_shared_warehouse_credit_anomalies(
                        _active_company(),
                        days=anom_days,
                        zscore_threshold=1.5,
                        allow_live_fallback=True,
                        force=True,
                        section="Recommendations",
                    )
                    st.session_state["rec_anomalies"] = anomaly_result.data
                    st.session_state["rec_anomalies_source"] = anomaly_result.source
                    st.session_state["rec_anomalies_message"] = anomaly_result.message
                except Exception as e:
                    st.warning(f"Recommendation scan unavailable in this role/context: {format_snowflake_error(e)}")

        df_an = st.session_state.get("rec_anomalies")
        if df_an is not None:
            source = str(st.session_state.get("rec_anomalies_source") or "Warehouse credit anomalies")
            defer_source_note(
                metric_confidence_label("estimated"),
                f"Anomaly source: {source}. Completed days only; current partial-day spend is excluded.",
            )
            if not df_an.empty:
                spikes = df_an[df_an.get("ANOMALY_FLAG", pd.Series(dtype=str)).astype(str) == "SPIKE"] if "ANOMALY_FLAG" in df_an.columns else df_an
                st.warning(f"{len(spikes)} spike events detected.")
                render_priority_dataframe(
                    df_an,
                    title="Credit anomalies to investigate first",
                    priority_columns=[
                        "WAREHOUSE_NAME", "DAY", "DAILY_CREDITS",
                        "ROLLING_AVG", "ZSCORE", "ANOMALY_FLAG",
                    ],
                    sort_by=["ZSCORE", "DAILY_CREDITS"],
                    ascending=[False, False],
                    raw_label="All anomaly rows",
                )
                download_csv(df_an, "anomaly_log.csv")
            else:
                st.success("No anomalies detected in the analysis window.")
