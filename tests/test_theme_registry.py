from pathlib import Path
import sys
import unittest

import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

import theme  # noqa: E402


class ThemeRegistryTests(unittest.TestCase):
    def test_theme_picker_order_and_default(self):
        self.assertEqual(
            list(theme.THEMES.keys()),
            ["carbon", "terminal"],
        )
        labels = [value["label"] for value in theme.THEMES.values()]
        self.assertEqual(
            labels,
            ["Snowflake Dark", "Snowflake White"],
        )
        self.assertEqual(theme._DEFAULT_THEME, "terminal")
        self.assertEqual(theme._normalize_theme_key(None), "terminal")

    def test_removed_and_nonproduction_themes_alias_to_snowflake_dark(self):
        labels = {key: value["label"] for key, value in theme.THEMES.items()}
        self.assertNotIn("midnight", theme.THEMES)
        self.assertNotIn("black_ice", theme.THEMES)
        self.assertNotIn("roll_tide", theme.THEMES)
        self.assertNotIn("war_eagle", theme.THEMES)
        self.assertNotIn("corporate", theme.THEMES)
        self.assertNotIn("Graphite Ember", labels.values())
        self.assertNotIn("Midnight", labels.values())
        self.assertNotIn("Roll Tide", labels.values())
        self.assertNotIn("War Eagle", labels.values())
        self.assertNotIn("Henson", labels.values())
        self.assertNotIn("roll_tide", theme._VARS)
        self.assertNotIn("war_eagle", theme._VARS)
        self.assertNotIn("corporate", theme._VARS)
        self.assertNotIn("roll_tide", theme._THEME_EXTRAS)
        self.assertNotIn("war_eagle", theme._THEME_EXTRAS)
        self.assertNotIn("corporate", theme._THEME_EXTRAS)
        cost_contract_text = (APP_ROOT / "sections" / "cost_contract.py").read_text(encoding="utf-8")
        self.assertNotIn('"roll_tide"', cost_contract_text)
        self.assertNotIn('"war_eagle"', cost_contract_text)
        self.assertEqual(theme._normalize_theme_key("aurora"), "carbon")
        self.assertEqual(theme._normalize_theme_key("black_ice"), "carbon")
        self.assertEqual(theme._normalize_theme_key("midnight"), "carbon")
        self.assertEqual(theme._normalize_theme_key("roll_tide"), "carbon")
        self.assertEqual(theme._normalize_theme_key("war_eagle"), "carbon")
        self.assertEqual(theme._normalize_theme_key("corporate"), "carbon")
        self.assertEqual(theme._normalize_theme_key("henson"), "carbon")

    def test_theme_picker_uses_dropdown_not_radio(self):
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")
        self.assertIn("st.selectbox(", theme_text)
        self.assertIn("def _commit_theme_picker_change", theme_text)
        self.assertIn("on_change=_commit_theme_picker_change", theme_text)
        self.assertNotIn("selected = st.radio(", theme_text)
        self.assertIn('key="theme_picker_radio"', theme_text)
        self.assertIn('_THEME_QUERY_PARAM = "overwatch_theme"', theme_text)
        self.assertIn("def _set_query_param_theme", theme_text)
        self.assertIn("_set_query_param_theme(selected)", theme_text)
        self.assertIn("st.experimental_get_query_params()", theme_text)
        self.assertIn("st.experimental_set_query_params(**query_params)", theme_text)
        self.assertIn('st.session_state.get("theme_picker_radio") != current', theme_text)

    def test_theme_version_change_preserves_dark_selection(self):
        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["active_theme"] = "carbon"
            st.session_state["theme_picker_radio"] = "carbon"
            st.session_state["_active_theme_version"] = "old-version"
            self.assertEqual(theme._get_theme(), "carbon")
            self.assertEqual(st.session_state["active_theme"], "carbon")
            self.assertEqual(st.session_state["_overwatch_active_theme"], "carbon")
            self.assertEqual(st.session_state["theme_picker_radio"], "carbon")
            self.assertEqual(st.session_state["_active_theme_version"], theme.THEME_VERSION)
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_settings_widget_cannot_reset_persistent_dark_theme(self):
        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["_overwatch_active_theme"] = "carbon"
            st.session_state["theme_picker_radio"] = "terminal"
            self.assertEqual(theme._get_theme(), "carbon")
            self.assertEqual(st.session_state["active_theme"], "carbon")
            self.assertEqual(st.session_state["_overwatch_active_theme"], "carbon")
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_snowflake_themes_use_snowflake_blue(self):
        self.assertEqual(theme.THEMES["terminal"]["swatch"], "#29B5E8")
        self.assertEqual(theme.THEMES["carbon"]["swatch"], "#29B5E8")
        self.assertIn("--bg-app:          #f6fbff;", theme._VARS["terminal"])
        self.assertIn("--bg-sidebar:      #ffffff;", theme._VARS["terminal"])
        self.assertIn("--text-primary:    #102a43;", theme._VARS["terminal"])
        self.assertIn("--text-primary:    #eef8fb;", theme._VARS["carbon"])

    def test_base_theme_pins_dark_safe_text_and_number_controls(self):
        self.assertIn("color: var(--text-primary) !important;", theme._STRUCTURAL_CSS)
        self.assertIn("p, li { color: var(--text-primary) !important;", theme._STRUCTURAL_CSS)
        self.assertIn('[data-testid="stMarkdownContainer"]', theme._STRUCTURAL_CSS)
        self.assertIn('[data-testid="stNumberInput"] button', theme._STRUCTURAL_CSS)
        self.assertIn("-webkit-text-fill-color: var(--text-input) !important", theme._STRUCTURAL_CSS)
        self.assertIn('[data-testid="stSidebarContent"]', theme._STRUCTURAL_CSS)
        self.assertIn("button[data-testid^=\"stBaseButton\"]:disabled", theme._STRUCTURAL_CSS)
        self.assertIn("color: var(--text-muted) !important;", theme._STRUCTURAL_CSS)
        self.assertIn('[data-testid="stSelectboxVirtualDropdown"]', theme._STRUCTURAL_CSS)
        self.assertIn('[role="option"]:hover', theme._STRUCTURAL_CSS)
        self.assertIn("background: rgba(var(--accent-rgb), 0.16) !important", theme._STRUCTURAL_CSS)

    def test_dark_theme_keeps_inactive_sidebar_buttons_subtle(self):
        carbon_extra = theme._THEME_EXTRAS["carbon"]
        self.assertIn('.stApp button[data-testid="stBaseButton-primary"]', carbon_extra)
        self.assertIn("background: linear-gradient(135deg, #0068b7, #003545) !important", carbon_extra)
        self.assertIn("background: linear-gradient(135deg, #0079d6, #004568) !important", carbon_extra)
        self.assertIn("-webkit-text-fill-color: #ffffff !important", carbon_extra)
        self.assertIn(
            "background: linear-gradient(135deg, rgba(41,181,232,0.10), rgba(113,211,220,0.06)) !important",
            carbon_extra,
        )
        self.assertIn("box-shadow: none !important", carbon_extra)
        self.assertIn("background: linear-gradient(135deg, #003f73, #0068b7) !important", carbon_extra)

    def test_executive_landing_charts_use_shared_theme_surface(self):
        executive_text = (APP_ROOT / "sections" / "executive_landing.py").read_text(encoding="utf-8")

        self.assertFalse((APP_ROOT / "sections" / "executive_landing_shell.py").exists())
        self.assertIn("def _render_line_chart", executive_text)
        self.assertIn("def _render_bar_chart", executive_text)
        self.assertIn('alt.value("#29B5E8")', executive_text)
        self.assertIn('st.altair_chart(chart, width="stretch")', executive_text)
        self.assertIn(".vega-embed svg text", theme._STRUCTURAL_CSS)
        self.assertIn("fill: var(--text-secondary) !important;", theme._STRUCTURAL_CSS)

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
        self.assertIn("background: linear-gradient(135deg, #ffffff, #eaf6fb) !important", theme._THEME_EXTRAS["terminal"])
        self.assertIn('[data-testid="stButton"] button', theme._THEME_EXTRAS["terminal"])
        self.assertIn('button[data-testid^="stBaseButton"]', theme._THEME_EXTRAS["terminal"])
        self.assertIn('[data-testid="stSidebar"] [data-testid="stExpander"] summary', theme._THEME_EXTRAS["terminal"])
        self.assertIn("background: linear-gradient(135deg, #0068b7, #00528f) !important", theme._THEME_EXTRAS["terminal"])
        self.assertIn("color: #ffffff !important", theme._THEME_EXTRAS["terminal"])
        self.assertIn('[data-testid="stExpander"] summary', theme._THEME_EXTRAS["terminal"])
        self.assertIn("color: #102a43 !important", theme._THEME_EXTRAS["terminal"])
        light_theme_text = {
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
        }
        for theme_key, gradient in expected_gradients.items():
            with self.subTest(theme=theme_key):
                extra = theme._THEME_EXTRAS[theme_key]
                self.assertIn('[data-testid="stSidebar"] .stButton > button', extra)
                self.assertIn('[data-testid="stSidebar"] [data-testid="stExpander"] summary', extra)
                self.assertIn(".stTabs [aria-selected=\"true\"]", extra)
                self.assertIn(gradient, extra)
                self.assertIn("color: #ffffff !important", extra)

    def test_theme_targets_current_streamlit_button_dom(self):
        self.assertIn('button[data-testid^="stBaseButton"]', theme._STRUCTURAL_CSS)
        self.assertIn('[data-testid="stButton"] button', theme._STRUCTURAL_CSS)
        self.assertIn('[data-baseweb="input"]', theme._STRUCTURAL_CSS)
        self.assertIn('[data-baseweb="base-input"]', theme._STRUCTURAL_CSS)
        self.assertIn('[data-baseweb="select"] > div', theme._STRUCTURAL_CSS)
        for theme_key in ("carbon", "terminal"):
            with self.subTest(theme=theme_key):
                extra = theme._THEME_EXTRAS[theme_key]
                self.assertIn('button[data-testid^="stBaseButton"]', extra)
                self.assertIn('[data-testid="stButton"] button', extra)

    def test_primary_dashboard_layout_uses_responsive_grids(self):
        self.assertIn(".ow-signal-grid", theme._STRUCTURAL_CSS)
        self.assertIn("repeat(auto-fit, minmax(175px, 1fr))", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-chart-title", theme._STRUCTURAL_CSS)
        self.assertIn('[data-testid="stVegaLiteChart"]', theme._STRUCTURAL_CSS)


if __name__ == "__main__":
    unittest.main()
