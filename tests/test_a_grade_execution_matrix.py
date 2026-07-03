from pathlib import Path
import json
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class AGradeExecutionMatrixTests(unittest.TestCase):
    REQUIRED_GATES = [
        "artifacts/launch_readiness/first_paint_slo_gate_results.json",
        "artifacts/launch_readiness/ui_system_grade_gate_results.json",
        "artifacts/launch_readiness/action_click_gate_results.json",
        "artifacts/launch_readiness/import_laziness_gate_results.json",
        "artifacts/launch_readiness/ci_artifact_reality_gate_results.json",
        "artifacts/launch_readiness/metric_source_governance_gate_results.json",
    ]

    def _write_gate(self, root: Path, rel: str, passed: bool = True, **extra) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"passed": passed, "failure_count": 0 if passed else 1}
        payload.update(extra)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_matrix_passes_release_blocking_rows_and_reports_a_grade(self):
        from tools.contracts.a_grade_execution_matrix import build_a_grade_execution_matrix

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in self.REQUIRED_GATES:
                self._write_gate(root, rel)
            results = build_a_grade_execution_matrix(root)

        self.assertTrue(results["passed"], results.get("failures"))
        self.assertTrue(results["a_grade_ready"], results)

    def test_matrix_includes_release_blocking_metric_governance(self):
        from tools.contracts.a_grade_execution_matrix import build_a_grade_execution_matrix

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in self.REQUIRED_GATES:
                self._write_gate(root, rel)
            results = build_a_grade_execution_matrix(root)

        metric_rows = [
            row for row in results["rows"] if row["required_gate"].endswith("metric_source_governance_gate_results.json")
        ]
        self.assertEqual(len(metric_rows), 1)
        self.assertTrue(metric_rows[0]["release_blocking"])
        self.assertEqual(metric_rows[0]["target_dimension"], "packet-backed high-impact metrics")

    def test_release_blocking_failure_blocks_matrix(self):
        from tools.contracts.a_grade_execution_matrix import build_a_grade_execution_matrix

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in self.REQUIRED_GATES:
                self._write_gate(root, rel)
            self._write_gate(root, "artifacts/launch_readiness/first_paint_slo_gate_results.json", False)
            results = build_a_grade_execution_matrix(root)

        self.assertFalse(results["passed"])
        self.assertFalse(results["a_grade_ready"])

    def test_advisory_ui_debt_defers_a_grade_without_blocking_production(self):
        from tools.contracts.a_grade_execution_matrix import build_a_grade_execution_matrix

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in self.REQUIRED_GATES:
                self._write_gate(root, rel)
            self._write_gate(
                root,
                "artifacts/launch_readiness/ui_system_grade_gate_results.json",
                True,
                ui_a_grade_ready=False,
            )
            results = build_a_grade_execution_matrix(root)

        self.assertTrue(results["passed"], results.get("failures"))
        self.assertFalse(results["a_grade_ready"])
        self.assertEqual(results["a_grade_deferred_count"], 1)


if __name__ == "__main__":
    unittest.main()
