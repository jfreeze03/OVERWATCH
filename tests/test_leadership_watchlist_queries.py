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

from queries import leadership_watchlist as queries  # noqa: E402


FORBIDDEN_QUERY_TOKENS = (
    "SNOWFLAKE.ACCOUNT_USAGE",
    "ACCOUNT_USAGE.",
    "SELECT *",
    "QUERY_TEXT",
    "USER_ID",
    "CREDENTIAL_ID",
)


class LeadershipWatchlistQueryTests(unittest.TestCase):
    def test_all_helpers_read_app_facing_views(self) -> None:
        captured: list[dict[str, object]] = []

        def fake_run_query(sql: str, **kwargs):
            captured.append({"sql": sql, **kwargs})
            return pd.DataFrame([{"ROW_COUNT": 1}])

        with patch.object(queries, "run_query", side_effect=fake_run_query):
            queries.get_credit_daily("ALFA", "ALL", "2026-06-28", "2026-07-05", warehouse="COMPUTE_WH")
            queries.get_credit_comparison_24h("ALFA", "ALL")
            queries.get_login_security("ALFA", "ALL", "2026-06-28", "2026-07-05", user="JANE")
            queries.get_failed_logins_last_hour("ALFA", "ALL")
            queries.get_suspicious_logins("ALFA", "ALL", "2026-06-28", "2026-07-05")
            queries.get_query_errors("ALFA", "ALL", "2026-06-28", "2026-07-05", warehouse="COMPUTE_WH")
            queries.get_storage_daily("ALFA", "ALL", "2026-06-28", "2026-07-05", database="ALFA_EDW_SAN")
            queries.get_cortex_code_usage("ALFA", "ALL", "2026-06-01", "2026-07-05", user="JANE")
            queries.get_role_grant_audit("ALFA", "ALL")

        self.assertEqual(len(captured), 9)
        for call in captured:
            sql = str(call["sql"])
            with self.subTest(sql=sql[:80]):
                self.assertIn("FROM V_LEADERSHIP_", sql)
                for token in FORBIDDEN_QUERY_TOKENS:
                    self.assertNotIn(token, sql.upper(), token)
                self.assertEqual(call["query_boundary"], "section_summary_autoload")
                self.assertEqual(call["tier"], "section_summary")
                self.assertLessEqual(int(call["max_rows"]), queries.DEFAULT_LIMIT)

    def test_role_grant_defaults_scope_to_dev_roles_and_alfa_database(self) -> None:
        captured: list[str] = []

        def fake_run_query(sql: str, **kwargs):
            captured.append(sql)
            return pd.DataFrame()

        with patch.object(queries, "run_query", side_effect=fake_run_query):
            queries.get_role_grant_audit("ALFA", "ALL")

        sql = captured[0]
        self.assertIn("ROLE_NAME ILIKE 'TF_O_DEV_%'", sql)
        self.assertIn("OBJECT_DATABASE = 'ALFA_EDW_SAN'", sql)

    def test_repo_defines_leadership_secure_views(self) -> None:
        sql = (ROOT / "snowflake" / "mart_setup" / "09_summary_marts.sql").read_text(encoding="utf-8").upper()
        validation = (ROOT / "snowflake" / "OVERWATCH_MART_VALIDATION.sql").read_text(encoding="utf-8").upper()
        drop = (ROOT / "snowflake" / "OVERWATCH_MART_DROP.sql").read_text(encoding="utf-8").upper()
        for spec in queries.LEADERSHIP_VIEW_SPECS.values():
            view = str(spec["view"]).upper()
            with self.subTest(view=view):
                self.assertIn(f"CREATE OR REPLACE SECURE VIEW {view}", sql)
                self.assertIn(view, validation)
                self.assertIn(f"DROP VIEW IF EXISTS {view}", drop)


if __name__ == "__main__":
    unittest.main()
