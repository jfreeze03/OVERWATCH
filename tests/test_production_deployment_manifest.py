from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ProductionDeploymentManifestTests(unittest.TestCase):
    def test_current_repo_manifest_passes_with_hard_gate_payloads(self):
        from tools.contracts.production_deployment_manifest import (
            build_production_deployment_manifest,
            evaluate_production_deployment_manifest_gate,
        )

        payloads = {
            "artifacts/launch_readiness/rollback_readiness_gate_results.json": {
                "passed": True,
                "rollback_ready": True,
            },
            "artifacts/launch_readiness/production_deployment_readiness_gate_results.json": {
                "passed": True,
                "production_deployable": True,
            },
            "artifacts/launch_readiness/app_entry_smoke_gate_results.json": {
                "passed": True,
            },
        }
        manifest = build_production_deployment_manifest(ROOT, payloads)
        gate = evaluate_production_deployment_manifest_gate(manifest)

        self.assertTrue(manifest["passed"], manifest)
        self.assertTrue(gate["passed"], gate)
        self.assertTrue(gate["production_deployable"], gate)
        self.assertTrue(manifest["setup_sql_sha256"])
        self.assertTrue(manifest["validation_sql_sha256"])
        self.assertTrue(manifest["drop_sql_sha256"])
        self.assertGreater(len(manifest["split_setup_file_hashes"]), 0)
        self.assertGreater(len(manifest["required_migration_versions"]), 0)
        self.assertFalse(manifest["token_file_path_stored"])
        self.assertFalse(manifest["raw_sql_included"])
        self.assertEqual(manifest["token_path_leak_count"], 0)
        self.assertEqual(manifest["raw_sql_body_leak_count"], 0)

    def test_missing_rollback_gate_blocks_deployable_manifest(self):
        from tools.contracts.production_deployment_manifest import build_production_deployment_manifest

        manifest = build_production_deployment_manifest(ROOT, {})

        self.assertFalse(manifest["passed"])
        self.assertFalse(manifest["production_deployable"])
        self.assertIn(
            "PRODUCTION_MANIFEST_ROLLBACK_NOT_READY",
            {row["code"] for row in manifest["failures"]},
        )

    def test_manifest_gate_fails_missing_payload(self):
        from tools.contracts.production_deployment_manifest import evaluate_production_deployment_manifest_gate

        gate = evaluate_production_deployment_manifest_gate({})

        self.assertFalse(gate["passed"])
        self.assertGreater(gate["failure_count"], 0)


if __name__ == "__main__":
    unittest.main()
