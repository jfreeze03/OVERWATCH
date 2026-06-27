import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class SqlPerformanceLintTests(unittest.TestCase):
    def test_linter_flags_fast_impl_shared_core_and_full_windows(self):
        from sql_performance_lint import lint_sql_text

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

    def test_repo_sql_performance_lint_artifact_has_no_errors(self):
        from sql_performance_lint import lint_sql_files

        paths = [
            *sorted((ROOT / "snowflake" / "mart_setup").glob("*.sql")),
            ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql",
        ]
        findings = lint_sql_files(paths, root=ROOT)
        errors = [finding for finding in findings if finding["severity"] == "error"]
        self.assertFalse(errors)


if __name__ == "__main__":
    unittest.main()
