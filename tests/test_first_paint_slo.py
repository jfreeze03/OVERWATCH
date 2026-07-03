from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FirstPaintSloTests(unittest.TestCase):
    def _rows(self, *, elapsed_ms: int = 50, warm_queries: int = 0):
        from tools.contracts.first_paint_slo import PRIMARY_SECTIONS

        return {
            "rows": [
                {
                    "section": section,
                    "workflow": "Overview",
                    "elapsed_ms": elapsed_ms,
                    "cold_first_paint_packet_query_count": 1,
                    "warm_first_paint_query_count": warm_queries,
                    "evidence_query_count": 0,
                    "account_usage_count": 0,
                    "detail_query_count": 0,
                    "cost_workbench_query_count": 0,
                    "query_search_query_count": 0,
                    "direct_sql_count": 0,
                    "passed": True,
                }
                for section in PRIMARY_SECTIONS
            ]
        }

    def test_primary_packet_rows_under_slo_pass(self):
        from tools.contracts.first_paint_slo import evaluate_first_paint_slo

        gate = evaluate_first_paint_slo(self._rows(), packet_size_payload={"max_packet_bytes": 42_000})

        self.assertTrue(gate["passed"], gate.get("failures"))
        self.assertTrue(gate["first_paint_slo_passed"])

    def test_missing_packet_size_fails(self):
        from tools.contracts.first_paint_slo import evaluate_first_paint_slo

        gate = evaluate_first_paint_slo(self._rows())

        self.assertFalse(gate["passed"])
        self.assertIn("packet size", " ".join(row["failure_reason"] for row in gate["failures"]))

    def test_slow_or_warm_query_row_fails(self):
        from tools.contracts.first_paint_slo import evaluate_first_paint_slo

        gate = evaluate_first_paint_slo(self._rows(elapsed_ms=2_000, warm_queries=1), packet_size_payload={"max_packet_bytes": 42_000})

        self.assertFalse(gate["passed"])
        reasons = " ".join(row["failure_reason"] for row in gate["failures"])
        self.assertIn("1.5s", reasons)
        self.assertIn("warm", reasons)


if __name__ == "__main__":
    unittest.main()
