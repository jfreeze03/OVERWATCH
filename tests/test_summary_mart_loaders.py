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

from sections import summary_mart_loaders as loaders  # noqa: E402


REQUIRED_LOADERS = (
    "load_query_daily_summary",
    "load_warehouse_daily_credits",
    "load_cortex_daily_usage",
    "load_user_display_dim",
    "load_login_security_daily",
    "load_task_status_daily",
    "load_security_posture_daily",
    "load_executive_packet_current",
)

FORBIDDEN_SOURCE_TOKENS = (
    "SNOWFLAKE.ACCOUNT_USAGE",
    "ACCOUNT_USAGE.",
    "SELECT *",
    "query_text",
    "USER_ID",
    "CREDENTIAL_ID",
)


class SummaryMartLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        for name in REQUIRED_LOADERS:
            fn = getattr(loaders, name)
            clear = getattr(fn, "clear", None)
            if callable(clear):
                clear()

    def test_required_loader_functions_exist(self) -> None:
        for name in REQUIRED_LOADERS:
            self.assertTrue(callable(getattr(loaders, name, None)), name)
            self.assertIn(name, loaders.__all__)

    def test_loader_source_avoids_raw_account_usage_and_raw_ids(self) -> None:
        source = (APP_ROOT / "sections" / "summary_mart_loaders.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, source, token)

    def test_summary_query_uses_summary_boundary_and_capped_rows(self) -> None:
        expected = pd.DataFrame([{"SECTION": "Cost & Contract", "SOURCE_STATUS": "current"}])
        with patch.object(loaders, "run_query", return_value=expected) as run_query:
            result = loaders._summary_query(
                section="Cost & Contract",
                workflow="Cost Overview",
                ttl_key="unit_summary",
                sql="SELECT COST_USD FROM V_WAREHOUSE_DAILY_CREDITS LIMIT 500",
                limit=999,
            )

        self.assertFalse(result.empty)
        kwargs = run_query.call_args.kwargs
        self.assertEqual(kwargs["query_boundary"], "section_summary_autoload")
        self.assertEqual(kwargs["tier"], "section_summary")
        self.assertEqual(kwargs["max_rows"], loaders.DEFAULT_SUMMARY_LIMIT)
        self.assertTrue(kwargs["use_cache"])

    def test_empty_result_returns_safe_fallback_row(self) -> None:
        with patch.object(loaders, "run_query", return_value=pd.DataFrame()):
            result = loaders._summary_query(
                section="Alert Center",
                workflow="Overview",
                ttl_key="unit_empty",
                sql="SELECT ACTIVE_ALERT_COUNT FROM V_EXECUTIVE_PACKET_CURRENT LIMIT 1",
                limit=50,
            )

        self.assertTrue(result.empty)
        self.assertEqual(result.attrs["SOURCE_STATUS"], "Refresh required")
        self.assertEqual(result.attrs["SUMMARY_STATUS"], "Refresh required")
        self.assertEqual(result.attrs["DATA_STATE"], "REFRESH_REQUIRED")
        self.assertTrue(result.attrs["IS_FALLBACK"])
        self.assertEqual(result.attrs["ROW_LIMIT"], 50)
        self.assertEqual(result.attrs["ROW_COUNT"], 0)
        self.assertFalse(result.attrs["RAW_SQL_INCLUDED"])
        serialized = str(result.attrs)
        self.assertNotIn("ACCOUNT_USAGE", serialized)
        self.assertNotIn("SELECT", serialized)

    def test_query_exception_returns_safe_fallback_row(self) -> None:
        with patch.object(loaders, "run_query", side_effect=RuntimeError("raw warehouse failure")):
            result = loaders._summary_query(
                section="Security Monitoring",
                workflow="Security Overview",
                ttl_key="unit_exception",
                sql="SELECT RISK_SCORE FROM V_SECURITY_POSTURE_DAILY LIMIT 1",
                limit=10,
            )

        self.assertTrue(result.empty)
        self.assertEqual(result.attrs["SOURCE_STATUS"], "Query failed")
        self.assertEqual(result.attrs["SUMMARY_STATUS"], "Query failed")
        self.assertEqual(result.attrs["DATA_STATE"], "QUERY_FAILED")
        self.assertNotIn("raw warehouse failure", str(result.attrs))

    def test_summary_result_keeps_empty_and_error_states_distinct(self) -> None:
        with patch.object(loaders, "run_query", return_value=pd.DataFrame()):
            empty = loaders._summary_result(
                section="Alert Center",
                workflow="Overview",
                ttl_key="unit_empty_result",
                sql="SELECT ACTIVE_ALERT_COUNT FROM V_EXECUTIVE_PACKET_CURRENT LIMIT 1",
                limit=50,
            )
        with patch.object(loaders, "run_query", side_effect=RuntimeError("object does not exist")):
            missing = loaders._summary_result(
                section="Alert Center",
                workflow="Overview",
                ttl_key="unit_missing_result",
                sql="SELECT ACTIVE_ALERT_COUNT FROM V_EXECUTIVE_PACKET_CURRENT LIMIT 1",
                limit=50,
            )

        self.assertIsInstance(empty, loaders.SummaryResult)
        self.assertEqual(empty.state, loaders.DataState.REFRESH_REQUIRED)
        self.assertEqual(missing.state, loaders.DataState.SETUP_REQUIRED)
        self.assertTrue(empty.data.empty)
        self.assertTrue(missing.data.empty)

    def test_loader_sql_uses_safe_window_and_summary_mart(self) -> None:
        captured: list[dict[str, object]] = []

        def fake_summary_query(**kwargs):
            captured.append(kwargs)
            return pd.DataFrame([{"SECTION": kwargs["section"], "SOURCE_STATUS": "current"}])

        with patch.object(loaders, "_summary_query", side_effect=fake_summary_query):
            result = loaders.load_query_daily_summary("ALFA", "ALL", "bad-window", limit=999)

        self.assertFalse(result.empty)
        self.assertEqual(captured[0]["limit"], 999)
        sql = str(captured[0]["sql"])
        self.assertIn("V_QUERY_DAILY_SUMMARY", sql)
        self.assertIn("DATEADD('day', -7, CURRENT_DATE())", sql)
        self.assertIn("LIMIT 200", sql)
        self.assertNotIn("ACCOUNT_USAGE", sql)


if __name__ == "__main__":
    unittest.main()
