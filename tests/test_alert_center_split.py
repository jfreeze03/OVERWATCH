from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections import alert_center  # noqa: E402
from sections import alert_center_contracts as contracts  # noqa: E402
from sections import alert_center_data as data  # noqa: E402
from sections import alert_center_navigation as navigation  # noqa: E402


class AlertCenterSplitTests(unittest.TestCase):
    def test_alert_center_primary_panes_stay_stable(self):
        self.assertEqual(
            alert_center.ALERT_CENTER_PANES,
            [
                "Active Alerts",
                "Cost Alerts",
                "Reliability Alerts",
                "Security Alerts",
                "Alert History",
                "Alert Settings / Admin",
            ],
        )

    def test_alert_center_contracts_reexport_focused_modules(self):
        self.assertIs(alert_center.ALERT_CENTER_PANES, contracts.ALERT_CENTER_PANES)
        self.assertIs(alert_center.ALERT_CENTER_PANE_LABELS, contracts.ALERT_CENTER_PANE_LABELS)
        self.assertIs(alert_center.ALERT_CENTER_BRIEF_WORKFLOWS, contracts.ALERT_CENTER_BRIEF_WORKFLOWS)
        self.assertIs(alert_center.ALERT_CENTER_SOURCES_BY_PANE, contracts.ALERT_CENTER_SOURCES_BY_PANE)
        self.assertIs(alert_center.ALERT_CENTER_SOURCE_PLAN, contracts.ALERT_CENTER_SOURCE_PLAN)
        self.assertIs(alert_center.defer_source_note, contracts.defer_source_note)
        self.assertIs(alert_center._deferred_notes_key, contracts._deferred_notes_key)
        self.assertIs(alert_center._normalize_alert_center_view, navigation._normalize_alert_center_view)
        self.assertIs(alert_center._alert_admin_view_for_route, navigation._alert_admin_view_for_route)
        self.assertIs(alert_center._alert_center_sources_for_view, navigation._alert_center_sources_for_view)
        self.assertIs(alert_center._alert_center_source_summary, navigation._alert_center_source_summary)
        self.assertIs(alert_center._load_center_data, data._load_center_data)

    def test_alert_center_legacy_aliases_normalize_to_current_panes(self):
        aliases = {
            "Command Center": "Active Alerts",
            "Issue Inbox": "Active Alerts",
            "Cost / Cortex": "Cost Alerts",
            "Pipeline": "Reliability Alerts",
            "Security": "Security Alerts",
            "Delivery & Automation": "Alert Settings / Admin",
            "Suppression Windows": "Alert Settings / Admin",
        }
        for alias, expected in aliases.items():
            with self.subTest(alias=alias):
                self.assertEqual(alert_center._normalize_alert_center_view(alias), expected)

    def test_alert_center_admin_view_for_route(self):
        expected = {
            "Alert Settings / Admin": "Delivery & Automation",
            "Detection Catalog": "Detection Catalog",
            "Delivery & Automation": "Delivery & Automation",
            "Suppression Windows": "Suppression Windows",
        }
        for route, admin_view in expected.items():
            with self.subTest(route=route):
                self.assertEqual(alert_center._alert_admin_view_for_route(route), admin_view)

    def test_alert_center_sources_for_view(self):
        expected = {
            "Active Alerts": {"alerts", "action_queue", "delivery_log", "rules"},
            "Cost Alerts": {"alerts", "action_queue", "rules"},
            "Reliability Alerts": {"alerts", "action_queue", "rules"},
            "Security Alerts": {"alerts", "action_queue", "rules"},
            "Alert History": {"alerts", "action_queue", "delivery_log"},
            "Alert Settings / Admin": set(),
            "Detection Catalog": set(),
            "Delivery & Automation": {
                "alerts",
                "action_queue",
                "delivery_log",
                "rules",
                "native_registry",
                "remediation_policy",
                "remediation_dry_run",
            },
            "Suppression Windows": set(),
        }
        for view, sources in expected.items():
            with self.subTest(view=view):
                self.assertEqual(alert_center._alert_center_sources_for_view(view), sources)

    def test_alert_center_source_summary_uses_operator_labels(self):
        summary = alert_center._alert_center_source_summary({
            "action_queue",
            "native_registry",
            "remediation_policy",
        })
        self.assertIn("Action queue", summary)
        self.assertIn("Native alert registry", summary)
        self.assertIn("Remediation policy", summary)
        self.assertNotIn("action_queue", summary)
        self.assertNotIn("native_registry", summary)
        self.assertNotIn("remediation_policy", summary)

    def test_alert_center_data_loader_respects_requested_sources(self):
        rules = pd.DataFrame({"RULE_NAME": ["COST_SPIKE"]})
        issues = pd.DataFrame({"ISSUE_SOURCE": ["Rule catalog"]})
        with patch("sections.alert_center_data.load_alert_rule_catalog", return_value=rules) as load_rules, patch(
            "sections.alert_center_data.load_alert_history"
        ) as load_history, patch(
            "sections.alert_center_data.load_action_queue"
        ) as load_queue, patch(
            "sections.alert_center_data.build_dashboard_issue_rows",
            return_value=issues,
        ) as build_issues:
            loaded = data._load_center_data(
                object(),
                "ALFA",
                "ALL",
                7,
                100,
                sources={"rules"},
            )

        load_rules.assert_called_once_with(section="Alert Center")
        load_history.assert_not_called()
        load_queue.assert_not_called()
        build_issues.assert_called_once()
        self.assertIs(loaded["rules"], rules)
        self.assertIs(loaded["issues"], issues)
        self.assertEqual(loaded["_loaded_sources"], ["rules"])


if __name__ == "__main__":
    unittest.main()
