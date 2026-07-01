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

        self.assertIn('render_ranked_bar_chart(user_agg, "USER_CHART_LABEL"', source)
        self.assertIn("USER_DISPLAY_NAME", source)
        self.assertIn("USER_ADMIN_LABEL", source)

    def test_grouping_keeps_stable_user_name_to_avoid_merging_duplicate_display_names(self):
        source = (ROOT / ".overwatch_final" / "sections" / "cortex_monitor.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('groupby(["USER_NAME", "USER_DISPLAY_NAME", "USER_CHART_LABEL"]', source)

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


if __name__ == "__main__":
    unittest.main()
