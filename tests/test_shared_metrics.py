from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils import shared_metrics as shared_metrics_facade  # noqa: E402
from utils import (  # noqa: E402
    shared_metrics_cache,
    shared_metrics_contracts,
    shared_metrics_procedures,
    shared_metrics_query,
    shared_metrics_recommendations,
    shared_metrics_service_cost,
    shared_metrics_service_health,
    shared_metrics_security,
    shared_metrics_storage,
    shared_metrics_tasks,
    shared_metrics_usage,
    shared_metrics_warehouse,
)
from utils.company_filter import get_company_scope_key  # noqa: E402
from utils.shared_metrics import (  # noqa: E402
    SharedMetricResult,
    _load_or_reuse,
    _query_history_rollup_exprs,
    _service_query_history_exprs,
    _shared_state_key,
    _storage_summary_from_trend,
    build_shared_bill_warehouse_delta_live_sql,
    build_shared_access_hygiene_sql,
    build_shared_security_mart_brief_sql,
    build_shared_security_privileged_grant_review_sql,
    build_shared_security_summary_sql,
    load_shared_access_hygiene_snapshot,
    load_shared_bill_metering_summary,
    load_shared_bill_warehouse_delta,
    load_shared_duplicate_query_patterns,
    load_shared_procedure_calls,
    load_shared_procedure_inventory,
    load_shared_procedure_sla,
    load_shared_recommendation_clustering_cost,
    load_shared_grants_to_users,
    load_shared_mfa_coverage,
    load_shared_query_history_rollup,
    load_shared_recommendation_failed_tasks,
    load_shared_recommendation_idle_warehouses,
    load_shared_recommendation_query_failures,
    load_shared_recommendation_repeated_queries,
    load_shared_recommendation_spill_warehouses,
    load_shared_recommendation_storage_retention,
    load_shared_service_cost_lens,
    load_shared_service_cost_trend,
    load_shared_service_login_health,
    load_shared_service_pipe_health,
    load_shared_service_query_health,
    load_shared_service_task_health,
    load_shared_service_warehouse_health,
    load_shared_storage_trend,
    load_shared_task_health_summary,
    load_shared_task_history_detail,
    load_shared_usage_metering_kpis,
    load_shared_warehouse_credit_anomalies,
    load_shared_warehouse_right_sizing,
    load_shared_warehouse_daily_credits_by_warehouse,
    load_shared_warehouse_efficiency,
    load_shared_warehouse_heatmap,
    load_shared_warehouse_overview,
    load_shared_warehouse_pressure_summary,
    load_shared_warehouse_scaling_events,
    load_shared_warehouse_spill,
    shared_mfa_count_expr,
    shared_mfa_gap_predicate,
    shared_mfa_proof_label,
)


class SharedMetricsTests(unittest.TestCase):
    def setUp(self):
        self._previous_state = dict(st.session_state)
        st.session_state.clear()
        st.session_state["active_company"] = "ALFA"
        st.session_state["global_environment"] = "ALL"

    def tearDown(self):
        st.session_state.clear()
        st.session_state.update(self._previous_state)

    def test_shared_metrics_contracts_and_cache_remain_public_surface(self):
        self.assertIs(SharedMetricResult, shared_metrics_contracts.SharedMetricResult)
        self.assertIs(shared_metrics_facade.SharedMetricResult, shared_metrics_contracts.SharedMetricResult)
        self.assertIs(shared_metrics_facade._empty_result, shared_metrics_cache._empty_result)
        self.assertIs(shared_metrics_facade._shared_state_key, shared_metrics_cache._shared_state_key)
        self.assertIs(shared_metrics_facade._get_cached_result, shared_metrics_cache._get_cached_result)
        self.assertIs(shared_metrics_facade._store_result, shared_metrics_cache._store_result)
        self.assertIs(shared_metrics_facade._load_or_reuse, shared_metrics_cache._load_or_reuse)
        self.assertIs(shared_metrics_facade._global_filter_values, shared_metrics_cache._global_filter_values)
        self.assertIs(shared_metrics_facade._company_column_filter, shared_metrics_cache._company_column_filter)
        self.assertIs(shared_metrics_facade._storage_summary_from_trend, shared_metrics_storage._storage_summary_from_trend)
        self.assertIs(shared_metrics_facade.load_shared_storage_trend, shared_metrics_storage.load_shared_storage_trend)
        self.assertIs(shared_metrics_facade.load_shared_usage_storage_kpis, shared_metrics_storage.load_shared_usage_storage_kpis)
        self.assertIs(shared_metrics_facade.load_shared_storage_db_detail, shared_metrics_storage.load_shared_storage_db_detail)
        self.assertIs(shared_metrics_facade.load_shared_usage_metering_kpis, shared_metrics_usage.load_shared_usage_metering_kpis)
        self.assertIs(
            shared_metrics_facade.build_shared_bill_metering_summary_live_sql,
            shared_metrics_usage.build_shared_bill_metering_summary_live_sql,
        )
        self.assertIs(
            shared_metrics_facade.build_shared_bill_warehouse_delta_live_sql,
            shared_metrics_usage.build_shared_bill_warehouse_delta_live_sql,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_bill_metering_summary,
            shared_metrics_usage.load_shared_bill_metering_summary,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_bill_warehouse_delta,
            shared_metrics_usage.load_shared_bill_warehouse_delta,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_service_cost_lens,
            shared_metrics_service_cost.load_shared_service_cost_lens,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_service_cost_trend,
            shared_metrics_service_cost.load_shared_service_cost_trend,
        )
        self.assertIs(shared_metrics_facade._query_history_rollup_exprs, shared_metrics_query._query_history_rollup_exprs)
        self.assertIs(
            shared_metrics_facade.load_shared_query_history_rollup,
            shared_metrics_query.load_shared_query_history_rollup,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_warehouse_pressure_summary,
            shared_metrics_query.load_shared_warehouse_pressure_summary,
        )
        self.assertIs(shared_metrics_facade._first_numeric_value, shared_metrics_service_health._first_numeric_value)
        self.assertIs(
            shared_metrics_facade._service_query_history_exprs,
            shared_metrics_service_health._service_query_history_exprs,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_service_query_health,
            shared_metrics_service_health.load_shared_service_query_health,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_service_warehouse_health,
            shared_metrics_service_health.load_shared_service_warehouse_health,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_service_login_health,
            shared_metrics_service_health.load_shared_service_login_health,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_service_task_health,
            shared_metrics_service_health.load_shared_service_task_health,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_service_pipe_health,
            shared_metrics_service_health.load_shared_service_pipe_health,
        )
        self.assertIs(shared_metrics_facade._warehouse_health_exprs, shared_metrics_warehouse._warehouse_health_exprs)
        self.assertIs(
            shared_metrics_facade.load_shared_warehouse_credit_anomalies,
            shared_metrics_warehouse.load_shared_warehouse_credit_anomalies,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_warehouse_daily_credits,
            shared_metrics_warehouse.load_shared_warehouse_daily_credits,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_warehouse_daily_credits_by_warehouse,
            shared_metrics_warehouse.load_shared_warehouse_daily_credits_by_warehouse,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_warehouse_efficiency,
            shared_metrics_warehouse.load_shared_warehouse_efficiency,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_warehouse_heatmap,
            shared_metrics_warehouse.load_shared_warehouse_heatmap,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_warehouse_overview,
            shared_metrics_warehouse.load_shared_warehouse_overview,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_warehouse_right_sizing,
            shared_metrics_warehouse.load_shared_warehouse_right_sizing,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_warehouse_scaling_events,
            shared_metrics_warehouse.load_shared_warehouse_scaling_events,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_warehouse_spill,
            shared_metrics_warehouse.load_shared_warehouse_spill,
        )
        self.assertIs(shared_metrics_facade.shared_mfa_count_expr, shared_metrics_security.shared_mfa_count_expr)
        self.assertIs(shared_metrics_facade.shared_mfa_gap_predicate, shared_metrics_security.shared_mfa_gap_predicate)
        self.assertIs(shared_metrics_facade.shared_mfa_proof_label, shared_metrics_security.shared_mfa_proof_label)
        self.assertIs(
            shared_metrics_facade.build_shared_security_summary_sql,
            shared_metrics_security.build_shared_security_summary_sql,
        )
        self.assertIs(
            shared_metrics_facade.build_shared_security_mart_brief_sql,
            shared_metrics_security.build_shared_security_mart_brief_sql,
        )
        self.assertIs(
            shared_metrics_facade.build_shared_security_privileged_grant_review_sql,
            shared_metrics_security.build_shared_security_privileged_grant_review_sql,
        )
        self.assertIs(
            shared_metrics_facade.build_shared_access_hygiene_sql,
            shared_metrics_security.build_shared_access_hygiene_sql,
        )
        self.assertIs(shared_metrics_facade.load_shared_mfa_coverage, shared_metrics_security.load_shared_mfa_coverage)
        self.assertIs(shared_metrics_facade.load_shared_grants_to_users, shared_metrics_security.load_shared_grants_to_users)
        self.assertIs(
            shared_metrics_facade.load_shared_access_hygiene_snapshot,
            shared_metrics_security.load_shared_access_hygiene_snapshot,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_recommendation_idle_warehouses,
            shared_metrics_recommendations.load_shared_recommendation_idle_warehouses,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_recommendation_spill_warehouses,
            shared_metrics_recommendations.load_shared_recommendation_spill_warehouses,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_recommendation_failed_tasks,
            shared_metrics_recommendations.load_shared_recommendation_failed_tasks,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_recommendation_query_failures,
            shared_metrics_recommendations.load_shared_recommendation_query_failures,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_recommendation_storage_retention,
            shared_metrics_recommendations.load_shared_recommendation_storage_retention,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_recommendation_clustering_cost,
            shared_metrics_recommendations.load_shared_recommendation_clustering_cost,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_recommendation_repeated_queries,
            shared_metrics_recommendations.load_shared_recommendation_repeated_queries,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_duplicate_query_patterns,
            shared_metrics_recommendations.load_shared_duplicate_query_patterns,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_task_health_summary,
            shared_metrics_tasks.load_shared_task_health_summary,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_task_history_detail,
            shared_metrics_tasks.load_shared_task_history_detail,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_procedure_inventory,
            shared_metrics_procedures.load_shared_procedure_inventory,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_procedure_calls,
            shared_metrics_procedures.load_shared_procedure_calls,
        )
        self.assertIs(
            shared_metrics_facade.load_shared_procedure_sla,
            shared_metrics_procedures.load_shared_procedure_sla,
        )

    def test_shared_metrics_public_import_surface_stays_available(self):
        public_names = (
            "SharedMetricResult",
            "_load_or_reuse",
            "_shared_state_key",
            "_storage_summary_from_trend",
            "_query_history_rollup_exprs",
            "_service_query_history_exprs",
            "build_shared_bill_warehouse_delta_live_sql",
            "build_shared_access_hygiene_sql",
            "build_shared_security_mart_brief_sql",
            "build_shared_security_privileged_grant_review_sql",
            "build_shared_security_summary_sql",
            "load_shared_access_hygiene_snapshot",
            "load_shared_bill_metering_summary",
            "load_shared_bill_warehouse_delta",
            "load_shared_duplicate_query_patterns",
            "load_shared_procedure_calls",
            "load_shared_procedure_inventory",
            "load_shared_procedure_sla",
            "load_shared_recommendation_clustering_cost",
            "load_shared_grants_to_users",
            "load_shared_mfa_coverage",
            "load_shared_query_history_rollup",
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
            "load_shared_storage_trend",
            "load_shared_task_health_summary",
            "load_shared_task_history_detail",
            "load_shared_usage_metering_kpis",
            "load_shared_warehouse_credit_anomalies",
            "load_shared_warehouse_right_sizing",
            "load_shared_warehouse_daily_credits_by_warehouse",
            "load_shared_warehouse_efficiency",
            "load_shared_warehouse_heatmap",
            "load_shared_warehouse_overview",
            "load_shared_warehouse_pressure_summary",
            "load_shared_warehouse_scaling_events",
            "load_shared_warehouse_spill",
            "shared_mfa_count_expr",
            "shared_mfa_gap_predicate",
            "shared_mfa_proof_label",
        )
        for name in public_names:
            with self.subTest(name=name):
                self.assertTrue(hasattr(shared_metrics_facade, name))
                self.assertIn(name, shared_metrics_facade.__all__)

    def test_shared_metrics_all_exports_exist(self):
        self.assertIsInstance(shared_metrics_facade.__all__, tuple)
        for name in shared_metrics_facade.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(shared_metrics_facade, name))

    def test_shared_metrics_facade_continues_shrinking(self):
        source = APP_ROOT.joinpath("utils", "shared_metrics.py").read_text(encoding="utf-8")
        self.assertLess(len(source.splitlines()), 250)
        forbidden_fragments = (
            "SNOWFLAKE.ACCOUNT_USAGE",
            "run_query(",
            "run_query_or_raise(",
            "def load_shared_",
            "def build_shared_",
            "pd.DataFrame(",
        )
        for fragment in forbidden_fragments:
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, source)

    def test_shared_metrics_load_or_reuse_returns_cached_result(self):
        calls = []

        def loader():
            calls.append("loaded")
            return SharedMetricResult(pd.DataFrame({"VALUE": [len(calls)]}), "Unit loader")

        first = _load_or_reuse("unit_cache", ("ALFA", 30), loader)
        second = _load_or_reuse("unit_cache", ("ALFA", 30), loader)

        self.assertIs(first, second)
        self.assertEqual(calls, ["loaded"])

    def test_shared_state_key_matches_company_scope_key(self):
        self.assertEqual(
            _shared_state_key("unit_metric", "ALFA", 30),
            f"_shared_metric_{get_company_scope_key('unit_metric', 'ALFA', 30)}",
        )

    def test_query_history_rollup_exprs_optional_columns(self):
        with patch(
            "utils.shared_metrics_query.filter_existing_columns",
            return_value=[
                "ERROR_CODE",
                "QUEUED_OVERLOAD_TIME",
                "QUEUED_PROVISIONING_TIME",
                "QUEUED_REPAIR_TIME",
                "CREDITS_USED_CLOUD_SERVICES",
                "BYTES_SPILLED_TO_REMOTE_STORAGE",
                "EXECUTION_TIME",
            ],
        ):
            exprs = _query_history_rollup_exprs(object())

        self.assertIn("q.error_code IS NULL", exprs["success_expr"])
        self.assertIn("q.queued_overload_time > 0", exprs["queued_expr"])
        self.assertIn("q.queued_provisioning_time > 0", exprs["queued_expr"])
        self.assertIn("credits_used_cloud_services", exprs["cloud_expr"])
        self.assertIn("bytes_spilled_to_remote_storage", exprs["remote_spill_expr"])
        self.assertIn("q.execution_time", exprs["avg_execution_expr"])

    def test_service_query_history_exprs_optional_columns(self):
        with patch(
            "utils.shared_metrics_service_health.filter_existing_columns",
            return_value=[
                "ERROR_CODE",
                "WAREHOUSE_SIZE",
                "QUEUED_OVERLOAD_TIME",
                "TRANSACTION_BLOCKED_TIME",
                "BYTES_SPILLED_TO_REMOTE_STORAGE",
                "PERCENTAGE_SCANNED_FROM_CACHE",
            ],
        ):
            exprs = _service_query_history_exprs(object())

        self.assertEqual(exprs["error_pred"], "q.error_code IS NOT NULL")
        self.assertEqual(exprs["wh_size_expr"], "MAX(q.warehouse_size)")
        self.assertEqual(exprs["queued_pred"], "q.queued_overload_time > 0")
        self.assertEqual(exprs["blocked_pred"], "q.transaction_blocked_time > 0")
        self.assertIn("bytes_spilled_to_remote_storage", exprs["remote_spill_expr"])
        self.assertIn("percentage_scanned_from_cache", exprs["cache_expr"])

    def test_storage_trend_reuses_session_result_for_same_scope(self):
        frame = pd.DataFrame({
            "USAGE_DATE": ["2026-06-15"],
            "STORAGE_GB": [1024.0],
            "FAILSAFE_GB": [0.0],
            "STAGE_GB": [0.0],
            "TOTAL_STORAGE_TB": [1.0],
        })

        with patch("utils.shared_metrics_storage.run_query", return_value=frame) as mock_run:
            first = load_shared_storage_trend(30, "ALFA", allow_live_fallback=False, section="Unit Test")
            second = load_shared_storage_trend(30, "ALFA", allow_live_fallback=False, section="Unit Test")

        self.assertIs(first, second)
        self.assertEqual(first.source, "Fast storage summary")
        self.assertEqual(mock_run.call_count, 1)

    def test_storage_trend_live_fallback_is_capped(self):
        live_frame = pd.DataFrame({
            "USAGE_DATE": ["2026-06-15"],
            "STORAGE_GB": [2048.0],
            "FAILSAFE_GB": [0.0],
            "STAGE_GB": [128.0],
            "TOTAL_STORAGE_TB": [2.125],
        })

        with patch(
            "utils.shared_metrics_storage.run_query",
            side_effect=[pd.DataFrame(), live_frame],
        ) as mock_run:
            result = load_shared_storage_trend(120, "ALL", allow_live_fallback=True, section="Unit Test")

        self.assertEqual(mock_run.call_count, 2)
        self.assertEqual(result.effective_days, 90)
        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE storage views")
        live_sql = mock_run.call_args_list[1].args[0]
        self.assertIn("STAGE_STORAGE_USAGE_HISTORY", live_sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.STORAGE_USAGE", live_sql)
        self.assertIn("HYBRID_TABLE_STORAGE_BYTES", live_sql.upper())
        self.assertIn("ARCHIVE_STORAGE_COOL_BYTES", live_sql.upper())
        self.assertIn("HYBRID_STORAGE_COST_USD", live_sql.upper())
        self.assertIn("ARCHIVE_COLD_COST_USD", live_sql.upper())
        self.assertIn("DATEADD('day', -90", live_sql)

    def test_storage_summary_from_trend_uses_prior_window(self):
        trend = pd.DataFrame({
            "USAGE_DATE": ["2026-05-16", "2026-06-15"],
            "STORAGE_GB": [1024.0, 2048.0],
            "FAILSAFE_GB": [256.0, 512.0],
        })

        summary = _storage_summary_from_trend(trend, 30)

        self.assertEqual(float(summary["ACTIVE_STORAGE_TB"].iloc[0]), 2.0)
        self.assertEqual(float(summary["FAILSAFE_STORAGE_TB"].iloc[0]), 0.5)
        self.assertEqual(float(summary["PRIOR_ACTIVE_STORAGE_TB"].iloc[0]), 1.0)

    def test_usage_metering_reuses_session_result_for_same_scope(self):
        frame = pd.DataFrame({
            "TOTAL_CREDITS": [42.0],
            "PRIOR_CREDITS": [35.0],
            "COMPUTE_CREDITS": [40.0],
            "WAREHOUSE_CLOUD_CREDITS": [2.0],
        })

        with patch("utils.shared_metrics_usage.run_query", return_value=frame) as mock_run:
            first = load_shared_usage_metering_kpis(object(), 30, "ALFA", section="Unit Test")
            second = load_shared_usage_metering_kpis(object(), 30, "ALFA", section="Unit Test")

        self.assertIs(first, second)
        self.assertEqual(first.source, "Fast metering summary")
        self.assertEqual(mock_run.call_count, 1)

    def test_usage_metering_live_fallback_matches_usage_overview_schema(self):
        live_frame = pd.DataFrame({
            "TOTAL_CREDITS": [12.0],
            "PRIOR_CREDITS": [9.0],
            "COMPUTE_CREDITS": [11.0],
            "WAREHOUSE_CLOUD_CREDITS": [1.0],
        })

        with patch(
            "utils.shared_metrics_usage.run_query",
            side_effect=[pd.DataFrame(), live_frame],
        ) as mock_run, patch(
            "utils.shared_metrics_usage.filter_existing_columns",
            return_value=["CREDITS_USED_COMPUTE"],
        ):
            result = load_shared_usage_metering_kpis(object(), 30, "ALFA", section="Unit Test")

        self.assertEqual(mock_run.call_count, 2)
        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY")
        live_sql = mock_run.call_args_list[1].args[0].upper()
        self.assertIn("AS PRIOR_CREDITS", live_sql)
        self.assertIn("AS COMPUTE_CREDITS", live_sql)
        self.assertIn("AS WAREHOUSE_CLOUD_CREDITS", live_sql)
        self.assertIn("CREDITS_USED_COMPUTE", live_sql)
        self.assertNotIn("CREDITS_USED_CLOUD_SERVICES, 0)) AS WAREHOUSE_CLOUD_CREDITS", live_sql)

    def test_service_cost_lens_reuses_official_metering_history(self):
        frame = pd.DataFrame({
            "SERVICE_TYPE": ["WAREHOUSE_METERING"],
            "CREDITS_BILLED": [10.0],
            "ESTIMATED_COST_USD": [36.8],
        })

        with patch("utils.shared_metrics_service_cost.run_query_or_raise", return_value=frame) as mock_run:
            first = load_shared_service_cost_lens(
                14,
                "ALFA",
                credit_price=3.68,
                ai_credit_price=2.20,
                section="Unit Test",
            )
            second = load_shared_service_cost_lens(
                14,
                "ALFA",
                credit_price=3.68,
                ai_credit_price=2.20,
                section="Unit Test",
            )

        self.assertIs(first, second)
        self.assertEqual(mock_run.call_count, 1)
        self.assertEqual(first.source, "Official Cost Monitor: SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY")
        sql = mock_run.call_args.args[0].upper()
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY", sql)
        self.assertIn("CREDITS_BILLED", sql)
        self.assertIn("START_TIME < DATEADD('HOUR', -24, CURRENT_TIMESTAMP())", sql)

    def test_service_cost_trend_reuses_official_metering_history(self):
        frame = pd.DataFrame({
            "USAGE_DATE": ["2026-06-15"],
            "DAILY_CREDITS": [10.0],
            "DAILY_SPEND_USD": [36.8],
        })

        with patch("utils.shared_metrics_service_cost.run_query_or_raise", return_value=frame) as mock_run:
            first = load_shared_service_cost_trend(
                7,
                "ALFA",
                credit_price=3.68,
                ai_credit_price=2.20,
                section="Unit Test",
            )
            second = load_shared_service_cost_trend(
                7,
                "ALFA",
                credit_price=3.68,
                ai_credit_price=2.20,
                section="Unit Test",
            )

        self.assertIs(first, second)
        self.assertEqual(mock_run.call_count, 1)
        self.assertEqual(first.source, "Official Cost Monitor: SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY")
        sql = mock_run.call_args.args[0].upper()
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY", sql)
        self.assertIn("DAILY_SPEND_USD", sql)
        self.assertIn("WHERE PERIOD = 'CURRENT'", sql)

    def test_bill_metering_summary_reuses_fast_summary(self):
        frame = pd.DataFrame({
            "PERIOD": ["CURRENT"],
            "CREDITS": [42.0],
            "ACTIVE_WAREHOUSES": [3],
            "ACTIVE_DAYS": [7],
        })

        with patch("utils.shared_metrics_usage.run_query", return_value=frame) as mock_run:
            first = load_shared_bill_metering_summary(
                "DATEADD('DAY', -7, CURRENT_TIMESTAMP())",
                "CURRENT_TIMESTAMP()",
                "DATEADD('DAY', -14, CURRENT_TIMESTAMP())",
                "DATEADD('DAY', -7, CURRENT_TIMESTAMP())",
                "ALFA",
                warehouse_contains="BI",
                section="Unit Test",
            )
            second = load_shared_bill_metering_summary(
                "DATEADD('DAY', -7, CURRENT_TIMESTAMP())",
                "CURRENT_TIMESTAMP()",
                "DATEADD('DAY', -14, CURRENT_TIMESTAMP())",
                "DATEADD('DAY', -7, CURRENT_TIMESTAMP())",
                "ALFA",
                warehouse_contains="BI",
                section="Unit Test",
            )

        self.assertIs(first, second)
        self.assertEqual(first.source, "Fast billing summary")
        self.assertEqual(mock_run.call_count, 1)
        sql = mock_run.call_args.args[0].upper()
        self.assertIn("FACT_WAREHOUSE_HOURLY", sql)
        self.assertIn("WAREHOUSE_NAME ILIKE", sql)

    def test_bill_warehouse_delta_live_fallback_is_shared(self):
        live_frame = pd.DataFrame({
            "WAREHOUSE_NAME": ["ALFA_WH"],
            "CURRENT_CREDITS": [20.0],
            "PRIOR_CREDITS": [10.0],
            "CREDIT_DELTA": [10.0],
            "PCT_DELTA": [100.0],
        })

        with patch(
            "utils.shared_metrics_usage.run_query",
            side_effect=[pd.DataFrame(), live_frame],
        ) as mock_run:
            result = load_shared_bill_warehouse_delta(
                "DATEADD('DAY', -7, CURRENT_TIMESTAMP())",
                "CURRENT_TIMESTAMP()",
                "DATEADD('DAY', -14, CURRENT_TIMESTAMP())",
                "DATEADD('DAY', -7, CURRENT_TIMESTAMP())",
                "ALFA",
                warehouse_contains="BI",
                section="Unit Test",
            )

        self.assertTrue(result.available)
        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY")
        self.assertEqual(mock_run.call_count, 2)
        mart_sql = mock_run.call_args_list[0].args[0].upper()
        live_sql = mock_run.call_args_list[1].args[0].upper()
        self.assertIn("FACT_WAREHOUSE_HOURLY", mart_sql)
        self.assertIn("WAREHOUSE_METERING_HISTORY", live_sql)
        self.assertIn("FULL OUTER JOIN", live_sql)
        self.assertIn("WAREHOUSE_NAME ILIKE", live_sql)

    def test_bill_warehouse_delta_live_sql_can_skip_global_filter(self):
        st.session_state["global_warehouse"] = "BI"

        scoped_sql = build_shared_bill_warehouse_delta_live_sql(
            "DATEADD('DAY', -7, CURRENT_TIMESTAMP())",
            "CURRENT_TIMESTAMP()",
            "DATEADD('DAY', -14, CURRENT_TIMESTAMP())",
            "DATEADD('DAY', -7, CURRENT_TIMESTAMP())",
            company="ALFA",
        ).upper()
        splash_sql = build_shared_bill_warehouse_delta_live_sql(
            "DATEADD('DAY', -7, CURRENT_TIMESTAMP())",
            "CURRENT_TIMESTAMP()",
            "DATEADD('DAY', -14, CURRENT_TIMESTAMP())",
            "DATEADD('DAY', -7, CURRENT_TIMESTAMP())",
            company="ALFA",
            include_global_warehouse_filter=False,
        ).upper()

        self.assertIn("WAREHOUSE_NAME ILIKE '%BI%'", scoped_sql)
        self.assertNotIn("WAREHOUSE_NAME ILIKE '%BI%'", splash_sql)
        self.assertIn("WAREHOUSE_METERING_HISTORY", splash_sql)

    def test_warehouse_daily_by_warehouse_reuses_session_result(self):
        frame = pd.DataFrame({
            "DAY": ["2026-06-15"],
            "WAREHOUSE_NAME": ["ALFA_WH"],
            "WAREHOUSE_SIZE": ["MEDIUM"],
            "DAILY_CREDITS": [8.5],
        })

        with patch(
            "utils.shared_metrics_warehouse.filter_existing_columns",
            return_value=["WAREHOUSE_SIZE"],
        ), patch("utils.shared_metrics_warehouse.run_query", return_value=frame) as mock_run:
            first = load_shared_warehouse_daily_credits_by_warehouse(object(), 30, "ALFA", section="Unit Test")
            second = load_shared_warehouse_daily_credits_by_warehouse(object(), 30, "ALFA", section="Unit Test")

        self.assertIs(first, second)
        self.assertEqual(first.source, "Live: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY by warehouse")
        self.assertEqual(mock_run.call_count, 1)

    def test_warehouse_daily_by_warehouse_handles_missing_size_column(self):
        frame = pd.DataFrame({
            "DAY": ["2026-06-15"],
            "WAREHOUSE_NAME": ["ALFA_WH"],
            "WAREHOUSE_SIZE": [None],
            "DAILY_CREDITS": [8.5],
        })

        with patch(
            "utils.shared_metrics_warehouse.filter_existing_columns",
            return_value=[],
        ), patch("utils.shared_metrics_warehouse.run_query", return_value=frame) as mock_run:
            result = load_shared_warehouse_daily_credits_by_warehouse(object(), 7, "ALFA", section="Unit Test")

        self.assertTrue(result.available)
        live_sql = mock_run.call_args.args[0].upper()
        self.assertIn("NULL::VARCHAR AS WAREHOUSE_SIZE", live_sql)
        self.assertIn("WAREHOUSE_METERING_HISTORY", live_sql)

    def test_warehouse_credit_anomalies_prefers_fast_summary(self):
        frame = pd.DataFrame({
            "WAREHOUSE_NAME": ["ALFA_WH"],
            "DAY": ["2026-06-15"],
            "DAILY_CREDITS": [42.0],
            "ROLLING_AVG": [10.0],
            "ZSCORE": [3.2],
            "ANOMALY_FLAG": ["SPIKE"],
        })

        with patch("utils.shared_metrics_warehouse.run_query", return_value=frame) as mock_run:
            first = load_shared_warehouse_credit_anomalies("ALFA", days=30, section="Unit Test")
            second = load_shared_warehouse_credit_anomalies("ALFA", days=30, section="Unit Test")

        self.assertIs(first, second)
        self.assertEqual(first.source, "Fast warehouse credit summary")
        self.assertEqual(mock_run.call_count, 1)
        sql = mock_run.call_args.args[0].upper()
        self.assertIn("FACT_WAREHOUSE_HOURLY", sql)
        self.assertIn("CURRENT_DATE()", sql)
        self.assertIn("ANOMALY_FLAG", sql)

    def test_warehouse_credit_anomalies_live_fallback_is_explicit(self):
        live_frame = pd.DataFrame({
            "WAREHOUSE_NAME": ["ALFA_WH"],
            "DAY": ["2026-06-15"],
            "DAILY_CREDITS": [22.0],
            "ROLLING_AVG": [8.0],
            "ZSCORE": [2.4],
            "ANOMALY_FLAG": ["SPIKE"],
        })

        with patch(
            "utils.shared_metrics_warehouse.run_query",
            side_effect=[pd.DataFrame(), live_frame],
        ) as mock_run:
            result = load_shared_warehouse_credit_anomalies(
                "ALFA",
                days=30,
                allow_live_fallback=True,
                section="Unit Test",
            )

        self.assertTrue(result.available)
        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY")
        self.assertEqual(mock_run.call_count, 2)
        live_sql = mock_run.call_args_list[1].args[0].upper()
        self.assertIn("WAREHOUSE_METERING_HISTORY", live_sql)
        self.assertIn("CURRENT_DATE()", live_sql)
        self.assertIn("ROLLING_AVG IS NOT NULL", live_sql)

    def test_warehouse_credit_anomalies_can_skip_live_fallback(self):
        with patch("utils.shared_metrics_warehouse.run_query", return_value=pd.DataFrame()) as mock_run:
            result = load_shared_warehouse_credit_anomalies(
                "ALFA",
                days=30,
                allow_live_fallback=False,
                section="Unit Test",
            )

        self.assertFalse(result.available)
        self.assertEqual(result.source, "Fast warehouse credit summary")
        self.assertEqual(mock_run.call_count, 1)

    def test_warehouse_overview_reuses_fast_summary_result(self):
        frame = pd.DataFrame({
            "WAREHOUSE_NAME": ["ALFA_WH"],
            "TOTAL_QUERIES": [100],
            "METERED_CREDITS": [10.0],
            "PRIOR_METERED_CREDITS": [7.0],
            "CREDIT_DELTA": [3.0],
        })

        with patch("utils.shared_metrics_warehouse.run_query", return_value=frame) as mock_run:
            first = load_shared_warehouse_overview(object(), 7, "ALFA", section="Unit Test")
            second = load_shared_warehouse_overview(object(), 7, "ALFA", section="Unit Test")

        self.assertIs(first, second)
        self.assertIn("Fast warehouse summary", first.source)
        self.assertEqual(mock_run.call_count, 1)

    def test_warehouse_overview_live_fallback_includes_movement_columns(self):
        live_frame = pd.DataFrame({
            "WAREHOUSE_NAME": ["ALFA_WH"],
            "TOTAL_QUERIES": [100],
            "METERED_CREDITS": [10.0],
            "PRIOR_METERED_CREDITS": [7.0],
            "CREDIT_DELTA": [3.0],
            "CREDIT_DELTA_PCT": [42.9],
        })

        with patch(
            "utils.shared_metrics_warehouse.run_query",
            side_effect=[pd.DataFrame(), live_frame],
        ) as mock_run, patch(
            "utils.shared_metrics_warehouse.filter_existing_columns",
            side_effect=[
                ["WAREHOUSE_SIZE", "QUEUED_OVERLOAD_TIME", "BYTES_SPILLED_TO_REMOTE_STORAGE"],
                ["CREDITS_USED_COMPUTE", "CREDITS_USED_CLOUD_SERVICES"],
            ],
        ):
            result = load_shared_warehouse_overview(object(), 7, "ALFA", section="Unit Test")

        self.assertEqual(mock_run.call_count, 2)
        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY + WAREHOUSE_METERING_HISTORY")
        live_sql = mock_run.call_args_list[1].args[0].upper()
        self.assertIn("QUERY_ROLLUP", live_sql)
        self.assertIn("CREDIT_ROLLUP", live_sql)
        self.assertIn("AS PRIOR_METERED_CREDITS", live_sql)
        self.assertIn("AS CREDIT_DELTA", live_sql)
        self.assertIn("AS CREDIT_DELTA_PCT", live_sql)

    def test_query_history_rollup_reuses_fast_summary(self):
        frame = pd.DataFrame({
            "TOTAL_QUERIES": [100],
            "FAILED_QUERIES": [2],
            "QUEUED_QUERIES": [5],
            "AVG_ELAPSED_SEC": [1.2],
        })

        with patch("utils.shared_metrics_query.run_query", return_value=frame) as mock_run:
            first = load_shared_query_history_rollup(object(), 7, "ALFA", section="Unit Test")
            second = load_shared_query_history_rollup(object(), 7, "ALFA", section="Unit Test")

        self.assertIs(first, second)
        self.assertEqual(first.source, "Fast usage summary")
        self.assertEqual(mock_run.call_count, 1)

    def test_query_history_rollup_live_fallback_uses_optional_columns(self):
        live_frame = pd.DataFrame({
            "TOTAL_QUERIES": [12],
            "FAILED_QUERIES": [1],
            "QUEUED_QUERIES": [2],
            "CLOUD_SERVICE_CREDITS": [0.5],
        })

        with patch(
            "utils.shared_metrics_query.run_query",
            side_effect=[pd.DataFrame(), live_frame],
        ) as mock_run, patch(
            "utils.shared_metrics_query.filter_existing_columns",
            return_value=[
                "ERROR_CODE",
                "QUEUED_OVERLOAD_TIME",
                "CREDITS_USED_CLOUD_SERVICES",
                "EXECUTION_TIME",
            ],
        ):
            result = load_shared_query_history_rollup(object(), 7, "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY")
        self.assertEqual(mock_run.call_count, 2)
        live_sql = mock_run.call_args_list[1].args[0].upper()
        self.assertIn("AS QUERY_SUCCESS_RATE", live_sql)
        self.assertIn("ERROR_CODE IS NULL", live_sql)
        self.assertIn("QUEUED_OVERLOAD_TIME", live_sql)
        self.assertIn("CREDITS_USED_CLOUD_SERVICES", live_sql)

    def test_warehouse_pressure_summary_live_fallback(self):
        live_frame = pd.DataFrame({
            "ACTIVE_WAREHOUSES": [2],
            "PRESSURE_WAREHOUSES": [1],
        })

        with patch(
            "utils.shared_metrics_query.run_query",
            side_effect=[pd.DataFrame(), live_frame],
        ) as mock_run, patch(
            "utils.shared_metrics_query.filter_existing_columns",
            return_value=["ERROR_CODE", "QUEUED_OVERLOAD_TIME", "BYTES_SPILLED_TO_REMOTE_STORAGE"],
        ):
            result = load_shared_warehouse_pressure_summary(object(), 7, "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY")
        live_sql = mock_run.call_args_list[1].args[0].upper()
        self.assertIn("REMOTE_SPILL_GB", live_sql)
        self.assertIn("PRESSURE_WAREHOUSES", live_sql)

    def test_service_query_health_live_fallback_is_hourly(self):
        live_frame = pd.DataFrame({
            "TOTAL_QUERIES": [24],
            "FAILED_QUERIES": [2],
            "QUEUED_QUERIES": [3],
            "BLOCKED_QUERIES": [1],
            "P95_ELAPSED_SEC": [12.5],
        })

        with patch(
            "utils.shared_metrics_service_health.run_query",
            side_effect=[pd.DataFrame(), live_frame],
        ) as mock_run, patch(
            "utils.shared_metrics_service_health.filter_existing_columns",
            return_value=[
                "ERROR_CODE",
                "QUEUED_OVERLOAD_TIME",
                "TRANSACTION_BLOCKED_TIME",
                "BYTES_SPILLED_TO_REMOTE_STORAGE",
            ],
        ):
            result = load_shared_service_query_health(object(), 12, "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY")
        self.assertEqual(mock_run.call_count, 2)
        live_sql = mock_run.call_args_list[1].args[0].upper()
        self.assertIn("DATEADD('HOUR', -12", live_sql)
        self.assertIn("AS BLOCKED_QUERIES", live_sql)
        self.assertIn("P95_ELAPSED_SEC", live_sql)
        self.assertIn("Q.ERROR_CODE IS NOT NULL", live_sql)

    def test_service_warehouse_health_prefers_fast_summary(self):
        frame = pd.DataFrame({
            "WAREHOUSE_NAME": ["ALFA_WH"],
            "TOTAL_QUERIES": [100],
            "QUEUED_SEC": [10.0],
        })

        with patch("utils.shared_metrics_service_health.run_query", return_value=frame) as mock_run:
            result = load_shared_service_warehouse_health(object(), 24, "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Fast warehouse pressure summary")
        self.assertEqual(mock_run.call_count, 1)

    def test_service_login_health_subday_uses_live_history(self):
        frame = pd.DataFrame({
            "LOGIN_EVENTS": [8],
            "FAILED_LOGINS": [1],
        })

        with patch("utils.shared_metrics_service_health.run_query", return_value=frame) as mock_run:
            result = load_shared_service_login_health(4, "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY")
        self.assertEqual(mock_run.call_count, 1)
        sql = mock_run.call_args.args[0].upper()
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY", sql)
        self.assertIn("DATEADD('HOUR', -4", sql)

    def test_service_task_health_falls_back_to_task_history(self):
        live_frame = pd.DataFrame({
            "TASK_RUNS": [4],
            "FAILED_TASKS": [1],
            "SUCCEEDED_TASKS": [3],
            "DISTINCT_TASKS": [2],
        })

        with patch(
            "utils.shared_metrics_service_health.run_query",
            side_effect=[pd.DataFrame(), live_frame],
        ) as mock_run, patch(
            "utils.shared_metrics_service_health.build_task_health_sql",
            return_value="SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY",
        ):
            result = load_shared_service_task_health(object(), 6, "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY")
        self.assertEqual(mock_run.call_count, 2)

    def test_service_pipe_health_uses_copy_history(self):
        frame = pd.DataFrame({
            "LOAD_EVENTS": [5],
            "FAILED_LOADS": [1],
        })

        with patch("utils.shared_metrics_service_health.run_query", return_value=frame) as mock_run:
            result = load_shared_service_pipe_health(8, "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Live: SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY")
        sql = mock_run.call_args.args[0].upper()
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY", sql)
        self.assertIn("DATEADD('HOUR', -8", sql)

    def test_warehouse_scaling_events_prefers_mart(self):
        frame = pd.DataFrame({
            "WAREHOUSE_NAME": ["ALFA_WH"],
            "CREDITS_USED": [10.0],
        })

        with patch("utils.shared_metrics_warehouse.run_query", return_value=frame) as mock_run:
            result = load_shared_warehouse_scaling_events(object(), 7, "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Fast warehouse summary")
        self.assertEqual(mock_run.call_count, 1)

    def test_warehouse_scaling_events_live_fallback_includes_optional_metering(self):
        live_frame = pd.DataFrame({
            "WAREHOUSE_NAME": ["ALFA_WH"],
            "CREDITS_USED": [10.0],
            "CREDITS_USED_COMPUTE": [9.5],
        })

        with patch(
            "utils.shared_metrics_warehouse.run_query",
            side_effect=[pd.DataFrame(), live_frame],
        ) as mock_run, patch(
            "utils.shared_metrics_warehouse.filter_existing_columns",
            side_effect=[["WAREHOUSE_SIZE"], ["CREDITS_USED_COMPUTE", "CREDITS_USED_CLOUD_SERVICES"]],
        ):
            result = load_shared_warehouse_scaling_events(object(), 7, "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY")
        live_sql = mock_run.call_args_list[1].args[0].upper()
        self.assertIn("LATEST_SIZE", live_sql)
        self.assertIn("CREDITS_USED_COMPUTE", live_sql)
        self.assertIn("CREDITS_USED_CLOUD_SERVICES", live_sql)

    def test_warehouse_efficiency_uses_shared_query_attributed_metering(self):
        frame = pd.DataFrame({
            "WAREHOUSE_NAME": ["ALFA_WH"],
            "METERED_CREDITS": [10.0],
            "EFFICIENCY_SCORE": [65.0],
        })

        with patch("utils.shared_metrics_warehouse.run_query", return_value=frame) as mock_run, patch(
            "utils.shared_metrics_warehouse.filter_existing_columns",
            side_effect=[
                [
                    "WAREHOUSE_SIZE",
                    "QUEUED_OVERLOAD_TIME",
                    "BYTES_SPILLED_TO_REMOTE_STORAGE",
                    "PERCENTAGE_SCANNED_FROM_CACHE",
                ],
                ["CREDITS_USED_COMPUTE", "CREDITS_USED_CLOUD_SERVICES"],
            ],
        ):
            result = load_shared_warehouse_efficiency(object(), 7, "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Live: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY + query-attributed metering")
        sql = mock_run.call_args.args[0].upper()
        self.assertIn("PER_QUERY_CREDITS", sql)
        self.assertIn("QUEUE_SEC_PER_CREDIT", sql)
        self.assertIn("REMOTE_SPILL_GB_PER_CREDIT", sql)
        self.assertIn("EFFICIENCY_SCORE", sql)

    def test_warehouse_spill_uses_shared_query_history_loader(self):
        frame = pd.DataFrame({
            "WAREHOUSE_NAME": ["ALFA_WH"],
            "LOCAL_SPILL_GB": [1.5],
            "REMOTE_SPILL_GB": [2.5],
        })

        with patch("utils.shared_metrics_warehouse.run_query", return_value=frame) as mock_run, patch(
            "utils.shared_metrics_warehouse.filter_existing_columns",
            return_value=[
                "WAREHOUSE_SIZE",
                "BYTES_SPILLED_TO_LOCAL_STORAGE",
                "BYTES_SPILLED_TO_REMOTE_STORAGE",
            ],
        ):
            result = load_shared_warehouse_spill(object(), 7, "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Live: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY")
        sql = mock_run.call_args.args[0].upper()
        self.assertIn("BYTES_SPILLED_TO_LOCAL_STORAGE", sql)
        self.assertIn("BYTES_SPILLED_TO_REMOTE_STORAGE", sql)
        self.assertIn("SPILL_QUERY_COUNT", sql)

    def test_warehouse_heatmap_prefers_mart_and_caps_live_fallback(self):
        mart_frame = pd.DataFrame({
            "WAREHOUSE_NAME": ["ALFA_WH"],
            "DAY_OF_WEEK": [1],
            "HOUR_OF_DAY": [12],
            "QUERY_COUNT": [10],
        })

        with patch("utils.shared_metrics_warehouse.run_query", return_value=mart_frame) as mock_run:
            result = load_shared_warehouse_heatmap(30, "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Fast warehouse summary")
        self.assertEqual(mock_run.call_count, 1)

        live_frame = pd.DataFrame({
            "WAREHOUSE_NAME": ["ALFA_WH"],
            "DAY_OF_WEEK": [1],
            "HOUR_OF_DAY": [12],
            "QUERY_COUNT": [10],
        })
        st.session_state.clear()
        st.session_state["active_company"] = "ALFA"
        st.session_state["global_environment"] = "ALL"
        with patch("utils.shared_metrics_warehouse.run_query", side_effect=[pd.DataFrame(), live_frame]) as mock_run:
            result = load_shared_warehouse_heatmap(45, "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Bounded live warehouse history")
        self.assertEqual(result.effective_days, 30)
        self.assertIn("capped at 30 days", result.message)
        live_sql = mock_run.call_args_list[1].args[0].upper()
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", live_sql)
        self.assertIn("DATEADD('DAY', -30", live_sql)

    def test_task_health_summary_returns_zero_row_when_unavailable(self):
        with patch(
            "utils.shared_metrics_tasks.build_task_health_sql",
            side_effect=ValueError("TASK_HISTORY unavailable"),
        ):
            result = load_shared_task_health_summary(object(), 7, "ALFA", section="Unit Test")

        self.assertFalse(result.available)
        self.assertEqual(int(result.data["TASK_RUNS"].iloc[0]), 0)
        self.assertIn("TASK_HISTORY", result.source)

    def test_task_history_detail_prefers_mart(self):
        frame = pd.DataFrame({
            "TASK_NAME": ["ALFA_TASK"],
            "STATE": ["SUCCEEDED"],
            "QUERY_ID": ["01a"],
        })

        with patch("utils.shared_metrics_tasks.run_query", return_value=frame) as mock_run:
            result = load_shared_task_history_detail(object(), 7, "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Fast task run summary")
        self.assertTrue(result.available)
        self.assertEqual(mock_run.call_count, 1)
        sql = mock_run.call_args.args[0].upper()
        self.assertIn("FACT_TASK_RUN", sql)

    def test_task_history_detail_live_fallback_after_empty_mart(self):
        live_frame = pd.DataFrame({
            "TASK_NAME": ["ALFA_TASK"],
            "STATE": ["FAILED"],
            "QUERY_ID": ["01b"],
        })

        with patch("utils.shared_metrics_tasks.run_query", side_effect=[pd.DataFrame(), live_frame]) as mock_run, patch(
            "utils.shared_metrics_tasks.build_task_history_sql",
            return_value="SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY",
        ) as mock_live_sql:
            result = load_shared_task_history_detail(
                object(),
                7,
                "ALFA",
                limit=500,
                section="Unit Test",
            )

        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY")
        self.assertIn("Fast task run summary returned no rows", result.message)
        self.assertEqual(mock_run.call_count, 2)
        mock_live_sql.assert_called_once()
        live_sql = mock_run.call_args_list[1].args[0].upper()
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY", live_sql)

    def test_mfa_coverage_uses_users_snapshot(self):
        frame = pd.DataFrame({
            "USER_NAME": ["ALFA_USER"],
            "HAS_PASSWORD": [True],
            "HAS_MFA": [False],
            "MFA_SOURCE": ["HAS_MFA"],
        })

        with patch("utils.shared_metrics_security.run_query", return_value=frame) as mock_run, patch(
            "utils.shared_metrics_security.filter_existing_columns",
            return_value=["HAS_MFA", "HAS_PASSWORD", "LAST_SUCCESS_LOGIN"],
        ):
            result = load_shared_mfa_coverage(object(), "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.USERS")
        sql = mock_run.call_args.args[0].upper()
        self.assertIn("AS HAS_MFA", sql)
        self.assertIn("AS MFA_SOURCE", sql)

    def test_shared_mfa_helpers_match_snowflake_user_variants(self):
        self.assertEqual(
            shared_mfa_count_expr({"HAS_MFA"}),
            "COUNT_IF(COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(has_mfa)), FALSE) = FALSE)",
        )
        self.assertEqual(
            shared_mfa_gap_predicate({"EXT_AUTHN_DUO"}),
            "AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.ext_authn_duo)), FALSE) = FALSE",
        )
        self.assertEqual(
            shared_mfa_gap_predicate({"HAS_MFA"}, alias="usr"),
            "AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(usr.has_mfa)), FALSE) = FALSE",
        )
        self.assertEqual(
            shared_mfa_proof_label(set()),
            "ACCOUNT_USAGE.USERS MFA signal unavailable",
        )

    def test_security_summary_builders_share_security_monitoring_sql(self):
        st.session_state["global_environment"] = "DEV_ALL"
        with patch(
            "utils.shared_metrics_security.filter_existing_columns",
            return_value=["HAS_MFA", "HAS_PASSWORD", "LAST_SUCCESS_LOGIN"],
        ):
            live_summary, live_exceptions = build_shared_security_summary_sql(object(), 14, "ALFA")
            mart_summary, mart_exceptions = build_shared_security_mart_brief_sql(object(), 14, "ALFA")

        combined_exceptions = "\n".join([live_exceptions, mart_exceptions]).upper()
        combined_summary = "\n".join([live_summary, mart_summary]).upper()
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY", live_summary.upper())
        self.assertIn("FACT_LOGIN_DAILY", mart_summary.upper())
        self.assertIn("FACT_GRANT_DAILY", mart_exceptions.upper())
        self.assertIn("GRANTS_TO_ROLES", combined_exceptions)
        self.assertIn("'OBJECT GRANT'", combined_exceptions)
        self.assertIn("GOR.TABLE_CATALOG AS DATABASE_NAME", combined_exceptions)
        self.assertIn("ALFA_EDW", combined_exceptions)
        self.assertIn("ROLE_SCOPE AS", mart_summary.upper())
        self.assertIn("HAS_EXCLUDED_ROLE", mart_summary.upper())
        self.assertIn("HAS_NON_EXCLUDED_ROLE", mart_summary.upper())
        self.assertEqual(mart_summary.upper().count("SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS"), 1)
        self.assertEqual(mart_exceptions.upper().count("SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS"), 1)
        self.assertNotIn("GRANTS_TO_ROLES", combined_summary)

    def test_security_mart_brief_role_scope_preserves_trexis_only_semantics(self):
        with patch(
            "utils.shared_metrics_security.filter_existing_columns",
            return_value=["HAS_MFA", "HAS_PASSWORD", "LAST_SUCCESS_LOGIN"],
        ):
            mart_summary, _ = build_shared_security_mart_brief_sql(object(), 14, "Trexis")

        sql = mart_summary.upper()
        self.assertIn("ROLE_SCOPE AS", sql)
        self.assertIn("HAS_COMPANY_ROLE", sql)
        self.assertIn("HAS_NON_COMPANY_ROLE", sql)
        self.assertIn("COALESCE(RS.HAS_COMPANY_ROLE, 0) = 1", sql)
        self.assertIn("COALESCE(RS.HAS_NON_COMPANY_ROLE, 0) = 0", sql)
        self.assertEqual(sql.count("SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS"), 1)

    def test_security_summary_builders_leave_all_company_unscoped(self):
        st.session_state["active_company"] = "ALFA"
        st.session_state["global_environment"] = "ALL"
        with patch(
            "utils.shared_metrics_security.filter_existing_columns",
            return_value=["HAS_MFA", "HAS_PASSWORD", "LAST_SUCCESS_LOGIN"],
        ):
            live_summary, live_exceptions = build_shared_security_summary_sql(object(), 14, "ALL")
            mart_summary, mart_exceptions = build_shared_security_mart_brief_sql(object(), 14, "ALL")

        for sql in (live_summary, live_exceptions, mart_summary, mart_exceptions):
            upper = sql.upper()
            self.assertNotIn("ROLE_SCOPE AS", upper)
            self.assertNotIn("HAS_EXCLUDED_ROLE", upper)
            self.assertNotIn("LH.COMPANY =", upper)
            self.assertNotIn("G.COMPANY =", upper)
            self.assertNotIn("ALFA_EDW", upper)
            self.assertNotIn("TRXS_EDW", upper)
            self.assertNotIn("WH_TRXS_LOAD", upper)

    def test_security_privileged_grant_review_builder_keeps_account_grants_unfiltered(self):
        sql = build_shared_security_privileged_grant_review_sql(30, "ALFA", "PROD")
        sql_upper = sql.upper()

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS", sql_upper)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES", sql_upper)
        self.assertIn("'NO DATABASE CONTEXT' AS ENVIRONMENT", sql_upper)
        self.assertIn("PRIVILEGED_ROLE_GRANTS", sql_upper)
        self.assertIn("OBJECT_PRIVILEGE_GRANTS", sql_upper)
        self.assertIn("ALFA_EDW_PRD", sql_upper)
        self.assertNotIn("GTU.TABLE_CATALOG", sql_upper)

    def test_grants_to_users_prefers_mart(self):
        frame = pd.DataFrame({
            "GRANTEE_NAME": ["ALFA_USER"],
            "ROLE": ["SYSADMIN"],
        })

        with patch("utils.shared_metrics_security.run_query", return_value=frame) as mock_run:
            result = load_shared_grants_to_users("ALFA", section="Unit Test")

        self.assertEqual(result.source, "Fast grant summary")
        self.assertEqual(mock_run.call_count, 1)

    def test_access_hygiene_sql_is_shared_and_account_scoped(self):
        sql = build_shared_access_hygiene_sql(
            object(),
            30,
            "ALFA",
            "DEV_ALL",
            user_columns=["HAS_PASSWORD", "EXT_AUTHN_DUO", "LAST_SUCCESS_LOGIN"],
        ).upper()

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.USERS", sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY", sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS", sql)
        self.assertIn("'NO DATABASE CONTEXT' AS DATABASE_CONTEXT", sql)
        self.assertIn("'NO DATABASE CONTEXT' AS ENVIRONMENT_SCOPE", sql)
        self.assertIn("'DEV_ALL' AS SELECTED_ENVIRONMENT", sql)
        self.assertNotIn("TABLE_CATALOG", sql)
        self.assertNotIn("DATABASE_NAME", sql)

    def test_access_hygiene_snapshot_labels_account_scope(self):
        frame = pd.DataFrame({
            "USER_NAME": ["ALFA_USER"],
            "DATABASE_CONTEXT": ["No Database Context"],
            "ENVIRONMENT_SCOPE": ["No Database Context"],
        })

        with patch("utils.shared_metrics_security.run_query", return_value=frame) as mock_run, patch(
            "utils.shared_metrics_security.filter_existing_columns",
            return_value=["HAS_MFA", "HAS_PASSWORD", "LAST_SUCCESS_LOGIN"],
        ):
            result = load_shared_access_hygiene_snapshot(
                object(),
                30,
                "ALFA",
                environment="DEV_ALL",
                section="Unit Test",
            )

        self.assertTrue(result.available)
        sql = mock_run.call_args.args[0].upper()
        self.assertIn("NO DATABASE CONTEXT", sql)
        self.assertIn("USERS, LOGIN_HISTORY, AND GRANTS_TO_USERS", sql)

    def test_recommendation_idle_warehouses_prefers_mart_and_reuses(self):
        frame = pd.DataFrame({
            "WAREHOUSE_NAME": ["ALFA_WH"],
            "IDLE_HOURS": [4],
            "IDLE_CREDITS": [2.5],
        })

        with patch("utils.shared_metrics_recommendations.run_query", return_value=frame) as mock_run:
            first = load_shared_recommendation_idle_warehouses("ALFA", section="Unit Test")
            second = load_shared_recommendation_idle_warehouses("ALFA", section="Unit Test")

        self.assertIs(first, second)
        self.assertEqual(first.source, "Fast recommendation summary")
        self.assertEqual(mock_run.call_count, 1)

    def test_recommendation_idle_warehouses_live_fallback_for_custom_lookback(self):
        frame = pd.DataFrame({
            "WAREHOUSE_NAME": ["ALFA_WH"],
            "IDLE_HOURS": [8],
            "IDLE_CREDITS": [4.0],
        })

        with patch("utils.shared_metrics_recommendations.run_query", return_value=frame) as mock_run:
            result = load_shared_recommendation_idle_warehouses(
                "ALFA",
                days=14,
                min_idle_credits=2.0,
                section="Unit Test",
            )

        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE warehouse/query history")
        sql = mock_run.call_args.args[0].upper()
        self.assertIn("WAREHOUSE_METERING_HISTORY", sql)
        self.assertIn("QUERY_HISTORY", sql)

    def test_recommendation_idle_warehouses_can_skip_live_fallback(self):
        with patch("utils.shared_metrics_recommendations.run_query") as mock_run:
            result = load_shared_recommendation_idle_warehouses(
                "ALFA",
                days=14,
                min_idle_credits=2.0,
                allow_live_fallback=False,
                section="Unit Test",
            )

        self.assertFalse(result.available)
        self.assertEqual(result.source, "Fast recommendation summary")
        self.assertEqual(mock_run.call_count, 0)

    def test_recommendation_spill_warehouses_live_fallback_uses_optional_size(self):
        frame = pd.DataFrame({
            "WAREHOUSE_NAME": ["ALFA_WH"],
            "WAREHOUSE_SIZE": ["MEDIUM"],
            "REMOTE_GB": [12.0],
        })

        with patch(
            "utils.shared_metrics_recommendations.run_query",
            side_effect=[pd.DataFrame(), frame],
        ) as mock_run, patch(
            "utils.shared_metrics_recommendations.filter_existing_columns",
            return_value=["WAREHOUSE_SIZE", "BYTES_SPILLED_TO_REMOTE_STORAGE"],
        ):
            result = load_shared_recommendation_spill_warehouses(object(), "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY")
        self.assertEqual(mock_run.call_count, 2)
        sql = mock_run.call_args_list[1].args[0].upper()
        self.assertIn("MAX(WAREHOUSE_SIZE)", sql)
        self.assertIn("BYTES_SPILLED_TO_REMOTE_STORAGE", sql)

    def test_recommendation_failed_tasks_live_fallback_wraps_task_summary(self):
        frame = pd.DataFrame({
            "TASK_NAME": ["LOAD_TASK"],
            "FAILURES": [5],
        })

        with patch(
            "utils.shared_metrics_recommendations.run_query",
            side_effect=[pd.DataFrame(), frame],
        ) as mock_run, patch(
            "utils.shared_metrics_recommendations.build_task_failure_summary_sql",
            return_value="SELECT 'LOAD_TASK' AS task_name, 5 AS failures",
        ):
            result = load_shared_recommendation_failed_tasks(object(), "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY")
        self.assertEqual(mock_run.call_count, 2)
        sql = mock_run.call_args_list[1].args[0].upper()
        self.assertIn("WITH FAILED_TASKS AS", sql)
        self.assertIn("WHERE FAILURES > 3", sql)

    def test_recommendation_query_failures_live_fallback_uses_global_filters(self):
        frame = pd.DataFrame({
            "WAREHOUSE_NAME": ["ALFA_WH"],
            "FAILURES": [12],
        })

        with patch(
            "utils.shared_metrics_recommendations.run_query",
            side_effect=[pd.DataFrame(), frame],
        ) as mock_run:
            result = load_shared_recommendation_query_failures(
                "ALFA",
                days=7,
                min_failures=10,
                section="Unit Test",
            )

        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY")
        sql = mock_run.call_args_list[1].args[0].upper()
        self.assertIn("FAILED_WITH_ERROR", sql)
        self.assertIn("HAVING FAILURES > 10", sql)

    def test_recommendation_storage_retention_uses_table_storage_metrics(self):
        frame = pd.DataFrame({
            "DATABASE_NAME": ["ALFA_DB"],
            "ACTIVE_TB": [1.0],
            "TIME_TRAVEL_TB": [0.5],
            "FAILSAFE_TB": [0.1],
        })

        with patch("utils.shared_metrics_recommendations.run_query", return_value=frame) as mock_run:
            result = load_shared_recommendation_storage_retention("ALFA", section="Unit Test")

        self.assertTrue(result.available)
        self.assertEqual(result.source, "Live: SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS")
        sql = mock_run.call_args.args[0].upper()
        self.assertIn("TABLE_STORAGE_METRICS", sql)
        self.assertIn("TIME_TRAVEL_TB >= 0.25", sql)

    def test_recommendation_clustering_cost_uses_shared_builder(self):
        frame = pd.DataFrame({
            "TABLE_NAME": ["ALFA_DB.PUBLIC.FACT"],
            "CLUSTERING_COST_USD": [42.0],
            "TB_RECLUSTERED": [1.5],
        })

        with patch("utils.shared_metrics_recommendations.run_query", return_value=frame) as mock_run:
            result = load_shared_recommendation_clustering_cost(
                "ALFA",
                days=7,
                credit_price=3.68,
                section="Unit Test",
            )

        self.assertEqual(result.source, "Live: SNOWFLAKE.ACCOUNT_USAGE.AUTOMATIC_CLUSTERING_HISTORY")
        sql = mock_run.call_args.args[0].upper()
        self.assertIn("AUTOMATIC_CLUSTERING_HISTORY", sql)
        self.assertIn("CLUSTERING_COST_USD", sql)

    def test_recommendation_repeated_queries_prefers_query_detail_mart(self):
        frame = pd.DataFrame({
            "QUERY_HASH": ["abc"],
            "RUNS": [60],
            "TOTAL_EXEC_HOURS": [3.0],
            "TB_SCANNED": [2.0],
            "HASH_COLUMN": ["QUERY_HASH"],
        })

        with patch("utils.shared_metrics_recommendations.run_query", return_value=frame) as mock_run:
            result = load_shared_recommendation_repeated_queries(object(), "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Fast query-detail summary")
        self.assertEqual(mock_run.call_count, 1)
        self.assertIn("FACT_QUERY_DETAIL_RECENT", mock_run.call_args.args[0].upper())

    def test_recommendation_repeated_queries_live_fallback_uses_parameterized_hash(self):
        frame = pd.DataFrame({
            "QUERY_HASH": ["abc"],
            "RUNS": [60],
            "TOTAL_EXEC_HOURS": [3.0],
            "HASH_COLUMN": ["QUERY_PARAMETERIZED_HASH"],
        })

        with patch(
            "utils.shared_metrics_recommendations.run_query",
            side_effect=[pd.DataFrame(), frame],
        ) as mock_run, patch(
            "utils.shared_metrics_recommendations.filter_existing_columns",
            return_value=["QUERY_PARAMETERIZED_HASH", "QUERY_HASH"],
        ):
            result = load_shared_recommendation_repeated_queries(object(), "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY")
        self.assertEqual(mock_run.call_count, 2)
        sql = mock_run.call_args_list[1].args[0].upper()
        self.assertIn("QUERY_PARAMETERIZED_HASH", sql)
        self.assertIn("TOTAL_EXEC_HOURS", sql)

    def test_recommendation_repeated_queries_can_skip_live_fallback(self):
        with patch("utils.shared_metrics_recommendations.run_query", return_value=pd.DataFrame()) as mock_run, patch(
            "utils.shared_metrics_recommendations.filter_existing_columns",
        ) as mock_cols:
            result = load_shared_recommendation_repeated_queries(
                object(),
                "ALFA",
                allow_live_fallback=False,
                section="Unit Test",
            )

        self.assertFalse(result.available)
        self.assertEqual(result.source, "Fast query-detail summary")
        self.assertEqual(mock_run.call_count, 1)
        mock_cols.assert_not_called()

    def test_duplicate_query_patterns_live_fallback_uses_cloud_credits_when_available(self):
        frame = pd.DataFrame({
            "QUERY_SIG": ["SELECT 1"],
            "EXECUTION_COUNT": [6],
            "USER_COUNT": [2],
            "CLOUD_CREDITS": [0.2],
        })

        with patch(
            "utils.shared_metrics_recommendations.run_query",
            side_effect=[pd.DataFrame(), frame],
        ) as mock_run, patch(
            "utils.shared_metrics_recommendations.filter_existing_columns",
            return_value=["CREDITS_USED_CLOUD_SERVICES"],
        ):
            result = load_shared_duplicate_query_patterns(object(), "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY")
        sql = mock_run.call_args_list[1].args[0].upper()
        self.assertIn("CREDITS_USED_CLOUD_SERVICES", sql)
        self.assertIn("HAVING COUNT(*) >= 5", sql)

    def test_warehouse_right_sizing_uses_optional_query_history_columns(self):
        frame = pd.DataFrame({
            "WAREHOUSE_NAME": ["ALFA_WH"],
            "WAREHOUSE_SIZE": ["MEDIUM"],
            "TOTAL_QUERIES": [100],
            "AVG_QUEUE_SEC": [1.5],
            "REMOTE_SPILL_GB": [10.0],
            "AVG_CACHE_PCT": [20.0],
            "TOTAL_CREDITS": [30.0],
        })

        with patch("utils.shared_metrics_warehouse.run_query", return_value=frame) as mock_run, patch(
            "utils.shared_metrics_warehouse.filter_existing_columns",
            return_value=[
                "WAREHOUSE_SIZE",
                "QUEUED_OVERLOAD_TIME",
                "BYTES_SPILLED_TO_REMOTE_STORAGE",
                "PERCENTAGE_SCANNED_FROM_CACHE",
            ],
        ):
            result = load_shared_warehouse_right_sizing(object(), "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Live: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY + WAREHOUSE_METERING_HISTORY")
        sql = mock_run.call_args.args[0].upper()
        self.assertIn("WAREHOUSE_METERING_HISTORY", sql)
        self.assertIn("BYTES_SPILLED_TO_REMOTE_STORAGE", sql)

    def test_procedure_inventory_live_fallback_uses_supplied_sql(self):
        frame = pd.DataFrame({"PROCEDURE_NAME": ["SP_LOAD"]})

        with patch(
            "utils.shared_metrics_procedures.run_query",
            side_effect=[pd.DataFrame(), frame],
        ) as mock_run:
            result = load_shared_procedure_inventory(
                "ALFA",
                live_sql="SELECT 'SP_LOAD' AS procedure_name",
                section="Unit Test",
            )

        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.PROCEDURES")
        self.assertEqual(mock_run.call_count, 2)

    def test_procedure_calls_prefers_mart(self):
        frame = pd.DataFrame({"PROCEDURE_NAME": ["SP_LOAD"], "CALL_COUNT": [3]})

        with patch("utils.shared_metrics_procedures.run_query", return_value=frame) as mock_run:
            result = load_shared_procedure_calls("ALFA", days=7, live_sql="SELECT 1", section="Unit Test")

        self.assertEqual(result.source, "Fast procedure run summary")
        self.assertEqual(mock_run.call_count, 1)

    def test_procedure_sla_live_sql_is_lazy_until_mart_empty(self):
        frame = pd.DataFrame({"PROCEDURE_NAME": ["SP_LOAD"], "ROOT_QUERY_ID": ["q1"]})
        calls = {"live": 0}

        def live_sql():
            calls["live"] += 1
            return "SELECT 'SP_LOAD' AS procedure_name"

        with patch("utils.shared_metrics_procedures.run_query", return_value=frame) as mock_run:
            result = load_shared_procedure_sla("ALFA", days=7, live_sql=live_sql, section="Unit Test")

        self.assertEqual(result.source, "Fast procedure SLA summary")
        self.assertEqual(mock_run.call_count, 1)
        self.assertEqual(calls["live"], 0)


if __name__ == "__main__":
    unittest.main()
