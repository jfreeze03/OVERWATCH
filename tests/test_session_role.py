from pathlib import Path
import sys
import unittest

import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils.session import (  # noqa: E402
    _capture_current_role,
    apply_overwatch_query_tag,
    build_overwatch_query_tag,
)


class SessionRoleTests(unittest.TestCase):
    def test_capture_current_role_populates_session_state(self):
        class Result:
            def collect(self):
                return [{"R": "accountadmin"}]

        class Session:
            def sql(self, statement):
                self.statement = statement
                return Result()

        previous = dict(st.session_state)
        try:
            st.session_state.pop("_overwatch_current_role", None)
            st.session_state.pop("_overwatch_current_role_source", None)
            role = _capture_current_role(Session())
            self.assertEqual(role, "ACCOUNTADMIN")
            self.assertEqual(st.session_state["_overwatch_current_role"], "ACCOUNTADMIN")
            self.assertEqual(st.session_state["_overwatch_current_role_source"], "session")
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_capture_current_role_fails_open(self):
        class Session:
            def sql(self, _statement):
                raise RuntimeError("not available")

        previous = dict(st.session_state)
        try:
            st.session_state.pop("_overwatch_current_role", None)
            st.session_state.pop("_overwatch_current_role_source", None)
            role = _capture_current_role(Session())
            self.assertEqual(role, "")
            self.assertEqual(st.session_state["_overwatch_current_role"], "")
            self.assertEqual(st.session_state["_overwatch_current_role_source"], "unknown")
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_build_overwatch_query_tag_includes_active_section_scope(self):
        st.session_state["_detailed_query_tags_enabled"] = True
        st.session_state["_overwatch_active_section"] = "Cost & Contract"
        st.session_state["active_company"] = "ALFA"
        st.session_state["global_environment"] = "PROD"

        tag = build_overwatch_query_tag(tier="recent")

        self.assertTrue(tag.startswith("OVERWATCH|"))
        self.assertIn("section=Cost_&_Contract", tag)
        self.assertIn("company=ALFA", tag)
        self.assertIn("env=PROD", tag)
        self.assertIn("tier=recent", tag)

    def test_apply_overwatch_query_tag_sets_session_state_without_alter_statement(self):
        class Result:
            def collect(self):
                return []

        class Session:
            def __init__(self):
                self.statements = []

            def sql(self, statement):
                self.statements.append(statement)
                return Result()

        st.session_state["_detailed_query_tags_enabled"] = True
        st.session_state.pop("_overwatch_active_query_tag", None)
        st.session_state.pop("_overwatch_active_query_tag_section", None)
        session = Session()

        apply_overwatch_query_tag(session, "OVERWATCH|section=DBA_Control_Room|company=ALFA")

        self.assertEqual(session.statements, [])
        self.assertEqual(st.session_state["_overwatch_active_query_tag"], "OVERWATCH|section=DBA_Control_Room|company=ALFA")
        self.assertEqual(st.session_state["_overwatch_active_query_tag_section"], "DBA_Control_Room")


if __name__ == "__main__":
    unittest.main()
