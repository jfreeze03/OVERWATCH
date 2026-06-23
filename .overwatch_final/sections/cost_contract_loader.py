# sections/cost_contract_loader.py - Explicit Cost & Contract detail refresh helper.
from __future__ import annotations

from collections.abc import MutableMapping

from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.cost_contract_helpers import get_current_ai_credit_price
from sections.cost_contract_sql import _build_cost_cockpit_sql, _build_cost_run_rate_sql
from sections.shell_helpers import with_loaded_at


pd = lazy_pandas()

build_clustering_cost_sql = _lazy_util("build_clustering_cost_sql")
build_cost_efficiency_summary_sql = _lazy_util("build_cost_efficiency_summary_sql")
build_cost_reconciliation_sql = _lazy_util("build_cost_reconciliation_sql")
build_mart_cost_cockpit_sql = _lazy_util("build_mart_cost_cockpit_sql")
build_mart_cost_run_rate_sql = _lazy_util("build_mart_cost_run_rate_sql")
build_warehouse_efficiency_sql = _lazy_util("build_warehouse_efficiency_sql")
format_snowflake_error = _lazy_util("format_snowflake_error")
load_action_queue = _lazy_util("load_action_queue")
load_shared_service_cost_lens = _lazy_util("load_shared_service_cost_lens")
run_query = _lazy_util("run_query")
run_query_or_raise = _lazy_util("run_query_or_raise")


def _refresh_cost_detail_state(
    state: MutableMapping,
    session,
    company: str,
    days: int,
    credit_price: float,
    *,
    run_query_func=None,
    run_query_or_raise_func=None,
    load_action_queue_func=None,
    service_lens_loader=None,
    mart_cockpit_sql_builder=None,
    live_cockpit_sql_builder=None,
    mart_run_rate_sql_builder=None,
    live_run_rate_sql_builder=None,
    reconciliation_sql_builder=None,
    service_cost_lens_loader=None,
    efficiency_summary_sql_builder=None,
    warehouse_efficiency_sql_builder=None,
    clustering_cost_sql_builder=None,
    snowflake_error_formatter=None,
    ai_credit_price_func=None,
    loaded_at_func=None,
) -> None:
    """Refresh explicit Cost & Contract detail state using the existing session-state contract."""
    run_query_func = run_query_func or run_query
    run_query_or_raise_func = run_query_or_raise_func or run_query_or_raise
    load_action_queue_func = load_action_queue_func or load_action_queue
    service_lens_loader = service_lens_loader or service_cost_lens_loader or load_shared_service_cost_lens
    mart_cockpit_sql_builder = mart_cockpit_sql_builder or build_mart_cost_cockpit_sql
    live_cockpit_sql_builder = live_cockpit_sql_builder or _build_cost_cockpit_sql
    mart_run_rate_sql_builder = mart_run_rate_sql_builder or build_mart_cost_run_rate_sql
    live_run_rate_sql_builder = live_run_rate_sql_builder or _build_cost_run_rate_sql
    reconciliation_sql_builder = reconciliation_sql_builder or build_cost_reconciliation_sql
    efficiency_summary_sql_builder = efficiency_summary_sql_builder or build_cost_efficiency_summary_sql
    warehouse_efficiency_sql_builder = warehouse_efficiency_sql_builder or build_warehouse_efficiency_sql
    clustering_cost_sql_builder = clustering_cost_sql_builder or build_clustering_cost_sql
    snowflake_error_formatter = snowflake_error_formatter or format_snowflake_error
    ai_credit_price_func = ai_credit_price_func or get_current_ai_credit_price
    loaded_at_func = loaded_at_func or with_loaded_at

    days = int(days)
    try:
        state["cost_contract_cockpit"] = run_query_func(
            mart_cockpit_sql_builder(company, days),
            ttl_key=f"cost_contract_cockpit_mart_{company}_{days}",
            tier="historical",
            section="Cost & Contract",
        )
        state["cost_contract_cockpit_source"] = "Fast warehouse cost summary"
        state["cost_contract_cockpit_meta"] = loaded_at_func(
            {"company": company, "days": days},
            source="Fast warehouse cost summary",
        )
        state["cost_contract_cockpit_error"] = ""
    except Exception as mart_exc:
        try:
            state["cost_contract_cockpit"] = run_query_func(
                live_cockpit_sql_builder(company, days),
                ttl_key=f"cost_contract_cockpit_{company}_{days}",
                tier="standard",
                section="Cost & Contract",
            )
            state["cost_contract_cockpit_source"] = (
                "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
            )
            state["cost_contract_cockpit_meta"] = loaded_at_func(
                {"company": company, "days": days},
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
            )
            state["cost_contract_cockpit_error"] = ""
        except Exception as exc:
            state["cost_contract_cockpit_error"] = (
                f"Fast summary unavailable: {snowflake_error_formatter(mart_exc)}; "
                f"live fallback failed: {snowflake_error_formatter(exc)}"
            )
            state["cost_contract_cockpit"] = pd.DataFrame()
            state["cost_contract_queue"] = pd.DataFrame()
    try:
        state["cost_contract_run_rate"] = run_query_func(
            mart_run_rate_sql_builder(company),
            ttl_key=f"cost_contract_run_rate_mart_{company}",
            tier="historical",
            section="Cost & Contract",
        )
        state["cost_contract_run_rate_source"] = "Fast run-rate summary"
        state["cost_contract_run_rate_error"] = ""
    except Exception as mart_exc:
        try:
            state["cost_contract_run_rate"] = run_query_func(
                live_run_rate_sql_builder(company),
                ttl_key=f"cost_contract_run_rate_live_{company}",
                tier="historical",
                section="Cost & Contract",
            )
            state["cost_contract_run_rate_source"] = (
                "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
            )
            state["cost_contract_run_rate_error"] = ""
        except Exception as exc:
            state["cost_contract_run_rate"] = pd.DataFrame()
            state["cost_contract_run_rate_source"] = ""
            state["cost_contract_run_rate_error"] = (
                f"Fast summary unavailable: {snowflake_error_formatter(mart_exc)}; "
                f"live fallback failed: {snowflake_error_formatter(exc)}"
            )
    try:
        state["cost_contract_queue"] = load_action_queue_func(session)
        state["cost_contract_queue_error"] = ""
    except Exception as exc:
        state["cost_contract_queue"] = pd.DataFrame()
        state["cost_contract_queue_error"] = snowflake_error_formatter(exc)
    try:
        state["cost_contract_attribution_reconciliation"] = run_query_or_raise_func(
            reconciliation_sql_builder(days, prefer_query_attribution=True),
            ttl_key=f"cost_contract_attribution_reconciliation_{company}_{days}",
            tier="historical",
            section="Cost & Contract",
        )
        state["cost_contract_attribution_error"] = ""
        state["cost_contract_attribution_source"] = (
            "SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY + WAREHOUSE_METERING_HISTORY"
        )
    except Exception as exc:
        state["cost_contract_attribution_reconciliation"] = pd.DataFrame()
        state["cost_contract_attribution_error"] = snowflake_error_formatter(exc)
        state["cost_contract_attribution_source"] = ""
    try:
        service_result = service_lens_loader(
            days,
            company,
            credit_price=credit_price,
            ai_credit_price=ai_credit_price_func(),
            force=True,
            section="Cost & Contract",
        )
        state["cost_contract_service_lens"] = service_result.data
        state["cost_contract_service_lens_error"] = service_result.message
        state["cost_contract_service_lens_source"] = service_result.source
    except Exception as exc:
        state["cost_contract_service_lens"] = pd.DataFrame()
        state["cost_contract_service_lens_error"] = snowflake_error_formatter(exc)
        state["cost_contract_service_lens_source"] = ""
    try:
        state["cost_contract_efficiency_summary"] = run_query_or_raise_func(
            efficiency_summary_sql_builder(
                days,
                company=company,
                credit_price=credit_price,
                prefer_query_attribution=True,
            ),
            ttl_key=f"cost_contract_efficiency_summary_{company}_{days}_{credit_price}",
            tier="historical",
            section="Cost & Contract",
        )
        state["cost_contract_efficiency_summary_error"] = ""
    except Exception as exc:
        state["cost_contract_efficiency_summary"] = pd.DataFrame()
        state["cost_contract_efficiency_summary_error"] = snowflake_error_formatter(exc)
    try:
        state["cost_contract_warehouse_efficiency"] = run_query_or_raise_func(
            warehouse_efficiency_sql_builder(
                days,
                company=company,
                credit_price=credit_price,
                top=50,
                prefer_query_attribution=True,
            ),
            ttl_key=f"cost_contract_warehouse_efficiency_{company}_{days}_{credit_price}",
            tier="historical",
            section="Cost & Contract",
        )
        state["cost_contract_warehouse_efficiency_error"] = ""
    except Exception as exc:
        state["cost_contract_warehouse_efficiency"] = pd.DataFrame()
        state["cost_contract_warehouse_efficiency_error"] = snowflake_error_formatter(exc)
    try:
        state["cost_contract_clustering_cost"] = run_query_or_raise_func(
            clustering_cost_sql_builder(
                days,
                company=company,
                credit_price=credit_price,
                top=50,
            ),
            ttl_key=f"cost_contract_clustering_cost_{company}_{days}_{credit_price}",
            tier="historical",
            section="Cost & Contract",
        )
        state["cost_contract_clustering_cost_error"] = ""
    except Exception as exc:
        state["cost_contract_clustering_cost"] = pd.DataFrame()
        state["cost_contract_clustering_cost_error"] = snowflake_error_formatter(exc)
