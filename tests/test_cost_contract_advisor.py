from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


class CostContractAdvisorTests(unittest.TestCase):
    def test_cost_contract_reexports_moved_advisor_helpers(self):
        from sections import cost_contract
        from sections import cost_contract_advisor

        self.assertIs(cost_contract._cost_action_mask, cost_contract_advisor._cost_action_mask)
        self.assertIs(cost_contract._build_cost_closure_analytics, cost_contract_advisor._build_cost_closure_analytics)
        self.assertIs(cost_contract._build_cost_advisor_board, cost_contract_advisor._build_cost_advisor_board)
        self.assertIs(cost_contract._open_cost_action_frame, cost_contract_advisor._open_cost_action_frame)

    def test_cost_action_mask_selects_cost_chargeback_and_cost_contract_source(self):
        from sections.cost_contract_advisor import _cost_action_mask

        rows = pd.DataFrame({
            "CATEGORY": ["Cost Spike", "Chargeback Gap", "Security", "Pipeline"],
            "SOURCE": ["Other", "Other", "Cost & Contract", "Workload Operations"],
        })

        self.assertEqual(_cost_action_mask(rows).tolist(), [True, True, True, False])

    def test_closure_analytics_classifies_cost_action_states(self):
        from sections.cost_contract_advisor import _build_cost_closure_analytics

        queue = pd.DataFrame({
            "CATEGORY": ["Cost", "Cost", "Cost", "Cost", "Cost", "Cost", "Chargeback"],
            "SOURCE": ["Cost & Contract"] * 7,
            "STATUS": ["New", "Fixed", "Ignored", "New", "Fixed", "Fixed", "New"],
            "REVIEW_STATUS": [
                "Approved",
                "Approved",
                "",
                "Requested",
                "Approved",
                "Approved",
                "Approved",
            ],
            "VERIFICATION_STATUS": ["", "Pending", "", "", "VERIFIED_SAVED", "VERIFIED_NO_CHANGE", ""],
            "VERIFICATION_RESULT": ["", "", "", "", "lower", "no change", ""],
            "BASELINE_VALUE": [0, 0, 0, 0, 10, 10, 0],
            "CURRENT_VALUE": [0, 0, 0, 0, 8, 10, 0],
            "MEASURED_DELTA": [0, 0, 0, 0, -2, 0, 0],
            "EST_MONTHLY_SAVINGS": [100, 50, 20, 25, 75, 0, 10],
            "RECOVERY_SLA_STATE": ["", "", "", "", "", "", "CHARGEBACK EVIDENCE PENDING"],
        })

        summary, detail = _build_cost_closure_analytics(queue, credit_price=3.0)

        self.assertEqual(summary["cost_actions"], 7)
        self.assertEqual(summary["open_actions"], 3)
        self.assertEqual(summary["approval_pending_actions"], 1)
        self.assertEqual(summary["fixed_without_verification"], 1)
        self.assertEqual(summary["verified_savings_actions"], 1)
        self.assertEqual(summary["verified_no_change_actions"], 1)
        self.assertEqual(summary["blocked_estimated_monthly_savings"], 35.0)
        self.assertEqual(summary["verified_estimated_monthly_savings"], 75.0)
        self.assertEqual(summary["verified_period_delta_dollars"], 6.0)
        self.assertEqual(summary["audit_ready_pct"], 66.7)
        self.assertEqual(
            detail["CLOSURE_STATE"].tolist(),
            [
                "Open cost action",
                "Fixed, awaiting measurement",
                "Ignored / not claimed",
                "Review pending",
                "Measured improvement",
                "Measured no improvement",
                "Chargeback telemetry pending",
            ],
        )

    def test_advisor_priority_and_action_mapping_stay_stable(self):
        from sections.cost_contract_advisor import _cost_advisor_action_for, _cost_advisor_priority

        self.assertEqual(_cost_advisor_priority(1000), "High")
        self.assertEqual(_cost_advisor_priority(10, finding_type="Remote spill detected"), "High")
        self.assertEqual(_cost_advisor_priority(250), "Medium")
        self.assertEqual(_cost_advisor_priority(12), "Low")
        self.assertEqual(
            _cost_advisor_action_for("Warehouse pressure"),
            ("Investigate pressure before capacity change", "Cost Explorer"),
        )
        self.assertEqual(
            _cost_advisor_action_for("Something else"),
            ("Investigate cost signal", "Cost Recommendations"),
        )

    def test_decorated_advisor_board_keeps_action_metric_and_execution_columns(self):
        from sections.cost_contract_advisor import _decorate_cost_advisor_board

        board = pd.DataFrame({
            "CATEGORY": ["Warehouse right-size review", "Unknown category"],
            "ESTIMATE_TYPE": ["Conservative savings candidate", "Value at risk"],
            "EST_MONTHLY_SAVINGS_USD": [125.0, 0.0],
            "EST_MONTHLY_IMPACT_USD": [500.0, 75.0],
        })

        decorated = _decorate_cost_advisor_board(board)

        self.assertEqual(decorated.loc[0, "ACTION_TYPE"], "Review right-size or suspend policy")
        self.assertEqual(decorated.loc[0, "WORKFLOW_ROUTE"], "Cost Explorer")
        self.assertEqual(decorated.loc[0, "PRIMARY_METRIC"], "$125/mo savings")
        self.assertEqual(decorated.loc[0, "EXECUTION_MODE"], "Savings candidate")
        self.assertEqual(decorated.loc[1, "ACTION_TYPE"], "Investigate cost signal")
        self.assertEqual(decorated.loc[1, "WORKFLOW_ROUTE"], "Cost Recommendations")
        self.assertEqual(decorated.loc[1, "PRIMARY_METRIC"], "$75/mo value at risk")
        self.assertEqual(decorated.loc[1, "EXECUTION_MODE"], "Investigation")

    def test_cost_advisor_board_builds_decorated_failed_query_finding(self):
        from sections.cost_contract_advisor import _build_cost_advisor_board

        summary, board = _build_cost_advisor_board(
            efficiency_summary=pd.DataFrame({
                "FAILED_QUERY_WASTE_USD": [70.0],
                "FAILED_QUERIES": [2],
            }),
            warehouse_efficiency=None,
            clustering_cost=None,
            reconciliation=None,
            service_lens=None,
            credit_price=3.0,
            days=7,
        )

        self.assertEqual(summary["findings"], 1)
        self.assertEqual(summary["high"], 1)
        self.assertEqual(board.loc[0, "CATEGORY"], "Failed query waste")
        self.assertEqual(board.loc[0, "ACTION_TYPE"], "Fix failed workload")
        self.assertEqual(board.loc[0, "WORKFLOW_ROUTE"], "Waste Detection")
        self.assertIn("PRIMARY_METRIC", board.columns)
        self.assertIn("EXECUTION_MODE", board.columns)

    def test_warehouse_pressure_keeps_spill_and_queue_evidence(self):
        from sections.cost_contract_advisor import _build_cost_advisor_board

        summary, board = _build_cost_advisor_board(
            efficiency_summary=None,
            warehouse_efficiency=pd.DataFrame({
                "WAREHOUSE_NAME": ["WH_ALFA_OVERWATCH"],
                "COST_USD": [280.0],
                "QUEUE_SECONDS": [1250.0],
                "REMOTE_SPILL_GB": [14.5],
                "LOCAL_SPILL_GB": [32.0],
                "FAILED_QUERY_WASTE_USD": [0.0],
                "QUERY_COUNT": [44],
                "AVG_CACHE_PCT": [70.0],
            }),
            clustering_cost=None,
            reconciliation=None,
            service_lens=None,
            credit_price=3.0,
            days=7,
        )

        self.assertEqual(summary["findings"], 1)
        row = board.iloc[0]
        self.assertEqual(row["CATEGORY"], "Warehouse pressure")
        self.assertEqual(row["EST_MONTHLY_SAVINGS_USD"], 0.0)
        self.assertGreater(row["VALUE_AT_RISK_USD"], 0)
        self.assertEqual(row["QUEUE_PRESSURE_SECONDS"], 1250.0)
        self.assertGreater(row["REMOTE_SPILL_BYTES"], 0)
        self.assertGreater(row["LOCAL_SPILL_BYTES"], 0)
        self.assertEqual(row["SAVINGS_ESTIMATE_STATUS"], "pressure_evidence_no_savings_formula")
        self.assertIn("value at risk", row["PRIMARY_METRIC"])
        self.assertNotEqual(row["PRIMARY_METRIC"], "$0/mo savings")

    def test_value_at_risk_launch_artifact_carries_export_case_fields(self):
        from sections.cost_contract_advisor import cost_advisor_value_at_risk_results

        result = cost_advisor_value_at_risk_results()

        self.assertTrue(result["passed"], result)
        self.assertGreater(result["row_count"], 0)
        self.assertTrue(result["export_case_fields_present"])
        self.assertTrue(result["pressure_rows_render_value_at_risk"])
        self.assertFalse(result["pressure_rows_render_fake_zero_savings"])
        row = result["rows"][0]
        for field in result["required_export_case_fields"]:
            self.assertIn(field, row)
        self.assertGreater(row["VALUE_AT_RISK_USD"], 0)
        self.assertGreater(row["QUEUE_PRESSURE_SECONDS"], 0)


if __name__ == "__main__":
    unittest.main()
