import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class SnowflakeExecutionValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tools.contracts.snowflake_execution_validation import write_snowflake_validation_artifacts

        cls.artifacts = write_snowflake_validation_artifacts(ROOT)

    def _read_json(self, rel: str):
        return json.loads((ROOT / rel).read_text(encoding="utf-8"))

    def test_fixture_mode_writes_static_validation_and_live_skip(self):
        from tools.contracts.snowflake_execution_validation import (
            EXPECTED_SCRIPT_ORDER,
            REQUIRED_RESULT_FILES,
            REQUIRED_VALIDATION_PHASES,
        )

        summary = self._read_json("artifacts/snowflake_validation/snowflake_validation_summary.json")
        manifest = self._read_json("artifacts/snowflake_validation/artifact_manifest.json")
        phases = self._read_json("artifacts/snowflake_validation/phase_validation_results.json")
        self.assertTrue(summary["passed"], summary)
        self.assertFalse(summary["live_mode_enabled"])
        self.assertEqual(summary["live_status"], "skipped")
        self.assertEqual(summary["procedure_compile_failure_count"], 0)
        self.assertEqual(summary["procedure_smoke_failure_count"], 0)
        self.assertTrue(summary["recent_snowflake_fix_validation_passed"])
        self.assertTrue(summary["packet_publication_validation_passed"])
        self.assertTrue(summary["compact_evidence_mart_validation_passed"])
        self.assertTrue((ROOT / "artifacts/snowflake_validation/snowflake_validation_SKIPPED.txt").exists())
        for name in REQUIRED_RESULT_FILES:
            self.assertIn(f"artifacts/snowflake_validation/{name}.json", manifest["files"])
        for rel in EXPECTED_SCRIPT_ORDER:
            self.assertTrue((ROOT / rel).exists(), rel)
        self.assertTrue(phases["passed"], phases)
        self.assertEqual({row["phase"] for row in phases["phases"]}, set(REQUIRED_VALIDATION_PHASES))

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
        compile_coverage = self._read_json("artifacts/snowflake_validation/procedure_compile_coverage_results.json")
        graph = self._read_json("artifacts/snowflake_validation/procedure_dependency_graph.json")
        self.assertGreaterEqual(len(compile_rows), expected_proc_count)
        self.assertTrue(graph["passed"], graph)
        self.assertFalse(graph["unresolved_call_targets"])
        self.assertTrue(compile_coverage["passed"], compile_coverage)
        self.assertGreaterEqual(compile_coverage["procedure_count"], graph["procedure_count"])
        self.assertEqual(compile_coverage["missing_compile_row_count"], 0)
        self.assertTrue(all(row["compile_static_status"] == "passed" for row in compile_coverage["rows"]))
        self.assertTrue(all(row["raw_sql_included"] is False for row in compile_rows))

    def test_procedure_compile_coverage_rejects_gaps(self):
        from tools.contracts import snowflake_execution_validation as validation

        texts = validation._load_script_texts(ROOT)
        graph = validation._dependency_graph(texts)
        compile_rows = validation._compile_results(texts)

        missing_name = compile_rows[0]["procedure_name"]
        missing_compile_rows = [row for row in compile_rows if row["procedure_name"] != missing_name]
        missing = validation._procedure_compile_coverage_results(graph, missing_compile_rows, live_enabled=False)
        self.assertFalse(missing["passed"])
        self.assertIn("CREATE_PROCEDURE_WITHOUT_COMPILE_ROW", {row["code"] for row in missing["failures"]})

        unresolved_graph = dict(graph)
        unresolved_graph["unresolved_call_targets"] = ["SP_OVERWATCH_MISSING_TARGET"]
        unresolved = validation._procedure_compile_coverage_results(unresolved_graph, compile_rows, live_enabled=False)
        self.assertFalse(unresolved["passed"])
        self.assertIn("UNRESOLVED_CALL_TARGET", {row["code"] for row in unresolved["failures"]})

        wrapper_graph = json.loads(json.dumps(graph))
        wrapper_graph["procedures"][0]["wrapper_of"] = "SP_OVERWATCH_MISSING_IMPL"
        wrapper = validation._procedure_compile_coverage_results(wrapper_graph, compile_rows, live_enabled=False)
        self.assertFalse(wrapper["passed"])
        self.assertIn("UNRESOLVED_WRAPPER_TARGET", {row["code"] for row in wrapper["failures"]})

        live_missing = validation._procedure_compile_coverage_results(graph, compile_rows, live_enabled=True)
        self.assertFalse(live_missing["passed"])
        self.assertIn("LIVE_COMPILE_PROOF_MISSING", {row["code"] for row in live_missing["failures"]})

        failed_rows = [dict(row) for row in compile_rows]
        failed_rows[0].update({"status": "failed", "sanitized_error": "", "raw_sql_included": True})
        failed = validation._procedure_compile_coverage_results(graph, failed_rows, live_enabled=False)
        self.assertFalse(failed["passed"])
        codes = {row["code"] for row in failed["failures"]}
        self.assertIn("PROCEDURE_COMPILE_FAILED", codes)
        self.assertIn("FAILED_COMPILE_MISSING_SANITIZED_ERROR", codes)
        self.assertIn("PROCEDURE_COMPILE_RAW_SQL_INCLUDED", codes)

    def test_validation_drop_and_compact_evidence_artifacts_pass(self):
        validation = self._read_json("artifacts/snowflake_validation/validation_sql_results.json")
        compact = self._read_json("artifacts/snowflake_validation/compact_evidence_mart_validation_results.json")
        compact_detail = self._read_json("artifacts/snowflake_validation/compact_evidence_mart_detail_results.json")
        self.assertTrue(all(row["status"] == "passed" for row in validation), validation)
        self.assertTrue(compact["passed"], compact)
        self.assertTrue(compact_detail["passed"], compact_detail)
        self.assertEqual(compact["mart_count"], 5)
        self.assertEqual(compact_detail["mart_count"], 5)
        self.assertEqual(compact["normal_account_usage_count"], 0)
        self.assertTrue(all(row["target_lookup_columns"] for row in compact_detail["marts"]))
        self.assertTrue(all(row["retention_bounded"] for row in compact_detail["marts"]))

    def test_compact_evidence_detail_rejects_policy_gaps(self):
        from tools.contracts import snowflake_execution_validation as validation

        compact = self._read_json("artifacts/snowflake_validation/compact_evidence_mart_validation_results.json")
        missing_row = json.loads(json.dumps(compact))
        missing_row["marts"] = missing_row["marts"][1:]
        result = validation._compact_evidence_mart_detail_results(missing_row)
        self.assertFalse(result["passed"])
        self.assertIn("COMPACT_MART_ROW_MISSING", {row["code"] for row in result["failures"]})

        bad_detail = json.loads(json.dumps(compact))
        bad_detail["marts"][0].update(
            {
                "target_lookup_columns_present": False,
                "retention_bounded": False,
                "normal_account_usage_used": True,
                "max_rows": 501,
            }
        )
        result = validation._compact_evidence_mart_detail_results(bad_detail)
        self.assertFalse(result["passed"])
        codes = {row["code"] for row in result["failures"]}
        self.assertIn("COMPACT_MART_DETAIL_CHECK_FAILED", codes)
        self.assertIn("NORMAL_EVIDENCE_ACCOUNT_USAGE", codes)
        self.assertIn("COMPACT_MART_MAX_ROWS_OVER_500", codes)

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

    def test_recent_fix_manifest_encoding_and_schema_artifacts_pass(self):
        recent = self._read_json("artifacts/snowflake_validation/recent_snowflake_fix_validation_results.json")
        metric = self._read_json("artifacts/snowflake_validation/metric_candidate_shape_results.json")
        encoding = self._read_json("artifacts/snowflake_validation/sql_encoding_scan_results.json")
        schema = self._read_json("artifacts/snowflake_validation/schema_drift_results.json")
        manifest = self._read_json("artifacts/snowflake_validation/streamlit_manifest_validation_results.json")
        self.assertTrue(recent["passed"], recent)
        self.assertTrue(metric["passed"], metric)
        self.assertTrue(encoding["passed"], encoding)
        self.assertTrue(schema["passed"], schema)
        self.assertGreater(schema["commented_ddl_count"], 0)
        self.assertTrue(all(row["validation_metadata"] for row in schema["rows"]), schema)
        self.assertTrue(manifest["passed"], manifest)

    def test_trend_packet_and_refresh_artifacts_are_present(self):
        trend = self._read_json("artifacts/snowflake_validation/trend_cardinality_results.json")
        packet = self._read_json("artifacts/snowflake_validation/packet_shape_results.json")
        packet_detail = self._read_json("artifacts/snowflake_validation/packet_validation_detail_results.json")
        refresh_fast = self._read_json("artifacts/snowflake_validation/refresh_fast_results.json")
        refresh_full = self._read_json("artifacts/snowflake_validation/refresh_full_results.json")
        refresh_detail = self._read_json("artifacts/snowflake_validation/refresh_detail_results.json")
        smoke_coverage = self._read_json("artifacts/snowflake_validation/procedure_smoke_call_coverage_results.json")
        self.assertTrue(trend["passed"], trend)
        self.assertEqual(
            trend["join_key"],
            ["BRIEF_ID", "SECTION_NAME", "COMPANY", "ENVIRONMENT", "WINDOW_DAYS", "METRIC_KEY"],
        )
        self.assertTrue(packet["passed"], packet)
        self.assertTrue(packet_detail["passed"], packet_detail)
        self.assertEqual(packet_detail["check_count"], 14)
        self.assertEqual(refresh_fast["status"], "skipped")
        self.assertEqual(refresh_full["status"], "skipped")
        self.assertTrue(refresh_detail["passed"], refresh_detail)
        self.assertTrue(smoke_coverage["passed"], smoke_coverage)
        self.assertEqual(smoke_coverage["expected_smoke_target_count"], 8)

    def test_packet_refresh_and_smoke_detail_reject_gaps(self):
        from tools.contracts import snowflake_execution_validation as validation

        publication = self._read_json("artifacts/snowflake_validation/packet_publication_validation_results.json")
        shape = self._read_json("artifacts/snowflake_validation/packet_shape_results.json")
        size = self._read_json("artifacts/snowflake_validation/packet_size_results.json")
        truth = self._read_json("artifacts/snowflake_validation/packet_source_truth_results.json")
        bad_publication = json.loads(json.dumps(publication))
        bad_shape = json.loads(json.dumps(shape))
        for payload in (bad_publication, bad_shape):
            payload["checks"]["current_active_unique"] = False
        packet_detail = validation._packet_validation_detail_results(bad_publication, bad_shape, size, truth)
        self.assertFalse(packet_detail["passed"])
        self.assertIn("current_active_unique", {row["check_name"] for row in packet_detail["failures"]})

        bad_size = json.loads(json.dumps(size))
        bad_size["max_packet_bytes"] = 100001
        packet_detail = validation._packet_validation_detail_results(publication, shape, bad_size, truth)
        self.assertFalse(packet_detail["passed"])
        self.assertIn("max_packet_bytes_under_100kb", {row["check_name"] for row in packet_detail["failures"]})

        smoke_rows = self._read_json("artifacts/snowflake_validation/procedure_smoke_call_results.json")
        smoke_gap = validation._procedure_smoke_call_coverage_results(smoke_rows[1:], live_enabled=False)
        self.assertFalse(smoke_gap["passed"])
        self.assertIn("SMOKE_TARGET_MISSING", {row["code"] for row in smoke_gap["failures"]})

        live_skip = validation._procedure_smoke_call_coverage_results(smoke_rows, live_enabled=True)
        self.assertFalse(live_skip["passed"])
        self.assertIn("LIVE_SMOKE_TARGET_SKIPPED", {row["code"] for row in live_skip["failures"]})

        destructive = json.loads(json.dumps(smoke_rows))
        for row in destructive:
            if row.get("smoke_target") == "optional_optimization_status":
                row.update({"status": "passed", "mode": "live"})
        destructive_result = validation._procedure_smoke_call_coverage_results(destructive, live_enabled=True)
        self.assertFalse(destructive_result["passed"])
        self.assertIn("DESTRUCTIVE_SMOKE_CALL_WITHOUT_ALLOW_FLAG", {row["code"] for row in destructive_result["failures"]})

        refresh_fast = self._read_json("artifacts/snowflake_validation/refresh_fast_results.json")
        refresh_full = self._read_json("artifacts/snowflake_validation/refresh_full_results.json")
        bad_refresh = dict(refresh_fast)
        bad_refresh.update({"max_packet_bytes": 100001, "skip_reason": ""})
        refresh_detail = validation._refresh_detail_results(
            validation._load_script_texts(ROOT),
            bad_refresh,
            refresh_full,
            live_enabled=False,
        )
        self.assertFalse(refresh_detail["passed"])
        names = {row["check_name"] for row in refresh_detail["failures"]}
        self.assertIn("max_packet_bytes_under_100kb", names)
        self.assertIn("live_skip_reason_present_when_skipped", names)

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
        sanitizer = self._read_json("artifacts/snowflake_validation/snowflake_error_sanitization_results.json")
        self.assertTrue(sanitizer["passed"], sanitizer)

    def test_live_mode_without_session_fails_instead_of_claiming_runtime_proof(self):
        from tools.contracts import snowflake_execution_validation as validation

        with patch.object(validation, "_open_live_session", side_effect=RuntimeError("SELECT * FROM secret_table password=hidden")):
            rows = validation._static_smoke_results(True, ROOT)
        self.assertTrue(rows)
        self.assertTrue(all(row["status"] == "failed" for row in rows))
        self.assertTrue(all(row["raw_sql_included"] is False for row in rows))
        self.assertTrue(all("SELECT" not in row.get("sanitized_error", "").upper() for row in rows))
        self.assertTrue(all("hidden" not in row.get("sanitized_error", "") for row in rows))

        texts = validation._load_script_texts(ROOT)
        with patch.object(validation, "_open_live_session", side_effect=RuntimeError("CREATE OR REPLACE PROCEDURE SP_X() AS $$ SELECT * FROM secret_table; $$")):
            compile_rows = validation._compile_results(texts, live_enabled=True, root=ROOT)
        live_rows = [row for row in compile_rows if row["phase"] == "procedure_compile_live"]
        self.assertTrue(live_rows)
        self.assertTrue(all(row["status"] == "failed" for row in live_rows))
        self.assertTrue(all(row["raw_sql_included"] is False for row in live_rows))
        self.assertTrue(all("CREATE OR REPLACE" not in row.get("sanitized_error", "").upper() for row in live_rows))


if __name__ == "__main__":
    unittest.main()
