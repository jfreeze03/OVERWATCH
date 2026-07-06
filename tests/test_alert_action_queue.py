from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils import alert_action_queue  # noqa: E402
from utils import alerts  # noqa: E402
from utils.action_queue import verification_query_safety_issues  # noqa: E402


class _FakeSqlResult:
    def collect(self):
        return []


class _FakeSession:
    def __init__(self):
        self.sql_texts: list[str] = []

    def sql(self, sql_text: str):
        self.sql_texts.append(sql_text)
        return _FakeSqlResult()


class AlertActionQueueTests(unittest.TestCase):
    def test_alerts_facade_reexports_action_queue_functions(self):
        self.assertIs(alerts.alert_history_to_actions, alert_action_queue.alert_history_to_actions)
        self.assertIs(alerts.mark_alerts_routed, alert_action_queue.mark_alerts_routed)

    def test_alert_to_action_conversion_keeps_public_key_fields(self):
        rows = pd.DataFrame([{
            "ALERT_ID": 7,
            "ALERT_TS": "2026-06-22 08:00:00",
            "COMPANY": "ALFA",
            "ENVIRONMENT": "PROD",
            "CATEGORY": "Cost Control",
            "ALERT_TYPE": "Credit Spike",
            "SEVERITY": "High",
            "STATUS": "New",
            "ENTITY_NAME": "WH_ALFA_OVERWATCH",
            "MESSAGE": "Credits increased by 50 percent.",
            "SUGGESTED_ACTION": "Open Cost & Contract.",
            "PROOF_QUERY": "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY LIMIT 10",
            "OWNER": "DBA / Cost owner",
        }])

        old_path = alerts.alert_history_to_actions(rows, company="ALFA")
        new_path = alert_action_queue.alert_history_to_actions(rows, company="ALFA")

        self.assertEqual(old_path, new_path)
        self.assertEqual(len(new_path), 1)
        action = new_path[0]
        self.assertEqual(action["Source"], "Alert Center")
        self.assertEqual(action["Severity"], "High")
        self.assertEqual(action["Category"], "Cost Control")
        self.assertEqual(action["Entity Type"], "Alert Entity")
        self.assertEqual(action["Entity"], "WH_ALFA_OVERWATCH")
        self.assertEqual(action["Owner"], "DBA / Cost owner")
        self.assertEqual(action["Verification Status"], "Pending")
        self.assertEqual(verification_query_safety_issues(action["Verification Query"]), [])

    def test_task_and_procedure_recovery_actions_include_verification_metadata(self):
        rows = pd.DataFrame([
            {
                "ALERT_ID": 41,
                "COMPANY": "ALFA",
                "ENVIRONMENT": "PROD",
                "CATEGORY": "Reliability",
                "ALERT_TYPE": "Task Failure",
                "SEVERITY": "Critical",
                "STATUS": "New",
                "ENTITY_NAME": "ALFA_EDW_PRD.PUBLIC.T_LOAD_POLICY",
                "DATABASE_NAME": "ALFA_EDW_PRD",
                "SCHEMA_NAME": "PUBLIC",
                "MESSAGE": "2 failed task runs.",
                "SUGGESTED_ACTION": "Review task failure.",
                "PROOF_QUERY": "ALTER TASK BAD_TASK RESUME",
                "OWNER": "Pipeline Owner",
                "SLA_TARGET_HOURS": 4,
                "ALERT_AGE_HOURS": 6.5,
                "SLA_STATE": "Overdue",
            },
            {
                "ALERT_ID": 42,
                "COMPANY": "ALFA",
                "ENVIRONMENT": "DEV",
                "CATEGORY": "Reliability",
                "ALERT_TYPE": "Stored Procedure Runtime Spike",
                "SEVERITY": "High",
                "STATUS": "Acknowledged",
                "ENTITY_NAME": "ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY",
                "DATABASE_NAME": "ALFA_EDW_DEV",
                "SCHEMA_NAME": "PUBLIC",
                "MESSAGE": "Average CALL duration 90.0s vs baseline 30.0s.",
                "SUGGESTED_ACTION": "Open stored procedure tracker.",
                "PROOF_QUERY": "CALL BAD_PROC()",
                "OWNER": "Procedure Owner",
                "SLA_TARGET_HOURS": 8,
                "ALERT_AGE_HOURS": 2,
                "SLA_STATE": "Within SLA",
            },
        ])

        by_entity = {action["Entity"]: action for action in alerts.alert_history_to_actions(rows, company="ALFA")}
        task = by_entity["ALFA_EDW_PRD.PUBLIC.T_LOAD_POLICY"]
        proc = by_entity["ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY"]

        self.assertEqual(task["Category"], "Task & Procedure Reliability")
        self.assertEqual(task["Entity Type"], "Task")
        self.assertEqual(task["Verification Status"], "Requested")
        self.assertEqual(task["Recovery Audit State"], "Audit Required")
        self.assertEqual(task["Recovery SLA State"], "Recovery SLA Breach")
        self.assertEqual(task["Recovery SLA Target Hours"], 4.0)
        self.assertEqual(task["Recovery SLA Hours"], 6.5)
        self.assertIn("TASK_HISTORY", task["Verification Query"])
        self.assertNotIn("ALTER TASK", task["Verification Query"].upper())
        self.assertIn("Required closure status", task["Recovery Evidence"])
        self.assertEqual(verification_query_safety_issues(task["Verification Query"]), [])

        self.assertEqual(proc["Category"], "Task & Procedure Reliability")
        self.assertEqual(proc["Entity Type"], "Stored Procedure")
        self.assertEqual(proc["Verification Status"], "Requested")
        self.assertEqual(proc["Recovery Audit State"], "Audit Required")
        self.assertEqual(proc["Recovery SLA State"], "Open Failure")
        self.assertEqual(proc["Baseline Value"], 30.0)
        self.assertEqual(proc["Current Value"], 90.0)
        self.assertIn("QUERY_HISTORY", proc["Verification Query"])
        self.assertIn("QUERY_TYPE = 'CALL'", proc["Verification Query"])
        self.assertEqual(verification_query_safety_issues(proc["Verification Query"]), [])

    def test_mark_alerts_routed_updates_routed_status_columns(self):
        session = _FakeSession()
        routed_columns = [
            "STATUS",
            "ROUTED_TO_ACTION_QUEUE_AT",
            "ROUTED_ACTION_COUNT",
            "LAST_STATUS_BY",
            "LAST_STATUS_AT",
        ]

        with patch("utils.alert_action_queue.filter_existing_columns", return_value=routed_columns) as probe:
            alerts.mark_alerts_routed(session, [101, "bad", "102"], action_count=3, actor="DBA_TEST")

        probe.assert_called_once()
        self.assertEqual(len(session.sql_texts), 1)
        sql = session.sql_texts[0]
        self.assertIn("UPDATE DBA_MAINT_DB.OVERWATCH.OVERWATCH_ALERTS", sql)
        self.assertIn("STATUS = CASE WHEN STATUS IS NULL OR STATUS = 'New' THEN 'In Progress' ELSE STATUS END", sql)
        self.assertIn("ROUTED_TO_ACTION_QUEUE_AT = CURRENT_TIMESTAMP()", sql)
        self.assertIn("ROUTED_ACTION_COUNT = COALESCE(ROUTED_ACTION_COUNT, 0) + 3", sql)
        self.assertIn("LAST_STATUS_BY = 'DBA_TEST'", sql)
        self.assertIn("LAST_STATUS_AT = CURRENT_TIMESTAMP()", sql)
        self.assertIn("WHERE ALERT_ID IN (101, 102)", sql)
        self.assertNotIn("bad", sql)


if __name__ == "__main__":
    unittest.main()
