from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils.shared_metrics import (  # noqa: E402
    _storage_summary_from_trend,
    load_shared_access_hygiene_snapshot,
    load_shared_grants_to_users,
    load_shared_mfa_coverage,
    load_shared_query_history_rollup,
    load_shared_storage_trend,
    load_shared_task_health_summary,
    load_shared_usage_metering_kpis,
    load_shared_warehouse_daily_credits_by_warehouse,
    load_shared_warehouse_overview,
    load_shared_warehouse_pressure_summary,
    load_shared_warehouse_scaling_events,
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

    def test_storage_trend_reuses_session_result_for_same_scope(self):
        frame = pd.DataFrame({
            "USAGE_DATE": ["2026-06-15"],
            "STORAGE_GB": [1024.0],
            "FAILSAFE_GB": [0.0],
            "STAGE_GB": [0.0],
            "TOTAL_STORAGE_TB": [1.0],
        })

        with patch("utils.shared_metrics.run_query", return_value=frame) as mock_run:
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
            "utils.shared_metrics.run_query",
            side_effect=[pd.DataFrame(), live_frame],
        ) as mock_run:
            result = load_shared_storage_trend(120, "ALL", allow_live_fallback=True, section="Unit Test")

        self.assertEqual(mock_run.call_count, 2)
        self.assertEqual(result.effective_days, 90)
        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE storage views")
        live_sql = mock_run.call_args_list[1].args[0]
        self.assertIn("STAGE_STORAGE_USAGE_HISTORY", live_sql)
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

        with patch("utils.shared_metrics.run_query", return_value=frame) as mock_run:
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
            "utils.shared_metrics.run_query",
            side_effect=[pd.DataFrame(), live_frame],
        ) as mock_run, patch(
            "utils.compatibility.filter_existing_columns",
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

    def test_warehouse_daily_by_warehouse_reuses_session_result(self):
        frame = pd.DataFrame({
            "DAY": ["2026-06-15"],
            "WAREHOUSE_NAME": ["ALFA_WH"],
            "WAREHOUSE_SIZE": ["MEDIUM"],
            "DAILY_CREDITS": [8.5],
        })

        with patch(
            "utils.compatibility.filter_existing_columns",
            return_value=["WAREHOUSE_SIZE"],
        ), patch("utils.shared_metrics.run_query", return_value=frame) as mock_run:
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
            "utils.compatibility.filter_existing_columns",
            return_value=[],
        ), patch("utils.shared_metrics.run_query", return_value=frame) as mock_run:
            result = load_shared_warehouse_daily_credits_by_warehouse(object(), 7, "ALFA", section="Unit Test")

        self.assertTrue(result.available)
        live_sql = mock_run.call_args.args[0].upper()
        self.assertIn("NULL::VARCHAR AS WAREHOUSE_SIZE", live_sql)
        self.assertIn("WAREHOUSE_METERING_HISTORY", live_sql)

    def test_warehouse_overview_reuses_fast_summary_result(self):
        frame = pd.DataFrame({
            "WAREHOUSE_NAME": ["ALFA_WH"],
            "TOTAL_QUERIES": [100],
            "METERED_CREDITS": [10.0],
            "PRIOR_METERED_CREDITS": [7.0],
            "CREDIT_DELTA": [3.0],
        })

        with patch("utils.shared_metrics.run_query", return_value=frame) as mock_run:
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
            "utils.shared_metrics.run_query",
            side_effect=[pd.DataFrame(), live_frame],
        ) as mock_run, patch(
            "utils.compatibility.filter_existing_columns",
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

        with patch("utils.shared_metrics.run_query", return_value=frame) as mock_run:
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
            "utils.shared_metrics.run_query",
            side_effect=[pd.DataFrame(), live_frame],
        ) as mock_run, patch(
            "utils.compatibility.filter_existing_columns",
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
            "utils.shared_metrics.run_query",
            side_effect=[pd.DataFrame(), live_frame],
        ) as mock_run, patch(
            "utils.compatibility.filter_existing_columns",
            return_value=["ERROR_CODE", "QUEUED_OVERLOAD_TIME", "BYTES_SPILLED_TO_REMOTE_STORAGE"],
        ):
            result = load_shared_warehouse_pressure_summary(object(), 7, "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY")
        live_sql = mock_run.call_args_list[1].args[0].upper()
        self.assertIn("REMOTE_SPILL_GB", live_sql)
        self.assertIn("PRESSURE_WAREHOUSES", live_sql)

    def test_warehouse_scaling_events_prefers_mart(self):
        frame = pd.DataFrame({
            "WAREHOUSE_NAME": ["ALFA_WH"],
            "CREDITS_USED": [10.0],
        })

        with patch("utils.shared_metrics.run_query", return_value=frame) as mock_run:
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
            "utils.shared_metrics.run_query",
            side_effect=[pd.DataFrame(), live_frame],
        ) as mock_run, patch(
            "utils.compatibility.filter_existing_columns",
            side_effect=[["WAREHOUSE_SIZE"], ["CREDITS_USED_COMPUTE", "CREDITS_USED_CLOUD_SERVICES"]],
        ):
            result = load_shared_warehouse_scaling_events(object(), 7, "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY")
        live_sql = mock_run.call_args_list[1].args[0].upper()
        self.assertIn("LATEST_SIZE", live_sql)
        self.assertIn("CREDITS_USED_COMPUTE", live_sql)
        self.assertIn("CREDITS_USED_CLOUD_SERVICES", live_sql)

    def test_task_health_summary_returns_zero_row_when_unavailable(self):
        with patch(
            "utils.compatibility.build_task_health_sql",
            side_effect=ValueError("TASK_HISTORY unavailable"),
        ):
            result = load_shared_task_health_summary(object(), 7, "ALFA", section="Unit Test")

        self.assertFalse(result.available)
        self.assertEqual(int(result.data["TASK_RUNS"].iloc[0]), 0)
        self.assertIn("TASK_HISTORY", result.source)

    def test_mfa_coverage_uses_users_snapshot(self):
        frame = pd.DataFrame({
            "USER_NAME": ["ALFA_USER"],
            "HAS_PASSWORD": [True],
            "HAS_MFA": [False],
            "MFA_SOURCE": ["HAS_MFA"],
        })

        with patch("utils.shared_metrics.run_query", return_value=frame) as mock_run, patch(
            "utils.compatibility.filter_existing_columns",
            return_value=["HAS_MFA", "HAS_PASSWORD", "LAST_SUCCESS_LOGIN"],
        ):
            result = load_shared_mfa_coverage(object(), "ALFA", section="Unit Test")

        self.assertEqual(result.source, "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.USERS")
        sql = mock_run.call_args.args[0].upper()
        self.assertIn("AS HAS_MFA", sql)
        self.assertIn("AS MFA_SOURCE", sql)

    def test_grants_to_users_prefers_mart(self):
        frame = pd.DataFrame({
            "GRANTEE_NAME": ["ALFA_USER"],
            "ROLE": ["SYSADMIN"],
        })

        with patch("utils.shared_metrics.run_query", return_value=frame) as mock_run:
            result = load_shared_grants_to_users("ALFA", section="Unit Test")

        self.assertEqual(result.source, "Fast grant summary")
        self.assertEqual(mock_run.call_count, 1)

    def test_access_hygiene_snapshot_labels_account_scope(self):
        frame = pd.DataFrame({
            "USER_NAME": ["ALFA_USER"],
            "DATABASE_CONTEXT": ["No Database Context"],
            "ENVIRONMENT_SCOPE": ["No Database Context"],
        })

        with patch("utils.shared_metrics.run_query", return_value=frame) as mock_run, patch(
            "utils.compatibility.filter_existing_columns",
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


if __name__ == "__main__":
    unittest.main()
