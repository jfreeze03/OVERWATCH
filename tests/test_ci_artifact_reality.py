from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _write(path: Path, text: str = "{}") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class CiArtifactRealityTests(unittest.TestCase):
    def test_local_signed_artifact_bundle_passes_without_github_metadata(self):
        from tools.contracts.ci_artifact_reality import (
            REQUIRED_LOCAL_ARTIFACTS,
            build_ci_artifact_reality_results,
            evaluate_ci_artifact_reality_gate,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in REQUIRED_LOCAL_ARTIFACTS:
                _write(root / rel, '{"commit_sha": "local"}')

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

        self.assertTrue(results["passed"], results)
        self.assertTrue(results["local_artifact_signature"], results)
        self.assertTrue(gate["passed"], gate)

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


if __name__ == "__main__":
    unittest.main()
