from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils.idle import pause_queries, queries_paused, resume_queries  # noqa: E402
from utils.query import run_query  # noqa: E402


class IdleGuardTests(unittest.TestCase):
    def setUp(self):
        self.previous_state = dict(st.session_state)
        st.session_state.clear()

    def tearDown(self):
        st.session_state.clear()
        st.session_state.update(self.previous_state)

    def test_idle_timeout_pauses_queries_and_disables_live_auto_refresh(self):
        st.session_state["overwatch_idle_timeout_seconds"] = 60
        st.session_state["_overwatch_last_operator_activity_ts"] = 100.0
        st.session_state["lm_auto"] = True

        self.assertTrue(queries_paused(now=161.0))
        self.assertTrue(st.session_state["_overwatch_queries_paused"])
        self.assertFalse(st.session_state["lm_auto"])

    def test_resume_queries_marks_activity_and_keeps_live_auto_refresh_off(self):
        st.session_state["lm_auto"] = True
        pause_queries(now=100.0)

        resume_queries(now=150.0)

        self.assertFalse(st.session_state["_overwatch_queries_paused"])
        self.assertEqual(st.session_state["_overwatch_last_operator_activity_ts"], 150.0)
        self.assertFalse(st.session_state["lm_auto"])

    def test_run_query_returns_empty_when_idle_guard_is_paused(self):
        pause_queries(now=100.0)

        with patch("utils.query.get_session", side_effect=AssertionError("should not connect")):
            result = run_query("SELECT 1", ttl_key="idle_guard_test", tier="live", section="Unit Test")

        self.assertTrue(result.empty)


if __name__ == "__main__":
    unittest.main()
