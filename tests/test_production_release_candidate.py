from pathlib import Path
import sys
import unittest


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


if __name__ == "__main__":
    unittest.main()
