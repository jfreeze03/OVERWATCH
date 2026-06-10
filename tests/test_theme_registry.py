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
            ["carbon", "terminal", "corporate"],
        )
        labels = [value["label"] for value in theme.THEMES.values()]
        self.assertEqual(
            labels,
            ["Snowflake Dark", "Snowflake White", "Henson"],
        )
        self.assertEqual(theme._DEFAULT_THEME, "carbon")
        self.assertEqual(theme._normalize_theme_key(None), "carbon")

    def test_removed_and_nonproduction_themes_alias_to_snowflake_dark(self):
        labels = {key: value["label"] for key, value in theme.THEMES.items()}
        self.assertNotIn("midnight", theme.THEMES)
        self.assertNotIn("black_ice", theme.THEMES)
        self.assertNotIn("roll_tide", theme.THEMES)
        self.assertNotIn("war_eagle", theme.THEMES)
        self.assertNotIn("Graphite Ember", labels.values())
        self.assertNotIn("Midnight", labels.values())
        self.assertNotIn("Roll Tide", labels.values())
        self.assertNotIn("War Eagle", labels.values())
        self.assertNotIn("roll_tide", theme._VARS)
        self.assertNotIn("war_eagle", theme._VARS)
        self.assertNotIn("roll_tide", theme._THEME_EXTRAS)
        self.assertNotIn("war_eagle", theme._THEME_EXTRAS)
        cost_contract_text = (APP_ROOT / "sections" / "cost_contract.py").read_text(encoding="utf-8")
        self.assertNotIn('"roll_tide"', cost_contract_text)
        self.assertNotIn('"war_eagle"', cost_contract_text)
        self.assertEqual(theme._normalize_theme_key("aurora"), "carbon")
        self.assertEqual(theme._normalize_theme_key("black_ice"), "carbon")
        self.assertEqual(theme._normalize_theme_key("midnight"), "carbon")
        self.assertEqual(theme._normalize_theme_key("roll_tide"), "carbon")
        self.assertEqual(theme._normalize_theme_key("war_eagle"), "carbon")

    def test_theme_picker_uses_dropdown_not_radio(self):
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")
        self.assertIn("selected = st.selectbox(", theme_text)
        self.assertNotIn("selected = st.radio(", theme_text)
        self.assertIn('key="theme_picker_radio"', theme_text)

    def test_snowflake_themes_use_snowflake_blue(self):
        self.assertEqual(theme.THEMES["terminal"]["swatch"], "#29B5E8")
        self.assertEqual(theme.THEMES["carbon"]["swatch"], "#29B5E8")

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
        light_theme_text = {
            "corporate": ("#151f2c", "#64748b"),
            "terminal": ("#102a43", "#526b7a"),
        }
        for theme_key, (body_color, caption_color) in light_theme_text.items():
            with self.subTest(theme=theme_key):
                extra = theme._THEME_EXTRAS[theme_key]
                self.assertIn('.stMain [data-testid="stMarkdownContainer"] p', extra)
                self.assertIn('.stMain [data-testid="stCaptionContainer"]', extra)
                self.assertIn(f"color: {body_color} !important", extra)
                self.assertIn(f"color: {caption_color} !important", extra)

    def test_all_themes_pin_sidebar_navigation_to_theme_color(self):
        expected_gradients = {
            "carbon": "background: linear-gradient(135deg, #0068b7, #003545) !important",
            "terminal": "background: linear-gradient(135deg, #0068b7, #00528f) !important",
            "corporate": "background: linear-gradient(135deg, #b00020, #8f001a) !important",
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
