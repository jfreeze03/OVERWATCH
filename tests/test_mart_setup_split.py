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


if __name__ == "__main__":
    unittest.main()
