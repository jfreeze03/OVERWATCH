from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

import access_control  # noqa: E402
from runtime_state import (  # noqa: E402
    ACCESS_GATE_STATE,
    ADMIN_CONNECTION_TEST_COUNT,
    CONNECTION_AVAILABLE,
    CONNECTION_UNAVAILABLE,
    get_runtime_event_ledger,
)


class AccessControlProbeTests(unittest.TestCase):
    def setUp(self):
        self.previous_state = dict(st.session_state)
        self.previous_wait = access_control._SNOWFLAKE_AVAILABLE_LOCK_WAIT_SECONDS
        st.session_state.clear()
        access_control._SNOWFLAKE_AVAILABLE_PROCESS_CACHE = None

    def tearDown(self):
        if access_control._SNOWFLAKE_AVAILABLE_LOCK.locked():
            try:
                access_control._SNOWFLAKE_AVAILABLE_LOCK.release()
            except RuntimeError:
                pass
        access_control._SNOWFLAKE_AVAILABLE_PROCESS_CACHE = None
        access_control._SNOWFLAKE_AVAILABLE_LOCK_WAIT_SECONDS = self.previous_wait
        st.session_state.clear()
        st.session_state.update(self.previous_state)

    def test_non_forced_probe_is_cached_only_and_does_not_stamp_false_state(self):
        with patch.object(access_control, "_declared_snowflake_connection_configured", return_value=False):
            available = access_control.probe_snowflake_available()

        self.assertFalse(available)
        self.assertIsNone(access_control._SNOWFLAKE_AVAILABLE_PROCESS_CACHE)
        self.assertNotIn(CONNECTION_AVAILABLE, st.session_state)
        self.assertNotIn(CONNECTION_UNAVAILABLE, st.session_state)
        self.assertEqual(st.session_state[ACCESS_GATE_STATE], "unknown_unprobed")

    def test_cached_probe_populates_state_from_process_cache_without_session(self):
        access_control._SNOWFLAKE_AVAILABLE_PROCESS_CACHE = True

        available = access_control.probe_snowflake_available()

        self.assertTrue(available)
        self.assertTrue(st.session_state[CONNECTION_AVAILABLE])
        self.assertFalse(st.session_state[CONNECTION_UNAVAILABLE])
        self.assertEqual(st.session_state[ACCESS_GATE_STATE], "process_cached_available")

    def test_forced_probe_uses_session_and_sets_state(self):
        with patch("utils.session.get_session", return_value=object()):
            available = access_control.probe_snowflake_available(force=True)

        self.assertTrue(available)
        self.assertTrue(st.session_state[CONNECTION_AVAILABLE])
        self.assertFalse(st.session_state[CONNECTION_UNAVAILABLE])
        self.assertEqual(st.session_state[ADMIN_CONNECTION_TEST_COUNT], 1)
        self.assertEqual(st.session_state[ACCESS_GATE_STATE], "admin_connection_test_available")
        events = get_runtime_event_ledger()
        admin_events = [event for event in events if event["event_type"] == "explicit_admin_connection_test"]
        self.assertEqual(len(admin_events), 1)
        self.assertEqual(admin_events[0]["boundary"], "explicit_connection_test")
        self.assertEqual(admin_events[0]["product_boundary"], "admin_setup_health")
        self.assertEqual(admin_events[0]["execution_boundary"], "explicit_connection_test")
        self.assertEqual(admin_events[0]["source_module"], "access_control.explicit_admin_connection_test")
        self.assertTrue(admin_events[0]["setup_live_validation_marker_present"])
        self.assertFalse(admin_events[0]["raw_sql_included"])

    def test_non_forced_probe_never_calls_get_active_session_or_get_session(self):
        context = types.ModuleType("snowflake.snowpark.context")

        def get_active_session():
            raise AssertionError("no shell active-session probe")

        context.get_active_session = get_active_session
        snowpark = types.ModuleType("snowflake.snowpark")
        snowpark.context = context
        snowflake = types.ModuleType("snowflake")
        snowflake.snowpark = snowpark
        modules = {
            "snowflake": snowflake,
            "snowflake.snowpark": snowpark,
            "snowflake.snowpark.context": context,
        }
        with patch.dict(sys.modules, modules):
            with patch.object(access_control, "_declared_snowflake_connection_configured", return_value=False):
                with patch("utils.session.get_session", side_effect=AssertionError("forced admin probe only")):
                    available = access_control.probe_snowflake_available()

        self.assertFalse(available)


if __name__ == "__main__":
    unittest.main()
