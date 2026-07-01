from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _passing_payload() -> dict:
    return {
        "artifacts/full_app_validation/settings_action_results.json": [
            {
                "section": "Settings",
                "workflow": "Default",
                "label": "Open Setup Health",
                "stable_key": "settings_open_setup_health",
                "control_key": "settings_open_setup_health",
                "action_type": "setup_health",
                "clicked": True,
                "admin_or_advanced_gated": True,
                "passed": True,
            }
        ],
        "artifacts/full_app_validation/live_feature_results.json": [
            {
                "section": "Settings/Admin Setup Health",
                "workflow": "Setup Health",
                "label": "Refresh Setup Health",
                "stable_key": "decision_setup_health_refresh",
                "control_key": "decision_setup_health_refresh",
                "clicked": True,
                "explicit_click_required": True,
                "admin_or_advanced_gated": True,
                "timeout_or_row_limit": True,
                "first_paint_invocation": False,
                "route_invocation": False,
                "passed": True,
            }
        ],
        "artifacts/full_app_validation/rendered_fragments.json": [
            {
                "section": "Settings",
                "workflow": "Default",
                "text": "Cost estimates use configured credit rates.",
            },
            {
                "section": "Settings/Admin Setup Health",
                "workflow": "Setup Health",
                "admin_only": True,
                "text": "Setup Health",
            },
        ],
    }


class SettingsLiveFeatureGauntletTests(unittest.TestCase):
    def test_passing_settings_and_live_feature_contract(self):
        from tools.contracts.settings_live_feature_gauntlet import build_settings_live_feature_results

        results = build_settings_live_feature_results(_passing_payload())

        self.assertTrue(results["passed"], results)
        self.assertTrue(results["setup_health_reachable"])
        self.assertTrue(results["setup_health_admin_gated"])

    def test_setup_health_without_click_fails(self):
        from tools.contracts.settings_live_feature_gauntlet import build_settings_live_feature_results

        payload = _passing_payload()
        payload["artifacts/full_app_validation/settings_action_results.json"][0]["clicked"] = False
        payload["artifacts/full_app_validation/settings_action_results.json"][0]["skip_reason"] = ""

        results = build_settings_live_feature_results(payload)

        self.assertFalse(results["passed"])
        self.assertGreater(results["settings_failure_count"], 0)

    def test_live_feature_first_paint_invocation_fails(self):
        from tools.contracts.settings_live_feature_gauntlet import build_settings_live_feature_results

        payload = _passing_payload()
        payload["artifacts/full_app_validation/live_feature_results.json"][0]["first_paint_invocation"] = True

        results = build_settings_live_feature_results(payload)

        self.assertFalse(results["passed"])
        self.assertGreater(results["live_feature_failure_count"], 0)

    def test_settings_default_with_raw_token_fails(self):
        from tools.contracts.settings_live_feature_gauntlet import build_settings_live_feature_results

        payload = _passing_payload()
        payload["artifacts/full_app_validation/rendered_fragments.json"][0][
            "text"
        ] = "Cost estimates use configured credit rates. ACCOUNT_USAGE"

        results = build_settings_live_feature_results(payload)

        self.assertFalse(results["passed"])
        self.assertTrue(any(row["area"] == "settings_render" for row in results["failures"]))


if __name__ == "__main__":
    unittest.main()
