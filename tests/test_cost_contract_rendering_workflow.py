from pathlib import Path
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
        from sections import cost_contract_rendering
        from sections import cost_contract_workflow

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

    def test_workflow_dispatch_preserves_cost_overview_and_delegated_module_routing(self):
        from sections import cost_contract_workflow

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


if __name__ == "__main__":
    unittest.main()
