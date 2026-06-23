"""Cost Center Explain This Bill renderer."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from sections.cost_center_action_queue import _queue_bill_exceptions, _queue_cost_outliers
from sections.cost_center_contracts import COST_EXPLORER_LENSES, NO_DATABASE_CONTEXT_VALUES
from sections.cost_center_models import (
    _annotate_allocation_quality,
    _annotate_cost_routes,
    _annual_service_projection_metrics,
    _bill_driver_summary,
    _bill_period_bounds,
    _build_bill_waterfall,
    _build_explain_bill_markdown,
    _build_finance_movement_summary,
    _cost_explorer_gap_board,
    _cost_explorer_summary,
    _first_value,
    _fmt_delta,
    _normalize_cost_explorer_detail,
    _pct_delta,
    _prepare_cost_forecast_rows,
    _service_cost_category,
)
from sections.cost_center_sql import (
    _annual_service_projection_sql,
    _cost_explorer_live_sql,
    _snowflake_admin_reconciliation_sql,
)
from sections.shell_helpers import render_escaped_bold_text, render_shell_snapshot
from utils import (
    build_cost_reconciliation_sql,
    build_mart_chargeback_sql,
    build_mart_cost_explorer_sql,
    build_metered_credit_cte,
    burn_trend_label,
    credits_to_dollars,
    day_window_selectbox,
    defer_source_note,
    download_csv,
    format_credits,
    format_snowflake_error,
    freshness_note,
    get_active_environment,
    get_company_case_expr,
    get_environment_case_expr,
    get_global_filter_clause,
    load_mart_table,
    load_shared_bill_metering_summary,
    load_shared_bill_warehouse_delta,
    load_shared_warehouse_daily_credits,
    load_shared_warehouse_daily_credits_by_warehouse,
    mart_source_caption,
    metric_confidence_label,
    query_attribution_supported,
    render_chart_with_data_toggle,
    render_drillable_bar_chart,
    render_entity_query_drilldown,
    render_priority_dataframe,
    render_ranked_bar_chart,
    run_query,
    safe_float,
    safe_int,
)


def render_explain_this_bill(session, company: str, credit_price: float, max_wh_size_expr: str, bytes_scanned_sum_expr: str, query_tag_dimension_expr: str) -> None:
    st.subheader("Explain This Bill")
    st.caption("Start here when someone asks why Snowflake spend moved.")
    defer_source_note(
        "Warehouse totals use exact ACCOUNT_USAGE metering; user and query drivers are allocated estimates."
    )
    explain_period = st.selectbox(
        "Bill period",
        [
            "Last complete day",
            "Last 7 complete days",
            "Last 30 complete days",
            "Current month to date",
            "Previous month",
        ],
        index=1,
        key="cc_explain_period",
    )
    bounds = _bill_period_bounds(explain_period)
    use_mart_summary = not any([
        st.session_state.get("global_user"),
        st.session_state.get("global_role"),
        st.session_state.get("global_database"),
        st.session_state.get("global_schema"),
    ])
    warehouse_contains = str(st.session_state.get("global_warehouse") or "").strip()
    wh_filter_query = get_global_filter_clause(
        "",
        "q.warehouse_name",
        "q.user_name",
        "q.role_name",
        "q.database_name",
        "q.schema_name",
    )
    attribution_only_filters = [
        name for name, value in {
            "user": st.session_state.get("global_user"),
            "role": st.session_state.get("global_role"),
            "database": st.session_state.get("global_database"),
            "schema": st.session_state.get("global_schema"),
        }.items()
        if value
    ]
    if attribution_only_filters:
        st.warning(
            "User, role, database, and schema filters narrow attribution rows only. "
            "Exact warehouse metering can be scoped only by company and warehouse."
        )
    explain_filter_signature = (
        st.session_state.get("global_warehouse"),
        st.session_state.get("global_user"),
        st.session_state.get("global_role"),
        st.session_state.get("global_database"),
        st.session_state.get("global_schema"),
    )

    if st.button("Explain Bill", key="cc_explain_load", type="primary"):
        try:
            summary_result = load_shared_bill_metering_summary(
                bounds["current_start"],
                bounds["current_end"],
                bounds["prior_start"],
                bounds["prior_end"],
                company,
                warehouse_contains=warehouse_contains,
                prefer_mart=use_mart_summary,
                force=True,
                section="Cost & Contract",
            )
            wh_delta_result = load_shared_bill_warehouse_delta(
                bounds["current_start"],
                bounds["current_end"],
                bounds["prior_start"],
                bounds["prior_end"],
                company,
                warehouse_contains=warehouse_contains,
                prefer_mart=use_mart_summary,
                force=True,
                section="Cost & Contract",
            )
            driver_sql = f"""
            WITH bounds AS (
                SELECT
                    {bounds['current_start']} AS current_start,
                    {bounds['current_end']} AS current_end
            ),
            {build_metered_credit_cte(days_back=bounds['days_back'], include_recent=False)}
            SELECT
                q.user_name,
                q.role_name,
                q.warehouse_name,
                {max_wh_size_expr} AS warehouse_size,
                COUNT(*) AS query_count,
                ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS total_credits,
                ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS allocated_credits,
                ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_execution_seconds,
                ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
                ROUND({bytes_scanned_sum_expr} / POWER(1024, 3), 2) AS gb_scanned
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
            CROSS JOIN bounds
            WHERE q.start_time >= current_start
              AND q.start_time < current_end
              AND q.warehouse_name IS NOT NULL
              {wh_filter_query}
            GROUP BY q.user_name, q.role_name, q.warehouse_name
            ORDER BY allocated_credits DESC
            LIMIT 50
            """
            type_sql = f"""
            WITH bounds AS (
                SELECT
                    {bounds['current_start']} AS current_start,
                    {bounds['current_end']} AS current_end
            ),
            {build_metered_credit_cte(days_back=bounds['days_back'], include_recent=False)}
            SELECT
                COALESCE(q.query_type, 'UNKNOWN') AS query_type,
                COUNT(*) AS query_count,
                ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS total_credits,
                ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS allocated_credits,
                ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_execution_seconds,
                ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
                ROUND({bytes_scanned_sum_expr} / POWER(1024, 3), 2) AS gb_scanned
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
            CROSS JOIN bounds
            WHERE q.start_time >= current_start
              AND q.start_time < current_end
              AND q.warehouse_name IS NOT NULL
              {wh_filter_query}
            GROUP BY COALESCE(q.query_type, 'UNKNOWN')
            ORDER BY allocated_credits DESC
            LIMIT 25
            """
            environment_sql = f"""
            WITH bounds AS (
                SELECT
                    {bounds['current_start']} AS current_start,
                    {bounds['current_end']} AS current_end
            ),
            {build_metered_credit_cte(days_back=bounds['days_back'], include_recent=False)}
            SELECT
                {get_environment_case_expr("q.database_name")} AS environment,
                COALESCE(q.database_name, 'NO_DATABASE_CONTEXT') AS database_name,
                COUNT(*) AS query_count,
                COUNT(DISTINCT q.user_name) AS users,
                COUNT(DISTINCT q.warehouse_name) AS warehouses,
                ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS allocated_credits,
                ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
                ROUND({bytes_scanned_sum_expr} / POWER(1024, 3), 2) AS gb_scanned
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
            CROSS JOIN bounds
            WHERE q.start_time >= current_start
              AND q.start_time < current_end
              AND q.warehouse_name IS NOT NULL
              AND q.database_name IS NOT NULL
              {wh_filter_query}
            GROUP BY 1, 2
            ORDER BY allocated_credits DESC
            LIMIT 100
            """
            service_sql = f"""
            WITH bounds AS (
                SELECT
                    {bounds['current_start']} AS current_start,
                    {bounds['current_end']} AS current_end,
                    {bounds['prior_start']} AS prior_start,
                    {bounds['prior_end']} AS prior_end
            ),
            metering AS (
                SELECT 'CURRENT' AS period, service_type, start_time, credits_used
                FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY, bounds
                WHERE start_time >= current_start
                  AND start_time < current_end
                UNION ALL
                SELECT 'PRIOR' AS period, service_type, start_time, credits_used
                FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY, bounds
                WHERE start_time >= prior_start
                  AND start_time < prior_end
            )
            SELECT
                period,
                COALESCE(service_type, 'UNKNOWN') AS service_type,
                ROUND(SUM(COALESCE(credits_used, 0)), 4) AS credits
            FROM metering
            GROUP BY period, COALESCE(service_type, 'UNKNOWN')
            ORDER BY period, credits DESC
            """
            st.session_state["cc_explain_summary"] = summary_result.data
            st.session_state["cc_explain_wh_delta"] = wh_delta_result.data
            st.session_state["cc_explain_drivers"] = run_query(
                driver_sql,
                ttl_key=f"cc_explain_drivers_{company}_{explain_period}",
                tier="standard",
            )
            st.session_state["cc_explain_types"] = run_query(
                type_sql,
                ttl_key=f"cc_explain_types_{company}_{explain_period}",
                tier="standard",
            )
            st.session_state["cc_explain_environments"] = run_query(
                environment_sql,
                ttl_key=(
                    f"cc_explain_env_{company}_{explain_period}_"
                    f"{get_active_environment()}_{st.session_state.get('global_database', '')}"
                ),
                tier="standard",
            )
            try:
                st.session_state["cc_explain_services"] = run_query(
                    service_sql,
                    ttl_key=f"cc_explain_services_{explain_period}",
                    tier="standard",
                )
                st.session_state["cc_explain_service_error"] = ""
            except Exception as service_error:
                st.session_state["cc_explain_services"] = pd.DataFrame()
                st.session_state["cc_explain_service_error"] = format_snowflake_error(service_error)
            st.session_state["cc_explain_meta"] = {
                "company": company,
                "period": explain_period,
                "credit_price": credit_price,
                "filters": explain_filter_signature,
                "summary_source": summary_result.source,
                "warehouse_delta_source": wh_delta_result.source,
            }
        except Exception as e:
            st.error(f"Unable to explain bill: {format_snowflake_error(e)}")

    summary = st.session_state.get("cc_explain_summary")
    wh_deltas = st.session_state.get("cc_explain_wh_delta")
    drivers = st.session_state.get("cc_explain_drivers")
    type_drivers = st.session_state.get("cc_explain_types")
    environment_drivers = st.session_state.get("cc_explain_environments")
    service_drivers = st.session_state.get("cc_explain_services")
    service_error = st.session_state.get("cc_explain_service_error", "")
    explain_meta = st.session_state.get("cc_explain_meta", {})
    has_current_explain = (
        explain_meta.get("company") == company
        and explain_meta.get("period") == explain_period
        and explain_meta.get("filters") == explain_filter_signature
        and summary is not None
        and not summary.empty
    )
    if has_current_explain:
        current_row = summary[summary["PERIOD"] == "CURRENT"]
        prior_row = summary[summary["PERIOD"] == "PRIOR"]
        current_credits = safe_float(_first_value(current_row, "CREDITS", 0))
        prior_credits = safe_float(_first_value(prior_row, "CREDITS", 0))
        current_cost = credits_to_dollars(current_credits, credit_price)
        prior_cost = credits_to_dollars(prior_credits, credit_price)
        delta_credits = current_credits - prior_credits
        delta_cost = current_cost - prior_cost
        delta_pct = _pct_delta(current_credits, prior_credits)
        active_warehouses = int(_first_value(current_row, "ACTIVE_WAREHOUSES", 0) or 0)
        allocated_credits = (
            safe_float(drivers["ALLOCATED_CREDITS"].sum())
            if drivers is not None and not drivers.empty else 0.0
        )
        unallocated_credits = max(0.0, current_credits - allocated_credits)
        unallocated_pct = (unallocated_credits / current_credits * 100) if current_credits else 0.0

        bill_metrics = [
            ("Current Spend", f"${current_cost:,.2f} ({delta_cost:+,.2f})"),
            ("Current Credits", f"{format_credits(current_credits)} ({delta_credits:+,.2f})"),
            ("Change vs Baseline", _fmt_delta(delta_pct)),
            ("Active Warehouses", f"{active_warehouses:,}"),
        ]
        render_shell_snapshot(tuple(bill_metrics))

        defer_source_note(
            f"{metric_confidence_label('exact')} for warehouse totals | "
            f"{metric_confidence_label('allocated')} for user/query attribution | "
            f"{explain_meta.get('summary_source', 'Live fallback: WAREHOUSE_METERING_HISTORY')} | "
            f"{freshness_note('ACCOUNT_USAGE')}"
        )

        if delta_credits > 0:
            st.warning(
                f"Spend increased by {delta_credits:,.2f} credits "
                f"(${delta_cost:,.2f}) compared with the prior comparable period."
            )
        elif delta_credits < 0:
            st.success(
                f"Spend decreased by {abs(delta_credits):,.2f} credits "
                f"(${abs(delta_cost):,.2f}) compared with the prior comparable period."
            )
        else:
            st.info("Spend held flat versus the prior comparable period.")

        gap_level = "material" if unallocated_pct >= 20 else "moderate" if unallocated_pct >= 10 else "low"
        st.info(
            f"Unallocated / idle / service-overhead gap is {unallocated_credits:,.2f} credits "
            f"({unallocated_pct:.1f}% of exact warehouse credits), which is {gap_level}."
        )
        if service_error:
            st.warning(f"Account-wide service credits were unavailable: {service_error}")

        finance_summary = _build_finance_movement_summary(
            current_credits=current_credits,
            prior_credits=prior_credits,
            allocated_credits=allocated_credits,
            unallocated_credits=unallocated_credits,
            service_drivers=service_drivers,
            credit_price=credit_price,
        )
        st.subheader("Finance Movement Summary")
        defer_source_note(
            "This bridge separates exact warehouse compute, allocated workload, estimated overhead, "
            "and account-wide service/serverless credits. It is designed for bill review and executive talking points."
        )
        render_priority_dataframe(
            finance_summary,
            title="Finance movement bridge",
            priority_columns=[
                "Category", "Current Credits", "Prior Credits", "Delta Credits",
                "Current Cost", "Delta Cost", "Measurement Basis", "Basis", "Action",
            ],
            sort_by=["Current Credits", "Delta Credits"],
            ascending=False,
            raw_label="All finance movement rows",
        )

        narrative = _bill_driver_summary(
            delta_credits=delta_credits,
            current_credits=current_credits,
            prior_credits=prior_credits,
            unallocated_pct=unallocated_pct,
            warehouse_deltas=wh_deltas,
            user_drivers=drivers,
            query_type_drivers=type_drivers,
        )
        st.subheader("Bill Narrative")
        n1, n2 = st.columns([1, 3])
        with n1:
            render_shell_snapshot((("Review Status", narrative["severity"]),))
        with n2:
            render_escaped_bold_text(narrative["headline"])
            st.write(narrative["reason"])
            st.caption(narrative["caveat"])
            st.info(narrative["next_action"])

        waterfall = _build_bill_waterfall(
            wh_deltas,
            prior_credits=prior_credits,
            current_credits=current_credits,
            credit_price=credit_price,
        )
        defer_source_note(
            "Positive bars increased the bill; negative bars reduced it. "
            "Baseline and current total are exact warehouse-metering totals."
        )
        render_chart_with_data_toggle(
            "Bill Movement Waterfall",
            "cc_bill_movement_waterfall",
            lambda: st.bar_chart(waterfall, x="Driver", y="Credits", color="Type"),
            waterfall,
            priority_columns=["Driver", "Credits", "Estimated Cost", "Type"],
            sort_by=["Credits"],
            ascending=False,
            raw_label="All usage movement rows",
        )

        if st.session_state.get("exceptions_only_mode"):
            st.subheader("Exceptions Only")
            if wh_deltas is not None and not wh_deltas.empty:
                exception_rows = wh_deltas[
                    (wh_deltas["CREDIT_DELTA"].fillna(0) > 0)
                    | (wh_deltas["PCT_DELTA"].fillna(0).abs() >= 25)
                ].copy()
                if exception_rows.empty:
                    st.success("No warehouse bill exceptions crossed the default thresholds.")
                else:
                    exception_rows = _annotate_cost_routes(exception_rows, "Warehouse Delta")
                    exception_rows["EST_DELTA_COST"] = exception_rows["CREDIT_DELTA"].apply(
                        lambda v: credits_to_dollars(v, credit_price)
                    )
                    render_priority_dataframe(
                        exception_rows,
                        title="Bill exceptions to explain first",
                        priority_columns=[
                            "WAREHOUSE_NAME", "CURRENT_CREDITS", "PRIOR_CREDITS",
                            "CREDIT_DELTA", "PCT_DELTA", "EST_DELTA_COST",
                            "NEXT_WORKFLOW", "NEXT_ACTION",
                        ],
                        sort_by=["CREDIT_DELTA", "PCT_DELTA"],
                        ascending=[False, False],
                        raw_label="All bill exception rows",
                    )
            else:
                st.info("No warehouse delta rows available.")
            st.stop()

        wh_delta_view = _annotate_cost_routes(wh_deltas, "Warehouse Delta")
        render_chart_with_data_toggle(
            "Warehouse cost movement to explain first",
            "cc_explain_wh_delta",
            lambda: render_drillable_bar_chart(
                wh_deltas.sort_values("CREDIT_DELTA", ascending=False).head(15)
                if wh_deltas is not None and not wh_deltas.empty else wh_deltas,
                dimension="WAREHOUSE_NAME",
                measure="CREDIT_DELTA",
                key="cc_explain_wh_delta_chart",
                drilldown_column="warehouse_name",
                lookback_hours=bounds["days_back"] * 24,
            ),
            wh_delta_view,
            priority_columns=[
                "WAREHOUSE_NAME", "CURRENT_CREDITS", "PRIOR_CREDITS",
                "CREDIT_DELTA", "PCT_DELTA", "NEXT_WORKFLOW", "NEXT_ACTION",
            ],
            sort_by=["CREDIT_DELTA", "PCT_DELTA"],
            ascending=[False, False],
            raw_label="All warehouse delta rows",
        )

        st.subheader("Top User / Warehouse Drivers")
        render_priority_dataframe(
            _annotate_cost_routes(drivers, "User Cost"),
            title="User and warehouse spend drivers",
            priority_columns=[
                "USER_NAME", "WAREHOUSE_NAME", "TOTAL_CREDITS", "QUERY_COUNT",
                "AVG_EXECUTION_SECONDS", "NEXT_WORKFLOW", "NEXT_ACTION",
            ],
            sort_by=["TOTAL_CREDITS", "QUERY_COUNT"],
            ascending=[False, False],
            raw_label="All user/warehouse driver rows",
        )

        st.subheader("Top Query-Type Drivers")
        render_priority_dataframe(
            _annotate_cost_routes(type_drivers, "Query Type Cost"),
            title="Query-type spend drivers",
            priority_columns=[
                "QUERY_TYPE", "TOTAL_CREDITS", "QUERY_COUNT",
                "AVG_EXECUTION_SECONDS", "NEXT_WORKFLOW", "NEXT_ACTION",
            ],
            sort_by=["TOTAL_CREDITS", "QUERY_COUNT"],
            ascending=[False, False],
            raw_label="All query-type driver rows",
        )

        st.subheader("PROD vs DEV Cost Split")
        defer_source_note(
            f"{metric_confidence_label('allocated')} | Shared warehouses mean exact WAREHOUSE_METERING_HISTORY "
            "cannot split PROD and DEV by itself. This view allocates metered credits to query database context, "
            "then rolls ALFA_EDW_PROD separately from ALFA_EDW_DEV/SAN/PHX/SEA/SIT."
        )
        if environment_drivers is not None and not environment_drivers.empty:
            env_display = _annotate_allocation_quality(environment_drivers)
            env_display["EST_COST"] = env_display["ALLOCATED_CREDITS"].apply(
                lambda x: credits_to_dollars(x, credit_price)
            )
            env_summary = (
                env_display.groupby(
                    ["ENVIRONMENT_ROLLUP", "ALLOCATION_CONFIDENCE", "CHARGEBACK_READY"],
                    as_index=False,
                )[
                    ["ALLOCATED_CREDITS", "EST_COST", "QUERY_COUNT", "USERS", "WAREHOUSES", "GB_SCANNED"]
                ]
                .sum()
                .sort_values("EST_COST", ascending=False)
            )
            render_shell_snapshot(tuple(
                (
                    str(row["ENVIRONMENT_ROLLUP"]),
                    f"${safe_float(row['EST_COST']):,.2f} ({safe_float(row['ALLOCATED_CREDITS']):,.2f} cr)",
                )
                for _, row in env_summary.head(4).iterrows()
            ))
            render_priority_dataframe(
                env_summary,
                title="Environment cost rollup",
                priority_columns=[
                    "ENVIRONMENT_ROLLUP", "ALLOCATION_CONFIDENCE", "CHARGEBACK_READY",
                    "ALLOCATED_CREDITS", "EST_COST", "QUERY_COUNT", "USERS", "WAREHOUSES", "GB_SCANNED",
                ],
                sort_by=["EST_COST", "ALLOCATED_CREDITS"],
                ascending=[False, False],
                raw_label="All environment rollup rows",
            )
            dev_detail = env_display[env_display["ENVIRONMENT_ROLLUP"] == "DEV_ALL"]
            if not dev_detail.empty:
                render_priority_dataframe(
                    dev_detail,
                    title="Individual DEV database cost",
                    priority_columns=[
                        "ENVIRONMENT", "DATABASE_NAME", "ALLOCATED_CREDITS", "EST_COST",
                        "QUERY_COUNT", "USERS", "WAREHOUSES", "ALLOCATION_CONFIDENCE", "GB_SCANNED",
                    ],
                    sort_by=["EST_COST", "ALLOCATED_CREDITS"],
                    ascending=[False, False],
                    raw_label="All individual DEV database rows",
                )
            render_priority_dataframe(
                env_display,
                title="Environment cost by database",
                priority_columns=[
                    "ENVIRONMENT_ROLLUP", "ENVIRONMENT", "DATABASE_NAME",
                    "ALLOCATION_CONFIDENCE", "CHARGEBACK_READY", "SCOPE_REVIEW",
                    "ALLOCATED_CREDITS", "EST_COST", "QUERY_COUNT", "USERS",
                    "WAREHOUSES", "AVG_ELAPSED_SEC", "GB_SCANNED",
                ],
                sort_by=["EST_COST", "ALLOCATED_CREDITS"],
                ascending=[False, False],
                raw_label="All environment/database rows",
            )
        else:
            st.info(
                "No database-scoped query cost was available for this period. "
                "Try a wider period or clear the database/environment filter."
            )

        st.subheader("Account-Wide Service / Serverless Contributors")
        defer_source_note(
            f"{metric_confidence_label('account-wide')} | "
            "METERING_HISTORY service credits are not company-scoped by warehouse. "
            "Use tags, ownership standards, or service-specific lineage before chargeback."
        )
        if service_drivers is not None and not service_drivers.empty:
            service_display = service_drivers.copy()
            service_display["CATEGORY"] = service_display["SERVICE_TYPE"].apply(_service_cost_category)
            service_display = _annotate_cost_routes(service_display, "Service Cost")
            render_priority_dataframe(
                service_display,
                title="Service and serverless contributors",
                priority_columns=[
                    "SERVICE_TYPE", "CATEGORY", "CREDITS_USED", "EST_COST",
                    "NEXT_WORKFLOW", "NEXT_ACTION",
                ],
                sort_by=["CREDITS_USED"],
                ascending=False,
                raw_label="All service contributor rows",
            )
        else:
            st.info("No service/serverless contributor rows were available for this period.")

        report_md = _build_explain_bill_markdown(
            company=company,
            period_label=bounds["label"],
            current_credits=current_credits,
            prior_credits=prior_credits,
            credit_price=credit_price,
            active_warehouses=active_warehouses,
            allocated_credits=allocated_credits,
            unallocated_credits=unallocated_credits,
            warehouse_deltas=wh_deltas,
            user_drivers=drivers,
            query_type_drivers=type_drivers,
            service_drivers=service_drivers,
        )
        st.download_button(
            "Download Bill Explanation",
            report_md,
            file_name=f"overwatch_bill_explanation_{company.lower()}.md",
            mime="text/markdown",
            key="cc_explain_download",
        )
        if st.button("Save Bill Exceptions to Action Queue", key="cc_explain_queue"):
            _queue_bill_exceptions(session, wh_deltas, credit_price, bounds["label"])


__all__ = [
    "render_explain_this_bill",
]
