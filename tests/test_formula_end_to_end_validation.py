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
            FLAT_PACKET_FORMULA_REL,
            FORMULA_CHAIN_REL,
            FORMULA_GATE_REL,
            FORMULA_LIVE_REL,
            PACKET_SCHEMA_GATE_REL,
            PACKET_SCHEMA_UPGRADE_REL,
            PACKET_FORMULA_REL,
            RENDERED_FORMULA_REL,
            SNOWFLAKE_FORMULA_GATE_REL,
            SNOWFLAKE_FORMULA_LIVE_REL,
            SNOWFLAKE_FORMULA_STATIC_REL,
            WORKLOAD_FORMULA_LIVE_REL,
        )

        for rel in (
            FORMULA_CHAIN_REL,
            PACKET_FORMULA_REL,
            FLAT_PACKET_FORMULA_REL,
            SNOWFLAKE_FORMULA_STATIC_REL,
            PACKET_SCHEMA_UPGRADE_REL,
            RENDERED_FORMULA_REL,
            COST_WORKBENCH_CHART_REL,
            FORMULA_LIVE_REL,
            SNOWFLAKE_FORMULA_LIVE_REL,
            CORTEX_SERVICE_TYPE_LIVE_REL,
            WORKLOAD_FORMULA_LIVE_REL,
            FORMULA_GATE_REL,
            PACKET_SCHEMA_GATE_REL,
            SNOWFLAKE_FORMULA_GATE_REL,
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

    def test_flat_packet_formula_sql_passes_for_repo(self):
        flat = self.artifacts["artifacts/formula_authority/flat_packet_formula_results.json"]

        self.assertTrue(flat["passed"], flat)
        self.assertEqual(flat["failure_count"], 0, flat)
        fields = {row["flat_packet_field"] for row in flat["rows"]}
        self.assertIn("ACCOUNT_BILLED_COST_USD", fields)
        self.assertIn("CORTEX_AI_COST_USD", fields)
        self.assertTrue(all(row["checks"]["flat_packet_extract"] for row in flat["rows"]))

    def test_packet_schema_upgrade_passes_for_repo(self):
        schema = self.artifacts["artifacts/snowflake_validation/packet_schema_upgrade_results.json"]

        self.assertTrue(schema["passed"], schema)
        self.assertEqual(schema["required_table_count"], 2)
        tables = {row["table_name"] for row in schema["rows"]}
        self.assertEqual(tables, {"MART_SECTION_COMMAND_BRIEF", "MART_SECTION_DECISION_CURRENT_FLAT"})
        self.assertTrue(all(row["checks"]["split_setup_alter"] for row in schema["rows"]))

    def test_snowflake_formula_static_passes_for_repo(self):
        static = self.artifacts["artifacts/formula_authority/snowflake_formula_static_results.json"]

        self.assertTrue(static["passed"], static)
        by_check = {row["check_name"]: row for row in static["checks"]}
        self.assertTrue(by_check["account_billed_total_not_warehouse_bridge"]["passed"])
        self.assertTrue(by_check["service_other_and_signed_bridge_delta_present"]["passed"])
        self.assertTrue(by_check["decision_packet_fields_inserted"]["passed"])
        self.assertTrue(by_check["flat_packet_fields_extracted"]["passed"])

    def test_formula_chain_covers_all_required_formula_fields(self):
        from tools.contracts.formula_end_to_end_validation import REQUIRED_PACKET_FIELDS

        chain = self.artifacts["artifacts/formula_authority/formula_chain_results.json"]

        self.assertTrue(chain["passed"], chain)
        by_field = {row["decision_packet_field"]: row for row in chain["rows"]}
        self.assertEqual(set(REQUIRED_PACKET_FIELDS), set(by_field))
        for field in REQUIRED_PACKET_FIELDS:
            self.assertIn(field, by_field)
            self.assertTrue(by_field[field]["packet_sql_present"], by_field[field])
            self.assertTrue(by_field[field]["flat_sql_present"], by_field[field])
            self.assertTrue(by_field[field]["rendered_field_present"], by_field[field])
            for key in (
                "formula_id",
                "cost_db_formula",
                "cost_db_columns",
                "overwatch_helper",
                "snowflake_source_file",
                "snowflake_procedure_or_cte",
                "decision_packet_field",
                "flat_packet_field",
                "selected_credit_column",
                "selected_credit_price",
                "packet_value",
                "flat_value",
                "rendered_value",
                "fixture_expected_value",
                "tolerance",
                "source_confirmed_zero",
                "unavailable_state",
            ):
                self.assertIn(key, by_field[field])

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

    def test_formula_gate_recomputes_new_sub_gates(self):
        gate = self.artifacts["artifacts/launch_readiness/formula_end_to_end_gate_results.json"]

        self.assertTrue(gate["passed"], gate)
        self.assertTrue(gate["packet_formula_sql_passed"])
        self.assertTrue(gate["flat_packet_formula_passed"])
        self.assertTrue(gate["snowflake_formula_static_passed"])
        self.assertTrue(gate["packet_schema_upgrade_passed"])
        self.assertTrue(gate["snowflake_formula_live_passed"])
        self.assertTrue(gate["snowflake_formula_live_skipped"])

    def test_formula_artifacts_do_not_store_raw_sql_bodies(self):
        for rel, payload in self.artifacts.items():
            serialized = json.dumps(payload, sort_keys=True)
            self.assertNotIn("SELECT ", serialized.upper(), rel)
            self.assertNotIn("CREATE OR REPLACE PROCEDURE", serialized.upper(), rel)
            self.assertIn('"raw_sql_included": false', serialized.lower(), rel)


if __name__ == "__main__":
    unittest.main()
