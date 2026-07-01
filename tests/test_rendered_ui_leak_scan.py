from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class RenderedUiLeakScanTests(unittest.TestCase):
    def test_daily_diagnostic_card_fails(self):
        from tools.contracts.rendered_ui_leak_scan import scan_rendered_ui

        results, failures = scan_rendered_ui(
            {
                "artifacts/full_app_validation/view_results.json": [
                    {
                        "section": "Executive Landing",
                        "workflow": "Overview",
                        "rendered_text": "diagnostic card Traceback ACCOUNT_USAGE",
                    }
                ]
            }
        )

        self.assertFalse(results["passed"])
        self.assertGreater(failures["failure_count"], 0)

    def test_admin_setup_allows_technical_terms(self):
        from tools.contracts.rendered_ui_leak_scan import scan_rendered_ui

        results, failures = scan_rendered_ui(
            {
                "artifacts/full_app_validation/view_results.json": [
                    {
                        "section": "Settings/Admin Setup Health",
                        "workflow": "Setup Health",
                        "admin_only": True,
                        "rendered_text": "ACCOUNT_USAGE setup validation row",
                    }
                ]
            }
        )

        self.assertTrue(results["passed"], failures)

    def test_ui_kit_demo_and_no_connection_copy_fails_daily_scan(self):
        from tools.contracts.rendered_ui_leak_scan import scan_rendered_ui

        results, failures = scan_rendered_ui(
            {
                "artifacts/full_app_validation/view_results.json": [
                    {
                        "section": "Executive Landing",
                        "workflow": "Overview",
                        "rendered_text": "No Snowflake connection. RoleGate demo role Lock button",
                    }
                ]
            }
        )

        self.assertFalse(results["passed"])
        self.assertGreaterEqual(failures["failure_count"], 1)
