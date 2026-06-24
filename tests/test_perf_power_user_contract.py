from pathlib import Path
import importlib.util
import json
import re
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
PERF_ROOT = ROOT / "perf_tests"
PROFILE_PATH = PERF_ROOT / "profiles" / "12_power_users.json"
RELEASE_EVIDENCE = ROOT / "docs" / "releases" / "OVERWATCH_RELEASE_EVIDENCE_24cd05e_2026-06-24.md"
RELEASE_MANIFEST = ROOT / "docs" / "OVERWATCH_RELEASE_MANIFEST.md"
TUNING_GUIDE = ROOT / "docs" / "OVERWATCH_12_POWER_USER_TUNING.md"
sys.path.insert(0, str(APP_ROOT))

import route_registry  # noqa: E402


def load_module(name: str, file_name: str):
    spec = importlib.util.spec_from_file_location(name, PERF_ROOT / file_name)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def section(text: str, heading: str) -> str:
    start = text.index(heading)
    next_heading = text.find("\n## ", start + len(heading))
    if next_heading == -1:
        return text[start:]
    return text[start:next_heading]


class PowerUserBenchmarkContractTests(unittest.TestCase):
    def test_12_power_user_profile_exists_and_covers_primary_sections(self):
        self.assertTrue(PROFILE_PATH.exists())
        profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))

        self.assertEqual(profile["users"], 12)
        self.assertEqual(profile["iterations"], 3)
        self.assertEqual(profile["ramp_seconds"], 12)
        self.assertEqual(profile["sections"], list(route_registry.PRIMARY_SECTION_TITLES))
        self.assertEqual(profile["load_buttons"]["Alert Center"], "Load Active Alerts")
        self.assertEqual(profile["load_buttons"]["Cost & Contract"], "Refresh Cost")

    def test_profile_contains_only_safe_load_buttons(self):
        runner = load_module("overwatch_live_runner_power_contract", "live_concurrent_runner.py")
        profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))

        for label in profile["load_buttons"].values():
            with self.subTest(label=label):
                self.assertEqual(runner.validate_safe_load_button_label(label), label)

    def test_profile_does_not_include_mutation_controls(self):
        runner = load_module("overwatch_live_runner_mutation_contract", "live_concurrent_runner.py")
        profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))

        for section_name, label in profile["load_buttons"].items():
            with self.subTest(section=section_name, label=label):
                normalized = label.casefold()
                for token in runner.FORBIDDEN_LOAD_BUTTON_TOKENS:
                    self.assertNotIn(token, normalized)

    def test_alert_center_profile_label_matches_default_visible_load_button(self):
        profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        contracts = (APP_ROOT / "sections" / "alert_center_contracts.py").read_text(encoding="utf-8")
        alert_center = (APP_ROOT / "sections" / "alert_center.py").read_text(encoding="utf-8")
        match = re.search(r'ALERT_CENTER_DEFAULT_VIEW = "([^"]+)"', contracts)
        self.assertIsNotNone(match)

        self.assertEqual(profile["load_buttons"]["Alert Center"], f"Load {match.group(1)}")
        self.assertIn('st.button(f"Load {source_view}"', alert_center)

    def test_release_evidence_records_power_user_metrics(self):
        text = RELEASE_EVIDENCE.read_text(encoding="utf-8")
        power_section = section(text, "## 12 Power User Performance")

        for field in (
            "p95",
            "p99",
            "errors",
            "readiness",
            "slowest section",
            "slowest action",
            "skipped buttons",
        ):
            with self.subTest(field=field):
                self.assertRegex(power_section, rf"- {re.escape(field)}: `[^`]+`")

    def test_release_evidence_artifact_paths_have_storage_policy(self):
        text = RELEASE_EVIDENCE.read_text(encoding="utf-8")
        power_section = section(text, "## 12 Power User Performance")
        lower_section = power_section.casefold()
        has_outside_git_policy = "stored outside git" in lower_section and "reason:" in lower_section

        for label in ("live report path", "expert review path"):
            with self.subTest(label=label):
                match = re.search(rf"- {label}: `([^`]+)`", power_section)
                self.assertIsNotNone(match)
                report_path = ROOT / match.group(1)
                self.assertTrue(report_path.exists() or has_outside_git_policy)

    def test_skipped_power_user_buttons_are_named_or_manifest_is_candidate(self):
        evidence = RELEASE_EVIDENCE.read_text(encoding="utf-8")
        manifest = RELEASE_MANIFEST.read_text(encoding="utf-8")
        power_section = section(evidence, "## 12 Power User Performance")
        match = re.search(r"- skipped buttons: `(\d+)`(?:, (.+))?", power_section)
        self.assertIsNotNone(match)
        skipped = int(match.group(1))
        if skipped == 0:
            return

        details = match.group(2) or ""
        self.assertIn("->", details)
        self.assertTrue("- Status: `candidate`" in manifest or "explicitly deferred" in manifest.casefold())

    def test_12_power_user_tuning_guide_covers_release_triage(self):
        self.assertTrue(TUNING_GUIDE.exists())
        text = TUNING_GUIDE.read_text(encoding="utf-8")

        for fragment in (
            "PERF_12_POWER_USERS_RELEASE",
            "Query History",
            "query tag",
            "PERF_TEST_APP_USAGE_REPORT_V",
            "PERF_TEST_SNOWFLAKE_QUERY_REPORT_V",
            "PERF_TEST_EXPENSIVE_QUERY_CANDIDATES_V",
            "10000 ms",
            "mutation controls",
            "initial_load",
            "goto_domcontentloaded",
            "app_ready",
            "idle_wait",
            "perf_tests/import_timing.py",
            "sections.executive_landing_shell",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)

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
                "release_blockers": [
                    {"type": "p95_threshold", "message": "p95 12000 ms exceeded threshold 10000 ms"}
                ],
                "top_slowest_sections": [
                    {"section": "App Shell", "steps": 12, "skipped": 0, "errors": 0, "p95_ms": 900, "max_ms": 1200}
                ],
                "top_slowest_actions": [
                    {"action": "initial_load", "steps": 12, "skipped": 0, "errors": 0, "p95_ms": 900, "max_ms": 1200}
                ],
                "initial_load_breakdown": [
                    {"action": "initial_load:app_ready", "steps": 12, "errors": 0, "p95_ms": 700, "max_ms": 900}
                ],
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
            "Release Blockers",
            "Top Slowest Sections",
            "Top Slowest Actions",
            "Initial Load Breakdown",
            "app_ready",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, markdown)


if __name__ == "__main__":
    unittest.main()
