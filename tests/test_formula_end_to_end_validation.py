import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


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
            FORMULA_VALUE_GATE_REL,
            FORMULA_VALUE_RECONCILIATION_REL,
            FORMULA_VALUE_SOURCE_RECONCILIATION_REL,
            PACKET_SCHEMA_GATE_REL,
            PACKET_SCHEMA_UPGRADE_REL,
            PACKET_FORMULA_REL,
            RENDERED_FORMULA_REL,
            SNOWFLAKE_FORMULA_GATE_REL,
            SNOWFLAKE_FORMULA_LIVE_REL,
            SNOWFLAKE_FORMULA_STATIC_REL,
            SNOWFLAKE_FORMULA_VALUE_REL,
            WORKLOAD_FORMULA_LIVE_REL,
        )

        for rel in (
            FORMULA_CHAIN_REL,
            FORMULA_VALUE_RECONCILIATION_REL,
            FORMULA_VALUE_SOURCE_RECONCILIATION_REL,
            PACKET_FORMULA_REL,
            FLAT_PACKET_FORMULA_REL,
            SNOWFLAKE_FORMULA_STATIC_REL,
            PACKET_SCHEMA_UPGRADE_REL,
            RENDERED_FORMULA_REL,
            COST_WORKBENCH_CHART_REL,
            FORMULA_LIVE_REL,
            SNOWFLAKE_FORMULA_LIVE_REL,
            SNOWFLAKE_FORMULA_VALUE_REL,
            CORTEX_SERVICE_TYPE_LIVE_REL,
            WORKLOAD_FORMULA_LIVE_REL,
            FORMULA_GATE_REL,
            FORMULA_VALUE_GATE_REL,
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
        self.assertTrue(by_check["account_billing_uses_daily_billing_source"]["passed"])
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

    def test_formula_value_reconciliation_is_value_level(self):
        from tools.contracts.formula_end_to_end_validation import REQUIRED_PACKET_FIELDS

        value = self.artifacts["artifacts/formula_authority/formula_value_reconciliation_results.json"]
        source = self.artifacts["artifacts/formula_authority/formula_value_source_reconciliation.json"]

        self.assertTrue(value["passed"], value)
        self.assertTrue(source["passed"], source)
        self.assertEqual(value["formula_validation_mode"], "fixture_static")
        self.assertTrue(value["live_skipped"])
        self.assertFalse(value["live_executed"])
        by_field = {row["decision_packet_field"]: row for row in value["rows"]}
        source_by_field = {row["decision_packet_field"]: row for row in source["rows"]}
        self.assertEqual(set(REQUIRED_PACKET_FIELDS), set(by_field))
        for field, row in by_field.items():
            self.assertIn(field, source_by_field)
            self.assertIn("source_rows_present", row, field)
            self.assertIn("source_confirmed_zero", row, field)
            self.assertIn("packet_value_source", row, field)
            self.assertIn("flat_value_source", row, field)
            self.assertIn("rendered_value_source", row, field)
            self.assertIn("chart_value_source", row, field)
            self.assertIn("export_value_source", row, field)
            self.assertIn("case_value_source", row, field)
            self.assertIn("packet_matches_flat", row, field)
            self.assertIn("flat_matches_rendered", row, field)
            self.assertTrue(row["packet_matches_flat"], row)
            self.assertTrue(row["flat_matches_rendered"], row)
            self.assertTrue(row["selected_credit_column"], row)
            self.assertTrue(row["selected_credit_price"], row)
            self.assertTrue(row["passed"], row)

    def test_formula_value_source_reconciliation_rejects_synthetic_only_live_proof(self):
        from tools.contracts.formula_end_to_end_validation import (
            FLAT_PACKET_FORMULA_REL,
            PACKET_FORMULA_REL,
            RENDERED_FORMULA_REL,
            build_formula_value_source_reconciliation_results,
        )

        chain = {
            "passed": True,
            "failure_count": 0,
            "rows": [
                {
                    "formula_id": "account_billed_total",
                    "decision_packet_field": "ACCOUNT_BILLED_COST_USD",
                    "flat_packet_field": "ACCOUNT_BILLED_COST_USD",
                    "selected_credit_column": "CREDITS_BILLED",
                    "selected_credit_price": "CREDIT_PRICE_USD",
                    "source_rows_present": True,
                    "source_confirmed_zero": False,
                    "fixture_expected_value": 36.8,
                    "tolerance": 0.01,
                    "raw_sql_included": False,
                }
            ],
        }

        result = build_formula_value_source_reconciliation_results(
            chain,
            root=ROOT,
            launch_profile="internal_live",
            artifact_payloads={
                PACKET_FORMULA_REL: {
                    "rows": [
                        {
                            "packet_field": "ACCOUNT_BILLED_COST_USD",
                            "packet_value": 36.8,
                            "packet_value_source": "fixture_expected_value",
                        }
                    ]
                },
                FLAT_PACKET_FORMULA_REL: {
                    "rows": [
                        {
                            "flat_packet_field": "ACCOUNT_BILLED_COST_USD",
                            "flat_value": 36.8,
                            "flat_value_source": "fixture_expected_value",
                        }
                    ]
                },
                RENDERED_FORMULA_REL: {
                    "value_checks": [
                        {
                            "packet_field": "ACCOUNT_BILLED_COST_USD",
                            "rendered_value": 36.8,
                            "rendered_value_source": "fixture_expected_value",
                        }
                    ]
                },
            },
        )

        self.assertFalse(result["passed"], result)
        self.assertIn("fixture", result["rows"][0]["failure_reason"])

    def test_formula_value_source_reconciliation_prefers_artifact_values(self):
        from tools.contracts.formula_end_to_end_validation import (
            FLAT_PACKET_FORMULA_REL,
            PACKET_FORMULA_REL,
            RENDERED_FORMULA_REL,
            build_formula_value_source_reconciliation_results,
        )

        chain = {
            "passed": True,
            "failure_count": 0,
            "rows": [
                {
                    "formula_id": "account_billed_total",
                    "decision_packet_field": "ACCOUNT_BILLED_COST_USD",
                    "flat_packet_field": "ACCOUNT_BILLED_COST_USD",
                    "selected_credit_column": "CREDITS_BILLED",
                    "selected_credit_price": "CREDIT_PRICE_USD",
                    "source_rows_present": True,
                    "source_confirmed_zero": False,
                    "fixture_expected_value": 36.8,
                    "tolerance": 0.01,
                    "raw_sql_included": False,
                }
            ],
        }
        payloads = {
            PACKET_FORMULA_REL: {"rows": [{"packet_field": "ACCOUNT_BILLED_COST_USD", "packet_value": 42.0}]},
            FLAT_PACKET_FORMULA_REL: {"rows": [{"flat_packet_field": "ACCOUNT_BILLED_COST_USD", "flat_value": 42.0}]},
            RENDERED_FORMULA_REL: {"value_checks": [{"packet_field": "ACCOUNT_BILLED_COST_USD", "rendered_value": 42.0}]},
        }

        result = build_formula_value_source_reconciliation_results(
            chain,
            root=ROOT,
            launch_profile="internal_fixture",
            artifact_payloads=payloads,
        )

        self.assertTrue(result["passed"], result)
        row = result["rows"][0]
        self.assertEqual(row["packet_value"], 42.0)
        self.assertIn(PACKET_FORMULA_REL, row["packet_value_source"])
        self.assertIn(RENDERED_FORMULA_REL, row["rendered_value_source"])

    def test_formula_value_reconciliation_rejects_missing_source_zero(self):
        from tools.contracts.formula_end_to_end_validation import (
            FLAT_PACKET_FORMULA_REL,
            PACKET_FORMULA_REL,
            RENDERED_FORMULA_REL,
            build_formula_value_reconciliation_results,
        )

        chain = {
            "passed": True,
            "failure_count": 0,
            "rows": [
                {
                    "formula_id": "account_billed_total",
                    "decision_packet_field": "ACCOUNT_BILLED_COST_USD",
                    "flat_packet_field": "ACCOUNT_BILLED_COST_USD",
                    "selected_credit_column": "CREDITS_BILLED",
                    "selected_credit_price": "CREDIT_PRICE_USD",
                    "source_rows_present": False,
                    "source_confirmed_zero": False,
                    "packet_value": 0,
                    "flat_value": 0,
                    "rendered_value": 0,
                    "fixture_expected_value": None,
                    "live_expected_value": None,
                    "tolerance": 0.01,
                    "raw_sql_included": False,
                }
            ],
        }

        result = build_formula_value_reconciliation_results(
            chain,
            launch_profile="internal_fixture",
            artifact_payloads={
                PACKET_FORMULA_REL: {"rows": [{"packet_field": "ACCOUNT_BILLED_COST_USD", "packet_value": 0}]},
                FLAT_PACKET_FORMULA_REL: {"rows": [{"flat_packet_field": "ACCOUNT_BILLED_COST_USD", "flat_value": 0}]},
                RENDERED_FORMULA_REL: {"value_checks": [{"packet_field": "ACCOUNT_BILLED_COST_USD", "rendered_value": 0}]},
            },
        )

        self.assertFalse(result["passed"], result)
        self.assertIn("source rows are missing", result["rows"][0]["failure_reason"])

    def test_formula_value_reconciliation_rejects_null_packet_with_source_rows(self):
        from tools.contracts.formula_end_to_end_validation import (
            FLAT_PACKET_FORMULA_REL,
            PACKET_FORMULA_REL,
            RENDERED_FORMULA_REL,
            build_formula_value_reconciliation_results,
        )

        chain = {
            "passed": True,
            "failure_count": 0,
            "rows": [
                {
                    "formula_id": "account_billed_total",
                    "decision_packet_field": "ACCOUNT_BILLED_COST_USD",
                    "flat_packet_field": "ACCOUNT_BILLED_COST_USD",
                    "selected_credit_column": "CREDITS_BILLED",
                    "selected_credit_price": "CREDIT_PRICE_USD",
                    "source_rows_present": True,
                    "source_confirmed_zero": False,
                    "packet_value": None,
                    "flat_value": None,
                    "rendered_value": None,
                    "fixture_expected_value": 36.8,
                    "live_expected_value": None,
                    "tolerance": 0.01,
                    "raw_sql_included": False,
                }
            ],
        }

        result = build_formula_value_reconciliation_results(
            chain,
            launch_profile="internal_fixture",
            artifact_payloads={
                PACKET_FORMULA_REL: {"rows": [{"packet_field": "ACCOUNT_BILLED_COST_USD", "packet_value": None}]},
                FLAT_PACKET_FORMULA_REL: {"rows": [{"flat_packet_field": "ACCOUNT_BILLED_COST_USD", "flat_value": None}]},
                RENDERED_FORMULA_REL: {"value_checks": [{"packet_field": "ACCOUNT_BILLED_COST_USD", "rendered_value": None}]},
            },
        )

        self.assertFalse(result["passed"], result)
        self.assertIn("FORMULA_VALUE_RECONCILIATION_FAILED", {row["code"] for row in result["failures"]})
        self.assertIn("packet value is null", result["rows"][0]["failure_reason"])

    def test_snowflake_formula_value_results_reconcile_fixture_math(self):
        value = self.artifacts["artifacts/snowflake_validation/snowflake_formula_value_results.json"]

        self.assertTrue(value["passed"], value)
        self.assertEqual(value["failure_count"], 0, value)
        by_check = {row["check_name"]: row for row in value["checks"]}
        for check_name in (
            "account_billed_cost_formula",
            "warehouse_cost_formula",
            "cortex_cost_formula",
            "cortex_ai_credit_price_source",
            "bridge_delta_signed_formula",
            "service_other_floor_formula",
            "billing_bridge_status_formula",
        ):
            self.assertIn(check_name, by_check)
            self.assertTrue(by_check[check_name]["passed"], by_check[check_name])

    def test_snowflake_formula_value_rejects_bridge_delta_mismatch(self):
        from tools.contracts.formula_end_to_end_validation import build_snowflake_formula_value_results

        def row(field: str, value: object) -> dict[str, object]:
            return {
                "decision_packet_field": field,
                "packet_value": value,
                "flat_value": value,
                "rendered_value": value,
                "source_rows_present": True,
                "source_confirmed_zero": False,
                "passed": True,
            }

        formula_values = {
            "passed": True,
            "rows": [
                row("ACCOUNT_BILLED_CREDITS", 10),
                row("ACCOUNT_BILLED_COST_USD", 36.8),
                row("WAREHOUSE_CREDITS", 6),
                row("WAREHOUSE_COST_ESTIMATE_USD", 22.08),
                row("WAREHOUSE_COST_USD", 22.08),
                row("CORTEX_AI_CREDITS", 2),
                row("CORTEX_AI_COST_USD", 4.40),
                row("SERVICE_OTHER_CREDITS", 4),
                row("SERVICE_OTHER_COST_USD", 14.72),
                row("BILLING_BRIDGE_DELTA_CREDITS", 99),
                row("BILLING_BRIDGE_DELTA_USD", 14.72),
                row("BILLING_BRIDGE_STATUS", "warehouse_lower_than_billed"),
                row("BILLING_WINDOW_COMPLETE", True),
                row("SPEND_MOVEMENT_PCT", 12.5),
            ],
        }

        result = build_snowflake_formula_value_results(formula_values)

        self.assertFalse(result["passed"], result)
        failed = {row["check_name"] for row in result["checks"] if not row["passed"]}
        self.assertIn("bridge_delta_signed_formula", failed)

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
        value_gate = self.artifacts["artifacts/launch_readiness/formula_value_gate_results.json"]

        self.assertTrue(gate["passed"], gate)
        self.assertTrue(value_gate["passed"], value_gate)
        self.assertTrue(gate["packet_formula_sql_passed"])
        self.assertTrue(gate["flat_packet_formula_passed"])
        self.assertTrue(gate["snowflake_formula_static_passed"])
        self.assertTrue(gate["packet_schema_upgrade_passed"])
        self.assertTrue(gate["formula_value_reconciliation_passed"])
        self.assertTrue(gate["formula_value_source_reconciliation_passed"])
        self.assertGreaterEqual(gate["formula_value_artifact_sourced_row_count"], 1)
        self.assertEqual(gate["formula_validation_mode"], "fixture_static")
        self.assertFalse(gate["snowflake_formula_live_required"])
        self.assertFalse(gate["snowflake_formula_live_executed"])
        self.assertFalse(gate["snowflake_formula_live_passed"])
        self.assertTrue(gate["snowflake_formula_live_skipped"])

    def test_live_formula_status_passes_only_when_live_rows_execute(self):
        from tools.contracts.formula_end_to_end_validation import build_formula_live_validation_results

        with patch.dict("os.environ", {"OVERWATCH_SNOWFLAKE_VALIDATION": "1"}, clear=False):
            result = build_formula_live_validation_results(ROOT, live_rows=[{"formula_id": "account_billed_cost", "passed": True}])

        self.assertTrue(result["passed"], result)
        self.assertEqual(result["formula_validation_mode"], "live")
        self.assertTrue(result["snowflake_formula_live_required"])
        self.assertTrue(result["snowflake_formula_live_executed"])
        self.assertTrue(result["snowflake_formula_live_passed"])
        self.assertFalse(result["snowflake_formula_live_skipped"])

    def test_ambiguous_live_skipped_and_passed_combination_fails(self):
        from tools.contracts.formula_end_to_end_validation import evaluate_formula_end_to_end_gate

        passed = {"passed": True, "failure_count": 0}
        live = {
            "passed": True,
            "formula_validation_mode": "fixture_static",
            "snowflake_formula_live_required": False,
            "snowflake_formula_live_executed": False,
            "snowflake_formula_live_passed": True,
            "snowflake_formula_live_skipped": True,
            "failure_count": 0,
        }

        result = evaluate_formula_end_to_end_gate(passed, passed, passed, passed, passed, passed, passed, live)

        self.assertFalse(result["passed"], result)
        self.assertIn("AMBIGUOUS_FORMULA_LIVE_STATUS", {row["code"] for row in result["failures"]})

    def test_formula_artifacts_do_not_store_raw_sql_bodies(self):
        for rel, payload in self.artifacts.items():
            serialized = json.dumps(payload, sort_keys=True)
            self.assertNotIn("SELECT ", serialized.upper(), rel)
            self.assertNotIn("CREATE OR REPLACE PROCEDURE", serialized.upper(), rel)
            self.assertIn('"raw_sql_included": false', serialized.lower(), rel)


if __name__ == "__main__":
    unittest.main()
