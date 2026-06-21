"""Regression tests for the shared SQL escaping helper.

These tests pin the behavior of ``utils.sql_safe.sql_literal`` and prove that
every historical import path now resolves to the same shared implementation
(previously the helper was copy/pasted into four modules).
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

    def test_empty_string_quotes_to_empty_literal(self):
        self.assertEqual(sql_literal(""), "''")

    def test_none_renders_unquoted_null(self):
        self.assertEqual(sql_literal(None), "NULL")

    def test_single_quote_is_doubled(self):
        self.assertEqual(sql_literal("O'Brien"), "'O''Brien'")

    def test_multiple_quotes_are_each_doubled(self):
        self.assertEqual(sql_literal("a'b'c"), "'a''b''c'")

    def test_already_doubled_quotes_are_re_escaped(self):
        # Defense in depth: a literal that arrives pre-escaped must not be
        # treated as safe; every single quote is doubled unconditionally.
        self.assertEqual(sql_literal("a''b"), "'a''''b'")

    def test_percent_and_underscore_are_preserved_verbatim(self):
        # LIKE wildcards are not escaped here; sql_literal only guards quoting.
        self.assertEqual(sql_literal("100%_done"), "'100%_done'")

    def test_nul_bytes_are_stripped(self):
        self.assertEqual(sql_literal("a\x00b"), "'ab'")

    def test_max_len_truncates_before_quoting(self):
        self.assertEqual(sql_literal("abcdef", max_len=3), "'abc'")

    def test_truncation_cannot_orphan_an_escape(self):
        # Truncation happens on the raw string, then quoting doubles the quote,
        # so the result is always balanced.
        self.assertEqual(sql_literal("ab'", max_len=3), "'ab'''")

    def test_non_string_values_are_coerced(self):
        self.assertEqual(sql_literal(42), "'42'")
        self.assertEqual(sql_literal(3.5), "'3.5'")
        self.assertEqual(sql_literal(True), "'True'")

    def test_injection_attempt_is_neutralized(self):
        payload = "x'; DROP TABLE users; --"
        self.assertEqual(sql_literal(payload), "'x''; DROP TABLE users; --'")

    def test_all_historical_import_paths_share_one_impl(self):
        from utils import sql_literal as via_pkg
        from utils.query import sql_literal as via_query
        from utils.admin import sql_literal as via_admin
        from utils.logging import sql_literal as via_logging
        from utils.company_filter import sql_literal as via_company_filter

        impls = {
            via_pkg,
            via_query,
            via_admin,
            via_logging,
            via_company_filter,
            sql_literal,
        }
        self.assertEqual(len(impls), 1, "sql_literal must be a single shared object")


if __name__ == "__main__":
    unittest.main()
