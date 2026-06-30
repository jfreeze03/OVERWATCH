from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class DeterministicStreamlitRenderTests(unittest.TestCase):
    def test_primary_sections_render_from_runtime_payloads(self):
        from tools.contracts.deterministic_streamlit_render import (
            build_deterministic_streamlit_render_results,
            evaluate_deterministic_render_gate,
        )

        payloads = {
            "artifacts/full_app_validation/view_results.json": [
                {
                    "section": section,
                    "workflow": "Overview",
                    "first_paint": {"observed_packet_queries": 1},
                    "elapsed_ms": 10,
                }
                for section in (
                    "Executive Landing",
                    "DBA Control Room",
                    "Alert Center",
                    "Cost & Contract",
                    "Workload Operations",
                    "Security Monitoring",
                )
            ],
            "artifacts/full_app_validation/rendered_fragments.json": [
                {"section": section, "workflow": "Overview", "text": f"{section} summary board"}
                for section in (
                    "Executive Landing",
                    "DBA Control Room",
                    "Alert Center",
                    "Cost & Contract",
                    "Workload Operations",
                    "Security Monitoring",
                )
            ],
            "artifacts/full_app_validation/query_search_results.json": [
                {"case": "render_no_click", "passed": True}
            ],
            "artifacts/full_app_validation/stress_results.json": [
                {"case": "advanced_scope_filters", "passed": True}
            ],
        }
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            results = build_deterministic_streamlit_render_results(Path(tmp), payloads)
            gate = evaluate_deterministic_render_gate(results)

        self.assertTrue(results["passed"], results)
        self.assertTrue(gate["passed"], gate)
        self.assertEqual(results["synthetic_fallback_count"], 0)
        self.assertTrue(all(row["source"] == "deterministic_streamlit_rendered" for row in results["rows"]))

    def test_missing_runtime_fragment_is_not_synthetic_success(self):
        from tools.contracts.deterministic_streamlit_render import build_deterministic_streamlit_render_results

        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            results = build_deterministic_streamlit_render_results(Path(tmp), payloads={})

        self.assertFalse(results["passed"])
        self.assertGreater(results["synthetic_fallback_count"], 0)
        self.assertTrue(any(not row["rendered"] for row in results["rows"]))


if __name__ == "__main__":
    unittest.main()
