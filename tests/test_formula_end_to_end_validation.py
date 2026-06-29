import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FormulaEndToEndValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tools.contracts.formula_end_to_end_validation import write_formula_end_to_end_artifacts

        cls.artifacts = write_formula_end_to_end_artifacts(ROOT)

    def test_formula_chain_artifacts_are_written(self):
        from tools.contracts.formula_end_to_end_validation import (
            CORTEX_SERVICE_TYPE_GATE_REL,
            CORTEX_SERVICE_TYPE_LIVE_REL,
            COST_WORKBENCH_CHART_REL,
            FORMULA_CHAIN_REL,
            FORMULA_GATE_REL,
            FORMULA_LIVE_REL,
            PACKET_FORMULA_REL,
            RENDERED_FORMULA_REL,
            WORKLOAD_FORMULA_LIVE_REL,
        )

        for rel in (
            FORMULA_CHAIN_REL,
            PACKET_FORMULA_REL,
            RENDERED_FORMULA_REL,
            COST_WORKBENCH_CHART_REL,
            FORMULA_LIVE_REL,
            CORTEX_SERVICE_TYPE_LIVE_REL,
            WORKLOAD_FORMULA_LIVE_REL,
            FORMULA_GATE_REL,
            CORTEX_SERVICE_TYPE_GATE_REL,
        ):
            self.assertIn(rel, self.artifacts)
            self.assertTrue((ROOT / rel).exists(), rel)

    def test_packet_formula_sql_passes_for_repo(self):
        packet = self.artifacts["artifacts/formula_authority/packet_formula_results.json"]

        self.assertTrue(packet["passed"], packet)
        self.assertEqual(packet["failure_count"], 0, packet)
        fields = {row["packet_field"] for row in packet["rows"]}
        self.assertIn("ACCOUNT_BILLED_COST_USD", fields)
        self.assertIn("CORTEX_AI_COST_USD", fields)
        self.assertIn("BILLING_BRIDGE_DELTA_CREDITS", fields)
        self.assertTrue(all(row["raw_sql_included"] is False for row in packet["rows"]))

    def test_formula_chain_covers_required_cost_metrics(self):
        chain = self.artifacts["artifacts/formula_authority/formula_chain_results.json"]

        self.assertTrue(chain["passed"], chain)
        by_field = {row["snowflake_packet_field"]: row for row in chain["rows"]}
        for field in (
            "ACCOUNT_BILLED_COST_USD",
            "ACCOUNT_BILLED_CREDITS",
            "CORTEX_AI_COST_USD",
            "CORTEX_AI_CREDITS",
            "WAREHOUSE_CREDITS",
            "SERVICE_OTHER_CREDITS",
            "BILLING_BRIDGE_DELTA_CREDITS",
            "SPEND_MOVEMENT_PCT",
            "FORECAST_RUN_RATE_USD",
        ):
            self.assertIn(field, by_field)
            self.assertTrue(by_field[field]["packet_sql_present"], by_field[field])
            self.assertTrue(by_field[field]["rendered_field_present"], by_field[field])
            self.assertTrue(by_field[field]["cost_db_formula_id"], by_field[field])

    def test_rendered_formula_uses_same_packet_fields_for_cost_and_executive(self):
        rendered = self.artifacts["artifacts/full_app_validation/rendered_formula_results.json"]

        self.assertTrue(rendered["passed"], rendered)
        by_check = {row["check_name"]: row for row in rendered["checks"]}
        self.assertEqual(by_check["executive_total_spend_packet_field"]["actual_packet_field"], "ACCOUNT_BILLED_COST_USD")
        self.assertEqual(by_check["cost_total_spend_packet_field"]["actual_packet_field"], "ACCOUNT_BILLED_COST_USD")
        self.assertEqual(by_check["executive_cortex_packet_field"]["actual_packet_field"], "CORTEX_AI_COST_USD")
        self.assertEqual(by_check["cost_cortex_packet_field"]["actual_packet_field"], "CORTEX_AI_COST_USD")

    def test_missing_packet_sql_field_fails_contract(self):
        from tools.contracts.formula_end_to_end_validation import evaluate_packet_formula_sql

        texts = {
            "setup": "ACCOUNT_BILLED_COST_USD",
            "tables": "",
            "validation": "",
            "monolith_setup": "",
            "monolith_validation": "",
        }

        result = evaluate_packet_formula_sql(ROOT, sql_texts=texts)

        self.assertFalse(result["passed"], result)
        self.assertGreater(result["failure_count"], 0)
        codes = {row["code"] for row in result["failures"]}
        self.assertIn("PACKET_FORMULA_FIELD_MISSING", codes)

    def test_formula_artifacts_do_not_store_raw_sql_bodies(self):
        for rel, payload in self.artifacts.items():
            serialized = json.dumps(payload, sort_keys=True)
            self.assertNotIn("SELECT ", serialized.upper(), rel)
            self.assertNotIn("CREATE OR REPLACE PROCEDURE", serialized.upper(), rel)
            self.assertIn('"raw_sql_included": false', serialized.lower(), rel)


if __name__ == "__main__":
    unittest.main()
