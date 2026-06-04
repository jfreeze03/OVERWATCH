from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils.admin import clamp_global_date_range  # noqa: E402
from utils.mart import load_mart_table  # noqa: E402


class GuardrailTests(unittest.TestCase):
    def test_clamp_global_date_range_respects_standard_and_admin_caps(self):
        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["_overwatch_current_role"] = "APP_READONLY"
            start, end, was_clamped, max_days = clamp_global_date_range(date(2026, 1, 1), date(2026, 2, 28))
            self.assertTrue(was_clamped)
            self.assertEqual(max_days, 35)
            self.assertEqual((end - start).days + 1, 35)

            st.session_state.clear()
            st.session_state["_overwatch_current_role"] = "ACCOUNTADMIN"
            start, end, was_clamped, max_days = clamp_global_date_range(date(2025, 1, 1), date(2025, 6, 1))
            self.assertTrue(was_clamped)
            self.assertEqual(max_days, 90)
            self.assertEqual((end - start).days + 1, 90)
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_load_mart_table_uses_run_query_and_marks_empty_unavailable(self):
        with patch("utils.mart.run_query", return_value=pd.DataFrame()) as mock_run:
            result = load_mart_table("MART_DBA_CONTROL_ROOM", "SELECT 1", source_label="DBA mart")

        self.assertFalse(result.available)
        self.assertTrue(result.data.empty)
        self.assertEqual(result.source, "DBA mart")
        self.assertEqual(result.message, "No mart rows returned.")
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs["tier"], "historical")
        self.assertEqual(kwargs["section"], "Mart")

    def test_usage_overview_and_heatmap_sources_use_mart_before_live(self):
        usage_text = (APP_ROOT / "sections" / "usage_overview.py").read_text(encoding="utf-8").upper()
        heatmap_text = (APP_ROOT / "sections" / "warehouse_health.py").read_text(encoding="utf-8").upper()
        task_text = (APP_ROOT / "sections" / "task_management.py").read_text(encoding="utf-8").upper()
        adoption_text = (APP_ROOT / "sections" / "adoption_analytics.py").read_text(encoding="utf-8").upper()

        self.assertIn("BUILD_MART_USAGE_STORAGE_SQL", usage_text)
        self.assertIn("FACT_STORAGE_DAILY", usage_text)
        self.assertIn("LIVE FALLBACK: SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY", usage_text)
        self.assertIn("BUILD_MART_WAREHOUSE_HEATMAP_SQL", heatmap_text)
        self.assertIn("WORKLOAD HEATMAP LIVE FALLBACK IS CAPPED AT 30 DAYS", heatmap_text)
        self.assertNotIn("SELECT * FROM {ETL_AUDIT_FQN}", task_text)
        self.assertIn("WHERE RUN_START >= DATEADD('DAY', -30, CURRENT_TIMESTAMP())", task_text)
        self.assertIn("ADOPTION ANALYTICS LIVE FALLBACK IS CAPPED AT 35 DAYS", adoption_text)

    def test_storage_monitor_live_fallback_is_capped(self):
        storage_text = (APP_ROOT / "sections" / "storage_monitor.py").read_text(encoding="utf-8")

        self.assertIn("LIVE_STORAGE_FALLBACK_MAX_DAYS = 90", storage_text)
        self.assertIn("fallback_days = min(int(stor_days), LIVE_STORAGE_FALLBACK_MAX_DAYS)", storage_text)
        self.assertIn("DATEADD('day', -{fallback_days}, CURRENT_DATE())", storage_text)
        self.assertIn('ttl_key=f"storage_trend_{company}_{fallback_days}"', storage_text)

    def test_app_clamps_global_date_widget_before_instantiation(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")

        self.assertIn('date_input_key = "_global_date_range_input"', app_text)
        self.assertIn("key=date_input_key", app_text)
        self.assertNotIn('st.session_state["_global_date_range_input"] =', app_text)
