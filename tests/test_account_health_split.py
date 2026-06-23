from pathlib import Path
import sys
import unittest

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections import account_health  # noqa: E402
from sections import account_health_common as common  # noqa: E402
from sections import account_health_contracts as contracts  # noqa: E402
from sections import account_health_data as data  # noqa: E402
from sections import account_health_models as models  # noqa: E402
from sections import account_health_source_health_view as source_health_view  # noqa: E402
from sections import account_health_sql as sql  # noqa: E402


class AccountHealthSplitTests(unittest.TestCase):
    def setUp(self):
        self._previous_state = dict(st.session_state)
        st.session_state.clear()

    def tearDown(self):
        st.session_state.clear()
        st.session_state.update(self._previous_state)

    def test_account_health_contracts_stay_stable(self):
        self.assertEqual(account_health.ACCOUNT_HEALTH_PANES, ("Overview", "Morning Report"))
        self.assertEqual(account_health.ACCOUNT_HEALTH_PANE_LABELS["Overview"], "Health Workspace")
        self.assertEqual(account_health.ACCOUNT_HEALTH_PANE_LABELS["Morning Report"], "DBA Daily Brief")
        self.assertEqual(set(account_health.ACCOUNT_HEALTH_PANES), set(account_health.ACCOUNT_HEALTH_PANE_DETAILS))
        self.assertEqual(
            account_health.ACCOUNT_HEALTH_SCOPE_FILTER_KEYS,
            (
                "global_start_date",
                "global_end_date",
                "global_warehouse",
                "global_user",
                "global_role",
                "global_database",
            ),
        )
        self.assertEqual(account_health.CHECKLIST_HISTORY_TABLE, "OVERWATCH_DBA_CHECKLIST_HISTORY")
        self.assertEqual(
            account_health.ACCOUNT_HEALTH_OPERABILITY_FACT_TABLE,
            "FACT_ACCOUNT_HEALTH_OPERABILITY_DAILY",
        )
        self.assertEqual(account_health.ACCOUNT_HEALTH_ACTION_SOURCE, "Account Health - Daily DBA Checklist")
        self.assertEqual(
            account_health.ACCOUNT_HEALTH_ACCESS_HYGIENE_SOURCE,
            "Account Health - Account Access Hygiene",
        )

    def test_account_health_facade_reexports_initial_focused_modules(self):
        for module in (contracts, common, data, models, source_health_view, sql):
            for name in module.__all__:
                with self.subTest(module=module.__name__, name=name):
                    self.assertTrue(hasattr(account_health, name))
                    self.assertIs(getattr(account_health, name), getattr(module, name))

    def test_canonical_route_preserves_retired_account_health_redirect(self):
        self.assertEqual(account_health._canonical_account_route(None), "DBA Control Room")
        self.assertEqual(account_health._canonical_account_route("Account Health"), "DBA Control Room")
        self.assertEqual(account_health._canonical_account_route("Command Center"), "DBA Control Room")
        self.assertEqual(account_health._canonical_account_route("DBA Control Room"), "DBA Control Room")

    def test_credit_price_uses_session_value_or_default(self):
        self.assertEqual(account_health.get_credit_price(), 3.68)
        st.session_state["credit_price"] = "4.25"
        self.assertEqual(account_health.get_credit_price(), 4.25)

    def test_scope_meta_and_matching_use_global_filters(self):
        state = {
            "global_start_date": "2026-06-01",
            "global_end_date": "2026-06-23",
            "global_warehouse": "WH_ALFA_LOAD",
            "global_user": "ANALYST",
            "global_role": "SYSADMIN",
            "global_database": "ALFA_EDW_PROD",
        }
        meta = account_health._account_health_scope_meta("ALFA", "PROD", window="30d", state=state)
        self.assertEqual(meta["company"], "ALFA")
        self.assertEqual(meta["environment"], "PROD")
        self.assertEqual(meta["window"], "30d")
        self.assertTrue(account_health._account_health_meta_matches(dict(meta), meta))
        self.assertFalse(account_health._account_health_meta_matches({**meta, "global_role": "ANALYST"}, meta))

        no_db_meta = account_health._account_health_scope_meta(
            "ALFA",
            "PROD",
            window="30d",
            state=state,
            ignore_environment=True,
            filter_keys=("global_user",),
        )
        self.assertEqual(no_db_meta["environment"], "No Database Context")
        self.assertEqual(set(no_db_meta), {"company", "environment", "window", "global_user"})

    def test_loaded_empty_and_row_count_helpers(self):
        frame = pd.DataFrame([{"A": 1}, {"A": 2}])
        empty = pd.DataFrame()
        self.assertTrue(account_health._account_health_loaded(frame))
        self.assertEqual(account_health._account_health_row_count(frame), 2)
        self.assertFalse(account_health._account_health_is_empty(frame))
        self.assertTrue(account_health._account_health_is_empty(empty))
        self.assertEqual(account_health._account_health_row_count({"a": frame, "b": empty}), 2)
        self.assertTrue(account_health._account_health_loaded("ready"))
        self.assertFalse(account_health._account_health_is_empty("ready"))
        self.assertEqual(account_health._account_health_row_count("ready"), 1)
        self.assertFalse(account_health._account_health_loaded(None))

    def test_source_confidence_labels_stay_stable(self):
        self.assertEqual(
            account_health._account_health_source_confidence("Fast account mart summary", "Mixed"),
            "Fast summary",
        )
        self.assertEqual(
            account_health._account_health_source_confidence("Live fallback: ACCOUNT_USAGE", "Mixed"),
            "Live fallback",
        )
        self.assertEqual(
            account_health._account_health_source_confidence("INFORMATION_SCHEMA status probe", "Mixed"),
            "Live Snowflake metadata",
        )
        self.assertEqual(account_health._account_health_source_confidence("workflow rows", "Workflow telemetry"), "Workflow telemetry")

    def test_source_health_rows_classify_all_expected_states(self):
        state = {
            "global_user": "ANALYST",
            "health_data": {
                "_account_health_detail_source": "Fast account health summary",
                "_control_mart": pd.DataFrame([{"HEALTH_SCORE": 92}]),
                "_control_mart_source": "Fast control-room summary",
                "live": pd.DataFrame(),
                "_live_source": "ACCOUNT_USAGE",
            },
            "account_health_overview_meta": account_health._account_health_scope_meta("ALFA", "PROD", window="24h", state={"global_user": "ANALYST"}),
            "account_health_live_status_meta": account_health._account_health_scope_meta("ALFA", "PROD", window="1h", state={"global_user": "ANALYST"}),
            "account_health_operability_fact_error": "missing mart",
            "account_health_access_hygiene": pd.DataFrame([{"USER_NAME": "USER_A"}]),
            "account_health_checklist_trend_days": 30,
        }

        rows = account_health._account_health_source_health_rows(state, "ALFA", "PROD")
        state_by_surface = dict(zip(rows["SURFACE"], rows["STATE"]))
        self.assertEqual(state_by_surface["Overview snapshot"], "Loaded")
        self.assertEqual(state_by_surface["Control-room summary"], "Loaded")
        self.assertEqual(state_by_surface["Live status probe"], "No Rows")
        self.assertEqual(state_by_surface["Control summary"], "Unavailable")
        self.assertEqual(state_by_surface["Access hygiene"], "Stale")
        self.assertEqual(state_by_surface["Checklist trend"], "On demand")

    def test_account_health_sql_builders_stay_deterministic(self):
        checklist_fqn = account_health.account_health_checklist_history_fqn(
            db="APP_DB",
            schema="ALERTING",
            table="CHECKLIST",
        )
        self.assertEqual(checklist_fqn, "APP_DB.ALERTING.CHECKLIST")
        action_fqn = account_health.account_health_action_queue_fqn(
            db="APP_DB",
            schema="ALERTING",
            table="ACTION_QUEUE",
        )
        self.assertEqual(action_fqn, "APP_DB.ALERTING.ACTION_QUEUE")

        checklist_ddl = account_health.build_account_health_checklist_history_ddl(
            db="APP_DB",
            schema="ALERTING",
            table="CHECKLIST",
        )
        self.assertIn("CREATE TABLE IF NOT EXISTS APP_DB.ALERTING.CHECKLIST", checklist_ddl)
        self.assertIn("VERIFICATION_QUERY", checklist_ddl)
        self.assertIn("RECOVERY_SLA_TARGET_HOURS", checklist_ddl)

        operability_ddl = account_health.build_account_health_operability_fact_ddl(table="FACT_TEST")
        self.assertIn("CREATE TRANSIENT TABLE IF NOT EXISTS", operability_ddl)
        self.assertIn("FACT_TEST", operability_ddl)
        self.assertIn("CONTROL_RANK", operability_ddl)

        self.assertTrue(
            all(
                "ADD COLUMN IF NOT EXISTS" in statement
                for statement in account_health.build_account_health_checklist_history_migration_sql()
            )
        )
        self.assertTrue(
            all(
                "ADD COLUMN IF NOT EXISTS" in statement
                for statement in account_health.build_account_health_operability_fact_migration_sql(table="FACT_TEST")
            )
        )

    def test_account_health_data_helper_contracts(self):
        defaults = account_health._default_query_history_capabilities()
        self.assertEqual(account_health._account_query_history_capabilities(None), defaults)
        self.assertEqual(defaults["cost_wh_size_expr"], "NULL::VARCHAR")
        self.assertIn("FAILED_WITH_ERROR", defaults["failed_pred_q"])

        live_sql = account_health._live_query_status_sql(
            "AND q.warehouse_name = 'WH'",
            "AND q.database_name = 'DB'",
            "AND q.user_name = 'USER_A'",
        )
        self.assertIn("INFORMATION_SCHEMA.QUERY_HISTORY", live_sql)
        self.assertIn("RESULT_LIMIT=>10000", live_sql)
        self.assertIn("AND q.warehouse_name = 'WH'", live_sql)
        self.assertIn("AND q.database_name = 'DB'", live_sql)
        self.assertIn("AND q.user_name = 'USER_A'", live_sql)

    def test_control_room_mart_gate_respects_all_scope_and_global_filters(self):
        self.assertEqual(account_health._can_use_control_room_mart("ALL")[0], False)
        ok, reason = account_health._can_use_control_room_mart("ALFA")
        self.assertTrue(ok)
        self.assertEqual(reason, "")
        st.session_state["global_user"] = "ANALYST"
        ok, reason = account_health._can_use_control_room_mart("ALFA")
        self.assertFalse(ok)
        self.assertIn("Global user filters are active", reason)

    def test_account_health_has_source_state_detects_loaded_or_error_surfaces(self):
        self.assertFalse(account_health._account_health_has_source_state({}))
        self.assertTrue(account_health._account_health_has_source_state({"health_data": {"live": pd.DataFrame()}}))
        self.assertTrue(account_health._account_health_has_source_state({"morning_data_error": "load failed"}))

    def test_account_health_shell_has_initial_split_guard(self):
        source = (APP_ROOT / "sections" / "account_health.py").read_text(encoding="utf-8")
        self.assertLess(len(source.splitlines()), 3200)
        for fragment in [
            "ACCOUNT_HEALTH_PANES = (",
            "ACCOUNT_HEALTH_SCOPE_FILTER_KEYS = (",
            "def _account_query_history_capabilities",
            "def _account_health_scope_meta",
            "def _account_health_source_health_rows",
            "def _canonical_account_route",
            "def _live_query_status_sql",
            "def _render_account_health_source_health",
            "def build_account_health_checklist_history_ddl",
            "def build_account_health_operability_fact_ddl",
        ]:
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, source)


if __name__ == "__main__":
    unittest.main()
