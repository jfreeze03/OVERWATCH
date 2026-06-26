from pathlib import Path
import sys
import unittest
from unittest.mock import patch

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
        self.assertEqual(theme._DEFAULT_THEME, "carbon")
        self.assertEqual(theme._normalize_theme_key(None), "carbon")

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
        self.assertNotIn("roll_tide", theme._THEME_ALIASES)
        self.assertNotIn("war_eagle", theme._THEME_ALIASES)
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
        executive_text = (APP_ROOT / "sections" / "executive_landing_charts.py").read_text(encoding="utf-8")

        self.assertTrue((APP_ROOT / "sections" / "executive_landing_shell.py").exists())
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
            '[data-testid="stMarkdownContainer"] .ow-section-subtitle',
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
        self.assertIn('min-width: min(340px, calc(100vw - 2rem))', theme._STRUCTURAL_CSS)
        self.assertIn('width: min(340px, calc(100vw - 2rem))', theme._STRUCTURAL_CSS)
        self.assertIn('[data-baseweb="popover"]:has([data-testid="stSelectboxVirtualDropdown"])', theme._STRUCTURAL_CSS)
        self.assertIn('[data-baseweb="popover"]:has([data-baseweb="calendar"]) [role="listbox"]', theme._STRUCTURAL_CSS)
        self.assertIn('[data-baseweb="popover"] [data-baseweb="menu"][role="listbox"]', theme._STRUCTURAL_CSS)
        self.assertIn('[data-baseweb="calendar"]', theme._STRUCTURAL_CSS)
        self.assertIn('[data-baseweb="calendar"] button', theme._STRUCTURAL_CSS)
        self.assertIn('[data-baseweb="calendar"] [role="gridcell"]:hover', theme._STRUCTURAL_CSS)
        calendar_css = theme._STRUCTURAL_CSS.split('[data-baseweb="calendar"]', 1)[1].split(".stNumberInput button", 1)[0]
        self.assertIn("background: var(--bg-card) !important", calendar_css)
        self.assertIn("color: var(--text-primary) !important", calendar_css)
        self.assertNotIn("background: #f6fbff !important", calendar_css)
        for theme_key in ("carbon", "terminal"):
            with self.subTest(theme=theme_key):
                extra = theme._THEME_EXTRAS[theme_key]
                self.assertIn('button[data-testid^="stBaseButton"]', extra)
                self.assertIn('[data-testid="stButton"] button', extra)

    def test_theme_keeps_shell_classes_without_global_button_blur(self):
        self.assertIn("--accent:", theme._VARS["carbon"])
        self.assertIn(".ow-topbar", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-section-title", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-section-subtitle", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-workflow-context", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-workflow-context-kicker", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-workflow-context-title", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-workflow-context-detail", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-command-deck", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-command-deck-kicker", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-command-deck-title", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-command-deck-primary", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-command-deck-boundary", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-command-action", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-command-action-label", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-command-action-detail", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-decision-brief", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-decision-operating-loop", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-decision-loop-header", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-decision-loop-headline", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-decision-loop-footer", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-decision-status", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-decision-metric-ribbon", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-decision-priority-list", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-decision-diagnostics-panel", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-decision-trust-detail", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-decision-source-row", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-decision-sparkline", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-executive-command-hero", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-executive-hero-kicker", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-executive-hero-title", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-executive-hero-detail", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-executive-hero-status", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-executive-hero-load-note", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-mission-control", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-mission-row", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-mission-severity", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-chart-empty", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-chart-empty-title", theme._STRUCTURAL_CSS)
        self.assertIn("line-height: 1.35", theme._STRUCTURAL_CSS)
        self.assertIn("max-width: min(880px, 100%)", theme._STRUCTURAL_CSS)
        self.assertIn('[data-testid="stMain"] [data-testid="stExpander"] details[open] > summary', theme._STRUCTURAL_CSS)
        self.assertIn('[data-testid="stMain"] [data-testid="stExpander"] summary:hover', theme._STRUCTURAL_CSS)
        self.assertIn("-webkit-text-fill-color: #ffffff", theme._STRUCTURAL_CSS)
        self.assertIn('[data-testid="stButton"] button:focus-visible', theme._STRUCTURAL_CSS)
        self.assertIn('[data-testid="stExpander"] summary:focus-visible', theme._STRUCTURAL_CSS)
        self.assertIn('[data-baseweb="select"] [role="combobox"]:focus-visible', theme._STRUCTURAL_CSS)
        self.assertIn('[data-baseweb="input"] input:focus-visible', theme._STRUCTURAL_CSS)
        self.assertIn("outline-offset: 2px", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-filter-strip-shell", theme._STRUCTURAL_CSS)
        self.assertIn('[data-testid="stExpander"].stExpander [data-testid="stExpander"].stExpander > details[open] > summary', theme._THEME_EXTRAS["carbon"])
        self.assertIn("background-color: rgba(9,23,32,0.98)", theme._THEME_EXTRAS["carbon"])
        button_css = theme._STRUCTURAL_CSS.split("/* Buttons */", 1)[1].split("/* Expanders */", 1)[0]
        self.assertNotIn("backdrop-filter", button_css)
        self.assertNotIn("backdrop-filter", theme._STRUCTURAL_CSS)

    def test_primary_dashboard_layout_uses_responsive_grids(self):
        self.assertIn(".ow-signal-grid", theme._STRUCTURAL_CSS)
        self.assertIn("repeat(auto-fit, minmax(175px, 1fr))", theme._STRUCTURAL_CSS)
        self.assertIn(".ow-chart-title", theme._STRUCTURAL_CSS)
        self.assertIn('[data-testid="stVegaLiteChart"]', theme._STRUCTURAL_CSS)

    def test_workflow_context_escapes_markup(self):
        from utils import workflows

        with patch.object(workflows.st, "html") as html:
            workflows._render_selector_context(
                label="<script>alert(1)</script>",
                selected="bad",
                labels={"bad": "<b>Selected</b>"},
                details={"bad": "<img src=x onerror=alert(1)>"},
            )

        markup = html.call_args.args[0]
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", markup)
        self.assertIn("&lt;b&gt;Selected&lt;/b&gt;", markup)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", markup)
        self.assertNotIn("<script>", markup)
        self.assertNotIn("<img src=x", markup)


if __name__ == "__main__":
    unittest.main()
