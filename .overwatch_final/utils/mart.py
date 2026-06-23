"""Helpers for reading the optional OVERWATCH Snowflake mart.

The app must keep working before the mart setup bundle is installed, so these
helpers always fail closed: callers get an empty frame plus a short reason and
can fall back to the existing live ACCOUNT_USAGE queries.
"""

from __future__ import annotations

import pandas as pd

from . import mart_account_health as _mart_account_health
from . import mart_adoption as _mart_adoption
from . import mart_contracts as _mart_contracts
from . import mart_control_room as _mart_control_room
from . import mart_cost as _mart_cost
from . import mart_filters as _mart_filters
from . import mart_names as _mart_names
from . import mart_recommendations as _mart_recommendations
from . import mart_service_health as _mart_service_health
from . import mart_storage_pipeline as _mart_storage_pipeline
from . import mart_task_procedure as _mart_task_procedure
from . import mart_usage as _mart_usage
from . import mart_warehouse as _mart_warehouse
from .mart_account_health import (
    build_mart_account_health_change_sql,
    build_mart_account_health_cost_drivers_sql,
    build_mart_account_health_credits_sql,
    build_mart_account_health_failure_count_sql,
    build_mart_account_health_failure_types_sql,
    build_mart_account_health_long_queries_sql,
    build_mart_account_health_queued_sql,
    build_mart_account_health_storage_sql,
    build_mart_account_health_top_driver_sql,
    build_mart_account_health_ytd_credits_sql,
)
from .mart_adoption import (
    build_mart_adoption_role_type_sql,
    build_mart_adoption_summary_sql,
    build_mart_adoption_trend_sql,
    build_mart_adoption_users_db_sql,
    build_mart_adoption_users_wh_sql,
    build_mart_adoption_warehouse_size_sql,
)
from .mart_contracts import MartResult, mart_source_caption
from .mart_control_room import (
    build_mart_control_room_cost_drivers_sql,
    build_mart_control_room_credits_sql,
    build_mart_control_room_failed_logins_sql,
    build_mart_control_room_failed_queries_sql,
    build_mart_control_room_object_changes_sql,
    build_mart_control_room_summary_sql,
    build_mart_control_room_task_failures_sql,
    build_mart_control_room_warehouse_pressure_sql,
)
from .mart_cost import (
    build_mart_bill_summary_sql,
    build_mart_bill_warehouse_delta_sql,
    build_mart_chargeback_sql,
    build_mart_cost_cockpit_sql,
    build_mart_cost_explorer_sql,
    build_mart_cost_run_rate_sql,
    build_mart_cost_service_lens_sql,
)
from .mart_filters import (
    _active_environment,
    _mart_company_filter,
    _mart_database_filter,
    _mart_environment_column,
    _mart_environment_filter,
    _mart_text_filter,
    _mart_window_condition,
    _mart_window_filter,
)
from .mart_names import mart_object_name
from .mart_recommendations import (
    build_mart_query_bottleneck_sql,
    build_mart_query_degradation_sql,
    build_mart_recommendation_failed_tasks_sql,
    build_mart_recommendation_idle_sql,
    build_mart_recommendation_query_errors_sql,
    build_mart_recommendation_spill_sql,
)
from .mart_service_health import (
    build_mart_service_login_health_sql,
    build_mart_service_query_health_sql,
    build_mart_service_task_health_sql,
    build_mart_service_warehouse_health_sql,
)
from .mart_storage_pipeline import (
    build_mart_pipeline_freshness_sql,
    build_mart_pipeline_load_failures_sql,
    build_mart_pipeline_volume_sql,
    build_mart_storage_db_detail_sql,
    build_mart_storage_trend_sql,
)
from .mart_task_procedure import (
    build_mart_procedure_calls_sql,
    build_mart_procedure_inventory_sql,
    build_mart_procedure_sla_sql,
    build_mart_query_detail_recent_sql,
    build_mart_task_critical_path_sql,
    build_mart_task_history_sql,
    build_mart_task_inventory_sql,
)
from .mart_usage import (
    build_mart_usage_cost_drivers_sql,
    build_mart_usage_database_adoption_sql,
    build_mart_usage_metering_sql,
    build_mart_usage_overview_sql,
    build_mart_usage_pressure_sql,
    build_mart_usage_query_mix_sql,
    build_mart_usage_storage_sql,
)
from .mart_warehouse import (
    build_mart_warehouse_heatmap_sql,
    build_mart_warehouse_overview_sql,
    build_mart_warehouse_scaling_sql,
)
from .query import run_query, sql_literal

__all__ = [
    *_mart_contracts.__all__,
    *_mart_names.__all__,
    *_mart_filters.__all__,
    *_mart_control_room.__all__,
    *_mart_account_health.__all__,
    *_mart_service_health.__all__,
    *_mart_task_procedure.__all__,
    *_mart_cost.__all__,
    *_mart_warehouse.__all__,
    *_mart_usage.__all__,
    *_mart_adoption.__all__,
    *_mart_storage_pipeline.__all__,
    *_mart_recommendations.__all__,
    "load_mart_table",
    "load_latest_control_room_mart",
]


def load_mart_table(
    table_name: str,
    sql: str,
    source_label: str | None = None,
) -> MartResult:
    """Run a mart query and return a fallback-friendly result object."""
    source = source_label or mart_object_name(table_name)
    try:
        df = run_query(
            sql,
            ttl_key=f"mart_{str(table_name).lower()}",
            tier="historical",
            section="Mart",
        )
        if df.empty:
            return MartResult(data=df, available=False, source=source, message="No summary rows returned.")
        return MartResult(data=df, available=True, source=source)
    except Exception as exc:
        return MartResult(data=pd.DataFrame(), available=False, source=source, message=str(exc))


def load_latest_control_room_mart(company: str = "ALFA", max_age_hours: int = 6) -> MartResult:
    """Load the latest DBA Control Room mart row for the active company."""
    table = mart_object_name("MART_DBA_CONTROL_ROOM")
    company = str(company or "ALFA")
    company_filter = ""
    if company.upper() != "ALL":
        company_filter = f"AND COMPANY = {sql_literal(company, 100)}"
    sql = f"""
        WITH latest AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY COMPANY
                       ORDER BY SNAPSHOT_TS DESC
                   ) AS RN
            FROM {table}
            WHERE SNAPSHOT_TS >= DATEADD('HOUR', -{int(max_age_hours)}, CURRENT_TIMESTAMP())
              {company_filter}
        )
        SELECT
            SNAPSHOT_TS,
            COMPANY,
            HEALTH_SCORE,
            FAILED_QUERIES_24H,
            FAILED_TASKS_24H,
            QUEUED_MS_24H,
            CREDITS_24H,
            COST_24H_USD,
            CORTEX_COST_7D_USD,
            SECURITY_EVENTS_24H,
            OBJECT_CHANGES_24H,
            TOP_RISK,
            LOAD_TS
        FROM latest
        WHERE RN = 1
        ORDER BY COMPANY
    """
    return load_mart_table("MART_DBA_CONTROL_ROOM", sql, source_label=table)
