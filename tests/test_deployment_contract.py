from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils.deployment import (  # noqa: E402
    STREAMLIT_MANIFEST_CONTRACT_VERSION,
    STREAMLIT_SNOWFLAKE_ARTIFACTS,
    build_streamlit_deployment_decision,
    build_streamlit_manifest_contract,
)


class DeploymentContractTests(unittest.TestCase):
    def test_streamlit_manifest_contract_is_ready(self):
        contract = build_streamlit_manifest_contract(ROOT)

        expected_checks = {
            "Snowflake manifest file",
            "Snowflake entrypoint",
            "Snowflake runtime warehouse",
            "Snowflake caller boundary",
            "Snowflake package artifacts",
            "Community Cloud wrapper",
            "Community Cloud config",
            "Deployment guide",
            "CI deployment contract",
        }
        self.assertEqual(set(contract["CHECK"]), expected_checks)
        self.assertEqual(set(contract["STATE"]), {"Ready"})

    def test_streamlit_runtime_decision_matches_manifest_contract(self):
        decision = build_streamlit_deployment_decision()
        snowflake = decision.loc[decision["RUNTIME"] == "Streamlit in Snowflake"].iloc[0]
        community = decision.loc[decision["RUNTIME"] == "Streamlit Community Cloud"].iloc[0]

        self.assertEqual(snowflake["ENTRYPOINT"], ".overwatch_final/app.py")
        self.assertEqual(snowflake["MANIFEST"], ".overwatch_final/snowflake.yml")
        self.assertEqual(snowflake["WAREHOUSE"], "OVERWATCH_WH")
        self.assertEqual(snowflake["EXECUTE_AS"], "CALLER")
        self.assertIn("streamlit_app.py", snowflake["DO_NOT_USE"])
        self.assertIn("COMPUTE_WH", snowflake["DO_NOT_USE"])

        self.assertEqual(community["ENTRYPOINT"], "streamlit_app.py")
        self.assertEqual(community["MANIFEST"], ".streamlit/config.toml")

    def test_snowflake_manifest_artifact_list_is_complete(self):
        manifest = (APP_ROOT / "snowflake.yml").read_text(encoding="utf-8")

        self.assertIn("2026.06.13", STREAMLIT_MANIFEST_CONTRACT_VERSION)
        for artifact in STREAMLIT_SNOWFLAKE_ARTIFACTS:
            with self.subTest(artifact=artifact):
                self.assertIn(f"- {artifact}", manifest)
                self.assertTrue((APP_ROOT / artifact.rstrip("/")).exists())

        self.assertNotIn("execute_as: OWNER", manifest)

    def test_ci_runs_deployment_contract_before_full_suite(self):
        workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8")

        self.assertIn("Validate deployment contract", workflow)
        self.assertIn("python -m unittest tests.test_deployment_contract", workflow)
        self.assertLess(
            workflow.index("Validate deployment contract"),
            workflow.index("Run unit tests"),
        )


if __name__ == "__main__":
    unittest.main()
