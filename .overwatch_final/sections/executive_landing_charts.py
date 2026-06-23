"""Executive Landing chart and board render helpers."""
from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from config import (
    ACTION_QUEUE_TABLE,
    ALERT_DB,
    ALERT_SCHEMA,
    DEFAULT_COMPANY,
    DEFAULT_DAY_WINDOW,
    DEFAULT_ENVIRONMENT,
    DEFAULTS,
    DAY_WINDOW_OPTIONS,
)
from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.navigation import apply_navigation_state, apply_section_workflow_navigation
from sections.shell_helpers import (
    render_escaped_bold_text,
    render_refresh_contract,
    render_shell_kpi_row,
    render_shell_snapshot,
    render_shell_status_strip,
)
from runtime_state import EXECUTIVE_LANDING_WORKFLOW
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_source_note


pd = lazy_pandas()

build_mart_cost_cockpit_sql = _lazy_util("build_mart_cost_cockpit_sql")
build_schema_migration_status_sql = _lazy_util("build_schema_migration_status_sql")
credits_to_dollars = _lazy_util("credits_to_dollars")
format_snowflake_error = _lazy_util("format_snowflake_error")
get_environment_label = _lazy_util("get_environment_label")
get_session_for_action = _lazy_util("get_session_for_action")
load_action_queue = _lazy_util("load_action_queue")
load_alert_history = _lazy_util("load_alert_history")
mart_object_name = _lazy_util("mart_object_name")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
build_loaded_section_alert_signal_board = _lazy_util("build_loaded_section_alert_signal_board")
load_enterprise_operating_rollups = _lazy_util("load_enterprise_operating_rollups")
load_change_intelligence_summary = _lazy_util("load_change_intelligence_summary")
load_closed_loop_summary = _lazy_util("load_closed_loop_summary")
load_command_center_summary = _lazy_util("load_command_center_summary")
load_executive_scorecard_summary = _lazy_util("load_executive_scorecard_summary")
load_executive_forecast_summary = _lazy_util("load_executive_forecast_summary")
load_production_readiness_summary = _lazy_util("load_production_readiness_summary")
render_workflow_selector = _lazy_util("render_workflow_selector")
run_query = _lazy_util("run_query")
safe_identifier = _lazy_util("safe_identifier")
snowflake_connection_known_unavailable = _lazy_util("snowflake_connection_known_unavailable")
sql_literal = _lazy_util("sql_literal")


from sections.executive_landing_contracts import *
from sections.executive_landing_common import _altair, _format_gb, _format_metric_value, _format_seconds, _money
from sections.executive_landing_models import *


def _render_observability_source_status(board: pd.DataFrame) -> None:
    statuses = _obs_rows(board, "SOURCE_STATUS")
    if not isinstance(statuses, pd.DataFrame) or statuses.empty:
        return
    rows = statuses[["DIMENSION", "METRIC", "UNIT"]].copy()
    rows = rows.rename(columns={"DIMENSION": "INPUT", "METRIC": "STATE", "UNIT": "DETAIL"})
    loaded = int(rows["STATE"].astype(str).eq("Loaded").sum()) if "STATE" in rows.columns else 0
    unavailable = int(rows["STATE"].astype(str).eq("Unavailable").sum()) if "STATE" in rows.columns else 0
    no_rows = int(rows["STATE"].astype(str).eq("No Rows").sum()) if "STATE" in rows.columns else 0
    with st.expander(
        f"Executive summary input status: {loaded} loaded, {unavailable} unavailable, {no_rows} no rows",
        expanded=unavailable > 0 and loaded == 0,
    ):
        render_priority_dataframe(
            rows,
            title="Executive summary input status",
            priority_columns=["INPUT", "STATE", "DETAIL"],
            sort_by=["STATE", "INPUT"],
            ascending=[True, True],
            raw_label="All executive summary input rows",
            height=260,
            max_rows=12,
        )

def _render_executive_priority_board(board: pd.DataFrame, *, days: int, advisor_rows: pd.DataFrame | None = None) -> None:
    rows = _executive_priority_rows(board, days=int(days), advisor_rows=advisor_rows)
    if rows.empty:
        return
    render_priority_dataframe(
        rows,
        title="Executive signals to work first",
        priority_columns=[
            "PRIORITY", "LANE", "STATE", "SIGNAL",
            "BUSINESS_IMPACT", "NEXT_ACTION", "ROUTE",
        ],
        sort_by=["PRIORITY"],
        ascending=True,
        raw_label="All executive priority rows",
        height=300,
        max_rows=12,
    )

def _render_executive_pressure_board(board: pd.DataFrame, advisor_rows: pd.DataFrame | None = None) -> None:
    rows = _executive_pressure_rows(board, advisor_rows=advisor_rows)
    if rows.empty and isinstance(board, pd.DataFrame) and {"LANE", "STATE", "VALUE", "PRESSURE_SCORE"}.issubset(set(board.columns)):
        rows = board.copy()
    if rows.empty:
        return
    st.markdown("**Executive Pressure Lanes**")
    top_pressure = safe_float(rows.iloc[0].get("PRESSURE_SCORE"))
    render_shell_kpi_row((
        ("Highest Pressure", str(rows.iloc[0].get("LANE") or "Loaded")),
        ("Pressure", _pressure_level(top_pressure)),
        ("Escalation", str(rows.iloc[0].get("OWNER_ROUTE") or "Executive Landing")),
        ("State", str(rows.iloc[0].get("STATE") or "Review")),
    ))
    display_rows = rows.copy()
    display_rows["PRESSURE_LEVEL"] = display_rows["PRESSURE_SCORE"].map(_pressure_level)
    display_rows = display_rows.drop(columns=["PRESSURE_SCORE"], errors="ignore")
    render_priority_dataframe(
        display_rows,
        title="Executive pressure details",
        priority_columns=[
            "LANE", "STATE", "VALUE", "PRESSURE_LEVEL",
            "OWNER_ROUTE", "WHY_IT_MATTERS", "NEXT_ACTION",
        ],
        sort_by=["LANE"],
        ascending=[True],
        raw_label="All executive pressure lanes",
        height=250,
        max_rows=8,
    )

def _render_loaded_advisor_overlay(advisor_rows: pd.DataFrame | None) -> None:
    if not isinstance(advisor_rows, pd.DataFrame) or advisor_rows.empty:
        return
    totals = _advisor_overlay_totals(advisor_rows)
    st.markdown("**Loaded Advisor Signals**")
    render_shell_kpi_row((
        ("Advisor Lanes", f"{totals['advisor_lanes']:,}"),
        ("Findings", f"{totals['advisor_findings']:,}"),
        ("High Priority", f"{totals['advisor_high_findings']:,}"),
        ("Est. Savings / Mo", _money(totals["advisor_estimated_monthly_savings_usd"])),
    ))
    render_priority_dataframe(
        advisor_rows,
        title="Advisor signals included in executive summary",
        priority_columns=[
            "PRIORITY", "LANE", "STATE", "VALUE", "ADVISOR_SIGNAL", "NEXT_ACTION", "ROUTE",
        ],
        sort_by=["PRIORITY", "HIGH_FINDINGS", "EST_MONTHLY_SAVINGS_USD"],
        ascending=[True, False, False],
        raw_label="All loaded advisor summary rows",
        height=260,
        max_rows=8,
    )

def _render_executive_command_summary(board: pd.DataFrame, advisor_rows: pd.DataFrame | None, *, days: int) -> None:
    rows = _executive_command_summary_rows(board, advisor_rows, days=int(days))
    if rows.empty:
        return
    st.markdown("**Executive Command Summary**")
    render_priority_dataframe(
        rows,
        title="Current top operating calls",
        priority_columns=["AREA", "STATE", "CURRENT_SIGNAL", "NEXT_ACTION", "ROUTE"],
        sort_by=["PRIORITY", "AREA"],
        ascending=[True, True],
        raw_label="All executive command summary rows",
        height=260,
        max_rows=5,
    )

def _render_line_chart(
    rows: pd.DataFrame,
    *,
    title: str,
    y_column: str,
    y_title: str,
    color_column: str | None = None,
    height: int = 210,
) -> None:
    render_escaped_bold_text(title)
    if rows is None or rows.empty or y_column not in rows.columns or "PERIOD_START" not in rows.columns:
        st.caption("No precomputed rows loaded for this chart.")
        return
    chart_rows = rows.copy()
    chart_rows["PERIOD_START"] = pd.to_datetime(chart_rows["PERIOD_START"], errors="coerce")
    chart_rows[y_column] = pd.to_numeric(chart_rows[y_column], errors="coerce").fillna(0)
    chart_rows = chart_rows.dropna(subset=["PERIOD_START"])
    if chart_rows.empty:
        st.caption("No precomputed rows loaded for this chart.")
        return
    alt = _altair()
    color = alt.Color(f"{color_column}:N", title=None) if color_column and color_column in chart_rows.columns else alt.value("#29B5E8")
    chart = (
        alt.Chart(chart_rows)
        .mark_line(point=True)
        .encode(
            x=alt.X("PERIOD_START:T", title=None),
            y=alt.Y(f"{y_column}:Q", title=y_title),
            color=color,
            tooltip=[
                alt.Tooltip("PERIOD_START:T", title="Period"),
                alt.Tooltip(f"{y_column}:Q", title=y_title, format=",.2f"),
                *([alt.Tooltip(f"{color_column}:N", title="Metric")] if color_column and color_column in chart_rows.columns else []),
            ],
        )
        .properties(height=height)
    )
    st.altair_chart(chart, width="stretch")

def _render_bar_chart(
    rows: pd.DataFrame,
    *,
    title: str,
    x_column: str,
    y_column: str,
    x_title: str,
    color: str = "#29B5E8",
    height: int = 220,
) -> None:
    render_escaped_bold_text(title)
    if rows is None or rows.empty or x_column not in rows.columns or y_column not in rows.columns:
        st.caption("No precomputed rows loaded for this chart.")
        return
    chart_rows = rows.copy()
    chart_rows[y_column] = pd.to_numeric(chart_rows[y_column], errors="coerce").fillna(0)
    chart_rows[x_column] = chart_rows[x_column].astype(str)
    chart_rows = chart_rows.sort_values(y_column, ascending=False).head(10)
    if chart_rows.empty:
        st.caption("No precomputed rows loaded for this chart.")
        return
    alt = _altair()
    chart = (
        alt.Chart(chart_rows)
        .mark_bar(cornerRadiusTopRight=3, cornerRadiusBottomRight=3, color=color)
        .encode(
            x=alt.X(f"{y_column}:Q", title=x_title),
            y=alt.Y(
                f"{x_column}:N",
                sort=alt.SortField(field=y_column, order="descending"),
                title=None,
                axis=alt.Axis(labelLimit=220),
            ),
            tooltip=[
                alt.Tooltip(f"{x_column}:N", title="Group"),
                alt.Tooltip(f"{y_column}:Q", title=x_title, format=",.2f"),
            ],
        )
        .properties(height=height)
    )
    st.altair_chart(chart, width="stretch")

def _render_executive_observability_board(
    board: pd.DataFrame,
    payload: dict,
    *,
    company: str,
    environment: str,
    days: int,
    credit_price: float,
) -> None:
    error = str((payload or {}).get("error") or "").strip()
    advisor_rows = _executive_loaded_advisor_rows()
    if not isinstance(board, pd.DataFrame) or board.empty or not _has_observability_kpis(board):
        render_shell_status_strip(
            state="Refresh Needed" if error else "Waiting",
            headline="Executive observability summary is ready for precomputed Snowflake facts.",
            detail=(
                error
                if error
                else "Refresh executive summaries to populate cost, query, task, storage, alert, and Cortex facts."
            ),
        )
        render_shell_kpi_row((
            ("Scope", f"{company} / {get_environment_label(environment, company)}"),
            ("Window", f"{int(days)}d"),
            ("Source", "Data summaries"),
            ("Status", "No rows"),
        ))
        render_refresh_contract(
            payload,
            source="Executive summary facts",
            target_minutes=60,
            refresh_method="Scheduled data refresh",
            live_fallback="On demand",
        )
        st.markdown("**Snowflake Observability Wall**")
        render_shell_kpi_row((
            ("Spend", "On demand"),
            ("Delta", "On demand"),
            ("Cortex", "On demand"),
            ("30d Forecast", "On demand"),
        ))
        render_shell_kpi_row((
            ("Queries", "On demand"),
            ("Avg Runtime", "On demand"),
            ("P95 Runtime", "On demand"),
            ("Remote Spill", "On demand"),
        ))
        render_shell_kpi_row((
            ("Critical / High", "On demand"),
            ("Failed Queries", "On demand"),
            ("Failed Tasks", "On demand"),
            ("Open Actions", "On demand"),
        ))
        render_shell_kpi_row((
            ("Queue Time", "On demand"),
            ("Avg/day", "On demand"),
            ("Storage", "On demand"),
            ("Freshness", "On demand"),
        ))
        _render_executive_command_summary(pd.DataFrame(), advisor_rows, days=int(days))
        _render_executive_pressure_board(_executive_pressure_placeholder_rows(), advisor_rows=advisor_rows)
        _render_executive_priority_board(pd.DataFrame(), days=int(days), advisor_rows=advisor_rows)
        _render_loaded_advisor_overlay(advisor_rows)
        _render_observability_source_status(board)
        return

    current_spend = _obs_value(board, "Credits Used", column="VALUE_USD")
    spend_delta = _obs_value(board, "Spend Delta", column="VALUE_USD")
    cortex_spend = _obs_value(board, "Cortex Spend", column="VALUE_USD")
    queries = _obs_value(board, "Total Queries")
    avg_runtime = _obs_value(board, "Avg Runtime")
    p95_runtime = _obs_value(board, "P95 Runtime")
    queue_seconds = _obs_value(board, "Queue Time")
    spill_gb = _obs_value(board, "Remote Spill")
    failed_queries = _obs_value(board, "Failed Queries")
    failed_tasks = _obs_value(board, "Failed Tasks")
    critical_high = _obs_value(board, "Critical High Alerts")
    open_actions = _obs_value(board, "Open Actions")
    storage_tb = _obs_value(board, "Storage")
    storage_cost = _obs_value(board, "Storage", column="VALUE_USD")
    health = _obs_value(board, "Platform Health")
    month_end_forecast = current_spend / max(int(days), 1) * 30.0
    avg_daily_spend = current_spend / max(int(days), 1)
    source_status = _obs_rows(board, "SOURCE_STATUS")
    unavailable_sources = (
        int(source_status["METRIC"].astype(str).eq("Unavailable").sum())
        if isinstance(source_status, pd.DataFrame) and not source_status.empty and "METRIC" in source_status.columns
        else 0
    )
    has_fact_trends = any(
        not _obs_rows(board, panel).empty
        for panel in (
            "DAILY_COST",
            "MONTHLY_COST",
            "DAILY_WORKLOAD",
            "COST_DRIVER",
            "QUERY_TYPE",
            "QUERY_DATABASE",
            "EXEC_STATUS",
            "WAREHOUSE_PRESSURE",
        )
    )
    status_state = "No Rows" if not has_fact_trends else (_platform_score_state(health) if health else "Loaded")
    status_headline = (
        "Executive summary schema loaded, but the mart has no recent fact rows for this scope."
        if not has_fact_trends
        else "Snowflake observability summary loaded from precomputed OVERWATCH facts."
    )
    loaded_advisor_count = safe_int(len(advisor_rows)) if isinstance(advisor_rows, pd.DataFrame) and not advisor_rows.empty else 0
    status_detail = (
        "Run or check the OVERWATCH mart refresh before using this view for leadership numbers."
        if not has_fact_trends
        else (
            f"{int(days)}-day view: cost, Cortex, query runtime, queue pressure, spill, task health, and storage. "
            f"{loaded_advisor_count:,} loaded advisor lane(s) are included from current session state. "
            "Alerts and action-queue counts remain On demand unless their secure app tables are available to this role. "
            "Detailed telemetry stays in the specialist sections."
        )
    )
    if unavailable_sources and has_fact_trends:
        status_detail = f"{status_detail} {unavailable_sources} optional source(s) are unavailable."

    render_shell_status_strip(
        state=status_state,
        headline=status_headline,
        detail=status_detail,
    )
    render_refresh_contract(
        payload,
        source="Executive summary facts",
        target_minutes=60,
        refresh_method="Scheduled data refresh",
        live_fallback="On demand",
    )
    st.markdown("**Snowflake Observability Wall**")
    render_shell_kpi_row((
        ("Platform", _platform_score_state(health) if health else "Loaded"),
        ("Spend", _obs_money_label(board, "Credits Used")),
        ("Delta", _obs_money_label(board, "Spend Delta", signed=True)),
        ("Cortex", _obs_money_label(board, "Cortex Spend")),
    ))
    render_shell_kpi_row((
        ("Queries", _obs_count_label(board, "Total Queries")),
        ("Avg Runtime", _format_seconds(avg_runtime) if _obs_metric_loaded(board, "Avg Runtime") else "On demand"),
        ("P95 Runtime", _format_seconds(p95_runtime) if _obs_metric_loaded(board, "P95 Runtime") else "On demand"),
        ("Remote Spill", _format_gb(spill_gb) if _obs_metric_loaded(board, "Remote Spill") else "On demand"),
    ))
    render_shell_kpi_row((
        ("Critical / High", _obs_count_label(board, "Critical High Alerts")),
        ("Failed Queries", _obs_count_label(board, "Failed Queries")),
        ("Failed Tasks", _obs_count_label(board, "Failed Tasks")),
        ("Open Actions", _obs_count_label(board, "Open Actions")),
    ))
    render_shell_kpi_row((
        ("Queue Time", _format_seconds(queue_seconds) if _obs_metric_loaded(board, "Queue Time") else "On demand"),
        ("30d Forecast", _money(month_end_forecast) if _obs_metric_loaded(board, "Credits Used") else "On demand"),
        ("Avg/day", _money(avg_daily_spend) if _obs_metric_loaded(board, "Credits Used") else "On demand"),
        ("Storage", f"{safe_float(storage_tb):,.2f} TB / {_money(storage_cost)}" if _obs_metric_loaded(board, "Storage") else "On demand"),
    ))
    _render_executive_command_summary(board, advisor_rows, days=int(days))
    _render_executive_pressure_board(board, advisor_rows=advisor_rows)
    _render_executive_priority_board(board, days=int(days), advisor_rows=advisor_rows)
    _render_loaded_advisor_overlay(advisor_rows)

    daily_cost = _obs_rows(board, "DAILY_COST").copy()
    monthly_cost = _obs_rows(board, "MONTHLY_COST").copy()
    daily_workload = _obs_rows(board, "DAILY_WORKLOAD").copy()
    cost_driver = _obs_rows(board, "COST_DRIVER").copy()
    query_mix = _obs_rows(board, "QUERY_TYPE").copy()
    query_database = _obs_rows(board, "QUERY_DATABASE").copy()
    exec_status = _obs_rows(board, "EXEC_STATUS").copy()
    warehouse_pressure = _obs_rows(board, "WAREHOUSE_PRESSURE").copy()

    chart_cols = st.columns(2)
    with chart_cols[0]:
        _render_line_chart(
            daily_cost,
            title="Daily Spend",
            y_column="VALUE_USD",
            y_title="Estimated Cost USD",
            height=210,
        )
    with chart_cols[1]:
        _render_bar_chart(
            monthly_cost,
            title="Monthly Spend Summary",
            x_column="DIMENSION",
            y_column="VALUE_USD",
            x_title="Estimated Cost USD",
            color="#71D3DC",
            height=210,
        )

    trend_cols = st.columns(2)
    with trend_cols[0]:
        _render_line_chart(
            daily_workload,
            title="Runtime and Queue Trend",
            y_column="VALUE",
            y_title="Seconds",
            color_column="METRIC",
            height=230,
        )
    with trend_cols[1]:
        _render_bar_chart(
            query_mix,
            title="Queries by Type",
            x_column="DIMENSION",
            y_column="VALUE",
            x_title="Queries",
            color="#10B981",
            height=230,
        )

    driver_cols = st.columns(3)
    with driver_cols[0]:
        _render_bar_chart(
            cost_driver,
            title="Top Cost Drivers",
            x_column="DIMENSION",
            y_column="VALUE_USD",
            x_title="Estimated Cost USD",
            color="#F59E0B",
            height=230,
        )
    with driver_cols[1]:
        _render_bar_chart(
            query_database,
            title="Queries by Database",
            x_column="DIMENSION",
            y_column="VALUE",
            x_title="Queries",
            color="#8B5CF6",
            height=230,
        )
    with driver_cols[2]:
        _render_bar_chart(
            exec_status,
            title="Execution Status",
            x_column="DIMENSION",
            y_column="VALUE",
            x_title="Queries",
            color="#EF4444",
            height=230,
        )

    pressure = warehouse_pressure.copy()
    if not pressure.empty:
        pressure["PRESSURE_VALUE"] = pd.to_numeric(pressure["VALUE"], errors="coerce").fillna(0)
        pressure = pressure.groupby("DIMENSION", as_index=False, sort=False)["PRESSURE_VALUE"].sum()
    _render_bar_chart(
        pressure,
        title="Warehouse Pressure: Queue + Spill",
        x_column="DIMENSION",
        y_column="PRESSURE_VALUE",
        x_title="Pressure",
        color="#F97316",
        height=260,
    )

    freshness = _obs_rows(board, "FRESHNESS")
    if isinstance(freshness, pd.DataFrame) and not freshness.empty:
        with st.expander("Summary data freshness", expanded=False):
            rows = freshness[["DIMENSION", "PERIOD_START", "UNIT"]].copy()
            rows = rows.rename(columns={"DIMENSION": "INPUT", "PERIOD_START": "LATEST_LOAD", "UNIT": "TYPE"})
            render_priority_dataframe(
                rows,
                title="Summary data freshness",
                priority_columns=["INPUT", "LATEST_LOAD", "TYPE"],
                raw_label="All executive summary freshness rows",
                height=180,
                max_rows=8,
            )
    _render_observability_source_status(board)

def _render_executive_operating_snapshot(
    summary: dict | None,
    *,
    credit_price: float,
    company: str,
    days: int,
) -> None:
    if not summary:
        metrics = (
            ("Scope", company),
            ("Window", f"{int(days)}d"),
            ("Rate", f"${safe_float(credit_price):,.2f}"),
            ("Telemetry", "On demand"),
        )
    else:
        metrics = (
            ("State", str(summary.get("state") or _platform_score_state(summary["score"]))),
            ("Spend", f"${credits_to_dollars(summary['current_credits'], credit_price):,.0f}"),
            ("Alerts", f"{summary['critical_high_alerts']:,}"),
            ("Data Gaps", f"{summary['migration_blockers']:,}"),
        )
    render_shell_kpi_row(metrics)


__all__ = ['_render_observability_source_status', '_render_executive_priority_board', '_render_executive_pressure_board', '_render_loaded_advisor_overlay', '_render_executive_command_summary', '_render_line_chart', '_render_bar_chart', '_render_executive_observability_board', '_render_executive_operating_snapshot']
