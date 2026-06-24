from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROCESS_DOC = ROOT / "docs" / "OVERWATCH_RELEASE_PROCESS.md"


class ReleaseProcessContractTests(unittest.TestCase):
    def test_release_process_doc_exists_and_covers_release_flow(self):
        self.assertTrue(PROCESS_DOC.exists())
        text = PROCESS_DOC.read_text(encoding="utf-8")

        for fragment in (
            "docs/OVERWATCH_RELEASE_MANIFEST.md",
            "docs/releases/",
            "validation commands",
            "STREAMLIT_CLOUD_DEPLOY.md",
            "live Snowflake regression",
            "credentialed run actually happened",
            "snowflake/OVERWATCH_MART_DROP.sql",
            "Never use historical evidence as current release evidence unless the SHA matches",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)


if __name__ == "__main__":
    unittest.main()
