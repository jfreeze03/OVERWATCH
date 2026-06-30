from pathlib import Path
import sys
import unittest

import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class ShellRenderingTests(unittest.TestCase):
    def test_widget_tracking_resets_once_per_script_run(self):
        from runtime_state import (
            GLOBAL_DATE_RANGE_INPUT,
            WIDGET_KEYS_RENDERED_THIS_RUN,
            mark_widget_key_rendered,
            reset_widget_render_tracking,
            widget_key_rendered_this_run,
        )

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            mark_widget_key_rendered(GLOBAL_DATE_RANGE_INPUT)
            self.assertTrue(widget_key_rendered_this_run(GLOBAL_DATE_RANGE_INPUT))

            reset_widget_render_tracking()

            self.assertFalse(widget_key_rendered_this_run(GLOBAL_DATE_RANGE_INPUT))
            self.assertEqual(st.session_state[WIDGET_KEYS_RENDERED_THIS_RUN], [])
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_shell_uses_single_global_command_bar_path(self):
        shell_text = (APP_ROOT / "shell.py").read_text(encoding="utf-8")
        filters_text = (APP_ROOT / "filters.py").read_text(encoding="utf-8")

        self.assertIn("render_global_command_bar", shell_text)
        self.assertIn("render_global_date_range_control", filters_text)
        self.assertIn("widget_key_rendered_this_run(GLOBAL_DATE_RANGE_INPUT)", filters_text)
        after_widget_block = filters_text[filters_text.index("date_range = _normalize_date_range_value(date_range)") :]
        self.assertNotIn("set_state(GLOBAL_DATE_RANGE_INPUT", after_widget_block)

    def test_daily_sidebar_settings_do_not_render_setup_health_panel(self):
        layout_text = (APP_ROOT / "layout.py").read_text(encoding="utf-8")

        self.assertNotIn("render_decision_setup_health_panel", layout_text)
        settings_block = layout_text.split('sidebar_panel_toggle("Settings", "settings")', 1)[1]
        self.assertNotIn("Decision Summary Setup Health", settings_block)


if __name__ == "__main__":
    unittest.main()
