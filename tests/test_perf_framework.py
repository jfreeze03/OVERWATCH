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


def load_live_runner():
    spec = importlib.util.spec_from_file_location(
        "overwatch_live_concurrent_runner",
        PERF_ROOT / "live_concurrent_runner.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_section_smoke_runner():
    spec = importlib.util.spec_from_file_location(
        "overwatch_section_smoke_runner",
        PERF_ROOT / "section_smoke_runner.py",
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
        self.assertIn("TRY_TO_NUMBER(TO_VARCHAR(\"AUTO_SUSPEND\"))", setup_sql)
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
        self.assertTrue(any("section render validation" in item.lower() for item in recommendations))

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
        self.assertIn("live_concurrent_runner.py", readme)
        self.assertIn("--no-load-buttons", readme)
        self.assertIn("--missing-load-button fail", readme)
        self.assertIn("section timing", readme)
        self.assertIn("99_cleanup_perf_test.sql", readme)
        self.assertIn("PERF_TEST_PRODUCTION_READINESS_V", readme)

    def test_snowflake_readiness_scores_latest_perf_run_only(self):
        report_sql = (PERF_ROOT / "sql" / "04_benchmark_report.sql").read_text(encoding="utf-8").upper()

        self.assertIn("LAST_QUERY_TIME", report_sql)
        self.assertIn("LATEST_SF_PERF", report_sql)
        self.assertIn("PERF_RUN_ID <> 'PERF:UNLABELED'", report_sql)
        self.assertIn("QUALIFY ROW_NUMBER() OVER (ORDER BY LAST_QUERY_TIME DESC", report_sql)

    def test_snowflake_safe_suite_runner_is_guarded(self):
        runner_text = (PERF_ROOT / "run_snowflake_safe_suite.py").read_text(encoding="utf-8")
        runner = load_snowflake_runner()

        self.assertIn("SP_PERF_TEST_GUARDRAIL_CHECK('LIGHTWEIGHT_METADATA', FALSE)", runner_text)
        self.assertIn("not guard_message.upper().startswith(\"OK:\")", runner_text)
        self.assertIn("SAFE_SQL_FILES", runner_text)
        self.assertIn("connection.execute_stream(handle, remove_comments=True)", runner_text)
        self.assertNotIn("cursor().execute_stream", runner_text)
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
        runner = load_section_smoke_runner()
        runner_text = (PERF_ROOT / "section_smoke_runner.py").read_text(encoding="utf-8")

        self.assertIn("DEFAULT_SECTIONS", runner_text)
        self.assertIn("Cost & Contract", runner_text)
        self.assertIn("DBA Control Room", runner.DEFAULT_SECTIONS)
        self.assertNotIn("Account Health", runner.DEFAULT_SECTIONS)
        self.assertIn("load_playwright", runner_text)
        self.assertIn("wait_for_app_ready", runner_text)
        self.assertIn('page.locator(".ow-section-title").first.wait_for', runner_text)
        self.assertIn("get_by_role(\"button\"", runner_text)
        self.assertIn("_sections.json", runner_text)

    def test_live_concurrent_runner_uses_only_safe_load_buttons(self):
        runner = load_live_runner()
        runner_text = (PERF_ROOT / "live_concurrent_runner.py").read_text(encoding="utf-8")
        readme = (PERF_ROOT / "README.md").read_text(encoding="utf-8")
        unsafe_tokens = ("Grant", "Save", "Queue", "Send", "Retry", "Suspend", "Resume", "Cancel", "Drop", "Alter")

        self.assertIn("DEFAULT_LOAD_BUTTONS", runner_text)
        self.assertEqual(runner.DEFAULT_LOAD_BUTTONS["Cost & Contract"], "Refresh Cost Details")
        self.assertEqual(runner.DEFAULT_LOAD_BUTTONS["Alert Center"], "Load Issue Inbox")
        self.assertIn("Alert Center: `Load Issue Inbox`", readme)
        self.assertIn("Cost & Contract: `Refresh Cost Details`", readme)
        self.assertNotIn("Account Health", runner.DEFAULT_LOAD_BUTTONS)
        self.assertNotIn("Warehouse Health", runner.DEFAULT_LOAD_BUTTONS)
        self.assertNotIn("Change & Drift", runner.DEFAULT_LOAD_BUTTONS)
        for label in runner.DEFAULT_LOAD_BUTTONS.values():
            self.assertTrue(label.startswith(("Load", "Refresh")))
            self.assertFalse(any(token in label for token in unsafe_tokens), label)

    def test_live_concurrent_runner_fail_mode_waits_full_button_timeout(self):
        runner_text = (PERF_ROOT / "live_concurrent_runner.py").read_text(encoding="utf-8")

        self.assertIn('button_wait_ms = timeout_ms if missing_behavior == "fail"', runner_text)
        self.assertIn("wait_for_named_button(page, label, button_wait_ms)", runner_text)

    def test_live_concurrent_runner_can_wait_for_initial_idle(self):
        runner = load_live_runner()
        runner_text = (PERF_ROOT / "live_concurrent_runner.py").read_text(encoding="utf-8")

        args = runner.parse_args(["--wait-initial-idle"])

        self.assertTrue(args.wait_initial_idle)
        self.assertIn("if args.wait_initial_idle:", runner_text)
        self.assertIn("wait_for_streamlit_idle(page, args.timeout_ms, args.action_settle_ms)", runner_text)

    def test_live_concurrent_runner_supports_single_initial_load_mode(self):
        runner = load_live_runner()
        runner_text = (PERF_ROOT / "live_concurrent_runner.py").read_text(encoding="utf-8")

        args = runner.parse_args(["--single-initial-load"])

        self.assertTrue(args.single_initial_load)
        self.assertIn("if args.single_initial_load:", runner_text)
        self.assertIn("if not args.single_initial_load:", runner_text)
        self.assertIn("Load the app once per user", runner_text)

    def test_live_concurrent_runner_summarizes_browser_steps(self):
        runner = load_live_runner()
        samples = [
            runner.StepSample(1, 1, "App Shell", "initial_load", 500.0, True),
            runner.StepSample(1, 1, "Cost & Contract", "section_nav", 900.0, True),
            runner.StepSample(1, 1, "Cost & Contract", "load_button:Refresh Cost Details", 3000.0, True),
            runner.StepSample(2, 1, "Cost & Contract", "load_button:Refresh Cost Details", 5000.0, False, "boom"),
            runner.StepSample(2, 1, "Warehouse Health", "load_button:Load Capacity Brief", 8.0, True, skipped=True),
        ]
        args = runner.parse_args([
            "--url", "http://localhost:8501/",
            "--users", "2",
            "--iterations", "1",
            "--fail-p95-ms", "6000",
            "--fail-error-rate", "0.30",
        ])
        summary = runner.summarize(samples, 8.0, args)

        self.assertEqual(summary["steps"], 5)
        self.assertEqual(summary["measured_steps"], 4)
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["errors"], 1)
        self.assertIn("Cost & Contract", summary["by_section"])
        self.assertIn("load_button:Refresh Cost Details", summary["by_action"])
        self.assertIn(summary["readiness_state"], {"PASS", "WATCH"})
