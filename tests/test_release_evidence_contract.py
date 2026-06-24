from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
RELEASES = DOCS / "releases"
MANIFEST = DOCS / "OVERWATCH_RELEASE_MANIFEST.md"

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


def _manifest_value(label: str) -> str:
    pattern = rf"^- {re.escape(label)}:\s+`?([^`\n]+)`?"
    match = re.search(pattern, MANIFEST.read_text(encoding="utf-8"), flags=re.M)
    if not match:
        return ""
    return match.group(1).strip()


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

    def test_manifest_referenced_release_evidence_matches_manifest_sha(self):
        self.assertTrue(MANIFEST.exists())
        commit_sha = _manifest_value("Commit SHA")
        evidence_path = _manifest_value("Evidence file")
        self.assertTrue(commit_sha)
        self.assertTrue(evidence_path)

        evidence_file = ROOT / evidence_path
        self.assertTrue(evidence_file.exists())
        self.assertIn(commit_sha, evidence_file.read_text(encoding="utf-8"))

    def test_validation_pass_claims_include_command_and_summary(self):
        validation_line = re.compile(r"^- `[^`]+`:\s+PASS,\s+\S", flags=re.M)
        for evidence in sorted(RELEASES.glob("OVERWATCH_RELEASE_EVIDENCE_*.md")):
            text = evidence.read_text(encoding="utf-8")
            validation = _section(text, "## Validation Commands")
            pass_lines = [line for line in validation.splitlines() if "PASS" in line]
            with self.subTest(file=evidence.name):
                self.assertTrue(pass_lines)
                for line in pass_lines:
                    self.assertRegex(line, validation_line)

    def test_not_run_statements_include_reason_words(self):
        for evidence in sorted(RELEASES.glob("OVERWATCH_RELEASE_EVIDENCE_*.md")):
            text = evidence.read_text(encoding="utf-8")
            not_run_lines = [line for line in text.splitlines() if "not run" in line.lower()]
            with self.subTest(file=evidence.name):
                for line in not_run_lines:
                    self.assertRegex(line.lower(), r"(reason|because)")

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
