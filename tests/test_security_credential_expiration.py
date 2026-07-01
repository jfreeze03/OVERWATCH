from datetime import UTC, datetime
from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
for path in (ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


NOW = datetime(2026, 6, 30, tzinfo=UTC)


class SecurityCredentialExpirationTests(unittest.TestCase):
    def test_days_buckets_and_severity(self):
        from utils.security_credentials import (
            days_to_expiration,
            expiration_bucket,
            expiration_severity,
        )

        self.assertEqual(days_to_expiration("2026-06-29", now=NOW), -1)
        self.assertEqual(expiration_bucket(-1), "expired")
        self.assertEqual(expiration_severity("expired"), "Critical")
        self.assertEqual(expiration_bucket(6), "expires_0_7_days")
        self.assertEqual(expiration_severity("expires_0_7_days"), "High")
        self.assertEqual(expiration_bucket(20), "expires_8_30_days")
        self.assertEqual(expiration_severity("expires_8_30_days"), "Medium")
        self.assertEqual(expiration_bucket(45), "ok")
        self.assertEqual(expiration_bucket(None), "no_expiration")

    def test_summary_counts_expired_and_due_under_30_only(self):
        from utils.security_credentials import credential_expiration_summary

        frame = pd.DataFrame(
            [
                {
                    "USER_NAME": "JDOE",
                    "FIRST_NAME": "Jane",
                    "LAST_NAME": "Doe",
                    "TYPE": "PAT",
                    "EXPIRATION_DATE": "2026-06-29",
                },
                {
                    "USER_NAME": "ASMITH",
                    "FIRST_NAME": "Ann",
                    "LAST_NAME": "Smith",
                    "TYPE": "PAT",
                    "EXPIRATION_DATE": "2026-07-05",
                },
                {
                    "USER_NAME": "BWHITE",
                    "FIRST_NAME": "Bob",
                    "LAST_NAME": "White",
                    "TYPE": "WIF",
                    "EXPIRATION_DATE": "2026-07-20",
                },
                {
                    "USER_NAME": "CFROST",
                    "FIRST_NAME": "Casey",
                    "LAST_NAME": "Frost",
                    "TYPE": "PAT",
                    "EXPIRATION_DATE": "2026-08-15",
                },
                {
                    "USER_NAME": "NNULL",
                    "DISPLAY_NAME": "No Expiration",
                    "TYPE": "MFA",
                    "EXPIRATION_DATE": None,
                },
            ]
        )

        summary = credential_expiration_summary(frame, now=NOW)

        self.assertEqual(summary["SECURITY_CREDENTIALS_EXPIRED_COUNT"], 1)
        self.assertEqual(summary["SECURITY_CREDENTIALS_EXPIRING_7D_COUNT"], 1)
        self.assertEqual(summary["SECURITY_CREDENTIALS_EXPIRING_30D_COUNT"], 2)
        self.assertEqual(summary["SECURITY_CREDENTIAL_NEXT_EXPIRATION_USER"], "Jane Doe")
        self.assertEqual(summary["SECURITY_CREDENTIAL_EXPIRATION_STATUS"], "due_or_expired")

    def test_snowflake_sql_promotes_credential_metric_and_findings(self):
        setup_sql = (ROOT / "snowflake" / "mart_setup" / "05_load_procedures.sql").read_text(
            encoding="utf-8"
        ).upper()

        self.assertIn("SP_OVERWATCH_LOAD_SECURITY_CREDENTIAL_EXPIRATIONS", setup_sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.CREDENTIALS", setup_sql)
        self.assertIn("MART_SECURITY_CREDENTIAL_EXPIRATIONS_CURRENT", setup_sql)
        self.assertIn("CREDENTIAL_EXPIRING::", setup_sql)
        self.assertIn("CREDENTIAL_EXPIRATIONS", setup_sql)
        self.assertIn("ROTATE OR RENEW CREDENTIAL BEFORE EXPIRATION", setup_sql)


if __name__ == "__main__":
    unittest.main()
