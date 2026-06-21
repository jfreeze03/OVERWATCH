from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

import utils.query as query  # noqa: E402
from utils.query import (  # noqa: E402
    ADMIN_SQL_READ_LIMIT_ROWS,
    CACHE_TIERS,
    QUERY_BUDGET_THRESHOLDS,
    STANDARD_SQL_READ_LIMIT_ROWS,
    STATEMENT_TIMEOUTS_SECONDS,
    _inject_read_limit,
    _query_starts_with_read,
    safe_identifier,
)
from utils.sql_safe import sql_literal  # noqa: E402


class QueryGuardrailTests(unittest.TestCase):
    def test_read_limit_is_added_to_unbounded_selects_and_ctes(self):
        self.assertEqual(
            _inject_read_limit("SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", max_rows=123),
            "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY\nLIMIT 123",
        )
        self.assertEqual(
            _inject_read_limit(
                "WITH q AS (SELECT * FROM T) SELECT * FROM q ORDER BY START_TIME DESC",
                max_rows=456,
            ),
            "WITH q AS (SELECT * FROM T) SELECT * FROM q ORDER BY START_TIME DESC\nLIMIT 456",
        )
        self.assertEqual(
            _inject_read_limit("/* dashboard probe */\n-- scoped read\nSELECT * FROM T", max_rows=25),
            "/* dashboard probe */\n-- scoped read\nSELECT * FROM T\nLIMIT 25",
        )

    def test_read_limit_leaves_bounded_or_non_read_sql_untouched(self):
        cases = [
            "SELECT * FROM T LIMIT 50",
            "SELECT * FROM T;",
            "SHOW WAREHOUSES",
            "DESC TABLE DBA_MAINT_DB.OVERWATCH.OVERWATCH_ALERTS",
            "CALL SP_OVERWATCH_SEND_ALERT_DIGEST()",
            "ALTER WAREHOUSE OVERWATCH_WH SUSPEND",
            "SELECT 1; SELECT 2",
        ]
        for sql in cases:
            with self.subTest(sql=sql):
                expected = sql if sql != "SELECT * FROM T;" else "SELECT * FROM T\nLIMIT 500"
                self.assertEqual(_inject_read_limit(sql, max_rows=500), expected)

    def test_read_limit_ignores_limit_inside_string_literals(self):
        self.assertEqual(
            _inject_read_limit("SELECT 'LIMIT 25' AS NOTE, WAREHOUSE_NAME FROM T", max_rows=250),
            "SELECT 'LIMIT 25' AS NOTE, WAREHOUSE_NAME FROM T\nLIMIT 250",
        )

    def test_read_prefix_detection_is_linear_for_block_comment_noise(self):
        suspicious_sql = "/*" + ("*" * 20_000) + "/ " + ("*" * 20_000) + " SELECT * FROM T"

        self.assertFalse(_query_starts_with_read(suspicious_sql))
        self.assertEqual(_inject_read_limit(suspicious_sql, max_rows=100), suspicious_sql)
        self.assertFalse(_query_starts_with_read("SELECTED_VALUE FROM T"))
        self.assertFalse(_query_starts_with_read("WITHHELD AS SELECT"))

    def test_default_read_limit_tracks_operator_mode(self):
        with patch("utils.query._admin_actions_enabled", return_value=False):
            self.assertTrue(
                _inject_read_limit("SELECT * FROM T").endswith(f"LIMIT {STANDARD_SQL_READ_LIMIT_ROWS}")
            )
        with patch("utils.query._admin_actions_enabled", return_value=True):
            self.assertTrue(
                _inject_read_limit("SELECT * FROM T").endswith(f"LIMIT {ADMIN_SQL_READ_LIMIT_ROWS}")
            )

    def test_safe_identifier_rejects_dollar_and_unsafe_parts(self):
        self.assertEqual(safe_identifier("DBA_MAINT_DB", allow_qualified=False), "DBA_MAINT_DB")
        self.assertEqual(
            safe_identifier("DBA_MAINT_DB.OVERWATCH.OVERWATCH_ALERTS", allow_qualified=True),
            "DBA_MAINT_DB.OVERWATCH.OVERWATCH_ALERTS",
        )
        for identifier in ("SYSTEM$STREAMLIT", "DB.TABLE$BAD", "1BAD", "DB;DROP"):
            with self.subTest(identifier=identifier):
                with self.assertRaises(ValueError):
                    safe_identifier(identifier, allow_qualified=True)

    def test_sql_literal_escapes_strings_without_treating_like_patterns_as_sql(self):
        self.assertEqual(sql_literal(None), "NULL")
        self.assertEqual(sql_literal(""), "''")
        self.assertEqual(sql_literal("O'Brien"), "'O''Brien'")
        self.assertEqual(sql_literal("100%_match"), "'100%_match'")
        self.assertEqual(sql_literal("a\x00b"), "'ab'")
        self.assertEqual(sql_literal("x" * 20, max_len=5), "'xxxxx'")
        self.assertEqual(sql_literal(42), "'42'")
        self.assertEqual(sql_literal("'; DROP TABLE t; --"), "'''; DROP TABLE t; --'")

    def test_sql_literal_is_shared_across_legacy_import_paths(self):
        from utils import admin, company_filter, logging as usage_logging

        for module in (query, admin, company_filter, usage_logging):
            with self.subTest(module=module.__name__):
                self.assertIs(module.sql_literal, sql_literal)
                self.assertEqual(module.sql_literal("a'b", 10), "'a''b'")

        public_defs = []
        for path in (APP_ROOT / "utils").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "def sql_literal(" in text:
                public_defs.append(path.relative_to(APP_ROOT).as_posix())
        self.assertEqual(public_defs, ["utils/sql_safe.py"])

    def test_query_cache_lock_stripes_stay_removed(self):
        query_text = (APP_ROOT / "utils" / "query.py").read_text(encoding="utf-8")
        self.assertNotIn("import threading", query_text)
        self.assertNotIn("_QUERY_CACHE_LOCK_STRIPE_COUNT", query_text)
        self.assertNotIn("_QUERY_CACHE_LOCK_STRIPES", query_text)
        self.assertNotIn("def _get_query_cache_lock", query_text)
        self.assertNotIn("with _get_query_cache_lock", query_text)

    def test_cache_timeout_and_budget_tiers_are_explicit(self):
        self.assertEqual(CACHE_TIERS["standard"], 300)
        self.assertEqual(CACHE_TIERS["historical"], 3600)
        self.assertLess(STATEMENT_TIMEOUTS_SECONDS["live"], STATEMENT_TIMEOUTS_SECONDS["historical"])
        self.assertIn("max_queries_per_render", QUERY_BUDGET_THRESHOLDS)
        self.assertGreaterEqual(QUERY_BUDGET_THRESHOLDS["max_queries_per_render"], 10)
        self.assertIs(query._TIER_FN["standard"], query._cached_standard)
        self.assertIs(query._RAISE_TIER_FN["standard"], query._cached_raise_standard)


if __name__ == "__main__":
    unittest.main()
