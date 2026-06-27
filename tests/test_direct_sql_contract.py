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
        from tools.contracts.direct_sql_contract import direct_sql_scan_artifact, scan_direct_sql_usage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            bad_section = temp_root / ".overwatch_final" / "sections" / "bad_primary.py"
            bad_evidence = temp_root / ".overwatch_final" / "sections" / "bad_evidence_loader.py"
            good_runner = temp_root / ".overwatch_final" / "utils" / "query.py"
            admin_file = temp_root / ".overwatch_final" / "sections" / "decision_workspace_setup_health.py"
            good_admin_file = temp_root / ".overwatch_final" / "sections" / "good_admin.py"
            header_only_admin = temp_root / ".overwatch_final" / "sections" / "header_admin.py"
            bad_marker_admin = temp_root / ".overwatch_final" / "sections" / "bad_marker_admin.py"
            missing_owner_admin = temp_root / ".overwatch_final" / "sections" / "missing_owner_admin.py"
            route_marker_admin = temp_root / ".overwatch_final" / "sections" / "route_marker_admin.py"
            string_literal_file = temp_root / ".overwatch_final" / "sections" / "string_literal.py"
            compatibility_file = temp_root / ".overwatch_final" / "utils" / "compatibility.py"
            bad_section.parent.mkdir(parents=True, exist_ok=True)
            good_runner.parent.mkdir(parents=True, exist_ok=True)
            admin_file.write_text("session.sql('SHOW TABLES').collect()\n", encoding="utf-8")
            good_admin_file.write_text(
                "# DIRECT_SQL_ADMIN_OK boundary=setup_health reason=setup_diagnostics budget=admin_setup owner=platform\n"
                "sess . sql('SHOW TABLES').collect()\n",
                encoding="utf-8",
            )
            header_only_admin.write_text(
                "# DIRECT_SQL_ADMIN_OK boundary=setup_health reason=file_header budget=admin_setup owner=platform\n"
                "\n\n\n\n"
                "session.sql('SHOW TABLES').collect()\n",
                encoding="utf-8",
            )
            bad_marker_admin.write_text(
                "# DIRECT_SQL_ADMIN_OK reason=missing_boundary budget=admin_setup\n"
                "session.sql('SHOW TABLES').collect()\n",
                encoding="utf-8",
            )
            missing_owner_admin.write_text(
                "# DIRECT_SQL_ADMIN_OK boundary=setup_health reason=setup_diagnostics budget=admin_setup\n"
                "session.sql('SHOW TABLES').collect()\n",
                encoding="utf-8",
            )
            route_marker_admin.write_text(
                "# DIRECT_SQL_ADMIN_OK boundary=route reason=bad_route budget=route_action owner=platform\n"
                "session.sql('SHOW TABLES').collect()\n",
                encoding="utf-8",
            )
            string_literal_file.write_text(
                "text = \"session.sql('SELECT 1')\"\n"
                "# get_session().sql('SELECT 1') in a comment\n",
                encoding="utf-8",
            )
            bad_section.write_text("session.sql('SELECT 1').collect()\n", encoding="utf-8")
            bad_evidence.write_text("get_session().sql(\n  'SELECT 1'\n).collect()\n", encoding="utf-8")
            good_runner.write_text("session.sql(executable_query).to_pandas()\n", encoding="utf-8")
            compatibility_file.write_text("sf.sql('SHOW COLUMNS').collect()\n", encoding="utf-8")

            findings = scan_direct_sql_usage(
                (
                    bad_section,
                    bad_evidence,
                    good_runner,
                    admin_file,
                    good_admin_file,
                    header_only_admin,
                    bad_marker_admin,
                    missing_owner_admin,
                    route_marker_admin,
                    string_literal_file,
                    compatibility_file,
                ),
                root=temp_root,
            )
            blocked = [finding for finding in findings if not finding["allowed"]]
            allowed = [finding for finding in findings if finding["allowed"]]
            blocked_paths = {str(finding["path"]).replace("\\", "/") for finding in blocked}
            self.assertEqual(len(blocked), 8)
            self.assertTrue(any("bad_primary.py" in path for path in blocked_paths))
            self.assertTrue(any("bad_evidence_loader.py" in path for path in blocked_paths))
            self.assertTrue(any("decision_workspace_setup_health.py" in path for path in blocked_paths))
            self.assertTrue(any("header_admin.py" in path for path in blocked_paths))
            self.assertTrue(any("bad_marker_admin.py" in path for path in blocked_paths))
            self.assertTrue(any("missing_owner_admin.py" in path for path in blocked_paths))
            self.assertTrue(any("route_marker_admin.py" in path for path in blocked_paths))
            self.assertTrue(any("compatibility.py" in path for path in blocked_paths))
            self.assertTrue(allowed)
            self.assertFalse(any("string_literal.py" in str(finding["path"]) for finding in findings))
            good_admin_finding = next(finding for finding in allowed if "good_admin.py" in str(finding["path"]))
            self.assertEqual(good_admin_finding["marker_boundary"], "setup_health")
            self.assertEqual(good_admin_finding["marker_budget"], "admin_setup")
            self.assertEqual(good_admin_finding["marker_owner"], "platform")
            artifact = direct_sql_scan_artifact(
                findings,
                (
                    bad_section,
                    bad_evidence,
                    good_runner,
                    admin_file,
                    good_admin_file,
                    header_only_admin,
                    bad_marker_admin,
                    missing_owner_admin,
                    route_marker_admin,
                    string_literal_file,
                    compatibility_file,
                ),
                root=temp_root,
            )
            self.assertEqual(artifact["blocked_count"], 8)
            self.assertFalse(artifact["raw_sql_included"])
            self.assertNotIn("SELECT 1", json.dumps(artifact))
            self.assertIn("marker_boundary", json.dumps(artifact))
            self.assertIn("marker_owner", json.dumps(artifact))

    def test_repo_direct_sql_scan_has_no_unallowlisted_daily_surface(self):
        from tools.contracts.direct_sql_contract import scan_direct_sql_usage

        files = sorted(APP_ROOT.rglob("*.py"))
        findings = scan_direct_sql_usage(files, root=ROOT)
        blocked = [finding for finding in findings if not finding["allowed"]]
        self.assertFalse(blocked)
        self.assertTrue([finding for finding in findings if "utils\\query.py" in finding["path"] or "utils/query.py" in finding["path"]])


if __name__ == "__main__":
    unittest.main()
