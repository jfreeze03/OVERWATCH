from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


class CostContractOverviewTests(unittest.TestCase):
    def test_cost_contract_reexports_moved_overview_helpers(self):
        from sections import cost_contract
        from sections import cost_contract_overview

        self.assertIs(cost_contract._cost_splash_status, cost_contract_overview._cost_splash_status)
        self.assertIs(cost_contract._cost_splash_next_move, cost_contract_overview._cost_splash_next_move)
        self.assertIs(cost_contract._cost_executive_decision_stack, cost_contract_overview._cost_executive_decision_stack)

    def test_cost_splash_status_labels_remain_stable(self):
        from sections.cost_contract_overview import _cost_splash_status

        attention = _cost_splash_status({
            "delta_pct": 25,
            "top_warehouse": "COMPUTE_WH",
            "top_warehouse_delta_spend": 125.0,
        })
        improving = _cost_splash_status({"delta_pct": -12})
        stable = _cost_splash_status({"delta_pct": 3, "top_warehouse": "LOAD_WH"})

        self.assertEqual(attention[0], "Attention")
        self.assertIn("COMPUTE_WH", attention[2])
        self.assertEqual(improving[0], "Improving")
        self.assertEqual(stable[0], "Stable")

    def test_cost_executive_decision_stack_on_demand_zero_state(self):
        from sections.cost_contract_overview import _cost_executive_decision_stack

        frame = _cost_executive_decision_stack(
            {
                "spend_delta": 0,
                "projected_30d_spend": 0,
                "spend": 0,
                "cortex_spend": 0,
            },
            {"open_actions": 0, "estimated_savings": 0},
        )

        self.assertEqual(len(frame), 4)
        self.assertTrue(frame["SIGNAL"].eq("On demand").all())
        self.assertEqual(frame["ROUTE"].tolist(), [
            "Cost Explorer > Warehouse",
            "Burn Rate & Forecast",
            "Cortex AI",
            "Cost Recommendations",
        ])


if __name__ == "__main__":
    unittest.main()
