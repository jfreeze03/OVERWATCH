from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

import theme  # noqa: E402


class ThemeRegistryTests(unittest.TestCase):
    def test_terminal_and_carbon_are_replaced_with_snowflake_themes(self):
        labels = {key: value["label"] for key, value in theme.THEMES.items()}
        self.assertEqual(labels["terminal"], "Snowflake White")
        self.assertEqual(labels["carbon"], "Snowflake Dark")
        self.assertNotIn("Terminal", labels.values())
        self.assertNotIn("Carbon", labels.values())

    def test_snowflake_themes_use_snowflake_blue(self):
        self.assertEqual(theme.THEMES["terminal"]["swatch"], "#29B5E8")
        self.assertEqual(theme.THEMES["carbon"]["swatch"], "#29B5E8")


if __name__ == "__main__":
    unittest.main()
