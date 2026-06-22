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

    def test_cost_chart_palette_returns_carbon_fallback_and_terminal_palette(self):
        from sections import cost_contract_charts

        with patch.object(cost_contract_charts.st, "session_state", {}):
            carbon = cost_contract_charts._cost_chart_palette()
        self.assertEqual(carbon["bar"], "#29B5E8")
        self.assertEqual(carbon["text"], "#eef8fb")

        with patch.object(cost_contract_charts.st, "session_state", {"active_theme": "terminal"}):
            terminal = cost_contract_charts._cost_chart_palette()
        self.assertEqual(terminal["bar"], "#0068B7")
        self.assertEqual(terminal["text"], "#102a43")

        with patch.object(cost_contract_charts.st, "session_state", {"active_theme": "unknown"}):
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

    def test_cost_charts_keep_altair_lazy(self):
        chart_text = (APP_ROOT / "sections" / "cost_contract_charts.py").read_text(encoding="utf-8")

        self.assertNotIn("\nimport altair as alt", chart_text.split("def _altair", 1)[0])
        self.assertIn("def _altair", chart_text)
        self.assertIn("alt = _altair()", chart_text)


if __name__ == "__main__":
    unittest.main()
