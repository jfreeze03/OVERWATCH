from pathlib import Path
from contextlib import ExitStack
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


class _Column:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class CostContractRenderingWorkflowTests(unittest.TestCase):
    def test_cost_contract_reexports_moved_rendering_evidence_alert_and_workflow_helpers(self):
        from sections import cost_contract
        from sections import cost_contract_alert_context
        from sections import cost_contract_evidence_panels
        from sections import cost_contract_overview_floor
        from sections import cost_contract_rendering
        from sections import cost_contract_workflow

        self.assertIs(cost_contract._render_cost_watch_floor, cost_contract_overview_floor._render_cost_watch_floor)
        self.assertIs(cost_contract.render_signal_confidence, cost_contract_rendering.render_signal_confidence)
        self.assertIs(cost_contract.render_operator_briefing, cost_contract_rendering.render_operator_briefing)
        self.assertIs(cost_contract.render_workflow_module, cost_contract_rendering.render_workflow_module)
        self.assertIs(cost_contract._compact_time, cost_contract_rendering._compact_time)
        self.assertIs(cost_contract._render_loaded_cost_alert_context, cost_contract_alert_context._render_loaded_cost_alert_context)
        self.assertIs(cost_contract._render_cost_spike_root_cause_board, cost_contract_evidence_panels._render_cost_spike_root_cause_board)
        self.assertIs(cost_contract._render_change_cost_correlation_board, cost_contract_evidence_panels._render_change_cost_correlation_board)
        self.assertIs(cost_contract._render_executive_value_ledger, cost_contract_evidence_panels._render_executive_value_ledger)
        self.assertIs(cost_contract._render_cost_efficiency_score_explanation, cost_contract_evidence_panels._render_cost_efficiency_score_explanation)
        self.assertIs(cost_contract._render_cost_forecast_detail, cost_contract_evidence_panels._render_cost_forecast_detail)
        self.assertIs(cost_contract._render_cost_change_correlation, cost_contract_evidence_panels._render_cost_change_correlation)
        self.assertIs(cost_contract._render_savings_verification_workflow, cost_contract_evidence_panels._render_savings_verification_workflow)
        self.assertIs(cost_contract._render_cost_command_findings, cost_contract_evidence_panels._render_cost_command_findings)
        self.assertIs(cost_contract._normalize_cost_contract_workflow_state, cost_contract_workflow._normalize_cost_contract_workflow_state)
        self.assertIs(cost_contract._apply_cost_workflow_preset, cost_contract_workflow._apply_cost_workflow_preset)
        self.assertIs(cost_contract._render_advanced_cost_tools, cost_contract_workflow._render_advanced_cost_tools)
        self.assertIs(cost_contract._render_cost_contract_workflow, cost_contract_workflow._render_cost_contract_workflow)
        self.assertIs(cost_contract._render_cost_filter_indicator, cost_contract_workflow._render_cost_filter_indicator)

    def test_signal_confidence_preserves_freshness_and_confidence_notes(self):
        from sections import cost_contract_rendering

        cases = [
            ("SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY", "allocated", "Freshness: ACCOUNT_USAGE can lag up to about 45-90 minutes", "Measurement: Allocated from warehouse metering"),
            ("OVERWATCH_MART.FACT_COST", "exact", "Freshness: fast summary refresh cadence", "Measurement: Exact"),
            ("INFORMATION_SCHEMA.TABLES", "estimated", "Freshness: live INFORMATION_SCHEMA view", "Measurement: Estimated"),
            ("unknown_source", "mystery", "Freshness: depends on source view availability", "Measurement depends on available account metadata"),
        ]
        for source, confidence, freshness, measurement in cases:
            with self.subTest(source=source, confidence=confidence):
                with patch.object(cost_contract_rendering, "defer_source_note") as note:
                    cost_contract_rendering.render_signal_confidence(
                        source=source,
                        confidence=confidence,
                        scope_note="Scoped",
                    )
                self.assertEqual(note.call_args.args, (freshness, measurement, "Scoped"))

    def test_loaded_alert_context_keeps_button_keys_and_no_query_behavior(self):
        from sections import cost_contract_alert_context

        board = pd.DataFrame([{
            "SECTION_FOCUS": "Cortex spend",
            "SEVERITY": "High",
            "SLA_STATE": "Breached",
            "CATEGORY": "Cost",
            "SIGNAL": "Cortex spike",
            "ENTITY": "USER_A",
            "OWNER": "DBA",
            "PRIORITY": 1,
            "ALERT_CENTER_VIEW": "Cost Alerts",
            "DESTINATION_SECTION": "Cost & Contract",
            "DESTINATION_WORKFLOW": "Cost by User / Role",
        }])
        button_keys: list[str] = []

        def _button(_label, *, key, width):
            button_keys.append(key)
            return False

        with (
            patch.object(cost_contract_alert_context, "build_loaded_section_alert_signal_board", return_value=board),
            patch.object(cost_contract_alert_context, "build_cost_cortex_alert_drilldown", return_value=pd.DataFrame()),
            patch.object(cost_contract_alert_context.st, "session_state", {"alert_center_data": {}}),
            patch.object(cost_contract_alert_context.st, "markdown"),
            patch.object(cost_contract_alert_context.st, "columns", return_value=[_Column(), _Column()]),
            patch.object(cost_contract_alert_context.st, "button", side_effect=_button),
            patch.object(cost_contract_alert_context, "render_shell_snapshot"),
            patch.object(cost_contract_alert_context, "render_priority_dataframe"),
            patch.object(cost_contract_alert_context, "defer_source_note") as note,
        ):
            cost_contract_alert_context._render_loaded_cost_alert_context()

        self.assertEqual(button_keys, ["cost_alert_open_alert_lane", "cost_alert_open_cost_drilldown"])
        self.assertEqual(
            note.call_args.args[0],
            "Loaded Cost and Cortex Alerts reuse Alert Center data and do not run a separate Snowflake query.",
        )

    def test_advanced_evidence_panels_keep_load_button_keys(self):
        from sections import cost_contract_evidence_panels

        button_keys: list[str] = []

        def _button(_label, *, key, width):
            button_keys.append(key)
            return False

        with (
            patch.object(cost_contract_evidence_panels.st, "button", side_effect=_button),
            patch.object(cost_contract_evidence_panels.st, "markdown"),
            patch.object(cost_contract_evidence_panels.st, "caption"),
            patch.object(cost_contract_evidence_panels.st, "session_state", {}),
            patch.object(cost_contract_evidence_panels, "load_value_ledger_rollup", return_value=pd.DataFrame()),
        ):
            cost_contract_evidence_panels._render_executive_value_ledger("ALFA", "ALL")
            cost_contract_evidence_panels._render_cost_efficiency_score_explanation("ALFA", "ALL")
            cost_contract_evidence_panels._render_cost_forecast_detail("ALFA", "ALL")
            cost_contract_evidence_panels._render_cost_change_correlation("ALFA", "ALL")
            cost_contract_evidence_panels._render_savings_verification_workflow("ALFA", "ALL")
            cost_contract_evidence_panels._render_cost_command_findings("ALFA", "ALL")

        self.assertEqual(button_keys, [
            "cost_contract_load_value_ledger_detail",
            "cost_contract_load_cost_score_drivers",
            "cost_contract_load_forecast_drivers",
            "cost_contract_load_change_correlations",
            "cost_contract_load_savings_verification",
            "cost_contract_load_command_center",
        ])

    def test_workflow_normalization_preserves_legacy_aliases_and_advanced_tool_mapping(self):
        from sections import cost_contract_workflow
        from sections.cost_contract_contracts import (
            _ADVANCED_COST_TOOLS_VISIBLE_KEY,
            _PRESERVE_COST_CENTER_VIEW_KEY,
        )

        state = {"cost_contract_workflow": "Storage Monitor"}
        with patch.object(cost_contract_workflow.st, "session_state", state):
            cost_contract_workflow._normalize_cost_contract_workflow_state()
        self.assertEqual(state["cost_contract_workflow"], "Cost Overview")
        self.assertEqual(state["cost_contract_advanced_tool"], "Storage & Retention")
        self.assertTrue(state[_ADVANCED_COST_TOOLS_VISIBLE_KEY])

        state = {"cost_contract_workflow": "Forecast"}
        with patch.object(cost_contract_workflow.st, "session_state", state):
            cost_contract_workflow._normalize_cost_contract_workflow_state()
        self.assertEqual(state["cost_contract_workflow"], "Burn Rate & Forecast")
        self.assertEqual(state["cost_center_view"], "Forecast")
        self.assertTrue(state[_PRESERVE_COST_CENTER_VIEW_KEY])

        state = {"cost_contract_workflow": "Cost by User / Role"}
        with patch.object(cost_contract_workflow.st, "session_state", state):
            cost_contract_workflow._normalize_cost_contract_workflow_state()
        self.assertEqual(state["cost_contract_workflow"], "Cost Explorer")
        self.assertEqual(state["cost_center_view"], "Cost Explorer")
        self.assertEqual(state["cc_explorer_lens"], "User / Role")
        self.assertTrue(state[_PRESERVE_COST_CENTER_VIEW_KEY])

        state = {"cost_contract_workflow": "Cortex Spend"}
        with patch.object(cost_contract_workflow.st, "session_state", state):
            cost_contract_workflow._normalize_cost_contract_workflow_state()
        self.assertEqual(state["cost_contract_workflow"], "Cortex AI")
        self.assertNotIn("cost_contract_advanced_tool", state)

    def test_workflow_dispatch_preserves_cost_overview_and_delegated_module_routing(self):
        from sections import cost_contract_workflow
        from sections.cost_contract_overview_floor import _render_cost_watch_floor

        calls: list[tuple[str, float]] = []
        cost_contract_workflow.set_cost_overview_renderer(lambda company, price: calls.append((company, price)))
        with (
            patch.object(cost_contract_workflow, "get_credit_price", return_value=4.25),
            patch.object(cost_contract_workflow, "render_workflow_module") as module_render,
            patch.object(cost_contract_workflow.st, "session_state", {}),
        ):
            cost_contract_workflow._render_cost_contract_workflow("Cost Overview", "ALFA", "ALL")
            cost_contract_workflow._render_cost_contract_workflow("Cost Recommendations", "ALFA", "ALL")

        self.assertEqual(calls, [("ALFA", 4.25)])
        module_render.assert_called_once()
        self.assertEqual(module_render.call_args.args[0], "Cost Recommendations")
        cost_contract_workflow.set_cost_overview_renderer(_render_cost_watch_floor)

    def test_cost_explorer_preset_preserves_existing_lens_widget_state(self):
        from sections import cost_contract_workflow
        from sections.cost_contract_contracts import _LAST_COST_WORKFLOW_KEY

        state = {
            _LAST_COST_WORKFLOW_KEY: "Cost Overview",
            "cost_center_view": "Cost Explorer",
            "cc_explorer_lens": "User / Role",
        }
        with patch.object(cost_contract_workflow.st, "session_state", state):
            cost_contract_workflow._apply_cost_workflow_preset("Cost Explorer")

        self.assertEqual(state["cost_center_view"], "Cost Explorer")
        self.assertEqual(state["cc_explorer_lens"], "User / Role")

    def test_cost_overview_floor_refresh_uses_existing_button_and_session_contract(self):
        from sections import cost_contract_overview_floor
        from sections.cost_contract_contracts import (
            _COST_SPLASH_AUTOLOAD_BLOCKED_SCOPE_KEY,
            _COST_SPLASH_KEY,
        )

        state = {
            "cost_contract_cockpit_window": 7,
            _COST_SPLASH_KEY: {"old": True},
            _COST_SPLASH_AUTOLOAD_BLOCKED_SCOPE_KEY: ("ALFA", 7),
        }
        button_keys: list[str] = []

        def _columns(spec):
            return [_Column() for _ in range(len(spec) if isinstance(spec, list) else spec)]

        def _button(_label, *, key, **_kwargs):
            button_keys.append(key)
            return False

        with (
            patch.object(cost_contract_overview_floor.st, "session_state", state),
            patch.object(cost_contract_overview_floor.st, "columns", side_effect=_columns),
            patch.object(cost_contract_overview_floor.st, "selectbox", return_value=7),
            patch.object(cost_contract_overview_floor.st, "button", side_effect=_button),
            patch.object(cost_contract_overview_floor, "_ensure_cost_splash", return_value={}) as ensure_splash,
            patch.object(cost_contract_overview_floor, "get_decision_evidence_target", return_value={}),
            patch.object(cost_contract_overview_floor, "render_decision_evidence_panel"),
            patch.object(cost_contract_overview_floor, "render_data_freshness"),
            patch.object(cost_contract_overview_floor, "get_session_for_action", return_value=object()) as get_session,
            patch.object(cost_contract_overview_floor, "_refresh_cost_detail_state") as refresh_detail,
            patch.object(cost_contract_overview_floor, "defer_section_note"),
        ):
            state["cost_contract_command_brief_load_evidence"] = True
            cost_contract_overview_floor._render_cost_watch_floor("ALFA", 4.0)

        self.assertNotIn("cost_contract_refresh", button_keys)
        self.assertNotIn(_COST_SPLASH_KEY, state)
        self.assertNotIn(_COST_SPLASH_AUTOLOAD_BLOCKED_SCOPE_KEY, state)
        ensure_splash.assert_called_once_with("ALFA", 7, 4.0, full_proof=True, target={})
        get_session.assert_called_once()
        refresh_detail.assert_called_once()

    def test_cost_overview_floor_first_paint_shell_does_not_autoload(self):
        from sections import cost_contract_overview_floor

        state = {"cost_contract_cockpit_window": 7}
        button_keys: list[str] = []

        def _columns(spec):
            return [_Column() for _ in range(len(spec) if isinstance(spec, list) else spec)]

        def _button(_label, *, key, **_kwargs):
            button_keys.append(key)
            return False

        with (
            patch.object(cost_contract_overview_floor.st, "session_state", state),
            patch.object(cost_contract_overview_floor.st, "columns", side_effect=_columns),
            patch.object(cost_contract_overview_floor.st, "selectbox", return_value=7),
            patch.object(cost_contract_overview_floor.st, "button", side_effect=_button),
            patch.object(
                cost_contract_overview_floor,
                "_ensure_cost_splash",
                side_effect=AssertionError("Cold Cost Overview first paint must not load cost splash"),
            ) as ensure_splash,
            patch.object(
                cost_contract_overview_floor,
                "render_section_first_paint_shell",
                side_effect=AssertionError("Cold Cost Overview first paint must not render the legacy shell"),
            ) as render_shell,
            patch.object(cost_contract_overview_floor, "render_data_freshness") as freshness,
            patch.object(
                cost_contract_overview_floor,
                "get_session_for_action",
                side_effect=AssertionError("Cold Cost Overview first paint must not request Snowflake"),
            ) as get_session,
            patch.object(cost_contract_overview_floor, "defer_section_note"),
            patch.object(
                cost_contract_overview_floor,
                "render_add_to_case_button",
                side_effect=AssertionError("Cost Add to Case should wait for loaded cost data"),
            ),
        ):
            cost_contract_overview_floor._render_cost_watch_floor("ALFA", 4.0)

        self.assertNotIn("cost_contract_refresh", button_keys)
        self.assertEqual(button_keys, [])
        ensure_splash.assert_not_called()
        get_session.assert_not_called()
        render_shell.assert_not_called()
        freshness.assert_called_once()

    def test_cost_overview_floor_advanced_detail_gate_stays_hidden_by_default(self):
        from sections import cost_contract_overview_floor
        from sections.cost_contract_contracts import _ADVANCED_COST_DETAIL_VISIBLE_KEY

        state = {
            "cost_contract_cockpit_window": 7,
            "cost_contract_command_brief_load_evidence": True,
            "cost_contract_cockpit": pd.DataFrame([{
                "CURRENT_CREDITS": 120.0,
                "PRIOR_CREDITS": 100.0,
                "TOP_INCREASE_WAREHOUSE": "COMPUTE_WH",
                "TOP_INCREASE_CREDITS": 12.0,
            }]),
            "cost_contract_cockpit_meta": {"company": "ALFA", "days": 7},
            "cost_contract_cockpit_source": "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
        }
        button_keys: list[str] = []

        def _columns(spec):
            return [_Column() for _ in range(len(spec) if isinstance(spec, list) else spec)]

        def _button(_label, *, key, **_kwargs):
            button_keys.append(key)
            return key == "cost_contract_view_advanced_details"

        with (
            patch.object(cost_contract_overview_floor.st, "session_state", state),
            patch.object(cost_contract_overview_floor.st, "columns", side_effect=_columns),
            patch.object(cost_contract_overview_floor.st, "selectbox", return_value=7),
            patch.object(cost_contract_overview_floor.st, "button", side_effect=_button),
            patch.object(cost_contract_overview_floor.st, "caption"),
            patch.object(cost_contract_overview_floor.st, "rerun") as rerun,
            patch.object(cost_contract_overview_floor, "_ensure_cost_splash", return_value={"loaded": True, "source": "Cost evidence"}),
            patch.object(cost_contract_overview_floor, "get_decision_evidence_target", return_value={}),
            patch.object(cost_contract_overview_floor, "render_decision_evidence_panel"),
            patch.object(cost_contract_overview_floor, "render_data_freshness"),
            patch.object(cost_contract_overview_floor, "get_session_for_action", return_value=object()),
            patch.object(cost_contract_overview_floor, "_refresh_cost_detail_state"),
            patch.object(cost_contract_overview_floor, "defer_section_note"),
            patch.object(cost_contract_overview_floor, "defer_source_note"),
            patch.object(cost_contract_overview_floor, "_render_cost_run_rate_lens") as run_rate_lens,
        ):
            cost_contract_overview_floor._render_cost_watch_floor("ALFA", 4.0)

        self.assertIn("cost_contract_view_advanced_details", button_keys)
        route_keys = [
            key for key in button_keys
            if key not in {"cost_contract_refresh", "cost_contract_view_advanced_details", "cost_contract_add_to_case"}
        ]
        self.assertTrue(all(key.startswith("cost_contract_command_deck_") for key in route_keys))
        self.assertTrue(state[_ADVANCED_COST_DETAIL_VISIBLE_KEY])
        rerun.assert_called_once()
        run_rate_lens.assert_not_called()

    def test_cost_refresh_key_does_not_collide_with_command_deck_routes(self):
        from sections.command_deck import _key_token
        from sections.command_deck_contracts import get_command_deck_contract

        source = (APP_ROOT / "sections" / "cost_contract.py").read_text(encoding="utf-8")
        self.assertEqual(source.count('key="cost_contract_refresh"'), 1)

        contract = get_command_deck_contract("Cost & Contract")
        route_keys = [
            f"cost_contract_command_deck_{idx}_{_key_token(action.label)}"
            for idx, action in enumerate(contract.route_actions)
        ]
        self.assertNotIn(contract.primary_cta_key, route_keys)
        self.assertEqual(len(route_keys), len(set(route_keys)))

    def test_cost_overview_floor_next_move_buttons_keep_route_key_contract(self):
        from sections import cost_contract_overview_floor
        from sections.cost_contract_contracts import _ADVANCED_COST_DETAIL_VISIBLE_KEY

        state = {
            "cost_contract_cockpit_window": 7,
            _ADVANCED_COST_DETAIL_VISIBLE_KEY: True,
            "cost_contract_cockpit": pd.DataFrame([{
                "CURRENT_CREDITS": 140.0,
                "PRIOR_CREDITS": 100.0,
                "TOP_INCREASE_WAREHOUSE": "COMPUTE_WH",
                "TOP_INCREASE_CREDITS": 15.0,
            }]),
            "cost_contract_cockpit_meta": {"company": "ALFA", "days": 7},
            "cost_contract_queue": pd.DataFrame([{
                "STATUS": "New",
                "SEVERITY": "High",
                "EST_MONTHLY_SAVINGS": 125.0,
            }]),
        }
        button_keys: list[str] = []

        def _columns(spec):
            return [_Column() for _ in range(len(spec) if isinstance(spec, list) else spec)]

        def _button(_label, *, key, **_kwargs):
            button_keys.append(key)
            return key == "cost_contract_next_0_Cost Explorer"

        with ExitStack() as stack:
            stack.enter_context(patch.object(cost_contract_overview_floor.st, "session_state", state))
            stack.enter_context(patch.object(cost_contract_overview_floor.st, "columns", side_effect=_columns))
            stack.enter_context(patch.object(cost_contract_overview_floor.st, "selectbox", return_value=7))
            stack.enter_context(patch.object(cost_contract_overview_floor.st, "button", side_effect=_button))
            stack.enter_context(patch.object(cost_contract_overview_floor.st, "caption"))
            stack.enter_context(patch.object(cost_contract_overview_floor.st, "expander", return_value=_Column()))
            stack.enter_context(patch.object(cost_contract_overview_floor.st, "markdown"))
            rerun = stack.enter_context(patch.object(cost_contract_overview_floor.st, "rerun"))
            stack.enter_context(patch.object(cost_contract_overview_floor, "_ensure_cost_splash", return_value={"loaded": True, "source": "Cost evidence"}))
            stack.enter_context(patch.object(cost_contract_overview_floor, "get_decision_evidence_target", return_value={}))
            stack.enter_context(patch.object(cost_contract_overview_floor, "render_decision_evidence_panel"))
            stack.enter_context(patch.object(cost_contract_overview_floor, "render_data_freshness"))
            stack.enter_context(patch.object(cost_contract_overview_floor, "get_session_for_action", return_value=object()))
            stack.enter_context(patch.object(cost_contract_overview_floor, "_refresh_cost_detail_state"))
            stack.enter_context(patch.object(cost_contract_overview_floor, "defer_section_note"))
            stack.enter_context(patch.object(cost_contract_overview_floor, "defer_source_note"))
            stack.enter_context(patch.object(cost_contract_overview_floor, "_loaded_cortex_state", return_value=(0.0, 0)))
            stack.enter_context(patch.object(cost_contract_overview_floor, "_render_metric_items"))
            stack.enter_context(patch.object(cost_contract_overview_floor, "_render_cost_run_rate_lens"))
            stack.enter_context(patch.object(cost_contract_overview_floor, "_render_cost_period_explanation"))
            stack.enter_context(patch.object(cost_contract_overview_floor, "_render_cost_source_health"))
            stack.enter_context(patch.object(cost_contract_overview_floor, "_render_query_attribution_gap"))
            stack.enter_context(patch.object(cost_contract_overview_floor, "_render_account_service_cost_lens"))
            stack.enter_context(patch.object(cost_contract_overview_floor, "_render_cost_advisor_board"))
            stack.enter_context(patch.object(cost_contract_overview_floor, "_render_cost_efficiency_rca"))
            stack.enter_context(patch.object(cost_contract_overview_floor, "_render_cost_spike_root_cause_board"))
            stack.enter_context(patch.object(cost_contract_overview_floor, "_render_change_cost_correlation_board"))
            stack.enter_context(patch.object(cost_contract_overview_floor, "_render_cost_monitoring_mart_and_incident_timeline"))
            stack.enter_context(patch.object(cost_contract_overview_floor, "_render_savings_closure_control"))
            stack.enter_context(patch.object(cost_contract_overview_floor, "_render_cost_control_coverage_board"))
            stack.enter_context(patch.object(cost_contract_overview_floor, "_render_cost_allocation_trust_board"))
            stack.enter_context(patch.object(cost_contract_overview_floor, "_render_cost_drilldown_command_map"))
            stack.enter_context(patch.object(cost_contract_overview_floor, "_render_cost_decomposition_board"))
            stack.enter_context(patch.object(cost_contract_overview_floor, "render_escaped_bold_text"))
            state["cost_contract_command_brief_load_evidence"] = True
            cost_contract_overview_floor._render_cost_watch_floor("ALFA", 4.0)

        self.assertIn("cost_contract_next_0_Cost Explorer", button_keys)
        self.assertEqual(state["cost_contract_workflow"], "Cost Explorer")
        self.assertEqual(state["cost_center_view"], "Cost Explorer")
        self.assertEqual(state["cc_explorer_lens"], "Warehouse")
        rerun.assert_called_once()


if __name__ == "__main__":
    unittest.main()
