import copy
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class LaunchReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tools.contracts.launch_readiness import write_launch_readiness_artifacts

        cls.artifacts = write_launch_readiness_artifacts(ROOT)
        cls.payloads = cls._load_payloads()
        cls.launch_payloads = cls._load_launch_payloads()

    def test_launch_readiness_is_top_level_release_gate(self):
        from tools.contracts.launch_readiness import REQUIRED_LAUNCH_READINESS_ARTIFACTS

        summary = self._read_json("artifacts/launch_readiness/launch_readiness_summary.json")
        failures = self._read_json("artifacts/launch_readiness/launch_readiness_failures.json")
        matrix = self._read_json("artifacts/launch_readiness/release_gate_matrix.json")
        manifest = self._read_json("artifacts/launch_readiness/artifact_manifest.json")

        self.assertTrue(summary["all_passed"], summary)
        self.assertTrue(summary["hard_gate_passed"], summary)
        self.assertEqual(summary["failure_count"], 0, summary)
        self.assertEqual(summary["blocking_failures"], [])
        self.assertTrue(failures["passed"], failures)
        self.assertEqual(failures["failures"], [])
        self.assertGreater(summary["check_count"], 12)
        self.assertEqual(summary["check_count"], len(matrix))
        self.assertEqual(summary["fail_count"], 0)
        self.assertEqual(summary["pass_count"], len(matrix))
        self.assertTrue(summary["gauntlet_passed"])
        self.assertTrue(summary["runtime_validation_passed"])
        self.assertGreaterEqual(summary["required_artifact_count"], len(REQUIRED_LAUNCH_READINESS_ARTIFACTS))
        self.assertIn("decision-workspace-proof", summary["uploaded_artifact_names"])
        self.assertFalse(summary["raw_sql_included"])

        matrix_by_gate = {row["gate"]: row for row in matrix}
        for gate in (
            "full_app_gauntlet",
            "runtime_validation",
            "required_artifacts",
            "browser_or_rendered_snapshot",
            "config_sanity",
            "secrets_scan",
            "role_readiness",
            "deployment_readiness",
            "upgrade_readiness",
            "drop_rollback",
            "sql_value_inventory",
            "sql_cost_risk",
            "live_query_history",
            "performance_slo",
            "settings_live_closure",
            "export_case_closure",
            "cleanup_closure",
            "docs_readiness",
            "ci_upload_paths",
        ):
            self.assertIn(gate, matrix_by_gate)
            self.assertTrue(matrix_by_gate[gate]["passed"], matrix_by_gate[gate])

        self.assertTrue(REQUIRED_LAUNCH_READINESS_ARTIFACTS.issubset(set(manifest["files"])))
        for rel in REQUIRED_LAUNCH_READINESS_ARTIFACTS:
            self.assertTrue((ROOT / rel).exists(), rel)

    def test_launch_readiness_records_browser_skip_or_screenshots(self):
        browser = self._read_json("artifacts/launch_readiness/browser_smoke_results.json")
        self.assertTrue(browser["passed"], browser)
        self.assertTrue(browser["deterministic_snapshots_present"], browser)
        if browser["browser_proof_skipped"]:
            self.assertTrue(browser["skip_reason"], browser)
            self.assertTrue((ROOT / "artifacts/browser_screenshots/SKIPPED.txt").exists())
        else:
            self.assertGreater(browser["browser_screenshot_count"], 0)

    def test_launch_readiness_config_secrets_permissions_and_docs_pass(self):
        for rel in (
            "artifacts/launch_readiness/config_sanity_results.json",
            "artifacts/launch_readiness/secrets_scan_results.json",
            "artifacts/launch_readiness/snowflake_permission_matrix.json",
            "artifacts/launch_readiness/role_readiness_results.json",
            "artifacts/launch_readiness/docs_readiness_results.json",
        ):
            payload = self._read_json(rel)
            self.assertTrue(payload["passed"], payload)
            self.assertFalse(payload["raw_sql_included"])

        permissions = self._read_json("artifacts/launch_readiness/snowflake_permission_matrix.json")
        daily_roles = [row for row in permissions["roles"] if row["role"] == "daily_user"]
        self.assertEqual(len(daily_roles), 1)
        self.assertFalse(daily_roles[0]["account_usage_required"])

    def test_launch_readiness_deployment_sql_and_performance_pass(self):
        for rel in (
            "artifacts/launch_readiness/deployment_readiness_results.json",
            "artifacts/launch_readiness/upgrade_readiness_results.json",
            "artifacts/launch_readiness/drop_rollback_results.json",
            "artifacts/launch_readiness/sql_value_inventory.json",
            "artifacts/launch_readiness/sql_cost_risk_findings.json",
            "artifacts/launch_readiness/performance_slo_results.json",
            "artifacts/launch_readiness/settings_live_closure_results.json",
            "artifacts/launch_readiness/export_case_closure_results.json",
            "artifacts/launch_readiness/cleanup_launch_closure_results.json",
        ):
            payload = self._read_json(rel)
            self.assertTrue(payload["passed"], payload)

        sql_value = self._read_json("artifacts/launch_readiness/sql_value_inventory.json")
        self.assertGreater(sql_value["sql_path_count"], 0)
        self.assertEqual(sql_value["unowned_or_no_value_count"], 0)
        self.assertTrue(all(row["owner"] for row in sql_value["paths"]))

        live_history = self._read_json("artifacts/launch_readiness/live_query_history_results.json")
        self.assertTrue(live_history["passed"], live_history)
        if live_history["skipped"]:
            self.assertTrue(live_history["skip_reason"], live_history)

    def test_launch_readiness_rejects_failed_gauntlet(self):
        self._assert_launch_failure(
            lambda payloads, launch: payloads["artifacts/full_app_validation/gauntlet_results.json"].update(
                {"passed": False}
            ),
            "full_app_gauntlet",
        )

    def test_launch_readiness_rejects_missing_gauntlet_artifacts(self):
        from tools.contracts.launch_readiness import evaluate_launch_readiness

        summary, failures, _matrix = evaluate_launch_readiness(
            self._payload_copy(),
            self._launch_payload_copy(),
            missing_artifacts=["artifacts/full_app_validation/gauntlet_results.json"],
        )
        self.assertFalse(summary["all_passed"], failures)
        self.assertTrue(
            any(row["gate"] == "missing_launch_prerequisite_artifacts" for row in failures["failures"]),
            failures,
        )

    def test_launch_readiness_rejects_runtime_and_artifact_risks(self):
        cases = [
            (
                "route leak",
                lambda payloads, launch: payloads["artifacts/full_app_validation/app_validation_summary.json"].update(
                    {"route_query_leak_count": 1, "all_passed": False}
                ),
                "runtime_validation",
            ),
            (
                "forbidden token",
                lambda payloads, launch: payloads["artifacts/full_app_validation/app_validation_summary.json"].update(
                    {"forbidden_ui_token_count": 1, "all_passed": False}
                ),
                "runtime_validation",
            ),
            (
                "stale artifact",
                lambda payloads, launch: launch["artifact_review_results"].update({"passed": False, "stale_artifact_count": 1}),
                "required_artifacts",
            ),
            (
                "direct sql block",
                lambda payloads, launch: payloads["artifacts/direct_sql_static_scan.json"].update({"blocked_count": 1}),
                "direct_sql_static_scan",
            ),
            (
                "session open block",
                lambda payloads, launch: payloads["artifacts/session_open_static_scan.json"].update({"blocked_count": 1}),
                "session_open_static_scan",
            ),
            (
                "sql lint error",
                lambda payloads, launch: payloads["artifacts/sql_performance_lint_findings.json"].append(
                    {"severity": "error", "code": "ALWAYS_TRUE_TIME_PREDICATE"}
                ),
                "sql_performance_lint",
            ),
        ]
        for name, mutator, gate in cases:
            with self.subTest(name=name):
                self._assert_launch_failure(mutator, gate)

    def test_launch_readiness_rejects_release_layer_failures(self):
        cases = [
            (
                "config",
                lambda payloads, launch: launch["config_sanity_results"].update({"passed": False}),
                "config_sanity",
            ),
            (
                "secrets",
                lambda payloads, launch: launch["secrets_scan_results"].update({"passed": False, "blocked_count": 1}),
                "secrets_scan",
            ),
            (
                "browser",
                lambda payloads, launch: launch["browser_smoke_results"].update({"passed": False}),
                "browser_or_rendered_snapshot",
            ),
            (
                "docs",
                lambda payloads, launch: launch["docs_readiness_results"].update({"passed": False}),
                "docs_readiness",
            ),
            (
                "deploy",
                lambda payloads, launch: launch["deployment_readiness_results"].update({"passed": False}),
                "deployment_readiness",
            ),
            (
                "sql value",
                lambda payloads, launch: launch["sql_value_inventory"].update({"passed": False}),
                "sql_value_inventory",
            ),
            (
                "exports",
                lambda payloads, launch: launch["export_case_closure_results"].update({"passed": False}),
                "export_case_closure",
            ),
        ]
        for name, mutator, gate in cases:
            with self.subTest(name=name):
                self._assert_launch_failure(mutator, gate)

    def test_launch_readiness_workflow_uploads_launch_artifacts(self):
        ci_review = self._read_json("artifacts/launch_readiness/ci_artifact_review_results.json")
        self.assertTrue(ci_review["passed"], ci_review)
        self.assertEqual(ci_review["missing_upload_paths"], [])
        self.assertEqual(ci_review["missing_steps"], [])

    def _assert_launch_failure(self, mutator, expected_gate: str) -> None:
        from tools.contracts.launch_readiness import evaluate_launch_readiness

        payloads = self._payload_copy()
        launch = self._launch_payload_copy()
        mutator(payloads, launch)
        summary, failures, matrix = evaluate_launch_readiness(payloads, launch)
        matched = [row for row in failures["failures"] if row["gate"] == expected_gate]
        self.assertFalse(summary["all_passed"], failures)
        self.assertTrue(matched, failures)
        self.assertTrue(matched[0]["recommendation"], matched[0])
        matrix_match = [row for row in matrix if row["gate"] == expected_gate]
        self.assertTrue(matrix_match, matrix)
        self.assertFalse(matrix_match[0]["passed"], matrix_match[0])

    def _payload_copy(self):
        return copy.deepcopy(self.payloads)

    def _launch_payload_copy(self):
        return copy.deepcopy(self.launch_payloads)

    @staticmethod
    def _read_json(rel: str):
        return json.loads((ROOT / rel).read_text(encoding="utf-8"))

    @classmethod
    def _load_payloads(cls):
        from tools.contracts.full_app_gauntlet import REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS

        return {
            rel: json.loads((ROOT / rel).read_text(encoding="utf-8"))
            for rel in REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS
            if (ROOT / rel).exists()
        }

    @classmethod
    def _load_launch_payloads(cls):
        launch_dir = ROOT / "artifacts" / "launch_readiness"
        payloads = {}
        for path in launch_dir.glob("*.json"):
            payloads[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        if "ci_artifact_review_results" in payloads and "artifact_review_results" not in payloads:
            payloads["artifact_review_results"] = payloads["ci_artifact_review_results"]
        return payloads


if __name__ == "__main__":
    unittest.main()
