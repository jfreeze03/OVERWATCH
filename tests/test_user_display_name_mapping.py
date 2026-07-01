from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
for path in (ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


class UserDisplayNameMappingTests(unittest.TestCase):
    def test_first_last_preferable_for_daily_display_and_chart(self):
        from utils.user_display import user_admin_label, user_chart_label, user_display_name

        row = {
            "USER_ID": "123456",
            "NAME": "JDOE",
            "DISPLAY_NAME": "John system display",
            "FIRST_NAME": "Jane",
            "LAST_NAME": "Doe",
        }

        self.assertEqual(user_display_name(row), "Jane Doe")
        self.assertEqual(user_chart_label(row), "Jane Doe")
        self.assertEqual(user_admin_label(row), "Jane Doe (JDOE)")

    def test_display_name_fallback_then_name(self):
        from utils.user_display import user_chart_label, user_display_name

        display_row = {"NAME": "ASMITH", "DISPLAY_NAME": "A. Smith", "FIRST_NAME": "", "LAST_NAME": ""}
        name_row = {"NAME": "BWHITE", "DISPLAY_NAME": "", "FIRST_NAME": None, "LAST_NAME": None}

        self.assertEqual(user_display_name(display_row), "A. Smith")
        self.assertEqual(user_chart_label(display_row), "ASMITH")
        self.assertEqual(user_display_name(name_row), "BWHITE")
        self.assertEqual(user_chart_label(name_row), "BWHITE")

    def test_user_id_only_source_is_unknown_in_daily_labels(self):
        from utils.user_display import looks_like_user_id, user_chart_label, user_display_name

        row = {"USER_ID": "123456789", "USER_NAME": "123456789", "FIRST_NAME": "", "LAST_NAME": ""}

        self.assertTrue(looks_like_user_id(row["USER_ID"]))
        self.assertEqual(user_display_name(row), "Unknown user")
        self.assertEqual(user_chart_label(row), "Unknown user")

    def test_opaque_stable_user_key_is_not_chart_label(self):
        from utils.user_display import looks_like_user_id, user_chart_label

        row = {"USER_NAME": "01b4a3c55e6f7788", "DISPLAY_NAME": "", "NAME": ""}

        self.assertTrue(looks_like_user_id(row["USER_NAME"]))
        self.assertEqual(user_chart_label(row), "Unknown user")

    def test_default_export_removes_user_ids_but_admin_export_keeps_them(self):
        from utils.user_display import sanitize_user_columns_for_export

        frame = pd.DataFrame(
            [
                {
                    "USER_ID": "98765",
                    "USER_NAME": "JDOE",
                    "FIRST_NAME": "Jane",
                    "LAST_NAME": "Doe",
                    "COST_USD": 12.5,
                }
            ]
        )

        daily = sanitize_user_columns_for_export(frame, admin_only=False)
        admin = sanitize_user_columns_for_export(frame, admin_only=True)

        self.assertNotIn("USER_ID", daily.columns)
        self.assertNotIn("USER_ADMIN_LABEL", daily.columns)
        self.assertEqual(daily.loc[0, "USER_DISPLAY_NAME"], "Jane Doe")
        self.assertIn("USER_ID", admin.columns)
        self.assertIn("USER_ADMIN_LABEL", admin.columns)


if __name__ == "__main__":
    unittest.main()
