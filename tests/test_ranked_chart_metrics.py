from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
for path in (ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


class RankedChartMetricTests(unittest.TestCase):
    def test_ratio_metrics_recompute_after_stable_user_aggregation(self):
        from utils.display import rank_chart_frame

        frame = pd.DataFrame(
            [
                {
                    "USER_NAME": "JDOE",
                    "USER_CHART_LABEL": "Jane Doe",
                    "COST_USD": 5.0,
                    "TOTAL_CREDITS": 2.2727,
                    "TOTAL_TOKENS": 1000,
                    "TOTAL_REQUESTS": 2,
                    "TOKENS_PER_DOLLAR": 200.0,
                    "COST_PER_1K_TOKENS_USD": 5.0,
                    "TOKENS_PER_REQUEST": 500.0,
                },
                {
                    "USER_NAME": "JDOE",
                    "USER_CHART_LABEL": "Jane Doe",
                    "COST_USD": 7.0,
                    "TOTAL_CREDITS": 3.1818,
                    "TOTAL_TOKENS": 3000,
                    "TOTAL_REQUESTS": 4,
                    "TOKENS_PER_DOLLAR": 428.57,
                    "COST_PER_1K_TOKENS_USD": 2.333333,
                    "TOKENS_PER_REQUEST": 750.0,
                },
            ]
        )

        ranked = rank_chart_frame(
            frame,
            "USER_CHART_LABEL",
            "COST_USD",
            stable_key="USER_NAME",
            tooltip_columns=(
                "TOTAL_CREDITS",
                "TOTAL_TOKENS",
                "TOTAL_REQUESTS",
                "TOKENS_PER_DOLLAR",
                "COST_PER_1K_TOKENS_USD",
                "TOKENS_PER_REQUEST",
                "AI_CREDITS_PER_1K_TOKENS",
                "COST_PER_REQUEST_USD",
            ),
        )

        row = ranked.iloc[0]
        self.assertEqual(float(row["COST_USD"]), 12.0)
        self.assertEqual(int(row["TOTAL_TOKENS"]), 4000)
        self.assertEqual(int(row["TOTAL_REQUESTS"]), 6)
        self.assertAlmostEqual(float(row["TOKENS_PER_DOLLAR"]), 333.33, places=2)
        self.assertAlmostEqual(float(row["COST_PER_1K_TOKENS_USD"]), 3.0, places=4)
        self.assertAlmostEqual(float(row["TOKENS_PER_REQUEST"]), 666.67, places=2)
        self.assertAlmostEqual(float(row["AI_CREDITS_PER_1K_TOKENS"]), 1.363625, places=6)
        self.assertAlmostEqual(float(row["COST_PER_REQUEST_USD"]), 2.0, places=4)

    def test_duplicate_friendly_names_remain_separate_with_daily_safe_label(self):
        from utils.display import rank_chart_frame

        frame = pd.DataFrame(
            [
                {"USER_NAME": "JDOE", "USER_CHART_LABEL": "Jane Doe", "COST_USD": 5.0},
                {"USER_NAME": "JDOE2", "USER_CHART_LABEL": "Jane Doe", "COST_USD": 7.0},
            ]
        )

        ranked = rank_chart_frame(frame, "USER_CHART_LABEL", "COST_USD", stable_key="USER_NAME")

        self.assertEqual(len(ranked), 2)
        self.assertEqual(float(ranked["COST_USD"].sum()), 12.0)
        self.assertIn("Jane Doe · JDOE", set(ranked["USER_CHART_LABEL"]))
        self.assertIn("Jane Doe · JDOE2", set(ranked["USER_CHART_LABEL"]))

    def test_zero_denominator_ratio_is_unavailable_unless_confirmed_zero(self):
        from utils.display import rank_chart_frame

        frame = pd.DataFrame(
            [{"USER_NAME": "JDOE", "USER_CHART_LABEL": "Jane Doe", "COST_USD": 0, "TOTAL_TOKENS": 10}]
        )

        pending = rank_chart_frame(
            frame,
            "USER_CHART_LABEL",
            "TOTAL_TOKENS",
            stable_key="USER_NAME",
            tooltip_columns=("TOKENS_PER_DOLLAR",),
        )
        self.assertTrue(pd.isna(pending.loc[0, "TOKENS_PER_DOLLAR"]))

        confirmed_zero = rank_chart_frame(
            frame,
            "USER_CHART_LABEL",
            "TOTAL_TOKENS",
            stable_key="USER_NAME",
            tooltip_columns=("TOKENS_PER_DOLLAR",),
            source_confirmed_zero=True,
        )
        self.assertEqual(float(confirmed_zero.loc[0, "TOKENS_PER_DOLLAR"]), 0.0)


if __name__ == "__main__":
    unittest.main()
