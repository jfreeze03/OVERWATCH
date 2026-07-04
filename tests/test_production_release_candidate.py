from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ProductionReleaseCandidateTests(unittest.TestCase):
    def test_options_accept_token_backed_cli_arguments(self):
        from tools.contracts.production_release_candidate import options_from_args

        options = options_from_args(
            [
                "--profile",
                "internal_live",
                "--connection",
                "overwatch_live",
                "--authenticator",
                "PROGRAMMATIC_ACCESS_TOKEN",
                "--token-file-path",
                r"C:\secure\overwatch_token.txt",
                "--database",
                "DBA_MAINT_DB",
                "--schema",
                "OVERWATCH",
                "--warehouse",
                "ADMIN_WH",
                "--company",
                "ALFA",
                "--environment",
                "ALL",
                "--window-days",
                "7",
                "--skip-refresh",
                "--no-launch-readiness",
            ]
        )

        self.assertEqual(options.profile, "internal_live")
        self.assertEqual(options.connection, "overwatch_live")
        self.assertEqual(options.authenticator, "PROGRAMMATIC_ACCESS_TOKEN")
        self.assertEqual(options.token_file_path, r"C:\secure\overwatch_token.txt")
        self.assertEqual(options.database, "DBA_MAINT_DB")
        self.assertEqual(options.schema, "OVERWATCH")
        self.assertEqual(options.warehouse, "ADMIN_WH")
        self.assertEqual(options.company, "ALFA")
        self.assertEqual(options.environment, "ALL")
        self.assertEqual(options.window_days, 7)
        self.assertTrue(options.skip_refresh)

    def test_options_default_to_repo_validation_scope(self):
        from tools.contracts.production_release_candidate import options_from_args

        with patch.dict(
            "os.environ",
            {
                "OVERWATCH_SNOWFLAKE_VALIDATION_DATABASE": "",
                "OVERWATCH_SNOWFLAKE_VALIDATION_SCHEMA": "",
            },
            clear=False,
        ):
            options = options_from_args(["--connection", "overwatch_live", "--no-launch-readiness"])

        self.assertEqual(options.database, "DBA_MAINT_DB")
        self.assertEqual(options.schema, "OVERWATCH")

    def test_internal_live_enables_query_budget_proof_by_default(self):
        from tools.contracts.production_release_candidate import options_from_args

        with patch.dict("os.environ", {}, clear=True):
            options = options_from_args(
                ["--connection", "overwatch_live", "--profile", "internal_live", "--no-launch-readiness"]
            )

        self.assertTrue(options.query_history_enabled)

    def test_gate_fails_missing_results(self):
        from tools.contracts.production_release_candidate import build_production_release_candidate_gate

        gate = build_production_release_candidate_gate({})

        self.assertFalse(gate["passed"])
        self.assertFalse(gate["production_deployable"])
        self.assertGreater(gate["failure_count"], 0)

    def test_gate_requires_deployable_results(self):
        from tools.contracts.production_release_candidate import build_production_release_candidate_gate

        gate = build_production_release_candidate_gate(
            {
                "passed": True,
                "production_deployable": True,
                "phase_count": 26,
                "failures": [],
                "token_path_leak_count": 0,
                "temp_sql_file_leftover_count": 0,
            }
        )

        self.assertTrue(gate["passed"], gate)
        self.assertTrue(gate["production_deployable"], gate)
        self.assertEqual(gate["phase_count"], 26)

    def test_internal_live_no_launch_readiness_is_not_deployable(self):
        from tools.contracts.production_release_candidate import (
            _profile_policy_row,
            options_from_args,
        )

        options = options_from_args(["--profile", "internal_live", "--connection", "dev", "--no-launch-readiness"])
        row = _profile_policy_row(ROOT, options, run_launch_readiness=False)

        self.assertFalse(row["passed"], row)
        self.assertTrue(row["launch_readiness_required"], row)
        self.assertIn("Launch readiness is required", row["failure_reason"])

    def test_final_summary_overwrites_stale_intermediate_release_summary(self):
        from tools.contracts.production_release_candidate import (
            _final_release_candidate_summary,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "artifacts" / "launch_readiness").mkdir(parents=True)
            self._write_json(
                root / "artifacts" / "launch_readiness" / "launch_readiness_summary.json",
                {
                    "passed": True,
                    "all_passed": True,
                    "production_deployable": True,
                    "ci_artifact_reality_passed": False,
                    "hard_gate_failure_count": 6,
                    "token_path_leak_count": 0,
                },
            )
            self._write_json(
                root / "artifacts" / "launch_readiness" / "ci_artifact_reality_gate_results.json",
                {"passed": True, "local_artifact_signature": "signed-local", "token_path_leak_count": 0},
            )
            self._write_json(
                root / "artifacts" / "launch_readiness" / "artifact_integrity_gate_results.json",
                {
                    "passed": True,
                    "failure_count": 0,
                    "verified_artifact_count": 14,
                    "hash_mismatch_count": 0,
                },
            )
            self._write_json(
                root / "artifacts" / "launch_readiness" / "snowflake_cli_live_gate_results.json",
                {"passed": True, "snowflake_cli_gate_passed": True, "snowflake_cli_live_passed": True},
            )
            self._write_json(
                root / "artifacts" / "launch_readiness" / "production_deployment_rehearsal_gate_results.json",
                {"passed": True},
            )
            self._write_json(
                root / "artifacts" / "launch_readiness" / "full_app_release_sweep_gate_results.json",
                {"passed": True},
            )

            summary = _final_release_candidate_summary(
                root,
                {
                    "passed": True,
                    "production_deployable": True,
                    "phase_count": 20,
                    "failures": [],
                    "local_artifact_signature": "signed-local",
                    "token_path_leak_count": 0,
                    "temp_sql_file_leftover_count": 0,
                },
            )

        self.assertTrue(summary["all_passed"], summary)
        self.assertTrue(summary["production_deployable"], summary)
        self.assertTrue(summary["ci_artifact_reality_passed"], summary)
        self.assertTrue(summary["artifact_integrity_passed"], summary)
        self.assertEqual(summary["artifact_integrity_verified_count"], 14)
        self.assertEqual(summary["hard_gate_failure_count"], 0)
        self.assertEqual(summary["local_artifact_signature"], "signed-local")

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        import json

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
