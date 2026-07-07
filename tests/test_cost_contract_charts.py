from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class CostContractChartTests(unittest.TestCase):
    def test_cost_contract_reexports_moved_chart_helpers(self):
        from sections import cost_contract
        from sections import cost_contract_charts

        self.assertIs(cost_contract._altair, cost_contract_charts._altair)
        self.assertIs(cost_contract._cost_chart_palette, cost_contract_charts._cost_chart_palette)
        self.assertIs(cost_contract._render_cost_chart_with_data_toggle, cost_contract_charts._render_cost_chart_with_data_toggle)
        self.assertIs(cost_contract._render_spend_trend_chart, cost_contract_charts._render_spend_trend_chart)
        self.assertIs(cost_contract._render_cost_advisor_category_chart, cost_contract_charts._render_cost_advisor_category_chart)
        self.assertIs(cost_contract.build_account_billed_cost_trend_rows, cost_contract_charts.build_account_billed_cost_trend_rows)
        self.assertIs(cost_contract.build_warehouse_bridge_top_rows, cost_contract_charts.build_warehouse_bridge_top_rows)
        self.assertIs(cost_contract.cost_db_chart_pattern_results, cost_contract_charts.cost_db_chart_pattern_results)

    def test_cost_chart_palette_returns_carbon_for_unknown_legacy_values(self):
        from sections import cost_contract_charts

        with patch.object(cost_contract_charts.st, "session_state", {}):
            carbon = cost_contract_charts._cost_chart_palette()
        self.assertEqual(carbon["bar"], "#29B5E8")
        self.assertEqual(carbon["text"], "#eef8fb")

        with patch.object(cost_contract_charts.st, "session_state", {"active_theme": "old_theme"}):
            fallback = cost_contract_charts._cost_chart_palette()
        self.assertEqual(fallback, carbon)

    def test_chart_toggle_uses_mode_and_requested_key_contract(self):
        from sections import cost_contract_charts

        state = {"cost_demo_chart_data_requested": "Data"}
        chart_renderer = Mock()
        rows = pd.DataFrame({"A": [1]})

        def _mode_selector(label, key, options, *, default):
            self.assertEqual(label, "Cost chart view")
            self.assertEqual(key, "cost_demo_chart_data_mode")
            self.assertEqual(options, ("Chart", "Data"))
            self.assertEqual(default, "Chart")
            return state.get(key, default)

        with (
            patch.object(cost_contract_charts.st, "session_state", state),
            patch.object(cost_contract_charts, "render_escaped_bold_text") as title,
            patch.object(cost_contract_charts, "render_mode_selector", side_effect=_mode_selector),
            patch.object(cost_contract_charts.st, "columns", return_value=[_Context(), _Context()]),
            patch.object(cost_contract_charts.st, "button", return_value=False) as button,
            patch.object(cost_contract_charts.st, "caption"),
            patch.object(cost_contract_charts, "render_priority_dataframe") as table,
        ):
            cost_contract_charts._render_cost_chart_with_data_toggle(
                "Demo Chart",
                "cost_demo",
                chart_renderer,
                rows,
                priority_columns=["A"],
                sort_by=["A"],
                max_rows=5,
            )

        title.assert_called_once_with("Demo Chart")
        self.assertEqual(state["cost_demo_chart_data_mode"], "Data")
        self.assertNotIn("cost_demo_chart_data_requested", state)
        button.assert_called_once_with("Back to chart", key="cost_demo_back_to_chart", width="stretch")
        chart_renderer.assert_not_called()
        table.assert_called_once()
        self.assertEqual(table.call_args.kwargs["title"], "Demo Chart data")
        self.assertEqual(table.call_args.kwargs["raw_label"], "Demo Chart full data")
        self.assertEqual(table.call_args.kwargs["priority_columns"], ["A"])
        self.assertEqual(table.call_args.kwargs["sort_by"], ["A"])
        self.assertEqual(table.call_args.kwargs["max_rows"], 5)

    def test_chart_toggle_back_to_chart_sets_requested_chart_before_rerun(self):
        from sections import cost_contract_charts

        state = {"cost_demo_chart_data_mode": "Data"}

        with (
            patch.object(cost_contract_charts.st, "session_state", state),
            patch.object(cost_contract_charts, "render_escaped_bold_text"),
            patch.object(cost_contract_charts, "render_mode_selector", return_value="Data"),
            patch.object(cost_contract_charts.st, "columns", return_value=[_Context(), _Context()]),
            patch.object(cost_contract_charts.st, "button", return_value=True),
            patch.object(cost_contract_charts.st, "rerun", side_effect=RuntimeError("rerun")),
        ):
            with self.assertRaisesRegex(RuntimeError, "rerun"):
                cost_contract_charts._render_cost_chart_with_data_toggle(
                    "Demo Chart",
                    "cost_demo",
                    Mock(),
                    pd.DataFrame({"A": [1]}),
                )

        self.assertEqual(state["cost_demo_chart_data_requested"], "Chart")

    def test_chart_toggle_chart_mode_calls_renderer(self):
        from sections import cost_contract_charts

        state = {}
        chart_renderer = Mock()
        with (
            patch.object(cost_contract_charts.st, "session_state", state),
            patch.object(cost_contract_charts, "render_escaped_bold_text"),
            patch.object(cost_contract_charts, "render_mode_selector", return_value="Chart"),
        ):
            cost_contract_charts._render_cost_chart_with_data_toggle(
                "Demo Chart",
                "cost_demo",
                chart_renderer,
                pd.DataFrame({"A": [1]}),
            )

        chart_renderer.assert_called_once_with()

    def test_mode_selector_omits_default_when_session_state_already_has_key(self):
        from utils import workflows

        state = {"cost_demo_chart_data_mode": "Data"}
        captured: dict[str, object] = {}

        def _segmented_control(label, options, **kwargs):
            captured.update(kwargs)
            return state["cost_demo_chart_data_mode"]

        with patch.object(workflows.st, "session_state", state), patch.object(
            workflows.st,
            "segmented_control",
            side_effect=_segmented_control,
            create=True,
        ):
            selected = workflows.render_mode_selector(
                "Chart view",
                "cost_demo_chart_data_mode",
                ("Chart", "Data"),
                default="Chart",
            )

        self.assertEqual(selected, "Data")
        self.assertNotIn("default", captured)
        self.assertEqual(captured["key"], "cost_demo_chart_data_mode")

    def test_cost_charts_keep_altair_lazy(self):
        chart_text = (APP_ROOT / "sections" / "cost_contract_charts.py").read_text(encoding="utf-8")

        self.assertNotIn("\nimport altair as alt", chart_text.split("def _altair", 1)[0])
        self.assertIn("def _altair", chart_text)
        self.assertIn("alt = _altair()", chart_text)

    def test_cost_db_chart_pattern_results_are_lazy(self):
        from sections import cost_contract_charts

        results = cost_contract_charts.cost_db_chart_pattern_results()

        self.assertTrue(results["passed"], results)
        self.assertFalse(results["autoloads_on_first_paint"])
        self.assertEqual(results["chart_count"], 6)
        self.assertIn("weekly_stacked_bar", results["patterns"].values())

    def test_account_billed_cost_trend_uses_credit_price(self):
        from sections import cost_contract_charts

        rows = cost_contract_charts.build_account_billed_cost_trend_rows(
            pd.DataFrame(
                {
                    "USAGE_DATE": ["2026-06-21", "2026-06-21", "2026-06-22"],
                    "CREDITS_BILLED": ["1.5", "2.5", "1.0"],
                }
            ),
            3.68,
        )

        self.assertEqual(rows["ACCOUNT_BILLED_CREDITS"].tolist(), [4.0, 1.0])
        self.assertEqual(rows["ACCOUNT_BILLED_COST_USD"].tolist(), [14.72, 3.68])
        self.assertEqual(rows.attrs["credit_column"], "CREDITS_BILLED")

    def test_account_billed_cost_trend_accepts_daily_credits(self):
        from sections import cost_contract_charts

        rows = cost_contract_charts.build_account_billed_cost_trend_rows(
            pd.DataFrame({"USAGE_DATE": ["2026-06-21", "2026-06-22"], "DAILY_CREDITS": ["2.0", "3.0"]}),
            3.68,
        )

        self.assertEqual(rows["ACCOUNT_BILLED_CREDITS"].tolist(), [2.0, 3.0])
        self.assertEqual(rows["ACCOUNT_BILLED_COST_USD"].tolist(), [7.36, 11.04])
        self.assertEqual(rows.attrs["credit_column"], "DAILY_CREDITS")

    def test_service_distribution_uses_account_price_and_cortex_rows_use_ai_price(self):
        from sections import cost_contract_charts

        service_rows = pd.DataFrame(
            {
                "USAGE_DATE": ["2026-06-21", "2026-06-21", "2026-06-22"],
                "SERVICE_TYPE": ["WAREHOUSE_METERING", "CORTEX_AI", "CORTEX_AI"],
                "DAILY_CREDITS": ["1", "2", "3"],
            }
        )
        distribution = cost_contract_charts.build_service_type_distribution_rows(service_rows, 3.68)
        cortex = cost_contract_charts.build_cortex_ai_daily_spend_rows(service_rows, 2.20)

        self.assertEqual(float(distribution.loc[distribution["SERVICE_TYPE"] == "CORTEX_AI", "COST_USD"].iloc[0]), 18.4)
        self.assertEqual(cortex["CORTEX_AI_COST_USD"].tolist(), [4.4, 6.6])
        self.assertEqual(distribution.attrs["credit_column"], "DAILY_CREDITS")
        self.assertEqual(cortex.attrs["credit_column"], "DAILY_CREDITS")

    def test_cortex_daily_spend_prefers_cortex_ai_credits_and_allowlist(self):
        from sections import cost_contract_charts

        service_rows = pd.DataFrame(
            {
                "USAGE_DATE": ["2026-06-21", "2026-06-21", "2026-06-21"],
                "SERVICE_TYPE": ["CORTEX_AI", "MAINTENANCE_AI_HELPER", "AI_SERVICES"],
                "CORTEX_AI_CREDITS": ["1", "99", "2"],
                "DAILY_CREDITS": ["10", "99", "20"],
            }
        )

        cortex = cost_contract_charts.build_cortex_ai_daily_spend_rows(service_rows, 2.20)

        self.assertEqual(cortex["CORTEX_AI_CREDITS"].tolist(), [3.0])
        self.assertEqual(cortex["CORTEX_AI_COST_USD"].tolist(), [6.6])
        self.assertEqual(cortex.attrs["credit_column"], "CORTEX_AI_CREDITS")

    def test_warehouse_top_and_weekly_rows_match_compute_plus_cloud(self):
        from sections import cost_contract_charts

        warehouse_rows = pd.DataFrame(
            {
                "START_TIME": ["2026-06-21 01:00:00", "2026-06-22 02:00:00", "2026-06-22 03:00:00"],
                "WAREHOUSE_ID": [1, 0, 2],
                "WAREHOUSE_NAME": ["WH_ALFA_OVERWATCH", "PSEUDO", "LOAD_WH"],
                "CREDITS_USED_COMPUTE": ["2", "100", "3"],
                "CREDITS_USED_CLOUD_SERVICES": ["0.5", "10", "1"],
            }
        )

        top = cost_contract_charts.build_warehouse_bridge_top_rows(warehouse_rows, 3.68)
        weekly = cost_contract_charts.build_weekly_warehouse_cost_rows(warehouse_rows, 3.68)
        hourly = cost_contract_charts.build_hourly_usage_pattern_rows(warehouse_rows, 3.68)

        self.assertEqual(top["WAREHOUSE_NAME"].tolist(), ["LOAD_WH", "WH_ALFA_OVERWATCH"])
        self.assertEqual(top["WAREHOUSE_CREDITS"].tolist(), [4.0, 2.5])
        self.assertEqual(round(float(weekly["WAREHOUSE_COST_USD"].sum()), 2), 23.92)
        self.assertIn("HOUR", hourly.columns)
        self.assertEqual(top.attrs["credit_column"], "CREDITS_USED_COMPUTE + CREDITS_USED_CLOUD_SERVICES")

    def test_missing_credit_column_returns_unavailable_state(self):
        from sections import cost_contract_charts

        rows = cost_contract_charts.build_account_billed_cost_trend_rows(
            pd.DataFrame({"USAGE_DATE": ["2026-06-21"], "NOT_CREDITS": [5]}),
            3.68,
        )

        self.assertTrue(rows.empty)
        self.assertIn("No acceptable credit column", rows.attrs["unavailable_reason"])


if __name__ == "__main__":
    unittest.main()
