from pathlib import Path
import importlib.util
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PERF_ROOT = ROOT / "perf_tests"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "overwatch_client_isolation_matrix_tests",
        PERF_ROOT / "run_client_isolation_matrix.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ClientIsolationMatrixTests(unittest.TestCase):
    def test_client_isolation_payload_and_markdown_shape(self):
        runner = load_module()
        report = {
            "summary": {
                "readiness_state": "WATCH",
                "readiness_score": 92,
                "p95_ms": 9000,
                "p99_ms": 21000,
                "max_ms": 23000,
                "errors": 0,
                "skipped_buttons": 0,
                "in_run_tail_captures": [{"user_id": 8}],
                "resource_samples": [{"cpu_percent": 75.0, "memory_percent": 80.0, "browser_child_process_count": 12}],
            }
        }
        case = {"label": "shared_ramp12", "browser_launch_mode": "shared", "ramp_seconds": 12.0}
        row = runner.summarize_report(report, run_id="CLIENT_UNIT", case=case, returncode=2)

        self.assertEqual(row["label"], "shared_ramp12")
        self.assertEqual(row["in_run_tail_capture_count"], 1)
        self.assertEqual(row["browser_child_process_count"], 12)

        payload = runner.build_payload(
            run_id_prefix="CLIENT_UNIT",
            url="http://localhost:8503/",
            rows=[row],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path, md_path = runner.write_reports(payload, output_dir=temp_dir)
            self.assertTrue(json_path.exists())
            markdown = md_path.read_text(encoding="utf-8")

        self.assertIn("Client Isolation Matrix", markdown)
        self.assertIn("shared_ramp12", markdown)
        self.assertIn("Tail captures", markdown)


if __name__ == "__main__":
    unittest.main()
