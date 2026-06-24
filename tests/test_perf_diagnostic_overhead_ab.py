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
        runs = []
        for repeat in (1, 2):
            clean_row = runner.summarize_live_report(
                clean_report,
                label="clean_scored",
                run_id=f"AB_R{repeat:02d}_CLEAN",
                returncode=0,
            )
            clean_row.update({"repeat": repeat, "warmup": False, "report_path": "clean.json"})
            runs.append(clean_row)
            diagnostic_row = runner.summarize_live_report(
                diagnostic_report,
                label="full_diagnostic",
                run_id=f"AB_R{repeat:02d}_DIAGNOSTIC",
                returncode=2,
            )
            diagnostic_row.update({"repeat": repeat, "warmup": False, "report_path": "diag.json"})
            runs.append(diagnostic_row)
        payload = runner.build_payload(
            run_id_prefix="AB_UNIT",
            url="http://localhost:8503/",
            runs=runs,
            repeats=2,
            warmup=True,
            order="alternating",
        )

        self.assertEqual(payload["delta"]["median_p95_delta_ms"], 5000)
        self.assertEqual(payload["profiles"][0]["label"], "clean_scored")
        self.assertEqual(payload["profiles"][1]["label"], "full_diagnostic")
        self.assertEqual(payload["profiles"][0]["runs"], 2)
        self.assertEqual(len(payload["run_order"]), 4)

        with tempfile.TemporaryDirectory() as temp_dir:
            json_path, md_path = runner.write_reports(payload, output_dir=temp_dir)
            self.assertTrue(json_path.exists())
            markdown = md_path.read_text(encoding="utf-8")

        self.assertIn("Diagnostic Overhead A/B", markdown)
        self.assertIn("clean_scored", markdown)
        self.assertIn("full_diagnostic", markdown)
        self.assertIn("Run Order", markdown)

    def test_ab_plans_warmup_and_alternating_order(self):
        runner = load_module()

        planned = runner.plan_run_order(repeats=2, warmup=True, order="alternating")

        self.assertTrue(planned[0]["warmup"])
        self.assertEqual(planned[0]["label"], "clean_scored")
        self.assertEqual(planned[1]["label"], "full_diagnostic")
        self.assertEqual(
            [row["label"] for row in planned if not row["warmup"]],
            ["clean_scored", "full_diagnostic", "full_diagnostic", "clean_scored"],
        )


if __name__ == "__main__":
    unittest.main()
