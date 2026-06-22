from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils import alert_command_center  # noqa: E402
from utils import alerts  # noqa: E402


class AlertCommandCenterTests(unittest.TestCase):
    def test_alerts_facade_reexports_command_center_helpers(self):
        for name in (
            "build_alert_acknowledgement_insert_sql",
            "build_alert_remediation_log_insert_sql",
            "build_alert_event_materialization_sql",
            "build_alert_command_center_setup_sql",
            "build_alert_signal_query_catalog",
            "build_alert_required_privileges",
            "build_alert_optional_integrations",
            "build_alert_command_center_runbook_markdown",
        ):
            self.assertIs(getattr(alerts, name), getattr(alert_command_center, name))

    def test_acknowledgement_and_remediation_sql_contracts(self):
        ack_sql = alerts.build_alert_acknowledgement_insert_sql(
            event_id="42",
            alert_key="PIPELINE_TASK_FAILURE",
            note="Route to DBA pipeline ticket OW-42.",
            actor="DBA_TEST",
            owner="DBA / Pipeline",
            status_after_ack="in_progress",
            next_checkpoint_hours=2,
        )
        remediation_sql = alerts.build_alert_remediation_log_insert_sql(
            event_id="42",
            alert_key="PIPELINE_TASK_FAILURE",
            action_type="Task rerun review",
            remediation_mode="verification_required",
            action_sql="EXECUTE TASK IDENTIFIER('<database.schema.task_name>');",
            rollback_guidance="Confirm downstream state before rerun.",
            verification_sql="SELECT * FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY()) LIMIT 10;",
            actor="DBA_TEST",
            approved_by="DBA_APPROVER",
        )

        self.assertIn("INSERT INTO DBA_MAINT_DB.OVERWATCH.ALERT_ACKNOWLEDGEMENTS", ack_sql)
        self.assertIn("'In Progress' AS STATUS_AFTER_ACK", ack_sql)
        self.assertIn("DATEADD('hour', 2, CURRENT_TIMESTAMP())", ack_sql)
        self.assertIn("INSERT INTO DBA_MAINT_DB.OVERWATCH.ALERT_REMEDIATION_LOG", remediation_sql)
        self.assertIn("'STATUS_REVIEW' AS REMEDIATION_MODE", remediation_sql)
        self.assertIn("'Task rerun review' AS ACTION_TYPE", remediation_sql)
        self.assertIn("EXECUTE TASK IDENTIFIER", remediation_sql)
        self.assertIn("TASK_HISTORY", remediation_sql)

    def test_command_center_setup_includes_review_gated_objects(self):
        setup_sql = alerts.build_alert_command_center_setup_sql().upper()
        materialize_sql = alerts.build_alert_event_materialization_sql(days=999).upper()

        self.assertIn("CREATE TABLE IF NOT EXISTS DBA_MAINT_DB.OVERWATCH.ALERT_CONFIG", setup_sql)
        self.assertIn("ALERT_DATA_QUALITY_CHECKS", setup_sql)
        self.assertIn("ALERT_NATIVE_OBJECT_REGISTRY", setup_sql)
        self.assertIn("ALERT_REMEDIATION_POLICY", setup_sql)
        self.assertIn("ALERT_NATIVE_DEPLOYMENT_REVIEW_V", setup_sql)
        self.assertIn("SP_OVERWATCH_STAGE_ALERT_REMEDIATION_DRY_RUN", setup_sql)
        self.assertIn("DATEADD('DAY', -90", materialize_sql)
        self.assertIn("MERGE INTO DBA_MAINT_DB.OVERWATCH.ALERT_EVENTS", materialize_sql)

    def test_signal_catalog_and_readiness_tables_remain_bounded(self):
        catalog = alerts.build_alert_signal_query_catalog(hours=999)
        privileges = alerts.build_alert_required_privileges()
        integrations = alerts.build_alert_optional_integrations()
        runbook = alerts.build_alert_command_center_runbook_markdown()

        self.assertFalse(catalog.empty)
        self.assertIn("SQL", catalog.columns)
        self.assertTrue(catalog["SQL"].str.contains("DATEADD\\('hour', -168", regex=True).any())
        self.assertIn("Imported privileges on SNOWFLAKE database", set(privileges["PRIVILEGE_ASSUMPTION"]))
        self.assertIn("Snowflake ALERT objects", set(integrations["INTEGRATION"]))
        self.assertIn("should not silently mutate Snowflake objects", runbook)


if __name__ == "__main__":
    unittest.main()
