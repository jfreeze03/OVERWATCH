from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _write(path: Path, text: str = "{}") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_required_release_artifacts(
    root: Path,
    *,
    commit_sha: str = "local",
    hard_gate_failure_count: int = 0,
) -> None:
    artifacts = root / "artifacts"
    _write(
        artifacts / "release_candidate" / "release_candidate_summary.json",
        json.dumps(
            {
                "commit_sha": commit_sha,
                "production_deployable": hard_gate_failure_count == 0,
                "hard_gate_failure_count": hard_gate_failure_count,
            }
        ),
    )
    _write(
        artifacts / "launch_readiness" / "launch_readiness_summary.json",
        json.dumps(
            {
                "commit_sha": commit_sha,
                "all_passed": hard_gate_failure_count == 0,
                "failure_count": hard_gate_failure_count,
            }
        ),
    )
    _write(
        artifacts / "release_candidate" / "artifact_manifest.json",
        json.dumps({
            "commit_sha": commit_sha,
            "files": [{"path": "artifacts/launch_readiness/launch_readiness_summary.json", "sha256": "abc"}],
        }),
    )
    _write(
        artifacts / "release_candidate" / "artifact_hashes.json",
        json.dumps({
            "commit_sha": commit_sha,
            "hashes": [{"path": "artifacts/launch_readiness/launch_readiness_summary.json", "sha256": "abc"}],
        }),
    )


class CiArtifactRealityTests(unittest.TestCase):
    def test_local_signed_artifact_bundle_passes_without_github_metadata(self):
        from tools.contracts.ci_artifact_reality import (
            LOCAL_ARTIFACT_PROOF_REL,
            build_ci_artifact_reality_results,
            evaluate_ci_artifact_reality_gate,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_required_release_artifacts(root)

            results = build_ci_artifact_reality_results(
                root,
                profile="internal_live",
                ci_run_review={"github_actions": False},
                upload_review={"uploaded_artifact_names": []},
                artifact_review={"stale_artifacts": []},
                missing_payloads=[],
                release_reconciliation={"passed": True},
            )
            gate = evaluate_ci_artifact_reality_gate(results)
            proof = json.loads((root / LOCAL_ARTIFACT_PROOF_REL).read_text(encoding="utf-8"))

        self.assertTrue(results["passed"], results)
        self.assertTrue(results["local_artifact_signature"], results)
        self.assertEqual(results["proof_type"], "local_artifact_reality")
        self.assertEqual(results["signature"], results["local_artifact_signature"])
        self.assertTrue(results["producer_signature"], results)
        self.assertEqual(results["artifact_hash_manifest"], "artifacts/release_candidate/artifact_hashes.json")
        self.assertEqual(
            results["summary_paths"],
            [
                "artifacts/release_candidate/release_candidate_summary.json",
                "artifacts/launch_readiness/launch_readiness_summary.json",
            ],
        )
        self.assertEqual(results["summary_hard_gate_failure_count"], 0)
        self.assertEqual(proof["proof_type"], "local_artifact_reality")
        self.assertEqual(proof["signature"], proof["local_artifact_signature"])
        self.assertEqual(proof["hard_gate_failure_count"], 0)
        self.assertFalse(proof["raw_sql_included"])
        self.assertGreater(results["artifact_hash_count"], 0, results)
        self.assertGreater(results["artifact_manifest_file_count"], 0, results)
        self.assertTrue(gate["passed"], gate)
        self.assertEqual(gate["proof_type"], "local_artifact_reality")
        self.assertEqual(gate["signature"], results["signature"])
        self.assertEqual(gate["hard_gate_failure_count"], 0)

    def test_missing_local_artifact_fails(self):
        from tools.contracts.ci_artifact_reality import build_ci_artifact_reality_results

        with tempfile.TemporaryDirectory() as tmp:
            results = build_ci_artifact_reality_results(
                Path(tmp),
                profile="internal_live",
                ci_run_review={"github_actions": False},
                upload_review={},
                artifact_review={},
                missing_payloads=[],
                release_reconciliation={"passed": True},
            )

        self.assertFalse(results["passed"], results)
        self.assertGreater(results["failure_count"], 0)

    def test_empty_artifact_hash_bundle_fails(self):
        from tools.contracts.ci_artifact_reality import build_ci_artifact_reality_results

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_required_release_artifacts(root)
            _write(root / "artifacts" / "release_candidate" / "artifact_hashes.json", '{"commit_sha": "local", "hashes": []}')
            results = build_ci_artifact_reality_results(
                root,
                profile="internal_live",
                ci_run_review={"github_actions": False},
                upload_review={},
                artifact_review={},
                missing_payloads=[],
                release_reconciliation={"passed": True},
            )

        self.assertFalse(results["passed"], results)
        self.assertIn("ARTIFACT_HASH_BUNDLE_EMPTY", {row["code"] for row in results["failures"]})

    def test_artifact_commit_mismatch_fails_when_current_commit_known(self):
        from tools.contracts.ci_artifact_reality import build_ci_artifact_reality_results

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_required_release_artifacts(root, commit_sha="old")
            with patch("tools.contracts.ci_artifact_reality._git_sha", return_value="current"):
                results = build_ci_artifact_reality_results(
                    root,
                    profile="internal_live",
                    ci_run_review={"github_actions": False},
                    upload_review={},
                    artifact_review={},
                    missing_payloads=[],
                    release_reconciliation={"passed": True},
                )

        self.assertFalse(results["passed"], results)
        self.assertEqual(results["artifact_commit_mismatch_count"], 4)
        self.assertIn("LOCAL_ARTIFACT_COMMIT_MISMATCH", {row["code"] for row in results["failures"]})

    def test_local_artifact_proof_fails_when_release_summaries_have_hard_gate_failures(self):
        from tools.contracts.ci_artifact_reality import (
            LOCAL_ARTIFACT_PROOF_REL,
            build_ci_artifact_reality_results,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_required_release_artifacts(root, hard_gate_failure_count=2)
            results = build_ci_artifact_reality_results(
                root,
                profile="internal_live",
                ci_run_review={"github_actions": False},
                upload_review={},
                artifact_review={},
                missing_payloads=[],
                release_reconciliation={"passed": True},
            )
            proof = json.loads((root / LOCAL_ARTIFACT_PROOF_REL).read_text(encoding="utf-8"))

        self.assertFalse(results["passed"], results)
        self.assertFalse(proof["passed"], proof)
        self.assertEqual(proof["hard_gate_failure_count"], 2)
        self.assertEqual(results["summary_hard_gate_failure_count"], 2)
        failure_codes = {row["code"] for row in results["failures"]}
        self.assertIn("LOCAL_ARTIFACT_HARD_GATE_FAILURE", failure_codes)

    def test_in_progress_launch_readiness_does_not_self_poison_from_stale_launch_summary(self):
        from tools.contracts.ci_artifact_reality import build_ci_artifact_reality_results

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_required_release_artifacts(root)
            _write(
                root / "artifacts" / "release_candidate" / "release_candidate_summary.json",
                json.dumps({"commit_sha": "local", "production_deployable": False, "hard_gate_failure_count": 7}),
            )
            _write(
                root / "artifacts" / "launch_readiness" / "launch_readiness_summary.json",
                json.dumps({"commit_sha": "local", "all_passed": False, "failure_count": 6}),
            )
            results = build_ci_artifact_reality_results(
                root,
                profile="internal_live",
                ci_run_review={"github_actions": False},
                upload_review={},
                artifact_review={},
                missing_payloads=[],
                release_reconciliation={"passed": True},
                allow_in_progress_launch_readiness=True,
            )

        self.assertTrue(results["passed"], results)
        self.assertEqual(results["summary_hard_gate_failure_count"], 0)


if __name__ == "__main__":
    unittest.main()
