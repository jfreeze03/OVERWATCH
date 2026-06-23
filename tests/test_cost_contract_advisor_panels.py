from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


class CostContractAdvisorPanelTests(unittest.TestCase):
    def test_cost_contract_reexports_moved_advisor_panel_helpers(self):
        from sections import cost_contract
        from sections import cost_contract_advisor_panels

        self.assertIs(cost_contract._render_savings_closure_control, cost_contract_advisor_panels._render_savings_closure_control)
        self.assertIs(cost_contract._render_cost_advisor_detail, cost_contract_advisor_panels._render_cost_advisor_detail)
        self.assertIs(cost_contract._render_cost_advisor_board, cost_contract_advisor_panels._render_cost_advisor_board)
        self.assertIs(cost_contract._render_account_service_cost_lens, cost_contract_advisor_panels._render_account_service_cost_lens)
        self.assertIs(cost_contract._render_cost_efficiency_rca, cost_contract_advisor_panels._render_cost_efficiency_rca)

    def test_savings_closure_control_uses_closure_analytics_and_priority_columns(self):
        from sections import cost_contract_advisor_panels

        summary = {
            "cost_actions": 2,
            "open_estimated_monthly_savings": 100.0,
            "blocked_estimated_monthly_savings": 25.0,
            "verified_period_delta_dollars": 40.0,
            "audit_ready_pct": 50.0,
        }
        detail = pd.DataFrame([{
            "SEVERITY": "High",
            "CLOSURE_STATE": "Open cost action",
            "CATEGORY": "Cost",
            "ENTITY_NAME": "COMPUTE_WH",
            "OWNER": "DBA",
        }])

        with (
            patch.object(cost_contract_advisor_panels, "_build_cost_closure_analytics", return_value=(summary, detail)) as analytics,
            patch.object(cost_contract_advisor_panels.st, "markdown"),
            patch.object(cost_contract_advisor_panels, "defer_source_note"),
            patch.object(cost_contract_advisor_panels, "render_shell_snapshot"),
            patch.object(cost_contract_advisor_panels, "render_priority_dataframe") as table,
        ):
            cost_contract_advisor_panels._render_savings_closure_control(pd.DataFrame({"CATEGORY": ["Cost"]}), 4.0)

        analytics.assert_called_once()
        self.assertEqual(table.call_args.kwargs["title"], "Cost actions that still need review, telemetry, or closure status")
        self.assertEqual(table.call_args.kwargs["priority_columns"], [
            "SEVERITY", "CLOSURE_STATE", "CATEGORY", "ENTITY_NAME", "OWNER",
            "OWNER_EMAIL", "ONCALL_PRIMARY", "APPROVAL_GROUP", "OWNER_SOURCE",
            "STATUS", "OWNER_APPROVAL_STATUS", "TELEMETRY_STATUS",
            "BASELINE_VALUE", "CURRENT_VALUE", "MEASURED_DELTA",
            "MEASURED_IMPACT_DOLLARS", "RECOVERY_SLA_STATE",
            "IMPACT_EVIDENCE", "TICKET_ID", "APPROVER",
        ])

    def test_cost_advisor_detail_keeps_select_and_route_button_keys(self):
        from sections import cost_contract_advisor_panels

        options = pd.DataFrame([{
            "DETAIL_LABEL": "High | Review right-size or suspend policy | COMPUTE_WH",
            "SEVERITY": "High",
            "ACTION_TYPE": "Review right-size or suspend policy",
            "WORKFLOW_ROUTE": "Cost by Warehouse",
            "PRIMARY_METRIC": "$100/mo savings",
            "TELEMETRY_SUMMARY": "Warehouse pressure telemetry",
            "SAFE_NEXT_ACTION": "Review suspend policy.",
            "VALIDATION_NEEDED": "Confirm complete-day metering.",
        }])
        state = {}

        def _selectbox(label, options_arg, *, key):
            self.assertEqual(label, "Advisor finding")
            self.assertEqual(key, "cost_advisor_detail_select")
            self.assertEqual(options_arg, options["DETAIL_LABEL"].tolist())
            return options_arg[0]

        def _button(label, *, key, width):
            self.assertEqual(label, "Open Cost by Warehouse")
            self.assertEqual(key, "cost_advisor_detail_route")
            self.assertEqual(width, "stretch")
            return False

        with (
            patch.object(cost_contract_advisor_panels, "_cost_advisor_detail_options", return_value=options),
            patch.object(cost_contract_advisor_panels.st, "session_state", state),
            patch.object(cost_contract_advisor_panels.st, "markdown"),
            patch.object(cost_contract_advisor_panels.st, "caption"),
            patch.object(cost_contract_advisor_panels.st, "selectbox", side_effect=_selectbox),
            patch.object(cost_contract_advisor_panels.st, "button", side_effect=_button),
            patch.object(cost_contract_advisor_panels, "render_shell_snapshot"),
            patch.object(cost_contract_advisor_panels, "render_escaped_labeled_text"),
        ):
            cost_contract_advisor_panels._render_cost_advisor_detail(Mock())

        self.assertEqual(state, {})


if __name__ == "__main__":
    unittest.main()
