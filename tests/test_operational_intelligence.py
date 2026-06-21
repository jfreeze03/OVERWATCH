from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


def _read_section(path: Path) -> str:
    path = Path(path)
    if path.suffix == ".py" and not path.exists():
        pkg = path.with_suffix("")
        if pkg.is_dir():
            order = ("types", "health", "queue", "incidents", "handoff", "render", "__init__")
            files = sorted(
                pkg.glob("*.py"),
                key=lambda p: (order.index(p.stem) if p.stem in order else len(order), p.stem),
            )
            return "\n".join(f.read_text(encoding="utf-8") for f in files)
    return path.read_text(encoding="utf-8")


from utils.operational_intelligence import (  # noqa: E402
    build_alert_lifecycle_sql,
    build_capability_register_rows,
    build_capability_setup_sql,
    build_compliance_readiness_sql,
    build_cost_run_rate_sql,
    build_operational_intelligence_sql_catalog,
    build_overwatch_self_monitoring_sql,
)


class OperationalIntelligenceTests(unittest.TestCase):
    def test_command_intelligence_plan_contains_all_12_ranked_capabilities(self):
        rows = build_capability_register_rows()
        self.assertEqual(len(rows), 12)
        self.assertEqual([row["RANK"] for row in rows], list(range(1, 13)))
        capabilities = {row["CAPABILITY"] for row in rows}
        for expected in {
            "Detection and Root-Cause Engine",
            "Task/Pipeline Critical Path Brain",
            "Data Quality and Reconciliation Center",
            "Cost Run-Rate and Attribution Monitor",
            "Alert Lifecycle 2.0",
            "Fact-Grounded AI Query Diagnosis",
            "Bounded Refresh Guardrails",
            "Scheduled Mart Layer With Fallback",
            "Security Risk Monitoring",
            "Multi-Account / Org View",
            "Data-First Navigation Contract",
            "Monitoring Docs and Runbooks",
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
            "OVERWATCH_ACTION_QUEUE",
        ]:
            self.assertIn(source, combined_sql)
        self.assertIn("NO SAVED-STATE TABLE", combined_sql)
        self.assertNotIn("OVERWATCH_USER_PREFERENCES", combined_sql)

    def test_core_sql_contracts_avoid_same_select_alias_dependency(self):
        cost_sql = build_cost_run_rate_sql().upper()
        compliance_sql = build_compliance_readiness_sql().upper()
        alert_sql = build_alert_lifecycle_sql().upper()
        self.assertIn("PROJECTED AS", cost_sql)
        self.assertIn("),\nPROJECTED AS", cost_sql)
        self.assertIn("FROM PROJECTED", cost_sql)
        self.assertIn("ROLLUP AS", compliance_sql)
        self.assertIn("),\nROLLUP AS", compliance_sql)
        self.assertIn("FROM ROLLUP", compliance_sql)
        self.assertIn("EVENT_ID", alert_sql)
        self.assertNotIn("USING (ALERT_ID)", alert_sql)

    def test_reconciliation_runner_uses_cross_database_account_usage_inventory(self):
        catalog = build_operational_intelligence_sql_catalog()
        recon_sql = next(row["SQL"] for row in catalog if row["CAPABILITY"] == "Data Quality and Reconciliation Center").upper()
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.TABLES", recon_sql)
        self.assertIn("SOURCE_DATABASE", recon_sql)
        self.assertIn("TARGET_DATABASE", recon_sql)
        self.assertIn("TARGET_TABLE_MISSING", recon_sql)
        self.assertIn("COMPARE_READY", recon_sql)
        self.assertNotIn("JOIN INFORMATION_SCHEMA.TABLES", recon_sql)

    def test_self_monitoring_and_setup_contracts_are_deployable(self):
        self_monitoring = build_overwatch_self_monitoring_sql().upper()
        setup_bundle = build_capability_setup_sql().upper()
        self.assertIn("QUERY_TAG ILIKE 'OVERWATCH%'", self_monitoring)
        self.assertIn("OVERWATCH_RECON_CONFIG", setup_bundle)
        self.assertIn("NO SAVED-STATE TABLE", setup_bundle)
        self.assertIn("OVERWATCH_MART_SETUP.SQL", setup_bundle)
        self.assertNotIn("OVERWATCH_USER_PREFERENCES", setup_bundle)

    def test_repo_docs_and_consolidated_setup_script_are_present(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        runbook = ROOT / "docs" / "OVERWATCH_COMMAND_INTELLIGENCE_RUNBOOK.md"
        data_model = ROOT / "docs" / "DATA_MODEL.md"
        refresh_arch = ROOT / "docs" / "REFRESH_ARCHITECTURE.md"
        setup_path = ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql"
        setup = setup_path.read_text(encoding="utf-8").upper()
        self.assertTrue(runbook.exists())
        self.assertTrue(data_model.exists())
        self.assertTrue(refresh_arch.exists())
        self.assertTrue(setup_path.exists())
        self.assertIn("OVERWATCH_COMMAND_INTELLIGENCE_RUNBOOK", readme)
        self.assertIn("REFRESH_ARCHITECTURE", readme)
        self.assertNotIn("OVERWATCH_COMMAND_INTELLIGENCE_CAPABILITY", setup)
        self.assertNotIn("OVERWATCH_REFRESH_POLICY", setup)
        self.assertIn("CREATE ROLE IF NOT EXISTS SNOW_ACCOUNTADMINS", setup)
        self.assertIn("CREATE ROLE IF NOT EXISTS SNOW_SYSADMINS", setup)
        self.assertIn("OVERWATCH_ROLE_READINESS_REQUIREMENT", setup)
        self.assertNotIn("OVERWATCH_MONITOR", setup)
        self.assertNotIn("CREATE ROLE IF NOT EXISTS OVERWATCH_OPERATOR", setup)
        self.assertNotIn("GRANT ROLE OVERWATCH_OPERATOR", setup)
        self.assertNotIn("PRECOMPUTE.SQL", readme.upper())
        self.assertNotIn("SP_OVERWATCH_AUTOMATE_VALUE_LOG", setup)
        self.assertNotIn("OVERWATCH_VALUE_AUTOMATION_HEALTH_V", setup)

    def test_sections_surface_command_intelligence_without_new_sidebar_sprawl(self):
        section_paths = [
            ROOT / ".overwatch_final" / "sections" / "alert_center.py",
            ROOT / ".overwatch_final" / "sections" / "workload_operations.py",
            ROOT / ".overwatch_final" / "sections" / "cost_contract.py",
            ROOT / ".overwatch_final" / "sections" / "dba_control_room.py",
            ROOT / ".overwatch_final" / "sections" / "executive_landing.py",
        ]
        text = "\n".join(_read_section(path) for path in section_paths)
        for marker in [
            "build_capability_register_rows",
            "build_mart_cost_run_rate_sql",
            "Bounded Refresh Guardrails",
        ]:
            self.assertIn(marker, text)
        self.assertNotIn("God-tier", text)


if __name__ == "__main__":
    unittest.main()
