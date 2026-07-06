from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ActionClickGauntletTests(unittest.TestCase):
    def test_button_action_area_classification_is_exact(self):
        sys.path.insert(0, str(ROOT / ".overwatch_final"))
        from sections.button_action_contracts import resolve_button_action_contract

        cases = [
            {
                "section": "Executive Landing",
                "workflow": "Overview",
                "label": "Executive Landing",
                "key": "nav_btn_MONITORING CORE_Executive Landing",
                "area": "sidebar_navigation",
            },
            {
                "section": "Advanced Scope",
                "workflow": "Active filters",
                "label": "Advanced Scope",
                "key": "sidebar_panel_advanced_scope",
                "area": "sidebar_panel_toggle",
            },
            {
                "section": "Settings",
                "workflow": "Default",
                "label": "Open Setup Health",
                "key": "settings_open_setup_health",
                "area": "setup_health_admin",
            },
            {
                "section": "Workload Operations",
                "workflow": "Query Investigation",
                "label": "Search deep history fallback",
                "key": "qs_account_usage_fallback",
                "area": "live_feature",
            },
        ]
        for case in cases:
            with self.subTest(case=case):
                contract = resolve_button_action_contract(
                    section=case["section"],
                    workflow=case["workflow"],
                    label=case["label"],
                    key=case["key"],
                )
                self.assertIsNotNone(contract)
                self.assertEqual(contract.to_artifact()["action_area"], case["area"])

    def test_unclicked_visible_button_fails_gate(self):
        from tools.contracts.action_click_gauntlet import build_action_click_results, evaluate_action_click_gate

        payload = {
            "artifacts/full_app_validation/button_click_results.json": [
                {"section": "Executive Landing", "label": "View all priorities", "clicked": False, "passed": True}
            ]
        }
        _manifest, results = build_action_click_results(payload)
        gate = evaluate_action_click_gate(results)

        self.assertFalse(results["passed"])
        self.assertFalse(gate["passed"])

    def test_live_feature_first_paint_invocation_fails(self):
        from tools.contracts.action_click_gauntlet import evaluate_live_feature_gate

        gate = evaluate_live_feature_gate(
            [
                {
                    "feature": "FAST refresh",
                    "passed": True,
                    "first_paint_invocation": True,
                    "route_invocation": False,
                    "explicit_click_required": True,
                    "admin_or_advanced_gated": True,
                    "timeout_or_row_limit": True,
                    "sanitized_error_state": True,
                    "raw_error_visible_daily": False,
                }
            ]
        )

        self.assertFalse(gate["passed"])

    def test_rendered_action_without_click_result_fails(self):
        from tools.contracts.action_click_gauntlet import build_action_click_results

        _manifest, results = build_action_click_results(
            {
                "artifacts/full_app_validation/rendered_fragments.json": [
                    {
                        "section": "Executive Landing",
                        "workflow": "Overview",
                        "action_like_elements": [
                            {
                                "label": "View all priorities",
                                "stable_key": "view_all_priorities",
                                "action_area": "route_action",
                            }
                        ],
                    }
                ],
                "artifacts/full_app_validation/button_click_results.json": [],
            }
        )

        self.assertFalse(results["passed"])
        self.assertTrue(
            any(row.get("failure_reason") == "rendered_action_without_click_result" for row in results["failures"])
        )
        self.assertTrue(any(row.get("action_key") == "view_all_priorities" for row in results["rows"]))
        self.assertTrue(any(row.get("action_area") == "route_action" for row in results["rows"]))

    def test_rendered_action_area_mismatch_fails(self):
        from tools.contracts.action_click_gauntlet import build_action_click_results

        _manifest, results = build_action_click_results(
            {
                "artifacts/full_app_validation/rendered_fragments.json": [
                    {
                        "section": "Settings",
                        "workflow": "Default",
                        "action_like_elements": [
                            {
                                "label": "Open Setup Health",
                                "stable_key": "settings_open_setup_health",
                                "action_area": "setup_health_admin",
                            }
                        ],
                    }
                ],
                "artifacts/full_app_validation/settings_action_results.json": [
                    {
                        "section": "Settings",
                        "workflow": "Default",
                        "label": "Open Setup Health",
                        "stable_key": "settings_open_setup_health",
                        "action_area": "settings_control",
                        "clicked": True,
                        "passed": True,
                    }
                ],
            }
        )

        self.assertFalse(results["passed"])
        self.assertTrue(any(row.get("failure_reason") == "rendered_action_area_mismatch" for row in results["failures"]))

    def test_rendered_action_prefix_key_does_not_match(self):
        from tools.contracts.action_click_gauntlet import build_action_click_results

        _manifest, results = build_action_click_results(
            {
                "artifacts/full_app_validation/rendered_fragments.json": [
                    {
                        "id": "alert::overview",
                        "section": "Alert Center",
                        "workflow": "Active Alerts",
                        "action_like_elements": [
                            {
                                "label": "Review Credential Expirations",
                                "stable_key": "alert_center_command_brief_primary_security_credential_expirations",
                                "action_area": "route_action",
                            }
                        ],
                    }
                ],
                "artifacts/full_app_validation/button_click_results.json": [
                    {
                        "section": "Alert Center",
                        "workflow": "Active Alerts",
                        "label": "Review Credential Expirations",
                        "stable_key": "alert_center_command_brief_primary_security",
                        "action_area": "route_action",
                        "clicked": True,
                        "passed": True,
                    }
                ],
            }
        )

        self.assertFalse(results["passed"])
        self.assertTrue(any(row.get("failure_reason") == "rendered_action_without_click_result" for row in results["failures"]))

    def test_rendered_action_wrong_section_click_fails(self):
        from tools.contracts.action_click_gauntlet import build_action_click_results

        _manifest, results = build_action_click_results(
            {
                "artifacts/full_app_validation/rendered_fragments.json": [
                    {
                        "id": "security::overview",
                        "section": "Security Monitoring",
                        "workflow": "Security Overview",
                        "action_like_elements": [
                            {
                                "label": "Open Security Details",
                                "stable_key": "security_monitoring_security_overview_load_security_evidence",
                                "action_area": "evidence_action",
                            }
                        ],
                    }
                ],
                "artifacts/full_app_validation/button_click_results.json": [
                    {
                        "section": "Alert Center",
                        "workflow": "Active Alerts",
                        "label": "Open Security Details",
                        "stable_key": "security_monitoring_security_overview_load_security_evidence",
                        "action_area": "evidence_action",
                        "clicked": True,
                        "passed": True,
                    }
                ],
            }
        )

        self.assertFalse(results["passed"])
        self.assertTrue(any(row.get("failure_reason") == "rendered_action_surface_mismatch" for row in results["failures"]))
