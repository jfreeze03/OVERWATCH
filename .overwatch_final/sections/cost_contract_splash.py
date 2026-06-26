# sections/cost_contract_splash.py - Cost & Contract splash loading and summary helpers.
from __future__ import annotations

import streamlit as st

from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.cost_contract_advisor import _open_cost_action_frame
from sections.cost_contract_charts import (
    _render_cost_chart_with_data_toggle,
    _render_spend_trend_chart,
    _render_warehouse_ranking_chart,
)
from sections.cost_contract_contracts import (
    _COST_SPLASH_AUTOLOAD_SCOPE_KEY,
    _COST_SPLASH_KEY,
)
from sections.cost_contract_dataframes import (
    _cost_spend_trend_rows,
    _cost_warehouse_ranking_rows,
    _looks_like_frame,
)
from sections.cost_contract_helpers import get_current_ai_credit_price
from sections.cost_contract_overview_panels import (
    _cost_snapshot_action_summary,
    _nullable_float,
    _render_cost_executive_decision_stack,
    _render_cost_splash_narrative,
    _render_cost_splash_next_move,
)
from sections.cost_contract_sql import (
    _build_cost_cockpit_sql,
    _build_cost_run_rate_sql,
    _build_cost_splash_cortex_sql,
    _build_cost_splash_warehouse_delta_sql,
)
from sections.shell_helpers import consume_section_autoload_request
from sections.decision_workspace_target_filters import build_target_sql_filter
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_source_note


pd = lazy_pandas()

build_mart_cost_cockpit_sql = _lazy_util("build_mart_cost_cockpit_sql")
build_mart_cost_run_rate_sql = _lazy_util("build_mart_cost_run_rate_sql")
credits_to_dollars = _lazy_util("credits_to_dollars")
format_snowflake_error = _lazy_util("format_snowflake_error")
get_session_for_action = _lazy_util("get_session_for_action")
load_shared_service_cost_lens = _lazy_util("load_shared_service_cost_lens")
load_shared_service_cost_trend = _lazy_util("load_shared_service_cost_trend")
run_query_or_raise = _lazy_util("run_query_or_raise")


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


def _target_wrapped_sql(sql: str, target: dict[str, str] | None) -> str:
    target_filter = build_target_sql_filter(
        "Cost & Contract",
        target or {},
        alias="target",
        available_columns=("WAREHOUSE_NAME", "ENTITY_NAME", "ENTITY_ID", "DRIVER", "DIMENSION"),
    )
    if not target_filter:
        return sql
    return f"""
        SELECT *
        FROM (
            {sql}
        ) target
        WHERE 1 = 1
          {target_filter}
    """


def _ensure_cost_splash(
    company: str,
    days: int,
    credit_price: float,
    *,
    full_proof: bool = True,
    target: dict[str, str] | None = None,
) -> dict:
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
        _target_wrapped_sql(_build_cost_splash_warehouse_delta_sql(company, int(days), mart=True), target),
        _target_wrapped_sql(_build_cost_splash_warehouse_delta_sql(company, int(days), mart=False), target),
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
    """Return cached cost landing data; navigation first paint stays query-on-demand."""
    meta = _cost_splash_meta(company, days, credit_price)
    cached = st.session_state.get(_COST_SPLASH_KEY)
    if isinstance(cached, dict) and cached.get("meta") == meta and cached.get("loaded"):
        return cached
    if consume_section_autoload_request("Cost & Contract"):
        st.session_state[_COST_SPLASH_AUTOLOAD_SCOPE_KEY] = meta
        st.caption(
            "Cost & Contract opened without loading cost facts. Refresh Cost loads official spend, "
            "warehouse ranking, Cortex spend, and supporting telemetry."
        )
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


def _slide_number(value: float, suffix: str = "") -> str:
    return f"{safe_float(value):,.0f}{suffix}"


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
