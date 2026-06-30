from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ActionClickGauntletTests(unittest.TestCase):
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
                            {"label": "View all priorities", "stable_key": "view_all_priorities"}
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
