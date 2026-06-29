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
                "COST": ["14.72"],
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
                "WAREHOUSE_NAME": ["COMPUTE_WH", "PSEUDO", "", "NO_ID"],
                "CREDITS_USED_COMPUTE": ["2.0", "100", "50", "70"],
                "CREDITS_USED_CLOUD_SERVICES": ["0.5", "10", "5", "7"],
            }
        )

        self.assertEqual(warehouse_bridge_credits(frame), 2.5)

    def test_service_other_bridge_never_negative(self):
        from utils.cost_formula_authority import service_other_bridge_credits

        self.assertEqual(service_other_bridge_credits(20, 12), 8)
        self.assertEqual(service_other_bridge_credits(5, 12), 0)

    def test_cortex_service_mask_is_canonical(self):
        from utils.cost_formula_authority import cortex_service_mask

        frame = pd.DataFrame({"SERVICE_TYPE": ["WAREHOUSE_METERING", "CORTEX_AI", "AI_SERVICES"]})
        self.assertEqual(cortex_service_mask(frame).tolist(), [False, True, True])

    def test_formula_authority_results_have_source_url(self):
        from utils.cost_formula_authority import COST_DB_SOURCE_URL, cost_db_formula_mapping, evaluate_formula_gaps

        rows = cost_db_formula_mapping()
        self.assertTrue(all(row["cost_db_source_url"] == COST_DB_SOURCE_URL for row in rows))
        self.assertTrue(evaluate_formula_gaps()["passed"])


if __name__ == "__main__":
    unittest.main()
