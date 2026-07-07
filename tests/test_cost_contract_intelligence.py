from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


class CostContractIntelligenceTests(unittest.TestCase):
    def test_cost_contract_reexports_intelligence_and_panel_helpers(self):
        from sections import cost_contract
        from sections import cost_contract_intelligence
        from sections import cost_contract_panels

        self.assertIs(cost_contract._build_cost_source_health_board, cost_contract_intelligence._build_cost_source_health_board)
        self.assertIs(cost_contract._build_service_cost_lens_summary, cost_contract_intelligence._build_service_cost_lens_summary)
        self.assertIs(cost_contract._build_cost_control_coverage_board, cost_contract_intelligence._build_cost_control_coverage_board)
        self.assertIs(cost_contract._build_cost_allocation_trust_board, cost_contract_intelligence._build_cost_allocation_trust_board)
        self.assertIs(cost_contract._build_cost_drilldown_command_map, cost_contract_intelligence._build_cost_drilldown_command_map)
        self.assertIs(cost_contract._build_cost_decomposition_board, cost_contract_intelligence._build_cost_decomposition_board)
        self.assertIs(cost_contract._build_cost_spike_root_cause_board, cost_contract_intelligence._build_cost_spike_root_cause_board)
        self.assertIs(cost_contract._build_change_cost_correlation_board, cost_contract_intelligence._build_change_cost_correlation_board)
        self.assertIs(cost_contract._render_cost_source_health, cost_contract_panels._render_cost_source_health)
        self.assertIs(cost_contract._render_cost_decomposition_board, cost_contract_panels._render_cost_decomposition_board)

    def test_source_health_state_contract_and_board_ranking(self):
        from sections.cost_contract_intelligence import _build_cost_source_health_board, _source_state

        self.assertEqual(_source_state(pd.DataFrame([{"A": 1}]), ""), "Ready")
        self.assertEqual(_source_state(pd.DataFrame(), "permission denied"), "Unavailable")
        self.assertEqual(_source_state(pd.DataFrame(), "", empty_state="Load Needed"), "Load Needed")
        self.assertEqual(_source_state(pd.DataFrame(), "", empty_state="Explicit action"), "Explicit action")
        self.assertEqual(_source_state(pd.DataFrame(), ""), "No Rows")

        summary, board = _build_cost_source_health_board(
            cockpit=pd.DataFrame(),
            run_rate=pd.DataFrame(),
            queue=pd.DataFrame(),
            attribution=pd.DataFrame(),
            service_lens=pd.DataFrame([{
                "SERVICE_CATEGORY": "AI / Cortex",
                "SERVICE_TYPE": "CORTEX",
                "CREDITS_BILLED": 2.0,
                "CREDIT_DELTA": 1.0,
            }]),
            state={
                "cost_contract_cockpit_error": "blocked",
                "cost_contract_service_lens_source": "Official service lens",
            },
        )

        self.assertEqual(board.iloc[0]["STATE"], "Unavailable")
        self.assertIn("Load Needed", set(board["STATE"]))
        self.assertIn("No Rows", set(board["STATE"]))
        self.assertIn("Ready", set(board["STATE"]))
        self.assertEqual(summary["unavailable"], 1)

    def test_service_lens_summary_separates_service_categories(self):
        from sections.cost_contract_intelligence import _build_service_cost_lens_summary

        frame = pd.DataFrame([
            {
                "SERVICE_CATEGORY": "Warehouse",
                "SERVICE_TYPE": "WAREHOUSE_METERING",
                "CREDITS_BILLED": 10.0,
                "CREDIT_DELTA": 0.2,
            },
            {
                "SERVICE_CATEGORY": "AI / Cortex",
                "SERVICE_TYPE": "CORTEX",
                "CREDITS_BILLED": 4.0,
                "CREDIT_DELTA": 3.5,
            },
            {
                "SERVICE_CATEGORY": "Serverless / Managed Compute",
                "SERVICE_TYPE": "SERVERLESS_TASK",
                "CREDITS_BILLED": 2.0,
                "CREDIT_DELTA": -1.0,
            },
        ])

        summary = _build_service_cost_lens_summary(frame)

        self.assertEqual(summary["total_credits"], 16.0)
        self.assertEqual(summary["non_warehouse_credits"], 6.0)
        self.assertEqual(summary["ai_credits"], 4.0)
        self.assertEqual(summary["serverless_credits"], 2.0)
        self.assertEqual(summary["top_service"], "WAREHOUSE_METERING")
        self.assertEqual(summary["top_moving_service"], "CORTEX")
        self.assertEqual(summary["categories"], 3)

    def test_trust_drilldown_and_decomposition_boards_preserve_columns_and_states(self):
        from sections.cost_contract_intelligence import (
            _build_cost_allocation_trust_board,
            _build_cost_control_coverage_board,
            _build_cost_decomposition_board,
            _build_cost_drilldown_command_map,
        )

        cockpit = pd.DataFrame([{
            "CURRENT_CREDITS": 100.0,
            "PRIOR_CREDITS": 80.0,
            "TOP_INCREASE_WAREHOUSE": "WH_ALFA_OVERWATCH",
            "TOP_INCREASE_CREDITS": 12.5,
        }])
        run_rate = pd.DataFrame([{
            "AVG_DAILY_7D": 14.0,
            "YOY_7D_PCT": 8.0,
            "YOY_30D_PCT": 5.0,
        }])
        queue = pd.DataFrame([{
            "CATEGORY": "Cost Control",
            "STATUS": "New",
            "ROUTE_SOURCE": "warehouse_scope",
            "VERIFICATION_STATUS": "Pending",
        }])
        state = {
            "df_cost_explorer_detail": pd.DataFrame([{
                "ROLE_NAME": "ETL_ROLE",
                "USER_NAME": "ETL_USER",
                "DEPARTMENT": "DATA",
                "ENVIRONMENT_ROLLUP": "PROD",
                "DATABASE_NAME": "",
                "ALLOCATION_CONFIDENCE": "Allocated/Estimated",
            }]),
            "df_chargeback": pd.DataFrame([{
                "COMPANY": "ALFA",
                "ENVIRONMENT": "PROD",
                "DATABASE_NAME": "ALFA_EDW",
                "ALLOCATION_CONFIDENCE": "Allocated/Estimated",
            }]),
        }

        coverage_summary, coverage = _build_cost_control_coverage_board(
            cockpit=cockpit,
            run_rate=run_rate,
            queue=queue,
            state=state,
        )
        trust_summary, trust = _build_cost_allocation_trust_board(
            cockpit=cockpit,
            run_rate=run_rate,
            queue=queue,
            state=state,
        )
        drill_summary, drill = _build_cost_drilldown_command_map(
            cockpit=cockpit,
            run_rate=run_rate,
            queue=queue,
            state=state,
        )
        decomposition_summary, decomposition = _build_cost_decomposition_board(
            cockpit=cockpit,
            run_rate=run_rate,
            queue=queue,
            state=state,
        )

        self.assertTrue({"STATE", "CONTROL", "EVIDENCE", "NEXT_ACTION", "OWNER"}.issubset(coverage.columns))
        self.assertTrue({"TRUST_STATE", "CONTROL", "EVIDENCE", "NEXT_ACTION", "OWNER"}.issubset(trust.columns))
        self.assertTrue({"COMMAND_PRIORITY", "DRILLDOWN", "STATE", "TRUST", "WORKFLOW"}.issubset(drill.columns))
        self.assertTrue({"STATUS", "DRIVER", "TRUST", "EVIDENCE", "NEXT_ACTION"}.issubset(decomposition.columns))
        self.assertGreaterEqual(coverage_summary["ready"], 1)
        self.assertGreaterEqual(trust_summary["estimated"], 1)
        self.assertIn("Ready", set(drill["STATE"]))
        self.assertIn("Review", set(drill["STATE"]))
        self.assertEqual(drill_summary["estimated"], 4)
        self.assertIn("Load Needed", set(_build_cost_control_coverage_board(
            cockpit=pd.DataFrame(),
            run_rate=pd.DataFrame(),
            queue=pd.DataFrame(),
            state={},
        )[1]["STATE"]))
        self.assertEqual(decomposition_summary["ready"], 6)


if __name__ == "__main__":
    unittest.main()
