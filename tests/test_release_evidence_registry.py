from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.contracts.release_evidence_registry import (
    REGISTRY_ROWS,
    RELEASE_EVIDENCE_REGISTRY_GATE_REL,
    build_release_evidence_registry_results,
    iter_required_release_artifacts,
    registry_gate_specs,
    registry_row_for_gate,
    required_artifacts_for_consumer,
    write_release_evidence_registry_artifacts,
)


class ReleaseEvidenceRegistryTests(unittest.TestCase):
    commit = "abc123"

    def _write_json(self, root: Path, rel: str, payload: object) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _seed_registered_artifacts(self, root: Path) -> None:
        for spec in REGISTRY_ROWS:
            self._write_json(
                root,
                spec.artifact_path,
                {
                    "source": spec.gate_id,
                    "producer": spec.producer,
                    "producer_signature": "sig",
                    "commit_sha": self.commit,
                    "passed": True,
                    "failure_count": 0,
                    "rows": [{"row_id": spec.gate_id, "passed": True}],
                    "raw_sql_included": False,
                },
            )

    def test_registered_artifacts_emit_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_registered_artifacts(root)
            with (
                patch("tools.contracts.release_evidence_registry._git_commit", return_value=self.commit),
                patch("tools.contracts.release_evidence_registry._consumer_has_artifact", return_value=True),
            ):
                artifacts = write_release_evidence_registry_artifacts(root)

        self.assertTrue(artifacts[RELEASE_EVIDENCE_REGISTRY_GATE_REL]["passed"], artifacts[RELEASE_EVIDENCE_REGISTRY_GATE_REL])

    def test_missing_required_artifact_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_registered_artifacts(root)
            (root / REGISTRY_ROWS[0].artifact_path).unlink()
            with (
                patch("tools.contracts.release_evidence_registry._git_commit", return_value=self.commit),
                patch("tools.contracts.release_evidence_registry._consumer_has_artifact", return_value=True),
            ):
                results = build_release_evidence_registry_results(root)

        self.assertFalse(results["passed"])
        self.assertGreater(results["missing_artifact_count"], 0)

    def test_unregistered_release_blocking_artifact_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_registered_artifacts(root)
            self._write_json(
                root,
                "artifacts/launch_readiness/new_gate_results.json",
                {
                    "release_blocking": True,
                    "passed": True,
                    "producer": "new",
                    "producer_signature": "sig",
                    "commit_sha": self.commit,
                    "rows": [{"row_id": "new", "passed": True}],
                    "raw_sql_included": False,
                },
            )
            with (
                patch("tools.contracts.release_evidence_registry._git_commit", return_value=self.commit),
                patch("tools.contracts.release_evidence_registry._consumer_has_artifact", return_value=True),
            ):
                results = build_release_evidence_registry_results(root)

        self.assertFalse(results["passed"])
        self.assertEqual(results["unregistered_artifact_count"], 1)

    def test_consumer_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_registered_artifacts(root)
            with (
                patch("tools.contracts.release_evidence_registry._git_commit", return_value=self.commit),
                patch("tools.contracts.release_evidence_registry._consumer_has_artifact", return_value=False),
            ):
                results = build_release_evidence_registry_results(root)

        self.assertFalse(results["passed"])
        self.assertGreater(results["consumer_mismatch_count"], 0)

    def test_in_progress_summary_artifact_does_not_self_fail_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_registered_artifacts(root)
            for spec in REGISTRY_ROWS:
                if not spec.artifact_required:
                    self._write_json(
                        root,
                        spec.artifact_path,
                        {
                            "source": spec.gate_id,
                            "producer": spec.producer,
                            "producer_signature": "sig",
                            "commit_sha": self.commit,
                            "passed": False,
                            "failure_count": 9,
                            "raw_sql_included": False,
                        },
                    )
            with (
                patch("tools.contracts.release_evidence_registry._git_commit", return_value=self.commit),
                patch("tools.contracts.release_evidence_registry._consumer_has_artifact", return_value=True),
            ):
                results = build_release_evidence_registry_results(root)

        self.assertTrue(results["passed"], results["failures"])

    def test_required_artifact_helpers_are_registry_backed(self) -> None:
        required = iter_required_release_artifacts(include_support_artifacts=False)
        self.assertEqual(
            {
                row.artifact_path
                for row in REGISTRY_ROWS
                if row.artifact_required and row.proof_rows_required
            },
            set(required),
        )
        specs = registry_gate_specs()
        self.assertEqual({row.gate_id for row in REGISTRY_ROWS}, {str(row["gate_id"]) for row in specs})
        launch_required = required_artifacts_for_consumer("launch_readiness.py")
        self.assertIn("artifacts/launch_readiness/runtime_event_ledger_gate_results.json", launch_required)
        self.assertIn("artifacts/launch_readiness/metric_source_governance_gate_results.json", launch_required)
        self.assertNotIn("artifacts/launch_readiness/metric_source_governance_gate_results.json", required)
        self.assertNotIn("artifacts/launch_readiness/artifact_integrity_gate_results.json", required)
        self.assertNotIn("artifacts/launch_readiness/release_evidence_registry_gate_results.json", required)

    def test_registry_row_for_gate_resolves_id_and_artifact(self) -> None:
        by_id = registry_row_for_gate("runtime_event_ledger")
        by_artifact = registry_row_for_gate("artifacts/launch_readiness/runtime_event_ledger_gate_results.json")

        self.assertEqual(by_id["gate_id"], "runtime_event_ledger")
        self.assertEqual(by_artifact["gate_id"], "runtime_event_ledger")
        self.assertIn("launch_readiness.py", by_id["required_consumers"])


if __name__ == "__main__":
    unittest.main()
