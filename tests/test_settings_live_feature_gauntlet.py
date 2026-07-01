from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _passing_payload() -> dict:
    control_rows = [
        {"section": "Settings", "workflow": "Default", "kind": "select", "key": "settings_theme_picker", "label": "Theme"},
        {"section": "Settings", "workflow": "Default", "kind": "number_input", "key": "_credit_price_input", "label": "$/credit (compute)"},
        {"section": "Settings", "workflow": "Default", "kind": "number_input", "key": "_ai_credit_price_input", "label": "$/AI credit (Cortex)"},
        {"section": "Settings", "workflow": "Default", "kind": "number_input", "key": "_storage_cost_input", "label": "$/TB/month (storage)"},
        {"section": "Settings", "workflow": "Default", "kind": "text_input", "key": "_alert_email_targets_input", "label": "Alert email recipients"},
        {"section": "Settings", "workflow": "Default", "kind": "select", "key": "rt_interval", "label": "Live refresh interval"},
        {"section": "Settings", "workflow": "Default", "kind": "select", "key": "overwatch_idle_timeout_seconds", "label": "Idle query pause"},
        {"section": "Settings", "workflow": "Default", "kind": "button", "key": "settings_open_setup_health", "label": "Open Setup Health"},
    ]
    live_rows = [
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
        },
        {
            "section": "Settings/Admin Setup Health",
            "workflow": "Setup Health",
            "label": "FAST refresh validation",
            "stable_key": "settings_fast_refresh_validation",
            "owner_skipped": True,
            "skip_reason": "covered by Snowflake CLI live lane",
            "explicit_click_required": True,
            "admin_or_advanced_gated": True,
            "timeout_or_row_limit": True,
            "first_paint_invocation": False,
            "route_invocation": False,
            "passed": True,
        },
        {
            "section": "Settings/Admin Setup Health",
            "workflow": "Setup Health",
            "label": "FULL dry-run validation",
            "stable_key": "settings_full_refresh_dry_run_validation",
            "owner_skipped": True,
            "skip_reason": "covered by Snowflake CLI live lane",
            "explicit_click_required": True,
            "admin_or_advanced_gated": True,
            "timeout_or_row_limit": True,
            "first_paint_invocation": False,
            "route_invocation": False,
            "passed": True,
        },
        {
            "section": "Settings/Admin Setup Health",
            "workflow": "Setup Health",
            "label": "Snowflake CLI live validation",
            "stable_key": "settings_snowflake_cli_live_validation",
            "owner_skipped": True,
            "skip_reason": "local CLI lane writes its own artifact",
            "explicit_click_required": True,
            "admin_or_advanced_gated": True,
            "timeout_or_row_limit": True,
            "first_paint_invocation": False,
            "route_invocation": False,
            "passed": True,
        },
        {
            "section": "Settings/Admin Setup Health",
            "workflow": "Setup Health",
            "label": "Query history proof",
            "stable_key": "settings_query_history_proof",
            "owner_skipped": True,
            "skip_reason": "requires Snowflake query-history permission",
            "explicit_click_required": True,
            "admin_or_advanced_gated": True,
            "timeout_or_row_limit": True,
            "first_paint_invocation": False,
            "route_invocation": False,
            "passed": True,
        },
        {
            "section": "DBA Control Room",
            "workflow": "Advanced Diagnostics",
            "label": "Show Advanced Diagnostics",
            "stable_key": "dba_control_room_show_advanced_diagnostics",
            "clicked": True,
            "explicit_click_required": True,
            "admin_or_advanced_gated": True,
            "timeout_or_row_limit": True,
            "first_paint_invocation": False,
            "route_invocation": False,
            "passed": True,
        },
        {
            "section": "Settings/Admin Setup Health",
            "workflow": "Setup Health",
            "label": "Account Usage fallback",
            "stable_key": "settings_account_usage_fallback",
            "owner_skipped": True,
            "skip_reason": "deep fallback requires explicit confirmation",
            "explicit_click_required": True,
            "admin_or_advanced_gated": True,
            "timeout_or_row_limit": True,
            "first_paint_invocation": False,
            "route_invocation": False,
            "passed": True,
        },
        {
            "section": "Cost & Contract",
            "workflow": "Cost Workbench",
            "label": "Cost Workbench live load",
            "stable_key": "cost_workbench_live_load",
            "owner_skipped": True,
            "skip_reason": "covered by explicit Cost Workbench action contract",
            "explicit_click_required": True,
            "admin_or_advanced_gated": True,
            "timeout_or_row_limit": True,
            "first_paint_invocation": False,
            "route_invocation": False,
            "passed": True,
        },
        {
            "section": "Workload Operations",
            "workflow": "Query Investigation",
            "label": "Query Search live search",
            "stable_key": "query_search_live_search",
            "owner_skipped": True,
            "skip_reason": "covered by Query Search explicit action contract",
            "explicit_click_required": True,
            "admin_or_advanced_gated": True,
            "timeout_or_row_limit": True,
            "first_paint_invocation": False,
            "route_invocation": False,
            "passed": True,
        },
    ]
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
        "artifacts/full_app_validation/live_feature_results.json": live_rows,
        "artifacts/full_app_validation/control_inventory.json": control_rows,
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

    def test_missing_required_settings_control_fails(self):
        from tools.contracts.settings_live_feature_gauntlet import build_settings_live_feature_results

        payload = _passing_payload()
        payload["artifacts/full_app_validation/control_inventory.json"] = [
            row for row in payload["artifacts/full_app_validation/control_inventory.json"]
            if row["key"] != "_ai_credit_price_input"
        ]

        results = build_settings_live_feature_results(payload)

        self.assertFalse(results["passed"])
        self.assertTrue(any(row.get("control_requirement") == "ai_credit_price" for row in results["failures"]))

    def test_missing_live_feature_inventory_fails(self):
        from tools.contracts.settings_live_feature_gauntlet import build_settings_live_feature_results

        payload = _passing_payload()
        payload["artifacts/full_app_validation/live_feature_results.json"] = [
            row for row in payload["artifacts/full_app_validation/live_feature_results.json"]
            if row["stable_key"] != "settings_query_history_proof"
        ]

        results = build_settings_live_feature_results(payload)

        self.assertFalse(results["passed"])
        self.assertTrue(any(row.get("feature_requirement") == "query_history_proof" for row in results["failures"]))

    def test_missing_settings_render_fails(self):
        from tools.contracts.settings_live_feature_gauntlet import build_settings_live_feature_results

        payload = _passing_payload()
        payload["artifacts/full_app_validation/rendered_fragments.json"] = [
            row for row in payload["artifacts/full_app_validation/rendered_fragments.json"]
            if row["section"] != "Settings"
        ]

        results = build_settings_live_feature_results(payload)

        self.assertFalse(results["passed"])
        self.assertTrue(any(row.get("failure_reason") == "settings_default_render_missing" for row in results["failures"]))


if __name__ == "__main__":
    unittest.main()
