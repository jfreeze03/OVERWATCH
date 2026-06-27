from pathlib import Path
import contextlib
import sys
import unittest
from unittest.mock import Mock, patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


class PrimaryFirstPaintContractTests(unittest.TestCase):
    def test_contract_registry_covers_primary_sections_and_stays_import_safe(self):
        from route_registry import PRIMARY_SECTION_TITLES
        from sections.first_paint_contracts import PRIMARY_FIRST_PAINT_CONTRACTS

        self.assertEqual(tuple(PRIMARY_FIRST_PAINT_CONTRACTS), PRIMARY_SECTION_TITLES)
        source = (APP_ROOT / "sections" / "first_paint_contracts.py").read_text(encoding="utf-8")
        self.assertNotIn("import streamlit", source)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", source)
        self.assertNotRegex(source, r"\brun_query(?:_or_raise)?\s*\(")

        for section, contract in PRIMARY_FIRST_PAINT_CONTRACTS.items():
            with self.subTest(section=section):
                self.assertEqual(contract.section, section)
                self.assertTrue(contract.default_view)
                self.assertTrue(contract.expected_lanes)
                self.assertTrue(contract.explicit_load_cta)
                self.assertIn("Entry", contract.no_query_note)
                self.assertTrue(contract.allowed_cached_sources)
                self.assertTrue(contract.forbidden_first_paint_loaders)

    def test_shell_builder_uses_registry_defaults_with_overrides(self):
        from sections.shell_helpers import build_first_paint_summary_spec

        spec = build_first_paint_summary_spec(
            "Alert Center",
            state="Ready",
            headline="Alerts are ready",
            metrics=(("Open Queue", "0"),),
            snapshot=(("Scope", "ALFA / PROD"),),
            load_cta="Load Cost Alerts",
            view="Cost Alerts",
        )

        self.assertEqual(spec.section, "Alert Center")
        self.assertEqual(spec.view, "Cost Alerts")
        self.assertEqual(spec.load_cta, "Load Cost Alerts")
        self.assertIn("Critical and high alerts", spec.expected_lanes)
        self.assertIn("Entry", spec.no_query_note)
        self.assertIn(("Open Queue", "0"), spec.metrics)
        self.assertIn(("Scope", "ALFA / PROD"), spec.snapshot)

    def test_alert_center_first_paint_contract_does_not_load_rows(self):
        from sections import alert_center

        with patch.object(alert_center, "_load_center_data", side_effect=AssertionError("details must stay behind Load")), patch.object(
            alert_center,
            "render_section_first_paint_shell",
        ) as render_shell, patch.object(
            alert_center,
            "_render_alert_command_lane_board",
        ), patch.object(alert_center.st, "info"):
            alert_center._render_alert_center_first_paint_shell(
                source_view="Active Alerts",
                company="ALFA",
                environment="PROD",
                days=7,
                limit=200,
                required_sources={"ALERTS", "ISSUES"},
            )

        spec = render_shell.call_args.args[0]
        self.assertEqual(spec.section, "Alert Center")
        self.assertEqual(spec.view, "Active Alerts")
        self.assertEqual(spec.load_cta, "Load Active Alerts")

    def test_workload_first_paint_contract_does_not_load_specialist_evidence(self):
        from sections import workload_operations

        with contextlib.ExitStack() as stack:
            render_brief = stack.enter_context(patch.object(workload_operations, "render_section_command_brief"))
            autoload = stack.enter_context(patch.object(workload_operations, "autoload_section_command_brief", return_value="brief"))
            stack.enter_context(patch.object(workload_operations, "build_loaded_section_alert_signal_board", return_value=pd.DataFrame()))
            stack.enter_context(patch.object(workload_operations.st, "columns", side_effect=lambda count: [contextlib.nullcontext() for _ in range(count)]))
            stack.enter_context(patch.object(workload_operations.st, "button", return_value=False))
            stack.enter_context(patch.object(workload_operations.st, "caption"))
            stack.enter_context(patch.object(workload_operations.st, "markdown"))
            for loader_name in (
                "load_change_correlation_detail",
                "load_change_event_detail",
                "load_closed_loop_execution_plan_detail",
                "load_closed_loop_workflow_detail",
                "load_command_center_finding_detail",
                "load_command_center_recommendation_detail",
                "load_forecast_detail",
            ):
                stack.enter_context(
                    patch.object(
                        workload_operations,
                        loader_name,
                        side_effect=AssertionError(f"{loader_name} must stay workflow gated"),
                    )
                )

            workload_operations._render_workload_overview("ALFA", "PROD")

        autoload.assert_called_once_with("Workload Operations", "ALFA", "PROD", 7, force=False)
        render_brief.assert_called_once()

    def test_dba_morning_cockpit_contract_does_not_load_until_button(self):
        from sections import dba_control_room
        from sections.first_paint_contracts import get_first_paint_contract

        labels: list[str] = []

        def _button(label, *args, **kwargs):
            labels.append(str(label))
            return False

        load_callback = Mock(side_effect=AssertionError("Morning Cockpit load must stay button gated"))
        with patch.object(dba_control_room.st, "markdown"), patch.object(
            dba_control_room,
            "render_shell_snapshot",
        ), patch.object(dba_control_room.st, "caption"), patch.object(
            dba_control_room.st,
            "columns",
            side_effect=lambda count: [contextlib.nullcontext() for _ in range(count)],
        ), patch.object(dba_control_room.st, "button", side_effect=_button):
            dba_control_room._render_morning_cockpit_empty(load_callback)

        load_callback.assert_not_called()
        self.assertIn(get_first_paint_contract("DBA Control Room").explicit_load_cta, labels)

    def test_security_and_cost_first_paint_use_registry_contracts(self):
        security_source = (APP_ROOT / "sections" / "security_posture.py").read_text(encoding="utf-8")
        cost_source = (APP_ROOT / "sections" / "cost_contract.py").read_text(encoding="utf-8")

        self.assertIn("autoload_section_command_brief", security_source)
        self.assertIn("render_section_command_brief", security_source)
        self.assertIn('"Security Monitoring"', security_source)
        self.assertNotIn("_load_security_brief(", security_source.split("def render_security_admin_advanced", 1)[0])
        self.assertIn("autoload_section_command_brief", cost_source)
        self.assertIn("render_section_command_brief", cost_source)
        self.assertIn('"Cost & Contract"', cost_source)

    def test_docs_list_primary_command_brief_contracts(self):
        from sections.first_paint_contracts import PRIMARY_FIRST_PAINT_CONTRACTS

        docs = (ROOT / "UX_PRODUCTION_GUIDELINES.md").read_text(encoding="utf-8")
        self.assertIn("Primary Section Command Brief Contract", docs)
        for section, contract in PRIMARY_FIRST_PAINT_CONTRACTS.items():
            with self.subTest(section=section):
                self.assertIn(section, docs)
                self.assertIn(contract.default_view, docs)
                self.assertIn(contract.explicit_load_cta, docs)


if __name__ == "__main__":
    unittest.main()
