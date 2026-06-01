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

    def test_theme_picker_uses_clean_current_names(self):
        labels = {key: value["label"] for key, value in theme.THEMES.items()}
        self.assertEqual(labels["midnight"], "Henson Basic")
        self.assertEqual(labels["corporate"], "ALFA")
        self.assertEqual(labels["terminal"], "Snowflake White")
        self.assertEqual(labels["black_ice"], "Black Ice")
        self.assertEqual(labels["carbon"], "Snowflake Dark")
        self.assertNotIn("aurora", theme.THEMES)
        self.assertNotIn("Aurora", labels.values())
        self.assertEqual(theme._normalize_theme_key("aurora"), "black_ice")

    def test_snowflake_themes_use_snowflake_blue(self):
        self.assertEqual(theme.THEMES["terminal"]["swatch"], "#29B5E8")
        self.assertEqual(theme.THEMES["carbon"]["swatch"], "#29B5E8")

    def test_black_ice_replaces_aurora_palette(self):
        self.assertEqual(theme.THEMES["black_ice"]["swatch"], "#a3e635")
        self.assertIn("#a3e635", theme._VARS["black_ice"])
        self.assertIn("#22d3ee", theme._VARS["black_ice"])

    def test_light_themes_pin_custom_shell_text_contrast(self):
        self.assertIn(
            '[data-testid="stMarkdownContainer"] .ow-section-title',
            theme._STRUCTURAL_CSS,
        )
        self.assertIn(
            '[data-testid="stMarkdownContainer"] .ow-empty-list span',
            theme._STRUCTURAL_CSS,
        )
        self.assertIn(
            '[data-testid="stSidebar"] .stButton > button[kind="primary"] p',
            theme._THEME_EXTRAS["corporate"],
        )
        self.assertIn(
            '[data-testid="stSidebar"] .stButton > button[kind="primary"] p',
            theme._THEME_EXTRAS["terminal"],
        )
        self.assertIn(
            '[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] .ow-brand-row',
            theme._STRUCTURAL_CSS,
        )
        self.assertIn(
            '[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] .ow-live-pill',
            theme._STRUCTURAL_CSS,
        )
        self.assertIn("color: #b00020 !important", theme._THEME_EXTRAS["corporate"])
        self.assertIn("color: #11567F !important", theme._THEME_EXTRAS["terminal"])


if __name__ == "__main__":
    unittest.main()
