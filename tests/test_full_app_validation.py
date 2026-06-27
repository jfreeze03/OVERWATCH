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


class FullAppValidationTests(unittest.TestCase):
    def test_full_app_validation_artifacts_cover_current_surface(self):
        from route_registry import PRIMARY_SECTION_TITLES, SECTION_WORKFLOW_CONTRACT
        from tools.contracts.full_app_validation import write_full_app_validation_artifacts

        artifacts = write_full_app_validation_artifacts(ROOT)
        required = {
            "artifacts/full_app_validation/app_validation_summary.json",
            "artifacts/full_app_validation/view_results.json",
            "artifacts/full_app_validation/button_results.json",
            "artifacts/full_app_validation/export_results.json",
            "artifacts/full_app_validation/settings_results.json",
            "artifacts/full_app_validation/live_feature_results.json",
            "artifacts/full_app_validation/performance_timings.json",
            "artifacts/full_app_validation/error_inventory.json",
            "artifacts/full_app_validation/forbidden_ui_token_scan.json",
            "artifacts/full_app_validation/button_contract_matrix.json",
            "artifacts/full_app_validation/button_click_results.json",
            "artifacts/full_app_validation/generated_exports_manifest.json",
            "artifacts/full_app_validation/settings_setup_health_results.json",
            "artifacts/full_app_validation/admin_internal_visibility_results.json",
            "artifacts/full_app_validation/live_feature_inventory.json",
            "artifacts/full_app_validation/forbidden_source_token_scan.json",
            "artifacts/full_app_validation/forbidden_daily_ui_scan.json",
            "artifacts/full_app_validation/forbidden_export_scan.json",
            "artifacts/full_app_validation/query_budget_results.json",
            "artifacts/full_app_validation/session_direct_sql_results.json",
            "artifacts/full_app_validation/query_search_results.json",
            "artifacts/full_app_validation/evidence_loader_results.json",
            "artifacts/full_app_validation/stress_results.json",
            "artifacts/full_app_validation/case_payload_results.json",
            "artifacts/full_app_validation/artifact_manifest.json",
        }
        self.assertTrue(required.issubset(artifacts))
        for rel in required:
            self.assertTrue((ROOT / rel).exists(), rel)

        summary = json.loads((ROOT / "artifacts/full_app_validation/app_validation_summary.json").read_text())
        views = json.loads((ROOT / "artifacts/full_app_validation/view_results.json").read_text())
        buttons = json.loads((ROOT / "artifacts/full_app_validation/button_results.json").read_text())
        exports = json.loads((ROOT / "artifacts/full_app_validation/export_results.json").read_text())
        query_search = json.loads((ROOT / "artifacts/full_app_validation/query_search_results.json").read_text())
        evidence = json.loads((ROOT / "artifacts/full_app_validation/evidence_loader_results.json").read_text())
        live = json.loads((ROOT / "artifacts/full_app_validation/live_feature_results.json").read_text())
        stress = json.loads((ROOT / "artifacts/full_app_validation/stress_results.json").read_text())
        manifest = json.loads((ROOT / "artifacts/full_app_validation/artifact_manifest.json").read_text())

        self.assertTrue(summary["all_passed"])
        self.assertEqual(summary["primary_sections_validated"], len(PRIMARY_SECTION_TITLES))
        self.assertEqual(summary["workflow_count"], sum(len(v) for v in SECTION_WORKFLOW_CONTRACT.values()))
        self.assertEqual(summary["failure_count"], 0)
        self.assertEqual(summary["forbidden_ui_token_count"], 0)
        self.assertEqual(summary["source_forbidden_token_count"], 0)
        self.assertGreater(summary["button_count"], 0)
        self.assertGreater(summary["export_count"], 0)
        self.assertGreater(summary["live_feature_count"], 0)
        self.assertGreater(summary["stress_case_count"], 0)
        self.assertEqual(set(manifest["files"]), required)

        rendered_pairs = {(row["section"], row["workflow"]) for row in views}
        for section, workflows in SECTION_WORKFLOW_CONTRACT.items():
            for workflow in workflows:
                self.assertIn((section, workflow), rendered_pairs)
        for row in views:
            self.assertTrue(row["passed"], row)
            self.assertEqual(row["first_paint"]["cold_packet_queries"], 1)
            self.assertEqual(row["first_paint"]["warm_packet_queries"], 0)
            self.assertEqual(row["first_paint"]["first_paint_account_usage"], 0)
            self.assertEqual(row["first_paint"]["route_action_queries"], 0)
            self.assertLess(row["elapsed_ms"], 100)

        action_types = {row["action_type"] for row in buttons}
        self.assertTrue({"route", "refresh_packet", "evidence_load", "admin_load", "advanced_load"}.issubset(action_types))
        for row in buttons:
            self.assertTrue(row["label"], row)
            self.assertTrue(row["key"], row)
            self.assertTrue(row["passed"] or row["skip_reason"], row)
            if row["action_type"] == "route":
                self.assertEqual(row["actual_snowflake_executions"], 0, row)
                self.assertEqual(row["session_open_count"], 0, row)
                self.assertEqual(row["direct_sql_event_count"], 0, row)
            if row["expected_query_budget_context"]:
                self.assertIn(row["expected_query_budget_context"], row["observed_query_budget_contexts"], row)
            self.assertEqual(row["marker_budget_mismatch_count"], 0, row)

        for row in exports:
            self.assertGreater(row["content_length"], 0, row)
            self.assertGreaterEqual(row["row_count"], 1, row)
            self.assertFalse(row["query_text_included"], row)
            self.assertTrue(row["passed"], row)

        query_cases = {row["case"]: row for row in query_search}
        self.assertEqual(query_cases["exact_query_id"]["max_rows"], 1)
        self.assertFalse(query_cases["exact_query_id"]["projects_query_text"])
        self.assertFalse(query_cases["sql_preview"]["raw_sql_visible_in_daily_ui"])
        self.assertEqual(query_cases["account_usage_fallback_unconfirmed"]["session_open_count"], 0)
        self.assertEqual(query_cases["account_usage_fallback_confirmed"]["metadata_probe_count"], 0)

        for row in evidence:
            self.assertFalse(row["account_usage_used"], row)
            self.assertTrue(row["target_marker_before_limit"], row)
            self.assertTrue(row["target_plan_id_present"], row)
            self.assertLessEqual(row["max_rows"], 200)
            self.assertLessEqual(row["hard_cap"], 500)
        for row in live:
            self.assertTrue(row["explicit_click_required"], row)
            self.assertTrue(row["admin_or_advanced_gated"], row)
            self.assertFalse(row["first_paint_invocation"], row)
            self.assertFalse(row["route_invocation"], row)
        for row in stress:
            self.assertTrue(row["passed"], row)

    def test_cleanup_artifacts_include_full_delete_first_outputs(self):
        from tools.contracts.cleanup_inventory import write_cleanup_artifacts

        artifacts = write_cleanup_artifacts(ROOT)
        required = {
            "artifacts/cleanup/deleted_sql_objects.json",
            "artifacts/cleanup/deleted_tests.json",
            "artifacts/cleanup/deleted_artifacts.json",
            "artifacts/cleanup/retained_routes.json",
            "artifacts/cleanup/sql_object_inventory.json",
            "artifacts/cleanup/sql_drop_plan.sql",
            "artifacts/cleanup/query_path_inventory.json",
        }
        self.assertTrue(required.issubset(artifacts))
        manifest = json.loads((ROOT / "artifacts/cleanup/artifact_manifest.json").read_text())
        self.assertTrue(required.issubset(set(manifest["files"])))
        retained_routes = json.loads((ROOT / "artifacts/cleanup/retained_routes.json").read_text())
        deleted_sql = json.loads((ROOT / "artifacts/cleanup/deleted_sql_objects.json").read_text())
        query_paths = json.loads((ROOT / "artifacts/cleanup/query_path_inventory.json").read_text())
        self.assertEqual(retained_routes["dead_route_count"], 0)
        self.assertEqual(deleted_sql["active_drop_collision_count"], 0)
        self.assertFalse(query_paths["account_usage_normal_evidence_allowed"])
        self.assertTrue((ROOT / "artifacts/cleanup/sql_drop_plan.sql").read_text(encoding="utf-8").startswith("-- OVERWATCH"))

    def test_runtime_package_does_not_import_full_validation_tools(self):
        forbidden = ("tools.contracts.full_app_validation", "full_app_validation")
        hits = []
        for path in APP_ROOT.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in forbidden:
                if token in text:
                    hits.append(f"{path.relative_to(ROOT)}:{token}")
        self.assertFalse(hits)


if __name__ == "__main__":
    unittest.main()
