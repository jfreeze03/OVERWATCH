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


class V2CurrentBranchHardeningTests(unittest.TestCase):
    def setUp(self):
        from overwatch_app.data.repositories import _common

        _common.clear_first_paint_cache()

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


if __name__ == "__main__":
    unittest.main()
