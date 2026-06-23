from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
REGRESSION_DOC = ROOT / "docs" / "OVERWATCH_SNOWFLAKE_REGRESSION_RESULTS.md"
RELEASE_DIR = ROOT / "docs" / "releases"


class SnowflakeRegressionResultsContractTests(unittest.TestCase):
    def _read_regression_doc(self) -> str:
        self.assertTrue(REGRESSION_DOC.exists())
        return REGRESSION_DOC.read_text(encoding="utf-8")

    def test_regression_results_doc_has_required_release_fields(self):
        text = self._read_regression_doc()
        for fragment in (
            "Run ID",
            "Timestamp",
            "Status",
            "Environment",
            "Role",
            "Warehouse",
            "Database/schema",
            "## Sections Tested",
            "## Workflows Tested",
            "## Static Route / Label Checks",
            "## Snowflake Checks",
            "## Object Inventory",
            "## Failures",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)

    def test_pass_regression_has_no_failures_recorded(self):
        text = self._read_regression_doc()
        if re.search(r"Status:\s+`PASS`", text):
            failures = re.search(r"^## Failures\n(?P<body>.*?)(?=^## |\Z)", text, flags=re.M | re.S)
            self.assertIsNotNone(failures)
            self.assertIn("None recorded.", failures.group("body"))

    def test_recommended_followups_are_recorded_or_deferred_in_release_evidence(self):
        text = self._read_regression_doc()
        recommendations = re.search(r"^## Recommended Fixes\n(?P<body>.*?)(?=^## |\Z)", text, flags=re.M | re.S)
        if not recommendations:
            return
        body = recommendations.group("body").lower()
        evidence = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(RELEASE_DIR.glob("OVERWATCH_RELEASE_EVIDENCE_*.md"))
        )
        if "section smoke" in body:
            self.assertIn("Section smoke result: PASS", evidence)
        if "full unit regression" in body:
            self.assertIn("python -m unittest discover -s tests`: PASS", evidence)


if __name__ == "__main__":
    unittest.main()
