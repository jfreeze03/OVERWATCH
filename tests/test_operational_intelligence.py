from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils.operational_intelligence import (  # noqa: E402
    build_alert_lifecycle_sql,
    build_compliance_readiness_sql,
    build_god_tier_capability_rows,
    build_god_tier_setup_bundle_sql,
    build_operational_intelligence_sql_catalog,
    build_overwatch_self_monitoring_sql,
    build_predictive_finops_sql,
    build_precompute_contract_sql,
    build_snowflake_value_auto_ddl,
    build_snowflake_value_automation_health_sql,
    build_snowflake_value_candidate_sql,
)


class OperationalIntelligenceTests(unittest.TestCase):
    def test_god_tier_plan_contains_all_12_ranked_capabilities(self):
        rows = build_god_tier_capability_rows()
        self.assertEqual(len(rows), 12)
        self.assertEqual([row["RANK"] for row in rows], list(range(1, 13)))
        capabilities = {row["CAPABILITY"] for row in rows}
        for expected in {
            "Detection and Root-Cause Engine",
            "Task/Pipeline Critical Path Brain",
            "Data Quality and Reconciliation Center",
            "Predictive FinOps and Automated Value Log",
            "Alert Lifecycle 2.0",
            "Fact-Grounded AI Query Diagnosis",
            "OVERWATCH Self-Monitoring",
            "Precomputed Mart / Dynamic Table Layer With Fallback",
            "Compliance Readiness Scorecard",
            "Multi-Account / Org View",
            "Data-First Navigation Contract",
            "Architecture Docs and Runbooks",
        }:
            self.assertIn(expected, capabilities)

    def test_sql_catalog_covers_all_capabilities_and_snowflake_sources(self):
        catalog = build_operational_intelligence_sql_catalog()
        self.assertEqual(len(catalog), 12)
        combined_sql = "\n".join(str(row["SQL"]).upper() for row in catalog)
        for source in [
            "QUERY_HISTORY",
            "TASK_HISTORY",
            "WAREHOUSE_METERING_HISTORY",
            "LOGIN_HISTORY",
            "ACCESS_HISTORY",
            "ORGANIZATION_USAGE",
            "OVERWATCH_RECON_CONFIG",
            "OVERWATCH_VALUE_CANDIDATE_V",
        ]:
            self.assertIn(source, combined_sql)
        self.assertIn("NO SAVED-STATE TABLE", combined_sql)
        self.assertNotIn("OVERWATCH_USER_PREFERENCES", combined_sql)

    def test_value_automation_uses_existing_alert_event_contract(self):
        value_sql = build_snowflake_value_auto_ddl().upper()
        self.assertIn("OVERWATCH_VALUE_CANDIDATE_V", value_sql)
        self.assertIn("OVERWATCH_VALUE_AUTOMATION_HEALTH_V", value_sql)
        self.assertIn("SP_OVERWATCH_AUTOMATE_VALUE_LOG", value_sql)
        self.assertIn("OVERWATCH_ACTION_QUEUE", value_sql)
        self.assertIn("ALERT_EVENTS", value_sql)
        self.assertIn("EVENT_ID", value_sql)
        self.assertIn("IMPACT_ESTIMATE", value_sql)
        self.assertNotIn("VALUE_AT_RISK_USD", value_sql)
        self.assertNotIn("BUSINESS_IMPACT_USD", value_sql)
        self.assertNotIn("SIGNAL_NAME", value_sql)

    def test_core_sql_contracts_avoid_same_select_alias_dependency(self):
        finops_sql = build_predictive_finops_sql().upper()
        compliance_sql = build_compliance_readiness_sql().upper()
        alert_sql = build_alert_lifecycle_sql().upper()
        value_health_sql = build_snowflake_value_automation_health_sql().upper()
        self.assertIn("PROJECTED AS", finops_sql)
        self.assertIn("),\nPROJECTED AS", finops_sql)
        self.assertIn("FROM PROJECTED", finops_sql)
        self.assertIn("ROLLUP AS", compliance_sql)
        self.assertIn("),\nROLLUP AS", compliance_sql)
        self.assertIn("FROM ROLLUP", compliance_sql)
        self.assertIn("EVENT_ID", alert_sql)
        self.assertNotIn("USING (ALERT_ID)", alert_sql)
        self.assertIn("OVERWATCH_VALUE_AUTOMATION_HEALTH_V", value_health_sql)

    def test_reconciliation_runner_uses_cross_database_account_usage_inventory(self):
        catalog = build_operational_intelligence_sql_catalog()
        recon_sql = next(row["SQL"] for row in catalog if row["CAPABILITY"] == "Data Quality and Reconciliation Center").upper()
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.TABLES", recon_sql)
        self.assertIn("SOURCE_DATABASE", recon_sql)
        self.assertIn("TARGET_DATABASE", recon_sql)
        self.assertIn("TARGET_TABLE_MISSING", recon_sql)
        self.assertIn("COMPARE_READY", recon_sql)
        self.assertNotIn("JOIN INFORMATION_SCHEMA.TABLES", recon_sql)

    def test_value_automation_candidate_and_health_queries_are_read_only(self):
        candidate_sql = build_snowflake_value_candidate_sql().upper()
        health_sql = build_snowflake_value_automation_health_sql().upper()
        self.assertIn("FROM OVERWATCH_VALUE_CANDIDATE_V", candidate_sql)
        self.assertIn("FROM OVERWATCH_VALUE_AUTOMATION_HEALTH_V", health_sql)
        self.assertNotIn("MERGE INTO", candidate_sql + health_sql)
        self.assertNotIn("CALL SP_OVERWATCH_AUTOMATE_VALUE_LOG", candidate_sql + health_sql)

    def test_self_monitoring_and_precompute_contracts_are_deployable(self):
        self_monitoring = build_overwatch_self_monitoring_sql().upper()
        precompute = build_precompute_contract_sql().upper()
        setup_bundle = build_god_tier_setup_bundle_sql().upper()
        self.assertIn("QUERY_TAG ILIKE 'OVERWATCH%'", self_monitoring)
        self.assertIn("CREATE DYNAMIC TABLE IF NOT EXISTS", precompute)
        self.assertIn("CREATE OR REPLACE VIEW OVERWATCH_QUERY_HEALTH_HOURLY_V", precompute)
        self.assertIn("OVERWATCH_RECON_CONFIG", setup_bundle)
        self.assertIn("NO SAVED-STATE TABLE", setup_bundle)
        self.assertNotIn("OVERWATCH_USER_PREFERENCES", setup_bundle)

    def test_repo_docs_and_precompute_script_are_present(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        runbook = ROOT / "docs" / "OVERWATCH_COMMAND_INTELLIGENCE_RUNBOOK.md"
        data_model = ROOT / "docs" / "DATA_MODEL.md"
        precompute = ROOT / "snowflake" / "PRECOMPUTE.sql"
        setup = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8").upper()
        self.assertTrue(runbook.exists())
        self.assertTrue(data_model.exists())
        self.assertTrue(precompute.exists())
        self.assertIn("OVERWATCH_COMMAND_INTELLIGENCE_RUNBOOK", readme)
        self.assertIn("OVERWATCH_COMMAND_INTELLIGENCE_CAPABILITY", setup)
        self.assertIn("SP_OVERWATCH_AUTOMATE_VALUE_LOG", setup)
        self.assertIn("OVERWATCH_VALUE_AUTOMATION_HEALTH_V", setup)

    def test_sections_surface_command_intelligence_without_new_sidebar_sprawl(self):
        section_paths = [
            ROOT / ".overwatch_final" / "sections" / "alert_center.py",
            ROOT / ".overwatch_final" / "sections" / "workload_operations.py",
            ROOT / ".overwatch_final" / "sections" / "cost_contract.py",
            ROOT / ".overwatch_final" / "sections" / "dba_control_room.py",
            ROOT / ".overwatch_final" / "sections" / "executive_landing.py",
            ROOT / ".overwatch_final" / "sections" / "snowflake_value.py",
        ]
        text = "\n".join(path.read_text(encoding="utf-8") for path in section_paths)
        for marker in [
            "build_god_tier_capability_rows",
            "build_task_critical_path_brain_sql",
            "build_predictive_finops_sql",
            "build_snowflake_value_auto_ddl",
            "build_overwatch_self_monitoring_sql",
            "build_ai_query_diagnosis_contract_rows",
        ]:
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
