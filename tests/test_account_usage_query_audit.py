from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from tools.contracts.account_usage_query_audit import (
    ACCOUNT_USAGE_QUERY_AUDIT_GATE_REL,
    build_account_usage_query_audit_results,
    write_account_usage_query_audit_artifacts,
)


class AccountUsageQueryAuditTests(unittest.TestCase):
    def _write(self, root: Path, rel: str, text: str) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_summary_path_account_usage_reference_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(
                root,
                ".overwatch_final/sections/section_command_rendering.py",
                "SQL = 'SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY'\n",
            )

            results = build_account_usage_query_audit_results(root)

        self.assertFalse(results["passed"])
        self.assertEqual(results["summary_path_account_usage_violation_count"], 1)

    def test_setup_sql_account_usage_is_approved_builder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(
                root,
                "snowflake/mart_setup/05_load_procedures.sql",
                "SELECT COUNT(1) FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY;\n",
            )

            results = build_account_usage_query_audit_results(root)

        self.assertTrue(results["passed"], results.get("failures"))
        self.assertEqual(results["classification_counts"]["approved_mart_builder"], 1)

    def test_explicit_query_search_fallback_is_not_summary_violation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(
                root,
                ".overwatch_final/sections/query_search.py",
                "with query_budget_context('account_usage_fallback'):\n"
                "    SQL = 'SELECT QUERY_ID FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY LIMIT 10'\n",
            )

            results = build_account_usage_query_audit_results(root)

        self.assertTrue(results["passed"], results.get("failures"))
        self.assertEqual(results["classification_counts"]["approved_explicit_deep_or_admin_path"], 2)

    def test_duplicate_cortex_union_in_app_runtime_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(
                root,
                ".overwatch_final/sections/cortex_inline.py",
                "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY\n"
                "UNION ALL\n"
                "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY\n",
            )

            results = build_account_usage_query_audit_results(root)

        self.assertFalse(results["passed"])
        self.assertEqual(results["cortex_union_duplicate_count"], 1)

    def test_repeated_users_join_in_summary_path_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(
                root,
                ".overwatch_final/sections/summary_user_labels.py",
                "LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u1 ON a.USER_ID = u1.USER_ID\n"
                "LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u2 ON b.USER_ID = u2.USER_ID\n",
            )

            results = build_account_usage_query_audit_results(root)

        self.assertFalse(results["passed"])
        self.assertEqual(results["repeated_users_join_count"], 1)

    def test_written_artifact_has_no_raw_sql_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(
                root,
                "snowflake/OVERWATCH_MART_SETUP.sql",
                "SELECT COUNT(1) FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY;\n",
            )

            artifacts = write_account_usage_query_audit_artifacts(root)

        gate = artifacts[ACCOUNT_USAGE_QUERY_AUDIT_GATE_REL]
        self.assertTrue(gate["passed"], gate.get("failures"))
        serialized = str(gate)
        self.assertNotIn("SELECT COUNT", serialized)
        self.assertFalse(gate["raw_sql_included"])


if __name__ == "__main__":
    unittest.main()
