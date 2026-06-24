from pathlib import Path
import importlib.util
import json
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
PERF_ROOT = ROOT / "perf_tests"
PROFILE_PATH = PERF_ROOT / "profiles" / "12_power_users.json"
sys.path.insert(0, str(APP_ROOT))

import route_registry  # noqa: E402


def load_module(name: str, file_name: str):
    spec = importlib.util.spec_from_file_location(name, PERF_ROOT / file_name)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PowerUserBenchmarkContractTests(unittest.TestCase):
    def test_12_power_user_profile_exists_and_covers_primary_sections(self):
        self.assertTrue(PROFILE_PATH.exists())
        profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))

        self.assertEqual(profile["users"], 12)
        self.assertEqual(profile["iterations"], 3)
        self.assertEqual(profile["ramp_seconds"], 12)
        self.assertEqual(profile["sections"], list(route_registry.PRIMARY_SECTION_TITLES))
        self.assertEqual(profile["load_buttons"]["Alert Center"], "Load Issue Inbox")
        self.assertEqual(profile["load_buttons"]["Cost & Contract"], "Refresh Cost")

    def test_profile_contains_only_safe_load_buttons(self):
        runner = load_module("overwatch_live_runner_power_contract", "live_concurrent_runner.py")
        profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))

        for label in profile["load_buttons"].values():
            with self.subTest(label=label):
                self.assertEqual(runner.validate_safe_load_button_label(label), label)

    def test_power_user_runner_and_expert_review_exist(self):
        self.assertTrue((PERF_ROOT / "run_12_power_users.py").exists())
        self.assertTrue((PERF_ROOT / "power_user_review.py").exists())

    def test_expert_review_generator_outputs_panel_report(self):
        review = load_module("overwatch_power_user_review_contract", "power_user_review.py")
        payload = {
            "run_id": "PERF_12_POWER_USERS_UNIT",
            "summary": {
                "users": 12,
                "iterations": 3,
                "steps": 4,
                "measured_steps": 4,
                "skipped": 0,
                "errors": 0,
                "error_rate": 0.0,
                "p50_ms": 100,
                "p95_ms": 900,
                "p99_ms": 1100,
                "max_ms": 1200,
                "readiness_score": 100,
                "readiness_state": "PASS",
                "fail_p95_ms": 10000,
                "fail_error_rate": 0.0,
                "throughput_steps_per_sec": 2.5,
                "by_section": {"Alert Center": {"p95_ms": 900}},
                "by_action": {"section_nav": {"p95_ms": 900}},
            },
            "samples": [
                {
                    "user_id": 1,
                    "iteration": 1,
                    "section": "Alert Center",
                    "action": "section_nav",
                    "elapsed_ms": 900,
                    "ok": True,
                    "skipped": False,
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            live_report = Path(tmpdir) / "live.json"
            output = Path(tmpdir) / "review.md"
            live_report.write_text(json.dumps(payload), encoding="utf-8")
            code = review.main(["--live-report", str(live_report), "--output", str(output)])
            self.assertEqual(code, 0)
            markdown = output.read_text(encoding="utf-8")

        for fragment in (
            "Snowflake architect",
            "SRE/performance engineer",
            "Streamlit UX engineer",
            "FinOps/cost reviewer",
            "Security/admin reviewer",
            "DBA/operator",
            "PASS",
            "WATCH",
            "FAIL",
            "Recommended fixes",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, markdown)


if __name__ == "__main__":
    unittest.main()
