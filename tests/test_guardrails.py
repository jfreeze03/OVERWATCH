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
import utils.query as query_utils  # noqa: E402


class GuardrailTests(unittest.TestCase):
    def test_clamp_global_date_range_uses_admin_cap(self):
        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["_overwatch_current_role"] = "APP_READONLY"
            start, end, was_clamped, max_days = clamp_global_date_range(date(2026, 1, 1), date(2026, 2, 28))
            self.assertFalse(was_clamped)
            self.assertEqual(max_days, 90)
            self.assertEqual((end - start).days + 1, 59)

            st.session_state.clear()
            st.session_state["_overwatch_current_role"] = "SNOW_ACCOUNTADMINS"
            start, end, was_clamped, max_days = clamp_global_date_range(date(2025, 1, 1), date(2025, 6, 1))
            self.assertTrue(was_clamped)
            self.assertEqual(max_days, 90)
            self.assertEqual((end - start).days + 1, 90)
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_load_mart_table_uses_run_query_and_marks_empty_unavailable(self):
        with patch("utils.mart_loader.run_query", return_value=pd.DataFrame()) as mock_run:
            result = load_mart_table("MART_DBA_CONTROL_ROOM", "SELECT 1", source_label="DBA mart")

        self.assertFalse(result.available)
        self.assertTrue(result.data.empty)
        self.assertEqual(result.source, "DBA mart")
        self.assertEqual(result.message, "No summary rows returned.")
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs["tier"], "command_summary")
        self.assertEqual(kwargs["section"], "Mart")

    def test_usage_overview_and_heatmap_sources_use_mart_before_live(self):
        cost_text = "\n".join(
            path.read_text(encoding="utf-8").upper()
            for path in [
                APP_ROOT / "sections" / "cost_center.py",
                APP_ROOT / "sections" / "cost_center_explain_view.py",
                APP_ROOT / "sections" / "cost_center_burn_view.py",
            ]
        )
        shared_metric_surface = "\n".join(
            path.read_text(encoding="utf-8").upper()
            for path in sorted((APP_ROOT / "utils").glob("shared_metrics*.py"))
        )
        heatmap_text = "\n".join(
            path.read_text(encoding="utf-8").upper()
            for path in [
                APP_ROOT / "sections" / "warehouse_health.py",
                APP_ROOT / "sections" / "warehouse_health_view_overview.py",
                APP_ROOT / "sections" / "warehouse_health_view_efficiency.py",
                APP_ROOT / "sections" / "warehouse_health_view_spill.py",
                APP_ROOT / "sections" / "warehouse_health_view_heatmap.py",
                APP_ROOT / "sections" / "warehouse_health_view_advisor.py",
            ]
        )
        task_text = "\n".join(
            path.read_text(encoding="utf-8").upper()
            for path in [
                APP_ROOT / "sections" / "task_management.py",
                APP_ROOT / "sections" / "task_management_etl_audit_view.py",
            ]
        )
        self.assertIn("LOAD_SHARED_BILL_METERING_SUMMARY", cost_text)
        self.assertIn("LOAD_SHARED_BILL_WAREHOUSE_DELTA", cost_text)
        self.assertIn("LOAD_SHARED_WAREHOUSE_DAILY_CREDITS_BY_WAREHOUSE", cost_text)
        self.assertIn("LOAD_SHARED_WAREHOUSE_OVERVIEW", heatmap_text)
        self.assertIn("LOAD_SHARED_WAREHOUSE_SCALING_EVENTS", heatmap_text)
        self.assertIn("LOAD_SHARED_WAREHOUSE_HEATMAP", heatmap_text)
        self.assertIn("BUILD_MART_USAGE_STORAGE_SQL", shared_metric_surface)
        self.assertIn("BUILD_MART_USAGE_METERING_SQL", shared_metric_surface)
        self.assertIn("BUILD_MART_USAGE_OVERVIEW_SQL", shared_metric_surface)
        self.assertIn("BUILD_MART_USAGE_PRESSURE_SQL", shared_metric_surface)
        self.assertIn("BUILD_MART_WAREHOUSE_OVERVIEW_SQL", shared_metric_surface)
        self.assertIn("BUILD_MART_WAREHOUSE_SCALING_SQL", shared_metric_surface)
        self.assertIn("BUILD_MART_WAREHOUSE_HEATMAP_SQL", shared_metric_surface)
        self.assertIn("LOAD_SHARED_MFA_COVERAGE", shared_metric_surface)
        self.assertIn("LOAD_SHARED_GRANTS_TO_USERS", shared_metric_surface)
        self.assertIn("LIVE FALLBACK: SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY", shared_metric_surface)
        self.assertIn("WORKLOAD HEATMAP LIVE FALLBACK IS CAPPED AT 30 DAYS", shared_metric_surface)
        self.assertNotIn("SELECT * FROM {ETL_AUDIT_FQN}", task_text)
        self.assertIn("WHERE RUN_START >= DATEADD('DAY', -30, CURRENT_TIMESTAMP())", task_text)

    def test_storage_monitor_live_fallback_is_capped(self):
        storage_text = (APP_ROOT / "sections" / "storage_monitor.py").read_text(encoding="utf-8")
        shared_metrics_storage_text = (APP_ROOT / "utils" / "shared_metrics_storage.py").read_text(encoding="utf-8")

        self.assertIn("LIVE_STORAGE_FALLBACK_MAX_DAYS = 90", storage_text)
        self.assertIn("fallback_days = min(int(stor_days), LIVE_STORAGE_FALLBACK_MAX_DAYS)", storage_text)
        self.assertIn("DATEADD('day', -{fallback_days}, CURRENT_DATE())", shared_metrics_storage_text)
        self.assertIn('"shared_storage_trend_live", fallback_days', shared_metrics_storage_text)

    def test_app_clamps_global_date_widget_before_instantiation(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        filters_text = (APP_ROOT / "filters.py").read_text(encoding="utf-8")

        self.assertIn("from shell import render_app", app_text)
        self.assertIn("GLOBAL_DATE_RANGE_INPUT", filters_text)
        self.assertIn("key=GLOBAL_DATE_RANGE_INPUT", filters_text)
        date_input_block = filters_text[
            filters_text.index("date_range = st.date_input"):
            filters_text.index("date_range = _normalize_date_range_value(date_range)")
        ]
        self.assertNotIn("value=", date_input_block)
        after_widget_block = filters_text[filters_text.index("date_range = _normalize_date_range_value(date_range)") :]
        self.assertNotIn("set_state(GLOBAL_DATE_RANGE_INPUT", after_widget_block)
        self.assertIn("try:\n    from utils.admin import clamp_global_date_range", filters_text)
        self.assertIn("Fallback for Snowflake stages that refresh filters before utils.admin", filters_text)
        self.assertNotIn("render_admin_mode_control", app_text + filters_text)
        self.assertNotIn('st.session_state["_global_date_range_input"] =', app_text + filters_text)

    def test_global_date_range_preserves_partial_selection(self):
        import filters
        from runtime_state import GLOBAL_DATE_RANGE_INPUT, GLOBAL_END_DATE, GLOBAL_START_DATE

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state[GLOBAL_START_DATE] = date(2026, 6, 21)
            st.session_state[GLOBAL_END_DATE] = date(2026, 6, 28)
            st.session_state[GLOBAL_DATE_RANGE_INPUT] = (date(2026, 6, 25),)

            with patch.object(filters.st, "date_input", return_value=(date(2026, 6, 25),)):
                filters.render_global_date_range_control(label="Window")

            self.assertEqual(st.session_state[GLOBAL_DATE_RANGE_INPUT], (date(2026, 6, 25),))
            self.assertEqual(st.session_state[GLOBAL_START_DATE], date(2026, 6, 21))
            self.assertEqual(st.session_state[GLOBAL_END_DATE], date(2026, 6, 28))

            with patch.object(filters.st, "date_input", return_value=(date(2026, 6, 20), date(2026, 6, 27))):
                filters.render_global_date_range_control(label="Window")

            self.assertEqual(st.session_state[GLOBAL_START_DATE], date(2026, 6, 20))
            self.assertEqual(st.session_state[GLOBAL_END_DATE], date(2026, 6, 27))
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_global_date_range_does_not_mutate_widget_key_after_instantiation(self):
        import filters
        from runtime_state import GLOBAL_DATE_RANGE_INPUT, GLOBAL_END_DATE, GLOBAL_START_DATE

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state[GLOBAL_START_DATE] = date(2026, 6, 21)
            st.session_state[GLOBAL_END_DATE] = date(2026, 6, 28)
            widget_created = False
            post_widget_writes: list[tuple[str, object]] = []
            original_set_state = filters.set_state

            def fake_date_input(*args, **kwargs):
                nonlocal widget_created
                widget_created = True
                return (date(2026, 1, 1), date(2026, 6, 28))

            def tracked_set_state(key, value):
                if widget_created and key == GLOBAL_DATE_RANGE_INPUT:
                    post_widget_writes.append((key, value))
                return original_set_state(key, value)

            with patch.object(filters.st, "date_input", side_effect=fake_date_input), patch.object(
                filters, "set_state", side_effect=tracked_set_state
            ):
                filters.render_global_date_range_control(label="Window")

            self.assertEqual(post_widget_writes, [])
            self.assertEqual(st.session_state[GLOBAL_START_DATE], date(2026, 6, 28) - filters.timedelta(days=89))
            self.assertEqual(st.session_state[GLOBAL_END_DATE], date(2026, 6, 28))
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_global_date_range_normalizes_list_before_widget_creation(self):
        import filters
        from runtime_state import GLOBAL_DATE_RANGE_INPUT, GLOBAL_END_DATE, GLOBAL_START_DATE

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state[GLOBAL_START_DATE] = date(2026, 6, 21)
            st.session_state[GLOBAL_END_DATE] = date(2026, 6, 28)
            st.session_state[GLOBAL_DATE_RANGE_INPUT] = [date(2026, 6, 21), date(2026, 6, 28)]

            def fake_date_input(*args, **kwargs):
                self.assertIsInstance(st.session_state[GLOBAL_DATE_RANGE_INPUT], tuple)
                return st.session_state[GLOBAL_DATE_RANGE_INPUT]

            with patch.object(filters.st, "date_input", side_effect=fake_date_input):
                filters.render_global_date_range_control(label="Window")

            self.assertEqual(st.session_state[GLOBAL_DATE_RANGE_INPUT], (date(2026, 6, 21), date(2026, 6, 28)))
            self.assertEqual(st.session_state[GLOBAL_START_DATE], date(2026, 6, 21))
            self.assertEqual(st.session_state[GLOBAL_END_DATE], date(2026, 6, 28))
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_global_date_range_duplicate_render_is_idempotent(self):
        import filters
        from runtime_state import (
            GLOBAL_DATE_RANGE_INPUT,
            GLOBAL_END_DATE,
            GLOBAL_START_DATE,
            reset_widget_render_tracking,
        )

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            reset_widget_render_tracking()
            st.session_state[GLOBAL_START_DATE] = date(2026, 6, 21)
            st.session_state[GLOBAL_END_DATE] = date(2026, 6, 28)
            st.session_state[GLOBAL_DATE_RANGE_INPUT] = [date(2026, 6, 21), date(2026, 6, 28)]

            with patch.object(filters.st, "date_input", return_value=(date(2026, 6, 21), date(2026, 6, 28))) as widget:
                filters.render_global_date_range_control(label="Window")
                filters.render_global_date_range_control(label="Window")

            self.assertEqual(widget.call_count, 1)
            self.assertEqual(st.session_state[GLOBAL_START_DATE], date(2026, 6, 21))
            self.assertEqual(st.session_state[GLOBAL_END_DATE], date(2026, 6, 28))
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_theme_picker_avoids_session_state_widget_key_conflict(self):
        import theme

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["theme_picker_radio"] = "terminal"

            with patch.object(theme.st, "selectbox", return_value="terminal") as selectbox:
                theme.render_theme_picker()

            _, kwargs = selectbox.call_args
            self.assertNotIn("key", kwargs)
            self.assertEqual(st.session_state.get("theme_picker_radio"), "terminal")
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_query_budget_assertion_is_sanitized_for_daily_ui(self):
        import shell

        message = shell._format_section_error(
            AssertionError("actual_snowflake_executions 7 exceeded budget 1; SELECT * FROM secret")
        )

        self.assertIn("live query budget", message)
        self.assertNotIn("actual_snowflake_executions", message)
        self.assertNotIn("SELECT", message)
        self.assertNotIn("Traceback", message)

    def test_invalid_identifier_message_hides_internal_column_name(self):
        message = query_utils.format_snowflake_error(
            RuntimeError("SQL compilation error: invalid identifier 'TARGET_QUERY_ID'")
        )

        self.assertIn("Historical detail is unavailable", message)
        self.assertNotIn("TARGET_QUERY_ID", message)
        self.assertNotIn("invalid identifier", message.lower())

    def test_query_guardrail_messages_are_hash_deduped(self):
        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            with patch("utils.query.st.warning") as warning:
                query_utils._show_query_warning("Cost guard", RuntimeError("boom"))
                query_utils._show_query_warning("Cost guard", RuntimeError("boom"))
            warning.assert_called_once()

            with patch("utils.query.st.warning") as warning:
                query_utils._show_result_guard_message("Large result guard")
                query_utils._show_result_guard_message("Large result guard")
            warning.assert_called_once()
        finally:
            st.session_state.clear()
            st.session_state.update(previous)
