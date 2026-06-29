from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class CostDbFormulaAuthorityContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tools.contracts.cost_db_formula_authority import write_cost_db_formula_authority_artifacts

        cls.artifacts = write_cost_db_formula_authority_artifacts(ROOT)

    def test_artifacts_are_written(self):
        from tools.contracts.cost_db_formula_authority import REQUIRED_FORMULA_AUTHORITY_ARTIFACTS

        for rel in REQUIRED_FORMULA_AUTHORITY_ARTIFACTS:
            self.assertIn(rel, self.artifacts)
            self.assertTrue((ROOT / rel).exists(), rel)

    def test_cost_db_mapping_captures_authority_patterns(self):
        cost_db_rows = self.artifacts["artifacts/formula_authority/cost_db_formula_mapping.json"]
        by_id = {row["formula_id"]: row for row in cost_db_rows}

        self.assertIn("numeric_normalization", by_id)
        self.assertIn("CREDITS_USED_COMPUTE", by_id["numeric_normalization"]["cost_db_columns"])
        self.assertIn("REQUEST_COUNT", by_id["numeric_normalization"]["cost_db_columns"])
        self.assertIn("SERVERLESS_CREDITS", by_id["numeric_normalization"]["cost_db_columns"])
        self.assertIn("WAREHOUSE_METERING_HISTORY", by_id["warehouse_bridge"]["cost_db_source_view"])
        self.assertIn("CREDITS_USED_COMPUTE + CREDITS_USED_CLOUD_SERVICES", by_id["warehouse_bridge"]["cost_db_formula"])
        self.assertIn("WAREHOUSE_ID > 0", by_id["warehouse_bridge"]["cost_db_formula"])
        self.assertEqual(by_id["credit_price"]["cost_db_formula"], "dollar_amount = credits * credit_price")
        self.assertIn("MoM", by_id["monthly_mom"]["cost_db_formula"])
        self.assertEqual(by_id["workbench_charts"]["status"], "matched")
        for row in cost_db_rows:
            self.assertTrue(row["overwatch_formula"], row)
            self.assertTrue(row["cost_db_columns"], row)
            self.assertEqual(row["launch_gate"], "cost_db_formula_authority")

    def test_authority_summary_and_cortex_mapping_are_written(self):
        summary = self.artifacts["artifacts/formula_authority/cost_db_formula_authority_summary.json"]
        cortex_mapping = self.artifacts["artifacts/formula_authority/cortex_service_type_mapping.json"]

        self.assertTrue(summary["passed"], summary)
        self.assertIn("SERVERLESS_CREDITS", summary["numeric_normalization_columns"])
        self.assertFalse(cortex_mapping["broad_ai_substring_match_enabled"])
        self.assertIn("CORTEX_AI", cortex_mapping["allowlist"])

    def test_gap_results_pass(self):
        gap = self.artifacts["artifacts/formula_authority/formula_gap_results.json"]

        self.assertTrue(gap["passed"], gap)
        self.assertEqual(gap["failure_count"], 0, gap)
        self.assertGreaterEqual(gap["authority_formula_count"], 6)
        self.assertGreaterEqual(gap["overwatch_formula_count"], 4)

    def test_launch_gate_rejects_missing_overwatch_mapping(self):
        from tools.contracts.cost_db_formula_authority import evaluate_cost_db_formula_authority

        gate = evaluate_cost_db_formula_authority(
            self.artifacts["artifacts/formula_authority/cost_db_formula_mapping.json"],
            [],
            self.artifacts["artifacts/formula_authority/formula_gap_results.json"],
            self.artifacts["artifacts/formula_authority/cost_db_formula_authority_summary.json"],
            self.artifacts["artifacts/formula_authority/cortex_service_type_mapping.json"],
        )

        self.assertFalse(gate["passed"], gate)
        codes = {row["code"] for row in gate["failures"]}
        self.assertIn("OVERWATCH_MAPPING_MISSING", codes)
        self.assertIn("REQUIRED_OVERWATCH_FORMULA_MISSING", codes)

    def test_launch_gate_rejects_gap_failure(self):
        from tools.contracts.cost_db_formula_authority import evaluate_cost_db_formula_authority

        gate = evaluate_cost_db_formula_authority(
            self.artifacts["artifacts/formula_authority/cost_db_formula_mapping.json"],
            self.artifacts["artifacts/formula_authority/overwatch_formula_mapping.json"],
            {"passed": False, "failure_count": 1},
            self.artifacts["artifacts/formula_authority/cost_db_formula_authority_summary.json"],
            self.artifacts["artifacts/formula_authority/cortex_service_type_mapping.json"],
        )

        self.assertFalse(gate["passed"], gate)
        self.assertIn("FORMULA_GAP_RESULTS_FAILED", {row["code"] for row in gate["failures"]})

    def test_launch_gate_rejects_symbolic_authority_row(self):
        from tools.contracts.cost_db_formula_authority import evaluate_cost_db_formula_authority

        rows = [dict(row) for row in self.artifacts["artifacts/formula_authority/cost_db_formula_mapping.json"]]
        rows[0]["overwatch_formula"] = ""
        gate = evaluate_cost_db_formula_authority(
            rows,
            self.artifacts["artifacts/formula_authority/overwatch_formula_mapping.json"],
            self.artifacts["artifacts/formula_authority/formula_gap_results.json"],
            self.artifacts["artifacts/formula_authority/cost_db_formula_authority_summary.json"],
            self.artifacts["artifacts/formula_authority/cortex_service_type_mapping.json"],
        )

        self.assertFalse(gate["passed"], gate)
        self.assertIn("COST_DB_ROW_NOT_LITERAL", {row["code"] for row in gate["failures"]})


if __name__ == "__main__":
    unittest.main()
