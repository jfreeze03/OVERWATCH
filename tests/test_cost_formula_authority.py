from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class CostFormulaAuthorityTests(unittest.TestCase):
    def test_numeric_normalization_covers_cost_db_columns(self):
        from utils.cost_formula_authority import NUMERIC_NORMALIZATION_COLUMNS, normalize_numeric_columns

        frame = pd.DataFrame(
            {
                "CREDITS_USED": ["1.25"],
                "CREDITS_USED_COMPUTE": ["2"],
                "CREDITS_USED_CLOUD_SERVICES": ["0.5"],
                "TOTAL_CREDITS": ["3.5"],
                "COMPUTE_CREDITS": ["2"],
                "CLOUD_SERVICES_CREDITS": ["0.5"],
                "CREDITS_BILLED": ["4"],
                "CREDITS": ["4"],
                "COST": ["14.72"],
                "SERVERLESS_CREDITS": ["0.3"],
                "TOTAL_SERVERLESS_CREDITS": ["0.6"],
                "AVG_CREDITS": ["1.2"],
                "INPUT_CREDITS": ["0.1"],
                "OUTPUT_CREDITS": ["0.2"],
                "TOKENS": ["1000"],
                "REQUEST_COUNT": ["7"],
            }
        )

        normalized = normalize_numeric_columns(frame)

        for column in NUMERIC_NORMALIZATION_COLUMNS:
            self.assertIn(column, normalized.columns)
            self.assertEqual(normalized[column].dtype.kind, "f")

    def test_credit_conversion_uses_single_price_source(self):
        from utils.cost_formula_authority import credits_to_usd

        self.assertEqual(credits_to_usd(10, 3.68), 36.8)
        self.assertEqual(credits_to_usd(2.5, 4), 10.0)

    def test_warehouse_bridge_matches_cost_db_formula(self):
        from utils.cost_formula_authority import warehouse_bridge_credits

        frame = pd.DataFrame(
            {
                "WAREHOUSE_ID": [1, 0, 2, None],
                "WAREHOUSE_NAME": ["WH_ALFA_OVERWATCH", "PSEUDO", "", "NO_ID"],
                "CREDITS_USED_COMPUTE": ["2.0", "100", "50", "70"],
                "CREDITS_USED_CLOUD_SERVICES": ["0.5", "10", "5", "7"],
            }
        )

        self.assertEqual(warehouse_bridge_credits(frame), 2.5)

    def test_service_other_bridge_and_signed_delta_are_separate(self):
        from utils.cost_formula_authority import billing_bridge_delta_credits, service_other_bridge_credits

        self.assertEqual(service_other_bridge_credits(20, 12), 8)
        self.assertEqual(service_other_bridge_credits(5, 12), 0)
        self.assertEqual(billing_bridge_delta_credits(20, 12), 8)
        self.assertEqual(billing_bridge_delta_credits(5, 12), -7)

    def test_choose_credit_column_uses_authority_order(self):
        from utils.cost_formula_authority import ACCOUNT_CREDIT_COLUMN_ORDER, WAREHOUSE_CREDIT_COLUMN_ORDER, choose_credit_column

        account = pd.DataFrame({"DAILY_CREDITS": ["3.5"], "TOTAL_CREDITS": ["99"]})
        account_choice = choose_credit_column(account, ACCOUNT_CREDIT_COLUMN_ORDER)
        self.assertTrue(account_choice.passed)
        self.assertEqual(account_choice.selected_column, "DAILY_CREDITS")
        self.assertEqual(account_choice.values.tolist(), [3.5])

        warehouse = pd.DataFrame({"CREDITS_USED_COMPUTE": ["2"], "CREDITS_USED_CLOUD_SERVICES": ["0.5"]})
        warehouse_choice = choose_credit_column(warehouse, WAREHOUSE_CREDIT_COLUMN_ORDER)
        self.assertTrue(warehouse_choice.passed)
        self.assertEqual(warehouse_choice.selected_column, "CREDITS_USED_COMPUTE + CREDITS_USED_CLOUD_SERVICES")
        self.assertEqual(warehouse_choice.values.tolist(), [2.5])

    def test_choose_credit_column_reports_missing_source(self):
        from utils.cost_formula_authority import ACCOUNT_CREDIT_COLUMN_ORDER, choose_credit_column

        choice = choose_credit_column(pd.DataFrame({"NOT_CREDITS": [1]}), ACCOUNT_CREDIT_COLUMN_ORDER)
        self.assertFalse(choice.passed)
        self.assertIn("No acceptable credit column", choice.reason)

    def test_cortex_service_mask_is_allowlisted(self):
        from utils.cost_formula_authority import cortex_service_mask

        frame = pd.DataFrame({"SERVICE_TYPE": ["WAREHOUSE_METERING", "CORTEX_AI", "AI_SERVICES", "MAINTENANCE_AI_HELPER"]})
        self.assertEqual(cortex_service_mask(frame).tolist(), [False, True, True, False])

    def test_formula_authority_results_have_source_url(self):
        from utils.cost_formula_authority import COST_DB_SOURCE_URL, cost_db_formula_mapping, evaluate_formula_gaps

        rows = cost_db_formula_mapping()
        self.assertTrue(all(row["cost_db_source_url"] == COST_DB_SOURCE_URL for row in rows))
        self.assertTrue(all(row["overwatch_formula"] for row in rows))
        self.assertTrue(all(row["launch_gate"] == "cost_db_formula_authority" for row in rows))
        self.assertTrue(evaluate_formula_gaps()["passed"])


if __name__ == "__main__":
    unittest.main()
