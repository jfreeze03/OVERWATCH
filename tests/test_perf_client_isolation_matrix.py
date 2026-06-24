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
        self.assertFalse(row["p99_tail_pass"])
        self.assertFalse(row["readiness_pass"])
        self.assertFalse(row["release_policy_candidate"])

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
        self.assertIn("Recommendation", markdown)
        self.assertEqual(payload["conclusion"]["recommendation"], "ramp12_tail_blocked")

    def test_client_isolation_recommends_ramp24_when_shared_longer_ramp_passes(self):
        runner = load_module()
        rows = [
            {
                "label": "shared_ramp12",
                "release_policy_candidate": False,
                "p99_ms": 21000,
                "readiness_score": 92,
            },
            {
                "label": "shared_ramp24",
                "release_policy_candidate": True,
                "p99_ms": 15000,
                "readiness_score": 100,
            },
            {
                "label": "per_user_ramp24",
                "release_policy_candidate": True,
                "p99_ms": 14000,
                "readiness_score": 100,
            },
        ]

        self.assertEqual(runner.recommend_release_policy(rows), "ramp24_passes")

    def test_client_isolation_recommends_per_user_when_only_browser_isolation_passes(self):
        runner = load_module()
        rows = [
            {"label": "shared_ramp12", "release_policy_candidate": False},
            {"label": "shared_ramp24", "release_policy_candidate": False},
            {"label": "per_user_ramp24", "release_policy_candidate": True},
        ]

        self.assertEqual(runner.recommend_release_policy(rows), "per_user_only_passes")


if __name__ == "__main__":
    unittest.main()
