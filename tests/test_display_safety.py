from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class DisplaySafetyTests(unittest.TestCase):
    def test_daily_source_labels_rewrite_ui_kit_like_source_names(self):
        from utils.display_safety import contains_raw_source_token, safe_source_label, scrub_daily_text

        cases = {
            "MART_EXECUTIVE_OBSERVABILITY": "Evidence cache",
            "FACT_COST_DAILY": "Evidence cache",
            "SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY": "Refresh-backed",
            "INFORMATION_SCHEMA.TABLES": "Deep diagnostics",
            "CALL SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEF()": "Deep diagnostics",
            "OVERWATCH_ALERTS": "Evidence cache",
            "ALERT_RUN_HISTORY": "Evidence cache",
            "GRANTS_TO_ROLES": "Deep diagnostics",
            "CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY": "Refresh-backed",
            "USER_ID": "Restricted identifier",
            "CREDENTIAL_ID": "Restricted identifier",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertTrue(contains_raw_source_token(raw))
                self.assertEqual(safe_source_label(raw), expected)
                cleaned = scrub_daily_text(f"Loaded from {raw}")
                self.assertNotIn(raw, cleaned)
                self.assertIn(expected, cleaned)

    def test_admin_source_label_can_preserve_exact_name(self):
        from utils.display_safety import safe_source_label

        self.assertEqual(
            safe_source_label("MART_SECURITY_CREDENTIAL_EXPIRATIONS_CURRENT", admin_only=True),
            "MART_SECURITY_CREDENTIAL_EXPIRATIONS_CURRENT",
        )

    def test_source_footer_items_are_unique_and_safe(self):
        from utils.display_safety import safe_source_footer_items

        labels = safe_source_footer_items(
            ["MART_COST_DAILY", "FACT_COST_DAILY", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"]
        )
        self.assertEqual(labels, ("Evidence cache", "Refresh-backed"))


if __name__ == "__main__":
    unittest.main()
