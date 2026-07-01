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
        self.assertEqual(summary["BILLING_BRIDGE_DELTA_CREDITS"], 6.0)
        self.assertEqual(summary["BILLING_BRIDGE_DELTA_USD"], 22.08)
        self.assertEqual(summary["BILLING_BRIDGE_STATUS"], "warehouse_lower_than_billed")
        self.assertEqual(summary["COMPUTE_CREDITS"], 8.0)
        self.assertEqual(summary["CLOUD_SERVICES_CREDITS"], 1.1)
        self.assertEqual(summary["CLOUD_SERVICES_ADJUSTMENT"], -0.3)
        self.assertEqual(summary["CORTEX_AI_CREDITS"], 4.0)
        self.assertEqual(summary["CORTEX_AI_COST_USD"], 14.72)
        self.assertEqual(summary["BILLING_WINDOW_START"], "2026-06-21")
        self.assertEqual(summary["BILLING_WINDOW_END"], "2026-06-22")
        self.assertTrue(summary["BILLING_WINDOW_COMPLETE"])
        self.assertFalse(summary["WAREHOUSE_BRIDGE_IS_PRIMARY_TOTAL"])
        self.assertEqual(summary["BILLING_RECONCILIATION_STATUS"], "warehouse_lower_than_billed")

    def test_warehouse_bridge_sql_matches_cost_db_formula(self):
        from utils.billing_reconciliation import build_warehouse_billing_bridge_sql

        sql = build_warehouse_billing_bridge_sql(
            8,
            company="ALFA",
            credit_price=3.68,
            start_date="2026-06-21",
            end_date="2026-06-28",
        ).upper()

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY", sql)
        self.assertIn("CREDITS_USED_COMPUTE", sql)
        self.assertIn("CREDITS_USED_CLOUD_SERVICES", sql)
        self.assertIn("COALESCE(WAREHOUSE_ID, 0) > 0", sql)
        self.assertIn("NULLIF(TRIM(WAREHOUSE_NAME), '') IS NOT NULL", sql)
        self.assertIn("HAVING SUM(COALESCE(CREDITS_USED_COMPUTE, 0) + COALESCE(CREDITS_USED_CLOUD_SERVICES, 0)) > 0", sql)
        self.assertIn("WAREHOUSE_BRIDGE_BREAKDOWN", sql)
        self.assertNotIn("SUM(COALESCE(CREDITS_USED, 0)) AS WAREHOUSE_CREDITS", sql)

    def test_warehouse_bridge_dataframe_fallback_uses_compute_plus_cloud(self):
        from utils.billing_reconciliation import summarize_billing_reconciliation

        account_rows = pd.DataFrame({"USAGE_DATE": ["2026-06-21"], "CREDITS_BILLED": [10.0]})
        warehouse_rows = pd.DataFrame(
            {
                "CREDITS_USED_COMPUTE": ["2.5", "3.0"],
                "CREDITS_USED_CLOUD_SERVICES": ["0.5", "1.0"],
            }
        )

        summary = summarize_billing_reconciliation(account_rows, warehouse_rows, credit_price=3.68)

        self.assertEqual(summary["WAREHOUSE_CREDITS"], 7.0)
        self.assertEqual(summary["WAREHOUSE_COST_USD"], 25.76)
        self.assertEqual(summary["SERVICE_OTHER_CREDITS"], 3.0)
        self.assertEqual(summary["BILLING_BRIDGE_DELTA_CREDITS"], 3.0)

    def test_negative_bridge_delta_is_preserved_and_labeled(self):
        from utils.billing_reconciliation import summarize_billing_reconciliation

        account_rows = pd.DataFrame({"USAGE_DATE": ["2026-06-21"], "CREDITS_BILLED": [5.0]})
        warehouse_rows = pd.DataFrame({"WAREHOUSE_CREDITS": [8.0]})

        summary = summarize_billing_reconciliation(account_rows, warehouse_rows, credit_price=3.68)

        self.assertEqual(summary["SERVICE_OTHER_CREDITS"], 0.0)
        self.assertEqual(summary["BILLING_BRIDGE_DELTA_CREDITS"], -3.0)
        self.assertEqual(summary["BILLING_BRIDGE_DELTA_USD"], -11.04)
        self.assertEqual(summary["BILLING_BRIDGE_STATUS"], "warehouse_higher_than_billed")

    def test_cortex_allowlist_avoids_broad_ai_substring(self):
        from utils.billing_reconciliation import summarize_billing_reconciliation

        account_rows = pd.DataFrame(
            {
                "USAGE_DATE": ["2026-06-21", "2026-06-21"],
                "SERVICE_TYPE": ["CORTEX_AI", "MAINTENANCE_AI_HELPER"],
                "CREDITS_BILLED": [2.0, 7.0],
            }
        )

        summary = summarize_billing_reconciliation(account_rows, pd.DataFrame({"WAREHOUSE_CREDITS": [1.0]}), credit_price=3.68)

        self.assertEqual(summary["CORTEX_AI_CREDITS"], 2.0)
        self.assertEqual(summary["CORTEX_AI_COST_USD"], 4.4)

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
                "BILLING_BRIDGE_DELTA_CREDITS": 0,
                "BILLING_BRIDGE_DELTA_USD": 0,
                "BILLING_BRIDGE_STATUS": "matched",
                "CORTEX_AI_CREDITS": 12,
                "CORTEX_AI_COST_USD": 44.16,
                "BILLING_RECONCILIATION_STATUS": "matched",
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

    def test_contract_allows_zero_account_total_only_when_pending(self):
        from utils.billing_reconciliation import billing_reconciliation_contract_results

        summary = {
            field: 0
            for field in (
                "ACCOUNT_BILLED_CREDITS",
                "ACCOUNT_BILLED_COST_USD",
                "ACCOUNT_USED_CREDITS",
                "COMPUTE_CREDITS",
                "CLOUD_SERVICES_CREDITS",
                "CLOUD_SERVICES_ADJUSTMENT",
                "ACCOUNT_CLOUD_SERVICES_ADJUSTMENT",
                "WAREHOUSE_CREDITS",
                "WAREHOUSE_COST_ESTIMATE_USD",
                "WAREHOUSE_COST_USD",
                "SERVICE_OTHER_CREDITS",
                "SERVICE_OTHER_COST_USD",
                "BILLING_BRIDGE_DELTA_CREDITS",
                "BILLING_BRIDGE_DELTA_USD",
            )
        }
        summary.update(
            {
                "BILLING_BRIDGE_STATUS": "pending",
                "CORTEX_AI_CREDITS": 12,
                "CORTEX_AI_COST_USD": 44.16,
                "BILLING_RECONCILIATION_STATUS": "pending",
                "BILLING_WINDOW_START": "pending",
                "BILLING_WINDOW_END": "pending",
                "BILLING_WINDOW_COMPLETE": False,
                "BILLING_SOURCE_FRESHNESS_TS": "pending",
                "BILLING_LATENCY_NOTE": "Billing reconciliation pending.",
                "BILLING_RECONCILIATION_WINDOW_START": "pending",
                "BILLING_RECONCILIATION_WINDOW_END": "pending",
                "BILLING_RECONCILIATION_FRESHNESS": "pending",
                "WAREHOUSE_BRIDGE_IS_PRIMARY_TOTAL": False,
            }
        )

        results = billing_reconciliation_contract_results(summary)

        self.assertTrue(results["passed"], results)


if __name__ == "__main__":
    unittest.main()
