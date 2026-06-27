import hashlib
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


class FullAppRuntimeValidationTests(unittest.TestCase):
    def _assert_runtime_proof_source(self, rel: str) -> None:
        payload = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        allowed = {"runtime_render", "runtime_click", "runtime_export", "runtime_stress"}
        if isinstance(payload, list):
            self.assertTrue(payload, rel)
            for row in payload:
                self.assertIsInstance(row, dict, rel)
                self.assertIn(row.get("proof_source"), allowed, row)
                self.assertNotEqual(row.get("proof_source"), "inventory_only", row)
            return
        self.assertIsInstance(payload, dict, rel)
        self.assertIn(payload.get("proof_source"), allowed, payload)
        self.assertNotEqual(payload.get("proof_source"), "inventory_only", payload)

    def test_full_app_validation_artifacts_cover_current_surface_from_runtime_clicks(self):
        from route_registry import PRIMARY_SECTION_TITLES, SECTION_WORKFLOW_CONTRACT
        from tools.contracts.full_app_runtime_validation import write_full_app_validation_artifacts

        artifacts = write_full_app_validation_artifacts(ROOT)
        required = {
            "artifacts/full_app_validation/app_validation_summary.json",
            "artifacts/full_app_validation/view_results.json",
            "artifacts/full_app_validation/rendered_fragments.json",
            "artifacts/full_app_validation/button_results.json",
            "artifacts/full_app_validation/control_inventory.json",
            "artifacts/full_app_validation/control_contract_coverage.json",
            "artifacts/full_app_validation/export_results.json",
            "artifacts/full_app_validation/settings_results.json",
            "artifacts/full_app_validation/settings_action_results.json",
            "artifacts/full_app_validation/live_feature_results.json",
            "artifacts/full_app_validation/performance_timings.json",
            "artifacts/full_app_validation/slow_runtime_inventory.json",
            "artifacts/full_app_validation/risk_inventory.json",
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
            "artifacts/full_app_validation/evidence_loader_call_matrix.json",
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
        evidence_matrix = json.loads((ROOT / "artifacts/full_app_validation/evidence_loader_call_matrix.json").read_text())
        live = json.loads((ROOT / "artifacts/full_app_validation/live_feature_results.json").read_text())
        settings_actions = json.loads((ROOT / "artifacts/full_app_validation/settings_action_results.json").read_text())
        stress = json.loads((ROOT / "artifacts/full_app_validation/stress_results.json").read_text())
        controls = json.loads((ROOT / "artifacts/full_app_validation/control_inventory.json").read_text())
        control_coverage = json.loads((ROOT / "artifacts/full_app_validation/control_contract_coverage.json").read_text())
        risk_inventory = json.loads((ROOT / "artifacts/full_app_validation/risk_inventory.json").read_text())
        forbidden_ui = json.loads((ROOT / "artifacts/full_app_validation/forbidden_ui_token_scan.json").read_text())
        settings_results = json.loads((ROOT / "artifacts/full_app_validation/settings_results.json").read_text())
        manifest = json.loads((ROOT / "artifacts/full_app_validation/artifact_manifest.json").read_text())

        for rel in required:
            self._assert_runtime_proof_source(rel)
        self.assertTrue(summary["all_passed"])
        self.assertEqual(summary["proof_source"], "runtime_render")
        self.assertEqual(summary["validation_source"], "runtime_render_and_click")
        self.assertFalse(summary["static_inventory_only"])
        self.assertNotIn("inventory_only", summary)
        self.assertEqual(summary["primary_sections_validated"], len(PRIMARY_SECTION_TITLES))
        self.assertEqual(summary["workflow_count"], sum(len(v) for v in SECTION_WORKFLOW_CONTRACT.values()))
        self.assertEqual(summary["failure_count"], 0)
        self.assertEqual(summary["marker_budget_mismatch_count"], 0)
        self.assertTrue(summary["control_contract_coverage_passed"])
        self.assertEqual(summary["forbidden_ui_token_count"], 0)
        self.assertEqual(summary["source_forbidden_token_count"], 0)
        self.assertGreater(summary["button_count"], 0)
        self.assertGreater(summary["export_count"], 0)
        self.assertGreater(summary["live_feature_count"], 0)
        self.assertGreater(summary["stress_case_count"], 0)
        self.assertTrue(required.issubset(set(manifest["files"])))
        generated_export_files = [
            path for path in manifest["files"]
            if path.startswith("artifacts/full_app_validation/generated_exports/")
        ]
        self.assertTrue(generated_export_files, manifest)
        self.assertGreater(len(controls), 0)
        self.assertTrue(control_coverage["passed"], control_coverage)
        self.assertEqual(control_coverage["unknown_control_count"], 0)
        self.assertEqual(control_coverage["duplicate_key_count"], 0)
        self.assertTrue(risk_inventory["passed"], risk_inventory)
        self.assertFalse(risk_inventory["marker_budget_mismatches"], risk_inventory)
        for risk_key in (
            "query_budget_failures",
            "route_leaks",
            "evidence_over_budget",
            "live_feature_budget_failures",
            "export_payload_risks",
        ):
            self.assertIn(risk_key, risk_inventory)
            self.assertFalse(risk_inventory[risk_key], risk_inventory)
        self.assertTrue(any(row.get("kind") == "button" for row in controls), controls[:5])
        self.assertTrue(any(row.get("kind") in {"select", "segmented_control", "text_input"} for row in controls), controls[:5])
        self.assertIn("daily_button_labels", forbidden_ui)
        self.assertIn("daily_exports", forbidden_ui)
        self.assertIn("case_payload_scan", forbidden_ui["daily_exports"])
        self.assertEqual(forbidden_ui["daily_button_labels"]["blocked_count"], 0, forbidden_ui)
        self.assertEqual(forbidden_ui["daily_exports"]["case_payload_scan"]["blocked_count"], 0, forbidden_ui)

        rendered_pairs = {(row["section"], row["workflow"]) for row in views}
        for section, workflows in SECTION_WORKFLOW_CONTRACT.items():
            for workflow in workflows:
                self.assertIn((section, workflow), rendered_pairs)
        for row in views:
            self.assertEqual(row["source"], "runtime_section_render")
            self.assertEqual(row["proof_source"], "runtime_render")
            self.assertTrue(row["passed"], row)
            self.assertGreater(row["rendered_fragment_count"], 0, row)
            self.assertEqual(row["first_paint"]["cold_packet_queries"], 1)
            self.assertEqual(row["first_paint"]["warm_packet_queries"], 0)
            self.assertEqual(row["first_paint"]["first_paint_account_usage"], 0)
            self.assertEqual(row["first_paint"]["route_action_queries"], 0)
            self.assertLess(row["elapsed_ms"], 100)

        action_types = {row["action_type"] for row in buttons}
        self.assertTrue({"route", "refresh_packet", "evidence_load", "admin_load", "advanced_load"}.issubset(action_types))
        for row in buttons:
            self.assertEqual(row["source"], "runtime_button_click")
            self.assertEqual(row["proof_source"], "runtime_click")
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
            if row["action_type"] == "evidence_load":
                self.assertTrue(row["evidence_loader_called"], row)
                self.assertTrue(row["evidence_loader_names"], row)
                self.assertEqual(row["observed_actual_boundaries"], row["expected_actual_boundaries"], row)
                self.assertEqual(row["actual_snowflake_executions"], row["expected_snowflake_execution_count"], row)

        for row in exports:
            self.assertEqual(row["source"], "runtime_export_payload")
            self.assertEqual(row["proof_source"], "runtime_export")
            self.assertNotIn("payload_text", row)
            self.assertGreater(row["content_length"], 0, row)
            self.assertGreaterEqual(row["row_count"], 1, row)
            self.assertEqual(row["row_count"], row["parsed_row_count"], row)
            self.assertEqual(row["row_count"], row["visible_row_count"], row)
            self.assertFalse(row["query_text_included"], row)
            self.assertEqual(row["raw_internal_token_count"], 0, row)
            self.assertTrue(row["sha256"], row)
            payload_file = ROOT / str(row["payload_file"])
            self.assertTrue(payload_file.exists(), row)
            self.assertIn(str(row["payload_file"]), manifest["files"], row)
            self.assertGreater(payload_file.stat().st_size, 0, row)
            payload_bytes = payload_file.read_bytes()
            payload_text = payload_bytes.decode("utf-8")
            self.assertEqual(hashlib.sha256(payload_bytes).hexdigest(), row["sha256"], row)
            forbidden_export_tokens = (
                "query_text",
                "SELECT",
                "WITH",
                "JOIN",
                "CALL",
                "SP_",
                "MART_",
                "FACT_",
                "ACCOUNT_USAGE",
                "Traceback",
                "SnowflakeSQLException",
            )
            for token in forbidden_export_tokens:
                self.assertNotIn(token, payload_text, row)
            self.assertTrue(row["passed"], row)

        query_cases = {row["case"]: row for row in query_search}
        self.assertTrue(query_cases)
        required_query_cases = {
            "render_no_click",
            "exact_query_id",
            "query_signature",
            "related_executions",
            "sql_preview",
            "default_export_no_query_text",
            "text_contains_no_autorun",
            "text_contains_explicit_search",
            "warehouse_prefill_no_autorun",
            "account_usage_fallback_unconfirmed",
            "account_usage_fallback_confirmed",
            "no_result_search",
            "slow_query_timeout",
            "permission_denied",
        }
        self.assertTrue(required_query_cases.issubset(query_cases), query_cases)
        for row in query_search:
            if row["case"] in {"render_no_click", "text_contains_no_autorun", "warehouse_prefill_no_autorun"}:
                self.assertEqual(row["source"], "runtime_query_search_render", row)
                self.assertEqual(row["proof_source"], "runtime_render", row)
                self.assertFalse(row["observed_contexts"], row)
                self.assertFalse(row["observed_boundaries"], row)
                self.assertEqual(row["session_open_count"], 0, row)
                self.assertEqual(row["direct_sql_event_count"], 0, row)
                self.assertEqual(row["snowflake_execution_count"], 0, row)
            elif row["case"] == "default_export_no_query_text":
                self.assertEqual(row["source"], "runtime_query_search_click", row)
                self.assertEqual(row["proof_source"], "runtime_click", row)
                self.assertGreater(row["export_count"], 0, row)
                self.assertFalse(row["query_text_included"], row)
                self.assertEqual(row["session_open_count"], 0, row)
                self.assertEqual(row["direct_sql_event_count"], 0, row)
            else:
                self.assertEqual(row["source"], "runtime_query_search_click", row)
                self.assertEqual(row["proof_source"], "runtime_click", row)
                self.assertTrue(row["observed_contexts"], row)
                self.assertTrue(row["observed_boundaries"] or row["case"] == "account_usage_fallback_unconfirmed", row)
            self.assertIn("session_open_count", row)
            self.assertIn("direct_sql_event_count", row)
            self.assertIn("metadata_probe_count", row)
            self.assertIn("snowflake_execution_count", row)
            self.assertFalse(row.get("raw_sql_visible_in_daily_ui", False), row)
        self.assertEqual(query_cases["exact_query_id"]["max_rows"], 1)
        self.assertFalse(query_cases["exact_query_id"]["projects_query_text"])
        self.assertFalse(query_cases["sql_preview"]["raw_sql_visible_in_daily_ui"])
        self.assertGreater(query_cases["default_export_no_query_text"]["export_count"], 0)
        self.assertFalse(query_cases["default_export_no_query_text"]["query_text_included"])
        self.assertEqual(query_cases["text_contains_no_autorun"]["snowflake_execution_count"], 0)
        self.assertEqual(query_cases["warehouse_prefill_no_autorun"]["snowflake_execution_count"], 0)
        self.assertLessEqual(query_cases["text_contains_explicit_search"]["max_rows"], 200)
        self.assertTrue(query_cases["exact_query_id"].get("loader_calls"), query_cases["exact_query_id"])
        self.assertTrue(query_cases["query_signature"].get("loader_calls"), query_cases["query_signature"])
        self.assertEqual(query_cases["account_usage_fallback_unconfirmed"]["session_open_count"], 0)
        self.assertEqual(query_cases["account_usage_fallback_unconfirmed"]["snowflake_execution_count"], 0)
        self.assertEqual(query_cases["account_usage_fallback_confirmed"]["metadata_probe_count"], 0)
        self.assertEqual(query_cases["no_result_search"]["max_rows"], 1, query_cases["no_result_search"])
        self.assertTrue(query_cases["no_result_search"].get("loader_calls"), query_cases["no_result_search"])
        self.assertTrue(query_cases["slow_query_timeout"]["sanitized_error_state"], query_cases["slow_query_timeout"])
        self.assertTrue(query_cases["permission_denied"]["sanitized_error_state"], query_cases["permission_denied"])
        self.assertFalse(query_cases["slow_query_timeout"]["raw_error_visible_daily"], query_cases["slow_query_timeout"])
        self.assertFalse(query_cases["permission_denied"]["raw_error_visible_daily"], query_cases["permission_denied"])

        for row in evidence:
            self.assertEqual(row["source"], "runtime_real_loader_spy", row)
            self.assertEqual(row["proof_source"], "runtime_click", row)
            self.assertTrue(row["loader_called"], row)
            self.assertTrue(row["real_loader_name"], row)
            self.assertEqual(row["loader_name"], row["real_loader_name"], row)
            self.assertIn("arg_count", row["args_shape"], row)
            self.assertTrue(row["target_context_seen"], row)
            self.assertTrue(row["compact_table_family"], row)
            self.assertGreater(row["row_count"], 0, row)
            self.assertEqual(row["returned_row_count"], row["row_count"], row)
            self.assertEqual(row["panel_row_count"], row["row_count"], row)
            self.assertEqual(row["export_row_count"], row["row_count"], row)
            self.assertEqual(row["case_row_count"], row["row_count"], row)
            self.assertTrue(row["panel_export_case_counts_match"], row)
            self.assertFalse(row["account_usage_used"], row)
            self.assertTrue(row["target_marker_before_limit"], row)
            self.assertTrue(row["target_plan_id_present"], row)
            self.assertTrue(row["query_boundary"], row)
            self.assertIn(row["loader_kind"], {"normal_evidence", "query_search", "advanced_diagnostics"}, row)
            self.assertLessEqual(row["max_rows"], 500)
            self.assertLessEqual(row["hard_cap"], 500)
        self.assertTrue(evidence_matrix, evidence_matrix)
        matrix_by_section = {}
        for row in evidence_matrix:
            self.assertEqual(row["source"], "runtime_real_loader_spy_matrix", row)
            self.assertEqual(row["proof_source"], "runtime_click", row)
            self.assertTrue(row["expected_loader_name"], row)
            self.assertNotEqual(row["expected_loader_name"], "sections.security_posture_privilege_sprawl_view.run_query", row)
            self.assertNotIn("._render_cost_contract_workflow", row["expected_loader_name"], row)
            self.assertNotEqual(row["expected_loader_name"].rsplit(".", 1)[-1], "run_query", row)
            self.assertTrue(row["observed_loader_name"], row)
            self.assertTrue(row["loader_called"], row)
            self.assertTrue(row["button_key"] or row["expected_loader_name"] == "sections.query_search.search_recent_query_summary", row)
            self.assertTrue(row["compact_table_family"], row)
            self.assertTrue(row["boundary"], row)
            self.assertTrue(row["query_boundary"], row)
            self.assertIn(row["loader_kind"], {"normal_evidence", "query_search", "advanced_diagnostics"}, row)
            if row["loader_kind"] == "normal_evidence":
                self.assertEqual(row["expected_query_budget_context"], "evidence_click", row)
                self.assertFalse(row["requires_admin"], row)
                self.assertTrue(row["normal_evidence_source_allowed"], row)
                self.assertFalse(row["account_usage_used"], row)
            self.assertGreater(row["max_rows"], 0, row)
            self.assertGreater(row["row_count"], 0, row)
            self.assertEqual(row["panel_row_count"], row["row_count"], row)
            self.assertEqual(row["export_row_count"], row["row_count"], row)
            self.assertEqual(row["case_row_count"], row["row_count"], row)
            self.assertTrue(row["observed"], row)
            self.assertTrue(row["passed"], row)
            matrix_by_section.setdefault(row["section"], set()).add(row["expected_loader_name"])
        self.assertEqual(set(matrix_by_section), set(PRIMARY_SECTION_TITLES))
        self.assertIn("sections.cost_contract_evidence.load_cost_evidence", matrix_by_section["Cost & Contract"])
        self.assertIn("sections.query_search.search_recent_query_summary", matrix_by_section["Workload Operations"])
        self.assertIn("sections.workload_operations.load_change_event_detail", matrix_by_section["Workload Operations"])
        workload_rows = [row for row in evidence_matrix if row["section"] == "Workload Operations"]
        self.assertTrue(any(row["loader_kind"] == "normal_evidence" for row in workload_rows), workload_rows)
        self.assertTrue(any(row["loader_kind"] == "query_search" for row in workload_rows), workload_rows)
        self.assertTrue(
            all(
                row["query_boundary"] != "advanced_diagnostics"
                for row in workload_rows
                if row["loader_kind"] == "normal_evidence"
            ),
            workload_rows,
        )
        self.assertIn("sections.security_posture_privilege_sprawl_view.load_privileged_grant_readiness", matrix_by_section["Security Monitoring"])
        self.assertTrue(settings_actions, settings_actions)
        self.assertTrue(settings_results["passed"], settings_results)
        self.assertTrue(settings_results["setup_refresh_validated"], settings_results)
        self.assertTrue(settings_results["all_actions_budgeted"], settings_results)
        self.assertTrue({
            "setup_health_refresh",
            "bootstrap_deployment_checks",
            "data_trust_source_status",
            "optional_optimization_status",
            "direct_session_allowlist_diagnostics",
            "query_budget_diagnostics",
            "live_query_status",
            "artifact_status",
            "admin_exports",
            "permission_denied_state",
            "unavailable_snowflake_state",
            "timeout_state",
        }.issubset(set(settings_results["validated_admin_facets"])), settings_results)
        self.assertTrue(any(row["setup_refresh_validated"] for row in settings_actions), settings_actions)
        for row in settings_actions:
            self.assertEqual(row["proof_source"], "runtime_click", row)
            self.assertTrue(row["clicked"], row)
            self.assertTrue(row["admin_or_advanced_gated"], row)
            self.assertTrue(row["sanitized_error_state"], row)
            self.assertFalse(row["raw_error_visible_daily"], row)
            self.assertTrue(row["passed"], row)
        for row in live:
            self.assertEqual(row["proof_source"], "runtime_click", row)
            self.assertTrue(row["control_key"], row)
            self.assertTrue(row["clicked"], row)
            self.assertTrue(row["explicit_click_required"], row)
            self.assertTrue(row["admin_or_advanced_gated"], row)
            self.assertFalse(row["first_paint_invocation"], row)
            self.assertFalse(row["route_invocation"], row)
            self.assertTrue(row["budget_context_observed"], row)
            self.assertIn("expected_session_open_count", row)
            self.assertIn("observed_session_open_count", row)
            self.assertIn("expected_direct_sql_count", row)
            self.assertIn("observed_direct_sql_count", row)
            self.assertIn("expected_snowflake_execution_count", row)
            self.assertIn("observed_snowflake_execution_count", row)
            self.assertTrue(row["timeout_or_row_limit"], row)
            self.assertTrue(row["permission_denied_sanitized"], row)
            self.assertTrue(row["unavailable_snowflake_sanitized"], row)
            self.assertTrue(row["passed"], row)
        for row in stress:
            self.assertEqual(row["proof_source"], "runtime_stress", row)
            self.assertTrue(row["sequence_steps"], row)
            self.assertIn("sections_touched", row)
            self.assertIn("actions_clicked", row)
            self.assertIn("query_counts_by_boundary", row)
            self.assertIn("state_delta_summary", row)
            self.assertIn("export_summary", row)
            self.assertTrue(row["threshold"], row)
            self.assertTrue(row["threshold_passed"], row)
            self.assertEqual(row["threshold_failures"], [], row)
            self.assertTrue(row["passed"], row)
        stress_cases = {row["case"]: row for row in stress}
        required_stress_cases = {
            "rapid_section_switching",
            "repeated_route_clicks",
            "repeated_evidence_loads",
            "repeated_refresh_packet",
            "repeated_query_search_interactions",
            "account_usage_confirmation_matrix",
            "advanced_scope_filters",
            "empty_evidence_result",
            "large_bounded_evidence_result",
            "snowflake_unavailable",
            "permission_denied",
            "slow_query_timeout",
            "stale_source_data",
            "fixture_data_mode",
            "live_feature_denied",
            "many_row_export",
            "no_row_export",
            "cache_expiry_force_refresh",
            "state_bleed_across_sections",
            "duplicate_session_state_collision",
        }
        self.assertTrue(required_stress_cases.issubset(stress_cases), stress_cases)
        self.assertEqual(stress_cases["rapid_section_switching"]["touched_primary_section_count"], len(PRIMARY_SECTION_TITLES))
        self.assertGreater(len(stress_cases["repeated_route_clicks"]["sequence_steps"]), 0, stress_cases["repeated_route_clicks"])
        self.assertGreater(stress_cases["repeated_evidence_loads"]["evidence_loader_call_count"], 0)
        self.assertIn("decision_packet", stress_cases["repeated_refresh_packet"]["query_counts_by_boundary"])
        self.assertTrue(stress_cases["permission_denied"]["sanitized_error_state"], stress_cases["permission_denied"])
        self.assertTrue(stress_cases["slow_query_timeout"]["sanitized_error_state"], stress_cases["slow_query_timeout"])

        query_search_proof = json.loads((ROOT / "artifacts/query_search_proof.json").read_text(encoding="utf-8"))
        self.assertEqual(query_search_proof["proof_source"], "runtime_click")
        self.assertEqual(query_search_proof["cases"], query_search)

    def test_static_full_app_inventory_cannot_claim_runtime_validation(self):
        from tools.contracts.full_app_validation_inventory import write_full_app_contract_inventory_artifacts

        artifacts = write_full_app_contract_inventory_artifacts(ROOT)
        self.assertIn("artifacts/full_app_inventory/app_validation_summary.json", artifacts)
        summary = json.loads((ROOT / "artifacts/full_app_inventory/app_validation_summary.json").read_text())
        manifest = json.loads((ROOT / "artifacts/full_app_inventory/artifact_manifest.json").read_text())

        self.assertTrue(summary["inventory_only"])
        self.assertFalse(summary["runtime_validated"])
        self.assertNotIn("all_passed", summary)
        self.assertNotIn("validation_source", summary)
        self.assertTrue(all(path.startswith("artifacts/full_app_inventory/") for path in manifest["files"]))

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
        forbidden = (
            "tools.contracts.full_app_gauntlet",
            "tools.contracts.full_app_runtime_validation",
            "tools.contracts.full_app_validation_inventory",
            "full_app_gauntlet",
            "full_app_runtime_validation",
            "full_app_validation_inventory",
        )
        hits = []
        for path in APP_ROOT.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in forbidden:
                if token in text:
                    hits.append(f"{path.relative_to(ROOT)}:{token}")
        self.assertFalse(hits)


if __name__ == "__main__":
    unittest.main()
