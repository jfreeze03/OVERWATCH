import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SnowflakeExecutionValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tools.contracts.snowflake_execution_validation import write_snowflake_validation_artifacts

        cls.artifacts = write_snowflake_validation_artifacts(ROOT)

    def _read_json(self, rel: str):
        return json.loads((ROOT / rel).read_text(encoding="utf-8"))

    def test_fixture_mode_writes_static_validation_and_live_skip(self):
        from tools.contracts.snowflake_execution_validation import EXPECTED_SCRIPT_ORDER, REQUIRED_RESULT_FILES

        summary = self._read_json("artifacts/snowflake_validation/snowflake_validation_summary.json")
        manifest = self._read_json("artifacts/snowflake_validation/artifact_manifest.json")
        self.assertTrue(summary["passed"], summary)
        self.assertFalse(summary["live_mode_enabled"])
        self.assertEqual(summary["live_status"], "skipped")
        self.assertTrue((ROOT / "artifacts/snowflake_validation/snowflake_validation_SKIPPED.txt").exists())
        for name in REQUIRED_RESULT_FILES:
            self.assertIn(f"artifacts/snowflake_validation/{name}.json", manifest["files"])
        for rel in EXPECTED_SCRIPT_ORDER:
            self.assertTrue((ROOT / rel).exists(), rel)

    def test_statement_splitter_preserves_procedure_bodies(self):
        from tools.contracts.snowflake_execution_validation import split_sql_statements

        sql = """
        CREATE OR REPLACE PROCEDURE SP_SAMPLE()
        RETURNS VARCHAR
        LANGUAGE SQL
        AS $$ BEGIN SELECT 1; SELECT 2; RETURN 'ok'; END; $$;
        CALL SP_SAMPLE();
        """
        statements = split_sql_statements(sql)
        self.assertEqual(len(statements), 2)
        self.assertIn("SELECT 1; SELECT 2", statements[0])
        self.assertTrue(statements[1].startswith("CALL SP_SAMPLE"))

    def test_procedure_compile_and_dependency_graph_cover_calls(self):
        setup_text = (ROOT / "snowflake/mart_setup/05_load_procedures.sql").read_text(encoding="utf-8")
        expected_proc_count = len(re.findall(r"\bCREATE\s+OR\s+REPLACE\s+PROCEDURE\b", setup_text, flags=re.IGNORECASE))
        compile_rows = self._read_json("artifacts/snowflake_validation/procedure_compile_results.json")
        graph = self._read_json("artifacts/snowflake_validation/procedure_dependency_graph.json")
        self.assertGreaterEqual(len(compile_rows), expected_proc_count)
        self.assertTrue(graph["passed"], graph)
        self.assertFalse(graph["unresolved_call_targets"])
        self.assertTrue(all(row["raw_sql_included"] is False for row in compile_rows))

    def test_validation_drop_and_compact_evidence_artifacts_pass(self):
        validation = self._read_json("artifacts/snowflake_validation/validation_sql_results.json")
        compact = self._read_json("artifacts/snowflake_validation/compact_evidence_mart_validation_results.json")
        self.assertTrue(all(row["status"] == "passed" for row in validation), validation)
        self.assertTrue(compact["passed"], compact)
        self.assertEqual(compact["mart_count"], 5)
        self.assertEqual(compact["normal_account_usage_count"], 0)

    def test_metric_candidate_shape_rejects_recent_failure_classes(self):
        from tools.contracts.snowflake_execution_validation import validate_metric_candidate_union_shape

        sql = (ROOT / "snowflake/mart_setup/05_load_procedures.sql").read_text(encoding="utf-8")
        self.assertTrue(validate_metric_candidate_union_shape(sql)["passed"])

        missing_confidence = sql.replace("TREND_LABEL, CONFIDENCE, 10 AS SORT_ORDER", "TREND_LABEL, 10 AS SORT_ORDER", 1)
        missing_codes = {row["code"] for row in validate_metric_candidate_union_shape(missing_confidence)["failures"]}
        self.assertIn("METRIC_UNION_BRANCH_COUNT_MISMATCH", missing_codes)
        self.assertIn("METRIC_UNION_BRANCH_MISSING_CONFIDENCE", missing_codes)

        mismatch = sql.replace("CONFIDENCE, 20", "'extra_column', CONFIDENCE, 20", 1)
        mismatch_codes = {row["code"] for row in validate_metric_candidate_union_shape(mismatch)["failures"]}
        self.assertIn("METRIC_UNION_BRANCH_COUNT_MISMATCH", mismatch_codes)

        scalar_trend = sql.replace("tr.TREND_POINTS", "(SELECT tr.TREND_POINTS FROM TMP_SECTION_METRIC_TRENDS tr)", 1)
        scalar_codes = {row["code"] for row in validate_metric_candidate_union_shape(scalar_trend)["failures"]}
        self.assertIn("SCALAR_TREND_SUBQUERY_PRESENT", scalar_codes)

        ambiguous = sql.replace("metric_candidates.METRIC_KEY IN", "METRIC_KEY IN", 1)
        ambiguous_codes = {row["code"] for row in validate_metric_candidate_union_shape(ambiguous)["failures"]}
        self.assertIn("UNQUALIFIED_AMBIGUOUS_METRIC_FIELD", ambiguous_codes)

    def test_trend_packet_and_refresh_artifacts_are_present(self):
        trend = self._read_json("artifacts/snowflake_validation/trend_cardinality_results.json")
        packet = self._read_json("artifacts/snowflake_validation/packet_shape_results.json")
        refresh_fast = self._read_json("artifacts/snowflake_validation/refresh_fast_results.json")
        refresh_full = self._read_json("artifacts/snowflake_validation/refresh_full_results.json")
        self.assertTrue(trend["passed"], trend)
        self.assertEqual(
            trend["join_key"],
            ["BRIEF_ID", "SECTION_NAME", "COMPANY", "ENVIRONMENT", "WINDOW_DAYS", "METRIC_KEY"],
        )
        self.assertTrue(packet["passed"], packet)
        self.assertEqual(refresh_fast["status"], "skipped")
        self.assertEqual(refresh_full["status"], "skipped")

    def test_snowflake_error_sanitizer_removes_sql_and_secrets(self):
        from tools.contracts.snowflake_execution_validation import sanitize_snowflake_error

        message = (
            "SnowflakeSQLException account=my_acct user=admin password=secret "
            "CREATE OR REPLACE PROCEDURE SP_X() AS $$ BEGIN SELECT * FROM T; END; $$;"
        )
        sanitized = sanitize_snowflake_error(message)
        self.assertNotIn("secret", sanitized)
        self.assertNotIn("SELECT *", sanitized)
        self.assertNotIn("CREATE OR REPLACE", sanitized)


if __name__ == "__main__":
    unittest.main()
