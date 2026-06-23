from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
RELEASES = DOCS / "releases"

REQUIRED_HEADINGS = (
    "## Commit",
    "## Validation Commands",
    "## Deployment Contract",
    "## Mart Setup",
    "## Browser Sanity",
    "## Performance Smoke",
    "## Guarded Operations",
    "## Live Snowflake Regression",
    "## Secrets Check",
    "## Rollback / Reset",
    "## Deferred Items",
)


def _section(text: str, heading: str) -> str:
    pattern = rf"^{re.escape(heading)}\n(?P<body>.*?)(?=^## |\Z)"
    match = re.search(pattern, text, flags=re.M | re.S)
    return match.group("body") if match else ""


class ReleaseEvidenceContractTests(unittest.TestCase):
    def test_release_evidence_template_has_required_headings(self):
        template = DOCS / "OVERWATCH_RELEASE_EVIDENCE_TEMPLATE.md"
        self.assertTrue(template.exists())
        text = template.read_text(encoding="utf-8")

        for heading in REQUIRED_HEADINGS:
            with self.subTest(heading=heading):
                self.assertIn(heading, text)

    def test_at_least_one_filled_release_evidence_file_exists(self):
        self.assertTrue(RELEASES.exists())
        evidence_files = sorted(RELEASES.glob("OVERWATCH_RELEASE_EVIDENCE_*.md"))
        self.assertTrue(evidence_files)

    def test_filled_release_evidence_files_have_required_sections(self):
        for evidence in sorted(RELEASES.glob("OVERWATCH_RELEASE_EVIDENCE_*.md")):
            text = evidence.read_text(encoding="utf-8")
            with self.subTest(file=evidence.name):
                self.assertIn("# OVERWATCH Release Evidence", text)
                self.assertIn("Commit SHA:", text)
                for heading in REQUIRED_HEADINGS:
                    self.assertIn(heading, text)

    def test_filled_release_evidence_has_no_empty_placeholder_bullets(self):
        placeholder = re.compile(r"^- (?P<label>[^:\n]+):\s*$", flags=re.M)
        for evidence in sorted(RELEASES.glob("OVERWATCH_RELEASE_EVIDENCE_*.md")):
            text = evidence.read_text(encoding="utf-8")
            empty_labels = [match.group("label") for match in placeholder.finditer(text)]
            with self.subTest(file=evidence.name):
                self.assertEqual([], empty_labels)

    def test_live_snowflake_pass_claims_are_backed_by_environment_evidence(self):
        for evidence in sorted(RELEASES.glob("OVERWATCH_RELEASE_EVIDENCE_*.md")):
            text = evidence.read_text(encoding="utf-8")
            live_section = _section(text, "## Live Snowflake Regression")
            with self.subTest(file=evidence.name):
                if "PASS" in live_section:
                    for fragment in (
                        "docs/OVERWATCH_SNOWFLAKE_REGRESSION_RESULTS.md",
                        "Status: `PASS`",
                        "Role:",
                        "Warehouse:",
                        "Database/schema:",
                    ):
                        self.assertIn(fragment, live_section)

    def test_not_run_live_snowflake_claims_include_reason(self):
        reason_pattern = re.compile(r"^- If not run, reason:\s+\S", flags=re.M)
        for evidence in sorted(RELEASES.glob("OVERWATCH_RELEASE_EVIDENCE_*.md")):
            text = evidence.read_text(encoding="utf-8")
            live_section = _section(text, "## Live Snowflake Regression")
            with self.subTest(file=evidence.name):
                if "not run" in live_section.lower():
                    self.assertRegex(live_section, reason_pattern)


if __name__ == "__main__":
    unittest.main()
