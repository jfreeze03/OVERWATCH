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
                "CREDITS_BILLED": [10.0, 4.0],
                "CREDITS_USED": [9.0, 3.5],
                "CREDITS_ADJUSTMENT_CLOUD_SERVICES": [-0.2, -0.1],
                "DAILY_SPEND_USD": [36.8, 14.72],
            }
        )
        warehouse_rows = pd.DataFrame({"WAREHOUSE_CREDITS": [6.0, 2.0]})

        summary = summarize_billing_reconciliation(account_rows, warehouse_rows, credit_price=3.68)

        self.assertEqual(summary["ACCOUNT_BILLED_CREDITS"], 14.0)
        self.assertEqual(summary["WAREHOUSE_CREDITS"], 8.0)
        self.assertEqual(summary["SERVICE_OTHER_CREDITS"], 6.0)
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


if __name__ == "__main__":
    unittest.main()
