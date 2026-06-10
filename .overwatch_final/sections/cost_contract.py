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
from sections.shell_helpers import render_shell_snapshot
import utils as _utils
from utils.section_guidance import defer_section_note, defer_source_note


class _LazyPandas:
    """Load pandas only after Cost & Contract needs dataframe work."""

    _module = None

    def _load(self):
        if self._module is None:
            import pandas as pandas_module

            self._module = pandas_module
        return self._module

    def __getattr__(self, name: str):
        return getattr(self._load(), name)


pd = _LazyPandas()


def _lazy_util(name: str):
    def _call(*args, **kwargs):
        return getattr(_utils, name)(*args, **kwargs)

    _call.__name__ = name
    return _call


build_cost_reconciliation_sql = _lazy_util("build_cost_reconciliation_sql")
build_cost_savings_verification_health_sql = _lazy_util("build_cost_savings_verification_health_sql")
build_cost_savings_verification_sql = _lazy_util("build_cost_savings_verification_sql")
build_mart_bill_warehouse_delta_sql = _lazy_util("build_mart_bill_warehouse_delta_sql")
build_mart_cost_cockpit_sql = _lazy_util("build_mart_cost_cockpit_sql")
build_mart_cost_run_rate_sql = _lazy_util("build_mart_cost_run_rate_sql")
build_mart_cost_service_lens_sql = _lazy_util("build_mart_cost_service_lens_sql")
build_snowflake_service_cost_lens_sql = _lazy_util("build_snowflake_service_cost_lens_sql")
credits_to_dollars = _lazy_util("credits_to_dollars")
format_snowflake_error = _lazy_util("format_snowflake_error")
get_active_environment = _lazy_util("get_active_environment")
get_ai_credit_price = _lazy_util("get_ai_credit_price")
get_environment_label = _lazy_util("get_environment_label")
get_session_for_action = _lazy_util("get_session_for_action")
get_user_filter_clause = _lazy_util("get_user_filter_clause")
get_wh_filter_clause = _lazy_util("get_wh_filter_clause")
load_action_queue = _lazy_util("load_action_queue")
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


def safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value != value:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default: int = 0) -> int:
    try:
        if value is None or value != value:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


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
        "carbon": {"bar": "#29B5E8", "line": "#71D3DC", "risk": "#F97316"},
        "terminal": {"bar": "#0068B7", "line": "#29B5E8", "risk": "#B45309"},
        "corporate": {"bar": "#B00020", "line": "#0F7894", "risk": "#D97706"},
        "roll_tide": {"bar": "#981D32", "line": "#74645D", "risk": "#B45309"},
        "war_eagle": {"bar": "#DD550C", "line": "#71D3DC", "risk": "#F97316"},
    }
    return palettes.get(theme_key, palettes["carbon"])


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
    bars = base.mark_bar(color=palette["bar"], opacity=0.62, cornerRadiusTopLeft=2, cornerRadiusTopRight=2).encode(
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
    st.altair_chart((bars + line + points).properties(height=265), width="stretch")


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
    st.markdown(f"**{title}**")
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
    labels = base.mark_text(align="left", dx=6, baseline="middle", color=palette["line"], fontWeight="bold").encode(
        x=alt.X("CURRENT_SPEND_USD:Q"),
        text="CURRENT_SPEND_LABEL:N",
    )
    chart = (
        bars + labels
    ).properties(height=max(230, min(360, 34 * len(ranking) + 54)))
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
    st.markdown(f"**{state}: {headline}**")
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
            "Explain bill / attribution / contract",
            "Bill movement",
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
            "FinOps Control Center",
            "Run-rate check",
            f"Projected 30-day spend is {_slide_money(projected_30d)}. Check pacing and controls.",
        )
    return (
        "Snowflake value log",
        "Value proof",
        "No dominant cost incident is visible. Capture verified savings or review attribution.",
    )


def _render_cost_splash_next_move(summary: dict) -> None:
    workflow, state, detail = _cost_splash_next_move(summary)
    with st.container(border=True):
        label_col, detail_col, action_col = st.columns([1.15, 4.2, 1.2])
        with label_col:
            st.markdown("**Next Cost Move**")
            st.caption(state)
        with detail_col:
            st.markdown(f"**{workflow}**")
            st.caption(detail)
        with action_col:
            st.write("")
            if st.button("Open workflow", key="cost_contract_splash_next_workflow", width="stretch"):
                st.session_state["cost_contract_workflow"] = workflow
                st.session_state[_DETAIL_WORKFLOW_KEY] = workflow
                st.rerun()


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
        "exact": "Source basis: Exact",
        "allocated": "Source basis: Allocated / estimated from exact warehouse metering",
        "estimated": "Source basis: Estimated",
        "forecast": "Source basis: Forecast from recent observed burn",
        "projection": "Source basis: Projection from recent observed burn",
    }
    return labels.get(str(kind or "").lower(), "Source basis: Calculation depends on available account metadata")


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
    "Explain bill / attribution / contract",
    "Budget governance",
    "Recommendations and action queue",
    "FinOps Control Center",
    "AI and Cortex spend",
    "SPCS spend",
    "Snowflake value log",
)

WORKFLOW_DETAILS = {
    "Explain bill / attribution / contract": "Start here: bill movement, chargeback, contract pacing, and cost drivers.",
    "Budget governance": "Native Snowflake budgets, shared AI resources, per-user AI quota patterns, and custom actions.",
    "Recommendations and action queue": "Owned fixes with severity, proof, savings, and status.",
    "FinOps Control Center": "Cost governance: resource monitors, migration status, verified savings, and formula trust.",
    "AI and Cortex spend": "Cortex usage, model spend, users, and runaway AI cost signals.",
    "SPCS spend": "Snowpark Container Services usage and service cost exposure.",
    "Snowflake value log": "Evidence that DBA changes avoided spend or improved service.",
}

WORKFLOW_MODULES = {
    "Explain bill / attribution / contract": "sections.cost_center",
    "FinOps Control Center": "sections.finops_control",
    "Recommendations and action queue": "sections.recommendations",
    "Snowflake value log": "sections.snowflake_value",
    "Budget governance": "sections.budget_governance",
    "AI and Cortex spend": "sections.cortex_monitor",
    "SPCS spend": "sections.spcs_tracker",
}

_DETAIL_WORKFLOW_KEY = "_cost_contract_detail_workflow"
_FULL_COCKPIT_BOARDS_KEY = "_cost_contract_full_cockpit_boards"
_COST_SPLASH_KEY = "cost_contract_splash"
_COST_SPLASH_AUTOLOAD_SCOPE_KEY = "_cost_contract_splash_autoload_scope"
_COST_SPLASH_AUTOLOAD_BLOCKED_SCOPE_KEY = "_cost_contract_splash_autoload_blocked_scope"
_POWERPOINT_SNAPSHOT_KEY = "_cost_contract_powerpoint_snapshot_loaded"


def _build_cost_cockpit_sql(company: str, days: int) -> str:
    wh_filter = get_wh_filter_clause("warehouse_name", company)
    return f"""
    WITH current_period AS (
        SELECT
            warehouse_name,
            SUM(COALESCE(credits_used, 0)) AS credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          AND start_time < CURRENT_TIMESTAMP()
          {wh_filter}
        GROUP BY warehouse_name
    ),
    prior_period AS (
        SELECT
            warehouse_name,
            SUM(COALESCE(credits_used, 0)) AS credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{int(days) * 2}, CURRENT_TIMESTAMP())
          AND start_time < DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          {wh_filter}
        GROUP BY warehouse_name
    ),
    deltas AS (
        SELECT
            COALESCE(c.warehouse_name, p.warehouse_name) AS warehouse_name,
            COALESCE(c.credits, 0) AS current_credits,
            COALESCE(p.credits, 0) AS prior_credits,
            COALESCE(c.credits, 0) - COALESCE(p.credits, 0) AS credit_delta
        FROM current_period c
        FULL OUTER JOIN prior_period p
            ON c.warehouse_name = p.warehouse_name
    )
    SELECT
        SUM(current_credits) AS current_credits,
        SUM(prior_credits) AS prior_credits,
        COUNT_IF(current_credits > 0) AS active_warehouses,
        MAX_BY(warehouse_name, credit_delta) AS top_increase_warehouse,
        MAX(credit_delta) AS top_increase_credits
    FROM deltas
    """


def _build_cost_run_rate_sql(company: str) -> str:
    """Build live fallback SQL for complete-day 7d/30d run-rate and YOY cost trend."""
    wh_filter = get_wh_filter_clause("warehouse_name", company)
    return f"""
    WITH bounds AS (
        SELECT
            DATE_TRUNC('DAY', CURRENT_TIMESTAMP()) AS today_start,
            DATEADD('DAY', -7, DATE_TRUNC('DAY', CURRENT_TIMESTAMP())) AS current_7d_start,
            DATEADD('DAY', -30, DATE_TRUNC('DAY', CURRENT_TIMESTAMP())) AS current_30d_start,
            DATEADD('YEAR', -1, DATEADD('DAY', -7, DATE_TRUNC('DAY', CURRENT_TIMESTAMP()))) AS yoy_7d_start,
            DATEADD('YEAR', -1, DATE_TRUNC('DAY', CURRENT_TIMESTAMP())) AS yoy_7d_end,
            DATEADD('YEAR', -1, DATEADD('DAY', -30, DATE_TRUNC('DAY', CURRENT_TIMESTAMP()))) AS yoy_30d_start,
            DATEADD('YEAR', -1, DATE_TRUNC('DAY', CURRENT_TIMESTAMP())) AS yoy_30d_end
    ),
    metering AS (
        SELECT
            start_time AS usage_ts,
            warehouse_name,
            COALESCE(credits_used, 0) AS credits_used
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY, bounds
        WHERE start_time >= yoy_30d_start
          AND start_time < today_start
          {wh_filter}
    ),
    aggregate_trend AS (
        SELECT
            SUM(IFF(usage_ts >= current_7d_start AND usage_ts < today_start, credits_used, 0)) AS credits_7d,
            SUM(IFF(usage_ts >= current_30d_start AND usage_ts < today_start, credits_used, 0)) AS credits_30d,
            SUM(IFF(usage_ts >= yoy_7d_start AND usage_ts < yoy_7d_end, credits_used, 0)) AS yoy_7d_credits,
            SUM(IFF(usage_ts >= yoy_30d_start AND usage_ts < yoy_30d_end, credits_used, 0)) AS yoy_30d_credits,
            COUNT(DISTINCT IFF(usage_ts >= current_7d_start AND usage_ts < today_start, TO_DATE(usage_ts), NULL)) AS observed_days_7d,
            COUNT(DISTINCT IFF(usage_ts >= current_30d_start AND usage_ts < today_start, TO_DATE(usage_ts), NULL)) AS observed_days_30d,
            COUNT(DISTINCT IFF(usage_ts >= yoy_7d_start AND usage_ts < yoy_7d_end, TO_DATE(usage_ts), NULL)) AS yoy_days_7d,
            COUNT(DISTINCT IFF(usage_ts >= yoy_30d_start AND usage_ts < yoy_30d_end, TO_DATE(usage_ts), NULL)) AS yoy_days_30d
        FROM metering, bounds
    ),
    warehouse_yoy AS (
        SELECT
            warehouse_name,
            SUM(IFF(usage_ts >= current_7d_start AND usage_ts < today_start, credits_used, 0)) AS current_7d_credits,
            SUM(IFF(usage_ts >= yoy_7d_start AND usage_ts < yoy_7d_end, credits_used, 0)) AS yoy_7d_credits
        FROM metering, bounds
        GROUP BY warehouse_name
    ),
    top_yoy AS (
        SELECT
            warehouse_name AS top_yoy_increase_warehouse,
            current_7d_credits - yoy_7d_credits AS top_yoy_increase_credits
        FROM warehouse_yoy
        WHERE current_7d_credits > 0 OR yoy_7d_credits > 0
        QUALIFY ROW_NUMBER() OVER (
            ORDER BY current_7d_credits - yoy_7d_credits DESC, current_7d_credits DESC
        ) = 1
    )
    SELECT
        ROUND(COALESCE(a.credits_7d, 0), 4) AS credits_7d,
        ROUND(COALESCE(a.credits_7d, 0) / 7, 4) AS avg_daily_7d,
        ROUND(COALESCE(a.credits_30d, 0), 4) AS credits_30d,
        ROUND(COALESCE(a.credits_30d, 0) / 30, 4) AS avg_daily_30d,
        ROUND((COALESCE(a.credits_7d, 0) / 7) * 30, 4) AS projected_30d_from_7d,
        ROUND(COALESCE(a.yoy_7d_credits, 0), 4) AS yoy_7d_credits,
        ROUND(COALESCE(a.yoy_30d_credits, 0), 4) AS yoy_30d_credits,
        a.observed_days_7d,
        a.observed_days_30d,
        a.yoy_days_7d,
        a.yoy_days_30d,
        CASE
            WHEN COALESCE(a.credits_30d, 0) = 0 THEN NULL
            ELSE ROUND(((COALESCE(a.credits_7d, 0) / 7) - (a.credits_30d / 30)) / NULLIF(a.credits_30d / 30, 0) * 100, 2)
        END AS pct_vs_30d_avg,
        CASE
            WHEN a.yoy_days_7d < 5 OR COALESCE(a.yoy_7d_credits, 0) = 0 THEN NULL
            ELSE ROUND((COALESCE(a.credits_7d, 0) - a.yoy_7d_credits) / NULLIF(a.yoy_7d_credits, 0) * 100, 2)
        END AS yoy_7d_pct,
        CASE
            WHEN a.yoy_days_30d < 20 OR COALESCE(a.yoy_30d_credits, 0) = 0 THEN NULL
            ELSE ROUND((COALESCE(a.credits_30d, 0) - a.yoy_30d_credits) / NULLIF(a.yoy_30d_credits, 0) * 100, 2)
        END AS yoy_30d_pct,
        CASE
            WHEN COALESCE(a.credits_30d, 0) = 0 THEN 'No 30-day baseline'
            WHEN ((COALESCE(a.credits_7d, 0) / 7) - (a.credits_30d / 30)) / NULLIF(a.credits_30d / 30, 0) >= 0.15 THEN 'Accelerating'
            WHEN ((COALESCE(a.credits_7d, 0) / 7) - (a.credits_30d / 30)) / NULLIF(a.credits_30d / 30, 0) <= -0.15 THEN 'Cooling'
            ELSE 'Stable'
        END AS run_rate_state,
        CASE
            WHEN a.yoy_days_7d < 5 THEN 'No prior-year baseline'
            WHEN COALESCE(a.yoy_7d_credits, 0) = 0 THEN 'No prior-year spend'
            WHEN (COALESCE(a.credits_7d, 0) - a.yoy_7d_credits) / NULLIF(a.yoy_7d_credits, 0) >= 0.20 THEN 'Above prior year'
            WHEN (COALESCE(a.credits_7d, 0) - a.yoy_7d_credits) / NULLIF(a.yoy_7d_credits, 0) <= -0.20 THEN 'Below prior year'
            ELSE 'Near prior year'
        END AS yoy_state,
        COALESCE(t.top_yoy_increase_warehouse, 'No warehouse baseline') AS top_yoy_increase_warehouse,
        ROUND(COALESCE(t.top_yoy_increase_credits, 0), 4) AS top_yoy_increase_credits
    FROM aggregate_trend a
    LEFT JOIN top_yoy t ON TRUE
    """


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
    days_int = max(int(days or 7), 1)
    credit_rate = safe_float(credit_price, safe_float(DEFAULTS.get("credit_price"), 3.68))
    ai_rate = safe_float(ai_credit_price, safe_float(DEFAULTS.get("ai_credit_price"), 2.20))
    return f"""
        WITH period_data AS (
            SELECT
                DATE(start_time) AS usage_date,
                UPPER(COALESCE(service_type, 'UNKNOWN')) AS service_type,
                SUM(COALESCE(credits_used_compute, 0)) AS compute_credits,
                SUM(COALESCE(credits_used_cloud_services, 0)) AS cloud_services_credits,
                SUM(COALESCE(credits_used, 0)) AS total_credits,
                CASE
                    WHEN UPPER(COALESCE(service_type, 'UNKNOWN')) ILIKE '%CORTEX%'
                      OR UPPER(COALESCE(service_type, 'UNKNOWN')) ILIKE '%AI%'
                      OR UPPER(COALESCE(service_type, 'UNKNOWN')) ILIKE '%INTELLIGENCE%'
                        THEN {ai_rate:.4f}
                    ELSE {credit_rate:.4f}
                END AS rate_usd,
                CASE
                    WHEN DATE(start_time) > DATEADD('day', -{days_int}, DATEADD('hour', -24, CURRENT_TIMESTAMP()))
                        THEN 'CURRENT'
                    ELSE 'PRIOR'
                END AS period
            FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
            WHERE start_time >= DATEADD('day', -{days_int * 2}, DATEADD('hour', -24, CURRENT_TIMESTAMP()))
              AND start_time < DATEADD('hour', -24, CURRENT_TIMESTAMP())
            GROUP BY DATE(start_time), UPPER(COALESCE(service_type, 'UNKNOWN'))
        )
        SELECT
            usage_date,
            ROUND(SUM(total_credits), 4) AS daily_credits,
            ROUND(SUM(total_credits * rate_usd), 2) AS daily_spend_usd,
            ROUND(SUM(compute_credits), 4) AS compute_credits,
            ROUND(SUM(cloud_services_credits), 4) AS cloud_services_credits,
            COUNT(DISTINCT service_type) AS active_services
        FROM period_data
        WHERE period = 'CURRENT'
        GROUP BY usage_date
        ORDER BY usage_date
    """


def _build_cost_splash_warehouse_delta_sql(company: str, days: int, *, mart: bool = True) -> str:
    if mart:
        return build_mart_bill_warehouse_delta_sql(
            f"DATEADD('DAY', -{int(days)}, CURRENT_TIMESTAMP())",
            "CURRENT_TIMESTAMP()",
            f"DATEADD('DAY', -{int(days) * 2}, CURRENT_TIMESTAMP())",
            f"DATEADD('DAY', -{int(days)}, CURRENT_TIMESTAMP())",
            company,
        )
    table = "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
    wh_filter = get_wh_filter_clause("warehouse_name", company)
    return f"""
        WITH current_wh AS (
            SELECT warehouse_name, SUM(COALESCE(credits_used, 0)) AS credits
            FROM {table}
            WHERE start_time >= DATEADD('DAY', -{int(days)}, CURRENT_TIMESTAMP())
              AND start_time < CURRENT_TIMESTAMP()
              {wh_filter}
            GROUP BY warehouse_name
        ),
        prior_wh AS (
            SELECT warehouse_name, SUM(COALESCE(credits_used, 0)) AS credits
            FROM {table}
            WHERE start_time >= DATEADD('DAY', -{int(days) * 2}, CURRENT_TIMESTAMP())
              AND start_time < DATEADD('DAY', -{int(days)}, CURRENT_TIMESTAMP())
              {wh_filter}
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
    user_filter = get_user_filter_clause("COALESCE(u.NAME, TO_VARCHAR(c.USER_ID), '')", company)
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
    """Summarize whether queued cost actions have real closure evidence."""
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
    approved = approval.isin(["APPROVED", "NOT REQUIRED"])
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
    post_period_pending = open_mask & recovery.str.contains("SAVINGS VERIFICATION PENDING|POST-PERIOD", na=False)
    chargeback_pending = open_mask & (
        category.str.contains("CHARGEBACK", na=False)
        | recovery.str.contains("CHARGEBACK EVIDENCE PENDING", na=False)
    )

    closure_states = []
    evidence_notes = []
    verified_period_values = []
    for idx in view.index:
        if bool(verified_savings.loc[idx]):
            closure_states.append("Verified savings")
            evidence_notes.append("Fixed, verified, approved, and measured lower than baseline.")
            verified_period_values.append(round(credits_to_dollars(abs(safe_float(measured_delta.loc[idx])), credit_price), 2))
        elif bool(verified_no_change_closure.loc[idx]):
            closure_states.append("Verified no savings")
            evidence_notes.append("Automated verifier measured the post-period and found no savings to claim.")
            verified_period_values.append(0.0)
        elif bool(fixed_without_verification.loc[idx]):
            closure_states.append("Fixed without verified savings")
            evidence_notes.append("Do not count savings until verification result, approval, and lower post-period usage are attached.")
            verified_period_values.append(0.0)
        elif bool(chargeback_pending.loc[idx]):
            closure_states.append("Chargeback evidence pending")
            evidence_notes.append("Owner/tag proof or shared-cost classification is still required before billing.")
            verified_period_values.append(0.0)
        elif bool(approval_pending.loc[idx]):
            closure_states.append("Approval pending")
            evidence_notes.append("Owner approval is required before action or savings closure.")
            verified_period_values.append(0.0)
        elif bool(post_period_pending.loc[idx]):
            closure_states.append("Post-period measurement pending")
            evidence_notes.append("Run the stored verification query after the next complete period.")
            verified_period_values.append(0.0)
        elif bool(open_mask.loc[idx]):
            closure_states.append("Open cost action")
            evidence_notes.append("Action is not closed; keep proof query and baseline/current values current.")
            verified_period_values.append(0.0)
        else:
            closure_states.append("Ignored / not claimed")
            evidence_notes.append("Ignored rows are excluded from savings claims.")
            verified_period_values.append(0.0)

    view["CLOSURE_STATE"] = closure_states
    view["SAVINGS_EVIDENCE"] = evidence_notes
    view["VERIFIED_PERIOD_DELTA_DOLLARS"] = verified_period_values
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


def _build_savings_verification_task_summary(health: pd.DataFrame | None) -> tuple[dict, pd.DataFrame]:
    """Summarize the Snowflake task that verifies cost savings into closure evidence."""
    empty_summary = {
        "loaded": False,
        "health_state": "Not Loaded",
        "task_state": "Not seen",
        "last_run": "Not seen",
        "failed_runs_7d": 0,
        "ledger_rows_7d": 0,
        "candidates_last_run": 0,
        "verified_last_run": 0,
        "verified_no_change_last_run": 0,
        "evidence_required_last_run": 0,
        "issue_count": 1,
        "issue_severity": "High",
        "next_action": "Deploy the latest OVERWATCH setup, then resume the savings verification task.",
    }
    if health is None or getattr(health, "empty", True):
        return empty_summary, pd.DataFrame()

    view = health.copy()
    expected_defaults = {
        "CONTROL_NAME": "Cost & Contract Savings Verification",
        "TASK_NAME": "OVERWATCH_COST_SAVINGS_VERIFY",
        "TASK_HEALTH_STATE": "Unknown",
        "LAST_TASK_STATE": "",
        "LAST_TASK_SCHEDULED_AT": "",
        "LAST_TASK_COMPLETED_AT": "",
        "LAST_TASK_ERROR": "",
        "FAILED_RUNS_7D": 0,
        "LAST_VERIFICATION_RUN_AT": "",
        "LEDGER_RUN_ROWS_7D": 0,
        "CANDIDATES_LAST_RUN": 0,
        "VERIFIED_LAST_RUN": 0,
        "EVIDENCE_REQUIRED_LAST_RUN": 0,
        "NO_CHANGE_LAST_RUN": 0,
        "NEXT_ACTION": "Review the verifier health row and cost action evidence.",
    }
    for column, default in expected_defaults.items():
        if column not in view.columns:
            view[column] = default

    row = view.iloc[0]
    health_state = str(row.get("TASK_HEALTH_STATE") or "Unknown").strip() or "Unknown"
    task_state = str(row.get("LAST_TASK_STATE") or "Not seen").strip() or "Not seen"
    failed_runs = safe_int(row.get("FAILED_RUNS_7D"))
    ledger_rows = safe_int(row.get("LEDGER_RUN_ROWS_7D"))
    candidates = safe_int(row.get("CANDIDATES_LAST_RUN"))
    verified = safe_int(row.get("VERIFIED_LAST_RUN"))
    no_change = safe_int(row.get("NO_CHANGE_LAST_RUN"))
    evidence_required = safe_int(row.get("EVIDENCE_REQUIRED_LAST_RUN"))
    next_action = str(row.get("NEXT_ACTION") or "Review the verifier health row and cost action evidence.").strip()

    issue_count = 0
    if health_state.upper() != "HEALTHY":
        issue_count += 1
    if failed_runs > 0:
        issue_count += failed_runs
    if evidence_required > 0:
        issue_count += evidence_required

    if health_state.upper() in {"TASK FAILED", "TASK STALE", "TASK NOT SEEN"} or failed_runs > 0:
        issue_severity = "Critical"
    elif health_state.upper() == "NO VERIFICATION LEDGER":
        issue_severity = "High"
    elif evidence_required > 0:
        issue_severity = "Medium"
    else:
        issue_severity = "Info"

    view["ISSUE_SEVERITY"] = issue_severity
    view["ISSUE_COUNT"] = issue_count
    view["ISSUE_DETAIL"] = next_action
    summary = {
        "loaded": True,
        "health_state": health_state,
        "task_state": task_state,
        "last_run": _compact_time(row.get("LAST_VERIFICATION_RUN_AT")),
        "failed_runs_7d": failed_runs,
        "ledger_rows_7d": ledger_rows,
        "candidates_last_run": candidates,
        "verified_last_run": verified,
        "verified_no_change_last_run": no_change,
        "evidence_required_last_run": evidence_required,
        "issue_count": issue_count,
        "issue_severity": issue_severity,
        "next_action": next_action,
    }
    return summary, view


def _render_savings_verification_task_health(health: pd.DataFrame | None, error: str = "") -> None:
    summary, detail = _build_savings_verification_task_summary(health)
    st.markdown("**Savings Verification Task Health**")
    st.caption(
        "Monitors the scheduled Snowflake verifier that converts estimated cost actions into ledger-backed savings evidence."
    )
    render_shell_snapshot((
        ("Task Health", summary["health_state"]),
        ("Failed 7d", f"{summary['failed_runs_7d']:,}"),
        ("Verified Saved", f"{summary['verified_last_run']:,}"),
        ("No Change", f"{summary['verified_no_change_last_run']:,}"),
        ("Needs Evidence", f"{summary['evidence_required_last_run']:,}"),
    ))
    st.caption(f"Last ledger run: {summary['last_run']} | Ledger rows 7d: {summary['ledger_rows_7d']:,}")

    if error:
        st.warning(f"Verification task health view unavailable: {error}")
        st.info("Deploy the latest OVERWATCH setup SQL to create OVERWATCH_COST_SAVINGS_VERIFICATION_HEALTH_V.")
        return
    if detail.empty:
        st.info("Load the cockpit after deploying the verifier health view to monitor savings task failures and stale runs.")
        return

    if summary["issue_severity"] in {"Critical", "High"}:
        st.warning(summary["next_action"])
    elif summary["issue_count"] > 0:
        st.info(summary["next_action"])

    render_priority_dataframe(
        detail,
        title="Verifier health evidence",
        priority_columns=[
            "ISSUE_SEVERITY", "TASK_HEALTH_STATE", "LAST_TASK_STATE",
            "LAST_TASK_SCHEDULED_AT", "LAST_TASK_COMPLETED_AT", "FAILED_RUNS_7D",
            "LAST_VERIFICATION_RUN_AT", "LEDGER_RUN_ROWS_7D",
            "CANDIDATES_LAST_RUN", "VERIFIED_LAST_RUN", "NO_CHANGE_LAST_RUN", "EVIDENCE_REQUIRED_LAST_RUN",
            "LAST_TASK_ERROR", "ISSUE_DETAIL",
        ],
        sort_by=["FAILED_RUNS_7D", "EVIDENCE_REQUIRED_LAST_RUN"],
        ascending=[False, False],
        raw_label="Full verifier health row",
        height=190,
        max_rows=5,
    )


def _render_savings_closure_control(queue: pd.DataFrame, credit_price: float) -> None:
    summary, detail = _build_cost_closure_analytics(queue, credit_price)
    st.markdown("**Savings Closure Control**")
    defer_source_note(
        "Potential savings stay estimated until the action is fixed, owner-approved, verified, "
        "and the measured post-period usage is lower than the stored baseline."
    )
    render_shell_snapshot((
        ("Cost Actions", f"{summary['cost_actions']:,}"),
        ("Open Est. Savings", f"${summary['open_estimated_monthly_savings']:,.0f}/mo"),
        ("Blocked Est. Savings", f"${summary['blocked_estimated_monthly_savings']:,.0f}/mo"),
        ("Verified Period Value", f"${summary['verified_period_delta_dollars']:,.0f}"),
        ("Fixed Audit Ready", f"{summary['audit_ready_pct']:,.1f}%"),
    ))

    if detail.empty:
        st.info("No cost-control or chargeback actions are currently visible in the loaded action queue scope.")
        with st.expander("Deploy scheduled savings verification", expanded=False):
            defer_source_note("Install scheduled savings verification once in the OVERWATCH summary schema, review the task, then resume it.")
            st.code(build_cost_savings_verification_sql(), language="sql")
        return

    render_priority_dataframe(
        detail,
        title="Cost actions that still need approval, measurement, or closure evidence",
        priority_columns=[
            "SEVERITY", "CLOSURE_STATE", "CATEGORY", "ENTITY_NAME", "OWNER",
            "OWNER_EMAIL", "ONCALL_PRIMARY", "APPROVAL_GROUP", "OWNER_SOURCE",
            "STATUS", "OWNER_APPROVAL_STATUS", "VERIFICATION_STATUS",
            "BASELINE_VALUE", "CURRENT_VALUE", "MEASURED_DELTA",
            "VERIFIED_PERIOD_DELTA_DOLLARS", "RECOVERY_SLA_STATE",
            "SAVINGS_EVIDENCE", "TICKET_ID", "APPROVER",
        ],
        sort_by=["QUEUE_PRIORITY", "SEVERITY"],
        ascending=[True, True],
        raw_label="All loaded cost closure rows",
        height=260,
        max_rows=10,
    )
    with st.expander("Deploy scheduled savings verification", expanded=False):
        defer_source_note(
            "This Snowflake procedure/task verifies warehouse cost-control actions from exact metering. "
            "Chargeback and database/user allocations still require owner evidence."
        )
        st.code(build_cost_savings_verification_sql(), language="sql")


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
        "NEXT_ACTION": "If the move is above 10%, explain the bill before tuning or raising budgets.",
    })
    rows.append({
        "QUESTION": "What likely changed?",
        "ANSWER": f"{top_wh} is the largest loaded increase at {top_delta:+,.2f} credits.",
        "DOLLAR_IMPACT": f"${credits_to_dollars(top_delta, credit_price):+,.0f}",
        "EVIDENCE": "Cost cockpit current/prior warehouse movement.",
        "NEXT_ACTION": "Open Warehouse Health to confirm queue, spill, p95, and setting evidence for that warehouse.",
    })
    rows.append({
        "QUESTION": "Is this a short spike or trend?",
        "ANSWER": f"7d vs 30d {_format_optional_pct(pct_vs_30d)}; YOY7 {_format_optional_pct(yoy_7d)}; {yoy_state}.",
        "DOLLAR_IMPACT": "Trend proof",
        "EVIDENCE": "Complete-day 7d, 30d, and prior-year metering.",
        "NEXT_ACTION": "Use the run-rate lens before calling same-day partial metering a real cost incident.",
    })
    rows.append({
        "QUESTION": "Is there already a fix path?",
        "ANSWER": f"{open_count:,} open action(s), ${open_savings:,.0f}/mo estimated savings.",
        "DOLLAR_IMPACT": f"${open_savings:,.0f}/mo",
        "EVIDENCE": "Open Cost & Contract action queue rows.",
        "NEXT_ACTION": "Work owner-approved actions first and verify savings with post-period metering.",
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
    verification_health: pd.DataFrame,
    attribution: pd.DataFrame,
    service_lens: pd.DataFrame,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Build a compact source-health panel for official and OVERWATCH cost proof."""
    state = state or st.session_state
    rows: list[dict] = []
    cockpit_error = str(state.get("cost_contract_cockpit_error", "") or "")
    run_error = str(state.get("cost_contract_run_rate_error", "") or "")
    attribution_error = str(state.get("cost_contract_attribution_error", "") or "")
    service_error = str(state.get("cost_contract_service_lens_error", "") or "")
    verification_error = str(state.get("cost_contract_verification_health_error", "") or "")

    _add_source_health_row(
        rows,
        "Warehouse metering",
        "Exact warehouse spend",
        _source_state(cockpit, cockpit_error, empty_state="Load Needed"),
        _loaded_rows(cockpit),
        "Current/prior movement loaded from fast warehouse metering summary or live Account Usage."
        if _loaded_rows(cockpit) else "Cost cockpit has not loaded warehouse movement proof.",
        "Load Cost Cockpit before explaining bill movement.",
        "ACCOUNT_USAGE warehouse metering latency applies; summary refresh is preferred.",
    )
    _add_source_health_row(
        rows,
        "Run-rate and YOY",
        "Complete-day trend",
        _source_state(run_rate, run_error, empty_state="Load Needed"),
        _loaded_rows(run_rate),
        "7d, 30d, and prior-year complete-day windows are loaded." if _loaded_rows(run_rate) else "Run-rate lens has not loaded complete-day trend proof.",
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
        "Review idle/unallocated gap before assigning query owners.",
        "QUERY_ATTRIBUTION_HISTORY can lag and excludes idle/serverless/AI costs.",
    )
    _add_source_health_row(
        rows,
        "Account service lens",
        "Warehouse, AI, serverless, storage, network",
        _source_state(service_lens, service_error, empty_state="No Rows"),
        _loaded_rows(service_lens),
        "Official account service cost rows are available." if _loaded_rows(service_lens) else "No service-type rows loaded.",
        "Use Budgets for AI/serverless and resource monitors for warehouses only.",
        str(state.get("cost_contract_service_lens_source") or "SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY"),
    )
    _add_source_health_row(
        rows,
        "Action and savings proof",
        "Queue and verified savings",
        "Unavailable" if verification_error else "Ready" if _loaded_rows(queue) or _loaded_rows(verification_health) else "No Rows",
        _loaded_rows(queue) + _loaded_rows(verification_health),
        "Action queue or savings verifier evidence is loaded." if _loaded_rows(queue) or _loaded_rows(verification_health) else "No queue/verifier rows loaded for this role.",
        "Keep savings estimated until verifier evidence is attached.",
        "OVERWATCH summary and action evidence; no direct Snowflake billing scan.",
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
    labels = base.mark_text(align="left", dx=6).encode(
        x="CURRENT_SPEND_USD:Q",
        text="DELTA_LABEL:N",
    )
    st.altair_chart((bars + prior_ticks + labels).properties(height=max(210, min(360, 34 * len(movement) + 58))), width="stretch")


def _render_cost_source_health(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    verification_health: pd.DataFrame,
    attribution: pd.DataFrame,
    service_lens: pd.DataFrame,
) -> None:
    summary, board = _build_cost_source_health_board(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
        verification_health=verification_health,
        attribution=attribution,
        service_lens=service_lens,
    )
    if board.empty:
        return
    st.markdown("**Cost Source Health**")
    render_shell_snapshot((
        ("Ready Sources", f"{summary['ready']:,}"),
        ("Review / On Demand", f"{summary['review']:,}"),
        ("Unavailable", f"{summary['unavailable']:,}"),
    ))
    render_priority_dataframe(
        board,
        title="Cost source readiness",
        priority_columns=["STATE", "SOURCE", "SCOPE", "ROWS_LOADED", "FRESHNESS", "EVIDENCE", "NEXT_ACTION"],
        sort_by=["STATE", "SOURCE"],
        ascending=[True, True],
        raw_label="All cost source health rows",
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


def _add_coverage_row(rows: list[dict], control: str, state: str, evidence: str, action: str, owner: str = "DBA / FinOps") -> None:
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
    verification_health: pd.DataFrame,
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
        "Cockpit has exact WAREHOUSE_METERING_HISTORY current/prior credits." if _has_columns(cockpit, ["CURRENT_CREDITS", "PRIOR_CREDITS"]) else "Cost cockpit has not loaded exact warehouse movement yet.",
        "Load Cost Cockpit before explaining any bill movement.",
    )
    _add_coverage_row(
        rows,
        "7-day average and YOY",
        "Ready" if _has_columns(run_rate, ["AVG_DAILY_7D", "YOY_7D_PCT", "YOY_30D_PCT"]) else "Load Needed",
        "Run-rate lens has complete-day 7d average and prior-year comparison." if _has_columns(run_rate, ["AVG_DAILY_7D", "YOY_7D_PCT", "YOY_30D_PCT"]) else "Run-rate/YOY evidence is not loaded.",
        "Load Cost Cockpit to populate complete-day run-rate and YOY proof.",
    )
    _add_coverage_row(
        rows,
        "Company and environment split",
        "Ready" if _has_columns(chargeback, ["COMPANY", "ENVIRONMENT"]) or _has_columns(explorer, ["COMPANY", "ENVIRONMENT_ROLLUP"]) else "Review",
        "Chargeback/Cost Explorer includes company and environment dimensions." if _has_columns(chargeback, ["COMPANY", "ENVIRONMENT"]) or _has_columns(explorer, ["COMPANY", "ENVIRONMENT_ROLLUP"]) else "Company/environment attribution is not loaded in this session.",
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
        "Cost Explorer detail includes role, user, and department dimensions." if _has_columns(explorer, ["ROLE_NAME", "USER_NAME", "DEPARTMENT"]) else "Role/user/department cost drivers are not loaded.",
        "Load Cost Explorer and sort by estimated cost before assigning optimization work.",
    )

    open_cost_queue = pd.DataFrame()
    if isinstance(queue, pd.DataFrame) and not queue.empty:
        category = queue.get("CATEGORY", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
        status = queue.get("STATUS", pd.Series(["New"] * len(queue), index=queue.index)).fillna("New").astype(str).str.title()
        open_cost_queue = queue[category.str.contains("COST|CHARGEBACK|FINOPS|CORTEX", na=False) & ~status.isin(["Fixed", "Ignored"])]
    owner_source = open_cost_queue.get("OWNER_SOURCE", pd.Series(dtype=str)).fillna("").astype(str).str.strip() if not open_cost_queue.empty else pd.Series(dtype=str)
    owner_ready = int(owner_source.ne("").sum()) if not owner_source.empty else 0
    _add_coverage_row(
        rows,
        "Owned cost action queue",
        "Ready" if not open_cost_queue.empty and owner_ready == len(open_cost_queue) else "Review" if not open_cost_queue.empty else "No Rows",
        f"{len(open_cost_queue):,} open cost action(s); {owner_ready:,} have owner-source evidence.",
        "Route cost findings through the action queue with owner, due date, approval, and verification proof.",
    )

    verification_summary, _ = _build_savings_verification_task_summary(verification_health)
    verifier_state = str(verification_summary.get("state") or "Unknown")
    _add_coverage_row(
        rows,
        "Verified savings ledger",
        "Ready" if verifier_state == "Ready" else "Review",
        str(verification_summary.get("evidence") or "Savings verifier health has not been loaded."),
        str(verification_summary.get("next_action") or "Deploy and monitor the scheduled savings verifier task."),
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
        "Keep shared warehouse and no-database-context costs out of exact PROD/DEV claims until owner/tag proof exists.",
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
    """Classify cost evidence as exact, allocated/estimated, or not yet defensible."""
    state = state or st.session_state
    rows: list[dict] = []
    explorer = _state_frame(state, "df_cost_explorer_detail")
    chargeback = _state_frame(state, "df_chargeback")

    def add(control: str, trust: str, evidence: str, action: str, owner: str = "DBA / FinOps") -> None:
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
        "Warehouse metering and complete-day run-rate/YOY are loaded." if exact_loaded and run_rate_loaded else "Exact warehouse totals or complete-day run-rate evidence is missing.",
        "Load Cost Cockpit before defending contract pace, 7-day average, or YOY movement.",
    )

    company_env_loaded = _has_columns(chargeback, ["COMPANY", "ENVIRONMENT"]) or _has_columns(explorer, ["COMPANY", "ENVIRONMENT_ROLLUP"])
    add(
        "Company and environment view",
        "Allocated/Estimated" if company_env_loaded else "Review",
        "Company/environment split is present; database-attributed cost remains allocated where warehouse usage is shared." if company_env_loaded else "Company/environment allocation is not loaded in this session.",
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
            f"Database drilldown loaded; {estimated_rows:,} row(s) explicitly carry allocated/shared/estimated source basis."
            if db_loaded else "Database attribution is not loaded."
        ),
        "Use database views for chargeback directionally; do not present shared warehouse database spend as exact.",
    )

    human_driver_loaded = _has_columns(explorer, ["ROLE_NAME", "USER_NAME", "DEPARTMENT"])
    add(
        "Role, user, department drivers",
        "Allocated/Estimated" if human_driver_loaded else "Review",
        "Human and department cost drivers are available for prioritization." if human_driver_loaded else "Role/user/department drilldown is not loaded.",
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
            if no_database_rows else "No loaded database-attribution rows are missing database context." if db_loaded else "No database-attribution rows loaded."
        ),
        "Keep no-database, login-only, and shared-service spend labeled allocated/estimated until owner/tag proof exists.",
    )

    open_cost_queue = pd.DataFrame()
    if isinstance(queue, pd.DataFrame) and not queue.empty:
        category = queue.get("CATEGORY", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
        status = queue.get("STATUS", pd.Series(["New"] * len(queue), index=queue.index)).fillna("New").astype(str).str.title()
        open_cost_queue = queue[category.str.contains("COST|CHARGEBACK|FINOPS|CORTEX", na=False) & ~status.isin(["Fixed", "Ignored"])].copy()
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
        f"{len(open_cost_queue):,} open cost action(s); {owner_ready:,} owner-routed; {verification_ready:,} verified/completed.",
        "Do not claim savings until owner approval, measurement period, verification result, and closure evidence are attached.",
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
        "Warehouse bill movement",
        "Ready" if exact_loaded else "Load Needed",
        "Exact",
        loaded_rows(cockpit),
        f"{current_credits:,.2f} current credits; {prior_credits:,.2f} prior credits",
        f"Explain top warehouse movement first{f': {top_wh}' if top_wh else ''}.",
        "Explain bill / attribution / contract",
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
            if run_loaded and not run_rate.empty else "No run-rate evidence loaded"
        ),
        "Use complete-day 7d average and YOY before calling a spike real.",
        "Explain bill / attribution / contract",
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
        "Explain bill / attribution / contract",
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
        f"{no_db_rows:,} no-database row(s)" if db_loaded else "No database rows loaded",
        "Show PROD, DEV_ALL, individual DEV databases, and keep no-database spend out of exact claims.",
        "Explain bill / attribution / contract",
        2 if db_loaded else 3,
    )

    human_loaded = _has_columns(explorer, ["ROLE_NAME", "USER_NAME", "DEPARTMENT"])
    add(
        "Role, user, department",
        "Ready" if human_loaded else "Review",
        "Allocated/Estimated",
        loaded_rows(explorer),
        "Role/user/department drivers loaded" if human_loaded else "Human driver rows not loaded",
        "Sort by estimated dollars before assigning work to a department or user.",
        "Explain bill / attribution / contract",
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
        "Savings closure proof",
        "Ready" if not open_cost_queue.empty and verified else "Review" if not open_cost_queue.empty else "No Rows",
        "Exact after verification",
        len(open_cost_queue),
        f"{verified:,} verified/completed action(s)",
        "Do not count savings until measurement, owner approval, and verification result are attached.",
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
    verification_health: pd.DataFrame,
) -> None:
    summary, board = _build_cost_control_coverage_board(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
        verification_health=verification_health,
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
        title="Cost evidence coverage",
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
    st.markdown("**Cost Drilldown Command Map**")
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
        raw_label="All cost drilldown command rows",
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
            "Exact warehouse metering has not been loaded.",
            "Load the Cost Control Cockpit before explaining contract movement.",
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
            "Run-rate evidence has not been loaded.",
            "Reload the run-rate lens before making trend claims.",
        )

    add(
        "Company and environment split",
        "Ready" if company_loaded else "Review",
        "Allocated/Estimated",
        "Company/environment split is present." if company_loaded else "Company/environment attribution is not loaded.",
        "Use this for ALFA/Trexis and PROD/DEV direction, not as exact allocation.",
    )
    add(
        "Database, DEV rollup, no-database spend",
        "Ready" if db_loaded else "Review",
        "Allocated/Estimated",
        "Database-attributed rows are present." if db_loaded else "Database attribution is not loaded.",
        "Show PROD, DEV_ALL, individual DEV databases, and keep shared/no-db spend labeled allocated or estimated.",
    )
    add(
        "Role, user, department drivers",
        "Ready" if human_loaded else "Review",
        "Allocated/Estimated",
        "Role, user, and department dimensions are available." if human_loaded else "Human driver rows are not loaded.",
        "Sort by estimated dollars before assigning optimization work.",
    )
    add(
        "Open cost action queue",
        "Ready" if not open_cost_queue.empty else "No Rows",
        "Exact after verification" if not open_cost_queue.empty else "No Rows",
        f"{len(open_cost_queue):,} open cost action(s)." if not open_cost_queue.empty else "No cost actions are loaded.",
        "Use the queue to close savings with owner, proof, and verification.",
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


def _cost_native_control_scope(control_type: str) -> str:
    text = str(control_type or "").upper()
    if "RESOURCE MONITOR" in text:
        return "Warehouse-only"
    if "BUDGET" in text:
        return "Account / shared / serverless / AI capable"
    return "OVERWATCH evidence control"


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


def _build_budget_anomaly_command_center(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    credit_price: float,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Build a DBA command board for budget, anomaly, and native control decisions."""
    state = state or st.session_state
    rows: list[dict] = []
    current_credits = safe_float(_first_frame_value(cockpit, "CURRENT_CREDITS", 0))
    prior_credits = safe_float(_first_frame_value(cockpit, "PRIOR_CREDITS", 0))
    top_wh = str(_first_frame_value(cockpit, "TOP_INCREASE_WAREHOUSE", "No loaded warehouse")).strip() or "No loaded warehouse"
    top_delta = safe_float(_first_frame_value(cockpit, "TOP_INCREASE_CREDITS", 0))
    delta_pct = ((current_credits - prior_credits) / prior_credits * 100) if prior_credits > 0 else 0.0
    current_dollars = credits_to_dollars(current_credits, credit_price)
    prior_dollars = credits_to_dollars(prior_credits, credit_price)
    top_delta_dollars = credits_to_dollars(top_delta, credit_price)

    avg_7d = safe_float(_first_frame_value(run_rate, "AVG_DAILY_7D", 0))
    avg_30d = safe_float(_first_frame_value(run_rate, "AVG_DAILY_30D", 0))
    pct_vs_30d = _first_frame_value(run_rate, "PCT_VS_30D_AVG", None)
    pct_vs_30d_float = safe_float(pct_vs_30d) if pct_vs_30d is not None and not pd.isna(pct_vs_30d) else 0.0
    yoy_7d = _first_frame_value(run_rate, "YOY_7D_PCT", None)
    yoy_7d_float = safe_float(yoy_7d) if yoy_7d is not None and not pd.isna(yoy_7d) else 0.0
    yoy_30d = _first_frame_value(run_rate, "YOY_30D_PCT", None)
    yoy_30d_float = safe_float(yoy_30d) if yoy_30d is not None and not pd.isna(yoy_30d) else 0.0
    run_state = str(_first_frame_value(run_rate, "RUN_RATE_STATE", "Not loaded") or "Not loaded")
    yoy_state = str(_first_frame_value(run_rate, "YOY_STATE", "Not loaded") or "Not loaded")
    top_yoy_wh = str(_first_frame_value(run_rate, "TOP_YOY_INCREASE_WAREHOUSE", "No YOY baseline") or "No YOY baseline")
    top_yoy_delta = safe_float(_first_frame_value(run_rate, "TOP_YOY_INCREASE_CREDITS", 0))

    open_cost_queue = _open_cost_action_frame(queue)
    high_open = (
        int(open_cost_queue.get("SEVERITY", pd.Series(dtype=str)).fillna("").astype(str).isin(["Critical", "High"]).sum())
        if not open_cost_queue.empty else 0
    )
    open_savings = (
        safe_float(pd.to_numeric(open_cost_queue.get("EST_MONTHLY_SAVINGS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        if not open_cost_queue.empty else 0.0
    )
    verified_open = (
        int(open_cost_queue.get("VERIFICATION_STATUS", pd.Series(dtype=str)).fillna("").astype(str).str.upper().str.contains("VERIFIED|PASSED|COMPLETE", regex=True).sum())
        if not open_cost_queue.empty else 0
    )
    cortex_projection, cortex_exceptions = _loaded_cortex_state()
    explorer = _state_frame(state, "df_cost_explorer_detail")
    chargeback = _state_frame(state, "df_chargeback")
    company_loaded = _has_columns(chargeback, ["COMPANY", "ENVIRONMENT"]) or _has_columns(explorer, ["COMPANY", "ENVIRONMENT_ROLLUP"])
    db_loaded = _has_columns(chargeback, ["DATABASE_NAME"]) or _has_columns(explorer, ["DATABASE_NAME"])
    human_loaded = _has_columns(explorer, ["ROLE_NAME", "USER_NAME", "DEPARTMENT"])

    try:
        from sections.budget_governance import _build_budget_governance_board

        budget_summary, budget_board = _build_budget_governance_board()
    except Exception:
        budget_summary, budget_board = {"score": 0, "ready": 0, "partial": 1}, pd.DataFrame()

    def add(
        lane: str,
        severity: str,
        signal: str,
        native_control: str,
        evidence: str,
        dba_decision: str,
        next_action: str,
        proof: str,
        do_not: str,
        route: str,
        value: float = 0.0,
    ) -> None:
        rows.append({
            "SEVERITY": severity,
            "LANE": lane,
            "SIGNAL": signal,
            "NATIVE_CONTROL": native_control,
            "CONTROL_SCOPE": _cost_native_control_scope(native_control),
            "EVIDENCE": evidence,
            "DBA_DECISION": dba_decision,
            "NEXT_ACTION": next_action,
            "PROOF_REQUIRED": proof,
            "DO_NOT_DO": do_not,
            "ROUTE": route,
            "VALUE_AT_RISK_USD": round(safe_float(value), 2),
        })

    spend_severity = "Critical" if delta_pct >= 50 and current_credits > prior_credits else "High" if delta_pct >= 20 or top_delta > 0 else "Info"
    add(
        "Account budget pace",
        spend_severity,
        "Spend movement" if spend_severity != "Info" else "Spend baseline",
        "Snowflake Budget - Account Root Budget",
        (
            f"Window ${current_dollars:,.0f} vs prior ${prior_dollars:,.0f} ({delta_pct:+.1f}%); "
            f"top warehouse increase {top_wh} {top_delta:+,.2f} credits (${top_delta_dollars:+,.0f})."
        ),
        "Explain the top warehouse driver before changing budget limits or contract assumptions.",
        "Open Explain bill / attribution / contract, then attach owner and metering proof for the top increase.",
        "Cost cockpit current/prior WAREHOUSE_METERING_HISTORY and top warehouse delta.",
        "Do not raise budget limits or call this a contract issue until the top driver is assigned.",
        "Cost & Contract > Explain bill / attribution / contract",
        max(current_dollars - prior_dollars, top_delta_dollars, 0),
    )
    baseline_severity = "High" if pct_vs_30d_float >= 20 or yoy_7d_float >= 25 else "Medium" if pct_vs_30d_float >= 10 or yoy_7d_float >= 15 else "Info"
    add(
        "Anomaly explanation",
        baseline_severity,
        "Predictive 7d / 30d / YOY pace",
        "OVERWATCH Predictive Cost Anomaly",
        (
            f"{run_state}; {yoy_state}; 7d avg {avg_7d:,.2f} credits/day vs 30d avg {avg_30d:,.2f}; "
            f"7d vs 30d {pct_vs_30d_float:+.1f}%; YOY7 {yoy_7d_float:+.1f}%; "
            f"top YOY increase {top_yoy_wh} {top_yoy_delta:+,.2f} credits. "
            "Alert Center also runs a complete-day 30-day baseline plus sigma anomaly model."
        ),
        "Use complete-day run-rate and prior-year comparison before declaring an incident or savings win.",
        "If the 7d or YOY move is high, queue a bill-explanation action for the top warehouse and owner.",
        "Cost run-rate lens: complete-day 7d, 30d, and prior-year warehouse metering.",
        "Do not act from same-day partial metering or a chart without a complete-day baseline.",
        "Cost & Contract > Explain bill / attribution / contract",
        credits_to_dollars(abs(top_yoy_delta), credit_price),
    )
    monitor_severity = "High" if top_delta > 0 and spend_severity in {"Critical", "High"} else "Medium"
    add(
        "Warehouse guardrail",
        monitor_severity,
        "Resource monitor candidate",
        "Resource Monitor",
        f"{top_wh} is the current top warehouse mover; resource monitors are useful only for warehouse credit control.",
        "Review warehouse-level resource monitor assignment for the top mover, but use Budgets for serverless, AI, and shared resources.",
        "Open Warehouse Health or Change & Drift controls to review monitor assignment and threshold SQL after owner approval.",
        "SHOW RESOURCE MONITORS; SHOW WAREHOUSES LIKE top warehouse; WAREHOUSE_METERING_HISTORY.",
        "Do not use resource monitors as AI/serverless budget controls; Snowflake budgets are the correct surface there.",
        "Warehouse Health > Settings / Cost & Contract > Budget governance",
        top_delta_dollars,
    )
    ai_severity = "High" if cortex_projection > 0 or cortex_exceptions > 0 else "Medium"
    add(
        "AI budget and quota",
        ai_severity,
        "Cortex spend control" if cortex_projection > 0 or cortex_exceptions > 0 else "Cortex control readiness",
        "Snowflake Budget + Per-User AI Quota",
        f"Loaded Cortex projection ${cortex_projection:,.0f}/30d with {cortex_exceptions:,} exception(s).",
        "Route Cortex usage through shared AI budgets and per-user quota review before broadening access.",
        "Open Budget governance to deploy shared AI budget/quota SQL; open AI and Cortex spend for first/last usage and user proof.",
        "Cortex usage history, shared AI budget policy, per-user quota action view.",
        "Do not revoke AI access or enforce quotas from projected spend alone; use dry-run and approval first.",
        "Cost & Contract > Budget governance / AI and Cortex spend",
        cortex_projection,
    )
    add(
        "Shared resource budget",
        "Medium" if safe_int(budget_summary.get("partial")) else "Info",
        "Native budget coverage",
        "Snowflake Budget - Shared Resource Budget",
        f"Ready budget controls {safe_int(budget_summary.get('ready'))}; partial controls {safe_int(budget_summary.get('partial'))}.",
        "Use Snowflake Budgets for AI, serverless, and shared resources because warehouse monitors cannot see those costs.",
        "Deploy account/shared AI budgets with verified email recipients and projected/actual thresholds.",
        "Budget policy frame, SET_EMAIL_NOTIFICATIONS, GET_SHARED_RESOURCES, spending history.",
        "Do not present warehouse-only monitors as full account or AI cost control.",
        "Cost & Contract > Budget governance",
        0,
    )
    add(
        "Budget custom action bridge",
        "Medium",
        "Budget event to action queue",
        "Snowflake Budget Custom Action",
        "Projected 75% and actual 90% budget events can be bridged to OVERWATCH_ACTION_QUEUE through an owner-rights procedure.",
        "Treat custom actions as incident creation and notification, not autonomous destructive remediation.",
        "Attach budget custom actions after confirming procedure access and SNOWFLAKE application grants.",
        "ADD_CUSTOM_ACTION, CONFIRM_CUSTOM_ACTIONS_ACCESS, TASK_HISTORY for triggered procedures.",
        "Do not suspend warehouses or revoke users from budget custom actions without approval and a cycle-start recovery path.",
        "Cost & Contract > Budget governance",
        0,
    )
    queue_severity = "High" if high_open else "Medium" if not open_cost_queue.empty else "Info"
    add(
        "DBA-safe action playbook",
        queue_severity,
        "Open cost actions" if not open_cost_queue.empty else "No loaded cost actions",
        "OVERWATCH Action Queue",
        f"{len(open_cost_queue):,} open cost action(s), {high_open:,} critical/high, ${open_savings:,.0f}/mo estimated savings, {verified_open:,} verified/completed.",
        "Work owner-approved high-impact actions first and keep savings estimated until measured and verified.",
        "Open Recommendations and action queue; require owner, ticket, verification query, baseline/current values, and closure proof.",
        "OVERWATCH_ACTION_QUEUE with owner approval, verification status, and measured post-period usage.",
        "Do not claim savings from recommendations that are fixed but unverified.",
        "Cost & Contract > Recommendations and action queue",
        open_savings,
    )
    allocation_state = "Ready" if company_loaded and db_loaded and human_loaded else "Review"
    add(
        "Chargeback drilldown",
        "Medium" if allocation_state == "Review" else "Info",
        "Allocation trust",
        "OVERWATCH Allocated / Estimated Attribution",
        (
            f"Company/env loaded={company_loaded}; database loaded={db_loaded}; role/user/department loaded={human_loaded}. "
            "Warehouse totals are exact; database/user/department views are allocated when warehouses are shared."
        ),
        "Use drilldowns to assign ownership, but keep shared warehouse and no-database rows labeled Allocated / Estimated.",
        "Load Cost Explorer or Chargeback before assigning database, role, user, or department ownership.",
        "QUERY_HISTORY, TAG_REFERENCES, owner directory, allocation source basis, chargeback-ready flag.",
        "Do not apply PROD/DEV database filters to login-only/no-database context or present shared allocation as exact.",
        "Cost & Contract > Explain bill / attribution / contract",
        0,
    )

    board = pd.DataFrame(rows)
    if board.empty:
        return {"score": 0, "critical_high": 0, "budget_controls": 0, "top_lane": "No loaded cost governance evidence"}, board
    board["_SEVERITY_RANK"] = board["SEVERITY"].apply(_cost_command_severity_rank)
    board = board.sort_values(["_SEVERITY_RANK", "VALUE_AT_RISK_USD"], ascending=[True, False]).drop(columns=["_SEVERITY_RANK"])
    severity = board["SEVERITY"].fillna("").astype(str)
    critical_high = int(severity.isin(["Critical", "High"]).sum())
    medium = int(severity.eq("Medium").sum())
    score = max(0, min(100, 100 - critical_high * 14 - medium * 5))
    top = board.iloc[0]
    summary = {
        "score": int(score),
        "critical_high": critical_high,
        "medium": medium,
        "budget_controls": int(board["NATIVE_CONTROL"].fillna("").astype(str).str.contains("Budget", case=False, regex=False).sum()),
        "warehouse_only_controls": int(board["CONTROL_SCOPE"].eq("Warehouse-only").sum()),
        "top_lane": str(top.get("LANE") or "Cost governance"),
        "top_signal": str(top.get("SIGNAL") or "Cost movement"),
        "top_next_action": str(top.get("NEXT_ACTION") or "Open Cost & Contract drilldown."),
        "top_native_control": str(top.get("NATIVE_CONTROL") or "OVERWATCH evidence control"),
    }
    return summary, board.reset_index(drop=True)


def _render_budget_anomaly_command_center(
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    credit_price: float,
) -> None:
    summary, board = _build_budget_anomaly_command_center(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
        credit_price=credit_price,
    )
    st.session_state["cost_contract_budget_command_summary"] = summary
    st.session_state["cost_contract_budget_command_center"] = board
    if board.empty:
        return
    st.markdown("**Budget & Anomaly Command Center**")
    value_at_risk = safe_float(pd.to_numeric(board.get("VALUE_AT_RISK_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    render_shell_snapshot((
        ("Critical/High", f"{summary['critical_high']:,}"),
        ("Value at Risk", f"${value_at_risk:,.0f}"),
        ("Budget Controls", f"{summary['budget_controls']:,}"),
    ))
    st.caption(
        f"Top lane: {summary['top_lane']} | Native route: {summary['top_native_control']} | "
        f"{summary['top_next_action']}"
    )
    render_priority_dataframe(
        board,
        title="Budget, anomaly, and DBA-safe cost actions",
        priority_columns=[
            "SEVERITY", "LANE", "SIGNAL", "NATIVE_CONTROL", "CONTROL_SCOPE",
            "VALUE_AT_RISK_USD", "EVIDENCE", "DBA_DECISION", "NEXT_ACTION",
            "PROOF_REQUIRED", "DO_NOT_DO", "ROUTE",
        ],
        sort_by=["SEVERITY", "VALUE_AT_RISK_USD"],
        ascending=[True, False],
        raw_label="All budget and anomaly command rows",
        height=360,
        max_rows=10,
    )


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
-- Resource monitors are warehouse-only controls. Use Snowflake Budgets for serverless, shared, and AI costs.
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


def _build_native_cost_control_inventory(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    verification_health: pd.DataFrame | None = None,
    credit_price: float = 3.68,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    state = state or st.session_state
    current_credits = safe_float(_first_frame_value(cockpit, "CURRENT_CREDITS", 0))
    prior_credits = safe_float(_first_frame_value(cockpit, "PRIOR_CREDITS", 0))
    top_wh = str(_first_frame_value(cockpit, "TOP_INCREASE_WAREHOUSE", "Top warehouse not loaded") or "Top warehouse not loaded")
    top_delta = safe_float(_first_frame_value(cockpit, "TOP_INCREASE_CREDITS", 0))
    projected_30d = safe_float(_first_frame_value(run_rate, "PROJECTED_30D_FROM_7D", 0))
    delta_pct = ((current_credits - prior_credits) / prior_credits * 100) if prior_credits > 0 else 0.0
    cortex_projection, cortex_exceptions = _loaded_cortex_state()
    open_cost_queue = _open_cost_action_frame(queue)
    verifier_summary, _ = _build_savings_verification_task_summary(verification_health)

    try:
        from sections.budget_governance import _build_budget_governance_board

        budget_summary, _ = _build_budget_governance_board()
    except Exception:
        budget_summary = {"score": 0, "ready": 0, "pattern": 0, "partial": 1}

    rows: list[dict] = []

    def add(
        control: str,
        state_value: str,
        native_surface: str,
        scope: str,
        evidence: str,
        strict_gap: str,
        next_action: str,
        sql_package: str,
        rank: int,
    ) -> None:
        rows.append({
            "CONTROL": control,
            "STATE": state_value,
            "NATIVE_SURFACE": native_surface,
            "SCOPE": scope,
            "EVIDENCE": evidence,
            "STRICT_GAP": strict_gap,
            "DBA_NEXT_MOVE": next_action,
            "SQL_PACKAGE": sql_package,
            "_RANK": rank,
        })

    add(
        "Warehouse resource monitor",
        "Review" if top_delta > 0 or delta_pct >= 20 else "Candidate",
        "RESOURCE MONITOR",
        "Warehouse-only",
        f"Top mover {top_wh}; delta {top_delta:+,.2f} credits; current/prior movement {delta_pct:+.1f}%.",
        "Does not cover serverless, shared AI, Cortex, Snowpipe, clustering, or no-warehouse cost surfaces.",
        "Generate a resource-monitor guardrail only after owner approval and quota review.",
        "Resource monitor guardrail",
        0,
    )
    add(
        "Account root budget",
        "Ready to Deploy" if safe_int(budget_summary.get("ready")) else "Review",
        "SNOWFLAKE.LOCAL.ACCOUNT_ROOT_BUDGET",
        "Account-level",
        f"Projected 30d from 7d ${credits_to_dollars(projected_30d, credit_price):,.0f}; ready budget controls {safe_int(budget_summary.get('ready'))}.",
        "Spending limit must be approved against contract, renewal, and known planned workload.",
        "Set account budget limit, threshold, and email target after DBA/FinOps approval.",
        "Native budgets",
        1,
    )
    add(
        "Shared AI resource budget",
        "Ready to Deploy" if cortex_projection > 0 or cortex_exceptions > 0 else "Candidate",
        "SNOWFLAKE.CORE.BUDGET",
        "Shared AI / serverless",
        f"Cortex projection ${cortex_projection:,.0f}/30d; {cortex_exceptions:,} exception(s) loaded.",
        "Tagged-user coverage must be validated or AI shared-resource budget will miss users.",
        "Deploy shared AI budget and verify GET_SHARED_RESOURCES plus user tag hygiene.",
        "Native budgets",
        2,
    )
    add(
        "Per-user AI quota",
        "Control Pattern",
        "CORTEX_USER grant + OVERWATCH quota table",
        "User-level AI",
        f"Default alert recipient {DEFAULT_ALERT_EMAIL}; quota control remains dry-run until approved.",
        "Requires removing blanket PUBLIC Cortex access and routing users through a controlled role.",
        "Deploy quota table/action view, then review generated revoke/restore SQL before enforcement.",
        "Per-user AI quota",
        3,
    )
    add(
        "Budget custom action bridge",
        "Ready to Deploy",
        "BUDGET ADD_CUSTOM_ACTION",
        "Budget threshold event",
        "Projected 75% and actual 90% budget thresholds can create OVERWATCH action queue incidents.",
        "Stored procedure must run owner-rights and procedure USAGE must be granted to the SNOWFLAKE application.",
        "Attach custom actions only after confirming procedure grants and dry-run bridge rows.",
        "Budget custom actions",
        4,
    )
    add(
        "Email notification path",
        "Review",
        "Budget email + monitor notifications",
        "Recipient / Snowflake user preference",
        f"Budget email target placeholder is {DEFAULT_ALERT_EMAIL}; resource monitors notify Snowflake users with verified email preferences.",
        "Budget email and resource monitor notification mechanics are different and must be validated separately.",
        "Verify budget recipient email and Snowflake user notification preferences before claiming alert readiness.",
        "Inventory checks",
        5,
    )
    verifier_state = str(verifier_summary.get("health_state") or "Not Loaded")
    add(
        "Savings verification task",
        "Ready" if verifier_state.upper() == "HEALTHY" else "Review",
        "OVERWATCH scheduled verifier",
        "Estimated-to-verified savings control",
        f"Verifier state {verifier_state}; open cost actions {len(open_cost_queue):,}.",
        "Estimated savings are not audit-ready until owner-approved and measured after the change window.",
        "Keep the verifier task healthy and reject savings claims without measured post-period proof.",
        "Inventory checks",
        6,
    )

    board = pd.DataFrame(rows)
    if board.empty:
        return {"score": 0, "ready": 0, "review": 0, "warehouse_only": 0}, board
    review = int(board["STATE"].isin(["Review", "Candidate"]).sum())
    ready = int(board["STATE"].isin(["Ready", "Ready to Deploy", "Control Pattern"]).sum())
    warehouse_only = int(board["SCOPE"].eq("Warehouse-only").sum())
    score = max(0, min(100, 100 - review * 7 - safe_int(budget_summary.get("partial")) * 4))
    return {
        "score": int(score),
        "ready": ready,
        "review": review,
        "warehouse_only": warehouse_only,
    }, board.sort_values(["_RANK", "CONTROL"]).drop(columns=["_RANK"], errors="ignore").reset_index(drop=True)


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
    top_wh = str(_first_frame_value(cockpit, "TOP_INCREASE_WAREHOUSE", "No warehouse loaded") or "No warehouse loaded")
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
        "Cost & Contract > Explain bill / attribution / contract",
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
        "Cost & Contract > Explain bill / attribution / contract",
        credits_to_dollars(abs(top_delta), credit_price),
        1,
    )

    company_driver = _top_loaded_cost_driver(chargeback if not chargeback.empty else explorer, ["COMPANY", "ENVIRONMENT", "ENVIRONMENT_ROLLUP"], credit_price=credit_price)
    add(
        "Medium" if company_driver["entity"] else "Watch",
        "Company / environment attribution",
        company_driver["entity"] or "Not loaded",
        "Chargeback direction",
        (
            f"Top loaded {company_driver['dimension']} is {company_driver['entity']} at ${company_driver['value_usd']:,.0f} across {company_driver['rows']:,} row(s)."
            if company_driver["entity"] else "Company/environment cost attribution is not loaded in this session."
        ),
        "Medium" if company_driver["entity"] else "Low",
        "Allocated / Estimated",
        "Use ALFA/Trexis and PROD/DEV attribution to assign ownership, but keep shared warehouse disclosure attached.",
        "Cost Explorer or Chargeback rows with company/environment dimensions and allocation source basis.",
        "Cost & Contract > Explain bill / attribution / contract",
        company_driver["value_usd"],
        2,
    )

    db_driver = _top_loaded_cost_driver(chargeback if not chargeback.empty else explorer, ["DATABASE_NAME", "ENVIRONMENT", "ENVIRONMENT_ROLLUP"], credit_price=credit_price)
    add(
        "Medium" if db_driver["entity"] else "Watch",
        "Database / DEV rollup",
        db_driver["entity"] or "Not loaded",
        "Database-attributed cost candidate",
        (
            f"Top loaded {db_driver['dimension']} is {db_driver['entity']} at ${db_driver['value_usd']:,.0f} across {db_driver['rows']:,} row(s)."
            if db_driver["entity"] else "Database-level attribution is not loaded."
        ),
        "Medium" if db_driver["entity"] else "Low",
        "Allocated / Estimated",
        "Drill into PROD, DEV_ALL, and individual DEV database views before assigning database ownership.",
        "QUERY_HISTORY allocation, tags, and no-database/shared source-basis labels.",
        "Cost & Contract > Explain bill / attribution / contract",
        db_driver["value_usd"],
        3,
    )

    human_driver = _top_loaded_cost_driver(explorer, ["ROLE_NAME", "USER_NAME", "DEPARTMENT"], credit_price=credit_price)
    add(
        "Medium" if human_driver["entity"] else "Watch",
        "Role / user / department",
        human_driver["entity"] or "Not loaded",
        "Human ownership candidate",
        (
            f"Top loaded {human_driver['dimension']} is {human_driver['entity']} at ${human_driver['value_usd']:,.0f} across {human_driver['rows']:,} row(s)."
            if human_driver["entity"] else "Role, user, and department drilldown is not loaded."
        ),
        "Medium" if human_driver["entity"] else "Low",
        "Allocated / Estimated",
        "Assign optimization work only after the cost row has role/user/department evidence and owner source.",
        "Cost Explorer detail with role, user, department, query count, and allocation source basis.",
        "Cost & Contract > Explain bill / attribution / contract",
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
        f"${savings:,.0f}/mo estimated savings loaded; keep savings estimated until verified.",
        "Medium" if not open_cost_queue.empty else "Low",
        "Exact after verification",
        "Work owner-approved actions first; reject fixed rows without post-period measured proof.",
        "OVERWATCH_ACTION_QUEUE owner, ticket, approval, verification result, baseline/current values.",
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
        "Cortex usage history, user attribution, shared AI budget, and per-user quota action rows.",
        "Cost & Contract > AI and Cortex spend",
        cortex_projection,
        6,
    )

    board = pd.DataFrame(rows)
    if board.empty:
        return {"score": 0, "critical_high": 0, "top_driver": "No loaded root-cause evidence"}, board
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
            "Change evidence not loaded",
            top_wh or "Cost scope",
            f"Top warehouse delta {top_delta:+,.2f} credits; 7d vs 30d {pct_vs_30d_float:+.1f}%.",
            "No loaded Change & Drift exceptions.",
            "Cost movement cannot be cleared of change-correlation risk until Change & Drift is loaded for the same scope.",
            "Load Change & Drift Brief, then compare warehouse, query_id, task/procedure, DDL, grant, and policy events to the cost spike.",
            "Change & Drift exceptions plus Cost Cockpit/run-rate evidence for the same company/environment window.",
            "Change & Drift > Object and access changes",
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
            "A cost spike near warehouse/task/procedure drift must be treated as a root-cause candidate until query/change proof clears it.",
            "Review query_id, actor, warehouse settings, task/procedure runtime, and rollback evidence before tuning or raising budget.",
            "Change exception query_id, WAREHOUSE_METERING_HISTORY, QUERY_HISTORY, task/procedure history, and post-change proof.",
            "Change & Drift > Controlled DBA actions",
            0,
        )
        add(
            "High" if high_rows and spike_signal else "Medium" if high_rows else "Info",
            "High-risk change near cost movement",
            matched_entity,
            f"Cost movement active={spike_signal}; top warehouse {top_wh or 'not loaded'}.",
            f"{high_rows:,} Critical/High change exception(s) loaded.",
            "High-severity DDL/DCL/policy changes near cost movement require a bill explanation, not just a cost chart.",
            "Attach change ticket, query_id, actor, object, and blast-radius proof to the cost incident.",
            "Change-control readiness, object/change evidence, and Cost & Contract root-cause board.",
            "Change & Drift > Object and access changes",
            1,
        )
        add(
            "Medium" if access_ai_changes else "Info",
            "AI/access policy cost route",
            "AI / access control",
            "Cortex or budget movement may be user-access driven.",
            f"{access_ai_changes:,} grant/role/policy/tag/AI-related change row(s) loaded.",
            "AI spend jumps can be caused by access expansion, tag mistakes, or policy changes as much as workload growth.",
            "Compare Cortex first/last usage to access and tag changes before enforcing per-user quotas.",
            "Cortex usage history, Change & Drift grants/policy rows, budget tag assignments.",
            "Cost & Contract > AI and Cortex spend",
            2,
        )

    if not operability.empty:
        blocked = int(pd.to_numeric(operability.get("ROUTE_BLOCKED", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        closure = int(pd.to_numeric(operability.get("CLOSURE_BLOCKED", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        add(
            "High" if blocked + closure > 0 and spike_signal else "Info",
            "Change-control closure blocker",
            "Change control summary",
            f"Cost movement active={spike_signal}.",
            f"{blocked:,} route blocker(s); {closure:,} closure blocker(s).",
            "Do not close a cost incident as remediated while related change-control routes or closures are blocked.",
            "Work change-control blockers before declaring the cost spike explained or resolved.",
            "FACT_CHANGE_CONTROL_OPERABILITY_DAILY with route/closure blocked counts and verified closures.",
            "Change & Drift > Change Control Summary",
            3,
        )

    board = pd.DataFrame(rows)
    if board.empty:
        return {"score": 0, "high": 0, "top_correlation": "No change/cost evidence"}, board
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
        "top_action": str(top.get("NEXT_ACTION") or "Load Change & Drift and compare to Cost & Contract."),
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


def _build_cost_governance_alert_rows(
    *,
    budget_board: pd.DataFrame | None = None,
    root_cause: pd.DataFrame | None = None,
    correlation: pd.DataFrame | None = None,
    email_target: str = DEFAULT_ALERT_EMAIL,
) -> tuple[dict, pd.DataFrame]:
    """Create Alert Center-ready rows from loaded Cost & Contract governance evidence."""
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
        entity = str(entity or "Cost governance").strip()
        rows.append({
            "SEVERITY": severity,
            "CATEGORY": "Cost Control",
            "ALERT_TYPE": alert_type,
            "ENTITY_NAME": entity,
            "MESSAGE": message,
            "SUGGESTED_ACTION": suggested_action,
            "PROOF_QUERY": proof_query,
            "ROUTE": route or "Cost & Contract",
            "OWNER": owner or "DBA / FinOps",
            "EMAIL_TARGET": email_target or DEFAULT_ALERT_EMAIL,
            "STATUS": "New",
            "VALUE_AT_RISK_USD": round(safe_float(value_at_risk), 2),
            "SOURCE_SURFACE": source_surface,
        })

    if isinstance(budget_board, pd.DataFrame) and not budget_board.empty:
        view = budget_board.copy()
        view.columns = [str(col).upper() for col in view.columns]
        high = view[view.get("SEVERITY", pd.Series(index=view.index, dtype=str)).fillna("").astype(str).str.title().isin(["Critical", "High"])]
        if "VALUE_AT_RISK_USD" in high.columns:
            high = high.sort_values("VALUE_AT_RISK_USD", ascending=False)
        for _, row in high.head(6).iterrows():
            lane = _cost_alert_message(row, "LANE", default="Cost governance")
            add(
                severity=_cost_alert_message(row, "SEVERITY", default="High"),
                alert_type=_cost_alert_message(row, "SIGNAL", default="Cost Governance Signal"),
                entity=lane,
                message=_cost_alert_message(row, "EVIDENCE", default="Cost governance signal requires review."),
                suggested_action=_cost_alert_message(row, "NEXT_ACTION", "DBA_DECISION", default="Open Cost & Contract and work the cost governance lane."),
                proof_query=_cost_alert_message(row, "PROOF_REQUIRED", default="Attach Cost & Contract budget/anomaly evidence."),
                route=_cost_alert_message(row, "ROUTE", default="Cost & Contract"),
                owner="DBA / FinOps",
                value_at_risk=safe_float(row.get("VALUE_AT_RISK_USD", 0)),
                source_surface="Budget & Anomaly Command Center",
            )

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
                proof_query=_cost_alert_message(row, "PROOF_REQUIRED", default="Attach warehouse metering, run-rate, owner, and change evidence."),
                route=_cost_alert_message(row, "ROUTE", default="Cost & Contract"),
                owner="DBA / FinOps",
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
                suggested_action=_cost_alert_message(row, "NEXT_ACTION", default="Compare change evidence to cost movement before tuning."),
                proof_query=_cost_alert_message(row, "PROOF_REQUIRED", default="Attach change query_id, actor, ticket, and cost proof."),
                route=_cost_alert_message(row, "ROUTE", default="Change & Drift"),
                owner="DBA / FinOps",
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
    """Build a compact incident narrative from cost movement to alert/action/verification."""
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
        "Explain the top cost mover before changing warehouse settings, budgets, or quotas.",
        "Complete-day run-rate plus FACT_WAREHOUSE_HOURLY current/prior warehouse metering.",
        "Cost & Contract > Explain bill / attribution / contract",
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
            _cost_alert_message(root, "NEXT_ACTION", default="Confirm owner demand, workload mix, and setting changes before tuning."),
            _cost_alert_message(root, "PROOF_REQUIRED", default="Attach Cost & Contract root-cause evidence."),
            _cost_alert_message(root, "ROUTE", default="Cost & Contract"),
        )
    else:
        add(
            2,
            "Medium",
            "Root cause candidate",
            top_wh,
            "Root-cause board has not been loaded for this incident window.",
            "Load Cost Cockpit root-cause evidence before assigning savings or tuning work.",
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
            _cost_alert_message(corr, "EVIDENCE", default="Change/cost correlation evidence loaded."),
            _cost_alert_message(corr, "NEXT_ACTION", default="Compare change evidence to the cost window before closure."),
            _cost_alert_message(corr, "PROOF_REQUIRED", default="Attach change query_id, actor, ticket, and cost proof."),
            _cost_alert_message(corr, "ROUTE", default="Change & Drift"),
        )
    else:
        add(
            3,
            "Medium",
            "Change correlation checked",
            top_wh,
            "Change & Drift evidence is not loaded for this cost movement.",
            "Load Change & Drift for the same company/environment before closing the incident as workload-only.",
            "FACT_OBJECT_CHANGE or Change & Drift exception rows.",
            "Change & Drift",
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
            _cost_alert_message(alert, "MESSAGE", default="Cost governance alert candidate is ready for Alert Center."),
            _cost_alert_message(alert, "SUGGESTED_ACTION", default="Route the alert to DBA / FinOps email triage."),
            _cost_alert_message(alert, "PROOF_QUERY", default="Attach the alert proof query."),
            "Alert Center",
        )
    else:
        add(
            4,
            "Info",
            "Alert routed",
            top_wh,
            "No Critical/High Cost & Contract alert candidate is loaded.",
            "Keep monitoring; only route actionable Cost & Contract rows with proof.",
            "Cost governance alert board.",
            "Alert Center",
        )

    add(
        5,
        "High" if not open_cost_queue.empty else "Info",
        "DBA action and verification",
        f"{len(open_cost_queue):,} open cost action(s)",
        f"{len(open_cost_queue):,} open Cost & Contract action queue row(s) need owner, approval, baseline/current values, and verification proof.",
        "Work owner-approved actions first; keep savings estimated until post-period proof verifies the change.",
        "OVERWATCH_ACTION_QUEUE owner approval, verification query, baseline/current, measured delta, and closure status.",
        "Cost & Contract > Recommendations and action queue",
    )

    board = pd.DataFrame(rows).sort_values("EVENT_ORDER").reset_index(drop=True)
    summary = {
        "event_count": int(len(board)),
        "critical_high": int(board["SEVERITY"].isin(["Critical", "High"]).sum()) if not board.empty else 0,
        "top_step": str(board.iloc[0].get("INCIDENT_STEP") if not board.empty else "No incident timeline"),
        "next_action": str(board.iloc[0].get("NEXT_ACTION") if not board.empty else "Load Cost Cockpit."),
    }
    return summary, board


def _extract_setup_sql_block(setup_sql: str, start_token: str, end_token: str) -> str:
    start_idx = setup_sql.upper().find(start_token.upper())
    if start_idx < 0:
        return ""
    end_idx = setup_sql.upper().find(end_token.upper(), start_idx + len(start_token))
    if end_idx < 0:
        return setup_sql[start_idx:].strip()
    return setup_sql[start_idx:end_idx].strip()


def build_cost_governance_mart_sql(
    *,
    db: str = ETL_AUDIT_DB,
    schema: str = ETL_AUDIT_SCHEMA,
    warehouse: str = "COMPUTE_WH",
    email_target: str = DEFAULT_ALERT_EMAIL,
) -> str:
    """Return the Cost Governance deployment excerpt from OVERWATCH_MART_SETUP.sql."""
    from pathlib import Path

    setup_path = Path(__file__).resolve().parents[2] / "snowflake" / "OVERWATCH_MART_SETUP.sql"
    try:
        setup_sql = setup_path.read_text(encoding="utf-8")
    except Exception:
        return """-- Source of truth: snowflake/OVERWATCH_MART_SETUP.sql
-- Expected objects:
--   FACT_COST_GOVERNANCE_SIGNAL
--   FACT_COST_INCIDENT_TIMELINE
--   SP_OVERWATCH_REFRESH_COST_GOVERNANCE
--   OVERWATCH_COST_GOVERNANCE_REFRESH
--   OVERWATCH_ALERTS bridge
-- Defaults: warehouse COMPUTE_WH, email dba-alerts@yourcompany.com.
"""

    table_block = _extract_setup_sql_block(
        setup_sql,
        "CREATE TRANSIENT TABLE IF NOT EXISTS FACT_COST_GOVERNANCE_SIGNAL",
        "CREATE TRANSIENT TABLE IF NOT EXISTS MART_DBA_CONTROL_ROOM",
    )
    procedure_block = _extract_setup_sql_block(
        setup_sql,
        "CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_COST_GOVERNANCE",
        "-- -----------------------------------------------------------------------------\n-- 5. Alert framework",
    )
    task_block = _extract_setup_sql_block(
        setup_sql,
        "CREATE OR REPLACE TASK OVERWATCH_COST_GOVERNANCE_REFRESH",
        "CREATE OR REPLACE TASK OVERWATCH_LOAD_DAILY",
    )
    resume_block = "ALTER TASK OVERWATCH_COST_GOVERNANCE_REFRESH RESUME;"
    smoke_block = """SELECT 'FACT_COST_GOVERNANCE_SIGNAL' AS TABLE_NAME, COUNT(*) AS ROWS_LOADED FROM FACT_COST_GOVERNANCE_SIGNAL
UNION ALL
SELECT 'FACT_COST_INCIDENT_TIMELINE', COUNT(*) FROM FACT_COST_INCIDENT_TIMELINE;

CALL SP_OVERWATCH_REFRESH_COST_GOVERNANCE();"""
    header = (
        "-- Source of truth: snowflake/OVERWATCH_MART_SETUP.sql\n"
        "-- This preview extracts the clean deploy blocks; edit the setup file, not app code, for DDL changes.\n"
        f"-- Default deployment context: {safe_identifier(db)}.{safe_identifier(schema)} on warehouse {safe_identifier(warehouse)}; alert email {sql_literal(email_target or DEFAULT_ALERT_EMAIL, 500)}.\n"
    )
    return "\n\n".join(part for part in [header, table_block, procedure_block, task_block, resume_block, smoke_block] if part).strip() + "\n"


def _build_cost_governance_mart_operability(sql_text: str) -> tuple[dict, pd.DataFrame]:
    rows = [
        {
            "COMPONENT": "FACT_COST_GOVERNANCE_SIGNAL",
            "STATE": "Install Ready",
            "DBA_USE": "Persists cost movement, Cortex budget/quota, and change/cost signals.",
            "PROOF": "DDL plus SP_OVERWATCH_REFRESH_COST_GOVERNANCE insert paths.",
        },
        {
            "COMPONENT": "FACT_COST_INCIDENT_TIMELINE",
            "STATE": "Install Ready",
            "DBA_USE": "Turns cost spikes into ordered incident events for root cause, alerting, and verification.",
            "PROOF": "Timeline insert from governance signals.",
        },
        {
            "COMPONENT": "OVERWATCH_COST_GOVERNANCE_REFRESH",
            "STATE": "Scheduled",
            "DBA_USE": "Runs after the control room mart so Alert Center can consume compact facts.",
            "PROOF": "Task uses COMPUTE_WH and depends on OVERWATCH_REFRESH_CONTROL_ROOM.",
        },
        {
            "COMPONENT": "OVERWATCH_ALERTS bridge",
            "STATE": "Email Ready",
            "DBA_USE": "Routes Critical/High cost governance signals to the consolidated Alert Center.",
            "PROOF": f"Default target {DEFAULT_ALERT_EMAIL}; dedupes open alerts for 24 hours.",
        },
    ]
    board = pd.DataFrame(rows)
    summary = {
        "components": int(len(board)),
        "sql_chars": int(len(sql_text or "")),
        "scheduled_components": int(board["STATE"].isin(["Scheduled", "Email Ready"]).sum()),
        "top_component": "OVERWATCH_COST_GOVERNANCE_REFRESH",
    }
    return summary, board


def _render_cost_governance_mart_and_incident_timeline(
    *,
    company: str,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
) -> None:
    budget_board = st.session_state.get("cost_contract_budget_command_center", pd.DataFrame())
    root_cause = st.session_state.get("cost_contract_spike_root_cause", pd.DataFrame())
    correlation = st.session_state.get("cost_contract_change_cost_correlation", pd.DataFrame())
    alert_summary, alert_board = _build_cost_governance_alert_rows(
        budget_board=budget_board,
        root_cause=root_cause,
        correlation=correlation,
        email_target=DEFAULT_ALERT_EMAIL,
    )
    st.session_state["cost_contract_governance_alert_summary"] = alert_summary
    st.session_state["cost_contract_governance_alerts"] = alert_board
    timeline_summary, timeline = _build_cost_incident_timeline(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
        alert_rows=alert_board,
    )
    st.session_state["cost_contract_incident_timeline_summary"] = timeline_summary
    st.session_state["cost_contract_incident_timeline"] = timeline
    sql_text = build_cost_governance_mart_sql(email_target=DEFAULT_ALERT_EMAIL)
    mart_summary, mart_board = _build_cost_governance_mart_operability(sql_text)
    st.session_state["cost_contract_mart_operability_summary"] = mart_summary
    st.session_state["cost_contract_mart_operability"] = mart_board

    st.markdown("**Cost Governance Alerts & Timeline**")
    render_shell_snapshot((
        ("Alert Candidates", f"{alert_summary['alert_count']:,}"),
        ("Critical/High", f"{alert_summary['critical_high']:,}"),
        ("Timeline Events", f"{timeline_summary['event_count']:,}"),
        ("Mart Components", f"{mart_summary['components']:,}"),
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
    with st.expander("Cost Governance SQL", expanded=False):
        sql_support_board = apply_operator_status_labels(
            add_cost_companion_columns(prioritize_context_columns(mart_board))
        )
        st.dataframe(sql_support_board, hide_index=True, width="stretch")
        st.code(sql_text, language="sql")


def _render_native_cost_control_inventory(
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    verification_health: pd.DataFrame | None,
    credit_price: float,
) -> None:
    summary, board = _build_native_cost_control_inventory(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
        verification_health=verification_health,
        credit_price=credit_price,
    )
    st.session_state["cost_contract_native_control_summary"] = summary
    st.session_state["cost_contract_native_control_inventory"] = board
    if board.empty:
        return
    st.markdown("**Native Cost Control Inventory**")
    render_shell_snapshot((
        ("Ready / Pattern", f"{summary['ready']:,}"),
        ("Review", f"{summary['review']:,}"),
        ("Controls", f"{len(board):,}"),
    ))
    render_priority_dataframe(
        board,
        title="Native controls, strict gaps, and DBA next move",
        priority_columns=[
            "STATE", "CONTROL", "NATIVE_SURFACE", "SCOPE", "EVIDENCE",
            "STRICT_GAP", "DBA_NEXT_MOVE", "SQL_PACKAGE",
        ],
        sort_by=["STATE", "CONTROL"],
        ascending=[True, True],
        raw_label="All native cost-control inventory rows",
        height=300,
        max_rows=8,
    )


def _render_governed_admin_action_pack(
    company: str,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    credit_price: float,
) -> None:
    top_wh = str(_first_frame_value(cockpit, "TOP_INCREASE_WAREHOUSE", "TOP_WAREHOUSE") or "TOP_WAREHOUSE")
    projected_30d = safe_float(_first_frame_value(run_rate, "PROJECTED_30D_FROM_7D", 0))
    top_delta = safe_float(_first_frame_value(cockpit, "TOP_INCREASE_CREDITS", 0))
    quota = max(projected_30d * 1.25, top_delta * 2, 50.0)
    with st.expander("Governed Admin SQL Pack", expanded=False):
        st.caption(
            "Review-only SQL. OVERWATCH does not execute these changes from the dashboard; DBA approval, rollback, and proof are required."
        )
        package = st.selectbox(
            "SQL package",
            [
                "Resource monitor guardrail",
                "Native budgets",
                "Per-user AI quota",
                "Budget custom actions",
                "Inventory checks",
            ],
            key="cost_contract_governed_sql_pack",
        )
        if package == "Resource monitor guardrail":
            st.code(
                _build_resource_monitor_guardrail_sql(top_wh, credit_quota=quota),
                language="sql",
            )
        else:
            try:
                from sections.budget_governance import (
                    _build_budget_custom_action_sql,
                    _build_budget_inventory_sql,
                    _build_budget_policy_frame,
                    _build_native_budget_sql,
                    _build_per_user_quota_sql,
                    _default_ai_budget_usd,
                )

                policy = _build_budget_policy_frame(
                    company,
                    credit_price,
                    ai_credit_price=get_current_ai_credit_price(),
                    ai_budget_usd=_default_ai_budget_usd(company),
                    per_user_limit_usd=250.0,
                    email_target=DEFAULT_ALERT_EMAIL,
                )
                if package == "Native budgets":
                    st.code(_build_native_budget_sql(policy, email_target=DEFAULT_ALERT_EMAIL), language="sql")
                elif package == "Per-user AI quota":
                    st.code(
                        _build_per_user_quota_sql(
                            default_limit_usd=250.0,
                            ai_credit_price=get_current_ai_credit_price(),
                        ),
                        language="sql",
                    )
                elif package == "Budget custom actions":
                    st.code(_build_budget_custom_action_sql(policy, email_target=DEFAULT_ALERT_EMAIL), language="sql")
                else:
                    st.code(
                        _build_budget_inventory_sql()
                        + "\n\nSHOW RESOURCE MONITORS;\n"
                        + f"SHOW WAREHOUSES LIKE {sql_literal(top_wh, 200)};\n",
                        language="sql",
                    )
            except Exception as exc:
                st.warning(f"Could not build SQL package: {format_snowflake_error(exc)}")


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
        board.rename(columns={"CONFIDENCE": "SOURCE_BASIS"}),
        title="Cost root-cause candidates ranked by risk and value",
        priority_columns=[
            "SEVERITY", "DRIVER", "ENTITY", "ROOT_CAUSE_SIGNAL", "VALUE_AT_RISK_USD",
            "SOURCE_BASIS", "TRUST", "EVIDENCE", "NEXT_ACTION", "PROOF_REQUIRED", "ROUTE",
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


def _load_cost_splash_query(mart_sql: str, live_sql: str, ttl_key: str, *, section: str = "Cost & Contract") -> tuple[pd.DataFrame, str, str]:
    try:
        frame = run_query_or_raise(
            mart_sql,
            ttl_key=f"{ttl_key}_mart",
            tier="historical",
            section=section,
        )
        return frame, "Fast summary", ""
    except Exception as mart_exc:
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
        )
    trend = pd.DataFrame()
    trend_source = trend_error = ""
    if full_proof:
        trend, trend_source, trend_error = _load_cost_splash_live_query(
            _build_cost_monitor_service_trend_sql(
                int(days),
                credit_price=credit_price,
                ai_credit_price=get_current_ai_credit_price(),
            ),
            f"cost_splash_official_service_trend_{company}_{days}",
            "Official Cost Monitor: SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY",
        )
    warehouse_delta, delta_source, delta_error = _load_cost_splash_query(
        _build_cost_splash_warehouse_delta_sql(company, int(days), mart=True),
        _build_cost_splash_warehouse_delta_sql(company, int(days), mart=False),
        f"cost_splash_warehouse_delta_{company}_{days}",
    )
    cortex, cortex_source, cortex_error = _load_cost_splash_query(
        _build_cost_splash_cortex_sql(company, int(days), get_current_ai_credit_price(), mart=True),
        _build_cost_splash_cortex_sql(company, int(days), get_current_ai_credit_price(), mart=False),
        f"cost_splash_cortex_{company}_{days}",
    )
    service_costs, service_source, service_error = _load_cost_splash_live_query(
        build_snowflake_service_cost_lens_sql(
            int(days),
            credit_price,
            ai_credit_price=get_current_ai_credit_price(),
        ),
        f"cost_splash_official_service_lens_{company}_{days}_{credit_price}",
        "Official Cost Monitor: SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY",
    )
    run_rate = pd.DataFrame()
    run_rate_source = run_rate_error = ""
    if full_proof:
        run_rate, run_rate_source, run_rate_error = _load_cost_splash_query(
            build_mart_cost_run_rate_sql(company),
            _build_cost_run_rate_sql(company),
            f"cost_splash_run_rate_{company}",
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
    """Use already-loaded cost overview data without starting Snowflake work on navigation."""
    meta = _cost_splash_meta(company, days, credit_price)
    cached = st.session_state.get(_COST_SPLASH_KEY)
    if isinstance(cached, dict) and cached.get("meta") == meta and cached.get("loaded"):
        return cached
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
    run_rate_state = str(run_rate_row.get("RUN_RATE_STATE") or "Not loaded")
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
        "yoy_state": str(run_rate_row.get("YOY_STATE") or "Not loaded"),
        "yoy_7d_pct": _nullable_float(run_rate_row, "YOY_7D_PCT") if _looks_like_frame(run_rate) and not run_rate.empty else None,
    }


def _slide_money(value: float, *, signed: bool = False) -> str:
    amount = safe_float(value)
    if signed:
        sign = "+" if amount >= 0 else "-"
        return f"{sign}${abs(amount):,.0f}"
    return f"${amount:,.0f}"


def _slide_number(value: float, suffix: str = "") -> str:
    return f"{safe_float(value):,.0f}{suffix}"


def _safe_filename_piece(value: object) -> str:
    text = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or "").strip())
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_") or "scope"


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


def _cost_snapshot_kpi_rows(
    summary: dict,
    service_summary: dict,
    action_summary: dict,
    *,
    company: str,
    environment_label: str,
    days: int,
) -> pd.DataFrame:
    rows = [
        ("Scope", f"{company} / {environment_label} / {int(days)} days", "Company, environment, and window."),
        ("Current spend", _slide_money(summary.get("spend")), str(summary.get("cost_basis") or "Warehouse spend for the selected window.")),
        ("Prior spend", _slide_money(summary.get("prior_spend")), "Prior window baseline."),
        ("Spend delta", _slide_money(summary.get("spend_delta"), signed=True), f"{safe_float(summary.get('delta_pct')):+.1f}% versus prior."),
        ("Top warehouse", str(summary.get("top_warehouse") or "No warehouse"), _slide_money(summary.get("top_warehouse_delta_spend"), signed=True)),
        ("Cortex spend", _slide_money(summary.get("cortex_spend")), f"Top user: {summary.get('top_cortex_user')}."),
        ("30d run-rate", _slide_money(summary.get("projected_30d_spend")), str(summary.get("run_rate_state") or "Not loaded")),
        ("Open actions", _slide_number(action_summary.get("open_actions")), f"{safe_int(action_summary.get('high_actions')):,} high-priority."),
    ]
    if safe_float(service_summary.get("top_moving_delta")):
        rows.append((
            "Service move",
            str(service_summary.get("top_moving_service") or "No movement"),
            f"{safe_float(service_summary.get('top_moving_delta')):+,.2f} credits versus prior.",
        ))
    return pd.DataFrame(rows, columns=["KPI", "VALUE", "SLIDE_NOTE"])


def _cost_snapshot_chart_rows(
    summary: dict,
    action_summary: dict,
    service_lens: pd.DataFrame | None = None,
    credit_price: float = 3.68,
) -> pd.DataFrame:
    rows = [
        ("Spend bridge", "Current spend", safe_float(summary.get("spend")), _slide_money(summary.get("spend"))),
        ("Spend bridge", "Prior spend", safe_float(summary.get("prior_spend")), _slide_money(summary.get("prior_spend"))),
        ("Spend bridge", "Spend delta", safe_float(summary.get("spend_delta")), _slide_money(summary.get("spend_delta"), signed=True)),
        ("Driver dollars", "Top warehouse move", safe_float(summary.get("top_warehouse_delta_spend")), _slide_money(summary.get("top_warehouse_delta_spend"), signed=True)),
        ("Driver dollars", "Cortex spend", safe_float(summary.get("cortex_spend")), _slide_money(summary.get("cortex_spend"))),
        ("Driver dollars", "Top AI user", safe_float(summary.get("top_cortex_user_spend")), _slide_money(summary.get("top_cortex_user_spend"))),
        ("Driver dollars", "Peak day", safe_float(summary.get("peak_day")), _slide_money(summary.get("peak_day"))),
        ("Work queue", "Open actions", safe_float(action_summary.get("open_actions")), _slide_number(action_summary.get("open_actions"))),
        ("Work queue", "High-priority", safe_float(action_summary.get("high_actions")), _slide_number(action_summary.get("high_actions"))),
        ("Work queue", "Savings queue", safe_float(action_summary.get("estimated_savings")), _slide_money(action_summary.get("estimated_savings")) + "/mo"),
    ]
    movement = _service_lens_movement_rows(service_lens, credit_price, limit=5)
    if not movement.empty:
        rows.extend(
            ("Service movement", str(row["SERVICE_TYPE"]), safe_float(row["COST_DELTA_USD"]), str(row["DELTA_LABEL"]))
            for _, row in movement.iterrows()
        )
    return pd.DataFrame(rows, columns=["CHART", "METRIC", "VALUE", "LABEL"])


def _cost_snapshot_slide_brief(
    summary: dict,
    service_summary: dict,
    action_summary: dict,
    *,
    company: str,
    environment_label: str,
    days: int,
) -> str:
    top_service = str(service_summary.get("top_moving_service") or "No service movement")
    service_delta = safe_float(service_summary.get("top_moving_delta"))
    service_line = (
        f"- Service movement: {top_service} moved {service_delta:+,.2f} credits versus prior."
        if service_delta
        else "- Service movement: service-level current/prior deltas are not loaded."
    )
    action_line = (
        f"- Actions: {safe_int(action_summary.get('open_actions')):,} open cost actions, "
            f"{safe_int(action_summary.get('high_actions')):,} high-priority, "
            f"{_slide_money(action_summary.get('estimated_savings'))}/mo estimated savings."
        if safe_int(action_summary.get("open_actions"))
        else "- Actions: action queue and verified savings context are not loaded."
    )
    yoy_pct = summary.get("yoy_7d_pct")
    yoy_line = (
        f"- Run-rate: projected 30d spend is {_slide_money(summary.get('projected_30d_spend'))}; 7d YOY is {_format_optional_pct(yoy_pct)}."
        if yoy_pct is not None
        else f"- Run-rate: projected 30d spend is {_slide_money(summary.get('projected_30d_spend'))}; {summary.get('run_rate_state')}."
    )
    return "\n".join([
        f"OVERWATCH Cost Snapshot - {company} / {environment_label} / {int(days)} days",
        f"Headline: spend is {_slide_money(summary.get('spend'))}, {_slide_money(summary.get('spend_delta'), signed=True)} versus prior ({safe_float(summary.get('delta_pct')):+.1f}%).",
        "",
        "Slide bullets:",
        f"- Spend: {_slide_money(summary.get('spend'))} current window versus {_slide_money(summary.get('prior_spend'))} prior.",
        f"- Warehouse driver: {summary.get('top_warehouse')} moved {safe_float(summary.get('top_warehouse_delta_credits')):+,.2f} credits ({_slide_money(summary.get('top_warehouse_delta_spend'), signed=True)}).",
        f"- Cortex: {_slide_money(summary.get('cortex_spend'))} total; top user {summary.get('top_cortex_user')} at {_slide_money(summary.get('top_cortex_user_spend'))}.",
        yoy_line,
        service_line,
        action_line,
        "",
        "Next decision:",
        "Explain the top warehouse or service movement first, then convert confirmed findings into owned actions.",
    ])


def _render_cost_snapshot_bar_chart(chart_rows: pd.DataFrame, chart_name: str) -> None:
    if not _looks_like_frame(chart_rows) or chart_rows.empty:
        st.caption("No chart rows loaded for this snapshot.")
        return
    data = chart_rows[chart_rows["CHART"].astype(str) == chart_name].copy()
    if data.empty:
        st.caption("No chart rows loaded for this snapshot.")
        return
    data["VALUE"] = pd.to_numeric(data["VALUE"], errors="coerce").fillna(0)
    max_abs = max(abs(float(data["VALUE"].min())), abs(float(data["VALUE"].max())), 1.0)
    palette = _cost_chart_palette()
    alt = _altair()
    bars = (
        alt.Chart(data)
        .mark_bar(cornerRadiusTopRight=3, cornerRadiusBottomRight=3)
        .encode(
            x=alt.X("VALUE:Q", title=None, scale=alt.Scale(domain=[min(0, -max_abs if data["VALUE"].min() < 0 else 0), max_abs])),
            y=alt.Y("METRIC:N", sort=None, title=None, axis=alt.Axis(labelLimit=180)),
            color=alt.condition("datum.VALUE < 0", alt.value(palette["line"]), alt.value(palette["bar"])),
            tooltip=[
                alt.Tooltip("METRIC:N", title="Metric"),
                alt.Tooltip("LABEL:N", title="Value"),
            ],
        )
    )
    labels = alt.Chart(data).mark_text(align="left", dx=5).encode(
        x="VALUE:Q",
        y=alt.Y("METRIC:N", sort=None),
        text="LABEL:N",
    )
    st.altair_chart((bars + labels).properties(height=max(145, 36 * len(data) + 30)), width="stretch")


_PPTX_EMU_PER_INCH = 914400
_PPTX_SLIDE_WIDTH = 12192000
_PPTX_SLIDE_HEIGHT = 6858000
_PPTX_TEXT_COLOR = "F8FAFC"
_PPTX_MUTED_COLOR = "B8C7D8"
_PPTX_PANEL_FILL = "0B1721"
_PPTX_CARD_FILL = "13283A"
_PPTX_GRID_FILL = "1D3346"
_PPTX_ACCENT = "29B5E8"
_PPTX_RISK = "F97316"


def _pptx_emu(inches: float) -> int:
    return int(float(inches) * _PPTX_EMU_PER_INCH)


def _pptx_color(value: str | None, fallback: str = _PPTX_TEXT_COLOR) -> str:
    text = str(value or fallback).strip().lstrip("#")
    return text.upper()[:6] if len(text) >= 6 else fallback


def _pptx_escape(value: object) -> str:
    from xml.sax.saxutils import escape as xml_escape

    return xml_escape(str(value or ""), {'"': "&quot;", "'": "&apos;"})


def _pptx_text_lines(value: object, *, max_lines: int | None = None) -> list[str]:
    lines = [line.strip() for line in str(value or "").replace("\r\n", "\n").split("\n") if line.strip()]
    return lines[:max_lines] if max_lines is not None else lines


def _pptx_paragraphs(lines: list[str], *, font_size: int, color: str, bold: bool = False) -> str:
    size = max(800, int(font_size * 100))
    bold_attr = ' b="1"' if bold else ""
    color = _pptx_color(color)
    if not lines:
        lines = [""]
    paragraphs = []
    for line in lines:
        paragraphs.append(
            f'<a:p><a:r><a:rPr lang="en-US" sz="{size}"{bold_attr}>'
            f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill></a:rPr>'
            f"<a:t>{_pptx_escape(line)}</a:t></a:r>"
            f'<a:endParaRPr lang="en-US" sz="{size}"/></a:p>'
        )
    return "".join(paragraphs)


def _pptx_shape(
    shape_id: int,
    name: str,
    x: float,
    y: float,
    width: float,
    height: float,
    lines: list[str] | str,
    *,
    font_size: int = 18,
    color: str = _PPTX_TEXT_COLOR,
    bold: bool = False,
    fill: str | None = None,
    line: str | None = None,
    radius: bool = False,
    margin: int = 91440,
) -> str:
    if isinstance(lines, str):
        lines = _pptx_text_lines(lines)
    fill_xml = (
        f'<a:solidFill><a:srgbClr val="{_pptx_color(fill)}"/></a:solidFill>'
        if fill
        else "<a:noFill/>"
    )
    line_xml = (
        f'<a:ln><a:solidFill><a:srgbClr val="{_pptx_color(line)}"/></a:solidFill></a:ln>'
        if line
        else "<a:ln><a:noFill/></a:ln>"
    )
    geometry = "roundRect" if radius else "rect"
    return (
        "<p:sp>"
        "<p:nvSpPr>"
        f'<p:cNvPr id="{shape_id}" name="{_pptx_escape(name)}"/>'
        '<p:cNvSpPr txBox="1"/><p:nvPr/>'
        "</p:nvSpPr>"
        "<p:spPr>"
        f'<a:xfrm><a:off x="{_pptx_emu(x)}" y="{_pptx_emu(y)}"/>'
        f'<a:ext cx="{_pptx_emu(width)}" cy="{_pptx_emu(height)}"/></a:xfrm>'
        f'<a:prstGeom prst="{geometry}"><a:avLst/></a:prstGeom>'
        f"{fill_xml}{line_xml}"
        "</p:spPr>"
        f'<p:txBody><a:bodyPr wrap="square" anchor="t" lIns="{margin}" tIns="{margin}" rIns="{margin}" bIns="{margin}"/>'
        f"<a:lstStyle/>{_pptx_paragraphs(lines, font_size=font_size, color=color, bold=bold)}</p:txBody>"
        "</p:sp>"
    )


def _pptx_slide_xml(shapes: list[str], *, background: str = "07111A") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        "<p:cSld>"
        f'<p:bg><p:bgPr><a:solidFill><a:srgbClr val="{_pptx_color(background)}"/></a:solidFill></p:bgPr></p:bg>'
        "<p:spTree>"
        "<p:nvGrpSpPr><p:cNvPr id=\"1\" name=\"\"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>"
        "<p:grpSpPr><a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"0\" cy=\"0\"/>"
        "<a:chOff x=\"0\" y=\"0\"/><a:chExt cx=\"0\" cy=\"0\"/></a:xfrm></p:grpSpPr>"
        f"{''.join(shapes)}"
        "</p:spTree>"
        "</p:cSld>"
        "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>"
        "</p:sld>"
    )


def _pptx_slide_brief_parts(slide_brief: str) -> tuple[str, list[str]]:
    lines = _pptx_text_lines(slide_brief)
    headline = next((line.replace("Headline:", "").strip() for line in lines if line.startswith("Headline:")), "")
    bullets = [line[2:].strip() for line in lines if line.startswith("- ")]
    return headline, bullets[:6]


def _pptx_kpi_lookup(kpi_rows: pd.DataFrame) -> dict[str, tuple[str, str]]:
    if not _looks_like_frame(kpi_rows) or kpi_rows.empty:
        return {}
    lookup: dict[str, tuple[str, str]] = {}
    for _, row in kpi_rows.iterrows():
        key = str(row.get("KPI") or "").strip()
        if key:
            lookup[key] = (str(row.get("VALUE") or ""), str(row.get("SLIDE_NOTE") or ""))
    return lookup


def _build_cost_snapshot_title_slide(
    slide_brief: str,
    kpi_rows: pd.DataFrame,
    *,
    company: str,
    environment_label: str,
    days: int,
) -> str:
    headline, bullets = _pptx_slide_brief_parts(slide_brief)
    kpis = _pptx_kpi_lookup(kpi_rows)
    cards = [
        ("Current spend", *kpis.get("Current spend", ("$0", ""))),
        ("Spend delta", *kpis.get("Spend delta", ("$0", ""))),
        ("Top warehouse", *kpis.get("Top warehouse", ("No warehouse", ""))),
        ("Cortex spend", *kpis.get("Cortex spend", ("$0", ""))),
    ]
    shapes = [
        _pptx_shape(2, "Title", 0.55, 0.35, 7.4, 0.55, "OVERWATCH Cost Snapshot", font_size=28, bold=True),
        _pptx_shape(
            3,
            "Scope",
            0.58,
            0.95,
            7.9,
            0.35,
            f"{company} / {environment_label} / {int(days)} days",
            font_size=13,
            color=_PPTX_MUTED_COLOR,
        ),
        _pptx_shape(4, "Headline", 0.58, 1.45, 7.4, 0.72, headline, font_size=18, bold=True, color="FFFFFF"),
        _pptx_shape(5, "Bullets", 0.58, 2.35, 7.2, 3.0, [f"- {line}" for line in bullets], font_size=15, color=_PPTX_TEXT_COLOR),
    ]
    x = 8.35
    y = 1.15
    for offset, (label, value, note) in enumerate(cards):
        shapes.append(_pptx_shape(10 + offset, f"Card {label}", x, y + offset * 1.25, 4.15, 0.94, "", fill=_PPTX_CARD_FILL, radius=True))
        shapes.append(_pptx_shape(20 + offset, f"Card label {label}", x + 0.18, y + offset * 1.25 + 0.08, 3.7, 0.2, label, font_size=9, color=_PPTX_MUTED_COLOR, bold=True))
        shapes.append(_pptx_shape(30 + offset, f"Card value {label}", x + 0.18, y + offset * 1.25 + 0.32, 3.7, 0.32, value, font_size=20, color="FFFFFF", bold=True))
        shapes.append(_pptx_shape(40 + offset, f"Card note {label}", x + 0.18, y + offset * 1.25 + 0.66, 3.7, 0.18, note, font_size=8, color=_PPTX_MUTED_COLOR))
    return _pptx_slide_xml(shapes)


def _build_cost_snapshot_kpi_slide(kpi_rows: pd.DataFrame, *, company: str, environment_label: str) -> str:
    shapes = [
        _pptx_shape(2, "Title", 0.55, 0.35, 7.2, 0.5, "KPI Readout", font_size=26, bold=True),
        _pptx_shape(3, "Scope", 0.58, 0.9, 7.5, 0.3, f"{company} / {environment_label}", font_size=12, color=_PPTX_MUTED_COLOR),
    ]
    rows = kpi_rows.head(9).copy() if _looks_like_frame(kpi_rows) and not kpi_rows.empty else pd.DataFrame()
    headers = [("KPI", 0.7, 1.45, 2.1), ("Value", 2.85, 1.45, 2.15), ("Slide note", 5.1, 1.45, 7.0)]
    for idx, (label, x, y, width) in enumerate(headers):
        shapes.append(_pptx_shape(10 + idx, f"Header {label}", x, y, width, 0.35, label, font_size=11, color="FFFFFF", bold=True, fill=_PPTX_GRID_FILL))
    for row_idx, (_, row) in enumerate(rows.iterrows()):
        y = 1.86 + row_idx * 0.55
        fill = _PPTX_PANEL_FILL if row_idx % 2 else "102335"
        cells = [
            (str(row.get("KPI") or ""), 0.7, 2.1, 13, True),
            (str(row.get("VALUE") or ""), 2.85, 2.15, 13, True),
            (str(row.get("SLIDE_NOTE") or ""), 5.1, 7.0, 11, False),
        ]
        for cell_idx, (text, x, width, font_size, bold) in enumerate(cells):
            shapes.append(
                _pptx_shape(
                    30 + row_idx * 4 + cell_idx,
                    f"KPI {row_idx} {cell_idx}",
                    x,
                    y,
                    width,
                    0.44,
                    text,
                    font_size=font_size,
                    color=_PPTX_TEXT_COLOR,
                    bold=bold,
                    fill=fill,
                    margin=64008,
                )
            )
    return _pptx_slide_xml(shapes)


def _pptx_bar_chart_shapes(
    chart_rows: pd.DataFrame,
    chart_name: str,
    *,
    start_id: int,
    x: float,
    y: float,
    width: float,
    height: float,
) -> list[str]:
    if not _looks_like_frame(chart_rows) or chart_rows.empty:
        return [
            _pptx_shape(start_id, f"{chart_name} empty", x, y, width, height, "No chart rows loaded.", font_size=12, color=_PPTX_MUTED_COLOR, fill=_PPTX_PANEL_FILL, radius=True)
        ]
    data = chart_rows[chart_rows["CHART"].astype(str) == chart_name].copy()
    if data.empty:
        return [
            _pptx_shape(start_id, f"{chart_name} empty", x, y, width, height, "No chart rows loaded.", font_size=12, color=_PPTX_MUTED_COLOR, fill=_PPTX_PANEL_FILL, radius=True)
        ]
    data["VALUE"] = pd.to_numeric(data["VALUE"], errors="coerce").fillna(0)
    max_abs = max(abs(float(data["VALUE"].min())), abs(float(data["VALUE"].max())), 1.0)
    has_negative = bool((data["VALUE"] < 0).any())
    label_width = min(2.2, width * 0.36)
    value_width = width - label_width - 0.25
    row_height = max(0.35, min(0.55, (height - 0.55) / max(1, len(data))))
    shapes = [
        _pptx_shape(start_id, f"{chart_name} panel", x, y, width, height, "", fill=_PPTX_PANEL_FILL, radius=True),
        _pptx_shape(start_id + 1, f"{chart_name} title", x + 0.18, y + 0.12, width - 0.36, 0.28, chart_name, font_size=14, color="FFFFFF", bold=True),
    ]
    for row_idx, (_, row) in enumerate(data.head(6).iterrows()):
        value = safe_float(row.get("VALUE"))
        label = str(row.get("METRIC") or "")
        display = str(row.get("LABEL") or _slide_number(value))
        row_y = y + 0.55 + row_idx * row_height
        shapes.append(
            _pptx_shape(
                start_id + 10 + row_idx * 4,
                f"{chart_name} label {row_idx}",
                x + 0.18,
                row_y,
                label_width,
                row_height * 0.78,
                label,
                font_size=9,
                color=_PPTX_MUTED_COLOR,
                margin=45720,
            )
        )
        track_x = x + 0.22 + label_width
        track_y = row_y + 0.06
        track_h = row_height * 0.44
        shapes.append(
            _pptx_shape(
                start_id + 11 + row_idx * 4,
                f"{chart_name} track {row_idx}",
                track_x,
                track_y,
                value_width,
                track_h,
                "",
                fill=_PPTX_GRID_FILL,
            )
        )
        if has_negative:
            half = value_width / 2
            bar_w = max(0.05, half * min(1.0, abs(value) / max_abs))
            bar_x = track_x + half - bar_w if value < 0 else track_x + half
        else:
            bar_w = max(0.05, value_width * min(1.0, abs(value) / max_abs))
            bar_x = track_x
        color = _PPTX_RISK if value < 0 else _PPTX_ACCENT
        shapes.append(
            _pptx_shape(
                start_id + 12 + row_idx * 4,
                f"{chart_name} bar {row_idx}",
                bar_x,
                track_y,
                bar_w,
                track_h,
                "",
                fill=color,
            )
        )
        shapes.append(
            _pptx_shape(
                start_id + 13 + row_idx * 4,
                f"{chart_name} value {row_idx}",
                track_x + value_width + 0.08,
                row_y,
                max(0.6, width - label_width - value_width - 0.55),
                row_height * 0.78,
                display,
                font_size=9,
                color=_PPTX_TEXT_COLOR,
                bold=True,
                margin=45720,
            )
        )
    return shapes


def _build_cost_snapshot_chart_slide(chart_rows: pd.DataFrame) -> str:
    chart_names = ["Spend bridge", "Driver dollars", "Work queue"]
    if _looks_like_frame(chart_rows) and "Service movement" in set(chart_rows.get("CHART", pd.Series(dtype=str)).astype(str)):
        chart_names.append("Service movement")
    shapes = [
        _pptx_shape(2, "Title", 0.55, 0.35, 7.2, 0.5, "Chart-Ready Drivers", font_size=26, bold=True),
        _pptx_shape(3, "Subtitle", 0.58, 0.9, 9.0, 0.3, "Bars are generated from the same rows available in the app download.", font_size=12, color=_PPTX_MUTED_COLOR),
    ]
    panels = [
        (chart_names[0], 0.65, 1.45, 5.95, 2.25),
        (chart_names[1], 6.85, 1.45, 5.65, 2.25),
        (chart_names[2], 0.65, 4.05, 5.95, 1.95),
    ]
    if len(chart_names) > 3:
        panels.append((chart_names[3], 6.85, 4.05, 5.65, 1.95))
    for idx, (chart_name, x, y, width, height) in enumerate(panels):
        shapes.extend(_pptx_bar_chart_shapes(chart_rows, chart_name, start_id=20 + idx * 50, x=x, y=y, width=width, height=height))
    return _pptx_slide_xml(shapes)


def _pptx_rels(entries: list[tuple[str, str, str]]) -> str:
    relationships = "".join(
        f'<Relationship Id="{rel_id}" Type="{rel_type}" Target="{_pptx_escape(target)}"/>'
        for rel_id, rel_type, target in entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{relationships}</Relationships>"
    )


def _pptx_content_types(slide_count: int) -> str:
    slide_overrides = "".join(
        f'<Override PartName="/ppt/slides/slide{idx}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for idx in range(1, slide_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
        '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
        '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
        '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
        f"{slide_overrides}</Types>"
    )


def _pptx_presentation_xml(slide_count: int) -> str:
    slide_ids = "".join(f'<p:sldId id="{255 + idx}" r:id="rId{idx + 1}"/>' for idx in range(1, slide_count + 1))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        f"<p:sldIdLst>{slide_ids}</p:sldIdLst>"
        f'<p:sldSz cx="{_PPTX_SLIDE_WIDTH}" cy="{_PPTX_SLIDE_HEIGHT}" type="wide"/>'
        '<p:notesSz cx="6858000" cy="9144000"/>'
        "</p:presentation>"
    )


def _pptx_slide_master_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        '<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/>'
        '<a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>'
        '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" '
        'accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
        '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
        '<p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles>'
        "</p:sldMaster>"
    )


def _pptx_slide_layout_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank" preserve="1">'
        '<p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/>'
        '<a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>'
        '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>'
        "</p:sldLayout>"
    )


def _pptx_theme_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="OVERWATCH">'
        '<a:themeElements><a:clrScheme name="OVERWATCH">'
        '<a:dk1><a:srgbClr val="07111A"/></a:dk1><a:lt1><a:srgbClr val="F8FAFC"/></a:lt1>'
        '<a:dk2><a:srgbClr val="13283A"/></a:dk2><a:lt2><a:srgbClr val="B8C7D8"/></a:lt2>'
        '<a:accent1><a:srgbClr val="29B5E8"/></a:accent1><a:accent2><a:srgbClr val="71D3DC"/></a:accent2>'
        '<a:accent3><a:srgbClr val="F97316"/></a:accent3><a:accent4><a:srgbClr val="10B981"/></a:accent4>'
        '<a:accent5><a:srgbClr val="EAB308"/></a:accent5><a:accent6><a:srgbClr val="8B5CF6"/></a:accent6>'
        '<a:hlink><a:srgbClr val="29B5E8"/></a:hlink><a:folHlink><a:srgbClr val="71D3DC"/></a:folHlink>'
        '</a:clrScheme><a:fontScheme name="OVERWATCH"><a:majorFont><a:latin typeface="Aptos Display"/>'
        '<a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="Aptos"/>'
        '<a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme><a:fmtScheme name="OVERWATCH">'
        '<a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
        '<a:solidFill><a:schemeClr val="phClr"><a:tint val="95000"/></a:schemeClr></a:solidFill>'
        '<a:solidFill><a:schemeClr val="phClr"><a:shade val="85000"/></a:schemeClr></a:solidFill></a:fillStyleLst>'
        '<a:lnStyleLst><a:ln w="6350" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:schemeClr val="phClr"/>'
        '</a:solidFill><a:prstDash val="solid"/></a:ln><a:ln w="12700" cap="flat" cmpd="sng" algn="ctr">'
        '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/></a:ln>'
        '<a:ln w="19050" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:schemeClr val="phClr"/>'
        '</a:solidFill><a:prstDash val="solid"/></a:ln></a:lnStyleLst>'
        '<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/>'
        '</a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>'
        '<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
        '<a:solidFill><a:schemeClr val="phClr"><a:tint val="95000"/></a:schemeClr></a:solidFill>'
        '<a:solidFill><a:schemeClr val="phClr"><a:shade val="85000"/></a:schemeClr></a:solidFill></a:bgFillStyleLst>'
        "</a:fmtScheme></a:themeElements>"
        "</a:theme>"
    )


def _pptx_doc_props(slide_count: int) -> tuple[str, str]:
    timestamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<dc:title>OVERWATCH Cost Snapshot</dc:title><dc:creator>OVERWATCH</dc:creator>'
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:modified>'
        "</cp:coreProperties>"
    )
    app = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        '<Application>OVERWATCH</Application><PresentationFormat>On-screen Show (16:9)</PresentationFormat>'
        f"<Slides>{int(slide_count)}</Slides></Properties>"
    )
    return core, app


def _build_cost_snapshot_pptx(
    slide_brief: str,
    kpi_rows: pd.DataFrame,
    chart_rows: pd.DataFrame,
    *,
    company: str,
    environment_label: str,
    days: int,
) -> bytes:
    from io import BytesIO
    import zipfile

    slides = [
        _build_cost_snapshot_title_slide(slide_brief, kpi_rows, company=company, environment_label=environment_label, days=days),
        _build_cost_snapshot_kpi_slide(kpi_rows, company=company, environment_label=environment_label),
        _build_cost_snapshot_chart_slide(chart_rows),
    ]
    core_props, app_props = _pptx_doc_props(len(slides))
    presentation_rels = [(
        "rId1",
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster",
        "slideMasters/slideMaster1.xml",
    )]
    presentation_rels.extend(
        (
            f"rId{idx + 1}",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide",
            f"slides/slide{idx}.xml",
        )
        for idx in range(1, len(slides) + 1)
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _pptx_content_types(len(slides)))
        archive.writestr("_rels/.rels", _pptx_rels([
            ("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument", "ppt/presentation.xml"),
            ("rId2", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "docProps/core.xml"),
            ("rId3", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties", "docProps/app.xml"),
        ]))
        archive.writestr("docProps/core.xml", core_props)
        archive.writestr("docProps/app.xml", app_props)
        archive.writestr("ppt/presentation.xml", _pptx_presentation_xml(len(slides)))
        archive.writestr("ppt/_rels/presentation.xml.rels", _pptx_rels(presentation_rels))
        archive.writestr("ppt/slideMasters/slideMaster1.xml", _pptx_slide_master_xml())
        archive.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", _pptx_rels([
            ("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout", "../slideLayouts/slideLayout1.xml"),
            ("rId2", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme", "../theme/theme1.xml"),
        ]))
        archive.writestr("ppt/slideLayouts/slideLayout1.xml", _pptx_slide_layout_xml())
        archive.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", _pptx_rels([
            ("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster", "../slideMasters/slideMaster1.xml"),
        ]))
        archive.writestr("ppt/theme/theme1.xml", _pptx_theme_xml())
        for idx, slide_xml in enumerate(slides, start=1):
            archive.writestr(f"ppt/slides/slide{idx}.xml", slide_xml)
            archive.writestr(f"ppt/slides/_rels/slide{idx}.xml.rels", _pptx_rels([
                ("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout", "../slideLayouts/slideLayout1.xml"),
            ]))
    return buffer.getvalue()


def _render_powerpoint_cost_snapshot(splash: dict, *, company: str, days: int, credit_price: float) -> None:
    summary = _cost_splash_summary(splash, credit_price, days)
    environment = get_active_environment()
    environment_label = get_environment_label(environment, company)
    service_lens = st.session_state.get("cost_contract_service_lens", pd.DataFrame())
    if not _looks_like_frame(service_lens) or service_lens.empty:
        service_lens = splash.get("service_costs", pd.DataFrame())
    service_summary = _build_service_cost_lens_summary(service_lens)
    action_summary = _cost_snapshot_action_summary(st.session_state.get("cost_contract_queue", pd.DataFrame()))
    kpi_rows = _cost_snapshot_kpi_rows(
        summary,
        service_summary,
        action_summary,
        company=company,
        environment_label=environment_label,
        days=days,
    )
    chart_rows = _cost_snapshot_chart_rows(summary, action_summary, service_lens=service_lens, credit_price=credit_price)
    slide_brief = _cost_snapshot_slide_brief(
        summary,
        service_summary,
        action_summary,
        company=company,
        environment_label=environment_label,
        days=days,
    )
    st.markdown("**PowerPoint Cost Snapshot**")
    st.text_area("Slide bullets", value=slide_brief, height=210, key="cost_contract_powerpoint_slide_bullets")
    file_scope = f"{_safe_filename_piece(company)}_{_safe_filename_piece(environment_label)}_{int(days)}d"
    deck_bytes = _build_cost_snapshot_pptx(
        slide_brief,
        kpi_rows,
        chart_rows,
        company=company,
        environment_label=environment_label,
        days=days,
    )
    dl_cols = st.columns([1.0, 1.0, 1.0, 1.0])
    dl_cols[0].download_button(
        "Download slide bullets",
        slide_brief,
        file_name=f"overwatch_cost_snapshot_{file_scope}.txt",
        mime="text/plain",
        key="cost_contract_powerpoint_bullets_download",
    )
    dl_cols[1].download_button(
        "Download chart data",
        chart_rows.to_csv(index=False, sep="\t"),
        file_name=f"overwatch_cost_snapshot_{file_scope}_chart_data.tsv",
        mime="text/tab-separated-values",
        key="cost_contract_powerpoint_chart_download",
    )
    dl_cols[2].download_button(
        "Download PowerPoint",
        deck_bytes,
        file_name=f"overwatch_cost_snapshot_{file_scope}.pptx",
        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        key="cost_contract_powerpoint_deck_download",
    )
    with st.expander("PowerPoint support data", expanded=False):
        render_priority_dataframe(
            kpi_rows,
            title="Slide KPI rows",
            priority_columns=["KPI", "VALUE", "SLIDE_NOTE"],
            raw_label="All PowerPoint KPI rows",
            height=250,
            max_rows=10,
        )
        chart_names = ["Spend bridge", "Driver dollars"]
        if "Service movement" in set(chart_rows["CHART"].astype(str)):
            chart_names.append("Service movement")
        chart_cols = st.columns(len(chart_names))
        for column, chart_name in zip(chart_cols, chart_names):
            with column:
                st.markdown(f"**{chart_name.title()}**")
                _render_cost_snapshot_bar_chart(chart_rows, chart_name)


def _render_powerpoint_snapshot_gate(splash: dict, *, company: str, days: int, credit_price: float) -> None:
    show_snapshot = bool(st.session_state.get(_POWERPOINT_SNAPSHOT_KEY))
    action_cols = st.columns([1.1, 1.1, 3.0])
    with action_cols[0]:
        if not show_snapshot and st.button(
            "Prepare PowerPoint Snapshot",
            key="cost_contract_prepare_powerpoint_snapshot",
            width="stretch",
        ):
            st.session_state[_POWERPOINT_SNAPSHOT_KEY] = True
            st.rerun()
    with action_cols[1]:
        if show_snapshot and st.button(
            "Hide Snapshot",
            key="cost_contract_hide_powerpoint_snapshot",
            width="stretch",
        ):
            st.session_state[_POWERPOINT_SNAPSHOT_KEY] = False
            st.rerun()
    with action_cols[2]:
        if show_snapshot:
            st.caption("Slide bullets, chart data, and PowerPoint export are prepared for this loaded cost window.")
        else:
            st.caption("Slide-ready evidence stays unloaded until leadership reporting is needed.")

    if not show_snapshot:
        return

    with st.expander("PowerPoint-ready snapshot", expanded=True):
        _render_powerpoint_cost_snapshot(splash, company=company, days=int(days), credit_price=credit_price)


def _render_cost_splash(splash: dict, *, company: str, days: int, credit_price: float) -> None:
    st.markdown("**Cost Overview**")
    if not splash.get("loaded"):
        st.caption("Refresh Overview loads official spend, warehouse ranking, Cortex spend, and slide-ready evidence.")
        render_shell_snapshot((
            ("Spend", "On demand"),
            ("Change", "On demand"),
            ("Driver", "On demand"),
            ("30d Run", "On demand"),
        ))
        if splash.get("errors"):
            for err in splash.get("errors", [])[:2]:
                defer_source_note(str(err))
        return

    summary = _cost_splash_summary(splash, credit_price, days)
    if splash.get("errors") and not summary["has_data"]:
        st.warning("Cost splash could not load from the mart or live fallback for this role.")
        for err in splash.get("errors", [])[:2]:
            defer_source_note(str(err))
        return

    _render_cost_splash_narrative(summary, days=int(days))
    _render_cost_splash_next_move(summary)

    if splash.get("source"):
        proof_note = (
            "Refresh Overview loads spend trend, full cockpit, and run-rate proof."
            if not splash.get("full_proof")
            else "Full overview proof is loaded."
        )
        defer_source_note(f"Cost splash source: {splash['source']}. {proof_note} Cached query results keep this page fast.")

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

    _render_powerpoint_snapshot_gate(splash, company=company, days=int(days), credit_price=credit_price)


def _cost_action_brief(company: str, days: int, credit_price: float) -> dict:
    data = st.session_state.get("cost_contract_cockpit")
    meta = st.session_state.get("cost_contract_cockpit_meta", {})
    err = str(st.session_state.get("cost_contract_cockpit_error", "") or "")
    data_loaded = _looks_like_frame(data) and not data.empty
    scope_matches = meta.get("company") == company and meta.get("days") == int(days)

    if err:
        return {
            "state": "Unavailable",
            "headline": "Cost cockpit did not load for this role or source.",
            "detail": "Specialist cost workflows remain available; reload the cockpit when Snowflake access is ready.",
        }
    if not data_loaded:
        return {
            "state": "Ready",
            "headline": "Load the cost cockpit before explaining bill movement.",
            "detail": "The cockpit stays quiet until you request warehouse, contract, action, and savings proof.",
        }
    if not scope_matches:
        return {
            "state": "Stale",
            "headline": "Reload Cost Cockpit before acting.",
            "detail": "Loaded cost evidence does not match the active company or cockpit window.",
        }

    row = data.iloc[0]
    current_credits = safe_float(row.get("CURRENT_CREDITS", 0))
    prior_credits = safe_float(row.get("PRIOR_CREDITS", 0))
    delta_pct = ((current_credits - prior_credits) / prior_credits * 100) if prior_credits > 0 else 0.0
    top_wh = str(row.get("TOP_INCREASE_WAREHOUSE") or "No increase")
    top_delta = safe_float(row.get("TOP_INCREASE_CREDITS", 0))
    queue = st.session_state.get("cost_contract_queue")
    open_actions = high_actions = 0
    if _looks_like_frame(queue) and not queue.empty and "STATUS" in queue.columns:
        open_mask = ~queue["STATUS"].isin(["Fixed", "Ignored"])
        open_actions = int(open_mask.sum())
        if "SEVERITY" in queue.columns:
            high_actions = int((queue["SEVERITY"].isin(["Critical", "High"]) & open_mask).sum())

    if delta_pct >= 20 or top_delta > 0:
        return {
            "state": "Bill Move",
            "headline": "Explain the top warehouse movement first.",
            "detail": f"{top_wh} moved {top_delta:+,.2f} credits; selected window is {delta_pct:+.1f}% versus prior.",
        }
    if high_actions:
        return {
            "state": "Action Queue",
            "headline": "Work high-priority savings or cost-control actions.",
            "detail": f"{high_actions:,} high-priority action(s) across {open_actions:,} open cost action(s).",
        }
    if current_credits > 0:
        return {
            "state": "Loaded",
            "headline": "No dominant cost incident in the loaded cockpit.",
            "detail": f"Selected window spend is about ${current_credits * credit_price:,.0f}; use workflows for attribution or value proof.",
        }
    return {
        "state": "Clear",
        "headline": "No warehouse spend surfaced in the loaded cockpit.",
        "detail": "Use specialist workflows only if a chargeback, contract, or savings question remains.",
    }


def _render_cost_action_brief(brief: dict) -> None:
    with st.container(border=True):
        label_col, detail_col = st.columns([1.1, 4.6])
        with label_col:
            st.markdown("**Action Brief**")
            st.caption(str(brief.get("state") or "Review"))
        with detail_col:
            st.markdown(f"**{brief.get('headline') or 'Review cost evidence.'}**")
            st.caption(str(brief.get("detail") or ""))


def _cost_operating_snapshot(company: str, days: int, credit_price: float) -> dict:
    data = st.session_state.get("cost_contract_cockpit")
    meta = st.session_state.get("cost_contract_cockpit_meta", {})
    loaded = (
        _looks_like_frame(data)
        and not data.empty
        and meta.get("company") == company
        and meta.get("days") == int(days)
    )
    if not loaded:
        return {"loaded": False}

    row = data.iloc[0]
    current_credits = safe_float(row.get("CURRENT_CREDITS", 0))
    prior_credits = safe_float(row.get("PRIOR_CREDITS", 0))
    delta_pct = ((current_credits - prior_credits) / prior_credits * 100) if prior_credits > 0 else 0.0
    queue = st.session_state.get("cost_contract_queue")
    open_actions = 0
    if _looks_like_frame(queue) and not queue.empty and "STATUS" in queue.columns:
        status = queue["STATUS"].fillna("").astype(str)
        open_actions = int((~status.isin(["Fixed", "Ignored"])).sum())

    return {
        "loaded": True,
        "spend": credits_to_dollars(current_credits, credit_price),
        "delta_pct": delta_pct,
        "top_delta_credits": safe_float(row.get("TOP_INCREASE_CREDITS", 0)),
        "open_actions": open_actions,
    }


def _render_cost_operating_snapshot(snapshot: dict) -> None:
    st.markdown("**Operating Snapshot**")
    loaded = bool(snapshot.get("loaded"))
    if not loaded:
        render_shell_snapshot((
            ("Spend", "On demand"),
            ("Delta", "Load proof"),
            ("Top Inc", "Load proof"),
            ("Actions", "Load queue"),
        ))
        return
    render_shell_snapshot((
        ("Spend", f"${safe_float(snapshot.get('spend')):,.0f}"),
        ("Delta", f"{safe_float(snapshot.get('delta_pct')):+.1f}%"),
        ("Top Inc", f"{safe_float(snapshot.get('top_delta_credits')):+,.1f} cr"),
        ("Actions", f"{safe_int(snapshot.get('open_actions')):,}"),
    ))


def _render_cost_watch_floor(company: str, credit_price: float) -> None:
    selected_days = safe_int(
        st.session_state.get("cost_contract_cockpit_window", DEFAULT_DAY_WINDOW),
        DEFAULT_DAY_WINDOW,
    )
    if selected_days not in DAY_WINDOW_OPTIONS:
        selected_days = DEFAULT_DAY_WINDOW

    controls = st.columns([1.0, 1.0, 1.0, 1.6])
    with controls[0]:
        days = st.selectbox(
            "Cost window",
            DAY_WINDOW_OPTIONS,
            index=DAY_WINDOW_OPTIONS.index(selected_days),
            format_func=lambda d: f"{d} days",
            key="cost_contract_cockpit_window",
        )
    with controls[1]:
        refresh_overview = st.button("Refresh Overview", key="cost_contract_splash_load", type="primary", width="stretch")
    with controls[2]:
        if st.button("Refresh Cost", key="cost_contract_splash_refresh", width="stretch"):
            st.session_state.pop(_COST_SPLASH_KEY, None)
            st.session_state.pop(_COST_SPLASH_AUTOLOAD_SCOPE_KEY, None)
            st.session_state.pop(_COST_SPLASH_AUTOLOAD_BLOCKED_SCOPE_KEY, None)
            st.session_state.pop(_POWERPOINT_SNAPSHOT_KEY, None)
            st.rerun()

    if refresh_overview:
        st.session_state.pop(_COST_SPLASH_AUTOLOAD_BLOCKED_SCOPE_KEY, None)
        splash = _ensure_cost_splash(company, int(days), credit_price)
    else:
        splash = _maybe_autoload_cost_splash(company, int(days), credit_price)
    _render_cost_splash(splash, company=company, days=int(days), credit_price=credit_price)

    st.markdown("**Cost Proof Workspace**")
    if st.button("Load Full Cost Proof", key="cost_contract_cockpit_load", type="primary"):
            st.session_state.pop(_FULL_COCKPIT_BOARDS_KEY, None)
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
                st.session_state["cost_contract_cockpit_meta"] = {"company": company, "days": int(days)}
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
                    st.session_state["cost_contract_cockpit_meta"] = {"company": company, "days": int(days)}
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
                st.session_state["cost_contract_verification_health"] = run_query(
                    build_cost_savings_verification_health_sql(),
                    ttl_key="cost_contract_verification_health",
                    tier="recent",
                    section="Cost & Contract",
                )
                st.session_state["cost_contract_verification_health_error"] = ""
            except Exception as exc:
                st.session_state["cost_contract_verification_health"] = pd.DataFrame()
                st.session_state["cost_contract_verification_health_error"] = format_snowflake_error(exc)
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
                st.session_state["cost_contract_service_lens"] = run_query_or_raise(
                    build_snowflake_service_cost_lens_sql(
                        int(days),
                        credit_price,
                        ai_credit_price=get_current_ai_credit_price(),
                    ),
                    ttl_key=f"cost_contract_service_lens_official_{company}_{days}_{credit_price}",
                    tier="historical",
                    section="Cost & Contract",
                )
                st.session_state["cost_contract_service_lens_error"] = ""
                st.session_state["cost_contract_service_lens_source"] = (
                    "Official Cost Monitor: SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY"
                )
            except Exception as exc:
                st.session_state["cost_contract_service_lens"] = pd.DataFrame()
                st.session_state["cost_contract_service_lens_error"] = format_snowflake_error(exc)
                st.session_state["cost_contract_service_lens_source"] = ""
    defer_section_note(
        "Cost cockpit: Load it to decide whether to explain the bill, work the action queue, inspect Cortex spend, or log verified savings."
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
            "Click Load Cost Cockpit to refresh the watch floor."
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
        verification_health=st.session_state.get("cost_contract_verification_health", pd.DataFrame()),
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
    if not st.session_state.get(_FULL_COCKPIT_BOARDS_KEY):
        if st.button("Open full cockpit boards", key="cost_contract_open_full_cockpit_boards"):
            st.session_state[_FULL_COCKPIT_BOARDS_KEY] = True
            st.rerun()
        st.caption("Derived governance, incident, allocation, and drilldown boards are rendered only when opened.")
        return

    _render_budget_anomaly_command_center(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
        credit_price,
    )
    _render_cost_spike_root_cause_board(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
        credit_price,
    )
    _render_native_cost_control_inventory(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
        st.session_state.get("cost_contract_verification_health", pd.DataFrame()),
        credit_price,
    )
    _render_change_cost_correlation_board(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
    )
    _render_cost_governance_mart_and_incident_timeline(
        company=company,
        cockpit=data,
        run_rate=st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue=queue,
    )
    _render_governed_admin_action_pack(
        company,
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        credit_price,
    )

    _render_savings_verification_task_health(
        st.session_state.get("cost_contract_verification_health", pd.DataFrame()),
        st.session_state.get("cost_contract_verification_health_error", ""),
    )
    _render_savings_closure_control(queue, credit_price)
    _render_cost_control_coverage_board(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
        st.session_state.get("cost_contract_verification_health", pd.DataFrame()),
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
            "Explain the bill movement",
            f"Top increase: {row.get('TOP_INCREASE_WAREHOUSE', 'unknown')} "
            f"({safe_float(row.get('TOP_INCREASE_CREDITS', 0)):,.2f} credits).",
            "Explain bill / attribution / contract",
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
            "Log value or review attribution",
            "No dominant cost incident in this cockpit window. Use value log for verified DBA wins or attribution for chargeback.",
            "Snowflake value log",
        ))

    st.markdown("**Next Cost Moves**")
    cols = st.columns(min(len(moves), 3))
    for idx, (title, evidence, workflow) in enumerate(moves[:3]):
        with cols[idx]:
            st.markdown(f"**{title}**")
            st.caption(evidence)
            if st.button(f"Open {workflow}", key=f"cost_contract_next_{idx}_{workflow}", width="stretch"):
                st.session_state["cost_contract_workflow"] = workflow
                st.session_state[_DETAIL_WORKFLOW_KEY] = workflow
                st.rerun()


def render() -> None:
    company = get_active_company()
    credit_price = safe_float(get_credit_price()) or 3.68
    if st.session_state.get("exceptions_only_mode") and "cost_contract_workflow" not in st.session_state:
        st.session_state["cost_contract_workflow"] = "Explain bill / attribution / contract"
    render_signal_confidence(
        source="ACCOUNT_USAGE",
        confidence="allocated",
        scope_note="Warehouse totals are exact; user/query chargeback is allocated unless noted.",
    )
    render_operator_briefing(
        [
            ("First move", "Explain why spend changed before tuning anything."),
            ("Evidence", "Reconcile warehouse metering, chargeback allocation, Cortex, and contract pace."),
            ("Control", "Convert findings into owned actions with savings and proof."),
            ("Output", "Produce a bill narrative leadership can understand without opening the app."),
        ],
        columns=4,
    )
    if st.session_state.get("exceptions_only_mode"):
        st.warning("Exceptions-only mode: prioritize bill deltas, open action queue items, and contract risk.")
    _render_cost_watch_floor(company, credit_price)

    workflow = render_workflow_selector(
        "Cost workflow",
        "cost_contract_workflow",
        WORKFLOWS,
        WORKFLOW_DETAILS,
        columns=5,
    )

    open_workflow = st.session_state.get(_DETAIL_WORKFLOW_KEY)
    if open_workflow not in WORKFLOWS:
        open_workflow = ""
        st.session_state.pop(_DETAIL_WORKFLOW_KEY, None)

    detail_cols = st.columns([1, 4])
    with detail_cols[0]:
        if st.button("Open detail", key="cost_contract_open_workflow_detail", width="stretch"):
            st.session_state[_DETAIL_WORKFLOW_KEY] = workflow
            st.rerun()
    with detail_cols[1]:
        if open_workflow and open_workflow != workflow:
            st.caption(f"Detail workspace is open for {open_workflow}. Select it again or open the current workflow.")
        else:
            st.caption(f"Selected workflow: {workflow}")

    if open_workflow == workflow:
        render_workflow_module(workflow, WORKFLOW_MODULES)
