"""Compatibility facade for shared metric dataset loaders.

Keep ``utils.shared_metrics`` as the stable public import surface while the
workflow-specific implementations live in focused ``shared_metrics_*`` modules.
"""

from __future__ import annotations

from .shared_metrics_cache import (
    _company_column_filter,
    _empty_result,
    _get_cached_result,
    _global_filter_values,
    _load_or_reuse,
    _shared_state_key,
    _store_result,
)
from .shared_metrics_contracts import LIVE_STORAGE_FALLBACK_MAX_DAYS, SharedMetricResult
from .shared_metrics_procedures import (
    load_shared_procedure_calls,
    load_shared_procedure_inventory,
    load_shared_procedure_sla,
)
from .shared_metrics_query import (
    _query_history_rollup_exprs,
    load_shared_query_history_rollup,
    load_shared_warehouse_pressure_summary,
)
from .shared_metrics_recommendations import (
    load_shared_duplicate_query_patterns,
    load_shared_recommendation_clustering_cost,
    load_shared_recommendation_failed_tasks,
    load_shared_recommendation_idle_warehouses,
    load_shared_recommendation_query_failures,
    load_shared_recommendation_repeated_queries,
    load_shared_recommendation_spill_warehouses,
    load_shared_recommendation_storage_retention,
)
from .shared_metrics_security import (
    _shared_security_user_columns,
    _shared_user_exprs,
    _shared_user_exprs_from_columns,
    build_shared_access_hygiene_sql,
    build_shared_security_mart_brief_sql,
    build_shared_security_privileged_grant_review_sql,
    build_shared_security_summary_sql,
    load_shared_access_hygiene_snapshot,
    load_shared_grants_to_users,
    load_shared_mfa_coverage,
    shared_mfa_count_expr,
    shared_mfa_gap_predicate,
    shared_mfa_proof_label,
)
from .shared_metrics_service_cost import (
    load_shared_service_cost_lens,
    load_shared_service_cost_trend,
)
from .shared_metrics_billing import load_shared_account_billing_reconciliation
from .shared_metrics_service_health import (
    _first_numeric_value,
    _service_query_history_exprs,
    load_shared_service_login_health,
    load_shared_service_pipe_health,
    load_shared_service_query_health,
    load_shared_service_task_health,
    load_shared_service_warehouse_health,
)
from .shared_metrics_storage import (
    _storage_summary_from_trend,
    load_shared_storage_db_detail,
    load_shared_storage_trend,
    load_shared_usage_storage_kpis,
)
from .shared_metrics_tasks import (
    load_shared_task_health_summary,
    load_shared_task_history_detail,
)
from .shared_metrics_usage import (
    build_shared_bill_metering_summary_live_sql,
    build_shared_bill_warehouse_delta_live_sql,
    load_shared_bill_metering_summary,
    load_shared_bill_warehouse_delta,
    load_shared_usage_metering_kpis,
)
from .shared_metrics_warehouse import (
    _warehouse_health_exprs,
    load_shared_warehouse_credit_anomalies,
    load_shared_warehouse_daily_credits,
    load_shared_warehouse_daily_credits_by_warehouse,
    load_shared_warehouse_efficiency,
    load_shared_warehouse_heatmap,
    load_shared_warehouse_overview,
    load_shared_warehouse_right_sizing,
    load_shared_warehouse_scaling_events,
    load_shared_warehouse_spill,
)

__all__ = (
    "LIVE_STORAGE_FALLBACK_MAX_DAYS",
    "SharedMetricResult",
    "_company_column_filter",
    "_empty_result",
    "_first_numeric_value",
    "_get_cached_result",
    "_global_filter_values",
    "_load_or_reuse",
    "_query_history_rollup_exprs",
    "_service_query_history_exprs",
    "_shared_security_user_columns",
    "_shared_state_key",
    "_shared_user_exprs",
    "_shared_user_exprs_from_columns",
    "_storage_summary_from_trend",
    "_store_result",
    "_warehouse_health_exprs",
    "build_shared_access_hygiene_sql",
    "build_shared_bill_metering_summary_live_sql",
    "build_shared_bill_warehouse_delta_live_sql",
    "build_shared_security_mart_brief_sql",
    "build_shared_security_privileged_grant_review_sql",
    "build_shared_security_summary_sql",
    "load_shared_access_hygiene_snapshot",
    "load_shared_account_billing_reconciliation",
    "load_shared_bill_metering_summary",
    "load_shared_bill_warehouse_delta",
    "load_shared_duplicate_query_patterns",
    "load_shared_grants_to_users",
    "load_shared_mfa_coverage",
    "load_shared_procedure_calls",
    "load_shared_procedure_inventory",
    "load_shared_procedure_sla",
    "load_shared_query_history_rollup",
    "load_shared_recommendation_clustering_cost",
    "load_shared_recommendation_failed_tasks",
    "load_shared_recommendation_idle_warehouses",
    "load_shared_recommendation_query_failures",
    "load_shared_recommendation_repeated_queries",
    "load_shared_recommendation_spill_warehouses",
    "load_shared_recommendation_storage_retention",
    "load_shared_service_cost_lens",
    "load_shared_service_cost_trend",
    "load_shared_service_login_health",
    "load_shared_service_pipe_health",
    "load_shared_service_query_health",
    "load_shared_service_task_health",
    "load_shared_service_warehouse_health",
    "load_shared_storage_db_detail",
    "load_shared_storage_trend",
    "load_shared_task_health_summary",
    "load_shared_task_history_detail",
    "load_shared_usage_metering_kpis",
    "load_shared_usage_storage_kpis",
    "load_shared_warehouse_credit_anomalies",
    "load_shared_warehouse_daily_credits",
    "load_shared_warehouse_daily_credits_by_warehouse",
    "load_shared_warehouse_efficiency",
    "load_shared_warehouse_heatmap",
    "load_shared_warehouse_overview",
    "load_shared_warehouse_pressure_summary",
    "load_shared_warehouse_right_sizing",
    "load_shared_warehouse_scaling_events",
    "load_shared_warehouse_spill",
    "shared_mfa_count_expr",
    "shared_mfa_gap_predicate",
    "shared_mfa_proof_label",
)
