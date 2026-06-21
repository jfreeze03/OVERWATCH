"""Reproducibility test for the split OVERWATCH mart setup.

The numbered files under ``snowflake/mart_setup/`` are an order-preserving split
of ``snowflake/OVERWATCH_MART_SETUP.sql``. Deploying the parts in numeric order
must be exactly equivalent to running the monolith, so we assert their ordered
concatenation reproduces the monolith byte-for-byte and that the split is a
clean partition (no gaps, no overlaps, no lost statements).
"""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
MONOLITH = ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql"
SPLIT_DIR = ROOT / "snowflake" / "mart_setup"

# Operator-facing docs that give deployment instructions. If any of these
# mentions the single-file monolith it must also point operators at the ordered
# split (the canonical human deployment path), so the docs never route
# deployment to OVERWATCH_MART_SETUP.sql alone.
OPERATOR_FACING_DEPLOY_DOCS = (
    "README.md",
    "docs/MART_RESET_RUNBOOK.md",
    "STREAMLIT_CLOUD_DEPLOY.md",
    "ALERT_COMMAND_CENTER_RUNBOOK.md",
    "docs/OVERWATCH_COMMAND_INTELLIGENCE_RUNBOOK.md",
)
MONOLITH_REF = "OVERWATCH_MART_SETUP.sql"
SPLIT_REF = "snowflake/mart_setup/"


def _numbered_files() -> list[Path]:
    return sorted(SPLIT_DIR.glob("[0-9][0-9]_*.sql"))


class MartSetupSplitTests(unittest.TestCase):
    def test_split_files_exist(self):
        files = _numbered_files()
        self.assertTrue(files, "no numbered split files found in snowflake/mart_setup/")
        # Numbering is contiguous starting at 01.
        prefixes = [int(p.name[:2]) for p in files]
        self.assertEqual(prefixes, list(range(1, len(files) + 1)))

    def test_concatenation_reproduces_monolith(self):
        monolith = MONOLITH.read_text(encoding="utf-8")
        concatenated = "".join(p.read_text(encoding="utf-8") for p in _numbered_files())
        self.assertEqual(
            concatenated,
            monolith,
            "Concatenating the numbered split files must reproduce "
            "OVERWATCH_MART_SETUP.sql byte-for-byte.",
        )

    def test_no_statements_lost(self):
        """Every CREATE/GRANT/CALL statement in the monolith appears in a split file."""
        monolith = MONOLITH.read_text(encoding="utf-8")
        split_text = "\n".join(p.read_text(encoding="utf-8") for p in _numbered_files())
        statements = re.findall(
            r"(?m)^\s*(CREATE(?: OR REPLACE)?(?: TRANSIENT)? \w+ [A-Z0-9_\.\"]+|GRANT [A-Z ,]+ ON|CALL \w+)",
            monolith,
        )
        self.assertTrue(statements, "expected to find DDL statements in the monolith")
        for stmt in statements:
            self.assertIn(stmt, split_text, f"statement missing from split files: {stmt!r}")

    def test_readme_and_runner_present(self):
        self.assertTrue((SPLIT_DIR / "README.md").is_file())
        self.assertTrue((SPLIT_DIR / "run_mart_setup.sh").is_file())


class MartSetupDocsRoutingTests(unittest.TestCase):
    """Operator-facing docs must not route deployment to the monolith alone."""

    def test_operator_docs_point_at_ordered_split(self):
        for rel in OPERATOR_FACING_DEPLOY_DOCS:
            path = ROOT / rel
            with self.subTest(doc=rel):
                self.assertTrue(path.is_file(), f"missing operator doc: {rel}")
                text = path.read_text(encoding="utf-8")
                if MONOLITH_REF in text:
                    self.assertIn(
                        SPLIT_REF,
                        text,
                        f"{rel} references {MONOLITH_REF} for deployment but never "
                        f"mentions {SPLIT_REF}; operator docs must route deployment "
                        f"to the ordered split (canonical human deployment path).",
                    )

    def test_readme_quick_start_documents_ordered_split(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        # The canonical human deployment path must be discoverable from the README.
        self.assertIn("snowflake/mart_setup/", readme)
        self.assertIn("run_mart_setup.sh", readme)
        # The single-file artifact is still documented as byte-equivalent.
        self.assertIn(MONOLITH_REF, readme)
        self.assertIn("byte-for-byte", readme)

    def test_reset_runbook_uses_split_or_runner_not_only_monolith(self):
        runbook = (ROOT / "docs" / "MART_RESET_RUNBOOK.md").read_text(encoding="utf-8")
        # Must offer the ordered split / runner, not only `!source` of the monolith.
        self.assertIn("snowflake/mart_setup/", runbook)
        self.assertTrue(
            "run_mart_setup.sh" in runbook
            or "snowflake/mart_setup/01_runtime_objects.sql" in runbook,
            "reset runbook must tell operators to run the numbered files in order "
            "or use the provided runner",
        )


if __name__ == "__main__":
    unittest.main()
