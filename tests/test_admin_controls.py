from pathlib import Path
import re
import sys
import unittest

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections.dba_tools import _build_warehouse_setting_plan  # noqa: E402
from sections.security_access import (  # noqa: E402
    _build_access_action_queue_record,
    _build_role_grant_change_plan,
)
from utils.admin import (  # noqa: E402
    ADMIN_ACTIONS_KEY,
    admin_actions_default_enabled,
    admin_actions_enabled,
    build_admin_audit_insert_sql,
    initialize_admin_actions_default,
)
from utils.action_queue import (  # noqa: E402
    action_queue_environment_clause,
    action_queue_environment_values,
    action_queue_fixed_missing_fields,
    action_queue_default_due_days,
    build_safe_verification_query,
    build_action_queue_ddl,
    build_cost_savings_verification_health_sql,
    build_cost_savings_verification_sql,
    enrich_action_queue_view,
    summarize_verification_frame,
    update_action_status_with_evidence,
    verification_query_safety_issues,
)
from utils.owner_directory import build_owner_directory_ddl  # noqa: E402
from utils.futures_governance import build_platform_futures_evidence_ddl  # noqa: E402
from utils.workload_audit import build_workload_recovery_audit_ddl  # noqa: E402


class AdminControlTests(unittest.TestCase):
    def test_admin_actions_default_on_for_full_privilege_roles(self):
        previous = dict(st.session_state)
        try:
            for role in ("ACCOUNTADMIN", "SYSADMIN", "SNOW_ACCOUNTADMIN", "SNOW_ACCOUNTADMINS", "SNOW_SYSADMIN"):
                with self.subTest(role=role):
                    st.session_state.clear()
                    st.session_state["_overwatch_current_role"] = role

                    self.assertTrue(admin_actions_default_enabled())
                    initialize_admin_actions_default()
                    self.assertTrue(st.session_state[ADMIN_ACTIONS_KEY])
                    self.assertTrue(admin_actions_enabled())
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_admin_actions_default_off_for_non_admin_roles_and_manual_choice_sticks(self):
        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["_overwatch_current_role"] = "APP_READONLY"
            self.assertFalse(admin_actions_default_enabled())
            initialize_admin_actions_default()
            self.assertFalse(st.session_state[ADMIN_ACTIONS_KEY])

            st.session_state["_overwatch_current_role"] = "SNOW_ACCOUNTADMINS"
            initialize_admin_actions_default()
            self.assertTrue(st.session_state[ADMIN_ACTIONS_KEY])

            st.session_state.clear()
            st.session_state["_overwatch_current_role"] = "ACCOUNTADMIN"
            st.session_state[ADMIN_ACTIONS_KEY] = False
            initialize_admin_actions_default()
            self.assertFalse(st.session_state[ADMIN_ACTIONS_KEY])

            st.session_state.clear()
            st.session_state["_overwatch_current_role"] = "APP_READONLY"
            st.session_state[ADMIN_ACTIONS_KEY] = True
            initialize_admin_actions_default()
            self.assertTrue(st.session_state[ADMIN_ACTIONS_KEY])
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

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
        self.assertIn("OWNER_APPROVAL_STATUS", ddl)
        self.assertIn("RECOVERY_SLA_STATE", ddl)
        self.assertIn("RECOVERY_EVIDENCE", ddl)
        self.assertIn("OWNER_EMAIL", ddl)
        self.assertIn("ONCALL_PRIMARY", ddl)
        self.assertIn("APPROVAL_GROUP", ddl)
        self.assertIn("OWNER_SOURCE", ddl)
        self.assertIn("RECOVERY_AUDIT_STATE", ddl)
        self.assertIn("COMPANY", ddl)
        self.assertIn("ALTER TABLE OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS VERIFICATION_STATUS", setup_sql)
        self.assertIn("ALTER TABLE OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS VERIFIED_AT", setup_sql)
        self.assertIn("ALTER TABLE OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS OWNER_APPROVAL_STATUS", setup_sql)
        self.assertIn("ALTER TABLE OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS RECOVERY_EVIDENCE", setup_sql)
        self.assertIn("ALTER TABLE OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS OWNER_EMAIL", setup_sql)
        self.assertIn("ALTER TABLE OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS ONCALL_PRIMARY", setup_sql)
        self.assertIn("ALTER TABLE OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS APPROVAL_GROUP", setup_sql)
        self.assertIn("ALTER TABLE OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS OWNER_SOURCE", setup_sql)
        self.assertIn("ALTER TABLE OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS RECOVERY_AUDIT_STATE", setup_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS OVERWATCH_DBA_CHECKLIST_HISTORY", setup_sql)
        self.assertIn("QUEUE_READINESS", setup_sql)
        self.assertIn("CONTROL_READINESS", setup_sql)
        self.assertIn("VERIFICATION_QUERY", setup_sql)
        self.assertIn("CREATE TRANSIENT TABLE IF NOT EXISTS FACT_ACCOUNT_HEALTH_OPERABILITY_DAILY", setup_sql)
        self.assertIn("ACCESS_HYGIENE_ROWS", setup_sql)
        self.assertIn("FAILED_LOGIN_ROWS", setup_sql)
        self.assertIn("PRIVILEGED_GRANT_ROWS", setup_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS OVERWATCH_WORKLOAD_RECOVERY_AUDIT", setup_sql)
        self.assertIn("CREATE OR REPLACE VIEW OVERWATCH_WORKLOAD_RECOVERY_AUDIT_LATEST_V", setup_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS OVERWATCH_PLATFORM_FUTURES_CONTROL_REGISTER", setup_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS OVERWATCH_PLATFORM_FUTURES_EVIDENCE", setup_sql)
        self.assertIn("CREATE OR REPLACE VIEW OVERWATCH_PLATFORM_FUTURES_EVIDENCE_LATEST_V", setup_sql)
        self.assertIn("CREATE OR REPLACE VIEW OVERWATCH_PLATFORM_FUTURES_CONTROL_COVERAGE_V", setup_sql)
        self.assertIn("ADAPTIVE_COMPUTE_READINESS", setup_sql)
        self.assertIn("ADAPTIVE_COMPUTE_DEFAULT", setup_sql)
        self.assertIn("AI_AGENT_MCP_GOVERNANCE", setup_sql)
        self.assertIn("AI_SECURITY_GUARDRAILS", setup_sql)
        self.assertIn("AI_SECURITY_DEFAULT", setup_sql)
        self.assertIn("COVERAGE_STATE", setup_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS OVERWATCH_COST_SAVINGS_VERIFICATION_RUN", setup_sql)
        self.assertIn("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_VERIFY_COST_SAVINGS", setup_sql)
        self.assertIn("CREATE OR REPLACE VIEW OVERWATCH_COST_SAVINGS_VERIFICATION_HEALTH_V", setup_sql)
        self.assertIn("CREATE OR REPLACE TASK OVERWATCH_COST_SAVINGS_VERIFY", setup_sql)
        self.assertIn("WAREHOUSE_METERING_HISTORY", setup_sql)
        self.assertIn("SAVINGS VERIFIED", setup_sql)
        self.assertIn("TASK_HEALTH_STATE", setup_sql)
        self.assertIn("FAILED_RUNS_7D", setup_sql)
        self.assertIn("TASK STALE", setup_sql)
        self.assertIn("ESCALATION_TARGET", setup_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS OVERWATCH_CHANGE_CONTROL_EVIDENCE", setup_sql)
        self.assertIn("CHANGE_TICKET_ID", setup_sql)
        self.assertIn("IAC_RECONCILIATION_STATE", setup_sql)
        self.assertIn("EXECUTION_AUDIT_STATE", setup_sql)
        self.assertIn("CREATE TRANSIENT TABLE IF NOT EXISTS FACT_CHANGE_CONTROL_OPERABILITY_DAILY", setup_sql)
        self.assertIn("CONTROL_SOURCE", setup_sql)
        self.assertIn("CONTROL_RANK", setup_sql)
        self.assertIn("CHANGE_EVIDENCE_READINESS", setup_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS OVERWATCH_WAREHOUSE_SETTING_REVIEW", setup_sql)
        self.assertIn("BASELINE_CAPACITY_SCORE", setup_sql)
        self.assertIn("SAVINGS_VERIFICATION_REQUIRED", setup_sql)
        self.assertIn("EXECUTED_SQL_HASH", setup_sql)
        self.assertIn("POST_CHANGE_VERIFICATION_STATUS", setup_sql)
        self.assertIn("AUDIT_READINESS", setup_sql)
        self.assertIn("CREATE TRANSIENT TABLE IF NOT EXISTS FACT_WAREHOUSE_OPERABILITY_DAILY", setup_sql)
        self.assertIn("QUEUE_PRESSURE_ROWS", setup_sql)
        self.assertIn("SPILL_PRESSURE_ROWS", setup_sql)
        self.assertIn("CREDIT_ALLOCATION_METHOD", setup_sql)
        self.assertIn("ESTIMATED FROM WAREHOUSE METERING ALLOCATED BY QUERY SHARE", setup_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS OVERWATCH_SECURITY_ACCESS_REVIEW", setup_sql)
        self.assertIn("DATABASE_CONTEXT", setup_sql)
        self.assertIn("ROLE_CAPABILITY_STATE", setup_sql)
        self.assertIn("ACCESS_TICKET_ID", setup_sql)
        self.assertIn("REVIEW_READINESS", setup_sql)
        self.assertIn("CONTROL_BLOCKERS", setup_sql)
        self.assertIn("NEXT_CONTROL_ACTION", setup_sql)
        self.assertIn("CREATE TRANSIENT TABLE IF NOT EXISTS FACT_SECURITY_OPERABILITY_DAILY", setup_sql)
        self.assertIn("REVIEW_BLOCKER_ROWS", setup_sql)
        self.assertIn("CAPABILITY_PROOF_ROWS", setup_sql)
        self.assertIn("NO_DATABASE_CONTEXT_ROWS", setup_sql)
        self.assertIn("CREATE TRANSIENT TABLE IF NOT EXISTS FACT_CHARGEBACK_DAILY", setup_sql)
        self.assertIn("ALLOCATED_CREDITS", setup_sql)
        self.assertIn("OWNER_EVIDENCE", setup_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS OVERWATCH_OWNER_TAG_NAMES", setup_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS OVERWATCH_OWNER_DIRECTORY", setup_sql)
        self.assertIn("CREATE OR REPLACE VIEW OVERWATCH_OWNER_DIRECTORY_ACTIVE_V", setup_sql)
        self.assertIn("COMPUTE_WH_EXECUTION", setup_sql)
        self.assertIn("ALFA_EDW_PROD_DATABASE", setup_sql)
        self.assertIn("ALFA_EDW_DEV_DATABASES", setup_sql)
        self.assertIn("ARCHITECTURE_DEFAULT", setup_sql)
        self.assertIn("ONCALL_PRIMARY", setup_sql)
        self.assertIn("APPROVAL_GROUP", setup_sql)
        self.assertIn("CREATE TRANSIENT TABLE IF NOT EXISTS DIM_COST_OWNER_TAG", setup_sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES", setup_sql)
        self.assertIn("WAREHOUSE_TAG:", setup_sql)
        self.assertIn("DATABASE_TAG:", setup_sql)
        self.assertIn("DELETE FROM FACT_CHARGEBACK_DAILY", setup_sql)
        self.assertIn("INSERT INTO FACT_CHARGEBACK_DAILY", setup_sql)
        self.assertIn("DEFAULT_ALERT_EMAIL", setup_sql)
        self.assertIn("JDEES@ALFAINS.COM", setup_sql)
        self.assertIn("ALERT_DELIVERY_METHOD", setup_sql)
        self.assertIn("EMAIL_TARGET", setup_sql)
        self.assertIn("EMAIL_SUBJECT", setup_sql)
        self.assertIn("EMAIL_BODY", setup_sql)
        self.assertIn("EMAIL_READY", setup_sql)
        self.assertIn("STATUS_REASON", setup_sql)
        self.assertIn("LAST_STATUS_BY", setup_sql)
        self.assertIn("LAST_DELIVERY_AT", setup_sql)
        self.assertIn("DELIVERY_LOG_COUNT", setup_sql)
        self.assertIn("ESCALATION_ACK_BY", setup_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS OVERWATCH_ALERT_DELIVERY_LOG", setup_sql)
        self.assertIn("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_SEND_ALERT_DIGEST", setup_sql)
        self.assertIn("SYSTEM$SEND_EMAIL", setup_sql)
        self.assertIn("EMAIL_DRY_RUN", setup_sql)
        self.assertIn("ROUTED_TO_ACTION_QUEUE_AT", setup_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS OVERWATCH_ALERT_RULES", setup_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS OVERWATCH_ALERT_RULE_AUDIT", setup_sql)
        self.assertIn("CREATE TRANSIENT TABLE IF NOT EXISTS FACT_TASK_CRITICAL_PATH", setup_sql)
        self.assertIn("INSERT INTO FACT_TASK_CRITICAL_PATH", setup_sql)
        self.assertIn("OWNER_ROLE", setup_sql)
        self.assertIn("APPROVAL_PATH", setup_sql)
        self.assertIn("SOURCE_FRESHNESS", setup_sql)
        self.assertIn("CREATE OR REPLACE VIEW OVERWATCH_ALERT_TRIAGE_V", setup_sql)
        self.assertIn("SLA_HOURS", setup_sql)
        self.assertIn("TRIAGE_PRIORITY", setup_sql)
        self.assertIn("PROCEDURE_FAILURE_OR_SPIKE", setup_sql)
        self.assertIn("CREATE OR REPLACE TASK OVERWATCH_ANOMALY_CHECK", setup_sql)
        self.assertIn("TASK FAILURE", setup_sql)
        self.assertIn("STORED PROCEDURE", setup_sql)
        self.assertIn("COST SAVINGS VERIFICATION FAILURE", setup_sql)
        self.assertIn("COST_SAVINGS_VERIFIER_FAILURE", setup_sql)
        self.assertIn("OVERWATCH_COST_SAVINGS_VERIFY", setup_sql)
        self.assertIn("GRANT/REVOKE ACTIVITY", setup_sql)
        self.assertIn("WAREHOUSE SETTING CHANGE", setup_sql)

        savings_verification_sql = build_cost_savings_verification_sql().upper()
        self.assertIn("OVERWATCH_COST_SAVINGS_VERIFICATION_RUN", savings_verification_sql)
        self.assertIn("SP_OVERWATCH_VERIFY_COST_SAVINGS", savings_verification_sql)
        self.assertIn("OVERWATCH_COST_SAVINGS_VERIFY", savings_verification_sql)
        self.assertIn("CURRENT_VALUE = V.POST_PERIOD_VALUE", savings_verification_sql)
        self.assertIn("VERIFICATION_STATUS = IFF", savings_verification_sql)
        self.assertIn("OVERWATCH_COST_SAVINGS_VERIFICATION_HEALTH_V", savings_verification_sql)
        self.assertIn("TASK_HEALTH_STATE", savings_verification_sql)
        self.assertIn("FAILED_RUNS_7D", savings_verification_sql)
        self.assertIn("ALTER TASK", savings_verification_sql)

        savings_health_sql = build_cost_savings_verification_health_sql().upper()
        self.assertIn("OVERWATCH_COST_SAVINGS_VERIFICATION_HEALTH_V", savings_health_sql)
        self.assertIn("EVIDENCE_REQUIRED_LAST_RUN", savings_health_sql)
        self.assertIn("NEXT_ACTION", savings_health_sql)

        owner_sql = build_owner_directory_ddl().upper()
        self.assertIn("OVERWATCH_OWNER_DIRECTORY", owner_sql)
        self.assertIn("OVERWATCH_OWNER_DIRECTORY_ACTIVE_V", owner_sql)
        self.assertIn("COMPUTE_WH_EXECUTION", owner_sql)
        self.assertIn("ALFA_EDW_PROD_DATABASE", owner_sql)
        self.assertIn("ARCHITECTURE_DEFAULT", owner_sql)

        recovery_audit_sql = build_workload_recovery_audit_ddl().upper()
        self.assertIn("OVERWATCH_WORKLOAD_RECOVERY_AUDIT", recovery_audit_sql)
        self.assertIn("VERIFICATION_RESULT", recovery_audit_sql)

        platform_futures_sql = build_platform_futures_evidence_ddl().upper()
        self.assertIn("OVERWATCH_PLATFORM_FUTURES_CONTROL_REGISTER", platform_futures_sql)
        self.assertIn("OVERWATCH_PLATFORM_FUTURES_EVIDENCE", platform_futures_sql)
        self.assertIn("OVERWATCH_PLATFORM_FUTURES_CONTROL_COVERAGE_V", platform_futures_sql)
        self.assertIn("AI_SECURITY_GUARDRAILS", platform_futures_sql)
        self.assertIn("RAW_EVIDENCE         VARIANT", platform_futures_sql)

        dev_values = action_queue_environment_values("DEV_ALL")
        self.assertIn("DEV_ALL", dev_values)
        self.assertIn("ALFA_EDW_DEV", dev_values)
        self.assertIn("ALFA_EDW_SIT", dev_values)
        self.assertIn("NO DATABASE CONTEXT", dev_values)

        prod_clause = action_queue_environment_clause("ENVIRONMENT", "PROD")
        self.assertIn("PROD", prod_clause)
        self.assertIn("NO DATABASE CONTEXT", prod_clause)
        self.assertEqual(action_queue_environment_clause("ENVIRONMENT", "ALL"), "")

    def test_overwatch_task_warehouses_match_intended_runtime(self):
        setup_sql = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8")
        task_blocks = re.findall(
            r"CREATE OR REPLACE TASK\s+(OVERWATCH_[A-Z0-9_]+)\s+(.*?);",
            setup_sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
        warehouses = {}
        for task_name, body in task_blocks:
            match = re.search(r"\bWAREHOUSE\s*=\s*([A-Z0-9_]+)", body, flags=re.IGNORECASE)
            self.assertIsNotNone(match, f"{task_name} is missing an explicit WAREHOUSE clause")
            warehouses[task_name.upper()] = match.group(1).upper()

        self.assertEqual(
            set(warehouses),
            {
                "OVERWATCH_COST_SAVINGS_VERIFY",
                "OVERWATCH_ANOMALY_CHECK",
                "OVERWATCH_LOAD_HOURLY",
                "OVERWATCH_LOAD_CORTEX",
                "OVERWATCH_REFRESH_CONTROL_ROOM",
                "OVERWATCH_LOAD_DAILY",
            },
        )
        self.assertEqual(
            warehouses,
            {
                "OVERWATCH_COST_SAVINGS_VERIFY": "COMPUTE_WH",
                "OVERWATCH_ANOMALY_CHECK": "COMPUTE_WH",
                "OVERWATCH_LOAD_HOURLY": "COMPUTE_WH",
                "OVERWATCH_LOAD_CORTEX": "COMPUTE_WH",
                "OVERWATCH_REFRESH_CONTROL_ROOM": "COMPUTE_WH",
                "OVERWATCH_LOAD_DAILY": "COMPUTE_WH",
            },
        )
        self.assertEqual(
            {task: warehouse for task, warehouse in warehouses.items() if not warehouse.endswith("_WH")},
            {},
        )

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
            due_date="2026-06-01",
            baseline_value=100,
            current_value=70,
            measured_delta=-30,
            owner_approval_status="Approved",
            owner_approval_note="Pipeline owner approved recovery after INC777.",
            recovery_sla_state="Recovered Within SLA",
            recovery_sla_hours=1.5,
            recovery_sla_target_hours=4,
            recovery_evidence="Latest task run succeeded 1.5 hours after failure.",
        )
        update_sql = session.sql_texts[-1].upper()

        self.assertIn("VERIFICATION_STATUS = 'VERIFIED'", update_sql)
        self.assertIn("VERIFICATION_RESULT", update_sql)
        self.assertIn("VERIFIED_AT = CURRENT_TIMESTAMP()", update_sql)
        self.assertIn("TICKET_ID", update_sql)
        self.assertIn("DUE_DATE", update_sql)
        self.assertIn("2026-06-01", update_sql)
        self.assertIn("MEASURED_DELTA = COALESCE(-30.0", update_sql)
        self.assertIn("OWNER_APPROVAL_STATUS", update_sql)
        self.assertIn("OWNER_APPROVAL_BY", update_sql)
        self.assertIn("OWNER_APPROVAL_AT", update_sql)
        self.assertIn("RECOVERY_SLA_STATE", update_sql)
        self.assertIn("RECOVERY_EVIDENCE", update_sql)

    def test_action_queue_triage_fields_expose_due_state_and_evidence_gaps(self):
        self.assertEqual(action_queue_default_due_days("Critical"), 1)
        self.assertEqual(action_queue_default_due_days("unknown"), 7)
        df = pd.DataFrame([
            {
                "ACTION_ID": "OVERDUE1",
                "STATUS": "New",
                "SEVERITY": "Critical",
                "CATEGORY": "Cost Control",
                "OWNER": "FINOPS_OWNER",
                "TICKET_ID": "",
                "APPROVER": "",
                "DUE_DATE": "2026-05-30",
                "VERIFICATION_QUERY": "SELECT * FROM COST_PROOF",
                "PROOF_QUERY": "",
                "BASELINE_VALUE": 100,
                "CURRENT_VALUE": 140,
            },
            {
                "ACTION_ID": "FIXED1",
                "STATUS": "Fixed",
                "SEVERITY": "High",
                "CATEGORY": "Task & Procedure Reliability",
                "OWNER": "TASK_OWNER",
                "TICKET_ID": "INC1",
                "APPROVER": "DBA_MANAGER",
                "DUE_DATE": "2026-05-31",
                "VERIFICATION_STATUS": "Verified",
                "VERIFICATION_RESULT": "Latest task run succeeded within the baseline.",
                "VERIFICATION_QUERY": "SELECT * FROM TASK_HISTORY",
                "BASELINE_VALUE": 300,
                "CURRENT_VALUE": 240,
                "OWNER_APPROVAL_STATUS": "Approved",
                "RECOVERY_SLA_STATE": "Recovered Within SLA",
                "RECOVERY_EVIDENCE": "Successful recovery run attached.",
            },
            {
                "ACTION_ID": "TASKOPEN1",
                "STATUS": "In Progress",
                "SEVERITY": "High",
                "CATEGORY": "Task & Procedure Reliability",
                "OWNER": "TASK_OWNER",
                "TICKET_ID": "INC2",
                "APPROVER": "DBA_MANAGER",
                "DUE_DATE": "2026-06-01",
                "VERIFICATION_QUERY": "SELECT * FROM TASK_HISTORY",
                "BASELINE_VALUE": 300,
                "CURRENT_VALUE": 500,
                "OWNER_APPROVAL_STATUS": "Requested",
                "RECOVERY_SLA_STATE": "Open Failure",
                "RECOVERY_EVIDENCE": "",
            },
        ])

        enriched = enrich_action_queue_view(df, today="2026-05-31")
        by_id = {row["ACTION_ID"]: row for _, row in enriched.iterrows()}

        self.assertEqual(by_id["OVERDUE1"]["DUE_STATE"], "Overdue")
        self.assertIn("missing ticket/change ID", by_id["OVERDUE1"]["EVIDENCE_GAP"])
        self.assertIn("Escalate", by_id["OVERDUE1"]["NEXT_ACTION"])
        self.assertEqual(by_id["FIXED1"]["DUE_STATE"], "Closed")
        self.assertEqual(by_id["FIXED1"]["EVIDENCE_GAP"], "Verified closure")
        self.assertGreater(by_id["FIXED1"]["QUEUE_PRIORITY"], by_id["OVERDUE1"]["QUEUE_PRIORITY"])
        self.assertIn("missing owner approval", by_id["TASKOPEN1"]["EVIDENCE_GAP"])
        self.assertIn("missing recovery evidence", by_id["TASKOPEN1"]["EVIDENCE_GAP"])

    def test_verification_query_runner_rejects_non_read_only_sql(self):
        self.assertEqual(verification_query_safety_issues("SELECT * FROM FOO"), [])
        self.assertEqual(
            build_safe_verification_query("-- proof\nSELECT * FROM FOO", limit=25),
            "SELECT * FROM FOO\nLIMIT 25",
        )
        self.assertIn("exactly one", verification_query_safety_issues("SELECT * FROM FOO; DROP TABLE BAR;")[0])
        with self.assertRaises(ValueError):
            build_safe_verification_query("SELECT * FROM FOO; DROP TABLE BAR;")
        self.assertIn("must start", verification_query_safety_issues("ALTER WAREHOUSE WH SET AUTO_SUSPEND = 60")[0])
        self.assertEqual(verification_query_safety_issues("SELECT * FROM QUERY_HISTORY WHERE QUERY_TYPE = 'CALL'"), [])
        self.assertIn("CALL", verification_query_safety_issues("SELECT * FROM FOO WHERE 1=1 CALL BAD_PROC()")[0])

    def test_verification_result_summary_is_compact(self):
        df = pd.DataFrame([
            {"STATUS": "SUCCEEDED", "CREDITS_USED": 10.5},
            {"STATUS": "SUCCEEDED", "CREDITS_USED": 9.2},
        ])

        summary = summarize_verification_frame(df)

        self.assertIn("2 row(s)", summary)
        self.assertIn("STATUS", summary)
        self.assertIn("SUCCEEDED", summary)


if __name__ == "__main__":
    unittest.main()
