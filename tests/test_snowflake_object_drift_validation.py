from pathlib import Path
import json
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class SnowflakeObjectDriftValidationTests(unittest.TestCase):
    def test_fixture_profile_can_skip_without_live_artifact(self):
        from tools.contracts.snowflake_object_drift_validation import (
            build_snowflake_object_drift_results,
            evaluate_snowflake_object_drift_gate,
        )

        with tempfile.TemporaryDirectory() as tmp:
            results = build_snowflake_object_drift_results(Path(tmp), profile="internal_fixture")
            gate = evaluate_snowflake_object_drift_gate(results)

        self.assertTrue(results["passed"], results)
        self.assertTrue(results["skipped"], results)
        self.assertTrue(gate["passed"], gate)

    def test_internal_live_requires_setup_migration_artifact(self):
        from tools.contracts.snowflake_object_drift_validation import build_snowflake_object_drift_results

        with tempfile.TemporaryDirectory() as tmp:
            results = build_snowflake_object_drift_results(Path(tmp), profile="internal_live")

        self.assertFalse(results["passed"], results)
        self.assertGreater(results["failure_count"], 0)

    def test_live_setup_artifact_drives_object_rows(self):
        from tools.contracts.snowflake_object_drift_validation import (
            SNOWFLAKE_OBJECT_DRIFT_GATE_REL,
            SNOWFLAKE_OBJECT_DRIFT_RESULTS_REL,
            write_snowflake_object_drift_validation_artifacts,
        )
        from tools.contracts.snowflake_cli_live_validation import CLI_SETUP_MIGRATION_REL

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setup_path = root / CLI_SETUP_MIGRATION_REL
            setup_path.parent.mkdir(parents=True, exist_ok=True)
            setup_path.write_text(
                json.dumps(
                    {
                        "passed": True,
                        "rows": [
                            {
                                "phase": "setup_migration_object_probe",
                                "passed": True,
                                "validation_id": "object_probe",
                                "missing_required_object_count": 0,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            artifacts = write_snowflake_object_drift_validation_artifacts(root, profile="internal_live")

        self.assertTrue(artifacts[SNOWFLAKE_OBJECT_DRIFT_RESULTS_REL]["passed"])
        self.assertTrue(artifacts[SNOWFLAKE_OBJECT_DRIFT_GATE_REL]["passed"])


if __name__ == "__main__":
    unittest.main()
