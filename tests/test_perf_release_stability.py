from pathlib import Path
import importlib.util
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PERF_ROOT = ROOT / "perf_tests"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "overwatch_release_stability_tests",
        PERF_ROOT / "run_release_stability.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ReleaseStabilityTests(unittest.TestCase):
    def test_stability_payload_and_markdown_shape(self):
        runner = load_module()
        rows = [
            {
                "run_id": "STAB_01",
                "readiness_state": "WATCH",
                "readiness_score": 92,
                "p95_ms": 9900,
                "p99_ms": 21000,
                "max_ms": 23000,
                "errors": 0,
                "skipped": 0,
                "slowest_initial_load": {"elapsed_ms": 23000},
                "readiness_penalties": [{"type": "p99_tail"}],
            },
            {
                "run_id": "STAB_02",
                "readiness_state": "PASS",
                "readiness_score": 100,
                "p95_ms": 8700,
                "p99_ms": 12000,
                "max_ms": 13000,
                "errors": 0,
                "skipped": 0,
                "slowest_initial_load": {"elapsed_ms": 13000},
                "readiness_penalties": [],
            },
            {
                "run_id": "STAB_03",
                "readiness_state": "WATCH",
                "readiness_score": 92,
                "p95_ms": 9800,
                "p99_ms": 19000,
                "max_ms": 21000,
                "errors": 0,
                "skipped": 0,
                "slowest_initial_load": {"elapsed_ms": 21000},
                "readiness_penalties": [{"type": "p99_tail"}],
            },
        ]

        payload = runner.build_payload(
            run_id_prefix="STAB_UNIT",
            url="http://localhost:8503/",
            profile="perf_tests/profiles/12_power_users_release_scored.json",
            rows=rows,
        )

        self.assertEqual(payload["summary"]["median_p95_ms"], 9800)
        self.assertEqual(payload["summary"]["median_readiness_score"], 92)
        self.assertEqual(payload["summary"]["pass_count"], 1)
        self.assertEqual(payload["summary"]["worst_p99_ms"], 21000)
        self.assertEqual(payload["summary"]["worst_readiness_score"], 92)
        self.assertEqual(payload["summary"]["p99_tail_runs"], 2)
        self.assertEqual(payload["summary"]["conclusion"], "stable_watch_tail")

        with tempfile.TemporaryDirectory() as temp_dir:
            json_path, md_path = runner.write_reports(payload, output_dir=temp_dir)
            self.assertTrue(json_path.exists())
            markdown = md_path.read_text(encoding="utf-8")

        self.assertIn("Clean Release Stability", markdown)
        self.assertIn("Median p95/p99/max", markdown)
        self.assertIn("Worst p95/p99/max", markdown)
        self.assertIn("Conclusion", markdown)
        self.assertIn("STAB_01", markdown)


if __name__ == "__main__":
    unittest.main()
