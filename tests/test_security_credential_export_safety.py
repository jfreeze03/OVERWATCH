from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
for path in (ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


class SecurityCredentialExportSafetyTests(unittest.TestCase):
    def test_default_credential_export_hides_raw_ids(self):
        from utils.security_credentials import sanitize_credential_export

        frame = pd.DataFrame(
            [
                {
                    "USER_ID": "12345",
                    "USER_NAME": "JDOE",
                    "FIRST_NAME": "Jane",
                    "LAST_NAME": "Doe",
                    "CREDENTIAL_ID": "cred-001",
                    "CREDENTIAL_NAME": "Jane PAT",
                    "TYPE": "PAT",
                    "EXPIRATION_DATE": "2026-07-05",
                }
            ]
        )

        daily = sanitize_credential_export(frame, admin_only=False)
        admin = sanitize_credential_export(frame, admin_only=True)

        self.assertNotIn("USER_ID", daily.columns)
        self.assertNotIn("CREDENTIAL_ID", daily.columns)
        self.assertEqual(daily.loc[0, "USER_DISPLAY_NAME"], "Jane Doe")
        self.assertIn("USER_ID", admin.columns)
        self.assertIn("CREDENTIAL_ID", admin.columns)

    def test_security_first_paint_python_does_not_query_account_usage_credentials(self):
        section_dir = ROOT / ".overwatch_final" / "sections"
        hits = []
        for path in section_dir.rglob("security*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore").upper()
            if "SNOWFLAKE.ACCOUNT_USAGE.CREDENTIALS" in text or "ACCOUNT_USAGE.CREDENTIALS" in text:
                hits.append(str(path.relative_to(ROOT)))

        self.assertEqual(hits, [], "Security daily sections must not query Account Usage credentials.")


if __name__ == "__main__":
    unittest.main()
