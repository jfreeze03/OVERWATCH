from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections import cost_contract, cost_contract_dataframes  # noqa: E402
from sections.cost_contract_dataframes import (  # noqa: E402
    _cost_spend_trend_rows,
    _cost_warehouse_ranking_rows,
    _service_lens_movement_rows,
    _short_label,
    _top_loaded_cost_driver,
)


class CostContractDataframeTests(unittest.TestCase):
    def test_cost_contract_reexports_dataframe_helpers(self):
        self.assertIs(cost_contract._short_label, cost_contract_dataframes._short_label)
        self.assertIs(cost_contract._cost_spend_trend_rows, cost_contract_dataframes._cost_spend_trend_rows)
        self.assertIs(cost_contract._cost_warehouse_ranking_rows, cost_contract_dataframes._cost_warehouse_ranking_rows)
        self.assertIs(cost_contract._service_lens_movement_rows, cost_contract_dataframes._service_lens_movement_rows)

    def test_short_label_trims_long_text(self):
        self.assertEqual(_short_label("  WAREHOUSE  ", 20), "WAREHOUSE")
        self.assertEqual(_short_label("LONG_WAREHOUSE_NAME_FOR_COST_REVIEW", 14), "LONG_WAREHO...")

    def test_cost_spend_trend_rows_sorts_dates_and_converts_credits(self):
        rows = _cost_spend_trend_rows(
            pd.DataFrame({
                "USAGE_DATE": ["2026-06-03", "not-a-date", "2026-06-01"],
                "DAILY_CREDITS": ["2", "99", "1"],
            }),
            4.0,
        )

        self.assertEqual([day.strftime("%Y-%m-%d") for day in rows["USAGE_DATE"]], ["2026-06-01", "2026-06-03"])
        self.assertEqual(rows["SPEND_USD"].tolist(), [4.0, 8.0])
        self.assertEqual(rows["ROLLING_SPEND_USD"].tolist(), [4.0, 6.0])

    def test_cost_spend_trend_rows_preserves_explicit_daily_spend(self):
        rows = _cost_spend_trend_rows(
            pd.DataFrame({
                "USAGE_DATE": ["2026-06-01"],
                "DAILY_CREDITS": [100],
                "DAILY_SPEND_USD": ["7.25"],
            }),
            4.0,
        )

        self.assertEqual(rows["SPEND_USD"].tolist(), [7.25])

    def test_warehouse_ranking_rows_calculates_spend_and_labels(self):
        rows = _cost_warehouse_ranking_rows(
            pd.DataFrame({
                "WAREHOUSE_NAME": ["A_WH", "B_WH", "C_WH"],
                "CURRENT_CREDITS": [10, 12, "bad"],
                "PRIOR_CREDITS": [6, 15, 1],
                "CREDIT_DELTA": [4, -3, -1],
            }),
            5.0,
            limit=2,
        )

        self.assertEqual(rows["WAREHOUSE_NAME"].tolist(), ["B_WH", "A_WH"])
        self.assertEqual(rows["CURRENT_SPEND_USD"].tolist(), [60.0, 50.0])
        self.assertEqual(rows["DELTA_SPEND_LABEL"].tolist(), ["-$15", "+$20"])

    def test_service_lens_movement_rows_uses_spend_then_credit_fallback(self):
        rows = _service_lens_movement_rows(
            pd.DataFrame({
                "SERVICE_CATEGORY": ["AI", "Cloud"],
                "SERVICE_TYPE": ["CORTEX", "CLOUD_SERVICES"],
                "CREDITS_BILLED": [5, 0],
                "CREDITS_BILLED_PRIOR": [1, 0],
                "ESTIMATED_COST_USD": [0, 10],
                "PRIOR_ESTIMATED_COST_USD": [0, 30],
                "COST_DELTA_USD": [0, -20],
                "CREDIT_DELTA": [0, 0],
            }),
            4.0,
            limit=2,
        )

        self.assertEqual(rows["SERVICE_TYPE"].tolist(), ["CLOUD_SERVICES", "CORTEX"])
        self.assertEqual(rows["COST_DELTA_USD"].tolist(), [-20, 16])
        self.assertEqual(rows["DELTA_LABEL"].tolist(), ["-$20", "+$16"])

    def test_top_loaded_cost_driver_selects_case_insensitive_columns(self):
        driver = _top_loaded_cost_driver(
            pd.DataFrame({
                "company": ["ALFA", "Trexis", "ALFA", ""],
                "total_credits": [2, 5, 4, 100],
            }),
            ["COMPANY"],
            credit_price=4.0,
        )

        self.assertEqual(driver["dimension"], "company")
        self.assertEqual(driver["metric"], "total_credits")
        self.assertEqual(driver["entity"], "ALFA")
        self.assertEqual(driver["value"], 6.0)
        self.assertEqual(driver["value_usd"], 24.0)
        self.assertEqual(driver["rows"], 2)


if __name__ == "__main__":
    unittest.main()
