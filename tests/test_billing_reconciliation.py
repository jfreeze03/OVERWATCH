from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class BillingReconciliationTests(unittest.TestCase):
    def test_account_billing_sql_uses_completed_daily_history(self):
        from utils.billing_reconciliation import build_account_billing_reconciliation_sql

        sql = build_account_billing_reconciliation_sql(
            8,
            credit_price=3.68,
            start_date="2026-06-21",
            end_date="2026-06-28",
        ).upper()

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY", sql)
        self.assertIn("CREDITS_BILLED", sql)
        self.assertIn("CREDITS_USED", sql)
        self.assertIn("CREDITS_ADJUSTMENT_CLOUD_SERVICES", sql)
        self.assertIn("SERVICE_TYPE", sql)
        self.assertIn("USAGE_DATE < CURRENT_DATE()", sql)

    def test_account_total_is_not_warehouse_only(self):
        from utils.billing_reconciliation import summarize_billing_reconciliation

        account_rows = pd.DataFrame(
            {
                "USAGE_DATE": ["2026-06-21", "2026-06-22"],
                "SERVICE_TYPE": ["WAREHOUSE_METERING", "CORTEX_AI"],
                "CREDITS_BILLED": [10.0, 4.0],
                "CREDITS_USED": [9.0, 3.5],
                "CREDITS_USED_COMPUTE": [8.0, 0.0],
                "CREDITS_USED_CLOUD_SERVICES": [1.0, 0.1],
                "CREDITS_ADJUSTMENT_CLOUD_SERVICES": [-0.2, -0.1],
                "DAILY_SPEND_USD": [36.8, 14.72],
            }
        )
        warehouse_rows = pd.DataFrame({"WAREHOUSE_CREDITS": [6.0, 2.0]})

        summary = summarize_billing_reconciliation(account_rows, warehouse_rows, credit_price=3.68)

        self.assertEqual(summary["ACCOUNT_BILLED_CREDITS"], 14.0)
        self.assertEqual(summary["WAREHOUSE_CREDITS"], 8.0)
        self.assertEqual(summary["SERVICE_OTHER_CREDITS"], 6.0)
        self.assertEqual(summary["COMPUTE_CREDITS"], 8.0)
        self.assertEqual(summary["CLOUD_SERVICES_CREDITS"], 1.1)
        self.assertEqual(summary["CLOUD_SERVICES_ADJUSTMENT"], -0.3)
        self.assertEqual(summary["CORTEX_AI_CREDITS"], 4.0)
        self.assertEqual(summary["CORTEX_AI_COST_USD"], 14.72)
        self.assertEqual(summary["BILLING_WINDOW_START"], "2026-06-21")
        self.assertEqual(summary["BILLING_WINDOW_END"], "2026-06-22")
        self.assertTrue(summary["BILLING_WINDOW_COMPLETE"])
        self.assertFalse(summary["WAREHOUSE_BRIDGE_IS_PRIMARY_TOTAL"])
        self.assertEqual(summary["BILLING_RECONCILIATION_STATUS"], "passed")

    def test_daily_labels_do_not_expose_raw_objects(self):
        from utils.billing_reconciliation import daily_safe_billing_labels

        text = " ".join(daily_safe_billing_labels().values()).upper()
        for token in ("ACCOUNT_USAGE", "SELECT ", "JOIN ", "CALL ", "SP_", "MART_", "FACT_"):
            self.assertNotIn(token, text)
        self.assertIn("SNOWSIGHT", text)

    def test_contract_requires_packet_fields(self):
        from utils.billing_reconciliation import (
            BILLING_RECONCILIATION_PACKET_FIELDS,
            billing_reconciliation_contract_results,
            summarize_billing_reconciliation,
        )

        account_rows = pd.DataFrame({"USAGE_DATE": ["2026-06-21"], "CREDITS_BILLED": [2.0]})
        summary = summarize_billing_reconciliation(account_rows, pd.DataFrame({"WAREHOUSE_CREDITS": [1.0]}), credit_price=3.68)
        results = billing_reconciliation_contract_results(summary)
        self.assertTrue(results["passed"], results)
        for field in BILLING_RECONCILIATION_PACKET_FIELDS:
            self.assertIn(field, summary)

    def test_contract_rejects_cortex_spend_with_zero_account_total(self):
        from utils.billing_reconciliation import billing_reconciliation_contract_results

        results = billing_reconciliation_contract_results(
            {
                "ACCOUNT_BILLED_CREDITS": 0,
                "ACCOUNT_BILLED_COST_USD": 0,
                "ACCOUNT_USED_CREDITS": 0,
                "COMPUTE_CREDITS": 0,
                "CLOUD_SERVICES_CREDITS": 0,
                "CLOUD_SERVICES_ADJUSTMENT": 0,
                "ACCOUNT_CLOUD_SERVICES_ADJUSTMENT": 0,
                "WAREHOUSE_CREDITS": 0,
                "WAREHOUSE_COST_ESTIMATE_USD": 0,
                "WAREHOUSE_COST_USD": 0,
                "SERVICE_OTHER_CREDITS": 0,
                "SERVICE_OTHER_COST_USD": 0,
                "CORTEX_AI_CREDITS": 12,
                "CORTEX_AI_COST_USD": 44.16,
                "BILLING_RECONCILIATION_STATUS": "passed",
                "BILLING_WINDOW_START": "2026-06-21",
                "BILLING_WINDOW_END": "2026-06-27",
                "BILLING_WINDOW_COMPLETE": True,
                "BILLING_SOURCE_FRESHNESS_TS": "2026-06-27",
                "BILLING_LATENCY_NOTE": "Completed UTC billing days only.",
                "BILLING_RECONCILIATION_WINDOW_START": "2026-06-21",
                "BILLING_RECONCILIATION_WINDOW_END": "2026-06-27",
                "BILLING_RECONCILIATION_FRESHNESS": "completed account billing history",
                "WAREHOUSE_BRIDGE_IS_PRIMARY_TOTAL": False,
            }
        )

        self.assertFalse(results["passed"], results)
        codes = {failure["code"] for failure in results["failures"]}
        self.assertIn("ACCOUNT_TOTAL_ZERO_WITH_CORTEX_SPEND", codes)


if __name__ == "__main__":
    unittest.main()
