from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils import alert_action_queue  # noqa: E402
from utils import alert_annotations  # noqa: E402
from utils import alert_catalog  # noqa: E402
from utils import alert_command_center  # noqa: E402
from utils import alert_delivery  # noqa: E402
from utils import alert_lifecycle  # noqa: E402
from utils import alert_status  # noqa: E402
from utils import alert_triage  # noqa: E402
from utils import alerts  # noqa: E402


class _FakeSnowparkResult:
    def collect(self):
        return []


class _FakeSnowparkSession:
    def __init__(self):
        self.sql_text: str | None = None

    def sql(self, sql_text: str):
        self.sql_text = sql_text
        return _FakeSnowparkResult()


class AlertLifecycleTests(unittest.TestCase):
    def test_alerts_facade_reexports_lifecycle_and_annotation_helpers(self):
        for name in (
            "build_alert_insert_sql",
            "build_alert_status_update_sql",
            "update_alert_status",
            "build_alert_escalation_ack_sql",
            "acknowledge_alert_escalation",
        ):
            self.assertIs(getattr(alerts, name), getattr(alert_lifecycle, name))
        for name in (
            "ANNOTATION_TABLE",
            "build_annotation_ddl",
            "build_alert_triage_view_sql",
        ):
            self.assertIs(getattr(alerts, name), getattr(alert_annotations, name))

    def test_lifecycle_sql_contracts_remain_stable(self):
        insert_sql = alerts.build_alert_insert_sql(
            company="ALFA",
            environment="PROD",
            category="Reliability",
            severity="critical",
            entity_name="TASK_A",
            message="Task failed.",
            suggested_action="Open Pipeline & Task Health.",
            proof_query="SELECT 1",
            owner="DBA",
            email_target="dba-alerts@example.com",
        ).upper()
        status_sql = alerts.build_alert_status_update_sql(
            alert_id="42",
            status="Fixed",
            reason="Verified next run.",
            actor="DBA_USER",
            columns={
                "STATUS",
                "RESOLVED",
                "ACKNOWLEDGED_BY",
                "ACKNOWLEDGED_AT",
                "STATUS_REASON",
                "LAST_STATUS_BY",
                "LAST_STATUS_AT",
            },
        ).upper()
        ack_sql = alerts.build_alert_escalation_ack_sql(
            alert_id=42,
            actor="DBA_USER",
            note="Owner acknowledged escalation under INC123.",
            columns={
                "STATUS",
                "ACKNOWLEDGED_BY",
                "ACKNOWLEDGED_AT",
                "ESCALATION_ACK_BY",
                "ESCALATION_ACK_AT",
                "ESCALATION_ACK_NOTE",
                "LAST_STATUS_BY",
                "LAST_STATUS_AT",
            },
        ).upper()

        self.assertIn("INSERT INTO DBA_MAINT_DB.OVERWATCH.OVERWATCH_ALERTS", insert_sql)
        self.assertIn("'CRITICAL'", insert_sql)
        self.assertIn("'EMAIL_READY'", insert_sql)
        self.assertIn("EMAIL_SUBJECT", insert_sql)
        self.assertIn("EMAIL_BODY", insert_sql)
        self.assertIn("STATUS = 'FIXED'", status_sql)
        self.assertIn("RESOLVED = TRUE", status_sql)
        self.assertIn("ACKNOWLEDGED_BY = COALESCE", status_sql)
        self.assertIn("STATUS_REASON = 'VERIFIED NEXT RUN.'", status_sql)
        self.assertIn("WHERE ALERT_ID = 42", status_sql)
        self.assertIn("STATUS = CASE", ack_sql)
        self.assertIn("ESCALATION_ACK_BY = 'DBA_USER'", ack_sql)
        self.assertIn("ESCALATION_ACK_NOTE", ack_sql)

    def test_lifecycle_session_mutators_use_existing_columns(self):
        session = _FakeSnowparkSession()
        with patch(
            "utils.alert_lifecycle.filter_existing_columns",
            return_value=[
                "STATUS",
                "RESOLVED",
                "ACKNOWLEDGED_BY",
                "ACKNOWLEDGED_AT",
                "STATUS_REASON",
                "LAST_STATUS_BY",
                "LAST_STATUS_AT",
                "ESCALATION_ACK_BY",
                "ESCALATION_ACK_AT",
                "ESCALATION_ACK_NOTE",
            ],
        ):
            alerts.update_alert_status(
                session,
                10,
                "Acknowledged",
                reason="Ticket opened.",
                actor="DBA_USER",
            )
            status_sql = str(session.sql_text or "").upper()
            alerts.acknowledge_alert_escalation(
                session,
                10,
                actor="DBA_USER",
                note="Owner acknowledged escalation under INC123.",
            )
            ack_sql = str(session.sql_text or "").upper()

        self.assertIn("STATUS = 'ACKNOWLEDGED'", status_sql)
        self.assertIn("LAST_STATUS_BY = 'DBA_USER'", status_sql)
        self.assertIn("ESCALATION_ACK_BY = 'DBA_USER'", ack_sql)
        self.assertIn("WHERE ALERT_ID = 10", ack_sql)

    def test_annotation_and_triage_view_sql_contracts_remain_stable(self):
        ddl = alerts.build_annotation_ddl().upper()
        view_sql = alerts.build_alert_triage_view_sql().upper()

        self.assertIn("CREATE TABLE IF NOT EXISTS DBA_MAINT_DB.OVERWATCH.OVERWATCH_ANNOTATIONS", ddl)
        self.assertIn("SUPPRESS_ALERTS BOOLEAN DEFAULT TRUE", ddl)
        self.assertIn("CREATE OR REPLACE VIEW DBA_MAINT_DB.OVERWATCH.OVERWATCH_ALERT_TRIAGE_V", view_sql)
        self.assertIn("OVERWATCH_ALERT_RULES", view_sql)
        self.assertIn("SLA_TARGET_HOURS", view_sql)
        self.assertIn("TRIAGE_PRIORITY", view_sql)

    def test_status_and_severity_constants_are_centralized_without_behavior_change(self):
        self.assertIs(alert_triage.normalize_alert_status, alert_status.normalize_alert_status)
        self.assertIs(alert_triage.normalize_alert_severity, alert_status.normalize_alert_severity)
        self.assertIs(alert_catalog.normalize_alert_severity, alert_status.normalize_alert_severity)
        self.assertIs(alert_delivery._normalize_alert_severity, alert_status.normalize_alert_severity)
        self.assertIs(alert_action_queue._normalize_alert_status, alert_status.normalize_alert_status)
        self.assertIs(alert_action_queue._normalize_alert_severity, alert_status.normalize_alert_severity)
        self.assertIs(
            alert_command_center.normalize_alert_status,
            alert_status.normalize_command_center_alert_status,
        )

        self.assertEqual(alert_triage.normalize_alert_status("config_required"), "Config Required")
        self.assertEqual(alert_command_center.normalize_alert_status("config_required"), "New")
        self.assertEqual(alert_triage.normalize_alert_status("suppressed"), "Suppressed")
        self.assertEqual(alert_command_center.normalize_alert_status("suppressed"), "Ignored")
        self.assertEqual(alert_status.ALERT_SLA_HOURS["High"], 8)
        self.assertEqual(alert_status.alert_severity_rank("critical"), 0)


if __name__ == "__main__":
    unittest.main()
