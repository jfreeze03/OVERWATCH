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
from runtime_state import CONNECTION_AVAILABLE, CONNECTION_UNAVAILABLE  # noqa: E402


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

    def _install_fake_snowflake_context(self, available: bool = True):
        context = types.ModuleType("snowflake.snowpark.context")

        def get_active_session():
            if not available:
                raise RuntimeError("no active session")
            return object()

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
        return patch.dict(sys.modules, modules)

    def test_first_probe_populates_process_cache_and_session_state(self):
        with self._install_fake_snowflake_context(available=True):
            available = access_control.probe_snowflake_available()

        self.assertTrue(available)
        self.assertTrue(access_control._SNOWFLAKE_AVAILABLE_PROCESS_CACHE)
        self.assertTrue(st.session_state[CONNECTION_AVAILABLE])
        self.assertFalse(st.session_state[CONNECTION_UNAVAILABLE])

    def test_concurrent_contention_does_not_stamp_false_availability(self):
        access_control._SNOWFLAKE_AVAILABLE_LOCK_WAIT_SECONDS = 0.001
        acquired = access_control._SNOWFLAKE_AVAILABLE_LOCK.acquire(blocking=False)
        self.assertTrue(acquired)
        try:
            available = access_control.probe_snowflake_available()
        finally:
            access_control._SNOWFLAKE_AVAILABLE_LOCK.release()

        self.assertFalse(available)
        self.assertIsNone(access_control._SNOWFLAKE_AVAILABLE_PROCESS_CACHE)
        self.assertNotIn(CONNECTION_AVAILABLE, st.session_state)
        self.assertNotIn(CONNECTION_UNAVAILABLE, st.session_state)

    def test_forced_probe_uses_session_and_sets_state(self):
        with patch.object(access_control, "get_session", return_value=object()):
            available = access_control.probe_snowflake_available(force=True)

        self.assertTrue(available)
        self.assertTrue(st.session_state[CONNECTION_AVAILABLE])
        self.assertFalse(st.session_state[CONNECTION_UNAVAILABLE])

    def test_non_forced_probe_uses_only_active_session_probe(self):
        with self._install_fake_snowflake_context(available=True):
            with patch.object(access_control, "get_session", side_effect=AssertionError("forced session probe only")):
                available = access_control.probe_snowflake_available()

        self.assertTrue(available)


if __name__ == "__main__":
    unittest.main()
