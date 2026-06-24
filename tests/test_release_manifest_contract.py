from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "OVERWATCH_RELEASE_MANIFEST.md"


def _manifest_text() -> str:
    return MANIFEST.read_text(encoding="utf-8")


def _manifest_value(label: str) -> str:
    pattern = rf"^- {re.escape(label)}:\s+`?([^`\n]+)`?"
    match = re.search(pattern, _manifest_text(), flags=re.M)
    if not match:
        return ""
    return match.group(1).strip()


class ReleaseManifestContractTests(unittest.TestCase):
    def test_release_manifest_exists_and_points_to_current_evidence(self):
        self.assertTrue(MANIFEST.exists())
        commit_sha = _manifest_value("Commit SHA")
        evidence_path = _manifest_value("Evidence file")
        self.assertRegex(commit_sha, r"^[0-9a-f]{40}$")
        self.assertTrue(evidence_path)

        evidence_file = ROOT / evidence_path
        self.assertTrue(evidence_file.exists())
        evidence_text = evidence_file.read_text(encoding="utf-8")
        self.assertIn(commit_sha, evidence_text)

    def test_manifest_references_required_release_artifacts(self):
        text = _manifest_text()
        for fragment in (
            "docs/OVERWATCH_PRODUCTION_READINESS.md",
            "docs/OVERWATCH_SNOWFLAKE_REGRESSION_RESULTS.md",
            "STREAMLIT_CLOUD_DEPLOY.md",
            "snowflake/OVERWATCH_MART_SETUP.sql",
            "snowflake/OVERWATCH_MART_DROP.sql",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)
                self.assertTrue((ROOT / fragment).exists())

    def test_release_ready_manifest_has_gate_results_or_reasons(self):
        text = _manifest_text()
        status = _manifest_value("Status")
        if status != "release-ready":
            self.assertEqual("candidate", status)
            self.assertIn("Deferred items:", text)
            return

        for fragment in (
            "Validate workflow/local equivalent: PASS",
            "Deployment contract: PASS",
            "Browser/section smoke: PASS",
            "Performance smoke: PASS",
            "Live Snowflake regression: PASS",
            "docs/OVERWATCH_SNOWFLAKE_REGRESSION_RESULTS.md",
            "not rerun",
            "because",
            "Deferred items:",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)


if __name__ == "__main__":
    unittest.main()
