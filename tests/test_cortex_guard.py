from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

import utils.cortex as cortex  # noqa: E402


class _DummySession:
    def __init__(self, value: str = "ok"):
        self.value = value
        self.sql_text = ""

    def sql(self, sql_text: str):
        self.sql_text = sql_text
        return self

    def collect(self):
        return [{"ANSWER": self.value}]


class CortexGuardTests(unittest.TestCase):
    def setUp(self):
        cortex._CORTEX_LAST_CALL_MONOTONIC = 0.0

    def tearDown(self):
        cortex._CORTEX_LAST_CALL_MONOTONIC = 0.0

    def test_cortex_completion_uses_safe_literal_and_alias(self):
        session = _DummySession("diagnosis")
        answer = cortex.run_cortex_completion(
            session,
            "query text with 'quoted' value",
            alias="answer",
            cooldown_seconds=0,
        )

        self.assertEqual(answer, "diagnosis")
        self.assertIn("SNOWFLAKE.CORTEX.COMPLETE", session.sql_text)
        self.assertIn("mistral-large2", session.sql_text)
        self.assertIn("''quoted''", session.sql_text)
        self.assertIn(" AS ANSWER", session.sql_text)

    def test_cortex_completion_sanitizes_unsafe_alias(self):
        session = _DummySession("diagnosis")
        answer = cortex.run_cortex_completion(
            session,
            "query text",
            alias="1 bad alias; drop table x",
            cooldown_seconds=0,
        )

        self.assertEqual(answer, "")
        self.assertIn(" AS CORTEX_1_BAD_ALIAS_DROP_TABLE_X", session.sql_text)
        self.assertNotIn("; drop", session.sql_text.lower())

    def test_cortex_completion_throttles_repeated_manual_calls(self):
        cortex.reserve_cortex_completion(cooldown_seconds=30)

        with self.assertRaises(cortex.CortexRateLimitError):
            cortex.reserve_cortex_completion(cooldown_seconds=30)
