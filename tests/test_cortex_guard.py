from pathlib import Path
import sys
import unittest

import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

import utils.cortex as cortex  # noqa: E402


class _DummySession:
    def __init__(self, value: str = "ok"):
        self.value = value
        self.sql_text = ""
        self.statements = []

    def sql(self, sql_text: str):
        self.sql_text = sql_text
        self.statements.append(sql_text)
        return self

    def collect(self):
        return [{"ANSWER": self.value}]


class CortexGuardTests(unittest.TestCase):
    def setUp(self):
        cortex.clear_cortex_usage()
        st.session_state.pop("_overwatch_active_query_tag", None)
        st.session_state.pop("_overwatch_active_query_tag_section", None)

    def tearDown(self):
        cortex.clear_cortex_usage()
        st.session_state.pop("_overwatch_active_query_tag", None)
        st.session_state.pop("_overwatch_active_query_tag_section", None)

    def test_cortex_completion_uses_safe_literal_and_alias(self):
        session = _DummySession("diagnosis")
        answer = cortex.run_cortex_completion(
            session,
            "query text with 'quoted' value",
            alias="answer",
            cooldown_seconds=0,
            daily_call_limit=0,
        )

        self.assertEqual(answer, "diagnosis")
        self.assertIn("SNOWFLAKE.CORTEX.COMPLETE", session.sql_text)
        self.assertIn("mistral-large2", session.sql_text)
        self.assertIn("''quoted''", session.sql_text)
        self.assertIn(" AS ANSWER", session.sql_text)
        self.assertTrue(session.statements[0].startswith("ALTER SESSION SET QUERY_TAG"))
        self.assertIn("tier=cortex", session.statements[0])

    def test_cortex_completion_sanitizes_unsafe_alias(self):
        session = _DummySession("diagnosis")
        answer = cortex.run_cortex_completion(
            session,
            "query text",
            alias="1 bad alias; drop table x",
            cooldown_seconds=0,
            daily_call_limit=0,
        )

        self.assertEqual(answer, "")
        self.assertIn(" AS CORTEX_1_BAD_ALIAS_DROP_TABLE_X", session.sql_text)
        self.assertNotIn("; drop", session.sql_text.lower())

    def test_cortex_completion_throttles_repeated_manual_calls(self):
        cortex.reserve_cortex_completion(cooldown_seconds=30, daily_call_limit=0)

        with self.assertRaises(cortex.CortexRateLimitError):
            cortex.reserve_cortex_completion(cooldown_seconds=30, daily_call_limit=0)

    def test_cortex_completion_enforces_session_daily_limit(self):
        cortex.reserve_cortex_completion(
            feature="query_analysis_ai_diagnosis",
            cooldown_seconds=0,
            daily_call_limit=1,
        )

        with self.assertRaises(cortex.CortexRateLimitError):
            cortex.reserve_cortex_completion(
                feature="query_analysis_ai_diagnosis",
                cooldown_seconds=0,
                daily_call_limit=1,
            )

    def test_cortex_completion_records_usage_without_prompt_text(self):
        session = _DummySession("diagnosis")
        cortex.run_cortex_completion(
            session,
            "sensitive query text with account details",
            alias="answer",
            feature="query_analysis_ai_diagnosis",
            cooldown_seconds=0,
            daily_call_limit=3,
        )

        usage = cortex.get_cortex_usage_summary()
        telemetry = cortex.get_cortex_telemetry()

        self.assertEqual(usage["total_calls"], 1)
        self.assertEqual(usage["feature_counts"]["query_analysis_ai_diagnosis"], 1)
        self.assertEqual(len(telemetry), 1)
        self.assertEqual(telemetry[0]["status"], "success")
        self.assertEqual(telemetry[0]["feature"], "query_analysis_ai_diagnosis")
        self.assertEqual(telemetry[0]["prompt_chars"], len("sensitive query text with account details"))
        self.assertNotIn("sensitive query text", str(telemetry[0]))
        self.assertIn("tier=cortex", telemetry[0]["query_tag"])
