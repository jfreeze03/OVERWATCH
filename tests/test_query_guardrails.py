from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils.query import (  # noqa: E402
    ADMIN_SQL_READ_LIMIT_ROWS,
    STANDARD_SQL_READ_LIMIT_ROWS,
    _inject_read_limit,
    _query_starts_with_read,
    safe_identifier,
)


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


if __name__ == "__main__":
    unittest.main()
