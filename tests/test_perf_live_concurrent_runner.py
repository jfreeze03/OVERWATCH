import argparse
from pathlib import Path
import importlib.util
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PERF_ROOT = ROOT / "perf_tests"
PROFILE_PATH = PERF_ROOT / "profiles" / "12_power_users.json"
INITIAL_LOAD_PROFILE_PATH = PERF_ROOT / "profiles" / "12_power_users_initial_load_only.json"


def load_live_runner():
    spec = importlib.util.spec_from_file_location(
        "overwatch_live_concurrent_runner_profile_tests",
        PERF_ROOT / "live_concurrent_runner.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class LiveConcurrentProfileTests(unittest.TestCase):
    def test_profile_values_are_loaded(self):
        runner = load_live_runner()

        args = runner.parse_args(["--profile", str(PROFILE_PATH)])

        self.assertEqual(args.users, 12)
        self.assertEqual(args.iterations, 3)
        self.assertEqual(args.ramp_seconds, 12)
        self.assertTrue(args.single_initial_load)
        self.assertTrue(args.fail_console_errors)
        self.assertTrue(args.initial_load_substeps)
        self.assertTrue(args.wait_initial_idle)
        self.assertEqual(args.fail_p95_ms, 10000)
        self.assertEqual(args.fail_error_rate, 0.0)
        self.assertEqual(args.missing_load_button_wait_ms, 10000)

    def test_initial_load_only_profile_is_diagnostic_not_release_gate(self):
        runner = load_live_runner()

        args = runner.parse_args(["--profile", str(INITIAL_LOAD_PROFILE_PATH)])

        self.assertEqual(args.users, 12)
        self.assertEqual(args.iterations, 1)
        self.assertTrue(args.single_initial_load)
        self.assertTrue(args.initial_load_substeps)
        self.assertTrue(args.wait_initial_idle)
        self.assertEqual(args.sections, [])
        self.assertFalse(args.load_buttons)

    def test_perf_run_url_preserves_existing_query_params(self):
        runner = load_live_runner()

        url = runner.perf_run_url(
            "http://localhost:8503/?foo=bar&overwatch_theme=carbon",
            run_id="RUN42",
            user_id=7,
            iteration=2,
        )

        self.assertIn("foo=bar", url)
        self.assertIn("overwatch_theme=carbon", url)
        self.assertIn("overwatch_perf_run_id=RUN42", url)
        self.assertIn("overwatch_perf_user=7", url)
        self.assertIn("overwatch_perf_iteration=2", url)

    def test_cli_overrides_profile_values(self):
        runner = load_live_runner()

        args = runner.parse_args([
            "--profile",
            str(PROFILE_PATH),
            "--users",
            "3",
            "--iterations",
            "1",
            "--no-wait-initial-idle",
            "--fail-p95-ms",
            "15000",
        ])

        self.assertEqual(args.users, 3)
        self.assertEqual(args.iterations, 1)
        self.assertFalse(args.wait_initial_idle)
        self.assertEqual(args.fail_p95_ms, 15000)

    def test_profile_sections_and_load_button_mapping_are_preserved(self):
        runner = load_live_runner()

        args = runner.parse_args(["--profile", str(PROFILE_PATH)])

        self.assertEqual(
            args.sections,
            [
                "Executive Landing",
                "DBA Control Room",
                "Alert Center",
                "Cost & Contract",
                "Workload Operations",
                "Security Monitoring",
            ],
        )
        self.assertEqual(args.load_buttons["Alert Center"], "Load Active Alerts")
        self.assertEqual(args.load_buttons["Cost & Contract"], "Refresh Cost")
        self.assertEqual(runner.active_load_button_map(args.load_buttons), args.load_buttons)

    def test_bool_load_buttons_preserve_existing_defaults(self):
        runner = load_live_runner()

        args = runner.parse_args(["--load-buttons"])

        self.assertTrue(args.load_buttons)
        self.assertEqual(runner.active_load_button_map(args.load_buttons), runner.DEFAULT_LOAD_BUTTONS)

    def test_forbidden_profile_load_buttons_are_rejected(self):
        runner = load_live_runner()
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            handle.write('{"load_buttons": {"Alert Center": "Route to Action Queue"}}')
            path = handle.name
        self.addCleanup(lambda: Path(path).unlink(missing_ok=True))

        with self.assertRaises(ValueError):
            runner.parse_args(["--profile", path])

    def test_safe_profile_load_buttons_are_accepted(self):
        runner = load_live_runner()

        label = runner.validate_safe_load_button_label("Refresh Cost")

        self.assertEqual(label, "Refresh Cost")

    def test_idle_wait_uses_visible_busy_elements_not_page_text(self):
        runner_source = (PERF_ROOT / "live_concurrent_runner.py").read_text(encoding="utf-8")
        idle_wait_source = runner_source.split("async def wait_for_streamlit_idle", 1)[1].split(
            "async def wait_for_section",
            1,
        )[0]

        self.assertIn("getClientRects().length > 0", idle_wait_source)
        self.assertIn('[data-testid="stSpinner"]', idle_wait_source)
        self.assertIn('[data-testid="stStatusWidget"]', idle_wait_source)
        self.assertNotIn("document.body ? document.body.innerText", idle_wait_source)
        self.assertNotIn('text.includes("Please wait...")', idle_wait_source)

    def test_section_navigation_measures_visible_route_before_load_idle(self):
        runner_source = (PERF_ROOT / "live_concurrent_runner.py").read_text(encoding="utf-8")
        section_nav_source = runner_source.split("async def section_nav", 1)[1].split(
            "nav_sample = await timed_step",
            1,
        )[0]

        self.assertIn("await wait_for_section(page, section_name, args.timeout_ms)", section_nav_source)
        self.assertNotIn("await wait_for_streamlit_idle", section_nav_source)

    def test_section_transition_wait_uses_visibility_not_detached_dom(self):
        runner_source = (PERF_ROOT / "live_concurrent_runner.py").read_text(encoding="utf-8")
        transition_wait_source = runner_source.split("async def wait_for_transition_clear", 1)[1].split(
            "async def wait_for_section",
            1,
        )[0]
        wait_for_section_source = runner_source.split("async def wait_for_section", 1)[1].split(
            "async def wait_for_app_ready",
            1,
        )[0]

        self.assertIn("getClientRects().length > 0", transition_wait_source)
        self.assertIn('querySelectorAll(".ow-section-transition")', transition_wait_source)
        self.assertIn("wait_for_transition_clear(page, timeout_ms)", wait_for_section_source)
        self.assertNotIn('state="detached"', wait_for_section_source)

    def test_summary_reports_p95_release_blocker(self):
        runner = load_live_runner()
        args = argparse.Namespace(users=2, iterations=1, fail_p95_ms=10000, fail_error_rate=0.0)
        samples = [
            runner.StepSample(1, 1, "App Shell", "initial_load", 12000.0, True),
            runner.StepSample(2, 1, "App Shell", "initial_load", 15000.0, True),
            runner.StepSample(2, 1, "DBA Control Room", "section_nav", 2000.0, True),
        ]

        summary = runner.summarize(samples, 1.0, args)

        self.assertIn("p95_threshold", {item["type"] for item in summary["release_blockers"]})

    def test_summary_reports_skipped_load_button_blocker(self):
        runner = load_live_runner()
        args = argparse.Namespace(users=1, iterations=1, fail_p95_ms=10000, fail_error_rate=0.0)
        samples = [
            runner.StepSample(1, 1, "Alert Center", "section_nav", 200.0, True),
            runner.StepSample(
                1,
                1,
                "Alert Center",
                "load_button:Load Active Alerts",
                0.0,
                True,
                skipped=True,
            ),
        ]

        summary = runner.summarize(samples, 1.0, args)

        self.assertIn("skipped_load_buttons", {item["type"] for item in summary["release_blockers"]})

    def test_summary_identifies_initial_load_when_slowest(self):
        runner = load_live_runner()
        args = argparse.Namespace(users=2, iterations=1, fail_p95_ms=10000, fail_error_rate=0.0)
        samples = [
            runner.StepSample(1, 1, "App Shell", "initial_load", 8000.0, True),
            runner.StepSample(1, 1, "DBA Control Room", "section_nav", 1200.0, True),
            runner.StepSample(2, 1, "Alert Center", "section_nav", 900.0, True),
        ]

        summary = runner.summarize(samples, 1.0, args)

        self.assertEqual(summary["slowest_step"]["action"], "initial_load")
        self.assertEqual(summary["top_slowest_actions"][0]["action"], "initial_load")
        self.assertEqual(summary["step_counts"]["initial_load"], 1)

    def test_summary_groups_skipped_buttons_by_label(self):
        runner = load_live_runner()
        args = argparse.Namespace(users=3, iterations=1, fail_p95_ms=10000, fail_error_rate=0.0)
        samples = [
            runner.StepSample(1, 1, "Alert Center", "section_nav", 200.0, True),
            runner.StepSample(1, 1, "Alert Center", "load_button:Load Active Alerts", 0.0, True, skipped=True),
            runner.StepSample(2, 1, "Alert Center", "load_button:Load Active Alerts", 0.0, True, skipped=True),
            runner.StepSample(3, 1, "Cost & Contract", "load_button:Refresh Cost", 0.0, True, skipped=True),
        ]

        summary = runner.summarize(samples, 1.0, args)

        self.assertEqual(summary["skipped_by_label"]["Load Active Alerts"], 2)
        self.assertEqual(summary["skipped_by_label"]["Refresh Cost"], 1)
        self.assertEqual(summary["step_counts"]["load_button"], 3)

    def test_summary_groups_browser_error_messages(self):
        runner = load_live_runner()
        args = argparse.Namespace(users=1, iterations=1, fail_p95_ms=10000, fail_error_rate=0.0)
        samples = [
            runner.StepSample(
                1,
                1,
                "Executive Landing",
                "section_nav",
                250.0,
                False,
                browser_errors=2,
                browser_error_messages=["console boom", "console boom"],
            ),
        ]

        summary = runner.summarize(samples, 1.0, args)

        self.assertEqual(summary["browser_error_messages"][0], {"message": "console boom", "count": 2})
        self.assertIn("browser_errors", {item["type"] for item in summary["release_blockers"]})

    def test_diagnostic_samples_are_excluded_from_release_scoring(self):
        runner = load_live_runner()
        args = argparse.Namespace(users=1, iterations=1, fail_p95_ms=10000, fail_error_rate=0.0)
        samples = [
            runner.StepSample(1, 1, "App Shell", "initial_load", 900.0, True),
            runner.StepSample(
                1,
                1,
                "App Shell",
                "initial_load:app_ready",
                50000.0,
                False,
                browser_errors=1,
                browser_error_messages=["diagnostic only"],
                diagnostic=True,
            ),
        ]

        summary = runner.summarize(samples, 1.0, args)

        self.assertEqual(summary["steps"], 1)
        self.assertEqual(summary["diagnostic_steps"], 1)
        self.assertEqual(summary["p95_ms"], 900.0)
        self.assertEqual(summary["errors"], 0)
        self.assertEqual(summary["browser_error_steps"], 0)
        self.assertEqual(summary["release_throughput_steps_per_sec"], 1.0)
        self.assertEqual(summary["diagnostic_throughput_steps_per_sec"], 1.0)
        self.assertEqual(summary["readiness_state"], "PASS")
        self.assertNotIn("p95_threshold", {item["type"] for item in summary["release_blockers"]})
        self.assertEqual(summary["diagnostic_by_action"]["initial_load:app_ready"]["p95_ms"], 50000.0)
        self.assertEqual(summary["initial_load_breakdown"][0]["action"], "initial_load:app_ready")

    def test_diagnostic_samples_are_written_to_reports(self):
        runner = load_live_runner()
        args = argparse.Namespace(
            url="http://localhost:8501/",
            users=1,
            iterations=1,
            sections=["Executive Landing"],
            load_buttons=False,
            output_dir="",
            run_id="DIAGNOSTIC_REPORT_TEST",
        )
        samples = [
            runner.StepSample(1, 1, "App Shell", "initial_load", 900.0, True),
            runner.StepSample(
                1,
                1,
                "App Shell",
                "initial_load:goto_domcontentloaded",
                200.0,
                True,
                diagnostic=True,
                detail={
                    "perf_trace": {
                        "samples": [
                            {"phase": "shell:probe_snowflake_available", "elapsed_ms": 12.5}
                        ]
                    },
                    "navigation_timing": {"responseStart": 30.0},
                    "paint_timing": {"first-contentful-paint": 55.0},
                },
            ),
        ]
        summary = runner.summarize(
            samples,
            1.0,
            argparse.Namespace(users=1, iterations=1, fail_p95_ms=10000, fail_error_rate=0.0),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            args.output_dir = temp_dir

            json_path, md_path = runner.write_reports(args, samples, summary)

            payload = json_path.read_text(encoding="utf-8")
            markdown = md_path.read_text(encoding="utf-8")
        self.assertIn('"diagnostic": true', payload)
        self.assertIn("Diagnostic Action P95", markdown)
        self.assertIn("Initial Load Breakdown", markdown)
        self.assertIn("goto_domcontentloaded", markdown)
        self.assertIn("Server Phase Breakdown", markdown)
        self.assertIn("Browser Navigation Timing", markdown)
        self.assertIn("Browser Paint Timing", markdown)
        self.assertEqual(summary["server_phase_breakdown"][0]["phase"], "shell:probe_snowflake_available")
        self.assertEqual(summary["browser_navigation_timing"][0]["metric"], "responseStart")


if __name__ == "__main__":
    unittest.main()
