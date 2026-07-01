from pathlib import Path
import sys
import unittest
from unittest.mock import patch

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

    def test_rendered_widget_state_updates_are_deferred_to_next_run(self):
        from runtime_state import (
            PENDING_WIDGET_STATE_UPDATES,
            apply_pending_widget_state_updates,
            mark_widget_key_rendered,
            reset_widget_render_tracking,
            set_state,
        )

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["cost_contract_workflow"] = "Cost Overview"
            reset_widget_render_tracking()
            mark_widget_key_rendered("cost_contract_workflow")

            set_state("cost_contract_workflow", "Cortex AI")

            self.assertEqual(st.session_state["cost_contract_workflow"], "Cost Overview")
            self.assertEqual(
                st.session_state[PENDING_WIDGET_STATE_UPDATES]["cost_contract_workflow"],
                "Cortex AI",
            )

            apply_pending_widget_state_updates()

            self.assertEqual(st.session_state["cost_contract_workflow"], "Cortex AI")
            self.assertNotIn(PENDING_WIDGET_STATE_UPDATES, st.session_state)
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_widget_instantiated_exception_queues_state_update(self):
        import runtime_state
        from runtime_state import PENDING_WIDGET_STATE_UPDATES, set_state

        class LockedWidgetState(dict):
            def __setitem__(self, key, value):
                if key == "security_posture_view":
                    raise RuntimeError(
                        "st.session_state.security_posture_view cannot be modified after the widget "
                        "with key security_posture_view is instantiated."
                    )
                return super().__setitem__(key, value)

        locked = LockedWidgetState({"security_posture_view": "Overview"})
        with patch.object(runtime_state.st, "session_state", locked):
            set_state("security_posture_view", "Security Alerts")

        self.assertEqual(locked["security_posture_view"], "Overview")
        self.assertEqual(
            locked[PENDING_WIDGET_STATE_UPDATES]["security_posture_view"],
            "Security Alerts",
        )

    def test_shell_uses_single_global_command_bar_path(self):
        shell_text = (APP_ROOT / "shell.py").read_text(encoding="utf-8")
        filters_text = (APP_ROOT / "filters.py").read_text(encoding="utf-8")

        self.assertIn("render_global_command_bar", shell_text)
        self.assertIn("render_global_date_range_control", filters_text)
        self.assertIn("widget_key_rendered_this_run(GLOBAL_DATE_RANGE_INPUT)", filters_text)
        after_widget_block = filters_text[filters_text.index("date_range = _normalize_date_range_value(date_range)") :]
        self.assertNotIn("set_state(GLOBAL_DATE_RANGE_INPUT", after_widget_block)

    def test_daily_sidebar_settings_mounts_setup_health_behind_admin_action(self):
        layout_text = (APP_ROOT / "layout.py").read_text(encoding="utf-8")

        settings_block = layout_text.split('sidebar_panel_toggle("Settings", "settings")', 1)[1]
        self.assertIn('"Open Setup Health"', settings_block)
        self.assertIn("admin_access_allowed", settings_block)
        self.assertIn("render_decision_setup_health_panel", settings_block)
        self.assertNotIn("Decision Summary Setup Health", settings_block)


if __name__ == "__main__":
    unittest.main()
