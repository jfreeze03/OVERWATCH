from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

import theme  # noqa: E402


class ThemeRegistryTests(unittest.TestCase):
    def test_theme_picker_order_and_default(self):
        self.assertEqual(
            list(theme.THEMES.keys()),
            ["carbon", "terminal", "corporate", "roll_tide", "war_eagle"],
        )
        labels = [value["label"] for value in theme.THEMES.values()]
        self.assertEqual(
            labels,
            ["Snowflake Dark", "Snowflake White", "Henson", "Roll Tide", "War Eagle"],
        )
        self.assertEqual(theme._DEFAULT_THEME, "carbon")
        self.assertEqual(theme._normalize_theme_key(None), "carbon")

    def test_removed_themes_alias_to_snowflake_dark(self):
        labels = {key: value["label"] for key, value in theme.THEMES.items()}
        self.assertNotIn("midnight", theme.THEMES)
        self.assertNotIn("black_ice", theme.THEMES)
        self.assertNotIn("Graphite Ember", labels.values())
        self.assertNotIn("Midnight", labels.values())
        self.assertEqual(theme._normalize_theme_key("aurora"), "carbon")
        self.assertEqual(theme._normalize_theme_key("black_ice"), "carbon")
        self.assertEqual(theme._normalize_theme_key("midnight"), "carbon")

    def test_snowflake_themes_use_snowflake_blue(self):
        self.assertEqual(theme.THEMES["terminal"]["swatch"], "#29B5E8")
        self.assertEqual(theme.THEMES["carbon"]["swatch"], "#29B5E8")

    def test_roll_tide_and_war_eagle_palettes_are_distinct(self):
        self.assertEqual(theme.THEMES["roll_tide"]["swatch"], "#981D32")
        self.assertEqual(theme.THEMES["war_eagle"]["swatch"], "#DD550C")
        self.assertIn("#981D32", theme._VARS["roll_tide"])
        self.assertIn("#DD550C", theme._VARS["war_eagle"])
        self.assertIn("#0C213E", theme._VARS["war_eagle"])
        self.assertIn("background: linear-gradient(135deg, #981D32, #6f1626) !important", theme._THEME_EXTRAS["roll_tide"])
        self.assertIn("background: linear-gradient(135deg, #DD550C, #0C213E) !important", theme._THEME_EXTRAS["war_eagle"])

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

    def test_all_themes_pin_sidebar_navigation_to_theme_color(self):
        expected_gradients = {
            "carbon": "background: linear-gradient(135deg, #0068b7, #003545) !important",
            "terminal": "background: linear-gradient(135deg, #0068b7, #00528f) !important",
            "corporate": "background: linear-gradient(135deg, #b00020, #8f001a) !important",
            "roll_tide": "background: linear-gradient(135deg, #981D32, #6f1626) !important",
            "war_eagle": "background: linear-gradient(135deg, #DD550C, #0C213E) !important",
        }
        for theme_key, gradient in expected_gradients.items():
            with self.subTest(theme=theme_key):
                extra = theme._THEME_EXTRAS[theme_key]
                self.assertIn('[data-testid="stSidebar"] .stButton > button', extra)
                self.assertIn('[data-testid="stSidebar"] [data-testid="stExpander"] summary', extra)
                self.assertIn(".stTabs [aria-selected=\"true\"]", extra)
                self.assertIn(gradient, extra)
                self.assertIn("color: #ffffff !important", extra)


if __name__ == "__main__":
    unittest.main()
