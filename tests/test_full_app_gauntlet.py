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

        self.assertTrue(summary["all_passed"], summary)
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
        self.assertIn("deleted_or_drop_candidate_count", summary)

        self.assertTrue(REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS.issubset(set(manifest["files"])))
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


if __name__ == "__main__":
    unittest.main()
