"""Regression tests for the shared SQL escaping helper.

These tests pin the behaviour of :func:`utils.sql_safe.sql_literal` and assert
that every historical import path resolves to the exact same implementation so
the de-duplication cannot silently regress.
"""
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils.sql_safe import sql_literal  # noqa: E402


class SqlLiteralTests(unittest.TestCase):
    def test_plain_string_is_quoted(self):
        self.assertEqual(sql_literal("hello"), "'hello'")

    def test_single_quotes_are_doubled(self):
        self.assertEqual(sql_literal("O'Brien"), "'O''Brien'")

    def test_multiple_quotes_are_each_doubled(self):
        self.assertEqual(sql_literal("''"), "''''''")

    def test_empty_string_returns_empty_literal(self):
        self.assertEqual(sql_literal(""), "''")

    def test_none_maps_to_sql_null_keyword(self):
        self.assertEqual(sql_literal(None), "NULL")

    def test_percent_sign_is_preserved_verbatim(self):
        self.assertEqual(sql_literal("100%"), "'100%'")

    def test_underscore_is_preserved_verbatim(self):
        self.assertEqual(sql_literal("a_b_c"), "'a_b_c'")

    def test_like_wildcards_preserved(self):
        self.assertEqual(sql_literal("%_foo_%"), "'%_foo_%'")

    def test_nul_bytes_are_stripped(self):
        self.assertEqual(sql_literal("a\x00b"), "'ab'")

    def test_non_string_values_are_stringified(self):
        self.assertEqual(sql_literal(42), "'42'")
        self.assertEqual(sql_literal(3.5), "'3.5'")

    def test_max_len_truncates_before_escaping_quotes(self):
        # Truncation happens on the raw text, then quotes are doubled.
        self.assertEqual(sql_literal("abcdef", max_len=3), "'abc'")

    def test_backslash_is_not_escaped(self):
        # Snowflake string literals treat backslash literally by default.
        self.assertEqual(sql_literal("a\\b"), "'a\\b'")

    def test_injection_attempt_is_neutralized(self):
        payload = "x'; DROP TABLE users; --"
        self.assertEqual(sql_literal(payload), "'x''; DROP TABLE users; --'")


class SqlLiteralImportIdentityTests(unittest.TestCase):
    """All legacy import sites must resolve to the canonical implementation."""

    def test_all_import_paths_share_one_implementation(self):
        from utils import sql_literal as via_package
        from utils.query import sql_literal as via_query
        from utils.logging import sql_literal as via_logging
        from utils.admin import sql_literal as via_admin
        from utils.company_filter import sql_literal as via_company_filter
        from utils.sql_safe import sql_literal as canonical

        for candidate in (
            via_package,
            via_query,
            via_logging,
            via_admin,
            via_company_filter,
        ):
            self.assertIs(candidate, canonical)

    def test_no_module_redefines_sql_literal(self):
        """Guard against a new copy-paste sneaking back into utils/."""
        utils_dir = APP_ROOT / "utils"
        offenders = []
        for path in utils_dir.glob("*.py"):
            if path.name == "sql_safe.py":
                continue
            text = path.read_text(encoding="utf-8")
            if "def sql_literal(" in text:
                offenders.append(path.name)
        self.assertEqual(
            offenders,
            [],
            f"sql_literal must only be defined in sql_safe.py, found copies in: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
