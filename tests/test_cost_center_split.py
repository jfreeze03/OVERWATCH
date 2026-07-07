from pathlib import Path
from datetime import date
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections import cost_center  # noqa: E402
from sections import cost_center_action_queue as action_queue  # noqa: E402
from sections import cost_center_attribution_view as attribution_view  # noqa: E402
from sections import cost_center_burn_view as burn_view  # noqa: E402
from sections import cost_center_chargeback_view as chargeback_view  # noqa: E402
from sections import cost_center_contracts as contracts  # noqa: E402
from sections import cost_center_explain_view as explain_view  # noqa: E402
from sections import cost_center_explorer_view as explorer_view  # noqa: E402
from sections import cost_center_forecast_view as forecast_view  # noqa: E402
from sections import cost_center_models as models  # noqa: E402
from sections import cost_center_reconciliation_view as reconciliation_view  # noqa: E402
from sections import cost_center_sql as sql  # noqa: E402
from sections import cost_center_user_leaderboard_view as user_leaderboard_view  # noqa: E402


class CostCenterSplitTests(unittest.TestCase):
    def test_cost_center_contracts_stay_stable(self):
        self.assertEqual(
            cost_center.COST_CENTER_VIEWS,
            (
                "Cost Explorer",
                "Explain This Bill",
                "User Leaderboard",
                "Burn Rate",
                "Reconciliation",
                "Forecast",
                "Attribution",
                "Chargeback",
            ),
        )
        self.assertEqual(set(cost_center.COST_CENTER_VIEWS), set(cost_center.COST_CENTER_VIEW_DETAILS))
        self.assertEqual(cost_center.COST_CENTER_VIEW_LABELS["User Leaderboard"], "Cost by User / Role")
        self.assertEqual(cost_center.COST_CENTER_VIEW_LABELS["Burn Rate"], "Burn Rate & Forecast")
        self.assertEqual(cost_center.COST_CENTER_VIEW_LABELS["Forecast"], "Run-Rate Projection")
        self.assertEqual(cost_center.COST_CENTER_VIEW_LABELS["Chargeback"], "Chargeback / Company Split")
        for value in ("", "NONE", "NULL", "NAN", "NO_DATABASE_CONTEXT", "NO DATABASE CONTEXT"):
            self.assertIn(value, cost_center.NO_DATABASE_CONTEXT_VALUES)
        self.assertIn("Department / Cost Center", cost_center.COST_EXPLORER_LENSES)
        self.assertEqual(cost_center.COST_EXPLORER_LENS_COLUMNS["Company"], ["COMPANY"])
        self.assertEqual(
            cost_center.COST_EXPLORER_LENS_COLUMNS["Department x Warehouse"],
            ["DEPARTMENT", "WAREHOUSE_NAME"],
        )

    def test_cost_center_facade_reexports_focused_modules(self):
        for module in (
            contracts,
            models,
            sql,
            action_queue,
            explorer_view,
            explain_view,
            user_leaderboard_view,
            burn_view,
            reconciliation_view,
            forecast_view,
            attribution_view,
            chargeback_view,
        ):
            for name in module.__all__:
                with self.subTest(module=module.__name__, name=name):
                    self.assertTrue(hasattr(cost_center, name))
                    self.assertIs(getattr(cost_center, name), getattr(module, name))

    def test_row_text_handles_snowflake_and_pandas_casing(self):
        self.assertEqual(cost_center._row_text({"warehouse_name": " wh_x "}, "WAREHOUSE_NAME"), "wh_x")
        self.assertEqual(cost_center._row_text({"Warehouse_Name": "WH_Y"}, "warehouse_name"), "WH_Y")
        self.assertEqual(cost_center._row_text(pd.Series({"ROLE_NAME": "SYSADMIN"}), "role_name"), "SYSADMIN")
        self.assertEqual(cost_center._row_text(None, "missing"), "")

    def test_environment_rollup_for_cost_preserves_scope_contract(self):
        cases = [
            ({"DATABASE_NAME": "ALFA_EDW_PRD", "ENVIRONMENT": "PROD"}, "PROD"),
            ({"DATABASE_NAME": "ALFA_EDW_DEV", "ENVIRONMENT": "DEV"}, "DEV_ALL"),
            ({"DATABASE_NAME": "ALFA_EDW_SAN", "ENVIRONMENT": "SAN"}, "DEV_ALL"),
            ({"DATABASE_NAME": "TRXS_CLAIMS_PROD", "ENVIRONMENT": "PROD"}, "PROD"),
            ({"DATABASE_NAME": "TRXS_CLAIMS_DEV", "ENVIRONMENT": "DEV"}, "Trexis"),
            ({"DATABASE_NAME": "ALFA_EDW_QA", "ENVIRONMENT": "QA"}, "Other ALFA Non-Prod"),
            ({"DATABASE_NAME": "TRXS_SHARED", "ENVIRONMENT": "SHARED"}, "Trexis"),
            ({"DATABASE_NAME": "NO_DATABASE_CONTEXT"}, "No Database Context"),
            ({"DATABASE_NAME": "CUSTOM_DB", "ENVIRONMENT": "OTHER"}, "Other / Shared"),
        ]
        for row, expected in cases:
            with self.subTest(row=row):
                self.assertEqual(cost_center._environment_rollup_for_cost(row), expected)

    def test_cost_allocation_quality_and_annotation_contract(self):
        no_context = cost_center._cost_allocation_quality({"DATABASE_NAME": "NO_DATABASE_CONTEXT"})
        self.assertEqual(no_context["ALLOCATION_CONFIDENCE"], "Account-wide / Shared")
        self.assertEqual(no_context["CHARGEBACK_READY"], "No")
        self.assertEqual(no_context["SCOPE_REVIEW"], "Missing database context")

        ready = cost_center._cost_allocation_quality({
            "DATABASE_NAME": "ALFA_EDW_PRD",
            "ENVIRONMENT": "PROD",
            "ROUTE_SOURCE": "WAREHOUSE_TAG",
            "COST_ATTRIBUTION": "Finance",
        })
        self.assertEqual(ready["ENVIRONMENT_ROLLUP"], "PROD")
        self.assertEqual(ready["CHARGEBACK_READY"], "Ready")

        directional = cost_center._cost_allocation_quality({"DATABASE_NAME": "ALFA_EDW_PRD", "ENVIRONMENT": "PROD"})
        self.assertEqual(directional["CHARGEBACK_READY"], "Directional")

        review = cost_center._cost_allocation_quality({"DATABASE_NAME": "ALFA_EDW_QA", "ENVIRONMENT": "QA"})
        self.assertEqual(review["CHARGEBACK_READY"], "Review")
        self.assertEqual(review["SCOPE_REVIEW"], "Unmapped ALFA environment")

        annotated = cost_center._annotate_allocation_quality(pd.DataFrame([{
            "DATABASE_NAME": "ALFA_EDW_PRD",
            "USER_NAME": "ANALYST",
            "TOTAL_CREDITS": 5,
        }]))
        for column in ("COST_ATTRIBUTION", "ROUTE_SOURCE", "ROUTE_EVIDENCE", "ENVIRONMENT_ROLLUP"):
            self.assertIn(column, annotated.columns)
        self.assertEqual(annotated["COST_ATTRIBUTION"].iloc[0], "ANALYST")
        self.assertEqual(annotated["ROUTE_SOURCE"].iloc[0], "QUERY_USER")

    def test_chargeback_renderer_imports_shared_aggregation_labels(self):
        self.assertIs(chargeback_view._mixed_label, models._mixed_label)
        self.assertIs(chargeback_view._chargeback_readiness_label, models._chargeback_readiness_label)
        self.assertIs(chargeback_view._route_telemetry_label, models._route_telemetry_label)

    def test_prepare_cost_forecast_rows_returns_normalized_30_day_window(self):
        rows = pd.DataFrame({
            "day": ["2026-06-22T12:00:00Z", "2026-06-23T01:00:00Z"],
            "daily_credits": [10, 12.5],
        })
        forecast = cost_center._prepare_cost_forecast_rows(rows, today="2026-06-23")
        self.assertEqual(len(forecast), 30)
        self.assertEqual(forecast["DAY"].min(), pd.Timestamp("2026-05-25"))
        self.assertEqual(forecast["DAY"].max(), pd.Timestamp("2026-06-23"))
        self.assertAlmostEqual(float(forecast.loc[forecast["DAY"] == pd.Timestamp("2026-06-22"), "DAILY_CREDITS"].iloc[0]), 10.0)
        self.assertAlmostEqual(float(forecast.loc[forecast["DAY"] == pd.Timestamp("2026-06-23"), "DAILY_CREDITS"].iloc[0]), 12.5)

        empty = cost_center._prepare_cost_forecast_rows(pd.DataFrame(), today="2026-06-23")
        self.assertEqual(len(empty), 30)
        self.assertEqual(float(empty["DAILY_CREDITS"].sum()), 0.0)

    def test_cost_center_sql_builders_keep_sources_and_labels(self):
        explorer_sql = cost_center._cost_explorer_live_sql(14, "ALFA", "MAX(q.warehouse_size)", "Claims").upper()
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", explorer_sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES", explorer_sql)
        self.assertIn("COALESCE(T.COST_CENTER_TAG, T.OWNER_TAG, '') ILIKE", explorer_sql)
        self.assertIn("GROUP BY 1,2,3,4,5,6,8,9,10,11", explorer_sql)

        admin_sql = cost_center._snowflake_admin_reconciliation_sql(30)
        self.assertIn("Snowflake Admin account total", admin_sql)
        self.assertIn("Official warehouse compute total", admin_sql)
        self.assertIn("Account service / other credits", admin_sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY", admin_sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY", admin_sql)

        verify_sql = cost_center._chargeback_cost_verification_sql(
            pd.Series({"WAREHOUSE_NAME": "WH_O'HARE", "DATABASE_NAME": "DB_A", "USER_NAME": "USER_A"}),
            lookback_days=7,
            company="ALFA",
        )
        self.assertIn("WH_O''HARE", verify_sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", verify_sql)

    def test_burn_rate_account_billing_summary_matches_snowsight_source(self):
        account_daily = pd.DataFrame(
            {
                "USAGE_DATE": ["2026-06-21", "2026-06-22"],
                "DAILY_CREDITS": [10.0, 2.5],
                "DAILY_SPEND_USD": [36.8, 5.5],
            }
        )

        summary = burn_view._account_billing_summary(account_daily, warehouse_credits=9.0, credit_price=3.68)

        self.assertTrue(summary["available"])
        self.assertAlmostEqual(summary["account_credits"], 12.5)
        self.assertAlmostEqual(summary["account_cost_usd"], 42.3)
        self.assertAlmostEqual(summary["service_other_credits"], 3.5)

    def test_account_billing_sql_uses_selected_completed_window(self):
        from utils.cost import build_snowflake_service_cost_trend_sql

        account_sql = build_snowflake_service_cost_trend_sql(
            8,
            credit_price=3.68,
            ai_credit_price=2.20,
            start_date=date(2026, 6, 21),
            end_date=date(2026, 6, 28),
        ).upper()

        self.assertIn("TO_TIMESTAMP_NTZ('2026-06-21 00:00:00')", account_sql)
        self.assertIn("TO_TIMESTAMP_NTZ('2026-06-28 00:00:00')", account_sql)
        self.assertIn("DATEADD('HOUR', -24, CURRENT_TIMESTAMP())", account_sql)
        self.assertNotIn("DATEADD('DAY', -16", account_sql)

    def test_burn_rate_window_uses_global_decision_window(self):
        with patch.object(burn_view, "active_decision_window_days", return_value=8) as active_window:
            self.assertEqual(burn_view._burn_rate_window_days(30), 8)
        active_window.assert_called_once_with(30)

    def test_cost_center_action_queue_remains_review_only(self):
        with self.subTest("empty frames do not upsert"):
            with patch("sections.cost_center_action_queue.upsert_actions") as upsert, patch(
                "sections.cost_center_action_queue.st.info"
            ):
                cost_center._queue_cost_outliers("SESSION", pd.DataFrame(), 3.0, "Cost & Contract - Chargeback")
            upsert.assert_not_called()

        df = pd.DataFrame([{
            "COMPANY": "ALFA",
            "ENVIRONMENT": "Other / Shared",
            "DATABASE_NAME": "NO_DATABASE_CONTEXT",
            "USER_NAME": "Unknown user",
            "WAREHOUSE_NAME": "BI_COMPUTE_WH",
            "TOTAL_CREDITS": 400.0,
            "ALLOCATION_CONFIDENCE": "Account-wide / Shared",
            "ALLOCATION_BASIS": "No database context; do not split PROD/DEV without tags or session lineage.",
            "CHARGEBACK_READY": "No",
            "SCOPE_REVIEW": "Missing database context",
        }])
        captured = {}

        def fake_upsert(session, actions):
            captured["session"] = session
            captured["actions"] = actions
            return len(actions)

        with patch("sections.cost_center_action_queue.upsert_actions", side_effect=fake_upsert), patch(
            "sections.cost_center_action_queue.get_active_environment", return_value="ALL"
        ), patch("sections.cost_center_action_queue.st.success"):
            cost_center._queue_cost_outliers("SESSION", df, 3.0, "Cost & Contract - Chargeback")

        self.assertEqual(captured["session"], "SESSION")
        action = captured["actions"][0]
        self.assertEqual(action["Source"], "Cost & Contract - Chargeback")
        self.assertEqual(action["Category"], "Chargeback Review")
        self.assertEqual(action["Entity Type"], "Database/User/Warehouse")
        self.assertEqual(action["Owner"], "DBA / Cost attribution")
        self.assertIn("no state-changing SQL", action["Generated SQL Fix"])
        for forbidden in ("ALTER ", "DROP ", "CREATE "):
            self.assertNotIn(forbidden, action["Generated SQL Fix"].upper())

    def test_cost_center_renderer_map_and_view_keys(self):
        expected = {
            "Cost Explorer": explorer_view.render_cost_explorer,
            "Explain This Bill": explain_view.render_explain_this_bill,
            "User Leaderboard": user_leaderboard_view.render_user_leaderboard,
            "Burn Rate": burn_view.render_burn_rate,
            "Reconciliation": reconciliation_view.render_cost_reconciliation,
            "Forecast": forecast_view.render_cost_forecast,
            "Attribution": attribution_view.render_cost_attribution,
            "Chargeback": chargeback_view.render_chargeback,
        }
        self.assertEqual(set(cost_center.COST_CENTER_VIEWS), set(cost_center.COST_CENTER_RENDERERS))
        for view, renderer in expected.items():
            with self.subTest(view=view):
                self.assertIs(cost_center.COST_CENTER_RENDERERS[view], renderer)

    def test_embedded_cost_center_suppresses_nested_workflow_selector(self):
        calls = []

        def _fake_renderer(*args):
            calls.append(args)

        state = {
            "_cost_center_embedded_in_cost_contract": True,
            "cost_center_view": "Cost Explorer",
        }
        with (
            patch.object(cost_center.st, "session_state", state),
            patch.object(cost_center, "get_session", return_value=object()),
            patch.object(cost_center, "get_credit_price", return_value=4.0),
            patch.object(
                cost_center,
                "_cost_center_query_history_expressions",
                return_value=("MAX(q.warehouse_size)", "SUM(q.bytes_scanned)", "q.query_tag"),
            ),
            patch.object(
                cost_center,
                "render_workflow_selector",
                side_effect=AssertionError("Embedded Cost Center must not render a second workflow selector"),
            ),
            patch.object(cost_center, "defer_source_note"),
            patch.dict(cost_center.COST_CENTER_RENDERERS, {"Cost Explorer": _fake_renderer}),
        ):
            cost_center.render()

        self.assertEqual(len(calls), 1)

    def test_cost_center_view_files_keep_stable_widget_keys(self):
        expected_tokens = {
            "cost_center_explorer_view.py": ["cc_explorer_load", "cc_explorer_lens", "cc_explorer_queue"],
            "cost_center_explain_view.py": [
                "cc_explain_load",
                "cc_explain_period",
                "cc_explain_summary",
                "cc_explain_wh_delta",
                "cc_explain_drivers",
                "cc_explain_types",
                "cc_explain_environments",
                "cc_explain_services",
                "cc_explain_meta",
            ],
            "cost_center_user_leaderboard_view.py": [
                "cc_user_profile_sel",
                "cc_user_profile_load",
                "cc_user_profile_requested",
                "cc_lead_queue",
                "cost_leaderboard.csv",
            ],
            "cost_center_burn_view.py": ["br_days", "br_load", "df_br", "cc_burn_source", "burn_rate.csv"],
            "cost_center_reconciliation_view.py": [
                "cc_recon_days",
                "cc_recon_load",
                "df_cc_recon",
                "df_cc_admin_recon",
                "cc_recon_attribution_source",
                "cc_admin_recon_error",
                "cost_reconciliation.csv",
            ],
            "cost_center_forecast_view.py": ["df_fc", "cc_forecast_source", "cc_annual_projection_period"],
            "cost_center_attribution_view.py": ["cc_attr_days", "cc_attr_mode", "cc_attr_load", "df_cc_attr"],
            "cost_center_chargeback_view.py": ["cc_cb_days", "cc_cb_load", "cc_chargeback_queue"],
        }
        for file_name, tokens in expected_tokens.items():
            source = (APP_ROOT / "sections" / file_name).read_text(encoding="utf-8")
            for token in tokens:
                with self.subTest(file=file_name, token=token):
                    self.assertIn(token, source)

    def test_cost_center_facade_all_exports_exist_and_no_creep(self):
        for name in cost_center.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(cost_center, name))
        source = (APP_ROOT / "sections" / "cost_center.py").read_text(encoding="utf-8")
        self.assertLess(len(source.splitlines()), 150)
        for fragment in [
            "SNOWFLAKE.ACCOUNT_USAGE",
            "filter_existing_columns(",
            "run_query(",
            "pd.DataFrame(",
            "CREATE TABLE",
            "INSERT INTO",
            "# -- BURN RATE",
            "# -- COST RECONCILIATION",
            "# -- RUN-RATE PROJECTION",
            'elif cost_view == "Burn Rate"',
            'elif cost_view == "Reconciliation"',
        ]:
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, source)

if __name__ == "__main__":
    unittest.main()
