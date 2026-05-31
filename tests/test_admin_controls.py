from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections.dba_tools import _build_warehouse_setting_plan  # noqa: E402
from sections.security_access import (  # noqa: E402
    _build_access_action_queue_record,
    _build_role_grant_change_plan,
)
from utils.admin import build_admin_audit_insert_sql  # noqa: E402
from utils.action_queue import (  # noqa: E402
    action_queue_environment_clause,
    action_queue_environment_values,
    action_queue_fixed_missing_fields,
    build_action_queue_ddl,
    update_action_status_with_evidence,
)


class AdminControlTests(unittest.TestCase):
    def test_warehouse_setting_plan_only_alters_changed_values(self):
        current = pd.Series({
            "name": "WH_ALFA_BI",
            "size": "Small",
            "auto_suspend": 600,
            "auto_resume": "true",
            "statement_timeout_in_seconds": 3600,
            "statement_queued_timeout_in_seconds": 600,
            "max_concurrency_level": 8,
            "scaling_policy": "STANDARD",
            "min_cluster_count": 1,
            "max_cluster_count": 1,
            "enable_query_acceleration": "false",
            "query_acceleration_max_scale_factor": 8,
        })
        plan = _build_warehouse_setting_plan(
            "WH_ALFA_BI",
            current,
            {
                "WAREHOUSE_SIZE": "Small",
                "AUTO_SUSPEND": 60,
                "AUTO_RESUME": True,
                "STATEMENT_TIMEOUT_IN_SECONDS": 3600,
                "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS": 600,
                "MAX_CONCURRENCY_LEVEL": 8,
                "SCALING_POLICY": "STANDARD",
                "MIN_CLUSTER_COUNT": 1,
                "MAX_CLUSTER_COUNT": 2,
                "ENABLE_QUERY_ACCELERATION": True,
                "QUERY_ACCELERATION_MAX_SCALE_FACTOR": 8,
            },
        )

        self.assertIn('ALTER WAREHOUSE "WH_ALFA_BI" SET', plan["alter_sql"])
        self.assertIn("AUTO_SUSPEND = 60", plan["alter_sql"])
        self.assertIn("MAX_CLUSTER_COUNT = 2", plan["alter_sql"])
        self.assertIn("ENABLE_QUERY_ACCELERATION = TRUE", plan["alter_sql"])
        self.assertNotIn("AUTO_RESUME", plan["alter_sql"])
        self.assertIn("AUTO_SUSPEND = 600", plan["rollback_sql"])
        self.assertIn("MAX_CLUSTER_COUNT = 1", plan["rollback_sql"])
        self.assertEqual(plan["confirmation_text"], "ALTER WH_ALFA_BI")
        self.assertIn('SHOW GRANTS ON WAREHOUSE "WH_ALFA_BI"', plan["preflight_sql"])
        self.assertIn("Serverless cost risk", plan["control_context"])

    def test_warehouse_setting_plan_skips_unknown_current_values(self):
        current = pd.Series({
            "name": "WH_ALFA_BI",
            "size": "Small",
            "auto_suspend": 600,
        })
        plan = _build_warehouse_setting_plan(
            "WH_ALFA_BI",
            current,
            {
                "WAREHOUSE_SIZE": "Medium",
                "MAX_CONCURRENCY_LEVEL": 5,
            },
        )

        self.assertIn("WAREHOUSE_SIZE = MEDIUM", plan["alter_sql"])
        self.assertNotIn("MAX_CONCURRENCY_LEVEL", plan["alter_sql"])
        self.assertEqual(plan["skipped"][0]["PARAMETER"], "MAX_CONCURRENCY_LEVEL")

    def test_admin_audit_sql_matches_setup_table_columns(self):
        sql = build_admin_audit_insert_sql(
            company="ALFA",
            environment="PROD",
            app_user="OVERWATCH",
            snowflake_user="DBA_USER",
            snowflake_role="SYSADMIN",
            action_type="ALTER WAREHOUSE",
            target_object="WH_ALFA_BI",
            sql_text='ALTER WAREHOUSE "WH_ALFA_BI" SET AUTO_SUSPEND = 60;',
            confirmation_text="ALTER WH_ALFA_BI",
            control_context="AUTO_SUSPEND: 600 -> 60",
            result_status="SUCCESS",
            result_message="Warehouse change completed.",
        ).upper()

        self.assertIn("TARGET_OBJECT", sql)
        self.assertIn("SQL_HASH", sql)
        self.assertNotIn("OBJECT_NAME", sql)
        self.assertNotIn("SNOWFLAKE_WAREHOUSE", sql)
        self.assertNotIn("ACTION_ID,", sql)

    def test_role_grant_plan_builds_sql_rollback_and_preflight(self):
        plan = _build_role_grant_change_plan(
            "grant",
            "app_readonly",
            "user",
            "etl_runner",
            "INC12345 approved least-privilege access",
            "ALFA Finance Data Owner",
            "SECURITYADMIN_APPROVER",
            "INC12345",
            "2026-06-30",
        )

        self.assertEqual(plan["change_sql"], 'GRANT ROLE "APP_READONLY" TO USER "ETL_RUNNER";')
        self.assertEqual(plan["rollback_sql"], 'REVOKE ROLE "APP_READONLY" FROM USER "ETL_RUNNER";')
        self.assertEqual(plan["confirmation_text"], "GRANT APP_READONLY TO USER ETL_RUNNER")
        self.assertTrue(plan["metadata_complete"])
        self.assertEqual(plan["access_owner"], "ALFA Finance Data Owner")
        self.assertEqual(plan["approver"], "SECURITYADMIN_APPROVER")
        self.assertEqual(plan["ticket_id"], "INC12345")
        self.assertEqual(plan["review_by"], "2026-06-30")
        self.assertIn('SHOW GRANTS OF ROLE "APP_READONLY"', plan["preflight_sql"])
        self.assertIn('SHOW GRANTS TO USER "ETL_RUNNER"', plan["preflight_sql"])
        self.assertIn("DIRECT_MANAGE_GRANTS_PRIVILEGES", plan["preflight_sql"].upper())
        self.assertIn("blast radius is the named user only", plan["preflight_sql"])
        self.assertIn("Post-change verification", plan["verification_sql"])
        self.assertIn("INC12345", plan["control_context"])
        self.assertIn("Account-role grants are account-wide", plan["control_context"])

    def test_role_revoke_plan_from_role_is_high_risk_with_inverse_rollback(self):
        plan = _build_role_grant_change_plan(
            "REVOKE",
            "SECURITYADMIN",
            "ROLE",
            "APP_SUPPORT",
            "INC12346 cleanup inherited admin access",
            "DBA Platform Owner",
            "Security Director",
            "INC12346",
            "2026-06-15",
        )

        self.assertEqual(plan["change_sql"], 'REVOKE ROLE "SECURITYADMIN" FROM ROLE "APP_SUPPORT";')
        self.assertEqual(plan["rollback_sql"], 'GRANT ROLE "SECURITYADMIN" TO ROLE "APP_SUPPORT";')
        self.assertEqual(plan["risk_level"], "Critical")
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES", plan["preflight_sql"])
        self.assertIn("direct_users_with_impacted_role", plan["preflight_sql"])
        self.assertIn("Inheritance risk", plan["control_context"])

    def test_role_grant_plan_rejects_database_role_scope(self):
        with self.assertRaises(ValueError):
            _build_role_grant_change_plan(
                "GRANT",
                "ALFA_EDW_PROD.PUBLIC.DB_ROLE",
                "USER",
                "ETL_RUNNER",
                "Not supported yet",
            )

    def test_role_grant_plan_requires_access_accountability_metadata(self):
        plan = _build_role_grant_change_plan(
            "GRANT",
            "APP_READONLY",
            "USER",
            "ETL_RUNNER",
            "INC12345 approved least-privilege access",
        )

        self.assertFalse(plan["metadata_complete"])
        self.assertIn("access owner", plan["missing_metadata"])
        self.assertIn("approver", plan["missing_metadata"])
        self.assertIn("ticket", plan["missing_metadata"])
        self.assertIn("review/expiry date", plan["missing_metadata"])
        self.assertIn("Missing accountability metadata", plan["control_context"])

    def test_access_action_queue_record_carries_owner_ticket_and_verification(self):
        plan = _build_role_grant_change_plan(
            "GRANT",
            "APP_READONLY",
            "USER",
            "ETL_RUNNER",
            "INC12345 approved least-privilege access",
            "ALFA Finance Data Owner",
            "SECURITYADMIN_APPROVER",
            "INC12345",
            "2026-06-30",
        )

        action = _build_access_action_queue_record(plan, "ALFA")

        self.assertEqual(action["Source"], "Security Posture - Role & Grant Change Control")
        self.assertEqual(action["Owner"], "ALFA Finance Data Owner")
        self.assertEqual(action["Company"], "ALFA")
        self.assertIn("INC12345", action["Finding"])
        self.assertIn("SECURITYADMIN_APPROVER", action["Action"])
        self.assertIn("Post-change verification SQL", action["Proof Query"])
        self.assertEqual(action["Generated SQL Fix"], 'GRANT ROLE "APP_READONLY" TO USER "ETL_RUNNER";')

    def test_action_queue_ddl_and_filters_are_environment_aware(self):
        ddl = build_action_queue_ddl().upper()
        setup_sql = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8").upper()

        self.assertIn("ENVIRONMENT", ddl)
        self.assertIn("VERIFICATION_STATUS", ddl)
        self.assertIn("VERIFICATION_RESULT", ddl)
        self.assertIn("MEASURED_DELTA", ddl)
        self.assertIn("COMPANY", ddl)
        self.assertIn("ALTER TABLE OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS VERIFICATION_STATUS", setup_sql)
        self.assertIn("ALTER TABLE OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS VERIFIED_AT", setup_sql)

        dev_values = action_queue_environment_values("DEV_ALL")
        self.assertIn("DEV_ALL", dev_values)
        self.assertIn("ALFA_EDW_DEV", dev_values)
        self.assertIn("ALFA_EDW_SIT", dev_values)
        self.assertIn("NO DATABASE CONTEXT", dev_values)

        prod_clause = action_queue_environment_clause("ENVIRONMENT", "PROD")
        self.assertIn("PROD", prod_clause)
        self.assertIn("NO DATABASE CONTEXT", prod_clause)
        self.assertEqual(action_queue_environment_clause("ENVIRONMENT", "ALL"), "")

    def test_fixed_action_status_requires_verification_evidence(self):
        missing = action_queue_fixed_missing_fields(
            status="Fixed",
            verification_notes="short",
            verification_result="",
        )

        self.assertIn("verification notes", missing)
        self.assertIn("verification result", missing)
        self.assertEqual(action_queue_fixed_missing_fields(
            status="In Progress",
            verification_notes="",
            verification_result="",
        ), [])

    def test_fixed_action_status_update_writes_verification_columns(self):
        class FakeResult:
            def __init__(self, rows=None):
                self._rows = rows or []

            def collect(self):
                return self._rows

        class FakeSession:
            def __init__(self):
                self.sql_texts = []

            def sql(self, sql_text):
                self.sql_texts.append(sql_text)
                if "SHOW COLUMNS" in sql_text:
                    return FakeResult([{"name": "present"}])
                return FakeResult([])

        session = FakeSession()
        update_action_status_with_evidence(
            session,
            "ABC123",
            "Fixed",
            reason="Resolved under INC777",
            verification_notes="Warehouse auto-suspend reduced idle runtime after owner review.",
            verification_result="Current 7-day metered credits are 30 percent lower than the baseline window.",
            verification_query="SELECT 1;",
            ticket_id="INC777",
            approver="DBA_MANAGER",
            baseline_value=100,
            current_value=70,
            measured_delta=-30,
        )
        update_sql = session.sql_texts[-1].upper()

        self.assertIn("VERIFICATION_STATUS = 'VERIFIED'", update_sql)
        self.assertIn("VERIFICATION_RESULT", update_sql)
        self.assertIn("VERIFIED_AT = CURRENT_TIMESTAMP()", update_sql)
        self.assertIn("TICKET_ID", update_sql)
        self.assertIn("MEASURED_DELTA = COALESCE(-30.0", update_sql)


if __name__ == "__main__":
    unittest.main()
