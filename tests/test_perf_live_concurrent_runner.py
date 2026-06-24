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
        self.assertEqual(args.load_buttons["Alert Center"], "Load Issue Inbox")
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


if __name__ == "__main__":
    unittest.main()
