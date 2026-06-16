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
    load_shared_storage_trend,
    load_shared_usage_metering_kpis,
    load_shared_warehouse_daily_credits_by_warehouse,
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


if __name__ == "__main__":
    unittest.main()
