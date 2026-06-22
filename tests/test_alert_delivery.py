from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils import alert_delivery  # noqa: E402
from utils import alerts  # noqa: E402


class _FakeSqlResult:
    def collect(self):
        return []


class _FakeSession:
    def __init__(self):
        self.sql_texts: list[str] = []

    def sql(self, sql_text: str):
        self.sql_texts.append(sql_text)
        return _FakeSqlResult()


class AlertDeliveryTests(unittest.TestCase):
    def test_alerts_facade_reexports_delivery_functions(self):
        for name in (
            "current_alert_recipient",
            "alert_recipient_label",
            "alert_delivery_status_for_target",
            "alert_delivery_log_fqn",
            "build_alert_email_subject",
            "build_alert_email_body",
            "build_alert_delivery_log_ddl",
            "build_alert_delivery_log_insert_sql",
            "build_alert_delivery_mark_sql",
            "build_alert_email_delivery_procedure_sql",
            "load_alert_delivery_log",
            "log_alert_digest_delivery",
            "send_teams_alert",
        ):
            self.assertIs(getattr(alerts, name), getattr(alert_delivery, name))

    def test_email_subject_body_and_status_stay_compatible(self):
        row = {
            "COMPANY": "ALFA",
            "ENVIRONMENT": "PROD",
            "SEVERITY": "critical",
            "CATEGORY": "Reliability",
            "ALERT_TYPE": "Task Failure",
            "ENTITY_NAME": "ALFA_EDW_PROD.PUBLIC.T_LOAD_POLICY",
            "MESSAGE": "Task failed twice.",
            "SUGGESTED_ACTION": "Open Pipeline & Task Health.",
            "PROOF_QUERY": "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY LIMIT 10",
        }

        self.assertEqual(
            alerts.build_alert_email_subject(row, company="ALFA"),
            "OVERWATCH Critical: Reliability - ALFA_EDW_PROD.PUBLIC.T_LOAD_POLICY (ALFA)",
        )
        body = alerts.build_alert_email_body(row, company="ALFA")
        self.assertIn("Environment: PROD", body)
        self.assertIn("Severity: Critical", body)
        self.assertIn("Task failed twice.", body)
        self.assertIn("Open Pipeline & Task Health.", body)
        self.assertEqual(alerts.alert_delivery_status_for_target("dba@example.com"), "EMAIL_READY")
        self.assertEqual(alerts.alert_delivery_status_for_target(""), "CONFIG_REQUIRED")
        self.assertEqual(alerts.send_teams_alert("", "message"), False)

    def test_delivery_log_sql_builders_keep_existing_contract(self):
        ddl = alerts.build_alert_delivery_log_ddl().upper()
        insert_sql = alerts.build_alert_delivery_log_insert_sql(
            alert_ids=[9, "bad", "10"],
            company="ALFA",
            environment="PROD",
            delivery_target="dba@example.com",
            email_subject="Subject",
            email_body="Body",
            actor="DBA_TEST",
            notes="Logged after operator review.",
        )
        mark_sql = alerts.build_alert_delivery_mark_sql(
            alert_ids=[9, "bad", "10"],
            delivery_target="dba@example.com",
            actor="DBA_TEST",
            columns={
                "DELIVERY_STATUS",
                "DELIVERY_TARGET",
                "EMAIL_TARGET",
                "LAST_DELIVERY_AT",
                "LAST_DELIVERY_BY",
                "DELIVERY_LOG_COUNT",
                "ESCALATED_TO",
                "ESCALATED_AT",
                "LAST_STATUS_BY",
                "LAST_STATUS_AT",
            },
        )

        self.assertIn("CREATE TABLE IF NOT EXISTS DBA_MAINT_DB.OVERWATCH.OVERWATCH_ALERT_DELIVERY_LOG", ddl)
        self.assertIn("INSERT INTO DBA_MAINT_DB.OVERWATCH.OVERWATCH_ALERT_DELIVERY_LOG", insert_sql)
        self.assertIn("PARSE_JSON('[9, 10]')", insert_sql)
        self.assertIn("'EMAIL_LOGGED'", insert_sql)
        self.assertIn("UPDATE DBA_MAINT_DB.OVERWATCH.OVERWATCH_ALERTS", mark_sql)
        self.assertIn("DELIVERY_STATUS = 'EMAIL_LOGGED'", mark_sql)
        self.assertIn("WHERE ALERT_ID IN (9, 10)", mark_sql)
        self.assertNotIn("bad", mark_sql)

    def test_log_alert_digest_delivery_uses_delivery_audit_and_mark_sql(self):
        session = _FakeSession()
        rows = pd.DataFrame({"ALERT_ID": ["21", "22", None]})
        columns = [
            "DELIVERY_STATUS",
            "DELIVERY_TARGET",
            "EMAIL_TARGET",
            "LAST_DELIVERY_AT",
            "LAST_DELIVERY_BY",
            "DELIVERY_LOG_COUNT",
        ]

        with patch("utils.alert_delivery.filter_existing_columns", return_value=columns) as probe:
            logged = alerts.log_alert_digest_delivery(
                session,
                rows,
                company="ALFA",
                environment="PROD",
                delivery_target="dba@example.com",
                email_subject="Digest",
                email_body="Body",
                actor="DBA_TEST",
                notes="Operator logged digest delivery.",
            )

        self.assertEqual(logged, 2)
        probe.assert_called_once()
        self.assertEqual(len(session.sql_texts), 2)
        self.assertIn("INSERT INTO DBA_MAINT_DB.OVERWATCH.OVERWATCH_ALERT_DELIVERY_LOG", session.sql_texts[0])
        self.assertIn("UPDATE DBA_MAINT_DB.OVERWATCH.OVERWATCH_ALERTS", session.sql_texts[1])
        self.assertIn("WHERE ALERT_ID IN (21, 22)", session.sql_texts[1])


if __name__ == "__main__":
    unittest.main()
