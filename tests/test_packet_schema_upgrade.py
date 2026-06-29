import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class PacketSchemaUpgradeTests(unittest.TestCase):
    def test_repo_packet_schema_upgrade_passes(self):
        from tools.contracts.formula_end_to_end_validation import build_packet_schema_upgrade_results

        result = build_packet_schema_upgrade_results(ROOT)

        self.assertTrue(result["passed"], result)
        self.assertEqual(result["failure_count"], 0)
        self.assertEqual(result["required_table_count"], 2)

    def test_command_brief_missing_new_fields_fails_upgrade(self):
        from tools.contracts.formula_end_to_end_validation import build_packet_schema_upgrade_results

        field = "ACCOUNT_BILLED_COST_USD"
        table_sql = f"""
          ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS {field} NUMBER(38,6);
        """
        validation_sql = field
        result = build_packet_schema_upgrade_results(
            ROOT,
            sql_texts={
                "setup": "",
                "tables": table_sql,
                "validation": validation_sql,
                "monolith_setup": table_sql,
                "monolith_validation": validation_sql,
                "drop": "",
            },
        )

        self.assertFalse(result["passed"], result)
        self.assertTrue(
            any(
                row["table_name"] == "MART_SECTION_COMMAND_BRIEF"
                and row["column_name"] == field
                and not row["checks"]["split_setup_alter"]
                for row in result["rows"]
            ),
            result,
        )

    def test_flat_table_missing_new_fields_fails_upgrade(self):
        from tools.contracts.formula_end_to_end_validation import build_packet_schema_upgrade_results

        field = "CORTEX_AI_COST_USD"
        table_sql = f"""
          ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS {field} NUMBER(38,6);
        """
        validation_sql = field
        result = build_packet_schema_upgrade_results(
            ROOT,
            sql_texts={
                "setup": "",
                "tables": table_sql,
                "validation": validation_sql,
                "monolith_setup": table_sql,
                "monolith_validation": validation_sql,
                "drop": "",
            },
        )

        self.assertFalse(result["passed"], result)
        self.assertTrue(
            any(
                row["table_name"] == "MART_SECTION_DECISION_CURRENT_FLAT"
                and row["column_name"] == field
                and not row["checks"]["split_setup_alter"]
                for row in result["rows"]
            ),
            result,
        )

    def test_schema_gate_fails_on_upgrade_failure(self):
        from tools.contracts.formula_end_to_end_validation import (
            build_packet_schema_upgrade_results,
            evaluate_packet_schema_gate,
        )

        failed = build_packet_schema_upgrade_results(
            ROOT,
            sql_texts={
                "setup": "",
                "tables": "",
                "validation": "",
                "monolith_setup": "",
                "monolith_validation": "",
                "drop": "",
            },
        )
        gate = evaluate_packet_schema_gate(failed)

        self.assertFalse(gate["passed"], gate)
        self.assertEqual(gate["failures"][0]["code"], "PACKET_SCHEMA_UPGRADE_FAILED")


if __name__ == "__main__":
    unittest.main()
