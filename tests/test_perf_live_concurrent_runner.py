import argparse
from pathlib import Path
import importlib.util
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PERF_ROOT = ROOT / "perf_tests"
PROFILE_PATH = PERF_ROOT / "profiles" / "12_power_users.json"


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
        self.assertTrue(args.wait_initial_idle)
        self.assertEqual(args.fail_p95_ms, 10000)
        self.assertEqual(args.fail_error_rate, 0.0)
        self.assertEqual(args.missing_load_button_wait_ms, 10000)

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


if __name__ == "__main__":
    unittest.main()
