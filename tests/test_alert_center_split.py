from pathlib import Path
import inspect
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections import alert_center  # noqa: E402
from sections import alert_center_active_view as active_view  # noqa: E402
from sections import alert_center_admin_catalog_view as catalog_view  # noqa: E402
from sections import alert_center_admin_delivery_view as delivery_view  # noqa: E402
from sections import alert_center_admin_suppression_view as suppression_view  # noqa: E402
from sections import alert_center_boards as boards  # noqa: E402
from sections import alert_center_category_views as category_views  # noqa: E402
from sections import alert_center_contracts as contracts  # noqa: E402
from sections import alert_center_data as data  # noqa: E402
from sections import alert_center_diagnostics_view as diagnostics_view  # noqa: E402
from sections import alert_center_history_view as history_view  # noqa: E402
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
        self.assertIs(alert_center.ALERT_CENTER_ADMIN_VIEWS, contracts.ALERT_CENTER_ADMIN_VIEWS)
        self.assertIs(alert_center.ALERT_CENTER_ADMIN_VIEW_KEY, contracts.ALERT_CENTER_ADMIN_VIEW_KEY)
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

    def test_alert_center_reexports_split_helpers(self):
        for name in [
            "ALERT_CENTER_PANES",
            "ALERT_CENTER_PANE_LABELS",
            "ALERT_CENTER_ADMIN_VIEWS",
            "ALERT_CENTER_ADMIN_VIEW_KEY",
            "ALERT_CENTER_SOURCE_PLAN",
            "_normalize_alert_center_view",
            "_alert_center_sources_for_view",
            "_alert_center_source_summary",
            "_load_center_data",
            "defer_source_note",
        ]:
            with self.subTest(name=name):
                self.assertTrue(hasattr(alert_center, name))

    def test_alert_center_renderer_maps_cover_panes(self):
        self.assertEqual(set(alert_center.ALERT_CENTER_PANES), set(alert_center.ALERT_CENTER_RENDERERS))
        for view in alert_center.ALERT_CENTER_PANES:
            with self.subTest(view=view):
                self.assertTrue(callable(alert_center.ALERT_CENTER_RENDERERS[view]))

        expected_admin = {"Detection Catalog", "Delivery & Automation", "Suppression Windows"}
        self.assertEqual(expected_admin, set(alert_center.ALERT_CENTER_ADMIN_RENDERERS))
        for view in expected_admin:
            with self.subTest(admin_view=view):
                self.assertTrue(callable(alert_center.ALERT_CENTER_ADMIN_RENDERERS[view]))
        legacy_aliases = {"Command Center", "Issue Inbox", "Triage Digest", "Cost / Cortex", "Pipeline", "Security"}
        self.assertFalse(legacy_aliases & set(alert_center.ALERT_CENTER_RENDERERS))
        self.assertFalse(legacy_aliases & set(alert_center.ALERT_CENTER_ADMIN_RENDERERS))
        self.assertIs(
            alert_center.ALERT_CENTER_ADMIN_RENDERERS["Detection Catalog"],
            catalog_view.render_alert_detection_catalog_tool,
        )

    def test_alert_center_renderer_identity(self):
        self.assertIs(alert_center.ALERT_CENTER_RENDERERS["Active Alerts"], active_view.render_active_alerts_pane)
        self.assertIs(alert_center.ALERT_CENTER_RENDERERS["Cost Alerts"], category_views.render_cost_alerts_pane)
        self.assertIs(alert_center.ALERT_CENTER_RENDERERS["Reliability Alerts"], category_views.render_reliability_alerts_pane)
        self.assertIs(alert_center.ALERT_CENTER_RENDERERS["Security Alerts"], category_views.render_security_alerts_pane)
        self.assertIs(alert_center.ALERT_CENTER_RENDERERS["Alert History"], history_view.render_alert_history_pane)
        self.assertIs(alert_center.ALERT_CENTER_ADMIN_RENDERERS["Delivery & Automation"], delivery_view.render_alert_delivery_automation_pane)
        self.assertIs(alert_center.ALERT_CENTER_ADMIN_RENDERERS["Suppression Windows"], suppression_view.render_suppression_windows_pane)
        self.assertIs(alert_center._render_advanced_alert_diagnostics, diagnostics_view._render_advanced_alert_diagnostics)
        self.assertIs(alert_center._render_alert_change_context, diagnostics_view._render_alert_change_context)

    def test_alert_center_board_helpers_reexport_focused_module(self):
        for name in [
            "_open_alert_mask",
            "_alert_center_operability_rows",
            "_alert_center_health_score",
            "_alert_center_action_brief",
            "_alert_operator_workflow_rows",
            "_alert_next_incident_packet",
            "_alert_domain_next_move_rows",
            "_alert_center_exception_rows",
            "_alert_threshold_tuning_rows",
            "_alert_company_scope_readiness_rows",
            "_alert_operations_review_rows",
            "_alert_center_scope_key",
            "_alert_center_loaded_meta",
            "_alert_lifecycle_board",
        ]:
            with self.subTest(name=name):
                self.assertIs(getattr(alert_center, name), getattr(boards, name))

    def test_alert_center_legacy_aliases_normalize_to_current_panes(self):
        aliases = {
            "Command Center": "Active Alerts",
            "Issue Inbox": "Active Alerts",
            "Cost / Cortex": "Cost Alerts",
            "Pipeline": "Reliability Alerts",
            "Security": "Security Alerts",
            "Triage Digest": "Active Alerts",
            "Delivery & Automation": "Alert Settings / Admin",
            "Suppression Windows": "Alert Settings / Admin",
        }
        for alias, expected in aliases.items():
            with self.subTest(alias=alias):
                self.assertEqual(alert_center._normalize_alert_center_view(alias), expected)
        self.assertNotIn("Issue Inbox", alert_center.ALERT_CENTER_RENDERERS)
        self.assertNotIn("Triage Digest", alert_center.ALERT_CENTER_RENDERERS)

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

    def test_operability_rows_flag_stale_loaded_scope(self):
        rows = boards._alert_center_operability_rows(
            {},
            company="ALFA",
            environment="PROD",
            days=7,
            limit=100,
            loaded_scope=("TREXIS", "PROD", 7, 100),
        )
        stale = rows[rows["CONTROL"].eq("Loaded scope status")].iloc[0]
        self.assertEqual(stale["STATE"], "Scope Stale")
        self.assertEqual(stale["SEVERITY"], "High")

    def test_action_brief_priority_order(self):
        blocker = pd.DataFrame([{
            "CONTROL": "Loaded scope status",
            "STATE": "Scope Stale",
            "EVIDENCE": "old scope",
            "NEXT_ACTION": "reload",
        }])
        cases = [
            (dict(readiness_rows=blocker), "Scope Stale"),
            (dict(overdue=2), "Escalate"),
            (dict(critical_high=2), "Priority"),
            (dict(open_queue=2), "Queue"),
            (dict(email_ready=3, email_logged=1), "Telemetry"),
            (dict(open_issues=2), "Triage"),
            ({}, "Clear"),
        ]
        defaults = dict(
            open_issues=0,
            open_alerts=0,
            critical_high=0,
            overdue=0,
            email_ready=0,
            email_logged=0,
            open_queue=0,
            readiness_rows=None,
        )
        for overrides, expected_state in cases:
            with self.subTest(expected_state=expected_state):
                brief = boards._alert_center_action_brief(**{**defaults, **overrides})
                self.assertEqual(brief["state"], expected_state)

    def test_alert_center_first_paint_shell_does_not_auto_load_data(self):
        render_source = inspect.getsource(alert_center.render)

        self.assertNotIn("_load_center_data(", render_source)
        self.assertIn('st.button(f"Load {source_view}"', render_source)
        self.assertIn("_render_alert_center_first_paint_shell(", render_source)
        self.assertLess(
            render_source.index('st.button(f"Load {source_view}"'),
            render_source.index("_load_alert_center_view_data("),
        )
        first_paint_source = inspect.getsource(alert_center._render_alert_center_first_paint_shell)
        self.assertIn("First paint does not query Snowflake", first_paint_source)
        self.assertIn("render_first_paint_summary_shell(", first_paint_source)

    def test_alert_center_first_paint_summary_cold_state_is_on_demand(self):
        summary = alert_center._alert_center_first_paint_summary(None, "Active Alerts")

        self.assertEqual(summary["critical_high"], "On demand")
        self.assertEqual(summary["overdue"], "On demand")
        self.assertEqual(summary["open_queue"], "On demand")
        self.assertEqual(summary["top_lane"], "Selected view")
        self.assertEqual(summary["freshness"], "Not loaded")

    def test_alert_center_first_paint_summary_uses_cached_summary(self):
        cached_summary = {
            "critical_high_count": 3,
            "overdue_count": "2",
            "open_queue_count": 5,
            "loaded_at": "2026-06-24 09:00",
        }

        summary = alert_center._alert_center_first_paint_summary(
            None,
            "Active Alerts",
            cached_summary=cached_summary,
        )

        self.assertEqual(summary["critical_high"], "3")
        self.assertEqual(summary["overdue"], "2")
        self.assertEqual(summary["open_queue"], "5")
        self.assertEqual(summary["top_lane"], "Critical / high")
        self.assertEqual(summary["freshness"], "2026-06-24 09:00")

    def test_alert_center_cached_summary_scope_must_match_filters(self):
        cached_summary = {
            "source_view": "Active Alerts",
            "company": "ALFA",
            "environment": "PROD",
            "days": 7,
            "limit": 200,
            "critical_high": "1",
        }

        self.assertIs(
            alert_center._alert_center_cached_summary_for_scope(
                cached_summary,
                source_view="Active Alerts",
                company="ALFA",
                environment="PROD",
                days=7,
                limit=200,
            ),
            cached_summary,
        )
        self.assertIsNone(
            alert_center._alert_center_cached_summary_for_scope(
                cached_summary,
                source_view="Active Alerts",
                company="TREXIS",
                environment="PROD",
                days=7,
                limit=200,
            )
        )

    def test_alert_center_first_paint_summary_uses_cached_session_data(self):
        cached = {
            "loaded_at": "2026-06-24 08:30",
            "alerts": pd.DataFrame([
                {
                    "STATUS": "New",
                    "SEVERITY": "Critical",
                    "SLA_STATE": "Overdue",
                },
                {
                    "STATUS": "Fixed",
                    "SEVERITY": "High",
                    "SLA_STATE": "",
                },
            ]),
            "action_queue": pd.DataFrame([
                {"STATUS": "New"},
                {"STATUS": "Fixed"},
            ]),
        }

        summary = alert_center._alert_center_first_paint_summary(cached, "Active Alerts")

        self.assertEqual(summary["critical_high"], "1")
        self.assertEqual(summary["overdue"], "1")
        self.assertEqual(summary["open_queue"], "1")
        self.assertEqual(summary["top_lane"], "Critical / high")
        self.assertEqual(summary["freshness"], "2026-06-24 08:30")

    def test_exception_rows_include_core_exception_signals(self):
        alerts = pd.DataFrame([{
            "STATUS": "New",
            "SEVERITY": "Critical",
            "SLA_STATE": "Overdue",
            "OWNER": "DBA",
            "DELIVERY_STATUS": "EMAIL_READY",
        }])
        queue = pd.DataFrame([{"STATUS": "New"}])
        issues = pd.DataFrame([{"SEVERITY": "High"}])
        delivery_log = pd.DataFrame([{"DELIVERY_STATUS": "FAILED"}])
        readiness = pd.DataFrame([{"STATE": "Scope Stale"}])
        rows = boards._alert_center_exception_rows(
            alerts=alerts,
            queue=queue,
            issues=issues,
            delivery_log=delivery_log,
            readiness_rows=readiness,
        )
        signals = set(rows["SIGNAL"])
        self.assertIn("Critical/high alerts", signals)
        self.assertIn("Overdue alert SLAs", signals)
        self.assertIn("Generic alert routes", signals)
        self.assertIn("Delivery status gap", signals)
        self.assertIn("Open action queue", signals)
        self.assertIn("Alert control blockers", signals)

    def test_company_scope_readiness_handles_missing_columns(self):
        rows = boards._alert_company_scope_readiness_rows(
            pd.DataFrame({"ALERT_ID": ["a1"]}),
            pd.DataFrame({"ACTION_ID": ["q1"]}),
        )
        states = dict(zip(rows["SOURCE"], rows["STATE"]))
        self.assertEqual(states["Alert events"], "Needs Company")
        self.assertEqual(states["Action queue"], "Needs Company")

    def test_operations_review_blocks_default_native_and_auto_policy(self):
        rows = boards._alert_operations_review_rows(
            native_registry=pd.DataFrame([{"STATUS": "READY", "ENABLED_BY_DEFAULT": True}]),
            remediation_policy=pd.DataFrame([{"AUTO_ELIGIBLE": True}]),
        )
        states = dict(zip(rows["REVIEW_AREA"], rows["STATE"]))
        self.assertEqual(states["Native alert promotion"], "Blocked")
        self.assertEqual(states["Dry-run automation"], "Blocked")

    def test_delivery_control_rows_surface_review_states(self):
        rows = delivery_view._delivery_remediation_control_rows(
            alerts=pd.DataFrame([{"ALERT_ID": "a1"}]),
            queue=pd.DataFrame([{"ACTION_ID": "q1"}]),
            delivery_log=pd.DataFrame([{"DELIVERY_STATUS": "FAILED"}]),
            rules=pd.DataFrame([{"RULE_ID": "r1"}]),
            native_registry=pd.DataFrame([{"STATUS": "READY", "ENABLED_BY_DEFAULT": True}]),
            remediation_policy=pd.DataFrame([{"AUTO_ELIGIBLE": True}]),
            remediation_dry_run=pd.DataFrame(),
        )
        states = dict(zip(rows["CONTROL"], rows["STATE"]))
        self.assertEqual(states["Delivery status"], "Review")
        self.assertEqual(states["Native alert registry"], "Review")
        self.assertEqual(states["Remediation policy"], "Review")

    def test_action_queue_routing_preview_uses_only_open_alerts(self):
        alerts = pd.DataFrame([
            {"ALERT_ID": "open-1", "STATUS": "New"},
            {"ALERT_ID": "closed-1", "STATUS": "Fixed"},
        ])
        captured = {}

        def fake_to_actions(frame, company):
            captured["ids"] = frame["ALERT_ID"].tolist()
            captured["company"] = company
            return [{"Entity": "WH1", "Action": "Review"}]

        with patch("utils.alert_action_queue.alert_history_to_actions", side_effect=fake_to_actions):
            routable, preview = delivery_view._action_queue_routing_preview(alerts, company="ALFA")

        self.assertEqual(routable["ALERT_ID"].tolist(), ["open-1"])
        self.assertEqual(captured, {"ids": ["open-1"], "company": "ALFA"})
        self.assertEqual(preview["Action"].tolist(), ["Review"])

    def test_loaded_pane_dispatch_calls_registered_renderer(self):
        calls = []

        def fake_active(alerts, queue, delivery_log, rules):
            calls.append((len(alerts), len(queue), len(delivery_log), len(rules)))

        handled = alert_center._render_loaded_alert_center_pane(
            "Active Alerts",
            pd.DataFrame([{"ALERT_ID": "a1"}]),
            pd.DataFrame([{"ACTION_ID": "q1"}]),
            pd.DataFrame([{"DELIVERY_STATUS": "SENT"}]),
            pd.DataFrame([{"RULE_ID": "r1"}]),
            "ALFA",
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            renderers={"Active Alerts": fake_active},
        )
        self.assertTrue(handled)
        self.assertEqual(calls, [(1, 1, 1, 1)])

    def test_category_token_patterns_do_not_drift(self):
        self.assertEqual(
            category_views.alert_category_token_pattern("Cost Alerts"),
            "COST|SPEND|CORTEX|WAREHOUSE|OPTIMIZATION|CONTRACT|CHARGEBACK",
        )
        self.assertEqual(
            category_views.alert_category_token_pattern("Reliability Alerts"),
            "QUERY|TASK|PIPELINE|PROCEDURE|COPY|LOAD|PERFORMANCE|WAREHOUSE",
        )
        self.assertEqual(
            category_views.alert_category_token_pattern("Security Alerts"),
            "SECURITY|LOGIN|GRANT|PRIVILEGE|SHARE|ACCESS|EXPORT",
        )

    def test_suppression_window_sql_builders(self):
        insert_sql = suppression_view._suppression_window_insert_sql(
            table_name="APP.ALERTS.OVERWATCH_ANNOTATIONS",
            entity="O'HARE_WH",
            entity_type="WAREHOUSE",
            window_start="2026-06-23 01:00:00",
            window_end="2026-06-23 02:00:00",
            annotation_type="PLANNED_MAINTENANCE",
            description="Owner's maintenance",
            suppress=True,
        )
        self.assertIn("INSERT INTO APP.ALERTS.OVERWATCH_ANNOTATIONS", insert_sql)
        self.assertIn("O''HARE_WH", insert_sql)
        self.assertIn("Owner''s maintenance", insert_sql)
        self.assertIn("SUPPRESS_ALERTS", insert_sql)

        deactivate_sql = suppression_view._suppression_window_deactivate_sql(7, "APP.ALERTS.OVERWATCH_ANNOTATIONS")
        self.assertIn("UPDATE APP.ALERTS.OVERWATCH_ANNOTATIONS", deactivate_sql)
        self.assertIn("WHERE ANNOTATION_ID = 7", deactivate_sql)

        select_sql = suppression_view._suppression_windows_select_sql("APP.ALERTS.OVERWATCH_ANNOTATIONS")
        self.assertIn("DATEADD('day', -7, CURRENT_TIMESTAMP())", select_sql)
        self.assertIn("LIMIT 300", select_sql)

    def test_alert_center_facade_line_count_stays_below_guardrail(self):
        source = (APP_ROOT / "sections" / "alert_center.py").read_text()
        self.assertLess(len(source.splitlines()), 1000)
        for moved_fragment in [
            "INSERT INTO {table_name}",
            "UPDATE {table_name}",
            "SNOWFLAKE.ACCOUNT_USAGE",
            "build_alert_signal_query_catalog(",
            "build_alert_native_object_registry_seed_rows(",
            "def render_alert_delivery_automation_pane",
            "def _render_alert_email_delivery_status",
            "def _render_alert_action_queue_routing",
            "def _render_alert_notification_remediation",
            "def _render_operational_ownership_coverage",
            "def _render_operational_risk_score_explanation",
            "def _render_alert_change_context",
            "def _render_alert_action_workflows",
            "def _render_alert_command_findings",
            'elif source_view == "Issue Inbox"',
            'elif source_view == "Triage Digest"',
        ]:
            with self.subTest(fragment=moved_fragment):
                self.assertNotIn(moved_fragment, source)

    def test_advanced_alert_diagnostics_are_explicit_after_first_paint(self):
        source = (APP_ROOT / "sections" / "alert_center_diagnostics_view.py").read_text(encoding="utf-8")
        diagnostics_gate = source.split("def _render_advanced_alert_diagnostics", 1)[1].split(
            "with st.expander",
            1,
        )[0]

        self.assertIn("alert_center_show_advanced_diagnostics", diagnostics_gate)
        self.assertIn("Show Advanced Alert Diagnostics", diagnostics_gate)
        self.assertIn("return", diagnostics_gate)


if __name__ == "__main__":
    unittest.main()
