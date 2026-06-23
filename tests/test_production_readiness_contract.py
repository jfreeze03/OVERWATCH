from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProductionReadinessContractTests(unittest.TestCase):
    def test_production_readiness_doc_covers_release_gates(self):
        doc_path = ROOT / "docs" / "OVERWATCH_PRODUCTION_READINESS.md"
        self.assertTrue(doc_path.exists())
        text = doc_path.read_text(encoding="utf-8")

        for fragment in (
            "Green Validate workflow",
            "tests.test_deployment_contract",
            "STREAMLIT_CLOUD_DEPLOY.md",
            "snowflake/OVERWATCH_MART_SETUP.sql",
            "snowflake/OVERWATCH_MART_DROP.sql",
            "perf_tests/README.md",
            "do not run live Snowflake regression unless credentials/auth are available",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)


if __name__ == "__main__":
    unittest.main()
