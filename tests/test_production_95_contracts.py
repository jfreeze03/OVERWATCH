from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from config import CREDIT_SOURCE_LABELS  # noqa: E402
from utils.company_filter import assert_no_sql_injection, validate_filter_input  # noqa: E402
from utils.command_board import build_executive_command_board_sql, empty_command_board, summarize_command_board  # noqa: E402
from utils.incident_correlation import build_incident_correlation_sql  # noqa: E402
from utils.predictive_sla import build_predictive_sla_sql  # noqa: E402
from utils.sql_builder import SafeQuery, bind_fqn, bind_identifier  # noqa: E402


class Production95ContractsTests(unittest.TestCase):
    def test_filter_inputs_reject_sql_control_tokens(self):
        self.assertEqual(validate_filter_input("WH_ALFA_LOAD"), "WH_ALFA_LOAD")
        self.assertEqual(validate_filter_input("abc'; drop role x; --"), "")
        self.assertEqual(validate_filter_input("SNOW_DTI_ANALYST"), "SNOW_DTI_ANALYST")
        with self.assertRaises(ValueError):
            assert_no_sql_injection("AND WAREHOUSE_NAME ILIKE '%X%' ; DROP TABLE T")

    def test_safe_query_builder_keeps_params_and_identifiers_explicit(self):
        query = SafeQuery("SELECT * FROM T WHERE X = :x", source="unit").with_param("x", 7)
        self.assertEqual(query.params["x"], 7)
        self.assertEqual(query.source, "unit")
        self.assertEqual(bind_identifier("alfa_edw_prod"), "ALFA_EDW_PROD")
        self.assertEqual(bind_fqn("db", "schema", "table"), "DB.SCHEMA.TABLE")
        with self.assertRaises(ValueError):
            bind_identifier("db;drop")

    def test_credit_source_labels_make_live_estimates_explicit(self):
        self.assertEqual(CREDIT_SOURCE_LABELS["warehouse_metering"], "Official warehouse metering")
        self.assertEqual(CREDIT_SOURCE_LABELS["live_estimate"], "Live estimate fallback")

    def test_new_snowflake_setup_contracts_exist(self):
        expected = {
            "OVERWATCH_ROLE_SETUP.sql": ("OVERWATCH_MONITOR", "OVERWATCH_OPERATOR"),
            "OVERWATCH_PIPELINE_SLA.sql": ("PIPELINE_SLA_CONFIG", "PIPELINE_SLA_EXECUTIVE_V"),
            "OVERWATCH_FRESHNESS_ALERT.sql": ("ALERT_PIPELINE_SLA_MISS", "ALERT_EVENTS"),
            "OVERWATCH_EXECUTIVE_DIGEST.sql": ("EXECUTIVE_DIGEST_HISTORY", "SP_OVERWATCH_EXECUTIVE_DIGEST"),
            "OVERWATCH_TAG_SETUP.sql": ("OVERWATCH_OWNER", "OVERWATCH_TAG_COVERAGE_V"),
            "OVERWATCH_AVAILABILITY.sql": ("OVERWATCH_SELF_HEALTH_V", "QUERY_TAG ILIKE 'OVERWATCH%'"),
        }
        for file_name, markers in expected.items():
            with self.subTest(file=file_name):
                text = (ROOT / "snowflake" / file_name).read_text(encoding="utf-8").upper()
                for marker in markers:
                    self.assertIn(marker, text)

    def test_incident_and_predictive_sla_sql_are_snowflake_native(self):
        incident_sql = build_incident_correlation_sql().upper()
        sla_sql = build_predictive_sla_sql().upper()
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", incident_sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY", incident_sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY", incident_sql)
        self.assertIn("OVERWATCH_INCIDENT_CORRELATION_V", incident_sql)
        self.assertIn("OVERWATCH_PREDICTIVE_SLA_V", sla_sql)
        self.assertIn("P95_DURATION_SEC", sla_sql)
        self.assertIn("PREDICTED_SLA_RISK", sla_sql)

    def test_command_board_uses_executive_observability_mart(self):
        sql = build_executive_command_board_sql("ALFA", "PROD", 7).upper()
        self.assertIn("MART_EXECUTIVE_OBSERVABILITY", sql)
        self.assertIn("WINDOW_DAYS = 7", sql)
        self.assertIn("ROW_NUMBER() OVER", sql)
        self.assertIn("PANEL, METRIC, DIMENSION", sql)

        board = pd.DataFrame(
            [
                {"PANEL": "KPI", "METRIC": "Credits Used", "DIMENSION": "Current", "VALUE": 100, "VALUE_USD": 368},
                {"PANEL": "KPI", "METRIC": "Spend Delta", "DIMENSION": "Current", "VALUE": 12, "VALUE_USD": 44.16},
                {"PANEL": "KPI", "METRIC": "Cortex Spend", "DIMENSION": "Current", "VALUE": 10, "VALUE_USD": 22},
                {"PANEL": "KPI", "METRIC": "Total Queries", "DIMENSION": "Current", "VALUE": 1200},
                {"PANEL": "KPI", "METRIC": "P95 Runtime", "DIMENSION": "Current", "VALUE": 42.5},
                {"PANEL": "KPI", "METRIC": "Queue Time", "DIMENSION": "Current", "VALUE": 300},
                {"PANEL": "KPI", "METRIC": "Remote Spill", "DIMENSION": "Current", "VALUE": 8.5},
                {"PANEL": "KPI", "METRIC": "Failed Queries", "DIMENSION": "Current", "VALUE": 4},
                {"PANEL": "KPI", "METRIC": "Failed Tasks", "DIMENSION": "Current", "VALUE": 2},
                {"PANEL": "KPI", "METRIC": "Critical High Alerts", "DIMENSION": "Current", "VALUE": 3},
                {"PANEL": "KPI", "METRIC": "Open Actions", "DIMENSION": "Current", "VALUE": 5},
                {"PANEL": "KPI", "METRIC": "Platform Health", "DIMENSION": "Current", "VALUE": 91},
                {"PANEL": "COST_DRIVER", "METRIC": "Cost Drivers", "DIMENSION": "WH_LOAD", "VALUE": 40, "VALUE_USD": 147.2},
                {"PANEL": "WAREHOUSE_PRESSURE", "METRIC": "Queue Seconds", "DIMENSION": "WH_QUERY", "VALUE": 300, "VALUE_USD": 0},
                {"PANEL": "WAREHOUSE_PRESSURE", "METRIC": "Remote Spill GB", "DIMENSION": "WH_LOAD", "VALUE": 8.5, "VALUE_USD": 0},
                {"PANEL": "FRESHNESS", "METRIC": "Source Freshness", "DIMENSION": "QUERY_HISTORY", "VALUE": 1},
            ]
        )
        summary = summarize_command_board(board)
        self.assertTrue(summary["loaded"])
        self.assertEqual(summary["current_cost_usd"], 368)
        self.assertEqual(summary["failed_queries"], 4)
        self.assertEqual(summary["failed_tasks"], 2)
        self.assertEqual(summary["critical_high_alerts"], 3)
        self.assertEqual(summary["open_actions"], 5)
        self.assertEqual(summary["score"], 91)
        self.assertEqual(summary["top_cost_driver"], "WH_LOAD")
        self.assertEqual(summary["top_queue_warehouse"], "WH_QUERY")
        self.assertEqual(summary["top_spill_warehouse"], "WH_LOAD")

        fallback = empty_command_board("ALFA", "PROD", 7)
        self.assertFalse(fallback.summary["loaded"])
        self.assertTrue(fallback.meta["first_paint"])
        self.assertIn("Use Refresh", fallback.summary["cap_reason"])

    def test_docs_track_recovery_and_release_history(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("OVERWATCH_ROLE_SETUP", readme)
        self.assertTrue((ROOT / "CHANGELOG.md").exists())
        self.assertTrue((ROOT / "docs" / "OVERWATCH_RECOVERY_RUNBOOK.md").exists())

    def test_executive_landing_is_kpi_first_not_shell_brief(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        shell_text = (APP_ROOT / "sections" / "executive_landing_shell.py").read_text(encoding="utf-8")
        self.assertNotIn("Top Priority Brief", app_text)
        self.assertNotIn("priority_brief_slot", app_text)
        self.assertIn("load_or_reuse_command_board", shell_text)
        self.assertIn("load_setup_readiness", shell_text)
        self.assertIn("Observability Summary", shell_text)
        self.assertIn("Snowflake Observability Wall", shell_text)
        self.assertIn("Setup Readiness", shell_text)
        self.assertIn("Platform Operating Score", shell_text)
        self.assertIn("Top 5 Action Items", shell_text)

    def test_final_pass_shells_surface_operating_contracts_before_drilldown(self):
        cost_shell = (APP_ROOT / "sections" / "cost_contract_shell.py").read_text(encoding="utf-8")
        alert_shell = (APP_ROOT / "sections" / "alert_center_shell.py").read_text(encoding="utf-8")
        workload_shell = (APP_ROOT / "sections" / "workload_operations_shell.py").read_text(encoding="utf-8")
        refresh_doc = (ROOT / "docs" / "REFRESH_ARCHITECTURE.md").read_text(encoding="utf-8")

        self.assertIn("Snowflake Value Automation", cost_shell)
        self.assertIn("No-Touch Value Capture", cost_shell)
        self.assertIn("OVERWATCH_VALUE_AUTOMATION_HEALTH_V", cost_shell)
        self.assertIn("SP_OVERWATCH_AUTOMATE_VALUE_LOG", cost_shell)

        self.assertIn("Lifecycle Control Loop", alert_shell)
        self.assertIn("ALERT_ACKNOWLEDGEMENTS", alert_shell)
        self.assertIn("ALERT_REMEDIATION_LOG", alert_shell)
        self.assertIn("ALERT_DATA_QUALITY_CHECKS", alert_shell)

        self.assertIn("Safe Fix Contract", workload_shell)
        self.assertIn("Lock vs queue", workload_shell)
        self.assertIn("blocker, waiter, object, and owner", workload_shell)

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Raw", readme)
        self.assertIn("`ACCOUNT_USAGE` scans are never part of Executive Landing first paint", readme)
        self.assertIn("Executive Landing is not allowed to start raw `SNOWFLAKE.ACCOUNT_USAGE` scans", refresh_doc)


if __name__ == "__main__":
    unittest.main()
