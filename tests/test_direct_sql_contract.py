import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class DirectSqlContractTests(unittest.TestCase):
    def test_direct_sql_scanner_allows_runner_and_blocks_primary_fixture(self):
        from direct_sql_contract import direct_sql_scan_artifact, scan_direct_sql_usage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            bad_section = temp_root / ".overwatch_final" / "sections" / "bad_primary.py"
            good_runner = temp_root / ".overwatch_final" / "utils" / "query.py"
            admin_file = temp_root / ".overwatch_final" / "sections" / "decision_workspace_setup_health.py"
            bad_section.parent.mkdir(parents=True, exist_ok=True)
            good_runner.parent.mkdir(parents=True, exist_ok=True)
            admin_file.write_text("session.sql('SHOW TABLES').collect()\n", encoding="utf-8")
            bad_section.write_text("session.sql('SELECT 1').collect()\n", encoding="utf-8")
            good_runner.write_text("session.sql(executable_query).to_pandas()\n", encoding="utf-8")

            findings = scan_direct_sql_usage(
                (bad_section, good_runner, admin_file),
                root=temp_root,
            )
            blocked = [finding for finding in findings if not finding["allowed"]]
            allowed = [finding for finding in findings if finding["allowed"]]
            self.assertEqual(len(blocked), 1)
            self.assertIn("bad_primary.py", blocked[0]["path"])
            self.assertEqual(blocked[0]["surface"], "section")
            self.assertTrue(allowed)
            artifact = direct_sql_scan_artifact(findings, (bad_section, good_runner, admin_file), root=temp_root)
            self.assertEqual(artifact["blocked_count"], 1)
            self.assertFalse(artifact["raw_sql_included"])
            self.assertNotIn("SELECT 1", json.dumps(artifact))

    def test_repo_direct_sql_scan_has_no_unallowlisted_daily_surface(self):
        from direct_sql_contract import scan_direct_sql_usage

        files = sorted(APP_ROOT.rglob("*.py"))
        findings = scan_direct_sql_usage(files, root=ROOT)
        blocked = [finding for finding in findings if not finding["allowed"]]
        self.assertFalse(blocked)
        self.assertTrue([finding for finding in findings if "utils\\query.py" in finding["path"] or "utils/query.py" in finding["path"]])


if __name__ == "__main__":
    unittest.main()
