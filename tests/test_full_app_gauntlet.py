import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


PRIMARY_SECTIONS = [
    "Executive Landing",
    "DBA Control Room",
    "Alert Center",
    "Cost & Contract",
    "Workload Operations",
    "Security Monitoring",
]


QUERY_SEARCH_CASES = [
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
]


STRESS_CASES = [
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
]


class FullAppGauntletTests(unittest.TestCase):
    def test_artifact_cleanup_removes_nested_directories_on_windows(self):
        from tools.contracts.full_app_gauntlet import _clean_artifact_directories

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "artifacts" / "launch_readiness" / "nested"
            nested.mkdir(parents=True)
            (nested / "gate.json").write_text("{}", encoding="utf-8")
            (root / "artifacts" / "full_app_validation").mkdir(parents=True)
            (root / "artifacts" / "full_app_inventory").mkdir(parents=True)
            (root / "artifacts" / "cleanup").mkdir(parents=True)

            _clean_artifact_directories(root)

            self.assertFalse((root / "artifacts" / "launch_readiness").exists())
            self.assertTrue((root / "artifacts").exists())

    def test_full_app_gauntlet_is_runtime_product_gate(self):
        from tools.contracts.full_app_gauntlet import (
            REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS,
            write_full_app_gauntlet_artifacts,
        )

        artifacts = write_full_app_gauntlet_artifacts(ROOT)
        self.assertTrue(REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS.issubset(artifacts))

        def read_json(rel: str):
            return json.loads((ROOT / rel).read_text(encoding="utf-8"))

        summary = read_json("artifacts/full_app_validation/app_validation_summary.json")
        manifest = read_json("artifacts/full_app_validation/artifact_manifest.json")
        views = read_json("artifacts/full_app_validation/view_results.json")
        controls = read_json("artifacts/full_app_validation/control_inventory.json")
        clicks = read_json("artifacts/full_app_validation/button_click_results.json")
        exports = read_json("artifacts/full_app_validation/export_results.json")
        settings = read_json("artifacts/full_app_validation/settings_action_results.json")
        live = read_json("artifacts/full_app_validation/live_feature_results.json")
        evidence = read_json("artifacts/full_app_validation/evidence_loader_call_matrix.json")
        stress = read_json("artifacts/full_app_validation/stress_results.json")
        slow = read_json("artifacts/full_app_validation/slow_runtime_inventory.json")
        errors = read_json("artifacts/full_app_validation/error_inventory.json")
        risk = read_json("artifacts/full_app_validation/risk_inventory.json")
        control_click = read_json("artifacts/full_app_validation/control_click_coverage.json")
        query_budget = read_json("artifacts/full_app_validation/query_budget_results.json")
        session_direct = read_json("artifacts/full_app_validation/session_direct_sql_results.json")
        gauntlet = read_json("artifacts/full_app_validation/gauntlet_results.json")
        gauntlet_failures = read_json("artifacts/full_app_validation/gauntlet_failures.json")
        recomputed = read_json("artifacts/full_app_validation/gauntlet_recomputed_invariants.json")
        sql_scan_inventory = read_json("artifacts/sql_performance_lint_file_inventory.json")

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
        self.assertEqual(
            control_click["action_control_count"],
            control_click["clicked_action_control_count"] + control_click["explicitly_skipped_action_control_count"],
        )
        self.assertEqual(control_click["missing_action_control_count"], 0, control_click)
        self.assertEqual(control_click["generic_skip_reason_count"], 0, control_click)
        self.assertEqual(control_click["unowned_skip_reason_count"], 0, control_click)
        self.assertEqual(control_click["expired_skip_reason_count"], 0, control_click)
        self.assertTrue(query_budget["passed"], query_budget)
        self.assertTrue(session_direct["passed"], session_direct)
        self.assertTrue(gauntlet["passed"], gauntlet)
        self.assertTrue(gauntlet["hard_gate_passed"], gauntlet)
        self.assertTrue(gauntlet["recomputed_invariants_passed"], gauntlet)
        self.assertEqual(gauntlet["failure_count"], 0, gauntlet)
        self.assertTrue(gauntlet_failures["passed"], gauntlet_failures)
        self.assertEqual(gauntlet_failures["failures"], [])
        self.assertTrue(recomputed["passed"], recomputed)
        self.assertEqual(recomputed["failure_count"], 0, recomputed)
        self.assertTrue(sql_scan_inventory["passed"], sql_scan_inventory)
        self.assertTrue(sql_scan_inventory["includes_validation_sql"], sql_scan_inventory)
        self.assertTrue(sql_scan_inventory["includes_drop_sql"], sql_scan_inventory)
        self.assertTrue(sql_scan_inventory["includes_secure_view_audit_sql"], sql_scan_inventory)
        self.assertEqual(sql_scan_inventory["missing_expected_files"], [], sql_scan_inventory)
        self.assertEqual(sql_scan_inventory["skipped_files"], [], sql_scan_inventory)
        self.assertIn("snowflake/OVERWATCH_MART_VALIDATION.sql", sql_scan_inventory["scanned_files"])
        self.assertIn("snowflake/OVERWATCH_MART_DROP.sql", sql_scan_inventory["scanned_files"])
        self.assertIn("snowflake/OVERWATCH_DYNAMIC_TABLE_SECURE_VIEW_AUDIT.sql", sql_scan_inventory["scanned_files"])
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

    def test_gauntlet_rejects_missing_artifact(self):
        from tools.contracts.full_app_gauntlet import evaluate_full_app_gauntlet

        results, failures = evaluate_full_app_gauntlet(
            self._passing_payloads(),
            missing_artifacts=["artifacts/full_app_validation/view_results.json"],
        )
        self.assertFalse(results["passed"])
        self.assertTrue(any(row["gate"] == "missing_artifacts" for row in failures["failures"]))

    def test_summary_cannot_pass_when_hard_gate_fails(self):
        self._assert_injected_failure(
            lambda payloads: payloads["artifacts/full_app_validation/app_validation_summary.json"].update(
                {"all_passed": True, "hard_gate_passed": False}
            ),
            "app_validation_summary",
        )

    def test_gauntlet_rejects_failed_sub_artifacts(self):
        cases = [
            (
                "query_budget_results false",
                lambda payloads: payloads["artifacts/full_app_validation/query_budget_results.json"].update({"passed": False}),
                "query_budget_results",
            ),
            (
                "session_direct_sql_results false",
                lambda payloads: payloads["artifacts/full_app_validation/session_direct_sql_results.json"].update({"passed": False}),
                "session_direct_sql_results",
            ),
            (
                "control_click_coverage false",
                lambda payloads: payloads["artifacts/full_app_validation/control_click_coverage.json"].update({"passed": False}),
                "control_click_coverage",
            ),
            (
                "risk inventory false",
                lambda payloads: payloads["artifacts/full_app_validation/risk_inventory.json"].update({"passed": False}),
                "risk_inventory",
            ),
        ]
        for name, mutator, gate in cases:
            with self.subTest(name=name):
                self._assert_injected_failure(mutator, gate)

    def test_gauntlet_recomputes_runtime_invariant_failures(self):
        cases = [
            (
                "route leak",
                lambda payloads: payloads["artifacts/full_app_validation/button_click_results.json"][0].update({"actual_snowflake_executions": 1}),
                "recomputed_route_action_zero_cost",
            ),
            (
                "first paint leak",
                lambda payloads: payloads["artifacts/full_app_validation/view_results.json"][0]["first_paint"].update(
                    {"observed_non_packet_first_paint_events": 1}
                ),
                "recomputed_first_paint_zero_non_packet",
            ),
            (
                "warm first paint packet leak",
                lambda payloads: payloads["artifacts/full_app_validation/view_results.json"][0]["first_paint"].update(
                    {"observed_warm_packet_queries": 1}
                ),
                "recomputed_warm_first_paint_zero_packet",
            ),
            (
                "summary board Account Usage first paint",
                lambda payloads: payloads["artifacts/full_app_validation/summary_board_results.json"][0].update(
                    {"passed": False, "account_usage_query_count": 1, "failed_checks": ["account_usage_on_first_paint"]}
                ),
                "recomputed_summary_board_packet_only_first_paint",
            ),
            (
                "missing primary evidence",
                lambda payloads: payloads.__setitem__(
                    "artifacts/full_app_validation/evidence_loader_call_matrix.json",
                    [
                        row for row in payloads["artifacts/full_app_validation/evidence_loader_call_matrix.json"]
                        if row["section"] != "Security Monitoring"
                    ],
                ),
                "recomputed_evidence_primary_section_coverage",
            ),
            (
                "normal evidence classified advanced",
                lambda payloads: payloads["artifacts/full_app_validation/evidence_loader_call_matrix.json"][0].update(
                    {"query_boundary": "advanced_diagnostics"}
                ),
                "recomputed_normal_evidence_source",
            ),
            (
                "normal evidence Account Usage",
                lambda payloads: payloads["artifacts/full_app_validation/evidence_loader_call_matrix.json"][0].update(
                    {"account_usage_used": True}
                ),
                "recomputed_normal_evidence_source",
            ),
            (
                "Workload missing normal evidence",
                lambda payloads: payloads.__setitem__(
                    "artifacts/full_app_validation/evidence_loader_call_matrix.json",
                    [
                        row for row in payloads["artifacts/full_app_validation/evidence_loader_call_matrix.json"]
                        if row["section"] != "Workload Operations" or row["loader_kind"] != "normal_evidence"
                    ],
                ),
                "recomputed_workload_evidence_coverage",
            ),
            (
                "generic loader",
                lambda payloads: payloads["artifacts/full_app_validation/evidence_loader_call_matrix.json"][0].update(
                    {"expected_loader_name": "sections.security.run_query"}
                ),
                "recomputed_evidence_loader_specificity",
            ),
            (
                "evidence row mismatch",
                lambda payloads: payloads["artifacts/full_app_validation/evidence_loader_call_matrix.json"][0].update({"case_row_count": 99}),
                "recomputed_evidence_row_count_match",
            ),
            (
                "export row mismatch",
                lambda payloads: payloads["artifacts/full_app_validation/export_results.json"][0].update({"parsed_row_count": 7}),
                "recomputed_export_payload_integrity",
            ),
            (
                "export missing payload file",
                lambda payloads: payloads["artifacts/full_app_validation/export_results.json"][0].update({"payload_file": ""}),
                "recomputed_export_payload_integrity",
            ),
            (
                "default export query text",
                lambda payloads: payloads["artifacts/full_app_validation/export_results.json"][0].update({"query_text_included": True}),
                "recomputed_export_payload_integrity",
            ),
            (
                "case payload missing freshness",
                lambda payloads: payloads["artifacts/full_app_validation/case_payload_results.json"][0].update({"freshness": ""}),
                "recomputed_case_payload_integrity",
            ),
            (
                "case payload missing source",
                lambda payloads: payloads["artifacts/full_app_validation/case_payload_results.json"][0].update({"source": ""}),
                "recomputed_case_payload_integrity",
            ),
            (
                "unclicked settings",
                lambda payloads: payloads["artifacts/full_app_validation/settings_action_results.json"][0].update(
                    {"clicked": False, "skip_reason": "", "owner": "", "review_note": ""}
                ),
                "recomputed_settings_click_or_skip",
            ),
            (
                "unclicked live",
                lambda payloads: payloads["artifacts/full_app_validation/live_feature_results.json"][0].update(
                    {"clicked": False, "skip_reason": "", "owner": "", "review_note": ""}
                ),
                "recomputed_live_click_or_skip",
            ),
            (
                "live missing budget",
                lambda payloads: payloads["artifacts/full_app_validation/live_feature_results.json"][0].update({"observed_contexts": []}),
                "recomputed_live_budget_gating",
            ),
            (
                "live first paint",
                lambda payloads: payloads["artifacts/full_app_validation/live_feature_results.json"][0].update({"first_paint_invocation": True}),
                "recomputed_live_budget_gating",
            ),
            (
                "live missing control key",
                lambda payloads: payloads["artifacts/full_app_validation/live_feature_results.json"][0].update({"control_key": ""}),
                "recomputed_live_budget_gating",
            ),
            (
                "live missing admin gating",
                lambda payloads: payloads["artifacts/full_app_validation/live_feature_results.json"][0].update({"admin_or_advanced_gated": False}),
                "recomputed_live_budget_gating",
            ),
            (
                "query search missing no result",
                lambda payloads: payloads.__setitem__(
                    "artifacts/full_app_validation/query_search_results.json",
                    [
                        row for row in payloads["artifacts/full_app_validation/query_search_results.json"]
                        if row["case"] != "no_result_search"
                    ],
                ),
                "recomputed_query_search_case_coverage",
            ),
            (
                "unconfirmed account usage cost",
                lambda payloads: self._query_case(payloads, "account_usage_fallback_unconfirmed").update(
                    {"snowflake_execution_count": 1}
                ),
                "recomputed_query_search_invariants",
            ),
            (
                "preview raw SQL visible",
                lambda payloads: self._query_case(payloads, "sql_preview").update({"raw_sql_visible_in_daily_ui": True}),
                "recomputed_query_search_invariants",
            ),
            (
                "exact query ID over limit",
                lambda payloads: self._query_case(payloads, "exact_query_id").update({"max_rows": 2}),
                "recomputed_query_search_invariants",
            ),
            (
                "stress threshold failure",
                lambda payloads: payloads["artifacts/full_app_validation/stress_results.json"][0].update(
                    {"threshold_passed": False, "threshold_failures": ["route query cost exceeded"]}
                ),
                "recomputed_stress_thresholds",
            ),
            (
                "large bounded evidence",
                lambda payloads: self._stress_case(payloads, "large_bounded_evidence_result")["export_summary"].update(
                    {"export_row_count": 501}
                ),
                "recomputed_large_evidence_bound",
            ),
            (
                "forbidden export token",
                lambda payloads: payloads["artifacts/full_app_validation/forbidden_export_scan.json"].update({"blocked_count": 1}),
                "recomputed_forbidden_token_scan",
            ),
            (
                "forbidden daily UI token",
                lambda payloads: payloads["artifacts/full_app_validation/forbidden_daily_ui_scan.json"].update({"blocked_count": 1}),
                "recomputed_forbidden_token_scan",
            ),
            (
                "forbidden source token",
                lambda payloads: payloads["artifacts/full_app_validation/forbidden_source_token_scan.json"].update({"blocked_count": 1}),
                "recomputed_forbidden_token_scan",
            ),
            (
                "unknown SQL object",
                lambda payloads: payloads["artifacts/cleanup/sql_object_inventory.json"].update({"unknown": [{"object": "OLD_TABLE"}]}),
                "recomputed_unknown_sql_objects",
            ),
            (
                "dead route",
                lambda payloads: payloads["artifacts/cleanup/route_state_inventory.json"].update({"dead_routes": [{"route": "old"}]}),
                "recomputed_dead_routes",
            ),
            (
                "stale artifact",
                lambda payloads: payloads["artifacts/cleanup/cleanup_summary.json"].update({"stale_generated_artifact_count": 1}),
                "recomputed_stale_artifacts",
            ),
            (
                "SQL linter error",
                lambda payloads: payloads["artifacts/sql_performance_lint_findings.json"].append(
                    {"severity": "error", "code": "ACCOUNT_USAGE_UNBOUNDED"}
                ),
                "recomputed_sql_lint_errors",
            ),
            (
                "SQL scan misses drop",
                lambda payloads: payloads["artifacts/sql_performance_lint_file_inventory.json"].update({"includes_drop_sql": False}),
                "recomputed_sql_scan_file_coverage",
            ),
            (
                "SQL scan misses secure view audit",
                lambda payloads: payloads["artifacts/sql_performance_lint_file_inventory.json"].update({"includes_secure_view_audit_sql": False}),
                "recomputed_sql_scan_file_coverage",
            ),
            (
                "generic skipped action control",
                lambda payloads: payloads["artifacts/full_app_validation/control_click_coverage.json"].update({"generic_skip_reason_count": 1}),
                "recomputed_control_click_coverage",
            ),
            (
                "unowned skipped action control",
                lambda payloads: payloads["artifacts/full_app_validation/control_click_coverage.json"].update({"unowned_skip_reason_count": 1}),
                "recomputed_control_click_coverage",
            ),
            (
                "expired skipped action control",
                lambda payloads: payloads["artifacts/full_app_validation/control_click_coverage.json"].update({"expired_skip_reason_count": 1}),
                "recomputed_control_click_coverage",
            ),
        ]
        for name, mutator, gate in cases:
            with self.subTest(name=name):
                self._assert_injected_failure(mutator, gate)

    def test_gauntlet_recomputes_payload_hash_and_manifest_failures_from_disk(self):
        from tools.contracts.full_app_gauntlet import evaluate_full_app_gauntlet

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payloads = self._passing_payloads()
            payload_rel = payloads["artifacts/full_app_validation/export_results.json"][0]["payload_file"]
            payload_path = root / payload_rel
            payload_path.parent.mkdir(parents=True, exist_ok=True)
            payload_path.write_text("id,name\n1,alpha\n", encoding="utf-8")
            payloads["artifacts/full_app_validation/export_results.json"][0].update(
                {
                    "sha256": "bad",
                    "content_length": payload_path.stat().st_size,
                }
            )
            results, failures = evaluate_full_app_gauntlet(payloads, root=root)
        self.assertFalse(results["passed"], failures)
        self.assertTrue(any(row["gate"] == "recomputed_export_payload_integrity" for row in failures["failures"]), failures)

    def test_gauntlet_rejects_unlisted_stale_artifact_file(self):
        from tools.contracts.full_app_gauntlet import evaluate_full_app_gauntlet

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale = root / "artifacts" / "full_app_validation" / "stale.json"
            stale.parent.mkdir(parents=True, exist_ok=True)
            stale.write_text("{}", encoding="utf-8")
            manifest = stale.parent / "artifact_manifest.json"
            manifest.write_text(json.dumps({"files": ["artifacts/full_app_validation/artifact_manifest.json"]}), encoding="utf-8")
            results, failures = evaluate_full_app_gauntlet(self._passing_payloads(), root=root)
        self.assertFalse(results["passed"], failures)
        self.assertTrue(any(row["gate"] == "recomputed_manifest_unlisted_files" for row in failures["failures"]), failures)

    def _assert_injected_failure(self, mutator, expected_gate: str) -> None:
        from tools.contracts.full_app_gauntlet import evaluate_full_app_gauntlet

        payloads = self._passing_payloads()
        mutator(payloads)
        results, failures = evaluate_full_app_gauntlet(payloads)
        matched = [row for row in failures["failures"] if row["gate"] == expected_gate]
        self.assertFalse(results["passed"], failures)
        self.assertTrue(matched, failures)
        self.assertTrue(matched[0].get("recommendation"), matched[0])

    def _query_case(self, payloads: dict, case: str) -> dict:
        for row in payloads["artifacts/full_app_validation/query_search_results.json"]:
            if row["case"] == case:
                return row
        self.fail(f"missing query case {case}")

    def _stress_case(self, payloads: dict, case: str) -> dict:
        for row in payloads["artifacts/full_app_validation/stress_results.json"]:
            if row["case"] == case:
                return row
        self.fail(f"missing stress case {case}")

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
        evidence_rows = [
            self._evidence_row("Executive Landing", "sections.executive_landing_shell._load_executive_snapshot"),
            self._evidence_row("DBA Control Room", "sections.dba_control_room.render._load_control_room"),
            self._evidence_row("Alert Center", "sections.alert_center._load_center_data"),
            self._evidence_row("Cost & Contract", "sections.cost_contract_evidence.load_cost_evidence"),
            self._evidence_row("Workload Operations", "sections.workload_operations.load_change_event_detail"),
            self._evidence_row("Workload Operations", "sections.workload_operations.load_change_correlation_detail"),
            self._evidence_row(
                "Workload Operations",
                "sections.query_search.search_recent_query_summary",
                loader_kind="query_search",
                query_boundary="query_search",
                max_rows=1,
            ),
            self._evidence_row("Security Monitoring", "sections.security_posture_overview_view._load_security_brief"),
            self._evidence_row("Security Monitoring", "sections.security_posture_access_changes_view.load_change_event_detail"),
            self._evidence_row("Security Monitoring", "sections.security_posture_privilege_sprawl_view.load_privileged_grant_readiness"),
        ]
        query_search_rows = [self._query_search_row(case) for case in QUERY_SEARCH_CASES]
        stress_rows = [self._stress_row(case) for case in STRESS_CASES]
        summary_board_rows = [
            {
                "source": "summary_board_first_paint_contract",
                "proof_source": "runtime_render",
                "section": section,
                "workflow": "Runtime validation",
                "rendered": True,
                "packet_only": True,
                "packet_query_count": 1,
                "warm_packet_query_count": 0,
                "non_packet_first_paint_event_count": 0,
                "session_open_count": 0,
                "direct_sql_event_count": 0,
                "account_usage_query_count": 0,
                "evidence_query_count": 0,
                "semantic_regions_missing": [],
                "packet_fields_missing": [],
                "optional_detail_state_reads": [],
                "old_surface_marker_count": 0,
                "raw_internal_token_count": 0,
                "passed": True,
                "failed_checks": [],
            }
            for section in PRIMARY_SECTIONS
        ]
        return copy.deepcopy({
            "artifacts/full_app_validation/app_validation_summary.json": summary,
            "artifacts/full_app_validation/view_results.json": [
                {
                    "section": section,
                    "proof_source": "runtime_render",
                    "first_paint": {
                        "observed_packet_queries": 1,
                        "observed_non_packet_first_paint_events": 0,
                        "observed_warm_packet_queries": 0,
                        "observed_session_opens": 0,
                        "observed_direct_sql_events": 0,
                    },
                    "passed": True,
                }
                for section in PRIMARY_SECTIONS
            ],
            "artifacts/full_app_validation/button_click_results.json": [
                {
                    "section": "Executive Landing",
                    "workflow": "Overview",
                    "key": "route_exec",
                    "action_type": "route",
                    "actual_snowflake_executions": 0,
                    "session_open_count": 0,
                    "direct_sql_event_count": 0,
                    "passed": True,
                    "proof_source": "runtime_click",
                },
                {
                    "section": "Cost & Contract",
                    "workflow": "Cost Evidence",
                    "key": "cost_load_evidence",
                    "action_type": "evidence_load",
                    "expected_snowflake_execution_count": 1,
                    "actual_snowflake_executions": 1,
                    "session_open_count": 0,
                    "direct_sql_event_count": 0,
                    "passed": True,
                    "proof_source": "runtime_click",
                },
            ],
            "artifacts/full_app_validation/control_inventory.json": [
                {"kind": "button", "key": "route_exec", "label": "Open", "proof_source": "runtime_render"},
            ],
            "artifacts/full_app_validation/control_contract_coverage.json": {"passed": True, "proof_source": "runtime_render"},
            "artifacts/full_app_validation/control_click_coverage.json": {
                "passed": True,
                "proof_source": "runtime_click",
                "action_control_count": 2,
                "clicked_action_control_count": 2,
                "explicitly_skipped_action_control_count": 0,
                "missing_action_control_count": 0,
                "generic_skip_reason_count": 0,
                "unowned_skip_reason_count": 0,
                "expired_skip_reason_count": 0,
                "duplicate_key_count": 0,
                "blank_label_count": 0,
                "unknown_action_control_count": 0,
            },
            "artifacts/full_app_validation/export_results.json": [
                {
                    "section": "Workload Operations",
                    "workflow": "Query Investigation",
                    "filename": "query-search-results.csv",
                    "payload_file": "artifacts/full_app_validation/generated_exports/query-search-results.csv",
                    "sha256": "0" * 64,
                    "content_type": "text/csv",
                    "content_length": 24,
                    "parsed_row_count": 1,
                    "visible_row_count": 1,
                    "row_count": 1,
                    "admin_only": False,
                    "query_text_included": False,
                    "raw_internal_token_count": 0,
                    "passed": True,
                    "proof_source": "runtime_export",
                }
            ],
            "artifacts/full_app_validation/case_payload_results.json": [
                {
                    "section": "Cost & Contract",
                    "workflow": "Cost Evidence",
                    "scope": "ALFA / ALL / 7",
                    "target": "Selected finding",
                    "freshness": "current",
                    "source": "MART_COST_EVIDENCE_RECENT",
                    "summary": "Targeted cost evidence",
                    "row_count": 1,
                    "visible_row_count": 1,
                    "payload_hash": "1" * 64,
                    "passed": True,
                    "proof_source": "runtime_export",
                }
            ],
            "artifacts/full_app_validation/settings_action_results.json": [
                {
                    "control_key": "decision_setup_health_refresh",
                    "label": "Refresh",
                    "clicked": True,
                    "owner": "Decision Workspace setup/admin",
                    "review_note": "Current Settings/Admin Setup Health action validated by runtime gauntlet.",
                    "expected_query_budget_context": "admin_setup",
                    "observed_query_budget_contexts": ["admin_setup"],
                    "admin_or_advanced_gated": True,
                    "sanitized_error_state": True,
                    "raw_error_visible_daily": False,
                    "passed": True,
                    "proof_source": "runtime_click",
                }
            ],
            "artifacts/full_app_validation/live_feature_results.json": [
                {
                    "control_key": "advanced_diagnostics_refresh",
                    "label": "Refresh diagnostics",
                    "clicked": True,
                    "owner": "Decision Workspace live/admin",
                    "review_note": "Current live/admin feature validated by runtime gauntlet.",
                    "expected_query_budget_context": "advanced_diagnostics",
                    "observed_contexts": ["advanced_diagnostics"],
                    "explicit_click_required": True,
                    "admin_or_advanced_gated": True,
                    "timeout_or_row_limit": True,
                    "permission_denied_sanitized": True,
                    "unavailable_snowflake_sanitized": True,
                    "first_paint_invocation": False,
                    "route_invocation": False,
                    "raw_error_visible_daily": False,
                    "passed": True,
                    "proof_source": "runtime_click",
                }
            ],
            "artifacts/full_app_validation/evidence_loader_call_matrix.json": evidence_rows,
            "artifacts/full_app_validation/query_search_results.json": query_search_rows,
            "artifacts/full_app_validation/stress_results.json": stress_rows,
            "artifacts/full_app_validation/forbidden_ui_token_scan.json": {"blocked_count": 0, "passed": True},
            "artifacts/full_app_validation/forbidden_daily_ui_scan.json": {"blocked_count": 0, "passed": True},
            "artifacts/full_app_validation/forbidden_source_token_scan.json": {"blocked_count": 0, "passed": True},
            "artifacts/full_app_validation/forbidden_export_scan.json": {"blocked_count": 0, "passed": True},
            "artifacts/full_app_validation/gauntlet_artifact_reconciliation.json": {"passed": True},
            "artifacts/full_app_validation/risk_inventory.json": {"passed": True, "proof_source": "runtime_click"},
            "artifacts/full_app_validation/query_budget_results.json": {"passed": True, "proof_source": "runtime_click"},
            "artifacts/full_app_validation/session_direct_sql_results.json": {"passed": True, "proof_source": "runtime_click"},
            "artifacts/full_app_validation/summary_board_results.json": summary_board_rows,
            "artifacts/full_app_validation/summary_board_query_budget_results.json": {
                "passed": True,
                "failure_count": 0,
                "failures": [],
                "proof_source": "runtime_render",
            },
            "artifacts/full_app_validation/summary_board_error_inventory.json": {
                "passed": True,
                "failure_count": 0,
                "failures_by_section": {},
                "proof_source": "runtime_render",
            },
            "artifacts/full_app_validation/summary_board_failure_diagnostics.json": {
                "passed": True,
                "failure_count": 0,
                "diagnostics": [],
                "proof_source": "runtime_render",
            },
            "artifacts/cleanup/cleanup_summary.json": {"stale_generated_artifact_count": 0},
            "artifacts/cleanup/sql_object_inventory.json": {"unknown": []},
            "artifacts/cleanup/route_state_inventory.json": {"dead_routes": []},
            "artifacts/direct_sql_static_scan.json": {"blocked_count": 0},
            "artifacts/session_open_static_scan.json": {"blocked_count": 0},
            "artifacts/sql_performance_lint_findings.json": [],
            "artifacts/sql_performance_lint_file_inventory.json": {
                "passed": True,
                "includes_validation_sql": True,
                "includes_drop_sql": True,
                "includes_secure_view_audit_sql": True,
                "includes_full_snowflake_tree": True,
                "missing_expected_files": [],
                "skipped_files": [],
                "scanned_files": [
                    "snowflake/OVERWATCH_MART_SETUP.sql",
                    "snowflake/OVERWATCH_MART_VALIDATION.sql",
                    "snowflake/OVERWATCH_MART_DROP.sql",
                    "snowflake/OVERWATCH_DYNAMIC_TABLE_SECURE_VIEW_AUDIT.sql",
                ],
            },
        })

    def _evidence_row(
        self,
        section: str,
        loader_name: str,
        *,
        loader_kind: str = "normal_evidence",
        query_boundary: str = "evidence",
        max_rows: int = 200,
    ) -> dict:
        return {
            "source": "runtime_real_loader_spy_matrix",
            "proof_source": "runtime_click",
            "section": section,
            "workflow": "Runtime validation",
            "expected_loader_name": loader_name,
            "observed_loader_name": loader_name,
            "loader_called": True,
            "button_key": "load_evidence",
            "loader_kind": loader_kind,
            "query_boundary": query_boundary,
            "expected_query_budget_context": "evidence_click" if loader_kind == "normal_evidence" else "query_search_exact",
            "requires_admin": False,
            "compact_table_family": "FACT_QUERY_DETAIL_RECENT" if loader_kind == "query_search" else "MART_QUERY_EVIDENCE_RECENT",
            "target_label": "Selected finding",
            "target_context_seen": True,
            "target_columns_used": ["QUERY_ID"],
            "target_predicate_plan_id": "target-plan-1",
            "max_rows": max_rows,
            "row_count": 1,
            "returned_row_count": 1,
            "panel_row_count": 1,
            "export_row_count": 1,
            "case_row_count": 1,
            "account_usage_used": False,
            "normal_evidence_source_allowed": True,
            "passed": True,
        }

    def _query_search_row(self, case: str) -> dict:
        max_rows_by_case = {
            "exact_query_id": 1,
            "query_signature": 200,
            "related_executions": 50,
            "sql_preview": 1,
        }
        zero_cost_cases = {
            "render_no_click",
            "text_contains_no_autorun",
            "warehouse_prefill_no_autorun",
            "account_usage_fallback_unconfirmed",
        }
        return {
            "case": case,
            "source": "runtime_query_search_click" if case not in zero_cost_cases else "runtime_query_search_render",
            "proof_source": "runtime_click" if case not in zero_cost_cases else "runtime_render",
            "control_key_clicked": "" if case in zero_cost_cases else "qs_run",
            "observed_contexts": [] if case in zero_cost_cases else ["query_search_exact"],
            "observed_boundaries": {"query_search_broad_explicit": 1} if case == "account_usage_fallback_confirmed" else {"query_search": 1},
            "max_rows": max_rows_by_case.get(case, 200 if case == "text_contains_explicit_search" else 0),
            "session_open_count": 0,
            "direct_sql_event_count": 0,
            "snowflake_execution_count": 0 if case in zero_cost_cases else 1,
            "metadata_probe_count": 0,
            "export_count": 1 if case == "default_export_no_query_text" else 0,
            "payload_file": "artifacts/full_app_validation/generated_exports/query-search-results.csv"
            if case == "default_export_no_query_text"
            else "",
            "raw_sql_visible_in_daily_ui": False,
            "query_text_included": False,
            "sanitized_error_state": case not in {"permission_denied", "slow_query_timeout"} or True,
            "raw_error_visible_daily": False,
            "passed": True,
        }

    def _stress_row(self, case: str) -> dict:
        sections = PRIMARY_SECTIONS if case == "rapid_section_switching" else ["Workload Operations"]
        export_summary = {"export_row_count": 500 if case == "large_bounded_evidence_result" else 1}
        return {
            "case": case,
            "source": "runtime_stress_sequence",
            "proof_source": "runtime_stress",
            "sequence_steps": ["render", "click"],
            "actions_clicked": ["load_evidence"],
            "sections_touched": sections,
            "elapsed_ms": 12,
            "query_counts_by_boundary": {"evidence": 1} if "evidence" in case else {},
            "session_open_count": 0,
            "direct_sql_count": 0,
            "warning_count": 0,
            "error_count": 0,
            "sanitized_error_state": True,
            "state_delta_summary": {"changed_keys": 1},
            "export_summary": export_summary,
            "threshold": {"max_snowflake_executions": 1, "max_rows": 500},
            "actuals": {"snowflake_executions": 1, "rows": export_summary["export_row_count"]},
            "threshold_passed": True,
            "threshold_failures": [],
            "passed": True,
            "failure_reason": "",
        }


if __name__ == "__main__":
    unittest.main()
