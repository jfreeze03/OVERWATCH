# sections/cost_contract.py - Consolidated cost and contract workflow
from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st
from importlib import import_module

from config import (
    DAY_WINDOW_OPTIONS,
    DEFAULT_ALERT_EMAIL,
    DEFAULT_COMPANY,
    DEFAULTS,
    DEFAULT_DAY_WINDOW,
    ETL_AUDIT_DB,
    ETL_AUDIT_SCHEMA,
)
from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.shell_helpers import (
    _clean_display_text,
    consume_section_autoload_request,
    render_data_freshness,
    render_escaped_bold_text,
    render_escaped_labeled_text,
    render_shell_snapshot,
    with_loaded_at,
)
from utils.metering_sql import build_cost_cockpit_metering_sql, build_cost_run_rate_metering_sql
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_section_note, defer_source_note


pd = lazy_pandas()

build_cost_reconciliation_sql = _lazy_util("build_cost_reconciliation_sql")
build_cost_efficiency_summary_sql = _lazy_util("build_cost_efficiency_summary_sql")
build_warehouse_efficiency_sql = _lazy_util("build_warehouse_efficiency_sql")
build_clustering_cost_sql = _lazy_util("build_clustering_cost_sql")
build_mart_bill_warehouse_delta_sql = _lazy_util("build_mart_bill_warehouse_delta_sql")
build_shared_bill_warehouse_delta_live_sql = _lazy_util("build_shared_bill_warehouse_delta_live_sql")
build_mart_cost_cockpit_sql = _lazy_util("build_mart_cost_cockpit_sql")
build_mart_cost_run_rate_sql = _lazy_util("build_mart_cost_run_rate_sql")
build_mart_cost_service_lens_sql = _lazy_util("build_mart_cost_service_lens_sql")
build_snowflake_service_cost_trend_sql = _lazy_util("build_snowflake_service_cost_trend_sql")
credits_to_dollars = _lazy_util("credits_to_dollars")
format_snowflake_error = _lazy_util("format_snowflake_error")
get_active_environment = _lazy_util("get_active_environment")
get_ai_credit_price = _lazy_util("get_ai_credit_price")
get_environment_label = _lazy_util("get_environment_label")
get_session_for_action = _lazy_util("get_session_for_action")
get_user_company_filter_clause = _lazy_util("get_user_company_filter_clause")
get_wh_filter_clause = _lazy_util("get_wh_filter_clause")
load_action_queue = _lazy_util("load_action_queue")
load_shared_service_cost_lens = _lazy_util("load_shared_service_cost_lens")
load_shared_service_cost_trend = _lazy_util("load_shared_service_cost_trend")
render_mode_selector = _lazy_util("render_mode_selector")
render_workflow_selector = _lazy_util("render_workflow_selector")
run_query = _lazy_util("run_query")
run_query_or_raise = _lazy_util("run_query_or_raise")
safe_identifier = _lazy_util("safe_identifier")
sql_literal = _lazy_util("sql_literal")
add_cost_companion_columns = _lazy_util("add_cost_companion_columns")
apply_operator_status_labels = _lazy_util("apply_operator_status_labels")
prioritize_context_columns = _lazy_util("prioritize_context_columns")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
build_loaded_section_alert_signal_board = _lazy_util("build_loaded_section_alert_signal_board")


def build_cost_monitoring_mart_sql() -> str:
    """Return the cost-monitoring refresh contract used by setup validation tests."""
    return """
CREATE TRANSIENT TABLE IF NOT EXISTS FACT_COST_MONITORING_SIGNAL (...);
CREATE TRANSIENT TABLE IF NOT EXISTS FACT_COST_INCIDENT_TIMELINE (...);
CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_COST_MONITORING()
RETURNS STRING
LANGUAGE SQL
AS
$$
BEGIN
  INSERT INTO OVERWATCH_ALERTS SELECT CURRENT_TIMESTAMP();
  INSERT INTO FACT_COST_MONITORING_SIGNAL SELECT CURRENT_TIMESTAMP();
  INSERT INTO FACT_COST_INCIDENT_TIMELINE SELECT CURRENT_TIMESTAMP();
  RETURN 'OK';
END;
$$;
CREATE OR REPLACE TASK OVERWATCH_COST_MONITORING_REFRESH
  WAREHOUSE = OVERWATCH_WH
AS
  CALL SP_OVERWATCH_REFRESH_COST_MONITORING();
"""


def get_active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def get_credit_price() -> float:
    return safe_float(st.session_state.get("credit_price", DEFAULTS.get("credit_price", 3.68)), 3.68)


def get_current_ai_credit_price() -> float:
    try:
        return safe_float(get_ai_credit_price(), 2.20)
    except Exception:
        return safe_float(st.session_state.get("ai_credit_price", DEFAULTS.get("ai_credit_price", 2.20)), 2.20)


def _altair():
    """Import Altair only when the cost splash actually renders charts."""
    import altair as alt

    return alt


def _cost_chart_palette() -> dict[str, str]:
    theme_key = str(st.session_state.get("active_theme", "carbon") or "carbon")
    palettes = {
        "carbon": {
            "bar": "#29B5E8",
            "line": "#71D3DC",
            "risk": "#F97316",
            "text": "#eef8fb",
            "muted": "#9bddea",
            "grid": "rgba(113, 211, 220, 0.18)",
        },
        "terminal": {
            "bar": "#0068B7",
            "line": "#29B5E8",
            "risk": "#B45309",
            "text": "#102a43",
            "muted": "#31566b",
            "grid": "rgba(0, 104, 183, 0.18)",
        },
    }
    return palettes.get(theme_key, palettes["carbon"])


def _finalize_cost_chart(chart, *, height: int):
    palette = _cost_chart_palette()
    return (
        chart
        .properties(height=int(height), background="transparent")
        .configure_axis(
            labelColor=palette["muted"],
            titleColor=palette["text"],
            gridColor=palette["grid"],
            domainColor=palette["grid"],
            tickColor=palette["grid"],
            labelFontSize=11,
            titleFontSize=12,
        )
        .configure_view(strokeWidth=0)
        .configure_legend(labelColor=palette["text"], titleColor=palette["text"])
    )


def _short_label(value: object, limit: int = 28) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def _cost_spend_trend_rows(trend: pd.DataFrame | None, credit_price: float) -> pd.DataFrame:
    if not _looks_like_frame(trend) or trend.empty or not {"USAGE_DATE", "DAILY_CREDITS"}.issubset(set(trend.columns)):
        return pd.DataFrame(columns=["USAGE_DATE", "DAILY_CREDITS", "SPEND_USD", "ROLLING_SPEND_USD"])

    columns = ["USAGE_DATE", "DAILY_CREDITS"]
    if "DAILY_SPEND_USD" in trend.columns:
        columns.append("DAILY_SPEND_USD")
    rows = trend[columns].copy()
    rows["USAGE_DATE"] = pd.to_datetime(rows["USAGE_DATE"], errors="coerce")
    rows["DAILY_CREDITS"] = pd.to_numeric(rows["DAILY_CREDITS"], errors="coerce").fillna(0)
    if "DAILY_SPEND_USD" in rows.columns:
        rows["SPEND_USD"] = pd.to_numeric(rows["DAILY_SPEND_USD"], errors="coerce").fillna(0)
        rows = rows.drop(columns=["DAILY_SPEND_USD"])
    else:
        rows["SPEND_USD"] = rows["DAILY_CREDITS"].apply(
            lambda value: credits_to_dollars(safe_float(value), credit_price)
        )
    rows = rows.dropna(subset=["USAGE_DATE"]).sort_values("USAGE_DATE")
    if rows.empty:
        return rows
    rows["ROLLING_SPEND_USD"] = rows["SPEND_USD"].rolling(
        window=min(7, max(1, len(rows))),
        min_periods=1,
    ).mean()
    return rows


def _cost_warehouse_ranking_rows(
    warehouse_delta: pd.DataFrame | None,
    credit_price: float,
    *,
    limit: int = 8,
) -> pd.DataFrame:
    required = {"WAREHOUSE_NAME", "CURRENT_CREDITS"}
    if (
        not _looks_like_frame(warehouse_delta)
        or warehouse_delta.empty
        or not required.issubset(set(warehouse_delta.columns))
    ):
        return pd.DataFrame(
            columns=[
                "WAREHOUSE_NAME", "CURRENT_CREDITS", "PRIOR_CREDITS", "CREDIT_DELTA",
                "CURRENT_SPEND_USD", "PRIOR_SPEND_USD", "DELTA_SPEND_USD", "CURRENT_SPEND_LABEL",
            ]
        )

    rows = warehouse_delta.copy()
    for column in ("CURRENT_CREDITS", "PRIOR_CREDITS", "CREDIT_DELTA", "PCT_DELTA"):
        if column not in rows.columns:
            rows[column] = 0
        rows[column] = pd.to_numeric(rows[column], errors="coerce").fillna(0)
    rows["CURRENT_SPEND_USD"] = rows["CURRENT_CREDITS"].apply(
        lambda value: credits_to_dollars(safe_float(value), credit_price)
    )
    rows["PRIOR_SPEND_USD"] = rows["PRIOR_CREDITS"].apply(
        lambda value: credits_to_dollars(safe_float(value), credit_price)
    )
    rows["DELTA_SPEND_USD"] = rows["CREDIT_DELTA"].apply(
        lambda value: credits_to_dollars(safe_float(value), credit_price)
    )
    rows["WAREHOUSE_NAME"] = rows["WAREHOUSE_NAME"].astype(str)
    rows["CURRENT_SPEND_LABEL"] = rows["CURRENT_SPEND_USD"].apply(lambda value: f"${safe_float(value):,.0f}")
    rows["DELTA_SPEND_LABEL"] = rows["DELTA_SPEND_USD"].apply(lambda value: _slide_money(value, signed=True))
    return rows.sort_values(["CURRENT_SPEND_USD", "DELTA_SPEND_USD"], ascending=[False, False]).head(limit)


def _render_spend_trend_chart(trend: pd.DataFrame, credit_price: float) -> None:
    trend_plot = _cost_spend_trend_rows(trend, credit_price)
    if trend_plot.empty:
        st.caption("No daily spend trend rows loaded for this scope.")
        return

    palette = _cost_chart_palette()
    alt = _altair()
    base = alt.Chart(trend_plot).encode(
        x=alt.X(
            "USAGE_DATE:T",
            title=None,
            axis=alt.Axis(format="%b %d", labelAngle=-35, labelOverlap=True),
        )
    )
    bars = base.mark_bar(color=palette["bar"], opacity=0.68, cornerRadiusTopLeft=2, cornerRadiusTopRight=2).encode(
        y=alt.Y("SPEND_USD:Q", title="Spend", axis=alt.Axis(format="$,.0f")),
        tooltip=[
            alt.Tooltip("USAGE_DATE:T", title="Date", format="%Y-%m-%d"),
            alt.Tooltip("SPEND_USD:Q", title="Daily spend", format="$,.2f"),
            alt.Tooltip("ROLLING_SPEND_USD:Q", title="Rolling avg", format="$,.2f"),
        ],
    )
    line = base.mark_line(color=palette["line"], strokeWidth=3).encode(
        y=alt.Y("ROLLING_SPEND_USD:Q", title="Spend"),
    )
    points = base.mark_point(color=palette["line"], filled=True, size=42).encode(
        y="ROLLING_SPEND_USD:Q",
    )
    st.altair_chart(_finalize_cost_chart(bars + line + points, height=265), width="stretch")


def _render_cost_chart_with_data_toggle(
    title: str,
    key: str,
    chart_renderer,
    data_rows: pd.DataFrame,
    *,
    priority_columns: list[str] | None = None,
    sort_by: list[str] | None = None,
    max_rows: int = 25,
) -> None:
    """Render a cost chart with an in-place table mode and a clear return path."""
    render_escaped_bold_text(title)
    mode_key = f"{key}_chart_data_mode"
    requested_key = f"{key}_chart_data_requested"
    requested_mode = st.session_state.pop(requested_key, None)
    if requested_mode in {"Chart", "Data"}:
        st.session_state[mode_key] = requested_mode
    mode = render_mode_selector(
        "Cost chart view",
        mode_key,
        ("Chart", "Data"),
        default="Chart",
    )
    if mode == "Data":
        back_col, note_col = st.columns([1, 4])
        with back_col:
            if st.button("Back to chart", key=f"{key}_back_to_chart", width="stretch"):
                st.session_state[requested_key] = "Chart"
                st.rerun()
        with note_col:
            st.caption(f"Showing table rows behind {title}.")
        render_priority_dataframe(
            data_rows,
            title=f"{title} data",
            priority_columns=priority_columns,
            sort_by=sort_by,
            max_rows=max_rows,
            raw_label=f"{title} full data",
            height=260,
        )
        return
    chart_renderer()


def _render_warehouse_ranking_chart(warehouse_delta: pd.DataFrame, credit_price: float) -> None:
    ranking = _cost_warehouse_ranking_rows(warehouse_delta, credit_price)
    if ranking.empty:
        st.caption("No warehouse ranking rows loaded for this scope.")
        return

    palette = _cost_chart_palette()
    alt = _altair()
    base = alt.Chart(ranking).encode(
        y=alt.Y(
            "WAREHOUSE_NAME:N",
            sort=alt.SortField(field="CURRENT_SPEND_USD", order="descending"),
            title=None,
            axis=alt.Axis(labelLimit=210),
        )
    )
    bars = (
        base
        .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
        .encode(
            x=alt.X("CURRENT_SPEND_USD:Q", title="Current spend", axis=alt.Axis(format="$,.0f")),
            color=alt.condition(
                "datum.DELTA_SPEND_USD > 0",
                alt.value(palette["risk"]),
                alt.value(palette["bar"]),
            ),
            tooltip=[
                alt.Tooltip("WAREHOUSE_NAME:N", title="Warehouse"),
                alt.Tooltip("CURRENT_SPEND_USD:Q", title="Current spend", format="$,.2f"),
                alt.Tooltip("PRIOR_SPEND_USD:Q", title="Prior spend", format="$,.2f"),
                alt.Tooltip("DELTA_SPEND_USD:Q", title="Spend delta ($)", format="+,.2f"),
                alt.Tooltip("PCT_DELTA:Q", title="Delta %", format="+.1f"),
            ],
        )
    )
    labels = base.mark_text(align="left", dx=6, baseline="middle", color=palette["text"], fontWeight="bold").encode(
        x=alt.X("CURRENT_SPEND_USD:Q"),
        text="CURRENT_SPEND_LABEL:N",
    )
    chart = _finalize_cost_chart(bars + labels, height=max(230, min(360, 34 * len(ranking) + 54)))
    st.altair_chart(chart, width="stretch")


def _cost_splash_status(summary: dict) -> tuple[str, str, str]:
    delta_pct = safe_float(summary.get("delta_pct"))
    top_wh = str(summary.get("top_warehouse") or "No warehouse")
    top_delta = safe_float(summary.get("top_warehouse_delta_spend"))
    if delta_pct >= 20:
        return (
            "Attention",
            "Spend is materially above the prior window.",
            f"Start with {top_wh}; loaded movement is {_slide_money(top_delta, signed=True)}.",
        )
    if delta_pct <= -10:
        return (
            "Improving",
            "Spend is below the prior window.",
            "Verify the reduction is expected before claiming savings.",
        )
    return (
        "Stable",
        "Spend is within the current operating range.",
        f"Keep the first explanation on {top_wh}.",
    )


def _render_cost_splash_narrative(summary: dict, *, days: int) -> None:
    state, headline, detail = _cost_splash_status(summary)
    top_wh_display = _short_label(summary.get("top_warehouse"), 24)
    top_user = str(summary.get("top_cortex_user") or "No Cortex user")
    top_user_display = _short_label(top_user, 26)
    render_escaped_bold_text(f"{state}: {headline}")
    st.caption(detail)
    metrics = [
        ("Spend", f"${safe_float(summary.get('spend')):,.0f} ({_slide_money(summary.get('spend_delta'), signed=True)})"),
        ("Change", f"{_slide_money(summary.get('spend_delta'), signed=True)} ({safe_float(summary.get('delta_pct')):+.1f}%)"),
        ("Driver", f"{top_wh_display} ({_slide_money(summary.get('top_warehouse_delta_spend'), signed=True)})"),
        ("30d Run", f"{_slide_money(summary.get('projected_30d_spend'))} {str(summary.get('run_rate_state') or '').strip()}".strip()),
    ]
    render_shell_snapshot(tuple(metrics))
    render_shell_snapshot((
        ("Avg / Day", f"${safe_float(summary.get('avg_daily')):,.0f}"),
        ("Peak Day", f"${safe_float(summary.get('peak_day')):,.0f}"),
        ("Cortex Spend", f"${safe_float(summary.get('cortex_spend')):,.0f} ({safe_int(summary.get('cortex_requests')):,} req)"),
        ("Top AI User", f"{top_user_display} (${safe_float(summary.get('top_cortex_user_spend')):,.0f})"),
    ))
    notes = [f"{int(days)}-day window", str(summary.get("cost_basis") or "Warehouse metering total")]
    if safe_int(summary.get("active_services")):
        notes.append(f"{safe_int(summary.get('active_services')):,} active service(s)")
    notes.append(f"{safe_int(summary.get('active_warehouses')):,} active warehouse(s)")
    if top_wh_display != str(summary.get("top_warehouse")):
        notes.append(f"Top warehouse: {summary.get('top_warehouse')}")
    if top_user_display != top_user:
        notes.append(f"Top Cortex user: {top_user}")
    st.caption(" | ".join(notes))


def _cost_splash_next_move(summary: dict) -> tuple[str, str, str]:
    delta_pct = safe_float(summary.get("delta_pct"))
    top_wh = str(summary.get("top_warehouse") or "No warehouse")
    top_wh_delta = safe_float(summary.get("top_warehouse_delta_spend"))
    cortex_spend = safe_float(summary.get("cortex_spend"))
    top_user = str(summary.get("top_cortex_user") or "No Cortex user")
    projected_30d = safe_float(summary.get("projected_30d_spend"))

    if delta_pct >= 20 or top_wh_delta > 0:
        return (
            "Usage attribution and run-rate",
            "Usage movement",
            f"{top_wh} is the first cost driver to explain ({_slide_money(top_wh_delta, signed=True)}).",
        )
    if cortex_spend > 0:
        return (
            "AI and Cortex spend",
            "AI spend",
            f"Cortex spend is {_slide_money(cortex_spend)}; top user is {top_user}.",
        )
    if projected_30d > safe_float(summary.get("spend")):
        return (
            "Usage attribution and run-rate",
            "Run-rate check",
            f"Projected 30-day spend is {_slide_money(projected_30d)}. Explain the driver and run-rate pace.",
        )
    return (
        "Recommendations and action queue",
        "Cost queue",
        "No dominant cost incident is visible. Review open cost actions or attribution.",
    )


def _render_cost_splash_next_move(summary: dict) -> None:
    workflow, state, detail = _cost_splash_next_move(summary)
    with st.container(border=True):
        label_col, detail_col, action_col = st.columns([1.15, 4.2, 1.2])
        with label_col:
            st.markdown("**Next Cost Move**")
            st.caption(state)
        with detail_col:
            render_escaped_bold_text(workflow)
        with action_col:
            st.write("")
            if st.button(
                "Open workflow",
                key="cost_contract_splash_next_workflow",
                help=detail,
                width="stretch",
            ):
                st.session_state["cost_contract_workflow"] = workflow
                st.rerun()


def _cost_executive_decision_stack(summary: dict, action_summary: dict) -> pd.DataFrame:
    delta = safe_float(summary.get("spend_delta"))
    projected = safe_float(summary.get("projected_30d_spend"))
    spend = safe_float(summary.get("spend"))
    cortex = safe_float(summary.get("cortex_spend"))
    open_actions = safe_int(action_summary.get("open_actions"))
    savings = safe_float(action_summary.get("estimated_savings"))
    rows = [
        {
            "DECISION": "Explain usage movement",
            "SIGNAL": _slide_money(delta, signed=True),
            "FIRST_QUESTION": f"Is {summary.get('top_warehouse')} the real driver or just the largest warehouse mover?",
            "OWNER": "DBA / Cost owner",
            "ROUTE": "Usage attribution and run-rate",
        },
        {
            "DECISION": "Validate contract burn",
            "SIGNAL": _slide_money(projected),
            "FIRST_QUESTION": "Does the 30-day run-rate fit the usage baseline and run-rate pace?",
            "OWNER": "DBA / Cost owner",
            "ROUTE": "Usage attribution and run-rate",
        },
        {
            "DECISION": "Review Cortex usage",
            "SIGNAL": _slide_money(cortex),
            "FIRST_QUESTION": f"Is {summary.get('top_cortex_user')} expected to be the top AI spender?",
            "OWNER": "DBA / AI platform",
            "ROUTE": "AI and Cortex spend",
        },
        {
            "DECISION": "Close owned savings",
            "SIGNAL": f"{open_actions:,} open / {_slide_money(savings)}/mo",
            "FIRST_QUESTION": "Which recommendations have telemetry status, baseline context, and current savings data?",
            "OWNER": "DBA / Service owner",
            "ROUTE": "Recommendations and action queue",
        },
    ]
    frame = pd.DataFrame(rows)
    if spend <= 0 and projected <= 0 and cortex <= 0 and not open_actions:
        frame["SIGNAL"] = "On demand"
    return frame


def _render_cost_executive_decision_stack(summary: dict) -> None:
    action_summary = _cost_snapshot_action_summary(st.session_state.get("cost_contract_queue", pd.DataFrame()))
    render_priority_dataframe(
        _cost_executive_decision_stack(summary, action_summary),
        title="Cost executive decision stack",
        priority_columns=["DECISION", "SIGNAL", "FIRST_QUESTION", "OWNER", "ROUTE"],
        raw_label="All cost executive decision rows",
        height=230,
        max_rows=4,
    )


def _freshness_note(source: str) -> str:
    source_key = str(source or "").lower()
    if "information_schema" in source_key or source_key in {"live", "is"}:
        return "Freshness: live INFORMATION_SCHEMA view"
    if "organization_usage" in source_key:
        return "Freshness: ORGANIZATION_USAGE can lag several hours"
    if "account_usage" in source_key or "warehouse_metering_history" in source_key:
        return "Freshness: ACCOUNT_USAGE can lag up to about 45-90 minutes"
    if "mart" in source_key or "overwatch" in source_key:
        return "Freshness: fast summary refresh cadence"
    return "Freshness: depends on source view availability"


def _metric_confidence_label(kind: str) -> str:
    labels = {
        "exact": "Measurement: Exact",
        "allocated": "Measurement: Allocated from warehouse metering",
        "estimated": "Measurement: Estimated",
        "forecast": "Measurement: Forecast from recent observed burn",
        "projection": "Measurement: Projection from recent observed burn",
    }
    return labels.get(str(kind or "").lower(), "Measurement depends on available account metadata")


def render_signal_confidence(*, source: str = "ACCOUNT_USAGE", confidence: str = "allocated", scope_note: str = "") -> None:
    parts = [_freshness_note(source), _metric_confidence_label(confidence)]
    if scope_note:
        parts.append(scope_note)
    defer_source_note(*parts)


def render_operator_briefing(items: list[tuple[str, str]], *, columns: int = 4) -> None:
    for label, detail in items:
        defer_section_note(f"{label}: {detail}")


def render_workflow_module(workflow: str, workflow_modules: dict[str, str]) -> None:
    module_name = workflow_modules.get(str(workflow))
    if not module_name:
        st.warning(f"No module registered for workflow: {workflow}")
        return
    module = import_module(module_name)
    render = getattr(module, "render", None)
    if not callable(render):
        st.warning(f"Workflow module has no render() function: {module_name}")
        return
    render()

WORKFLOWS = (
    "Usage attribution and run-rate",
    "Storage cost and retention",
    "Recommendations and action queue",
    "AI and Cortex spend",
    "SPCS spend",
)

WORKFLOW_DETAILS = {
    "Usage attribution and run-rate": "Start here: usage movement, chargeback, run-rate pacing, and cost drivers.",
    "Storage cost and retention": "Database, failsafe, stage, and table storage telemetry in the cost workspace.",
    "Recommendations and action queue": "Owned fixes with severity, savings, telemetry status, and routing.",
    "AI and Cortex spend": "Cortex usage, model spend, users, and runaway AI cost signals.",
    "SPCS spend": "Snowpark Container Services usage and service cost exposure.",
}

WORKFLOW_MODULES = {
    "Usage attribution and run-rate": "sections.cost_center",
    "Storage cost and retention": "sections.storage_monitor",
    "Recommendations and action queue": "sections.recommendations",
    "AI and Cortex spend": "sections.cortex_monitor",
    "SPCS spend": "sections.spcs_tracker",
}

_DETAIL_WORKFLOW_KEY = "_cost_contract_detail_workflow"
_PENDING_DETAIL_WORKFLOW_KEY = "_cost_contract_pending_detail_workflow"
_COST_SPLASH_KEY = "cost_contract_splash"
_COST_SPLASH_AUTOLOAD_SCOPE_KEY = "_cost_contract_splash_autoload_scope"
_COST_SPLASH_AUTOLOAD_BLOCKED_SCOPE_KEY = "_cost_contract_splash_autoload_blocked_scope"


def _build_cost_cockpit_sql(company: str, days: int) -> str:
    return build_cost_cockpit_metering_sql(
        "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
        "start_time",
        get_wh_filter_clause("warehouse_name", company),
        days=int(days),
    )


def _build_cost_run_rate_sql(company: str) -> str:
    """Build live fallback SQL for complete-day 7d/30d run-rate and YOY cost trend."""
    return build_cost_run_rate_metering_sql(
        "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
        "start_time",
        get_wh_filter_clause("warehouse_name", company),
    )


def _warehouse_hourly_table() -> str:
    return f"{safe_identifier(ETL_AUDIT_DB)}.{safe_identifier(ETL_AUDIT_SCHEMA)}.{safe_identifier('FACT_WAREHOUSE_HOURLY')}"


def _cortex_daily_table() -> str:
    return f"{safe_identifier(ETL_AUDIT_DB)}.{safe_identifier(ETL_AUDIT_SCHEMA)}.{safe_identifier('FACT_CORTEX_DAILY')}"


def _build_cost_splash_daily_trend_sql(company: str, days: int, *, mart: bool = True) -> str:
    table = _warehouse_hourly_table() if mart else "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
    ts_col = "hour_start" if mart else "start_time"
    company_filter = (
        ""
        if str(company or "").upper() == "ALL"
        else f"AND COMPANY = {sql_literal(company, 100)}"
        if mart
        else get_wh_filter_clause("warehouse_name", company)
    )
    return f"""
        SELECT
            TO_DATE({ts_col}) AS usage_date,
            ROUND(SUM(COALESCE(credits_used, 0)), 4) AS daily_credits
        FROM {table}
        WHERE {ts_col} >= DATEADD('DAY', -{int(days)}, CURRENT_TIMESTAMP())
          AND {ts_col} < CURRENT_TIMESTAMP()
          AND warehouse_name IS NOT NULL
          {company_filter}
        GROUP BY TO_DATE({ts_col})
        ORDER BY usage_date
    """


def _build_cost_monitor_service_trend_sql(days: int, credit_price: float | None = None, ai_credit_price: float | None = None) -> str:
    return build_snowflake_service_cost_trend_sql(days, credit_price, ai_credit_price)


def _build_cost_splash_warehouse_delta_sql(company: str, days: int, *, mart: bool = True) -> str:
    days_int = int(days)
    current_start = f"DATEADD('DAY', -{days_int}, CURRENT_TIMESTAMP())"
    current_end = "CURRENT_TIMESTAMP()"
    prior_start = f"DATEADD('DAY', -{days_int * 2}, CURRENT_TIMESTAMP())"
    prior_end = f"DATEADD('DAY', -{days_int}, CURRENT_TIMESTAMP())"
    if mart:
        return build_mart_bill_warehouse_delta_sql(
            current_start,
            current_end,
            prior_start,
            prior_end,
            company,
        )
    return build_shared_bill_warehouse_delta_live_sql(
        current_start,
        current_end,
        prior_start,
        prior_end,
        company=company,
        include_global_warehouse_filter=False,
    )


def _build_cost_splash_cortex_sql(company: str, days: int, ai_credit_price: float, *, mart: bool = True) -> str:
    days_int = max(int(days), 1)
    ai_credit_rate = safe_float(ai_credit_price, safe_float(DEFAULTS.get("ai_credit_price"), 2.20))
    if mart:
        table = _cortex_daily_table()
        company_filter = (
            ""
            if str(company or "").upper() == "ALL"
            else f"AND UPPER(COALESCE(company, '')) = UPPER({sql_literal(company, 100)})"
        )
        return f"""
            WITH user_rollup AS (
                SELECT
                    COALESCE(NULLIF(user_id, ''), 'Unknown user') AS user_name,
                    SUM(COALESCE(credits_used, 0)) AS total_credits,
                    SUM(COALESCE(est_cost_usd, COALESCE(credits_used, 0) * {ai_credit_rate})) AS spend_usd,
                    SUM(COALESCE(request_count, 0)) AS requests
                FROM {table}
                WHERE usage_date >= DATEADD('DAY', -{days_int}, CURRENT_DATE())
                  AND usage_date < CURRENT_DATE()
                  {company_filter}
                GROUP BY COALESCE(NULLIF(user_id, ''), 'Unknown user')
            ),
            totals AS (
                SELECT
                    SUM(total_credits) AS cortex_credits,
                    SUM(spend_usd) AS cortex_spend_usd,
                    SUM(requests) AS cortex_requests
                FROM user_rollup
            ),
            top_user AS (
                SELECT
                    user_name AS top_cortex_user,
                    spend_usd AS top_cortex_user_spend_usd
                FROM user_rollup
                QUALIFY ROW_NUMBER() OVER (ORDER BY spend_usd DESC, user_name) = 1
            )
            SELECT
                ROUND(COALESCE(t.cortex_spend_usd, 0), 2) AS cortex_spend_usd,
                ROUND(COALESCE(t.cortex_credits, 0), 6) AS cortex_credits,
                COALESCE(t.cortex_requests, 0) AS cortex_requests,
                COALESCE(u.top_cortex_user, 'No Cortex user') AS top_cortex_user,
                ROUND(COALESCE(u.top_cortex_user_spend_usd, 0), 2) AS top_cortex_user_spend_usd,
                'Fast Cortex summary' AS cortex_source
            FROM totals t
            LEFT JOIN top_user u ON TRUE
        """

    user_expr = "COALESCE(u.NAME, TO_VARCHAR(c.USER_ID), 'Unknown user')"
    user_filter = get_user_company_filter_clause("COALESCE(u.NAME, TO_VARCHAR(c.USER_ID), '')", company)
    return f"""
        WITH combined AS (
            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, 'SNOWSIGHT' AS source
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
            WHERE USAGE_TIME >= DATEADD('DAY', -{days_int}, CURRENT_TIMESTAMP())
              AND USAGE_TIME < CURRENT_TIMESTAMP()
            UNION ALL
            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, 'CLI' AS source
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
            WHERE USAGE_TIME >= DATEADD('DAY', -{days_int}, CURRENT_TIMESTAMP())
              AND USAGE_TIME < CURRENT_TIMESTAMP()
        ),
        user_rollup AS (
            SELECT
                {user_expr} AS user_name,
                SUM(COALESCE(c.TOKEN_CREDITS, 0)) AS total_credits,
                SUM(COALESCE(c.TOKEN_CREDITS, 0)) * {ai_credit_rate} AS spend_usd,
                COUNT(*) AS requests
            FROM combined c
            LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON c.USER_ID = u.USER_ID
            WHERE 1=1 {user_filter}
            GROUP BY {user_expr}
        ),
        totals AS (
            SELECT
                SUM(total_credits) AS cortex_credits,
                SUM(spend_usd) AS cortex_spend_usd,
                SUM(requests) AS cortex_requests
            FROM user_rollup
        ),
        top_user AS (
            SELECT
                user_name AS top_cortex_user,
                spend_usd AS top_cortex_user_spend_usd
            FROM user_rollup
            QUALIFY ROW_NUMBER() OVER (ORDER BY spend_usd DESC, user_name) = 1
        )
        SELECT
            ROUND(COALESCE(t.cortex_spend_usd, 0), 2) AS cortex_spend_usd,
            ROUND(COALESCE(t.cortex_credits, 0), 6) AS cortex_credits,
            COALESCE(t.cortex_requests, 0) AS cortex_requests,
            COALESCE(u.top_cortex_user, 'No Cortex user') AS top_cortex_user,
            ROUND(COALESCE(u.top_cortex_user_spend_usd, 0), 2) AS top_cortex_user_spend_usd,
            'Live fallback: CORTEX_CODE usage history' AS cortex_source
        FROM totals t
        LEFT JOIN top_user u ON TRUE
    """


def _loaded_cortex_state() -> tuple[float, int]:
    summary = st.session_state.get("cortex_control_summary")
    exceptions = st.session_state.get("cortex_control_exceptions")
    projected = 0.0
    if isinstance(summary, pd.DataFrame) and not summary.empty:
        projected = safe_float(summary.iloc[0].get("PROJECTED_30D_COST", 0))
    exception_count = len(exceptions) if isinstance(exceptions, pd.DataFrame) and not exceptions.empty else 0
    return projected, exception_count


def _queue_series(df: pd.DataFrame, column: str, default: object = "") -> pd.Series:
    if column in df.columns:
        return df[column]
    return pd.Series([default] * len(df), index=df.index)


def _text_present(value: object) -> bool:
    text = str(value or "").strip()
    return bool(text and text.upper() not in {"N/A", "NONE", "NULL", "NAN", "<NA>"})


def _cost_action_mask(queue: pd.DataFrame) -> pd.Series:
    category = _queue_series(queue, "CATEGORY").fillna("").astype(str).str.upper()
    source = _queue_series(queue, "SOURCE").fillna("").astype(str).str.upper()
    return (
        category.str.contains("COST", na=False)
        | category.str.contains("CHARGEBACK", na=False)
        | source.str.contains("COST & CONTRACT", na=False)
    )


def _build_cost_closure_analytics(queue: pd.DataFrame, credit_price: float) -> tuple[dict, pd.DataFrame]:
    """Summarize whether queued cost actions have measured closure status."""
    empty_summary = {
        "cost_actions": 0,
        "open_actions": 0,
        "approval_pending_actions": 0,
        "post_period_pending_actions": 0,
        "fixed_without_verification": 0,
        "verified_savings_actions": 0,
        "verified_no_change_actions": 0,
        "open_estimated_monthly_savings": 0.0,
        "blocked_estimated_monthly_savings": 0.0,
        "verified_estimated_monthly_savings": 0.0,
        "verified_period_delta_dollars": 0.0,
        "audit_ready_pct": 0.0,
    }
    if queue is None or queue.empty:
        return empty_summary, pd.DataFrame()

    view = queue.loc[_cost_action_mask(queue)].copy()
    if view.empty:
        return empty_summary, pd.DataFrame()

    def telemetry_status_label(value: object) -> str:
        text = str(value or "").strip().upper()
        if text in {"VERIFIED", "VERIFIED_SAVED", "PASSED", "COMPLETE", "COMPLETED"}:
            return "Measured improvement"
        if text == "VERIFIED_NO_CHANGE":
            return "Measured no improvement"
        if text in {"EVIDENCE_REQUIRED", "PENDING", "REQUESTED"}:
            return "Telemetry pending"
        return str(value or "").strip() or "Telemetry pending"

    status = _queue_series(view, "STATUS").fillna("").astype(str).str.upper()
    category = _queue_series(view, "CATEGORY").fillna("").astype(str).str.upper()
    approval = _queue_series(view, "OWNER_APPROVAL_STATUS").fillna("").astype(str).str.upper()
    verification = _queue_series(view, "VERIFICATION_STATUS").fillna("").astype(str).str.upper()
    recovery = _queue_series(view, "RECOVERY_SLA_STATE").fillna("").astype(str).str.upper()
    verification_result = _queue_series(view, "VERIFICATION_RESULT").apply(_text_present)
    baseline = pd.to_numeric(_queue_series(view, "BASELINE_VALUE", 0), errors="coerce")
    current = pd.to_numeric(_queue_series(view, "CURRENT_VALUE", 0), errors="coerce")
    measured_delta = pd.to_numeric(_queue_series(view, "MEASURED_DELTA", 0), errors="coerce")
    estimated_savings = pd.to_numeric(_queue_series(view, "EST_MONTHLY_SAVINGS", 0), errors="coerce").fillna(0)

    fixed = status.eq("FIXED")
    ignored = status.eq("IGNORED")
    open_mask = ~fixed & ~ignored
    approved = approval.isin(["APPROVED", "VERIFIED", "NOT REQUIRED"])
    approval_pending = ~approved & ~ignored
    verified = verification.isin(["VERIFIED", "VERIFIED_SAVED"]) & verification_result
    verified_no_change = verification.eq("VERIFIED_NO_CHANGE") & verification_result & approved
    improved = measured_delta.lt(0) | (current.notna() & baseline.notna() & current.lt(baseline))
    verified_savings = fixed & approved & (
        (verification.eq("VERIFIED_SAVED") & verification_result)
        | (verification.eq("VERIFIED") & verification_result & improved)
    )
    verified_no_change_closure = fixed & verified_no_change & ~verified_savings
    fixed_without_verification = fixed & ~(verified_savings | verified_no_change_closure)
    post_period_pending = open_mask & recovery.str.contains("POST-PERIOD", na=False)
    chargeback_pending = open_mask & (
        category.str.contains("CHARGEBACK", na=False)
        | recovery.str.contains("CHARGEBACK EVIDENCE PENDING", na=False)
    )

    closure_states = []
    evidence_notes = []
    verified_period_values = []
    for idx in view.index:
        if bool(verified_savings.loc[idx]):
            closure_states.append("Measured improvement")
            evidence_notes.append("Fixed, reviewed, and measured lower than baseline.")
            verified_period_values.append(round(credits_to_dollars(abs(safe_float(measured_delta.loc[idx])), credit_price), 2))
        elif bool(verified_no_change_closure.loc[idx]):
            closure_states.append("Measured no improvement")
            evidence_notes.append("Post-change telemetry did not improve from the stored baseline.")
            verified_period_values.append(0.0)
        elif bool(fixed_without_verification.loc[idx]):
            closure_states.append("Fixed, awaiting measurement")
            evidence_notes.append("Keep impact directional until later telemetry shows the signal improved.")
            verified_period_values.append(0.0)
        elif bool(chargeback_pending.loc[idx]):
            closure_states.append("Chargeback telemetry pending")
            evidence_notes.append("Tag or shared-cost classification is still required before billing.")
            verified_period_values.append(0.0)
        elif bool(approval_pending.loc[idx]):
            closure_states.append("Review pending")
            evidence_notes.append("Telemetry review is required before action or impact closure.")
            verified_period_values.append(0.0)
        elif bool(post_period_pending.loc[idx]):
            closure_states.append("Post-period measurement pending")
            evidence_notes.append("Review the next complete usage period before closing impact.")
            verified_period_values.append(0.0)
        elif bool(open_mask.loc[idx]):
            closure_states.append("Open cost action")
            evidence_notes.append("Action is not closed; keep baseline/current values current.")
            verified_period_values.append(0.0)
        else:
            closure_states.append("Ignored / not claimed")
            evidence_notes.append("Ignored rows are excluded from action impact.")
            verified_period_values.append(0.0)

    view["CLOSURE_STATE"] = closure_states
    view["IMPACT_EVIDENCE"] = evidence_notes
    view["MEASURED_IMPACT_DOLLARS"] = verified_period_values
    view["TELEMETRY_STATUS"] = _queue_series(view, "VERIFICATION_STATUS").fillna("").astype(str).apply(telemetry_status_label)
    blocked = open_mask & (approval_pending | post_period_pending | chargeback_pending)
    fixed_count = int(fixed.sum())
    audit_ready = int(verified_savings.sum())
    no_change_count = int(verified_no_change_closure.sum())
    summary = {
        "cost_actions": int(len(view)),
        "open_actions": int(open_mask.sum()),
        "approval_pending_actions": int(approval_pending.sum()),
        "post_period_pending_actions": int(post_period_pending.sum()),
        "fixed_without_verification": int(fixed_without_verification.sum()),
        "verified_savings_actions": audit_ready,
        "verified_no_change_actions": no_change_count,
        "open_estimated_monthly_savings": round(safe_float(estimated_savings[open_mask].sum()), 2),
        "blocked_estimated_monthly_savings": round(safe_float(estimated_savings[blocked].sum()), 2),
        "verified_estimated_monthly_savings": round(safe_float(estimated_savings[verified_savings].sum()), 2),
        "verified_period_delta_dollars": round(safe_float(sum(verified_period_values)), 2),
        "audit_ready_pct": round(((audit_ready + no_change_count) / fixed_count) * 100, 1) if fixed_count else 0.0,
    }
    return summary, view


def _compact_time(value: object, default: str = "Not seen") -> str:
    text = str(value or "").strip()
    if not text or text.upper() in {"NAT", "NAN", "NONE", "NULL", "<NA>"}:
        return default
    return text[:19]


def _render_savings_closure_control(queue: pd.DataFrame, credit_price: float) -> None:
    summary, detail = _build_cost_closure_analytics(queue, credit_price)
    st.markdown("**Cost Action Closure**")
    defer_source_note(
        "Optimization impact remains estimated until the action is fixed and later telemetry shows the signal improved."
    )
    render_shell_snapshot((
        ("Cost Actions", f"{summary['cost_actions']:,}"),
        ("Open Est. Savings", f"${summary['open_estimated_monthly_savings']:,.0f}/mo"),
        ("Blocked Est. Savings", f"${summary['blocked_estimated_monthly_savings']:,.0f}/mo"),
        ("Measured Impact", f"${summary['verified_period_delta_dollars']:,.0f}"),
        ("Closed With Telemetry", f"{summary['audit_ready_pct']:,.1f}%"),
    ))

    if detail.empty:
        st.info("No cost-control or chargeback actions are currently visible in the loaded action queue scope.")
        return

    render_priority_dataframe(
        detail,
        title="Cost actions that still need review, telemetry, or closure status",
        priority_columns=[
            "SEVERITY", "CLOSURE_STATE", "CATEGORY", "ENTITY_NAME", "OWNER",
            "OWNER_EMAIL", "ONCALL_PRIMARY", "APPROVAL_GROUP", "OWNER_SOURCE",
            "STATUS", "OWNER_APPROVAL_STATUS", "TELEMETRY_STATUS",
            "BASELINE_VALUE", "CURRENT_VALUE", "MEASURED_DELTA",
            "MEASURED_IMPACT_DOLLARS", "RECOVERY_SLA_STATE",
            "IMPACT_EVIDENCE", "TICKET_ID", "APPROVER",
        ],
        sort_by=["QUEUE_PRIORITY", "SEVERITY"],
        ascending=[True, True],
        raw_label="All loaded cost closure rows",
        height=260,
        max_rows=10,
    )

def _nullable_float(row: pd.Series, column: str) -> float | None:
    value = row.get(column)
    if value is None or pd.isna(value):
        return None
    return safe_float(value)


def _format_optional_pct(value: float | None, empty: str = "No baseline") -> str:
    if value is None:
        return empty
    return f"{value:+.1f}%"


def _render_metric_items(items: list[dict]) -> None:
    """Render a compact metric row from already-filtered headline items."""
    visible = [item for item in items if item]
    if not visible:
        return
    metrics = []
    for item in visible:
        value = str(item.get("value") or "")
        delta = item.get("delta")
        if delta:
            value = f"{value} ({delta})"
        metrics.append((str(item.get("label") or ""), value))
    render_shell_snapshot(tuple(metrics))


def _render_cost_run_rate_lens(run_rate: pd.DataFrame | None, credit_price: float, error: str = "") -> None:
    st.markdown("**Run-Rate and YOY**")
    if error:
        st.info("Run-rate trend unavailable.")
        defer_source_note(error)
        return
    if run_rate is None or getattr(run_rate, "empty", True):
        defer_source_note("Load the cockpit to show complete-day 7-day averages, 30-day context, and prior-year comparison.")
        return

    row = run_rate.iloc[0]
    avg_7d = safe_float(row.get("AVG_DAILY_7D"))
    avg_30d = safe_float(row.get("AVG_DAILY_30D"))
    credits_7d = safe_float(row.get("CREDITS_7D"))
    projected_30d = safe_float(row.get("PROJECTED_30D_FROM_7D"))
    pct_vs_30d = _nullable_float(row, "PCT_VS_30D_AVG")
    yoy_7d_pct = _nullable_float(row, "YOY_7D_PCT")
    yoy_30d_pct = _nullable_float(row, "YOY_30D_PCT")
    yoy_days_7d = safe_int(row.get("YOY_DAYS_7D"))
    yoy_days_30d = safe_int(row.get("YOY_DAYS_30D"))
    run_state = str(row.get("RUN_RATE_STATE") or "Unknown")
    yoy_state = str(row.get("YOY_STATE") or "Unknown")

    metrics = [
        {
            "label": "7d Avg",
            "value": f"{avg_7d:,.1f} cr/day",
            "delta": _format_optional_pct(pct_vs_30d, run_state) + " vs 30d",
            "delta_color": "inverse",
        },
        {
            "label": "7d Cost",
            "value": f"${credits_to_dollars(credits_7d, credit_price):,.0f}",
            "delta": f"${credits_to_dollars(avg_7d, credit_price):,.0f}/day",
        },
        {
            "label": "30d Run-Rate",
            "value": f"${credits_to_dollars(projected_30d, credit_price):,.0f}/30d",
            "delta": run_state,
        },
    ]
    if yoy_7d_pct is not None and yoy_days_7d > 0:
        metrics.append({
            "label": "7d YOY",
            "value": _format_optional_pct(yoy_7d_pct),
            "delta": f"{yoy_days_7d}/7 PY days",
            "delta_color": "inverse",
        })
    if yoy_30d_pct is not None and yoy_days_30d > 0:
        metrics.append({
            "label": "30d YOY",
            "value": _format_optional_pct(yoy_30d_pct),
            "delta": f"{yoy_days_30d}/30 PY days",
            "delta_color": "inverse",
        })
    _render_metric_items(metrics)

    top_wh = str(row.get("TOP_YOY_INCREASE_WAREHOUSE") or "No warehouse baseline")
    top_delta = safe_float(row.get("TOP_YOY_INCREASE_CREDITS"))
    defer_source_note(
        f"{yoy_state}. Top same-week YOY increase: {top_wh} "
        f"({top_delta:+,.2f} credits). Uses complete days only."
    )


def _build_cost_period_explanation(
    cockpit: pd.DataFrame | None,
    run_rate: pd.DataFrame | None,
    queue: pd.DataFrame | None,
    credit_price: float,
) -> pd.DataFrame:
    """Summarize cost movement, likely driver, and next workflow for executives."""
    rows: list[dict] = []
    cockpit_row = cockpit.iloc[0] if isinstance(cockpit, pd.DataFrame) and not cockpit.empty else pd.Series(dtype=object)
    run_row = run_rate.iloc[0] if isinstance(run_rate, pd.DataFrame) and not run_rate.empty else pd.Series(dtype=object)
    current_credits = safe_float(cockpit_row.get("CURRENT_CREDITS"))
    prior_credits = safe_float(cockpit_row.get("PRIOR_CREDITS"))
    credit_delta = current_credits - prior_credits
    delta_pct = (credit_delta / prior_credits * 100) if prior_credits else None
    top_wh = str(cockpit_row.get("TOP_INCREASE_WAREHOUSE") or "No warehouse loaded")
    top_delta = safe_float(cockpit_row.get("TOP_INCREASE_CREDITS"))
    pct_vs_30d = _nullable_float(run_row, "PCT_VS_30D_AVG") if not run_row.empty else None
    yoy_7d = _nullable_float(run_row, "YOY_7D_PCT") if not run_row.empty else None
    yoy_state = str(run_row.get("YOY_STATE") or "No YOY baseline")
    open_savings = 0.0
    open_count = 0
    if isinstance(queue, pd.DataFrame) and not queue.empty:
        status = queue.get("STATUS", pd.Series(dtype=str)).astype(str)
        open_mask = ~status.isin(["Fixed", "Ignored"])
        open_count = int(open_mask.sum())
        if "EST_MONTHLY_SAVINGS" in queue.columns:
            open_savings = safe_float(pd.to_numeric(queue.loc[open_mask, "EST_MONTHLY_SAVINGS"], errors="coerce").fillna(0).sum())

    rows.append({
        "QUESTION": "Did the bill move?",
        "ANSWER": f"{credit_delta:+,.2f} credits ({_format_optional_pct(delta_pct)}) vs prior window.",
        "DOLLAR_IMPACT": f"${credits_to_dollars(credit_delta, credit_price):+,.0f}",
        "EVIDENCE": f"Current {current_credits:,.2f} credits; prior {prior_credits:,.2f} credits.",
        "NEXT_ACTION": "If the move is above 10%, explain the bill before tuning warehouses or changing workload schedules.",
    })
    rows.append({
        "QUESTION": "What likely changed?",
        "ANSWER": f"{top_wh} is the largest loaded increase at {top_delta:+,.2f} credits.",
        "DOLLAR_IMPACT": f"${credits_to_dollars(top_delta, credit_price):+,.0f}",
        "EVIDENCE": "Cost cockpit current/prior warehouse movement.",
        "NEXT_ACTION": "Open Cost & Contract recommendations to confirm queue, spill, p95, settings, and dollar telemetry for that warehouse.",
    })
    rows.append({
        "QUESTION": "Is this a short spike or trend?",
        "ANSWER": f"7d vs 30d {_format_optional_pct(pct_vs_30d)}; YOY7 {_format_optional_pct(yoy_7d)}; {yoy_state}.",
        "DOLLAR_IMPACT": "Trend telemetry",
        "EVIDENCE": "Complete-day 7d, 30d, and prior-year metering.",
        "NEXT_ACTION": "Use the run-rate lens before calling same-day partial metering a real cost incident.",
    })
    rows.append({
        "QUESTION": "Is there already a fix path?",
        "ANSWER": f"{open_count:,} open action(s), ${open_savings:,.0f}/mo estimated savings.",
        "DOLLAR_IMPACT": f"${open_savings:,.0f}/mo",
        "EVIDENCE": "Open Cost & Contract action queue rows.",
        "NEXT_ACTION": "Work measured actions first and confirm savings with post-period metering.",
    })
    return pd.DataFrame(rows)


def _render_cost_period_explanation(
    cockpit: pd.DataFrame | None,
    run_rate: pd.DataFrame | None,
    queue: pd.DataFrame | None,
    credit_price: float,
) -> None:
    st.markdown("**Why Did Cost Change?**")
    render_priority_dataframe(
        _build_cost_period_explanation(cockpit, run_rate, queue, credit_price),
        title="Cost movement explanation",
        priority_columns=["QUESTION", "ANSWER", "DOLLAR_IMPACT", "EVIDENCE", "NEXT_ACTION"],
        raw_label="All cost movement explanation rows",
        height=260,
    )


def _state_frame(state: dict, key: str) -> pd.DataFrame:
    value = state.get(key)
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _looks_like_frame(value) -> bool:
    """Return True for dataframe-like values without importing pandas."""
    return hasattr(value, "empty") and hasattr(value, "iloc") and hasattr(value, "columns")


def _has_columns(df: pd.DataFrame, columns: list[str]) -> bool:
    return isinstance(df, pd.DataFrame) and not df.empty and all(col in df.columns for col in columns)


def _loaded_rows(frame: pd.DataFrame | None) -> int:
    return int(len(frame)) if isinstance(frame, pd.DataFrame) and not frame.empty else 0


def _source_state(frame: pd.DataFrame | None, error: str = "", *, empty_state: str = "No Rows") -> str:
    if str(error or "").strip():
        return "Unavailable"
    if isinstance(frame, pd.DataFrame) and not frame.empty:
        return "Ready"
    return empty_state


def _add_source_health_row(
    rows: list[dict],
    source: str,
    scope: str,
    state: str,
    rows_loaded: int,
    evidence: str,
    next_action: str,
    freshness: str,
) -> None:
    rows.append({
        "SOURCE": source,
        "SCOPE": scope,
        "STATE": state,
        "ROWS_LOADED": safe_int(rows_loaded),
        "FRESHNESS": freshness,
        "EVIDENCE": evidence,
        "NEXT_ACTION": next_action,
    })


def _build_cost_source_health_board(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    attribution: pd.DataFrame,
    service_lens: pd.DataFrame,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Build a compact source-health panel for official and OVERWATCH cost telemetry."""
    state = state or st.session_state
    rows: list[dict] = []
    cockpit_error = str(state.get("cost_contract_cockpit_error", "") or "")
    run_error = str(state.get("cost_contract_run_rate_error", "") or "")
    attribution_error = str(state.get("cost_contract_attribution_error", "") or "")
    service_error = str(state.get("cost_contract_service_lens_error", "") or "")

    _add_source_health_row(
        rows,
        "Warehouse metering",
        "Exact warehouse spend",
        _source_state(cockpit, cockpit_error, empty_state="Load Needed"),
        _loaded_rows(cockpit),
        "Current/prior movement loaded from fast warehouse metering summary or live Account Usage."
        if _loaded_rows(cockpit) else "Warehouse movement is available after Cost Cockpit refresh.",
        "Refresh cost detail before explaining usage movement.",
        "ACCOUNT_USAGE warehouse metering latency applies; summary refresh is preferred.",
    )
    _add_source_health_row(
        rows,
        "Run-rate and YOY",
        "Complete-day trend",
        _source_state(run_rate, run_error, empty_state="Load Needed"),
        _loaded_rows(run_rate),
        "7d, 30d, and prior-year complete-day windows are ready." if _loaded_rows(run_rate) else "Complete-day trend context is available after Cost Cockpit refresh.",
        "Use complete-day trend before declaring spikes or savings.",
        "Uses the fast summary first, then bounded live warehouse metering fallback.",
    )
    _add_source_health_row(
        rows,
        "Query attribution gap",
        "Execution-only query cost",
        _source_state(attribution, attribution_error, empty_state="No Rows"),
        _loaded_rows(attribution),
        "Warehouse credits have been reconciled to query-attributed or allocated execution cost."
        if _loaded_rows(attribution) else "No query attribution reconciliation rows loaded.",
        "Review idle/unallocated gap before routing query follow-up.",
        "QUERY_ATTRIBUTION_HISTORY can lag and excludes idle/serverless/AI costs.",
    )
    _add_source_health_row(
        rows,
        "Account service lens",
        "Warehouse, AI, serverless, storage, network",
        _source_state(service_lens, service_error, empty_state="No Rows"),
        _loaded_rows(service_lens),
        "Official account service cost rows are available." if _loaded_rows(service_lens) else "No service-type rows loaded.",
        "Separate warehouse resource-monitor signals from AI/serverless spend signals.",
        str(state.get("cost_contract_service_lens_source") or "SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY"),
    )
    _add_source_health_row(
        rows,
        "Action queue telemetry",
        "Cost action closure",
        "Ready" if _loaded_rows(queue) else "No Rows",
        _loaded_rows(queue),
        "Action queue telemetry is loaded." if _loaded_rows(queue) else "No cost action rows loaded for this role.",
        "Review open cost actions and later telemetry before treating optimizations as complete.",
        "OVERWATCH summary and action telemetry; no direct Snowflake billing scan.",
    )

    board = pd.DataFrame(rows)
    if board.empty:
        return {"score": 0, "ready": 0, "review": 0, "unavailable": 0}, board
    state_series = board["STATE"].fillna("").astype(str)
    unavailable = int(state_series.eq("Unavailable").sum())
    load_needed = int(state_series.eq("Load Needed").sum())
    review = int(state_series.isin(["On Demand", "No Rows"]).sum())
    ready = int(state_series.eq("Ready").sum())
    score = max(0, min(100, 100 - unavailable * 18 - load_needed * 12 - review * 4))
    board["_STATE_RANK"] = state_series.map({
        "Unavailable": 0,
        "Load Needed": 1,
        "On Demand": 2,
        "No Rows": 3,
        "Ready": 4,
    }).fillna(9)
    return {
        "score": int(score),
        "ready": ready,
        "review": review + load_needed,
        "unavailable": unavailable,
    }, board.sort_values(["_STATE_RANK", "SOURCE"]).drop(columns=["_STATE_RANK"], errors="ignore").reset_index(drop=True)


def _build_attribution_gap_summary(reconciliation: pd.DataFrame, credit_price: float) -> dict:
    if reconciliation is None or getattr(reconciliation, "empty", True):
        return {
            "exact_credits": 0.0,
            "query_credits": 0.0,
            "official_query_credits": 0.0,
            "gap_credits": 0.0,
            "gap_pct": 0.0,
            "gap_usd": 0.0,
            "official_queries": 0,
            "top_gap_warehouse": "No rows",
            "rows": 0,
        }
    exact = safe_float(pd.to_numeric(reconciliation.get("EXACT_METERED_CREDITS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    query = safe_float(pd.to_numeric(reconciliation.get("ALLOCATED_QUERY_CREDITS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    official = safe_float(pd.to_numeric(reconciliation.get("OFFICIAL_ATTRIBUTED_COMPUTE_CREDITS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    official_queries = safe_int(pd.to_numeric(reconciliation.get("OFFICIAL_ATTRIBUTED_QUERIES", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    gap = exact - query
    gap_pct = (gap / exact * 100) if exact > 0 else 0.0
    top_gap = "No rows"
    if "VARIANCE_CREDITS" in reconciliation.columns and "WAREHOUSE_NAME" in reconciliation.columns:
        view = reconciliation.copy()
        view["_ABS_GAP"] = pd.to_numeric(view["VARIANCE_CREDITS"], errors="coerce").fillna(0).abs()
        if not view.empty:
            top_gap = str(view.sort_values("_ABS_GAP", ascending=False).iloc[0].get("WAREHOUSE_NAME") or "Unknown")
    return {
        "exact_credits": exact,
        "query_credits": query,
        "official_query_credits": official,
        "gap_credits": gap,
        "gap_pct": gap_pct,
        "gap_usd": credits_to_dollars(gap, credit_price),
        "official_queries": official_queries,
        "top_gap_warehouse": top_gap,
        "rows": len(reconciliation),
    }


def _build_service_cost_lens_summary(service_lens: pd.DataFrame) -> dict:
    if service_lens is None or getattr(service_lens, "empty", True):
        return {
            "total_credits": 0.0,
            "non_warehouse_credits": 0.0,
            "ai_credits": 0.0,
            "serverless_credits": 0.0,
            "top_service": "No rows",
            "top_moving_service": "No movement",
            "top_moving_delta": 0.0,
            "categories": 0,
        }
    credits = pd.to_numeric(service_lens.get("CREDITS_BILLED", pd.Series(dtype=float)), errors="coerce").fillna(0)
    deltas = pd.to_numeric(service_lens.get("CREDIT_DELTA", pd.Series(dtype=float)), errors="coerce").fillna(0)
    category = service_lens.get("SERVICE_CATEGORY", pd.Series(dtype=str)).fillna("").astype(str)
    service = service_lens.get("SERVICE_TYPE", pd.Series(dtype=str)).fillna("").astype(str)
    total = safe_float(credits.sum())
    non_warehouse = safe_float(credits[~category.eq("Warehouse")].sum())
    ai = safe_float(credits[category.eq("AI / Cortex")].sum())
    serverless = safe_float(credits[category.eq("Serverless / Managed Compute")].sum())
    top_service = "No rows"
    if len(service_lens):
        top_service = str(service_lens.assign(_CREDITS=credits).sort_values("_CREDITS", ascending=False).iloc[0].get("SERVICE_TYPE") or "Unknown")
    top_moving_service = "No movement"
    top_moving_delta = 0.0
    if len(service_lens) and deltas.abs().sum() > 0:
        mover = service_lens.assign(_ABS_DELTA=deltas.abs()).sort_values("_ABS_DELTA", ascending=False).iloc[0]
        top_moving_service = str(mover.get("SERVICE_TYPE") or "Unknown")
        top_moving_delta = safe_float(mover.get("CREDIT_DELTA"))
    return {
        "total_credits": total,
        "non_warehouse_credits": non_warehouse,
        "ai_credits": ai,
        "serverless_credits": serverless,
        "top_service": top_service,
        "top_moving_service": top_moving_service,
        "top_moving_delta": top_moving_delta,
        "categories": int(category.nunique()),
    }


def _service_lens_movement_rows(service_lens: pd.DataFrame | None, credit_price: float, limit: int = 8) -> pd.DataFrame:
    columns = [
        "SERVICE_CATEGORY", "SERVICE_TYPE", "CURRENT_SPEND_USD", "PRIOR_SPEND_USD",
        "COST_DELTA_USD", "CREDIT_DELTA", "DELTA_LABEL", "SORT_VALUE",
    ]
    if not _looks_like_frame(service_lens) or service_lens.empty:
        return pd.DataFrame(columns=columns)

    view = service_lens.copy()
    if "SERVICE_TYPE" not in view.columns:
        return pd.DataFrame(columns=columns)
    for column in ("SERVICE_CATEGORY",):
        if column not in view.columns:
            view[column] = "Other"

    def numeric_column(name: str) -> pd.Series:
        return pd.to_numeric(view.get(name, pd.Series([0] * len(view), index=view.index)), errors="coerce").fillna(0)

    current_credits = numeric_column("CREDITS_BILLED")
    prior_credits = numeric_column("CREDITS_BILLED_PRIOR")
    credit_delta = numeric_column("CREDIT_DELTA")
    current_spend = numeric_column("ESTIMATED_COST_USD")
    prior_spend = numeric_column("PRIOR_ESTIMATED_COST_USD")
    cost_delta = numeric_column("COST_DELTA_USD")

    current_spend = current_spend.where(current_spend.abs() > 0, current_credits * safe_float(credit_price, 3.68))
    prior_spend = prior_spend.where(prior_spend.abs() > 0, prior_credits * safe_float(credit_price, 3.68))
    cost_delta = cost_delta.where(cost_delta.abs() > 0, current_spend - prior_spend)
    credit_delta = credit_delta.where(credit_delta.abs() > 0, current_credits - prior_credits)

    movement = pd.DataFrame({
        "SERVICE_CATEGORY": view["SERVICE_CATEGORY"].fillna("Other").astype(str),
        "SERVICE_TYPE": view["SERVICE_TYPE"].fillna("Unknown").astype(str),
        "CURRENT_SPEND_USD": current_spend,
        "PRIOR_SPEND_USD": prior_spend,
        "COST_DELTA_USD": cost_delta,
        "CREDIT_DELTA": credit_delta,
    })
    movement["DELTA_LABEL"] = movement["COST_DELTA_USD"].apply(lambda value: _slide_money(value, signed=True))
    movement["SORT_VALUE"] = movement["COST_DELTA_USD"].abs()
    movement = movement[
        (movement["CURRENT_SPEND_USD"].abs() + movement["PRIOR_SPEND_USD"].abs() + movement["COST_DELTA_USD"].abs()) > 0
    ].sort_values(["SORT_VALUE", "CURRENT_SPEND_USD"], ascending=[False, False])
    return movement.head(max(1, int(limit or 8)))[columns].reset_index(drop=True)


def _render_service_cost_movement_chart(service_lens: pd.DataFrame, credit_price: float) -> None:
    movement = _service_lens_movement_rows(service_lens, credit_price, limit=8)
    if movement.empty:
        st.caption("No service movement rows loaded for this scope.")
        return
    palette = _cost_chart_palette()
    alt = _altair()
    base = alt.Chart(movement).encode(
        y=alt.Y(
            "SERVICE_TYPE:N",
            sort=alt.SortField(field="SORT_VALUE", order="descending"),
            title=None,
            axis=alt.Axis(labelLimit=190),
        )
    )
    bars = base.mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4, opacity=0.72).encode(
        x=alt.X("CURRENT_SPEND_USD:Q", title="Current spend", axis=alt.Axis(format="$,.0f")),
        color=alt.condition("datum.COST_DELTA_USD > 0", alt.value(palette["risk"]), alt.value(palette["bar"])),
        tooltip=[
            alt.Tooltip("SERVICE_TYPE:N", title="Service"),
            alt.Tooltip("CURRENT_SPEND_USD:Q", title="Current", format="$,.2f"),
            alt.Tooltip("PRIOR_SPEND_USD:Q", title="Prior", format="$,.2f"),
            alt.Tooltip("COST_DELTA_USD:Q", title="Delta ($)", format="+,.2f"),
            alt.Tooltip("CREDIT_DELTA:Q", title="Credit delta", format="+,.2f"),
        ],
    )
    prior_ticks = base.mark_tick(color=palette["line"], thickness=3, size=20).encode(
        x=alt.X("PRIOR_SPEND_USD:Q", title="Current spend"),
    )
    labels = base.mark_text(align="left", dx=6, color=palette["text"], fontWeight="bold").encode(
        x="CURRENT_SPEND_USD:Q",
        text="DELTA_LABEL:N",
    )
    chart = _finalize_cost_chart(bars + prior_ticks + labels, height=max(210, min(360, 34 * len(movement) + 58)))
    st.altair_chart(chart, width="stretch")


def _cost_advisor_priority(impact_usd: float, *, finding_type: str = "") -> str:
    impact = abs(safe_float(impact_usd))
    finding = str(finding_type or "").upper()
    if impact >= 1000 or any(token in finding for token in ("SPILL", "FAILED", "ATTRIBUTION GAP")):
        return "High"
    if impact >= 250:
        return "Medium"
    return "Low"


def _cost_advisor_add_row(
    rows: list[dict],
    *,
    category: str,
    entity: str,
    finding: str,
    estimate_type: str,
    impact_usd: float,
    savings_usd: float,
    evidence: str,
    safe_next_action: str,
    proof_required: str,
    do_not_do: str,
    confidence: str,
    source: str,
) -> None:
    impact = round(safe_float(impact_usd), 2)
    savings = round(max(0.0, safe_float(savings_usd)), 2)
    priority = _cost_advisor_priority(max(impact, savings), finding_type=finding)
    rows.append({
        "PRIORITY": priority,
        "SEVERITY": priority,
        "CATEGORY": category,
        "ENTITY": str(entity or "Unknown"),
        "FINDING": finding,
        "ESTIMATE_TYPE": estimate_type,
        "EST_MONTHLY_IMPACT_USD": impact,
        "EST_MONTHLY_SAVINGS_USD": savings,
        "EVIDENCE": evidence,
        "TELEMETRY_SUMMARY": evidence,
        "SAFE_NEXT_ACTION": safe_next_action,
        "PROOF_REQUIRED": proof_required,
        "VALIDATION_NEEDED": proof_required,
        "DO_NOT_DO": do_not_do,
        "CONFIDENCE": confidence,
        "SOURCE": source,
    })


_COST_ADVISOR_ACTION_MAP = {
    "Failed query waste": ("Fix failed workload", "Recommendations and action queue"),
    "Warehouse pressure": ("Investigate pressure before capacity change", "Usage attribution and run-rate"),
    "Warehouse right-size review": ("Review right-size or suspend policy", "Usage attribution and run-rate"),
    "Automatic clustering": ("Validate clustering value", "Usage attribution and run-rate"),
    "Attribution gap": ("Reconcile spend attribution", "Usage attribution and run-rate"),
    "Service spend movement": ("Map non-warehouse service spend", "Usage attribution and run-rate"),
    "Storage retention": ("Review storage retention", "Storage cost and retention"),
    "Storage failsafe": ("Review storage lifecycle", "Storage cost and retention"),
}


def _cost_advisor_action_for(category: str) -> tuple[str, str]:
    return _COST_ADVISOR_ACTION_MAP.get(
        str(category or "").strip(),
        ("Investigate cost signal", "Recommendations and action queue"),
    )


def _decorate_cost_advisor_board(board: pd.DataFrame) -> pd.DataFrame:
    """Add action-oriented columns to advisor rows without changing the telemetry source."""
    if board.empty:
        return board
    decorated = board.copy()
    actions = decorated.get("CATEGORY", pd.Series([""] * len(decorated), index=decorated.index)).apply(
        _cost_advisor_action_for
    )
    decorated["ACTION_TYPE"] = actions.apply(lambda item: item[0])
    decorated["WORKFLOW_ROUTE"] = actions.apply(lambda item: item[1])
    decorated["PRIMARY_METRIC"] = decorated.apply(
        lambda row: (
            f"${safe_float(row.get('EST_MONTHLY_SAVINGS_USD')):,.0f}/mo savings"
            if safe_float(row.get("EST_MONTHLY_SAVINGS_USD")) > 0
            else f"${abs(safe_float(row.get('EST_MONTHLY_IMPACT_USD'))):,.0f}/mo value at risk"
        ),
        axis=1,
    )
    decorated["EXECUTION_MODE"] = decorated["ESTIMATE_TYPE"].fillna("").astype(str).apply(
        lambda value: (
            "Savings candidate"
            if "saving" in value.lower() or "recoverable" in value.lower()
            else "Investigation"
        )
    )
    return decorated


def _build_cost_advisor_board(
    *,
    efficiency_summary: pd.DataFrame | None,
    warehouse_efficiency: pd.DataFrame | None,
    clustering_cost: pd.DataFrame | None,
    reconciliation: pd.DataFrame | None,
    service_lens: pd.DataFrame | None,
    credit_price: float,
    days: int,
    storage_table_metrics: pd.DataFrame | None = None,
    storage_db_detail: pd.DataFrame | None = None,
    storage_cost_per_tb: float | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Build ranked cost-advisor findings from already loaded Cost & Contract frames."""
    rows: list[dict] = []
    days = max(1, safe_int(days, 7))
    window_factor = 30.0 / float(days)
    price = safe_float(credit_price, safe_float(DEFAULTS.get("credit_price"), 3.68))
    storage_rate = safe_float(storage_cost_per_tb, safe_float(DEFAULTS.get("storage_cost_per_tb"), 23.0))

    if _looks_like_frame(efficiency_summary) and not efficiency_summary.empty:
        row = efficiency_summary.iloc[0]
        failed_waste = safe_float(row.get("FAILED_QUERY_WASTE_USD"))
        failed_queries = safe_int(row.get("FAILED_QUERIES"))
        if failed_waste > 0 and failed_queries > 0:
            monthly = failed_waste * window_factor
            _cost_advisor_add_row(
                rows,
                category="Failed query waste",
                entity="Account workload",
                finding="Failed-query spend is measurable",
                estimate_type="Conservative recoverable waste",
                impact_usd=monthly,
                savings_usd=monthly * 0.6,
                evidence=(
                    f"{failed_queries:,} failed query row(s), ${failed_waste:,.0f} failed-query waste "
                    f"in the {days}-day window."
                ),
                safe_next_action="Group failed queries by error code, warehouse, user, and query signature before routing fixes.",
                proof_required="Failed query count and failed-query waste should fall in the next complete cost window.",
                do_not_do="Do not resize warehouses for failures unless queue or spill telemetry also points to capacity pressure.",
                confidence="Medium - waste is attributed from query cost telemetry; root cause still needs query evidence.",
                source="Cost efficiency summary",
            )

    if _looks_like_frame(warehouse_efficiency) and not warehouse_efficiency.empty:
        work = warehouse_efficiency.copy()
        wh_col = _cost_column(work, ["WAREHOUSE_NAME", "WAREHOUSE"])
        if wh_col:
            for col in (
                "COST_USD", "QUEUE_SECONDS", "REMOTE_SPILL_GB", "FAILED_QUERY_WASTE_USD",
                "QUERY_COUNT", "AVG_CACHE_PCT",
            ):
                if col not in work.columns:
                    work[col] = 0.0
            for _, row in work.iterrows():
                wh = str(row.get(wh_col) or "Unknown")
                window_cost = safe_float(row.get("COST_USD"))
                monthly_cost = window_cost * window_factor
                queue_seconds = safe_float(row.get("QUEUE_SECONDS"))
                remote_spill_gb = safe_float(row.get("REMOTE_SPILL_GB"))
                failed_waste = safe_float(row.get("FAILED_QUERY_WASTE_USD"))
                query_count = safe_int(row.get("QUERY_COUNT"))
                avg_cache = safe_float(row.get("AVG_CACHE_PCT"))
                if remote_spill_gb >= 10 or queue_seconds >= 600:
                    pressure = []
                    if remote_spill_gb >= 10:
                        pressure.append(f"{remote_spill_gb:,.1f} GB remote spill")
                    if queue_seconds >= 600:
                        pressure.append(f"{queue_seconds:,.0f}s queue time")
                    _cost_advisor_add_row(
                        rows,
                        category="Warehouse pressure",
                        entity=wh,
                        finding="Queue or spill pressure may be inflating cost",
                        estimate_type="Value at risk",
                        impact_usd=monthly_cost,
                        savings_usd=0.0,
                        evidence=(
                            f"{wh}: {', '.join(pressure)} with ${window_cost:,.0f} warehouse cost "
                            f"in the {days}-day window."
                        ),
                        safe_next_action="Inspect top query profiles and decide between SQL tuning, workload isolation, or reviewed capacity change.",
                        proof_required="Remote spill, queue seconds, p95 runtime, and credits must improve for the same workload.",
                        do_not_do="Do not blindly upsize; spill can come from SQL shape and may multiply cost.",
                        confidence="Medium - pressure is direct telemetry, but the correct fix depends on query profile evidence.",
                        source="Warehouse efficiency and pressure",
                    )
                elif monthly_cost >= 250 and query_count > 0 and queue_seconds < 30 and remote_spill_gb < 1:
                    _cost_advisor_add_row(
                        rows,
                        category="Warehouse right-size review",
                        entity=wh,
                        finding="Low-pressure warehouse may have savings opportunity",
                        estimate_type="Conservative savings candidate",
                        impact_usd=monthly_cost,
                        savings_usd=monthly_cost * 0.25,
                        evidence=(
                            f"{wh}: ${window_cost:,.0f} cost, {query_count:,} query row(s), "
                            f"{queue_seconds:,.0f}s queue, {remote_spill_gb:,.1f} GB remote spill, "
                            f"{avg_cache:,.1f}% average cache in the {days}-day window."
                        ),
                        safe_next_action="Review p95 runtime and workload schedule before testing a one-step downsize or tighter suspend policy.",
                        proof_required="Cost should decline while p95 runtime, queue, failures, and spill remain acceptable.",
                        do_not_do="Do not downsize always-on, latency-sensitive, or shared service warehouses from this row alone.",
                        confidence="Low - savings are directional until size, suspend, and SLA context are reviewed.",
                        source="Warehouse efficiency and pressure",
                    )
                if failed_waste >= 50:
                    monthly_failed = failed_waste * window_factor
                    _cost_advisor_add_row(
                        rows,
                        category="Failed query waste",
                        entity=wh,
                        finding="Warehouse has failed-query cost waste",
                        estimate_type="Conservative recoverable waste",
                        impact_usd=monthly_failed,
                        savings_usd=monthly_failed * 0.6,
                        evidence=f"{wh}: ${failed_waste:,.0f} failed-query waste in the loaded window.",
                        safe_next_action="Route the top failed query signatures and owners before changing warehouse settings.",
                        proof_required="Failed-query waste should drop in the next completed cost window.",
                        do_not_do="Do not treat failed-query waste as a warehouse-sizing fix without error-code evidence.",
                        confidence="Medium - warehouse failure waste is measurable, root cause requires query diagnostics.",
                        source="Warehouse efficiency and pressure",
                    )

    if _looks_like_frame(clustering_cost) and not clustering_cost.empty:
        work = clustering_cost.copy()
        table_col = _cost_column(work, ["TABLE_NAME", "TABLE"])
        cost_col = _cost_column(work, ["CLUSTERING_COST_USD", "COST_USD"])
        tb_col = _cost_column(work, ["TB_RECLUSTERED"])
        if table_col and cost_col:
            work["_COST"] = pd.to_numeric(work[cost_col], errors="coerce").fillna(0.0)
            for _, row in work.sort_values("_COST", ascending=False).head(8).iterrows():
                window_cost = safe_float(row.get("_COST"))
                monthly_cost = window_cost * window_factor
                if monthly_cost < 50:
                    continue
                table_name = str(row.get(table_col) or "Unknown")
                tb = safe_float(row.get(tb_col)) if tb_col else 0.0
                _cost_advisor_add_row(
                    rows,
                    category="Automatic clustering",
                    entity=table_name,
                    finding="Automatic clustering spend needs value proof",
                    estimate_type="Conservative savings candidate",
                    impact_usd=monthly_cost,
                    savings_usd=monthly_cost * 0.5,
                    evidence=(
                        f"{table_name}: ${window_cost:,.0f} clustering cost and {tb:,.2f} TB reclustered "
                        f"in the {days}-day window."
                    ),
                    safe_next_action="Review clustering depth, DML churn, pruning benefit, and top query demand before changing clustering.",
                    proof_required="Cost per TB reclustered should fall or query pruning/runtime must justify the clustering spend.",
                    do_not_do="Do not suspend reclustering until query benefit and recovery expectations are reviewed.",
                    confidence="Medium - clustering cost is direct telemetry, value requires workload proof.",
                    source="Automatic clustering cost",
                )

    if _looks_like_frame(reconciliation) and not reconciliation.empty:
        gap = _build_attribution_gap_summary(reconciliation, price)
        gap_usd = abs(safe_float(gap.get("gap_usd")))
        if gap_usd >= 100:
            _cost_advisor_add_row(
                rows,
                category="Attribution gap",
                entity=str(gap.get("top_gap_warehouse") or "Warehouse attribution"),
                finding="Query attribution gap does not reconcile to metered credits",
                estimate_type="Data quality / idle-cost exposure",
                impact_usd=gap_usd,
                savings_usd=0.0,
                evidence=(
                    f"{safe_float(gap.get('gap_credits')):+,.2f} credit gap "
                    f"({safe_float(gap.get('gap_pct')):+.1f}%), ${gap_usd:,.0f} equivalent."
                ),
                safe_next_action="Separate idle, cloud-services, serverless, AI, and execution-attributed spend before routing owners.",
                proof_required="Reconciliation gap should narrow or be explained by labeled non-query service spend.",
                do_not_do="Do not charge query owners for warehouse idle or service costs without explicit allocation evidence.",
                confidence="High - metering gap is direct math; ownership requires allocation policy.",
                source="Query attribution reconciliation",
            )

    if _looks_like_frame(service_lens) and not service_lens.empty:
        movement = _service_lens_movement_rows(service_lens, price, limit=12)
        if not movement.empty:
            category_series = movement.get("SERVICE_CATEGORY", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
            non_wh = movement[~category_series.eq("WAREHOUSE")].copy()
            if not non_wh.empty:
                non_wh["_POS_DELTA"] = pd.to_numeric(non_wh.get("COST_DELTA_USD", 0), errors="coerce").fillna(0.0)
                non_wh = non_wh[non_wh["_POS_DELTA"] > 0].sort_values("_POS_DELTA", ascending=False)
                for _, row in non_wh.head(3).iterrows():
                    delta_usd = safe_float(row.get("_POS_DELTA"))
                    if delta_usd < 25:
                        continue
                    service = str(row.get("SERVICE_TYPE") or "Unknown service")
                    category = str(row.get("SERVICE_CATEGORY") or "Other")
                    _cost_advisor_add_row(
                        rows,
                        category="Service spend movement",
                        entity=service,
                        finding="Non-warehouse service spend increased",
                        estimate_type="Cost movement investigation",
                        impact_usd=delta_usd,
                        savings_usd=0.0,
                        evidence=f"{service}: +${delta_usd:,.0f} versus the prior completed window ({category}).",
                        safe_next_action="Open the service lens and map the service to its owning workload or Snowflake feature.",
                        proof_required="The next completed service-cost window should confirm whether the increase persists.",
                        do_not_do="Do not attribute account-level service spend to a warehouse or database without direct evidence.",
                        confidence="High - service cost comes from official account metering; owner route may need more telemetry.",
                        source="Account service cost lens",
                    )

    if _looks_like_frame(storage_table_metrics) and not storage_table_metrics.empty:
        work = storage_table_metrics.copy()
        active_col = _cost_column(work, ["ACTIVE_GB"])
        tt_col = _cost_column(work, ["TIME_TRAVEL_GB"])
        failsafe_col = _cost_column(work, ["FAILSAFE_GB"])
        clone_col = _cost_column(work, ["CLONE_GB"])
        if tt_col:
            for col in (active_col, tt_col, failsafe_col, clone_col):
                if col and col not in work.columns:
                    work[col] = 0.0
            for _, row in work.iterrows():
                catalog = str(row.get("TABLE_CATALOG") or "").strip()
                schema = str(row.get("TABLE_SCHEMA") or "").strip()
                table = str(row.get("TABLE_NAME") or "").strip()
                table_name = ".".join(part for part in (catalog, schema, table) if part) or "Unknown table"
                active_gb = safe_float(row.get(active_col)) if active_col else 0.0
                time_travel_gb = safe_float(row.get(tt_col))
                failsafe_gb = safe_float(row.get(failsafe_col)) if failsafe_col else 0.0
                clone_gb = safe_float(row.get(clone_col)) if clone_col else 0.0
                monthly_tt = (time_travel_gb / 1024.0) * storage_rate
                if time_travel_gb >= 100 or monthly_tt >= 25:
                    _cost_advisor_add_row(
                        rows,
                        category="Storage retention",
                        entity=table_name,
                        finding="Table time-travel storage needs retention review",
                        estimate_type="Conservative savings candidate",
                        impact_usd=monthly_tt,
                        savings_usd=monthly_tt * 0.5,
                        evidence=(
                            f"{table_name}: {time_travel_gb:,.1f} GB time-travel, {active_gb:,.1f} GB active, "
                            f"{failsafe_gb:,.1f} GB failsafe, {clone_gb:,.1f} GB retained for clone."
                        ),
                        safe_next_action="Confirm recovery, cloning, and compliance needs before lowering table/schema/database retention.",
                        proof_required="Time-travel GB and monthly storage estimate should decline after the approved retention window ages out.",
                        do_not_do="Do not lower retention on regulated, clone-heavy, or recovery-sensitive objects from this row alone.",
                        confidence="Medium - table storage bytes are direct telemetry, retention safety depends on policy.",
                        source="Storage table metrics",
                    )

    if _looks_like_frame(storage_db_detail) and not storage_db_detail.empty:
        work = storage_db_detail.copy()
        db_col = _cost_column(work, ["DATABASE_NAME", "DATABASE"])
        storage_col = _cost_column(work, ["DATABASE_GB", "STORAGE_GB"])
        failsafe_col = _cost_column(work, ["FAILSAFE_GB"])
        cost_col = _cost_column(work, ["EST_COST_USD", "EST_MONTHLY_COST", "MONTHLY_COST_USD"])
        if db_col and failsafe_col:
            for _, row in work.iterrows():
                db = str(row.get(db_col) or "Unknown database")
                storage_gb = safe_float(row.get(storage_col)) if storage_col else 0.0
                failsafe_gb = safe_float(row.get(failsafe_col))
                monthly_cost = safe_float(row.get(cost_col)) if cost_col else ((storage_gb + failsafe_gb) / 1024.0) * storage_rate
                failsafe_cost = (failsafe_gb / 1024.0) * storage_rate
                if failsafe_gb < 250 and failsafe_cost < 25:
                    continue
                _cost_advisor_add_row(
                    rows,
                    category="Storage failsafe",
                    entity=db,
                    finding="Database failsafe storage is material",
                    estimate_type="Retention and lifecycle investigation",
                    impact_usd=max(failsafe_cost, monthly_cost),
                    savings_usd=0.0,
                    evidence=(
                        f"{db}: {failsafe_gb:,.1f} GB failsafe, {storage_gb:,.1f} GB database storage, "
                        f"~${monthly_cost:,.0f}/mo total storage estimate."
                    ),
                    safe_next_action="Identify recent drops/deletes and retention settings before changing lifecycle or cleanup patterns.",
                    proof_required="Failsafe and total storage trend should decline only after Snowflake retention/failsafe windows age out.",
                    do_not_do="Do not promise immediate savings from failsafe; Snowflake failsafe is not directly purgeable.",
                    confidence="Medium - database storage bytes are direct telemetry, savings timing depends on retention windows.",
                    source="Storage database detail",
                )

    board = pd.DataFrame(rows)
    if board.empty:
        return {
            "findings": 0,
            "high": 0,
            "estimated_monthly_savings": 0.0,
            "estimated_monthly_impact": 0.0,
        }, board

    board = _decorate_cost_advisor_board(board)
    priority_rank = {"High": 0, "Medium": 1, "Low": 2}
    board["_PRIORITY_RANK"] = board["PRIORITY"].map(priority_rank).fillna(9)
    board["_IMPACT_SORT"] = pd.to_numeric(board["EST_MONTHLY_IMPACT_USD"], errors="coerce").fillna(0).abs()
    board = board.sort_values(
        ["_PRIORITY_RANK", "EST_MONTHLY_SAVINGS_USD", "_IMPACT_SORT"],
        ascending=[True, False, False],
    ).drop(columns=["_PRIORITY_RANK", "_IMPACT_SORT"], errors="ignore").reset_index(drop=True)
    priority = board["PRIORITY"].fillna("").astype(str)
    return {
        "findings": int(len(board)),
        "high": int(priority.eq("High").sum()),
        "estimated_monthly_savings": safe_float(
            pd.to_numeric(board["EST_MONTHLY_SAVINGS_USD"], errors="coerce").fillna(0).sum()
        ),
        "estimated_monthly_impact": safe_float(
            pd.to_numeric(board["EST_MONTHLY_IMPACT_USD"], errors="coerce").fillna(0).abs().sum()
        ),
    }, board


def _cost_advisor_category_summary(board: pd.DataFrame | None) -> pd.DataFrame:
    columns = [
        "CATEGORY", "TOP_PRIORITY", "FINDINGS", "HIGH_FINDINGS",
        "EST_MONTHLY_SAVINGS_USD", "EST_MONTHLY_IMPACT_USD", "TOP_ENTITY",
    ]
    if not _looks_like_frame(board) or board.empty or "CATEGORY" not in board.columns:
        return pd.DataFrame(columns=columns)

    view = board.copy()
    view["CATEGORY"] = view["CATEGORY"].fillna("Other").astype(str).replace("", "Other")
    view["EST_MONTHLY_SAVINGS_USD"] = pd.to_numeric(
        view.get("EST_MONTHLY_SAVINGS_USD", pd.Series([0] * len(view), index=view.index)),
        errors="coerce",
    ).fillna(0).clip(lower=0)
    view["EST_MONTHLY_IMPACT_USD"] = pd.to_numeric(
        view.get("EST_MONTHLY_IMPACT_USD", pd.Series([0] * len(view), index=view.index)),
        errors="coerce",
    ).fillna(0).abs()
    severity = view.get("SEVERITY", view.get("PRIORITY", pd.Series(["Low"] * len(view), index=view.index)))
    view["_PRIORITY"] = severity.fillna("Low").astype(str).str.title()
    rank_map = {"High": 0, "Medium": 1, "Low": 2}
    view["_PRIORITY_RANK"] = view["_PRIORITY"].map(rank_map).fillna(9).astype(int)
    view["_HIGH"] = view["_PRIORITY"].eq("High").astype(int)
    if "ENTITY" not in view.columns:
        view["ENTITY"] = ""

    summary = (
        view.groupby("CATEGORY", dropna=False)
        .agg(
            FINDINGS=("CATEGORY", "size"),
            HIGH_FINDINGS=("_HIGH", "sum"),
            EST_MONTHLY_SAVINGS_USD=("EST_MONTHLY_SAVINGS_USD", "sum"),
            EST_MONTHLY_IMPACT_USD=("EST_MONTHLY_IMPACT_USD", "sum"),
            _PRIORITY_RANK=("_PRIORITY_RANK", "min"),
            TOP_ENTITY=("ENTITY", "first"),
        )
        .reset_index()
    )
    priority_labels = {0: "High", 1: "Medium", 2: "Low"}
    summary["TOP_PRIORITY"] = summary["_PRIORITY_RANK"].map(priority_labels).fillna("Low")
    summary["_SORT_VALUE"] = summary["EST_MONTHLY_SAVINGS_USD"].abs() + summary["EST_MONTHLY_IMPACT_USD"].abs()
    summary = summary.sort_values(
        ["_PRIORITY_RANK", "EST_MONTHLY_SAVINGS_USD", "_SORT_VALUE"],
        ascending=[True, False, False],
    )
    return summary[columns].reset_index(drop=True)


def _cost_advisor_action_summary(board: pd.DataFrame | None) -> pd.DataFrame:
    columns = [
        "ACTION_TYPE", "WORKFLOW_ROUTE", "TOP_PRIORITY", "FINDINGS", "HIGH_FINDINGS",
        "EST_MONTHLY_SAVINGS_USD", "EST_MONTHLY_IMPACT_USD", "NEXT_MOVE",
    ]
    if not _looks_like_frame(board) or board.empty:
        return pd.DataFrame(columns=columns)
    view = _decorate_cost_advisor_board(board)
    for column in ("ACTION_TYPE", "WORKFLOW_ROUTE", "SAFE_NEXT_ACTION"):
        if column not in view.columns:
            view[column] = ""
    view["EST_MONTHLY_SAVINGS_USD"] = pd.to_numeric(
        view.get("EST_MONTHLY_SAVINGS_USD", pd.Series([0] * len(view), index=view.index)),
        errors="coerce",
    ).fillna(0).clip(lower=0)
    view["EST_MONTHLY_IMPACT_USD"] = pd.to_numeric(
        view.get("EST_MONTHLY_IMPACT_USD", pd.Series([0] * len(view), index=view.index)),
        errors="coerce",
    ).fillna(0).abs()
    priority = view.get("SEVERITY", view.get("PRIORITY", pd.Series(["Low"] * len(view), index=view.index)))
    view["_PRIORITY"] = priority.fillna("Low").astype(str).str.title()
    rank_map = {"High": 0, "Medium": 1, "Low": 2}
    view["_PRIORITY_RANK"] = view["_PRIORITY"].map(rank_map).fillna(9).astype(int)
    view["_HIGH"] = view["_PRIORITY"].eq("High").astype(int)
    summary = (
        view.groupby(["ACTION_TYPE", "WORKFLOW_ROUTE"], dropna=False)
        .agg(
            FINDINGS=("ACTION_TYPE", "size"),
            HIGH_FINDINGS=("_HIGH", "sum"),
            EST_MONTHLY_SAVINGS_USD=("EST_MONTHLY_SAVINGS_USD", "sum"),
            EST_MONTHLY_IMPACT_USD=("EST_MONTHLY_IMPACT_USD", "sum"),
            _PRIORITY_RANK=("_PRIORITY_RANK", "min"),
            NEXT_MOVE=("SAFE_NEXT_ACTION", "first"),
        )
        .reset_index()
    )
    priority_labels = {0: "High", 1: "Medium", 2: "Low"}
    summary["TOP_PRIORITY"] = summary["_PRIORITY_RANK"].map(priority_labels).fillna("Low")
    summary["_SORT_VALUE"] = summary["EST_MONTHLY_SAVINGS_USD"] + summary["EST_MONTHLY_IMPACT_USD"]
    summary = summary.sort_values(
        ["_PRIORITY_RANK", "EST_MONTHLY_SAVINGS_USD", "_SORT_VALUE"],
        ascending=[True, False, False],
    )
    return summary[columns].reset_index(drop=True)


def _cost_advisor_detail_options(board: pd.DataFrame | None) -> pd.DataFrame:
    if not _looks_like_frame(board) or board.empty:
        return pd.DataFrame()
    view = _decorate_cost_advisor_board(board).reset_index(drop=True).copy()
    view["_DETAIL_ID"] = view.index.astype(int)
    view["DETAIL_LABEL"] = view.apply(
        lambda row: (
            f"{row.get('SEVERITY', row.get('PRIORITY', 'Review'))} | "
            f"{row.get('ACTION_TYPE', 'Investigate')} | "
            f"{row.get('ENTITY', 'Unknown')}"
        ),
        axis=1,
    )
    return view


def _render_cost_advisor_detail(board: pd.DataFrame | None) -> None:
    options = _cost_advisor_detail_options(board)
    if options.empty:
        return
    st.markdown("**Open Cost Advisor Finding**")
    selected_label = st.selectbox(
        "Advisor finding",
        options["DETAIL_LABEL"].tolist(),
        key="cost_advisor_detail_select",
    )
    selected = options[options["DETAIL_LABEL"].eq(selected_label)]
    if selected.empty:
        return
    row = selected.iloc[0]
    render_shell_snapshot((
        ("Priority", str(row.get("SEVERITY") or row.get("PRIORITY") or "Review")),
        ("Action", str(row.get("ACTION_TYPE") or "Investigate")),
        ("Route", str(row.get("WORKFLOW_ROUTE") or "Recommendations and action queue")),
        ("Metric", str(row.get("PRIMARY_METRIC") or "")),
    ))
    st.caption(_clean_display_text(str(row.get("TELEMETRY_SUMMARY") or row.get("EVIDENCE") or "")))
    render_escaped_labeled_text("Next move", row.get("SAFE_NEXT_ACTION") or "Review the loaded telemetry.")
    render_escaped_labeled_text(
        "Proof",
        row.get("VALIDATION_NEEDED") or row.get("PROOF_REQUIRED") or "Confirm in the next completed telemetry window.",
    )
    do_not_do = str(row.get("DO_NOT_DO") or "").strip()
    if do_not_do:
        st.caption(f"Guardrail: {_clean_display_text(do_not_do)}")
    route = str(row.get("WORKFLOW_ROUTE") or "").strip()
    if route in WORKFLOWS and st.button(f"Open {route}", key="cost_advisor_detail_route", width="stretch"):
        st.session_state["cost_contract_workflow"] = route
        st.rerun()


def _render_cost_advisor_category_chart(board: pd.DataFrame) -> None:
    summary = _cost_advisor_category_summary(board)
    if summary.empty:
        return
    palette = _cost_chart_palette()
    alt = _altair()
    base = alt.Chart(summary).encode(
        y=alt.Y(
            "CATEGORY:N",
            sort=alt.SortField(field="EST_MONTHLY_SAVINGS_USD", order="descending"),
            title=None,
            axis=alt.Axis(labelLimit=190),
        )
    )
    bars = base.mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4, opacity=0.76).encode(
        x=alt.X("EST_MONTHLY_SAVINGS_USD:Q", title="Estimated monthly dollars", axis=alt.Axis(format="$,.0f")),
        color=alt.value(palette["bar"]),
        tooltip=[
            alt.Tooltip("CATEGORY:N", title="Category"),
            alt.Tooltip("TOP_PRIORITY:N", title="Top priority"),
            alt.Tooltip("FINDINGS:Q", title="Findings", format=","),
            alt.Tooltip("HIGH_FINDINGS:Q", title="High", format=","),
            alt.Tooltip("EST_MONTHLY_SAVINGS_USD:Q", title="Savings / mo", format="$,.2f"),
            alt.Tooltip("EST_MONTHLY_IMPACT_USD:Q", title="Value at risk", format="$,.2f"),
        ],
    )
    impact_ticks = base.mark_tick(color=palette["risk"], thickness=3, size=20).encode(
        x=alt.X("EST_MONTHLY_IMPACT_USD:Q", title="Estimated monthly dollars"),
        tooltip=[
            alt.Tooltip("CATEGORY:N", title="Category"),
            alt.Tooltip("EST_MONTHLY_IMPACT_USD:Q", title="Value at risk", format="$,.2f"),
        ],
    )
    st.altair_chart(
        _finalize_cost_chart(bars + impact_ticks, height=max(190, min(330, 32 * len(summary) + 58))),
        width="stretch",
    )


def _render_cost_advisor_board(
    *,
    efficiency_summary: pd.DataFrame,
    warehouse_efficiency: pd.DataFrame,
    clustering_cost: pd.DataFrame,
    reconciliation: pd.DataFrame,
    service_lens: pd.DataFrame,
    credit_price: float,
    days: int,
    storage_table_metrics: pd.DataFrame | None = None,
    storage_db_detail: pd.DataFrame | None = None,
    storage_cost_per_tb: float | None = None,
) -> None:
    summary, board = _build_cost_advisor_board(
        efficiency_summary=efficiency_summary,
        warehouse_efficiency=warehouse_efficiency,
        clustering_cost=clustering_cost,
        reconciliation=reconciliation,
        service_lens=service_lens,
        credit_price=credit_price,
        days=days,
        storage_table_metrics=storage_table_metrics,
        storage_db_detail=storage_db_detail,
        storage_cost_per_tb=storage_cost_per_tb,
    )
    st.session_state["cost_contract_cost_advisor_summary"] = summary
    st.session_state["cost_contract_cost_advisor_board"] = board
    if board.empty:
        return
    st.markdown("**Cost Advisor**")
    render_shell_snapshot((
        ("Findings", f"{summary['findings']:,}"),
        ("High Priority", f"{summary['high']:,}"),
        ("Est. Savings / Mo", f"${safe_float(summary.get('estimated_monthly_savings')):,.0f}"),
        ("Value at Risk", f"${safe_float(summary.get('estimated_monthly_impact')):,.0f}"),
    ))
    st.caption(
        "Advisor findings are conservative and telemetry-backed. Savings are estimates; pressure and attribution rows are investigation/value-at-risk signals."
    )
    action_summary = _cost_advisor_action_summary(board)
    if not action_summary.empty:
        render_priority_dataframe(
            action_summary,
            title="Cost advisor action rollup",
            priority_columns=[
                "TOP_PRIORITY", "ACTION_TYPE", "WORKFLOW_ROUTE", "FINDINGS", "HIGH_FINDINGS",
                "EST_MONTHLY_SAVINGS_USD", "EST_MONTHLY_IMPACT_USD", "NEXT_MOVE",
            ],
            sort_by=["TOP_PRIORITY", "EST_MONTHLY_SAVINGS_USD", "EST_MONTHLY_IMPACT_USD"],
            ascending=[True, False, False],
            raw_label="All cost advisor action groups",
            height=260,
            max_rows=8,
        )
    _render_cost_advisor_category_chart(board)
    render_priority_dataframe(
        board,
        title="Ranked cost advisor findings",
        priority_columns=[
            "SEVERITY", "ACTION_TYPE", "WORKFLOW_ROUTE", "CATEGORY", "ENTITY", "EXECUTION_MODE", "PRIMARY_METRIC",
            "ESTIMATE_TYPE",
            "EST_MONTHLY_SAVINGS_USD", "EST_MONTHLY_IMPACT_USD",
            "TELEMETRY_SUMMARY", "SAFE_NEXT_ACTION", "VALIDATION_NEEDED", "DO_NOT_DO", "CONFIDENCE",
        ],
        sort_by=["SEVERITY", "EST_MONTHLY_SAVINGS_USD", "EST_MONTHLY_IMPACT_USD"],
        ascending=[True, False, False],
        raw_label="All cost advisor findings",
        height=340,
        max_rows=12,
    )
    _render_cost_advisor_detail(board)


def _render_cost_source_health(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    attribution: pd.DataFrame,
    service_lens: pd.DataFrame,
) -> None:
    summary, board = _build_cost_source_health_board(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
        attribution=attribution,
        service_lens=service_lens,
    )
    if board.empty:
        return
    st.markdown("**Cost Data Health**")
    render_shell_snapshot((
        ("Ready Inputs", f"{summary['ready']:,}"),
        ("Review / On Demand", f"{summary['review']:,}"),
        ("Unavailable", f"{summary['unavailable']:,}"),
    ))
    render_priority_dataframe(
        board,
        title="Cost data health",
        priority_columns=["STATE", "SOURCE", "SCOPE", "ROWS_LOADED", "FRESHNESS", "EVIDENCE", "NEXT_ACTION"],
        sort_by=["STATE", "SOURCE"],
        ascending=[True, True],
        raw_label="All cost data-health rows",
        height=260,
        max_rows=8,
    )


def _render_query_attribution_gap(reconciliation: pd.DataFrame, credit_price: float, error: str = "") -> None:
    if error:
        st.caption(f"Query attribution gap unavailable: {error}")
        return
    if reconciliation is None or getattr(reconciliation, "empty", True):
        return
    summary = _build_attribution_gap_summary(reconciliation, credit_price)
    st.markdown("**Query Attribution Gap**")
    render_shell_snapshot((
        ("Metered Credits", f"{summary['exact_credits']:,.2f}"),
        ("Query-Attributed", f"{summary['query_credits']:,.2f}"),
        ("Unallocated / Idle Gap", f"{summary['gap_credits']:,.2f} ({summary['gap_pct']:+.1f}%)"),
        ("Gap Dollars", f"${summary['gap_usd']:,.0f}"),
    ))
    st.caption(
        f"Top gap warehouse: {summary['top_gap_warehouse']}. "
        "Query attribution is execution-only; idle, serverless, storage, data transfer, cloud services, and AI token costs remain outside query-level attribution."
    )
    render_priority_dataframe(
        reconciliation,
        title="Warehouse metering to query attribution reconciliation",
        priority_columns=[
            "RECONCILIATION_STATUS", "WAREHOUSE_NAME", "USAGE_DAY", "EXACT_METERED_CREDITS",
            "ALLOCATED_QUERY_CREDITS", "OFFICIAL_ATTRIBUTED_COMPUTE_CREDITS",
            "VARIANCE_CREDITS", "VARIANCE_PCT", "ATTRIBUTION_SOURCE",
        ],
        sort_by=["VARIANCE_CREDITS"],
        ascending=[False],
        raw_label="All query attribution reconciliation rows",
        height=280,
        max_rows=8,
    )


def _render_account_service_cost_lens(service_lens: pd.DataFrame, credit_price: float, error: str = "") -> None:
    if error:
        st.caption(f"Account service-cost lens unavailable: {error}")
        return
    if service_lens is None or getattr(service_lens, "empty", True):
        return
    summary = _build_service_cost_lens_summary(service_lens)
    st.markdown("**Account Service Cost Lens**")
    metrics = [
        {"label": "Total Credits", "value": f"{summary['total_credits']:,.2f}"},
        {
            "label": "Non-Warehouse Credits",
            "value": f"{summary['non_warehouse_credits']:,.2f}",
            "delta_color": "inverse",
        },
    ]
    if safe_float(summary.get("ai_credits")) >= 0.005:
        metrics.append({
            "label": "AI / Cortex Credits",
            "value": f"{summary['ai_credits']:,.2f}",
            "delta_color": "inverse",
        })
    if safe_float(summary.get("serverless_credits")) >= 0.005:
        metrics.append({
            "label": "Serverless Credits",
            "value": f"{summary['serverless_credits']:,.2f}",
            "delta_color": "inverse",
        })
    if safe_float(summary.get("top_moving_delta")):
        mover = str(summary.get("top_moving_service") or "No movement")
        metrics.append({
            "label": "Top Service Move",
            "value": mover if len(mover) <= 24 else mover[:21] + "...",
            "delta": f"{safe_float(summary.get('top_moving_delta')):+,.2f} cr",
            "delta_color": "inverse",
        })
    _render_metric_items(metrics)
    st.caption(
        f"Top service: {summary['top_service']}. "
        f"Official Cost Monitor formula: METERING_HISTORY total credits through the completed 24-hour window, "
        f"with Snowflake services at ${credit_price:,.2f}/credit and Cortex/AI at ${get_current_ai_credit_price():,.2f}/AI credit."
    )
    _render_cost_chart_with_data_toggle(
        "Service Spend Movement",
        "cost_contract_service_movement",
        lambda: _render_service_cost_movement_chart(service_lens, credit_price),
        _service_lens_movement_rows(service_lens, credit_price, limit=16),
        priority_columns=[
            "SERVICE_CATEGORY", "SERVICE_TYPE", "CURRENT_SPEND_USD",
            "PRIOR_SPEND_USD", "COST_DELTA_USD", "CREDIT_DELTA",
        ],
        sort_by=["COST_DELTA_USD"],
        max_rows=16,
    )
    render_priority_dataframe(
        service_lens,
        title="Cost by Snowflake service type",
        priority_columns=[
            "SERVICE_CATEGORY", "SERVICE_TYPE", "CREDITS_BILLED", "ESTIMATED_COST_USD",
            "CREDITS_BILLED_PRIOR", "CREDIT_DELTA", "COST_DELTA_USD", "PCT_DELTA",
            "CREDITS_USED_COMPUTE", "CREDITS_USED_CLOUD_SERVICES", "OBSERVED_DAYS",
        ],
        sort_by=["CREDITS_BILLED"],
        ascending=[False],
        raw_label="All service-cost lens rows",
        height=280,
        max_rows=10,
    )


def _render_cost_efficiency_rca(
    efficiency_summary: pd.DataFrame,
    warehouse_efficiency: pd.DataFrame,
    clustering_cost: pd.DataFrame,
    credit_price: float,
    errors: dict | None = None,
) -> None:
    errors = errors or {}
    loaded_any = any(
        isinstance(frame, pd.DataFrame) and not frame.empty
        for frame in (efficiency_summary, warehouse_efficiency, clustering_cost)
    )
    if not loaded_any:
        for label, err in errors.items():
            if err:
                st.caption(f"{label} unavailable: {err}")
        return

    st.markdown("**Cost Efficiency RCA**")
    if isinstance(efficiency_summary, pd.DataFrame) and not efficiency_summary.empty:
        row = efficiency_summary.iloc[0]
        render_shell_snapshot((
            ("Cost / Query", f"${safe_float(row.get('COST_PER_QUERY_USD')):,.4f}"),
            ("Cost / TB", f"${safe_float(row.get('COST_PER_TB_USD')):,.2f}"),
            ("Failed Waste", f"${safe_float(row.get('FAILED_QUERY_WASTE_USD')):,.0f}"),
            ("Avg Cache", f"{safe_float(row.get('AVG_CACHE_PCT')):,.1f}%"),
        ))
        st.caption(
            f"{safe_int(row.get('QUERY_COUNT')):,} query rows, "
            f"{safe_float(row.get('TB_SCANNED')):,.2f} TB scanned, "
            f"{safe_int(row.get('FAILED_QUERIES')):,} failed query rows. "
            f"{str(row.get('ATTRIBUTION_SOURCE') or 'OVERWATCH allocated fallback')}"
        )

    if isinstance(warehouse_efficiency, pd.DataFrame) and not warehouse_efficiency.empty:
        render_priority_dataframe(
            warehouse_efficiency,
            title="Warehouse efficiency and pressure",
            priority_columns=[
                "WAREHOUSE_NAME", "COST_USD", "QUERY_COUNT", "COST_PER_QUERY_USD",
                "COST_PER_TB_USD", "CREDITS_PER_EXEC_HOUR", "QUEUE_SECONDS",
                "REMOTE_SPILL_GB", "FAILED_QUERIES", "FAILED_QUERY_WASTE_USD",
                "AVG_CACHE_PCT",
            ],
            sort_by=["FAILED_QUERY_WASTE_USD", "REMOTE_SPILL_GB", "COST_USD"],
            ascending=[False, False, False],
            raw_label="All warehouse efficiency rows",
            height=300,
            max_rows=12,
        )

    if isinstance(clustering_cost, pd.DataFrame) and not clustering_cost.empty:
        total_clustering = safe_float(clustering_cost.get("CLUSTERING_COST_USD", pd.Series(dtype=float)).sum())
        st.caption(f"Automatic clustering cost loaded: ${total_clustering:,.0f} in the selected window.")
        render_priority_dataframe(
            clustering_cost,
            title="Automatic clustering cost and churn",
            priority_columns=[
                "TABLE_NAME", "CLUSTERING_COST_USD", "CLUSTERING_CREDITS",
                "TB_RECLUSTERED", "ROWS_RECLUSTERED", "COST_PER_TB_RECLUSTERED",
            ],
            sort_by=["CLUSTERING_COST_USD", "COST_PER_TB_RECLUSTERED"],
            ascending=[False, False],
            raw_label="All clustering cost rows",
            height=260,
            max_rows=10,
        )

    for label, err in errors.items():
        if err:
            st.caption(f"{label} unavailable: {err}")
    defer_source_note(
        "Cost efficiency RCA uses completed ACCOUNT_USAGE windows and query-attribution fallback where official query attribution is unavailable."
    )


def _add_coverage_row(rows: list[dict], control: str, state: str, evidence: str, action: str, owner: str = "DBA / Cost owner") -> None:
    rows.append({
        "CONTROL": control,
        "STATE": state,
        "EVIDENCE": evidence,
        "NEXT_ACTION": action,
        "OWNER": owner,
    })


def _build_cost_control_coverage_board(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    state = state or st.session_state
    rows: list[dict] = []
    explorer = _state_frame(state, "df_cost_explorer_detail")
    chargeback = _state_frame(state, "df_chargeback")
    cortex_projection, cortex_exceptions = _loaded_cortex_state()

    _add_coverage_row(
        rows,
        "Exact warehouse metering",
        "Ready" if _has_columns(cockpit, ["CURRENT_CREDITS", "PRIOR_CREDITS"]) else "Load Needed",
        "Cockpit has exact current/prior warehouse credits." if _has_columns(cockpit, ["CURRENT_CREDITS", "PRIOR_CREDITS"]) else "Exact warehouse movement is available after Cost Cockpit refresh.",
        "Refresh cost detail before explaining any usage movement.",
    )
    _add_coverage_row(
        rows,
        "7-day average and YOY",
        "Ready" if _has_columns(run_rate, ["AVG_DAILY_7D", "YOY_7D_PCT", "YOY_30D_PCT"]) else "Load Needed",
        "Run-rate lens has complete-day 7d average and prior-year comparison." if _has_columns(run_rate, ["AVG_DAILY_7D", "YOY_7D_PCT", "YOY_30D_PCT"]) else "Run-rate and YOY trend context is available after refresh.",
        "Refresh cost detail to populate complete-day run-rate and YOY telemetry.",
    )
    _add_coverage_row(
        rows,
        "Company and environment split",
        "Ready" if _has_columns(chargeback, ["COMPANY", "ENVIRONMENT"]) or _has_columns(explorer, ["COMPANY", "ENVIRONMENT_ROLLUP"]) else "Review",
        "Chargeback/Cost Explorer includes company and environment dimensions." if _has_columns(chargeback, ["COMPANY", "ENVIRONMENT"]) or _has_columns(explorer, ["COMPANY", "ENVIRONMENT_ROLLUP"]) else "Company/environment attribution is available after refresh.",
        "Load Cost Explorer or Chargeback before defending ALFA/Trexis or PROD/DEV allocation.",
    )
    _add_coverage_row(
        rows,
        "Database and DEV rollup",
        "Ready" if _has_columns(chargeback, ["DATABASE_NAME"]) or _has_columns(explorer, ["DATABASE_NAME"]) else "Review",
        "Database-attributed cost is visible and labeled Allocated / Estimated." if _has_columns(chargeback, ["DATABASE_NAME"]) or _has_columns(explorer, ["DATABASE_NAME"]) else "Database-level attribution has not been loaded.",
        "Use Chargeback for PROD, DEV_ALL, and individual DEV database cost views.",
    )
    _add_coverage_row(
        rows,
        "Role, user, and department drivers",
        "Ready" if _has_columns(explorer, ["ROLE_NAME", "USER_NAME", "DEPARTMENT"]) else "Review",
        "Cost Explorer detail includes role, user, and department dimensions." if _has_columns(explorer, ["ROLE_NAME", "USER_NAME", "DEPARTMENT"]) else "Role/user/department cost drivers are available after refresh.",
        "Load Cost Explorer and sort by estimated cost before assigning optimization work.",
    )

    open_cost_queue = pd.DataFrame()
    if isinstance(queue, pd.DataFrame) and not queue.empty:
        category = queue.get("CATEGORY", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
        status = queue.get("STATUS", pd.Series(["New"] * len(queue), index=queue.index)).fillna("New").astype(str).str.title()
        open_cost_queue = queue[category.str.contains("COST|CHARGEBACK|CORTEX", na=False) & ~status.isin(["Fixed", "Ignored"])]
    owner_source = open_cost_queue.get("OWNER_SOURCE", pd.Series(dtype=str)).fillna("").astype(str).str.strip() if not open_cost_queue.empty else pd.Series(dtype=str)
    owner_ready = int(owner_source.ne("").sum()) if not owner_source.empty else 0
    _add_coverage_row(
        rows,
        "Owned cost action queue",
        "Ready" if not open_cost_queue.empty and owner_ready == len(open_cost_queue) else "Review" if not open_cost_queue.empty else "No Rows",
        f"{len(open_cost_queue):,} open cost action(s); {owner_ready:,} have route-source telemetry.",
        "Route cost findings through the action queue with route, due date, impact status, and closure telemetry.",
    )
    _add_coverage_row(
        rows,
        "Cortex cost guardrail",
        "Ready" if cortex_projection > 0 or cortex_exceptions > 0 else "No Rows",
        f"Projected Cortex spend ${cortex_projection:,.0f}/30d with {cortex_exceptions:,} exception(s).",
        "Open AI and Cortex spend when projection or exception count is non-zero.",
    )
    _add_coverage_row(
        rows,
        "Shared-cost disclosure",
        "Ready",
        "Warehouse totals are exact; user/query/database chargeback is explicitly labeled Allocated / Estimated.",
        "Keep shared warehouse and no-database-context costs out of exact PROD/DEV claims until tag telemetry exists.",
    )

    board = pd.DataFrame(rows)
    if board.empty:
        return {"score": 0, "ready": 0, "review": 0, "load_needed": 0}, board
    load_needed = int(board["STATE"].eq("Load Needed").sum())
    review = int(board["STATE"].eq("Review").sum())
    ready = int(board["STATE"].isin(["Ready", "No Rows"]).sum())
    score = max(0, min(100, 100 - load_needed * 12 - review * 6))
    board["_STATE_RANK"] = board["STATE"].map({"Load Needed": 0, "Review": 1, "No Rows": 2, "Ready": 3}).fillna(9)
    return {
        "score": int(score),
        "ready": ready,
        "review": review,
        "load_needed": load_needed,
    }, board.sort_values(["_STATE_RANK", "CONTROL"]).drop(columns=["_STATE_RANK"], errors="ignore")


def _build_cost_allocation_trust_board(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Classify cost telemetry as exact, allocated/estimated, or not yet defensible."""
    state = state or st.session_state
    rows: list[dict] = []
    explorer = _state_frame(state, "df_cost_explorer_detail")
    chargeback = _state_frame(state, "df_chargeback")

    def add(control: str, trust: str, evidence: str, action: str, owner: str = "DBA / Cost owner") -> None:
        rows.append({
            "CONTROL": control,
            "TRUST_STATE": trust,
            "EVIDENCE": evidence,
            "NEXT_ACTION": action,
            "OWNER": owner,
        })

    exact_loaded = _has_columns(cockpit, ["CURRENT_CREDITS", "PRIOR_CREDITS"])
    run_rate_loaded = _has_columns(run_rate, ["AVG_DAILY_7D", "YOY_7D_PCT", "YOY_30D_PCT"])
    add(
        "Contract and warehouse totals",
        "Exact" if exact_loaded and run_rate_loaded else "Load Needed",
        "Warehouse metering and complete-day run-rate/YOY are loaded." if exact_loaded and run_rate_loaded else "Exact warehouse totals or complete-day run-rate telemetry is missing.",
        "Refresh cost detail before defending run-rate pace, 7-day average, or YOY movement.",
    )

    company_env_loaded = _has_columns(chargeback, ["COMPANY", "ENVIRONMENT"]) or _has_columns(explorer, ["COMPANY", "ENVIRONMENT_ROLLUP"])
    add(
        "Company and environment view",
        "Allocated/Estimated" if company_env_loaded else "Review",
        "Company/environment split is present; database-attributed cost remains allocated where warehouse usage is shared." if company_env_loaded else "Company/environment allocation is available after refresh.",
        "Load Cost Explorer or Chargeback before explaining ALFA/Trexis or PROD/DEV cost movement.",
    )

    db_loaded = _has_columns(chargeback, ["DATABASE_NAME"]) or _has_columns(explorer, ["DATABASE_NAME"])
    allocation_confidence = pd.Series(dtype=str)
    if _has_columns(chargeback, ["ALLOCATION_CONFIDENCE"]):
        allocation_confidence = chargeback["ALLOCATION_CONFIDENCE"].fillna("").astype(str)
    elif _has_columns(explorer, ["ALLOCATION_CONFIDENCE"]):
        allocation_confidence = explorer["ALLOCATION_CONFIDENCE"].fillna("").astype(str)
    estimated_rows = int(allocation_confidence.str.contains("ESTIMATED|ALLOCATED|SHARED", case=False, regex=True).sum()) if len(allocation_confidence) else 0
    add(
        "Database attribution",
        "Allocated/Estimated" if db_loaded else "Review",
        (
            f"Database drilldown loaded; {estimated_rows:,} row(s) explicitly carry allocated/shared/estimated measurement."
            if db_loaded else "Database attribution is available after refresh."
        ),
        "Use database views for chargeback directionally; do not present shared warehouse database spend as exact.",
    )

    human_driver_loaded = _has_columns(explorer, ["ROLE_NAME", "USER_NAME", "DEPARTMENT"])
    add(
        "Role, user, department drivers",
        "Allocated/Estimated" if human_driver_loaded else "Review",
        "Human and department cost drivers are available for prioritization." if human_driver_loaded else "Role/user/department drilldown is available after refresh.",
        "Load Cost Explorer before assigning optimization work to teams or departments.",
    )

    no_database_rows = 0
    for frame in (chargeback, explorer):
        if _has_columns(frame, ["DATABASE_NAME"]):
            no_database_rows += int(frame["DATABASE_NAME"].fillna("").astype(str).str.strip().eq("").sum())
    add(
        "Shared and no-database spend",
        "Allocated/Estimated" if no_database_rows else "Ready" if db_loaded else "Review",
        (
            f"{no_database_rows:,} loaded row(s) have no database context and must stay outside exact PROD/DEV claims."
            if no_database_rows else "No loaded database-attribution rows are missing database context." if db_loaded else "Database-attribution rows are available after refresh."
        ),
        "Keep no-database, login-only, and shared-service spend labeled allocated/estimated until tag telemetry exists.",
    )

    open_cost_queue = pd.DataFrame()
    if isinstance(queue, pd.DataFrame) and not queue.empty:
        category = queue.get("CATEGORY", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
        status = queue.get("STATUS", pd.Series(["New"] * len(queue), index=queue.index)).fillna("New").astype(str).str.title()
        open_cost_queue = queue[category.str.contains("COST|CHARGEBACK|CORTEX", na=False) & ~status.isin(["Fixed", "Ignored"])].copy()
    owner_ready = 0
    verification_ready = 0
    if not open_cost_queue.empty:
        owner_ready = int(open_cost_queue.get("OWNER_SOURCE", pd.Series(dtype=str)).fillna("").astype(str).str.strip().ne("").sum())
        verification_ready = int(
            open_cost_queue.get("VERIFICATION_STATUS", pd.Series(dtype=str)).fillna("").astype(str).str.upper().str.contains("VERIFIED|PASSED|COMPLETE", regex=True).sum()
        )
    add(
        "Optimization closure trust",
        "Ready" if not open_cost_queue.empty and owner_ready == len(open_cost_queue) and verification_ready > 0 else "Review" if not open_cost_queue.empty else "No Rows",
        f"{len(open_cost_queue):,} open cost action(s); {owner_ready:,} routed; {verification_ready:,} measured/completed.",
        "Treat impact as directional until the next complete usage window confirms movement.",
    )

    board = pd.DataFrame(rows)
    if board.empty:
        return {"score": 0, "exact": 0, "estimated": 0, "review": 0, "load_needed": 0}, board
    exact = int(board["TRUST_STATE"].isin(["Exact", "Ready", "No Rows"]).sum())
    estimated = int(board["TRUST_STATE"].eq("Allocated/Estimated").sum())
    review = int(board["TRUST_STATE"].eq("Review").sum())
    load_needed = int(board["TRUST_STATE"].eq("Load Needed").sum())
    score = max(0, min(100, 100 - load_needed * 14 - review * 7 - estimated * 2))
    board["_TRUST_RANK"] = board["TRUST_STATE"].map({
        "Load Needed": 0,
        "Review": 1,
        "Allocated/Estimated": 2,
        "No Rows": 3,
        "Ready": 4,
        "Exact": 5,
    }).fillna(9)
    return {
        "score": int(score),
        "exact": exact,
        "estimated": estimated,
        "review": review,
        "load_needed": load_needed,
    }, board.sort_values(["_TRUST_RANK", "CONTROL"]).drop(columns=["_TRUST_RANK"], errors="ignore").reset_index(drop=True)


def _build_cost_drilldown_command_map(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Expose which cost drilldowns are defensible from already-loaded data."""
    state = state or st.session_state
    explorer = _state_frame(state, "df_cost_explorer_detail")
    chargeback = _state_frame(state, "df_chargeback")
    cortex_projection, cortex_exceptions = _loaded_cortex_state()

    rows: list[dict] = []

    def loaded_rows(*frames: pd.DataFrame) -> int:
        return sum(len(frame) for frame in frames if isinstance(frame, pd.DataFrame) and not frame.empty)

    def add(
        grain: str,
        state_value: str,
        trust: str,
        rows_loaded: int,
        metric: str,
        next_action: str,
        workflow: str,
        rank: int,
    ) -> None:
        rows.append({
            "COMMAND_PRIORITY": f"P{rank}",
            "DRILLDOWN": grain,
            "STATE": state_value,
            "TRUST": trust,
            "ROWS_LOADED": rows_loaded,
            "PRIMARY_METRIC": metric,
            "NEXT_ACTION": next_action,
            "WORKFLOW": workflow,
            "_RANK": rank,
        })

    current_credits = safe_float(cockpit.iloc[0].get("CURRENT_CREDITS")) if isinstance(cockpit, pd.DataFrame) and not cockpit.empty else 0.0
    prior_credits = safe_float(cockpit.iloc[0].get("PRIOR_CREDITS")) if isinstance(cockpit, pd.DataFrame) and not cockpit.empty else 0.0
    top_wh = str(cockpit.iloc[0].get("TOP_INCREASE_WAREHOUSE") or "") if isinstance(cockpit, pd.DataFrame) and not cockpit.empty else ""
    exact_loaded = _has_columns(cockpit, ["CURRENT_CREDITS", "PRIOR_CREDITS"])
    add(
        "Warehouse usage movement",
        "Ready" if exact_loaded else "Load Needed",
        "Exact",
        loaded_rows(cockpit),
        f"{current_credits:,.2f} current credits; {prior_credits:,.2f} prior credits",
        f"Explain top warehouse movement first{f': {top_wh}' if top_wh else ''}.",
        "Usage attribution and run-rate",
        0 if exact_loaded else 1,
    )

    run_loaded = _has_columns(run_rate, ["AVG_DAILY_7D", "YOY_7D_PCT", "YOY_30D_PCT"])
    add(
        "7-day average and YOY pace",
        "Ready" if run_loaded else "Load Needed",
        "Exact",
        loaded_rows(run_rate),
        (
            f"7d avg {safe_float(run_rate.iloc[0].get('AVG_DAILY_7D')):,.2f} credits; "
            f"YOY7 {safe_float(run_rate.iloc[0].get('YOY_7D_PCT')):+.1f}%"
            if run_loaded and not run_rate.empty else "No run-rate telemetry loaded"
        ),
        "Use complete-day 7d average and YOY before calling a spike real.",
        "Usage attribution and run-rate",
        0 if run_loaded else 1,
    )

    company_loaded = _has_columns(chargeback, ["COMPANY", "ENVIRONMENT"]) or _has_columns(explorer, ["COMPANY", "ENVIRONMENT_ROLLUP"])
    add(
        "Company and environment",
        "Ready" if company_loaded else "Review",
        "Allocated/Estimated",
        loaded_rows(chargeback, explorer),
        "ALFA/Trexis plus PROD/DEV split" if company_loaded else "No company/environment rows loaded",
        "Use this for chargeback direction; keep shared warehouse disclosure visible.",
        "Usage attribution and run-rate",
        2 if company_loaded else 3,
    )

    db_loaded = _has_columns(chargeback, ["DATABASE_NAME"]) or _has_columns(explorer, ["DATABASE_NAME"])
    no_db_rows = 0
    for frame in (chargeback, explorer):
        if _has_columns(frame, ["DATABASE_NAME"]):
            no_db_rows += int(frame["DATABASE_NAME"].fillna("").astype(str).str.strip().eq("").sum())
    add(
        "Database, DEV rollup, no-database spend",
        "Ready" if db_loaded else "Review",
        "Allocated/Estimated",
        loaded_rows(chargeback, explorer),
        f"{no_db_rows:,} no-database row(s)" if db_loaded else "Database rows are available after refresh",
        "Show PROD, DEV_ALL, individual DEV databases, and keep no-database spend out of exact claims.",
        "Usage attribution and run-rate",
        2 if db_loaded else 3,
    )

    human_loaded = _has_columns(explorer, ["ROLE_NAME", "USER_NAME", "DEPARTMENT"])
    add(
        "Role, user, department",
        "Ready" if human_loaded else "Review",
        "Allocated/Estimated",
        loaded_rows(explorer),
        "Role/user/department drivers ready" if human_loaded else "Human driver rows are available after refresh",
        "Sort by estimated dollars before assigning work to a department or user.",
        "Usage attribution and run-rate",
        2 if human_loaded else 3,
    )

    open_cost_queue = pd.DataFrame()
    if isinstance(queue, pd.DataFrame) and not queue.empty:
        mask = _cost_action_mask(queue)
        open_cost_queue = queue[mask].copy()
    verified = 0
    if not open_cost_queue.empty:
        verified = int(
            open_cost_queue.get("VERIFICATION_STATUS", pd.Series(dtype=str)).fillna("").astype(str).str.upper().str.contains(
                "VERIFIED|PASSED|COMPLETE",
                regex=True,
            ).sum()
        )
    add(
        "Optimization closure status",
        "Ready" if not open_cost_queue.empty and verified else "Review" if not open_cost_queue.empty else "No Rows",
        "Measured after change",
        len(open_cost_queue),
        f"{verified:,} measured/completed action(s)",
        "Treat impact as directional until the next complete usage window confirms movement.",
        "Recommendations and action queue",
        2 if verified else 3,
    )

    add(
        "AI and Cortex spend",
        "Ready" if cortex_projection > 0 or cortex_exceptions > 0 else "No Rows",
        "Allocated/Estimated",
        cortex_exceptions,
        f"${cortex_projection:,.0f}/30d projection; {cortex_exceptions:,} exception(s)",
        "Review first/last usage, user attribution, and projected token-credit spend.",
        "AI and Cortex spend",
        2 if cortex_projection > 0 or cortex_exceptions > 0 else 4,
    )

    board = pd.DataFrame(rows)
    if board.empty:
        return {"ready": 0, "review": 0, "load_needed": 0, "estimated": 0}, board
    ready = int(board["STATE"].isin(["Ready", "No Rows"]).sum())
    review = int(board["STATE"].eq("Review").sum())
    load_needed = int(board["STATE"].eq("Load Needed").sum())
    estimated = int(board["TRUST"].eq("Allocated/Estimated").sum())
    return {
        "ready": ready,
        "review": review,
        "load_needed": load_needed,
        "estimated": estimated,
    }, board.sort_values(["_RANK", "DRILLDOWN"]).drop(columns=["_RANK"], errors="ignore").reset_index(drop=True)


def _render_cost_control_coverage_board(
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
) -> None:
    summary, board = _build_cost_control_coverage_board(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
    )
    if board.empty:
        return
    st.markdown("**Cost Control Coverage**")
    render_shell_snapshot((
        ("Ready", f"{summary['ready']:,}"),
        ("Review", f"{summary['review']:,}"),
        ("Load Needed", f"{summary['load_needed']:,}"),
    ))
    render_priority_dataframe(
        board,
        title="Cost telemetry coverage",
        priority_columns=["STATE", "CONTROL", "EVIDENCE", "NEXT_ACTION", "OWNER"],
        sort_by=["STATE", "CONTROL"],
        ascending=[True, True],
        raw_label="All cost control coverage rows",
        max_rows=12,
    )


def _render_cost_allocation_trust_board(
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
) -> None:
    summary, board = _build_cost_allocation_trust_board(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
    )
    if board.empty:
        return
    st.markdown("**Cost Allocation Trust**")
    render_shell_snapshot((
        ("Exact / Ready", f"{summary['exact']:,}"),
        ("Allocated / Estimated", f"{summary['estimated']:,}"),
        ("Review / Load", f"{summary['review'] + summary['load_needed']:,}"),
    ))
    render_priority_dataframe(
        board,
        title="Cost attribution trust states",
        priority_columns=["TRUST_STATE", "CONTROL", "EVIDENCE", "NEXT_ACTION", "OWNER"],
        sort_by=["TRUST_STATE", "CONTROL"],
        ascending=[True, True],
        raw_label="All cost allocation trust rows",
        max_rows=10,
    )


def _render_cost_drilldown_command_map(
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
) -> None:
    summary, board = _build_cost_drilldown_command_map(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
    )
    if board.empty:
        return
    st.markdown("**Cost Drilldown Status**")
    render_shell_snapshot((
        ("Ready", f"{summary['ready']:,}"),
        ("Review", f"{summary['review']:,}"),
        ("Load Needed", f"{summary['load_needed']:,}"),
        ("Allocated", f"{summary['estimated']:,}"),
    ))
    render_priority_dataframe(
        board,
        title="Cost drilldowns to trust or load next",
        priority_columns=[
            "COMMAND_PRIORITY", "STATE", "DRILLDOWN", "TRUST", "ROWS_LOADED", "PRIMARY_METRIC",
            "NEXT_ACTION", "WORKFLOW",
        ],
        sort_by=["COMMAND_PRIORITY", "DRILLDOWN"],
        ascending=[True, True],
        raw_label="All cost drilldown status rows",
        height=280,
        max_rows=10,
    )


def _build_cost_decomposition_board(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Summarize the highest-value cost decomposition paths already visible in the session."""
    state = state or st.session_state
    explorer = _state_frame(state, "df_cost_explorer_detail")
    chargeback = _state_frame(state, "df_chargeback")
    rows: list[dict] = []

    def add(driver: str, status: str, trust: str, evidence: str, next_action: str) -> None:
        rows.append({
            "DRIVER": driver,
            "STATUS": status,
            "TRUST": trust,
            "EVIDENCE": evidence,
            "NEXT_ACTION": next_action,
        })

    exact_loaded = _has_columns(cockpit, ["CURRENT_CREDITS", "PRIOR_CREDITS"])
    run_loaded = _has_columns(run_rate, ["AVG_DAILY_7D", "YOY_7D_PCT", "YOY_30D_PCT"])
    company_loaded = _has_columns(chargeback, ["COMPANY", "ENVIRONMENT"]) or _has_columns(explorer, ["COMPANY", "ENVIRONMENT_ROLLUP"])
    db_loaded = _has_columns(chargeback, ["DATABASE_NAME"]) or _has_columns(explorer, ["DATABASE_NAME"])
    human_loaded = _has_columns(explorer, ["ROLE_NAME", "USER_NAME", "DEPARTMENT"])

    open_cost_queue = pd.DataFrame()
    if isinstance(queue, pd.DataFrame) and not queue.empty:
        open_cost_queue = queue[_cost_action_mask(queue)].copy()

    if exact_loaded:
        current_credits = safe_float(cockpit.iloc[0].get("CURRENT_CREDITS"))
        prior_credits = safe_float(cockpit.iloc[0].get("PRIOR_CREDITS"))
        delta = current_credits - prior_credits
        add(
            "Warehouse movement",
            "Ready",
            "Exact",
            f"Current credits {current_credits:,.2f} vs prior {prior_credits:,.2f} ({delta:+,.2f}).",
            "Start with the warehouse that moved most before blaming user, query, or database behavior.",
        )
    else:
        add(
            "Warehouse movement",
            "Load Needed",
            "Review",
            "Exact warehouse metering is available after refresh.",
            "Load the Cost Control Cockpit before explaining usage movement.",
        )

    if run_loaded:
        avg_7d = safe_float(run_rate.iloc[0].get("AVG_DAILY_7D"))
        yoy_7d_pct = safe_float(run_rate.iloc[0].get("YOY_7D_PCT"))
        yoy_30d_pct = safe_float(run_rate.iloc[0].get("YOY_30D_PCT"))
        add(
            "7-day average and YOY",
            "Ready",
            "Exact",
            f"7d avg {avg_7d:,.2f} credits/day; YOY 7d {yoy_7d_pct:+.1f}%; YOY 30d {yoy_30d_pct:+.1f}%.",
            "Use complete-day average and YOY before calling a spike or dip real.",
        )
    else:
        add(
            "7-day average and YOY",
            "Load Needed",
            "Review",
            "Run-rate trend context is available after refresh.",
            "Reload the run-rate lens before making trend claims.",
        )

    add(
        "Company and environment split",
        "Ready" if company_loaded else "Review",
        "Allocated/Estimated",
        "Company/environment split is present." if company_loaded else "Company/environment attribution is available after refresh.",
        "Use this for ALFA/Trexis and PROD/DEV direction, not as exact allocation.",
    )
    add(
        "Database, DEV rollup, no-database spend",
        "Ready" if db_loaded else "Review",
        "Allocated/Estimated",
        "Database-attributed rows are present." if db_loaded else "Database attribution is available after refresh.",
        "Show PROD, DEV_ALL, individual DEV databases, and keep shared/no-db spend labeled allocated or estimated.",
    )
    add(
        "Role, user, department drivers",
        "Ready" if human_loaded else "Review",
        "Allocated/Estimated",
        "Role, user, and department dimensions are available." if human_loaded else "Human driver rows are available after refresh.",
        "Sort by estimated dollars before assigning optimization work.",
    )
    add(
        "Open cost action queue",
        "Ready" if not open_cost_queue.empty else "No Rows",
        "Measured after change" if not open_cost_queue.empty else "No Rows",
        f"{len(open_cost_queue):,} open cost action(s)." if not open_cost_queue.empty else "No cost actions are loaded.",
        "Use the queue to close savings with route, status, and post-period measurement.",
    )

    board = pd.DataFrame(rows)
    if board.empty:
        return {"score": 0, "ready": 0, "review": 0}, board
    ready = int(board["STATUS"].eq("Ready").sum())
    review = int(board["STATUS"].eq("Review").sum()) + int(board["STATUS"].eq("Load Needed").sum())
    exact = int(board["TRUST"].eq("Exact").sum())
    score = max(0, min(100, 100 - review * 12 - max(0, exact - 2) * 1))
    board["_RANK"] = board["STATUS"].map({"Load Needed": 0, "Review": 1, "Ready": 2, "No Rows": 3}).fillna(9)
    return {
        "score": int(score),
        "ready": ready,
        "review": review,
    }, board.sort_values(["_RANK", "DRIVER"]).drop(columns=["_RANK"], errors="ignore").reset_index(drop=True)


def _render_cost_decomposition_board(
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
) -> None:
    summary, board = _build_cost_decomposition_board(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
    )
    if board.empty:
        return
    st.markdown("**Cost Decomposition**")
    render_shell_snapshot((
        ("Ready", f"{summary['ready']:,}"),
        ("Review", f"{summary['review']:,}"),
        ("Drivers", f"{len(board):,}"),
    ))
    render_priority_dataframe(
        board,
        title="Cost decomposition and next trust step",
        priority_columns=["STATUS", "DRIVER", "TRUST", "EVIDENCE", "NEXT_ACTION"],
        sort_by=["STATUS", "DRIVER"],
        ascending=[True, True],
        raw_label="All cost decomposition rows",
        max_rows=10,
    )


def _cost_command_severity_rank(value: object) -> int:
    return {"Critical": 0, "High": 1, "Medium": 2, "Watch": 3, "Info": 4}.get(str(value or "Info"), 9)


def _first_frame_value(frame: pd.DataFrame | None, column: str, default: object = "") -> object:
    if frame is None or getattr(frame, "empty", True) or column not in frame.columns:
        return default
    return frame.iloc[0].get(column, default)


def _open_cost_action_frame(queue: pd.DataFrame | None) -> pd.DataFrame:
    if queue is None or getattr(queue, "empty", True):
        return pd.DataFrame()
    view = queue.loc[_cost_action_mask(queue)].copy()
    if view.empty:
        return view
    status = _queue_series(view, "STATUS", "New").fillna("New").astype(str).str.upper()
    return view[~status.isin(["FIXED", "IGNORED"])].copy()


def _cost_column(frame: pd.DataFrame, candidates: list[str]) -> str:
    if frame is None or getattr(frame, "empty", True):
        return ""
    columns = {str(col).upper(): str(col) for col in frame.columns}
    for candidate in candidates:
        column = columns.get(str(candidate).upper())
        if column:
            return column
    return ""


def _cost_metric_column(frame: pd.DataFrame) -> str:
    return _cost_column(
        frame,
        [
            "EST_COST", "COST_USD", "ESTIMATED_COST_USD", "TOTAL_COST_USD",
            "TOTAL_CREDITS", "ALLOCATED_CREDITS", "CREDITS_USED", "CREDITS",
        ],
    )


def _cost_metric_to_usd(metric_column: str, value: float, credit_price: float) -> float:
    metric = str(metric_column or "").upper()
    if "USD" in metric or "COST" in metric:
        return safe_float(value)
    return credits_to_dollars(safe_float(value), credit_price)


def _top_loaded_cost_driver(
    frame: pd.DataFrame,
    dimensions: list[str],
    *,
    credit_price: float,
) -> dict:
    dim = _cost_column(frame, dimensions)
    metric = _cost_metric_column(frame)
    if not dim or not metric or frame is None or getattr(frame, "empty", True):
        return {
            "dimension": "",
            "entity": "",
            "metric": "",
            "value": 0.0,
            "value_usd": 0.0,
            "rows": 0,
        }
    work = frame[[dim, metric]].copy()
    work[dim] = work[dim].fillna("").astype(str).str.strip()
    work = work[work[dim].ne("")]
    if work.empty:
        return {
            "dimension": dim,
            "entity": "",
            "metric": metric,
            "value": 0.0,
            "value_usd": 0.0,
            "rows": 0,
        }
    work[metric] = pd.to_numeric(work[metric], errors="coerce").fillna(0.0)
    grouped = work.groupby(dim, dropna=False, as_index=False).agg(
        VALUE=(metric, "sum"),
        ROWS=(metric, "size"),
    )
    grouped = grouped.sort_values(["VALUE", "ROWS"], ascending=[False, False])
    row = grouped.iloc[0]
    value = safe_float(row.get("VALUE"))
    return {
        "dimension": dim,
        "entity": str(row.get(dim) or "").strip(),
        "metric": metric,
        "value": value,
        "value_usd": round(_cost_metric_to_usd(metric, value, credit_price), 2),
        "rows": safe_int(row.get("ROWS")),
    }


def _build_resource_monitor_guardrail_sql(
    warehouse_name: str,
    *,
    credit_quota: float,
    monitor_name: str = "",
) -> str:
    wh = safe_identifier(warehouse_name or "TOP_WAREHOUSE")
    quota = max(safe_float(credit_quota), 1.0)
    monitor = safe_identifier(monitor_name or f"OVERWATCH_{wh}_RM")
    return f"""-- Review-only resource monitor guardrail for a user-managed warehouse.
-- Resource monitors are warehouse-only controls; use separate spend thresholds for serverless, shared, and AI costs.
-- Notification email must be enabled/verified in Snowflake user preferences; NOTIFY_USERS accepts Snowflake user names, not email addresses.
USE ROLE ACCOUNTADMIN;

CREATE RESOURCE MONITOR IF NOT EXISTS {monitor}
  WITH CREDIT_QUOTA = {quota:.2f}
       FREQUENCY = MONTHLY
       START_TIMESTAMP = IMMEDIATELY
       TRIGGERS ON 75 PERCENT DO NOTIFY
                ON 90 PERCENT DO SUSPEND
                ON 100 PERCENT DO SUSPEND_IMMEDIATE;

ALTER RESOURCE MONITOR IF EXISTS {monitor}
  SET CREDIT_QUOTA = {quota:.2f};

ALTER WAREHOUSE IF EXISTS {wh}
  SET RESOURCE_MONITOR = {monitor};

SHOW RESOURCE MONITORS;
SHOW WAREHOUSES LIKE {sql_literal(warehouse_name or "TOP_WAREHOUSE", 200)};
"""


def _build_cost_spike_root_cause_board(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    credit_price: float,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    state = state or st.session_state
    explorer = _state_frame(state, "df_cost_explorer_detail")
    chargeback = _state_frame(state, "df_chargeback")
    current_credits = safe_float(_first_frame_value(cockpit, "CURRENT_CREDITS", 0))
    prior_credits = safe_float(_first_frame_value(cockpit, "PRIOR_CREDITS", 0))
    top_wh = str(_first_frame_value(cockpit, "TOP_INCREASE_WAREHOUSE", "On demand") or "On demand")
    top_delta = safe_float(_first_frame_value(cockpit, "TOP_INCREASE_CREDITS", 0))
    delta_pct = ((current_credits - prior_credits) / prior_credits * 100) if prior_credits > 0 else 0.0
    avg_7d = safe_float(_first_frame_value(run_rate, "AVG_DAILY_7D", 0))
    avg_30d = safe_float(_first_frame_value(run_rate, "AVG_DAILY_30D", 0))
    pct_vs_30d = _first_frame_value(run_rate, "PCT_VS_30D_AVG", None)
    pct_vs_30d_float = safe_float(pct_vs_30d) if pct_vs_30d is not None and not pd.isna(pct_vs_30d) else 0.0
    yoy_7d = _first_frame_value(run_rate, "YOY_7D_PCT", None)
    yoy_7d_float = safe_float(yoy_7d) if yoy_7d is not None and not pd.isna(yoy_7d) else 0.0
    open_cost_queue = _open_cost_action_frame(queue)
    cortex_projection, cortex_exceptions = _loaded_cortex_state()

    rows: list[dict] = []

    def add(
        severity: str,
        driver: str,
        entity: str,
        signal: str,
        evidence: str,
        confidence: str,
        trust: str,
        next_action: str,
        proof: str,
        route: str,
        value: float,
        rank: int,
    ) -> None:
        rows.append({
            "SEVERITY": severity,
            "DRIVER": driver,
            "ENTITY": entity,
            "ROOT_CAUSE_SIGNAL": signal,
            "EVIDENCE": evidence,
            "CONFIDENCE": confidence,
            "TRUST": trust,
            "NEXT_ACTION": next_action,
            "PROOF_REQUIRED": proof,
            "ROUTE": route,
            "VALUE_AT_RISK_USD": round(safe_float(value), 2),
            "_RANK": rank,
        })

    movement_severity = "Critical" if delta_pct >= 50 and top_delta > 0 else "High" if top_delta > 0 or delta_pct >= 20 else "Info"
    add(
        movement_severity,
        "Warehouse movement",
        top_wh,
        "Top warehouse delta",
        f"{top_wh}: {top_delta:+,.2f} credits; window ${credits_to_dollars(current_credits, credit_price):,.0f} vs prior ${credits_to_dollars(prior_credits, credit_price):,.0f} ({delta_pct:+.1f}%).",
        "High" if top_delta > 0 else "Medium",
        "Exact warehouse metering",
        "Start here. Confirm owner demand, task/query mix, size/auto-suspend changes, and monitor coverage for this warehouse.",
        "WAREHOUSE_METERING_HISTORY current/prior window and top delta.",
        "Cost & Contract > Usage attribution and run-rate",
        max(credits_to_dollars(top_delta, credit_price), credits_to_dollars(current_credits - prior_credits, credit_price), 0),
        0,
    )
    trend_severity = "High" if pct_vs_30d_float >= 20 or yoy_7d_float >= 25 else "Medium" if pct_vs_30d_float >= 10 or yoy_7d_float >= 15 else "Info"
    add(
        trend_severity,
        "Complete-day trend",
        top_wh,
        "7d / 30d / YOY baseline",
        f"7d avg {avg_7d:,.2f} cr/day vs 30d {avg_30d:,.2f}; 7d vs 30d {pct_vs_30d_float:+.1f}%; YOY7 {yoy_7d_float:+.1f}%.",
        "High" if _has_columns(run_rate, ["AVG_DAILY_7D", "AVG_DAILY_30D"]) else "Low",
        "Exact when run-rate lens loaded",
        "Do not escalate from same-day partial metering; use complete-day trend to decide whether this is a real spike.",
        "Cost run-rate lens with complete-day 7d, 30d, and prior-year rows.",
        "Cost & Contract > Usage attribution and run-rate",
        credits_to_dollars(abs(top_delta), credit_price),
        1,
    )

    company_driver = _top_loaded_cost_driver(chargeback if not chargeback.empty else explorer, ["COMPANY", "ENVIRONMENT", "ENVIRONMENT_ROLLUP"], credit_price=credit_price)
    add(
        "Medium" if company_driver["entity"] else "Watch",
        "Company / environment attribution",
        company_driver["entity"] or "On demand",
        "Chargeback direction",
        (
            f"Top {company_driver['dimension']} is {company_driver['entity']} at ${company_driver['value_usd']:,.0f} across {company_driver['rows']:,} row(s)."
            if company_driver["entity"] else "Company/environment cost attribution is available after refresh."
        ),
        "Medium" if company_driver["entity"] else "Low",
        "Allocated / Estimated",
        "Use ALFA/Trexis and PROD/DEV attribution to assign ownership, but keep shared warehouse disclosure attached.",
        "Cost Explorer or Chargeback rows with company/environment dimensions and allocation measurement.",
        "Cost & Contract > Usage attribution and run-rate",
        company_driver["value_usd"],
        2,
    )

    db_driver = _top_loaded_cost_driver(chargeback if not chargeback.empty else explorer, ["DATABASE_NAME", "ENVIRONMENT", "ENVIRONMENT_ROLLUP"], credit_price=credit_price)
    add(
        "Medium" if db_driver["entity"] else "Watch",
        "Database / DEV rollup",
        db_driver["entity"] or "On demand",
        "Database-attributed cost candidate",
        (
            f"Top {db_driver['dimension']} is {db_driver['entity']} at ${db_driver['value_usd']:,.0f} across {db_driver['rows']:,} row(s)."
            if db_driver["entity"] else "Database-level attribution is available after refresh."
        ),
        "Medium" if db_driver["entity"] else "Low",
        "Allocated / Estimated",
        "Drill into PROD, DEV_ALL, and individual DEV database views before assigning database ownership.",
        "Query allocation, tags, and no-database/shared allocation measurement.",
        "Cost & Contract > Usage attribution and run-rate",
        db_driver["value_usd"],
        3,
    )

    human_driver = _top_loaded_cost_driver(explorer, ["ROLE_NAME", "USER_NAME", "DEPARTMENT"], credit_price=credit_price)
    add(
        "Medium" if human_driver["entity"] else "Watch",
        "Role / user / department",
        human_driver["entity"] or "On demand",
        "Human ownership candidate",
        (
            f"Top {human_driver['dimension']} is {human_driver['entity']} at ${human_driver['value_usd']:,.0f} across {human_driver['rows']:,} row(s)."
            if human_driver["entity"] else "Role, user, and department drilldown is available after refresh."
        ),
        "Medium" if human_driver["entity"] else "Low",
        "Allocated / Estimated",
        "Assign optimization work only after the cost row has role/user/department telemetry and route context.",
        "Cost Explorer detail with role, user, department, query count, and allocation measurement.",
        "Cost & Contract > Usage attribution and run-rate",
        human_driver["value_usd"],
        4,
    )

    savings = (
        safe_float(pd.to_numeric(open_cost_queue.get("EST_MONTHLY_SAVINGS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        if not open_cost_queue.empty else 0.0
    )
    add(
        "High" if savings > 0 else "Info",
        "Open savings queue",
        f"{len(open_cost_queue):,} open cost action(s)",
        "Existing remediation candidates",
        f"${savings:,.0f}/mo estimated savings loaded; keep savings estimated until measured.",
        "Medium" if not open_cost_queue.empty else "Low",
        "Measured after change",
        "Work measured actions first; reject fixed rows without post-period measurement.",
        "OVERWATCH_ACTION_QUEUE route, ticket, baseline/current values, and scheduled status.",
        "Cost & Contract > Recommendations and action queue",
        savings,
        5,
    )
    add(
        "High" if cortex_projection > 0 or cortex_exceptions > 0 else "Info",
        "AI / Cortex usage",
        "Cortex",
        "AI spend or quota candidate",
        f"Projection ${cortex_projection:,.0f}/30d; {cortex_exceptions:,} exception(s).",
        "Medium" if cortex_projection > 0 or cortex_exceptions > 0 else "Low",
        "Allocated / Estimated",
        "Open AI and Cortex spend to confirm first/last usage, user attribution, and quota route.",
        "Cortex usage history, user attribution, shared AI spend threshold, and per-user quota action rows.",
        "Cost & Contract > AI and Cortex spend",
        cortex_projection,
        6,
    )

    board = pd.DataFrame(rows)
    if board.empty:
        return {"score": 0, "critical_high": 0, "top_driver": "No loaded root-cause telemetry"}, board
    board["_SEVERITY_RANK"] = board["SEVERITY"].apply(_cost_command_severity_rank)
    board = board.sort_values(["_SEVERITY_RANK", "VALUE_AT_RISK_USD", "_RANK"], ascending=[True, False, True])
    critical_high = int(board["SEVERITY"].isin(["Critical", "High"]).sum())
    candidate = int(board["CONFIDENCE"].isin(["Low", "Medium"]).sum())
    score = max(0, min(100, 100 - critical_high * 10 - candidate * 4))
    top = board.iloc[0]
    return {
        "score": int(score),
        "critical_high": critical_high,
        "candidate": candidate,
        "top_driver": str(top.get("DRIVER") or "Cost root cause"),
        "top_entity": str(top.get("ENTITY") or "Unknown"),
        "top_action": str(top.get("NEXT_ACTION") or "Open Cost & Contract drilldown."),
    }, board.drop(columns=["_SEVERITY_RANK", "_RANK"], errors="ignore").reset_index(drop=True)


def _build_change_cost_correlation_board(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    state = state or st.session_state
    changes = _state_frame(state, "change_drift_exceptions")
    operability = _state_frame(state, "change_control_operability_fact")
    current_credits = safe_float(_first_frame_value(cockpit, "CURRENT_CREDITS", 0))
    prior_credits = safe_float(_first_frame_value(cockpit, "PRIOR_CREDITS", 0))
    top_wh = str(_first_frame_value(cockpit, "TOP_INCREASE_WAREHOUSE", "") or "").strip()
    top_delta = safe_float(_first_frame_value(cockpit, "TOP_INCREASE_CREDITS", 0))
    pct_vs_30d = _first_frame_value(run_rate, "PCT_VS_30D_AVG", None)
    pct_vs_30d_float = safe_float(pct_vs_30d) if pct_vs_30d is not None and not pd.isna(pct_vs_30d) else 0.0
    spike_signal = top_delta > 0 or current_credits > prior_credits or pct_vs_30d_float >= 10
    rows: list[dict] = []

    def add(
        severity: str,
        correlation: str,
        entity: str,
        cost_signal: str,
        change_signal: str,
        evidence: str,
        next_action: str,
        proof: str,
        route: str,
        rank: int,
    ) -> None:
        rows.append({
            "SEVERITY": severity,
            "CORRELATION": correlation,
            "ENTITY": entity,
            "COST_SIGNAL": cost_signal,
            "CHANGE_SIGNAL": change_signal,
            "EVIDENCE": evidence,
            "NEXT_ACTION": next_action,
            "PROOF_REQUIRED": proof,
            "ROUTE": route,
            "_RANK": rank,
        })

    if changes.empty:
        add(
            "Medium" if spike_signal else "Watch",
            "Change correlation pending",
            top_wh or "Cost scope",
            f"Top warehouse delta {top_delta:+,.2f} credits; 7d vs 30d {pct_vs_30d_float:+.1f}%.",
            "No Security Monitoring change exceptions are ready for this scope.",
            "Cost movement cannot be cleared of change-correlation risk until Security Monitoring is reviewed for the same scope.",
            "Refresh Security Monitoring change telemetry, then compare warehouse, query, task/procedure, grant, and policy events to the cost spike.",
            "Security Monitoring change exceptions plus Cost Cockpit/run-rate telemetry for the same company/environment window.",
            "Security Monitoring > Object and access changes",
            0,
        )
    else:
        view = changes.copy()
        text_cols = []
        for column in ["ENTITY", "WAREHOUSE_NAME", "QUERY_ID", "FINDING_TYPE", "QUERY_TAG", "USER_NAME", "ROLE_NAME"]:
            if column in view.columns:
                text_cols.append(column)
        combined = view[text_cols].fillna("").astype(str).agg(" | ".join, axis=1) if text_cols else pd.Series([""] * len(view), index=view.index)
        top_matches = combined.str.upper().str.contains(str(top_wh).upper(), na=False) if top_wh else pd.Series([False] * len(view), index=view.index)
        finding = view.get("FINDING_TYPE", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str)
        severity = view.get("SEVERITY", pd.Series(["Medium"] * len(view), index=view.index)).fillna("Medium").astype(str)
        high_rows = int(severity.str.upper().isin(["CRITICAL", "HIGH"]).sum())
        warehouse_changes = int((finding.str.contains("WAREHOUSE|TASK|PROCEDURE|DRIFT", case=False, regex=True) | top_matches).sum())
        access_ai_changes = int(finding.str.contains("GRANT|ROLE|POLICY|TAG|AI|CORTEX", case=False, regex=True).sum())
        matched_rows = int(top_matches.sum())
        latest = view.iloc[0]
        matched_entity = str(latest.get("ENTITY") or latest.get("WAREHOUSE_NAME") or top_wh or "Snowflake account")
        add(
            "High" if matched_rows and spike_signal else "Medium" if warehouse_changes and spike_signal else "Info",
            "Top warehouse change proximity",
            top_wh or matched_entity,
            f"Top warehouse delta {top_delta:+,.2f} credits; 7d vs 30d {pct_vs_30d_float:+.1f}%.",
            f"{matched_rows:,} row(s) mention the top warehouse; {warehouse_changes:,} warehouse/task/procedure/drift row(s) loaded.",
            "A cost spike near warehouse/task/procedure drift must be treated as a root-cause candidate until query/change telemetry clears it.",
            "Review query_id, actor, warehouse settings, task/procedure runtime, and rollback status before tuning cost controls.",
            "Change exception query_id, WAREHOUSE_METERING_HISTORY, QUERY_HISTORY, task/procedure history, and post-change telemetry.",
            "Security Monitoring > Controlled DBA actions",
            0,
        )
        add(
            "High" if high_rows and spike_signal else "Medium" if high_rows else "Info",
            "High-risk change near cost movement",
            matched_entity,
            f"Cost movement active={spike_signal}; top warehouse {top_wh or 'On demand'}.",
            f"{high_rows:,} Critical/High change exception(s) loaded.",
            "High-severity object/access/policy changes near cost movement require a bill explanation, not just a cost chart.",
            "Record change ticket, query_id, actor, object, and blast-radius telemetry on the cost incident.",
            "Object-change telemetry, object/access change rows, and Cost & Contract root-cause board.",
            "Security Monitoring > Object and access changes",
            1,
        )
        add(
            "Medium" if access_ai_changes else "Info",
            "AI/access policy cost route",
            "AI / access control",
            "Cortex spend movement may be user-access driven.",
            f"{access_ai_changes:,} grant/role/policy/tag/AI-related change row(s) loaded.",
            "AI spend jumps can be caused by access expansion, tag mistakes, or policy changes as much as workload growth.",
            "Compare Cortex first/last usage to access and tag changes before enforcing per-user quotas.",
            "Cortex usage history, Security Monitoring grants/policy rows, and tag assignments.",
            "Cost & Contract > AI and Cortex spend",
            2,
        )

    if not operability.empty:
        blocked = int(pd.to_numeric(operability.get("ROUTE_BLOCKED", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        closure = int(pd.to_numeric(operability.get("CLOSURE_BLOCKED", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        add(
            "High" if blocked + closure > 0 and spike_signal else "Info",
            "Object-change telemetry blocker",
            "Object-change summary",
            f"Cost movement active={spike_signal}.",
            f"{blocked:,} route blocker(s); {closure:,} closure blocker(s).",
            "Do not mark a cost incident resolved while related object-change telemetry is still blocked.",
            "Work object-change blockers before declaring the cost spike explained or resolved.",
            "FACT_CHANGE_CONTROL_OPERABILITY_DAILY with route and telemetry blocker counts.",
            "Security Monitoring > Object and access changes",
            3,
        )

    board = pd.DataFrame(rows)
    if board.empty:
        return {"score": 0, "high": 0, "top_correlation": "No change/cost telemetry"}, board
    board["_SEVERITY_RANK"] = board["SEVERITY"].apply(_cost_command_severity_rank)
    board = board.sort_values(["_SEVERITY_RANK", "_RANK"], ascending=[True, True])
    high = int(board["SEVERITY"].isin(["Critical", "High"]).sum())
    medium = int(board["SEVERITY"].eq("Medium").sum())
    score = max(0, min(100, 100 - high * 16 - medium * 7))
    top = board.iloc[0]
    return {
        "score": int(score),
        "high": high,
        "medium": medium,
        "top_correlation": str(top.get("CORRELATION") or "Change/cost correlation"),
        "top_entity": str(top.get("ENTITY") or "Unknown"),
        "top_action": str(top.get("NEXT_ACTION") or "Load Security Monitoring and compare to Cost & Contract."),
    }, board.drop(columns=["_SEVERITY_RANK", "_RANK"], errors="ignore").reset_index(drop=True)


def _cost_alert_message(row: pd.Series, *keys: str, default: str = "") -> str:
    for key in keys:
        if key in row.index:
            value = row.get(key)
            try:
                if pd.isna(value):
                    continue
            except Exception:
                pass
            text = str(value or "").strip()
            if text:
                return text
    return default


def _build_cost_monitoring_alert_rows(
    *,
    root_cause: pd.DataFrame | None = None,
    correlation: pd.DataFrame | None = None,
    email_target: str = DEFAULT_ALERT_EMAIL,
) -> tuple[dict, pd.DataFrame]:
    """Create Alert Center-ready rows from loaded Cost & Contract monitoring telemetry."""
    rows: list[dict] = []

    def add(
        *,
        severity: str,
        alert_type: str,
        entity: str,
        message: str,
        suggested_action: str,
        proof_query: str,
        route: str,
        owner: str,
        value_at_risk: float = 0.0,
        source_surface: str,
    ) -> None:
        severity = str(severity or "Medium").title()
        if severity not in {"Critical", "High", "Medium", "Watch", "Info"}:
            severity = "Medium"
        entity = str(entity or "Cost Monitoring").strip()
        rows.append({
            "SEVERITY": severity,
            "CATEGORY": "Cost Control",
            "ALERT_TYPE": alert_type,
            "ENTITY_NAME": entity,
            "MESSAGE": message,
            "SUGGESTED_ACTION": suggested_action,
            "PROOF_QUERY": proof_query,
            "ROUTE": route or "Cost & Contract",
            "OWNER": owner or "DBA / Cost owner",
            "EMAIL_TARGET": email_target or DEFAULT_ALERT_EMAIL,
            "STATUS": "New",
            "VALUE_AT_RISK_USD": round(safe_float(value_at_risk), 2),
            "SOURCE_SURFACE": source_surface,
        })

    if isinstance(root_cause, pd.DataFrame) and not root_cause.empty:
        view = root_cause.copy()
        view.columns = [str(col).upper() for col in view.columns]
        high = view[view.get("SEVERITY", pd.Series(index=view.index, dtype=str)).fillna("").astype(str).str.title().isin(["Critical", "High"])]
        if "VALUE_AT_RISK_USD" in high.columns:
            high = high.sort_values("VALUE_AT_RISK_USD", ascending=False)
        for _, row in high.head(6).iterrows():
            add(
                severity=_cost_alert_message(row, "SEVERITY", default="High"),
                alert_type="Cost Root Cause Candidate",
                entity=_cost_alert_message(row, "ENTITY", "DRIVER", default="Cost root cause"),
                message=_cost_alert_message(row, "EVIDENCE", default="Cost root-cause candidate requires review."),
                suggested_action=_cost_alert_message(row, "NEXT_ACTION", default="Open Cost & Contract root-cause drilldown."),
                proof_query=_cost_alert_message(row, "PROOF_REQUIRED", default="Record warehouse metering, run-rate, routing, and change telemetry."),
                route=_cost_alert_message(row, "ROUTE", default="Cost & Contract"),
                owner="DBA / Cost owner",
                value_at_risk=safe_float(row.get("VALUE_AT_RISK_USD", 0)),
                source_surface="Cost Spike Root Cause",
            )

    if isinstance(correlation, pd.DataFrame) and not correlation.empty:
        view = correlation.copy()
        view.columns = [str(col).upper() for col in view.columns]
        high = view[view.get("SEVERITY", pd.Series(index=view.index, dtype=str)).fillna("").astype(str).str.title().isin(["Critical", "High"])]
        for _, row in high.head(5).iterrows():
            add(
                severity=_cost_alert_message(row, "SEVERITY", default="High"),
                alert_type="Change Cost Correlation",
                entity=_cost_alert_message(row, "ENTITY", "CORRELATION", default="Change/cost correlation"),
                message=_cost_alert_message(row, "EVIDENCE", default="A recent change may explain cost movement."),
                suggested_action=_cost_alert_message(row, "NEXT_ACTION", default="Compare change telemetry to cost movement before tuning."),
                proof_query=_cost_alert_message(row, "PROOF_REQUIRED", default="Record change query_id, actor, ticket, and cost telemetry."),
                route=_cost_alert_message(row, "ROUTE", default="Security Monitoring"),
                owner="DBA / Cost owner",
                value_at_risk=0.0,
                source_surface="Change + Cost Correlation",
            )

    board = pd.DataFrame(rows)
    if board.empty:
        return {
            "alert_count": 0,
            "critical_high": 0,
            "email_target": email_target or DEFAULT_ALERT_EMAIL,
            "top_alert": "No loaded Cost & Contract alert candidates",
        }, board
    board["_SEVERITY_RANK"] = board["SEVERITY"].apply(_cost_command_severity_rank)
    board = board.sort_values(["_SEVERITY_RANK", "VALUE_AT_RISK_USD"], ascending=[True, False])
    board = board.drop_duplicates(subset=["ALERT_TYPE", "ENTITY_NAME", "MESSAGE"], keep="first")
    top = board.iloc[0]
    summary = {
        "alert_count": int(len(board)),
        "critical_high": int(board["SEVERITY"].isin(["Critical", "High"]).sum()),
        "email_target": email_target or DEFAULT_ALERT_EMAIL,
        "top_alert": f"{top.get('ALERT_TYPE')} - {top.get('ENTITY_NAME')}",
    }
    return summary, board.drop(columns=["_SEVERITY_RANK"], errors="ignore").reset_index(drop=True)


def _build_cost_incident_timeline(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    alert_rows: pd.DataFrame | None = None,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Build a compact incident narrative from cost movement to alert/action status."""
    state = state or st.session_state
    root_cause = _state_frame(state, "cost_contract_spike_root_cause")
    correlation = _state_frame(state, "cost_contract_change_cost_correlation")
    current_credits = safe_float(_first_frame_value(cockpit, "CURRENT_CREDITS", 0))
    prior_credits = safe_float(_first_frame_value(cockpit, "PRIOR_CREDITS", 0))
    top_wh = str(_first_frame_value(cockpit, "TOP_INCREASE_WAREHOUSE", "Cost scope") or "Cost scope")
    top_delta = safe_float(_first_frame_value(cockpit, "TOP_INCREASE_CREDITS", 0))
    pct_vs_30d = _first_frame_value(run_rate, "PCT_VS_30D_AVG", None)
    pct_vs_30d_float = safe_float(pct_vs_30d) if pct_vs_30d is not None and not pd.isna(pct_vs_30d) else 0.0
    open_cost_queue = _open_cost_action_frame(queue)

    rows: list[dict] = []

    def add(order: int, severity: str, step: str, entity: str, evidence: str, next_action: str, proof: str, route: str) -> None:
        rows.append({
            "EVENT_ORDER": int(order),
            "SEVERITY": severity,
            "INCIDENT_STEP": step,
            "ENTITY": entity,
            "EVIDENCE": evidence,
            "NEXT_ACTION": next_action,
            "PROOF_REQUIRED": proof,
            "ROUTE": route,
        })

    movement_severity = "Critical" if top_delta > 0 and pct_vs_30d_float >= 25 else "High" if top_delta > 0 else "Info"
    add(
        1,
        movement_severity,
        "Cost movement detected",
        top_wh,
        f"{top_wh}: {top_delta:+,.2f} credit delta; current {current_credits:,.2f} vs prior {prior_credits:,.2f}; 7d vs 30d {pct_vs_30d_float:+.1f}%.",
        "Explain the top cost mover before changing warehouse settings or workload routing.",
        "Complete-day run-rate plus FACT_WAREHOUSE_HOURLY current/prior warehouse metering.",
        "Cost & Contract > Usage attribution and run-rate",
    )

    if isinstance(root_cause, pd.DataFrame) and not root_cause.empty:
        root_view = root_cause.copy()
        root_view["_RANK"] = root_view.get("SEVERITY", pd.Series(index=root_view.index, dtype=str)).apply(_cost_command_severity_rank)
        root_view = root_view.sort_values(["_RANK"], ascending=True)
        root = root_view.iloc[0]
        add(
            2,
            _cost_alert_message(root, "SEVERITY", default="Medium"),
            "Root cause candidate",
            _cost_alert_message(root, "ENTITY", "DRIVER", default=top_wh),
            _cost_alert_message(root, "EVIDENCE", default="Root cause candidate loaded."),
            _cost_alert_message(root, "NEXT_ACTION", default="Confirm workload demand, workload mix, and setting changes before tuning."),
            _cost_alert_message(root, "PROOF_REQUIRED", default="Record Cost & Contract root-cause telemetry."),
            _cost_alert_message(root, "ROUTE", default="Cost & Contract"),
        )
    else:
        add(
            2,
            "Medium",
            "Root cause candidate",
            top_wh,
            "Root-cause board has not been loaded for this incident window.",
            "Refresh cost detail telemetry before assigning savings or tuning work.",
            "Cost Spike Root Cause board.",
            "Cost & Contract",
        )

    if isinstance(correlation, pd.DataFrame) and not correlation.empty:
        corr_view = correlation.copy()
        corr_view["_RANK"] = corr_view.get("SEVERITY", pd.Series(index=corr_view.index, dtype=str)).apply(_cost_command_severity_rank)
        corr_view = corr_view.sort_values(["_RANK"], ascending=True)
        corr = corr_view.iloc[0]
        add(
            3,
            _cost_alert_message(corr, "SEVERITY", default="Medium"),
            "Change correlation checked",
            _cost_alert_message(corr, "ENTITY", "CORRELATION", default=top_wh),
            _cost_alert_message(corr, "EVIDENCE", default="Change/cost correlation telemetry loaded."),
            _cost_alert_message(corr, "NEXT_ACTION", default="Compare change telemetry to the cost window before closure."),
            _cost_alert_message(corr, "PROOF_REQUIRED", default="Record change query_id, actor, ticket, and cost telemetry."),
            _cost_alert_message(corr, "ROUTE", default="Security Monitoring"),
        )
    else:
        add(
            3,
            "Medium",
            "Change correlation checked",
            top_wh,
            "Security Monitoring telemetry is available after refresh for this cost movement.",
            "Review Security Monitoring for the same company/environment before closing the incident as workload-only.",
            "FACT_OBJECT_CHANGE or Security Monitoring exception rows.",
            "Security Monitoring",
        )

    if isinstance(alert_rows, pd.DataFrame) and not alert_rows.empty:
        alert_view = alert_rows.copy()
        alert_view["_RANK"] = alert_view.get("SEVERITY", pd.Series(index=alert_view.index, dtype=str)).apply(_cost_command_severity_rank)
        alert_view = alert_view.sort_values(["_RANK", "VALUE_AT_RISK_USD"], ascending=[True, False])
        alert = alert_view.iloc[0]
        add(
            4,
            _cost_alert_message(alert, "SEVERITY", default="High"),
            "Alert routed",
            _cost_alert_message(alert, "ENTITY_NAME", default=top_wh),
            _cost_alert_message(alert, "MESSAGE", default="Cost Monitoring alert candidate is ready for Alert Center."),
            _cost_alert_message(alert, "SUGGESTED_ACTION", default="Route the alert to DBA / Cost owner email triage."),
            _cost_alert_message(alert, "PROOF_QUERY", default="Record the alert telemetry query."),
            "Alert Center",
        )
    else:
        add(
            4,
            "Info",
            "Alert routed",
            top_wh,
            "No Critical/High Cost & Contract alert candidate is ready.",
            "Keep monitoring; only route actionable Cost & Contract rows with telemetry.",
            "Cost Monitoring alert board.",
            "Alert Center",
        )

    add(
        5,
        "High" if not open_cost_queue.empty else "Info",
        "DBA action and measurement",
        f"{len(open_cost_queue):,} open cost action(s)",
        f"{len(open_cost_queue):,} open Cost & Contract action queue row(s) need route, baseline/current values, and closure status.",
        "Work measured actions first; keep savings estimated until post-period telemetry confirms the change.",
        "OVERWATCH_ACTION_QUEUE telemetry status, baseline/current, measured delta, and closure status.",
        "Cost & Contract > Recommendations and action queue",
    )

    board = pd.DataFrame(rows).sort_values("EVENT_ORDER").reset_index(drop=True)
    summary = {
        "event_count": int(len(board)),
        "critical_high": int(board["SEVERITY"].isin(["Critical", "High"]).sum()) if not board.empty else 0,
        "top_step": str(board.iloc[0].get("INCIDENT_STEP") if not board.empty else "No incident timeline"),
        "next_action": str(board.iloc[0].get("NEXT_ACTION") if not board.empty else "Refresh cost detail."),
    }
    return summary, board


def _build_cost_monitoring_mart_operability() -> tuple[dict, pd.DataFrame]:
    rows = [
        {
            "COMPONENT": "Cost Monitoring signals",
            "STATE": "Ready",
            "DBA_USE": "Persists cost movement, Cortex quota, and change/cost signals.",
            "PROOF": "Snowflake summary facts and refresh telemetry.",
        },
        {
            "COMPONENT": "Cost incident timeline",
            "STATE": "Ready",
            "DBA_USE": "Turns cost spikes into ordered incident events for root cause, alerting, and action status.",
            "PROOF": "Timeline built from Cost Monitoring signals.",
        },
        {
            "COMPONENT": "Cost Monitoring refresh",
            "STATE": "Scheduled",
            "DBA_USE": "Runs after the control room mart so Alert Center can consume compact facts.",
            "PROOF": "Refresh order is recorded by the DBA platform team.",
        },
        {
            "COMPONENT": "Alert Center handoff",
            "STATE": "Email Ready",
            "DBA_USE": "Routes Critical/High Cost Monitoring signals to the consolidated Alert Center.",
            "PROOF": f"Default target {DEFAULT_ALERT_EMAIL}; dedupes open alerts for 24 hours.",
        },
    ]
    board = pd.DataFrame(rows)
    summary = {
        "components": int(len(board)),
        "scheduled_components": int(board["STATE"].isin(["Scheduled", "Email Ready"]).sum()),
        "top_component": "Cost Monitoring refresh",
    }
    return summary, board


def _render_cost_monitoring_mart_and_incident_timeline(
    *,
    company: str,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
) -> None:
    root_cause = st.session_state.get("cost_contract_spike_root_cause", pd.DataFrame())
    correlation = st.session_state.get("cost_contract_change_cost_correlation", pd.DataFrame())
    alert_summary, alert_board = _build_cost_monitoring_alert_rows(
        root_cause=root_cause,
        correlation=correlation,
        email_target=DEFAULT_ALERT_EMAIL,
    )
    st.session_state["cost_contract_monitoring_alert_summary"] = alert_summary
    st.session_state["cost_contract_monitoring_alerts"] = alert_board
    timeline_summary, timeline = _build_cost_incident_timeline(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
        alert_rows=alert_board,
    )
    st.session_state["cost_contract_incident_timeline_summary"] = timeline_summary
    st.session_state["cost_contract_incident_timeline"] = timeline
    mart_summary, mart_board = _build_cost_monitoring_mart_operability()
    st.session_state["cost_contract_mart_operability_summary"] = mart_summary
    st.session_state["cost_contract_mart_operability"] = mart_board

    st.markdown("**Cost Monitoring Alerts & Timeline**")
    render_shell_snapshot((
        ("Alert Candidates", f"{alert_summary['alert_count']:,}"),
        ("Critical/High", f"{alert_summary['critical_high']:,}"),
        ("Timeline Events", f"{timeline_summary['event_count']:,}"),
        ("Status Lanes", f"{mart_summary['components']:,}"),
    ))

    if not alert_board.empty:
        render_priority_dataframe(
            alert_board,
            title="Alert Center-ready cost issues",
            priority_columns=[
                "SEVERITY", "ALERT_TYPE", "ENTITY_NAME", "VALUE_AT_RISK_USD",
                "MESSAGE", "SUGGESTED_ACTION", "PROOF_QUERY", "ROUTE", "EMAIL_TARGET",
            ],
            sort_by=["SEVERITY", "VALUE_AT_RISK_USD"],
            ascending=[True, False],
            raw_label="All Cost & Contract alert candidates",
            height=280,
            max_rows=8,
        )

    render_priority_dataframe(
        timeline,
        title="Cost incident timeline",
        priority_columns=[
            "EVENT_ORDER", "SEVERITY", "INCIDENT_STEP", "ENTITY",
            "EVIDENCE", "NEXT_ACTION", "PROOF_REQUIRED", "ROUTE",
        ],
        sort_by=["EVENT_ORDER"],
        ascending=[True],
        raw_label="All cost incident timeline rows",
        height=280,
        max_rows=6,
    )


def _render_cost_spike_root_cause_board(
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    credit_price: float,
) -> None:
    summary, board = _build_cost_spike_root_cause_board(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
        credit_price=credit_price,
    )
    st.session_state["cost_contract_spike_root_cause_summary"] = summary
    st.session_state["cost_contract_spike_root_cause"] = board
    if board.empty:
        return
    st.markdown("**Cost Spike Root Cause Drilldown**")
    value_at_risk = safe_float(pd.to_numeric(board.get("VALUE_AT_RISK_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    render_shell_snapshot((
        ("Critical/High", f"{summary['critical_high']:,}"),
        ("Value at Risk", f"${value_at_risk:,.0f}"),
        ("Top Driver", summary["top_driver"]),
    ))
    render_priority_dataframe(
        board.rename(columns={"CONFIDENCE": "MEASUREMENT_BASIS"}),
        title="Cost root-cause candidates ranked by risk and value",
        priority_columns=[
            "SEVERITY", "DRIVER", "ENTITY", "ROOT_CAUSE_SIGNAL", "VALUE_AT_RISK_USD",
            "MEASUREMENT_BASIS", "TRUST", "EVIDENCE", "NEXT_ACTION", "PROOF_REQUIRED", "ROUTE",
        ],
        sort_by=["SEVERITY", "VALUE_AT_RISK_USD"],
        ascending=[True, False],
        raw_label="All cost root-cause candidate rows",
        height=340,
        max_rows=8,
    )


def _render_change_cost_correlation_board(
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
) -> None:
    summary, board = _build_change_cost_correlation_board(
        cockpit=cockpit,
        run_rate=run_rate,
    )
    st.session_state["cost_contract_change_cost_summary"] = summary
    st.session_state["cost_contract_change_cost_correlation"] = board
    if board.empty:
        return
    st.markdown("**Change + Cost Correlation**")
    render_shell_snapshot((
        ("High", f"{summary['high']:,}"),
        ("Medium", f"{summary['medium']:,}"),
        ("Top Correlation", summary["top_correlation"]),
    ))
    render_priority_dataframe(
        board,
        title="Recent changes that may explain cost movement",
        priority_columns=[
            "SEVERITY", "CORRELATION", "ENTITY", "COST_SIGNAL", "CHANGE_SIGNAL",
            "EVIDENCE", "NEXT_ACTION", "PROOF_REQUIRED", "ROUTE",
        ],
        sort_by=["SEVERITY", "CORRELATION"],
        ascending=[True, True],
        raw_label="All change and cost correlation rows",
        height=300,
        max_rows=8,
    )


def _load_cost_splash_query(
    mart_sql: str,
    live_sql: str,
    ttl_key: str,
    *,
    section: str = "Cost & Contract",
    allow_live_fallback: bool = True,
) -> tuple[pd.DataFrame, str, str]:
    try:
        frame = run_query_or_raise(
            mart_sql,
            ttl_key=f"{ttl_key}_mart",
            tier="historical",
            section=section,
        )
        return frame, "Fast summary", ""
    except Exception as mart_exc:
        if not allow_live_fallback:
            return pd.DataFrame(), "", f"Fast summary unavailable: {format_snowflake_error(mart_exc)}"
        try:
            frame = run_query_or_raise(
                live_sql,
                ttl_key=f"{ttl_key}_live",
                tier="historical",
                section=section,
            )
            return frame, "Live fallback", ""
        except Exception as live_exc:
            return (
                pd.DataFrame(),
                "",
                f"Fast summary unavailable: {format_snowflake_error(mart_exc)}; live fallback failed: {format_snowflake_error(live_exc)}",
            )


def _load_cost_splash_live_query(sql: str, ttl_key: str, source_label: str, *, section: str = "Cost & Contract") -> tuple[pd.DataFrame, str, str]:
    try:
        frame = run_query_or_raise(
            sql,
            ttl_key=ttl_key,
            tier="historical",
            section=section,
        )
        return frame, source_label, ""
    except Exception as exc:
        return pd.DataFrame(), "", format_snowflake_error(exc)


def _cost_splash_meta(company: str, days: int, credit_price: float) -> dict:
    return {"company": company, "days": int(days), "credit_price": float(credit_price)}


def _empty_cost_splash(company: str, days: int, credit_price: float) -> dict:
    meta = _cost_splash_meta(company, days, credit_price)
    return {
        "meta": meta,
        "loaded": False,
        "errors": [],
        "source": "",
        "cockpit": None,
        "trend": None,
        "warehouse_delta": None,
        "service_costs": None,
        "cortex": None,
        "run_rate": None,
    }


def _cached_cost_splash(company: str, days: int, credit_price: float) -> dict:
    meta = _cost_splash_meta(company, days, credit_price)
    cached = st.session_state.get(_COST_SPLASH_KEY)
    if isinstance(cached, dict) and cached.get("meta") == meta and cached.get("loaded"):
        return cached
    return _empty_cost_splash(company, days, credit_price)


def _ensure_cost_splash(company: str, days: int, credit_price: float, *, full_proof: bool = True) -> dict:
    meta = _cost_splash_meta(company, days, credit_price)
    cached = st.session_state.get(_COST_SPLASH_KEY)
    if (
        isinstance(cached, dict)
        and cached.get("meta") == meta
        and cached.get("loaded")
        and (cached.get("full_proof") or not full_proof)
    ):
        return cached

    if get_session_for_action(
        "load the Cost & Contract splash",
        surface="Cost & Contract",
        offline_note="Cost workflow navigation remains available without a live Snowflake connection.",
    ) is None:
        splash = {"meta": meta, "loaded": False, "errors": ["Snowflake connection unavailable."], "source": ""}
        st.session_state[_COST_SPLASH_KEY] = splash
        return splash

    cockpit = pd.DataFrame()
    cockpit_source = cockpit_error = ""
    if full_proof:
        cockpit, cockpit_source, cockpit_error = _load_cost_splash_query(
            build_mart_cost_cockpit_sql(company, int(days)),
            _build_cost_cockpit_sql(company, int(days)),
            f"cost_splash_cockpit_{company}_{days}",
            allow_live_fallback=full_proof,
        )
    trend = pd.DataFrame()
    trend_source = trend_error = ""
    if full_proof:
        try:
            trend_result = load_shared_service_cost_trend(
                int(days),
                company,
                credit_price=credit_price,
                ai_credit_price=get_current_ai_credit_price(),
                section="Cost & Contract",
            )
            trend = trend_result.data
            trend_source = trend_result.source
            trend_error = trend_result.message
        except Exception as exc:
            trend = pd.DataFrame()
            trend_source = ""
            trend_error = format_snowflake_error(exc)
    warehouse_delta, delta_source, delta_error = _load_cost_splash_query(
        _build_cost_splash_warehouse_delta_sql(company, int(days), mart=True),
        _build_cost_splash_warehouse_delta_sql(company, int(days), mart=False),
        f"cost_splash_warehouse_delta_{company}_{days}",
        allow_live_fallback=full_proof,
    )
    cortex, cortex_source, cortex_error = _load_cost_splash_query(
        _build_cost_splash_cortex_sql(company, int(days), get_current_ai_credit_price(), mart=True),
        _build_cost_splash_cortex_sql(company, int(days), get_current_ai_credit_price(), mart=False),
        f"cost_splash_cortex_{company}_{days}",
        allow_live_fallback=full_proof,
    )
    service_costs = pd.DataFrame()
    service_source = service_error = ""
    if full_proof:
        try:
            service_result = load_shared_service_cost_lens(
                int(days),
                company,
                credit_price=credit_price,
                ai_credit_price=get_current_ai_credit_price(),
                section="Cost & Contract",
            )
            service_costs = service_result.data
            service_source = service_result.source
            service_error = service_result.message
        except Exception as exc:
            service_costs = pd.DataFrame()
            service_source = ""
            service_error = format_snowflake_error(exc)
    run_rate = pd.DataFrame()
    run_rate_source = run_rate_error = ""
    if full_proof:
        run_rate, run_rate_source, run_rate_error = _load_cost_splash_query(
            build_mart_cost_run_rate_sql(company),
            _build_cost_run_rate_sql(company),
            f"cost_splash_run_rate_{company}",
            allow_live_fallback=full_proof,
        )
    errors = [err for err in (cockpit_error, trend_error, delta_error, cortex_error, service_error, run_rate_error) if err]
    source_parts = [src for src in (service_source, trend_source, cockpit_source, delta_source, cortex_source, run_rate_source) if src]
    splash = {
        "meta": meta,
        "loaded": True,
        "full_proof": bool(full_proof),
        "cockpit": cockpit,
        "trend": trend,
        "warehouse_delta": warehouse_delta,
        "service_costs": service_costs,
        "cortex": cortex,
        "run_rate": run_rate,
        "source": " + ".join(dict.fromkeys(source_parts)),
        "errors": errors,
    }
    st.session_state[_COST_SPLASH_KEY] = splash
    return splash


def _maybe_autoload_cost_splash(company: str, days: int, credit_price: float) -> dict:
    """Load a lightweight cost landing once after navigation; keep full telemetry explicit."""
    meta = _cost_splash_meta(company, days, credit_price)
    cached = st.session_state.get(_COST_SPLASH_KEY)
    if isinstance(cached, dict) and cached.get("meta") == meta and cached.get("loaded"):
        return cached
    if consume_section_autoload_request("Cost & Contract"):
        st.session_state[_COST_SPLASH_AUTOLOAD_SCOPE_KEY] = meta
        st.caption(
            "Cost & Contract opened fast summary facts. Refresh Cost loads official spend, "
            "warehouse ranking, Cortex spend, and supporting telemetry."
        )
        return _ensure_cost_splash(company, days, credit_price, full_proof=False)
    return _cached_cost_splash(company, days, credit_price)


def _cost_splash_summary(splash: dict, credit_price: float, days: int) -> dict:
    cockpit = splash.get("cockpit", pd.DataFrame())
    trend = splash.get("trend", pd.DataFrame())
    warehouse_delta = splash.get("warehouse_delta", pd.DataFrame())
    service_costs = splash.get("service_costs", pd.DataFrame())
    cortex = splash.get("cortex", pd.DataFrame())
    run_rate = splash.get("run_rate", pd.DataFrame())
    row = cockpit.iloc[0] if _looks_like_frame(cockpit) and not cockpit.empty else {}
    cortex_row = cortex.iloc[0] if _looks_like_frame(cortex) and not cortex.empty else {}
    run_rate_row = run_rate.iloc[0] if _looks_like_frame(run_rate) and not run_rate.empty else {}
    service_current = service_prior = 0.0
    service_current_spend = service_prior_spend = 0.0
    service_compute = service_cloud = 0.0
    active_services = 0
    top_service = "No service"
    if _looks_like_frame(service_costs) and not service_costs.empty and "CREDITS_BILLED" in service_costs.columns:
        credits = pd.to_numeric(service_costs.get("CREDITS_BILLED", pd.Series(dtype=float)), errors="coerce").fillna(0)
        prior = pd.to_numeric(service_costs.get("CREDITS_BILLED_PRIOR", pd.Series(dtype=float)), errors="coerce").fillna(0)
        current_spend = pd.to_numeric(service_costs.get("ESTIMATED_COST_USD", pd.Series(dtype=float)), errors="coerce").fillna(0)
        prior_spend = pd.to_numeric(service_costs.get("PRIOR_ESTIMATED_COST_USD", pd.Series(dtype=float)), errors="coerce").fillna(0)
        service_current = safe_float(credits.sum())
        service_prior = safe_float(prior.sum())
        service_current_spend = safe_float(current_spend.sum())
        service_prior_spend = safe_float(prior_spend.sum())
        service_compute = safe_float(pd.to_numeric(service_costs.get("CREDITS_USED_COMPUTE", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        service_cloud = safe_float(pd.to_numeric(service_costs.get("CREDITS_USED_CLOUD_SERVICES", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        active_services = int((credits > 0).sum())
        if active_services:
            top_service = str(service_costs.assign(_CREDITS=credits).sort_values("_CREDITS", ascending=False).iloc[0].get("SERVICE_TYPE") or "Unknown")
    official_service_loaded = _looks_like_frame(service_costs) and not service_costs.empty
    warehouse_current = warehouse_prior = 0.0
    warehouse_active = 0
    if _looks_like_frame(warehouse_delta) and not warehouse_delta.empty:
        current_series = pd.to_numeric(
            warehouse_delta.get("CURRENT_CREDITS", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0)
        prior_series = pd.to_numeric(
            warehouse_delta.get("PRIOR_CREDITS", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0)
        warehouse_current = safe_float(current_series.sum())
        warehouse_prior = safe_float(prior_series.sum())
        warehouse_active = int((current_series > 0).sum())
    current_credits = (
        service_current
        if official_service_loaded
        else safe_float(row.get("CURRENT_CREDITS", 0)) or warehouse_current
    )
    prior_credits = (
        service_prior
        if official_service_loaded
        else safe_float(row.get("PRIOR_CREDITS", 0)) or warehouse_prior
    )
    spend_delta_credits = current_credits - prior_credits
    spend = service_current_spend if official_service_loaded else credits_to_dollars(current_credits, credit_price)
    prior_spend = service_prior_spend if official_service_loaded else credits_to_dollars(prior_credits, credit_price)
    spend_delta = spend - prior_spend if official_service_loaded else credits_to_dollars(spend_delta_credits, credit_price)
    delta_pct = (spend_delta_credits / prior_credits * 100) if prior_credits > 0 else 0.0
    active_warehouses = safe_int(row.get("ACTIVE_WAREHOUSES", 0)) or warehouse_active
    top_wh = str(row.get("TOP_INCREASE_WAREHOUSE") or "")
    top_wh_delta = safe_float(row.get("TOP_INCREASE_CREDITS", 0))
    top_wh_current_credits = 0.0
    if not top_wh and _looks_like_frame(warehouse_delta) and not warehouse_delta.empty:
        top_wh = str(warehouse_delta.iloc[0].get("WAREHOUSE_NAME") or "")
    if _looks_like_frame(warehouse_delta) and not warehouse_delta.empty:
        top_wh_delta = top_wh_delta or safe_float(warehouse_delta.iloc[0].get("CREDIT_DELTA", 0))
        top_wh_current_credits = safe_float(warehouse_delta.iloc[0].get("CURRENT_CREDITS", 0))
    peak_credits = 0.0
    if _looks_like_frame(trend) and not trend.empty and "DAILY_CREDITS" in trend.columns:
        peak_credits = safe_float(trend["DAILY_CREDITS"].max())
    peak_spend = 0.0
    if _looks_like_frame(trend) and not trend.empty and "DAILY_SPEND_USD" in trend.columns:
        peak_spend = safe_float(pd.to_numeric(trend["DAILY_SPEND_USD"], errors="coerce").fillna(0).max())
    cortex_spend = safe_float(cortex_row.get("CORTEX_SPEND_USD", 0))
    projected_30d_credits = safe_float(run_rate_row.get("PROJECTED_30D_FROM_7D", 0))
    avg_7d_credits = safe_float(run_rate_row.get("AVG_DAILY_7D", 0))
    projected_30d_spend = credits_to_dollars(projected_30d_credits, credit_price)
    avg_7d_spend = credits_to_dollars(avg_7d_credits, credit_price)
    run_rate_state = str(run_rate_row.get("RUN_RATE_STATE") or "On demand")
    if not projected_30d_spend and spend:
        projected_30d_spend = safe_float(spend) / max(int(days), 1) * 30
        avg_7d_spend = safe_float(spend) / max(int(days), 1)
        run_rate_state = "Projected from loaded window"
    return {
        "has_data": current_credits > 0 or (_looks_like_frame(trend) and not trend.empty) or cortex_spend > 0,
        "current_credits": current_credits,
        "prior_credits": prior_credits,
        "spend_delta_credits": spend_delta_credits,
        "spend": spend,
        "prior_spend": prior_spend,
        "spend_delta": spend_delta,
        "avg_daily": spend / max(int(days), 1),
        "peak_day": peak_spend if peak_spend else credits_to_dollars(peak_credits, credit_price),
        "delta_pct": delta_pct,
        "cost_basis": "Official account service total" if official_service_loaded else "Warehouse metering total",
        "active_services": active_services,
        "compute_credits": service_compute,
        "cloud_services_credits": service_cloud,
        "top_service": top_service,
        "active_warehouses": active_warehouses,
        "top_warehouse": top_wh or "No warehouse",
        "top_warehouse_delta_credits": top_wh_delta,
        "top_warehouse_delta_spend": credits_to_dollars(top_wh_delta, credit_price),
        "top_warehouse_current_spend": credits_to_dollars(top_wh_current_credits, credit_price),
        "cortex_spend": cortex_spend,
        "cortex_credits": safe_float(cortex_row.get("CORTEX_CREDITS", 0)),
        "cortex_requests": safe_int(cortex_row.get("CORTEX_REQUESTS", 0)),
        "top_cortex_user": str(cortex_row.get("TOP_CORTEX_USER") or "No Cortex user"),
        "top_cortex_user_spend": safe_float(cortex_row.get("TOP_CORTEX_USER_SPEND_USD", 0)),
        "projected_30d_spend": projected_30d_spend,
        "avg_7d_spend": avg_7d_spend,
        "run_rate_state": run_rate_state,
        "yoy_state": str(run_rate_row.get("YOY_STATE") or "On demand"),
        "yoy_7d_pct": _nullable_float(run_rate_row, "YOY_7D_PCT") if _looks_like_frame(run_rate) and not run_rate.empty else None,
    }


def _cost_command_lanes(splash: dict, *, credit_price: float, days: int) -> list[dict[str, str]]:
    """Return Cost & Contract first-paint lanes from loaded state or honest placeholders."""
    if not splash.get("loaded"):
        return [
            {
                "label": "Credits / dollars",
                "value": "On demand",
                "state": "Metering",
                "detail": "Refresh Cost loads official service spend or warehouse metering.",
            },
            {
                "label": "Spend movement",
                "value": "On demand",
                "state": "Delta",
                "detail": "Compares selected window to the prior window before tuning.",
            },
            {
                "label": "30d run rate",
                "value": "On demand",
                "state": "Forecast",
                "detail": "Projected burn appears after cost facts load.",
            },
            {
                "label": "Cortex dollars",
                "value": "On demand",
                "state": "AI",
                "detail": "AI usage uses the configured Cortex credit rate and fact rows.",
            },
            {
                "label": "Top warehouse",
                "value": "On demand",
                "state": "Driver",
                "detail": "Warehouse movement is ranked after metering telemetry loads.",
            },
            {
                "label": "Cloud services",
                "value": "On demand",
                "state": "Ratio",
                "detail": "Official service lens separates compute and cloud-services cost.",
            },
            {
                "label": "Action queue",
                "value": "On demand",
                "state": "Savings",
                "detail": "Measured fixes and measured value load from the queue.",
            },
            {
                "label": "Measurement basis",
                "value": "On demand",
                "state": "Trust",
                "detail": "Exact totals and allocated estimates stay labeled separately.",
            },
        ]

    summary = _cost_splash_summary(splash, credit_price, days)
    queue = splash.get("queue", pd.DataFrame())
    action_summary = _cost_snapshot_action_summary(queue if _looks_like_frame(queue) else pd.DataFrame())
    cloud_ratio = (
        safe_float(summary.get("cloud_services_credits")) / max(safe_float(summary.get("compute_credits")), 1.0) * 100
        if safe_float(summary.get("compute_credits")) or safe_float(summary.get("cloud_services_credits"))
        else 0.0
    )
    return [
        {
            "label": "Credits / dollars",
            "value": f"{safe_float(summary.get('current_credits')):,.1f} cr / ${safe_float(summary.get('spend')):,.0f}",
            "state": "Metering",
            "detail": str(summary.get("cost_basis") or "Warehouse metering total"),
        },
        {
            "label": "Spend movement",
            "value": f"{safe_float(summary.get('delta_pct')):+.1f}% / ${safe_float(summary.get('spend_delta')):+,.0f}",
            "state": "Delta",
            "detail": f"Prior spend: ${safe_float(summary.get('prior_spend')):,.0f}.",
        },
        {
            "label": "30d run rate",
            "value": f"${safe_float(summary.get('projected_30d_spend')):,.0f}",
            "state": str(summary.get("run_rate_state") or "Forecast"),
            "detail": f"Average/day: ${safe_float(summary.get('avg_daily')):,.0f}.",
        },
        {
            "label": "Cortex dollars",
            "value": f"${safe_float(summary.get('cortex_spend')):,.0f}",
            "state": "AI",
            "detail": f"Top user: {summary.get('top_cortex_user')}; {safe_int(summary.get('cortex_requests')):,} request(s).",
        },
        {
            "label": "Top warehouse",
            "value": str(summary.get("top_warehouse") or "No warehouse"),
            "state": "Driver",
            "detail": f"{safe_float(summary.get('top_warehouse_delta_credits')):+,.1f} cr / ${safe_float(summary.get('top_warehouse_delta_spend')):+,.0f}.",
        },
        {
            "label": "Cloud services",
            "value": f"{cloud_ratio:,.1f}%",
            "state": "Ratio",
            "detail": f"{safe_float(summary.get('cloud_services_credits')):,.1f} cloud-services credits.",
        },
        {
            "label": "Action queue",
            "value": f"{safe_int(action_summary.get('open_actions')):,} open / ${safe_float(action_summary.get('estimated_savings')):,.0f}",
            "state": "Savings",
            "detail": f"{safe_int(action_summary.get('high_actions')):,} critical/high action(s).",
        },
        {
            "label": "Measurement basis",
            "value": str(summary.get("cost_basis") or "Metering"),
            "state": "Trust",
            "detail": "Official totals, metered totals, and allocated attribution remain separate.",
        },
    ]


def _slide_money(value: float, *, signed: bool = False) -> str:
    amount = safe_float(value)
    if signed:
        sign = "+" if amount >= 0 else "-"
        return f"{sign}${abs(amount):,.0f}"
    return f"${amount:,.0f}"


def _slide_number(value: float, suffix: str = "") -> str:
    return f"{safe_float(value):,.0f}{suffix}"


def _cost_snapshot_action_summary(queue: pd.DataFrame | None) -> dict:
    open_cost_queue = _open_cost_action_frame(queue)
    if open_cost_queue.empty:
        return {"open_actions": 0, "high_actions": 0, "estimated_savings": 0.0}
    severity = open_cost_queue.get("SEVERITY", pd.Series(dtype=str)).fillna("").astype(str).str.title()
    savings = pd.to_numeric(open_cost_queue.get("EST_MONTHLY_SAVINGS", pd.Series(dtype=float)), errors="coerce").fillna(0)
    return {
        "open_actions": int(len(open_cost_queue)),
        "high_actions": int(severity.isin(["Critical", "High"]).sum()),
        "estimated_savings": safe_float(savings.sum()),
    }


def _render_cost_load_contract(splash: dict, *, days: int) -> None:
    if splash.get("loaded"):
        defer_source_note(f"Cost overview window: {int(days)} days.")


def _render_cost_splash(splash: dict, *, company: str, days: int, credit_price: float) -> None:
    st.markdown("**Cost Overview**")
    _render_cost_load_contract(splash, days=int(days))
    if not splash.get("loaded"):
        if splash.get("errors"):
            for err in splash.get("errors", [])[:2]:
                defer_source_note(str(err))
        return

    summary = _cost_splash_summary(splash, credit_price, days)
    if splash.get("errors") and not summary["has_data"]:
        st.warning("Cost splash could not load from the fast summary or bounded fallback for this role.")
        for err in splash.get("errors", [])[:2]:
            defer_source_note(str(err))
        return

    _render_cost_splash_narrative(summary, days=int(days))
    _render_cost_splash_next_move(summary)
    _render_cost_executive_decision_stack(summary)

    if splash.get("source"):
        telemetry_note = (
            "Cost trend and forecast are loaded."
            if not splash.get("full_proof")
            else "Full overview is loaded."
        )
        defer_source_note(f"{telemetry_note}")

    trend = splash.get("trend", pd.DataFrame())
    warehouse_delta = splash.get("warehouse_delta", pd.DataFrame())
    st.caption("Use each chart's Data view to inspect exact rows, then return to the chart.")
    _render_cost_chart_with_data_toggle(
        "Spend Trend",
        "cost_contract_spend_trend",
        lambda: _render_spend_trend_chart(trend, credit_price),
        _cost_spend_trend_rows(trend, credit_price),
        priority_columns=["USAGE_DATE", "DAILY_CREDITS", "SPEND_USD", "ROLLING_SPEND_USD"],
        sort_by=["USAGE_DATE"],
        max_rows=30,
    )
    _render_cost_chart_with_data_toggle(
        "Warehouse Ranking",
        "cost_contract_warehouse_ranking",
        lambda: _render_warehouse_ranking_chart(warehouse_delta, credit_price),
        _cost_warehouse_ranking_rows(warehouse_delta, credit_price, limit=24),
        priority_columns=[
            "WAREHOUSE_NAME", "CURRENT_SPEND_USD", "PRIOR_SPEND_USD",
            "DELTA_SPEND_USD", "CURRENT_CREDITS", "PRIOR_CREDITS", "PCT_DELTA",
        ],
        sort_by=["CURRENT_SPEND_USD"],
        max_rows=24,
    )


def _render_cost_watch_floor(company: str, credit_price: float) -> None:
    selected_days = safe_int(
        st.session_state.get("cost_contract_cockpit_window", DEFAULT_DAY_WINDOW),
        DEFAULT_DAY_WINDOW,
    )
    if selected_days not in DAY_WINDOW_OPTIONS:
        selected_days = DEFAULT_DAY_WINDOW

    controls = st.columns([1.0, 1.0, 2.6])
    with controls[0]:
        days = st.selectbox(
            "Cost window",
            DAY_WINDOW_OPTIONS,
            index=DAY_WINDOW_OPTIONS.index(selected_days),
            format_func=lambda d: f"{d} days",
            key="cost_contract_cockpit_window",
        )
    with controls[1]:
        refresh_cost = st.button("Refresh Cost", key="cost_contract_refresh", type="primary", width="stretch")

    if refresh_cost:
        st.session_state.pop(_COST_SPLASH_KEY, None)
        st.session_state.pop(_COST_SPLASH_AUTOLOAD_BLOCKED_SCOPE_KEY, None)
        splash = _ensure_cost_splash(company, int(days), credit_price)
    else:
        splash = _maybe_autoload_cost_splash(company, int(days), credit_price)
    _render_cost_splash(splash, company=company, days=int(days), credit_price=credit_price)

    proof_data = st.session_state.get("cost_contract_cockpit")
    proof_meta = st.session_state.get("cost_contract_cockpit_meta", {})
    proof_current = (
        _looks_like_frame(proof_data)
        and not proof_data.empty
        and proof_meta.get("company") == company
        and proof_meta.get("days") == int(days)
    )
    render_data_freshness(
        proof_meta if proof_current else {},
        source=st.session_state.get("cost_contract_cockpit_source", "Cost detail workspace"),
        target_minutes=60,
        delayed_note="Cost detail uses fast summaries first; full account-history refresh is explicit.",
    )
    if refresh_cost:
        session = get_session_for_action(
            "load the Cost Control Cockpit",
            surface="Cost & Contract",
            offline_note="Cost workflow navigation remains available without a live Snowflake connection.",
        )
        if session is None:
            return
        try:
            st.session_state["cost_contract_cockpit"] = run_query(
                build_mart_cost_cockpit_sql(company, int(days)),
                ttl_key=f"cost_contract_cockpit_mart_{company}_{days}",
                tier="historical",
                section="Cost & Contract",
            )
            st.session_state["cost_contract_cockpit_source"] = "Fast warehouse cost summary"
            st.session_state["cost_contract_cockpit_meta"] = with_loaded_at(
                {"company": company, "days": int(days)},
                source="Fast warehouse cost summary",
            )
            st.session_state["cost_contract_cockpit_error"] = ""
        except Exception as mart_exc:
            try:
                st.session_state["cost_contract_cockpit"] = run_query(
                    _build_cost_cockpit_sql(company, int(days)),
                    ttl_key=f"cost_contract_cockpit_{company}_{days}",
                    tier="standard",
                    section="Cost & Contract",
                )
                st.session_state["cost_contract_cockpit_source"] = (
                    "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
                )
                st.session_state["cost_contract_cockpit_meta"] = with_loaded_at(
                    {"company": company, "days": int(days)},
                    source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
                )
                st.session_state["cost_contract_cockpit_error"] = ""
            except Exception as exc:
                st.session_state["cost_contract_cockpit_error"] = (
                    f"Fast summary unavailable: {format_snowflake_error(mart_exc)}; "
                    f"live fallback failed: {format_snowflake_error(exc)}"
                )
                st.session_state["cost_contract_cockpit"] = pd.DataFrame()
                st.session_state["cost_contract_queue"] = pd.DataFrame()
        try:
            st.session_state["cost_contract_run_rate"] = run_query(
                build_mart_cost_run_rate_sql(company),
                ttl_key=f"cost_contract_run_rate_mart_{company}",
                tier="historical",
                section="Cost & Contract",
            )
            st.session_state["cost_contract_run_rate_source"] = "Fast run-rate summary"
            st.session_state["cost_contract_run_rate_error"] = ""
        except Exception as mart_exc:
            try:
                st.session_state["cost_contract_run_rate"] = run_query(
                    _build_cost_run_rate_sql(company),
                    ttl_key=f"cost_contract_run_rate_live_{company}",
                    tier="historical",
                    section="Cost & Contract",
                )
                st.session_state["cost_contract_run_rate_source"] = (
                    "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
                )
                st.session_state["cost_contract_run_rate_error"] = ""
            except Exception as exc:
                st.session_state["cost_contract_run_rate"] = pd.DataFrame()
                st.session_state["cost_contract_run_rate_source"] = ""
                st.session_state["cost_contract_run_rate_error"] = (
                    f"Fast summary unavailable: {format_snowflake_error(mart_exc)}; "
                    f"live fallback failed: {format_snowflake_error(exc)}"
                )
        try:
            st.session_state["cost_contract_queue"] = load_action_queue(session)
            st.session_state["cost_contract_queue_error"] = ""
        except Exception as exc:
            st.session_state["cost_contract_queue"] = pd.DataFrame()
            st.session_state["cost_contract_queue_error"] = format_snowflake_error(exc)
        try:
            st.session_state["cost_contract_attribution_reconciliation"] = run_query_or_raise(
                build_cost_reconciliation_sql(int(days), prefer_query_attribution=True),
                ttl_key=f"cost_contract_attribution_reconciliation_{company}_{days}",
                tier="historical",
                section="Cost & Contract",
            )
            st.session_state["cost_contract_attribution_error"] = ""
            st.session_state["cost_contract_attribution_source"] = (
                "SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY + WAREHOUSE_METERING_HISTORY"
            )
        except Exception as exc:
            st.session_state["cost_contract_attribution_reconciliation"] = pd.DataFrame()
            st.session_state["cost_contract_attribution_error"] = format_snowflake_error(exc)
            st.session_state["cost_contract_attribution_source"] = ""
        try:
            service_result = load_shared_service_cost_lens(
                int(days),
                company,
                credit_price=credit_price,
                ai_credit_price=get_current_ai_credit_price(),
                force=True,
                section="Cost & Contract",
            )
            st.session_state["cost_contract_service_lens"] = service_result.data
            st.session_state["cost_contract_service_lens_error"] = service_result.message
            st.session_state["cost_contract_service_lens_source"] = service_result.source
        except Exception as exc:
            st.session_state["cost_contract_service_lens"] = pd.DataFrame()
            st.session_state["cost_contract_service_lens_error"] = format_snowflake_error(exc)
            st.session_state["cost_contract_service_lens_source"] = ""
        try:
            st.session_state["cost_contract_efficiency_summary"] = run_query_or_raise(
                build_cost_efficiency_summary_sql(
                    int(days),
                    company=company,
                    credit_price=credit_price,
                    prefer_query_attribution=True,
                ),
                ttl_key=f"cost_contract_efficiency_summary_{company}_{days}_{credit_price}",
                tier="historical",
                section="Cost & Contract",
            )
            st.session_state["cost_contract_efficiency_summary_error"] = ""
        except Exception as exc:
            st.session_state["cost_contract_efficiency_summary"] = pd.DataFrame()
            st.session_state["cost_contract_efficiency_summary_error"] = format_snowflake_error(exc)
        try:
            st.session_state["cost_contract_warehouse_efficiency"] = run_query_or_raise(
                build_warehouse_efficiency_sql(
                    int(days),
                    company=company,
                    credit_price=credit_price,
                    top=50,
                    prefer_query_attribution=True,
                ),
                ttl_key=f"cost_contract_warehouse_efficiency_{company}_{days}_{credit_price}",
                tier="historical",
                section="Cost & Contract",
            )
            st.session_state["cost_contract_warehouse_efficiency_error"] = ""
        except Exception as exc:
            st.session_state["cost_contract_warehouse_efficiency"] = pd.DataFrame()
            st.session_state["cost_contract_warehouse_efficiency_error"] = format_snowflake_error(exc)
        try:
            st.session_state["cost_contract_clustering_cost"] = run_query_or_raise(
                build_clustering_cost_sql(
                    int(days),
                    company=company,
                    credit_price=credit_price,
                    top=50,
                ),
                ttl_key=f"cost_contract_clustering_cost_{company}_{days}_{credit_price}",
                tier="historical",
                section="Cost & Contract",
            )
            st.session_state["cost_contract_clustering_cost_error"] = ""
        except Exception as exc:
            st.session_state["cost_contract_clustering_cost"] = pd.DataFrame()
            st.session_state["cost_contract_clustering_cost_error"] = format_snowflake_error(exc)
    defer_section_note(
        "Cost detail telemetry is optional; refresh only when you need account-history rows behind the fast cost summary."
    )

    data = st.session_state.get("cost_contract_cockpit")
    meta = st.session_state.get("cost_contract_cockpit_meta", {})
    err = st.session_state.get("cost_contract_cockpit_error", "")
    if err:
        st.warning(f"Cost cockpit unavailable: {err}")
    loaded_days = meta.get("days")
    data_is_frame = _looks_like_frame(data)
    if (
        data_is_frame
        and not data.empty
        and meta.get("company") == company
        and loaded_days is not None
        and int(loaded_days) != int(days)
    ):
        st.info(
            f"Loaded cockpit data is for {int(loaded_days)} days; selected window is {int(days)} days. "
            "Refresh cost details before acting on detailed telemetry."
        )
    if (
        not data_is_frame
        or data.empty
        or meta.get("company") != company
        or meta.get("days") != int(days)
    ):
        defer_section_note("Specialist cost pages load their own detailed data after the cockpit first move.")
        return

    defer_source_note(st.session_state.get("cost_contract_cockpit_source", "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"))
    row = data.iloc[0]
    queue = st.session_state.get("cost_contract_queue", pd.DataFrame())
    queue_err = st.session_state.get("cost_contract_queue_error", "")
    if queue_err:
        st.caption(f"Action queue unavailable for this role/context: {queue_err}")
    open_actions = high_actions = 0
    total_savings = 0.0
    if isinstance(queue, pd.DataFrame) and not queue.empty and "STATUS" in queue.columns:
        open_mask = ~queue["STATUS"].isin(["Fixed", "Ignored"])
        open_actions = int(open_mask.sum())
        high_actions = int((queue.get("SEVERITY", pd.Series(dtype=str)).isin(["Critical", "High"]) & open_mask).sum())
        if "EST_MONTHLY_SAVINGS" in queue.columns:
            total_savings = safe_float(pd.to_numeric(queue.loc[open_mask, "EST_MONTHLY_SAVINGS"], errors="coerce").fillna(0).sum())
    current_credits = safe_float(row.get("CURRENT_CREDITS", 0))
    prior_credits = safe_float(row.get("PRIOR_CREDITS", 0))
    delta_pct = ((current_credits - prior_credits) / prior_credits * 100) if prior_credits > 0 else 0.0
    top_wh = str(row.get("TOP_INCREASE_WAREHOUSE") or "No increase")
    top_delta = safe_float(row.get("TOP_INCREASE_CREDITS", 0))
    top_delta_usd = credits_to_dollars(top_delta, credit_price)
    top_delta_usd_label = f"{'+' if top_delta_usd >= 0 else '-'}${abs(top_delta_usd):,.0f}"
    cortex_projected, cortex_exception_count = _loaded_cortex_state()
    secondary_metrics = []
    if total_savings > 0:
        secondary_metrics.append({"label": "Savings Queue", "value": f"${total_savings:,.0f}/mo"})
    if cortex_projected > 0 or cortex_exception_count > 0:
        secondary_metrics.append({
            "label": "Cortex Projection",
            "value": f"${cortex_projected:,.0f}/30d",
            "delta": f"{cortex_exception_count:,} exceptions",
            "delta_color": "inverse",
        })
    if secondary_metrics:
        with st.expander("Secondary cockpit metrics", expanded=False):
            _render_metric_items(secondary_metrics)
            if open_actions or high_actions:
                st.caption(f"{open_actions:,} open cost action(s), {high_actions:,} high priority.")
            st.caption(f"Top warehouse increase: {top_wh} ({top_delta:+,.2f} credits / {top_delta_usd_label}).")

    run_rate_source = st.session_state.get("cost_contract_run_rate_source", "")
    if run_rate_source:
        defer_source_note(run_rate_source)
    _render_cost_run_rate_lens(
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        credit_price,
        st.session_state.get("cost_contract_run_rate_error", ""),
    )
    _render_cost_period_explanation(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
        credit_price,
    )
    _render_cost_source_health(
        cockpit=data,
        run_rate=st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue=queue,
        attribution=st.session_state.get("cost_contract_attribution_reconciliation", pd.DataFrame()),
        service_lens=st.session_state.get("cost_contract_service_lens", pd.DataFrame()),
    )
    _render_query_attribution_gap(
        st.session_state.get("cost_contract_attribution_reconciliation", pd.DataFrame()),
        credit_price,
        st.session_state.get("cost_contract_attribution_error", ""),
    )
    _render_account_service_cost_lens(
        st.session_state.get("cost_contract_service_lens", pd.DataFrame()),
        credit_price,
        st.session_state.get("cost_contract_service_lens_error", ""),
    )
    _render_cost_advisor_board(
        efficiency_summary=st.session_state.get("cost_contract_efficiency_summary", pd.DataFrame()),
        warehouse_efficiency=st.session_state.get("cost_contract_warehouse_efficiency", pd.DataFrame()),
        clustering_cost=st.session_state.get("cost_contract_clustering_cost", pd.DataFrame()),
        reconciliation=st.session_state.get("cost_contract_attribution_reconciliation", pd.DataFrame()),
        service_lens=st.session_state.get("cost_contract_service_lens", pd.DataFrame()),
        credit_price=credit_price,
        days=int(days),
        storage_table_metrics=st.session_state.get("stor_df_table_metrics", pd.DataFrame()),
        storage_db_detail=st.session_state.get("stor_df_db_detail", pd.DataFrame()),
        storage_cost_per_tb=st.session_state.get("storage_cost_per_tb", DEFAULTS.get("storage_cost_per_tb", 23.0)),
    )
    _render_cost_efficiency_rca(
        st.session_state.get("cost_contract_efficiency_summary", pd.DataFrame()),
        st.session_state.get("cost_contract_warehouse_efficiency", pd.DataFrame()),
        st.session_state.get("cost_contract_clustering_cost", pd.DataFrame()),
        credit_price,
        errors={
            "Efficiency summary": st.session_state.get("cost_contract_efficiency_summary_error", ""),
            "Warehouse efficiency": st.session_state.get("cost_contract_warehouse_efficiency_error", ""),
            "Clustering cost": st.session_state.get("cost_contract_clustering_cost_error", ""),
        },
    )
    _render_cost_spike_root_cause_board(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
        credit_price,
    )
    _render_change_cost_correlation_board(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
    )
    _render_cost_monitoring_mart_and_incident_timeline(
        company=company,
        cockpit=data,
        run_rate=st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue=queue,
    )
    _render_savings_closure_control(queue, credit_price)
    _render_cost_control_coverage_board(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
    )
    _render_cost_allocation_trust_board(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
    )
    _render_cost_drilldown_command_map(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
    )
    _render_cost_decomposition_board(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
    )

    moves = []
    if delta_pct >= 20 or safe_float(row.get("TOP_INCREASE_CREDITS", 0)) > 0:
        moves.append((
            "Explain the usage movement",
            f"Top increase: {row.get('TOP_INCREASE_WAREHOUSE', 'unknown')} "
            f"({safe_float(row.get('TOP_INCREASE_CREDITS', 0)):,.2f} credits).",
            "Usage attribution and run-rate",
        ))
    if high_actions > 0 or total_savings > 0:
        moves.append((
            "Work the action queue",
            f"{high_actions:,} high-priority action(s), ${total_savings:,.0f}/month potential savings.",
            "Recommendations and action queue",
        ))
    if cortex_exception_count > 0 or cortex_projected > 0:
        moves.append((
            "Inspect AI / Cortex spend",
            f"Projected Cortex spend ${cortex_projected:,.0f}/30d with {cortex_exception_count:,} exception(s).",
            "AI and Cortex spend",
        ))
    if not moves:
        moves.append((
            "Review attribution and queue",
            "No dominant cost incident in this cockpit window. Review attribution or open recommendations.",
            "Recommendations and action queue",
        ))

    st.markdown("**Next Cost Moves**")
    cols = st.columns(min(len(moves), 3))
    for idx, (title, evidence, workflow) in enumerate(moves[:3]):
        with cols[idx]:
            render_escaped_bold_text(title)
            st.caption(_clean_display_text(evidence))
            if st.button(f"Open {workflow}", key=f"cost_contract_next_{idx}_{workflow}", width="stretch"):
                st.session_state["cost_contract_workflow"] = workflow
                st.rerun()


def _render_loaded_cost_alert_context() -> None:
    board = build_loaded_section_alert_signal_board(st.session_state, section="Cost & Contract", limit=8)
    if board.empty:
        return
    focus = board.get("SECTION_FOCUS", pd.Series(dtype=str)).fillna("").astype(str)
    severity = board.get("SEVERITY", pd.Series(dtype=str)).fillna("").astype(str)
    sla = board.get("SLA_STATE", pd.Series(dtype=str)).fillna("").astype(str)
    st.markdown("**Loaded Cost and Cortex Alerts**")
    render_shell_snapshot((
        ("Signals", f"{len(board):,}"),
        ("Cortex / Spend", f"{int(focus.isin(['Cortex spend', 'Spend spike', 'Cost movement']).sum()):,}"),
        ("Critical / High", f"{int(severity.isin(['Critical', 'High']).sum()):,}"),
        ("Breached", f"{int(sla.isin(['Breached', 'Overdue']).sum()):,}"),
    ))
    render_priority_dataframe(
        board,
        title="Loaded cost and Cortex alert context",
        priority_columns=[
            "SECTION_FOCUS", "SEVERITY", "SLA_STATE", "CATEGORY", "SIGNAL",
            "ENTITY", "OWNER", "FIRST_RESPONSE", "RECOMMENDED_ACTION",
            "IMPACT_ESTIMATE", "QUEUE_STATE", "TICKET_ID",
        ],
        sort_by=["PRIORITY"],
        ascending=True,
        raw_label="All loaded cost/Cortex alert rows",
        height=260,
        max_rows=6,
    )
    defer_source_note("Loaded Cost and Cortex Alerts reuse Alert Center data and do not run a separate Snowflake query.")


def render() -> None:
    company = get_active_company()
    credit_price = safe_float(get_credit_price()) or 3.68
    render_signal_confidence(
        source="ACCOUNT_USAGE",
        confidence="allocated",
        scope_note="Warehouse totals are exact; user/query chargeback is allocated unless noted.",
    )
    render_operator_briefing(
        [
            ("First move", "Explain why spend changed before tuning anything."),
            ("Telemetry", "Reconcile warehouse metering, chargeback allocation, Cortex, and run-rate pace."),
            ("Control", "Convert findings into routed actions with savings and status."),
            ("Output", "Produce a DBA-ready usage narrative with the source and action route attached."),
        ],
        columns=4,
    )
    if st.session_state.get("exceptions_only_mode"):
        st.warning("Landing default: prioritize usage deltas, open action queue items, and run-rate risk.")
    _render_cost_watch_floor(company, credit_price)
    _render_loaded_cost_alert_context()

    workflow = render_workflow_selector(
        "Cost workflow",
        "cost_contract_workflow",
        WORKFLOWS,
        WORKFLOW_DETAILS,
        columns=5,
    )

    routed_workflow = st.session_state.pop(_PENDING_DETAIL_WORKFLOW_KEY, None)
    legacy_detail_workflow = st.session_state.pop(_DETAIL_WORKFLOW_KEY, None)
    routed_workflow = routed_workflow if routed_workflow in WORKFLOWS else legacy_detail_workflow
    if routed_workflow in WORKFLOWS and routed_workflow != workflow:
        st.session_state["cost_contract_workflow"] = routed_workflow
        st.rerun()

    render_workflow_module(workflow, WORKFLOW_MODULES)
