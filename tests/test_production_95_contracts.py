from pathlib import Path
import sys
import unittest

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from config import CREDIT_SOURCE_LABELS  # noqa: E402
from utils.company_filter import assert_no_sql_injection, validate_filter_input  # noqa: E402
import utils.command_board as command_board  # noqa: E402
from utils.command_board import build_executive_command_board_sql, empty_command_board, summarize_command_board  # noqa: E402
from utils.incident_correlation import build_incident_correlation_sql  # noqa: E402
from utils.native_snowflake import (  # noqa: E402
    build_alert_object_registry_sql,
    build_data_quality_dmf_sql,
    build_executive_digest_history_sql,
    build_org_rollup_sql,
    build_overwatch_self_cost_sql,
    build_tag_allocation_sql,
    native_capability_lanes,
)
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
        setup = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8").upper()
        for marker in (
            "CREATE ROLE IF NOT EXISTS SNOW_ACCOUNTADMINS",
            "CREATE ROLE IF NOT EXISTS SNOW_SYSADMINS",
            "GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE SNOW_ACCOUNTADMINS",
            "CREATE WAREHOUSE IF NOT EXISTS OVERWATCH_WH",
            "CREATE TABLE IF NOT EXISTS ALERT_EVENTS",
            "CREATE TABLE IF NOT EXISTS OVERWATCH_RECON_CONFIG",
            "CREATE OR REPLACE TASK OVERWATCH_COST_MONITORING_REFRESH",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, setup)
        self.assertNotIn("OVERWATCH_MONITOR", setup)
        self.assertNotIn("OVERWATCH_OPERATOR", setup)

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
        self.assertEqual(summary["score"], 47)
        self.assertEqual(summary["score_cap"], 82)
        self.assertIn("stale source", summary["cap_reason"])
        self.assertEqual(summary["platform_score_drivers"][0]["DRIVER"], "Critical/high alerts")
        self.assertEqual(summary["top_cost_driver"], "WH_LOAD")
        self.assertEqual(summary["top_queue_warehouse"], "WH_QUERY")
        self.assertEqual(summary["top_spill_warehouse"], "WH_LOAD")

        fallback = empty_command_board("ALFA", "PROD", 7)
        self.assertFalse(fallback.summary["loaded"])
        self.assertTrue(fallback.meta["first_paint"])
        self.assertIn("Use Refresh", fallback.summary["cap_reason"])

    def test_command_board_loader_hydrates_on_first_render(self):
        state_keys = (
            "test_exec_board",
            "test_exec_summary",
            "test_exec_meta",
            "test_exec_refresh_marker",
            "_refresh_salt_global",
        )
        for key in state_keys:
            st.session_state.pop(key, None)

        calls = []
        original_mart_loader = command_board.load_executive_command_board
        original_first_paint_loader = command_board.load_first_paint_command_board
        payload = command_board.CommandBoard(
            data=pd.DataFrame(
                [
                    {
                        "PANEL": "KPI",
                        "METRIC": "Credits Used",
                        "DIMENSION": "Current",
                        "VALUE": 10,
                        "VALUE_USD": 36.8,
                    }
                ]
            ),
            summary={"loaded": True, "current_cost_usd": 36.8},
            meta={"company": "ALFA", "environment": "ALL", "days": 7},
        )

        def fake_mart_loader(company, environment, days):
            calls.append(("mart", company, environment, days))
            return payload

        def fake_first_paint_loader(company, environment, days):
            calls.append(("first_paint", company, environment, days))
            return empty_command_board(company, environment, days)

        try:
            command_board.load_executive_command_board = fake_mart_loader
            command_board.load_first_paint_command_board = fake_first_paint_loader
            result = command_board.load_or_reuse_command_board(
                data_key="test_exec_board",
                summary_key="test_exec_summary",
                meta_key="test_exec_meta",
                refresh_marker_key="test_exec_refresh_marker",
                company="ALFA",
                environment="ALL",
                days=7,
            )
        finally:
            command_board.load_executive_command_board = original_mart_loader
            command_board.load_first_paint_command_board = original_first_paint_loader
            for key in state_keys:
                st.session_state.pop(key, None)

        self.assertTrue(result.summary["loaded"])
        self.assertEqual(calls, [("mart", "ALFA", "ALL", 7)])

    def test_docs_track_recovery_and_release_history(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("OVERWATCH_MART_SETUP.sql", readme)
        self.assertTrue((ROOT / "CHANGELOG.md").exists())
        self.assertTrue((ROOT / "docs" / "OVERWATCH_RECOVERY_RUNBOOK.md").exists())

    def test_executive_landing_is_kpi_first_not_shell_brief(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        executive_text = (APP_ROOT / "sections" / "executive_landing.py").read_text(encoding="utf-8")
        self.assertNotIn("Top Priority Brief", app_text)
        self.assertNotIn("priority_brief_slot", app_text)
        self.assertIn(
            'SectionDefinition("COMMAND CENTER", "briefcase", "Executive Landing", "sections.executive_landing")',
            (APP_ROOT / "config.py").read_text(encoding="utf-8"),
        )
        self.assertFalse((APP_ROOT / "sections" / "executive_landing_shell.py").exists())
        self.assertIn("def _load_executive_observability", executive_text)
        self.assertIn("_executive_landing_observability_autoload_scope", executive_text)
        self.assertIn("Snowflake Observability Wall", executive_text)
        self.assertIn("Executive Summary Signals", executive_text)
        self.assertIn("Executive decisions to make first", executive_text)
        self.assertNotIn("Refresh Board", executive_text)
        self.assertNotIn("Executive Command Wall", executive_text)
        self.assertNotIn("Setup Readiness", executive_text)
        self.assertNotIn("Platform Operating Score", executive_text)
        self.assertNotIn("Platform Score Basis", executive_text)
        self.assertNotIn("Platform Score Drivers", executive_text)
        self.assertNotIn("render_native_readiness_board", executive_text)
        self.assertNotIn("from sections.native_readiness import render_native_readiness_board", executive_text)
        self.assertNotIn("from sections.native_readiness", executive_text)

    def test_final_pass_shells_surface_operating_contracts_before_drilldown(self):
        config_text = (APP_ROOT / "config.py").read_text(encoding="utf-8")
        cost_text = (APP_ROOT / "sections" / "cost_contract.py").read_text(encoding="utf-8")
        alert_text = (APP_ROOT / "sections" / "alert_center.py").read_text(encoding="utf-8")
        workload_text = (APP_ROOT / "sections" / "workload_operations.py").read_text(encoding="utf-8")
        native_monitoring = (APP_ROOT / "sections" / "native_monitoring.py").read_text(encoding="utf-8")
        refresh_doc = (ROOT / "docs" / "REFRESH_ARCHITECTURE.md").read_text(encoding="utf-8")

        self.assertIn('"Cost & Contract", "sections.cost_contract"', config_text)
        self.assertIn('"Alert Center", "sections.alert_center"', config_text)
        self.assertIn('"Workload Operations", "sections.workload_operations"', config_text)
        self.assertFalse((APP_ROOT / "sections" / "cost_contract_shell.py").exists())
        self.assertFalse((APP_ROOT / "sections" / "alert_center_shell.py").exists())
        self.assertFalse((APP_ROOT / "sections" / "workload_operations_shell.py").exists())
        self.assertIn("Cost Signal Summary", cost_text)
        self.assertIn("Alert Signal Summary", alert_text)
        self.assertIn('QUERY_INVESTIGATION_WORKFLOW = "Query investigation"', workload_text)
        self.assertNotIn("Cost Command Board", cost_text)
        self.assertNotIn("Alert Command Board", alert_text)
        self.assertNotIn("Workload Command Board", workload_text)
        self.assertNotIn("Data Quality & Compare", native_monitoring)
        self.assertNotIn("Governance Native Sources", native_monitoring)
        self.assertFalse((APP_ROOT / "sections" / "native_readiness.py").exists())
        self.assertNotIn("render_workload_data_quality_board", workload_text)

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Raw", readme)
        self.assertIn("`ACCOUNT_USAGE` scans are never part of Executive Landing first paint", readme)
        self.assertIn("Executive Landing is not allowed to start raw `SNOWFLAKE.ACCOUNT_USAGE` scans", refresh_doc)

    def test_native_snowflake_contracts_cover_coco_kiro_gaps(self):
        lanes = native_capability_lanes()
        labels = {row["label"] for row in lanes}
        self.assertIn("Data Quality / DMF", labels)
        self.assertIn("Native alerts", labels)
        self.assertIn("Tag allocation", labels)
        self.assertIn("OVERWATCH self-cost", labels)
        self.assertIn("Executive digest", labels)
        self.assertIn("Org rollup", labels)

        sql_bundle = "\n".join([
            build_data_quality_dmf_sql(),
            build_alert_object_registry_sql(),
            build_tag_allocation_sql(),
            build_overwatch_self_cost_sql(),
            build_executive_digest_history_sql(),
            build_org_rollup_sql(),
        ]).upper()
        for marker in (
            "DATA_METRIC_FUNCTION_REFERENCES",
            "SHOW ALERTS IN ACCOUNT",
            "ALERT_HISTORY",
            "TAG_REFERENCES",
            "QUERY_TAG ILIKE 'OVERWATCH%'",
            "EXECUTIVE_DIGEST_HISTORY",
            "ORGANIZATION_USAGE.METERING_DAILY_HISTORY",
        ):
            self.assertIn(marker, sql_bundle)


if __name__ == "__main__":
    unittest.main()
