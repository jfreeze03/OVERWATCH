from pathlib import Path
import re
import sys
import unittest

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections.dba_tools import (  # noqa: E402
    DATA_COMPARE_EXECUTION_STAGES,
    SCHEMA_COMPARE_OBJECT_COVERAGE,
    _build_data_compare_plan,
    _build_schema_compare_frame,
    _build_warehouse_setting_plan,
    _data_compare_persistence_sql,
    _current_role_allows_alter_account,
    _data_compare_bucket_sql,
    _data_compare_forensic_sql,
    _data_compare_hash_sql,
    _data_compare_tables_sql,
    _recon_config_insert_sql,
    _recon_history_sql,
    _schema_compare_columns_sql,
    _schema_compare_ddl_script,
    _schema_compare_inventory,
    _schema_compare_persistence_sql,
    _schema_compare_show_objects_sql,
)
from utils.admin import (  # noqa: E402
    ADMIN_ACTIONS_KEY,
    admin_actions_default_enabled,
    admin_actions_enabled,
    build_admin_audit_insert_sql,
    initialize_admin_actions_default,
    log_admin_action,
)
from utils.action_queue import (  # noqa: E402
    action_queue_environment_clause,
    action_queue_environment_values,
    action_queue_fixed_missing_fields,
    action_queue_default_due_days,
    build_safe_verification_query,
    build_action_queue_ddl,
    clear_action_queue_process_cache,
    enrich_action_queue_view,
    summarize_verification_frame,
    update_action_status_with_evidence,
    verification_query_safety_issues,
)
from utils.workload_audit import build_workload_recovery_audit_ddl  # noqa: E402


class AdminControlTests(unittest.TestCase):
    def test_data_compare_builds_explicit_hash_and_diff_sql(self):
        table_sql = _data_compare_tables_sql("ALFA_EDW_DEV", "PUBLIC").upper()
        hash_sql = _data_compare_hash_sql(
            "ALFA_EDW_DEV",
            "PUBLIC",
            "POLICY_FACT",
            ["POLICY_ID", "PREMIUM_AMT"],
            "BUSINESS_DATE >= '2026-01-01'",
        )
        bucket_sql = _data_compare_bucket_sql(
            "ALFA_EDW_DEV",
            "PUBLIC",
            "ALFA_EDW_PROD",
            "PUBLIC",
            "POLICY_FACT",
            ["POLICY_ID", "PREMIUM_AMT"],
            key_columns=["POLICY_ID"],
        )
        forensic_sql = _data_compare_forensic_sql(
            "ALFA_EDW_DEV",
            "PUBLIC",
            "ALFA_EDW_PROD",
            "PUBLIC",
            "POLICY_FACT",
            ["POLICY_ID", "PREMIUM_AMT"],
            key_columns=["POLICY_ID"],
            limit=50,
        )
        no_key_sql = _data_compare_forensic_sql(
            "ALFA_EDW_DEV",
            "PUBLIC",
            "ALFA_EDW_PROD",
            "PUBLIC",
            "POLICY_FACT",
            ["POLICY_ID", "PREMIUM_AMT"],
            limit=50,
        )

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.TABLES", table_sql)
        self.assertIn("TABLE_CATALOG", table_sql)
        self.assertIn("DELETED IS NULL", table_sql)
        self.assertIn("HASH_AGG(\"POLICY_ID\", \"PREMIUM_AMT\")", hash_sql)
        self.assertIn("COUNT(*) AS actual_row_count", hash_sql)
        self.assertIn("WHERE BUSINESS_DATE >= '2026-01-01'", hash_sql)
        self.assertIn("MOD(ABS(HASH(\"POLICY_ID\")), 128)", bucket_sql)
        self.assertIn("FULL OUTER JOIN target_rows", forensic_sql)
        self.assertIn("IS NOT DISTINCT FROM", forensic_sql)
        self.assertIn("ROW_HASH_MISMATCH", forensic_sql)
        self.assertIn("source_duplicate_count", no_key_sql)
        self.assertIn("DUPLICATE_COUNT_MISMATCH", no_key_sql)

    def test_data_compare_plan_flags_structure_drift_and_missing_tables(self):
        source_tables = pd.DataFrame([
            {"TABLE_NAME": "POLICY_FACT", "TABLE_TYPE": "BASE TABLE", "METADATA_ROW_COUNT": 10},
            {"TABLE_NAME": "CLAIM_FACT", "TABLE_TYPE": "BASE TABLE", "METADATA_ROW_COUNT": 5},
        ])
        target_tables = pd.DataFrame([
            {"TABLE_NAME": "POLICY_FACT", "TABLE_TYPE": "BASE TABLE", "METADATA_ROW_COUNT": 10},
        ])
        source_columns = pd.DataFrame([
            {
                "OBJECT_NAME": "POLICY_FACT.POLICY_ID",
                "PARENT_OBJECT_NAME": "POLICY_FACT",
                "ORDINAL_POSITION": 1,
                "DATA_TYPE": "NUMBER",
                "IS_NULLABLE": "NO",
            },
            {
                "OBJECT_NAME": "POLICY_FACT.LOAD_TS",
                "PARENT_OBJECT_NAME": "POLICY_FACT",
                "ORDINAL_POSITION": 2,
                "DATA_TYPE": "TIMESTAMP_NTZ",
                "IS_NULLABLE": "YES",
            },
            {
                "OBJECT_NAME": "CLAIM_FACT.CLAIM_ID",
                "PARENT_OBJECT_NAME": "CLAIM_FACT",
                "ORDINAL_POSITION": 1,
                "DATA_TYPE": "NUMBER",
                "IS_NULLABLE": "NO",
            },
        ])
        target_columns = pd.DataFrame([
            {
                "OBJECT_NAME": "POLICY_FACT.POLICY_ID",
                "PARENT_OBJECT_NAME": "POLICY_FACT",
                "ORDINAL_POSITION": 1,
                "DATA_TYPE": "NUMBER",
                "IS_NULLABLE": "NO",
            },
        ])

        plan = _build_data_compare_plan(
            source_tables,
            target_tables,
            source_columns,
            target_columns,
            excluded_columns=[],
        )
        rows = {row["TABLE_NAME"]: row for _, row in plan.iterrows()}

        self.assertEqual(rows["POLICY_FACT"]["COMPARE_STATUS"], "Comparable with structure drift")
        self.assertEqual(rows["POLICY_FACT"]["COMPARABLE_COLUMNS"], "POLICY_ID")
        self.assertEqual(rows["POLICY_FACT"]["SOURCE_ONLY_COLUMNS"], "LOAD_TS")
        self.assertEqual(rows["CLAIM_FACT"]["COMPARE_STATUS"], "Missing in target")

    def test_schema_compare_uses_all_schema_objects_and_columns(self):
        objects_sql = _schema_compare_show_objects_sql("ALFA_EDW_DEV", "PUBLIC").upper()
        columns_sql = _schema_compare_columns_sql("ALFA_EDW_DEV", "PUBLIC").upper()

        self.assertIn("SHOW OBJECTS IN SCHEMA", objects_sql)
        self.assertIn('"ALFA_EDW_DEV"."PUBLIC"', objects_sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.COLUMNS", columns_sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.TABLES", columns_sql)
        self.assertIn("TABLE_CATALOG", columns_sql)
        self.assertIn("C.DELETED IS NULL", columns_sql)
        self.assertIn("LEFT JOIN", columns_sql)
        self.assertNotIn("TABLE_TYPE='BASE TABLE'", columns_sql.replace(" ", ""))
        self.assertIn("TASK", SCHEMA_COMPARE_OBJECT_COVERAGE)
        self.assertIn("PROCEDURE", SCHEMA_COMPARE_OBJECT_COVERAGE)
        self.assertIn("MASKING POLICY", SCHEMA_COMPARE_OBJECT_COVERAGE)
        self.assertIn("explicit-column HASH_AGG", DATA_COMPARE_EXECUTION_STAGES)

    def test_schema_compare_generates_review_sql_for_missing_objects(self):
        source_objects = pd.DataFrame([
            {"name": "POLICY_FACT", "kind": "TABLE", "rows": 10, "bytes": 2048, "owner": "SYSADMIN"},
            {"name": "SP_LOAD_POLICY", "kind": "PROCEDURE", "owner": "SYSADMIN"},
        ])
        target_objects = pd.DataFrame([
            {"name": "POLICY_FACT", "kind": "TABLE", "rows": 8, "bytes": 1024, "owner": "SYSADMIN"},
        ])
        source_columns = pd.DataFrame([
            {
                "OBJECT_NAME": "POLICY_FACT.POLICY_ID",
                "PARENT_OBJECT_NAME": "POLICY_FACT",
                "PARENT_OBJECT_TYPE": "TABLE",
                "ORDINAL_POSITION": 1,
                "DATA_TYPE": "NUMBER",
                "IS_NULLABLE": "NO",
                "OBJECT_SIGNATURE": "NUMBER nullable=NO",
            },
            {
                "OBJECT_NAME": "POLICY_FACT.LOAD_TS",
                "PARENT_OBJECT_NAME": "POLICY_FACT",
                "PARENT_OBJECT_TYPE": "TABLE",
                "ORDINAL_POSITION": 2,
                "DATA_TYPE": "TIMESTAMP_NTZ",
                "IS_NULLABLE": "YES",
                "OBJECT_SIGNATURE": "TIMESTAMP_NTZ nullable=YES",
            },
        ])
        target_columns = pd.DataFrame([
            {
                "OBJECT_NAME": "POLICY_FACT.POLICY_ID",
                "PARENT_OBJECT_NAME": "POLICY_FACT",
                "PARENT_OBJECT_TYPE": "TABLE",
                "ORDINAL_POSITION": 1,
                "DATA_TYPE": "NUMBER",
                "IS_NULLABLE": "NO",
                "OBJECT_SIGNATURE": "NUMBER nullable=NO",
            },
        ])

        source_inventory = _schema_compare_inventory(
            source_objects,
            source_columns,
            database="ALFA_EDW_DEV",
            schema="PUBLIC",
            side="SOURCE",
        )
        target_inventory = _schema_compare_inventory(
            target_objects,
            target_columns,
            database="ALFA_EDW_PROD",
            schema="PUBLIC",
            side="TARGET",
        )
        compare = _build_schema_compare_frame(
            source_inventory,
            target_inventory,
            source_db="ALFA_EDW_DEV",
            source_schema="PUBLIC",
            target_db="ALFA_EDW_PROD",
            target_schema="PUBLIC",
        )
        rows = {
            (row["OBJECT_TYPE"], row["OBJECT_NAME"]): row
            for _, row in compare.iterrows()
        }

        self.assertEqual(rows[("PROCEDURE", "SP_LOAD_POLICY")]["COMPARE_STATUS"], "Only in source")
        self.assertEqual(rows[("COLUMN", "POLICY_FACT.LOAD_TS")]["COMPARE_STATUS"], "Only in source")
        self.assertIn("GET_DDL('PROCEDURE'", rows[("PROCEDURE", "SP_LOAD_POLICY")]["DDL_REVIEW_SQL"])
        self.assertIn(", TRUE)", rows[("PROCEDURE", "SP_LOAD_POLICY")]["DDL_REVIEW_SQL"])
        self.assertIn("AS DDL_STATEMENT", rows[("PROCEDURE", "SP_LOAD_POLICY")]["DDL_REVIEW_SQL"])
        self.assertIn('"ALFA_EDW_DEV"."PUBLIC"."SP_LOAD_POLICY"', rows[("PROCEDURE", "SP_LOAD_POLICY")]["DDL_REVIEW_SQL"])
        self.assertIn('"ALFA_EDW_PROD"."PUBLIC"', rows[("PROCEDURE", "SP_LOAD_POLICY")]["DDL_REVIEW_SQL"])
        self.assertIn(
            'ALTER TABLE "ALFA_EDW_PROD"."PUBLIC"."POLICY_FACT" ADD COLUMN "LOAD_TS" TIMESTAMP_NTZ;',
            rows[("COLUMN", "POLICY_FACT.LOAD_TS")]["DDL_REVIEW_SQL"],
        )
        script = _schema_compare_ddl_script(
            compare[compare["DDL_REVIEW_SQL"].fillna("").astype(str).str.strip().ne("")],
            source_db="ALFA_EDW_DEV",
            source_schema="PUBLIC",
            target_db="ALFA_EDW_PROD",
            target_schema="PUBLIC",
        )
        self.assertIn("OVERWATCH schema compare missing-object script", script)
        self.assertIn("Only in source: PROCEDURE SP_LOAD_POLICY", script)
        self.assertIn("Only in source: COLUMN POLICY_FACT.LOAD_TS", script)
        self.assertIn("GET_DDL('PROCEDURE'", script)
        self.assertIn("ADD COLUMN", script)

    def test_schema_and_data_compare_generate_persistence_sql(self):
        schema_sql = _schema_compare_persistence_sql(
            pd.DataFrame([{
                "COMPARE_STATUS": "Only in source",
                "OBJECT_TYPE": "TABLE",
                "OBJECT_NAME": "POLICY_FACT",
                "DDL_STATEMENT": 'CREATE TABLE "ALFA_EDW_PROD"."PUBLIC"."POLICY_FACT" (POLICY_ID NUMBER);',
            }]),
            source_db="ALFA_EDW_DEV",
            source_schema="PUBLIC",
            target_db="ALFA_EDW_PROD",
            target_schema="PUBLIC",
            owner="Release DBA",
            severity="HIGH",
        ).upper()
        recon_sql = _data_compare_persistence_sql(pd.DataFrame([{
            "TABLE_NAME": "POLICY_FACT",
            "DATA_COMPARE_STATUS": "Hash mismatch",
            "SOURCE_ACTUAL_ROW_COUNT": 10,
            "TARGET_ACTUAL_ROW_COUNT": 10,
            "SOURCE_DATA_HASH": "abc",
            "TARGET_DATA_HASH": "def",
            "FORENSIC_DIFF_SQL": "SELECT * FROM DIFF_SAMPLE;",
        }]), check_id=42).upper()

        self.assertIn("INSERT INTO OVERWATCH_SCHEMA_DIFF_RESULT", schema_sql)
        self.assertIn("ALFA_EDW_DEV", schema_sql)
        self.assertIn("POLICY_FACT", schema_sql)
        self.assertIn("CREATE TABLE", schema_sql)
        self.assertIn("INSERT INTO OVERWATCH_RECON_RUN", recon_sql)
        self.assertIn("TRY_TO_NUMBER('42')", recon_sql)
        self.assertIn("HASH MISMATCH", recon_sql)
        self.assertIn("SELECT * FROM DIFF_SAMPLE", recon_sql)

        config_sql = _recon_config_insert_sql(
            check_name="Policy cutover count/hash",
            source_db="ALFA_EDW_DEV",
            source_schema="PUBLIC",
            target_db="ALFA_EDW_PROD",
            target_schema="PUBLIC",
            table_pattern="%POLICY%",
            key_columns="POLICY_ID",
            exclude_columns="LOAD_TS",
            where_clause="BUSINESS_DATE >= '2026-01-01'",
            hash_bucket_count=128,
            check_mode="COUNT_HASH_BUCKET_FORENSIC",
            severity="HIGH",
            owner="Release DBA",
        ).upper()
        history_sql = _recon_history_sql(days=14).upper()

        self.assertIn("INSERT INTO OVERWATCH_RECON_CONFIG", config_sql)
        self.assertIn("POLICY CUTOVER COUNT/HASH", config_sql)
        self.assertIn("%POLICY%", config_sql)
        self.assertIn("COUNT_HASH_BUCKET_FORENSIC", config_sql)
        self.assertIn("BUSINESS_DATE >= ''2026-01-01''", config_sql)
        self.assertIn("FROM OVERWATCH_RECON_RUN R", history_sql)
        self.assertIn("LEFT JOIN OVERWATCH_RECON_CONFIG C", history_sql)
        self.assertIn("DATEADD('DAY', -14", history_sql)

    def test_admin_actions_are_always_enabled_for_admin_only_app(self):
        previous = dict(st.session_state)
        try:
            for role in (
                "SNOW_ACCOUNTADMINS",
                "SNOW_SYSADMINS",
            ):
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

    def test_admin_actions_override_legacy_disabled_state(self):
        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["_overwatch_current_role"] = "APP_READONLY"
            self.assertTrue(admin_actions_default_enabled())
            initialize_admin_actions_default()
            self.assertTrue(st.session_state[ADMIN_ACTIONS_KEY])

            st.session_state["_overwatch_current_role"] = "SNOW_ACCOUNTADMINS"
            initialize_admin_actions_default()
            self.assertTrue(st.session_state[ADMIN_ACTIONS_KEY])

            st.session_state.clear()
            st.session_state["_overwatch_current_role"] = "ACCOUNTADMIN"
            st.session_state[ADMIN_ACTIONS_KEY] = False
            initialize_admin_actions_default()
            self.assertTrue(st.session_state[ADMIN_ACTIONS_KEY])

            st.session_state.clear()
            st.session_state["_overwatch_current_role"] = "APP_READONLY"
            st.session_state[ADMIN_ACTIONS_KEY] = True
            initialize_admin_actions_default()
            self.assertTrue(st.session_state[ADMIN_ACTIONS_KEY])
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_alter_account_guard_only_allows_accountadmin_roles(self):
        allowed_roles = ("ACCOUNTADMIN", "SNOW_ACCOUNTADMINS")
        blocked_roles = ("", "SYSADMIN", "SNOW_SYSADMINS", "SECURITYADMIN", "APP_READONLY")

        for role in allowed_roles:
            with self.subTest(role=role):
                self.assertTrue(_current_role_allows_alter_account(role))

        for role in blocked_roles:
            with self.subTest(role=role):
                self.assertFalse(_current_role_allows_alter_account(role))

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
        self.assertIn("REVIEW_GATE", plan["changes_df"].columns)
        by_param = {row["PARAMETER"]: row for _, row in plan["changes_df"].iterrows()}
        self.assertEqual(by_param["AUTO_SUSPEND"]["REVIEW_GATE"], "Availability/cost control")
        self.assertEqual(by_param["MAX_CLUSTER_COUNT"]["REVIEW_GATE"], "Capacity control")
        self.assertEqual(by_param["ENABLE_QUERY_ACCELERATION"]["REVIEW_GATE"], "Serverless cost control")
        self.assertIn("rollback SQL", by_param["MAX_CLUSTER_COUNT"]["PROOF_REQUIRED"])
        self.assertIn("Capacity control", plan["control_context"])

    def test_warehouse_setting_plan_marks_timeout_guardrails_as_review_gate(self):
        current = pd.Series({
            "name": "WH_ALFA_BI",
            "statement_timeout_in_seconds": 0,
            "statement_queued_timeout_in_seconds": 0,
        })
        plan = _build_warehouse_setting_plan(
            "WH_ALFA_BI",
            current,
            {
                "STATEMENT_TIMEOUT_IN_SECONDS": 3600,
                "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS": 600,
            },
        )
        by_param = {row["PARAMETER"]: row for _, row in plan["changes_df"].iterrows()}

        self.assertIn("STATEMENT_TIMEOUT_IN_SECONDS = 3600", plan["alter_sql"])
        self.assertIn("STATEMENT_QUEUED_TIMEOUT_IN_SECONDS = 600", plan["alter_sql"])
        self.assertIn("STATEMENT_TIMEOUT_IN_SECONDS = 0", plan["rollback_sql"])
        self.assertEqual(by_param["STATEMENT_TIMEOUT_IN_SECONDS"]["REVIEW_GATE"], "Runaway/queue control")
        self.assertEqual(by_param["STATEMENT_TIMEOUT_IN_SECONDS"]["REVIEW_DECISION"], "Timeout tightened")
        self.assertEqual(by_param["STATEMENT_QUEUED_TIMEOUT_IN_SECONDS"]["REVIEW_GATE"], "Runaway/queue control")
        self.assertIn("queued-time distribution", by_param["STATEMENT_QUEUED_TIMEOUT_IN_SECONDS"]["PROOF_REQUIRED"])
        self.assertIn("Runaway/queue control", plan["control_context"])

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

    def test_admin_audit_defaults_to_global_environment_scope(self):
        class FakeStatement:
            def __init__(self, session, sql):
                self.session = session
                self.sql = sql

            def collect(self):
                self.session.sql_texts.append(self.sql)
                return []

        class FakeSession:
            def __init__(self):
                self.sql_texts = []

            def sql(self, sql):
                return FakeStatement(self, sql)

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["active_company"] = "ALFA"
            st.session_state["global_environment"] = "PROD"
            session = FakeSession()

            saved = log_admin_action(
                session,
                action_type="ALTER WAREHOUSE",
                target_object="WH_ALFA_BI",
                sql_text='ALTER WAREHOUSE "WH_ALFA_BI" SET AUTO_SUSPEND = 60;',
                result_status="SUCCESS",
                result_message="Warehouse change completed.",
            )

            self.assertTrue(saved)
            self.assertTrue(session.sql_texts)
            self.assertIn("'PROD'", session.sql_texts[-1])
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_security_access_has_no_role_grant_change_planner(self):
        security_access_text = (APP_ROOT / "sections" / "security_access.py").read_text(encoding="utf-8")

        self.assertNotIn("_build_role_grant_change_plan", security_access_text)
        self.assertNotIn("_build_role_grant_control_board", security_access_text)
        self.assertNotIn("_build_access_action_queue_record", security_access_text)
        self.assertNotIn("Role & Grant Change Control", security_access_text)
        self.assertNotIn("Prepare Role Grant Plan", security_access_text)
        self.assertNotIn("Apply Access Change", security_access_text)

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
        queue_start = setup_sql.index("CREATE TABLE IF NOT EXISTS OVERWATCH_ACTION_QUEUE")
        queue_end = setup_sql.index(");", queue_start)
        queue_block = setup_sql[queue_start:queue_end]
        self.assertIn("VERIFICATION_STATUS", queue_block)
        self.assertIn("VERIFIED_AT", queue_block)
        self.assertIn("OWNER_APPROVAL_STATUS", queue_block)
        self.assertIn("RECOVERY_EVIDENCE", queue_block)
        self.assertIn("OWNER_EMAIL", queue_block)
        self.assertIn("ONCALL_PRIMARY", queue_block)
        self.assertIn("APPROVAL_GROUP", queue_block)
        self.assertIn("OWNER_SOURCE", queue_block)
        self.assertIn("RECOVERY_AUDIT_STATE", queue_block)
        self.assertIn("ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS ENVIRONMENT", setup_sql)
        self.assertIn("ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS OWNER_EMAIL", setup_sql)
        self.assertIn("ALTER TABLE IF EXISTS OVERWATCH_ACTION_QUEUE ADD COLUMN IF NOT EXISTS RECOVERY_AUDIT_STATE", setup_sql)
        self.assertIn("ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS OWNER", setup_sql)
        self.assertIn("ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS STATUS", setup_sql)
        self.assertIn("ALTER TABLE IF EXISTS OVERWATCH_ALERTS ADD COLUMN IF NOT EXISTS ROUTED_ACTION_COUNT", setup_sql)
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
        self.assertNotIn("CREATE TABLE IF NOT EXISTS OVERWATCH_PLATFORM_FUTURES_CONTROL_REGISTER", setup_sql)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS OVERWATCH_PLATFORM_FUTURES_EVIDENCE", setup_sql)
        self.assertNotIn("CREATE OR REPLACE VIEW OVERWATCH_PLATFORM_FUTURES_EVIDENCE_LATEST_V", setup_sql)
        self.assertNotIn("CREATE OR REPLACE VIEW OVERWATCH_PLATFORM_FUTURES_CONTROL_COVERAGE_V", setup_sql)
        self.assertNotIn("ADAPTIVE_COMPUTE_READINESS", setup_sql)
        self.assertNotIn("ADAPTIVE_COMPUTE_DEFAULT", setup_sql)
        self.assertNotIn("AI_AGENT_MCP_GOVERNANCE", setup_sql)
        self.assertNotIn("AI_SECURITY_GUARDRAILS", setup_sql)
        self.assertNotIn("AI_SECURITY_DEFAULT", setup_sql)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS OVERWATCH_COST_SAVINGS_VERIFICATION_RUN", setup_sql)
        self.assertNotIn("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_VERIFY_COST_SAVINGS", setup_sql)
        self.assertNotIn("CREATE OR REPLACE VIEW OVERWATCH_COST_SAVINGS_VERIFICATION_HEALTH_V", setup_sql)
        self.assertNotIn("CREATE OR REPLACE TASK OVERWATCH_COST_SAVINGS_VERIFY", setup_sql)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS OVERWATCH_EXTERNAL_CONTROL_FEED", setup_sql)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS OVERWATCH_AUTOMATION_RUN", setup_sql)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS OVERWATCH_EXECUTIVE_PACKET", setup_sql)
        self.assertNotIn("CREATE OR REPLACE VIEW OVERWATCH_AUTOMATION_HEALTH_V", setup_sql)
        self.assertNotIn("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_AUTOMATION", setup_sql)
        self.assertNotIn("CREATE OR REPLACE TASK OVERWATCH_AUTOMATION_REFRESH", setup_sql)
        self.assertNotIn("TASK_STATUS_ROWS", setup_sql)
        self.assertNotIn("FLYWAY_ROWS", setup_sql)
        self.assertNotIn("FLYWAY_MIGRATION", setup_sql)
        self.assertNotIn("DEPLOYMENT_DRIFT_MODE", setup_sql)
        self.assertNotIn("PRIMARY_EVIDENCE_READY", setup_sql)
        self.assertNotIn("OVERWATCH_COST_SAVINGS_VERIFY TASK HANDLES AUTO-CLOSE", setup_sql)
        self.assertIn("WAREHOUSE_METERING_HISTORY", setup_sql)
        self.assertIn("ESCALATION_TARGET", setup_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS OVERWATCH_CHANGE_CONTROL_EVIDENCE", setup_sql)
        self.assertIn("CHANGE_TICKET_ID", setup_sql)
        self.assertIn("IAC_RECONCILIATION_STATE", setup_sql)
        self.assertIn("EXECUTION_AUDIT_STATE", setup_sql)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS OVERWATCH_SOURCE_CONTROL_CHANGE", setup_sql)
        self.assertNotIn("DEPLOYMENT_ADDRESS", setup_sql)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS OVERWATCH_OWNER_APPROVAL", setup_sql)
        self.assertIn("APPROVAL_STATUS", setup_sql)
        self.assertIn("CREATE TRANSIENT TABLE IF NOT EXISTS FACT_CHANGE_CONTROL_OPERABILITY_DAILY", setup_sql)
        self.assertIn("CONTROL_SOURCE", setup_sql)
        self.assertIn("CONTROL_RANK", setup_sql)
        self.assertIn("CHANGE_EVIDENCE_READINESS", setup_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS OVERWATCH_WAREHOUSE_SETTING_REVIEW", setup_sql)
        self.assertIn("BASELINE_CAPACITY_SCORE", setup_sql)
        self.assertIn("IMPACT_TELEMETRY_REQUIRED", setup_sql)
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
        self.assertNotIn("CREATE TABLE IF NOT EXISTS OVERWATCH_OWNER_DIRECTORY", setup_sql)
        self.assertNotIn("CREATE OR REPLACE VIEW OVERWATCH_OWNER_DIRECTORY_ACTIVE_V", setup_sql)
        self.assertNotIn("OVERWATCH_WH_EXECUTION", setup_sql)
        self.assertNotIn("COMPUTE_WH_EXECUTION", setup_sql)
        self.assertNotIn("ALFA_EDW_PROD_DATABASE", setup_sql)
        self.assertNotIn("ALFA_EDW_DEV_DATABASES", setup_sql)
        self.assertNotIn("ARCHITECTURE_DEFAULT", setup_sql)
        self.assertIn("ONCALL_PRIMARY", setup_sql)
        self.assertIn("APPROVAL_GROUP", setup_sql)
        self.assertIn("CREATE TRANSIENT TABLE IF NOT EXISTS DIM_COST_OWNER_TAG", setup_sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES", setup_sql)
        self.assertIn("WAREHOUSE_TAG:", setup_sql)
        self.assertIn("DATABASE_TAG:", setup_sql)
        self.assertIn("DELETE FROM FACT_CHARGEBACK_DAILY", setup_sql)
        self.assertIn("INSERT INTO FACT_CHARGEBACK_DAILY", setup_sql)
        self.assertIn("DEFAULT_ALERT_EMAIL", setup_sql)
        self.assertIn("DBA-ALERTS@YOURCOMPANY.COM", setup_sql)
        self.assertNotIn("JDEES@ALFAINS.COM", setup_sql)
        self.assertNotIn("JFREEZE03@YAHOO.COM", setup_sql)
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
        self.assertIn("COST_ANOMALY_MODEL", setup_sql)
        self.assertIn("PREDICTIVE_COST_ANOMALIES", setup_sql)
        self.assertIn("STDDEV(DAILY_CREDITS)", setup_sql)
        self.assertIn("BASELINE_CREDITS + 2.5 * COALESCE(SIGMA_CREDITS, 0)", setup_sql)
        self.assertIn("PREDICTIVE COST ANOMALY", setup_sql)
        self.assertIn("TASK FAILURE", setup_sql)
        self.assertIn("STORED PROCEDURE", setup_sql)
        self.assertNotIn("COST SAVINGS VERIFICATION FAILURE", setup_sql)
        self.assertNotIn("COST_SAVINGS_VERIFIER_FAILURE", setup_sql)
        self.assertNotIn("OVERWATCH_COST_SAVINGS_VERIFY", setup_sql)
        self.assertIn("GRANT/REVOKE ACTIVITY", setup_sql)
        self.assertIn("WAREHOUSE SETTING CHANGE", setup_sql)

        recovery_audit_sql = build_workload_recovery_audit_ddl().upper()
        self.assertIn("OVERWATCH_WORKLOAD_RECOVERY_AUDIT", recovery_audit_sql)
        self.assertIn("VERIFICATION_RESULT", recovery_audit_sql)

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
                "OVERWATCH_ANOMALY_CHECK",
                "OVERWATCH_LOAD_HOURLY",
                "OVERWATCH_LOAD_CORTEX",
                "OVERWATCH_REFRESH_CONTROL_ROOM",
                "OVERWATCH_COST_MONITORING_REFRESH",
                "OVERWATCH_EXECUTIVE_OBSERVABILITY_REFRESH",
                "OVERWATCH_LOAD_DAILY",
            },
        )
        self.assertEqual(
            warehouses,
            {
                "OVERWATCH_ANOMALY_CHECK": "OVERWATCH_WH",
                "OVERWATCH_LOAD_HOURLY": "OVERWATCH_WH",
                "OVERWATCH_LOAD_CORTEX": "OVERWATCH_WH",
                "OVERWATCH_REFRESH_CONTROL_ROOM": "OVERWATCH_WH",
                "OVERWATCH_COST_MONITORING_REFRESH": "OVERWATCH_WH",
                "OVERWATCH_EXECUTIVE_OBSERVABILITY_REFRESH": "OVERWATCH_WH",
                "OVERWATCH_LOAD_DAILY": "OVERWATCH_WH",
            },
        )
        self.assertEqual(
            {task: warehouse for task, warehouse in warehouses.items() if not warehouse.endswith("_WH")},
            {},
        )

    def test_fixed_action_status_does_not_require_manual_verification(self):
        missing = action_queue_fixed_missing_fields(
            status="Fixed",
            verification_notes="short",
            verification_result="",
        )

        self.assertEqual(missing, [])
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
                    return FakeResult([
                        {"column_name": column}
                        for column in (
                            "ENVIRONMENT",
                            "TICKET_ID",
                            "APPROVER",
                            "DUE_DATE",
                            "VERIFICATION_STATUS",
                            "VERIFICATION_NOTES",
                            "VERIFICATION_QUERY",
                            "VERIFICATION_RESULT",
                            "BASELINE_VALUE",
                            "CURRENT_VALUE",
                            "MEASURED_DELTA",
                            "VERIFIED_BY",
                            "VERIFIED_AT",
                            "OWNER_APPROVAL_STATUS",
                            "OWNER_APPROVAL_BY",
                            "OWNER_APPROVAL_AT",
                            "OWNER_APPROVAL_NOTE",
                            "RECOVERY_SLA_STATE",
                            "RECOVERY_SLA_HOURS",
                            "RECOVERY_SLA_TARGET_HOURS",
                            "RECOVERY_EVIDENCE",
                        )
                    ])
                return FakeResult([])

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            clear_action_queue_process_cache()
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
            show_calls = [sql for sql in session.sql_texts if "SHOW COLUMNS" in sql.upper()]

            st.session_state.clear()
            second_session = FakeSession()
            update_action_status_with_evidence(
                second_session,
                "ABC124",
                "Fixed",
                reason="Resolved under INC778",
                verification_notes="Warehouse setting validation stayed green after the second review.",
                verification_result="Current 7-day metered credits remain below the reviewed baseline.",
                verification_query="SELECT 1;",
                ticket_id="INC778",
                approver="DBA_MANAGER",
                due_date="2026-06-02",
                baseline_value=100,
                current_value=68,
                measured_delta=-32,
                owner_approval_status="Approved",
                owner_approval_note="Pipeline owner approved follow-up recovery after INC778.",
                recovery_sla_state="Recovered Within SLA",
                recovery_sla_hours=1.25,
                recovery_sla_target_hours=4,
                recovery_evidence="Latest task run succeeded within the recovery window.",
            )
            second_show_calls = [sql for sql in second_session.sql_texts if "SHOW COLUMNS" in sql.upper()]
        finally:
            clear_action_queue_process_cache()
            st.session_state.clear()
            st.session_state.update(previous)

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
        self.assertEqual(len(show_calls), 1)
        self.assertEqual(second_show_calls, [])
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
        self.assertEqual(by_id["FIXED1"]["EVIDENCE_GAP"], "Closed")
        self.assertGreater(by_id["FIXED1"]["QUEUE_PRIORITY"], by_id["OVERDUE1"]["QUEUE_PRIORITY"])
        self.assertIn("missing telemetry status", by_id["TASKOPEN1"]["EVIDENCE_GAP"])
        self.assertIn("missing recovery status", by_id["TASKOPEN1"]["EVIDENCE_GAP"])

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
