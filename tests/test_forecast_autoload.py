from __future__ import annotations

from pathlib import Path
import inspect
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from sections import cost_center_forecast_view as forecast_view  # noqa: E402
from sections.cost_center_models import _cost_forecast_projection  # noqa: E402


class ForecastAutoloadTests(unittest.TestCase):
    def test_forecast_renderer_autoloads_without_generate_button(self) -> None:
        source = inspect.getsource(forecast_view.render_cost_forecast)

        self.assertIn("load_shared_warehouse_daily_credits(", source)
        self.assertNotIn("Generate Run-Rate Projection", source)
        self.assertNotIn("Load Annual Service Projection", source)
        self.assertIn("_cost_forecast_projection(", source)

    def test_forecast_output_includes_method_confidence_bounds_and_history(self) -> None:
        source = inspect.getsource(forecast_view.render_cost_forecast)

        for label in (
            "Method",
            "Confidence",
            "Lower Bound",
            "Upper Bound",
            "History Window",
            "Source Freshness",
            "Projected Period-End Cost",
        ):
            with self.subTest(label=label):
                self.assertIn(label, source)

    def test_deterministic_fallback_is_not_simple_avg_daily_times_30(self) -> None:
        rows = pd.DataFrame(
            {
                "DAY": pd.date_range("2026-06-01", periods=21, freq="D"),
                "DAILY_CREDITS": [10, 12, 9, 15, 20, 8, 7, 11, 13, 9, 18, 21, 8, 6, 12, 14, 10, 16, 24, 9, 7],
            }
        )

        summary, forecast_frame = _cost_forecast_projection(rows, credit_price=4.0, today="2026-06-21")

        simple_run_rate = float(rows["DAILY_CREDITS"].mean()) * 30
        self.assertEqual(summary["method_label"], "Seasonal fallback")
        self.assertIn(summary["confidence_label"], {"High", "Medium", "Low", "Directional"})
        self.assertGreater(summary["upper_bound_credits"], summary["lower_bound_credits"])
        self.assertNotAlmostEqual(summary["projected_end_period_credits"], simple_run_rate)
        self.assertTrue({"ACTUAL_CREDITS", "FORECAST_CREDITS", "BUDGET_CREDITS"}.issubset(forecast_frame.columns))


if __name__ == "__main__":
    unittest.main()
