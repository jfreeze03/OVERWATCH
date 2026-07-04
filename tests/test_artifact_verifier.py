from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
import unittest

from tools.contracts.artifact_verifier import (
    ARTIFACT_HASHES_REL,
    ARTIFACT_INTEGRITY_GATE_REL,
    ARTIFACT_INTEGRITY_RESULTS_REL,
    build_artifact_integrity_gate,
    build_artifact_integrity_results,
    verify_artifact,
    write_artifact_integrity_artifacts,
)


class ArtifactVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.rel = "artifacts/full_app_validation/example_results.json"
        self.commit_sha = "abc123"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_json(self, rel: str, payload: object) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _sha(self, rel: str) -> str:
        return hashlib.sha256((self.root / rel).read_bytes()).hexdigest()

    def _write_hashes(self, *rels: str, override_sha: str = "") -> None:
        hashes = [
            {
                "path": rel,
                "sha256": override_sha or self._sha(rel),
            }
            for rel in rels
        ]
        self._write_json(
            ARTIFACT_HASHES_REL,
            {
                "source": "release_candidate_artifact_hashes",
                "producer": "test",
                "producer_signature": "sig",
                "passed": True,
                "failure_count": 0,
                "hashes": hashes,
                "raw_sql_included": False,
            },
        )

    def _artifact(self, **overrides: object) -> dict[str, object]:
        row = {
            "row_id": "row-1",
            "producer": "runtime",
            "producer_signature": "sig",
            "commit_sha": self.commit_sha,
            "passed": True,
            "raw_sql_included": False,
        }
        payload: dict[str, object] = {
            "source": "example_results",
            "producer": "runtime",
            "producer_signature": "sig",
            "commit_sha": self.commit_sha,
            "passed": True,
            "failure_count": 0,
            "rows": [row],
            "raw_sql_included": False,
        }
        payload.update(overrides)
        return payload

    def _write_valid_artifact(self) -> None:
        self._write_json(self.rel, self._artifact())
        self._write_hashes(self.rel)

    def test_producer_backed_artifact_passes(self) -> None:
        self._write_valid_artifact()

        row = verify_artifact(
            self.root,
            self.rel,
            expected_commit_sha=self.commit_sha,
            hash_index={self.rel: self._sha(self.rel)},
        )

        self.assertTrue(row["passed"], row["failure_reason"])

    def test_missing_artifact_fails(self) -> None:
        self._write_json(ARTIFACT_HASHES_REL, {"hashes": []})

        results = build_artifact_integrity_results(
            self.root,
            required_artifacts=[self.rel],
            expected_commit_sha=self.commit_sha,
        )

        self.assertFalse(results["passed"])
        self.assertEqual(results["missing_artifact_count"], 1)

    def test_malformed_json_fails(self) -> None:
        path = self.root / self.rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{bad", encoding="utf-8")
        self._write_json(ARTIFACT_HASHES_REL, {"hashes": [{"path": self.rel, "sha256": self._sha(self.rel)}]})

        results = build_artifact_integrity_results(
            self.root,
            required_artifacts=[self.rel],
            expected_commit_sha=self.commit_sha,
        )

        self.assertFalse(results["passed"])
        self.assertIn("malformed", results["failures"][0]["failure_reason"])

    def test_missing_producer_signature_fails(self) -> None:
        payload = self._artifact(producer_signature="")
        self._write_json(self.rel, payload)
        self._write_hashes(self.rel)

        results = build_artifact_integrity_results(
            self.root,
            required_artifacts=[self.rel],
            expected_commit_sha=self.commit_sha,
        )

        self.assertFalse(results["passed"])
        self.assertIn("missing producer_signature", results["failures"][0]["failure_reason"])

    def test_wrong_commit_fails(self) -> None:
        payload = self._artifact(commit_sha="old")
        payload["rows"] = [
            {
                "row_id": "row-1",
                "producer": "runtime",
                "producer_signature": "sig",
                "commit_sha": "old",
                "passed": True,
                "raw_sql_included": False,
            }
        ]
        self._write_json(self.rel, payload)
        self._write_hashes(self.rel)

        results = build_artifact_integrity_results(
            self.root,
            required_artifacts=[self.rel],
            expected_commit_sha=self.commit_sha,
        )

        self.assertFalse(results["passed"])
        self.assertIn("commit_sha mismatch", results["failures"][0]["failure_reason"])

    def test_boolean_only_artifact_fails(self) -> None:
        self._write_json(
            self.rel,
            {
                "producer": "runtime",
                "producer_signature": "sig",
                "commit_sha": self.commit_sha,
                "passed": True,
                "failure_count": 0,
                "raw_sql_included": False,
            },
        )
        self._write_hashes(self.rel)

        results = build_artifact_integrity_results(
            self.root,
            required_artifacts=[self.rel],
            expected_commit_sha=self.commit_sha,
        )

        self.assertFalse(results["passed"])
        self.assertIn("row-level proof missing", results["failures"][0]["failure_reason"])

    def test_raw_sql_flag_fails(self) -> None:
        self._write_json(self.rel, self._artifact(raw_sql_included=True))
        self._write_hashes(self.rel)

        results = build_artifact_integrity_results(
            self.root,
            required_artifacts=[self.rel],
            expected_commit_sha=self.commit_sha,
        )

        self.assertFalse(results["passed"])
        self.assertIn("raw_sql_included=true", results["failures"][0]["failure_reason"])

    def test_missing_hash_manifest_entry_fails(self) -> None:
        self._write_json(self.rel, self._artifact())
        self._write_json(ARTIFACT_HASHES_REL, {"hashes": []})

        results = build_artifact_integrity_results(
            self.root,
            required_artifacts=[self.rel],
            expected_commit_sha=self.commit_sha,
        )

        self.assertFalse(results["passed"])
        self.assertIn("artifact hash is missing", results["failures"][0]["failure_reason"])

    def test_hash_mismatch_fails(self) -> None:
        self._write_json(self.rel, self._artifact())
        self._write_hashes(self.rel, override_sha="0" * 64)

        results = build_artifact_integrity_results(
            self.root,
            required_artifacts=[self.rel],
            expected_commit_sha=self.commit_sha,
        )

        self.assertFalse(results["passed"])
        self.assertEqual(results["hash_mismatch_count"], 1)

    def test_forbidden_token_fails(self) -> None:
        self._write_json(self.rel, self._artifact(visible_text="SNOWFLAKE.ACCOUNT_USAGE.CREDENTIALS"))
        self._write_hashes(self.rel)

        results = build_artifact_integrity_results(
            self.root,
            required_artifacts=[self.rel],
            expected_commit_sha=self.commit_sha,
        )

        self.assertFalse(results["passed"])
        self.assertGreaterEqual(results["forbidden_token_count"], 1)

    def test_gate_and_writer_emit_producer_backed_rows(self) -> None:
        self._write_valid_artifact()

        artifacts = write_artifact_integrity_artifacts(
            self.root,
            required_artifacts=[self.rel],
        )
        gate = artifacts[ARTIFACT_INTEGRITY_GATE_REL]

        self.assertTrue((self.root / ARTIFACT_INTEGRITY_RESULTS_REL).exists())
        self.assertTrue((self.root / ARTIFACT_INTEGRITY_GATE_REL).exists())
        self.assertTrue(gate["passed"], gate["failures"])
        self.assertEqual(gate["verified_artifact_count"], 1)
        self.assertTrue(gate["rows"][0]["producer_signature"])

    def test_gate_refuses_failed_result_rows(self) -> None:
        results = {
            "producer": "artifact_verifier",
            "producer_signature": "sig",
            "commit_sha": self.commit_sha,
            "passed": False,
            "failure_count": 1,
            "verified_artifact_count": 1,
            "rows": [
                {
                    "artifact_path": self.rel,
                    "passed": False,
                    "failure_reason": "bad",
                }
            ],
            "raw_sql_included": False,
        }

        gate = build_artifact_integrity_gate(results)

        self.assertFalse(gate["passed"])
        self.assertEqual(gate["failure_count"], 1)


if __name__ == "__main__":
    unittest.main()
