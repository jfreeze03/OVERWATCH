from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


class SqlSafeTests(unittest.TestCase):
    def test_sql_literal_escapes_strings_without_treating_like_wildcards_as_special(self):
        from utils.sql_safe import sql_literal

        self.assertEqual(sql_literal("O'Reilly"), "'O''Reilly'")
        self.assertEqual(sql_literal("50%_ready"), "'50%_ready'")
        self.assertEqual(sql_literal(""), "''")
        self.assertEqual(sql_literal("a\x00b"), "'ab'")
        self.assertEqual(sql_literal("abcdef", max_len=3), "'abc'")

    def test_sql_literal_none_becomes_sql_null(self):
        from utils.sql_safe import sql_literal

        self.assertEqual(sql_literal(None), "NULL")

    def test_legacy_sql_literal_imports_use_shared_helper(self):
        from utils.admin import sql_literal as admin_literal
        from utils.company_filter import sql_literal as company_literal
        from utils.logging import sql_literal as logging_literal
        from utils.query import sql_literal as query_literal
        from utils.sql_safe import sql_literal

        self.assertIs(admin_literal, sql_literal)
        self.assertIs(company_literal, sql_literal)
        self.assertIs(logging_literal, sql_literal)
        self.assertIs(query_literal, sql_literal)


if __name__ == "__main__":
    unittest.main()
