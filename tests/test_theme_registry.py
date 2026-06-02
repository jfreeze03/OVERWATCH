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
        self.assertEqual(labels["midnight"], "Midnight")
        self.assertEqual(labels["corporate"], "Henson")
        self.assertEqual(labels["terminal"], "Snowflake White")
        self.assertEqual(labels["black_ice"], "Graphite Ember")
        self.assertEqual(labels["carbon"], "Snowflake Dark")
        self.assertNotIn("aurora", theme.THEMES)
        self.assertNotIn("Aurora", labels.values())
        self.assertNotIn("Black Ice", labels.values())
        self.assertEqual(theme._normalize_theme_key("aurora"), "black_ice")

    def test_snowflake_themes_use_snowflake_blue(self):
        self.assertEqual(theme.THEMES["terminal"]["swatch"], "#29B5E8")
        self.assertEqual(theme.THEMES["carbon"]["swatch"], "#29B5E8")

    def test_graphite_ember_is_visually_distinct_from_snowflake_dark(self):
        self.assertEqual(theme.THEMES["black_ice"]["swatch"], "#f97316")
        self.assertIn("#f97316", theme._VARS["black_ice"])
        self.assertIn("#14b8a6", theme._VARS["black_ice"])
        self.assertNotIn("#29B5E8", theme._VARS["black_ice"])

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
        self.assertIn("background: linear-gradient(135deg, #7f0017, #b00020) !important", theme._THEME_EXTRAS["corporate"])
        self.assertIn("background: linear-gradient(135deg, #003f73, #0068b7) !important", theme._THEME_EXTRAS["terminal"])
        self.assertIn('[data-testid="stSidebar"] [data-testid="stExpander"] summary', theme._THEME_EXTRAS["corporate"])
        self.assertIn('[data-testid="stSidebar"] [data-testid="stExpander"] summary', theme._THEME_EXTRAS["terminal"])
        self.assertIn("background: linear-gradient(135deg, #b00020, #8f001a) !important", theme._THEME_EXTRAS["corporate"])
        self.assertIn("background: linear-gradient(135deg, #0068b7, #00528f) !important", theme._THEME_EXTRAS["terminal"])
        self.assertIn("color: #ffffff !important", theme._THEME_EXTRAS["corporate"])
        self.assertIn("color: #ffffff !important", theme._THEME_EXTRAS["terminal"])
        self.assertIn('[data-testid="stExpander"] summary', theme._THEME_EXTRAS["corporate"])
        self.assertIn('[data-testid="stExpander"] summary', theme._THEME_EXTRAS["terminal"])
        self.assertIn("color: #102a43 !important", theme._THEME_EXTRAS["terminal"])


if __name__ == "__main__":
    unittest.main()
