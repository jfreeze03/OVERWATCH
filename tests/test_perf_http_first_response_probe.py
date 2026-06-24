import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PERF_ROOT = ROOT / "perf_tests"


def load_probe():
    spec = importlib.util.spec_from_file_location(
        "overwatch_http_first_response_probe_tests",
        PERF_ROOT / "http_first_response_probe.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class HttpFirstResponseProbeTests(unittest.TestCase):
    def test_perf_url_preserves_existing_query_params(self):
        probe = load_probe()

        url = probe.perf_url("http://localhost:8503/?foo=bar", run_id="HTTP_TEST", user_id=3)

        self.assertIn("foo=bar", url)
        self.assertIn("overwatch_perf_run_id=HTTP_TEST", url)
        self.assertIn("overwatch_perf_user=3", url)
        self.assertIn("overwatch_perf_iteration=1", url)

    def test_summarize_level_reports_concurrent_results(self):
        probe = load_probe()
        rows = [
            {"ok": True, "status_code": 200, "connect_ms": 1.0, "time_to_first_byte_ms": 10.0, "total_ms": 15.0},
            {"ok": True, "status_code": 200, "connect_ms": 2.0, "time_to_first_byte_ms": 20.0, "total_ms": 25.0},
            {"ok": False, "status_code": 0, "connect_ms": 0.0, "time_to_first_byte_ms": 0.0, "total_ms": 30.0},
        ]

        summary = probe.summarize_level(run_id="HTTP_TEST_U03", users=3, elapsed_sec=0.3, results=rows)

        self.assertEqual(summary["users"], 3)
        self.assertEqual(summary["requests"], 3)
        self.assertEqual(summary["ok"], 2)
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["time_to_first_byte_p95_ms"], 20.0)

    def test_write_reports_outputs_json_and_markdown(self):
        probe = load_probe()
        payload = {
            "run_id": "HTTP_TEST",
            "url": "http://localhost:8503/",
            "created_at": "2026-06-24T00:00:00+00:00",
            "levels": [
                probe.summarize_level(run_id="HTTP_TEST_U01", users=1, elapsed_sec=0.1, results=[
                    {"ok": True, "status_code": 200, "connect_ms": 1.0, "time_to_first_byte_ms": 2.0, "total_ms": 3.0}
                ])
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path, md_path = probe.write_reports(payload, output_dir=temp_dir)
            json_payload = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = md_path.read_text(encoding="utf-8")

        self.assertEqual(json_payload["run_id"], "HTTP_TEST")
        self.assertIn("HTTP First Response Probe", markdown)
        self.assertIn("TTFB p95", markdown)


if __name__ == "__main__":
    unittest.main()
