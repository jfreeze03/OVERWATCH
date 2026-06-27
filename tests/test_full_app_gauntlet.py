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


class FullAppGauntletTests(unittest.TestCase):
    def test_full_app_gauntlet_is_runtime_product_gate(self):
        from tools.contracts.full_app_gauntlet import (
            REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS,
            write_full_app_gauntlet_artifacts,
        )

        artifacts = write_full_app_gauntlet_artifacts(ROOT)
        self.assertTrue(REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS.issubset(artifacts))

        summary = json.loads((ROOT / "artifacts/full_app_validation/app_validation_summary.json").read_text(encoding="utf-8"))
        manifest = json.loads((ROOT / "artifacts/full_app_validation/artifact_manifest.json").read_text(encoding="utf-8"))
        views = json.loads((ROOT / "artifacts/full_app_validation/view_results.json").read_text(encoding="utf-8"))
        controls = json.loads((ROOT / "artifacts/full_app_validation/control_inventory.json").read_text(encoding="utf-8"))
        clicks = json.loads((ROOT / "artifacts/full_app_validation/button_click_results.json").read_text(encoding="utf-8"))
        exports = json.loads((ROOT / "artifacts/full_app_validation/export_results.json").read_text(encoding="utf-8"))
        settings = json.loads((ROOT / "artifacts/full_app_validation/settings_action_results.json").read_text(encoding="utf-8"))
        live = json.loads((ROOT / "artifacts/full_app_validation/live_feature_results.json").read_text(encoding="utf-8"))
        evidence = json.loads((ROOT / "artifacts/full_app_validation/evidence_loader_call_matrix.json").read_text(encoding="utf-8"))
        stress = json.loads((ROOT / "artifacts/full_app_validation/stress_results.json").read_text(encoding="utf-8"))
        slow = json.loads((ROOT / "artifacts/full_app_validation/slow_runtime_inventory.json").read_text(encoding="utf-8"))
        errors = json.loads((ROOT / "artifacts/full_app_validation/error_inventory.json").read_text(encoding="utf-8"))
        risk = json.loads((ROOT / "artifacts/full_app_validation/risk_inventory.json").read_text(encoding="utf-8"))
        control_click = json.loads((ROOT / "artifacts/full_app_validation/control_click_coverage.json").read_text(encoding="utf-8"))
        query_budget = json.loads((ROOT / "artifacts/full_app_validation/query_budget_results.json").read_text(encoding="utf-8"))
        session_direct = json.loads((ROOT / "artifacts/full_app_validation/session_direct_sql_results.json").read_text(encoding="utf-8"))
        gauntlet = json.loads((ROOT / "artifacts/full_app_validation/gauntlet_results.json").read_text(encoding="utf-8"))
        gauntlet_failures = json.loads((ROOT / "artifacts/full_app_validation/gauntlet_failures.json").read_text(encoding="utf-8"))

        self.assertTrue(summary["all_passed"], summary)
        self.assertTrue(summary["hard_gate_passed"], summary)
        self.assertEqual(summary["hard_gate_failures"], [])
        for gate_name in (
            "cleanup_gate_passed",
            "performance_gate_passed",
            "live_feature_gate_passed",
            "export_gate_passed",
            "settings_gate_passed",
            "evidence_gate_passed",
            "query_search_gate_passed",
        ):
            self.assertTrue(summary[gate_name], gate_name)
        self.assertEqual(summary["validation_source"], "runtime_render_and_click")
        self.assertEqual(summary["proof_source"], "runtime_render")
        self.assertFalse(summary["static_inventory_only"])
        self.assertGreater(summary["total_views_rendered"], 0)
        self.assertEqual(summary["total_views_rendered"], len(views))
        self.assertEqual(summary["total_controls_found"], len(controls))
        self.assertEqual(summary["total_controls_clicked"], sum(1 for row in clicks if row.get("clicked")))
        self.assertEqual(summary["total_exports_validated"], len(exports))
        self.assertEqual(summary["total_settings_actions_clicked"], sum(1 for row in settings if row.get("clicked")))
        self.assertEqual(summary["total_live_features_clicked"], sum(1 for row in live if row.get("clicked")))
        self.assertEqual(summary["total_evidence_loaders_reached"], sum(1 for row in evidence if row.get("loader_called")))
        self.assertEqual(summary["total_stress_cases_executed"], len(stress))
        self.assertEqual(summary["failure_count"], 0)
        self.assertEqual(summary["slow_action_count"], len(slow["slow_actions"]))
        self.assertEqual(summary["forbidden_ui_token_count"], 0)
        self.assertEqual(summary["route_query_leak_count"], 0)
        self.assertEqual(summary["first_paint_query_leak_count"], 0)
        self.assertEqual(summary["account_usage_unconfirmed_leak_count"], 0)
        self.assertEqual(summary["stale_artifact_count"], 0)
        self.assertEqual(summary["cleanup_unknown_sql_object_count"], 0)
        self.assertEqual(summary["cleanup_dead_route_count"], 0)
        self.assertEqual(summary["export_payload_risk_count"], 0)
        self.assertEqual(summary["live_feature_failure_count"], 0)
        self.assertEqual(summary["evidence_over_budget_count"], 0)
        self.assertIn("deleted_or_drop_candidate_count", summary)

        full_validation_required = {
            rel for rel in REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS
            if rel.startswith("artifacts/full_app_validation/")
        }
        self.assertTrue(full_validation_required.issubset(set(manifest["files"])))
        for rel in REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS:
            self.assertTrue((ROOT / rel).exists(), rel)
        self.assertTrue(control_click["passed"], control_click)
        self.assertEqual(control_click["action_control_count"], control_click["clicked_action_control_count"] + control_click["explicitly_skipped_action_control_count"])
        self.assertEqual(control_click["missing_action_control_count"], 0, control_click)
        self.assertEqual(control_click["generic_skip_reason_count"], 0, control_click)
        self.assertTrue(query_budget["passed"], query_budget)
        self.assertTrue(session_direct["passed"], session_direct)
        self.assertTrue(gauntlet["passed"], gauntlet)
        self.assertTrue(gauntlet["hard_gate_passed"], gauntlet)
        self.assertEqual(gauntlet["failure_count"], 0, gauntlet)
        self.assertTrue(gauntlet_failures["passed"], gauntlet_failures)
        self.assertEqual(gauntlet_failures["failures"], [])
        self.assertTrue(risk["passed"], risk)
        self.assertIn("cleanup_risks", risk)
        self.assertIn("slow_action_risks", risk)
        self.assertEqual(risk["cleanup_risks"]["stale_artifact_count"], summary["stale_artifact_count"])

        elapsed = [float(row.get("elapsed_ms") or 0) for row in slow["slowest_views"]]
        self.assertEqual(elapsed, sorted(elapsed, reverse=True))
        for group_name in ("slowest_views", "slowest_clicks", "slowest_exports", "slowest_live_features"):
            for row in slow[group_name]:
                self.assertTrue(row.get("recommendation"), row)
        self.assertIn("views_with_most_controls", slow)
        self.assertIn("skipped_controls_by_reason", slow)
        self.assertTrue(errors["passed"], errors)
        self.assertIn("permission_denied_states", errors)
        self.assertIn("unavailable_snowflake_states", errors)
        self.assertIn("timeout_simulations", errors)
        self.assertFalse(errors["raw_errors_visible_daily"], errors)

    def test_gauntlet_rejects_injected_sub_artifact_failure(self):
        from tools.contracts.full_app_gauntlet import evaluate_full_app_gauntlet

        payloads = self._passing_payloads()
        payloads["artifacts/full_app_validation/live_feature_results.json"] = [
            {"source": "runtime_click", "proof_source": "runtime_click", "passed": False}
        ]
        results, failures = evaluate_full_app_gauntlet(payloads)
        self.assertFalse(results["passed"])
        self.assertTrue(any(row["gate"] == "sub_artifact_passed_flag" for row in failures["failures"]))

    def test_gauntlet_rejects_missing_artifact(self):
        from tools.contracts.full_app_gauntlet import evaluate_full_app_gauntlet

        results, failures = evaluate_full_app_gauntlet(
            self._passing_payloads(),
            missing_artifacts=["artifacts/full_app_validation/view_results.json"],
        )
        self.assertFalse(results["passed"])
        self.assertTrue(any(row["gate"] == "missing_artifacts" for row in failures["failures"]))

    def test_gauntlet_rejects_stale_artifact_and_route_leak(self):
        from tools.contracts.full_app_gauntlet import evaluate_full_app_gauntlet

        payloads = self._passing_payloads()
        summary = dict(payloads["artifacts/full_app_validation/app_validation_summary.json"])
        summary["stale_artifact_count"] = 1
        summary["route_query_leak_count"] = 1
        summary["all_passed"] = False
        payloads["artifacts/full_app_validation/app_validation_summary.json"] = summary
        results, failures = evaluate_full_app_gauntlet(payloads)
        gates = {row["gate"] for row in failures["failures"]}
        self.assertFalse(results["passed"])
        self.assertIn("stale_artifact_count", gates)
        self.assertIn("route_query_leak_count", gates)
        self.assertIn("app_validation_summary", gates)

    def test_gauntlet_rejects_risk_inventory_failure(self):
        from tools.contracts.full_app_gauntlet import evaluate_full_app_gauntlet

        payloads = self._passing_payloads()
        payloads["artifacts/full_app_validation/risk_inventory.json"] = {
            "source": "runtime_validation_risk_capture",
            "proof_source": "runtime_click",
            "passed": False,
        }
        results, failures = evaluate_full_app_gauntlet(payloads)
        self.assertFalse(results["passed"])
        self.assertTrue(any(row["gate"] == "risk_inventory" for row in failures["failures"]))

    def test_summary_cannot_pass_when_hard_gate_fails(self):
        from tools.contracts.full_app_gauntlet import evaluate_full_app_gauntlet

        payloads = self._passing_payloads()
        summary = dict(payloads["artifacts/full_app_validation/app_validation_summary.json"])
        summary["all_passed"] = True
        summary["hard_gate_passed"] = False
        payloads["artifacts/full_app_validation/app_validation_summary.json"] = summary
        results, failures = evaluate_full_app_gauntlet(payloads)
        self.assertFalse(results["passed"])
        self.assertTrue(any(row["gate"] == "app_validation_summary" for row in failures["failures"]))

    def _passing_payloads(self):
        summary = {
            "all_passed": True,
            "hard_gate_passed": True,
            "failure_count": 0,
            "forbidden_ui_token_count": 0,
            "source_forbidden_token_count": 0,
            "unhandled_exception_count": 0,
            "marker_budget_mismatch_count": 0,
            "route_query_leak_count": 0,
            "first_paint_query_leak_count": 0,
            "account_usage_unconfirmed_leak_count": 0,
            "stale_artifact_count": 0,
            "cleanup_unknown_sql_object_count": 0,
            "cleanup_dead_route_count": 0,
            "export_payload_risk_count": 0,
            "live_feature_failure_count": 0,
            "evidence_over_budget_count": 0,
            "control_contract_coverage_passed": True,
            "control_click_coverage_passed": True,
            "query_budget_passed": True,
            "session_direct_sql_passed": True,
            "cleanup_gate_passed": True,
            "performance_gate_passed": True,
            "live_feature_gate_passed": True,
            "export_gate_passed": True,
            "settings_gate_passed": True,
            "evidence_gate_passed": True,
            "query_search_gate_passed": True,
        }
        return {
            "artifacts/full_app_validation/app_validation_summary.json": summary,
            "artifacts/full_app_validation/risk_inventory.json": {"passed": True, "proof_source": "runtime_click"},
            "artifacts/full_app_validation/query_budget_results.json": {"passed": True, "proof_source": "runtime_click"},
            "artifacts/full_app_validation/session_direct_sql_results.json": {"passed": True, "proof_source": "runtime_click"},
            "artifacts/full_app_validation/control_contract_coverage.json": {"passed": True, "proof_source": "runtime_render"},
            "artifacts/full_app_validation/control_click_coverage.json": {"passed": True, "proof_source": "runtime_click"},
            "artifacts/cleanup/cleanup_summary.json": {"stale_generated_artifact_count": 0},
            "artifacts/cleanup/sql_object_inventory.json": {"unknown": []},
            "artifacts/cleanup/route_state_inventory.json": {"dead_routes": []},
            "artifacts/direct_sql_static_scan.json": {"blocked_count": 0},
            "artifacts/session_open_static_scan.json": {"blocked_count": 0},
            "artifacts/sql_performance_lint_findings.json": [],
        }


if __name__ == "__main__":
    unittest.main()
