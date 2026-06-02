from pathlib import Path
import importlib.util
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PERF_ROOT = ROOT / "perf_tests"


def load_perf_runner():
    spec = importlib.util.spec_from_file_location("overwatch_perf_runner", PERF_ROOT / "perf_runner.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_snowflake_runner():
    spec = importlib.util.spec_from_file_location(
        "overwatch_snowflake_perf_runner",
        PERF_ROOT / "run_snowflake_safe_suite.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PerformanceFrameworkTests(unittest.TestCase):
    def test_perf_sql_scripts_are_guarded_and_cleanup_is_scoped(self):
        setup_sql = (PERF_ROOT / "sql" / "01_perf_test_setup.sql").read_text(encoding="utf-8").upper()
        synthetic_sql = (PERF_ROOT / "sql" / "02_generate_synthetic_light_medium.sql").read_text(encoding="utf-8").upper()
        full_sql = (PERF_ROOT / "sql" / "03_generate_full_5tb_physical_BLOCKED_BY_DEFAULT.sql").read_text(encoding="utf-8").upper()
        cleanup_sql = (PERF_ROOT / "sql" / "99_cleanup_perf_test.sql").read_text(encoding="utf-8").upper()

        self.assertIn("SP_PERF_TEST_GUARDRAIL_CHECK", setup_sql)
        self.assertIn("FULL_5TB_ALLOWED", setup_sql)
        self.assertIn("MAX_ALLOWED_WAREHOUSE_SIZE", setup_sql)
        self.assertIn("AUTO_SUSPEND", setup_sql)
        self.assertIn("PERF_TEST_QUERY_HISTORY", synthetic_sql)
        self.assertIn("PERF_TEST_WAREHOUSE_METERING_HISTORY", synthetic_sql)
        self.assertIn("PERF_TEST_TASK_HISTORY", synthetic_sql)
        self.assertIn("PERF_TEST_PROCEDURE_EXECUTION", synthetic_sql)
        self.assertIn("PERF_TEST_SCALE_SUMMARY_V", synthetic_sql)
        self.assertIn("SET ALLOW_FULL_5TB = FALSE", full_sql)
        self.assertIn("CREATE OR REPLACE TABLE PERF_TEST_5TB_PHYSICAL_FACT", full_sql)
        self.assertNotIn("DROP TABLE IF EXISTS OVERWATCH_", cleanup_sql)
        self.assertIn("DROP TABLE IF EXISTS PERF_TEST_QUERY_HISTORY", cleanup_sql)

    def test_perf_runner_summarizes_latency_and_writes_reports(self):
        runner = load_perf_runner()
        samples = [
            runner.Sample(1, 1, 200, 100.0, 1000, True),
            runner.Sample(2, 1, 200, 250.0, 1000, True),
            runner.Sample(3, 1, 200, 500.0, 1000, True),
            runner.Sample(4, 1, 500, 900.0, 0, False, "boom"),
        ]
        summary = runner.summarize(samples, 1.5, fail_p95_ms=1000, fail_error_rate=0.30)

        self.assertEqual(summary["requests"], 4)
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["p95_ms"], 900.0)
        self.assertIn("first_iteration_p95_ms", summary)
        self.assertIn("cold_start_gap_pct", summary)
        self.assertIn(summary["readiness_state"], {"PASS", "WATCH"})
        recommendations = runner.build_recommendations(summary, samples, "metadata")
        self.assertTrue(any("section smoke runner" in item.lower() for item in recommendations))

        with tempfile.TemporaryDirectory() as tmpdir:
            args = type("Args", (), {
                "output_dir": tmpdir,
                "run_id": "PERF_TEST_UNIT",
                "url": "http://localhost:8501/",
                "mode": "metadata",
                "users": 4,
                "iterations": 1,
            })()
            json_path, md_path = runner.write_reports(args, samples, summary)
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            markdown = md_path.read_text(encoding="utf-8")
            self.assertIn("OVERWATCH Performance Run", markdown)
            self.assertIn("Recommended Next Actions", markdown)

    def test_perf_readme_documents_modes_and_rollback(self):
        readme = (PERF_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("metadata", readme)
        self.assertIn("medium", readme)
        self.assertIn("full_5tb", readme)
        self.assertIn("section_smoke_runner.py", readme)
        self.assertIn("section timing", readme)
        self.assertIn("99_cleanup_perf_test.sql", readme)
        self.assertIn("PERF_TEST_PRODUCTION_READINESS_V", readme)

    def test_snowflake_safe_suite_runner_is_guarded(self):
        runner_text = (PERF_ROOT / "run_snowflake_safe_suite.py").read_text(encoding="utf-8")
        runner = load_snowflake_runner()

        self.assertIn("SP_PERF_TEST_GUARDRAIL_CHECK('LIGHTWEIGHT_METADATA', FALSE)", runner_text)
        self.assertIn("not guard_message.upper().startswith(\"OK:\")", runner_text)
        self.assertIn("SAFE_SQL_FILES", runner_text)
        self.assertNotIn("03_generate_full_5tb_physical", runner_text)
        self.assertEqual(
            runner.SAFE_SQL_FILES,
            (
                "01_perf_test_setup.sql",
                "02_generate_synthetic_light_medium.sql",
                "04_benchmark_report.sql",
            ),
        )

        args = runner.parse_args(["--run-id", "PERF_SQL_UNIT"])
        self.assertEqual(args.run_id, "PERF_SQL_UNIT")

    def test_section_smoke_runner_is_optional_navigation_coverage(self):
        runner_text = (PERF_ROOT / "section_smoke_runner.py").read_text(encoding="utf-8")

        self.assertIn("DEFAULT_SECTIONS", runner_text)
        self.assertIn("Cost & Contract", runner_text)
        self.assertIn("load_playwright", runner_text)
        self.assertIn("wait_for_app_ready", runner_text)
        self.assertIn('page.locator(".ow-section-title").first.wait_for', runner_text)
        self.assertIn("get_by_role(\"button\"", runner_text)
        self.assertIn("_sections.json", runner_text)
