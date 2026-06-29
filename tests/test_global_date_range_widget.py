from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class GlobalDateRangeWidgetTests(unittest.TestCase):
    def test_command_bar_date_range_normalizes_list_before_widget_creation(self):
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

            self.assertEqual(st.session_state[GLOBAL_START_DATE], date(2026, 6, 21))
            self.assertEqual(st.session_state[GLOBAL_END_DATE], date(2026, 6, 28))
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_partial_tuple_does_not_update_canonical_dates(self):
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

            self.assertEqual(st.session_state[GLOBAL_START_DATE], date(2026, 6, 21))
            self.assertEqual(st.session_state[GLOBAL_END_DATE], date(2026, 6, 28))
        finally:
            st.session_state.clear()
            st.session_state.update(previous)


if __name__ == "__main__":
    unittest.main()
