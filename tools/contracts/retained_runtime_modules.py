"""Explicit registry for retained non-primary runtime modules.

Entries here are intentionally exact module names. Cleanup inventory must not
keep broad module families alive through prefix rules.
"""

from __future__ import annotations

from typing import Any


def _entry(
    module: str,
    *,
    category: str,
    owning_route: str,
    budget: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "module": module,
        "category": category,
        "owning_section_or_admin_route": owning_route,
        "active_button_key_or_route_key": owning_route,
        "owner": "decision_workspace",
        "reason": reason,
        "expiration_or_review_note": "Review during the next cleanup pass and delete if the named route/action is removed.",
        "runtime_budget_context": budget,
    }


_ADMIN_MODULES = (
    "sections.cost_center_action_queue",
    "sections.cost_center_attribution_view",
    "sections.cost_center_burn_view",
    "sections.cost_center_chargeback_view",
    "sections.cost_center_explain_view",
    "sections.cost_center_explorer_view",
    "sections.cost_center_forecast_view",
    "sections.cost_center_reconciliation_view",
    "sections.cost_center_user_leaderboard_view",
    "sections.dba_tools_common",
    "sections.dba_tools_cortex_limits_view",
    "sections.dba_tools_data_compare_view",
    "sections.dba_tools_query_kill_view",
    "sections.dba_tools_task_graph_control_view",
    "sections.dba_tools_warehouse_settings_view",
    "sections.pipeline_health",
    "sections.query_analysis",
    "sections.query_search",
    "sections.query_investigation_root_cause",
    "sections.recommendations",
    "sections.security_access",
    "sections.storage_monitor",
    "sections.warehouse_health",
    "sections.warehouse_health_actions",
    "sections.warehouse_health_capacity",
    "sections.warehouse_health_dataframes",
    "sections.warehouse_health_overview_panels",
    "sections.warehouse_health_panels",
    "sections.warehouse_health_queue",
    "utils.deployment",
    "utils.optimization_advisor",
)

_CONTRACT_MODULES = (
    "utils.__init__",
    "utils.alerts",
    "utils.ask_overwatch",
    "utils.command_board",
    "utils.billing_reconciliation",
    "utils.cortex",
    "utils.native_snowflake",
    "utils.recommendation_intelligence",
    "utils.scorecards",
    "utils.sql_builder",
    "utils.shared_metrics_billing",
    "sections.summary_board_contract",
    "workflow_contracts",
)


RETAINED_RUNTIME_MODULES: tuple[dict[str, Any], ...] = (
    *(
        _entry(
            module,
            category="active_admin_setup_surface",
            owning_route="Settings/Admin Setup Health or explicit advanced diagnostics",
            budget="advanced_diagnostics",
            reason="Current admin or advanced diagnostic route imports this module after an explicit user action.",
        )
        for module in _ADMIN_MODULES
    ),
    *(
        _entry(
            module,
            category="active_contract_runtime",
            owning_route="current route/button/static contract suite",
            budget="contract_scan",
            reason="Current Decision Workspace contract tests import this runtime helper to protect active behavior.",
        )
        for module in _CONTRACT_MODULES
    ),
)


RETAINED_RUNTIME_MODULE_BY_NAME = {
    str(entry["module"]): dict(entry)
    for entry in RETAINED_RUNTIME_MODULES
}


__all__ = ["RETAINED_RUNTIME_MODULES", "RETAINED_RUNTIME_MODULE_BY_NAME"]
