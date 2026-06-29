import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FormulaPacketSqlTests(unittest.TestCase):
    def test_repo_snowflake_formula_static_passes(self):
        from tools.contracts.formula_end_to_end_validation import build_snowflake_formula_static_results

        result = build_snowflake_formula_static_results(ROOT)

        self.assertTrue(result["passed"], result)
        self.assertEqual(result["failure_count"], 0)

    def test_account_total_formula_using_warehouse_bridge_fails(self):
        from tools.contracts.formula_end_to_end_validation import build_snowflake_formula_static_results

        result = build_snowflake_formula_static_results(
            ROOT,
            sql_texts={
                "setup": """
                  CREDITS_BILLED CREDITS_USED_COMPUTE CREDITS_USED_CLOUD_SERVICES
                  WAREHOUSE_CREDITS AS ACCOUNT_BILLED_COST_USD
                  FACT_CORTEX_DAILY CORTEX_AI_CREDITS CREDIT_PRICE_USD
                  SERVICE_OTHER_CREDITS
                  ACCOUNT_BILLED_CREDITS - WAREHOUSE_CREDITS AS BILLING_BRIDGE_DELTA_CREDITS
                  SPEND_MOVEMENT_PCT PRIOR_COST_USD BILLING_WINDOW_COMPLETE
                """,
                "tables": "",
                "validation": "",
                "monolith_setup": "",
                "monolith_validation": "",
                "drop": "",
            },
        )

        by_check = {row["check_name"]: row for row in result["checks"]}
        self.assertFalse(by_check["account_billed_total_not_warehouse_bridge"]["passed"], result)
        self.assertFalse(result["passed"], result)

    def test_missing_cortex_canonical_source_fails(self):
        from tools.contracts.formula_end_to_end_validation import build_snowflake_formula_static_results

        result = build_snowflake_formula_static_results(
            ROOT,
            sql_texts={
                "setup": """
                  ACCOUNT_BILLED_CREDITS CREDITS_BILLED
                  WAREHOUSE_CREDITS CREDITS_USED_COMPUTE CREDITS_USED_CLOUD_SERVICES
                  SERVICE_TYPE ILIKE '%AI%' CORTEX_AI_CREDITS CREDIT_PRICE_USD
                  SERVICE_OTHER_CREDITS
                  ACCOUNT_BILLED_CREDITS - WAREHOUSE_CREDITS AS BILLING_BRIDGE_DELTA_CREDITS
                  SPEND_MOVEMENT_PCT PRIOR_COST_USD BILLING_WINDOW_COMPLETE
                """,
                "tables": "",
                "validation": "",
                "monolith_setup": "",
                "monolith_validation": "",
                "drop": "",
            },
        )

        by_check = {row["check_name"]: row for row in result["checks"]}
        self.assertFalse(by_check["cortex_formula_uses_canonical_source"]["passed"], result)
        self.assertFalse(result["passed"], result)

    def test_clipped_bridge_delta_fails(self):
        from tools.contracts.formula_end_to_end_validation import build_snowflake_formula_static_results

        result = build_snowflake_formula_static_results(
            ROOT,
            sql_texts={
                "setup": """
                  ACCOUNT_BILLED_CREDITS CREDITS_BILLED
                  WAREHOUSE_CREDITS CREDITS_USED_COMPUTE CREDITS_USED_CLOUD_SERVICES
                  FACT_CORTEX_DAILY CORTEX_AI_CREDITS CREDIT_PRICE_USD
                  SERVICE_OTHER_CREDITS
                  GREATEST(ACCOUNT_BILLED_CREDITS - WAREHOUSE_CREDITS, 0) AS BILLING_BRIDGE_DELTA_CREDITS
                  SPEND_MOVEMENT_PCT PRIOR_COST_USD BILLING_WINDOW_COMPLETE
                """,
                "tables": "",
                "validation": "",
                "monolith_setup": "",
                "monolith_validation": "",
                "drop": "",
            },
        )

        by_check = {row["check_name"]: row for row in result["checks"]}
        self.assertFalse(by_check["service_other_and_signed_bridge_delta_present"]["passed"], result)
        self.assertFalse(result["passed"], result)

    def test_spend_movement_without_complete_window_or_pending_state_fails(self):
        from tools.contracts.formula_end_to_end_validation import build_snowflake_formula_static_results

        result = build_snowflake_formula_static_results(
            ROOT,
            sql_texts={
                "setup": """
                  ACCOUNT_BILLED_CREDITS CREDITS_BILLED
                  WAREHOUSE_CREDITS CREDITS_USED_COMPUTE CREDITS_USED_CLOUD_SERVICES
                  FACT_CORTEX_DAILY CORTEX_AI_CREDITS CREDIT_PRICE_USD
                  SERVICE_OTHER_CREDITS
                  ACCOUNT_BILLED_CREDITS - WAREHOUSE_CREDITS AS BILLING_BRIDGE_DELTA_CREDITS
                  SPEND_MOVEMENT_PCT PRIOR_COST_USD
                """,
                "tables": "",
                "validation": "",
                "monolith_setup": "",
                "monolith_validation": "",
                "drop": "",
            },
        )

        by_check = {row["check_name"]: row for row in result["checks"]}
        self.assertFalse(by_check["spend_movement_comparable_window"]["passed"], result)
        self.assertFalse(result["passed"], result)


if __name__ == "__main__":
    unittest.main()
