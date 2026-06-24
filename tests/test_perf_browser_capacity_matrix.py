from pathlib import Path
import importlib.util
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PERF_ROOT = ROOT / "perf_tests"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "overwatch_browser_capacity_matrix_tests",
        PERF_ROOT / "run_browser_capacity_matrix.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class BrowserCapacityMatrixTests(unittest.TestCase):
    def test_capacity_payload_and_markdown_shape(self):
        runner = load_module()
        report = {
            "summary": {
                "readiness_state": "PASS",
                "readiness_score": 100,
                "p95_ms": 5000,
                "p99_ms": 6000,
                "errors": 0,
                "browser_navigation_timing": [{"metric": "responseStart", "p95_ms": 900}],
                "browser_paint_timing": [{"metric": "first-contentful-paint", "p95_ms": 2500}],
                "frontend_dom_metrics": [{"metric": "node_count", "p95": 900}],
                "frontend_resource_timing": [{"initiator_type": "script", "count_p95": 3}],
                "resource_samples": [{"cpu_percent": 10.0, "memory_percent": 60.0, "browser_child_process_count": 4}],
            }
        }
        row = runner.summarize_report(
            report,
            run_id="CAP_UNIT",
            users=3,
            viewport="1280x800",
            chromium_variant="default",
            returncode=0,
        )

        self.assertEqual(row["first_contentful_paint_p95_ms"], 2500)
        self.assertEqual(row["dom_node_count_p95"], 900)
        self.assertEqual(row["browser_child_process_count"], 4)

        payload = runner.build_payload(
            run_id_prefix="CAP_UNIT",
            url="http://localhost:8503/",
            rows=[row],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path, md_path = runner.write_reports(payload, output_dir=temp_dir)
            self.assertTrue(json_path.exists())
            markdown = md_path.read_text(encoding="utf-8")

        self.assertIn("Browser Capacity Matrix", markdown)
        self.assertIn("1280x800", markdown)


if __name__ == "__main__":
    unittest.main()
