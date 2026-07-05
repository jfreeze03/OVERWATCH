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
        self.assertIn(".ow-cc-kpi-strip", css)
        self.assertIn(".ow-cc-kpi-card", css)
        self.assertIn(".ow-coco-ai-summary", css)
        self.assertIn(".ow-coco-score-section", css)
        self.assertIn(".ow-coco-kpi-row", css)
        self.assertIn(".ow-coco-chart-card", css)
        self.assertIn(".ow-coco-alert-shell", css)
        self.assertIn(".ow-cc-hero-card", css)
        self.assertIn(".ow-cc-attention-panel", css)
        self.assertIn(".ow-cc-health-panel", css)
        self.assertIn(".ow-cc-warehouse-panel", css)
        self.assertIn(".ow-cc-status-panel", css)
        self.assertIn(".ow-cc-context-panel", css)

    def test_executive_overview_routes_to_command_center_dashboard(self):
        shell = (APP_ROOT / "sections" / "executive_landing_shell.py").read_text(encoding="utf-8")
        view = (APP_ROOT / "sections" / "executive_command_center_view.py").read_text(encoding="utf-8")
        self.assertIn("render_executive_command_center_page", shell)
        self.assertIn("if active_workflow == EXECUTIVE_OVERVIEW_WORKFLOW:", shell)
        self.assertIn("return", shell.split("render_executive_command_center_page", 1)[1].split("render_section_command_brief", 1)[0])
        self.assertIn("render_coco_ai_summary", view)
        self.assertIn("render_coco_score_section", view)
        self.assertIn("render_coco_kpi_row", view)
        self.assertIn("render_coco_credit_consumption_panel", view)
        self.assertNotIn("render_command_center_kpi_strip(model)", view)
        self.assertNotIn("render_executive_hero_card(model)", view)
        self.assertIn("executive_landing_command_brief_refresh_packet", view)
        self.assertIn("executive_cc_load_snapshot", view)

    def test_coco_kpi_css_prevents_vertical_text_towers(self):
        css = theme._combined_theme_css("carbon")
        self.assertIn("grid-template-columns: repeat(4, minmax(160px, 1fr));", css)
        self.assertIn(".ow-coco-kpi-card strong", css)
        self.assertIn("white-space: nowrap;", css)
        self.assertIn("text-overflow: ellipsis;", css)
        self.assertNotIn(".ow-coco-kpi-row {\n    display: grid;\n    grid-template-columns: repeat(6, minmax(0, 1fr));", css)

    def test_alert_center_default_visual_contract_is_inbox_not_kanban(self):
        alert_source = (APP_ROOT / "sections" / "alert_center.py").read_text(encoding="utf-8")
        inbox_source = (APP_ROOT / "sections" / "alert_center_inbox_shell.py").read_text(encoding="utf-8")
        css = theme._combined_theme_css("carbon")
        self.assertIn("Alert Inbox", alert_source)
        self.assertIn("Alert Intelligence", inbox_source)
        self.assertIn("ow-coco-filter-chip", inbox_source)
        self.assertIn(".ow-coco-alert-shell", css)
        self.assertNotIn("lane-column", alert_source)

    def test_executive_command_center_snowflake_objects_are_deployable(self):
        setup = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8").upper()
        split_setup = (ROOT / "snowflake" / "mart_setup" / "04_mart_tables.sql").read_text(encoding="utf-8").upper()
        procedures = (ROOT / "snowflake" / "mart_setup" / "05_load_procedures.sql").read_text(encoding="utf-8").upper()
        validation = (ROOT / "snowflake" / "OVERWATCH_MART_VALIDATION.sql").read_text(encoding="utf-8").upper()
        drop = (ROOT / "snowflake" / "OVERWATCH_MART_DROP.sql").read_text(encoding="utf-8").upper()
        for token in [
            "MART_EXECUTIVE_COMMAND_CENTER_KPI",
            "MART_EXECUTIVE_COMMAND_CENTER_TIMESERIES",
            "MART_EXECUTIVE_COMMAND_CENTER_WAREHOUSE",
            "MART_EXECUTIVE_COMMAND_CENTER_ALERTS",
            "MART_EXECUTIVE_COMMAND_CENTER_CONTEXT",
            "SP_OVERWATCH_REFRESH_EXECUTIVE_COMMAND_CENTER",
            "OVERWATCH_EXECUTIVE_COMMAND_CENTER_REFRESH",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, setup)
                self.assertIn(token, split_setup + procedures)
                self.assertIn(token, validation)
                self.assertIn(token, drop)

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
