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

    def test_command_deck_contracts_cover_primary_sections_and_stay_import_safe(self):
        from route_registry import PRIMARY_SECTION_TITLES
        from sections.command_deck_contracts import COMMAND_DECK_CONTRACTS

        self.assertEqual(tuple(COMMAND_DECK_CONTRACTS), PRIMARY_SECTION_TITLES)
        source = (APP_ROOT / "sections" / "command_deck_contracts.py").read_text(encoding="utf-8")
        self.assertNotIn("import streamlit", source)
        self.assertNotIn("SNOWFLAKE", source)
        self.assertNotRegex(source, r"\brun_query(?:_or_raise)?\s*\(")

        for section, contract in COMMAND_DECK_CONTRACTS.items():
            with self.subTest(section=section):
                self.assertEqual(contract.section, section)
                self.assertTrue(contract.primary_cta)
                self.assertTrue(contract.primary_cta_key)
                self.assertIn(contract.primary_cta_behavior, {"existing_button", "route_only", "callback"})
                self.assertTrue(contract.primary_cta_description)
                self.assertTrue(contract.primary_cta_preserve_existing)
                self.assertGreaterEqual(len(contract.route_actions), 2)
                self.assertTrue(contract.evidence_boundary)
                self.assertTrue(contract.no_query_note)
                for action in contract.route_actions:
                    self.assertTrue(action.label)
                    self.assertTrue(action.description)
                    self.assertTrue(
                        action.target_section or action.target_workflow or action.session_state_updates
                    )

    def test_command_deck_renderer_does_not_load_when_route_buttons_are_idle(self):
        from sections import command_deck
        from sections.command_deck_contracts import COMMAND_DECK_CONTRACTS

        with patch.object(command_deck.st, "container", return_value=contextlib.nullcontext()), patch.object(
            command_deck.st,
            "columns",
            side_effect=lambda count: [contextlib.nullcontext() for _ in range(count)],
        ), patch.object(
            command_deck,
            "safe_caption",
        ), patch.object(command_deck, "safe_button", return_value=False) as safe_button, patch.object(
            command_deck.st,
            "rerun",
            side_effect=AssertionError("idle command deck must not rerun"),
        ), patch.object(command_deck, "render_case_drawer"):
            for section, contract in COMMAND_DECK_CONTRACTS.items():
                with self.subTest(section=section):
                    command_deck.render_command_deck(
                        contract,
                        key_prefix=f"test_{section.lower().replace(' ', '_')}_command_deck",
                    )

        self.assertGreaterEqual(safe_button.call_count, 12)

    def test_command_deck_renderer_has_no_query_loader_imports(self):
        source = (APP_ROOT / "sections" / "command_deck.py").read_text(encoding="utf-8")

        self.assertNotRegex(source, r"\brun_query(?:_or_raise)?\b")
        self.assertNotRegex(source, r"\bget_session(?:_for_action)?\b")
        self.assertNotIn("load_latest_control_room_mart", source)
        self.assertIn("from sections.ui_compat import safe_button, safe_caption", source)

    def test_command_deck_route_keys_are_unique_and_do_not_shadow_primary_cta_keys(self):
        from sections.command_deck import _key_token
        from sections.command_deck_contracts import COMMAND_DECK_CONTRACTS

        for section, contract in COMMAND_DECK_CONTRACTS.items():
            with self.subTest(section=section):
                prefix = f"command_deck_{_key_token(contract.section)}"
                route_keys = [
                    f"{prefix}_{idx}_{_key_token(action.label)}"
                    for idx, action in enumerate(contract.route_actions)
                ]
                self.assertEqual(len(route_keys), len(set(route_keys)))
                self.assertNotIn(contract.primary_cta_key, route_keys)

    def test_command_deck_html_escapes_header_and_action_copy(self):
        from sections import command_deck
        from sections.command_deck_contracts import CommandDeckAction, SectionCommandDeckContract

        contract = SectionCommandDeckContract(
            section="<script>alert(1)</script>",
            primary_cta="<b>Load</b>",
            primary_cta_key="safe_primary",
            route_actions=(),
            advanced_label="",
            evidence_boundary="<img src=x onerror=alert(1)>",
            no_query_note="Entry",
        )
        action = CommandDeckAction(
            label="<b>Route</b>",
            description="<svg onload=alert(1)>",
            target_workflow="Route",
        )
        with patch.object(command_deck.st, "html") as html:
            command_deck._render_deck_header(contract)
            command_deck._render_action_context(action)

        markup = "\n".join(call.args[0] for call in html.call_args_list)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", markup)
        self.assertIn("&lt;b&gt;Load&lt;/b&gt;", markup)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", markup)
        self.assertIn("&lt;b&gt;Route&lt;/b&gt;", markup)
        self.assertIn("&lt;svg onload=alert(1)&gt;", markup)
        self.assertNotIn("<script>", markup)
        self.assertNotIn("<img src=x", markup)
        self.assertNotIn("<svg onload", markup)

    def test_command_deck_primary_cta_is_callback_only(self):
        from sections import command_deck
        from sections.command_deck_contracts import get_command_deck_contract

        primary_callback = Mock()
        with patch.object(command_deck.st, "container", return_value=contextlib.nullcontext()), patch.object(
            command_deck.st,
            "columns",
            side_effect=lambda count: [contextlib.nullcontext() for _ in range(count)],
        ), patch.object(
            command_deck,
            "safe_caption",
        ), patch.object(command_deck, "safe_button", side_effect=lambda label, **kwargs: label == "Load Active Alerts"), patch.object(
            command_deck.st,
            "rerun",
            side_effect=AssertionError("primary CTA callback should not force a rerun"),
        ), patch.object(command_deck, "render_case_drawer"):
            command_deck.render_command_deck(
                get_command_deck_contract("Alert Center"),
                key_prefix="test_alert_command_deck",
                on_primary_cta=primary_callback,
            )

        primary_callback.assert_called_once()

    def test_command_deck_route_button_only_sets_state_and_reruns(self):
        from sections import command_deck
        from sections.command_deck_contracts import get_command_deck_contract

        with patch.object(command_deck.st, "container", return_value=contextlib.nullcontext()), patch.object(
            command_deck.st,
            "columns",
            side_effect=lambda count: [contextlib.nullcontext() for _ in range(count)],
        ), patch.object(
            command_deck,
            "safe_caption",
        ), patch.object(
            command_deck,
            "safe_button",
            side_effect=lambda label, **kwargs: label == "Task or load failure",
        ), patch.object(command_deck, "apply_command_deck_action") as apply_action, patch.object(
            command_deck.st,
            "rerun",
        ) as rerun, patch.object(command_deck, "render_case_drawer"):
            command_deck.render_command_deck(
                get_command_deck_contract("Workload Operations"),
                key_prefix="test_workload_command_deck",
            )

        apply_action.assert_called_once()
        self.assertEqual(apply_action.call_args.args[0].label, "Task or load failure")
        rerun.assert_called_once()

    def test_command_deck_action_only_sets_routing_state(self):
        from sections.command_deck import apply_command_deck_action
        from sections.command_deck_contracts import get_command_deck_contract

        state: dict[str, object] = {}
        contract = get_command_deck_contract("Workload Operations")
        action = next(item for item in contract.route_actions if item.label == "Task or load failure")

        apply_command_deck_action(action, state)

        self.assertEqual(state["workload_operations_workflow"], "Pipeline & Task Health")
        self.assertEqual(state["workload_pipeline_focus"], "Failed Tasks")
        self.assertEqual(set(state), {"workload_operations_workflow", "workload_pipeline_focus"})

    def test_command_deck_cross_section_updates_win_after_default_navigation(self):
        from sections import command_deck
        from sections.command_deck_contracts import get_command_deck_contract

        state: dict[str, object] = {}
        contract = get_command_deck_contract("Executive Landing")
        action = next(item for item in contract.route_actions if item.label == "Cortex AI Cost")

        def _default_navigation(_section: str) -> None:
            state["cost_contract_workflow"] = "Cost Overview"

        with patch.object(command_deck, "queue_section_navigation", side_effect=_default_navigation):
            command_deck.apply_command_deck_action(action, state)

        self.assertEqual(state["cost_contract_workflow"], "Cortex AI")

    def test_command_deck_preserves_benchmark_load_boundaries(self):
        from sections.command_deck_contracts import get_command_deck_contract

        expected = {
            "Executive Landing": ("Refresh Decision Brief", "executive_landing_observability_refresh"),
            "Alert Center": ("Load Active Alerts", "alert_center_load"),
            "Cost & Contract": ("Refresh Cost", "cost_contract_refresh"),
            "Security Monitoring": ("Refresh Security Summary", "security_posture_brief_load"),
            "DBA Control Room": ("Load Morning Cockpit", "dba_morning_cockpit_load_empty"),
        }
        for section, (label, key) in expected.items():
            with self.subTest(section=section):
                contract = get_command_deck_contract(section)
                self.assertEqual(contract.primary_cta, label)
                self.assertEqual(contract.primary_cta_key, key)

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

        autoload.assert_called_once_with("Workload Operations", "ALFA", "PROD", 7)
        render_brief.assert_called_once_with("brief", key_prefix="workload_operations_command_brief")

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
