from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


class CostContractSplitTests(unittest.TestCase):
    def test_cost_contract_reexports_moved_contracts(self):
        from sections import cost_contract
        from sections import cost_contract_contracts

        self.assertIs(cost_contract.build_cost_monitoring_mart_sql, cost_contract_contracts.build_cost_monitoring_mart_sql)
        self.assertIs(cost_contract.WORKFLOWS, cost_contract_contracts.WORKFLOWS)
        self.assertIs(cost_contract.WORKFLOW_DETAILS, cost_contract_contracts.WORKFLOW_DETAILS)
        self.assertIs(cost_contract.WORKFLOW_MODULES, cost_contract_contracts.WORKFLOW_MODULES)
        self.assertIs(cost_contract.LEGACY_COST_WORKFLOW_ALIASES, cost_contract_contracts.LEGACY_COST_WORKFLOW_ALIASES)
        self.assertEqual(cost_contract._DETAIL_WORKFLOW_KEY, "_cost_contract_detail_workflow")
        self.assertEqual(cost_contract._PENDING_DETAIL_WORKFLOW_KEY, "_cost_contract_pending_detail_workflow")

    def test_cost_contract_reexports_moved_price_helpers(self):
        from sections import cost_contract
        from sections import cost_contract_helpers

        self.assertIs(cost_contract.get_credit_price, cost_contract_helpers.get_credit_price)
        self.assertIs(cost_contract.get_current_ai_credit_price, cost_contract_helpers.get_current_ai_credit_price)

    def test_cost_monitoring_mart_sql_contract_stays_stable(self):
        from sections.cost_contract_contracts import build_cost_monitoring_mart_sql

        sql = build_cost_monitoring_mart_sql().upper()

        self.assertIn("FACT_COST_MONITORING_SIGNAL", sql)
        self.assertIn("FACT_COST_INCIDENT_TIMELINE", sql)
        self.assertIn("SP_OVERWATCH_REFRESH_COST_MONITORING", sql)
        self.assertIn("OVERWATCH_COST_MONITORING_REFRESH", sql)
        self.assertIn("WAREHOUSE = COMPUTE_WH", sql)

    def test_price_helpers_preserve_session_state_fallbacks(self):
        from sections import cost_contract_helpers

        with patch.object(cost_contract_helpers.st, "session_state", {"credit_price": "4.25"}):
            self.assertEqual(cost_contract_helpers.get_credit_price(), 4.25)

        with (
            patch.object(cost_contract_helpers.st, "session_state", {"ai_credit_price": "3.10"}),
            patch("sections.cost_contract_helpers.get_ai_credit_price", side_effect=RuntimeError("not configured")),
        ):
            self.assertEqual(cost_contract_helpers.get_current_ai_credit_price(), 3.10)

    def test_cost_contract_split_does_not_import_alert_facade(self):
        alert_facade_import = "utils" + ".alerts"
        modules = (
            APP_ROOT / "sections" / "cost_contract.py",
            APP_ROOT / "sections" / "cost_contract_advisor.py",
            APP_ROOT / "sections" / "cost_contract_advisor_panels.py",
            APP_ROOT / "sections" / "cost_contract_alert_context.py",
            APP_ROOT / "sections" / "cost_contract_charts.py",
            APP_ROOT / "sections" / "cost_contract_contracts.py",
            APP_ROOT / "sections" / "cost_contract_dataframes.py",
            APP_ROOT / "sections" / "cost_contract_evidence_panels.py",
            APP_ROOT / "sections" / "cost_contract_helpers.py",
            APP_ROOT / "sections" / "cost_contract_intelligence.py",
            APP_ROOT / "sections" / "cost_contract_loader.py",
            APP_ROOT / "sections" / "cost_contract_monitoring.py",
            APP_ROOT / "sections" / "cost_contract_overview.py",
            APP_ROOT / "sections" / "cost_contract_overview_floor.py",
            APP_ROOT / "sections" / "cost_contract_overview_panels.py",
            APP_ROOT / "sections" / "cost_contract_panels.py",
            APP_ROOT / "sections" / "cost_contract_rendering.py",
            APP_ROOT / "sections" / "cost_contract_sql.py",
            APP_ROOT / "sections" / "cost_contract_splash.py",
            APP_ROOT / "sections" / "cost_contract_workflow.py",
        )
        for path in modules:
            with self.subTest(path=path.name):
                self.assertNotIn(alert_facade_import, path.read_text(encoding="utf-8"))

    def test_cost_contract_uses_single_local_navigation_hierarchy(self):
        cost_contract_text = (APP_ROOT / "sections" / "cost_contract.py").read_text(encoding="utf-8")
        hierarchy_text = (APP_ROOT / "sections" / "cost_contract_hierarchy.py").read_text(encoding="utf-8")
        cost_center_text = (APP_ROOT / "sections" / "cost_center.py").read_text(encoding="utf-8")
        explorer_text = (APP_ROOT / "sections" / "cost_center_explorer_view.py").read_text(encoding="utf-8")
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")

        self.assertNotIn('render_workflow_selector(\n        "Cost workflow"', cost_contract_text)
        self.assertNotIn("st.columns([0.24, 0.76]", cost_contract_text)
        self.assertNotIn("render_local_section_menu", cost_contract_text)
        self.assertNotIn("render_explore_lens_selector", cost_contract_text)
        self.assertIn("render_section_breadcrumb", cost_contract_text)
        self.assertIn("autoload_section_command_brief", cost_contract_text)
        self.assertIn("render_section_command_brief", cost_contract_text)
        self.assertIn("render_cost_primary_tabs", cost_contract_text)
        self.assertIn("render_cost_explorer_lens_pills", cost_contract_text)
        self.assertLess(
            cost_contract_text.rindex("render_section_command_brief("),
            cost_contract_text.rindex("_render_cost_contract_workflow(workflow, company, environment)"),
        )
        self.assertIn("render_primary_section_tabs", hierarchy_text)
        self.assertIn("render_secondary_lens_pills", hierarchy_text)
        self.assertIn("COST_PRIMARY_NAV", hierarchy_text)
        self.assertIn('"Cost Overview"', hierarchy_text)
        self.assertIn('"Cost Explorer"', hierarchy_text)
        self.assertIn('"Cortex AI"', hierarchy_text)
        primary_nav_literal = hierarchy_text.split("COST_PRIMARY_NAV = (", 1)[1].split(")", 1)[0]
        self.assertIn('"Cortex AI"', primary_nav_literal)
        self.assertNotIn('"Waste Detection"', primary_nav_literal)
        self.assertIn('"Cortex AI"', hierarchy_text)
        self.assertIn('"Cortex AI Spend"', hierarchy_text)
        self.assertIn('"Cortex Predictive Alerts"', hierarchy_text)
        self.assertIn('"Review Cortex AI Costs"', hierarchy_text)
        self.assertIn("_cost_center_embedded_in_cost_contract", cost_center_text)
        self.assertIn("Cost & Contract owns section navigation", cost_center_text)
        self.assertIn("Current lens:", explorer_text)
        embedded_block = explorer_text.split("if embedded:", 1)[1].split("else:", 1)[0]
        self.assertNotIn("Break down by", embedded_block)
        for css_class in (
            "ow-breadcrumb",
            "ow-primary-tabs",
            "ow-primary-tab",
            "ow-lens-pills",
            "ow-lens-pill",
            "ow-kpi-hero",
            "ow-action-card",
            "ow-cost-filter-row",
            "ow-cost-action-strip",
            "ow-content-panel",
        ):
            self.assertIn(css_class, theme_text)

    def test_account_health_user_cost_drilldown_targets_explorer_user_lens(self):
        account_health_text = (APP_ROOT / "sections" / "account_health_overview_view.py").read_text(encoding="utf-8")

        self.assertIn('workflow="Cost Explorer"', account_health_text)
        self.assertIn('"cc_explorer_lens": "User / Role"', account_health_text)
        self.assertNotIn('workflow="Cortex AI",\n                        )', account_health_text)


if __name__ == "__main__":
    unittest.main()
