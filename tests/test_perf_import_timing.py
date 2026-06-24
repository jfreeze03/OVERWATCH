import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PERF_ROOT = ROOT / "perf_tests"


def load_import_timing():
    spec = importlib.util.spec_from_file_location(
        "overwatch_import_timing_tests",
        PERF_ROOT / "import_timing.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ImportTimingTests(unittest.TestCase):
    def test_run_import_timing_returns_summary_and_rows(self):
        timing = load_import_timing()

        payload = timing.run_import_timing(["json"], baseline_modules=["math"], timeout_sec=10)

        self.assertEqual(payload["summary"]["module_count"], 1)
        self.assertEqual(payload["summary"]["ok"], 1)
        self.assertEqual(payload["summary"]["failed"], 0)
        self.assertEqual(payload["summary"]["baseline_module_count"], 1)
        self.assertEqual(payload["baseline_modules"][0]["module"], "math")
        self.assertEqual(payload["target_modules"][0]["module"], "json")
        self.assertTrue(payload["target_modules"][0]["ok"])
        self.assertIn("baseline_adjusted_ms", payload["target_modules"][0])
        self.assertGreaterEqual(payload["target_modules"][0]["elapsed_ms"], 0)

    def test_importtime_parser_returns_cumulative_rows(self):
        timing = load_import_timing()
        stderr = "\n".join([
            "import time: self [us] | cumulative | imported package",
            "import time:       111 |        222 | json",
            "import time:       333 |        444 | collections",
        ])

        rows = timing._parse_importtime(stderr, target_module="json")

        self.assertEqual(rows[0]["target_module"], "json")
        self.assertEqual(rows[0]["import"], "collections")
        self.assertEqual(rows[0]["cumulative_ms"], 0.44)

    def test_write_reports_outputs_json_and_markdown(self):
        timing = load_import_timing()
        payload = {
            "baseline_modules": [{
                "module": "math",
                "ok": True,
                "elapsed_ms": 0.5,
                "process_wall_ms": 10.0,
                "error": "",
            }],
            "target_modules": [{
                "module": "json",
                "ok": True,
                "elapsed_ms": 1.23,
                "baseline_adjusted_ms": 0.73,
                "process_wall_ms": 12.34,
                "error": "",
            }],
            "modules": [{
                "module": "json",
                "ok": True,
                "elapsed_ms": 1.23,
                "baseline_adjusted_ms": 0.73,
                "process_wall_ms": 12.34,
                "error": "",
            }],
            "summary": {
                "module_count": 1,
                "ok": 1,
                "failed": 0,
                "max_ms": 1.23,
                "avg_ms": 1.23,
                "slowest_module": "json",
                "slowest_ms": 1.23,
                "baseline_module_count": 1,
                "baseline_slowest_module": "math",
                "baseline_slowest_ms": 0.5,
            },
            "baseline_summary": {
                "module_count": 1,
                "ok": 1,
                "failed": 0,
                "max_ms": 0.5,
                "avg_ms": 0.5,
                "slowest_module": "math",
                "slowest_ms": 0.5,
            },
            "target_summary": {
                "module_count": 1,
                "ok": 1,
                "failed": 0,
                "max_ms": 1.23,
                "avg_ms": 1.23,
                "slowest_module": "json",
                "slowest_ms": 1.23,
            },
            "top_cumulative_imports": [{
                "target_module": "json",
                "import": "json",
                "cumulative_ms": 1.0,
                "self_ms": 0.5,
            }],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path, md_path = timing.write_reports(payload, run_id="IMPORT_TEST", output_dir=temp_dir)

            json_payload = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = md_path.read_text(encoding="utf-8")

        self.assertEqual(json_payload["run_id"], "IMPORT_TEST")
        self.assertEqual(json_payload["summary"]["slowest_module"], "json")
        self.assertEqual(json_payload["baseline_modules"][0]["module"], "math")
        self.assertIn("OVERWATCH Import Timing IMPORT_TEST", markdown)
        self.assertIn("Baseline Import Timings", markdown)
        self.assertIn("Target Module Timings", markdown)
        self.assertIn("Top Cumulative Import Offenders", markdown)
        self.assertIn("| json | yes | 1.23 | 0.73 | 12.34 |  |", markdown)


if __name__ == "__main__":
    unittest.main()
