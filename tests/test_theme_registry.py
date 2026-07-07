from pathlib import Path
import sys
import unittest

import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

import theme  # noqa: E402
from brand import render_overwatch_logo_svg, render_sidebar_brand  # noqa: E402


class ThemeRegistryTests(unittest.TestCase):
    def test_only_carbon_theme_is_active(self):
        self.assertEqual(list(theme.THEMES.keys()), ["carbon"])
        self.assertEqual(theme.THEMES["carbon"]["label"], "Snowflake Dark")
        self.assertEqual(theme._DEFAULT_THEME, "carbon")
        self.assertEqual(list(theme._VARS.keys()), ["carbon"])
        self.assertEqual(list(theme._THEME_EXTRAS.keys()), ["carbon"])
        self.assertEqual(theme._normalize_theme_key(None), "carbon")
        self.assertEqual(theme._normalize_theme_key("anything_else"), "carbon")

    def test_removed_theme_names_and_picker_are_not_active_source(self):
        old_light_theme = "ter" + "minal"
        old_light_label = "Snowflake " + "White"
        old_widget_key = "theme_" + "picker"
        old_picker_function = "render_" + old_widget_key
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")
        layout_text = (APP_ROOT / "layout.py").read_text(encoding="utf-8")
        deployment_text = (APP_ROOT / "utils" / "deployment.py").read_text(encoding="utf-8")

        for source in (theme_text, layout_text, deployment_text):
            self.assertNotIn(old_light_theme, source)
            self.assertNotIn(old_light_label, source)
            self.assertNotIn(old_widget_key, source)
            self.assertNotIn(old_picker_function, source)

    def test_legacy_query_values_silently_resolve_to_carbon(self):
        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            old_value = "ter" + "minal"
            self.assertEqual(theme._normalize_theme_key(old_value), "carbon")
            st.session_state["active_theme"] = old_value
            self.assertEqual(theme._get_theme(), "carbon")
            self.assertEqual(st.session_state["active_theme"], "carbon")
            self.assertEqual(st.session_state["_overwatch_active_theme"], "carbon")
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_combined_css_pins_select_input_text_leak_fix(self):
        css = theme._combined_theme_css("carbon")
        self.assertIn('.stApp [data-baseweb="select"] input[role="combobox"]', css)
        select_input_block = css[
            css.index('.stApp [data-baseweb="select"] input[role="combobox"]'):
            css.index('[data-testid="stSelectboxVirtualDropdown"]')
        ]
        self.assertIn("color: transparent !important", select_input_block)
        self.assertIn("-webkit-text-fill-color: transparent !important", select_input_block)
        self.assertIn("caret-color: transparent !important", select_input_block)
        self.assertIn("opacity: 0 !important", select_input_block)
        self.assertIn("width: 0 !important", select_input_block)
        self.assertIn("min-width: 0 !important", select_input_block)
        self.assertIn("max-width: 0 !important", select_input_block)
        self.assertIn("input[role=\"combobox\"]::selection", css)
        self.assertIn("background: transparent !important", select_input_block)
        self.assertIn(".stApp [data-baseweb=\"select\"] span", css)
        self.assertIn("-webkit-text-fill-color: var(--text-input) !important", css)

    def test_carbon_theme_keeps_current_streamlit_shell_targets(self):
        css = theme._combined_theme_css("carbon")
        self.assertIn("color: var(--text-primary) !important;", css)
        self.assertIn('[data-testid="stMarkdownContainer"]', css)
        self.assertIn('[data-testid="stNumberInput"] button', css)
        self.assertIn('[data-testid="stSidebarContent"]', css)
        self.assertIn("button[data-testid^=\"stBaseButton\"]:disabled", css)
        self.assertIn('[data-testid="stSelectboxVirtualDropdown"]', css)
        self.assertIn('[role="option"]:hover', css)
        self.assertIn(".ow-topbar", css)
        self.assertIn(".ow-section-title", css)
        self.assertIn(".ow-decision-workspace-marker", css)
        self.assertIn(".ow-kit-command-brief", css)
        self.assertIn(".ow-kit-metric-row", css)
        self.assertIn(".ow-kit-action-panel", css)
        self.assertIn(".ow-filter-strip-shell", css)
        self.assertIn("button[data-testid^=\"stBaseButton\"]", css)
        self.assertIn('[data-baseweb="popover"]:has([data-testid="stSelectboxVirtualDropdown"])', css)

    def test_sidebar_brand_uses_svg_component_not_inline_layout_art(self):
        svg = render_overwatch_logo_svg(24)
        sidebar = render_sidebar_brand()
        layout_text = (APP_ROOT / "layout.py").read_text(encoding="utf-8")

        self.assertIn('role="img"', svg)
        self.assertIn("aria-label", svg)
        self.assertIn("<title>OVERWATCH</title>", svg)
        self.assertIn('viewBox="0 0 48 48"', svg)
        self.assertEqual(svg.count("<path"), 3)
        self.assertIn("ow-logo-prism", svg)
        self.assertIn("ow-logo-cut", svg)
        self.assertIn("ow-logo-core", svg)
        self.assertNotIn("LIVE", sidebar)
        self.assertIn("SNOWFLAKE MONITOR", sidebar)
        self.assertIn("render_sidebar_brand()", layout_text)
        self.assertNotIn("<svg", layout_text)


if __name__ == "__main__":
    unittest.main()
