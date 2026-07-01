import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


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
        self.assertTrue(summary["snowflake_validation_passed"])
        self.assertFalse(summary["snowflake_live_validation_enabled"])
        self.assertTrue(summary["snowflake_live_validation_skipped"])
        self.assertIn("OVERWATCH_SNOWFLAKE_VALIDATION", summary["snowflake_validation_skip_reason"])
        self.assertEqual(summary["live_validation_status"], "static_skipped")
        self.assertEqual(summary["live_validation_waiver_id"], "")
        self.assertEqual(summary["live_validation_waiver_owner"], "")
        self.assertEqual(summary["live_validation_waiver_expiration"], "")
        self.assertFalse(summary["live_validation_required"])
        self.assertTrue(summary["live_validation_skip_allowed"])
        self.assertEqual(summary["live_validation_missing_reason"], "")
        self.assertTrue(summary["live_execution_manifest_passed"])
        self.assertGreater(summary["live_execution_manifest_entry_count"], 0)
        self.assertEqual(summary["live_execution_manifest_failure_count"], 0)
        self.assertTrue(summary["live_execution_manifest_gate_passed"])
        self.assertTrue(summary["live_execution_manifest_reconciliation_passed"])
        self.assertEqual(summary["live_execution_manifest_reconciliation_failure_count"], 0)
        self.assertTrue(summary["live_execution_manifest_category_coverage_passed"])
        self.assertEqual(summary["live_execution_manifest_category_failure_count"], 0)
        self.assertEqual(summary["live_execution_manifest_orphan_count"], 0)
        self.assertEqual(summary["live_execution_manifest_unknown_id_count"], 0)
        self.assertEqual(summary["live_execution_manifest_missing_id_count"], 0)
        self.assertEqual(summary["live_execution_manifest_status_mismatch_count"], 0)
        self.assertEqual(summary["live_execution_manifest_mode_mismatch_count"], 0)
        self.assertEqual(summary["live_execution_manifest_row_index_mismatch_count"], 0)
        self.assertEqual(summary["live_execution_manifest_row_key_mismatch_count"], 0)
        self.assertGreater(summary["procedure_compile_count"], 0)
        self.assertEqual(summary["procedure_compile_failure_count"], 0)
        self.assertGreater(summary["procedure_smoke_call_count"], 0)
        self.assertEqual(summary["procedure_smoke_failure_count"], 0)
        self.assertEqual(summary["refresh_fast_status"], "skipped")
        self.assertEqual(summary["refresh_full_status"], "skipped")
        self.assertEqual(summary["packet_validation_status"], "passed")
        self.assertEqual(summary["packet_validation_failed_check_count"], 0)
        self.assertEqual(summary["packet_duplicate_array_count"], 0)
        self.assertEqual(summary["packet_missing_field_count"], 0)
        self.assertEqual(summary["packet_duplicate_arrays"], [])
        self.assertEqual(summary["packet_missing_fields"], [])
        self.assertEqual(summary["compact_evidence_validation_status"], "passed")
        self.assertEqual(summary["compact_mart_count"], 5)
        self.assertEqual(summary["compact_mart_failure_count"], 0)
        self.assertEqual(summary["compact_normal_account_usage_count"], 0)
        self.assertEqual(summary["compact_missing_target_columns"], [])
        self.assertTrue(summary["encoding_hygiene_passed"])
        self.assertEqual(summary["encoding_blocked_count"], 0)
        self.assertTrue(summary["ci_artifact_reality_passed"])
        self.assertEqual(summary["ci_artifact_reality_failure_count"], 0)
        self.assertTrue(summary["release_candidate_bundle_passed"])
        self.assertEqual(summary["release_candidate_bundle_failure_count"], 0)
        self.assertGreater(summary["release_candidate_artifact_count"], 0)
        self.assertGreater(summary["release_candidate_artifact_hash_count"], 0)
        self.assertTrue(summary["summary_board_first_paint_passed"])
        self.assertEqual(summary["summary_board_first_paint_failure_count"], 0)
        self.assertEqual(summary["summary_board_section_count"], 6)
        self.assertTrue(summary["billing_reconciliation_passed"])
        self.assertEqual(summary["billing_reconciliation_failure_count"], 0)
        self.assertTrue(summary["billing_reconciliation_live_passed"])
        self.assertTrue(summary["billing_reconciliation_live_skipped"])
        self.assertFalse(summary["billing_reconciliation_live_required"])
        self.assertTrue(summary["cortex_cost_consistency_passed"])
        self.assertEqual(summary["cortex_cost_consistency_failure_count"], 0)
        self.assertTrue(summary["cost_chart_workbench_passed"])
        self.assertEqual(summary["cost_chart_workbench_failure_count"], 0)
        self.assertTrue(summary["cost_db_formula_authority_passed"])
        self.assertEqual(summary["cost_db_formula_authority_failure_count"], 0)
        self.assertGreaterEqual(summary["cost_db_formula_count"], 7)
        self.assertGreaterEqual(summary["overwatch_formula_count"], 4)
        self.assertTrue(summary["formula_end_to_end_passed"])
        self.assertEqual(summary["formula_end_to_end_failure_count"], 0)
        self.assertTrue(summary["formula_value_reconciliation_passed"])
        self.assertEqual(summary["formula_value_reconciliation_failure_count"], 0)
        self.assertEqual(summary["formula_validation_mode"], "fixture_static")
        self.assertTrue(summary["packet_formula_sql_passed"])
        self.assertTrue(summary["flat_packet_formula_passed"])
        self.assertTrue(summary["packet_schema_upgrade_passed"])
        self.assertEqual(summary["packet_schema_failure_count"], 0)
        self.assertTrue(summary["snowflake_formula_static_passed"])
        self.assertTrue(summary["snowflake_formula_value_passed"])
        self.assertEqual(summary["snowflake_formula_value_failure_count"], 0)
        self.assertFalse(summary["snowflake_formula_live_required"])
        self.assertFalse(summary["snowflake_formula_live_executed"])
        self.assertFalse(summary["snowflake_formula_live_passed"])
        self.assertTrue(summary["snowflake_formula_live_skipped"])
        self.assertIn("OVERWATCH_SNOWFLAKE_VALIDATION", summary["snowflake_formula_live_skip_reason"])
        self.assertTrue(summary["snowflake_formula_gate_passed"])
        self.assertEqual(summary["snowflake_formula_gate_failure_count"], 0)
        self.assertTrue(summary["rendered_formula_passed"])
        self.assertTrue(summary["cortex_service_type_gate_passed"])
        self.assertEqual(summary["cortex_service_type_failure_count"], 0)
        self.assertEqual(summary["cortex_unknown_service_type_count"], 0)
        self.assertTrue(summary["formula_live_validation_passed"])
        self.assertTrue(summary["formula_live_validation_skipped"])
        self.assertFalse(summary["formula_live_validation_required"])
        self.assertTrue(summary["snowflake_cli_gate_passed"])
        self.assertFalse(summary["snowflake_cli_live_passed"])
        self.assertFalse(summary["snowflake_cli_live_executed"])
        self.assertTrue(summary["snowflake_cli_live_skipped"])
        self.assertFalse(summary["snowflake_cli_live_required"])
        self.assertFalse(summary["snowflake_cli_live_waived"])
        self.assertTrue(summary["snowflake_cli_live_validation_passed"])
        self.assertTrue(summary["snowflake_cli_live_validation_skipped"])
        self.assertFalse(summary["snowflake_cli_live_validation_required"])
        self.assertFalse(summary["snowflake_cli_live_validation_waived"])
        self.assertEqual(summary["snowflake_cli_live_validation_failure_count"], 0)
        self.assertFalse(summary["snowflake_cli_connection_passed"])
        self.assertFalse(summary["snowflake_cli_setup_validation_passed"])
        self.assertFalse(summary["snowflake_cli_packet_value_passed"])
        self.assertFalse(summary["snowflake_cli_formula_value_passed"])
        self.assertFalse(summary["snowflake_cli_summary_card_value_passed"])
        self.assertFalse(summary["snowflake_cli_query_budget_passed"])
        self.assertTrue(summary["snowflake_cli_manifest_reconciliation_passed"])
        self.assertTrue(summary["metric_semantic_registry_passed"])
        self.assertEqual(summary["metric_semantic_registry_failure_count"], 0)
        self.assertGreater(summary["metric_semantic_registry_row_count"], 0)
        self.assertTrue(summary["workload_formula_semantics_passed"])
        self.assertEqual(summary["workload_formula_semantics_failure_count"], 0)
        self.assertTrue(summary["query_budget_gate_passed"])
        self.assertEqual(summary["query_budget_gate_failure_count"], 0)
        self.assertTrue(summary["render_provenance_reconciliation_passed"])
        self.assertEqual(summary["render_provenance_reconciliation_failure_count"], 0)
        self.assertGreater(summary["render_provenance_reconciliation_surface_count"], 0)
        self.assertGreaterEqual(summary["required_artifact_count"], len(REQUIRED_LAUNCH_READINESS_ARTIFACTS))
        self.assertIn("decision-workspace-proof", summary["uploaded_artifact_names"])
        self.assertFalse(summary["raw_sql_included"])

        matrix_by_gate = {row["gate"]: row for row in matrix}
        for gate in (
            "launch_profile",
            "profile_gate_failures",
            "raw_invariants",
            "full_app_gauntlet",
            "summary_board_first_paint",
            "billing_reconciliation",
            "billing_reconciliation_live",
            "cost_db_formula_authority",
            "formula_end_to_end",
            "formula_value_reconciliation",
            "packet_schema_upgrade",
            "snowflake_formula_static_live",
            "snowflake_formula_value",
            "live_static_formula_status",
            "cortex_service_type_mapping",
            "cortex_cost_consistency",
            "cost_chart_workbench",
            "formula_live_validation",
            "render_provenance_reconciliation",
            "snowflake_cli_live_validation",
            "metric_semantic_registry",
            "workload_formula_semantics",
            "query_budget_recording",
            "runtime_validation",
            "required_artifacts",
            "artifact_upload_review",
            "ci_artifact_reality",
            "ci_run_review",
            "browser_or_rendered_snapshot",
            "browser_required_coverage",
            "browser_or_snapshot_failures",
            "config_sanity",
            "secrets_scan",
            "role_readiness",
            "deployment_readiness",
            "upgrade_readiness",
            "drop_rollback",
            "sql_value_inventory",
            "sql_cost_risk",
            "encoding_hygiene",
            "live_query_history",
            "snowflake_raw_validation_recheck",
            "live_execution_manifest_gate",
            "snowflake_execution_validation",
            "procedure_compile_validation",
            "procedure_smoke_call_validation",
            "recent_snowflake_fix_validation",
            "streamlit_manifest_validation",
            "snowflake_phase_validation",
            "compact_evidence_mart_validation",
            "packet_publication_validation",
            "refresh_performance_validation",
            "performance_slo",
            "settings_live_closure",
            "export_case_closure",
            "cleanup_closure",
            "delete_first_release",
            "docs_readiness",
            "ci_upload_paths",
            "release_candidate_bundle",
        ):
            self.assertIn(gate, matrix_by_gate)
            self.assertTrue(matrix_by_gate[gate]["passed"], matrix_by_gate[gate])

        snowflake_gate = self._read_json("artifacts/launch_readiness/snowflake_validation_gate_results.json")
        manifest_gate = self._read_json("artifacts/launch_readiness/live_execution_manifest_gate_results.json")
        self.assertIn("OVERWATCH_SNOWFLAKE_VALIDATION", snowflake_gate["snowflake_validation_skip_reason"])
        self.assertEqual(snowflake_gate["live_validation_status"], "static_skipped")
        self.assertEqual(snowflake_gate["packet_validation_status"], "passed")
        self.assertEqual(snowflake_gate["compact_evidence_validation_status"], "passed")
        self.assertEqual(snowflake_gate["packet_validation_failed_check_count"], 0)
        self.assertTrue(snowflake_gate["live_execution_manifest_passed"])
        self.assertGreater(snowflake_gate["live_execution_manifest_entry_count"], 0)
        self.assertTrue(snowflake_gate["live_execution_manifest_reconciliation_passed"])
        self.assertEqual(snowflake_gate["live_execution_manifest_reconciliation_failure_count"], 0)
        self.assertTrue(snowflake_gate["live_execution_manifest_category_coverage_passed"])
        self.assertEqual(snowflake_gate["live_execution_manifest_category_failure_count"], 0)
        self.assertTrue(manifest_gate["passed"], manifest_gate)
        self.assertEqual(manifest_gate["failure_count"], 0, manifest_gate)
        self.assertTrue(manifest_gate["live_execution_manifest_category_coverage_passed"], manifest_gate)
        self.assertEqual(snowflake_gate["compact_mart_count"], 5)
        raw_recheck = self._read_json("artifacts/launch_readiness/snowflake_raw_validation_recheck.json")
        snowflake_failures = self._read_json("artifacts/launch_readiness/snowflake_validation_failures.json")
        self.assertTrue(raw_recheck["passed"], raw_recheck)
        self.assertEqual(raw_recheck["failure_count"], 0, raw_recheck)
        self.assertEqual(raw_recheck["packet_validation_status"], "passed")
        self.assertEqual(raw_recheck["packet_validation_failed_check_count"], 0)
        self.assertTrue(raw_recheck["live_execution_manifest_passed"])
        self.assertGreater(raw_recheck["live_execution_manifest_entry_count"], 0)
        self.assertTrue(raw_recheck["live_execution_manifest_reconciliation_passed"])
        self.assertEqual(raw_recheck["live_execution_manifest_reconciliation_failure_count"], 0)
        self.assertTrue(raw_recheck["live_execution_manifest_category_coverage_passed"])
        self.assertEqual(raw_recheck["live_execution_manifest_category_failure_count"], 0)
        self.assertEqual(raw_recheck["compact_evidence_validation_status"], "passed")
        self.assertEqual(raw_recheck["compact_mart_count"], 5)
        self.assertEqual(raw_recheck["live_validation_status"], "static_skipped")
        self.assertTrue(snowflake_failures["passed"], snowflake_failures)
        self.assertEqual(snowflake_failures["failure_count"], 0, snowflake_failures)

        formula_gate = self._read_json("artifacts/launch_readiness/cost_db_formula_authority_gate_results.json")
        cortex_gate = self._read_json("artifacts/launch_readiness/cortex_cost_consistency_gate_results.json")
        chart_gate = self._read_json("artifacts/launch_readiness/cost_chart_workbench_gate_results.json")
        formula_live_gate = self._read_json("artifacts/launch_readiness/formula_live_gate_results.json")
        snowflake_cli_gate = self._read_json("artifacts/launch_readiness/snowflake_cli_live_gate_results.json")
        metric_gate = self._read_json("artifacts/launch_readiness/metric_semantic_gate_results.json")
        workload_gate = self._read_json("artifacts/launch_readiness/workload_formula_gate_results.json")
        self.assertTrue(formula_gate["passed"], formula_gate)
        self.assertEqual(formula_gate["failure_count"], 0, formula_gate)
        self.assertTrue(cortex_gate["passed"], cortex_gate)
        self.assertTrue(chart_gate["passed"], chart_gate)
        self.assertTrue(formula_live_gate["passed"], formula_live_gate)
        self.assertTrue(snowflake_cli_gate["passed"], snowflake_cli_gate)
        self.assertTrue(snowflake_cli_gate["snowflake_cli_gate_passed"], snowflake_cli_gate)
        self.assertTrue(snowflake_cli_gate["snowflake_cli_live_skipped"], snowflake_cli_gate)
        self.assertFalse(snowflake_cli_gate["snowflake_cli_live_passed"], snowflake_cli_gate)
        self.assertFalse(snowflake_cli_gate["snowflake_cli_live_executed"], snowflake_cli_gate)
        self.assertTrue(metric_gate["passed"], metric_gate)
        self.assertEqual(metric_gate["failure_count"], 0, metric_gate)
        self.assertTrue(workload_gate["passed"], workload_gate)

        self.assertTrue(REQUIRED_LAUNCH_READINESS_ARTIFACTS.issubset(set(manifest["files"])))
        for rel in REQUIRED_LAUNCH_READINESS_ARTIFACTS:
            self.assertTrue((ROOT / rel).exists(), rel)

    def test_release_candidate_bundle_has_hashes_and_product_gauntlet(self):
        summary = self._read_json("artifacts/release_candidate/release_candidate_summary.json")
        manifest = self._read_json("artifacts/release_candidate/artifact_manifest.json")
        hashes = self._read_json("artifacts/release_candidate/artifact_hashes.json")
        reconciliation = self._read_json("artifacts/release_candidate/artifact_reconciliation_results.json")
        product = self._read_json("artifacts/release_candidate/product_gauntlet_release_results.json")
        gate_matrix = self._read_json("artifacts/release_candidate/release_gate_matrix.json")
        notes = self._read_json("artifacts/release_candidate/release_notes.json")

        self.assertTrue(summary["all_passed"], summary)
        self.assertEqual(summary["hard_gate_failure_count"], 0, summary)
        for field in (
            "commit_sha",
            "source_tree_sha",
            "branch_ref",
            "workflow_run_id",
            "workflow_url",
            "run_attempt",
            "workflow_name",
            "job_name",
            "artifact_upload_name",
            "uploaded_artifact_names",
            "generated_at",
            "launch_profile",
            "ci_metadata_source",
        ):
            self.assertIn(field, summary)
        self.assertTrue(reconciliation["passed"], reconciliation)
        self.assertEqual(reconciliation["missing_required_categories"], [])
        self.assertEqual(reconciliation["raw_sql_or_secret_count"], 0)
        self.assertEqual(reconciliation["commit_mismatch_count"], 0)
        self.assertEqual(summary["raw_sql_leak_count"], 0)
        self.assertEqual(summary["forbidden_daily_token_count"], 0)
        self.assertEqual(summary["stale_artifact_count"], 0)
        self.assertEqual(summary["unknown_sql_object_count"], 0)
        self.assertEqual(summary["dead_route_count"], 0)
        self.assertTrue(summary["artifact_reconciliation_passed"])
        self.assertTrue(summary["product_gauntlet_passed"])
        self.assertTrue(summary["cortex_cost_consistency_passed"])
        self.assertTrue(summary["cost_chart_workbench_passed"])
        self.assertTrue(summary["cost_db_formula_authority_passed"])
        self.assertTrue(summary["formula_live_validation_passed"])
        self.assertTrue(summary["snowflake_cli_gate_passed"])
        self.assertFalse(summary["snowflake_cli_live_passed"])
        self.assertFalse(summary["snowflake_cli_live_executed"])
        self.assertTrue(summary["snowflake_cli_live_skipped"])
        self.assertTrue(summary["snowflake_cli_live_validation_passed"])
        self.assertTrue(summary["snowflake_cli_live_validation_skipped"])
        self.assertFalse(summary["snowflake_cli_live_validation_required"])
        self.assertTrue(summary["render_provenance_reconciliation_passed"])
        self.assertEqual(summary["render_provenance_reconciliation_failure_count"], 0)
        self.assertTrue(summary["credential_expiration_gate_passed"])
        self.assertTrue(summary["credential_expiration_live_gate_passed"])
        self.assertEqual(summary["credential_expiring_30d_count"], 0)
        self.assertEqual(summary["credential_expired_count"], 0)
        self.assertEqual(summary["credential_next_expiration_days"], 0)
        self.assertEqual(summary["credential_live_validation_status"], "not_executed_static_contract")
        self.assertTrue(summary["user_display_name_gate_passed"])
        self.assertTrue(summary["user_display_name_live_gate_passed"])
        self.assertTrue(summary["user_display_surface_gate_passed"])
        self.assertTrue(summary["cortex_user_label_gate_passed"])
        self.assertEqual(summary["credential_first_paint_violation_count"], 0)
        self.assertEqual(summary["credential_export_leak_count"], 0)
        self.assertEqual(summary["user_id_daily_leak_count"], 0)
        self.assertTrue(summary["formula_value_reconciliation_passed"])
        self.assertEqual(summary["formula_validation_mode"], "fixture_static")
        self.assertTrue(summary["snowflake_formula_value_passed"])
        self.assertEqual(summary["snowflake_formula_value_failure_count"], 0)
        self.assertFalse(summary["snowflake_formula_live_passed"])
        self.assertTrue(summary["snowflake_formula_live_skipped"])
        self.assertTrue(summary["workload_formula_semantics_passed"])
        self.assertGreater(manifest["artifact_count"], 0)
        self.assertEqual(manifest["artifact_count"], hashes["hash_count"])
        self.assertEqual(manifest["artifact_count"], reconciliation["artifact_count"])
        self.assertEqual(hashes["hash_count"], reconciliation["hash_count"])
        self.assertTrue(product["passed"], product)
        self.assertTrue(product["checks"], product)
        for field in (
            "commit_range",
            "changed_files_summary",
            "launch_profile",
            "workflow_url",
            "artifact_bundle_name",
            "validation_commands",
            "hard_blockers",
            "known_skips_or_waivers",
            "live_snowflake_validation_status",
            "browser_proof_status",
            "snowflake_validation_status",
            "product_gauntlet_status",
            "rollback_notes",
            "operator_next_steps",
        ):
            self.assertIn(field, notes)
        self.assertTrue(all(row["passed"] for row in gate_matrix), gate_matrix)

    def test_release_artifact_reconciliation_rejects_manifest_drift(self):
        from tools.contracts import launch_readiness as readiness

        manifest = self._read_json("artifacts/release_candidate/artifact_manifest.json")
        hashes = self._read_json("artifacts/release_candidate/artifact_hashes.json")
        baseline = readiness._release_artifact_reconciliation_results(ROOT, manifest, hashes)
        self.assertTrue(baseline["passed"], baseline)
        non_self = next(row["path"] for row in manifest["files"] if not row.get("self_referential_hash"))

        unlisted_manifest = copy.deepcopy(manifest)
        unlisted_manifest["files"] = [row for row in unlisted_manifest["files"] if row["path"] != non_self]
        result = readiness._release_artifact_reconciliation_results(ROOT, unlisted_manifest, hashes)
        self.assertFalse(result["passed"])
        self.assertIn("RELEASE_UNLISTED_ARTIFACT", {row["code"] for row in result["failures"]})

        missing_manifest = copy.deepcopy(manifest)
        missing_manifest["files"][0]["path"] = "artifacts/release_candidate/does_not_exist.json"
        result = readiness._release_artifact_reconciliation_results(ROOT, missing_manifest, hashes)
        self.assertFalse(result["passed"])
        self.assertIn("RELEASE_MANIFEST_FILE_MISSING", {row["code"] for row in result["failures"]})

        hash_manifest = copy.deepcopy(manifest)
        for row in hash_manifest["files"]:
            if row["path"] == non_self:
                row["sha256"] = "0" * 64
                break
        result = readiness._release_artifact_reconciliation_results(ROOT, hash_manifest, hashes)
        self.assertFalse(result["passed"])
        self.assertIn("RELEASE_HASH_MISMATCH", {row["code"] for row in result["failures"]})

        missing_category_manifest = copy.deepcopy(manifest)
        missing_category_manifest["files"] = [
            row for row in missing_category_manifest["files"] if row["category"] != "snowflake_validation"
        ]
        result = readiness._release_artifact_reconciliation_results(ROOT, missing_category_manifest, hashes)
        self.assertFalse(result["passed"])
        self.assertIn("RELEASE_CATEGORY_MISSING", {row["code"] for row in result["failures"]})

        commit_manifest = copy.deepcopy(manifest)
        commit_manifest["files"][0]["commit_sha"] = "0" * 40
        result = readiness._release_artifact_reconciliation_results(ROOT, commit_manifest, hashes)
        self.assertFalse(result["passed"])
        self.assertIn("RELEASE_ARTIFACT_COMMIT_MISMATCH", {row["code"] for row in result["failures"]})

        stale_manifest = copy.deepcopy(manifest)
        stale_manifest["commit_sha"] = "0" * 40
        for row in stale_manifest["files"]:
            row["commit_sha"] = "0" * 40
        result = readiness._release_artifact_reconciliation_results(ROOT, stale_manifest, hashes)
        self.assertFalse(result["passed"])
        mismatch_paths = [
            item["path"]
            for item in result["commit_mismatches"]
        ]
        self.assertIn("artifacts/release_candidate/artifact_manifest.json", mismatch_paths)

        raw_manifest = copy.deepcopy(manifest)
        raw_manifest["files"][0]["contains_raw_sql"] = True
        result = readiness._release_artifact_reconciliation_results(ROOT, raw_manifest, hashes)
        self.assertFalse(result["passed"])
        self.assertIn("RELEASE_RAW_SQL_OR_SECRET", {row["code"] for row in result["failures"]})

        deleted_ref_manifest = copy.deepcopy(manifest)
        deleted_file = ROOT / "artifacts" / "release_candidate" / "deleted_reference_probe.json"
        deleted_file.write_text('{"route": "sections.command_deck"}', encoding="utf-8")
        try:
            deleted_ref_manifest["files"].append(
                {
                    **deleted_ref_manifest["files"][0],
                    "path": "artifacts/release_candidate/deleted_reference_probe.json",
                    "sha256": readiness._file_sha256(deleted_file),
                    "category": "release_candidate",
                    "self_referential_hash": False,
                }
            )
            result = readiness._release_artifact_reconciliation_results(ROOT, deleted_ref_manifest, hashes)
            self.assertFalse(result["passed"])
            self.assertIn("RELEASE_ARTIFACT_REFERENCES_DELETED_ITEM", {row["code"] for row in result["failures"]})
        finally:
            deleted_file.unlink(missing_ok=True)

    def test_product_gauntlet_release_rejects_raw_app_invariant_gaps(self):
        from tools.contracts import launch_readiness as readiness

        cases = [
            (
                "missing primary",
                lambda payloads: payloads.update(
                    {
                        "artifacts/full_app_validation/view_results.json": [
                            row
                            for row in payloads["artifacts/full_app_validation/view_results.json"]
                            if row.get("section") != "Security Monitoring"
                        ]
                    }
                ),
                "six_primary_overviews_rendered",
            ),
            (
                "route query leak",
                lambda payloads: self._mutate_first(
                    payloads["artifacts/full_app_validation/button_click_results.json"],
                    lambda row: row.get("action_type") == "route",
                    {"query_count": 1},
                ),
                "route_actions_zero_query",
            ),
            (
                "summary board first paint leak",
                lambda payloads: payloads["artifacts/full_app_validation/summary_board_results.json"][0].update(
                    {"passed": False, "account_usage_query_count": 1}
                ),
                "summary_board_packet_only_first_paint",
            ),
            (
                "evidence account usage",
                lambda payloads: payloads["artifacts/full_app_validation/evidence_loader_call_matrix.json"][0].update(
                    {"account_usage_used": True}
                ),
                "normal_evidence_compact_mart_backed",
            ),
            (
                "query search no click query",
                lambda payloads: self._mutate_first(
                    payloads["artifacts/full_app_validation/query_search_results.json"],
                    lambda row: row.get("case") == "render_no_click",
                    {"query_count": 1},
                ),
                "query_search_no_click_zero_cost",
            ),
            (
                "export hash mismatch",
                lambda payloads: payloads["artifacts/full_app_validation/export_results.json"][0].update(
                    {"hash_mismatch": True}
                ),
                "export_payloads_hash_and_row_valid",
            ),
            (
                "forbidden daily token",
                lambda payloads: payloads["artifacts/full_app_validation/forbidden_daily_ui_scan.json"].update(
                    {"blocked_count": 1}
                ),
                "daily_forbidden_token_scans_zero",
            ),
            (
                "settings ungated",
                lambda payloads: payloads["artifacts/full_app_validation/settings_action_results.json"][0].update(
                    {"admin_or_advanced_gated": False}
                ),
                "settings_actions_gated",
            ),
            (
                "live ungated",
                lambda payloads: payloads["artifacts/full_app_validation/live_feature_results.json"][0].update(
                    {"explicit_click_required": False}
                ),
                "live_features_gated",
            ),
            (
                "stress failure",
                lambda payloads: payloads["artifacts/full_app_validation/stress_results.json"][0].update(
                    {"threshold_passed": False, "threshold_failures": ["forced failure"]}
                ),
                "stress_thresholds_pass",
            ),
        ]
        for name, mutator, check_name in cases:
            with self.subTest(name=name):
                payloads = self._payload_copy()
                mutator(payloads)
                result = readiness._product_gauntlet_release_results(ROOT, payloads, self._launch_payload_copy())
                self.assertFalse(result["passed"], result)
                failed = {row["check_name"] for row in result["failures"]}
                self.assertIn(check_name, failed)

    def test_release_summary_fails_when_launch_readiness_fails(self):
        from tools.contracts import launch_readiness as readiness

        launch_summary = self._read_json("artifacts/launch_readiness/launch_readiness_summary.json")
        launch_summary = copy.deepcopy(launch_summary)
        launch_summary.update({"all_passed": False, "ci_artifact_reality_passed": True})
        summary, failures, matrix, notes = readiness._release_candidate_summary_bundle(
            launch_summary=launch_summary,
            launch_failures={"failures": []},
            matrix=self._read_json("artifacts/launch_readiness/release_gate_matrix.json"),
            release_gate=self._read_json("artifacts/launch_readiness/release_candidate_gate_results.json"),
            product_gauntlet=self._read_json("artifacts/release_candidate/product_gauntlet_release_results.json"),
            reconciliation=self._read_json("artifacts/release_candidate/artifact_reconciliation_results.json"),
            ci_context=self._read_json("artifacts/launch_readiness/release_candidate_ci_context.json"),
        )
        self.assertFalse(summary["all_passed"], summary)
        self.assertFalse(failures["passed"], failures)
        self.assertIn("launch_readiness", {row["gate"] for row in failures["failures"]})
        self.assertIn("launch_readiness", {row["gate"] for row in matrix})
        self.assertTrue(notes["waiver_section_present"])
        self.assertTrue(notes["blocker_section_present"])

    def test_release_summary_fails_when_snowflake_or_product_gauntlet_fails(self):
        from tools.contracts import launch_readiness as readiness

        base_summary = self._read_json("artifacts/launch_readiness/launch_readiness_summary.json")
        base_matrix = self._read_json("artifacts/launch_readiness/release_gate_matrix.json")
        launch_failures = {"failures": []}
        release_gate = self._read_json("artifacts/launch_readiness/release_candidate_gate_results.json")
        product = self._read_json("artifacts/release_candidate/product_gauntlet_release_results.json")
        reconciliation = self._read_json("artifacts/release_candidate/artifact_reconciliation_results.json")
        ci_context = self._read_json("artifacts/launch_readiness/release_candidate_ci_context.json")

        snowflake_summary = copy.deepcopy(base_summary)
        snowflake_summary["snowflake_validation_passed"] = False
        snowflake_matrix = copy.deepcopy(base_matrix)
        for row in snowflake_matrix:
            if row["gate"] == "snowflake_execution_validation":
                row["passed"] = False
        summary, failures, _matrix, _notes = readiness._release_candidate_summary_bundle(
            launch_summary=snowflake_summary,
            launch_failures=launch_failures,
            matrix=snowflake_matrix,
            release_gate=release_gate,
            product_gauntlet=product,
            reconciliation=reconciliation,
            ci_context=ci_context,
        )
        self.assertFalse(summary["all_passed"], summary)
        self.assertFalse(summary["snowflake_validation_passed"])
        self.assertFalse(failures["passed"], failures)

        bad_product = copy.deepcopy(product)
        bad_product.update({"passed": False, "failure_count": 1, "failures": [{"check_name": "route_actions_zero_query"}]})
        summary, failures, _matrix, _notes = readiness._release_candidate_summary_bundle(
            launch_summary=base_summary,
            launch_failures=launch_failures,
            matrix=base_matrix,
            release_gate=release_gate,
            product_gauntlet=bad_product,
            reconciliation=reconciliation,
            ci_context=ci_context,
        )
        self.assertFalse(summary["all_passed"], summary)
        self.assertFalse(summary["product_gauntlet_passed"])
        self.assertFalse(failures["passed"], failures)

    def test_query_budget_gate_fails_on_recorded_violation(self):
        from tools.contracts import launch_readiness as readiness

        payloads = self._payload_copy()
        payloads["artifacts/full_app_validation/query_budget_results.json"] = {
            "passed": True,
            "failed_contexts": [],
            "route_query_leaks": 0,
            "evidence_clicks_over_budget": 0,
            "marker_budget_mismatch_count": 0,
        }
        payloads["artifacts/full_app_validation/query_budget_violation_results.json"] = {
            "passed": False,
            "recorded": True,
            "violation_count": 1,
            "production_interrupting": False,
        }
        result = readiness._query_budget_gate_results(payloads)
        self.assertFalse(result["passed"], result)
        self.assertIn("QUERY_BUDGET_VIOLATION_RECORDED", {row["code"] for row in result["failures"]})
        self.assertFalse(result["production_interrupting"])

    def test_release_notes_operator_ready_rejects_missing_fields(self):
        from tools.contracts import launch_readiness as readiness

        notes = self._read_json("artifacts/release_candidate/release_notes.json")
        ci_context = self._read_json("artifacts/launch_readiness/release_candidate_ci_context.json")
        ready = readiness._release_notes_operator_ready(notes, ci_context)
        self.assertTrue(ready["passed"], ready)

        missing = copy.deepcopy(notes)
        missing.pop("hard_blockers", None)
        missing.pop("known_skips_or_waivers", None)
        missing.pop("rollback_notes", None)
        result = readiness._release_notes_operator_ready(missing, ci_context)
        self.assertFalse(result["passed"], result)
        self.assertIn("hard_blockers", result["missing_fields"])
        self.assertIn("known_skips_or_waivers", result["missing_fields"])
        self.assertIn("rollback_notes", result["missing_fields"])

    def test_ci_release_context_uses_github_actions_metadata_without_leaking_tokens(self):
        from tools.contracts import launch_readiness as readiness

        head = readiness._git_output("rev-parse", "HEAD")
        env = {
            "GITHUB_ACTIONS": "true",
            "GITHUB_RUN_ID": "123456789",
            "GITHUB_RUN_ATTEMPT": "2",
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "jfreeze03/OVERWATCH",
            "GITHUB_SHA": head,
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_WORKFLOW": "Validate",
            "GITHUB_JOB": "release-validation",
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_TOKEN": "ghp_do_not_record_this_token",
        }
        with patch.dict("os.environ", env, clear=False):
            ci_run = readiness._ci_run_review_results("prod_candidate", [])
            context = readiness._release_candidate_ci_context("prod_candidate", [])
        self.assertTrue(ci_run["passed"], ci_run)
        self.assertEqual(ci_run["workflow_url"], "https://github.com/jfreeze03/OVERWATCH/actions/runs/123456789")
        self.assertEqual(context["proof_source"], "github_actions_metadata")
        self.assertEqual(context["github_sha"], head)
        self.assertEqual(context["source_tree_sha"], head)
        self.assertEqual(context["artifact_upload_name"], "decision-workspace-proof")
        self.assertNotIn("GITHUB_TOKEN", json.dumps(context))
        self.assertNotIn("ghp_do_not_record", json.dumps(context))

        mismatch_env = dict(env)
        mismatch_env["GITHUB_SHA"] = "0" * 40
        with patch.dict("os.environ", mismatch_env, clear=False):
            ci_run = readiness._ci_run_review_results("prod_candidate", [])
        self.assertFalse(ci_run["passed"], ci_run)
        self.assertFalse(ci_run["commit_sha_matches_source"])

        local_env = {key: "" for key in env}
        local_env["GITHUB_ACTIONS"] = "false"
        with patch.dict("os.environ", local_env, clear=False):
            ci_run = readiness._ci_run_review_results("prod_candidate", [])
        self.assertFalse(ci_run["passed"], ci_run)
        self.assertTrue(ci_run["workflow_metadata_required"])
        self.assertTrue(ci_run["workflow_metadata_missing"])

        malformed_env = dict(env)
        malformed_env["GITHUB_SERVER_URL"] = ""
        with patch.dict("os.environ", malformed_env, clear=False):
            ci_run = readiness._ci_run_review_results("prod_candidate", [])
        self.assertFalse(ci_run["passed"], ci_run)
        self.assertTrue(ci_run["workflow_url_missing"])

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
            "artifacts/launch_readiness/snowflake_validation_gate_results.json",
            "artifacts/launch_readiness/live_execution_manifest_gate_results.json",
            "artifacts/launch_readiness/encoding_hygiene_results.json",
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

    def test_launch_profiles_are_profile_aware(self):
        profile = self._read_json("artifacts/launch_readiness/launch_profile_results.json")
        profile_failures = self._read_json("artifacts/launch_readiness/profile_gate_failures.json")
        live_history = self._read_json("artifacts/launch_readiness/live_query_history_results.json")
        summary = self._read_json("artifacts/launch_readiness/launch_readiness_summary.json")

        self.assertEqual(profile["selected_profile"], "internal_fixture")
        self.assertTrue(profile["passed"], profile)
        self.assertTrue(profile_failures["passed"], profile_failures)
        self.assertEqual(profile_failures["failure_count"], 0)
        self.assertFalse(profile["browser_proof_required"], profile)
        self.assertFalse(profile["live_query_history_required"], profile)
        self.assertTrue(live_history["passed"], live_history)
        self.assertTrue(summary["commit_sha"], summary)
        self.assertTrue(summary["branch_ref"], summary)
        self.assertIn("ci_metadata_warning", summary)
        if live_history["skipped"]:
            self.assertEqual(live_history["status"], "skipped_with_reason")
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
                "missing uploaded artifact",
                lambda payloads, launch: launch["artifact_upload_review_results"].update(
                    {"passed": False, "missing_upload_paths": ["artifacts/launch_readiness/**"], "missing_upload_path_count": 1}
                ),
                "artifact_upload_review",
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
            (
                "encoding hygiene block",
                lambda payloads, launch: launch["encoding_hygiene_results"].update(
                    {"passed": False, "blocked_count": 1}
                ),
                "encoding_hygiene",
            ),
        ]
        for name, mutator, gate in cases:
            with self.subTest(name=name):
                self._assert_launch_failure(mutator, gate)

    def test_launch_readiness_rejects_profile_proof_gaps(self):
        cases = [
            (
                "prod browser skipped",
                lambda payloads, launch: (
                    launch["launch_profile_results"].update(
                        {
                            "selected_profile": "prod_candidate",
                            "browser_proof_required": True,
                            "live_query_history_required": True,
                            "passed": True,
                        }
                    ),
                    launch["browser_smoke_results"].update(
                        {
                            "browser_required": True,
                            "browser_proof_skipped": True,
                            "skip_reason": "No browser worker was available for this release candidate.",
                            "passed": False,
                        }
                    ),
                ),
                "browser_or_rendered_snapshot",
            ),
            (
                "prod live skipped",
                lambda payloads, launch: (
                    launch["launch_profile_results"].update(
                        {
                            "selected_profile": "prod_candidate",
                            "browser_proof_required": True,
                            "live_query_history_required": True,
                            "passed": True,
                        }
                    ),
                    launch["live_query_history_results"].update(
                        {
                            "launch_profile": "prod_candidate",
                            "live_query_history_required": True,
                            "skipped": True,
                            "status": "missing",
                            "passed": False,
                        }
                    ),
                ),
                "live_query_history",
            ),
            (
                "prod snowflake validation skipped",
                lambda payloads, launch: (
                    launch["launch_profile_results"].update(
                        {
                            "selected_profile": "prod_candidate",
                            "browser_proof_required": True,
                            "live_query_history_required": True,
                            "passed": True,
                        }
                    ),
                    payloads["artifacts/snowflake_validation/snowflake_validation_summary.json"].update(
                        {
                            "live_mode_enabled": False,
                            "live_status": "skipped",
                            "passed": True,
                        }
                    ),
                ),
                "snowflake_execution_validation",
            ),
            (
                "prod snowflake cli validation skipped",
                lambda payloads, launch: (
                    launch["launch_profile_results"].update(
                        {
                            "selected_profile": "prod_candidate",
                            "browser_proof_required": True,
                            "live_query_history_required": True,
                            "passed": True,
                        }
                    ),
                    launch["snowflake_cli_live_gate_results"].update(
                        {
                            "launch_profile": "prod_candidate",
                            "live_required": True,
                            "skipped": True,
                            "passed": False,
                            "failure_count": 1,
                            "failures": [{"code": "SNOWFLAKE_CLI_LIVE_PROOF_MISSING"}],
                        }
                    ),
                ),
                "snowflake_cli_live_validation",
            ),
            (
                "internal live snowflake validation skipped",
                lambda payloads, launch: (
                    launch["launch_profile_results"].update(
                        {
                            "selected_profile": "internal_live",
                            "browser_proof_required": True,
                            "live_query_history_required": True,
                            "passed": True,
                        }
                    ),
                    payloads["artifacts/snowflake_validation/snowflake_validation_summary.json"].update(
                        {
                            "live_mode_enabled": False,
                            "live_status": "skipped",
                            "live_skip_reason": "Set OVERWATCH_SNOWFLAKE_VALIDATION=1 to run controlled live validation.",
                            "passed": True,
                        }
                    ),
                ),
                "snowflake_raw_validation_recheck",
            ),
            (
                "invalid waiver",
                lambda payloads, launch: launch["launch_profile_results"].update(
                    {
                        "selected_profile": "prod_candidate",
                        "passed": False,
                        "invalid_waiver_count": 1,
                        "failures": ["One or more launch waivers is missing owner, reason, or expiration/review note."],
                    }
                ),
                "launch_profile",
            ),
            (
                "prod missing ci metadata",
                lambda payloads, launch: (
                    launch["launch_profile_results"].update(
                        {
                            "selected_profile": "prod_candidate",
                            "browser_proof_required": True,
                            "live_query_history_required": True,
                            "passed": True,
                        }
                    ),
                    launch["ci_run_review_results"].update(
                        {
                            "launch_profile": "prod_candidate",
                            "workflow_metadata_required": True,
                            "workflow_metadata_missing": True,
                            "passed": False,
                        }
                    ),
                ),
                "ci_run_review",
            ),
        ]
        for name, mutator, gate in cases:
            with self.subTest(name=name):
                self._assert_launch_failure(mutator, gate)

    def test_launch_readiness_rejects_invalid_profiles_and_waivers(self):
        cases = [
            (
                "invalid profile",
                lambda payloads, launch: launch["launch_profile_results"].update(
                    {"selected_profile": "surprise_release", "recognized_profile": False, "passed": False, "failures": ["Unknown profile."]}
                ),
                "launch_profile",
            ),
            (
                "waiver without owner",
                lambda payloads, launch: launch["launch_waivers"].update(
                    {
                        "waivers": [
                            {
                                "gate": "browser_proof",
                                "reason": "Browser worker unavailable.",
                                "expiration_or_review_note": "Review before launch promotion.",
                                "approving_surface": "Launch review",
                            }
                        ]
                    }
                ),
                "profile_gate_failures",
            ),
            (
                "generic waiver reason",
                lambda payloads, launch: launch["launch_waivers"].update(
                    {
                        "waivers": [
                            {
                                "gate": "browser_proof",
                                "owner": "Release captain",
                                "reason": "todo",
                                "expiration_or_review_note": "Review before launch promotion.",
                                "approving_surface": "Launch review",
                            }
                        ]
                    }
                ),
                "profile_gate_failures",
            ),
            (
                "expired waiver",
                lambda payloads, launch: launch["launch_waivers"].update(
                    {
                        "waivers": [
                            {
                                "gate": "live_query_history",
                                "owner": "Release captain",
                                "reason": "Snowflake proof window unavailable.",
                                "expiration": "2000-01-01T00:00:00+00:00",
                                "approving_surface": "Launch review",
                            }
                        ]
                    }
                ),
                "profile_gate_failures",
            ),
        ]
        for name, mutator, gate in cases:
            with self.subTest(name=name):
                self._assert_launch_failure(mutator, gate)

    def test_launch_readiness_rejects_browser_snapshot_failure_rows(self):
        cases = [
            (
                "missing rendered launch coverage",
                lambda payloads, launch: launch["browser_required_coverage"].update(
                    {"passed": True, "missing_coverage": ["query_search"], "missing_coverage_count": 1}
                ),
            ),
            (
                "daily leakage in snapshot",
                lambda payloads, launch: launch["browser_smoke_results"].update(
                    {"daily_forbidden_blocked_count": 1, "passed": True}
                ),
            ),
            (
                "missing deterministic snapshots",
                lambda payloads, launch: launch["browser_smoke_results"].update(
                    {"deterministic_snapshots_present": False, "passed": True}
                ),
            ),
        ]
        for name, mutator in cases:
            with self.subTest(name=name):
                self._assert_launch_failure(mutator, "browser_or_snapshot_failures")

    def test_launch_readiness_recomputes_raw_row_invariants(self):
        cases = [
            (
                "route query leak",
                lambda payloads, launch: self._mutate_first(
                    payloads["artifacts/full_app_validation/button_click_results.json"],
                    lambda row: row.get("action_type") == "route",
                    {"actual_snowflake_executions": 1, "session_open_count": 0, "direct_sql_event_count": 0},
                ),
            ),
            (
                "first paint leak",
                lambda payloads, launch: payloads["artifacts/full_app_validation/view_results.json"][0]["first_paint"].update(
                    {"observed_non_packet_first_paint_events": 1}
                ),
            ),
            (
                "warm first paint packet query",
                lambda payloads, launch: payloads["artifacts/full_app_validation/view_results.json"][0]["first_paint"].update(
                    {"warm_packet_queries": 1}
                ),
            ),
            (
                "missing primary section",
                lambda payloads, launch: payloads.update(
                    {
                        "artifacts/full_app_validation/view_results.json": [
                            row
                            for row in payloads["artifacts/full_app_validation/view_results.json"]
                            if row.get("section") != "Security Monitoring"
                        ]
                    }
                ),
            ),
            (
                "normal evidence Account Usage",
                lambda payloads, launch: payloads["artifacts/full_app_validation/evidence_loader_call_matrix.json"][0].update(
                    {"account_usage_used": True}
                ),
            ),
            (
                "export hash mismatch",
                lambda payloads, launch: payloads["artifacts/full_app_validation/export_results.json"][0].update(
                    {"sha256": "0" * 64}
                ),
            ),
            (
                "case missing freshness",
                lambda payloads, launch: payloads["artifacts/full_app_validation/case_payload_results.json"][0].pop(
                    "freshness", None
                ),
            ),
            (
                "unclicked settings action",
                lambda payloads, launch: payloads["artifacts/full_app_validation/settings_action_results.json"][0].update(
                    {"clicked": False, "skip_reason": "", "owner": "", "review_note": ""}
                ),
            ),
            (
                "unclicked live feature",
                lambda payloads, launch: payloads["artifacts/full_app_validation/live_feature_results.json"][0].update(
                    {"clicked": False, "skip_reason": "", "owner": "", "review_note": ""}
                ),
            ),
            (
                "unconfirmed Account Usage cost",
                lambda payloads, launch: self._mutate_first(
                    payloads["artifacts/full_app_validation/query_search_results.json"],
                    lambda row: row.get("case") == "account_usage_fallback_unconfirmed",
                    {"snowflake_execution_count": 1},
                ),
            ),
            (
                "forbidden export token",
                lambda payloads, launch: payloads["artifacts/full_app_validation/forbidden_export_scan.json"].update(
                    {"blocked_count": 1, "passed": False}
                ),
            ),
            (
                "stale artifact",
                lambda payloads, launch: payloads["artifacts/cleanup/cleanup_summary.json"].update(
                    {"stale_generated_artifact_count": 1}
                ),
            ),
            (
                "unknown SQL object",
                lambda payloads, launch: payloads["artifacts/cleanup/sql_object_inventory.json"].setdefault(
                    "unknown", []
                ).append({"name": "MART_UNKNOWN_LAUNCH_LEFTOVER"}),
            ),
        ]
        for name, mutator in cases:
            with self.subTest(name=name):
                self._assert_launch_failure(mutator, "raw_invariants")

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
                "ci artifact reality",
                lambda payloads, launch: launch["ci_artifact_reality_results"].update(
                    {"passed": False, "failure_count": 1, "uploaded_artifact_names": []}
                ),
                "ci_artifact_reality",
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
            (
                "snowflake compile",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/procedure_compile_results.json"][0].update({"status": "failed"}),
                "procedure_compile_validation",
            ),
            (
                "snowflake compile coverage",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/procedure_compile_coverage_results.json"].update(
                    {"passed": False, "failure_count": 1}
                ),
                "procedure_compile_validation",
            ),
            (
                "snowflake smoke coverage",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/procedure_smoke_call_coverage_results.json"].update(
                    {"passed": False, "failure_count": 1}
                ),
                "procedure_smoke_call_validation",
            ),
            (
                "snowflake live session",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/live_validation_session_results.json"].update(
                    {"passed": False, "status": "failed", "failure_count": 1}
                ),
                "snowflake_raw_validation_recheck",
            ),
            (
                "snowflake live environment",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/live_validation_environment_results.json"].update(
                    {"passed": False, "failure_count": 1}
                ),
                "snowflake_raw_validation_recheck",
            ),
            (
                "live execution manifest",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/live_execution_manifest.json"].update(
                    {"passed": False, "failure_count": 1}
                ),
                "snowflake_raw_validation_recheck",
            ),
            (
                "manifest missing compile row",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/procedure_compile_results.json"][0].update(
                    {"live_execution_manifest_id": ""}
                ),
                "procedure_compile_validation",
            ),
            (
                "manifest missing smoke row",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/procedure_smoke_call_results.json"][0].update(
                    {"live_execution_manifest_id": ""}
                ),
                "procedure_smoke_call_validation",
            ),
            (
                "manifest raw sql",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/live_execution_manifest.json"]["entries"][0].update(
                    {"raw_sql_included": True}
                ),
                "snowflake_raw_validation_recheck",
            ),
            (
                "manifest static row in live mode",
                lambda payloads, launch: (
                    payloads["artifacts/snowflake_validation/snowflake_validation_summary.json"].update(
                        {"live_mode_enabled": True, "live_status": "enabled", "passed": True}
                    ),
                    payloads["artifacts/snowflake_validation/live_execution_manifest.json"]["entries"][0].update(
                        {"expected_mode": "live", "observed_mode": "static"}
                    ),
                ),
                "snowflake_raw_validation_recheck",
            ),
            (
                "manifest reconciliation artifact",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/live_execution_manifest_reconciliation.json"].update(
                    {"passed": False, "failure_count": 1, "orphan_manifest_entry_count": 1}
                ),
                "live_execution_manifest_gate",
            ),
            (
                "manifest category coverage artifact",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/live_execution_manifest_category_coverage.json"].update(
                    {"passed": False, "failure_count": 1, "category_failure_count": 1}
                ),
                "live_execution_manifest_gate",
            ),
            (
                "manifest orphan raw row",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/live_execution_manifest.json"]["entries"].append(
                    {
                        **payloads["artifacts/snowflake_validation/live_execution_manifest.json"]["entries"][0],
                        "validation_id": "orphan-launch-ledger-entry",
                        "artifact": "procedure_compile_results.json",
                    }
                ),
                "live_execution_manifest_gate",
            ),
            (
                "manifest unknown artifact id",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/procedure_compile_results.json"][0].update(
                    {"live_execution_manifest_id": "unknown-launch-ledger-entry"}
                ),
                "live_execution_manifest_gate",
            ),
            (
                "manifest row index mismatch",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/live_execution_manifest.json"]["entries"][0].update(
                    {"row_index": 999}
                ),
                "live_execution_manifest_gate",
            ),
            (
                "manifest row key mismatch",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/live_execution_manifest.json"]["entries"][0].update(
                    {"row_key": "wrong-row-key"}
                ),
                "live_execution_manifest_gate",
            ),
            (
                "manifest status mismatch",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/live_execution_manifest.json"]["entries"][0].update(
                    {"status": "failed"}
                ),
                "live_execution_manifest_gate",
            ),
            (
                "session missing manifest id",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/live_validation_session_results.json"].pop(
                    "live_execution_manifest_id", None
                ),
                "snowflake_raw_validation_recheck",
            ),
            (
                "missing packet raw artifact",
                lambda payloads, launch: payloads.pop("artifacts/snowflake_validation/packet_publication_validation_results.json", None),
                "snowflake_raw_validation_recheck",
            ),
            (
                "packet status lies",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/packet_shape_results.json"].update(
                    {"passed": True, "failure_count": 0, "checks": {"current_rows_unique": False}}
                ),
                "packet_publication_validation",
            ),
            (
                "packet detail failure",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/packet_validation_detail_results.json"]["checks"][0].update(
                    {"passed": False}
                ),
                "packet_publication_validation",
            ),
            (
                "packet detail missing actual expected",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/packet_validation_detail_results.json"]["checks"][0].pop(
                    "actual", None
                ),
                "packet_publication_validation",
            ),
            (
                "packet missing field names absent",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/packet_validation_detail_results.json"].update(
                    {"packet_missing_field_count": 1, "packet_missing_fields": []}
                ),
                "packet_publication_validation",
            ),
            (
                "packet duplicate array names absent",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/packet_validation_detail_results.json"].update(
                    {"packet_duplicate_array_count": 1, "packet_duplicate_arrays": []}
                ),
                "packet_publication_validation",
            ),
            (
                "compact status lies",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/compact_evidence_mart_validation_results.json"]["marts"][0].update(
                    {"passed": False}
                ),
                "compact_evidence_mart_validation",
            ),
            (
                "compact detail failure",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/compact_evidence_mart_detail_results.json"]["marts"][0].update(
                    {"retention_bounded": False, "passed": False}
                ),
                "compact_evidence_mart_validation",
            ),
            (
                "compact missing target column names",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/compact_evidence_mart_detail_results.json"]["marts"][0].update(
                    {"target_lookup_columns_present": False, "missing_target_lookup_columns": []}
                ),
                "compact_evidence_mart_validation",
            ),
            (
                "compact missing loader sections",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/compact_evidence_mart_detail_results.json"]["marts"][0].update(
                    {"loader_matrix_references": True, "loader_matrix_sections": []}
                ),
                "compact_evidence_mart_validation",
            ),
            (
                "recent snowflake fix",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/recent_snowflake_fix_validation_results.json"].update({"passed": False}),
                "recent_snowflake_fix_validation",
            ),
            (
                "trend cardinality raw failure",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/trend_cardinality_results.json"].update({"passed": False, "failure_count": 1}),
                "snowflake_raw_validation_recheck",
            ),
            (
                "schema drift raw failure",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/schema_drift_results.json"].update({"passed": False, "failure_count": 1}),
                "snowflake_raw_validation_recheck",
            ),
            (
                "snowflake error sanitizer failure",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/snowflake_error_sanitization_results.json"].update(
                    {"passed": False, "failure_count": 1}
                ),
                "recent_snowflake_fix_validation",
            ),
            (
                "missing snowflake skip reason",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/snowflake_validation_summary.json"].update(
                    {"live_mode_enabled": False, "live_status": "skipped", "live_skip_reason": "", "passed": True}
                ),
                "snowflake_raw_validation_recheck",
            ),
            (
                "snowflake manifest",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/streamlit_manifest_validation_results.json"].update({"passed": False}),
                "streamlit_manifest_validation",
            ),
            (
                "snowflake phases",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/phase_validation_results.json"].update({"passed": False}),
                "snowflake_phase_validation",
            ),
            (
                "snowflake fast refresh",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/refresh_fast_results.json"].update({"passed": False}),
                "refresh_performance_validation",
            ),
            (
                "snowflake refresh missing freshness counts",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/refresh_fast_results.json"].pop(
                    "fresh_command_row_count", None
                ),
                "snowflake_raw_validation_recheck",
            ),
            (
                "snowflake refresh detail",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/refresh_detail_results.json"].update({"passed": False, "failure_count": 1}),
                "refresh_performance_validation",
            ),
            (
                "compact evidence",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/compact_evidence_mart_validation_results.json"].update({"passed": False}),
                "compact_evidence_mart_validation",
            ),
            (
                "packet shape",
                lambda payloads, launch: payloads["artifacts/snowflake_validation/packet_shape_results.json"].update({"passed": False}),
                "packet_publication_validation",
            ),
            (
                "encoding hygiene",
                lambda payloads, launch: launch["encoding_hygiene_results"].update({"passed": False, "blocked_count": 1}),
                "encoding_hygiene",
            ),
        ]
        for name, mutator, gate in cases:
            with self.subTest(name=name):
                self._assert_launch_failure(mutator, gate)

    def test_launch_readiness_workflow_uploads_launch_artifacts(self):
        ci_review = self._read_json("artifacts/launch_readiness/ci_artifact_review_results.json")
        ci_reality = self._read_json("artifacts/launch_readiness/ci_artifact_reality_results.json")
        self.assertTrue(ci_review["passed"], ci_review)
        self.assertEqual(ci_review["missing_upload_paths"], [])
        self.assertEqual(ci_review["missing_steps"], [])
        self.assertIn("artifacts/release_candidate/**", ci_review["required_upload_paths"])
        self.assertIn("artifacts/snowflake_validation/**", ci_review["required_upload_paths"])
        self.assertIn("artifacts/encoding_hygiene_results.json", ci_review["required_upload_paths"])
        self.assertIn("scripts/run_snowflake_cli_live_validation.ps1", ci_review["required_upload_paths"])
        self.assertIn("scripts/run_snowflake_cli_live_validation.sh", ci_review["required_upload_paths"])
        self.assertTrue(ci_reality["passed"], ci_reality)
        self.assertIn("decision-workspace-proof", ci_reality["uploaded_artifact_names"])

    def _assert_launch_failure(self, mutator, expected_gate: str) -> None:
        from tools.contracts.launch_readiness import evaluate_launch_readiness

        payloads = self._payload_copy()
        launch = self._launch_payload_copy()
        mutator(payloads, launch)
        summary, failures, matrix = evaluate_launch_readiness(payloads, launch, root=ROOT)
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

    def _mutate_first(self, rows, predicate, updates) -> None:
        for row in rows:
            if predicate(row):
                row.update(updates)
                return
        self.fail("No matching row found for mutation")

    @staticmethod
    def _read_json(rel: str):
        return json.loads((ROOT / rel).read_text(encoding="utf-8"))

    @classmethod
    def _load_payloads(cls):
        from tools.contracts.full_app_gauntlet import REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS
        from tools.contracts.snowflake_execution_validation import SNOWFLAKE_VALIDATION_DIR

        payloads = {
            rel: json.loads((ROOT / rel).read_text(encoding="utf-8"))
            for rel in REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS
            if (ROOT / rel).exists()
        }
        snowflake_dir = ROOT / SNOWFLAKE_VALIDATION_DIR
        for path in snowflake_dir.glob("*.json"):
            payloads[f"{SNOWFLAKE_VALIDATION_DIR}/{path.name}"] = json.loads(path.read_text(encoding="utf-8"))
        return payloads

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
