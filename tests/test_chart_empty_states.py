from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


class ChartEmptyStateTests(unittest.TestCase):
    def test_time_series_chart_drops_infinite_values_before_altair(self):
        from utils import display

        frame = pd.DataFrame({
            "DAY": ["2026-06-24", "2026-06-25"],
            "VALUE": [float("inf"), "not numeric"],
        })
        with patch.object(display.st, "altair_chart") as altair_chart, patch.object(
            display,
            "render_chart_empty_state",
        ) as empty_state:
            plotted = display.render_time_series_chart(frame, "DAY", "VALUE", title="Bad trend")

        self.assertTrue(plotted.empty)
        altair_chart.assert_not_called()
        empty_state.assert_called_once()

    def test_ranked_bar_chart_drops_invalid_values_before_altair(self):
        from utils import display

        frame = pd.DataFrame({
            "WAREHOUSE_NAME": ["WH1", "WH2"],
            "CREDITS": [float("-inf"), "bad"],
        })
        with patch.object(display.st, "altair_chart") as altair_chart, patch.object(
            display,
            "render_chart_empty_state",
        ) as empty_state:
            plotted = display.render_ranked_bar_chart(
                frame,
                "WAREHOUSE_NAME",
                "CREDITS",
                title="Bad ranking",
            )

        self.assertTrue(plotted.empty)
        altair_chart.assert_not_called()
        empty_state.assert_called_once()

    def test_empty_state_markup_is_text_first(self):
        from sections import empty_states

        with patch.object(empty_states.st, "html") as html:
            empty_states.render_chart_empty_state("<b>Title</b>", "<script>alert(1)</script>")

        markup = html.call_args.args[0]
        self.assertIn("&lt;b&gt;Title&lt;/b&gt;", markup)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", markup)
        self.assertNotIn("<script>", markup)


if __name__ == "__main__":
    unittest.main()
