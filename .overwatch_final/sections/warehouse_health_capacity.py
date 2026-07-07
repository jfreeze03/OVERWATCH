# sections/warehouse_health_capacity.py - Warehouse Health capacity SQL and brief helpers.
from __future__ import annotations

import pandas as pd
import streamlit as st

from sections.base import lazy_util as _lazy_util
from sections.shell_helpers import render_escaped_bold_text, render_shell_snapshot
from sections.warehouse_health_actions import (
    _annotate_warehouse_admin_readiness,
    _warehouse_capacity_priority_view,
)
from sections.warehouse_health_overview_panels import _queue_warehouse_health_view
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_source_note


filter_existing_columns = _lazy_util("filter_existing_columns")
format_credits = _lazy_util("format_credits")
get_global_filter_clause = _lazy_util("get_global_filter_clause")
get_wh_filter_clause = _lazy_util("get_wh_filter_clause")


def _warehouse_sql_exprs(session) -> dict[str, str]:
    """Resolve optional ACCOUNT_USAGE columns only when a live query is requested."""
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "WAREHOUSE_SIZE",
            "QUEUED_OVERLOAD_TIME",
            "BYTES_SPILLED_TO_LOCAL_STORAGE",
            "BYTES_SPILLED_TO_REMOTE_STORAGE",
            "PERCENTAGE_SCANNED_FROM_CACHE",
            "BYTES_SCANNED",
        ],
    ))
    wm_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
        ["CREDITS_USED_COMPUTE", "CREDITS_USED_CLOUD_SERVICES"],
    ))
    return {
        "wh_size_expr": "MAX(q.warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR",
        "plain_wh_size_expr": "MAX(warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR",
        "latest_size_expr": "q.warehouse_size" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR",
        "queue_avg_expr": "AVG(q.queued_overload_time)/1000" if "QUEUED_OVERLOAD_TIME" in qh_cols else "0",
        "queue_sum_expr": "SUM(q.queued_overload_time)" if "QUEUED_OVERLOAD_TIME" in qh_cols else "0",
        "remote_spill_sum_expr": (
            "SUM(q.bytes_spilled_to_remote_storage)"
            if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
            else "0"
        ),
        "local_spill_expr": (
            "SUM(bytes_spilled_to_local_storage)"
            if "BYTES_SPILLED_TO_LOCAL_STORAGE" in qh_cols
            else "0"
        ),
        "local_spill_row_expr": (
            "bytes_spilled_to_local_storage"
            if "BYTES_SPILLED_TO_LOCAL_STORAGE" in qh_cols
            else "0"
        ),
        "remote_spill_expr": (
            "SUM(bytes_spilled_to_remote_storage)"
            if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
            else "0"
        ),
        "remote_spill_row_expr": (
            "bytes_spilled_to_remote_storage"
            if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
            else "0"
        ),
        "cache_expr": "AVG(q.percentage_scanned_from_cache)" if "PERCENTAGE_SCANNED_FROM_CACHE" in qh_cols else "0",
        "bytes_scanned_expr": "SUM(q.bytes_scanned)" if "BYTES_SCANNED" in qh_cols else "0",
        "compute_meter_expr": "m.credits_used_compute" if "CREDITS_USED_COMPUTE" in wm_cols else "m.credits_used",
        "cloud_meter_expr": "m.credits_used_cloud_services" if "CREDITS_USED_CLOUD_SERVICES" in wm_cols else "0::FLOAT",
    }


def _render_warehouse_watch_floor(score: int, exceptions: pd.DataFrame, summary_row: dict) -> None:
    priority = _warehouse_capacity_priority_view(exceptions).head(3)
    high_risk = 0
    if exceptions is not None and not exceptions.empty and "SEVERITY" in exceptions.columns:
        high_risk = int(exceptions["SEVERITY"].isin(["Critical", "High"]).sum())

    render_shell_snapshot((
        ("High-Risk Warehouses", f"{high_risk:,}"),
        ("Remote Spill", f"{safe_float(summary_row.get('REMOTE_SPILL_GB')):,.1f} GB"),
        ("Queued Queries", f"{safe_int(summary_row.get('QUEUED_QUERIES')):,}"),
    ))
    if priority.empty:
        st.success("No urgent warehouse capacity exceptions crossed the selected thresholds.")
    else:
        first = priority.iloc[0]
        st.warning(
            f"First move: {first.get('SIGNAL', 'Warehouse pressure')} on "
            f"{first.get('WAREHOUSE_NAME', 'unknown warehouse')} -> {first.get('NEXT_ACTION', 'Review warehouse pressure.')}"
        )

    st.markdown("**Warehouse Watch Floor**")
    if priority.empty:
        defer_source_note("Use Overview & Scaling for periodic checks, or Efficiency after a cost spike.")
        return

    cols = st.columns(len(priority))
    for idx, (_, item) in enumerate(priority.iterrows()):
        workflow = str(item.get("NEXT_WORKFLOW") or "Overview & Scaling")
        with cols[idx]:
            render_escaped_bold_text(f"{item.get('SEVERITY', 'Medium')}: {item.get('SIGNAL', '')}")
            st.caption(
                f"{item.get('WAREHOUSE_NAME', 'unknown warehouse')} | "
                f"Queued {safe_int(item.get('QUEUED_QUERIES')):,} | "
                f"Spill {safe_int(item.get('SPILL_QUERIES')):,} | "
                f"{format_credits(safe_float(item.get('METERED_CREDITS')))}"
            )
            next_action = str(item.get("NEXT_ACTION", "") or "")
            if st.button(
                f"Open {workflow}",
                key=f"wh_watch_floor_{idx}_{workflow}",
                help=next_action or None,
                width="stretch",
            ):
                warehouse = str(item.get("WAREHOUSE_NAME") or "")
                if warehouse:
                    st.session_state["global_warehouse"] = warehouse
                    st.session_state["wh_filter"] = warehouse
                    st.session_state["lm_wh"] = warehouse
                    for stale_key in ["wh_df_wh", "wh_efficiency", "wh_df_sp", "wh_df_hm"]:
                        st.session_state.pop(stale_key, None)
                _queue_warehouse_health_view(workflow)


def _build_warehouse_capacity_markdown(
    company: str,
    days: int,
    score: int,
    summary_row: dict,
    exceptions: pd.DataFrame,
) -> str:
    exceptions_view = _annotate_warehouse_admin_readiness(exceptions)
    lines = [
        f"# OVERWATCH Warehouse Capacity Brief - {company}",
        "",
        f"- Lookback: {days} days",
        f"- Warehouses active: {safe_int(summary_row.get('WAREHOUSES_ACTIVE')):,}",
        f"- Queries: {safe_int(summary_row.get('TOTAL_QUERIES')):,}",
        f"- Queued queries: {safe_int(summary_row.get('QUEUED_QUERIES')):,}",
        f"- Spill queries: {safe_int(summary_row.get('SPILL_QUERIES')):,}",
        f"- Credit movement: {safe_float(summary_row.get('CREDIT_SPIKE_PCT')):,.1f}%",
        "",
        "## DBA Narrative",
        (
            "Use this brief to decide whether warehouse pressure is capacity, memory, workload shape, "
            "or cost drift. It is intended to support DBA action and executive reporting without forcing "
            "stakeholders through raw warehouse telemetry."
        ),
        "",
        "## Top Warehouse Exceptions",
    ]
    if exceptions is None or exceptions.empty:
        lines.append("- No warehouse capacity exceptions found for the selected scope.")
    else:
        for _, row in exceptions_view.head(10).iterrows():
            lines.append(
                "- "
                f"{row.get('SEVERITY', 'Watch')} | {row.get('SIGNAL', 'Unknown')} | "
                f"{row.get('WAREHOUSE_NAME', '')} | "
                f"{safe_float(row.get('METERED_CREDITS')):,.2f} credits | "
                f"{row.get('SETTING_CHANGE_CANDIDATE', 'Review warehouse settings')}"
            )
    lines.extend([
        "",
        "## Settings Change Status",
        (
            "- Warehouse capacity findings are not direct change orders. Route setting changes through "
            "the guarded warehouse settings workflow so current values, review status, rollback SQL, "
            "and post-change telemetry are captured."
        ),
        "",
        "## Telemetry Limits",
        "- ACCOUNT_USAGE can lag; Live Monitor should be used for current in-flight warehouse pressure.",
        "- Per-warehouse pressure is inferred from query history plus metering history, not Snowsight implementation details.",
        "- Company scope follows configured warehouse/database/user naming rules.",
    ])
    return "\n".join(lines)


def _build_warehouse_capacity_sql(session, days: int) -> tuple[str, str]:
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "WAREHOUSE_SIZE",
            "QUEUED_OVERLOAD_TIME",
            "QUEUED_PROVISIONING_TIME",
            "QUEUED_REPAIR_TIME",
            "BYTES_SPILLED_TO_LOCAL_STORAGE",
            "BYTES_SPILLED_TO_REMOTE_STORAGE",
        ],
    ))
    wm_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
        ["CREDITS_USED_COMPUTE", "CREDITS_USED"],
    ))
    warehouse_size_expr = "MAX(q.warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR"
    queue_ms_expr = " + ".join([
        "COALESCE(q.queued_overload_time, 0)" if "QUEUED_OVERLOAD_TIME" in qh_cols else "0",
        "COALESCE(q.queued_provisioning_time, 0)" if "QUEUED_PROVISIONING_TIME" in qh_cols else "0",
        "COALESCE(q.queued_repair_time, 0)" if "QUEUED_REPAIR_TIME" in qh_cols else "0",
    ])
    local_spill_expr = (
        "COALESCE(q.bytes_spilled_to_local_storage, 0)"
        if "BYTES_SPILLED_TO_LOCAL_STORAGE" in qh_cols
        else "0"
    )
    remote_spill_expr = (
        "COALESCE(q.bytes_spilled_to_remote_storage, 0)"
        if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
        else "0"
    )
    spill_bytes_expr = f"{local_spill_expr} + {remote_spill_expr}"
    meter_expr = (
        "COALESCE(m.credits_used_compute, m.credits_used)"
        if {"CREDITS_USED_COMPUTE", "CREDITS_USED"}.issubset(wm_cols)
        else "m.credits_used"
    )
    filters_q = get_global_filter_clause(
        date_col="q.start_time",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
    )
    filters_m = get_wh_filter_clause("m.warehouse_name")
    summary_sql = f"""
        WITH query_rollup AS (
            SELECT
                q.warehouse_name,
                COUNT(*) AS total_queries,
                SUM(IFF(({queue_ms_expr}) > 0, 1, 0)) AS queued_queries,
                SUM(IFF(({spill_bytes_expr}) > 0, 1, 0)) AS spill_queries,
                SUM(IFF(q.total_elapsed_time >= 30000, 1, 0)) AS high_latency_queries,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY q.total_elapsed_time / 1000.0) AS p95_elapsed_sec,
                SUM({remote_spill_expr}) / POWER(1024, 3) AS remote_spill_gb
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {filters_q}
            GROUP BY q.warehouse_name
        ),
        metering AS (
            SELECT
                m.warehouse_name,
                SUM(IFF(m.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP()),
                        {meter_expr}, 0)) AS current_credits,
                SUM(IFF(m.start_time >= DATEADD('day', -{int(days) * 2}, CURRENT_TIMESTAMP())
                         AND m.start_time < DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP()),
                        {meter_expr}, 0)) AS prior_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY m
            WHERE m.start_time >= DATEADD('day', -{int(days) * 2}, CURRENT_TIMESTAMP())
              {filters_m}
            GROUP BY m.warehouse_name
        ),
        combined AS (
            SELECT
                COALESCE(q.warehouse_name, m.warehouse_name) AS warehouse_name,
                COALESCE(q.total_queries, 0) AS total_queries,
                COALESCE(q.queued_queries, 0) AS queued_queries,
                COALESCE(q.spill_queries, 0) AS spill_queries,
                COALESCE(q.high_latency_queries, 0) AS high_latency_queries,
                COALESCE(q.p95_elapsed_sec, 0) AS p95_elapsed_sec,
                COALESCE(q.remote_spill_gb, 0) AS remote_spill_gb,
                COALESCE(m.current_credits, 0) AS current_credits,
                COALESCE(m.prior_credits, 0) AS prior_credits,
                (COALESCE(m.current_credits, 0) - COALESCE(m.prior_credits, 0))
                    / NULLIF(COALESCE(m.prior_credits, 0), 0) * 100 AS credit_spike_pct
            FROM query_rollup q
            FULL OUTER JOIN metering m ON q.warehouse_name = m.warehouse_name
        )
        SELECT
            COUNT(DISTINCT warehouse_name) AS warehouses_active,
            SUM(total_queries) AS total_queries,
            SUM(queued_queries) AS queued_queries,
            SUM(spill_queries) AS spill_queries,
            SUM(high_latency_queries) AS high_latency_queries,
            SUM(current_credits) AS metered_credits,
            SUM(prior_credits) AS prior_credits,
            (SUM(current_credits) - SUM(prior_credits)) / NULLIF(SUM(prior_credits), 0) * 100 AS credit_spike_pct,
            MAX(p95_elapsed_sec) AS worst_p95_elapsed_sec,
            SUM(remote_spill_gb) AS remote_spill_gb
        FROM combined
    """
    exceptions_sql = f"""
        WITH query_rollup AS (
            SELECT
                q.warehouse_name,
                {warehouse_size_expr} AS warehouse_size,
                COUNT(*) AS total_queries,
                SUM(IFF(({queue_ms_expr}) > 0, 1, 0)) AS queued_queries,
                SUM(IFF(({spill_bytes_expr}) > 0, 1, 0)) AS spill_queries,
                SUM(IFF(q.total_elapsed_time >= 30000, 1, 0)) AS high_latency_queries,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY q.total_elapsed_time / 1000.0) AS p95_elapsed_sec,
                SUM({remote_spill_expr}) / POWER(1024, 3) AS remote_spill_gb
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {filters_q}
            GROUP BY q.warehouse_name
        ),
        metering AS (
            SELECT
                m.warehouse_name,
                SUM(IFF(m.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP()),
                        {meter_expr}, 0)) AS current_credits,
                SUM(IFF(m.start_time >= DATEADD('day', -{int(days) * 2}, CURRENT_TIMESTAMP())
                         AND m.start_time < DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP()),
                        {meter_expr}, 0)) AS prior_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY m
            WHERE m.start_time >= DATEADD('day', -{int(days) * 2}, CURRENT_TIMESTAMP())
              {filters_m}
            GROUP BY m.warehouse_name
        ),
        combined AS (
            SELECT
                COALESCE(q.warehouse_name, m.warehouse_name) AS warehouse_name,
                q.warehouse_size,
                COALESCE(q.total_queries, 0) AS total_queries,
                COALESCE(q.queued_queries, 0) AS queued_queries,
                COALESCE(q.spill_queries, 0) AS spill_queries,
                COALESCE(q.high_latency_queries, 0) AS high_latency_queries,
                COALESCE(q.p95_elapsed_sec, 0) AS p95_elapsed_sec,
                COALESCE(q.remote_spill_gb, 0) AS remote_spill_gb,
                COALESCE(m.current_credits, 0) AS current_credits,
                COALESCE(m.prior_credits, 0) AS prior_credits,
                (COALESCE(m.current_credits, 0) - COALESCE(m.prior_credits, 0))
                    / NULLIF(COALESCE(m.prior_credits, 0), 0) * 100 AS credit_spike_pct
            FROM query_rollup q
            FULL OUTER JOIN metering m ON q.warehouse_name = m.warehouse_name
        )
        SELECT
            CASE
                WHEN queued_queries >= 20 OR remote_spill_gb >= 20 THEN 'Critical'
                WHEN credit_spike_pct >= 50 OR spill_queries >= 10 OR high_latency_queries >= 25 THEN 'High'
                ELSE 'Medium'
            END AS severity,
            CASE
                WHEN queued_queries >= 20 THEN 'Queue Pressure'
                WHEN remote_spill_gb >= 1 THEN 'Memory Spill'
                WHEN credit_spike_pct >= 25 THEN 'Credit Spike'
                ELSE 'Latency Pressure'
            END AS signal,
            warehouse_name,
            warehouse_size,
            total_queries,
            queued_queries,
            spill_queries,
            high_latency_queries,
            ROUND(p95_elapsed_sec, 2) AS p95_elapsed_sec,
            ROUND(remote_spill_gb, 2) AS remote_spill_gb,
            ROUND(current_credits, 4) AS metered_credits,
            ROUND(prior_credits, 4) AS prior_credits,
            ROUND(COALESCE(credit_spike_pct, 0), 1) AS credit_spike_pct,
            ROUND(100
                - LEAST(queued_queries * 100.0 / NULLIF(total_queries, 0) * 2.0, 28)
                - LEAST(spill_queries * 100.0 / NULLIF(total_queries, 0) * 1.8, 24)
                - LEAST(high_latency_queries * 100.0 / NULLIF(total_queries, 0) * 1.1, 18)
                - LEAST(GREATEST(COALESCE(credit_spike_pct, 0), 0) / 4, 20), 1) AS capacity_score
        FROM combined
        WHERE queued_queries > 0
           OR spill_queries > 0
           OR high_latency_queries > 0
           OR credit_spike_pct >= 25
        ORDER BY
            CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 ELSE 3 END,
            capacity_score ASC,
            metered_credits DESC
        LIMIT 100
    """
    return summary_sql, exceptions_sql
