from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


class CostContractOverviewPanelTests(unittest.TestCase):
    def test_cost_contract_reexports_moved_overview_panel_helpers(self):
        from sections import cost_contract
        from sections import cost_contract_overview_panels

        self.assertIs(cost_contract._render_cost_splash_narrative, cost_contract_overview_panels._render_cost_splash_narrative)
        self.assertIs(cost_contract._render_cost_splash_next_move, cost_contract_overview_panels._render_cost_splash_next_move)
        self.assertIs(cost_contract._render_cost_executive_decision_stack, cost_contract_overview_panels._render_cost_executive_decision_stack)
        self.assertIs(cost_contract._build_cost_period_explanation, cost_contract_overview_panels._build_cost_period_explanation)
        self.assertIs(cost_contract._render_cost_run_rate_lens, cost_contract_overview_panels._render_cost_run_rate_lens)
        self.assertIs(cost_contract._render_metric_items, cost_contract_overview_panels._render_metric_items)
        self.assertIs(cost_contract._cost_snapshot_action_summary, cost_contract_overview_panels._cost_snapshot_action_summary)

    def test_cost_period_explanation_preserves_questions_and_dollar_text(self):
        from sections.cost_contract_overview_panels import _build_cost_period_explanation

        cockpit = pd.DataFrame([{
            "CURRENT_CREDITS": 120.0,
            "PRIOR_CREDITS": 100.0,
            "TOP_INCREASE_WAREHOUSE": "COMPUTE_WH",
            "TOP_INCREASE_CREDITS": 12.5,
        }])
        run_rate = pd.DataFrame([{
            "PCT_VS_30D_AVG": 25.0,
            "YOY_7D_PCT": None,
            "YOY_STATE": "No YOY baseline",
        }])
        queue = pd.DataFrame([{
            "STATUS": "New",
            "EST_MONTHLY_SAVINGS": 300.0,
        }])

        frame = _build_cost_period_explanation(cockpit, run_rate, queue, credit_price=4.0)

        self.assertEqual(frame["QUESTION"].tolist(), [
            "Did the bill move?",
            "What likely changed?",
            "Is this a short spike or trend?",
            "Is there already a fix path?",
        ])
        self.assertEqual(frame.loc[0, "DOLLAR_IMPACT"], "$+80")
        self.assertIn("COMPUTE_WH", frame.loc[1, "ANSWER"])
        self.assertIn("Open Cost & Contract recommendations", frame.loc[1, "NEXT_ACTION"])
        self.assertIn("No baseline", frame.loc[2, "ANSWER"])
        self.assertEqual(frame.loc[3, "DOLLAR_IMPACT"], "$300/mo")

    def test_run_rate_formatting_preserves_no_baseline_and_percent_labels(self):
        from sections import cost_contract_overview_panels

        self.assertEqual(cost_contract_overview_panels._format_optional_pct(None), "No baseline")
        self.assertEqual(cost_contract_overview_panels._format_optional_pct(None, "Flat"), "Flat")
        self.assertEqual(cost_contract_overview_panels._format_optional_pct(12.345), "+12.3%")
        self.assertEqual(cost_contract_overview_panels._format_optional_pct(-4.44), "-4.4%")

        run_rate = pd.DataFrame([{
            "AVG_DAILY_7D": 3.0,
            "AVG_DAILY_30D": 2.0,
            "CREDITS_7D": 21.0,
            "PROJECTED_30D_FROM_7D": 90.0,
            "PCT_VS_30D_AVG": None,
            "RUN_RATE_STATE": "No baseline",
            "YOY_STATE": "No YOY baseline",
        }])

        with (
            patch.object(cost_contract_overview_panels.st, "markdown"),
            patch.object(cost_contract_overview_panels, "_render_metric_items") as metric_items,
            patch.object(cost_contract_overview_panels, "defer_source_note"),
        ):
            cost_contract_overview_panels._render_cost_run_rate_lens(run_rate, credit_price=4.0)

        metrics = metric_items.call_args.args[0]
        self.assertEqual(metrics[0]["delta"], "No baseline vs 30d")
        self.assertEqual(metrics[1]["value"], "$84")
        self.assertEqual(metrics[2]["value"], "$360/30d")


if __name__ == "__main__":
    unittest.main()
