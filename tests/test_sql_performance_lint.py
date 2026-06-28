import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class SqlPerformanceLintTests(unittest.TestCase):
    def test_linter_flags_fast_impl_shared_core_and_full_windows(self):
        from tools.contracts.sql_performance_lint import lint_sql_text

        findings = lint_sql_text(
            """
            CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS_FAST_IMPL()
            RETURNS VARCHAR
            LANGUAGE SQL
            AS
            $$
            BEGIN
              CALL SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS('FAST');
              SELECT 14;
            END;
            $$;
            CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS_FULL_IMPL()
            RETURNS VARCHAR
            LANGUAGE SQL
            AS $$ BEGIN RETURN 'ok'; END; $$;
            """,
            path="synthetic.sql",
        )
        codes = {finding["code"] for finding in findings}
        self.assertIn("FAST_IMPL_SHARED_CORE_CALL", codes)
        self.assertIn("FAST_IMPL_FULL_WINDOW", codes)
        self.assertNotIn("CALL SP_OVERWATCH", str(findings))

    def test_linter_flags_fast_impl_republish_from_current_flat(self):
        from tools.contracts.sql_performance_lint import lint_sql_text

        findings = lint_sql_text(
            """
            CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS_FAST_IMPL()
            RETURNS VARCHAR
            LANGUAGE SQL
            AS
            $$
            BEGIN
              CREATE OR REPLACE TEMPORARY TABLE TMP_FAST_SECTION_DECISION_PACKET_FLAT AS
              SELECT BRIEF_ID FROM MART_SECTION_DECISION_CURRENT_FLAT WHERE IS_ACTIVE;
            END;
            $$;
            CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS_FULL_IMPL()
            RETURNS VARCHAR
            LANGUAGE SQL
            AS $$ BEGIN RETURN 'ok'; END; $$;
            """,
            path="synthetic.sql",
        )
        codes = {finding["code"] for finding in findings}
        self.assertIn("FAST_IMPL_REPUBLISH_CURRENT_FLAT", codes)

    def test_linter_warns_fast_command_reuse_without_fresh_source_snapshot(self):
        from tools.contracts.sql_performance_lint import lint_sql_text

        findings = lint_sql_text(
            """
            CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS_FAST_IMPL()
            RETURNS VARCHAR
            LANGUAGE SQL
            AS
            $$
            BEGIN
              CREATE OR REPLACE TEMPORARY TABLE TMP_FAST_SECTION_COMMAND_BRIEF AS
              SELECT SECTION_NAME FROM MART_SECTION_COMMAND_BRIEF WHERE WINDOW_DAYS IN (1, 7);
            END;
            $$;
            CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS_FULL_IMPL()
            RETURNS VARCHAR
            LANGUAGE SQL
            AS $$ BEGIN RETURN 'ok'; END; $$;
            """,
            path="synthetic.sql",
        )
        self.assertIn(
            "FAST_IMPL_REUSES_COMMAND_MARTS_WITHOUT_SOURCE_SNAPSHOT",
            {finding["code"] for finding in findings},
        )
        self.assertIn(
            "FAST_IMPL_COMMAND_FRESHNESS_UNPROVEN",
            {finding["code"] for finding in findings},
        )

    def test_linter_modes_cover_first_paint_evidence_and_account_usage(self):
        from tools.contracts.sql_performance_lint import lint_sql_text

        good_packet = lint_sql_text(
            """
            SELECT BRIEF_ID, SECTION_NAME
            FROM MART_SECTION_DECISION_CURRENT_FLAT
            WHERE IS_ACTIVE
            LIMIT 1
            """,
            path="packet_lookup.sql",
            mode="app_first_paint",
        )
        self.assertFalse([finding for finding in good_packet if finding["severity"] == "error"])
        bad_packet = lint_sql_text(
            'SELECT DECISION_PACKET:"BRIEF_ID" FROM MART_SECTION_DECISION_CURRENT LIMIT 10',
            path="packet_lookup.sql",
            mode="app_first_paint",
        )
        bad_packet_codes = {finding["code"] for finding in bad_packet}
        self.assertIn("FIRST_PAINT_VARIANT_EXTRACTION", bad_packet_codes)
        self.assertIn("FIRST_PAINT_LIMIT_ONE_REQUIRED", bad_packet_codes)

        bad_evidence = lint_sql_text(
            "SELECT QUERY_ID FROM MART_QUERY_EVIDENCE_RECENT WHERE QUERY_ID IS NOT NULL LIMIT 500",
            path="evidence.sql",
            mode="evidence",
            target_context_present=True,
        )
        self.assertIn("EVIDENCE_TARGET_MARKER_REQUIRED", {finding["code"] for finding in bad_evidence})

        good_account_usage = lint_sql_text(
            """
            SELECT QUERY_ID
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE START_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP())
            LIMIT 10
            """,
            path="account_usage.sql",
            mode="account_usage_fallback",
        )
        self.assertFalse([finding for finding in good_account_usage if finding["severity"] == "error"])

    def test_linter_requires_account_usage_time_predicate_and_limit(self):
        from tools.contracts.sql_performance_lint import lint_sql_text

        bad = lint_sql_text(
            "SELECT QUERY_ID FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY LIMIT 10",
            path="synthetic.sql",
        )
        self.assertIn("ACCOUNT_USAGE_UNBOUNDED", {finding["code"] for finding in bad})
        good = lint_sql_text(
            """
            SELECT QUERY_ID
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE START_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP())
            LIMIT 10
            """,
            path="synthetic.sql",
            mode="account_usage_fallback",
        )
        self.assertNotIn("ACCOUNT_USAGE_UNBOUNDED", {finding["code"] for finding in good})

    def test_linter_rejects_always_true_timestamp_predicates(self):
        from tools.contracts.sql_performance_lint import lint_sql_text

        findings = lint_sql_text(
            """
            SELECT REFERENCING_OBJECT_NAME
            FROM SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES
            WHERE CURRENT_TIMESTAMP() >= DATEADD(day, -30, CURRENT_TIMESTAMP())
            LIMIT 100
            """,
            path="snowflake/OVERWATCH_DYNAMIC_TABLE_SECURE_VIEW_AUDIT.sql",
        )
        codes = {finding["code"] for finding in findings}
        self.assertIn("ALWAYS_TRUE_TIME_PREDICATE", codes)
        self.assertIn("ACCOUNT_USAGE_UNBOUNDED", codes)

    def test_secure_view_audit_uses_bounded_admin_object_dependency_scan(self):
        from tools.contracts.sql_performance_lint import lint_sql_files

        findings = lint_sql_files(
            [ROOT / "snowflake" / "OVERWATCH_DYNAMIC_TABLE_SECURE_VIEW_AUDIT.sql"],
            root=ROOT,
        )
        codes = {finding["code"] for finding in findings}
        self.assertNotIn("ALWAYS_TRUE_TIME_PREDICATE", codes)
        self.assertNotIn("ACCOUNT_USAGE_UNBOUNDED", codes)
        self.assertFalse([finding for finding in findings if finding["severity"] == "error"], findings)

    def test_linter_warns_limit_only_account_usage_without_order_or_predicate(self):
        from tools.contracts.sql_performance_lint import lint_sql_text

        findings = lint_sql_text(
            """
            SELECT QUERY_ID
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            LIMIT 25
            """,
            path="synthetic.sql",
        )
        self.assertIn("ACCOUNT_USAGE_LIMIT_WITHOUT_ORDER_OR_PREDICATE", {finding["code"] for finding in findings})

    def test_linter_query_search_mode_enforces_exact_related_and_projection(self):
        from tools.contracts.sql_performance_lint import lint_sql_text

        bad_exact = lint_sql_text(
            "SELECT QUERY_ID FROM FACT_QUERY_DETAIL_RECENT WHERE QUERY_ID = '01a' LIMIT 10",
            path="query_search_exact.sql",
            mode="query_search",
        )
        self.assertIn("QUERY_SEARCH_EXACT_LIMIT_ONE", {finding["code"] for finding in bad_exact})
        bad_projection = lint_sql_text(
            "SELECT QUERY_ID, QUERY_TEXT FROM FACT_QUERY_DETAIL_RECENT WHERE QUERY_ID = '01a' LIMIT 1",
            path="query_search_exact.sql",
            mode="query_search",
        )
        self.assertIn("QUERY_SEARCH_QUERY_TEXT_PROJECTION", {finding["code"] for finding in bad_projection})
        good_related = lint_sql_text(
            "SELECT 'query_search_related' AS PATH, QUERY_ID FROM FACT_QUERY_DETAIL_RECENT "
            "WHERE QUERY_HASH = 'abc' AND QUERY_ID <> '01a' LIMIT 50",
            path="query_search_related.sql",
            mode="query_search",
        )
        self.assertFalse([finding for finding in good_related if finding["severity"] == "error"])

    def test_linter_rejects_mixed_type_coalesce_without_cast(self):
        from tools.contracts.sql_performance_lint import lint_sql_text

        bad = lint_sql_text("SELECT COALESCE(TOP_ALERT_EVENT_ID, TOP_ALERT_KEY) AS TOP_ALERT_EVIDENCE_ID")
        self.assertIn("COALESCE_MIXED_TYPE_RISK", {finding["code"] for finding in bad})
        good = lint_sql_text("SELECT COALESCE(TOP_ALERT_EVENT_ID::VARCHAR, TOP_ALERT_KEY) AS TOP_ALERT_EVIDENCE_ID")
        self.assertNotIn("COALESCE_MIXED_TYPE_RISK", {finding["code"] for finding in good})

    def test_linter_rejects_metric_candidate_shape_failures(self):
        from tools.contracts.sql_performance_lint import lint_sql_text

        sql = (ROOT / "snowflake/mart_setup/05_load_procedures.sql").read_text(encoding="utf-8")
        bad_confidence = sql.replace("TREND_LABEL, CONFIDENCE, 10 AS SORT_ORDER", "TREND_LABEL, 10 AS SORT_ORDER", 1)
        findings = lint_sql_text(bad_confidence, path="snowflake/mart_setup/05_load_procedures.sql")
        self.assertIn("METRIC_UNION_BRANCH_MISSING_CONFIDENCE", {finding["code"] for finding in findings})

        scalar_trend = sql.replace("tr.TREND_POINTS", "(SELECT tr.TREND_POINTS FROM TMP_SECTION_METRIC_TRENDS tr)", 1)
        scalar_findings = lint_sql_text(scalar_trend, path="snowflake/mart_setup/05_load_procedures.sql")
        self.assertIn("SCALAR_TREND_SUBQUERY_PRESENT", {finding["code"] for finding in scalar_findings})

    def test_linter_rejects_sql_encoding_artifacts(self):
        from tools.contracts.sql_performance_lint import lint_sql_text

        bom = lint_sql_text("\ufeffSELECT 1", path="snowflake/synthetic.sql")
        self.assertIn("SQL_FILE_BOM", {finding["code"] for finding in bom})
        replacement = lint_sql_text("SELECT '\ufffd'", path="snowflake/synthetic.sql")
        self.assertIn("SQL_REPLACEMENT_CHARACTER", {finding["code"] for finding in replacement})
        mojibake = lint_sql_text("SELECT '" + "\u00e2\u20ac\u2122" + "'", path="snowflake/synthetic.sql")
        self.assertIn("SQL_MOJIBAKE_RISK", {finding["code"] for finding in mojibake})

    def test_linter_flags_select_star_app_facing_sql(self):
        from tools.contracts.sql_performance_lint import lint_sql_text

        findings = lint_sql_text("SELECT * FROM APP_FACING_TABLE LIMIT 10", path="synthetic.sql")
        self.assertIn("APP_FACING_SELECT_STAR", {finding["code"] for finding in findings})
        finding = findings[0]
        self.assertGreater(int(finding["risk_score"]), 0)
        self.assertTrue(finding["expected_pruning_key"])
        self.assertTrue(finding["recommended_replacement"])
        self.assertFalse(finding["raw_sql_included"])

    def test_repo_sql_performance_lint_artifact_has_no_errors(self):
        from tools.contracts.sql_performance_lint import lint_sql_files

        paths = [
            *sorted((ROOT / "snowflake").rglob("*.sql")),
        ]
        findings = lint_sql_files(paths, root=ROOT)
        errors = [finding for finding in findings if finding["severity"] == "error"]
        self.assertFalse(errors)
        severity_order = {"error": 0, "warning": 1, "info": 2}
        sorted_findings = sorted(
            findings,
            key=lambda finding: (
                severity_order.get(str(finding.get("severity") or "").lower(), 9),
                -int(finding.get("risk_score") or 0),
                str(finding.get("code") or ""),
            ),
        )
        self.assertEqual(findings, sorted_findings)


if __name__ == "__main__":
    unittest.main()
