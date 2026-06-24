from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "OVERWATCH_RELEASE_MANIFEST.md"
RELEASE_POLICY_COMMIT = "9603567b30b0e2dcda601fe772f8e7ee94a35ad1"


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
        policy_commit_sha = _manifest_value("Release-readiness policy/evidence commit")
        evidence_path = _manifest_value("Evidence file")
        self.assertRegex(commit_sha, r"^[0-9a-f]{40}$")
        self.assertRegex(policy_commit_sha, r"^[0-9a-f]{40}$")
        self.assertTrue(evidence_path)

        evidence_file = ROOT / evidence_path
        self.assertTrue(evidence_file.exists())
        evidence_text = evidence_file.read_text(encoding="utf-8")
        self.assertIn(commit_sha, evidence_text)
        self.assertIn(policy_commit_sha, evidence_text)

    def test_release_manifest_clarifies_candidate_and_policy_identity(self):
        text = _manifest_text()

        self.assertIn("original release-candidate baseline", text)
        self.assertIn("ramp-24 release-policy/profile/evidence updates", text)
        self.assertEqual(_manifest_value("Release-readiness policy/evidence commit"), RELEASE_POLICY_COMMIT)

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
            self.assertIn("reason", text.lower())
            return

        for fragment in (
            "Validate workflow/local equivalent: PASS",
            "Deployment contract: PASS",
            "Browser/section smoke: PASS",
            "Performance smoke: PASS",
            "Live Snowflake regression: PASS",
            "Secrets check: PASS",
            "docs/OVERWATCH_SNOWFLAKE_REGRESSION_RESULTS.md",
            "not rerun",
            "because",
            "Deferred items:",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)

    def test_release_ready_gate_results_are_specific(self):
        text = _manifest_text()
        if _manifest_value("Status") != "release-ready":
            self.skipTest("Specific release-ready gates apply only to release-ready manifests")

        self.assertRegex(text, r"Browser/section smoke: PASS, `PERF_TEST_SECTION_SMOKE_RELEASE_[^`]+`")
        self.assertRegex(text, r"Performance smoke: PASS, section smoke readiness `\d+/100`, p95 `\d+(?:\.\d+)? ms`")
        self.assertRegex(text, r"Validate workflow/local equivalent: PASS, .+`[0-9a-f]{40}`")

    def test_prior_live_regression_pass_is_labeled_as_prior_evidence(self):
        text = _manifest_text()
        if "Live Snowflake regression: PASS" not in text:
            return

        for fragment in (
            "PASS from prior credentialed evidence",
            "not rerun",
            "because",
            "docs/OVERWATCH_SNOWFLAKE_REGRESSION_RESULTS.md",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)


if __name__ == "__main__":
    unittest.main()
