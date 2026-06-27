from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils import alert_triage  # noqa: E402
from utils import alerts  # noqa: E402


class AlertTriageTests(unittest.TestCase):
    def test_alerts_facade_reexports_triage_helpers(self):
        for name in (
            "ALERT_OPEN_STATUSES",
            "ALERT_CLOSED_STATUSES",
            "ALERT_STATUS_CHOICES",
            "ALERT_SLA_HOURS",
            "ISSUE_COLUMNS",
            "normalize_alert_severity",
            "normalize_alert_status",
            "alert_severity_rank",
            "alert_sla_hours",
            "annotate_alert_triage_frame",
            "alert_escalation_candidates",
            "build_alert_digest_summary",
            "build_alert_digest_subject",
            "build_alert_digest_body",
            "normalize_alert_frame",
            "load_alert_history",
            "normalize_alert_issue_rows",
            "normalize_action_issue_rows",
            "normalize_control_room_issue_rows",
            "build_dashboard_issue_rows",
        ):
            self.assertIs(getattr(alerts, name), getattr(alert_triage, name))

    def test_triage_annotation_digest_and_issue_contract(self):
        source = pd.DataFrame([{
            "ALERT_ID": 1,
            "ALERT_TS": "2026-06-22 08:00:00",
            "COMPANY": "ALFA",
            "CATEGORY": "Reliability",
            "ALERT_TYPE": "Task Failure",
            "SEVERITY": "critical",
            "ENTITY_NAME": "TASK_A",
            "MESSAGE": "Task failed overnight.",
            "SUGGESTED_ACTION": "Open Pipeline & Task Health.",
            "OWNER": "DBA",
            "STATUS": "new",
            "EMAIL_TARGET": "dba-alerts@example.com",
            "DELIVERY_STATUS": "EMAIL_READY",
        }])
        triage = alerts.annotate_alert_triage_frame(source, now="2026-06-22 14:00:00")
        summary = alerts.build_alert_digest_summary(source)
        subject = alerts.build_alert_digest_subject(source, company="ALFA", environment="PROD")
        body = alerts.build_alert_digest_body(source, company="ALFA", environment="PROD", recipient="dba-alerts@example.com")
        issues = alerts.build_dashboard_issue_rows(alerts=source)

        self.assertEqual(triage.iloc[0]["SEVERITY"], "critical")
        self.assertEqual(float(triage.iloc[0]["ALERT_AGE_HOURS"]), 6.0)
        self.assertEqual(summary["open"], 1)
        self.assertEqual(summary["critical_high"], 1)
        self.assertIn("1 open", subject)
        self.assertIn("Escalate first", body)
        self.assertEqual(issues.iloc[0]["ISSUE_SOURCE"], "Alert History")
        self.assertEqual(issues.iloc[0]["SEVERITY"], "Critical")

    def test_load_alert_history_uses_existing_columns_and_facade_path(self):
        captured: dict[str, object] = {}
        columns = [
            "ALERT_ID",
            "ALERT_TS",
            "COMPANY",
            "ENVIRONMENT",
            "CATEGORY",
            "ALERT_TYPE",
            "SEVERITY",
            "ENTITY_NAME",
            "MESSAGE",
            "SUGGESTED_ACTION",
            "OWNER",
            "STATUS",
            "EMAIL_TARGET",
            "DELIVERY_STATUS",
        ]

        def fake_run_query(sql, **kwargs):
            captured["sql"] = sql
            captured["kwargs"] = kwargs
            return pd.DataFrame([{
                "ALERT_ID": 9,
                "ALERT_TS": "2026-06-22 08:00:00",
                "COMPANY": "ALFA",
                "ENVIRONMENT": "PROD",
                "CATEGORY": "Reliability",
                "ALERT_TYPE": "Task Failure",
                "SEVERITY": "High",
                "ENTITY_NAME": "TASK_A",
                "MESSAGE": "Task failed.",
                "SUGGESTED_ACTION": "Review the task.",
                "OWNER": "DBA",
                "STATUS": "New",
                "EMAIL_TARGET": "dba-alerts@example.com",
                "DELIVERY_STATUS": "EMAIL_READY",
            }])

        with patch("utils.alert_triage.filter_existing_columns", return_value=columns) as filter_mock, patch(
            "utils.alert_triage.run_query",
            side_effect=fake_run_query,
        ):
            result = alerts.load_alert_history(object(), company="ALFA", environment="PROD", days=999, limit=9999)

        self.assertEqual(result.iloc[0]["ALERT_ID"], 9)
        self.assertIn("FROM DBA_MAINT_DB.OVERWATCH.MART_ALERT_EVIDENCE_RECENT", str(captured["sql"]))
        self.assertEqual(filter_mock.call_args[0][1], "DBA_MAINT_DB.OVERWATCH.MART_ALERT_EVIDENCE_RECENT")
        self.assertIn("DATEADD('day', -365", str(captured["sql"]))
        self.assertIn("LIMIT 5000", str(captured["sql"]))
        self.assertEqual(captured["kwargs"]["tier"], "recent")
        self.assertIn("SLA_TARGET_HOURS", result.columns)


if __name__ == "__main__":
    unittest.main()
