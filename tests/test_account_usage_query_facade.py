from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from queries import account_usage  # noqa: E402


class AccountUsageQueryFacadeTests(unittest.TestCase):
    def test_summary_helpers_read_secure_views_and_boundary(self) -> None:
        captured: list[dict[str, object]] = []

        def fake_run_query(sql: str, **kwargs):
            captured.append({"sql": sql, **kwargs})
            return pd.DataFrame([{"QUERY_COUNT": 7}])

        with patch.object(account_usage, "run_query", side_effect=fake_run_query):
            result = account_usage.get_query_daily_summary(
                "ALFA",
                "ALL",
                "2026-06-28",
                "2026-07-05",
                warehouse="COMPUTE_WH",
                limit=999,
            )

        self.assertFalse(result.empty)
        call = captured[0]
        sql = str(call["sql"])
        self.assertIn("FROM V_QUERY_DAILY_SUMMARY", sql)
        self.assertIn("TOP_WAREHOUSE_NAME = 'COMPUTE_WH'", sql)
        self.assertIn("LIMIT 200", sql)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", sql)
        self.assertNotIn("SELECT *", sql.upper())
        self.assertEqual(call["query_boundary"], "section_summary_autoload")
        self.assertEqual(call["tier"], "section_summary")
        self.assertEqual(call["max_rows"], 200)

    def test_all_summary_domains_have_secure_view_specs(self) -> None:
        for name, spec in account_usage.SUMMARY_VIEW_SPECS.items():
            with self.subTest(name=name):
                self.assertTrue(str(spec["view"]).startswith("V_"))
                self.assertIn("columns", spec)

    def test_detail_helpers_are_bounded_and_mart_backed(self) -> None:
        captured: list[dict[str, object]] = []

        def fake_run_query(sql: str, **kwargs):
            captured.append({"sql": sql, **kwargs})
            return pd.DataFrame([{"QUERY_ID": "01a"}])

        with patch.object(account_usage, "run_query", side_effect=fake_run_query):
            result = account_usage.get_recent_query_detail(
                "ALFA",
                "ALL",
                "2026-06-28",
                "2026-07-05",
                query_id="01a",
                limit=999,
            )

        self.assertFalse(result.empty)
        call = captured[0]
        sql = str(call["sql"])
        self.assertIn("FROM FACT_QUERY_DETAIL_RECENT", sql)
        self.assertIn("QUERY_ID = '01a'", sql)
        self.assertIn("LIMIT 500", sql)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", sql)
        self.assertNotIn("QUERY_TEXT", sql.upper())
        self.assertEqual(call["query_boundary"], "evidence_action")
        self.assertEqual(call["max_rows"], 500)


if __name__ == "__main__":
    unittest.main()
