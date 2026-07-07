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

    def test_clean_display_text_preserves_business_operator_labels(self):
        from utils.display_safety import clean_display_text

        self.assertEqual(clean_display_text("Open Security Details"), "Open Security Details")
        self.assertEqual(clean_display_text("Owner"), "Owner")
        self.assertEqual(clean_display_text("Workflow route"), "Workflow route")

    def test_operator_copy_normalizer_is_explicit(self):
        from utils.display_safety import clean_display_text, clean_operator_copy

        self.assertEqual(clean_display_text("Allocation Basis"), "Allocation Basis")
        self.assertEqual(clean_operator_copy("Allocation Basis"), "Route Telemetry")

    def test_raw_internal_scrubber_still_blocks_default_daily_identifiers(self):
        from utils.display_safety import clean_display_text, contains_raw_source_token, scrub_raw_internal_text

        raw = "Loaded from MART_COST_DAILY with USER_ID"
        self.assertTrue(contains_raw_source_token(raw))
        cleaned = scrub_raw_internal_text(raw)
        self.assertNotIn("MART_COST_DAILY", cleaned)
        self.assertNotIn("USER_ID", cleaned)
        self.assertNotIn("MART_COST_DAILY", clean_display_text(raw))

    def test_clean_display_text_scrubs_release_proof_wording(self):
        from utils.display_safety import clean_display_text

        cleaned = clean_display_text("Approval proof required before rollout.")
        self.assertNotIn("proof", cleaned.lower())
        self.assertIn("telemetry", cleaned.lower())

    def test_clean_display_text_hides_daily_source_health_diagnostics(self):
        from utils.display_safety import clean_display_text

        raw = (
            "Required Decision Brief source unavailable | Oldest required source age 552 minutes; "
            "target 60 minutes | Requested: ALFA / ALL / 7 days"
        )
        self.assertEqual(clean_display_text(raw), "Refresh required")


if __name__ == "__main__":
    unittest.main()
