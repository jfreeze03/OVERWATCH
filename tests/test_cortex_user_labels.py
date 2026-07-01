from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
for path in (ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


class CortexUserLabelTests(unittest.TestCase):
    def test_cortex_monitor_uses_chart_label_not_user_id_for_user_chart(self):
        source = (ROOT / ".overwatch_final" / "sections" / "cortex_monitor.py").read_text(
            encoding="utf-8"
        )

        self.assertRegex(source, r"render_ranked_bar_chart\(\s*user_agg,\s*\"USER_CHART_LABEL\"")
        self.assertIn("USER_DISPLAY_NAME", source)
        self.assertIn("USER_ADMIN_LABEL", source)

    def test_grouping_keeps_stable_user_name_to_avoid_merging_duplicate_display_names(self):
        source = (ROOT / ".overwatch_final" / "sections" / "cortex_monitor.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('groupby(["USER_NAME", "USER_DISPLAY_NAME", "USER_CHART_LABEL"]', source)

    def test_cortex_user_chart_carries_tokens_and_efficiency_metrics(self):
        source = (ROOT / ".overwatch_final" / "sections" / "cortex_monitor.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('TOTAL_TOKENS=("TOTAL_TOKENS", "sum")', source)
        self.assertIn("tooltip_columns=(", source)
        self.assertIn('stable_key="USER_NAME"', source)
        self.assertIn('"TOTAL_TOKENS"', source)
        self.assertIn('"TOKENS_PER_DOLLAR"', source)
        self.assertIn('"COST_PER_1K_TOKENS_USD"', source)
        self.assertIn('"AI_CREDITS_PER_1K_TOKENS"', source)
        self.assertIn('"Load Cortex Efficiency"', source)

    def test_ranked_chart_frame_preserves_opt_in_tooltip_metrics(self):
        from utils.display import rank_chart_frame

        frame = pd.DataFrame(
            [
                {
                    "USER_CHART_LABEL": "Jane Doe",
                    "COST_USD": 5.0,
                    "TOTAL_TOKENS": 1000,
                    "TOTAL_REQUESTS": 2,
                },
                {
                    "USER_CHART_LABEL": "Jane Doe",
                    "COST_USD": 7.0,
                    "TOTAL_TOKENS": 3000,
                    "TOTAL_REQUESTS": 4,
                },
            ]
        )

        ranked = rank_chart_frame(
            frame,
            "USER_CHART_LABEL",
            "COST_USD",
            tooltip_columns=("TOTAL_TOKENS", "TOTAL_REQUESTS"),
        )

        self.assertEqual(float(ranked.loc[0, "COST_USD"]), 12.0)
        self.assertEqual(int(ranked.loc[0, "TOTAL_TOKENS"]), 4000)
        self.assertEqual(int(ranked.loc[0, "TOTAL_REQUESTS"]), 6)

    def test_cortex_efficiency_helper_uses_ai_credit_cost_and_not_compute_rate(self):
        from sections.cortex_monitor import _add_cortex_token_efficiency_columns

        frame = pd.DataFrame(
            [
                {
                    "TOTAL_CREDITS": 10,
                    "COST_USD": 22,
                    "TOTAL_TOKENS": 2000,
                    "TOTAL_REQUESTS": 4,
                }
            ]
        )

        enriched = _add_cortex_token_efficiency_columns(frame)

        self.assertEqual(float(enriched.loc[0, "TOKENS_PER_DOLLAR"]), 90.91)
        self.assertEqual(float(enriched.loc[0, "COST_PER_1K_TOKENS_USD"]), 11.0)
        self.assertEqual(float(enriched.loc[0, "AI_CREDITS_PER_1K_TOKENS"]), 5.0)
        self.assertEqual(float(enriched.loc[0, "TOKENS_PER_REQUEST"]), 500.0)

    def test_helper_builds_friendly_chart_label(self):
        from utils.user_display import apply_user_display_columns

        frame = pd.DataFrame(
            [
                {
                    "USER_ID": "55555",
                    "USER_NAME": "JDOE",
                    "FIRST_NAME": "Jane",
                    "LAST_NAME": "Doe",
                    "COST_USD": 10.0,
                }
            ]
        )

        labeled = apply_user_display_columns(frame)

        self.assertEqual(labeled.loc[0, "USER_CHART_LABEL"], "Jane Doe")
        self.assertNotEqual(labeled.loc[0, "USER_CHART_LABEL"], labeled.loc[0, "USER_ID"])

    def test_helper_never_uses_user_id_only_for_chart_label(self):
        from utils.user_display import apply_user_display_columns

        frame = pd.DataFrame([{"USER_ID": "55555", "USER_NAME": "55555", "COST_USD": 10.0}])

        labeled = apply_user_display_columns(frame)

        self.assertEqual(labeled.loc[0, "USER_CHART_LABEL"], "Unknown user")
        self.assertEqual(labeled.loc[0, "USER_DISPLAY_NAME"], "Unknown user")

    def test_cortex_sql_daily_label_fallbacks_do_not_use_user_id(self):
        source = (ROOT / ".overwatch_final" / "sections" / "cortex_monitor.py").read_text(
            encoding="utf-8"
        )
        cost_sql = (ROOT / ".overwatch_final" / "sections" / "cost_contract_sql.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn('_snowflake_user_chart_expr("u", "TO_VARCHAR(c.USER_ID)")', source)
        self.assertNotIn('_snowflake_user_chart_expr("u", "TO_VARCHAR(r.USER_ID)")', source)
        self.assertNotIn('_snowflake_user_chart_expr("u", "TO_VARCHAR(s.USER_ID)")', source)
        self.assertNotIn('_snowflake_user_chart_expr("u", "TO_VARCHAR(c.USER_ID)")', cost_sql)
        self.assertIn("sanitize_user_columns_for_export(df_cc)", source)


if __name__ == "__main__":
    unittest.main()
