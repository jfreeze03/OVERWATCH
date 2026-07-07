from datetime import datetime, timezone
from pathlib import Path
import inspect
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


class FakeResult:
    def collect(self):
        return []


class FakeSession:
    def __init__(self):
        self.sql_texts = []

    def sql(self, sql_text):
        self.sql_texts.append(sql_text)
        return FakeResult()


class V2ProductHardeningTests(unittest.TestCase):
    def test_repository_first_paint_functions_are_cached_and_scope_keys_vary(self):
        from overwatch_app.data.repositories import executive
        from overwatch_app.data.repositories import _common

        executive.load_executive_first_paint.clear()
        calls = []

        def fake_run_query(sql, **kwargs):
            calls.append((sql, kwargs))
            return pd.DataFrame([{"SNAPSHOT_TS": "2026-07-07", "COMPANY": kwargs["company"]}])

        args = ("ALFA", "PROD", 30, "WH_ALFA_OVERWATCH", "Overview", "SNOW_SYSADMINS", "v1")
        with patch.object(_common, "run_query", side_effect=fake_run_query):
            first = executive.load_executive_first_paint(*args)
            second = executive.load_executive_first_paint(*args)
            third = executive.load_executive_first_paint("Trexis", *args[1:])

        self.assertEqual(len(calls), 2)
        self.assertEqual(first.to_dict("records"), second.to_dict("records"))
        self.assertNotEqual(first.to_dict("records"), third.to_dict("records"))
        self.assertIn("V_EXECUTIVE_SUMMARY", calls[0][0])
        self.assertIn("ALFA", calls[0][1]["ttl_key"])
        self.assertIn("TREXIS", calls[1][1]["ttl_key"])

    def test_all_repository_modules_export_cached_functions(self):
        import overwatch_app.data.repositories.alerts as alerts
        import overwatch_app.data.repositories.cost as cost
        import overwatch_app.data.repositories.dba as dba
        import overwatch_app.data.repositories.executive as executive
        import overwatch_app.data.repositories.security as security
        import overwatch_app.data.repositories.workload as workload

        for module in (alerts, cost, dba, executive, security, workload):
            with self.subTest(module=module.__name__):
                self.assertTrue(module.CACHED_REPOSITORY_FUNCTIONS)
                for func in module.CACHED_REPOSITORY_FUNCTIONS:
                    self.assertTrue(hasattr(func, "clear"), func)
                    sig = inspect.signature(func)
                    for name in ("company", "environment", "window", "warehouse", "workflow", "role", "source_version"):
                        self.assertIn(name, sig.parameters)

    def test_rbac_uses_role_context_not_settings_checkbox(self):
        from overwatch_app.security.rbac import (
            RbacContext,
            can_change_alert_status,
            can_kill_query,
            can_view_admin_workflows,
        )

        viewer = RbacContext(snowflake_role="PUBLIC")
        admin = RbacContext(snowflake_role="ACCOUNTADMIN")
        self.assertFalse(can_view_admin_workflows(viewer))
        self.assertFalse(can_kill_query(viewer))
        self.assertFalse(can_change_alert_status(viewer))
        self.assertTrue(can_view_admin_workflows(admin))
        self.assertTrue(can_kill_query(admin))
        rbac_source = (ROOT / "overwatch_app" / "security" / "rbac.py").read_text(encoding="utf-8")
        self.assertNotIn("checkbox", rbac_source.lower())
        self.assertNotIn("session_state", rbac_source)

    def test_restricted_actions_write_audit_events(self):
        from overwatch_app.data.alert_actions import AlertActionRequest, apply_alert_action
        from overwatch_app.data.live_ops import QueryKillRequest, kill_query_with_confirmation
        from overwatch_app.security.rbac import RbacContext

        session = FakeSession()
        viewer = RbacContext(snowflake_role="PUBLIC", snowflake_user="VIEWER")
        admin = RbacContext(snowflake_role="ACCOUNTADMIN", snowflake_user="ADMIN")

        denied = apply_alert_action(session, AlertActionRequest(alert_id="A1", action="acknowledge"), viewer)
        self.assertFalse(denied)
        self.assertTrue(any("OVERWATCH_APP_AUDIT_LOG" in sql for sql in session.sql_texts))

        allowed = apply_alert_action(session, AlertActionRequest(alert_id="A1", action="resolve", note="done", ticket_id="CHG-1"), admin)
        self.assertTrue(allowed)
        self.assertTrue(any("MERGE INTO OVERWATCH_ALERT_STATE" in sql for sql in session.sql_texts))
        self.assertTrue(any("OVERWATCH_ALERT_STATE_HISTORY" in sql for sql in session.sql_texts))

        self.assertFalse(kill_query_with_confirmation(session, QueryKillRequest("01abc", "wrong"), admin))
        self.assertTrue(kill_query_with_confirmation(session, QueryKillRequest("01abc", "KILL 01abc"), admin))
        self.assertTrue(any("SYSTEM$CANCEL_QUERY" in sql for sql in session.sql_texts))

    def test_audit_table_contract_columns_exist(self):
        from overwatch_app.data.audit import build_audit_table_ddl, build_audit_insert_sql, make_audit_event
        from overwatch_app.security.rbac import RbacContext

        ddl = build_audit_table_ddl()
        for column in (
            "EVENT_ID", "EVENT_TS", "APP_USER", "SNOWFLAKE_USER", "SNOWFLAKE_ROLE",
            "COMPANY", "ENVIRONMENT", "SECTION", "WORKFLOW", "ACTION_TYPE",
            "TARGET_TYPE", "TARGET_NAME", "STATUS", "MESSAGE", "QUERY_HASH", "SESSION_ID",
        ):
            self.assertIn(column, ddl)
        event = make_audit_event(
            action_type="section_view",
            status="SUCCESS",
            rbac_context=RbacContext(snowflake_role="ACCOUNTADMIN", snowflake_user="ADMIN"),
        )
        self.assertIn("INSERT INTO OVERWATCH_APP_AUDIT_LOG", build_audit_insert_sql(event))

    def test_first_paint_marts_are_precomputed_and_validated(self):
        setup_sql = (ROOT / "snowflake" / "mart_setup" / "04_mart_tables.sql").read_text(encoding="utf-8").upper()
        validation_sql = (ROOT / "snowflake" / "validation" / "validate_v2_first_paint_marts.sql").read_text(encoding="utf-8").upper()
        for view in (
            "V_EXECUTIVE_SUMMARY", "V_DBA_MORNING_COCKPIT", "V_SOURCE_FRESHNESS",
            "V_ALERT_INTELLIGENCE", "V_TASK_STATUS_DAILY", "V_WAREHOUSE_DAILY_CREDITS",
            "V_COST_FORECAST", "V_CONTRACT_BURN_DOWN", "V_LOGIN_SECURITY_DAILY",
            "V_QUERY_ERROR_SUMMARY", "V_STORAGE_DAILY", "V_CORTEX_CODE_USAGE_DAILY",
        ):
            view_block = setup_sql.rsplit(f"CREATE OR REPLACE SECURE VIEW {view}", 1)[1].split(";", 1)[0]
            self.assertIn("FROM MART_V2_", view_block)
            self.assertNotIn("SELECT *", view_block)
        v2_block = setup_sql.split("CREATE TRANSIENT TABLE IF NOT EXISTS MART_V2_EXECUTIVE_SUMMARY", 1)[1]
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", v2_block.split("GRANT SELECT ON VIEW V_QUERY_DAILY_SUMMARY", 1)[0])
        self.assertIn("V2_SOURCE_FRESHNESS_MAX_AGE_MINUTES", validation_sql)
        self.assertIn("V2_ALERT_INTELLIGENCE_NO_CORRELATED_SUBQUERY_PATTERN", validation_sql)

    def test_workflow_registry_only_exposes_implemented_unique_renderers(self):
        import importlib
        from overwatch_app.registry import SECTIONS

        renderers = []
        for section in SECTIONS:
            module = importlib.import_module(section.module)
            for workflow in section.workflows:
                self.assertTrue(workflow.visible)
                self.assertTrue(hasattr(module, workflow.renderer), workflow)
                renderers.append(f"{section.key}:{workflow.renderer}")
        self.assertEqual(len(renderers), len(set(renderers)))

    def test_metrics_registry_has_no_unrendered_metrics(self):
        from overwatch_app.metrics import REGISTERED_METRICS, RENDERED_METRICS, unrendered_metrics

        self.assertEqual(REGISTERED_METRICS, RENDERED_METRICS)
        self.assertEqual(unrendered_metrics(), {})
        serialized = str(REGISTERED_METRICS)
        for retired in ("ytd_mtd_credit_trend", "failsafe_growth", "budget_headroom_pct"):
            self.assertNotIn(retired, serialized)

    def test_executive_landing_has_decomposition_burn_down_and_real_queue(self):
        from overwatch_app.sections.executive import build_executive_view_model

        summary = pd.DataFrame([{
            "EXECUTIVE_NARRATIVE": "Ready",
            "PLATFORM_SCORE": 90,
            "COMMITTED_CREDITS": 1000,
            "CONSUMED_CREDITS": 400,
            "YEAR_ELAPSED_PCT": 50,
            "PROJECTED_PERIOD_END_CREDITS": 950,
            "TOP_COST_DRIVER": "WH_LOAD",
        }])
        actions = pd.DataFrame([{"SEVERITY": "High", "FINDING": "Queue", "STATUS": "New", "NEXT_ACTION": "Fix"}])
        model = build_executive_view_model(summary, actions, pd.DataFrame([{"SOURCE_NAME": "cost"}]))
        self.assertIn("Platform Score with decomposition", model["first_viewport_order"])
        self.assertGreater(len(model["platform_score_components"]), 1)
        self.assertIn("projected_over_under_usd", model["contract_burn_down"])
        self.assertIn("NEXT_ACTION", model["open_work_items"].columns)

    def test_cost_first_viewport_forecast_bounds_and_tag_free_chargeback(self):
        from overwatch_app.sections.cost import build_cost_view_model, build_tag_free_chargeback

        forecast = pd.DataFrame([{"DAY": "2026-07-01", "FORECAST_CREDITS": 10, "BUDGET_CREDITS": 8}])
        model = build_cost_view_model(forecast, pd.DataFrame(), pd.DataFrame([{"DRIVER": "WH", "COST_USD": 5}]))
        self.assertTrue(model["forecast_has_budget_line"])
        self.assertTrue(model["forecast_has_bounds_band"])
        self.assertLess(
            model["first_viewport_order"].index("Top Cost Drivers"),
            model["first_viewport_order"].index("KPI row"),
        )

        usage = pd.DataFrame([{"WAREHOUSE_NAME": "WH_ALFA_LOAD", "CREDITS": 10, "USAGE_DATE": "2026-07-01"}])
        rules = pd.DataFrame([{
            "COMPANY": "ALFA", "BUSINESS_UNIT": "Load", "MATCH_TYPE": "WAREHOUSE",
            "MATCH_PATTERN": "WH_ALFA", "ALLOCATION_PCT": 100, "PRIORITY": 1, "IS_ACTIVE": True,
        }])
        allocation = build_tag_free_chargeback(usage, rules)
        self.assertEqual(allocation.iloc[0]["BUSINESS_UNIT"], "Load")
        self.assertNotIn("OWNER_TAG", "".join(allocation.columns))

    def test_alert_center_is_inbox_with_detail_panel_and_writable_actions(self):
        from overwatch_app.sections.alerts import ALERT_ACTIONS, build_alert_detail, build_alert_inbox

        alerts = pd.DataFrame([{"SEVERITY": "High", "STATUS": "OPEN", "ENTITY": "WH", "MESSAGE": "Queued"}])
        inbox = build_alert_inbox(alerts)
        detail = build_alert_detail(inbox.iloc[0])
        self.assertIn("acknowledge", ALERT_ACTIONS)
        self.assertIn("resolve", ALERT_ACTIONS)
        self.assertIn("timeline", detail)
        self.assertIn("verification_closure_status", detail)
        self.assertNotIn("TRANSPOSE", inspect.getsource(build_alert_detail).upper())

    def test_dba_live_mode_requires_rbac_and_labels_latency(self):
        from overwatch_app.sections.dba import build_live_mode_model
        from overwatch_app.security.rbac import RbacContext

        denied = build_live_mode_model(pd.DataFrame(), RbacContext(snowflake_role="PUBLIC"))
        allowed = build_live_mode_model(pd.DataFrame([{"QUERY_ID": "01"}]), RbacContext(snowflake_role="ACCOUNTADMIN"))
        self.assertTrue(denied["access_denied"])
        self.assertTrue(allowed["allowed"])
        self.assertIn("ACCOUNT_USAGE latency disclosed", allowed["latency_caveat"])
        self.assertTrue(allowed["kill_requires_confirmation"])
        self.assertTrue(allowed["kill_requires_audit"])

    def test_workload_metrics_and_anomaly_detection_are_rendered(self):
        from overwatch_app.sections.workload import WORKLOAD_METRICS, detect_query_anomalies

        for metric in ("ERROR_CODE_FREQUENCY", "TOP_ERROR_CODE", "SLA_ATTAINMENT"):
            self.assertIn(metric, WORKLOAD_METRICS)
        current = pd.DataFrame([{"QUERY_HASH": "A", "DURATION_MS": 300, "REMOTE_SPILL_GB": 2}])
        baseline = pd.DataFrame([{"QUERY_HASH": "A", "DURATION_MS": 50, "REMOTE_SPILL_GB": 1}])
        anomalies = detect_query_anomalies(current, baseline)
        self.assertIn("same_query_hash_3x_duration", set(anomalies["ANOMALY_TYPE"]))
        self.assertIn("spill_regression", set(anomalies["ANOMALY_TYPE"]))

    def test_security_heuristics_have_threshold_confidence_latency_and_retention(self):
        from overwatch_app.sections.security import SECURITY_RETENTION_SETTINGS, suspicious_login_heuristics

        events = pd.DataFrame([
            {"CLIENT_IP": "1.1.1.1", "USER_NAME": "A", "FAILED": 1, "PRIVILEGED_USER": 1},
            {"CLIENT_IP": "1.1.1.1", "USER_NAME": "B", "FAILED": 1, "PRIVILEGED_USER": 0},
            {"CLIENT_IP": "1.1.1.1", "USER_NAME": "C", "FAILED": 1, "PRIVILEGED_USER": 0},
        ])
        heuristics = suspicious_login_heuristics(events)
        self.assertTrue({"RULE_NAME", "THRESHOLD", "EVIDENCE_COUNT", "CONFIDENCE", "SOURCE_LATENCY"}.issubset(heuristics.columns))
        self.assertGreaterEqual(SECURITY_RETENTION_SETTINGS["SECURITY_RETENTION_DAYS"], 365)
        self.assertGreaterEqual(SECURITY_RETENTION_SETTINGS["LOGIN_RETENTION_DAYS"], 365)
        self.assertGreaterEqual(SECURITY_RETENTION_SETTINGS["GRANT_RETENTION_DAYS"], 365)

    def test_timezone_freshness_handles_ntz_and_display_timezone(self):
        from overwatch_app.timezone import freshness_minutes, to_display_timezone

        now = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(freshness_minutes("2026-07-07 11:30:00", now=now), 30)
        display = to_display_timezone("2026-07-07 12:00:00+00:00")
        self.assertEqual(str(display.tzinfo), "America/Chicago")

    def test_dashboard_self_cost_and_governance_levers_exist(self):
        setup = (ROOT / "snowflake" / "mart_setup" / "04_mart_tables.sql").read_text(encoding="utf-8").upper()
        settings = (ROOT / "snowflake" / "mart_setup" / "03_config_and_audit_tables.sql").read_text(encoding="utf-8").upper()
        self.assertIn("MART_V2_OVERWATCH_APP_SELF_COST_DAILY", setup)
        for column in ("TASK_CREDITS", "APP_QUERY_CREDITS", "REFRESH_WAREHOUSE_CREDITS", "EST_MONTHLY_COST_USD", "PCT_OF_MONITORED_SPEND"):
            self.assertIn(column, setup)
        for setting in ("ANNUAL_COMMITTED_CREDITS", "CONTRACT_PERIOD_START", "CONTRACT_PERIOD_END", "BUDGET_SOURCE_LABEL"):
            self.assertIn(setting, settings)

    def test_dead_components_are_absent_from_v2_product_path(self):
        source = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in (ROOT / "overwatch_app").rglob("*.py"))
        for token in ("detail_action", "DETAIL_ACTION_LABELS", "action_card_html", "severity_badge_html", "donut_chart"):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
