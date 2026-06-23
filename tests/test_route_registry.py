from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

import route_registry  # noqa: E402
import workflow_contracts  # noqa: E402
from config import PRIMARY_SECTIONS, normalize_section_name  # noqa: E402
from sections import account_health  # noqa: E402
from sections import alert_center  # noqa: E402
from sections import executive_landing  # noqa: E402


class RouteRegistryTests(unittest.TestCase):
    def test_workflow_contracts_reexport_route_registry(self):
        self.assertIs(workflow_contracts.PRIMARY_SECTION_TITLES, route_registry.PRIMARY_SECTION_TITLES)
        self.assertIs(workflow_contracts.SECTION_WORKFLOW_CONTRACT, route_registry.SECTION_WORKFLOW_CONTRACT)
        self.assertIs(workflow_contracts.LEGACY_ROUTE_CONTRACT, route_registry.LEGACY_ROUTE_CONTRACT)

    def test_abandoned_primary_sections_are_not_primary_ui(self):
        for title in route_registry.ABANDONED_PRIMARY_SECTION_TITLES:
            with self.subTest(title=title):
                self.assertNotIn(title, PRIMARY_SECTIONS)
        self.assertEqual(tuple(PRIMARY_SECTIONS), route_registry.PRIMARY_SECTION_TITLES)

    def test_known_legacy_section_aliases_normalize_to_six_sections(self):
        expected = {
            "Command Center": "DBA Control Room",
            "Account Health": "DBA Control Room",
            "Optimization": "Cost & Contract",
            "Warehouse Health": "Cost & Contract",
            "Executive Briefing": "Executive Landing",
            "Alerts": "Alert Center",
            "Security Posture": "Security Monitoring",
            "Data Sharing": "Security Monitoring",
            "Task Management": "Workload Operations",
        }
        for alias, target in expected.items():
            with self.subTest(alias=alias):
                self.assertEqual(route_registry.normalize_section_route(alias), target)
                self.assertEqual(normalize_section_name(alias), target)

    def test_executive_landing_aliases_remain_unchanged(self):
        expected = {
            "Executive Briefing": "Executive Overview",
            "Executive Summary": "Executive Overview",
            "Adoption Analytics": "Executive Admin / Advanced",
            "Executive Scorecard": "Executive Admin / Advanced",
            "Scorecard Formulas": "Executive Admin / Advanced",
            "Value Ledger": "Executive Admin / Advanced",
            "Production Readiness": "Executive Admin / Advanced",
            "Data Trust": "Executive Admin / Advanced",
            "Command Center": "Executive Overview",
            "Forecasting": "Cost Movement",
        }
        for alias, workflow in expected.items():
            with self.subTest(alias=alias):
                self.assertEqual(route_registry.normalize_workflow_alias("Executive Landing", alias), workflow)
                self.assertEqual(executive_landing.normalize_executive_landing_workflow(alias), workflow)
        self.assertEqual(executive_landing.normalize_executive_landing_workflow("Unknown"), "Executive Overview")

    def test_alert_center_aliases_remain_current_panes(self):
        expected = {
            "Command Center": "Active Alerts",
            "Issue Inbox": "Active Alerts",
            "Triage Digest": "Active Alerts",
            "Cost / Cortex": "Cost Alerts",
            "Pipeline": "Reliability Alerts",
            "Security": "Security Alerts",
            "Delivery & Automation": "Alert Settings / Admin",
            "Suppression Windows": "Alert Settings / Admin",
        }
        for alias, pane in expected.items():
            with self.subTest(alias=alias):
                self.assertEqual(route_registry.normalize_workflow_alias("Alert Center", alias), pane)
                self.assertEqual(alert_center._normalize_alert_center_view(alias), pane)

    def test_account_health_retired_routes_still_land_on_control_room(self):
        for route in (None, "Account Health", "Command Center", "DBA Control Room"):
            with self.subTest(route=route):
                self.assertEqual(account_health._canonical_account_route(route), "DBA Control Room")


if __name__ == "__main__":
    unittest.main()
