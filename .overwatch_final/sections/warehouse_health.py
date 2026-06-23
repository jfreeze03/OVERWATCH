# sections/warehouse_health.py - Warehouse stats, scaling events, idle detection, spill, heatmap
from __future__ import annotations

import streamlit as st
from sections.base import lazy_pandas, lazy_util as _lazy_util
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_section_note, defer_source_note
from config import DEFAULT_COMPANY, DEFAULTS, DEFAULT_ENVIRONMENT
from sections.shell_helpers import (
    consume_section_autoload_request,
    render_data_freshness,
    render_escaped_bold_text,
    render_shell_snapshot,
    with_loaded_at,
)

from sections.warehouse_health_actions import (
    _annotate_warehouse_admin_readiness,
    _build_warehouse_cost_control_posture,
    _build_warehouse_guardrail_coverage,
    _route_label,
    _warehouse_approval_for,
    _warehouse_capacity_priority_view,
    _warehouse_capacity_review_sql,
    _warehouse_intervention_matrix,
    _warehouse_owner_context,
    _warehouse_setting_action_plan,
    _warehouse_setting_audit_readiness_for_row,
    _warehouse_setting_candidate_for,
    _warehouse_setting_control_board,
    _warehouse_setting_detail_options,
    _warehouse_setting_review_insert_sql,
    _warehouse_setting_route,
)
from sections.warehouse_health_contracts import (
    WAREHOUSE_HEALTH_BRIEF_FIRST_VERSION,
    WAREHOUSE_HEALTH_BRIEF_WORKFLOWS,
    WAREHOUSE_HEALTH_DETAILS,
    WAREHOUSE_HEALTH_FAST_ENTRY_VERSION,
    WAREHOUSE_HEALTH_VIEWS,
    WAREHOUSE_OPERABILITY_FACT_TABLE,
    WAREHOUSE_SCOPE_FILTER_KEYS,
    WAREHOUSE_SETTING_REVIEW_TABLE,
)
from sections.warehouse_health_dataframes import (
    _frame_row_count,
    _scope_value,
    _source_confidence,
    _source_next_action,
    _warehouse_column_sum,
    _warehouse_frame_has_rows,
    _warehouse_frame_sum,
    _warehouse_looks_like_frame,
    _warehouse_meta_matches,
    _warehouse_operator_next_moves,
    _warehouse_overview_exceptions,
    _warehouse_period_movement,
    _warehouse_scope_meta,
    _warehouse_state_count,
    _warehouse_source_health_rows,
)
from sections.warehouse_health_helpers import (
    _warehouse_capacity_action_for,
    _warehouse_capacity_score,
    _warehouse_capacity_workflow_for,
)
from sections.warehouse_health_overview_panels import (
    _apply_queued_warehouse_health_view,
    _apply_warehouse_brief_first_default,
    _queue_warehouse_health_view,
    _render_warehouse_action_brief,
    _render_warehouse_brief_launchpad,
    _render_warehouse_operating_snapshot,
    _warehouse_action_brief,
    _warehouse_brief_workflow_rows,
    _warehouse_operating_snapshot,
    _warehouse_support_panels_have_state,
)
from sections.warehouse_health_setting_panels import (
    _render_warehouse_cost_control_posture,
    _render_warehouse_setting_action_detail,
    _save_warehouse_setting_review_snapshot,
)
from sections.warehouse_health_sql import (
    _admin_audit_fqn,
    _overwatch_dedicated_warehouse_setup_sql,
    _warehouse_action_queue_closure_sql,
    _warehouse_capacity_verification_sql,
    _warehouse_cost_control_review_sql,
    _warehouse_operability_fact_sql,
    _warehouse_setting_execution_audit_sql,
    _warehouse_setting_review_history_sql,
    _warehouse_setting_review_sql,
    _warehouse_sql_identifier,
    build_warehouse_operability_fact_ddl,
    build_warehouse_operability_fact_migration_sql,
    build_warehouse_setting_review_ddl,
    build_warehouse_setting_review_migration_sql,
    warehouse_operability_fact_fqn,
    warehouse_setting_review_fqn,
)


pd = lazy_pandas()

get_session_for_action = _lazy_util("get_session_for_action")
format_credits = _lazy_util("format_credits")
download_csv = _lazy_util("download_csv")
render_drillable_bar_chart = _lazy_util("render_drillable_bar_chart")
get_wh_filter_clause = _lazy_util("get_wh_filter_clause")
get_global_filter_clause = _lazy_util("get_global_filter_clause")
metric_confidence_label = _lazy_util("metric_confidence_label")
freshness_note = _lazy_util("freshness_note")
make_action_id = _lazy_util("make_action_id")
upsert_actions = _lazy_util("upsert_actions")
run_query = _lazy_util("run_query")
format_snowflake_error = _lazy_util("format_snowflake_error")
filter_existing_columns = _lazy_util("filter_existing_columns")
render_optimization_advisor = _lazy_util("render_optimization_advisor")
load_shared_warehouse_overview = _lazy_util("load_shared_warehouse_overview")
load_shared_warehouse_scaling_events = _lazy_util("load_shared_warehouse_scaling_events")
load_shared_warehouse_efficiency = _lazy_util("load_shared_warehouse_efficiency")
load_shared_warehouse_spill = _lazy_util("load_shared_warehouse_spill")
load_shared_warehouse_heatmap = _lazy_util("load_shared_warehouse_heatmap")
load_warehouse_inventory = _lazy_util("load_warehouse_inventory")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
render_load_status = _lazy_util("render_load_status")
render_workflow_selector = _lazy_util("render_workflow_selector")
day_window_selectbox = _lazy_util("day_window_selectbox")


def get_active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def get_active_environment() -> str:
    return str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)


def render_operator_briefing(items: list[tuple[str, str]], *, columns: int = 4) -> None:
    for label, detail in items:
        defer_section_note(f"{label}: {detail}")


def _warehouse_action_session(action: str):
    return get_session_for_action(
        action,
        surface="Warehouse Health",
        offline_note="Warehouse shell, source summaries, and cached telemetry remain visible without a live connection.",
    )


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
            "leadership through raw warehouse telemetry."
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


def _queue_capacity_findings(session, exceptions: pd.DataFrame) -> int:
    if exceptions is None or exceptions.empty:
        return 0
    company = get_active_company()
    environment = get_active_environment()
    exceptions = _annotate_warehouse_admin_readiness(exceptions)
    actions = []
    for _, row in exceptions.head(50).iterrows():
        wh = str(row.get("WAREHOUSE_NAME", ""))
        signal = str(row.get("SIGNAL", "Warehouse Pressure"))
        action_text, _ = _warehouse_capacity_action_for(signal)
        verification_sql = _warehouse_capacity_verification_sql(
            wh,
            days=7,
            environment=environment,
            company=company,
        )
        finding = (
            f"{signal} on {wh}: "
            f"queued={safe_int(row.get('QUEUED_QUERIES')):,}, spill={safe_int(row.get('SPILL_QUERIES')):,}, "
            f"credits={safe_float(row.get('METERED_CREDITS')):,.2f}; "
            f"{row.get('PRESSURE_EVIDENCE', '')}."
        )
        actions.append({
            "Action ID": make_action_id("Warehouse Capacity", wh, finding),
            "Source": "Warehouse Health - Capacity Brief",
            "Category": "Warehouse Capacity",
            "Severity": row.get("SEVERITY", "High"),
            "Entity Type": "Warehouse",
            "Entity": wh,
            "Route": _route_label(row.get("OWNER", "Platform DBA")),
            "Route Email": row.get("OWNER_EMAIL", ""),
            "Oncall Primary": row.get("ONCALL_PRIMARY", ""),
            "Oncall Secondary": row.get("ONCALL_SECONDARY", ""),
            "Escalation": _route_label(row.get("APPROVAL_GROUP", row.get("APPROVER", "Warehouse Route / DBA Lead"))),
            "Escalation Target": row.get("ESCALATION_TARGET", "DBA Lead"),
            "Route Basis": _route_label(row.get("OWNER_SOURCE", "")),
            "Route Detail": _route_label(row.get("OWNER_EVIDENCE", "")),
            "Finding": finding,
            "Action": (
                f"{action_text} {row.get('SAFE_CHANGE_PATH', '')} "
                f"Review from {_route_label(row.get('APPROVER', 'Warehouse DBA Lead'))} is required. "
                "Actual warehouse changes must be generated from the Warehouse Settings Manager."
            ),
            "Estimated Monthly Savings": 0,
            "Generated SQL Fix": _warehouse_capacity_review_sql(row),
            "Telemetry Query": verification_sql,
            "Reviewer": _route_label(row.get("APPROVER", "Warehouse Route / DBA Lead")),
            "Telemetry Status": "Requested",
            "Status Note": (
                f"{row.get('CHANGE_RISK', '')} "
                f"Escalation: {row.get('ESCALATION_TARGET', 'DBA Lead')}. "
                f"Rollback required: {row.get('ROLLBACK_REQUIRED', 'Yes')}; "
                f"impact telemetry required: {row.get('IMPACT_TELEMETRY_REQUIRED', 'No')}."
            ),
            "Recovery Status": (
                f"Baseline: {row.get('PRESSURE_EVIDENCE', '')}. "
                f"Closure uses post-change telemetry: {row.get('POST_CHANGE_VERIFICATION', '')}"
            ),
            "Recovery Audit State": "Warehouse Change Telemetry Pending",
            "Baseline Value": safe_float(row.get("CAPACITY_SCORE")),
            "Current Value": safe_float(row.get("CAPACITY_SCORE")),
            "Measured Delta": 0,
            "Company": company,
            "Environment": environment,
        })
    return upsert_actions(session, actions)


def _render_capacity_brief(company: str, environment: str) -> None:
    with st.expander("Capacity Brief", expanded=bool(st.session_state.get("exceptions_only_mode"))):
        days = day_window_selectbox("Capacity lookback", key="wh_capacity_days", default=7)
        if st.button("Load Capacity Brief", key="wh_capacity_load"):
            with render_load_status("Building warehouse capacity brief", "Warehouse capacity brief ready"):
                try:
                    session = _warehouse_action_session("load the warehouse capacity brief")
                    if session is None:
                        return
                    summary_sql, exceptions_sql = _build_warehouse_capacity_sql(session, days)
                    summary = run_query(
                        summary_sql,
                        ttl_key=f"wh_capacity_summary_{company}_{environment}_{days}",
                        tier="historical",
                        section="Warehouse Health",
                    )
                    exceptions = run_query(
                        exceptions_sql,
                        ttl_key=f"wh_capacity_exceptions_{company}_{environment}_{days}",
                        tier="historical",
                        section="Warehouse Health",
                    )
                    st.session_state["wh_capacity_summary"] = summary
                    st.session_state["wh_capacity_exceptions"] = exceptions
                    st.session_state["wh_capacity_sql"] = {
                        "summary": summary_sql,
                        "exceptions": exceptions_sql,
                    }
                    st.session_state["wh_capacity_meta"] = _warehouse_scope_meta(company, environment, days)
                    try:
                        operability_sql = _warehouse_operability_fact_sql(days, company, environment)
                        st.session_state["wh_operability_fact_sql"] = operability_sql
                        st.session_state["wh_operability_fact"] = run_query(
                            operability_sql,
                            ttl_key=f"wh_operability_fact_{company}_{environment}_{days}",
                            tier="standard",
                            section="Warehouse Health",
                        )
                        st.session_state.pop("wh_operability_fact_error", None)
                    except Exception as fact_exc:
                        st.session_state["wh_operability_fact"] = pd.DataFrame()
                        st.session_state["wh_operability_fact_error"] = format_snowflake_error(fact_exc)
                except Exception as e:
                    st.warning(f"Capacity brief unavailable in this role/context: {format_snowflake_error(e)}")

        summary = st.session_state.get("wh_capacity_summary")
        exceptions = st.session_state.get("wh_capacity_exceptions")
        meta = st.session_state.get("wh_capacity_meta", {})
        if (
            summary is None
            or summary.empty
            or meta.get("company") != company
            or meta.get("environment") != environment
            or meta.get("days") != int(days)
        ):
            return
        exceptions = _warehouse_capacity_priority_view(exceptions)
        row = summary.iloc[0].to_dict()
        score = _warehouse_capacity_score(
            queued_queries=safe_int(row.get("QUEUED_QUERIES")),
            spill_queries=safe_int(row.get("SPILL_QUERIES")),
            high_latency_queries=safe_int(row.get("HIGH_LATENCY_QUERIES")),
            total_queries=safe_int(row.get("TOTAL_QUERIES")),
            credit_spike_pct=safe_float(row.get("CREDIT_SPIKE_PCT")),
        )
        render_shell_snapshot((
            ("Queued", f"{safe_int(row.get('QUEUED_QUERIES')):,}"),
            ("Spill", f"{safe_int(row.get('SPILL_QUERIES')):,}"),
            ("Metered Credits", format_credits(safe_float(row.get("METERED_CREDITS")))),
        ))
        if score < 65:
            st.error("Capacity risk: warehouse pressure is high enough to affect service levels or cost control.")
        elif score < 78:
            st.warning("Pressure: review exception warehouses before expanding workload growth.")
        elif score < 90:
            st.info("Watch: warehouse pressure exists, but it is not currently dominant.")
        else:
            st.success("Healthy: no major warehouse pressure signal in this scope.")

        operability_fact = st.session_state.get("wh_operability_fact")
        if operability_fact is not None and not operability_fact.empty:
            st.subheader("Warehouse Control Summary")
            render_shell_snapshot((
                ("Rows", f"{len(operability_fact):,}"),
                ("Overdue", f"{int(operability_fact.get('OVERDUE_OPEN', pd.Series(dtype=int)).sum()):,}"),
                (
                    "Pressure Signals",
                    f"{int(operability_fact.get('QUEUE_PRESSURE_ROWS', pd.Series(dtype=int)).sum() + operability_fact.get('SPILL_PRESSURE_ROWS', pd.Series(dtype=int)).sum()):,}",
                ),
                ("Closed", f"{int(operability_fact.get('VERIFIED_CLOSURES', pd.Series(dtype=int)).sum()):,}"),
            ))
            render_priority_dataframe(
                operability_fact,
                title="Warehouse blockers",
                priority_columns=[
                    "SNAPSHOT_DATE", "CONTROL_STATE", "CONTROL_SOURCE", "ENVIRONMENT",
                    "WAREHOUSE_NAME", "SEVERITY", "SIGNAL",
                    "QUERY_ROWS", "QUEUE_PRESSURE_ROWS", "SPILL_PRESSURE_ROWS",
                    "HIGH_LATENCY_ROWS", "METERED_CREDITS", "CREDIT_ALLOCATION_METHOD", "REVIEW_ROWS",
                    "APPROVAL_REQUIRED_ROWS", "ROLLBACK_REQUIRED_ROWS",
                    "IMPACT_TELEMETRY_ROWS", "OPEN_ACTIONS", "OVERDUE_OPEN",
                    "FIXED_WITHOUT_VERIFICATION", "VERIFIED_CLOSURES", "NEXT_CONTROL_ACTION",
                ],
                sort_by=["CONTROL_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "METERED_CREDITS"],
                ascending=[True, False, False, False],
                raw_label="All warehouse control rows",
                height=300,
            )
            with st.expander("Warehouse Control Status", expanded=False):
                render_shell_snapshot((
                    ("Control summary", "Ready"),
                    ("Escalation route", "Review"),
                    ("Closure status", "Required"),
                    ("Execution", "Runbook only"),
                ))
        elif st.session_state.get("wh_operability_fact_error"):
            defer_source_note(
                "Warehouse control summary is not available yet; refresh data health to enable the fast blocker surface."
            )

        _render_warehouse_watch_floor(score, exceptions, row)
        if exceptions is not None and not exceptions.empty:
            audit_col, audit_hint_col = st.columns([1, 3])
            with audit_col:
                if st.button("Load Execution Audit", key="wh_setting_execution_audit_load", width="stretch"):
                    try:
                        audit_sql = _warehouse_setting_execution_audit_sql(30, company, environment)
                        audit = run_query(
                            audit_sql,
                            ttl_key=f"wh_setting_execution_audit_{company}_{environment}_30",
                            tier="standard",
                            section="Warehouse Health",
                        )
                        st.session_state["wh_setting_execution_audit"] = audit
                        st.session_state["wh_setting_execution_audit_sql"] = audit_sql
                        st.session_state["wh_setting_execution_audit_meta"] = _warehouse_scope_meta(
                            company, environment, 30
                        )
                    except Exception as exc:
                        st.session_state["wh_setting_execution_audit"] = pd.DataFrame()
                        st.warning(f"Warehouse execution audit unavailable: {format_snowflake_error(exc)}")
            with audit_hint_col:
                defer_source_note(
                    "Joins setting-review snapshots to guarded ALTER WAREHOUSE audit rows so changes have "
                    "review status, rollback, SQL hash, executor, and post-change telemetry."
                )

            closure_days_for_board = safe_int(st.session_state.get("wh_action_closure_days", 30)) or 30
            closure_for_board = st.session_state.get("wh_action_closure")
            if not _warehouse_meta_matches(
                st.session_state.get("wh_action_closure_meta"),
                _warehouse_scope_meta(company, environment, closure_days_for_board),
            ):
                closure_for_board = pd.DataFrame()
            audit_for_board = st.session_state.get("wh_setting_execution_audit")
            if not _warehouse_meta_matches(
                st.session_state.get("wh_setting_execution_audit_meta"),
                _warehouse_scope_meta(company, environment, 30),
            ):
                audit_for_board = pd.DataFrame()

            control_board = _warehouse_setting_control_board(
                exceptions,
                closure=closure_for_board,
                execution_audit=audit_for_board,
            )
            operator_moves = _warehouse_operator_next_moves(
                score=score,
                exceptions=exceptions,
                control_board=control_board,
                closure=closure_for_board,
                execution_audit=audit_for_board,
                operability_fact=operability_fact,
            )
            render_priority_dataframe(
                operator_moves,
                title="Warehouse operator next-move gates",
                priority_columns=["GATE", "STATE", "COUNT", "PROOF_REQUIRED", "NEXT_ACTION"],
                sort_by=["GATE_RANK", "COUNT"],
                ascending=[True, False],
                raw_label="All warehouse operator gates",
                height=220,
                max_rows=5,
            )
            intervention_matrix = _warehouse_intervention_matrix(
                exceptions,
                control_board=control_board,
                closure=closure_for_board,
            )
            if not intervention_matrix.empty:
                render_priority_dataframe(
                    intervention_matrix,
                    title="Warehouse DBA intervention matrix",
                    priority_columns=[
                        "DBA_PRIORITY", "INTERVENTION_STATE", "WAREHOUSE_NAME", "SEVERITY", "SIGNAL",
                        "METERED_CREDITS", "PRESSURE_EVIDENCE",
                        "CONTROL_STATE", "CLOSURE_READINESS", "NEXT_DECISION",
                        "PROOF_REQUIRED", "NEXT_WORKFLOW",
                    ],
                    sort_by=["DBA_PRIORITY", "METERED_CREDITS"],
                    ascending=[True, False],
                    raw_label="All warehouse DBA intervention rows",
                    height=280,
                    max_rows=8,
                )
            if not control_board.empty:
                render_priority_dataframe(
                    control_board,
                    title="Warehouse setting control board",
                    priority_columns=[
                        "CONTROL_STATE", "WAREHOUSE_NAME", "SEVERITY", "SIGNAL",
                        "METERED_CREDITS", "ROUTE_READINESS",
                        "AUDIT_READINESS", "AUDIT_BLOCKERS", "CLOSURE_READINESS",
                        "AUDIT_ROWS", "SUCCESSFUL_CHANGES", "FAILED_CHANGES",
                        "LAST_EXECUTION_STATUS", "APPROVAL_REQUIRED", "ROLLBACK_REQUIRED",
                        "IMPACT_TELEMETRY_REQUIRED", "NEXT_CONTROL_ACTION",
                    ],
                    sort_by=["CONTROL_RANK", "METERED_CREDITS"],
                    ascending=[True, False],
                    raw_label="All warehouse setting control rows",
                    height=300,
                    max_rows=12,
                )
        st.divider()

        if exceptions is not None and not exceptions.empty:
            render_priority_dataframe(
                exceptions,
                title="Warehouse capacity exceptions to work first",
                priority_columns=[
                    "SEVERITY", "SIGNAL", "WAREHOUSE_NAME", "WAREHOUSE_SIZE",
                    "QUEUED_QUERIES", "SPILL_QUERIES", "HIGH_LATENCY_QUERIES",
                    "METERED_CREDITS", "ADMIN_READINESS", "SETTING_CHANGE_CANDIDATE",
                    "OWNER", "ESCALATION_TARGET", "APPROVER",
                    "APPROVAL_REQUIRED", "ROLLBACK_REQUIRED", "IMPACT_TELEMETRY_REQUIRED", "NEXT_ACTION",
                ],
                sort_by=["QUEUED_QUERIES", "SPILL_QUERIES", "HIGH_LATENCY_QUERIES", "METERED_CREDITS"],
                ascending=[False, False, False, False],
                raw_label="All warehouse capacity exceptions",
            )
            save_col, review_col = st.columns([1, 2])
            with save_col:
                if st.button("Save Setting Review Snapshot", key="wh_setting_review_snapshot", width="stretch"):
                    session = _warehouse_action_session("save a warehouse setting review snapshot")
                    if session is not None:
                        _save_warehouse_setting_review_snapshot(
                            session,
                            exceptions,
                            company=company,
                            environment=environment,
                            source="Warehouse Health Capacity Brief",
                        )
            with review_col:
                defer_source_note(
                    "Snapshot stores review path, rollback requirement, baseline pressure, and post-change telemetry."
                )
            with st.expander("Warehouse Setting Review Trend", expanded=False):
                trend_days = day_window_selectbox(
                    "Setting review trend window",
                    key="wh_setting_review_trend_days",
                    default=30,
                )
                if st.button("Load Setting Review Trend", key="wh_setting_review_trend_load"):
                    try:
                        trend_sql = _warehouse_setting_review_history_sql(trend_days, company, environment)
                        trend = run_query(
                            trend_sql,
                            ttl_key=f"wh_setting_review_trend_{company}_{environment}_{trend_days}",
                            tier="standard",
                            section="Warehouse Health",
                        )
                        st.session_state["wh_setting_review_trend"] = trend
                        st.session_state["wh_setting_review_trend_sql"] = trend_sql
                    except Exception as exc:
                        st.error(f"Unable to load warehouse setting review trend: {format_snowflake_error(exc)}")
                trend = st.session_state.get("wh_setting_review_trend")
                if trend is not None and not trend.empty:
                    render_priority_dataframe(
                        trend,
                        title="Persistent warehouse setting review backlog",
                        priority_columns=[
                            "WAREHOUSE_NAME", "OWNER", "ESCALATION_TARGET", "REVIEW_ROWS",
                            "APPROVAL_REQUIRED_ROWS", "ROLLBACK_REQUIRED_ROWS",
                            "IMPACT_TELEMETRY_ROWS", "WORST_BASELINE_CAPACITY_SCORE",
                            "MAX_BASELINE_QUEUED_QUERIES", "MAX_BASELINE_SPILL_QUERIES",
                            "LAST_SIGNAL", "LAST_SETTING_CHANGE_CANDIDATE",
                        ],
                        sort_by=["WORST_BASELINE_CAPACITY_SCORE", "APPROVAL_REQUIRED_ROWS", "LAST_SNAPSHOT_TS"],
                        ascending=[True, False, False],
                        raw_label="All persisted warehouse setting reviews",
                        height=260,
                    )
                defer_source_note(
                    "Warehouse setting-review history is owned by the DBA platform team for this environment."
                )
            with st.expander("Warehouse Action Closure Analytics", expanded=False):
                defer_source_note(
                    "Uses Cost & Contract warehouse action-queue rows to show which capacity or efficiency actions are open, "
                    "overdue, telemetry-pending, or recently closed."
                )
                closure_days = day_window_selectbox(
                    "Warehouse closure window",
                    key="wh_action_closure_days",
                    default=30,
                )
                if st.button("Load Warehouse Closure Analytics", key="wh_action_closure_load"):
                    try:
                        closure_sql = _warehouse_action_queue_closure_sql(closure_days, company, environment)
                        closure = run_query(
                            closure_sql,
                            ttl_key=f"wh_action_closure_{company}_{environment}_{closure_days}",
                            tier="standard",
                            section="Warehouse Health",
                        )
                        st.session_state["wh_action_closure"] = closure
                        st.session_state["wh_action_closure_sql"] = closure_sql
                        st.session_state["wh_action_closure_meta"] = _warehouse_scope_meta(
                            company, environment, closure_days
                        )
                    except Exception as exc:
                        st.session_state["wh_action_closure"] = pd.DataFrame()
                        st.warning(f"Warehouse closure analytics unavailable: {format_snowflake_error(exc)}")
                closure = st.session_state.get("wh_action_closure")
                closure_current = _warehouse_meta_matches(
                    st.session_state.get("wh_action_closure_meta"),
                    _warehouse_scope_meta(company, environment, closure_days),
                )
                if closure is not None and not closure.empty and closure_current:
                    render_priority_dataframe(
                        closure,
                        title="Warehouse closure status gaps",
                        priority_columns=[
                            "WAREHOUSE_NAME", "CLOSURE_READINESS", "OWNER", "APPROVER",
                            "TOTAL_ACTIONS", "OPEN_ACTIONS", "OVERDUE_OPEN",
                            "VERIFIED_CLOSURES", "FIXED_WITHOUT_VERIFICATION",
                            "OWNER_GAP_ROWS", "TICKET_GAP_ROWS", "APPROVER_GAP_ROWS",
                            "OWNER_APPROVAL_GAP_ROWS", "VERIFICATION_QUERY_GAP_ROWS",
                            "RECOVERY_RISK_ROWS", "NEXT_DUE_DATE", "LAST_STATUS", "NEXT_ACTION",
                        ],
                        sort_by=["CLOSURE_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "OPEN_ACTIONS"],
                        ascending=[True, False, False, False],
                        raw_label="All warehouse closure rows",
                        height=300,
                    )
                    with st.expander("Warehouse Closure Status", expanded=False):
                        render_shell_snapshot((
                            ("Closure status", "Ready"),
                            ("Telemetry", "Review"),
                            ("Telemetry", "Required"),
                            ("Execution", "Runbook only"),
                        ))
                elif closure is not None and not closure.empty and not closure_current:
                    st.info("Loaded warehouse closure analytics are stale for the active scope. Reload closure analytics before acting.")
                elif closure is not None:
                    st.info("No warehouse capacity action-queue rows found for the selected scope.")
            with st.expander("Warehouse Execution Audit Detail", expanded=False):
                audit = st.session_state.get("wh_setting_execution_audit")
                audit_current = _warehouse_meta_matches(
                    st.session_state.get("wh_setting_execution_audit_meta"),
                    _warehouse_scope_meta(company, environment, 30),
                )
                if audit is not None and not audit.empty and audit_current:
                    render_priority_dataframe(
                        audit,
                        title="Warehouse setting execution audit",
                        priority_columns=[
                            "WAREHOUSE_NAME", "EXECUTION_AUDIT_READINESS", "OWNER", "APPROVER",
                            "APPROVAL_STATE", "CHANGE_TICKET_ID", "REVIEW_ROWS", "AUDIT_ROWS",
                            "SUCCESSFUL_CHANGES", "FAILED_CHANGES", "LAST_SQL_HASH",
                            "LAST_EXECUTED_BY", "LAST_EXECUTED_ROLE", "LAST_EXECUTION_STATUS",
                            "LAST_EXECUTED_AT", "POST_CHANGE_VERIFICATION_STATUS",
                            "NEXT_CONTROL_ACTION",
                        ],
                        sort_by=["FAILED_CHANGES", "AUDIT_ROWS", "LAST_EXECUTED_AT"],
                        ascending=[False, False, False],
                        raw_label="All warehouse execution audit rows",
                        height=300,
                    )
                elif audit is not None and not audit.empty and not audit_current:
                    st.info("Loaded warehouse execution audit is stale for the active scope. Reload execution audit before acting.")
                elif audit is not None:
                    st.info("No warehouse setting review or ALTER WAREHOUSE audit rows found for the selected scope.")
                defer_source_note("Warehouse execution audit detail is available through the reviewed runbook.")
            if st.button("Save Capacity Findings to Action Queue", key="wh_capacity_queue"):
                try:
                    session = _warehouse_action_session("save warehouse capacity findings to the action queue")
                    if session is not None:
                        saved = _queue_capacity_findings(session, exceptions)
                        st.success(f"Saved {saved} warehouse capacity findings to the action queue.")
                except Exception as e:
                    st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
                    st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")
        else:
            st.success("No warehouse capacity exceptions found for this scope.")

        st.download_button(
            "Download Capacity Brief",
            _build_warehouse_capacity_markdown(company, days, score, row, exceptions),
            file_name=f"overwatch_warehouse_capacity_{company.lower()}.md",
            mime="text/markdown",
            key="wh_capacity_download",
        )
        with st.expander("Data Health"):
            render_shell_snapshot((
                ("Summary telemetry", "Ready after refresh"),
                ("Exception telemetry", "Ready after refresh"),
                ("Route review", "Required"),
                ("Execution", "Runbook only"),
            ))


def _queue_efficiency_findings(session, df_eff: pd.DataFrame) -> None:
    if df_eff is None or df_eff.empty:
        st.info("No efficiency findings to queue.")
        return
    company = get_active_company()
    environment = get_active_environment()
    actions = []
    for _, row in df_eff[df_eff["EFFICIENCY_SCORE"] < 70].head(100).iterrows():
        wh = str(row.get("WAREHOUSE_NAME", ""))
        score = safe_float(row.get("EFFICIENCY_SCORE", 0))
        queue = safe_float(row.get("QUEUE_SEC_PER_CREDIT", 0))
        spill = safe_float(row.get("REMOTE_SPILL_GB_PER_CREDIT", 0))
        credits = safe_float(row.get("METERED_CREDITS", 0))
        severity = "High" if score < 50 or queue > 10 or spill > 5 else "Medium"
        owner_context = _warehouse_owner_context({
            "WAREHOUSE_NAME": wh,
            "SIGNAL": "Efficiency",
            "METERED_CREDITS": credits,
        })
        verification_sql = _warehouse_capacity_verification_sql(
            wh,
            days=7,
            environment=environment,
            company=company,
        )
        approver = _warehouse_approval_for({
            "WAREHOUSE_NAME": wh,
            "SIGNAL": "Efficiency",
            "OWNER": owner_context.get("owner", ""),
        })
        finding = (
            f"{wh} efficiency review: queue sec/credit={queue:.2f}, "
            f"spill GB/credit={spill:.2f}; metered credits={credits:.2f}."
        )
        actions.append({
            "Action ID": make_action_id("Warehouse Efficiency", wh, finding),
            "Source": "Warehouse Health - Efficiency",
            "Severity": severity,
            "Category": "Warehouse Efficiency",
            "Entity Type": "Warehouse",
            "Entity": wh,
            "Route": _route_label(owner_context.get("owner", "Platform DBA")),
            "Route Email": owner_context.get("owner_email", ""),
            "Oncall Primary": owner_context.get("oncall_primary", ""),
            "Oncall Secondary": owner_context.get("oncall_secondary", ""),
            "Escalation": _route_label(owner_context.get("approval_group", approver)),
            "Escalation Target": owner_context.get("escalation", "DBA Lead"),
            "Route Basis": _route_label(owner_context.get("source", "")),
            "Route Detail": _route_label(owner_context.get("owner_evidence", "")),
            "Finding": finding,
            "Action": (
                "Review queue, spill, cache, and credit/query patterns. Route setting changes through "
                "Warehouse Settings Manager so current values, review status, rollback plan, and post-change "
                "telemetry are captured."
            ),
            "Estimated Monthly Savings": 0.0,
            "Generated SQL Fix": "\n".join([
                f"-- Review {wh} efficiency before changing warehouse settings.",
                "-- If queue dominates, compare multi-cluster settings and workload routing.",
                "-- If spill dominates, inspect top spilling query profiles before considering size changes.",
            "-- Do not execute warehouse changes from this action; use Warehouse Settings Manager after review.",
            ]),
            "Telemetry Query": verification_sql,
            "Reviewer": _route_label(approver),
            "Telemetry Status": "Requested",
            "Status Note": (
                f"Efficiency review basis attached. Route basis: {owner_context.get('owner_evidence', '')}. "
                "Setting changes require review status, rollback SQL, and post-change telemetry."
            ),
            "Recovery Status": (
                f"Baseline queue sec/credit={queue:.2f}; "
                f"remote spill GB/credit={spill:.2f}; metered credits={credits:.2f}. "
                "Closure uses queue/spill/credit telemetry for the same warehouse and environment."
            ),
            "Recovery Audit State": "Warehouse Efficiency Telemetry Pending",
            "Recovery SLA Target Hours": 24 if severity == "High" else 72,
            "Baseline Value": score,
            "Current Value": score,
            "Measured Delta": 0,
            "Company": company,
            "Environment": environment,
        })
    if not actions:
        st.success("No warehouses below the queue threshold.")
        return
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} warehouse efficiency findings to the action queue.")
    except Exception as e:
        st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
        st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")


def _render_warehouse_source_health(company: str, environment: str) -> None:
    source_health = _warehouse_source_health_rows(st.session_state, company, environment)
    if source_health.empty:
        return
    with st.expander("Warehouse Telemetry Health", expanded=False):
        loaded = int(source_health["STATE"].isin(["Loaded", "No Rows"]).sum())
        stale = int(source_health["STATE"].eq("Stale").sum())
        unavailable = int(source_health["STATE"].eq("Unavailable").sum())
        fast_summary = int(
            source_health[
            source_health["STATE"].isin(["Loaded", "No Rows"])
            & source_health["CONFIDENCE"].astype(str).str.contains("Fast summary", case=False, regex=False)
        ].shape[0]
        )
        render_shell_snapshot((
            ("Current Surfaces", f"{loaded}/{len(source_health)}"),
            ("Fast Summary", f"{fast_summary:,}"),
            ("Stale", f"{stale:,}"),
            ("Unavailable", f"{unavailable:,}"),
        ))
        defer_source_note(
            "Use this before acting on warehouse findings. Stale rows mean the data was loaded under a different "
            "company, environment, lookback, or triage filter."
        )
        render_priority_dataframe(
            source_health,
            title="Warehouse telemetry source and freshness",
            priority_columns=[
                "SURFACE", "STATE", "SOURCE", "CONFIDENCE", "ROWS", "SCOPE", "NEXT_ACTION",
            ],
            sort_by=["STATE_RANK", "SURFACE"],
            ascending=[True, True],
            raw_label="All warehouse source-health rows",
            height=320,
        )


def _apply_warehouse_fast_entry_default() -> None:
    """Keep first Warehouse Health navigation from replaying heavy support panels."""
    if st.session_state.get("_warehouse_health_fast_entry_version") == WAREHOUSE_HEALTH_FAST_ENTRY_VERSION:
        return
    st.session_state.pop("warehouse_health_support_panels_open", None)
    st.session_state["_warehouse_health_fast_entry_version"] = WAREHOUSE_HEALTH_FAST_ENTRY_VERSION


def _render_warehouse_overview_exception_strip(df: pd.DataFrame | None) -> None:
    exceptions = _warehouse_overview_exceptions(df)
    st.markdown("**Exception Strip**")
    if not exceptions:
        st.success("No urgent warehouse queue, spill, latency, or credit movement exceptions in the loaded overview.")
        return
    for item in exceptions:
        message = (
            f"{item['severity']}: {item['warehouse']} - {item['signal']}. "
            f"{item['next_action']}"
        )
        if item["severity"] == "Critical":
            st.error(message)
        elif item["severity"] == "High":
            st.warning(message)
        else:
            st.info(message)


def render():
    credit_price = st.session_state.get("credit_price", DEFAULTS["credit_price"])
    company = get_active_company()
    environment = get_active_environment()
    _apply_warehouse_fast_entry_default()
    _apply_warehouse_brief_first_default()
    _apply_queued_warehouse_health_view()
    global_warehouse = str(st.session_state.get("global_warehouse", "") or "").strip()
    global_user = str(st.session_state.get("global_user", "") or "").strip()
    global_role = str(st.session_state.get("global_role", "") or "").strip()
    global_database = str(st.session_state.get("global_database", "") or "").strip()
    global_start_date = st.session_state.get("global_start_date")
    global_end_date = st.session_state.get("global_end_date")

    selected_days = safe_int(st.session_state.get("wh_days", 7), 7) or 7
    if selected_days < 1 or selected_days > 30:
        selected_days = 7
    _render_warehouse_action_brief(_warehouse_action_brief(company, environment, selected_days))
    _render_warehouse_operating_snapshot(_warehouse_operating_snapshot(company, environment, selected_days))

    render_operator_briefing(
        [
            ("First move", "Decide whether pressure is queue, spill, latency, or cost drift."),
            ("Telemetry", "Use metering plus query history before changing size or clusters."),
            ("Control", "Tune routing, auto-suspend, QAS, size, or multi-cluster with measured context."),
            ("Output", "Create a warehouse capacity brief for release or cost review."),
        ],
        columns=4,
    )
    warehouse_view = render_workflow_selector(
        "Warehouse capacity workflow",
        "warehouse_health_view",
        WAREHOUSE_HEALTH_VIEWS,
        WAREHOUSE_HEALTH_DETAILS,
        columns=3,
    )
    if warehouse_view == "Overview & Scaling" and not _warehouse_frame_has_rows(st.session_state.get("wh_df_wh")):
        _render_warehouse_brief_launchpad()
    show_support_panels = bool(st.session_state.get("warehouse_health_support_panels_open"))
    if show_support_panels:
        if st.button("Hide Detail Panels", key="warehouse_health_hide_support_panels"):
            st.session_state["warehouse_health_support_panels_open"] = False
            st.rerun()
        _render_capacity_brief(company, environment)
        _render_warehouse_source_health(company, environment)
    elif st.button("Detail Panels", key="warehouse_health_open_support_panels"):
        st.session_state["warehouse_health_support_panels_open"] = True
        st.rerun()
    if st.session_state.get("exceptions_only_mode") and warehouse_view != "Overview & Scaling":
        return

    # -- OVERVIEW --------------------------------------------------------------
    if warehouse_view == "Overview & Scaling":
        st.subheader("Warehouse Capacity Overview")
        wh_days = day_window_selectbox("Lookback", key="wh_days", default=7)

        def _load_warehouse_overview() -> None:
            try:
                session = _warehouse_action_session("load warehouse overview")
                if session is None:
                    return
                overview_result = load_shared_warehouse_overview(
                    session,
                    wh_days,
                    company,
                    force=True,
                    section="Warehouse Health",
                )
                df_w = overview_result.data
                source = overview_result.source
                try:
                    st.session_state["wh_settings_inventory"] = load_warehouse_inventory(
                        session,
                        company,
                    )
                    st.session_state["wh_settings_inventory_meta"] = with_loaded_at(
                        _warehouse_scope_meta(
                            company,
                            environment,
                            wh_days,
                        ),
                        source="Warehouse guardrail metadata",
                    )
                    st.session_state.pop("wh_settings_inventory_error", None)
                except Exception as metadata_exc:
                    st.session_state["wh_settings_inventory"] = pd.DataFrame()
                    st.session_state["wh_settings_inventory_error"] = format_snowflake_error(metadata_exc)
                st.session_state["wh_df_wh"] = df_w
                st.session_state["wh_df_wh_source"] = source
                st.session_state["wh_df_wh_meta"] = with_loaded_at(
                    _warehouse_scope_meta(company, environment, wh_days),
                    source=source,
                )
            except Exception as e:
                st.warning(f"Warehouse overview unavailable in this role/context: {format_snowflake_error(e)}")

        wh_expected_meta = _warehouse_scope_meta(company, environment, wh_days)
        loaded_wh_meta = st.session_state.get("wh_df_wh_meta", {})
        wh_current = (
            st.session_state.get("wh_df_wh") is not None
            and _warehouse_meta_matches(loaded_wh_meta, wh_expected_meta)
        )
        if consume_section_autoload_request("Warehouse Health") and not wh_current:
            st.caption("Warehouse capacity opened with a lightweight summary. Load warehouse data when current capacity detail is needed.")
        render_data_freshness(
            loaded_wh_meta if wh_current else {},
            source=st.session_state.get("wh_df_wh_source", "Warehouse overview"),
            target_minutes=30,
            delayed_note="Warehouse overview prefers fast summary telemetry; live account history refresh is explicit.",
        )

        if st.button("Load Warehouse Data", key="wh_load"):
            _load_warehouse_overview()

        if (
            st.session_state.get("wh_df_wh") is not None
            and not _warehouse_meta_matches(
                st.session_state.get("wh_df_wh_meta"),
                _warehouse_scope_meta(company, environment, wh_days),
            )
        ):
            st.info("Loaded warehouse overview is stale for the active scope. Reload Warehouse Data before acting.")
        elif st.session_state.get("wh_df_wh") is not None and not st.session_state["wh_df_wh"].empty:
            df_w = st.session_state["wh_df_wh"]

            render_shell_snapshot((
                ("Warehouses Active", len(df_w)),
                ("Total Queries", f"{int(df_w['TOTAL_QUERIES'].sum()):,}"),
                ("Total Remote Spill", f"{df_w['TOTAL_REMOTE_SPILL_GB'].sum():.1f} GB"),
                ("Credit Delta", format_credits(float(df_w.get("CREDIT_DELTA", pd.Series(dtype=float)).sum()))),
            ))
            wh_source = st.session_state.get("wh_df_wh_source", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY")
            wh_source_lower = str(wh_source).lower()
            confidence = "estimated" if "fast" in wh_source_lower and "summary" in wh_source_lower else "exact"
            defer_source_note(metric_confidence_label(confidence), wh_source)
            _render_warehouse_overview_exception_strip(df_w)
            detail_key = "warehouse_health_show_overview_evidence"
            detail_open = bool(st.session_state.get(detail_key))
            detail_col, _ = st.columns([1.2, 4.0])
            with detail_col:
                if detail_open:
                    if st.button("Hide Warehouse Detail", key="warehouse_health_hide_overview_evidence", width="stretch"):
                        st.session_state[detail_key] = False
                        st.rerun()
                elif st.button("Show Warehouse Detail", key="warehouse_health_show_overview_evidence_button", width="stretch"):
                    st.session_state[detail_key] = True
                    st.rerun()
            if not detail_open:
                return

            movement = _warehouse_period_movement(df_w)
            if not movement.empty:
                st.subheader("Warehouse Period Movement")
                render_priority_dataframe(
                    movement,
                    title="Current vs prior warehouse movement",
                    priority_columns=[
                        "WAREHOUSE_NAME", "MOVEMENT_STATE", "METERED_CREDITS",
                        "PRIOR_METERED_CREDITS", "CREDIT_DELTA", "CREDIT_DELTA_PCT",
                        "AVG_QUEUED_SEC", "TOTAL_REMOTE_SPILL_GB", "NEXT_ACTION",
                    ],
                    sort_by=["CREDIT_DELTA", "METERED_CREDITS"],
                    ascending=[False, False],
                    raw_label="All warehouse period movement rows",
                    height=320,
                )
            else:
                defer_source_note("Current/prior warehouse movement appears when the fast warehouse summary is available.")

            settings_inventory = st.session_state.get("wh_settings_inventory")
            if not _warehouse_meta_matches(
                st.session_state.get("wh_settings_inventory_meta"),
                _warehouse_scope_meta(company, environment, wh_days),
            ):
                settings_inventory = pd.DataFrame()

            guardrail_summary, guardrail_board = _build_warehouse_guardrail_coverage(
                df_w,
                settings_inventory=settings_inventory,
            )
            if not guardrail_board.empty:
                st.subheader("Warehouse Guardrail Coverage")
                render_shell_snapshot((
                    ("Guardrail State", "Stable" if guardrail_summary["score"] >= 90 else "Review" if guardrail_summary["score"] >= 70 else "Critical"),
                    ("Blocked", f"{guardrail_summary['blocked']:,}"),
                    ("Needs Review", f"{guardrail_summary['review']:,}"),
                    ("Data Missing", f"{guardrail_summary['unknown']:,}"),
                ))
                render_priority_dataframe(
                    guardrail_board,
                    title="Auto-derived warehouse guardrail coverage",
                    priority_columns=[
                        "WAREHOUSE_NAME", "GUARDRAIL_STATE", "GUARDRAIL_SCORE", "SEVERITY",
                        "RESOURCE_MONITOR_STATE", "AUTO_SUSPEND_STATE", "TIMEOUT_STATE",
                        "ESCALATION_ROUTE_STATE", "CAPACITY_STATE", "COST_STATE",
                        "METERED_CREDITS", "CREDIT_DELTA",
                        "AVG_QUEUED_SEC", "TOTAL_REMOTE_SPILL_GB", "P95_ELAPSED_SEC",
                        "NEXT_ACTION", "PROOF_REQUIRED",
                    ],
                    sort_by=["GUARDRAIL_RANK", "GUARDRAIL_SCORE", "METERED_CREDITS"],
                    ascending=[True, True, False],
                    raw_label="All warehouse guardrail coverage rows",
                    height=320,
                    max_rows=12,
                )
                download_csv(guardrail_board, "warehouse_guardrail_coverage.csv")
                setting_plan = _warehouse_setting_action_plan(guardrail_board)
                st.session_state["wh_settings_action_plan"] = setting_plan
                if not setting_plan.empty:
                    st.subheader("Warehouse Setting Action Plan")
                    render_priority_dataframe(
                        setting_plan,
                        title="Recommended warehouse setting controls",
                        priority_columns=[
                            "PRIORITY", "WAREHOUSE_NAME", "ACTION_TYPE", "CURRENT_STATE",
                            "CURRENT_SETTING", "SAFE_SETTING_MOVE", "WHY", "ROLLBACK_CHECK",
                        ],
                        sort_by=["PRIORITY", "WAREHOUSE_NAME", "ACTION_TYPE"],
                        ascending=[True, True, True],
                        raw_label="All warehouse setting action rows",
                        height=320,
                        max_rows=12,
                    )
                    download_csv(setting_plan, "warehouse_setting_action_plan.csv")
                    _render_warehouse_setting_action_detail(setting_plan)
                _render_warehouse_cost_control_posture(settings_inventory, df_w)
                if st.session_state.get("wh_settings_inventory_error"):
                    defer_source_note(
                        "Warehouse metadata was unavailable for resource-monitor, timeout, and auto-suspend checks: "
                        f"{st.session_state.get('wh_settings_inventory_error')}"
                    )
                elif settings_inventory is None or settings_inventory.empty:
                    defer_source_note("Resource-monitor, timeout, and AUTO_SUSPEND checks need SHOW WAREHOUSES metadata.")

            render_priority_dataframe(
                df_w,
                title="Warehouse overview ranked by pressure",
                priority_columns=[
                    "WAREHOUSE_NAME",
                    "WAREHOUSE_SIZE",
                    "TOTAL_QUERIES",
                    "AVG_QUEUED_SEC",
                    "TOTAL_REMOTE_SPILL_GB",
                    "AVG_ELAPSED_SEC",
                    "METERED_CREDITS",
                    "PRIOR_METERED_CREDITS",
                    "CREDIT_DELTA",
                    "AVG_CACHE_PCT",
                ],
                sort_by=[
                    "AVG_QUEUED_SEC",
                    "TOTAL_REMOTE_SPILL_GB",
                    "AVG_ELAPSED_SEC",
                    "METERED_CREDITS",
                ],
                ascending=[False, False, False, False],
                raw_label="All warehouse overview rows",
            )

            # Cache efficiency chart
            cache_available = "AVG_CACHE_PCT" in df_w.columns and df_w["AVG_CACHE_PCT"].notna().any()
            if cache_available:
                st.subheader("Cache Hit % by Warehouse")
                render_drillable_bar_chart(
                    df_w,
                    dimension="WAREHOUSE_NAME",
                    measure="AVG_CACHE_PCT",
                    key="wh_cache_pct",
                    drilldown_column="warehouse_name",
                    lookback_hours=wh_days * 24,
                )
            else:
                defer_source_note("Cache hit percentage is a live ACCOUNT_USAGE-only metric and is not included in the fast warehouse summary.")

            download_csv(df_w, "warehouse_health.csv")

            # Scaling events
            st.divider()
            st.subheader("Scaling Events (WAREHOUSE_METERING_HISTORY)")
            if st.button("Load Scaling Events", key="wh_scale_load"):
                try:
                    session = _warehouse_action_session("load warehouse scaling events")
                    if session is None:
                        return
                    scale_result = load_shared_warehouse_scaling_events(
                        session,
                        wh_days,
                        company,
                        force=True,
                        section="Warehouse Health",
                    )
                    st.session_state["wh_scaling"] = scale_result.data
                    st.session_state["wh_scaling_source"] = scale_result.source
                    st.session_state["wh_scaling_meta"] = _warehouse_scope_meta(company, environment, wh_days)
                except Exception as e:
                    st.warning(f"Scaling events unavailable in this role/context: {format_snowflake_error(e)}")
            df_scale = st.session_state.get("wh_scaling")
            if (
                df_scale is not None
                and not _warehouse_meta_matches(
                    st.session_state.get("wh_scaling_meta"),
                    _warehouse_scope_meta(company, environment, wh_days),
                )
            ):
                st.info("Loaded scaling events are stale for the active scope. Reload Scaling Events before acting.")
            elif df_scale is not None and not df_scale.empty:
                scale_source = st.session_state.get("wh_scaling_source", "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY")
                defer_source_note(metric_confidence_label("exact"), scale_source)
                render_priority_dataframe(
                    df_scale,
                    title="Largest scaling/metering events",
                    priority_columns=[
                        "WAREHOUSE_NAME",
                        "WAREHOUSE_SIZE",
                        "START_TIME",
                        "END_TIME",
                        "CREDITS_USED",
                        "CREDITS_USED_COMPUTE",
                        "CREDITS_USED_CLOUD_SERVICES",
                    ],
                    sort_by=["CREDITS_USED", "CREDITS_USED_COMPUTE"],
                    ascending=[False, False],
                    raw_label="All scaling events",
                )
                download_csv(df_scale, "scaling_events.csv")
            elif df_scale is not None:
                st.info("No scaling or metering events found for the selected warehouse scope.")

    elif warehouse_view == "Efficiency":
        st.subheader("Warehouse Efficiency Risks")
        eff_days = day_window_selectbox("Lookback", key="wh_eff_days", default=7)
        if st.button("Load Efficiency Metrics", key="wh_eff_load"):
            try:
                session = _warehouse_action_session("load warehouse efficiency metrics")
                if session is None:
                    return
                result = load_shared_warehouse_efficiency(
                    session,
                    eff_days,
                    company,
                    force=True,
                    section="Warehouse Health",
                )
                st.session_state["wh_efficiency"] = result.data
                st.session_state["wh_efficiency_meta"] = _warehouse_scope_meta(company, environment, eff_days)
                st.session_state["wh_efficiency_source"] = result.source
            except Exception as e:
                st.warning(f"Efficiency metrics unavailable in this role/context: {format_snowflake_error(e)}")

        df_eff = st.session_state.get("wh_efficiency")
        if (
            df_eff is not None
            and not _warehouse_meta_matches(
                st.session_state.get("wh_efficiency_meta"),
                _warehouse_scope_meta(company, environment, eff_days),
            )
        ):
            st.info("Loaded efficiency metrics are stale for the active scope. Reload Efficiency Metrics before acting.")
        elif df_eff is not None and not df_eff.empty:
            low = df_eff[df_eff["EFFICIENCY_SCORE"] < 70]
            render_shell_snapshot((
                ("Warehouses Reviewed", len(df_eff)),
                ("Needs Review", len(low)),
                ("Total metered credits", format_credits(float(df_eff["METERED_CREDITS"].sum()))),
            ))
            defer_source_note(
                metric_confidence_label("allocated"),
                st.session_state.get("wh_efficiency_source", freshness_note("ACCOUNT_USAGE")),
            )
            df_eff_display = df_eff.rename(columns={"EFFICIENCY_SCORE": "REVIEW_PRIORITY"})
            render_priority_dataframe(
                df_eff_display,
                title="Warehouse efficiency risks",
                priority_columns=[
                    "WAREHOUSE_NAME",
                    "WAREHOUSE_SIZE",
                    "REVIEW_PRIORITY",
                    "METERED_CREDITS",
                    "CREDITS_PER_QUERY",
                    "QUEUE_SEC_PER_CREDIT",
                    "REMOTE_SPILL_GB_PER_CREDIT",
                    "AVG_CACHE_PCT",
                ],
                sort_by=["REVIEW_PRIORITY", "METERED_CREDITS"],
                ascending=[True, False],
                raw_label="All warehouse efficiency rows",
            )
            render_drillable_bar_chart(
                df_eff_display,
                dimension="WAREHOUSE_NAME",
                measure="REVIEW_PRIORITY",
                key="wh_efficiency_review_priority",
                drilldown_column="warehouse_name",
                lookback_hours=eff_days * 24,
            )
            download_csv(df_eff, "warehouse_efficiency.csv")
            if st.button("Save low-efficiency warehouses to Action Queue", key="wh_eff_queue"):
                session = _warehouse_action_session("save warehouse efficiency findings to the action queue")
                if session is not None:
                    _queue_efficiency_findings(session, df_eff)

    # -- SPILL -----------------------------------------------------------------
    elif warehouse_view == "Spill & Memory":
        st.subheader("Spill & Memory Pressure")
        sp_days = day_window_selectbox("Lookback", key="sp_days", default=7)

        if st.button("Load Spill Data", key="sp_load"):
            try:
                session = _warehouse_action_session("load warehouse spill data")
                if session is None:
                    return
                result = load_shared_warehouse_spill(
                    session,
                    sp_days,
                    company,
                    force=True,
                    section="Warehouse Health",
                )
                st.session_state["wh_df_sp"] = result.data
                st.session_state["wh_df_sp_meta"] = _warehouse_scope_meta(company, environment, sp_days)
                st.session_state["wh_df_sp_source"] = result.source
            except Exception as e:
                st.warning(f"Spill data unavailable in this role/context: {format_snowflake_error(e)}")

        if (
            st.session_state.get("wh_df_sp") is not None
            and not _warehouse_meta_matches(
                st.session_state.get("wh_df_sp_meta"),
                _warehouse_scope_meta(company, environment, sp_days),
            )
        ):
            st.info("Loaded spill data is stale for the active scope. Reload Spill Data before acting.")
        elif st.session_state.get("wh_df_sp") is not None and not st.session_state["wh_df_sp"].empty:
            df_sp = st.session_state["wh_df_sp"]
            render_shell_snapshot((
                ("Spilling Warehouses", len(df_sp)),
                ("Total Local Spill", f"{df_sp['LOCAL_SPILL_GB'].sum():.1f} GB"),
                ("Total Remote Spill", f"{df_sp['REMOTE_SPILL_GB'].sum():.1f} GB"),
            ))
            defer_source_note(st.session_state.get("wh_df_sp_source", "Live: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"))
            render_priority_dataframe(
                df_sp,
                title="Spill and memory pressure",
                priority_columns=[
                    "WAREHOUSE_NAME",
                    "WAREHOUSE_SIZE",
                    "SPILL_QUERY_COUNT",
                    "LOCAL_SPILL_GB",
                    "REMOTE_SPILL_GB",
                    "AVG_ELAPSED_SEC",
                ],
                sort_by=["REMOTE_SPILL_GB", "LOCAL_SPILL_GB", "AVG_ELAPSED_SEC"],
                ascending=[False, False, False],
                raw_label="All spill rows",
            )
            df_sp["TOTAL_SPILL_GB"] = df_sp["LOCAL_SPILL_GB"] + df_sp["REMOTE_SPILL_GB"]
            render_drillable_bar_chart(
                df_sp,
                dimension="WAREHOUSE_NAME",
                measure="TOTAL_SPILL_GB",
                key="wh_spill_total",
                drilldown_column="warehouse_name",
                lookback_hours=sp_days * 24,
            )
            for _, row in df_sp.iterrows():
                if row["REMOTE_SPILL_GB"] > 10:
                    st.error(f"**{row['WAREHOUSE_NAME']}**: {row['REMOTE_SPILL_GB']:.1f} GB remote spill - upsize immediately")
            download_csv(df_sp, "spill_report.csv")

    # -- HEATMAP ---------------------------------------------------------------
    elif warehouse_view == "Workload Heatmap":
        st.subheader("Workload Concurrency Heatmap")
        hm_days = day_window_selectbox("Lookback", key="hm_days", default=30)

        if st.button("Refresh Heatmap", key="hm_build"):
            try:
                result = load_shared_warehouse_heatmap(
                    hm_days,
                    company,
                    warehouse_contains=global_warehouse,
                    user_contains=global_user,
                    role_contains=global_role,
                    database_contains=global_database,
                    start_date=global_start_date,
                    end_date=global_end_date,
                    force=True,
                    section="Warehouse Health",
                )
                if result.message:
                    st.warning(result.message)
                st.session_state["wh_df_hm"] = result.data
                st.session_state["wh_df_hm_meta"] = _warehouse_scope_meta(company, environment, hm_days)
                st.session_state["wh_df_hm_source"] = result.source
            except Exception as e:
                st.warning(f"Workload heatmap unavailable in this role/context: {format_snowflake_error(e)}")

        if (
            st.session_state.get("wh_df_hm") is not None
            and not _warehouse_meta_matches(
                st.session_state.get("wh_df_hm_meta"),
                _warehouse_scope_meta(company, environment, hm_days),
            )
        ):
            st.info("Loaded workload heatmap is stale for the active scope. Refresh Heatmap before acting.")
        elif st.session_state.get("wh_df_hm") is not None and not st.session_state["wh_df_hm"].empty:
            df_hm = st.session_state["wh_df_hm"]
            if st.session_state.get("wh_df_hm_source"):
                defer_source_note(str(st.session_state.get("wh_df_hm_source")))
            whs = df_hm["WAREHOUSE_NAME"].unique()
            sel_wh = st.selectbox("Warehouse", whs, key="hm_wh_sel")

            if sel_wh:
                wh_data = df_hm[df_hm["WAREHOUSE_NAME"] == sel_wh]
                pivot = wh_data.pivot_table(
                    index="DAY_OF_WEEK", columns="HOUR_OF_DAY",
                    values="QUERY_COUNT", aggfunc="sum"
                ).fillna(0)
                day_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
                pivot.index = pivot.index.map(lambda x: day_names.get(int(x), str(x)))
                st.subheader(f"Query Volume Heatmap - {sel_wh}")
                st.dataframe(pivot.style.background_gradient(cmap="YlOrRd"), width="stretch")
                render_shell_snapshot((
                    ("Total Queries", f"{int(wh_data['QUERY_COUNT'].sum()):,}"),
                    ("Peak Hour", f"{int(pivot.max().max()):,}"),
                    ("Avg Elapsed", f"{wh_data['AVG_ELAPSED_SEC'].mean():.1f}s"),
                ))

    elif warehouse_view == "Optimization Advisor":
        render_optimization_advisor()
