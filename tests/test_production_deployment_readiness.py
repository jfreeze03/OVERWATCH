from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class ProductionDeploymentReadinessTests(unittest.TestCase):
    def test_current_repo_production_deployment_readiness_passes(self):
        from tools.contracts.production_deployment_readiness import (
            build_production_deployment_readiness_results,
            evaluate_production_deployment_readiness_gate,
        )

        payloads = {
            "artifacts/launch_readiness/setup_migration_live_gate_results.json": {
                "passed": True,
                "setup_migration_live_passed": True,
            },
            "artifacts/launch_readiness/snowflake_cli_temp_file_hygiene_gate_results.json": {
                "passed": True,
                "temp_sql_file_leftover_count": 0,
            },
        }
        results = build_production_deployment_readiness_results(ROOT, payloads)
        gate = evaluate_production_deployment_readiness_gate(results)

        self.assertTrue(results["passed"], results)
        self.assertTrue(gate["passed"], gate)
        self.assertTrue(gate["production_deployable"], gate)
        self.assertTrue(gate["rollback_ready"], gate)
        self.assertTrue(gate["deployment_role_ready"], gate)
        self.assertTrue(gate["runtime_role_ready"], gate)
        self.assertTrue(gate["privilege_matrix_passed"], gate)
        self.assertTrue(gate["secret_inventory_passed"], gate)
        self.assertTrue(gate["token_auth_ready"], gate)
        self.assertEqual(gate["notification_integration_status"], "ready")
        self.assertEqual(gate["alert_recipient_governance_status"], "ready")
        self.assertEqual(gate["token_path_leak_count"], 0)
        self.assertEqual(gate["raw_secret_leak_count"], 0)

    def test_missing_role_and_secret_docs_fail(self):
        from tools.contracts.production_deployment_readiness import build_production_deployment_readiness_results

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "snowflake" / "OVERWATCH_MART_SETUP.sql", "CREATE DATABASE IF NOT EXISTS DBA_MAINT_DB;")
            _write(root / "snowflake" / "OVERWATCH_MART_VALIDATION.sql", "")
            _write(root / "snowflake" / "OVERWATCH_MART_DROP.sql", "")
            results = build_production_deployment_readiness_results(root, {})

        self.assertFalse(results["passed"])
        checks = {row["check"]: row for row in results["failures"]}
        self.assertIn("role_documented::OVERWATCH_VIEWER", checks)
        self.assertIn("secret_env_documented::OVERWATCH_SNOWFLAKE_CLI_CONNECTION", checks)

    def test_token_path_leak_in_artifact_payload_fails(self):
        from tools.contracts.production_deployment_readiness import build_production_deployment_readiness_results

        token_path = "C:/secure/private_pat_file.txt"
        payloads = {
            "artifacts/launch_readiness/setup_migration_live_gate_results.json": {"passed": True},
            "artifacts/launch_readiness/snowflake_cli_temp_file_hygiene_gate_results.json": {"passed": True},
            "artifacts/snowflake_validation/snowflake_cli_connection_results.json": {
                "sanitized_error": f"opened {token_path}"
            },
        }
        with patch.dict("os.environ", {"OVERWATCH_SNOWFLAKE_CLI_TOKEN_FILE_PATH": token_path}, clear=False):
            results = build_production_deployment_readiness_results(ROOT, payloads)

        self.assertFalse(results["passed"])
        self.assertGreater(results["token_path_leak_count"], 0)

    def test_placeholder_alert_email_fails(self):
        from tools.contracts.production_deployment_readiness import build_production_deployment_readiness_results

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            required = "\n".join(
                [
                    "OVERWATCH_VIEWER OVERWATCH_OPERATOR OVERWATCH_ADMIN",
                    "CREATE DATABASE CREATE SCHEMA CREATE WAREHOUSE TASK PROCEDURE",
                    "SELECT from SNOWFLAKE.ACCOUNT_USAGE views",
                    "MONITOR ACCOUNT",
                    "GRANT USAGE ON WAREHOUSE",
                    "GRANT USAGE ON DATABASE GRANT USAGE ON SCHEMA",
                    "NOTIFICATION INTEGRATION",
                    "PROGRAMMATIC_ACCESS_TOKEN --token-file-path",
                    "OVERWATCH_SNOWFLAKE_CLI_CONNECTION OVERWATCH_LAUNCH_PROFILE",
                    "OVERWATCH_SNOWFLAKE_CLI_AUTHENTICATOR OVERWATCH_SNOWFLAKE_CLI_TOKEN_FILE_PATH",
                    "OVERWATCH_SNOWFLAKE_VALIDATION_DATABASE OVERWATCH_SNOWFLAKE_VALIDATION_SCHEMA",
                    "OVERWATCH_SNOWFLAKE_VALIDATION_WAREHOUSE",
                    "OVERWATCH_SCHEMA_MIGRATION MART_SECURITY_CREDENTIAL_EXPIRATIONS_CURRENT",
                    "MART_USER_DISPLAY_DIMENSION MART_SECTION_DECISION_CURRENT",
                    "MART_SECTION_DECISION_CURRENT_FLAT OVERWATCH_SETUP_HEALTH",
                    "DBA-ALERTS@YOURCOMPANY.COM",
                ]
            )
            _write(root / "snowflake" / "OVERWATCH_MART_SETUP.sql", required)
            _write(root / "snowflake" / "OVERWATCH_MART_VALIDATION.sql", required)
            _write(root / "snowflake" / "OVERWATCH_MART_DROP.sql", "-- drop")
            _write(root / "snowflake" / "mart_setup" / "01.sql", required)
            _write(root / "docs" / "PRODUCTION_READINESS_CLEANUP.md", "Do not execute grants")
            _write(root / "docs" / "snowflake_cli_live_validation.md", required)
            _write(root / "scripts" / "run_snowflake_cli_live_validation.ps1", required)
            _write(root / "scripts" / "run_snowflake_cli_live_validation.sh", required)
            _write(root / "tools" / "contracts" / "snowflake_cli_live_validation.py", required)
            _write(root / ".overwatch_final" / "config.py", 'DEFAULT_ALERT_EMAIL = "DBA-ALERTS@YOURCOMPANY.COM"')

            results = build_production_deployment_readiness_results(
                root,
                {
                    "artifacts/launch_readiness/setup_migration_live_gate_results.json": {"passed": True},
                    "artifacts/launch_readiness/snowflake_cli_temp_file_hygiene_gate_results.json": {"passed": True},
                },
            )

        self.assertFalse(results["passed"])
        self.assertTrue(any(row["check"] == "alert_email_default_governed" for row in results["failures"]))


if __name__ == "__main__":
    unittest.main()
