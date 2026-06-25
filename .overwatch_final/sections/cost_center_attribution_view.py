"""Cost Center Attribution renderer."""
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
from sections.chart_helpers import render_ranked_bar_chart
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
    run_query,
    safe_float,
    safe_int,
)


def render_cost_attribution(session, company: str, credit_price: float, max_wh_size_expr: str, bytes_scanned_sum_expr: str, query_tag_dimension_expr: str) -> None:
    st.subheader("Cost Attribution")
    attr_days = day_window_selectbox("Lookback", key="cc_attr_days", default=30)
    attr_mode = st.selectbox(
        "Attribution dimension",
        ["Role", "Database / Schema", "Application / Client", "Stored Procedure / Task Lineage"],
        key="cc_attr_mode",
    )
    gf = get_global_filter_clause(
        "q.start_time", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name"
    )

    if st.button("Load Attribution", key="cc_attr_load"):
        if attr_mode == "Role":
            select_cols = "COALESCE(q.role_name, 'UNKNOWN') AS dimension"
            group_cols  = "COALESCE(q.role_name, 'UNKNOWN')"
        elif attr_mode == "Database / Schema":
            select_cols = "COALESCE(q.database_name,'UNKNOWN')||'.'||COALESCE(q.schema_name,'UNKNOWN') AS dimension"
            group_cols  = "COALESCE(q.database_name,'UNKNOWN')||'.'||COALESCE(q.schema_name,'UNKNOWN')"
        elif attr_mode == "Application / Client":
            select_cols = f"{query_tag_dimension_expr} AS dimension"
            group_cols  = query_tag_dimension_expr
        else:
            select_cols = "COALESCE(REGEXP_SUBSTR(q.query_text,'CALL\\\\s+([^\\\\(]+)',1,1,'i',1), q.query_type, 'ADHOC') AS dimension"
            group_cols  = "COALESCE(REGEXP_SUBSTR(q.query_text,'CALL\\\\s+([^\\\\(]+)',1,1,'i',1), q.query_type, 'ADHOC')"

        try:
            df_attr = run_query(f"""
            WITH {build_metered_credit_cte(days_back=attr_days)}
            SELECT {select_cols},
                   COUNT(*) AS query_count,
                   COUNT(DISTINCT q.user_name)      AS users,
                   COUNT(DISTINCT q.warehouse_name) AS warehouses,
                   ROUND(SUM(COALESCE(pqc.metered_credits,0)),4) AS total_credits,
                   ROUND({bytes_scanned_sum_expr}/POWER(1024,3),2)   AS gb_scanned
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
            WHERE q.start_time >= DATEADD('day', -{attr_days}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {gf}
            GROUP BY {group_cols}
            ORDER BY total_credits DESC
            LIMIT 200
            """, ttl_key=f"cc_attr_{company}_{attr_mode}_{attr_days}", tier="standard")
            st.session_state["df_cc_attr"] = df_attr
        except Exception as e:
            st.warning(f"Attribution data unavailable in this role/context: {format_snowflake_error(e)}")

    if st.session_state.get("df_cc_attr") is not None and not st.session_state["df_cc_attr"].empty:
        df_attr = st.session_state["df_cc_attr"]
        df_attr["EST_COST"] = df_attr["TOTAL_CREDITS"].apply(lambda x: credits_to_dollars(x, credit_price))
        render_priority_dataframe(
            df_attr,
            title=f"{attr_mode} cost attribution drivers",
            priority_columns=[
                "DIMENSION",
                "TOTAL_CREDITS",
                "EST_COST",
                "QUERY_COUNT",
                "USERS",
                "WAREHOUSES",
                "GB_SCANNED",
            ],
            sort_by=["TOTAL_CREDITS", "EST_COST", "QUERY_COUNT"],
            ascending=[False, False, False],
            raw_label="All attribution rows",
        )
        dim_col = (
            "role_name" if attr_mode == "Role" else
            "database_schema" if attr_mode == "Database / Schema" else
            "application_client" if attr_mode == "Application / Client" else
            "lineage_dimension"
        )
        render_drillable_bar_chart(
            df_attr, dimension="DIMENSION", measure="EST_COST",
            key="cc_attr_cost", title="Attribution drill-down",
            drilldown_column=dim_col, lookback_hours=attr_days * 24,
        )
        download_csv(df_attr, "cost_attribution.csv")


__all__ = [
    "render_cost_attribution",
]
