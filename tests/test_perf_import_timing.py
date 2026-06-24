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

        payload = timing.run_import_timing(["json"], timeout_sec=10)

        self.assertEqual(payload["summary"]["module_count"], 1)
        self.assertEqual(payload["summary"]["ok"], 1)
        self.assertEqual(payload["summary"]["failed"], 0)
        self.assertEqual(payload["modules"][0]["module"], "json")
        self.assertTrue(payload["modules"][0]["ok"])
        self.assertGreaterEqual(payload["modules"][0]["elapsed_ms"], 0)

    def test_write_reports_outputs_json_and_markdown(self):
        timing = load_import_timing()
        payload = {
            "modules": [{
                "module": "json",
                "ok": True,
                "elapsed_ms": 1.23,
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
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path, md_path = timing.write_reports(payload, run_id="IMPORT_TEST", output_dir=temp_dir)

            json_payload = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = md_path.read_text(encoding="utf-8")

        self.assertEqual(json_payload["run_id"], "IMPORT_TEST")
        self.assertEqual(json_payload["summary"]["slowest_module"], "json")
        self.assertIn("OVERWATCH Import Timing IMPORT_TEST", markdown)
        self.assertIn("| json | yes | 1.23 | 12.34 |  |", markdown)


if __name__ == "__main__":
    unittest.main()
