from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

import config  # noqa: E402
import theme  # noqa: E402
from sections.decision_workspace_components import render_section_header  # noqa: E402


class CommandCenterVisualRedesignTests(unittest.TestCase):
    def test_cost_intelligence_is_display_only_alias(self):
        self.assertEqual(config.normalize_section_name("Cost Intelligence"), "Cost & Contract")
        self.assertEqual(config.display_section_label("Cost & Contract"), "Cost Intelligence")
        self.assertIn("Cost & Contract", config.PRIMARY_SECTIONS)
        self.assertNotIn("Cost Intelligence", config.PRIMARY_SECTIONS)

    def test_sidebar_uses_display_label_without_renaming_route_key(self):
        layout_text = (APP_ROOT / "layout.py").read_text(encoding="utf-8")
        self.assertIn("display_section_label(section_name)", layout_text)
        self.assertIn("args=(section_name,)", layout_text)
        self.assertIn("Cost & Contract", config.NAV_GROUPS["FINANCIAL CONTROL"])

    def test_command_brief_header_shows_cost_intelligence(self):
        html = render_section_header("Cost & Contract", "Cost Overview")
        self.assertIn("Cost Intelligence", html)
        self.assertNotIn("<h1>Cost &amp; Contract</h1>", html)

    def test_command_center_css_tokens_and_surfaces_exist(self):
        css = theme._combined_theme_css("carbon")
        self.assertIn("Command-center release skin", css)
        self.assertIn("--ow-cyan: #29b5e8;", css)
        self.assertIn("--ow-green: #47d487;", css)
        self.assertIn("backdrop-filter: blur(15px) saturate(140%);", css)
        self.assertIn(".ow-global-command-bar + div", css)
        self.assertIn(".ow-kit-command-brief", css)
        self.assertIn(".ow-kit-metric-card", css)
        self.assertIn(".ow-kit-signal-panel", css)
        self.assertIn(".ow-kit-data-trust", css)

    def test_selectbox_internal_combobox_input_does_not_paint_focus_leak(self):
        css = theme._combined_theme_css("carbon")
        self.assertIn('[data-testid="stSelectbox"] [data-baseweb="select"] input[role="combobox"]', css)
        self.assertIn("caret-color: transparent !important", css)
        self.assertIn("color: transparent !important", css)
        self.assertIn("-webkit-text-fill-color: transparent !important", css)
        self.assertIn("opacity: 0 !important", css)
        self.assertIn("width: 0 !important", css)
        self.assertIn("max-width: 0 !important", css)

    def test_existing_filter_labels_are_preserved(self):
        filters_text = (APP_ROOT / "filters.py").read_text(encoding="utf-8")
        self.assertIn('"Company"', filters_text)
        self.assertIn('label="Window"', filters_text)
        self.assertIn("render_global_environment_control", filters_text)
        self.assertIn("render_global_warehouse_control", filters_text)
        self.assertIn('"User contains"', filters_text)
        self.assertIn('"Role contains"', filters_text)
        self.assertIn('"Database"', filters_text)
        self.assertIn('"Schema"', filters_text)


if __name__ == "__main__":
    unittest.main()
