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
        self.assertTrue(summary["snowflake_validation_passed"])
        self.assertFalse(summary["snowflake_live_validation_enabled"])
        self.assertTrue(summary["snowflake_live_validation_skipped"])
        self.assertIn("OVERWATCH_SNOWFLAKE_VALIDATION", summary["snowflake_validation_skip_reason"])
        self.assertEqual(summary["live_validation_status"], "static_skipped")
        self.assertEqual(summary["live_validation_waiver_id"], "")
        self.assertEqual(summary["live_validation_waiver_owner"], "")
        self.assertEqual(summary["live_validation_waiver_expiration"], "")
        self.assertGreater(summary["procedure_compile_count"], 0)
        self.assertEqual(summary["procedure_compile_failure_count"], 0)
        self.assertGreater(summary["procedure_smoke_call_count"], 0)
        self.assertEqual(summary["procedure_smoke_failure_count"], 0)
        self.assertEqual(summary["refresh_fast_status"], "skipped")
        self.assertEqual(summary["refresh_full_status"], "skipped")
        self.assertEqual(summary["packet_validation_status"], "passed")
        self.assertEqual(summary["compact_evidence_validation_status"], "passed")
        self.assertTrue(summary["encoding_hygiene_passed"])
        self.assertEqual(summary["encoding_blocked_count"], 0)
        self.assertGreaterEqual(summary["required_artifact_count"], len(REQUIRED_LAUNCH_READINESS_ARTIFACTS))
        self.assertIn("decision-workspace-proof", summary["uploaded_artifact_names"])
        self.assertFalse(summary["raw_sql_included"])

        matrix_by_gate = {row["gate"]: row for row in matrix}
        for gate in (
            "launch_profile",
            "profile_gate_failures",
            "raw_invariants",
            "full_app_gauntlet",
            "runtime_validation",
            "required_artifacts",
            "artifact_upload_review",
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
        ):
            self.assertIn(gate, matrix_by_gate)
            self.assertTrue(matrix_by_gate[gate]["passed"], matrix_by_gate[gate])

        snowflake_gate = self._read_json("artifacts/launch_readiness/snowflake_validation_gate_results.json")
        self.assertIn("OVERWATCH_SNOWFLAKE_VALIDATION", snowflake_gate["snowflake_validation_skip_reason"])
        self.assertEqual(snowflake_gate["live_validation_status"], "static_skipped")
        self.assertEqual(snowflake_gate["packet_validation_status"], "passed")
        self.assertEqual(snowflake_gate["compact_evidence_validation_status"], "passed")
        raw_recheck = self._read_json("artifacts/launch_readiness/snowflake_raw_validation_recheck.json")
        snowflake_failures = self._read_json("artifacts/launch_readiness/snowflake_validation_failures.json")
        self.assertTrue(raw_recheck["passed"], raw_recheck)
        self.assertEqual(raw_recheck["failure_count"], 0, raw_recheck)
        self.assertEqual(raw_recheck["packet_validation_status"], "passed")
        self.assertEqual(raw_recheck["compact_evidence_validation_status"], "passed")
        self.assertEqual(raw_recheck["live_validation_status"], "static_skipped")
        self.assertTrue(snowflake_failures["passed"], snowflake_failures)
        self.assertEqual(snowflake_failures["failure_count"], 0, snowflake_failures)

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
            "artifacts/launch_readiness/snowflake_validation_gate_results.json",
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
        self.assertTrue(ci_review["passed"], ci_review)
        self.assertEqual(ci_review["missing_upload_paths"], [])
        self.assertEqual(ci_review["missing_steps"], [])

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
