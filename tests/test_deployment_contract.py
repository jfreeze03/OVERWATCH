from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils.deployment import (  # noqa: E402
    STREAMLIT_MANIFEST_CONTRACT_VERSION,
    STREAMLIT_SNOWFLAKE_ARTIFACTS,
    build_streamlit_deployment_decision,
    build_streamlit_manifest_contract,
)


def _strip_sql_comments(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _setup_sql() -> str:
    return _strip_sql_comments(
        (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8")
    ).upper()


def _procedure_bodies(setup_sql: str) -> dict[str, str]:
    pattern = re.compile(
        r"CREATE\s+OR\s+REPLACE\s+PROCEDURE\s+(SP_OVERWATCH_[A-Z0-9_]+)\s*\([^)]*\).*?\$\$(.*?)\$\$",
        flags=re.DOTALL,
    )
    return {match.group(1): match.group(2) for match in pattern.finditer(setup_sql)}


RETIRED_DROP_OBJECTS = {
    "TABLE": [
        "FACT_MONITORING_COST_DAILY",
        "OVERWATCH_COST_SAVINGS_VERIFICATION_RUN",
        "OVERWATCH_EXTERNAL_CONTROL_FEED",
        "OVERWATCH_SOURCE_CONTROL_CHANGE",
        "OVERWATCH_OWNER_APPROVAL",
        "OVERWATCH_OWNER_DIRECTORY",
        "OVERWATCH_PLATFORM_FUTURES_CONTROL_REGISTER",
        "OVERWATCH_PLATFORM_FUTURES_EVIDENCE",
        "OVERWATCH_COMMAND_INTELLIGENCE_CAPABILITY",
        "OVERWATCH_REFRESH_POLICY",
        "OVERWATCH_COMPANY_SCOPE",
        "OVERWATCH_AUTOMATION_RUN",
        "OVERWATCH_EXECUTIVE_PACKET",
    ],
    "VIEW": [
        "OVERWATCH_AUTOMATION_HEALTH_V",
        "OVERWATCH_COST_SAVINGS_VERIFICATION_HEALTH_V",
        "OVERWATCH_OWNER_DIRECTORY_ACTIVE_V",
        "OVERWATCH_PLATFORM_FUTURES_CONTROL_COVERAGE_V",
        "OVERWATCH_PLATFORM_FUTURES_EVIDENCE_LATEST_V",
        "OVERWATCH_COMPLIANCE_READINESS_V",
    ],
    "TASK": [
        "OVERWATCH_AUTOMATION_REFRESH",
        "OVERWATCH_COST_SAVINGS_VERIFY",
    ],
    "PROCEDURE": [
        "SP_OVERWATCH_REFRESH_AUTOMATION",
        "SP_OVERWATCH_VERIFY_COST_SAVINGS",
    ],
}


class DeploymentContractTests(unittest.TestCase):
    def test_streamlit_manifest_contract_is_ready(self):
        contract = build_streamlit_manifest_contract(ROOT)

        expected_checks = {
            "Snowflake manifest file",
            "Snowflake entrypoint",
            "Snowflake runtime warehouse",
            "Snowflake caller boundary",
            "Snowflake package artifacts",
            "Community Cloud wrapper",
            "Community Cloud config",
            "Deployment guide",
            "CI deployment contract",
            "CI production shell guards",
            "Cortex completion guardrails",
        }
        self.assertEqual(set(contract["CHECK"]), expected_checks)
        self.assertEqual(set(contract["STATE"]), {"Ready"})

    def test_streamlit_runtime_decision_matches_manifest_contract(self):
        decision = build_streamlit_deployment_decision()
        snowflake = decision.loc[decision["RUNTIME"] == "Streamlit in Snowflake"].iloc[0]
        community = decision.loc[decision["RUNTIME"] == "Streamlit Community Cloud"].iloc[0]

        self.assertEqual(snowflake["ENTRYPOINT"], ".overwatch_final/app.py")
        self.assertEqual(snowflake["MANIFEST"], ".overwatch_final/snowflake.yml")
        self.assertEqual(snowflake["WAREHOUSE"], "COMPUTE_WH")
        self.assertEqual(snowflake["EXECUTE_AS"], "CALLER")
        self.assertIn("streamlit_app.py", snowflake["DO_NOT_USE"])
        self.assertNotIn("COMPUTE_WH", snowflake["DO_NOT_USE"])

        self.assertEqual(community["ENTRYPOINT"], "streamlit_app.py")
        self.assertEqual(community["MANIFEST"], ".streamlit/config.toml")

    def test_snowflake_manifest_artifact_list_is_complete(self):
        manifest = (APP_ROOT / "snowflake.yml").read_text(encoding="utf-8")

        self.assertIn("2026.06.13", STREAMLIT_MANIFEST_CONTRACT_VERSION)
        for artifact in STREAMLIT_SNOWFLAKE_ARTIFACTS:
            with self.subTest(artifact=artifact):
                self.assertIn(f"- {artifact}", manifest)
                self.assertTrue((APP_ROOT / artifact.rstrip("/")).exists())

        self.assertNotIn("execute_as: OWNER", manifest)

    def test_mart_setup_avoids_dynamic_tables_and_secure_views(self):
        setup_sql = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8").upper()
        drop_sql = (ROOT / "snowflake" / "OVERWATCH_MART_DROP.sql").read_text(encoding="utf-8").upper()

        self.assertNotIn("CREATE DYNAMIC TABLE", setup_sql)
        self.assertNotIn("CREATE OR REPLACE DYNAMIC TABLE", setup_sql)
        self.assertNotIn("CREATE SECURE VIEW", setup_sql)
        self.assertNotIn("CREATE OR REPLACE SECURE VIEW", setup_sql)
        self.assertNotIn("DROP DYNAMIC TABLE", drop_sql)
        self.assertIn("TASK/PROCEDURE-LOADED TABLES INSTEAD OF DYNAMIC TABLES", setup_sql)
        self.assertIn("SECURE VIEWS", setup_sql)

        for column_name in (
            "STAGE_BYTES",
            "HYBRID_TABLE_STORAGE_BYTES",
            "ARCHIVE_STORAGE_COOL_BYTES",
            "ARCHIVE_STORAGE_COLD_BYTES",
            "STANDARD_STORAGE_COST_USD",
            "HYBRID_STORAGE_COST_USD",
            "ARCHIVE_COOL_COST_USD",
            "ARCHIVE_COLD_COST_USD",
        ):
            with self.subTest(column_name=column_name):
                self.assertIn(column_name, setup_sql)
                self.assertIn(f"ADD COLUMN IF NOT EXISTS {column_name}", setup_sql)

    def test_mart_refresh_tasks_call_procedure_loaded_tables(self):
        setup_sql = _setup_sql()
        expected_task_calls = {
            "OVERWATCH_LOAD_HOURLY": "SP_OVERWATCH_LOAD_HOURLY_UNIT",
            "OVERWATCH_LOAD_QUERY_HOURLY": "SP_OVERWATCH_LOAD_HOURLY_UNIT",
            "OVERWATCH_LOAD_QUERY_DETAIL": "SP_OVERWATCH_LOAD_HOURLY_UNIT",
            "OVERWATCH_LOAD_OBJECT_CHANGE": "SP_OVERWATCH_LOAD_HOURLY_UNIT",
            "OVERWATCH_LOAD_TASK_RUN": "SP_OVERWATCH_LOAD_HOURLY_UNIT",
            "OVERWATCH_LOAD_PROCEDURE_RUN": "SP_OVERWATCH_LOAD_HOURLY_UNIT",
            "OVERWATCH_LOAD_SNAPSHOTS": "SP_OVERWATCH_LOAD_HOURLY_UNIT",
            "OVERWATCH_LOAD_TASK_CRITICAL_PATH": "SP_OVERWATCH_LOAD_HOURLY_UNIT",
            "OVERWATCH_LOAD_CORTEX": "SP_OVERWATCH_LOAD_CORTEX",
            "OVERWATCH_REFRESH_CONTROL_ROOM": "SP_OVERWATCH_REFRESH_CONTROL_ROOM",
            "OVERWATCH_COST_MONITORING_REFRESH": "SP_OVERWATCH_REFRESH_COST_MONITORING",
            "OVERWATCH_EXECUTIVE_OBSERVABILITY_REFRESH": "SP_OVERWATCH_REFRESH_EXECUTIVE_OBSERVABILITY",
            "OVERWATCH_LOAD_DAILY": "SP_OVERWATCH_LOAD_DAILY",
        }

        for task_name, proc_name in expected_task_calls.items():
            with self.subTest(task_name=task_name):
                task = re.search(
                    rf"CREATE\s+OR\s+REPLACE\s+TASK\s+{task_name}\b(.*?)(?=CREATE\s+OR\s+REPLACE\s+TASK|ALTER\s+TASK|SHOW\s+TASKS|$)",
                    setup_sql,
                    flags=re.DOTALL,
                )
                self.assertIsNotNone(task)
                task_body = task.group(1)
                self.assertIn("WAREHOUSE = COMPUTE_WH", task_body)
                self.assertRegex(task_body, rf"\bCALL\s+{proc_name}\s*\(")

        anomaly_task = re.search(
            r"CREATE\s+OR\s+REPLACE\s+TASK\s+OVERWATCH_ANOMALY_CHECK\b(.*?)(?=CREATE\s+OR\s+REPLACE\s+TASK|ALTER\s+TASK|SHOW\s+TASKS|$)",
            setup_sql,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(anomaly_task)
        self.assertIn("INSERT INTO OVERWATCH_ALERTS", anomaly_task.group(1))
        self.assertNotRegex(anomaly_task.group(1), r"\bCALL\s+SP_OVERWATCH_")

    def test_hourly_refresh_wrapper_is_guarded_by_default(self):
        setup_sql = _setup_sql()

        self.assertIn("'HOURLY_REFRESH_LOOKBACK_DAYS', '3', 'NUMBER'", setup_sql)
        self.assertIn("'HOURLY_REFRESH_COMPAT_WRAPPER_ENABLED', 'FALSE', 'BOOLEAN'", setup_sql)

        wrapper_body = _procedure_bodies(setup_sql)["SP_OVERWATCH_LOAD_HOURLY"]
        self.assertIn("HOURLY_REFRESH_COMPAT_WRAPPER_ENABLED", wrapper_body)
        self.assertIn("STATUS = 'SKIPPED'", wrapper_body)
        self.assertIn("SP_OVERWATCH_LOAD_HOURLY SKIPPED BY SAFETY GUARD", wrapper_body)
        self.assertIn("SP_OVERWATCH_LOAD_HOURLY_UNIT(UNIT_NAME, FROM_DAYS_AGO, TO_DAYS_AGO)", wrapper_body)

    def test_hourly_unit_binds_scripting_variables_in_dml(self):
        setup_sql = _setup_sql()
        hourly_body = _procedure_bodies(setup_sql)["SP_OVERWATCH_LOAD_HOURLY_UNIT"]

        self.assertIn("'STARTED HOURLY MART UNIT ' || :UNIT_NAME", hourly_body)
        self.assertIn("'HOURLY MART UNIT ' || :UNIT_NAME", hourly_body)
        self.assertIn("' FOR DAY WINDOW [' || :FROM_DAYS", hourly_body)
        self.assertIn("|| ', ' || :TO_DAYS || '].'", hourly_body)
        self.assertNotIn("'STARTED HOURLY MART UNIT ' || UNIT_NAME", hourly_body)
        self.assertNotIn("'HOURLY MART UNIT ' || UNIT_NAME", hourly_body)

    def test_hourly_unit_qualifies_account_usage_task_columns(self):
        setup_sql = _setup_sql()
        hourly_body = _procedure_bodies(setup_sql)["SP_OVERWATCH_LOAD_HOURLY_UNIT"]

        self.assertIn("SELECT\n      H.SCHEDULED_TIME,\n      H.COMPLETED_TIME,", hourly_body)
        self.assertIn("COALESCE(H.DATABASE_NAME, '')", hourly_body)
        self.assertIn("FROM SNOWFLAKE.ACCOUNT_USAGE.TASKS T", hourly_body)
        self.assertIn("T.TASK_DATABASE AS DATABASE_NAME", hourly_body)
        self.assertIn("VALUES ('DIM_TASK_AND_PROCEDURE_SNAPSHOT'", hourly_body)

    def test_refresh_procedures_write_only_setup_physical_tables(self):
        setup_sql = _setup_sql()
        table_creates = set(
            re.findall(
                r"^\s*CREATE\s+(?:TRANSIENT\s+)?TABLE\s+IF\s+NOT\s+EXISTS\s+([A-Z0-9_]+)",
                setup_sql,
                flags=re.MULTILINE,
            )
        )
        procedure_bodies = _procedure_bodies(setup_sql)
        self.assertGreaterEqual(len(procedure_bodies), 8)

        for proc_name, body in procedure_bodies.items():
            with self.subTest(proc_name=proc_name):
                self.assertNotIn("CREATE DYNAMIC TABLE", body)
                self.assertNotIn("CREATE OR REPLACE DYNAMIC TABLE", body)
                targets = sorted(
                    set(
                        re.findall(
                            r"\b(?:INSERT\s+INTO|DELETE\s+FROM|MERGE\s+INTO|TRUNCATE\s+TABLE|UPDATE)\s+([A-Z0-9_]+)",
                            body,
                        )
                    )
                )
                self.assertTrue(targets)
                for target in targets:
                    self.assertIn(target, table_creates)

    def test_drop_script_covers_retired_scope_cleanup_objects(self):
        setup_sql = _setup_sql()
        drop_sql = (ROOT / "snowflake" / "OVERWATCH_MART_DROP.sql").read_text(encoding="utf-8").upper()

        for object_type, names in RETIRED_DROP_OBJECTS.items():
            for name in names:
                with self.subTest(object_type=object_type, name=name):
                    if object_type == "TABLE":
                        self.assertIn(f"DROP TABLE IF EXISTS {name}", drop_sql)
                        self.assertNotIn(f"CREATE TABLE IF NOT EXISTS {name}", setup_sql)
                        self.assertNotIn(f"CREATE TRANSIENT TABLE IF NOT EXISTS {name}", setup_sql)
                    elif object_type == "VIEW":
                        self.assertIn(f"DROP VIEW IF EXISTS {name}", drop_sql)
                        self.assertNotIn(f"CREATE OR REPLACE VIEW {name}", setup_sql)
                    elif object_type == "TASK":
                        self.assertIn(f"ALTER TASK IF EXISTS {name} SUSPEND", drop_sql)
                        self.assertIn(f"DROP TASK IF EXISTS {name}", drop_sql)
                        self.assertNotIn(f"CREATE OR REPLACE TASK {name}", setup_sql)
                    elif object_type == "PROCEDURE":
                        self.assertIn(f"DROP PROCEDURE IF EXISTS {name}", drop_sql)
                        self.assertNotIn(f"CREATE OR REPLACE PROCEDURE {name}", setup_sql)

    def test_mart_validation_surfaces_dynamic_and_secure_view_collisions(self):
        validation_sql = (ROOT / "snowflake" / "OVERWATCH_MART_VALIDATION.sql").read_text(encoding="utf-8").upper()
        audit_sql = (ROOT / "snowflake" / "OVERWATCH_DYNAMIC_TABLE_SECURE_VIEW_AUDIT.sql").read_text(encoding="utf-8").upper()

        self.assertIn("DEPLOYABLE OBJECT COUNT CONTRACT", validation_sql)
        self.assertIn("EXPECTED_COUNT", validation_sql)
        self.assertIn("ACTUAL_COUNT", validation_sql)
        self.assertIn("ESCAPE '^'", validation_sql)
        self.assertNotIn("ESCAPE '\\'", validation_sql)
        self.assertIn("SHOW TASKS IN SCHEMA", validation_sql)
        self.assertIn("TASK GRAPH DEPLOYMENT PROOF", validation_sql)
        self.assertIn("OVERWATCH_EXECUTIVE_OBSERVABILITY_REFRESH", validation_sql)
        self.assertIn("SHOW DYNAMIC TABLES IN SCHEMA", validation_sql)
        self.assertIn("DYNAMIC_TABLE_COLLISIONS", validation_sql)
        self.assertIn("SECURE_VIEW_COLLISIONS", validation_sql)
        self.assertIn("INFORMATION_SCHEMA.VIEWS", validation_sql)
        self.assertIn("SHOW DYNAMIC TABLES IN SCHEMA", audit_sql)
        self.assertIn("DYNAMIC_TABLE_COLLISIONS", audit_sql)
        self.assertIn("SECURE_VIEW_COLLISIONS", audit_sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES", audit_sql)
        self.assertIn("TABLE + TASK/PROCEDURE", audit_sql)
        self.assertIn("GENERATED_DROP_SQL", audit_sql)
        self.assertIn("GENERATED_TABLE_STUB_SQL", audit_sql)
        self.assertIn("GENERATED_PROCEDURE_STUB_SQL", audit_sql)
        self.assertIn("GENERATED_TASK_STUB_SQL", audit_sql)

    def test_native_alert_deployment_script_is_review_only(self):
        setup_sql = _setup_sql()
        deployment_sql = (ROOT / "snowflake" / "OVERWATCH_NATIVE_ALERT_DEPLOYMENT.sql").read_text(encoding="utf-8").upper()
        drop_sql = (ROOT / "snowflake" / "OVERWATCH_MART_DROP.sql").read_text(encoding="utf-8").upper()
        validation_sql = (ROOT / "snowflake" / "OVERWATCH_MART_VALIDATION.sql").read_text(encoding="utf-8").upper()

        self.assertIn("CREATE OR REPLACE VIEW ALERT_NATIVE_DEPLOYMENT_REVIEW_V", deployment_sql)
        self.assertIn("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_STAGE_ALERT_REMEDIATION_DRY_RUN", deployment_sql)
        self.assertIn("THIS SCRIPT DOES NOT ENABLE OR EXECUTE NATIVE ALERTS AUTOMATICALLY", deployment_sql)
        self.assertIn("ALERT_NATIVE_DEPLOYMENT_REVIEW_V", setup_sql)
        self.assertIn("SP_OVERWATCH_STAGE_ALERT_REMEDIATION_DRY_RUN", setup_sql)
        self.assertIn("DROP VIEW IF EXISTS ALERT_NATIVE_DEPLOYMENT_REVIEW_V", drop_sql)
        self.assertIn("DROP PROCEDURE IF EXISTS SP_OVERWATCH_STAGE_ALERT_REMEDIATION_DRY_RUN", drop_sql)
        self.assertIn("('VIEW', 'ALERT_NATIVE_DEPLOYMENT_REVIEW_V')", validation_sql)
        self.assertIn("('VIEW', 3)", validation_sql)
        self.assertIn("('PROCEDURE', 17)", validation_sql)

    def test_alert_operations_review_script_is_read_only_and_covers_key_marts(self):
        review_sql = (ROOT / "snowflake" / "OVERWATCH_ALERT_OPERATIONS_REVIEW.sql").read_text(encoding="utf-8")
        review_sql_no_comments = _strip_sql_comments(review_sql).upper()

        self.assertIn("OBJECT_READINESS", review_sql_no_comments)
        self.assertIn("NATIVE_ALERT_PROMOTION_REVIEW", review_sql_no_comments)
        self.assertIn("THRESHOLD_TUNING_REVIEW", review_sql_no_comments)
        self.assertIn("COMPANY_SCOPE_REVIEW", review_sql_no_comments)
        self.assertIn("DYNAMIC_TABLE_COMPATIBILITY_REVIEW", review_sql_no_comments)
        for source in [
            "ALERT_EVENTS",
            "ALERT_THRESHOLDS",
            "ALERT_NATIVE_OBJECT_REGISTRY",
            "ALERT_REMEDIATION_POLICY",
            "FACT_CORTEX_DAILY",
            "FACT_WAREHOUSE_HOURLY",
            "FACT_QUERY_DETAIL_RECENT",
            "FACT_TASK_RUN",
            "FACT_GRANT_DAILY",
            "OVERWATCH_DYNAMIC_TABLE_SECURE_VIEW_AUDIT.SQL",
        ]:
            with self.subTest(source=source):
                self.assertIn(source, review_sql_no_comments)

        mutating_sql = re.search(
            r"\b(CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|MERGE|TRUNCATE|CALL)\b",
            review_sql_no_comments,
        )
        self.assertIsNone(mutating_sql)

    def test_ci_runs_deployment_contract_before_full_suite(self):
        workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8")

        self.assertIn("Validate deployment contract", workflow)
        self.assertIn("python -m unittest tests.test_deployment_contract", workflow)
        self.assertIn("Run production shell guards", workflow)
        self.assertIn("test_streamlit_deployment_entrypoints_are_pinned", workflow)
        self.assertIn("test_app_shell_header_renders_before_sidebar_hydration", workflow)
        self.assertIn("test_workflow_hubs_replace_scattered_operational_pages", workflow)
        self.assertIn("test_dead_ui_helpers_stay_removed", workflow)
        self.assertIn("Run Cortex guardrails", workflow)
        self.assertIn("python -m unittest tests.test_cortex_guard", workflow)
        self.assertLess(
            workflow.index("Validate deployment contract"),
            workflow.index("Run production shell guards"),
        )
        self.assertLess(
            workflow.index("Run production shell guards"),
            workflow.index("Run Cortex guardrails"),
        )
        self.assertLess(
            workflow.index("Run Cortex guardrails"),
            workflow.index("Run unit tests"),
        )


if __name__ == "__main__":
    unittest.main()
