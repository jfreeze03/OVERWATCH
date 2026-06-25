from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


class CortexFirstClassSignalTests(unittest.TestCase):
    def test_cortex_signal_module_has_no_query_or_session_loader_calls(self):
        source = (APP_ROOT / "sections" / "cortex_signals.py").read_text(encoding="utf-8")

        self.assertNotRegex(source, r"\brun_query(?:_or_raise)?\s*\(")
        self.assertNotRegex(source, r"\bget_session(?:_for_action)?\s*\(")
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", source)

    def test_cortex_signal_builds_graceful_unavailable_state(self):
        from sections.cortex_signals import build_cortex_signal

        signal = build_cortex_signal({}, state={}, days=7)

        self.assertEqual(signal["spend_label"], "No Cortex telemetry available")
        self.assertEqual(signal["forecast_label"], "Predictive alert data not loaded")
        self.assertEqual(signal["predictive_alert_label"], "Not loaded")
        self.assertEqual(signal["top_driver"], "Not loaded")

    def test_cortex_signal_uses_loaded_summary_and_session_context(self):
        from sections.cortex_signals import build_cortex_signal

        state = {
            "cortex_control_summary": pd.DataFrame(
                [{
                    "PROJECTED_30D_COST": 4600.0,
                    "TOTAL_CREDITS": 42.0,
                    "TOTAL_REQUESTS": 900,
                }]
            ),
            "cortex_control_exceptions": pd.DataFrame([{"SIGNAL": "Forecast breach"}, {"SIGNAL": "Heavy user"}]),
        }
        signal = build_cortex_signal(
            {
                "cortex_spend": 920.0,
                "spend": 4600.0,
                "top_cortex_user": "ANALYST_1",
                "run_rate_state": "Accelerating",
            },
            state=state,
            days=7,
        )

        self.assertEqual(signal["spend_label"], "$920.00")
        self.assertEqual(signal["forecast_label"], "$4,600")
        self.assertEqual(signal["predictive_alert_label"], "2")
        self.assertEqual(signal["top_driver"], "ANALYST_1")
        self.assertEqual(signal["percent_of_total"], "20.0%")

    def test_executive_landing_surfaces_cortex_first_class_labels(self):
        source = (APP_ROOT / "sections" / "executive_landing_overview_view.py").read_text(encoding="utf-8")

        self.assertIn("Cortex AI executive cost lane", source)
        self.assertIn("Cortex AI Spend", (APP_ROOT / "sections" / "cortex_signals.py").read_text(encoding="utf-8"))
        self.assertIn("Review Cortex AI Cost & Predictive Alerts", source)
        self.assertNotIn("Show Workflow Shortcuts", source)
        self.assertNotIn("Show Summary Detail", source)

    def test_decision_rows_include_cortex_ai_cost_risk(self):
        from sections.executive_landing_models import _decision_rows

        rows = _decision_rows(
            {
                "critical_high_alerts": 0,
                "top_cost_driver": "Account spend",
                "cost_delta": 12.5,
                "advisor_findings": 0,
                "advisor_high_findings": 0,
                "advisor_estimated_monthly_savings_usd": 0,
                "open_actions": 0,
                "high_actions": 0,
                "migration_blockers": 0,
                "cortex_spend_usd": 1200.0,
                "cortex_predictive_alerts": 3,
            }
        )

        self.assertIn("Cortex AI cost risk", set(rows["DECISION_AREA"]))
        row = rows.loc[rows["DECISION_AREA"].eq("Cortex AI cost risk")].iloc[0]
        self.assertIn("$1,200", row["SIGNAL"])
        self.assertIn("3 predictive alert", row["SIGNAL"])

    def test_cost_contract_surfaces_cortex_cost_lane_and_cta(self):
        source = (APP_ROOT / "sections" / "cost_contract_overview_floor.py").read_text(encoding="utf-8")

        self.assertIn("Cortex AI cost lane", source)
        self.assertIn("Open Cortex Cost Drivers", source)
        self.assertIn("build_cortex_signal", source)
        self.assertIn("_cost_splash_summary", source)

    def test_alert_center_surfaces_cortex_predictive_alert_family(self):
        from sections.alert_center import _alert_command_lanes

        cold_lanes = _alert_command_lanes(
            active_view="Active Alerts",
            required_sources={"ALERTS"},
            loaded=False,
        )
        self.assertIn("Cortex predictive alerts", {lane["label"] for lane in cold_lanes})

        loaded_lanes = _alert_command_lanes(
            active_view="Active Alerts",
            required_sources={"ALERTS"},
            alerts=pd.DataFrame(
                [
                    {
                        "STATUS": "New",
                        "SEVERITY": "High",
                        "CATEGORY": "COST",
                        "ALERT_TYPE": "Cortex Forecast",
                        "SIGNAL": "Predictive Cortex spend anomaly",
                    }
                ]
            ),
            loaded=True,
        )
        cortex_lane = next(lane for lane in loaded_lanes if lane["label"] == "Cortex predictive alerts")
        self.assertEqual(cortex_lane["value"], "1")
        self.assertEqual(cortex_lane["state"], "AI cost")

    def test_command_deck_contracts_include_cortex_routes(self):
        from sections.command_deck_contracts import get_command_deck_contract

        executive_labels = {action.label for action in get_command_deck_contract("Executive Landing").route_actions}
        cost_labels = {action.label for action in get_command_deck_contract("Cost & Contract").route_actions}
        alert_labels = {action.label for action in get_command_deck_contract("Alert Center").route_actions}

        self.assertIn("Cortex AI Cost", executive_labels)
        self.assertIn("Review Cortex AI Costs", cost_labels)
        self.assertIn("Cortex Predictive Alerts", alert_labels)

    def test_cortex_monitor_top_summary_is_visible_before_detail_workflows(self):
        source = (APP_ROOT / "sections" / "cortex_monitor.py").read_text(encoding="utf-8")

        self.assertIn("Cortex AI executive command lane", source)
        self.assertIn("Review Cortex Predictive Alerts", source)
        self.assertLess(source.index("Cortex AI executive command lane"), source.index("render_workflow_selector("))


if __name__ == "__main__":
    unittest.main()
