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

    def test_security_primary_summary_includes_packet_backed_credential_metric(self):
        from sections.metric_semantic_registry import PRIMARY_METRIC_KEYS, get_metric_semantic
        from sections.section_command_brief import SectionCommandBrief, SectionCommandMetric
        from sections.decision_workspace_view_model import build_decision_workspace_view_model

        self.assertIn("credential_expirations", PRIMARY_METRIC_KEYS["Security Monitoring"])
        semantic = get_metric_semantic("Security Monitoring", "credential_expirations")
        self.assertIsNotNone(semantic)
        self.assertEqual(semantic.source_family, "credential_expiration")

        brief = SectionCommandBrief(
            "Security Monitoring",
            "ALFA",
            "ALL",
            "7 days",
            "Watch",
            "Security posture needs review.",
            "Security view",
            "fixture",
            "Updated now",
            "2026-06-30T00:00:00",
            metrics=(
                SectionCommandMetric(key="failed_logins", label="Failed Logins", value="", numeric_value=0),
                SectionCommandMetric(
                    key="credential_expirations",
                    label="Credential expirations",
                    value="1 expired · 2 due within 30d",
                    numeric_value=3,
                    detail="Next: Jane Doe · PAT · 6d",
                    metric_format="integer",
                    unit="credentials",
                ),
                SectionCommandMetric(key="mfa_gaps", label="MFA Gaps", value="", numeric_value=1),
                SectionCommandMetric(key="risky_grants", label="Risky Grants", value="", numeric_value=2),
                SectionCommandMetric(key="sharing_exposure", label="Sharing Exposure", value="", numeric_value=4),
            ),
            raw_payload={
                "SECURITY_CREDENTIALS_EXPIRED_COUNT": 1,
                "SECURITY_CREDENTIALS_EXPIRING_30D_COUNT": 2,
                "SECURITY_CREDENTIAL_NEXT_EXPIRATION_USER": "Jane Doe",
                "SECURITY_CREDENTIAL_NEXT_EXPIRATION_TYPE": "PAT",
            },
        )

        model = build_decision_workspace_view_model(brief, current_workflow="Security Overview")
        by_key = {metric.key: metric for metric in model.metric_cells}

        self.assertIn("credential_expirations", by_key)
        self.assertEqual(by_key["credential_expirations"].label, "Credential Expirations")
        self.assertEqual(by_key["credential_expirations"].value, "3")
        self.assertIn("Jane Doe", by_key["credential_expirations"].detail)

    def test_missing_credential_metric_renders_pending_not_zero(self):
        from sections.section_command_brief import SectionCommandBrief, SectionCommandMetric
        from sections.decision_workspace_view_model import build_decision_workspace_view_model

        brief = SectionCommandBrief(
            "Security Monitoring",
            "ALFA",
            "ALL",
            "7 days",
            "Watch",
            "Security posture needs review.",
            "Security view",
            "fixture",
            "Updated now",
            "2026-06-30T00:00:00",
            metrics=(
                SectionCommandMetric(key="failed_logins", label="Failed Logins", value="", numeric_value=0),
                SectionCommandMetric(
                    key="credential_expirations",
                    label="Credential expirations",
                    value="0",
                    numeric_value=0,
                    metric_format="integer",
                    available=False,
                    availability_state="Credential expiration source pending",
                ),
                SectionCommandMetric(key="mfa_gaps", label="MFA Gaps", value="", numeric_value=1),
                SectionCommandMetric(key="risky_grants", label="Risky Grants", value="", numeric_value=2),
            ),
        )

        model = build_decision_workspace_view_model(brief, current_workflow="Security Overview")
        by_key = {metric.key: metric for metric in model.metric_cells}

        self.assertEqual(by_key["credential_expirations"].value, "Credential expiration source pending")


if __name__ == "__main__":
    unittest.main()
