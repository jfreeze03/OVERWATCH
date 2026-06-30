from pathlib import Path
import json
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class RuntimeArtifactProvenanceTests(unittest.TestCase):
    def test_missing_provenance_fails_gate(self):
        from tools.contracts.runtime_artifact_provenance import (
            RUNTIME_ARTIFACT_PROVENANCE_REL,
            build_runtime_artifact_provenance,
            evaluate_runtime_artifact_provenance_gate,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "artifacts/full_app_validation/view_results.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(json.dumps([{"section": "Executive Landing"}]), encoding="utf-8")
            result = build_runtime_artifact_provenance(
                root,
                required_rels=("artifacts/full_app_validation/view_results.json",),
            )
            gate = evaluate_runtime_artifact_provenance_gate(result)

        self.assertEqual(RUNTIME_ARTIFACT_PROVENANCE_REL, "artifacts/full_app_validation/runtime_artifact_provenance_results.json")
        self.assertFalse(result["passed"])
        self.assertFalse(gate["passed"])
        self.assertIn("missing_producer", result["failures"][0]["failure_reason"])

    def test_writer_stamps_runtime_artifacts(self):
        from tools.contracts.runtime_artifact_provenance import (
            annotate_runtime_artifacts,
            build_runtime_artifact_provenance,
        )

        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            artifact = root / "artifacts/full_app_validation/view_results.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                json.dumps([{"section": "Executive Landing", "source": "runtime_render"}]),
                encoding="utf-8",
            )
            annotate_runtime_artifacts(root)
            stamped = json.loads(artifact.read_text(encoding="utf-8"))
            result = build_runtime_artifact_provenance(
                root,
                required_rels=("artifacts/full_app_validation/view_results.json",),
            )

        self.assertEqual(stamped[0]["source"], "rendered_app")
        self.assertEqual(stamped[0]["runtime_source"], "runtime_render")
        self.assertTrue(result["passed"], result)

    def test_internal_live_fixture_source_requires_waiver(self):
        from tools.contracts.runtime_artifact_provenance import build_runtime_artifact_provenance

        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            artifact = root / "artifacts/full_app_validation/stress_results.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                json.dumps(
                    [
                        {
                            "producer": "stress",
                            "generated_at": "2026-06-29T00:00:00Z",
                            "source": "fixture",
                            "fixture_mode": True,
                            "launch_profile": "internal_live",
                            "commit_sha": "abc",
                            "raw_sql_included": False,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            result = build_runtime_artifact_provenance(
                root,
                launch_profile="internal_live",
                required_rels=("artifacts/full_app_validation/stress_results.json",),
            )

        self.assertFalse(result["passed"])
        self.assertIn("fixture_only_runtime_artifact_requires_waiver", result["failures"][0]["failure_reason"])


if __name__ == "__main__":
    unittest.main()
