from pathlib import Path
import sys
import unittest

import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils.session import _capture_current_role  # noqa: E402


class SessionRoleTests(unittest.TestCase):
    def test_capture_current_role_populates_session_state(self):
        class Result:
            def collect(self):
                return [{"R": "accountadmin"}]

        class Session:
            def sql(self, statement):
                self.statement = statement
                return Result()

        st.session_state.pop("_overwatch_current_role", None)
        role = _capture_current_role(Session())
        self.assertEqual(role, "ACCOUNTADMIN")
        self.assertEqual(st.session_state["_overwatch_current_role"], "ACCOUNTADMIN")

    def test_capture_current_role_fails_open(self):
        class Session:
            def sql(self, _statement):
                raise RuntimeError("not available")

        st.session_state.pop("_overwatch_current_role", None)
        role = _capture_current_role(Session())
        self.assertEqual(role, "")
        self.assertEqual(st.session_state["_overwatch_current_role"], "")


if __name__ == "__main__":
    unittest.main()
