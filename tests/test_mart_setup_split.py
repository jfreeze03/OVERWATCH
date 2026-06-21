"""Guard the ordered split of the Snowflake mart setup DDL.

``snowflake/setup/`` contains an ordered, reviewable split of the monolithic
``snowflake/OVERWATCH_MART_SETUP.sql``. These tests prove the split stays a
faithful, reproducible view of the monolith so that deploying the parts in order
is exactly equivalent to deploying the single file.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SETUP_FILE = ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql"
SETUP_DIR = ROOT / "snowflake" / "setup"

EXPECTED_PARTS = [
    "01_runtime_warehouse.sql",
    "02_roles_grants.sql",
    "03_config_audit_tables.sql",
    "04_mart_tables.sql",
    "05_load_procedures.sql",
    "06_alert_framework.sql",
    "07_tasks.sql",
    "08_validation.sql",
]


def _part_files():
    return sorted(p for p in SETUP_DIR.glob("0[1-9]_*.sql"))


class MartSetupSplitTests(unittest.TestCase):
    def test_expected_part_files_exist_and_are_sequential(self):
        names = [p.name for p in _part_files()]
        self.assertEqual(names, EXPECTED_PARTS)
        prefixes = [int(re.match(r"(\d+)_", n).group(1)) for n in names]
        self.assertEqual(prefixes, list(range(1, len(EXPECTED_PARTS) + 1)))

    def test_parts_concatenate_to_the_monolith(self):
        # Reproducibility guarantee: running the ordered parts is byte-for-byte
        # equivalent to running the original single setup file.
        monolith = SETUP_FILE.read_text(encoding="utf-8")
        combined = "".join(
            (SETUP_DIR / name).read_text(encoding="utf-8") for name in EXPECTED_PARTS
        )
        self.assertEqual(combined, monolith)

    def test_runner_lists_every_part_in_order(self):
        runner = (SETUP_DIR / "00_run_all.sql").read_text(encoding="utf-8")
        sourced = re.findall(r"!source\s+(\S+)", runner)
        self.assertEqual(sourced, EXPECTED_PARTS)

    def test_readme_documents_each_part(self):
        readme = (SETUP_DIR / "README.md").read_text(encoding="utf-8")
        for name in EXPECTED_PARTS:
            self.assertIn(name, readme)


if __name__ == "__main__":
    unittest.main()
