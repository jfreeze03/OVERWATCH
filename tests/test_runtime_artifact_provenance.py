from pathlib import Path
import json
import subprocess
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

    def test_writer_marks_annotation_origin_in_internal_fixture(self):
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

        self.assertEqual(stamped[0]["source"], "lower_artifact_rendered")
        self.assertEqual(stamped[0]["runtime_source"], "runtime_render")
        self.assertEqual(stamped[0]["provenance_origin"], "annotated")
        self.assertTrue(result["passed"], result)

    def test_after_the_fact_annotation_fails_under_internal_live(self):
        from tools.contracts.runtime_artifact_provenance import annotate_runtime_artifacts, build_runtime_artifact_provenance

        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            artifact = root / "artifacts/full_app_validation/view_results.json"
            artifact.parent.mkdir(parents=True)
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
            artifact.write_text(
                json.dumps([{"section": "Executive Landing", "source": "runtime_render"}]),
                encoding="utf-8",
            )
            annotate_runtime_artifacts(root, launch_profile="internal_live")
            result = build_runtime_artifact_provenance(
                root,
                launch_profile="internal_live",
                required_rels=("artifacts/full_app_validation/view_results.json",),
            )

        self.assertFalse(result["passed"])
        self.assertIn("provenance_annotation_requires_waiver", result["failures"][0]["failure_reason"])

    def test_producer_written_provenance_passes(self):
        from tools.contracts.runtime_artifact_provenance import build_runtime_artifact_provenance

        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            artifact = root / "artifacts/full_app_validation/view_results.json"
            artifact.parent.mkdir(parents=True)
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
            artifact.write_text(
                json.dumps(
                    [
                        {
                            "producer": "full_app_runtime_validation",
                            "generated_at": "2026-06-29T00:00:00Z",
                            "source": "lower_artifact_rendered",
                            "provenance_origin": "producer",
                            "producer_signature": "sig",
                            "fixture_mode": False,
                            "launch_profile": "internal_live",
                            "commit_sha": commit,
                            "raw_sql_included": False,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            result = build_runtime_artifact_provenance(
                root,
                launch_profile="internal_live",
                required_rels=("artifacts/full_app_validation/view_results.json",),
            )

        self.assertTrue(result["passed"], result)

    def test_deterministic_render_rows_keep_surface_identity(self):
        from tools.contracts.runtime_artifact_provenance import build_runtime_artifact_provenance

        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            artifact = root / "artifacts/full_app_validation/deterministic_streamlit_render_results.json"
            artifact.parent.mkdir(parents=True)
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
            artifact.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "producer": "deterministic_streamlit_render",
                                "generated_at": "2026-06-29T00:00:00Z",
                                "source": "deterministic_streamlit_rendered",
                                "provenance_origin": "producer",
                                "producer_signature": "sig",
                                "fixture_mode": False,
                                "launch_profile": "internal_live",
                                "commit_sha": commit,
                                "section": "Executive Landing",
                                "workflow": "Overview",
                                "raw_sql_included": False,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = build_runtime_artifact_provenance(
                root,
                launch_profile="internal_live",
                required_rels=("artifacts/full_app_validation/deterministic_streamlit_render_results.json",),
            )

        self.assertTrue(result["passed"], result)
        self.assertEqual(result["rows"][0]["section"], "Executive Landing")
        self.assertEqual(result["rows"][0]["workflow"], "Overview")

    def test_skipped_browser_smoke_top_level_proof_is_machine_readable(self):
        from tools.contracts.runtime_artifact_provenance import (
            annotate_runtime_artifacts,
            build_runtime_artifact_provenance,
        )

        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            artifact = root / "artifacts/full_app_validation/browser_smoke_results.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                json.dumps(
                    {
                        "producer": "browser_smoke_runner",
                        "source": "browser_smoke_results",
                        "proof_source": "browser_skipped",
                        "rows": [],
                        "skipped": True,
                        "passed": True,
                        "raw_sql_included": False,
                    }
                ),
                encoding="utf-8",
            )
            annotate_runtime_artifacts(root)
            result = build_runtime_artifact_provenance(
                root,
                required_rels=("artifacts/full_app_validation/browser_smoke_results.json",),
            )

        self.assertTrue(result["passed"], result)
        self.assertEqual(result["row_count"], 1)
        self.assertEqual(result["rows"][0]["producer"], "browser_smoke_runner")

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
