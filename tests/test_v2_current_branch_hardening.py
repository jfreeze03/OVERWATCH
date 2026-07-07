from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def collect(self):
        return self._rows


class _RoleSession:
    def __init__(self, role="SNOW_SYSADMINS"):
        self.role = role
        self.sql_texts = []

    def sql(self, sql_text):
        self.sql_texts.append(sql_text)
        if "CURRENT_ROLE()" in sql_text:
            return _Rows([{"CURRENT_ROLE": self.role}])
        return _Rows([{"SETTING_VALUE": '["SNOW_ACCOUNTADMINS","SNOW_SYSADMINS"]'}])


class _ScopeRow:
    COMPANY = "ALFA"
    ENVIRONMENT = "PROD"
    WAREHOUSE_NAME = "WH_ALFA_LOAD"


class _ScopeSession:
    def __init__(self):
        self.sql_texts = []

    def sql(self, sql_text):
        self.sql_texts.append(sql_text)
        return _Rows([
            _ScopeRow(),
            {"COMPANY": "Trexis", "ENVIRONMENT": "NONPROD", "WAREHOUSE_NAME": "WH_TRXS_QUERY"},
        ])


class V2CurrentBranchHardeningTests(unittest.TestCase):
    def setUp(self):
        from overwatch_app.data.repositories import _common
        from overwatch_app.data.repositories.scope import clear_scope_options_cache

        _common.clear_first_paint_cache()
        clear_scope_options_cache()

    def test_dataframe_cache_copies_hits_and_retries_failure_states(self):
        from overwatch_app.data.repositories import _common

        kwargs = dict(
            cache_key="cache-test",
            section="Executive Landing",
            company="ALFA",
            environment="PROD",
            window=30,
            warehouse="ALL",
            workflow="Overview",
            role="SNOW_SYSADMINS",
            source_version="current",
        )
        calls = []

        def success(sql, **params):
            calls.append((sql, params))
            return pd.DataFrame([{"VALUE": 1}])

        with patch.object(_common, "run_query", side_effect=success):
            first = _common.read_first_paint_view("SELECT * FROM V_EXECUTIVE_SUMMARY", **kwargs)
            first.loc[0, "VALUE"] = 99
            second = _common.read_first_paint_view("SELECT * FROM V_EXECUTIVE_SUMMARY", **kwargs)

        self.assertEqual(len(calls), 1)
        self.assertEqual(second.loc[0, "VALUE"], 1)

        _common.clear_first_paint_cache()
        frames = [
            pd.DataFrame([{"DATA_STATE": "QUERY_FAILED"}]),
            pd.DataFrame([{"DATA_STATE": "LOADED", "VALUE": 2}]),
        ]

        with patch.object(_common, "run_query", side_effect=lambda *args, **params: frames.pop(0)):
            _common.read_first_paint_view("SELECT * FROM V_EXECUTIVE_SUMMARY", **kwargs)
            recovered = _common.read_first_paint_view("SELECT * FROM V_EXECUTIVE_SUMMARY", **kwargs)

        self.assertEqual(recovered.loc[0, "VALUE"], 2)

    def test_access_control_reads_json_roles_and_hides_admin_workflows(self):
        from overwatch_app.data.access_control import is_admin
        from overwatch_app.registry import visible_workflows

        self.assertFalse(is_admin(None))
        self.assertTrue(is_admin(_RoleSession()))
        dba_visible = {workflow.key for workflow in visible_workflows("dba", include_admin=False)}
        dba_admin = {workflow.key for workflow in visible_workflows("dba", include_admin=True)}
        self.assertNotIn("live", dba_visible)
        self.assertIn("live", dba_admin)

    def test_scope_options_use_data_when_session_exists_and_defaults_offline(self):
        from overwatch_app.data.repositories.scope import fetch_scope_options

        offline = fetch_scope_options(None)
        self.assertEqual(offline.companies, ("ALL", "ALFA", "Trexis"))
        self.assertEqual(offline.warehouses, ("ALL",))

        session = _ScopeSession()
        loaded = fetch_scope_options(session)
        self.assertEqual(loaded.state, "loaded")
        self.assertEqual(loaded.companies, ("ALL", "ALFA", "Trexis"))
        self.assertEqual(loaded.environments, ("ALL", "NONPROD", "PROD"))
        self.assertEqual(loaded.warehouses, ("ALL", "WH_ALFA_LOAD", "WH_TRXS_QUERY"))
        self.assertIn("V_WAREHOUSE_DAILY_CREDITS", session.sql_texts[0])

    def test_alert_detail_panel_model_has_product_fields(self):
        from overwatch_app.sections.alerts import build_alert_detail

        detail = build_alert_detail({
            "ALERT_ID": "A1",
            "SEVERITY": "Critical",
            "STATUS": "OPEN",
            "ENTITY": "WH_LOAD",
            "MESSAGE": "Queue pressure",
            "DELIVERY_STATUS": "Delivered",
            "ACK_AGE_MINUTES": 15,
            "RESOLVE_AGE_MINUTES": 45,
            "IS_OVERDUE": True,
            "SOURCE_OBJECT": "MART_V2_ALERT_INTELLIGENCE",
        })
        for key in ("delivery_status", "ack_age_minutes", "resolve_age_minutes", "is_overdue", "source_object"):
            self.assertIn(key, detail)
        self.assertTrue(detail["is_overdue"])

    def test_server_age_minutes_preferred_over_client_timestamp_math(self):
        from overwatch_app.timezone import freshness_minutes_from_row

        self.assertEqual(freshness_minutes_from_row({"AGE_MINUTES": 7, "SNAPSHOT_TS": "2020-01-01"}), 7)

    def test_v2_sql_contract_adds_sla_config_and_server_age(self):
        setup_03 = (ROOT / "snowflake" / "mart_setup" / "03_config_and_audit_tables.sql").read_text(encoding="utf-8").upper()
        setup_04 = (ROOT / "snowflake" / "mart_setup" / "04_mart_tables.sql").read_text(encoding="utf-8").upper()

        self.assertIn("CREATE TABLE IF NOT EXISTS OVERWATCH_ALERT_SLA", setup_03)
        self.assertIn("MONTHLY_BUDGET_USD", setup_03)
        self.assertIn("OVERWATCH_ADMIN_ROLES", setup_03)
        self.assertIn("DATEDIFF('MINUTE', SNAPSHOT_TS, CURRENT_TIMESTAMP()) AS AGE_MINUTES", setup_04)
        self.assertIn("DELIVERY_STATUS", setup_04)
        self.assertIn("IS_OVERDUE", setup_04)

    def test_missing_budget_and_contract_config_render_as_setup_required(self):
        from overwatch_app.sections.cost import build_cost_view_model
        from overwatch_app.sections.executive import build_contract_burn_down, render_executive_overview
        import inspect

        burn = build_contract_burn_down({"COMMITTED_CREDITS": None, "CONSUMED_CREDITS": 10})
        self.assertTrue(burn["setup_required"])
        self.assertIsNone(burn["annual_commit_burn_pct"])

        model = build_cost_view_model(
            pd.DataFrame([{"DAY": "2026-07-01", "FORECAST_CREDITS": 10, "BUDGET_CREDITS": None}]),
            pd.DataFrame(),
            pd.DataFrame(),
        )
        self.assertFalse(model["forecast_has_budget_line"])
        self.assertTrue(model["forecast_budget_setup_required"])
        self.assertNotIn("st.json", inspect.getsource(render_executive_overview))


if __name__ == "__main__":
    unittest.main()
