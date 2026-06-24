import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PERF_ROOT = ROOT / "perf_tests"


def load_ladder():
    spec = importlib.util.spec_from_file_location(
        "overwatch_initial_load_ladder_tests",
        PERF_ROOT / "run_initial_load_ladder.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class InitialLoadLadderTests(unittest.TestCase):
    def test_summarize_report_output_shape_is_deterministic(self):
        ladder = load_ladder()
        report = {
            "summary": {
                "readiness_state": "FAIL",
                "readiness_score": 57,
                "p50_ms": 100,
                "p95_ms": 200,
                "p99_ms": 300,
                "errors": 0,
                "browser_navigation_timing": [
                    {"metric": "responseStart", "p95_ms": 40},
                    {"metric": "domContentLoadedEventEnd", "p95_ms": 50},
                ],
                "browser_paint_timing": [
                    {"metric": "first-contentful-paint", "p95_ms": 60},
                ],
                "server_phase_breakdown": [
                    {"phase": "shell:total_render_app", "p95_ms": 70},
                    {"phase": "app_entry:import_shell", "p95_ms": 80},
                ],
            }
        }

        row = ladder.summarize_report(report, users=6, run_id="LADDER_U06")

        self.assertEqual(row["users"], 6)
        self.assertEqual(row["p95_ms"], 200)
        self.assertEqual(row["responseStart_p95_ms"], 40)
        self.assertEqual(row["domContentLoadedEventEnd_p95_ms"], 50)
        self.assertEqual(row["first_contentful_paint_p95_ms"], 60)
        self.assertEqual(row["server_shell_total_render_app_p95_ms"], 70)
        self.assertEqual(row["slowest_app_entry_phase"], "app_entry:import_shell")

    def test_write_reports_outputs_json_and_markdown(self):
        ladder = load_ladder()
        payload = ladder.build_payload(
            run_id_prefix="LADDER_TEST",
            url="http://localhost:8503/",
            rows=[
                {
                    "run_id": "LADDER_TEST_U01",
                    "users": 1,
                    "readiness_state": "PASS",
                    "p50_ms": 1,
                    "p95_ms": 2,
                    "p99_ms": 3,
                    "responseStart_p95_ms": 4,
                    "domContentLoadedEventEnd_p95_ms": 5,
                    "first_contentful_paint_p95_ms": 6,
                    "server_shell_total_render_app_p95_ms": 7,
                    "slowest_app_entry_phase": "app_entry:import_shell",
                    "slowest_app_entry_p95_ms": 8,
                }
            ],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path, md_path = ladder.write_reports(payload, output_dir=temp_dir)
            json_payload = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = md_path.read_text(encoding="utf-8")

        self.assertEqual(json_payload["run_id_prefix"], "LADDER_TEST")
        self.assertIn("Initial Load Ladder", markdown)
        self.assertIn("Diagnostic only", markdown)
        self.assertIn("responseStart p95", markdown)


if __name__ == "__main__":
    unittest.main()
