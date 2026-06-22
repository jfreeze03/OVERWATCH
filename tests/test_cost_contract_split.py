from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


class CostContractSplitTests(unittest.TestCase):
    def test_cost_contract_reexports_moved_contracts(self):
        from sections import cost_contract
        from sections import cost_contract_contracts

        self.assertIs(cost_contract.build_cost_monitoring_mart_sql, cost_contract_contracts.build_cost_monitoring_mart_sql)
        self.assertIs(cost_contract.WORKFLOWS, cost_contract_contracts.WORKFLOWS)
        self.assertIs(cost_contract.WORKFLOW_DETAILS, cost_contract_contracts.WORKFLOW_DETAILS)
        self.assertIs(cost_contract.WORKFLOW_MODULES, cost_contract_contracts.WORKFLOW_MODULES)
        self.assertIs(cost_contract.LEGACY_COST_WORKFLOW_ALIASES, cost_contract_contracts.LEGACY_COST_WORKFLOW_ALIASES)
        self.assertEqual(cost_contract._DETAIL_WORKFLOW_KEY, "_cost_contract_detail_workflow")
        self.assertEqual(cost_contract._PENDING_DETAIL_WORKFLOW_KEY, "_cost_contract_pending_detail_workflow")

    def test_cost_contract_reexports_moved_price_helpers(self):
        from sections import cost_contract
        from sections import cost_contract_helpers

        self.assertIs(cost_contract.get_credit_price, cost_contract_helpers.get_credit_price)
        self.assertIs(cost_contract.get_current_ai_credit_price, cost_contract_helpers.get_current_ai_credit_price)

    def test_cost_monitoring_mart_sql_contract_stays_stable(self):
        from sections.cost_contract_contracts import build_cost_monitoring_mart_sql

        sql = build_cost_monitoring_mart_sql().upper()

        self.assertIn("FACT_COST_MONITORING_SIGNAL", sql)
        self.assertIn("FACT_COST_INCIDENT_TIMELINE", sql)
        self.assertIn("SP_OVERWATCH_REFRESH_COST_MONITORING", sql)
        self.assertIn("OVERWATCH_COST_MONITORING_REFRESH", sql)
        self.assertIn("WAREHOUSE = COMPUTE_WH", sql)

    def test_price_helpers_preserve_session_state_fallbacks(self):
        from sections import cost_contract_helpers

        with patch.object(cost_contract_helpers.st, "session_state", {"credit_price": "4.25"}):
            self.assertEqual(cost_contract_helpers.get_credit_price(), 4.25)

        with (
            patch.object(cost_contract_helpers.st, "session_state", {"ai_credit_price": "3.10"}),
            patch("sections.cost_contract_helpers.get_ai_credit_price", side_effect=RuntimeError("not configured")),
        ):
            self.assertEqual(cost_contract_helpers.get_current_ai_credit_price(), 3.10)

    def test_cost_contract_split_does_not_import_alert_facade(self):
        alert_facade_import = "utils" + ".alerts"
        modules = (
            APP_ROOT / "sections" / "cost_contract.py",
            APP_ROOT / "sections" / "cost_contract_contracts.py",
            APP_ROOT / "sections" / "cost_contract_helpers.py",
        )
        for path in modules:
            with self.subTest(path=path.name):
                self.assertNotIn(alert_facade_import, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
