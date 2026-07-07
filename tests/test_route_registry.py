from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

import route_registry  # noqa: E402
import workflow_contracts  # noqa: E402
import config  # noqa: E402
from config import PRIMARY_SECTIONS, normalize_section_name  # noqa: E402
from sections import alert_center  # noqa: E402
from sections import executive_landing_common  # noqa: E402
from sections import executive_landing_contracts  # noqa: E402
from sections import security_posture_contracts  # noqa: E402


class RouteRegistryTests(unittest.TestCase):
    def test_workflow_contracts_reexport_route_registry(self):
        self.assertIs(workflow_contracts.PRIMARY_SECTION_TITLES, route_registry.PRIMARY_SECTION_TITLES)
        self.assertIs(workflow_contracts.SECTION_WORKFLOW_CONTRACT, route_registry.SECTION_WORKFLOW_CONTRACT)
        self.assertIs(workflow_contracts.LEGACY_ROUTE_CONTRACT, route_registry.LEGACY_ROUTE_CONTRACT)
        self.assertEqual(
            set(workflow_contracts.__all__),
            {
                "LEGACY_ROUTE_CONTRACT",
                "PRIMARY_SECTION_TITLES",
                "SECTION_WORKFLOW_CONTRACT",
            },
        )

    def test_abandoned_primary_section_constant_is_removed(self):
        removed_name = "ABANDONED" + "_PRIMARY_SECTION_TITLES"
        self.assertFalse(hasattr(route_registry, removed_name))
        self.assertNotIn(removed_name, route_registry.__all__)
        self.assertEqual(tuple(PRIMARY_SECTIONS), route_registry.PRIMARY_SECTION_TITLES)

    def test_primary_sections_have_workflow_contracts_and_defaults(self):
        for section in route_registry.PRIMARY_SECTION_TITLES:
            with self.subTest(section=section):
                workflows = route_registry.SECTION_WORKFLOW_CONTRACT[section]
                self.assertGreater(len(workflows), 0)
                self.assertIn(route_registry.DEFAULT_WORKFLOW_BY_SECTION[section], workflows)

    def test_legacy_route_contract_targets_are_primary_sections(self):
        primary = set(route_registry.PRIMARY_SECTION_TITLES)
        for route, target, state in route_registry.LEGACY_ROUTE_CONTRACT:
            with self.subTest(route=route):
                self.assertIn(target, primary)
                self.assertIsInstance(state, dict)

    def test_route_state_keys_are_known_routes(self):
        known_routes = (
            set(route_registry.PRIMARY_SECTION_TITLES)
            | set(route_registry.LEGACY_SECTION_ALIASES)
            | set(route_registry.RETIRED_SECTION_ALIASES)
        )
        for route in route_registry.SECTION_ROUTE_STATE:
            with self.subTest(route=route):
                self.assertIn(route, known_routes)

    def test_workflow_alias_targets_are_valid_workflows(self):
        for section, aliases in route_registry.WORKFLOW_ALIASES_BY_SECTION.items():
            workflows = set(route_registry.SECTION_WORKFLOW_CONTRACT[section])
            for alias, workflow in aliases.items():
                with self.subTest(section=section, alias=alias):
                    self.assertIn(workflow, workflows)

    def test_known_legacy_section_aliases_normalize_to_six_sections(self):
        expected = {
            "Executive Briefing": "Executive Landing",
            "Alerts": "Alert Center",
            "Data Sharing": "Security Monitoring",
            "Task Management": "Workload Operations",
        }
        for alias, target in expected.items():
            with self.subTest(alias=alias):
                self.assertEqual(route_registry.normalize_section_route(alias), target)
                self.assertEqual(normalize_section_name(alias), target)

    def test_all_registered_section_aliases_target_primary_sections(self):
        primary = set(route_registry.PRIMARY_SECTION_TITLES)
        for alias, target in route_registry.SECTION_ALIASES.items():
            with self.subTest(alias=alias):
                self.assertIn(target, primary)

    def test_executive_landing_aliases_remain_unchanged(self):
        expected = {
            "Executive Briefing": "Executive Overview",
            "Executive Summary": "Executive Overview",
            "Executive Scorecard": "Executive Admin / Advanced",
            "Scorecard Formulas": "Executive Admin / Advanced",
            "Value Ledger": "Executive Admin / Advanced",
            "Production Readiness": "Executive Admin / Advanced",
            "Data Trust": "Executive Admin / Advanced",
            "Forecasting": "Cost Movement",
        }
        for alias, workflow in expected.items():
            with self.subTest(alias=alias):
                self.assertEqual(route_registry.normalize_workflow_alias("Executive Landing", alias), workflow)
                self.assertEqual(executive_landing_common.normalize_executive_landing_workflow(alias), workflow)
        self.assertEqual(executive_landing_common.normalize_executive_landing_workflow("Unknown"), "Executive Overview")

    def test_alert_center_aliases_remain_current_panes(self):
        expected = {
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

    def test_retired_routes_no_longer_silently_redirect(self):
        for route in ("Account Health", "Command Center", "Optimization", "Warehouse Health", "Security Posture"):
            with self.subTest(route=route):
                self.assertEqual(route_registry.normalize_section_route(route), route)
                self.assertEqual(config.normalize_section_name(route), route)
                self.assertEqual(route_registry.compatibility_state_for_route(route), {})

    def test_config_reuses_route_registry_contracts(self):
        self.assertEqual(config.SECTION_REDIRECTS, route_registry.LEGACY_SECTION_ALIASES)
        self.assertEqual(config.RETIRED_SECTION_REDIRECTS, route_registry.RETIRED_SECTION_ALIASES)
        self.assertEqual(config.SECTION_ROUTE_STATE, route_registry.SECTION_ROUTE_STATE)
        self.assertEqual(config.SECTION_ALIASES, route_registry.SECTION_ALIASES)
        self.assertEqual(set(config.SECTION_REDIRECTS), set(route_registry.LEGACY_SECTION_ALIASES))
        self.assertEqual(set(config.RETIRED_SECTION_REDIRECTS), set(route_registry.RETIRED_SECTION_ALIASES))
        for route in route_registry.SECTION_ROUTE_STATE:
            with self.subTest(route=route):
                self.assertEqual(
                    config.compatibility_state_for_section(route),
                    route_registry.compatibility_state_for_route(route),
                )

        for alias in ("Executive Briefing", "Task Management", "Totally Unknown Route"):
            with self.subTest(alias=alias):
                self.assertEqual(config.normalize_section_name(alias), route_registry.normalize_section_route(alias))

    def test_section_alias_constants_are_registry_backed(self):
        self.assertEqual(
            executive_landing_contracts.EXECUTIVE_LANDING_LEGACY_WORKFLOW_ALIASES,
            dict(route_registry.WORKFLOW_ALIASES_BY_SECTION["Executive Landing"]),
        )
        self.assertEqual(
            security_posture_contracts.SECURITY_VIEW_ALIASES,
            dict(route_registry.WORKFLOW_ALIASES_BY_SECTION["Security Monitoring"]),
        )
        self.assertEqual(
            alert_center._normalize_alert_center_view("Issue Inbox"),
            route_registry.normalize_workflow_alias("Alert Center", "Issue Inbox"),
        )

    def test_route_registry_stays_dependency_light(self):
        source = (APP_ROOT / "route_registry.py").read_text(encoding="utf-8")
        forbidden = (
            "import config",
            "from config",
            "import streamlit",
            "from streamlit",
            "import sections",
            "from sections",
            "import utils",
            "from utils",
            "import snowflake",
            "from snowflake",
        )
        for fragment in forbidden:
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, source)

    def test_route_registry_consumers_import_without_live_sessions(self):
        import workflow_contracts as imported_workflow_contracts  # noqa: F401
        import config as imported_config  # noqa: F401
        from sections import alert_center_navigation  # noqa: F401
        from sections import executive_landing_contracts  # noqa: F401
        from sections import security_posture_contracts  # noqa: F401


if __name__ == "__main__":
    unittest.main()
