import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class SessionOpenContractTests(unittest.TestCase):
    def test_session_open_scanner_blocks_primary_and_allows_marked_admin(self):
        from tools.contracts.session_open_contract import scan_session_open_usage, session_open_scan_artifact

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            bad_primary = temp_root / ".overwatch_final" / "sections" / "query_search.py"
            good_admin = temp_root / ".overwatch_final" / "sections" / "decision_workspace_setup_health.py"
            bad_header = temp_root / ".overwatch_final" / "sections" / "alert_center.py"
            bad_owner = temp_root / ".overwatch_final" / "sections" / "security_posture_overview_view.py"
            bad_helper = temp_root / ".overwatch_final" / "sections" / "legacy_helper.py"
            good_runner = temp_root / ".overwatch_final" / "utils" / "query.py"
            string_literal = temp_root / ".overwatch_final" / "sections" / "string_literal.py"
            bad_primary.parent.mkdir(parents=True, exist_ok=True)
            good_runner.parent.mkdir(parents=True, exist_ok=True)
            bad_primary.write_text("session = get_session()\n", encoding="utf-8")
            good_admin.write_text(
                "# SESSION_OPEN_ADMIN_OK boundary=setup_health reason=setup_diagnostics budget=admin_setup owner=platform\n"
                "session = get_session()\n",
                encoding="utf-8",
            )
            bad_header.write_text(
                "# SESSION_OPEN_ADMIN_OK boundary=admin reason=file_header budget=advanced_diagnostics owner=platform\n"
                "\n\n\n\n"
                "session = action_session_factory('route alerts')\n",
                encoding="utf-8",
            )
            bad_owner.write_text(
                "# SESSION_OPEN_ADMIN_OK boundary=admin reason=post_click budget=advanced_diagnostics\n"
                "session = get_session()\n",
                encoding="utf-8",
            )
            bad_helper.write_text("session = get_session()\n", encoding="utf-8")
            good_runner.write_text("_make_session(defer_role_capture=True)\n", encoding="utf-8")
            string_literal.write_text(
                "text = 'get_session() in docs'\n"
                "# get_session() in a comment\n",
                encoding="utf-8",
            )
            files = (bad_primary, good_admin, bad_header, bad_owner, bad_helper, good_runner, string_literal)
            findings = scan_session_open_usage(files, root=temp_root)
            blocked = [finding for finding in findings if not finding["allowed"]]
            self.assertEqual(len(blocked), 4)
            blocked_paths = {str(finding["path"]).replace("\\", "/") for finding in blocked}
            self.assertTrue(any("query_search.py" in path for path in blocked_paths))
            self.assertTrue(any("alert_center.py" in path for path in blocked_paths))
            self.assertTrue(any("security_posture_overview_view.py" in path for path in blocked_paths))
            self.assertTrue(any("legacy_helper.py" in path for path in blocked_paths))
            allowed = [finding for finding in findings if finding["allowed"]]
            admin = next(finding for finding in allowed if "decision_workspace_setup_health.py" in str(finding["path"]))
            self.assertEqual(admin["marker_boundary"], "setup_health")
            self.assertEqual(admin["marker_budget"], "admin_setup")
            self.assertEqual(admin["marker_owner"], "platform")
            self.assertFalse(any("string_literal.py" in str(finding["path"]) for finding in findings))
            artifact = session_open_scan_artifact(findings, files, root=temp_root)
            self.assertEqual(artifact["blocked_count"], 4)
            self.assertFalse(artifact["raw_sql_included"])
            self.assertFalse(artifact["credentials_included"])
            self.assertNotIn("SELECT", json.dumps(artifact))

    def test_repo_session_open_scan_has_no_unallowlisted_primary_surface(self):
        from tools.contracts.session_open_contract import scan_session_open_usage

        findings = scan_session_open_usage(sorted(APP_ROOT.rglob("*.py")), root=ROOT)
        blocked = [finding for finding in findings if not finding["allowed"]]
        self.assertFalse(blocked)
        self.assertTrue([finding for finding in findings if "utils\\query.py" in finding["path"] or "utils/query.py" in finding["path"]])


if __name__ == "__main__":
    unittest.main()
