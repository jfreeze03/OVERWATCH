from pathlib import Path
import importlib.util
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PERF_ROOT = ROOT / "perf_tests"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "overwatch_diagnostic_overhead_ab_tests",
        PERF_ROOT / "run_diagnostic_overhead_ab.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DiagnosticOverheadABTests(unittest.TestCase):
    def test_ab_payload_and_markdown_shape(self):
        runner = load_module()
        clean_report = {
            "summary": {
                "readiness_state": "PASS",
                "readiness_score": 100,
                "p95_ms": 9000,
                "p99_ms": 10000,
                "errors": 0,
                "skipped": 0,
                "diagnostic_steps": 0,
                "browser_navigation_timing": [{"metric": "responseStart", "p95_ms": 1000}],
                "browser_paint_timing": [{"metric": "first-contentful-paint", "p95_ms": 5000}],
                "server_phase_breakdown": [{"phase": "shell:total_render_app", "p95_ms": 100}],
            }
        }
        diagnostic_report = {
            "summary": {
                "readiness_state": "FAIL",
                "readiness_score": 57,
                "p95_ms": 14000,
                "p99_ms": 18000,
                "errors": 0,
                "skipped": 1,
                "diagnostic_steps": 100,
                "browser_navigation_timing": [{"metric": "responseStart", "p95_ms": 2000}],
                "browser_paint_timing": [{"metric": "first-contentful-paint", "p95_ms": 9000}],
                "server_phase_breakdown": [{"phase": "shell:total_render_app", "p95_ms": 150}],
            }
        }
        payload = runner.build_payload(
            run_id_prefix="AB_UNIT",
            url="http://localhost:8503/",
            clean={"run_id": "AB_CLEAN", "returncode": 0, "report_path": "clean.json", "report": clean_report},
            diagnostic={"run_id": "AB_DIAG", "returncode": 2, "report_path": "diag.json", "report": diagnostic_report},
        )

        self.assertEqual(payload["delta"]["p95_delta_ms"], 5000)
        self.assertEqual(payload["profiles"][0]["label"], "clean_scored")
        self.assertEqual(payload["profiles"][1]["label"], "full_diagnostic")

        with tempfile.TemporaryDirectory() as temp_dir:
            json_path, md_path = runner.write_reports(payload, output_dir=temp_dir)
            self.assertTrue(json_path.exists())
            markdown = md_path.read_text(encoding="utf-8")

        self.assertIn("Diagnostic Overhead A/B", markdown)
        self.assertIn("clean_scored", markdown)
        self.assertIn("full_diagnostic", markdown)


if __name__ == "__main__":
    unittest.main()
