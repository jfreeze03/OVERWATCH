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
RELEASE_PROFILE_PATH = PERF_ROOT / "profiles" / "12_power_users_release_scored.json"
DIAGNOSTIC_PROFILE_PATH = PERF_ROOT / "profiles" / "12_power_users_diagnostic.json"
SECTION_NAV_PROFILE_PATH = PERF_ROOT / "profiles" / "12_power_users_section_nav_only.json"
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
        self.assertTrue(profile["initial_load_substeps"])
        self.assertTrue(profile["section_nav_substeps"])
        self.assertTrue(profile["trace_slowest_initial_load"])
        self.assertEqual(profile["sections"], list(route_registry.PRIMARY_SECTION_TITLES))
        self.assertEqual(profile["load_buttons"]["Alert Center"], "Load Active Alerts")
        self.assertEqual(profile["load_buttons"]["Cost & Contract"], "Refresh Cost")

    def test_release_scored_profile_exists_and_disables_diagnostics(self):
        self.assertTrue(RELEASE_PROFILE_PATH.exists())
        profile = json.loads(RELEASE_PROFILE_PATH.read_text(encoding="utf-8"))

        self.assertEqual(profile["users"], 12)
        self.assertEqual(profile["iterations"], 3)
        self.assertEqual(profile["sections"], list(route_registry.PRIMARY_SECTION_TITLES))
        self.assertFalse(profile["initial_load_substeps"])
        self.assertFalse(profile["section_nav_substeps"])
        self.assertFalse(profile["trace_slowest_initial_load"])
        self.assertFalse(profile.get("tail_diagnostics", False))
        self.assertEqual(profile["load_buttons"]["Alert Center"], "Load Active Alerts")

    def test_diagnostic_profile_exists_and_enables_diagnostics(self):
        self.assertTrue(DIAGNOSTIC_PROFILE_PATH.exists())
        profile = json.loads(DIAGNOSTIC_PROFILE_PATH.read_text(encoding="utf-8"))

        self.assertTrue(profile["initial_load_substeps"])
        self.assertTrue(profile["section_nav_substeps"])
        self.assertTrue(profile["trace_slowest_initial_load"])

    def test_section_nav_only_profile_has_no_load_buttons(self):
        self.assertTrue(SECTION_NAV_PROFILE_PATH.exists())
        profile = json.loads(SECTION_NAV_PROFILE_PATH.read_text(encoding="utf-8"))

        self.assertTrue(profile["section_nav_substeps"])
        self.assertFalse(profile["initial_load_substeps"])
        self.assertFalse(profile["load_buttons"])

    def test_profile_contains_only_safe_load_buttons(self):
        runner = load_module("overwatch_live_runner_power_contract", "live_concurrent_runner.py")
        for profile_path in (PROFILE_PATH, RELEASE_PROFILE_PATH, DIAGNOSTIC_PROFILE_PATH):
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            for label in profile["load_buttons"].values():
                with self.subTest(profile=profile_path.name, label=label):
                    self.assertEqual(runner.validate_safe_load_button_label(label), label)

    def test_profile_does_not_include_mutation_controls(self):
        runner = load_module("overwatch_live_runner_mutation_contract", "live_concurrent_runner.py")
        for profile_path in (PROFILE_PATH, RELEASE_PROFILE_PATH, DIAGNOSTIC_PROFILE_PATH, SECTION_NAV_PROFILE_PATH):
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            load_buttons = profile.get("load_buttons") or {}
            for section_name, label in load_buttons.items():
                with self.subTest(profile=profile_path.name, section=section_name, label=label):
                    normalized = label.casefold()
                    for token in runner.FORBIDDEN_LOAD_BUTTON_TOKENS:
                        self.assertNotIn(token, normalized)

    def test_run_12_power_users_defaults_to_scored_profile(self):
        runner = load_module("overwatch_run_12_power_users_contract", "run_12_power_users.py")

        args = runner.parse_args([])

        self.assertEqual(Path(args.profile), RELEASE_PROFILE_PATH)

    def test_generated_perf_results_are_ignored_not_tracked(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("perf_tests/results/", gitignore)

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
            "goto_commit",
            "domcontentloaded",
            "shell_title_visible",
            "server phase trace",
            "browser navigation timing",
            "12_power_users_initial_load_only.json",
            "12_power_users_release_scored.json",
            "12_power_users_diagnostic.json",
            "12_power_users_section_nav_only.json",
            "run_initial_load_ladder.py",
            "run_diagnostic_overhead_ab.py",
            "run_browser_capacity_matrix.py",
            "run_client_isolation_matrix.py",
            "run_release_stability.py",
            "tail replay diagnostics",
            "in-run tail capture",
            "replay reproduction",
            "Client 404 troubleshooting",
            "Stale section-state troubleshooting",
            "client isolation matrix",
            "Download Button source error - 404",
            "release stability conclusion",
            "readiness penalty",
            "http_first_response_probe.py",
            "frontend paint metrics",
            "skipped-button diagnostics",
            "app-entry",
            "responseStart",
            "first-contentful-paint",
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
                "readiness_penalties": [
                    {
                        "type": "p99_tail",
                        "points": 8,
                        "observed_ms": 19000,
                        "threshold_ms": 18000,
                        "message": "p99 19000 ms exceeded tail threshold 18000 ms (fail_p95_ms * 1.8)",
                    }
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
                "server_phase_breakdown": [
                    {"phase": "app_entry:import_shell", "steps": 12, "p95_ms": 42, "max_ms": 60},
                    {"phase": "shell:probe_snowflake_available", "steps": 12, "p95_ms": 55, "max_ms": 80}
                ],
                "app_entry_phase_breakdown": [
                    {"phase": "app_entry:import_shell", "steps": 12, "p95_ms": 42, "max_ms": 60}
                ],
                "browser_navigation_timing": [
                    {"metric": "responseStart", "samples": 12, "p95_ms": 30, "max_ms": 40}
                ],
                "browser_paint_timing": [
                    {"metric": "first-contentful-paint", "samples": 12, "p95_ms": 50, "max_ms": 70}
                ],
                "frontend_dom_metrics": [
                    {"metric": "node_count", "samples": 12, "p95": 1000, "max": 1200}
                ],
                "frontend_resource_timing": [
                    {"initiator_type": "script", "samples": 12, "count_p95": 6, "duration_p95_ms": 30, "transfer_size_p95": 2000}
                ],
                "tail_summary": {
                    "p95_threshold_ms": 10000,
                    "p99_tail_threshold_ms": 18000,
                    "observed_p99_ms": 1100,
                    "p99_overage_ms": 0,
                    "slowest_section": "App Shell",
                    "slowest_action": "initial_load",
                    "slowest_initial_load_user": 1,
                    "slowest_initial_load_iteration": 1,
                    "slowest_initial_load_elapsed_ms": 900,
                },
                "initial_load_matrix": [
                    {
                        "user_id": 1,
                        "release_initial_load_ms": 900,
                        "browser_navigation_timing": {"responseStart": 30},
                        "browser_paint_timing": {"first-contentful-paint": 50},
                        "top_app_entry_phase": {"phase": "app_entry:import_shell", "elapsed_ms": 42},
                        "top_server_phase": {"phase": "shell:total_render_app", "elapsed_ms": 80},
                    }
                ],
                "skipped_button_details": [
                    {
                        "user_id": 2,
                        "iteration": 1,
                        "section": "Alert Center",
                        "action": "load_button:Load Active Alerts",
                        "detail": {
                            "active_section_title": "Alert Center",
                            "visible_button_labels": ["Load History"],
                            "screenshot_path": "perf_tests/results/skip.png",
                        },
                    }
                ],
                "tail_diagnostics": {
                    "enabled": True,
                    "post_scoring": True,
                    "tail_replay_reproduced": False,
                    "reproduction_summary": {"replayed": 1, "reproduced": 0, "not_reproduced": 1},
                    "replays": [
                        {
                            "kind": "initial_load",
                            "user_id": 1,
                            "iteration": 1,
                            "section": "App Shell",
                            "release_elapsed_ms": 1200,
                            "ok": True,
                            "elapsed_ms": 900,
                            "navigation_timing": {"responseStart": 30},
                            "paint_timing": {"first-contentful-paint": 50},
                            "tail_replay_reproduced": False,
                            "tail_replay_release_tail": True,
                            "tail_replay_reason": "release tail was not reproduced; replay FCP stayed below 2000 ms",
                            "trace_path": "perf_tests/results/tail.zip",
                            "screenshot_path": "perf_tests/results/tail.png",
                        }
                    ],
                },
                "in_run_tail_captures": [
                    {
                        "user_id": 1,
                        "iteration": 1,
                        "section": "App Shell",
                        "action": "initial_load",
                        "release_elapsed_ms": 19000,
                        "navigation_timing": {"responseStart": 1200},
                        "paint_timing": {"first-contentful-paint": 1500},
                        "visible_context": {"active_section_title": "Executive Landing"},
                        "screenshot_path": "perf_tests/results/in_run_tail.png",
                    }
                ],
                "resource_samples": [
                    {"label": "before_launch", "cpu_percent": 1.0, "memory_percent": 50.0, "process_count": 100, "browser_child_process_count": 0}
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
                    "diagnostic": False,
                },
                {
                    "user_id": 1,
                    "iteration": 1,
                    "section": "App Shell",
                    "action": "initial_load:app_ready",
                    "elapsed_ms": 700,
                    "ok": True,
                    "skipped": False,
                    "diagnostic": True,
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
            "Readiness Penalties",
            "Readiness Tail Summary",
            "Top Slowest Sections",
            "Top Slowest Actions",
            "Initial Load Breakdown",
            "Server Phase Breakdown",
            "App Entry Phase Breakdown",
            "Browser Navigation Timing",
            "Browser Paint Timing",
            "Diagnostic Overhead A/B",
            "Frontend Paint Metrics",
            "Skipped Button Context",
            "Slowest User Correlation",
            "Tail Initial Load Replay",
            "In-Run Tail Captures",
            "Replay Reproduction Check",
            "Clean Release Stability",
            "Playwright Host Resource Samples",
            "Top 10 Slowest Release Steps",
            "Top 10 Slowest Diagnostic Steps",
            "app_ready",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, markdown)


if __name__ == "__main__":
    unittest.main()
