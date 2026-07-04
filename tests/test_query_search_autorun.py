from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class QuerySearchAutorunTests(unittest.TestCase):
    def _rows(self):
        return [
            {"case": "render_no_click", "snowflake_execution_count": 0},
            {"case": "text_contains_no_autorun", "snowflake_execution_count": 0},
            {"case": "warehouse_prefill_no_autorun", "snowflake_execution_count": 0},
            {"case": "account_usage_fallback_unconfirmed", "snowflake_execution_count": 0},
            {
                "case": "exact_query_id",
                "snowflake_execution_count": 1,
                "max_rows": 1,
                "observed_boundaries": {"query_search_exact": 1},
            },
            {
                "case": "query_signature",
                "snowflake_execution_count": 1,
                "max_rows": 200,
                "observed_boundaries": {"query_search_exact": 1},
            },
            {
                "case": "account_usage_fallback_confirmed",
                "snowflake_execution_count": 1,
                "observed_boundaries": {"query_search_broad_explicit": 1},
            },
            {
                "case": "text_contains_explicit_search",
                "snowflake_execution_count": 1,
                "observed_boundaries": {"query_search_broad_explicit": 1},
            },
        ]

    def test_query_search_autorun_contract_passes_safe_cases(self):
        from tools.contracts.query_search_autorun import evaluate_query_search_autorun

        results = evaluate_query_search_autorun(self._rows(), root=ROOT)

        self.assertTrue(results["passed"], results.get("failures"))
        self.assertEqual(results["query_search_broad_autorun_count"], 0)

    def test_warehouse_prefill_query_fails(self):
        from tools.contracts.query_search_autorun import evaluate_query_search_autorun

        rows = self._rows()
        rows[2]["snowflake_execution_count"] = 1
        results = evaluate_query_search_autorun(rows, root=ROOT)

        self.assertFalse(results["passed"])
        self.assertEqual(results["query_search_broad_autorun_count"], 1)


if __name__ == "__main__":
    unittest.main()
